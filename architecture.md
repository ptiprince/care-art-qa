# Care Art — System Architecture

> **Status:** Phase 1 in progress. Sections cover platform overview, architecture layers, audit logging, and core data model for Phase 1 entities. Phase 2 will extend the data model and add module requirements.
> **Regulatory scope:** HIPAA · 42 CFR Part 2 · CMS (Medicaid/Medicare) · HL7 FHIR · SOC 2 Type II · State adult day care licensing

---

## 1. Platform Overview

Care Art is a regulated, multi-tenant SaaS platform for adult day care program (ADCP) operators. It replaces paper-based and fragmented workflows across clinical, administrative, and billing functions with a unified, audit-ready system.

### 1.1 Target Users

| Role | Primary Modules |
|---|---|
| Program Administrator | Attendance, Billing, Reporting |
| Care Coordinator | Care Plans, Incident Reports, Appointments |
| Nurse / Medication Aide | MAR, Medication Refill, Care Plans |
| Billing Specialist | Insurance Billing, Claims, Remittance |
| Physician (external) | Appointments, Care Plan Orders (via FHIR) |
| Participant / Family | Reminders, Appointment Tracking (read-only portal) |
| Compliance Officer | Audit Logs, Incident Reports, All Modules |

### 1.2 Core Modules

1. **Attendance Tracking** — daily sign-in/sign-out, census, authorization unit tracking
2. **Insurance Billing & Claims** — Medicaid/Medicare claim generation, submission, remittance reconciliation
3. **Care Plan Management** — individualized care plans, goal tracking, physician order integration
4. **Incident Reporting** — state-mandated incident documentation, escalation workflows, regulatory submission
5. **Physician Appointments** — scheduling, referral tracking, FHIR-based result exchange
6. **Reminder & Tracking App** — participant/family-facing notifications, appointment reminders, transport alerts
7. **Medication Administration Records (MAR)** — eMAR with controlled substance tracking, 42 CFR Part 2 controls
8. **Medication Refill** — refill requests to pharmacies, status tracking, FHIR MedicationRequest exchange

### 1.3 Deployment Model

- **Multi-tenant SaaS** — each ADCP operator is an isolated tenant with separate data partitioning
- **Cloud-hosted** — AWS GovCloud (US) preferred for HIPAA BAA availability and FedRAMP alignment
- **API-first** — all modules expose RESTful and FHIR R4 APIs; UI is a thin client over these APIs
- **Mobile-ready** — responsive web for staff; native mobile app (iOS/Android) for the reminder/tracking module

---

## 2. Architecture Layers

| Layer | Components | Audit Events Emitted |
|---|---|---|
| **Client** | Web App (React), Mobile App (React Native), FHIR API | UI actions; session start/end; failed logins |
| **API Gateway** | Rate limiting · Auth · Tenant routing · WAF · TLS termination · PHI request tagging | Every API request: method, path, status, user, tenant, latency |
| **Application** | Attendance Service, Billing & Claims, Care Plan Service, Incident Reporting, Physician Scheduling, Reminder & Tracking, MAR Service, Medication Refill | PHI read/write per module; consent checks; 42 CFR Part 2 disclosures; business logic events |
| **Integration** | FHIR R4 (EHR/Pharmacy), Clearinghouse (837/835 EDI), State Portals | Outbound PHI disclosures to EHRs, pharmacies, clearinghouses, state portals; FHIR exchanges |
| **Data** | Primary DB (PostgreSQL RDS, tenant-partitioned, encrypted at rest), FHIR Data Store (HAPI FHIR / AWS HealthLake), Audit Log Sink (CloudWatch + S3 WORM, 6-yr retain), Object Storage (S3, encrypted, versioned) | DB reads/writes on PHI tables; schema changes; backup and restore events |
| **Audit Logging** (cross-cutting) | Amazon CloudWatch Logs + S3 WORM; immutable; 6-year retention; HIPAA §164.312(b); SOC 2 CC7.2 | Receives events from all layers; every PHI action logged with: timestamp, user ID, action type, data affected, tenant ID, source IP |

### 2.1 Client Layer

- **Web application** (React + TypeScript) — primary interface for all staff roles; role-based views enforce least-privilege access
- **Mobile application** (React Native) — participant/family portal for the Reminder & Tracking module; push notifications for appointments and transport
- **FHIR API surface** — external-facing FHIR R4 endpoints for physician EHR systems and pharmacy integrations; secured with SMART on FHIR OAuth 2.0

**Audit events emitted:** session start/end, authentication success and failure, page/screen views that render PHI, explicit logout and timeout events.

### 2.2 API Gateway Layer

All inbound traffic passes through a managed API gateway (AWS API Gateway or Kong) enforcing:

- **TLS 1.2+ only** — no plaintext PHI in transit
- **OAuth 2.0 / SMART on FHIR** — token-based auth for all clients
- **Tenant routing** — every request is tagged with a tenant ID resolved from the JWT; cross-tenant access is blocked at this layer
- **WAF rules** — OWASP Top 10 protections, geo-fencing if required by state licensing

**Audit events emitted:** every inbound API request — HTTP method, endpoint path, response status code, user ID, tenant ID, source IP, and latency. PHI-touching endpoints are flagged so downstream log processors can apply stricter retention and access controls.

### 2.3 Application Layer

Domain services are independently deployable (containerized, Kubernetes). Each service owns its bounded context and communicates via:

- **Synchronous REST** — for user-facing request/response flows
- **Async event bus** (Amazon EventBridge or Kafka) — for cross-service workflows (e.g., attendance event triggers billing authorization check)

Services never share databases; PHI crossing service boundaries is minimized and always encrypted in transit.

**Audit events emitted:** every PHI read or write operation at the service level, including the specific record type and record ID affected (never raw PHI values in log payloads). Additional events: 42 CFR Part 2 consent checks and outcomes, care plan approvals, incident escalations, MAR administrations, and medication refill authorizations.

### 2.4 Integration Layer

| Integration | Protocol | Regulatory Note |
|---|---|---|
| Physician EHRs | HL7 FHIR R4 (REST) | HIPAA-covered; BAA required with EHR vendor |
| Pharmacies | FHIR MedicationRequest / NCPDP SCRIPT | 42 CFR Part 2 consent required before SUD Rx disclosure |
| Medicaid/Medicare clearinghouse | EDI X12 837/835 | CMS compliance; NPI and taxonomy codes required |
| State incident portals | State-specific API or secure file upload | Varies by state; mandated timelines (often 24–72 hrs) |
| Push notifications | APNs / FCM | No PHI in notification payloads; deep-link to authenticated session |

**Audit events emitted:** every outbound PHI disclosure — destination system, FHIR resource type and ID, user or service identity initiating the disclosure, timestamp, and whether a 42 CFR Part 2 consent record was present. Failed or rejected transmissions are also logged.

### 2.5 Data Layer

| Store | Technology | Purpose |
|---|---|---|
| Primary relational DB | PostgreSQL on AWS RDS (Multi-AZ) | Transactional data for all modules; row-level tenant isolation |
| FHIR data store | HAPI FHIR Server or AWS HealthLake | FHIR resource persistence; supports CQL for clinical queries |
| Audit log | Amazon CloudWatch Logs + S3 (WORM) | Immutable access and change logs; 6-year retention (HIPAA) |
| Object storage | AWS S3 (SSE-KMS, versioning enabled) | Documents, attachments, signed forms, incident photos |
| Cache | Amazon ElastiCache (Redis) | Session tokens, rate-limit counters; no PHI cached |

**Audit events emitted:** database-level PHI table reads and writes (captured via PostgreSQL audit extension — pgaudit), S3 object access on PHI documents, backup initiation and completion, key rotation events, and any schema migrations affecting PHI tables.

### 2.6 Audit Logging — Cross-Cutting Layer

Audit logging is a mandatory, non-bypassable control that spans all five architecture layers. No service or integration may omit audit events for PHI-touching operations. The audit pipeline is independent of the application stack — a compromised service cannot suppress its own audit trail.

#### 2.6.1 Mandatory Log Record Fields

Every audit event, regardless of originating layer, must include:

| Field | Description | Example |
|---|---|---|
| `timestamp` | ISO 8601 UTC, millisecond precision | `2026-05-18T14:32:01.847Z` |
| `user_id` | Authenticated user or service account ID | `usr_9f3a2c` / `svc_billing` |
| `tenant_id` | ADCP operator tenant | `tenant_acme_adcp` |
| `session_id` | Auth session or API token identifier | `sess_7d1b...` |
| `action_type` | Standardized verb from controlled vocabulary | `PHI_READ`, `PHI_WRITE`, `PHI_DELETE`, `PHI_DISCLOSE`, `AUTH_SUCCESS`, `AUTH_FAILURE`, `CONSENT_CHECK` |
| `resource_type` | Category of data affected | `Participant`, `MedicationRecord`, `CarePlan`, `Claim` |
| `resource_id` | Record identifier (never raw PHI) | `part_00123` |
| `data_affected` | Fields accessed or changed (field names only, not values) | `["diagnosis_code","dob","insurance_id"]` |
| `source_ip` | Client IP address | `203.0.113.42` |
| `outcome` | Result of the action | `SUCCESS`, `DENIED`, `ERROR` |
| `layer` | Originating architecture layer | `API_GATEWAY`, `APP_SERVICE`, `INTEGRATION`, `DATA` |

> **PHI values are never written to audit logs.** Only identifiers, field names, and metadata are captured. This satisfies HIPAA Minimum Necessary while preserving full accountability.

#### 2.6.2 Audit Pipeline Architecture

| Step | Component | Notes |
|---|---|---|
| 1 — Source | All Layers | PHI actions emitted as structured audit events |
| 2 — Ingest | Amazon EventBridge (audit event bus) | Structured JSON, schema-validated; no PHI values; record IDs only |
| 3 — Enrich | AWS Lambda (log enrichment + validation) | Rejects malformed events; enriches with geo, user role snapshot |
| 4 — Hot store | Amazon CloudWatch Logs | 90-day queryable retention |
| 5 — Cold store | Amazon S3 (WORM / Object Lock) | 6-year retention; encrypted with KMS, cross-region replicated; immutable: no delete, no overwrite |
| 6 — Alerting | SIEM (e.g., Splunk / AWS Security Hub) | Real-time alerting on anomalous PHI access patterns |

#### 2.6.3 Audit Controls by Layer

| Layer | What Is Logged | Mechanism |
|---|---|---|
| Client | Session start/end, auth events, PHI screen renders | Frontend event emitter → API Gateway |
| API Gateway | Every request: method, path, status, user, tenant, IP | AWS API Gateway access logs |
| Application | PHI reads/writes per service, consent checks, business events | Shared audit SDK injected into each service |
| Integration | All outbound PHI disclosures, FHIR exchanges, EDI submissions | Integration adapters emit pre/post-send events |
| Data | Table-level PHI access, schema changes, backup/restore | pgaudit extension + S3 server access logs |

#### 2.6.4 Regulatory Mapping

| Requirement | Audit Control |
|---|---|
| HIPAA §164.312(b) — Audit Controls | Immutable logs for all PHI access; 6-year retention |
| HIPAA §164.308(a)(1) — Risk Analysis | Audit log anomaly alerts feed into risk management process |
| 42 CFR Part 2 §2.13(b) — SUD Disclosure Accounting | Every SUD record disclosure logged with consent record ID |
| SOC 2 CC7.2 — System Monitoring | Continuous log ingestion; alerts for access anomalies and policy violations |
| CMS Medicaid/Medicare | Claim submission and remittance events retained for 10 years (CMS requirement overrides HIPAA 6-year minimum for billing records) |

#### 2.6.5 Access to Audit Logs

- Audit logs are **read-only** for all application roles, including system administrators
- Only the **Compliance Officer** role and designated auditors may query logs
- Log access itself is meta-logged (logs of log access)
- Deletion or modification of audit records requires multi-party approval and is recorded as a compliance event

### 2.7 Security & Compliance Posture

| Control | Implementation |
|---|---|
| Encryption at rest | AES-256 via AWS KMS; tenant-specific key hierarchy |
| Encryption in transit | TLS 1.2+ enforced at gateway and between all services |
| Access control | RBAC enforced at API gateway + service level; no UI-only enforcement |
| 42 CFR Part 2 | SUD records flagged at row level; separate consent check before any disclosure |
| HIPAA Minimum Necessary | Field-level access controls; PHI not included in logs or error messages |
| SOC 2 Type II | Continuous control monitoring (Vanta or Drata); annual third-party audit |
| Disaster recovery | RTO ≤ 4 hours, RPO ≤ 1 hour; multi-AZ with automated failover |

---

## 3. Core Data Model

> **Approach:** Entities are defined one at a time with client approval before proceeding. Each entity specifies field name, data type, PHI classification, and storage/handling rules.

> **Phased scope:**
> **Phase 1** covers the minimum entities needed to support mock backend development and initial test coverage: Participant (already defined), User, Attendance, Claim, MARRecord, and Incident. **Phase 2** will add: CarePlan, Appointment, MedicationRefill, Reminder, and Consent. This phased approach keeps the mock backend simple while covering the highest-risk regulatory flows first.

### PHI Classification Key

| Class | Meaning | Handling Rule |
|---|---|---|
| **Direct Identifier** | One of HIPAA §164.514(b)'s 18 listed identifiers (name, DOB, SSN, address, phone, email, account numbers, geographic data below state level, dates except year) | Encrypted at rest (AES-256, field-level); never appear in logs or error messages |
| **Clinical PHI** | Health condition, diagnosis, treatment, or functional information linked to an individual | Encrypted at rest; access restricted to clinical roles |
| **42 CFR Part 2** | Substance use disorder record or flag; disclosure requires explicit patient consent even within the platform | Encrypted at rest; row-level consent gate before any read; every disclosure separately audit-logged |
| **Non-PHI** | System or administrative field not directly identifying or describing an individual's health | Standard encryption at rest; no special access restriction |

---

### 3.1 Participant

The Participant is the central entity of the platform. Every clinical, billing, scheduling, and administrative record in all 8 modules links back to a Participant.

#### 3.1.1 Identity & Demographics

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `participant_id` | UUID (PK) | Non-PHI | Synthetic primary key; never expose SSN or Medicaid ID as a key |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries must filter by this |
| `first_name` | VARCHAR(100) | Direct Identifier | Encrypted at rest |
| `last_name` | VARCHAR(100) | Direct Identifier | Encrypted at rest |
| `middle_name` | VARCHAR(100) | Direct Identifier | Encrypted at rest; nullable |
| `preferred_name` | VARCHAR(100) | Direct Identifier | Nullable |
| `date_of_birth` | DATE | Direct Identifier | Encrypted; age may be derived for display but DOB stored encrypted |
| `gender` | ENUM (`male`, `female`, `non_binary`, `unknown`) | Clinical PHI | |
| `race` | VARCHAR(100) | Clinical PHI | Nullable; used for CMS quality reporting |
| `ethnicity` | VARCHAR(100) | Clinical PHI | Nullable; CMS reporting |
| `preferred_language` | VARCHAR(50) | Clinical PHI | Drives care plan and reminder language |
| `ssn_encrypted` | VARCHAR(256) | Direct Identifier | Stored as AES-256 encrypted ciphertext; last 4 digits available as `ssn_last4` for display |
| `ssn_last4` | CHAR(4) | Direct Identifier | Derived; stored separately for UI display without decrypting full SSN |

#### 3.1.2 Insurance & Program Identifiers

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `medicaid_id` | VARCHAR(20) | Direct Identifier | Encrypted; required for Medicaid billing |
| `medicare_id` | VARCHAR(20) | Direct Identifier | Encrypted; MBI format; nullable if not Medicare-enrolled |
| `primary_payer_id` | UUID (FK → Payer) | Non-PHI | References payer entity, not PHI itself |
| `primary_policy_number` | VARCHAR(50) | Direct Identifier | Encrypted |
| `secondary_payer_id` | UUID (FK → Payer) | Non-PHI | Nullable |
| `secondary_policy_number` | VARCHAR(50) | Direct Identifier | Encrypted; nullable |
| `npi_attending_physician` | VARCHAR(10) | Non-PHI | NPI is a public provider identifier, not participant PHI |

#### 3.1.3 Contact Information

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `address_line_1` | VARCHAR(200) | Direct Identifier | Encrypted |
| `address_line_2` | VARCHAR(200) | Direct Identifier | Encrypted; nullable |
| `city` | VARCHAR(100) | Direct Identifier | Encrypted |
| `state` | CHAR(2) | Non-PHI | Two-letter state code; state alone is not a HIPAA identifier |
| `zip_code` | VARCHAR(10) | Direct Identifier | First 3 digits may be used for de-identified reporting; full ZIP is a Direct Identifier |
| `phone_primary` | VARCHAR(20) | Direct Identifier | Encrypted |
| `phone_secondary` | VARCHAR(20) | Direct Identifier | Encrypted; nullable |
| `email` | VARCHAR(254) | Direct Identifier | Encrypted; used for reminder/portal access |

#### 3.1.4 Emergency Contact

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `emergency_contact_name` | VARCHAR(200) | Direct Identifier | PHI because it is associated with and links back to the participant |
| `emergency_contact_relationship` | VARCHAR(50) | Clinical PHI | e.g., spouse, child, legal guardian |
| `emergency_contact_phone` | VARCHAR(20) | Direct Identifier | Encrypted |

#### 3.1.5 Clinical & Program Information

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `primary_diagnosis_code` | VARCHAR(10) | Clinical PHI | ICD-10-CM code |
| `secondary_diagnosis_codes` | JSONB | Clinical PHI | Array of ICD-10 codes; nullable |
| `is_sud_record` | BOOLEAN | **42 CFR Part 2** | If `true`, all records for this participant are subject to Part 2 consent controls; flag itself is Part 2-protected |
| `functional_level` | ENUM (`independent`, `supervised`, `assisted`, `dependent`) | Clinical PHI | Used in care plan and billing |
| `mobility_status` | ENUM (`ambulatory`, `wheelchair`, `bedridden`, `other`) | Clinical PHI | Informs transport and MAR |
| `attending_physician_id` | UUID (FK → Provider) | Clinical PHI | Links to physician scheduling and care plan orders |

#### 3.1.6 Program Enrollment

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `enrollment_date` | DATE | Direct Identifier | Dates of service are HIPAA identifiers |
| `discharge_date` | DATE | Direct Identifier | Nullable; set on discharge |
| `program_status` | ENUM (`active`, `on_leave`, `discharged`, `deceased`) | Clinical PHI | |
| `authorized_units_per_week` | INTEGER | Non-PHI | Authorization quantity; not PHI in isolation |
| `discharge_reason` | VARCHAR(500) | Clinical PHI | Nullable |

#### 3.1.7 Record Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC; set on insert |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC; updated on every write |
| `created_by` | UUID (FK → User) | Non-PHI | Staff user who created the record |
| `updated_by` | UUID (FK → User) | Non-PHI | Staff user who last modified the record |
| `version` | INTEGER | Non-PHI | Optimistic locking; incremented on each update |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period |

---

#### 3.1.8 Relationships to All 8 Core Modules

