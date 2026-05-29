"""
test_incident.py — 15 tests mapped to TC-6.1 through TC-6.15.

Regulatory scope: HIPAA §164.308 / §164.312 · 42 CFR Part 2 (SUD incidents) ·
State adult day care incident-reporting regulations · OSHA recordkeeping.

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
  - Error codes asserted exactly: RBAC_DENIED, SUD_ACCESS_DENIED,
    INCIDENT_CLOSED_IMMUTABLE, INCIDENT_MISSING_REGULATORY_SUBMISSION,
    INCIDENT_VERSION_CONFLICT.
  - Auto-escalation: severity="severe" OR incident_type="medical_emergency"
    sets status="escalated" on creation.
  - SUD_PRIVILEGED_ROLES for incident: compliance_officer, care_coordinator,
    nurse_medication_aide, program_administrator.
  - Physicians and participant_family cannot read any incidents (RBAC_DENIED).
  - Closed incidents are immutable; the closed check fires before the version
    check (INCIDENT_CLOSED_IMMUTABLE precedes INCIDENT_VERSION_CONFLICT).
  - Job endpoint: GET /jobs/escalated-incidents-alert emits ESCALATION_ALERT
    audit entries for escalated incidents with created_at <= (now - 20h) and
    regulatory_submission_date IS NULL.
"""
import json as _json
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from sqlalchemy import text

from helpers import TENANT_A, ADMIN_ID, COORDINATOR_ID, BILLING_ID, PHYSICIAN_ID, make_headers


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
    assert row.action_type == action_type, (
        f"Expected action_type='{action_type}', got '{row.action_type}'"
    )
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


# ─── TC-6.1 ──────────────────────────────────────────────────────────────────

def test_tc_6_1_successful_incident_creation_audit_trail(
    client, admin_headers, fresh_participant, db_session
):
    """TC-6.1 — POST /incidents by program_administrator returns 201 with
    status=draft; audit_log contains a PHI_WRITE entry with all 11 mandatory
    fields populated and no PHI values in data_affected."""
    p = fresh_participant
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=1)).isoformat()
    h = {**admin_headers, "X-Session-Id": "sess-tc61", "X-User-Id": ADMIN_ID}

    r = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "incident_date": incident_date,
        "incident_type": "fall",
        "description": "Participant slipped near entrance — no injury observed.",
        "severity": "minor",
        "is_sud_related": False,
        "status": "draft",
        "created_by": ADMIN_ID,
    }, headers=h))
    assert r.status_code == 201, f"Expected 201, got {r.text}"
    body = r.json()
    incident_id = body["incident_id"]
    assert body["status"] == "draft"
    assert body["severity"] == "minor"

    # DB: record persisted correctly
    row_inc = db_session.execute(
        text(
            "SELECT status, severity, created_by, version "
            "FROM incident WHERE incident_id = :iid"
        ),
        {"iid": incident_id},
    ).fetchone()
    assert row_inc is not None, f"Incident {incident_id} not found in DB"
    assert row_inc.status == "draft"
    assert row_inc.severity == "minor"
    assert row_inc.created_by == ADMIN_ID
    assert row_inc.version == 1

    # Audit: PHI_WRITE with all 11 mandatory fields
    aud_rows = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'PHI_WRITE' AND resource_type = 'Incident' "
            "AND resource_id = :iid AND session_id = 'sess-tc61'"
        ),
        {"iid": incident_id},
    ).fetchall()
    assert len(aud_rows) >= 1, "PHI_WRITE audit entry not found for incident creation"
    aud = aud_rows[0]
    _assert_audit_row(
        aud,
        action_type="PHI_WRITE",
        resource_type="Incident",
        resource_id=incident_id,
        outcome="SUCCESS",
        user_id=ADMIN_ID,
        session_id="sess-tc61",
        tenant_id=TENANT_A,
    )

    # No PHI values in data_affected
    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list) and len(da) > 0
    da_str = str(da)
    for phi_val in ("Jane", "Doe", "1980"):
        assert phi_val not in da_str, (
            f"PHI value '{phi_val}' found in data_affected: {da_str}"
        )


