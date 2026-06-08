from __future__ import annotations

from collections import defaultdict
import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Any

import jwt
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get("DATABASE_URL", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "resq_service_jwt_secret_2026")
ACCESS_EXPIRE_MINUTES = 30
REFRESH_EXPIRE_DAYS = 30
CORS_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    os.environ.get("FRONTEND_URL", ""),
}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])


class SheetItem(Base):
    __tablename__ = "sheet_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sku: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ServiceJob(Base):
    __tablename__ = "service_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    service_number: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(40))
    customer_email: Mapped[str | None] = mapped_column(String(255))
    google_sheet_row_id: Mapped[str | None] = mapped_column(String(120))
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    current_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    assignee = relationship("User", foreign_keys=[assigned_to])


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    parts_requested_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    date_stamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("ServiceJob", foreign_keys=[job_id])
    employee = relationship("User", foreign_keys=[employee_id])


class PartRequest(Base):
    __tablename__ = "part_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending_approval", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job = relationship("ServiceJob", foreign_keys=[job_id])
    employee = relationship("User", foreign_keys=[employee_id])
    inventory_item = relationship("InventoryItem", foreign_keys=[inventory_item_id])
    approver = relationship("User", foreign_keys=[approved_by])


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("service_jobs.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(30), default="sms", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("ServiceJob", foreign_keys=[job_id])


def _build_engine():
    db_url = DATABASE_URL
    is_mysql = "mysql" in db_url

    if is_mysql:
        # Try to use ca.pem if it exists (local dev), otherwise use ssl=True (Vercel/cloud)
        ssl_ca = ROOT_DIR / "ca.pem"
        if ssl_ca.exists():
            connect_kwargs: dict[str, Any] = {"ssl": {"ca": str(ssl_ca.resolve())}}
        else:
            # Vercel / cloud deployment: trust the server cert
            connect_kwargs = {"ssl": {"check_hostname": False, "verify_mode": 0}}
        return create_engine(
            db_url,
            connect_args=connect_kwargs,
            pool_pre_ping=True,
            pool_recycle=300,
            future=True,
        )
    else:
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            future=True,
        )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = Field(default="employee", pattern="^(employee)$")
    department: str | None = None
    phone: str | None = None


class UserCreateRequest(RegisterRequest):
    role: str = Field(pattern="^(admin|employee)$")


class UserUpdateRequest(BaseModel):
    name: str | None = None
    department: str | None = None
    phone: str | None = None
    status: str | None = None


class ChatMessageCreate(BaseModel):
    senderId: int
    recipientId: int
    text: str = Field(min_length=1)


class SheetCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    assignedTo: int
    assignedBy: int
    priority: str = Field(default="medium", pattern="^(low|medium|high)$")
    status: str = Field(default="open")


class SheetStatusUpdate(BaseModel):
    status: str = Field(pattern="^(open|in-progress|completed)$")


class JobImportRow(BaseModel):
    serviceNumber: str = Field(min_length=1)
    customerName: str = Field(min_length=1)
    customerPhone: str | None = None
    customerEmail: str | None = None
    googleSheetRowId: str | None = None
    assignedTo: int | None = None
    priority: str = Field(default="medium", pattern="^(low|medium|high)$")
    currentStatus: str = Field(default="pending", pattern="^(pending|completed_today|tomorrow|no_install|customer_next_day)$")


class JobNoteCreate(BaseModel):
    noteText: str = Field(min_length=1)
    currentStatus: str | None = Field(default=None, pattern="^(pending|completed_today|tomorrow|no_install|customer_next_day)$")
    partsRequested: list[dict[str, Any]] = Field(default_factory=list)


class PartRequestCreate(BaseModel):
    inventoryItemId: int
    quantity: int = Field(default=1, ge=1)


class JobStatusUpdate(BaseModel):
    currentStatus: str = Field(pattern="^(pending|completed_today|tomorrow|no_install|customer_next_day)$")


class ManagerApprovalUpdate(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class MessageResponse(BaseModel):
    message: str


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def create_access_token(user_id: int) -> str:
    return create_token(str(user_id), "access", timedelta(minutes=ACCESS_EXPIRE_MINUTES))


def create_refresh_token(user_id: int) -> str:
    return create_token(str(user_id), "refresh", timedelta(days=REFRESH_EXPIRE_DAYS))


def decode_token(token: str, token_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if payload.get("type") != token_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    return payload


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def role_label(role: str) -> str:
    return {"admin": "Admin", "manager": "Manager", "employee": "Employee"}.get(role, role)


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "passwordHash": user.password_hash,
        "department": user.department or "",
        "phone": user.phone or "",
        "status": user.status,
        "createdAt": user.created_at.replace(tzinfo=timezone.utc).isoformat() if user.created_at.tzinfo is None else user.created_at.astimezone(timezone.utc).isoformat(),
    }


def activity_to_dict(activity: Activity) -> dict[str, Any]:
    created_at = activity.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)

    return {
        "id": activity.id,
        "type": activity.type,
        "title": activity.title,
        "description": activity.description,
        "createdAt": created_at.isoformat(),
    }


