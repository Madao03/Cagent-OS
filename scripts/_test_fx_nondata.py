"""Test: fx_rate non-data exclusion and derived fix together."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")

from cagent_os.provenance.normalizer import extract_numbers

# Test fx_rate in context
tests = [
    "CNY/USD 汇率 6.9931",
    "折算汇率 7.25",
    "财报数据：营收 222.54亿",  # should still be data
]
for t in tests:
    nums = extract_numbers(t)
    print(f"'{t[:40]}': {[(n.raw, n.is_data) for n in nums]}")