| Module | Relationship | Cardinality | Key Link | Notes |
|---|---|---|---|---|
| **Attendance Tracking** | A participant has attendance records | 1 → Many | `attendance.participant_id` | Each attendance record captures a date, sign-in/sign-out time, and authorized units consumed |
| **Insurance Billing & Claims** | A participant is the subject of insurance claims | 1 → Many | `claim.participant_id` | Claims reference Medicaid/Medicare IDs, payer, and dates of service from attendance |
| **Care Plan Management** | A participant has one active care plan at a time; historical plans are versioned | 1 → Many (versioned) | `care_plan.participant_id` | Care plans reference diagnosis codes and functional level from Participant |
| **Incident Reporting** | A participant may be involved in zero or more incidents | 1 → Many | `incident_report.participant_id` | Incident records inherit the `is_sud_record` flag for 42 CFR Part 2 handling |
| **Physician Appointments** | A participant has scheduled appointments with providers | 1 → Many | `appointment.participant_id` | Links to `attending_physician_id`; FHIR Appointment resource generated per record |
| **Reminder & Tracking App** | A participant (or their family) receives reminders and notifications | 1 → Many | `reminder.participant_id` | No PHI in notification payloads; deep-links to authenticated session |
| **Medication Administration Records (MAR)** | A participant has medication administration records | 1 → Many | `mar_record.participant_id` | If `is_sud_record = true`, MAR records for SUD medications require Part 2 consent before disclosure |
| **Medication Refill** | A participant has medication refill requests | 1 → Many | `refill_request.participant_id` | FHIR MedicationRequest generated per refill; pharmacy disclosure logged under audit layer |

---

#### 3.1.9 Unique Constraint

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_participant_medicaid_id` | `tenant_id`, `medicaid_id` | Per tenant | Return HTTP 409 with validation error; do not create a second record |

**Rule:** A Medicaid ID may be registered to at most one Participant per tenant. A duplicate attempt — regardless of participant name or enrollment date — must be rejected at the application layer before reaching the database, with the database enforcing the same constraint as a backstop.

**Implementation:**
- Database: `UNIQUE (tenant_id, medicaid_id)` index on the `participant` table
- Application: pre-insert existence check returns a `409 Conflict` with error code `PARTICIPANT_DUPLICATE_MEDICAID_ID` before the insert is attempted
- Error message exposed to the client: `"A participant with this Medicaid ID is already registered in this program."`

**Billing integrity rationale:** Duplicate Medicaid IDs within a tenant would produce conflicting claim submissions for the same beneficiary, triggering payer rejection and potential fraud flags under CMS audit rules.

**Test case target:** Integration test must attempt to POST a second participant with the same `medicaid_id` within the same tenant and assert a `409` response with error code `PARTICIPANT_DUPLICATE_MEDICAID_ID`.

---

> **Pending approval before continuing to next entity.**

---

### 3.2 User

The User entity represents any person who authenticates into the Care Art platform — staff, external providers, and family/participant portal users. User records are **not PHI** (they describe workforce members or authorized representatives, not patients). Fields containing personal information are classified as **Workforce PII**, governed by HIPAA's workforce provisions (§164.308(a)(3)) rather than the PHI rules that apply to Participant data.

> **Phase 1 scope:** minimal fields sufficient for authentication, RBAC enforcement, tenant isolation, and audit trail attribution. No preference or notification settings — those belong to Phase 2.

#### 3.2.1 Identity

| Field | Data Type | Classification | RBAC Role | Notes |
|---|---|---|---|---|
| `user_id` | UUID (PK) | Non-PHI | — | Synthetic key; referenced as `created_by` / `updated_by` on all other entities |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | — | All queries must filter by this; a user can belong to exactly one tenant |
| `first_name` | VARCHAR(100) | Workforce PII | — | Displayed in UI and audit log entries |
| `last_name` | VARCHAR(100) | Workforce PII | — | |
| `email` | VARCHAR(254) | Workforce PII | — | Unique within tenant; primary login credential and notification address |
| `phone` | VARCHAR(20) | Workforce PII | — | Nullable; used for MFA SMS fallback |

#### 3.2.2 Role & Permissions

| Field | Data Type | Classification | RBAC Role | Notes |
|---|---|---|---|---|
| `role` | ENUM | Non-PHI | **Primary RBAC driver** | See role mapping table below; enforced at API Gateway and service level — never UI-only |
| `is_external` | BOOLEAN | Non-PHI | — | `true` for Physician and Participant/Family roles; restricts accessible tenants and modules |

**Role enum → Section 1.1 mapping:**

| `role` Value | Section 1.1 Role | Module Access Scope |
|---|---|---|
| `program_administrator` | Program Administrator | Attendance, Billing, Reporting |
| `care_coordinator` | Care Coordinator | Care Plans, Incidents, Appointments |
| `nurse_medication_aide` | Nurse / Medication Aide | MAR, Medication Refill, Care Plans |
| `billing_specialist` | Billing Specialist | Insurance Billing, Claims, Remittance |
| `physician` | Physician (external) | Appointments, Care Plan Orders (read/sign only) |
| `participant_family` | Participant / Family | Reminders, Appointment Tracking (read-only portal) |
| `compliance_officer` | Compliance Officer | All modules + audit logs |

#### 3.2.3 Credentials & MFA

| Field | Data Type | Classification | RBAC Role | Notes |
|---|---|---|---|---|
| `password_hash` | VARCHAR(256) | Workforce PII | — | bcrypt or Argon2id; plaintext password never stored |
| `mfa_enabled` | BOOLEAN | Non-PHI | — | MFA mandatory for all roles with PHI access (all except `participant_family`) |
| `mfa_secret_encrypted` | VARCHAR(512) | Workforce PII | — | TOTP seed; AES-256 encrypted at rest; nullable until MFA enrolled |
| `failed_login_count` | SMALLINT | Non-PHI | — | Reset to 0 on successful login |
| `locked_until` | TIMESTAMPTZ | Non-PHI | — | Nullable; account locked after 5 consecutive failures; auto-unlocks after 30 min |
| `password_changed_at` | TIMESTAMPTZ | Non-PHI | — | Used to enforce 90-day password rotation policy |

#### 3.2.4 Status

| Field | Data Type | Classification | RBAC Role | Notes |
|---|---|---|---|---|
| `status` | ENUM (`active`, `inactive`, `suspended`, `pending_activation`) | Non-PHI | **Secondary RBAC gate** | `inactive` and `suspended` users are denied all access at API Gateway before role is evaluated |
| `deactivated_at` | TIMESTAMPTZ | Non-PHI | — | Nullable; set when status moves to `inactive`; user record is never deleted (audit trail integrity) |
| `last_login_at` | TIMESTAMPTZ | Non-PHI | — | Used to detect and auto-deactivate dormant accounts (90-day inactivity policy) |

#### 3.2.5 Audit Metadata

| Field | Data Type | Classification | RBAC Role | Notes |
|---|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | — | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | — | UTC; updated on every write |
| `created_by` | UUID (FK → User) | Non-PHI | — | Admin who provisioned the account |
| `updated_by` | UUID (FK → User) | Non-PHI | — | Last modifier |
| `version` | INTEGER | Non-PHI | — | Optimistic locking |

---

#### 3.2.6 RBAC Enforcement Notes

- `tenant_id` + `status` + `role` are evaluated in that order on every request. A user who is `active` with a valid role but mismatched `tenant_id` is denied.
- `role` is the only field that controls module-level access. No other User field grants or restricts permissions.
- `is_external` additionally prevents external users (`physician`, `participant_family`) from accessing internal staff endpoints regardless of role.
- User records are **never hard-deleted**. Deactivation is the only supported offboarding action, preserving `user_id` references in all audit logs and PHI records.

---

#### 3.2.7 Unique Constraints

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_user_id` | `user_id` | Global (all tenants) | Enforced by primary key; UUID generation makes collision negligible but constraint is explicit |
| `uq_user_email_tenant` | `tenant_id`, `email` | Per tenant | Return HTTP 409 with validation error; do not create a second account |

**Rules:**
- `user_id` is a system-generated UUID and must be globally unique across all tenants. This is the stable identifier referenced by every audit log entry and every PHI record's `created_by` / `updated_by` field.
- `email` must be unique within a tenant. A staff member cannot hold two accounts in the same program. The same email address may exist in different tenants (the same nurse could work at two ADCP operators), so uniqueness is scoped per tenant, not globally.

**Implementation:**
- Database: `PRIMARY KEY (user_id)` for global uniqueness; `UNIQUE (tenant_id, email)` index for per-tenant email uniqueness
- Application: pre-insert existence check on `(tenant_id, email)` returns `409 Conflict` with error code `USER_DUPLICATE_EMAIL` before the insert is attempted
- Error message exposed to the client: `"An account with this email address already exists in this program."`

**Test case target:** Integration test must attempt to POST a second user with the same `email` within the same tenant and assert a `409` response with error code `USER_DUPLICATE_EMAIL`. A separate test must confirm the same email is accepted in a different tenant.

---

> **Pending approval before proceeding to 3.3 Attendance.**

---

### 3.3 Attendance

The Attendance entity records a single day of service for one participant — their arrival, departure, total time present, and the billable service units consumed. It is the source of truth that downstream billing (Claim) uses to generate Medicaid and Medicare claims. Every confirmed Attendance record with units consumed is a potential claim line.

> **Phase 1 scope:** fields required for sign-in/sign-out workflows, unit calculation, billing handoff, and audit trail. Transport, notes, and exception flags are Phase 2.

#### 3.3.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `attendance_id` | UUID (PK) | Non-PHI | Synthetic primary key |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries filter by this |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Links this attendance record to the participant; inherits `is_sud_record` flag from Participant |

#### 3.3.2 Date & Time of Service

| Field | Data Type | PHI Class | Billing Mapping | Notes |
|---|---|---|---|---|
| `date_of_service` | DATE | **Direct Identifier** | → Claim line service date (Loop 2400 DTP\*472 in 837P) | HIPAA identifier; encrypted at rest |
| `sign_in_time` | TIMETZ | **Direct Identifier** | — | Time of day only; combined with `date_of_service` for full timestamp |
| `sign_out_time` | TIMETZ | **Direct Identifier** | — | Nullable until participant departs |
| `total_hours` | NUMERIC(4,2) | Clinical PHI | → Used to calculate `authorized_units_consumed` | Derived from sign-in/sign-out; stored to avoid recalculation drift; recalculated on any time edit |

#### 3.3.3 Billing Units

| Field | Data Type | PHI Class | Billing Mapping | Notes |
|---|---|---|---|---|
| `service_type_code` | VARCHAR(10) | Non-PHI | → Procedure code on claim line (Loop 2400 SV1\*HC in 837P) | e.g., `T2021` (Medicaid adult day health); `S5100` (adult day care); populated from program configuration, not user input |
| `authorized_units_consumed` | NUMERIC(6,2) | Clinical PHI | → Claim line quantity (Loop 2400 SV1, element 4 in 837P); → Medicare HIPPS or revenue code units on 837I | Units of service per payer definition — typically 15-min increments (1 unit = 0.25 hr) for Medicaid; daily rate (1 unit = 1 day) for some Medicare programs; calculated from `total_hours` and program's unit definition |
| `authorized_units_remaining` | NUMERIC(6,2) | Clinical PHI | → Drives billing authorization check before claim submission | Pulled from participant's weekly authorization at time of sign-in; stored as a snapshot to preserve the value at time of service |

#### 3.3.4 Staff & Status

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `recorded_by` | UUID (FK → User) | Non-PHI | Staff member who created or last edited the entry; surfaced in audit log |
| `status` | ENUM (`pending`, `confirmed`, `billed`, `voided`) | Non-PHI | Only `confirmed` records are eligible for claim generation; `billed` set when a Claim references this record; `voided` blocks billing and requires a reason |
| `void_reason` | VARCHAR(500) | Non-PHI | Nullable; required when `status = voided` |

#### 3.3.5 Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `created_by` | UUID (FK → User) | Non-PHI | |
| `updated_by` | UUID (FK → User) | Non-PHI | |
| `version` | INTEGER | Non-PHI | Optimistic locking; any edit to a `confirmed` record resets status to `pending` and requires re-confirmation |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period |

---

#### 3.3.6 Medicaid & Medicare Billing Field Map

| Claim Type | Standard | Attendance Field | Maps To |
|---|---|---|---|
| Medicaid | EDI X12 837P | `participant_id` → Participant.medicaid_id | Loop 2010BA — Subscriber Name / ID |
| Medicaid | EDI X12 837P | `date_of_service` | Loop 2400 DTP\*472 — Date of Service |
| Medicaid | EDI X12 837P | `service_type_code` | Loop 2400 SV1 — Procedure Code |
| Medicaid | EDI X12 837P | `authorized_units_consumed` | Loop 2400 SV1 — Units of Service |
| Medicare | EDI X12 837I | `participant_id` → Participant.medicare_id | Loop 2010BA — Subscriber MBI |
| Medicare | EDI X12 837I | `date_of_service` | Loop 2400 DTP\*472 — Service Date |
| Medicare | EDI X12 837I | `authorized_units_consumed` | Loop 2300/2400 — Revenue Code Units |

> A Claim record (3.4) is the formal billing artifact. Attendance is the source; Claim is the submission. One Claim may reference one or more Attendance records as line items.

---

#### 3.3.7 Unique Constraint

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_attendance_participant_date` | `tenant_id`, `participant_id`, `date_of_service` | Per tenant | Return HTTP 409 with validation error; do not create a second record |

**Rule:** A participant may have at most one Attendance record per date of service within a tenant. A duplicate attempt — regardless of sign-in time or recorded-by user — must be rejected at the application layer before reaching the database, and the database enforces the same constraint as a backstop.

**Implementation:**
- Database: `UNIQUE (tenant_id, participant_id, date_of_service)` index on the `attendance` table
- Application: pre-insert existence check returns a `409 Conflict` with error code `ATTENDANCE_DUPLICATE_DATE` before the insert is attempted
- Error message exposed to the client: `"An attendance record for this participant already exists for the selected date of service."`

**Billing integrity rationale:** Duplicate attendance records would produce duplicate claim lines for the same date of service, triggering payer rejection, overpayment liability, and potential fraud flags under CMS audit rules.

**Test case target:** This constraint must be covered by an integration test that attempts to POST a second attendance record for the same `participant_id` and `date_of_service` within the same tenant and asserts a `409` response with error code `ATTENDANCE_DUPLICATE_DATE`.

---

> **Pending approval before proceeding to 3.4 Claim.**

---

### 3.4 Claim

The Claim entity is the formal billing artifact submitted to a payer (Medicaid or Medicare) on behalf of a participant. It is generated from one or more confirmed Attendance records and carries the financial and regulatory data required for EDI X12 837 submission. A Claim is never created manually — it is always derived from Attendance.

> **Phase 1 scope:** single primary payer (Medicaid or Medicare) per claim. Secondary payer coordination of benefits (COB) and managed care organization (MCO) fields are deferred to Phase 2.

#### 3.4.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `claim_id` | UUID (PK) | Non-PHI | System-generated; never user-supplied |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Resolves to Medicaid ID or Medicare MBI at submission time; not stored directly on the claim to avoid ID duplication |
| `attendance_ids` | UUID[] | Clinical PHI | Array of Attendance record IDs covered by this claim; each referenced record must have `status = confirmed` at claim creation |

#### 3.4.2 Payer & Service

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `payer_type` | ENUM (`medicaid`, `medicare`) | Non-PHI | Determines EDI format (837P for Medicaid, 837I for Medicare) and ID field used from Participant; Phase 2 adds `secondary` |
| `claim_reference_number` | VARCHAR(50) | **Direct Identifier** | Globally unique; system-generated per payer format (e.g., NPI + date + sequence); HIPAA account number identifier; encrypted at rest |
| `procedure_code` | VARCHAR(10) | Clinical PHI | e.g., `T2021`, `S5100`; must match `service_type_code` on referenced Attendance records |
| `date_of_service_start` | DATE | **Direct Identifier** | Earliest date of service across referenced Attendance records; HIPAA identifier; encrypted at rest |
| `date_of_service_end` | DATE | **Direct Identifier** | Latest date of service across referenced Attendance records; nullable if single-day claim |

#### 3.4.3 Billing Amounts

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `units_billed` | NUMERIC(6,2) | Clinical PHI | Sum of `authorized_units_consumed` across all referenced Attendance records |
| `amount` | NUMERIC(10,2) | Clinical PHI | Billed amount in USD; calculated as `units_billed × payer rate`; payer rate comes from program fee schedule configuration |

#### 3.4.4 Claim Status & Dates

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `claim_status` | ENUM (`draft`, `submitted`, `accepted`, `rejected`, `paid`) | Clinical PHI | State machine: `draft` → `submitted` → `accepted` or `rejected`; `accepted` → `paid` on remittance |
| `submission_date` | TIMESTAMPTZ | **Direct Identifier** | Nullable; set when claim is transmitted to clearinghouse; encrypted at rest |
| `remittance_date` | TIMESTAMPTZ | **Direct Identifier** | Nullable; set when 835 remittance advice is received; encrypted at rest |
| `rejection_reason` | VARCHAR(1000) | Clinical PHI | Nullable; populated from payer 277CA or 835 claim adjustment reason codes on rejection |

#### 3.4.5 Staff & Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_by` | UUID (FK → User) | Non-PHI | User who initiated claim generation; typically `billing_specialist` or `program_administrator` role |
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_by` | UUID (FK → User) | Non-PHI | |
| `version` | INTEGER | Non-PHI | Optimistic locking; a submitted or paid claim cannot be updated — only voided and resubmitted |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period |

---

#### 3.4.6 Unique Constraints

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_claim_reference_number` | `claim_reference_number` | Global (all tenants) | Return HTTP 409 with error code `CLAIM_DUPLICATE_REFERENCE`; generation logic must retry with next sequence value |
| `uq_claim_participant_dos_procedure_payer` | `tenant_id`, `participant_id`, `date_of_service_start`, `procedure_code`, `payer_type` | Per tenant | Return HTTP 409 with error code `CLAIM_DUPLICATE`; prevents double-billing the same service to the same payer |

**Rules:**
- `claim_reference_number` must be globally unique across all tenants. If the generation algorithm produces a collision (rare), the system retries with an incremented sequence — it does not surface the collision as a user error.
- The combination of `participant_id + date_of_service_start + procedure_code + payer_type` within a tenant must be unique. A second claim for the same participant, start date, procedure, and payer is always a duplicate billing attempt, regardless of units or amount.

**Implementation:**
- Database: `UNIQUE (claim_reference_number)` global index; `UNIQUE (tenant_id, participant_id, date_of_service_start, procedure_code, payer_type)` composite index
- Application: pre-insert check on the composite key returns `409 Conflict` with error code `CLAIM_DUPLICATE` before insert is attempted
- Error message exposed to the client: `"A claim for this participant, date of service, procedure, and payer already exists."`

**Test case targets:**
- Integration test must attempt to POST a second claim with the same `participant_id`, `date_of_service_start`, `procedure_code`, and `payer_type` within the same tenant and assert `409` with `CLAIM_DUPLICATE`.
- Integration test must verify that a `submitted` or `paid` claim cannot be updated in place — only its `claim_status` may transition following the allowed state machine.

---

#### 3.4.7 Phase 2 Deferred Fields

> The following fields are intentionally excluded from Phase 1 to keep the mock backend minimal. They will be added in Phase 2 when secondary billing and MCO workflows are implemented.

| Deferred Field | Purpose |
|---|---|
| `secondary_payer_id` | Coordination of benefits (COB) — secondary payer reference |
| `secondary_claim_reference_number` | Reference number for secondary payer submission |
| `secondary_amount` | Amount billed to secondary payer after primary remittance |
| `mco_id` | Managed care organization identifier for managed Medicaid plans |
| `prior_authorization_number` | PA number required by some Medicaid MCOs before claim submission |
| `adjustment_reason_codes` | Structured payer adjustment codes from 835 remittance (Phase 1 stores raw in `rejection_reason`) |

---

> **Pending approval before proceeding to 3.5 MARRecord.**

---

### 3.5 MARRecord

