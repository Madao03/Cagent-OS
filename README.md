# CagentOS

> English | [中文](README.zh-CN.md)
>
> **Status: Phase 4a/4b Complete ✅ — 15 skills · 28+ tools · 5 data sources · Multi-agent + Cron + RAG + Auto-Eval**
> A self-contained financial research agent operating system built from scratch — not a LangChain wrapper.

CagentOS is a Python framework for building AI agents that perform financial research. It implements a ReAct loop with event sourcing at its core, surrounded by a plugin-based tool system, cross-session memory, and a data integrity layer designed specifically for financial data.

## Why this exists

LangChain is too abstract. LangGraph's state machine is overkill for most agent workflows. AutoGen focuses on multi-agent dialog. None of them have a data integrity wall — in financial research, a Forward PE that's 47% off silently corrupts every downstream conclusion.

CagentOS fills this gap with a minimal, readable runtime that you can understand end-to-end, plus a data pipeline that catches bad data before it reaches the LLM.

## Architecture

```
CLI / HTTP API
     ↓
AgentRuntime (ReAct loop + Event Sourcing)
  ├── PromptBuilder          (system prompt assembly)
  ├── ModelRouter → LLM      (8 providers, cost-tiered routing)
  ├── ToolGuard              (allow-list authorization)
  ├── ToolDispatcher         (plugin-based tool execution)
  └── TranscriptReplayer     (event stream → LLM transcript)
        ↑
  EventStore (SQLite, WAL mode)
        ↑
  Plugins: financial · web · read · write · skills · bash · panews
        ↑
  Cross-cutting:
    Ⓐ Memory (hot ≤500 chars / cold SQLite 3-tables / LLM contradiction detection)
    Ⓑ Observability (TraceWriter + TraceReader query API / DICA 4-dimension tagging)
    Ⓒ Data Integrity Wall (FRED + Jin10 + yfinance + akshare + PANews 5-source / variance >5% alert)
    Ⓓ Eval (Golden Cases ×13 + 25-criterion LLM-Judge)
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
| ReAct loop | Yao et al., 2022 | `AgentRuntime.run()` — 12-iteration max, failure streak → graceful degrade |
| Event Sourcing | Fowler, 2005 | `JournalEntry` → `EventStore` → `TranscriptReplayer.replay()` |
| Tool/Function Calling | OpenAI, 2023 | `ToolRegistry` + `ToolSchema` (JSON Schema) |
| Access control | — | `ToolGuard` (allow-list) + `ArgumentChecker` (schema validation) |
| MCP | Anthropic, 2024 | `MCPSessionManager` (official `mcp` SDK) |

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
```

## What's included

- **AgentRuntime**: ReAct loop with iteration limits and graceful failure degradation
- **ToolRegistry + ToolGuard + ArgumentChecker**: plugin-based tools with JSON Schema validation and allow-list authorization
- **EventStore**: SQLite-backed event sourcing with WAL mode for concurrent reads
- **TraceReader**: Conversation history query API (list/summary/timeline/count) + DICA 4-dimension tagging
- **8 LLM providers**: OpenRouter, DeepSeek, OpenAI, Anthropic, Groq, SiliconFlow, Together, Custom
- **MCP Client**: Multi-transport session manager (Anthropic official SDK)
- **Memory system**: Hot memory (≤500 chars in system prompt) + Cold memory (SQLite 3 tables) + **LLM contradiction detection**
- **Data Integrity Wall**: FRED + Jin10 MCP + yfinance + akshare + PANews → variance detection (>5% alert) → cross-validation → VerifiedMetric
- **Browser fetch**: Playwright + Readability.js + Stealth anti-bot — fetches CDN-protected institutional research sites
- **Skill Schemas**: Pydantic v2 I/O schemas for core skills + State 3-layer separation + permission matrix
- **Golden Cases**: 13 evaluation benchmarks covering triage/macro/NVDA/crypto/crypto-stock/cross-skill/RAG/degradation/discipline/opposing-view/product-decomposition/anti-false-precision
- **RAG Pipeline**: Qwen3-Embedding-8B + 6 chunking schemes + Reranker (cos 0.79→0.999) + NumPy vector store
- **Auto-Evaluation**: 25 criterion LLM-Judge + JSON result storage + history comparison + dashboard
- **CLI + HTTP dual entry**: REPL for local, FastAPI + SSE for web
- **Multi-agent orchestration** (Phase 4a): Self-built Supervisor coordinating 4 agents (DataCollector → Researcher → Red-Team → Editor) with Pydantic message bus, parallel + serial pipeline, intent-based routing
- **Cron scheduler** (Phase 4b): CronAgent with pre-configured report templates (crypto daily + macro weekly), integrated into FastAPI lifespan (daily 8:00 AM trigger)
- **A-share / futures data**: akshare adapters for China markets (Sina source, 5 exchanges × 82 futures products)
- **Crypto news**: PANews plugin (7 capabilities — search/briefing/trending/article/polymarket/hooks/events)

