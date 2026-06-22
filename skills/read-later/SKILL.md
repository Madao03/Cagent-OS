---
name: read-later
description: 三层渐进式披露阅读系统 — 甩 URL/文件/纯文本，先出 L1 关键词卡片，追问展开 L2 观点摘要，再追问拉 L3 原文摘录。触发：URL、文件路径、>200 字纯文本。命令：rL list / rL search。
category: research
---

# Read Later — 三层渐进式披露

> **不是「read it later」，是「understand it now, read it never」。**

本质是把 Skill 渐进式披露的 AI 设计模式搬到人类信息消费上。用户甩 URL/文件/文本 → 系统自动抓取 → 提取核心信息 → 先只给关键词卡片。想知道更多再追问，不想知道就跳过。

## 触发规则

| 用户动作 | 触发条件 | 行为 |
|:--------|:--------|:-----|
| `存档 <URL>` / `save <URL>` | 命令匹配 | 抓取 → 出 L1 卡片 + 写入 `knowledge/00_Inbox/` |
| `rL <URL>` | 命令匹配 | 同上，rL 是 read-later 缩写 |
| 发送 URL（bare URL，无附带文字） | `http://` 或 `https://` 开头，用户未附加任何指令 | 默认视为存档意图 → 抓取 → 出 L1 卡片 + 写入 |
| 发送 URL + 其他问题 | `http://` 或 `https://` 开头，用户同时问了具体问题 | 直接用 `web.fetch` 回答，不走 read-later 协议 |
| 发送文件路径 | `.pdf` `.md` `.txt` 结尾 | 提取文本 → 出 L1 卡片 |
| 粘贴长文本 | 无 URL/路径，纯文本 > 200 字 | 直接分析 → 出 L1 卡片 |
| `rL list` | 命令匹配 | 显示当前队列 |
| `rL search <关键词>` | 命令匹配 | 搜索已保存条目 |
| 追问 L1 关键词 | 匹配已有条目标签 | 展开 L2 |

**意图判断优先级**: 命令关键词 > bare URL 默认存档 > URL+问题自动降级为查询。用户说「存档」「save」「read later」「rL」「收藏」「摘录」「L1」等词时，明确走 read-later 协议。

## 三层渐进式披露

```
L1: 关键词卡片（永远可见、零摩擦）
"MSTR — 币股 / mNAV 2.1x / 可转债套利 / 空头"
3-5 个标签 + 一句话结论
如果涉及 ticker，附带当前股价和涨跌幅

    ↓ 用户追问 "mNAV 什么情况？"

L2: 观点摘要（按需拉取）
"mNAV 从3月3.5x压缩到2.1x，三个原因：
①BTC回调-15% ②可转债稀释 ③空头挤压
作者认为当前折价已过度..."
2-3 段，每段 3-5 句

    ↓ 用户追问 "原文怎么说的？"

L3: 原文摘录（最后一级）
"> 原文第4段: The short squeeze dynamics...
[完整段落引用 + 行号定位]"
```

## 数据存储

使用 `knowledge/00_Inbox/` 目录下的 .md 文件（Obsidian 兼容）：

- **L1 卡片** → `knowledge/00_Inbox/{slug}.md`（新建文件，包含 frontmatter + L1 内容）
- **L2 展开** → 追加到同一文件（`## L2: 观点摘要` 段落）
- **L3 原文** → 追加到同一文件（`## L3: 原文摘录` 段落）

文件命名：`{YYYY-MM-DD}-{关键词slug}.md`，如 `2026-06-10-mstr-mnav-analysis.md`

每篇 .md 文件结构：
```markdown
---
date: YYYY-MM-DD
source_url: https://...
source_type: web|pdf|md|plaintext
tags: [tag1, tag2, tag3]
tickers: [MSTR, BTC]
confidence: high|medium|low
---

# {标题}

## L1: 关键词卡片

**标签**: {keyword1} / {keyword2} / {keyword3}

**一句话结论**: {方向判断 + 为什么}

## L2: 观点摘要
(用户追问后追加)

## L3: 原文摘录
(用户追问后追加)
```

## 输入路由

根据 URL/文件类型，走不同抓取通道：

