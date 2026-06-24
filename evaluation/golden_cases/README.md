# Golden Cases — 评测基准

> 阶段 2c 交付物。每个 Golden Case 是一个"标准答案"——人工定义了什么是对的，用于验证 Agent 行为是否正确。

## 六维 Rubric 框架

每个 Case 从六个维度打分，每维 0-4 分，满分 24 分。

| 维度 | 评分标准 | 权重 |
|:-----|:-----|:--:|
| **任务理解** (Task) | Agent 是否正确识别了用户意图？是否加载了正确的 Skill？是否做了时间周期判断？ | 20% |
| **事实准确** (Facts) | 数据是否正确（来源+数值）？是否标注了数据来源？是否交叉验证了关键数字？ | 20% |
| **工具使用** (Tools) | 是否选了正确的工具？是否走降级链而非死磕不可用源？是否避免了工具幻觉？ | 15% |
| **推理质量** (Reasoning) | 推理链是否完整（不跳因果）？是否区分了相关 vs 因果？是否给出了对立面/反驳？ | 25% |
| **风险标注** (Risk) | 是否标注了置信度？是否指出了关键风险？是否给出了"什么情况下这个结论会错"？ | 10% |
| **输出格式** (Format) | 是否符合对应 Skill 的 Schema？是否结构化？关键信息是否一眼可见？ | 10% |

## Case 文件格式

每个 Case 是一个 YAML 文件：

```yaml
id: "case_001"
title: "一句话描述"
skill: "content-triage"  # 对应 Schema 的 skill 字段
scenario: "用户场景描述"
input:
  type: "text"  # text | conversation_replay
  content: "用户的原始输入"
expected:
  task: "Agent 应该做什么"
  critical_facts:  # 必须出现的数字/事实
    - "fact 1"
    - "fact 2"
  must_use_tools:  # 必须调用的工具
    - "web.fetch"
  must_not_do:  # 绝对不能做的事
    - "用 LLM 记忆中的数据"
  output_assertions:  # Schema 级别断言
    - "output.entries[0].scores.total >= 7"
    - "output.entries 至少有 3 条"
rubric:
  task: {score: 0, note: ""}
  facts: {score: 0, note: ""}
  tools: {score: 0, note: ""}
  reasoning: {score: 0, note: ""}
  risk: {score: 0, note: ""}
  format: {score: 0, note: ""}
```

## 使用方式

1. 修改 Agent 代码后，重新跑 Golden Cases
2. 每次运行对比 Agent 输出 vs expected
3. 人工按 Rubric 打分
4. 总分 < 18 分 → 阻塞发布

## 当前覆盖

| Case | Skill | 输入 | 测试重点 |
|:-----|:-----|:-----|:-----|
| case_001 | content-triage | 5 篇混合 URL 批量分诊 | 多源抓取 + 五维评分 + 台账追加 |
| case_002 | macro-analysis | 宏观环境评估 | 时间周期 + PMI/CPI-PPI/就业 + FRED 调用 |
| case_003 | us-stock-analysis | NVDA 估值分析 | 三层分析 + 周期陷阱 + 交叉验证 + 红方挑战 |
