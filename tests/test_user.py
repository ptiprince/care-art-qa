"""
test_user.py — 13 tests mapped to TC-2.1 through TC-2.13.

Regulatory scope: HIPAA · CMS Medicaid/Medicare · State adult day care licensing
"""
import uuid

import httpx
import pytest
from sqlalchemy import text

from helpers import TENANT_A, TENANT_B, make_headers, make_user


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


# ─── TC-2.1 ──────────────────────────────────────────────────────────────────

def test_tc_2_1_positive_user_creation_by_program_administrator(
    client, admin_headers, db_session
):
    """TC-2.1 — POST /users by program_administrator returns 201 with all required fields and status active."""
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Celeste",
        "last_name": "Fontaine",
        "email": f"celeste-{uuid.uuid4().hex[:8]}@test.care",
        "role": "care_coordinator",
    }
    r = _call(lambda: client.post("/users", json=payload, headers=admin_headers))
    assert r.status_code == 201
    body = r.json()
    assert body["user_id"] is not None
    assert body["first_name"] == "Celeste"
    assert body["last_name"] == "Fontaine"
    assert body["email"] == payload["email"]
    assert body["role"] == "care_coordinator"
    assert body["status"] == "active"
    assert body["version"] is not None

    # DB layer: verify the row was persisted with correct fields
    uid = body["user_id"]
    row = db_session.execute(
        text(
            'SELECT first_name, last_name, email, role, status '
            'FROM "user" WHERE user_id = :uid'
        ),
        {"uid": uid},
    ).fetchone()
    assert row is not None, f"User {uid} not found in DB after creation"
    assert row.first_name == "Celeste"
    assert row.last_name == "Fontaine"
    assert row.role == "care_coordinator"
    assert row.status == "active"


# ─── TC-2.2 ──────────────────────────────────────────────────────────────────

def test_tc_2_2_user_creation_by_unauthorized_role_returns_403(
    client, coordinator_headers, db_session
):
    """TC-2.2 — POST /users by care_coordinator returns 403; no user row is created."""
    email = f"unauthorized-{uuid.uuid4().hex[:8]}@test.care"
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Should",
        "last_name": "NotExist",
        "email": email,
        "role": "care_coordinator",
    }
    r = _call(lambda: client.post("/users", json=payload, headers=coordinator_headers))
    assert r.status_code == 403

    # DB layer: no user must have been created
    count = db_session.execute(
        text('SELECT COUNT(*) FROM "user" WHERE email = :email AND tenant_id = :tid'),
        {"email": email, "tid": TENANT_A},
    ).scalar()
    assert count == 0, "No user should be created after a 403 rejection by care_coordinator"


# ─── TC-2.3 ──────────────────────────────────────────────────────────────────

def test_tc_2_3_positive_login_valid_credentials_returns_200(
    client, users, db_session
):
    """TC-2.3 — POST /login with valid user_id and correct password returns 200 with status ok."""
    uid = users["admins"][0]["user_id"]
    r = _call(lambda: client.post("/login", json={"user_id": uid, "password": "ValidPass1!"}))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body.get("message") is not None

    # DB layer: last_login_at must be updated after a successful login
    row = db_session.execute(
        text('SELECT last_login_at FROM "user" WHERE user_id = :uid'),
        {"uid": uid},
    ).fetchone()
    assert row is not None, f"User {uid} not found in DB"
    assert row.last_login_at is not None, (
        "last_login_at must be populated after a successful login"
    )


# ─── TC-2.4 ──────────────────────────────────────────────────────────────────

def test_tc_2_4_login_wrong_password_returns_401_no_credential_disclosure(
    client, users, db_session
):
    """TC-2.4 — POST /login with wrong non-empty password returns 401; message does not reveal which credential was wrong."""
    uid = users["coordinators"][0]["user_id"]
    r = _call(lambda: client.post("/login", json={"user_id": uid, "password": "WrongPass!!"}))
    assert r.status_code == 401
    msg = r.json().get("detail", {}).get("message", "")
    assert "email" not in msg.lower(), "Error message must not mention 'email'"
    assert "user_id" not in msg.lower(), "Error message must not mention 'user_id'"
    assert "password" not in msg.lower(), "Error message must not mention 'password'"

    # DB layer: failed_login_count must be incremented after a failed login
    row = db_session.execute(
        text('SELECT failed_login_count FROM "user" WHERE user_id = :uid'),
        {"uid": uid},
    ).fetchone()
    assert row is not None, f"User {uid} not found in DB"
    assert row.failed_login_count >= 1, (
        f"Expected failed_login_count >= 1 after a failed login, got {row.failed_login_count}"
    )


