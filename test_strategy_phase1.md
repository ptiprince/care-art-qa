# Care Art - Test Strategy: Phase 1

> **Status:** Phase 1 draft. Covers the six entities defined in Section 3 of the architecture document: Participant, User, Attendance, Claim, MARRecord, and Incident. This document describes strategy and approach only - individual test cases are tracked separately.
> **Regulatory scope:** HIPAA - 42 CFR Part 2 - CMS (Medicaid/Medicare) - State adult day care licensing

---

## 1. Scope

### 1.1 What This Strategy Covers

This strategy governs test planning for the Phase 1 mock backend. Coverage is bounded to the six entities defined in the Phase 1 data model: Participant, User, Attendance, Claim, MARRecord, and Incident. The 57 requirements in `requirements_phase1.xlsx` are the authoritative source of acceptance criteria.

The mock backend is the sole target. Tests run against a local SQLite database standing in for the production PostgreSQL RDS instance. All test infrastructure is self-contained and requires no external network access.

### 1.2 Phase 1 Entity Inventory

| Entity | Section | Primary Regulatory Obligation | Req Count |
|---|---|---|---|
| Participant | 3.1 | HIPAA - 42 CFR Part 2 (via is_sud_record) - CMS | 12 |
| User | 3.2 | HIPAA Workforce §164.308(a)(3) | 13 |
| Attendance | 3.3 | HIPAA - CMS billing integrity | 12 |
| Claim | 3.4 | HIPAA - CMS Medicaid/Medicare - EDI X12 | 9 |
| MARRecord | 3.5 | HIPAA - 42 CFR Part 2 (via is_controlled_substance) | 10 |
| Incident | 3.6 | HIPAA - State licensing - 42 CFR Part 2 (via is_sud_related) | 8 |

### 1.3 Out of Scope for Phase 1

The following are explicitly excluded and will be addressed in a separate Phase 2 test strategy:

- Phase 2 entities: CarePlan, Appointment, MedicationRefill, Reminder
- Secondary payer coordination of benefits (COB) and MCO fields on Claim
- PRN and recurring schedule MAR workflows
- Multi-participant incident records and corrective action plans
- FHIR R4 API surface and SMART on FHIR token validation
- Clearinghouse EDI X12 837/835 round-trip integration
- HAPI FHIR / AWS HealthLake integration
- Push notification delivery (APNs/FCM)
- Production infrastructure: PostgreSQL RDS, pgaudit extension, CloudWatch, S3 WORM
- UI and browser rendering tests (covered by the Playwright layer only at the API level in Phase 1)
- Load, stress, and performance benchmarking
- Third-party penetration testing

---

## 2. Risk-Based Prioritization

### 2.1 Entity Risk Ranking

Entities are ranked by the combination of patient safety risk, regulatory penalty exposure, and the number of high-severity requirement types (42 CFR Part 2, Audit Logging, State Machine) they carry.

| Rank | Entity | Risk Driver | Risk Level |
|---|---|---|---|
| 1 | MARRecord | Medication safety - controlled substance access under 42 CFR Part 2 - nurse-only write gate | Critical |
| 2 | Incident | State licensing deadline (24-hour notification) - 42 CFR Part 2 for SUD incidents - immutability | Critical |
| 3 | Participant | Central PHI anchor - is_sud_record flag propagates Part 2 controls to all linked entities | High |
| 4 | Claim | CMS fraud and billing integrity - double-billing prevention - 10-year audit retention | High |
| 5 | Attendance | Billing source of truth - confirmed status gate for Claim - void chain dependencies | Medium |
| 6 | User | Authentication and RBAC foundation - lockout and session controls - lower PHI exposure | Medium |

The ranking determines test authoring and execution order, not whether an entity is tested. All entities reach full coverage before release.

### 2.2 Requirement Type Risk Ranking

| Rank | Requirement Type | Regulatory Basis | Failure Consequence |
|---|---|---|---|
| 1 | 42 CFR Part 2 | 42 CFR Part 2 §2.13(b) - §2.31 | Prohibited SUD disclosure - civil and criminal penalties |
| 2 | Audit Logging | HIPAA §164.312(b) - SOC 2 CC7.2 | HIPAA breach finding - SOC 2 audit failure - undetectable access |
| 3 | Unique Constraint | CMS billing integrity | Duplicate claims - payer rejection - fraud flag |
| 4 | State Machine | State licensing - CMS | Missed regulatory deadlines - invalid billing artifacts |
| 5 | RBAC | HIPAA §164.312(a)(1) | Unauthorized PHI access or modification |
| 6 | Business Rule | CMS - State licensing | Billing manipulation - workflow bypass |
| 7 | Field Validation | HIPAA minimum necessary - State MAR requirements | Data corruption - patient safety (MAR route/timing) |
| 8 | Data Integrity | HIPAA §164.312(b) | Concurrent-edit data loss - optimistic locking bypass |

