"""
test_mar_record.py — 21 tests mapped to TC-5.1 through TC-5.21.

Regulatory scope: HIPAA §164.308 / §164.312 · 42 CFR Part 2 (SUD / controlled
substance records) · State adult day care medication-administration rules.

Design rules (enforced throughout):
  - All DB seeding lives in conftest.py fixtures.
  - All API actions are invoked via _call(); test functions contain only
    business-logic assertions.
  - Every assertion on persisted state queries the SQLite DB directly through
    db_session.
  - No time.sleep(), no UI, no inline data creation in test functions.
  - No hardcoded dates; all timestamps computed via datetime.now(timezone.utc)
    and timedelta at runtime.
  - Audit log assertions always query audit_log table directly; all 11 mandatory
    fields asserted; no PHI values asserted absent from data_affected.
  - Error codes asserted exactly: MAR_DUPLICATE_EVENT, MAR_MISSING_ADMINISTERED_TIME,
    MAR_MISSING_NOTES, ADMIN_TIME_FUTURE, ADMIN_TIME_TOO_EARLY,
    MAR_ADMINISTERED_IMMUTABLE, MAR_VERSION_CONFLICT,
    MAR_CORRECTION_MISSING_ORIGINAL, MAR_CORRECTION_NOTES_TOO_SHORT, RBAC_DENIED.
  - SUD/controlled-substance privileged roles for mar_record:
    compliance_officer and nurse_medication_aide.
  - WRITE_ROLES["mar_record"] = {"nurse_medication_aide"} only.
"""
import json as _json
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from sqlalchemy import text

from helpers import TENANT_A, NURSE_ID, ADMIN_ID, COORDINATOR_ID, BILLING_ID, make_headers


def _call(fn):
    """Execute a bound client call with connectivity error handling."""
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


_AUDIT_FIELDS = (
    "audit_id", "timestamp", "user_id", "tenant_id", "session_id",
    "action_type", "resource_type", "resource_id", "data_affected",
    "source_ip", "outcome", "layer",
)


def _assert_audit_row(row, *, action_type, resource_type, resource_id,
                      outcome, user_id=None, session_id=None, tenant_id=None):
    """Assert all 11 mandatory audit fields are non-null and key values match."""
    for field in _AUDIT_FIELDS:
        assert getattr(row, field) is not None, (
            f"Mandatory audit field '{field}' is null in audit_log"
        )
    assert row.action_type == action_type, f"Expected action_type='{action_type}', got '{row.action_type}'"
    assert row.resource_type == resource_type
    assert row.resource_id == resource_id
    assert row.outcome == outcome
    assert row.layer == "APP_SERVICE"
    if user_id is not None:
        assert row.user_id == user_id
    if session_id is not None:
        assert row.session_id == session_id
    if tenant_id is not None:
        assert row.tenant_id == tenant_id


# ─── TC-5.1 ──────────────────────────────────────────────────────────────────

def test_tc_5_1_duplicate_mar_event_returns_409(
    client, nurse_headers, mar_dup_setup, db_session
):
    """TC-5.1 — POST /mar-records with the same (tenant, participant, medication,
    scheduled_time) as an existing record returns 409 MAR_DUPLICATE_EVENT; DB
    count for that composite key remains 1."""
    p, nurse_user, first_mar = mar_dup_setup

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": first_mar["medication_name"],
        "administered_by": nurse_user["user_id"],
        "scheduled_time": first_mar["scheduled_time"],
        "status": "administered",
        "administered_time": first_mar["administered_time"],
    }, headers=nurse_headers))
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "MAR_DUPLICATE_EVENT"

    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM mar_record "
            "WHERE participant_id = :pid AND medication_name = :med"
        ),
        {"pid": p["participant_id"], "med": first_mar["medication_name"]},
    ).scalar()
    assert count == 1, (
        f"Expected exactly 1 MAR record after duplicate rejection, found {count}"
    )


# ─── TC-5.2 ──────────────────────────────────────────────────────────────────

