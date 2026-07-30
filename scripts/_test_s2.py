"""Test S2: AAPL 8-K Item 2.02."""
import asyncio, sys
sys.path.insert(0, "src")
from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder

async def main():
    finder = EarningsReleaseFinder()
    
    for qe, label in [("2026-03-28", "Q2 FY2026"), ("2025-12-27", "Q1 FY2026"),
                       ("2025-09-27", "Q4 FY2025"), ("2025-06-28", "Q3 FY2025")]:
        result = await finder.find("AAPL", qe)
        if result and result.get("found"):
            print(f"{label} ({qe}): YES | conf={result['conf']} | {result['filing_date']} | {result['document'][:35]} | {result['accession']}")
        else:
            print(f"{label} ({qe}): NO")

asyncio.run(main())
