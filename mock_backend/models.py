import uuid
from datetime import date, datetime, time
from enum import Enum as PyEnum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    event,
    text,
)

from database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────



class GenderEnum(str, PyEnum):
    male = "male"
    female = "female"
    non_binary = "non_binary"
    unknown = "unknown"

class FunctionalLevelEnum(str, PyEnum):
    independent = "independent"
    supervised = "supervised"
    assisted = "assisted"
    dependent = "dependent"

class MobilityStatusEnum(str, PyEnum):
    ambulatory = "ambulatory"
    wheelchair = "wheelchair"
    bedridden = "bedridden"
    other = "other"

class ProgramStatusEnum(str, PyEnum):
    active = "active"
    on_leave = "on_leave"
    discharged = "discharged"
    deceased = "deceased"

class UserRoleEnum(str, PyEnum):
    program_administrator = "program_administrator"
    care_coordinator = "care_coordinator"
    nurse_medication_aide = "nurse_medication_aide"
    billing_specialist = "billing_specialist"
    physician = "physician"
    participant_family = "participant_family"
    compliance_officer = "compliance_officer"

class UserStatusEnum(str, PyEnum):
    active = "active"
    inactive = "inactive"
    suspended = "suspended"
    pending_activation = "pending_activation"

class AttendanceStatusEnum(str, PyEnum):
    pending = "pending"
    confirmed = "confirmed"
    billed = "billed"
    voided = "voided"

class PayerTypeEnum(str, PyEnum):
    medicaid = "medicaid"
    medicare = "medicare"

class ClaimStatusEnum(str, PyEnum):
    draft = "draft"
    submitted = "submitted"
    accepted = "accepted"
    rejected = "rejected"
    paid = "paid"

class MARRouteEnum(str, PyEnum):
    oral = "oral"
    injection = "injection"
    topical = "topical"

class MARStatusEnum(str, PyEnum):
    administered = "administered"
    refused = "refused"
    held = "held"
    missed = "missed"

class IncidentTypeEnum(str, PyEnum):
    fall = "fall"
    medication_error = "medication_error"
    behavioral = "behavioral"
    medical_emergency = "medical_emergency"
    other = "other"
    addendum = "addendum"

class SeverityEnum(str, PyEnum):
    minor = "minor"
    moderate = "moderate"
    severe = "severe"

class IncidentStatusEnum(str, PyEnum):
    draft = "draft"
    submitted = "submitted"
    escalated = "escalated"
    closed = "closed"


# ─── Phase 2 Enums ─────────────────────────────────────────────────────────────


class CarePlanStatusEnum(str, PyEnum):
    draft = "draft"
    active = "active"
    superseded = "superseded"
    archived = "archived"


class CarePlanGoalDomainEnum(str, PyEnum):
    functional = "functional"
    clinical = "clinical"
    social = "social"
    behavioral = "behavioral"


