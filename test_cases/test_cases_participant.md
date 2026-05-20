# Care Art — Test Cases: Participant

> **Status:** Phase 1 draft. Covers TC-1.1–TC-1.12 for the Participant group. One test case per scenario. Test function names correspond to test_participant.py.
> **Regulatory scope:** HIPAA · 42 CFR Part 2 · CMS (Medicaid/Medicare) · State adult day care licensing

---

## Summary

| Test ID | Test Function | Layer | Regulatory Reference |
|---|---|---|---|
| TC-1.1 | test_1_1_positive_participant_creation_by_program_administrator | API | CMS Medicaid/Medicare; State Adult Day Care Licensing |
| TC-1.2 | test_1_2_positive_user_login_valid_credentials | API | HIPAA §164.312(d) |
| TC-1.3 | test_1_3_negative_user_login_wrong_password_returns_401 | API | HIPAA §164.312(d) |
| TC-1.4 | test_1_4_duplicate_medicaid_id_returns_409 | API | CMS Medicaid Billing Integrity |
| TC-1.5 | test_1_5_sud_record_billing_specialist_returns_403_no_disclosure | API | 42 CFR Part 2 §2.13(b) |
| TC-1.6 | test_1_6_audit_log_phi_operation_mandatory_fields_no_phi_values | Business Rules | HIPAA §164.312(b); SOC 2 CC7.2 |
| TC-1.7 | test_1_7_state_machine_active_to_on_leave_returns_200 | Business Rules | State Adult Day Care Licensing |
| TC-1.8 | test_1_8_state_machine_deceased_to_active_returns_422 | Business Rules | State Adult Day Care Licensing |
| TC-1.9 | test_1_9_soft_delete_returns_200_is_deleted_true | API | HIPAA §164.530(j) — Record Retention |
| TC-1.10 | test_1_10_hard_delete_attempt_returns_405_record_persists | API | HIPAA §164.530(j) — Record Retention |
| TC-1.11 | test_1_11_missing_first_name_returns_400_with_field_name | API | CMS Medicaid/Medicare |
| TC-1.12 | test_1_12_missing_enrollment_date_returns_400_with_field_name | API | State Adult Day Care Licensing |

---

## Test Cases

### TC-1.1 — Positive Participant Creation by Program_administrator

| Field | Value |
|---|---|
| **Test ID** | TC-1.1 |
| **Test Function** | test_1_1_positive_participant_creation_by_program_administrator |
| **Layer** | API |
| **REQ_ID** | 1.7 |
| **Regulatory Reference** | CMS Medicaid/Medicare; State Adult Day Care Licensing |

**Preconditions**

No participant with these details exists in the system. Program_administrator role is authenticated.

**Test Steps**

1. Prepare a POST /participants payload with tenant_id, first_name, last_name, date_of_birth, and enrollment_date.
2. Send POST /participants using program_administrator headers.
3. Assert response status is 201 Created.
4. Assert response body contains participant_id, first_name, last_name, date_of_birth, and enrollment_date.
5. Assert program_status defaults to "active" in the response.

**Expected Result**

HTTP 201 Created. Response body contains the assigned participant_id and all submitted fields. program_status is set to "active" automatically.

---

### TC-1.2 — Positive User Login with Valid Credentials

| Field | Value |
|---|---|
| **Test ID** | TC-1.2 |
| **Test Function** | test_1_2_positive_user_login_valid_credentials |
| **Layer** | API |
| **REQ_ID** | 2.5 |
| **Regulatory Reference** | HIPAA §164.312(d) |

**Preconditions**

A user account exists with a known email and password. The account is active and MFA is enabled.

**Test Steps**

1. Prepare a POST /login payload with the valid email and correct password.
2. Send POST /login.
3. Assert response status is 200 OK.
4. Assert response body contains a session token or access token.

**Expected Result**

HTTP 200 OK. Login succeeds and the response includes valid session credentials. No error is returned.

---

### TC-1.3 — Negative User Login with Wrong Password Returns 401

| Field | Value |
|---|---|
| **Test ID** | TC-1.3 |
| **Test Function** | test_1_3_negative_user_login_wrong_password_returns_401 |
| **Layer** | API |
| **REQ_ID** | 2.5 |
| **Regulatory Reference** | HIPAA §164.312(d) |

**Preconditions**

A user account exists with a known email. An incorrect password is used for the attempt.

**Test Steps**

1. Prepare a POST /login payload with the valid email and an incorrect password.
2. Send POST /login.
3. Assert response status is 401 Unauthorized.
4. Assert no session token is present in the response body.
5. Assert the error message does not reveal whether the email or the password was wrong.

