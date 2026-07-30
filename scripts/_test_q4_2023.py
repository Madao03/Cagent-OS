"""Check: does Q4 2023 130.50亿 get correctly flagged as untraced?"""
import sys, json, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")

from cagent_os.provenance.fact_registry import FactRegistry
from cagent_os.provenance.checker import check_provenance

# Load actual registry from cache
db = sqlite3.connect("data/edgar_release.db")
cur = db.execute("SELECT records_json FROM edgar_release_cache WHERE ticker='XPEV' AND quarter_end='2025-12-31'")
r = cur.fetchone()
recs = json.loads(r[0])
db.close()

# Build registry from cached records
registry = FactRegistry(turn=1)
for rec in recs:
    facts = registry._extract_from_dict("financial.edgar.release", rec, {"ticker": "XPEV"})
    registry._facts.extend(facts)

print(f"Registry facts: {len(registry.facts)}")
for f in registry.facts:
    print(f"  [{f.kind}] caliber={f.caliber} value={f.value}")

# Test 1: Q4 2023 (NOT in registry — should be untraced)
print("\n--- Test 1: Q4 2023 outside coverage ---")
test = "Q4 2023: 130.50亿"
result = check_provenance(test, registry)
print(f"traced={result.traced} untraced={result.untraced}")
for u in result.untraced_numbers:
    print(f"  UNTRACED: {u.raw}")
for t in result.traced_numbers:
    print(f"  TRACED: {t.raw} → {t.fact_id[:40]}")

# Test 2: Q4 2024 (in registry, should match)
print("\n--- Test 2: Q4 2024 inside coverage ---")
test2 = "Q4 2024: 161.05亿"
result2 = check_provenance(test2, registry)
print(f"traced={result2.traced} untraced={result2.untraced}")
for t in result2.traced_numbers:
    print(f"  TRACED: {t.raw} → {t.source}")
for u in result2.untraced_numbers:
    print(f"  UNTRACED: {u.raw}")
