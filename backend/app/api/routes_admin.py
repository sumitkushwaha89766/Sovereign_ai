"""Admin-only user and audit views for the live workbench."""

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.database import get_db
from app.models.db_models import SovereigntyLog, User

router = APIRouter(tags=["admin"])


@router.get("/admin/users")
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> list[dict]:
    users = db.execute(select(User).order_by(User.username)).scalars().all()
    return [
        {"username": item.username, "role": item.role, "status": "active"}
        for item in users
    ]


@router.get("/admin/audit")
def list_audit_log(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> list[dict]:
    rows = db.execute(
        select(SovereigntyLog)
        .order_by(desc(SovereigntyLog.timestamp), desc(SovereigntyLog.id))
        .limit(200)
    ).scalars().all()
    return [
        {
            "id": row.id,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "event_type": row.event_type,
            "detail": row.detail or "",
            "destination": row.destination,
            "external_attempt_blocked": row.external_attempt_blocked,
        }
        for row in rows
    ]