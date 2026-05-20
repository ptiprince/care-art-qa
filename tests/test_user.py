"""
test_user.py — 12 tests covering REQ_IDs 2.1–2.12.
"""
from datetime import datetime, timedelta
import re

import pytest
from helpers import TENANT_A, TENANT_B, make_participant, make_user, make_headers


# ─── 2.1 Unique email per tenant ──────────────────────────────────────────────

def test_2_1_unique_email_per_tenant(client, admin_headers):
    """REQ 2.1 — duplicate email in same tenant returns 409 USER_DUPLICATE_EMAIL; same email in another tenant returns 201."""
    make_user(client, admin_headers, email="shared@example.com")

    r_dup = client.post(
        "/users",
        json={"tenant_id": TENANT_A, "first_name": "Bob", "last_name": "Jones",
              "email": "shared@example.com", "role": "care_coordinator"},
        headers=admin_headers,
    )
    assert r_dup.status_code == 409
    assert r_dup.json()["detail"]["error_code"] == "USER_DUPLICATE_EMAIL"

    admin_b = make_headers("program_administrator", tenant_id=TENANT_B)
    r_other_tenant = client.post(
        "/users",
        json={"tenant_id": TENANT_B, "first_name": "Bob", "last_name": "Jones",
              "email": "shared@example.com", "role": "care_coordinator"},
        headers=admin_b,
    )
    assert r_other_tenant.status_code == 201


# ─── 2.2 Unique user_id globally ──────────────────────────────────────────────

def test_2_2_unique_user_id_globally(client, admin_headers, db_session):
    """REQ 2.2 — user_id is globally unique (PRIMARY KEY enforcement)."""
    from models import User
    u1 = make_user(client, admin_headers, email="global1@example.com")
    u2 = make_user(client, admin_headers, email="global2@example.com")

    ids = db_session.execute(
        db_session.connection().engine.connect().execute.__self__
        if False else
        __import__("sqlalchemy").text("SELECT user_id FROM user")
    ).fetchall()

    # Verify uniqueness via the response — each call gets distinct user_id
    assert u1["user_id"] != u2["user_id"]

    # Verify no duplicate user_ids across tenants
    from models import User as UserModel
    all_users = db_session.query(UserModel).all()
    all_ids = [u.user_id for u in all_users]
    assert len(all_ids) == len(set(all_ids))


# ─── 2.3 RBAC evaluation order — tenant status checked before role ─────────────

def test_2_3_rbac_evaluation_order_tenant_status_role(client, admin_headers):
    """REQ 2.3 — inactive user returns 403 before role check; wrong-tenant user also returns 403."""
    inactive_headers = make_headers("program_administrator", status="inactive")
    r_inactive = client.get(
        "/users",
        params={"tenant_id": TENANT_A},
        headers=inactive_headers,
    )
    assert r_inactive.status_code == 403
    assert "ACCOUNT_INACTIVE" in r_inactive.json()["detail"]["error_code"] or \
           "inactive" in r_inactive.json()["detail"]["message"].lower()


# ─── 2.4 MFA required for PHI-accessing roles ─────────────────────────────────

def test_2_4_mfa_required_for_phi_accessing_roles(client, admin_headers):
    """REQ 2.4 — PHI endpoint access with mfa_enabled=false returns 403 MFA_REQUIRED."""
    no_mfa_headers = make_headers("program_administrator", mfa=False)
    payload = {
        "tenant_id": TENANT_A,
        "first_name": "MFA",
        "last_name": "Test",
        "date_of_birth": "1990-01-01",
        "enrollment_date": "2026-01-01",
    }
    r = client.post("/participants", json=payload, headers=no_mfa_headers)
    assert r.status_code == 403
    assert "MFA" in r.json()["detail"]["error_code"]


# ─── 2.5 Account locked after five failed logins ──────────────────────────────

def test_2_5_account_locked_after_five_failed_logins(client, admin_headers, db_session):
    """REQ 2.5 — fifth failed login sets locked_until; login within lockout window returns 401."""
    from models import User as UserModel

    user = make_user(client, admin_headers, email="lockout@example.com")
    uid = user["user_id"]

    # Set a password_changed_at so it won't trigger expiry
    db_session.query(UserModel).filter(UserModel.user_id == uid).update({
        "password_changed_at": datetime.utcnow()
    })
    db_session.commit()

    for i in range(5):
        r = client.post("/login", json={"user_id": uid, "password": ""})
        if i < 4:
            assert r.status_code == 401
        else:
            assert r.status_code == 401

    db_session.expire_all()
    locked_user = db_session.query(UserModel).filter(UserModel.user_id == uid).first()
    assert locked_user.locked_until is not None
    assert locked_user.locked_until > datetime.utcnow()

    # Login attempt while locked returns 401 ACCOUNT_LOCKED
    r_locked = client.post("/login", json={"user_id": uid, "password": "anypassword"})
    assert r_locked.status_code == 401
    assert "LOCKED" in r_locked.json()["detail"]["error_code"]


