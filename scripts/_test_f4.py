"""Test F4 cache: first call extracts, second call hits cache."""
import sys, time
sys.path.insert(0, "src")
from cagent_os.plugins.financial.plugin import FinancialPlugin
from cagent_os.config.settings import Settings

plugin = FinancialPlugin(settings=Settings(), toolkit=None, data_layer=None, memory_api=None, rag_service=None)

# Call 1: should do real extraction
t0 = time.perf_counter()
r1 = plugin._dispatch("financial.edgar.release", {"ticker": "XPEV", "quarter_end": "2025-12-31"})
t1 = time.perf_counter() - t0

# Call 2: should hit cache
t0 = time.perf_counter()
r2 = plugin._dispatch("financial.edgar.release", {"ticker": "XPEV", "quarter_end": "2025-12-31"})
t2 = time.perf_counter() - t0

print(f"Call 1: {t1:.3f}s | success={r1['success']} | records={r1.get('record_count')} | cached={r1.get('cached', False)}")
print(f"Call 2: {t2:.3f}s | success={r2['success']} | records={r2.get('record_count')} | cached={r2.get('cached', False)}")

if r2.get("cached"):
    print(f"\nCache speedup: {t1/t2:.0f}x ({t1:.1f}s → {t2*1000:.0f}ms)")
else:
    print("\nCache MISS on second call!")
