---
name: edgar-lane2-earnings-release
purpose: 业绩新闻稿抽取管线 —— FPI 季度数据唯一来源
depends_on: EDGAR_ADAPTER.md (LANE 1 已交付)
status: 已交付（MVP）
delivery_date: 2026-07-23
coverage: 3 ticker × 8 季 = 20/24 = 83%（口径见 §12）
---

# EDGAR LANE 2 交付报告：业绩新闻稿抽取

## 0. 交付摘要

| 能力 | 状态 | 验收 |
|------|------|------|
| `financial.edgar.release` | ✅ 已注册 | 端到端 6s，缓存命中 17ms |
| S3 文档分类器（零成本信号） | ✅ | XPEV 22 季 sweep: 21/22 召回 |
| S4-S6 表格解析 + 期间归属 | ✅ | 四季加总 0.0000% 差异 |
| G4 Guidance 抽取 | ✅ | Q1 2026 实际 vs 指引 4/4 命中 |
| 8-K Item 2.02（本土） | ✅ | AAPL 4/4 命中 |
| F4 离线物化（SQLite 缓存） | ✅ | 362x 加速（6.2s → 17ms） |

---

## 1. 七次同模式 Bug 及固化规则

本轮开发中最可复用的产出：**同一模式在不同环节出现七次**，根因统一。

| # | 环节 | 表现 | 修复 |
|---|------|------|------|
| 1 | LANE 1 `fy` | `fy` 字段是申报年份，非覆盖期间 → XPEV 返回 FY2023 | 用 `start`/`end` 日期 + 时长分类 |
| 2 | LANE 1 标签别名 | AAPL 2019+ 换 tag → 别名匹配在第一个 tag 就停 | 合并所有别名数据 |
| 3 | LANE 1 币种默认 | FPI 默认 USD → 拿的是便利折算值 | 取历史最长的单位为本位币 |
| 4 | LANE 1 FPI≠IFRS | entity_type 推断 taxonomy → 实际数据在 us-gaap | 统计数据点分布判断 taxonomy |
| 5 | LANE 2 表头日期 | bare year "2025" → 默认 Dec 31 → AAPL(Sep 财年)错 3 月 | **bare year → None，禁止推断月日** |
| 6 | LANE 2 币种默认 | AAPL HTML 表无币种标签 → 返回 "unknown" | `_detect_document_currency()` 检测显式信号 |
| 7 | S3 分类器无下限 | `find()` 取窗口内最高分 → Q3 2022 返回了季末前的文档 | **硬约束 filed > period_end + score < 0.35 下限** |

**固化规则**：信息缺失或歧义时，必须返回 None / 标 unknown / 报 ambiguous，**禁止填充默认值**。"相对最好"在信息缺失时 = 默认值。

---

## 2. 管线架构

```
agent 查询 "XPEV Q3 2025 营收"
    ↓
financial.edgar.release
    ↓
┌─ F4 缓存命中？─ 是 → 17ms 返回
│  否 ↓
├─ S3 find(ticker, quarter_end)
│   ├ 窗口：季末 + 90 天（Q4 更宽）
│   ├ 硬约束①：filed_date > period_end
│   ├ 硬约束②：filed_date - period_end ≥ 30 天
│   ├ 6-K：EX-99.1 大小 + 多附件 + 日期接近度 打分
│   ├ 8-K：Item 2.02 → 直接命中，conf=0.85
│   └ 绝对下限：score < 0.35 → 返回未找到
├─ 下载 EX-99.x 正文
├─ extract(html)
│   ├ S4：表格筛选（INCOME_KEYWORDS + 期间头）
│   ├ S5：列头跨行合并 + 行归一化 + 括号负数
│   ├ S6：期间归属（start/end 显式绑定）
│   └ G4：Business Outlook → 区间 + YoY
└─ 写缓存 → 返回
```

---

## 3. 分类器设计（S3）

### 3.1 零成本信号（Phase 1，已交付）

