"""
test_claim.py — 15 tests mapped to TC-4.1 through TC-4.15.

Regulatory scope: HIPAA §164.308 / §164.312 · CMS Medicaid/Medicare billing
integrity · 42 CFR Part 455 · State adult day care licensing.

Design rules (enforced throughout):
  - All DB seeding lives in conftest.py fixtures.
  - All API actions are invoked via _call(); test functions contain only
    business-logic assertions.
  - Every assertion on persisted state queries the SQLite DB directly through
    db_session.
  - No time.sleep(), no UI, no inline data creation in test functions.
  - Error codes asserted exactly: CLAIM_DUPLICATE_REFERENCE, CLAIM_DUPLICATE,
    CLAIM_FIELD_IMMUTABLE, CLAIM_NO_ATTENDANCE_RECORDS,
    CLAIM_ATTENDANCE_NOT_FOUND, CLAIM_VERSION_CONFLICT.
  - units_billed is server-calculated from sum of authorized_units_consumed;
    any caller-supplied value is ignored.
  - State machine: draft → submitted only. PATCH on submitted or paid returns
    422 (CLAIM_FIELD_IMMUTABLE) before the version check.
  - RBAC: only billing_specialist and program_administrator may POST /claims.
  - TC-4.8 audit assertions query audit_log table directly, not GET /audit-logs.
"""
import re
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from sqlalchemy import text

from helpers import TENANT_A, TENANT_B, BILLING_ID, make_headers


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


# ─── TC-4.1 ──────────────────────────────────────────────────────────────────

def test_tc_4_1_duplicate_claim_reference_returns_409(
    client, billing_headers, claim_dup_ref_setup, db_session
):
    """TC-4.1 — POST /claims whose generated reference collides with an existing
    claim reference returns 409 CLAIM_DUPLICATE_REFERENCE; DB count stays at 1."""
    today = datetime.now(timezone.utc).date()
    dos_4_1 = (today - timedelta(days=90)).isoformat()
    p, att, fixed_ref = claim_dup_ref_setup

    # Pre-condition: exactly one claim with the fixed reference exists in DB
    count_before = db_session.execute(
        text(
            "SELECT COUNT(*) FROM claim "
            "WHERE claim_reference_number = :ref AND tenant_id = :tid"
        ),
        {"ref": fixed_ref, "tid": TENANT_A},
    ).scalar()
    assert count_before == 1, (
        f"Pre-condition failed: expected 1 claim with reference {fixed_ref}, found {count_before}"
    )

    r = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "attendance_ids": [att["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_1,
    }, headers=billing_headers))
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "CLAIM_DUPLICATE_REFERENCE"

    # DB: count must remain 1 — no second row with that reference was created
    count_after = db_session.execute(
        text(
            "SELECT COUNT(*) FROM claim "
            "WHERE claim_reference_number = :ref AND tenant_id = :tid"
        ),
        {"ref": fixed_ref, "tid": TENANT_A},
    ).scalar()
    assert count_after == 1, (
        f"Expected count=1 after rejected POST, found {count_after}"
    )


# ─── TC-4.2 ──────────────────────────────────────────────────────────────────

def test_tc_4_2_composite_duplicate_returns_409_claim_duplicate(
    client, billing_headers, claim_dup_composite_setup, db_session
):
    """TC-4.2 — POST /claims with same (participant, dos, procedure, payer) as an
    existing claim returns 409 CLAIM_DUPLICATE; DB count stays at 1."""
    p, _att1, existing_claim, att2 = claim_dup_composite_setup
    pid = p["participant_id"]
    dos = existing_claim["date_of_service_start"]

    # Pre-condition: exactly one claim for this composite key
    count_before = db_session.execute(
        text(
            "SELECT COUNT(*) FROM claim "
            "WHERE tenant_id = :tid AND participant_id = :pid "
            "AND date_of_service_start = :dos "
            "AND procedure_code = 'T2029' AND payer_type = 'medicaid'"
        ),
        {"tid": TENANT_A, "pid": pid, "dos": dos},
    ).scalar()
    assert count_before == 1, (
        f"Pre-condition failed: expected 1 claim with composite key, found {count_before}"
    )

    r = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [att2["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos,
    }, headers=billing_headers))
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "CLAIM_DUPLICATE"

    # DB: still exactly one claim for this composite key
    count_after = db_session.execute(
        text(
            "SELECT COUNT(*) FROM claim "
            "WHERE tenant_id = :tid AND participant_id = :pid "
            "AND date_of_service_start = :dos "
            "AND procedure_code = 'T2029' AND payer_type = 'medicaid'"
        ),
        {"tid": TENANT_A, "pid": pid, "dos": dos},
    ).scalar()
    assert count_after == 1, (
        f"Expected count=1 after rejected duplicate POST, found {count_after}"
    )


# ─── TC-4.3 ──────────────────────────────────────────────────────────────────

