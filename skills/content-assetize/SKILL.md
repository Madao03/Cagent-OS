---
name: content-assetize
description: >
  内容资产化——将 A 类（精读级）文章拆解为 事实/观点/框架 三类结构化资产，
  写入知识库供后续 RAG 检索、交叉验证和投资决策参考。
  这是「读完→记住→能用」的核心引擎。
  触发：用户说「资产化」「拆解」「提取」「assestize」，
  或对一篇已分诊的 A 类文章进行深度加工时。
category: knowledge
---

# 内容资产化（Content Assetize）

> **一句话**：把一篇好文章从"读过就忘的文本"变成"可检索、可引用、可复用的知识资产"。

---

## 何时触发

1. 用户明确要求对某篇 A 类文章进行资产化
2. 用户说「把这篇文章拆一下」「提取关键信息」
3. 分诊完成后，对评级为 A（≥7 分）的文章自动触发

---

## 资产分类（三类）

### 🔵 事实（Facts）

**定义**：可被数据验证的客观陈述。不包含作者主观判断。

**识别标准**：
- 包含具体数字、日期、百分比
- 可以追溯到原始数据源（财报、监管文件、链上数据）
- 不同来源可以交叉验证

**反例（不是事实）**：
- "NVDA 估值过高" → 这是观点，不是事实
- "市场情绪悲观" → 不可量化，降级为观点

**输出格式**：
```json
{
  "type": "fact",
  "statement": "AAVE 协议 2026 年预计产生约 $60M 费用收入",
  "value": 60000000,
  "unit": "USD",
  "time_period": "2026",
  "source_quote": "the protocol will earn ~$60 million in 2026",
  "source_article": "Grayscale Research",
  "confidence": "high",
  "cross_validatable": true,
  "tags": ["AAVE", "DeFi", "revenue"]
}
```

### 🟢 观点（Opinions）

**定义**：作者的主观判断、预测、投资建议。不能被客观验证，但可能有参考价值。

**识别标准**：
- 包含"认为""预计""应该""可能""看好/看空"等主观措辞
- 预测未来（不是陈述过去）
- 给出投资建议或方向性判断

**输出格式**：
```json
{
  "type": "opinion",
  "statement": "AAVE 代币公允价值 $80-100，牛市场景 $175",
  "author": "Grayscale Research / Zach Pandl",
  "confidence_level": "explicit",  // explicit=作者给出了置信度, implied=从上下文推断
  "time_horizon": "1 year",
  "counterpoint": "AAVE 近期经历核心贡献者离职和存款外流，基本面存在不确定性",
  "tags": ["AAVE", "valuation", "bull-case"]
}
```

### 🟣 框架（Frameworks）

**定义**：可复用的分析结构——分类法、模型、检查清单、决策树。不绑定于单一标的。

**识别标准**：
- 给出了一套可应用于其他场景的分类/步骤/模型
- 有明确的输入→处理→输出结构
- 命名了（或有能力命名）一个可引用的框架名

**输出格式**：
```json
{
  "type": "framework",
  "name": "Crypto Asset Spectrum (Commodity ↔ Financial Claim)",
  "description": "将加密资产按经济实质排列在商品→金融索取权的光谱上，决定适用哪种估值方法",
  "steps": [
    "识别资产的 economic substance（商品 vs 金融索取权）",
    "判断是否产生可观测现金流",
    "若产生现金流 → DCF / PE / 可比分析",
    "若不产生现金流 → 稀缺性 / 网络效应 / 货币溢价分析"
  ],
  "applicable_to": ["crypto-valuation", "asset-classification"],
  "source_article": "Grayscale Research — Guide to Buying the Dip",
  "reusability": "high"
}
```

---

## 执行流程

### Step 1：读取原文

用 `docs.read` 读取目标文章（路径格式：`knowledge/00_Inbox/<date>-<title>/article.md`）。

⚠️ 必须读全文，不能只看标题和摘要。资产化需要完整的上下文。

### Step 2：逐段提取

逐段扫描文章，对每个信息单元判断它属于事实/观点/框架中的哪一类：

| 判断线索 | → 分类 |
|:-----|:--:|
| 有数字 + 可溯源 + 无主观措辞 | 🔵 事实 |
| 有判断词（认为/预计/应该） + 不可量化验证 | 🟢 观点 |
| 有分类/步骤/模型结构 + 可脱离原文复用 | 🟣 框架 |

**同一条信息只归入一个分类。** 如果一条陈述既是"事实"又是"观点"→ 优先归为观点（因为选数字本身就是主观行为）。

### Step 3：质量过滤

提取后，逐条检查：

- [ ] 事实：数字是否正确转录？source_quote 是否精确匹配原文？
- [ ] 观点：是否标注了作者？是否给出了对立面（counterpoint）？
- [ ] 框架：是否命名了？是否可脱离原文独立使用？

**丢弃规则**：
- 纯叙事/过渡句 → 不提取
- 广告/推广内容 → 丢弃
- 无法独立理解的碎片 → 丢弃（如"如上所述""详见上文"）

### Step 4：结构化输出

生成一个 JSON 对象，包含三组资产：

```json
{
  "article": {
    "title": "...",
    "url": "...",
    "source": "...",
    "triage_score": 8,
    "assetized_at": "2026-06-24T..."
  },
  "facts": [...],
  "opinions": [...],
  "frameworks": [...],
  "stats": {
    "facts_count": 5,
    "opinions_count": 3,
    "frameworks_count": 2,
    "total_assets": 10
  }
}
```

### Step 5：写入知识库

用 `write.file` 将 JSON 写入：
```
knowledge/01_Assets/<date>-<title>/asset.json
```

同时用 `write.file`（mode="append"）更新资产索引：
```
knowledge/01_Assets/_index.jsonl
```
每行一条：`{"article_title": "...", "article_path": "...", "asset_count": 10, "assetized_at": "..."}`

---

## 质量标准

| 维度 | 要求 |
|:-----|:-----|
| 完整性 | 每篇 A 类文章至少提取 5 条资产（否则说明没读懂 or 文章不值得 A） |
| 准确性 | 每条事实的 source_quote 必须可在原文中找到 |
| 可用性 | 每条框架必须命名 + 可脱离原文使用 |
| 可溯源性 | 每条资产必须标注来源文章 |

---

## 注意事项

- ⚠️ 不要从 B/C 类文章提取——只处理 A 类（≥7 分）
- ⚠️ 不要编造框架——如果文章没有可复用的分析结构，框架数组可以为空
- ⚠️ 不要改写原文含义——source_quote 必须逐字引用，不要用自己的话重新表述
- ✅ 数字要带单位——"60M" 写成 `"value": 60000000, "unit": "USD"`
- ✅ 标签要统一——使用小写英文 + 连字符（如 `"defi-lending"`, `"ai-infrastructure"`）
