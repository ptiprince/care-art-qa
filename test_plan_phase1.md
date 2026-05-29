# Care Art - Test Plan: Phase 1

> **Status:** Phase 1 draft. Derived from test_strategy_phase1.md and requirements_phase1.xlsx. Each entity test function maps to exactly one REQ_ID. Cross-cutting test functions address concerns that span multiple entities or requirement types.
> **Regulatory scope:** HIPAA - 42 CFR Part 2 - CMS (Medicaid/Medicare) - State adult day care licensing

---

## 1. Overview

| Test File | Tests | REQ_IDs Covered | Layer(s) | Gate Group |
|---|---|---|---|---|
| test_participant.py | 12 | TC-1.1 - TC-1.12 | API, Business Rules | Unique constraints, RBAC, 42 CFR Part 2, State machine, Soft delete, Mandatory fields |
| test_user.py | 13 | TC-2.1 - TC-2.13 | API, Business Rules | Unique constraints, RBAC, Auth, Account lockout, State machine, Audit log, Mandatory fields |
| test_attendance.py | 12 | TC-3.1 - TC-3.12 | API, Business Rules | Unique constraints, RBAC, State machine, Billing units, Audit log, Billed immutability |
| test_claim.py | 15 | TC-4.1 - TC-4.15 | API, Business Rules | Unique constraints, RBAC, State machine, Attendance integrity, Mandatory fields, Audit log, Billing units server-calculated, Phase 2 field rejection, Optimistic locking, Tenant isolation, Not found |
| test_mar_record.py | 10 | 5.1 - 5.10 | API, Business Rules | Unique constraints, RBAC, 42 CFR Part 2, Optimistic locking |
| test_incident.py | 8 | 6.1 - 6.8 | API, Business Rules | Unique constraints, RBAC, 42 CFR Part 2, State machine, Optimistic locking |
| test_audit_log.py | 9 | Cross-cutting | DB, Business Rules | Audit log completeness (regulatory gate) |
| test_rbac_sweep.py | 9 | Cross-cutting | API | RBAC enforcement (security gate) |
| test_tenant_isolation.py | 7 | Cross-cutting | API, Business Rules | Tenant isolation (security gate) |
| db/test_schema.py | 8 | Cross-cutting | DB | Schema and constraint assertions (data integrity gate) |
| **Total** | **103** | **70 entity TCs** | | |

---

## 2. Entity Test Files

### 2.1 test_participant.py - Participant (12 tests)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_1_1_positive_participant_creation_by_program_administrator | TC-1.1 | API | POST /participants by program_administrator returns 201 with all required fields and program_status active |
| test_tc_1_2_positive_login_valid_credentials | TC-1.2 | API | POST /login with valid user_id and correct password returns 200 with status ok |
| test_tc_1_3_negative_login_wrong_password_returns_401 | TC-1.3 | API | POST /login with wrong non-empty password returns 401; error message does not reveal which credential was wrong |
| test_tc_1_4_duplicate_medicaid_id_returns_409 | TC-1.4 | API | POST with duplicate medicaid_id in same tenant returns 409 PARTICIPANT_DUPLICATE_MEDICAID_ID |
| test_tc_1_5_sud_record_billing_specialist_returns_403_no_disclosure | TC-1.5 | API | GET on is_sud_record=true by billing_specialist returns 403 SUD_ACCESS_DENIED with no participant data in response |
| test_tc_1_6_audit_log_phi_operation_mandatory_fields_no_phi_values | TC-1.6 | Business Rules | PHI_WRITE audit event after participant creation has all 11 mandatory fields non-null and no PHI values in data_affected |
| test_tc_1_7_state_machine_active_to_on_leave_returns_200 | TC-1.7 | Business Rules | PATCH program_status from active to on_leave returns 200 with updated status persisted in DB |
| test_tc_1_8_state_machine_deceased_to_active_returns_422 | TC-1.8 | Business Rules | PATCH program_status from deceased to active returns 422 with TRANSITION error code; DB status unchanged |
| test_tc_1_9_soft_delete_returns_200_is_deleted_true | TC-1.9 | API | DELETE returns 200 with is_deleted=true; subsequent GET by care_coordinator returns 404; row persists in DB |
| test_tc_1_10_hard_delete_attempt_returns_405_record_persists | TC-1.10 | API | DELETE /hard returns 405 HARD_DELETE_NOT_PERMITTED; record remains retrievable and row persists in DB |
| test_tc_1_11_missing_first_name_returns_400_with_field_name | TC-1.11 | API | POST without first_name returns 400 or 422 identifying first_name in the error; no participant row created |
| test_tc_1_12_missing_enrollment_date_returns_400_with_field_name | TC-1.12 | API | POST without enrollment_date returns 400 identifying enrollment_date in the error; no participant row created |

