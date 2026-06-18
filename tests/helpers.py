"""Utility helpers for Care Art Phase 1 tests."""

import uuid
from datetime import datetime, timezone, timedelta

TENANT_A = "tenant-aaa-001"
TENANT_B = "tenant-bbb-002"

ADMIN_ID = "user-admin-001"
COORDINATOR_ID = "user-coord-001"
NURSE_ID = "user-nurse-001"
BILLING_ID = "user-billing-001"
PHYSICIAN_ID = "user-physician-001"
FAMILY_ID = "user-family-001"
COMPLIANCE_ID = "user-compliance-001"
INVALID_COORDINATOR_ID = "some-other-coordinator"


def make_headers(
    role: str,
    tenant_id: str = TENANT_A,
    user_id: str = "test-user",
    status: str = "active",
    mfa: bool = True,
) -> dict:
    return {
        "X-User-Id": user_id,
        "X-User-Role": role,
        "X-Tenant-Id": tenant_id,
        "X-User-Status": status,
        "X-User-MFA": "true" if mfa else "false",
    }


def make_participant(client, headers, tenant_id=TENANT_A, medicaid_id=None,
                     is_sud_record=False, **kwargs):
    enrollment_date = kwargs.pop(
        "enrollment_date",
        datetime.now(timezone.utc).date().isoformat(),
    )
    payload = {
        "tenant_id": tenant_id,
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": (datetime.now(timezone.utc).date() - timedelta(days=365 * 45)).isoformat(),
        "enrollment_date": enrollment_date,
        "is_sud_record": is_sud_record,
    }
    if medicaid_id:
        payload["medicaid_id"] = medicaid_id
    payload.update(kwargs)
    r = client.post("/participants", json=payload, headers=headers)
    assert r.status_code == 201, f"Participant creation failed: {r.text}"
    return r.json()


def make_user(client, headers, tenant_id=TENANT_A, email=None, role="care_coordinator", **kwargs):
    payload = {
        "tenant_id": tenant_id,
        "first_name": "Test",
        "last_name": "User",
        "email": email or f"user-{uuid.uuid4().hex[:8]}@example.com",
        "role": role,
    }
    payload.update(kwargs)
    r = client.post("/users", json=payload, headers=headers)
    assert r.status_code == 201, f"User creation failed: {r.text}"
    return r.json()


def make_nurse_user(client, headers, tenant_id=TENANT_A, email=None):
    return make_user(
        client, headers, tenant_id=tenant_id,
        email=email or f"nurse-{uuid.uuid4().hex[:8]}@example.com",
        role="nurse_medication_aide",
    )


