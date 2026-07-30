---
name: ashare-adapter-provenance-addendum
purpose: A股 Adapter 的增量要求 —— 原规格写于溯源系统之前
配套: ASHARE_FINANCIALS_ADAPTER.md（主规格，仍然有效）
status: 必读补丁
---

# A股 Adapter 补丁：溯源时代的增量要求

> 主规格 `ASHARE_FINANCIALS_ADAPTER.md` 的领域知识部分（报告体系、累计口径、三表勾稽、一手源分层）**全部仍然有效**。
> 本补丁只写「溯源系统上线后新增的要求」和「EDGAR 实战中踩出来、A股 会重演的坑」。

---

## 1. Fact schema 对齐（硬要求）

每条 A股 数据进 registry 必须携带：

```yaml
period_start / period_end:
period_type:   cumulative | quarterly | fiscal_year   # ★A股 默认是 cumulative
currency:      CNY          # 显式，禁止默认
accounting_standard: CAS         # ★中国企业会计准则
audited:       年报 true；一季/半年/三季报 false
derived:       差分值 true
precision:     若来自舍入值（亿元/万元两位小数）必须标注
caliber:       科目名 + 累计/单季标识
source:        akshare
tier:          secondary    # ★不是 primary，一手是巨潮
announcement_url:           # 巨潮公告链接，可追溯
```

**`period_type` 是 A股 特有的关键字段**：同一个"净利润"，累计口径和单季口径是两个不同的事实，**必须分别落库，不进同一个去重组**。

---

## 2. 单位陷阱（★最高危）

akshare 不同接口返回单位不一致：**元 / 万元 / 亿元 混杂**。

这是 EDGAR 双尺度 bug 的 A股 版本，而且更凶 —— EDGAR 是一份文档里两张表，这里是**不同接口不同单位**。

**规则（直接抄 EDGAR 的教训）：**

```
✅ 固定因子换算：万元 ×1e4，亿元 ×1e8
❌ 推算因子：ratio = raw / display
   ← EDGAR 曾用推算因子，把舍入误差放大成假精度
     （-1.39e9 被算成 -1389576873.99）
```

推算比值**只用于校验**（落在 0.99×~1.01× 之间确认单位判断正确），**不用于换算**。
换算自舍入值的字段必须标 `precision`。

**反例基线**：同一科目从两个接口取值，量级必须一致。

---

## 3. 差分实现（继承 LANE 2 教训）

主规格已写差分公式，这里补三条实现纪律：

| # | 规则 | 出处 |
|:--:|:--|:--|
| ① | **字段级合并，不是记录级二选一** | EDGAR 曾按记录去重，静默丢掉三个季度的净利润 |
| ② | **资产负债表禁止差分**（时点值） | 主规格已写，但极易在实现时套用同一套逻辑 |
| ③ | `audited` 取 **min(parents)** | Q4 = 年报(审计) − 三季报(未审计) → **结果不是审计** |

③ 与溯源系统的派生链继承规则完全一致，可直接复用 `min(parents)` 实现。

差分出现负值 → **flag 不 reject**（真实减值/退货/追溯调整会造成合法负值）。

---

## 4. 管道字段黑名单（防假 traced）

akshare 返回大量元数据，**不得注册为 fact**：

```
序号 / index / 更新时间 / 数据来源标记 / 股票代码 /
报告期字符串 / 排名 / 涨跌幅排名 / 数据条数
```

**EDGAR 教训**：`similarity` / `rank` / `conf` / `record_count` / `fx_rate` 曾被当成事实注册，
造成两个后果：污染 registry，以及**无关数字碰巧匹配到它们、拿到"已溯源"绿标**。

假的溯源比没有溯源更危险。

---

## 5. 缺失即缺失

```
拿不到 → 返回 None / 标 unknown
禁止 → 填 0 / 上期值 / 行业均值 / 任何默认值
```

这是已固化八次的同模式规则。A股 高发位置：
- 停牌期间的行情
- 未披露的分部数据
- 新上市公司的历史同期
- ST 公司的异常科目

---

## 6. 非数据识别（供 normalizer 补充）

A股 特有的、会被误判为数据的数字：

```
股票代码    600519 / 000001 / 300750 / 688981 / 8xxxxx
交易所后缀  .SH / .SZ / .BJ
报告期      20250930 / 2025-09-30
公告编号    2025-001
ST 标记     ST / *ST（含在名称里）
```

**EDGAR 先例**：accession `0001193125-26-117623` 曾被拆成两个数字判为幻觉。
股票代码是同类问题，且 6 位数字更容易碰撞。

---

## 7. 测试结构（复用 EDGAR 三层）

```
Tier 1（fixture，每次提交）
  存 akshare 返回快照：四种报告 / 业绩预告 / 业绩快报 /
                       ST股 / 送转股 / 追溯重述 / 停牌
Tier 2（live，定时）
  连通性 + ★akshare 函数签名漂移检测（非正式 API，随时变）
```

**反例基线（盯"不该发生的事"）：**

```
❌ 资产负债表科目被差分
❌ 半年报数字被当作 Q2 单季
❌ 三季报数字被当作 Q3 单季
❌ 差分值标注 audited=true
❌ akshare 标注 tier=primary
❌ 单位换算使用推算因子
❌ 缺失填 0 或上期值
❌ 股票代码被判为数据数字
❌ 累计值与单季值进入同一去重组
```

---

## 8. 验收标准

