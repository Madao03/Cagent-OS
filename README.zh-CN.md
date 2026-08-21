# CagentOS

> **状态:Beta 上线 ✅ — cagentos.com 运行中 — 16 个技能 · 42+ 个能力 · 10 个数据源 · 多 Agent + Cron + Web UI + RAG + 数字溯源 + BYOK + 自动评测**
> 一个从零搭建的金融投研 Agent 操作系统 —— 不是 LangChain 包装器。
>
> [English](README.md) | 中文

CagentOS 是一个用 Python 构建金融投研 AI Agent 的框架。核心实现了 ReAct 循环 + 事件溯源的运行时,围绕它构建了插件化工具系统、跨会话记忆、一个追溯每个数字到源头的数字溯源层、以及一个专门为金融数据设计的数据完整性防线。

## 为什么造这个轮子

LangChain 太抽象,LangGraph 的状态机对大多数 Agent 场景过度设计,AutoGen 偏多多智能体对话。它们都没有数据完整性防线 —— 而在金融投研场景里,一个 Forward PE 偏差 47% 会静默腐蚀所有下游结论。

CagentOS 用一个最小化、可读、能从头到尾理解的运行时填补这个空白,加上一个在数据到达 LLM 之前就拦截坏数据的数据管道,以及一个确保**核心金融数字零幻觉**的数字溯源系统(已通过冻结基线验证)。

## 架构

```
CLI / HTTP API / Web UI
     ↓
AgentRuntime (ReAct 循环 + 事件溯源)
  ├── PromptBuilder          (system prompt 组装 + 派生计算溯源)
  ├── ModelRouter → LLM      (10 个 provider,按成本分层路由 + BYOK 用户自带 key)
  ├── ToolGuard              (白名单授权)
  ├── ToolDispatcher         (插件化工具执行)
  └── TranscriptReplayer     (事件流 → LLM transcript)
        ↑
  EventStore (SQLite, WAL 模式)
        ↑
  Plugins: financial · crypto · web · read · write · skills · memory · panews
        ↑
  数字溯源层 (provenance/)
  ├── FactRegistry           (字段级事实注册 + 精度传播)
  ├── Normalizer             (中文量级/货币/百分比归一化)
  ├── Checker (3-pass)       (精确 → abs → verbatim 匹配)
  └── Gate                   (路由感知反馈 + best-attempt + 派生提示分叉)
  ────────────────────────────────────────
  横切关注点:
    Ⓐ 记忆 (热记忆 ≤500 字注入 / 冷记忆 SQLite 三表 / LLM 矛盾检测)
    Ⓑ 可观测性 (TraceWriter + TraceReader 查询API / DICA 四维标注)
    Ⓒ 数据防线 (10 个数据源 / 方差检测 >5% / 熔断器 + 降级链)
    Ⓓ 评测 (Golden Cases ×14 + 25-criterion LLM-Judge + 上线前基线)
  ────────────────────────────────────────
  多 Agent 层 (阶段 4a/4b):
    Supervisor (自研编排器)
      ├── DataCollector (并行) — RAG + FRED + web 搜索
      ├── Researcher   (并行) — 全 Skill 套件,可注入 AgentRuntime
      ├── Red-Team     (串行) — 启发式对抗检查
      └── Editor       (串行) — 决策摘要压缩
    CronAgent (定时) — 加密日报 + 宏观周报模板
```

### 核心机制

| 机制 | 来源 | 实现 |
|------|------|------|
| ReAct 循环 | Yao et al., 2022 | `AgentRuntime.run()` — 墙钟 240s + 迭代上限 + 优雅降级(绝不空白输出) |
| 事件溯源 | Fowler, 2005 | `JournalEntry` → `EventStore` → `TranscriptReplayer.replay()` |
| Tool/Function Calling | OpenAI, 2023 | `ToolRegistry` + `ToolSchema` (JSON Schema) |
| 访问控制 | — | `ToolGuard` (白名单) + `ArgumentChecker` (Schema 校验) |
| MCP | Anthropic, 2024 | `MCPSessionManager` (官方 `mcp` SDK) |
| 数字溯源 | — | `FactRegistry` → `Checker` → `Gate` — 每个数字可追溯到源头 |

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

