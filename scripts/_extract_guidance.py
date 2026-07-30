"""Extract exact guidance text from fixtures."""
from pathlib import Path
from bs4 import BeautifulSoup
import re

# XPEV guidance
text = BeautifulSoup(Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html").read_bytes(), "lxml").get_text(" ", strip=True)
print("=== XPEV 'to be between' context ===")
for m in re.finditer(r"to be between", text, re.IGNORECASE):
    start = max(0, m.start() - 100)
    end = min(len(text), m.end() + 200)
    print(f"\n  ...{text[start:end]}...")

print("\n\n=== AAPL guidance context ===")
aapl_text = BeautifulSoup(Path("tests/fixtures/edgar/aapl_8k_earnings.html").read_bytes(), "lxml").get_text(" ", strip=True)
for keyword in ["expect", "guidance", "outlook", "approximately", "13%", "16%"]:
    for m in re.finditer(re.escape(keyword), aapl_text, re.IGNORECASE):
        start = max(0, m.start() - 80)
        end = min(len(aapl_text), m.end() + 200)
        snippet = aapl_text[start:end].strip()
        if "revenue" in snippet.lower() or "growth" in snippet.lower() or "billion" in snippet.lower() or "%" in snippet:
            print(f"\n  [{keyword}] ...{snippet[:250]}...")
            break
