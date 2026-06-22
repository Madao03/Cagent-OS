"""Agent-to-agent communication schemas.

All cross-agent messages are Pydantic models. No natural-language
negotiation between agents — structured data only.

Stage 0: schema definitions only. Not wired into the runtime yet.
Stage 2+: consumed by Task DAG Scheduler and agent message bus.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Research agent → downstream agents ──

class ValuationMetrics(BaseModel):
    fwd_pe: float | None = None
    fwd_ps: float | None = None
    ev_ebitda: float | None = None
    pb: float | None = None
    notes: str = ""


class DataCitation(BaseModel):
    metric: str
    value: float
    source: str
    confidence: float = Field(ge=0.0, le=1.0)


class AnalysisReport(BaseModel):
    ticker: str
    thesis: str
    valuation: ValuationMetrics = Field(default_factory=ValuationMetrics)
    risks: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    data_citations: list[DataCitation] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Risk audit agent ──

class RiskAuditResult(BaseModel):
    ticker: str
    risk_type: str
    severity: Literal["low", "medium", "high", "critical"]
    gap: str
    recommendation: str
    references_report_id: str | None = None


# ── Counter-narrative agent ──

class CounterNarrative(BaseModel):
    ticker: str
    counter_thesis: str
    evidence: list[str] = Field(default_factory=list)
    trigger_reason: str = ""
    references_report_id: str | None = None