# 或启动 Web UI + HTTP API
uvicorn cagent_os.interfaces.http.app:create_app --factory --host 0.0.0.0 --port 8000
```

## 数据源 (10 个)

| 数据源 | 覆盖范围 | 接入方式 |
|--------|----------|----------|
| **SEC EDGAR** | 10-K/20-F XBRL 结构化数据 + 6-K/8-K 业绩新闻稿 + Guidance | `EdgarAdapter` (LANE 1) + `EarningsReleaseExtractor` (LANE 2) |
| **FRED** | 21 个宏观系列 (ONRRP/TGA/储备金/国债收益率/就业/通胀/M1M2) | `FredAdapter` |
| **yfinance** | 美股估值 (PE/PB/ROE) + 财报 + 政策新闻 | `YFinanceAdapter` (带熔断器) |
| **akshare** | A股 + 港股 + 国内期货 (5交易所 × 82品种) | `AkshareStockAdapter` + `AkshareFuturesAdapter` (Sina 源) |
| **金十 MCP** | 实时行情 + 财经日历 + 快讯 | MCP streamable-http, Bearer token |
| **PANews** | 加密资讯 (7能力: search/briefing/trending/article/polymarket/hooks/events) | `PanewsPlugin` (HTTP API) |
| **DeFiLlama** | TVL / 稳定币 / 协议收入 / DEX量 / 收益池 | `DefiLlamaAdapter` (免费, 无key) |
| **Coin Metrics** | 链上基本面 (MVRV / MVRV-Z, BTC/ETH) | `CoinMetricsAdapter` (Community tier) |
| **Binance Futures** | 资金费率 / OI / 多空比 | `BinanceDerivativesAdapter` (免费) |
| **恐贪指数** | 加密情绪指数 (0-100) | `FearGreedAdapter` (alternative.me, 免费) |

## 包含什么

- **AgentRuntime**:ReAct 循环 + 墙钟预算 (240s) + 迭代上限 + 优雅降级 —— 绝不返回空白输出
- **数字溯源系统**:`FactRegistry` (字段级事实注册) + `Normalizer` + `Checker` (3-pass: 精确→abs→verbatim) + `Gate` (路由感知反馈) + P1 派生链 (agent 显式声明 parents, AST 安全求值验证公式, 三条继承规则)
- **SEC EDGAR** (LANE 1+2):companyfacts XBRL 结构化数据 + 6-K/8-K 业绩新闻稿抽取 + 离线物化缓存 (362x 加速)
- **Crypto 数据适配器** (4源 × 7能力):DeFiLlama + Coin Metrics + Binance + 恐贪指数 —— 全免费无 key
- **ToolRegistry + ToolGuard + ArgumentChecker**:插件化工具 + JSON Schema 校验 + 白名单授权
- **EventStore**:SQLite 事件溯源,WAL 模式支持并发读
- **TraceReader**:对话历史查询 API (list/summary/timeline/count) + DICA 四维标注
- **10 个 LLM provider**:OpenRouter / DeepSeek / OpenAI / Anthropic / Groq / SiliconFlow / Together + 智谱 GLM / 月之暗面 Kimi / 通义千问 Qwen (均 OpenAI 兼容) + Custom
- **BYOK 用户自带 key**:Fernet 加密 per-user key 存储 + `BackendRegistry` (LRU 缓存) + `FallbackBackend` (用户 key 失败 → 透明回落平台 key, model 自动重定向) + 成本归因 (`billed_to`: 用户 key 调用平台成本记 0 且不占配额) + 日志密钥打码 (sk-xxx/Bearer 掩码)
- **微信公众号抓取 (三级降级)**:微信内置浏览器 UA 直抓 (~1s, 零凭据, 提取标题/公众号/作者/发布时间/全文 — 海外 IP 实测可用) → Jina 云渲染 → Playwright
- **落地页 + demo 对话**:`/` 公开展示页 (中英双语) + 无需登录的 demo 对话框 (IP 限流 3 次/天, SSE 流式) —— 完整产品迁移至 `/chat`
- **MCP Client**:多传输协议 session 管理器(Anthropic 官方 SDK)
- **记忆系统**:热记忆(≤500 字注入 system prompt)+ 冷记忆(SQLite 三表)+ **LLM 矛盾检测**
- **数据防线**:10 源 → 方差检测(>5% 告警)→ 交叉验证 → 熔断器 + akshare 价格降级
- **通用浏览器抓取**:Playwright + Readability.js + Stealth 反反爬,CDN 保护站点 + 微信公众号文章直接可读
- **RAG 管线**:Qwen3-Embedding-8B (1024 维) + 6 种分块策略 + Reranker (cos 0.79→0.999) + NumPy 向量库
- **Skill Schema**:核心 skill 的 Pydantic v2 I/O Schema + State 三层分离 + 权限标签矩阵
- **Golden Cases**:14 个评测基准 (含"数据不可得"防幻觉 case)
- **自动评测**:25 条 criterion LLM-Judge + JSON 结果存储 + 历史对比 + 仪表板
- **CLI + HTTP 双入口**:REPL 用于本地,FastAPI + SSE 用于 web
- **Web UI** (阶段 4c):HTML + vanilla JS 三合一页面 (对话面板/每日简报/知识库浏览) + JWT auth + 静态资源托管
- **多 Agent 编排**(阶段 4a):自研 Supervisor 协调 4 个 Agent,Pydantic 消息总线,并行+串行流水线,意图路由
- **定时调度器**(阶段 4b):CronAgent + 预配置报告模板,接入 FastAPI lifespan
- **保障链**:锁泄漏 TTL 自愈 (5min) → 墙钟兜底 (240s) → yfinance 熔断 (连续失败3次→冷却300s) → akshare 价格降级 → 绝不空白输出

## 不包含什么(暂未实现)

- Langfuse 全链路可视化(阶段 4d)
- 评测 CI/CD 回归套件(阶段 4e)
- 自进化飞轮 / 模型微调(阶段 5)

## Skills

包含 **16 个** 投研技能,以 `.md` 模板形式由 SkillsPlugin 动态加载:

**核心研究技能 (9 个):**
- `us-stock-analysis` — 美股三层分析(常态/非常态/黑箱)+ 周期股陷阱检测(5信号)
- `macro-analysis` — **重写** 时间周期×指标权重 + PMI 子项拆解 + CPI-PPI 剪刀差 + 就业结构
- `crypto-analysis` — Crypto 三层分析 + 周期定位(MVRV-Z / 恐贪 / 资金费率)
- `read-later` — L1/L2/L3 渐进式披露 + Obsidian 图片本地化
- `content-triage` — 五维锚点评分(A/B/C 分诊)+ append-only 台账 (29 条积累)
- `content-assetize` — A 类文章→事实/观点/框架 三类结构化资产
- `crypto-stock-analysis` — MSTR/COIN/矿企 mNAV + STRC 飞轮
- `tech-sector-bridge` — 宏观 → 科技板块传导矩阵
- `crypto-funds-flow-analysis` — 稳定币 / CEX / TVL / 杠杆资金面

**扩展技能 (7 个):**
- `defi-analysis` — DeFi 协议研究与估值(需求/供给/收入/代币经济四维拆解)
- `event-calendar` — 经济事件日历与影响评估
- `investment-memo` — 结构化投资备忘录生成
- `multicoin-lens` — 多币种对比分析框架
- `data-source-handbook` — 数据源参考与可靠性指南
- `fin-skill-dq-guard` — 金融数据质量校验护栏
- `web-search` — 多 provider 搜索降级链 (Tavily→fin-skill→Perplexity→Google CSE→SerpAPI→AnySearch→DDG)

## 路线图

| 阶段 | 重点 | 状态 |
|------|------|------|
| 0 | 地基期:Runtime + Plugin + LLM + CLI | ✅ 完成 |
| 1 | 知识入口:read-later + 分诊 + 数据防线 | ✅ 完成 |
| 1.5 | Runtime 规范化 + 开源准备 | ✅ 完成 |
| 2 | 知识引擎 + Golden Cases + Schema + Trace + 矛盾检测 | ✅ 完成 (2026-06-25) |
| 3 | RAG + Rerank + Golden Cases ×10 + LLM-Judge 自动评测 + 仪表板 | ✅ 完成 (2026-06-26) |
| 4a | Supervisor + 4 Agent + 消息总线 | ✅ 完成 (2026-07-13) |
| 4b | Cron 定时调度 + 每日简报模板 | ✅ 完成 (2026-07-13) |
| 4c | Web UI (HTML + vanilla JS + JWT auth) | ✅ 完成 (2026-07-20) |
| — | SEC EDGAR LANE 1/2 (XBRL + 业绩新闻稿) | ✅ 完成 (2026-07-22) |
| — | Crypto 数据适配器 (4源 × 7能力) | ✅ 完成 (2026-07-23) |
| — | 数字溯源系统 (P0-c + P1 派生链) | ✅ 完成 (2026-07-24) |
| — | 上线前基线 (n=24, 0% 失败, 21.6% 幻觉率) | ✅ 完成 (2026-07-29) |
| **Beta** | **上线: cagentos.com — 邀请制内测** | **✅ 上线 (2026-08-07)** |
| — | 上线周迭代: 溯源 UI + 路线图/反馈/观点库页 + React 基建 + 运维优化 | ✅ 完成 (2026-08-08) |
| — | 落地页 `/` + demo 对话框 (免登录/IP 限流/SSE) + `/chat` 迁移 | ✅ 完成 (2026-08-09) |
| — | BYOK: 加密 key 库 + BackendRegistry + 设置弹窗 + 错误回落 + 成本归因 + 日志打码 | ✅ 完成 (2026-08-20) |
| — | 新增 3 家 LLM provider (智谱/Kimi/Qwen, 共 10 家) + 模型快捷切换 | ✅ 完成 (2026-08-20) |
| — | 微信公众号三级降级抓取 (微信 UA 直抓, 海外 IP 验证) | ✅ 完成 (2026-08-20) |
| — | P0 修复: cost-tracker 从未记录 token / 多轮历史渲染 / FRED 阻塞事件循环 | ✅ 完成 (2026-08-20) |
| 4d | Langfuse 全链路可视化 | 规划中 |
| 4e | 评测 CI/CD 回归套件 | 规划中 |
| 5 | 自进化飞轮 (SFT/DPO) | 远期 |

## 上线前基线 (2026-07-29)

| 指标 | 数值 | 备注 |
|------|------|------|
| 失败率 | 0/24 | 墙钟 240s 兜底,零空白输出 |
| 回答率 | 20/24 | 4 次撞迭代上限但仍返回了部分结果 |
| 幻觉率 | 21.6% (355/1643) | 排除内容处理类 case (case_001/011) |
| 瞬态失败 | 12/14 cases | yfinance 限流(熔断器 + akshare 降级生效) |
| 保障链 | ✅ 闭环 | 锁 TTL → 墙钟 → 熔断器 → akshare 降级 → 绝不空白 |

## 设计决策

**为什么用事件溯源而不是 messages 表?**
每次状态变化(用户输入、工具调用、工具结果、Agent 回复)都是一条不可变的 `JournalEntry`。`TranscriptReplayer` 每轮从事件重建 LLM transcript。好处:可回放调试、天然 trace、崩溃后可恢复。

**为什么有 ToolGuard 而不是信任 LLM?**
LLM 会幻觉工具名。Guard 强制执行 per-agent 白名单。如果 LLM 返回了不在白名单里的工具名,调用在到达 dispatcher 之前就被拒绝 —— 不会静默误路由。

**为什么有数据防线?**
真实案例:NVDA Forward PE,yfinance 返回 35.2,第二个数据源返回 18.5 —— 47% 的差异。数据防线并行从多源采集,标记 >5% 的方差,用 2/3 共识决策选出可信值。现已扩展到 10 个数据源,包括 FRED、EDGAR 和加密链上数据。

**为什么有数字溯源系统?**
金融分析成也数字败也数字。溯源系统将每个工具输出注册到字段级事实库,然后检查 LLM 最终回答中的每个数字是否与注册事实匹配(三趟:精确→绝对差→原文字符串)。不匹配的数字被标记为幻觉。P1 派生链甚至验证计算值(如"营收增长 23.2%"必须等于 `(Q4 - Q3) / Q3`,且 Q4/Q3 都在事实库中)。冻结基线验证了 **XPEV Q4 2025 的 0% 幻觉率**(三跑全通过)。

## 技术栈

| 层 | 技术 |
|---|------|
| 语言 | Python ≥ 3.11 |
| 框架 | FastAPI, Pydantic v2 |
| 数据库 | SQLite (aiosqlite + WAL) — 三库:conversations / memory / trace |
| LLM | DeepSeek V4 Pro(平台默认), 另有 9 家 —— 含智谱 GLM / Kimi / Qwen |
| SEC 财报 | EDGAR companyfacts XBRL + 6-K/8-K 业绩新闻稿 |
| 宏观数据 | FRED API (21 系列) + 金十 MCP (行情/日历/快讯) |
| 股票数据 | yfinance + akshare (A股 / 港股 / 美股指数 / 国内期货) |
| 链上数据 | Coin Metrics (MVRV/MVRV-Z) + DeFiLlama (TVL/稳定币/收入) |
| 衍生品 | Binance Futures (资金费率/OI/多空) + 恐贪指数 |
| 加密资讯 | PANews (7 个能力) |
| 数字溯源 | FactRegistry + Normalizer + 3-pass Checker + Gate + AST 派生链 |
| 多 Agent | 自研 Supervisor (asyncio.gather 并行 + 串行流水线) |
| 定时调度 | CronAgent (FastAPI lifespan,每天 8:00 触发) |
| MCP | Anthropic 官方 `mcp` SDK |
| 浏览器抓取 | Playwright + Readability.js + Stealth 反反爬 + Jina 降级 + 常驻实例复用 |
| 微信抓取 | 微信内置浏览器 UA 直抓 (js_content 解析) + Jina + Playwright 三级降级 |
| RAG | Qwen3-Embedding-8B (1024-dim) + Qwen3-Reranker-8B + 6 种分块 |
| 评测 | Golden Cases × 14 + 25-criterion LLM-Judge + 仪表板 |
| CLI | argparse REPL |
| HTTP | FastAPI + SSE 流式 + JWT auth |
| Web UI | HTML + vanilla JS (对话 / 简报 / 知识库) + 落地页 + demo 对话框 |
| React 前端 | Vite + React 18 + TypeScript + React Router (观点库页, `/app/*` 路由) |

## License

[MIT](LICENSE) — Copyright (c) 2026 Madao03

---

*本项目是从第一性原理构建 Agent 系统的个人学习实践。不附属于、不派生自、也不受任何雇主或组织认可。*
