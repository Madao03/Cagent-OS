# Provenance Baseline Predictions

**Written**: 2026-07-24, before running real agent baseline.
**Purpose**: Record expectations BEFORE measuring, so they can be falsified.

## Five-Bucket Predictions

| Bucket | Predicted % | Reasoning |
|:-------|:----------:|:----------|
| **Derived values** (同比/比率/利润率/mNAV) | **40-60%** | P1 derived chain not built. Investment research output is full of YoY, margins, ratios. Largest known blind spot. |
| **Text citation values** (RAG/news/web numbers) | **15-30%** | Tools like rag.search / websearch / panews return prose, not structured fields. Numbers inside text chunks won't match Registry facts. Second largest bucket. |
| **Normalization gaps** (correct number, format mismatch) | **10-20%** | Chinese magnitudes, percentages, negative formats. Most covered, but real output has long tail. |
| **Scanner blind spots** (number not detected at all) | **<5%** | `\w` → ASCII fix resolved main gap. Table/paren numbers may have residual misses. |
| **True hallucinations** (Registry has nothing, not derivable) | **<5%** | Routing rules 6/7 (EDGAR mandatory, crypto.* mandatory) block most cases. Agent sometimes uses memory numbers but rarely for hard data. |

**Overall untraced rate prediction**: 30-50% of data numbers.

## What This Measures

If predictions are right → we understand the system's output characteristics.
If predictions are wrong → the gap reveals where our mental model is off.

The most important comparison:
- If derived values are >50% → P1 derived chain must be next priority
- If text citations are >20% → need text_citation fact extraction before P1
- If true hallucinations are >10% → routing rules need strengthening

## Test Cases (to be selected from Golden Cases + derived-heavy scenarios)

1. "小鹏 Q1 2026 同比怎么样" → derived (YoY)
2. "对比 NVDA 和 AAPL 的营收增速" → cross-source + derived
3. "MSTR 的 mNAV 现在是多少" → multi-layer derived
4. "腾讯 2025 Q3 营收" → data-not-available path ★
5. "BTC 现在是高估还是低估" → qualitative + numbers mixed

## Post-Run Checklist

- [ ] Classify every untraced number into one of 5 buckets
- [ ] Compare actual % vs predicted % per bucket
- [ ] Identify which predictions were most wrong and why
- [ ] Decide P1 priority based on derived values %
