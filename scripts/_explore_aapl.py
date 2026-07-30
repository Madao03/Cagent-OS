"""Explore AAPL 8-K table structure to find why extractor fails."""
from pathlib import Path
from bs4 import BeautifulSoup
import re

html = Path("tests/fixtures/edgar/aapl_8k_earnings.html").read_bytes()
soup = BeautifulSoup(html, "lxml")
tables = soup.find_all("table")
print(f"Total tables: {len(tables)}")

# Check period patterns and financial keywords in all tables
for i, table in enumerate(tables):
    text = table.get_text(" ", strip=True)
    has_period = bool(re.search(r"three months ended|twelve months ended|year ended", text.lower()))
    has_rev = "total net sales" in text.lower() or "total revenues" in text.lower() or "net sales" in text.lower()
    rows = table.find_all("tr")
    if has_period or has_rev:
        print(f"\n[Table {i}] rows={len(rows)} period={'Y' if has_period else 'N'} rev={'Y' if has_rev else 'N'}")
        # Show first 5 rows
        for ri, row in enumerate(rows[:6]):
            cells = [c.get_text(strip=True).replace("\xa0", " ")[:25] for c in row.find_all(["td", "th"])]
            non_empty = [c for c in cells if c]
            if non_empty:
                print(f"  R{ri}: {non_empty[:8]}")
