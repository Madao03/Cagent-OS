---
name: edgar-adapter
purpose: 美股上市公司财报取数适配器规格 —— 完整 / 及时 / 正确
source: data.sec.gov (EDGAR) 官方 API，无需 key，免费
status: LANE 1 已交付 ✅ | LANE 2 已交付 ✅（详见 EDGAR_LANE2.md）
关联: DATA_INFRASTRUCTURE.md（DataLayer）、web-search skill（财报路由）
---

# EDGAR Adapter 规格文档

## 0. 目标与范围

**目标**：拿到**完整 + 及时 + 正确**的美股上市公司财报数据。

**覆盖**（本文档负责的）：EDGAR / data.sec.gov 的结构化取数 + 原始文件定位。
**不覆盖**（另立管线，见 §9）：财报电话会议 transcript、分析师一致预期（consensus/estimates）、非 GAAP 调整指标、实时股价反应。

一句话定位：本适配器是财报数据的 **source of truth（权威底座）**，不是财报投研能力的全部。

---

## 1. 概念速查（非金融背景 30 秒版）

| 概念 | 一句话 |
|:--|:--|
| **CIK** | 每个申报主体的唯一数字 ID（苹果=320193）。URL 里要补零到 10 位 |
| **XBRL** | 财务数字的机器可读标签标准。每个数字裹一层「是什么/哪期/什么单位」 |
| **Taxonomy** | 标签词典：`us-gaap`(美准则) / `ifrs-full`(国际) / `dei` / `srt` |
| **Tag** | 词典里的具体行：`Revenues`、`NetIncomeLoss` |
| **Accession Number** | 每份申报的唯一编号，用它去 Archives 取原始正文 |

**Form 速查：**

| Form | 是什么 | 频率 | 审计 | XBRL 结构化 |
|:--|:--|:--|:--|:--|
| **10-K** | 年报（最全最权威） | 1/年 | ✅ | ✅ |
| **10-Q** | 季报（Q1/Q2/Q3，无 Q4） | 3/年 | ❌ | ✅ |
| **8-K** | 重大事件公告，业绩发布最先落此（Item 2.02） | 事件驱动 | ❌ | ⚠️ 新闻稿附件，需解析 |
| **20-F** | **外国公司**年报（≈老外版 10-K，可能 IFRS 口径） | 1/年 | ✅ | ✅ |
| **6-K** | 外国公司中期/临时披露。★FPI 无 10-Q，季度业绩全靠此表报出 | 事件驱动 | ❌ | ⚠️ |
| **10-K/A、10-Q/A** | 修订件，覆盖原件 | 不定期 | — | 视情况 |

---

## 2. 数据获取全景（4 LANE）

```
[0] 入口  ticker ──► company_tickers.json ──► CIK（补零10位）

[1] 路由/索引  submissions.json
        · 全部申报流水：form / filingDate / accessionNumber
        · ★分流：10-K→本土 / 20-F→外国
                              │
        ┌──────────┬──────────┴──────────┬──────────┐
        ▼          ▼                     ▼          ▼
    [LANE 1]   [LANE 2]              [LANE 3]   [LANE 4]
   底座·数字   鲜度·触发             叙述·定性   外国发行人
   companyfacts 8-K→新闻稿           10-K正文    20-F/6-K
   结构化✅     chunking❌           chunking❌  口径分支
```

| LANE | 投研场景 | 端点 | 结构化 | chunking |
|:--:|:--|:--|:--:|:--:|
| 1 | 拿准确的历史财务数字 | companyfacts | ✅ | 否 |
| 2 | 业绩发布鲜度；★FPI 唯一季度数据源 | 8-K/6-K → Archives | ❌ | ★事实密集型 |
| 3 | MD&A/风险因素等定性材料 | 10-K 正文 → Archives | ❌ | ★分节语义型 |
| 4 | 中概股/外国公司完整性 | 20-F/6-K | 半 | 视情况 |

★ LANE 2 的优先级取决于覆盖范围：只做美国本土公司 = P1（早几天）；覆盖中概股/FPI = P0，因为 FPI 不报 10-Q，不解析 6-K 则季度序列直接塌成年度点。

---

## 3. 端点规格

> **Base**：`https://data.sec.gov`（XBRL + submissions）
> 原始文件在 `https://www.sec.gov/Archives`；对照表在 `https://www.sec.gov/files`

### 3.1 ticker → CIK

