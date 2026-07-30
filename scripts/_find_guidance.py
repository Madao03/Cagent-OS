"""Find guidance text in fixtures."""
from pathlib import Path
from bs4 import BeautifulSoup
import re

for name in ["xpev_6k_fy2025q4_earnings", "aapl_8k_earnings"]:
    fp = Path(f"tests/fixtures/edgar/{name}.html")
    if not fp.exists():
        continue
    text = BeautifulSoup(fp.read_bytes(), "lxml").get_text(" ", strip=True)
    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"{'='*60}")

    # Search for guidance patterns
    patterns = [
        (r".{0,80}(expect|guidance|outlook|forecast|estimate).{0,150}", "expect/guidance/outlook"),
        (r".{0,80}(to be between|range of|approximately).{0,150}", "range/between"),
        (r".{0,40}(represent.{0,20}increase|represent.{0,20}decrease).{0,100}", "represent increase/decrease"),
    ]

    for regex, label in patterns:
        matches = re.findall(regex, text, re.IGNORECASE)
        if matches:
            print(f"\n  [{label}] ({len(matches)} matches):")
            for m in matches[:3]:
                clean = m.strip()[:200]
                print(f"    {clean}")
