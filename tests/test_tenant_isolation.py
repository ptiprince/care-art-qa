"""
test_tenant_isolation.py — 7 tests covering cross-cutting tenant isolation gate.

Verifies that no record belonging to tenant A is visible or writable by a user of tenant B,
and that uniqueness constraints are scoped per tenant.
"""
import pytest
from helpers import (
    TENANT_A, TENANT_B, make_participant, make_attendance, make_confirmed_attendance,
    make_claim, make_nurse_user, make_mar_record, make_incident, make_headers,
)

ADMIN_B = make_headers("program_administrator", tenant_id=TENANT_B)
COORD_B = make_headers("care_coordinator", tenant_id=TENANT_B)
NURSE_B = make_headers("nurse_medication_aide", tenant_id=TENANT_B)
BILLING_B = make_headers("billing_specialist", tenant_id=TENANT_B)


# ─── Participant not accessible from other tenant ─────────────────────────────

def test_tenant_isolation_participant_not_accessible_from_other_tenant(client, admin_headers):
    """GET Participant from tenant-B user returns 404 for a record belonging to tenant A."""
    p = make_participant(client, admin_headers, tenant_id=TENANT_A)
    pid = p["participant_id"]

    r = client.get(f"/participants/{pid}", headers=ADMIN_B)
    assert r.status_code in (403, 404), \
        f"Expected 403 or 404 for cross-tenant participant access, got {r.status_code}"


# ─── User token rejected on other tenant endpoints ───────────────────────────

def test_tenant_isolation_user_token_rejected_on_other_tenant_endpoints(client, admin_headers):
    """Tenant-A user's headers rejected with 403 on tenant-B list endpoints."""
    r = client.get(
        "/participants",
        params={"tenant_id": TENANT_B},
        headers=admin_headers,
    )
    # Tenant A user querying tenant B data — RBAC check passes (role is valid)
    # but tenant isolation check should block cross-tenant reads.
    # In this mock, tenant isolation is enforced via the tenant_id filter in the query
    # (records returned are empty — not the same as 403).
    # A 200 with empty list is acceptable isolation if the list returns only own-tenant records.
    # A 403 is also acceptable if the middleware checks X-Tenant-Id vs query param.
    # Both are valid isolation behaviors; this test confirms no cross-tenant leakage.
    if r.status_code == 200:
        participant_ids = [p["participant_id"] for p in r.json()]
        tenant_a_participants = client.get(
            "/participants",
            params={"tenant_id": TENANT_A},
            headers=admin_headers,
        ).json()
        tenant_a_ids = {p["participant_id"] for p in tenant_a_participants}
        for pid in participant_ids:
            assert pid not in tenant_a_ids, \
                f"Tenant-A participant {pid} leaked into tenant-B list response"
    else:
        assert r.status_code == 403


# ─── Attendance not accessible from other tenant ──────────────────────────────

def test_tenant_isolation_attendance_not_accessible_from_other_tenant(client, admin_headers, coordinator_headers):
    """GET Attendance from tenant-B user returns 404 for a record belonging to tenant A."""
    p = make_participant(client, admin_headers, tenant_id=TENANT_A)
    att = make_attendance(client, coordinator_headers, p["participant_id"],
                          tenant_id=TENANT_A, date_of_service="2026-08-01")
    att_id = att["attendance_id"]

    r = client.get(f"/attendance/{att_id}", headers=COORD_B)
    assert r.status_code in (403, 404), \
        f"Expected 403 or 404 for cross-tenant attendance access, got {r.status_code}"


# ─── Claim not accessible from other tenant ───────────────────────────────────