```
① 三表勾稽全过（六条，见主规格 §5）
② 覆盖率统计：N 只票 × M 期，口径写清楚（分母是什么）
③ ★接入后重跑溯源基线 —— 确认新数据源没有引入假 traced
   （对比接入前后的 hallucination / derived / traced 分布）
④ 核心指标覆盖数达标（不能靠少报数字降低幻觉率）
```

**③ 是这次和以往最大的不同**：溯源系统已经建成，
它可以**直接测量新数据源的质量**，不用等到写研报时才发现问题。

这也是先做 A股 的一个实际好处 —— 测量工具是现成的。

---

## 9. 优先级建议

```
P0-a  akshare 定期报告 + 累计/差分双字段 + 单位固定因子 + 三表勾稽
P0-b  Fact schema 对齐 + 管道黑名单 + 非数据识别
P0-c  巨潮公告索引（溯源 URL，不解析 PDF）
P0-d  接 capability + skill 路由：结构化优先
P1    业绩预告/快报（鲜度层）+ 预告区间 vs 实际后验
P1    追溯重述检测 + 送转股复权
```

**P0-b 不能推到后面** —— 如果先接数据再补元数据，
registry 会先被脏数据污染一轮，然后你要重跑所有基线。

下面这段可以直接贴到 `ASHARE_ADAPTER_ADDENDUM.md` 末尾。前半是新增章节,后半是要回改的几处现有条目。

------

markdown

```markdown
## 10. accounting_standard 字段（跨 adapter，非 A股 专有）

### 10.1 取值域
```

CAS       中国企业会计准则
 US_GAAP   美国公认会计原则
 IFRS      国际财务报告准则（含港股 HKFRS，已实质趋同）
 null      不适用（crypto / 宏观 / 行情）

```
> HKFRS 与 IFRS 已实质趋同，MVP 阶段合并为 `IFRS`。
> 若将来需要区分 A+H 公司的两套报表，再拆出 `HKFRS`。

### 10.2 各 adapter 的映射

**EDGAR** —— 已有信息，只是命名不同。`_detect_taxonomy()` 的返回值直接映射：

| taxonomy（现有） | accounting_standard（新增） |
|:--|:--|
| `us-gaap` | `US_GAAP` |
| `ifrs-full` | `IFRS` |
| `dei` / `srt` | — （元数据，不产出财务 fact） |

⚠️ **映射源必须是 taxonomy，不是 entity_type。**
FPI 不等于 IFRS —— XPEV / BABA 都是 FPI 但采用 US GAAP，
数据实际落在 `facts["us-gaap"]`。这是已修复过的 bug，不要在映射时重新引入。

**A股（akshare）** —— 恒为 `CAS`。

**Crypto / FRED / 行情** —— `null`，字段缺席即可。

### 10.3 空值规则
```

✅ 不适用 → null / 字段缺席
 ❌ 不适用 → 填任何默认值（"CAS" / "UNKNOWN" / ""）

```
同已固化的「信息缺失禁止填默认值」规则。
crypto 与宏观数据没有会计准则，这是**真实的不适用**，不是缺失。

### 10.4 派生链继承规则（与 currency 同构）

在 `derived_chain.py` 的 `verify_derivations()` 中，
紧邻现有的 currency 一致性检查后增加：
```

parents 的 accounting_standard 不一致  →  拒绝计算（不是 flag）

````
**拒绝而非 flag 的理由**：CAS 口径的净利润除以 IFRS 口径的营收，
数值算得出来但没有意义 —— 与跨币种相加同性质。

继承规则汇总（三条 + 一条新增）：

| 字段 | 规则 |
|:--|:--|
| `audited` | min(parents) —— 审计 − 未审计 = 未审计 |
| `precision` | min(parents) —— 取最低精度 |
| `currency` | 不一致 → 拒绝计算 |
| **`accounting_standard`** | **不一致 → 拒绝计算** |

### 10.5 缓存失效

EDGAR 侧新增该字段后，已缓存的 release 记录不含此字段。
按现有纪律 **bump `SCHEMA_VERSION`**（`data_layer/lane2/materializer.py`），
触发全量重抽，否则新字段只对新拉取的数据生效。

---

## 回改现有章节

**§1 Fact schema** —— 在 `currency` 下方增加一行：

```yaml
currency:            CNY      # 显式，禁止默认
accounting_standard: CAS      # ★可为 null（crypto/宏观不适用）
```

**§5 缺失即缺失** —— 高发位置列表增补一条：
````

- 非财报类数据源的 accounting_standard（应为 null，非默认值）

```
**§7 反例基线** —— 增补三条：
```

❌ accounting_standard 由 entity_type 推断（必须由 taxonomy 判定）
 ❌ 不适用场景填默认值而非 null
 ❌ 跨 accounting_standard 的派生计算被放行

```
**§8 验收标准** —— 增补一条：
```

⑤ 跨准则拒绝生效：构造一条 CAS fact ÷ US_GAAP fact 的派生，
 verifier 必须拒绝（与跨币种拒绝同路径）

```

```

------

两点补充说明:

**为什么强调"映射源是 taxonomy 不是 entity_type"** —— 这是你已经修过的 bug(FPI ≠ IFRS,XPEV/BABA 都是 FPI 但走 us-gaap)。加新字段时最容易顺手写成 `if entity_type == FPI: IFRS`,把修好的东西重新引入。

**§10.5 那个缓存失效容易漏** —— 你的 EDGAR release 有 SQLite 物化缓存,不 bump 版本号的话,新字段只对新拉的数据生效,老数据静默缺失。这条你自己在 `CLAUDE.md` 的开发注意事项里已经写过了,只是加字段时容易忘。

> 编制：A股 Adapter 补丁 | 与主规格配套使用
