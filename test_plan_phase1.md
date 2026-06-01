# Care Art - Test Plan: Phase 1

> **Status:** Phase 1 draft. Derived from test_strategy_phase1.md and requirements_phase1.xlsx. Each entity test function maps to exactly one REQ_ID. Cross-cutting test functions address concerns that span multiple entities or requirement types.
> **Regulatory scope:** HIPAA - 42 CFR Part 2 - CMS (Medicaid/Medicare) - State adult day care licensing

---

## 1. Overview

| Test File | Tests | REQ_IDs Covered | Layer(s) | Gate Group | Status |
|---|---|---|---|---|---|
| test_participant.py | 12 | TC-1.1 - TC-1.12 | API, Business Rules | Unique constraints, RBAC, 42 CFR Part 2, State machine, Soft delete, Mandatory fields | written |
| test_user.py | 15 | TC-2.1 - TC-2.15 | API, Business Rules | Unique constraints, RBAC, Auth, Account lockout, State machine, Audit log, Mandatory fields | written |
| test_attendance.py | 12 | TC-3.1 - TC-3.12 | API, Business Rules | Unique constraints, RBAC, State machine, Billing units, Audit log, Billed immutability | written |
| test_claim.py | 15 | TC-4.1 - TC-4.15 | API, Business Rules | Unique constraints, RBAC, State machine, Attendance integrity, Mandatory fields, Audit log, Billing units server-calculated, Phase 2 field rejection, Optimistic locking, Tenant isolation, Not found | written |
| test_mar_record.py | 21 | TC-5.1 - TC-5.21 | API, Business Rules | Duplicate event, RBAC write, Controlled substance access gate 42 CFR Part 2, Status field rules, Administered time bounds, Immutability, State transitions, Correction record, Optimistic locking | written |
| test_incident.py | 15 | TC-6.1 - TC-6.15 | API, Business Rules | Creation and audit, RBAC, SUD access gate 42 CFR Part 2, Auto-escalation, Escalation alert job, Addendum, Closed immutability, Regulatory submission gate, Optimistic locking | written |
| test_audit_log.py | 10 | TC-7.1 - TC-7.10 | DB, Business Rules | Audit log completeness (regulatory gate) | planned |
| test_rbac_sweep.py | 12 | TC-8.1 - TC-8.12 | API | RBAC enforcement (security gate) | planned |
| test_tenant_isolation.py | 7 | Cross-cutting | API, Business Rules | Tenant isolation (security gate) | planned |
| db/test_schema.py | 8 | Cross-cutting | DB | Schema and constraint assertions (data integrity gate) | written |
| **Total** | **123** | **90 entity TCs** | | | |

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

### 2.2 test_user.py - User (15 tests)

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
| test_tc_2_14_inactive_user_denied_before_role_evaluation | TC-2.14 | API | inactive user receives 403 before role is checked; DB confirms audit event records tenant_id user_id and outcome |
| test_tc_2_15_suspended_user_denied_before_role_evaluation | TC-2.15 | API | suspended user receives 403 before role is checked; DB confirms audit event records tenant_id user_id and outcome |

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

### 2.5 test_mar_record.py - MARRecord (21 tests)

**Regulatory scope:** HIPAA §164.312(a)(2)(iv) · 42 CFR Part 2 §2.13(b) (controlled substance access gate)

