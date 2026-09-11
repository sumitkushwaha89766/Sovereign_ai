"""Agent run routes (Architecture.md §5).

Phase 7.6: POST /agent/run now launches the full planner pipeline
(OCR -> task classification -> RAG -> reasoning -> grounding verification
-> docgen -> awaiting_approval) in a background thread so the endpoint
returns immediately with the run ID while the pipeline executes.

GET /agent/run/{id}/status reads the DB row that the background task
updates when each step completes.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.core.audit import record_audit
from app.db.database import SessionLocal, get_db
from app.models.db_models import ApprovalRequest, AgentRun, Document, User
from app.models.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    AgentRunStatusResponse,
    Evidence,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent"])


# ---------------------------------------------------------------------------
# Background pipeline runner
# ---------------------------------------------------------------------------

def _run_pipeline(run_id: int, goal: str, document_id: int | None) -> None:
    """Execute the planner pipeline and write results back to the DB.

    This runs in a thread-pool thread (launched via BackgroundTasks).
    It opens its own DB session so it doesn't share the request session.
    """
    from app.agent.planner import get_planner

    db = SessionLocal()
    try:
        run = db.get(AgentRun, run_id)
        requester = db.get(User, run.user_id) if run and run.user_id else None
        # Resolve document text and disk path
        doc_text = ""
        doc_filename = None
        doc_path = None
        if document_id is not None:
            doc = db.get(Document, document_id)
            if doc:
                doc_text = doc.extracted_text or ""
                doc_filename = doc.filename
                # Locate the file on disk so the planner can re-run extraction
                # if the DB text is absent (e.g. extraction failed at upload time).
                from pathlib import Path
                upload_dir = Path("data/uploads")
                if upload_dir.exists():
                    matches = list(upload_dir.glob(f"{doc.id}_{doc.filename}"))
                    if not matches:
                        matches = list(upload_dir.glob(f"*_{doc.filename}"))
                    doc_path = matches[0] if matches else None

        planner = get_planner()
        result = planner.execute(
            goal=goal,
            document_text=doc_text,
            run_id=run_id,
            document_filename=doc_filename,
            document_path=doc_path,
            requester_name=requester.username if requester else None,
        )

        # Persist results back to AgentRun
        if run:
            run.status = result.status
            run.task_type = "inspection_approval"
            requester = db.get(User, run.user_id) if run.user_id else None
            if result.approval_note is not None:
                result.approval_note["requester_name"] = (
                    requester.username if requester else "[PENDING — requester unavailable]"
                )
            # Serialise full run metadata as JSON in model_used (Text column — no truncation).
            run.model_used = json.dumps({
                "models": result.model_used,
                "steps_completed": result.steps_completed,
                "output_file": result.output_file,
                "verification_flags": [
                    {"claim_type": f.claim_type, "value": f.value, "note": f.note}
                    for f in result.verification_flags
                ],
                # Full RAG evidence — source_file / page / quote / confidence per chunk.
                # This is what populates the frontend evidence panel with real citations.
                "rag_evidence": [
                    {
                        "finding": r.finding,
                        "source_file": r.source_file,
                        "page_number": r.page_number,
                        "exact_quote": r.exact_quote[:300],  # cap for DB size
                        "confidence": round(r.confidence, 3),
                        "doc_type": r.doc_type,
                        "section_title": r.section_title,
                    }
                    for r in result.evidence
                ],
                "error": result.error,
                "approval_note": result.approval_note,
            })
            if result.status == "awaiting_approval":
                existing_approval = (
                    db.query(ApprovalRequest)
                    .filter(ApprovalRequest.agent_run_id == run_id)
                    .first()
                )
                if existing_approval is None:
                    db.add(ApprovalRequest(
                        agent_run_id=run_id,
                        action="Export approval note",
                        status="pending",
                    ))
            db.commit()
            logger.info(
                "AGENT_RUN_UPDATED | run_id=%d | status=%s | flags=%d | rag_chunks=%d | file=%s",
                run_id, result.status, len(result.verification_flags),
                len(result.evidence), result.output_file,
            )
    except Exception as exc:
        logger.error("AGENT_RUN_BG_FAILED | run_id=%d | error=%s", run_id, exc, exc_info=True)
        try:
            run = db.get(AgentRun, run_id)
            if run:
                run.status = "failed"
                run.model_used = json.dumps({"error": str(exc)})
                db.commit()
                record_audit(
                    db,
                    "agent_run_failed",
                    f"Agent run {run_id} failed: {exc}",
                    user_id=run.user_id,
                )
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/agent/run", response_model=AgentRunResponse)
def run_agent(
    payload: AgentRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("engineer")),
) -> AgentRunResponse:
    """Create an AgentRun record and launch the planner pipeline in the background.

    Returns immediately with the run ID; clients poll
    GET /agent/run/{id}/status for progress.
    """
    run = AgentRun(
        user_id=user.id,
        task_type="inspection_approval",
        model_used=None,
        status="in_progress",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    record_audit(
        db,
        "agent_run_started",
        f"{user.username} started agent run {run.id} for document {payload.document_id}",
        user_id=user.id,
    )

    background_tasks.add_task(
        _run_pipeline,
        run_id=run.id,
        goal=payload.goal,
        document_id=payload.document_id,
    )

    logger.info(
        "AGENT_RUN_STARTED | run_id=%d | user=%d | document_id=%s | goal=%.80r",
        run.id, user.id, payload.document_id, payload.goal,
    )
    return AgentRunResponse(agent_run_id=run.id, status=run.status)


@router.get("/agent/run/{run_id}/status", response_model=AgentRunStatusResponse)
def agent_run_status(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentRunStatusResponse:
    """Return the current status of an agent run, including pipeline steps and evidence."""
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    # Parse the JSON blob stored in model_used (populated by the background task)
    meta: dict = {}
    if run.model_used:
        try:
            meta = json.loads(run.model_used)
        except (json.JSONDecodeError, TypeError):
            meta = {}

    steps_completed: list[str] = meta.get("steps_completed") or []
    model_used_map: dict[str, str] = meta.get("models") or {}

    # Build evidence list:
    # 1. Real RAG citations (source / page / quote / confidence) — shown first
    # 2. Grounding verification flags — shown after, labelled [NEEDS REVIEW]
    evidence: list[Evidence] = []

    for chunk in meta.get("rag_evidence") or []:
        evidence.append(Evidence(
            claim=chunk.get("finding", chunk.get("source_file", "retrieved chunk")),
            source=(
                f"{chunk.get('source_file', '?')}"
                f" [{chunk.get('doc_type', '')}]"
                f" conf={chunk.get('confidence', 0):.2f}"
            ),
            page=chunk.get("page_number", 0),
        ))

    for flag in meta.get("verification_flags") or []:
        evidence.append(Evidence(
            claim=f"[NEEDS REVIEW] {flag['claim_type']}: {flag['value']} — {flag.get('note', '')}",
            source="grounding_verifier",
            page=0,
        ))

    approval = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.agent_run_id == run_id)
        .first()
    )
    return AgentRunStatusResponse(
        status=run.status,
        steps_completed=steps_completed,
        model_used=model_used_map,
        evidence=evidence,
        approval_id=approval.id if approval else None,
        approval_status=approval.status if approval else None,
    )
