---
name: fin-skill-dq-guard
description: |
  数据质量守卫 — fin-skill MCP 各工具的已知 Bug、字段可信度评级、交叉验证方法。
  记录 CIQ 分拆调整错误、商品报价 42% 价差异常、Forward PE 溯源链路、FMP 数据不可信标的。
  使用 fin-skill MCP 工具时必须加载此 skill，防止静默输出错误分析。
category: research
---

# fin-skill MCP 数据质量守卫

> ⚠️ 不加载此 skill 的情况下使用 fin-skill 工具 = 静默输出错误分析。所有已知 Bug 都经过实测验证。

## 何时加载

- 使用 fin-skill MCP 工具提取财报/行情/新闻数据时
- 对 fin-skill 返回的数据做交叉验证时
- 需要知道 CIQ 数据源有哪些已知 bug 时
- 分析 NFLX/AMZN/GOOG/NVDA 等有历史拆股的标的时
- 获取商品行情（XAUUSD/XAGUSD）时

---

## 工具总览与可信度评级

| 工具 | 用途 | 可信度 | 已知问题 |
|------|------|--------|---------|
| `get_stock_quote` | 实时行情 | 🟢 高（股票）/ 🔴 低（商品） | **股票**: pe_trailing 恒 null。**商品**: 仅返回裸价，OHLCV/open/prev_close 均为 null。🔴 XAUUSD 返回 $4,715.42，同日 klines 返回 $3,323.64——价差 ~42% |
| `get_stock_snapshot` | 批量行情 | 🟢 高 | 同上 |
| `get_stock_analysis` | 综合概览 | 🟡 中 | growth 指标乱（AAPL 营收增速报 30% 实为 ~6%）；latest_quarter 数据滞后 |
| `get_financials` | 三大报表 | 🟢 高（通用）/ 🔴 低（分拆股） | **CIQ 分拆调整 bug** — NFLX 股数多 10x，EPS 少 10x |
| `get_financials_raw` | 原始字段级 | 🟢 高 | 同 get_financials，字段更全，推荐做对账用 |
| `get_financial_metrics` | 估值比率 | 🟡 中 | P/B/P/S/EV/EBITDA 缩放错误（值在百万级）；ROE/ROA 可信。**港股全量不可用** |
| `get_company_news` | 公司新闻 | 🔴 低 | **系统性问题：对大量 ticker 返回相同通用文章**，ticker 参数被忽略 |
| `get_asset_klines` | K 线 | ⚠️ 需必传参数 | start_time/end_time 不可缺 |

---

## CIQ 数据源已知 Bug

### Bug 1: 分拆调整错误（已确认 🔴）

- **现象**：NFLX dilute shares 报 4,344M，实际应为 ~434M（10x 误差）
- **原因**：2015 年 10:1 forward split 的分拆调整在 CIQ 未正确应用
- **影响**：EPS、Revenue per Share 等所有每股指标均错误
- **交叉验证方法**：用 `market_cap / stock_price = implied_shares` 反算，与 `shares_diluted` 比对。偏差 > 2% → 分拆调整 bug

**需额外谨慎的标的**：AMZN（2022 20:1）、GOOG（2022 20:1）、NVDA（2024 10:1）— 使用前先做交叉验证

### Bug 2: 估值倍数缩放错误

- P/B、P/S、EV/EBITDA 返回千万/亿级数字
- 不要直接用，自己算（price / 已知靠谱的每股数据）

### Bug 3: get_stock_analysis 指标混乱 + latest_quarter 严重滞后

- AAPL `revenue_yoy_pct`=30.35%（实际 ~6%）；ROE=235%（偏高）
- `latest_quarter` 数据严重滞后：MU 返回 5+ 个月前数据
- 只取 quote 和 news 字段，财务指标用 `get_financials` 替代

### Bug 4: 商品报价价格异常（XAUUSD 价差 42% 🔴）

- `get_stock_quote("XAUUSD.COMMODITY")` 返回 price: 4715.42，同日 klines 返回 close: 3323.64
- 三方对照：Yahoo Finance GC=F 同日 $3,335.40 → klines 可信，quote 异常
- **商品行情一律用 `get_asset_klines`（取最新一根 K 线）或金十 MCP**

---

## 推荐的数据获取方案

```
需要股票行情 → get_stock_quote（价格/市值/52w范围）
需要商品行情 → get_asset_klines 或金十 MCP。⚠️ 不用 get_stock_quote
需要财报 → get_financials_raw（字段最全，可做对账）
需要完整报表 → get_financials（limit=4 看多期趋势）
需要估值 → get_financial_metrics（只看 ROE/ROA/NII Margin，忽略 P/B/P/S）
需要新闻 → get_company_news / get_market_news（时效性一般，个股新闻不可靠）
银行类标的 → get_financials_raw 而非 get_financials
```

## Forward PE/EP 数据源对照

| 指标 | fin-skill MCP | yfinance |
|:-----|:-------------|:---------|
| Forward PE | ✅ `pe_forward` | ✅ `info['forwardPE']` |
| **Forward EPS（下一财年共识）** | ❌ **不提供** | ✅ `info['forwardEps']` |
| Forward EPS 历史趋势 | ❌ | ✅ `ticker.eps_trend` — 5 个快照 |
| Forward EPS 共识范围 | ❌ | ✅ `ticker.earnings_estimate` |
| 分析师修订计数 | ❌ | ✅ `ticker.eps_revisions` |

### Fine-skill pe_forward 溯源

- fin-skill `pe_forward` **不来自 CIQ**，来自 CMCF Quote API 的 `ntm_pe` 字段
- 8 票跨源验证：高波动成长股（NVDA/MU/WMT）差异 >5%，稳定大盘股（JPM/AAPL/XOM）差异 <5%
- NVDA: yfinance PE=18.5x vs QAPI PE=25x（差异 35%）→ 不可互换

### 周期股 Forward EPS 趋势检查

对周期股（半导体/内存/化工/航运），用 `eps_trend` 检查 Forward EPS 的 60-90 天变化：
- 如果 +1y Forward EPS 在 60-90 天内翻倍 → 🔴 分析师在"追涨"，线性外推当前暴利 → Forward PE 的"低"是幻觉

---

## 已知可信/需谨慎标的

**已验证正确**: AAPL ✅ | JPM ✅ | MSFT ✅ | GOOGL ✅ | MU ✅（财报，非 Forward PE）

**需谨慎（分拆调整存疑）**: NFLX 🔴 | AMZN ⚠️ | GOOG ⚠️ | NVDA ⚠️

**FMP 数据不可信**: XPEV 🔴（财报推算造假）| NIO ⚠️ | LI ⚠️

---

## 交叉验证方法

遇到可疑数据时：
1. 用 `search_assets` 确认 ticker 正确
2. 对比 get_financials 和 get_financials_raw 的 EPS 是否一致
3. **股数验真**：用 `market_cap / price = implied_shares` 反算，偏差 > 2% → 分拆调整 bug
4. 对 banks: get_financials 的 revenue=null 是正常现象，用 get_financials_raw 取银行专有字段
5. 商品行情双源对照：金十 MCP vs get_asset_klines
