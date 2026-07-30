from __future__ import annotations

from collections.abc import Iterator
import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cagent_os.agents.run_engine import AgentRuntime
from cagent_os.config.cost_tracker import BudgetExceeded, ConcurrencyExceeded, CostTracker
from cagent_os.conversations.service import ConversationService
from cagent_os.interfaces.http.auth_context import require_principal_id, resolve_principal_id
from cagent_os.interfaces.http.rate_limiter import limiter
from cagent_os.interfaces.http.run_events import project_stream_payload
from cagent_os.interfaces.http.schemas import (
    OneshotRunRequest,
    PostMessageRequest,
    SupervisorRunRequest,
    SupervisorRunResponse,
)
from cagent_os.shared.logging_utils import build_log_extra, format_log_context
from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService

logger = logging.getLogger(__name__)


def build_runs_router(
    *,
    run_engine: AgentRuntime,
    conversation_service: ConversationService,
    user_skill_service: UserSkillService,
    cost_tracker: CostTracker | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/conversations/{conversation_id}/messages")
    @limiter.limit("5/minute")
    def post_message(conversation_id: str, payload: PostMessageRequest, request: Request) -> StreamingResponse:
        principal_id = resolve_principal_id(request)
        request_id = getattr(request.state, "request_id", "")

        # ── Record query for telemetry (before any checks — captures all attempts
        #     that pass the rate limiter, including concurrency-blocked ones) ──
        if cost_tracker is not None:
            try:
                cost_tracker.record_query(
                    principal_id,
                    query=payload.content,
                    session_id=conversation_id,
                    request_id=request_id,
                    is_follow_up=False,  # updated below after conversation lookup
                )
            except Exception:
                logger.debug("Query recording failed (non-fatal)", exc_info=True)

        # ── Concurrency check ──
        if cost_tracker is not None:
            try:
                cost_tracker.acquire(principal_id)
            except ConcurrencyExceeded as exc:
                return JSONResponse(status_code=429, content={"detail": str(exc)})

        # ── Auto-create conversation ──
        try:
            conversation_service.get_conversation(principal_id, conversation_id)
        except (KeyError, LookupError):
            user_skill_snapshot = user_skill_service.load_snapshot(principal_id)
            conversation_service.create_conversation(
                principal_id=principal_id,
                user_id=principal_id,
                user_skill_snapshot=user_skill_snapshot,
                conversation_id=conversation_id,
            )
            logger.info("Auto-created conversation %s for principal %s", conversation_id, principal_id)

        logger.info(
            "Conversation message request received %s",
            format_log_context(
                conversation_id=conversation_id,
                principal_id=principal_id,
                request_id=getattr(request.state, "request_id", None),
            ),
            extra=build_log_extra(
                conversation_id=conversation_id,
                principal_id=principal_id,
                request_id=getattr(request.state, "request_id", None),
            ),
        )

        def sse() -> Iterator[str]:
            try:
                for event in run_engine.run_stream(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_content=payload.content,
                ):
                    yield f"data: {json.dumps(project_stream_payload(event, conversation_id=conversation_id), ensure_ascii=False)}\n\n"
            except BudgetExceeded as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc), 'retry_after_sec': exc.retry_after_sec}, ensure_ascii=False)}\n\n"
            finally:
                if cost_tracker is not None:
                    try:
                        cost_tracker.release(principal_id)
                    except Exception:
                        pass

        return StreamingResponse(sse(), media_type="text/event-stream")

    @router.post("/api/v1/runs/oneshot")
    def oneshot_run(payload: OneshotRunRequest, request: Request) -> dict:
        started_at = time.perf_counter()
        principal_id = require_principal_id(request)
        user_skill_snapshot = user_skill_service.load_snapshot(principal_id)
        conversation = conversation_service.create_conversation(
            principal_id=principal_id,
            user_id=principal_id,
            user_skill_snapshot=user_skill_snapshot,
        )
        events = list(
            run_engine.run(
                conversation_id=conversation.conversation_id,
                principal_id=principal_id,
                user_content=payload.content,
            )
        )
        assistant_content = ""
        for event in reversed(events):
            if event.type == "message.assistant_added":
                assistant_content = event.content
                break
        logger.info(
            "Oneshot run completed %s",
            format_log_context(
                conversation_id=conversation.conversation_id,
                principal_id=principal_id,
                user_id=principal_id,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
            extra=build_log_extra(
                conversation_id=conversation.conversation_id,
                principal_id=principal_id,
                user_id=principal_id,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
        )
        return {
            "user_id": principal_id,
            "assistant_content": assistant_content,
            "event_types": [event.type for event in events],
        }

    @router.post("/api/v1/supervisor/run")
    async def supervisor_run(payload: SupervisorRunRequest, request: Request) -> SupervisorRunResponse:
        """Run the full multi-agent Supervisor pipeline.

        Synchronous (non-streaming) — caller waits for the full pipeline.
        Typical latency: 60-180s depending on query complexity and LLM.

        Frontend can use this endpoint for one-shot deep analysis. For
        streaming ReAct events, use POST /api/v1/conversations/{id}/messages
        (single-agent path) instead.
        """
        principal_id = require_principal_id(request)
        started_at = time.perf_counter()

        # Lazy import to avoid loading supervisor + agent_runner deps on
        # every worker boot — only paid when this endpoint is called.
        from cagent_os.multi_agent.agent_runner import build_default_runner
        from cagent_os.multi_agent.supervisor import Supervisor, SupervisorConfig

        runner = build_default_runner()
        config = SupervisorConfig(
            timeout_seconds=payload.timeout_seconds,
            enable_rag=payload.enable_rag,
            enable_fred=payload.enable_fred,
            enable_web_search=payload.enable_web_search,
            agent_runner=runner,
        )
        supervisor = Supervisor(config=config)

        logger.info(
            "Supervisor run started %s",
            format_log_context(
                principal_id=principal_id,
                query_len=len(payload.query),
            ),
            extra=build_log_extra(
                principal_id=principal_id,
                query_preview=payload.query[:120],
            ),
        )

        result = await supervisor.run(payload.query)

        # Flatten SupervisorResult into SupervisorRunResponse
        response = SupervisorRunResponse(
            query=result.query,
            intent=result.decision.intent,
            agents=result.decision.agents,
            elapsed_ms=result.elapsed_ms,
            errors=result.errors,
        )

        if result.analysis:
            response.ticker = result.analysis.ticker
            response.thesis = result.analysis.thesis
            response.risks = result.analysis.risks
            response.catalysts = result.analysis.catalysts
            response.recommendation = result.analysis.recommendation
            response.confidence = result.analysis.confidence
            response.fwd_pe = result.analysis.valuation.fwd_pe
            response.fwd_ps = result.analysis.valuation.fwd_ps
            response.ev_ebitda = result.analysis.valuation.ev_ebitda
            response.pb = result.analysis.valuation.pb
            response.valuation_notes = result.analysis.valuation.notes
            for c in result.analysis.data_citations:
                response.citations.append({
                    "metric": c.metric,
                    "value": c.value,
                    "source": c.source,
                    "confidence": c.confidence,
                })

        if result.raw_data:
            response.source_summary = result.raw_data.source_summary
            for item in result.raw_data.items:
                response.raw_data_items.append({
                    "source": item.source,
                    "metric": item.metric,
                    "value": item.value,
                    "unit": item.unit,
                    "timestamp": item.timestamp,
                    "url": item.url,
                    "confidence": item.confidence,
                })

        if result.audit:
            response.audit_severity = result.audit.severity
            response.audit_gap = result.audit.gap
            response.audit_recommendation = result.audit.recommendation

        if result.summary:
            response.summary_conclusion = result.summary.conclusion
            response.summary_key_evidence = result.summary.key_evidence
            response.summary_key_risks = result.summary.key_risks
            response.summary_references = result.summary.references
            response.summary_confidence = result.summary.confidence

        logger.info(
            "Supervisor run completed %s",
            format_log_context(
                principal_id=principal_id,
                intent=result.decision.intent,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
            extra=build_log_extra(
                principal_id=principal_id,
                intent=result.decision.intent,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
        )
        return response

    return router
