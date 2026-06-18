# Care Art - Test Strategy: Phase 2

> **Status:** Phase 2 draft. Covers the five entities defined in Section 3.8–3.12 of the architecture document: CarePlan, Appointment, MedicationRefill, Reminder, and Consent. CarePlan includes a dependent sub-entity `care_plan_goal` (Section 3.8.4) whose table definition and constraints are complete in Phase 2; tests for `care_plan_goal` are deferred to Phase 3. This document describes strategy and approach only — individual test cases are tracked separately.
> **Regulatory scope:** HIPAA · 42 CFR Part 2 · CMS (Medicaid/Medicare) · HL7 FHIR R4 · NCPDP SCRIPT · State adult day care licensing

---

## 1. Scope

### 1.1 What This Strategy Covers

This strategy governs test planning for the Phase 2 mock backend expansion. Coverage is bounded to the five entities defined in the Phase 2 data model: CarePlan, Appointment, MedicationRefill, Reminder, and Consent. The 52 requirements in `requirements_phase1.xlsx` (Phase 2 Requirements sheet, REQ_7.1 through REQ_11.10) are the authoritative source of acceptance criteria.

The mock backend remains the sole target. Tests run against the same local SQLite database used by Phase 1, standing in for the production PostgreSQL RDS instance. All test infrastructure is self-contained and requires no external network access. Phase 1 tests (REQ_1.x through REQ_6.x) must continue to pass at all times — no Phase 2 change may break a Phase 1 gate test.

### 1.2 Phase 2 Entity Inventory

| Entity | Section | Primary Regulatory Obligation | Req Count |
|---|---|---|---|
| CarePlan | 3.8 | HIPAA · 42 CFR Part 2 (via Participant.is_sud_record) · State licensing · CMS | 11 |
| Appointment | 3.9 | HIPAA · 42 CFR Part 2 (via Participant.is_sud_record) · HL7 FHIR R4 | 10 |
| MedicationRefill | 3.10 | HIPAA · 42 CFR Part 2 (via is_controlled_substance) · HL7 FHIR R4 · NCPDP SCRIPT | 11 |
| Reminder | 3.11 | HIPAA · No-PHI-in-payload rule (Section 2.4) · 42 CFR Part 2 SUD delivery gate | 10 |
| Consent | 3.12 | 42 CFR Part 2 §2.31 · HIPAA | 10 |

### 1.3 Out of Scope for Phase 2

The following are explicitly excluded and will be addressed in a separate Phase 3 test strategy:

- `care_plan_goal` functional tests (table and constraints defined in Phase 2 Section 3.8.4; tests deferred to Phase 3 per architecture §3.7.1)
- Care team member assignments beyond the primary care coordinator (CarePlan Phase 3 scope)
- Individual goal progress audit rows (CarePlan Phase 3 scope)
- Reminder module integration for goal-based alerts (CarePlan Phase 3 scope)
- Automated reminder generation triggered by appointment scheduling events (Reminder Phase 3 scope)
- SMS and email channel delivery for Reminder (`channel` restricted to `push` in Phase 2 per §3.11.3)
- Transport entity and `reminder_type = 'transport'` records (deferred to Phase 3 per §3.11.7)
- Referral tracking details and transport coordination for Appointment (Phase 3 scope)
- Pharmacy claims linkage, formulary checks, and prior authorization workflows for MedicationRefill (Phase 3 scope)
- Multi-recipient batch consent, re-disclosure prohibition tracking, and external consent management platform integration (Consent Phase 3 scope)
- Event-driven consent expiration trigger (Phase 3 replaces the cron job per §3.12.3)
- Secondary payer coordination of benefits (COB) and MCO fields on Claim (Phase 2 deferred fields per §3.4.7)
- PRN and recurring schedule MAR workflows (Phase 2 deferred per §3.5)
- FHIR R4 round-trip integration with physician EHR systems and pharmacy systems (consent gate logic is tested; actual FHIR transmission is infrastructure)
- NCPDP SCRIPT round-trip integration with pharmacy systems
- Production infrastructure: PostgreSQL RDS, pgaudit extension, CloudWatch, S3 WORM
- Load, stress, and performance benchmarking
- Third-party penetration testing

---

## 2. Risk-Based Prioritization

### 2.1 Entity Risk Ranking

Entities are ranked by the combination of patient safety risk, regulatory penalty exposure, and the number of high-severity requirement types (42 CFR Part 2, Audit Logging, State Machine, Consent Gate) they carry.

| Rank | Entity | Risk Driver | Risk Level |
|---|---|---|---|
| 1 | Consent | Regulatory core of 42 CFR Part 2 disclosure framework — every outbound SUD disclosure blocked without active consent — withdrawal immediate and irrevocable — consent gate referenced by all four other Phase 2 entities | Critical |
| 2 | MedicationRefill | Controlled substance refills under 42 CFR Part 2 — pharmacy consent gate — duplicate in-flight prevention for controlled substance inventory — partial immutability after fulfillment | Critical |
| 3 | CarePlan | Central clinical artifact — physician signature gate — single-active-plan enforcement — SUD access controls inherited from Participant.is_sud_record — FHIR consent gate for EHR disclosure | High |
| 4 | Appointment | Physician overlap interval constraint with SQLite trigger backstop — SUD access controls — FHIR consent gate — partial immutability after completion | High |
| 5 | Reminder | No-PHI-in-payload rule — SUD delivery gate — push channel restriction — lower PHI exposure than clinical entities | Medium |

The ranking determines test authoring and execution order, not whether an entity is tested. All entities reach full coverage before release.

### 2.2 Requirement Type Risk Ranking