### 2.2 test_user.py - User (13 tests)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_2_1_positive_user_creation_by_program_administrator | TC-2.1 | API | POST /users by program_administrator returns 201 with all required fields and status active |
| test_tc_2_2_user_creation_by_unauthorized_role_returns_403 | TC-2.2 | API | POST /users by care_coordinator returns 403; no user row created in DB |
| test_tc_2_3_positive_login_valid_credentials_returns_200 | TC-2.3 | API | POST /login with valid user_id and correct password returns 200 with status ok; last_login_at updated in DB |
| test_tc_2_4_login_wrong_password_returns_401_no_credential_disclosure | TC-2.4 | API | POST /login with wrong non-empty password returns 401; message does not reveal email, user_id, or password; failed_login_count incremented in DB |
| test_tc_2_5_duplicate_email_same_tenant_returns_409 | TC-2.5 | API | POST with email already registered in same tenant returns 409 USER_DUPLICATE_EMAIL; exactly one row with that email in DB |
| test_tc_2_6_same_email_different_tenant_returns_201 | TC-2.6 | API | POST with same email in different tenant returns 201; two rows with that email coexist across tenants in DB |
| test_tc_2_7_account_lockout_after_5_failed_logins | TC-2.7 | Business Rules | 5 consecutive wrong-password logins lock the account; 6th attempt returns 401 ACCOUNT_LOCKED; locked_until set in DB |
| test_tc_2_8_locked_user_login_returns_401_account_locked | TC-2.8 | Business Rules | Locked user login with correct password returns 401 ACCOUNT_LOCKED; locked_until remains set in DB |
| test_tc_2_9_soft_delete_user_returns_200_status_inactive | TC-2.9 | API | PATCH status=inactive returns 200 with status inactive; deactivated_at set in DB; row persists (no physical removal) |
| test_tc_2_10_audit_log_on_user_creation_has_mandatory_fields_no_pii | TC-2.10 | Business Rules | PHI_WRITE audit event after user creation has all 11 mandatory fields non-null and no PII values in data_affected |
| test_tc_2_11_missing_email_returns_400_or_422_with_field_name | TC-2.11 | API | POST without email returns 400 or 422 identifying email in the error; no user row created in DB |
| test_tc_2_12_billing_specialist_create_participant_returns_403 | TC-2.12 | API | POST /participants by billing_specialist returns 403; no participant row created in DB |
| test_tc_2_13_nurse_create_claim_returns_403 | TC-2.13 | API | POST /claims by nurse_medication_aide returns 403; claim count for the participant unchanged in DB |

### 2.3 test_attendance.py - Attendance (12 tests)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_3_1_positive_attendance_creation_by_program_administrator | TC-3.1 | API | POST /attendance by program_administrator returns 201 with status pending and all required fields |
| test_tc_3_2_positive_attendance_creation_by_care_coordinator | TC-3.2 | API | POST /attendance by care_coordinator returns 201 with status pending; row persisted in DB |
| test_tc_3_3_missing_date_of_service_returns_400 | TC-3.3 | API | POST /attendance without date_of_service returns 400 or 422 identifying date_of_service; no row created |
| test_tc_3_4_missing_participant_id_returns_400 | TC-3.4 | API | POST /attendance without participant_id returns 400 or 422 identifying participant_id; no row created |
| test_tc_3_5_duplicate_participant_date_returns_409 | TC-3.5 | API | POST second Attendance for same participant_id and date_of_service returns 409 ATTENDANCE_DUPLICATE_DATE; exactly one row in DB |
| test_tc_3_6_status_transition_pending_to_confirmed | TC-3.6 | Business Rules | PATCH status from pending to confirmed returns 200; DB shows confirmed and version n+1 |
| test_tc_3_7_void_with_void_reason_returns_200 | TC-3.7 | Business Rules | PATCH with status=voided and void_reason returns 200; DB shows voided and void_reason persisted |
| test_tc_3_8_void_without_void_reason_returns_422 | TC-3.8 | Business Rules | PATCH with status=voided but no void_reason returns 422 VOID_REASON_REQUIRED; DB status unchanged |
| test_tc_3_9_billing_units_total_hours_to_authorized_units_consumed | TC-3.9 | Business Rules | total_hours converted server-side at Medicaid rate (1 h = 4 units); 6 h → 24, 8 h → 32; verified in DB |
| test_tc_3_10_billed_attendance_cannot_be_modified | TC-3.10 | Business Rules | PATCH on billed attendance returns 422 ATTENDANCE_BILLED_IMMUTABLE; DB status remains billed |
| test_tc_3_11_audit_log_on_creation_has_mandatory_fields_no_phi | TC-3.11 | Business Rules | PHI_WRITE audit event after POST /attendance has all 11 mandatory fields non-null and no PHI values in data_affected |
| test_tc_3_12_billing_specialist_create_attendance_returns_403 | TC-3.12 | API | POST /attendance by billing_specialist returns 403; attendance count for participant unchanged in DB |

