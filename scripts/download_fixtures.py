"""Download selected SEC filing fixtures with EX-99.1 auto-discovery.

Each target is specified as: ticker accession ex99_filename fixture_slug [label]

Usage:
  python scripts/download_fixtures.py
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

HEADERS = {"User-Agent": "CagentOS madaocage@gmail.com", "Accept-Encoding": "gzip, deflate"}
BASE_SEC = "https://www.sec.gov"
FIXTURE_DIR = Path("tests/fixtures/edgar")

MIN_INTERVAL = 0.15
_last = 0.0


def throttle() -> None:
    global _last
    elapsed = time.perf_counter() - _last
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last = time.perf_counter()


def list_documents(cik_int: int, accession: str) -> list[dict]:
    """List all documents in a filing via index.json."""
    throttle()
    accn_no_dash = accession.replace("-", "")
    url = f"{BASE_SEC}/Archives/edgar/data/{cik_int}/{accn_no_dash}/index.json"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return []
    items = resp.json().get("directory", {}).get("item", [])
    return [
        {"name": i.get("name", ""), "size": i.get("size", "")}
        for i in items
    ]


def find_ex99(docs: list[dict]) -> str | None:
    """Find the EX-99.1 document (performance press release)."""
    for d in docs:
        name = d["name"].lower()
        if "ex99" in name and name.endswith((".htm", ".html")):
            return d["name"]
    return None


def download(
    ticker: str,
    cik_int: int,
    accession: str,
    filename: str,
    slug: str,
    label: str,
    filing_date: str = "",
) -> bool:
    """Download a document and save as fixture with .meta.json sidecar."""
    throttle()
    accn_no_dash = accession.replace("-", "")
    url = f"{BASE_SEC}/Archives/edgar/data/{cik_int}/{accn_no_dash}/{filename}"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code != 200:
        print(f"  FAIL [{slug}]: HTTP {resp.status_code} — {url}")
        return False

    # Determine extension
    ext = ".html"
    if filename.endswith(".pdf"):
        ext = ".pdf"
    elif filename.endswith(".txt"):
        ext = ".txt"

    fixture_path = FIXTURE_DIR / f"{slug}{ext}"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_bytes(resp.content)

    # SHA-256 checksum (SEC docs are immutable by accession — proves determinism)
    sha256 = hashlib.sha256(resp.content).hexdigest()

    # .meta.json sidecar
    meta = {
        "ticker": ticker.upper(),
        "accession": accession,
        "form": "6-K",
        "filing_date": filing_date,
        "document": filename,
        "url": url,
        "content_type": resp.headers.get("content-type", ""),
        "size_bytes": len(resp.content),
        "sha256": sha256,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
    }
    meta_path = FIXTURE_DIR / f"{slug}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  OK  [{slug}]: {len(resp.content)} bytes, sha256={sha256[:12]}...")
    return True


def main():
    # ── XPEV fixtures ──
    xpev_cik = 1810997

    # Target filings (accession, ex99_filename, slug, label, filing_date)
    targets = [
        # Q1 2025 earnings (May 2025)
        ("0001193125-25-123650", None, "xpev_6k_2025q1_earnings", "earnings_q1_2025", "2025-05-21"),
        # Q2 2025 earnings (Aug 2025)
        ("0001193125-25-181261", None, "xpev_6k_2025q2_earnings", "earnings_q2_2025", "2025-08-15"),
        # Q3 2025 earnings (Nov 2025)
        ("0001193125-25-267074", None, "xpev_6k_2025q3_earnings", "earnings_q3_2025", "2025-11-05"),
        # FY2024 earnings (Mar 2025) — for restatement detection
        ("0001193125-25-057682", None, "xpev_6k_fy2024_earnings", "earnings_fy2024", "2025-03-19"),
        # Monthly delivery (pick a recent one)
        ("0001193125-26-293394", None, "xpev_6k_monthly_delivery", "negative_monthly_delivery", "2026-07-02"),
    ]

    print("=== XPEV fixtures ===")
    for accession, ex99_name, slug, label, fdate in targets:
        print(f"\n  {slug} ({label})")
        print(f"  accession: {accession}")

        # Auto-discover EX-99.1 if not specified
        if ex99_name is None:
            docs = list_documents(xpev_cik, accession)
            ex99_name = find_ex99(docs)
            if not ex99_name:
                # Use primary document
                print(f"  No EX-99 found, docs: {[d['name'] for d in docs[:5]]}")
                # For monthly delivery, primary doc IS the content
                ex99_name = docs[0]["name"] if docs else ""
                label = label  # Keep as negative sample

        if ex99_name:
            download("XPEV", xpev_cik, accession, ex99_name, slug, label, fdate)
        else:
            print(f"  SKIP: no document found")

    # ── AAPL 8-K fixture ──
    print("\n\n=== AAPL 8-K fixture ===")
    aapl_cik = 320193

    # Find latest 8-K with Item 2.02 (earnings)
    throttle()
    resp = requests.get(
        f"https://data.sec.gov/submissions/CIK{aapl_cik:010d}.json",
        headers=HEADERS, timeout=15,
    )
    submissions = resp.json()
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    docs_list = recent.get("primaryDocument", [])

    # Find 8-K with earnings
    for i, f in enumerate(forms[:30]):
        if f == "8-K":
            accession = accessions[i]
            # Check if it has EX-99.1
            docs = list_documents(aapl_cik, accession)
            ex99 = find_ex99(docs)
            if ex99:
                print(f"\n  AAPL 8-K {dates[i]} — EX-99.1: {ex99}")
                download("AAPL", aapl_cik, accession, ex99,
                         "aapl_8k_earnings", "earnings_8k_us_domestic", dates[i])
                break

    print("\n=== Done ===")
    print(f"Fixtures in {FIXTURE_DIR}:")
    for f in sorted(FIXTURE_DIR.glob("*")):
        if f.is_file():
            print(f"  {f.name} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
