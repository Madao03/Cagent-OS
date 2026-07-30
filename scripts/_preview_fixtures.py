"""Preview all fixtures: show size + first 100 chars."""
from pathlib import Path
from bs4 import BeautifulSoup

FIXTURE_DIR = Path("tests/fixtures/edgar")
for f in sorted(FIXTURE_DIR.glob("*.html")):
    soup = BeautifulSoup(f.read_bytes(), "lxml")
    text = soup.get_text(" ", strip=True)[:100]
    print(f"{f.name:45s} {f.stat().st_size:>8d}B  {text}")