**Expected Result**

HTTP 401 Unauthorized. No session token is returned. The error message is generic and does not disclose which field (email or password) was incorrect.

---

### TC-1.4 — Duplicate Medicaid ID Returns 409

| Field | Value |
|---|---|
| **Test ID** | TC-1.4 |
| **Test Function** | test_1_4_duplicate_medicaid_id_returns_409 |
| **Layer** | API |
| **REQ_ID** | 1.1 |
| **Regulatory Reference** | CMS Medicaid Billing Integrity |

**Preconditions**

A participant with medicaid_id="MCD-001" already exists in tenant-aaa-001. Program_administrator role is authenticated.

**Test Steps**

1. Send POST /participants with medicaid_id="MCD-001" and a different first_name and last_name in the same tenant-aaa-001.
2. Assert response status is 409 Conflict.
3. Assert detail.error_code = "PARTICIPANT_DUPLICATE_MEDICAID_ID".

**Expected Result**

HTTP 409 Conflict. The response body contains error_code="PARTICIPANT_DUPLICATE_MEDICAID_ID". No duplicate record is created in the database.

---

### TC-1.5 — SUD Record Protected from billing_specialist Returns 403 Without Disclosure

| Field | Value |
|---|---|
| **Test ID** | TC-1.5 |
| **Test Function** | test_1_5_sud_record_billing_specialist_returns_403_no_disclosure |
| **Layer** | API |
| **REQ_ID** | 1.3 |
| **Regulatory Reference** | 42 CFR Part 2 §2.13(b) |

**Preconditions**

A participant with is_sud_record=true has been created in tenant-aaa-001 by program_administrator. billing_specialist role is authenticated in the same tenant.

**Test Steps**

1. Send GET /participants/{participant_id} using billing_specialist headers.
2. Assert response status is 403 Forbidden.
3. Assert detail.error_code contains "SUD".
4. Assert the response body contains no participant data — no participant_id, no PHI fields, no is_sud_record flag value.

**Expected Result**

HTTP 403 Forbidden with error_code containing "SUD". The existence of the record is not revealed. No participant data of any kind appears in the error response body.

---

### TC-1.6 — Audit Log on PHI Operation Contains All Mandatory Fields and No PHI Values

| Field | Value |
|---|---|
| **Test ID** | TC-1.6 |
| **Test Function** | test_1_6_audit_log_phi_operation_mandatory_fields_no_phi_values |
| **Layer** | Business Rules |
| **REQ_ID** | 1.4 |
| **Regulatory Reference** | HIPAA §164.312(b); SOC 2 CC7.2 |

**Preconditions**

A program_administrator and a compliance_officer are both authenticated in tenant-aaa-001.

**Test Steps**

1. Send POST /participants using program_administrator headers. Record the returned participant_id.
2. Send GET /audit-logs with tenant_id="tenant-aaa-001", resource_type="Participant", resource_id={participant_id} using compliance_officer headers.
3. Assert response status is 200 OK.
4. Locate the event with action_type="PHI_WRITE" in the returned list.
5. Assert all 11 mandatory fields are non-null: timestamp, user_id, tenant_id, session_id, action_type, resource_type, resource_id, data_affected, source_ip, outcome, layer.
6. Assert PHI values — first_name, last_name, date_of_birth — are absent from data_affected.

**Expected Result**

Audit log contains a PHI_WRITE event with outcome="SUCCESS". All 11 mandatory fields from Section 2.6.1 are populated. PHI values do not appear in data_affected.

---

### TC-1.7 — State Machine Positive: active → on_leave Returns 200

| Field | Value |
|---|---|
| **Test ID** | TC-1.7 |
| **Test Function** | test_1_7_state_machine_active_to_on_leave_returns_200 |
| **Layer** | Business Rules |
| **REQ_ID** | 1.5 |
| **Regulatory Reference** | State Adult Day Care Licensing |

**Preconditions**

A participant with program_status="active" exists in tenant-aaa-001. Program_administrator role is authenticated.

**Test Steps**

1. Record the participant_id and current version.
2. Send PATCH /participants/{participant_id} with program_status="on_leave" and the correct version value.
3. Assert response status is 200 OK.
4. Assert program_status="on_leave" in the response body.

**Expected Result**

HTTP 200 OK. The program_status transitions to "on_leave" successfully. The updated status is reflected in the response body.

---

### TC-1.8 — State Machine Negative: deceased → active Returns 422