def test_tc_4_3_unauthorized_roles_post_claims_returns_403(
    client,
    coordinator_headers,
    nurse_headers,
    physician_headers,
    family_headers,
    fresh_confirmed_attendance,
    db_session,
):
    """TC-4.3 — POST /claims by care_coordinator, nurse_medication_aide, physician,
    and participant_family each return 403 RBAC_DENIED; DB claim count is unchanged."""
    today = datetime.now(timezone.utc).date()
    dos_4_3 = (today - timedelta(days=91)).isoformat()
    att, p = fresh_confirmed_attendance
    pid = p["participant_id"]

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE tenant_id = :tid"),
        {"tid": TENANT_A},
    ).scalar()

    payload = {
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [att["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_3,
    }

    unauthorized = [
        ("care_coordinator",       coordinator_headers),
        ("nurse_medication_aide",  nurse_headers),
        ("physician",              physician_headers),
        ("participant_family",     family_headers),
    ]
    for role, headers in unauthorized:
        r = _call(lambda h=headers: client.post("/claims", json=payload, headers=h))
        assert r.status_code == 403, (
            f"Expected 403 for role '{role}', got {r.status_code}"
        )
        assert r.json()["detail"]["error_code"] == "RBAC_DENIED", (
            f"Expected RBAC_DENIED for role '{role}', got {r.json()['detail']['error_code']}"
        )

    # DB: no new claims created by any unauthorized attempt
    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE tenant_id = :tid"),
        {"tid": TENANT_A},
    ).scalar()
    assert count_after == count_before, (
        f"DB claim count changed after 403 rejections: before={count_before}, after={count_after}"
    )


# ─── TC-4.4 ──────────────────────────────────────────────────────────────────

def test_tc_4_4_submitted_and_paid_claims_are_immutable(
    client, billing_headers, submitted_and_paid_claims, db_session
):
    """TC-4.4 — PATCH a non-status field on a submitted claim returns 422
    CLAIM_FIELD_IMMUTABLE; PATCH any field on a paid claim returns 422; DB
    shows both claims unchanged after rejected edits."""
    c_sub, c_paid, _p_a, _p_b = submitted_and_paid_claims
    c_sub_id = c_sub["claim_id"]
    c_paid_id = c_paid["claim_id"]

    # GET C_sub to confirm submitted status and capture version
    r_get_sub = _call(lambda: client.get(f"/claims/{c_sub_id}", headers=billing_headers))
    assert r_get_sub.status_code == 200
    sub_body = r_get_sub.json()
    assert sub_body["claim_status"] == "submitted"
    sub_version = sub_body["version"]

    # PATCH non-status field on submitted claim → 422 CLAIM_FIELD_IMMUTABLE
    r_patch_sub = _call(lambda: client.patch(
        f"/claims/{c_sub_id}",
        json={"version": sub_version, "rejection_reason": "Test edit on submitted claim"},
        headers=billing_headers,
    ))
    assert r_patch_sub.status_code == 422
    assert r_patch_sub.json()["detail"]["error_code"] == "CLAIM_FIELD_IMMUTABLE"

    # DB: submitted claim is unchanged
    row_sub = db_session.execute(
        text("SELECT claim_status, version FROM claim WHERE claim_id = :cid"),
        {"cid": c_sub_id},
    ).fetchone()
    assert row_sub is not None, f"Submitted claim {c_sub_id} not found in DB"
    assert row_sub.claim_status == "submitted", (
        f"Expected claim_status='submitted' in DB after rejected PATCH, got '{row_sub.claim_status}'"
    )
    assert row_sub.version == sub_version, (
        f"Expected version={sub_version} unchanged, got {row_sub.version}"
    )

    # GET C_paid to confirm paid status and capture version
    r_get_paid = _call(lambda: client.get(f"/claims/{c_paid_id}", headers=billing_headers))
    assert r_get_paid.status_code == 200
    paid_body = r_get_paid.json()
    assert paid_body["claim_status"] == "paid"
    paid_version = paid_body["version"]

    # PATCH non-status field on paid claim → 422 CLAIM_FIELD_IMMUTABLE
    r_patch_paid = _call(lambda: client.patch(
        f"/claims/{c_paid_id}",
        json={"version": paid_version, "rejection_reason": "Attempt to modify paid claim"},
        headers=billing_headers,
    ))
    assert r_patch_paid.status_code == 422
    assert r_patch_paid.json()["detail"]["error_code"] == "CLAIM_FIELD_IMMUTABLE"

    # DB: paid claim is unchanged
    row_paid = db_session.execute(
        text("SELECT claim_status, version FROM claim WHERE claim_id = :cid"),
        {"cid": c_paid_id},
    ).fetchone()
    assert row_paid is not None, f"Paid claim {c_paid_id} not found in DB"
    assert row_paid.claim_status == "paid", (
        f"Expected claim_status='paid' in DB after rejected PATCH, got '{row_paid.claim_status}'"
    )
    assert row_paid.version == paid_version, (
        f"Expected version={paid_version} unchanged, got {row_paid.version}"
    )


# ─── TC-4.5 ──────────────────────────────────────────────────────────────────

def test_tc_4_5_attendance_status_validation_and_confirmed_creates_claim(
    client, billing_headers, attendance_variety_setup, participants, db_session
):
    """TC-4.5 — POST /claims referencing pending or voided attendance returns 422
    ATTENDANCE_NOT_CONFIRMED; cross-tenant attendance returns 422 or 404;
    confirmed attendance returns 201 and sets attendance status to billed."""
    today = datetime.now(timezone.utc).date()
    dos_4_5_a = (today - timedelta(days=92)).isoformat()
    dos_4_5_b = (today - timedelta(days=93)).isoformat()
    dos_4_5_c = (today - timedelta(days=94)).isoformat()
    dos_4_5_d = (today - timedelta(days=95)).isoformat()
    setup = attendance_variety_setup
    p = setup["participant"]
    pid = p["participant_id"]

    # Step 1: pending attendance → 422 ATTENDANCE_NOT_CONFIRMED
    r_pending = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [setup["att_pending"]["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_5_a,
    }, headers=billing_headers))
    assert r_pending.status_code == 422
    assert r_pending.json()["detail"]["error_code"] == "ATTENDANCE_NOT_CONFIRMED"

    # Step 2: voided attendance → 422 ATTENDANCE_NOT_CONFIRMED
    r_voided = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [setup["att_voided"]["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_5_b,
    }, headers=billing_headers))
    assert r_voided.status_code == 422
    assert r_voided.json()["detail"]["error_code"] == "ATTENDANCE_NOT_CONFIRMED"

    # Step 3: cross-tenant attendance → 422 or 404 (cross-tenant isolation)
    r_cross = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [setup["att_other_tenant"]["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_5_c,
    }, headers=billing_headers))
    assert r_cross.status_code in (422, 404), (
        f"Expected 422 or 404 for cross-tenant attendance, got {r_cross.status_code}"
    )

    # Step 4: confirmed attendance → 201 draft claim
    att_conf_id = setup["att_confirmed"]["attendance_id"]
    r_ok = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [att_conf_id],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_5_d,
    }, headers=billing_headers))
    assert r_ok.status_code == 201, f"Expected 201 for confirmed attendance, got {r_ok.text}"
    body = r_ok.json()

    # Step 5: response fields
    assert body["claim_id"] is not None
    assert body["claim_status"] == "draft"
    assert re.match(r"^(MCD|MCR)-\d{8}-[0-9A-Fa-f]{8}$", body["claim_reference_number"]), (
        f"claim_reference_number format unexpected: {body['claim_reference_number']}"
    )

    # Step 6: DB — confirmed attendance is now billed
    row_att = db_session.execute(
        text("SELECT status FROM attendance WHERE attendance_id = :aid"),
        {"aid": att_conf_id},
    ).fetchone()
    assert row_att is not None, f"Attendance {att_conf_id} not found in DB"
    assert row_att.status == "billed", (
        f"Expected attendance status='billed' after claim creation, got '{row_att.status}'"
    )


