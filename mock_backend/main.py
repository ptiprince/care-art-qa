from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
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
    "participant": STAFF_ROLES,
    "attendance": {"program_administrator", "care_coordinator"},
    "claim": {"billing_specialist", "program_administrator"},
    "mar_record": {"nurse_medication_aide"},
    "incident": STAFF_ROLES,
    "user": {"program_administrator"},
}

READ_ROLES = {
    "participant": STAFF_ROLES,
    "attendance": STAFF_ROLES,
    "claim": STAFF_ROLES,
    "mar_record": STAFF_ROLES,
    "incident": STAFF_ROLES,
    "user": STAFF_ROLES,
    "audit_log": {"compliance_officer"},
}

SUD_PRIVILEGED_ROLES = {
    "participant": {"compliance_officer", "care_coordinator", "nurse_medication_aide", "program_administrator"},
    "mar_record": {"compliance_officer", "nurse_medication_aide"},
    "incident": {"compliance_officer", "care_coordinator", "nurse_medication_aide", "program_administrator"},
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
        timestamp=datetime.utcnow(),
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

    now = datetime.utcnow()
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
    row.updated_at = datetime.utcnow()

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
    row.updated_at = datetime.utcnow()
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
    _405("Physical deletion of participant records is prohibited.")


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

    now = datetime.utcnow()
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
            row.deactivated_at = datetime.utcnow()
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
    row.updated_at = datetime.utcnow()

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

    now = datetime.utcnow()

    # Check lockout
    if row.locked_until and row.locked_until > now:
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

    # Simulate password check: password must be non-empty (mock — no real bcrypt)
    if not body.password:
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
    cutoff = datetime.utcnow() - timedelta(days=90)
    dormant = db.query(User).filter(
        User.status == "active",
        User.last_login_at < cutoff,
    ).all()
    deactivated = []
    for user in dormant:
        user.status = "inactive"
        user.deactivated_at = datetime.utcnow()
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

    now = datetime.utcnow()
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
    row.updated_at = datetime.utcnow()

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

    # Validate attendance records exist and are confirmed
    for att_id in body.attendance_ids:
        att = db.query(Attendance).filter(Attendance.attendance_id == att_id).first()
        if not att:
            _422("ATTENDANCE_NOT_FOUND", f"Attendance record {att_id} does not exist.")
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

    now = datetime.utcnow()
    data = body.model_dump()
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
    for att_id in body.attendance_ids:
        att = db.query(Attendance).filter(Attendance.attendance_id == att_id).first()
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

    # Immutable states: submitted and paid
    if row.claim_status in ("submitted", "paid"):
        _422(
            "CLAIM_STATUS_IMMUTABLE",
            f"Claim in status '{row.claim_status}' cannot be modified.",
        )

    _check_optimistic_lock(body.version, row.version, "CLAIM_VERSION_CONFLICT")

    changed_fields = []
    if body.claim_status is not None:
        # draft → submitted is the only forward transition
        if row.claim_status == "draft" and body.claim_status.value == "submitted":
            row.claim_status = "submitted"
            row.submission_date = datetime.utcnow()
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
    row.updated_at = datetime.utcnow()

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
        now = datetime.utcnow()
        if body.administered_time > now:
            _422("ADMIN_TIME_FUTURE", "administered_time cannot be in the future.")
        early_cutoff = body.scheduled_time - timedelta(hours=2)
        if body.administered_time < early_cutoff:
            _422("ADMIN_TIME_TOO_EARLY", "administered_time is more than 2 hours before scheduled_time.")

    now = datetime.utcnow()
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
        _404("MARRecord", mar_id)

    if row.is_controlled_substance:
        priv = SUD_PRIVILEGED_ROLES["mar_record"]
        if caller["role"] not in priv:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "PHI_READ", "MARRecord", row.mar_id,
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
    row.updated_at = datetime.utcnow()

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

    now = datetime.utcnow()
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
            "PHI_READ", "Incident", incident_id,
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
        _404("Incident", incident_id)

    if row.is_sud_related:
        priv = SUD_PRIVILEGED_ROLES["incident"]
        if caller["role"] not in priv:
            _emit_audit(
                db, caller["user_id"], row.tenant_id, caller["session_id"],
                "PHI_READ", "Incident", row.incident_id,
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
    row.updated_at = datetime.utcnow()

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
            "PHI_WRITE", "Incident", inc.incident_id,
            ["status", "regulatory_submission_date"],
            "127.0.0.1", "SUCCESS",
        )
        alerted.append(inc.incident_id)
    db.commit()
    return {"alerted": alerted}
