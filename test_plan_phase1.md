# Care Art - Test Plan: Phase 1

> **Status:** Phase 1 draft. Derived from test_strategy_phase1.md and requirements_phase1.xlsx. Each entity test function maps to exactly one REQ_ID. Cross-cutting test functions address concerns that span multiple entities or requirement types.
> **Regulatory scope:** HIPAA - 42 CFR Part 2 - CMS (Medicaid/Medicare) - State adult day care licensing

---

## 1. Overview

| Test File | Tests | REQ_IDs Covered | Layer(s) | Gate Group |
|---|---|---|---|---|
| test_participant.py | 10 | 1.1 - 1.10 | API, Business Rules | Unique constraints, RBAC, 42 CFR Part 2, State machine, Optimistic locking |
| test_user.py | 12 | 2.1 - 2.12 | API, DB, Business Rules | Unique constraints, RBAC, State machine, Optimistic locking |
| test_attendance.py | 8 | 3.1 - 3.8 | API, Business Rules | Unique constraints, RBAC, State machine, Optimistic locking |
| test_claim.py | 9 | 4.1 - 4.9 | API, Business Rules | Unique constraints, RBAC, State machine, Optimistic locking |
| test_mar_record.py | 10 | 5.1 - 5.10 | API, Business Rules | Unique constraints, RBAC, 42 CFR Part 2, Optimistic locking |
| test_incident.py | 8 | 6.1 - 6.8 | API, Business Rules | Unique constraints, RBAC, 42 CFR Part 2, State machine, Optimistic locking |
| test_audit_log.py | 9 | Cross-cutting | DB, Business Rules | Audit log completeness (regulatory gate) |
| test_rbac_sweep.py | 9 | Cross-cutting | API | RBAC enforcement (security gate) |
| test_tenant_isolation.py | 7 | Cross-cutting | API, Business Rules | Tenant isolation (security gate) |
| db/test_schema.py | 8 | Cross-cutting | DB | Schema and constraint assertions (data integrity gate) |
| **Total** | **90** | **57 entity REQ_IDs** | | |

---

## 2. Entity Test Files

### 2.1 test_participant.py - Participant (10 tests)

| Test Function | REQ_ID | Layer | What Is Verified |
|---|---|---|---|
| test_1_1_unique_medicaid_id_per_tenant | 1.1 | API | POST with duplicate medicaid_id in same tenant returns 409 and PARTICIPANT_DUPLICATE_MEDICAID_ID |
| test_1_2_rbac_write_restricted_to_staff_roles | 1.2 | API | POST or PATCH from physician or participant_family role returns 403; authorized staff roles succeed |
| test_1_3_42cfr_part2_sud_record_access_gate | 1.3 | API | GET on is_sud_record=true Participant from non-privileged role returns 403 with no record disclosure |
| test_1_4_audit_log_on_phi_read_and_write | 1.4 | Business Rules | Participant write produces audit event with all Section 2.6.1 fields non-null and no PHI values in payload |
| test_1_5_program_status_state_machine_transitions | 1.5 | Business Rules | Disallowed program_status transition returns 422; each allowed transition returns 200 with updated status |
| test_1_6_enrollment_date_required_and_discharge_date_auto_set | 1.6 | Business Rules | POST without enrollment_date returns 400; PATCH to discharged auto-populates discharge_date if not supplied |
| test_1_7_mandatory_fields_on_participant_creation | 1.7 | API | POST missing any mandatory field returns 400 identifying the absent field by name |
| test_1_8_soft_delete_no_hard_delete | 1.8 | API | DELETE returns 200 and sets is_deleted=true; physical row removal attempt returns 405 |
| test_1_9_is_deleted_excluded_from_standard_queries | 1.9 | API | GET /participants list excludes is_deleted=true records; compliance_officer audit endpoint returns them |
| test_1_10_optimistic_locking_version_conflict_returns_409 | 1.10 | Business Rules | PATCH with stale version returns 409 PARTICIPANT_VERSION_CONFLICT; correct version returns 200 with version n+1 |

