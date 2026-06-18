from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from database import Base, engine, get_db
import models
from models import (
    AuditLog, AuditLogResponse,
    Attendance, AttendanceCreate, AttendancePatch, AttendanceResponse,
    Claim, ClaimCreate, ClaimPatch, ClaimResponse,
    Incident, IncidentCreate, IncidentPatch, IncidentResponse,
    LoginRequest, LoginResponse,
    MARRecord, MARRecordCreate, MARRecordPatch, MARRecordResponse,
    Participant, ParticipantCreate, ParticipantPatch, ParticipantResponse,
    User, UserCreate, UserPatch, UserResponse,
    CarePlan, CarePlanCreate, CarePlanPatch, CarePlanResponse,
    CarePlanGoal, CarePlanGoalCreate, CarePlanGoalResponse,
    Appointment, AppointmentCreate, AppointmentPatch, AppointmentResponse,
    MedicationRefill, MedicationRefillCreate, MedicationRefillPatch, MedicationRefillResponse,
    Reminder, ReminderCreate, ReminderPatch, ReminderResponse,
    Consent, ConsentCreate, ConsentPatch, ConsentResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Care Art Mock Backend",
    description="Local QA mock — no real PHI, no AWS dependencies.",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── RBAC configuration ───────────────────────────────────────────────────────

STAFF_ROLES = {
    "program_administrator",
    "care_coordinator",
    "nurse_medication_aide",
    "billing_specialist",
    "compliance_officer",
}

WRITE_ROLES = {
    "participant": {"program_administrator", "care_coordinator", "nurse_medication_aide", "compliance_officer"},
    "attendance": {"program_administrator", "care_coordinator"},
    "claim": {"billing_specialist", "program_administrator"},
    "mar_record": {"nurse_medication_aide"},
    "incident": STAFF_ROLES,
    "user": {"program_administrator"},
    # Phase 2
    "care_plan": {"care_coordinator"},
    "appointment": {"care_coordinator"},
    "medication_refill": {"nurse_medication_aide"},
    "reminder": {"care_coordinator"},
    "consent": {"care_coordinator", "compliance_officer"},
}

READ_ROLES = {
    "participant": STAFF_ROLES,
    "attendance": STAFF_ROLES,
    "claim": STAFF_ROLES,
    "mar_record": STAFF_ROLES,
    "incident": STAFF_ROLES,
    "user": STAFF_ROLES,
    "audit_log": {"compliance_officer"},
    # Phase 2
    "care_plan": {"care_coordinator", "nurse_medication_aide", "compliance_officer", "physician"},
    "appointment": {"program_administrator", "care_coordinator", "nurse_medication_aide", "compliance_officer", "physician"},
    "medication_refill": {"nurse_medication_aide", "compliance_officer"},
    "reminder": {"care_coordinator", "compliance_officer", "participant_family"},
    "consent": {"care_coordinator", "compliance_officer"},
}

SUD_PRIVILEGED_ROLES = {
    "participant": {"compliance_officer", "care_coordinator", "nurse_medication_aide", "program_administrator"},
    "mar_record": {"compliance_officer", "nurse_medication_aide"},
    "incident": {"compliance_officer", "care_coordinator", "nurse_medication_aide", "program_administrator"},
    # Phase 2 — 42 CFR Part 2 gated roles (Sections 3.8.9, 3.9.9, 3.10.8)
    "care_plan": {"care_coordinator", "nurse_medication_aide", "compliance_officer"},
    "appointment": {"care_coordinator", "nurse_medication_aide", "compliance_officer"},
    "medication_refill": {"care_coordinator", "nurse_medication_aide", "compliance_officer"},
}

PHI_ENTITIES = {"participant", "attendance", "claim", "mar_record", "incident", "user"}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _409(error_code: str, message: str):
    raise HTTPException(status_code=409, detail={"error_code": error_code, "message": message})


def _404(entity: str, id_: str):
    raise HTTPException(status_code=404, detail={"error_code": "NOT_FOUND", "message": f"{entity} {id_} not found."})


def _403(message: str, error_code: str = "FORBIDDEN"):
    raise HTTPException(status_code=403, detail={"error_code": error_code, "message": message})


def _422(error_code: str, message: str):
    raise HTTPException(status_code=422, detail={"error_code": error_code, "message": message})


def _405(message: str = "Method not allowed."):
    raise HTTPException(status_code=405, detail={"error_code": "METHOD_NOT_ALLOWED", "message": message})


def _400(error_code: str, message: str):
    raise HTTPException(status_code=400, detail={"error_code": error_code, "message": message})


def _gen_claim_ref(payer_type: str) -> str:
    prefix = "MCD" if payer_type == "medicaid" else "MCR"
    today = date.today().strftime("%Y%m%d")
    return f"{prefix}-{today}-{str(uuid.uuid4())[:8].upper()}"


def _emit_audit(
    db: Session,
    user_id: str,
    tenant_id: str,
    session_id: str,
    action_type: str,
    resource_type: str,
    resource_id: str,
    data_affected: list,
    source_ip: str,
    outcome: str,
    layer: str = "APP_SERVICE",
    retention_years: int = 6,
):
    row = AuditLog(
        audit_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        data_affected=data_affected,
        source_ip=source_ip,
        outcome=outcome,
        layer=layer,
        retention_years=retention_years,
    )
    db.add(row)
    db.flush()


def _get_caller(request: Request) -> dict:
    return {
        "user_id": request.headers.get("X-User-Id", "anonymous"),
        "tenant_id": request.headers.get("X-Tenant-Id", ""),
        "session_id": request.headers.get("X-Session-Id", "sess_mock"),
        "role": request.headers.get("X-User-Role", ""),
        "status": request.headers.get("X-User-Status", "active"),
        "mfa": request.headers.get("X-User-MFA", "true").lower() == "true",
        "source_ip": request.client.host if request.client else "127.0.0.1",
    }


def _check_active(caller: dict):
    if caller["status"] in ("inactive", "suspended"):
        _403(f"User account is {caller['status']}.", "ACCOUNT_INACTIVE")


def _check_mfa(caller: dict):
    if not caller["mfa"]:
        _403("MFA enrollment required to access PHI modules.", "MFA_REQUIRED")


def _check_write_rbac(entity: str, caller: dict, db: Session):
    _check_active(caller)
    allowed = WRITE_ROLES.get(entity, set())
    if caller["role"] not in allowed:
        _403(f"Role '{caller['role']}' is not permitted to write {entity}.", "RBAC_DENIED")


def _check_read_rbac(entity: str, caller: dict):
    _check_active(caller)
    allowed = READ_ROLES.get(entity, set())
    if caller["role"] not in allowed:
        _403(f"Role '{caller['role']}' is not permitted to read {entity}.", "RBAC_DENIED")


def _check_sud_read(entity: str, caller: dict):
    privileged = SUD_PRIVILEGED_ROLES.get(entity, set())
    if caller["role"] not in privileged:
        _403(
            f"Access to SUD-flagged {entity} records requires special authorization (42 CFR Part 2).",
            "SUD_ACCESS_DENIED",
        )


def _check_optimistic_lock(version_sent: int, version_stored: int, error_code: str):
    if version_sent != version_stored:
        raise HTTPException(
            status_code=409,
            detail={"error_code": error_code, "message": "Version conflict. Reload and retry."},
        )


# ─── Participant state machine ─────────────────────────────────────────────────

_PARTICIPANT_TRANSITIONS = {
    "active": {"on_leave", "discharged", "deceased"},
    "on_leave": {"active", "discharged", "deceased"},
    "discharged": set(),
    "deceased": set(),
}


def _validate_participant_transition(current: str, next_: str):
    allowed = _PARTICIPANT_TRANSITIONS.get(current, set())
    if next_ != current and next_ not in allowed:
        _422(
            "PARTICIPANT_INVALID_STATUS_TRANSITION",
            f"Transition from '{current}' to '{next_}' is not allowed.",
        )


# ─── User status state machine ─────────────────────────────────────────────────

_USER_TRANSITIONS = {
    "active": {"inactive", "suspended"},
    "inactive": {"active"},
    "suspended": {"active", "inactive"},
    "pending_activation": {"active"},
}


def _validate_user_transition(current: str, next_: str):
    allowed = _USER_TRANSITIONS.get(current, set())
    if next_ != current and next_ not in allowed:
        _422(
            "USER_INVALID_STATUS_TRANSITION",
            f"Transition from '{current}' to '{next_}' is not allowed.",
        )


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ─── Participants ─────────────────────────────────────────────────────────────

@app.post("/participants", response_model=ParticipantResponse, status_code=201, tags=["participants"])
def create_participant(body: ParticipantCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("participant", caller, db)
    _check_mfa(caller)

    if not body.enrollment_date:
        _400("ENROLLMENT_DATE_REQUIRED", "enrollment_date is required.")

    if body.medicaid_id is not None:
        exists = db.query(Participant).filter(
            Participant.tenant_id == body.tenant_id,
            Participant.medicaid_id == body.medicaid_id,
        ).first()
        if exists:
            _409(
                "PARTICIPANT_DUPLICATE_MEDICAID_ID",
                "A participant with this Medicaid ID is already registered in this program.",
            )

    now = datetime.now(timezone.utc)
    row = Participant(
        participant_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **body.model_dump(),
    )
    db.add(row)
    db.flush()
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "Participant", row.participant_id,
        [k for k, v in body.model_dump().items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return ParticipantResponse.model_validate(row)


@app.get("/participants/{participant_id}", response_model=ParticipantResponse, tags=["participants"])
def get_participant(participant_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("participant", caller)
    _check_mfa(caller)

    row = db.query(Participant).filter(
        Participant.participant_id == participant_id,
        Participant.is_deleted.is_(False),
    ).first()
    if not row:
        _404("Participant", participant_id)

    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "Participant", participant_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("Participant", participant_id)

    if row.is_sud_record:
        _check_sud_read("participant", caller)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_READ", "Participant", row.participant_id,
        ["participant_id", "first_name", "last_name", "date_of_birth"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return ParticipantResponse.model_validate(row)


@app.get("/participants", response_model=List[ParticipantResponse], tags=["participants"])
def list_participants(
    tenant_id: str = Query(...),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("participant", caller)

    q = db.query(Participant).filter(Participant.tenant_id == tenant_id)
    if not include_deleted:
        q = q.filter(Participant.is_deleted.is_(False))
    rows = q.offset(offset).limit(limit).all()
    return [ParticipantResponse.model_validate(r) for r in rows]


@app.patch("/participants/{participant_id}", response_model=ParticipantResponse, tags=["participants"])
def patch_participant(participant_id: str, body: ParticipantPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("participant", caller, db)
    _check_mfa(caller)

    row = db.query(Participant).filter(Participant.participant_id == participant_id).first()
    if not row:
        _404("Participant", participant_id)
    if row.is_deleted:
        _422("PARTICIPANT_DELETED", "Cannot modify a deleted participant.")

    _check_optimistic_lock(body.version, row.version, "PARTICIPANT_VERSION_CONFLICT")

    changed_fields = []
    if body.program_status is not None:
        _validate_participant_transition(row.program_status, body.program_status.value)
        if body.program_status.value == "discharged" and row.discharge_date is None and body.discharge_date is None:
            body = body.model_copy(update={"discharge_date": date.today()})
        row.program_status = body.program_status.value
        changed_fields.append("program_status")

    for field in ("enrollment_date", "discharge_date", "discharge_reason", "authorized_units_per_week",
                  "functional_level", "mobility_status", "attending_physician_id", "is_deleted"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "Participant", row.participant_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return ParticipantResponse.model_validate(row)


@app.delete("/participants/{participant_id}", status_code=200, tags=["participants"])
def soft_delete_participant(participant_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("participant", caller, db)

    row = db.query(Participant).filter(Participant.participant_id == participant_id).first()
    if not row:
        _404("Participant", participant_id)
    if row.is_deleted:
        return {"participant_id": participant_id, "is_deleted": True}

    row.is_deleted = True
    row.updated_at = datetime.now(timezone.utc)
    row.version = row.version + 1
    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_DELETE", "Participant", row.participant_id,
        ["is_deleted"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return {"participant_id": participant_id, "is_deleted": True}


@app.delete("/participants/{participant_id}/hard", status_code=405, tags=["participants"])
def hard_delete_participant(participant_id: str):
    raise HTTPException(
        status_code=405,
        detail={
            "error_code": "HARD_DELETE_NOT_PERMITTED",
            "message": "Physical deletion of participant records is prohibited under HIPAA retention rules.",
        },
    )


# ─── Users ────────────────────────────────────────────────────────────────────

@app.post("/users", response_model=UserResponse, status_code=201, tags=["users"])
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("user", caller, db)

    exists = db.query(User).filter(
        User.tenant_id == body.tenant_id,
        User.email == body.email,
    ).first()
    if exists:
        _409(
            "USER_DUPLICATE_EMAIL",
            "An account with this email address already exists in this program.",
        )

    now = datetime.now(timezone.utc)
    row = User(
        user_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        failed_login_count=0,
        mfa_enabled=body.mfa_enabled,
        **{k: v for k, v in body.model_dump().items() if k != "mfa_enabled"},
    )
    db.add(row)
    db.flush()
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "User", row.user_id,
        [k for k, v in body.model_dump().items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return UserResponse.model_validate(row)


@app.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
def get_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("user", caller)

    row = db.query(User).filter(User.user_id == user_id).first()
    if not row:
        _404("User", user_id)
    return UserResponse.model_validate(row)


@app.get("/users", response_model=List[UserResponse], tags=["users"])
def list_users(
    tenant_id: str = Query(...),
    role: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("user", caller)

    q = db.query(User).filter(User.tenant_id == tenant_id)
    if role:
        q = q.filter(User.role == role)
    rows = q.offset(offset).limit(limit).all()
    return [UserResponse.model_validate(r) for r in rows]


@app.patch("/users/{user_id}", response_model=UserResponse, tags=["users"])
def patch_user(user_id: str, body: UserPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("user", caller, db)

    row = db.query(User).filter(User.user_id == user_id).first()
    if not row:
        _404("User", user_id)

    _check_optimistic_lock(body.version, row.version, "USER_VERSION_CONFLICT")

    changed_fields = []
    if body.status is not None:
        _validate_user_transition(row.status, body.status.value)
        if body.status.value == "inactive" and row.deactivated_at is None:
            row.deactivated_at = datetime.now(timezone.utc)
        row.status = body.status.value
        changed_fields.append("status")

    for field in ("role", "mfa_enabled", "phone"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val.value if hasattr(val, "value") else val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "User", row.user_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return UserResponse.model_validate(row)


@app.delete("/users/{user_id}", status_code=405, tags=["users"])
def delete_user(user_id: str):
    _405("Physical deletion of user records is prohibited. Use status=inactive.")


@app.post("/login", response_model=LoginResponse, tags=["auth"])
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    source_ip = request.client.host if request.client else "127.0.0.1"

    row = db.query(User).filter(User.user_id == body.user_id).first()
    if not row:
        raise HTTPException(status_code=401, detail={"error_code": "AUTH_FAILURE", "message": "Invalid credentials."})

    now = datetime.now(timezone.utc)

    # Check lockout
    locked_until = row.locked_until.replace(tzinfo=timezone.utc) if row.locked_until and row.locked_until.tzinfo is None else row.locked_until
    if locked_until and locked_until > now:
        _emit_audit(
            db, row.user_id, row.tenant_id, "sess_login",
            "AUTH_FAILURE", "User", row.user_id,
            ["locked_until"],
            source_ip, "DENIED",
        )
        db.commit()
        raise HTTPException(status_code=401, detail={"error_code": "ACCOUNT_LOCKED", "message": "Account is locked."})

    # Check password expiry (90 days)
    if row.password_changed_at and (now - row.password_changed_at) > timedelta(days=90):
        _emit_audit(
            db, row.user_id, row.tenant_id, "sess_login",
            "AUTH_FAILURE", "User", row.user_id,
            ["password_changed_at"],
            source_ip, "DENIED",
        )
        db.commit()
        raise HTTPException(status_code=403, detail={"error_code": "PASSWORD_EXPIRED", "message": "Password has expired. Please reset."})

    # Simulate password check (mock: plaintext comparison when hash is stored)
    password_rejected = (not body.password) or (
        bool(row.password_hash) and body.password != row.password_hash
    )
    if password_rejected:
        row.failed_login_count = (row.failed_login_count or 0) + 1
        if row.failed_login_count >= 5:
            row.locked_until = now + timedelta(minutes=30)
        db.flush()
        _emit_audit(
            db, row.user_id, row.tenant_id, "sess_login",
            "AUTH_FAILURE", "User", row.user_id,
            ["failed_login_count"],
            source_ip, "DENIED",
        )
        db.commit()
        raise HTTPException(status_code=401, detail={"error_code": "AUTH_FAILURE", "message": "Invalid credentials."})

    # Success
    row.failed_login_count = 0
    row.locked_until = None
    row.last_login_at = now
    _emit_audit(
        db, row.user_id, row.tenant_id, "sess_login",
        "AUTH_SUCCESS", "User", row.user_id,
        ["last_login_at"],
        source_ip, "SUCCESS",
    )
    db.commit()
    return LoginResponse(status="ok", message="Login successful.")


@app.post("/jobs/deactivate-dormant", tags=["jobs"])
def deactivate_dormant_accounts(db: Session = Depends(get_db)):
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    dormant = db.query(User).filter(
        User.status == "active",
        User.last_login_at < cutoff,
    ).all()
    deactivated = []
    for user in dormant:
        user.status = "inactive"
        user.deactivated_at = datetime.now(timezone.utc)
        _emit_audit(
            db, "system", user.tenant_id, "sess_job",
            "PHI_WRITE", "User", user.user_id,
            ["status", "deactivated_at"],
            "127.0.0.1", "SUCCESS",
        )
        deactivated.append(user.user_id)
    db.commit()
    return {"deactivated": deactivated}


# ─── Attendance ───────────────────────────────────────────────────────────────

@app.post("/attendance", response_model=AttendanceResponse, status_code=201, tags=["attendance"])
def create_attendance(body: AttendanceCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("attendance", caller, db)

    exists = db.query(Attendance).filter(
        Attendance.tenant_id == body.tenant_id,
        Attendance.participant_id == body.participant_id,
        Attendance.date_of_service == body.date_of_service,
    ).first()
    if exists:
        _409(
            "ATTENDANCE_DUPLICATE_DATE",
            "An attendance record for this participant already exists for the selected date of service.",
        )

    # Auto-calculate authorized_units_consumed if total_hours supplied
    att_data = body.model_dump()
    if body.total_hours is not None and body.authorized_units_consumed is None:
        # Medicaid: 1 unit = 15 min; Medicare: 1 unit per daily rate (set to 1.0)
        service_code = (body.service_type_code or "").upper()
        if service_code.startswith("MCR") or body.service_type_code == "medicare_daily":
            att_data["authorized_units_consumed"] = 1.0
        else:
            att_data["authorized_units_consumed"] = round(body.total_hours * 4, 2)

    now = datetime.now(timezone.utc)
    row = Attendance(
        attendance_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **att_data,
    )
    db.add(row)
    db.flush()
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "Attendance", row.attendance_id,
        [k for k, v in att_data.items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return AttendanceResponse.model_validate(row)


@app.get("/attendance/{attendance_id}", response_model=AttendanceResponse, tags=["attendance"])
def get_attendance(attendance_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("attendance", caller)

    row = db.query(Attendance).filter(Attendance.attendance_id == attendance_id).first()
    if not row:
        _404("Attendance", attendance_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "Attendance", attendance_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("Attendance", attendance_id)
    return AttendanceResponse.model_validate(row)


@app.get("/attendance", response_model=List[AttendanceResponse], tags=["attendance"])
def list_attendance(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("attendance", caller)

    q = db.query(Attendance).filter(Attendance.tenant_id == tenant_id)
    if participant_id:
        q = q.filter(Attendance.participant_id == participant_id)
    if status:
        q = q.filter(Attendance.status == status)
    rows = q.offset(offset).limit(limit).all()
    return [AttendanceResponse.model_validate(r) for r in rows]


@app.patch("/attendance/{attendance_id}", response_model=AttendanceResponse, tags=["attendance"])
def patch_attendance(attendance_id: str, body: AttendancePatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("attendance", caller, db)

    row = db.query(Attendance).filter(Attendance.attendance_id == attendance_id).first()
    if not row:
        _404("Attendance", attendance_id)

    if row.status == "billed":
        _422("ATTENDANCE_BILLED_IMMUTABLE", "Billed attendance records cannot be modified.")

    # Void restrictions
    if body.status and body.status.value == "voided":
        if not body.void_reason:
            _422("VOID_REASON_REQUIRED", "void_reason is required when setting status to voided.")
        # Cannot void attendance referenced by an active claim
        active_claims = db.query(Claim).filter(
            Claim.claim_status.in_(["submitted", "accepted", "paid"]),
        ).all()
        for c in active_claims:
            if attendance_id in (c.attendance_ids or []):
                _422("ATTENDANCE_REFERENCED_BY_ACTIVE_CLAIM",
                     "Cannot void attendance record referenced by an active claim.")

    _check_optimistic_lock(body.version, row.version, "ATTENDANCE_VERSION_CONFLICT")

    changed_fields = []
    if body.status is not None:
        if row.status == "confirmed" and body.status.value not in ("voided", "confirmed"):
            # Editing status on confirmed record that isn't a void → reset to pending
            row.status = "pending"
            changed_fields.append("status")
        else:
            row.status = body.status.value
            changed_fields.append("status")
    elif row.status == "confirmed":
        # Any field change on a confirmed record resets it to pending
        row.status = "pending"
        changed_fields.append("status")

    for field in ("sign_in_time", "sign_out_time", "total_hours", "authorized_units_consumed", "void_reason"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "Attendance", row.attendance_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return AttendanceResponse.model_validate(row)


# ─── Claims ───────────────────────────────────────────────────────────────────

CLAIM_PHASE2_FIELDS = {"secondary_payer_id", "secondary_policy_number", "clearinghouse_id", "edi_transaction_id"}


@app.post("/claims", response_model=ClaimResponse, status_code=201, tags=["claims"])
def create_claim(body: ClaimCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("claim", caller, db)

    if not body.attendance_ids:
        _422("CLAIM_NO_ATTENDANCE_RECORDS", "At least one attendance_id is required.")

    # Validate attendance records exist within the same tenant and are confirmed
    for att_id in body.attendance_ids:
        att = db.query(Attendance).filter(
            Attendance.attendance_id == att_id,
            Attendance.tenant_id == body.tenant_id,
        ).first()
        if not att:
            _422("CLAIM_ATTENDANCE_NOT_FOUND", f"Attendance record {att_id} does not exist.")
        if att.status != "confirmed":
            _422(
                "ATTENDANCE_NOT_CONFIRMED",
                f"Attendance record {att_id} must have status=confirmed before claim creation (current: {att.status}).",
            )

    # Composite duplicate check (per tenant)
    exists = db.query(Claim).filter(
        Claim.tenant_id == body.tenant_id,
        Claim.participant_id == body.participant_id,
        Claim.date_of_service_start == body.date_of_service_start,
        Claim.procedure_code == body.procedure_code,
        Claim.payer_type == body.payer_type,
    ).first()
    if exists:
        _409(
            "CLAIM_DUPLICATE",
            "A claim for this participant, date of service, procedure, and payer already exists.",
        )

    # Generate globally unique claim reference number (retry on collision)
    for _ in range(5):
        ref = _gen_claim_ref(body.payer_type)
        if not db.query(Claim).filter(Claim.claim_reference_number == ref).first():
            break
    else:
        _409("CLAIM_DUPLICATE_REFERENCE", "Could not generate a unique claim reference number.")

    now = datetime.now(timezone.utc)
    data = body.model_dump()

    # Server-calculates units_billed; caller-supplied value is ignored entirely.
    att_rows = [
        db.query(Attendance).filter(Attendance.attendance_id == aid).first()
        for aid in body.attendance_ids
    ]
    data["units_billed"] = sum(
        float(a.authorized_units_consumed or 0) for a in att_rows
    )

    row = Claim(
        claim_id=str(uuid.uuid4()),
        claim_reference_number=ref,
        created_at=now,
        updated_at=now,
        **data,
    )
    db.add(row)
    db.flush()

    # Mark attendance records as billed
    for att in att_rows:
        att.status = "billed"
        att.updated_at = now

    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "Claim", row.claim_id,
        [k for k, v in data.items() if v is not None],
        caller["source_ip"], "SUCCESS",
        retention_years=10,
    )
    db.commit()
    db.refresh(row)
    return ClaimResponse.model_validate(row)


@app.get("/claims/{claim_id}", response_model=ClaimResponse, tags=["claims"])
def get_claim(claim_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("claim", caller)

    row = db.query(Claim).filter(Claim.claim_id == claim_id).first()
    if not row:
        _404("Claim", claim_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "Claim", claim_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("Claim", claim_id)
    return ClaimResponse.model_validate(row)


@app.get("/claims", response_model=List[ClaimResponse], tags=["claims"])
def list_claims(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    claim_status: Optional[str] = Query(None),
    payer_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("claim", caller)

    q = db.query(Claim).filter(Claim.tenant_id == tenant_id)
    if participant_id:
        q = q.filter(Claim.participant_id == participant_id)
    if claim_status:
        q = q.filter(Claim.claim_status == claim_status)
    if payer_type:
        q = q.filter(Claim.payer_type == payer_type)
    rows = q.offset(offset).limit(limit).all()
    return [ClaimResponse.model_validate(r) for r in rows]


@app.patch("/claims/{claim_id}", response_model=ClaimResponse, tags=["claims"])
def patch_claim(claim_id: str, body: ClaimPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("claim", caller, db)

    row = db.query(Claim).filter(Claim.claim_id == claim_id).first()
    if not row:
        _404("Claim", claim_id)

    # Immutable states: submitted and paid — checked before version validation
    if row.claim_status in ("submitted", "paid"):
        _422(
            "CLAIM_FIELD_IMMUTABLE",
            f"Claim in status '{row.claim_status}' cannot be modified.",
        )

    _check_optimistic_lock(body.version, row.version, "CLAIM_VERSION_CONFLICT")

    changed_fields = []
    if body.claim_status is not None:
        # draft → submitted is the only forward transition
        if row.claim_status == "draft" and body.claim_status.value == "submitted":
            row.claim_status = "submitted"
            row.submission_date = datetime.now(timezone.utc)
            changed_fields.extend(["claim_status", "submission_date"])
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "PHI_DISCLOSE", "Claim", row.claim_id,
                ["claim_status", "submission_date", "claim_reference_number"],
                caller["source_ip"], "SUCCESS",
                retention_years=10,
            )
        else:
            row.claim_status = body.claim_status.value
            changed_fields.append("claim_status")

    for field in ("rejection_reason",):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "Claim", row.claim_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
        retention_years=10,
    )
    db.commit()
    db.refresh(row)
    return ClaimResponse.model_validate(row)


# ─── MAR Records ──────────────────────────────────────────────────────────────

@app.post("/mar-records", response_model=MARRecordResponse, status_code=201, tags=["mar-records"])
def create_mar_record(body: MARRecordCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("mar_record", caller, db)

    # Enforce administered_by role restriction (Section 3.5.7)
    nurse = db.query(User).filter(User.user_id == body.administered_by).first()
    if not nurse:
        _403(f"User {body.administered_by} not found.")
    if nurse.role != "nurse_medication_aide":
        _403(
            f"administered_by must reference a user with role=nurse_medication_aide "
            f"(got role={nurse.role})."
        )

    # Unique constraint check
    exists = db.query(MARRecord).filter(
        MARRecord.tenant_id == body.tenant_id,
        MARRecord.participant_id == body.participant_id,
        MARRecord.medication_name == body.medication_name,
        MARRecord.scheduled_time == body.scheduled_time,
    ).first()
    if exists:
        _409(
            "MAR_DUPLICATE_EVENT",
            "A medication administration record for this participant, medication, and scheduled time already exists.",
        )

    # Business rule: administered requires administered_time
    if body.status == "administered" and body.administered_time is None:
        _422(
            "MAR_MISSING_ADMINISTERED_TIME",
            "administered_time is required when status=administered.",
        )

    # Business rule: refused/held require notes
    if body.status in ("refused", "held") and not body.notes:
        _422(
            "MAR_MISSING_NOTES",
            f"notes is required when status={body.status} to document clinical rationale.",
        )

    # Administered time bounds
    if body.administered_time is not None:
        now_naive = datetime.utcnow()
        adm = body.administered_time
        if adm.tzinfo is not None:
            adm = adm.astimezone(timezone.utc).replace(tzinfo=None)
        sched = body.scheduled_time
        if sched.tzinfo is not None:
            sched = sched.astimezone(timezone.utc).replace(tzinfo=None)
        if adm > now_naive:
            _422("ADMIN_TIME_FUTURE", "administered_time cannot be in the future.")
        early_cutoff = sched - timedelta(hours=2)
        if adm < early_cutoff:
            _422("ADMIN_TIME_TOO_EARLY", "administered_time is more than 2 hours before scheduled_time.")

    # Correction validation
    if body.is_correction:
        if not body.original_mar_id:
            _422("MAR_CORRECTION_MISSING_ORIGINAL", "original_mar_id is required when is_correction=True.")
        if not body.notes or len(body.notes) < 20:
            _422("MAR_CORRECTION_NOTES_TOO_SHORT", "notes must be at least 20 characters when is_correction=True.")
        original = db.query(MARRecord).filter(MARRecord.mar_id == body.original_mar_id).first()
        if not original:
            _422("MAR_CORRECTION_ORIGINAL_NOT_FOUND", f"original_mar_id {body.original_mar_id} not found.")

    now = datetime.now(timezone.utc)
    row = MARRecord(
        mar_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **body.model_dump(),
    )
    db.add(row)
    db.flush()

    action = "PHI_WRITE"
    if body.is_controlled_substance:
        action = "PHI_WRITE"  # controlled substance write is still PHI_WRITE but will be specially noted

    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        action, "MARRecord", row.mar_id,
        [k for k, v in body.model_dump().items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return MARRecordResponse.model_validate(row)


@app.get("/mar-records/{mar_id}", response_model=MARRecordResponse, tags=["mar-records"])
def get_mar_record(mar_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("mar_record", caller)

    row = db.query(MARRecord).filter(MARRecord.mar_id == mar_id).first()
    if not row:
        _404("MARRecord", mar_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "MARRecord", mar_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("MARRecord", mar_id)

    if row.is_controlled_substance:
        priv = SUD_PRIVILEGED_ROLES["mar_record"]
        if caller["role"] not in priv:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "ACCESS_DENIED", "MARRecord", row.mar_id,
                ["is_controlled_substance"],
                caller["source_ip"], "DENIED",
            )
            db.commit()
            _403(
                "Access to controlled-substance MARRecord requires special authorization (42 CFR Part 2).",
                "SUD_ACCESS_DENIED",
            )

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_READ", "MARRecord", row.mar_id,
        ["mar_id", "medication_name", "administered_by", "status"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return MARRecordResponse.model_validate(row)


@app.get("/mar-records", response_model=List[MARRecordResponse], tags=["mar-records"])
def list_mar_records(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("mar_record", caller)

    q = db.query(MARRecord).filter(MARRecord.tenant_id == tenant_id)
    if participant_id:
        q = q.filter(MARRecord.participant_id == participant_id)
    if status:
        q = q.filter(MARRecord.status == status)
    rows = q.offset(offset).limit(limit).all()
    return [MARRecordResponse.model_validate(r) for r in rows]


@app.patch("/mar-records/{mar_id}", response_model=MARRecordResponse, tags=["mar-records"])
def patch_mar_record(mar_id: str, body: MARRecordPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("mar_record", caller, db)

    row = db.query(MARRecord).filter(MARRecord.mar_id == mar_id).first()
    if not row:
        _404("MARRecord", mar_id)

    # Administered records are immutable
    if row.status == "administered":
        _422("MAR_ADMINISTERED_IMMUTABLE", "MARRecord with status=administered cannot be modified.")

    _check_optimistic_lock(body.version, row.version, "MAR_VERSION_CONFLICT")

    changed_fields = []
    for field in ("status", "administered_time", "notes"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val.value if hasattr(val, "value") else val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "MARRecord", row.mar_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return MARRecordResponse.model_validate(row)


# ─── Incidents ────────────────────────────────────────────────────────────────

@app.post("/incidents", response_model=IncidentResponse, status_code=201, tags=["incidents"])
def create_incident(body: IncidentCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("incident", caller, db)

    # Auto-escalate severe or medical_emergency incidents (Section 3.6.8)
    auto_escalate = body.severity == "severe" or body.incident_type == "medical_emergency"
    effective_status = "escalated" if auto_escalate else body.status.value

    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["status"] = effective_status

    row = Incident(
        incident_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **data,
    )
    db.add(row)
    db.flush()

    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "Incident", row.incident_id,
        [k for k, v in data.items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return IncidentResponse.model_validate(row)


@app.get("/incidents/{incident_id}", response_model=IncidentResponse, tags=["incidents"])
def get_incident(incident_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)

    # Physicians and participant_family cannot read incidents
    if caller["role"] in ("physician", "participant_family"):
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "Incident", incident_id,
            ["incident_id"],
            caller["source_ip"], "DENIED",
        )
        db.commit()
        _403("Role is not permitted to access incident records.", "RBAC_DENIED")

    _check_active(caller)

    row = db.query(Incident).filter(Incident.incident_id == incident_id).first()
    if not row:
        _404("Incident", incident_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "Incident", incident_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("Incident", incident_id)

    if row.is_sud_related:
        priv = SUD_PRIVILEGED_ROLES["incident"]
        if caller["role"] not in priv:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "ACCESS_DENIED", "Incident", row.incident_id,
                ["is_sud_related"],
                caller["source_ip"], "DENIED",
            )
            db.commit()
            _403(
                "Access to SUD-related incident records requires special authorization (42 CFR Part 2).",
                "SUD_ACCESS_DENIED",
            )

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_READ", "Incident", row.incident_id,
        ["incident_id", "incident_type", "severity", "status"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return IncidentResponse.model_validate(row)


@app.get("/incidents", response_model=List[IncidentResponse], tags=["incidents"])
def list_incidents(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    if caller["role"] in ("physician", "participant_family"):
        _403("Role is not permitted to access incident records.", "RBAC_DENIED")
    _check_active(caller)

    q = db.query(Incident).filter(Incident.tenant_id == tenant_id)
    if participant_id:
        q = q.filter(Incident.participant_id == participant_id)
    if status:
        q = q.filter(Incident.status == status)
    if severity:
        q = q.filter(Incident.severity == severity)
    rows = q.offset(offset).limit(limit).all()
    return [IncidentResponse.model_validate(r) for r in rows]


@app.patch("/incidents/{incident_id}", response_model=IncidentResponse, tags=["incidents"])
def patch_incident(incident_id: str, body: IncidentPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("incident", caller, db)

    row = db.query(Incident).filter(Incident.incident_id == incident_id).first()
    if not row:
        _404("Incident", incident_id)

    # Closed incidents are immutable
    if row.status == "closed":
        _422("INCIDENT_CLOSED_IMMUTABLE", "Closed incident cannot be modified.")

    # Escalated → closed requires regulatory_submission_date
    if body.status and body.status.value == "closed" and row.status == "escalated":
        if not (body.regulatory_submission_date or row.regulatory_submission_date):
            _422(
                "INCIDENT_MISSING_REGULATORY_SUBMISSION",
                "regulatory_submission_date is required before closing an escalated incident.",
            )

    _check_optimistic_lock(body.version, row.version, "INCIDENT_VERSION_CONFLICT")

    changed_fields = []
    if body.status is not None:
        row.status = body.status.value
        changed_fields.append("status")

    for field in ("description", "location", "severity", "regulatory_submission_date"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val.value if hasattr(val, "value") else val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "Incident", row.incident_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return IncidentResponse.model_validate(row)


# ─── Audit Logs ───────────────────────────────────────────────────────────────

@app.get("/audit-logs", response_model=List[AuditLogResponse], tags=["audit"])
def list_audit_logs(
    tenant_id: str = Query(...),
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    if caller["role"] not in READ_ROLES["audit_log"]:
        _403("Only compliance_officer role may access audit logs.", "RBAC_DENIED")

    q = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        q = q.filter(AuditLog.resource_id == resource_id)
    if action_type:
        q = q.filter(AuditLog.action_type == action_type)
    rows = q.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    return [AuditLogResponse.model_validate(r) for r in rows]


# ─── Jobs ─────────────────────────────────────────────────────────────────────

@app.get("/jobs/escalated-incidents-alert", tags=["jobs"])
def alert_escalated_incidents_approaching_deadline(db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(hours=20)
    incidents = db.query(Incident).filter(
        Incident.status == "escalated",
        Incident.regulatory_submission_date.is_(None),
        Incident.created_at <= cutoff,
    ).all()
    alerted = []
    for inc in incidents:
        _emit_audit(
            db, "system", inc.tenant_id, "sess_job",
            "ESCALATION_ALERT", "Incident", inc.incident_id,
            ["status", "regulatory_submission_date"],
            "127.0.0.1", "SUCCESS",
        )
        alerted.append(inc.incident_id)
    db.commit()
    return {"alerted": alerted}


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Shared helpers
# ════════════════════════════════════════════════════════════════════════════


def _consent_gate_active(db: Session, tenant_id: str, participant_id: str, recipient_type: str):
    """Return the active, in-window consent row (or None) for a disclosure gate.

    Mirrors the disclosure gate query in Section 3.12.7 / 3.12.8:
    status='active' AND effective_date <= today AND expiration_date > today.
    """
    today = date.today()
    return db.query(Consent).filter(
        Consent.tenant_id == tenant_id,
        Consent.participant_id == participant_id,
        Consent.disclosure_recipient_type == recipient_type,
        Consent.status == "active",
        Consent.is_deleted.is_(False),
        Consent.effective_date <= today,
        Consent.expiration_date > today,
    ).first()


def _strip_nonempty(value) -> bool:
    return value is not None and str(value).strip() != ""


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2 — CarePlan  (Section 3.8)
# ════════════════════════════════════════════════════════════════════════════


def _care_plan_sud_gate(db: Session, caller: dict, row: "CarePlan", action: str):
    """Evaluate Participant.is_sud_record gate for a single care plan (3.8.9)."""
    participant = db.query(Participant).filter(
        Participant.participant_id == row.participant_id
    ).first()
    if participant and participant.is_sud_record:
        if caller["role"] not in SUD_PRIVILEGED_ROLES["care_plan"]:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "ACCESS_DENIED", "CarePlan", row.care_plan_id,
                ["is_sud_record"], caller["source_ip"], "DENIED",
            )
            db.commit()
            _403(
                "Access to SUD-flagged care plan records requires special authorization (42 CFR Part 2).",
                "SUD_ACCESS_DENIED",
            )
        return True
    return False


@app.post("/care-plans", response_model=CarePlanResponse, status_code=201, tags=["care-plans"])
def create_care_plan(body: CarePlanCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("care_plan", caller, db)
    _check_mfa(caller)

    # Determine version_number: read participant max and increment if not supplied.
    if body.version_number is not None:
        version_number = body.version_number
    else:
        max_v = db.query(CarePlan.version_number).filter(
            CarePlan.tenant_id == body.tenant_id,
            CarePlan.participant_id == body.participant_id,
        ).order_by(CarePlan.version_number.desc()).first()
        version_number = (max_v[0] + 1) if max_v else 1

    exists = db.query(CarePlan).filter(
        CarePlan.tenant_id == body.tenant_id,
        CarePlan.participant_id == body.participant_id,
        CarePlan.version_number == version_number,
    ).first()
    if exists:
        _409(
            "CARE_PLAN_DUPLICATE_VERSION",
            "A care plan with this version number already exists for this participant.",
        )

    now = datetime.now(timezone.utc)
    data = body.model_dump(exclude={"version_number"})
    row = CarePlan(
        care_plan_id=str(uuid.uuid4()),
        version_number=version_number,
        status="draft",
        created_at=now,
        updated_at=now,
        **data,
    )
    db.add(row)
    db.flush()
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "CarePlan", row.care_plan_id,
        [k for k, v in data.items() if v is not None] + ["version_number"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return CarePlanResponse.model_validate(row)


@app.get("/care-plans/{care_plan_id}", response_model=CarePlanResponse, tags=["care-plans"])
def get_care_plan(care_plan_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("care_plan", caller)
    _check_mfa(caller)

    row = db.query(CarePlan).filter(
        CarePlan.care_plan_id == care_plan_id,
        CarePlan.is_deleted.is_(False),
    ).first()
    if not row:
        _404("CarePlan", care_plan_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "CarePlan", care_plan_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("CarePlan", care_plan_id)

    _care_plan_sud_gate(db, caller, row, "read")

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_READ", "CarePlan", row.care_plan_id,
        ["care_plan_id", "participant_id", "status", "version_number"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return CarePlanResponse.model_validate(row)


@app.get("/care-plans", response_model=List[CarePlanResponse], tags=["care-plans"])
def list_care_plans(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("care_plan", caller)

    q = db.query(CarePlan).filter(CarePlan.tenant_id == tenant_id)
    if not include_deleted:
        q = q.filter(CarePlan.is_deleted.is_(False))
    if participant_id:
        q = q.filter(CarePlan.participant_id == participant_id)
    if status:
        q = q.filter(CarePlan.status == status)
    rows = q.offset(offset).limit(limit).all()

    # SUD redaction: omit notes (and goals are a separate endpoint) for unauthorized roles.
    sud_participants = {
        p.participant_id
        for p in db.query(Participant).filter(
            Participant.tenant_id == tenant_id,
            Participant.is_sud_record.is_(True),
        ).all()
    }
    privileged = caller["role"] in SUD_PRIVILEGED_ROLES["care_plan"]

    results = []
    for r in rows:
        resp = CarePlanResponse.model_validate(r)
        if r.participant_id in sud_participants and not privileged:
            resp = resp.model_copy(update={"notes": None})
        results.append(resp)
    return results


@app.patch("/care-plans/{care_plan_id}", response_model=CarePlanResponse, tags=["care-plans"])
def patch_care_plan(care_plan_id: str, body: CarePlanPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("care_plan", caller, db)
    _check_mfa(caller)

    row = db.query(CarePlan).filter(CarePlan.care_plan_id == care_plan_id).first()
    if not row:
        _404("CarePlan", care_plan_id)
    if row.is_deleted:
        _422("CARE_PLAN_DELETED", "Cannot modify a deleted care plan.")

    _care_plan_sud_gate(db, caller, row, "write")

    # Superseded / archived plans are immutable.
    if row.status in ("superseded", "archived"):
        _422(
            "CARE_PLAN_IMMUTABLE",
            f"A care plan in status '{row.status}' cannot be modified.",
        )

    _check_optimistic_lock(body.version, row.version, "CARE_PLAN_VERSION_CONFLICT")

    clinical_fields = ("primary_diagnosis_code", "secondary_diagnosis_codes", "functional_level")

    # Active plans: only review_date and notes may be updated in place; clinical
    # field changes and care_coordinator_id are rejected.
    if row.status == "active":
        for f in clinical_fields:
            if getattr(body, f, None) is not None:
                _422(
                    "CARE_PLAN_REVISION_REQUIRED",
                    "Changing a clinical field on an active plan requires a full plan revision.",
                )
        if body.care_coordinator_id is not None and body.care_coordinator_id != row.care_coordinator_id:
            _422(
                "CARE_PLAN_COORDINATOR_IMMUTABLE",
                "care_coordinator_id is immutable once a care plan is active.",
            )

    changed_fields = []

    # Activation transition.
    if body.status is not None and body.status.value == "active" and row.status != "active":
        effective_date = body.effective_date if body.effective_date is not None else row.effective_date
        physician_id = body.physician_id if body.physician_id is not None else row.physician_id
        physician_sig = (
            body.physician_signature_date
            if body.physician_signature_date is not None
            else row.physician_signature_date
        )
        if effective_date is None:
            _422("CARE_PLAN_MISSING_EFFECTIVE_DATE", "A care plan cannot be activated without an effective date.")
        if physician_id is None or physician_sig is None:
            _422("CARE_PLAN_UNSIGNED", "A care plan cannot be activated without a physician signature date.")

        existing_active = db.query(CarePlan).filter(
            CarePlan.tenant_id == row.tenant_id,
            CarePlan.participant_id == row.participant_id,
            CarePlan.status == "active",
            CarePlan.care_plan_id != row.care_plan_id,
            CarePlan.is_deleted.is_(False),
        ).first()
        if existing_active:
            _409(
                "CARE_PLAN_ALREADY_ACTIVE",
                "This participant already has an active care plan. The current plan must be superseded before a new one can be activated.",
            )

    # Apply field updates.
    if body.status is not None:
        row.status = body.status.value
        changed_fields.append("status")

    for field in ("effective_date", "review_date", "expiration_date",
                  "primary_diagnosis_code", "secondary_diagnosis_codes", "functional_level",
                  "notes", "physician_id", "physician_signature_date",
                  "physician_order_reference", "care_coordinator_id", "is_deleted"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val.value if hasattr(val, "value") else val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "CarePlan", row.care_plan_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return CarePlanResponse.model_validate(row)


@app.delete("/care-plans/{care_plan_id}", status_code=200, tags=["care-plans"])
def soft_delete_care_plan(care_plan_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("care_plan", caller, db)

    row = db.query(CarePlan).filter(CarePlan.care_plan_id == care_plan_id).first()
    if not row:
        _404("CarePlan", care_plan_id)
    if row.is_deleted:
        return {"care_plan_id": care_plan_id, "is_deleted": True}

    row.is_deleted = True
    row.updated_at = datetime.now(timezone.utc)
    row.version = row.version + 1
    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_DELETE", "CarePlan", row.care_plan_id,
        ["is_deleted"], caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return {"care_plan_id": care_plan_id, "is_deleted": True}


@app.post("/care-plans/{care_plan_id}/fhir-transmit", tags=["care-plans"])
def fhir_transmit_care_plan(care_plan_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("care_plan", caller, db)

    row = db.query(CarePlan).filter(
        CarePlan.care_plan_id == care_plan_id,
        CarePlan.is_deleted.is_(False),
    ).first()
    if not row:
        _404("CarePlan", care_plan_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _404("CarePlan", care_plan_id)

    participant = db.query(Participant).filter(
        Participant.participant_id == row.participant_id
    ).first()

    # When the participant is not SUD-flagged, no consent gate applies (3.12.8).
    if not (participant and participant.is_sud_record):
        _emit_audit(
            db, caller["user_id"], row.tenant_id, caller["session_id"],
            "CONSENT_CHECK", "CarePlan", row.care_plan_id,
            ["disclosure_recipient_type:ehr"], caller["source_ip"], "ALLOWED",
        )
        db.commit()
        return {"care_plan_id": care_plan_id, "transmitted": True, "consent": "not_required"}

    consent = _consent_gate_active(db, row.tenant_id, row.participant_id, "ehr")
    if not consent:
        _emit_audit(
            db, caller["user_id"], row.tenant_id, caller["session_id"],
            "CONSENT_CHECK", "CarePlan", row.care_plan_id,
            ["disclosure_recipient_type:ehr"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _403(
            "No active EHR consent on file. FHIR transmission blocked under 42 CFR Part 2.",
            "CONSENT_REQUIRED",
        )

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "CONSENT_CHECK", "CarePlan", row.care_plan_id,
        ["disclosure_recipient_type:ehr", "consent_id:" + consent.consent_id],
        caller["source_ip"], "ALLOWED",
    )
    db.commit()
    return {"care_plan_id": care_plan_id, "transmitted": True, "consent": "allowed"}


# ─── CarePlanGoal ──────────────────────────────────────────────────────────────


@app.post("/care-plan-goals", response_model=CarePlanGoalResponse, status_code=201, tags=["care-plans"])
def create_care_plan_goal(body: CarePlanGoalCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("care_plan", caller, db)
    _check_mfa(caller)

    parent = db.query(CarePlan).filter(CarePlan.care_plan_id == body.care_plan_id).first()
    if not parent:
        _422("CARE_PLAN_GOAL_PLAN_NOT_FOUND", f"Care plan {body.care_plan_id} does not exist.")

    _care_plan_sud_gate(db, caller, parent, "write")

    exists = db.query(CarePlanGoal).filter(
        CarePlanGoal.tenant_id == body.tenant_id,
        CarePlanGoal.care_plan_id == body.care_plan_id,
        CarePlanGoal.domain == body.domain.value,
        CarePlanGoal.description == body.description,
    ).first()
    if exists:
        _409(
            "CARE_PLAN_GOAL_DUPLICATE",
            "A goal with this domain and description already exists on this care plan.",
        )

    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["domain"] = body.domain.value
    data["status"] = body.status.value
    row = CarePlanGoal(
        goal_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **data,
    )
    db.add(row)
    db.flush()
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "CarePlanGoal", row.goal_id,
        [k for k, v in data.items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return CarePlanGoalResponse.model_validate(row)


@app.get("/care-plan-goals", response_model=List[CarePlanGoalResponse], tags=["care-plans"])
def list_care_plan_goals(
    tenant_id: str = Query(...),
    care_plan_id: str = Query(...),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("care_plan", caller)

    parent = db.query(CarePlan).filter(CarePlan.care_plan_id == care_plan_id).first()
    if parent:
        _care_plan_sud_gate(db, caller, parent, "read")

    rows = db.query(CarePlanGoal).filter(
        CarePlanGoal.tenant_id == tenant_id,
        CarePlanGoal.care_plan_id == care_plan_id,
    ).offset(offset).limit(limit).all()
    return [CarePlanGoalResponse.model_validate(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Appointment  (Section 3.9)
# ════════════════════════════════════════════════════════════════════════════


_APPOINTMENT_TERMINAL = {"completed", "cancelled", "no_show"}


def _appointment_sud_gate(db: Session, caller: dict, row: "Appointment"):
    participant = db.query(Participant).filter(
        Participant.participant_id == row.participant_id
    ).first()
    is_sud = participant and participant.is_sud_record
    if is_sud:
        if caller["role"] not in SUD_PRIVILEGED_ROLES["appointment"]:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "ACCESS_DENIED", "Appointment", row.appointment_id,
                ["is_sud_record"], caller["source_ip"], "DENIED",
            )
            db.commit()
            _403(
                "Access to SUD-flagged appointment records requires special authorization (42 CFR Part 2).",
                "SUD_ACCESS_DENIED",
            )
        return True
    if caller["role"] == "nurse_medication_aide":
        _403(
            "nurse_medication_aide may only access appointments for SUD-flagged participants.",
            "RBAC_DENIED",
        )
    return False


def _appointment_overlap(db: Session, tenant_id: str, physician_id: str,
                         new_start, new_end, self_id: Optional[str]):
    q = db.query(Appointment).filter(
        Appointment.tenant_id == tenant_id,
        Appointment.physician_id == physician_id,
        Appointment.status.notin_(["cancelled", "no_show"]),
        Appointment.scheduled_start < new_end,
        Appointment.scheduled_end > new_start,
        Appointment.is_deleted.is_(False),
    )
    if self_id is not None:
        q = q.filter(Appointment.appointment_id != self_id)
    return q.first()


@app.post("/appointments", response_model=AppointmentResponse, status_code=201, tags=["appointments"])
def create_appointment(body: AppointmentCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("appointment", caller, db)
    _check_mfa(caller)

    if body.scheduled_end <= body.scheduled_start:
        _422("APPOINTMENT_INVALID_WINDOW", "scheduled_end must be strictly after scheduled_start.")

    exists = db.query(Appointment).filter(
        Appointment.tenant_id == body.tenant_id,
        Appointment.participant_id == body.participant_id,
        Appointment.physician_id == body.physician_id,
        Appointment.scheduled_start == body.scheduled_start,
    ).first()
    if exists:
        _409(
            "APPOINTMENT_DUPLICATE",
            "An appointment for this participant with this physician at the same start time already exists.",
        )

    if _appointment_overlap(db, body.tenant_id, body.physician_id,
                            body.scheduled_start, body.scheduled_end, None):
        _409(
            "APPOINTMENT_PHYSICIAN_OVERLAP",
            "This physician already has an appointment scheduled during the requested time slot.",
        )

    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["appointment_type"] = body.appointment_type.value
    data["status"] = body.status.value
    row = Appointment(
        appointment_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **data,
    )
    db.add(row)
    db.flush()
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "Appointment", row.appointment_id,
        [k for k, v in data.items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return AppointmentResponse.model_validate(row)


@app.get("/appointments/{appointment_id}", response_model=AppointmentResponse, tags=["appointments"])
def get_appointment(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("appointment", caller)
    _check_mfa(caller)

    row = db.query(Appointment).filter(
        Appointment.appointment_id == appointment_id,
        Appointment.is_deleted.is_(False),
    ).first()
    if not row:
        _404("Appointment", appointment_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "Appointment", appointment_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("Appointment", appointment_id)

    _appointment_sud_gate(db, caller, row)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_READ", "Appointment", row.appointment_id,
        ["appointment_id", "participant_id", "physician_id", "status"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return AppointmentResponse.model_validate(row)


@app.get("/appointments", response_model=List[AppointmentResponse], tags=["appointments"])
def list_appointments(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    physician_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("appointment", caller)

    q = db.query(Appointment).filter(Appointment.tenant_id == tenant_id)
    if not include_deleted:
        q = q.filter(Appointment.is_deleted.is_(False))
    if participant_id:
        q = q.filter(Appointment.participant_id == participant_id)
    if physician_id:
        q = q.filter(Appointment.physician_id == physician_id)
    if status:
        q = q.filter(Appointment.status == status)
    rows = q.offset(offset).limit(limit).all()

    sud_participants = {
        p.participant_id
        for p in db.query(Participant).filter(
            Participant.tenant_id == tenant_id,
            Participant.is_sud_record.is_(True),
        ).all()
    }
    privileged = caller["role"] in SUD_PRIVILEGED_ROLES["appointment"]

    results = []
    for r in rows:
        resp = AppointmentResponse.model_validate(r)
        if r.participant_id in sud_participants and not privileged:
            resp = resp.model_copy(update={
                "appointment_type": None,
                "cancellation_reason": None,
                "result_notes": None,
                "follow_up_required": None,
            })
        results.append(resp)
    return results


@app.patch("/appointments/{appointment_id}", response_model=AppointmentResponse, tags=["appointments"])
def patch_appointment(appointment_id: str, body: AppointmentPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("appointment", caller, db)
    _check_mfa(caller)

    row = db.query(Appointment).filter(Appointment.appointment_id == appointment_id).first()
    if not row:
        _404("Appointment", appointment_id)
    if row.is_deleted:
        _422("APPOINTMENT_DELETED", "Cannot modify a deleted appointment.")

    _appointment_sud_gate(db, caller, row)

    immutable_fields = {"scheduled_start", "physician_id", "appointment_type"}
    body_set = {k for k, v in body.model_dump(exclude={"version", "updated_by"}).items() if v is not None}

    # Completed immutability (mixed body rejected as a whole).
    if row.status == "completed":
        if body_set & immutable_fields:
            _422(
                "APPOINTMENT_COMPLETED_IMMUTABLE",
                "A completed appointment's scheduled time, physician, or type cannot be changed.",
            )

    # Terminal-state status transitions are not reversible.
    if body.status is not None and row.status in _APPOINTMENT_TERMINAL and body.status.value != row.status:
        _422(
            "APPOINTMENT_INVALID_STATUS_TRANSITION",
            f"Transition from terminal state '{row.status}' is not allowed.",
        )

    # Cancellation requires a non-empty reason.
    if body.status is not None and body.status.value == "cancelled":
        if not _strip_nonempty(body.cancellation_reason):
            _422(
                "APPOINTMENT_MISSING_CANCELLATION_REASON",
                "A cancellation reason is required when cancelling an appointment.",
            )

    _check_optimistic_lock(body.version, row.version, "APPOINTMENT_VERSION_CONFLICT")

    # Overlap re-check when scheduled_start or physician_id change.
    new_start = body.scheduled_start if body.scheduled_start is not None else row.scheduled_start
    new_end = body.scheduled_end if body.scheduled_end is not None else row.scheduled_end
    new_physician = body.physician_id if body.physician_id is not None else row.physician_id
    if body.scheduled_start is not None or body.physician_id is not None:
        if new_end <= new_start:
            _422("APPOINTMENT_INVALID_WINDOW", "scheduled_end must be strictly after scheduled_start.")
        if _appointment_overlap(db, row.tenant_id, new_physician, new_start, new_end, row.appointment_id):
            _409(
                "APPOINTMENT_PHYSICIAN_OVERLAP",
                "This physician already has an appointment scheduled during the requested time slot.",
            )

    changed_fields = []
    if body.status is not None:
        row.status = body.status.value
        changed_fields.append("status")

    for field in ("scheduled_start", "scheduled_end", "physician_id", "appointment_type",
                  "cancellation_reason", "result_notes", "fhir_result_reference", "follow_up_required"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val.value if hasattr(val, "value") else val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "Appointment", row.appointment_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return AppointmentResponse.model_validate(row)


@app.delete("/appointments/{appointment_id}", status_code=200, tags=["appointments"])
def soft_delete_appointment(appointment_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("appointment", caller, db)

    row = db.query(Appointment).filter(Appointment.appointment_id == appointment_id).first()
    if not row:
        _404("Appointment", appointment_id)
    if row.is_deleted:
        return {"appointment_id": appointment_id, "is_deleted": True}

    row.is_deleted = True
    row.updated_at = datetime.now(timezone.utc)
    row.version = row.version + 1
    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_DELETE", "Appointment", row.appointment_id,
        ["is_deleted"], caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return {"appointment_id": appointment_id, "is_deleted": True}


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2 — MedicationRefill  (Section 3.10)
# ════════════════════════════════════════════════════════════════════════════


_REFILL_TERMINAL = {"fulfilled", "denied", "cancelled"}


def _refill_controlled_gate(db: Session, caller: dict, row: "MedicationRefill"):
    """Elevated access for controlled-substance refills (3.10.8)."""
    if row.is_controlled_substance:
        if caller["role"] not in SUD_PRIVILEGED_ROLES["medication_refill"]:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "ACCESS_DENIED", "MedicationRefill", row.refill_id,
                ["is_controlled_substance"], caller["source_ip"], "DENIED",
            )
            db.commit()
            _403(
                "Access to controlled-substance refill records requires special authorization (42 CFR Part 2).",
                "SUD_ACCESS_DENIED",
            )
        return True
    return False


@app.post("/medication-refills", response_model=MedicationRefillResponse, status_code=201, tags=["medication-refills"])
def create_medication_refill(body: MedicationRefillCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_active(caller)
    if caller["role"] == "care_coordinator":
        if not body.is_controlled_substance:
            _403("care_coordinator may only access controlled-substance refill records.", "RBAC_DENIED")
    elif caller["role"] not in WRITE_ROLES.get("medication_refill", set()):
        _403(f"Role '{caller['role']}' is not permitted to write medication_refill.", "RBAC_DENIED")
    _check_mfa(caller)

    if body.quantity_requested is None or body.quantity_requested < 1:
        _422("REFILL_INVALID_QUANTITY", "quantity_requested must be a positive integer greater than zero.")

    exists = db.query(MedicationRefill).filter(
        MedicationRefill.tenant_id == body.tenant_id,
        MedicationRefill.participant_id == body.participant_id,
        MedicationRefill.medication_name == body.medication_name,
        MedicationRefill.requested_at == body.requested_at,
    ).first()
    if exists:
        _409(
            "REFILL_DUPLICATE",
            "A refill request for this participant and medication at the same time already exists.",
        )

    open_req = db.query(MedicationRefill).filter(
        MedicationRefill.tenant_id == body.tenant_id,
        MedicationRefill.participant_id == body.participant_id,
        MedicationRefill.medication_name == body.medication_name,
        MedicationRefill.status.notin_(list(_REFILL_TERMINAL)),
    ).first()
    if open_req:
        _409(
            "REFILL_DUPLICATE_IN_FLIGHT",
            "An open refill request for this medication already exists for this participant. "
            "The existing request must be fulfilled, denied, or cancelled before a new one can be submitted.",
        )

    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["status"] = body.status.value
    if body.route is not None:
        data["route"] = body.route.value
    row = MedicationRefill(
        refill_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **data,
    )
    db.add(row)
    db.flush()
    # is_controlled_substance / medication_name etc. are Part 2-protected — log field names only.
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "MedicationRefill", row.refill_id,
        [k for k, v in data.items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return MedicationRefillResponse.model_validate(row)


@app.get("/medication-refills/{refill_id}", response_model=MedicationRefillResponse, tags=["medication-refills"])
def get_medication_refill(refill_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_active(caller)
    if caller["role"] not in READ_ROLES.get("medication_refill", set()) and caller["role"] != "care_coordinator":
        _403(f"Role '{caller['role']}' is not permitted to read medication_refill.", "RBAC_DENIED")
    _check_mfa(caller)

    row = db.query(MedicationRefill).filter(
        MedicationRefill.refill_id == refill_id,
        MedicationRefill.is_deleted.is_(False),
    ).first()
    if not row:
        _404("MedicationRefill", refill_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "MedicationRefill", refill_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("MedicationRefill", refill_id)

    if caller["role"] == "care_coordinator" and not row.is_controlled_substance:
        _403("care_coordinator may only access controlled-substance refill records.", "RBAC_DENIED")

    _refill_controlled_gate(db, caller, row)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_READ", "MedicationRefill", row.refill_id,
        ["refill_id", "participant_id", "status"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return MedicationRefillResponse.model_validate(row)


@app.get("/medication-refills", response_model=List[MedicationRefillResponse], tags=["medication-refills"])
def list_medication_refills(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_active(caller)
    if caller["role"] not in READ_ROLES.get("medication_refill", set()) and caller["role"] != "care_coordinator":
        _403(f"Role '{caller['role']}' is not permitted to read medication_refill.", "RBAC_DENIED")

    q = db.query(MedicationRefill).filter(MedicationRefill.tenant_id == tenant_id)
    if not include_deleted:
        q = q.filter(MedicationRefill.is_deleted.is_(False))
    if participant_id:
        q = q.filter(MedicationRefill.participant_id == participant_id)
    if status:
        q = q.filter(MedicationRefill.status == status)
    if caller["role"] == "care_coordinator":
        q = q.filter(MedicationRefill.is_controlled_substance.is_(True))
    rows = q.offset(offset).limit(limit).all()

    privileged = caller["role"] in SUD_PRIVILEGED_ROLES["medication_refill"]
    results = []
    for r in rows:
        resp = MedicationRefillResponse.model_validate(r)
        if r.is_controlled_substance and not privileged:
            resp = resp.model_copy(update={
                "medication_name": None,
                "dose": None,
                "route": None,
                "is_controlled_substance": None,
                "denial_reason": None,
                "ncpdp_script_reference": None,
            })
        results.append(resp)
    return results


@app.patch("/medication-refills/{refill_id}", response_model=MedicationRefillResponse, tags=["medication-refills"])
def patch_medication_refill(refill_id: str, body: MedicationRefillPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_active(caller)
    if caller["role"] == "care_coordinator":
        pass
    elif caller["role"] not in WRITE_ROLES.get("medication_refill", set()):
        _403(f"Role '{caller['role']}' is not permitted to write medication_refill.", "RBAC_DENIED")
    _check_mfa(caller)

    row = db.query(MedicationRefill).filter(MedicationRefill.refill_id == refill_id).first()
    if not row:
        _404("MedicationRefill", refill_id)
    if caller["role"] == "care_coordinator" and not row.is_controlled_substance:
        _403("care_coordinator may only access controlled-substance refill records.", "RBAC_DENIED")
    if row.is_deleted:
        _422("REFILL_DELETED", "Cannot modify a deleted refill record.")

    _refill_controlled_gate(db, caller, row)

    immutable_fields = {"medication_name", "dose", "route", "quantity_requested"}
    body_set = {k for k, v in body.model_dump(exclude={"version", "updated_by"}).items() if v is not None}

    # Fulfilled immutability (mixed body rejected as a whole).
    if row.status == "fulfilled" and (body_set & immutable_fields):
        _422(
            "REFILL_FULFILLED_IMMUTABLE",
            "A fulfilled refill request's medication, dose, route, or quantity cannot be changed.",
        )

    # Quantity validation on PATCH.
    if body.quantity_requested is not None and body.quantity_requested < 1:
        _422("REFILL_INVALID_QUANTITY", "quantity_requested must be a positive integer greater than zero.")

    # Terminal states cannot be reversed.
    if body.status is not None and row.status in _REFILL_TERMINAL and body.status.value != row.status:
        _422(
            "REFILL_INVALID_STATUS_TRANSITION",
            f"Transition from terminal state '{row.status}' is not allowed.",
        )

    if body.status is not None and body.status.value == "denied":
        if not _strip_nonempty(body.denial_reason):
            _422("REFILL_MISSING_DENIAL_REASON", "A denial reason is required when denying a refill request.")
    if body.status is not None and body.status.value == "cancelled":
        if not _strip_nonempty(body.cancellation_reason):
            _422("REFILL_MISSING_CANCELLATION_REASON", "A cancellation reason is required when cancelling a refill request.")

    _check_optimistic_lock(body.version, row.version, "REFILL_VERSION_CONFLICT")

    changed_fields = []
    if body.status is not None:
        row.status = body.status.value
        changed_fields.append("status")
        if body.status.value == "fulfilled" and body.fulfilled_at is None and row.fulfilled_at is None:
            row.fulfilled_at = datetime.now(timezone.utc)
            changed_fields.append("fulfilled_at")

    for field in ("medication_name", "dose", "route", "quantity_requested", "refills_requested",
                  "denial_reason", "cancellation_reason", "fulfilled_at", "pharmacy_id",
                  "fhir_medication_request_id", "ncpdp_script_reference"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val.value if hasattr(val, "value") else val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "MedicationRefill", row.refill_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return MedicationRefillResponse.model_validate(row)


@app.delete("/medication-refills/{refill_id}", status_code=200, tags=["medication-refills"])
def soft_delete_medication_refill(refill_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("medication_refill", caller, db)

    row = db.query(MedicationRefill).filter(MedicationRefill.refill_id == refill_id).first()
    if not row:
        _404("MedicationRefill", refill_id)
    if row.is_deleted:
        return {"refill_id": refill_id, "is_deleted": True}

    row.is_deleted = True
    row.updated_at = datetime.now(timezone.utc)
    row.version = row.version + 1
    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_DELETE", "MedicationRefill", row.refill_id,
        ["is_deleted"], caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return {"refill_id": refill_id, "is_deleted": True}


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Reminder  (Section 3.11)
# ════════════════════════════════════════════════════════════════════════════


# Minimal PHI pattern detector for notification payloads (Section 3.11.7).
_PHI_TOKENS = (
    "dob", "date of birth", "ssn", "diagnosis", "icd", "mg", "ml",
    "metformin", "insulin", "oxycodone", "tablet", "medication",
)


def _contains_phi(*texts) -> bool:
    for t in texts:
        if not t:
            continue
        lowered = t.lower()
        for token in _PHI_TOKENS:
            if token in lowered:
                return True
    return False


def _reminder_immutable_after_send() -> set:
    return {"title", "body", "deep_link_path", "channel", "scheduled_for"}


@app.post("/reminders", response_model=ReminderResponse, status_code=201, tags=["reminders"])
def create_reminder(body: ReminderCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("reminder", caller, db)
    _check_mfa(caller)

    # Transport reminders are Phase 3 — rejected before any other constraint.
    if body.reminder_type.value == "transport":
        _422(
            "REMINDER_TRANSPORT_NOT_IMPLEMENTED",
            "reminder_type 'transport' is not supported in Phase 2. This value is reserved for Phase 3.",
        )

    if body.channel.value != "push":
        _422("REMINDER_INVALID_CHANNEL", "Only the 'push' channel is supported in Phase 2.")

    # scheduled_for must be strictly in the future (server UTC).
    now = datetime.now(timezone.utc)
    sched = body.scheduled_for
    if sched.tzinfo is None:
        sched_cmp = sched.replace(tzinfo=timezone.utc)
    else:
        sched_cmp = sched.astimezone(timezone.utc)
    if sched_cmp <= now:
        _422("REMINDER_INVALID_SCHEDULED_FOR", "scheduled_for must be a future date and time.")

    if _contains_phi(body.title, body.body):
        _422("REMINDER_PHI_IN_PAYLOAD", "Notification title and body must not contain protected health information.")

    exists = db.query(Reminder).filter(
        Reminder.tenant_id == body.tenant_id,
        Reminder.participant_id == body.participant_id,
        Reminder.reminder_type == body.reminder_type.value,
        Reminder.scheduled_for == body.scheduled_for,
    ).first()
    if exists:
        _409(
            "REMINDER_DUPLICATE",
            "A reminder of this type for this participant at this scheduled time already exists.",
        )

    open_scheduled = db.query(Reminder).filter(
        Reminder.tenant_id == body.tenant_id,
        Reminder.participant_id == body.participant_id,
        Reminder.reminder_type == body.reminder_type.value,
        Reminder.status == "scheduled",
    ).first()
    if open_scheduled:
        _409(
            "REMINDER_DUPLICATE_SCHEDULED",
            "A scheduled reminder of this type already exists for this participant. "
            "The existing reminder must be sent, delivered, failed, or cancelled before a new one can be scheduled.",
        )

    data = body.model_dump()
    data["reminder_type"] = body.reminder_type.value
    data["channel"] = body.channel.value
    data["status"] = body.status.value
    if body.reference_entity_type is not None:
        data["reference_entity_type"] = body.reference_entity_type.value
    if body.push_provider is not None:
        data["push_provider"] = body.push_provider.value
    row = Reminder(
        reminder_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **data,
    )
    db.add(row)
    db.flush()
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "PHI_WRITE", "Reminder", row.reminder_id,
        [k for k, v in data.items() if v is not None],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return ReminderResponse.model_validate(row)


@app.get("/reminders/{reminder_id}", response_model=ReminderResponse, tags=["reminders"])
def get_reminder(reminder_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("reminder", caller)

    row = db.query(Reminder).filter(
        Reminder.reminder_id == reminder_id,
        Reminder.is_deleted.is_(False),
    ).first()
    if not row:
        _404("Reminder", reminder_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "Reminder", reminder_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("Reminder", reminder_id)

    # participant_family may only read reminders addressed to themselves (3.11.8).
    if caller["role"] == "participant_family":
        if row.recipient_user_id != caller["user_id"]:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "ACCESS_DENIED", "Reminder", reminder_id,
                ["recipient_user_id"], caller["source_ip"], "DENIED",
            )
            db.commit()
            _403("This reminder is not addressed to the requesting user.", "RBAC_DENIED")

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_READ", "Reminder", row.reminder_id,
        ["reminder_id", "participant_id", "status"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return ReminderResponse.model_validate(row)


@app.get("/reminders", response_model=List[ReminderResponse], tags=["reminders"])
def list_reminders(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("reminder", caller)

    q = db.query(Reminder).filter(Reminder.tenant_id == tenant_id)
    if not include_deleted:
        q = q.filter(Reminder.is_deleted.is_(False))
    if participant_id:
        q = q.filter(Reminder.participant_id == participant_id)
    if status:
        q = q.filter(Reminder.status == status)
    # participant_family is limited to reminders addressed to them.
    if caller["role"] == "participant_family":
        q = q.filter(Reminder.recipient_user_id == caller["user_id"])
    rows = q.offset(offset).limit(limit).all()
    return [ReminderResponse.model_validate(r) for r in rows]


@app.patch("/reminders/{reminder_id}", response_model=ReminderResponse, tags=["reminders"])
def patch_reminder(reminder_id: str, body: ReminderPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("reminder", caller, db)
    _check_mfa(caller)

    row = db.query(Reminder).filter(Reminder.reminder_id == reminder_id).first()
    if not row:
        _404("Reminder", reminder_id)
    if row.is_deleted:
        _422("REMINDER_DELETED", "Cannot modify a deleted reminder.")

    immutable_fields = _reminder_immutable_after_send()
    body_set = {k for k, v in body.model_dump(exclude={"version", "updated_by"}).items() if v is not None}

    # Sent immutability: once status leaves scheduled, content fields are immutable.
    if row.status != "scheduled" and (body_set & immutable_fields):
        _422(
            "REMINDER_SENT_IMMUTABLE",
            "A reminder that has already been submitted to the push provider cannot have its "
            "content, channel, scheduled time, or failure reason changed.",
        )

    # failure_reason writable only when status is (or is being set to) failed.
    if body.failure_reason is not None:
        target_status = body.status.value if body.status is not None else row.status
        if target_status != "failed":
            _422(
                "REMINDER_SENT_IMMUTABLE",
                "failure_reason may only be set on a reminder whose status is 'failed'.",
            )

    # PHI re-check on title/body.
    if body.title is not None or body.body is not None:
        if _contains_phi(body.title, body.body):
            _422("REMINDER_PHI_IN_PAYLOAD", "Notification title and body must not contain protected health information.")

    # Cancellation requires a reason.
    if body.status is not None and body.status.value == "cancelled":
        if not _strip_nonempty(body.cancellation_reason):
            _422("REMINDER_MISSING_CANCELLATION_REASON", "A cancellation reason is required when cancelling a reminder.")

    _check_optimistic_lock(body.version, row.version, "REMINDER_VERSION_CONFLICT")

    changed_fields = []
    if body.status is not None:
        row.status = body.status.value
        changed_fields.append("status")

    for field in ("title", "body", "deep_link_path", "channel", "scheduled_for",
                  "sent_at", "delivered_at", "failure_reason", "cancellation_reason",
                  "push_provider", "device_push_token", "provider_message_id"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val.value if hasattr(val, "value") else val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "Reminder", row.reminder_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return ReminderResponse.model_validate(row)


@app.post("/reminders/{reminder_id}/deliver", tags=["reminders"])
def deliver_reminder(reminder_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("reminder", caller, db)

    row = db.query(Reminder).filter(
        Reminder.reminder_id == reminder_id,
        Reminder.is_deleted.is_(False),
    ).first()
    if not row:
        _404("Reminder", reminder_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _404("Reminder", reminder_id)

    participant = db.query(Participant).filter(
        Participant.participant_id == row.participant_id
    ).first()

    # Adapter PHI re-check (defence-in-depth).
    if _contains_phi(row.title, row.body):
        _emit_audit(
            db, caller["user_id"], row.tenant_id, caller["session_id"],
            "PHI_PAYLOAD_BLOCKED", "Reminder", row.reminder_id,
            ["title", "body"], caller["source_ip"], "DENIED",
        )
        db.commit()
        return {"reminder_id": reminder_id, "delivered": False, "reason": "PHI_PAYLOAD_BLOCKED"}

    # SUD delivery gate (3.11.8): is_sud_record true AND reference_entity_type != none.
    is_sud = bool(participant and participant.is_sud_record)
    ref_type = row.reference_entity_type
    gate_applies = is_sud and ref_type is not None and ref_type != "none"

    if gate_applies:
        consent = _consent_gate_active(db, row.tenant_id, row.participant_id, "push_notification")
        if not consent:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "SUD_DELIVERY_GATE", "Reminder", row.reminder_id,
                ["participant_id"], caller["source_ip"], "SUPPRESSED",
            )
            db.commit()
            return {"reminder_id": reminder_id, "delivered": False, "status": row.status, "reason": "SUD_DELIVERY_GATE"}
        _emit_audit(
            db, caller["user_id"], row.tenant_id, caller["session_id"],
            "SUD_DELIVERY_GATE", "Reminder", row.reminder_id,
            ["participant_id", "consent_id:" + consent.consent_id],
            caller["source_ip"], "ALLOWED",
        )

    # Mark sent.
    now = datetime.now(timezone.utc)
    row.status = "sent"
    row.sent_at = now
    row.version = row.version + 1
    row.updated_at = now
    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_WRITE", "Reminder", row.reminder_id,
        ["status", "sent_at"], caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return {"reminder_id": reminder_id, "delivered": True, "status": row.status}


@app.delete("/reminders/{reminder_id}", status_code=200, tags=["reminders"])
def soft_delete_reminder(reminder_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("reminder", caller, db)

    row = db.query(Reminder).filter(Reminder.reminder_id == reminder_id).first()
    if not row:
        _404("Reminder", reminder_id)
    if row.is_deleted:
        return {"reminder_id": reminder_id, "is_deleted": True}

    row.is_deleted = True
    row.updated_at = datetime.now(timezone.utc)
    row.version = row.version + 1
    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_DELETE", "Reminder", row.reminder_id,
        ["is_deleted"], caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return {"reminder_id": reminder_id, "is_deleted": True}


# ════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Consent  (Section 3.12)
# ════════════════════════════════════════════════════════════════════════════


@app.post("/consents", response_model=ConsentResponse, status_code=201, tags=["consents"])
def create_consent(body: ConsentCreate, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("consent", caller, db)
    _check_mfa(caller)

    if not _strip_nonempty(body.consent_form_reference):
        _422(
            "CONSENT_MISSING_FORM_REFERENCE",
            "A consent form reference is required. The signed consent artifact must be documented before the consent record is activated.",
        )

    if body.expiration_date <= body.effective_date:
        _422("CONSENT_INVALID_DATES", "expiration_date must be strictly after effective_date.")

    if body.expiration_date <= date.today():
        _422(
            "CONSENT_EXPIRATION_IN_PAST",
            "expiration_date must be a future date. A consent cannot be created already expired.",
        )

    active_exists = db.query(Consent).filter(
        Consent.tenant_id == body.tenant_id,
        Consent.participant_id == body.participant_id,
        Consent.disclosure_recipient_type == body.disclosure_recipient_type.value,
        Consent.status == "active",
        Consent.is_deleted.is_(False),
    ).first()
    if active_exists:
        _409(
            "CONSENT_DUPLICATE_ACTIVE",
            "An active consent of this type already exists for this participant. "
            "The existing consent must be withdrawn or expired before a new one can be created.",
        )

    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["disclosure_recipient_type"] = body.disclosure_recipient_type.value
    data["consent_method"] = body.consent_method.value
    row = Consent(
        consent_id=str(uuid.uuid4()),
        status="active",
        created_at=now,
        updated_at=now,
        **data,
    )
    db.add(row)
    db.flush()
    # scope_description is Part 2-protected — do NOT include it in the audit payload.
    _emit_audit(
        db, caller["user_id"], body.tenant_id, caller["session_id"],
        "CONSENT_CREATED", "Consent", row.consent_id,
        ["consent_id", "participant_id", "disclosure_recipient_type",
         "effective_date", "expiration_date", "created_by"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return ConsentResponse.model_validate(row)


# Static-path routes are declared BEFORE the dynamic /consents/{consent_id} route
# so FastAPI matches them first (path matching is order-dependent).

@app.post("/consents/expire-check", tags=["consents", "jobs"])
def consent_expire_check(db: Session = Depends(get_db)):
    """Background cron endpoint: transition active consents whose expiration_date
    has passed to status='expired' (Section 3.12, Phase 2 scope note)."""
    today = date.today()
    expiring = db.query(Consent).filter(
        Consent.status == "active",
        Consent.is_deleted.is_(False),
        Consent.expiration_date <= today,
    ).all()
    expired = []
    for c in expiring:
        c.status = "expired"
        c.version = c.version + 1
        c.updated_at = datetime.now(timezone.utc)
        _emit_audit(
            db, "system", c.tenant_id, "sess_job",
            "CONSENT_EXPIRED", "Consent", c.consent_id,
            ["consent_id", "participant_id"], "127.0.0.1", "SUCCESS",
        )
        expired.append(c.consent_id)
    db.commit()
    return {"expired": expired}


@app.get("/consents/disclosure-gate", tags=["consents"])
def consent_disclosure_gate(
    tenant_id: str = Query(...),
    participant_id: str = Query(...),
    disclosure_recipient_type: str = Query(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """5-condition disclosure gate check (Section 3.12.7 / 3.12.8).

    Conditions: Participant.is_sud_record = true, plus an active, in-window consent
    of the requested type (status='active', effective_date <= today, expiration_date > today).
    """
    caller = _get_caller(request)
    _check_read_rbac("consent", caller)

    participant = db.query(Participant).filter(
        Participant.participant_id == participant_id,
        Participant.tenant_id == tenant_id,
    ).first()

    # When participant is not SUD-flagged, Part 2 controls do not trigger.
    if not (participant and participant.is_sud_record):
        return {
            "allowed": True,
            "reason": "not_sud_record",
            "consent_id": None,
        }

    consent = _consent_gate_active(db, tenant_id, participant_id, disclosure_recipient_type)
    outcome = "ALLOWED" if consent else "DENIED"
    _emit_audit(
        db, caller["user_id"], tenant_id, caller["session_id"],
        "CONSENT_CHECK", "Consent", consent.consent_id if consent else participant_id,
        ["disclosure_recipient_type:" + disclosure_recipient_type],
        caller["source_ip"], outcome,
    )
    db.commit()
    return {
        "allowed": bool(consent),
        "reason": "active_consent" if consent else "no_active_consent",
        "consent_id": consent.consent_id if consent else None,
    }


@app.get("/consents/{consent_id}", response_model=ConsentResponse, tags=["consents"])
def get_consent(consent_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_read_rbac("consent", caller)
    _check_mfa(caller)

    row = db.query(Consent).filter(
        Consent.consent_id == consent_id,
        Consent.is_deleted.is_(False),
    ).first()
    if not row:
        _404("Consent", consent_id)
    if caller["tenant_id"] and row.tenant_id != caller["tenant_id"]:
        _emit_audit(
            db, caller["user_id"], caller["tenant_id"], caller["session_id"],
            "ACCESS_DENIED", "Consent", consent_id,
            ["tenant_id"], caller["source_ip"], "DENIED",
        )
        db.commit()
        _404("Consent", consent_id)

    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_READ", "Consent", row.consent_id,
        ["consent_id", "participant_id", "disclosure_recipient_type", "status"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return ConsentResponse.model_validate(row)


@app.get("/consents", response_model=List[ConsentResponse], tags=["consents"])
def list_consents(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    disclosure_recipient_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    request: Request = None,
    db: Session = Depends(get_db),
):
    caller = _get_caller(request)
    _check_read_rbac("consent", caller)

    q = db.query(Consent).filter(Consent.tenant_id == tenant_id)
    if not include_deleted:
        q = q.filter(Consent.is_deleted.is_(False))
    if participant_id:
        q = q.filter(Consent.participant_id == participant_id)
    if disclosure_recipient_type:
        q = q.filter(Consent.disclosure_recipient_type == disclosure_recipient_type)
    if status:
        q = q.filter(Consent.status == status)
    rows = q.offset(offset).limit(limit).all()
    return [ConsentResponse.model_validate(r) for r in rows]


@app.patch("/consents/{consent_id}", response_model=ConsentResponse, tags=["consents"])
def patch_consent(consent_id: str, body: ConsentPatch, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("consent", caller, db)
    _check_mfa(caller)

    row = db.query(Consent).filter(Consent.consent_id == consent_id).first()
    if not row:
        _404("Consent", consent_id)
    if row.is_deleted:
        _422("CONSENT_DELETED", "Cannot modify a deleted consent record.")

    # Withdrawn / expired records are fully immutable.
    if row.status in ("withdrawn", "expired"):
        _422(
            "CONSENT_WITHDRAWN_IMMUTABLE",
            "A withdrawn or expired consent record cannot be modified. Create a new consent record to restore authorization.",
        )

    # Date validation when either date supplied.
    if body.effective_date is not None or body.expiration_date is not None:
        eff = body.effective_date if body.effective_date is not None else row.effective_date
        exp = body.expiration_date if body.expiration_date is not None else row.expiration_date
        if exp <= eff:
            _422("CONSENT_INVALID_DATES", "expiration_date must be strictly after effective_date.")
        if exp <= date.today():
            _422(
                "CONSENT_EXPIRATION_IN_PAST",
                "expiration_date must be a future date. A consent cannot be created already expired.",
            )

    _check_optimistic_lock(body.version, row.version, "CONSENT_VERSION_CONFLICT")

    changed_fields = []
    is_withdrawal = body.status is not None and body.status.value == "withdrawn"

    if body.status is not None:
        row.status = body.status.value
        changed_fields.append("status")
        if is_withdrawal and row.withdrawn_at is None:
            row.withdrawn_at = datetime.now(timezone.utc)
            changed_fields.append("withdrawn_at")

    for field in ("effective_date", "expiration_date", "withdrawal_reason", "is_deleted"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val)
            changed_fields.append(field)

    if body.updated_by:
        row.updated_by = body.updated_by

    row.version = row.version + 1
    row.updated_at = datetime.now(timezone.utc)

    action = "CONSENT_WITHDRAWN" if is_withdrawal else "PHI_WRITE"
    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        action, "Consent", row.consent_id,
        changed_fields or ["version"],
        caller["source_ip"], "SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return ConsentResponse.model_validate(row)


@app.delete("/consents/{consent_id}", status_code=200, tags=["consents"])
def soft_delete_consent(consent_id: str, request: Request, db: Session = Depends(get_db)):
    caller = _get_caller(request)
    _check_write_rbac("consent", caller, db)

    row = db.query(Consent).filter(Consent.consent_id == consent_id).first()
    if not row:
        _404("Consent", consent_id)
    if row.is_deleted:
        return {"consent_id": consent_id, "is_deleted": True}

    row.is_deleted = True
    row.updated_at = datetime.now(timezone.utc)
    row.version = row.version + 1
    _emit_audit(
        db, caller["user_id"], row.tenant_id, caller["session_id"],
        "PHI_DELETE", "Consent", row.consent_id,
        ["is_deleted"], caller["source_ip"], "SUCCESS",
    )
    db.commit()
    return {"consent_id": consent_id, "is_deleted": True}

