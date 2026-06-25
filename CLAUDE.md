# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 项目概述

CagentOS — 面向金融投研场景的 Agent 操作系统。底层 Runtime 基于 ReAct 循环 + Event Sourcing 模式自研,上层构建投研方法论工程化体系。

- **Python**: >=3.11, **包名**: `cagent_os` (源码在 `src/cagent_os/`)
- **数据库**: SQLite (`aiosqlite` + WAL 模式)
- **LLM**: DeepSeek V4 Pro (默认),8 个 provider 框架就绪
- **当前阶段**: **阶段 2 完成 ✅** (知识引擎 + 横切奠基,2026-06-25)

## 常用命令

```bash
pip install -e ".[dev]"
cagent-os                            # CLI REPL
cagent-os chat "分析 NVDA 估值"      # 一次性对话
uvicorn cagent_os.interfaces.http.app:create_app --factory --reload
pytest -v
```

## 核心架构 (七层 + 四横切)

```
CLI / HTTP API
     ↓
AgentRuntime (agents/run_engine.py)         ← ReAct 循环 + Event Sourcing
  ├── PromptBuilder                           ← system prompt 组装
  ├── ModelRouter → LLM                       ← 8 provider 路由
  ├── ToolGuard → ToolDispatcher              ← 白名单 + 插件执行
  └── TranscriptReplayer                      ← 事件流 → transcript
        ↑
  EventStore (SQLite, WAL)
        ↑
  Plugins: financial · web · read · write · skills · bash
```

**横切关注点**:
- Ⓐ Memory: 热记忆(≤500 字注入) + 冷记忆(SQLite 三表) + **LLM 矛盾检测**
- Ⓑ Observe: TraceWriter + **TraceReader** (查询API) + DICA 四维标注
- Ⓒ DataWall: **FRED (21 系列) + 金十 MCP + yfinance** 三源 → 方差检测 >5% → 交叉验证
- Ⓓ Eval: **Golden Cases × 3** + 六维 Rubric 手动评分

## 命名约定

| 层 | 核心类型 | 文件 |
|:---|:--------|:-----|
| Runtime | `AgentRuntime` | `agents/run_engine.py` |
| Tools | `ToolRegistry` / `ToolDispatcher` / `ToolGuard` | `plugins/` |
| Schema | `MacroAnalysisOutput` / `ContentTriageOutput` 等 6 个 Skill Schema | `schemas/skill_io.py` |
| State | `SessionStateSchema` / `AgentStateSchema` / `ToolContextSchema` | `schemas/state.py` |
| Permissions | `AgentRole` (researcher/risk_auditor/editor) + `PERMISSION_MATRIX` | `schemas/permissions.py` |
| Memory | `MemoryAPI` / `ContradictionDetector` / `SqliteMemoryStore` | `memory/` |
| Trace | `TraceWriter` / `TraceReader` (list/summary/timeline/count) | `observability/` |
| Data | `DataLayer` / `FredAdapter` / `YFinanceAdapter` / `FinSkillAdapter` | `data_layer/` |
| LLM | `ChatMessage` / `ModelRequest` / `ModelResponse` | `llm/protocol.py` |
| Events | `JournalEntry` / `TranscriptView` | `conversations/` |

## 数据源 (3 个)

| 源 | 用途 | 接入方式 |
|:---|:-----|:-----|
| **FRED** | 21 个宏观系列 (ONRRP/TGA/储备金/国债/就业/通胀/M1M2) | `FredAdapter` → `DataLayer` → `financial.fred` |
| **金十 MCP** | 实时行情(quote) + 财经日历(calendar) + 快讯(flash) + 资讯(news) | MCP streamable-http, Bearer token |
| **yfinance + fin-skill** | 股票估值(PE/PB/ROE) + 财报 + 政策新闻 | `DataLayer` → `financial.quote.verified` (交叉验证) |

## 技能体系 (9 个 Skill)