### 2.3 Cross-Cutting Controls

Three controls cut across all six entities and are treated as blocking gates regardless of entity rank:

- **Optimistic locking** (version field - 409 on stale version): all entities
- **Soft delete only** (is_deleted flag - hard delete blocked): Participant and User
- **Audit log completeness** (mandatory fields, PHI values never in payload): all entities

---

## 3. Test Layers

### 3.1 Overview

Three distinct test layers map to the three verification surfaces of the mock backend. Each layer has a defined purpose, tool, and scope boundary. No layer substitutes for another - all three must pass.

| Layer | Target | Primary Verification | Tool |
|---|---|---|---|
| API | HTTP endpoints | Status codes - response shape - error codes - headers | Playwright (Python) via `request` context |
| Database | SQLite schema and data | Constraint enforcement - index presence - field-level rules - soft delete | pytest + sqlite3 direct queries |
| Business Rules | Cross-layer logic | State machine transitions - calculation correctness - workflow sequencing | pytest calling API + asserting DB state |

### 3.2 API Layer

The API layer tests every HTTP surface of the mock backend. It does not query the database directly - it treats the API as the system under test and verifies observable behaviour through responses.

Responsibilities of this layer:

- Correct HTTP status codes for happy path and error conditions (200, 201, 400, 403, 404, 405, 409, 422)
- Correct error code strings in response bodies (for example PARTICIPANT_DUPLICATE_MEDICAID_ID, CLAIM_DUPLICATE)
- Response body shape conformance: required fields present, forbidden fields absent, PHI values absent from error responses
- Phase 2 field rejection on Claim endpoints (400 on secondary_payer_id and related fields)
- Header-level controls: authentication required, tenant isolation enforced at gateway

This layer does not verify that a database constraint fired - it verifies that the application returned the correct client-visible outcome.

### 3.3 Database Layer

The database layer bypasses the application and queries SQLite directly to verify that schema-level constraints exist and data invariants hold. This layer is the backstop that confirms the application cannot accidentally bypass a constraint.

Responsibilities of this layer:

- UNIQUE index presence on all constrained field combinations (for example tenant_id + medicaid_id on Participant, tenant_id + participant_id + date_of_service on Attendance)
- NOT NULL constraints on mandatory fields
- Soft delete: is_deleted defaults to false and no hard-delete path removes a row
- Optimistic locking: version increments on every write and the column exists on all six entity tables
- Audit log table: mandatory fields present and non-null after any PHI operation (timestamp, user_id, tenant_id, action_type, resource_id, outcome)
- PHI field values absent from audit log rows

### 3.4 Business Rules Layer

The business rules layer orchestrates multi-step scenarios that cannot be verified by a single API call or a single database query. It calls the API, observes the state transitions, and then asserts both the API response and the resulting database state.

Responsibilities of this layer:

- State machine transitions: valid and invalid paths verified for all six entities
- Billing unit calculation: total_hours to authorized_units_consumed conversion for Medicaid and Medicare payer definitions
- Void workflow chain: Attendance void blocked when referencing Claim is active
- Claim generation: units_billed override from attendance sum, empty attendance_ids rejection
- MARRecord correction: administered record immutability, correction record creation rules
- Incident escalation: automatic escalation on severe/medical_emergency, 24-hour deadline alerting
- Optimistic locking: concurrent-edit 409 produced when version is stale
- 42 CFR Part 2 gate: access denied for disallowed roles on is_controlled_substance and is_sud_related records
- RBAC evaluation order: tenant_id check before status check before role check

---

## 4. Test Types

### 4.1 Functional Tests

Functional tests verify that the system does what the requirements say it must do when inputs are valid. They follow happy-path flows and the immediate variations defined in each requirement's acceptance criteria.

Coverage map:

