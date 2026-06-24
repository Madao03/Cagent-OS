# Web3 数据源评估报告 — 投研Agent数据基座

> **编制日期**: 2026-06-23  
> **编制目的**: CagentOS 投研Agent数据基座建设 — Web3 数据源选型评估  
> **评估范围**: 7 个核心数据源（DeFiLlama / SoSoValue / 恐贪指数 / BlockWorks / rwa.xyz / Coinglass / CMC）  
> **评估方法论**: 每个数据源从「作用与价值 × 成本结构 × API 拆解 × 接入方式 × 使用规范」五维评估

---

## 目录

1. [评估框架与选型原则](#1-评估框架与选型原则)
2. [DeFiLlama — DeFi 全貌数据](#2-defillama--defi-全貌数据)
3. [SoSoValue — 一站式投研平台](#3-sosovalue--一站式投研平台)
4. [恐贪指数 — 市场情绪量化](#4-恐贪指数--市场情绪量化)
5. [BlockWorks Research — 机构级链上基本面](#5-blockworks-research--机构级链上基本面)
6. [rwa.xyz — RWA 赛道专精](#6-rwaxyz--rwa-赛道专精)
7. [Coinglass — 衍生品全维度](#7-coinglass--衍生品全维度)
8. [CoinMarketCap — 行情与市值基准](#8-coinmarketcap--行情与市值基准)
9. [综合对比与推荐组合](#9-综合对比与推荐组合)
10. [数据采集策略](#10-数据采集策略)

---

## 1. 评估框架与选型原则

### 五维评估模型

| 维度 | 评估问题 | 权重 |
|:-----|:--------|:----:|
| **数据价值** | 这些数据能回答哪些投研问题？独特性如何？ | ⭐⭐⭐⭐⭐ |
| **成本结构** | 免费额度够用吗？付费升级性价比？ | ⭐⭐⭐⭐ |
| **接入难度** | Auth方式、SDK支持、文档质量 | ⭐⭐⭐ |
| **数据质量** | 时效性、准确度、覆盖范围、已知坑 | ⭐⭐⭐⭐⭐ |
| **合规与限制** | 商业使用条款、再分发限制、限速策略 | ⭐⭐⭐ |

### 选型铁律（来自生产环境实测）

1. **优先免费/公开 API**：免费额度内能满足的，不付费
2. **交叉验证不互替**：两个 API 共存不是因为"一个限速用另一个"，是因为数据维度不同
3. **标注来源和时间**：所有数据点标注数据源 + 抓取时间，不做「LLM记忆中的数字」
4. **获取不到就标 `[无数据]`**：不编造
5. **备用路径必须预置**：每个数据源必须配置 fallback（见各节 Fallback 链）
6. **JS 渲染页面不可自动读取**：Coinglass / rwa.xyz / SoSoValue 等 SPA 站点 curl 返回空，需要浏览器渲染或 API 端点（确认有 API 后再集成）

---

## 2. DeFiLlama — DeFi 全貌数据

### 2.1 作用与价值

**一句话定位**：DeFi 领域最权威的 TVL/DEX/收益/稳定币数据聚合平台，覆盖 200+ 条链，社区维护适配器保证数据质量。

**核心价值**：

| 投研问题 | DeFiLlama 能回答 | 对应端点 |
|:---------|:----------------|:--------|
| 各链资金流向：钱在涌入哪条链？ | 各链 TVL + 历史趋势 | `/chains` + `/charts/{chain}` |
| DEX 赛道的王者是谁？增速如何？ | 各协议 24h/7d/30d 交易量 | `/overview/dexs` |
| 哪些协议在"真赚钱"？ | 协议收入/费用数据 | `/overview/fees` |
| 稳定币是扩张还是收缩？ | 各稳定币流通量 + 链分布 | `/stablecoins` |
| 哪里的收益最高？风险如何？ | 各链收益池 APY + 无常损失风险 | `/yields/pools` |
| VC 在投什么？ | 融资轮次数据 | `/raises` |
| 治理动态 | 提案活跃度 | `/governance` |

**为什么是 Tier 1**：完全免费、无需认证、数据实时、覆盖面广。是 DeFi 投研的「第一天必须接」的数据源。

### 2.2 成本结构

| Tier | 价格 | 限速 | 适用场景 |
|:-----|:----|:----|:--------|
| **Free** | $0/月 | ~60 req/min（软限制） | ✅ 大部分投研需求已够用 |
| **Pro** | $3,000/月 | 定制（10-100x 免费版） | 商业产品 / 高频轮询 / SLA |

**判断**：免费版对个人投研 Agent 使用**足够**。Pro 仅在对外商业产品场景需要。

### 2.3 API 拆解

**文档地址**：https://api-docs.defillama.com/ （Dimensions） / https://defillama.com/docs/api （经典）

**Base URL（4 个子域）**：

```
https://api.llama.fi/          ← TVL、协议、DEX 总览、收入/费用
https://stablecoins.llama.fi/  ← 稳定币专用
https://yields.llama.fi/       ← 收益池专用
https://nft.llama.fi/          ← NFT 专用
```

**核心端点详解**：

#### 🔴 高优先级端点（每日调用）

| 端点 | 方法 | 说明 | 响应关键字段 |
|:-----|:----|:-----|:-----------|
| `/chains` | GET | ⚠️ 各链 TVL 排名（**不要用 `/v2/chains`，有 bug**） | `gecko_id`, `tvl`, `tokenSymbol`, `name`, `chainId` |
| `/overview/dexs` | GET | DEX 24h/7d/30d 交易量总览 | `total24h`, `total7d`, `change_1d`, `change_7d`, `breakdown24h` |
| `/overview/fees` | GET | ⚠️ 协议收入/费用（**已知不可靠：`/summary/fees/` 频繁 500**） | `total24h`, `change_1d`, `breakdown24h` |
| `/stablecoins` | GET | 所有稳定币 + 各链分布 | `peggedAssets[]`, `chains{}` |
| `/yields/pools` | GET | 收益池（APY + TVL + 风险预测） | `apy`, `apyBase`, `apyReward`, `tvlUsd`, `ilRisk`, `predictions` |

#### 🟡 中优先级端点（按需调用）

| 端点 | 用途 | 说明 |
|:-----|:----|:-----|
| `/protocol/{name}` | 单协议详情（含各链 TVL 拆解） | 如 `/protocol/aave` |
| `/charts/{chain}` | 链 TVL 历史走势 | 用于趋势分析 |
| `/raises` | VC 融资轮次 | 追踪投资热度 |

#### 🟢 低优先级端点（偶尔调用）

| 端点 | 用途 |
|:-----|:----|
| `/config/adapters` | 适配器元数据 |
| `/governance` | 治理提案数据 |
| `/borrows` | 借贷协议数据 |
| NFT 端点 | NFT 合集数据 |

### 2.4 接入方式

**无需 API Key，直接 GET**：

```python
import requests

# 1. 各链 TVL 排名（主力端点）
chains = requests.get("https://api.llama.fi/chains").json()
top5 = sorted(chains, key=lambda x: x["tvl"], reverse=True)[:5]
for c in top5:
    print(f"{c['name']}: ${c['tvl']:,.0f}")

# 2. DEX 24h 交易量
dexs = requests.get("https://api.llama.fi/overview/dexs").json()
print(f"Total DEX 24h: ${dexs['total24h']:,.0f}")

# 3. 稳定币流通
stables = requests.get("https://stablecoins.llama.fi/stablecoins").json()
for p in stables["peggedAssets"][:5]:
    circ = p.get("circulating", {}).get("peggedUSD", 0)
    print(f"{p['symbol']}: ${circ:,.0f}")

# 4. 收益池（Top 5 APY）
pools = requests.get("https://yields.llama.fi/pools").json()
for p in sorted(pools["data"], key=lambda x: x.get("apy", 0), reverse=True)[:5]:
    print(f"{p['project']} {p['symbol']}: APY {p['apy']:.2f}% | TVL ${p['tvlUsd']:,.0f}")
```

**Fallback 链**：CoinGecko `/global`（总市场数据） + BlockWorks Research API（链上细粒度）

### 2.5 已知坑与使用规范

| 坑 | 表现 | 规避方式 |
|:--|:----|:--------|
| ❌ `/v2/chains` | 首条永远是 Harmony + TVL≈0 | **只用 `/chains`**（不带 v2） |
| ⚠️ `/summary/fees/` | 频繁返回 Internal Server Error 或空数据 | **不要依赖此端点做估值**。用 Token Terminal / web_search 替代 |
| ⚠️ 费用数据不可靠 | 同上，已知问题 | 标注 `[DeFiLlama费用数据，可能存在500错误]` |
| 💡 社区适配器 | 各协议数据由社区维护，偶尔滞后 | 交叉验证 Token Terminal / 协议官网 |
| 💡 缓存周期 | 服务端 5-15 分钟缓存 | 不必每个请求都拉，客户端缓存 15 分钟 |

### 2.6 投研 Agent 集成建议

```
用途级别：⭐⭐⭐⭐⭐ 核心数据源
调用频率：每日定时拉取（非实时轮询）
存储策略：拉取后写入本地 DuckDB（阶段 2），缓存 1 小时
接入优先级：P0（第一优先级）
```

---

## 3. SoSoValue — 一站式投研平台

### 3.1 作用与价值

**一句话定位**：连接「宏观 ↔ 加密」的桥梁型平台。最大独特价值在 **现货 ETF 资金流向**（BTC/ETH ETF 的每日净流入/流出）——这是其他免费数据源做不到的。

**核心价值**：

| 投研问题 | SoSoValue 能回答 | 独特性 |
|:---------|:----------------|:------:|
| 美国机构通过 ETF 在买还是卖？ | BTC/ETH ETF 每日净流入/流出 | ⭐ 独一无二 |
| 哪些 ETF 发行商在吸筹？ | 按发行商拆解的 ETF 持仓 | ⭐ 独一无二 |
| 加密市场和各板块表现如何？ | 各赛道（L1/L2/DeFi/Meme）涨跌 | 中 |
| 当前宏观环境对加密有利吗？ | CPI、利率、DXY、黄金综合仪表盘 | 高（一站式） |
| 最近有什么重要事件？ | 精选加密新闻 + 投研报告 | 中 |

### 3.2 成本结构

| Tier | 价格 | 说明 |
|:-----|:----|:-----|
| **Free** | $0/月 | 基础数据，有限调用次数（约 100-500 req/day，实测待确认） |
| **Pro** | 联系销售 | 更高限额、高级端点、实时数据 |

⚠️ **当前处于「免费期」**，后续会上线付费 API。现在是接入和测试的好窗口。

### 3.3 API 拆解

**文档地址**：https://sosovalue.com/zh/developer

**Auth**：`Header: X-API-Key: <your_key>`

**已知端点（基于文档推导 + 网页结构分析）**：

```
Base: https://api.sosovalue.com （推测，需注册开发者账号后确认）

# ETF 数据（⭐ 最有价值的模块）
GET /api/v1/etf/flow           — BTC/ETH ETF 每日资金流向
GET /api/v1/etf/holdings       — 按发行商拆解的 ETF 持仓
GET /api/v1/etf/history        — ETF 历史流向时间序列

# 宏观数据
GET /api/v1/macro/indicators   — CPI / 利率 / DXY / 黄金综合仪表盘
GET /api/v1/macro/fomc         — FOMC 会议日历

# 市场数据
GET /api/v1/market/overview    — 总市值 / BTC 占比 / 成交量
GET /api/v1/sector/performance — 各赛道涨跌（L1/L2/DeFi/Meme/...）
GET /api/v1/token/{symbol}     — 单币数据

# 内容
GET /api/v1/news/feed          — 加密新闻精选
GET /api/v1/research/reports   — 投研报告列表
```

⚠️ **注意**：SoSoValue 的 API 文档为 JS 渲染页面，curl 无法直接抓取。需注册开发者账号后在浏览器中查看完整文档。

### 3.4 接入方式

```python
# 基础调用模板（端点需确认）
import requests

HEADERS = {"X-API-Key": "YOUR_API_KEY"}

# ETF 资金流向（最有价值）
etf = requests.get("https://api.sosovalue.com/api/v1/etf/flow", headers=HEADERS).json()
print(f"BTC ETF Net Flow: ${etf.get('btc_net_flow', 0):,.0f}")

# 宏观仪表盘
macro = requests.get("https://api.sosovalue.com/api/v1/macro/indicators", headers=HEADERS).json()

# 赛道表现
sectors = requests.get("https://api.sosovalue.com/api/v1/sector/performance", headers=HEADERS).json()
```

### 3.5 使用规范

- **ETF 数据是核心差异化价值**：如果只需要 ETF 流向，SoSoValue 是首选（比 CoinGlass ETF 端点更专注）
- 宏观数据可做交叉验证：SoSoValue 的 CPI/利率 vs FRED 原生数据
- 免费期结束后需要评估付费 API 性价比

### 3.6 投研 Agent 集成建议

```
用途级别：⭐⭐⭐⭐ 高价值补充
调用频率：每日 1 次（ETF 流向）+ 每周 1 次（宏观仪表盘）
接入优先级：P1（免费期内接入，付费后重新评估）
与 DeFiLlama 关系：互补（DeFiLlama = 链上，SoSoValue = 链下金融桥）
```

---

## 4. 恐贪指数 — 市场情绪量化

### 4.1 作用与价值

**一句话定位**：最简单的市场情绪量化指标，0-100 分值 + 文字定性，免费无限制。

**数据来源**：https://alternative.me/crypto/fear-and-greed-index/

**核心价值**：

- **反向指标**：极度恐慌（0-25）≈ 潜在底部；极度贪婪（75-100）≈ 潜在顶部
- **回测能力强**：`limit=0` 可获取自 2018 年 2 月以来的全部历史数据
- **零成本零认证**：完全公开，无 Key，无限速

**分类标准**：

| 分值区间 | 分类 |
|:--------|:-----|
| 0-25 | Extreme Fear（极度恐慌） |
| 26-46 | Fear（恐慌） |
| 47-54 | Neutral（中性） |
| 55-74 | Greed（贪婪） |
| 75-100 | Extreme Greed（极度贪婪） |

### 4.2 成本结构

| Tier | 价格 | 限速 |
|:-----|:----|:----|
| **免费** | $0 | ~30 req/min（非常宽松，官方未文档化具体限速） |
| 付费 | 无 | — |

**完全免费，无付费版本**。

### 4.3 API 拆解

**API 文档**：https://alternative.me/crypto/api/

**端点**：

```
GET https://api.alternative.me/fng/?limit={n}
```

**参数说明**：

| 参数 | 类型 | 说明 | 示例 |
|:-----|:----|:-----|:-----|
| `limit` | int | 返回条目数。`0`=全部（自 2018.02），`1`=最新（默认） | `?limit=30` 返回最近 30 天 |
| `format` | str | 输出格式：`json`（默认）或 `csv` | `?format=csv` |
| `date_format` | str | 日期格式：`world` / `cn` / `us` / `kr` | `?date_format=cn` |

**⚠️ 重要**：端点必须以 `/fng/` 结尾（末尾斜杠）。`/fng`（无斜杠）会触发 301 跳转，偶尔失败。

**响应示例**（已生产验证）：

```json
{
  "name": "Fear and Greed Index",
  "data": [{
    "value": "23",
    "value_classification": "Extreme Fear",
    "timestamp": "1782172800",
    "time_until_update": "47389"
  }],
  "metadata": {"error": null}
}
```

### 4.4 接入方式

```python
import requests
from datetime import datetime

# 最新恐贪指数（正确端点：末尾斜杠）
resp = requests.get("https://api.alternative.me/fng/", params={"limit": 1})
data = resp.json()["data"][0]
print(f"当前: {data['value']} ({data['value_classification']})")

# 最近 30 天历史（用于趋势分析）
resp = requests.get("https://api.alternative.me/fng/", params={"limit": 30})
history = resp.json()["data"]
for d in reversed(history):
    ts = datetime.fromtimestamp(int(d["timestamp"]))
    print(f"{ts.date()}: {d['value']} ({d['value_classification']})")

# 全部历史（用于回测）
resp = requests.get("https://api.alternative.me/fng/", params={"limit": 0})
all_data = resp.json()["data"]  # 自 2018-02-01 起
```

**Fallback**: web_search `"crypto fear and greed index today"`

### 4.5 使用规范

- **不要单独依赖**：恐贪指数是一个辅助指标，必须结合链上数据和价格走势使用
- **极端值更有意义**：恐慌/贪婪在极端区间（0-25 / 75-100）的信号价值远大于中性区间（47-54）
- **每天拉一次即可**：指数每日更新一次（UTC 00:00），无需高频轮询
- **搭配建议**：恐贪指数（情绪）+ DeFiLlama TVL（资金）+ Coinglass 清算（杠杆）≈ 完整的市场状态快照

### 4.6 投研 Agent 集成建议

```
用途级别：⭐⭐⭐ 辅助情绪指标
调用频率：每日 1 次
接入优先级：P0（零成本零障碍，当天即可接入）
```

---

## 5. BlockWorks Research — 机构级链上基本面

### 5.1 作用与价值

**一句话定位**：把「协议当公司看」的机构级链上基本面数据。提供类似股票分析的 P/S 比率、收入增长、费用结构等估值框架。

**核心价值**：

| 投研问题 | BlockWorks 能回答 | 对标传统金融 |
|:---------|:----------------|:-----------|
| 这个协议"贵不贵"？ | P/S 比率、P/F 比率 | 股票的 P/E、P/S |
| 协议收入在增长还是萎缩？ | 收入/Fee 时间序列 | 营收同比增长 |
| 哪些协议基本面最扎实？ | Screener（按 P/S、增速筛选） | 股票筛选器 |
| 各链活跃度如何？ | 29 条链的活跃地址、交易量 | — |
| 机构怎么看？ | 专业投研报告 | 卖方研报 |

### 5.2 成本结构

| Tier | 价格 | 限速 | 说明 |
|:-----|:----|:----|:-----|
| **Free** | $0/月 | 2,500 次/月（~83 次/天） | 当前处于「临时发布政策」期 |
| **Pro** | 联系销售 | 定制 | — |
| **Enterprise** | 定制 | 定制 | 实时数据 + SLA |

⚠️ **当前阶段**：刚启动，处于临时免费政策期。正式定价未来几个月公布。现在是免费测试的窗口期。

### 5.3 API 拆解

**文档地址**：https://docs.blockworksresearch.com/

**Auth**：`Header: X-API-Key: <key>` 或 `Authorization: Bearer <key>`

**Base URL**：`https://api.blockworksresearch.com/v1`

**已知端点**：

```bash
# === 协议数据 ===
GET /v1/protocols                    # 所有协议（136+）基础信息
GET /v1/protocols/{id}               # 单协议详情
GET /v1/protocols/{id}/metrics       # 时间序列指标（收入/费用/TVL）

# === 链数据 ===
GET /v1/chains                       # 29 条链表
GET /v1/chains/{id}/metrics          # 链级别活跃指标

# === 估值/基本面（⭐ 最有价值） ===
GET /v1/data/fundamentals/{protocol} # P/S 比率、P/F 比率、增长率

# === 市场发现 ===
GET /v1/market/screener              # 协议筛选器（按估值/增长）
GET /v1/market/trending              # 热门协议

# === 治理 ===
GET /v1/data/governance/{protocol}   # 治理提案

# === 研究 ===
GET /v1/research/reports             # 研报列表
GET /v1/research/reports/{id}        # 研报全文
```

**覆盖范围**：29 条链（BTC/ETH/SOL/Arbitrum/Base/HyperEVM 等）+ 136+ 个项目（Aave/Uniswap/Aerodrome 等）

### 5.4 接入方式

```python
import requests

HEADERS = {"X-API-Key": "YOUR_BLOCKWORKS_KEY"}
BASE = "https://api.blockworksresearch.com/v1"

# 1. 协议基本面（⭐ 最值钱端点）
fundamentals = requests.get(
    f"{BASE}/data/fundamentals/aave", headers=HEADERS
).json()
print(f"Aave P/S: {fundamentals.get('ps_ratio')}")
print(f"Aave Revenue Growth: {fundamentals.get('revenue_growth')}%")

# 2. 协议筛选器
screener = requests.get(
    f"{BASE}/market/screener",
    params={"sort_by": "ps_ratio", "order": "asc", "limit": 10},
    headers=HEADERS,
).json()

# 3. 链指标
chains = requests.get(f"{BASE}/v1/chains", headers=HEADERS).json()
for c in chains:
    print(f"{c['name']}: TVL=${c.get('tvl', 0):,.0f}")
```

### 5.5 使用规范

- **协议估值是核心差异**：DeFiLlama 给原始数据（TVL/交易量），BlockWorks 给分析后的数据（P/S 比率）
- 免费额度 2,500 次/月 ≈ 83 次/天，需规划调用节奏
- 覆盖项目 136 个，非全覆盖。不在覆盖列表的项目走 DeFiLlama
- 适合「周度协议基本面扫描」，不适合实时行情

### 5.6 投研 Agent 集成建议

```
用途级别：⭐⭐⭐⭐ 协议估值核心
调用频率：每周 1-2 次（周度基本面扫描）
接入优先级：P1（免费期接入，先占坑）
与 DeFiLlama 关系：互补（DeFiLlama = 原始数据，BlockWorks = 分析后数据）
```

---

## 6. rwa.xyz — RWA 赛道专精

### 6.1 作用与价值

**一句话定位**：RWA（Real World Assets）赛道唯一专精数据平台。代币化美债、私人信贷、大宗商品等现实资产上链后的全维度追踪。

**核心价值**：

| 投研问题 | rwa.xyz 能回答 |
|:---------|:-------------|
| 代币化美债规模在扩大还是缩小？ | AUM 趋势（如 BlackRock BUIDL、Ondo USDY） |
| 私人信贷真实违约率多少？ | 按协议的活跃贷款 + APY + 违约率 |
| RWA 赛道总量和增速？ | 各子赛道 TVL 汇总 |
| 哪个 RWA 发行商的信用风险最低？ | 按发行商拆解的 AUM + 底层资产 |
| 不同 RWA 协议的收益率对比？ | 各协议 APY 横向对比 |

**为什么独特**：DeFiLlama / CMC 等通用平台对 RWA 类资产的追踪非常粗糙（只标记为"RWA"类别，无细粒度数据）。rwa.xyz 是唯一一个把代币化资产的底层（美债/CUSIP/发行商/到期日）拆清楚的平台。

### 6.2 成本结构

| Tier | 价格 | 说明 |
|:-----|:----|:-----|
| **免费** | $0 | Web 仪表盘（可视化浏览，不可编程） |
| **API** | 联系销售 | 定制报价 |

⚠️ **API 是企业销售制**，无标准定价页面。适合「免费仪表盘人工查看 + 等待合适时机接入 API」。

### 6.3 数据类别

**客户端仪表盘覆盖**（非 API，是网页）：

```
代币化美债 (Tokenized Treasuries)
  ├─ BlackRock BUIDL（最大代币化美债基金）
  ├─ Ondo USDY
  ├─ Franklin Templeton FOBXX
  ├─ Hashnote USYC
  └─ 其他

私人信贷 (Private Credit)
  ├─ 活跃贷款总额
  ├─ 平均 APY
  ├─ 违约率
  └─ 按协议拆解（Maple, Centrifuge, Goldfinch...）

大宗商品 (Commodities)
  ├─ 代币化黄金：PAXG, XAUT
  ├─ 代币化白银
  └─ 其他

RWA 支持的稳定币
  ├─ USYC, USDY, USTB
  └─ 各稳定币底层资产穿透
```

### 6.4 接入方式

```python
# ⚠️ API 需联系销售获取 Key
# 以下为推测模板（待确认）

import requests

HEADERS = {"X-API-Key": "YOUR_RWA_KEY"}
BASE = "https://api.rwa.xyz/v1"  # 推测 Base URL

# Tokenized Treasury AUM
treasuries = requests.get(
    f"{BASE}/treasuries", headers=HEADERS
).json()

# Private Credit stats
credit = requests.get(
    f"{BASE}/private-credit", headers=HEADERS
).json()

# Commodities
commodities = requests.get(
    f"{BASE}/commodities", headers=HEADERS
).json()
```

**当前可用路径**：免费仪表盘 → 定期人工浏览 → 手动录入关键数据 → 等待 API 开放

### 6.5 使用规范

- **API 不是自助服务**：需要联系销售团队获取报价和 API Key
- **仪表盘目前免费**：可以定期人工查看，不适合自动化
- **RWA 赛道还在早期**：数据量和覆盖协议数有限，但增速快
- **与 DeFiLlama 的关系**：DeFiLlama 有 RWA 板块但很粗糙，rwa.xyz 是专精版

### 6.6 投研 Agent 集成建议

```
用途级别：⭐⭐⭐ RWA 赛道研究（低频但高价值）
调用频率：API 未接入前 — 每周人工浏览仪表盘
接入优先级：P2（等 API 公开或联系销售后接入）
备选方案：DeFiLlama RWA 板块 + CoinGecko RWA 分类（粗糙但可自动化）
```

---

## 7. Coinglass — 衍生品全维度

### 7.1 作用与价值

**一句话定位**：加密衍生品数据的行业标准。清算数据、资金费率、未平仓合约、期权持仓——所有「杠杆游戏」的数据都在这里。

**核心价值**（按投研重要性排序）：

| 投研问题 | Coinglass 能回答 | 信号意义 |
|:---------|:----------------|:--------|
| 多头是否在被屠杀？ | 实时清算数据（按币种、按交易所） | 恐慌/投降信号 |
| 市场是否过热？ | 资金费率（正极高 = 多头拥挤） | 反转预警 |
| 钱在流入还是流出交易所？ | Exchange Flow（净流入/流出） | 积累/分配 |
| 大户在做什么？ | 多空持仓比、大户账户比 | 聪明钱方向 |
| 期权市场怎么看？ | 期权 OI、Max Pain、PCR | 机构预期 |
| ETF 资金动向？ | BTC/ETH ETF 净流入 | 机构需求（替代 SoSoValue） |

### 7.2 成本结构

| Tier | 年费 | 月均 | 限速 | 适用场景 |
|:-----|:----:|:----:|:----:|:--------|
| **Free** | $0 | $0 | ~30 req/min | 开发测试 |
| **Basic** | **$3,588** | $299 | ~120 req/min | 个人投研/小型项目 |
| **Professional** | ~$8,400 | ~$700 | ~300 req/min | 专业交易/中型产品 |
| **Enterprise** | 定制 | 定制 | 定制 | 机构/高频 |

**免费版限制**：数据延迟、端点受限、历史深度有限。生产环境建议至少 Basic。

### 7.3 API 拆解

**文档地址**：https://www.coinglass.com/zh/CryptoApi

**Auth**：`Header: coinglassSecret: <key>` 或 Query Param `?apiKey=<key>`

**Base URL**：`https://api.coinglass.com`（推测，需注册后确认）

**核心端点**：

```bash
# ========================
# 🔴 期货数据（最核心）
# ========================

# 实时清算（⭐ 最重要的端点）
GET /api/v2/futures/liquidations
  → 按币种/交易所的爆仓金额（1h/4h/12h/24h）

# 未平仓合约（OI）
GET /api/v2/futures/openInterest
  → 按交易所/币种的 OI 及 OI 变化

# 资金费率（⭐ 市场过热信号）
GET /api/v2/futures/fundingRate
  → 各币种当前资金费率（正=多头付空头）

# 多空比
GET /api/v2/futures/longShortRatio
  → 账户多空比 + 持仓多空比

# OI 历史
GET /api/v2/futures/openInterestHistory
  → OI 时间序列（5m / 15m / 1h / 4h / 1d）

# ========================
# 🟡 期权数据
# ========================

GET /api/v2/options/openInterest    # 期权 OI（call/put 拆解）
GET /api/v2/options/maxPain         # Max Pain 价位
GET /api/v2/options/volume          # 期权成交量

# ========================
# 🟡 资金流向数据
# ========================

GET /api/v2/exchange/flow           # 交易所净流入/流出（Spot + Derivatives）

# ========================
# 🟡 市场/情绪
# ========================

GET /api/v2/market/globalLongShortAccountRatio   # 全球账户多空比
GET /api/v2/etf/flow                             # ETF 资金流向
GET /api/v2/market/fearAndGreed                  # Coinglass 自有情绪指数
```

### 7.4 接入方式

```python
import requests

API_KEY = "YOUR_COINGLASS_KEY"
BASE = "https://api.coinglass.com"  # 待确认

# 1. 24h 清算数据（⭐ 核心）
liq = requests.get(
    f"{BASE}/api/v2/futures/liquidations",
    headers={"coinglassSecret": API_KEY},
    params={"symbol": "BTC", "range": "24h"},
).json()
print(f"BTC 24h 清算: Long ${liq.get('longLiquidations', 0):,.0f} | Short ${liq.get('shortLiquidations', 0):,.0f}")

# 2. BTC 资金费率
funding = requests.get(
    f"{BASE}/api/v2/futures/fundingRate",
    headers={"coinglassSecret": API_KEY},
    params={"symbol": "BTC"},
).json()
print(f"BTC Funding Rate: {funding.get('rate', 0):.4%}")

# 3. BTC OI
oi = requests.get(
    f"{BASE}/api/v2/futures/openInterest",
    headers={"coinglassSecret": API_KEY},
    params={"symbol": "BTC"},
).json()
print(f"BTC Open Interest: ${oi.get('openInterest', 0):,.0f}")
```

### 7.5 使用规范

- **清算数据是 Coinglass 的"护城河"**：全市场独此一家能覆盖 100+ 交易所的实时清算
- **资金费率极度正向 = 危险信号**：历史上 BTC 资金费率 >0.1%（8h）时，短期回调概率大增
- **Exchange Flow 有滞后**：不是实时流，有 5-15 分钟延迟
- **免费版仅开发测试**：数据不完整且有延迟，生产环境走 Basic 以上
- **WebSocket 需 Enterprise**：实时推送仅在最高 tier

### 7.6 投研 Agent 集成建议

```
用途级别：⭐⭐⭐⭐⭐ 衍生品核心数据
调用频率：免费版 — 每日 2-4 次关键查询 / 付费版 — 每小时
接入优先级：P2（免费版先接入开发测试 → 预算到位后升级 Basic）
替代方案：Binance Futures API（资金费率/OI，免费但限于 Binance）
```

---

## 8. CoinMarketCap — 行情与市值基准

### 8.1 作用与价值

**一句话定位**：加密资产行情的"彭博终端"。最全的代币覆盖（2万+）、最标准化的市值排名体系、最广泛使用的行业基准。

**核心价值**：

| 投研问题 | CMC 能回答 | 独特性 |
|:---------|:----------|:------:|
| 整个市场多大？BTC 占比多少？ | 总市值、BTC.D、ETH.D、稳定币市值 | 行业标准 |
| 任意代币的实时价格？ | 2万+ 代币实时报价 | ⭐ 最全 |
| 哪些币在涨/跌？ | 24h 涨跌榜（gainers-losers） | ⭐ CMC 独家 |
| 这个币的流通量和最大供应？ | 流通供应 / 总供应 / 最大供应 | ⭐ 最准 |
| 这个项目的官网/白皮书/社交？ | 完整 Metadata | 中 |
| 链上基础数据？ | 哈希率、交易量、活跃地址（v2 区块链端点） | 中 |

### 8.2 成本结构（Credit 体系）

| Tier | 月费 | **年费** | Credits/月 | 速率 | 适用场景 |
|:-----|:----:|:-------:|:---------:|:----:|:--------|
| **Basic（免费）** | $0 | $0 | 10,000 | 30/min | ✅ 个人/开发 |
| **Hobbyist** | $79 | **$948** | 40,000 | 60/min | 小型项目 |
| **Standard** | $349 | **$4,188** | 200,000 | 120/min | 专业投研 |
| **Professional** | $849 | **$10,188** | 1,000,000 | 300/min | 机构/产品 |
| **Enterprise** | 定制 | 定制 | 定制 | 定制 | 大型平台 |

**Credit 消耗参考**：

| 端点 | Credits/次 | 说明 |
|:-----|:----------:|:-----|
| `/cryptocurrency/map` | 1 | 最便宜，映射用 |
| `/cryptocurrency/quotes/latest` | 2 | 实时报价 |
| `/cryptocurrency/listings/latest` | 3 | 排行列表 |
| `/cryptocurrency/categories` | 2 | 板块分类 |
| `/global-metrics/quotes/latest` | 1 | 全局指标 |
| `/blockchain/statistics/latest` | 3 | 链上统计 |
| `/cryptocurrency/quotes/historical` | 10+ | 历史数据（最贵） |
| `/cryptocurrency/metadata` | 2 | 项目详情 |

**免费版 (10,000 credits) ≈ 3,000-5,000 次简单调用/月**。

### 8.3 API 拆解

**文档地址**：https://coinmarketcap.com/api/documentation/v1/

**Auth**：`Header: X-CMC_PRO_API_KEY: <key>` 或 Query Param `?CMC_PRO_API_KEY=<key>`

**Base URL**：
- **生产**：`https://pro-api.coinmarketcap.com` ← 真实数据 ✅
- **沙盒**：`https://sandbox-api.coinmarketcap.com` ← ⚠️ 伪造数据！仅用于测试字段结构

⚠️ **重要**：沙盒环境返回的数据是伪造的（如 BTC.D 显示 0.18%，明显异常）。**永远不要用沙盒数据做分析！**

**核心端点（v1 / v2）**：

```bash
# ========================
# 🔴 加密货币端点（v1）
# ========================

# 市值排行（⭐ 最常用）
GET /v1/cryptocurrency/listings/latest?limit=100&sort=market_cap
  → cmc_rank, price, market_cap, volume_24h, percent_change_1h/24h/7d/30d/60d/90d,
    circulating_supply, total_supply, max_supply

# 实时报价（⭐ 批量查价）
GET /v1/cryptocurrency/quotes/latest?symbol=BTC,ETH,SOL
  → price, market_cap, volume_24h, percent_change_*, fully_diluted_market_cap

# 历史数据（⚠️ 最贵，10+ credits）
GET /v1/cryptocurrency/quotes/historical?symbol=BTC&time_start=...&interval=1d

# 项目元数据
GET /v1/cryptocurrency/metadata?symbol=BTC
  → logo, description, website, twitter, reddit, technical_doc, tags

# ID 映射
GET /v1/cryptocurrency/map?symbol=BTC,ETH  # 1 credit

# 板块分类
GET /v1/cryptocurrency/categories          # 所有板块列表 + 市值
GET /v1/cryptocurrency/category?id=...     # 某板块下币种列表

# ⭐ CMC 独家：热门币种 + 涨跌榜
GET /v1/cryptocurrency/trending/latest      # 热门搜索
GET /v1/cryptocurrency/trending/gainers-losers  # 24h涨跌榜

# ========================
# 🔴 全局指标（v1）
# ========================

GET /v1/global-metrics/quotes/latest
  → btc_dominance, eth_dominance, total_market_cap, total_volume_24h,
    stablecoin_market_cap, altcoin_market_cap, defi_market_cap,
    derivatives_volume_24h, active_cryptocurrencies

# ========================
# 🟡 交易所端点（v1）
# ========================

GET /v1/exchange/listings/latest       # 交易所排行（按成交量）

# ========================
# 🟡 区块链端点（v2）
# ========================

GET /v2/blockchain/statistics/latest?symbol=BTC  # 哈希率、交易量、活跃地址

# ========================
# 🟢 账户管理
# ========================

GET /v1/key/info   # 查询 API Key 使用情况（剩余 credits、速率限制）
```

**响应头中的限速信息**（每次请求返回）：

```
X-Ratelimit-Limit-Minute: 30
X-Ratelimit-Remaining-Minute: 28
X-Credits-Limit-Month: 10000
X-Credits-Remaining-Month: 8723
```

### 8.4 接入方式

```python
import requests

API_KEY = "YOUR_CMC_PRO_API_KEY"
HEADERS = {"X-CMC_PRO_API_KEY": API_KEY}
BASE = "https://pro-api.coinmarketcap.com"

# 1. 全局市场快照（1 credit）
global_data = requests.get(
    f"{BASE}/v1/global-metrics/quotes/latest", headers=HEADERS
).json()
quote = global_data["data"]["quote"]["USD"]
print(f"总市值: ${quote['total_market_cap']:,.0f}")
print(f"BTC 占比: {quote['btc_dominance']:.1f}%")
print(f"稳定币市值: ${quote['stablecoin_market_cap']:,.0f}")
print(f"DeFi 市值: ${quote['defi_market_cap']:,.0f}")

# 2. Top 10 市值排行（3 credits）
listings = requests.get(
    f"{BASE}/v1/cryptocurrency/listings/latest",
    headers=HEADERS,
    params={"limit": 10, "sort": "market_cap"},
).json()
for coin in listings["data"]:
    p = coin["quote"]["USD"]
    print(f"#{coin['cmc_rank']} {coin['symbol']}: ${p['price']:.2f} "
          f"(MCap ${p['market_cap']:,.0f} | 24h {p['percent_change_24h']:.1f}%)")

# 3. 24h 涨跌榜（CMC 独家）
gainers_losers = requests.get(
    f"{BASE}/v1/cryptocurrency/trending/gainers-losers", headers=HEADERS
).json()
print("Top Gainers 24h:")
for g in gainers_losers["data"]["gainers"][:5]:
    print(f"  {g['symbol']}: +{g['quote']['USD']['percent_change_24h']:.1f}%")

# 4. Key 信息查询（不消耗 credits）
key_info = requests.get(
    f"{BASE}/v1/key/info", headers=HEADERS
).json()
print(f"本月剩余: {key_info['data']['usage']['current_month']['credits_left']} credits")
```

### 8.5 使用规范

- **⚠️ 沙盒 vs 真实**：沙盒 (`sandbox-api`) 返回伪造数据，**仅用于字段结构测试**
- **Credit 预算管理**：10,000 credits/月 = ~333 credits/天。每次调用 >3 credits 的端点需谨慎
- **历史数据最贵**：`/quotes/historical` 10+ credits/次，仅在必要时调用
- **批量优于单次**：`/quotes/latest?symbol=BTC,ETH,SOL` 一次 2 credits vs 三次 6 credits
- **CMC vs CoinGecko 分工**：
  - CMC 胜在 `global-metrics` 细粒度、`gainers-losers`（独家）、多周期涨跌幅
  - CoinGecko 胜在免费无需 Key、板块/叙事分类更好、衍生品交易所端点
  - **策略**：CoinGecko 做主力（免费且不限 credits），CMC 做辅助（补充 CMC 独家端点）
- **汇率转换要加钱**：每个请求只支持 1 种报价货币转换

### 8.6 投研 Agent 集成建议

```
用途级别：⭐⭐⭐⭐⭐ 核心行情基准
调用频率：每日 2-3 次（global-metrics + listings + gainers-losers）
每月消耗：约 300-500 credits（合理）
接入优先级：P0（已激活 Free Basic Key ✅）
配合：CoinGecko 做主力（免费）、CMC 补充（独家端点）
```

---

## 9. 综合对比与推荐组合

### 9.1 七源总览

| # | 数据源 | 定位 | 免费额度 | 最低付费 | Auth | 独有护城河 |
|:-:|:------|:----|:--------|:--------|:----|:----------|
| 1 | **DeFiLlama** | DeFi 全景 | ✅ 无限制 | $3,000/月 | 无 | 200+ 链 TVL 全貌、DEX 总览 |
| 2 | **SoSoValue** | 加密 ↔ 宏观桥 | ✅ 有（限） | 联系销售 | API Key | BTC/ETH ETF 资金流向 |
| 3 | **恐贪指数** | 市场情绪 | ✅ 无限制 | 无 | 无 | 零成本情绪量化 |
| 4 | **BlockWorks** | 协议基本面 | ✅ 2,500/月 | 联系销售 | API Key | P/S 比率、协议估值 |
| 5 | **rwa.xyz** | RWA 专精 | ⚠️ 仅仪表盘 | 联系销售 | API Key | 代币化美债穿透 |
| 6 | **Coinglass** | 衍生品全维度 | ⚠️ 有限 | **$3,588/年** | API Key | 全市场实时清算 |
| 7 | **CMC** | 行情基准 | ✅ 10k credits | **$948/年** | API Key | 2万+代币覆盖、涨跌榜 |

### 9.2 数据源职能矩阵

| 投研场景 | 首选数据源 | 备选数据源 | 交叉验证 |
|:---------|:----------|:----------|:--------|
| 链上资金流向 | **DeFiLlama** /chains | BlockWorks /chains/{id}/metrics | — |
| 协议估值 | **BlockWorks** /fundamentals | DeFiLlama /overview/fees | 手动 P/S 反算 |
| 市场情绪 | **恐贪指数** | Coinglass 情绪 | — |
| 杠杆健康度 | **Coinglass** 清算+费率 | Binance API 费率 | — |
| ETF 机构流向 | **SoSoValue** | Coinglass ETF | — |
| 代币行情 | **CMC** / CoinGecko | — | 双源对比 |
| RWA 赛道 | **rwa.xyz** 仪表盘 | DeFiLlama RWA | — |
| DeFi 收益 | **DeFiLlama** /yields | — | 协议官网 |

### 9.3 推荐组合（按预算）

#### 🟢 免费组合（$0/月）— 可立即接入

```
DeFiLlama（TVL/DEX/收益/稳定币）
+ 恐贪指数（情绪）
+ CMC Basic（行情/市值/涨跌榜）
+ BlockWorks Free（协议估值）
+ SoSoValue Free（ETF 流向）
+ rwa.xyz 仪表盘（人工查看）
────────────────────
覆盖：90% 投研场景
缺口：衍生品清算/费率（需 Binance API 补充）
总成本：$0/月
```

#### 🟡 入门付费组合（~$380/月）— 补齐衍生品

```
免费组合
+ Coinglass Basic（$299/月，衍生品完整数据）
────────────────────
覆盖：95% 投研场景
缺口：高精度协议估值（BlockWorks Pro）/ RWA API
总成本：~$3,588/年
```

#### 🔴 专业组合（~$1,200/月）— 生产级投研

```
Coinglass Pro（$700/月）
+ CMC Standard（$349/月）
+ BlockWorks Pro（联系销售）
+ SoSoValue Pro（联系销售）
+ 免费层全保留
────────────────────
总成本：~$14,000+/年
```

### 9.4 决策树：何时接入哪个

```
需要 DeFi 数据？
├─ TVL / DEX / 稳定币 → DeFiLlama ✅ 免费
├─ 协议估值 P/S 比率 → BlockWorks ✅ 免费 2,500/mo
├─ 代币化美债 / RWA → rwa.xyz ⚠️ 仪表盘（API 待销售）
└─ 收益池 / APY → DeFiLlama /yields ✅ 免费

需要市场数据？
├─ 实时行情 / 市值排行 → CMC ✅ 免费 10k credits
├─ 24h 涨跌榜 → CMC gainers-losers ✅ CMC 独家
├─ ETF 资金流向 → SoSoValue ✅ 免费（暂时）
└─ 恐贪指数 → alternative.me ✅ 免费无限

需要衍生品数据？
├─ 清算 / 资金费率 / OI → Coinglass ⚠️ 免费有限 → Basic $299/月
└─ 仅 Binance 费率 → Binance Futures API ✅ 免费

需要宏观数据？
├─ CPI / 利率 / DXY / 黄金 → SoSoValue / FRED
└─ 美债收益率 → FRED ✅ 免费
```

---

## 10. 数据采集策略

### 10.1 分层采集频率

| 频率 | 数据源 | 端点 | 目的 |
|:----:|:------|:-----|:-----|
| **每日 1 次** | DeFiLlama | `/chains`, `/overview/dexs`, `/stablecoins` | 链上资金流向日监控 |
| **每日 1 次** | CMC | `/global-metrics`, `/listings/latest` | 市场结构快照 |
| **每日 1 次** | 恐贪指数 | `/fng/` | 情绪锚点 |
| **每日 1 次** | SoSoValue | ETF flow | 机构流向 |
| **每小时** | CMC | `/quotes/latest` (watchlist) | 关键标的价格刷新 |
| **每 8 小时** | Coinglass | 资金费率（BTC/ETH） | 市场过热监控 |
| **每周 1 次** | BlockWorks | 协议估值 scanner | 周度基本面扫描 |
| **每周 1 次** | rwa.xyz | 仪表盘 | RWA 赛道周度监测 |

### 10.2 降级链（每个数据源的 Fallback）

```
DeFiLlama 不可用 → CoinGecko /global + /coins/categories
CMC 不可用     → CoinGecko /coins/markets
恐贪指数 不可用 → Google Trends "bitcoin"
SoSoValue 不可用 → Coinglass ETF endpoint / web_search
BlockWorks 不可用 → 手动 P/S = DeFiLlama fees / Token Terminal
Coinglass 不可用 → Binance API（仅 Binance 数据，覆盖率下降）
rwa.xyz 不可用  → DeFiLlama RWA 板块 + web_search
```

### 10.3 存储规范

```
阶段 1（当前）：拉取后标注来源和时间，以 JSON 写入临时文件
阶段 2（计划）：拉取 → 写入 DuckDB → 数据层统一 SQL 查询接口
阶段 3（远期）：DuckDB + 回测引擎 + 因子化指标体系
```

### 10.4 数据质量标注规范

每条数据必须附带：

```python
{
    "value": 123456789,
    "source": "DeFiLlama",
    "endpoint": "/chains",
    "fetched_at": "2026-06-23T08:00:00Z",
    "confidence": "high",  # high / medium / low / stub
    "notes": ""  # 如有已知偏差在此标注
}
```

---

## 附录：已注册数据源代码（data-module 对应编号）

| # | 数据源 | 状态 | data-module 编号 |
|:-:|:------|:----|:---------------:|
| 1 | CoinGecko | 🟢 已接入 | #1 |
| 2 | CMC | 🟢 已接入（Basic Key ✅） | #2 |
| 3 | Binance Futures | 🟢 已接入 | #3 |
| 4 | **DeFiLlama** | 🟢 已接入 | #4 |
| 5 | **恐贪指数 (alternative.me)** | 🟢 已接入 | #5 |
| 6 | LookIntoBitcoin | ❌ 已迁移（BM Pro 付费墙） | #6 |
| 7 | PANews | 🟢 已接入 | #7 |
| 8 | FRED | 🟢 已接入（Key ✅） | #8 |
| 9 | Yahoo Finance | 🟢 已接入 | #9 |
| 10 | Trading Economics | 🟡 可用（浏览器） | #10 |
| 11 | CME FedWatch | 🟡 可用（浏览器） | #11 |
| 12 | **Coinglass** | 🟡 浏览器 + API（待付费） | #12 |
| 13 | WhaleAlert | 💎 付费 | #13 |
| 14 | RootData | 🟢 已接入（Basic ✅） | #14 |
| 15 | **BlockWorks Research** | 🟢 已接入（免费期） | #15 |
| 16 | SEC EDGAR | 🟢 已接入 | #16 |
| 17 | CryptoQuant | 💎 付费（$399+/月） | #17 |

---

> **编制人**：Cage Agent OS 数据模块 | **最后更新**：2026-06-23  
> **下次复审**：2026-07-23（评估接入进度 + 免费期到期状态 + 新数据源候选）  
> **关联文档**：`~/.hermes/skills/research/data-module/SKILL.md`（全局数据源注册表 + 生产环境实测经验）