class CarePlanGoalStatusEnum(str, PyEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    achieved = "achieved"
    discontinued = "discontinued"


class AppointmentTypeEnum(str, PyEnum):
    routine = "routine"
    specialist_referral = "specialist_referral"
    urgent = "urgent"
    telehealth = "telehealth"


class AppointmentStatusEnum(str, PyEnum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class RefillRouteEnum(str, PyEnum):
    oral = "oral"
    injection = "injection"
    topical = "topical"


class RefillStatusEnum(str, PyEnum):
    requested = "requested"
    sent_to_pharmacy = "sent_to_pharmacy"
    processing = "processing"
    fulfilled = "fulfilled"
    denied = "denied"
    cancelled = "cancelled"


class ReminderTypeEnum(str, PyEnum):
    appointment = "appointment"
    transport = "transport"
    general = "general"


class ReminderReferenceEntityEnum(str, PyEnum):
    appointment = "appointment"
    none = "none"


class ReminderStatusEnum(str, PyEnum):
    scheduled = "scheduled"
    sent = "sent"
    delivered = "delivered"
    failed = "failed"
    cancelled = "cancelled"


class ReminderChannelEnum(str, PyEnum):
    push = "push"


class PushProviderEnum(str, PyEnum):
    apns = "apns"
    fcm = "fcm"


class ConsentRecipientTypeEnum(str, PyEnum):
    ehr = "ehr"
    pharmacy = "pharmacy"
    push_notification = "push_notification"


class ConsentStatusEnum(str, PyEnum):
    active = "active"
    withdrawn = "withdrawn"
    expired = "expired"


class ConsentMethodEnum(str, PyEnum):
    written = "written"
    electronic = "electronic"


# ─── SQLAlchemy ORM Models ─────────────────────────────────────────────────────



class Participant(Base):
    __tablename__ = "participant"
    __table_args__ = (
        UniqueConstraint("tenant_id", "medicaid_id", name="uq_participant_medicaid_id"),
    )

    participant_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    # Demographics
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    middle_name = Column(String(100))
    preferred_name = Column(String(100))
    date_of_birth = Column(Date, nullable=False)
    gender = Column(String(20))
    race = Column(String(100))
    ethnicity = Column(String(100))
    preferred_language = Column(String(50))
    ssn_encrypted = Column(String(256))
    ssn_last4 = Column(String(4))
    # Insurance & program identifiers
    medicaid_id = Column(String(20))
    medicare_id = Column(String(20))
    primary_payer_id = Column(String(36))
    primary_policy_number = Column(String(50))
    secondary_payer_id = Column(String(36))
    secondary_policy_number = Column(String(50))
    npi_attending_physician = Column(String(10))
    # Contact
    address_line_1 = Column(String(200))
    address_line_2 = Column(String(200))
    city = Column(String(100))
    state = Column(String(2))
    zip_code = Column(String(10))
    phone_primary = Column(String(20))
    phone_secondary = Column(String(20))
    email = Column(String(254))
    # Emergency contact
    emergency_contact_name = Column(String(200))
    emergency_contact_relationship = Column(String(50))
    emergency_contact_phone = Column(String(20))
    # Clinical & program
    primary_diagnosis_code = Column(String(10))
    secondary_diagnosis_codes = Column(JSON)
    is_sud_record = Column(Boolean, default=False, nullable=False)
    functional_level = Column(String(20))
    mobility_status = Column(String(20))
    attending_physician_id = Column(String(36))
    # Enrollment
    enrollment_date = Column(Date)
    discharge_date = Column(Date)
    program_status = Column(String(20), default="active", nullable=False)
    authorized_units_per_week = Column(Integer)
    discharge_reason = Column(String(500))
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_email_tenant"),
    )

    user_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(254), nullable=False)
    phone = Column(String(20))
    role = Column(String(50), nullable=False)
    is_external = Column(Boolean, default=False, nullable=False)
    password_hash = Column(String(256))
    mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_secret_encrypted = Column(String(512))
    failed_login_count = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime)
    password_changed_at = Column(DateTime)
    status = Column(String(30), default="active", nullable=False)
    deactivated_at = Column(DateTime)
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "participant_id", "date_of_service",
            name="uq_attendance_participant_date",
        ),
    )

    attendance_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    date_of_service = Column(Date, nullable=False)
    sign_in_time = Column(Time)
    sign_out_time = Column(Time)
    total_hours = Column(Numeric(4, 2))
    service_type_code = Column(String(10))
    authorized_units_consumed = Column(Numeric(6, 2))
    authorized_units_remaining = Column(Numeric(6, 2))
    recorded_by = Column(String(36))
    status = Column(String(20), default="pending", nullable=False)
    void_reason = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


class Claim(Base):
    __tablename__ = "claim"
    __table_args__ = (
        UniqueConstraint("claim_reference_number", name="uq_claim_reference_number"),
        UniqueConstraint(
            "tenant_id", "participant_id", "date_of_service_start",
            "procedure_code", "payer_type",
            name="uq_claim_participant_dos_procedure_payer",
        ),
    )

    claim_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    attendance_ids = Column(JSON, nullable=False)
    payer_type = Column(String(20), nullable=False)
    claim_reference_number = Column(String(50), nullable=False)
    procedure_code = Column(String(10), nullable=False)
    date_of_service_start = Column(Date, nullable=False)
    date_of_service_end = Column(Date)
    units_billed = Column(Numeric(6, 2))
    amount = Column(Numeric(10, 2))
    claim_status = Column(String(20), default="draft", nullable=False)
    submission_date = Column(DateTime)
    remittance_date = Column(DateTime)
    rejection_reason = Column(String(1000))
    created_by = Column(String(36))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


