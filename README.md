# SovereignAI Workbench

A **sovereign, on-premise, agentic AI workbench** for confidential industrial workflows. Runs entirely offline — no cloud LLM APIs, no cloud OCR, no cloud embeddings. Every AI call stays on your machine.

> **SIH (Smart India Hackathon) demo** — flagship use-case: scanned inspection report → local OCR → SOP retrieval → reasoning → approval note DOCX, with a sovereignty dashboard proving zero external calls.

---

## What it does

```
Scanned inspection report
  → Local OCR (Tesseract + gemma4:e2b vision fallback)
  → Structured field extraction (local model)
  → SOP retrieval from local ChromaDB vector store
  → Reasoning + grounding verification (local model)
  → Approval Note DOCX generated
  → Sovereignty Dashboard: zero external calls proven
```

---

## Prerequisites (install before cloning)

| Tool | Version | Purpose |
|------|---------|---------|
| **Python** | 3.11 or 3.12 | Backend |
| **Node.js** | 18+ | Frontend |
| **Ollama** | latest | Local model serving |
| **Tesseract OCR** | 5.x | Stage-1 OCR |
| **Git** | any | Cloning the repo |

### Install Ollama
- Windows / macOS: https://ollama.com/download
- After install, run: `ollama serve` (keep this terminal open)

### Install Tesseract (Windows)
Download installer from: https://github.com/UB-Mannheim/tesseract/wiki  
Default install path: `C:\Program Files\Tesseract-OCR\tesseract.exe`  
Add that folder to your system `PATH`.

### Pull the required model
```bash
ollama pull gemma4:e2b
```
> This is ~1.5 GB. On stronger hardware you can switch to `llama3.1:8b` later — just edit `backend/app/agent/model_registry.yaml`.

---

## Setup (new machine, step by step)

### 1 — Clone the repo
```bash
git clone https://github.com/<your-username>/SovereignAI.git
cd SovereignAI
```

### 2 — Backend setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

# Install all Python dependencies
pip install -r requirements.txt
```

#### Create your `.env` file
```bash
# Copy the example
copy ..\..\.env.example .env        # Windows
# cp ../../.env.example .env        # macOS/Linux
```

Open `.env` and set `JWT_SECRET` to a random value:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Paste the output as the value of `JWT_SECRET` in `.env`.

Your `.env` should look like:
```
DATABASE_URL=sqlite:///./data/app.db
VECTOR_DB_PATH=./data/vector_store
OLLAMA_HOST=http://localhost:11434
JWT_SECRET=<paste-your-generated-secret-here>
SANDBOX_TIMEOUT_SECONDS=30
ALLOWED_ORIGINS=http://localhost:5173
```

#### Create required data directories
```bash
# From the backend/ directory
mkdir data\uploads data\deliverables data\vector_store   # Windows
# mkdir -p data/uploads data/deliverables data/vector_store  # macOS/Linux
```

### 3 — Frontend setup

```bash
# From the repo root (SovereignAI/)
cd frontend
npm install
```

Create `frontend/.env` (Vite does not load `.env.example` automatically):
```env
VITE_API_BASE=http://localhost:8000
VITE_USE_MOCKS=false
```

---

## Running the workbench

You need **three terminals** running simultaneously.

### Terminal 1 — Ollama (model server)
```bash
ollama serve
```
Keep this running. It loads `gemma4:e2b` on the first request (~10s warm-up).

### Terminal 2 — Backend (FastAPI)
```bash
cd SovereignAI/backend
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
uvicorn app.main:app --reload --port 8000
```

On first startup you will see:
```
RAG_STARTUP_INGEST | reason=collection is empty, ingesting sample_docs/
RAG_STARTUP_INGEST_DONE | chunks_stored=45
Application startup complete.
```
This builds the local ChromaDB vector store from `backend/data/sample_docs/` — happens **once** on first run.

### Terminal 3 — Frontend (Vite dev server)
```bash
cd SovereignAI/frontend
npm run dev
```

Open: **http://localhost:5173**

---

## Running the flagship demo

### Login
| Username | Password | Role |
|----------|----------|------|
| `engineer1` | `demo1234` | Engineer (can run agent) |
| `approver1` | `demo1234` | Approver |
| `admin1` | `demo1234` | Admin |

### Step-by-step demo
1. **Login** as `engineer1 / demo1234`
2. **Upload** `backend/data/sample_docs/inspection_report_892.txt`
3. **Goal** is pre-filled: *"Assess pump P-204 vibration against SOP-17 and draft an approval note."*
4. Click **Run agent**
5. Watch the pipeline steps fill in (takes 30–90 s — local model inference)
6. When status shows **Awaiting approval**, click **Review & approve**
7. Click **Approve** — the DOCX is generated in `backend/data/deliverables/<run_id>/`

### What to look for in backend logs
```
PLANNER_STEP | step=ocr_extraction
PLANNER_STEP | step=task_classification
PLANNER_STEP | step=rag_sop_retrieval
PLANNER_STEP | step=reasoning_draft
PLANNER_GROUNDING_OK | all claims verified in retrieved chunks
AGENT_RUN_UPDATED | status=awaiting_approval | flags=0
```

### Sovereignty dashboard
Go to **Sovereignty** tab — you'll see all local model calls logged and zero external API calls.

---

## Project structure

```
SovereignAI/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   │   ├── planner.py          # Main orchestration pipeline
│   │   │   ├── model_router.py     # Routes tasks to local models via Ollama
│   │   │   ├── task_classifier.py  # Classifies task type
│   │   │   ├── model_registry.yaml # ← Change model names here (not in code)
│   │   │   └── tools/
│   │   │       ├── docgen_tool.py      # DOCX generation
│   │   │       ├── document_extractor.py # OCR pipeline
│   │   │       └── sandbox_tool.py     # Sandboxed code execution
│   │   ├── api/
│   │   │   ├── routes_agent.py     # POST /agent/run, GET /agent/run/{id}/status
│   │   │   ├── routes_auth.py      # POST /auth/login
│   │   │   ├── routes_documents.py # POST /documents/upload, GET /documents
│   │   │   ├── routes_approval.py  # POST /approval/{id}/decide
│   │   │   └── routes_sovereignty.py # GET /sovereignty/status
│   │   ├── core/
│   │   │   ├── network_guard.py    # Socket-level outbound block + logging
│   │   │   └── security.py         # JWT auth, RBAC
│   │   ├── rag/
│   │   │   ├── ingest.py           # Parse + chunk documents
│   │   │   ├── embed.py            # ChromaDB + sentence-transformers
│   │   │   └── retrieve.py         # Semantic search
│   │   ├── db/                     # SQLAlchemy models + SQLite setup
│   │   └── main.py                 # FastAPI app + startup hooks
│   ├── data/
│   │   └── sample_docs/            # Demo knowledge base (committed to git)
│   │       ├── inspection_report_892.txt   # Main demo document
│   │       ├── SOP-17-vibration-limits.txt
│   │       ├── SOP-22-valve-inspection.txt
│   │       └── approval_note_A*.txt
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── WorkbenchPage.jsx   # Main demo surface
│   │   │   └── SovereigntyDashboard.jsx
│   │   ├── hooks/
│   │   │   └── useWorkbenchState.js # localStorage persistence
│   │   ├── components/             # UI components
│   │   └── api/                    # Backend API clients
│   └── package.json
├── .env.example                    # Copy → .env and set JWT_SECRET
├── Architecture.md                 # Full architecture reference
├── Plan.md                         # Phase-by-phase build plan
└── TODO.md                         # Task tracking
```

---

## Switching models (upgrading hardware)

All model routing is controlled by one file: `backend/app/agent/model_registry.yaml`

```yaml
models:
  reasoning:
    name: gemma4:e2b          # Change to llama3.1:8b on stronger hardware
  coding:
    name: gemma4:e2b          # Change to qwen2.5-coder:7b
  vision:
    name: gemma4:e2b          # Change to llava:7b or qwen2-vl:7b
  embedding:
    name: all-MiniLM-L6-v2   # Permanent — no change needed