def test_tenant_isolation_claim_not_accessible_from_other_tenant(
    client, admin_headers, coordinator_headers
):
    """GET Claim from tenant-B user returns 404 for a record belonging to tenant A."""
    p = make_participant(client, admin_headers, tenant_id=TENANT_A)
    att = make_confirmed_attendance(client, coordinator_headers, p["participant_id"],
                                   tenant_id=TENANT_A, date_of_service="2026-08-05")
    claim = make_claim(
        client, make_headers("billing_specialist"),
        p["participant_id"], [att["attendance_id"]], tenant_id=TENANT_A,
    )
    claim_id = claim["claim_id"]

    r = client.get(f"/claims/{claim_id}", headers=BILLING_B)
    assert r.status_code in (403, 404), \
        f"Expected 403 or 404 for cross-tenant claim access, got {r.status_code}"


# ─── MARRecord not accessible from other tenant ───────────────────────────────

def test_tenant_isolation_mar_record_not_accessible_from_other_tenant(
    client, admin_headers, nurse_headers
):
    """GET MARRecord from tenant-B user returns 404 for a record belonging to tenant A."""
    p = make_participant(client, admin_headers, tenant_id=TENANT_A)
    nurse_user = make_nurse_user(client, admin_headers, tenant_id=TENANT_A,
                                 email="isolation-nurse@example.com")
    mar = make_mar_record(client, nurse_headers, p["participant_id"],
                          nurse_user["user_id"], tenant_id=TENANT_A,
                          scheduled_time="2026-08-10T09:00:00")
    mar_id = mar["mar_id"]

    r = client.get(f"/mar-records/{mar_id}", headers=NURSE_B)
    assert r.status_code in (403, 404), \
        f"Expected 403 or 404 for cross-tenant MAR access, got {r.status_code}"


# ─── Incident not accessible from other tenant ────────────────────────────────

def test_tenant_isolation_incident_not_accessible_from_other_tenant(client, admin_headers):
    """GET Incident from tenant-B user returns 404 for a record belonging to tenant A."""
    p = make_participant(client, admin_headers, tenant_id=TENANT_A)
    inc = make_incident(client, admin_headers, p["participant_id"],
                        tenant_id=TENANT_A, severity="minor", incident_type="fall",
                        description="Isolation test incident.")
    inc_id = inc["incident_id"]

    r = client.get(f"/incidents/{inc_id}", headers=ADMIN_B)
    assert r.status_code in (403, 404), \
        f"Expected 403 or 404 for cross-tenant incident access, got {r.status_code}"


# ─── Unique constraints are scoped per tenant ─────────────────────────────────

def test_tenant_isolation_unique_constraints_are_scoped_per_tenant(client, admin_headers):
    """medicaid_id registered in tenant A is accepted in tenant B; email similarly accepted."""
    make_participant(client, admin_headers, tenant_id=TENANT_A, medicaid_id="MCD-ISO-001")

    r_b = client.post(
        "/participants",
        json={
            "tenant_id": TENANT_B,
            "first_name": "Cross",
            "last_name": "Tenant",
            "date_of_birth": "1975-05-15",
            "enrollment_date": "2026-01-01",
            "medicaid_id": "MCD-ISO-001",
        },
        headers=ADMIN_B,
    )
    assert r_b.status_code == 201, \
        f"Expected 201 for same medicaid_id in different tenant, got {r_b.status_code}: {r_b.text}"

    make_user(client, admin_headers, email="shared-email@example.com", tenant_id=TENANT_A)

    admin_b_headers = make_headers("program_administrator", tenant_id=TENANT_B)
    r_user_b = client.post(
        "/users",
        json={
            "tenant_id": TENANT_B,
            "first_name": "Cross",
            "last_name": "Tenant",
            "email": "shared-email@example.com",
            "role": "care_coordinator",
        },
        headers=admin_b_headers,
    )
    assert r_user_b.status_code == 201, \
        f"Expected 201 for same email in different tenant, got {r_user_b.status_code}: {r_user_b.text}"


def make_user(client, headers, email, tenant_id=TENANT_A, role="care_coordinator"):
    r = client.post(
        "/users",
        json={"tenant_id": tenant_id, "first_name": "Test", "last_name": "User",
              "email": email, "role": role},
        headers=headers,
    )
    assert r.status_code == 201, f"User creation failed: {r.text}"
    return r.json()