| Rank | Requirement Type | Regulatory Basis | Failure Consequence |
|---|---|---|---|
| 1 | 42 CFR Part 2 | 42 CFR Part 2 §2.13(b) · §2.31 · §2.16 | Prohibited SUD disclosure — civil and criminal penalties — consent gate bypass |
| 2 | Audit Logging | HIPAA §164.312(b) · SOC 2 CC7.2 · 42 CFR Part 2 §2.16 | HIPAA breach finding — SOC 2 audit failure — undetectable disclosure |
| 3 | Unique Constraint | HIPAA §164.312(b) · CMS billing integrity | Duplicate care plans — overlapping appointments — duplicate refill transmissions |
| 4 | State Machine | State licensing · CMS · HIPAA §164.530(j) | Invalid clinical artifacts — terminal state reversal — consent lifecycle bypass |
| 5 | RBAC | HIPAA §164.312(a)(1) | Unauthorized PHI access or modification — SUD record exposure to non-privileged roles |
| 6 | Business Rule | CMS · State licensing · 42 CFR Part 2 §2.31 | Consent gate bypass — fulfilled refill tampering — completed appointment revision — PHI in push payload |
| 7 | Field Validation | HIPAA minimum necessary · State licensing · 42 CFR Part 2 §2.31(a)(8) | Invalid consent dates — PHI in notification payload — zero-quantity refill — null effective_date activation |
| 8 | Data Integrity | HIPAA §164.312(b) | Concurrent-edit data loss — optimistic locking bypass |

### 2.3 Cross-Cutting Controls

Four controls cut across all five Phase 2 entities and are treated as blocking gates regardless of entity rank:

- **Soft delete only** (is_deleted flag — hard delete blocked): CarePlan (REQ_7.10), Appointment (REQ_8.10), MedicationRefill (REQ_9.11), Reminder (REQ_10.9), Consent (REQ_11.10)
- **Audit log completeness** (mandatory fields, PHI values never in payload): SUD-flagged care plans (REQ_7.7), SUD-flagged appointments (REQ_8.8), controlled substance refills (REQ_9.9), consent lifecycle events (REQ_11.9)
- **42 CFR Part 2 access gate**: CarePlan via Participant.is_sud_record (REQ_7.6), Appointment via Participant.is_sud_record (REQ_8.7), MedicationRefill via is_controlled_substance (REQ_9.8), Reminder SUD delivery gate (REQ_10.8), Consent disclosure gate (REQ_11.7)
- **Consent gate for external disclosure**: CarePlan FHIR (REQ_7.8), Appointment FHIR (REQ_8.9), MedicationRefill pharmacy (REQ_9.10), Reminder push delivery (REQ_10.8)

---

## 3. Test Layers

### 3.1 Overview

The same three test layers from Phase 1 apply to Phase 2. Each layer has a defined purpose, tool, and scope boundary. No layer substitutes for another — all three must pass.

| Layer | Target | Primary Verification | Tool |
|---|---|---|---|
| API | HTTP endpoints | Status codes · response shape · error codes · headers | Playwright (Python) via `request` context |
| Database | SQLite schema and data | Constraint enforcement · index presence · trigger enforcement · field-level rules · soft delete | pytest + sqlite3 direct queries |
| Business Rules | Cross-layer logic | State machine transitions · consent gate logic · immutability rules · overlap detection · workflow sequencing | pytest calling API + asserting DB state |

### 3.2 API Layer

The API layer tests every HTTP surface of the Phase 2 mock backend endpoints. It does not query the database directly — it treats the API as the system under test and verifies observable behaviour through responses.

Responsibilities of this layer:

- Correct HTTP status codes for happy path and error conditions (200, 201, 400, 403, 404, 409, 422)
- Correct error code strings in response bodies (for example CARE_PLAN_DUPLICATE_VERSION, APPOINTMENT_PHYSICIAN_OVERLAP, REFILL_DUPLICATE_IN_FLIGHT, REMINDER_PHI_IN_PAYLOAD, CONSENT_DUPLICATE_ACTIVE)
- Response body shape conformance: required fields present, forbidden fields absent, PHI values absent from error responses
- 42 CFR Part 2 field redaction: is_controlled_substance absent from non-privileged responses (MedicationRefill), care_plan_goal rows and notes redacted for unauthorized roles (CarePlan), appointment_type/result_notes/cancellation_reason/follow_up_required redacted for unauthorized roles (Appointment), medication_name/dose/route/is_controlled_substance/denial_reason/ncpdp_script_reference redacted for unauthorized roles (MedicationRefill)
- Consent gate denial: 403 with no record existence disclosure for unauthorized role requests on SUD-flagged records
- Phase 2 channel restriction: channel values other than `push` rejected on Reminder (REQ_10.10); `reminder_type = 'transport'` rejected (REQ_10.2)

This layer does not verify that a database constraint fired — it verifies that the application returned the correct client-visible outcome.

### 3.3 Database Layer

The database layer bypasses the application and queries SQLite directly to verify that schema-level constraints exist and data invariants hold. This layer is the backstop that confirms the application cannot accidentally bypass a constraint.

Responsibilities of this layer:

- UNIQUE index presence on all constrained field combinations (for example tenant_id + participant_id + version_number on CarePlan, tenant_id + participant_id + physician_id + scheduled_start on Appointment, tenant_id + participant_id + medication_name + requested_at on MedicationRefill, tenant_id + participant_id + reminder_type + scheduled_for on Reminder)
- Partial unique index presence where applicable (for example tenant_id + participant_id WHERE status = 'active' on CarePlan, tenant_id + participant_id + disclosure_recipient_type WHERE status = 'active' on Consent, tenant_id + participant_id + medication_name WHERE status NOT IN ('fulfilled', 'denied', 'cancelled') on MedicationRefill, tenant_id + participant_id + reminder_type WHERE status = 'scheduled' on Reminder)
- SQLite trigger presence and enforcement on Appointment: trg_appointment_physician_no_overlap_insert and trg_appointment_physician_no_overlap_update — direct SQL INSERT and UPDATE that would create overlapping windows raise OperationalError with message 'overlapping appointment for this physician' and commit no row (REQ_8.2)
- NOT NULL constraints on mandatory fields
- Soft delete: is_deleted defaults to false and no hard-delete path removes a row — all five entities
- Version column exists on all five entity tables and care_plan_goal; increments on every write
- Audit log table: mandatory fields present and non-null after any PHI operation involving SUD-flagged records or controlled substance records; consent lifecycle audit events (CONSENT_CREATED, CONSENT_WITHDRAWN, CONSENT_EXPIRED) contain required fields; scope_description never appears in consent audit log payloads; `PHI_PAYLOAD_BLOCKED` audit event emitted when the push notification adapter pre-send PHI check fails — no payload content captured in the audit log
- PHI field values absent from audit log rows