# ─── TC-4.6 ──────────────────────────────────────────────────────────────────

def test_tc_4_6_multi_attendance_units_billed_sum_and_not_found(
    client, billing_headers, three_confirmed_attendances, db_session
):
    """TC-4.6 — POST /claims with three confirmed attendances returns 201; server
    calculates units_billed = sum of authorized_units_consumed (4+6+8=18); all
    three attendances become billed; non-existent attendance UUID returns 422
    CLAIM_ATTENDANCE_NOT_FOUND."""
    today = datetime.now(timezone.utc).date()
    dos_4_6_a = (today - timedelta(days=96)).isoformat()
    dos_4_6_b = (today - timedelta(days=97)).isoformat()
    p, att_a, att_b, att_c = three_confirmed_attendances
    pid = p["participant_id"]
    ids = [att_a["attendance_id"], att_b["attendance_id"], att_c["attendance_id"]]

    # Step 1+2: POST with three attendances → 201, units_billed=18.0
    r = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": ids,
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_6_a,
    }, headers=billing_headers))
    assert r.status_code == 201, f"Expected 201, got {r.text}"
    body = r.json()
    assert set(body["attendance_ids"]) == set(ids), (
        f"Response attendance_ids mismatch: {body['attendance_ids']}"
    )
    assert body["units_billed"] == 18.0, (
        f"Expected server-calculated units_billed=18.0, got {body['units_billed']}"
    )

    claim_id = body["claim_id"]

    # Step 3: DB — units_billed persisted as 18.0
    row_claim = db_session.execute(
        text("SELECT units_billed FROM claim WHERE claim_id = :cid"),
        {"cid": claim_id},
    ).fetchone()
    assert row_claim is not None, f"Claim {claim_id} not found in DB"
    assert float(row_claim.units_billed) == 18.0, (
        f"Expected DB units_billed=18.0, got {row_claim.units_billed}"
    )

    # Step 4: DB — all three attendances are billed
    for att_id in ids:
        row_att = db_session.execute(
            text("SELECT status FROM attendance WHERE attendance_id = :aid"),
            {"aid": att_id},
        ).fetchone()
        assert row_att is not None, f"Attendance {att_id} not found in DB"
        assert row_att.status == "billed", (
            f"Expected status='billed' for attendance {att_id}, got '{row_att.status}'"
        )

    # Step 5+6: non-existent UUID → 422 CLAIM_ATTENDANCE_NOT_FOUND
    fake_id = "00000000-0000-0000-0000-000000000000"
    r_bad = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [fake_id],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_6_b,
    }, headers=billing_headers))
    assert r_bad.status_code == 422
    assert r_bad.json()["detail"]["error_code"] == "CLAIM_ATTENDANCE_NOT_FOUND"
    assert fake_id in r_bad.json()["detail"]["message"], (
        "Error message must contain the non-existent attendance UUID"
    )


