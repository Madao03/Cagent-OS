"""Debug row normalization value ordering."""
import sys
sys.path.insert(0, "src")
from pathlib import Path
from bs4 import BeautifulSoup
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor

html = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html").read_bytes()
soup = BeautifulSoup(html, "lxml")
tables = soup.find_all("table")
ext = EarningsReleaseExtractor()

# Check Table 37 (FY income statement)
table = tables[37]
rows = table.find_all("tr")

print("Table 37 rows with Total revenues:")
for ri, row in enumerate(rows):
    text = row.get_text(" ", strip=True).lower()
    if "total revenues" in text:
        cells = row.find_all("td")
        merged = ext._normalize_row(cells)
        values = ext._extract_values_from_row(cells)
        non_null = [(p, v) for p, v in values if v is not None]
        print(f"  Row {ri}: {len(cells)} cells → {len(merged)} merged → {len(non_null)} values")
        print(f"  Merged: {merged[:10]}")
        print(f"  Values: {non_null[:10]}")

print("\nTable 33 (Q4 income statement) rows with Total revenues:")
table = tables[33]
rows = table.find_all("tr")
for ri, row in enumerate(rows):
    text = row.get_text(" ", strip=True).lower()
    if "total revenues" in text and "vehicle" not in text:
        cells = row.find_all("td")
        merged = ext._normalize_row(cells)
        values = ext._extract_values_from_row(cells)
        non_null = [(p, v) for p, v in values if v is not None]
        print(f"  Row {ri}: {len(cells)} cells → {len(merged)} merged → {len(non_null)} values")
        print(f"  Merged: {merged[:12]}")
        print(f"  Values: {non_null[:10]}")
