"""
test_tenant_isolation_phase2.py — Phase 2 multi-tenant isolation tests.

Regulatory scope: HIPAA · 42 CFR Part 2
"""
import uuid

from helpers import (
    TENANT_A, TENANT_B, ADMIN_ID, COORDINATOR_ID,
    make_headers, make_participant, make_care_plan,
)

_ADMIN_A = make_headers("program_administrator", user_id=ADMIN_ID)
_COORD_A = make_headers("care_coordinator", user_id=COORDINATOR_ID)
_COORD_B = make_headers("care_coordinator", tenant_id=TENANT_B,
                         user_id="user-coord-tenant-b-001")


def _unique_medicaid():
    return f"TI-{uuid.uuid4().hex[:8].upper()}"


# ─── TI-P2-1 ─────────────────────────────────────────────────────────────────


def test_tenant_isolation_care_plan_not_accessible_from_other_tenant(
    client, coordinator_headers, participants, users
):
    """TI-P2-1 — GET CarePlan from tenant-B user returns 404 for a tenant-A record."""
    p = make_participant(client, _ADMIN_A, medicaid_id=_unique_medicaid())
    cp = make_care_plan(client, _COORD_A, p["participant_id"])

    r = client.get(f"/care-plans/{cp['care_plan_id']}", headers=_COORD_B)
    assert r.status_code == 404
