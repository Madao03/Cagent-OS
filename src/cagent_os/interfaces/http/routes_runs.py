from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cagent_os.agents.run_engine import AgentRuntime
from cagent_os.config.cost_tracker import BudgetExceeded, ConcurrencyExceeded, CostTracker
from cagent_os.conversations.service import ConversationService
from cagent_os.interfaces.http.auth_context import require_principal_id
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
    backend_registry=None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/conversations/{conversation_id}/messages")
    @limiter.limit("5/minute")
    def post_message(conversation_id: str, payload: PostMessageRequest, request: Request) -> StreamingResponse:
        principal_id = require_principal_id(request)
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

        # ── Decoupled SSE: run agent in background task, stream from queue ──
        # The agent runs to completion even if the client disconnects.
        # Results are persisted to DB by run_engine regardless of SSE state.
        # The SSE reader simply drains the queue and exits when done.
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        # ── BYOK: resolve per-user backend + model (falls back to platform) ──
        model_override = None
        backend_override = None
        if backend_registry is not None:
            try:
                resolved = backend_registry.resolve_for(principal_id)
                if resolved.is_user_key:
                    backend_override = resolved.backend
                    model_override = resolved.default_model
            except Exception:
                logger.debug("BYOK resolution failed, using platform backend", exc_info=True)

        # ★ Request-level model wins (quick switcher) — only with a user backend
        if backend_override is not None and payload.model:
            model_override = payload.model

        def _run_agent_thread() -> None:
            """Run agent in a thread, push events to queue."""
            try:
                for event in run_engine.run_stream(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_content=payload.content,
                    model_override=model_override,
                    backend_override=backend_override,
                ):
                    payload_dict = project_stream_payload(event, conversation_id=conversation_id)
                    try:
                        event_queue.put_nowait(json.dumps(payload_dict, ensure_ascii=False))
                    except asyncio.QueueFull:
                        logger.warning("SSE queue full, dropping event for conv=%s", conversation_id)
            except BudgetExceeded as exc:
                error_data = json.dumps(
                    {"type": "error", "message": str(exc), "retry_after_sec": exc.retry_after_sec},
                    ensure_ascii=False,
                )
                try:
                    event_queue.put_nowait(error_data)
                except asyncio.QueueFull:
                    pass
            except Exception:
                logger.exception("Agent run failed in background thread conv=%s", conversation_id)
                error_data = json.dumps(
                    {"type": "error", "message": "Agent run failed unexpectedly"},
                    ensure_ascii=False,
                )
                try:
                    event_queue.put_nowait(error_data)
                except asyncio.QueueFull:
                    pass
            finally:
                # Signal end of stream
                try:
                    event_queue.put_nowait(None)  # type: ignore[arg-type]
                except asyncio.QueueFull:
                    pass
                # Release concurrency slot
                if cost_tracker is not None:
                    try:
                        cost_tracker.release(principal_id)
                    except Exception:
                        pass

        async def sse() -> Iterator[str]:
            """Stream events from queue to client.

            If client disconnects, this generator stops — but the background
            thread continues running until the agent completes or wall-clock
            timeout. Results are persisted to DB regardless.
            """
            import concurrent.futures
            import threading

            # Start agent in a daemon thread (not asyncio task — run_engine is sync)
            thread = threading.Thread(target=_run_agent_thread, daemon=True)
            thread.start()

            try:
                while True:
                    # Use run_in_executor to make Queue.get_nowait non-blocking-friendly
                    # in async context. Poll with small sleep.
                    try:
                        raw = event_queue.get_nowait()
                        if raw is None:
                            break  # End of stream sentinel
                        yield f"data: {raw}\n\n"
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.05)
                        continue
            except asyncio.CancelledError:
                # Client disconnected — agent thread keeps running
                logger.info("SSE client disconnected, agent continues in background conv=%s", conversation_id)

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
