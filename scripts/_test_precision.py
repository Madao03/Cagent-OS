"""Debug: why isn't _precision flowing into Facts?"""
import sys, json, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")

from cagent_os.provenance.fact_registry import FactRegistry

db = sqlite3.connect("data/edgar_release.db")
cur = db.execute("SELECT records_json FROM edgar_release_cache WHERE ticker='XPEV' AND quarter_end='2025-12-31'")
r = cur.fetchone()
recs = json.loads(r[0])
db.close()

# Test with quarter record that has _precision
rec = recs[2]  # quarter end=2024-12-31
print(f"Record keys: {list(rec.keys())}")
print(f"_precision: {rec.get('_precision')}")
print(f"net_income: {rec.get('net_income')}")

reg = FactRegistry(turn=1)
facts = reg._extract_from_dict("financial.edgar.release", rec, {"ticker": "XPEV"})
reg._facts.extend(facts)

for f in reg._facts:
    print(f"  caliber={f.caliber} value={f.value} precision='{f.precision}' period_type={f.period_type}")