| 输入类型 | 抓取方式 |
|:--------|:--------|
| 微信公众号 URL (`mp.weixin.qq.com`) | **`web.fetch_weixin`**（Playwright 无头浏览器，绕过反爬） |
| 其他 URL | `web.fetch` 工具抓取 |
| `*.md` / `*.txt` (本地) | `docs.read` 工具直读 |
| 纯文本（无 URL/路径） | 直接分析 |

## Workflow

### Step 1: 接收输入 → 抓取

```
if 输入是微信公众号 URL (mp.weixin.qq.com):
    → web.fetch_weixin 抓取（Playwright 无头浏览器）
    → 如果失败 → web.fetch 试 → financial.websearch 搜转载
elif 输入是其他 URL:
    → web.fetch 抓取 → 获取内容
elif 输入是文件路径:
    → docs.read 读取
elif 输入是纯文本 > 200 字:
    → 直接用
else:
    → 不触发（普通对话）
```

### Step 2: 提取 L1 关键词卡片

从全文提取 **3-5 个核心关键词/标签 + 一句话结论**。

要求：
- 标签是投资人视角的概念，不是通用词（"市场" ❌，"mNAV压缩" ✅）
- 一句话结论必须有判断方向（利好/利空/中性 + 为什么）
- 如果涉及 ticker，通过 FinancialPlugin 附加当前行情数据

### Step 3: 保存 + 出 L1（强制）

**MUST use `write.file` tool to save the L1 card to disk FIRST, then output to user.**

This is NOT optional — the entire purpose of read-later is to persist the card for future retrieval. If you only output to console without saving, the entry is lost.

Call `write.file` with:
- `path`: `knowledge/00_Inbox/{YYYY-MM-DD}-{slug}.md`
- `content`: the markdown card content (see template below)

File content template:
```markdown
---
date: YYYY-MM-DD
source_url: {原始URL}
source_type: web
tags: [{tag1}, {tag2}, {tag3}]
confidence: {high|medium|low}
---

# {标题}

## L1: 关键词卡片

**标签**: {keyword1} / {keyword2} / {keyword3}

**一句话结论**: {方向判断 + 为什么}
```

After saving, output this to user:
```
📌 rL #{slug}  {title}
🏷 {keyword1} / {keyword2} / {keyword3} / {keyword4}
💬 {一句话结论}
📁 saved to: knowledge/00_Inbox/{YYYY-MM-DD}-{slug}.md
```

### Step 4: L2 展开（用户追问时）

用户追问某个关键词或说「展开」「详细点」→ 从原文提取该关键词相关的 2-3 段观点摘要。
追加写入同一 .md 文件的 `## L2: 观点摘要` 段。

### Step 5: L3 原文（用户追问时）

用户说「原文」「原文怎么说」「具体段落」→ 返回相关段落的原文引用 + 行号定位。
追加写入同一 .md 文件的 `## L3: 原文摘录` 段。

### 管理命令

`rL list` — 列出 `knowledge/00_Inbox/` 下的所有 .md 文件（用 `docs.read` 读取 `knowledge/00_Inbox/`）

`rL search <关键词>` — 读取 `knowledge/00_Inbox/` 下的文件，按关键词匹配

## 关联能力

| 工具 | 用途 |
|:------|:-----|
| `web.fetch_weixin` | 微信公众号 URL → Playwright 抓取（绕过反爬） |
| `web.fetch` | 普通 URL → 网页内容抓取（Jina AI + 直连 fallback） |
| `financial.websearch` | web.fetch 失败时搜索转载/镜像 |
| `docs.read` | 本地文件读取 |
| `write.file` | 写入 `knowledge/00_Inbox/` 下的 .md 文件 |
| `Skill` | 加载 us-stock-analysis / crypto-analysis 获取行情 |

## 输出格式规范

- L1 关键词 ≤ 5 个，每个 ≤ 10 字
- L1 一句话结论 ≤ 50 字
- L2 每个观点 3-5 句
- L3 原文引用标注段落/行号
- 所有推理性内容标注置信度：🟢高 🟡中 🔴低

## 注意事项

- ❌ **不是「存起来以后看」**——是「现在就帮你提炼完」
- ❌ **不要对每个 URL 都输出完整摘要**——默认只出 L1，用户追问才展开
- ✅ **ticker 识别后主动附加行情**——不用用户再手动查
- ✅ **交叉引用自动关联**——两篇都提同一 ticker 的文章自动标注
- ✅ **如果抓取失败**→ 标注 `[抓取失败: {原因}]`，不阻塞，用户可手动粘贴内容