def chat_message_to_dict(message: ChatMessage) -> dict[str, Any]:
    created_at = message.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)

    return {
        "id": message.id,
        "senderId": message.sender_id,
        "recipientId": message.recipient_id,
        "text": message.text,
        "createdAt": created_at.isoformat(),
    }


def sheet_to_dict(item: SheetItem) -> dict[str, Any]:
    created_at = item.created_at
    updated_at = item.updated_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    else:
        updated_at = updated_at.astimezone(timezone.utc)

    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "assignedTo": item.assigned_to,
        "assignedBy": item.assigned_by,
        "priority": item.priority,
        "status": item.status,
        "createdAt": created_at.isoformat(),
        "updatedAt": updated_at.isoformat(),
    }


def inventory_to_dict(item: InventoryItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "sku": item.sku,
        "quantity": item.quantity,
        "createdAt": item.created_at.replace(tzinfo=timezone.utc).isoformat() if item.created_at.tzinfo is None else item.created_at.astimezone(timezone.utc).isoformat(),
    }


def service_job_to_dict(item: ServiceJob) -> dict[str, Any]:
    created_at = item.created_at.replace(tzinfo=timezone.utc) if item.created_at.tzinfo is None else item.created_at.astimezone(timezone.utc)
    updated_at = item.updated_at.replace(tzinfo=timezone.utc) if item.updated_at.tzinfo is None else item.updated_at.astimezone(timezone.utc)
    completed_at = None
    if item.completed_at:
        completed_at = item.completed_at.replace(tzinfo=timezone.utc).isoformat() if item.completed_at.tzinfo is None else item.completed_at.astimezone(timezone.utc).isoformat()
    return {
        "id": item.id,
        "serviceNumber": item.service_number,
        "customerDetails": {
            "name": item.customer_name,
            "phone": item.customer_phone or "",
            "email": item.customer_email or "",
        },
        "googleSheetRowId": item.google_sheet_row_id or "",
        "assignedTo": item.assigned_to,
        "priority": item.priority,
        "currentStatus": item.current_status,
        "createdAt": created_at.isoformat(),
        "updatedAt": updated_at.isoformat(),
        "completedAt": completed_at,
    }


def job_log_to_dict(item: JobLog) -> dict[str, Any]:
    return {
        "id": item.id,
        "jobId": item.job_id,
        "employeeId": item.employee_id,
        "noteText": item.note_text,
        "currentStatus": item.status,
        "partsRequested": json.loads(item.parts_requested_json or "[]"),
        "dateStamp": item.date_stamp.replace(tzinfo=timezone.utc).isoformat() if item.date_stamp.tzinfo is None else item.date_stamp.astimezone(timezone.utc).isoformat(),
    }


def part_request_to_dict(item: PartRequest) -> dict[str, Any]:
    requested_at = item.requested_at.replace(tzinfo=timezone.utc) if item.requested_at.tzinfo is None else item.requested_at.astimezone(timezone.utc)
    approved_at = None
    if item.approved_at:
        approved_at = item.approved_at.replace(tzinfo=timezone.utc).isoformat() if item.approved_at.tzinfo is None else item.approved_at.astimezone(timezone.utc).isoformat()
    return {
        "id": item.id,
        "jobId": item.job_id,
        "employeeId": item.employee_id,
        "inventoryItemId": item.inventory_item_id,
        "inventoryItem": inventory_to_dict(item.inventory_item) if item.inventory_item else None,
        "quantity": item.quantity,
        "status": item.status,
        "requestedAt": requested_at.isoformat(),
        "approvedBy": item.approved_by,
        "approvedAt": approved_at,
    }


def webhook_log_to_dict(item: WebhookLog) -> dict[str, Any]:
    return {
        "id": item.id,
        "jobId": item.job_id,
        "channel": item.channel,
        "message": item.message,
        "status": item.status,
        "payload": json.loads(item.payload_json or "{}"),
        "createdAt": item.created_at.replace(tzinfo=timezone.utc).isoformat() if item.created_at.tzinfo is None else item.created_at.astimezone(timezone.utc).isoformat(),
    }


