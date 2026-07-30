"""Build candidate index from SEC submissions.

Exports 6-K/8-K filings as a table for manual selection.
This table is also the first batch of labeled data for S3 classifier.

Usage:
  python scripts/build_filing_index.py XPEV --form 6-K --limit 80
  python scripts/build_filing_index.py AAPL --form 8-K --limit 30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "CagentOS madaocage@gmail.com", "Accept-Encoding": "gzip, deflate"}
BASE_DATA = "https://data.sec.gov"
BASE_SEC = "https://www.sec.gov"
FIXTURE_DIR = Path("tests/fixtures/edgar")
INDEX_DIR = Path("tests/fixtures/edgar/_index")

MIN_INTERVAL = 0.15  # 6.7 req/s, safe margin
_last = 0.0


def throttle() -> None:
    global _last
    elapsed = time.perf_counter() - _last
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last = time.perf_counter()


def get_cik(ticker: str) -> str:
    throttle()
    resp = requests.get(f"{BASE_SEC}/files/company_tickers.json", headers=HEADERS, timeout=10)
    for entry in resp.json().values():
        if entry["ticker"].upper() == ticker.upper():
            return f"{entry['cik_str']:010d}"
    raise ValueError(f"Ticker not found: {ticker}")


def get_submissions(cik: str) -> dict:
    throttle()
    resp = requests.get(f"{BASE_DATA}/submissions/CIK{cik}.json", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_doc_preview(cik_int: int, accession: str, doc: str) -> str:
    """Fetch first 200 chars of a document for classification."""
    throttle()
    accn_no_dash = accession.replace("-", "")
    url = f"{BASE_SEC}/Archives/edgar/data/{cik_int}/{accn_no_dash}/{doc}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return f"[HTTP {resp.status_code}]"
        # Parse as HTML and get text
        soup = BeautifulSoup(resp.content[:4096], "lxml")  # Only first 4KB
        text = soup.get_text(" ", strip=True)
        return text[:200].replace("\n", " ").replace("\r", "")
    except Exception as e:
        return f"[ERROR: {e}]"


def main():
    parser = argparse.ArgumentParser(description="Build SEC filing candidate index")
    parser.add_argument("ticker", help="Stock ticker")
    parser.add_argument("--form", default="6-K", help="Form type")
    parser.add_argument("--limit", type=int, default=50, help="Max filings")
    parser.add_argument("--preview", action="store_true", help="Fetch 200-char preview (slower)")
    args = parser.parse_args()

    cik = get_cik(args.ticker)
    cik_int = int(cik)
    print(f"{args.ticker} CIK: {cik}")

    submissions = get_submissions(cik)
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])

    # Filter by form type
    matching = []
    for i, f in enumerate(forms):
        if f == args.form:
            matching.append({
                "date": dates[i] if i < len(dates) else "",
                "accession": accessions[i] if i < len(accessions) else "",
                "doc": docs[i] if i < len(docs) else "",
                "form": f,
            })

    print(f"\nFound {len(matching)} {args.form} filings (showing last {min(args.limit, len(matching))}):")
    print(f"{'#':>3s}  {'Date':12s}  {'Accession':22s}  {'Doc':30s}  Preview")
    print("-" * 120)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    output_rows = []

    for idx, m in enumerate(matching[:args.limit]):
        preview = ""
        if args.preview:
            preview = get_doc_preview(cik_int, m["accession"], m["doc"])

        print(f"{idx:3d}  {m['date']:12s}  {m['accession']:22s}  {m['doc']:30s}  {preview[:60]}")
        output_rows.append({
            "idx": idx,
            "date": m["date"],
            "accession": m["accession"],
            "doc": m["doc"],
            "preview": preview,
        })

    # Save index
    index_path = INDEX_DIR / f"{args.ticker.lower()}_{args.form.lower()}_index.json"
    index_path.write_text(json.dumps(output_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nIndex saved: {index_path}")


if __name__ == "__main__":
    main()
