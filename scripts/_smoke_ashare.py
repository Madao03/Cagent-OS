"""Quick smoke test: fetch 贵州茅台 (600519) financials, verify pipeline.
Post-fix: source-table-driven differential (fail-closed), reconciliation, caliber check.
"""
import sys, asyncio, json
sys.stdout.reconfigure(encoding='utf-8')

from cagent_os.data_layer.adapters.akshare_financials_adapter import (
    AkshareFinancialsAdapter, _fetch_statement, normalize_unit,
    _detect_unit_from_values, validate_unit_detection,
    detect_period_type, detect_period_range,
    difference_cumulative_periods, _flow_items,
    reconcile_triple_statements,
)

TICKER = "600519"

print(f"=== Fetching {TICKER} financials ===")

# Step 1: Fetch individual statements
bs = _fetch_statement(TICKER, "balance_sheet")
income = _fetch_statement(TICKER, "income")
cf = _fetch_statement(TICKER, "cash_flow")

dates = sorted(bs.keys()) if bs else []
print(f"  BS dates: {dates[-5:]}")
print(f"  IS dates: {sorted(income.keys())[-5:] if income else 'N/A'}")
print(f"  CF dates: {sorted(cf.keys())[-5:] if cf else 'N/A'}")

# Step 2: period_type detection
print("\n=== Period type detection ===")
for d in dates[-4:]:
    pt = detect_period_type(d)
    ps, pe = detect_period_range(d, pt)
    print(f"  {d} → {pt} ({ps} ~ {pe})")

# Step 3: Reconciliation
print("\n=== Reconciliation (latest period) ===")
sorted_dates = sorted(bs.keys()) if bs else []
bs_latest = bs[sorted_dates[-1]] if len(sorted_dates) >= 1 else {}
income_latest = income[sorted_dates[-1]] if len(sorted_dates) >= 1 else {}
cf_latest = cf[sorted_dates[-1]] if len(sorted_dates) >= 1 else {}
# Prior period BS for ⑤ ΔRE check
bs_prior = bs[sorted_dates[-2]] if len(sorted_dates) >= 2 else None

recon = reconcile_triple_statements(bs_latest, income_latest, cf_latest, prior_bs=bs_prior)
print(f"  Period: {sorted_dates[-1] if sorted_dates else 'N/A'} (prior: {sorted_dates[-2] if len(sorted_dates) >= 2 else 'N/A'})")
print(f"  Overall: {'✓ PASSED' if recon.passed else '✗ FAILED'}")
for c in recon.checks:
    status = "✓" if c["passed"] else "✗"
    gap_info = f" gap={c.get('actual','') - c.get('expected','') if isinstance(c.get('actual'), (int,float)) and isinstance(c.get('expected'), (int,float)) else ''}" if not c["passed"] else ""
    print(f"  {status} {c['name']}: expected={c.get('expected')}, actual={c.get('actual')} {c.get('detail','')}{gap_info}")

# Step 4: Caliber check
print("\n=== Caliber check (latest income) ===")
for key in ("营业总收入", "营业收入", "净利润", "归属于母公司所有者的净利润"):
    v = income_latest.get(key)
    if v is not None:
        print(f"  {key}: {v:,.0f}")

# Verify difference between 营业总收入 and 营业收入
tr = income_latest.get("营业总收入")
or_ = income_latest.get("营业收入")
if tr and or_:
    diff = tr - or_
    print(f"  Δ(营业总收入 − 营业收入) = {diff:,.0f} ({diff/tr*100:.1f}%)")

np_total = income_latest.get("净利润")
np_parent = income_latest.get("归属于母公司所有者的净利润")
if np_total and np_parent:
    diff_np = np_total - np_parent
    print(f"  Δ(净利润 − 归母净利润) = {diff_np:,.0f} ({diff_np/np_total*100:.1f}%)")

# Step 5: Cumulative differencing (source-table-driven)
print("\n=== Cumulative differencing (source-table-driven) ===")
all_dates = set()
for d in [bs, income, cf]:
    if d:
        all_dates.update(d.keys())

periods = []
for d in sorted(all_dates):
    pt = detect_period_type(d)
    ps, pe = detect_period_range(d, pt)
    periods.append({
        "report_date": d,
        "period_type": pt,
        "period_start": ps,
        "period_end": pe,
        "bs_items": bs.get(d, {}),
        "is_items": income.get(d, {}),
        "cf_items": cf.get(d, {}),
        "audited": (pt == "fiscal_year"),
    })

latest_year = int(sorted(all_dates)[-1][:4])
diff_results = difference_cumulative_periods(periods, latest_year)

# ★ Verify: NO BS-only items should appear in differenced results.
# "其他综合收益" appears in BOTH BS (equity section) and IS (comprehensive income)
# — it's a legitimate IS flow item. We check for items that are in BS
# but NOT in any flow statement (IS or CF).
_bs_only_keys = set(bs_latest.keys()) - set(income_latest.keys()) - set(cf_latest.keys())
for dr in diff_results:
    leaked = [k for k in dr.items if k in _bs_only_keys]
    assert not leaked, f"BS-only items leaked into {dr.quarter_label} diff: {leaked[:10]}"

print(f"  Q1-Q4 computed ({len(diff_results)} quarters)")
for dr in diff_results:
    neg_flag = f" ⚠ {len(dr.negative_items)} neg items" if dr.negative_items else ""
    audited_str = " (audited)" if dr.audited else ""
    print(f"  {dr.quarter_label} {dr.period_start}~{dr.period_end}{audited_str}{neg_flag}")
    for key in ("营业总收入", "营业收入", "净利润", "归属于母公司所有者的净利润"):
        v = dr.items.get(key)
        if v is not None:
            print(f"    {key}: {v:,.0f}")
    # Verify no BS-only items in diff
    bs_in_diff = [k for k in dr.items if k in _bs_only_keys]
    if bs_in_diff:
        print(f"    ✗ LEAKED BS ITEMS: {bs_in_diff}")

print("\n✓ Source-table-driven differential: BS items excluded (fail-closed)")

# Step 6: period label check
print("\n=== Period labels ===")
for d in sorted(all_dates)[-2:]:
    pt = detect_period_type(d)
    ps, pe = detect_period_range(d, pt)
    year = ps[:4] if ps else "?"
    label = f"FY{year}" if pt == "fiscal_year" else f"{year}Q{int(pe[5:7])//3}" if pt == "quarter" else f"{year} {'H1' if '06' in pe else '9M'}"
    print(f"  {d} → period_type={pt}, label={label}")

print("\n✓ Smoke test complete.")