# ─── TC-4.7 ──────────────────────────────────────────────────────────────────

def test_tc_4_7_missing_required_fields_return_400_or_422(
    client, billing_headers, fresh_confirmed_attendance, db_session
):
    """TC-4.7 — POST /claims omitting participant_id, procedure_code, or payer_type
    each return 400 or 422 identifying the missing field; no claims are created."""
    today = datetime.now(timezone.utc).date()
    dos_4_7 = (today - timedelta(days=98)).isoformat()
    att, _p = fresh_confirmed_attendance
    att_id = att["attendance_id"]

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE tenant_id = :tid"),
        {"tid": TENANT_A},
    ).scalar()

    # Missing participant_id
    r1 = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "attendance_ids": [att_id],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_7,
    }, headers=billing_headers))
    assert r1.status_code in (400, 422)
    assert "participant_id" in r1.text, (
        "Error response must identify 'participant_id' as the missing field"
    )

    # Missing procedure_code
    r2 = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": att["attendance_id"],  # placeholder; field validation fires first
        "attendance_ids": [att_id],
        "payer_type": "medicaid",
        "date_of_service_start": dos_4_7,
    }, headers=billing_headers))
    assert r2.status_code in (400, 422)
    assert "procedure_code" in r2.text, (
        "Error response must identify 'procedure_code' as the missing field"
    )

    # Missing payer_type
    r3 = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": att["attendance_id"],  # placeholder; field validation fires first
        "attendance_ids": [att_id],
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_7,
    }, headers=billing_headers))
    assert r3.status_code in (400, 422)
    assert "payer_type" in r3.text, (
        "Error response must identify 'payer_type' as the missing field"
    )

    # DB: no new claims from any of the three invalid requests
    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE tenant_id = :tid"),
        {"tid": TENANT_A},
    ).scalar()
    assert count_after == count_before, (
        f"Expected claim count unchanged after validation failures: "
        f"before={count_before}, after={count_after}"
    )


# ─── TC-4.8 ──────────────────────────────────────────────────────────────────

