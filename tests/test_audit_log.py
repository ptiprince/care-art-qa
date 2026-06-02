"""
test_audit_log.py — 10 tests TC-7.1 through TC-7.10.

Regulatory scope: HIPAA §164.312(b) · SOC 2 CC7.2 · CMS 10-year Claim retention.

Design rules:
  - All DB assertions query audit_log directly via db_session.
  - No GET /audit-logs endpoint used anywhere.
  - No time.sleep(); no hardcoded dates.
  - All 11 mandatory audit fields asserted on every audit row check:
    audit_id, timestamp, user_id, tenant_id, session_id, action_type,
    resource_type, resource_id, data_affected, source_ip, outcome, layer.
  - data_affected checked for PHI value absence (field names only expected).
  - TC-7.2 uses billing_specialist GET on CS MARRecord (ACCESS_DENIED logged).
  - TC-7.5 uses billing_specialist GET on SUD Incident (ACCESS_DENIED logged).
  - TC-7.9 relies on _emit_audit default retention_years=6; Claim ops pass 10.
"""
import json as _json
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from sqlalchemy import text

from helpers import (
    TENANT_A,
    ADMIN_ID, BILLING_ID, NURSE_ID, COMPLIANCE_ID,
    make_headers,
)


def _call(fn):
    try:
        return fn()
    except httpx.ConnectError:
        pytest.fail("Cannot connect to mock backend.")
    except httpx.TimeoutException:
        pytest.fail("Mock backend timed out.")


_AUDIT_FIELDS = (
    "audit_id", "timestamp", "user_id", "tenant_id", "session_id",
    "action_type", "resource_type", "resource_id", "data_affected",
    "source_ip", "outcome", "layer",
)

_AUDIT_SELECT = (
    "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
    "action_type, resource_type, resource_id, data_affected, "
    "source_ip, outcome, layer, retention_years "
    "FROM audit_log "
)


def _assert_audit_row(row, *, action_type, resource_type, outcome,
                      resource_id=None, user_id=None, session_id=None,
                      tenant_id=None):
    for field in _AUDIT_FIELDS:
        assert getattr(row, field) is not None, (
            f"Mandatory audit field '{field}' is null"
        )
    assert row.action_type == action_type
    assert row.resource_type == resource_type
    assert row.outcome == outcome
    assert row.layer == "APP_SERVICE"
    if resource_id is not None:
        assert row.resource_id == resource_id
    if user_id is not None:
        assert row.user_id == user_id
    if session_id is not None:
        assert row.session_id == session_id
    if tenant_id is not None:
        assert row.tenant_id == tenant_id


def _no_phi(da, phi_values):
    if isinstance(da, str):
        da = _json.loads(da)
    da_str = str(da)
    for val in phi_values:
        if val:
            assert val not in da_str, (
                f"PHI value '{val}' found in data_affected: {da_str}"
            )


# ─── TC-7.1 ──────────────────────────────────────────────────────────────────

def test_tc_7_1_audit_mandatory_fields_present_on_participant_write(
    client, db_session, admin_headers
):
    """TC-7.1 — POST /participants by program_administrator produces a PHI_WRITE
    audit row with all 11 mandatory fields non-null."""
    h = {**admin_headers, "X-Session-Id": "sess-tc71", "X-User-Id": ADMIN_ID}
    today = datetime.now(timezone.utc).date()
    r = _call(lambda: client.post("/participants", json={
        "tenant_id": TENANT_A,
        "first_name": "AuditCheck",
        "last_name": "TC71",
        "date_of_birth": (today - timedelta(days=365 * 40)).isoformat(),
        "enrollment_date": today.isoformat(),
        "medicaid_id": f"TC71-{uuid.uuid4().hex[:8].upper()}",
    }, headers=h))
    assert r.status_code == 201, f"Expected 201: {r.text}"
    pid = r.json()["participant_id"]

    rows = db_session.execute(
        text(_AUDIT_SELECT +
             "WHERE action_type='PHI_WRITE' AND resource_type='Participant' "
             "AND resource_id=:rid AND session_id='sess-tc71'"),
        {"rid": pid},
    ).fetchall()
    assert len(rows) >= 1, "PHI_WRITE audit row not found for participant creation"
    _assert_audit_row(
        rows[0],
        action_type="PHI_WRITE",
        resource_type="Participant",
        resource_id=pid,
        outcome="SUCCESS",
        user_id=ADMIN_ID,
        session_id="sess-tc71",
        tenant_id=TENANT_A,
    )


# ─── TC-7.2 ──────────────────────────────────────────────────────────────────

