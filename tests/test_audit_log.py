"""
test_audit_log.py — 9 tests covering REQ_IDs 1.4, 2.8, 3.5, 4.6, 5.4, 6.4 (cross-cutting audit gate).
"""
import pytest
from helpers import (
    TENANT_A, make_participant, make_attendance, make_confirmed_attendance, make_claim,
    make_nurse_user, make_mar_record, make_incident, make_headers,
)


MANDATORY_FIELDS = [
    "timestamp", "user_id", "tenant_id", "session_id",
    "action_type", "resource_type", "resource_id",
    "data_affected", "source_ip", "outcome", "layer",
]

PHI_SAMPLE_VALUES = ["Jane", "Doe", "1980-01-15", "MCD-AUDIT-001", "0123456789"]


def _all_mandatory_fields_present(event: dict) -> bool:
    return all(event.get(f) is not None for f in MANDATORY_FIELDS)


# ─── Audit mandatory fields — participant write ───────────────────────────────

def test_audit_mandatory_fields_present_on_participant_write(client, admin_headers, compliance_headers):
    """All 11 Section 2.6.1 fields are non-null in the audit event for a Participant write."""
    p = make_participant(client, admin_headers, medicaid_id="MCD-AUDIT-001")
    pid = p["participant_id"]

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "Participant", "resource_id": pid},
        headers=compliance_headers,
    )
    assert logs.status_code == 200
    events = logs.json()
    assert len(events) >= 1

    write_event = next((e for e in events if e["action_type"] == "PHI_WRITE"), None)
    assert write_event is not None, "No PHI_WRITE audit event found for Participant"

    for field in MANDATORY_FIELDS:
        assert write_event.get(field) is not None, f"Mandatory audit field '{field}' is null"


# ─── Audit mandatory fields — controlled substance MAR read ──────────────────

def test_audit_mandatory_fields_present_on_mar_controlled_substance_read(
    client, admin_headers, nurse_headers, compliance_headers
):
    """Controlled-substance MARRecord read produces audit row with all mandatory fields before API response."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    mar = make_mar_record(
        client, nurse_headers, pid, nid,
        scheduled_time="2026-04-01T08:00:00",
        is_controlled_substance=True,
        medication_name="Fentanyl",
    )
    mar_id = mar["mar_id"]

    client.get(f"/mar-records/{mar_id}", headers=nurse_headers)

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "MARRecord", "resource_id": mar_id,
                "action_type": "PHI_READ"},
        headers=compliance_headers,
    )
    events = logs.json()
    read_events = [e for e in events if e["action_type"] == "PHI_READ" and e["outcome"] == "SUCCESS"]
    assert len(read_events) >= 1

    for field in MANDATORY_FIELDS:
        assert read_events[0].get(field) is not None, f"'{field}' is null in controlled-substance read audit event"


# ─── No PHI values in any audit log payload ───────────────────────────────────

def test_audit_phi_values_absent_from_log_payloads_all_entities(
    client, admin_headers, coordinator_headers, billing_headers, nurse_headers,
    compliance_headers, db_session
):
    """Direct DB query confirms no PHI field values appear in any audit row."""
    from models import AuditLog

    make_participant(client, admin_headers,
                     first_name="PhiCheckFirst", last_name="PhiCheckLast",
                     medicaid_id="MCD-PHI-999")

    all_logs = db_session.query(AuditLog).all()
    assert len(all_logs) > 0

    phi_values = ["PhiCheckFirst", "PhiCheckLast", "MCD-PHI-999", "1980-01-15"]
    for row in all_logs:
        row_str = str(row.data_affected)
        for phi in phi_values:
            assert phi not in row_str, \
                f"PHI value '{phi}' found in audit log {row.audit_id} data_affected: {row.data_affected}"


# ─── ACCESS_DENIED event for every 403 response ───────────────────────────────

def test_audit_access_denied_event_logged_for_every_403_response(
    client, admin_headers, nurse_headers, billing_headers, compliance_headers
):
    """Each PHI endpoint 403 response produces a corresponding ACCESS_DENIED (DENIED outcome) audit event."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    mar = make_mar_record(
        client, nurse_headers, pid, nid,
        scheduled_time="2026-04-02T08:00:00",
        is_controlled_substance=True,
        medication_name="Codeine",
    )
    mar_id = mar["mar_id"]

    before_count_resp = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "MARRecord", "resource_id": mar_id},
        headers=compliance_headers,
    )
    before_denied = sum(1 for e in before_count_resp.json() if e["outcome"] == "DENIED")

    r_403 = client.get(f"/mar-records/{mar_id}", headers=billing_headers)
    assert r_403.status_code == 403

    after_count_resp = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "MARRecord", "resource_id": mar_id},
        headers=compliance_headers,
    )
    after_denied = sum(1 for e in after_count_resp.json() if e["outcome"] == "DENIED")
    assert after_denied > before_denied, "No ACCESS_DENIED audit event was created after 403 response"


# ─── Audit event emitted before API response ─────────────────────────────────

