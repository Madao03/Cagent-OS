"""Download XPEV Q4 2025 earnings release fixture."""
import json
from pathlib import Path
from datetime import datetime, timezone
import requests

HEADERS = {"User-Agent": "CagentOS madaocage@gmail.com"}
accn = "0001193125-26-117623"
doc = "d270013dex991.htm"
accn_no_dash = accn.replace("-", "")
url = f"https://www.sec.gov/Archives/edgar/data/1810997/{accn_no_dash}/{doc}"

resp = requests.get(url, headers=HEADERS, timeout=30)
print(f"HTTP {resp.status_code}, {len(resp.content)} bytes")

if resp.status_code == 200:
    Path("tests/fixtures/edgar").mkdir(parents=True, exist_ok=True)
    fp = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html")
    fp.write_bytes(resp.content)

    meta = {
        "ticker": "XPEV", "accession": accn, "form": "6-K",
        "filing_date": "2026-03-20", "document": doc, "url": url,
        "content_type": resp.headers.get("content-type", ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "description": "XPENG Q4 2025 + FY2025 earnings press release (EX-99.1)",
        "expected": {
            "revenue_q4_cny": "XPEV Q4 2025 revenue in CNY",
            "revenue_fy_cny": "XPEV FY2025 revenue in CNY",
            "currency": "CNY",
            "period_q4": "2025-10-01 to 2025-12-31",
            "period_fy": "2025-01-01 to 2025-12-31",
            "contains_guidance": True,
            "contains_rmb_usd_dual": True,
        },
    }
    mp = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.meta.json")
    mp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved: {fp}")
    print(f"Meta:  {mp}")
