"""Find XPEV Q3 2025 earnings 6-K."""
import requests
HEADERS = {"User-Agent": "CagentOS madaocage@gmail.com"}
resp = requests.get("https://data.sec.gov/submissions/CIK0001810997.json", headers=HEADERS, timeout=15)
sub = resp.json()
recent = sub["filings"]["recent"]
for i, f in enumerate(recent["form"][:80]):
    if f == "6-K" and "2025-1" in recent["filingDate"][i]:
        accn = recent["accessionNumber"][i]
        print(f"{recent['filingDate'][i]} {accn}")
