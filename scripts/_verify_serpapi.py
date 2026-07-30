"""Test SerpAPI directly."""
import os, requests
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ.get("SERPAPI_KEY", "").strip()
print(f"SERPAPI_KEY: {'set' if api_key else 'NOT SET'}")

resp = requests.get(
    "https://serpapi.com/search",
    params={"engine": "google", "api_key": api_key, "q": "NVDA earnings Q2 2026", "num": 5},
    timeout=10,
)
print(f"status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    organic = data.get("organic_results", [])
    print(f"organic_results: {len(organic)}")
    for i, item in enumerate(organic[:5]):
        print(f"  {i+1}. {item.get('title', '')[:60]}")
        print(f"     {item.get('link', '')[:80]}")
        print(f"     {item.get('snippet', '')[:100]}")
else:
    print(f"error: {resp.text[:300]}")
