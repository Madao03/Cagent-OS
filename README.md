# CagentOS

> English | [中文](README.zh-CN.md)
>
> **Status: Work in Progress (Phase 1.5)**
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
  Plugins: financial · web · read · write · skills · bash
        ↑
  Cross-cutting:
    Ⓐ Memory (hot ≤500 chars in prompt / cold in SQLite, 3 tables)
    Ⓑ Observability (event stream = trace, no separate logging)
    Ⓒ Data Integrity Wall (multi-source fetch → variance check → cross-validate)
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
- **8 LLM providers**: OpenRouter, DeepSeek, OpenAI, Anthropic, Groq, SiliconFlow, Together, Custom
- **MCP Client**: Multi-transport session manager (Anthropic official SDK)
- **Memory system**: Hot memory (≤500 chars in system prompt) + Cold memory (SQLite, 3 tables: user_facts / investment_theses / contradiction_log)
- **Data Integrity Wall**: Multi-source fetch → variance detection (>5% alert) → cross-validation → VerifiedMetric
- **CLI + HTTP dual entry**: REPL for local, FastAPI + SSE for web

## What's NOT included (yet)

- Multi-agent orchestration (Phase 2+, schemas defined but not wired)
- Web UI (Phase 4)
- Evaluation suite / Golden Cases (Phase 2-3)
- Self-improving flywheel / model fine-tuning (Phase 5)
- Unit tests (work in progress)

## Skills

8 investment research skills are included as `.md` templates loaded dynamically by the SkillsPlugin:

- `us-stock-analysis` — Three-tier analysis (normal / abnormal / black-box) + cyclical trap detection
- `macro-analysis` — Macro → risk-asset transmission
- `crypto-analysis` — Crypto three-tier analysis + cycle positioning
- `read-later` — L1/L2/L3 progressive disclosure for URL archiving
- `content-triage` — Five-dimension scoring (A/B/C classification) + append-only ledger
- `crypto-stock-analysis` — MSTR/COIN/miners mNAV + STRC flywheel
- `tech-sector-bridge` — Macro → tech sector transmission matrix
- `crypto-funds-flow-analysis` — Stablecoins / CEX / TVL / leverage

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 0 | Foundation: Runtime + Plugin + LLM + CLI | ✅ Done |
| 1 | Knowledge entry: read-later + triage + data wall | ✅ Done |
| 1.5 | Runtime normalization + open-source prep | ✅ Done |
| 2 | Knowledge engine + Golden Cases + memory contradiction detection | 🔜 Next |
| 3 | Semantic retrieval (RAG) + evaluation suite (DeepEval) | Planned |
| 4 | Multi-agent DAG + Web UI + Langfuse trace | Planned |
| 5 | Self-improving flywheel (SFT/DPO) | Future |

## Design decisions

**Why Event Sourcing instead of a messages table?**
Every state change (user input, tool call, tool result, assistant reply) is an immutable `JournalEntry`. The `TranscriptReplayer` rebuilds the LLM transcript from events on each turn. Benefits: replayable debugging, natural trace, crash recovery.

**Why a ToolGuard instead of trusting the LLM?**
LLMs hallucinate tool names. The guard enforces a per-agent allow-list. If the LLM returns a tool name not in the list, the call is rejected before it reaches the dispatcher — no silent mis-routing.

**Why a Data Integrity Wall?**
Real case: NVDA Forward PE from yfinance = 35.2, from a second source = 18.5 — a 47% discrepancy caused by different data vendors. The wall fetches from multiple sources in parallel, flags variance >5%, and uses 2/3 consensus to pick the trusted value.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python ≥ 3.11 |
| Framework | FastAPI, Pydantic v2 |
| Database | SQLite (aiosqlite + WAL) |
| LLM | DeepSeek V4 Pro (default), 7 others supported |
| MCP | Anthropic official `mcp` SDK |
| CLI | argparse-based REPL |
| HTTP | FastAPI + SSE streaming |
| Testing | pytest (WIP) |

## License

[MIT](LICENSE) — Copyright (c) 2026 Madao03

---

*This project is a personal learning exercise in building agent systems from first principles. It is not affiliated with, derived from, or endorsed by any employer or organization.*
