"""Provenance gate — turns the checker from a post-hoc reporter into a generation gate.

When untraced numbers are detected in agent output, the gate:
1. Does NOT yield the output immediately
2. Injects a feedback message telling the agent which numbers lack sources
3. Gives the agent one chance to regenerate (call tools or declare unavailable)
4. If still untraced after retry: yields with visible ⚠️ markers

This is the mechanism that makes routing rules STRUCTURAL rather than advisory:
  - Tencent (no data): agent must declare "数据不可得" instead of hallucinating
  - FRED (has data but unused): agent must call FRED instead of answering from memory

The gate and the "data unavailable" terminal state are co-designed:
  gate blocks → agent needs an exit → "declare unavailable" is that exit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cagent_os.provenance.checker import CheckResult, check_provenance, annotate_output
from cagent_os.provenance.fact_registry import FactRegistry

logger = logging.getLogger(__name__)

# Maximum regeneration attempts before giving up and outputting with markers.
MAX_PROVENANCE_RETRIES = 1


@dataclass
class GateDecision:
    """Result of the provenance gate check."""
    action: str           # "pass" | "regenerate" | "output_with_markers"
    untraced_summary: str # human-readable list of untraced numbers (for agent feedback)
    check_result: CheckResult
    retry_count: int


def evaluate_gate(
    output_text: str,
    registry: FactRegistry,
    retry_count: int = 0,
) -> GateDecision:
    """Evaluate whether the agent output passes the provenance gate.

    Returns:
        GateDecision with action:
        - "pass": all numbers traced, output is good
        - "regenerate": untraced numbers found, agent should try again
        - "output_with_markers": max retries exceeded, output with visible warnings
    """
    result = check_provenance(output_text, registry)

    # No untraced numbers → pass
    if result.untraced == 0 and result.sign_conflicts == 0:
        return GateDecision(
            action="pass",
            untraced_summary="",
            check_result=result,
            retry_count=retry_count,
        )

    # Untraced list
    untraced_list = ", ".join(u.raw for u in result.untraced_numbers[:15])
    conflict_list = ""
    if result.sign_conflicts:
        conflict_list = "\n符号冲突: " + "; ".join(
            s.raw for s in result.sign_conflict_numbers[:5]
        )

    # ★ Derived-chain hint: if untraced numbers look like ratios/percentages,
    # suggest using the [derivations] block (P1 derived chain).
    derived_hint = _build_derived_hint(result)

    # ★ Routing-aware feedback: different signal for out-of-coverage vs untraced.
    # When the code-level routing has already determined that this ticker is
    # out of coverage (no CIK, not SEC-registered), the correct response is
    # NOT "go find data elsewhere" — it's "declare unavailability."
    # Sending a generic "go find sources" signal causes the agent to search
    # the web and fabricate numbers from unreliable text (motivated citation).
    #
    # ★ P1 expansion: also detect tickers where ALL structured tools failed
    # (not just not_sec_registered). These have zero facts but did have tool
    # calls — the agent tried and everything failed. Web search is the only
    # option, and the output MUST declare "未经结构化验证."
    ooc = registry.out_of_coverage
    atf = registry.all_tools_failed
    all_ooc = {**ooc, **atf}  # merge: institutional + all-tools-failed
    if all_ooc:
        ooc_tickers = ", ".join(all_ooc.keys())
        ooc_detail_parts = []
        for t, r in all_ooc.items():
            if r == "all_structured_tools_failed":
                ooc_detail_parts.append(f"{t}: 所有结构化数据源均失败（akshare 未收录 / 非SEC注册等），"
                                         "当前仅外网搜索文本可用")
            else:
                ooc_detail_parts.append(f"{t}={r}")
        ooc_detail = "; ".join(ooc_detail_parts)
        # ★ Separate institutional vs tool-failure feedback
        inst_parts = []
        fail_parts = []
        for t, r in all_ooc.items():
            if r == "all_structured_tools_failed":
                fail_parts.append(t)
            else:
                inst_parts.append(t)
        feedback = (
            f"以下数字没有可靠来源（未在工具返回中找到）: {untraced_list}"
            f"{conflict_list}\n"
            f"{derived_hint}"
            f"⚠️ 结构化数据不可得: {ooc_tickers}（{ooc_detail}）。\n"
            f"这些标的的结构性数据无法通过工具获取。\n"
            f"唯一可接受的输出：对每个不可得的标的，明确声明「数据来源为外网搜索，未经结构化验证」。\n"
            f"禁止：以权威感输出这些数字。外网数据 ≠ 官方数据。诚实声明比装饰性表格更有价值。"
        )
        if fail_parts and not inst_parts:
            feedback += (
                f"\n特别说明：{', '.join(fail_parts)} 的行情/财报工具均返回失败，"
                f"不是'没去调'而是'调了全失败'——这是数据可得性限制，请如实告知用户。"
            )
    else:
        feedback = (
            f"以下数字没有可靠来源（未在工具返回中找到）: {untraced_list}"
            f"{conflict_list}\n"
            f"{derived_hint}"
            f"请选择:\n"
            f"  1. 调用工具获取这些数据（如 financial.edgar.facts / financial.fred / crypto.* ）\n"
            f"  2. 如果数据确实不可得（如港股季度数据、未覆盖的标的），"
            f"这正是展示职业素养的时机——请明确声明「数据不可得」，解释原因。"
            f"诚实是最高质量的输出，不要编造数字。"
        )

    # First attempt with untraced → regenerate
    if retry_count < MAX_PROVENANCE_RETRIES:
        return GateDecision(
            action="regenerate",
            untraced_summary=feedback,
            check_result=result,
            retry_count=retry_count,
        )

    # Max retries exceeded → output with markers
    return GateDecision(
        action="output_with_markers",
        untraced_summary=feedback,
        check_result=result,
        retry_count=retry_count,
    )


def apply_markers(text: str, result: CheckResult) -> str:
    """Apply visible ⚠️ markers to untraced numbers in the output."""
    return annotate_output(text, result, mode="production")


# ── Derived-chain hint builder (P1) ─────────────────────────────

def _build_derived_hint(result: CheckResult) -> str:
    """Build feedback for untraced numbers, forked by number type.

    Two categories:
      Rate/percentage → can be derived from registry facts → suggest [derivations]
      Absolute amount  → must come from tools or not be reported → suggest tool call
    """
    _AMOUNT_UNITS = {"亿", "万", "元", "¥", "$", "￥", "T", "B", "M", "K"}

    rate_looking: list[str] = []
    amount_looking: list[str] = []

    for u in result.untraced_numbers:
        raw = u.raw
        val = abs(u.value)

        has_amount = any(un in raw for un in _AMOUNT_UNITS) and "%" not in raw

        if has_amount:
            amount_looking.append(raw)
        elif "%" in raw and 0 < val <= 100:
            rate_looking.append(raw)
        elif 0 < val < 1:
            rate_looking.append(raw)
        elif 1 < val < 50 and all(c not in raw for c in "¥$%亿万亿TBMK"):
            rate_looking.append(raw)

    parts: list[str] = []

    if rate_looking:
        seen = set(); unique = []
        for d in rate_looking:
            if d not in seen: seen.add(d); unique.append(d)
        items = ", ".join(unique[:5])
        parts.append(
            f"💡 以下数字看起来像计算派生值（比率/百分比）: {items}\n"
            f"   这类数字通常是计算所得，必须在 [derivations] 块中声明公式与父节点。\n"
            f"   格式示例:\n"
            f"   [derivations]\n"
            f"   (revenue@2025Q4 - revenue@2024Q4) / abs(revenue@2024Q4) = 0.382\n"
            f"   (price@MSFT - fifty_two_week_high@MSFT) / fifty_two_week_high@MSFT = -0.103\n"
            f"   capex@GOOGL_Q1 + capex@AMZN_Q1 + capex@MSFT_Q1 = 110.8\n"
            f"   [/derivations]\n"
            f"   引用格式: caliber@period（如 revenue@2025Q4）或 fact_id（如 f:0:3）。\n"
            f"   也可引用 quote.query 的字段：price@MSFT、fifty_two_week_high@MSFT。\n"
        )

    if amount_looking:
        seen = set(); unique = []
        for d in amount_looking:
            if d not in seen: seen.add(d); unique.append(d)
        items = ", ".join(unique[:5])
        parts.append(
            f"⚠️ 以下数字是绝对金额（含亿/万/元等单位），无法从已有数据派生: {items}\n"
            f"   请调用相应的数据工具获取这些数字（如 financial.edgar.release），\n"
            f"   或如果数据不可得，不要报告这些数字。\n"
        )

    return "\n".join(parts)
