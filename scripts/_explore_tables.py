"""Explore table structure in XPEV earnings fixture.

Goal: understand which of the 40 tables are data tables vs layout scaffolding,
and which is the income statement.
"""
from pathlib import Path
from bs4 import BeautifulSoup, Tag
import re

FIXTURE = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html")
html = FIXTURE.read_bytes()
soup = BeautifulSoup(html, "lxml")
tables = soup.find_all("table")

print(f"Total tables: {len(tables)}")
print("=" * 80)

# Period header signals
PERIOD_PATTERNS = [
    r"[Tt]hree [Mm]onths [Ee]nded",
    r"[Ss]ix [Mm]onths [Ee]nded",
    r"[Tt]welve [Mm]onths [Ee]nded",
    r"[Ff]iscal [Yy]ear",
    r"[Yy]ear [Ee]nded",
]

# Financial keyword signals
FINANCIAL_KEYWORDS = [
    "revenue", "Revenues", "gross profit", "Gross profit",
    "operating", "net income", "Net income", "loss",
    "RMB", "shares", "earnings per share", "EPS",
    "total assets", "cash flow", "delivery",
]

def is_numeric_cell(text: str) -> bool:
    """Check if a cell contains a number (after basic cleanup)."""
    cleaned = re.sub(r"[\s,\$\(\)]", "", text.strip())
    if not cleaned:
        return False
    # Match number patterns: 1234, 1234.56, (1234), —, -
    if cleaned in ("—", "–", "-", "nil"):
        return True
    try:
        float(cleaned)
        return True
    except ValueError:
        return False

for i, table in enumerate(tables):
    rows = table.find_all("tr")
    if not rows:
        continue

    # Count columns (max across rows)
    max_cols = 0
    for row in rows:
        cells = row.find_all(["td", "th"])
        max_cols = max(max_cols, len(cells))

    # Count numeric cells
    total_cells = 0
    numeric_cells = 0
    table_text = ""

    for row in rows:
        cells = row.find_all(["td", "th"])
        for cell in cells:
            text = cell.get_text(strip=True)
            table_text += text + " "
            total_cells += 1
            if is_numeric_cell(text):
                numeric_cells += 1

    numeric_ratio = numeric_cells / total_cells if total_cells > 0 else 0

    # Check for period headers
    has_period = any(re.search(p, table_text) for p in PERIOD_PATTERNS)

    # Check for financial keywords
    has_financial = any(kw in table_text for kw in FINANCIAL_KEYWORDS)

    # Classify
    is_data_table = (
        len(rows) >= 3
        and max_cols >= 3
        and numeric_ratio > 0.3
    )

    # Mark as income statement
    is_income = (
        is_data_table
        and has_period
        and ("revenues" in table_text.lower() or "revenue" in table_text.lower())
    )

    # Print only interesting tables
    if is_data_table:
        status = "★ INCOME" if is_income else "✓ DATA"
        print(f"\n[Table {i:2d}] {status} | rows={len(rows)} cols={max_cols} numeric={numeric_ratio:.0%} "
              f"period={'Y' if has_period else 'N'} financial={'Y' if has_financial else 'N'}")
        # Print first 3 rows for context
        for row in rows[:4]:
            cells = [c.get_text(strip=True)[:20] for c in row.find_all(["td", "th"])]
            print(f"  {cells}")
    elif has_period or has_financial:
        print(f"\n[Table {i:2d}] ⚠ SMALL | rows={len(rows)} cols={max_cols} "
              f"period={'Y' if has_period else 'N'} financial={'Y' if has_financial else 'N'}")
        for row in rows[:2]:
            cells = [c.get_text(strip=True)[:30] for c in row.find_all(["td", "th"])]
            print(f"  {cells}")
