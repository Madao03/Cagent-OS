# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 项目概述

CagentOS — 面向金融投研场景的 Agent 操作系统。底层 Runtime 基于 ReAct 循环 + Event Sourcing 模式自研,上层构建投研方法论工程化体系。

- **Python**: >=3.11, **包名**: `cagent_os` (源码在 `src/cagent_os/`)
- **数据库**: SQLite (`aiosqlite` + WAL 模式)
- **LLM**: DeepSeek V4 Pro (默认),8 个 provider 框架就绪
- **当前阶段**: **阶段 4a/4b + EDGAR LANE 1/2 + Crypto Data Adapters + Provenance System 完成 ✅** (2026-07-24)

## 常用命令

```bash
pip install -e ".[dev]"
cagent-os                            # CLI REPL
cagent-os chat "分析 NVDA 估值"      # 一次性对话
uvicorn cagent_os.interfaces.http.app:create_app --factory --reload
python -m cagent_os.multi_agent.cron_agent  # 手动触发 Cron 日报
python scripts/run_provenance_baseline.py   # 5 问溯源基线
python scripts/_baseline_xpev_q4_3x.py      # XPEV Q4 3x 零幻觉基线
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
  Plugins: financial · crypto · web · read · write · skills · memory · panews(unreg)
        ↑
  Provenance Layer (provenance/)               ← 数字溯源 (P0-c 已交付 ✅)
  ├── FactRegistry                             ← 工具输出 → 字段级事实注册
  ├── Normalizer                               ← 中文量级/货币/百分比归一化
  ├── Checker (3-pass)                         ← 精确→abs→verbatim 匹配
  └── Gate                                     ← 路由感知反馈 + best-attempt
────────────────────────────────────────────────
Multi-Agent Layer (multi_agent/)
  Supervisor (supervisor.py)                   ← 自研编排器,意图路由 + 并行/串行调度
    ├── DataCollector (并行)                   ← RAG + FRED + web 搜索
    ├── Researcher   (并行)                    ← 全 Skill 套件,可注入 agent_runner
    ├── Red-Team     (串行)                    ← 启发式对抗检查
    └── Editor       (串行)                    ← 决策摘要压缩
  CronAgent (cron_agent.py)                    ← 定时触发,共用 Agent 池
```

**横切关注点**:
- Ⓐ Memory: 热记忆(≤500 字注入) + 冷记忆(SQLite 三表) + **LLM 矛盾检测**
- Ⓑ Observe: TraceWriter + **TraceReader** (查询API) + DICA 四维标注
- Ⓒ DataWall: **FRED (21 系列) + EDGAR + Crypto (DeFiLlama/CoinMetrics/Binance/恐贪) + 金十 MCP + yfinance + akshare (A股+期货) + PANews** → 方差检测 >5% → 交叉验证
- Ⓓ Eval: **Golden Cases × 14** (含腾讯数据不可得防幻觉) + 25-criterion LLM-Judge 自动评分 + 仪表板

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
| Data | `DataLayer` / `FredAdapter` / `YFinanceAdapter` / `FinSkillAdapter` / `AkshareStockAdapter` / `AkshareFuturesAdapter` | `data_layer/` |
| **EDGAR** | **`EdgarAdapter` / `EarningsReleaseFinder` / `EarningsReleaseExtractor` / `EdgarReleaseStore`** | **`data_layer/adapters/edgar_adapter.py` / `data_layer/lane2/`** |
| **Crypto** | **`DefiLlamaAdapter` / `FearGreedAdapter` / `CoinMetricsAdapter` / `BinanceDerivativesAdapter` / `CryptoPlugin`** | **`data_layer/adapters/` / `plugins/crypto/`** |
| LLM | `ChatMessage` / `ModelRequest` / `ModelResponse` | `llm/protocol.py` |
| Events | `JournalEntry` / `TranscriptView` | `conversations/` |
| **Multi-Agent** | **`Supervisor` / `CronAgent` / `SupervisorConfig`** | **`multi_agent/supervisor.py` / `multi_agent/cron_agent.py`** |
| **Message Bus** | **`RawDataDump` / `AnalysisReport` / `RiskAuditResult` / `DecisionSummary`** | **`multi_agent/schemas.py`** |
| **PANews** | **`PanewsPlugin` / `PanewsClient`** | **`plugins/panews/`** |
| **RAG** | **`RAGService` / `Chunker` / `Embedder` / `Reranker` / `VectorStore`** | **`rag/`** |
| **Provenance** | **`FactRegistry` / `CheckResult` / `TracedNumber` / `Fact`** | **`provenance/`** |

