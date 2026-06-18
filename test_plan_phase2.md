# Care Art - Test Plan: Phase 2

> **Status:** Phase 2 draft. Derived from test_strategy_phase2.md and requirements_phase1.xlsx (Phase 2 Requirements sheet). Each entity test function maps to exactly one REQ_ID. Cross-cutting test functions address concerns that span multiple entities or requirement types.
> **Regulatory scope:** HIPAA - 42 CFR Part 2 - CMS (Medicaid/Medicare) - HL7 FHIR R4 - NCPDP SCRIPT - State adult day care licensing

---

## 1. Overview

| Test File | Tests | REQ_IDs Covered | Layer(s) | Gate Group | Status |
|---|---|---|---|---|---|
| test_care_plan.py | 11 | TC-11.1 - TC-11.11 | API, Business Rules | Unique constraints, State machine, RBAC, 42 CFR Part 2, Audit log, Consent gate, Soft delete, Field validation | planned |
| test_appointment.py | 10 | TC-12.1 - TC-12.10 | API, Business Rules | Unique constraints, Physician overlap, State machine, Partial immutability, RBAC, 42 CFR Part 2, Audit log, Consent gate, Soft delete | planned |
| test_medication_refill.py | 11 | TC-13.1 - TC-13.11 | API, Business Rules | Unique constraints, In-flight uniqueness, State machine, Partial immutability, Field validation, RBAC, 42 CFR Part 2, Audit log, Consent gate, Soft delete | planned |
| test_reminder.py | 10 | TC-14.1 - TC-14.10 | API, Business Rules | Unique constraints, In-flight uniqueness, PHI-in-payload, Field validation, Immutability, RBAC, SUD delivery gate, Soft delete, Channel restriction | planned |
| test_consent.py | 10 | TC-15.1 - TC-15.10 | API, Business Rules | Active uniqueness, Date validation, Form reference, Immutability, Withdrawal, Expiration cron, Disclosure gate, RBAC, Audit log, Soft delete | planned |
| test_consent_gate.py | 11 | Cross-cutting | Business Rules | Consent gate integration (regulatory gate) | planned |
| test_audit_log_phase2.py | 10 | Cross-cutting | DB, Business Rules | Audit log completeness Phase 2 (regulatory gate) | planned |
| test_rbac_sweep_phase2.py | 10 | Cross-cutting | API | RBAC enforcement Phase 2 (security gate) | planned |
| test_tenant_isolation_phase2.py | 5 | Cross-cutting | API, Business Rules | Tenant isolation Phase 2 (security gate) | planned |
| db/test_schema_phase2.py | 10 | Cross-cutting | DB | Schema, constraint, and trigger assertions Phase 2 (data integrity gate) | planned |
| **Total** | **98** | **52 entity TCs** | | | |

---

## 2. Entity Test Files

### 2.1 test_care_plan.py - CarePlan (11 tests)

**Regulatory scope:** HIPAA §164.312(b) - 42 CFR Part 2 §2.13(b) (via Participant.is_sud_record) - 42 CFR Part 2 §2.31 (FHIR consent gate) - State adult day care licensing - CMS Medicaid/Medicare

**Gate groups:** Unique constraint (7.1) - Single active plan (7.2) - Physician signature gate (7.3) - Superseded immutability and revision workflow (7.4) - RBAC write (7.5) - 42 CFR Part 2 access gate (7.6) - Audit log SUD (7.7) - FHIR consent gate (7.8) - Goal duplicate (7.9) - Soft delete (7.10) - Effective date pre-activation (7.11)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_7_1_duplicate_version_number_returns_409 | TC-11.1 | API | POST with duplicate participant_id+version_number in same tenant returns 409 CARE_PLAN_DUPLICATE_VERSION; concurrent race results in one 201 and one 409; DB confirms exactly one row per version |
| test_tc_7_2_single_active_plan_supersession_in_transaction | TC-11.2 | Business Rules | PATCH activating a draft when another active plan exists without supersession returns 409 CARE_PLAN_ALREADY_ACTIVE; valid activation supersedes prior plan to superseded and sets new plan to active in single transaction; DB confirms both status values |
| test_tc_7_3_activation_requires_physician_signature_and_physician_id | TC-11.3 | Business Rules | PATCH activating a plan with null physician_signature_date returns 422 CARE_PLAN_UNSIGNED; PATCH activating with null physician_id returns 422 CARE_PLAN_UNSIGNED; plan with both set transitions to active; DB confirms status and physician fields |
| test_tc_7_4_superseded_plan_immutable_clinical_field_change_requires_revision | TC-11.4 | Business Rules | PATCH on superseded plan returns 422; PATCH changing primary_diagnosis_code on active plan without creating new version returns 422; PATCH updating only review_date or notes on active plan returns 200 with version incremented; DB confirms superseded plan fields unchanged |
| test_tc_7_5_rbac_care_coordinator_only_write_access | TC-11.5 | API | POST from billing_specialist, participant_family, or program_administrator returns 403; care_coordinator POST returns 201; nurse_medication_aide or compliance_officer GET returns 200; PATCH changing care_coordinator_id on active plan returns 422; all denials recorded in audit log |
| test_tc_7_6_sud_participant_care_plan_access_denied_for_unauthorized_roles | TC-11.6 | Business Rules | GET CarePlan where Participant.is_sud_record=true from billing_specialist or program_administrator returns 403 with no record details; list responses to unauthorized roles omit care_plan_goal rows and notes; is_sud_record flag absent from non-privileged responses |
| test_tc_7_7_audit_log_sud_care_plan_phi_read_write_access_denied | TC-11.7 | Business Rules | PHI_READ on SUD-flagged care plan produces audit event before response with all Section 2.6.1 mandatory fields; PHI_WRITE lists data_affected with field names only; ACCESS_DENIED logged for unauthorized attempts; no PHI values in audit rows; records retained minimum 6 years |
| test_tc_7_8_fhir_consent_gate_blocks_transmission_without_ehr_consent | TC-11.8 | Business Rules | FHIR CarePlan transmission for SUD participant with no active ehr consent is blocked; CONSENT_CHECK audit event emitted with outcome DENIED; with valid active ehr consent where effective_date <= today and expiration_date > today, transmission proceeds and CONSENT_CHECK emitted with outcome ALLOWED |
| test_tc_7_9_duplicate_goal_domain_description_returns_409 | TC-11.9 | API | POST care_plan_goal with same care_plan_id, domain, and description returns 409 CARE_PLAN_GOAL_DUPLICATE; same domain+description on different care_plan_id returns 201; DB confirms constraint scoped to care_plan_id |
| test_tc_7_10_soft_delete_sets_is_deleted_true_hard_delete_blocked | TC-11.10 | Business Rules | DELETE sets is_deleted=true and returns 200; subsequent GET by standard role returns 404; compliance_officer audit query returns record with is_deleted=true; no hard-delete permitted; goal rows inherit soft-delete policy |
| test_tc_7_11_activation_requires_non_null_effective_date | TC-11.11 | Business Rules | PATCH activating a plan with null effective_date returns 422 CARE_PLAN_MISSING_EFFECTIVE_DATE; plan with effective_date set and all physician fields populated transitions to active; PATCH setting effective_date on draft without activation returns 200 with version incremented |