class MARRecord(Base):
    __tablename__ = "mar_record"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "participant_id", "medication_name", "scheduled_time",
            name="uq_mar_participant_medication_scheduled_time",
        ),
    )

    mar_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    medication_name = Column(String(200), nullable=False)
    dose = Column(String(100))
    route = Column(String(20))
    scheduled_time = Column(DateTime, nullable=False)
    administered_time = Column(DateTime)
    administered_by = Column(String(36), nullable=False)
    status = Column(String(20), default="administered", nullable=False)
    notes = Column(String(1000))
    is_controlled_substance = Column(Boolean, default=False, nullable=False)
    is_correction = Column(Boolean, default=False, nullable=False)
    original_mar_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


class Incident(Base):
    __tablename__ = "incident"
    # No composite unique constraint — PK only (see Section 3.6.7)

    incident_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    incident_date = Column(Date, nullable=False)
    incident_time = Column(Time)
    incident_type = Column(String(30), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(200))
    reported_by = Column(String(36))
    severity = Column(String(20), nullable=False)
    status = Column(String(20), default="draft", nullable=False)
    regulatory_submission_date = Column(Date)
    is_sud_related = Column(Boolean, default=False, nullable=False)
    original_incident_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


# ─── Phase 2 ORM Models ────────────────────────────────────────────────────────


class CarePlan(Base):
    __tablename__ = "care_plan"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "participant_id", "version_number",
            name="uq_care_plan_participant_version",
        ),
    )

    care_plan_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    status = Column(String(20), default="draft", nullable=False)
    effective_date = Column(Date)
    review_date = Column(Date)
    expiration_date = Column(Date)
    primary_diagnosis_code = Column(String(10))
    secondary_diagnosis_codes = Column(JSON)
    functional_level = Column(String(20))
    notes = Column(Text)
    physician_id = Column(String(36))
    physician_signature_date = Column(Date)
    physician_order_reference = Column(String(100))
    fhir_care_plan_id = Column(String(100))
    care_coordinator_id = Column(String(36))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


class CarePlanGoal(Base):
    __tablename__ = "care_plan_goal"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "care_plan_id", "domain", "description",
            name="uq_care_plan_goal_domain_description",
        ),
    )

    goal_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    care_plan_id = Column(String(36), ForeignKey("care_plan.care_plan_id"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    domain = Column(String(20), nullable=False)
    description = Column(Text, nullable=False)
    target_metric = Column(Text)
    target_date = Column(Date)
    status = Column(String(20), default="not_started", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)


class Appointment(Base):
    __tablename__ = "appointment"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "participant_id", "physician_id", "scheduled_start",
            name="uq_appointment_participant_physician_scheduled_start",
        ),
    )

    appointment_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    physician_id = Column(String(36), nullable=False, index=True)
    scheduled_start = Column(DateTime, nullable=False)
    scheduled_end = Column(DateTime, nullable=False)
    appointment_type = Column(String(30), nullable=False)
    status = Column(String(20), default="scheduled", nullable=False)
    cancellation_reason = Column(String(500))
    result_notes = Column(Text)
    fhir_result_reference = Column(String(100))
    follow_up_required = Column(Boolean)
    fhir_appointment_id = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


# ─── Appointment physician-overlap triggers (Section 3.9.8) ────────────────────
# Created as DDL events on the appointment table so they are installed whenever the
# table is created — both via the app lifespan and via the test-suite create_all.

_trg_appointment_overlap_insert = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_appointment_physician_no_overlap_insert
    BEFORE INSERT ON appointment
    FOR EACH ROW
    BEGIN
      SELECT RAISE(ABORT, 'overlapping appointment for this physician')
      WHERE EXISTS (
        SELECT 1 FROM appointment
        WHERE tenant_id    = NEW.tenant_id
          AND physician_id = NEW.physician_id
          AND status NOT IN ('cancelled', 'no_show')
          AND scheduled_start < NEW.scheduled_end
          AND scheduled_end   > NEW.scheduled_start
      );
    END;
    """
)

_trg_appointment_overlap_update = DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_appointment_physician_no_overlap_update
    BEFORE UPDATE ON appointment
    FOR EACH ROW
    BEGIN
      SELECT RAISE(ABORT, 'overlapping appointment for this physician')
      WHERE EXISTS (
        SELECT 1 FROM appointment
        WHERE tenant_id      = NEW.tenant_id
          AND physician_id   = NEW.physician_id
          AND status NOT IN ('cancelled', 'no_show')
          AND scheduled_start < NEW.scheduled_end
          AND scheduled_end   > NEW.scheduled_start
          AND appointment_id != NEW.appointment_id
      );
    END;
    """
)

