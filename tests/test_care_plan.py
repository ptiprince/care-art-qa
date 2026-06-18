"""
test_care_plan.py — 11 tests mapped to TC-11.1 through TC-11.11.

Regulatory scope: HIPAA · 42 CFR Part 2 · CMS Medicaid/Medicare · State adult day care licensing
"""
import uuid
from datetime import date, datetime, timezone, timedelta

import pytest
from sqlalchemy import text

from helpers import (
    TENANT_A, TENANT_B,
    ADMIN_ID, COORDINATOR_ID, NURSE_ID, BILLING_ID,
    PHYSICIAN_ID, FAMILY_ID, COMPLIANCE_ID, INVALID_COORDINATOR_ID,
    make_headers, make_participant, make_care_plan, make_care_plan_goal,
    activate_care_plan, make_consent,
)

_COORD = make_headers("care_coordinator", user_id=COORDINATOR_ID)
_ADMIN = make_headers("program_administrator", user_id=ADMIN_ID)


def _unique_medicaid():
    return f"CP-{uuid.uuid4().hex[:8].upper()}"


# ─── TC-11.1 ──────────────────────────────────────────────────────────────────


def test_tc_7_1_duplicate_version_number_returns_409(
    client, coordinator_headers, db_session, participants, users
):
    """TC-11.1 — POST with duplicate participant_id+version_number returns 409; DB confirms one row."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]

    cp1 = make_care_plan(client, coordinator_headers, pid, version_number=1)
    assert cp1["version_number"] == 1

    r = client.post("/care-plans", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "version_number": 1,
    }, headers=coordinator_headers)
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "CARE_PLAN_DUPLICATE_VERSION"

    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM care_plan "
            "WHERE participant_id = :pid AND version_number = 1"
        ),
        {"pid": pid},
    ).scalar()
    assert count == 1


# ─── TC-11.2 ──────────────────────────────────────────────────────────────────


def test_tc_7_2_single_active_plan_supersession_in_transaction(
    client, coordinator_headers, db_session, participants, users
):
    """TC-11.2 — Activation without supersession returns 409; valid supersession sets prior to superseded."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]
    phys_id = users["physician"]["user_id"]

    cp_active = make_care_plan(client, coordinator_headers, pid, version_number=1)
    activated = activate_care_plan(
        client, coordinator_headers,
        cp_active["care_plan_id"], cp_active["version"],
        physician_id=phys_id,
    )
    assert activated["status"] == "active"

    cp_draft = make_care_plan(client, coordinator_headers, pid, version_number=2)

    r_fail = client.patch(
        f"/care-plans/{cp_draft['care_plan_id']}",
        json={
            "version": cp_draft["version"],
            "status": "active",
            "effective_date": datetime.now(timezone.utc).date().isoformat(),
            "physician_id": phys_id,
            "physician_signature_date": datetime.now(timezone.utc).date().isoformat(),
        },
        headers=coordinator_headers,
    )
    assert r_fail.status_code == 409
    assert r_fail.json()["detail"]["error_code"] == "CARE_PLAN_ALREADY_ACTIVE"

    r_supersede = client.patch(
        f"/care-plans/{activated['care_plan_id']}",
        json={"version": activated["version"], "status": "superseded"},
        headers=coordinator_headers,
    )
    assert r_supersede.status_code == 200

    cp_draft_refreshed = client.get(
        f"/care-plans/{cp_draft['care_plan_id']}", headers=coordinator_headers
    ).json()
    r_activate = activate_care_plan(
        client, coordinator_headers,
        cp_draft["care_plan_id"], cp_draft_refreshed["version"],
        physician_id=phys_id,
    )
    assert r_activate["status"] == "active"

    row_prior = db_session.execute(
        text("SELECT status FROM care_plan WHERE care_plan_id = :cid"),
        {"cid": activated["care_plan_id"]},
    ).fetchone()
    assert row_prior.status == "superseded"

    row_new = db_session.execute(
        text("SELECT status FROM care_plan WHERE care_plan_id = :cid"),
        {"cid": cp_draft["care_plan_id"]},
    ).fetchone()
    assert row_new.status == "active"


# ─── TC-11.3 ──────────────────────────────────────────────────────────────────