| Requirement Type | Functional Test Focus |
|---|---|
| State Machine | Every allowed transition for each entity - automatic field side-effects (discharge_date, deactivated_at, submission_date) |
| Field Validation | Mandatory field presence - enum range (route, status, payer_type) - date and timestamp constraints |
| Business Rule | Calculation correctness - workflow trigger conditions - generation rules |
| RBAC | Each permitted role can perform its allowed operations successfully |

Functional tests do not assert security controls - that is the responsibility of the security test type.

### 4.2 Data Integrity Tests

Data integrity tests verify that uniqueness, referential, and concurrency constraints prevent corrupt state from entering the system, both through the application layer and directly at the database layer.

Coverage map:

| Constraint | Entity | Error Code |
|---|---|---|
| Medicaid ID unique per tenant | Participant | PARTICIPANT_DUPLICATE_MEDICAID_ID |
| Email unique per tenant | User | USER_DUPLICATE_EMAIL |
| Participant + date_of_service unique per tenant | Attendance | ATTENDANCE_DUPLICATE_DATE |
| claim_reference_number globally unique | Claim | CLAIM_DUPLICATE_REFERENCE |
| Participant + date_of_service_start + procedure_code + payer_type per tenant | Claim | CLAIM_DUPLICATE |
| Participant + medication_name + scheduled_time per tenant | MARRecord | MAR_DUPLICATE_EVENT |
| incident_id PK only - no composite unique | Incident | 409 on duplicate PK only |
| version field - stale version | All entities | *_VERSION_CONFLICT |

Each constraint is tested twice: once at the API layer (verify the 409 and error code) and once at the DB layer (verify the UNIQUE index fires independently).

### 4.3 Security Tests

Security tests verify that access controls prevent unauthorised operations and that sensitive data is never exposed through error messages or audit logs.

Coverage areas:

- RBAC: every role that must be denied for each entity operation receives 403 - the response contains no PHI values
- 42 CFR Part 2: role-restricted access to records where is_controlled_substance = true (MARRecord) and is_sud_related = true (Incident) - 403 with no record existence confirmation
- Account lockout: locked account returns 401 after 5 failures and remains locked after server restart
- MFA gate: PHI module access blocked for unenrolled PHI-accessing roles
- Password controls: plaintext never stored or returned, expired password triggers forced reset, previous-five reuse rejected
- Tenant isolation: a valid user from tenant A cannot read or write any record belonging to tenant B
- Hard delete blocked: DELETE on Participant and User returns 405

### 4.4 Regulatory Tests

Regulatory tests verify compliance obligations that go beyond normal application behaviour. These tests are the direct translation of HIPAA, 42 CFR Part 2, CMS, and state licensing requirements into verifiable assertions.

Coverage areas:

- **Audit log completeness**: every PHI read, write, and access denial produces an audit event containing all mandatory fields from architecture Section 2.6.1 - no PHI values in any audit row
- **42 CFR Part 2 disclosure gate**: no MARRecord with is_controlled_substance = true and no Incident with is_sud_related = true can be returned to an unauthorised role, and every authorised access produces a separate audit event before the response is sent
- **Claim audit retention**: audit events for Claim operations carry a 10-year retention marker (CMS requirement), distinguishable from the standard 6-year HIPAA retention used by other entities
- **Incident 24-hour deadline**: an escalated Incident without regulatory_submission_date and created_at more than 20 hours ago must appear in the alert query result - closing such an incident returns 422 with INCIDENT_MISSING_REGULATORY_SUBMISSION
- **Soft delete integrity**: soft-deleted Participant and User records remain in the database and are recoverable by compliance_officer audit queries - the PHI they contain is not orphaned

---

## 5. Data Strategy

### 5.1 Test Atomicity and Traceability Principles

Each test is atomic. One test covers exactly one requirement from `requirements_phase1.xlsx`, identified by its REQ_ID. A test that covers two requirements is two tests that have been merged and must be split before it can be accepted into the suite.

Test ID naming maps directly to REQ_ID. A test covering requirement 3.4 carries that identifier in its function name so that a CI failure immediately identifies the violated requirement without reading the test body.

A test that fails must point to exactly one requirement violation. If a failure is ambiguous about which requirement was broken, the test scope is too broad.

Reuse is achieved through the fixture layer only. Session-scoped fixtures provide authentication tokens and baseline entities shared as read-only context across all tests. Function-scoped fixtures provide isolated, freshly created records for each individual test.

