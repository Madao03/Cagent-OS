"""S3 Phase 1: Zero-cost document classifier for SEC earnings releases.

Finds earnings press releases among a company's 6-K / 8-K filings using
structural signals from the filing index.json — no LLM calls, no content parsing.

Signals (empirically validated on XPEV filings):
  Primary:
    - EX-99.1 file size: >100KB = earnings release (tables + text)
                           <15KB = monthly delivery / board notice / misc
    - EX-99 count: earnings releases often have EX-99.1 + EX-99.2
    - Date proximity: earnings filed 30-90 days after quarter end
                      (longer window for Q4/annual)
  Secondary:
    - reportDate in submissions API matches quarter end
    - total filing size (index sum)

Design: conservative failure (reject false positives, tolerate false negatives).
        Missing a filing -> visible data gap. Wrong filing -> silent data corruption.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)

_USER_AGENT = "CagentOS madaocage@gmail.com"
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}
_BASE_SEC = "https://www.sec.gov"
_BASE_DATA = "https://data.sec.gov"

# Global rate limiter (shared with edgar_adapter)
_last_request_time = 0.0
_MIN_INTERVAL = 0.15  # ~6.7 req/s, safer margin from SEC's 10/s limit


def _throttle() -> None:
    """Ensure >=110ms between SEC requests."""
    global _last_request_time
    elapsed = time.perf_counter() - _last_request_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_time = time.perf_counter()


class EarningsReleaseFinder:
    """Find earnings press releases in SEC 6-K / 8-K filings.

    Phase 1 signals (zero-cost, no LLM):
      - EX-99.1 file size from index.json (>100KB earns high confidence)
      - Date proximity to quarter end
      - reportDate match (submissions API)
      - EX-99 exhibit count
    """

    def __init__(self) -> None:
        self._cik_cache: dict[str, str] = {}

    # ── Public API ──────────────────────────────────────────────

    async def find(
        self,
        ticker: str,
        quarter_end: str,
        adapter: Any | None = None,
    ) -> dict[str, Any] | None:
        """Find the earnings release 6-K/8-K for a given quarter.

        Args:
            ticker: Stock ticker (e.g., "XPEV").
            quarter_end: ISO date for quarter end (e.g., "2025-09-30").
            adapter: Optional EdgardAdapter for CIK resolution + submissions.

        Returns:
            dict with: accession, form, document, url, filing_date, conf —
            or None if no release found.
        """
        cik = await self._resolve_cik(ticker, adapter)
        if not cik:
            logger.warning("S3: CIK not found for %s", ticker)
            return None

        if adapter:
            submissions = await adapter.get_submissions(ticker)
        else:
            submissions = await self._fetch_submissions(cik)
        if not submissions:
            return None

        # Extract entity_type for degradation gating
        entity_type = self._detect_entity(submissions)

        q_end = datetime.strptime(quarter_end, "%Y-%m-%d")
        # Q4/FY earnings can take up to 90 days; other quarters ~60
        is_q4 = q_end.month == 12
        window_start = q_end - timedelta(days=5)
        window_end = q_end + timedelta(days=90 if is_q4 else 60)

        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        report_dates = recent.get("reportDate", [])
        items_list = recent.get("items", [])  # 8-K item numbers

        candidates = []
        for i, form in enumerate(forms):
            form_str = str(form).upper().strip()
            if form_str not in ("6-K", "8-K"):
                continue

            fd_str = str(filing_dates[i]) if i < len(filing_dates) else ""
            if not fd_str:
                continue
            try:
                fd = datetime.strptime(fd_str, "%Y-%m-%d")
            except ValueError:
                continue
            if not (window_start <= fd <= window_end):
                continue

            # ★ Hard constraint: filing must be AFTER quarter end.
            # A document filed before the quarter closed cannot possibly
            # report that quarter's results. This catches HKEX interim
            # reports and other pre-quarter-end filings.
            if fd <= q_end:
                continue

            # ★ Hard constraint: earnings releases are filed 30+ days
            # after quarter end. Filings within 30 days are annual reports,
            # HKEX interim reports, or other non-earnings bundles.
            # This is deterministic — no scoring, no thresholds.
            if (fd - q_end).days < 30:
                continue

            acc = str(accessions[i])
            rd = str(report_dates[i]) if i < len(report_dates) else ""

            # ── 8-K fast path: Item 2.02 = Results of Operations ──
            # SEC Item taxonomy is authoritative — no scoring needed.
            # 8-K with "2.02" in items IS an earnings release.
            is_8k = form_str == "8-K"
            if is_8k:
                item_str = str(items_list[i]) if i < len(items_list) else ""
                if "2.02" not in item_str:
                    continue  # Not an earnings 8-K

            # Fetch index.json to get EX-99.1 size / document name
            index_data = await self._fetch_index_json(cik, acc)
            if not index_data:
                continue

            ex99_name, ex99_size, total_ex99 = self._parse_index(index_data)
            if not ex99_name:
                logger.debug("S3: %s — no EX-99.1, skip", acc)
                continue

            # Score based on structural signals
            if is_8k:
                # Item 2.02 is authoritative — fixed high confidence
                score = 0.85
            else:
                score = self._score_structural(
                    ex99_size=ex99_size,
                    total_ex99=total_ex99,
                    filing_date=fd,
                    quarter_end=q_end,
                    report_date=rd,
                )
            if score == 0:
                continue

            candidates.append({
                "accession": acc,
                "form": form_str,
                "document": ex99_name,
                "ex99_size": ex99_size,
                "filing_date": fd_str,
                "report_date": rd,
                "score": score,
            })

        if not candidates:
            logger.info("S3: no earnings release for %s Q ending %s",
                        ticker, quarter_end)
            return {"entity_type": entity_type, "found": False}

        candidates.sort(key=lambda c: (-c["score"], c["filing_date"]))
        best = candidates[0]

        # ★ Absolute minimum score: refuse to return "best of nothing".
        # This is the seventh same-pattern fix: when no real earnings
        # release exists in the window, return None instead of silently
        # returning the least-bad wrong answer.
        if best["score"] < 0.35:
            logger.info("S3: best candidate (score=%.2f) below floor 0.35 — "
                        "no earnings release found for %s Q ending %s",
                        best["score"], ticker, quarter_end)
            return {"entity_type": entity_type, "found": False}

        acc_no_dash = best["accession"].replace("-", "")
        url = (
            f"{_BASE_SEC}/Archives/edgar/data/{cik.lstrip('0')}/"
            f"{acc_no_dash}/{best['document']}"
        )

        return {
            "accession": best["accession"],
            "form": best["form"],
            "document": best["document"],
            "url": url,
            "filing_date": best["filing_date"],
            "conf": best["score"],
            "entity_type": entity_type,
            "found": True,
        }

    # ── Structural signal scoring ───────────────────────────────

    @staticmethod
    def _detect_entity(submissions: dict[str, Any]) -> str:
        """Detect entity type from submissions data.

        Returns "foreign_private_issuer" or "operating".
        FPI companies file 6-K (not 10-Q) and may have extrapolated
        quarterly data from third-party aggregators.
        """
        category = str(submissions.get("entityCategory", "")).lower()
        if category in ("foreign", "foreign private issuer"):
            return "foreign_private_issuer"

        # Check filings for 20-F (definitive FPI marker)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        for f in forms:
            if str(f).strip().upper() == "20-F":
                return "foreign_private_issuer"

        return "operating"

    @staticmethod
    def _score_structural(
        ex99_size: int,
        total_ex99: int,
        filing_date: datetime,
        quarter_end: datetime,
        report_date: str,
    ) -> float:
        """Score based on EX-99.1 size + date proximity + exhibit count.

        Returns 0.0 if the filing is clearly NOT an earnings release.
        """
        # Hard negative: EX-99.1 < 8KB is NOT an earnings release
        # (board notice, monthly delivery, director change, etc.)
        if ex99_size < 8000:
            return 0.0

        score = 0.0

        # ── EX-99.1 size (primary signal) ──
        if ex99_size >= 200000:
            score += 0.45  # Full earnings with tables + charts
        elif ex99_size >= 100000:
            score += 0.35  # Standard earnings release
        elif ex99_size >= 50000:
            score += 0.20  # Could be earnings (short format)
        elif ex99_size >= 15000:
            score += 0.10  # Ambiguous: could be monthly delivery w/ details

        # ── Multiple EX-99 exhibits (secondary) ──
        # Earnings releases often have EX-99.1 + EX-99.2 (financial tables)
        if total_ex99 >= 2:
            score += 0.15

        # ── Date proximity to quarter end ──
        # Earnings are typically filed 30-90 days after quarter end.
        # (<30 days already hard-excluded above — no need to score here.)
        days_after = (filing_date - quarter_end).days
        if 30 <= days_after <= 90:
            score += 0.15  # Sweet spot
        elif 90 < days_after <= 120:
            score += 0.08  # Late Q4/annual filer

        # ── reportDate matches quarter end ──
        if report_date == quarter_end.strftime("%Y-%m-%d"):
            score += 0.15

        return min(score, 1.0)

    # ── SEC API helpers ─────────────────────────────────────────

    @staticmethod
    def _ticker_to_cik_map() -> dict[str, str]:
        """Load ticker->CIK mapping from SEC. Returns {TICKER: "XXXXXXXXXX"}."""
        _throttle()
        resp = requests.get(
            f"{_BASE_SEC}/files/company_tickers.json",
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error("Failed to load ticker map: HTTP %s", resp.status_code)
            return {}

        mapping: dict[str, str] = {}
        for entry in resp.json().values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = int(entry.get("cik_str", 0))
            if ticker and cik:
                mapping[ticker] = f"{cik:010d}"
        return mapping

    async def _resolve_cik(self, ticker: str, adapter: Any | None) -> str | None:
        """Resolve ticker to zero-padded CIK."""
        if adapter:
            return adapter._ticker_to_cik(ticker)
        if ticker.upper() not in self._cik_cache:
            self._cik_cache = self._ticker_to_cik_map()
        return self._cik_cache.get(ticker.upper())

    async def _fetch_submissions(self, cik: str) -> dict[str, Any] | None:
        """Fetch submissions JSON for a CIK."""
        _throttle()
        resp = await asyncio.to_thread(
            requests.get,
            f"{_BASE_DATA}/submissions/CIK{cik}.json",
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error("S3: submissions fetch failed HTTP %s for CIK %s",
                         resp.status_code, cik)
            return None
        return resp.json()

    async def _fetch_index_json(self, cik: str, accession: str) -> dict[str, Any] | None:
        """Fetch filing index.json.

        SEC URL format: .../Archives/edgar/data/{cik}/{acc_no_dash}/index.json
        """
        acc_no_dash = accession.replace("-", "")
        cik_stripped = cik.lstrip("0")
        url = (
            f"{_BASE_SEC}/Archives/edgar/data/{cik_stripped}/"
            f"{acc_no_dash}/index.json"
        )
        _throttle()
        resp = await asyncio.to_thread(
            requests.get, url, headers=_HEADERS, timeout=15,
        )
        if resp.status_code != 200:
            logger.debug("S3: index.json not found for %s (HTTP %s)",
                         accession, resp.status_code)
            return None
        return resp.json()

    @staticmethod
    def _parse_index(index_data: dict[str, Any]) -> tuple[str, int, int]:
        """Parse index.json for EX-99.1 info.

        Returns:
            ex99_name: Filename of the largest EX-99 exhibit (e.g., "d270013dex991.htm").
            ex99_size: Size of that EX-99 in bytes.
            total_ex99: Count of EX-99 exhibits found.
        """
        item_list = index_data.get("directory", {}).get("item", [])
        ex99_entries: list[tuple[str, int]] = []

        for item in item_list:
            name = str(item.get("name", ""))
            size_str = str(item.get("size", "0"))
            # EX-99 exhibits have "ex99" in filename (e.g., "d270013dex991.htm")
            if "ex99" in name.lower():
                try:
                    size = int(size_str)
                except ValueError:
                    size = 0
                ex99_entries.append((name, size))

        if not ex99_entries:
            return ("", 0, 0)

        # Pick the largest EX-99 as the primary (earnings release)
        ex99_entries.sort(key=lambda x: -x[1])
        best_name, best_size = ex99_entries[0]
        return (best_name, best_size, len(ex99_entries))


# ── Module-level convenience ─────────────────────────────────────

async def find_earnings_release(
    ticker: str,
    quarter_end: str,
    adapter: Any | None = None,
) -> dict[str, Any] | None:
    """Find earnings release for a quarter."""
    finder = EarningsReleaseFinder()
    return await finder.find(ticker, quarter_end, adapter)