# ─── TC-6.2 ──────────────────────────────────────────────────────────────────

def test_tc_6_2_admin_and_coordinator_can_create_incident(
    client, admin_headers, coordinator_headers, participants, db_session
):
    """TC-6.2 — POST /incidents succeeds for both program_administrator and
    care_coordinator; DB records created_by equal to the respective caller's
    user_id in each case."""
    p_a = participants["active"][0]
    p_b = participants["active"][1]
    today = datetime.now(timezone.utc).date()
    incident_date_a = (today - timedelta(days=2)).isoformat()
    incident_date_b = (today - timedelta(days=3)).isoformat()
    h_admin = {**admin_headers, "X-User-Id": ADMIN_ID}
    h_coord = {**coordinator_headers, "X-User-Id": COORDINATOR_ID}

    # Program administrator creates an incident
    r_admin = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": p_a["participant_id"],
        "incident_date": incident_date_a,
        "incident_type": "behavioral",
        "description": "Behavioral incident documented by program administrator.",
        "severity": "minor",
        "status": "draft",
        "created_by": ADMIN_ID,
    }, headers=h_admin))
    assert r_admin.status_code == 201, f"Admin incident creation failed: {r_admin.text}"
    inc_admin_id = r_admin.json()["incident_id"]

    # Care coordinator creates an incident
    r_coord = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": p_b["participant_id"],
        "incident_date": incident_date_b,
        "incident_type": "other",
        "description": "Incident documented by care coordinator on afternoon shift.",
        "severity": "minor",
        "status": "draft",
        "created_by": COORDINATOR_ID,
    }, headers=h_coord))
    assert r_coord.status_code == 201, f"Coordinator incident creation failed: {r_coord.text}"
    inc_coord_id = r_coord.json()["incident_id"]

    # DB: created_by matches respective caller
    row_admin = db_session.execute(
        text("SELECT created_by FROM incident WHERE incident_id = :iid"),
        {"iid": inc_admin_id},
    ).fetchone()
    assert row_admin is not None
    assert row_admin.created_by == ADMIN_ID, (
        f"Expected created_by='{ADMIN_ID}', got '{row_admin.created_by}'"
    )

    row_coord = db_session.execute(
        text("SELECT created_by FROM incident WHERE incident_id = :iid"),
        {"iid": inc_coord_id},
    ).fetchone()
    assert row_coord is not None
    assert row_coord.created_by == COORDINATOR_ID, (
        f"Expected created_by='{COORDINATOR_ID}', got '{row_coord.created_by}'"
    )


# ─── TC-6.3 ──────────────────────────────────────────────────────────────────

def test_tc_6_3_physician_cannot_create_incident(
    client, physician_headers, fresh_incident, db_session
):
    """TC-6.3 — POST /incidents by physician returns 403 RBAC_DENIED;
    no incident is created."""
    _inc, p = fresh_incident
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=4)).isoformat()

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM incident WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()

    r = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "incident_date": incident_date,
        "incident_type": "fall",
        "description": "Physician cannot report incidents.",
        "severity": "minor",
        "status": "draft",
    }, headers=physician_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM incident WHERE participant_id = :pid"),
        {"pid": p["participant_id"]},
    ).scalar()
    assert count_after == count_before, (
        f"No incident should be created after 403 rejection: before={count_before}, after={count_after}"
    )


# ─── TC-6.4 ──────────────────────────────────────────────────────────────────

