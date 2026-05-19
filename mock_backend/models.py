import uuid
from datetime import date, datetime, time
from enum import Enum as PyEnum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
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

class SeverityEnum(str, PyEnum):
    minor = "minor"
    moderate = "moderate"
    severe = "severe"

class IncidentStatusEnum(str, PyEnum):
    draft = "draft"
    submitted = "submitted"
    escalated = "escalated"
    closed = "closed"


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
    is_deleted = Column(Boolean, default=False, nullable=False)


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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)


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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(36))
    updated_by = Column(String(36))
    version = Column(Integer, default=1, nullable=False)


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


# Claim ────────────────────────────────────────────────────────────────────────

class ClaimCreate(BaseModel):
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
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int


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
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    version: int
