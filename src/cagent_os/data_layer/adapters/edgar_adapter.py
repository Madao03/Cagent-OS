"""SEC EDGAR Adapter — authoritative source for US-listed financial statements.

LANE 1 (P0): companyfacts structured numbers + submissions routing.
    - ticker → CIK mapping
    - submissions index (form/filingDate/accessionNumber routing)
    - companyfacts: structured XBRL data (us-gaap + ifrs-full)
    - Four robustness checks: Q4 gap, amendments, tag normalization, audit priority

No API key required. Just set User-Agent header (SEC requirement).
Rate limit: 10 requests/second per IP.

Reference: docs/EDGAR_ADAPTER.md (full specification)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

# SEC requires a descriptive User-Agent. Format: "Name email"
_USER_AGENT = "CagentOS madaocage@gmail.com"
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

_BASE_DATA = "https://data.sec.gov"
_BASE_SEC = "https://www.sec.gov"

# Rate limiting: SEC allows 10 req/s. We use a simple token bucket.
_last_request_time = 0.0
_MIN_INTERVAL = 0.11  # ~9 req/s, leaving headroom

# ── Tag alias normalization ───────────────────────────────────────────
# Maps unified field names → possible XBRL tags (tried in order).
# Extended from EDGAR_ADAPTER.md §5.
_TAG_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
    "total_assets": ["Assets"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_basic": ["WeightedAverageNumberOfSharesOutstandingBasic"],
    "dividends_paid": ["PaymentsOfDividends", "CommonStockDividendsPaid"],
}

# us-gaap taxonomy covers most US domestic filers.
# ifrs-full covers some foreign filers reporting under IFRS.
_TAXONOMIES = ["us-gaap", "ifrs-full"]

# Map XBRL taxonomy to accounting_standard field values.
# Source must be taxonomy (not entity_type) — FPI companies like
# XPEV/BABA are FPI but voluntarily report under us-gaap.
_TAXONOMY_TO_STANDARD = {
    "us-gaap": "US_GAAP",
    "ifrs-full": "IFRS",
}

# ★ CIK → accounting_standard cache.
# accounting_standard is an issuer-level attribute (same company, same standard
# across all its SEC filings). Cached by CIK (immutable per issuer).
# Maps int CIK → "US_GAAP" | "IFRS" | "UNKNOWN".
_CIK_STANDARD_CACHE: dict[int, str] = {}


async def get_issuer_accounting_standard(ticker: str) -> str:
    """Look up the accounting standard for a US-listed issuer by CIK.

    This is an ISSUER-LEVEL attribute — not document-level.
    XPEV uses US GAAP whether you're reading its 20-F XBRL or 6-K HTML.
    LANE 2 calls this to populate accounting_standard on extracted records.

    Returns:
        "US_GAAP" | "IFRS" | "UNKNOWN" (has CIK but couldn't determine standard)
        "" if ticker has no CIK (not SEC-registered → not applicable)
    """
    ticker = ticker.upper().strip()
    adapter = EdgardAdapter()
    cik = adapter._ticker_to_cik(ticker)
    if not cik:
        return ""

    cik_int = int(cik)
    if cik_int in _CIK_STANDARD_CACHE:
        return _CIK_STANDARD_CACHE[cik_int]

    try:
        facts = await adapter.get_company_facts(ticker)
        if facts and facts.taxonomy:
            standard = _TAXONOMY_TO_STANDARD.get(facts.taxonomy, "UNKNOWN")
        else:
            standard = "UNKNOWN"
    except Exception:
        logger.exception("Failed to determine accounting_standard for %s", ticker)
        standard = "UNKNOWN"

    _CIK_STANDARD_CACHE[cik_int] = standard
    return standard


@dataclass
class EarningsDataPoint:
    """One financial data point from EDGAR."""
    tag: str               # XBRL tag used (e.g. "Revenues")
    value: float | None
    fiscal_year: int       # e.g. 2025
    fiscal_period: str     # "FY" | "Q1" | "Q2" | "Q3"
    form: str              # "10-K" | "10-Q" | "20-F"
    start_date: str        # period start (ISO)
    end_date: str          # period end (ISO)
    accession: str         # accession number for traceability
    filed_date: str
    audited: bool          # True if form is 10-K or 20-F


@dataclass
class CompanyFacts:
    """Structured financial data for one company."""
    ticker: str
    cik: str               # zero-padded CIK (e.g. "0000320193")
    name: str
    facts: dict[str, list[EarningsDataPoint]]  # unified_field → data points
    entity_type: str       # "operating" | "foreign_private_issuer"
    taxonomy: str          # "us-gaap" | "ifrs-full"
    currency: str = "USD"  # reporting currency (USD/CNY/RMB/...)


class EdgardAdapter(DataSourceAdapter):
    """SEC EDGAR data source — authoritative financial statements.

    Free, no API key. Requires User-Agent header. Rate-limited at 10 req/s.
    """

    tier = 0  # Highest priority — authoritative source
    name = "edgar"

    def __init__(self) -> None:
        self._ticker_cache: dict[str, str] | None = None  # ticker → CIK
        self._cache_timestamp: float = 0.0
        self._CACHE_TTL = 86400  # ticker map cache 1 day

    # ── DataSourceAdapter interface ───────────────────────────────────

    async def fetch(self, metric: str, **params: Any) -> RawData:
        """Fetch a single metric for a ticker.

        params:
            ticker: stock symbol (e.g. "AAPL")
            fiscal_year: target fiscal year (optional)
            fiscal_period: "FY" | "Q1" | "Q2" | "Q3" (optional, default FY)
        """
        ticker = str(params.get("ticker", "")).upper().strip()
        if not ticker:
            return RawData(source="edgar", metric=metric, value=None,
                           fetched_at=datetime.now(timezone.utc).isoformat())

        try:
            facts = await self.get_company_facts(ticker)
            if not facts or metric not in facts.facts:
                return RawData(source="edgar", metric=metric, value=None,
                               fetched_at=datetime.now(timezone.utc).isoformat())

            # Get latest data point for the requested period
            fy = params.get("fiscal_year")
            fp = params.get("fiscal_period", "FY")
            points = facts.facts[metric]

            if fy:
                points = [p for p in points if p.fiscal_year == fy and p.fiscal_period == fp]
            else:
                # Latest available
                points = sorted(points, key=lambda p: (p.fiscal_year, p.fiscal_period), reverse=True)

            if not points:
                return RawData(source="edgar", metric=metric, value=None,
                               fetched_at=datetime.now(timezone.utc).isoformat())

            best = points[0]
            return RawData(
                source="edgar", metric=metric, value=best.value,
                raw_response={
                    "tag": best.tag, "form": best.form, "audited": best.audited,
                    "accession": best.accession, "filed_date": best.filed_date,
                    "fiscal_year": best.fiscal_year, "fiscal_period": best.fiscal_period,
                    "end_date": best.end_date,
                },
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.warning("EDGAR fetch failed for %s/%s: %s", ticker, metric, exc)
            return RawData(source="edgar", metric=metric, value=None,
                           fetched_at=datetime.now(timezone.utc).isoformat())

    async def health_check(self) -> DataSourceHealth:
        """Check if SEC EDGAR is reachable."""
        try:
            start = time.perf_counter()
            resp = await asyncio.to_thread(
                requests.get,
                f"{_BASE_SEC}/files/company_tickers.json",
                headers=_HEADERS,
                timeout=5,
            )
            latency = (time.perf_counter() - start) * 1000
            if resp.status_code == 200:
                return DataSourceHealth(available=True, latency_ms=round(latency, 1))
            return DataSourceHealth(available=False, latency_ms=round(latency, 1),
                                    error_message=f"HTTP {resp.status_code}")
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    # ── LANE 1: ticker → CIK → companyfacts ───────────────────────────

    def _throttle(self) -> None:
        """Simple rate limiter: ensure ≥110ms between requests."""
        global _last_request_time
        elapsed = time.perf_counter() - _last_request_time
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _last_request_time = time.perf_counter()

    def _get_ticker_map(self) -> dict[str, str]:
        """Load ticker → CIK mapping from SEC. Cached for 1 day."""
        if self._ticker_cache and (time.time() - self._cache_timestamp < self._CACHE_TTL):
            return self._ticker_cache

        self._throttle()
        resp = requests.get(
            f"{_BASE_SEC}/files/company_tickers.json",
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to load ticker map: HTTP {resp.status_code}")

        data = resp.json()
        mapping: dict[str, str] = {}
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = int(entry.get("cik_str", 0))
            if ticker and cik:
                mapping[ticker] = f"{cik:010d}"

        self._ticker_cache = mapping
        self._cache_timestamp = time.time()
        logger.info("EDGAR ticker map loaded: %d entries", len(mapping))
        return mapping

    def _ticker_to_cik(self, ticker: str) -> str | None:
        """Convert ticker to zero-padded CIK. Returns None if not found."""
        ticker_map = self._get_ticker_map()
        return ticker_map.get(ticker.upper())

    def has_sec_cik(self, ticker: str) -> bool:
        """Check if a ticker is registered with the SEC (has a CIK).

        This is the code-level gate for EDGAR routing: if a ticker has no CIK,
        it is NOT registered with the SEC — quarterly/annual data via EDGAR
        is structurally unavailable. No HTTP call is needed beyond the cached
        company_tickers.json lookup.

        This replaces prompt-based routing tables. The CIK absence signal is
        more general and reliable than any hard-coded list of stock symbols.
        """
        return self._ticker_to_cik(ticker) is not None

    async def get_submissions(self, ticker: str) -> dict[str, Any]:
        """Get submissions index for a company (LANE 1 routing).

        Returns the full submissions.json including:
        - Company metadata (name, sic, entityType)
        - filings.recent.{form[], filingDate[], accessionNumber[], ...}
        """
        cik = self._ticker_to_cik(ticker)
        if not cik:
            raise ValueError(f"Ticker not found in SEC: {ticker}")

        self._throttle()
        resp = await asyncio.to_thread(
            requests.get,
            f"{_BASE_DATA}/submissions/CIK{cik}.json",
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Submissions fetch failed for {ticker}: HTTP {resp.status_code}")

        return resp.json()

    def _detect_entity_type(self, submissions: dict) -> tuple[str, str]:
        """Detect if company is domestic (10-K) or foreign private issuer (20-F).

        Returns (entity_type, form_type) where:
        - entity_type: "operating" | "foreign_private_issuer"
        - form_type: "10-K" | "20-F"

        Scans ALL recent filings (not just first 20) to find the most
        recent annual filing. Some companies have many 6-K/8-K between
        annual filings, so a shallow scan can miss the 20-F.
        """
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])

        # Scan through ALL forms to find the most recent annual filing
        has_20f = False
        has_10k = False
        for form in forms:
            if form in ("20-F", "20-F/A"):
                has_20f = True
                break  # Found 20-F before 10-K → definitely FPI
            if form in ("10-K", "10-K/A"):
                has_10k = True
                break  # Found 10-K before 20-F → definitely domestic

        # Also check entityCategory field if present
        category = submissions.get("entityCategory", "").lower()
        if "foreign" in category:
            return ("foreign_private_issuer", "20-F")

        if has_20f:
            return ("foreign_private_issuer", "20-F")
        if has_10k:
            return ("operating", "10-K")

        # Fallback: check if sic description mentions foreign
        sic_desc = submissions.get("sicDescription", "").lower()
        if "foreign" in sic_desc:
            return ("foreign_private_issuer", "20-F")

        # Default to domestic
        return ("operating", "10-K")

    def _detect_taxonomy(self, facts_data: dict) -> str:
        """Detect which XBRL taxonomy the company actually reports in.

        FPI ≠ IFRS: many foreign private issuers (XPEV, BABA) are FPI
        but voluntarily report under us-gaap. The taxonomy must be
        determined by where the data actually lives, not inferred
        from entity_type.

        Strategy: count data points in each taxonomy and pick the one
        with the most. If both have data, prefer us-gaap (most companies).
        """
        us_gaap_count = 0
        ifrs_count = 0

        us_gaap = facts_data.get("us-gaap", {})
        ifrs = facts_data.get("ifrs-full", {})

        # Count entries across all revenue aliases
        for field, aliases in _TAG_ALIASES.items():
            # Also check IFRS aliases (Revenue singular, ProfitLoss, etc.)
            ifrs_aliases = {
                "revenue": ["Revenue", "Revenues"],
                "net_income": ["ProfitLoss"],
            }.get(field, aliases)

            for tag in aliases:
                tag_data = us_gaap.get(tag, {})
                if tag_data:
                    for unit_items in tag_data.get("units", {}).values():
                        us_gaap_count += len(unit_items)

            for tag in ifrs_aliases:
                tag_data = ifrs.get(tag, {})
                if tag_data:
                    for unit_items in tag_data.get("units", {}).values():
                        ifrs_count += len(unit_items)

        if ifrs_count > us_gaap_count * 2:
            return "ifrs-full"
        return "us-gaap"

    def _detect_currency(self, facts_data: dict, taxonomy: str) -> str:
        """Detect the reporting currency (本位币) from companyfacts.

        FPI (especially Chinese companies) often report in CNY/RMB natively
        and provide USD as "convenience translation" (便利折算) for only
        the most recent period. Using USD would cause:
        - Historical series gaps (USD only covers 1-2 years)
        - Growth rates polluted by FX (not operating performance)

        Strategy: find the unit key with the MOST data entries across years.
        The unit with full history = native currency = the correct choice.
        """
        # Collect all unit keys and their data counts across all revenue tags
        unit_counts: dict[str, int] = {}
        for tag_aliases in _TAG_ALIASES.values():
            for tag in tag_aliases[:1]:  # Check first alias only (e.g. "Revenues")
                tag_data = facts_data.get(taxonomy, {}).get(tag, {})
                if not tag_data:
                    # Try fallback taxonomy
                    for t in _TAXONOMIES:
                        tag_data = facts_data.get(t, {}).get(tag, {})
                        if tag_data:
                            break
                if not tag_data:
                    continue
                units = tag_data.get("units", {})
                for unit_key, items in units.items():
                    # Count distinct fiscal years in this unit
                    years = set()
                    for item in items:
                        fy = item.get("fy")
                        if fy:
                            years.add(fy)
                    # Score = number of distinct years (full history)
                    prev = unit_counts.get(unit_key, 0)
                    unit_counts[unit_key] = max(prev, len(years))

        if not unit_counts:
            return "USD"

        # Pick the unit with the most years of data (= native currency)
        best_unit = max(unit_counts, key=unit_counts.get)

        # Normalize: CNY and RMB are the same thing
        if best_unit in ("CNY", "RMB", "CNH"):
            return "CNY"

        return best_unit

    def _extract_metric(
        self,
        facts_data: dict,
        taxonomy: str,
        unified_field: str,
        currency: str = "USD",
    ) -> list[EarningsDataPoint]:
        """Extract all data points for one unified field from companyfacts.

        Handles:
        - Tag alias normalization: MERGES data from ALL matching XBRL tags
          (e.g. AAPL used 'Revenues' until FY2018 then switched to
          'RevenueFromContractWithCustomerExcludingAssessedTax'. We need
          both to get the full time series.)
        - Taxonomy fallback: if primary taxonomy has no data, tries the other
        - Currency selection: uses detected currency (USD/CNY/RMB), not hardcoded
        """
        aliases = _TAG_ALIASES.get(unified_field, [])
        if not aliases:
            return []

        # Taxonomy fallback: try primary first, then the other
        taxonomies_to_try = [taxonomy]
        for t in _TAXONOMIES:
            if t not in taxonomies_to_try:
                taxonomies_to_try.append(t)

        # Collect data from ALL aliases across ALL taxonomies, then merge.
        # Different aliases may cover different time ranges (tag changes).
        all_points: list[EarningsDataPoint] = []

        for tax in taxonomies_to_try:
            for tag in aliases:
                tag_data = facts_data.get(tax, {}).get(tag, {})
                if not tag_data:
                    continue

                units = tag_data.get("units", {})
                if not units:
                    continue

                # Build list of unit keys to try, prioritizing detected currency
                unit_priority = [currency]
                for uk in ["USD", "USD/shares", "shares", "CNY", "CNH", "RMB", ""]:
                    if uk and uk not in unit_priority:
                        unit_priority.append(uk)

                for unit_key in unit_priority:
                    unit_data = units.get(unit_key, [])
                    if not unit_data:
                        continue

                    for item in unit_data:
                        val = item.get("val")
                        if val is None:
                            continue

                        form = item.get("form", "")
                        audited = form in ("10-K", "20-F", "10-K/A", "20-F/A")

                        all_points.append(EarningsDataPoint(
                            tag=tag,
                            value=float(val),
                            fiscal_year=item.get("fy", 0),
                            fiscal_period=item.get("fp", ""),
                            form=form,
                            start_date=item.get("start", ""),
                            end_date=item.get("end", ""),
                            accession=item.get("accn", ""),
                            filed_date=item.get("filed", ""),
                            audited=audited,
                        ))
                    break  # Only use the first matching unit per tag

        if all_points and all_points[0].tag != aliases[0]:
            logger.info(
                "EDGAR: %s data from tag=%s (alias fallback), %d points",
                unified_field, all_points[0].tag, len(all_points),
            )

        return all_points

    def _apply_robustness(
        self,
        points: list[EarningsDataPoint],
        target_fy: int | None,
        target_fp: str,
        aliases_priority: list[str] | None = None,
    ) -> list[EarningsDataPoint]:
        """Apply four robustness checks (§5):

        ① Q4 gap: Q4 doesn't exist as 10-Q; only FY (annual) covers Q4.
        ② Amendments: 10-K/A or 10-Q/A overrides original.
        ③ Tag normalization: already handled in _extract_metric.
        ④ Audit priority: 10-K (audited) preferred over 10-Q (unaudited).

        ★ KEY FIX: period is determined by start/end dates, NOT by fy/fp.
        In companyfacts, fy = "which filing this fact appeared in", NOT
        "which period it covers". A 20-F filed in 2025 covering FY2023/24/25
        will have all three years' data tagged fy=2025. We must use the
        start/end dates to determine the actual period.

        Period classification by duration:
        - Annual: (end - start) ≈ 365 days (330-400 to be safe)
        - Quarterly: (end - start) ≈ 90 days (70-100)
        """
        from collections import defaultdict
        from datetime import datetime as _dt

        if not points:
            return points

        def _parse_date(s: str) -> _dt | None:
            if not s:
                return None
            try:
                return _dt.fromisoformat(s[:10])
            except (ValueError, TypeError):
                return None

        def _duration_days(p: EarningsDataPoint) -> int | None:
            """Days between start and end. None if either missing."""
            s, e = _parse_date(p.start_date), _parse_date(p.end_date)
            if not s or not e:
                return None
            return (e - s).days

        # ②+④ Deduplicate by (start_date, end_date): same period appears in
        # multiple filings (original + comparison data in later filings).
        # Take the most recently filed version (handles amendments + restatements).
        grouped: dict[tuple[str, str], list[EarningsDataPoint]] = defaultdict(list)
        for p in points:
            key = (p.start_date or "", p.end_date or "")
            grouped[key].append(p)

        result: list[EarningsDataPoint] = []
        for key, group in grouped.items():
            # Sort priority (lower = picked first):
            # 1. Tag alias priority (first in _TAG_ALIASES wins — consistent definition)
            # 2. Amendment > original
            # 3. Audited > unaudited
            # 4. Latest filed date
            def _tag_rank(p: EarningsDataPoint) -> int:
                if aliases_priority and p.tag in aliases_priority:
                    return aliases_priority.index(p.tag)
                return 999

            group.sort(
                key=lambda p: (
                    _tag_rank(p),                           # tag priority
                    0 if "/A" in p.form else 1,             # amendment > original
                    0 if p.audited else 1,                  # audited > unaudited
                    p.filed_date or "",                      # newer > older
                ),
            )
            result.append(group[0])

        # Classify periods by duration (NOT by fy/fp)
        annual: list[EarningsDataPoint] = []
        quarterly: list[EarningsDataPoint] = []
        unknown: list[EarningsDataPoint] = []
        for p in result:
            dur = _duration_days(p)
            if dur is None:
                unknown.append(p)
            elif dur >= 330:  # Annual (~365 days)
                annual.append(p)
            elif dur >= 70:   # Quarterly (~90 days)
                quarterly.append(p)
            else:
                unknown.append(p)  # Short period (e.g., transition)

        # Select the right bucket based on target_fp
        if target_fp in ("FY", "Q4"):
            # Q4 = annual - first 3 quarters (reconstruction is P1)
            # For now, return annual data sorted by end_date desc
            bucket = annual
        elif target_fp in ("Q1", "Q2", "Q3"):
            bucket = quarterly
        else:
            bucket = annual + quarterly + unknown

        # Sort by end_date DESCENDING (latest period first)
        # This is the correct "latest" — NOT fy.
        bucket.sort(
            key=lambda p: p.end_date or "",
            reverse=True,
        )

        # If filtering by fiscal_year, match on end_date year
        # (e.g., FY2025 = period ending in 2025)
        if target_fy:
            bucket = [p for p in bucket if p.end_date and p.end_date[:4] == str(target_fy)]

        return bucket if bucket else result

    async def get_company_facts(self, ticker: str) -> CompanyFacts | None:
        """Get structured financial facts for a company (LANE 1 main).

        This is the primary entry point for financial data from EDGAR.
        Returns CompanyFacts with all core metrics, or None if not found.
        """
        cik = self._ticker_to_cik(ticker)
        if not cik:
            logger.warning("EDGAR: ticker %s not found", ticker)
            return None

        # Get submissions to detect entity type
        submissions = await self.get_submissions(ticker)
        entity_type, form_type = self._detect_entity_type(submissions)
        name = submissions.get("name", ticker)

        # Get companyfacts (full XBRL dataset)
        self._throttle()
        resp = await asyncio.to_thread(
            requests.get,
            f"{_BASE_DATA}/api/xbrl/companyfacts/CIK{cik}.json",
            headers=_HEADERS,
            timeout=30,  # companyfacts can be large (several MB)
        )
        if resp.status_code != 200:
            logger.warning("EDGAR companyfacts failed for %s: HTTP %d", ticker, resp.status_code)
            return None

        facts_data = resp.json().get("facts", {})

        # Detect taxonomy from actual data, NOT from entity_type.
        # FPI ≠ IFRS: many Chinese companies (XPEV, BABA) are FPI but use
        # us-gaap tags voluntarily. Taxonomy is determined by which XBRL
        # dictionary the company actually reports in.
        taxonomy = self._detect_taxonomy(facts_data)

        # Detect reporting currency (FPI may use CNY/RMB, not USD)
        currency = self._detect_currency(facts_data, taxonomy)
        if currency != "USD":
            logger.info("EDGAR: %s reports in %s (not USD)", ticker, currency)

        # Extract all unified fields with robustness applied
        facts: dict[str, list[EarningsDataPoint]] = {}
        for unified_field, aliases in _TAG_ALIASES.items():
            raw_points = self._extract_metric(facts_data, taxonomy, unified_field, currency=currency)
            if raw_points:
                facts[unified_field] = self._apply_robustness(
                    raw_points, None, "FY", aliases_priority=aliases,
                )

        return CompanyFacts(
            ticker=ticker.upper(),
            cik=cik,
            name=name,
            facts=facts,
            entity_type=entity_type,
            taxonomy=taxonomy,
            currency=currency,
        )

    async def get_earnings_summary(
        self,
        ticker: str,
        fiscal_year: int | None = None,
        fiscal_period: str = "FY",
    ) -> dict[str, Any]:
        """Get a summary of key financial metrics for a ticker.

        This is the high-level API used by the toolkit.
        Returns a dict with revenue, net_income, eps, etc.
        """
        facts = await self.get_company_facts(ticker)
        if not facts:
            return {"error": "Company not found in EDGAR", "ticker": ticker}

        result: dict[str, Any] = {
            "ticker": facts.ticker,
            "name": facts.name,
            "cik": facts.cik,
            "entity_type": facts.entity_type,
            "taxonomy": facts.taxonomy,
            "currency": facts.currency,
            "accounting_standard": _TAXONOMY_TO_STANDARD.get(facts.taxonomy, ""),
            "source": "edgar",
            "source_tier": "primary",
            "audited": True,  # LANE 1: XBRL data from annual reports (10-K / 20-F)
            "metrics": {},
        }

        for field_name, points in facts.facts.items():
            # Filter by requested period if specified
            filtered = points
            if fiscal_year:
                filtered = [p for p in points if p.end_date and p.end_date[:4] == str(fiscal_year)]
            if fiscal_period != "FY":
                filtered = [p for p in filtered if p.fiscal_period == fiscal_period]

            if not filtered:
                # Fallback: get the latest available
                filtered = points

            if filtered:
                best = filtered[0]
                result["metrics"][field_name] = {
                    "value": best.value,
                    "currency": facts.currency,
                    "accounting_standard": _TAXONOMY_TO_STANDARD.get(facts.taxonomy, ""),
                    "fiscal_year": best.fiscal_year,
                    "fiscal_period": best.fiscal_period,
                    "form": best.form,
                    "audited": best.audited,
                    "start_date": best.start_date,
                    "end_date": best.end_date,
                    "filed_date": best.filed_date,
                    "accession": best.accession,
                    "tag_used": best.tag,
                }

        return result