### 3.4 Business Rules Layer

The business rules layer orchestrates multi-step scenarios that cannot be verified by a single API call or a single database query. It calls the API, observes the state transitions, and then asserts both the API response and the resulting database state.

Responsibilities of this layer:

- **CarePlan state machine**: draft → active (requires non-null physician_id, physician_signature_date, and effective_date); active → superseded (when new version activated); archived terminal; at most one active plan per participant (REQ_7.2, REQ_7.3, REQ_7.11)
- **CarePlan revision workflow**: clinical field change on active plan requires new version + supersession in single transaction; in-place updates limited to review_date and notes (REQ_7.4)
- **CarePlan care_coordinator_id immutability**: care_coordinator_id cannot change on an active plan (REQ_7.5)
- **Appointment overlap detection**: physician interval overlap check on POST and PATCH; cancelled/no_show excluded; boundary-exact (scheduled_end = next scheduled_start) is permitted; self-exclusion on reschedule (REQ_8.2)
- **Appointment completed partial immutability**: scheduled_start, physician_id, appointment_type immutable after completion; result_notes, fhir_result_reference, follow_up_required mutable; mixed body rejected in full (REQ_8.4)
- **Appointment status state machine**: scheduled → completed/cancelled/no_show; all terminal; cancelled requires cancellation_reason (REQ_8.3, REQ_8.5)
- **MedicationRefill in-flight uniqueness**: one open refill per medication per participant; restriction lifts on terminal status (REQ_9.2)
- **MedicationRefill fulfilled partial immutability**: medication_name, dose, route, quantity_requested immutable after fulfillment; fulfilled_at, ncpdp_script_reference mutable; mixed body rejected in full (REQ_9.5)
- **MedicationRefill status state machine**: requested → sent_to_pharmacy → processing → fulfilled/denied; cancelled from any non-terminal; denied requires denial_reason; cancelled requires cancellation_reason (REQ_9.4, REQ_9.6)
- **Reminder sent immutability**: title, body, deep_link_path, channel, scheduled_for immutable once status leaves scheduled; failure_reason writable only when status = failed (REQ_10.5)
- **Reminder in-flight uniqueness**: one scheduled reminder per type per participant; restriction lifts on any non-scheduled status (REQ_10.2)
- **Reminder PHI-in-payload check**: title and body containing participant name, diagnosis code, medication name, or any HIPAA identifier rejected with REMINDER_PHI_IN_PAYLOAD at the application layer on every POST and PATCH; the push notification adapter additionally validates the final composed payload against the same PHI pattern set immediately before submission to APNs or FCM — a payload that fails the adapter pre-send check is held in `status = 'scheduled'`, the delivery attempt is aborted, and a `PHI_PAYLOAD_BLOCKED` audit event is emitted (REQ_10.3)
- **Consent active uniqueness**: one active consent per disclosure_recipient_type per participant; restriction lifts on withdrawn/expired (REQ_11.1)
- **Consent withdrawal**: no withdrawal_reason required; withdrawn_at set immediately; subsequent disclosure gate queries return no qualifying record (REQ_11.5)
- **Consent expiration cron**: background job transitions active consents past expiration_date to expired; audit event CONSENT_EXPIRED emitted (REQ_11.6)
- **Consent withdrawn/expired immutability**: any PATCH rejected with CONSENT_WITHDRAWN_IMMUTABLE (REQ_11.4)
- **Disclosure gate (5-condition check)**: Participant.is_sud_record = true, matching consent exists, status = active, effective_date ≤ today, expiration_date > today — all five conditions checked at disclosure time; any failure blocks disclosure (REQ_11.7)
- **FHIR consent gate — CarePlan**: active ehr consent required before FHIR CarePlan transmission for SUD participant; missing/expired consent blocks and emits CONSENT_CHECK DENIED (REQ_7.8)
- **FHIR consent gate — Appointment**: active ehr consent required before FHIR Appointment transmission for SUD participant (REQ_8.9)
- **Pharmacy consent gate — MedicationRefill**: active pharmacy consent required before FHIR MedicationRequest / NCPDP SCRIPT transmission when is_controlled_substance = true and Participant.is_sud_record = true (REQ_9.10)
- **SUD delivery gate — Reminder**: active push_notification consent required before APNs/FCM delivery when Participant.is_sud_record = true and reference_entity_type ≠ none; missing consent holds status = scheduled and emits SUD_DELIVERY_GATE SUPPRESSED (REQ_10.8)
- **42 CFR Part 2 role gate**: access denied for disallowed roles on SUD-flagged CarePlan/Appointment records; access denied for disallowed roles on is_controlled_substance MedicationRefill records (REQ_7.6, REQ_8.7, REQ_9.8)
- **RBAC — entity-specific**: nurse_medication_aide SUD-only access on Appointment (REQ_8.6); care_coordinator controlled-substance-only access on MedicationRefill (REQ_9.7); participant_family self-only read on Reminder (REQ_10.7); care_coordinator and compliance_officer only on Consent (REQ_11.8)

---

## 4. Test Types

### 4.1 Functional Tests

Functional tests verify that the system does what the requirements say it must do when inputs are valid. They follow happy-path flows and the immediate variations defined in each requirement's acceptance criteria.

Coverage map:

