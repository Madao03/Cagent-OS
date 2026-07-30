"""List documents in a specific SEC filing."""
import requests, json, sys

HEADERS = {"User-Agent": "CagentOS madaocage@gmail.com"}

accn = sys.argv[1] if len(sys.argv) > 1 else "0001193125-26-092807"
cik_int = 1810997
accn_no_dash = accn.replace("-", "")

# SEC provides index.json for every filing directory
url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_no_dash}/index.json"
resp = requests.get(url, headers=HEADERS, timeout=15)
print(f"index.json: HTTP {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    items = data.get("directory", {}).get("item", [])
    print(f"Documents ({len(items)}):")
    for item in items:
        name = item.get("name", "")
        try:
            size = int(item.get("size", 0))
        except (ValueError, TypeError):
            size = 0
        ftype = item.get("type", "")
        size_str = f"{size/1024:.0f}KB" if size > 1024 else f"{size}B"
        print(f"  {name:50s} {size_str:>8s}  {ftype}")
else:
    # Fallback: try HTML index
    url2 = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_no_dash}/"
    resp2 = requests.get(url2, headers=HEADERS, timeout=15)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp2.text, "lxml")
    print("HTML index links:")
    for a in soup.select("table a"):
        href = a.get("href", "")
        if href and "." in href and not href.startswith("http") and not href.startswith("/"):
            print(f"  {a.text.strip()}")