**Gate groups:** Duplicate event (5.1) · RBAC write (5.2, 5.3, 5.13) · Controlled substance access gate 42 CFR Part 2 (5.4, 5.6) · Status field rules (5.5, 5.7, 5.8) · Administered time bounds (5.9, 5.10, 5.11, 5.12) · Immutability (5.14, 5.15) · State transitions (5.16, 5.20) · Correction record (5.17, 5.18, 5.19) · Optimistic locking (5.21)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_5_1_duplicate_mar_event_returns_409 | TC-5.1 | API | POST with duplicate participant_id+medication_name+scheduled_time in same tenant returns 409 MAR_DUPLICATE_EVENT; DB confirms exactly one row |
| test_tc_5_2_successful_mar_creation_audit_trail | TC-5.2 | Business Rules | POST by nurse_medication_aide returns 201; DB confirms created_by and tenant_id; PHI_WRITE audit event has all 11 mandatory fields |
| test_tc_5_3_billing_specialist_cannot_create_mar | TC-5.3 | API | POST by billing_specialist returns 403 RBAC_DENIED; DB confirms no row created |
| test_tc_5_4_controlled_substance_read_denied_for_non_privileged_role | TC-5.4 | API | GET controlled-substance MARRecord by non-privileged role returns 403 SUD_ACCESS_DENIED; ACCESS_DENIED audit event logged |
| test_tc_5_5_administered_status_requires_administered_time | TC-5.5 | API | POST with status=administered and null administered_time returns 422 MAR_MISSING_ADMINISTERED_TIME; DB confirms no row created |
| test_tc_5_6_controlled_substance_read_allowed_for_privileged_role | TC-5.6 | Business Rules | GET controlled-substance MARRecord by nurse_medication_aide returns 200; PHI_READ audit event logged with all 11 mandatory fields |
| test_tc_5_7_refused_status_requires_notes | TC-5.7 | API | POST with status=refused and null notes returns 422 MAR_MISSING_NOTES; DB confirms no row created |
| test_tc_5_8_held_status_requires_notes | TC-5.8 | API | POST with status=held and null notes returns 422 MAR_MISSING_NOTES; DB confirms no row created |
| test_tc_5_9_future_administered_time_rejected | TC-5.9 | API | POST with administered_time in the future returns 422 ADMIN_TIME_FUTURE; DB confirms no row created |
| test_tc_5_10_administered_time_too_early_rejected | TC-5.10 | API | POST with administered_time more than 2 hours before scheduled_time returns 422 ADMIN_TIME_TOO_EARLY; DB confirms no row created |
| test_tc_5_11_administered_by_must_be_nurse_role | TC-5.11 | API | POST with administered_by referencing a non-nurse-role user returns 403; DB confirms no row created |
| test_tc_5_12_administered_by_user_not_found_rejected | TC-5.12 | API | POST with administered_by referencing a non-existent user_id returns 403 or 422; DB confirms no row created |
| test_tc_5_13_coordinator_cannot_create_mar | TC-5.13 | API | POST by care_coordinator returns 403 RBAC_DENIED; DB confirms no row created |
| test_tc_5_14_administered_mar_is_immutable | TC-5.14 | Business Rules | PATCH on MARRecord with status=administered returns 422 MAR_ADMINISTERED_IMMUTABLE for any field change; DB confirms version unchanged |
| test_tc_5_15_administered_mar_immutable_check_fires_before_version_check | TC-5.15 | Business Rules | PATCH with stale version on administered MAR returns 422 MAR_ADMINISTERED_IMMUTABLE not 409; immutability check fires before version check |
| test_tc_5_16_patch_notes_on_missed_mar_succeeds | TC-5.16 | Business Rules | PATCH notes on missed MAR returns 200; DB confirms notes updated and version incremented |
| test_tc_5_17_correction_mar_requires_original_mar_id | TC-5.17 | API | Correction POST without original_mar_id returns 422 MAR_CORRECTION_MISSING_ORIGINAL; DB confirms no correction row created |
| test_tc_5_18_correction_mar_requires_notes_min_20_chars | TC-5.18 | API | Correction POST with notes shorter than 20 characters returns 422 MAR_CORRECTION_NOTES_TOO_SHORT; DB confirms no correction row created |
| test_tc_5_19_correction_mar_with_valid_fields_succeeds | TC-5.19 | Business Rules | Correction POST with valid original_mar_id and notes >= 20 chars returns 201; DB confirms is_correction=True and original_mar_id set |
| test_tc_5_20_patch_missed_mar_status_transition_succeeds | TC-5.20 | Business Rules | PATCH status from missed to held returns 200; DB confirms status changed and version incremented |
| test_tc_5_21_stale_version_on_missed_mar_returns_version_conflict | TC-5.21 | Business Rules | PATCH with stale version on missed MAR returns 409 MAR_VERSION_CONFLICT; DB confirms version unchanged |

### 2.6 test_incident.py - Incident (15 tests)

