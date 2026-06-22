# CagentOS

> **状态:开发中 (阶段 1.5)**
> 一个从零搭建的金融投研 Agent 操作系统 —— 不是 LangChain 包装器。
>
> [English](README.md) | 中文

CagentOS 是一个用 Python 构建金融投研 AI Agent 的框架。核心实现了 ReAct 循环 + 事件溯源的运行时,围绕它构建了插件化工具系统、跨会话记忆、以及一个专门为金融数据设计的数据完整性防线。

## 为什么造这个轮子

LangChain 太抽象,LangGraph 的状态机对大多数 Agent 场景过度设计,AutoGen 偏多多智能体对话。它们都没有数据完整性防线 —— 而在金融投研场景里,一个 Forward PE 偏差 47% 会静默腐蚀所有下游结论。

CagentOS 用一个最小化、可读、能从头到尾理解的运行时填补这个空白,加上一个在数据到达 LLM 之前就拦截坏数据的数据管道。

## 架构

```
CLI / HTTP API
     ↓
AgentRuntime (ReAct 循环 + 事件溯源)
  ├── PromptBuilder          (system prompt 组装)
  ├── ModelRouter → LLM      (8 个 provider,按成本分层路由)
  ├── ToolGuard              (白名单授权)
  ├── ToolDispatcher         (插件化工具执行)
  └── TranscriptReplayer     (事件流 → LLM transcript)
        ↑
  EventStore (SQLite, WAL 模式)
        ↑
  Plugins: financial · web · read · write · skills · bash
        ↑
  横切关注点:
    Ⓐ 记忆 (热记忆 ≤500 字注入 prompt / 冷记忆 SQLite 三表)
    Ⓑ 可观测性 (事件流即 trace,无需额外日志系统)
    Ⓒ 数据防线 (多源采集 → 方差检测 → 交叉验证)
```

### 核心机制

| 机制 | 来源 | 实现 |
|------|------|------|
| ReAct 循环 | Yao et al., 2022 | `AgentRuntime.run()` — 最多 12 轮迭代,失败连续触发自动降级 |
| 事件溯源 | Fowler, 2005 | `JournalEntry` → `EventStore` → `TranscriptReplayer.replay()` |
| Tool/Function Calling | OpenAI, 2023 | `ToolRegistry` + `ToolSchema` (JSON Schema) |
| 访问控制 | — | `ToolGuard` (白名单) + `ArgumentChecker` (Schema 校验) |
| MCP | Anthropic, 2024 | `MCPSessionManager` (官方 `mcp` SDK) |

## 快速开始

```bash
# 安装
pip install -e ".[dev]"

# 配置环境
cp .env.example .env
# 编辑 .env —— 填入你的 DeepSeek API key (或 OpenRouter key)

# 一次性查询
cagent-os chat "NVDA 的 forward PE 是多少?"

# 或启动交互式 REPL
cagent-os
```

## 包含什么

- **AgentRuntime**:ReAct 循环 + 迭代上限 + 优雅失败降级
- **ToolRegistry + ToolGuard + ArgumentChecker**:插件化工具 + JSON Schema 校验 + 白名单授权
- **EventStore**:SQLite 事件溯源,WAL 模式支持并发读
- **8 个 LLM provider**:OpenRouter / DeepSeek / OpenAI / Anthropic / Groq / SiliconFlow / Together / Custom
- **MCP Client**:多传输协议 session 管理器(Anthropic 官方 SDK)
- **记忆系统**:热记忆(≤500 字注入 system prompt)+ 冷记忆(SQLite 三表:user_facts / investment_theses / contradiction_log)
- **数据防线**:多源并行采集 → 方差检测(>5% 告警)→ 交叉验证 → VerifiedMetric
- **CLI + HTTP 双入口**:REPL 用于本地,FastAPI + SSE 用于 web

## 不包含什么(暂未实现)

- 多智能体编排(阶段 2+,Schema 已定义但未接入)
- Web UI(阶段 4)
- 评测体系 / Golden Cases(阶段 2-3)
- 自进化飞轮 / 模型微调(阶段 5)
- 单元测试(进行中)

## Skills

包含 8 个投研技能,以 `.md` 模板形式由 SkillsPlugin 动态加载:

- `us-stock-analysis` — 美股三层分析(常态/非常态/黑箱)+ 周期股陷阱检测
- `macro-analysis` — 宏观 → 风险资产传导
- `crypto-analysis` — Crypto 三层分析 + 周期定位
- `read-later` — L1/L2/L3 渐进式披露,用于 URL 归档
- `content-triage` — 五维锚点评分(A/B/C 分诊)+ append-only 台账
- `crypto-stock-analysis` — MSTR/COIN/矿企 mNAV + STRC 飞轮
- `tech-sector-bridge` — 宏观 → 科技板块传导矩阵
- `crypto-funds-flow-analysis` — 稳定币 / CEX / TVL / 杠杆资金面

## 路线图

| 阶段 | 重点 | 状态 |
|------|------|------|
| 0 | 地基期:Runtime + Plugin + LLM + CLI | ✅ 完成 |
| 1 | 知识入口:read-later + 分诊 + 数据防线 | ✅ 完成 |
| 1.5 | Runtime 规范化 + 开源准备 | ✅ 完成 |
| 2 | 知识引擎 + Golden Cases + 记忆矛盾检测 | 🔜 下一步 |
| 3 | 语义检索 (RAG) + 评测体系 (DeepEval) | 规划中 |
| 4 | 多 Agent DAG + Web UI + Langfuse 全链路 | 规划中 |
| 5 | 自进化飞轮 (SFT/DPO) | 远期 |

## 设计决策

**为什么用事件溯源而不是 messages 表?**
每次状态变化(用户输入、工具调用、工具结果、Agent 回复)都是一条不可变的 `JournalEntry`。`TranscriptReplayer` 每轮从事件重建 LLM transcript。好处:可回放调试、天然 trace、崩溃后可恢复。

**为什么有 ToolGuard 而不是信任 LLM?**
LLM 会幻觉工具名。Guard 强制执行 per-agent 白名单。如果 LLM 返回了不在白名单里的工具名,调用在到达 dispatcher 之前就被拒绝 —— 不会静默误路由。

**为什么有数据防线?**
真实案例:NVDA Forward PE,yfinance 返回 35.2,fin-skill 返回 18.5 —— 47% 的差异,原因是数据供应商不同(Refinitiv vs data vendor)。数据防线并行从多源采集,标记 >5% 的方差,用 2/3 共识决策选出可信值。

## 技术栈

| 层 | 技术 |
|---|------|
| 语言 | Python ≥ 3.11 |
| 框架 | FastAPI, Pydantic v2 |
| 数据库 | SQLite (aiosqlite + WAL) |
| LLM | DeepSeek V4 Pro(默认),另有 7 个 provider |
| MCP | Anthropic 官方 `mcp` SDK |
| CLI | argparse REPL |
| HTTP | FastAPI + SSE 流式 |
| 测试 | pytest (WIP) |

## License

[MIT](LICENSE) — Copyright (c) 2026 Madao03

---

*本项目是从第一性原理构建 Agent 系统的个人学习实践。不附属于、不派生自、也不受任何雇主或组织认可。*
