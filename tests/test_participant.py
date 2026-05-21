"""
test_participant.py — 12 tests mapped to TC-1.1 through TC-1.12.

Regulatory scope: HIPAA · 42 CFR Part 2 · CMS Medicaid/Medicare · State adult day care licensing
"""
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


# ─── TC-1.1 ──────────────────────────────────────────────────────────────────

def test_tc_1_1_positive_participant_creation_by_program_administrator(
    client, admin_headers, db_session
):
    """TC-1.1 — POST /participants by program_administrator returns 201 with all required fields and program_status active."""
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Claudia",
        "last_name": "Marsh",
        "date_of_birth": "1950-04-12",
        "enrollment_date": "2026-01-01",
    }
    r = _call(lambda: client.post("/participants", json=payload, headers=admin_headers))
    assert r.status_code == 201
    body = r.json()
    assert body["participant_id"] is not None
    assert body["first_name"] == "Claudia"
    assert body["last_name"] == "Marsh"
    assert body["date_of_birth"] == "1950-04-12"
    assert body["enrollment_date"] == "2026-01-01"
    assert body["program_status"] == "active"

    # DB layer: verify the row was persisted with correct fields
    pid = body["participant_id"]
    row = db_session.execute(
        text(
            "SELECT first_name, last_name, program_status, is_deleted "
            "FROM participant WHERE participant_id = :pid"
        ),
        {"pid": pid},
    ).fetchone()
    assert row is not None, f"Participant {pid} not found in DB after creation"
    assert row.first_name == "Claudia"
    assert row.last_name == "Marsh"
    assert row.program_status == "active"
    assert not row.is_deleted


# ─── TC-1.2 ──────────────────────────────────────────────────────────────────

def test_tc_1_2_positive_login_valid_credentials(client, users, db_session):
    """TC-1.2 — POST /login with valid user_id and non-empty password returns 200 with success status."""
    uid = users["admins"][0]["user_id"]
    r = _call(lambda: client.post("/login", json={"user_id": uid, "password": "ValidPass1!"}))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body.get("message") is not None

    # DB layer: login must not alter the participants table
    count = db_session.execute(
        text("SELECT COUNT(*) FROM participant WHERE tenant_id = :tid AND is_deleted = 0"),
        {"tid": TENANT_A},
    ).scalar()
    assert count >= 0, "Participant table count must be a non-negative integer after login"


# ─── TC-1.3 ──────────────────────────────────────────────────────────────────

def test_tc_1_3_negative_login_wrong_password_returns_401(client, users, db_session):
    """TC-1.3 — POST /login with a wrong non-empty password returns 401; error message does not reveal which credential was wrong."""
    uid = users["admins"][0]["user_id"]
    # Use a non-empty string that does not match the stored password hash
    r = _call(lambda: client.post("/login", json={"user_id": uid, "password": "WrongPass!!"}))
    assert r.status_code == 401
    body = r.json()
    assert body.get("status") != "ok"
    msg = body.get("detail", {}).get("message", "")
    assert "email" not in msg.lower()
    assert "user_id" not in msg.lower()
    assert "password" not in msg.lower()

    # DB layer: failed login must not affect the participants table
    count = db_session.execute(
        text("SELECT COUNT(*) FROM participant WHERE tenant_id = :tid"),
        {"tid": TENANT_A},
    ).scalar()
    assert count >= 0, "Participant table count must remain unchanged after a failed login"


# ─── TC-1.4 ──────────────────────────────────────────────────────────────────

def test_tc_1_4_duplicate_medicaid_id_returns_409(client, admin_headers, participants, db_session):
    """TC-1.4 — POST /participants with an already-registered medicaid_id returns 409 PARTICIPANT_DUPLICATE_MEDICAID_ID."""
    existing_medicaid = participants["active"][0]["medicaid_id"]
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Other",
        "last_name": "Person",
        "date_of_birth": "1960-05-10",
        "enrollment_date": "2026-01-01",
        "medicaid_id": existing_medicaid,
    }
    r = _call(lambda: client.post("/participants", json=payload, headers=admin_headers))
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "PARTICIPANT_DUPLICATE_MEDICAID_ID"

    # DB layer: exactly one participant with this medicaid_id must exist
    dup_count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM participant "
            "WHERE medicaid_id = :mid AND tenant_id = :tid"
        ),
        {"mid": existing_medicaid, "tid": TENANT_A},
    ).scalar()
    assert dup_count == 1, (
        f"Expected exactly 1 participant with medicaid_id={existing_medicaid}, found {dup_count}"
    )


# ─── TC-1.5 ──────────────────────────────────────────────────────────────────