def test_tc_6_4_physician_cannot_read_any_incident(
    client, physician_headers, fresh_incident_sud, db_session
):
    """TC-6.4 — GET /incidents/<id> by physician returns 403 RBAC_DENIED; the
    denial is logged with action_type=ACCESS_DENIED and outcome=DENIED in the
    audit_log regardless of whether the incident is SUD-related."""
    inc, _p = fresh_incident_sud
    incident_id = inc["incident_id"]
    h = {**physician_headers, "X-Session-Id": "sess-tc64", "X-User-Id": PHYSICIAN_ID}

    r = _call(lambda: client.get(f"/incidents/{incident_id}", headers=h))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    aud_rows = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'ACCESS_DENIED' AND resource_type = 'Incident' "
            "AND resource_id = :iid AND session_id = 'sess-tc64'"
        ),
        {"iid": incident_id},
    ).fetchall()
    assert len(aud_rows) >= 1, "ACCESS_DENIED audit entry not found for physician denial"
    aud = aud_rows[0]
    _assert_audit_row(
        aud,
        action_type="ACCESS_DENIED",
        resource_type="Incident",
        resource_id=incident_id,
        outcome="DENIED",
        user_id=PHYSICIAN_ID,
        session_id="sess-tc64",
    )

    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list)


# ─── TC-6.5 ──────────────────────────────────────────────────────────────────

def test_tc_6_5_billing_specialist_read_sud_incident_denied_with_audit(
    client, billing_headers, fresh_incident_sud, db_session
):
    """TC-6.5 — GET /incidents/<id> on a SUD-related incident by billing_specialist
    returns 403 SUD_ACCESS_DENIED; audit_log contains an ACCESS_DENIED entry with
    all 11 mandatory fields and outcome=DENIED."""
    inc, _p = fresh_incident_sud
    incident_id = inc["incident_id"]
    h = {**billing_headers, "X-Session-Id": "sess-tc65", "X-User-Id": BILLING_ID}

    r = _call(lambda: client.get(f"/incidents/{incident_id}", headers=h))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "SUD_ACCESS_DENIED"

    aud_rows = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'ACCESS_DENIED' AND resource_type = 'Incident' "
            "AND resource_id = :iid AND session_id = 'sess-tc65'"
        ),
        {"iid": incident_id},
    ).fetchall()
    assert len(aud_rows) >= 1, "ACCESS_DENIED audit entry not found for SUD incident denial"
    aud = aud_rows[0]
    _assert_audit_row(
        aud,
        action_type="ACCESS_DENIED",
        resource_type="Incident",
        resource_id=incident_id,
        outcome="DENIED",
        user_id=BILLING_ID,
        session_id="sess-tc65",
        tenant_id=TENANT_A,
    )

    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list)
    da_str = str(da)
    for phi_val in ("Jane", "Doe"):
        assert phi_val not in da_str, (
            f"PHI value '{phi_val}' found in ACCESS_DENIED data_affected: {da_str}"
        )


# ─── TC-6.6 ──────────────────────────────────────────────────────────────────

def test_tc_6_6_medical_emergency_incident_auto_escalates(
    client, admin_headers, fresh_participant, db_session
):
    """TC-6.6 — POST /incidents with incident_type=medical_emergency automatically
    sets status=escalated regardless of the submitted status value; DB reflects
    the escalated status."""
    p = fresh_participant
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=5)).isoformat()

    r = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "incident_date": incident_date,
        "incident_type": "medical_emergency",
        "description": "Participant experienced acute respiratory distress requiring 911 call.",
        "severity": "moderate",
        "status": "draft",
    }, headers=admin_headers))
    assert r.status_code == 201, f"Expected 201, got {r.text}"
    body = r.json()
    incident_id = body["incident_id"]
    assert body["status"] == "escalated", (
        f"medical_emergency must auto-escalate; expected 'escalated', got '{body['status']}'"
    )

    row = db_session.execute(
        text("SELECT status, incident_type FROM incident WHERE incident_id = :iid"),
        {"iid": incident_id},
    ).fetchone()
    assert row is not None
    assert row.status == "escalated", (
        f"Expected DB status='escalated' for medical_emergency, got '{row.status}'"
    )
    assert row.incident_type == "medical_emergency"


# ─── TC-6.7 ──────────────────────────────────────────────────────────────────

