"""LANE 2: Earnings release extractor.

Parses SEC 6-K/8-K earnings press releases into structured records.

Architecture (EDGAR_LANE2.md):
  S4: Table triage → identify financial data tables (not layout scaffolding)
  S4b: Income statement location → find the table with revenue/earnings data
  S5: Column header parsing → extract period (start/end) from column headers
  S5b: Value cleanup → handle $/RMB split cells, parenthesized negatives, dashes
  S6: Period attribution → bind each value to explicit (start, end) dates
  S7: Schema output → structured records with full traceability

Key design principles:
  - Table headers are the source of truth for periods (not body text)
  - RMB (native currency) is primary; USD is convenience translation (derived)
  - Comparative clause values are NEVER extracted as independent records
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


@dataclass
class GuidanceRecord:
    """Company guidance for a future period."""
    period_label: str          # "Q1 2026" (display only)
    metric_name: str           # "revenue" / "deliveries" / "growth_rate"
    low: float | None
    high: float | None
    currency: str              # "CNY" / "USD" / "count"
    yoy_change_low: float | None   # Year-over-year change (%)
    yoy_change_high: float | None
    source: str                # "6-K" / "8-K"
    accession: str
    extraction_conf: float


@dataclass
class FinancialRecord:
    """One period's financial data extracted from a press release."""
    period_start: str        # ISO date (e.g. "2025-01-01")
    period_end: str          # ISO date (e.g. "2025-12-31")
    period_type: str         # "quarter" | "fiscal_year" | "half_year"
    currency: str            # "CNY" | "USD"
    fx_rate: float | None    # If USD derived: exchange rate used
    fx_rate_date: str | None # Date of FX rate
    metrics: dict[str, float | None]  # revenue, net_income, eps_diluted, etc.
    source: str              # "6-K" or "8-K"
    accession: str           # SEC accession number
    document: str            # e.g. "EX-99.1"
    audited: bool            # Always False for press releases
    extraction_method: str   # "table" or "text"
    extraction_conf: float   # Confidence score


class ExtractedData:
    """Container for all records extracted from one press release."""

    def __init__(self) -> None:
        self.records: list[FinancialRecord] = []
        self.guidance: list[GuidanceRecord] = []
        self.meta: dict[str, Any] = {}

    def add_record(self, rec: FinancialRecord) -> None:
        self.records.append(rec)

    def add_guidance(self, g: GuidanceRecord) -> None:
        self.guidance.append(g)

    def get_record(self, period_type: str, start: str, end: str) -> dict[str, Any] | None:
        """Get a single record as dict (matching test expectations)."""
        for r in self.records:
            if r.period_type == period_type and r.period_start == start and r.period_end == end:
                return {
                    "period_start": r.period_start,
                    "period_end": r.period_end,
                    "period_type": r.period_type,
                    "currency": r.currency,
                    "fx_rate": r.fx_rate,
                    "fx_rate_date": r.fx_rate_date,
                    "revenue": r.metrics.get("revenue"),
                    "cost_of_sales": r.metrics.get("cost_of_sales"),
                    "gross_profit": r.metrics.get("gross_profit"),
                    "operating_income": r.metrics.get("operating_income"),
                    "net_income": r.metrics.get("net_income"),
                    "eps_diluted": r.metrics.get("eps_diluted"),
                    "source": r.source,
                    "audited": r.audited,
                    "accession": r.accession,
                    "extraction_method": r.extraction_method,
                }
        return None

    def all_records(self) -> list[dict[str, Any]]:
        return [
            {
                "period_start": r.period_start,
                "period_end": r.period_end,
                "period_type": r.period_type,
                "currency": r.currency,
                "fx_rate": r.fx_rate,
                "revenue": r.metrics.get("revenue"),
                "cost_of_sales": r.metrics.get("cost_of_sales"),
                "gross_profit": r.metrics.get("gross_profit"),
                "operating_income": r.metrics.get("operating_income"),
                "net_income": r.metrics.get("net_income"),
                "eps_diluted": r.metrics.get("eps_diluted"),
                "source": r.source,
                "audited": r.audited,
                "accession": r.accession,
                "extraction_method": r.extraction_method,
            }
            for r in self.records
        ]


