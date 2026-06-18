"""
test_rbac_sweep_phase2.py — Phase 2 role access matrix tests.

Regulatory scope: HIPAA · 42 CFR Part 2
"""
import uuid
from datetime import datetime, timezone, timedelta

from helpers import (
    TENANT_A,
    ADMIN_ID, COORDINATOR_ID, NURSE_ID, BILLING_ID,
    PHYSICIAN_ID, FAMILY_ID, COMPLIANCE_ID,
    make_headers, make_participant, make_care_plan, make_appointment,
    make_consent,
)

_ADMIN = make_headers("program_administrator", user_id=ADMIN_ID)
_COORD = make_headers("care_coordinator", user_id=COORDINATOR_ID)
_NURSE = make_headers("nurse_medication_aide", user_id=NURSE_ID)


def _unique_medicaid():
    return f"RP2-{uuid.uuid4().hex[:8].upper()}"


# ─── RP2-1 ────────────────────────────────────────────────────────────────────


def test_rbac_p2_1_care_coordinator_write_on_care_plan_and_appointment(
    client, coordinator_headers, participants, users
):
    """RP2-1 — care_coordinator POST on CarePlan and Appointment returns 201."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    phys_id = users["physician"]["user_id"]

    cp = make_care_plan(client, coordinator_headers, p["participant_id"])
    assert cp["care_plan_id"] is not None

    appt = make_appointment(client, coordinator_headers,
                            p["participant_id"], phys_id)
    assert appt["appointment_id"] is not None


# ─── RP2-5 ────────────────────────────────────────────────────────────────────


def test_rbac_p2_5_billing_specialist_denied_all_phase2_entities(
    client, billing_headers, coordinator_headers, participants, users
):
    """RP2-5 — billing_specialist POST and GET on all five Phase 2 entities return 403."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]
    phys_id = users["physician"]["user_id"]

    cp = make_care_plan(client, _COORD, pid)
    appt = make_appointment(client, _COORD, pid, phys_id)

    now = datetime.now(timezone.utc)
    sched = (now + timedelta(days=30)).isoformat()
    reminder_payload = {
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "reminder_type": "general",
        "title": "Reminder",
        "body": "Check app",
        "scheduled_for": sched,
        "channel": "push",
        "reference_entity_type": "none",
    }
    consent_payload = {
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "disclosure_recipient_type": "ehr",
        "disclosure_recipient_name": "Test",
        "disclosure_purpose": "Test",
        "scope_description": "Test",
        "effective_date": now.date().isoformat(),
        "expiration_date": (now.date() + timedelta(days=365)).isoformat(),
        "consent_form_reference": "FORM-RP2",
        "consent_method": "written",
        "participant_signature_date": now.date().isoformat(),
    }

    post_endpoints = [
        ("/care-plans", {"tenant_id": TENANT_A, "participant_id": pid}),
        ("/appointments", {
            "tenant_id": TENANT_A, "participant_id": pid,
            "physician_id": phys_id,
            "scheduled_start": (now + timedelta(days=60)).isoformat(),
            "scheduled_end": (now + timedelta(days=60, hours=1)).isoformat(),
            "appointment_type": "routine",
        }),
        ("/medication-refills", {
            "tenant_id": TENANT_A, "participant_id": pid,
            "medication_name": "Metformin", "prescribing_physician_id": phys_id,
            "quantity_requested": 30,
            "requested_at": now.isoformat(),
        }),
        ("/reminders", reminder_payload),
        ("/consents", consent_payload),
    ]

    for endpoint, payload in post_endpoints:
        r = client.post(endpoint, json=payload, headers=billing_headers)
        assert r.status_code == 403, f"billing POST {endpoint} expected 403, got {r.status_code}"

    get_endpoints = [
        f"/care-plans/{cp['care_plan_id']}",
        f"/appointments/{appt['appointment_id']}",
        f"/care-plans?tenant_id={TENANT_A}",
    ]

    for endpoint in get_endpoints:
        r = client.get(endpoint, headers=billing_headers)
        assert r.status_code == 403, f"billing GET {endpoint} expected 403, got {r.status_code}"


# ─── RP2-9 ────────────────────────────────────────────────────────────────────


def test_rbac_p2_9_compliance_officer_read_all_phase2_entities(
    client, compliance_headers, coordinator_headers, participants, users
):
    """RP2-9 — compliance_officer GET on all five Phase 2 entities returns 200."""
    p = make_participant(client, _ADMIN, medicaid_id=_unique_medicaid())
    pid = p["participant_id"]
    phys_id = users["physician"]["user_id"]

    cp = make_care_plan(client, _COORD, pid)
    now = datetime.now(timezone.utc)
    appt_start = (now + timedelta(days=400)).isoformat()
    appt_end = (now + timedelta(days=400, hours=1)).isoformat()
    appt = make_appointment(client, _COORD, pid, phys_id,
                            scheduled_start=appt_start,
                            scheduled_end=appt_end)

    consent = make_consent(client, _COORD, pid, disclosure_recipient_type="ehr")

    sched = (now + timedelta(days=31)).isoformat()
    reminder = client.post("/reminders", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "reminder_type": "general",
        "title": "Reminder",
        "body": "Check app",
        "scheduled_for": sched,
        "channel": "push",
        "reference_entity_type": "none",
        "created_by": COORDINATOR_ID,
    }, headers=_COORD)
    assert reminder.status_code == 201
    reminder_id = reminder.json()["reminder_id"]

    med_refill = client.post("/medication-refills", json={
        "tenant_id": TENANT_A,
        "participant_id": pid,
        "medication_name": "Metformin",
        "prescribing_physician_id": phys_id,
        "quantity_requested": 30,
        "requested_at": now.isoformat(),
    }, headers=_NURSE)
    assert med_refill.status_code == 201
    refill_id = med_refill.json()["refill_id"]

    get_checks = [
        (f"/care-plans/{cp['care_plan_id']}", 200),
        (f"/appointments/{appt['appointment_id']}", 200),
        (f"/medication-refills/{refill_id}", 200),
        (f"/reminders/{reminder_id}", 200),
        (f"/consents/{consent['consent_id']}", 200),
    ]

    for endpoint, expected in get_checks:
        r = client.get(endpoint, headers=compliance_headers)
        assert r.status_code == expected, (
            f"compliance GET {endpoint} expected {expected}, got {r.status_code}"
        )