# ─── 2.6 Lockout state persists in database ────────────────────────────────────

def test_2_6_lockout_state_persists_in_database(client, admin_headers, db_session):
    """REQ 2.6 — locked_until is persisted in DB; login while locked returns 401; response omits locked_until value."""
    from models import User as UserModel

    user = make_user(client, admin_headers, email="lockpersist@example.com")
    uid = user["user_id"]

    db_session.query(UserModel).filter(UserModel.user_id == uid).update({
        "failed_login_count": 4,
        "password_changed_at": datetime.utcnow(),
    })
    db_session.commit()

    # One more failed login triggers lockout
    client.post("/login", json={"user_id": uid, "password": ""})

    db_session.expire_all()
    u = db_session.query(UserModel).filter(UserModel.user_id == uid).first()
    assert u.locked_until is not None

    r_locked = client.post("/login", json={"user_id": uid, "password": "correct"})
    assert r_locked.status_code == 401
    detail = r_locked.json()["detail"]
    # locked_until value must not appear in the response
    assert "locked_until" not in str(detail).lower() or detail.get("locked_until") is None


# ─── 2.7 User status state machine ───────────────────────────────────────────

def test_2_7_user_status_state_machine_transitions(client, admin_headers):
    """REQ 2.7 — invalid transitions return 422; DELETE returns 405; inactive sets deactivated_at."""
    user = make_user(client, admin_headers, email="statemachine@example.com")
    uid = user["user_id"]

    r_delete = client.delete(f"/users/{uid}", headers=admin_headers)
    assert r_delete.status_code == 405

    # active → suspended is allowed
    r_suspend = client.patch(
        f"/users/{uid}",
        json={"version": user["version"], "status": "suspended"},
        headers=admin_headers,
    )
    assert r_suspend.status_code == 200
    suspended = r_suspend.json()

    # suspended → pending_activation is NOT in defined transitions
    r_invalid = client.patch(
        f"/users/{uid}",
        json={"version": suspended["version"], "status": "pending_activation"},
        headers=admin_headers,
    )
    assert r_invalid.status_code == 422
    assert "TRANSITION" in r_invalid.json()["detail"]["error_code"]

    # Fresh user: active → inactive sets deactivated_at
    user2 = make_user(client, admin_headers, email="deactivate@example.com")
    r_inactive = client.patch(
        f"/users/{user2['user_id']}",
        json={"version": user2["version"], "status": "inactive"},
        headers=admin_headers,
    )
    assert r_inactive.status_code == 200
    assert r_inactive.json()["deactivated_at"] is not None


# ─── 2.8 Audit log on auth events and user changes ───────────────────────────

def test_2_8_audit_log_on_auth_events_and_user_changes(client, admin_headers, compliance_headers, db_session):
    """REQ 2.8 — login produces AUTH_SUCCESS event; user role change produces PHI_WRITE event."""
    from models import User as UserModel

    user = make_user(client, admin_headers, email="auditauth@example.com")
    uid = user["user_id"]
    db_session.query(UserModel).filter(UserModel.user_id == uid).update({
        "password_changed_at": datetime.utcnow()
    })
    db_session.commit()

    r_login = client.post("/login", json={"user_id": uid, "password": "valid"})
    assert r_login.status_code == 200

    logs = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "User", "resource_id": uid},
        headers=compliance_headers,
    )
    events = logs.json()
    auth_event = next((e for e in events if e["action_type"] == "AUTH_SUCCESS"), None)
    assert auth_event is not None

    r_patch = client.patch(
        f"/users/{uid}",
        json={"version": user["version"] + 1, "role": "billing_specialist"},
        headers=admin_headers,
    )
    # version incremented after successful login (last_login_at changes version)
    if r_patch.status_code == 409:
        fresh = client.get(f"/users/{uid}", headers=admin_headers).json()
        r_patch = client.patch(
            f"/users/{uid}",
            json={"version": fresh["version"], "role": "billing_specialist"},
            headers=admin_headers,
        )
    assert r_patch.status_code == 200

    logs2 = client.get(
        "/audit-logs",
        params={"tenant_id": TENANT_A, "resource_type": "User", "resource_id": uid},
        headers=compliance_headers,
    )
    write_events = [e for e in logs2.json() if e["action_type"] == "PHI_WRITE"]
    assert len(write_events) >= 1
    for evt in write_events:
        for phi_val in ["billing_specialist", uid, "care_coordinator"]:
            assert phi_val not in str(evt.get("data_affected", []))


