"""
test_incident.py — 8 tests covering REQ_IDs 6.1–6.8.
"""
from datetime import datetime, timedelta

import pytest
from helpers import TENANT_A, make_participant, make_incident, make_headers


# ─── 6.1 incident_id is sole unique constraint — no composite key ─────────────

def test_6_1_incident_id_is_sole_unique_constraint_no_composite_key(client, admin_headers):
    """REQ 6.1 — two POSTs for same participant+date+type both return 201 with distinct incident_ids."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    inc1 = make_incident(client, admin_headers, pid, incident_date="2026-03-15",
                         incident_type="fall", severity="minor")
    inc2 = make_incident(client, admin_headers, pid, incident_date="2026-03-15",
                         incident_type="fall", severity="minor")

    assert inc1["incident_id"] != inc2["incident_id"]


# ─── 6.2 RBAC — staff can create, external roles denied ──────────────────────

def test_6_2_rbac_staff_can_create_external_roles_denied(
    client, admin_headers, coordinator_headers, nurse_headers, billing_headers,
    physician_headers, family_headers
):
    """REQ 6.2 — any staff role can POST incidents; physician and participant_family are denied all access."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    for staff_headers in (admin_headers, coordinator_headers, nurse_headers, billing_headers):
        r = client.post(
            "/incidents",
            json={
                "tenant_id": TENANT_A,
                "participant_id": pid,
                "incident_date": "2026-04-01",
                "incident_type": "behavioral",
                "description": "Participant became agitated during group activity.",
                "severity": "minor",
                "status": "draft",
            },
            headers=staff_headers,
        )
        assert r.status_code == 201, f"Staff role got {r.status_code}: {r.text}"

    inc = make_incident(client, admin_headers, pid, incident_date="2026-04-15", severity="minor")
    inc_id = inc["incident_id"]

    r_physician = client.get(f"/incidents/{inc_id}", headers=physician_headers)
    assert r_physician.status_code == 403

    r_family = client.get(f"/incidents/{inc_id}", headers=family_headers)
    assert r_family.status_code == 403


# ─── 6.3 42 CFR Part 2 — SUD-related incident access gate ────────────────────

def test_6_3_42cfr_part2_sud_related_incident_access_gate(client, admin_headers, billing_headers,
                                                            coordinator_headers):
    """REQ 6.3 — GET is_sud_related=true incident from billing_specialist returns 403."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    inc = make_incident(client, admin_headers, pid, incident_type="other",
                        severity="minor", is_sud_related=True,
                        description="SUD-related incident during group session.")
    inc_id = inc["incident_id"]

    r_billing = client.get(f"/incidents/{inc_id}", headers=billing_headers)
    assert r_billing.status_code == 403
    detail = r_billing.json()["detail"]
    assert "SUD" in detail["error_code"]
    # The raw description value must not appear in the 403 response
    assert "during group session" not in str(detail)
    assert "participant_id" not in str(detail)

    r_coordinator = client.get(f"/incidents/{inc_id}", headers=coordinator_headers)
    assert r_coordinator.status_code == 200


# ─── 6.4 Audit log on SUD-related incident read and write ────────────────────

def test_6_4_audit_log_on_sud_related_incident_read_and_write(
    client, admin_headers, coordinator_headers, billing_headers, compliance_headers
):
    """REQ 6.4 — SUD incident write produces audit event; unauthorized attempt produces DENIED event."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    inc = make_incident(client, admin_headers, pid, incident_type="other",
                        severity="minor", is_sud_related=True,
                        description="SUD incident for audit test.")
    inc_id = inc["incident_id"]

    client.get(f"/incidents/{inc_id}", headers=billing_headers)

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "Incident", "resource_id": inc_id},
        headers=compliance_headers,
    )
    events = logs.json()

    write_event = next((e for e in events if e["action_type"] == "PHI_WRITE"), None)
    assert write_event is not None

    denied_event = next((e for e in events if e["outcome"] == "DENIED"), None)
    assert denied_event is not None


# ─── 6.5 State machine auto-escalates severe and medical_emergency ────────────