### 2.2 test_appointment.py - Appointment (10 tests)

**Regulatory scope:** HIPAA §164.312(b) - 42 CFR Part 2 §2.13(b) (via Participant.is_sud_record) - 42 CFR Part 2 §2.31 (FHIR consent gate) - State adult day care licensing - HL7 FHIR R4

**Gate groups:** Duplicate constraint (8.1) - Physician overlap with trigger backstop (8.2) - Status state machine (8.3) - Completed partial immutability (8.4) - Cancellation reason (8.5) - RBAC (8.6) - 42 CFR Part 2 access gate (8.7) - Audit log SUD (8.8) - FHIR consent gate (8.9) - Soft delete (8.10)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_8_1_duplicate_participant_physician_scheduled_start_returns_409 | TC-12.1 | API | POST with duplicate participant_id+physician_id+scheduled_start in same tenant returns 409 APPOINTMENT_DUPLICATE; same participant+physician with different scheduled_start returns 201; DB confirms exactly one row per unique combination |
| test_tc_8_2_physician_overlap_rejected_boundary_permitted_trigger_backstop | TC-12.2 | Business Rules | POST where scheduled_start falls inside existing active appointment window returns 409 APPOINTMENT_PHYSICIAN_OVERLAP; POST where scheduled_start equals existing scheduled_end returns 201 (boundary); POST overlapping cancelled appointment returns 201; direct SQL INSERT bypassing application raises OperationalError 'overlapping appointment for this physician'; direct SQL UPDATE into overlap raises same error; PATCH scheduled_start into overlap returns 409; PATCH physician_id to overlapping physician returns 409; reschedule within own window returns 200 |
| test_tc_8_3_status_state_machine_terminal_states_irreversible | TC-12.3 | Business Rules | PATCH from scheduled to completed returns 200; PATCH from completed to scheduled returns 422; PATCH from cancelled to scheduled returns 422; PATCH from no_show to scheduled returns 422; DB confirms status after each transition |
| test_tc_8_4_completed_appointment_partial_immutability_mixed_body_rejected | TC-12.4 | Business Rules | PATCH including scheduled_start on completed appointment returns 422 APPOINTMENT_COMPLETED_IMMUTABLE; PATCH including only result_notes returns 200 with version incremented; PATCH body containing both result_notes and scheduled_start returns 422 (mixed body rejected in full); DB confirms version and fields after each attempt |
| test_tc_8_5_cancellation_requires_non_empty_cancellation_reason | TC-12.5 | Business Rules | PATCH status=cancelled with no cancellation_reason returns 422 APPOINTMENT_MISSING_CANCELLATION_REASON; with cancellation_reason="" returns 422; with whitespace-only returns 422; with non-empty cancellation_reason returns 200; DB confirms status=cancelled and cancellation_reason persisted |
| test_tc_8_6_rbac_nurse_sud_only_physician_read_billing_denied | TC-12.6 | API | POST from participant_family or billing_specialist returns 403; care_coordinator POST returns 201; physician GET returns 200; nurse_medication_aide GET on non-SUD appointment returns 403; nurse_medication_aide GET on SUD appointment returns 200; all denials recorded in audit log |
| test_tc_8_7_sud_participant_appointment_access_denied_for_unauthorized_roles | TC-12.7 | Business Rules | GET Appointment where Participant.is_sud_record=true from billing_specialist or program_administrator returns 403 with no record details; list responses to unauthorized roles omit appointment_type, cancellation_reason, result_notes, and follow_up_required for SUD-flagged records |
| test_tc_8_8_audit_log_sud_appointment_phi_read_write_access_denied | TC-12.8 | Business Rules | PHI_READ on SUD-flagged appointment produces audit event before response with all Section 2.6.1 mandatory fields; PHI_WRITE lists data_affected with field names only; ACCESS_DENIED logged for unauthorized attempts; no PHI values in audit rows; records retained minimum 6 years |
| test_tc_8_9_fhir_consent_gate_blocks_transmission_without_ehr_consent | TC-12.9 | Business Rules | FHIR Appointment transmission for SUD participant with no active ehr consent is blocked; CONSENT_CHECK emitted with outcome DENIED; with valid active ehr consent, transmission proceeds and CONSENT_CHECK emitted with outcome ALLOWED |
| test_tc_8_10_soft_delete_sets_is_deleted_true_hard_delete_blocked | TC-12.10 | Business Rules | DELETE sets is_deleted=true and returns 200; subsequent GET by standard role returns 404; compliance_officer audit query returns record with is_deleted=true; no hard-delete permitted at any application layer |

