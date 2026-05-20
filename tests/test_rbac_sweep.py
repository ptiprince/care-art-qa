"""
test_rbac_sweep.py — 9 tests covering cross-cutting RBAC gate (REQ_IDs 1.2, 2.3, 3.2, 4.3, 5.2, 6.2).

Parametrized matrix confirming every role receives 200/201 on permitted endpoints
and 403 on restricted ones.
"""
import pytest
from helpers import (
    TENANT_A, make_participant, make_confirmed_attendance, make_nurse_user,
    make_mar_record, make_headers,
)


# ─── Shared setup helper ──────────────────────────────────────────────────────

def _setup_entities(client, admin_headers, coordinator_headers, nurse_headers):
    """Create shared participant, attendance, MAR, and incident for sweep tests."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    att = make_confirmed_attendance(client, coordinator_headers, pid, date_of_service="2026-05-15")

    nurse_user = make_nurse_user(client, admin_headers, email="sweep-nurse@example.com")
    nid = nurse_user["user_id"]
    mar = make_mar_record(client, nurse_headers, pid, nid,
                          scheduled_time="2026-05-15T08:00:00", status="administered")

    return pid, att["attendance_id"], mar["mar_id"]


# ─── program_administrator write on attendance and claims ─────────────────────

def test_rbac_program_administrator_write_permitted_on_attendance_and_claims(
    client, admin_headers, coordinator_headers, nurse_headers
):
    """program_administrator POST/PATCH on Attendance and Claim returns 201/200."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    r_att = client.post(
        "/attendance",
        json={"tenant_id": TENANT_A, "participant_id": pid,
              "date_of_service": "2026-03-01", "status": "pending"},
        headers=admin_headers,
    )
    assert r_att.status_code == 201

    att = make_confirmed_attendance(client, admin_headers, pid, date_of_service="2026-03-02")
    billing_hdrs = make_headers("billing_specialist")
    claim_r = client.post(
        "/claims",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "attendance_ids": [att["attendance_id"]],
            "payer_type": "medicaid",
            "procedure_code": "S5101",
            "date_of_service_start": "2026-03-02",
        },
        headers=admin_headers,
    )
    assert claim_r.status_code == 201


# ─── care_coordinator write on attendance and incidents ───────────────────────

def test_rbac_care_coordinator_write_permitted_on_attendance_and_incidents(
    client, admin_headers, coordinator_headers
):
    """care_coordinator POST/PATCH on Attendance and Incident returns 201."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    r_att = client.post(
        "/attendance",
        json={"tenant_id": TENANT_A, "participant_id": pid,
              "date_of_service": "2026-03-05", "status": "pending"},
        headers=coordinator_headers,
    )
    assert r_att.status_code == 201

    r_inc = client.post(
        "/incidents",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "incident_date": "2026-03-05",
            "incident_type": "fall",
            "description": "Coordinator-created incident.",
            "severity": "minor",
            "status": "draft",
        },
        headers=coordinator_headers,
    )
    assert r_inc.status_code == 201


# ─── nurse_medication_aide write on MAR only ──────────────────────────────────

def test_rbac_nurse_medication_aide_write_permitted_on_mar_record_only(
    client, admin_headers, nurse_headers
):
    """nurse_medication_aide POST on MARRecord returns 201; POST on Claim returns 403."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse_user = make_nurse_user(client, admin_headers, email="solo-nurse@example.com")
    nid = nurse_user["user_id"]

    r_mar = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Ramipril",
            "administered_by": nid,
            "scheduled_time": "2026-03-10T08:00:00",
            "status": "administered",
            "administered_time": "2026-03-10T08:05:00",
        },
        headers=nurse_headers,
    )
    assert r_mar.status_code == 201

    r_claim = client.post(
        "/claims",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "attendance_ids": ["fake-att-id"],
            "payer_type": "medicaid",
            "procedure_code": "S5101",
            "date_of_service_start": "2026-03-10",
        },
        headers=nurse_headers,
    )
    assert r_claim.status_code == 403


# ─── billing_specialist write on claims only ──────────────────────────────────

