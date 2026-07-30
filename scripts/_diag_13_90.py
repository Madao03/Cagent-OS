"""Diagnose: why is 13.90 not traced?"""
import sys, json, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")
from cagent_os.provenance.fact_registry import FactRegistry
from cagent_os.provenance.checker import check_provenance

# Build registry with actual XPEV data
db = sqlite3.connect("data/edgar_release.db")
cur = db.execute("SELECT records_json FROM edgar_release_cache WHERE ticker='XPEV' AND quarter_end='2025-12-31'")
r = cur.fetchone()
recs = json.loads(r[0])
db.close()

reg = FactRegistry(turn=1)
for rec in recs:
    facts = reg._extract_from_dict("financial.edgar.release", rec, {"ticker": "XPEV"})
    reg._facts.extend(facts)

# Show relevant registry values
print("Registry net_income values:")
for f in reg._facts:
    if f.caliber == "net_income":
        print(f"  value={f.value} period_type={f.period_type} period_end={f.period_end}")

# Test: various phrasings of Q4 2024 net income
tests = [
    "净收入 -13.9 亿（亏损）",
    "净亏损 13.90 亿",
    "净利润 -13.90亿",
    "亏损 13.9 亿元",
    "-13.9亿",
    "净收入 13.90 亿",  # without loss keyword before
]

for t in tests:
    result = check_provenance(t, reg)
    status = "TRACED" if result.traced > 0 else "UNTRACED"
    detail = ""
    if result.traced_numbers:
        detail = f"→ fact={result.traced_numbers[0].fact_id[:30]} caliber"
    elif result.sign_conflict_numbers:
        detail = f"→ sign_conflict: {result.sign_conflict_numbers[0].conflict_detail[:60]}"
    print(f"\n'{t}': {status} {detail}")
    for u in result.untraced_numbers:
        print(f"  untraced: {u.raw} value={u.value}")