def test_tc_5_2_successful_mar_creation_audit_trail(
    client, nurse_headers, mar_write_setup, db_session
):
    """TC-5.2 — POST /mar-records by nurse_medication_aide returns 201; DB stores
    created_by equal to the caller user_id; audit_log contains a PHI_WRITE entry
    with all 11 mandatory fields populated and no PHI values in data_affected."""
    p, nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    admin_time = (now - timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%S")
    h = {**nurse_headers, "X-Session-Id": "sess-tc52", "X-User-Id": NURSE_ID}

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Amlodipine 5mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "administered_time": admin_time,
        "status": "administered",
        "is_controlled_substance": False,
        "created_by": NURSE_ID,
    }, headers=h))
    assert r.status_code == 201, f"Expected 201, got {r.text}"
    mar_id = r.json()["mar_id"]

    # DB: created_by equals caller's user_id
    row_mar = db_session.execute(
        text("SELECT created_by, status, version FROM mar_record WHERE mar_id = :mid"),
        {"mid": mar_id},
    ).fetchone()
    assert row_mar is not None, f"MAR {mar_id} not found in DB"
    assert row_mar.created_by == NURSE_ID, (
        f"Expected created_by='{NURSE_ID}', got '{row_mar.created_by}'"
    )
    assert row_mar.status == "administered"
    assert row_mar.version == 1

    # Audit: PHI_WRITE entry with all 11 mandatory fields
    aud_rows = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'PHI_WRITE' AND resource_type = 'MARRecord' "
            "AND resource_id = :mid AND session_id = 'sess-tc52'"
        ),
        {"mid": mar_id},
    ).fetchall()
    assert len(aud_rows) >= 1, "PHI_WRITE audit entry not found for MAR creation"
    aud = aud_rows[0]
    _assert_audit_row(
        aud,
        action_type="PHI_WRITE",
        resource_type="MARRecord",
        resource_id=mar_id,
        outcome="SUCCESS",
        user_id=NURSE_ID,
        session_id="sess-tc52",
        tenant_id=TENANT_A,
    )

    # No PHI values in data_affected — only field names
    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list) and len(da) > 0
    da_str = str(da)
    for phi_val in ("Jane", "Doe", "1980"):
        assert phi_val not in da_str, (
            f"PHI value '{phi_val}' unexpectedly found in data_affected: {da_str}"
        )


# ─── TC-5.3 ──────────────────────────────────────────────────────────────────

def test_tc_5_3_billing_specialist_cannot_create_mar(
    client, billing_headers, mar_write_setup, db_session
):
    """TC-5.3 — POST /mar-records by billing_specialist returns 403 RBAC_DENIED;
    no MAR record is created in the DB."""
    p, nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    admin_time = (now - timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Warfarin 5mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "administered_time": admin_time,
        "status": "administered",
    }, headers=billing_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before, (
        f"No MAR should be created after 403 rejection: before={count_before}, after={count_after}"
    )


# ─── TC-5.4 ──────────────────────────────────────────────────────────────────

def test_tc_5_4_controlled_substance_read_denied_for_non_privileged_role(
    client, billing_headers, controlled_substance_mar_setup, db_session
):
    """TC-5.4 — GET /mar-records/<controlled-substance-id> by billing_specialist
    returns 403 SUD_ACCESS_DENIED; audit_log contains an ACCESS_DENIED entry with
    all 11 mandatory fields and outcome=DENIED."""
    _p, _nurse_user, cs_mar = controlled_substance_mar_setup
    mar_id = cs_mar["mar_id"]
    h = {**billing_headers, "X-Session-Id": "sess-tc54"}

    r = _call(lambda: client.get(f"/mar-records/{mar_id}", headers=h))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "SUD_ACCESS_DENIED"

    aud_rows = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'ACCESS_DENIED' AND resource_type = 'MARRecord' "
            "AND resource_id = :mid AND session_id = 'sess-tc54'"
        ),
        {"mid": mar_id},
    ).fetchall()
    assert len(aud_rows) >= 1, "ACCESS_DENIED audit entry not found for controlled-substance denial"
    aud = aud_rows[0]
    _assert_audit_row(
        aud,
        action_type="ACCESS_DENIED",
        resource_type="MARRecord",
        resource_id=mar_id,
        outcome="DENIED",
        user_id=BILLING_ID,
        session_id="sess-tc54",
        tenant_id=TENANT_A,
    )

    # No PHI in data_affected
    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list)
    da_str = str(da)
    for phi_val in ("Jane", "Doe", "Oxycodone"):
        assert phi_val not in da_str, (
            f"PHI value '{phi_val}' found in ACCESS_DENIED data_affected: {da_str}"
        )


