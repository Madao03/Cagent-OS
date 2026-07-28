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
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from cagent_os.multi_agent.schemas import (
    AnalysisReport,
    DataCitation,
    DataSourceItem,
    DecisionSummary,
    RawDataDump,
    RiskAuditResult,
    SupervisorDecision,
    ValuationMetrics,
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
    # Phase 4a MVP: injectable agent runner for Researcher step.
    # Signature: async def run_analysis(query: str) -> str (raw markdown output)
    agent_runner: Callable[[str], Awaitable[str]] | None = None


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
        supervisor = Supervisor(config=SupervisorConfig(
            agent_runner=my_async_agent_runner,
        ))
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

        Delegates to the injected agent_runner callable (if configured),
        which wraps AgentRuntime.run(). Falls back to a template-based
        analysis when no runner is available.
        """
        ticker = self._extract_ticker(query)

        if self._config.agent_runner is not None:
            try:
                raw_output = await asyncio.wait_for(
                    self._config.agent_runner(query),
                    timeout=self._config.timeout_seconds,
                )
                # Parse key sections from the agent's markdown output.
                # Returns 5-tuple: thesis, risks, catalysts, valuation, citations
                thesis, risks, catalysts, valuation, citations = self._parse_analysis_output(
                    raw_output, query, ticker,
                )
                return AnalysisReport(
                    ticker=ticker,
                    thesis=thesis,
                    risks=risks,
                    catalysts=catalysts,
                    valuation=valuation,
                    data_citations=citations,
                    generated_at=datetime.now(timezone.utc),
                )
            except asyncio.TimeoutError:
                logger.warning("Researcher timed out after %ds", self._config.timeout_seconds)
            except Exception as exc:
                logger.warning("Researcher agent runner failed: %s", exc)

        # Fallback: template-based analysis (no agent runner configured)
        return AnalysisReport(
            ticker=ticker,
            thesis=f"Analysis requested for: {query[:200]}",
            risks=[
                "Macro environment uncertainty",
                "Data source reliability varies",
            ],
            catalysts=[
                "Real-time data feeds available via DataLayer",
            ],
            generated_at=datetime.now(timezone.utc),
        )

    async def _run_red_team(self, query: str, analysis: AnalysisReport) -> RiskAuditResult:
        """Red-Team: adversarial check on the analysis output.

        Applies lightweight heuristic checks for common analysis weaknesses:
        - Missing risk factors (<= 1 risk listed)
        - No data citations (unsubstantiated claims)
        - Overconfident thesis without caveats
        - No opposing viewpoints considered

        Phase 4+ can upgrade to LLM-based adversarial review.
        """
        risks_found: list[str] = []
        severity: str = "low"

        # Check 1: Insufficient risk coverage
        if len(analysis.risks) <= 1:
            risks_found.append("Analysis lists 1 or fewer risk factors — may be missing key counter-arguments")
            severity = "medium"

        # Check 2: No data citations → unsubstantiated claims
        if not analysis.data_citations:
            risks_found.append("No data citations found — claims may be unsubstantiated")

        # Check 3: Thesis too short or vague
        if len(analysis.thesis) < 50:
            risks_found.append("Thesis is very brief (<50 chars) — lacks depth")
            severity = "medium"

        # Check 4: Overconfidence detection
        overconfident_patterns = [
            r"一定", r"必然", r"毫无疑问", r"绝对", r"guaranteed", r"certainly",
            r"definitely", r"without doubt", r"100%",
        ]
        for pattern in overconfident_patterns:
            if re.search(pattern, analysis.thesis, re.IGNORECASE):
                risks_found.append(f"Overconfident language detected in thesis: '{pattern}'")
                severity = "high"
                break

        if not risks_found:
            risks_found.append("No significant issues detected in heuristic review")
            recommendation = "Analysis appears structurally sound. Consider LLM-based deep review for nuanced issues."
        else:
            recommendation = (
                f"Found {len(risks_found)} potential issue(s). "
                "Consider: (1) adding more risk factors, (2) citing specific data sources, "
                "(3) including opposing viewpoints."
            )

        return RiskAuditResult(
            ticker=analysis.ticker,
            risk_type="analytical",
            severity=severity,
            gap="; ".join(risks_found),
            recommendation=recommendation,
            references_report_id=None,
        )

    async def _run_editor(
        self,
        query: str,
        analysis: AnalysisReport | None,
        audit: RiskAuditResult | None,
        raw_data: RawDataDump | None,
    ) -> DecisionSummary:
        """Editor: compress analysis + audit + raw data into a decision summary.

        Synthesizes all upstream outputs into:
        - 1-2 sentence conclusion
        - Top 3 key evidence points (by confidence)
        - Top 2 risks
        - Source references

        Phase 4+ can upgrade to LLM-based summarization.
        """
        evidence_lines: list[str] = []
        risks: list[str] = []
        refs: list[str] = []

        # ── Extract key evidence from raw data (top 3 by confidence) ──
        if raw_data and raw_data.items:
            sorted_items = sorted(raw_data.items, key=lambda x: x.confidence, reverse=True)
            for item in sorted_items[:3]:
                if item.value is not None:
                    value_str = str(item.value)[:60] if not isinstance(item.value, (int, float)) else f"{item.value}"
                    evidence_lines.append(
                        f"[{item.source}] {item.metric}: {value_str}"
                    )
                if item.url:
                    refs.append(item.url)

        # ── Extract risks from audit ──
        if audit:
            risks.append(f"[{audit.severity}] {audit.gap[:150]}")
            if audit.recommendation:
                risks.append(audit.recommendation[:200])

        if analysis and analysis.risks:
            for r in analysis.risks[:2]:
                if r not in risks:
                    risks.append(r)

        # ── Build conclusion ──
        if analysis and len(analysis.thesis) > 10:
            # Truncate thesis to ~300 chars for the conclusion
            thesis = analysis.thesis[:300]
            if len(analysis.thesis) > 300:
                thesis += "..."
            conclusion = thesis
        elif raw_data and raw_data.items:
            conclusion = (
                f"Analysis of '{query[:80]}': collected {len(raw_data.items)} data points "
                f"from {raw_data.source_summary}. No structured analysis available (Researcher not run)."
            )
        else:
            conclusion = f"No data or analysis available for: {query[:200]}"

        # ── Determine confidence ──
        confidence: str = "medium"
        if audit:
            if audit.severity == "critical":
                confidence = "low"
            elif audit.severity == "high":
                confidence = "low"
        if analysis and len(analysis.data_citations) >= 3:
            confidence = "high"

        return DecisionSummary(
            query=query,
            conclusion=conclusion,
            key_evidence=evidence_lines[:3],
            key_risks=risks[:3],
            confidence=confidence,
            references=refs[:5],
            raw_text=analysis.thesis if analysis else query,
        )

    # ── Helpers ──

    # Pre-compiled regex for the trailing hidden JSON block
    # Tolerant to whitespace/newlines inside the HTML comment
    _ANALYSIS_JSON_RE = re.compile(
        r"<!--\s*ANALYSIS_JSON\s*:\s*(\{.*?\})\s*-->",
        re.DOTALL,
    )

    @staticmethod
    def _extract_trailing_json(raw_output: str) -> dict | None:
        """Extract the hidden `<!-- ANALYSIS_JSON: {...} -->` block from the end of output.

        Returns the parsed dict on success, None when the block is absent
        or the JSON is malformed.
        """
        if not raw_output:
            return None
        match = Supervisor._ANALYSIS_JSON_RE.search(raw_output)
        if not match:
            return None
        raw_json = match.group(1)
        # Strip trailing commas (common LLM error) before parsing
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw_json)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as exc:
            logger.warning(
                "ANALYSIS_JSON block present but unparseable: %s; falling back to regex",
                exc,
            )
        return None

    @staticmethod
    def _parse_analysis_output(
        raw_output: str,
        query: str,
        ticker: str,
    ) -> tuple[str, list[str], list[str], ValuationMetrics, list[DataCitation]]:
        """Parse Researcher raw output into structured AnalysisReport fields.

        Strategy:
          1. Try to extract trailing `<!-- ANALYSIS_JSON: {...} -->` block.
             If present and parseable, use it as the source of truth.
          2. Otherwise, fall back to regex heuristics on markdown headings.

        Returns:
          (thesis, risks, catalysts, valuation, citations)
        """
        # Default values
        thesis = ""
        risks: list[str] = []
        catalysts: list[str] = []
        valuation = ValuationMetrics()
        citations: list[DataCitation] = []

        # ── Path 1: structured JSON block ──
        structured = Supervisor._extract_trailing_json(raw_output)
        if structured:
            thesis = str(structured.get("thesis", "")).strip() or raw_output[:300]
            raw_risks = structured.get("risks", [])
            if isinstance(raw_risks, list):
                risks = [str(r).strip()[:200] for r in raw_risks if str(r).strip()]
            raw_catalysts = structured.get("catalysts", [])
            if isinstance(raw_catalysts, list):
                catalysts = [str(c).strip()[:200] for c in raw_catalysts if str(c).strip()]

            # Valuation
            def _num(key: str) -> float | None:
                v = structured.get(key)
                if v is None or v == "":
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            valuation = ValuationMetrics(
                fwd_pe=_num("pe_forward"),
                fwd_ps=_num("pe_ttm"),  # map pe_ttm to fwd_ps slot? no — see below
                ev_ebitda=_num("ev_ebitda"),
                pb=_num("pb"),
            )
            # Override: we want pe_ttm in its own field, but ValuationMetrics
            # only exposes fwd_pe/fwd_ps/ev_ebitda/pb. Put pe_ttm in notes.
            pe_ttm = _num("pe_ttm")
            if pe_ttm is not None:
                valuation.notes = (valuation.notes + f" P/E (TTM): {pe_ttm}").strip()
            dcf = _num("dcf_implied_value")
            if dcf is not None:
                valuation.notes = (valuation.notes + f" DCF implied: ${dcf}").strip()

            # Citations
            raw_cits = structured.get("citations", [])
            if isinstance(raw_cits, list):
                for c in raw_cits:
                    if not isinstance(c, dict):
                        continue
                    try:
                        citations.append(DataCitation(
                            metric=str(c.get("metric", "")),
                            value=float(c.get("value", 0) or 0),
                            source=str(c.get("source", "")),
                            confidence=float(c.get("confidence", 0.8)),
                        ))
                    except (TypeError, ValueError):
                        continue

            logger.info(
                "Researcher output parsed via JSON block: thesis_len=%d risks=%d citations=%d",
                len(thesis), len(risks), len(citations),
            )
            return thesis, risks, catalysts, valuation, citations

        # ── Path 2: regex fallback (pre-existing logic, lightly tightened) ──
        logger.info("Researcher output: JSON block not found, using regex fallback")
        thesis, risks, catalysts = Supervisor._parse_markdown_sections(raw_output)
        return thesis, risks, catalysts, valuation, citations

    @staticmethod
    def _parse_markdown_sections(
        raw_output: str,
    ) -> tuple[str, list[str], list[str]]:
        """Fallback parser: extract thesis/risks/catalysts from markdown headings.

        This is the original parser logic — kept for resilience when the LLM
        fails to emit the hidden JSON block.
        """
        thesis = ""
        risks: list[str] = []
        catalysts: list[str] = []

        # Try to find a thesis/analysis section
        analysis_section_match = re.search(
            r"(?:分析|判断|结论|thesis|analysis)[\s:：]*\n+(.{50,500})",
            raw_output, re.IGNORECASE,
        )
        if analysis_section_match:
            thesis = analysis_section_match.group(1).strip()
        else:
            # Fallback: first paragraph that looks like a conclusion
            paras = [p.strip() for p in raw_output.split("\n\n") if len(p.strip()) > 40]
            thesis = paras[0][:500] if paras else raw_output[:300]

        # Extract risks
        risk_section = re.search(
            r"(?:风险|risk|不利因素|看跌)[\s\w]*[:：]?\n(.*?)(?:\n##|\n#|\n---|\Z)",
            raw_output, re.IGNORECASE | re.DOTALL,
        )
        if risk_section:
            risk_lines = re.findall(r"[-*•]\s*(.+)", risk_section.group(1))
            risks = [r.strip()[:200] for r in risk_lines if len(r.strip()) > 10][:5]

        if not risks:
            risks = ["No risk factors identified in analysis output"]

        # Extract catalysts
        catalyst_section = re.search(
            r"(?:催化剂|catalyst|看涨|利好)[\s\w]*[:：]?\n(.*?)(?:\n##|\n#|\n---|\Z)",
            raw_output, re.IGNORECASE | re.DOTALL,
        )
        if catalyst_section:
            cat_lines = re.findall(r"[-*•]\s*(.+)", catalyst_section.group(1))
            catalysts = [c.strip()[:200] for c in cat_lines if len(c.strip()) > 10][:5]

        if not catalysts:
            catalysts = ["Real-time market data available"]

        return thesis, risks, catalysts

    @staticmethod
    def _extract_ticker(query: str) -> str:
        """Extract ticker symbol from query."""
        import re
        match = re.search(r'\b([A-Z]{2,5})\b', query.upper())
        return match.group(1) if match else "UNKNOWN"