def test_6_5_state_machine_auto_escalates_severe_and_medical_emergency(client, admin_headers):
    """REQ 6.5 — POST severity=severe auto-sets status=escalated; PATCH close without regulatory_submission_date returns 422."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    inc = make_incident(client, admin_headers, pid, severity="severe",
                        incident_type="fall", description="Severe fall with head injury.")
    assert inc["status"] == "escalated"
    inc_id = inc["incident_id"]

    r_close_no_date = client.patch(
        f"/incidents/{inc_id}",
        json={"version": inc["version"], "status": "closed"},
        headers=admin_headers,
    )
    assert r_close_no_date.status_code == 422
    assert "REGULATORY_SUBMISSION" in r_close_no_date.json()["detail"]["error_code"]

    r_close_with_date = client.patch(
        f"/incidents/{inc_id}",
        json={
            "version": inc["version"],
            "status": "closed",
            "regulatory_submission_date": "2026-03-16",
        },
        headers=admin_headers,
    )
    assert r_close_with_date.status_code == 200
    assert r_close_with_date.json()["status"] == "closed"


# ─── 6.6 Alert raised when escalated incident approaches 24-hour deadline ────

def test_6_6_alert_raised_when_escalated_incident_approaches_24_hour_deadline(
    client, admin_headers, db_session
):
    """REQ 6.6 — job identifies escalated incidents with null regulatory_submission_date and created_at > 20h."""
    from models import Incident as IncidentModel

    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    inc = make_incident(client, admin_headers, pid, severity="severe",
                        incident_type="fall", description="Severe fall approaching deadline.")
    inc_id = inc["incident_id"]

    # Backdate created_at to 21 hours ago
    db_session.query(IncidentModel).filter(IncidentModel.incident_id == inc_id).update({
        "created_at": datetime.utcnow() - timedelta(hours=21),
    })
    db_session.commit()

    r_job = client.get("/jobs/escalated-incidents-alert")
    assert r_job.status_code == 200
    assert inc_id in r_job.json()["alerted"]


# ─── 6.7 Closed incident is immutable ────────────────────────────────────────

def test_6_7_closed_incident_is_immutable(client, admin_headers):
    """REQ 6.7 — PATCH on closed incident returns 422; new incident referencing original as addendum returns 201."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    inc = make_incident(client, admin_headers, pid, severity="minor",
                        incident_type="fall", description="Minor fall incident.")
    inc_id = inc["incident_id"]

    # Transition to submitted then closed
    r_submit = client.patch(
        f"/incidents/{inc_id}",
        json={"version": inc["version"], "status": "submitted"},
        headers=admin_headers,
    )
    assert r_submit.status_code == 200

    r_close = client.patch(
        f"/incidents/{inc_id}",
        json={"version": r_submit.json()["version"], "status": "closed"},
        headers=admin_headers,
    )
    assert r_close.status_code == 200

    r_modify = client.patch(
        f"/incidents/{inc_id}",
        json={"version": r_close.json()["version"], "description": "Attempt to modify."},
        headers=admin_headers,
    )
    assert r_modify.status_code == 422
    assert "CLOSED" in r_modify.json()["detail"]["error_code"]

    r_addendum = client.post(
        "/incidents",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "incident_date": "2026-03-15",
            "incident_type": "fall",
            "description": f"Addendum to incident {inc_id}: witness statement added.",
            "severity": "minor",
            "status": "draft",
        },
        headers=admin_headers,
    )
    assert r_addendum.status_code == 201
    assert r_addendum.json()["incident_id"] != inc_id


# ─── 6.8 Optimistic locking — version conflict returns 409 ───────────────────

def test_6_8_optimistic_locking_version_conflict_returns_409(client, admin_headers):
    """REQ 6.8 — PATCH with stale version returns 409 INCIDENT_VERSION_CONFLICT; PATCH closed returns 422 first."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    inc = make_incident(client, admin_headers, pid, severity="minor",
                        incident_type="behavioral", description="Test incident for locking.")
    inc_id = inc["incident_id"]
    version = inc["version"]

    # Stale version → 409
    r_stale = client.patch(
        f"/incidents/{inc_id}",
        json={"version": version - 1, "description": "Updated."},
        headers=admin_headers,
    )
    assert r_stale.status_code == 409
    assert r_stale.json()["detail"]["error_code"] == "INCIDENT_VERSION_CONFLICT"

    # Correct version → 200 with n+1
    r_ok = client.patch(
        f"/incidents/{inc_id}",
        json={"version": version, "description": "Updated description text."},
        headers=admin_headers,
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["version"] == version + 1

    # Close the incident
    submitted = client.patch(
        f"/incidents/{inc_id}",
        json={"version": r_ok.json()["version"], "status": "closed"},
        headers=admin_headers,
    )
    assert submitted.status_code == 200

    # PATCH closed with ANY version → 422 before version check
    r_closed_stale = client.patch(
        f"/incidents/{inc_id}",
        json={"version": 0, "description": "Another update."},
        headers=admin_headers,
    )
    assert r_closed_stale.status_code == 422
    assert "CLOSED" in r_closed_stale.json()["detail"]["error_code"]
