# TODO

## Phase 1 — Setup Repository and Tools
- [x] Create root repo skeleton: `backend/`, `frontend/`, `.env.example`, `docker-compose.yml`
- [x] `git init`; create `backend/` and `frontend/` folders
- [x] Backend: create `requirements.txt` with Phase 1 dependencies
- [x] Frontend: `npm create vite` (React), `npm install`, add axios/tailwindcss/postcss/autoprefixer/react-router-dom, `npx tailwindcss init -p`
- [x] Verify: `npm run build` succeeds (frontend toolchain)

## Phase 2 — Backend Foundation
- [x] Create `backend/app/main.py` (FastAPI instance)
- [x] Add CORS middleware allowing only localhost frontend origin
- [x] Add `/health` endpoint returning `{"status": "ok"}`
- [x] Create `backend/app/core/config.py`
- [x] Verify: `GET /health` returns 200 + CORS allows only `localhost:5173` (via ASGI TestClient)

## Phase 3 — Database Models
- [x] Create `backend/app/db/database.py` (engine, session, `init_db`)
- [x] Create `backend/app/models/db_models.py` (ORM models)
- [x] Define `users` table
- [x] Define `documents` table
- [x] Define `knowledge_chunks` table
- [x] Define `equipment` table (§4.3 knowledge layer)
- [x] Define `equipment_links` table (§4.3 knowledge layer)
- [x] Define `agent_runs` table
- [x] Define `approval_requests` table
- [x] Define `sovereignty_log` table
- [x] Verify: running app auto-creates `app.db` with all 8 tables

## Phase 4 — Core APIs
- [x] `POST /auth/login`
- [x] `POST /documents/upload`
- [x] `POST /agent/run`
- [x] `GET /agent/run/{id}/status`
- [x] `POST /approval/{id}/decide`
- [x] `GET /sovereignty/status`
- [x] Verify: every endpoint testable via `/docs`

## Phase 5 — Frontend Pages
- [x] Login page (secure-terminal; demo-role quick-fill chips)
- [x] Workbench page (goal box + file upload + documents list + run-steps rail + evidence)
- [x] Evidence/citations panel (sourced / low-confidence / unsourced-reasoning states, §9/§16)
- [x] Approval modal (Approve/Reject + optional comment, §8)
- [x] Sovereignty Dashboard page (dataviz stat tiles; egress-blocked = nominal)
- [x] Verify: all pages render with mock/static data (`npm run build` + `npm run lint`)
- Additions beyond the 5-surface list:
  - [x] Minimal Admin page (users + audit log) — per user choice + §4.1
  - [x] Approvals queue page (approver/admin pending queue, §8)
  - [x] Industrial control-room design system (tokens in `tailwind.config.js` + `index.css`); self-hosted/system fonts only — no CDN/external requests
  - [x] Role-aware AppShell (telemetry bar) + `ProtectedRoute` RBAC (§6)

## Phase 6 — Connect Frontend with Backend
- [x] Replace mock data with real axios calls to backend endpoints (via `src/api/` mock↔live seam; flip `VITE_USE_MOCKS=false`)
- [x] Verify: upload a real PDF, see it in documents list from DB (DB-assigned `document_id`)
- Seam / wiring notes:
  - [x] `src/api/` layer: one module per endpoint, `USE_MOCKS` switch, identical shapes both modes
  - [x] JWT stored on login; axios request interceptor attaches Bearer; 401 → logout
  - [x] Agent run poll loop (no websockets, §4.2); documents list built from upload responses (no `GET /documents` in Phase 4)
  - [x] Live evidence empty until Phase 7 → truthful pending empty state; approvals/admin are mock/demo surfaces (no Phase 4 list/admin endpoints)

## Phase 7 — Add AI/Intelligent Features
- [ ] 7.1 Model serving — install Ollama, pull `llama3.1:8b`, `qwen2.5-coder:7b`, `llava:7b` (or run local model endpoint)
- [x] 7.2 Task Classifier (`agent/task_classifier.py`)
- [x] 7.3 Model Router (`agent/model_router.py`)
- [x] 7.4 RAG pipeline — `rag/ingest.py`, `rag/embed.py`, `rag/retrieve.py`
- [x] 7.5 Tools — `sandbox_tool.py`, `docgen_tool.py`, `document_extractor.py`
- [x] 7.6 Agent Planner (`agent/planner.py`)
- [x] Verify: model routing logs show reasoning model + sandbox execution firing

## Phase 8 — Dashboards and Analytics
- [x] Create `core/network_guard.py` middleware (intercept + log outbound attempts; block non-localhost)
- [x] Build Sovereignty Dashboard from `sovereignty_log` + `agent_runs`
- [ ] Verify: disconnect internet, run full flagship demo end-to-end

## Phase 9 — Testing and Debugging
- [x] Unit tests for `task_classifier`, `model_router`, `retrieve.py`
- [x] Manual end-to-end test script for flagship workflow
- [x] Edge-case tests: corrupted PDF, empty document, ambiguous task type, sandbox timeout
- [ ] Verify: all tests pass; flagship demo runs 3× consecutively
  - [x] Automated suite passes: `pytest` → 39 passed (`backend/tests/`)
  - [ ] Flagship demo 3× consecutively — run `python tests/manual_e2e.py --runs 3` with backend + Ollama live

## Phase 10 — Deployment
- [ ] Write `docker-compose.yml` (services: `backend`, `frontend`, `ollama`, `chromadb`)
- [ ] `docker compose up --build`
- [ ] Verify: fresh machine runs the whole stack with one command

## Phase 11 — SIH Presentation and Demo Preparation
- [ ] Slide deck: problem → solution → architecture → live demo → impact metrics
- [ ] Judge script: "Disconnect the internet. It still works." moment
- [ ] Pre-recorded backup video of full demo
- [ ] One-page architecture diagram
- [ ] Rehearsed Q&A answers
- [ ] Metrics table: manual vs AI-assisted time
- [ ] Verify: full run-through rehearsed ≥2×, timed under demo slot