```
GET https://www.sec.gov/files/company_tickers.json
```
返回形如 `{"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}, ...}`。
处理：建 `ticker → cik` 内存映射；用时把 cik 补零到 10 位（`f"CIK{cik:010d}"`）。
缓存：整表低频变动，缓存 1 天。

### 3.2 submissions —— 路由/索引（不是数字）

```
GET https://data.sec.gov/submissions/CIK##########.json
```
关键字段：
- `name / tickers / sic / entityType` —— 公司元数据
- `filings.recent.{form[], filingDate[], accessionNumber[], primaryDocument[], reportDate[]}`
  —— **平行数组，同一下标对应同一份申报**（下标 0 是最近一份）

用途：
1. **判本土/外国**：流水里出现的是 10-K 还是 20-F。
2. **取最新一期**：按 form 过滤（如 `10-Q`），取 filingDate 最大的。
3. **拿 accession**：去 Archives 取原始正文（LANE 2/3）。

注意：`recent` 默认最近 1000 份；更早的走分页文件（响应里给下一批文件名）。

### 3.3 companyfacts —— 底座数字（LANE 1 主力）

```
GET https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
```
结构：`facts["us-gaap"][TAG]["units"]["USD"] = [ {val, fy, fp, form, start, end, accn, filed}, ... ]`

**核心 TAG（起手集）：**

| 科目 | 首选 TAG |
|:--|:--|
| 营收 | `Revenues` / `RevenueFromContractWithCustomerExcludingAssessedTax` |
| 毛利 | `GrossProfit` |
| 营业利润 | `OperatingIncomeLoss` |
| 净利润 | `NetIncomeLoss` |
| 摊薄 EPS | `EarningsPerShareDiluted` |
| 总资产 | `Assets` |
| 股东权益 | `StockholdersEquity` |
| 现金及等价物 | `CashAndCashEquivalents` |
| 经营现金流 | `NetCashProvidedByUsedInOperatingActivities` |

取数规则：
- 同 TAG 多条 → 按 `fy`（财年）+ `fp`（FY/Q1/Q2/Q3）选目标期间。**← 这一步用真实 fy，彻底替代硬编码 fiscal_year**
- `form=10-K`（审计）优先于 `10-Q`（未审计），并记录审计状态。
- 每个点带 `accn`，可回溯到原始申报（可追溯性）。

代价：单次返回可能几 MB。targeted 取数用 3.4。

### 3.4 companyconcept —— 单指标时间序列（省流量）

```
GET https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/{TAG}.json
```
只要一个科目的历史（如只要营收趋势）时用它，比 companyfacts 轻。

### 3.5 frames —— 跨公司横截面（同业对比）

```
GET https://data.sec.gov/api/xbrl/frames/us-gaap/{TAG}/USD/CY{year}{period}.json
```
一个概念、一个期间、**所有公司**。用途：同业分位、板块基准。P2 再接。

### 3.6 Archives —— 原始正文（LANE 2/3 输入）

```
https://www.sec.gov/Archives/edgar/data/{cik}/{accn_no_dashes}/{primaryDocument}
```
从 submissions 拿到 accession + primaryDocument 拼出来。
- LANE 2：8-K 的 `EX-99.1`（业绩新闻稿）→ 事实密集型 chunking。
- LANE 3：10-K/10-Q 主文档 → 按 Item 分节语义 chunking。

### 3.7 efts 全文检索 —— 辅助定位（不是主干）

```
efts.sec.gov（独立系统，覆盖 2001+）
```
用于「某句话/某概念在哪份 filing 里」的跨文件定位，定位到 accession 后回到上面的通道取数。

---

## 4. 取数决策流程

```
1. ticker ──► company_tickers.json ──► cik ──► 补零10位
2. GET submissions/CIK{cik}.json
3. 分流：
     若 filings 里是 10-K/10-Q ──► 本土（us-gaap）
     若 是 20-F/6-K            ──► 外国（可能 ifrs-full，见 §5 口径）
4. 按需求走 LANE：
     要数字   ──► companyfacts（选 fy/fp，审计优先）
     要鲜度   ──► filter 8-K(Item 2.02) → Archives EX-99.1 → chunk
     要定性   ──► 10-K/Q 主文档 → Archives → chunk
5. 出口过 §5 四道健壮性处理 ──► 写入 DataLayer（标注 source/accn/fetched_at）
```

---

## 5. 四道健壮性处理（不做必出内容级错误）

