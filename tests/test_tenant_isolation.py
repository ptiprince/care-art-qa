"""
test_tenant_isolation.py — 7 tests TC-9.1 through TC-9.7.

Regulatory scope: HIPAA §164.308(a)(3) multi-tenant PHI isolation.

Design rules:
  - TENANT_A is the primary test tenant (tenant-aaa-001).
  - TENANT_B is the secondary isolation tenant (tenant-bbb-002).
  - Cross-tenant reads return 404. The backend logs an ACCESS_DENIED audit row
    before returning 404 — confirmed in main.py get_participant, get_attendance,
    get_claim, get_mar_record, and get_incident handlers.
  - All DB assertions use db_session; no inline SQL values for tenant IDs.
  - TENANT_B admin headers use a distinct user_id prefix to avoid audit log
    conflicts with TENANT_A fixture data.
  - TC-9.7 uses distinct medicaid_id/email values to avoid conflicts with the
    session-scoped seed data while demonstrating per-tenant uniqueness.
"""
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from sqlalchemy import text

from helpers import (
    TENANT_A, TENANT_B,
    ADMIN_ID,
    make_headers, make_participant, make_attendance, make_confirmed_attendance,
    make_claim, make_mar_record, make_nurse_user, make_incident,
)

_ADMIN_A = make_headers("program_administrator", tenant_id=TENANT_A, user_id="iso-admin-a-001")
_ADMIN_B = make_headers("program_administrator", tenant_id=TENANT_B, user_id="iso-admin-b-001")
_COORD_B = make_headers("care_coordinator",      tenant_id=TENANT_B, user_id="iso-coord-b-001")


def _call(fn):
    try:
        return fn()
    except httpx.ConnectError:
        pytest.fail("Cannot connect to mock backend.")
    except httpx.TimeoutException:
        pytest.fail("Mock backend timed out.")


# ─── TC-9.1 ──────────────────────────────────────────────────────────────────

def test_tc_9_1_participant_not_accessible_from_other_tenant(
    session_client, db_session, participants
):
    """TC-9.1 — GET /participants/{id} with tenant-B headers returns 404 for a
    tenant-A record; the row exists unchanged in the DB under tenant A."""
    p = participants["active"][4]
    pid = p["participant_id"]

    r = _call(lambda: session_client.get(f"/participants/{pid}", headers=_ADMIN_B))
    assert r.status_code == 404, (
        f"Expected 404 for cross-tenant participant GET, got {r.status_code}"
    )

    row = db_session.execute(
        text("SELECT tenant_id FROM participant WHERE participant_id=:pid"),
        {"pid": pid},
    ).fetchone()
    assert row is not None, "Participant row was removed — must not happen"
    assert row.tenant_id == TENANT_A, (
        f"Participant tenant changed: expected {TENANT_A}, got {row.tenant_id}"
    )

    aud = db_session.execute(
        text("SELECT action_type, outcome FROM audit_log "
             "WHERE action_type='ACCESS_DENIED' AND resource_id=:id "
             "ORDER BY rowid DESC LIMIT 1"),
        {"id": pid},
    ).fetchone()
    assert aud is not None, "ACCESS_DENIED audit row not found for cross-tenant participant GET"
    assert aud.outcome == "DENIED"


# ─── TC-9.2 ──────────────────────────────────────────────────────────────────

def test_tc_9_2_user_token_rejected_on_other_tenant_endpoints(
    session_client, db_session
):
    """TC-9.2 — tenant-A headers cannot access a tenant-B participant record;
    GET returns 404 and the tenant-B row is unchanged in the DB."""
    p_b = make_participant(
        session_client, _ADMIN_B,
        tenant_id=TENANT_B,
        medicaid_id=f"ISO-B-TC92-{uuid.uuid4().hex[:6].upper()}",
    )
    pid_b = p_b["participant_id"]

    r = _call(lambda: session_client.get(f"/participants/{pid_b}", headers=_ADMIN_A))
    assert r.status_code == 404, (
        f"Expected 404 when tenant-A token accesses tenant-B record, got {r.status_code}"
    )

    row = db_session.execute(
        text("SELECT tenant_id FROM participant WHERE participant_id=:pid"),
        {"pid": pid_b},
    ).fetchone()
    assert row is not None, "Tenant-B participant row was deleted — must not happen"
    assert row.tenant_id == TENANT_B

    aud = db_session.execute(
        text("SELECT action_type, outcome FROM audit_log "
             "WHERE action_type='ACCESS_DENIED' AND resource_id=:id "
             "ORDER BY rowid DESC LIMIT 1"),
        {"id": pid_b},
    ).fetchone()
    assert aud is not None, "ACCESS_DENIED audit row not found for cross-tenant participant GET"
    assert aud.outcome == "DENIED"