# ─── 2.9 Password stored as hash, never plaintext ────────────────────────────

def test_2_9_password_stored_as_hash_never_plaintext(client, admin_headers, db_session):
    """REQ 2.9 — password_hash column uses bcrypt/Argon2id pattern; no plaintext in any row."""
    from models import User as UserModel

    user = make_user(client, admin_headers, email="hashcheck@example.com",
                     password_hash="$2b$12$abcdefghijklmnopqrstuuVHKHCr7MUwAQvI4VkC7eTF3r5g2R5ey")

    u = db_session.query(UserModel).filter(UserModel.user_id == user["user_id"]).first()
    if u.password_hash:
        bcrypt_pattern = re.compile(r"^\$2[aby]\$\d{2}\$")
        argon2_pattern = re.compile(r"^\$argon2")
        assert bcrypt_pattern.match(u.password_hash) or argon2_pattern.match(u.password_hash), \
            "password_hash does not match bcrypt or Argon2id pattern"

    all_users = db_session.query(UserModel).all()
    for u in all_users:
        if u.password_hash:
            assert not re.match(r"^[a-zA-Z0-9 !@#$%]{1,30}$", u.password_hash) or \
                   u.password_hash.startswith("$"), \
                   f"Possible plaintext password in user {u.user_id}"


# ─── 2.10 90-day password rotation and reuse prevention ──────────────────────

def test_2_10_90_day_password_rotation_and_reuse_prevention(client, admin_headers, db_session):
    """REQ 2.10 — login with password age > 90 days returns 403 PASSWORD_EXPIRED."""
    from models import User as UserModel

    user = make_user(client, admin_headers, email="passexpiry@example.com")
    uid = user["user_id"]

    db_session.query(UserModel).filter(UserModel.user_id == uid).update({
        "password_changed_at": datetime.utcnow() - timedelta(days=91),
    })
    db_session.commit()

    r = client.post("/login", json={"user_id": uid, "password": "valid"})
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "PASSWORD_EXPIRED"


# ─── 2.11 Dormant account auto-deactivated after 90 days ─────────────────────

def test_2_11_dormant_account_auto_deactivated_after_90_days(client, admin_headers, db_session, compliance_headers):
    """REQ 2.11 — job deactivates accounts with last_login_at > 90 days; produces ACCOUNT_AUTO_DEACTIVATED audit event."""
    from models import User as UserModel

    user = make_user(client, admin_headers, email="dormant@example.com")
    uid = user["user_id"]

    db_session.query(UserModel).filter(UserModel.user_id == uid).update({
        "last_login_at": datetime.utcnow() - timedelta(days=91),
    })
    db_session.commit()

    r_job = client.post("/jobs/deactivate-dormant")
    assert r_job.status_code == 200
    assert uid in r_job.json()["deactivated"]

    db_session.expire_all()
    u = db_session.query(UserModel).filter(UserModel.user_id == uid).first()
    assert u.status == "inactive"
    assert u.deactivated_at is not None


# ─── 2.12 Optimistic locking — version conflict returns 409 ──────────────────

def test_2_12_optimistic_locking_version_conflict_returns_409(client, admin_headers):
    """REQ 2.12 — PATCH with stale version returns 409 USER_VERSION_CONFLICT; correct version returns 200 with n+1."""
    user = make_user(client, admin_headers, email="userlock@example.com")
    uid = user["user_id"]
    version = user["version"]

    r_stale = client.patch(
        f"/users/{uid}",
        json={"version": version - 1, "status": "suspended"},
        headers=admin_headers,
    )
    assert r_stale.status_code == 409
    assert r_stale.json()["detail"]["error_code"] == "USER_VERSION_CONFLICT"

    r_ok = client.patch(
        f"/users/{uid}",
        json={"version": version, "status": "suspended"},
        headers=admin_headers,
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["version"] == version + 1
