"""Find exact FX rate text in XPEV fixture."""
from pathlib import Path
from bs4 import BeautifulSoup
import re

text = BeautifulSoup(Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html").read_bytes(), "lxml").get_text(" ", strip=True)
# Find all occurrences of "exchange rate" with wide context
for m in re.finditer(r"exchange rate", text, re.IGNORECASE):
    start = max(0, m.start() - 50)
    end = min(len(text), m.end() + 200)
    print(f"...{text[start:end]}...")
    print()