### 2.4 test_claim.py - Claim (15 tests)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_4_1_duplicate_claim_reference_number_returns_409 | TC-4.1 | API | POST with duplicate claim_reference_number returns 409 CLAIM_DUPLICATE_REFERENCE; DB confirms exactly one claim with that reference |
| test_tc_4_2_composite_unique_key_prevents_duplicate_billing | TC-4.2 | API | POST with duplicate participant_id+date_of_service_start+procedure_code+payer_type returns 409 CLAIM_DUPLICATE; DB confirms one claim |
| test_tc_4_3_rbac_unauthorized_roles_return_403_db_count_unchanged | TC-4.3 | API | POST from care_coordinator, nurse_medication_aide, physician, participant_family each returns 403 RBAC_DENIED; DB claim count unchanged |
| test_tc_4_4_claim_status_immutability_and_transitions | TC-4.4 | Business Rules | PATCH non-status field on submitted returns 422 CLAIM_STATUS_IMMUTABLE; PATCH status returns 200; PATCH paid returns 422; DB status unchanged after rejected edits |
| test_tc_4_5_claim_requires_confirmed_attendance_records | TC-4.5 | Business Rules | POST referencing pending or voided attendance returns 422; cross-tenant returns 422/404; confirmed attendance returns 201 and sets attendance status to billed |
| test_tc_4_6_multi_attendance_units_billed_server_calculated | TC-4.6 | Business Rules | POST with multiple confirmed attendance returns 201; DB units_billed equals server-calculated sum of authorized_units_consumed; non-existent UUID returns 422 CLAIM_ATTENDANCE_NOT_FOUND |
| test_tc_4_7_missing_required_fields_return_400_with_field_name | TC-4.7 | API | POST without participant_id returns 400 identifying field; POST without procedure_code returns 400; POST without payer_type returns 400; no claim created in DB |
| test_tc_4_8_audit_log_phi_write_and_phi_disclose_events | TC-4.8 | Business Rules | POST produces PHI_WRITE audit event with all 11 mandatory fields non-null and no PHI values; PATCH draft-to-submitted produces PHI_DISCLOSE; GET /audit-logs returns both events |
| test_tc_4_9_empty_attendance_ids_and_server_calculates_units_billed | TC-4.9 | Business Rules | POST with empty attendance_ids returns 422 CLAIM_NO_ATTENDANCE_RECORDS; server calculates units_billed from authorized_units_consumed; caller-supplied value ignored |
| test_tc_4_10_phase2_fields_rejected_with_400 | TC-4.10 | API | POST with secondary_payer_id, mco_id, or prior_authorization_number each returns 400; DB no claim created in any case |
| test_tc_4_11_optimistic_locking_version_conflict_returns_409 | TC-4.11 | Business Rules | PATCH draft with stale version returns 409 CLAIM_VERSION_CONFLICT; submitted returns 422 before version check; correct version returns 200; DB version incremented |
| test_tc_4_12_cross_tenant_attendance_reference_rejected | TC-4.12 | API | POST referencing attendance from different tenant returns 422 or 404; DB no cross-tenant claim created |
| test_tc_4_13_already_billed_attendance_cannot_be_reclaimed | TC-4.13 | API | POST referencing attendance with status=billed returns 422 ATTENDANCE_NOT_CONFIRMED; DB no duplicate claim created |
| test_tc_4_14_get_nonexistent_claim_returns_404 | TC-4.14 | API | GET /claims with non-existent claim_id returns 404 NOT_FOUND; response body contains error_code and claim_id |
| test_tc_4_15_paid_claim_fully_immutable | TC-4.15 | Business Rules | PATCH paid claim any field returns 422 CLAIM_STATUS_IMMUTABLE; DB claim_status, version, and all fields unchanged after all rejected attempts |