| # | 处理 | 规则 |
|:--:|:--|:--|
| ① | **Q4 缺口** | Q4 无专属定期报告 → XBRL 结构化数据里必须推算：Q4 = 年报 − 前三季。但 Q4 的「已报告数字」存在于 Q4 业绩新闻稿（本土=8-K Item 2.02，FPI=6-K），比年报早数周至数月。⚠️ 本条推算式仅适用本土申报人；FPI 见下方分支。⚠️ 推算值与公司报告值可能合法不一致（季度未审计 vs 年报审计调整），差异本身是诊断信号而非 bug |
| ② | **修订件** | 出现 10-K/A、10-Q/A 时取最新，覆盖原件 |
| ③ | **标签归一化** | 同科目多别名 → 映射到统一字段（见下表） |
| ④ | **审计优先** | 10-K(审计) > 10-Q(未审计)，冲突时以年报为准并标注 |

**口径分支（外国私人发行人 FPI，★中概股全部适用）：**

先用 submissions 判申报类型，命中 20-F 即走本分支：

- **申报结构**：只有 20-F（年报）+ 6-K（中期/临时）；从不报 10-K，也从不报 10-Q —— SEC 意义上一份季报都没有，「Q4 无季报」对 FPI 不是特例而是四季常态。
- **时间线**（以小鹏 XPEV / CIK 1810997 为基准，FY2020–FY2025 均落在 4/12–4/28）：
  - 12/31 财年结束 → 约3月：Q4&全年业绩新闻稿(6-K)，未审计
  - → 约4月中：20-F 年报，审计 + XBRL
  - 即财年结束后 3.5 个月才有年报；中间存在「有 Q4 数字但无年报」的合法窗口，不可判为数据异常。
- **季度数据来源**：唯一来源是 6-K 业绩新闻稿 → 必须走 LANE 2 chunking。
- **会计口径**：可能整套在 `facts["ifrs-full"]` 而非 us-gaap，本土 TAG 集不可套用。
- **★币种**：许多中概股以 RMB 记账，USD 为「便利折算」。取数必须显式确认币种字段，禁止默认 USD。

**标签别名映射表（starter，按需扩充）：**

