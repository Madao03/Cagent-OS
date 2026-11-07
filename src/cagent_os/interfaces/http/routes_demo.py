"""Demo endpoint — no-auth trial chat for landing page visitors.

IP-limited to 3 requests per day. Creates a temporary conversation
and runs the agent as the demo user. SSE streaming just like the real chat.
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import uuid

from slowapi.util import get_remote_address

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cagent_os.domain.models import PolicyView
from cagent_os.interfaces.http.rate_limiter import limiter
from cagent_os.interfaces.http.run_events import project_stream_payload
from cagent_os.user_skills.models import UserSkillSnapshot

logger = logging.getLogger(__name__)

_DEMO_CONVERSATION_PREFIX = "demo-"
# Anonymous runs can search public providers and query market data. The
# shared RAG index, trace database, filesystem and arbitrary URL fetchers
# are intentionally outside this boundary.
_DEMO_CAPABILITIES = (
    "Skill",
    "financial.websearch",
    "financial.earnings.query",
    "financial.earnings.query_full",
    "financial.quote.query",
    "financial.quote.verified",
    "financial.edgar.facts",
    "financial.edgar.release",
    "financial.ashare.report",
    "financial.fred",
    "crypto.onchain.metrics",
    "crypto.sentiment.fng",
    "crypto.derivatives.funding",
    "crypto.derivatives.oi",
    "crypto.defi.tvl",
    "crypto.defi.stablecoins",
    "crypto.defi.revenue",
    "panews.search",
    "panews.article",
    "panews.briefing",
    "panews.trending",
    "panews.polymarket",
    "panews.events",
)


def build_demo_router(run_engine, conversation_service, user_skill_service) -> APIRouter:
    """Build router for the public demo endpoint."""

    router = APIRouter()

    @router.post("/api/v1/demo")
    @limiter.limit("3/day", key_func=get_remote_address)
    def demo_chat(payload: dict, request: Request) -> StreamingResponse:
        """No-auth demo chat. IP-limited to 3/day.

        Body: {"query": "..."}
        Returns: SSE stream (same format as /conversations/{id}/messages)
        """
        query = str(payload.get("query", "")).strip()
        if not query:
            return JSONResponse(
                status_code=400,
                content={"detail": "query is required"},
            )

        # Create a fresh conversation each time
        conversation_id = f"{_DEMO_CONVERSATION_PREFIX}{uuid.uuid4().hex}"
        principal_id = f"demo-guest-{uuid.uuid4().hex}"

        try:
            user_skill_snapshot = user_skill_service.load_snapshot(principal_id)
        except FileNotFoundError:
            user_skill_snapshot = UserSkillSnapshot(user_id=principal_id)

        try:
            conversation_service.create_conversation(
                principal_id=principal_id,
                user_id=principal_id,
                user_skill_snapshot=user_skill_snapshot,
                policy_snapshot=PolicyView(allowed_capability_ids=list(_DEMO_CAPABILITIES)),
                conversation_id=conversation_id,
            )
        except Exception:
            logger.exception("Failed to create demo conversation")
            return JSONResponse(status_code=503, content={"detail": "Demo temporarily unavailable"})

        event_queue: queue.SimpleQueue[str | None] = queue.SimpleQueue()

        disconnected = threading.Event()

        def _run_agent_thread() -> None:
            try:
                for event in run_engine.run_stream(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_content=query,
                ):
                    if disconnected.is_set():
                        continue
                    payload_dict = project_stream_payload(
                        event, conversation_id=conversation_id
                    )
                    event_queue.put(json.dumps(payload_dict, ensure_ascii=False))
            except Exception:
                logger.exception("Demo agent run failed conv=%s", conversation_id)
                event_queue.put(json.dumps({"type": "error", "message": "Agent run failed"}))
            finally:
                event_queue.put(None)

        async def sse():
            thread = threading.Thread(target=_run_agent_thread, daemon=True)
            thread.start()
            try:
                while True:
                    try:
                        raw = event_queue.get_nowait()
                        if raw is None:
                            break
                        yield f"data: {raw}\n\n"
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue
            finally:
                disconnected.set()

        limit_item, identifiers = request.state.view_rate_limit
        window = limiter.limiter.get_window_stats(limit_item, *identifiers)
        return StreamingResponse(
            sse(),
            media_type="text/event-stream",
            headers={
                "X-RateLimit-Remaining": str(window.remaining),
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    return router
