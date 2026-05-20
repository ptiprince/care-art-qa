# Care Art — Test Cases: Participant

> **Status:** Phase 1 draft. Covers REQ_IDs 1.1–1.10 as defined in test_plan_phase1.md Section 2.1. One test case per requirement. Test function names correspond to test_participant.py.
> **Regulatory scope:** HIPAA · 42 CFR Part 2 · CMS (Medicaid/Medicare) · State adult day care licensing

---

## Summary

| Test ID | Test Function | Layer | Regulatory Reference |
|---|---|---|---|
| TC-1.1 | test_1_1_unique_medicaid_id_per_tenant | API | CMS Medicaid Billing Integrity |
| TC-1.2 | test_1_2_rbac_write_restricted_to_staff_roles | API | HIPAA §164.312(a)(1) |
| TC-1.3 | test_1_3_42cfr_part2_sud_record_access_gate | API | 42 CFR Part 2 §2.13(b) |
| TC-1.4 | test_1_4_audit_log_on_phi_read_and_write | Business Rules | HIPAA §164.312(b); SOC 2 CC7.2 |
| TC-1.5 | test_1_5_program_status_state_machine_transitions | Business Rules | State Adult Day Care Licensing |
| TC-1.6 | test_1_6_enrollment_date_required_and_discharge_date_auto_set | Business Rules | State Adult Day Care Licensing |
| TC-1.7 | test_1_7_mandatory_fields_on_participant_creation | API | CMS Medicaid/Medicare |
| TC-1.8 | test_1_8_soft_delete_no_hard_delete | API | HIPAA §164.530(j) — Record Retention |
| TC-1.9 | test_1_9_is_deleted_excluded_from_standard_queries | API | HIPAA §164.530(j) — Record Retention |
| TC-1.10 | test_1_10_optimistic_locking_version_conflict_returns_409 | Business Rules | HIPAA §164.312(b) — Data Integrity |

---

## Test Cases

### TC-1.1 — Unique Medicaid ID Per Tenant

| Field | Value |
|---|---|
| **Test ID** | TC-1.1 |
| **Test Function** | test_1_1_unique_medicaid_id_per_tenant |
| **Layer** | API |
| **Regulatory Reference** | CMS Medicaid Billing Integrity |

**Preconditions**

- A `program_administrator` user is active, MFA-enabled, and scoped to `tenant-aaa-001`.
- The test database is empty; no Participant with `medicaid_id="MCD-001"` exists in `tenant-aaa-001`.

**Test Steps**

1. Send `POST /participants` with `tenant_id="tenant-aaa-001"`, `medicaid_id="MCD-001"`, and all required fields using `program_administrator` headers.
2. Assert the response status is `201 Created` and record the returned `participant_id`.
3. Send a second `POST /participants` with the same `tenant_id="tenant-aaa-001"` and `medicaid_id="MCD-001"` for a different participant (different `first_name`, `last_name`).
4. Assert the response status and inspect the error body.

**Expected Result**

The second POST returns HTTP `409 Conflict`. The response body contains `detail.error_code = "PARTICIPANT_DUPLICATE_MEDICAID_ID"`. The first participant remains in the database unchanged.

---

### TC-1.2 — RBAC Write Restricted to Staff Roles

| Field | Value |
|---|---|
| **Test ID** | TC-1.2 |
| **Test Function** | test_1_2_rbac_write_restricted_to_staff_roles |
| **Layer** | API |
| **Regulatory Reference** | HIPAA §164.312(a)(1) |

**Preconditions**

- Active, MFA-enabled users exist for the `physician`, `participant_family`, and `program_administrator` roles, all scoped to `tenant-aaa-001`.
- The test database is empty.

**Test Steps**

1. Send `POST /participants` with valid participant fields using `physician` role headers.
2. Assert the response status is `403 Forbidden`.
3. Send `POST /participants` with the same payload using `participant_family` role headers.
4. Assert the response status is `403 Forbidden`.
5. Send `POST /participants` with the same payload using `program_administrator` role headers.
6. Assert the response status is `201 Created`.

**Expected Result**

Both `physician` and `participant_family` receive HTTP `403 Forbidden`. The `program_administrator` request succeeds with HTTP `201 Created`. All access denials are recorded in the audit log.

---

### TC-1.3 — 42 CFR Part 2 SUD Record Access Gate

| Field | Value |
|---|---|
| **Test ID** | TC-1.3 |
| **Test Function** | test_1_3_42cfr_part2_sud_record_access_gate |
| **Layer** | API |
| **Regulatory Reference** | 42 CFR Part 2 §2.13(b) |

**Preconditions**

- A `program_administrator` user is active and MFA-enabled.
- A `billing_specialist` user is active and MFA-enabled.
- Both users are scoped to `tenant-aaa-001`.
- No SUD-flagged Participant exists yet.

**Test Steps**

1. Send `POST /participants` with `is_sud_record=true` using `program_administrator` headers. Record the returned `participant_id`.
2. Send `GET /participants/{participant_id}` using `billing_specialist` headers.
3. Assert the response status and inspect the error body for SUD indicator.
4. Send `GET /participants/{participant_id}` using `program_administrator` headers.
5. Assert the response status and verify full participant data is returned.