# ─── TC-5.5 ──────────────────────────────────────────────────────────────────

def test_tc_5_5_administered_status_requires_administered_time(
    client, nurse_headers, mar_write_setup, db_session
):
    """TC-5.5 — POST /mar-records with status=administered and no administered_time
    returns 422 MAR_MISSING_ADMINISTERED_TIME; no MAR record is created."""
    p, nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Aspirin 81mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "status": "administered",
    }, headers=nurse_headers))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "MAR_MISSING_ADMINISTERED_TIME"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before, (
        "No MAR should be created when administered_time is missing"
    )


# ─── TC-5.6 ──────────────────────────────────────────────────────────────────

def test_tc_5_6_controlled_substance_read_allowed_for_privileged_role(
    client, nurse_headers, controlled_substance_mar_setup, db_session
):
    """TC-5.6 — GET /mar-records/<controlled-substance-id> by nurse_medication_aide
    (a privileged role) returns 200; audit_log contains a PHI_READ entry with all
    11 mandatory fields and outcome=SUCCESS."""
    _p, _nurse_user, cs_mar = controlled_substance_mar_setup
    mar_id = cs_mar["mar_id"]
    h = {**nurse_headers, "X-Session-Id": "sess-tc56"}

    r = _call(lambda: client.get(f"/mar-records/{mar_id}", headers=h))
    assert r.status_code == 200
    assert r.json()["mar_id"] == mar_id
    assert r.json()["is_controlled_substance"] is True

    aud_rows = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'PHI_READ' AND resource_type = 'MARRecord' "
            "AND resource_id = :mid AND session_id = 'sess-tc56'"
        ),
        {"mid": mar_id},
    ).fetchall()
    assert len(aud_rows) >= 1, "PHI_READ audit entry not found for privileged CS MAR read"
    aud = aud_rows[0]
    _assert_audit_row(
        aud,
        action_type="PHI_READ",
        resource_type="MARRecord",
        resource_id=mar_id,
        outcome="SUCCESS",
        user_id=NURSE_ID,
        session_id="sess-tc56",
        tenant_id=TENANT_A,
    )

    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list) and len(da) > 0


# ─── TC-5.7 ──────────────────────────────────────────────────────────────────

def test_tc_5_7_refused_status_requires_notes(
    client, nurse_headers, mar_write_setup, db_session
):
    """TC-5.7 — POST /mar-records with status=refused and no notes returns 422
    MAR_MISSING_NOTES; no MAR record is created."""
    p, nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Furosemide 20mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "status": "refused",
    }, headers=nurse_headers))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "MAR_MISSING_NOTES"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before


# ─── TC-5.8 ──────────────────────────────────────────────────────────────────

def test_tc_5_8_held_status_requires_notes(
    client, nurse_headers, mar_write_setup, db_session
):
    """TC-5.8 — POST /mar-records with status=held and no notes returns 422
    MAR_MISSING_NOTES; no MAR record is created."""
    p, nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Atorvastatin 10mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "status": "held",
    }, headers=nurse_headers))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "MAR_MISSING_NOTES"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before


# ─── TC-5.9 ──────────────────────────────────────────────────────────────────

def test_tc_5_9_future_administered_time_rejected(
    client, nurse_headers, mar_write_setup, db_session
):
    """TC-5.9 — POST /mar-records with administered_time in the future returns 422
    ADMIN_TIME_FUTURE; no MAR record is created."""
    p, nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    future_time = (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Metoprolol 25mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "administered_time": future_time,
        "status": "administered",
    }, headers=nurse_headers))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "ADMIN_TIME_FUTURE"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before