**Regulatory scope:** HIPAA §164.308 · 42 CFR Part 2 §2.13(b) (SUD incident access gate) · State adult day care licensing (24-hour incident reporting)

**Gate groups:** Creation and audit (6.1, 6.2) · RBAC (6.3, 6.4) · SUD access gate 42 CFR Part 2 (6.5, 6.7) · Auto-escalation (6.6, 6.9) · Escalation alert job (6.10) · Addendum (6.11) · Closed immutability (6.8, 6.12, 6.15) · Regulatory submission gate (6.13) · Optimistic locking (6.14)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_6_1_successful_incident_creation_audit_trail | TC-6.1 | Business Rules | POST /incidents by program_administrator returns 201 with status=draft; PHI_WRITE audit event logged with all 11 mandatory fields |
| test_tc_6_2_admin_and_coordinator_can_create_incident | TC-6.2 | API | POST by program_administrator and care_coordinator each returns 201; DB confirms correct created_by for each |
| test_tc_6_3_physician_cannot_create_incident | TC-6.3 | API | POST by physician returns 403 RBAC_DENIED; DB confirms no incident row created |
| test_tc_6_4_physician_cannot_read_any_incident | TC-6.4 | API | GET /incidents/<id> by physician returns 403 RBAC_DENIED regardless of SUD status; ACCESS_DENIED audit event logged |
| test_tc_6_5_billing_specialist_read_sud_incident_denied_with_audit | TC-6.5 | Business Rules | GET is_sud_related=true Incident by billing_specialist returns 403 SUD_ACCESS_DENIED; ACCESS_DENIED audit event logged with all 11 mandatory fields |
| test_tc_6_6_medical_emergency_incident_auto_escalates | TC-6.6 | Business Rules | POST with incident_type=medical_emergency returns 201 with status=escalated; DB confirms auto-escalation |
| test_tc_6_7_coordinator_can_read_sud_incident | TC-6.7 | Business Rules | GET is_sud_related=true Incident by care_coordinator returns 200; PHI_READ audit event logged with all 11 mandatory fields |
| test_tc_6_8_closed_incident_is_immutable | TC-6.8 | Business Rules | PATCH on closed Incident returns 422 INCIDENT_CLOSED_IMMUTABLE; DB confirms all fields unchanged |
| test_tc_6_9_severe_incident_auto_escalates | TC-6.9 | Business Rules | POST with severity=severe returns 201 with status=escalated; DB confirms status=escalated and severity=severe |
| test_tc_6_10_escalation_alert_job_emits_escalation_alert_audit | TC-6.10 | Business Rules | GET /jobs/escalated-incidents-alert returns incident with created_at <= (now - 20h) and null regulatory_submission_date; ESCALATION_ALERT audit event logged |
| test_tc_6_11_addendum_incident_links_to_original_incident | TC-6.11 | API | POST addendum incident with original_incident_id returns 201; DB confirms incident_type=addendum and original_incident_id set |
| test_tc_6_12_closed_incident_immutable_check_fires_before_version_check | TC-6.12 | Business Rules | PATCH with stale version on closed Incident returns 422 INCIDENT_CLOSED_IMMUTABLE not 409; immutability check fires before version check |
| test_tc_6_13_escalated_to_closed_requires_regulatory_submission_date | TC-6.13 | Business Rules | PATCH status=closed on escalated Incident without regulatory_submission_date returns 422 INCIDENT_MISSING_REGULATORY_SUBMISSION; DB status unchanged |
| test_tc_6_14_stale_version_on_incident_returns_version_conflict | TC-6.14 | Business Rules | PATCH with stale version on open Incident returns 409 INCIDENT_VERSION_CONFLICT; DB confirms version unchanged |
| test_tc_6_15_closed_incident_patch_any_field_returns_immutable | TC-6.15 | Business Rules | PATCH any field on closed Incident with correct version returns 422 INCIDENT_CLOSED_IMMUTABLE; DB confirms all fields unchanged |


---

## 3. Cross-Cutting Test Files

Cross-cutting tests verify controls that span multiple entities or that cannot be satisfied by a single entity test. They do not map to a single REQ_ID; the REQ_IDs column lists the requirements they collectively support.

