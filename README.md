# CagentOS

> English | [中文](README.zh-CN.md)
>
> **Status: Beta Online ✅ — Live at cagentos.com — 16 skills · 42+ capabilities · 10 data sources · Multi-agent + Cron + Web UI + RAG + Provenance + Playwright + Auto-Eval**
> A self-contained financial research agent operating system built from scratch — not a LangChain wrapper.

CagentOS is a Python framework for building AI agents that perform financial research. It implements a ReAct loop with event sourcing at its core, surrounded by a plugin-based tool system, cross-session memory, a provenance layer that traces every number to its source, and a data integrity layer designed specifically for financial data.

## Why this exists

LangChain is too abstract. LangGraph's state machine is overkill for most agent workflows. AutoGen focuses on multi-agent dialog. None of them have a data integrity wall — in financial research, a Forward PE that's 47% off silently corrupts every downstream conclusion.

CagentOS fills this gap with a minimal, readable runtime that you can understand end-to-end, plus a data pipeline that catches bad data before it reaches the LLM, and a provenance system that ensures **zero hallucination on core financial numbers** (verified by frozen baselines).

## Architecture

```
CLI / HTTP API / Web UI
     ↓
AgentRuntime (ReAct loop + Event Sourcing)
  ├── PromptBuilder          (system prompt assembly + derivation lineage)
  ├── ModelRouter → LLM      (8 providers, cost-tiered routing)
  ├── ToolGuard              (allow-list authorization)
  ├── ToolDispatcher         (plugin-based tool execution)
  └── TranscriptReplayer     (event stream → LLM transcript)
        ↑
  EventStore (SQLite, WAL mode)
        ↑
  Plugins: financial · crypto · web · read · write · skills · memory · panews
        ↑
  Provenance Layer (provenance/)
  ├── FactRegistry           (field-level fact registration + precision propagation)
  ├── Normalizer             (CN magnitude/currency/percentage normalization)
  ├── Checker (3-pass)       (exact → abs → verbatim matching)
  └── Gate                   (route-aware feedback + best-attempt + derivation fork)
  ────────────────────────────────────────
  Cross-cutting:
    Ⓐ Memory (hot ≤500 chars / cold SQLite 3-tables / LLM contradiction detection)
    Ⓑ Observability (TraceWriter + TraceReader query API / DICA 4-dimension tagging)
    Ⓒ Data Integrity Wall (10 sources / variance >5% alert / circuit breaker + fallback)
    Ⓓ Eval (Golden Cases ×14 + 25-criterion LLM-Judge + pre-launch baseline)
  ────────────────────────────────────────
  Multi-agent layer (Phase 4a/4b):
    Supervisor (self-built orchestrator)
      ├── DataCollector (parallel) — RAG + FRED + web search
      ├── Researcher   (parallel) — full skill suite via injected AgentRuntime
      ├── Red-Team     (serial)   — heuristic adversarial check
      └── Editor       (serial)   — decision summary compression
    CronAgent (scheduled) — daily crypto brief + weekly macro report
```

### Core mechanisms

| Mechanism | Source | Implementation |
|-----------|--------|----------------|
| ReAct loop | Yao et al., 2022 | `AgentRuntime.run()` — wall-clock 240s + iteration limit + graceful degrade (never empty output) |
| Event Sourcing | Fowler, 2005 | `JournalEntry` → `EventStore` → `TranscriptReplayer.replay()` |
| Tool/Function Calling | OpenAI, 2023 | `ToolRegistry` + `ToolSchema` (JSON Schema) |
| Access control | — | `ToolGuard` (allow-list) + `ArgumentChecker` (schema validation) |
| MCP | Anthropic, 2024 | `MCPSessionManager` (official `mcp` SDK) |
| Provenance | — | `FactRegistry` → `Checker` → `Gate` — every number traced to source |

## Quick start

```bash
# Install
pip install -e ".[dev]"

# Set up environment
cp .env.example .env
# Edit .env — add your DeepSeek API key (or OpenRouter key)

# Run a one-shot query
cagent-os chat "What is NVDA's forward PE?"

# Or start the interactive REPL
cagent-os

# Or start the Web UI + HTTP API
uvicorn cagent_os.interfaces.http.app:create_app --factory --host 0.0.0.0 --port 8000
```