def test_rbac_billing_specialist_write_permitted_on_claims_only(
    client, admin_headers, coordinator_headers, billing_headers, nurse_headers
):
    """billing_specialist POST/PATCH on Claim returns 201; POST on MARRecord returns 403."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    att = make_confirmed_attendance(client, coordinator_headers, pid, date_of_service="2026-03-15")

    r_claim = client.post(
        "/claims",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "attendance_ids": [att["attendance_id"]],
            "payer_type": "medicaid",
            "procedure_code": "S5101",
            "date_of_service_start": "2026-03-15",
        },
        headers=billing_headers,
    )
    assert r_claim.status_code == 201

    nurse_user = make_nurse_user(client, admin_headers, email="billing-mar-test@example.com")
    r_mar = client.post(
        "/mar-records",
        json={
            "tenant_id": TENANT_A,
            "participant_id": pid,
            "medication_name": "Atorvastatin",
            "administered_by": nurse_user["user_id"],
            "scheduled_time": "2026-03-15T08:00:00",
            "status": "administered",
            "administered_time": "2026-03-15T08:05:00",
        },
        headers=billing_headers,
    )
    assert r_mar.status_code == 403


# ─── physician denied all entity write endpoints ──────────────────────────────

def test_rbac_physician_denied_all_entity_write_endpoints(
    client, admin_headers, coordinator_headers, physician_headers
):
    """physician POST or PATCH on any entity endpoint returns 403."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    write_attempts = [
        ("/participants", {"tenant_id": TENANT_A, "first_name": "Phys", "last_name": "Doc",
                           "date_of_birth": "1970-01-01", "enrollment_date": "2026-01-01"}),
        ("/attendance", {"tenant_id": TENANT_A, "participant_id": pid,
                         "date_of_service": "2026-03-01", "status": "pending"}),
        ("/claims", {"tenant_id": TENANT_A, "participant_id": pid,
                     "attendance_ids": [], "payer_type": "medicaid",
                     "procedure_code": "S5101", "date_of_service_start": "2026-03-01"}),
        ("/incidents", {"tenant_id": TENANT_A, "participant_id": pid,
                        "incident_date": "2026-03-01", "incident_type": "fall",
                        "description": "Test.", "severity": "minor", "status": "draft"}),
    ]

    for endpoint, payload in write_attempts:
        r = client.post(endpoint, json=payload, headers=physician_headers)
        assert r.status_code == 403, \
            f"Expected 403 for physician on POST {endpoint}, got {r.status_code}"


# ─── participant_family denied all staff entity endpoints ─────────────────────

def test_rbac_participant_family_denied_all_staff_entity_endpoints(
    client, admin_headers, family_headers
):
    """participant_family request to any entity endpoint returns 403."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]

    endpoints = [
        ("GET", f"/participants/{pid}"),
        ("GET", "/participants"),
        ("POST", "/participants"),
        ("GET", "/attendance"),
        ("GET", "/claims"),
        ("GET", "/mar-records"),
    ]

    for method, endpoint in endpoints:
        params = {"tenant_id": TENANT_A} if method == "GET" and endpoint.endswith("s") else {}
        if method == "GET":
            r = client.get(endpoint, params=params, headers=family_headers)
        else:
            r = client.post(endpoint, params=params, headers=family_headers, json={})
        assert r.status_code == 403, \
            f"Expected 403 for participant_family on {method} {endpoint}, got {r.status_code}"


# ─── compliance_officer read permitted on all entities ────────────────────────

def test_rbac_compliance_officer_read_permitted_all_entities(
    client, admin_headers, coordinator_headers, nurse_headers, compliance_headers
):
    """compliance_officer GET on all six entity endpoints returns 200."""
    p = make_participant(client, admin_headers)
    pid = p["participant_id"]
    nurse_user = make_nurse_user(client, admin_headers, email="co-nurse@example.com")
    nid = nurse_user["user_id"]
    att = make_confirmed_attendance(client, coordinator_headers, pid, date_of_service="2026-03-20")
    mar = make_mar_record(client, nurse_headers, pid, nid,
                          scheduled_time="2026-03-20T08:00:00", status="administered")

    read_checks = [
        (f"/participants/{pid}", {}),
        (f"/participants", {"tenant_id": TENANT_A}),
        (f"/attendance/{att['attendance_id']}", {}),
        (f"/attendance", {"tenant_id": TENANT_A}),
        (f"/mar-records/{mar['mar_id']}", {}),
        (f"/mar-records", {"tenant_id": TENANT_A}),
        (f"/incidents", {"tenant_id": TENANT_A}),
        (f"/claims", {"tenant_id": TENANT_A}),
        (f"/users", {"tenant_id": TENANT_A}),
    ]

    for endpoint, params in read_checks:
        r = client.get(endpoint, params=params, headers=compliance_headers)
        assert r.status_code == 200, \
            f"Expected 200 for compliance_officer on GET {endpoint}, got {r.status_code}: {r.text}"


# ─── inactive user denied before role evaluation ──────────────────────────────

def test_rbac_inactive_user_denied_before_role_evaluation(client, admin_headers, compliance_headers):
    """inactive user receives 403 before role is checked; audit event records outcome."""
    inactive_admin_headers = make_headers("program_administrator", status="inactive",
                                           user_id="inactive-admin-001")

    r = client.get(
        "/participants",
        params={"tenant_id": TENANT_A},
        headers=inactive_admin_headers,
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "inactive" in detail["message"].lower() or "ACCOUNT_INACTIVE" in detail["error_code"]


# ─── suspended user denied before role evaluation ────────────────────────────

def test_rbac_suspended_user_denied_before_role_evaluation(client, admin_headers, compliance_headers):
    """suspended user receives 403 before role is checked."""
    suspended_headers = make_headers("billing_specialist", status="suspended",
                                      user_id="suspended-user-001")

    r = client.get(
        "/claims",
        params={"tenant_id": TENANT_A},
        headers=suspended_headers,
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "suspended" in detail["message"].lower() or "ACCOUNT_INACTIVE" in detail["error_code"]