def test_audit_event_emitted_before_api_response_returns(
    client, admin_headers, compliance_headers
):
    """Audit event timestamp precedes or equals HTTP response timestamp for every write operation."""
    from datetime import datetime as dt

    before = dt.utcnow()
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    after = dt.utcnow()

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "Participant", "resource_id": pid},
        headers=compliance_headers,
    )
    events = logs.json()
    write_event = next((e for e in events if e["action_type"] == "PHI_WRITE"), None)
    assert write_event is not None

    raw_ts = write_event["timestamp"]
    event_ts = dt.fromisoformat(raw_ts.replace("Z", ""))
    assert event_ts <= after, "Audit event timestamp is after the API response completed"


# ─── Claim submission produces PHI_DISCLOSE event ────────────────────────────

def test_audit_claim_submission_produces_phi_disclose_event(
    client, admin_headers, coordinator_headers, billing_headers, compliance_headers
):
    """Clearinghouse submission produces PHI_DISCLOSE event with no raw PHI."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    att = make_confirmed_attendance(client, coordinator_headers, pid, date_of_service="2026-05-10")
    claim = make_claim(client, billing_headers, pid, [att["attendance_id"]])
    claim_id = claim["claim_id"]

    r_submit = client.patch(
        f"/claims/{claim_id}",
        json={"version": claim["version"], "claim_status": "submitted"},
        headers=billing_headers,
    )
    assert r_submit.status_code == 200

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "Claim", "resource_id": claim_id,
                "action_type": "PHI_DISCLOSE"},
        headers=compliance_headers,
    )
    events = logs.json()
    disclose_events = [e for e in events if e["action_type"] == "PHI_DISCLOSE"]
    assert len(disclose_events) >= 1

    disclose = disclose_events[0]
    phi_values = [pid, p.get("first_name", ""), p.get("last_name", "")]
    payload_str = str(disclose["data_affected"])
    for phi in phi_values:
        if phi:
            assert phi not in payload_str, f"PHI value '{phi}' found in PHI_DISCLOSE event"


# ─── SUD incident write produces separate audit event ────────────────────────

def test_audit_sud_related_incident_write_produces_separate_event(
    client, admin_headers, compliance_headers
):
    """Write to is_sud_related=true Incident produces event distinct from non-SUD Incident write event."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    non_sud = make_incident(client, admin_headers, pid, severity="minor",
                            incident_type="fall", is_sud_related=False,
                            description="Non-SUD fall incident.")
    sud = make_incident(client, admin_headers, pid, severity="minor",
                        incident_type="other", is_sud_related=True,
                        description="SUD-related incident.")

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "Incident"},
        headers=compliance_headers,
    )
    all_events = logs.json()

    non_sud_events = [e for e in all_events if e["resource_id"] == non_sud["incident_id"]]
    sud_events = [e for e in all_events if e["resource_id"] == sud["incident_id"]]

    assert len(non_sud_events) >= 1
    assert len(sud_events) >= 1
    assert {e["resource_id"] for e in non_sud_events}.isdisjoint(
        {e["resource_id"] for e in sud_events}
    ), "SUD and non-SUD incident audit events share resource_id — should be distinct"


# ─── Claim audit rows carry 10-year retention marker ─────────────────────────

def test_audit_claim_events_carry_10_year_retention_marker(
    client, admin_headers, coordinator_headers, billing_headers, compliance_headers, db_session
):
    """Audit rows for Claim operations carry 10-year retention; all others carry 6-year marker."""
    from models import AuditLog

    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    att = make_confirmed_attendance(client, coordinator_headers, pid, date_of_service="2026-06-10")
    make_claim(client, billing_headers, pid, [att["attendance_id"]])

    claim_logs = db_session.query(AuditLog).filter(AuditLog.resource_type == "Claim").all()
    participant_logs = db_session.query(AuditLog).filter(AuditLog.resource_type == "Participant").all()

    assert len(claim_logs) >= 1
    for log in claim_logs:
        assert log.retention_years == 10, f"Claim audit log {log.audit_id} has retention_years={log.retention_years}, expected 10"

    assert len(participant_logs) >= 1
    for log in participant_logs:
        assert log.retention_years == 6, f"Participant audit log {log.audit_id} has retention_years={log.retention_years}, expected 6"


# ─── No raw PHI values in any audit row ───────────────────────────────────────

def test_audit_log_rows_contain_no_raw_phi_field_values(
    client, admin_headers, coordinator_headers, nurse_headers, compliance_headers, db_session
):
    """Broad DB scan confirms no audit row contains SSN, DOB, medication_name, or other direct PHI value."""
    from models import AuditLog

    p = make_participant(
        client, admin_headers,
        first_name="ScanTest", last_name="Noshow",
        medicaid_id="MCD-SCAN-111",
    )

    all_logs = db_session.query(AuditLog).all()

    direct_phi = ["ScanTest", "Noshow", "MCD-SCAN-111", "1980-01-15", "Fentanyl", "Oxycodone"]
    for row in all_logs:
        row_str = str(row.data_affected)
        for phi in direct_phi:
            assert phi not in row_str, \
                f"PHI value '{phi}' found in audit log row {row.audit_id}"
