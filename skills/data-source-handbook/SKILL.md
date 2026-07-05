---
name: data-source-handbook
description: |
  全局数据源注册表 — 集中管理所有数据源的接入方式、实测可靠性、已知陷阱与 fallback 策略。
  20 个数据源全覆盖，所有分析 Skill 的 Step 1 数据收集环节引用此手册。
  含 CoinGecko/CMC/Binance/DeFiLlama/FRED/Yahoo Finance/金十/Coinglass/SoSoValue 等实测教训。
category: research
---

# Data Source Handbook — 全局数据源注册表

> **定位**: 所有分析 Skill 的数据获取前置参考。每个数据源标注了实测可靠性、已知陷阱和 fallback 策略。
> 这些信息无法通过阅读文档得知——每一行都是踩坑换来的。

## 使用方式

当分析 Skill 触发时：
1. 先加载本 handbook 获取数据源信息
2. 按优先级选择数据源
3. 如有失败，按 fallback 策略降级
4. 所有数据标注来源和时间

---

## 数据源分层

| 层级 | 类型 | 策略 | 举例 |
|:----:|:----|:-----|:-----|
| 🟢 Tier 1 | 免费/公开 API | 优先使用 | CoinGecko, CMC, Binance, DeFiLlama, FRED, Yahoo Finance, 金十, BlockWorks |
| 🔶 Tier 2 | 浏览器读取 | 一次性查证（慢但可用） | Trading Economics, CME FedWatch |
| 💎 Tier 3 | 付费订阅 | 锦上添花 | Coinglass Basic ($299/月), CryptoQuant Pro ($399/月), Dune |

---

## 两个主力 API 的战略分工

| | CoinGecko | CoinMarketCap |
|:--|:----------|:--------------|
| 定位 | **主力** | **辅助** |
| 免费可用 | ✅ 无key也可（10-30/min） | 需 API Key（333 credits/天） |
| 胜场 | 板块/叙事分类、衍生品交易所 | global-metrics 细粒度、gainers-losers、多周期涨跌幅 |
| 限速切换 | → 切 CMC | → 切 CoinGecko |

---

## 各数据源实测可靠性

### CoinGecko — 🟢 主力

| 端点 | 可靠性 | 注意 |
|:-----|:------|:-----|
| `GET /global` | ✅ 稳定 | BTC.D、总市值、24h成交量 |
| `GET /coins/markets?ids=a,b,c` | ✅ 稳定 | ⭐ 推荐替代 `/simple/price` |
| `GET /coins/categories` | ✅ 稳定 | 某些 category 的 market_cap 可能为 null |
| `GET /simple/price` | ⚠️ 不可靠 | 代理下常返回空响应——用 `/coins/markets` 替代 |
| `GET /coins/{id}` | ⚠️ 不可靠 | 易超时——用 `/coins/markets` 替代 |

### CMC — 🟢 辅助 (Basic Plan)

- Sandbox key 返回的数据是**伪造的**（如 BTC.D=0.18%）← 只能做字段结构测试
- 真实 API (`pro-api.coinmarketcap.com`) 已验证可用
- 10,000 credits/月硬顶，约333 credits/天
- ⭐ 最值钱端点: `GET /v1/global-metrics/quotes/latest`（比 CoinGecko `/global` 更细）

### Yahoo Finance + yfinance — ⚠️ 间歇性可用

- **yfinance 直连可用，不走代理**（curl_cffi 浏览器指纹在直连时不会被限速）
- **走 Clash 代理反而被返回 HTTP 429**（curl_cffi 指纹被识别为爬虫）
- Yahoo v8 chart API 高频请求下返回 `Too Many Requests`
- **单次 + 间隔 3s** 勉强可用
- 替代方案：FRED(美债) + 金十MCP(黄金/原油/外汇) + web_search(VIX/SPX)

### FRED — ✅ 稳定

- Key 已验证可用，限速 120 req/min（远够用）
- 部分系列为季度数据（GDP/FYFSD），查询间隔不同

### DeFiLlama — ✅ 大部分端点稳定

| 端点 | 可靠性 | 注意 |
|:-----|:------|:-----|
| `GET /chains` | ✅ 正确端点 | 不要用 `/v2/chains`——首条永远是 Harmony + TVL≈0 |
| `GET /overview/fees/{protocol}` | ❌ 不可靠 | 频繁返回 Internal Server Error 或空数据。**不要依赖此端点做估值** |

### alternative.me — ⚠️ 端点迁移