**Expected Result**

The `billing_specialist` request returns HTTP `403 Forbidden` with `detail.error_code` containing `"SUD"`. No participant data (including `participant_id`, clinical fields, or the `is_sud_record` flag value) appears in the `403` response body. The `program_administrator` request returns HTTP `200 OK` with the full participant record.

---

### TC-1.4 — Audit Log on PHI Read and Write

| Field | Value |
|---|---|
| **Test ID** | TC-1.4 |
| **Test Function** | test_1_4_audit_log_on_phi_read_and_write |
| **Layer** | Business Rules |
| **Regulatory Reference** | HIPAA §164.312(b); SOC 2 CC7.2 |

**Preconditions**

- A `program_administrator` user is active and MFA-enabled in `tenant-aaa-001`.
- A `compliance_officer` user is active and MFA-enabled in `tenant-aaa-001`.
- The test database is empty.

**Test Steps**

1. Send `POST /participants` with standard participant fields using `program_administrator` headers. Record the returned `participant_id`.
2. Send `GET /audit-logs` with query params `tenant_id="tenant-aaa-001"`, `resource_type="Participant"`, `resource_id={participant_id}` using `compliance_officer` headers.
3. Assert the response status is `200 OK`.
4. Locate the event with `action_type="PHI_WRITE"` in the returned list.
5. Assert that the following 11 fields are all non-null: `timestamp`, `user_id`, `tenant_id`, `session_id`, `action_type`, `resource_type`, `resource_id`, `data_affected`, `source_ip`, `outcome`, `layer`.
6. Assert `outcome="SUCCESS"` and `resource_type="Participant"`.
7. Assert that PHI values — `"Jane"`, `"Doe"`, `"1980-01-15"` — do not appear anywhere in the `data_affected` payload.

**Expected Result**

At least one `PHI_WRITE` audit event is present for the created Participant. All 11 mandatory audit fields are non-null. No PHI values appear in `data_affected`. Audit records carry a retention period of at least 6 years.

---

### TC-1.5 — Program Status State Machine Transitions

| Field | Value |
|---|---|
| **Test ID** | TC-1.5 |
| **Test Function** | test_1_5_program_status_state_machine_transitions |
| **Layer** | Business Rules |
| **Regulatory Reference** | State Adult Day Care Licensing |

**Preconditions**

- A `program_administrator` user is active and MFA-enabled in `tenant-aaa-001`.
- The test database is empty.
- Valid transitions: `active → on_leave`, `active → discharged`, `active → deceased`, `on_leave → active`, `on_leave → discharged`. Terminal states: `discharged`, `deceased`.

**Test Steps**

1. Send `POST /participants` → record `participant_id` and `version`.
2. Send `PATCH /participants/{participant_id}` with `program_status="discharged"` and correct `version`. Assert `200 OK` and `program_status="discharged"` in the response. Record new `version`.
3. Send `PATCH /participants/{participant_id}` with `program_status="on_leave"` (disallowed from `discharged`) and the current `version`. Assert `422 Unprocessable Entity` and that `error_code` contains `"TRANSITION"`.
4. Create a second participant via `POST /participants` with distinct `medicaid_id`. Record `participant_id` and `version`.
5. Send `PATCH /participants/{participant_id}` with `program_status="on_leave"` and correct `version`. Assert `200 OK` and `program_status="on_leave"`.

**Expected Result**

The disallowed transition (`discharged → on_leave`) returns HTTP `422` with an error code containing `"TRANSITION"`. Valid transitions (`active → discharged`, `active → on_leave`) return HTTP `200` with the updated `program_status` reflected in the response body.

---

### TC-1.6 — Enrollment Date Required; Discharge Date Auto-Set

| Field | Value |
|---|---|
| **Test ID** | TC-1.6 |
| **Test Function** | test_1_6_enrollment_date_required_and_discharge_date_auto_set |
| **Layer** | Business Rules |
| **Regulatory Reference** | State Adult Day Care Licensing |

**Preconditions**

- A `program_administrator` user is active and MFA-enabled in `tenant-aaa-001`.
- The test database is empty.

**Test Steps**

1. Send `POST /participants` with `first_name`, `last_name`, `date_of_birth`, and `tenant_id` but **without** `enrollment_date`.
2. Assert the response status is `400 Bad Request` and that `"enrollment_date"` or `"ENROLLMENT"` appears in the response body.
3. Send `POST /participants` with all required fields including `enrollment_date="2026-01-01"`. Record `participant_id` and `version`.
4. Send `PATCH /participants/{participant_id}` with `program_status="discharged"` and correct `version`, without supplying a `discharge_date`.
5. Assert the response status is `200 OK`.
6. Assert that `discharge_date` in the response body is non-null.

**Expected Result**

POST without `enrollment_date` returns HTTP `400` identifying the missing field. PATCH to `discharged` without a caller-supplied `discharge_date` returns HTTP `200` with `discharge_date` automatically set to the current UTC date.

---

### TC-1.7 — Mandatory Fields on Participant Creation