def test_tc_6_7_coordinator_can_read_sud_incident(
    client, coordinator_headers, fresh_incident_sud, db_session
):
    """TC-6.7 — GET /incidents/<id> on a SUD-related incident by care_coordinator
    (a SUD-privileged role) returns 200; audit_log contains a PHI_READ entry with
    all 11 mandatory fields and outcome=SUCCESS."""
    inc, _p = fresh_incident_sud
    incident_id = inc["incident_id"]
    h = {**coordinator_headers, "X-Session-Id": "sess-tc67", "X-User-Id": COORDINATOR_ID}

    r = _call(lambda: client.get(f"/incidents/{incident_id}", headers=h))
    assert r.status_code == 200, f"Expected 200 for coordinator reading SUD incident, got {r.text}"
    assert r.json()["incident_id"] == incident_id
    assert r.json()["is_sud_related"] is True

    aud_rows = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'PHI_READ' AND resource_type = 'Incident' "
            "AND resource_id = :iid AND session_id = 'sess-tc67'"
        ),
        {"iid": incident_id},
    ).fetchall()
    assert len(aud_rows) >= 1, "PHI_READ audit entry not found for coordinator SUD incident read"
    aud = aud_rows[0]
    _assert_audit_row(
        aud,
        action_type="PHI_READ",
        resource_type="Incident",
        resource_id=incident_id,
        outcome="SUCCESS",
        user_id=COORDINATOR_ID,
        session_id="sess-tc67",
        tenant_id=TENANT_A,
    )

    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list) and len(da) > 0


# ─── TC-6.8 ──────────────────────────────────────────────────────────────────

def test_tc_6_8_closed_incident_is_immutable(
    client, admin_headers, fresh_incident_closed, db_session
):
    """TC-6.8 — PATCH /incidents/<id> on a closed incident returns 422
    INCIDENT_CLOSED_IMMUTABLE; DB version and status remain unchanged."""
    inc, _p = fresh_incident_closed
    incident_id = inc["incident_id"]
    closed_version = inc["version"]

    r = _call(lambda: client.patch(
        f"/incidents/{incident_id}",
        json={"version": closed_version, "location": "Updated location"},
        headers=admin_headers,
    ))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "INCIDENT_CLOSED_IMMUTABLE"

    row = db_session.execute(
        text("SELECT status, version FROM incident WHERE incident_id = :iid"),
        {"iid": incident_id},
    ).fetchone()
    assert row is not None
    assert row.status == "closed"
    assert row.version == closed_version, (
        f"Expected version={closed_version} unchanged after rejected PATCH, got {row.version}"
    )


# ─── TC-6.9 ──────────────────────────────────────────────────────────────────

def test_tc_6_9_severe_incident_auto_escalates(
    client, fresh_incident_escalated, db_session
):
    """TC-6.9 — POST /incidents with severity=severe automatically sets
    status=escalated on creation; DB confirms escalated status and severe
    severity."""
    inc, _p = fresh_incident_escalated
    incident_id = inc["incident_id"]

    assert inc["status"] == "escalated", (
        f"Severe incident must auto-escalate; API response status='{inc['status']}'"
    )
    assert inc["severity"] == "severe"

    row = db_session.execute(
        text("SELECT status, severity FROM incident WHERE incident_id = :iid"),
        {"iid": incident_id},
    ).fetchone()
    assert row is not None, f"Incident {incident_id} not found in DB"
    assert row.status == "escalated", (
        f"Expected DB status='escalated' for severe incident, got '{row.status}'"
    )
    assert row.severity == "severe"


# ─── TC-6.10 ─────────────────────────────────────────────────────────────────