### 2.3 test_medication_refill.py - MedicationRefill (11 tests)

**Regulatory scope:** HIPAA §164.312(b) - 42 CFR Part 2 §2.13(b) (via is_controlled_substance) - 42 CFR Part 2 §2.31 (pharmacy consent gate) - HL7 FHIR R4 - NCPDP SCRIPT

**Gate groups:** Duplicate constraint (9.1) - In-flight uniqueness (9.2) - Quantity validation (9.3) - Status state machine (9.4) - Fulfilled partial immutability (9.5) - Denial and cancellation reason (9.6) - RBAC (9.7) - 42 CFR Part 2 controlled substance gate (9.8) - Audit log controlled substance (9.9) - Pharmacy consent gate (9.10) - Soft delete (9.11)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_9_1_duplicate_participant_medication_requested_at_returns_409 | TC-13.1 | API | POST with duplicate participant_id+medication_name+requested_at in same tenant returns 409 REFILL_DUPLICATE; same participant+medication with different requested_at returns 201; DB confirms exactly one row |
| test_tc_9_2_one_open_refill_per_medication_in_flight_uniqueness | TC-13.2 | Business Rules | POST for medication with open request (status requested/sent_to_pharmacy/processing) returns 409 REFILL_DUPLICATE_IN_FLIGHT; after prior request reaches fulfilled, new POST returns 201; after denied, returns 201; after cancelled, returns 201; DB confirms in-flight restriction lifts on terminal status |
| test_tc_9_3_quantity_requested_must_be_positive_integer | TC-13.3 | API | POST with quantity_requested=0 returns 422 REFILL_INVALID_QUANTITY; POST with quantity_requested=-1 returns 422; PATCH setting quantity_requested=0 returns 422; POST with valid positive integer returns 201; DB confirms field value on success |
| test_tc_9_4_status_state_machine_terminal_states_irreversible | TC-13.4 | Business Rules | PATCH from requested to sent_to_pharmacy returns 200; PATCH from fulfilled to processing returns 422; PATCH from cancelled to requested returns 422; PATCH from denied to any status returns 422; PATCH from processing to cancelled with non-empty cancellation_reason returns 200; DB confirms status after each transition |
| test_tc_9_5_fulfilled_refill_partial_immutability_mixed_body_rejected | TC-13.5 | Business Rules | PATCH including medication_name on fulfilled refill returns 422 REFILL_FULFILLED_IMMUTABLE; PATCH including only fulfilled_at returns 200 with version incremented; PATCH including only ncpdp_script_reference returns 200; PATCH body containing both ncpdp_script_reference and medication_name returns 422 (mixed body rejected); DB confirms version and fields after each attempt |
| test_tc_9_6_denied_requires_denial_reason_cancelled_requires_cancellation_reason | TC-13.6 | Business Rules | PATCH status=denied with no denial_reason returns 422 REFILL_MISSING_DENIAL_REASON; with denial_reason="" returns 422; with non-empty denial_reason returns 200; DB confirms denial_reason persisted; PATCH status=cancelled with no cancellation_reason returns 422 REFILL_MISSING_CANCELLATION_REASON; with non-empty cancellation_reason returns 200; DB confirms cancellation_reason persisted |
| test_tc_9_7_rbac_nurse_write_coordinator_controlled_only_billing_denied | TC-13.7 | API | POST from billing_specialist, physician, or participant_family returns 403; nurse_medication_aide POST returns 201; care_coordinator GET on non-controlled refill returns 403; care_coordinator GET on is_controlled_substance=true refill returns 200; compliance_officer GET returns 200; all denials recorded in audit log |
| test_tc_9_8_controlled_substance_access_denied_for_unauthorized_roles | TC-13.8 | Business Rules | GET MedicationRefill where is_controlled_substance=true from billing_specialist or program_administrator returns 403; list responses to unauthorized roles omit medication_name, dose, route, is_controlled_substance, denial_reason, and ncpdp_script_reference; is_controlled_substance flag absent from non-privileged responses |
| test_tc_9_9_audit_log_controlled_substance_phi_read_write_access_denied | TC-13.9 | Business Rules | PHI_READ on controlled substance refill produces audit event before response with all Section 2.6.1 mandatory fields; PHI_WRITE lists data_affected with field names only; ACCESS_DENIED logged for unauthorized attempts; no PHI values in audit rows; records retained minimum 6 years |
| test_tc_9_10_pharmacy_consent_gate_blocks_transmission_without_consent | TC-13.10 | Business Rules | FHIR MedicationRequest or NCPDP SCRIPT transmission for participant where is_controlled_substance=true and is_sud_record=true with no active pharmacy consent is blocked; CONSENT_CHECK emitted with outcome DENIED; expired pharmacy consent also blocks; with valid active pharmacy consent where effective_date <= today and expiration_date > today, transmission proceeds and CONSENT_CHECK emitted with outcome ALLOWED |
| test_tc_9_11_soft_delete_sets_is_deleted_true_hard_delete_blocked | TC-13.11 | Business Rules | DELETE sets is_deleted=true and returns 200; subsequent GET by standard role returns 404; compliance_officer audit query returns record with is_deleted=true; no hard-delete permitted at any application layer |

### 2.4 test_reminder.py - Reminder (10 tests)

