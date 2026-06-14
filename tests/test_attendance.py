"""
test_attendance.py — 12 tests mapped to TC-3.1 through TC-3.12.

Regulatory scope: HIPAA · CMS Medicaid/Medicare · State adult day care licensing
"""
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from sqlalchemy import text

from helpers import TENANT_A


def _call(fn):
    """
    Execute a bound client call.  Fails with a clear message when the mock
    backend is unreachable or does not respond within the configured timeout.
    """
    try:
        return fn()
    except httpx.ConnectError:
        pytest.fail(
            "Cannot connect to the mock backend — ensure the server is running "
            "and accessible at the expected address."
        )
    except httpx.TimeoutException:
        pytest.fail(
            "Mock backend did not respond within the timeout — "
            "the server may be overloaded or has stopped."
        )


# ─── TC-3.1 ──────────────────────────────────────────────────────────────────

def test_tc_3_1_positive_attendance_creation_by_program_administrator(
    client, admin_headers, participants, db_session
):
    """TC-3.1 — POST /attendance by program_administrator returns 201 with status pending."""
    today = datetime.now(timezone.utc).date()
    dos_3_1 = (today - timedelta(days=81)).isoformat()
    pid = participants["active"][0]["participant_id"]
    r = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": dos_3_1,
    }, headers=admin_headers))
    assert r.status_code == 201
    body = r.json()
    assert body["attendance_id"] is not None
    assert body["participant_id"] == pid
    assert body["date_of_service"] == dos_3_1
    assert body["status"] == "pending"
    assert body["version"] is not None

    # DB layer: verify the row was persisted with correct fields
    att_id = body["attendance_id"]
    row = db_session.execute(
        text(
            "SELECT participant_id, date_of_service, status, version, is_deleted "
            "FROM attendance WHERE attendance_id = :aid"
        ),
        {"aid": att_id},
    ).fetchone()
    assert row is not None, f"Attendance {att_id} not found in DB after creation"
    assert row.participant_id == pid
    assert str(row.date_of_service) == dos_3_1
    assert row.status == "pending"
    assert not row.is_deleted


# ─── TC-3.2 ──────────────────────────────────────────────────────────────────

def test_tc_3_2_positive_attendance_creation_by_care_coordinator(
    client, coordinator_headers, participants, db_session
):
    """TC-3.2 — POST /attendance by care_coordinator returns 201 with status pending."""
    today = datetime.now(timezone.utc).date()
    dos_3_2 = (today - timedelta(days=82)).isoformat()
    pid = participants["active"][1]["participant_id"]
    r = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": dos_3_2,
    }, headers=coordinator_headers))
    assert r.status_code == 201
    body = r.json()
    assert body["attendance_id"] is not None
    assert body["participant_id"] == pid
    assert body["status"] == "pending"

    # DB layer: verify the row exists with correct participant and status
    att_id = body["attendance_id"]
    row = db_session.execute(
        text(
            "SELECT participant_id, status FROM attendance WHERE attendance_id = :aid"
        ),
        {"aid": att_id},
    ).fetchone()
    assert row is not None, f"Attendance {att_id} not found in DB after creation by care_coordinator"
    assert row.participant_id == pid
    assert row.status == "pending"


# ─── TC-3.3 ──────────────────────────────────────────────────────────────────

def test_tc_3_3_missing_date_of_service_returns_400(
    client, admin_headers, participants, db_session
):
    """TC-3.3 — POST /attendance without date_of_service returns 400 or 422 identifying the field."""
    pid = participants["active"][5]["participant_id"]
    r = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        # date_of_service deliberately omitted
    }, headers=admin_headers))
    assert r.status_code in (400, 422)
    assert "date_of_service" in r.text, (
        "Error response must identify 'date_of_service' as the missing field"
    )

    # DB layer: no attendance must exist for this participant on the sentinel date
    today = datetime.now(timezone.utc).date()
    dos_3_3 = (today - timedelta(days=83)).isoformat()
    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM attendance "
            "WHERE participant_id = :pid AND date_of_service = :dos"
        ),
        {"pid": pid, "dos": dos_3_3},
    ).scalar()
    assert count == 0, (
        "No attendance should exist after a failed creation missing date_of_service"
    )


# ─── TC-3.4 ──────────────────────────────────────────────────────────────────