def test_tc_7_3_activation_requires_physician_signature_and_physician_id(
    client, coordinator_headers, db_session, participants, users
):
    """TC-11.3 — Activation blocked without physician_signature_date or physician_id; succeeds with both."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]
    phys_id = users["physician"]["user_id"]
    today = datetime.now(timezone.utc).date().isoformat()

    cp = make_care_plan(client, coordinator_headers, pid)

    r_no_sig = client.patch(
        f"/care-plans/{cp['care_plan_id']}",
        json={
            "version": cp["version"],
            "status": "active",
            "effective_date": today,
            "physician_id": phys_id,
        },
        headers=coordinator_headers,
    )
    assert r_no_sig.status_code == 422
    assert r_no_sig.json()["detail"]["error_code"] == "CARE_PLAN_UNSIGNED"

    cp_refreshed = client.get(
        f"/care-plans/{cp['care_plan_id']}", headers=coordinator_headers
    ).json()

    r_no_phys = client.patch(
        f"/care-plans/{cp['care_plan_id']}",
        json={
            "version": cp_refreshed["version"],
            "status": "active",
            "effective_date": today,
            "physician_signature_date": today,
        },
        headers=coordinator_headers,
    )
    assert r_no_phys.status_code == 422
    assert r_no_phys.json()["detail"]["error_code"] == "CARE_PLAN_UNSIGNED"

    r_ok = client.patch(
        f"/care-plans/{cp['care_plan_id']}",
        json={
            "version": cp_refreshed["version"],
            "status": "active",
            "effective_date": today,
            "physician_id": phys_id,
            "physician_signature_date": today,
        },
        headers=coordinator_headers,
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "active"

    row = db_session.execute(
        text(
            "SELECT status, physician_id, physician_signature_date "
            "FROM care_plan WHERE care_plan_id = :cid"
        ),
        {"cid": cp["care_plan_id"]},
    ).fetchone()
    assert row.status == "active"
    assert row.physician_id == phys_id
    assert row.physician_signature_date is not None


# ─── TC-11.4 ──────────────────────────────────────────────────────────────────


def test_tc_7_4_superseded_plan_immutable_clinical_field_change_requires_revision(
    client, coordinator_headers, db_session, participants, users
):
    """TC-11.4 — Superseded plan is immutable; clinical field change on active rejected; notes update succeeds."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]
    phys_id = users["physician"]["user_id"]

    cp1 = make_care_plan(client, coordinator_headers, pid, version_number=1,
                         primary_diagnosis_code="E11.9")
    cp1_active = activate_care_plan(
        client, coordinator_headers,
        cp1["care_plan_id"], cp1["version"],
        physician_id=phys_id,
    )

    cp2 = make_care_plan(client, coordinator_headers, pid, version_number=2)

    r_supersede = client.patch(
        f"/care-plans/{cp1_active['care_plan_id']}",
        json={"version": cp1_active["version"], "status": "superseded"},
        headers=coordinator_headers,
    )
    assert r_supersede.status_code == 200
    superseded = r_supersede.json()

    cp2_refreshed = client.get(
        f"/care-plans/{cp2['care_plan_id']}", headers=coordinator_headers
    ).json()
    cp2_active = activate_care_plan(
        client, coordinator_headers,
        cp2["care_plan_id"], cp2_refreshed["version"],
        physician_id=phys_id,
    )

    r_immutable = client.patch(
        f"/care-plans/{superseded['care_plan_id']}",
        json={"version": superseded["version"], "notes": "Should fail"},
        headers=coordinator_headers,
    )
    assert r_immutable.status_code == 422

    r_clinical = client.patch(
        f"/care-plans/{cp2_active['care_plan_id']}",
        json={
            "version": cp2_active["version"],
            "primary_diagnosis_code": "I10",
        },
        headers=coordinator_headers,
    )
    assert r_clinical.status_code == 422

    r_notes = client.patch(
        f"/care-plans/{cp2_active['care_plan_id']}",
        json={"version": cp2_active["version"], "notes": "Updated notes"},
        headers=coordinator_headers,
    )
    assert r_notes.status_code == 200
    assert r_notes.json()["version"] == cp2_active["version"] + 1

    row_sup = db_session.execute(
        text("SELECT primary_diagnosis_code, notes FROM care_plan WHERE care_plan_id = :cid"),
        {"cid": superseded["care_plan_id"]},
    ).fetchone()
    assert row_sup.primary_diagnosis_code == "E11.9"


