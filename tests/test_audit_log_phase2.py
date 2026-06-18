"""
test_audit_log_phase2.py — Phase 2 audit pipeline completeness tests.

Regulatory scope: HIPAA · 42 CFR Part 2 §2.31 · §2.13(b)
"""
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from helpers import (
    TENANT_A, ADMIN_ID, COORDINATOR_ID,
    make_headers, make_participant, make_care_plan,
)

_ADMIN = make_headers("program_administrator", user_id=ADMIN_ID)
_COORD = make_headers("care_coordinator", user_id=COORDINATOR_ID)


def _unique_medicaid():
    return f"AP2-{uuid.uuid4().hex[:8].upper()}"


# ─── AP2-1 ────────────────────────────────────────────────────────────────────


def test_audit_p2_1_care_plan_sud_phi_write_mandatory_fields(
    client, coordinator_headers, db_session, participants, users
):
    """AP2-1 — CarePlan write for SUD participant produces PHI_WRITE with mandatory fields."""
    p_sud = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid(),
                            is_sud_record=True)
    cp = make_care_plan(client, coordinator_headers, p_sud["participant_id"],
                        notes="SUD clinical context")

    row = db_session.execute(
        text(
            "SELECT audit_id, timestamp, user_id, tenant_id, session_id, "
            "action_type, resource_type, resource_id, data_affected, "
            "source_ip, outcome, layer, retention_years "
            "FROM audit_log WHERE resource_id = :rid AND action_type = 'PHI_WRITE' "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"rid": cp["care_plan_id"]},
    ).fetchone()
    assert row is not None
    assert row.audit_id is not None
    assert row.timestamp is not None
    assert row.user_id is not None
    assert row.tenant_id == TENANT_A
    assert row.session_id is not None
    assert row.action_type == "PHI_WRITE"
    assert row.resource_type == "CarePlan"
    assert row.resource_id == cp["care_plan_id"]
    assert row.data_affected is not None
    assert row.source_ip is not None
    assert row.outcome == "SUCCESS"
    assert row.layer is not None
    assert row.retention_years >= 6

    da_str = str(row.data_affected)
    assert p_sud["participant_id"] not in da_str


# ─── AP2-2 ────────────────────────────────────────────────────────────────────


def test_audit_p2_2_care_plan_sud_phi_read_before_response(
    client, coordinator_headers, db_session, participants, users
):
    """AP2-2 — CarePlan read for SUD participant produces PHI_READ audit event."""
    p_sud = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid(),
                            is_sud_record=True)
    cp = make_care_plan(client, coordinator_headers, p_sud["participant_id"])

    r = client.get(f"/care-plans/{cp['care_plan_id']}", headers=coordinator_headers)
    assert r.status_code == 200

    row = db_session.execute(
        text(
            "SELECT action_type, resource_type, resource_id, outcome "
            "FROM audit_log WHERE resource_id = :rid AND action_type = 'PHI_READ' "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"rid": cp["care_plan_id"]},
    ).fetchone()
    assert row is not None
    assert row.action_type == "PHI_READ"
    assert row.resource_type == "CarePlan"
    assert row.outcome == "SUCCESS"