The MARRecord entity captures each individual instance of a medication being administered to a participant — the electronic medication administration record (eMAR). Each record corresponds to one scheduled medication event. MARRecord is one of the highest-risk entities in the platform: it contains clinical PHI, may carry 42 CFR Part 2 protections when a controlled substance is involved, and its write operations are restricted to a single staff role.

> **Phase 1 scope:** single administration event per record. Recurring schedule templates, PRN (as-needed) medication workflows, and pharmacy dispense linkage are Phase 2.

#### 3.5.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `mar_id` | UUID (PK) | Non-PHI | System-generated; never user-supplied |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries filter by this |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Inherits `is_sud_record` flag from Participant; combined with `is_controlled_substance` to determine Part 2 gate (see 3.5.6) |

#### 3.5.2 Medication Details

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `medication_name` | VARCHAR(200) | Clinical PHI | Full medication name including strength, e.g., `Metformin 500mg`; encrypted at rest |
| `dose` | VARCHAR(100) | Clinical PHI | Human-readable dose expression, e.g., `1 tablet`, `5mL`, `10 units`; encrypted at rest |
| `route` | ENUM (`oral`, `injection`, `topical`) | Clinical PHI | Route of administration |

#### 3.5.3 Administration Event

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `scheduled_time` | TIMESTAMPTZ | **Direct Identifier** | The time the medication was scheduled to be administered; HIPAA date/time identifier; encrypted at rest; part of unique constraint |
| `administered_time` | TIMESTAMPTZ | **Direct Identifier** | Actual time of administration; nullable — null when `status` is `refused`, `held`, or `missed`; encrypted at rest |
| `administered_by` | UUID (FK → User) | Non-PHI | Must resolve to a User with `role = nurse_medication_aide`; enforced at application layer on write; any other role is rejected with `403 Forbidden` |
| `status` | ENUM (`administered`, `refused`, `held`, `missed`) | Clinical PHI | `administered` requires `administered_time` to be non-null; `refused`, `held`, `missed` set `administered_time` to null |
| `notes` | VARCHAR(1000) | Clinical PHI | Nullable; required when `status = refused` or `held` to document clinical rationale; encrypted at rest |

#### 3.5.4 Regulatory Flag

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `is_controlled_substance` | BOOLEAN | **42 CFR Part 2** | When `true`, this record is subject to elevated access controls (see 3.5.6); the flag itself is treated as 42 CFR Part 2-protected and must not appear in non-privileged API responses or logs |

#### 3.5.5 Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `created_by` | UUID (FK → User) | Non-PHI | Must match `administered_by` in normal workflows; a supervisor override creates a separate audit event |
| `updated_by` | UUID (FK → User) | Non-PHI | |
| `version` | INTEGER | Non-PHI | Optimistic locking; an `administered` record may not be edited — only a correction record may be appended with reference to the original `mar_id` |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period |

---

#### 3.5.6 Unique Constraint

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_mar_participant_medication_scheduled_time` | `tenant_id`, `participant_id`, `medication_name`, `scheduled_time` | Per tenant | Return HTTP 409 with error code `MAR_DUPLICATE_EVENT`; do not create a second record |

**Rule:** A participant may have at most one MAR record per medication per scheduled time within a tenant. A duplicate attempt — regardless of dose, route, or administering user — must be rejected at the application layer before reaching the database, with the database enforcing the constraint as a backstop.

**Implementation:**
- Database: `UNIQUE (tenant_id, participant_id, medication_name, scheduled_time)` index on the `mar_record` table
- Application: pre-insert existence check returns `409 Conflict` with error code `MAR_DUPLICATE_EVENT` before the insert is attempted
- Error message exposed to the client: `"A medication administration record for this participant, medication, and scheduled time already exists."`

**Test case target:** Integration test must attempt to POST a second MAR record with the same `participant_id`, `medication_name`, and `scheduled_time` within the same tenant and assert a `409` response with error code `MAR_DUPLICATE_EVENT`.

---

#### 3.5.7 Role Restriction on Write

`administered_by` must reference a User with `role = nurse_medication_aide`. This restriction is enforced at the application service layer on every create and update operation, independently of the API Gateway RBAC check.

| Operation | Permitted Roles | Enforcement Point |
|---|---|---|
| Create MAR record | `nurse_medication_aide` only | Application service (pre-insert role check) |
| Update MAR record | `nurse_medication_aide` only (corrections require supervisor counter-signature — Phase 2) | Application service |
| Read MAR record (non-controlled) | `nurse_medication_aide`, `care_coordinator`, `compliance_officer`, `program_administrator` | API Gateway RBAC |
| Read MAR record (`is_controlled_substance = true`) | `nurse_medication_aide`, `compliance_officer` only | Application service (Part 2 gate — see 3.5.8) |

---

#### 3.5.8 42 CFR Part 2 Compliance Note

When `is_controlled_substance = true`, the MARRecord is subject to 42 CFR Part 2 access controls, layered on top of the standard HIPAA PHI protections.

**Access restriction:**
- Read and write access is limited to `nurse_medication_aide` and `compliance_officer` roles regardless of any other RBAC permission
- The `is_controlled_substance` flag is evaluated at the application service layer on every read — it is not sufficient to filter at the API Gateway
- API responses for unauthorized role requests return `403 Forbidden` with no indication of the record's existence (to avoid confirming that a controlled substance record exists for the participant)

**Audit logging requirement:**
- Every read and every write on a record where `is_controlled_substance = true` must be captured in the audit log with: user identity (`user_id`), `tenant_id`, `mar_id`, action type (`PHI_READ` or `PHI_WRITE`), timestamp, and outcome
- This logging is mandatory and non-bypassable — the audit event must be emitted before the response is returned to the caller
- Failed access attempts (role not permitted) are also logged with action type `ACCESS_DENIED`

**Relationship to Participant.is_sud_record:**
- The strictest controls apply when both `MARRecord.is_controlled_substance = true` AND `Participant.is_sud_record = true` — this combination indicates a controlled substance administered as part of SUD treatment, which is the core scope of 42 CFR Part 2
- When `is_controlled_substance = true` but `is_sud_record = false`, the record may represent a controlled substance unrelated to SUD treatment (e.g., pain management); elevated access controls still apply per this design, but the full Part 2 consent gate for external disclosure is driven by `is_sud_record` on the Participant

**External disclosure:**
- No MARRecord where `is_controlled_substance = true` may be disclosed outside the platform (to physicians, pharmacies, or any third party) without explicit patient consent documented in the system, consistent with 42 CFR Part 2 §2.31

---

> **Pending approval before proceeding to 3.6 Incident.**

---

### 3.6 Incident

The Incident entity records a reportable event involving a participant — a fall, medication error, behavioral incident, medical emergency, or other occurrence requiring documentation. Incident records are subject to state adult day care licensing regulations and, when `is_sud_related = true`, to 42 CFR Part 2 controls. Severe incidents and medical emergencies trigger a mandatory state notification workflow with a 24-hour deadline.

> **Phase 1 scope:** single-participant incidents with state notification workflow. Multi-participant incidents, witness statements, corrective action plans, and insurance notification are Phase 2.

#### 3.6.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `incident_id` | UUID (PK) | Non-PHI | System-generated; globally unique across all tenants; the only unique constraint on this entity (see 3.6.7) |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Inherits `is_sud_record` flag from Participant; combined with `is_sud_related` to determine Part 2 gate (see 3.6.9) |

#### 3.6.2 Incident Details

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `incident_date` | DATE | **Direct Identifier** | Date the incident occurred; HIPAA identifier; encrypted at rest |
| `incident_time` | TIMETZ | **Direct Identifier** | Time of occurrence; encrypted at rest; nullable if exact time unknown |
| `incident_type` | ENUM (`fall`, `medication_error`, `behavioral`, `medical_emergency`, `other`) | Clinical PHI | `medical_emergency` triggers mandatory 24-hour state notification regardless of severity (see 3.6.8) |
| `description` | TEXT | Clinical PHI | Narrative account of the incident; encrypted at rest; may contain participant names, staff observations, and clinical detail — treated as high-sensitivity PHI |
| `location` | VARCHAR(200) | Clinical PHI | Facility room or area where the incident occurred, e.g., `"Day room"`, `"Restroom B"`; encrypted at rest |

#### 3.6.3 Reporting & Severity

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `reported_by` | UUID (FK → User) | Non-PHI | Staff member who created the incident record; any staff role may report; surfaced in audit log |
| `severity` | ENUM (`minor`, `moderate`, `severe`) | Clinical PHI | `severe` triggers mandatory 24-hour state notification regardless of incident type (see 3.6.8) |

#### 3.6.4 Status & Regulatory Tracking

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `status` | ENUM (`draft`, `submitted`, `escalated`, `closed`) | Non-PHI | State machine enforced at application layer (see 3.6.8); `escalated` is mandatory for severe/medical_emergency incidents before `closed` is permitted |
| `regulatory_submission_date` | DATE | **Direct Identifier** | Nullable; set when the incident report is transmitted to the state regulator; HIPAA date identifier; encrypted at rest |

#### 3.6.5 Regulatory Flag

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `is_sud_related` | BOOLEAN | **42 CFR Part 2** | When `true`, this incident record is subject to Part 2 access controls (see 3.6.9); the flag itself is Part 2-protected and must not appear in non-privileged API responses |

#### 3.6.6 Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `created_by` | UUID (FK → User) | Non-PHI | |
| `updated_by` | UUID (FK → User) | Non-PHI | |
| `version` | INTEGER | Non-PHI | Optimistic locking; a `closed` incident cannot be edited — a new incident or addendum must be created |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period |

---

#### 3.6.7 Unique Constraint

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `pk_incident_id` | `incident_id` | Global (all tenants) | Enforced by primary key; UUID generation makes collision negligible but constraint is explicit |

**Rule:** `incident_id` is the only unique constraint on this entity. A participant may have multiple incidents on the same date, including multiple incidents of the same type, because real incidents are distinct events that each require independent documentation. No composite key constraint is applied — every incident gets its own record and its own regulatory tracking lifecycle.

---

#### 3.6.8 Regulatory Workflow Note — 24-Hour State Notification

State adult day care licensing regulations require notification to the state regulator within 24 hours when an incident meets either of the following conditions:

| Trigger | Field | Value |
|---|---|---|
| Severity trigger | `severity` | `severe` |
| Type trigger | `incident_type` | `medical_emergency` |

**Status state machine:**

| Path | Transitions | Condition |
|---|---|---|
| Standard | draft → submitted → closed | Minor / moderate, non-emergency |
| Escalation | draft → submitted → escalated → closed | Severe OR medical_emergency |
| Regulatory deadline | escalated: regulatory_submission_date must be set before closing | Within 24 hours of escalation |

**Enforcement rules:**
- When `severity = severe` OR `incident_type = medical_emergency`, the application must automatically transition `status` to `escalated` on submission and block the `closed` transition until `regulatory_submission_date` is set
- A `closed` transition on an escalated incident without `regulatory_submission_date` must return `422 Unprocessable Entity` with error code `INCIDENT_MISSING_REGULATORY_SUBMISSION`
- An async job (Phase 1: cron; Phase 2: event-driven) checks all `escalated` incidents hourly and raises an alert if `regulatory_submission_date` is null and `created_at` is more than 20 hours ago — providing a 4-hour buffer before the 24-hour deadline

**Test case targets:**
- POST an incident with `severity = severe` → assert `status` is automatically set to `escalated`
- POST an incident with `incident_type = medical_emergency` → assert `status` is automatically set to `escalated`
- Attempt to PATCH `status = closed` on an `escalated` incident without `regulatory_submission_date` → assert `422` with `INCIDENT_MISSING_REGULATORY_SUBMISSION`
- PATCH `regulatory_submission_date` on an escalated incident, then PATCH `status = closed` → assert `200` and final `closed` state
- POST an incident with `severity = minor` and `incident_type = fall` → assert `status` remains `submitted` after submission (no auto-escalation)

---

#### 3.6.9 42 CFR Part 2 Compliance Note

When `is_sud_related = true`, the Incident record is subject to 42 CFR Part 2 access controls, consistent with the controls applied to MARRecord (3.5.8) and the `is_sud_record` flag on Participant (3.1.5).

**Access restriction:**
- Read and write access is limited to `care_coordinator`, `nurse_medication_aide`, and `compliance_officer` roles
- The `is_sud_related` flag is evaluated at the application service layer on every read — API responses for unauthorized roles return `403 Forbidden` with no indication of the record's existence
- `description` and `incident_type` fields are additionally redacted from list-view responses for unauthorized roles even when the participant is otherwise accessible

**Audit logging requirement:**
- Every read on a record where `is_sud_related = true` must be captured in the audit log with: `user_id`, `tenant_id`, `incident_id`, action type `PHI_READ`, timestamp, and outcome
- Every write must be logged with action type `PHI_WRITE` and `data_affected` listing field names changed (never field values)
- Failed access attempts are logged with `ACCESS_DENIED`

**Relationship to Participant.is_sud_record:**
- `is_sud_related = true` on an Incident does not require `Participant.is_sud_record = true`, because a non-SUD participant may be involved in an incident that is SUD-related (e.g., a behavioral incident triggered by another participant's SUD status). Each flag is evaluated independently.
- When both are true, the full Part 2 consent gate for external disclosure applies

---

### 3.7 Phase 1 Data Model — Completion Summary

All six Phase 1 entities are now defined. The table below summarizes the entity inventory, their primary regulatory obligations, unique constraints, and readiness for mock backend implementation.

| Entity | Section | Primary PHI Class | Regulatory Controls | Unique Constraint(s) | Mock Backend Ready |
|---|---|---|---|---|---|
| **Participant** | 3.1 | Direct Identifier + Clinical PHI | HIPAA · 42 CFR Part 2 (via `is_sud_record`) · CMS | `medicaid_id` unique per tenant | Yes |
| **User** | 3.2 | Workforce PII (not PHI) | HIPAA Workforce §164.308(a)(3) | `user_id` globally; `email` per tenant | Yes |
| **Attendance** | 3.3 | Direct Identifier + Clinical PHI | HIPAA · CMS billing integrity | `participant_id + date_of_service` per tenant | Yes |
| **Claim** | 3.4 | Direct Identifier + Clinical PHI | HIPAA · CMS (Medicaid/Medicare) · EDI X12 | `claim_reference_number` globally; composite per tenant | Yes |
| **MARRecord** | 3.5 | Clinical PHI + 42 CFR Part 2 | HIPAA · 42 CFR Part 2 (via `is_controlled_substance`) | `participant_id + medication_name + scheduled_time` per tenant | Yes |
| **Incident** | 3.6 | Direct Identifier + Clinical PHI + 42 CFR Part 2 | HIPAA · State licensing · 42 CFR Part 2 (via `is_sud_related`) | `incident_id` globally (PK only) | Yes |

**Cross-cutting controls confirmed across all Phase 1 entities:**
- Immutable audit log with mandatory fields (timestamp, user ID, action type, data affected) — Section 2.6
- Soft delete only — no hard deletes within HIPAA retention period
- Optimistic locking via `version` field on every entity
- Tenant isolation via `tenant_id` on every entity; all queries must filter by this
- PHI fields encrypted at rest (AES-256, field-level) across all entities
- 42 CFR Part 2 flag present on Participant (`is_sud_record`), MARRecord (`is_controlled_substance`), and Incident (`is_sud_related`) — evaluated independently and combined for strictest controls

**Phase 2 entities to be defined:** CarePlan, Appointment, MedicationRefill, Reminder, Consent.

---

### 3.8 CarePlan

The CarePlan entity represents an individualized, structured plan of care created for a participant by a care coordinator and signed by the attending physician before it may be activated. Each plan documents clinical goals, functional targets, and therapeutic interventions required to support the participant's health and program engagement. A participant has at most one active care plan at a time; when a plan is revised, the prior version is superseded and retained as an immutable historical record. Care plans snapshot the participant's current diagnosis codes and functional level at authorship time, serve as the clinical foundation for MAR administration goals, and are exchanged with physician EHR systems as FHIR CarePlan resources. This entity is the primary artifact of the Care Plan Management module (Section 1.2, module 3).

> **Phase 2 scope:** core plan fields, goal tracking, physician order integration, and FHIR resource linkage. Care team member assignments beyond the primary care coordinator, individual goal progress audit rows, and Reminder module integration for goal-based alerts are deferred to Phase 3.

#### 3.8.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `care_plan_id` | UUID (PK) | Non-PHI | System-generated; never user-supplied |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries must filter by this |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Central link to the Participant record; care plan inherits `is_sud_record` from Participant for 42 CFR Part 2 gate (see 3.8.9) |

#### 3.8.2 Plan Identity & Versioning

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `version_number` | INTEGER | Non-PHI | Plan revision number within this participant's history; starts at 1 on first plan creation, incremented on each full revision; distinct from the `version` field used for optimistic locking |
| `status` | ENUM (`draft`, `active`, `superseded`, `archived`) | Non-PHI | State machine enforced at application layer: `draft` → `active` (requires non-null `physician_signature_date`); `active` → `superseded` (when a new version is activated); `archived` is a terminal state for plans withdrawn without revision; at most one `active` plan is permitted per participant per tenant at any time (see 3.8.8) |
| `effective_date` | DATE | **Direct Identifier** | Date the plan takes effect clinically; HIPAA date identifier; must be non-null before `status` may transition to `active`; encrypted at rest |
| `review_date` | DATE | **Direct Identifier** | Scheduled date for plan review by the care coordinator and physician; HIPAA date identifier; encrypted at rest |
| `expiration_date` | DATE | **Direct Identifier** | Nullable; date after which the plan is no longer clinically valid without renewal; HIPAA date identifier; encrypted at rest; if null, plan remains in force until explicitly superseded or archived |

#### 3.8.3 Clinical Context

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `primary_diagnosis_code` | VARCHAR(10) | Clinical PHI | ICD-10-CM code; snapshotted from `Participant.primary_diagnosis_code` at plan creation; may be refined on the plan without updating the Participant record; changes to the Participant field after plan activation do not propagate to this field |
| `secondary_diagnosis_codes` | JSONB | Clinical PHI | Array of ICD-10-CM codes; nullable; snapshotted from `Participant.secondary_diagnosis_codes` at plan creation |
| `functional_level` | ENUM (`independent`, `supervised`, `assisted`, `dependent`) | Clinical PHI | Participant's functional level at the time the plan is authored; snapshotted from `Participant.functional_level`; does not auto-update if the Participant record changes — a changed functional level requires a plan revision |
| `notes` | TEXT | Clinical PHI | Free-text clinical narrative; encrypted at rest; nullable; may include care rationale, clinical observations, and contraindications; PHI values must never appear in audit log payloads |

#### 3.8.4 Goals — `care_plan_goal` Table

Goals are defined in a separate `care_plan_goal` table rather than a JSONB column on `care_plan`. This gives db_validator the ability to assert individual goal fields via SQL and aligns with the column-per-field pattern used by all Phase 1 entities. Each goal row belongs to exactly one care plan and is identified by its own UUID primary key.

**`care_plan_goal` — Core Reference**

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `goal_id` | UUID (PK) | Non-PHI | System-generated; never user-supplied |
| `care_plan_id` | UUID (FK → care_plan) | Non-PHI | Parent care plan; a goal may not exist without a parent; cascade-deleted if the parent plan is hard-deleted (soft delete is preferred — see audit note below) |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries must filter by this; must match the `tenant_id` on the parent `care_plan` row |

**`care_plan_goal` — Goal Definition**

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `domain` | ENUM (`functional`, `clinical`, `social`, `behavioral`) | Clinical PHI | Category of the goal; drives care coordinator workflow and reporting |
| `description` | TEXT | Clinical PHI | Narrative statement of the goal, e.g., `"Walk 50 feet unassisted by review date"`; encrypted at rest; required; PHI values must never appear in audit log payloads |
| `target_metric` | TEXT | Clinical PHI | Nullable; measurable target for goal achievement, e.g., `"Blood pressure < 130/80 mmHg"` or `"≥ 3 days per week attendance"`; encrypted at rest |
| `target_date` | DATE | **Direct Identifier** | Nullable; date by which the goal is expected to be achieved; HIPAA date identifier; encrypted at rest |
| `status` | ENUM (`not_started`, `in_progress`, `achieved`, `discontinued`) | Clinical PHI | Reflects the participant's current progress toward this goal; updated by the care coordinator as part of plan review; `discontinued` requires a note on the parent care plan |

**`care_plan_goal` — Audit Metadata**

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `created_by` | UUID (FK → User) | Non-PHI | User who created this goal entry; typically `care_coordinator` |
| `updated_by` | UUID (FK → User) | Non-PHI | Last user to modify this goal entry |
| `version` | INTEGER | Non-PHI | Optimistic locking; incremented on every write to this goal row |

> **Soft delete note:** Goal rows inherit the soft-delete policy of the parent care plan. A `care_plan_goal` row is never hard-deleted within the HIPAA retention period. If a goal is removed during a plan revision, the prior plan version (including its goal rows) is retained as `superseded`; the new plan version carries its own goal rows.

#### 3.8.5 Physician Order Integration

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `physician_id` | UUID (FK → Provider) | Clinical PHI | Ordering and signing physician; must resolve to a User with `role = physician`; required — a care plan with a null `physician_id` cannot transition to `active` |
| `physician_signature_date` | DATE | **Direct Identifier** | Date the physician reviewed and signed the care plan; HIPAA date identifier; nullable until signed; encrypted at rest; plan is blocked from `active` transition while this field is null |
| `physician_order_reference` | VARCHAR(100) | Non-PHI | External reference to the physician's originating order, e.g., an EHR order ID or FHIR Task resource ID; nullable; not encrypted — this is a non-PHI system identifier |
| `fhir_care_plan_id` | VARCHAR(100) | Non-PHI | FHIR CarePlan resource ID generated for exchange with physician EHR systems via HL7 FHIR R4; nullable until the FHIR resource is created on plan activation; not encrypted — public FHIR resource identifier |
| `care_coordinator_id` | UUID (FK → User) | Non-PHI | Care coordinator who authored and is clinically responsible for this plan; must resolve to a User with `role = care_coordinator`; immutable after plan reaches `active` — a coordinator change requires a plan revision |

#### 3.8.6 Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `created_by` | UUID (FK → User) | Non-PHI | User who created the plan draft; typically `care_coordinator` |
| `updated_by` | UUID (FK → User) | Non-PHI | Last user to modify the record |
| `version` | INTEGER | Non-PHI | Optimistic locking; incremented on every write; an `active` plan may have `review_date` and `notes` updated in place; any change to `primary_diagnosis_code`, `secondary_diagnosis_codes`, or `functional_level` requires a full plan revision (new `version_number`, prior plan transitioned to `superseded`) |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period; a soft-deleted care plan remains queryable by `compliance_officer` via the audit interface |

---

#### 3.8.7 Relationships to Other Entities

| Entity | Relationship | Cardinality | Key Link | Notes |
|---|---|---|---|---|
| **Participant** | A participant has one active care plan at a time; all historical versions are retained | Many → 1 (per active); 1 → Many (all versions) | `care_plan.participant_id` | Care plan snapshots `primary_diagnosis_code`, `secondary_diagnosis_codes`, and `functional_level` from Participant at creation; inherits `is_sud_record` for Part 2 access gate (see 3.8.9) |
| **User (care_coordinator)** | Each care plan is authored and managed by one care coordinator | Many → 1 | `care_plan.care_coordinator_id` | Must resolve to `role = care_coordinator`; coordinator is responsible for drafting, reviewing, and revising the plan |
| **User (physician)** | Each active care plan requires a physician signature; the physician is the ordering provider | Many → 1 | `care_plan.physician_id` | Must resolve to `role = physician`; FHIR CarePlan resource is generated for exchange with the physician's EHR system on plan activation |
| **care_plan_goal** | A care plan has one or more goals; each goal row belongs to exactly one care plan | 1 → Many | `care_plan_goal.care_plan_id` | Normalized table enabling db_validator to assert `domain`, `status`, `target_date`, and all other fields individually via SQL; goals are created and managed through the care plan service; `tenant_id` on every goal row must match the parent care plan |
| **MARRecord** | MAR records share a participant with the active care plan; care plan goals may specify medication administration context | Indirect | `mar_record.participant_id` / `care_plan.participant_id` | No direct FK from MARRecord to CarePlan in Phase 2; medication goals in `care_plan_goal` inform MAR entries at the workflow level, not via a database constraint |
| **Incident** | An incident involving a participant may trigger a care plan revision; no direct FK relationship | Indirect | `incident.participant_id` / `care_plan.participant_id` | A care plan revision prompted by an incident is captured via a new `version_number` and `notes`; the incident that prompted the revision may be referenced in `notes` by `incident_id` |
| **Appointment** | Physician appointments may produce care plan orders; the signing physician is shared across both entities | Indirect | `care_plan.physician_id` / `appointment.physician_id` | FHIR Appointment and FHIR CarePlan resources may be generated from the same physician interaction; linked at the FHIR integration layer, not via a database FK in Phase 2 |

---

#### 3.8.8 Unique Constraints

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_care_plan_participant_version` | `tenant_id`, `participant_id`, `version_number` | Per tenant | Return HTTP 409 with error code `CARE_PLAN_DUPLICATE_VERSION`; version numbering logic must guarantee monotonic increment |
| `uq_care_plan_participant_active` | `tenant_id`, `participant_id` WHERE `status = 'active'` | Per tenant (partial index) | Return HTTP 409 with error code `CARE_PLAN_ALREADY_ACTIVE`; the revision workflow must transition the current active plan to `superseded` before the new version is activated |
| `uq_care_plan_goal_domain_description` | `tenant_id`, `care_plan_id`, `domain`, `description` | Per care plan | Return HTTP 409 with error code `CARE_PLAN_GOAL_DUPLICATE`; do not create a second goal row |

