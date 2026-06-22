from __future__ import annotations

from collections.abc import Iterator
import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from cagent_os.agents.run_engine import AgentRuntime
from cagent_os.conversations.service import ConversationService
from cagent_os.interfaces.http.auth_context import resolve_principal_id
from cagent_os.interfaces.http.run_events import project_stream_payload
from cagent_os.interfaces.http.schemas import OneshotRunRequest, PostMessageRequest
from cagent_os.shared.logging_utils import build_log_extra, format_log_context
from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService

logger = logging.getLogger(__name__)


def build_runs_router(
    *,
    run_engine: AgentRuntime,
    conversation_service: ConversationService,
    user_skill_service: UserSkillService,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/conversations/{conversation_id}/messages")
    def post_message(conversation_id: str, payload: PostMessageRequest, request: Request) -> StreamingResponse:
        principal_id = resolve_principal_id(request)
        conversation_service.get_conversation(principal_id, conversation_id)
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
            for event in run_engine.run_stream(
                conversation_id=conversation_id,
                principal_id=principal_id,
                user_content=payload.content,
            ):
                yield f"data: {json.dumps(project_stream_payload(event, conversation_id=conversation_id), ensure_ascii=False)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    @router.post("/api/v1/runs/oneshot")
    def oneshot_run(payload: OneshotRunRequest, request: Request) -> dict:
        started_at = time.perf_counter()
        principal_id = resolve_principal_id(request)
        user_skill_snapshot = user_skill_service.load_snapshot(payload.user_id)
        conversation = conversation_service.create_conversation(
            principal_id=principal_id,
            user_id=payload.user_id,
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
                user_id=payload.user_id,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
            extra=build_log_extra(
                conversation_id=conversation.conversation_id,
                principal_id=principal_id,
                user_id=payload.user_id,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
        )
        return {
            "user_id": payload.user_id,
            "assistant_content": assistant_content,
            "event_types": [event.type for event in events],
        }

    return router
