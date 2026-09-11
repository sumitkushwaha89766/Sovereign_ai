"""Best-effort audit event writer for the local admin audit view."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.db_models import SovereigntyLog

logger = logging.getLogger(__name__)


def record_audit(
    db: Session,
    event_type: str,
    detail: str,
    *,
    user_id: int | None = None,
    external_attempt_blocked: bool = False,
) -> None:
    """Record a local workflow event without allowing audit failure to break work."""
    try:
        db.add(SovereigntyLog(
            event_type=event_type,
            detail=detail,
            destination=f"user:{user_id}" if user_id is not None else None,
            external_attempt_blocked=external_attempt_blocked,
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("AUDIT_LOG_FAILED | event=%s | error=%s", event_type, exc)