## Data sources (10)

| Source | Coverage | Access |
|--------|----------|--------|
| **SEC EDGAR** | 10-K/20-F XBRL facts + 6-K/8-K earnings releases + Guidance | `EdgarAdapter` (LANE 1) + `EarningsReleaseExtractor` (LANE 2) |
| **FRED** | 21 macro series (ONRRP/TGA/reserves/yields/employment/inflation/M1M2) | `FredAdapter` |
| **yfinance** | US stock valuation (PE/PB/ROE) + earnings + news | `YFinanceAdapter` (with circuit breaker) |
| **akshare** | A-shares + HK stocks + China futures (5 exchanges × 82 products) | `AkshareStockAdapter` + `AkshareFuturesAdapter` (Sina source) |
| **金十 MCP** | Real-time quotes + economic calendar + flash news | MCP streamable-http, Bearer token |
| **PANews** | Crypto news (7 capabilities: search/briefing/trending/article/polymarket/hooks/events) | `PanewsPlugin` (HTTP API) |
| **DeFiLlama** | TVL / stablecoins / protocol revenue / DEX volume / yield pools | `DefiLlamaAdapter` (free, no key) |
| **Coin Metrics** | On-chain fundamentals (MVRV / MVRV-Z for BTC/ETH) | `CoinMetricsAdapter` (Community tier) |
| **Binance Futures** | Funding rates / Open Interest / Long-Short ratio | `BinanceDerivativesAdapter` (free) |
| **Fear & Greed** | Crypto sentiment index (0-100) | `FearGreedAdapter` (alternative.me, free) |

## What's included

- **AgentRuntime**: ReAct loop with wall-clock budget (240s) + iteration limit + graceful degrade — never returns empty output
- **Provenance System**: `FactRegistry` (field-level fact registration) + `Normalizer` + `Checker` (3-pass: exact→abs→verbatim) + `Gate` (route-aware feedback) + P1 derivation chain (agent-declared parents, AST-validated formulas, inheritance rules)
- **SEC EDGAR** (LANE 1+2): companyfacts XBRL structured data + 6-K/8-K earnings release extraction with offline materialization cache (362x speedup)
- **Crypto Data Adapters** (4 sources × 7 capabilities): DeFiLlama + Coin Metrics + Binance + Fear&Greed — all free, no API key needed
- **ToolRegistry + ToolGuard + ArgumentChecker**: plugin-based tools with JSON Schema validation and allow-list authorization
- **EventStore**: SQLite-backed event sourcing with WAL mode for concurrent reads
- **TraceReader**: Conversation history query API (list/summary/timeline/count) + DICA 4-dimension tagging
- **8 LLM providers**: OpenRouter, DeepSeek, OpenAI, Anthropic, Groq, SiliconFlow, Together, Custom
- **MCP Client**: Multi-transport session manager (Anthropic official SDK)
- **Memory system**: Hot memory (≤500 chars in system prompt) + Cold memory (SQLite 3 tables) + **LLM contradiction detection**
- **Data Integrity Wall**: 10 sources → variance detection (>5% alert) → cross-validation → circuit breaker + akshare price fallback
- **Browser fetch**: Playwright + Readability.js + Stealth anti-bot — native Linux Playwright with circuit breaker (3 fails → 5min cooldown) + concurrency limiter (1 Chromium instance) + UTF-8 encoding fix for Chinese sites
- **Skill Schemas**: Pydantic v2 I/O schemas for core skills + State 3-layer separation + permission matrix
- **Golden Cases**: 14 evaluation benchmarks (including "data unavailable" anti-hallucination case)
- **RAG Pipeline**: Qwen3-Embedding-8B + 6 chunking schemes + Reranker (cos 0.79→0.999) + NumPy vector store
- **Auto-Evaluation**: 25 criterion LLM-Judge + JSON result storage + history comparison + dashboard
- **CLI + HTTP dual entry**: REPL for local, FastAPI + SSE for web
- **Web UI** (Phase 4c): HTML + vanilla JS three-in-one page (chat panel / daily brief / knowledge browser) + JWT auth + static asset hosting
- **Multi-agent orchestration** (Phase 4a): Self-built Supervisor coordinating 4 agents with Pydantic message bus, parallel + serial pipeline, intent-based routing
- **Cron scheduler** (Phase 4b): CronAgent with pre-configured report templates (crypto daily + macro weekly), integrated into FastAPI lifespan
- **Reliability chain**: Lock TTL self-heal (5min) → wall-clock fallback (240s) → yfinance circuit breaker (3 fails → 300s cooldown) → akshare price degradation → never empty output