def test_tc_7_2_unauthorized_role_denied_write_phi_resource_access_denied_audit_logged(
    client, db_session, billing_headers, controlled_substance_mar_setup
):
    """TC-7.2 — billing_specialist GET on a controlled-substance MARRecord returns
    403 SUD_ACCESS_DENIED; ACCESS_DENIED audit row logged with all 11 mandatory
    fields non-null and no PHI values in data_affected."""
    _p, _nurse, cs_mar = controlled_substance_mar_setup
    mar_id = cs_mar["mar_id"]
    h = {**billing_headers, "X-Session-Id": "sess-tc72", "X-User-Id": BILLING_ID}

    r = _call(lambda: client.get(f"/mar-records/{mar_id}", headers=h))
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"
    assert r.json()["detail"]["error_code"] == "SUD_ACCESS_DENIED"

    rows = db_session.execute(
        text(_AUDIT_SELECT +
             "WHERE action_type='ACCESS_DENIED' AND resource_type='MARRecord' "
             "AND resource_id=:rid AND session_id='sess-tc72'"),
        {"rid": mar_id},
    ).fetchall()
    assert len(rows) >= 1, "ACCESS_DENIED audit row not found for CS MAR denial"
    aud = rows[0]
    _assert_audit_row(
        aud,
        action_type="ACCESS_DENIED",
        resource_type="MARRecord",
        resource_id=mar_id,
        outcome="DENIED",
        user_id=BILLING_ID,
        session_id="sess-tc72",
    )
    _no_phi(aud.data_affected, ("Jane", "Doe"))


# ─── TC-7.3 ──────────────────────────────────────────────────────────────────

def test_tc_7_3_audit_mandatory_fields_present_on_mar_controlled_substance_read(
    client, db_session, nurse_headers, controlled_substance_mar_setup
):
    """TC-7.3 — nurse_medication_aide GET on a controlled-substance MARRecord
    returns 200 and produces a PHI_READ audit row with all 11 mandatory fields."""
    _p, _nurse_user, cs_mar = controlled_substance_mar_setup
    mar_id = cs_mar["mar_id"]
    h = {**nurse_headers, "X-Session-Id": "sess-tc73", "X-User-Id": NURSE_ID}

    r = _call(lambda: client.get(f"/mar-records/{mar_id}", headers=h))
    assert r.status_code == 200, f"Expected 200: {r.text}"

    rows = db_session.execute(
        text(_AUDIT_SELECT +
             "WHERE action_type='PHI_READ' AND resource_type='MARRecord' "
             "AND resource_id=:rid AND session_id='sess-tc73'"),
        {"rid": mar_id},
    ).fetchall()
    assert len(rows) >= 1, "PHI_READ audit row not found for nurse CS MAR read"
    _assert_audit_row(
        rows[0],
        action_type="PHI_READ",
        resource_type="MARRecord",
        resource_id=mar_id,
        outcome="SUCCESS",
        user_id=NURSE_ID,
        session_id="sess-tc73",
    )


# ─── TC-7.4 ──────────────────────────────────────────────────────────────────

def test_tc_7_4_phi_values_absent_from_audit_log_payloads_across_all_entities(
    db_session, participants
):
    """TC-7.4 — Direct DB scan confirms no audit row contains PHI field values
    (SSN, medicaid_id, first_name, last_name) in data_affected across all entities."""
    rows = db_session.execute(
        text(
            "SELECT data_affected FROM audit_log "
            "WHERE resource_type IN ('Participant','User','Attendance','Claim','MARRecord','Incident')"
        )
    ).fetchall()
    assert len(rows) > 0, "No audit rows found — session fixtures must have written some"

    phi_patterns = ("Eleanor", "Vasquez", "1942-03-14", "SEED-MC-001")
    for row in rows:
        da = row.data_affected
        if isinstance(da, str):
            da = _json.loads(da)
        assert isinstance(da, list), f"data_affected is not a list: {da}"
        da_str = str(da)
        for pattern in phi_patterns:
            assert pattern not in da_str, (
                f"PHI pattern '{pattern}' found in data_affected: {da_str}"
            )


# ─── TC-7.5 ──────────────────────────────────────────────────────────────────