def test_tc_6_10_escalation_alert_job_emits_escalation_alert_audit(
    client, overdue_escalated_incident_setup, db_session
):
    """TC-6.10 — GET /jobs/escalated-incidents-alert returns the incident that has
    status=escalated, created_at <= (now - 20h), and regulatory_submission_date IS
    NULL; audit_log contains an ESCALATION_ALERT entry for that incident with all
    11 mandatory fields."""
    inc, _p = overdue_escalated_incident_setup
    incident_id = inc["incident_id"]

    r = _call(lambda: client.get("/jobs/escalated-incidents-alert"))
    assert r.status_code == 200
    alerted = r.json()["alerted"]
    assert incident_id in alerted, (
        f"Expected incident {incident_id} in job alerted list, got {alerted}"
    )

    aud_rows = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'ESCALATION_ALERT' AND resource_type = 'Incident' "
            "AND resource_id = :iid"
        ),
        {"iid": incident_id},
    ).fetchall()
    assert len(aud_rows) >= 1, (
        f"ESCALATION_ALERT audit entry not found for incident {incident_id}"
    )
    aud = aud_rows[0]
    _assert_audit_row(
        aud,
        action_type="ESCALATION_ALERT",
        resource_type="Incident",
        resource_id=incident_id,
        outcome="SUCCESS",
    )
    assert aud.user_id == "system"
    assert aud.session_id == "sess_job"

    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list) and len(da) > 0
    da_str = str(da)
    for phi_val in ("Jane", "Doe"):
        assert phi_val not in da_str, (
            f"PHI value '{phi_val}' found in ESCALATION_ALERT data_affected: {da_str}"
        )


# ─── TC-6.11 ─────────────────────────────────────────────────────────────────

def test_tc_6_11_addendum_incident_links_to_original_incident(
    client, admin_headers, fresh_incident_open, db_session
):
    """TC-6.11 — POST /incidents with incident_type=addendum and a valid
    original_incident_id returns 201; DB stores original_incident_id referencing
    the base incident."""
    base_inc, p = fresh_incident_open
    original_id = base_inc["incident_id"]
    today = datetime.now(timezone.utc).date()
    addendum_date = (today - timedelta(days=6)).isoformat()

    r = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "incident_date": addendum_date,
        "incident_type": "addendum",
        "description": "Addendum: witness statement obtained after initial report — no additional injuries.",
        "severity": "minor",
        "status": "draft",
        "original_incident_id": original_id,
    }, headers=admin_headers))
    assert r.status_code == 201, f"Expected 201 for addendum incident, got {r.text}"
    body = r.json()
    addendum_id = body["incident_id"]
    assert body["incident_type"] == "addendum"
    assert body["original_incident_id"] == original_id

    row = db_session.execute(
        text(
            "SELECT incident_type, original_incident_id, status "
            "FROM incident WHERE incident_id = :iid"
        ),
        {"iid": addendum_id},
    ).fetchone()
    assert row is not None, f"Addendum incident {addendum_id} not found in DB"
    assert row.incident_type == "addendum"
    assert row.original_incident_id == original_id, (
        f"Expected original_incident_id='{original_id}', got '{row.original_incident_id}'"
    )
    assert row.status == "draft"


# ─── TC-6.12 ─────────────────────────────────────────────────────────────────

def test_tc_6_12_closed_incident_immutable_check_fires_before_version_check(
    client, admin_headers, fresh_incident_closed, db_session
):
    """TC-6.12 — PATCH /incidents/<id> on a closed incident with a stale version
    returns 422 INCIDENT_CLOSED_IMMUTABLE (not 409 INCIDENT_VERSION_CONFLICT),
    confirming the closed-immutability check fires before the version check."""
    inc, _p = fresh_incident_closed
    incident_id = inc["incident_id"]
    closed_version = inc["version"]
    stale_version = closed_version - 1

    r = _call(lambda: client.patch(
        f"/incidents/{incident_id}",
        json={"version": stale_version, "description": "Stale version on closed incident."},
        headers=admin_headers,
    ))
    assert r.status_code == 422, (
        "Closed immutability must fire before version check: expected 422, "
        f"got {r.status_code}"
    )
    assert r.json()["detail"]["error_code"] == "INCIDENT_CLOSED_IMMUTABLE", (
        "INCIDENT_CLOSED_IMMUTABLE must precede INCIDENT_VERSION_CONFLICT"
    )

    row = db_session.execute(
        text("SELECT status, version FROM incident WHERE incident_id = :iid"),
        {"iid": incident_id},
    ).fetchone()
    assert row.status == "closed"
    assert row.version == closed_version