### 3.1 test_audit_log.py - Audit Pipeline Completeness (10 tests)

Regulatory gate. Verifies that the audit pipeline receives complete, PHI-free events for every entity and that the pipeline architecture properties (pre-response emission, retention markers, distinct SUD events) hold across the suite.

Supported REQ_IDs: 1.4, 2.8, 3.5, 4.6, 5.4, 6.4

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_7_1_audit_mandatory_fields_present_on_participant_write | TC-7.1 | Business Rules | Participant write produces audit row with all 11 Section 2.6.1 fields non-null |
| test_tc_7_2_unauthorized_role_denied_write_phi_resource_access_denied_audit_logged | TC-7.2 | Business Rules | Unauthorized role denied write to PHI-protected resource; ACCESS_DENIED audit event logged with all mandatory fields |
| test_tc_7_3_audit_mandatory_fields_present_on_mar_controlled_substance_read | TC-7.3 | Business Rules | Controlled-substance MARRecord read produces audit row with all mandatory fields before API response |
| test_tc_7_4_phi_values_absent_from_audit_log_payloads_across_all_entities | TC-7.4 | DB | Direct query confirms no PHI field values appear in any audit row across all six entity tables |
| test_tc_7_5_access_denied_audit_event_logged_for_every_403_response | TC-7.5 | Business Rules | Each PHI endpoint 403 response produces a corresponding ACCESS_DENIED audit event |
| test_tc_7_6_audit_row_exists_in_db_after_api_call_completes | TC-7.6 | Business Rules | DB query confirms audit row exists in audit_log table after API call completes |
| test_tc_7_7_claim_submission_produces_phi_disclose_audit_event | TC-7.7 | Business Rules | Claim submission generates PHI_DISCLOSE event with destination system and no raw PHI |
| test_tc_7_8_sud_related_incident_write_produces_separate_audit_event | TC-7.8 | Business Rules | Write to is_sud_related=true Incident produces event distinct from non-SUD Incident write event |
| test_tc_7_9_claim_audit_events_carry_10_year_retention_marker | TC-7.9 | DB | Audit rows for Claim operations carry 10-year retention marker; all other entities carry 6-year marker |
| test_tc_7_10_audit_log_rows_contain_no_raw_phi_field_values | TC-7.10 | DB | Broad DB scan confirms no audit row contains SSN, DOB, medication_name, or other direct PHI field value |

### 3.2 test_rbac_sweep.py - Role Access Matrix (12 tests)

Security gate. Parametrized matrix confirming every role receives 200/201 on permitted endpoints and 403 on all others. Supplements the per-entity RBAC tests with a systematic cross-entity sweep.

Supported REQ_IDs: 1.2, 2.3, 3.2, 4.3, 5.2, 6.2

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_8_1_program_administrator_write_permitted_on_attendance_and_claims | TC-8.1 | API | program_administrator POST/PATCH on Attendance and Claim endpoints returns 200/201 |
| test_tc_8_2_care_coordinator_write_permitted_on_attendance_and_incidents | TC-8.2 | API | care_coordinator POST/PATCH on Attendance and Incident endpoints returns 200/201 |
| test_tc_8_3_nurse_medication_aide_write_permitted_on_mar_record_only | TC-8.3 | API | nurse_medication_aide POST on MARRecord returns 201; POST on Claim returns 403 |
| test_tc_8_4_billing_specialist_write_permitted_on_claims_only | TC-8.4 | API | billing_specialist POST/PATCH on Claim returns 200/201; POST on MARRecord returns 403 |
| test_tc_8_5_physician_denied_write_on_participant_endpoint | TC-8.5 | API | physician POST on Participant endpoint returns 403 RBAC_DENIED; DB confirms no row created |
| test_tc_8_6_physician_denied_write_on_user_endpoint | TC-8.6 | API | physician POST on User endpoint returns 403 RBAC_DENIED; DB confirms no row created |
| test_tc_8_7_physician_denied_write_on_attendance_endpoint | TC-8.7 | API | physician POST on Attendance endpoint returns 403 RBAC_DENIED; DB confirms no row created |
| test_tc_8_8_physician_denied_write_on_claim_endpoint | TC-8.8 | API | physician POST on Claim endpoint returns 403 RBAC_DENIED; DB confirms no row created |
| test_tc_8_9_physician_denied_write_on_mar_record_endpoint | TC-8.9 | API | physician POST on MARRecord endpoint returns 403 RBAC_DENIED; DB confirms no row created |
| test_tc_8_10_physician_denied_write_on_incident_endpoint | TC-8.10 | API | physician POST on Incident endpoint returns 403 RBAC_DENIED; DB confirms no row created |
| test_tc_8_11_participant_family_denied_all_staff_entity_endpoints | TC-8.11 | API | participant_family request to any of the six entity endpoints returns 403; DB confirms no row created in any table |
| test_tc_8_12_compliance_officer_read_permitted_on_all_entities | TC-8.12 | API | compliance_officer GET on all six entity endpoints returns 200 |