event.listen(
    Appointment.__table__, "after_create",
    _trg_appointment_overlap_insert.execute_if(dialect="sqlite"),
)
event.listen(
    Appointment.__table__, "after_create",
    _trg_appointment_overlap_update.execute_if(dialect="sqlite"),
)


class MedicationRefill(Base):
    __tablename__ = "medication_refill"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "participant_id", "medication_name", "requested_at",
            name="uq_refill_participant_medication_requested_at",
        ),
    )

    refill_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    medication_name = Column(String(200), nullable=False)
    dose = Column(String(100))
    route = Column(String(20))
    quantity_requested = Column(Integer, nullable=False)
    refills_requested = Column(SmallInteger)
    prescribing_physician_id = Column(String(36), nullable=False)
    is_controlled_substance = Column(Boolean, default=False, nullable=False)
    status = Column(String(20), default="requested", nullable=False)
    denial_reason = Column(String(500))
    cancellation_reason = Column(String(500))
    requested_at = Column(DateTime, nullable=False)
    fulfilled_at = Column(DateTime)
    pharmacy_id = Column(String(100))
    fhir_medication_request_id = Column(String(100))
    ncpdp_script_reference = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


class Reminder(Base):
    __tablename__ = "reminder"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "participant_id", "reminder_type", "scheduled_for",
            name="uq_reminder_participant_type_scheduled_for",
        ),
    )

    reminder_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    reminder_type = Column(String(20), nullable=False)
    title = Column(String(100), nullable=False)
    body = Column(String(500), nullable=False)
    deep_link_path = Column(String(500))
    reference_entity_type = Column(String(20))
    reference_entity_id = Column(String(36))
    status = Column(String(20), default="scheduled", nullable=False)
    channel = Column(String(20), default="push", nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    sent_at = Column(DateTime)
    delivered_at = Column(DateTime)
    failure_reason = Column(String(500))
    cancellation_reason = Column(String(500))
    push_provider = Column(String(20))
    device_push_token = Column(String(500))
    provider_message_id = Column(String(200))
    recipient_user_id = Column(String(36))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


class Consent(Base):
    __tablename__ = "consent"
    # Active-uniqueness is a partial index (WHERE status='active') enforced at the
    # application layer; SQLite partial unique index not declared as a table-level
    # constraint to mirror the Phase 1 application-layer pattern.

    consent_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), nullable=False, index=True)
    participant_id = Column(String(36), nullable=False, index=True)
    disclosure_recipient_type = Column(String(30), nullable=False)
    disclosure_recipient_name = Column(String(200), nullable=False)
    disclosure_purpose = Column(String(500), nullable=False)
    scope_description = Column(String(1000), nullable=False)
    status = Column(String(20), default="active", nullable=False)
    effective_date = Column(Date, nullable=False)
    expiration_date = Column(Date, nullable=False)
    withdrawn_at = Column(DateTime)
    withdrawal_reason = Column(String(500))
    consent_form_reference = Column(String(200), nullable=False)
    consent_method = Column(String(20), nullable=False)
    participant_signature_date = Column(Date, nullable=False)
    witnessed_by_user_id = Column(String(36))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, server_default=text("0"), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    audit_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    user_id = Column(String(36), nullable=False)
    tenant_id = Column(String(36), nullable=False)
    session_id = Column(String(100), nullable=False)
    action_type = Column(String(30), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(36), nullable=False)
    data_affected = Column(JSON, nullable=False)
    source_ip = Column(String(45), nullable=False)
    outcome = Column(String(20), nullable=False)
    layer = Column(String(30), nullable=False)
    retention_years = Column(Integer, nullable=False, default=6)


# ─── Pydantic Schemas ──────────────────────────────────────────────────────────

class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Participant ──────────────────────────────────────────────────────────────────

class ParticipantCreate(BaseModel):
    tenant_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    middle_name: Optional[str] = None
    preferred_name: Optional[str] = None
    gender: Optional[GenderEnum] = None
    race: Optional[str] = None
    ethnicity: Optional[str] = None
    preferred_language: Optional[str] = None
    ssn_encrypted: Optional[str] = None
    ssn_last4: Optional[str] = None
    medicaid_id: Optional[str] = None
    medicare_id: Optional[str] = None
    primary_payer_id: Optional[str] = None
    primary_policy_number: Optional[str] = None
    secondary_payer_id: Optional[str] = None
    secondary_policy_number: Optional[str] = None
    npi_attending_physician: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    email: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    primary_diagnosis_code: Optional[str] = None
    secondary_diagnosis_codes: Optional[List[str]] = None
    is_sud_record: bool = False
    functional_level: Optional[FunctionalLevelEnum] = None
    mobility_status: Optional[MobilityStatusEnum] = None
    attending_physician_id: Optional[str] = None
    enrollment_date: Optional[date] = None
    discharge_date: Optional[date] = None
    program_status: ProgramStatusEnum = ProgramStatusEnum.active
    authorized_units_per_week: Optional[int] = None
    discharge_reason: Optional[str] = None
    created_by: Optional[str] = None