**Regulatory scope:** HIPAA §164.514 (no PHI in payload) - 42 CFR Part 2 §2.31 (SUD delivery gate via Consent) - HIPAA §164.530(j) (record retention)

**Gate groups:** Duplicate constraint (10.1) - Scheduled uniqueness and transport rejection (10.2) - PHI-in-payload (10.3) - Scheduled-for future validation (10.4) - Sent immutability (10.5) - Cancellation reason (10.6) - RBAC (10.7) - SUD delivery gate (10.8) - Soft delete (10.9) - Channel restriction (10.10)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_10_1_duplicate_participant_type_scheduled_for_returns_409 | TC-14.1 | API | POST with duplicate participant_id+reminder_type+scheduled_for in same tenant returns 409 REMINDER_DUPLICATE; same participant+type with different scheduled_for returns 201; DB confirms exactly one row |
| test_tc_10_2_one_scheduled_reminder_per_type_transport_rejected | TC-14.2 | Business Rules | POST for reminder_type with existing scheduled reminder returns 409 REMINDER_DUPLICATE_SCHEDULED; after prior reminder transitions to sent, new POST returns 201; after cancelled with non-empty cancellation_reason, new POST returns 201; POST with reminder_type=transport returns 422 REMINDER_TRANSPORT_NOT_IMPLEMENTED; DB confirms in-flight restriction lifts on non-scheduled status |
| test_tc_10_3_phi_in_payload_rejected_name_diagnosis_medication | TC-14.3 | Business Rules | POST with participant full name in title returns 422 REMINDER_PHI_IN_PAYLOAD; POST with diagnosis code in body returns 422; POST with medication name in body returns 422; POST with generic PHI-free title and body returns 201; push notification adapter validates composed payload before APNs/FCM submission and emits PHI_PAYLOAD_BLOCKED audit event if pre-send check fails, holding status=scheduled and aborting delivery |
| test_tc_10_4_scheduled_for_must_be_strictly_future | TC-14.4 | API | POST with scheduled_for equal to current UTC returns 422 REMINDER_INVALID_SCHEDULED_FOR; POST with scheduled_for one hour in past returns 422; POST with scheduled_for one minute in future returns 201; DB confirms record created on success |
| test_tc_10_5_sent_reminder_immutable_failure_reason_writable_on_failed_only | TC-14.5 | Business Rules | PATCH on title with status=sent returns 422 REMINDER_SENT_IMMUTABLE; PATCH on scheduled_for with status=delivered returns 422; PATCH on failure_reason with status=delivered returns 422; PATCH on failure_reason with status=failed returns 200 with version incremented; PATCH body with both failure_reason and title on status=sent returns 422 (mixed body rejected); DB confirms fields and version after each attempt |
| test_tc_10_6_cancellation_requires_non_empty_cancellation_reason | TC-14.6 | Business Rules | PATCH status=cancelled with no cancellation_reason returns 422 REMINDER_MISSING_CANCELLATION_REASON; with cancellation_reason="" returns 422; with whitespace-only returns 422; with non-empty cancellation_reason returns 200; DB confirms status=cancelled and cancellation_reason persisted |
| test_tc_10_7_rbac_care_coordinator_write_participant_family_self_read_only | TC-14.7 | API | POST from participant_family or nurse_medication_aide returns 403; care_coordinator POST returns 201; GET from participant_family where recipient_user_id does not match requesting user_id returns 403; GET from participant_family where recipient_user_id matches returns 200; billing_specialist denied all access |
| test_tc_10_8_sud_delivery_gate_blocks_without_push_notification_consent | TC-14.8 | Business Rules | Delivery of reminder where Participant.is_sud_record=true and reference_entity_type=appointment with no active push_notification consent results in status remaining scheduled, delivery suppressed, and SUD_DELIVERY_GATE emitted with outcome SUPPRESSED; with valid active consent, delivery proceeds and SUD_DELIVERY_GATE emitted with outcome ALLOWED; when is_sud_record=false or reference_entity_type=none, gate does not apply |
| test_tc_10_9_soft_delete_sets_is_deleted_true_hard_delete_blocked | TC-14.9 | Business Rules | DELETE sets is_deleted=true and returns 200; subsequent GET by standard role returns 404; compliance_officer audit query returns record with is_deleted=true; no hard-delete permitted at any application layer |
| test_tc_10_10_channel_restricted_to_push_sms_email_rejected | TC-14.10 | API | POST with channel=sms returns 422 REMINDER_INVALID_CHANNEL; POST with channel=email returns 422 REMINDER_INVALID_CHANNEL; POST with channel=push returns 201; DB confirms channel=push on success |

### 2.5 test_consent.py - Consent (10 tests)

**Regulatory scope:** 42 CFR Part 2 §2.31 (written consent requirements) - 42 CFR Part 2 §2.31(a)(8) (expiration date) - 42 CFR Part 2 §2.31(c) (right to revoke) - 42 CFR Part 2 §2.16 (record retention) - HIPAA §164.530(j)