- 正确端点: `https://api.alternative.me/fng/`（注意末尾斜杠）
- 旧形式 `fng?limit=1` 会 301 跳转

### 金十 MCP — 🟢 稳定 (92品种)

- SSE 协议直连（不走代理），session 重启后需重新初始化
- 覆盖外汇/商品/全球指数/银行贵金属，**不含美股个股**
- 黄金数据首选金十（返回完整 OHLCV），fin-skill 仅返回裸价

### LookIntoBitcoin — ❌ 已不可用

- 域名已重定向到 `bitcoinmagazinepro.com`，需登录+付费订阅
- Fallback: web_search "BTC MVRV-Z score [date]"

### PANews — 🟢 加密新闻

- 中文加密新闻搜索、项目动态追踪、叙事分析
- 比 web_search 更聚焦且去噪
- Fallback: CMC latest-news + web_search

### Binance Futures API — 🟢 衍生品数据

- 公开端点无需 key
- 资金费率/OI/多空比/基差 均可直接获取

### BlockWorks Research API — 🟢 免费额度

- 2,500 次/月免费，29 条链 + 136 个项目
- 替代/补充 DeFiLlama 做链上监控

### RootData — 🟢 加密项目数据库

- Basic plan 免费，`ser_inv` 搜索无限额度
- 项目详情/VC详情各消耗2 credits

### SEC EDGAR XBRL — 🟢 美股季报时效性补丁

- 当 yfinance/CIQ 尚未录入最新季度财报时，唯一能获取刚出炉数据的通路
- 无需 key，但必须设合法 User-Agent
- 10-Q 数据通常是累计 YTD，需减出单季

### SoSoValue — 🟢 免费期

- BTC/ETH 现货 ETF 资金流向是独有差异化价值
- 当前免费期，后续上线付费 API

### Coinglass — 💎 付费（$299/月）

- 加密衍生品数据行业标准
- 免费版仅开发测试，生产走 Basic

### CryptoQuant — 💎 付费（$399/月）

- 专业级链上数据（Exchange Flow/Miner Flow/UTXO年龄分布）
- 网站有 Cloudflare 严格反爬

---

## URL → Markdown 抓取工具

- **qiaomu-markdown-proxy**（已安装可用 ✅）
- Playwright + Chromium 已安装（`/tmp/pw_venv/`），微信公众号抓取已验证
- 5 种专用通道：微信公众号(Playwright) / 飞书文档(API) / YouTube / PDF(三级提取) / 普通网页

### 各站点实测抓取路径

| 站点 | curl | browser | 最佳路径 |
|:-----|:----:|:-------:|:--------|
| Yahoo Finance | ❌ 429 | ✅ | browser直接读 |
| The Defiant | ❌ JS渲染 | ✅ console | browser → console |
| CoinGecko | ❌ Cloudflare | ❌ | **无法自动读取** |
| CMC Community | ✅ | ✅ | curl 或 browser 均可 |

---

## 搜索引擎降级链

| 引擎 | 实测 | 说明 |
|:----|:-----|:-----|
| ❌ Google (curl) | 400 Error | 检测非浏览器 UA |
| ❌ Bing (proxy) | 结果污染 | 中文搜索返回百度知道垃圾 |
| ❌ DuckDuckGo HTML | 超时 | 代理下不可达 |
| ✅ Naver (browser) | 中文搜索可用 | Google/Bing 被拦截时的首选 fallback |
| ✅ 36kr 站内搜索 | 中文科技新闻可用 | 科技/创投领域深度覆盖 |

### 中文内容搜索降级链

```
1. Naver browser搜索 (search.naver.com)
2. 36kr 站内搜索 (36kr.com/search/articles/<query>)
3. PANews (加密新闻) / fin-skill MCP (美股新闻)
4. 直接知识 — 标注来源和时效性
```

---

## 通用选型原则（实测修正版）

1. **集合/聚合端点 > 单币端点**: `/global` > `/simple/price`, `/coins/markets?id=a,b,c` > `/coins/{id}`
2. **优先使用无需密钥的公开 API**: CoinGecko(无key) > CMC(需key确认)
3. **代理解析**: CoinGecko/Binance/FRED/DeFiLlama → ✅ 通过代理稳定。Yahoo Finance → ⚠️ yfinance 直连不走代理
4. **金十 MCP**: SSE协议直连（不走代理），session 重启后需重新初始化
5. **margin of error**: 任何数据源标注"完全可用"都必须经过至少两个不同时段的实测验证
6. **所有数据标注来源和时间**，获取不到就标 `[无数据]`，不编造
