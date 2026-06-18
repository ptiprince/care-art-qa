"""
test_consent_gate.py — Consent gate integration tests.

Regulatory scope: HIPAA · 42 CFR Part 2 §2.31
"""
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from helpers import (
    TENANT_A, ADMIN_ID, COORDINATOR_ID,
    make_headers, make_participant, make_care_plan, make_consent,
)

_ADMIN = make_headers("program_administrator", user_id=ADMIN_ID)
_COORD = make_headers("care_coordinator", user_id=COORDINATOR_ID)


def _unique_medicaid():
    return f"CG-{uuid.uuid4().hex[:8].upper()}"


# ─── CG-1 ────────────────────────────────────────────────────────────────────


def test_cg_1_care_plan_fhir_blocked_without_ehr_consent(
    client, coordinator_headers, db_session, participants, users
):
    """CG-1 — FHIR CarePlan transmission blocked without ehr consent; CONSENT_CHECK DENIED."""
    p_sud = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid(),
                            is_sud_record=True)
    cp = make_care_plan(client, coordinator_headers, p_sud["participant_id"])

    r = client.post(
        f"/care-plans/{cp['care_plan_id']}/fhir-transmit",
        headers=coordinator_headers,
    )
    assert r.status_code == 403

    audit = db_session.execute(
        text(
            "SELECT action_type, outcome "
            "FROM audit_log WHERE resource_id = :rid "
            "AND action_type = 'CONSENT_CHECK' ORDER BY timestamp DESC LIMIT 1"
        ),
        {"rid": cp["care_plan_id"]},
    ).fetchone()
    assert audit is not None
    assert audit.outcome == "DENIED"


# ─── CG-2 ────────────────────────────────────────────────────────────────────


def test_cg_2_care_plan_fhir_permitted_with_valid_ehr_consent(
    client, coordinator_headers, db_session, participants, users
):
    """CG-2 — FHIR CarePlan transmission permitted with valid ehr consent; CONSENT_CHECK ALLOWED."""
    p_sud = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid(),
                            is_sud_record=True)
    cp = make_care_plan(client, coordinator_headers, p_sud["participant_id"])

    make_consent(client, coordinator_headers, p_sud["participant_id"],
                 disclosure_recipient_type="ehr")

    r = client.post(
        f"/care-plans/{cp['care_plan_id']}/fhir-transmit",
        headers=coordinator_headers,
    )
    assert r.status_code == 200
    assert r.json()["consent"] == "allowed"

    audit = db_session.execute(
        text(
            "SELECT action_type, outcome "
            "FROM audit_log WHERE resource_id = :rid "
            "AND action_type = 'CONSENT_CHECK' AND outcome = 'ALLOWED' "
            "ORDER BY timestamp DESC LIMIT 1"
        ),
        {"rid": cp["care_plan_id"]},
    ).fetchone()
    assert audit is not None
    assert audit.outcome == "ALLOWED"