### 2.5 test_mar_record.py - MARRecord (10 tests)

| Test Function | REQ_ID | Layer | What Is Verified |
|---|---|---|---|
| test_5_1_unique_mar_per_participant_medication_and_scheduled_time | 5.1 | API | POST with same participant_id+medication_name+scheduled_time in same tenant returns 409 MAR_DUPLICATE_EVENT |
| test_5_2_rbac_write_restricted_to_nurse_medication_aide | 5.2 | API | POST from care_coordinator or billing_specialist returns 403; service-layer check fires independently of gateway RBAC |
| test_5_3_42cfr_part2_controlled_substance_access_gate | 5.3 | API | GET controlled-substance MARRecord from unauthorized role returns 403 with no record content or existence confirmation |
| test_5_4_audit_log_on_controlled_substance_read_and_write | 5.4 | Business Rules | Write to controlled-substance MARRecord produces audit event before response; denied attempt produces ACCESS_DENIED event |
| test_5_5_status_field_rules_administered_refused_held_missed | 5.5 | API | POST administered with null administered_time returns 422; POST refused or held with null notes returns 422 |
| test_5_6_administered_time_required_and_within_bounds | 5.6 | API | Future administered_time returns 422 ADMIN_TIME_FUTURE; value more than 2 h before scheduled_time returns 422 ADMIN_TIME_TOO_EARLY |
| test_5_7_route_must_be_oral_injection_or_topical | 5.7 | API | POST with route outside allowed enum returns 400; null route returns 400; valid route value returns 201 |
| test_5_8_administered_record_is_immutable | 5.8 | API | PATCH on MARRecord with status=administered returns 422 for any field change |
| test_5_9_correction_record_references_original_mar_id | 5.9 | Business Rules | Correction POST without 20-char notes returns 422; without original mar_id ref returns 422; valid correction returns 201 and original unchanged |
| test_5_10_optimistic_locking_version_conflict_returns_409 | 5.10 | Business Rules | PATCH non-administered MARRecord with stale version returns 409 MAR_VERSION_CONFLICT; PATCH administered returns 422 before version check |

### 2.6 test_incident.py - Incident (8 tests)

| Test Function | REQ_ID | Layer | What Is Verified |
|---|---|---|---|
| test_6_1_incident_id_is_sole_unique_constraint_no_composite_key | 6.1 | Business Rules | Two POSTs for same participant+date+type both return 201 with distinct incident_ids confirming no composite constraint |
| test_6_2_rbac_staff_can_create_external_roles_denied | 6.2 | API | POST from any staff role returns 201; GET from physician or participant_family returns 403 |
| test_6_3_42cfr_part2_sud_related_incident_access_gate | 6.3 | API | GET is_sud_related=true Incident from billing_specialist returns 403; list response redacts description and incident_type |
| test_6_4_audit_log_on_sud_related_incident_read_and_write | 6.4 | Business Rules | Read or write on is_sud_related=true Incident produces audit event before response; unauthorized attempt produces ACCESS_DENIED event |
| test_6_5_state_machine_auto_escalates_severe_and_medical_emergency | 6.5 | Business Rules | POST with severity=severe auto-sets status to escalated; PATCH close on escalated without regulatory_submission_date returns 422 INCIDENT_MISSING_REGULATORY_SUBMISSION |
| test_6_6_alert_raised_when_escalated_incident_approaches_24_hour_deadline | 6.6 | Business Rules | Job identifies escalated Incident with null regulatory_submission_date and created_at > 20 h; alert and audit event confirmed |
| test_6_7_closed_incident_is_immutable | 6.7 | API | PATCH on closed Incident returns 422; new Incident referencing original incident_id as addendum returns 201 |
| test_6_8_optimistic_locking_version_conflict_returns_409 | 6.8 | Business Rules | PATCH with stale version returns 409 INCIDENT_VERSION_CONFLICT; PATCH closed returns 422 before version check |