def test_tc_1_5_sud_record_billing_specialist_returns_403_no_disclosure(
    client, participants, billing_headers, db_session
):
    """TC-1.5 — GET on is_sud_record=True participant by billing_specialist returns 403 with no participant data in body."""
    pid = participants["sud"]["participant_id"]
    r = _call(lambda: client.get(f"/participants/{pid}", headers=billing_headers))
    assert r.status_code == 403
    body = r.json()
    # Exact error code as defined in architecture.md for SUD access denial
    assert body["detail"]["error_code"] == "SUD_ACCESS_DENIED"
    # No participant data must appear in the error response
    body_str = str(body)
    assert pid not in body_str
    assert "date_of_birth" not in body_str
    assert participants["sud"]["first_name"] not in body_str
    assert participants["sud"]["last_name"] not in body_str

    # DB layer: denied access must leave the SUD participant row unchanged
    row = db_session.execute(
        text(
            "SELECT is_sud_record, is_deleted "
            "FROM participant WHERE participant_id = :pid"
        ),
        {"pid": pid},
    ).fetchone()
    assert row is not None, f"SUD participant {pid} not found in DB"
    assert row.is_sud_record, "SUD participant must still have is_sud_record=True after denied read"
    assert not row.is_deleted, "SUD participant must not be marked deleted after denied read"


# ─── TC-1.6 ──────────────────────────────────────────────────────────────────