| Requirement Type | Functional Test Focus |
|---|---|
| State Machine | Every allowed transition for each entity — automatic supersession on CarePlan activation (REQ_7.2) — terminal state enforcement on Appointment, MedicationRefill, Consent (REQ_8.3, REQ_9.4, REQ_11.4) |
| Field Validation | Mandatory field presence — enum range (channel, reminder_type, disclosure_recipient_type, appointment_type, route) — date and timestamp constraints (effective_date before active per REQ_7.11, expiration_date after effective_date per REQ_11.2, scheduled_for future-only per REQ_10.4, quantity_requested positive per REQ_9.3) — consent_form_reference non-empty (REQ_11.3) |
| Business Rule | Consent gate logic at disclosure time (REQ_11.7) — SUD delivery gate (REQ_10.8) — PHI-in-payload detection (REQ_10.3) — physician overlap detection (REQ_8.2) — in-flight uniqueness (REQ_9.2, REQ_10.2) — partial immutability after terminal status (REQ_8.4, REQ_9.5, REQ_10.5) — cancellation/denial reason requirements (REQ_8.5, REQ_9.6, REQ_10.6) — consent expiration cron (REQ_11.6) — withdrawal without reason (REQ_11.5) |
| RBAC | Each permitted role can perform its allowed operations successfully — entity-specific role gates confirmed (REQ_7.5, REQ_8.6, REQ_9.7, REQ_10.7, REQ_11.8) |

Functional tests do not assert security controls — that is the responsibility of the security test type.

### 4.2 Data Integrity Tests

Data integrity tests verify that uniqueness, referential, and concurrency constraints prevent corrupt state from entering the system, both through the application layer and directly at the database layer.

Coverage map:

| Constraint | Entity | Error Code | REQ_ID |
|---|---|---|---|
| participant_id + version_number per tenant | CarePlan | CARE_PLAN_DUPLICATE_VERSION | REQ_7.1 |
| Single active plan per participant (partial index) | CarePlan | CARE_PLAN_ALREADY_ACTIVE | REQ_7.2 |
| care_plan_id + domain + description per care plan | care_plan_goal | CARE_PLAN_GOAL_DUPLICATE | REQ_7.9 |
| participant_id + physician_id + scheduled_start per tenant | Appointment | APPOINTMENT_DUPLICATE | REQ_8.1 |
| Physician interval overlap (application + SQLite triggers) | Appointment | APPOINTMENT_PHYSICIAN_OVERLAP | REQ_8.2 |
| participant_id + medication_name + requested_at per tenant | MedicationRefill | REFILL_DUPLICATE | REQ_9.1 |
| One open refill per medication per participant (partial index) | MedicationRefill | REFILL_DUPLICATE_IN_FLIGHT | REQ_9.2 |
| participant_id + reminder_type + scheduled_for per tenant | Reminder | REMINDER_DUPLICATE | REQ_10.1 |
| One scheduled reminder per type per participant (partial index) | Reminder | REMINDER_DUPLICATE_SCHEDULED | REQ_10.2 |
| One active consent per disclosure_recipient_type per participant (partial index) | Consent | CONSENT_DUPLICATE_ACTIVE | REQ_11.1 |

Each constraint is tested twice: once at the API layer (verify the 409 and error code) and once at the DB layer (verify the UNIQUE index or partial index fires independently). The Appointment physician overlap constraint is additionally tested via direct SQL INSERT and UPDATE to confirm the SQLite triggers fire independently of the application layer (REQ_8.2).

### 4.3 Security Tests

Security tests verify that access controls prevent unauthorised operations and that sensitive data is never exposed through error messages or audit logs.

Coverage areas:

- **RBAC — CarePlan**: billing_specialist, participant_family, and program_administrator denied write; care_coordinator is the sole write role; nurse_medication_aide and compliance_officer read-only; care_coordinator_id immutable on active plan (REQ_7.5)
- **RBAC — Appointment**: participant_family and billing_specialist denied all access; care_coordinator write; physician read; nurse_medication_aide access only for SUD-flagged participant appointments — denied for non-SUD (REQ_8.6)
- **RBAC — MedicationRefill**: billing_specialist, physician, participant_family, and program_administrator denied all access; nurse_medication_aide write; care_coordinator access only for is_controlled_substance = true records — denied for non-controlled (REQ_9.7)
- **RBAC — Reminder**: participant_family and nurse_medication_aide denied write; care_coordinator write; participant_family read limited to records where recipient_user_id matches their own user_id; billing_specialist denied all access (REQ_10.7)
- **RBAC — Consent**: billing_specialist, nurse_medication_aide, physician, participant_family, and program_administrator denied all access; care_coordinator and compliance_officer write and read (REQ_11.8)
- **42 CFR Part 2 — CarePlan**: access denied for unauthorized roles on care plans where Participant.is_sud_record = true; 403 with no record existence disclosure; care_plan_goal rows and notes redacted in list responses (REQ_7.6)
- **42 CFR Part 2 — Appointment**: access denied for unauthorized roles on appointments where Participant.is_sud_record = true; appointment_type, cancellation_reason, result_notes, follow_up_required redacted in list responses (REQ_8.7)
- **42 CFR Part 2 — MedicationRefill**: access denied for unauthorized roles on refills where is_controlled_substance = true; medication_name, dose, route, is_controlled_substance, denial_reason, ncpdp_script_reference redacted in list responses; is_controlled_substance flag absent from non-privileged API responses (REQ_9.8)
- **Consent gate enforcement**: disclosure blocked without active, non-expired consent of matching type — CarePlan FHIR (REQ_7.8), Appointment FHIR (REQ_8.9), MedicationRefill pharmacy (REQ_9.10), Reminder push delivery (REQ_10.8)
- **Soft delete — all entities**: hard delete blocked; soft-deleted records excluded from standard queries; compliance_officer audit query retrieves soft-deleted records (REQ_7.10, REQ_8.10, REQ_9.11, REQ_10.9, REQ_11.10)
- **Consent record retention**: withdrawn and expired consent records for SUD-flagged participants retained per 42 CFR Part 2 §2.16 — no hard delete regardless of status (REQ_11.10)

