from __future__ import annotations

from pydantic import BaseModel, Field


class PostMessageRequest(BaseModel):
    content: str
    stream: bool = True
    model: str | None = None  # per-request model override (BYOK quick switcher)


class OneshotRunRequest(BaseModel):
    content: str


class OneshotRunResponse(BaseModel):
    user_id: str
    assistant_content: str
    event_types: list[str] = Field(default_factory=list)


class SupervisorRunRequest(BaseModel):
    """Request body for POST /api/v1/supervisor/run."""
    query: str
    enable_rag: bool = True
    enable_fred: bool = True
    enable_web_search: bool = True
    timeout_seconds: int = 240


class SupervisorRunResponse(BaseModel):
    """Response for POST /api/v1/supervisor/run.

    Returns the full SupervisorResult payload — frontend can render
    analysis / risks / citations / decision summary from one call.
    """
    query: str
    intent: str
    agents: list[str]
    elapsed_ms: int
    errors: list[str] = Field(default_factory=list)
    # Analysis
    ticker: str = ""
    thesis: str = ""
    risks: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    recommendation: str = ""
    confidence: str = "medium"
    # Valuation
    fwd_pe: float | None = None
    fwd_ps: float | None = None
    ev_ebitda: float | None = None
    pb: float | None = None
    valuation_notes: str = ""
    # Citations
    citations: list[dict] = Field(default_factory=list)
    # Raw data
    raw_data_items: list[dict] = Field(default_factory=list)
    source_summary: str = ""
    # Red-team audit
    audit_severity: str = ""
    audit_gap: str = ""
    audit_recommendation: str = ""
    # Editor summary
    summary_conclusion: str = ""
    summary_key_evidence: list[str] = Field(default_factory=list)
    summary_key_risks: list[str] = Field(default_factory=list)
    summary_references: list[str] = Field(default_factory=list)
    summary_confidence: str = "medium"
