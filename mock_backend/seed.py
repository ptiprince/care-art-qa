"""
Seed synthetic test data for Care Art mock backend.
Safe to re-run: wipes existing data and reloads from scratch.
No real PHI — all names, IDs, and values are fabricated.
"""

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from database import Base, SessionLocal, engine
from models import Attendance, Claim, Incident, MARRecord, Participant, User

# ─── Fixed IDs ────────────────────────────────────────────────────────────────

TENANT = "a0000001-care-0000-0000-000000000001"

# Users
ADMIN_ID    = "u0000001-0000-0000-0000-000000000001"
COORD_ID    = "u0000002-0000-0000-0000-000000000002"
NURSE_ID    = "u0000003-0000-0000-0000-000000000003"
BILLING_ID  = "u0000004-0000-0000-0000-000000000004"
COMPLY_ID   = "u0000005-0000-0000-0000-000000000005"

# Participants
P1 = "p0000001-0000-0000-0000-000000000001"
P2 = "p0000002-0000-0000-0000-000000000002"
P3 = "p0000003-0000-0000-0000-000000000003"
P4 = "p0000004-0000-0000-0000-000000000004"  # discharged

# Attendance
A1 = "a0000001-0000-0000-0000-000000000001"
A2 = "a0000002-0000-0000-0000-000000000002"
A3 = "a0000003-0000-0000-0000-000000000003"
A4 = "a0000004-0000-0000-0000-000000000004"
A5 = "a0000005-0000-0000-0000-000000000005"
A6 = "a0000006-0000-0000-0000-000000000006"

# Claims
C1 = "c0000001-0000-0000-0000-000000000001"
C2 = "c0000002-0000-0000-0000-000000000002"
C3 = "c0000003-0000-0000-0000-000000000003"

# MAR records
M1 = "m0000001-0000-0000-0000-000000000001"
M2 = "m0000002-0000-0000-0000-000000000002"
M3 = "m0000003-0000-0000-0000-000000000003"
M4 = "m0000004-0000-0000-0000-000000000004"
M5 = "m0000005-0000-0000-0000-000000000005"
M6 = "m0000006-0000-0000-0000-000000000006"

# Incidents
I1 = "i0000001-0000-0000-0000-000000000001"
I2 = "i0000002-0000-0000-0000-000000000002"
I3 = "i0000003-0000-0000-0000-000000000003"
I4 = "i0000004-0000-0000-0000-000000000004"

NOW = datetime.utcnow()
TODAY = date.today()


