---
name: crypto-stock-analysis
description: |
  币股分析框架 — 覆盖 MSTR/STRC/STRF/COIN/MARA/RIOT/CLSK 等加密关联美股及优先股。
  不同于传统美股分析，核心驱动因子是 BTC 价格、mNAV、可转债结构、矿机成本、
  加密周期 β 等加密原生变量。含 Saylor 融资操作(STRC/STRF/可转债)分析。
  三层分析模式 + 与传统美股框架的对照表。⚠️ 问 STRC 必须加载此 skill。
category: research
---

# Crypto Stock Analysis

> 币股不是传统科技股，也不是纯 crypto。它是两者的杂交品种——用美股的估值语言讲 crypto 的故事。

## 何时触发

- 分析 MSTR/COIN/MARA/RIOT/CLSK/IREN/BITF/HUT 等币股
- 用户问「MSTR 现在怎么样」「COIN 为什么不跟 BTC 涨」「矿企 PE 为什么这么低」
- 对比币股 vs 直接持有 BTC/ETH 的优劣
- 分析 Saylor 的融资操作（STRC/STRF/可转债）
- ⚠️ 需要宏观环境判断 → 同时加载 macro-analysis
- ⚠️ 需要 BTC 链上/市场数据 → 同时加载 crypto-analysis
- ⚠️ 需要传统估值对比 → 同时加载 us-stock-analysis

## ⚠️ 步骤 0：标的解构（强制执行，不可跳过）

在对任何币股进行估值或预测之前，**必须先用 RAG + web 搜索完成以下解构**：

1. **标的身份**：这个 ticker 对应的金融工具到底是什么？（普通股？优先股？永续？有到期日？可转换？）
2. **现金流机制**：钱从哪来？支付给谁？是固定还是浮动？由谁决定何时调整？——**这是最易出错的一步**
3. **定价机制**：价格由市场供求决定，还是存在主动锚定机制（如发行人承诺维持 par）？
4. **控制权**：谁有权改变关键参数？这些权力在实际中是否被使用过？

完成后标注：
```
[标的解构] 身份: ... | 现金流: ... | 定价: ... | 控制权: ...
```

⚠️ **不完成这一步，禁止进入估值/预测环节。** 这是系统级纪律，不是建议。

## 币股分类与驱动因子

| 类别 | 代表 | 核心驱动因子 | 传统估值陷阱 |
|:-----|:-----|:-----------|:-----------|
| **BTC 杠杆 proxy** | MSTR | mNAV / 可转债稀释 / BTC 价格 / STRC 股息机制 | PE/PB/PEG 全部无意义——伪装成软件公司的 BTC 买入机器 |
| **交易所/券商** | COIN | 交易量 × 费率 / USDC 利息收入 / 监管 / Base 链生态 | PE 在牛市被交易量放大低估，熊市被放大高估 |
| **矿企** | MARA/RIOT/CLSK | BTC 价格 / 全网算力 / 电力成本 / 减半周期 / CAPEX | Fwd PE < 5x 是周期顶部陷阱 |

---

## 核心概念速查

### mNAV（Market-to-Net Asset Value）= 市值 / BTC 持仓价值

```
mNAV > 2x   — 市场极度看好 Saylor 的融资飞轮（机构溢价）
mNAV 1-2x   — 正常区间
mNAV = 1x   — 市价 = BTC 持有价值。买 MSTR = 直接买 BTC
mNAV < 1x   — 🔴 市场认为 MSTR 的负债/稀释 > BTC 价值
```

### STRC — Saylor 的固收化融资工具

- 目标面值 $100 的永续优先股，每月浮动股息
- 核心矛盾：看起来像货币市场基金，但信用风险 = 单一公司 BTC 持仓
- **死亡螺旋条件**：mNAV < 1x 连续 4 周 + BTC 持续低于关键支撑位

### 可转债稀释 — MSTR 的隐性成本

- 每轮可转债 ≈ 5-8% 稀释（过去 12 个月三笔 ≈ 18%）
- 不在 PE/PB 里显示——只盯着 PE 完全看不到这个成本

---

## 步骤 1：数据收集

### 通用币股数据

用 `financial.quote.verified` 获取交叉验证后的估值指标，用 `financial.quote.query` 获取行情快照，用 `financial.earnings.query_full` 获取财报。

### MSTR 专属

```
BTC 持仓量：web.fetch 搜索 "MSTR Bitcoin holdings 8-K"
BTC 价格：financial.quote.verified(ticker="BTC-USD", metric="price")
mNAV = 市值 / (BTC持仓 × BTC价格)

STRC 数据：web.fetch 搜索最新股息率、VWAP vs $100 面值
关注指标：股息是否连续上调（每月调 25-50bps 是预警信号）
```

### 矿企专属

```
全网算力：web.fetch 搜索 "BTC hashrate"
公司自有算力（EH/s）、电力成本（$/kWh）、每 BTC 挖矿成本
BTC 持仓量、减半倒计时
```

### COIN 专属