def test_tc_3_4_missing_participant_id_returns_400(
    client, coordinator_headers, db_session
):
    """TC-3.4 — POST /attendance without participant_id returns 400 or 422 identifying the field."""
    today = datetime.now(timezone.utc).date()
    dos_3_4 = (today - timedelta(days=84)).isoformat()
    r = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        # participant_id deliberately omitted
        "date_of_service": dos_3_4,
    }, headers=coordinator_headers))
    assert r.status_code in (400, 422)
    assert "participant_id" in r.text, (
        "Error response must identify 'participant_id' as the missing field"
    )

    # DB layer: no attendance must exist on the sentinel date within this tenant
    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM attendance "
            "WHERE date_of_service = :dos AND tenant_id = :tid"
        ),
        {"dos": dos_3_4, "tid": TENANT_A},
    ).scalar()
    assert count == 0, (
        f"No attendance should exist on {dos_3_4} after a failed creation missing participant_id"
    )


# ─── TC-3.5 ──────────────────────────────────────────────────────────────────

def test_tc_3_5_duplicate_participant_date_returns_409(
    client, admin_headers, fresh_participant, db_session
):
    """TC-3.5 — POST /attendance for the same participant_id and date_of_service returns 409 ATTENDANCE_DUPLICATE_DATE."""
    today = datetime.now(timezone.utc).date()
    dos_3_5 = (today - timedelta(days=85)).isoformat()
    pid = fresh_participant["participant_id"]

    r1 = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": dos_3_5,
    }, headers=admin_headers))
    assert r1.status_code == 201, f"First attendance creation failed: {r1.text}"

    r2 = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": dos_3_5,
    }, headers=admin_headers))
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "ATTENDANCE_DUPLICATE_DATE"

    # DB layer: exactly one attendance row must exist for this participant on this date
    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM attendance "
            "WHERE participant_id = :pid AND date_of_service = :dos"
        ),
        {"pid": pid, "dos": dos_3_5},
    ).scalar()
    assert count == 1, (
        f"Expected exactly 1 attendance for participant {pid} on {dos_3_5}, found {count}"
    )


# ─── TC-3.6 ──────────────────────────────────────────────────────────────────

def test_tc_3_6_status_transition_pending_to_confirmed(
    client, admin_headers, fresh_attendance, db_session
):
    """TC-3.6 — PATCH attendance status from pending to confirmed returns 200; DB shows confirmed."""
    att, _p = fresh_attendance
    att_id = att["attendance_id"]
    version = att["version"]

    r = _call(lambda: client.patch(
        f"/attendance/{att_id}",
        json={"version": version, "status": "confirmed"},
        headers=admin_headers,
    ))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["version"] == version + 1

    # DB layer: status and version must be persisted correctly
    row = db_session.execute(
        text("SELECT status, version FROM attendance WHERE attendance_id = :aid"),
        {"aid": att_id},
    ).fetchone()
    assert row is not None, f"Attendance {att_id} not found in DB"
    assert row.status == "confirmed", (
        f"Expected status='confirmed' in DB, got '{row.status}'"
    )
    assert row.version == version + 1, (
        f"Expected version={version + 1} in DB, got {row.version}"
    )


# ─── TC-3.7 ──────────────────────────────────────────────────────────────────

def test_tc_3_7_void_with_void_reason_returns_200(
    client, admin_headers, fresh_attendance, db_session
):
    """TC-3.7 — PATCH attendance with status=voided and void_reason returns 200; DB shows voided."""
    att, _p = fresh_attendance
    att_id = att["attendance_id"]
    version = att["version"]

    r = _call(lambda: client.patch(
        f"/attendance/{att_id}",
        json={"version": version, "status": "voided", "void_reason": "Data entry error"},
        headers=admin_headers,
    ))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "voided"
    assert body["void_reason"] == "Data entry error"

    # DB layer: status and void_reason must be persisted
    row = db_session.execute(
        text(
            "SELECT status, void_reason FROM attendance WHERE attendance_id = :aid"
        ),
        {"aid": att_id},
    ).fetchone()
    assert row is not None, f"Attendance {att_id} not found in DB"
    assert row.status == "voided", (
        f"Expected status='voided' in DB, got '{row.status}'"
    )
    assert row.void_reason == "Data entry error", (
        f"Expected void_reason='Data entry error' in DB, got '{row.void_reason}'"
    )