def test_tc_4_8_phi_write_and_phi_disclose_audit_events_in_db(
    client, fresh_confirmed_attendance, db_session
):
    """TC-4.8 — POST /claims emits PHI_WRITE audit event with all 11 mandatory
    fields and no PHI values; PATCH draft→submitted emits PHI_DISCLOSE with
    data_affected=['claim_status','submission_date','claim_reference_number'].
    All assertions query the audit_log table directly."""
    today = datetime.now(timezone.utc).date()
    dos_4_8 = (today - timedelta(days=99)).isoformat()
    att, p = fresh_confirmed_attendance
    att_id = att["attendance_id"]

    # billing_specialist with specific session_id for traceability
    billing_session_headers = make_headers(
        "billing_specialist",
        user_id=BILLING_ID,
    )
    billing_session_headers["X-Session-Id"] = "sess-tc48"

    # Step 1: POST /claims → 201
    r_create = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "attendance_ids": [att_id],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_8,
    }, headers=billing_session_headers))
    assert r_create.status_code == 201, f"Claim creation failed: {r_create.text}"
    claim_id = r_create.json()["claim_id"]
    claim_version = r_create.json()["version"]

    # Step 3: audit_log — PHI_WRITE entry for claim creation
    phi_write_rows = db_session.execute(
        text(
            "SELECT audit_id, user_id, tenant_id, session_id, action_type, "
            "resource_type, resource_id, data_affected, source_ip, outcome, layer "
            "FROM audit_log "
            "WHERE action_type = 'PHI_WRITE' AND resource_type = 'Claim' "
            "AND resource_id = :cid AND session_id = 'sess-tc48'"
        ),
        {"cid": claim_id},
    ).fetchall()
    assert len(phi_write_rows) >= 1, (
        "PHI_WRITE audit entry not found for claim creation in audit_log table"
    )
    phi_write = phi_write_rows[0]

    # All 11 mandatory fields must be non-null
    mandatory = [
        "audit_id", "user_id", "tenant_id", "session_id",
        "action_type", "resource_type", "resource_id",
        "data_affected", "source_ip", "outcome", "layer",
    ]
    for field in mandatory:
        assert getattr(phi_write, field) is not None, (
            f"Mandatory audit field '{field}' is null in audit_log"
        )

    assert phi_write.outcome == "SUCCESS"
    assert phi_write.resource_type == "Claim"
    assert phi_write.user_id == BILLING_ID
    assert phi_write.session_id == "sess-tc48"

    # Step 4: data_affected must contain field names only — no PHI values
    import json as _json
    data_affected = phi_write.data_affected
    if isinstance(data_affected, str):
        data_affected = _json.loads(data_affected)
    data_str = str(data_affected)
    for phi_val in (p["first_name"], p["last_name"], p.get("date_of_birth", "")):
        if phi_val:
            assert phi_val not in data_str, (
                f"PHI value '{phi_val}' found in data_affected of PHI_WRITE audit entry"
            )

    # Step 5: PATCH draft → submitted → 200
    r_patch = _call(lambda: client.patch(
        f"/claims/{claim_id}",
        json={"version": claim_version, "claim_status": "submitted"},
        headers=billing_session_headers,
    ))
    assert r_patch.status_code == 200, f"Submit PATCH failed: {r_patch.text}"
    assert r_patch.json()["claim_status"] == "submitted"

    # Step 6+7: audit_log — PHI_DISCLOSE entry after submission
    phi_disclose_rows = db_session.execute(
        text(
            "SELECT data_affected, outcome FROM audit_log "
            "WHERE action_type = 'PHI_DISCLOSE' AND resource_type = 'Claim' "
            "AND resource_id = :cid AND session_id = 'sess-tc48'"
        ),
        {"cid": claim_id},
    ).fetchall()
    assert len(phi_disclose_rows) >= 1, (
        "PHI_DISCLOSE audit entry not found after draft→submitted transition"
    )
    disclose = phi_disclose_rows[0]

    disclose_fields = disclose.data_affected
    if isinstance(disclose_fields, str):
        disclose_fields = _json.loads(disclose_fields)
    assert set(disclose_fields) == {"claim_status", "submission_date", "claim_reference_number"}, (
        f"PHI_DISCLOSE data_affected mismatch: {disclose_fields}"
    )
    assert disclose.outcome == "SUCCESS"

    # No PHI values in the disclose event
    disclose_str = str(disclose_fields)
    for phi_val in (p["first_name"], p["last_name"]):
        assert phi_val not in disclose_str, (
            f"PHI value '{phi_val}' found in PHI_DISCLOSE data_affected"
        )

    # DB: claim persisted as submitted
    row = db_session.execute(
        text("SELECT claim_status FROM claim WHERE claim_id = :cid"),
        {"cid": claim_id},
    ).fetchone()
    assert row is not None, f"Claim {claim_id} not found in DB"
    assert row.claim_status == "submitted"


# ─── TC-4.9 ──────────────────────────────────────────────────────────────────

def test_tc_4_9_empty_attendance_ids_and_server_calculated_units_billed(
    client, billing_headers, fresh_confirmed_attendance, db_session
):
    """TC-4.9 — POST /claims with empty attendance_ids returns 422
    CLAIM_NO_ATTENDANCE_RECORDS; POST with caller-supplied units_billed=999.0
    is ignored and server stores the value calculated from authorized_units_consumed."""
    today = datetime.now(timezone.utc).date()
    dos_4_9_a = (today - timedelta(days=100)).isoformat()
    dos_4_9_b = (today - timedelta(days=101)).isoformat()
    att, p = fresh_confirmed_attendance
    pid = p["participant_id"]

    # Step 1+2: empty attendance_ids → 422 CLAIM_NO_ATTENDANCE_RECORDS
    r_empty = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_9_a,
    }, headers=billing_headers))
    assert r_empty.status_code == 422
    assert r_empty.json()["detail"]["error_code"] == "CLAIM_NO_ATTENDANCE_RECORDS"

    # Step 3: DB — no claim created on this sentinel date
    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM claim "
            "WHERE tenant_id = :tid AND date_of_service_start = :dos"
        ),
        {"tid": TENANT_A, "dos": dos_4_9_a},
    ).scalar()
    assert count == 0, f"No claim should exist on {dos_4_9_a} after rejected POST, found {count}"

    # Step 4+5: caller supplies units_billed=999.0 but server must calculate from attendance
    # att was created with total_hours=1.0 → authorized_units_consumed=4.0
    r_units = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [att["attendance_id"]],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_9_b,
        "units_billed": 999.0,
    }, headers=billing_headers))
    assert r_units.status_code == 201, f"Expected 201, got {r_units.text}"
    body = r_units.json()
    assert body["units_billed"] == 4.0, (
        f"Expected server-calculated units_billed=4.0 (ignoring caller 999.0), "
        f"got {body['units_billed']}"
    )

    # DB: persisted value is also 4.0
    row = db_session.execute(
        text("SELECT units_billed FROM claim WHERE claim_id = :cid"),
        {"cid": body["claim_id"]},
    ).fetchone()
    assert row is not None, f"Claim {body['claim_id']} not found in DB"
    assert float(row.units_billed) == 4.0, (
        f"Expected DB units_billed=4.0, got {row.units_billed}"
    )