| Skill | 阶段 | 核心 |
|:------|:-----|:-----|
| `macro-analysis` | 0 → **1.5 重写** | 时间周期×指标权重 + PMI 子项 + CPI-PPI 剪刀差 + 就业结构 |
| `us-stock-analysis` | 0 | 三层分析(常态/非常态/黑箱) + 周期陷阱检测(5 信号) |
| `crypto-analysis` | 0 | 加密三层分析 + 周期定位(MVRV-Z/恐贪/资金费率) |
| `read-later` | 1a | L1/L2/L3 渐进式披露 + Obsidian 图片本地化 |
| `content-triage` | 1c | 五维锚点评分(A/B/C) + append-only 台账 (29 条) |
| `crypto-stock-analysis` | 1d | MSTR mNAV + STRC 飞轮 + 矿企分析 |
| `tech-sector-bridge` | 1d | 宏观→科技板块传导矩阵 |
| `crypto-funds-flow-analysis` | 1d | 稳定币/CEX/TVL/杠杆资金面 |
| `content-assetize` | **2a 新建** | A 类文章→事实/观点/框架 结构化资产 |

## 能力清单 (19 个 capability)

**Financial**: `financial.fred` · `financial.websearch` · `financial.earnings.query` · `financial.earnings.query_full` · `financial.quote.query` · `financial.quote.verified` · `financial.data.health_check` · `financial.trace.query` · `financial.memory.save_thesis` · `financial.memory.query_theses` · `financial.memory.check_contradictions` · `financial.memory.append` · `financial.memory.get_document`

**Web**: `web.fetch` (auto-fallback 到浏览器模式) · `web.fetch_weixin` (微信) · `image.describe` (多模态骨架)

**Infra**: `docs.read` · `write.file` · `Skill` (技能加载)

## 当前进度 — 阶段 2 完成 ✅

### 已就绪
- ✅ AgentRuntime + Plugin 体系 + LLM 层完整可运行
- ✅ CLI REPL + FastAPI HTTP 双入口
- ✅ SQLite 持久化: conversations / memory / trace 三库 WAL 模式
- ✅ MCP Client: fin-skill (stdio) + 金十 MCP (streamable-http, Bearer token)
- ✅ DataLayer: `FredAdapter` + `YFinanceAdapter` + `FinSkillAdapter` + `MetricCrossValidator`
- ✅ Memory: `SqliteMemoryStore` (3 表) + `ContradictionDetector` (LLM 语义比较)
- ✅ Schemas: 6 个核心 skill Pydantic I/O + State 三层 + 权限标签矩阵
- ✅ Trace: `TraceWriter` + `TraceReader` (查询 API) + DICA 四维标注
- ✅ 9 个 Skill (8 投研 + 1 资产化), macro 已重写
- ✅ 浏览器抓取: Playwright + Readability.js + Stealth 反反爬, 自动降级
- ✅ Golden Cases × 3 (triage/macro/NVDA) + 六维 Rubric + scorer.py
- ✅ 29 篇分诊积累, 分诊台账 (append-only)
- ✅ 图片多模态骨架 (`image.describe`), 等待 API key 激活

### 待实现 (阶段 3)
- RAG: Chunking + Embedding (硅基流动 Qwen3-Embedding-8B) + ChromaDB + Rerank
- 评测自动化: Golden Cases 3→10+ + DeepEval G-Eval 自动评分
- 多模态图片处理: 代码编排调用多模态 LLM 描述图表并拼回原文

## 开发注意事项

- **必须用 `aiosqlite`**, 原生 `sqlite3` 在 asyncio 中阻塞事件循环
- **MCP 用官方 SDK** (`from mcp import ClientSession`), 不要手搓 SSE/JSON-RPC
- **新 skill 全部用 Pydantic BaseModel 定义 I/O**, 禁止返回裸 `str`
- **改已有 skill 遵循 `schemas/` 规范**: 加字段必须 Optional + default, 不删除已有字段
- **Pydantic V2 脏数据**: 金融 API 返回 `null`/`"N/A"`/`"NaN"` 需 `@model_validator(mode='before')` 前置清洗
- **工具权限走 `ToolGuard`**, 不要在执行层绕过检查
- **包名是 `cagent_os`**, 源码在 `src/cagent_os/`
- **Git 身份**: `Madao03 <98048020+Madao03@users.noreply.github.com>` (匿名)
- **`.env` 不入库**: JIN10_API_KEY、FRED_API_KEY、DEEPSEEK_API_KEY 均在 `.gitignore` 中
- **知识库不入库**: `knowledge/` 在 `.gitignore` 中