### 2.2 test_user.py - User (12 tests)

| Test Function | REQ_ID | Layer | What Is Verified |
|---|---|---|---|
| test_2_1_unique_email_per_tenant | 2.1 | API | POST with email already in same tenant returns 409 USER_DUPLICATE_EMAIL; same email in other tenant returns 201 |
| test_2_2_unique_user_id_globally | 2.2 | DB | UNIQUE index on user_id confirmed via PRAGMA; no two rows share user_id across tenants |
| test_2_3_rbac_evaluation_order_tenant_status_role | 2.3 | Business Rules | Inactive user returns 403 before role is checked; mismatched tenant_id returns 403 before role is checked |
| test_2_4_mfa_required_for_phi_accessing_roles | 2.4 | API | PHI module request from user with mfa_enabled=false returns 403 with MFA enrollment redirect |
| test_2_5_account_locked_after_five_failed_logins | 2.5 | Business Rules | Fifth failed login sets locked_until; valid login within window returns 401; post-expiry valid login returns 200 |
| test_2_6_lockout_state_persists_in_database | 2.6 | Business Rules | locked_until persisted in DB; login while locked_until is future returns 401; response omits locked_until value |
| test_2_7_user_status_state_machine_transitions | 2.7 | Business Rules | Disallowed status transition returns 422; DELETE returns 405; transition to inactive sets deactivated_at |
| test_2_8_audit_log_on_auth_events_and_user_changes | 2.8 | Business Rules | Login produces AUTH_SUCCESS or AUTH_FAILURE event; User role change produces PHI_WRITE listing field names only |
| test_2_9_password_stored_as_hash_never_plaintext | 2.9 | DB | password_hash column contains only bcrypt/Argon2id pattern; no plaintext string present in any row or audit log |
| test_2_10_90_day_password_rotation_and_reuse_prevention | 2.10 | Business Rules | Login with password age > 90 days returns 403 PASSWORD_EXPIRED; prior hash reuse returns 422 PASSWORD_REUSE_PROHIBITED |
| test_2_11_dormant_account_auto_deactivated_after_90_days | 2.11 | Business Rules | Job query identifies accounts with last_login_at > 90 days; each transitions to inactive with ACCOUNT_AUTO_DEACTIVATED audit event |
| test_2_12_optimistic_locking_version_conflict_returns_409 | 2.12 | Business Rules | PATCH with stale version returns 409 USER_VERSION_CONFLICT; correct version returns 200 with version n+1 |

### 2.3 test_attendance.py - Attendance (8 tests)

| Test Function | REQ_ID | Layer | What Is Verified |
|---|---|---|---|
| test_3_1_unique_attendance_per_participant_per_date | 3.1 | API | POST second Attendance for same participant_id and date_of_service in same tenant returns 409 ATTENDANCE_DUPLICATE_DATE |
| test_3_2_rbac_write_restricted_to_program_administrator_and_care_coordinator | 3.2 | API | POST or PATCH from billing_specialist, physician, or participant_family returns 403; authorized roles succeed |
| test_3_3_attendance_status_state_machine_transitions | 3.3 | Business Rules | Edit to confirmed record resets status to pending; pending Attendance referenced in Claim returns 422 |
| test_3_4_void_reason_required_when_status_is_voided | 3.4 | API | PATCH to voided without void_reason returns 422 Unprocessable Entity; with void_reason returns 200 |
| test_3_5_audit_log_on_attendance_write_operations | 3.5 | Business Rules | Any Attendance write produces audit event with all mandatory fields; data_affected lists field names only |
| test_3_6_authorized_units_consumed_derived_from_total_hours | 3.6 | Business Rules | Medicaid sign-out of 6 h sets authorized_units_consumed=24; Medicare daily-rate sign-out sets value=1.00 |
| test_3_7_void_blocked_when_referencing_claim_is_active | 3.7 | Business Rules | Void on billed Attendance with active Claim returns 422; void attempt by care_coordinator returns 403 |
| test_3_8_optimistic_locking_version_conflict_returns_409 | 3.8 | Business Rules | PATCH with stale version returns 409 ATTENDANCE_VERSION_CONFLICT; correct version returns 200 with version n+1 |