## What's NOT included (yet)

- Web UI (Phase 4c — React + Tailwind, static prototype exists)
- Langfuse trace visualization (Phase 4d)
- Evaluation regression CI suite (Phase 4e)
- Self-improving flywheel / model fine-tuning (Phase 5)

## Skills

**15** investment research skills included as `.md` templates loaded dynamically:

**Core research skills (9):**
- `us-stock-analysis` — Three-tier analysis (normal/abnormal/black-box) + cyclical trap detection
- `macro-analysis` — **Rewritten** time-horizon × indicator-weight framework + PMI sub-index + CPI-PPI spread
- `crypto-analysis` — Crypto three-tier analysis + cycle positioning
- `read-later` — L1/L2/L3 progressive disclosure + Obsidian image localization
- `content-triage` — Five-dimension scoring (A/B/C) + append-only ledger (29 entries accumulated)
- `content-assetize` — A-class articles → facts/opinions/frameworks structured assets
- `crypto-stock-analysis` — MSTR/COIN/miners mNAV + STRC flywheel
- `tech-sector-bridge` — Macro → tech sector transmission matrix
- `crypto-funds-flow-analysis` — Stablecoins / CEX / TVL / leverage

**Extended skills (6):**
- `defi-analysis` — DeFi protocol research & valuation (demand/supply/revenue/tokenomics)
- `event-calendar` — Economic event calendar & impact assessment
- `investment-memo` — Structured investment memo generation
- `multicoin-lens` — Multi-coin comparative analysis framework
- `data-source-handbook` — Data source reference & reliability guide
- `fin-skill-dq-guard` — Financial data quality validation guardrails

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
| 4c | Web UI (React + Tailwind) | 🔜 Next |
| 4d | Langfuse trace visualization | Planned |
| 4e | Evaluation regression CI suite | Planned |
| 5 | Self-improving flywheel (SFT/DPO) | Future |

## Design decisions

**Why Event Sourcing instead of a messages table?**
Every state change is an immutable `JournalEntry`. The `TranscriptReplayer` rebuilds the LLM transcript from events on each turn. Benefits: replayable debugging, natural trace, crash recovery.

**Why a ToolGuard instead of trusting the LLM?**
LLMs hallucinate tool names. The guard enforces a per-agent allow-list. If the LLM returns a tool name not in the list, the call is rejected before reaching the dispatcher.

**Why a Data Integrity Wall?**
Real case: NVDA Forward PE from yfinance = 35.2, from a second source = 18.5 — 47% discrepancy. The wall fetches from multiple sources in parallel, flags variance >5%, and uses 2/3 consensus. Now augmented with **FRED** (21 series) and **Jin10 MCP** as additional data sources.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python ≥ 3.11 |
| Framework | FastAPI, Pydantic v2 |
| Database | SQLite (aiosqlite + WAL) |
| LLM | DeepSeek V4 Pro (default), 7 others |
| Macro data | FRED API (44 series) + Jin10 MCP (quotes/calendar/flash) |
| Stock data | yfinance + akshare (A-shares, HK stocks, US indices) |
| Futures data | akshare (DCE/CZCE/SHFE/CFFEX/GFEX × 82 products) |
| Crypto news | PANews (7 capabilities — search/briefing/trending/article/polymarket/hooks/events) |
| Multi-agent | Self-built Supervisor (asyncio.gather parallel + serial pipeline) |
| Scheduling | CronAgent (FastAPI lifespan, daily 8:00 AM trigger) |
| MCP | Anthropic official `mcp` SDK |
| Browser fetch | Playwright + Readability.js (WSL bridge) |
| RAG | Qwen3-Embedding-8B (1024-dim) + Qwen3-Reranker-8B + NumPy + 6 chunking schemes |
| Evaluation | Golden Cases × 13 + 25-criterion LLM-Judge auto-scoring + Dashboard |
| CLI | argparse-based REPL |
| HTTP | FastAPI + SSE streaming |

## License

[MIT](LICENSE) — Copyright (c) 2026 Madao03

---

*This project is a personal learning exercise in building agent systems from first principles. It is not affiliated with, derived from, or endorsed by any employer or organization.*
