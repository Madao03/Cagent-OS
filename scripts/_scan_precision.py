"""F3: Scan ALL historical 6-Ks — precision estimate."""
import asyncio, sys, time
sys.path.insert(0, "src")
from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder

async def scan_ticker(finder, ticker):
    cik = await finder._resolve_cik(ticker, None)
    if not cik:
        print(f"  {ticker}: CIK not found")
        return [], 0, 0, 0
    
    submissions = await finder._fetch_submissions(cik)
    if not submissions:
        print(f"  {ticker}: submissions fetch failed")
        return [], 0, 0, 0
    
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    
    positives, neg_hard, no_ex99, errors, skipped = [], 0, 0, 0, 0
    
    for i, form in enumerate(forms):
        if str(form).strip().upper() != "6-K":
            continue
        
        acc = str(accessions[i])
        fd = str(dates[i])
        
        try:
            idx = await finder._fetch_index_json(cik, acc)
        except Exception:
            errors += 1
            continue
        
        if not idx:
            skipped += 1
            continue
        
        ex99_name, ex99_size, total_ex99 = finder._parse_index(idx)
        if not ex99_name:
            no_ex99 += 1
            continue
        
        if ex99_size < 8000:
            neg_hard += 1
            continue
        
        from datetime import datetime
        score = finder._score_structural(
            ex99_size=ex99_size, total_ex99=total_ex99,
            filing_date=datetime.strptime(fd, "%Y-%m-%d"),
            quarter_end=datetime.strptime("2025-12-31", "%Y-%m-%d"),
            report_date=str(report_dates[i]) if i < len(report_dates) else "",
        )
        
        if score > 0:
            positives.append({
                "ticker": ticker, "accession": acc, "filing_date": fd,
                "ex99_name": ex99_name, "ex99_size": ex99_size,
                "total_ex99": total_ex99, "score": score,
            })
    
    return positives, neg_hard, no_ex99, errors, skipped


async def main():
    finder = EarningsReleaseFinder()
    
    for ticker in ["XPEV", "AAPL", "BABA"]:
        print(f"\n=== {ticker} ===")
        t0 = time.perf_counter()
        result = await scan_ticker(finder, ticker)
        if len(result) != 5:
            continue
        positives, neg_hard, no_ex99, errors, skipped = result
        elapsed = time.perf_counter() - t0
        
        positives.sort(key=lambda p: -p["score"])
        
        print(f"  Scan time: {elapsed:.1f}s")
        print(f"  No EX-99.1: {no_ex99} | <8KB (hard neg): {neg_hard} | Errors: {errors} | No index: {skipped}")
        print(f"  Scored > 0: {len(positives)}")
        print()
        
        for p in positives:
            kb = p["ex99_size"] / 1024
            print(f"  {p['filing_date']} | score={p['score']:.2f} | {p['ex99_name'][:30]} | {kb:.0f}KB | ×{p['total_ex99']} | {p['accession']}")

asyncio.run(main())