class ParticipantResponse(_ORM):
    participant_id: str
    tenant_id: str
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    preferred_name: Optional[str] = None
    date_of_birth: date
    gender: Optional[str] = None
    race: Optional[str] = None
    ethnicity: Optional[str] = None
    preferred_language: Optional[str] = None
    ssn_encrypted: Optional[str] = None
    ssn_last4: Optional[str] = None
    medicaid_id: Optional[str] = None
    medicare_id: Optional[str] = None
    primary_payer_id: Optional[str] = None
    primary_policy_number: Optional[str] = None
    secondary_payer_id: Optional[str] = None
    secondary_policy_number: Optional[str] = None
    npi_attending_physician: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    email: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    primary_diagnosis_code: Optional[str] = None
    secondary_diagnosis_codes: Optional[List[str]] = None
    is_sud_record: bool
    functional_level: Optional[str] = None
    mobility_status: Optional[str] = None
    attending_physician_id: Optional[str] = None
    enrollment_date: Optional[date] = None
    discharge_date: Optional[date] = None
    program_status: str
    authorized_units_per_week: Optional[int] = None
    discharge_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# User ─────────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    tenant_id: str
    first_name: str
    last_name: str
    email: str
    role: UserRoleEnum
    phone: Optional[str] = None
    is_external: bool = False
    password_hash: Optional[str] = None
    mfa_enabled: bool = False
    status: UserStatusEnum = UserStatusEnum.active
    created_by: Optional[str] = None


class UserResponse(_ORM):
    user_id: str
    tenant_id: str
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    role: str
    is_external: bool
    password_hash: Optional[str] = None
    mfa_enabled: bool
    mfa_secret_encrypted: Optional[str] = None
    failed_login_count: int
    locked_until: Optional[datetime] = None
    password_changed_at: Optional[datetime] = None
    status: str
    deactivated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int


# Attendance ───────────────────────────────────────────────────────────────────

class AttendanceCreate(BaseModel):
    tenant_id: str
    participant_id: str
    date_of_service: date
    sign_in_time: Optional[time] = None
    sign_out_time: Optional[time] = None
    total_hours: Optional[float] = None
    service_type_code: Optional[str] = None
    authorized_units_consumed: Optional[float] = None
    authorized_units_remaining: Optional[float] = None
    recorded_by: Optional[str] = None
    status: AttendanceStatusEnum = AttendanceStatusEnum.pending
    void_reason: Optional[str] = None
    created_by: Optional[str] = None


class AttendanceResponse(_ORM):
    attendance_id: str
    tenant_id: str
    participant_id: str
    date_of_service: date
    sign_in_time: Optional[Any] = None
    sign_out_time: Optional[Any] = None
    total_hours: Optional[float] = None
    service_type_code: Optional[str] = None
    authorized_units_consumed: Optional[float] = None
    authorized_units_remaining: Optional[float] = None
    recorded_by: Optional[str] = None
    status: str
    void_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# Claim ────────────────────────────────────────────────────────────────────────

class ClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    participant_id: str
    attendance_ids: List[str]
    payer_type: PayerTypeEnum
    procedure_code: str
    date_of_service_start: date
    date_of_service_end: Optional[date] = None
    units_billed: Optional[float] = None
    amount: Optional[float] = None
    claim_status: ClaimStatusEnum = ClaimStatusEnum.draft
    created_by: Optional[str] = None


class ClaimResponse(_ORM):
    claim_id: str
    tenant_id: str
    participant_id: str
    attendance_ids: List[str]
    payer_type: str
    claim_reference_number: str
    procedure_code: str
    date_of_service_start: date
    date_of_service_end: Optional[date] = None
    units_billed: Optional[float] = None
    amount: Optional[float] = None
    claim_status: str
    submission_date: Optional[datetime] = None
    remittance_date: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# MARRecord ────────────────────────────────────────────────────────────────────