### 4.4 Regulatory Tests

Regulatory tests verify compliance obligations that go beyond normal application behaviour. These tests are the direct translation of HIPAA, 42 CFR Part 2, CMS, and state licensing requirements into verifiable assertions.

Coverage areas:

- **Audit log completeness — CarePlan**: every PHI read and write on SUD-flagged care plans produces an audit event with all mandatory fields from Section 2.6.1 before the response is returned; ACCESS_DENIED logged for unauthorized attempts; no PHI values in any audit row (REQ_7.7)
- **Audit log completeness — Appointment**: every PHI read and write on SUD-flagged appointments produces an audit event before response; ACCESS_DENIED logged (REQ_8.8)
- **Audit log completeness — MedicationRefill**: every PHI read and write on controlled substance refills produces an audit event before response; ACCESS_DENIED logged (REQ_9.9)
- **Audit log completeness — Consent**: CONSENT_CREATED event on creation with required fields and without scope_description; CONSENT_WITHDRAWN event on withdrawal; CONSENT_EXPIRED event on expiration; every disclosure gate evaluation logged with outcome ALLOWED or DENIED/SUPPRESSED regardless of result (REQ_11.9)
- **42 CFR Part 2 disclosure gate**: no CarePlan or Appointment FHIR resource for a SUD participant may be transmitted without an active ehr consent; no MedicationRefill for a controlled substance SUD participant may be transmitted to a pharmacy without an active pharmacy consent; every gate evaluation produces an audit event (REQ_7.8, REQ_8.9, REQ_9.10)
- **42 CFR Part 2 SUD delivery gate**: no push notification for a SUD participant with a clinical reference may be delivered without an active push_notification consent; SUD_DELIVERY_GATE audit event emitted for every delivery attempt regardless of outcome (REQ_10.8)
- **Consent date validation**: expiration_date must be strictly after effective_date (CONSENT_INVALID_DATES); expiration_date must be strictly after current date (CONSENT_EXPIRATION_IN_PAST); past effective_date permitted for late entry (REQ_11.2)
- **Consent form documentation**: consent_form_reference required and non-empty per 42 CFR Part 2 §2.31 written consent requirement (REQ_11.3)
- **Consent withdrawal right**: withdrawal accepted without a reason per 42 CFR Part 2 §2.31(c); takes effect immediately; blocks all subsequent disclosures (REQ_11.5)
- **Soft delete integrity**: soft-deleted records for all five entities remain in the database and are recoverable by compliance_officer audit queries; SUD consent records retained per 42 CFR Part 2 §2.16 regardless of consent status (REQ_7.10, REQ_8.10, REQ_9.11, REQ_10.9, REQ_11.10)

---

## 5. Data Strategy

### 5.1 Test Atomicity and Traceability Principles

Each test is atomic. One test covers exactly one requirement from `requirements_phase1.xlsx` (Phase 2 Requirements sheet), identified by its REQ_ID. A test that covers two requirements is two tests that have been merged and must be split before it can be accepted into the suite.

Test ID naming maps directly to REQ_ID. A test covering requirement 8.4 carries that identifier in its function name so that a CI failure immediately identifies the violated requirement without reading the test body.

A test that fails must point to exactly one requirement violation. If a failure is ambiguous about which requirement was broken, the test scope is too broad.

Reuse is achieved through the fixture layer only. Session-scoped fixtures provide authentication tokens and baseline entities shared as read-only context across all tests. Function-scoped fixtures provide isolated, freshly created records for each individual test.

No test creates its own data. All records used in a test are supplied by fixtures declared in the test's function signature. A test body that calls an API to create a prerequisite record violates this rule.

No test depends on another test's side effects. Tests run in any order and produce the same result. A test that only passes because a prior test left a record in the database is a hidden dependency and must be refactored.

A requirement not covered by a dedicated test is explicitly marked as not covered in the `Covered In` column of `requirements_phase1.xlsx`. An empty `Covered In` cell is a declared gap that requires a tracking decision, not an accidental omission.

### 5.2 Fixture Scopes

| Scope | Contents | Rationale |
|---|---|---|
| Session | Tenant record — one User per role (7 roles) — one base Participant per is_sud_record value — reused from Phase 1 session fixtures | Created once per test run — never mutated — provides shared read-only context for all tests |
| Function | Any record that will be mutated, voided, soft-deleted, withdrawn, expired, activated, superseded, completed, cancelled, or involved in a state transition | Created fresh for each individual test — torn down after assertion — guarantees no cross-test state |

### 5.3 Fixture Hierarchy

The fixture hierarchy follows the dependency chain of the data model. Lower-level fixtures must be available before higher-level ones can be created. Phase 2 fixtures extend the Phase 1 hierarchy — Phase 1 session-scoped Participant and User fixtures are reused.

```
Tenant (session) — reused from Phase 1
  User x 7 roles (session) — reused from Phase 1
  Participant - is_sud_record=false (session) — reused from Phase 1
  Participant - is_sud_record=true  (session) — reused from Phase 1
    CarePlan - draft (function)
    CarePlan - active with physician signature and effective_date (function)
    CarePlan - superseded (function)
    Appointment - scheduled (function)
    Appointment - completed (function)
    MedicationRefill - requested, non-controlled (function)
    MedicationRefill - requested, is_controlled_substance=true (function)
    MedicationRefill - fulfilled (function)
    Reminder - scheduled, channel=push (function)
    Reminder - sent (function)
    Consent - active, disclosure_recipient_type=ehr (function)
    Consent - active, disclosure_recipient_type=pharmacy (function)
    Consent - active, disclosure_recipient_type=push_notification (function)
    Consent - withdrawn (function)
```