def write_activity(db: Session, type_: str, title: str, description: str) -> None:
    # Skip noisy low-value activity types
    if type_ in {"inventory", "approval"}:
        return
    db.add(Activity(type=type_, title=title, description=description))
    # Auto-purge: keep only the latest 10 activity records
    all_ids = db.scalars(
        select(Activity.id).order_by(Activity.created_at.desc())
    ).all()
    if len(all_ids) > 10:
        old_ids = all_ids[10:]
        db.execute(
            Activity.__table__.delete().where(Activity.id.in_(old_ids))
        )


def add_seed_data(db: Session) -> None:
    if db.scalar(select(func.count(User.id))) > 0:
        return

    seeded_users = [
        User(
            name="Sravan Kumar",
            email="kunta.sravan11111@gmail.com",
            role="manager",
            password_hash=hash_password("Sravankumar@123"),
            department="Management",
            phone="",
            status="active",
        ),
        User(
            name="System Admin",
            email="admin@company.com",
            role="admin",
            password_hash=hash_password("admin123"),
            department="Operations",
            phone="+1 555 0100",
            status="active",
        ),
        User(
            name="John Employee",
            email="employee@company.com",
            role="employee",
            password_hash=hash_password("employee123"),
            department="Support",
            phone="+1 555 0102",
            status="active",
        ),
    ]

    db.add_all(seeded_users)
    db.flush()

    db.add_all(
        [
            SheetItem(
                title="Weekly attendance sheet",
                description="Attendance data for the current week.",
                assigned_to=seeded_users[2].id,
                assigned_by=seeded_users[1].id,
                priority="high",
                status="in-progress",
            ),
            SheetItem(
                title="Payroll verification sheet",
                description="Cross-check payroll entries with employee records.",
                assigned_to=seeded_users[2].id,
                assigned_by=seeded_users[0].id,
                priority="medium",
                status="open",
            ),
        ]
    )

    db.add_all(
        [
            InventoryItem(name="Fuse kit", sku="PART-FUSE-01", quantity=24),
            InventoryItem(name="Control board", sku="PART-CTRL-02", quantity=8),
            InventoryItem(name="Fan motor", sku="PART-FAN-03", quantity=5),
        ]
    )

    db.add_all(
        [
            ServiceJob(
                service_number="SV-10001",
                customer_name="Jordan Blake",
                customer_phone="+1 555 2001",
                customer_email="jordan@example.com",
                google_sheet_row_id="row-1",
                assigned_to=seeded_users[2].id,
                priority="high",
                current_status="pending",
            ),
            ServiceJob(
                service_number="SV-10002",
                customer_name="Avery Cole",
                customer_phone="+1 555 2002",
                customer_email="avery@example.com",
                google_sheet_row_id="row-2",
                assigned_to=seeded_users[2].id,
                priority="medium",
                current_status="tomorrow",
            ),
        ]
    )

    write_activity(db, "seed", "Workspace seeded", "Default manager, admin, and employee accounts created.")


def build_chat_snapshot(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(ChatMessage).order_by(ChatMessage.created_at.asc())).all()
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)

    for message in rows:
        key = tuple(sorted((message.sender_id, message.recipient_id)))
        grouped[key].append(chat_message_to_dict(message))

    chats: list[dict[str, Any]] = []
    for key, messages in grouped.items():
        updated_at = messages[-1]["createdAt"] if messages else datetime.now(timezone.utc).isoformat()
        chats.append(
            {
                "id": f"{key[0]}:{key[1]}",
                "participants": list(key),
                "messages": messages,
                "updatedAt": updated_at,
            }
        )

    chats.sort(key=lambda item: item["updatedAt"], reverse=True)
    return chats


def build_state_snapshot(db: Session) -> dict[str, Any]:
    users = [user_to_dict(user) for user in db.scalars(select(User).order_by(User.created_at.asc())).all()]
    sheets = [sheet_to_dict(item) for item in db.scalars(select(SheetItem).order_by(SheetItem.created_at.desc())).all()]
    activities = [activity_to_dict(item) for item in db.scalars(select(Activity).order_by(Activity.created_at.desc())).all()]
    chats = build_chat_snapshot(db)
    service_jobs = [service_job_to_dict(item) for item in db.scalars(select(ServiceJob).order_by(ServiceJob.created_at.desc())).all()]
    job_logs = [job_log_to_dict(item) for item in db.scalars(select(JobLog).order_by(JobLog.date_stamp.desc())).all()]
    inventory = [inventory_to_dict(item) for item in db.scalars(select(InventoryItem).order_by(InventoryItem.name.asc())).all()]
    part_requests = [part_request_to_dict(item) for item in db.scalars(select(PartRequest).order_by(PartRequest.requested_at.desc())).all()]
    webhook_logs = [webhook_log_to_dict(item) for item in db.scalars(select(WebhookLog).order_by(WebhookLog.created_at.desc())).all()]
    metrics = manager_metrics(db)
    return {
        "users": users,
        "chats": chats,
        "sheetItems": sheets,
        "activities": activities,
        "serviceJobs": service_jobs,
        "jobLogs": job_logs,
        "inventory": inventory,
        "partRequests": part_requests,
        "webhookLogs": webhook_logs,
        "managerMetrics": metrics,
    }