```

Pull new models with `ollama pull <model-name>`, then edit the YAML. No code changes required.

---

## Troubleshooting

### Backend won't start — `ModuleNotFoundError`
```bash
cd backend
venv\Scripts\activate
pip install -r requirements.txt
```

### `No module named 'chromadb'` or `sentence_transformers`
Same fix — run `pip install -r requirements.txt` inside the activated venv.

### Ollama model not found
```bash
ollama pull gemma4:e2b
```

### `HuggingFace` network errors at startup
The embedding model (all-MiniLM-L6-v2) must be cached locally. On first run with internet available it downloads automatically. After that it runs fully offline. The server sets `HF_HUB_OFFLINE=1` automatically after first download.

### Frontend shows "Failed to fetch" errors
- Confirm backend is running on port 8000: `curl http://localhost:8000/health`
- Confirm the frontend is on 5173 and `ALLOWED_ORIGINS` in `.env` matches

### Agent run stuck on "Running…" for more than 2 minutes
- Check backend terminal for `PLANNER_STEP` logs — if absent, Ollama is not responding
- Run `curl http://localhost:11434/api/tags` to verify Ollama is alive
- First inference on a cold start takes 30–90 s — this is normal

### Tesseract not found
Set the path explicitly in your environment:
```bash
# Windows — add to .env or set as system env var
TESSDATA_PREFIX=C:\Program Files\Tesseract-OCR\tessdata
```
Or add `C:\Program Files\Tesseract-OCR` to your system `PATH`.

---

## Data persistence

All workbench state (uploaded documents, run results, evidence, pipeline steps) is stored in **two places**:

| Storage | What | Persists |
|---------|------|---------|
| `backend/data/app.db` | Documents, agent runs, approvals, sovereignty log | Server restarts ✓ |
| Browser `localStorage` | Documents list, last run status, evidence | Page reloads ✓ |

---

## Security notes (pre-production)

- Set a strong `JWT_SECRET` in `.env` — never use the default `change-me-locally`
- The network guard blocks outbound connections at the socket level during agent runs
- All uploaded documents are sandboxed — content is treated as data, never as instructions
- Admin password should be changed from `admin/admin` before any shared deployment

---

## Phase roadmap (TODO.md)

- ✅ Phase 1–4: Auth, DB, API contracts, Frontend shell
- ✅ Phase 5–6: Security hardening, sovereignty network guard
- ✅ Phase 7: Full AI pipeline (OCR → RAG → reasoning → docgen)
- ✅ Phase 8: Sovereignty dashboard
- ⬜ Phase 9: Docker Compose one-command deployment
- ⬜ Phase 10: Kubernetes (future roadmap)
