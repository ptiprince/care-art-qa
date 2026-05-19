from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import List, Optional
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from database import Base, engine, get_db
import models
from models import (
    Attendance, AttendanceCreate, AttendanceResponse,
    Claim, ClaimCreate, ClaimResponse,
    Incident, IncidentCreate, IncidentResponse,
    MARRecord, MARRecordCreate, MARRecordResponse,
    Participant, ParticipantCreate, ParticipantResponse,
    User, UserCreate, UserResponse,
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


def _409(error_code: str, message: str):
    raise HTTPException(status_code=409, detail={"error_code": error_code, "message": message})


def _404(entity: str, id_: str):
    raise HTTPException(status_code=404, detail={"error_code": "NOT_FOUND", "message": f"{entity} {id_} not found."})


def _403(message: str):
    raise HTTPException(status_code=403, detail={"error_code": "FORBIDDEN", "message": message})


def _422(error_code: str, message: str):
    raise HTTPException(status_code=422, detail={"error_code": error_code, "message": message})


def _gen_claim_ref(payer_type: str) -> str:
    prefix = "MCD" if payer_type == "medicaid" else "MCR"
    today = date.today().strftime("%Y%m%d")
    return f"{prefix}-{today}-{str(uuid.uuid4())[:8].upper()}"


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ─── Participants ─────────────────────────────────────────────────────────────

@app.post("/participants", response_model=ParticipantResponse, status_code=201, tags=["participants"])
def create_participant(body: ParticipantCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(row)
    return ParticipantResponse.model_validate(row)


@app.get("/participants/{participant_id}", response_model=ParticipantResponse, tags=["participants"])
def get_participant(participant_id: str, db: Session = Depends(get_db)):
    row = db.query(Participant).filter(Participant.participant_id == participant_id).first()
    if not row:
        _404("Participant", participant_id)
    return ParticipantResponse.model_validate(row)


@app.get("/participants", response_model=List[ParticipantResponse], tags=["participants"])
def list_participants(
    tenant_id: str = Query(...),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Participant)
        .filter(Participant.tenant_id == tenant_id, Participant.is_deleted.is_(False))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [ParticipantResponse.model_validate(r) for r in rows]


# ─── Users ────────────────────────────────────────────────────────────────────

@app.post("/users", response_model=UserResponse, status_code=201, tags=["users"])
def create_user(body: UserCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(row)
    return UserResponse.model_validate(row)


@app.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
def get_user(user_id: str, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
):
    q = db.query(User).filter(User.tenant_id == tenant_id)
    if role:
        q = q.filter(User.role == role)
    rows = q.offset(offset).limit(limit).all()
    return [UserResponse.model_validate(r) for r in rows]


# ─── Attendance ───────────────────────────────────────────────────────────────

@app.post("/attendance", response_model=AttendanceResponse, status_code=201, tags=["attendance"])
def create_attendance(body: AttendanceCreate, db: Session = Depends(get_db)):
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

    now = datetime.utcnow()
    row = Attendance(
        attendance_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **body.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return AttendanceResponse.model_validate(row)


@app.get("/attendance/{attendance_id}", response_model=AttendanceResponse, tags=["attendance"])
def get_attendance(attendance_id: str, db: Session = Depends(get_db)):
    row = db.query(Attendance).filter(Attendance.attendance_id == attendance_id).first()
    if not row:
        _404("Attendance", attendance_id)
    return AttendanceResponse.model_validate(row)


@app.get("/attendance", response_model=List[AttendanceResponse], tags=["attendance"])
def list_attendance(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Attendance).filter(Attendance.tenant_id == tenant_id)
    if participant_id:
        q = q.filter(Attendance.participant_id == participant_id)
    if status:
        q = q.filter(Attendance.status == status)
    rows = q.offset(offset).limit(limit).all()
    return [AttendanceResponse.model_validate(r) for r in rows]


# ─── Claims ───────────────────────────────────────────────────────────────────

@app.post("/claims", response_model=ClaimResponse, status_code=201, tags=["claims"])
def create_claim(body: ClaimCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(row)
    return ClaimResponse.model_validate(row)


@app.get("/claims/{claim_id}", response_model=ClaimResponse, tags=["claims"])
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    row = db.query(Claim).filter(Claim.claim_id == claim_id).first()
    if not row:
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
    db: Session = Depends(get_db),
):
    q = db.query(Claim).filter(Claim.tenant_id == tenant_id)
    if participant_id:
        q = q.filter(Claim.participant_id == participant_id)
    if claim_status:
        q = q.filter(Claim.claim_status == claim_status)
    if payer_type:
        q = q.filter(Claim.payer_type == payer_type)
    rows = q.offset(offset).limit(limit).all()
    return [ClaimResponse.model_validate(r) for r in rows]


# ─── MAR Records ──────────────────────────────────────────────────────────────

@app.post("/mar-records", response_model=MARRecordResponse, status_code=201, tags=["mar-records"])
def create_mar_record(body: MARRecordCreate, db: Session = Depends(get_db)):
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

    now = datetime.utcnow()
    row = MARRecord(
        mar_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
        **body.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return MARRecordResponse.model_validate(row)


@app.get("/mar-records/{mar_id}", response_model=MARRecordResponse, tags=["mar-records"])
def get_mar_record(mar_id: str, db: Session = Depends(get_db)):
    row = db.query(MARRecord).filter(MARRecord.mar_id == mar_id).first()
    if not row:
        _404("MARRecord", mar_id)
    return MARRecordResponse.model_validate(row)


@app.get("/mar-records", response_model=List[MARRecordResponse], tags=["mar-records"])
def list_mar_records(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(MARRecord).filter(MARRecord.tenant_id == tenant_id)
    if participant_id:
        q = q.filter(MARRecord.participant_id == participant_id)
    if status:
        q = q.filter(MARRecord.status == status)
    rows = q.offset(offset).limit(limit).all()
    return [MARRecordResponse.model_validate(r) for r in rows]


# ─── Incidents ────────────────────────────────────────────────────────────────

@app.post("/incidents", response_model=IncidentResponse, status_code=201, tags=["incidents"])
def create_incident(body: IncidentCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(row)
    return IncidentResponse.model_validate(row)


@app.get("/incidents/{incident_id}", response_model=IncidentResponse, tags=["incidents"])
def get_incident(incident_id: str, db: Session = Depends(get_db)):
    row = db.query(Incident).filter(Incident.incident_id == incident_id).first()
    if not row:
        _404("Incident", incident_id)
    return IncidentResponse.model_validate(row)


@app.get("/incidents", response_model=List[IncidentResponse], tags=["incidents"])
def list_incidents(
    tenant_id: str = Query(...),
    participant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Incident).filter(Incident.tenant_id == tenant_id)
    if participant_id:
        q = q.filter(Incident.participant_id == participant_id)
    if status:
        q = q.filter(Incident.status == status)
    if severity:
        q = q.filter(Incident.severity == severity)
    rows = q.offset(offset).limit(limit).all()
    return [IncidentResponse.model_validate(r) for r in rows]