class MARRecordCreate(BaseModel):
    tenant_id: str
    participant_id: str
    medication_name: str
    administered_by: str
    scheduled_time: datetime
    dose: Optional[str] = None
    route: Optional[MARRouteEnum] = None
    administered_time: Optional[datetime] = None
    status: MARStatusEnum = MARStatusEnum.administered
    notes: Optional[str] = None
    is_controlled_substance: bool = False
    is_correction: bool = False
    original_mar_id: Optional[str] = None
    created_by: Optional[str] = None


class MARRecordResponse(_ORM):
    mar_id: str
    tenant_id: str
    participant_id: str
    medication_name: str
    dose: Optional[str] = None
    route: Optional[str] = None
    scheduled_time: datetime
    administered_time: Optional[datetime] = None
    administered_by: str
    status: str
    notes: Optional[str] = None
    is_controlled_substance: bool
    is_correction: bool
    original_mar_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# Incident ─────────────────────────────────────────────────────────────────────

class IncidentCreate(BaseModel):
    tenant_id: str
    participant_id: str
    incident_date: date
    incident_type: IncidentTypeEnum
    description: str
    severity: SeverityEnum
    incident_time: Optional[time] = None
    location: Optional[str] = None
    reported_by: Optional[str] = None
    status: IncidentStatusEnum = IncidentStatusEnum.draft
    regulatory_submission_date: Optional[date] = None
    is_sud_related: bool = False
    original_incident_id: Optional[str] = None
    created_by: Optional[str] = None


class IncidentResponse(_ORM):
    incident_id: str
    tenant_id: str
    participant_id: str
    incident_date: date
    incident_time: Optional[Any] = None
    incident_type: str
    description: str
    location: Optional[str] = None
    reported_by: Optional[str] = None
    severity: str
    status: str
    regulatory_submission_date: Optional[date] = None
    is_sud_related: bool
    original_incident_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# ─── PATCH request bodies ─────────────────────────────────────────────────────

class ParticipantPatch(BaseModel):
    version: int
    program_status: Optional[ProgramStatusEnum] = None
    enrollment_date: Optional[date] = None
    discharge_date: Optional[date] = None
    discharge_reason: Optional[str] = None
    authorized_units_per_week: Optional[int] = None
    functional_level: Optional[FunctionalLevelEnum] = None
    mobility_status: Optional[MobilityStatusEnum] = None
    attending_physician_id: Optional[str] = None
    is_deleted: Optional[bool] = None
    updated_by: Optional[str] = None


class UserPatch(BaseModel):
    version: int
    status: Optional[UserStatusEnum] = None
    role: Optional[UserRoleEnum] = None
    mfa_enabled: Optional[bool] = None
    phone: Optional[str] = None
    updated_by: Optional[str] = None


class AttendancePatch(BaseModel):
    version: int
    status: Optional[AttendanceStatusEnum] = None
    sign_in_time: Optional[time] = None
    sign_out_time: Optional[time] = None
    total_hours: Optional[float] = None
    authorized_units_consumed: Optional[float] = None
    void_reason: Optional[str] = None
    updated_by: Optional[str] = None


class ClaimPatch(BaseModel):
    version: int
    claim_status: Optional[ClaimStatusEnum] = None
    submission_date: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    updated_by: Optional[str] = None


class MARRecordPatch(BaseModel):
    version: int
    status: Optional[MARStatusEnum] = None
    administered_time: Optional[datetime] = None
    notes: Optional[str] = None
    updated_by: Optional[str] = None


class IncidentPatch(BaseModel):
    version: int
    status: Optional[IncidentStatusEnum] = None
    description: Optional[str] = None
    location: Optional[str] = None
    severity: Optional[SeverityEnum] = None
    regulatory_submission_date: Optional[date] = None
    updated_by: Optional[str] = None


# ─── Phase 2 Pydantic Schemas ──────────────────────────────────────────────────

# CarePlan ───────────────────────────────────────────────────────────────────

class CarePlanCreate(BaseModel):
    tenant_id: str
    participant_id: str
    version_number: Optional[int] = None
    effective_date: Optional[date] = None
    review_date: Optional[date] = None
    expiration_date: Optional[date] = None
    primary_diagnosis_code: Optional[str] = None
    secondary_diagnosis_codes: Optional[List[str]] = None
    functional_level: Optional[FunctionalLevelEnum] = None
    notes: Optional[str] = None
    physician_id: Optional[str] = None
    physician_signature_date: Optional[date] = None
    physician_order_reference: Optional[str] = None
    care_coordinator_id: Optional[str] = None
    created_by: Optional[str] = None


