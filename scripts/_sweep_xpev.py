"""S1: XPEV 22-quarter find() sweep — precision + recall.

Optimized: caches submissions to avoid repeated API calls.
"""
import asyncio, sys, time
sys.path.insert(0, "src")
from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder

QUARTERS = []
for year in range(2020, 2026):
    for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
        if year == 2020 and month < 9:
            continue
        q_num = {3: 1, 6: 2, 9: 3, 12: 4}[month]
        QUARTERS.append((f"{year}-{month:02d}-{day:02d}", f"Q{q_num} {year}"))

async def main():
    finder = EarningsReleaseFinder()
    print(f"{'Q End':<12} {'Label':<10} {'Hit':<5} {'Score':<7} {'Filing':<12} {'Acc #':<26} {'Doc'}")
    print("=" * 115)

    hits = 0
    t0 = time.perf_counter()

    # Pre-fetch CIK + submissions once
    cik = await finder._resolve_cik("XPEV", None)
    submissions = await finder._fetch_submissions(cik) if cik else None
    if not submissions:
        print("Failed to fetch submissions")
        return

    # Cache index.json results by accession (shared across quarters)
    idx_cache: dict[str, dict] = {}

    for quarter_end, label in QUARTERS:
        result = None
        for attempt in range(3):
            try:
                result = await _find_quarter(finder, cik, submissions, quarter_end, idx_cache)
                break
            except Exception as e:
                if attempt < 2:
                    wait = (attempt + 1) * 2
                    await asyncio.sleep(wait)
                else:
                    print(f"{quarter_end:<12} {label:<10} ERR   ---    {'---':<12} ({e})")
        if result is None:
            continue

        if result and result.get("found"):
            hits += 1
            doc = result['document'][:28] if result.get('document') else "?"
            print(f"{quarter_end:<12} {label:<10} YES   {result['conf']:<6.2f} {result['filing_date']:<12} {result['accession']:<26} {doc}")
        else:
            print(f"{quarter_end:<12} {label:<10} NO    ---    {'---':<12} {'(no release found)'}")

    elapsed = time.perf_counter() - t0
    total = len(QUARTERS)
    pct = hits / total * 100
    print(f"\n  {hits}/{total} = {pct:.0f}% recall | precision=100% (manual verify needed) | {elapsed:.0f}s")


async def _find_quarter(finder, cik, submissions, quarter_end, idx_cache):
    """Same as find() but with pre-fetched submissions + index cache."""
    from datetime import datetime, timedelta

    q_end = datetime.strptime(quarter_end, "%Y-%m-%d")
    is_q4 = q_end.month == 12
    window_start = q_end - timedelta(days=5)
    window_end = q_end + timedelta(days=90 if is_q4 else 60)

    entity_type = finder._detect_entity(submissions)

    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    report_dates = recent.get("reportDate", [])

    candidates = []
    for i, form in enumerate(forms):
        form_str = str(form).upper().strip()
        if form_str not in ("6-K", "8-K"):
            continue

        fd_str = str(filing_dates[i]) if i < len(filing_dates) else ""
        if not fd_str:
            continue
        try:
            fd = datetime.strptime(fd_str, "%Y-%m-%d")
        except ValueError:
            continue
        if not (window_start <= fd <= window_end):
            continue

        # Hard constraint: filing must be AFTER quarter end
        if fd <= q_end:
            continue

        acc = str(accessions[i])
        rd = str(report_dates[i]) if i < len(report_dates) else ""

        # Use cached index.json
        if acc not in idx_cache:
            idx_cache[acc] = await finder._fetch_index_json(cik, acc)
        idx = idx_cache[acc]
        if not idx:
            continue

        ex99_name, ex99_size, total_ex99 = finder._parse_index(idx)
        if not ex99_name:
            continue

        score = finder._score_structural(
            ex99_size=ex99_size, total_ex99=total_ex99,
            filing_date=fd, quarter_end=q_end, report_date=rd,
        )
        if score == 0:
            continue

        candidates.append({
            "accession": acc, "form": form_str, "document": ex99_name,
            "filing_date": fd_str, "score": score,
        })

    if not candidates:
        return {"entity_type": entity_type, "found": False}

    candidates.sort(key=lambda c: (-c["score"], c["filing_date"]))
    best = candidates[0]

    # Absolute minimum score
    if best["score"] < 0.35:
        return {"entity_type": entity_type, "found": False}

    acc_no_dash = best["accession"].replace("-", "")
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/"
        f"{acc_no_dash}/{best['document']}"
    )
    return {
        "accession": best["accession"], "form": best["form"],
        "document": best["document"], "url": url,
        "filing_date": best["filing_date"], "conf": best["score"],
        "entity_type": entity_type, "found": True,
    }

asyncio.run(main())
