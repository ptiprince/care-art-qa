"""
conftest.py — Care Art Phase 1 test suite fixture layer.

Scope layout
------------
session : session_engine, session_client, tenant, users, participants
function: db_session, client (alias), all header fixtures, all fresh_* fixtures

All session-scoped data fixtures create records exclusively through API endpoints.
No direct SQL inserts.  Function-scoped fresh_* fixtures isolate per-test state
and clean up after themselves via API calls.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Import paths ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mock_backend"))
sys.path.insert(0, os.path.dirname(__file__))

from database import Base, get_db
from main import app
from helpers import (
    TENANT_A, TENANT_B,
    ADMIN_ID, COORDINATOR_ID, NURSE_ID, BILLING_ID,
    PHYSICIAN_ID, FAMILY_ID, COMPLIANCE_ID,
    make_headers,
    make_participant, make_attendance, make_confirmed_attendance,
    make_claim, make_mar_record, make_incident, make_nurse_user,
)

# ── Bootstrap headers used only inside this module for fixture setup ──────────
_ADMIN   = make_headers("program_administrator", user_id="bootstrap-admin-001")
_COORD   = make_headers("care_coordinator",       user_id="bootstrap-coord-001")
_NURSE   = make_headers("nurse_medication_aide",  user_id="bootstrap-nurse-001")
_BILLING = make_headers("billing_specialist",     user_id="bootstrap-billing-001")


# ════════════════════════════════════════════════════════════════════════════
# SESSION-SCOPED INFRASTRUCTURE
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def session_engine():
    """Single in-memory SQLite engine shared for the entire test session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="session")
def session_client(session_engine):
    """Single TestClient bound to the session engine, shared across all tests."""
    TestSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=session_engine
    )

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        c.timeout = 5.0  # 5-second timeout; triggers httpx.TimeoutException if backend hangs
        yield c
    app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════════════
# SESSION-SCOPED DATA FIXTURES  (API-only, no direct SQL)
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def tenant():
    """Primary test tenant ID."""
    return TENANT_A


@pytest.fixture(scope="session")
def users(session_client, tenant):
    """
    Create 21 users via POST /users.

    Role breakdown
    --------------
    program_administrator  × 2   (admins[0], admins[1])
    care_coordinator       × 3   (coordinators[0..2])
    nurse_medication_aide  × 3   (nurses[0..2])
    billing_specialist     × 1   (billing)
    physician              × 1   (physician)
    participant_family     × 10  (families[0..9])
    compliance_officer     × 1   (compliance)

    Returns a dict with role-keyed entries; single-user roles return the object
    directly, multi-user roles return a list.
    """
    _first = {
        "program_administrator": ["Sandra",    "Marcus"],
        "care_coordinator":      ["Elena",     "David",   "Priya"],
        "nurse_medication_aide": ["James",     "Maria",   "Chen"],
        "billing_specialist":    ["Jerome"],
        "physician":             ["Robert"],
        "participant_family":    [f"Family{i:02d}" for i in range(1, 11)],
        "compliance_officer":    ["Renata"],
    }
    _last = {
        "program_administrator": ["Holloway",  "Delgado"],
        "care_coordinator":      ["Vasquez",   "Park",    "Nair"],
        "nurse_medication_aide": ["Okafor",    "Santos",  "Wei"],
        "billing_specialist":    ["Kimura"],
        "physician":             ["Sterling"],
        "participant_family":    [f"Member{i:02d}" for i in range(1, 11)],
        "compliance_officer":    ["Volkov"],
    }
    _specs = [
        ("admins",        "program_administrator",  2),
        ("coordinators",  "care_coordinator",        3),
        ("nurses",        "nurse_medication_aide",   3),
        ("billing",       "billing_specialist",      1),
        ("physician",     "physician",               1),
        ("families",      "participant_family",      10),
        ("compliance",    "compliance_officer",      1),
    ]

    result = {}
    for key, role, count in _specs:
        bucket = []
        for i in range(count):
            slug = f"{role.replace('_', '-')}-{i+1:02d}"
            payload = {
                "tenant_id":     tenant,
                "first_name":    _first[role][i],
                "last_name":     _last[role][i],
                "email":         f"{slug}@test.care",
                "role":          role,
                "password_hash": "ValidPass1!",
            }
            r = session_client.post("/users", json=payload, headers=_ADMIN)
            assert r.status_code == 201, (
                f"Failed to seed user {slug}: {r.status_code} — {r.text}"
            )
            bucket.append(r.json())
        result[key] = bucket[0] if count == 1 else bucket

    return result


