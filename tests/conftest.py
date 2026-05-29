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

    # 7 regular active participants
    active_seed = [
        ("Eleanor", "Vasquez",  "1942-03-14", "2024-01-15", "SEED-MC-001"),
        ("Robert",  "Kimura",   "1938-11-28", "2023-09-01", "SEED-MC-002"),
        ("Dorothy", "Franklin", "1950-06-05", "2024-03-10", "SEED-MC-003"),
        ("Harold",  "Nguyen",   "1945-09-20", "2023-05-01", "SEED-MC-004"),
        ("Agnes",   "Petrov",   "1948-01-12", "2024-06-01", "SEED-MC-005"),
        ("James",   "Okonkwo",  "1952-07-30", "2024-08-15", "SEED-MC-006"),
        ("Miriam",  "Torres",   "1955-11-03", "2025-01-10", "SEED-MC-007"),
    ]
    active = [_post(*row) for row in active_seed]

    # 1 SUD-flagged active participant
    p_sud = _post(
        "Franklin", "Reed", "1961-04-22", "2024-09-01", "SEED-MC-008",
        is_sud=True,
    )

    # 1 on_leave  (active → on_leave)
    p_on_leave = _patch_status(
        _post("Ingrid", "Bauer", "1949-08-08", "2024-02-01", "SEED-MC-009"),
        "on_leave",
    )

    # 1 deceased  (active → deceased)
    p_deceased = _patch_status(
        _post("Victor", "Sousa", "1935-12-15", "2022-11-01", "SEED-MC-010"),
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
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att = make_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-03-01",
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
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-03-01",
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
        scheduled_time="2026-03-01T09:00:00",
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
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-05-01",
        total_hours=1.0,
    )
    yield att, p
    _soft_delete(session_client, p["participant_id"])


# ── claim_dup_ref_setup ───────────────────────────────────────────────────────

_FIXED_DUP_REF = "MCD-20260301-DUPREF1"


@pytest.fixture(scope="function")
def claim_dup_ref_setup(session_client, tenant, db_session, monkeypatch):
    """
    TC-4.1 fixture.
    Inserts a claim with _FIXED_DUP_REF directly into the DB, then patches
    _gen_claim_ref so every POST /claims attempt generates that same value.
    After 5 collisions the server returns CLAIM_DUPLICATE_REFERENCE (409).
    Yields (participant, confirmed_attendance, ref_number).
    """
    import main as _backend_main

    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-05-03",
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
            "'T2029', '2026-05-04', 'draft', 1, datetime('now'), datetime('now'))"
        ),
        {
            "cid": str(uuid.uuid4()),
            "tid": tenant,
            "aids": json.dumps([]),
            "ref": _FIXED_DUP_REF,
        },
    )
    db_session.commit()
    monkeypatch.setattr(_backend_main, "_gen_claim_ref", lambda _pt: _FIXED_DUP_REF)
    yield p, att, _FIXED_DUP_REF
    _soft_delete(session_client, p["participant_id"])


# ── claim_dup_composite_setup ─────────────────────────────────────────────────

@pytest.fixture(scope="function")
def claim_dup_composite_setup(session_client, tenant):
    """
    TC-4.2 fixture.
    Creates participant P1, confirmed att1 (used in existing claim), an
    existing claim keyed on (P1, 2026-03-01, T2029, medicaid), and confirmed
    att2 (used in the duplicate POST attempt).
    Yields (participant, att1, existing_claim, att2).
    """
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att1 = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-05-05",
    )
    existing_claim = make_claim(
        session_client, _BILLING,
        participant_id=p["participant_id"],
        attendance_ids=[att1["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start="2026-03-01",
        procedure_code="T2029",
        payer_type="medicaid",
    )
    att2 = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-05-06",
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
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_pending = make_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-06-01",
    )
    att_to_void = make_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-06-02",
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
        date_of_service="2026-06-03",
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
        date_of_service="2026-06-04",
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
    p = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_a = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-07-01",
        total_hours=1.0,
    )
    att_b = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-07-02",
        total_hours=1.5,
    )
    att_c = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-07-03",
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
    p_a = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_a = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p_a["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-08-01",
    )
    c_a = make_claim(
        session_client, _BILLING,
        participant_id=p_a["participant_id"],
        attendance_ids=[att_a["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start="2026-08-01",
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
        date_of_service="2026-08-02",
    )
    c_b = make_claim(
        session_client, _BILLING,
        participant_id=p_b["participant_id"],
        attendance_ids=[att_b["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start="2026-08-02",
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
    p_a = make_participant(
        session_client, _ADMIN,
        tenant_id=tenant,
        medicaid_id=_unique_medicaid(),
    )
    att_a = make_confirmed_attendance(
        session_client, _COORD,
        participant_id=p_a["participant_id"],
        tenant_id=tenant,
        date_of_service="2026-09-01",
    )
    c_a = make_claim(
        session_client, _BILLING,
        participant_id=p_a["participant_id"],
        attendance_ids=[att_a["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start="2026-09-01",
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
        date_of_service="2026-09-02",
    )
    c_b_draft = make_claim(
        session_client, _BILLING,
        participant_id=p_b["participant_id"],
        attendance_ids=[att_b["attendance_id"]],
        tenant_id=tenant,
        date_of_service_start="2026-09-02",
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
