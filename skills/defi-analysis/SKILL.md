---
name: defi-analysis
description: |
  DeFi 项目研究与估值框架 — 适用于 Jito、Hyperliquid、Aave 等各类 DeFi 协议。
  四维基本面拆解(需求/供给/收入/代币经济) + 三层估值法(同业对标→架构溢价→TAM替代)
  + MCap/TVL 交叉验证 + 代际分类(Gen1/2/3)。含 DeFiLlama 数据获取最佳实践与已知陷阱。
category: research
---

# DeFi Project Research & Valuation Framework

> DeFi 项目研究与估值框架模板。适用于各类 DeFi 协议：Lending / DEX / LSD / Perp DEX / Yield Aggregator / 衍生品。

## 触发条件

- 用户要求研究 / 分析某个 DeFi 协议
- 用户要求给 DeFi 项目估值
- 用户问某个 DeFi 赛道 / 协议基本面怎么看
- 用户比较多个 DeFi 项目（如同一赛道不同代际）

---

## 完整分析框架

### 一、项目定位

**赛道判断**
- 什么类型：Lending / DEX / LSD / Perp DEX / Yield Aggregator / 衍生品 / 保险 / 治理…
- 链：Ethereum / Solana / BSC / 跨链…
- 核心价值捕获：手续费 / 质押收益 / MEV / 治理价值 / 流动性激励…

**一句话定位**
> 解决了什么问题，竞争对手是谁，凭什么能赢

---

### 二、基本面四维拆解

#### 2.1 需求侧 — 真实需求还是刷量？

| 维度 | 看什么 | 数据来源 |
|---|---|---|
| 用户数 | DAU / MAU / 活跃地址趋势 | Dune / 链上 |
| 留存 | 30d/90d 用户留存率 | 自行统计 / Messari |
| 手续费来源 | 真实交易 vs 套利 vs 刷量 | 链上TX拆分 |
| 订单簿深度 | 真实流动性 | DEX页面 / DeFiLlama |

**核心问题**：去掉激励和套利后，还有多少真实用户？

#### 2.2 供给侧 — TVL 与市场份额

| 维度 | 看什么 | 数据来源 |
|---|---|---|
| TVL | 当前总量 / 历史趋势 | DeFiLlama |
| 赛道天花板 | 链上总锁仓 / 赛道渗透率 | 链上总TVL |
| 市场份额 | TVL占比 / 手续费占比 | DeFiLlama |
| 跨链布局 | 多链TVL分布 | DeFiLlama |

**核心问题**：赛道渗透率到顶了吗？还能增长几倍？

#### 2.3 协议收入 — 真金白银

| 维度 | 看什么 | 数据来源 |
|---|---|---|
| Fees | 协议产生的总手续费 | DeFiLlama / Dune |
| Protocol Revenue | 协议实际留存收入 | Token Terminal / Messari |
| Real Yield | staker/流动性提供者拿到的实际收益 | 链上 / Dune |
| 收入增长率 | QoQ / YoY | 自行计算 |
| **Incentives** | 代币补贴是否为零？ | DeFiLlama |

**核心问题**：谁拿走了收入？团队抽成比例是多少？**Incentives=0 是极度稀缺的正面信号**——意味着协议收入是真实利润而非补贴刷量。

#### 2.4 代币经济 — 供需结构

| 维度 | 看什么 | 数据来源 |
|---|---|---|
| 总供应量 | 固定 vs 通胀 | 白皮书 |
| 流通量 | 当前流通 / 解锁时间表 | CoinGecko / 白皮书 |
| 分配结构 | 团队 / 投资者 / 社区 / 国库 | 白皮书 / 链上 |
| 质押机制 | 质押量 / 质押收益率 / 质押率 | 链上 |
| 销毁/回购 | 是否有收入销毁机制 | 白皮书 |

**核心问题**：解锁是线性还是悬崖？质押消耗了多少流通？

---

### 三、估值框架

#### 3.1 核心估值倍数

| 倍数 | 公式 | 适用场景 |
|---|---|---|
| P/S (FDV basis) | FDV / Revenue | 通用 |
| P/Fees | FDV / Fees | 手续费协议 |
| EV/Revenue | EV / Revenue | 对标传统金融 |
| P/S (MCap basis) | MCap / Revenue | 保守估值 |
| Price/TVL | 代币价格 / TVL share | LSD协议 |

#### 3.2 三层估值法（跨类别协议适用）

某些协议横跨多个资产类别（如 Hyperliquid: Perp DEX + L1 + CEX 挑战者），单一赛道对标会严重低估或高估：

**第一层：同赛道估值底线**
- 找 3-5 个同赛道直接竞品（同类型、同代际）
- 用 P/S、MCap/TVL 锚定估值下限
- 如果目标标的估值远高于此层 → 说明市场在额外定价某些溢价

**第二层：架构/叙事溢价评估**
- 找出目标标的的"第二重身份"对应的赛道对标池
- 评估溢价是否合理：技术差异化 / 品牌 / 先发优势 / 飞轮效应
- 常用溢价因子：L1 溢价、transparency premium、网络效应溢价
- 关键：要量化推演溢价的合理性

**第三层：TAM 替代推演（上行空间）**
- 计算目标标的正在替代的现有市场的总规模
- 用渗透率分段推演：3% → 5% → 10% → 20%
- 这个场景是"期权价值"，不纳入保守估值

#### 3.3 MCap/TVL 交叉验证

| MCap/TVL | 判断 |
|---|---|
| < 1x | 被低估/被市场抛弃（如 Lighter 0.43x） |
| 1-3x | 典型 DeFi 应用估值（Aster 1.8x, dYdX 1.5x） |
| 3-10x | 有 L1/平台溢价（Hyperliquid 5-7x） |
| > 10x | 高溢价或泡沫，需谨慎 |