| 信号 | 来源 | 作用 |
|------|------|------|
| `filed_date > period_end` | 提交日 vs 季末 | 硬排除（逻辑不可能） |
| `filed_date - period_end ≥ 30 天` | 同上 | 硬排除（年报 PDF 抢跑） |
| EX-99.1 大小 > 8KB | index.json | 排除月度交付/董事变动 |
| 多 EX-99 附件 | index.json | 正信号（≥2 个 EX-99） |
| 8-K Item 2.02 | submissions.items | 权威正信号（SEC 已分类） |
| score 绝对下限 0.35 | 打分 | 防止"最好但也不够好" |

### 3.2 打分模型（6-K 路径）

```
总分 = size_score + multi_exhibit + date_proximity + reportDate_match

size_score:    ≥200KB → 0.45 | ≥100KB → 0.35 | ≥50KB → 0.20 | ≥15KB → 0.10
multi_exhibit: ≥2 个 EX-99 → 0.15
date:          30-90 天 → 0.15 | 90-120 天 → 0.08
reportDate:    匹配季末 → 0.15
```

### 3.3 已知未实现

- S3 Phase 2（LLM 兜底）—— MVP 阶段零成本信号已覆盖近期季度
- 分页（`filings.files[]`）—— BABA 等长期上市 FPI 的历史会溢出 `recent` 上限

---

## 4. 提取器（S4-S8）

### 4.1 表格解析（S4-S6）

- 表头跨行合并：SEC 表常把日期拆成多行（月/日一行，年另一行）
- 行归一化：合并装饰性 `<td>`($、括号、逗号) 与相邻数值
- 括号负数：`(16,583,754)` → −16,583,754
- 期间绑定：每个值显式标记 `(start, end)`，靠时长判单季/全年
- 币种：CNY 本位币入库，USD 折算标注 `fx_rate`（从脚注解析）
- 去重：同 (start, end, currency) 保留指标最多的记录

### 4.2 Guidance 抽取（G4）

从 Business Outlook 段落提取：
- 绝对区间："RMB12.20 billion and RMB13.28 billion"
- YoY 锚点："year-over-year decrease of 16.01% to 22.84%"
- 区间方向：低值 → 更大跌幅（yoy_change_low = −max(pct), yoy_change_high = −min(pct)）
- 可比验证：Q4 2025 指引 vs Q1 2026 实际 4/4 命中（§11）

### 4.3 已知边界

| 边界 | 成因 | 影响 |
|------|------|------|
| **ex992 文档** | XPEV 港交所双重上市导致 EX-99.1/99.2 顺序交换；ex992 是业绩稿本身（已验证），但格式为港交所式深层嵌套 HTML（非 iXBRL），226 个 table 无一命中 INCOME_KEYWORDS | Q1/Q2 2025、Q1 2026 无法提取 |
| **PDF** | `filed_date ≥ 30 天` 硬约束已排除年报 PDF 抢跑；若 PDF 确为业绩稿 → 格式不支持 | MVP 不覆盖 |
| **非 12 月财年** | AAPL（Sep 财年）、NVDA 等财年结日 ≠ 日历年季末，季度窗口需对齐 | 覆盖率计算用日历季末代理 |

---

## 5. 缓存（F4 离线物化）

- 后端：SQLite (`data/edgar_release.db`)，WAL 模式
- Schema：`(ticker, quarter_end) → {accession, records_json, guidance_json, schema_version, ...}`
- 版本控制：`SCHEMA_VERSION` 字段 → bump 版本号自动全量重抽
- 加速比：**362x**（6.2s → 17ms）
- 安全性：SEC 文档按 accession 寻址，落地后永不改变，缓存永不过期

---

## 6. 测试三层结构

| 层 | 标记 | 数量 | 时间 | 职责 |
|------|------|------|------|------|
| **Tier 1** | `-m "not sec"` | 39 | 2.9s | 每次提交：提取器逻辑、fixture 回归 |
| **Tier 2 选择层** | `@pytest.mark.sec` | 26 | ~70s | 定时：`find()` 返回正确 accession（23 XPEV + 3 AAPL） |
| **Tier 2 SEC 回归** | `@pytest.mark.sec` | 11 | ~8s | 定时：LANE 1 反例基线（币种/税类/期间） |
| **Tier 2 总计** | | 37 | ~80s | 定时/手动触发 |

