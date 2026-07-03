"""Cron Agent — scheduled multi-agent pipeline for daily/weekly reports.

Phase 4b: Pre-configured skill combinations run by cron trigger, sharing
the same Supervisor + 4-Agent pool as the interactive research pipeline.

Architecture:
  Cron trigger → CronAgent.run_template() → Supervisor.run()
      → DataCollector (RAG + FRED + web) + Researcher (pre-set skills)
      → Red-Team → Editor
      → write to knowledge/02_Daily/YYYY-MM-DD-{type}.md

Usage:
  from cagent_os.multi_agent.cron_agent import CronAgent
  agent = CronAgent()
  result = await agent.run_daily_crypto()  # generate today's crypto brief
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cagent_os.multi_agent.supervisor import Supervisor, SupervisorConfig, SupervisorResult

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_KNOWLEDGE_ROOT = _PROJECT_ROOT / "knowledge"
_DAILY_DIR = _KNOWLEDGE_ROOT / "02_Daily"


# ── Report templates ────────────────────────────────────────────────

@dataclass
class ReportTemplate:
    """Pre-configured template for a scheduled report."""
    template_id: str
    name: str              # e.g. "加密市场日报"
    frequency: str         # "daily" | "weekly" | "on_demand"
    query: str             # the structured query to send to Supervisor
    skills: list[str]      # pre-loaded skills for Researcher
    output_dir: Path       # where to save the report
    include_sections: list[str]  # required sections


# Pre-defined templates
DEFAULT_TEMPLATES: list[ReportTemplate] = [
    ReportTemplate(
        template_id="crypto_daily",
        name="加密市场日报",
        frequency="daily",
        query=(
            "生成今日加密货币市场日报。请覆盖: "
            "1) BTC/ETH 价格与24h涨跌幅 "
            "2) 恐惧贪婪指数与市场情绪 "
            "3) 稳定币市值变化(USDT/USDC) "
            "4) DeFi TVL 趋势 "
            "5) 24h重要新闻与事件(最多5条) "
            "6) 宏观环境速览(10Y国债/联邦利率/FOMC日程) "
            "7) 综合判断:短期(1-4周)风险偏好方向"
        ),
        skills=["crypto-analysis", "crypto-funds-flow-analysis", "macro-analysis"],
        output_dir=_DAILY_DIR,
        include_sections=["价格行情", "市场情绪", "资金面", "DeFi", "重要新闻", "宏观速览", "综合判断"],
    ),
    ReportTemplate(
        template_id="macro_weekly",
        name="宏观环境周报",
        frequency="weekly",
        query=(
            "生成本周宏观环境周报。请覆盖: "
            "1) 本周关键经济数据回顾(CPI/PPI/非农/PMI) "
            "2) 美联储政策动态(讲话/会议/预期变化) "
            "3) 美债收益率曲线变化(2Y/10Y利差) "
            "4) 外围市场(DXY/SPX/VIX/黄金/原油) "
            "5) 地缘政治风险更新 "
            "6) 下周关注:重要数据发布(FOMC/CPI/NFP) "
            "7) 对风险资产的综合影响判断"
        ),
        skills=["macro-analysis", "tech-sector-bridge"],
        output_dir=_DAILY_DIR,
        include_sections=["数据回顾", "政策动态", "利率曲线", "外围市场", "地缘风险", "下周关注", "综合判断"],
    ),
]


@dataclass
class CronResult:
    """Result of a scheduled report run."""
    template_id: str
    name: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    output_path: str = ""
    supervisor_result: SupervisorResult | None = None
    markdown: str = ""
    error: str = ""


class CronAgent:
    """Runs scheduled multi-agent pipelines for periodic reports.

    Shares the Supervisor + 4-Agent pool with the interactive pipeline.
    """

    def __init__(self) -> None:
        self._templates: dict[str, ReportTemplate] = {
            t.template_id: t for t in DEFAULT_TEMPLATES
        }

    @property
    def available_templates(self) -> list[str]:
        return list(self._templates.keys())

    def get_template(self, template_id: str) -> ReportTemplate | None:
        return self._templates.get(template_id)

    # ── Template runners ──

    async def run_daily_crypto(self) -> CronResult:
        """Generate today's crypto daily briefing."""
        return await self.run_template("crypto_daily")

    async def run_weekly_macro(self) -> CronResult:
        """Generate this week's macro report."""
        return await self.run_template("macro_weekly")

    async def run_template(self, template_id: str) -> CronResult:
        """Run a pre-defined report template through the Supervisor pipeline."""
        template = self._templates.get(template_id)
        if not template:
            return CronResult(
                template_id=template_id,
                name="Unknown",
                error=f"Template '{template_id}' not found. Available: {self.available_templates}",
            )

        logger.info("CronAgent: running template %s (%s)", template_id, template.name)

        try:
            # Step 1: Run Supervisor pipeline
            config = SupervisorConfig(timeout_seconds=300)
            supervisor = Supervisor(config=config)
            result = await supervisor.run(template.query)

            # Step 2: Format output as markdown
            markdown = self._format_report(template, result)

            # Step 3: Write to Obsidian vault
            today = datetime.now().strftime("%Y-%m-%d")
            template.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = template.output_dir / f"{today}-{template_id}.md"
            output_path.write_text(markdown, encoding="utf-8")

            logger.info("CronAgent: report saved to %s", output_path)

            return CronResult(
                template_id=template_id,
                name=template.name,
                output_path=str(output_path),
                supervisor_result=result,
                markdown=markdown,
            )

        except Exception as exc:
            logger.error("CronAgent failed: %s", exc)
            return CronResult(
                template_id=template_id,
                name=template.name,
                error=str(exc),
            )

    async def run_all_daily(self) -> list[CronResult]:
        """Run all daily templates."""
        results = []
        for t in self._templates.values():
            if t.frequency == "daily":
                results.append(await self.run_template(t.template_id))
        return results

    # ── Formatting ──

    def _format_report(self, template: ReportTemplate, result: SupervisorResult) -> str:
        """Format Supervisor output as a clean markdown daily report."""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%d %H:%M UTC")
        today = now.strftime("%Y-%m-%d")

        lines = [
            "---",
            f"title: \"{template.name} — {today}\"",
            f"date: \"{today}\"",
            f"generated: \"{ts}\"",
            f"type: cron",
            f"template: {template.template_id}",
            "---",
            "",
            f"# {template.name}",
            f"> 生成时间: {ts} | 引擎: CagentOS Phase 4 Supervisor + 4-Agent",
            "",
        ]

        # Data summary from collector
        if result.raw_data:
            lines.append("## 📊 数据源")
            lines.append(f"共采集 {len(result.raw_data.items)} 条数据点。{result.raw_data.source_summary}")
            lines.append("")

        # RAG results
        if result.raw_data and result.raw_data.rag_results:
            lines.append("## 📚 相关知识库")
            for i, r in enumerate(result.raw_data.rag_results[:3], 1):
                meta = r.get("metadata", {})
                lines.append(f"{i}. **{meta.get('title', '?')}** (相似度 {r.get('similarity', 0):.2f})")
                lines.append(f"   _{r.get('text', '')[:200]}_")
            lines.append("")

        # Analysis summary
        if result.summary:
            lines.append("## 🎯 综合判断")
            lines.append(result.summary.conclusion)
            lines.append("")
            if result.summary.key_evidence:
                lines.append("### 关键数据")
                for e in result.summary.key_evidence[:5]:
                    lines.append(f"- {e}")
                lines.append("")

        # Red team
        if result.audit:
            lines.append("## ⚠️ 风险警示")
            lines.append(f"- 严重程度: **{result.audit.severity}**")
            lines.append(f"- {result.audit.recommendation}")
            lines.append("")

        # Errors
        if result.errors:
            lines.append("## ⚠️ 生成异常")
            for e in result.errors:
                lines.append(f"- {e}")
            lines.append("")

        lines.append("---")
        lines.append(f"*本报告由 CagentOS Cron Agent 自动生成，数据截至 {ts}。仅供参考，不构成投资建议。*")

        return "\n".join(lines)


# ── CLI entry point ──

async def run_cron_daily() -> None:
    """CLI entry: run all daily templates."""
    agent = CronAgent()
    print("Running daily reports...")
    results = await agent.run_all_daily()
    for r in results:
        if r.error:
            print(f"  ❌ {r.name}: {r.error}")
        else:
            print(f"  ✅ {r.name} → {r.output_path}")


def run_cron_daily_sync() -> None:
    """Sync wrapper for CLI."""
    asyncio.run(run_cron_daily())