No test creates its own data. All records used in a test are supplied by fixtures declared in the test's function signature. A test body that calls an API to create a prerequisite record violates this rule.

No test depends on another test's side effects. Tests run in any order and produce the same result. A test that only passes because a prior test left a record in the database is a hidden dependency and must be refactored.

A requirement not covered by a dedicated test is explicitly marked as not covered in the `Covered In` column of `requirements_phase1.xlsx`. An empty `Covered In` cell is a declared gap that requires a tracking decision, not an accidental omission.

### 5.2 Fixture Scopes

| Scope | Contents | Rationale |
|---|---|---|
| Session | Tenant record - one User per role (7 roles) - one base Participant per is_sud_record value | Created once per test run - never mutated - provides shared read-only context for all tests |
| Function | Any record that will be mutated, voided, soft-deleted, or involved in a state transition | Created fresh for each individual test - torn down after assertion - guarantees no cross-test state |

### 5.3 Fixture Hierarchy

The fixture hierarchy follows the dependency chain of the data model. Lower-level fixtures must be available before higher-level ones can be created.

```
Tenant (session)
  User x 7 roles (session)
  Participant - is_sud_record=false (session)
  Participant - is_sud_record=true  (session)
    Attendance - pending (function)
    Attendance - confirmed (function)
    MARRecord - non-controlled (function)
    MARRecord - is_controlled_substance=true (function)
    Incident - standard (function)
    Incident - is_sud_related=true (function)
    Claim - draft (function)
```

Session-scoped Participant fixtures are never mutated. Any test that needs to modify a Participant (status transition, soft delete, version conflict) creates its own function-scoped Participant.

### 5.4 Tenant Isolation in Fixtures

Two distinct tenant fixtures are created at session scope: a primary tenant used for all standard tests and a secondary tenant used exclusively for cross-tenant isolation tests. The secondary tenant contains a minimal record set (one user, one participant) with the same Medicaid IDs and email addresses as the primary tenant, confirming that uniqueness constraints are correctly scoped per tenant.

### 5.5 Synthetic Data Conventions

| Field | Synthetic Format | Example |
|---|---|---|
| Medicaid ID | TEST + 9 digits | TEST000000001 |
| Medicare MBI | T + 10 alphanumeric | T1EG4TE5MK9 |
| SSN | 900-00-NNNN (invalid range) | 900-00-0001 |
| Email | testuser+N@care-art-test.invalid | testuser+1@care-art-test.invalid |
| First/last name | Synthetic-N format | SynthFirst-001 / SynthLast-001 |
| Medication name | TEST-MED-N | TEST-MED-001 |
| Claim reference | TESTCLM + timestamp + seq | TESTCLM20260520001 |

The `.invalid` TLD (RFC 2606) guarantees that no synthetic email can resolve to a real address. The 900-series SSN prefix is reserved and cannot belong to a real person.

---

## 6. CI Gate

### 6.1 Gate Design

The CI gate is a set of test groups that must all pass before a Phase 1 release artifact is produced. Gate failures block the build. Non-gate tests produce coverage reports but do not block release.

### 6.2 Blocking Gate Groups

| Gate Group | Test Type | Rationale |
|---|---|---|
| Unique constraints - all six entities | Data Integrity | Billing fraud and duplicate record prevention - CMS requirement |
| RBAC enforcement - all entities - all roles | Security | Unauthorized PHI access is a HIPAA breach |
| 42 CFR Part 2 access gate - MARRecord and Incident | Regulatory | Prohibited SUD disclosure carries criminal penalties |
| Audit log completeness - all PHI operations | Regulatory | HIPAA §164.312(b) - SOC 2 CC7.2 - non-bypassable control |
| State machine transitions - all entities | Functional | Invalid billing artifacts and missed regulatory deadlines |
| Optimistic locking - all entities | Data Integrity | Concurrent-edit data loss corrupts PHI records and audit trail |
| Tenant isolation | Security | Cross-tenant PHI access is a multi-party HIPAA breach |
| Phase 2 field rejection on Claim | Functional | Phase 1 API contract - prevents schema corruption |

### 6.3 Non-Blocking (Informational) Groups

The following test groups run in CI and produce reports but do not block release in Phase 1. They become blocking gates in Phase 2.

| Group | Current Status | Phase 2 Gate |
|---|---|---|
| Soft delete audit query recovery | Informational | Blocking |
| 24-hour incident alert job | Informational | Blocking |
| Dormant account auto-deactivation job | Informational | Blocking |
| Billing unit calculation edge cases (partial hours, rounding) | Informational | Blocking |
| Password rotation history enforcement | Informational | Blocking |

