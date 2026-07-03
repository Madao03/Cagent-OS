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


# ── Data Collector agent → Researcher ──

class DataSourceItem(BaseModel):
    """One data point from a single source."""
    source: str           # "FRED" | "jin10" | "yfinance" | "rag" | "web" | "fin-skill"
    metric: str           # e.g. "CPI YoY", "BTC price", "NVDA PE"
    value: str | float | None = None
    unit: str = ""        # "%", "USD", "BTC" etc.
    timestamp: str = ""   # ISO 8601, when was this data observed
    url: str = ""         # source URL if applicable
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)  # 1.0 = high confidence
    raw_text: str = ""    # original text from source (for traceability)


class RawDataDump(BaseModel):
    """DataCollector output: cleaned, deduplicated, confidence-annotated data."""
    query: str
    items: list[DataSourceItem] = Field(default_factory=list)
    rag_results: list[dict] = Field(default_factory=list)  # from financial.rag.search
    source_summary: str = ""    # e.g. "3 sources: FRED(5 items), web(3), rag(2)"
    collected_at: datetime = Field(default_factory=datetime.utcnow)


# ── Editor Agent output ──

class DecisionSummary(BaseModel):
    """Editor output: 500-char decision summary."""
    query: str
    conclusion: str                        # 1-2 sentence verdict
    key_evidence: list[str] = Field(default_factory=list)   # top 3 data points
    key_risks: list[str] = Field(default_factory=list)       # top 2 risks
    confidence: Literal["high", "medium", "low"] = "medium"
    references: list[str] = Field(default_factory=list)     # source citations
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    raw_text: str = ""                    # full text before compression


# ── Supervisor routing ──

class SupervisorDecision(BaseModel):
    """Supervisor routing: which agents to invoke, in what order."""
    intent: str = ""                       # "research" | "quick_lookup" | "triage"
    agents: list[str] = Field(default_factory=list)  # ordered agent names
    parallel_groups: list[list[str]] = Field(default_factory=list)  # [["crawler","researcher"], ["red_team"], ["editor"]]
    reasoning: str = ""                    # why this routing plan


# ── Counter-narrative agent ──

class CounterNarrative(BaseModel):
    ticker: str
    counter_thesis: str
    evidence: list[str] = Field(default_factory=list)
    trigger_reason: str = ""
    references_report_id: str | None = None