@pytest.fixture(scope="session")
def participants(session_client, tenant, users):
    """
    Create 10 participants via POST /participants (and PATCH for status transitions).

    Composition
    -----------
    7  active          — varied demographics, no SUD flag
    1  active + SUD    — is_sud_record=True
    1  on_leave        — created active then patched
    1  deceased        — created active then patched

    Returns a dict:
        active   : list of 7 active participant dicts
        sud      : single participant dict (is_sud_record=True, active)
        on_leave : single participant dict
        deceased : single participant dict
        all      : flat list of all 10
    """
    today = datetime.now(timezone.utc).date()

    def _e(days_ago):
        return (today - timedelta(days=days_ago)).isoformat()

    def _post(first, last, dob, enrolled, medicaid, is_sud=False, **extra):
        payload = {
            "tenant_id":      tenant,
            "first_name":     first,
            "last_name":      last,
            "date_of_birth":  dob,
            "enrollment_date": enrolled,
            "medicaid_id":    medicaid,
            "is_sud_record":  is_sud,
        }
        payload.update(extra)
        r = session_client.post("/participants", json=payload, headers=_ADMIN)
        assert r.status_code == 201, (
            f"Failed to seed participant {medicaid}: {r.status_code} — {r.text}"
        )
        return r.json()

    def _patch_status(participant, new_status):
        r = session_client.patch(
            f"/participants/{participant['participant_id']}",
            json={"version": participant["version"], "program_status": new_status},
            headers=_ADMIN,
        )
        assert r.status_code == 200, (
            f"Failed to transition {participant['participant_id']} "
            f"to {new_status}: {r.status_code} — {r.text}"
        )
        return r.json()

    # 7 regular active participants — enrollment dates spread over ~2 years back
    active_seed = [
        ("Eleanor", "Vasquez",  "1942-03-14", _e(500),  "SEED-MC-001"),
        ("Robert",  "Kimura",   "1938-11-28", _e(700),  "SEED-MC-002"),
        ("Dorothy", "Franklin", "1950-06-05", _e(450),  "SEED-MC-003"),
        ("Harold",  "Nguyen",   "1945-09-20", _e(750),  "SEED-MC-004"),
        ("Agnes",   "Petrov",   "1948-01-12", _e(350),  "SEED-MC-005"),
        ("James",   "Okonkwo",  "1952-07-30", _e(290),  "SEED-MC-006"),
        ("Miriam",  "Torres",   "1955-11-03", _e(130),  "SEED-MC-007"),
    ]
    active = [_post(*row) for row in active_seed]

    # 1 SUD-flagged active participant
    p_sud = _post(
        "Franklin", "Reed", "1961-04-22", _e(270), "SEED-MC-008",
        is_sud=True,
    )

    # 1 on_leave  (active → on_leave)
    p_on_leave = _patch_status(
        _post("Ingrid", "Bauer", "1949-08-08", _e(480), "SEED-MC-009"),
        "on_leave",
    )

    # 1 deceased  (active → deceased)
    p_deceased = _patch_status(
        _post("Victor", "Sousa", "1935-12-15", _e(1200), "SEED-MC-010"),
        "deceased",
    )

    return {
        "active":   active,
        "sud":      p_sud,
        "on_leave": p_on_leave,
        "deceased": p_deceased,
        "all":      active + [p_sud, p_on_leave, p_deceased],
    }


# ════════════════════════════════════════════════════════════════════════════
# FUNCTION-SCOPED DB SESSION  (for direct DB assertions in tests)
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="function")
def db_session(session_engine):
    """SQLAlchemy session against the shared in-memory database."""
    TestSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=session_engine
    )
    session = TestSessionLocal()
    yield session
    session.close()