# ─── TC-5.10 ─────────────────────────────────────────────────────────────────

def test_tc_5_10_administered_time_too_early_rejected(
    client, nurse_headers, mar_write_setup, db_session
):
    """TC-5.10 — POST /mar-records with administered_time more than 2 hours before
    scheduled_time returns 422 ADMIN_TIME_TOO_EARLY; no MAR record is created."""
    p, nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    too_early = (now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Omeprazole 20mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "administered_time": too_early,
        "status": "administered",
    }, headers=nurse_headers))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "ADMIN_TIME_TOO_EARLY"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before


# ─── TC-5.11 ─────────────────────────────────────────────────────────────────

def test_tc_5_11_administered_by_must_be_nurse_role(
    client, nurse_headers, mar_write_setup, users, db_session
):
    """TC-5.11 — POST /mar-records where administered_by references a user with a
    role other than nurse_medication_aide returns 403; no MAR record is created."""
    p, _nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    admin_time = (now - timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%S")
    admin_user_id = users["admins"][0]["user_id"]

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Pantoprazole 40mg",
        "administered_by": admin_user_id,
        "scheduled_time": scheduled,
        "administered_time": admin_time,
        "status": "administered",
    }, headers=nurse_headers))
    assert r.status_code == 403, (
        f"Expected 403 when administered_by is a non-nurse user, got {r.status_code}"
    )
    assert "nurse_medication_aide" in r.json()["detail"]["message"] or \
           "role" in r.json()["detail"]["message"].lower()

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before


# ─── TC-5.12 ─────────────────────────────────────────────────────────────────

def test_tc_5_12_administered_by_user_not_found_rejected(
    client, nurse_headers, mar_write_setup, db_session
):
    """TC-5.12 — POST /mar-records where administered_by references a non-existent
    user_id returns 403; no MAR record is created."""
    p, _nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    admin_time = (now - timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%S")
    nonexistent_user = str(uuid.uuid4())

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Glipizide 5mg",
        "administered_by": nonexistent_user,
        "scheduled_time": scheduled,
        "administered_time": admin_time,
        "status": "administered",
    }, headers=nurse_headers))
    assert r.status_code in (403, 422), (
        f"Expected 403 or 422 when administered_by user does not exist, got {r.status_code}"
    )
    assert nonexistent_user in r.json()["detail"]["message"] or \
           "not found" in r.json()["detail"]["message"].lower()

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before


# ─── TC-5.13 ─────────────────────────────────────────────────────────────────

def test_tc_5_13_coordinator_cannot_create_mar(
    client, coordinator_headers, mar_write_setup, db_session
):
    """TC-5.13 — POST /mar-records by care_coordinator returns 403 RBAC_DENIED;
    no MAR record is created."""
    p, nurse_user = mar_write_setup
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    admin_time = (now - timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Simvastatin 20mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "administered_time": admin_time,
        "status": "administered",
    }, headers=coordinator_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before


# ─── TC-5.14 ─────────────────────────────────────────────────────────────────

def test_tc_5_14_administered_mar_is_immutable(
    client, nurse_headers, fresh_mar_record, db_session
):
    """TC-5.14 — PATCH /mar-records/<id> on a record with status=administered
    returns 422 MAR_ADMINISTERED_IMMUTABLE; DB version remains unchanged."""
    mar, _nurse_user, _p = fresh_mar_record
    mar_id = mar["mar_id"]
    original_version = mar["version"]

    r = _call(lambda: client.patch(
        f"/mar-records/{mar_id}",
        json={"version": original_version, "notes": "Attempted modification."},
        headers=nurse_headers,
    ))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "MAR_ADMINISTERED_IMMUTABLE"

    row = db_session.execute(
        text("SELECT version, status FROM mar_record WHERE mar_id = :mid"),
        {"mid": mar_id},
    ).fetchone()
    assert row is not None, f"MAR {mar_id} not found in DB"
    assert row.version == original_version, (
        f"Expected version={original_version} unchanged after rejected PATCH, got {row.version}"
    )
    assert row.status == "administered"


# ─── TC-5.15 ─────────────────────────────────────────────────────────────────

