"""Demo endpoint — no-auth trial chat for landing page visitors.

IP-limited to 3 requests per day. Creates a temporary conversation
and runs the agent as the demo user. SSE streaming just like the real chat.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cagent_os.interfaces.http.rate_limiter import limiter
from cagent_os.interfaces.http.run_events import project_stream_payload

logger = logging.getLogger(__name__)

_DEMO_PRINCIPAL_ID = "demo-user"
_DEMO_CONVERSATION_PREFIX = "demo-"


def build_demo_router(run_engine, conversation_service, user_skill_service) -> APIRouter:
    """Build router for the public demo endpoint."""

    router = APIRouter()

    @router.post("/api/v1/demo")
    @limiter.limit("3/day")
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
        conversation_id = f"{_DEMO_CONVERSATION_PREFIX}{uuid.uuid4().hex[:12]}"

        try:
            user_skill_snapshot = user_skill_service.load_snapshot(_DEMO_PRINCIPAL_ID)
            conversation_service.create_conversation(
                principal_id=_DEMO_PRINCIPAL_ID,
                user_id=_DEMO_PRINCIPAL_ID,
                user_skill_snapshot=user_skill_snapshot,
                conversation_id=conversation_id,
            )
        except Exception:
            # Demo user might not exist in skills store — use empty snapshot
            try:
                conversation_service.create_conversation(
                    principal_id=_DEMO_PRINCIPAL_ID,
                    user_id=_DEMO_PRINCIPAL_ID,
                    user_skill_snapshot={},
                    conversation_id=conversation_id,
                )
            except Exception:
                logger.exception("Failed to create demo conversation")

        event_queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        def _run_agent_thread() -> None:
            try:
                for event in run_engine.run_stream(
                    conversation_id=conversation_id,
                    principal_id=_DEMO_PRINCIPAL_ID,
                    user_content=query,
                ):
                    payload_dict = project_stream_payload(
                        event, conversation_id=conversation_id
                    )
                    try:
                        event_queue.put_nowait(
                            json.dumps(payload_dict, ensure_ascii=False)
                        )
                    except asyncio.QueueFull:
                        pass
            except Exception:
                logger.exception("Demo agent run failed conv=%s", conversation_id)
                try:
                    event_queue.put_nowait(
                        json.dumps(
                            {"type": "error", "message": "Agent run failed"},
                            ensure_ascii=False,
                        )
                    )
                except asyncio.QueueFull:
                    pass
            finally:
                try:
                    event_queue.put_nowait(None)  # type: ignore[arg-type]
                except asyncio.QueueFull:
                    pass

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
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.05)
                        continue
            except asyncio.CancelledError:
                pass

        return StreamingResponse(sse(), media_type="text/event-stream")

    return router
