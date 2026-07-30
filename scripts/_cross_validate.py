"""Cross-template validation: run extractor on all fixtures."""
import json, sys
from pathlib import Path
sys.path.insert(0, "src")
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor

FIXTURE_DIR = Path("tests/fixtures/edgar")
ext = EarningsReleaseExtractor()

for html_file in sorted(FIXTURE_DIR.glob("*.html")):
    meta_file = html_file.with_suffix(".meta.json")
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}

    data = ext.extract(html_file.read_bytes(), meta=meta)
    label = meta.get("label", "?")

    print(f"\n{'='*80}")
    print(f"{html_file.name} ({html_file.stat().st_size//1024}KB) [{label}]")
    print(f"Records: {len(data.records)}")

    if not data.records:
        print("  (no records extracted)")
        continue

    for r in data.records:
        rev = r.metrics.get("revenue")
        ni = r.metrics.get("net_income")
        rev_str = f"rev={rev/1e9:.2f}B" if rev and rev > 1e6 else f"rev={rev}"
        ni_str = f"ni={ni/1e9:.2f}B" if ni and abs(ni) > 1e6 else f"ni={ni}"
        print(f"  {r.period_type:12s} {r.period_start}→{r.period_end} [{r.currency}] {rev_str} {ni_str}")
