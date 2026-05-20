"""
test_attendance.py — 8 tests covering REQ_IDs 3.1–3.8.
"""
import pytest
from helpers import (
    TENANT_A, make_participant, make_attendance, make_confirmed_attendance, make_claim,
    make_headers,
)


# ─── 3.1 Unique attendance per participant per date ───────────────────────────

def test_3_1_unique_attendance_per_participant_per_date(client, admin_headers, coordinator_headers):
    """REQ 3.1 — second attendance for same participant+date in same tenant returns 409 ATTENDANCE_DUPLICATE_DATE."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    make_attendance(client, coordinator_headers, pid, date_of_service="2026-03-10")

    r = client.post(
        "/attendance",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "date_of_service": "2026-03-10",
            "status": "pending",
        },
        headers=coordinator_headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "ATTENDANCE_DUPLICATE_DATE"


# ─── 3.2 RBAC write restricted to program_administrator and care_coordinator ─

def test_3_2_rbac_write_restricted_to_program_administrator_and_care_coordinator(
    client, admin_headers, coordinator_headers, billing_headers, physician_headers, family_headers
):
    """REQ 3.2 — billing_specialist, physician, participant_family get 403; authorized roles succeed."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    base_payload = {
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": "2026-04-01",
        "status": "pending",
    }

    for forbidden_headers in (billing_headers, physician_headers, family_headers):
        r = client.post("/attendance", json=base_payload, headers=forbidden_headers)
        assert r.status_code == 403, f"Expected 403 but got {r.status_code} for role"

    r_admin = client.post(
        "/attendance",
        json={**base_payload, "date_of_service": "2026-04-02"},
        headers=admin_headers,
    )
    assert r_admin.status_code == 201

    r_coord = client.post(
        "/attendance",
        json={**base_payload, "date_of_service": "2026-04-03"},
        headers=coordinator_headers,
    )
    assert r_coord.status_code == 201


# ─── 3.3 Attendance status state machine transitions ─────────────────────────

def test_3_3_attendance_status_state_machine_transitions(client, admin_headers, coordinator_headers, billing_headers):
    """REQ 3.3 — edit to confirmed record resets to pending; pending attendance in claim returns 422."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    att = make_attendance(client, coordinator_headers, pid, date_of_service="2026-05-01")
    att_id = att["attendance_id"]

    # Confirm attendance
    r_confirm = client.patch(
        f"/attendance/{att_id}",
        json={"version": att["version"], "status": "confirmed"},
        headers=coordinator_headers,
    )
    assert r_confirm.status_code == 200
    confirmed = r_confirm.json()
    assert confirmed["status"] == "confirmed"

    # Edit confirmed attendance — should reset to pending
    r_edit = client.patch(
        f"/attendance/{att_id}",
        json={"version": confirmed["version"], "total_hours": 6.0},
        headers=coordinator_headers,
    )
    assert r_edit.status_code == 200
    edited = r_edit.json()
    assert edited["status"] == "pending"

    # Attempt claim on pending attendance — returns 422
    claim_headers = make_headers("billing_specialist")
    r_claim = client.post(
        "/claims",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "attendance_ids": [att_id],
            "payer_type": "medicaid",
            "procedure_code": "S5101",
            "date_of_service_start": "2026-05-01",
        },
        headers=claim_headers,
    )
    assert r_claim.status_code == 422
    assert "CONFIRMED" in r_claim.json()["detail"]["error_code"]


# ─── 3.4 Void reason required when status is voided ──────────────────────────

def test_3_4_void_reason_required_when_status_is_voided(client, admin_headers, coordinator_headers):
    """REQ 3.4 — PATCH to voided without void_reason returns 422; with void_reason returns 200."""
    p = make_participant(client, admin_headers)
    att = make_attendance(client, coordinator_headers, p["participant_id"], date_of_service="2026-06-01")
    att_id = att["attendance_id"]

    r_no_reason = client.patch(
        f"/attendance/{att_id}",
        json={"version": att["version"], "status": "voided"},
        headers=coordinator_headers,
    )
    assert r_no_reason.status_code == 422
    assert "VOID_REASON" in r_no_reason.json()["detail"]["error_code"]

    r_with_reason = client.patch(
        f"/attendance/{att_id}",
        json={"version": att["version"], "status": "voided", "void_reason": "Data entry error."},
        headers=coordinator_headers,
    )
    assert r_with_reason.status_code == 200
    assert r_with_reason.json()["void_reason"] == "Data entry error."


# ─── 3.5 Audit log on attendance write operations ────────────────────────────

def test_3_5_audit_log_on_attendance_write_operations(client, admin_headers, coordinator_headers, compliance_headers):
    """REQ 3.5 — any Attendance write produces audit event with mandatory fields; data_affected has field names only."""
    p = make_participant(client, admin_headers)
    att = make_attendance(client, coordinator_headers, p["participant_id"], date_of_service="2026-07-01")
    att_id = att["attendance_id"]

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "Attendance", "resource_id": att_id},
        headers=compliance_headers,
    )
    assert logs.status_code == 200
    events = logs.json()
    assert len(events) >= 1

    write_event = next((e for e in events if e["action_type"] == "PHI_WRITE"), None)
    assert write_event is not None
    assert write_event["resource_type"] == "Attendance"
    assert write_event["outcome"] == "SUCCESS"

    data_affected = write_event["data_affected"]
    assert isinstance(data_affected, list)
    phi_values = [p["first_name"], p["last_name"], "2026-07-01"]
    payload_str = str(data_affected)
    for phi in phi_values:
        assert phi not in payload_str


# ─── 3.6 Authorized units consumed derived from total hours ──────────────────

def test_3_6_authorized_units_consumed_derived_from_total_hours(client, admin_headers, coordinator_headers):
    """REQ 3.6 — 6h sign-out sets authorized_units_consumed=24; Medicare daily-rate sets value=1.0."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    # Medicaid: 6 hours × 4 units/hour = 24
    att_medicaid = make_attendance(
        client, coordinator_headers, pid,
        date_of_service="2026-08-01",
        total_hours=6.0,
        service_type_code="S5101",
    )
    assert float(att_medicaid["authorized_units_consumed"]) == 24.0

    # Medicare daily rate: 1 unit
    att_medicare = make_attendance(
        client, coordinator_headers, pid,
        date_of_service="2026-08-02",
        total_hours=6.0,
        service_type_code="MCR001",
    )
    assert float(att_medicare["authorized_units_consumed"]) == 1.0


