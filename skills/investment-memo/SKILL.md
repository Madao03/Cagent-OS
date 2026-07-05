---
name: investment-memo
description: |
  投资 Memo 框架 — 不是研究报告，是决策导向的精炼文档。覆盖 Perp DEX/L1-native 项目的
  完整 memo 结构(0-VII章) + F/R乘数法(公链视角估值) + 双轨估值交叉验证(P/S底+F/R顶)
  + 因子叠加法 + 分层触发式建仓 + 反馈分诊协议。适用于加密/DeFi/币股投资决策。
category: research
---

# Investment Memo Framework

> Investment memo ≠ research report. A memo exists to make an investment decision, not to be exhaustive.
> Every section must pass the test: "does this change whether the reader would buy/hold/sell?"

## 触发条件

- 用户要求写投资 memo / 研究报告
- 用户要求给 Perp DEX / L1 / DeFi 协议估值
- 用户比较同一赛道的多个项目
- 用户提供了 PM 反馈需要处理
- 用户说「互动模式」「workshop」「一起写」

---

## 核心方法论：提炼原则 (The Distillation Principle)

| | Research Report | Investment Memo |
|---|---|---|
| Goal | Let reader fully understand the project | Let reader make an investment decision |
| Content strategy | Exhaustive | Only what changes the conclusion |
| Length | Long is better | As short as possible |
| Test | "Did I miss anything?" | "Can they decide to buy/hold/sell?" |

**Rule of thumb**: If the reader can make a decision with only your memo, it's good enough.

---

## 标准章节结构 (Perp DEX / L1-native focus)

### 0. Executive Summary
- One-line thesis + 3 supporting bullets + target valuation range

### I. Product & Tech Positioning
- Architecture (own L1 vs app on general chain vs Cosmos SDK)
- Technical moat: consensus, finality, fee sovereignty
- Comparison matrix against 5+ competitors

### II. The Replacement Narrative
- CEX market share penetration modeling
- Stress-test event validation (TVL / Volume / OI before-during-after)
- "System handled 3x volume + -56% OI with TVL flat" = institutional-grade evidence

### III. Fundamentals (Data Tables)
- Core metrics: TVL, MCap, FDV, MCap/TVL, Daily Volume, Revenue, P/S (MCap), P/S (FDV)

### IV. Tokenomics / Protocol Mechanics
- Value flywheel identification
- **Fee Buyback Ratio** — most undervalued metric. Buyback ≠ Dividend; always ask "Who Benefits?"
- Unlock schedule analysis, staking-adjusted effective dilution

### V. Valuation Framework (Multi-Layer + Dual-Track)
- **3-layer comps**: Same-vertical → Architecture comps → TAM replacement
- **Factor-Based Valuation (因子叠加法)**: Base + Alpha - Risk + Growth
- **F/R 乘数法 (公链视角)**: FDV/REV for L1-native projects — see below
- Always compute BOTH MCap and FDV multiples
- P/S Interpretation Trap: high P/S of dying competitor ≠ premium

### VI. Catalysts & Risks
- Ranked by probability, include failed-comparable case study

### VII. Action Framework — Trigger-Based Position Sizing (分层触发式建仓)
- Four-tier: Base(观察仓) → Left-side add(左侧) → Right-side add(右侧) → Hard cap
- Quantify every trigger. Coherence check: risks must be reflected in position caps.

---

## F/R 乘数法 + REV/OI 资本效率 — L1-native Valuation (公链视角估值)

> **When to use**: The project being valued is an L1-native protocol (自研共识 + 独立执行层), not a dApp on a general-purpose chain. F/R 乘数法 answers: "If the market prices this as a sovereign L1 rather than a DeFi application, what's the upside?"

### Core Concept

F/R 乘数 = FDV / REV (Real Economic Value / 真实经济价值)

Unlike P/S (which values the "business"), F/R values "network sovereignty." The same $1 of revenue means different things depending on whether it flows through a sovereign L1 or a tenant application.

### Step 1: Collect F/R comparables

| Chain | FDV | 1Y Revenue | F/R | MEV Purity |
|-------|-----|-----------|-----|------------|
| Ethereum | ~$400B | ~$400M | ~880x | Low (heavy MEV/PBS) |
| Solana | ~$80B | ~$600M | ~340x | Medium (junk tx + MEV) |
| **Target** | $X B | $Y M | **Zx** | High (MEV ≈ 0 for L1-native orderbook) |

### Step 2: Adjust for MEV Purity — "Clean Revenue Premium"

General-purpose L1s have toxic MEV in their REV. An L1-native orderbook chain with zero gas and anti-frontrunning has **structurally pure REV** (MEV/REV ≈ 0). This deserves a higher valuation for the same revenue level.

### Step 3: Dual-track cross-validation

| Method | What it answers | When to use |
|--------|----------------|-------------|
| **P/S 因子法** (应用视角) | "As a business, is it cheap or expensive now?" | Finding entry, setting defensive stops |
| **F/R 乘数法** (公链视角) | "As a sovereign network, what's the terminal value?" | Sizing upside, preventing premature exit |

**Decision heuristic**:
- Downside protection → use P/S (bottom-up)
- Upside potential → use F/R (top-down)
- `F/R_target << F/R_comps` while `Revenue_target > Revenue_comps` → **structural undervaluation signal**

