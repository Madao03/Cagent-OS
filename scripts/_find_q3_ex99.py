"""Find XPEV Q3 earnings EX-99.1."""
import requests, json
HEADERS = {"User-Agent": "CagentOS madaocage@gmail.com"}
CIK = 1810997

for accn in ["0001193125-25-284983", "0001193125-25-283869", "0001193125-25-303892"]:
    accn_no_dash = accn.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{accn_no_dash}/index.json"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        continue
    items = resp.json().get("directory", {}).get("item", [])
    print(f"\n{accn}:")
    for item in items:
        name = item.get("name", "")
        try:
            size = int(item.get("size", 0))
        except (ValueError, TypeError):
            size = 0
        size_str = f"{size//1024}KB" if size > 1024 else f"{size}B"
        if "ex99" in name.lower() or "ex-99" in name.lower():
            print(f"  ★ {name:40s} {size_str:>8s}")
        elif size > 50000:
            print(f"    {name:40s} {size_str:>8s}")