def service_job_history(db: Session, job_id: int) -> dict[str, Any]:
    job = db.get(ServiceJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service job not found")
    logs = db.scalars(select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.date_stamp.asc())).all()
    requests = db.scalars(select(PartRequest).where(PartRequest.job_id == job_id).order_by(PartRequest.requested_at.asc())).all()
    return {
        "job": service_job_to_dict(job),
        "logs": [job_log_to_dict(item) for item in logs],
        "partRequests": [part_request_to_dict(item) for item in requests],
    }


def emit_customer_webhook(db: Session, job: ServiceJob, channel: str = "sms") -> WebhookLog:
    message = f"Your service for Job #{job.service_number} is complete and ready for pickup!"
    payload = {
        "jobId": job.id,
        "serviceNumber": job.service_number,
        "customer": job.customer_name,
        "message": message,
        "channel": channel,
    }
    status_text = "queued"
    callback_url = os.getenv("CUSTOMER_WEBHOOK_URL", "").strip()
    if callback_url:
        try:
            response = httpx.post(callback_url, json=payload, timeout=10.0)
            status_text = "sent" if response.is_success else f"http_{response.status_code}"
        except Exception as exc:  # pragma: no cover - network depends on env
            status_text = "failed"
            payload["error"] = str(exc)
    webhook = WebhookLog(job_id=job.id, channel=channel, message=message, status=status_text, payload_json=json.dumps(payload))
    db.add(webhook)
    return webhook


def manager_metrics(db: Session) -> dict[str, Any]:
    jobs = db.scalars(select(ServiceJob)).all()
    logs = db.scalars(select(JobLog)).all()
    users = db.scalars(select(User)).all()
    part_requests = db.scalars(select(PartRequest)).all()
    by_employee: dict[int, dict[str, Any]] = defaultdict(lambda: {"completedToday": 0, "pendingBacklog": 0, "resolutionSeconds": []})

    for job in jobs:
        if job.assigned_to:
            entry = by_employee[job.assigned_to]
            if job.current_status == "completed_today":
                entry["completedToday"] += 1
            if job.current_status == "pending":
                entry["pendingBacklog"] += 1
            if job.completed_at:
                resolution = (job.completed_at - job.created_at).total_seconds()
                entry["resolutionSeconds"].append(resolution)

    employee_metrics = []
    for user in users:
        if user.role != "employee":
            continue
        entry = by_employee[user.id]
        avg_resolution = sum(entry["resolutionSeconds"]) / len(entry["resolutionSeconds"]) if entry["resolutionSeconds"] else 0
        employee_metrics.append(
            {
                "employeeId": user.id,
                "employeeName": user.name,
                "jobsCompletedToday": entry["completedToday"],
                "pendingBacklog": entry["pendingBacklog"],
                "averageResolutionMinutes": round(avg_resolution / 60, 1) if avg_resolution else 0,
            }
        )

    return {
        "pendingJobs": sum(1 for job in jobs if job.current_status == "pending"),
        "completedToday": sum(1 for job in jobs if job.current_status == "completed_today"),
        "scheduledTomorrow": sum(1 for job in jobs if job.current_status == "tomorrow"),
        "pendingPartRequests": sum(1 for request in part_requests if request.status == "pending_approval"),
        "employeeMetrics": employee_metrics,
        "recentLogs": [job_log_to_dict(item) for item in logs[-10:]],
    }


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = authorization.removeprefix("Bearer ").strip()
    claims = decode_token(token, "access")
    user = db.get(User, int(claims["sub"]))
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return user