# ════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE CLIENT FIXTURE
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="function")
def client(session_client):
    """
    Exposes the shared session client under the name 'client' so that
    existing tests require no changes.
    """
    return session_client


# ════════════════════════════════════════════════════════════════════════════
# HEADER FIXTURES  (backward-compatible, function-scoped)
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def admin_headers():
    return make_headers("program_administrator", user_id=ADMIN_ID)


@pytest.fixture
def coordinator_headers():
    return make_headers("care_coordinator", user_id=COORDINATOR_ID)


@pytest.fixture
def nurse_headers():
    return make_headers("nurse_medication_aide", user_id=NURSE_ID)


@pytest.fixture
def billing_headers():
    return make_headers("billing_specialist", user_id=BILLING_ID)


@pytest.fixture
def physician_headers():
    return make_headers("physician", user_id=PHYSICIAN_ID)


@pytest.fixture
def family_headers():
    return make_headers("participant_family", user_id=FAMILY_ID)


@pytest.fixture
def compliance_headers():
    return make_headers("compliance_officer", user_id=COMPLIANCE_ID)


# ════════════════════════════════════════════════════════════════════════════
# FUNCTION-SCOPED FRESH FIXTURES
# Each fixture is fully self-contained: it creates its own participant (and
# any supporting records), yields the resource(s), then cleans up via API.
# ════════════════════════════════════════════════════════════════════════════

def _unique_medicaid() -> str:
    return f"FRESH-{uuid.uuid4().hex[:8].upper()}"


def _soft_delete(c, participant_id: str) -> None:
    """Soft-delete a participant; silently ignores any error (already deleted, etc.)."""
    try:
        c.delete(f"/participants/{participant_id}", headers=_ADMIN)
    except Exception:
        pass


# ── fresh_participant ─────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_participant(session_client, tenant):
    """
    Yields one newly created Participant dict.
    Soft-deleted via DELETE /participants/{id} in teardown.
    """
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    yield p
    _soft_delete(session_client, p["participant_id"])


# ── fresh_attendance ──────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_attendance(session_client, tenant):
    """
    Yields (attendance, participant) for one pending Attendance record.

    Teardown: voids attendance if not already billed/voided, then soft-deletes
    the participant.
    """
    today = datetime.now(timezone.utc).date()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att = make_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=(today - timedelta(days=10)).isoformat(),
    )
    yield att, p

    # Void if still voidable
    try:
        r = session_client.get(
            f"/attendance/{att['attendance_id']}", headers=_ADMIN
        )
        if r.status_code == 200:
            current = r.json()
            if current["status"] not in ("voided", "billed"):
                session_client.patch(
                    f"/attendance/{att['attendance_id']}",
                    json={
                        "version":     current["version"],
                        "status":      "voided",
                        "void_reason": "test cleanup",
                    },
                    headers=_ADMIN,
                )
    except Exception:
        pass
    _soft_delete(session_client, p["participant_id"])


# ── fresh_claim ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_claim(session_client, tenant):
    """
    Yields (claim, attendance, participant) for one draft Claim backed by a
    confirmed Attendance record.

    Teardown: soft-deletes the participant.  The attendance becomes billed and
    cannot be voided; the claim has no delete endpoint — both remain in the DB
    as orphaned records tied to the soft-deleted participant.
    """
    today = datetime.now(timezone.utc).date()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=(today - timedelta(days=11)).isoformat(),
    )
    claim = make_claim(
        session_client, _BILLING,
        participant_id=p["participant_id"],
        attendance_ids=[att["attendance_id"]],
        tenant_id=tenant,
    )
    yield claim, att, p
    _soft_delete(session_client, p["participant_id"])


# ── fresh_mar_record ──────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_mar_record(session_client, tenant):
    """
    Yields (mar_record, nurse_user, participant) for one administered MARRecord.

    Teardown: soft-deletes the participant (MAR record has no delete endpoint).
    """
    scheduled = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    nurse_user = make_nurse_user(session_client, _ADMIN, tenant_id=tenant)
    mar = make_mar_record(
        session_client, _NURSE,
        participant_id=p["participant_id"],
        administered_by=nurse_user["user_id"],
        tenant_id=tenant,
        scheduled_time=scheduled,
        status="administered",
    )
    yield mar, nurse_user, p
    _soft_delete(session_client, p["participant_id"])