## 数据源 (10 个)

| 源 | 用途 | 接入方式 |
|:---|:-----|:-----|
| **SEC EDGAR** | 年度审计财报 (10-K/20-F XBRL) + 季度业绩新闻稿 (6-K/8-K) + Guidance | `EdgarAdapter` (LANE 1) + `EarningsReleaseExtractor` (LANE 2) → `financial.edgar.facts` / `financial.edgar.release` |
| **Crypto On-chain** | MVRV / MVRV-Z / 链上基本面 (BTC/ETH) | `CoinMetricsAdapter` (Community tier, 免费) → `crypto.onchain.metrics` |
| **Crypto Derivatives** | 资金费率 / OI / 多空比 (Binance Futures) | `BinanceDerivativesAdapter` (免费, 单交易所) → `crypto.derivatives.funding` / `crypto.derivatives.oi` |
| **DeFi Data** | TVL / 稳定币 / 协议收入 / DEX量 / 收益池 | `DefiLlamaAdapter` (免费, 无 key) → `crypto.defi.tvl` / `crypto.defi.stablecoins` / `crypto.defi.revenue` |
| **Crypto Sentiment** | 恐贪指数 (0-100) | `FearGreedAdapter` (alternative.me, 免费) → `crypto.sentiment.fng` |
| **FRED** | 21 个宏观系列 (ONRRP/TGA/储备金/国债收益率/就业/通胀/M1M2) | `FredAdapter` → `DataLayer` → `financial.fred` |
| **金十 MCP** | 实时行情(quote) + 财经日历(calendar) + 快讯(flash) + 资讯(news) | MCP streamable-http, Bearer token |
| **yfinance + fin-skill** | 股票估值(PE/PB/ROE) + 财报 + 政策新闻 | `DataLayer` → `financial.quote.verified` (交叉验证) |
| **akshare** | A股(daily/minute/quote) + 港股(daily) + 国内期货(5交易所×82品种) | `AkshareStockAdapter` + `AkshareFuturesAdapter` (Sina 源, 无需 key) |
| **PANews** | 加密资讯 7 个能力: search/briefing/trending/article/polymarket/hooks/events | `PanewsPlugin` → HTTP API (公开端点,无需 key) |

## 技能体系 (16 个 Skill)

### 核心研究技能 (9 个)

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

### 扩展技能 (7 个, Hermes 集成 + web-search)

| Skill | 核心 |
|:------|:-----|
| `defi-analysis` | DeFi 协议研究与估值(需求/供给/收入/代币经济四维拆解) |
| `event-calendar` | 经济事件日历与影响评估 |
| `investment-memo` | 结构化投资备忘录生成 |
| `multicoin-lens` | 多币种对比分析框架 |
| `data-source-handbook` | 数据源参考与可靠性指南 |
| `fin-skill-dq-guard` | 金融数据质量校验护栏 |
| `web-search` | 多 provider 搜索降级链 (Tavily→fin-skill→Perplexity→Google CSE→SerpAPI→AnySearch→DDG) |

## 能力清单 (~42 个 capability)

**Financial**: `financial.fred` · `financial.websearch` · `financial.earnings.query` · `financial.earnings.query_full` · `financial.quote.query` · `financial.quote.verified` · `financial.data.health_check` · `financial.trace.query` · `financial.memory.save_thesis` · `financial.memory.query_theses` · `financial.memory.check_contradictions` · `financial.memory.append` · `financial.memory.get_document` · `financial.rag.search` · `financial.rag.status` · **`financial.edgar.facts`** · **`financial.edgar.release`**

