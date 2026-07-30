"""Fetch SEC filing documents as test fixtures.

Stores raw bytes (no prettify) + .meta.json sidecar for provenance.
SEC filings are public records — storing as fixtures is standard practice.

Usage:
  python scripts/fetch_fixture.py XPEV           # auto-find latest earnings 6-K
  python scripts/fetch_fixture.py XPEV --form 6-K --keyword "Fourth Quarter"
  python scripts/fetch_fixture.py AAPL --form 8-K --keyword "Item 2.02"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# SEC requires descriptive User-Agent
HEADERS = {
    "User-Agent": "CagentOS madaocage@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}
BASE_DATA = "https://data.sec.gov"
BASE_SEC = "https://www.sec.gov"
FIXTURE_DIR = Path("tests/fixtures/edgar")

# Rate limit: 10 req/s
MIN_INTERVAL = 0.12
_last = 0.0


def throttle() -> None:
    global _last
    elapsed = time.perf_counter() - _last
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last = time.perf_counter()


def get_cik(ticker: str) -> str:
    """Get zero-padded CIK for ticker."""
    throttle()
    resp = requests.get(f"{BASE_SEC}/files/company_tickers.json", headers=HEADERS, timeout=10)
    data = resp.json()
    for entry in data.values():
        if entry["ticker"].upper() == ticker.upper():
            return f"{entry['cik_str']:010d}"
    raise ValueError(f"Ticker not found: {ticker}")


def get_submissions(cik: str) -> dict:
    """Get submissions index."""
    throttle()
    resp = requests.get(f"{BASE_DATA}/submissions/CIK{cik}.json", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def find_filing(
    submissions: dict,
    form: str,
    keyword: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Find filings matching form type and optional keyword in description."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    descs = recent.get("primaryDocDescription", [])

    results = []
    for i, f in enumerate(forms):
        if f == form or f == f + "/A":
            desc = descs[i] if i < len(descs) else ""
            if keyword is None or keyword.lower() in desc.lower():
                results.append({
                    "form": f,
                    "date": dates[i] if i < len(dates) else "",
                    "accession": accessions[i] if i < len(accessions) else "",
                    "primary_document": docs[i] if i < len(docs) else "",
                    "description": desc,
                })
                if len(results) >= limit:
                    break
    return results


def get_filing_documents(cik: str, accession: str) -> list[dict]:
    """Get list of all documents in a filing (including EX-99.x attachments)."""
    accn_no_dashes = accession.replace("-", "")
    throttle()
    # The filing index page lists all documents
    url = f"{BASE_SEC}/Archives/edgar/data/{int(cik)}/{accn_no_dashes}/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return []

    # Parse the directory listing (it's an HTML page from SEC)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "lxml")
    docs = []
    for link in soup.find_all("a"):
        href = link.get("href", "")
        if href and not href.startswith("?") and not href.startswith("/"):
            name = link.text.strip()
            if name and "." in name:
                docs.append({"name": name, "url": url + href})
    return docs


def save_fixture(
    ticker: str,
    filing: dict,
    doc_url: str,
    doc_name: str,
    subdir: str = "",
) -> Path:
    """Download a document and save as fixture with .meta.json sidecar."""
    throttle()
    resp = requests.get(doc_url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        print(f"  FAIL: HTTP {resp.status_code}")
        return None

    # Determine extension from content-type or filename
    content_type = resp.headers.get("content-type", "")
    ext = ".html"
    if "pdf" in content_type or doc_name.endswith(".pdf"):
        ext = ".pdf"
    elif doc_name.endswith(".txt"):
        ext = ".txt"

    # Save raw bytes (no prettify, no re-encoding)
    tag = filing["form"].lower().replace("/", "_")
    date = filing["date"]
    slug = f"{ticker.lower()}_{tag}_{date}"
    if subdir:
        slug = f"{subdir}/{slug}"

    fixture_path = FIXTURE_DIR / f"{slug}{ext}"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_bytes(resp.content)

    # Save .meta.json sidecar
    meta = {
        "ticker": ticker.upper(),
        "accession": filing["accession"],
        "form": filing["form"],
        "filing_date": filing["date"],
        "description": filing.get("description", ""),
        "document": doc_name,
        "url": doc_url,
        "content_type": content_type,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = FIXTURE_DIR / f"{slug}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"  Saved: {fixture_path} ({len(resp.content)} bytes)")
    print(f"  Meta:  {meta_path}")
    return fixture_path


def main():
    parser = argparse.ArgumentParser(description="Fetch SEC filing fixtures")
    parser.add_argument("ticker", help="Stock ticker (e.g. XPEV, AAPL)")
    parser.add_argument("--form", default="6-K", help="Form type (default: 6-K)")
    parser.add_argument("--keyword", default=None, help="Filter by keyword in description")
    parser.add_argument("--limit", type=int, default=5, help="Max filings to list")
    parser.add_argument("--download", type=int, default=None, help="Download N-th filing (0-indexed)")
    parser.add_argument("--doc", default=None, help="Specific document name to download (e.g. EX-99.1)")
    args = parser.parse_args()

    cik = get_cik(args.ticker)
    print(f"{args.ticker} CIK: {cik}")

    submissions = get_submissions(cik)
    filings = find_filing(submissions, args.form, args.keyword, args.limit)

    if not filings:
        print(f"No {args.form} filings found matching '{args.keyword or ''}'")
        return

    print(f"\nFound {len(filings)} {args.form} filings:")
    for i, f in enumerate(filings):
        print(f"  [{i}] {f['date']} | {f['form']} | {f['description'][:60]} | {f['accession']}")

    if args.download is None and args.doc is None:
        print("\nUse --download N to download a filing, or --doc EX-99.1 for specific document")
        return

    target = filings[args.download or 0]
    print(f"\nTarget: {target['date']} {target['form']} {target['accession']}")

    # List all documents in the filing
    docs = get_filing_documents(cik, target["accession"])
    print(f"Documents in filing ({len(docs)}):")
    for d in docs:
        print(f"  {d['name']}")

    # Download target document
    doc_name = args.doc or target.get("primary_document", "")
    doc_url = None
    for d in docs:
        if doc_name.lower() in d["name"].lower():
            doc_url = d["url"]
            doc_name = d["name"]
            break

    if not doc_url:
        # Try primary document directly
        accn_no_dashes = target["accession"].replace("-", "")
        doc_url = f"{BASE_SEC}/Archives/edgar/data/{int(cik)}/{accn_no_dashes}/{doc_name}"

    save_fixture(args.ticker, target, doc_url, doc_name)


if __name__ == "__main__":
    main()