---

## 3. Cross-Cutting Test Files

Cross-cutting tests verify controls that span multiple entities or that cannot be satisfied by a single entity test. They do not map to a single REQ_ID; the REQ_IDs column lists the requirements they collectively support.

### 3.1 test_audit_log.py - Audit Pipeline Completeness (9 tests)

Regulatory gate. Verifies that the audit pipeline receives complete, PHI-free events for every entity and that the pipeline architecture properties (pre-response emission, retention markers, distinct SUD events) hold across the suite.

Supported REQ_IDs: 1.4, 2.8, 3.5, 4.6, 5.4, 6.4

| Test Function | Layer | What Is Verified |
|---|---|---|
| test_audit_mandatory_fields_present_on_participant_write | Business Rules | Participant write produces audit row with all 11 Section 2.6.1 fields non-null |
| test_audit_mandatory_fields_present_on_mar_controlled_substance_read | Business Rules | Controlled-substance MARRecord read produces audit row with all mandatory fields before API response |
| test_audit_phi_values_absent_from_log_payloads_all_entities | DB | Direct query confirms no PHI field values appear in any audit row across all six entity tables |
| test_audit_access_denied_event_logged_for_every_403_response | Business Rules | Each PHI endpoint 403 response produces a corresponding ACCESS_DENIED audit event |
| test_audit_event_emitted_before_api_response_returns | Business Rules | Audit event timestamp precedes HTTP response timestamp for every write operation |
| test_audit_claim_submission_produces_phi_disclose_event | Business Rules | Clearinghouse submission generates PHI_DISCLOSE event with destination system and no raw PHI |
| test_audit_sud_related_incident_write_produces_separate_event | Business Rules | Write to is_sud_related=true Incident produces event distinct from non-SUD Incident write event |
| test_audit_claim_events_carry_10_year_retention_marker | DB | Audit rows for Claim operations carry 10-year retention marker; all other entities carry 6-year marker |
| test_audit_log_rows_contain_no_raw_phi_field_values | DB | Broad DB scan confirms no audit row contains SSN, DOB, medication_name, or other direct PHI field value |

### 3.2 test_rbac_sweep.py - Role Access Matrix (9 tests)

Security gate. Parametrized matrix confirming every role receives 200/201 on permitted endpoints and 403 on all others. Supplements the per-entity RBAC tests with a systematic cross-entity sweep.

Supported REQ_IDs: 1.2, 2.3, 3.2, 4.3, 5.2, 6.2

| Test Function | Layer | What Is Verified |
|---|---|---|
| test_rbac_program_administrator_write_permitted_on_attendance_and_claims | API | program_administrator POST/PATCH on Attendance and Claim endpoints returns 200/201 |
| test_rbac_care_coordinator_write_permitted_on_attendance_and_incidents | API | care_coordinator POST/PATCH on Attendance and Incident endpoints returns 200/201 |
| test_rbac_nurse_medication_aide_write_permitted_on_mar_record_only | API | nurse_medication_aide POST on MARRecord returns 201; POST on Claim returns 403 |
| test_rbac_billing_specialist_write_permitted_on_claims_only | API | billing_specialist POST/PATCH on Claim returns 200/201; POST on MARRecord returns 403 |
| test_rbac_physician_denied_all_entity_write_endpoints | API | physician POST or PATCH on any of the six entity endpoints returns 403 |
| test_rbac_participant_family_denied_all_staff_entity_endpoints | API | participant_family request to any of the six entity endpoints returns 403 |
| test_rbac_compliance_officer_read_permitted_all_entities | API | compliance_officer GET on all six entity endpoints returns 200 |
| test_rbac_inactive_user_denied_before_role_evaluation | API | inactive user receives 403 before role is checked; audit event records tenant_id, user_id, and outcome |
| test_rbac_suspended_user_denied_before_role_evaluation | API | suspended user receives 403 before role is checked; audit event records tenant_id, user_id, and outcome |

### 3.3 test_tenant_isolation.py - Multi-Tenant Isolation (7 tests)

Security gate. Verifies that no record belonging to tenant A is visible or writable by any user of tenant B, and that uniqueness constraints are correctly scoped per tenant rather than globally.

Supported REQ_IDs: 1.1, 2.1, 3.1, 4.1, 4.2, 5.1