**Rules:**
- `version_number` must be unique per participant per tenant. The application reads the participant's maximum existing `version_number` and increments it immediately before insert. A collision indicates a concurrency race; the application retries once with re-read of the maximum; if the second attempt also collides, `409 Conflict` with `CARE_PLAN_DUPLICATE_VERSION` is returned and the operator is notified.
- At most one `active` plan is permitted per participant per tenant at any time. Before transitioning a draft plan to `active`, the application must find any existing `active` plan for the same participant and update it to `superseded` within the same database transaction. An activation attempt when an `active` plan exists and no supersession is performed returns `409 Conflict` with `CARE_PLAN_ALREADY_ACTIVE`.
- A plan cannot transition to `active` while `physician_signature_date` is null or `physician_id` is null. This pre-activation check is enforced at the application service layer with `422 Unprocessable Entity` and error code `CARE_PLAN_UNSIGNED`, independently of the database constraints.
- Within a single care plan, a goal with an identical `domain` and `description` is always a duplicate entry. A second goal row with the same `care_plan_id`, `domain`, and `description` must be rejected at the application layer before reaching the database, with the database enforcing the same constraint as a backstop. The constraint is scoped to `care_plan_id`, not to the participant: the same `domain` and `description` combination may appear on a different care plan, including a newer version of the same participant's plan, because each plan version is an independent clinical record with its own goal set.

**Implementation:**
- Database: `UNIQUE (tenant_id, participant_id, version_number)` index on the `care_plan` table; partial unique index `UNIQUE (tenant_id, participant_id) WHERE status = 'active'` to enforce the single-active-plan constraint at the database layer as a backstop; `UNIQUE (tenant_id, care_plan_id, domain, description)` index on the `care_plan_goal` table
- Application: pre-activation check verifies `physician_id` is non-null and `physician_signature_date` is non-null; supersession of any existing `active` plan and activation of the new plan execute in a single atomic transaction; pre-insert existence check on `(care_plan_id, domain, description)` returns `409 Conflict` with error code `CARE_PLAN_GOAL_DUPLICATE` before a duplicate goal insert is attempted
- Error message for `CARE_PLAN_ALREADY_ACTIVE`: `"This participant already has an active care plan. The current plan must be superseded before a new one can be activated."`
- Error message for `CARE_PLAN_UNSIGNED`: `"A care plan cannot be activated without a physician signature date."`
- Error message for `CARE_PLAN_DUPLICATE_VERSION`: `"A care plan with this version number already exists for this participant."`
- Error message for `CARE_PLAN_GOAL_DUPLICATE`: `"A goal with this domain and description already exists on this care plan."`

**Test case targets:**
- Attempt to POST a second care plan for the same participant with an identical `version_number` → assert `409` with `CARE_PLAN_DUPLICATE_VERSION`
- Attempt to activate a draft plan when the participant already has an `active` plan without first superseding it → assert `409` with `CARE_PLAN_ALREADY_ACTIVE`
- Attempt to activate a plan where `physician_signature_date` is null → assert `422` with `CARE_PLAN_UNSIGNED`
- Execute the full revision workflow: create new draft version, set `physician_signature_date`, activate → assert prior plan `status = superseded` and new plan `status = active` in a single transaction
- Confirm that a superseded plan is immutable: attempt to PATCH a `superseded` plan → assert `409` or `422`
- Attempt to POST a second `care_plan_goal` row with the same `care_plan_id`, `domain`, and `description` as an existing goal → assert `409` with `CARE_PLAN_GOAL_DUPLICATE`
- Confirm that the same `domain` and `description` combination is accepted on a different `care_plan_id`, including a superseded version of the same participant's plan

---

#### 3.8.9 42 CFR Part 2 Compliance Note

When `Participant.is_sud_record = true`, all CarePlan and `care_plan_goal` records for that participant are subject to 42 CFR Part 2 access controls, consistent with the controls applied to MARRecord (3.5.8) and Incident (3.6.9). The CarePlan entity carries no independent Part 2 flag — the control is derived entirely from `Participant.is_sud_record`, which the application service must read on every care plan and goal access.

**Access restriction:**
- Read and write access to care plans and their goals for SUD-flagged participants is limited to `care_coordinator`, `nurse_medication_aide`, and `compliance_officer` roles
- `Participant.is_sud_record` is evaluated at the application service layer on every care plan read and write — it is not sufficient to enforce this at the API Gateway, because `is_sud_record` is itself a Part 2-protected field that must not be exposed to the gateway layer
- API responses for unauthorized role requests return `403 Forbidden` with no indication of the care plan's existence
- The `care_plan_goal` rows and the `notes` field are redacted from list-view responses for unauthorized roles even when the participant's non-clinical fields are otherwise accessible

**Audit logging requirement:**
- Every read on a care plan or goal where `Participant.is_sud_record = true` must be captured in the audit log with: `user_id`, `tenant_id`, `care_plan_id`, action type `PHI_READ`, timestamp, and outcome — before the response is returned to the caller
- Every write must be logged with action type `PHI_WRITE` and `data_affected` listing field names changed (never field values)
- Failed access attempts are logged with `ACCESS_DENIED`

**External disclosure:**
- No CarePlan or `care_plan_goal` for a participant where `is_sud_record = true` may be transmitted externally — including via FHIR CarePlan exchange with physician EHR systems — without explicit patient consent documented in the system, consistent with 42 CFR Part 2 §2.31. The FHIR outbound adapter must verify that a valid consent record exists before generating or transmitting the FHIR CarePlan resource. A missing consent record blocks the FHIR transmission and emits a `CONSENT_CHECK` audit event with outcome `DENIED`.

---

> **Pending approval before proceeding to 3.9 Appointment.**

---

### 3.9 Appointment

The Appointment entity records a scheduled clinical encounter between a participant and a physician — an in-person visit, specialist referral, or telehealth session. Appointments are the scheduling artifact that drives physician order integration, generates FHIR Appointment resources for exchange with physician EHR systems, and produces the clinical context from which care plan orders and result documentation flow. Each appointment belongs to exactly one participant and one physician, is bounded by a defined time window, and transitions through a lifecycle from scheduled to completed, cancelled, or no_show. This entity supports the Physician Appointments module (Section 1.2, module 5).

> **Phase 2 scope:** core scheduling fields, status lifecycle, clinical result documentation, and FHIR resource linkage. Referral tracking details, transport coordination, and participant-facing reminder integration are Phase 3.

#### 3.9.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `appointment_id` | UUID (PK) | Non-PHI | System-generated; never user-supplied |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries must filter by this |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Central link to the Participant record; appointment inherits `is_sud_record` from Participant for 42 CFR Part 2 gate considerations |

#### 3.9.2 Scheduling

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `physician_id` | UUID (FK → User) | Clinical PHI | Attending physician for this appointment; must resolve to a User with `role = physician`; required — an appointment cannot be created without a physician |
| `scheduled_start` | TIMESTAMPTZ | **Direct Identifier** | Date and time the appointment is scheduled to begin; HIPAA date/time identifier; encrypted at rest; part of unique constraint (see 3.9.8) |
| `scheduled_end` | TIMESTAMPTZ | **Direct Identifier** | Date and time the appointment is scheduled to end; HIPAA date/time identifier; encrypted at rest; must be strictly after `scheduled_start`; used in physician overlap check (see 3.9.8) |
| `appointment_type` | ENUM (`routine`, `specialist_referral`, `urgent`, `telehealth`) | Clinical PHI | Nature of the clinical encounter; immutable once `status` reaches `completed` (see 3.9.8) |

#### 3.9.3 Status & Workflow

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `status` | ENUM (`scheduled`, `completed`, `cancelled`, `no_show`) | Non-PHI | State machine enforced at application layer: `scheduled` → `completed` or `cancelled` or `no_show`; terminal states may not be reversed; a PATCH transitioning `status` to `cancelled` requires a non-empty `cancellation_reason` (see 3.9.8) |
| `cancellation_reason` | VARCHAR(500) | Non-PHI | Nullable unless `status = 'cancelled'`; required and must be non-empty when `status` transitions to `cancelled`; a PATCH to `cancelled` without this field populated is rejected with `422` and error code `APPOINTMENT_MISSING_CANCELLATION_REASON` (see 3.9.8) |

#### 3.9.4 Clinical Results

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `result_notes` | TEXT | Clinical PHI | Nullable; free-text clinical notes documenting the outcome of the appointment; encrypted at rest; may be added or updated after the appointment reaches `status = completed` — PATCH to this field on a completed appointment is permitted and increments `version` (see 3.9.8) |
| `fhir_result_reference` | VARCHAR(100) | Non-PHI | Nullable; FHIR resource reference (e.g., `DiagnosticReport/dr_00456`) returned by the physician's EHR system after the encounter; set via FHIR R4 exchange; not encrypted — public FHIR resource identifier; may be added or updated on a completed appointment (see 3.9.8) |
| `follow_up_required` | BOOLEAN | Clinical PHI | Nullable; set to `true` when the attending physician determines a follow-up appointment is clinically indicated; may be set or updated after the appointment reaches `status = completed` — PATCH to this field on a completed appointment is permitted and increments `version` (see 3.9.8) |

#### 3.9.5 FHIR Integration

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `fhir_appointment_id` | VARCHAR(100) | Non-PHI | FHIR Appointment resource ID generated for exchange with the physician's EHR system via HL7 FHIR R4; nullable until the FHIR resource is created on appointment scheduling; not encrypted — public FHIR resource identifier |

#### 3.9.6 Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC; updated on every write |
| `created_by` | UUID (FK → User) | Non-PHI | Staff user who created the appointment record; typically `care_coordinator` or `program_administrator` |
| `updated_by` | UUID (FK → User) | Non-PHI | Last user to modify the record |
| `version` | INTEGER | Non-PHI | Optimistic locking; incremented on every permitted write, including PATCH to `result_notes`, `fhir_result_reference`, or `follow_up_required` on a `completed` appointment (see 3.9.8); `scheduled_start`, `physician_id`, and `appointment_type` are immutable once `status = 'completed'` |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period |

---

#### 3.9.7 Relationships to Other Entities

| Entity | Relationship | Cardinality | Key Link | Notes |
|---|---|---|---|---|
| **Participant** | A participant has zero or more appointments | 1 → Many | `appointment.participant_id` | Appointment inherits Part 2 considerations from `Participant.is_sud_record`; FHIR Appointment resource is generated per appointment record |
| **User (physician)** | Each appointment is attended by one physician | Many → 1 | `appointment.physician_id` | Must resolve to `role = physician`; physician availability is enforced via overlap constraint (see 3.9.8); FHIR Appointment resource references the physician's NPI |
| **CarePlan** | Physician appointments may produce care plan orders; the signing physician is shared across both entities | Indirect | `care_plan.physician_id` / `appointment.physician_id` | FHIR Appointment and FHIR CarePlan resources may be generated from the same physician interaction; linked at the FHIR integration layer, not via a database FK |
| **MARRecord** | Appointment outcomes may inform medication administration goals; no direct FK | Indirect | `mar_record.participant_id` / `appointment.participant_id` | Clinical results documented in `result_notes` may prompt MAR updates at the workflow level |
| **Reminder** | A participant or family member may receive appointment reminders; no direct FK in Phase 2 | Indirect | `reminder.participant_id` / `appointment.participant_id` | Reminder generation from appointment records is Phase 3 |

---

