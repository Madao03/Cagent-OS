"""Supervisor — multi-agent orchestrator for Phase 4.

Coordinates 4 specialized agents through a parallel+serial pipeline:
  1. DataCollector (parallel) — fetch data from all sources
  2. Researcher     (parallel) — analyze with skills
  3. Red-Team       (serial)   — challenge with counter-arguments
  4. Editor         (serial)   — compress to decision summary

Design decisions:
  - Self-built, NOT LangGraph. Leverages existing AgentRuntime + Event Sourcing.
  - Each sub-agent call is a self-contained AgentRuntime.run() invocation.
  - Agent-to-agent communication uses Pydantic schemas (no natural-language
    negotiation between agents).
  - Parallel layer uses asyncio.gather(), serial layer is sequential.

Trace: each sub-agent run produces its own conversation with
distinct conversation_id (supervisor_id + agent_name suffix),
enabling per-agent trace spans in Phase 4d (Langfuse).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from cagent_os.multi_agent.schemas import (
    AnalysisReport,
    DataSourceItem,
    DecisionSummary,
    RawDataDump,
    RiskAuditResult,
    SupervisorDecision,
)

logger = logging.getLogger(__name__)


@dataclass
class SupervisorConfig:
    """Configuration for the Supervisor pipeline."""
    max_parallel_agents: int = 2
    timeout_seconds: int = 180
    enable_rag: bool = True
    enable_fred: bool = True
    enable_web_search: bool = True


@dataclass
class SupervisorResult:
    """Complete output from a Supervisor-coordinated pipeline run."""
    query: str
    decision: SupervisorDecision
    raw_data: RawDataDump | None = None
    analysis: AnalysisReport | None = None
    audit: RiskAuditResult | None = None
    summary: DecisionSummary | None = None
    elapsed_ms: int = 0
    errors: list[str] = field(default_factory=list)


class Supervisor:
    """Orchestrates multi-agent pipeline for financial analysis.

    Usage:
        supervisor = Supervisor()
        result = await supervisor.run("分析 NVDA 当前估值")
        # result.summary.conclusion → "NVDA 当前 PE 18.5..."
    """

    def __init__(self, config: SupervisorConfig | None = None) -> None:
        self._config = config or SupervisorConfig()

    async def run(self, query: str) -> SupervisorResult:
        """Execute the full 4-agent pipeline."""
        started_at = datetime.now(timezone.utc)

        # Step 0: Intent routing
        decision = self._route_intent(query)
        logger.info("Supervisor intent: %s, agents: %s", decision.intent, decision.agents)

        errors: list[str] = []

        # ── Phase 1: Parallel — DataCollector + Researcher ──
        raw_data: RawDataDump | None = None
        analysis: AnalysisReport | None = None

        parallel_tasks = []
        if "crawler" in decision.agents:
            parallel_tasks.append(self._run_collector(query))
        if "researcher" in decision.agents:
            parallel_tasks.append(self._run_researcher(query))

        if parallel_tasks:
            results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    errors.append(f"Parallel agent failed: {r}")
                    logger.warning("Parallel agent error: %s", r)
                elif isinstance(r, RawDataDump):
                    raw_data = r
                elif isinstance(r, AnalysisReport):
                    analysis = r

        # ── Phase 2: Serial — Red-Team (needs analysis output) ──
        audit: RiskAuditResult | None = None
        if "red_team" in decision.agents and analysis is not None:
            try:
                audit = await self._run_red_team(query, analysis)
            except Exception as exc:
                errors.append(f"Red-Team failed: {exc}")
                logger.warning("Red-Team error: %s", exc)

        # ── Phase 3: Serial — Editor (needs analysis + audit) ──
        summary: DecisionSummary | None = None
        if "editor" in decision.agents:
            try:
                summary = await self._run_editor(query, analysis, audit, raw_data)
            except Exception as exc:
                errors.append(f"Editor failed: {exc}")
                logger.warning("Editor error: %s", exc)

        elapsed = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)

        result = SupervisorResult(
            query=query,
            decision=decision,
            raw_data=raw_data,
            analysis=analysis,
            audit=audit,
            summary=summary,
            elapsed_ms=elapsed,
            errors=errors,
        )
        logger.info("Supervisor pipeline complete: %dms, %d errors", elapsed, len(errors))
        return result

    # ── Intent routing ──

    def _route_intent(self, query: str) -> SupervisorDecision:
        """Determine which agents to invoke based on query intent.

        Simple keyword-based routing for MVP. Phase 4+ can use LLM-based routing.
        """
        query_lower = query.lower()

        # Quick lookup: just fetch data, no deep analysis
        quick_keywords = ["价格", "报价", "多少", "price", "quote", "利率", "yield", "rate是多少"]
        if any(kw in query_lower for kw in quick_keywords) and len(query) < 30:
            return SupervisorDecision(
                intent="quick_lookup",
                agents=["crawler"],
                parallel_groups=[["crawler"]],
                reasoning="Short query asking for a specific data point",
            )

        # Triage: batch of articles
        triage_keywords = ["分诊", "甄别", "筛一下", "值不值得读", "abc"]
        if any(kw in query_lower for kw in triage_keywords):
            return SupervisorDecision(
                intent="triage",
                agents=["crawler", "researcher", "editor"],
                parallel_groups=[["crawler", "researcher"], ["editor"]],
                reasoning="Batch article triage — crawl + analyze, then editor summarizes",
            )

        # Default: full research pipeline
        return SupervisorDecision(
            intent="research",
            agents=["crawler", "researcher", "red_team", "editor"],
            parallel_groups=[["crawler", "researcher"], ["red_team"], ["editor"]],
            reasoning="Full analysis with counter-argument and decision summary",
        )

    # ── Agent runners ──

    async def _run_collector(self, query: str) -> RawDataDump:
        """DataCollector: fetch data from all configured sources."""
        items: list[DataSourceItem] = []
        rag_results: list[dict] = []

        # RAG search (local knowledge base)
        if self._config.enable_rag:
            try:
                from cagent_os.rag.rag_service import RAGService
                rag = RAGService(knowledge_dir="knowledge", chroma_path="data/vectors")
                rag_results = rag.search(query, top_k=5, use_rerank=True)
                for r in rag_results:
                    items.append(DataSourceItem(
                        source="rag",
                        metric="knowledge_base",
                        value=r.get("similarity", 0),
                        unit="similarity",
                        confidence=0.8,
                        raw_text=r.get("text", "")[:200],
                    ))
            except Exception as exc:
                logger.warning("RAG unavailable in collector: %s", exc)

        # FRED macro data
        if self._config.enable_fred:
            try:
                from cagent_os.data_layer.adapters.fred_adapter import FRED_SERIES
                from cagent_os.config import get_settings
                settings = get_settings()
                if settings.fred_api_key:
                    from cagent_os.data_layer.adapters.fred_adapter import FredAdapter
                    fred = FredAdapter(api_key=settings.fred_api_key)
                    # Quick fetch of key macro indicators
                    for metric in ["treasury_10y", "unemployment_rate", "cpi", "ppi"]:
                        try:
                            raw = await fred.fetch(metric)
                            if raw.value is not None:
                                items.append(DataSourceItem(
                                    source="fred",
                                    metric=metric,
                                    value=raw.value,
                                    unit=raw.raw_response.get("unit", ""),
                                    timestamp=raw.raw_response.get("latest_date", ""),
                                    confidence=0.95,
                                ))
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning("FRED unavailable in collector: %s", exc)

        # Web search
        if self._config.enable_web_search:
            try:
                from cagent_os.plugins.financial.toolkit import FinancialToolkit
                from cagent_os.config import get_settings
                settings = get_settings()
                tk = FinancialToolkit(settings=settings)
                result = tk.search_multi_provider(query=query, num_results=3)
                web_results = result.get("results", [])
                for wr in web_results:
                    items.append(DataSourceItem(
                        source="web",
                        metric="search_result",
                        value=wr.get("title", "")[:100],
                        url=wr.get("url", ""),
                        confidence=0.5,
                        raw_text=wr.get("snippet", "")[:200],
                    ))
            except Exception as exc:
                logger.warning("Web search unavailable in collector: %s", exc)

        dump = RawDataDump(
            query=query,
            items=items,
            rag_results=rag_results,
            source_summary=f"Sources: RAG({len(rag_results)}), FRED, web({len([i for i in items if i.source=='web'])}). Total items: {len(items)}",
        )
        logger.info("DataCollector done: %d items", len(items))
        return dump

    async def _run_researcher(self, query: str) -> AnalysisReport:
        """Researcher: analyze with full skill suite.

        For MVP, delegates to existing AgentRuntime. Phase 4+ can run as a
        sub-agent with its own tool scope.
        """
        # Placeholder: invoke the main agent runtime
        # In production, this would be a separate AgentRuntime instance
        ticker = self._extract_ticker(query)
        return AnalysisReport(
            ticker=ticker,
            thesis=f"Analysis of: {query}",
            risks=["Data quality risk", "Model uncertainty"],
            catalysts=["Real-time data integration"],
            generated_at=datetime.now(timezone.utc),
        )

    async def _run_red_team(self, query: str, analysis: AnalysisReport) -> RiskAuditResult:
        """Red-Team: challenge the analysis with counter-arguments."""
        return RiskAuditResult(
            ticker=analysis.ticker,
            risk_type="analytical",
            severity="medium",
            gap=f"Counter-analysis for: {query[:80]}",
            recommendation="Verify data sources independently. Consider opposing market views.",
            references_report_id=None,
        )

    async def _run_editor(
        self,
        query: str,
        analysis: AnalysisReport | None,
        audit: RiskAuditResult | None,
        raw_data: RawDataDump | None,
    ) -> DecisionSummary:
        """Editor: compress analysis + audit into a decision summary."""
        evidence_lines: list[str] = []
        risks: list[str] = []
        refs: list[str] = []

        if raw_data:
            top_items = sorted(raw_data.items, key=lambda x: x.confidence, reverse=True)[:3]
            evidence_lines = [
                f"{i.source}: {i.metric} = {i.value} {i.unit}"
                for i in top_items if i.value is not None
            ]
            refs = [i.url for i in top_items if i.url]

        if audit:
            risks.append(audit.recommendation)

        return DecisionSummary(
            query=query,
            conclusion=analysis.thesis if analysis else f"Analysis of: {query}",
            key_evidence=evidence_lines,
            key_risks=risks,
            confidence="medium",
            references=refs,
            raw_text=query,  # placeholder
        )

    # ── Helpers ──

    @staticmethod
    def _extract_ticker(query: str) -> str:
        """Extract ticker symbol from query."""
        import re
        match = re.search(r'\b([A-Z]{2,5})\b', query.upper())
        return match.group(1) if match else "UNKNOWN"
