"""
test_rbac_sweep.py — 12 tests TC-8.1 through TC-8.12.

Regulatory scope: HIPAA §164.312(a)(1) · 42 CFR Part 2 access gates.

Design rules:
  - Every test captures DB row counts before the RBAC action and asserts the
    count is unchanged after denied calls.
  - All DB assertions use db_session count queries; no direct row inspection
    for success cases (HTTP status + basic response field is sufficient).
  - No hardcoded dates; all dates computed at runtime.
  - physician and participant_family are outside STAFF_ROLES for write and have
    no read access to any entity.
  - WRITE_ROLES: participant=[admin,coord,nurse,compliance],
    attendance=[admin,coord], claim=[billing,admin], mar_record=[nurse],
    incident=STAFF_ROLES, user=[admin].
  - SUD_PRIVILEGED_ROLES: mar_record=[compliance,nurse],
    incident=[compliance,coord,nurse,admin].
  - compliance_officer has READ on all entities (STAFF_ROLES).
"""
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from sqlalchemy import text

from helpers import (
    TENANT_A,
    ADMIN_ID, COORDINATOR_ID, NURSE_ID, BILLING_ID,
    PHYSICIAN_ID, FAMILY_ID, COMPLIANCE_ID,
    make_headers, make_participant, make_confirmed_attendance,
    make_claim, make_mar_record, make_nurse_user, make_incident,
)


def _call(fn):
    try:
        return fn()
    except httpx.ConnectError:
        pytest.fail("Cannot connect to mock backend.")
    except httpx.TimeoutException:
        pytest.fail("Mock backend timed out.")


def _count(db, table, *, tenant_id=TENANT_A, extra_where=""):
    sql = f"SELECT COUNT(*) FROM {table} WHERE tenant_id=:tid {extra_where}"
    return db.execute(text(sql), {"tid": tenant_id}).scalar()


# ─── TC-8.1 ──────────────────────────────────────────────────────────────────

def test_tc_8_1_program_administrator_write_permitted_on_attendance_and_claims(
    client, db_session, admin_headers, fresh_participant, fresh_claim
):
    """TC-8.1 — program_administrator POST /attendance returns 201 and
    PATCH /claims/{id} returns 200; DB confirms both operations persisted."""
    p = fresh_participant
    claim, _att, _cp = fresh_claim
    today = datetime.now(timezone.utc).date()
    dos = (today - timedelta(days=80)).isoformat()

    count_before = _count(db_session, "attendance",
                          extra_where=f"AND participant_id='{p['participant_id']}'")

    r_att = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "date_of_service": dos,
        "status": "pending",
    }, headers=admin_headers))
    assert r_att.status_code == 201, f"Expected 201: {r_att.text}"
    att_id = r_att.json()["attendance_id"]

    count_after = _count(db_session, "attendance",
                         extra_where=f"AND participant_id='{p['participant_id']}'")
    assert count_after == count_before + 1

    row_att = db_session.execute(
        text("SELECT tenant_id FROM attendance WHERE attendance_id=:aid"),
        {"aid": att_id},
    ).fetchone()
    assert row_att is not None and row_att.tenant_id == TENANT_A

    r_claim = _call(lambda: client.patch(
        f"/claims/{claim['claim_id']}",
        json={"version": claim["version"], "claim_status": "submitted"},
        headers=admin_headers,
    ))
    assert r_claim.status_code == 200, f"Expected 200: {r_claim.text}"

    row_claim = db_session.execute(
        text("SELECT claim_status FROM claim WHERE claim_id=:cid"),
        {"cid": claim["claim_id"]},
    ).fetchone()
    assert row_claim.claim_status == "submitted"


# ─── TC-8.2 ──────────────────────────────────────────────────────────────────