# ── fresh_incident ────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_incident(session_client, tenant):
    """
    Yields (incident, participant) for one draft minor Incident.

    Teardown: closes the incident (draft → submitted → closed) if it is still
    in an open state, then soft-deletes the participant.
    """
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    inc = make_incident(
        session_client, _ADMIN,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        severity="minor",
    )
    yield inc, p

    # Close the incident if still open
    try:
        r = session_client.get(
            f"/incidents/{inc['incident_id']}", headers=_ADMIN
        )
        if r.status_code == 200:
            current = r.json()
            if current["status"] == "draft":
                r2 = session_client.patch(
                    f"/incidents/{inc['incident_id']}",
                    json={"version": current["version"], "status": "submitted"},
                    headers=_ADMIN,
                )
                if r2.status_code == 200:
                    session_client.patch(
                        f"/incidents/{inc['incident_id']}",
                        json={"version": r2.json()["version"], "status": "closed"},
                        headers=_ADMIN,
                    )
    except Exception:
        pass
    _soft_delete(session_client, p["participant_id"])


# ════════════════════════════════════════════════════════════════════════════
# CLAIM TEST FIXTURES (TC-4.x)
# ════════════════════════════════════════════════════════════════════════════

# ── fresh_confirmed_attendance ────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_confirmed_attendance(session_client, tenant):
    """
    Yields (attendance, participant) for one confirmed Attendance with no claim.
    Teardown: soft-deletes the participant.
    """
    today = datetime.now(timezone.utc).date()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=(today - timedelta(days=12)).isoformat(),
        total_hours=1.0,
    )
    yield att, p
    _soft_delete(session_client, p["participant_id"])


# ── claim_dup_ref_setup ───────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def claim_dup_ref_setup(session_client, tenant, db_session, monkeypatch):
    """
    TC-4.1 fixture.
    Inserts a claim with a fixture-computed reference directly into the DB,
    then patches _gen_claim_ref so every POST /claims attempt generates that
    same value.  After 5 collisions the server returns CLAIM_DUPLICATE_REFERENCE
    (409).  Yields (participant, confirmed_attendance, ref_number).
    """
    import main as _backend_main

    today = datetime.now(timezone.utc).date()
    fixed_dup_ref = f"MCD-{today.strftime('%Y%m%d')}-DUPREF1"
    dos_att = (today - timedelta(days=13)).isoformat()
    dos_insert = (today - timedelta(days=14)).isoformat()

    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_att,
    )
    # Direct insert: pre-seed a claim that owns the fixed reference number.
    # A placeholder participant_id is used so the composite duplicate check
    # cannot fire when the test POSTs using p["participant_id"].
    db_session.execute(
        text(
            "INSERT INTO claim "
            "(claim_id, tenant_id, participant_id, attendance_ids, payer_type, "
            "claim_reference_number, procedure_code, date_of_service_start, "
            "claim_status, version, created_at, updated_at) VALUES "
            "(:cid, :tid, 'placeholder-pid-dup-ref', :aids, 'medicaid', :ref, "
            "'T2029', :dos, 'draft', 1, datetime('now'), datetime('now'))"
        ),
        {
            "cid": str(uuid.uuid4()),
            "tid": tenant,
            "aids": json.dumps([]),
            "ref": fixed_dup_ref,
            "dos": dos_insert,
        },
    )
    db_session.commit()
    monkeypatch.setattr(_backend_main, "_gen_claim_ref", lambda _pt: fixed_dup_ref)
    yield p, att, fixed_dup_ref
    _soft_delete(session_client, p["participant_id"])


# ── claim_dup_composite_setup ─────────────────────────────────────────────────