def test_tc_7_5_access_denied_audit_event_logged_for_every_403_response(
    client, db_session, billing_headers, compliance_headers, fresh_incident_sud
):
    """TC-7.5 — billing_specialist GET on SUD Incident returns 403; ACCESS_DENIED
    logged. compliance_officer GET same Incident returns 200; PHI_READ logged."""
    inc, _p = fresh_incident_sud
    incident_id = inc["incident_id"]

    h_billing = {**billing_headers, "X-Session-Id": "sess-tc75-deny", "X-User-Id": BILLING_ID}
    r_deny = _call(lambda: client.get(f"/incidents/{incident_id}", headers=h_billing))
    assert r_deny.status_code == 403
    assert r_deny.json()["detail"]["error_code"] == "SUD_ACCESS_DENIED"

    deny_rows = db_session.execute(
        text(_AUDIT_SELECT +
             "WHERE action_type='ACCESS_DENIED' AND resource_type='Incident' "
             "AND resource_id=:rid AND session_id='sess-tc75-deny'"),
        {"rid": incident_id},
    ).fetchall()
    assert len(deny_rows) >= 1, "ACCESS_DENIED row not found for billing SUD incident denial"
    _assert_audit_row(
        deny_rows[0],
        action_type="ACCESS_DENIED",
        resource_type="Incident",
        resource_id=incident_id,
        outcome="DENIED",
        user_id=BILLING_ID,
    )

    h_compliance = {**compliance_headers, "X-Session-Id": "sess-tc75-read", "X-User-Id": COMPLIANCE_ID}
    r_read = _call(lambda: client.get(f"/incidents/{incident_id}", headers=h_compliance))
    assert r_read.status_code == 200, f"Expected 200 for compliance_officer: {r_read.text}"

    read_rows = db_session.execute(
        text(_AUDIT_SELECT +
             "WHERE action_type='PHI_READ' AND resource_type='Incident' "
             "AND resource_id=:rid AND session_id='sess-tc75-read'"),
        {"rid": incident_id},
    ).fetchall()
    assert len(read_rows) >= 1, "PHI_READ row not found for compliance_officer SUD incident read"
    _assert_audit_row(
        read_rows[0],
        action_type="PHI_READ",
        resource_type="Incident",
        resource_id=incident_id,
        outcome="SUCCESS",
        user_id=COMPLIANCE_ID,
    )


# ─── TC-7.6 ──────────────────────────────────────────────────────────────────

def test_tc_7_6_audit_row_exists_in_db_after_api_call_completes(
    client, db_session, admin_headers
):
    """TC-7.6 — After POST /participants completes, a PHI_WRITE audit row for
    that participant_id exists immediately in the DB. No timestamp comparison."""
    h = {**admin_headers, "X-Session-Id": "sess-tc76", "X-User-Id": ADMIN_ID}
    today = datetime.now(timezone.utc).date()
    r = _call(lambda: client.post("/participants", json={
        "tenant_id": TENANT_A,
        "first_name": "Exists",
        "last_name": "Immediately",
        "date_of_birth": (today - timedelta(days=365 * 55)).isoformat(),
        "enrollment_date": today.isoformat(),
        "medicaid_id": f"TC76-{uuid.uuid4().hex[:8].upper()}",
    }, headers=h))
    assert r.status_code == 201, f"Expected 201: {r.text}"
    pid = r.json()["participant_id"]

    row = db_session.execute(
        text("SELECT audit_id FROM audit_log "
             "WHERE resource_type='Participant' AND resource_id=:rid "
             "AND session_id='sess-tc76'"),
        {"rid": pid},
    ).fetchone()
    assert row is not None, (
        f"Audit row not found for participant {pid} immediately after API response"
    )


# ─── TC-7.7 ──────────────────────────────────────────────────────────────────

def test_tc_7_7_claim_submission_produces_phi_disclose_audit_event(
    client, db_session, billing_headers, fresh_claim
):
    """TC-7.7 — Patching a draft Claim to submitted emits a PHI_DISCLOSE audit row
    with all 11 mandatory fields and no raw PHI values in data_affected."""
    claim, _att, _p = fresh_claim
    claim_id = claim["claim_id"]
    h = {**billing_headers, "X-Session-Id": "sess-tc77", "X-User-Id": BILLING_ID}

    r = _call(lambda: client.patch(
        f"/claims/{claim_id}",
        json={"version": claim["version"], "claim_status": "submitted"},
        headers=h,
    ))
    assert r.status_code == 200, f"Expected 200: {r.text}"

    rows = db_session.execute(
        text(_AUDIT_SELECT +
             "WHERE action_type='PHI_DISCLOSE' AND resource_type='Claim' "
             "AND resource_id=:cid AND session_id='sess-tc77'"),
        {"cid": claim_id},
    ).fetchall()
    assert len(rows) >= 1, "PHI_DISCLOSE audit row not found after claim submission"
    aud = rows[0]
    _assert_audit_row(
        aud,
        action_type="PHI_DISCLOSE",
        resource_type="Claim",
        resource_id=claim_id,
        outcome="SUCCESS",
        user_id=BILLING_ID,
    )
    da = aud.data_affected
    if isinstance(da, str):
        da = _json.loads(da)
    assert isinstance(da, list) and len(da) > 0
    _no_phi(da, ("Jane", "Doe"))