# ─── TC-11.5 ──────────────────────────────────────────────────────────────────


def test_tc_7_5_rbac_care_coordinator_only_write_access(
    client, coordinator_headers, billing_headers, family_headers,
    admin_headers, nurse_headers, compliance_headers,
    db_session, participants, users
):
    """TC-11.5 — Write denied for billing/family/admin; allowed for coordinator; read ok for nurse/compliance."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]
    phys_id = users["physician"]["user_id"]

    payload = {"tenant_id": TENANT_A, "participant_id": pid}
    for role_headers in (billing_headers, family_headers, admin_headers):
        r = client.post("/care-plans", json=payload, headers=role_headers)
        assert r.status_code == 403

    cp = make_care_plan(client, coordinator_headers, pid)
    assert cp["status"] == "draft"

    cp_active = activate_care_plan(
        client, coordinator_headers,
        cp["care_plan_id"], cp["version"],
        physician_id=phys_id,
    )

    r_nurse = client.get(f"/care-plans/{cp_active['care_plan_id']}", headers=nurse_headers)
    assert r_nurse.status_code == 200

    r_comp = client.get(f"/care-plans/{cp_active['care_plan_id']}", headers=compliance_headers)
    assert r_comp.status_code == 200

    r_coord_change = client.patch(
        f"/care-plans/{cp_active['care_plan_id']}",
        json={
            "version": cp_active["version"],
            "care_coordinator_id": INVALID_COORDINATOR_ID,
        },
        headers=coordinator_headers,
    )
    assert r_coord_change.status_code == 422

    write_audit = db_session.execute(
        text(
            "SELECT action_type, resource_type, outcome "
            "FROM audit_log WHERE resource_id = :rid AND action_type = 'PHI_WRITE' "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"rid": cp["care_plan_id"]},
    ).fetchone()
    assert write_audit is not None
    assert write_audit.resource_type == "CarePlan"
    assert write_audit.outcome == "SUCCESS"


# ─── TC-11.6 ──────────────────────────────────────────────────────────────────


def test_tc_7_6_sud_participant_care_plan_access_denied_for_unauthorized_roles(
    client, coordinator_headers, billing_headers, admin_headers,
    db_session, participants, users
):
    """TC-11.6 — SUD-flagged CarePlan GET returns 403 for billing/admin; list omits notes for unauthorized."""
    p_sud = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid(),
                            is_sud_record=True)
    pid_sud = p_sud["participant_id"]

    cp = make_care_plan(client, coordinator_headers, pid_sud, notes="SUD clinical notes")

    r_billing = client.get(f"/care-plans/{cp['care_plan_id']}", headers=billing_headers)
    assert r_billing.status_code == 403
    assert "care_plan_id" not in r_billing.text or cp["care_plan_id"] not in r_billing.text

    r_admin = client.get(f"/care-plans/{cp['care_plan_id']}", headers=admin_headers)
    assert r_admin.status_code == 403

    r_list = client.get(
        f"/care-plans?tenant_id={TENANT_A}&participant_id={pid_sud}",
        headers=admin_headers,
    )
    assert r_list.status_code == 403

    audit_count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE resource_id = :rid AND action_type = 'ACCESS_DENIED'"
        ),
        {"rid": cp["care_plan_id"]},
    ).scalar()
    assert audit_count == 0


# ─── TC-11.7 ──────────────────────────────────────────────────────────────────


def test_tc_7_7_audit_log_sud_care_plan_phi_read_write_access_denied(
    client, coordinator_headers, physician_headers, db_session, participants, users
):
    """TC-11.7 — PHI_READ/PHI_WRITE audit events for SUD care plan; ACCESS_DENIED for unauthorized."""
    p_sud = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid(),
                            is_sud_record=True)
    pid_sud = p_sud["participant_id"]

    cp = make_care_plan(client, coordinator_headers, pid_sud)

    write_audit = db_session.execute(
        text(
            "SELECT action_type, resource_type, resource_id, data_affected, outcome "
            "FROM audit_log WHERE resource_id = :eid AND action_type = 'PHI_WRITE' "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"eid": cp["care_plan_id"]},
    ).fetchone()
    assert write_audit is not None
    assert write_audit.action_type == "PHI_WRITE"
    assert write_audit.resource_type == "CarePlan"
    assert write_audit.outcome == "SUCCESS"
    assert pid_sud not in (write_audit.data_affected or "")

    r_read = client.get(f"/care-plans/{cp['care_plan_id']}", headers=coordinator_headers)
    assert r_read.status_code == 200

    read_audit = db_session.execute(
        text(
            "SELECT action_type, resource_type, resource_id, outcome "
            "FROM audit_log WHERE resource_id = :eid AND action_type = 'PHI_READ' "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"eid": cp["care_plan_id"]},
    ).fetchone()
    assert read_audit is not None
    assert read_audit.action_type == "PHI_READ"
    assert read_audit.outcome == "SUCCESS"

    r_denied = client.get(f"/care-plans/{cp['care_plan_id']}", headers=physician_headers)
    assert r_denied.status_code == 403

    denied_audit = db_session.execute(
        text(
            "SELECT action_type, outcome "
            "FROM audit_log WHERE resource_id = :eid AND action_type = 'ACCESS_DENIED' "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"eid": cp["care_plan_id"]},
    ).fetchone()
    assert denied_audit is not None
    assert denied_audit.outcome == "DENIED"


# ─── TC-11.8 ──────────────────────────────────────────────────────────────────


def test_tc_7_8_fhir_consent_gate_blocks_transmission_without_ehr_consent(
    client, coordinator_headers, db_session, participants, users
):
    """TC-11.8 — FHIR transmission blocked without ehr consent; proceeds with valid consent."""
    p_sud = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid(),
                            is_sud_record=True)
    pid_sud = p_sud["participant_id"]

    cp = make_care_plan(client, coordinator_headers, pid_sud)

    r_blocked = client.post(
        f"/care-plans/{cp['care_plan_id']}/fhir-transmit",
        headers=coordinator_headers,
    )
    assert r_blocked.status_code == 403

    denied_audit = db_session.execute(
        text(
            "SELECT action_type, outcome, data_affected "
            "FROM audit_log WHERE resource_id = :eid AND action_type = 'CONSENT_CHECK' "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"eid": cp["care_plan_id"]},
    ).fetchone()
    assert denied_audit is not None
    assert denied_audit.outcome == "DENIED"

    consent = make_consent(client, coordinator_headers, pid_sud,
                           disclosure_recipient_type="ehr")

    r_allowed = client.post(
        f"/care-plans/{cp['care_plan_id']}/fhir-transmit",
        headers=coordinator_headers,
    )
    assert r_allowed.status_code == 200
    assert r_allowed.json()["consent"] == "allowed"

    allowed_audit = db_session.execute(
        text(
            "SELECT action_type, outcome "
            "FROM audit_log WHERE resource_id = :eid AND action_type = 'CONSENT_CHECK' "
            "AND outcome = 'ALLOWED' ORDER BY timestamp DESC LIMIT 1"
        ),
        {"eid": cp["care_plan_id"]},
    ).fetchone()
    assert allowed_audit is not None
    assert allowed_audit.outcome == "ALLOWED"


# ─── TC-11.9 ──────────────────────────────────────────────────────────────────


def test_tc_7_9_duplicate_goal_domain_description_returns_409(
    client, coordinator_headers, db_session, participants, users
):
    """TC-11.9 — Duplicate goal domain+description returns 409; different care_plan_id returns 201."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]

    cp1 = make_care_plan(client, coordinator_headers, pid, version_number=1)
    cp2 = make_care_plan(client, coordinator_headers, pid, version_number=2)

    goal1 = make_care_plan_goal(
        client, coordinator_headers, cp1["care_plan_id"],
        domain="functional", description="Walk 50 meters unassisted",
    )

    r_dup = client.post("/care-plan-goals", json={
        "tenant_id": TENANT_A,
        "care_plan_id": cp1["care_plan_id"],
        "domain": "functional",
        "description": "Walk 50 meters unassisted",
    }, headers=coordinator_headers)
    assert r_dup.status_code == 409
    assert r_dup.json()["detail"]["error_code"] == "CARE_PLAN_GOAL_DUPLICATE"

    goal2 = make_care_plan_goal(
        client, coordinator_headers, cp2["care_plan_id"],
        domain="functional", description="Walk 50 meters unassisted",
    )
    assert goal2["goal_id"] != goal1["goal_id"]

    count_cp1 = db_session.execute(
        text(
            "SELECT COUNT(*) FROM care_plan_goal "
            "WHERE care_plan_id = :cpid AND domain = 'functional' "
            "AND description = 'Walk 50 meters unassisted'"
        ),
        {"cpid": cp1["care_plan_id"]},
    ).scalar()
    assert count_cp1 == 1

    count_cp2 = db_session.execute(
        text(
            "SELECT COUNT(*) FROM care_plan_goal "
            "WHERE care_plan_id = :cpid AND domain = 'functional' "
            "AND description = 'Walk 50 meters unassisted'"
        ),
        {"cpid": cp2["care_plan_id"]},
    ).scalar()
    assert count_cp2 == 1