@pytest.fixture(scope="function")
def claim_dup_composite_setup(session_client, tenant):
    """
    TC-4.2 fixture.
    Creates participant P1, confirmed att1 (used in existing claim), an
    existing claim, and confirmed att2 (used in the duplicate POST attempt).
    Yields (participant, att1, existing_claim, att2).
    """
    today = datetime.now(timezone.utc).date()
    dos_att1    = (today - timedelta(days=20)).isoformat()
    dos_start   = (today - timedelta(days=30)).isoformat()
    dos_att2    = (today - timedelta(days=21)).isoformat()

    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att1 = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_att1,
    )
    existing_claim = make_claim(
        session_client, _BILLING,
        participant_id=p["participant_id"],
        attendance_ids=[att1["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start=dos_start,
        procedure_code="T2029",
        payer_type="medicaid",
    )
    att2 = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_att2,
    )
    yield p, att1, existing_claim, att2
    _soft_delete(session_client, p["participant_id"])


# ── attendance_variety_setup ──────────────────────────────────────────────────

@pytest.fixture(scope="function")
def attendance_variety_setup(session_client, tenant):
    """
    TC-4.5 / TC-4.12 fixture.
    Yields a dict with keys:
        participant      : active participant in TENANT_A
        att_pending      : pending attendance (TENANT_A)
        att_voided       : voided attendance (TENANT_A)
        att_confirmed    : confirmed attendance (TENANT_A, total_hours=1.0)
        att_other_tenant : confirmed attendance in TENANT_B
        participant_b    : participant in TENANT_B
    """
    today = datetime.now(timezone.utc).date()
    dos_pending   = (today - timedelta(days=40)).isoformat()
    dos_void      = (today - timedelta(days=41)).isoformat()
    dos_confirmed = (today - timedelta(days=42)).isoformat()
    dos_other     = (today - timedelta(days=43)).isoformat()

    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_pending = make_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_pending,
    )
    att_to_void = make_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_void,
    )
    r_void = session_client.patch(
        f"/attendance/{att_to_void['attendance_id']}",
        json={
            "version": att_to_void["version"],
            "status": "voided",
            "void_reason": "TC-4.5 fixture setup",
        },
        headers=_ADMIN,
    )
    assert r_void.status_code == 200, f"Failed to void attendance: {r_void.text}"
    att_voided = r_void.json()

    att_confirmed = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_confirmed,
        total_hours=1.0,
    )

    _admin_b = make_headers(
        "program_administrator", tenant_id=TENANT_B, user_id="bootstrap-admin-tenantb-claim-001"
    )
    _coord_b = make_headers(
        "care_coordinator", tenant_id=TENANT_B, user_id="bootstrap-coord-tenantb-claim-001"
    )
    p_b = make_participant(
        session_client, _admin_b,
        tenant_id=TENANT_B,
        medicaid_id=_unique_medicaid(),
    )
    att_other = make_confirmed_attendance(
        session_client, _coord_b,
        participant_id=p_b["participant_id"],
        tenant_id=TENANT_B,
        date_of_service=dos_other,
        total_hours=1.0,
    )

    yield {
        "participant": p,
        "att_pending": att_pending,
        "att_voided": att_voided,
        "att_confirmed": att_confirmed,
        "att_other_tenant": att_other,
        "participant_b": p_b,
    }
    _soft_delete(session_client, p["participant_id"])
    _soft_delete(session_client, p_b["participant_id"])


# ── three_confirmed_attendances ───────────────────────────────────────────────

@pytest.fixture(scope="function")
def three_confirmed_attendances(session_client, tenant):
    """
    TC-4.6 fixture.
    Participant P1 with three confirmed attendances:
        att_a: total_hours=1.0 → authorized_units_consumed=4.0
        att_b: total_hours=1.5 → authorized_units_consumed=6.0
        att_c: total_hours=2.0 → authorized_units_consumed=8.0
    Sum = 18.0; server uses this sum as units_billed when creating a claim.
    Yields (participant, att_a, att_b, att_c).
    """
    today = datetime.now(timezone.utc).date()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_a = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=(today - timedelta(days=50)).isoformat(),
        total_hours=1.0,
    )
    att_b = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=(today - timedelta(days=51)).isoformat(),
        total_hours=1.5,
    )
    att_c = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service=(today - timedelta(days=52)).isoformat(),
        total_hours=2.0,
    )
    yield p, att_a, att_b, att_c
    _soft_delete(session_client, p["participant_id"])


# ── submitted_and_paid_claims ─────────────────────────────────────────────────