**Gate groups:** Active uniqueness (11.1) - Date validation (11.2) - Form reference (11.3) - Withdrawn/expired immutability (11.4) - Withdrawal right (11.5) - Expiration cron (11.6) - Disclosure gate 5-condition check (11.7) - RBAC (11.8) - Audit log lifecycle (11.9) - Soft delete and SUD retention (11.10)

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tc_11_1_one_active_consent_per_type_per_participant | TC-15.1 | Business Rules | POST second active consent of same disclosure_recipient_type for same participant returns 409 CONSENT_DUPLICATE_ACTIVE; after withdrawing prior consent, new POST returns 201; after expiration, new POST returns 201; multiple withdrawn/expired consents of same type permitted; DB confirms active uniqueness |
| test_tc_11_2_expiration_date_after_effective_date_and_after_current_date | TC-15.2 | API | POST with expiration_date equal to effective_date returns 422 CONSENT_INVALID_DATES; POST with expiration_date before effective_date returns 422; POST with expiration_date equal to today returns 422 CONSENT_EXPIRATION_IN_PAST; POST with expiration_date one year future and effective_date today returns 201; POST with past effective_date and future expiration_date returns 201 (late entry permitted); DB confirms field values on success |
| test_tc_11_3_consent_form_reference_required_non_empty | TC-15.3 | API | POST without consent_form_reference returns 422 CONSENT_MISSING_FORM_REFERENCE; POST with consent_form_reference="" returns 422; POST with whitespace-only returns 422; POST with non-empty consent_form_reference and all required fields returns 201; DB confirms field persisted |
| test_tc_11_4_withdrawn_expired_consent_fully_immutable | TC-15.4 | Business Rules | PATCH any field on consent with status=withdrawn returns 422 CONSENT_WITHDRAWN_IMMUTABLE; PATCH any field on consent with status=expired returns 422 CONSENT_WITHDRAWN_IMMUTABLE; after creating new consent of same type, new consent is active and old remains withdrawn and unmodified; DB confirms no modification on terminal records |
| test_tc_11_5_withdrawal_without_reason_accepted_blocks_future_disclosures | TC-15.5 | Business Rules | PATCH status=withdrawn without withdrawal_reason returns 200; DB confirms status=withdrawn and withdrawn_at non-null; PATCH status=withdrawn with non-empty withdrawal_reason returns 200; DB confirms withdrawal_reason persisted; subsequent disclosure gate queries return no qualifying record for that participant and disclosure_recipient_type |
| test_tc_11_6_expiration_cron_transitions_active_to_expired | TC-15.6 | Business Rules | After consent expiration_date passes, background cron transitions status to expired; subsequent disclosure gate query returns no qualifying record; CONSENT_EXPIRED audit event emitted with consent_id, participant_id, tenant_id, and date of expiration |
| test_tc_11_7_disclosure_gate_five_condition_check_at_disclosure_time | TC-15.7 | Business Rules | Disclosure where Participant.is_sud_record=false proceeds without consent check; disclosure where all five conditions met proceeds with audit event outcome ALLOWED including consent_id; disclosure where any condition fails (no matching record, wrong type, status not active, effective_date in future, expiration_date passed) is blocked with audit event outcome DENIED or SUPPRESSED |
| test_tc_11_8_rbac_care_coordinator_compliance_officer_only | TC-15.8 | API | POST from billing_specialist, nurse_medication_aide, or participant_family returns 403; care_coordinator POST returns 201; compliance_officer GET returns 200; compliance_officer PATCH to withdraw returns 200; all denials recorded in audit log |
| test_tc_11_9_audit_log_created_withdrawn_expired_gate_evaluation | TC-15.9 | Business Rules | Creating consent produces CONSENT_CREATED audit event with consent_id, participant_id, tenant_id, disclosure_recipient_type, effective_date, expiration_date, created_by and without scope_description; withdrawing produces CONSENT_WITHDRAWN with consent_id, withdrawn_at, updated_by; expiration produces CONSENT_EXPIRED; every disclosure gate evaluation logged with outcome ALLOWED or DENIED/SUPPRESSED regardless of result; all records immutable and retained per 42 CFR Part 2 §2.16 |
| test_tc_11_10_soft_delete_sets_is_deleted_true_sud_retention_enforced | TC-15.10 | Business Rules | DELETE sets is_deleted=true and returns 200; subsequent GET by standard role returns 404; compliance_officer audit query returns record with is_deleted=true; no hard-delete permitted at any application layer; withdrawn and expired consent records for SUD-flagged participants retained per 42 CFR Part 2 §2.16 |


---

## 3. Cross-Cutting Test Files

Cross-cutting tests verify controls that span multiple entities or that cannot be satisfied by a single entity test. They do not map to a single REQ_ID; the REQ_IDs column lists the requirements they collectively support.

### 3.1 test_consent_gate.py - Consent Gate Integration (11 tests)

Regulatory gate. Verifies that the consent gate mechanics operate correctly across all four referencing entities (CarePlan, Appointment, MedicationRefill, Reminder), testing both the blocking and permitting paths, consent expiration, withdrawal, and the non-SUD bypass.

