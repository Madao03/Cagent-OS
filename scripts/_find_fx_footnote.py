"""Find FX rate footnote in XPEV fixtures."""
from pathlib import Path
from bs4 import BeautifulSoup
import re

for fixture in sorted(Path("tests/fixtures/edgar").glob("xpev_6k_*earnings*.html")):
    text = BeautifulSoup(fixture.read_bytes(), "lxml").get_text(" ", strip=True)
    # Search for exchange rate footnotes
    matches = re.findall(r".{0,80}(exchange rate|convenience translation|translated into).{0,120}", text, re.IGNORECASE)
    if matches:
        print(f"\n{fixture.name}:")
        for m in matches[:3]:
            print(f"  ...{m.strip()[:180]}...")