@pytest.fixture(scope="function")
def submitted_and_paid_claims(session_client, tenant):
    """
    TC-4.4 / TC-4.15 fixture.
    claim_submitted: draft → submitted via PATCH claim_status="submitted".
    claim_paid:      draft → paid via PATCH claim_status="paid" (direct override).
    Yields (claim_submitted, claim_paid, participant_a, participant_b).
    """
    today = datetime.now(timezone.utc).date()
    dos_a = (today - timedelta(days=60)).isoformat()
    dos_b = (today - timedelta(days=61)).isoformat()

    p_a = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_a = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p_a["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_a,
    )
    c_a = make_claim(
        session_client, _BILLING,
        participant_id=p_a["participant_id"],
        attendance_ids=[att_a["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start=dos_a,
    )
    r_sub = session_client.patch(
        f"/claims/{c_a['claim_id']}",
        json={"version": c_a["version"], "claim_status": "submitted"},
        headers=_BILLING,
    )
    assert r_sub.status_code == 200, f"Failed to submit claim: {r_sub.text}"
    claim_submitted = r_sub.json()

    p_b = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_b = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p_b["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_b,
    )
    c_b = make_claim(
        session_client, _BILLING,
        participant_id=p_b["participant_id"],
        attendance_ids=[att_b["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start=dos_b,
    )
    r_paid = session_client.patch(
        f"/claims/{c_b['claim_id']}",
        json={"version": c_b["version"], "claim_status": "paid"},
        headers=_BILLING,
    )
    assert r_paid.status_code == 200, f"Failed to set claim to paid: {r_paid.text}"
    claim_paid = r_paid.json()

    yield claim_submitted, claim_paid, p_a, p_b
    _soft_delete(session_client, p_a["participant_id"])
    _soft_delete(session_client, p_b["participant_id"])


# ── draft_and_submitted_claims ────────────────────────────────────────────────

@pytest.fixture(scope="function")
def draft_and_submitted_claims(session_client, tenant):
    """
    TC-4.11 fixture.
    C_A: draft claim (version=1 after creation).
    C_B: draft → submitted (version incremented after submit PATCH).
    Yields (claim_draft, claim_submitted, participant_a, participant_b).
    """
    today = datetime.now(timezone.utc).date()
    dos_a = (today - timedelta(days=70)).isoformat()
    dos_b = (today - timedelta(days=71)).isoformat()

    p_a = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_a = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p_a["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_a,
    )
    c_a = make_claim(
        session_client, _BILLING,
        participant_id=p_a["participant_id"],
        attendance_ids=[att_a["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start=dos_a,
    )

    p_b = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_b = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p_b["participant_id"],
        tenant_id=tenant,
        date_of_service=dos_b,
    )
    c_b_draft = make_claim(
        session_client, _BILLING,
        participant_id=p_b["participant_id"],
        attendance_ids=[att_b["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start=dos_b,
    )
    r_sub = session_client.patch(
        f"/claims/{c_b_draft['claim_id']}",
        json={"version": c_b_draft["version"], "claim_status": "submitted"},
        headers=_BILLING,
    )
    assert r_sub.status_code == 200, f"Failed to submit claim C_B: {r_sub.text}"
    c_b = r_sub.json()

    yield c_a, c_b, p_a, p_b
    _soft_delete(session_client, p_a["participant_id"])
    _soft_delete(session_client, p_b["participant_id"])


# ════════════════════════════════════════════════════════════════════════════
# MAR RECORD TEST FIXTURES (TC-5.x)
# ════════════════════════════════════════════════════════════════════════════

# ── mar_write_setup ───────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def mar_write_setup(session_client, tenant):
    """
    TC-5.2, TC-5.3, TC-5.5, TC-5.7–TC-5.13 fixture.
    Yields (participant, nurse_user) for tests that create or attempt to create
    MAR records.  No MAR is pre-seeded.
    """
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    nurse_user = make_nurse_user(session_client, _ADMIN, tenant_id=tenant)
    yield p, nurse_user
    _soft_delete(session_client, p["participant_id"])


# ── mar_dup_setup ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def mar_dup_setup(session_client, tenant):
    """
    TC-5.1 fixture.
    Pre-seeds one administered MAR.  Test attempts a duplicate POST to the same
    (participant, medication, scheduled_time) tuple.
    Yields (participant, nurse_user, first_mar).
    """
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    nurse_user = make_nurse_user(session_client, _ADMIN, tenant_id=tenant)
    first_mar = make_mar_record(
        session_client, _NURSE,
        participant_id=p["participant_id"],
        administered_by=nurse_user["user_id"],
        tenant_id=tenant,
        scheduled_time=scheduled,
        medication_name="Lisinopril 10mg",
        status="administered",
    )
    yield p, nurse_user, first_mar
    _soft_delete(session_client, p["participant_id"])


# ── controlled_substance_mar_setup ────────────────────────────────────────────

@pytest.fixture(scope="function")
def controlled_substance_mar_setup(session_client, tenant):
    """
    TC-5.4, TC-5.6 fixture.
    Pre-seeds one controlled-substance administered MAR.
    Yields (participant, nurse_user, cs_mar).
    """
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S")
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    nurse_user = make_nurse_user(session_client, _ADMIN, tenant_id=tenant)
    cs_mar = make_mar_record(
        session_client, _NURSE,
        participant_id=p["participant_id"],
        administered_by=nurse_user["user_id"],
        tenant_id=tenant,
        scheduled_time=scheduled,
        medication_name="Oxycodone 5mg",
        is_controlled_substance=True,
        status="administered",
    )
    yield p, nurse_user, cs_mar
    _soft_delete(session_client, p["participant_id"])


# ── fresh_missed_mar ──────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_missed_mar(session_client, tenant):
    """
    TC-5.16–TC-5.20 fixture.
    Pre-seeds one missed MAR with notes.
    Yields (mar, nurse_user, participant).
    """
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    nurse_user = make_nurse_user(session_client, _ADMIN, tenant_id=tenant)
    mar = make_mar_record(
        session_client, _NURSE,
        participant_id=p["participant_id"],
        administered_by=nurse_user["user_id"],
        tenant_id=tenant,
        scheduled_time=scheduled,
        medication_name="Metformin 500mg",
        status="missed",
        notes="Patient refused medication at scheduled time.",
    )
    yield mar, nurse_user, p
    _soft_delete(session_client, p["participant_id"])


# ── mar_version_conflict_setup ────────────────────────────────────────────────

@pytest.fixture(scope="function")
def mar_version_conflict_setup(session_client, tenant):
    """
    TC-5.21 fixture.
    Creates a missed MAR then PATCHes it once to produce version=2.
    Yields (mar_v2, nurse_user, participant).  Test uses mar_v2["version"]-1 as
    the stale version to trigger MAR_VERSION_CONFLICT.
    """
    now = datetime.now(timezone.utc)
    scheduled = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S")
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    nurse_user = make_nurse_user(session_client, _ADMIN, tenant_id=tenant)
    mar = make_mar_record(
        session_client, _NURSE,
        participant_id=p["participant_id"],
        administered_by=nurse_user["user_id"],
        tenant_id=tenant,
        scheduled_time=scheduled,
        medication_name="Lisinopril 5mg",
        status="missed",
        notes="Initial missed dose documentation.",
    )
    r_patch = session_client.patch(
        f"/mar-records/{mar['mar_id']}",
        json={"version": mar["version"], "notes": "Updated missed dose documentation."},
        headers=_NURSE,
    )
    assert r_patch.status_code == 200, f"mar_version_conflict_setup PATCH failed: {r_patch.text}"
    mar_v2 = r_patch.json()
    yield mar_v2, nurse_user, p
    _soft_delete(session_client, p["participant_id"])


# ════════════════════════════════════════════════════════════════════════════
# INCIDENT TEST FIXTURES (TC-6.x)
# ════════════════════════════════════════════════════════════════════════════

# ── fresh_incident_sud ────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_incident_sud(session_client, tenant):
    """
    TC-6.4, TC-6.5, TC-6.7 fixture.
    Pre-seeds a SUD-related minor draft incident.
    Yields (incident, participant).
    """
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=110)).isoformat()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
        is_sud_record=True,
    )
    inc = make_incident(
        session_client, _ADMIN,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        severity="minor",
        is_sud_related=True,
        incident_date=incident_date,
    )
    yield inc, p
    _soft_delete(session_client, p["participant_id"])


# ── fresh_incident_escalated ──────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_incident_escalated(session_client, tenant):
    """
    TC-6.9, TC-6.13 fixture.
    Creates a severe incident that is auto-escalated on creation.
    Yields (incident, participant).
    """
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=111)).isoformat()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    inc = make_incident(
        session_client, _ADMIN,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        severity="severe",
        incident_date=incident_date,
    )
    yield inc, p
    _soft_delete(session_client, p["participant_id"])


# ── overdue_escalated_incident_setup ─────────────────────────────────────────

@pytest.fixture(scope="function")
def overdue_escalated_incident_setup(session_client, tenant, db_session):
    """
    TC-6.10 fixture.
    Creates a severe (auto-escalated) incident, then backdates created_at to
    21 h ago so the /jobs/escalated-incidents-alert endpoint includes it.
    Yields (incident, participant).
    """
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=112)).isoformat()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    inc = make_incident(
        session_client, _ADMIN,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        severity="severe",
        incident_date=incident_date,
    )
    overdue_ts = (datetime.now(timezone.utc) - timedelta(hours=21)).strftime("%Y-%m-%d %H:%M:%S")
    db_session.execute(
        text("UPDATE incident SET created_at = :ts WHERE incident_id = :iid"),
        {"ts": overdue_ts, "iid": inc["incident_id"]},
    )
    db_session.commit()
    yield inc, p
    _soft_delete(session_client, p["participant_id"])


