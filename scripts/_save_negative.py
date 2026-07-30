"""Download Q3 2022 false-positive as hard negative fixture."""
import json, requests, sys
from pathlib import Path
from datetime import datetime, timezone

ACCESSION = "0001193125-22-250567"
DOC = "d404869dex991.htm"
CIK = "1810997"
URL = f"https://www.sec.gov/Archives/edgar/data/{CIK}/000119312522250567/{DOC}"

HEADERS = {"User-Agent": "CagentOS madaocage@gmail.com"}

print(f"Downloading: {URL}")
resp = requests.get(URL, headers=HEADERS, timeout=30)
if resp.status_code != 200:
    print(f"FAILED: HTTP {resp.status_code}")
    sys.exit(1)

out_dir = Path("tests/fixtures/edgar")
out_dir.mkdir(parents=True, exist_ok=True)

html_path = out_dir / "xpev_6k_q32022_hard_negative.html"
html_path.write_bytes(resp.content)
print(f"Saved: {html_path} ({len(resp.content)} bytes)")

meta = {
    "ticker": "XPEV",
    "accession": ACCESSION,
    "form": "6-K",
    "filing_date": "2022-09-26",
    "document": DOC,
    "url": URL,
    "description": "HARD NEGATIVE: HKEX interim report filed BEFORE Q3 2022 quarter end. "
                   "Contains full financial tables but is NOT an earnings release. "
                   "Identified as false positive in S3 Phase 1 precision sweep.",
    "is_hard_negative": True,
    "failure_mode": "pre_quarter_end_filing",
    "quarter_end": "2022-09-30",
    "fetched_at": datetime.now(timezone.utc).isoformat(),
}
meta_path = out_dir / "xpev_6k_q32022_hard_negative.meta.json"
meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
print(f"Saved: {meta_path}")