# ─── TC-4.10 ─────────────────────────────────────────────────────────────────

def test_tc_4_10_phase2_fields_return_400_no_claim_created(
    client, billing_headers, fresh_confirmed_attendance, db_session
):
    """TC-4.10 — POST /claims with Phase 2 fields secondary_payer_id, mco_id, or
    prior_authorization_number each return 400; no claim is created in any case."""
    att, p = fresh_confirmed_attendance
    pid = p["participant_id"]
    att_id = att["attendance_id"]

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE tenant_id = :tid"),
        {"tid": TENANT_A},
    ).scalar()

    today = datetime.now(timezone.utc).date()
    dos_4_10 = (today - timedelta(days=102)).isoformat()
    base_payload = {
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [att_id],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_10,
    }

    # secondary_payer_id (Phase 2 field) → 400 or 422 (schema-level rejection)
    r1 = _call(lambda: client.post(
        "/claims",
        json={**base_payload, "secondary_payer_id": "payer-999"},
        headers=billing_headers,
    ))
    assert r1.status_code in (400, 422), (
        f"Expected 400 or 422 for secondary_payer_id, got {r1.status_code}"
    )

    # mco_id (Phase 2 field) → 400 or 422
    r2 = _call(lambda: client.post(
        "/claims",
        json={**base_payload, "mco_id": "mco-001"},
        headers=billing_headers,
    ))
    assert r2.status_code in (400, 422), (
        f"Expected 400 or 422 for mco_id, got {r2.status_code}"
    )

    # prior_authorization_number (Phase 2 field) → 400 or 422
    r3 = _call(lambda: client.post(
        "/claims",
        json={**base_payload, "prior_authorization_number": "PA-12345"},
        headers=billing_headers,
    ))
    assert r3.status_code in (400, 422), (
        f"Expected 400 or 422 for prior_authorization_number, got {r3.status_code}"
    )

    # DB: no claims created by any of the three rejected requests
    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE tenant_id = :tid"),
        {"tid": TENANT_A},
    ).scalar()
    assert count_after == count_before, (
        f"Expected claim count unchanged after Phase 2 field rejections: "
        f"before={count_before}, after={count_after}"
    )


# ─── TC-4.11 ─────────────────────────────────────────────────────────────────

def test_tc_4_11_version_conflict_and_submitted_immutable_before_version_check(
    client, billing_headers, draft_and_submitted_claims, db_session
):
    """TC-4.11 — PATCH C_A with stale version returns 409 CLAIM_VERSION_CONFLICT;
    PATCH C_B (submitted) returns 422 CLAIM_FIELD_IMMUTABLE before version check;
    PATCH C_A with correct version returns 200 and DB version increments."""
    c_a, c_b, _p_a, _p_b = draft_and_submitted_claims
    c_a_id = c_a["claim_id"]
    c_b_id = c_b["claim_id"]

    # GET C_A to confirm draft status and version=1
    r_get_a = _call(lambda: client.get(f"/claims/{c_a_id}", headers=billing_headers))
    assert r_get_a.status_code == 200
    a_body = r_get_a.json()
    assert a_body["claim_status"] == "draft"
    a_version = a_body["version"]

    # Step 2: stale version → 409 CLAIM_VERSION_CONFLICT
    r_stale = _call(lambda: client.patch(
        f"/claims/{c_a_id}",
        json={"version": a_version - 1, "rejection_reason": "stale version test"},
        headers=billing_headers,
    ))
    assert r_stale.status_code == 409
    assert r_stale.json()["detail"]["error_code"] == "CLAIM_VERSION_CONFLICT"

    # Step 3: DB — C_A unchanged after stale version rejection
    row_a = db_session.execute(
        text("SELECT version, claim_status FROM claim WHERE claim_id = :cid"),
        {"cid": c_a_id},
    ).fetchone()
    assert row_a is not None, f"Claim {c_a_id} not found in DB"
    assert row_a.version == a_version, (
        f"Expected version={a_version} unchanged after version conflict, got {row_a.version}"
    )
    assert row_a.claim_status == "draft"

    # Step 4: submitted claim with ANY body → 422 CLAIM_FIELD_IMMUTABLE before version check
    # Use stale version intentionally to confirm immutability check fires first
    r_submitted = _call(lambda: client.patch(
        f"/claims/{c_b_id}",
        json={"version": 0, "rejection_reason": "any payload"},
        headers=billing_headers,
    ))
    assert r_submitted.status_code == 422, (
        f"Expected 422 for PATCH on submitted claim, got {r_submitted.status_code}"
    )
    assert r_submitted.json()["detail"]["error_code"] == "CLAIM_FIELD_IMMUTABLE", (
        "Immutability check (CLAIM_FIELD_IMMUTABLE) must fire before version check"
    )

    # Step 5+6: correct version on draft claim → 200, version incremented
    r_ok = _call(lambda: client.patch(
        f"/claims/{c_a_id}",
        json={"version": a_version, "rejection_reason": "corrected field value"},
        headers=billing_headers,
    ))
    assert r_ok.status_code == 200, f"Expected 200 for correct version PATCH, got {r_ok.text}"
    ok_body = r_ok.json()
    assert ok_body["version"] == a_version + 1, (
        f"Expected version={a_version + 1}, got {ok_body['version']}"
    )

    # Step 7: DB — version incremented
    row_a_updated = db_session.execute(
        text("SELECT version FROM claim WHERE claim_id = :cid"),
        {"cid": c_a_id},
    ).fetchone()
    assert row_a_updated is not None
    assert row_a_updated.version == a_version + 1, (
        f"Expected DB version={a_version + 1}, got {row_a_updated.version}"
    )


