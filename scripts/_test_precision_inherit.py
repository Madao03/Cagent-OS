"""Precision inheritance end-to-end test.

Verifies: net_income (2_sig_digits_from_billion) / revenue (full)
  → inherited precision = min → 2_sig_digits_from_billion
  → display hint = "≈ 2.3%" (not 0.022917...)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")
from cagent_os.provenance import (
    FactRegistry, Fact, check_provenance,
    extract_derivations_block, verify_derivations, register_derived_facts,
)

reg = FactRegistry(turn=0)

# Simulate facts: net_income from billion-scale merge (precision=2_sig_digits)
# and revenue at full precision
facts = [
    ("revenue", 22253759000, "2025-12-31", "quarter", "CNY", ""),
    ("net_income", 510000000, "2025-12-31", "quarter", "CNY", "2_sig_digits_from_billion"),
    ("revenue", 16105096000, "2024-12-31", "quarter", "CNY", ""),
    ("net_income", -1390000000, "2024-12-31", "quarter", "CNY", "2_sig_digits_from_billion"),
    ("gross_profit", 4741806000, "2025-12-31", "quarter", "CNY", ""),
    ("gross_profit", 2324777000, "2024-12-31", "quarter", "CNY", ""),
]
for caliber, value, pe, pt, curr, prec in facts:
    f = Fact(id=reg.next_id(), kind="data", value=value, caliber=caliber,
             period_end=pe, period_type=pt, currency=curr, precision=prec,
             source="EDGAR", capability="financial.edgar.release", audited=True)
    reg._facts.append(f)

print("Registry facts:")
for f in reg.facts:
    print(f"  {f.id}: {f.caliber}={f.value} precision={f.precision!r}")

# Agent output with derivations
output = """小鹏 Q4 2025 营收 222.54 亿，净利 5.1 亿，净利率约 2.3%。

[derivations]
net_income@Q4 2025 / revenue@Q4 2025 = 0.0229
(revenue@Q4 2025 - revenue@Q4 2024) / abs(revenue@Q4 2024) = 0.382
gross_profit@Q4 2025 / revenue@Q4 2025 = 0.2131
[/derivations]"""

print(f"\n{'='*60}")
print("Testing precision inheritance + percentage bridge")
prov = check_provenance(output, reg)

print(f"  traced: {prov.traced}")
print(f"  derived_traced: {prov.derived_traced}")
print(f"  untraced: {prov.untraced}")
print(f"  Summary: {prov.summary()}")

if prov.derivation_result:
    print(f"\n  Derivations: {len(prov.derivation_result.derivations)} parsed, "
          f"{len(prov.derivation_result.verified)} verified, "
          f"{len(prov.derivation_result.errors)} errors")
    for vd in prov.derivation_result.verified:
        print(f"    {vd.formula_display}")
        print(f"      computed={vd.computed_value} hint={vd.result_display_hint!r}")
        print(f"      audited={vd.audited} currency={vd.currency} precision={vd.precision!r}")
    for err in prov.derivation_result.errors:
        print(f"    ERROR: {err}")

# Check: registered derived facts
print(f"\n  Derived facts in registry:")
for f in reg.facts:
    if f.kind == "derived":
        print(f"    {f.id}: value={f.value} display={f.display} precision={f.precision!r}")

# Check: all numbers traced
print(f"\n  Traced numbers:")
for t in prov.traced_numbers:
    print(f"    '{t.raw}' value={t.value} status={t.status} kind={t.kind} fact={t.fact_id}")
print(f"\n  Untraced numbers:")
for u in prov.untraced_numbers:
    print(f"    '{u.raw}' value={u.value}")

# ── Assertions ──
print(f"\n{'='*60}")
print("CHECKS:")

# 1. derived_traced ≥ 3
ok1 = prov.derived_traced >= 3
print(f"  derived_traced ≥ 3: {'✅' if ok1 else '❌'} ({prov.derived_traced})")

# 2. All untraced should be 0 (all % numbers should match via bridge)
ok2 = prov.untraced == 0
print(f"  untraced == 0: {'✅' if ok2 else '❌'} ({prov.untraced})")

# 3. Precision inheritance: net_income/revenue should get 2_sig_digits_from_billion
precision_fact = None
for f in reg.facts:
    if f.kind == "derived" and "net_income" in f.display and "revenue" in f.display and abs(float(f.value) - 0.0229) < 0.01:
        precision_fact = f
        break
ok3 = precision_fact is not None and precision_fact.precision == "2_sig_digits_from_billion"
print(f"  precision inheritance (net_income→derived): {'✅' if ok3 else '❌'}")
if precision_fact:
    print(f"    precision={precision_fact.precision!r} value={precision_fact.value}")

# 4. Percentage bridge: check that 2.3% (value=2.3) is matched
# The output has "净利率约 2.3%" → normalizer extracts 2.3
pct_matched = any("2.3" in t.raw for t in prov.traced_numbers)
print(f"  2.3% matched via bridge: {'✅' if pct_matched else '❌'}")

# 5. Display hint for precision-limited fact
ok5 = precision_fact and "≈" in precision_fact.display
print(f"  display hint '≈': {'✅' if ok5 else '❌'}")
if precision_fact:
    print(f"    display={precision_fact.display}")

all_ok = ok1 and ok2 and ok3 and pct_matched and ok5
print(f"\n  OVERALL: {'✅ ALL PASSED' if all_ok else '❌ SOME FAILED'}")