# ─── TC-3.8 ──────────────────────────────────────────────────────────────────

def test_tc_3_8_void_without_void_reason_returns_422(
    client, admin_headers, fresh_attendance, db_session
):
    """TC-3.8 — PATCH attendance with status=voided but no void_reason returns 422 VOID_REASON_REQUIRED; status unchanged."""
    att, _p = fresh_attendance
    att_id = att["attendance_id"]
    version = att["version"]

    r = _call(lambda: client.patch(
        f"/attendance/{att_id}",
        json={"version": version, "status": "voided"},
        # void_reason deliberately omitted
        headers=admin_headers,
    ))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "VOID_REASON_REQUIRED"

    # DB layer: status must remain pending — the failed PATCH must not alter the row
    row = db_session.execute(
        text("SELECT status FROM attendance WHERE attendance_id = :aid"),
        {"aid": att_id},
    ).fetchone()
    assert row is not None, f"Attendance {att_id} not found in DB"
    assert row.status == "pending", (
        f"Expected status='pending' after rejected void, got '{row.status}'"
    )


# ─── TC-3.9 ──────────────────────────────────────────────────────────────────

def test_tc_3_9_billing_units_total_hours_to_authorized_units_consumed(
    client, admin_headers, participants, db_session
):
    """TC-3.9 — total_hours is converted server-side to authorized_units_consumed at Medicaid rate (1 h = 4 units)."""
    pid = participants["active"][2]["participant_id"]

    today = datetime.now(timezone.utc).date()
    dos_3_9_a = (today - timedelta(days=86)).isoformat()
    dos_3_9_b = (today - timedelta(days=87)).isoformat()
    # 6 hours × 4 units/hour = 24 units
    r1 = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": dos_3_9_a,
        "total_hours": 6.0,
    }, headers=admin_headers))
    assert r1.status_code == 201, f"Attendance creation failed: {r1.text}"
    body1 = r1.json()
    assert body1["authorized_units_consumed"] == 24.0, (
        f"Expected authorized_units_consumed=24.0 for total_hours=6.0, "
        f"got {body1['authorized_units_consumed']}"
    )

    att_id1 = body1["attendance_id"]
    row1 = db_session.execute(
        text(
            "SELECT authorized_units_consumed FROM attendance WHERE attendance_id = :aid"
        ),
        {"aid": att_id1},
    ).fetchone()
    assert row1 is not None, f"Attendance {att_id1} not found in DB"
    assert float(row1.authorized_units_consumed) == 24.0, (
        f"Expected 24.0 in DB for total_hours=6.0, got {row1.authorized_units_consumed}"
    )

    # 8 hours × 4 units/hour = 32 units
    r2 = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": dos_3_9_b,
        "total_hours": 8.0,
    }, headers=admin_headers))
    assert r2.status_code == 201, f"Second attendance creation failed: {r2.text}"
    body2 = r2.json()
    assert body2["authorized_units_consumed"] == 32.0, (
        f"Expected authorized_units_consumed=32.0 for total_hours=8.0, "
        f"got {body2['authorized_units_consumed']}"
    )

    att_id2 = body2["attendance_id"]
    row2 = db_session.execute(
        text(
            "SELECT authorized_units_consumed FROM attendance WHERE attendance_id = :aid"
        ),
        {"aid": att_id2},
    ).fetchone()
    assert row2 is not None, f"Attendance {att_id2} not found in DB"
    assert float(row2.authorized_units_consumed) == 32.0, (
        f"Expected 32.0 in DB for total_hours=8.0, got {row2.authorized_units_consumed}"
    )


# ─── TC-3.10 ─────────────────────────────────────────────────────────────────