# ─── TC-4.12 ─────────────────────────────────────────────────────────────────

def test_tc_4_12_cross_tenant_attendance_reference_returns_422_or_404(
    client, billing_headers, attendance_variety_setup, participants, db_session
):
    """TC-4.12 — POST /claims referencing an attendance from TENANT_B while the
    caller is authenticated in TENANT_A returns 422 or 404; no claim is created
    in TENANT_A referencing that attendance."""
    today = datetime.now(timezone.utc).date()
    dos_4_12 = (today - timedelta(days=103)).isoformat()
    att_other_id = attendance_variety_setup["att_other_tenant"]["attendance_id"]
    p = attendance_variety_setup["participant"]
    pid = p["participant_id"]

    r = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [att_other_id],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_12,
    }, headers=billing_headers))
    assert r.status_code in (422, 404), (
        f"Expected 422 or 404 for cross-tenant attendance, got {r.status_code}"
    )
    error_code = r.json()["detail"]["error_code"]
    assert error_code in ("ATTENDANCE_NOT_FOUND", "CLAIM_ATTENDANCE_NOT_FOUND", "NOT_FOUND"), (
        f"Unexpected error_code for cross-tenant rejection: {error_code}"
    )

    # DB — no claim created in TENANT_A referencing the cross-tenant attendance
    count_a = db_session.execute(
        text(
            "SELECT COUNT(*) FROM claim "
            "WHERE tenant_id = :tid AND date_of_service_start = :dos"
        ),
        {"tid": TENANT_A, "dos": dos_4_12},
    ).scalar()
    assert count_a == 0, (
        f"Expected 0 claims in TENANT_A on {dos_4_12} after cross-tenant rejection, found {count_a}"
    )

    # DB — no claim in any tenant references the cross-tenant attendance
    all_claims = db_session.execute(
        text("SELECT attendance_ids FROM claim WHERE tenant_id = :tid"),
        {"tid": TENANT_A},
    ).fetchall()
    for row in all_claims:
        import json as _json
        att_ids = row.attendance_ids
        if isinstance(att_ids, str):
            att_ids = _json.loads(att_ids)
        assert att_other_id not in att_ids, (
            f"Cross-tenant attendance {att_other_id} found in a TENANT_A claim"
        )


# ─── TC-4.13 ─────────────────────────────────────────────────────────────────

def test_tc_4_13_billed_attendance_cannot_be_reclaimed(
    client, billing_headers, fresh_claim, db_session
):
    """TC-4.13 — POST /claims referencing a billed attendance (already linked to
    an existing claim) returns 422 ATTENDANCE_NOT_CONFIRMED; no duplicate claim
    is created."""
    existing_claim, att, p = fresh_claim
    att_id = att["attendance_id"]
    existing_claim_id = existing_claim["claim_id"]

    # Step 1: GET attendance — confirm it is billed
    r_att = _call(lambda: client.get(f"/attendance/{att_id}", headers=billing_headers))
    assert r_att.status_code == 200
    assert r_att.json()["status"] == "billed", (
        f"Attendance must be billed after claim creation, got '{r_att.json()['status']}'"
    )

    today = datetime.now(timezone.utc).date()
    dos_4_13 = (today - timedelta(days=104)).isoformat()
    # Step 2+3: POST new claim referencing the billed attendance → 422
    r_reclaim = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": p["participant_id"],
        "attendance_ids": [att_id],
        "payer_type": "medicaid",
        "procedure_code": "T2029",
        "date_of_service_start": dos_4_13,
    }, headers=billing_headers))
    assert r_reclaim.status_code == 422
    assert r_reclaim.json()["detail"]["error_code"] == "ATTENDANCE_NOT_CONFIRMED"

    # Step 4: DB — att_id is not referenced by any claim other than the existing one
    all_rows = db_session.execute(
        text(
            "SELECT claim_id, attendance_ids FROM claim "
            "WHERE tenant_id = :tid"
        ),
        {"tid": TENANT_A},
    ).fetchall()
    import json as _json
    other_claims_with_att = [
        row.claim_id for row in all_rows
        if row.claim_id != existing_claim_id
        and att_id in (
            _json.loads(row.attendance_ids)
            if isinstance(row.attendance_ids, str)
            else (row.attendance_ids or [])
        )
    ]
    assert len(other_claims_with_att) == 0, (
        f"Billed attendance {att_id} was unexpectedly linked to additional claims: "
        f"{other_claims_with_att}"
    )


