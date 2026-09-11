"""Pydantic request/response models — the exact API contracts from Architecture.md §5.

Field names and structures match the architecture's request/response examples. Where
a value depends on a later phase (e.g. the generated deliverable path), the field is
kept optional so the wire shape stays stable.
"""

from pydantic import BaseModel


# --- POST /auth/login ---
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    role: str


# --- POST /documents/upload ---
class DocumentUploadResponse(BaseModel):
    document_id: int
    filename: str
    status: str


# --- GET /documents ---
class DocumentListItem(BaseModel):
    document_id: int
    filename: str
    status: str


# --- POST /agent/run ---
class AgentRunRequest(BaseModel):
    goal: str
    document_id: int | None = None


class AgentRunResponse(BaseModel):
    agent_run_id: int
    status: str


# --- GET /agent/run/{id}/status ---
class Evidence(BaseModel):
    claim: str
    source: str
    page: int


class AgentRunStatusResponse(BaseModel):
    status: str
    steps_completed: list[str]
    model_used: dict[str, str]
    evidence: list[Evidence]
    approval_id: int | None = None
    approval_status: str | None = None


# --- POST /approval/{id}/decide ---
class ApprovalDecideRequest(BaseModel):
    decision: str  # "approve" | "reject"
    comment: str | None = None


class ApprovalDecideResponse(BaseModel):
    status: str
    output_file: str | None = None


class ApprovalQueueItem(BaseModel):
    approval_id: int
    agent_run_id: int
    action: str
    status: str
    requested_by: str
    decided_by: str | None = None
    decided_at: str | None = None
    output_file: str | None = None


class ApprovalQueueCounts(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int
    decided: int


class ApprovalQueueResponse(BaseModel):
    items: list[ApprovalQueueItem]
    counts: ApprovalQueueCounts


# --- GET /sovereignty/status ---
class SovereigntyStatusResponse(BaseModel):
    external_calls: int
    internet_status: str
    local_model_calls: int
    documents_processed: int
    sandbox_executions: int