# ─── TC-9.3 ──────────────────────────────────────────────────────────────────

def test_tc_9_3_attendance_not_accessible_from_other_tenant(
    session_client, db_session, fresh_attendance
):
    """TC-9.3 — GET /attendance/{id} with tenant-B headers returns 404 for a
    tenant-A attendance record; the row exists unchanged in the DB."""
    att, _p = fresh_attendance
    att_id = att["attendance_id"]

    r = _call(lambda: session_client.get(f"/attendance/{att_id}", headers=_ADMIN_B))
    assert r.status_code == 404, (
        f"Expected 404 for cross-tenant attendance GET, got {r.status_code}"
    )

    row = db_session.execute(
        text("SELECT tenant_id FROM attendance WHERE attendance_id=:aid"),
        {"aid": att_id},
    ).fetchone()
    assert row is not None, "Attendance row was removed — must not happen"
    assert row.tenant_id == TENANT_A

    aud = db_session.execute(
        text("SELECT action_type, outcome FROM audit_log "
             "WHERE action_type='ACCESS_DENIED' AND resource_id=:id "
             "ORDER BY rowid DESC LIMIT 1"),
        {"id": att_id},
    ).fetchone()
    assert aud is not None, "ACCESS_DENIED audit row not found for cross-tenant attendance GET"
    assert aud.outcome == "DENIED"


# ─── TC-9.4 ──────────────────────────────────────────────────────────────────

def test_tc_9_4_claim_not_accessible_from_other_tenant(
    session_client, db_session, fresh_claim
):
    """TC-9.4 — GET /claims/{id} with tenant-B headers returns 404 for a
    tenant-A claim; the row exists unchanged in the DB."""
    claim, _att, _p = fresh_claim
    claim_id = claim["claim_id"]

    r = _call(lambda: session_client.get(f"/claims/{claim_id}", headers=_ADMIN_B))
    assert r.status_code == 404, (
        f"Expected 404 for cross-tenant claim GET, got {r.status_code}"
    )

    row = db_session.execute(
        text("SELECT tenant_id FROM claim WHERE claim_id=:cid"),
        {"cid": claim_id},
    ).fetchone()
    assert row is not None, "Claim row was removed — must not happen"
    assert row.tenant_id == TENANT_A

    aud = db_session.execute(
        text("SELECT action_type, outcome FROM audit_log "
             "WHERE action_type='ACCESS_DENIED' AND resource_id=:id "
             "ORDER BY rowid DESC LIMIT 1"),
        {"id": claim_id},
    ).fetchone()
    assert aud is not None, "ACCESS_DENIED audit row not found for cross-tenant claim GET"
    assert aud.outcome == "DENIED"


# ─── TC-9.5 ──────────────────────────────────────────────────────────────────

def test_tc_9_5_mar_record_not_accessible_from_other_tenant(
    session_client, db_session, fresh_mar_record
):
    """TC-9.5 — GET /mar-records/{id} with tenant-B headers returns 404 for a
    tenant-A MARRecord; the row exists unchanged in the DB."""
    mar, _nurse_user, _p = fresh_mar_record
    mar_id = mar["mar_id"]

    r = _call(lambda: session_client.get(f"/mar-records/{mar_id}", headers=_ADMIN_B))
    assert r.status_code == 404, (
        f"Expected 404 for cross-tenant MAR GET, got {r.status_code}"
    )

    row = db_session.execute(
        text("SELECT tenant_id FROM mar_record WHERE mar_id=:mid"),
        {"mid": mar_id},
    ).fetchone()
    assert row is not None, "MARRecord row was removed — must not happen"
    assert row.tenant_id == TENANT_A

    aud = db_session.execute(
        text("SELECT action_type, outcome FROM audit_log "
             "WHERE action_type='ACCESS_DENIED' AND resource_id=:id "
             "ORDER BY rowid DESC LIMIT 1"),
        {"id": mar_id},
    ).fetchone()
    assert aud is not None, "ACCESS_DENIED audit row not found for cross-tenant MAR GET"
    assert aud.outcome == "DENIED"


# ─── TC-9.6 ──────────────────────────────────────────────────────────────────

