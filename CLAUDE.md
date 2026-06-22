# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 项目概述

CagentOS — 面向金融投研场景的 Agent 操作系统。底层 Runtime 基于 ReAct 循环 + Event Sourcing 模式自研,上层构建投研方法论工程化体系。

- **Python**: >=3.11
- **包名**: `cagent_os`(源码在 `src/cagent_os/`)
- **数据库**: SQLite(`aiosqlite` + WAL 模式)
- **LLM**: OpenRouter / OpenAI-compatible,通过 `ModelRouter` 路由
- **当前阶段**: 阶段 1 完成(知识入口期),底层 Runtime 规范化完成

## 常用命令

```bash
# 安装
pip install -e ".[dev]"

# CLI — REPL 交互模式
cagent-os

# CLI — 一次性对话
cagent-os chat "分析 NVDA 当前估值"

# HTTP 服务
uvicorn cagent_os.interfaces.http.app:create_app --factory --reload

# 测试
pytest -v
```

## 核心架构

项目采用 Plugin 体系 + Event Sourcing 模式:

```
CLI / HTTP API
     ↓
AgentRuntime (agents/run_engine.py)         ← 核心 ReAct 循环
  ├── PromptBuilder                           ← 组装 system prompt
  ├── ModelRouter → LLMBackend.complete()     ← LLM 调用(支持 stream)
  ├── ToolGuard                               ← 工具白名单授权
  ├── ToolDispatcher                          ← 通过 Plugin.handler() 执行工具
  └── TranscriptReplayer                      ← 事件流 → LLM transcript
        ↑
  EventStore (in-memory / SQLite)
```

**Plugin 体系**: 每个 Plugin 声明 `PluginSpec` 列表 + 提供 `handler(capability_id)`。现有 plugin: `financial`(市场数据/PE/新闻)、`web`(抓取)、`read`(文档)、`write`(文件写入)、`skills`(动态加载 SKILL.md)、`bash`(shell 执行)。

**AgentRuntime** 同时支持 `run()`(同步返回完整文本)和 `run_stream()`(逐 token 流式推送),最多 12 轮迭代,连续工具失败后自动降级。

## 命名约定(规范化后)

底层 Runtime 已完成命名规范化,使用以下命名:

| 层 | 核心类型 | 文件 |
|:---|:--------|:-----|
| Runtime | `AgentRuntime` | `agents/run_engine.py` |
| Tools | `ToolRegistry` / `ToolDispatcher` / `ToolGuard` / `ArgumentChecker` | `plugins/registry.py` / `plugins/executor.py` / `plugins/policy.py` / `plugins/validator.py` |
| Tool Types | `ToolRequest` / `ToolResult` / `ToolSpec` / `ToolTrustLevel` | `plugins/contracts.py` / `plugins/manifests.py` |
| Events | `JournalEntry` / `SessionSnapshot` / `TranscriptView` | `conversations/models.py` |
| Replayer | `TranscriptReplayer` | `conversations/projector.py` |
| Prompt | `PromptBuilder` / `BuiltPrompt` | `agents/prompt_compiler.py` |
| Profile | `AgentProfile` / `UserPersona` / `MemorySnapshot` | `agents/definition.py` / `domain/models.py` |
| LLM | `ChatMessage` / `ModelRequest` / `ModelResponse` / `ToolSchema` | `llm/protocol.py` |

## 当前进度

### 已就绪
- AgentRuntime + Plugin 体系 + LLM 层(OpenRouter/OpenAI 后端)全部可运行
- CLI REPL + FastAPI HTTP 双入口
- SQLite 持久化: `aiosqlite` + `PRAGMA journal_mode=WAL`(conversations、memory、trace 三库)
- MCP Client 层: `MCPSessionManager`(用 Anthropic 官方 `mcp` SDK)+ `MCPBridge`
- Data Layer: `DataLayer` 统一入口 + `DataSourceAdapter` ABC + `PEForwardCrossValidator`(完整实现)
- Memory: `SqliteMemoryStore`(3 表: user_facts / investment_theses / contradiction_log)
- Multi-agent Pydantic Schema: `AnalysisReport` / `RiskAuditResult` / `CounterNarrative` 已定义

### 待实现
- **P0 Skill 零实现**: `capabilities/stock/`、`crypto/`、`macro/` 只有空 `__init__.py`
- **Data Adapter 是 stub**: `YFinanceAdapter`、`FinSkillAdapter` 的 `fetch()` 返回硬编码 `{"status": "stub"}`
- **MCP 未联调**: `config/mcp_servers.json` 端口是占位符
- **零测试**: `tests/` 空

### 已有但未接入 AgentRuntime 的模块
- `mcp_client/` — session/bridge/registry 代码完整,但 CLI main() 未创建 `MCPSessionManager` 并注入
- `data_layer/` — DataLayer + CrossValidator 完整,但 CLI 和 AgentRuntime 未注入使用
- `memory/` — SqliteMemoryStore 完整,但 AgentRuntime 仍通过旧的 `memory_context` 快照方式传记忆
- `observability/` — TraceWriter 完整,但 AgentRuntime 未调用
- `state/` — SessionState/AgentState/ToolContext 定义完成,但未在 AgentRuntime 中使用
- `multi_agent/schemas.py` — Schema 已定义,阶段 2+ 使用

## 开发注意事项

- **必须用 `aiosqlite`**,原生 `sqlite3` 在 asyncio 中阻塞事件循环
- **MCP 用官方 SDK** (`from mcp import ClientSession`),不要手搓 SSE/JSON-RPC
- **新 skill 全部用 Pydantic BaseModel 定义 I/O**,禁止返回裸 `str`
- **Pydantic V2 脏数据**: 金融 API 返回 `null`/`"N/A"`/`"NaN"` 需 `@model_validator(mode='before')` 前置清洗
- **`conversation_id` 和 `principal_id` 是 AgentRuntime 所有方法的必需参数**,不要省略
- **工具权限走 `ToolGuard`**,不要在执行层绕过检查
- **包名是 `cagent_os`**,源码在 `src/cagent_os/`
- **底层 Runtime 基于业界 Agent 框架设计模式(ReAct + Event Sourcing)自研**,核心价值在投研方法论的工程化