def ensure_role(current_user: User, allowed: set[str]) -> None:
    if current_user.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def create_user_record(db: Session, payload: RegisterRequest | UserCreateRequest, created_by: User | None = None) -> User:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    if created_by and created_by.role == "manager" and payload.role not in {"admin", "employee"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers can only create admin or employee accounts")

    user = User(
        name=payload.name.strip(),
        email=email,
        role=payload.role,
        password_hash=hash_password(payload.password),
        department=(payload.department or "").strip() or None,
        phone=(payload.phone or "").strip() or None,
        status="active",
    )
    db.add(user)
    db.flush()
    if created_by:
        write_activity(db, "create", "User created", f"{created_by.name} created {user.name} as {role_label(user.role)}.")
    else:
        write_activity(db, "register", "User registered", f"{user.name} joined as {role_label(user.role)}.")
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    return user


app = FastAPI(title="Employee Management API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        add_seed_data(db)
        db.commit()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state")
def get_state(db: Session = Depends(get_db)) -> dict[str, Any]:
    return build_state_snapshot(db)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(db, payload.email, payload.password)
    write_activity(db, "login", "User logged in", f"{user.name} signed in.")
    db.commit()
    db.refresh(user)
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=user_to_dict(user),
    )


@app.post("/api/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = create_user_record(db, payload)
    db.commit()
    db.refresh(user)
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=user_to_dict(user),
    )


@app.post("/api/auth/bootstrap-manager", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def bootstrap_manager(db: Session = Depends(get_db)) -> dict[str, Any]:
    existing = db.scalar(select(User).where(User.role == "manager"))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Manager already exists")

    user = User(
        name="Bootstrap Manager",
        email="bootstrap-manager@company.com",
        role="manager",
        password_hash=hash_password("manager123"),
        department="Operations",
        phone="+1 555 0199",
        status="active",
    )
    db.add(user)
    db.flush()
    write_activity(db, "seed", "Manager bootstrapped", "A manager account was bootstrapped for the workspace.")
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


@app.post("/api/auth/refresh")
def refresh(payload: dict[str, str], db: Session = Depends(get_db)) -> dict[str, str]:
    token = payload.get("refresh_token", "")
    claims = decode_token(token, "refresh")
    user = db.get(User, int(claims["sub"]))
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@app.post("/api/auth/logout")
def logout(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MessageResponse:
    write_activity(db, "logout", "User logged out", f"{current_user.name} signed out.")
    db.commit()
    return MessageResponse(message="Logged out")


@app.get("/api/users/me")
def me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return user_to_dict(current_user)


@app.get("/api/users")
def list_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    users = db.scalars(select(User).order_by(User.created_at.asc())).all()
    if current_user.role == "employee":
        users = [user for user in users if user.id == current_user.id]
    elif current_user.role == "manager":
        users = [user for user in users if user.role in {"manager", "employee"}]
    return [user_to_dict(user) for user in users]


@app.post("/api/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_role(current_user, {"manager"})
    user = create_user_record(db, payload, created_by=current_user)
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


@app.get("/api/users/{user_id}")
def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if current_user.role == "employee" and current_user.id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return user_to_dict(user)


@app.put("/api/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if current_user.role == "employee" and current_user.id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    if payload.name is not None:
        user.name = payload.name.strip()
    if payload.department is not None:
        user.department = payload.department.strip() or None
    if payload.phone is not None:
        user.phone = payload.phone.strip() or None
    if payload.status is not None and current_user.role in {"admin", "manager"}:
        user.status = payload.status

    write_activity(db, "update", "User updated", f"{current_user.name} updated {user.name}.")
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


@app.delete("/api/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    ensure_role(current_user, {"admin", "manager"})
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    db.delete(user)
    write_activity(db, "delete", "User deleted", f"{current_user.name} deleted {user.name}.")
    db.commit()
    return MessageResponse(message="User deleted")


@app.get("/api/inventory")
def list_inventory(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    ensure_role(current_user, {"admin", "manager", "employee"})
    return [inventory_to_dict(item) for item in db.scalars(select(InventoryItem).order_by(InventoryItem.name.asc())).all()]


@app.get("/api/jobs")
def list_jobs(
    serviceNumber: str | None = None,
    fromDate: str | None = None,
    toDate: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    jobs = db.scalars(select(ServiceJob).order_by(ServiceJob.updated_at.desc())).all()
    if current_user.role == "employee":
        jobs = [job for job in jobs if job.assigned_to == current_user.id]
    if serviceNumber:
        jobs = [job for job in jobs if serviceNumber.lower() in job.service_number.lower()]
    if fromDate:
        start = datetime.fromisoformat(fromDate)
        jobs = [job for job in jobs if job.created_at >= start]
    if toDate:
        end = datetime.fromisoformat(toDate)
        jobs = [job for job in jobs if job.created_at <= end]
    return [service_job_to_dict(job) for job in jobs]


@app.get("/api/jobs/search/{service_number}")
def search_job(
    service_number: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = db.scalar(select(ServiceJob).where(ServiceJob.service_number == service_number))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service job not found")
    if current_user.role == "employee" and job.assigned_to != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return service_job_history(db, job.id)


@app.post("/api/jobs/import-sheet")
def import_sheet_jobs(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_role(current_user, {"admin", "manager"})
    rows = payload.get("rows", [])
    created = 0
    updated = 0
    for row in rows:
        parsed = JobImportRow.model_validate(row)
        job = db.scalar(select(ServiceJob).where(ServiceJob.service_number == parsed.serviceNumber))
        if job:
            job.customer_name = parsed.customerName
            job.customer_phone = parsed.customerPhone
            job.customer_email = parsed.customerEmail
            job.google_sheet_row_id = parsed.googleSheetRowId
            job.assigned_to = parsed.assignedTo
            job.priority = parsed.priority
            job.current_status = parsed.currentStatus
            updated += 1
        else:
            db.add(
                ServiceJob(
                    service_number=parsed.serviceNumber,
                    customer_name=parsed.customerName,
                    customer_phone=parsed.customerPhone,
                    customer_email=parsed.customerEmail,
                    google_sheet_row_id=parsed.googleSheetRowId,
                    assigned_to=parsed.assignedTo,
                    priority=parsed.priority,
                    current_status=parsed.currentStatus,
                )
            )
            created += 1
    write_activity(db, "sheet", "Google Sheet imported", f"{current_user.name} imported {created + updated} service rows.")
    db.commit()
    return {"created": created, "updated": updated}


@app.get("/api/jobs/{job_id}/history")
def get_job_history(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = db.get(ServiceJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service job not found")
    if current_user.role == "employee" and job.assigned_to != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return service_job_history(db, job_id)


@app.post("/api/jobs/{job_id}/notes")
def add_job_note(
    job_id: int,
    payload: JobNoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = db.get(ServiceJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service job not found")
    if current_user.role == "employee" and job.assigned_to != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    if payload.currentStatus:
        job.current_status = payload.currentStatus
        if payload.currentStatus == "completed_today" and not job.completed_at:
            job.completed_at = datetime.utcnow()
            emit_customer_webhook(db, job, channel="sms")
            write_activity(db, "notify", "Customer update queued", f"Customer notification prepared for Job #{job.service_number}.")

    log = JobLog(
        job_id=job.id,
        employee_id=current_user.id,
        note_text=payload.noteText,
        status=payload.currentStatus or job.current_status,
        parts_requested_json=json.dumps(payload.partsRequested or []),
    )
    db.add(log)
    write_activity(db, "note", "Job note added", f"{current_user.name} added a worklog note to Job #{job.service_number}.")
    db.commit()
    db.refresh(job)
    db.refresh(log)
    return {"job": service_job_to_dict(job), "log": job_log_to_dict(log)}


@app.post("/api/jobs/{job_id}/parts-request")
def request_part(
    job_id: int,
    payload: PartRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = db.get(ServiceJob, job_id)
    inventory_item = db.get(InventoryItem, payload.inventoryItemId)
    if not job or not inventory_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job or inventory item not found")
    if current_user.role == "employee" and job.assigned_to != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    request = PartRequest(
        job_id=job.id,
        employee_id=current_user.id,
        inventory_item_id=inventory_item.id,
        quantity=payload.quantity,
        status="pending_approval",
    )
    db.add(request)
    write_activity(db, "approval", "Part requested", f"{current_user.name} requested {payload.quantity} x {inventory_item.name} for Job #{job.service_number}.")
    db.commit()
    db.refresh(request)
    return part_request_to_dict(request)


@app.patch("/api/jobs/{job_id}/status")
def update_job_status(
    job_id: int,
    payload: JobStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = db.get(ServiceJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service job not found")
    if current_user.role == "employee" and job.assigned_to != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    previous = job.current_status
    job.current_status = payload.currentStatus
    if payload.currentStatus == "completed_today" and not job.completed_at:
        job.completed_at = datetime.utcnow()
    if previous != payload.currentStatus:
        write_activity(db, "status", "Job status changed", f"Job #{job.service_number} marked as {payload.currentStatus}.")
    if payload.currentStatus == "completed_today":
        emit_customer_webhook(db, job, channel="whatsapp")
    db.commit()
    db.refresh(job)
    return service_job_to_dict(job)


@app.get("/api/manager/approvals")
def manager_approvals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    ensure_role(current_user, {"admin", "manager"})
    requests = db.scalars(select(PartRequest).where(PartRequest.status == "pending_approval").order_by(PartRequest.requested_at.desc())).all()
    return [part_request_to_dict(item) for item in requests]


@app.post("/api/manager/approvals/{request_id}")
def decide_approval(
    request_id: int,
    payload: ManagerApprovalUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_role(current_user, {"admin", "manager"})
    request = db.get(PartRequest, request_id)
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part request not found")
    request.status = payload.decision
    request.approved_by = current_user.id
    request.approved_at = datetime.utcnow()
    write_activity(db, "approval", f"Part request {payload.decision}", f"{current_user.name} {payload.decision} part request #{request.id}.")
    db.commit()
    db.refresh(request)
    return part_request_to_dict(request)


@app.get("/api/manager/metrics")
def get_manager_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_role(current_user, {"admin", "manager"})
    return manager_metrics(db)


@app.get("/api/manager/webhooks")
def get_webhook_logs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    ensure_role(current_user, {"admin", "manager"})
    return [webhook_log_to_dict(item) for item in db.scalars(select(WebhookLog).order_by(WebhookLog.created_at.desc())).all()]


@app.get("/api/chat/messages")
def get_chat_messages(
    currentUserId: int,
    otherUserId: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    if current_user.id != currentUserId and current_user.role == "employee":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    messages = db.scalars(
        select(ChatMessage)
        .where(
            ((ChatMessage.sender_id == currentUserId) & (ChatMessage.recipient_id == otherUserId))
            | ((ChatMessage.sender_id == otherUserId) & (ChatMessage.recipient_id == currentUserId))
        )
        .order_by(ChatMessage.created_at.asc())
    ).all()
    return [chat_message_to_dict(message) for message in messages]


@app.post("/api/chat/messages")
def send_chat_message(
    payload: ChatMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if current_user.id != payload.senderId:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot send messages as another user")

    message = ChatMessage(
        sender_id=payload.senderId,
        recipient_id=payload.recipientId,
        text=payload.text.strip(),
    )
    db.add(message)
    sender = db.get(User, payload.senderId)
    recipient = db.get(User, payload.recipientId)
    write_activity(
        db,
        "message",
        "Chat updated",
        f"{sender.name if sender else payload.senderId} sent a message to {recipient.name if recipient else payload.recipientId}.",
    )
    db.commit()
    db.refresh(message)
    return chat_message_to_dict(message)


@app.get("/api/sheets")
def list_sheets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    items = db.scalars(select(SheetItem).order_by(SheetItem.created_at.desc())).all()
    if current_user.role == "employee":
        items = [item for item in items if item.assigned_to == current_user.id]
    return [sheet_to_dict(item) for item in items]


@app.post("/api/sheets", status_code=status.HTTP_201_CREATED)
def create_sheet(
    payload: SheetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_role(current_user, {"admin", "manager"})
    item = SheetItem(
        title=payload.title.strip(),
        description=payload.description.strip(),
        assigned_to=payload.assignedTo,
        assigned_by=payload.assignedBy,
        priority=payload.priority,
        status=payload.status or "open",
    )
    db.add(item)
    assignee = db.get(User, payload.assignedTo)
    write_activity(db, "sheet", "Sheet data assigned", f"{item.title} assigned to {assignee.name if assignee else 'an employee'}.")
    db.commit()
    db.refresh(item)
    return sheet_to_dict(item)


@app.patch("/api/sheets/{sheet_id}/status")
def update_sheet_status(
    sheet_id: int,
    payload: SheetStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    item = db.get(SheetItem, sheet_id)
    if not item:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sheet item not found")
    if current_user.role == "employee" and item.assigned_to != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    item.status = payload.status
    item.updated_at = datetime.utcnow()
    write_activity(db, "sheet", "Sheet status updated", f"{item.title} marked as {payload.status}.")
    db.commit()
    db.refresh(item)
    return sheet_to_dict(item)


@app.get("/api/dashboard/summary")
def dashboard_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    users = db.scalars(select(User)).all()
    chats = db.scalar(select(func.count(ChatMessage.id))) or 0
    sheets = db.scalars(select(SheetItem)).all()
    assigned = [sheet for sheet in sheets if sheet.assigned_to == current_user.id]
    return {
        "totalUsers": len(users),
        "admins": sum(1 for user in users if user.role == "admin"),
        "managers": sum(1 for user in users if user.role == "manager"),
        "employees": sum(1 for user in users if user.role == "employee"),
        "chats": int(chats),
        "openSheets": sum(1 for sheet in sheets if sheet.status != "completed"),
        "assignedToCurrent": len(assigned),
        "completedForCurrent": sum(1 for sheet in assigned if sheet.status == "completed"),
    }


# ── Google Sheet URL fetch (uses Google Sheets API v4 with API key) ───────────

class SheetFetchRequest(BaseModel):
    url: str = Field(min_length=10)
    apiKey: str | None = None  # falls back to env VITE_SHEETS_API_KEY


def _extract_sheet_id(url: str) -> str:
    """Pull spreadsheet ID out of a Google Sheets URL."""
    import re
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Google Sheet URL — could not find spreadsheet ID")
    return match.group(1)


@app.post("/api/google-sheet/fetch")
def fetch_google_sheet(
    payload: SheetFetchRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch rows from a public Google Sheet using the Sheets REST API v4."""
    ensure_role(current_user, {"admin", "manager"})
    spreadsheet_id = _extract_sheet_id(payload.url)
    api_key = (payload.apiKey or os.getenv("VITE_SHEETS_API_KEY", "")).strip()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google Sheets API key is required. Add VITE_SHEETS_API_KEY to .env")

    sheets_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/Sheet1"
        f"?key={api_key}"
    )
    try:
        resp = httpx.get(sheets_url, timeout=15.0)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to reach Google Sheets API: {exc}") from exc

    if resp.status_code == 403:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Google Sheets API returned 403. Make sure the sheet is public ('Anyone with the link can view') and the API key is valid.")
    if not resp.is_success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Google Sheets API error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    values: list[list[str]] = data.get("values", [])
    if not values:
        return {"headers": [], "rows": [], "spreadsheetId": spreadsheet_id}

    raw_headers = [str(h).strip() for h in values[0]]
    rows = []
    for row_index, row in enumerate(values[1:], start=2):
        padded = row + [""] * (len(raw_headers) - len(row))
        rows.append({raw_headers[i]: padded[i] for i in range(len(raw_headers))} | {"_row": row_index})

    return {"headers": raw_headers, "rows": rows, "spreadsheetId": spreadsheet_id}


# ── Inventory management (manager/admin) ──────────────────────────────────────

class InventoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    sku: str = Field(min_length=1, max_length=80)
    quantity: int = Field(default=0, ge=0)


class InventoryUpdateRequest(BaseModel):
    name: str | None = None
    quantity: int | None = Field(default=None, ge=0)


@app.post("/api/inventory", status_code=status.HTTP_201_CREATED)
def create_inventory_item(
    payload: InventoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_role(current_user, {"admin", "manager"})
    existing = db.scalar(select(InventoryItem).where(InventoryItem.sku == payload.sku))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An inventory item with this SKU already exists")
    item = InventoryItem(name=payload.name.strip(), sku=payload.sku.strip().upper(), quantity=payload.quantity)
    db.add(item)
    write_activity(db, "inventory", "Inventory item added", f"{current_user.name} added {item.name} (SKU: {item.sku}).")
    db.commit()
    db.refresh(item)
    return inventory_to_dict(item)


@app.put("/api/inventory/{item_id}")
def update_inventory_item(
    item_id: int,
    payload: InventoryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_role(current_user, {"admin", "manager"})
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.quantity is not None:
        item.quantity = payload.quantity
    write_activity(db, "inventory", "Inventory updated", f"{current_user.name} updated {item.name}.")
    db.commit()
    db.refresh(item)
    return inventory_to_dict(item)


@app.delete("/api/inventory/{item_id}")
def delete_inventory_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    ensure_role(current_user, {"admin", "manager"})
    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    db.delete(item)
    write_activity(db, "inventory", "Inventory item removed", f"{current_user.name} removed {item.name}.")
    db.commit()
    return MessageResponse(message="Inventory item deleted")


# ── Job management (manager/admin can edit/delete any job) ────────────────────

class JobUpdateRequest(BaseModel):
    serviceNumber: str | None = None
    customerName: str | None = None
    customerPhone: str | None = None
    customerEmail: str | None = None
    assignedTo: int | None = None
    priority: str | None = Field(default=None, pattern="^(low|medium|high)$")
    currentStatus: str | None = Field(default=None, pattern="^(pending|completed_today|tomorrow|no_install|customer_next_day)$")


@app.put("/api/jobs/{job_id}")
def update_job(
    job_id: int,
    payload: JobUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_role(current_user, {"admin", "manager"})
    job = db.get(ServiceJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service job not found")
    if payload.serviceNumber is not None:
        job.service_number = payload.serviceNumber.strip()
    if payload.customerName is not None:
        job.customer_name = payload.customerName.strip()
    if payload.customerPhone is not None:
        job.customer_phone = payload.customerPhone.strip() or None
    if payload.customerEmail is not None:
        job.customer_email = payload.customerEmail.strip() or None
    if payload.assignedTo is not None:
        job.assigned_to = payload.assignedTo
    if payload.priority is not None:
        job.priority = payload.priority
    if payload.currentStatus is not None:
        job.current_status = payload.currentStatus
        if payload.currentStatus == "completed_today" and not job.completed_at:
            job.completed_at = datetime.utcnow()
            emit_customer_webhook(db, job, channel="sms")
    write_activity(db, "update", "Job updated", f"{current_user.name} updated Job #{job.service_number}.")
    db.commit()
    db.refresh(job)
    return service_job_to_dict(job)


@app.delete("/api/jobs/{job_id}")
def delete_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    ensure_role(current_user, {"admin", "manager"})
    job = db.get(ServiceJob, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service job not found")
    service_num = job.service_number
    db.delete(job)
    write_activity(db, "delete", "Job deleted", f"{current_user.name} deleted Job #{service_num}.")
    db.commit()
    return MessageResponse(message="Service job deleted")
