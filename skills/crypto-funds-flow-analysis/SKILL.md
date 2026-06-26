---
name: crypto-funds-flow-analysis
description: 加密货币资金面分析框架 — 覆盖稳定币市值、CEX储备、链上TVL、DEX交易量、杠杆数据等关键指标，提供标准化数据获取与解读流程
category: research
---

# Crypto Funds Flow Analysis

> 资金面是 crypto 的"财务报表"——链上不会说谎。这个 Skill 帮你从资金流向角度判断市场健康度。

## 何时触发

- 用户问「资金面表现如何」「资金流入数据」「稳定币市值变化」「链上资金活动」
- 需要判断市场是否在"真金白银"流入还是存量博弈
- 杠杆水平是否危险
- ⚠️ 需要价格/周期分析 → 同时加载 crypto-analysis

---

## 步骤 1：数据获取

### 稳定币总市值
- 来源：CMC MCP `get_global_metrics_latest`（含稳定币市值）
- 备选：`web.fetch` 搜索 "stablecoin total market cap"
- 关注：总市值趋势（扩张=资金流入，收缩=资金流出）

### CEX 稳定币储备
- 来源：`web.fetch` 搜索交易所钱包余额
- 关注：CEX 稳定币储备上升 → 购买力积累，潜在买盘

### DeFi TVL
- 来源：`web.fetch` 搜索 "DeFi TVL" 或 DeFiLlama
- 关注：TVL 趋势、各链占比变化

### DEX 交易量
- 来源：`web.fetch` 搜索 "DEX volume 24h"
- 关注：交易量趋势 vs CEX 交易量（DEX/CEX 比上升 = 链上活跃度提升）

### 杠杆水平
- 资金费率：`web.fetch` 搜索 "BTC funding rate"
- 未平仓合约（OI）：`web.fetch` 搜索 "BTC open interest"
- 关注：资金费率极端正值（>0.1%）= 多头拥挤；OI 飙升 + 价格不涨 = 危险背离

---

## 步骤 2：数据分析框架

```
市场情绪：恐惧贪婪指数（CMC MCP 含 fear_greed 字段）、BTC 主导率
资金流向：稳定币市值变化、CEX 储备变化
链上活动：DeFi TVL、DEX 交易量
杠杆水平：资金费率、未平仓合约（OI）
```

### 判断矩阵

| 信号组合 | 判断 |
|:--------|:-----|
| 稳定币市值↑ + CEX储备↑ + 资金费率中性 | 🟢 健康积累期——资金在进场但没过热 |
| 稳定币市值↑ + OI↑ + 资金费率极高 | 🟡 杠杆牛——上涨可持续性取决于去杠杆速度 |
| 稳定币市值↓ + CEX储备↓ + TVL↓ | 🔴 资金外流——市场在系统性去风险 |
| TVL↑ + DEX量↑ + CEX量↓ | 🟢 链上活跃度提升——DeFi 叙事回归 |

---

## 步骤 3：报告模板

```markdown
### 资金面分析（YYYY-MM-DD）

1. **稳定币市值**：$X亿（+Y% 7D）
2. **CEX 储备**：$X亿（+Y% 7D）
3. **链上 TVL**：$X亿（+Y% 7D）
4. **DEX 交易量**：$X亿（24h）
5. **杠杆信号**：资金费率 X%（[偏高/正常/偏低]），OI +Y%

### 综合判断
[🟢 健康 / 🟡 谨慎 / 🔴 危险] — [一句话总结]

### 关键变量
[本周需要持续关注的 2-3 个指标]
```

---

## 注意事项

- 数据更新频率：稳定币/CEX 数据每日，链上数据实时
- 异常值处理：若单日波动 >5%，交叉验证（多个数据源对照）
- 杠杆数据有滞后——资金费率和 OI 是快变量，TVL 和稳定币是慢变量
- 快变量给出入场时机，慢变量给出方向判断

## 工具使用约定

⚠️ **检索优先级: RAG > Web Search** — 先查本地知识库，命中不到再搜外部。

| 操作 | 工具 |
|:-----|:-----|
| **🔍 知识库（优先）** | **`financial.rag.search`** — 查已归档资金面分析/稳定币动态 |
| 稳定币市值/恐惧贪婪 | CMC MCP `get_global_metrics_latest` |
| DeFi TVL/DEX 量 | `web.fetch` / `financial.websearch` (fallback) |
| 资金费率/OI | `web.fetch` 搜索 |
| 加载关联 Skill | `Skill(skill="crypto-analysis")` |