### 3.3 test_tenant_isolation.py - Multi-Tenant Isolation (7 tests)

Security gate. Verifies that no record belonging to tenant A is visible or writable by any user of tenant B, and that uniqueness constraints are correctly scoped per tenant rather than globally.

Supported REQ_IDs: 1.1, 2.1, 3.1, 4.1, 4.2, 5.1

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tenant_isolation_participant_not_accessible_from_other_tenant | TC-9.1 | API | GET Participant from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_user_token_rejected_on_other_tenant_endpoints | TC-9.2 | API | JWT issued for tenant A is rejected with 403 on all tenant B endpoints |
| test_tenant_isolation_attendance_not_accessible_from_other_tenant | TC-9.3 | API | GET Attendance from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_claim_not_accessible_from_other_tenant | TC-9.4 | API | GET Claim from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_mar_record_not_accessible_from_other_tenant | TC-9.5 | API | GET MARRecord from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_incident_not_accessible_from_other_tenant | TC-9.6 | API | GET Incident from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_unique_constraints_are_scoped_per_tenant | TC-9.7 | Business Rules | medicaid_id registered in tenant A is accepted in tenant B; email similarly accepted in a different tenant |

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

All 90 Phase 1 test cases have a dedicated test function. The table below shows the count per entity.

| Entity | TCs | Test Functions | Uncovered |
|---|---|---|---|
| Participant | TC-1.1 - TC-1.12 | 12 | 0 |
| User | TC-2.1 - TC-2.15 | 15 | 0 |
| Attendance | TC-3.1 - TC-3.12 | 12 | 0 |
| Claim | TC-4.1 - TC-4.15 | 15 | 0 |
| MARRecord | TC-5.1 - TC-5.21 | 21 | 0 |
| Incident | TC-6.1 - TC-6.15 | 15 | 0 |
| **Total** | **90** | **90** | **0** |

### 5.2 Test Layer Distribution

| Layer | Tests | Primary Use |
|---|---|---|
| API | 60 | Single-request status codes, error codes, response shape, field rejection |
| Business Rules | 52 | Multi-step flows, state machines, calculations, audit event verification |
| DB | 9 | Index presence, constraint existence, column defaults, schema assertions |
| **Total** | **123** | |

94 tests written, 29 planned (test_audit_log.py 10, test_rbac_sweep.py 12, test_tenant_isolation.py 7).

### 5.3 Gate Group to Test File Mapping

| Gate Group | Test File(s) | Test Count | Notes |
|---|---|---|---|
| Unique constraints | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py | 7 | - |
| RBAC enforcement | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py, test_rbac_sweep.py | 15 | test_rbac_sweep.py planned, not yet written |
| 42 CFR Part 2 access gate | test_participant.py, test_mar_record.py, test_incident.py | 3 | - |
| Audit log completeness | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py, test_audit_log.py | 15 | - |
| State machine transitions | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_incident.py | 8 | - |
| Optimistic locking | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py | 6 | - |
| Tenant isolation | test_tenant_isolation.py, test_claim.py | 8 | test_tenant_isolation.py planned, not yet written |
| Phase 2 field rejection | test_claim.py | 1 | - |
| Attendance integrity | test_claim.py | 3 | - |
| Mandatory fields | test_claim.py | 1 | - |
| Billing units server-calculated | test_claim.py | 1 | - |
| Not found | test_claim.py | 1 | - |
| Schema and constraints (DB backstop) | db/test_schema.py | 8 | - |

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
| Attendance integrity - Claim | Functional | Confirmed-only attendance gate prevents erroneous billing artifacts |
| Mandatory fields - Claim | Functional | Minimum required fields enforced on Claim creation |
| Billing units server-calculated - Claim | Functional | Server-calculated units_billed prevents billing manipulation |
| Not found handling - Claim | Functional | Non-existent resource returns 404 with structured error body |

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