| Test Function | Layer | What Is Verified |
|---|---|---|
| test_tenant_isolation_participant_not_accessible_from_other_tenant | API | GET Participant from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_user_token_rejected_on_other_tenant_endpoints | API | JWT issued for tenant A is rejected with 403 on all tenant B endpoints |
| test_tenant_isolation_attendance_not_accessible_from_other_tenant | API | GET Attendance from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_claim_not_accessible_from_other_tenant | API | GET Claim from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_mar_record_not_accessible_from_other_tenant | API | GET MARRecord from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_incident_not_accessible_from_other_tenant | API | GET Incident from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_unique_constraints_are_scoped_per_tenant | Business Rules | medicaid_id registered in tenant A is accepted in tenant B; email similarly accepted in a different tenant |

---

## 4. DB Layer - db/test_schema.py (8 tests)

Data integrity gate. Bypasses the application and asserts directly against the SQLite schema that every UNIQUE index, NOT NULL constraint, version column, and soft-delete default exists as defined in the architecture. Confirms the database is a backstop independent of application-layer enforcement.

| Test Function | Layer | What Is Verified |
|---|---|---|
| test_schema_participant_unique_index_tenant_medicaid_id | DB | UNIQUE index on (tenant_id, medicaid_id) present on participant table via PRAGMA index_list |
| test_schema_user_unique_indexes_and_primary_key | DB | UNIQUE index on (tenant_id, email) and PRIMARY KEY on user_id present on user table |
| test_schema_attendance_unique_index_tenant_participant_date | DB | UNIQUE index on (tenant_id, participant_id, date_of_service) present on attendance table |
| test_schema_claim_unique_indexes_reference_and_composite | DB | UNIQUE index on claim_reference_number and composite billing key both present on claim table |
| test_schema_mar_record_unique_index_participant_medication_time | DB | UNIQUE index on (tenant_id, participant_id, medication_name, scheduled_time) present on mar_record table |
| test_schema_not_null_constraints_on_all_mandatory_fields | DB | NOT NULL confirmed on all mandatory fields for all six entities via PRAGMA table_info |
| test_schema_version_column_present_on_all_entity_tables | DB | version column of INTEGER type exists on all six entity tables |
| test_schema_is_deleted_defaults_false_on_participant_and_user | DB | is_deleted column has DEFAULT false on participant and user tables; no row has null is_deleted |

---

## 5. Coverage Summary

### 5.1 REQ_ID Coverage

All 70 Phase 1 test cases have a dedicated test function. The table below shows the count per entity.

| Entity | TCs | Test Functions | Uncovered |
|---|---|---|---|
| Participant | TC-1.1 - TC-1.12 | 12 | 0 |
| User | TC-2.1 - TC-2.13 | 13 | 0 |
| Attendance | TC-3.1 - TC-3.12 | 12 | 0 |
| Claim | TC-4.1 - TC-4.15 | 15 | 0 |
| MARRecord | 5.1 - 5.10 | 10 | 0 |
| Incident | 6.1 - 6.8 | 8 | 0 |
| **Total** | **70** | **70** | **0** |

### 5.2 Test Layer Distribution

| Layer | Tests | Primary Use |
|---|---|---|
| API | 51 | Single-request status codes, error codes, response shape, field rejection |
| Business Rules | 43 | Multi-step flows, state machines, calculations, audit event verification |
| DB | 9 | Index presence, constraint existence, column defaults, schema assertions |
| **Total** | **103** | |

### 5.3 Gate Group to Test File Mapping

| Gate Group | Test File(s) | Test Count |
|---|---|---|
| Unique constraints | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py | 7 |
| RBAC enforcement | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py, test_rbac_sweep.py | 15 |
| 42 CFR Part 2 access gate | test_participant.py, test_mar_record.py, test_incident.py | 3 |
| Audit log completeness | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py, test_audit_log.py | 15 |
| State machine transitions | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_incident.py | 8 |
| Optimistic locking | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py | 6 |
| Tenant isolation | test_tenant_isolation.py, test_claim.py | 8 |
| Phase 2 field rejection | test_claim.py | 1 |
| Attendance integrity | test_claim.py | 3 |
| Mandatory fields | test_claim.py | 1 |
| Billing units server-calculated | test_claim.py | 1 |
| Not found | test_claim.py | 1 |
| Schema and constraints (DB backstop) | db/test_schema.py | 8 |

---
