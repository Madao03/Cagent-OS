"""Re-fetch XPEV Q2/Q3/FY2024 earnings releases.

Problem: XPEV files multiple 6-Ks on the same day. The auto-discovery
grabbed the HKEX notice (small) instead of the actual press release (large).

Solution: List ALL filings around each earnings date, find the one with
a large EX-99.1 (the real press release with financial tables).
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "CagentOS madaocage@gmail.com", "Accept-Encoding": "gzip, deflate"}
BASE_DATA = "https://data.sec.gov"
BASE_SEC = "https://www.sec.gov"
FIXTURE_DIR = Path("tests/fixtures/edgar")
XPEV_CIK = 1810997

MIN_INTERVAL = 0.15
_last = 0.0


def throttle():
    global _last
    elapsed = time.perf_counter() - _last
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last = time.perf_counter()


def list_documents(accession: str) -> list[dict]:
    """List all documents in a filing via index.json."""
    throttle()
    accn_no_dash = accession.replace("-", "")
    url = f"{BASE_SEC}/Archives/edgar/data/{XPEV_CIK}/{accn_no_dash}/index.json"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return []
    items = resp.json().get("directory", {}).get("item", [])
    result = []
    for i in items:
        name = i.get("name", "")
        try:
            size = int(i.get("size", 0))
        except (ValueError, TypeError):
            size = 0
        result.append({"name": name, "size": size})
    return result


def preview_doc(accession: str, doc_name: str, max_bytes: int = 4096) -> str:
    """Fetch first N chars of a document."""
    throttle()
    accn_no_dash = accession.replace("-", "")
    url = f"{BASE_SEC}/Archives/edgar/data/{XPEV_CIK}/{accn_no_dash}/{doc_name}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code != 200:
        return f"[HTTP {resp.status_code}]"
    soup = BeautifulSoup(resp.content[:max_bytes], "lxml")
    text = soup.get_text(" ", strip=True)
    return text[:200].replace("\n", " ")


def download(accession: str, doc_name: str, slug: str, label: str, filing_date: str):
    """Download and save fixture with .meta.json."""
    throttle()
    accn_no_dash = accession.replace("-", "")
    url = f"{BASE_SEC}/Archives/edgar/data/{XPEV_CIK}/{accn_no_dash}/{doc_name}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        print(f"  FAIL [{slug}]: HTTP {resp.status_code}")
        return False

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    fixture_path = FIXTURE_DIR / f"{slug}.html"
    fixture_path.write_bytes(resp.content)

    sha256 = hashlib.sha256(resp.content).hexdigest()
    meta = {
        "ticker": "XPEV", "accession": accession, "form": "6-K",
        "filing_date": filing_date, "document": doc_name, "url": url,
        "content_type": resp.headers.get("content-type", ""),
        "size_bytes": len(resp.content), "sha256": sha256,
        "fetched_at": datetime.now(timezone.utc).isoformat(), "label": label,
    }
    meta_path = FIXTURE_DIR / f"{slug}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  OK  [{slug}]: {len(resp.content)//1024}KB")
    return True


def find_earnings_6k_around_date(target_date: str, submissions: dict) -> list[dict]:
    """Find all 6-K filings within ±7 days of target_date."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])

    from datetime import datetime as dt, timedelta
    target = dt.fromisoformat(target_date)

    results = []
    for i, f in enumerate(forms):
        if f != "6-K":
            continue
        d = dates[i] if i < len(dates) else ""
        if not d:
            continue
        filing_dt = dt.fromisoformat(d)
        if abs((filing_dt - target).days) <= 7:
            results.append({
                "date": d,
                "accession": accessions[i] if i < len(accessions) else "",
            })
    return results


def main():
    # Get submissions
    throttle()
    resp = requests.get(f"{BASE_DATA}/submissions/CIK{XPEV_CIK:010d}.json", headers=HEADERS, timeout=15)
    submissions = resp.json()

    # Target earnings dates (approximate filing dates)
    targets = [
        ("2025-08-15", "xpev_6k_2025q2_earnings", "earnings_q2_2025", "Q2 2025"),
        ("2025-11-05", "xpev_6k_2025q3_earnings", "earnings_q3_2025", "Q3 2025"),
        ("2025-03-19", "xpev_6k_fy2024_earnings", "earnings_fy2024", "FY2024"),
    ]

    for target_date, slug, label, desc in targets:
        print(f"\n{'='*60}")
        print(f"Target: {desc} (around {target_date})")
        print(f"{'='*60}")

        candidates = find_earnings_6k_around_date(target_date, submissions)
        print(f"6-K filings within ±7 days: {len(candidates)}")

        best_doc = None
        best_accession = None
        best_size = 0

        for cand in candidates:
            docs = list_documents(cand["accession"])
            for doc in docs:
                name = doc["name"].lower()
                size = doc["size"]
                # Look for EX-99.1 HTML files that are large (>50KB = real press release)
                if "ex99" in name and name.endswith((".htm", ".html")) and size > 50000:
                    print(f"  Candidate: {cand['date']} {cand['accession']} → {doc['name']} ({size//1024}KB)")
                    if size > best_size:
                        best_size = size
                        best_doc = doc["name"]
                        best_accession = cand["accession"]

        if best_doc:
            print(f"\n  Selected: {best_doc} ({best_size//1024}KB)")
            download(best_accession, best_doc, slug, label, target_date)
        else:
            print(f"\n  No large EX-99.1 found, trying all candidates...")
            # Fallback: check all candidates' EX-99.1 previews
            for cand in candidates:
                docs = list_documents(cand["accession"])
                for doc in docs:
                    name = doc["name"].lower()
                    if "ex99" in name and name.endswith((".htm", ".html")):
                        preview = preview_doc(cand["accession"], doc["name"])
                        has_earnings = any(kw in preview.lower() for kw in
                            ["unaudited financial results", "reports", "quarter", "fiscal year"])
                        print(f"  {cand['date']} {doc['name']} ({doc['size']//1024}KB): {preview[:80]}")
                        if has_earnings and doc["size"] > best_size:
                            best_size = doc["size"]
                            best_doc = doc["name"]
                            best_accession = cand["accession"]

            if best_doc:
                print(f"\n  Selected via preview: {best_doc} ({best_size//1024}KB)")
                download(best_accession, best_doc, slug, label, target_date)
            else:
                print(f"\n  SKIP: no earnings press release found for {desc}")


if __name__ == "__main__":
    main()