#### 3.9.8 Unique Constraints

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_appointment_participant_physician_scheduled_start` | `tenant_id`, `participant_id`, `physician_id`, `scheduled_start` | Per tenant | Return HTTP 409 with error code `APPOINTMENT_DUPLICATE`; do not create a second record |
| `ck_appointment_physician_no_overlap` | `tenant_id`, `physician_id`, `scheduled_start` evaluated against existing `[scheduled_start, scheduled_end)` intervals | Per tenant, per physician | Return HTTP 409 with error code `APPOINTMENT_PHYSICIAN_OVERLAP`; evaluated on create and on any PATCH that changes `scheduled_start` or `physician_id`; rows with `status IN ('cancelled', 'no_show')` are excluded from the check |

**Rules:**
- `uq_appointment_participant_physician_scheduled_start` prevents two appointments for the same participant and physician at the identical start instant. This exact-match constraint is enforced at both the database and application layers but does not cover the case where a new appointment's start time falls within an existing appointment's window without matching the start exactly. The interval overlap rule below provides the broader guard.
- `ck_appointment_physician_no_overlap` (interval overlap): A physician may not have two overlapping appointments within the same tenant. A create or reschedule is rejected when the new or updated `scheduled_start` satisfies `existing.scheduled_start <= new_scheduled_start < existing.scheduled_end` for any existing appointment with the same `physician_id` and `tenant_id`, where the existing appointment's `status` is not `cancelled` or `no_show`. The check runs on every POST and on every PATCH that modifies `scheduled_start` or `physician_id`; on PATCH the current record is excluded from the check by `appointment_id` to permit a reschedule that stays within its own existing window.
- `APPOINTMENT_COMPLETED_IMMUTABLE`: An appointment whose `status` is `completed` is partially immutable. PATCH requests that include any of `scheduled_start`, `physician_id`, or `appointment_type` on a completed appointment are rejected with `422 Unprocessable Entity` and error code `APPOINTMENT_COMPLETED_IMMUTABLE` — these fields describe the encounter as it occurred and cannot be revised after the visit is recorded as complete. PATCH requests that change only `result_notes`, `fhir_result_reference`, or `follow_up_required` on a completed appointment are accepted; the response is `200 OK` with `version` incremented. A PATCH body that mixes immutable and mutable fields is rejected as a whole with `422` — the caller must separate the writes.
- `APPOINTMENT_MISSING_CANCELLATION_REASON`: A PATCH that transitions `status` to `cancelled` must supply a non-empty `cancellation_reason`. A request with `status = 'cancelled'` and an absent or empty-string `cancellation_reason` is rejected with `422 Unprocessable Entity` and error code `APPOINTMENT_MISSING_CANCELLATION_REASON`. A request with `status = 'cancelled'` and a non-empty `cancellation_reason` is accepted; the database must confirm `status = 'cancelled'` and `cancellation_reason` persisted exactly as supplied.

**Implementation:**
- Database:
  - `UNIQUE (tenant_id, participant_id, physician_id, scheduled_start)` index on the `appointment` table enforces the exact-match constraint as a backstop
  - Two SQLite triggers enforce the interval overlap constraint at the database layer as a backstop against any write that bypasses the application layer:

    ```sql
    CREATE TRIGGER trg_appointment_physician_no_overlap_insert
    BEFORE INSERT ON appointment
    FOR EACH ROW
    BEGIN
      SELECT RAISE(ABORT, 'overlapping appointment for this physician')
      WHERE EXISTS (
        SELECT 1 FROM appointment
        WHERE tenant_id    = NEW.tenant_id
          AND physician_id = NEW.physician_id
          AND status NOT IN ('cancelled', 'no_show')
          AND scheduled_start < NEW.scheduled_end
          AND scheduled_end   > NEW.scheduled_start
      );
    END;

    CREATE TRIGGER trg_appointment_physician_no_overlap_update
    BEFORE UPDATE ON appointment
    FOR EACH ROW
    BEGIN
      SELECT RAISE(ABORT, 'overlapping appointment for this physician')
      WHERE EXISTS (
        SELECT 1 FROM appointment
        WHERE tenant_id      = NEW.tenant_id
          AND physician_id   = NEW.physician_id
          AND status NOT IN ('cancelled', 'no_show')
          AND scheduled_start < NEW.scheduled_end
          AND scheduled_end   > NEW.scheduled_start
          AND appointment_id != NEW.appointment_id
      );
    END;
    ```

    The INSERT trigger fires on every new row; the UPDATE trigger fires on every row modification and excludes the row being updated via `appointment_id != NEW.appointment_id` to permit reschedules that do not introduce an external overlap. Both triggers abort the transaction and surface the message `'overlapping appointment for this physician'` if a conflicting row is found; no partial write occurs.
- Application:
  - **Interval overlap check:** On every POST and on every PATCH that changes `scheduled_start` or `physician_id`, the service executes: `SELECT 1 FROM appointment WHERE tenant_id = :tenant_id AND physician_id = :physician_id AND status NOT IN ('cancelled', 'no_show') AND scheduled_start <= :new_scheduled_start AND scheduled_end > :new_scheduled_start AND appointment_id != :self_id LIMIT 1`. A non-empty result returns `409 Conflict` with `APPOINTMENT_PHYSICIAN_OVERLAP` before the write is attempted. On POST `:self_id` is `NULL` (no exclusion needed); on PATCH it is the `appointment_id` of the record being updated.
  - **Completed-immutable check:** On every PATCH, the service reads the current `status`. If `status = 'completed'` and the request body contains any of `scheduled_start`, `physician_id`, or `appointment_type`, the service returns `422 Unprocessable Entity` with `APPOINTMENT_COMPLETED_IMMUTABLE` before the write is attempted. If the body contains only fields from `{result_notes, fhir_result_reference, follow_up_required}`, the write proceeds and `version` is incremented.
  - **Cancellation-reason check:** On every PATCH, if `status = 'cancelled'` is present in the request body, the service validates that `cancellation_reason` is also present in the body and evaluates to a non-empty string after stripping whitespace. If the check fails, the service returns `422 Unprocessable Entity` with `APPOINTMENT_MISSING_CANCELLATION_REASON` before the write is attempted.
- Error messages exposed to the client:
  - `APPOINTMENT_DUPLICATE`: `"An appointment for this participant with this physician at the same start time already exists."`
  - `APPOINTMENT_PHYSICIAN_OVERLAP`: `"This physician already has an appointment scheduled during the requested time slot."`
  - `APPOINTMENT_COMPLETED_IMMUTABLE`: `"A completed appointment's scheduled time, physician, or type cannot be changed."`
  - `APPOINTMENT_MISSING_CANCELLATION_REASON`: `"A cancellation reason is required when cancelling an appointment."`

**Test case targets:**
- POST a second appointment with the same `participant_id`, `physician_id`, and `scheduled_start` within the same tenant → assert `409` with `APPOINTMENT_DUPLICATE`
- POST an appointment where `scheduled_start` falls strictly inside an existing active appointment's `[scheduled_start, scheduled_end)` window for the same `physician_id` and `tenant_id` → assert `409` with `APPOINTMENT_PHYSICIAN_OVERLAP`
- POST an appointment where `scheduled_start` matches an existing appointment's `scheduled_end` exactly (boundary — no overlap) → assert `201 Created`
- POST an appointment where `scheduled_start` falls within an existing `cancelled` appointment's window → assert `201 Created` (cancelled excluded from overlap check)
- POST an appointment where `scheduled_start` falls within an existing `no_show` appointment's window → assert `201 Created` (no_show excluded from overlap check)
- PATCH `scheduled_start` on an existing appointment so the new start overlaps a different active appointment for the same `physician_id` → assert `409` with `APPOINTMENT_PHYSICIAN_OVERLAP`
- PATCH `physician_id` on an appointment to a physician who already has an active appointment whose window covers the current appointment's `scheduled_start` → assert `409` with `APPOINTMENT_PHYSICIAN_OVERLAP`
- PATCH `scheduled_start` on an appointment to a new value that still lies within that same appointment's own original window (reschedule within gap — no external overlap) → assert `200` (self-exclusion works correctly)
- PATCH `scheduled_start`, `physician_id`, or `appointment_type` on a `completed` appointment → assert `422` with `APPOINTMENT_COMPLETED_IMMUTABLE`
- PATCH `result_notes` on a `completed` appointment → assert `200`; DB confirms `version` incremented and `status` remains `completed`
- PATCH `fhir_result_reference` on a `completed` appointment → assert `200`; DB confirms `version` incremented
- PATCH `follow_up_required` on a `completed` appointment → assert `200`; DB confirms `version` incremented
- PATCH a body containing both `result_notes` and `scheduled_start` on a `completed` appointment → assert `422` with `APPOINTMENT_COMPLETED_IMMUTABLE` (mixed body rejected in full)
- PATCH `status = 'cancelled'` with no `cancellation_reason` field → assert `422` with `APPOINTMENT_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with `cancellation_reason = ""` (empty string) → assert `422` with `APPOINTMENT_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with `cancellation_reason = "   "` (whitespace only) → assert `422` with `APPOINTMENT_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with a non-empty `cancellation_reason` → assert `200`; DB confirms `status = 'cancelled'` and `cancellation_reason` persisted exactly as supplied
- Execute a direct SQL INSERT into the `appointment` table — bypassing the application layer entirely — for a `physician_id` and `tenant_id` that already has an active appointment whose `[scheduled_start, scheduled_end)` window covers the new row's `scheduled_start`; assert the database raises an `OperationalError` (or equivalent SQLite abort) with the message `'overlapping appointment for this physician'` and that no row is committed. Repeat for a direct SQL UPDATE that reschedules an existing appointment into an overlapping window and assert the same database-level rejection.

---

#### 3.9.9 42 CFR Part 2 Compliance Note

When `Participant.is_sud_record = true`, all Appointment records for that participant are subject to 42 CFR Part 2 access controls, consistent with the controls applied to MARRecord (3.5.8), Incident (3.6.9), and CarePlan (3.8.9). The Appointment entity carries no independent Part 2 flag — the control is derived entirely from `Participant.is_sud_record`, which the application service must read on every appointment access.

**Access restriction:**
- Read and write access to appointments for SUD-flagged participants is limited to `care_coordinator`, `nurse_medication_aide`, and `compliance_officer` roles
- `Participant.is_sud_record` is evaluated at the application service layer on every appointment read and write — it is not sufficient to enforce this at the API Gateway, because `is_sud_record` is itself a Part 2-protected field that must not be exposed to the gateway layer
- API responses for unauthorized role requests return `403 Forbidden` with no indication of the appointment's existence
- The `appointment_type`, `cancellation_reason`, `result_notes`, and `follow_up_required` fields are additionally redacted from list-view responses for unauthorized roles even when the participant's non-clinical fields are otherwise accessible

**Audit logging requirement:**
- Every read on an appointment where `Participant.is_sud_record = true` must be captured in the audit log with: `user_id`, `tenant_id`, `appointment_id`, action type `PHI_READ`, timestamp, and outcome — before the response is returned to the caller
- Every write must be logged with action type `PHI_WRITE` and `data_affected` listing field names changed (never field values)
- Failed access attempts are logged with `ACCESS_DENIED`

**External disclosure:**
- No Appointment record or `fhir_result_reference` for a participant where `is_sud_record = true` may be transmitted to a physician EHR system or any external party — including via FHIR Appointment or FHIR DiagnosticReport exchange — without explicit patient consent documented in the system, consistent with 42 CFR Part 2 §2.31. The FHIR outbound adapter must verify that a valid consent record exists before generating or transmitting the FHIR Appointment resource or any linked result reference. A missing consent record blocks the FHIR transmission and emits a `CONSENT_CHECK` audit event with outcome `DENIED`.

---

> **Pending approval before proceeding to 3.10 MedicationRefill.**

---

### 3.10 MedicationRefill

The MedicationRefill entity records a request to refill a participant's prescription medication through a pharmacy. It is the operational artifact for the Medication Refill module (Section 1.2, module 8), tracking the full lifecycle from request initiation through pharmacy transmission, processing, and fulfillment. Each refill request is linked to a participant and a prescribing physician, transmitted to a designated pharmacy via HL7 FHIR R4 MedicationRequest or NCPDP SCRIPT (Section 2.4), and carries a controlled-substance flag that triggers 42 CFR Part 2 access controls and the pharmacy consent gate when the medication is a controlled substance associated with a substance use disorder record. Fulfilled refill records provide medication supply continuity for the participant's active MAR entries managed in the MARRecord entity.

> **Phase 2 scope:** core request fields, pharmacy transmission status lifecycle, FHIR MedicationRequest and NCPDP SCRIPT integration, and 42 CFR Part 2 controls for controlled substance refills. Pharmacy claims linkage, formulary checks, and prior authorization workflows are Phase 3.

#### 3.10.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `refill_id` | UUID (PK) | Non-PHI | System-generated; never user-supplied |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries must filter by this |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Central link to the Participant record; inherits `is_sud_record` from Participant for the combined 42 CFR Part 2 gate when `is_controlled_substance = true` (see 3.10.8) |

#### 3.10.2 Request Details

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `medication_name` | VARCHAR(200) | Clinical PHI | Full medication name including strength, e.g., `Metformin 500mg`; encrypted at rest; should match `MARRecord.medication_name` for the same participant where the refill supports an active MAR entry — alignment is enforced at the workflow level, not via a database constraint |
| `dose` | VARCHAR(100) | Clinical PHI | Human-readable dose expression, e.g., `1 tablet`, `5mL`, `10 units`; encrypted at rest |
| `route` | ENUM (`oral`, `injection`, `topical`) | Clinical PHI | Route of administration; must match the corresponding MAR entry when the refill supports an active MARRecord |
| `quantity_requested` | INTEGER | Clinical PHI | Number of units (tablets, doses, or vials) requested in the refill; must be a positive integer greater than or equal to 1 (see 3.10.7) |
| `refills_requested` | SMALLINT | Clinical PHI | Number of refill authorizations requested; nullable; when null, interpreted as a single fill with no standing refill authorization |
| `prescribing_physician_id` | UUID (FK → User) | Clinical PHI | Physician who holds the underlying prescription being refilled; must resolve to a User with `role = physician`; required — a refill request cannot be created without a prescribing physician |
| `is_controlled_substance` | BOOLEAN | **42 CFR Part 2** | When `true`, this refill request is for a controlled substance and is subject to elevated access controls and the pharmacy consent gate (see 3.10.8); the flag itself is Part 2-protected and must not appear in non-privileged API responses or audit log payloads; mirrors the same flag on MARRecord (3.5.4) |

#### 3.10.3 Status & Workflow

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `status` | ENUM (`requested`, `sent_to_pharmacy`, `processing`, `fulfilled`, `denied`, `cancelled`) | Non-PHI | State machine enforced at application layer: `requested` → `sent_to_pharmacy` → `processing` → `fulfilled` or `denied`; `cancelled` may be set from any non-terminal state; terminal states (`fulfilled`, `denied`, `cancelled`) may not be reversed; a PATCH transitioning `status` to `denied` requires a non-empty `denial_reason` (see 3.10.7); a PATCH transitioning `status` to `cancelled` requires a non-empty `cancellation_reason` (see 3.10.7) |
| `denial_reason` | VARCHAR(500) | Non-PHI | Nullable unless `status = 'denied'`; required and must be non-empty when `status` transitions to `denied`; populated from the pharmacy's or prescribing physician's stated reason for rejection; a PATCH to `denied` without this field is rejected with `422` and error code `REFILL_MISSING_DENIAL_REASON` (see 3.10.7) |
| `cancellation_reason` | VARCHAR(500) | Non-PHI | Nullable unless `status = 'cancelled'`; required and must be non-empty when `status` transitions to `cancelled`; a PATCH to `cancelled` without this field populated is rejected with `422` and error code `REFILL_MISSING_CANCELLATION_REASON` (see 3.10.7) |
| `requested_at` | TIMESTAMPTZ | **Direct Identifier** | Date and time the refill request was submitted by staff; HIPAA date/time identifier; encrypted at rest; set on insert and immutable thereafter |
| `fulfilled_at` | TIMESTAMPTZ | **Direct Identifier** | Nullable; date and time the pharmacy confirmed dispensing; HIPAA date/time identifier; encrypted at rest; set when `status` transitions to `fulfilled`; may be updated on a `fulfilled` record without triggering immutability rules (see 3.10.7) |

#### 3.10.4 Pharmacy & FHIR Integration

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `pharmacy_id` | VARCHAR(100) | Non-PHI | Identifier of the target pharmacy — NPI, NCPDP provider ID, or internal pharmacy record ID; required at the time of transmission; may be null on initial `requested` status if the pharmacy is selected at send time |
| `fhir_medication_request_id` | VARCHAR(100) | Non-PHI | FHIR MedicationRequest resource ID generated for exchange with the pharmacy via HL7 FHIR R4; nullable until the FHIR resource is created when `status` transitions to `sent_to_pharmacy`; not encrypted — public FHIR resource identifier |
| `ncpdp_script_reference` | VARCHAR(100) | Non-PHI | NCPDP SCRIPT transaction reference returned by the pharmacy system on acknowledgement of the FHIR or EDI transmission; nullable until the pharmacy responds; not encrypted — public transaction identifier; may be updated on a `fulfilled` record (see 3.10.7) |

#### 3.10.5 Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC; updated on every write |
| `created_by` | UUID (FK → User) | Non-PHI | Staff user who initiated the refill request; typically `nurse_medication_aide` or `care_coordinator` |
| `updated_by` | UUID (FK → User) | Non-PHI | Last user to modify the record |
| `version` | INTEGER | Non-PHI | Optimistic locking; incremented on every permitted write, including PATCH to `fulfilled_at` or `ncpdp_script_reference` on a `fulfilled` record (see 3.10.7); `medication_name`, `dose`, `route`, and `quantity_requested` are immutable once `status = 'fulfilled'` |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period |

---

#### 3.10.6 Relationships to Other Entities

| Entity | Relationship | Cardinality | Key Link | Notes |
|---|---|---|---|---|
| **Participant** | A participant has zero or more refill requests | 1 → Many | `refill.participant_id` | Refill inherits `is_sud_record` from Participant for the combined 42 CFR Part 2 pharmacy consent gate (see 3.10.8); every refill where `is_controlled_substance = true` and `Participant.is_sud_record = true` requires documented consent before FHIR MedicationRequest or NCPDP SCRIPT transmission |
| **User (prescribing physician)** | Each refill request names one prescribing physician | Many → 1 | `refill.prescribing_physician_id` | Must resolve to `role = physician`; the prescribing physician's NPI is included in the FHIR MedicationRequest transmitted to the pharmacy |
| **MARRecord** | A fulfilled refill provides medication supply continuity for active MAR entries for the same participant and medication | Indirect | `mar_record.participant_id` / `refill.participant_id` + `mar_record.medication_name` / `refill.medication_name` | No direct FK from MARRecord to MedicationRefill in Phase 2; alignment is by participant and medication name at the workflow level; `is_controlled_substance` on MedicationRefill mirrors the same flag on the corresponding MARRecord and both records are subject to the same Part 2 access gate |
| **CarePlan** | A care plan goal may specify a medication whose refill is tracked here; no direct FK | Indirect | `care_plan.participant_id` / `refill.participant_id` | Refill history surfaces in care plan context at the workflow level, not via a database constraint |
| **Appointment** | A physician appointment may prompt the prescribing physician to authorize a refill; no direct FK | Indirect | `appointment.physician_id` / `refill.prescribing_physician_id` | Refills originating from an appointment encounter may be linked at the FHIR integration layer (a FHIR MedicationRequest may reference the originating FHIR Appointment resource) but carry no database FK in Phase 2 |

---