Supported REQ_IDs: 7.8, 8.9, 9.10, 10.8, 11.7

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_cg_1_care_plan_fhir_blocked_without_ehr_consent | CG-1 | Business Rules | FHIR CarePlan transmission for SUD participant with no active ehr consent is blocked; CONSENT_CHECK emitted with outcome DENIED |
| test_cg_2_care_plan_fhir_permitted_with_valid_ehr_consent | CG-2 | Business Rules | FHIR CarePlan transmission for SUD participant with valid active ehr consent proceeds; CONSENT_CHECK emitted with outcome ALLOWED |
| test_cg_3_appointment_fhir_blocked_without_ehr_consent | CG-3 | Business Rules | FHIR Appointment transmission for SUD participant with no active ehr consent is blocked; CONSENT_CHECK emitted with outcome DENIED |
| test_cg_4_appointment_fhir_permitted_with_valid_ehr_consent | CG-4 | Business Rules | FHIR Appointment transmission for SUD participant with valid active ehr consent proceeds; CONSENT_CHECK emitted with outcome ALLOWED |
| test_cg_5_medication_refill_pharmacy_blocked_without_pharmacy_consent | CG-5 | Business Rules | FHIR MedicationRequest/NCPDP SCRIPT for controlled substance SUD participant with no active pharmacy consent is blocked; CONSENT_CHECK emitted with outcome DENIED |
| test_cg_6_medication_refill_pharmacy_permitted_with_valid_pharmacy_consent | CG-6 | Business Rules | Pharmacy transmission with valid active pharmacy consent proceeds; CONSENT_CHECK emitted with outcome ALLOWED |
| test_cg_7_reminder_push_blocked_without_push_notification_consent | CG-7 | Business Rules | Push delivery for SUD participant with reference_entity_type=appointment and no active push_notification consent is suppressed; status remains scheduled; SUD_DELIVERY_GATE emitted with outcome SUPPRESSED |
| test_cg_8_reminder_push_permitted_with_valid_push_notification_consent | CG-8 | Business Rules | Push delivery with valid active push_notification consent proceeds; SUD_DELIVERY_GATE emitted with outcome ALLOWED |
| test_cg_9_expired_consent_blocks_disclosure | CG-9 | Business Rules | Consent with expiration_date in past blocks disclosure; CONSENT_CHECK emitted with outcome DENIED |
| test_cg_10_withdrawn_consent_blocks_disclosure | CG-10 | Business Rules | Withdrawn consent blocks all subsequent disclosures of that type for that participant; CONSENT_CHECK emitted with outcome DENIED |
| test_cg_11_non_sud_participant_disclosure_proceeds_without_consent_check | CG-11 | Business Rules | Disclosure for participant where is_sud_record=false proceeds without a consent check; no CONSENT_CHECK audit event required |

### 3.2 test_audit_log_phase2.py - Audit Pipeline Completeness Phase 2 (10 tests)

Regulatory gate. Verifies that the audit pipeline receives complete, PHI-free events for every Phase 2 entity and that consent lifecycle events, SUD access events, and disclosure gate evaluations are logged correctly.

Supported REQ_IDs: 7.7, 8.8, 9.9, 11.9

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_audit_p2_1_care_plan_sud_phi_write_mandatory_fields | AP2-1 | Business Rules | CarePlan write for SUD participant produces PHI_WRITE audit event with all 11 Section 2.6.1 fields; data_affected lists field names only |
| test_audit_p2_2_care_plan_sud_phi_read_before_response | AP2-2 | Business Rules | CarePlan read for SUD participant produces PHI_READ audit event before response is returned |
| test_audit_p2_3_appointment_sud_access_denied_logged | AP2-3 | Business Rules | Unauthorized role read on SUD Appointment produces ACCESS_DENIED audit event with all mandatory fields |
| test_audit_p2_4_controlled_substance_refill_phi_read_before_response | AP2-4 | Business Rules | Controlled substance MedicationRefill read produces PHI_READ audit event before response |
| test_audit_p2_5_consent_created_event_excludes_scope_description | AP2-5 | DB | CONSENT_CREATED audit event includes consent_id, participant_id, tenant_id, disclosure_recipient_type, effective_date, expiration_date, created_by; scope_description absent |
| test_audit_p2_6_consent_withdrawn_event_mandatory_fields | AP2-6 | Business Rules | CONSENT_WITHDRAWN event includes consent_id, participant_id, tenant_id, disclosure_recipient_type, withdrawn_at, updated_by |
| test_audit_p2_7_consent_expired_event_mandatory_fields | AP2-7 | Business Rules | CONSENT_EXPIRED event includes consent_id, participant_id, tenant_id, and date of expiration |
| test_audit_p2_8_disclosure_gate_allowed_includes_consent_id | AP2-8 | Business Rules | Disclosure gate evaluation with outcome ALLOWED includes consent_id of matching record, disclosure_recipient_type, and service identity |
| test_audit_p2_9_disclosure_gate_denied_logged_regardless | AP2-9 | Business Rules | Disclosure gate evaluation with outcome DENIED is logged regardless of failure reason |
| test_audit_p2_10_no_phi_values_in_phase2_audit_rows | AP2-10 | DB | Direct DB query confirms no PHI field values appear in any audit row for Phase 2 entity operations |

### 3.3 test_rbac_sweep_phase2.py - Phase 2 Role Access Matrix (10 tests)

Security gate. Parametrized matrix confirming every role receives the correct access on Phase 2 entity endpoints, including the conditional access rules (nurse SUD-only on Appointment, care_coordinator controlled-only on MedicationRefill, participant_family self-only on Reminder).

Supported REQ_IDs: 7.5, 8.6, 9.7, 10.7, 11.8

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_rbac_p2_1_care_coordinator_write_on_care_plan_and_appointment | RP2-1 | API | care_coordinator POST on CarePlan and Appointment returns 201 |
| test_rbac_p2_2_nurse_write_on_medication_refill_only | RP2-2 | API | nurse_medication_aide POST on MedicationRefill returns 201; POST on CarePlan returns 403 |
| test_rbac_p2_3_nurse_read_appointment_sud_only | RP2-3 | API | nurse_medication_aide GET on non-SUD Appointment returns 403; GET on SUD Appointment returns 200 |
| test_rbac_p2_4_coordinator_read_refill_controlled_only | RP2-4 | API | care_coordinator GET on non-controlled MedicationRefill returns 403; GET on controlled returns 200 |
| test_rbac_p2_5_billing_specialist_denied_all_phase2_entities | RP2-5 | API | billing_specialist POST/GET on all five Phase 2 entity endpoints returns 403 |
| test_rbac_p2_6_physician_read_appointment_only | RP2-6 | API | physician GET on Appointment returns 200; POST on Appointment returns 403; GET on CarePlan returns 200; POST on CarePlan returns 403 |
| test_rbac_p2_7_participant_family_denied_write_all_phase2 | RP2-7 | API | participant_family POST on all five Phase 2 entity endpoints returns 403 |
| test_rbac_p2_8_participant_family_reminder_self_read_only | RP2-8 | API | participant_family GET on Reminder where recipient_user_id matches returns 200; where it does not match returns 403 |
| test_rbac_p2_9_compliance_officer_read_all_phase2_entities | RP2-9 | API | compliance_officer GET on all five Phase 2 entity endpoints returns 200 |
| test_rbac_p2_10_consent_write_restricted_to_coordinator_and_compliance | RP2-10 | API | care_coordinator and compliance_officer POST/PATCH on Consent returns 200/201; nurse_medication_aide POST returns 403; program_administrator POST returns 403 |