Session-scoped Participant fixtures are never mutated. Any test that needs to modify a Participant (status transition, soft delete, version conflict) creates its own function-scoped Participant.

### 5.4 Tenant Isolation in Fixtures

Two distinct tenant fixtures are created at session scope: a primary tenant used for all standard tests and a secondary tenant used exclusively for cross-tenant isolation tests. The secondary tenant contains a minimal record set (one user, one participant) with the same identifiers as the primary tenant, confirming that uniqueness constraints are correctly scoped per tenant. This infrastructure is reused from Phase 1.

### 5.5 Synthetic Data Conventions

Phase 2 reuses the Phase 1 synthetic data conventions and extends them for the new entity types:

| Field | Synthetic Format | Example |
|---|---|---|
| Medication name (refill) | TEST-REFILL-N | TEST-REFILL-001 |
| Reminder title | TEST-REMINDER-TITLE-N | TEST-REMINDER-TITLE-001 |
| Reminder body | Generic PHI-free text | Your scheduled activity is coming up |
| Consent form reference | TEST-CONSENT-REF-N | TEST-CONSENT-REF-001 |
| Disclosure recipient name | Test Recipient N | Test Recipient 001 |
| Disclosure purpose | Test purpose for disclosure | Test purpose for treatment coordination |
| Scope description | Test scope description | Test scope for medication management |
| ICD-10 code (care plan) | Z00.N (exam codes) | Z00.0 |
| Physician order reference | TEST-ORDER-N | TEST-ORDER-001 |
| FHIR resource IDs | TEST-FHIR-N | TEST-FHIR-CP-001 |

All conventions from Phase 1 (Medicaid ID, Medicare MBI, SSN, email, first/last name, medication name for MAR, claim reference) remain unchanged and are inherited from the Phase 1 fixture layer.

---

## 6. CI Gate

### 6.1 Gate Design

The CI gate is a set of test groups that must all pass before a Phase 2 release artifact is produced. Gate failures block the build. Non-gate tests produce coverage reports but do not block release. All Phase 1 gate tests remain blocking — no Phase 2 change may cause a Phase 1 gate failure.

### 6.2 Blocking Gate Groups

| Gate Group | Test Type | Rationale |
|---|---|---|
| Unique constraints — all five entities + care_plan_goal | Data Integrity | Duplicate care plans, overlapping appointments, duplicate refill transmissions, duplicate reminders, duplicate active consents (REQ_7.1, REQ_7.9, REQ_8.1, REQ_9.1, REQ_10.1, REQ_11.1) |
| Partial index constraints — CarePlan, MedicationRefill, Reminder, Consent | Data Integrity | Single-active-plan (REQ_7.2), one open refill (REQ_9.2), one scheduled reminder (REQ_10.2), one active consent per type (REQ_11.1) |
| Physician overlap — Appointment (application + SQLite triggers) | Data Integrity | Double-booked physician — application layer and database trigger backstop (REQ_8.2) |
| RBAC enforcement — all entities, all roles | Security | Unauthorized PHI access is a HIPAA breach (REQ_7.5, REQ_8.6, REQ_9.7, REQ_10.7, REQ_11.8) |
| 42 CFR Part 2 access gate — CarePlan, Appointment, MedicationRefill | Regulatory | Prohibited SUD disclosure carries criminal penalties (REQ_7.6, REQ_8.7, REQ_9.8) |
| Audit log completeness — all SUD/controlled substance PHI operations and consent lifecycle | Regulatory | HIPAA §164.312(b) — SOC 2 CC7.2 — 42 CFR Part 2 §2.16 — non-bypassable control (REQ_7.7, REQ_8.8, REQ_9.9, REQ_11.9) |
| State machine transitions — all five entities | Functional | Invalid clinical artifacts, terminal state reversal, consent lifecycle bypass (REQ_7.2, REQ_7.3, REQ_8.3, REQ_9.4, REQ_11.4, REQ_11.5) |
| Consent gate — CarePlan FHIR, Appointment FHIR, MedicationRefill pharmacy, Reminder push delivery | Regulatory | 42 CFR Part 2 §2.31 — disclosure without consent (REQ_7.8, REQ_8.9, REQ_9.10, REQ_10.8) |
| Consent disclosure gate (5-condition check) | Regulatory | Consent gate mechanics must enforce all five conditions simultaneously at disclosure time (REQ_11.7) |
| Soft delete — all five entities | Regulatory | HIPAA record retention — 42 CFR Part 2 §2.16 SUD consent retention (REQ_7.10, REQ_8.10, REQ_9.11, REQ_10.9, REQ_11.10) |
| Partial immutability — Appointment completed, MedicationRefill fulfilled, Reminder sent | Functional | Clinical record integrity after completion/fulfillment/delivery (REQ_8.4, REQ_9.5, REQ_10.5) |
| Full immutability — CarePlan superseded/archived, Consent withdrawn/expired | Functional | Historical clinical records and consent records must not be modified (REQ_7.4, REQ_11.4) |
| PHI-in-payload rejection — Reminder | Functional | HIPAA minimum necessary — no PHI in push notification payloads (REQ_10.3) |
| Cancellation/denial reason enforcement | Functional | Appointment cancellation (REQ_8.5), MedicationRefill denial and cancellation (REQ_9.6), Reminder cancellation (REQ_10.6) |
| Field validation — effective_date, expiration_date, quantity_requested, channel, scheduled_for | Functional | Pre-activation effective_date (REQ_7.11), consent date validation (REQ_11.2), positive quantity (REQ_9.3), push-only channel (REQ_10.10), future scheduled_for (REQ_10.4) |
| Consent form reference | Functional | 42 CFR Part 2 §2.31 written consent documentation requirement (REQ_11.3) |
| Tenant isolation — Phase 2 entities | Security | Cross-tenant PHI access is a multi-party HIPAA breach |

### 6.3 Non-Blocking (Informational) Groups