## What's NOT included (yet)

- Langfuse trace visualization (Phase 4d)
- Evaluation regression CI suite (Phase 4e)
- Self-improving flywheel / model fine-tuning (Phase 5)

## Skills

**16** investment research skills included as `.md` templates loaded dynamically:

**Core research skills (9):**
- `us-stock-analysis` — Three-tier analysis (normal/abnormal/black-box) + cyclical trap detection (5 signals)
- `macro-analysis` — **Rewritten** time-horizon × indicator-weight framework + PMI sub-index + CPI-PPI spread
- `crypto-analysis` — Crypto three-tier analysis + cycle positioning (MVRV-Z / Fear&Greed / funding rate)
- `read-later` — L1/L2/L3 progressive disclosure + Obsidian image localization
- `content-triage` — Five-dimension scoring (A/B/C) + append-only ledger (29 entries accumulated)
- `content-assetize` — A-class articles → facts/opinions/frameworks structured assets
- `crypto-stock-analysis` — MSTR/COIN/miners mNAV + STRC flywheel
- `tech-sector-bridge` — Macro → tech sector transmission matrix
- `crypto-funds-flow-analysis` — Stablecoins / CEX / TVL / leverage

**Extended skills (7):**
- `defi-analysis` — DeFi protocol research & valuation (demand/supply/revenue/tokenomics)
- `event-calendar` — Economic event calendar & impact assessment
- `investment-memo` — Structured investment memo generation
- `multicoin-lens` — Multi-coin comparative analysis framework
- `data-source-handbook` — Data source reference & reliability guide
- `fin-skill-dq-guard` — Financial data quality validation guardrails
- `web-search` — Multi-provider search fallback chain (Tavily→fin-skill→Perplexity→Google CSE→SerpAPI→AnySearch→DDG)

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 0 | Foundation: Runtime + Plugin + LLM + CLI | ✅ Done |
| 1 | Knowledge entry: read-later + triage + data wall | ✅ Done |
| 1.5 | Runtime normalization + open-source prep | ✅ Done |
| 2 | Knowledge engine + Golden Cases + Schema + Trace + Memory | ✅ Done (2026-06-25) |
| 3 | RAG + Rerank + Golden Cases ×10 + LLM-Judge Auto-Eval + Dashboard | ✅ Done (2026-06-26) |
| 4a | Supervisor + 4 Agent + Message Bus | ✅ Done (2026-07-13) |
| 4b | Cron scheduler + daily brief templates | ✅ Done (2026-07-13) |
| 4c | Web UI (HTML + vanilla JS + JWT auth) | ✅ Done (2026-07-20) |
| — | SEC EDGAR LANE 1/2 (XBRL + earnings releases) | ✅ Done (2026-07-22) |
| — | Crypto Data Adapters (4 sources × 7 capabilities) | ✅ Done (2026-07-23) |
| — | Provenance System (P0-c + P1 derivation chain) | ✅ Done (2026-07-24) |
| — | Pre-launch baseline (n=24, 0% failed, 21.6% hallucination) | ✅ Done (2026-07-29) |
| **Beta** | **Online launch: cagentos.com — invite-only beta** | **✅ Live (2026-08-07)** |
| — | Provenance UI: data cards + traced/untraced markers + derived chain expansion + media tier + variant matching | ✅ Done |
| — | Native Playwright on Linux (circuit breaker + concurrency limit + UTF-8 fix) | ✅ Done |
| — | write.file enabled in HTTP server (knowledge persistence) | ✅ Done |
| — | Frontend: conversation polling, force re-render, tool status colors, popover persistence, global icons, logo | ✅ Done |
| 4d | Langfuse trace visualization | Planned |
| 4e | Evaluation regression CI suite | Planned |
| 5 | Self-improving flywheel (SFT/DPO) | Future |