### 2.4 test_claim.py - Claim (9 tests)

| Test Function | REQ_ID | Layer | What Is Verified |
|---|---|---|---|
| test_4_1_unique_claim_reference_number_globally | 4.1 | API | POST with manually supplied duplicate claim_reference_number returns 409 CLAIM_DUPLICATE_REFERENCE |
| test_4_2_composite_unique_key_prevents_duplicate_billing | 4.2 | API | POST with duplicate participant_id+date_of_service_start+procedure_code+payer_type returns 409 CLAIM_DUPLICATE |
| test_4_3_rbac_write_restricted_to_billing_specialist_and_program_administrator | 4.3 | API | POST or PATCH from care_coordinator, nurse_medication_aide, physician, or participant_family returns 403 |
| test_4_4_claim_status_state_machine_transitions | 4.4 | Business Rules | PATCH any field on submitted or paid Claim returns 422; valid draft-to-submitted transition returns 200 |
| test_4_5_claim_requires_confirmed_attendance_records | 4.5 | Business Rules | POST referencing pending or voided attendance returns 422; confirmed attendance returns 201 and sets attendance to billed |
| test_4_6_audit_log_on_claim_creation_and_submission | 4.6 | Business Rules | Claim write produces audit event with all mandatory fields; clearinghouse submission produces PHI_DISCLOSE event |
| test_4_7_claim_generated_from_attendance_units_not_blank | 4.7 | API | POST with empty attendance_ids returns 422 CLAIM_NO_ATTENDANCE_RECORDS; caller-supplied units_billed is overridden by calculated sum |
| test_4_8_phase2_deferred_fields_rejected_with_400 | 4.8 | API | POST with secondary_payer_id or any Phase 2 deferred field returns 400 identifying the unsupported field name |
| test_4_9_optimistic_locking_version_conflict_returns_409 | 4.9 | Business Rules | PATCH draft with stale version returns 409 CLAIM_VERSION_CONFLICT; PATCH submitted returns 422 before version check |

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

All 57 Phase 1 requirements have a dedicated test function. The table below shows the count per entity.

| Entity | REQ_IDs | Test Functions | Uncovered |
|---|---|---|---|
| Participant | 1.1 - 1.10 | 10 | 0 |
| User | 2.1 - 2.12 | 12 | 0 |
| Attendance | 3.1 - 3.8 | 8 | 0 |
| Claim | 4.1 - 4.9 | 9 | 0 |
| MARRecord | 5.1 - 5.10 | 10 | 0 |
| Incident | 6.1 - 6.8 | 8 | 0 |
| **Total** | **57** | **57** | **0** |

### 5.2 Test Layer Distribution

| Layer | Tests | Primary Use |
|---|---|---|
| API | 35 | Single-request status codes, error codes, response shape, field rejection |
| Business Rules | 44 | Multi-step flows, state machines, calculations, audit event verification |
| DB | 11 | Index presence, constraint existence, column defaults, schema assertions |
| **Total** | **90** | |

### 5.3 Gate Group to Test File Mapping

| Gate Group | Test File(s) | Test Count |
|---|---|---|
| Unique constraints | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py | 7 |
| RBAC enforcement | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py, test_rbac_sweep.py | 15 |
| 42 CFR Part 2 access gate | test_participant.py, test_mar_record.py, test_incident.py | 3 |
| Audit log completeness | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py, test_audit_log.py | 15 |
| State machine transitions | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_incident.py | 6 |
| Optimistic locking | test_participant.py, test_user.py, test_attendance.py, test_claim.py, test_mar_record.py, test_incident.py | 6 |
| Tenant isolation | test_tenant_isolation.py | 7 |
| Phase 2 field rejection | test_claim.py | 1 |
| Schema and constraints (DB backstop) | db/test_schema.py | 8 |

---
