"""Test P1 derived chain — end-to-end verification."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")
from cagent_os.provenance import (
    FactRegistry, Fact, check_provenance,
    extract_derivations_block, verify_derivations, register_derived_facts,
)

# Build a mock registry with XPEV Q4 2025 data
reg = FactRegistry(turn=0)

# Simulate edgar.release facts (what the agent would see in _fact_refs)
facts_data = [
    ("revenue", 22253759000, "2025-12-31", "quarter"),
    ("revenue", 16105490000, "2024-12-31", "quarter"),
    ("net_income", 510000000, "2025-12-31", "quarter"),
    ("net_income", -1390000000, "2024-12-31", "quarter"),
    ("gross_profit", 3193000000, "2025-12-31", "quarter"),
    ("cost_of_revenue", 19060759000, "2025-12-31", "quarter"),
]

for caliber, value, period_end, period_type in facts_data:
    f = Fact(
        id=reg.next_id(),
        kind="data",
        value=value,
        caliber=caliber,
        period_end=period_end,
        period_type=period_type,
        source="EDGAR",
        capability="financial.edgar.release",
        audited=True,
        currency="CNY",
    )
    reg._facts.append(f)

# Show facts
print("Registry facts:")
for f in reg.facts:
    print(f"  {f.id}: {f.caliber}={f.value} ({f.period_end})")

# Simulate agent output with derivation block
# Net margin = net_income / revenue = 510000000 / 22253759000 ≈ 0.0229
# YoY revenue = (rev_q4_2025 - rev_q4_2024) / abs(rev_q4_2024) ≈ 0.382
output = """小鹏 Q4 2025 营收 222.54 亿，同比增长 38.2%。

净利 5.1 亿，净利率约 2.3%，首次实现单季度盈利。

[derivations]
f:0:3 / f:0:1 = 0.0229
(f:0:1 - f:0:2) / abs(f:0:2) = 0.382
[/derivations]"""

print(f"\n{'='*60}")
print("Agent output (with derivations):")
print(output)

# Step 1: Extract block
cleaned, dr = extract_derivations_block(output)
print(f"\nBlock found: {dr is not None}")
if dr:
    print(f"  Derivations parsed: {len(dr.derivations)}")
    for d in dr.derivations:
        print(f"    {d.line}")

# Step 2: Verify
if dr:
    verify_derivations(dr, reg)
    print(f"  Verified: {dr.verified_count}")
    print(f"  Errors: {dr.error_count}")
    for vd in dr.verified:
        print(f"    {vd.formula_display} = {vd.computed_value} {vd.result_display_hint}")
        print(f"      audited={vd.audited} currency={vd.currency} precision={vd.precision!r}")
    for err in dr.errors:
        print(f"    ERROR: {err}")

# Step 3: Register as facts
if dr:
    new_facts = register_derived_facts(dr, reg)
    print(f"\n  Registered derived facts: {len(new_facts)}")
    for nf in new_facts:
        print(f"    {nf.id}: kind={nf.kind} value={nf.value} display={nf.display}")

# Step 4: Full check_provenance
print(f"\n{'='*60}")
print("Full check_provenance:")
prov = check_provenance(output, reg)
print(f"  traced: {prov.traced}")
print(f"  derived_traced: {prov.derived_traced}")
print(f"  untraced: {prov.untraced}")
print(f"  non_data: {prov.non_data}")
print(f"  verified_citation: {prov.verified_citation}")
print(f"  Summary: {prov.summary()}")
print(f"  Traced numbers: {[(t.raw, t.value, t.status) for t in prov.traced_numbers]}")
print(f"  Untraced numbers: {[(t.raw, t.value) for t in prov.untraced_numbers]}")

# ── Test 2: Semantic references ──
output2 = """小鹏 Q4 2025 营收 222.54 亿，同比增长 38.2%。

净利 5.1 亿，净利率约 2.3%。

[derivations]
net_income@2025Q4 / revenue@2025Q4 = 0.0229
(revenue@2025Q4 - revenue@2024Q4) / abs(revenue@2024Q4) = 0.382
[/derivations]"""

print(f"\n{'='*60}")
print("Test 2: Semantic references")
cleaned2, dr2 = extract_derivations_block(output2)
if dr2:
    print(f"  Derivations parsed: {len(dr2.derivations)}")
    for d in dr2.derivations:
        print(f"    {d.line}")
        print(f"      fact_ids={d.parent_ids}  semantic={d.parent_semantic}")
    verify_derivations(dr2, reg)
    print(f"  Verified: {dr2.verified_count}, Errors: {dr2.error_count}")
    for vd in dr2.verified:
        print(f"    {vd.formula_display} = {vd.computed_value} {vd.result_display_hint}")
    for err in dr2.errors:
        print(f"    ERROR: {err}")

# Step 5: Test error cases
print(f"\n{'='*60}")
print("Error cases:")
error_tests = [
    # Missing parent
    ("f:99:99 / f:0:1 = 0.5", "Missing parent"),
    # Currency mismatch (we don't have multi-currency data, so skip)
    # Result mismatch
    ("f:0:3 / f:0:1 = 0.999", "Wrong result"),
    # Invalid function
    ("f:0:1 ** 2 = 100", "Invalid operator **"),
]

for formula, desc in error_tests:
    block = f"[derivations]\n{formula}\n[/derivations]"
    _, dr2 = extract_derivations_block("test\n" + block)
    if dr2:
        verify_derivations(dr2, reg)
        status = "✅ OK" if dr2.error_count > 0 else "❌ MISSED"
        result = dr2.errors[0][:80] if dr2.errors else "no error"
        print(f"  {desc}: {status} — {result}")

print("\nDone!")