class CarePlanPatch(BaseModel):
    version: int
    status: Optional[CarePlanStatusEnum] = None
    effective_date: Optional[date] = None
    review_date: Optional[date] = None
    expiration_date: Optional[date] = None
    primary_diagnosis_code: Optional[str] = None
    secondary_diagnosis_codes: Optional[List[str]] = None
    functional_level: Optional[FunctionalLevelEnum] = None
    notes: Optional[str] = None
    physician_id: Optional[str] = None
    physician_signature_date: Optional[date] = None
    physician_order_reference: Optional[str] = None
    care_coordinator_id: Optional[str] = None
    is_deleted: Optional[bool] = None
    updated_by: Optional[str] = None


class CarePlanResponse(_ORM):
    care_plan_id: str
    tenant_id: str
    participant_id: str
    version_number: int
    status: str
    effective_date: Optional[date] = None
    review_date: Optional[date] = None
    expiration_date: Optional[date] = None
    primary_diagnosis_code: Optional[str] = None
    secondary_diagnosis_codes: Optional[List[str]] = None
    functional_level: Optional[str] = None
    notes: Optional[str] = None
    physician_id: Optional[str] = None
    physician_signature_date: Optional[date] = None
    physician_order_reference: Optional[str] = None
    fhir_care_plan_id: Optional[str] = None
    care_coordinator_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# CarePlanGoal ─────────────────────────────────────────────────────────────────

class CarePlanGoalCreate(BaseModel):
    tenant_id: str
    care_plan_id: str
    domain: CarePlanGoalDomainEnum
    description: str
    target_metric: Optional[str] = None
    target_date: Optional[date] = None
    status: CarePlanGoalStatusEnum = CarePlanGoalStatusEnum.not_started
    created_by: Optional[str] = None


class CarePlanGoalResponse(_ORM):
    goal_id: str
    care_plan_id: str
    tenant_id: str
    domain: str
    description: str
    target_metric: Optional[str] = None
    target_date: Optional[date] = None
    status: str
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int


# Appointment ──────────────────────────────────────────────────────────────────

class AppointmentCreate(BaseModel):
    tenant_id: str
    participant_id: str
    physician_id: str
    scheduled_start: datetime
    scheduled_end: datetime
    appointment_type: AppointmentTypeEnum
    status: AppointmentStatusEnum = AppointmentStatusEnum.scheduled
    cancellation_reason: Optional[str] = None
    result_notes: Optional[str] = None
    fhir_result_reference: Optional[str] = None
    follow_up_required: Optional[bool] = None
    fhir_appointment_id: Optional[str] = None
    created_by: Optional[str] = None


class AppointmentPatch(BaseModel):
    version: int
    status: Optional[AppointmentStatusEnum] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    physician_id: Optional[str] = None
    appointment_type: Optional[AppointmentTypeEnum] = None
    cancellation_reason: Optional[str] = None
    result_notes: Optional[str] = None
    fhir_result_reference: Optional[str] = None
    follow_up_required: Optional[bool] = None
    updated_by: Optional[str] = None


class AppointmentResponse(_ORM):
    appointment_id: str
    tenant_id: str
    participant_id: str
    physician_id: str
    scheduled_start: datetime
    scheduled_end: datetime
    appointment_type: str
    status: str
    cancellation_reason: Optional[str] = None
    result_notes: Optional[str] = None
    fhir_result_reference: Optional[str] = None
    follow_up_required: Optional[bool] = None
    fhir_appointment_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# MedicationRefill ─────────────────────────────────────────────────────────────

class MedicationRefillCreate(BaseModel):
    tenant_id: str
    participant_id: str
    medication_name: str
    prescribing_physician_id: str
    quantity_requested: int
    requested_at: datetime
    dose: Optional[str] = None
    route: Optional[RefillRouteEnum] = None
    refills_requested: Optional[int] = None
    is_controlled_substance: bool = False
    status: RefillStatusEnum = RefillStatusEnum.requested
    denial_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    fulfilled_at: Optional[datetime] = None
    pharmacy_id: Optional[str] = None
    fhir_medication_request_id: Optional[str] = None
    ncpdp_script_reference: Optional[str] = None
    created_by: Optional[str] = None