Tier 1 全部走 fixture，不碰网络。Tier 2 打 SEC API，验证连通性 + 上游漂移。

---

## 7. 数据源

| 源 | 用途 | 接入 |
|------|------|------|
| `company_tickers.json` | ticker → CIK | 同 LANE 1 |
| `submissions/CIK{}.json` | 申报索引（form/filingDate/accession/items） | 同 LANE 1 |
| `Archives/.../index.json` | 附件清单 + 大小 | Phase 1 分类信号 |
| `Archives/.../EX-99.x` | 业绩新闻稿正文 | 下载 + 提取 |

---

## 8. 数据库表

```
edgar_release_cache
  PRIMARY KEY (ticker, quarter_end)
  ├ accession, document, filing_date, form
  ├ schema_version    ← 版本控制
  ├ records_json      ← FinancialRecord[]
  ├ guidance_json     ← GuidanceRecord[]
  └ conf
```

---

## 9. 接入点

| 位置 | 内容 |
|------|------|
| `lane2/classifier.py` | S3 文档分类器（`EarningsReleaseFinder`） |
| `lane2/extractor.py` | S4-S8 提取器（`EarningsReleaseExtractor`） |
| `lane2/materializer.py` | F4 缓存（`EdgarReleaseStore`） |
| `plugins/financial/plugin.py` | `financial.edgar.release` capability |
| `agents/prompt_compiler.py` | 规则 7：季度分拆/指引 → `financial.edgar.release` |

---

## 10. Fixture 清单

```
tests/fixtures/edgar/
  xpev_6k_fy2025q4_earnings.html + .meta.json    ← Q4 2025 业绩稿（EX-99.1）
  xpev_6k_q32022_hard_negative.html + .meta.json ← HKEX 中期报告（难负样本）
```

---

## 11. Guidance 后验验证

Q4 2025 指引 vs Q1 2026 实际（2026-05-11 发布）：

| 指标 | 指引区间 | 实际 | 落点 |
|------|---------|------|------|
| 营收 | ¥12.20B ~ 13.28B | ¥13.03B | ✅ 区间内 |
| 交付量 | 61,000 ~ 66,000 | 62,682 | ✅ 区间内 |
| 营收 YoY | −22.84% ~ −16.01% | −17.6% | ✅ 区间内 |
| 交付 YoY | −35.11% ~ −29.79% | −33.3% | ✅ 区间内 |

---

## 12. 覆盖率（MVP 验收指标）

**口径**：对目标标的，取最近 8 个完整日历季度，统计 `finder.find() + extractor.extract()` 产出 ≥1 条 FinancialRecord 的比例。

**分母**：3 个标的（XPEV / AAPL / BABA）× 8 个季度（Q2 2024 – Q1 2026）= 24

| Ticker | 命中 | 说明 |
|--------|------|------|
| AAPL | 8/8 (100%) | 8-K Item 2.02 路径 |
| BABA | 8/8 (100%) | 6-K 路径 |
| XPEV | 4/8 (50%) | Q1/Q2 2025、Q1 2026 的 ex992 文档为港交所格式 → 提取器不支持 |
| **合计** | **20/24 (83%)** | |

**注**：选择层（`find()` 返回正确 accession）XPEV 23/23 全对。覆盖率短板在提取器对非 Donnelley 模板的支持，不在文档选择。

---

## 13. 明确不做

- ✗ LANE 3 正文定性 — RAG 已能吃文档
- ✗ PDF 解析 — 选择逻辑修复后 PDF 不应被选中
- ✗ S3 Phase 2 LLM 兜底 — 零成本信号已覆盖近期季度
- ✗ 2023 年以前历史季度 — 投研价值低
- ✗ 财报电话会议 — 不在 SEC，另立管线
- ✗ BABA 分页 — MVP 不覆盖长历史 FPI
- ✗ iXBRL / 港交所模板 — ex992 格式，非 Donnelley 印刷厂模板

---

> 编制：CagentOS EDGAR LANE 2 交付报告 | 依赖 LANE 1（已交付）