def _days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def _dt(d: date, h: int, m: int) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, 0)


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Wipe all tables in dependency-safe order
        db.query(Incident).delete()
        db.query(MARRecord).delete()
        db.query(Claim).delete()
        db.query(Attendance).delete()
        db.query(Participant).delete()
        db.query(User).delete()
        db.commit()

        # ── Users ──────────────────────────────────────────────────────────────
        users = [
            User(
                user_id=ADMIN_ID, tenant_id=TENANT,
                first_name="Sandra", last_name="Holloway",
                email="s.holloway@careartdemo.local",
                role="program_administrator", is_external=False,
                password_hash="mock_hash_admin", mfa_enabled=True,
                status="active", failed_login_count=0,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
            User(
                user_id=COORD_ID, tenant_id=TENANT,
                first_name="Marcus", last_name="Delgado",
                email="m.delgado@careartdemo.local",
                role="care_coordinator", is_external=False,
                password_hash="mock_hash_coord", mfa_enabled=True,
                status="active", failed_login_count=0,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
            User(
                user_id=NURSE_ID, tenant_id=TENANT,
                first_name="Priya", last_name="Nair",
                email="p.nair@careartdemo.local",
                role="nurse_medication_aide", is_external=False,
                password_hash="mock_hash_nurse", mfa_enabled=True,
                status="active", failed_login_count=0,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
            User(
                user_id=BILLING_ID, tenant_id=TENANT,
                first_name="Jerome", last_name="Okafor",
                email="j.okafor@careartdemo.local",
                role="billing_specialist", is_external=False,
                password_hash="mock_hash_billing", mfa_enabled=True,
                status="active", failed_login_count=0,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
            User(
                user_id=COMPLY_ID, tenant_id=TENANT,
                first_name="Renata", last_name="Volkov",
                email="r.volkov@careartdemo.local",
                role="compliance_officer", is_external=False,
                password_hash="mock_hash_comply", mfa_enabled=True,
                status="active", failed_login_count=0,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
        ]
        db.add_all(users)
        db.commit()
        print(f"  Users:        {len(users)}")

        # ── Participants ───────────────────────────────────────────────────────
        participants = [
            Participant(
                participant_id=P1, tenant_id=TENANT,
                first_name="Eleanor", last_name="Vasquez",
                date_of_birth=date(1942, 3, 14),
                gender="female", race="Hispanic or Latino", ethnicity="Mexican",
                preferred_language="Spanish",
                ssn_last4="4821",
                medicaid_id="MC-00001", medicare_id=None,
                primary_payer_id="payer-medicaid-ny",
                primary_policy_number="POL-00001",
                address_line_1="84 Maple Street", city="Albany", state="NY", zip_code="12202",
                phone_primary="5183310001",
                emergency_contact_name="Carlos Vasquez", emergency_contact_relationship="son",
                emergency_contact_phone="5183310002",
                primary_diagnosis_code="E11.9",
                secondary_diagnosis_codes=["I10", "E78.5"],
                is_sud_record=False,
                functional_level="assisted", mobility_status="ambulatory",
                attending_physician_id="phys-001",
                enrollment_date=date(2024, 1, 15),
                program_status="active", authorized_units_per_week=20,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1, is_deleted=False,
            ),
            Participant(
                participant_id=P2, tenant_id=TENANT,
                first_name="Robert", last_name="Kimura",
                date_of_birth=date(1938, 11, 28),
                gender="male", race="Asian", ethnicity="Japanese",
                preferred_language="English",
                ssn_last4="7743",
                medicaid_id="MC-00002", medicare_id="1EG4-TE5-MK72",
                primary_payer_id="payer-medicare",
                primary_policy_number="POL-00002",
                address_line_1="201 Elm Avenue", city="Albany", state="NY", zip_code="12206",
                phone_primary="5183310003",
                emergency_contact_name="Diane Kimura", emergency_contact_relationship="spouse",
                emergency_contact_phone="5183310004",
                primary_diagnosis_code="G30.9",
                secondary_diagnosis_codes=["I10", "M17.11"],
                is_sud_record=False,
                functional_level="supervised", mobility_status="wheelchair",
                attending_physician_id="phys-001",
                enrollment_date=date(2023, 9, 1),
                program_status="active", authorized_units_per_week=20,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1, is_deleted=False,
            ),
            Participant(
                participant_id=P3, tenant_id=TENANT,
                first_name="Dorothy", last_name="Franklin",
                date_of_birth=date(1950, 6, 5),
                gender="female", race="Black or African American", ethnicity="Not Hispanic",
                preferred_language="English",
                ssn_last4="3390",
                medicaid_id="MC-00003", medicare_id=None,
                primary_payer_id="payer-medicaid-ny",
                primary_policy_number="POL-00003",
                address_line_1="17 Pine Road", city="Troy", state="NY", zip_code="12180",
                phone_primary="5183310005",
                emergency_contact_name="James Franklin", emergency_contact_relationship="son",
                emergency_contact_phone="5183310006",
                primary_diagnosis_code="F32.1",
                secondary_diagnosis_codes=["E11.9"],
                is_sud_record=True,
                functional_level="independent", mobility_status="ambulatory",
                attending_physician_id="phys-002",
                enrollment_date=date(2024, 3, 10),
                program_status="active", authorized_units_per_week=15,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1, is_deleted=False,
            ),
            Participant(
                participant_id=P4, tenant_id=TENANT,
                first_name="Harold", last_name="Nguyen",
                date_of_birth=date(1945, 9, 20),
                gender="male", race="Asian", ethnicity="Vietnamese",
                preferred_language="Vietnamese",
                ssn_last4="6612",
                medicaid_id="MC-00004", medicare_id=None,
                primary_payer_id="payer-medicaid-ny",
                primary_policy_number="POL-00004",
                address_line_1="55 Oak Lane", city="Schenectady", state="NY", zip_code="12305",
                phone_primary="5183310007",
                emergency_contact_name="Lily Nguyen", emergency_contact_relationship="daughter",
                emergency_contact_phone="5183310008",
                primary_diagnosis_code="I50.9",
                secondary_diagnosis_codes=["E11.9", "N18.3"],
                is_sud_record=False,
                functional_level="dependent", mobility_status="bedridden",
                enrollment_date=date(2023, 5, 1),
                discharge_date=_days_ago(30),
                program_status="discharged",
                discharge_reason="Participant transferred to skilled nursing facility.",
                authorized_units_per_week=20,
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1, is_deleted=False,
            ),
        ]
        db.add_all(participants)
        db.commit()
        print(f"  Participants: {len(participants)}")

        # ── Attendance (all confirmed for claim eligibility) ───────────────────
        dos1 = _days_ago(10)
        dos2 = _days_ago(9)
        dos3 = _days_ago(8)

        attendance = [
            Attendance(
                attendance_id=A1, tenant_id=TENANT, participant_id=P1,
                date_of_service=dos1,
                sign_in_time=time(8, 30), sign_out_time=time(14, 30), total_hours=6.0,
                service_type_code="T2021",
                authorized_units_consumed=24.0, authorized_units_remaining=56.0,
                recorded_by=ADMIN_ID, status="confirmed",
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
            Attendance(
                attendance_id=A2, tenant_id=TENANT, participant_id=P1,
                date_of_service=dos2,
                sign_in_time=time(8, 45), sign_out_time=time(15, 0), total_hours=6.25,
                service_type_code="T2021",
                authorized_units_consumed=25.0, authorized_units_remaining=31.0,
                recorded_by=ADMIN_ID, status="confirmed",
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
            Attendance(
                attendance_id=A3, tenant_id=TENANT, participant_id=P2,
                date_of_service=dos1,
                sign_in_time=time(9, 0), sign_out_time=time(15, 0), total_hours=6.0,
                service_type_code="S5100",
                authorized_units_consumed=1.0, authorized_units_remaining=19.0,
                recorded_by=ADMIN_ID, status="confirmed",
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
            Attendance(
                attendance_id=A4, tenant_id=TENANT, participant_id=P2,
                date_of_service=dos2,
                sign_in_time=time(9, 0), sign_out_time=time(14, 30), total_hours=5.5,
                service_type_code="S5100",
                authorized_units_consumed=1.0, authorized_units_remaining=18.0,
                recorded_by=ADMIN_ID, status="confirmed",
                created_at=NOW, updated_at=NOW, created_by=ADMIN_ID, version=1,
            ),
            Attendance(
                attendance_id=A5, tenant_id=TENANT, participant_id=P3,
                date_of_service=dos2,
                sign_in_time=time(8, 0), sign_out_time=time(13, 0), total_hours=5.0,
                service_type_code="T2021",
                authorized_units_consumed=20.0, authorized_units_remaining=40.0,
                recorded_by=COORD_ID, status="confirmed",
                created_at=NOW, updated_at=NOW, created_by=COORD_ID, version=1,
            ),
            Attendance(
                attendance_id=A6, tenant_id=TENANT, participant_id=P3,
                date_of_service=dos3,
                sign_in_time=time(8, 0), sign_out_time=time(13, 0), total_hours=5.0,
                service_type_code="T2021",
                authorized_units_consumed=20.0, authorized_units_remaining=20.0,
                recorded_by=COORD_ID, status="pending",  # not confirmed — for testing
                created_at=NOW, updated_at=NOW, created_by=COORD_ID, version=1,
            ),
        ]
        db.add_all(attendance)
        db.commit()
        print(f"  Attendance:   {len(attendance)}")

        # ── Claims ────────────────────────────────────────────────────────────
        claims = [
            Claim(
                claim_id=C1, tenant_id=TENANT, participant_id=P1,
                attendance_ids=[A1, A2],
                payer_type="medicaid",
                claim_reference_number="MCD-20260510-SEED001",
                procedure_code="T2021",
                date_of_service_start=dos2,
                date_of_service_end=dos1,
                units_billed=49.0, amount=196.0,
                claim_status="submitted",
                submission_date=_dt(TODAY, 9, 0),
                created_by=BILLING_ID,
                created_at=NOW, updated_at=NOW, version=1,
            ),
            Claim(
                claim_id=C2, tenant_id=TENANT, participant_id=P2,
                attendance_ids=[A3, A4],
                payer_type="medicare",
                claim_reference_number="MCR-20260510-SEED002",
                procedure_code="S5100",
                date_of_service_start=dos2,
                date_of_service_end=dos1,
                units_billed=2.0, amount=280.0,
                claim_status="paid",
                submission_date=_dt(TODAY - timedelta(days=5), 10, 0),
                remittance_date=_dt(TODAY - timedelta(days=2), 14, 0),
                created_by=BILLING_ID,
                created_at=NOW, updated_at=NOW, version=1,
            ),
            Claim(
                claim_id=C3, tenant_id=TENANT, participant_id=P1,
                attendance_ids=[A1],
                payer_type="medicaid",
                claim_reference_number="MCD-20260510-SEED003",
                procedure_code="T2021",
                date_of_service_start=dos1,
                date_of_service_end=None,
                units_billed=24.0, amount=96.0,
                claim_status="draft",
                created_by=BILLING_ID,
                created_at=NOW, updated_at=NOW, version=1,
            ),
        ]
        db.add_all(claims)
        db.commit()
        print(f"  Claims:       {len(claims)}")

        # ── MAR Records ───────────────────────────────────────────────────────
        base_day = _dt(TODAY - timedelta(days=3), 8, 0)

        mar_records = [
            MARRecord(
                mar_id=M1, tenant_id=TENANT, participant_id=P1,
                medication_name="Metformin 500mg",
                dose="1 tablet", route="oral",
                scheduled_time=_dt(_days_ago(3), 8, 0),
                administered_time=_dt(_days_ago(3), 8, 5),
                administered_by=NURSE_ID,
                status="administered",
                is_controlled_substance=False,
                created_at=NOW, updated_at=NOW, created_by=NURSE_ID, version=1,
            ),
            MARRecord(
                mar_id=M2, tenant_id=TENANT, participant_id=P1,
                medication_name="Lisinopril 10mg",
                dose="1 tablet", route="oral",
                scheduled_time=_dt(_days_ago(3), 8, 0),
                administered_time=_dt(_days_ago(3), 8, 6),
                administered_by=NURSE_ID,
                status="administered",
                is_controlled_substance=False,
                created_at=NOW, updated_at=NOW, created_by=NURSE_ID, version=1,
            ),
            MARRecord(
                mar_id=M3, tenant_id=TENANT, participant_id=P1,
                medication_name="Atorvastatin 20mg",
                dose="1 tablet", route="oral",
                scheduled_time=_dt(_days_ago(2), 8, 0),
                administered_time=None,
                administered_by=NURSE_ID,
                status="refused",
                notes="Participant declined medication citing nausea from previous dose.",
                is_controlled_substance=False,
                created_at=NOW, updated_at=NOW, created_by=NURSE_ID, version=1,
            ),
            MARRecord(
                mar_id=M4, tenant_id=TENANT, participant_id=P2,
                medication_name="Donepezil 5mg",
                dose="1 tablet", route="oral",
                scheduled_time=_dt(_days_ago(3), 9, 0),
                administered_time=_dt(_days_ago(3), 9, 10),
                administered_by=NURSE_ID,
                status="administered",
                is_controlled_substance=False,
                created_at=NOW, updated_at=NOW, created_by=NURSE_ID, version=1,
            ),
            MARRecord(
                mar_id=M5, tenant_id=TENANT, participant_id=P3,
                medication_name="Sertraline 50mg",
                dose="1 tablet", route="oral",
                scheduled_time=_dt(_days_ago(3), 8, 30),
                administered_time=_dt(_days_ago(3), 8, 35),
                administered_by=NURSE_ID,
                status="administered",
                is_controlled_substance=False,
                created_at=NOW, updated_at=NOW, created_by=NURSE_ID, version=1,
            ),
            MARRecord(
                mar_id=M6, tenant_id=TENANT, participant_id=P3,
                medication_name="Buprenorphine 8mg",
                dose="1 sublingual tablet", route="oral",
                scheduled_time=_dt(_days_ago(3), 12, 0),
                administered_time=_dt(_days_ago(3), 12, 5),
                administered_by=NURSE_ID,
                status="administered",
                notes="Administered under direct observation per SUD treatment protocol.",
                is_controlled_substance=True,
                created_at=NOW, updated_at=NOW, created_by=NURSE_ID, version=1,
            ),
        ]
        db.add_all(mar_records)
        db.commit()
        print(f"  MAR Records:  {len(mar_records)}")

        # ── Incidents ─────────────────────────────────────────────────────────
        incidents = [
            Incident(
                incident_id=I1, tenant_id=TENANT, participant_id=P1,
                incident_date=_days_ago(5), incident_time=time(10, 15),
                incident_type="fall",
                description="Participant slipped on wet floor near restroom. No visible injury. Vitals stable. Family notified.",
                location="Restroom B hallway",
                reported_by=COORD_ID,
                severity="minor",
                status="submitted",
                is_sud_related=False,
                created_at=NOW, updated_at=NOW, created_by=COORD_ID, version=1,
            ),
            Incident(
                incident_id=I2, tenant_id=TENANT, participant_id=P2,
                incident_date=_days_ago(4), incident_time=time(14, 30),
                incident_type="behavioral",
                description="Participant became agitated during afternoon activity. Required verbal de-escalation. Calmed after 10 minutes. No injury to self or others.",
                location="Day room",
                reported_by=COORD_ID,
                severity="moderate",
                status="submitted",
                is_sud_related=False,
                created_at=NOW, updated_at=NOW, created_by=COORD_ID, version=1,
            ),
            Incident(
                incident_id=I3, tenant_id=TENANT, participant_id=P1,
                incident_date=_days_ago(2), incident_time=time(11, 45),
                incident_type="fall",
                description="Participant fell from chair during lunch. Head strike on table edge. Laceration to forehead requiring bandaging. EMS called. Participant transported to ER.",
                location="Dining room",
                reported_by=COORD_ID,
                severity="severe",
                status="escalated",  # auto-escalated by severity=severe
                regulatory_submission_date=None,
                is_sud_related=False,
                created_at=NOW, updated_at=NOW, created_by=COORD_ID, version=1,
            ),
            Incident(
                incident_id=I4, tenant_id=TENANT, participant_id=P3,
                incident_date=_days_ago(1), incident_time=time(9, 20),
                incident_type="medical_emergency",
                description="Participant unresponsive on arrival. Staff initiated CPR. EMS arrived in 6 minutes. Participant stabilized and transported. Attending physician notified.",
                location="Entry lobby",
                reported_by=NURSE_ID,
                severity="severe",
                status="escalated",  # auto-escalated by both triggers
                regulatory_submission_date=None,
                is_sud_related=True,
                created_at=NOW, updated_at=NOW, created_by=NURSE_ID, version=1,
            ),
        ]
        db.add_all(incidents)
        db.commit()
        print(f"  Incidents:    {len(incidents)}")

    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding Care Art mock database...")
    run()
    print("Done.")
    print(f"\nTenant ID for queries: {TENANT}")
    print(f"Sample participant IDs: {P1}, {P2}, {P3}")
    print(f"Nurse user ID (for MAR administered_by): {NURSE_ID}")
