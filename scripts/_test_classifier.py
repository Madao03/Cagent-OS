"""Test S3 classifier on multiple quarters and tickers."""
import asyncio, sys
sys.path.insert(0, "src")
from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder

async def test_one(finder, ticker, quarter_end, label=""):
    result = await finder.find(ticker, quarter_end)
    status = "FOUND" if result else "NOT FOUND"
    extra = ""
    if result:
        extra = f" | conf={result['conf']} | {result['filing_date']} | {result['document'][:25]}"
    print(f"  {ticker:6s} {quarter_end} ({label:10s}): {status}{extra}")

async def main():
    finder = EarningsReleaseFinder()
    
    # XPEV quarters
    print("=== XPEV ===")
    await test_one(finder, "XPEV", "2025-12-31", "Q4 2025")
    await test_one(finder, "XPEV", "2025-09-30", "Q3 2025")
    await test_one(finder, "XPEV", "2025-06-30", "Q2 2025")
    await test_one(finder, "XPEV", "2025-03-31", "Q1 2025")
    await test_one(finder, "XPEV", "2024-12-31", "Q4 2024")
    
    # AAPL 8-K
    print("\n=== AAPL ===")
    await test_one(finder, "AAPL", "2026-03-28", "Q2 FY2026")
    await test_one(finder, "AAPL", "2025-12-27", "Q1 FY2026")
    
    # BABA (might not work for FPI)
    print("\n=== BABA ===")
    await test_one(finder, "BABA", "2025-12-31", "Q3 FY2026")

asyncio.run(main())