#### 3.4 场景估值

| 场景 | 市场情绪 | 典型 P/Revenue |
|---|---|---|
| 极度悲观 | 熊市底部 / 协议濒死 | 10-20x |
| 保守 | 正常DeFi估值 | 30-50x |
| 合理 | 赛道龙头溢价 | 60-100x |
| 乐观 | 牛市叙事 / 高速增长 | 100-200x |
| 疯狂 | Meme / 无理性繁荣 | 500x+ |

---

### 四、代际分类

同一赛道内出现代际分化时，估值逻辑完全不同：

| 代际 | 架构 | 典型项目 | 估值逻辑 | P/S 区间 |
|---|---|---|---|---|
| Gen 1 | 通用链上应用/vAMM | dYdX, GMX, SNX | DeFi 应用倍数 | 15-30x |
| Gen 2 | 自研链/定制化 L1 | Hyperliquid | L1 溢价 + CEX 挑战 | 50-150x |
| Gen 3 | 新一代高性能/模块化 | Aster, Lighter | 追赶者折扣，需看数据 | TBD |

**分析时先判断标的属于第几代——同一代内的对标才有意义。**

---

### 五、关键变量清单

#### 催化因素（向上）
- [ ] 链上TVL增长 / 赛道渗透率提升
- [ ] 协议收入连续增长（QoQ>20%）
- [ ] 代币解锁完成，抛压出清
- [ ] 牛市中给更高倍数
- [ ] 新产品 / 合作 / 头部CEX上线
- [ ] 治理提案通过，机制优化

#### 风险因素（向下）
- [ ] 代币解锁线性抛压（算清楚每月砸多少）
- [ ] 竞争者出现 / 市场份额下滑
- [ ] 激励停止后用户留存率低
- [ ] 链价格下跌 / DeFi系统性风险
- [ ] 团队/投资人大额解锁砸盘
- [ ] 智能合约安全风险（TVL归零）

---

### 六、研究流程

```
1. 项目定位 → 赛道 + 链 + 核心机制
2. 拉数据 → TVL / Fees / Revenue / 代币供应
3. 填框架 → 四维基本面 + 关键变量
4. 给估值 → 三种场景（悲/中/乐）
5. 列催化/风险 → 决策依据
6. 结论 → 一句话投资逻辑
```

---

### 七、数据获取常用API

```bash
# CoinGecko 代币行情
curl -s "https://api.coingecko.com/api/v3/coins/{id}?localization=false&tickers=false&community_data=false&developer_data=false&sparkline=false"

# DeFiLlama TVL / 协议信息
curl -s "https://api.llama.fi/protocol/{protocol-name}"

# DeFiLlama Fees（部分协议有——⚠️ 经常不可靠）
curl -s "https://api.llama.fi/overview/fees/{protocol-name}"

# DeFiLlama Revenue
curl -s "https://api.llama.fi/protocol/{protocol-name}/revenue"

# 多协议对比价格
curl -s "https://api.coingecko.com/api/v3/simple/price?ids={id1,id2}&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true"
```

---

## ⚠️ 常见陷阱

| 陷阱 | 说明 |
|---|---|
| TVL虚高 | 激励砸出来的，激励停了就崩 |
| Fees刷量 | DEX订单簿深度差，实际交易少 |
| 混淆Fees和Revenue | $100M Fees，Protocol Revenue可能只有$5M |
| 忽略代币通胀 | 供应量年增20%，价格再涨也被稀释 |
| 解锁时间表不看 | 解锁是线性还是悬崖，差很多 |
| 用MCap而不是FDV | 流通少的时候MCap失真 |
| 牛市给高倍数当常态 | 熊市P/Revenue可能跌80% |
| 跨协议混为一谈 | 同一赛道出现代际分化（Gen1/2/3），架构不同估值逻辑完全不同 |
| 只用一个对标池 | 跨类别项目必须用三层估值法交叉验证 |
| **DeFiLlama fees端点不可靠** | `/overview/fees/{protocol}` 经常返回 Internal Server Error 或空数据。不要假定能拿到 fees/revenue 数据 |
| **忽略 Incentives 信号** | Incentives=$0（零代币补贴）= 协议收入是真实利润而非补贴刷量——这是极度稀缺的正面信号 |

### DeFiLlama 费用数据 fallback 策略

| 优先级 | 方案 | 适用场景 |
|:----:|:----|:--------|
| 🥇 | **直接询问用户** | 用户可能有协议官方 dashboard 或 Dune 数据 |
| 🥈 | **Token Terminal** | 免费版可查部分协议的基础收入数据 |
| 🥉 | **web_search** | 搜索 "{Protocol} annualized revenue" |
| 4 | **从 TVL 反推估算** | TVL × 行业平均利差率 × 协议抽成率 → 仅作粗略参考，必须标注"估算" |

### Incentives=0 的估值溢价

- **不是所有 DeFi 协议都有这个特质**——大多数用代币补贴刷 TVL
- 零激励 + 正收入 = **协议有真实 PMF**，不是靠补贴存活
- 在场景估值中应给 **10-20% 的质量溢价**（体现在 P/S 倍数上移）

---

## 输出标准

当用户要求分析某个DeFi项目时，输出：
1. **项目定位**（一句话）
2. **基本面数据表**（四维填满，有数据填数据，无数据标"待查"）
3. **估值区间**（悲观/合理/乐观三种场景，给具体数字）
4. **核心催化 / 核心风险**（各列3-5条）
5. **结论**（一句话投资逻辑）