| Field | Value |
|---|---|
| **Test ID** | TC-1.7 |
| **Test Function** | test_1_7_mandatory_fields_on_participant_creation |
| **Layer** | API |
| **Regulatory Reference** | CMS Medicaid/Medicare |

**Preconditions**

- A `program_administrator` user is active and MFA-enabled in `tenant-aaa-001`.
- The test database is empty.

**Test Steps**

1. Send `POST /participants` with all required fields **except** `first_name`. Assert `422 Unprocessable Entity`.
2. Send `POST /participants` with all required fields **except** `date_of_birth`. Assert `422 Unprocessable Entity`.
3. Send `POST /participants` with all required fields **except** `tenant_id`. Assert `422 Unprocessable Entity`.

**Expected Result**

Each POST missing a required field returns HTTP `422 Unprocessable Entity`. The response body identifies the absent field. A valid POST with all mandatory fields (`first_name`, `last_name`, `date_of_birth`, `enrollment_date`, `tenant_id`) returns `201 Created`.

---

### TC-1.8 — Soft Delete, No Hard Delete

| Field | Value |
|---|---|
| **Test ID** | TC-1.8 |
| **Test Function** | test_1_8_soft_delete_no_hard_delete |
| **Layer** | API |
| **Regulatory Reference** | HIPAA §164.530(j) — Record Retention |

**Preconditions**

- A `program_administrator` user is active and MFA-enabled in `tenant-aaa-001`.
- A Participant has been created and `participant_id` is known.

**Test Steps**

1. Send `POST /participants` → record `participant_id`.
2. Send `DELETE /participants/{participant_id}` using `program_administrator` headers.
3. Assert the response status is `200 OK`.
4. Assert that `is_deleted=true` appears in the response body.
5. Send `DELETE /participants/{participant_id}/hard` using `program_administrator` headers.
6. Assert the response status.

**Expected Result**

Soft delete (`DELETE /participants/{participant_id}`) returns HTTP `200` with `is_deleted=true`. Hard delete (`DELETE /participants/{participant_id}/hard`) returns HTTP `405 Method Not Allowed`. The physical database row is not removed; the record and its audit log references remain intact for the full HIPAA retention period.

---

### TC-1.9 — is_deleted Excluded from Standard Queries

| Field | Value |
|---|---|
| **Test ID** | TC-1.9 |
| **Test Function** | test_1_9_is_deleted_excluded_from_standard_queries |
| **Layer** | API |
| **Regulatory Reference** | HIPAA §164.530(j) — Record Retention |

**Preconditions**

- A `program_administrator` user is active and MFA-enabled in `tenant-aaa-001`.
- A `compliance_officer` user is active and MFA-enabled in `tenant-aaa-001`.
- A Participant has been created and then soft-deleted; its `participant_id` is known.

**Test Steps**

1. Send `POST /participants` → record `participant_id`.
2. Send `DELETE /participants/{participant_id}` → soft-delete the record.
3. Send `GET /participants?tenant_id=tenant-aaa-001` using `program_administrator` headers.
4. Assert the response status is `200 OK`.
5. Assert that `participant_id` from step 1 is **not** present in the returned list.
6. Send `GET /participants?tenant_id=tenant-aaa-001&include_deleted=true` using `compliance_officer` headers.
7. Assert the response status is `200 OK`.
8. Assert that `participant_id` from step 1 **is** present in the returned list with `is_deleted=true`.

**Expected Result**

The standard list endpoint (`GET /participants`) excludes records where `is_deleted=true`. The compliance audit query (`include_deleted=true`) returns the soft-deleted record with `is_deleted=true`. Each compliance query generates an audit event.

---

### TC-1.10 — Optimistic Locking — Version Conflict Returns 409

| Field | Value |
|---|---|
| **Test ID** | TC-1.10 |
| **Test Function** | test_1_10_optimistic_locking_version_conflict_returns_409 |
| **Layer** | Business Rules |
| **Regulatory Reference** | HIPAA §164.312(b) — Data Integrity |

**Preconditions**

- A `program_administrator` user is active and MFA-enabled in `tenant-aaa-001`.
- A Participant has been created with a known `version` (initial version is `1`).

**Test Steps**

1. Send `POST /participants` → record `participant_id` and `version` (e.g., `version=1`).
2. Send `PATCH /participants/{participant_id}` with `version=version-1` (stale value) and `program_status="on_leave"`.
3. Assert the response status is `409 Conflict`.
4. Assert `detail.error_code = "PARTICIPANT_VERSION_CONFLICT"`.
5. Send `PATCH /participants/{participant_id}` with `version=version` (correct current value) and `program_status="on_leave"`.
6. Assert the response status is `200 OK`.
7. Assert that `version` in the response body equals `version+1`.

**Expected Result**

PATCH with a stale `version` returns HTTP `409 Conflict` with `error_code = "PARTICIPANT_VERSION_CONFLICT"`. PATCH with the correct current `version` returns HTTP `200 OK` with `version` incremented by 1 in the response body. Two concurrent PATCHes using the same initial version result in one `200` and one `409`.