---

## 因子叠加法 (Factor-Based Valuation)

```
合理估值 = Base + Alpha - Risk + Growth

Base (基础倍数):
  - Perp DEX Gen1: 15-20x P/S
  - Perp DEX Gen2 (L1-native): 50-80x P/S
  - DeFi Lending: 10-15x P/S

Alpha (超额因子):
  - 自研 L1 + 独立执行层: +20-30x
  - 零 MEV/反抢跑架构: +10-15x
  - 机构级抗压验证: +10x
  - 品牌/社区: +5-10x

Risk (风险折扣):
  - 中心化(验证者<50 + 有干预历史): -15-25%
  - 代币解锁悬崖: -10-20%
  - 监管不确定性: -15-30%
  - 竞品代际优势: -10-20%

Growth (增长溢价):
  - 渗透率<5% + 增速>100%: +10-20x
  - 渗透率5-15%: +5-10x
  - 渗透率>30% + 增速放缓: 0x
```

---

## 中心化审计 (Centralization Audit — L1-native projects ONLY)

**Core question**: How many validators control the chain, and have they ever intervened?

Data points: validator count + operators + geography, staking %/APY, code open-sourcing history, intervention history (JELLY events).

Apply a "centralization discount" to P/S: 15-25% off comp-derived range for projects with <50 validators + intervention history.

---

## 分阶段修订法 (Phased Memo Revision)

When a memo receives 25+ feedback items:

| Phase | What | When | Duration |
|-------|------|------|----------|
| **Phase 1: Data Calibration** | Mechanical replacements: numbers, dates, formatting | Immediately, before any discussion | ~10 min |
| **Phase 2: Framework Repair** | Valuation methodology, logical contradictions, factor anchoring | After Phase 1, requires user discussion | Variable |
| **Phase 3: Prose/Structure** | Rewrite sections, add new sections | After Phase 2 framework is locked | One pass |
| **Phase 4: Deep Research** | Competitor deep dives, new data sources | Can be deferred or parallelized | Variable |

---

## 反馈分诊协议 (Feedback Triage Protocol)

| Category | Examples | Priority |
|----------|----------|----------|
| 致命事实错误 | Validator count, tokenomics math | P0 — fix immediately |
| 估值框架问题 | Factor anchoring, F/R comparability | P1 — discuss then fix |
| 缺失风险维度 | Regulatory, HLP tail, team black-box | P2 — add new sections |
| 催化剂时间线 | HIP-4 date, competitor data freshness | P2 — verify and update |
| 竞品盲点 | Competitor depth | P3 — deep research |
| 结构/写作 | Executive Memo clarity, excessive precision | P3 — polish |

---

## 数据源速查卡

| Data | Source | Notes |
|---|---|---|
| TVL | DeFiLlama `/protocol/{name}` | `currentChainTvls`, `mcap`, `raises` |
| Market Cap | DeFiLlama or CoinGecko | CoinGecko `/coins/{id}` for price, MCap, FDV, supply, ATH |
| Daily Volume | Back-calculate from fees | `daily_vol = annualized_fees / avg_fee_rate / 365` |
| Revenue | DeFiLlama `/overview/fees/{name}` | `total24h`, `total7d`, `total30d`, `total1y` |
| Blockworks REV | Blockworks Research dashboards | TTM and 30D revenue for F/R乘数法 |
| 稳定币流通量/市占率 | DeFiLlama `/stablecoins?includePrices=true` | `peggedAssets[].circulating.peggedUSD` |

---

## ⚠️ 常见陷阱

- ❌ **Jumping to write memo in analysis mode** — "拉出来看看结构", "理一下roadmap", "补习" = STUDY mode, not build mode. Extract skeleton first, present mapping, WAIT for confirmation.
- ❌ Writing a research report when user wants a memo
- ❌ Comparing to only old/reference projects (dYdX, GMX) — always find newest competitors
- ❌ Using FDV P/S without also showing MCap P/S (low circ supply inflates FDV ratio)
- ❌ Presenting "high P/S" of a dying competitor as a premium — it's revenue collapse, not market respect
- ❌ Not checking validator count and intervention history for L1 projects
- ❌ Using peak-event volume instead of full-year run-rate for TAM estimation
- ❌ Applying F/R to dApp-layer projects — only valid for sovereign L1s
- ❌ Using 30D annualized REV without checking TTM (30D can be noisy)
- ❌ Ignoring MEV composition — $100M clean REV ≠ $100M toxic-MEV REV
- ❌ **费率假设不区分商业模式** — B2B 清算网络的费率与零售 card network 差一个数量级
- ❌ **模型假设在逆风周期中"恒定"** — net take-rate、distribution cost ratio 在利率下行时不是常数

---

## 关联 Skill

| Skill | 关系 |
|:------|:----|
| defi-analysis | Memo 中估值部分的核心方法论来源 |
| crypto-stock-analysis | 币股 memo 的标的分析框架 |
| multicoin-lens | 提供 VC 级投资视角作为 memo 的参考框架 |
| us-stock-analysis | 美股 memo 的估值对照 |
| macro-analysis | 宏观环境判断作为 memo 风险章节输入 |
