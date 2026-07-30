"""M3: Coverage stats — extract records for 3 tickers × recent 8 quarters.

Uses the cached materializer (F4) — first run populates cache, subsequent runs instant.
Reports: how many quarters produce records (the MVP acceptance metric).
"""
import asyncio, sys, time, requests
sys.path.insert(0, "src")
from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor
from cagent_os.data_layer.lane2.materializer import EdgarReleaseStore

# 8 most recent completed quarters (Q2 2024 – Q1 2026)
QUARTERS = []
for year in [2024, 2025, 2026]:
    for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
        q_num = {3: 1, 6: 2, 9: 3, 12: 4}[month]
        label = f"Q{q_num} {year}"
        qe = f"{year}-{month:02d}-{day:02d}"
        if qe < "2024-06-30":
            continue
        if qe > "2026-03-31":
            continue
        QUARTERS.append((qe, label))

TICKERS = ["XPEV", "AAPL", "BABA"]

async def main():
    finder = EarningsReleaseFinder()
    extractor = EarningsReleaseExtractor()
    store = EdgarReleaseStore()

    for ticker in TICKERS:
        print(f"\n{'='*60}")
        print(f"  {ticker}")
        print(f"{'='*60}")

        hits, records_total = 0, 0

        for qe, label in QUARTERS:
            # Check cache first
            cached = store.get(ticker, qe)
            if cached:
                n = cached["record_count"]
                if n > 0:
                    hits += 1
                    records_total += n
                print(f"  {label} ({qe}): cached, {n} records | {cached.get('accession', '?')}")
                continue

            # Real-time extraction
            # Use production find() directly (no local copy that can drift)
            release = None
            for att in range(3):
                try:
                    release = await finder.find(ticker, qe)
                    break
                except Exception:
                    if att < 2:
                        await asyncio.sleep((att + 1) * 2)

            if not release or not release.get("found"):
                print(f"  {label} ({qe}): NOT FOUND")
                continue

            resp = requests.get(release["url"],
                headers={"User-Agent": "CagentOS madaocage@gmail.com"}, timeout=30)
            if resp.status_code != 200:
                print(f"  {label} ({qe}): DOWNLOAD FAILED")
                continue

            meta = {"accession": release["accession"], "document": release["document"],
                    "form": release["form"], "filing_date": release["filing_date"], "ticker": ticker}
            extracted = extractor.extract(resp.content, meta=meta)
            n = len(extracted.records)
            if n > 0:
                hits += 1
                records_total += n

            # Cache result
            record_dicts = [{"period_start": r.period_start, "period_end": r.period_end,
                "period_type": r.period_type, "currency": r.currency,
                "revenue": r.metrics.get("revenue"), "net_income": r.metrics.get("net_income"),
                "extraction_method": r.extraction_method} for r in extracted.records]
            guidance_dicts = [{"period_label": g.period_label, "metric_name": g.metric_name,
                "low": g.low, "high": g.high} for g in extracted.guidance]
            store.put(ticker, qe, {"accession": release["accession"],
                "document": release["document"], "filing_date": release["filing_date"],
                "form": release["form"], "conf": release["conf"],
                "records": record_dicts, "guidance": guidance_dicts})

            print(f"  {label} ({qe}): {n} records | {release['accession']} | {release['filing_date']}")

        pct = hits / len(QUARTERS) * 100
        print(f"  → {hits}/{len(QUARTERS)} = {pct:.0f}% quarters with records, {records_total} total records")


asyncio.run(main())