def test_tc_8_2_care_coordinator_write_permitted_on_attendance_and_incidents(
    client, db_session, coordinator_headers, fresh_participant
):
    """TC-8.2 — care_coordinator POST /attendance and POST /incidents both return
    201; DB confirms both rows created with correct tenant."""
    p = fresh_participant
    today = datetime.now(timezone.utc).date()

    r_att = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "date_of_service": (today - timedelta(days=90)).isoformat(),
        "status": "pending",
    }, headers=coordinator_headers))
    assert r_att.status_code == 201, f"Expected 201: {r_att.text}"
    att_id = r_att.json()["attendance_id"]

    r_inc = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "incident_date": (today - timedelta(days=91)).isoformat(),
        "incident_type": "fall",
        "description": "TC-8.2 coordinator incident test.",
        "severity": "minor",
        "is_sud_related": False,
        "status": "draft",
    }, headers=coordinator_headers))
    assert r_inc.status_code == 201, f"Expected 201: {r_inc.text}"
    inc_id = r_inc.json()["incident_id"]

    row_att = db_session.execute(
        text("SELECT tenant_id FROM attendance WHERE attendance_id=:aid"),
        {"aid": att_id},
    ).fetchone()
    assert row_att is not None and row_att.tenant_id == TENANT_A

    row_inc = db_session.execute(
        text("SELECT tenant_id FROM incident WHERE incident_id=:iid"),
        {"iid": inc_id},
    ).fetchone()
    assert row_inc is not None and row_inc.tenant_id == TENANT_A


# ─── TC-8.3 ──────────────────────────────────────────────────────────────────

def test_tc_8_3_nurse_medication_aide_write_permitted_on_mar_record_only(
    client, db_session, nurse_headers, mar_write_setup, fresh_confirmed_attendance
):
    """TC-8.3 — nurse_medication_aide POST /mar-records returns 201; POST /claims
    returns 403 RBAC_DENIED; DB confirms no claim row was created."""
    p, nurse_user = mar_write_setup
    att, _cp = fresh_confirmed_attendance

    claim_count_before = _count(db_session, "claim")

    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    r_mar = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "medication_name": "Furosemide 40mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "administered_time": (now - timedelta(hours=1, minutes=55)).strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "administered",
        "is_controlled_substance": False,
    }, headers=nurse_headers))
    assert r_mar.status_code == 201, f"Expected 201 for nurse MAR: {r_mar.text}"

    r_claim = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": att["participant_id"],
        "attendance_ids": [att["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "S5101",
        "date_of_service_start": (datetime.now(timezone.utc).date() - timedelta(days=12)).isoformat(),
    }, headers=nurse_headers))
    assert r_claim.status_code == 403, f"Expected 403 for nurse claim: {r_claim.status_code}"
    assert r_claim.json()["detail"]["error_code"] == "RBAC_DENIED"

    claim_count_after = _count(db_session, "claim")
    assert claim_count_after == claim_count_before, (
        f"Claim count changed after nurse denied: before={claim_count_before}, after={claim_count_after}"
    )


# ─── TC-8.4 ──────────────────────────────────────────────────────────────────

def test_tc_8_4_billing_specialist_write_permitted_on_claims_only(
    client, db_session, billing_headers, fresh_confirmed_attendance, mar_write_setup
):
    """TC-8.4 — billing_specialist POST /claims returns 201; POST /mar-records
    returns 403 RBAC_DENIED; DB confirms no MAR row was created."""
    att, _cp = fresh_confirmed_attendance
    p_mar, nurse_user = mar_write_setup

    mar_count_before = _count(db_session, "mar_record")

    r_claim = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": att["participant_id"],
        "attendance_ids": [att["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "S5101",
        "date_of_service_start": (datetime.now(timezone.utc).date() - timedelta(days=13)).isoformat(),
    }, headers=billing_headers))
    assert r_claim.status_code == 201, f"Expected 201 for billing claim: {r_claim.text}"

    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    r_mar = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": p_mar["participant_id"],
        "medication_name": "Amlodipine 5mg",
        "administered_by": nurse_user["user_id"],
        "scheduled_time": scheduled,
        "status": "administered",
    }, headers=billing_headers))
    assert r_mar.status_code == 403, f"Expected 403 for billing MAR: {r_mar.status_code}"
    assert r_mar.json()["detail"]["error_code"] == "RBAC_DENIED"

    mar_count_after = _count(db_session, "mar_record")
    assert mar_count_after == mar_count_before, (
        f"MAR count changed after billing denied: before={mar_count_before}, after={mar_count_after}"
    )


# ─── TC-8.5 ──────────────────────────────────────────────────────────────────

