"""Test Perplexity search directly."""
import os, sys, requests, json
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
print(f"PERPLEXITY_API_KEY: {'set' if api_key else 'NOT SET'}")

queries = ["NVDA earnings Q2 2026", "美联储 2026年7月 利率决议"]

for q in queries:
    print(f"\n{'='*60}")
    print(f"Query: {q}")
    resp = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "sonar",
            "messages": [{"role": "user", "content": q}],
            "max_tokens": 512,
        },
        timeout=15,
    )
    print(f"  status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        citations = data.get("citations", [])
        print(f"  answer: {answer[:200]}...")
        print(f"  citations ({len(citations)}):")
        for c in citations[:5]:
            print(f"    - {c}")
    else:
        print(f"  error: {resp.text[:200]}")