| 统一字段 | 可能的 XBRL 标签 |
|:--|:--|
| revenue | `Revenues`、`RevenueFromContractWithCustomerExcludingAssessedTax`、`RevenueFromContractWithCustomerIncludingAssessedTax`、`SalesRevenueNet`(旧) |
| net_income | `NetIncomeLoss`、`ProfitLoss`(含少数股东权益) |
| equity | `StockholdersEquity`、`StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| op_cash_flow | `NetCashProvidedByUsedInOperatingActivities`、`...ContinuingOperations` |

> 实现建议：把别名表当**配置/数据**存，不写死进代码分支——新公司出现新别名时改配置即可。

---

## 6. 接入约束（硬规则，违反直接失败）

| 约束 | 细节 |
|:--|:--|
| **User-Agent 必填** | 每个请求带 `User-Agent: Name email`，否则常见 403 |
| **限速 10 req/s** | 超了 429；批量取数要节流 |
| **CIK 补零 10 位** | `CIK0000320193`，不补零取不到 |
| **XBRL 覆盖 2009+** | 更早申报无结构化，只能走 Archives 文本 |
| **payload 大** | companyfacts 单次可达数 MB，配缓存 |

---

## 7. DataLayer 集成

**能力命名（对齐现有 `financial.*` 约定）：**

| Capability | LANE | 说明 |
|:--|:--:|:--|
| `financial.edgar.filings` | 1路由 | submissions 索引，判本土/外国、取最新期 |
| `financial.edgar.facts` | 1 | companyfacts 结构化数字（主力） |
| `financial.edgar.concept` | 1 | 单指标时间序列 |
| `financial.edgar.document` | 2/3 | Archives 原始正文（喂 chunker） |

**与现有 fin-skill earnings 的关系（二选一，建议 A）：**
- **A（推荐）**：EDGAR 做美股财报**一手权威源**，fin-skill 降为解析便利/兜底。EDGAR 的 fy/fp 天然治好 `get_financials` 里 `fiscal_year=2025` 的硬编码 bug。
- **B**：两源并存，EDGAR 作 fin-skill 的**交叉验证基准**（同口径差异 > 阈值即标矛盾，接 DQ guard）。

**缓存策略**：财报低频变动 → 长缓存（如 24h）；但订阅 8-K/修订件事件时**主动失效**对应公司缓存。

**数据标注**（沿用现有规范）：每条落库带 `source=EDGAR / endpoint / accn / fetched_at / confidence / audited`。

---

## 8. 连通性 & 正确性验证清单（接线前自己跑一遍）

> 环境需能出网。逐条对预期结果肉眼核。

1. **Happy path**：`AAPL → CIK0000320193 → companyfacts`，取最新 10-K 的 `Revenues`，和苹果官方年报数字核对是否一致。
2. **User-Agent**：故意不带 UA 发一次 → 确认拿到 403（验证约束真实存在）。
3. **限速**：连发 > 10 req/s → 观察是否 429，确认节流逻辑生效。
4. **FPI 全链路**：XPEV(CIK 1810997) → 确认 submissions 中只有 20-F/6-K、无 10-K/10-Q；确认 20-F 提交日在次年 4 月中；确认数字所在 taxonomy 与记账币种。
5. **标签缺失**：找一个营收用 `RevenueFromContractWithCustomer...` 而非 `Revenues` 的公司 → 确认归一化映射能命中。
6. **Q4 重建**：取某公司 10-K 全年营收 − 同财年 Q1+Q2+Q3 → 得到 Q4 单季，核对量级合理。
7. **修订件**：找一家有 10-K/A 的公司 → 确认取到的是修订后而非原始数字。
8. **可追溯**：任取一个数字 → 用其 `accn` 拼出 Archives 链接 → 确认能打开对应申报。
9. **第三方 Q4 溯源比对**：取 FMP(或其他聚合商)某 FPI 的 Q4 记录，与公司 Q4 业绩新闻稿逐项对：完全一致 → 源自新闻稿；有零头差异 → 系 `全年−前三季` 推算值。同时校验其 fillingDate/period 字段是否早于任何真实 SEC 申报（早于 = 自行拼装）。

跑完这 9 条，连通性和正确性就有底了。

---

## 9. 边界：EDGAR 不覆盖什么（决定「90%」的真相）

EDGAR adapter 给你的是**公司自己报出来的、经审计的财务数字**——权威、完整、可追溯。但「财报投研能力」不止这些。以下**都不在 EDGAR 里**，各需独立管线：

| 缺口 | 为什么重要 | 从哪拿 |
|:--|:--|:--|
| **一致预期 / estimates** | 没有预期就无法判断「超预期/不及预期」——投研里比绝对数字更关键 | Zacks / Refinitiv / Visible Alpha 等（多为付费） |
| **财报电话会议 transcript** | 管理层口风、下季 guidance、分析师 Q&A | IR 官网 / Motley Fool / Seeking Alpha |
| **非 GAAP 调整指标** | Adjusted EBITDA 等，公司在新闻稿里给，标准 XBRL 常无 | 8-K 新闻稿解析（LANE 2） |
| **公司特有 KPI** | 如 MAU、储备金收入等，可能是自造扩展标签或只在正文 | companyfacts 扩展标签 / LANE 3 正文 |
| **实时市场反应** | 财报后的股价/成交 | 现有 quote 层 |
| **聚合商 Q4 推算值** | 第三方(FMP等)对 FPI 的 Q4 可能是推算而非报告值 | 以 6-K 新闻稿原文为准 |

---

## 10. 交付状态（2026-07-23）

| 阶段 | 内容 | 状态 |
|:--|:--|:--:|
| **LANE 1 (P0)** | ticker→CIK→companyfacts + submissions 路由 + 四道处理 + 本土 10-K/Q + FPI 20-F | ✅ 14 回归测试 |
| **LANE 2 (P0)** | 6-K/8-K 业绩新闻稿抽取 + 季度数据 + Guidance + FPI 降级保护 | ✅ 详见 EDGAR_LANE2.md |
| **P1** | 本土 8-K 鲜度（Item 2.02） | ✅ 已交付 |
| P1 | LANE 3 正文定性 | ✗ MVP 不做 |
| P2 | frames 同业基准；efts 全文定位 | ✗ 未排期 |

---

## 附：已完成的接线

1. ✅ **bug 修复**：companyfacts 的 fy/fp + start/end 日期替代了硬编码 fiscal_year；币种检测、税率推断均完成。
2. ✅ **能力注册**：`financial.edgar.facts`（LANE 1）+ `financial.edgar.release`（LANE 2）+ `financial.edgar.filings`（路由）。
3. ✅ **路由更新**：prompt_compiler 规则 6（财报 → edgar.facts）、规则 7（季度分拆/指引 → edgar.release）。

> 编制：为 CagentOS 财报数据基座 | LANE 1 ✅ LANE 2 ✅