# ─── TC-2.5 ──────────────────────────────────────────────────────────────────

def test_tc_2_5_duplicate_email_same_tenant_returns_409(
    client, admin_headers, db_session
):
    """TC-2.5 — POST /users with an email already registered in the same tenant returns 409 USER_DUPLICATE_EMAIL."""
    email = f"dup-{uuid.uuid4().hex[:8]}@test.care"
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "First",
        "last_name": "Entry",
        "email": email,
        "role": "care_coordinator",
    }
    r1 = _call(lambda: client.post("/users", json=payload, headers=admin_headers))
    assert r1.status_code == 201, f"First user creation failed: {r1.text}"

    payload2 = {**payload, "first_name": "Second"}
    r2 = _call(lambda: client.post("/users", json=payload2, headers=admin_headers))
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "USER_DUPLICATE_EMAIL"

    # DB layer: exactly one user with this email must exist in the tenant
    count = db_session.execute(
        text('SELECT COUNT(*) FROM "user" WHERE email = :email AND tenant_id = :tid'),
        {"email": email, "tid": TENANT_A},
    ).scalar()
    assert count == 1, (
        f"Expected exactly 1 user with email {email} in TENANT_A, found {count}"
    )


# ─── TC-2.6 ──────────────────────────────────────────────────────────────────

def test_tc_2_6_same_email_different_tenant_returns_201(
    client, admin_headers, db_session
):
    """TC-2.6 — POST /users with the same email in a different tenant returns 201; both rows coexist in DB."""
    email = f"cross-tenant-{uuid.uuid4().hex[:8]}@test.care"
    tenant_b_admin = make_headers(
        "program_administrator", tenant_id=TENANT_B, user_id="admin-tenantb-001"
    )

    r_a = _call(lambda: client.post("/users", json={
        "tenant_id": TENANT_A,
        "first_name": "Alice",
        "last_name": "Alpha",
        "email": email,
        "role": "care_coordinator",
    }, headers=admin_headers))
    assert r_a.status_code == 201, f"User creation in TENANT_A failed: {r_a.text}"

    r_b = _call(lambda: client.post("/users", json={
        "tenant_id": TENANT_B,
        "first_name": "Bob",
        "last_name": "Beta",
        "email": email,
        "role": "care_coordinator",
    }, headers=tenant_b_admin))
    assert r_b.status_code == 201, f"User creation in TENANT_B failed: {r_b.text}"

    # DB layer: two distinct rows — one per tenant — must share the same email
    count = db_session.execute(
        text('SELECT COUNT(*) FROM "user" WHERE email = :email'),
        {"email": email},
    ).scalar()
    assert count == 2, (
        f"Expected 2 users with email {email} across both tenants, found {count}"
    )


# ─── TC-2.7 ──────────────────────────────────────────────────────────────────

def test_tc_2_7_account_lockout_after_5_failed_logins(
    client, admin_headers, db_session
):
    """TC-2.7 — 5 consecutive wrong-password logins lock the account; the 6th attempt returns 401 ACCOUNT_LOCKED."""
    # Create an isolated user so lockout does not affect any seeded user
    user = make_user(
        client, admin_headers,
        tenant_id=TENANT_A,
        role="care_coordinator",
        password_hash="LockTestPass1!",
    )
    uid = user["user_id"]

    for attempt in range(1, 6):
        r = _call(lambda: client.post("/login", json={"user_id": uid, "password": "WrongPass!!"}))
        assert r.status_code == 401, (
            f"Attempt {attempt}: expected 401 AUTH_FAILURE, got {r.status_code}"
        )

    r_sixth = _call(lambda: client.post("/login", json={"user_id": uid, "password": "WrongPass!!"}))
    assert r_sixth.status_code == 401
    assert r_sixth.json()["detail"]["error_code"] == "ACCOUNT_LOCKED", (
        "6th consecutive failed login must return ACCOUNT_LOCKED"
    )

    # DB layer: locked_until must be set and failed_login_count must reflect the lockout threshold
    row = db_session.execute(
        text('SELECT failed_login_count, locked_until FROM "user" WHERE user_id = :uid'),
        {"uid": uid},
    ).fetchone()
    assert row is not None, f"User {uid} not found in DB"
    assert row.failed_login_count >= 5, (
        f"Expected failed_login_count >= 5 after lockout, got {row.failed_login_count}"
    )
    assert row.locked_until is not None, "locked_until must be set after account lockout"