```
24h 交易量：CMC MCP get_global_metrics_latest
USDC 流通量、Base 链 TVL/交易量
订阅收入占比（目标 >50%）、监管进展
```

---

## 步骤 2：常态性分析 — 估值与质量

### 估值方法对照表

| 币股 | 该用什么 | 不该用什么 | 为什么 |
|:----|:--------|:---------|:------|
| **MSTR** | mNAV 分位法 | PE/PB/PEG | PE 毫无意义 |
| **COIN** | P/S + 订阅收入占比 | PEG | 交易手续费强周期 |
| **矿企** | PB 周期分位法 + EV/EBITDA | PE/PEG | 周期股陷阱 |
| **矿企 CAPEX** | CAPEX/OCF 比 | — | >60% 预警 |

### MSTR 飞轮状态

```
正常运转：
✅ mNAV > 1.0x          ← 能以溢价发普通股去杠杆
✅ BTC 趋势向上          ← 资产端升值
✅ STRC 守在 $100 面值   ← 融资通道畅通

降速信号：
⚠️ mNAV 接近 1.0x       ← 飞轮杠杆空间收窄
⚠️ 股息暂停上调

断裂条件（死亡螺旋）：
🔴 mNAV < 1.0x 连续 4 周
🔴 STRC VWAP < $95 连续 4 周
🔴 BTC 放量跌破 $55K
🔴 股息被迫上调至 13-15%
```

### 矿企周期定位

```
□ 52 周涨幅 > 200%？→ 暂停 PE/PEG
□ 毛利率创历史新高？→ 周期顶部
□ CAPEX/OCF > 60%？→ 利润被矿机供应商拿走
□ 分析师一致上调 EPS？→ 追涨模式
□ 减半后 < 6 个月？→ 成本翻倍压力

如果 ≥ 2 个 Yes → 切换 PB 分位法 + EV/EBITDA
```

---

## 步骤 3：非常态性分析 — 催化剂与风险

### MSTR

```
🟢 BTC 站上 $70-75K + mNAV > 1.1x 连续两周 → 重新建仓
🟢 STRC 守稳 $100 + 股息不涨 → 飞轮正常
🔴 mNAV < 1x 连续 2 周 → 减持预警
🔴 BTC 放量跌破 $55K → 硬止损
```

### 矿企

```
🟢 BTC 减半后算力出清 → 剩者份额变大
🟢 电费下降/新能源合作 → 成本改善
🟢 AI/HPC 业务拓展 → 第二曲线
🔴 BTC 跌破挖矿成本 → 入不敷出
```

### COIN

```
🟢 监管清晰化 → 合规溢价
🟢 Base 链增长 → 第二引擎
🔴 交易量萎缩 → 核心收入受压
```

---

## 步骤 4：黑箱观察 — 联动与背离

```
MSTR 涨 > BTC 涨 → mNAV 扩张
MSTR 涨 < BTC 涨 → mNAV 压缩
MSTR 跌 + BTC 不跌 → 最危险

矿企 vs BTC：
  牛市：矿企 β > 1
  熊市：矿企 β > 1（跌更多）
  减半前：矿企跑赢
  减半后：矿企跑输
```

---

## 步骤 5：综合输出模板

```markdown
## 币股分析：[TICKER]

### 公司 vs BTC 关联度
类型：BTC 杠杆 proxy / 交易所 / 矿企
BTC β：[数值]

### 估值速查
正确方法：[mNAV / P/S / PB分位]
当前值：[X] — [偏高/偏低/合理]
误区提醒：[PE 在这里毫无意义，因为...]

### 飞轮/周期状态
[✅/⚠️/🔴 信号列表]

### 核心变量追踪
1. [变量1] — [当前值] — [为什么重要]
2. [变量2] — [当前值] — [阈值]
3. [变量3] — [触发条件]
```

---

## 关联 Skill

| Skill | 关系 | 加载时机 |
|:------|:----:|:--------|
| crypto-analysis | 上游（BTC 数据） | 需要 BTC 价格/链上/资金费率时 |
| us-stock-analysis | 互补（传统估值） | 需要传统 PE/DCF 对照时 |
| macro-analysis | 上游（宏观环境） | 利率/流动性影响 BTC 时 |

## 工具使用约定

⚠️ **数据检索优先级: RAG > Web Search** — 先查本地知识库（已归档 29 篇研报/新闻/台账），命中不到再搜外部。

| 操作 | 工具 |
|:-----|:-----|
| **🔍 知识库检索（优先）** | **`financial.rag.search`** — 查已归档的币股分析/新闻/MSTR 相关文章 |
| 币股行情/估值（交叉验证） | `financial.quote.verified` |
| 币股行情快照 | `financial.quote.query` |
| 财报数据 | `financial.earnings.query_full` |
| 外部搜索（fallback） | `web.fetch` / `financial.websearch` |
| **📊 对立观点（强制）** | `financial.websearch` 搜索 "{标的} bull case" + "{标的} bear case"，必须呈现至少一个有明确来源的反对观点 |
| 加载关联 Skill | `Skill(skill="...")` |