### 3.4 test_tenant_isolation_phase2.py - Phase 2 Multi-Tenant Isolation (5 tests)

Security gate. Verifies that no Phase 2 record belonging to tenant A is visible or writable by any user of tenant B.

Supported REQ_IDs: 7.1, 8.1, 9.1, 10.1, 11.1

| Test Function | TC | Layer | What Is Verified |
|---|---|---|---|
| test_tenant_isolation_care_plan_not_accessible_from_other_tenant | TI-P2-1 | API | GET CarePlan from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_appointment_not_accessible_from_other_tenant | TI-P2-2 | API | GET Appointment from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_medication_refill_not_accessible_from_other_tenant | TI-P2-3 | API | GET MedicationRefill from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_reminder_not_accessible_from_other_tenant | TI-P2-4 | API | GET Reminder from tenant-B user returns 404 for a record belonging to tenant A |
| test_tenant_isolation_consent_not_accessible_from_other_tenant | TI-P2-5 | API | GET Consent from tenant-B user returns 404 for a record belonging to tenant A |

---

## 4. DB Layer - db/test_schema_phase2.py (10 tests)

Data integrity gate. Bypasses the application and asserts directly against the SQLite schema that every UNIQUE index, partial unique index, SQLite trigger, NOT NULL constraint, version column, and soft-delete default exists as defined in the architecture for all five Phase 2 entities and care_plan_goal.

| Test Function | Layer | What Is Verified |
|---|---|---|
| test_schema_care_plan_unique_index_tenant_participant_version | DB | UNIQUE index on (tenant_id, participant_id, version_number) present on care_plan table |
| test_schema_care_plan_partial_unique_active_per_participant | DB | Partial unique index on (tenant_id, participant_id) WHERE status='active' present on care_plan table |
| test_schema_care_plan_goal_unique_index_domain_description | DB | UNIQUE index on (tenant_id, care_plan_id, domain, description) present on care_plan_goal table |
| test_schema_appointment_unique_index_and_overlap_triggers | DB | UNIQUE index on (tenant_id, participant_id, physician_id, scheduled_start) present; triggers trg_appointment_physician_no_overlap_insert and trg_appointment_physician_no_overlap_update exist in sqlite_master with correct SQL |
| test_schema_medication_refill_unique_and_partial_indexes | DB | UNIQUE index on (tenant_id, participant_id, medication_name, requested_at) present; partial unique index WHERE status NOT IN ('fulfilled','denied','cancelled') present |
| test_schema_reminder_unique_and_partial_indexes | DB | UNIQUE index on (tenant_id, participant_id, reminder_type, scheduled_for) present; partial unique index WHERE status='scheduled' present |
| test_schema_consent_partial_unique_active_per_type | DB | Partial unique index on (tenant_id, participant_id, disclosure_recipient_type) WHERE status='active' present on consent table |
| test_schema_not_null_constraints_phase2_mandatory_fields | DB | NOT NULL confirmed on all mandatory fields for all five Phase 2 entities and care_plan_goal via PRAGMA table_info |
| test_schema_version_column_present_on_phase2_tables | DB | version column of INTEGER type exists on all five Phase 2 entity tables and care_plan_goal |
| test_schema_is_deleted_defaults_false_on_all_phase2_entities | DB | is_deleted column has DEFAULT false on all five Phase 2 entity tables; no row has null is_deleted |

---

## 5. Coverage Summary

### 5.1 REQ_ID Coverage

All 52 Phase 2 test cases have a dedicated test function. The table below shows the count per entity.

| Entity | TCs | Test Functions | Uncovered |
|---|---|---|---|
| CarePlan | TC-11.1 - TC-11.11 | 11 | 0 |
| Appointment | TC-12.1 - TC-12.10 | 10 | 0 |
| MedicationRefill | TC-13.1 - TC-13.11 | 11 | 0 |
| Reminder | TC-14.1 - TC-14.10 | 10 | 0 |
| Consent | TC-15.1 - TC-15.10 | 10 | 0 |
| **Total** | **52** | **52** | **0** |

### 5.2 Test Layer Distribution

| Layer | Tests | Primary Use |
|---|---|---|
| API | 36 | Single-request status codes, error codes, response shape, field rejection, RBAC sweep |
| Business Rules | 52 | Multi-step flows, state machines, consent gates, immutability, audit event verification, disclosure gates |
| DB | 10 | Index presence, trigger presence, constraint existence, column defaults, schema assertions |
| **Total** | **98** | |

98 tests planned, 0 written.

### 5.3 Gate Group to Test File Mapping

