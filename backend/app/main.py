"""FastAPI application entry point (Phase 2 — backend foundation).

Thin composition layer per Architecture.md §4.2: this module wires middleware
and mounts the API routers. Business logic lives under ``app/agent``,
``app/rag``, ``app/agent/tools`` and ``app/db``.

Phase 8: the network guard is installed at process startup (before any library
can make an outbound call) and the isolation probe runs in the background.

Run locally from the ``backend/`` directory:

    uvicorn app.main:app --reload
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

# Configure root logger so that background-thread logs from the planner,
# RAG pipeline, and agent tools appear in the uvicorn console.
# Without this call the logging module discards all non-WARNING messages
# from threads spawned by BackgroundTasks.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
)
# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("multipart").setLevel(logging.WARNING)

# Enforce fully offline mode for HuggingFace/transformers so they don't even
# attempt to check for config updates when the model weights are already cached locally.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Phase 8: Install the socket-level network guard BEFORE any other import
# so no library can sneak in an outbound call during module initialisation.
from app.core.network_guard import NetworkGuardMiddleware, install_socket_guard, probe_isolation
install_socket_guard()

from app.api import (
    routes_admin,
    routes_agent,
    routes_approval,
    routes_auth,
    routes_documents,
    routes_sovereignty,
)
from app.core.config import settings
from app.core.security import seed_demo_users
from app.db.database import SessionLocal, init_db

logger = logging.getLogger(__name__)


async def _startup_ingest() -> None:
    """Populate the vector store from sample_docs/ if the collection is empty.

    Runs in a thread pool so the heavy sentence-transformers load does not
    block the asyncio event loop during server startup.
    """
    try:
        from app.rag.embed import collection_count, ingest_and_embed
        count = await asyncio.to_thread(collection_count)
        if count > 0:
            logger.info("RAG_STARTUP_SKIP | reason=collection already has %d chunks", count)
            return
        logger.info("RAG_STARTUP_INGEST | reason=collection is empty, ingesting sample_docs/")
        stored = await asyncio.to_thread(ingest_and_embed)
        logger.info("RAG_STARTUP_INGEST_DONE | chunks_stored=%d", stored)
    except Exception as exc:
        # Non-fatal: the server still starts; RAG just won't work until fixed.
        logger.error(
            "RAG_STARTUP_INGEST_FAILED | error=%s | "
            "hint=ensure sentence-transformers and chromadb are installed",
            exc,
        )


async def _startup_probe() -> None:
    """Run the isolation probe once at startup and log the result.

    Fires as a background asyncio task so it does not delay server startup.
    The result is stored in sovereignty_log; the dashboard reads it from there.
    """
    try:
        probe_result = await asyncio.to_thread(probe_isolation)
        if probe_result["all_blocked"]:
            logger.info("SOVEREIGNTY_PROBE_STARTUP | result=all_cloud_endpoints_blocked | SOVEREIGN=True")
        else:
            logger.warning(
                "SOVEREIGNTY_PROBE_STARTUP | result=some_endpoints_reachable | "
                "SOVEREIGN=False | details=%s",
                [r for r in probe_result["results"] if r["reachable"]],
            )
    except Exception as exc:
        logger.error("SOVEREIGNTY_PROBE_STARTUP_FAILED | error=%s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):

    # 1. Auto-create the schema and seed local demo users on startup
    #    (Architecture.md §4.3 schema, §6 RBAC; SQLite MVP).
    init_db()
    db = SessionLocal()
    try:
        seed_demo_users(db)
    finally:
        db.close()

    # 2. Populate the RAG vector store from sample_docs/ (Phase 7.4).
    #    Runs only if the collection is empty — idempotent across restarts.
    await _startup_ingest()

    # 3. Run the isolation probe in the background (Phase 8).
    #    Does not block startup. Result is stored in sovereignty_log so the
    #    dashboard can show "last verified: <timestamp>" with proof.
    asyncio.create_task(_startup_probe())

    yield


app = FastAPI(title="Sovereign AI Workbench", version="0.1.0", lifespan=lifespan)

# Mount the API routers (Architecture.md §5 contracts).
app.include_router(routes_auth.router)
app.include_router(routes_admin.router)
app.include_router(routes_documents.router)
app.include_router(routes_agent.router)
app.include_router(routes_approval.router)
app.include_router(routes_sovereignty.router)

# Phase 8: NetworkGuardMiddleware stamps X-Sovereignty on every HTTP response.
# The socket-level hook (installed at module top) does the actual blocking.
app.add_middleware(NetworkGuardMiddleware)

# CORS is restricted to the local frontend origin(s) only. No wildcard: the backend
# must not accept cross-origin traffic from anywhere off the local machine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: always returns 200 with a static payload."""
    return {"status": "ok"}