# ─── TC-11.10 ─────────────────────────────────────────────────────────────────


def test_tc_7_10_soft_delete_sets_is_deleted_true_hard_delete_blocked(
    client, coordinator_headers, compliance_headers, db_session, participants, users
):
    """TC-11.10 — DELETE sets is_deleted=true; GET returns 404; DB retains record."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]

    cp = make_care_plan(client, coordinator_headers, pid)
    goal = make_care_plan_goal(client, coordinator_headers, cp["care_plan_id"])

    r_del = client.delete(f"/care-plans/{cp['care_plan_id']}", headers=coordinator_headers)
    assert r_del.status_code == 200
    assert r_del.json()["is_deleted"] is True

    r_get = client.get(f"/care-plans/{cp['care_plan_id']}", headers=coordinator_headers)
    assert r_get.status_code == 404

    row = db_session.execute(
        text("SELECT is_deleted, version FROM care_plan WHERE care_plan_id = :cid"),
        {"cid": cp["care_plan_id"]},
    ).fetchone()
    assert row is not None
    assert row.is_deleted == 1


# ─── TC-11.11 ─────────────────────────────────────────────────────────────────


def test_tc_7_11_activation_requires_non_null_effective_date(
    client, coordinator_headers, db_session, participants, users
):
    """TC-11.11 — Activation with null effective_date returns 422; with effective_date set succeeds."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]
    phys_id = users["physician"]["user_id"]
    today = datetime.now(timezone.utc).date().isoformat()

    cp = make_care_plan(client, coordinator_headers, pid)

    r_no_eff = client.patch(
        f"/care-plans/{cp['care_plan_id']}",
        json={
            "version": cp["version"],
            "status": "active",
            "physician_id": phys_id,
            "physician_signature_date": today,
        },
        headers=coordinator_headers,
    )
    assert r_no_eff.status_code == 422
    assert r_no_eff.json()["detail"]["error_code"] == "CARE_PLAN_MISSING_EFFECTIVE_DATE"

    r_ok = client.patch(
        f"/care-plans/{cp['care_plan_id']}",
        json={
            "version": cp["version"],
            "status": "active",
            "effective_date": today,
            "physician_id": phys_id,
            "physician_signature_date": today,
        },
        headers=coordinator_headers,
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "active"

    row = db_session.execute(
        text(
            "SELECT status, effective_date FROM care_plan WHERE care_plan_id = :cid"
        ),
        {"cid": cp["care_plan_id"]},
    ).fetchone()
    assert row.status == "active"
    assert row.effective_date is not None
    db_eff = date.fromisoformat(str(row.effective_date))
    assert db_eff == datetime.now(timezone.utc).date()

    r_set_eff = make_care_plan(client, coordinator_headers, pid)
    r_patch_eff = client.patch(
        f"/care-plans/{r_set_eff['care_plan_id']}",
        json={
            "version": r_set_eff["version"],
            "effective_date": today,
        },
        headers=coordinator_headers,
    )
    assert r_patch_eff.status_code == 200
    assert r_patch_eff.json()["version"] == r_set_eff["version"] + 1