def make_attendance(client, headers, participant_id, tenant_id=TENANT_A,
                    date_of_service=None, status="pending", **kwargs):
    if date_of_service is None:
        date_of_service = (datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat()
    payload = {
        "tenant_id": tenant_id,
        "participant_id": participant_id,
        "date_of_service": date_of_service,
        "status": status,
    }
    payload.update(kwargs)
    r = client.post("/attendance", json=payload, headers=headers)
    assert r.status_code == 201, f"Attendance creation failed: {r.text}"
    return r.json()


def make_confirmed_attendance(client, headers, participant_id, tenant_id=TENANT_A,
                              date_of_service=None, **kwargs):
    if date_of_service is None:
        date_of_service = (datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat()
    att = make_attendance(client, headers, participant_id, tenant_id, date_of_service, **kwargs)
    att_id = att["attendance_id"]
    r = client.patch(
        f"/attendance/{att_id}",
        json={"version": att["version"], "status": "confirmed"},
        headers=headers,
    )
    assert r.status_code == 200, f"Attendance confirmation failed: {r.text}"
    return r.json()


def make_claim(client, headers, participant_id, attendance_ids, tenant_id=TENANT_A, **kwargs):
    if "date_of_service_start" not in kwargs:
        kwargs["date_of_service_start"] = (
            datetime.now(timezone.utc).date() - timedelta(days=11)
        ).isoformat()
    payload = {
        "tenant_id": tenant_id,
        "participant_id": participant_id,
        "attendance_ids": attendance_ids,
        "payer_type": "medicaid",
        "procedure_code": "S5101",
    }
    payload.update(kwargs)
    r = client.post("/claims", json=payload, headers=headers)
    assert r.status_code == 201, f"Claim creation failed: {r.text}"
    return r.json()


def make_mar_record(client, headers, participant_id, administered_by,
                    tenant_id=TENANT_A, scheduled_time=None,
                    is_controlled_substance=False, status="administered",
                    medication_name="Metformin", **kwargs):
    st = scheduled_time or (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    payload = {
        "tenant_id": tenant_id,
        "participant_id": participant_id,
        "medication_name": medication_name,
        "administered_by": administered_by,
        "scheduled_time": st,
        "status": status,
        "is_controlled_substance": is_controlled_substance,
    }
    if status == "administered" and "administered_time" not in kwargs:
        st_date = st[:10]
        st_hour = int(st[11:13])
        st_min = int(st[14:16])
        admin_min = st_min + 5
        admin_hour = st_hour + (1 if admin_min >= 60 else 0)
        admin_min = admin_min % 60
        payload["administered_time"] = f"{st_date}T{admin_hour:02d}:{admin_min:02d}:00"
    payload.update(kwargs)
    r = client.post("/mar-records", json=payload, headers=headers)
    assert r.status_code == 201, f"MAR record creation failed: {r.text}"
    return r.json()


def make_incident(client, headers, participant_id, tenant_id=TENANT_A,
                  incident_type="fall", severity="minor", is_sud_related=False,
                  incident_date=None, description="Test incident.", **kwargs):
    if incident_date is None:
        incident_date = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
    payload = {
        "tenant_id": tenant_id,
        "participant_id": participant_id,
        "incident_date": incident_date,
        "incident_type": incident_type,
        "description": description,
        "severity": severity,
        "is_sud_related": is_sud_related,
        "status": "draft",
    }
    payload.update(kwargs)
    r = client.post("/incidents", json=payload, headers=headers)
    assert r.status_code == 201, f"Incident creation failed: {r.text}"
    return r.json()


# ── Phase 2 helpers ──────────────────────────────────────────────────────────


def make_care_plan(client, headers, participant_id, tenant_id=TENANT_A,
                   version_number=None, **kwargs):
    payload = {
        "tenant_id": tenant_id,
        "participant_id": participant_id,
    }
    if version_number is not None:
        payload["version_number"] = version_number
    payload.update(kwargs)
    r = client.post("/care-plans", json=payload, headers=headers)
    assert r.status_code == 201, f"CarePlan creation failed: {r.text}"
    return r.json()


def make_care_plan_goal(client, headers, care_plan_id, tenant_id=TENANT_A,
                        domain="functional",
                        description="Improve ambulation distance",
                        **kwargs):
    payload = {
        "tenant_id": tenant_id,
        "care_plan_id": care_plan_id,
        "domain": domain,
        "description": description,
    }
    payload.update(kwargs)
    r = client.post("/care-plan-goals", json=payload, headers=headers)
    assert r.status_code == 201, f"CarePlanGoal creation failed: {r.text}"
    return r.json()


def activate_care_plan(client, headers, care_plan_id, version,
                       physician_id, effective_date=None,
                       physician_signature_date=None):
    if effective_date is None:
        effective_date = datetime.now(timezone.utc).date().isoformat()
    if physician_signature_date is None:
        physician_signature_date = datetime.now(timezone.utc).date().isoformat()
    r = client.patch(
        f"/care-plans/{care_plan_id}",
        json={
            "version": version,
            "status": "active",
            "effective_date": effective_date,
            "physician_id": physician_id,
            "physician_signature_date": physician_signature_date,
        },
        headers=headers,
    )
    assert r.status_code == 200, f"CarePlan activation failed: {r.text}"
    return r.json()


def make_appointment(client, headers, participant_id, physician_id,
                     tenant_id=TENANT_A, **kwargs):
    now = datetime.now(timezone.utc)
    offset_days = 7 + hash(uuid.uuid4()) % 300
    start = kwargs.pop("scheduled_start",
                       (now + timedelta(days=offset_days)).isoformat())
    end = kwargs.pop("scheduled_end",
                     (now + timedelta(days=offset_days, hours=1)).isoformat())
    payload = {
        "tenant_id": tenant_id,
        "participant_id": participant_id,
        "physician_id": physician_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "appointment_type": "routine",
    }
    payload.update(kwargs)
    r = client.post("/appointments", json=payload, headers=headers)
    assert r.status_code == 201, f"Appointment creation failed: {r.text}"
    return r.json()


def make_consent(client, headers, participant_id, tenant_id=TENANT_A,
                 disclosure_recipient_type="ehr", **kwargs):
    today = datetime.now(timezone.utc).date()
    payload = {
        "tenant_id": tenant_id,
        "participant_id": participant_id,
        "disclosure_recipient_type": disclosure_recipient_type,
        "disclosure_recipient_name": "Dr. Smith EHR",
        "disclosure_purpose": "Treatment coordination",
        "scope_description": "Full care plan records",
        "effective_date": today.isoformat(),
        "expiration_date": (today + timedelta(days=365)).isoformat(),
        "consent_form_reference": "FORM-001",
        "consent_method": "written",
        "participant_signature_date": today.isoformat(),
    }
    payload.update(kwargs)
    r = client.post("/consents", json=payload, headers=headers)
    assert r.status_code == 201, f"Consent creation failed: {r.text}"
    return r.json()
