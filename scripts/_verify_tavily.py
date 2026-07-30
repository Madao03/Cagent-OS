"""Test search providers: Tavily + Perplexity."""
import os
import sys
import time

# Load .env
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, "src")

from cagent_os.plugins.financial.toolkit import FinancialToolkit
from cagent_os.config import get_settings

settings = get_settings()
toolkit = FinancialToolkit(settings=settings)

queries = [
    "NVDA earnings Q2 2026",
    "美联储 2026年7月 利率决议",
    "Bitcoin ETF flows July 2026",
]

for q in queries:
    print(f"\n{'='*60}")
    print(f"Query: {q}")
    print(f"{'='*60}")
    result = toolkit.search_multi_provider(query=q, num_results=5)
    print(f"  providers_used: {result.get('providers_used')}")
    print(f"  providers_failed: {result.get('providers_failed')}")
    print(f"  execution_time: {result.get('execution_time')}s")
    print(f"  results ({len(result.get('results', []))}):")
    for i, r in enumerate(result.get("results", [])[:5]):
        title = r.get("title", "")[:60]
        url = r.get("url", "")[:80]
        snippet = r.get("snippet", "")[:100]
        print(f"    {i+1}. [{title}]")
        print(f"       {url}")
        print(f"       {snippet}")
