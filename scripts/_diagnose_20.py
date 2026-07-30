"""Diagnose: is 20.38B from Q3 column (period mismatch) or vehicle sales row (metric mismatch)?"""
import sys
sys.path.insert(0, "src")
from pathlib import Path
from bs4 import BeautifulSoup

html = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html").read_bytes()
soup = BeautifulSoup(html, "lxml")
tables = soup.find_all("table")

# Check Table 22 (Highlights) - which row/col has 20.38
table = tables[22]
rows = table.find_all("tr")
print("=== TABLE 22 (Highlights) — rows containing 20.38 ===")
for ri, row in enumerate(rows):
    cells = row.find_all("td")
    cell_texts = [c.get_text(strip=True).replace("\xa0", " ") for c in cells]
    for ci, t in enumerate(cell_texts):
        if "20.38" in t or "20,380" in t:
            print(f"  Row {ri}, Col {ci}: row_label={cell_texts[0][:40]}, value={t}")

print()

# Check Table 33 (Q4 detailed) - which row/col has 20.38
table = tables[33]
rows = table.find_all("tr")
print("=== TABLE 33 (Q4 detailed) — rows containing 20.38 or 20,380 ===")
for ri, row in enumerate(rows):
    cells = row.find_all("td")
    cell_texts = [c.get_text(strip=True).replace("\xa0", " ") for c in cells]
    for ci, t in enumerate(cell_texts):
        if "20.38" in t or "20,380" in t:
            print(f"  Row {ri}, Col {ci}: row_label={cell_texts[0][:40]}, value={t}")

# Also check what row has 22.25/22,253
print("\n=== TABLE 33 — rows containing 22.25 or 22,253 ===")
for ri, row in enumerate(rows):
    cells = row.find_all("td")
    cell_texts = [c.get_text(strip=True).replace("\xa0", " ") for c in cells]
    for ci, t in enumerate(cell_texts):
        if "22.25" in t or "22,253" in t:
            print(f"  Row {ri}, Col {ci}: row_label={cell_texts[0][:40]}, value={t}")

# Check Table 33 headers to see column meaning
print("\n=== TABLE 33 headers ===")
for ri in range(5):
    cells = rows[ri].find_all(["td", "th"])
    texts = [c.get_text(strip=True).replace("\xa0", " ")[:30] for c in cells]
    non_empty = [(ci, t) for ci, t in enumerate(texts) if t and t != "\x95"]
    if non_empty:
        print(f"  Row {ri}: {non_empty}")