def test_tc_3_10_billed_attendance_cannot_be_modified(
    client, admin_headers, fresh_claim, db_session
):
    """TC-3.10 — PATCH on a billed attendance record returns 422; status remains billed in DB."""
    _claim, att, _p = fresh_claim
    att_id = att["attendance_id"]

    # Re-fetch to get the current state — claim creation transitions status to billed
    r_get = _call(lambda: client.get(f"/attendance/{att_id}", headers=admin_headers))
    assert r_get.status_code == 200
    current = r_get.json()
    assert current["status"] == "billed", (
        f"Attendance must be billed after claim creation, got '{current['status']}'"
    )

    r_patch = _call(lambda: client.patch(
        f"/attendance/{att_id}",
        json={"version": current["version"], "total_hours": 7.0},
        headers=admin_headers,
    ))
    assert r_patch.status_code == 422, (
        f"Expected 422 when modifying a billed attendance, got {r_patch.status_code}"
    )

    # DB layer: status must remain billed — the rejected PATCH must not alter the row
    row = db_session.execute(
        text("SELECT status FROM attendance WHERE attendance_id = :aid"),
        {"aid": att_id},
    ).fetchone()
    assert row is not None, f"Attendance {att_id} not found in DB"
    assert row.status == "billed", (
        f"Expected status='billed' after rejected PATCH, got '{row.status}'"
    )


# ─── TC-3.11 ─────────────────────────────────────────────────────────────────

def test_tc_3_11_audit_log_on_creation_has_mandatory_fields_no_phi(
    client, admin_headers, compliance_headers, participants, db_session
):
    """TC-3.11 — PHI_WRITE audit event after POST /attendance has all 11 mandatory fields and no PHI values in data_affected."""
    pid = participants["active"][3]["participant_id"]

    today = datetime.now(timezone.utc).date()
    dos_3_11 = (today - timedelta(days=88)).isoformat()
    r = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": dos_3_11,
    }, headers=admin_headers))
    assert r.status_code == 201
    att_id = r.json()["attendance_id"]

    logs_r = _call(lambda: client.get(
        "/audit-logs",
        params={
            "tenant_id": TENANT_A,
            "resource_type": "Attendance",
            "resource_id": att_id,
        },
        headers=compliance_headers,
    ))
    if logs_r.status_code == 404:
        pytest.fail(
            "GET /audit-logs returned 404 — the audit-log endpoint is not implemented "
            "in the mock backend. Add it before running this test."
        )
    assert logs_r.status_code == 200
    events = logs_r.json()

    write_event = next(
        (e for e in events if e["action_type"] == "PHI_WRITE"), None
    )
    assert write_event is not None, "PHI_WRITE audit event not found for attendance creation"

    mandatory_fields = [
        "timestamp", "user_id", "tenant_id", "session_id",
        "action_type", "resource_type", "resource_id",
        "data_affected", "source_ip", "outcome", "layer",
    ]
    for field in mandatory_fields:
        assert write_event[field] is not None, (
            f"Mandatory audit field '{field}' is null"
        )

    assert write_event["outcome"] == "SUCCESS"
    assert write_event["resource_type"] == "Attendance"

    # data_affected must contain field names only — no PHI values from the participant record
    data_str = str(write_event["data_affected"])
    participant = participants["active"][3]
    for phi_value in (participant["first_name"], participant["last_name"],
                      participant.get("date_of_birth", "")):
        if phi_value:
            assert phi_value not in data_str, (
                f"PHI value '{phi_value}' found in data_affected — "
                "audit log must not expose PHI values"
            )

    # DB layer: verify the attendance row was persisted
    row = db_session.execute(
        text(
            "SELECT attendance_id, participant_id, status "
            "FROM attendance WHERE attendance_id = :aid"
        ),
        {"aid": att_id},
    ).fetchone()
    assert row is not None, f"Attendance {att_id} not found in DB after creation"
    assert row.participant_id == pid
    assert row.status == "pending"


# ─── TC-3.12 ─────────────────────────────────────────────────────────────────

def test_tc_3_12_billing_specialist_create_attendance_returns_403(
    client, billing_headers, participants, db_session
):
    """TC-3.12 — POST /attendance by billing_specialist returns 403; no attendance row created."""
    pid = participants["active"][4]["participant_id"]

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM attendance WHERE participant_id = :pid"),
        {"pid": pid},
    ).scalar()

    today = datetime.now(timezone.utc).date()
    dos_3_12 = (today - timedelta(days=89)).isoformat()
    r = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "date_of_service": dos_3_12,
    }, headers=billing_headers))
    assert r.status_code == 403

    # DB layer: attendance count for this participant must be unchanged
    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM attendance WHERE participant_id = :pid"),
        {"pid": pid},
    ).scalar()
    assert count_after == count_before, (
        f"No attendance should be created after a 403 rejection by billing_specialist "
        f"(before={count_before}, after={count_after})"
    )