The following test groups run in CI and produce reports but do not block release in Phase 2. They become blocking gates in Phase 3.

| Group | Current Status | Phase 3 Gate |
|---|---|---|
| care_plan_goal functional tests (CRUD, status transitions, discontinued-requires-note) | Informational | Blocking |
| Automated reminder generation from appointment scheduling events | Informational | Blocking |
| SMS and email channel delivery for Reminder | Informational | Blocking |
| Transport reminder type records | Informational | Blocking |
| Event-driven consent expiration trigger (replacing cron) | Informational | Blocking |
| FHIR round-trip integration (CarePlan, Appointment, MedicationRefill) | Informational | Blocking |
| NCPDP SCRIPT round-trip integration (MedicationRefill) | Informational | Blocking |

### 6.4 Coverage Threshold

Line coverage of the mock backend routes and service layer must reach 80% before release, inclusive of both Phase 1 and Phase 2 code paths. Coverage is measured by pytest-cov and reported in CI but does not independently block release — gate group failures are the primary release control. A release that meets 80% coverage but fails a gate group is still blocked.

---

## 7. Tools

### 7.1 Tool Stack

| Tool | Version Constraint | Role |
|---|---|---|
| pytest | >= 8.0 | Test runner — fixture management — parameterisation |
| pytest-cov | latest | Line coverage reporting |
| Playwright (Python) | >= 1.40 | API-layer tests via `request` context — no browser required |
| sqlite3 (stdlib) | Python stdlib | DB-layer direct queries — trigger verification |
| openpyxl | >= 3.1 | Requirements cross-reference in fixture helpers |
| factory-boy | optional | Synthetic data generation for function-scoped fixtures |

### 7.2 pytest

pytest is the top-level runner for all three test layers. It manages the fixture scope hierarchy (session, module, function), parametrize decorators for multi-role RBAC sweeps, and the conftest chain that handles tenant and user setup.

Configuration is defined in `pyproject.toml`. Test discovery follows the standard `test_*.py` naming convention. Marks are defined for each gate group so that the CI pipeline can run gate-only tests with `pytest -m gate` and full suite tests with `pytest`. Phase 2 tests use the same marks infrastructure as Phase 1.

### 7.3 Playwright Python API Request Context

Playwright is used exclusively through its `APIRequestContext` (the `request` fixture), not through a browser page. This avoids the overhead of launching a browser for pure HTTP API verification.

Playwright handles:
- Session management and token injection for each role
- Multipart and JSON request bodies
- Response status, headers, and body assertion
- Concurrent request patterns needed for optimistic locking tests and concurrency race tests (two POSTs racing on the same CarePlan version_number)

No Playwright tests use `page.goto` or any browser-rendered surface in Phase 2.

### 7.4 SQLite Direct Queries

The database layer uses Python's built-in `sqlite3` module to execute queries directly against the mock backend's SQLite file. This layer does not go through the application stack.

Direct query responsibilities:

- `PRAGMA index_list` and `PRAGMA index_info` to assert UNIQUE index existence on each constrained column set for all five Phase 2 entities and care_plan_goal
- Partial unique index verification for single-active constraints (CarePlan, MedicationRefill, Reminder, Consent)
- `SELECT name, sql FROM sqlite_master WHERE type='trigger'` to verify the existence and SQL definition of the two Appointment physician overlap triggers (trg_appointment_physician_no_overlap_insert and trg_appointment_physician_no_overlap_update)
- Direct SQL INSERT and UPDATE on the appointment table to verify that the triggers fire independently and raise OperationalError with message 'overlapping appointment for this physician'
- `SELECT` assertions after soft-delete operations to confirm the row persists with is_deleted = true — all five entities
- Audit log table `SELECT` to confirm mandatory fields are non-null after SUD/controlled-substance PHI operations and consent lifecycle events; scope_description absent from consent audit payloads
- Version column `SELECT` to confirm increment after each write
- `PRAGMA table_info` to confirm NOT NULL constraints on mandatory fields

All direct queries run inside a read-only connection opened on the same database file used by the running mock backend instance. Trigger verification tests use a separate writable connection to execute the INSERT/UPDATE statements that test the trigger backstop.

### 7.5 Test Organisation

Each entity test file contains exactly one function per REQ_ID. Function names carry the REQ_ID as a numeric prefix followed by a short description of the requirement being verified. The `Covered In` column in `requirements_phase1.xlsx` (Phase 2 Requirements sheet) is populated with the file name and function name for each covered row; an empty cell is a declared gap.

```
tests/
  conftest.py
  test_participant.py          — Phase 1 (unchanged)
  test_user.py                 — Phase 1 (unchanged)
  test_attendance.py           — Phase 1 (unchanged)
  test_claim.py                — Phase 1 (unchanged)
  test_mar_record.py           — Phase 1 (unchanged)
  test_incident.py             — Phase 1 (unchanged)
  test_audit_log.py            — Phase 1 (unchanged)
  test_rbac_sweep.py           — Phase 1 (unchanged)
  test_tenant_isolation.py     — Phase 1 (unchanged)
  test_care_plan.py            — Phase 2
  test_appointment.py          — Phase 2
  test_medication_refill.py    — Phase 2
  test_reminder.py             — Phase 2
  test_consent.py              — Phase 2
  test_audit_log_phase2.py     — Phase 2 audit events
  test_rbac_sweep_phase2.py    — Phase 2 RBAC sweep
  test_tenant_isolation_phase2.py — Phase 2 tenant isolation
  test_consent_gate.py         — Phase 2 consent gate integration
  db/
    conftest.py
    test_schema.py             — Phase 1 (unchanged)
    test_schema_phase2.py      — Phase 2 schema assertions
```

**test_care_plan.py** — 11 functions (REQ_7.1 – REQ_7.11)

