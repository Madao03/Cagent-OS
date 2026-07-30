"""AgentRuntime wrapper — produces a callable for Supervisor's Researcher step.

The Supervisor expects `agent_runner: Callable[[str], Awaitable[str]]` so it
can delegate deep analysis to the full AgentRuntime (ReAct + skills + memory
+ data layer). This module builds that callable, encapsulating:

  1. Conversation lifecycle (create → run → extract assistant message)
  2. Sync→async bridge (AgentRuntime.run() is a sync iterator because it
     owns its own event loop via AsyncBridge; we wrap with run_in_executor)
  3. Output contract — append a "隐藏 JSON 块" hint to the user_content
     so downstream `_parse_analysis_output` can extract structured fields
     (ValuationMetrics / DataCitation) without fragile regex on prose

Design choice (2026-07-20):
  We chose prompt-hint + trailing JSON block over full Pydantic enforcement
  because:
    - 15 existing skills already produce raw_markdown; forcing structured
      output would risk Golden Cases regressions
    - DeepSeek V4 Pro follows the hidden-JSON convention reliably
    - When LLM doesn't comply, parser falls back to regex gracefully
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable
from uuid import uuid4

from cagent_os.agents.run_engine import AgentRuntime
from cagent_os.conversations.service import ConversationService
from cagent_os.user_skills import UserSkillService

logger = logging.getLogger(__name__)


# ── Prompt hint appended to every Researcher query ────────────────────
# We ask the LLM to emit a trailing HTML comment with a JSON payload.
# The parser in supervisor._parse_analysis_output looks for this block
# first and falls back to regex when absent.
RESEARCHER_OUTPUT_HINT = """

---
**[输出规范 — 必须遵守]**
完成分析后,在回答最末尾追加一个隐藏的 JSON 块(用 HTML 注释包裹,用户不可见),
包含以下字段(缺失字段允许省略):

<!-- ANALYSIS_JSON:
{
  "ticker": "NVDA",
  "thesis": "1-3 句核心判断(必填)",
  "risks": ["风险1", "风险2"],
  "catalysts": ["催化剂1"],
  "pe_forward": 35.2,
  "pe_ttm": 42.1,
  "ev_ebitda": 28.5,
  "pb": 45.0,
  "dcf_implied_value": 580.0,
  "recommendation": "hold",
  "confidence": "medium",
  "citations": [
    {"metric": "Forward PE", "value": 35.2, "source": "yfinance", "confidence": 0.9}
  ]
}
-->

