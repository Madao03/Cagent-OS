"""F4: Batch materialize all quarters for a ticker."""
import asyncio, sys, time, requests, json
sys.path.insert(0, "src")
from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor
from cagent_os.data_layer.lane2.materializer import EdgarReleaseStore

QUARTERS = []
for year in range(2020, 2026):
    for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
        if year == 2020 and month < 9:
            continue
        q_num = {3: 1, 6: 2, 9: 3, 12: 4}[month]
        QUARTERS.append((f"{year}-{month:02d}-{day:02d}", f"Q{q_num} {year}"))

async def _find_quarter(finder, cik, submissions, quarter_end, idx_cache):
    from datetime import datetime, timedelta
    q_end = datetime.strptime(quarter_end, "%Y-%m-%d")
    ws = q_end - timedelta(days=5)
    we = q_end + timedelta(days=90 if q_end.month == 12 else 60)
    recent = submissions.get("filings", {}).get("recent", {})
    candidates = []
    for i, form in enumerate(recent.get("form", [])):
        if str(form).strip().upper() not in ("6-K", "8-K"):
            continue
        try:
            fd = datetime.strptime(str(recent["filingDate"][i]), "%Y-%m-%d")
        except (ValueError, IndexError):
            continue
        if not (ws <= fd <= we) or fd <= q_end:
            continue
        acc = str(recent["accessionNumber"][i])
        if acc not in idx_cache:
            idx_cache[acc] = await finder._fetch_index_json(cik, acc)
        idx = idx_cache[acc]
        if not idx:
            continue
        en, es, ec = finder._parse_index(idx)
        if not en:
            continue
        score = finder._score_structural(es, ec, fd, q_end,
            str(recent["reportDate"][i]) if i < len(recent.get("reportDate", [])) else "")
        if score > 0:
            candidates.append({"accession": acc, "form": str(form), "document": en,
                "filing_date": str(recent["filingDate"][i]), "score": score})
    if not candidates:
        return {"entity_type": finder._detect_entity(submissions), "found": False}
    candidates.sort(key=lambda c: (-c["score"], c["filing_date"]))
    best = candidates[0]
    if best["score"] < 0.35:
        return {"entity_type": finder._detect_entity(submissions), "found": False}
    acc_no_dash = best["accession"].replace("-", "")
    return {"accession": best["accession"], "form": best["form"],
        "document": best["document"], "url": f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_dash}/{best['document']}",
        "filing_date": best["filing_date"], "conf": best["score"], "entity_type": finder._detect_entity(submissions), "found": True}

async def main():
    finder = EarningsReleaseFinder()
    extractor = EarningsReleaseExtractor()
    store = EdgarReleaseStore()
    ticker = "XPEV"
    cik = await finder._resolve_cik(ticker, None)
    submissions = await finder._fetch_submissions(cik)
    idx_cache = {}
    new_c, skip_c, fail_c = 0, 0, 0
    t0 = time.perf_counter()
    for qe, label in QUARTERS:
        if store.has(ticker, qe):
            skip_c += 1
            continue
        release = None
        for att in range(3):
            try:
                release = await _find_quarter(finder, cik, submissions, qe, idx_cache)
                break
            except Exception:
                if att < 2:
                    await asyncio.sleep((att + 1) * 2)
        if not release or not release.get("found"):
            print(f"  {label}: NOT FOUND")
            fail_c += 1
            continue
        resp = requests.get(release["url"], headers={"User-Agent": "CagentOS madaocage@gmail.com"}, timeout=30)
        if resp.status_code != 200:
            print(f"  {label}: DOWNLOAD FAIL")
            fail_c += 1
            continue
        meta = {"accession": release["accession"], "document": release["document"],
                "form": release["form"], "filing_date": release["filing_date"], "ticker": ticker}
        extracted = extractor.extract(resp.content, meta=meta)
        records_out = [{"period_start": r.period_start, "period_end": r.period_end,
            "period_type": r.period_type, "currency": r.currency, "fx_rate": r.fx_rate,
            "revenue": r.metrics.get("revenue"), "net_income": r.metrics.get("net_income"),
            "gross_profit": r.metrics.get("gross_profit"), "extraction_method": r.extraction_method}
            for r in extracted.records]
        guidance_out = [{"period_label": g.period_label, "metric_name": g.metric_name,
            "low": g.low, "high": g.high, "currency": g.currency,
            "yoy_change_low": g.yoy_change_low, "yoy_change_high": g.yoy_change_high}
            for g in extracted.guidance]
        result = {"accession": release["accession"], "document": release["document"],
            "filing_date": release["filing_date"], "form": release["form"], "conf": release["conf"],
            "records": records_out, "guidance": guidance_out}
        store.put(ticker, qe, result)
        new_c += 1
        print(f"  {label}: OK ({release['filing_date']}, {len(records_out)} records, {len(guidance_out)} guidance)")
    elapsed = time.perf_counter() - t0
    print(f"\nNew: {new_c} | Skipped: {skip_c} | Failed: {fail_c} | {elapsed:.0f}s")

asyncio.run(main())
