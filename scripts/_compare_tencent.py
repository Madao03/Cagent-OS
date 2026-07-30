"""Compare baseline 13 numbers vs gate-enabled 13 numbers.
Determines: did the agent discover new numbers, or justify pre-existing knowledge?
"""
import json

# From provenance_baseline_report.json (run 1, no gate)
baseline_numbers = [
    ("1,928.69 亿", 192869000000.0),
    ("15%", 15.0),
    ("1,888", 1888.0),
    ("1,891 亿", 189100000000.0),
    ("959 亿", 95900000000.0),
    ("16%", 16.0),
    ("362 亿", 36200000000.0),
    ("21%", 21.0),
    ("582 亿", 58200000000.0),
    ("706 亿", 70600000000.0),
    ("18%", 18.0),
    ("1,088 亿", 108800000000.0),
    ("22%", 22.0),
]

# From gate-enabled run (run 2, output captured from terminal)
gate_numbers = [
    ("1,928.69 亿", 192869000000.0),
    ("15%", 15.0),
    ("959 亿", 95900000000.0),
    ("16%", 16.0),
    ("362 亿", 36200000000.0),
    ("21%", 21.0),
    ("582 亿", 58200000000.0),
    ("10%", 10.0),
    ("1,088 亿", 108800000000.0),
    ("22%", 22.0),
    ("726 亿", 72600000000.0),
    ("18%", 18.0),
    ("0700", 700.0),  # stock code
]

# Compare
baseline_vals = {v for _, v in baseline_numbers}
gate_vals = {v for _, v in gate_numbers}

unchanged = baseline_vals & gate_vals
only_baseline = baseline_vals - gate_vals
only_gate = gate_vals - baseline_vals

print("=== NUMBER-BY-NUMBER COMPARISON ===\n")
print(f"{'#':<4} {'Baseline':<20} {'Gate':<20} {'Verdict'}")
print("-" * 60)

all_vals = sorted(baseline_vals | gate_vals, reverse=True)
for v in all_vals:
    b_raw = next((r for r, val in baseline_numbers if val == v), "")
    g_raw = next((r for r, val in gate_numbers if val == v), "")
    if v in unchanged:
        verdict = "★ IDENTICAL"
    elif v in only_baseline:
        verdict = "dropped"
    else:
        verdict = "new"
    print(f"{'':<4} {b_raw:<20} {g_raw:<20} {verdict}")

print(f"\n=== SUMMARY ===")
print(f"Identical (both runs):  {len(unchanged)} / 13 = {len(unchanged)/13*100:.0f}%")
print(f"Only in baseline:       {len(only_baseline)}")
print(f"Only in gate run:       {len(only_gate)}")

print(f"\n=== VERDICT ===")
overlap_pct = len(unchanged) / max(len(baseline_vals), len(gate_vals)) * 100
if overlap_pct > 70:
    print(f"⚠️ MOTIVATED CITATION: {overlap_pct:.0f}% of numbers are identical.")
    print("Agent recalled numbers from parametric knowledge,")
    print("then searched for URLs to justify them.")
    print("The search was for LEGITIMACY, not for INFORMATION.")
elif overlap_pct < 30:
    print(f"✅ GATE SUCCESS: {100-overlap_pct:.0f}% of numbers changed.")
    print("Baseline numbers were hallucinated;")
    print("gate run discovered genuinely different data.")
else:
    print(f"MIXED: {overlap_pct:.0f}% overlap — needs manual review.")