def test_tc_9_6_incident_not_accessible_from_other_tenant(
    session_client, db_session, fresh_incident
):
    """TC-9.6 — GET /incidents/{id} with tenant-B headers returns 404 for a
    tenant-A incident; the row exists unchanged in the DB."""
    inc, _p = fresh_incident
    incident_id = inc["incident_id"]

    r = _call(lambda: session_client.get(f"/incidents/{incident_id}", headers=_ADMIN_B))
    assert r.status_code == 404, (
        f"Expected 404 for cross-tenant incident GET, got {r.status_code}"
    )

    row = db_session.execute(
        text("SELECT tenant_id FROM incident WHERE incident_id=:iid"),
        {"iid": incident_id},
    ).fetchone()
    assert row is not None, "Incident row was removed — must not happen"
    assert row.tenant_id == TENANT_A

    aud = db_session.execute(
        text("SELECT action_type, outcome FROM audit_log "
             "WHERE action_type='ACCESS_DENIED' AND resource_id=:id "
             "ORDER BY rowid DESC LIMIT 1"),
        {"id": incident_id},
    ).fetchone()
    assert aud is not None, "ACCESS_DENIED audit row not found for cross-tenant incident GET"
    assert aud.outcome == "DENIED"


# ─── TC-9.7 ──────────────────────────────────────────────────────────────────

def test_tc_9_7_unique_constraints_are_scoped_per_tenant(
    session_client, db_session, admin_headers
):
    """TC-9.7 — medicaid_id and email registered in tenant A are accepted in
    tenant B (returns 201); DB shows exactly 2 rows for each value, one per tenant."""
    today = datetime.now(timezone.utc).date()
    medicaid_id = f"TC97-DEDUP-{uuid.uuid4().hex[:6].upper()}"
    email = f"tc97-dedup-{uuid.uuid4().hex[:6]}@care-art-test.invalid"

    # Create participant in TENANT_A
    r_pa = _call(lambda: session_client.post("/participants", json={
        "tenant_id": TENANT_A,
        "first_name": "Iso",
        "last_name": "TenantA",
        "date_of_birth": (today - timedelta(days=365 * 50)).isoformat(),
        "enrollment_date": today.isoformat(),
        "medicaid_id": medicaid_id,
    }, headers=admin_headers))
    assert r_pa.status_code == 201, f"Tenant-A participant failed: {r_pa.text}"

    # Same medicaid_id in TENANT_B → must succeed (different tenant scope)
    r_pb = _call(lambda: session_client.post("/participants", json={
        "tenant_id": TENANT_B,
        "first_name": "Iso",
        "last_name": "TenantB",
        "date_of_birth": (today - timedelta(days=365 * 50)).isoformat(),
        "enrollment_date": today.isoformat(),
        "medicaid_id": medicaid_id,
    }, headers=_ADMIN_B))
    assert r_pb.status_code == 201, (
        f"Tenant-B participant with same medicaid_id should succeed (per-tenant uniqueness): {r_pb.text}"
    )

    # Create user in TENANT_A
    r_ua = _call(lambda: session_client.post("/users", json={
        "tenant_id": TENANT_A,
        "first_name": "Iso",
        "last_name": "UserA",
        "email": email,
        "role": "care_coordinator",
    }, headers=admin_headers))
    assert r_ua.status_code == 201, f"Tenant-A user failed: {r_ua.text}"

    # Same email in TENANT_B → must succeed
    r_ub = _call(lambda: session_client.post("/users", json={
        "tenant_id": TENANT_B,
        "first_name": "Iso",
        "last_name": "UserB",
        "email": email,
        "role": "care_coordinator",
    }, headers=_ADMIN_B))
    assert r_ub.status_code == 201, (
        f"Tenant-B user with same email should succeed (per-tenant uniqueness): {r_ub.text}"
    )

    # DB: exactly 2 participant rows with that medicaid_id (one per tenant)
    p_count = db_session.execute(
        text("SELECT COUNT(*) FROM participant WHERE medicaid_id=:mid"),
        {"mid": medicaid_id},
    ).scalar()
    assert p_count == 2, (
        f"Expected 2 participant rows with medicaid_id={medicaid_id}, got {p_count}"
    )

    # DB: each tenant has exactly 1
    for tid in (TENANT_A, TENANT_B):
        c = db_session.execute(
            text("SELECT COUNT(*) FROM participant WHERE medicaid_id=:mid AND tenant_id=:tid"),
            {"mid": medicaid_id, "tid": tid},
        ).scalar()
        assert c == 1, f"Expected 1 participant row in {tid}, got {c}"

    # DB: exactly 2 user rows with that email (one per tenant)
    u_count = db_session.execute(
        text("SELECT COUNT(*) FROM user WHERE email=:em"),
        {"em": email},
    ).scalar()
    assert u_count == 2, (
        f"Expected 2 user rows with email={email}, got {u_count}"
    )

    for tid in (TENANT_A, TENANT_B):
        c = db_session.execute(
            text("SELECT COUNT(*) FROM user WHERE email=:em AND tenant_id=:tid"),
            {"em": email, "tid": tid},
        ).scalar()
        assert c == 1, f"Expected 1 user row in {tid}, got {c}"
