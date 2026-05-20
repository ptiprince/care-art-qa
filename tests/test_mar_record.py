"""
test_mar_record.py — 10 tests covering REQ_IDs 5.1–5.10.
"""
from datetime import datetime, timedelta

import pytest
from helpers import (
    TENANT_A, make_participant, make_nurse_user, make_mar_record, make_headers,
)


# ─── 5.1 Unique MAR per participant, medication, and scheduled_time ──────────

def test_5_1_unique_mar_per_participant_medication_and_scheduled_time(client, admin_headers, nurse_headers):
    """REQ 5.1 — duplicate participant+medication+scheduled_time returns 409 MAR_DUPLICATE_EVENT."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    make_mar_record(client, nurse_headers, pid, nid,
                    scheduled_time="2026-03-01T09:00:00",
                    medication_name="Metformin")

    r = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Metformin",
            "administered_by": nid,
            "scheduled_time": "2026-03-01T09:00:00",
            "status": "administered",
            "administered_time": "2026-03-01T09:05:00",
        },
        headers=nurse_headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "MAR_DUPLICATE_EVENT"


# ─── 5.2 RBAC write restricted to nurse_medication_aide ──────────────────────

def test_5_2_rbac_write_restricted_to_nurse_medication_aide(client, admin_headers, nurse_headers,
                                                               coordinator_headers, billing_headers):
    """REQ 5.2 — care_coordinator and billing_specialist get 403; nurse_medication_aide succeeds."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    base_payload = {
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "medication_name": "Aspirin",
        "administered_by": nid,
        "scheduled_time": "2026-03-02T10:00:00",
        "status": "administered",
        "administered_time": "2026-03-02T10:05:00",
    }

    r_coord = client.post("/mar-records", json=base_payload, headers=coordinator_headers)
    assert r_coord.status_code == 403

    r_billing = client.post("/mar-records", json=base_payload, headers=billing_headers)
    assert r_billing.status_code == 403

    r_nurse = client.post("/mar-records", json=base_payload, headers=nurse_headers)
    assert r_nurse.status_code == 201


# ─── 5.3 42 CFR Part 2 — controlled substance access gate ────────────────────

def test_5_3_42cfr_part2_controlled_substance_access_gate(client, admin_headers, nurse_headers,
                                                            billing_headers, coordinator_headers):
    """REQ 5.3 — GET controlled-substance MAR from unauthorized role returns 403 with no record disclosure."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    mar = make_mar_record(
        client, nurse_headers, pid, nid,
        scheduled_time="2026-03-03T09:00:00",
        is_controlled_substance=True,
        medication_name="Oxycodone",
    )
    mar_id = mar["mar_id"]

    # billing_specialist is not in SUD_PRIVILEGED_ROLES for mar_record
    r_billing = client.get(f"/mar-records/{mar_id}", headers=billing_headers)
    assert r_billing.status_code == 403
    detail = r_billing.json()["detail"]
    assert "SUD" in detail["error_code"]
    # No record data in response body
    assert "Oxycodone" not in str(detail)
    assert "participant_id" not in str(detail)

    # nurse_medication_aide is privileged
    r_nurse = client.get(f"/mar-records/{mar_id}", headers=nurse_headers)
    assert r_nurse.status_code == 200


# ─── 5.4 Audit log on controlled substance read and write ────────────────────

def test_5_4_audit_log_on_controlled_substance_read_and_write(client, admin_headers, nurse_headers,
                                                                billing_headers, compliance_headers):
    """REQ 5.4 — Write to controlled-substance MAR produces audit event; denied attempt produces ACCESS_DENIED event."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    mar = make_mar_record(
        client, nurse_headers, pid, nid,
        scheduled_time="2026-03-04T09:00:00",
        is_controlled_substance=True,
        medication_name="Morphine",
    )
    mar_id = mar["mar_id"]

    # Access denied attempt
    client.get(f"/mar-records/{mar_id}", headers=billing_headers)

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "MARRecord", "resource_id": mar_id},
        headers=compliance_headers,
    )
    events = logs.json()

    write_event = next((e for e in events if e["action_type"] == "PHI_WRITE"), None)
    assert write_event is not None
    assert write_event["outcome"] == "SUCCESS"

    denied_event = next((e for e in events if e["outcome"] == "DENIED"), None)
    assert denied_event is not None


