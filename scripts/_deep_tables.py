"""Deep dive into key tables in XPEV fixture."""
from pathlib import Path
from bs4 import BeautifulSoup

FIXTURE = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html")
soup = BeautifulSoup(FIXTURE.read_bytes(), "lxml")
tables = soup.find_all("table")

for idx in [22, 33, 37]:
    table = tables[idx]
    rows = table.find_all("tr")
    print(f"\n{'='*80}")
    print(f"TABLE {idx}: {len(rows)} rows")
    print(f"{'='*80}")

    for ri, row in enumerate(rows[:15]):  # First 15 rows
        cells = row.find_all(["td", "th"])
        cell_texts = []
        for cell in cells:
            text = cell.get_text(strip=True).replace("\xa0", " ")[:25]
            colspan = cell.get("colspan", "1")
            cell_texts.append(f"[{text}]" if text else "[·]")
        print(f"  R{ri:2d} ({len(cells):2d}c): {' '.join(cell_texts)}")
    if len(rows) > 15:
        print(f"  ... ({len(rows) - 15} more rows)")