**PANews** (加密资讯 ×7): `panews.search` · `panews.briefing` · `panews.trending` · `panews.article` · `panews.polymarket` · `panews.hooks` · `panews.events`

**Crypto** (链上/衍生品/DeFi/情绪 ×7): `crypto.onchain.metrics` · `crypto.derivatives.funding` · `crypto.derivatives.oi` · `crypto.defi.tvl` · `crypto.defi.stablecoins` · `crypto.defi.revenue` · `crypto.sentiment.fng`

**Memory** (热记忆 ×3): `memory.get_full_state` · `memory.update_notes` · `memory.update_profile`

**Web**: `web.fetch` (auto-fallback 到浏览器模式) · `web.fetch_weixin` (微信) · `image.describe` (多模态骨架)

**Infra**: `docs.read` · `write.file` · `Skill` (技能加载)

## 当前进度 — 阶段 4a/4b + EDGAR LANE 1/2 + Crypto Adapters + Web UI 完成 ✅

### 已就绪
- ✅ AgentRuntime + Plugin 体系 + LLM 层完整可运行
- ✅ CLI REPL + FastAPI HTTP 双入口
- ✅ SQLite 持久化: conversations / memory / trace 三库 WAL 模式
- ✅ MCP Client: fin-skill (stdio) + 金十 MCP (streamable-http, Bearer token)
- ✅ DataLayer: `FredAdapter` + `YFinanceAdapter` + `FinSkillAdapter` + `AkshareStockAdapter` + `AkshareFuturesAdapter` + `MetricCrossValidator`
- ✅ Memory: `SqliteMemoryStore` (3 表) + `ContradictionDetector` (LLM 语义比较)
- ✅ Schemas: 6 个核心 skill Pydantic I/O + State 三层 + 权限标签矩阵
- ✅ Trace: `TraceWriter` + `TraceReader` (查询 API) + DICA 四维标注
- ✅ 16 个 Skill (9 投研核心 + 7 扩展含 web-search), macro 已重写
- ✅ 浏览器抓取: Playwright + Readability.js + Stealth 反反爬, 自动降级
- ✅ Golden Cases × 13 (triage/macro/NVDA/crypto/crypto-stock/cross-skill/RAG/容错/纪律/对立观点/标的解构/RAG优先/反伪精确) + 六维 Rubric + scorer.py
- ✅ RAG 管线: 6-scheme Chunking + Qwen3-Embedding-8B + NumPy + Qwen3-Reranker-8B + 容错重试 + Plugin 接入
- ✅ 评测自动化: 25-criterion LLM-Judge 自动评分 + JSON 存储 + 历史对比 + 仪表板
- ✅ 29 篇分诊积累, 分诊台账 (append-only)
- ✅ 图片多模态骨架 (`image.describe`), 等待 API key 激活
- ✅ **多 Agent 编排 (4a)**: `Supervisor` 自研编排器 + 4 Agent (DataCollector/Researcher/Red-Team/Editor) + Pydantic Message Bus + 意图路由
- ✅ **Cron 定时调度 (4b)**: `CronAgent` + 2 套模板 (加密日报/宏观周报) + FastAPI lifespan 接入 (每天 8:00 触发)
- ✅ **新数据源**: akshare (A股+港股+期货 82 品种) + PANews (7 capabilities)
- ✅ P0 bug 修复: quote.query yfinance 两级降级 + Jina 预检超时
- ✅ **SEC EDGAR LANE 1** (`financial.edgar.facts`): companyfacts XBRL 结构化 + 4 道健壮性处理 + FPI 分支 + 14 回归测试
- ✅ **SEC EDGAR LANE 2** (`financial.edgar.release`): 6-K/8-K 业绩新闻稿抽取 + S3 零成本分类器 + S4-S8 表格解析 + G4 Guidance + F4 离线物化缓存 (362x 加速)
- ✅ **测试三层**: Tier 1 (48 fixture: EDGAR 39 + Crypto 9) + Tier 2 选择层 (26 accession 钉死) + Tier 2 SEC/Crypto 回归 (13)
- ✅ **七次同模式 bug 固化**: 信息缺失禁止填默认值 (fy/别名/币种/税率/bare year/unknown currency/无下限)
- ✅ **Crypto Data Adapters** (4 源 × 7 capability): DeFiLlama (TVL/稳定币/收入) + Coin Metrics (MVRV/MVRV-Z) + Binance (费率/OI/多空) + 恐贪指数 — 全免费无 key, 口径标注 (interval/venue/unit/definition)
- ✅ **用户隔离修复**: 6 个漏洞修复 (financial.memory.* 从 context 取 user_id + oneshot_run 用 principal_id + 路由改 require_principal_id)
- ✅ **Crypto DQ 护栏**: 8h 费率不存年化 + fees≠revenue + 恐贪不参与数值交叉验证 + 缺失返回 None
- ✅ **Web UI (Phase 4c)**: HTML + vanilla JS 三合一页面 (对话面板/每日简报/知识库浏览) + JWT auth + 静态资源托管
- ✅ **Provenance System (P0-c)**: FactRegistry (字段级事实注册 + precision 传播 + pipeline noise 过滤) + Normalizer (中文量级/货币/百分比归一化 + 日期/汇率/accession 非数据过滤) + Checker (3-pass: 精确→abs→verbatim, 防 motivated citation) + Gate (路由感知反馈 + best-attempt 跟踪 + 派生提示分叉) + F1 answered 断言 + 核心指标覆盖数 (防薄回答刷分)
- ✅ **P1 派生链**: agent 显式声明 derivation parents (prompt 集成 `## 派生计算溯源` + fact_refs 显示 period 标签 `revenue@2025Q4` + 语义引用 `caliber@period`/`fact_id` 双格式) + checker 验证公式 (AST 安全求值: +-*/abs) + 三条继承规则 (audited 取最弱 / currency 不一致拒绝 / precision 取最低) + 百分比 bridge (ratio 0.382 ↔ 正文 38.2%) + inline 计算容错
- ✅ **Provenance 基线 (XPEV Q4 2025, n=3, 冻结)**: **0% 幻觉率**, 三跑全 ANSWERED, core_coverage 达标, 可复现 — 每个数字都可追溯, 指标不能靠少说话刷
- ✅ **精度继承闭环**: `2_sig_digits_from_billion` → derived fact → display hint `≈ 2.3%` (非 `2.2917%`)
- ✅ **Bug 固化扩展**: 七次同模式 + dual-scale 字段级合并 (×1e9 固定) + 日期格式整体 non-data (含 `2025.10`/`Q4 2025` 片段) + derived 裸整数排除 + 绝对金额排除 (亿/元/$ 不能是派生值)

