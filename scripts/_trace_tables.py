"""Trace which table produces the wrong Q4'25 value."""
import sys, json
sys.path.insert(0, "src")
from pathlib import Path
from bs4 import BeautifulSoup
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor, FinancialRecord

fixture = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html").read_bytes()
meta = json.loads(Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.meta.json").read_text())

soup = BeautifulSoup(fixture, "lxml")
tables = soup.find_all("table")
ext = EarningsReleaseExtractor()
ext._accession = meta.get("accession", "")
ext._document = meta.get("document", "")
ext._source_form = meta.get("form", "6-K")

# Replicate extract() but with logging
data_tables = ext._find_financial_tables(tables)
print(f"Financial tables found: {len(data_tables)}")

all_records = []
for table_info in data_tables:
    periods = ext._parse_column_headers(table_info)
    if not periods:
        continue

    records = ext._parse_rows(table_info, periods)

    # Log each table's output
    print(f"\n--- Table {table_info['index']} (kw={table_info['financial_keywords']}) ---")
    print(f"  Periods detected:")
    for p in periods:
        dc = p.get("data_cols", p.get("header_cols", []))
        hc = p.get("header_cols", [])
        print(f"    {p['end_date']} [{p['currency']}] header_col={hc} data_col={dc}")

    for r in records:
        rev = r.metrics.get("revenue")
        rev_str = f"{rev/1e9:.2f}B" if rev and rev > 1e6 else f"{rev}"
        if r.period_type == "quarter":
            print(f"  → {r.period_start}→{r.period_end} [{r.currency}] revenue={rev_str} metrics={len(r.metrics)}")
        all_records.append(r)

print(f"\n=== All quarter records before dedup ({sum(1 for r in all_records if r.period_type=='quarter')}) ===")
for r in all_records:
    if r.period_type == "quarter":
        rev = r.metrics.get("revenue")
        rev_str = f"{rev/1e9:.2f}B" if rev and rev > 1e6 else f"{rev}"
        print(f"  {r.period_start}→{r.period_end} [{r.currency}] revenue={rev_str} metrics={len([v for v in r.metrics.values() if v is not None])}")