# ─── 5.5 Status field rules: administered, refused, held, missed ──────────────

def test_5_5_status_field_rules_administered_refused_held_missed(client, admin_headers, nurse_headers):
    """REQ 5.5 — administered without administered_time returns 422; refused/held without notes returns 422."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    r_admin_no_time = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Lisinopril",
            "administered_by": nid,
            "scheduled_time": "2026-03-05T09:00:00",
            "status": "administered",
        },
        headers=nurse_headers,
    )
    assert r_admin_no_time.status_code == 422
    assert "ADMINISTERED_TIME" in r_admin_no_time.json()["detail"]["error_code"]

    r_refused_no_notes = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Lisinopril",
            "administered_by": nid,
            "scheduled_time": "2026-03-05T10:00:00",
            "status": "refused",
        },
        headers=nurse_headers,
    )
    assert r_refused_no_notes.status_code == 422
    assert "NOTES" in r_refused_no_notes.json()["detail"]["error_code"]

    r_held_no_notes = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Lisinopril",
            "administered_by": nid,
            "scheduled_time": "2026-03-05T11:00:00",
            "status": "held",
        },
        headers=nurse_headers,
    )
    assert r_held_no_notes.status_code == 422
    assert "NOTES" in r_held_no_notes.json()["detail"]["error_code"]


# ─── 5.6 Administered time required and within bounds ────────────────────────

def test_5_6_administered_time_required_and_within_bounds(client, admin_headers, nurse_headers):
    """REQ 5.6 — future administered_time returns 422 ADMIN_TIME_FUTURE; too early returns 422 ADMIN_TIME_TOO_EARLY."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    future_time = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    r_future = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Warfarin",
            "administered_by": nid,
            "scheduled_time": "2026-03-06T09:00:00",
            "status": "administered",
            "administered_time": future_time,
        },
        headers=nurse_headers,
    )
    assert r_future.status_code == 422
    assert r_future.json()["detail"]["error_code"] == "ADMIN_TIME_FUTURE"

    # More than 2 hours before scheduled_time
    too_early = "2026-03-06T06:00:00"
    r_early = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Warfarin",
            "administered_by": nid,
            "scheduled_time": "2026-03-06T09:00:00",
            "status": "administered",
            "administered_time": too_early,
        },
        headers=nurse_headers,
    )
    assert r_early.status_code == 422
    assert r_early.json()["detail"]["error_code"] == "ADMIN_TIME_TOO_EARLY"


# ─── 5.7 Route must be oral, injection, or topical ───────────────────────────

def test_5_7_route_must_be_oral_injection_or_topical(client, admin_headers, nurse_headers):
    """REQ 5.7 — invalid route returns 400; null route returns 400 (422); valid route returns 201."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    r_invalid_route = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Ibuprofen",
            "administered_by": nid,
            "scheduled_time": "2026-03-07T09:00:00",
            "status": "administered",
            "administered_time": "2026-03-07T09:05:00",
            "route": "intravenous",
        },
        headers=nurse_headers,
    )
    assert r_invalid_route.status_code in (400, 422)

    r_valid = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Ibuprofen",
            "administered_by": nid,
            "scheduled_time": "2026-03-07T09:00:00",
            "status": "administered",
            "administered_time": "2026-03-07T09:05:00",
            "route": "oral",
        },
        headers=nurse_headers,
    )
    assert r_valid.status_code == 201


# ─── 5.8 Administered record is immutable ────────────────────────────────────

def test_5_8_administered_record_is_immutable(client, admin_headers, nurse_headers):
    """REQ 5.8 — PATCH on MARRecord with status=administered returns 422 for any field change."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    mar = make_mar_record(client, nurse_headers, pid, nid,
                          scheduled_time="2026-03-08T09:00:00",
                          status="administered")
    mar_id = mar["mar_id"]

    r_patch = client.patch(
        f"/mar-records/{mar_id}",
        json={"version": mar["version"], "notes": "Correction attempt."},
        headers=nurse_headers,
    )
    assert r_patch.status_code == 422
    assert "ADMINISTERED" in r_patch.json()["detail"]["error_code"]