### 6.4 Coverage Threshold

Line coverage of the mock backend routes and service layer must reach 80% before release. Coverage is measured by pytest-cov and reported in CI but does not independently block release - gate group failures are the primary release control. A release that meets 80% coverage but fails a gate group is still blocked.

---

## 7. Tools

### 7.1 Tool Stack

| Tool | Version Constraint | Role |
|---|---|---|
| pytest | >= 8.0 | Test runner - fixture management - parameterisation |
| pytest-cov | latest | Line coverage reporting |
| Playwright (Python) | >= 1.40 | API-layer tests via `request` context - no browser required |
| sqlite3 (stdlib) | Python stdlib | DB-layer direct queries |
| openpyxl | >= 3.1 | Requirements cross-reference in fixture helpers |
| factory-boy | optional | Synthetic data generation for function-scoped fixtures |

### 7.2 pytest

pytest is the top-level runner for all three test layers. It manages the fixture scope hierarchy (session, module, function), parametrize decorators for multi-role RBAC sweeps, and the conftest chain that handles tenant and user setup.

Configuration is defined in `pyproject.toml`. Test discovery follows the standard `test_*.py` naming convention. Marks are defined for each gate group so that the CI pipeline can run gate-only tests with `pytest -m gate` and full suite tests with `pytest`.

### 7.3 Playwright Python API Request Context

Playwright is used exclusively through its `APIRequestContext` (the `request` fixture), not through a browser page. This avoids the overhead of launching a browser for pure HTTP API verification.

Playwright handles:
- Session management and token injection for each role
- Multipart and JSON request bodies
- Response status, headers, and body assertion
- Concurrent request patterns needed for optimistic locking tests (two requests with the same version value)

No Playwright tests use `page.goto` or any browser-rendered surface in Phase 1.

### 7.4 SQLite Direct Queries

The database layer uses Python's built-in `sqlite3` module to execute queries directly against the mock backend's SQLite file. This layer does not go through the application stack.

Direct query responsibilities:

- `PRAGMA index_list` and `PRAGMA index_info` to assert UNIQUE index existence on each constrained column set
- `SELECT` assertions after soft-delete operations to confirm the row persists with is_deleted = true
- Audit log table `SELECT` to confirm mandatory fields are non-null and no PHI column values appear
- Version column `SELECT` to confirm increment after each write
- `PRAGMA table_info` to confirm NOT NULL constraints on mandatory fields

All direct queries run inside a read-only connection opened on the same database file used by the running mock backend instance.

### 7.5 Test Organisation

Each entity test file contains exactly one function per REQ_ID. Function names carry the REQ_ID as a numeric prefix followed by a short description of the requirement being verified. The `Covered In` column in `requirements_phase1.xlsx` is populated with the file name and function name for each covered row; an empty cell is a declared gap.

```
tests/
  conftest.py
  test_participant.py
  test_user.py
  test_attendance.py
  test_claim.py
  test_mar_record.py
  test_incident.py
  test_audit_log.py
  test_rbac_sweep.py
  test_tenant_isolation.py
  db/
    conftest.py
    test_schema.py
```

**test_participant.py** - 12 functions (TC-1.1 - TC-1.12)

```
def test_tc_1_1_positive_participant_creation_by_program_administrator
def test_tc_1_2_positive_login_valid_credentials
def test_tc_1_3_negative_login_wrong_password_returns_401
def test_tc_1_4_duplicate_medicaid_id_returns_409
def test_tc_1_5_sud_record_billing_specialist_returns_403_no_disclosure
def test_tc_1_6_audit_log_phi_operation_mandatory_fields_no_phi_values
def test_tc_1_7_state_machine_active_to_on_leave_returns_200
def test_tc_1_8_state_machine_deceased_to_active_returns_422
def test_tc_1_9_soft_delete_returns_200_is_deleted_true
def test_tc_1_10_hard_delete_attempt_returns_405_record_persists
def test_tc_1_11_missing_first_name_returns_400_with_field_name
def test_tc_1_12_missing_enrollment_date_returns_400_with_field_name
```

**test_user.py** - 13 functions (TC-2.1 - TC-2.13)