### 待实现 (阶段 4d-4e)
- Langfuse 全链路 trace 可视化 (每子 Agent 独立 span)
- 评测 CI/CD 回归套件 (14 Case 按 Agent 维度评估退化)

### EDGAR LANE 2 已知边界（MVP 不做）
- ex992 / 港交所式深层嵌套 HTML — XPEV Q1/Q2 2025、Q1 2026 无法提取
- 非 12 月财年 — AAPL/NVDA 财年结日 ≠ 日历年季末
- BABA 分页 — 长期上市 FPI 溢出 `submissions.recent` 上限
- S3 Phase 2 LLM 兜底 — 零成本信号已覆盖近期季度

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
- **EDGAR 测试分层**: Tier 1 `-m "not sec"` 每次提交跑（fixture-only），Tier 2 `@pytest.mark.sec` 打 SEC API 定时跑
- **EDGAR 缓存版本**: 改 extractor/classifier 逻辑后必须 bump `SCHEMA_VERSION`（`data_layer/lane2/materializer.py`）
- **EDGAR 降级保护**: FPI 季度数据禁止降级到 fin-skill（聚合商可能是推算值）
- **Crypto 口径标注**: 资金费率存原生 8h 值（不存年化为主值）+ OI 标 `unit=contracts`（不是 USD）+ 单交易所标 `venue=binance`（不叫"全市场"）
- **Crypto DQ**: 恐贪指数是情绪指标（`caliber=sentiment`），禁止参与价格/成交量的数值交叉验证
- **Provenance 字段级合并**: EDGAR 双精度记录按 (period_end, period_type) 分组, primary (raw-scale) 优先, secondary (billion-scale) 用固定 ×1e9 导入缺失字段, ratio 仅做验证 (0.99e9-1.01e9)
- **Provenance 非数据过滤**: 正常化器排除日期 (YYYY-MM-DD / YYYY年MM月)、EDGAR accession (\\d{10}-\\d{2}-\\d{6})、HK 股票代码 (.HK)、汇率上下文、pipeline noise (similarity/rank/score/count/conf/fx_rate)
- **Provenance verbatim 边界**: ✅ 货币符号/千分位逗号/全半角/空格 ←→ ❌ 单位换算/量级/四舍五入
- **Provenance 基线**: `run_provenance_baseline.py` (5 问) + `_baseline_xpev_q4_3x.py` (XPEV Q4 ×3), F1 answered 断言防止"少说话降分"
- **Provenance derived 过宽**: ~~事后 pairwise 反推是过渡方案, 随 registry 变大假阳性上升 — P1 后由 agent 显式声明 parents 根治~~ ✅ P1 派生链已交付, 绝对金额已排除, post-hoc derived 仅保留比率/百分比
- **Provenance accounting_standard 三态语义**: `""` = 不适用 (crypto/macro), 跳过冲突检测; `"UNKNOWN"` = 应有但未记录 (数据缺口), flag 不拒; 具体值参与冲突判定。`""` ≠ `"UNKNOWN"` — 不适用和未记录是两个状态，共用一个值会静默腐败
- **Provenance accounting_standard 归属层级**: 发行人级 (同一 CIK 所有文档一致), 非文档级。LANE 1 (XBRL) 和 LANE 2 (HTML) 都按 CIK 查 `get_issuer_accounting_standard(ticker)` — 不能因为读的是 HTML 就返回 null
- **Provenance period_type 域**: `fiscal_year` / `quarter` / `cumulative` (A-share 特有), 三个值在 `fact_registry.py` 顶部 `PERIOD_TYPES` 统一定义。Fact 构造时 `__post_init__` 硬校验 — 写 "ytd" 会直接抛错
- **Provenance `tier` 三重含义 (注意区分)**:
  - `Fact.media_tier: str` — 信源可信度 (`"0_primary"` / `"1_media_pro"` / `"3_aggregator"`), 仅用于 news fact
  - `Fact.source_tier: str` — 数据源层级 (`"primary"` / `"secondary"`), A-share 为 `"secondary"`
  - `DataSourceAdapter.tier: int` — 适配器降级优先级 (0/1/2), 不同类, 冲突风险低但值得记