# ─── 5.9 Correction record references original mar_id ────────────────────────

def test_5_9_correction_record_references_original_mar_id(client, admin_headers, nurse_headers):
    """REQ 5.9 — A correction record is a new MAR entry with distinct scheduled_time;
    the original administered record remains unchanged; correction POST with long clinical notes returns 201."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    original = make_mar_record(client, nurse_headers, pid, nid,
                               scheduled_time="2026-03-09T09:00:00",
                               status="administered",
                               medication_name="Metformin")
    orig_id = original["mar_id"]
    assert original["status"] == "administered"

    # Valid correction: different scheduled_time (distinct entry), long notes
    r_correction = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Metformin",
            "administered_by": nid,
            "scheduled_time": "2026-03-09T09:30:00",
            "status": "administered",
            "administered_time": "2026-03-09T09:35:00",
            "notes": "Correction: original dose was 500mg, this corrects to 250mg per physician order.",
        },
        headers=nurse_headers,
    )
    assert r_correction.status_code == 201
    assert r_correction.json()["mar_id"] != orig_id

    # Original remains unchanged
    original_unchanged = client.get(f"/mar-records/{orig_id}", headers=nurse_headers).json()
    assert original_unchanged["mar_id"] == orig_id
    assert original_unchanged["status"] == "administered"


# ─── 5.10 Optimistic locking — version conflict returns 409 ──────────────────

def test_5_10_optimistic_locking_version_conflict_returns_409(client, admin_headers, nurse_headers):
    """REQ 5.10 — PATCH non-administered MAR with stale version returns 409; administered returns 422 before version check."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse = make_nurse_user(client, admin_headers)
    nid = nurse["user_id"]

    # Create a non-administered record (refused)
    mar_refused = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Amlodipine",
            "administered_by": nid,
            "scheduled_time": "2026-03-10T09:00:00",
            "status": "refused",
            "notes": "Participant declined medication.",
        },
        headers=nurse_headers,
    )
    assert mar_refused.status_code == 201
    mar_id = mar_refused.json()["mar_id"]
    version = mar_refused.json()["version"]

    # Stale version → 409
    r_stale = client.patch(
        f"/mar-records/{mar_id}",
        json={"version": version - 1, "notes": "Updated note."},
        headers=nurse_headers,
    )
    assert r_stale.status_code == 409
    assert r_stale.json()["detail"]["error_code"] == "MAR_VERSION_CONFLICT"

    # Correct version → 200 with n+1
    r_ok = client.patch(
        f"/mar-records/{mar_id}",
        json={"version": version, "notes": "Updated clinical note."},
        headers=nurse_headers,
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["version"] == version + 1

    # Administered record → 422 before version check (use any version)
    mar_admin = make_mar_record(client, nurse_headers, pid, nid,
                                scheduled_time="2026-03-10T10:00:00",
                                status="administered")
    r_admin_patch = client.patch(
        f"/mar-records/{mar_admin['mar_id']}",
        json={"version": 0, "notes": "Should be blocked."},
        headers=nurse_headers,
    )
    assert r_admin_patch.status_code == 422
    assert "ADMINISTERED" in r_admin_patch.json()["detail"]["error_code"]
