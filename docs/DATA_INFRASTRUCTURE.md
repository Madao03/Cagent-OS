# CagentOS 数据源全链路现状

> **更新日期**: 2026-07-22
> **适用版本**: Phase 4c+ (MVP 内测)
> **本文档**: 基于代码级全链路核查生成,非推测
> **最近变更**: 2026-07-22 Tavily + Perplexity 搜索已实现并接入(4 级降级链,fin-skill 优先省钱)

本系统是一个多 Agent 投研操作系统,数据层是基石。本文档梳理所有数据源的现状、配置方式、fallback 机制和已知问题。

---

## 目录

1. [架构总览](#1-架构总览)
2. [金融数据源](#2-金融数据源)
3. [网络搜索引擎](#3-网络搜索引擎)
4. [网页抓取](#4-网页抓取)
5. [RAG 知识库](#5-rag-知识库)
6. [MCP 服务](#6-mcp-服务)
7. [LLM 配置](#7-llm-配置)
8. [环境变量完整清单](#8-环境变量完整清单)
9. [已知问题与风险](#9-已知问题与风险)

---

## 1. 架构总览

```
用户对话
  │
  ├── LLM(DeepSeek / Claude / GPT)
  │     ├── ReAct 工具调用
  │     │
  │     ├── financial.rag.search     ──→ RAG 知识库(1491 chunks)
  │     │
  │     ├── financial.quote.query    ──→ 金融报价
  │     │     ├── fin-skill MCP (Tier 2)
  │     │     └── yfinance (Tier 1, fallback)
  │     │
  │     ├── financial.quote.verified ──→ 交叉验证(5% 方差)
  │     │
  │     ├── financial.websearch      ──→ 网络搜索
  │     │     ├── fin-skill MCP market_news
  │     │     └── DuckDuckGo HTML (fallback)
  │     │
  │     ├── web.fetch / web.fetch_weixin ──→ 网页抓取
  │     │     ├── Jina AI Reader
  │     │     ├── HTTP 直连 + sanitizer
  │     │     └── Playwright 浏览器 (WSL)
  │     │
  │     ├── FRED API ──→ 宏观经济数据(21 系列)
  │     │
  │     ├── akshare ──→ A股/期货/港股(免费)
  │     │
  │     ├── PANews ──→ 加密资讯(PANews API)
  │     │
  │     ├── memory.update_notes / profile ──→ 用户记忆
  │     │
  │     └── write.file ──→ 知识库归档
  │
  └── SSE 流式返回 ──→ 前端渲染
```

---

## 2. 金融数据源

### 2.1 源总览

| 源名称 | Provider | Tier | API Key | Fallback | 状态 |
|:------|:---------|:----:|:--------|:---------|:----:|
| `yfinance` | Yahoo Finance | 1 | 否(免费) | 无 | ✅ |
| `fin-skill` | fin-skill MCP Server | 2 | 否(MCP stdio) | 无 | ✅ |
| `fred` | FRED API | 1 | `FRED_API_KEY` | 无(单源独占) | ✅ |
| `akshare-stock` | 新浪财经 | 1 | 否(免费) | 无 | ✅ |
| `akshare-futures` | 新浪财经 | 1 | 否(免费) | 无 | ✅ |

### 2.2 报价链路:两级降级 + 交叉验证

`financial.quote.query` 的 fallback 逻辑:

```
Tier 2: fin-skill MCP get_stock_quote
  │
  ├─ 有有效数据(price 非 None/0) → 返回
  │
  └─ 无有效数据 → 降级
        │
        Tier 1: yfinance Ticker.info
          │
          ├─ 有数据 → 返回(标注 data_source: yfinance)
          │
          └─ 无数据 → 返回 finance_empty_result 错误
```

`financial.quote.verified` 的交叉验证逻辑(`cross_validator.py`):

| 验证级别 | 条件 | Confidence | 处理 |
|:--------|:-----|:----------:|:-----|
| `dual_source` | 两源方差 ≤ 5% | 0.85 | 取均值 |
| `dual_source_with_outlier` | 方差 > 5%,排除离群源后仍 ≥ 2 源 | 0.70 | 排除偏离最大的源 |
| `single_source` | 只有一源返回数据 | 0.50 | 直接使用 |
| `single_source_after_outlier` | 排除离群后只剩 1 源 | 0.40 | 使用剩余源 |
| `failed` | 无源返回数据 | 0.00 | 报错 |

> **注意**: 交叉验证目前硬编码只对 `{"yfinance", "fin-skill"}` 两源生效(`__init__.py:96-97`)。akshare 不参与交叉验证。

### 2.3 缓存 TTL(`__init__.py:25-30`)

| Metric 类型 | TTL |
|:-----------|:---|
| price / volume | 300s (5 分钟) |
| PE / PB / PS / peg / market_cap | 900s (15 分钟) |
| ROE / ROA / dividend_yield / beta | 86400s (24 小时) |
| 其他 | 900s |

### 2.4 YFinanceAdapter(免费主力)

| 项 | 值 |
|:---|:---|
| 覆盖 metric | 30 个(fwd_pe, ttm_pe, price, market_cap, beta, pb, ps, eps, roe, roa, peg 等) |
| 特殊 metric | `full_quote` → 返回完整 `Ticker.info` dict |
| 实现 | `asyncio.to_thread` 包装同步 `yfinance` 库 |
| 已知问题 | `forwardPE` 常为 null(数据供应商差异) |

### 2.5 FinSkillAdapter(MCP 补充)

| 项 | 值 |
|:---|:---|
| MCP Server | `fin-skill-mcp` (stdio) |
| 覆盖 metric | 21 个 |
| 调用的 MCP 工具 | `get_stock_analysis` / `get_financials` / `get_stock_quote` / `get_company_news` / `get_market_news` / `get_asset_klines` |
| 已知问题 | PE forward 可能与 yfinance 差异 > 30%; `get_financials` 硬编码 `fiscal_year=2025` |

### 2.6 FREDAdapter(宏观独占)

| 项 | 值 |
|:---|:---|
| API | `https://api.stlouisfed.org/fred` |
| 速率限制 | 120 req/min |
| 覆盖系列 | **21 个命名系列**(不是文档之前说的 44 个) |
| 分类 | 流动性(4) + 国债收益率(6) + 就业(5) + 通胀(3) + GDP(1) + 货币供应(2) |
| 特殊功能 | 支持 `metric="custom"` + `series_id=` 传入任意 FRED 系列 ID |
| 缺失值过滤 | `"."`, `"N/A"`, `None`, `""` |

### 2.7 Akshare(A股 / 期货)

| Adapter | 市场 | Metric | 复权方式 |
|:--------|:-----|:-------|:--------|
| `akshare-stock` | A股(沪深) / 港股 / 美股指数 | daily / minute / quote | 前复权(`qfq`) |
| `akshare-futures` | 5 交易所 × 82 品种 | daily / minute / quote / symbols | 主连合约 |

### 2.8 财报链路(⚠️ 无降级)

| 工具 | 数据源 | 降级 | 状态 |
|:----|:------|:----:|:----:|
| `financial.earnings.query` | fin-skill MCP only | ❌ 无 | 🔴 MCP 挂则不可用 |
| `financial.earnings.query_full` | fin-skill MCP only | ❌ 无 | 🔴 同上 |

---

## 3. 网络搜索引擎

### 3.1 当前实现(`toolkit.py:339-404`)

四级降级链(按成本从低到高排列):

```
Tier 1: fin-skill MCP get_market_news (免费,无 API key)
  │     ⚠️ 拿的是通用市场新闻,不接受 query 参数
  │
  ├─ 有结果 → 加入 combined
  └─ 无结果/MCP 不可用 → 记录失败
        │
Tier 2: Tavily API (https://api.tavily.com/search)
  │     高质量语义搜索,需要 TAVILY_API_KEY
  │     search_depth: "basic", 1000 次/月免费
  │     超时 10s
  │
  ├─ combined 不足 → 补充
  └─ 无结果/无 key → 记录失败
        │
Tier 3: Perplexity Sonar API (https://api.perplexity.ai/chat/completions)
  │     AI 综合回答 + 引用来源,需要 PERPLEXITY_API_KEY
  │     免费版有速率限制,model="sonar"
  │     超时 15s
  │
  ├─ combined 不足 → 补充
  └─ 无结果/无 key → 记录失败
        │
Tier 4: DuckDuckGo HTML (免费兜底)
        POST https://html.duckduckgo.com/html/
        伪装 Chrome 130 UA,正则解析
        超时 8s
```

**设计考量**: fin-skill 放第一(免费 + 本地),付费 API(Tavily/Perplexity)只在免费源不足时调用,最大限度节省 API 费用。

**实测结果**(2026-07-22):

| 查询 | Provider 命中 | 质量 |
|:----|:--------|:----|
| `NVDA earnings Q2 2026` | tavily | CNBC + Yahoo + NVIDIA 官网 |
| `美联储 2026年7月 利率决议` | tavily | 币安 + 新浪 + 经济日历(中文) |
| `Bitcoin ETF flows July 2026` | tavily | CoinDesk + X/Twitter + LiveVolatile |
| (Perplexity 单独测试) | perplexity | AI 综合回答("revenue $46.7B, EPS $1.08") + 14 条引用 |

### 3.2 搜索 Provider 配置 vs 实现差距

| Provider | 配置层 | 实现层 | 费用 | 状态 |
|:---------|:------|:------|:-----|:----:|
| **fin-skill** | MCP 配置 | ✅ Tier 1 优先 | 免费 | ✅ |
| **Tavily** | ✅ 常量+环境变量 | ✅ Tier 2 | 1000 次/月免费 | ✅ |
| **Perplexity** | ✅ 常量+环境变量 | ✅ Tier 3 | 免费版(限速) | ✅ |
| **DuckDuckGo** | 未声明 | ✅ Tier 4 兜底 | 完全免费 | ✅ |
| **Google CSE** | ✅ 常量+环境变量 | ❌ 未实现 | 100 次/天免费 | 🔴 |
| **Perplexity Pro** | — | ❌ 未实现 | 付费 | — |

> **关于 Google CSE**: 质量最好但免费额度太少(100次/天),不适合高频使用。当前 Tavily + Perplexity 组合已足够。
>
> **为什么很多人用 DDG 不用 Google**: 不是反爬问题(Google CSE 是官方付费 API 不受限),而是 Google 免费额度太少。DDG 爬取完全免费但质量一般。

---

## 4. 网页抓取

### 4.1 三个 Capability

| 工具 | 适用场景 | 降级链 |
|:----|:--------|:------|
| `web.fetch` | 普通网页 | Jina → HTTP → Playwright |
| `web.fetch_weixin` | 微信公众号 | 直接 Playwright(微信反爬强) |
| `image.describe` | 图片多模态理解 | GPT-4o Vision(需配 Key) |

### 4.2 web.fetch 三级降级链(`plugin.py:137-290`)

```
Layer 1: Jina AI Reader (https://r.jina.ai/{url})
  │     3s 探活,首次检测后缓存结果
  │     5s 超时,返回 markdown
  │
  ├─ 成功且非反爬 → 返回
  └─ 失败/反爬 → 降级
        │
Layer 2: HTTP 直连 (requests.Session)
  │     10s 超时,HTML 走 sanitizer
  │
  ├─ 成功且非反爬 → 返回
  └─ 失败/反爬 → 降级
        │
Layer 3: Playwright 浏览器 (via WSL)
        WSL 探活(5s) → 调用 fetch_browser.py
        90s 超时,最多重试 2 次
        成功后从 WSL /tmp/ 复制到 Windows knowledge/00_Inbox/
```

### 4.3 反爬检测(`plugin.py:565-607`)

判定逻辑:
- 内容 < 500 字符 → 可疑
- 前 2000 字符匹配以下任一 → 判定反爬:
  - `just a moment` (Cloudflare)
  - `checking your browser`
  - `enable javascript`
  - `verify you are a human`
  - `attention required`
  - `access denied`
  - `request blocked`
  - `challenge-page`

### 4.4 WSL Playwright 环境变量(⚠️ 必须配置)

| 变量 | 默认值(占位符) | 用途 |
|:-----|:-------------|:-----|
| `CAGENTOS_WSL_PYTHON` | `/path/to/your/playwright-venv/bin/python3` | WSL 中 Python 路径 |
| `CAGENTOS_WSL_FETCH_SCRIPT` | `/path/to/your/fetch_weixin.py` | 微信抓取脚本 |
| `CAGENTOS_WSL_FETCH_BROWSER_SCRIPT` | `/path/to/your/fetch_browser.py` | 通用浏览器抓取脚本 |

> **部署注意**:这三个默认值是占位符,不配置会导致 Playwright 降级链完全失效。

---

## 5. RAG 知识库

### 5.1 技术栈

| 项 | 值 |
|:---|:---|
| 嵌入模型 | **Qwen/Qwen3-Embedding-8B** |
| 嵌入 API | SiliconFlow (`https://api.siliconflow.cn/v1`) |
| 向量维度 | **1024** |
| 批大小 | 32 |
| 向量存储 | **NumPy**(非 FAISS/ChromaDB) |
| Reranker | **Qwen/Qwen3-Reranker-8B** (SiliconFlow) |
| 检索流程 | 向量召回 Top-20 → rerank → Top-5 → LLM context |

### 5.2 环境变量

| 变量 | 必需 | 用途 |
|:-----|:----:|:-----|
| `SILICONFLOW_API_KEY` | ✅ | 嵌入 + Reranker 共用 |

### 5.3 Chunking 策略(6 种方案)

| Scheme | 函数 | 模式 | 参数 | 适用 |
|:-------|:-----|:-----|:-----|:-----|
| `news` | `chunk_news` | flat | size=512, overlap=50 | 新闻、短文 |
| `research` | `chunk_research` | parent-child | parent=1500, child=300 | 长篇研报 |
| `ledger` | `chunk_ledger` | 按表格行 | 一行一 chunk | 分诊台账 |
| `earnings` | `chunk_earnings` | flat | size=1024 | 财报 |
| `social` | `chunk_social` | flat | size=256, overlap=30 | KOL 短文 |
| `asset` | `chunk_json` | 按字段 | facts/opinions/frameworks | asset.json |

**自动检测**(`_detect_scheme`): ledger > earnings > social < 400 字 > news 400-2000 字 > research

**保护模式**(不分割): 代码块、数学公式 `$$...$$`、图片 `![]()`、完整表格

**噪声过滤**: YAML frontmatter / 合规免责声明 / 微信尾部样板文字

### 5.4 当前索引状态

```
chunks: 1491
embedding_model: Qwen/Qwen3-Embedding-8B
dimensions: 1024
knowledge_dir: knowledge
```

### 5.5 图片处理

| 链路 | 状态 |
|:----|:----|
| Chunking | 🟡 保留图片标记 `![]()`,不提取内容 |
| Embedding | 🔴 纯文本嵌入,图片被忽略 |
| RAG 检索 | 🔴 返回文字,不含图片 |
| 前端显示 | ✅ `/knowledge-static/` 端点 serving 本地图片 |

---

## 6. MCP 服务

**配置文件**: `config/mcp_servers.json`

| Server | Transport | 状态 | 认证 | 能力 |
|:------|:----------|:----:|:-----|:-----|
| `fin-skill-mcp` | stdio | ✅ enabled | 无 | 股票分析、财报、行情、新闻、K线 |
| `jin10-mcp` | streamable-http | ✅ enabled | `JIN10_API_KEY` | 金十数据:实时行情+财经日历+快讯 |
| `cmc-mcp` | streamable-http | ❌ disabled | `CMC_API_KEY` | CoinMarketCap 加密货币数据 |

> `fin-skill-mcp` 支持切换到 streamable-http(`http://localhost:8102/mcp`,env `MCP_TRANSPORT=streamable-http`)

---

## 7. LLM 配置

### 7.1 支持的 Provider

| Provider | 后端类 | API Key 环境变量 | 状态 |
|:---------|:-------|:----------------|:----:|
| `openrouter`(默认) | `OpenRouterBackend` | `OPENROUTER_API_KEY` | ✅ |
| `deepseek` | `OpenAICompatibleBackend` | `DEEPSEEK_API_KEY` / `LLM_API_KEY` | ✅ |
| `openai` | `OpenAICompatibleBackend` | `OPENAI_API_KEY` / `LLM_API_KEY` | ✅ |
| `anthropic` | `OpenAICompatibleBackend` | `ANTHROPIC_API_KEY` / `LLM_API_KEY` | ✅ |
| `groq` | `OpenAICompatibleBackend` | `LLM_API_KEY` | ✅ |
| `siliconflow` | `OpenAICompatibleBackend` | `LLM_API_KEY` | ✅ |
| `together` | `OpenAICompatibleBackend` | `LLM_API_KEY` | ✅ |
| `custom` | `OpenAICompatibleBackend` | `LLM_API_KEY` + `LLM_BASE_URL` | ✅ |

### 7.2 Model Aliases

| Alias | 模型 |
|:------|:-----|
| `claude-balanced`(默认) | `anthropic/claude-sonnet-4.6` |
| `opus-strong` | `anthropic/claude-opus-4.6` |
| `gpt-fast` | `openai/gpt-5-mini` |
| `gpt-strong` | `openai/gpt-5.4` |
| `gemini-strong` | `google/gemini-3.1-pro-preview` |
| `gemini-cheap` | `google/gemini-2.5-flash-lite` |
| `gemini-balanced` | `google/gemini-2.5-flash` |

可通过 `MODEL_ALIASES` 环境变量(JSON 格式)覆盖。

---

## 8. 环境变量完整清单

### 8.1 必须配置(上线前)

| 变量 | 用途 | 生成方式 |
|:-----|:-----|:--------|
| `JWT_SECRET_KEY` | JWT 签名 | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ADMIN_TOKEN` | Admin API 鉴权 | `python -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `DEEPSEEK_API_KEY` | 主 LLM | DeepSeek 平台 |
| `SILICONFLOW_API_KEY` | 嵌入 + Reranker | SiliconFlow 平台 |

### 8.2 推荐配置(增强能力)

| 变量 | 用途 |
|:-----|:-----|
| `FRED_API_KEY` | 宏观经济数据(21 系列) |
| `JIN10_API_KEY` | 金十数据(实时行情+快讯) |
| `TAVILY_API_KEY` | 高质量网络搜索(⚠️ 需实现) |
| `JINA_API_KEY` | 网页抓取(Jina Reader) |

### 8.3 浏览器抓取(WSL 相关)

| 变量 | 用途 |
|:-----|:-----|
| `CAGENTOS_WSL_PYTHON` | WSL Playwright Python 路径 |
| `CAGENTOS_WSL_FETCH_SCRIPT` | 微信抓取脚本路径 |
| `CAGENTOS_WSL_FETCH_BROWSER_SCRIPT` | 浏览器抓取脚本路径 |

### 8.4 可选

| 变量 | 用途 |
|:-----|:-----|
| `OPENROUTER_API_KEY` | OpenRouter(多模型聚合) |
| `OPENAI_API_KEY` | OpenAI(含 GPT-4V 多模态) |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `GOOGLE_API_KEY` + `SEARCH_ENGINE_ID` | Google Custom Search |
| `PERPLEXITY_API_KEY` | Perplexity 搜索 |
| `CMC_API_KEY` | CoinMarketCap |
| `CAGENTOS_VISION_API_KEY` | 图片理解(GPT-4o) |

---

## 9. 已知问题与风险

### 🔴 P0 - 必须修复

| # | 问题 | 影响 | 位置 |
|:-|:----|:----|:-----|
| 1 | **财报(earnings)无降级** | MCP 挂则完全不可用 | `toolkit.py:278-279, 315-316` |
| 2 | **WSL 脚本路径是占位符** | 浏览器抓取完全失效 | `plugin.py:22-24` |

### 🟡 P1 - 应该修复

| # | 问题 | 影响 |
|:-|:----|:----|
| 3 | ~~`websearch` 的 MCP 层名不副实~~ → **已缓解**:Tavily 作为 Tier 1 后,MCP 新闻降为 Tier 2 补充 |
| 4 | 交叉验证硬编码两源 | akshare 不参与,无法多源验证 |
| 5 | `get_financials` 硬编码 `fiscal_year=2025` | 2026 年会拿错年份 |
| 6 | FRED 实际 21 系列(文档说 44) | 文档不准确 |
| 7 | RAG 图片纯文本嵌入 | 图表内容无法被检索 |

### 🟢 P2 - 已知限制

| # | 问题 | 影响 |
|:-|:----|:----|
| 9 | `ALPHA_VANTAGE_API_KEY` / `FMP_BASE_URL` 声明但无 adapter | 声明层残留 |
| 10 | `EMBEDDING_PROVIDER` / `FASTEMBED_MODEL` 声明但未使用 | RAG 硬编码 SiliconFlow |
| 11 | VectorStore 变量名 `chroma_path` 实际是 NumPy | 命名误导 |
| 12 | 对话 LLM 不支持图像输入 | 用户不能截图提问 |