def test_tc_5_15_administered_mar_immutable_check_fires_before_version_check(
    client, nurse_headers, fresh_mar_record, db_session
):
    """TC-5.15 — PATCH /mar-records/<id> on an administered record with a stale
    version returns 422 MAR_ADMINISTERED_IMMUTABLE (not 409 MAR_VERSION_CONFLICT),
    confirming the immutability check fires before the version check."""
    mar, _nurse_user, _p = fresh_mar_record
    mar_id = mar["mar_id"]
    original_version = mar["version"]
    stale_version = original_version - 1

    r = _call(lambda: client.patch(
        f"/mar-records/{mar_id}",
        json={"version": stale_version, "notes": "Stale version on administered MAR."},
        headers=nurse_headers,
    ))
    assert r.status_code == 422, (
        "Administered immutability must fire before version check: expected 422, "
        f"got {r.status_code}"
    )
    assert r.json()["detail"]["error_code"] == "MAR_ADMINISTERED_IMMUTABLE", (
        "Immutability check must precede version check on administered records"
    )

    row = db_session.execute(
        text("SELECT version, status FROM mar_record WHERE mar_id = :mid"),
        {"mid": mar_id},
    ).fetchone()
    assert row.version == original_version
    assert row.status == "administered"


# ─── TC-5.16 ─────────────────────────────────────────────────────────────────

def test_tc_5_16_patch_notes_on_missed_mar_succeeds(
    client, nurse_headers, fresh_missed_mar, db_session
):
    """TC-5.16 — PATCH /mar-records/<id> updating notes on a missed MAR returns
    200; DB shows notes updated and version incremented."""
    mar, _nurse_user, _p = fresh_missed_mar
    mar_id = mar["mar_id"]
    original_version = mar["version"]
    new_notes = "Dose missed — patient in procedure room during scheduled time."

    r = _call(lambda: client.patch(
        f"/mar-records/{mar_id}",
        json={"version": original_version, "notes": new_notes},
        headers=nurse_headers,
    ))
    assert r.status_code == 200
    body = r.json()
    assert body["notes"] == new_notes
    assert body["version"] == original_version + 1
    assert body["status"] == "missed"

    row = db_session.execute(
        text("SELECT notes, version, status FROM mar_record WHERE mar_id = :mid"),
        {"mid": mar_id},
    ).fetchone()
    assert row is not None
    assert row.notes == new_notes
    assert row.version == original_version + 1
    assert row.status == "missed"


# ─── TC-5.17 ─────────────────────────────────────────────────────────────────

def test_tc_5_17_correction_mar_requires_original_mar_id(
    client, nurse_headers, fresh_missed_mar, db_session
):
    """TC-5.17 — POST /mar-records with is_correction=True but no original_mar_id
    returns 422 MAR_CORRECTION_MISSING_ORIGINAL; no MAR record is created."""
    mar, nurse_user, p = fresh_missed_mar
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Correction Metformin 500mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "status": "missed",
        "is_correction": True,
        "notes": "This is a correction note that is long enough to pass the minimum length check.",
    }, headers=nurse_headers))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "MAR_CORRECTION_MISSING_ORIGINAL"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before, (
        "No MAR should be created when original_mar_id is missing for a correction"
    )


# ─── TC-5.18 ─────────────────────────────────────────────────────────────────

def test_tc_5_18_correction_mar_requires_notes_min_20_chars(
    client, nurse_headers, fresh_missed_mar, db_session
):
    """TC-5.18 — POST /mar-records with is_correction=True and notes shorter than
    20 characters returns 422 MAR_CORRECTION_NOTES_TOO_SHORT; no MAR is created."""
    mar, nurse_user, p = fresh_missed_mar
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=5, minutes=45)).strftime("%Y-%m-%dT%H:%M:%S")

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Correction Metformin 500mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "status": "missed",
        "is_correction": True,
        "original_mar_id": mar["mar_id"],
        "notes": "Too short",
    }, headers=nurse_headers))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "MAR_CORRECTION_NOTES_TOO_SHORT"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM mar_record WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before