#### 3.10.7 Unique Constraints

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_refill_participant_medication_requested_at` | `tenant_id`, `participant_id`, `medication_name`, `requested_at` | Per tenant | Return HTTP 409 with error code `REFILL_DUPLICATE`; do not create a second record |
| `uq_refill_participant_medication_open` | `tenant_id`, `participant_id`, `medication_name` WHERE `status NOT IN ('fulfilled', 'denied', 'cancelled')` | Per tenant (partial index) | Return HTTP 409 with error code `REFILL_DUPLICATE_IN_FLIGHT`; only one open refill request per medication per participant per tenant is permitted at any time |

**Rules:**
- `uq_refill_participant_medication_requested_at` prevents two refill requests for the same participant and medication submitted at the identical instant within a tenant. This exact-match constraint is enforced at both the database and application layers as a backstop against concurrent duplicate submissions.
- `uq_refill_participant_medication_open` (in-flight uniqueness): A participant may have at most one open (non-terminal) refill request per medication per tenant at any time. A new refill request for a `medication_name` is rejected if an existing request for the same `participant_id` and `medication_name` within the same `tenant_id` has `status` of `requested`, `sent_to_pharmacy`, or `processing`. The restriction lifts when the prior request reaches a terminal state (`fulfilled`, `denied`, or `cancelled`). This prevents duplicate in-flight transmissions to the pharmacy for the same medication, which could produce duplicate dispense events or controlled substance inventory discrepancies.
- `REFILL_INVALID_QUANTITY`: A POST or PATCH that supplies a `quantity_requested` value of zero, a negative integer, or any non-positive value is rejected with `422 Unprocessable Entity` and error code `REFILL_INVALID_QUANTITY` before the write is attempted. `quantity_requested` must be a whole number greater than or equal to 1 on every create and on every PATCH that includes the field.
- `REFILL_FULFILLED_IMMUTABLE`: A refill request whose `status` is `fulfilled` is partially immutable. PATCH requests that include any of `medication_name`, `dose`, `route`, or `quantity_requested` on a fulfilled record are rejected with `422 Unprocessable Entity` and error code `REFILL_FULFILLED_IMMUTABLE` — these fields describe the dispensed medication as confirmed by the pharmacy and cannot be revised after fulfillment. PATCH requests limited to `fulfilled_at` or `ncpdp_script_reference` on a fulfilled record are accepted; the response is `200 OK` with `version` incremented. A PATCH body that mixes immutable and mutable fields is rejected as a whole with `422` — the caller must separate the writes.
- `REFILL_MISSING_DENIAL_REASON`: A PATCH that transitions `status` to `denied` must supply a non-empty `denial_reason`. A request with `status = 'denied'` and an absent or empty-string `denial_reason` is rejected with `422 Unprocessable Entity` and error code `REFILL_MISSING_DENIAL_REASON`. A request with `status = 'denied'` and a non-empty `denial_reason` is accepted; the database must confirm `status = 'denied'` and `denial_reason` persisted exactly as supplied.
- `REFILL_MISSING_CANCELLATION_REASON`: A PATCH that transitions `status` to `cancelled` must supply a non-empty `cancellation_reason`. A request with `status = 'cancelled'` and an absent or empty-string `cancellation_reason` is rejected with `422 Unprocessable Entity` and error code `REFILL_MISSING_CANCELLATION_REASON`. A request with `status = 'cancelled'` and a non-empty `cancellation_reason` is accepted; the database must confirm `status = 'cancelled'` and `cancellation_reason` persisted exactly as supplied.

**Implementation:**
- Database:
  - `UNIQUE (tenant_id, participant_id, medication_name, requested_at)` index on the `medication_refill` table enforces the exact-match constraint as a backstop
  - Partial unique index `UNIQUE (tenant_id, participant_id, medication_name) WHERE status NOT IN ('fulfilled', 'denied', 'cancelled')` enforces the in-flight uniqueness constraint at the database layer as a backstop
- Application:
  - **In-flight uniqueness check:** On every POST, the service executes: `SELECT 1 FROM medication_refill WHERE tenant_id = :tenant_id AND participant_id = :participant_id AND medication_name = :medication_name AND status NOT IN ('fulfilled', 'denied', 'cancelled') LIMIT 1`. A non-empty result returns `409 Conflict` with `REFILL_DUPLICATE_IN_FLIGHT` before the insert is attempted.
  - **Quantity validation:** On every POST and on every PATCH that includes `quantity_requested`, the service validates that the value is an integer greater than or equal to 1. If the value is zero, negative, or not a whole number, the service returns `422 Unprocessable Entity` with `REFILL_INVALID_QUANTITY` before the write is attempted.
  - **Fulfilled-immutable check:** On every PATCH, the service reads the current `status`. If `status = 'fulfilled'` and the request body contains any of `medication_name`, `dose`, `route`, or `quantity_requested`, the service returns `422 Unprocessable Entity` with `REFILL_FULFILLED_IMMUTABLE` before the write is attempted. If the body contains only `fulfilled_at` or `ncpdp_script_reference`, the write proceeds and `version` is incremented.
  - **Denial-reason check:** On every PATCH, if `status = 'denied'` is present in the request body, the service validates that `denial_reason` is also present and evaluates to a non-empty string after stripping whitespace. If the check fails, the service returns `422 Unprocessable Entity` with `REFILL_MISSING_DENIAL_REASON` before the write is attempted.
  - **Cancellation-reason check:** On every PATCH, if `status = 'cancelled'` is present in the request body, the service validates that `cancellation_reason` is also present and evaluates to a non-empty string after stripping whitespace. If the check fails, the service returns `422 Unprocessable Entity` with `REFILL_MISSING_CANCELLATION_REASON` before the write is attempted.
- Error messages exposed to the client:
  - `REFILL_DUPLICATE`: `"A refill request for this participant and medication at the same time already exists."`
  - `REFILL_DUPLICATE_IN_FLIGHT`: `"An open refill request for this medication already exists for this participant. The existing request must be fulfilled, denied, or cancelled before a new one can be submitted."`
  - `REFILL_INVALID_QUANTITY`: `"quantity_requested must be a positive integer greater than zero."`
  - `REFILL_FULFILLED_IMMUTABLE`: `"A fulfilled refill request's medication, dose, route, or quantity cannot be changed."`
  - `REFILL_MISSING_DENIAL_REASON`: `"A denial reason is required when denying a refill request."`
  - `REFILL_MISSING_CANCELLATION_REASON`: `"A cancellation reason is required when cancelling a refill request."`

**Test case targets:**
- POST a second refill with the same `participant_id`, `medication_name`, and `requested_at` within the same tenant → assert `409` with `REFILL_DUPLICATE`
- POST a refill for a `medication_name` that already has an open request (status `requested`, `sent_to_pharmacy`, or `processing`) for the same `participant_id` and `tenant_id` → assert `409` with `REFILL_DUPLICATE_IN_FLIGHT`
- Transition an existing open refill to `fulfilled`, then POST a new refill for the same participant and medication → assert `201 Created` (in-flight restriction lifts on terminal status)
- Transition an existing open refill to `denied`, then POST a new refill for the same participant and medication → assert `201 Created`
- Transition an existing open refill to `cancelled`, then POST a new refill for the same participant and medication → assert `201 Created`
- POST a refill with `quantity_requested = 0` → assert `422` with `REFILL_INVALID_QUANTITY`
- POST a refill with `quantity_requested = -1` (negative value) → assert `422` with `REFILL_INVALID_QUANTITY`
- POST a refill with a valid positive integer `quantity_requested` → assert `201 Created`
- PATCH `quantity_requested = 0` on an existing refill → assert `422` with `REFILL_INVALID_QUANTITY`
- PATCH `quantity_requested = -5` on an existing refill → assert `422` with `REFILL_INVALID_QUANTITY`
- PATCH `medication_name`, `dose`, `route`, or `quantity_requested` on a `fulfilled` refill → assert `422` with `REFILL_FULFILLED_IMMUTABLE`
- PATCH `fulfilled_at` on a `fulfilled` refill → assert `200`; DB confirms `version` incremented and `status` remains `fulfilled`
- PATCH `ncpdp_script_reference` on a `fulfilled` refill → assert `200`; DB confirms `version` incremented
- PATCH a body containing both `ncpdp_script_reference` and `medication_name` on a `fulfilled` refill → assert `422` with `REFILL_FULFILLED_IMMUTABLE` (mixed body rejected in full)
- PATCH `status = 'denied'` with no `denial_reason` field → assert `422` with `REFILL_MISSING_DENIAL_REASON`
- PATCH `status = 'denied'` with `denial_reason = ""` (empty string) → assert `422` with `REFILL_MISSING_DENIAL_REASON`
- PATCH `status = 'denied'` with `denial_reason = "   "` (whitespace only) → assert `422` with `REFILL_MISSING_DENIAL_REASON`
- PATCH `status = 'denied'` with a non-empty `denial_reason` → assert `200`; DB confirms `status = 'denied'` and `denial_reason` persisted exactly as supplied
- PATCH `status = 'cancelled'` with no `cancellation_reason` field → assert `422` with `REFILL_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with `cancellation_reason = ""` (empty string) → assert `422` with `REFILL_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with `cancellation_reason = "   "` (whitespace only) → assert `422` with `REFILL_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with a non-empty `cancellation_reason` → assert `200`; DB confirms `status = 'cancelled'` and `cancellation_reason` persisted exactly as supplied

---

#### 3.10.8 42 CFR Part 2 Compliance Note

When `is_controlled_substance = true`, the MedicationRefill record is subject to 42 CFR Part 2 access controls, consistent with the controls applied to MARRecord (3.5.8). The MedicationRefill entity carries its own `is_controlled_substance` flag — the control is evaluated from this field directly, not derived solely from `Participant.is_sud_record`. The strictest controls and the mandatory pharmacy consent gate apply when both `is_controlled_substance = true` and `Participant.is_sud_record = true`, which indicates a controlled substance refill in the context of a substance use disorder treatment record, the core scope of 42 CFR Part 2.

**Access restriction:**
- Read and write access to a refill record where `is_controlled_substance = true` is limited to `care_coordinator`, `nurse_medication_aide`, and `compliance_officer` roles
- `is_controlled_substance` is evaluated at the application service layer on every refill read and write — it is not sufficient to enforce this at the API Gateway, because `is_controlled_substance` is itself a Part 2-protected field that must not be exposed to the gateway layer
- API responses for unauthorized role requests return `403 Forbidden` with no indication of the refill record's existence
- `medication_name`, `dose`, `route`, `is_controlled_substance`, `denial_reason`, and `ncpdp_script_reference` are additionally redacted from list-view responses for unauthorized roles even when the participant's non-clinical fields are otherwise accessible

**Audit logging requirement:**
- Every read on a refill record where `is_controlled_substance = true` must be captured in the audit log with: `user_id`, `tenant_id`, `refill_id`, action type `PHI_READ`, timestamp, and outcome — before the response is returned to the caller
- Every write must be logged with action type `PHI_WRITE` and `data_affected` listing field names changed (never field values)
- Failed access attempts are logged with `ACCESS_DENIED`

**Relationship to Participant.is_sud_record:**
- The strictest controls apply when both `MedicationRefill.is_controlled_substance = true` AND `Participant.is_sud_record = true` — this combination indicates a controlled substance refill as part of SUD treatment, which is the core scope of 42 CFR Part 2
- When `is_controlled_substance = true` but `Participant.is_sud_record = false`, the refill may represent a controlled substance unrelated to SUD treatment (e.g., pain management); elevated access controls still apply per this design, but the full Part 2 consent gate for external pharmacy disclosure is triggered only when `Participant.is_sud_record = true`

**External disclosure:**
- No MedicationRefill record where `is_controlled_substance = true` and `Participant.is_sud_record = true` may be transmitted to a pharmacy or any external party — including via FHIR MedicationRequest or NCPDP SCRIPT exchange — without explicit patient consent documented in the system, consistent with 42 CFR Part 2 §2.31 and the pharmacy integration note in Section 2.4. The FHIR outbound adapter must verify that a valid consent record exists before generating or transmitting the FHIR MedicationRequest resource or the NCPDP SCRIPT message. A missing consent record blocks the pharmacy transmission and emits a `CONSENT_CHECK` audit event with outcome `DENIED`.

---

> **Pending approval before proceeding to 3.11 Reminder.**

---

### 3.11 Reminder

The Reminder entity records a scheduled notification destined for a participant or a registered family member, generated by the Reminder & Tracking App (Section 1.2, module 6). Each reminder captures the notification content, target channel, scheduled delivery time, and the full delivery lifecycle from scheduling through confirmed receipt or failure. Reminders support three primary use cases: appointment alerts, transport notifications, and general care communications addressed to the participant or their family. Outbound delivery is routed to mobile devices via Apple Push Notification service (APNs) or Firebase Cloud Messaging (FCM) per the integration layer (Section 2.4). The no-PHI-in-payload rule applies to every channel without exception: notification titles and bodies must contain no protected health information; clinical context is surfaced only after the recipient authenticates via the deep link embedded in the notification. Access to reminder records is gated by the `participant_family` RBAC role for family-member recipients; direct participant and care-team access follows the standard role hierarchy. 42 CFR Part 2 does not govern Reminder records directly, but reminder delivery for participants whose `is_sud_record = true` is subject to an SUD delivery gate when the reminder references a SUD-related appointment or care plan context.

> **Phase 2 scope:** core reminder record, delivery status lifecycle, and push notification channel integration (APNs/FCM). Automated reminder generation triggered by appointment scheduling events and care plan goal alerts are Phase 3. SMS and email channel delivery are deferred to Phase 3; Phase 2 supports push channel only.

#### 3.11.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `reminder_id` | UUID (PK) | Non-PHI | System-generated; never user-supplied |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries must filter by this |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Central link to the Participant record; `Participant.is_sud_record` is read at delivery time to evaluate the SUD delivery gate (see 3.11.8) |

#### 3.11.2 Content Fields

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `reminder_type` | ENUM (`appointment`, `transport`, `general`) | Non-PHI | Category of the reminder; drives deep-link path construction and UI rendering on the mobile client; `appointment` reminders relate to the Physician Appointments module; `transport` reminders notify of scheduled pickup or drop-off; `general` covers administrative care communications |
| `title` | VARCHAR(100) | Non-PHI | Short notification title displayed in the device notification tray; must contain no PHI — no participant name, date of birth, diagnosis code, medication name, or appointment detail; generic text only, e.g., `"You have an upcoming appointment"`; validated on every POST and PATCH (see `REMINDER_PHI_IN_PAYLOAD`, 3.11.7) |
| `body` | VARCHAR(500) | Non-PHI | Notification body text delivered in the push payload; must contain no PHI; only a generic description and the deep-link token are permitted; a body containing any PHI pattern is rejected with `422` and error code `REMINDER_PHI_IN_PAYLOAD` before the record is written or the notification is queued (see 3.11.7) |
| `deep_link_path` | VARCHAR(500) | Non-PHI | Authenticated deep-link path embedded in the push payload; resolves to the relevant clinical screen (appointment detail, transport summary) only after the recipient completes authentication in the mobile app; the path itself must carry no PHI — no participant identifiers, diagnosis codes, or appointment dates that could be interpreted without authentication; consistent with the Section 2.4 integration constraint |
| `reference_entity_type` | ENUM (`appointment`, `none`) | Non-PHI | Nullable; indicates the type of clinical record this reminder is associated with; Phase 2 supports `appointment` and `none` only — the Transport entity is deferred to Phase 3 and `reference_entity_type` will be extended with a `transport_record` value at that time; no FK to a Transport entity exists in Phase 2; used at delivery time to evaluate the SUD delivery gate when `Participant.is_sud_record = true` (see 3.11.8); `none` or null when the reminder has no specific clinical record reference |
| `reference_entity_id` | UUID | Non-PHI | Nullable; the primary key of the associated appointment record; no FK constraint in Phase 2 — reminder generation from appointment records is Phase 3, and the Transport entity referenced by `reminder_type = 'transport'` is deferred to Phase 3 with no FK defined in Phase 2; stored as a soft reference for application-layer lookup at delivery time |

#### 3.11.3 Delivery & Status

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `status` | ENUM (`scheduled`, `sent`, `delivered`, `failed`, `cancelled`) | Non-PHI | State machine enforced at application layer: `scheduled` → `sent` → `delivered` or `failed`; `cancelled` may be set from any non-terminal state; terminal states (`delivered`, `failed`, `cancelled`) may not be reversed; a PATCH transitioning `status` to `cancelled` requires a non-empty `cancellation_reason` (see 3.11.7) |
| `channel` | ENUM (`push`) | Non-PHI | Delivery channel; Phase 2 supports `push` only; SMS and email are Phase 3; must be `push` on all Phase 2 records |
| `scheduled_for` | TIMESTAMPTZ | **Direct Identifier** | Date and time the reminder is scheduled for delivery to the device; HIPAA date/time identifier — the delivery time in conjunction with `participant_id` can imply an appointment date; encrypted at rest; must be strictly in the future at creation time (see `REMINDER_INVALID_SCHEDULED_FOR`, 3.11.7) |
| `sent_at` | TIMESTAMPTZ | **Direct Identifier** | Nullable; date and time the notification was submitted to APNs or FCM; HIPAA date/time identifier; encrypted at rest; set when `status` transitions to `sent` |
| `delivered_at` | TIMESTAMPTZ | **Direct Identifier** | Nullable; date and time the delivery receipt was received from APNs or FCM confirming device receipt; HIPAA date/time identifier; encrypted at rest; set when `status` transitions to `delivered` |
| `failure_reason` | VARCHAR(500) | Non-PHI | Nullable; populated when `status = 'failed'`; records the APNs or FCM error code and provider description returned by the push provider; must contain no PHI; writable only when `status = 'failed'` — a PATCH to `failure_reason` on a record with `status = 'delivered'` or `status = 'sent'` is rejected with `422` and `REMINDER_SENT_IMMUTABLE` (see 3.11.7) |
| `cancellation_reason` | VARCHAR(500) | Non-PHI | Nullable unless `status = 'cancelled'`; required and must be non-empty when `status` transitions to `cancelled`; a PATCH to `cancelled` without this field populated is rejected with `422` and error code `REMINDER_MISSING_CANCELLATION_REASON` (see 3.11.7) |

#### 3.11.4 Channel Integration

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `push_provider` | ENUM (`apns`, `fcm`) | Non-PHI | Nullable until delivery is attempted; identifies the push provider that handled the send; set when `status` transitions to `sent` |
| `device_push_token` | VARCHAR(500) | Non-PHI | Device push token registered by the participant or family member's mobile app session; required before the notification can be submitted to APNs or FCM; not encrypted — the token is a provider-assigned opaque identifier with no PHI content; validated as non-empty before the send attempt |
| `provider_message_id` | VARCHAR(200) | Non-PHI | Nullable; APNs `apns-id` or FCM message ID returned by the push provider on successful submission; used to correlate delivery receipts with provider logs; set when `status` transitions to `sent`; not encrypted — public provider transaction identifier |
| `recipient_user_id` | UUID (FK → User) | Non-PHI | Nullable; identifies the family member User record that is the intended recipient when the notification is directed to a registered family member rather than the participant's own portal session; when null, the notification is directed to the participant's primary registered device; must resolve to a User with `role = participant_family` when non-null; the `participant_family` RBAC gate limits read access to the reminder record to the matching user (see 3.11.8) |

#### 3.11.5 Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC; updated on every write |
| `created_by` | UUID (FK → User) | Non-PHI | User or service identity that created the reminder record; typically a `care_coordinator` or the Reminder & Tracking service identity for system-generated reminders |
| `updated_by` | UUID (FK → User) | Non-PHI | Last user or service to modify the record |
| `version` | INTEGER | Non-PHI | Optimistic locking; incremented on every permitted write; `title`, `body`, `deep_link_path`, `channel`, and `scheduled_for` are immutable once `status` is no longer `scheduled` (see `REMINDER_SENT_IMMUTABLE`, 3.11.7) |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within retention period |

---

#### 3.11.6 Relationships to Other Entities

| Entity | Relationship | Cardinality | Key Link | Notes |
|---|---|---|---|---|
| **Participant** | A participant has zero or more reminders | 1 → Many | `reminder.participant_id` | `Participant.is_sud_record` is read at delivery time to evaluate the SUD delivery gate (see 3.11.8); no PHI from the Participant record is embedded in the notification payload |
| **User (participant_family)** | A family member user may be the named recipient of a reminder | Many → 1 | `reminder.recipient_user_id` | Nullable; must resolve to `role = participant_family`; when non-null, the family member is the intended notification recipient and must satisfy the `participant_family` RBAC gate to read the reminder record (see 3.11.8); the participant's own portal session retains read access to all reminders associated with their `participant_id` regardless of `recipient_user_id` |
| **Appointment** | An appointment may contextually prompt a reminder for the same participant; no direct FK in Phase 2 | Indirect | `reminder.reference_entity_id` / `appointment.appointment_id` | `reference_entity_type = 'appointment'` and `reference_entity_id` carry the soft association; automated reminder generation triggered by appointment scheduling events is Phase 3; in Phase 2, reminders referencing appointments are created manually by care coordinators |
| **CarePlan** | A care plan may contextually prompt care goal reminders for the same participant; no direct FK in Phase 2 | Indirect | `reminder.participant_id` / `care_plan.participant_id` | Care plan goal-based alert generation is Phase 3; no `reference_entity_type` value for care plan is defined in Phase 2; alignment is by participant at the workflow level |

---