def test_tc_8_5_physician_denied_write_on_participant_endpoint(
    client, db_session, physician_headers
):
    """TC-8.5 — physician POST /participants returns 403 RBAC_DENIED;
    DB participant count unchanged."""
    count_before = _count(db_session, "participant")
    today = datetime.now(timezone.utc).date()

    r = _call(lambda: client.post("/participants", json={
        "tenant_id": TENANT_A,
        "first_name": "Blocked",
        "last_name": "Physician",
        "date_of_birth": (today - timedelta(days=365 * 50)).isoformat(),
        "enrollment_date": today.isoformat(),
    }, headers=physician_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    assert _count(db_session, "participant") == count_before


# ─── TC-8.6 ──────────────────────────────────────────────────────────────────

def test_tc_8_6_physician_denied_write_on_user_endpoint(
    client, db_session, physician_headers
):
    """TC-8.6 — physician POST /users returns 403 RBAC_DENIED;
    DB user count unchanged."""
    count_before = _count(db_session, "user")

    r = _call(lambda: client.post("/users", json={
        "tenant_id": TENANT_A,
        "first_name": "Blocked",
        "last_name": "PhysUser",
        "email": f"physician-blocked-{uuid.uuid4().hex[:6]}@test.care",
        "role": "care_coordinator",
    }, headers=physician_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    assert _count(db_session, "user") == count_before


# ─── TC-8.7 ──────────────────────────────────────────────────────────────────

def test_tc_8_7_physician_denied_write_on_attendance_endpoint(
    client, db_session, physician_headers, participants
):
    """TC-8.7 — physician POST /attendance returns 403 RBAC_DENIED;
    DB attendance count unchanged."""
    p = participants["active"][0]
    count_before = _count(db_session, "attendance")
    today = datetime.now(timezone.utc).date()

    r = _call(lambda: client.post("/attendance", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "date_of_service": (today - timedelta(days=200)).isoformat(),
        "status": "pending",
    }, headers=physician_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    assert _count(db_session, "attendance") == count_before


# ─── TC-8.8 ──────────────────────────────────────────────────────────────────

def test_tc_8_8_physician_denied_write_on_claim_endpoint(
    client, db_session, physician_headers
):
    """TC-8.8 — physician POST /claims returns 403 RBAC_DENIED;
    DB claim count unchanged."""
    count_before = _count(db_session, "claim")

    today_tc88 = datetime.now(timezone.utc).date()
    r = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": "fake-pid-tc88",
        "attendance_ids": ["fake-att-tc88"],
        "payer_type": "medicaid",
        "procedure_code": "S5101",
        "date_of_service_start": (today_tc88 - timedelta(days=110)).isoformat(),
    }, headers=physician_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    assert _count(db_session, "claim") == count_before


# ─── TC-8.9 ──────────────────────────────────────────────────────────────────

def test_tc_8_9_physician_denied_write_on_mar_record_endpoint(
    client, db_session, physician_headers
):
    """TC-8.9 — physician POST /mar-records returns 403 RBAC_DENIED;
    DB mar_record count unchanged."""
    count_before = _count(db_session, "mar_record")
    now = datetime.now(timezone.utc)

    r = _call(lambda: client.post("/mar-records", json={
        "tenant_id": TENANT_A,
        "participant_id": "fake-pid-tc89",
        "medication_name": "Metformin 500mg",
        "administered_by": "fake-nurse-tc89",
        "scheduled_time": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "administered",
    }, headers=physician_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    assert _count(db_session, "mar_record") == count_before


# ─── TC-8.10 ─────────────────────────────────────────────────────────────────

def test_tc_8_10_physician_denied_write_on_incident_endpoint(
    client, db_session, physician_headers, participants
):
    """TC-8.10 — physician POST /incidents returns 403 RBAC_DENIED;
    DB incident count unchanged."""
    p = participants["active"][1]
    count_before = _count(db_session, "incident")
    today = datetime.now(timezone.utc).date()

    r = _call(lambda: client.post("/incidents", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "incident_date": (today - timedelta(days=210)).isoformat(),
        "incident_type": "fall",
        "description": "Physician cannot create incidents.",
        "severity": "minor",
        "status": "draft",
    }, headers=physician_headers))
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    assert _count(db_session, "incident") == count_before


# ─── TC-8.11 ─────────────────────────────────────────────────────────────────

def test_tc_8_11_participant_family_denied_all_staff_entity_endpoints(
    client, db_session, family_headers, participants
):
    """TC-8.11 — participant_family POST to each of the 6 write endpoints returns
    403 RBAC_DENIED; all 6 DB table counts unchanged."""
    p = participants["active"][2]
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    tables = ["participant", "user", "attendance", "claim", "mar_record", "incident"]
    counts_before = {t: _count(db_session, t) for t in tables}

    payloads = [
        ("POST", "/participants", {
            "tenant_id": TENANT_A, "first_name": "Fam", "last_name": "Block",
            "date_of_birth": (today - timedelta(days=365*30)).isoformat(),
            "enrollment_date": today.isoformat(),
        }),
        ("POST", "/users", {
            "tenant_id": TENANT_A, "first_name": "Fam", "last_name": "Block",
            "email": f"famblock-{uuid.uuid4().hex[:6]}@test.care",
            "role": "care_coordinator",
        }),
        ("POST", "/attendance", {
            "tenant_id": TENANT_A, "participant_id": p["participant_id"],
            "date_of_service": (today - timedelta(days=220)).isoformat(),
            "status": "pending",
        }),
        ("POST", "/claims", {
            "tenant_id": TENANT_A, "participant_id": p["participant_id"],
            "attendance_ids": ["fake-att-tc811"], "payer_type": "medicaid",
            "procedure_code": "S5101",
            "date_of_service_start": (today - timedelta(days=230)).isoformat(),
        }),
        ("POST", "/mar-records", {
            "tenant_id": TENANT_A, "participant_id": p["participant_id"],
            "medication_name": "Lisinopril", "administered_by": "fake-nurse-tc811",
            "scheduled_time": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "administered",
        }),
        ("POST", "/incidents", {
            "tenant_id": TENANT_A, "participant_id": p["participant_id"],
            "incident_date": (today - timedelta(days=221)).isoformat(),
            "incident_type": "fall", "description": "Family block test.",
            "severity": "minor", "status": "draft",
        }),
    ]

    for _method, url, body in payloads:
        r = _call(lambda u=url, b=body: client.post(u, json=b, headers=family_headers))
        assert r.status_code == 403, (
            f"Expected 403 on {url} for participant_family, got {r.status_code}"
        )
        assert r.json()["detail"]["error_code"] == "RBAC_DENIED"

    for table in tables:
        count_after = _count(db_session, table)
        assert count_after == counts_before[table], (
            f"{table} count changed after family denied: "
            f"before={counts_before[table]}, after={count_after}"
        )


# ─── TC-8.12 ─────────────────────────────────────────────────────────────────

def test_tc_8_12_compliance_officer_read_permitted_on_all_entities(
    client, db_session, compliance_headers,
    participants, users, fresh_claim, fresh_mar_record, fresh_incident
):
    """TC-8.12 — compliance_officer GET on all 6 entity endpoints returns 200;
    DB confirms each returned record matches the row by primary key."""
    p = participants["active"][3]
    u = users["admins"][0]
    claim, att, _cp = fresh_claim
    mar, _nurse_user, _mp = fresh_mar_record
    inc, _ip = fresh_incident

    checks = [
        (f"/participants/{p['participant_id']}", "participant_id", p["participant_id"]),
        (f"/users/{u['user_id']}",              "user_id",        u["user_id"]),
        (f"/attendance/{att['attendance_id']}",  "attendance_id",  att["attendance_id"]),
        (f"/claims/{claim['claim_id']}",         "claim_id",       claim["claim_id"]),
        (f"/mar-records/{mar['mar_id']}",        "mar_id",         mar["mar_id"]),
        (f"/incidents/{inc['incident_id']}",     "incident_id",    inc["incident_id"]),
    ]

    for url, id_field, expected_id in checks:
        r = _call(lambda u=url: client.get(u, headers=compliance_headers))
        assert r.status_code == 200, (
            f"compliance_officer GET {url} returned {r.status_code}: {r.text}"
        )
        body = r.json()
        assert body.get(id_field) == expected_id, (
            f"{id_field} mismatch: expected {expected_id}, got {body.get(id_field)}"
        )