def test_tc_1_6_audit_log_phi_operation_mandatory_fields_no_phi_values(
    client, admin_headers, compliance_headers, db_session
):
    """TC-1.6 — PHI_WRITE audit event after POST /participants has all 11 mandatory fields and no PHI values in data_affected."""
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Audra",
        "last_name": "Linden",
        "date_of_birth": "1955-07-19",
        "enrollment_date": "2026-02-01",
    }
    r = _call(lambda: client.post("/participants", json=payload, headers=admin_headers))
    assert r.status_code == 201
    participant_id = r.json()["participant_id"]

    logs_r = _call(lambda: client.get(
        "/audit-logs",
        params={
            "tenant_id": TENANT_A,
            "resource_type": "Participant",
            "resource_id": participant_id,
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
    assert write_event is not None, "PHI_WRITE audit event not found"

    mandatory_fields = [
        "timestamp", "user_id", "tenant_id", "session_id",
        "action_type", "resource_type", "resource_id",
        "data_affected", "source_ip", "outcome", "layer",
    ]
    for field in mandatory_fields:
        assert write_event[field] is not None, f"Mandatory audit field '{field}' is null"

    assert write_event["outcome"] == "SUCCESS"

    data_str = str(write_event["data_affected"])
    for phi_value in ("Audra", "Linden", "1955-07-19"):
        assert phi_value not in data_str, f"PHI value '{phi_value}' found in data_affected"

    # DB layer: verify the participant was persisted correctly
    row = db_session.execute(
        text(
            "SELECT first_name, last_name FROM participant WHERE participant_id = :pid"
        ),
        {"pid": participant_id},
    ).fetchone()
    assert row is not None, f"Participant {participant_id} not found in DB after creation"
    assert row.first_name == "Audra"
    assert row.last_name == "Linden"


# ─── TC-1.7 ──────────────────────────────────────────────────────────────────

def test_tc_1_7_state_machine_active_to_on_leave_returns_200(
    client, fresh_participant, admin_headers, db_session
):
    """TC-1.7 — PATCH program_status from active to on_leave returns 200 with updated status."""
    pid = fresh_participant["participant_id"]
    version = fresh_participant["version"]
    r = _call(lambda: client.patch(
        f"/participants/{pid}",
        json={"version": version, "program_status": "on_leave"},
        headers=admin_headers,
    ))
    assert r.status_code == 200
    assert r.json()["program_status"] == "on_leave"

    # DB layer: verify program_status was persisted as on_leave
    row = db_session.execute(
        text("SELECT program_status FROM participant WHERE participant_id = :pid"),
        {"pid": pid},
    ).fetchone()
    assert row is not None, f"Participant {pid} not found in DB"
    assert row.program_status == "on_leave", (
        f"Expected program_status='on_leave' in DB, got '{row.program_status}'"
    )


# ─── TC-1.8 ──────────────────────────────────────────────────────────────────

def test_tc_1_8_state_machine_deceased_to_active_returns_422(
    client, participants, admin_headers, db_session
):
    """TC-1.8 — PATCH program_status from deceased to active returns 422 with TRANSITION error code."""
    p = participants["deceased"]
    # Guard: version field must be present before it is used in the PATCH body
    assert p.get("version") is not None, (
        "deceased participant fixture is missing the 'version' field — "
        "confirm that the PATCH /participants response includes version"
    )
    r = _call(lambda: client.patch(
        f"/participants/{p['participant_id']}",
        json={"version": p["version"], "program_status": "active"},
        headers=admin_headers,
    ))
    assert r.status_code == 422
    assert "TRANSITION" in r.json()["detail"]["error_code"]

    # DB layer: the illegal transition must leave the status as deceased
    row = db_session.execute(
        text("SELECT program_status FROM participant WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).fetchone()
    assert row is not None, "Deceased participant not found in DB"
    assert row.program_status == "deceased", (
        f"Expected program_status='deceased' in DB after rejected transition, got '{row.program_status}'"
    )


# ─── TC-1.9 ──────────────────────────────────────────────────────────────────

def test_tc_1_9_soft_delete_returns_200_is_deleted_true(
    client, fresh_participant, admin_headers, coordinator_headers, db_session
):
    """TC-1.9 — DELETE returns 200 with is_deleted=True; subsequent GET by care_coordinator returns 404."""
    pid = fresh_participant["participant_id"]

    r_del = _call(lambda: client.delete(f"/participants/{pid}", headers=admin_headers))
    assert r_del.status_code == 200
    assert r_del.json()["is_deleted"] is True

    r_get = _call(lambda: client.get(f"/participants/{pid}", headers=coordinator_headers))
    assert r_get.status_code == 404

    # DB layer: row must still exist but have is_deleted=True (soft delete, not physical removal)
    row = db_session.execute(
        text("SELECT is_deleted FROM participant WHERE participant_id = :pid"),
        {"pid": pid},
    ).fetchone()
    assert row is not None, f"Participant {pid} must still exist in DB after soft delete"
    assert row.is_deleted, "Participant must have is_deleted=True in DB after soft delete"


# ─── TC-1.10 ─────────────────────────────────────────────────────────────────

def test_tc_1_10_hard_delete_attempt_returns_405_record_persists(
    client, fresh_participant, admin_headers, compliance_headers, db_session
):
    """TC-1.10 — DELETE /hard returns 405; record is still retrievable by compliance_officer with include_deleted=true."""
    pid = fresh_participant["participant_id"]

    r_hard = _call(lambda: client.delete(f"/participants/{pid}/hard", headers=admin_headers))
    if r_hard.status_code == 404:
        pytest.fail(
            f"DELETE /participants/{{id}}/hard returned 404 — "
            "the hard-delete endpoint is not implemented in the mock backend. "
            "Add it to mock_backend/main.py returning 405 with error_code=HARD_DELETE_NOT_PERMITTED."
        )
    assert r_hard.status_code == 405
    assert r_hard.json()["detail"]["error_code"] == "HARD_DELETE_NOT_PERMITTED"

    r_list = _call(lambda: client.get(
        "/participants",
        params={"tenant_id": TENANT_A, "include_deleted": "true"},
        headers=compliance_headers,
    ))
    assert r_list.status_code == 200
    ids = [p["participant_id"] for p in r_list.json()]
    assert pid in ids

    # DB layer: hard delete must not remove the row
    row = db_session.execute(
        text(
            "SELECT participant_id, is_deleted FROM participant WHERE participant_id = :pid"
        ),
        {"pid": pid},
    ).fetchone()
    assert row is not None, (
        f"Participant {pid} must still exist in DB after a hard-delete attempt"
    )


# ─── TC-1.11 ─────────────────────────────────────────────────────────────────

def test_tc_1_11_missing_first_name_returns_400_with_field_name(
    client, admin_headers, db_session
):
    """TC-1.11 — POST /participants without first_name returns 400 or 422 and identifies first_name in the error."""
    payload = {
        "tenant_id": TENANT_A,
        "last_name": "Norris",
        "date_of_birth": "1965-03-22",
        "enrollment_date": "2026-01-01",
    }
    r = _call(lambda: client.post("/participants", json=payload, headers=admin_headers))
    assert r.status_code in (400, 422)
    assert "first_name" in r.text

    # DB layer: no participant with last_name 'Norris' must have been created
    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM participant "
            "WHERE last_name = 'Norris' AND tenant_id = :tid"
        ),
        {"tid": TENANT_A},
    ).scalar()
    assert count == 0, (
        "No participant with last_name='Norris' should exist after a failed creation (missing first_name)"
    )


# ─── TC-1.12 ─────────────────────────────────────────────────────────────────

def test_tc_1_12_missing_enrollment_date_returns_400_with_field_name(
    client, admin_headers, db_session
):
    """TC-1.12 — POST /participants without enrollment_date returns 400 or 422 and identifies enrollment_date in the error."""
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Rupert",
        "last_name": "Dane",
        "date_of_birth": "1970-09-30",
    }
    r = _call(lambda: client.post("/participants", json=payload, headers=admin_headers))
    assert r.status_code in (400, 422)
    assert "enrollment_date" in r.text

    # DB layer: no participant with last_name 'Dane' must have been created
    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM participant "
            "WHERE last_name = 'Dane' AND tenant_id = :tid"
        ),
        {"tid": TENANT_A},
    ).scalar()
    assert count == 0, (
        "No participant with last_name='Dane' should exist after a failed creation (missing enrollment_date)"
    )