#### 3.11.7 Unique Constraints

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_reminder_participant_type_scheduled_for` | `tenant_id`, `participant_id`, `reminder_type`, `scheduled_for` | Per tenant | Return HTTP 409 with error code `REMINDER_DUPLICATE`; do not create a second record |
| `uq_reminder_participant_type_open` | `tenant_id`, `participant_id`, `reminder_type` WHERE `status = 'scheduled'` | Per tenant (partial index) | Return HTTP 409 with error code `REMINDER_DUPLICATE_SCHEDULED`; only one scheduled reminder per type per participant per tenant is permitted at any time |

**Rules:**
- `uq_reminder_participant_type_scheduled_for` prevents two reminders of the same type for the same participant at the identical scheduled delivery time within a tenant. This exact-match constraint is enforced at both the database and application layers as a backstop against concurrent duplicate submissions.
- `uq_reminder_participant_type_open` (in-flight uniqueness): A participant may have at most one reminder in `scheduled` status per `reminder_type` per tenant at any time. A new reminder of the same type is rejected if an existing reminder for the same `participant_id`, `reminder_type`, and `tenant_id` currently has `status = 'scheduled'`. The restriction lifts when the prior reminder reaches any non-`scheduled` status (`sent`, `delivered`, `failed`, or `cancelled`). This prevents duplicate push notifications for the same upcoming appointment or transport event.
- `REMINDER_PHI_IN_PAYLOAD`: A POST or PATCH that supplies a `title` or `body` value containing a detected PHI pattern — participant name, date of birth, age, diagnosis code, medication name, appointment date or time expressed as a human-readable string, or any other HIPAA-enumerated identifier — is rejected with `422 Unprocessable Entity` and error code `REMINDER_PHI_IN_PAYLOAD` before the record is written or the notification is queued. PHI pattern detection is enforced at the application service layer on every create and on every PATCH that includes `title` or `body`.
- `REMINDER_INVALID_SCHEDULED_FOR`: A POST that supplies a `scheduled_for` value at or before the current UTC timestamp is rejected with `422 Unprocessable Entity` and error code `REMINDER_INVALID_SCHEDULED_FOR`. Reminders must be scheduled for a strictly future delivery time; the comparison is performed against server UTC at the moment the request is processed.
- `REMINDER_SENT_IMMUTABLE`: A reminder whose `status` is no longer `scheduled` is partially immutable. PATCH requests that include any of `title`, `body`, `deep_link_path`, `channel`, or `scheduled_for` on a non-`scheduled` record are rejected with `422 Unprocessable Entity` and error code `REMINDER_SENT_IMMUTABLE`. PATCH to `failure_reason` is only permitted when `status = 'failed'`; a PATCH including `failure_reason` on a record with `status = 'delivered'` or `status = 'sent'` is rejected with `422 Unprocessable Entity` and `REMINDER_SENT_IMMUTABLE` because those states do not represent a delivery failure. PATCH requests limited to `failure_reason` on a `failed` record are accepted; the response is `200 OK` with `version` incremented. A PATCH body that mixes immutable and mutable fields is rejected as a whole with `422` — the caller must separate the writes.
- `REMINDER_MISSING_CANCELLATION_REASON`: A PATCH that transitions `status` to `cancelled` must supply a non-empty `cancellation_reason`. A request with `status = 'cancelled'` and an absent or empty-string `cancellation_reason` is rejected with `422 Unprocessable Entity` and error code `REMINDER_MISSING_CANCELLATION_REASON`. A request with `status = 'cancelled'` and a non-empty `cancellation_reason` is accepted; the database must confirm `status = 'cancelled'` and `cancellation_reason` persisted exactly as supplied.

**Implementation:**
- Database:
  - `UNIQUE (tenant_id, participant_id, reminder_type, scheduled_for)` index on the `reminder` table enforces the exact-match constraint as a backstop
  - Partial unique index `UNIQUE (tenant_id, participant_id, reminder_type) WHERE status = 'scheduled'` enforces the in-flight uniqueness constraint at the database layer as a backstop
- Application:
  - **In-flight uniqueness check:** On every POST, the service executes: `SELECT 1 FROM reminder WHERE tenant_id = :tenant_id AND participant_id = :participant_id AND reminder_type = :reminder_type AND status = 'scheduled' LIMIT 1`. A non-empty result returns `409 Conflict` with `REMINDER_DUPLICATE_SCHEDULED` before the insert is attempted.
  - **PHI-in-payload check:** On every POST and on every PATCH that includes `title` or `body`, the service runs the registered PHI pattern detector over both fields. If a match is found, the service returns `422 Unprocessable Entity` with `REMINDER_PHI_IN_PAYLOAD` before the write is attempted. The push notification adapter additionally validates the final composed payload against the same pattern set immediately before submission to APNs or FCM as a defence-in-depth check.
  - **Scheduled-for validation:** On every POST, the service compares `scheduled_for` to the current UTC timestamp. If `scheduled_for` is not strictly greater than the current UTC time, the service returns `422 Unprocessable Entity` with `REMINDER_INVALID_SCHEDULED_FOR` before the insert is attempted.
  - **Sent-immutable check:** On every PATCH, the service reads the current `status`. If `status != 'scheduled'` and the request body contains any of `title`, `body`, `deep_link_path`, `channel`, or `scheduled_for`, the service returns `422 Unprocessable Entity` with `REMINDER_SENT_IMMUTABLE` before the write is attempted. If the request body contains `failure_reason` and `status != 'failed'` (i.e., `status` is `delivered`, `sent`, or `cancelled`), the service also returns `422 Unprocessable Entity` with `REMINDER_SENT_IMMUTABLE`. If the body contains only `failure_reason` and `status = 'failed'`, the write proceeds and `version` is incremented. A PATCH body that mixes immutable and mutable fields is rejected as a whole with `422` — the caller must separate the writes.
  - **Cancellation-reason check:** On every PATCH, if `status = 'cancelled'` is present in the request body, the service validates that `cancellation_reason` is also present and evaluates to a non-empty string after stripping whitespace. If the check fails, the service returns `422 Unprocessable Entity` with `REMINDER_MISSING_CANCELLATION_REASON` before the write is attempted.
- Error messages exposed to the client:
  - `REMINDER_DUPLICATE`: `"A reminder of this type for this participant at this scheduled time already exists."`
  - `REMINDER_DUPLICATE_SCHEDULED`: `"A scheduled reminder of this type already exists for this participant. The existing reminder must be sent, delivered, failed, or cancelled before a new one can be scheduled."`
  - `REMINDER_PHI_IN_PAYLOAD`: `"Notification title and body must not contain protected health information."`
  - `REMINDER_INVALID_SCHEDULED_FOR`: `"scheduled_for must be a future date and time."`
  - `REMINDER_SENT_IMMUTABLE`: `"A reminder that has already been submitted to the push provider cannot have its content, channel, scheduled time, or failure reason changed."`
  - `REMINDER_MISSING_CANCELLATION_REASON`: `"A cancellation reason is required when cancelling a reminder."`

**Test case targets:**
- POST a second reminder with the same `participant_id`, `reminder_type`, and `scheduled_for` within the same tenant → assert `409` with `REMINDER_DUPLICATE`
- POST a reminder for a `participant_id` and `reminder_type` that already has a `scheduled` reminder within the same tenant → assert `409` with `REMINDER_DUPLICATE_SCHEDULED`
- Transition an existing `scheduled` reminder to `sent`, then POST a new reminder of the same type for the same participant → assert `201 Created` (in-flight restriction lifts on any non-`scheduled` status)
- Transition an existing `scheduled` reminder to `cancelled` with a non-empty `cancellation_reason`, then POST a new reminder of the same type for the same participant → assert `201 Created`
- POST a reminder with `scheduled_for` equal to the current UTC timestamp → assert `422` with `REMINDER_INVALID_SCHEDULED_FOR`
- POST a reminder with `scheduled_for` one hour in the past → assert `422` with `REMINDER_INVALID_SCHEDULED_FOR`
- POST a reminder with a `scheduled_for` value one minute in the future → assert `201 Created`
- POST a reminder with PHI text in `title` (e.g., participant full name) → assert `422` with `REMINDER_PHI_IN_PAYLOAD`
- POST a reminder with a diagnosis code string in `body` → assert `422` with `REMINDER_PHI_IN_PAYLOAD`
- POST a reminder with a medication name in `body` → assert `422` with `REMINDER_PHI_IN_PAYLOAD`
- POST a reminder with a generic, PHI-free `title` and `body` → assert `201 Created`
- PATCH `title` on a reminder with `status = 'sent'` → assert `422` with `REMINDER_SENT_IMMUTABLE`
- PATCH `scheduled_for` on a reminder with `status = 'delivered'` → assert `422` with `REMINDER_SENT_IMMUTABLE`
- PATCH `channel` on a reminder with `status = 'failed'` → assert `422` with `REMINDER_SENT_IMMUTABLE`
- PATCH `failure_reason` on a reminder with `status = 'delivered'` → assert `422` with `REMINDER_SENT_IMMUTABLE`
- PATCH `failure_reason` on a reminder with `status = 'sent'` → assert `422` with `REMINDER_SENT_IMMUTABLE`
- PATCH a body containing both `failure_reason` and `title` on a reminder with `status = 'sent'` → assert `422` with `REMINDER_SENT_IMMUTABLE` (mixed body rejected in full)
- PATCH `failure_reason` on a `failed` reminder → assert `200`; DB confirms `version` incremented and `status` remains `failed`
- PATCH `status = 'cancelled'` with no `cancellation_reason` field → assert `422` with `REMINDER_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with `cancellation_reason = ""` (empty string) → assert `422` with `REMINDER_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with `cancellation_reason = "   "` (whitespace only) → assert `422` with `REMINDER_MISSING_CANCELLATION_REASON`
- PATCH `status = 'cancelled'` with a non-empty `cancellation_reason` → assert `200`; DB confirms `status = 'cancelled'` and `cancellation_reason` persisted exactly as supplied
- Attempt to trigger delivery of a reminder where `Participant.is_sud_record = true` and `reference_entity_type = 'appointment'` without a valid consent record documented in the system per section 3.12 Consent — assert `status` remains `scheduled`, delivery is suppressed, and a `SUD_DELIVERY_GATE` audit event is emitted with outcome `SUPPRESSED`
- Attempt to GET a reminder record where `recipient_user_id` does not match the requesting user's `user_id` (requesting user has `role = participant_family`) — assert `403 Forbidden`

---

#### 3.11.8 Privacy Note

**No-PHI-in-payload rule:**

The no-PHI-in-payload constraint governs every outbound push notification generated from a Reminder record. The rule derives from the Section 2.4 integration constraint for the APNs/FCM channel and applies without exception across all `reminder_type` values and all participant contexts. The push payload delivered to the device — specifically the `title` and `body` fields — must contain no protected health information of any kind: no participant name, date of birth, age, diagnosis code, medication name, appointment date or time expressed as human-readable text, provider name, or any of the 18 HIPAA identifiers. Only a generic notification string and a deep-link token are permitted in the payload. Clinical context (appointment detail, transport schedule, care communication) is surfaced exclusively through the authenticated deep-link destination — the participant or family member must complete authentication in the mobile app before the clinical screen is rendered.

The `REMINDER_PHI_IN_PAYLOAD` check (see 3.11.7) is the enforcement mechanism at write time. The push notification adapter additionally validates the final composed payload against the same PHI pattern set immediately before submission to APNs or FCM. A payload that fails the pre-send check is held in `status = 'scheduled'`, the delivery attempt is aborted, and a `PHI_PAYLOAD_BLOCKED` audit event is emitted with `reminder_id`, `tenant_id`, `user_id`, and timestamp — no payload content is captured in the audit log.

**`participant_family` RBAC gate:**

Read access to Reminder records is governed by role at the record level. The `participant_family` role grants access only to reminder records where `recipient_user_id` matches the requesting user's `user_id` — a family member cannot enumerate or read reminders directed to the participant's own portal session or to a different family member. The participant's own authenticated portal session has read access to all reminders associated with their `participant_id` regardless of `recipient_user_id`. Staff roles — `care_coordinator` and above — may read all reminder records for participants within their tenant. The `nurse_medication_aide` and `billing_specialist` roles have no access to reminder records.

The `participant_family` RBAC gate is evaluated at the application service layer on every reminder read and list operation; enforcement at the API Gateway alone is insufficient because the access decision depends on `recipient_user_id`, which requires a record-level check unavailable at the gateway.

Write access follows a narrower rule: only `care_coordinator` and above may create, update, or cancel reminder records in Phase 2. Participants and family members interact with reminders through the read-only portal; they do not hold write access to reminder records directly.

**SUD delivery gate:**

42 CFR Part 2 does not govern the Reminder entity directly — reminder records contain no SUD diagnosis data, treatment episode information, or controlled substance references and therefore fall outside the core scope of 42 CFR Part 2. However, a reminder that references a SUD-related clinical context — identified when `Participant.is_sud_record = true` and `reference_entity_type = 'appointment'` (a `transport_record` and care-plan value are Phase 3) — is subject to a delivery gate before the push notification is submitted to APNs or FCM.

The delivery gate operates as follows:
- At the time the Reminder & Tracking service prepares a push submission, it reads `Participant.is_sud_record` for the associated participant
- If `is_sud_record = true` and `reference_entity_type` is not `none`, the service evaluates whether a valid consent record documented in the system per section 3.12 Consent exists for this participant
- If no valid consent record exists, the notification is held in `status = 'scheduled'`, the delivery attempt is aborted, and a `SUD_DELIVERY_GATE` audit event is emitted with `reminder_id`, `participant_id`, `tenant_id`, and outcome `SUPPRESSED`
- If a valid consent record exists, delivery proceeds normally and the audit event is emitted with outcome `ALLOWED`
- When `is_sud_record = false`, or when `reference_entity_type = 'none'`, the SUD delivery gate does not apply and the standard no-PHI payload check alone governs delivery

The `SUD_DELIVERY_GATE` audit event is emitted for every delivery attempt — both `SUPPRESSED` and `ALLOWED` outcomes — when `Participant.is_sud_record = true`. This preserves a complete delivery audit trail for SUD participants regardless of delivery outcome.

The `is_sud_record` value used for the gate check is read at delivery time, not stored on the Reminder record itself. This ensures that changes to `Participant.is_sud_record` — including on record closure or consent withdrawal — are reflected in subsequent delivery attempts without requiring reminder record updates.

---

> **Pending approval before proceeding to 3.12 Consent.**

---

### 3.12 Consent

The Consent entity records explicit patient consent for the disclosure of 42 CFR Part 2-protected information to external parties, and is the authoritative consent gate for every outbound SUD disclosure in the platform. It is referenced by CarePlan (3.8.9), Appointment (3.9.9), MedicationRefill (3.10.8), and Reminder (3.11.8) as the single source of truth for whether a disclosure is permitted at the time it is attempted. Each consent record is tied to one participant, specifies the permitted disclosure recipient type (`ehr`, `pharmacy`, or `push_notification`), names the specific recipient, states the purpose and scope of the disclosure, and carries an effective date and an expiration date as required by 42 CFR Part 2 §2.31. Consent may be withdrawn by the participant or authorized staff at any time by transitioning `status` to `withdrawn`, which immediately blocks all future disclosures of that type for that participant; disclosures completed before withdrawal are unaffected. A new consent record may be created to restore disclosure authorization after a prior consent is withdrawn or has expired. The Consent entity is not module-specific — it is a cross-cutting regulatory artifact that supports every module conducting outbound PHI disclosures for SUD-flagged participants.

> **Phase 2 scope:** core consent fields, disclosure recipient type classification (`ehr`, `pharmacy`, `push_notification`), validity lifecycle (`active`, `withdrawn`, `expired`), and the four consent gate integrations (CarePlan FHIR disclosure per 3.8.9, Appointment FHIR disclosure per 3.9.9, MedicationRefill pharmacy transmission per 3.10.8, and Reminder push notification delivery per 3.11.8). The `expired` status is set by a background cron job that runs on a scheduled interval and evaluates `expiration_date` against the current server date, following the same pattern as the incident escalation alert job (3.6.8); Phase 3 replaces the cron with an event-driven expiration trigger. Multi-recipient batch consent, re-disclosure prohibition tracking, and integration with an external consent management platform are Phase 3.

#### 3.12.1 Core Reference

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `consent_id` | UUID (PK) | Non-PHI | System-generated; never user-supplied |
| `tenant_id` | UUID (FK → Tenant) | Non-PHI | Row-level tenant isolation; all queries must filter by this |
| `participant_id` | UUID (FK → Participant) | Clinical PHI | Central link to the Participant record; a consent record is only gate-relevant when `Participant.is_sud_record = true`; a consent record for a participant where `is_sud_record = false` is accepted but produces no gate effect because Part 2 disclosure controls are not triggered for that participant |

#### 3.12.2 Consent Scope Fields

These fields satisfy the written consent content requirements of 42 CFR Part 2 §2.31(a)(3)–(5).

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `disclosure_recipient_type` | ENUM (`ehr`, `pharmacy`, `push_notification`) | Non-PHI | Category of the external disclosure this consent authorizes; `ehr` covers FHIR-based exchange with physician EHR systems and is the gate type checked by CarePlan (3.8.9) and Appointment (3.9.9); `pharmacy` covers FHIR MedicationRequest and NCPDP SCRIPT transmission and is the gate type checked by MedicationRefill (3.10.8); `push_notification` covers APNs/FCM delivery for SUD-flagged participants and is the gate type checked by Reminder (3.11.8); the disclosure gate in each referencing module filters on this exact value |
| `disclosure_recipient_name` | VARCHAR(200) | Non-PHI | Name of the specific individual, organization, or program authorized to receive the disclosure, as required by 42 CFR Part 2 §2.31(a)(3); e.g., `"Walgreens Pharmacy NPI 1234567890"`, `"Dr. A. Smith EHR via FHIR"`, `"Participant Mobile App Push Notifications"`; required on create; must be non-empty |
| `disclosure_purpose` | VARCHAR(500) | Non-PHI | Specific purpose of the disclosure as required by 42 CFR Part 2 §2.31(a)(4); e.g., `"Treatment coordination with attending physician"`, `"Prescription fulfillment for active medication regimen"`, `"Appointment and transport reminder delivery"`; required on create; must be non-empty |
| `scope_description` | VARCHAR(1000) | Clinical PHI | Description of the type and extent of information to be disclosed as required by 42 CFR Part 2 §2.31(a)(5); encrypted at rest because the scope description may reference specific SUD treatment context, diagnosis category, or medication class; required on create; must be non-empty |

#### 3.12.3 Status & Validity Lifecycle

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `status` | ENUM (`active`, `withdrawn`, `expired`) | Non-PHI | `active` — consent is in force and permits disclosures of the authorized type, subject to `effective_date` and `expiration_date` checks at disclosure time; `withdrawn` — consent has been explicitly revoked by the participant or authorized staff; terminal and irreversible; `expired` — set by the background cron job (see Phase 2 scope note) when `expiration_date` has passed; terminal; both `withdrawn` and `expired` immediately block all future disclosures of the authorized recipient type; a PATCH to any field on a `withdrawn` or `expired` record is rejected with `422` and `CONSENT_WITHDRAWN_IMMUTABLE` (see 3.12.7) |
| `effective_date` | DATE | **Direct Identifier** | Date on which the consent takes effect; HIPAA date identifier; encrypted at rest; must be strictly before `expiration_date` (see `CONSENT_INVALID_DATES`, 3.12.7); may be set to a past date to accommodate late entry of a consent form signed before system recording; at disclosure time the gate checks `effective_date <= CURRENT_DATE` in addition to `status = 'active'` |
| `expiration_date` | DATE | **Direct Identifier** | Date on which the consent expires, as required by 42 CFR Part 2 §2.31(a)(8); HIPAA date identifier; encrypted at rest; must be strictly after `effective_date` and strictly after the current date at creation time (see `CONSENT_EXPIRATION_IN_PAST`, 3.12.7); at disclosure time the gate checks `expiration_date > CURRENT_DATE`; the background cron job transitions `status` to `expired` when `expiration_date` passes, following the same scheduled-interval pattern as the incident escalation alert job (3.6.8); Phase 3 replaces the cron with an event-driven expiration trigger |
| `withdrawn_at` | TIMESTAMPTZ | **Direct Identifier** | Nullable; date and time the consent was withdrawn; HIPAA date/time identifier; encrypted at rest; set when `status` transitions to `withdrawn`; immutable once set |
| `withdrawal_reason` | VARCHAR(500) | Non-PHI | Nullable; records the reason the participant or staff withdrew consent; not required — a participant holds an absolute right to withdraw without explanation per 42 CFR Part 2 §2.31(c); populated when provided at withdrawal time |

#### 3.12.4 Documentation Fields

These fields satisfy the signature and execution record requirements of 42 CFR Part 2 §2.31(a)(7) and (a)(9).

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `consent_form_reference` | VARCHAR(200) | Non-PHI | Reference to the signed consent form artifact stored in the platform's document management system (S3 object key or document record ID); required on create — a consent record may not be activated without a documented consent artifact, consistent with the written consent requirement of 42 CFR Part 2 §2.31; a POST without a non-empty `consent_form_reference` is rejected with `422` and `CONSENT_MISSING_FORM_REFERENCE` (see 3.12.7) |
| `consent_method` | ENUM (`written`, `electronic`) | Non-PHI | Indicates how consent was executed; `written` for a physically signed paper form; `electronic` for a digitally signed or acknowledged form permissible under HITECH; required on create |
| `participant_signature_date` | DATE | **Direct Identifier** | Date the participant or their authorized representative signed the consent form, as required by 42 CFR Part 2 §2.31(a)(9); HIPAA date identifier; encrypted at rest; required on create |
| `witnessed_by_user_id` | UUID (FK → User) | Non-PHI | Nullable; identifies the staff user who witnessed consent execution; must resolve to an active User record within the same tenant when non-null; not required by §2.31 but recommended as a platform practice for evidentiary purposes |

#### 3.12.5 Audit Metadata

| Field | Data Type | PHI Class | Notes |
|---|---|---|---|
| `created_at` | TIMESTAMPTZ | Non-PHI | UTC |
| `updated_at` | TIMESTAMPTZ | Non-PHI | UTC; updated on every write |
| `created_by` | UUID (FK → User) | Non-PHI | Staff user who created the consent record; typically `care_coordinator` or `compliance_officer` |
| `updated_by` | UUID (FK → User) | Non-PHI | Last user or service to modify the record; on withdrawal this is the staff user or system identity that set `status = 'withdrawn'` |
| `version` | INTEGER | Non-PHI | Optimistic locking; incremented on every permitted write; `disclosure_recipient_type`, `disclosure_recipient_name`, `disclosure_purpose`, `scope_description`, `effective_date`, `expiration_date`, `participant_signature_date`, `consent_form_reference`, and `consent_method` are immutable once `status` is no longer `active` (see `CONSENT_WITHDRAWN_IMMUTABLE`, 3.12.7) |
| `is_deleted` | BOOLEAN | Non-PHI | Soft delete only; HIPAA prohibits permanent deletion within the applicable retention period; 42 CFR Part 2 §2.16 requires SUD records to be retained per applicable state and federal schedules |

---

#### 3.12.6 Relationships to Other Entities

| Entity | Relationship | Cardinality | Key Link | Notes |
|---|---|---|---|---|
| **Participant** | A participant has zero or more consent records | 1 → Many | `consent.participant_id` | A consent record produces a gate effect only while `Participant.is_sud_record = true`; the gate query always reads `Participant.is_sud_record` at disclosure time — a consent record alone does not authorize disclosure if the participant's SUD flag has been cleared |
| **CarePlan** | A valid `ehr` consent is required before a CarePlan FHIR resource may be transmitted for a SUD-flagged participant; no direct FK | Indirect | `consent.participant_id` / `care_plan.participant_id` WHERE `disclosure_recipient_type = 'ehr'` | The CarePlan FHIR outbound adapter (3.8.9) queries this entity for an active, non-expired `ehr` consent before generating or transmitting the FHIR CarePlan resource; absence of a qualifying record emits `CONSENT_CHECK` with outcome `DENIED` and blocks the transmission |
| **Appointment** | A valid `ehr` consent is required before an Appointment FHIR resource may be transmitted for a SUD-flagged participant; no direct FK | Indirect | `consent.participant_id` / `appointment.participant_id` WHERE `disclosure_recipient_type = 'ehr'` | The Appointment FHIR outbound adapter (3.9.9) applies the same gate as CarePlan; a single active `ehr` consent covers FHIR disclosure for both CarePlan and Appointment in Phase 2 |
| **MedicationRefill** | A valid `pharmacy` consent is required before a refill where `is_controlled_substance = true` and `Participant.is_sud_record = true` may be transmitted to a pharmacy; no direct FK | Indirect | `consent.participant_id` / `refill.participant_id` WHERE `disclosure_recipient_type = 'pharmacy'` | The MedicationRefill pharmacy transmission adapter (3.10.8) queries this entity before generating or transmitting the FHIR MedicationRequest or NCPDP SCRIPT message; absence of a qualifying record emits `CONSENT_CHECK` with outcome `DENIED` and blocks the transmission |
| **Reminder** | A valid `push_notification` consent is required before a push notification is delivered to a SUD-flagged participant where `reference_entity_type != 'none'`; no direct FK | Indirect | `consent.participant_id` / `reminder.participant_id` WHERE `disclosure_recipient_type = 'push_notification'` | The Reminder & Tracking delivery adapter (3.11.8) queries this entity before submitting the push payload to APNs or FCM; absence of a qualifying record emits `SUD_DELIVERY_GATE` with outcome `SUPPRESSED` and holds the reminder in `status = 'scheduled'` |

---

#### 3.12.7 Unique Constraints

| Constraint | Fields | Scope | Behavior on Violation |
|---|---|---|---|
| `uq_consent_participant_type_active` | `tenant_id`, `participant_id`, `disclosure_recipient_type` WHERE `status = 'active'` | Per tenant (partial index) | Return HTTP 409 with error code `CONSENT_DUPLICATE_ACTIVE`; only one active consent per disclosure type per participant per tenant is permitted at any time |

**Rules:**
- `uq_consent_participant_type_active` (active uniqueness): A participant may have at most one consent record in `active` status per `disclosure_recipient_type` per tenant at any time. A POST that would create a second active consent of the same type for the same participant within the same tenant is rejected with `409 Conflict` and error code `CONSENT_DUPLICATE_ACTIVE`. The restriction lifts when the prior consent reaches status `withdrawn` or `expired`, at which point a new active consent of the same type may be created. Multiple withdrawn or expired historical consents of the same type for the same participant are permitted and are not subject to this constraint.
- `CONSENT_INVALID_DATES`: A POST or PATCH that supplies an `expiration_date` that is not strictly after `effective_date` is rejected with `422 Unprocessable Entity` and error code `CONSENT_INVALID_DATES`. A consent period must be a positive duration — `expiration_date` equal to `effective_date` is not permitted.
- `CONSENT_EXPIRATION_IN_PAST`: A POST that supplies an `expiration_date` at or before the current server UTC date is rejected with `422 Unprocessable Entity` and error code `CONSENT_EXPIRATION_IN_PAST`. A consent cannot be created already expired; the `expiration_date` must allow a future validity window at the time of creation.
- `CONSENT_MISSING_FORM_REFERENCE`: A POST that does not supply a non-empty `consent_form_reference` is rejected with `422 Unprocessable Entity` and error code `CONSENT_MISSING_FORM_REFERENCE`. A consent record may not be activated without a reference to a signed consent artifact, consistent with the written consent documentation requirement of 42 CFR Part 2 §2.31.
- `CONSENT_WITHDRAWN_IMMUTABLE`: Any PATCH to a consent record with `status = 'withdrawn'` or `status = 'expired'` is rejected with `422 Unprocessable Entity` and error code `CONSENT_WITHDRAWN_IMMUTABLE`. Terminal consent records are fully immutable — neither their scope fields nor their status may be altered. A new consent record must be created to restore disclosure authorization.

**Implementation:**
- Database:
  - Partial unique index `UNIQUE (tenant_id, participant_id, disclosure_recipient_type) WHERE status = 'active'` on the `consent` table enforces the active-uniqueness constraint at the database layer as a backstop
- Application:
  - **Active-uniqueness check:** On every POST, the service executes: `SELECT 1 FROM consent WHERE tenant_id = :tenant_id AND participant_id = :participant_id AND disclosure_recipient_type = :disclosure_recipient_type AND status = 'active' LIMIT 1`. A non-empty result returns `409 Conflict` with `CONSENT_DUPLICATE_ACTIVE` before the insert is attempted.
  - **Date validation:** On every POST and on every PATCH that includes `effective_date` or `expiration_date`, the service validates: (1) `expiration_date` is strictly after `effective_date`; if not, returns `422 Unprocessable Entity` with `CONSENT_INVALID_DATES` before the write is attempted. (2) `expiration_date` is strictly after the current server UTC date; if not, returns `422 Unprocessable Entity` with `CONSENT_EXPIRATION_IN_PAST` before the write is attempted. Both checks run before the write is attempted.
  - **Form-reference check:** On every POST, the service validates that `consent_form_reference` is present and evaluates to a non-empty string after stripping whitespace. If the check fails, the service returns `422 Unprocessable Entity` with `CONSENT_MISSING_FORM_REFERENCE` before the insert is attempted.
  - **Immutability check:** On every PATCH, the service reads the current `status`. If `status` is `withdrawn` or `expired`, the service returns `422 Unprocessable Entity` with `CONSENT_WITHDRAWN_IMMUTABLE` before the write is attempted, regardless of which fields the request body contains.
  - **Disclosure gate query:** At the moment each referencing module (CarePlan, Appointment, MedicationRefill, Reminder) prepares an outbound SUD disclosure, the service executes: `SELECT 1 FROM consent WHERE tenant_id = :tenant_id AND participant_id = :participant_id AND disclosure_recipient_type = :disclosure_recipient_type AND status = 'active' AND effective_date <= CURRENT_DATE AND expiration_date > CURRENT_DATE LIMIT 1`. A non-empty result permits the disclosure; an empty result blocks it and emits the appropriate audit event (`CONSENT_CHECK` with outcome `DENIED` for CarePlan, Appointment, and MedicationRefill adapters; `SUD_DELIVERY_GATE` with outcome `SUPPRESSED` for the Reminder adapter).
- Error messages exposed to the client:
  - `CONSENT_DUPLICATE_ACTIVE`: `"An active consent of this type already exists for this participant. The existing consent must be withdrawn or expired before a new one can be created."`
  - `CONSENT_INVALID_DATES`: `"expiration_date must be strictly after effective_date."`
  - `CONSENT_EXPIRATION_IN_PAST`: `"expiration_date must be a future date. A consent cannot be created already expired."`
  - `CONSENT_MISSING_FORM_REFERENCE`: `"A consent form reference is required. The signed consent artifact must be documented before the consent record is activated."`
  - `CONSENT_WITHDRAWN_IMMUTABLE`: `"A withdrawn or expired consent record cannot be modified. Create a new consent record to restore authorization."`

**Test case targets:**
- POST a consent with `expiration_date = effective_date` → assert `422` with `CONSENT_INVALID_DATES`
- POST a consent with `expiration_date` one day before `effective_date` → assert `422` with `CONSENT_INVALID_DATES`
- POST a consent with `expiration_date` equal to today's date → assert `422` with `CONSENT_EXPIRATION_IN_PAST`
- POST a consent with `expiration_date` one day in the past → assert `422` with `CONSENT_EXPIRATION_IN_PAST`
- POST a consent with `effective_date = today` and `expiration_date` one year in the future → assert `201 Created`
- POST a consent with `effective_date` two days in the past and `expiration_date` one year in the future → assert `201 Created` (past `effective_date` is permitted to accommodate late entry of a signed form)
- POST a second consent with the same `participant_id` and `disclosure_recipient_type` within the same tenant while a prior consent of that type has `status = 'active'` → assert `409` with `CONSENT_DUPLICATE_ACTIVE`
- PATCH `status = 'withdrawn'` on the first active consent, then POST a new consent with the same `participant_id` and `disclosure_recipient_type` → assert `201 Created` (active-uniqueness restriction lifts when prior consent reaches `withdrawn`)
- POST a consent without a `consent_form_reference` field → assert `422` with `CONSENT_MISSING_FORM_REFERENCE`
- POST a consent with `consent_form_reference = ""` (empty string) → assert `422` with `CONSENT_MISSING_FORM_REFERENCE`
- POST a consent with `consent_form_reference = "   "` (whitespace only) → assert `422` with `CONSENT_MISSING_FORM_REFERENCE`
- PATCH any field on a consent with `status = 'withdrawn'` → assert `422` with `CONSENT_WITHDRAWN_IMMUTABLE`
- PATCH any field on a consent with `status = 'expired'` → assert `422` with `CONSENT_WITHDRAWN_IMMUTABLE`
- PATCH `status = 'withdrawn'` on an active consent without a `withdrawal_reason` → assert `200`; DB confirms `status = 'withdrawn'` and `withdrawn_at` is non-null (withdrawal reason not required)
- PATCH `status = 'withdrawn'` with a non-empty `withdrawal_reason` on an active consent → assert `200`; DB confirms `status = 'withdrawn'`, `withdrawn_at` non-null, and `withdrawal_reason` persisted exactly as supplied
- Attempt a MedicationRefill pharmacy transmission for a participant where `is_sud_record = true` and `is_controlled_substance = true` with no active `pharmacy` consent record in the system for that participant → assert transmission blocked and `CONSENT_CHECK` audit event emitted with outcome `DENIED`
- Attempt a MedicationRefill pharmacy transmission for a participant where `is_sud_record = true` and `is_controlled_substance = true` with an active `pharmacy` consent whose `expiration_date` has passed → assert transmission blocked and `CONSENT_CHECK` audit event emitted with outcome `DENIED`
- Attempt a MedicationRefill pharmacy transmission for a participant where `is_sud_record = true` and `is_controlled_substance = true` with an active, non-expired `pharmacy` consent where `effective_date <= today` → assert transmission proceeds and `CONSENT_CHECK` audit event emitted with outcome `ALLOWED`
- Attempt a CarePlan FHIR transmission for a participant where `is_sud_record = true` with no active `ehr` consent → assert transmission blocked and `CONSENT_CHECK` audit event emitted with outcome `DENIED`
- Attempt a Reminder push delivery for a participant where `is_sud_record = true` and `reference_entity_type = 'appointment'` with no active `push_notification` consent → assert delivery suppressed, `status` remains `scheduled`, and `SUD_DELIVERY_GATE` audit event emitted with outcome `SUPPRESSED`

---

#### 3.12.8 42 CFR Part 2 Compliance Note

The Consent entity is the regulatory core of the platform's 42 CFR Part 2 disclosure framework. Unlike other entities that carry a Part 2 flag and defer to this entity for gate authorization, the Consent entity defines the authorization boundary itself: no outbound disclosure of SUD-protected information may proceed without an active, non-expired consent record of the matching `disclosure_recipient_type` for the relevant participant. This section documents how the entity fulfills the requirements of 42 CFR Part 2 §2.31 and governs the gate mechanics shared by the four referencing entities.

**§2.31 field mapping:**

| §2.31 Requirement | Satisfied By |
|---|---|
| §2.31(a)(1) — Name of patient | `participant_id` → Participant record |
| §2.31(a)(2) — Name of the disclosing SUD program | Platform identity (system configuration; not a per-record field) |
| §2.31(a)(3) — Name or title of recipient | `disclosure_recipient_name` + `disclosure_recipient_type` |
| §2.31(a)(4) — Purpose of the disclosure | `disclosure_purpose` |
| §2.31(a)(5) — Amount and kind of information | `scope_description` |
| §2.31(a)(6) — Re-disclosure prohibition notice | Delivered with the signed consent form artifact referenced by `consent_form_reference` |
| §2.31(a)(7) — Signature of patient or representative | `participant_signature_date` + `consent_method` + `consent_form_reference` |
| §2.31(a)(8) — Date consent expires | `expiration_date` |
| §2.31(a)(9) — Date signed | `participant_signature_date` |
| §2.31(c) — Right to revoke at any time | `status = 'withdrawn'`; no `withdrawal_reason` required |

**Consent gate mechanics:**

The disclosure gate is executed by each referencing module at the moment an outbound disclosure is prepared — not at the moment the source record (CarePlan, Appointment, MedicationRefill, Reminder) is created or updated. This ensures that consent changes (withdrawal, expiration) are reflected immediately in all subsequent disclosure attempts without requiring updates to the clinical records themselves. The gate query checks all of the following conditions simultaneously:

- `Participant.is_sud_record = true` for the relevant participant
- A consent record exists with `participant_id = :participant_id` AND `tenant_id = :tenant_id` AND `disclosure_recipient_type = :disclosure_recipient_type` AND `status = 'active'` AND `effective_date <= CURRENT_DATE` AND `expiration_date > CURRENT_DATE`

If any condition is not satisfied, the disclosure is blocked. The audit event carries outcome `DENIED` (for `CONSENT_CHECK` events emitted by the CarePlan, Appointment, and MedicationRefill adapters) or `SUPPRESSED` (for `SUD_DELIVERY_GATE` events emitted by the Reminder adapter). All outcomes — permitted and blocked — are audit-logged; the `consent_id` of the matching record is included in the log when the outcome is `ALLOWED`.

**Withdrawal effect:**

Setting `status = 'withdrawn'` on a Consent record is immediate and irrevocable. From the moment `withdrawn_at` is set, the gate query returns no qualifying result for that `disclosure_recipient_type`, and all subsequent disclosure attempts of that type for that participant are blocked. No retroactive effect applies to disclosures already completed under the prior active consent — those are governed by the audit log. A new consent record of the same type may be created at any time after withdrawal; the active-uniqueness constraint in 3.12.7 does not apply to `withdrawn` or `expired` records.

**Audit logging requirement:**
- Every consent creation must be logged with action type `CONSENT_CREATED`, including `consent_id`, `participant_id`, `tenant_id`, `disclosure_recipient_type`, `effective_date`, `expiration_date`, and `created_by` — `scope_description` must not appear in the audit log payload, as it may contain sensitive SUD treatment context
- Every withdrawal must be logged with action type `CONSENT_WITHDRAWN`, including `consent_id`, `participant_id`, `tenant_id`, `disclosure_recipient_type`, `withdrawn_at`, and `updated_by`
- Every expiration transition must be logged with action type `CONSENT_EXPIRED`, including `consent_id`, `participant_id`, `tenant_id`, and the date of expiration
- Every disclosure gate evaluation must be logged with its outcome (`ALLOWED` or `DENIED`/`SUPPRESSED`), `consent_id` when a qualifying record was found, `disclosure_recipient_type` evaluated, and the identity of the service that triggered the check — regardless of outcome

**Relationship to `Participant.is_sud_record`:**

A consent record for a participant where `is_sud_record = false` produces no gate effect, because Part 2 disclosure controls are not triggered for that participant. The gate query checks `Participant.is_sud_record` first; if `false`, the disclosure proceeds without a consent check and no `CONSENT_CHECK` audit event is required. Changes to `Participant.is_sud_record` are reflected in all subsequent gate evaluations without requiring consent record updates. If `is_sud_record` transitions to `true` after clinical records have already been created, the consent gate applies to all future disclosures of those records from that point forward.

---

> **Pending approval before proceeding to Phase 2 completion.**

---

> **Phase 1 data model complete. Pending client approval to begin Phase 2 or proceed to test strategy.**

