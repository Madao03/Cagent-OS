"""Number normalizer — extract and normalize numbers from text for provenance matching.

Handles:
  - Chinese magnitudes: 亿/万/万亿/bp/%
  - Currency symbols: ¥/￥/$/US$
  - Scientific notation: 76.72B / 1.3T
  - Percentages: 15.6% / 0.156
  - Negative numbers: (16,583) / -578.6亿

Also provides a whitelist for non-data numbers that should be excluded
from provenance checks (years, quarter labels, list indices, etc.).
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import NamedTuple

logger = logging.getLogger(__name__)


class ExtractedNumber(NamedTuple):
    """A number extracted from text, normalized to its raw value."""
    raw: str           # original text match: "¥767.2亿"
    value: float       # normalized: 76720000000.0
    start: int         # position in source text
    end: int           # position in source text
    is_data: bool      # True if this looks like data (not a year/index/label)


# ── Chinese / Western magnitude multipliers ────────────────────

_MAGNITUDE_MAP = {
    # Chinese
    "万亿": 1e12,
    "千亿": 1e11,
    "百亿": 1e10,
    "十亿": 1e9,
    "亿": 1e8,
    "千万": 1e7,
    "百万": 1e6,
    "万": 1e4,
    "千": 1e3,
    # Western abbreviations
    "T": 1e12,
    "B": 1e9,
    "M": 1e6,
    "K": 1e3,
}

# Currency symbols (stripped before parsing)
_CURRENCY_RE = re.compile(r'[¥￥$￥US\$]')

# Core number pattern: optional sign, digits with optional commas/decimal
_NUMBER_CORE = r'[-]?[\d,]+\.?\d*'

# Full pattern: optional currency + number + optional magnitude suffix
# ★ Trailing lookbehind uses [a-zA-Z0-9_] NOT \w, because \w with re.UNICODE
# matches Chinese characters — so "977亿美元" would be rejected by (?!\w)
# because 美 is a Unicode word char. We only want to avoid matching inside
# ASCII identifiers (file123, var_456), not block Chinese suffixes.
_FULL_NUMBER_RE = re.compile(
    r'(?<![a-zA-Z0-9_])'  # Not preceded by ASCII word char (allow Chinese prefix)
    r'(?:[¥￥$US\$]*)\s*'  # Optional currency prefix
    r'(?:\()?'  # Optional opening paren for negative accounting
    r'(-?\d[\d,]*\.?\d+)'  # Core number: digit, commas, decimal
    r'(?:\))?'  # Optional closing paren
    r'\s*'
    r'(万亿|千亿|百亿|十亿|亿|千万|百万|万|千|[TBMK])?'  # Magnitude suffix
    r'\s*%?'  # Optional percentage
    r'(?![a-zA-Z0-9_])',  # Not followed by ASCII word char (allow Chinese suffix like 美元)
)


def extract_numbers(text: str) -> list[ExtractedNumber]:
    """Extract all data-like numbers from text.

    Returns numbers with their positions and normalized values.
    Non-data numbers (years, indices, etc.) are filtered out by _is_data_number.
    """
    results: list[ExtractedNumber] = []

    for match in _FULL_NUMBER_RE.finditer(text):
        raw_match = match.group(0)
        number_str = match.group(1)
        magnitude_str = match.group(2) or ""

        # Parse the core number
        try:
            clean_num = number_str.replace(",", "")
            # Handle parenthesized negatives: (16,583) → -16583
            is_negative_paren = raw_match.strip().startswith("(") and raw_match.strip().endswith(")")
            value = float(clean_num)
            if is_negative_paren and value > 0:
                value = -value
        except ValueError:
            continue

        # Apply magnitude multiplier
        if magnitude_str in _MAGNITUDE_MAP:
            value *= _MAGNITUDE_MAP[magnitude_str]

        # Check if it's a percentage
        is_percent = "%" in raw_match
        if is_percent:
            # Keep as percentage value (don't convert to decimal here)
            # The matcher will handle both 15.6% and 0.156
            pass

        is_data = _is_data_number(raw_match, number_str, text, match.start())

        results.append(ExtractedNumber(
            raw=raw_match.strip(),
            value=value,
            start=match.start(),
            end=match.end(),
            is_data=is_data,
        ))

    return results


# ── Whitelist: numbers that are NOT data ───────────────────────

# These patterns should be excluded from provenance checks.
# Matching them as "untraced data" would flood the output with false positives.

# Pure 4-digit years (2018-2030 range)
_YEAR_RE = re.compile(r'^20[12]\d$')

# Quarter labels: Q1, Q2, Q3, Q4 (possibly with year: Q1 2025)
_QUARTER_RE = re.compile(r'^Q[1-4]', re.IGNORECASE)

# Fiscal year labels: FY2025, FY25
_FY_RE = re.compile(r'^FY\d{2,4}$', re.IGNORECASE)

# List indices: "1." "2." "3." at start of line or after whitespace
_INDEX_RE = re.compile(r'^\d+\.$')

# Version-like: 1.0, 2.1.3
_VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')

# Very small integers that are likely counts/labels, not data
# (e.g., "3 个因素", "5 条来源") — these are structural, not financial
_SMALL_COUNT_RE = re.compile(r'^\d{1,2}$')


# Document/form reference prefixes (EX-99.1, No. 5, Figure 3, Rule 144A, etc.)
_DOC_REF_PREFIXES = {"EX-", "NO.", "FIGURE", "TABLE", "SECTION", "EXHIBIT", "ITEM", "RULE", "FORM"}


def _is_data_number(raw: str, number_str: str, full_text: str, pos: int) -> bool:
    """Determine if a number is likely data (financial/metric) vs structural.

    Returns False for: years, quarter labels, list indices, version numbers,
    small counts (< 100 without currency/magnitude/percent context).
    """
    clean = number_str.replace(",", "")

    # Years: 2018-2030
    if _YEAR_RE.match(clean):
        return False

    # Quarter labels
    context_before = full_text[max(0, pos-3):pos].strip().upper()
    if "Q" in context_before and clean.isdigit() and int(clean) <= 4:
        return False

    # Document/form reference numbers: "EX-99.1", "No. 5", "Figure 3", "Rule 144A"
    context_before_8 = full_text[max(0, pos-8):pos].strip().upper()
    for prefix in _DOC_REF_PREFIXES:
        if context_before_8.endswith(prefix):
            return False

    # HK stock codes: "0700.HK", "1299.HK", "0001.HK"
    after_num = full_text[pos + len(raw_match_safe(raw)):pos + len(raw_match_safe(raw)) + 4]
    if ".HK" in after_num.upper()[:4]:
        return False

    # EDGAR accession numbers: "0001193125-26-215961"
    # The individual digit groups get extracted as separate numbers.
    # Check if we're inside an accession-like pattern in the surrounding text.
    import re as _re_acc
    context_60 = full_text[max(0, pos-30):pos+30]
    if _re_acc.search(r'\d{10}-\d{2}-\d{6}', context_60):
        return False

    # FY labels
    if _FY_RE.match(raw.strip()):
        return False

    # Version numbers
    if _VERSION_RE.match(clean):
        return False

    # List indices: "1." "2." etc (check if followed by space + text)
    after = full_text[pos + len(raw_match_safe(raw)):pos + len(raw_match_safe(raw)) + 2]
    if clean.isdigit() and raw.strip().endswith(".") and int(clean) <= 20:
        return False

    # Date components: covers multiple formats
    #   ISO full:   "2025-12-31"
    #   ISO short:  "2025-10", "2025.10", "2025/10" (fiscal periods without day)
    #   Chinese:    "2025年12月31日"
    #   Quarter:    "Q4 2025"
    surrounding_20 = full_text[max(0, pos-15):pos+15]
    if re.search(r'\d{4}[-/年.]\d{1,2}[-/月日]?', surrounding_20):
        return False
    # "Q4 2025" near the number
    if re.search(r'Q[1-4]\s*\d{4}', surrounding_20):
        return False

    # Exchange rates: "CNY/USD 6.9931", "汇率 7.25"
    # These are metadata, not financial results. Agent legitimately references
    # them for currency conversion context, but they should not be counted as
    # data numbers in provenance scoring.
    surrounding_40 = full_text[max(0, pos-20):pos+20]
    fx_keywords = ("汇率", "USD", "CNY", "fx", "exchange")
    if any(kw in surrounding_40 for kw in fx_keywords):
        return False

    # Small integers without any data context (currency, magnitude, percent)
    has_context = any(c in raw for c in "¥￥$%亿万亿") or any(
        raw.upper().endswith(suffix) for suffix in ["T", "B", "M", "K"]
    )
    if _SMALL_COUNT_RE.match(clean) and not has_context:
        # Check surrounding text for data context
        surrounding = full_text[max(0, pos-20):pos+20]
        data_context_words = ["营收", "利润", "收入", "增长", "下降", "revenue", "income",
                              "价格", "市值", "TVL", "单价", "同比", "环比"]
        if not any(w in surrounding for w in data_context_words):
            return False

    # ★ Chapter/section numbers at line start: "2.3", "3.1.1", "2.2"
    # These look like "X.Y" or "X.Y.Z" at the beginning of a line followed by space + text
    # Must check: is this at a line start and followed by non-digit content?
    line_start = full_text.rfind("\n", 0, pos)
    line_start = line_start + 1 if line_start != -1 else 0
    line_from_start = full_text[line_start:]
    # Match X.Y or X.Y.Z at line start, followed by space and text (not more digits)
    if re.match(r'^\s*\d+\.\d+(?:\.\d+)?\s+[^\d]', line_from_start):
        # But allow if the number has currency/magnitude context (e.g., "$2.3B")
        if not has_context and "." in clean:
            parts = clean.split(".")
            if all(p.isdigit() for p in parts) and all(int(p) < 100 for p in parts):
                return False

    # ★ Markdown heading numbers: lines starting with # or **bold**
    if re.match(r'^#{1,6}\s', line_from_start) or re.match(r'^\*\*[^*]+\*\*', line_from_start):
        return False

    return True


def raw_match_safe(raw: str) -> str:
    """Helper for position calculations."""
    return raw
