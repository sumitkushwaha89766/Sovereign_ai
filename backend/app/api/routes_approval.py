"""Approval decision route (Architecture.md §5 contract, §6 — approver role).

A dedicated router for the ``/approval/*`` boundary (maps to the approver role and a pending-approval queue).  The deliverable file is produced by the docgen tool in Phase 7.5 and its path is stored in ``AgentRun.model_used`` (JSON blob, key ``output_file``).  This route reads it so the frontend can offer a download link.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.core.audit import record_audit
from app.db.database import get_db
from app.models.db_models import AgentRun, ApprovalRequest, User
from app.agent.tools.docgen_tool import (
    ApprovalNoteInput,
    EvidenceCitation,
    Finding,
    generate_approval_note_docx,
)
from app.models.schemas import (
    ApprovalDecideRequest,
    ApprovalDecideResponse,
    ApprovalQueueCounts,
    ApprovalQueueItem,
    ApprovalQueueResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["approval"])

_DECISION_TO_STATUS = {"approve": "approved", "reject": "rejected"}


@router.get("/approval/queue", response_model=ApprovalQueueResponse)
def approval_queue(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("approver")),
) -> ApprovalQueueResponse:
    """Return live approval history, with pending items ready for review."""
    requests = db.query(ApprovalRequest).order_by(ApprovalRequest.id.desc()).all()
    items: list[ApprovalQueueItem] = []
    counts = {"total": len(requests), "pending": 0, "approved": 0, "rejected": 0}

    for request in requests:
        status_name = request.status.lower()
        if status_name in counts:
            counts[status_name] += 1
        run = db.get(AgentRun, request.agent_run_id)
        requester = db.get(User, run.user_id) if run and run.user_id else None
        decider = db.get(User, request.decided_by) if request.decided_by else None
        output_file = None
        if run and run.model_used:
            try:
                output_file = json.loads(run.model_used).get("output_file")
            except (TypeError, json.JSONDecodeError):
                output_file = None
        items.append(ApprovalQueueItem(
            approval_id=request.id,
            agent_run_id=request.agent_run_id,
            action=request.action,
            status=status_name,
            requested_by=requester.username if requester else "unknown",
            decided_by=decider.username if decider else None,
            decided_at=request.decided_at.isoformat() if request.decided_at else None,
            output_file=output_file,
        ))

    counts["decided"] = counts["approved"] + counts["rejected"]
    return ApprovalQueueResponse(
        items=items,
        counts=ApprovalQueueCounts(**counts),
    )


@router.post("/approval/{approval_id}/decide", response_model=ApprovalDecideResponse)
def decide_approval(
    approval_id: int,
    payload: ApprovalDecideRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("approver")),
) -> ApprovalDecideResponse:
    new_status = _DECISION_TO_STATUS.get(payload.decision)
    if new_status is None:
        raise HTTPException(
            status_code=422,
            detail="decision must be 'approve' or 'reject'",
        )
    req = db.get(ApprovalRequest, approval_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    req.status = new_status
    req.decided_by = user.id
    req.decided_at = datetime.now(timezone.utc)
    req_comment = payload.comment.strip() if payload.comment else None
    db.commit()

    # Resolve and finalize the approval note from the persisted structured input.
    output_file: str | None = None
    try:
        agent_run = db.get(AgentRun, req.agent_run_id)
        if agent_run and agent_run.model_used:
            meta = json.loads(agent_run.model_used)
            note = meta.get("approval_note")
            if note:
                note["findings"] = [Finding(**item) for item in note.get("findings", [])]
                note["evidence"] = [EvidenceCitation(**item) for item in note.get("evidence", [])]
                note.update({
                    "approval_status": new_status,
                    "approver_name": user.username,
                    "area_engineer_name": user.username,
                    "approval_date": datetime.now(timezone.utc).date().isoformat(),
                    "approval_comment": req_comment,
                    "note_id": f"AN-RUN-{req.agent_run_id}-{new_status.upper()}",
                })
                output_file = str(generate_approval_note_docx(ApprovalNoteInput(**note)))
                meta["output_file"] = output_file
                meta["approval_status"] = new_status
                meta["approver_name"] = user.username
                meta["approval_comment"] = req_comment
                agent_run.model_used = json.dumps(meta)
                agent_run.status = new_status
                db.commit()
            else:
                output_file = meta.get("output_file")
    except Exception as exc:
        logger.warning(
            "APPROVAL_OUTPUT_FILE_LOOKUP_FAILED | approval_id=%d | error=%s",
            approval_id, exc,
        )

    logger.info(
        "APPROVAL_DECIDED | approval_id=%d | decision=%s | user_id=%d | output_file=%s",
        approval_id, new_status, user.id, output_file,
    )
    record_audit(
        db,
        "approval_decision",
        f"{user.username} {new_status} approval {approval_id} for agent run {req.agent_run_id}",
        user_id=user.id,
    )
    return ApprovalDecideResponse(status=new_status, output_file=output_file)