# ── fresh_incident_open ───────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_incident_open(session_client, tenant):
    """
    TC-6.11 fixture.
    Pre-seeds a draft (open) minor incident.
    Yields (incident, participant).
    """
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=113)).isoformat()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    inc = make_incident(
        session_client, _ADMIN,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        severity="minor",
        incident_date=incident_date,
    )
    yield inc, p
    _soft_delete(session_client, p["participant_id"])


# ── fresh_incident_closed ─────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def fresh_incident_closed(session_client, tenant):
    """
    TC-6.8, TC-6.12, TC-6.15 fixture.
    Creates a draft incident then PATCHes it to closed (version=2).
    Yields (closed_incident, participant).
    """
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=114)).isoformat()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    inc = make_incident(
        session_client, _ADMIN,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        severity="minor",
        incident_date=incident_date,
    )
    r_close = session_client.patch(
        f"/incidents/{inc['incident_id']}",
        json={"version": inc["version"], "status": "closed"},
        headers=_ADMIN,
    )
    assert r_close.status_code == 200, f"fresh_incident_closed PATCH failed: {r_close.text}"
    closed_inc = r_close.json()
    yield closed_inc, p
    _soft_delete(session_client, p["participant_id"])


# ── incident_version3_setup ───────────────────────────────────────────────────

@pytest.fixture(scope="function")
def incident_version3_setup(session_client, tenant):
    """
    TC-6.14 fixture.
    Creates a draft incident and PATCHes it twice to reach version=3.
    Yields (incident_v3, participant).
    """
    today = datetime.now(timezone.utc).date()
    incident_date = (today - timedelta(days=115)).isoformat()
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    inc = make_incident(
        session_client, _ADMIN,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        severity="minor",
        incident_date=incident_date,
    )
    r1 = session_client.patch(
        f"/incidents/{inc['incident_id']}",
        json={"version": inc["version"], "location": "Day room"},
        headers=_ADMIN,
    )
    assert r1.status_code == 200, f"incident_version3_setup PATCH 1 failed: {r1.text}"
    inc_v2 = r1.json()
    r2 = session_client.patch(
        f"/incidents/{inc['incident_id']}",
        json={"version": inc_v2["version"], "location": "Hallway"},
        headers=_ADMIN,
    )
    assert r2.status_code == 200, f"incident_version3_setup PATCH 2 failed: {r2.text}"
    inc_v3 = r2.json()
    yield inc_v3, p
    _soft_delete(session_client, p["participant_id"])
