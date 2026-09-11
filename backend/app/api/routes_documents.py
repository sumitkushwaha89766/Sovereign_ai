"""Document upload route (Architecture.md §5).

Uploaded files are treated as untrusted input:
  - filename is reduced to its basename (no path traversal)
  - file contents are stored on disk under data/uploads/
  - text is extracted locally using document_extractor.py (Tesseract → vision
    model fallback) and stored in Document.extracted_text so the planner can
    read it without re-running OCR on every agent run.

Phase 7: extraction is now live. Status is "extracted" on success, "uploaded"
if extraction produced no text (fallback — agent will retry in-pipeline).

Phase 7.4 (upload→embed fix): after extraction succeeds, the extracted text is
immediately chunked and embedded into ChromaDB so the grounding verifier can
find the claims in retrieved chunks during the agent pipeline.
"""

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.core.audit import record_audit
from app.db.database import get_db
from app.models.db_models import Document, User
from app.models.schemas import DocumentListItem, DocumentUploadResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])

UPLOAD_DIR = os.path.join("data", "uploads")


@router.get("/documents", response_model=list[DocumentListItem])
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("engineer")),
) -> list[DocumentListItem]:
    """Return the 20 most recently uploaded documents for the current user's session.

    Used by the frontend to rebuild the document list after a page reload
    without requiring the user to re-upload everything.
    """
    docs = (
        db.query(Document)
        .order_by(Document.id.desc())
        .limit(20)
        .all()
    )
    return [
        DocumentListItem(
            document_id=d.id,
            filename=d.filename,
            status="extracted" if d.extracted_text else "uploaded",
        )
        for d in docs
    ]


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("engineer")),
) -> DocumentUploadResponse:
    """Upload a document, save it to disk, extract its text, and embed it.

    Extraction uses Tesseract OCR (Stage 1) with an automatic fallback to
    the vision model (Stage 2) for handwriting / diagrams that Tesseract
    cannot parse.  See document_extractor.py for the full strategy.

    After extraction the text is chunked and embedded into ChromaDB so that
    subsequent agent runs can retrieve it via semantic search and the grounding
    verifier can confirm extracted claims against the source document.
    """
    from app.agent.tools.document_extractor import extract_text

    safe_name = os.path.basename(file.filename or "upload.bin")
    doc_type = os.path.splitext(safe_name)[1].lstrip(".").lower() or None

    # Read file bytes once — used for both disk storage and extraction.
    file_bytes = await file.read()

    # Persist the DB record first so we have a document_id.
    doc = Document(filename=safe_name, doc_type=doc_type, extracted_text=None)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    record_audit(
        db,
        "document_upload",
        f"{user.username} uploaded {safe_name} as document {doc.id}",
        user_id=user.id,
    )

    # Write to disk (untrusted data; stored by document_id prefix to avoid collisions).
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    disk_path = os.path.join(UPLOAD_DIR, f"{doc.id}_{safe_name}")
    with open(disk_path, "wb") as out:
        out.write(file_bytes)

    # Extract text locally (Tesseract → vision fallback).
    extraction_status = "uploaded"
    extracted_text: str | None = None
    try:
        result = extract_text(file_bytes, safe_name)
        if result.full_text:
            extracted_text = result.full_text
            doc.extracted_text = extracted_text
            db.commit()
            extraction_status = "extracted"
            logger.info(
                "UPLOAD_EXTRACTED | doc_id=%d | file=%s | method=%s | "
                "chars=%d | vision_pages=%d",
                doc.id, safe_name, result.primary_method,
                result.total_chars, result.vision_fallback_pages,
            )
        else:
            logger.warning(
                "UPLOAD_EXTRACT_EMPTY | doc_id=%d | file=%s | error=%s | "
                "hint=agent will retry OCR in-pipeline",
                doc.id, safe_name, result.error,
            )
    except Exception as exc:
        # Non-fatal: the document is stored; the planner will attempt extraction.
        logger.error(
            "UPLOAD_EXTRACT_FAILED | doc_id=%d | file=%s | error=%s",
            doc.id, safe_name, exc,
        )

    # -------------------------------------------------------------------------
    # Embed into ChromaDB (Phase 7.4 upload→embed fix).
    # Runs in a background thread so it doesn't block the HTTP response.
    # Non-fatal: if embedding fails the document is still usable via SQLite.
    # -------------------------------------------------------------------------
    if extracted_text:
        async def _embed_in_background() -> None:
            try:
                from app.rag.ingest import ingest_text
                from app.rag.embed import add_chunks
                chunks = await asyncio.to_thread(ingest_text, extracted_text, safe_name)
                if chunks:
                    stored = await asyncio.to_thread(add_chunks, chunks)
                    logger.info(
                        "UPLOAD_EMBED_DONE | doc_id=%d | file=%s | chunks=%d | stored=%d",
                        doc.id, safe_name, len(chunks), stored,
                    )
                else:
                    logger.warning(
                        "UPLOAD_EMBED_EMPTY | doc_id=%d | file=%s | reason=no chunks produced",
                        doc.id, safe_name,
                    )
            except Exception as embed_exc:
                logger.error(
                    "UPLOAD_EMBED_FAILED | doc_id=%d | file=%s | error=%s | "
                    "hint=agent grounding may flag claims as unverified",
                    doc.id, safe_name, embed_exc,
                )

        asyncio.create_task(_embed_in_background())

    return DocumentUploadResponse(
        document_id=doc.id,
        filename=safe_name,
        status=extraction_status,
    )