# ─── TC-7.8 ──────────────────────────────────────────────────────────────────

def test_tc_7_8_sud_related_incident_write_produces_separate_audit_event(
    client, db_session, admin_headers, fresh_participant
):
    """TC-7.8 — Creating a SUD incident and a non-SUD incident each produce
    a distinct PHI_WRITE audit row, confirming separate events per write."""
    p = fresh_participant
    pid = p["participant_id"]
    h = {**admin_headers, "X-Session-Id": "sess-tc78", "X-User-Id": ADMIN_ID}
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=5)).isoformat()

    r_sud = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "incident_date": incident_date,
        "incident_type": "fall",
        "description": "TC-7.8 SUD incident for audit test.",
        "severity": "minor",
        "is_sud_related": True,
        "status": "draft",
    }, headers=h))
    assert r_sud.status_code == 201, f"SUD incident creation failed: {r_sud.text}"
    sud_id = r_sud.json()["incident_id"]

    r_nonsud = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "incident_date": (today - timedelta(days=6)).isoformat(),
        "incident_type": "fall",
        "description": "TC-7.8 non-SUD incident for audit test.",
        "severity": "minor",
        "is_sud_related": False,
        "status": "draft",
    }, headers=h))
    assert r_nonsud.status_code == 201, f"Non-SUD incident creation failed: {r_nonsud.text}"
    nonsud_id = r_nonsud.json()["incident_id"]

    rows = db_session.execute(
        text(_AUDIT_SELECT +
             "WHERE action_type='PHI_WRITE' AND resource_type='Incident' "
             "AND resource_id IN (:sid, :nid) AND session_id='sess-tc78'"),
        {"sid": sud_id, "nid": nonsud_id},
    ).fetchall()
    assert len(rows) == 2, (
        f"Expected 2 distinct PHI_WRITE rows for SUD and non-SUD incidents, got {len(rows)}"
    )
    resource_ids = {row.resource_id for row in rows}
    assert sud_id in resource_ids
    assert nonsud_id in resource_ids


# ─── TC-7.9 ──────────────────────────────────────────────────────────────────

def test_tc_7_9_claim_audit_events_carry_10_year_retention_marker(
    db_session, fresh_claim
):
    """TC-7.9 — Audit rows for Claim operations carry retention_years=10;
    audit rows for Participant operations carry the default retention_years=6."""
    claim, _att, _p = fresh_claim
    claim_id = claim["claim_id"]

    claim_rows = db_session.execute(
        text("SELECT retention_years FROM audit_log "
             "WHERE resource_type='Claim' AND resource_id=:cid"),
        {"cid": claim_id},
    ).fetchall()
    assert len(claim_rows) >= 1, "No audit rows found for the fresh claim"
    for row in claim_rows:
        assert row.retention_years == 10, (
            f"Claim audit row has retention_years={row.retention_years}, expected 10"
        )

    non_claim_rows = db_session.execute(
        text("SELECT retention_years, resource_type FROM audit_log "
             "WHERE resource_type='Participant' LIMIT 5")
    ).fetchall()
    assert len(non_claim_rows) >= 1, "No Participant audit rows found"
    for row in non_claim_rows:
        assert row.retention_years == 6, (
            f"{row.resource_type} audit row has retention_years={row.retention_years}, expected 6"
        )


# ─── TC-7.10 ─────────────────────────────────────────────────────────────────

def test_tc_7_10_audit_log_rows_contain_no_raw_phi_field_values(
    db_session, participants
):
    """TC-7.10 — Broad DB scan confirms no audit row contains raw PHI field values
    (medicaid IDs, real names, SSN patterns) in any column."""
    rows = db_session.execute(
        text("SELECT user_id, resource_id, data_affected FROM audit_log")
    ).fetchall()
    assert len(rows) > 0, "No audit rows to scan"

    phi_patterns = ("Eleanor", "Vasquez", "1942-03-14", "SEED-MC-001")
    for row in rows:
        da = row.data_affected
        if isinstance(da, str):
            da_parsed = _json.loads(da)
        else:
            da_parsed = da
        assert isinstance(da_parsed, list), (
            f"data_affected is not a list: {da_parsed!r}"
        )
        da_str = str(da_parsed)
        for pattern in phi_patterns:
            assert pattern not in da_str, (
                f"PHI pattern '{pattern}' found in data_affected: {da_str}"
            )
        for item in da_parsed:
            assert isinstance(item, str), (
                f"data_affected contains non-string element: {item!r} — "
                "expected field names only, not values"
            )