| Gate Group | Test File(s) | Test Count | Notes |
|---|---|---|---|
| Unique constraints | test_care_plan.py, test_appointment.py, test_medication_refill.py, test_reminder.py, test_consent.py | 6 | REQ_7.1, REQ_8.1, REQ_9.1, REQ_10.1, REQ_11.1 |
| Partial index constraints | test_care_plan.py, test_medication_refill.py, test_reminder.py, test_consent.py | 4 | REQ_7.2, REQ_9.2, REQ_10.2, REQ_11.1 |
| Physician overlap (application + triggers) | test_appointment.py, db/test_schema_phase2.py | 2 | REQ_8.2 |
| Goal duplicate | test_care_plan.py | 1 | REQ_7.9 |
| RBAC enforcement | test_care_plan.py, test_appointment.py, test_medication_refill.py, test_reminder.py, test_consent.py, test_rbac_sweep_phase2.py | 15 | REQ_7.5, REQ_8.6, REQ_9.7, REQ_10.7, REQ_11.8 |
| 42 CFR Part 2 access gate | test_care_plan.py, test_appointment.py, test_medication_refill.py | 3 | REQ_7.6, REQ_8.7, REQ_9.8 |
| Audit log completeness | test_care_plan.py, test_appointment.py, test_medication_refill.py, test_consent.py, test_audit_log_phase2.py | 14 | REQ_7.7, REQ_8.8, REQ_9.9, REQ_11.9 |
| Consent gate integration | test_care_plan.py, test_appointment.py, test_medication_refill.py, test_reminder.py, test_consent.py, test_consent_gate.py | 16 | REQ_7.8, REQ_8.9, REQ_9.10, REQ_10.8, REQ_11.6, REQ_11.7 |
| State machine transitions | test_care_plan.py, test_appointment.py, test_medication_refill.py, test_consent.py | 8 | REQ_7.2, REQ_7.3, REQ_8.3, REQ_9.4, REQ_11.4, REQ_11.5 |
| Soft delete | test_care_plan.py, test_appointment.py, test_medication_refill.py, test_reminder.py, test_consent.py | 5 | REQ_7.10, REQ_8.10, REQ_9.11, REQ_10.9, REQ_11.10 |
| Partial immutability | test_appointment.py, test_medication_refill.py, test_reminder.py | 3 | REQ_8.4, REQ_9.5, REQ_10.5 |
| Full immutability | test_care_plan.py, test_consent.py | 2 | REQ_7.4, REQ_11.4 |
| PHI-in-payload rejection | test_reminder.py | 1 | REQ_10.3 |
| Cancellation/denial reason enforcement | test_appointment.py, test_medication_refill.py, test_reminder.py | 3 | REQ_8.5, REQ_9.6, REQ_10.6 |
| Field validation | test_care_plan.py, test_medication_refill.py, test_reminder.py, test_consent.py | 5 | REQ_7.11, REQ_9.3, REQ_10.4, REQ_10.10, REQ_11.2, REQ_11.3 |
| Tenant isolation | test_tenant_isolation_phase2.py | 5 | Cross-entity |
| Schema and constraints (DB backstop) | db/test_schema_phase2.py | 10 | Cross-entity |

---

## 6. CI Gate

### 6.1 Gate Design

The CI gate is a set of test groups that must all pass before a Phase 2 release artifact is produced. Gate failures block the build. Non-gate tests produce coverage reports but do not block release. All Phase 1 gate tests remain blocking - no Phase 2 change may cause a Phase 1 gate failure.

### 6.2 Blocking Gate Groups

| Gate Group | Test Type | Rationale |
|---|---|---|
| Unique constraints - all five entities + care_plan_goal | Data Integrity | Duplicate care plans, overlapping appointments, duplicate refill transmissions, duplicate reminders, duplicate active consents |
| Partial index constraints - CarePlan, MedicationRefill, Reminder, Consent | Data Integrity | Single-active-plan, one open refill, one scheduled reminder, one active consent per type |
| Physician overlap - Appointment (application + SQLite triggers) | Data Integrity | Double-booked physician - application layer and database trigger backstop |
| RBAC enforcement - all entities, all roles | Security | Unauthorized PHI access is a HIPAA breach |
| 42 CFR Part 2 access gate - CarePlan, Appointment, MedicationRefill | Regulatory | Prohibited SUD disclosure carries criminal penalties |
| Audit log completeness - all SUD/controlled substance operations and consent lifecycle | Regulatory | HIPAA §164.312(b) - SOC 2 CC7.2 - 42 CFR Part 2 §2.16 - non-bypassable control |
| State machine transitions - all five entities | Functional | Invalid clinical artifacts, terminal state reversal, consent lifecycle bypass |
| Consent gate - CarePlan FHIR, Appointment FHIR, MedicationRefill pharmacy, Reminder push | Regulatory | 42 CFR Part 2 §2.31 - disclosure without consent |
| Consent disclosure gate (5-condition check) | Regulatory | All five conditions checked simultaneously at disclosure time |
| Soft delete - all five entities | Regulatory | HIPAA record retention - 42 CFR Part 2 §2.16 SUD consent retention |
| Partial immutability - Appointment completed, MedicationRefill fulfilled, Reminder sent | Functional | Clinical record integrity after completion/fulfillment/delivery |
| Full immutability - CarePlan superseded/archived, Consent withdrawn/expired | Functional | Historical records must not be modified |
| PHI-in-payload rejection - Reminder | Functional | HIPAA minimum necessary - no PHI in push notification payloads |
| Cancellation/denial reason enforcement | Functional | Appointment cancellation, MedicationRefill denial and cancellation, Reminder cancellation |
| Field validation - effective_date, expiration_date, quantity_requested, channel, scheduled_for | Functional | Pre-activation constraints, consent date validation, positive quantity, push-only channel, future delivery time |
| Consent form reference | Functional | 42 CFR Part 2 §2.31 written consent documentation requirement |
| Tenant isolation - Phase 2 entities | Security | Cross-tenant PHI access is a multi-party HIPAA breach |

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

Line coverage of the mock backend routes and service layer must reach 80% before release, inclusive of both Phase 1 and Phase 2 code paths. Coverage is measured by pytest-cov and reported in CI but does not independently block release - gate group failures are the primary release control. A release that meets 80% coverage but fails a gate group is still blocked.

---