class EarningsReleaseExtractor:
    """Extract structured financial data from SEC earnings press releases."""

    # Keywords that identify an income statement table
    INCOME_KEYWORDS = {
        "total revenues", "revenues", "total revenue",
        "total net sales", "net sales",  # AAPL and many US companies use this
        "cost of sales", "cost of revenue", "cost of products sold",
        "gross profit", "gross margin",
        "operating income", "operating loss", "operating expenses",
        "net income", "net loss", "net profit",
        "earnings per share", "eps",
    }

    # Period header patterns
    PERIOD_PATTERNS = [
        (r"three months ended", "quarter"),
        (r"six months ended", "half_year"),
        (r"twelve months ended", "fiscal_year"),
        (r"for the year ended", "fiscal_year"),
        (r"fiscal year", "fiscal_year"),
        (r"year ended", "fiscal_year"),
        (r"quarter ended", "quarter"),
    ]

    def __init__(self) -> None:
        self._accession = ""
        self._document = ""
        self._source_form = "6-K"

    def extract(self, html_bytes: bytes, meta: dict[str, Any] | None = None) -> ExtractedData:
        """Main entry point. Parse HTML and return structured records."""
        result = ExtractedData()
        if meta:
            self._accession = meta.get("accession", "")
            self._document = meta.get("document", "")
            self._source_form = meta.get("form", "6-K")
            result.meta = meta

        soup = BeautifulSoup(html_bytes, "lxml")
        tables = soup.find_all("table")

        # ── S4: Table triage — find financial data tables ──
        data_tables = self._find_financial_tables(tables)
        logger.info("LANE2: found %d financial tables out of %d total",
                    len(data_tables), len(tables))

        for table_info in data_tables:
            # ── S5: Parse column headers → periods ──
            periods = self._parse_column_headers(table_info)
            if not periods:
                logger.debug("LANE2: table %d has no parseable periods", table_info["index"])
                continue

            # ── S5b+S6: Parse rows → bind values to periods ──
            records = self._parse_rows(table_info, periods)
            for rec in records:
                result.add_record(rec)

        # Deduplicate: if same (period_start, period_end, currency) exists,
        # keep the one from the more detailed table (more metrics)
        result.records = self._deduplicate(result.records)

        # Currency fallback for "unknown" columns: infer from document-level
        # signals (NOT a guess — uses explicit $/RMB/US$ symbols in the text).
        # ★ This runs at CONSUMER level (after parsing), with explicit labeling.
        doc_currency = self._detect_document_currency(soup)
        for rec in result.records:
            if rec.currency == "unknown":
                if doc_currency:
                    rec.currency = doc_currency
                else:
                    rec.currency = "unknown"  # Stay unknown — don't guess

        # FX rate: parse from footnote (authoritative) instead of column division.
        # Footnote states exact rate: "RMB6.9931 to US$1.00 on December 31, 2025"
        fx_rate, fx_date = self._parse_fx_rate_footnote(soup)
        if fx_rate:
            for rec in result.records:
                if rec.currency == "CNY" and not rec.fx_rate:
                    rec.fx_rate = fx_rate
                    rec.fx_rate_date = fx_date

        # ── G4: Guidance extraction ──
        guidance = self._parse_guidance(soup)
        for g in guidance:
            result.add_guidance(g)

        return result

    def _detect_document_currency(self, soup: BeautifulSoup) -> str | None:
        """Detect currency from document-level signals (not column-level).

        Uses explicit text signals — does NOT guess:
        - "RMB" / "Renminbi" appearing in headers or footnotes → CNY
        - "US$" / "U.S. dollars" in headers → USD
        - "€" / "EUR" → EUR
        - No signal → None (stays unknown)

        For FPI documents that have BOTH RMB and US$:
          RMB is the primary reporting currency → return CNY

        Note: US domestic companies (AAPL 8-K) often don't label currency
        at all — their tables say "(In millions)" with no $ symbol.
        This is a legitimate USD-default convention for SEC domestic filings,
        NOT a guess. We check for absence of foreign currency signals.
        """
        text = soup.get_text(" ", strip=True)

        # Count currency signal occurrences
        rmb_count = len(re.findall(r"\bRMB\b|\bRenminbi\b", text, re.IGNORECASE))
        usd_count = len(re.findall(r"US\$|U\.S\. dollar", text, re.IGNORECASE))
        eur_count = len(re.findall(r"\bEUR\b|€", text))
        hkd_count = len(re.findall(r"\bHKD\b|\bHK\$\b", text))

        # Strong signals (explicit currency labels)
        if rmb_count > 3:
            return "CNY"
        if eur_count > 3:
            return "EUR"
        if hkd_count > 3:
            return "HKD"
        if usd_count > 3:
            return "USD"

        # Weak signal: US domestic filing with "(In millions)" and no
        # foreign currency labels. This is the standard SEC convention —
        # domestic companies report in USD without labeling it.
        # We check: "In millions" present + no RMB/EUR/HKD anywhere
        has_in_millions = "in millions" in text.lower()
        no_foreign = rmb_count == 0 and eur_count == 0 and hkd_count == 0
        if has_in_millions and no_foreign:
            return "USD"  # US domestic default convention

        # No signal → return None (truly unknown)
        return None

    def _parse_fx_rate_footnote(self, soup: BeautifulSoup) -> tuple[float | None, str | None]:
        """Parse FX rate from the footnote text (authoritative source).

        SEC FPI filings state the exact exchange rate used:
        "all translations from RMB to US$ are made at a rate of RMB6.9931
         to US$1.00, the exchange rate on December 31, 2025"

        Returns (fx_rate, fx_rate_date) or (None, None) if not found.
        """
        text = soup.get_text(" ", strip=True)

        # Pattern: "RMB X.XXXX to US$1.00" or "rate of RMB X.XX to US$1.00"
        match = re.search(
            r"rate\s+of\s+RMB\s*(\d+\.\d+)\s*to\s*US\$?\s*1\.00",
            text, re.IGNORECASE,
        )
        if not match:
            # Fallback: "RMB X.XX = US$1.00"
            match = re.search(r"RMB\s*(\d+\.\d{2,6})\s*(?:to|=|per)\s*US\$?\s*1", text, re.IGNORECASE)

        fx_rate = None
        if match:
            fx_rate = float(match.group(1))

        # Parse the date
        fx_date = None
        date_match = re.search(
            r"(?:exchange rate on|as of)\s+"
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
            text, re.IGNORECASE,
        )
        if date_match:
            months = {
                "january": 1, "february": 2, "march": 3, "april": 4,
                "may": 5, "june": 6, "july": 7, "august": 8,
                "september": 9, "october": 10, "november": 11, "december": 12,
            }
            month = months[date_match.group(1).lower()]
            fx_date = f"{date_match.group(3)}-{month:02d}-{int(date_match.group(2)):02d}"

        return fx_rate, fx_date

    # ── Guidance extraction (Business Outlook section) ──────────

    # Period label patterns: "For the first quarter of 2026" → "Q1 2026"
    _QUARTER_WORDS = {
        "first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4",
    }

    def _parse_guidance(self, soup: BeautifulSoup) -> list[GuidanceRecord]:
        """Extract company guidance from the Business Outlook section.

        Handles two forms:
        - Absolute range (XPEV): "Total revenues to be between RMB12.20 billion
          and RMB13.28 billion, representing a year-over-year decrease of
          approximately 16.01% to 22.84%"
        - Count range: "Deliveries of vehicles to be between 61,000 and 66,000"

        Design notes:
        - yoy_change is normalized to signed % (decrease → negative)
        - Range direction: text says "decrease of 16.01% to 22.84%" but the
          LOW value (12.20B) maps to the LARGER decrease (-22.84%).
          So yoy_change_low = -22.84, yoy_change_high = -16.01.
        - No rejection here — magnitude sanity checks belong to the
          assertion layer (flag, not reject).
        """
        text = soup.get_text(" ", strip=True)
        results: list[GuidanceRecord] = []

        # Locate outlook section: "Business Outlook" or "expects:"
        outlook_match = re.search(
            r"(?:Business Outlook|Outlook|Guidance)\s*(.*?)(?:Conference Call|Safe Harbor|About |$)",
            text, re.IGNORECASE | re.DOTALL,
        )
        if not outlook_match:
            return results
        outlook_text = outlook_match.group(1)[:2000]  # Cap section size

        # Extract period label: "For the first quarter of 2026"
        period_label = ""
        period_match = re.search(
            r"[Ff]or the (first|second|third|fourth) quarter of (\d{4})",
            outlook_text,
        )
        if period_match:
            q = self._QUARTER_WORDS.get(period_match.group(1).lower(), "")
            period_label = f"{q} {period_match.group(2)}"
        else:
            fy_match = re.search(r"[Ff]or (?:fiscal year|the year) (\d{4})", outlook_text)
            if fy_match:
                period_label = f"FY {fy_match.group(1)}"

        # Extract metric ranges:
        # "Total revenues to be between RMB12.20 billion and RMB13.28 billion"
        # "Deliveries of vehicles to be between 61,000 and 66,000"
        range_pattern = re.compile(
            r"([A-Za-z\s]+?)\s+to be between\s+"
            r"(RMB|US\$|\$)?\s*([\d,.]+)\s*(billion|million)?\s*"
            r"and\s+(?:RMB|US\$|\$)?\s*([\d,.]+)\s*(billion|million)?",
            re.IGNORECASE,
        )

        # YoY pattern (appears right after each range):
        # "representing a year-over-year decrease of approximately 16.01% to 22.84%"
        yoy_pattern = re.compile(
            r"year-over-year\s+(increase|decrease)\s+of\s+approximately\s+"
            r"([\d.]+)%\s*to\s*([\d.]+)%",
            re.IGNORECASE,
        )

        for m in range_pattern.finditer(outlook_text):
            raw_metric = m.group(1).strip().lower()
            cur_symbol = m.group(2) or ""
            low_val = self._scale_value(m.group(3), m.group(4))
            high_val = self._scale_value(m.group(5), m.group(6) or m.group(4))
            if low_val is None or high_val is None:
                continue

            # Normalize metric name
            metric_name = self._normalize_guidance_metric(raw_metric)
            if not metric_name:
                continue

            # Currency
            if cur_symbol.upper() == "RMB":
                currency = "CNY"
            elif cur_symbol in ("US$", "$"):
                currency = "USD"
            else:
                currency = "count"  # e.g. deliveries

            # Look for YoY clause immediately following this range
            yoy_low = yoy_high = None
            tail = outlook_text[m.end():m.end() + 300]
            yoy_m = yoy_pattern.search(tail)
            if yoy_m:
                direction = yoy_m.group(1).lower()
                pct_a = float(yoy_m.group(2))
                pct_b = float(yoy_m.group(3))
                if direction == "decrease":
                    # Text order is small-decrease first; map to value order:
                    # low value → larger decrease, high value → smaller decrease
                    yoy_low = -max(pct_a, pct_b)
                    yoy_high = -min(pct_a, pct_b)
                else:
                    yoy_low = min(pct_a, pct_b)
                    yoy_high = max(pct_a, pct_b)

            # Evidence-based confidence (not a decorative constant).
            # Each signal independently observed → additive score.
            # For monetary metrics: period + currency + YoY + scale
            # For count metrics:  period + explicit_unit + YoY + scale
            # (Currency dimension is replaced with "unit explicit" for counts.)
            raw_conf = 0.30  # base: found in Business Outlook section
            if period_label:
                raw_conf += 0.15  # explicit period label "Q1 2026"
            if yoy_low is not None:
                raw_conf += 0.15  # explicit YoY comparison clause
            if m.group(4) or m.group(6):
                raw_conf += 0.10  # explicit scale word (billion/million)

            if currency in ("CNY", "USD"):
                raw_conf += 0.10  # explicit currency prefix (RMB/US$)
            elif currency == "count":
                # Check for explicit unit mention ("vehicles", "units", etc.)
                if any(w in raw_metric.lower() for w in
                       ("vehicle", "deliveries", "units", "unit", "cars")):
                    raw_conf += 0.10  # explicit unit reference

            conf = min(raw_conf, 0.95)

            results.append(GuidanceRecord(
                period_label=period_label,
                metric_name=metric_name,
                low=low_val,
                high=high_val,
                currency=currency,
                yoy_change_low=yoy_low,
                yoy_change_high=yoy_high,
                source=self._source_form,
                accession=self._accession,
                extraction_conf=round(conf, 2),
            ))

        return results

    @staticmethod
    def _scale_value(num_str: str, scale_word: str | None) -> float | None:
        """Parse '12.20' + 'billion' → 12.20e9."""
        try:
            val = float(num_str.replace(",", ""))
        except ValueError:
            return None
        if scale_word:
            w = scale_word.lower()
            if w == "billion":
                val *= 1e9
            elif w == "million":
                val *= 1e6
        return val

    @staticmethod
    def _normalize_guidance_metric(raw: str) -> str | None:
        """Map raw guidance metric text to unified names."""
        raw = raw.strip().lower()
        mapping = {
            "total revenues": "revenue",
            "revenues": "revenue",
            "revenue": "revenue",
            "deliveries of vehicles": "deliveries",
            "vehicle deliveries": "deliveries",
            "deliveries": "deliveries",
            "net income": "net_income",
            "eps": "eps",
        }
        for k, v in mapping.items():
            if raw.endswith(k) or raw == k:
                return v
        return None

    # ── S4: Table triage ──────────────────────────────────────

    def _find_financial_tables(self, tables: list[Tag]) -> list[dict]:
        """Identify which tables contain financial data (not layout).

        Signals:
        - Contains period headers ("Three Months Ended", "Year Ended", etc.)
        - Contains financial keywords (Total revenues, Gross profit, etc.)
        - Has enough rows and numeric cells
        """
        results = []

        for i, table in enumerate(tables):
            rows = table.find_all("tr")
            if len(rows) < 3:
                continue

            table_text = table.get_text(" ", strip=True).lower()

            # Must have period header
            has_period = any(
                re.search(pattern, table_text)
                for pattern, _ in self.PERIOD_PATTERNS
            )
            if not has_period:
                continue

            # Must have financial keywords
            financial_hits = sum(
                1 for kw in self.INCOME_KEYWORDS if kw in table_text
            )
            if financial_hits < 2:
                continue

            # Parse column structure
            col_data = self._analyze_columns(table)

            results.append({
                "index": i,
                "table": table,
                "rows": rows,
                "financial_keywords": financial_hits,
                "columns": col_data,
            })

        # Sort by financial keyword count desc (most relevant first)
        results.sort(key=lambda x: x["financial_keywords"], reverse=True)
        return results

    # ── S4b: Column analysis ──────────────────────────────────

    def _analyze_columns(self, table: Tag) -> list[dict]:
        """Analyze table column structure from header rows.

        Returns a list of column descriptors, each with:
        - col_index: which <td> index
        - currency: "RMB" / "US$" / None
        - period_text: raw text from header (e.g. "December 31, 2025")
        """
        rows = table.find_all("tr")
        # Header is usually in the first 4 rows
        # Build column → metadata mapping

        columns = []
        for row in rows[:5]:
            cells = row.find_all(["td", "th"])
            for ci, cell in enumerate(cells):
                text = cell.get_text(strip=True).replace("\xa0", " ")
                # Check for currency markers
                currency = None
                if "rmb" in text.lower() or "renminbi" in text.lower():
                    currency = "CNY"
                elif "us$" in text.lower() or "usd" in text.lower():
                    currency = "USD"

                if currency:
                    while len(columns) <= ci:
                        columns.append({"col_index": len(columns), "currency": None, "period_text": ""})
                    columns[ci]["currency"] = currency

        return columns

    # ── S5: Column header → period mapping ────────────────────

    def _parse_column_headers(self, table_info: dict) -> list[dict]:
        """Parse column headers to extract period (start/end) for each column.

        Strategy: SEC tables use sparse columns with empty cells as spacers.
        We build "logical columns" by finding the column positions where
        actual header text appears (dates + currency), then match data values
        to those positions.

        Example Table 37 header:
          R2: [·] [·] [2024] [·] [·] [2025] [·] [·] [2025] [·]
          R3: [·] [·] [RMB]  [·] [·] [RMB]  [·] [·] [US$]  [·]

        This gives us 3 logical columns:
          Col A: date=2024-12-31, currency=CNY, header_col=2
          Col B: date=2025-12-31, currency=CNY, header_col=5
          Col C: date=2025-12-31, currency=USD, header_col=8
        """
        table = table_info["table"]
        rows = table.find_all("tr")
        table_text = table.get_text(" ", strip=True)

        # Determine overall period type
        period_type = "quarter"
        for pattern, ptype in self.PERIOD_PATTERNS:
            if re.search(pattern, table_text.lower()):
                period_type = ptype
                break

        # For fiscal_year tables, the month/day is often in a shared colspan
        # header like "For the Year Ended December 31" — not column-specific.
        # Extract it as a fallback for year-only columns.
        shared_month_day = None
        if period_type == "fiscal_year":
            md_match = re.search(
                r"(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+(\d{1,2})",
                table_text, re.IGNORECASE,
            )
            if md_match:
                shared_month_day = md_match.group()

        # Step 1: Scan header rows to find date+currency positions
        # Build map: col_index → {date, currency}
        #
        # SEC tables often split dates across rows:
        #   Row 2: "December 31," / "September 30," / "December 31,"
        #   Row 3: "2024" / "2025" / "2025"
        # We must merge them: col 5 → "September 30, 2025"
        col_month_day: dict[int, str] = {}  # "December 31," etc.
        col_year: dict[int, str] = {}       # "2024" etc.
        col_currencies: dict[int, str] = {}

        for row in rows[:5]:
            cells = row.find_all(["td", "th"])
            for ci, cell in enumerate(cells):
                text = cell.get_text(strip=True).replace("\xa0", " ")

                # Try to parse full date AND/OR month+day
                # These are independent: "September 30," has no year so
                # _parse_header_date returns None, but we still need to
                # capture the month+day for cross-row merging.
                date = self._parse_header_date(text)

                # Capture month+day (even without year) for cross-row merge
                month_day_match = re.search(
                    r"(January|February|March|April|May|June|July|August|"
                    r"September|October|November|December)\s+(\d{1,2}),?",
                    text, re.IGNORECASE,
                )
                if month_day_match and not re.search(r"\d{4}", text):
                    col_month_day[ci] = month_day_match.group()

                # Store full date if text has month+day+year
                if date and re.search(
                    r"(January|February|March|April|May|June|July|August|"
                    r"September|October|November|December).*\d{4}",
                    text, re.IGNORECASE,
                ):
                    col_month_day[ci] = date

                # Try standalone year ("2024")
                if re.match(r"^(20\d{2})$", text):
                    col_year[ci] = text

                # Currency
                if "rmb" in text.lower() or "renminbi" in text.lower():
                    col_currencies[ci] = "CNY"
                elif "us$" in text.lower() or "usd" in text.lower():
                    col_currencies[ci] = "USD"

        # Merge month_day + year into full dates per column
        col_dates: dict[int, str] = {}
        all_cols = set(col_month_day.keys()) | set(col_year.keys())
        for ci in all_cols:
            md = col_month_day.get(ci, "")
            yr = col_year.get(ci, "")

            if md and re.match(r"\d{4}-\d{2}-\d{2}", md):
                # Already a full date
                col_dates[ci] = md
            elif md and yr:
                # Combine "September 30," + "2025" → parse
                combined = f"{md} {yr}"
                parsed = self._parse_header_date(combined)
                if parsed:
                    col_dates[ci] = parsed
            elif yr and not md:
                # Year only, no column-specific month/day.
                # For fiscal_year tables, use shared_month_day from colspan header
                # (e.g., "For the Year Ended December 31" applies to all columns).
                # For quarter tables, DO NOT guess — return None (unknown period).
                if shared_month_day:
                    combined = f"{shared_month_day} {yr}"
                    parsed = self._parse_header_date(combined)
                    if parsed:
                        col_dates[ci] = parsed
                # else: period unknown, column will be skipped (safe)

        # Step 2: Merge date+currency into logical columns
        # A logical column is a (date, currency) pair.
        # Date and currency may be on different rows but SAME col_index.
        #
        # ★ RULE (6th same-pattern bug): do NOT default to USD when currency
        # is unknown. Return "unknown" and let the consumer decide.
        # Explicit signals: RMB/CNY → CNY, US$/USD → USD, €/EUR → EUR
        # No signal → "unknown" (not a guess)
        logical_cols = {}
        for ci, date in col_dates.items():
            currency = col_currencies.get(ci, "unknown")
            key = (date, currency)
            if key not in logical_cols:
                end_date = date
                start_date = self._derive_start_date(end_date, period_type)
                logical_cols[key] = {
                    "end_date": end_date,
                    "start_date": start_date,
                    "period_type": period_type,
                    "currency": currency,
                    "header_cols": [ci],
                }
            else:
                logical_cols[key]["header_cols"].append(ci)

        # Step 3: Find data column positions for each logical column.
        # Data values may be offset from header position due to spacer cells.
        # We find them by scanning data rows for numeric values.
        # Strategy: for each logical column, find the nearest numeric cell
        # position to its header_col, across multiple data rows.
        for key, lc in logical_cols.items():
            data_cols = self._find_data_columns(rows, lc["header_cols"])
            lc["data_cols"] = data_cols

        return list(logical_cols.values())

    def _find_data_columns(self, rows: list[Tag], header_cols: list[int]) -> list[int]:
        """Find which cell positions contain numeric data for a header column.

        SEC tables use empty cells as spacers, so data may be 1-3 positions
        after the header. We scan data rows (after headers) and find the
        column positions with the most numeric values near each header_col.
        """
        from collections import Counter

        numeric_positions = Counter()

        for row in rows[4:]:  # Skip header rows
            cells = row.find_all("td")
            for ci in range(max(header_cols), min(len(cells), max(header_cols) + 4)):
                val = self._clean_value(cells[ci].get_text(strip=True))
                if val is not None:
                    numeric_positions[ci] += 1

        if not numeric_positions:
            return header_cols

        # Pick the position with most numeric values
        best_col = numeric_positions.most_common(1)[0][0]
        return [best_col]

    def _parse_header_date(self, text: str) -> str | None:
        """Extract a full date from header text like 'December 31, 2025'.

        ★ RULE: bare year "2025" returns None, NOT a guessed Dec 31.
        Guessing month/day when missing causes silent period errors
        (especially for non-Dec fiscal years: AAPL Sep, BABA Mar).
        Month/day must come from the text or cross-row header merge.
        """
        # Try full date: "December 31, 2025" or "March 28,2026" (no space after comma)
        match = re.search(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{1,2}),?\s*(\d{4})",
            text, re.IGNORECASE,
        )
        if match:
            month_str, day, year = match.groups()
            months = {
                "january": 1, "february": 2, "march": 3, "april": 4,
                "may": 5, "june": 6, "july": 7, "august": 8,
                "september": 9, "october": 10, "november": 11, "december": 12,
            }
            month = months[month_str.lower()]
            return f"{year}-{month:02d}-{int(day):02d}"

        # Bare year "2025" → return None, do NOT guess Dec 31.
        # Cross-row header merge handles "September 30," + "2025".
        # If only a year is available with no month/day, the caller must
        # explicitly decide what to do (error, flag unknown, or use row context).
        return None

    def _find_column_currency(self, rows: list[Tag], col_index: int) -> str | None:
        """Find currency label for a column by scanning header rows."""
        for row in rows[:5]:
            cells = row.find_all(["td", "th"])
            if col_index < len(cells):
                text = cells[col_index].get_text(strip=True).replace("\xa0", " ")
                if "rmb" in text.lower() or "renminbi" in text.lower():
                    return "CNY"
                if "us$" in text.lower() or "usd" in text.lower():
                    return "USD"
        return None

    def _derive_start_date(self, end_date: str, period_type: str) -> str:
        """Derive start date from end date and period type.

        For quarters ending Dec 31 (Q4): start = Oct 1
        For quarters ending Sep 30 (Q3): start = Jul 1
        For quarters ending Mar 31 (Q1): start = Jan 1
        """
        try:
            end = datetime.fromisoformat(end_date)
            if period_type == "quarter":
                # Quarter start = first day of the month 3 months before end month
                # Dec end → Oct start, Sep end → Jul start, etc.
                month = end.month - 2  # Dec(12) → Oct(10), Sep(9) → Jul(7)
                year = end.year
                if month <= 0:
                    month += 12
                    year -= 1
                return f"{year}-{month:02d}-01"
            elif period_type == "fiscal_year":
                # Year: start = first day of month after end month, previous year
                # Dec 31 2025 → Jan 1 2025
                month = end.month
                year = end.year - 1
                return f"{year}-{month + 1:02d}-01" if month < 12 else f"{year + 1}-01-01"
            elif period_type == "half_year":
                month = end.month - 5
                year = end.year
                if month <= 0:
                    month += 12
                    year -= 1
                return f"{year}-{month + 1:02d}-01"
        except (ValueError, TypeError):
            pass
        return ""

    # ── S5b+S6: Row parsing + value binding ───────────────────

    def _parse_rows(self, table_info: dict, periods: list[dict]) -> list[FinancialRecord]:
        """Parse data rows and bind values to periods.

        Uses data_cols (computed from numeric cell scanning) to correctly
        locate values even with spacer cells.
        """
        table = table_info["table"]
        rows = table.find_all("tr")

        METRIC_MAP = {
            "total revenues": "revenue",
            "total revenue": "revenue",
            "revenues": "revenue",
            "total net sales": "revenue",
            "net sales": "revenue",
            "total net revenues": "revenue",
            "cost of sales": "cost_of_sales",
            "cost of revenue": "cost_of_sales",
            "cost of products sold": "cost_of_sales",
            "total cost of sales": "cost_of_sales",
            "total cost of products sold": "cost_of_sales",
            "gross profit": "gross_profit",
            "gross margin": "gross_profit",
            "operating income": "operating_income",
            "operating loss": "operating_income",
            "operating expenses": "operating_income",
            "net income": "net_income",
            "net loss": "net_income",
            "net profit": "net_income",
            "net profit (loss)": "net_income",
            "basic and diluted net profit per share": "eps_diluted",
            "earnings per share": "eps_diluted",
            "diluted earnings per share": "eps_diluted",
        }

        # Collect values by period
        period_values: dict[str, dict[str, float]] = {}
        for p in periods:
            key = f"{p['start_date']}|{p['end_date']}|{p['currency']}"
            period_values[key] = {}
            p["_key"] = key

        for row in rows[4:]:  # Skip header rows
            row_text = row.get_text(" ", strip=True).lower()

            # Find which metric this row is
            metric_name = None
            for keyword, unified in METRIC_MAP.items():
                if keyword in row_text:
                    metric_name = unified
                    break

            if not metric_name:
                continue

            # Use row normalization to handle split cells ($, parens, etc.)
            cells = row.find_all("td")
            values = self._extract_values_from_row(cells)  # [(pos, val), ...]

            # After row normalization, decorative cells are merged.
            # Values are in TABLE COLUMN ORDER (left to right as they appear).
            # We must match values to periods in the SAME order.
            non_null_values = [val for pos, val in values if val is not None]

            # Use periods in their detection order (order of header_cols,
            # which reflects left-to-right column position in the table).
            # Do NOT sort by end_date — the table may show most-recent-first.
            ordered_periods = sorted(
                periods,
                key=lambda p: min(p.get("header_cols", [999])),
            )

            for idx, p in enumerate(ordered_periods):
                if idx < len(non_null_values):
                    period_values[p["_key"]][metric_name] = non_null_values[idx]

        # Build records (rest of logic same as before)
        records = []
        for p in periods:
            metrics = period_values.get(p["_key"], {})
            if not metrics:
                continue

            # Skip USD if CNY exists for same period
            if p["currency"] == "USD":
                cny_key = f"{p['start_date']}|{p['end_date']}|CNY"
                if cny_key in period_values and period_values[cny_key]:
                    continue

            # Determine value scale
            rev = metrics.get("revenue")
            if rev is not None and rev > 1e6:
                metrics = {k: v * 1000 if v else v for k, v in metrics.items()}

            # FX rate is parsed from footnote at extract() level,
            # NOT calculated from column division here (which is unreliable
            # due to column positioning issues).
            fx_rate = None
            fx_date = None

            records.append(FinancialRecord(
                period_start=p["start_date"],
                period_end=p["end_date"],
                period_type=p["period_type"],
                currency=p["currency"],
                fx_rate=fx_rate,
                fx_rate_date=fx_date,
                metrics=metrics,
                source=self._source_form,
                accession=self._accession,
                document=self._document,
                audited=False,
                extraction_method="table",
                extraction_conf=0.95,
            ))

        return records

    # ── Row normalization (handles split cells: $ in separate <td>, ( ) split) ──

    # Characters that are "decorative" — they modify adjacent numeric cells
    # but don't themselves contain data. When found alone in a cell, they
    # should be merged with the adjacent cell.
    _DECORATIVE_CHARS = set("$()（）—–-,% \xa0\u00a0\t\n")

    def _normalize_row(self, cells: list) -> list[str]:
        """Normalize a table row by merging decorative cells into adjacent values.

        SEC tables from financial printers (Donnelley/Toppan) often split
        values across cells:
          [<td>(</td><td>16,583,754</td><td>)</td>]  → "(16,583,754)"
          [<td>$</td><td>3.18</td><td>billion</td>]  → "$3.18"
          [<td>22.25</td><td>%</td>]                  → "22.25%"

        This function merges decorative cells with their neighbors before
        tokenizing values, so downstream parsing sees clean tokens.
        """
        # Extract raw text from each cell
        raw_texts = []
        for cell in cells:
            text = cell.get_text(strip=True).replace("\xa0", " ").replace("\u00a0", " ")
            raw_texts.append(text)

        # Merge decorative cells into preceding non-empty cell
        merged: list[str] = []
        for text in raw_texts:
            if not text:
                continue

            # Check if this cell is purely decorative
            stripped = text.strip()
            is_decorative = len(stripped) <= 2 and all(c in self._DECORATIVE_CHARS for c in stripped)

            if is_decorative and merged:
                # Merge into previous cell
                merged[-1] += stripped
            elif is_decorative and not merged:
                # Leading decorative (rare) — skip
                continue
            else:
                merged.append(text)

        return merged

    def _extract_values_from_row(self, cells: list) -> list[tuple[int, float | None]]:
        """Extract numeric values from a row, with positions.

        Returns list of (position_index, value) where position_index is
        the index in the merged cell list (not raw cell index).
        """
        merged = self._normalize_row(cells)
        results = []
        for i, text in enumerate(merged):
            val = self._parse_numeric(text)
            results.append((i, val))
        return results

    def _parse_numeric(self, text: str) -> float | None:
        """Parse a numeric value from text, handling all SEC formatting quirks.

        Handles:
        - Parenthesized negatives: (1,234) → -1234
        - Commas: 1,234,567 → 1234567
        - Currency prefixes: RMB, $, US$
        - Percent suffix: 38.2% → 38.2
        - Dashes/nil: — → None
        - &nbsp; and unicode spaces
        """
        if not text:
            return None

        text = text.replace("\xa0", "").replace("\u00a0", "").strip()

        # Handle dashes/nil
        if text in ("—", "–", "-", "nil", "—", ".", "—"):
            return None

        # Handle parenthesized negatives
        is_negative = False
        if text.startswith("(") and ")" in text:
            text = text.replace("(", "").replace(")", "")
            is_negative = True
        elif text.startswith("("):
            # Opening paren without closing (from split cell merge)
            text = text.lstrip("(")
            is_negative = True

        # Remove currency markers, commas
        text = text.replace("$", "").replace("US$", "").replace(",", "")
        text = re.sub(r"^RMB\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^USD\s*", "", text, flags=re.IGNORECASE)

        # Handle percent
        if text.endswith("%"):
            text = text[:-1]

        # Remove any remaining non-numeric chars (spaces, etc.)
        text = text.strip()

        try:
            val = float(text)
            if is_negative:
                val = -val
            return val
        except ValueError:
            return None

    def _clean_value(self, text: str) -> float | None:
        """Legacy single-cell value cleaner (kept for header scanning).
        Use _parse_numeric for row data."""
        return self._parse_numeric(text)

    # ── Deduplication ─────────────────────────────────────────

    def _deduplicate(self, records: list[FinancialRecord]) -> list[FinancialRecord]:
        """Keep the best record per (period_start, period_end, currency).

        "Best" = most metrics populated.
        """
        from collections import defaultdict

        grouped: dict[tuple, list[FinancialRecord]] = defaultdict(list)
        for r in records:
            key = (r.period_start, r.period_end, r.currency)
            grouped[key].append(r)

        result = []
        for key, group in grouped.items():
            # Sort by number of non-None metrics (desc)
            group.sort(
                key=lambda r: sum(1 for v in r.metrics.values() if v is not None),
                reverse=True,
            )
            result.append(group[0])

        return result