## Pre-launch baseline (2026-07-29)

| Metric | Value | Notes |
|--------|-------|-------|
| Failed rate | 0/24 | Wall-clock 240s fallback, zero empty output |
| Answered rate | 20/24 | 4 runs hit iteration limit but still returned partial results |
| Hallucination rate | 21.6% (355/1643) | Excludes content-processing cases (case_001/011) |
| Transient failures | 12/14 cases | yfinance rate-limiting (circuit breaker + akshare fallback active) |
| Reliability chain | ✅ Closed | Lock TTL → wall-clock → circuit breaker → akshare degradation → never empty |

## Design decisions

**Why Event Sourcing instead of a messages table?**
Every state change is an immutable `JournalEntry`. The `TranscriptReplayer` rebuilds the LLM transcript from events on each turn. Benefits: replayable debugging, natural trace, crash recovery.

**Why a ToolGuard instead of trusting the LLM?**
LLMs hallucinate tool names. The guard enforces a per-agent allow-list. If the LLM returns a tool name not in the list, the call is rejected before reaching the dispatcher.

**Why a Data Integrity Wall?**
Real case: NVDA Forward PE from yfinance = 35.2, from a second source = 18.5 — 47% discrepancy. The wall fetches from multiple sources in parallel, flags variance >5%, and uses 2/3 consensus. Now augmented with 10 data sources including FRED, EDGAR, and crypto on-chain data.

**Why a Provenance System?**
Financial analysis lives or dies by the accuracy of its numbers. The provenance system registers every tool output at the field level, then checks every number in the LLM's final answer against the registered facts (3-pass: exact → absolute difference → verbatim string). Numbers that don't match get flagged as hallucinations. The P1 derivation chain even validates computed values (e.g., "revenue growth 23.2%" must equal `(Q4 - Q3) / Q3` within the registered facts). Frozen baselines verify **0% hallucination on XPEV Q4 2025** across 3 runs.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python ≥ 3.11 |
| Framework | FastAPI, Pydantic v2 |
| Database | SQLite (aiosqlite + WAL) — 3 databases: conversations, memory, trace |
| LLM | DeepSeek V4 Pro (default), 7 others |
| SEC filings | EDGAR companyfacts XBRL + 6-K/8-K earnings releases |
| Macro data | FRED API (21 series) + 金十 MCP (quotes/calendar/flash) |
| Stock data | yfinance + akshare (A-shares, HK stocks, US indices, China futures) |
| Crypto on-chain | Coin Metrics (MVRV/MVRV-Z) + DeFiLlama (TVL/stablecoins/revenue) |
| Crypto derivatives | Binance Futures (funding/OI/long-short) + Fear&Greed Index |
| Crypto news | PANews (7 capabilities) |
| Provenance | FactRegistry + Normalizer + 3-pass Checker + Gate + AST-validated derivation chain |
| Multi-agent | Self-built Supervisor (asyncio.gather parallel + serial pipeline) |
| Scheduling | CronAgent (FastAPI lifespan, daily 8:00 AM trigger) |
| MCP | Anthropic official `mcp` SDK |
| Browser fetch | Playwright + Readability.js + Stealth anti-bot + circuit breaker + UTF-8 encoding fix |
| RAG | Qwen3-Embedding-8B (1024-dim) + Qwen3-Reranker-8B + NumPy + 6 chunking schemes |
| Evaluation | Golden Cases ×14 + 25-criterion LLM-Judge auto-scoring + Dashboard |
| CLI | argparse-based REPL |
| HTTP | FastAPI + SSE streaming + JWT auth |
| Web UI | HTML + vanilla JS (chat / brief / knowledge browser) |

## License

[MIT](LICENSE) — Copyright (c) 2026 Madao03

---

*This project is a personal learning exercise in building agent systems from first principles. It is not affiliated with, derived from, or endorsed by any employer or organization.*