# ─── TC-2.8 ──────────────────────────────────────────────────────────────────

def test_tc_2_8_locked_user_login_returns_401_account_locked(
    client, admin_headers, db_session
):
    """TC-2.8 — A locked user's login attempt — even with the correct password — returns 401 ACCOUNT_LOCKED."""
    # Create an isolated user and trigger lockout via 5 failed attempts
    user = make_user(
        client, admin_headers,
        tenant_id=TENANT_A,
        role="care_coordinator",
        password_hash="LockedUserPass1!",
    )
    uid = user["user_id"]

    for _ in range(5):
        _call(lambda: client.post("/login", json={"user_id": uid, "password": "WrongPass!!"}))

    # Correct password must still be rejected while the account is locked
    r = _call(lambda: client.post("/login", json={"user_id": uid, "password": "LockedUserPass1!"}))
    assert r.status_code == 401
    assert r.json()["detail"]["error_code"] == "ACCOUNT_LOCKED", (
        "Locked account must reject even a valid password with ACCOUNT_LOCKED"
    )

    # DB layer: locked_until must remain set
    row = db_session.execute(
        text('SELECT locked_until FROM "user" WHERE user_id = :uid'),
        {"uid": uid},
    ).fetchone()
    assert row is not None, f"User {uid} not found in DB"
    assert row.locked_until is not None, (
        "locked_until must remain populated for a locked user"
    )


# ─── TC-2.9 ──────────────────────────────────────────────────────────────────

def test_tc_2_9_soft_delete_user_returns_200_status_inactive(
    client, admin_headers, db_session
):
    """TC-2.9 — PATCH /users/{id} with status=inactive returns 200; DB row shows status=inactive and deactivated_at set."""
    user = make_user(client, admin_headers, tenant_id=TENANT_A, role="care_coordinator")
    uid = user["user_id"]
    version = user["version"]

    r_patch = _call(lambda: client.patch(
        f"/users/{uid}",
        json={"version": version, "status": "inactive"},
        headers=admin_headers,
    ))
    assert r_patch.status_code == 200
    assert r_patch.json()["status"] == "inactive"

    # Subsequent GET must still return the row with status=inactive (soft delete, not physical removal)
    r_get = _call(lambda: client.get(f"/users/{uid}", headers=admin_headers))
    assert r_get.status_code == 200
    assert r_get.json()["status"] == "inactive"

    # DB layer: status and deactivated_at must reflect the deactivation
    row = db_session.execute(
        text('SELECT status, deactivated_at FROM "user" WHERE user_id = :uid'),
        {"uid": uid},
    ).fetchone()
    assert row is not None, f"User {uid} must still exist in DB after deactivation (soft delete, not physical removal)"
    assert row.status == "inactive", (
        f"Expected status='inactive' in DB after soft delete, got '{row.status}'"
    )
    assert row.deactivated_at is not None, (
        "deactivated_at must be set when a user is deactivated"
    )


# ─── TC-2.10 ─────────────────────────────────────────────────────────────────