class MedicationRefillPatch(BaseModel):
    version: int
    status: Optional[RefillStatusEnum] = None
    medication_name: Optional[str] = None
    dose: Optional[str] = None
    route: Optional[RefillRouteEnum] = None
    quantity_requested: Optional[int] = None
    refills_requested: Optional[int] = None
    denial_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    fulfilled_at: Optional[datetime] = None
    pharmacy_id: Optional[str] = None
    fhir_medication_request_id: Optional[str] = None
    ncpdp_script_reference: Optional[str] = None
    updated_by: Optional[str] = None


class MedicationRefillResponse(_ORM):
    refill_id: str
    tenant_id: str
    participant_id: str
    medication_name: str
    dose: Optional[str] = None
    route: Optional[str] = None
    quantity_requested: int
    refills_requested: Optional[int] = None
    prescribing_physician_id: str
    is_controlled_substance: bool
    status: str
    denial_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    requested_at: datetime
    fulfilled_at: Optional[datetime] = None
    pharmacy_id: Optional[str] = None
    fhir_medication_request_id: Optional[str] = None
    ncpdp_script_reference: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# Reminder ─────────────────────────────────────────────────────────────────────

class ReminderCreate(BaseModel):
    tenant_id: str
    participant_id: str
    reminder_type: ReminderTypeEnum
    title: str
    body: str
    scheduled_for: datetime
    deep_link_path: Optional[str] = None
    reference_entity_type: Optional[ReminderReferenceEntityEnum] = None
    reference_entity_id: Optional[str] = None
    status: ReminderStatusEnum = ReminderStatusEnum.scheduled
    channel: ReminderChannelEnum = ReminderChannelEnum.push
    push_provider: Optional[PushProviderEnum] = None
    device_push_token: Optional[str] = None
    recipient_user_id: Optional[str] = None
    created_by: Optional[str] = None


class ReminderPatch(BaseModel):
    version: int
    status: Optional[ReminderStatusEnum] = None
    title: Optional[str] = None
    body: Optional[str] = None
    deep_link_path: Optional[str] = None
    channel: Optional[ReminderChannelEnum] = None
    scheduled_for: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    push_provider: Optional[PushProviderEnum] = None
    device_push_token: Optional[str] = None
    provider_message_id: Optional[str] = None
    updated_by: Optional[str] = None


class ReminderResponse(_ORM):
    reminder_id: str
    tenant_id: str
    participant_id: str
    reminder_type: str
    title: str
    body: str
    deep_link_path: Optional[str] = None
    reference_entity_type: Optional[str] = None
    reference_entity_id: Optional[str] = None
    status: str
    channel: str
    scheduled_for: datetime
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    push_provider: Optional[str] = None
    device_push_token: Optional[str] = None
    provider_message_id: Optional[str] = None
    recipient_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# Consent ──────────────────────────────────────────────────────────────────────

class ConsentCreate(BaseModel):
    tenant_id: str
    participant_id: str
    disclosure_recipient_type: ConsentRecipientTypeEnum
    disclosure_recipient_name: str
    disclosure_purpose: str
    scope_description: str
    effective_date: date
    expiration_date: date
    consent_form_reference: Optional[str] = None
    consent_method: ConsentMethodEnum = ConsentMethodEnum.written
    participant_signature_date: date
    witnessed_by_user_id: Optional[str] = None
    created_by: Optional[str] = None


class ConsentPatch(BaseModel):
    version: int
    status: Optional[ConsentStatusEnum] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    withdrawal_reason: Optional[str] = None
    is_deleted: Optional[bool] = None
    updated_by: Optional[str] = None


class ConsentResponse(_ORM):
    consent_id: str
    tenant_id: str
    participant_id: str
    disclosure_recipient_type: str
    disclosure_recipient_name: str
    disclosure_purpose: str
    scope_description: str
    status: str
    effective_date: date
    expiration_date: date
    withdrawn_at: Optional[datetime] = None
    withdrawal_reason: Optional[str] = None
    consent_form_reference: str
    consent_method: str
    participant_signature_date: date
    witnessed_by_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
    is_deleted: bool


# ─── AuditLog ─────────────────────────────────────────────────────────────────

class AuditLogResponse(_ORM):
    audit_id: str
    timestamp: datetime
    user_id: str
    tenant_id: str
    session_id: str
    action_type: str
    resource_type: str
    resource_id: str
    data_affected: List[str]
    source_ip: str
    outcome: str
    layer: str
    retention_years: int


# ─── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    user_id: str
    password: str


class LoginResponse(BaseModel):
    status: str
    message: str