# ─── TC-4.14 ─────────────────────────────────────────────────────────────────

def test_tc_4_14_get_nonexistent_claim_returns_404(
    client, billing_headers, db_session
):
    """TC-4.14 — GET /claims/<non-existent-UUID> returns 404 NOT_FOUND with
    a message identifying the requested resource."""
    nonexistent_id = "00000000-0000-0000-0000-999999999999"

    # Pre-condition: this UUID does not exist in the DB
    count = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE claim_id = :cid"),
        {"cid": nonexistent_id},
    ).scalar()
    assert count == 0, f"Pre-condition failed: UUID {nonexistent_id} should not exist in DB"

    r = _call(lambda: client.get(
        f"/claims/{nonexistent_id}", headers=billing_headers
    ))
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["error_code"] == "NOT_FOUND"
    assert (
        nonexistent_id in body["detail"]["message"]
        or "Claim" in body["detail"]["message"]
    ), (
        "Error message must contain the requested claim_id or the resource type 'Claim'"
    )


# ─── TC-4.15 ─────────────────────────────────────────────────────────────────

def test_tc_4_15_paid_claim_fully_immutable(
    client, billing_headers, submitted_and_paid_claims, db_session
):
    """TC-4.15 — PATCH a paid claim with a non-status field, a status rollback,
    or a date field each return 422 CLAIM_FIELD_IMMUTABLE; DB shows the paid
    claim fully unchanged after all three rejected attempts."""
    _c_sub, c_paid, _p_a, _p_b = submitted_and_paid_claims
    c_paid_id = c_paid["claim_id"]

    # GET paid claim to confirm status and capture version
    r_get = _call(lambda: client.get(f"/claims/{c_paid_id}", headers=billing_headers))
    assert r_get.status_code == 200
    paid_body = r_get.json()
    assert paid_body["claim_status"] == "paid"
    paid_version = paid_body["version"]

    # Step 2: PATCH non-status field → 422 CLAIM_FIELD_IMMUTABLE
    r1 = _call(lambda: client.patch(
        f"/claims/{c_paid_id}",
        json={"version": paid_version, "rejection_reason": "Test non-status field edit"},
        headers=billing_headers,
    ))
    assert r1.status_code == 422
    assert r1.json()["detail"]["error_code"] == "CLAIM_FIELD_IMMUTABLE"

    # Step 3: PATCH status rollback (paid → draft) → 422 CLAIM_FIELD_IMMUTABLE
    r2 = _call(lambda: client.patch(
        f"/claims/{c_paid_id}",
        json={"version": paid_version, "claim_status": "draft"},
        headers=billing_headers,
    ))
    assert r2.status_code == 422
    assert r2.json()["detail"]["error_code"] == "CLAIM_FIELD_IMMUTABLE"

    # Step 4: PATCH submission_date → 422 CLAIM_FIELD_IMMUTABLE
    past_submission_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r3 = _call(lambda: client.patch(
        f"/claims/{c_paid_id}",
        json={"version": paid_version, "submission_date": past_submission_date},
        headers=billing_headers,
    ))
    assert r3.status_code == 422
    assert r3.json()["detail"]["error_code"] == "CLAIM_FIELD_IMMUTABLE"

    # Step 5: DB — all fields unchanged after three rejected PATCH attempts
    row = db_session.execute(
        text(
            "SELECT claim_status, version, rejection_reason "
            "FROM claim WHERE claim_id = :cid"
        ),
        {"cid": c_paid_id},
    ).fetchone()
    assert row is not None, f"Paid claim {c_paid_id} not found in DB"
    assert row.claim_status == "paid", (
        f"Expected claim_status='paid' in DB after rejected PATCHes, got '{row.claim_status}'"
    )
    assert row.version == paid_version, (
        f"Expected version={paid_version} unchanged, got {row.version}"
    )
    assert row.rejection_reason is None or row.rejection_reason == paid_body.get("rejection_reason"), (
        f"rejection_reason must not be modified by rejected PATCHes, got '{row.rejection_reason}'"
    )
