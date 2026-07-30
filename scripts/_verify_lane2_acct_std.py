"""Verify LANE 2 cache: clear XPEV Q4 2025, re-extract with
get_issuer_accounting_standard() injection, check FactRegistry.

Acceptance criteria:
  - quarter records have accounting_standard == "US_GAAP"
  - NOT "" (null/not-applicable)
  - NOT "UNKNOWN" (data gap)
"""
import sys, sqlite3, asyncio, json
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = "data/edgar_release.db"

# ── Step 1: Clear cache ─────────────────────────────────────────
db = sqlite3.connect(DB_PATH)
rows = db.execute(
    "SELECT ticker, quarter_end, schema_version FROM edgar_release_cache "
    "WHERE ticker='XPEV' AND quarter_end='2025-12-31'"
).fetchall()
if rows:
    db.execute("DELETE FROM edgar_release_cache WHERE ticker='XPEV' AND quarter_end='2025-12-31'")
    db.commit()
    print(f"Deleted {len(rows)} cached XPEV Q4 2025 entries (schema_v={rows[0][2]})")
else:
    print("No cache to delete")
db.close()

# ── Step 2: Look up issuer accounting_standard ─────────────────
print("\n=== Issuer accounting_standard ===")
from cagent_os.data_layer.adapters.edgar_adapter import get_issuer_accounting_standard
issuer_std = asyncio.run(get_issuer_accounting_standard("XPEV"))
print(f"  XPEV accounting_standard = {issuer_std!r}")
assert issuer_std == "US_GAAP", f"Expected US_GAAP, got {issuer_std!r}"

# ── Step 3: Extract ─────────────────────────────────────────────
print("\n=== Extracting XPEV Q4 2025 ===")
from cagent_os.data_layer.lane2.materializer import EdgarReleaseStore
from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor
import requests

store = EdgarReleaseStore()
finder = EarningsReleaseFinder()

release = asyncio.run(finder.find("XPEV", "2025-12-31"))
assert release and release.get("found"), f"No release: {release}"
print(f"  Found: {release['accession']} ({release['form']}) — {release['filing_date']}")

resp = requests.get(
    release["url"],
    headers={"User-Agent": "CagentOS madaocage@gmail.com"},
    timeout=30,
)
assert resp.status_code == 200, f"HTTP {resp.status_code}"

extractor = EarningsReleaseExtractor()
meta = {
    "accession": release["accession"],
    "document": release["document"],
    "form": release["form"],
    "filing_date": release["filing_date"],
    "ticker": "XPEV",
}
extracted = extractor.extract(resp.content, meta=meta)
print(f"  Extracted: {len(extracted.records)} records, {len(extracted.guidance)} guidance")

# ── Step 4: Build records with issuer_std injection (mirroring plugin) ──
_FINANCIAL_FIELDS = (
    "revenue", "cost_of_sales", "gross_profit",
    "operating_income", "net_income", "eps_diluted",
    "fx_rate",
)
from collections import defaultdict as _dd
period_groups: dict[tuple[str, str], list[dict]] = _dd(list)
for r in extracted.records:
    rec = {
        "period_start": r.period_start,
        "period_end": r.period_end,
        "period_type": r.period_type,
        "currency": r.currency,
        "fx_rate": r.fx_rate,
        "fx_rate_date": r.fx_rate_date,
        "revenue": r.metrics.get("revenue"),
        "cost_of_sales": r.metrics.get("cost_of_sales"),
        "gross_profit": r.metrics.get("gross_profit"),
        "operating_income": r.metrics.get("operating_income"),
        "net_income": r.metrics.get("net_income"),
        "eps_diluted": r.metrics.get("eps_diluted"),
        "extraction_method": r.extraction_method,
        # ★ Issuer-level injection (mirrors plugin._handle_edgar_release)
        "accounting_standard": issuer_std,
        "audited": False,
    }
    period_groups[(r.period_end or "", r.period_type or "")].append(rec)

records_out = []
for per_key, recs in period_groups.items():
    if len(recs) == 1:
        records_out.append(recs[0])
        continue
    primary = recs[0]
    merged = dict(primary)
    secondary = recs[1] if len(recs) > 1 else None
    if secondary:
        for field in _FINANCIAL_FIELDS:
            if merged.get(field) is None and secondary.get(field) is not None:
                merged[field] = secondary[field] * 1e9
    records_out.append(merged)

# ── Step 5: Materialize and run through FactRegistry ────────────
result = {
    "success": True,
    "ticker": "XPEV",
    "quarter_end": "2025-12-31",
    "accession": release["accession"],
    "document": release["document"],
    "form": release["form"],
    "filing_date": release["filing_date"],
    "audited": False,
    "accounting_standard": issuer_std,  # ★ top-level injection
    "currency": "CNY",
    "records": records_out,
    "guidance": [],
    "extraction_conf": 1.0,
}
store.put("XPEV", "2025-12-31", result)

print("\n=== FactRegistry ===")
from cagent_os.provenance.fact_registry import FactRegistry
reg = FactRegistry(turn=0)
facts = reg.register_tool_result("financial.edgar.release", result)

quarter_facts = [f for f in facts if f.kind == "data" and f.period_type == "quarter"]
fiscal_year_facts = [f for f in facts if f.kind == "data" and f.period_type == "fiscal_year"]

print(f"  Total data facts: {len([f for f in facts if f.kind == 'data'])}")
print(f"  Quarter facts: {len(quarter_facts)}")
print(f"  Fiscal year facts: {len(fiscal_year_facts)}")

# ── Verification ────────────────────────────────────────────────
print("\n=== Quarter record verification ===")
all_ok = True
for f in quarter_facts:
    status = "✓" if f.accounting_standard == "US_GAAP" else "✗"
    if f.accounting_standard != "US_GAAP":
        all_ok = False
    print(f"  {status} {f.caliber:20s} = {f.value:>18,.0f}  "
          f"period={f.period_end}  acct_std={f.accounting_standard!r}")

print(f"\n=== Fiscal year record verification ===")
for f in fiscal_year_facts:
    status = "✓" if f.accounting_standard == "US_GAAP" else "✗"
    if f.accounting_standard != "US_GAAP":
        all_ok = False
    print(f"  {status} {f.caliber:20s} = {f.value:>18,.0f}  "
          f"period={f.period_end}  acct_std={f.accounting_standard!r}")

# ── Acceptance ──────────────────────────────────────────────────
print(f"\n{'='*60}")
if all_ok:
    print("✓ ACCEPTED: All LANE 2 facts have accounting_standard='US_GAAP'")
else:
    print("✗ REJECTED: Some facts have missing/incorrect accounting_standard")
    sys.exit(1)

# ── Bonus: Verify failure paths ─────────────────────────────────
print("\n=== Failure path verification ===")
# No CIK → ""
std_no_cik = asyncio.run(get_issuer_accounting_standard("ZZZ999"))  # bogus ticker
assert std_no_cik == "", f"No-CIK should return '', got {std_no_cik!r}"
print(f"  Bogus ticker (no CIK): {std_no_cik!r} ✓")

# CIK exists → specific value (cached, no API call)
std_tsla = asyncio.run(get_issuer_accounting_standard("TSLA"))
assert std_tsla == "US_GAAP", f"TSLA should be US_GAAP, got {std_tsla!r}"
print(f"  TSLA (real CIK): {std_tsla!r} ✓")

print("\n✓ All checks passed.")