```
def test_tc_7_1_duplicate_version_number_returns_409
def test_tc_7_2_single_active_plan_supersession_in_transaction
def test_tc_7_3_activation_requires_physician_signature_and_physician_id
def test_tc_7_4_superseded_plan_immutable_clinical_field_change_requires_revision
def test_tc_7_5_rbac_care_coordinator_only_write_access
def test_tc_7_6_sud_participant_care_plan_access_denied_for_unauthorized_roles
def test_tc_7_7_audit_log_sud_care_plan_phi_read_write_access_denied
def test_tc_7_8_fhir_consent_gate_blocks_transmission_without_ehr_consent
def test_tc_7_9_duplicate_goal_domain_description_returns_409
def test_tc_7_10_soft_delete_sets_is_deleted_true_hard_delete_blocked
def test_tc_7_11_activation_requires_non_null_effective_date
```

**test_appointment.py** — 10 functions (REQ_8.1 – REQ_8.10)

```
def test_tc_8_1_duplicate_participant_physician_scheduled_start_returns_409
def test_tc_8_2_physician_overlap_rejected_boundary_permitted_trigger_backstop
def test_tc_8_3_status_state_machine_terminal_states_irreversible
def test_tc_8_4_completed_appointment_partial_immutability_mixed_body_rejected
def test_tc_8_5_cancellation_requires_non_empty_cancellation_reason
def test_tc_8_6_rbac_nurse_sud_only_physician_read_billing_denied
def test_tc_8_7_sud_participant_appointment_access_denied_for_unauthorized_roles
def test_tc_8_8_audit_log_sud_appointment_phi_read_write_access_denied
def test_tc_8_9_fhir_consent_gate_blocks_transmission_without_ehr_consent
def test_tc_8_10_soft_delete_sets_is_deleted_true_hard_delete_blocked
```

**test_medication_refill.py** — 11 functions (REQ_9.1 – REQ_9.11)

```
def test_tc_9_1_duplicate_participant_medication_requested_at_returns_409
def test_tc_9_2_one_open_refill_per_medication_in_flight_uniqueness
def test_tc_9_3_quantity_requested_must_be_positive_integer
def test_tc_9_4_status_state_machine_terminal_states_irreversible
def test_tc_9_5_fulfilled_refill_partial_immutability_mixed_body_rejected
def test_tc_9_6_denied_requires_denial_reason_cancelled_requires_cancellation_reason
def test_tc_9_7_rbac_nurse_write_coordinator_controlled_only_billing_denied
def test_tc_9_8_controlled_substance_access_denied_for_unauthorized_roles
def test_tc_9_9_audit_log_controlled_substance_phi_read_write_access_denied
def test_tc_9_10_pharmacy_consent_gate_blocks_transmission_without_consent
def test_tc_9_11_soft_delete_sets_is_deleted_true_hard_delete_blocked
```

**test_reminder.py** — 10 functions (REQ_10.1 – REQ_10.10)

```
def test_tc_10_1_duplicate_participant_type_scheduled_for_returns_409
def test_tc_10_2_one_scheduled_reminder_per_type_transport_rejected
def test_tc_10_3_phi_in_payload_rejected_name_diagnosis_medication
def test_tc_10_4_scheduled_for_must_be_strictly_future
def test_tc_10_5_sent_reminder_immutable_failure_reason_writable_on_failed_only
def test_tc_10_6_cancellation_requires_non_empty_cancellation_reason
def test_tc_10_7_rbac_care_coordinator_write_participant_family_self_read_only
def test_tc_10_8_sud_delivery_gate_blocks_without_push_notification_consent
def test_tc_10_9_soft_delete_sets_is_deleted_true_hard_delete_blocked
def test_tc_10_10_channel_restricted_to_push_sms_email_rejected
```

**test_consent.py** — 10 functions (REQ_11.1 – REQ_11.10)

```
def test_tc_11_1_one_active_consent_per_type_per_participant
def test_tc_11_2_expiration_date_after_effective_date_and_after_current_date
def test_tc_11_3_consent_form_reference_required_non_empty
def test_tc_11_4_withdrawn_expired_consent_fully_immutable
def test_tc_11_5_withdrawal_without_reason_accepted_blocks_future_disclosures
def test_tc_11_6_expiration_cron_transitions_active_to_expired
def test_tc_11_7_disclosure_gate_five_condition_check_at_disclosure_time
def test_tc_11_8_rbac_care_coordinator_compliance_officer_only
def test_tc_11_9_audit_log_created_withdrawn_expired_gate_evaluation
def test_tc_11_10_soft_delete_sets_is_deleted_true_sud_retention_enforced
```

**test_consent_gate.py** — Cross-entity consent gate integration tests

```
def test_cg_1_care_plan_fhir_blocked_without_ehr_consent
def test_cg_2_care_plan_fhir_permitted_with_valid_ehr_consent
def test_cg_3_appointment_fhir_blocked_without_ehr_consent
def test_cg_4_appointment_fhir_permitted_with_valid_ehr_consent
def test_cg_5_medication_refill_pharmacy_blocked_without_pharmacy_consent
def test_cg_6_medication_refill_pharmacy_permitted_with_valid_pharmacy_consent
def test_cg_7_reminder_push_blocked_without_push_notification_consent
def test_cg_8_reminder_push_permitted_with_valid_push_notification_consent
def test_cg_9_expired_consent_blocks_disclosure
def test_cg_10_withdrawn_consent_blocks_disclosure
def test_cg_11_non_sud_participant_disclosure_proceeds_without_consent_check
```

**test_audit_log_phase2.py** — Phase 2 audit event assertions

**test_rbac_sweep_phase2.py** — Phase 2 RBAC sweep across all five entities and all seven roles

**test_tenant_isolation_phase2.py** — Phase 2 cross-tenant isolation for all five entities

**db/test_schema_phase2.py** — DB-layer assertions: UNIQUE and partial unique index presence, SQLite trigger presence and enforcement, NOT NULL constraints, version column existence, is_deleted default — all five entities and care_plan_goal

---