# ─── TC-6.13 ─────────────────────────────────────────────────────────────────

def test_tc_6_13_escalated_to_closed_requires_regulatory_submission_date(
    client, admin_headers, fresh_incident_escalated, db_session
):
    """TC-6.13 — PATCH /incidents/<id> attempting to transition an escalated
    incident to closed without providing regulatory_submission_date returns 422
    INCIDENT_MISSING_REGULATORY_SUBMISSION; DB status remains escalated."""
    inc, _p = fresh_incident_escalated
    incident_id = inc["incident_id"]
    escalated_version = inc["version"]

    assert inc["status"] == "escalated", (
        f"Pre-condition: incident must be escalated; got '{inc['status']}'"
    )

    r = _call(lambda: client.patch(
        f"/incidents/{incident_id}",
        json={"version": escalated_version, "status": "closed"},
        headers=admin_headers,
    ))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "INCIDENT_MISSING_REGULATORY_SUBMISSION"

    row = db_session.execute(
        text("SELECT status, version FROM incident WHERE incident_id = :iid"),
        {"iid": incident_id},
    ).fetchone()
    assert row is not None
    assert row.status == "escalated", (
        f"Expected DB status='escalated' unchanged after rejected PATCH, got '{row.status}'"
    )
    assert row.version == escalated_version


# ─── TC-6.14 ─────────────────────────────────────────────────────────────────

def test_tc_6_14_stale_version_on_incident_returns_version_conflict(
    client, admin_headers, incident_version3_setup, db_session
):
    """TC-6.14 — PATCH /incidents/<id> with a stale version on a non-closed
    incident (current version=3) returns 409 INCIDENT_VERSION_CONFLICT; DB version
    remains unchanged at 3."""
    inc_v3, _p = incident_version3_setup
    incident_id = inc_v3["incident_id"]
    current_version = inc_v3["version"]
    stale_version = current_version - 1

    r = _call(lambda: client.patch(
        f"/incidents/{incident_id}",
        json={"version": stale_version, "location": "Stale version attempt"},
        headers=admin_headers,
    ))
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "INCIDENT_VERSION_CONFLICT"

    row = db_session.execute(
        text("SELECT version, status FROM incident WHERE incident_id = :iid"),
        {"iid": incident_id},
    ).fetchone()
    assert row is not None
    assert row.version == current_version, (
        f"Expected version={current_version} unchanged after version conflict, "
        f"got {row.version}"
    )
    assert row.status == "draft"


# ─── TC-6.15 ─────────────────────────────────────────────────────────────────

def test_tc_6_15_closed_incident_patch_any_field_returns_immutable(
    client, admin_headers, fresh_incident_closed, db_session
):
    """TC-6.15 — PATCH /incidents/<id> on a closed incident attempting to change
    description (non-status field) with the correct version returns 422
    INCIDENT_CLOSED_IMMUTABLE; DB description and version remain unchanged."""
    inc, _p = fresh_incident_closed
    incident_id = inc["incident_id"]
    closed_version = inc["version"]

    r = _call(lambda: client.patch(
        f"/incidents/{incident_id}",
        json={
            "version": closed_version,
            "description": "Attempted description update on closed incident.",
        },
        headers=admin_headers,
    ))
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "INCIDENT_CLOSED_IMMUTABLE"

    row = db_session.execute(
        text("SELECT status, version, description FROM incident WHERE incident_id = :iid"),
        {"iid": incident_id},
    ).fetchone()
    assert row is not None
    assert row.status == "closed"
    assert row.version == closed_version, (
        f"Expected version={closed_version} unchanged, got {row.version}"
    )
    assert "Attempted description update" not in (row.description or ""), (
        "Description must not be modified on a closed incident"
    )