```
def test_tc_2_1_positive_user_creation_by_program_administrator
def test_tc_2_2_user_creation_by_unauthorized_role_returns_403
def test_tc_2_3_positive_login_valid_credentials_returns_200
def test_tc_2_4_login_wrong_password_returns_401_no_credential_disclosure
def test_tc_2_5_duplicate_email_same_tenant_returns_409
def test_tc_2_6_same_email_different_tenant_returns_201
def test_tc_2_7_account_lockout_after_5_failed_logins
def test_tc_2_8_locked_user_login_returns_401_account_locked
def test_tc_2_9_soft_delete_user_returns_200_status_inactive
def test_tc_2_10_audit_log_on_user_creation_has_mandatory_fields_no_pii
def test_tc_2_11_missing_email_returns_400_or_422_with_field_name
def test_tc_2_12_billing_specialist_create_participant_returns_403
def test_tc_2_13_nurse_create_claim_returns_403
```

**test_attendance.py** - 12 functions (TC-3.1 - TC-3.12)

```
def test_tc_3_1_positive_attendance_creation_by_program_administrator
def test_tc_3_2_positive_attendance_creation_by_care_coordinator
def test_tc_3_3_missing_date_of_service_returns_400
def test_tc_3_4_missing_participant_id_returns_400
def test_tc_3_5_duplicate_participant_date_returns_409
def test_tc_3_6_status_transition_pending_to_confirmed
def test_tc_3_7_void_with_void_reason_returns_200
def test_tc_3_8_void_without_void_reason_returns_422
def test_tc_3_9_billing_units_total_hours_to_authorized_units_consumed
def test_tc_3_10_billed_attendance_cannot_be_modified
def test_tc_3_11_audit_log_on_creation_has_mandatory_fields_no_phi
def test_tc_3_12_billing_specialist_create_attendance_returns_403
```

**test_claim.py** - 9 functions (REQ_IDs 4.1 - 4.9)

```
def test_4_1_unique_claim_reference_number_globally
def test_4_2_composite_unique_key_prevents_duplicate_billing
def test_4_3_rbac_write_restricted_to_billing_specialist_and_program_administrator
def test_4_4_claim_status_state_machine_transitions
def test_4_5_claim_requires_confirmed_attendance_records
def test_4_6_audit_log_on_claim_creation_and_submission
def test_4_7_claim_generated_from_attendance_units_not_blank
def test_4_8_phase2_deferred_fields_rejected_with_400
def test_4_9_optimistic_locking_version_conflict_returns_409
```

**test_mar_record.py** - 10 functions (REQ_IDs 5.1 - 5.10)

```
def test_5_1_unique_mar_per_participant_medication_and_scheduled_time
def test_5_2_rbac_write_restricted_to_nurse_medication_aide
def test_5_3_42cfr_part2_controlled_substance_access_gate
def test_5_4_audit_log_on_controlled_substance_read_and_write
def test_5_5_status_field_rules_administered_refused_held_missed
def test_5_6_administered_time_required_and_within_bounds
def test_5_7_route_must_be_oral_injection_or_topical
def test_5_8_administered_record_is_immutable
def test_5_9_correction_record_references_original_mar_id
def test_5_10_optimistic_locking_version_conflict_returns_409
```

**test_incident.py** - 8 functions (REQ_IDs 6.1 - 6.8)

```
def test_6_1_incident_id_is_sole_unique_constraint_no_composite_key
def test_6_2_rbac_staff_can_create_external_roles_denied
def test_6_3_42cfr_part2_sud_related_incident_access_gate
def test_6_4_audit_log_on_sud_related_incident_read_and_write
def test_6_5_state_machine_auto_escalates_severe_and_medical_emergency
def test_6_6_alert_raised_when_escalated_incident_approaches_24_hour_deadline
def test_6_7_closed_incident_is_immutable
def test_6_8_optimistic_locking_version_conflict_returns_409
```

**test_audit_log.py** - cross-entity: verifies audit pipeline completeness across all six entities (regulatory gate)

**test_rbac_sweep.py** - cross-entity: parametrized matrix of all roles against all entity endpoints (security gate)

**test_tenant_isolation.py** - cross-entity: verifies no record from tenant A is accessible to tenant B users (security gate)

**db/conftest.py** - sqlite3 read-only connection fixture

**db/test_schema.py** - DB-layer assertions: UNIQUE index presence, NOT NULL constraints, version column existence, is_deleted default, audit log mandatory fields

---