# ─── 3.7 Void blocked when referencing claim is active ───────────────────────

def test_3_7_void_blocked_when_referencing_claim_is_active(client, admin_headers, coordinator_headers, billing_headers):
    """REQ 3.7 — void on billed attendance with active claim returns 422."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    att = make_confirmed_attendance(client, coordinator_headers, pid, date_of_service="2026-09-01")
    att_id = att["attendance_id"]

    claim = make_claim(client, billing_headers, pid, [att_id])
    claim_id = claim["claim_id"]

    # Transition claim to submitted (active state)
    r_submit = client.patch(
        f"/claims/{claim_id}",
        json={"version": claim["version"], "claim_status": "submitted"},
        headers=billing_headers,
    )
    assert r_submit.status_code == 200

    # Attempt to void the attendance — should fail
    r_void = client.patch(
        f"/attendance/{att_id}",
        json={"version": att["version"], "status": "voided", "void_reason": "Error."},
        headers=coordinator_headers,
    )
    assert r_void.status_code == 422
    assert "CLAIM" in r_void.json()["detail"]["error_code"]


# ─── 3.8 Optimistic locking — version conflict returns 409 ───────────────────

def test_3_8_optimistic_locking_version_conflict_returns_409(client, admin_headers, coordinator_headers):
    """REQ 3.8 — PATCH with stale version returns 409 ATTENDANCE_VERSION_CONFLICT; correct version returns 200 with n+1."""
    p = make_participant(client, admin_headers)
    att = make_attendance(client, coordinator_headers, p["participant_id"], date_of_service="2026-10-01")
    att_id = att["attendance_id"]
    version = att["version"]

    r_stale = client.patch(
        f"/attendance/{att_id}",
        json={"version": version - 1, "status": "confirmed"},
        headers=coordinator_headers,
    )
    assert r_stale.status_code == 409
    assert r_stale.json()["detail"]["error_code"] == "ATTENDANCE_VERSION_CONFLICT"

    r_ok = client.patch(
        f"/attendance/{att_id}",
        json={"version": version, "status": "confirmed"},
        headers=coordinator_headers,
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["version"] == version + 1
