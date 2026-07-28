"""Fact Registry — per-turn registry of facts returned by tools.

Each tool return value is decomposed into individual facts at the field level
(not the call level). Every fact gets a stable ID assigned at registration time,
so downstream consumers (prompt, post-processor, trace) can reference facts
without guessing which tool produced which number.

Design principles:
  - fact_id assigned at tool return time, NOT at post-processing time
  - Registration granularity is field-level (revenue, net_income, etc.
    from a single edgar.facts call each become separate facts)
  - Registry is per-turn (conversation turn), persisted to trace
  - Fact values are normalized for matching (see normalizer.py in P0-b)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── period_type domain ──────────────────────────────────────────
# All adapters MUST use one of these three values.
# Do NOT introduce synonyms (ytd, accumulated, half_year, etc.) —
# the registry normalizes on these three strings.

PERIOD_TYPE_FISCAL_YEAR = "fiscal_year"   # 全年 (EDGAR, A-share 年报)
PERIOD_TYPE_QUARTER = "quarter"            # 单季 (A-share 差分值也归这里)
PERIOD_TYPE_CUMULATIVE = "cumulative"      # ★ A-share 特有: 半年报/三季报的累计口径

PERIOD_TYPES = frozenset({
    PERIOD_TYPE_FISCAL_YEAR,
    PERIOD_TYPE_QUARTER,
    PERIOD_TYPE_CUMULATIVE,
})


@dataclass
class Fact:
    """A single data point returned by a tool, with full provenance."""
    id: str                    # f:{turn}:{seq}
    kind: str                  # "data" | "news" | "derived"
    value: Any                 # raw value (number, string, etc.)
    display: str = ""          # human-readable form for matching ("¥767.2亿")
    source: str = ""           # "EDGAR" | "DeFiLlama" | "Binance" etc.
    capability: str = ""       # "financial.edgar.facts"
    # A-class provenance (structured data)
    audited: bool | None = None
    currency: str = ""
    accounting_standard: str = ""  # "CAS" | "US_GAAP" | "IFRS" | "" (null for crypto/macro)
    unit: str = ""
    interval: str = ""
    venue: str = ""
    caliber: str = ""          # tag / definition /口径
    accession: str = ""
    period_start: str = ""
    period_end: str = ""
    period_type: str = ""
    # B-class provenance (news/web)
    url: str = ""
    published_at: str = ""
    media_tier: str = ""       # 信源可信度: "0_primary" | "1_media_pro" | "3_aggregator"
    source_tier: str = ""      # 数据源层级: "primary" | "secondary" (A-share 为 secondary)
    # Metadata
    fetched_at: str = ""
    confidence: str = "high"   # "high" | "medium" | "low"
    precision: str = ""        # "2_sig_digits_from_billion" | "" — significant digits info

    def __post_init__(self) -> None:
        """Validate structural constraints on Fact fields.

        - period_type: if set, must be in PERIOD_TYPES.
          An invalid value like "ytd" would silently bypass cumulative filtering
          logic in the A-share diff pipeline. Hard fail is safe here — this is
          a pure structural constraint, not data-semantic.
        """
        if self.period_type and self.period_type not in PERIOD_TYPES:
            raise ValueError(
                f"Invalid period_type: {self.period_type!r}. "
                f"Must be one of {sorted(PERIOD_TYPES)}. "
                f"(fact_id={self.id}, caliber={self.caliber})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v != "" and v is not None}


class FactRegistry:
    """Per-turn fact registry. Tracks all facts produced by tool calls.

    Usage:
        registry = FactRegistry(turn=12)
        registry.register_tool_result(
            capability_id="financial.edgar.facts",
            result=tool_result,
            arguments={"ticker": "XPEV"},
        )
        # Later: look up by value, by fact_id, or export all
    """

    def __init__(self, turn: int = 0) -> None:
        self._turn = turn
        self._facts: list[Fact] = []
        self._seq = 0
        self._out_of_coverage: dict[str, str] = {}  # ticker → reason (institutional)
        self._targeted_tickers: set[str] = set()    # tickers that had at least one tool call
        self._ticker_fact_ids: dict[str, set[str]] = {}  # ticker → fact IDs that belong to it

    def note_tool_target(self, ticker: str) -> None:
        """Record that a tool was called targeting this ticker.

        Used at the end of the turn to detect tickers where ALL structured
        tools failed — these should trigger the "data unavailable" terminal
        state even without a not_sec_registered signal.
        """
        if ticker and ticker.strip():
            self._targeted_tickers.add(ticker.upper())

    @property
    def all_tools_failed(self) -> dict[str, str]:
        """Tickers where at least one tool was called but ZERO facts were registered.

        These tickers are not in the institutional out_of_coverage list
        (they're not "structurally unavailable"), but ALL structured data
        sources failed for them — web search is the only fallback. The gate
        should treat this like out_of_coverage: declare unavailability, don't
        pass off web-scraped numbers as authoritative.

        ★ Key invariant: a ticker must have ZERO facts to qualify.
        Even one fact (from EDGAR, akshare, etc.) means the ticker is NOT
        all_tools_failed — partial failure is not full failure.
        """
        failed = {}
        for t in sorted(self._targeted_tickers):
            if t not in self._ticker_fact_ids and t not in self._out_of_coverage:
                failed[t] = "all_structured_tools_failed"
        return failed

    @property
    def out_of_coverage(self) -> dict[str, str]:
        """Return tickers that are out of coverage with their reasons."""
        return dict(self._out_of_coverage)

    def mark_out_of_coverage(self, ticker: str, reason: str) -> None:
        """Mark a ticker as out of SEC coverage (no CIK, not registered, etc.).

        This is used by the provenance gate to provide routing-aware feedback:
        when a ticker is out of coverage, the correct agent action is to
        declare unavailability, NOT to search for substitute numbers.
        """
        self._out_of_coverage[ticker.upper()] = reason

    @property
    def turn(self) -> int:
        return self._turn

    @property
    def facts(self) -> list[Fact]:
        return list(self._facts)

    def next_id(self) -> str:
        self._seq += 1
        return f"f:{self._turn}:{self._seq}"

    def register_tool_result(
        self,
        capability_id: str,
        result: Any,
        arguments: dict[str, Any] | None = None,
    ) -> list[Fact]:
        """Decompose a tool result into individual facts and register them.

        This is the MAIN ENTRY POINT — called by ToolDispatcher after every
        successful tool execution. It inspects the result structure and
        extracts individual data points as separate facts.

        Returns the list of registered facts (for logging/debugging).
        """
        arguments = arguments or {}

        # Only register successful results with content
        if hasattr(result, "status"):
            if result.status != "ok":
                return []
            content = result.content
        elif isinstance(result, dict) and result.get("success") is False:
            return []
        else:
            content = result

        if content is None:
            return []

        # Route to type-specific extractors
        registered: list[Fact] = []

        if isinstance(content, dict):
            registered.extend(self._extract_from_dict(capability_id, content, arguments))
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    registered.extend(self._extract_from_dict(capability_id, item, arguments))
                elif isinstance(item, str):
                    registered.extend(self._extract_from_text(capability_id, item, arguments))
                else:
                    registered.append(self._make_fact(capability_id, item, arguments))
        elif isinstance(content, str):
            registered.extend(self._extract_from_text(capability_id, content, arguments))
        else:
            # Non-string primitive — register as single fact
            registered.append(self._make_fact(capability_id, content, arguments))

        self._facts.extend(registered)

        # ★ Associate facts with ticker for accurate all_tools_failed detection.
        # Fact objects don't carry a ticker field (ticker is in the tool call
        # arguments, not the result data), so we track the mapping separately.
        # This is the authoritative source for "does this ticker have any facts?"
        ticker_arg = arguments.get("ticker", "") if arguments else ""
        if ticker_arg:
            ticker = ticker_arg.upper()
            if ticker not in self._ticker_fact_ids:
                self._ticker_fact_ids[ticker] = set()
            for f in registered:
                self._ticker_fact_ids[ticker].add(f.id)

        return registered

    # Text-source capabilities: their output is prose, not structured fields.
    # ★ Numbers are NOT auto-registered from text content.
    # Instead, the text source is registered as a "verified_citation" container
    # — the CHECKER will verify that a specific number appears verbatim in the
    # source text before allowing it to be traced. This prevents motivated citation
    # (agent recalls number from memory, then finds a URL to justify it).
    _TEXT_CAPABILITIES = {
        "financial.rag.search", "financial.websearch",
        "web.fetch", "web.fetch_weixin",
        "panews.search", "panews.briefing", "panews.article", "panews.trending",
        "docs.read",
    }

    def _extract_from_text(
        self,
        capability_id: str,
        text: str,
        arguments: dict[str, Any],
    ) -> list[Fact]:
        """Register text-source tools as verified_citation containers.

        ★ Do NOT extract numbers from text automatically.
        The checker will verify verbatim: a number in agent output is only
        "traced" if it literally appears in this text. This is the mechanism
        that blocks motivated citation — the agent cannot claim a number
        came from a source unless the source actually contains it.

        Returns a single fact of kind=verified_citation that stores the
        full source text. The checker will use it for verbatim matching.
        """
        # Only apply to known text-source capabilities
        if capability_id not in self._TEXT_CAPABILITIES:
            # Other string returns: register as single non-numeric fact
            return [self._make_fact(capability_id, text, arguments)]

        source = self._infer_source(capability_id)
        url = arguments.get("url", "")
        title = arguments.get("title", "") or arguments.get("query", "")

        # ★ Knowledge base sources: curated content with article-level provenance
        source_tier = ""
        published_at = ""
        if capability_id == "docs.read":
            source_tier = "curated"
            # File path as citation URL
            file_path = arguments.get("source", "")
            url = file_path
            title = arguments.get("title", "") or file_path
            published_at = arguments.get("published_at", "") or arguments.get("date", "")
        elif "rag.search" in capability_id:
            source_tier = "curated"

        # Register the text source as a citation container.
        # value = the full text (for verbatim checking by the checker)
        return [Fact(
            id=self.next_id(),
            kind="verified_citation",
            value=text[:5000],  # Cap at 5K chars for registry size
            display=title or source,
            source=source,
            capability=capability_id,
            url=url,
            source_tier=source_tier,
            published_at=published_at,
            confidence="medium",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )]

    def _extract_from_dict(
        self,
        capability_id: str,
        data: dict[str, Any],
        arguments: dict[str, Any],
    ) -> list[Fact]:
        """Extract individual facts from a dict result.

        Field-level granularity: each numeric/monetary field becomes a fact.
        """
        facts: list[Fact] = []

        # Determine source from capability_id
        source = self._infer_source(capability_id)

        # Common provenance fields that apply to all facts from this call
        common = {
            "source": source,
            "capability": capability_id,
            "audited": data.get("audited"),
            "currency": data.get("currency", ""),
            "accounting_standard": data.get("accounting_standard", ""),
            "source_tier": data.get("source_tier", ""),
            "unit": data.get("unit", ""),
            "interval": data.get("interval", ""),
            "venue": data.get("venue", ""),
            "accession": data.get("accession", ""),
            "period_start": data.get("period_start", ""),
            "period_end": data.get("period_end", ""),
            "period_type": data.get("period_type", ""),
            "fetched_at": data.get("fetched_at", datetime.now(timezone.utc).isoformat()),
            "confidence": data.get("confidence", "high"),
        }

        # Fields that are provenance metadata, NOT data values
        META_FIELDS = {
            "success", "message", "error", "source", "capability",
            "audited", "currency", "accounting_standard", "source_tier",
            "media_tier", "unit", "interval", "venue",
            "accession", "period_start", "period_end", "period_type",
            "fetched_at", "confidence", "tag_used", "caliber",
            "definition", "zscore_definition", "zscore_window",
            "execution_time", "degraded_from", "degradation_reason",
            "found", "document", "form", "filing_date",
            "available", "count", "total",
        }

        # ★ Pipeline metadata blacklist: fields that look like data (numeric)
        # but are actually tool pipeline internals. Registering these as facts
        # creates false positives — e.g. "5 个来源" matching results_count=5
        # → fake traced provenance. These should NEVER be registered.
        _PIPELINE_NOISE_PATTERNS = (
            "conf",           # confidence score / extraction_conf
            "_count",         # record_count, guidance_count, results_count
            "similarity",     # RAG embedding similarity
            "rank",           # RAG result rank
            "score",          # generic score
            "elapsed_ms",     # timing metadata
            "page",           # pagination
            "offset",         # pagination
            "fx_rate_date",   # date string, not data
            "fx_rate",        # exchange rate metadata, repeats per record
            "extraction_method",  # string label, not data
            "chunks",         # RAG chunk count metadata
            "dimensions",     # RAG embedding dimensions metadata
        )

        def _is_pipeline_noise(field_name: str) -> bool:
            """Check if a field name is pipeline metadata, not financial data."""
            lower = field_name.lower()
            for pattern in _PIPELINE_NOISE_PATTERNS:
                if pattern in lower:
                    return True
            return False

        # Extract numeric data fields
        for key, value in data.items():
            if key in META_FIELDS or _is_pipeline_noise(key):
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                # ★ Propagate field-level precision from _precision dict if present
                precision_info = ""
                prec_dict = data.get("_precision", {})
                if isinstance(prec_dict, dict):
                    precision_info = prec_dict.get(key, "")
                fact = Fact(
                    id=self.next_id(),
                    kind="data",
                    value=value,
                    display=str(value),
                    caliber=key,
                    precision=precision_info,
                    **{k: v for k, v in common.items() if v is not None and v != ""},
                )
                facts.append(fact)

            # Nested dicts (e.g., records, latest, metrics)
            elif isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    if sub_key in META_FIELDS or _is_pipeline_noise(sub_key):
                        continue
                    if isinstance(sub_val, (int, float)) and not isinstance(sub_val, bool):
                        fact = Fact(
                            id=self.next_id(),
                            kind="data",
                            value=sub_val,
                            display=str(sub_val),
                            caliber=f"{key}.{sub_key}",
                            **{k: v for k, v in common.items() if v is not None and v != ""},
                        )
                        facts.append(fact)
                    # ★ 2-level nested dict: {metrics: {revenue: {value: 123, audited: True, ...}}}
                    # This is EDGAR LANE 1's structure — the "value" key holds the number,
                    # and the other keys are per-field metadata that override common.
                    elif isinstance(sub_val, dict):
                        num_val = sub_val.get("value")
                        if num_val is None or not isinstance(num_val, (int, float)):
                            continue
                        if isinstance(num_val, bool):
                            continue
                        # Merge: common + per-field overrides from sub_val (excluding "value" itself)
                        merged = dict(common)
                        _META_OVERRIDE_KEYS = (
                            "period_start", "period_end", "period_type",
                            "currency", "accounting_standard", "source_tier",
                            "audited", "accession",
                        )
                        for mk in _META_OVERRIDE_KEYS:
                            if mk in sub_val and sub_val[mk] is not None:
                                merged[mk] = sub_val[mk]
                        # LANE 1 uses "start_date"/"end_date" keys; map to period_start/end
                        if "start_date" in sub_val and sub_val["start_date"] is not None:
                            merged["period_start"] = sub_val["start_date"]
                        if "end_date" in sub_val and sub_val["end_date"] is not None:
                            merged["period_end"] = sub_val["end_date"]
                        # LANE 1 uses "fiscal_period" (e.g., "FY", "Q4"); map to period_type
                        fp = sub_val.get("fiscal_period", "")
                        if fp == "FY":
                            merged["period_type"] = "fiscal_year"
                        elif fp and fp.startswith("Q"):
                            merged["period_type"] = "quarter"
                        # Precision from sub_val's _precision if present
                        precision_info = ""
                        prec_dict = sub_val.get("_precision", {})
                        if isinstance(prec_dict, dict):
                            precision_info = prec_dict.get(sub_key, "")
                        fact = Fact(
                            id=self.next_id(),
                            kind="data",
                            value=num_val,
                            display=str(num_val),
                            caliber=sub_key,
                            precision=precision_info,
                            **{k: v for k, v in merged.items() if v is not None and v != ""},
                        )
                        facts.append(fact)

            # Lists of records (e.g., edgar records array)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item_common = {**common}
                        # Override with item-specific provenance
                        for meta_key in ["period_start", "period_end", "period_type",
                                          "currency", "accounting_standard", "source_tier", "audited", "accession"]:
                            if meta_key in item:
                                item_common[meta_key] = item[meta_key]

                        for item_key, item_val in item.items():
                            if item_key in META_FIELDS or _is_pipeline_noise(item_key):
                                continue
                            if isinstance(item_val, (int, float)) and not isinstance(item_val, bool):
                                # ★ Propagate field-level precision from _precision dict
                                precision_info = ""
                                prec_dict = item.get("_precision", {})
                                if isinstance(prec_dict, dict):
                                    precision_info = prec_dict.get(item_key, "")
                                fact = Fact(
                                    id=self.next_id(),
                                    kind="data",
                                    value=item_val,
                                    display=str(item_val),
                                    caliber=f"{key}.{item_key}" if key != "records" else item_key,
                                    precision=precision_info,
                                    **{k: v for k, v in item_common.items() if v is not None and v != ""},
                                )
                                facts.append(fact)
                            # ★ String values in list items from text-source capabilities
                            elif isinstance(item_val, str) and capability_id in self._TEXT_CAPABILITIES:
                                if item_key in ("content", "text", "text_preview", "snippet", "formatted_context", "body"):
                                    cit_url = item.get("url", "") or item.get("source", "")
                                    cit_title = item.get("title", "")
                                    cit_date = item.get("date", "") or item.get("published_at", "")
                                    facts.append(Fact(
                                        id=self.next_id(),
                                        kind="verified_citation",
                                        value=item_val[:5000],
                                        display=cit_title or source,
                                        source=source,
                                        capability=capability_id,
                                        url=cit_url,
                                        source_tier="curated" if source == "knowledge_base" else "",
                                        published_at=cit_date,
                                        confidence="medium",
                                        fetched_at=datetime.now(timezone.utc).isoformat(),
                                    ))

        # ★ String values from text-source capabilities → verified_citation facts.
        # Covers: docs.read content, RAG formatted_context, websearch snippets.
        # (String values in nested list items are handled separately above.)
        for key, value in data.items():
            if key in META_FIELDS or _is_pipeline_noise(key):
                continue
            if isinstance(value, str) and capability_id in self._TEXT_CAPABILITIES:
                if key in ("content", "text", "text_preview", "snippet", "formatted_context", "body"):
                    cit_url = data.get("url", "") or data.get("source", "") or arguments.get("url", "")
                    cit_title = data.get("title", "") or arguments.get("title", "")
                    cit_date = data.get("date", "") or data.get("published_at", "") or arguments.get("published_at", "")
                    facts.append(Fact(
                        id=self.next_id(),
                        kind="verified_citation",
                        value=value[:5000],
                        display=cit_title or source,
                        source=source,
                        capability=capability_id,
                        url=cit_url,
                        source_tier="curated" if source == "knowledge_base" else "",
                        published_at=cit_date,
                        confidence="medium",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    ))

        # Also register string values that look like they carry data (urls, etc.)
        url = data.get("url") or data.get("source_url")
        if url:
            facts.append(Fact(
                id=self.next_id(),
                kind="news",
                value=url,
                display=url,
                source=source,
                capability=capability_id,
                url=url,
                published_at=data.get("published_at", ""),
                media_tier=data.get("media_tier", data.get("tier", "")),
                fetched_at=data.get("fetched_at", ""),
            ))

        return facts

    def _make_fact(
        self,
        capability_id: str,
        value: Any,
        arguments: dict[str, Any],
    ) -> Fact:
        """Create a single fact from a primitive value."""
        return Fact(
            id=self.next_id(),
            kind="data",
            value=value,
            display=str(value),
            source=self._infer_source(capability_id),
            capability=capability_id,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _infer_source(capability_id: str) -> str:
        """Infer data source name from capability_id."""
        if "edgar" in capability_id:
            return "EDGAR"
        if "fred" in capability_id:
            return "FRED"
        if "ashare" in capability_id:
            return "akshare"
        if "crypto.onchain" in capability_id:
            return "CoinMetrics"
        if "crypto.derivatives" in capability_id:
            return "Binance"
        if "crypto.defi" in capability_id:
            return "DeFiLlama"
        if "crypto.sentiment" in capability_id:
            return "alternative.me"
        if "panews" in capability_id:
            return "PANews"
        if "websearch" in capability_id or "web.fetch" in capability_id:
            return "web"
        if "rag.search" in capability_id or "docs.read" in capability_id:
            return "knowledge_base"
        if "quote" in capability_id:
            return "yfinance"
        return capability_id.split(".")[0] if "." in capability_id else "unknown"

    def find_by_value(
        self,
        value: float,
        tolerance: float = 0.005,
        sign_context: str = "",
        force_abs: bool = False,
    ) -> Fact | None:
        """Find a fact whose value matches within tolerance (0.5% by default).

        Supports absolute value matching for negative numbers:
          Registry: -57860000000 (net loss)
          Output:   "净亏损 ¥578.6亿" (positive + semantic context "亏损")

        When force_abs=True, matches on absolute value regardless of context.
        The checker uses this to detect sign conflicts (Registry negative
        but output says "profit").

        Args:
            value: the number extracted from agent output
            tolerance: relative tolerance (0.5%)
            sign_context: surrounding text for sign disambiguation
            force_abs: if True, always match on absolute value
        """
        # Keywords indicating the output number should be negative
        LOSS_KEYWORDS = {"亏损", "损失", "下降", "减少", "负", "净亏",
                         "loss", "decrease", "decline", "negative", "drop"}
        GAIN_KEYWORDS = {"利润", "盈利", "增长", "增加", "正", "净利",
                         "profit", "gain", "increase", "growth", "positive"}

        context_lower = sign_context.lower()
        implies_negative = any(kw in sign_context or kw in context_lower for kw in LOSS_KEYWORDS)
        implies_positive = any(kw in sign_context or kw in context_lower for kw in GAIN_KEYWORDS)

        for fact in reversed(self._facts):  # Most recent first
            if fact.kind in ("news", "verified_citation"):
                continue  # news = URLs, verified_citation = text containers
            try:
                fact_val = float(fact.value)
            except (ValueError, TypeError):
                continue

            # Try exact match first
            if abs(fact_val - value) <= abs(fact_val) * tolerance:
                return fact

            # Absolute value matching
            use_abs = force_abs or (fact_val < 0 and value > 0 and implies_negative)
            if use_abs:
                if abs(abs(fact_val) - abs(value)) <= abs(fact_val) * tolerance:
                    return fact

            # ★ Percentage bridge: ratio (0.0147) ↔ percentage (1.47%)
            # Derived facts often store ratios while output uses percentages.
            # e.g. derivation = 0.0147, output = "1.47%" → 0.0147 × 100 = 1.47
            if 0.0001 <= abs(fact_val) <= 1.0 and 0.1 <= abs(value) <= 200:
                bridged = fact_val * 100
                if abs(bridged - value) <= abs(bridged) * tolerance:
                    return fact
            if 0.0001 <= abs(value) <= 1.0 and 0.1 <= abs(fact_val) <= 200:
                bridged = value * 100
                if abs(fact_val - bridged) <= abs(fact_val) * tolerance:
                    return fact

        return None

    def export(self) -> list[dict[str, Any]]:
        """Export all facts as dicts (for trace persistence)."""
        return [f.to_dict() for f in self._facts]

    def stats(self) -> dict[str, int]:
        """Return registry statistics."""
        return {
            "total_facts": len(self._facts),
            "data_facts": sum(1 for f in self._facts if f.kind == "data"),
            "news_facts": sum(1 for f in self._facts if f.kind == "news"),
            "derived_facts": sum(1 for f in self._facts if f.kind == "derived"),
        }
