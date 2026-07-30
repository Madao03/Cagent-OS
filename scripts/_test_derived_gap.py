"""Test: why is -76.4% classified as hallucination not derived?"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")

from cagent_os.provenance.normalizer import extract_numbers
from cagent_os.provenance.fact_registry import FactRegistry

# Build registry with actual XPEV Q4 values
reg = FactRegistry(turn=1)
# Operating income values from the actual registry
ois = [108154000.0, 44789000.0, 94093000.0, -1113000.0, 22173000.0]
for val in ois:
    reg._facts.extend(reg._extract_from_dict("edgar", {"operating_income": val}, {}))

# The RESCALES and classify_untracked logic from baseline runner
RESCALES = [100.0, 0.01, 1e4, 1e-4, 1e8, 1e-8]

def classify_untracked(value, registry_facts):
    data_vals = [
        f.value for f in registry_facts
        if isinstance(f.value, (int, float)) and not isinstance(f.value, bool)
        and f.kind in ("data", "text_citation") and f.value != 0
    ]
    for rv in data_vals:
        for s in RESCALES:
            if rv != 0 and abs(value * s - rv) <= abs(rv) * 0.01:
                return "normalization"
    for a in data_vals:
        for b in data_vals:
            if a == b or b == 0:
                continue
            candidates = [a / b, a - b, (a - b) / abs(b), a + b]
            for c in candidates:
                if c == 0:
                    continue
                if abs(value - c) <= abs(c) * 0.02:
                    return "derived"
                # Percentage bridge
                if abs(value / 100 - c) <= abs(c) * 0.02:
                    return "derived"
                if abs(value * 100 - c) <= abs(c) * 0.02:
                    return "derived"
    return "hallucination"

# Test: normalize -76.4% → value = -76.4
nums = extract_numbers("-76.4%")
for n in nums:
    print(f"raw={n.raw} value={n.value} is_data={n.is_data}")
    result = classify_untracked(n.value, reg.facts)
    print(f"  → {result}")
    
    # Manually check derived candidates
    vals = [f.value for f in reg.facts if isinstance(f.value, (int, float))]
    print(f"  Registry values: {vals}")
    for a in vals:
        for b in vals:
            if a == b or b == 0:
                continue
            yoy = (a - b) / abs(b)
            if abs(n.value/100 - yoy) < 0.01:
                print(f"  ★ MATCH with /100: ({a} - {b}) / |{b}| = {yoy:.4f} ≈ {n.value/100}")
            if abs(n.value - yoy*100) < 1:
                print(f"  ★ ×100 gap: value={n.value}, derived*100={yoy*100:.1f}")