### 6.5 P1 Gate Test Functions

The following 26 test functions plus db/test_schema.py (all 8 tests) run in the GitHub Actions P1 gate job on every push and pull request to main. The list matches ci.yml exactly.

| Test File | Test Function | TC |
|---|---|---|
| tests/test_participant.py | test_tc_1_1_positive_participant_creation_by_program_administrator | TC-1.1 |
| tests/test_participant.py | test_tc_1_4_duplicate_medicaid_id_returns_409 | TC-1.4 |
| tests/test_participant.py | test_tc_1_5_sud_record_billing_specialist_returns_403_no_disclosure | TC-1.5 |
| tests/test_participant.py | test_tc_1_9_soft_delete_returns_200_is_deleted_true | TC-1.9 |
| tests/test_user.py | test_tc_2_1_positive_user_creation_by_program_administrator | TC-2.1 |
| tests/test_user.py | test_tc_2_2_user_creation_by_unauthorized_role_returns_403 | TC-2.2 |
| tests/test_user.py | test_tc_2_4_login_wrong_password_returns_401_no_credential_disclosure | TC-2.4 |
| tests/test_user.py | test_tc_2_7_account_lockout_after_5_failed_logins | TC-2.7 |
| tests/test_attendance.py | test_tc_3_1_positive_attendance_creation_by_program_administrator | TC-3.1 |
| tests/test_attendance.py | test_tc_3_5_duplicate_participant_date_returns_409 | TC-3.5 |
| tests/test_attendance.py | test_tc_3_2_positive_attendance_creation_by_care_coordinator | TC-3.2 |
| tests/test_claim.py | test_tc_4_1_duplicate_claim_reference_returns_409 | TC-4.1 |
| tests/test_claim.py | test_tc_4_2_composite_duplicate_returns_409_claim_duplicate | TC-4.2 |
| tests/test_claim.py | test_tc_4_3_unauthorized_roles_post_claims_returns_403 | TC-4.3 |
| tests/test_claim.py | test_tc_4_5_attendance_status_validation_and_confirmed_creates_claim | TC-4.5 |
| tests/test_claim.py | test_tc_4_8_phi_write_and_phi_disclose_audit_events_in_db | TC-4.8 |
| tests/test_mar_record.py | test_tc_5_1_duplicate_mar_event_returns_409 | TC-5.1 |
| tests/test_mar_record.py | test_tc_5_2_successful_mar_creation_audit_trail | TC-5.2 |
| tests/test_mar_record.py | test_tc_5_3_billing_specialist_cannot_create_mar | TC-5.3 |
| tests/test_mar_record.py | test_tc_5_4_controlled_substance_read_denied_for_non_privileged_role | TC-5.4 |
| tests/test_mar_record.py | test_tc_5_5_administered_status_requires_administered_time | TC-5.5 |
| tests/test_incident.py | test_tc_6_1_successful_incident_creation_audit_trail | TC-6.1 |
| tests/test_incident.py | test_tc_6_2_admin_and_coordinator_can_create_incident | TC-6.2 |
| tests/test_incident.py | test_tc_6_3_physician_cannot_create_incident | TC-6.3 |
| tests/test_incident.py | test_tc_6_5_billing_specialist_read_sud_incident_denied_with_audit | TC-6.5 |
| tests/test_incident.py | test_tc_6_8_closed_incident_is_immutable | TC-6.8 |
| db/test_schema.py | (all 8 tests) | - |