- **A-share ⑤ 分红未入等式 (backlog)**: ΔRE≈归母NP 在无分红区间精确匹配(Q1), 跨越分红除息日(6-7月)会差出一个分红量级误报 FAILED。需纳入分红项(分配股利,利润分配表/CF)或降级为 flag。当前状态: smoke test 通过但未经分红期验证。
- **Fact 独立索引表 (P2)**: 现状 facts 在 conversation events 表 JSON 里，功能不丢数据；缺口是无法按 `(ticker, period, caliber)` 直接跨会话查询；触发时机为复盘功能开工时；⚠️ 届时需一次性从 events 反解析回填历史 facts。
- **Provenance P3**: ✅ 已修复 — `_extract_from_dict` 增加 2 层嵌套 dict 处理，EDGAR LANE 1 的 `metrics → field → {value, audited, ...}` 结构现在正确提取事实。
- **Provenance P4 (backlog)**: dump 脚本按数组下标顺序猜 Q1/Q2/Q3 分组 — 应按 `period_start/period_end` 分组。不影响 registry 数据，仅影响 CLI dump 可读性。
- **Provenance P5 (backlog)**: 派生 fact 成对出现（ratio 0.38 + percentage 38.18 — percentage bridge 产物），且丢失 period_type。应标注主值（primary），并继承父 fact 的 period 信息。
- **Provenance P6**: ✅ 已修复 — akshare 财报截取最近 8 个报告期，fact 数从 10,204 降至约 600-800。
