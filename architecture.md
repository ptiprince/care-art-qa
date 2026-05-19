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

*Next section pending approval: **3. Module Requirements***

---

## 3. Core Data Model

> **Approach:** Entities are defined one at a time with client approval before proceeding. Each entity specifies field name, data type, PHI classification, and storage/handling rules.

> **Phased scope:**
> **Phase 1** covers the minimum entities needed to support mock backend development and initial test coverage: Participant (already defined), User, Attendance, Claim, MARRecord, and Incident. **Phase 2** will add: CarePlan, Appointment, MedicationRefill, and Reminder. This phased approach keeps the mock backend simple while covering the highest-risk regulatory flows first.

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

**Phase 2 entities to be defined:** CarePlan, Appointment, MedicationRefill, Reminder.

---

> **Phase 1 data model complete. Pending client approval to begin Phase 2 or proceed to test strategy.**