# ─── TC-5.19 ─────────────────────────────────────────────────────────────────

def test_tc_5_19_correction_mar_with_valid_fields_succeeds(
    client, nurse_headers, fresh_missed_mar, db_session
):
    """TC-5.19 — POST /mar-records with is_correction=True, a valid original_mar_id,
    and notes of at least 20 characters returns 201; DB stores is_correction=True
    and original_mar_id pointing to the original record."""
    mar, nurse_user, p = fresh_missed_mar
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=5, minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
    long_notes = "Correction for original missed dose — clinical override authorized by charge nurse."

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Corrected Metformin 500mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "status": "missed",
        "is_correction": True,
        "original_mar_id": mar["mar_id"],
        "notes": long_notes,
    }, headers=nurse_headers))
    assert r.status_code == 201, f"Expected 201 for valid correction MAR, got {r.text}"
    body = r.json()
    correction_mar_id = body["mar_id"]
    assert body["is_correction"] is True
    assert body["original_mar_id"] == mar["mar_id"]

    row = db_session.execute(
        text(
            "SELECT is_correction, original_mar_id, notes, status "
            "FROM mar_record WHERE mar_id = :mid"
        ),
        {"mid": correction_mar_id},
    ).fetchone()
    assert row is not None, f"Correction MAR {correction_mar_id} not found in DB"
    assert row.is_correction in (True, 1), "is_correction must be True in DB"
    assert row.original_mar_id == mar["mar_id"], (
        f"Expected original_mar_id='{mar['mar_id']}', got '{row.original_mar_id}'"
    )
    assert row.notes == long_notes
    assert row.status == "missed"


# ─── TC-5.20 ─────────────────────────────────────────────────────────────────

def test_tc_5_20_patch_missed_mar_status_transition_succeeds(
    client, nurse_headers, fresh_missed_mar, db_session
):
    """TC-5.20 — PATCH /mar-records/<id> changing status from missed to held on
    a non-administered MAR returns 200; DB reflects the new status and incremented
    version."""
    mar, _nurse_user, _p = fresh_missed_mar
    mar_id = mar["mar_id"]
    original_version = mar["version"]

    r = _call(lambda: client.patch(
        f"/mar-records/{mar_id}",
        json={
            "version": original_version,
            "status": "held",
            "notes": "Held per physician telephone order received prior to scheduled time.",
        },
        headers=nurse_headers,
    ))
    assert r.status_code == 200, f"Expected 200 for status transition patch, got {r.text}"
    body = r.json()
    assert body["status"] == "held"
    assert body["version"] == original_version + 1

    row = db_session.execute(
        text("SELECT status, version FROM mar_record WHERE mar_id = :mid"),
        {"mid": mar_id},
    ).fetchone()
    assert row is not None
    assert row.status == "held", f"Expected status='held' in DB, got '{row.status}'"
    assert row.version == original_version + 1


# ─── TC-5.21 ─────────────────────────────────────────────────────────────────

def test_tc_5_21_stale_version_on_missed_mar_returns_version_conflict(
    client, nurse_headers, mar_version_conflict_setup, db_session
):
    """TC-5.21 — PATCH /mar-records/<id> with a stale version on a missed MAR
    (current version=2) returns 409 MAR_VERSION_CONFLICT; DB version remains
    unchanged at 2."""
    mar_v2, _nurse_user, _p = mar_version_conflict_setup
    mar_id = mar_v2["mar_id"]
    current_version = mar_v2["version"]
    stale_version = current_version - 1

    r = _call(lambda: client.patch(
        f"/mar-records/{mar_id}",
        json={"version": stale_version, "notes": "Stale version attempt on missed MAR."},
        headers=nurse_headers,
    ))
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "MAR_VERSION_CONFLICT"

    row = db_session.execute(
        text("SELECT version, status FROM mar_record WHERE mar_id = :mid"),
        {"mid": mar_id},
    ).fetchone()
    assert row is not None
    assert row.version == current_version, (
        f"Expected version={current_version} unchanged after version conflict, "
        f"got {row.version}"
    )
    assert row.status == "missed"