说明:
- ticker / thesis 必填,其余按场景可选
- 数字字段用 number,不要带引号或单位
- recommendation ∈ {accumulate, hold, reduce, avoid}
- confidence ∈ {high, medium, low}
- JSON 必须合法(无尾逗号、无注释)
"""


# ── Principal / user identity for supervisor-spawned runs ─────────────
SUPERVISOR_PRINCIPAL = "supervisor"
SUPERVISOR_USER_ID = "supervisor_researcher"


def make_researcher_runner(
    *,
    run_engine: AgentRuntime,
    conversation_service: ConversationService,
    user_skill_service: UserSkillService,
    principal_id: str = SUPERVISOR_PRINCIPAL,
    user_id: str = SUPERVISOR_USER_ID,
) -> Callable[[str], Awaitable[str]]:
    """Build an async callable that runs the full AgentRuntime for one query.

    The returned callable matches `SupervisorConfig.agent_runner` signature.
    Each call:
      1. Loads the supervisor's skill snapshot (all 9 core skills)
      2. Creates a one-shot conversation (unique ID per call)
      3. Runs the ReAct loop with the query + RESEARCHER_OUTPUT_HINT
      4. Returns the final assistant markdown (including the trailing JSON block)
    """
    # Pre-load skill snapshot once — all calls reuse it
    skill_snapshot = user_skill_service.load_snapshot(user_id)
    logger.info(
        "Researcher runner initialized principal=%s user=%s skills=%d",
        principal_id, user_id, len(skill_snapshot.documents),
    )

    async def runner(query: str) -> str:
        # Use a unique conversation_id per call so each sub-agent run
        # produces its own trace span (Phase 4d Langfuse requirement)
        conversation_id = f"sup-{uuid4().hex[:12]}"
        # Create conversation via service (it assigns a new id internally,
        # but we pass our id-via-override path below for traceability)
        try:
            conversation = conversation_service.create_conversation(
                principal_id=principal_id,
                user_id=user_id,
                user_skill_snapshot=skill_snapshot,
            )
            conv_id = conversation.conversation_id
        except Exception as exc:
            logger.exception("Researcher runner: create_conversation failed: %s", exc)
            return ""

        logger.info(
            "Researcher runner invoked conv=%s query_len=%d",
            conv_id, len(query),
        )

        # Build augmented content with output contract hint
        augmented_content = f"{query}\n{RESEARCHER_OUTPUT_HINT}"

        # AgentRuntime.run() is a SYNC iterator (it owns its event loop
        # via AsyncBridge). Wrap in run_in_executor so we can await it
        # from the Supervisor's async context without blocking the loop.
        loop = asyncio.get_event_loop()

        def _run_sync() -> str:
            final_content = ""
            try:
                for event in run_engine.run(
                    conversation_id=conv_id,
                    principal_id=principal_id,
                    user_content=augmented_content,
                ):
                    if event.type == "message.assistant_added":
                        final_content = event.content or ""
                    # Other events (run.started, tool_*, run.completed)
                    # are emitted for trace but we only need final text
            except Exception as exc:
                logger.exception(
                    "Researcher runner: AgentRuntime.run failed conv=%s: %s",
                    conv_id, exc,
                )
            return final_content

        try:
            result = await loop.run_in_executor(None, _run_sync)
            logger.info(
                "Researcher runner completed conv=%s output_len=%d",
                conv_id, len(result),
            )
            return result
        except Exception as exc:
            logger.exception(
                "Researcher runner: executor failed conv=%s: %s", conv_id, exc,
            )
            return ""

    return runner


# ── Default-runner factory (used by CronAgent) ────────────────────────
def build_default_runner() -> Callable[[str], Awaitable[str]] | None:
    """Construct a default runner using the global config.

    Returns None if any dependency is missing (RAG/MCP/LLM backend) so
    that SupervisorConfig.agent_runner stays None and the Supervisor
    falls back to template mode gracefully.
    """
    try:
        from cagent_os.config import get_settings
        from cagent_os.conversations.repository import InMemoryConversationRepository
        from cagent_os.conversations.service import ConversationService
        from cagent_os.llm.factory import create_backend
        from cagent_os.plugins import ToolDispatcher, ToolRegistry
        from cagent_os.plugins.financial.plugin import FinancialPlugin
        from cagent_os.plugins.financial.toolkit import build_financial_toolkit
        from cagent_os.plugins.read.plugin import ReadPlugin
        from cagent_os.plugins.skills.plugin import SkillsPlugin
        from cagent_os.plugins.web.plugin import WebPlugin
        from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService
        from pathlib import Path
    except ImportError as exc:
        logger.warning("Default runner unavailable (missing deps): %s", exc)
        return None

    settings = get_settings()

    # Build minimal runtime dependencies
    conversation_repository = InMemoryConversationRepository()
    conversation_service = ConversationService(repository=conversation_repository)

    project_root = Path(__file__).resolve().parent.parent.parent.parent
    skills_data_dir = (project_root / settings.skills_data_dir).resolve()
    shared_skills_dir = (
        (project_root / settings.shared_skills_dir).resolve()
        if settings.shared_skills_dir else None
    )
    user_skill_service = UserSkillService(
        FilesystemUserSkillStore(skills_data_dir, shared_skills_dir=shared_skills_dir)
    )

    try:
        llm_backend = create_backend(settings)
    except Exception as exc:
        logger.warning("LLM backend unavailable for default runner: %s", exc)
        return None

    # Build toolkit + plugins (same as app.py create_app)
    toolkit = build_financial_toolkit(settings=settings, mcp_session_manager=None)
    registry = ToolRegistry()
    registry.register_plugin(FinancialPlugin(settings=settings, toolkit=toolkit, data_layer=None, rag_service=None))
    registry.register_plugin(WebPlugin(settings=settings))
    registry.register_plugin(ReadPlugin(settings=settings))
    from cagent_os.plugins.crypto.plugin import CryptoPlugin
    registry.register_plugin(CryptoPlugin())
    registry.register_plugin(
        SkillsPlugin(
            user_skill_service=user_skill_service,
            skills_data_dir=skills_data_dir,
            shared_skills_dir=shared_skills_dir,
        )
    )
    executor = ToolDispatcher(registry=registry)

    run_engine = AgentRuntime(
        conversation_service=conversation_service,
        event_store=conversation_repository,
        llm_backend=llm_backend,
        capability_executor=executor,
        settings=settings,
    )

    return make_researcher_runner(
        run_engine=run_engine,
        conversation_service=conversation_service,
        user_skill_service=user_skill_service,
    )