| Field | Value |
|---|---|
| **Test ID** | TC-1.8 |
| **Test Function** | test_1_8_state_machine_deceased_to_active_returns_422 |
| **Layer** | Business Rules |
| **REQ_ID** | 1.5 |
| **Regulatory Reference** | State Adult Day Care Licensing |

**Preconditions**

A participant exists and has been transitioned to program_status="deceased". Program_administrator role is authenticated.

**Test Steps**

1. Record the participant_id and current version after the deceased transition.
2. Send PATCH /participants/{participant_id} with program_status="active" and the current version.
3. Assert response status is 422 Unprocessable Entity.
4. Assert error_code contains "TRANSITION".

**Expected Result**

HTTP 422 Unprocessable Entity. The transition from deceased to active is blocked. The error code indicates an invalid state transition. The participant record remains unchanged.

---

### TC-1.9 — Soft Delete Positive: Returns 200 and is_deleted True in DB

| Field | Value |
|---|---|
| **Test ID** | TC-1.9 |
| **Test Function** | test_1_9_soft_delete_returns_200_is_deleted_true |
| **Layer** | API |
| **REQ_ID** | 1.8 |
| **Regulatory Reference** | HIPAA §164.530(j) — Record Retention |

**Preconditions**

A participant exists in tenant-aaa-001 and has not been deleted. Program_administrator role is authenticated.

**Test Steps**

1. Record the participant_id.
2. Send DELETE /participants/{participant_id} using program_administrator headers.
3. Assert response status is 200 OK.
4. Assert is_deleted=true in the response body.
5. Send GET /participants/{participant_id} using a standard role (e.g., care_coordinator).
6. Assert response status is 404 Not Found.

**Expected Result**

HTTP 200 OK with is_deleted=true in the response. A subsequent standard GET on the same participant_id returns 404. The database row is not physically removed.

---

### TC-1.10 — Soft Delete Negative: Physical Delete Attempt Returns 405 Record Remains in DB

| Field | Value |
|---|---|
| **Test ID** | TC-1.10 |
| **Test Function** | test_1_10_hard_delete_attempt_returns_405_record_persists |
| **Layer** | API |
| **REQ_ID** | 1.9 |
| **Regulatory Reference** | HIPAA §164.530(j) — Record Retention |

**Preconditions**

A participant exists in tenant-aaa-001. Program_administrator role is authenticated.

**Test Steps**

1. Record the participant_id.
2. Send DELETE /participants/{participant_id}/hard using program_administrator headers.
3. Assert response status is 405 Method Not Allowed.
4. Send GET /participants/{participant_id} using compliance_officer headers with include_deleted=true.
5. Assert the participant record is still present in the response.

**Expected Result**

HTTP 405 Method Not Allowed. The physical database row is not removed. The record remains retrievable by compliance_officer with include_deleted=true.

---

### TC-1.11 — Required Field Missing first_name Returns 400 with Field Name in Error

| Field | Value |
|---|---|
| **Test ID** | TC-1.11 |
| **Test Function** | test_1_11_missing_first_name_returns_400_with_field_name |
| **Layer** | API |
| **REQ_ID** | 1.7 |
| **Regulatory Reference** | CMS Medicaid/Medicare |

**Preconditions**

Program_administrator role is authenticated. No participant with these details needs to exist beforehand.

**Test Steps**

1. Prepare a POST /participants payload with tenant_id, last_name, date_of_birth, and enrollment_date — omitting first_name.
2. Send POST /participants using program_administrator headers.
3. Assert response status is 400 or 422.
4. Assert the response body contains "first_name" identifying the missing field.

**Expected Result**

HTTP 400 or 422. The error response explicitly names "first_name" as the missing or invalid field. No participant record is created.

---

### TC-1.12 — Required Field Missing enrollment_date Returns 400 with Field Name in Error

| Field | Value |
|---|---|
| **Test ID** | TC-1.12 |
| **Test Function** | test_1_12_missing_enrollment_date_returns_400_with_field_name |
| **Layer** | API |
| **REQ_ID** | 1.6 |
| **Regulatory Reference** | State Adult Day Care Licensing |

**Preconditions**

Program_administrator role is authenticated. No participant with these details needs to exist beforehand.

**Test Steps**

1. Prepare a POST /participants payload with tenant_id, first_name, last_name, and date_of_birth — omitting enrollment_date.
2. Send POST /participants using program_administrator headers.
3. Assert response status is 400.
4. Assert the response body contains "enrollment_date" identifying the missing field.

**Expected Result**

HTTP 400. The error response explicitly names "enrollment_date" as the missing field. No participant record is created.