def test_tc_2_10_audit_log_on_user_creation_has_mandatory_fields_no_pii(
    client, admin_headers, compliance_headers, db_session
):
    """TC-2.10 — PHI_WRITE audit event after POST /users has all 11 mandatory fields and no PII values in data_affected."""
    email = f"audit-{uuid.uuid4().hex[:8]}@test.care"
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Margot",
        "last_name": "Bellamy",
        "email": email,
        "role": "care_coordinator",
    }
    r = _call(lambda: client.post("/users", json=payload, headers=admin_headers))
    assert r.status_code == 201
    uid = r.json()["user_id"]

    logs_r = _call(lambda: client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "User", "resource_id": uid},
        headers=compliance_headers,
    ))
    if logs_r.status_code == 404:
        pytest.fail(
            "GET /audit-logs returned 404 — the audit-log endpoint is not implemented "
            "in the mock backend. Add it before running this test."
        )
    assert logs_r.status_code == 200
    events = logs_r.json()

    write_event = next(
        (e for e in events if e["action_type"] == "PHI_WRITE"), None
    )
    assert write_event is not None, "PHI_WRITE audit event not found for user creation"

    mandatory_fields = [
        "timestamp", "user_id", "tenant_id", "session_id",
        "action_type", "resource_type", "resource_id",
        "data_affected", "source_ip", "outcome", "layer",
    ]
    for field in mandatory_fields:
        assert write_event[field] is not None, (
            f"Mandatory audit field '{field}' is null"
        )

    assert write_event["outcome"] == "SUCCESS"
    assert write_event["resource_type"] == "User"

    # data_affected must contain field names only — no PII values
    data_str = str(write_event["data_affected"])
    for pii_value in ("Margot", "Bellamy", email):
        assert pii_value not in data_str, (
            f"PII value '{pii_value}' found in data_affected — audit log must not expose PII"
        )

    # DB layer: verify the user was persisted correctly
    row = db_session.execute(
        text('SELECT first_name, last_name, email FROM "user" WHERE user_id = :uid'),
        {"uid": uid},
    ).fetchone()
    assert row is not None, f"User {uid} not found in DB after creation"
    assert row.first_name == "Margot"
    assert row.last_name == "Bellamy"
    assert row.email == email


# ─── TC-2.11 ─────────────────────────────────────────────────────────────────

def test_tc_2_11_missing_email_returns_400_or_422_with_field_name(
    client, admin_headers, db_session
):
    """TC-2.11 — POST /users without email returns 400 or 422 and identifies 'email' in the error body."""
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Missing",
        "last_name": "EmailField",
        "role": "care_coordinator",
    }
    r = _call(lambda: client.post("/users", json=payload, headers=admin_headers))
    assert r.status_code in (400, 422)
    assert "email" in r.text, "Error response must identify 'email' as the missing field"

    # DB layer: no user with this last_name must have been created
    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM \"user\" "
            "WHERE last_name = 'EmailField' AND tenant_id = :tid"
        ),
        {"tid": TENANT_A},
    ).scalar()
    assert count == 0, (
        "No user should exist with last_name='EmailField' after a failed creation (missing email)"
    )


# ─── TC-2.12 ─────────────────────────────────────────────────────────────────

def test_tc_2_12_billing_specialist_create_participant_returns_403(
    client, billing_headers, db_session
):
    """TC-2.12 — POST /participants by billing_specialist returns 403; no participant row is created."""
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "Billing",
        "last_name": "Blocked",
        "date_of_birth": "1960-01-01",
        "enrollment_date": "2026-01-01",
    }
    r = _call(lambda: client.post("/participants", json=payload, headers=billing_headers))
    assert r.status_code == 403

    # DB layer: no participant with this last_name must have been created
    count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM participant "
            "WHERE last_name = 'Blocked' AND tenant_id = :tid"
        ),
        {"tid": TENANT_A},
    ).scalar()
    assert count == 0, (
        "No participant with last_name='Blocked' should exist after a 403 rejection by billing_specialist"
    )


# ─── TC-2.13 ─────────────────────────────────────────────────────────────────

def test_tc_2_13_nurse_create_claim_returns_403(
    client, nurse_headers, participants, db_session
):
    """TC-2.13 — POST /claims by nurse_medication_aide returns 403; no claim row is created."""
    pid = participants["active"][0]["participant_id"]

    count_before = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE participant_id = :pid"),
        {"pid": pid},
    ).scalar()

    r = _call(lambda: client.post("/claims", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "attendance_ids": [str(uuid.uuid4())],
        "payer_type": "medicaid",
        "procedure_code": "S5101",
        "date_of_service_start": "2026-03-01",
    }, headers=nurse_headers))
    assert r.status_code == 403

    # DB layer: claim count for this participant must be unchanged
    count_after = db_session.execute(
        text("SELECT COUNT(*) FROM claim WHERE participant_id = :pid"),
        {"pid": pid},
    ).scalar()
    assert count_after == count_before, (
        f"No claim should be created after a 403 rejection by nurse_medication_aide "
        f"(before={count_before}, after={count_after})"
    )
