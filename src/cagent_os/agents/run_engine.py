"""AgentRuntime — the central agent execution loop (ReAct + Event Sourcing).

This module implements the core Agent Loop: receive user input → build runtime
context → loop (LLM call → tool dispatch → feed result back) → yield events.

Architecture:
    AgentRuntime
      ├── ConversationService (snapshot + event persistence)
      ├── PromptBuilder   (system prompt assembly)
      ├── ToolDispatcher (tool dispatch)
      ├── ModelRouter      (LLM provider selection)
      ├── MemoryAPI        (cross-session hot memory)
      ├── TraceWriter      (structured trace logging)
      └── AsyncBridge      (sync↔async bridge)

Every state change is recorded as an immutable ``JournalEntry`` and
persisted via ``EventStore`` (Event Sourcing). The projector
rebuilds the LLM transcript from events on each turn.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
import datetime
import json
import logging
import re
import time
from pathlib import Path
from typing import NamedTuple

from cagent_os.agents.definition import AgentProfile
from cagent_os.agents.prompt_compiler import PromptBuilder
from cagent_os.plugins.contracts import ToolRequest, ToolResult
from cagent_os.plugins.executor import ToolDispatcher
from cagent_os.plugins.policy import ToolGuard
from cagent_os.plugins.validator import ArgumentChecker, ArgumentError
from cagent_os.config import Settings, get_settings
from cagent_os.conversations.locking import ConversationLockManager
from cagent_os.conversations.models import (
    JournalEntry,
    assistant_message,
    assistant_tool_calls,
    user_message,
)
from cagent_os.conversations.projector import TranscriptReplayer
from cagent_os.conversations.repository import EventStore
from cagent_os.conversations.service import ConversationService
from cagent_os.domain.models import MemorySnapshot
from cagent_os.llm import LLMBackend, ModelRouter
from cagent_os.llm.protocol import ChatMessage, ModelRequest, ToolSchema
from cagent_os.memory.api import MemoryAPI, UserFact
from cagent_os.observability.tracing import TraceWriter
from cagent_os.plugins.skills.plugin import SKILL_TOOL_NAME, build_skill_tool_description
from cagent_os.shared.async_bridge import AsyncBridge
from cagent_os.shared.errors import ToolAccessDenied
from cagent_os.shared.logging_utils import build_log_extra, format_log_context

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

MAX_ITERATIONS = 12
MAX_CONSECUTIVE_TOOL_ERRORS = 5
SOFT_ERROR_CODES: set[str] = {
    "finance_empty_result",
    "finance_provider_error",
    "invalid_arguments",
    "invalid_finance_request",
    "no_symbol",
    "web_fetch_failed",       # 403/406/404 — normal on the open web
    "weixin_fetch_failed",    # WeChat CAPTCHA — expected
    "weixin_fetch_empty",     # deleted article — not exceptional
}

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _to_full_json(value: object) -> str:
    """Serialize any Python value to a JSON string for trace storage."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(value)


class _RuntimeSetup(NamedTuple):
    """Frozen snapshot of everything the agent loop needs for one run."""
    model: str
    policy: ToolGuard
    system_prompt: str
    tool_schemas: list


@dataclass
class _AgentRunState:
    """Mutable counters for the current run — avoids O(n) event-store scans."""
    iteration: int = 0
    consecutive_exceptional_failures: int = 0
    tool_results: list[dict] = field(default_factory=list)


# ------------------------------------------------------------------
# AgentRuntime
# ------------------------------------------------------------------


class AgentRuntime:
    """Central agent execution loop.

    Orchestrates the ReAct cycle: build prompt → call LLM → dispatch tool
    calls → feed results back → repeat until the LLM produces a final answer
    or the iteration / failure budget is exhausted.

    Every state change is emitted as a ``JournalEntry`` and persisted
    via the event store. Callers iterate over the event stream via ``run()``.
    """

    def __init__(
        self,
        *,
        conversation_service: ConversationService,
        event_store: EventStore,
        llm_backend: LLMBackend,
        capability_executor: ToolDispatcher,
        prompt_compiler: PromptBuilder | None = None,
        model_router: ModelRouter | None = None,
        lock_manager: ConversationLockManager | None = None,
        projector: TranscriptReplayer | None = None,
        argument_validator: ArgumentChecker | None = None,
        settings: Settings | None = None,
        memory_api: MemoryAPI | None = None,
        trace_writer: TraceWriter | None = None,
        async_bridge: AsyncBridge | None = None,
    ) -> None:
        self._conversation_service = conversation_service
        self._event_store = event_store
        self._llm_backend = llm_backend
        self._capability_executor = capability_executor
        self._projector = projector or TranscriptReplayer()
        self._prompt_compiler = prompt_compiler or PromptBuilder()
        self._model_router = model_router or ModelRouter()
        self._lock_manager = lock_manager or ConversationLockManager()
        self._argument_validator = argument_validator or ArgumentChecker()
        self._settings = settings or get_settings()
        self._memory = memory_api
        self._trace_writer = trace_writer
        self._bridge = async_bridge

    def run(
        self,
        *,
        conversation_id: str,
        principal_id: str,
        user_content: str,
    ) -> Iterator[JournalEntry]:
        conversation = self._conversation_service.get_conversation(principal_id, conversation_id)
        if not self._lock_manager.acquire(conversation_id):
            logger.warning(
                "Run rejected because conversation is busy %s",
                format_log_context(conversation_id=conversation_id, principal_id=principal_id),
                extra=build_log_extra(conversation_id=conversation_id, principal_id=principal_id),
            )
            failed = JournalEntry(type="run.failed", data={"reason": "conversation_busy"})
            yield failed
            return

        state = _AgentRunState()
        started_at = time.perf_counter()
        try:
            logger.info(
                "Run started %s",
                format_log_context(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_id=conversation.user_id,
                ),
                extra=build_log_extra(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_id=conversation.user_id,
                ),
            )
            user_event = user_message(user_content)
            self._event_store.append(conversation_id, user_event)

            started = JournalEntry(type="run.started", data={"conversation_id": conversation_id})
            self._event_store.append(conversation_id, started)
            yield started
            self._trace("run_started", conversation_id, user_id=conversation.user_id, user_query=user_content)

            try:
                setup = self._build_runtime_setup(conversation)
                # Phase 1a: inject read-later skill into system prompt for URL messages
                _injection = _build_read_later_prompt_injection(user_content)
                if _injection:
                    setup = setup._replace(system_prompt=setup.system_prompt + "\n\n" + _injection)
            except Exception as exc:
                logger.exception(
                    "Runtime setup failed %s",
                    format_log_context(
                        conversation_id=conversation_id,
                        principal_id=principal_id,
                        user_id=conversation.user_id,
                        stage="runtime_setup",
                    ),
                    extra=build_log_extra(
                        conversation_id=conversation_id,
                        principal_id=principal_id,
                        user_id=conversation.user_id,
                        stage="runtime_setup",
                    ),
                )
                failed = self._append_failed(
                    conversation_id,
                    reason="runtime_error",
                    stage="runtime_setup",
                    message=str(exc),
                )
                self._trace("run_failed", conversation_id, reason="runtime_error", stage="runtime_setup")
                yield failed
                return

            self._trace(
                "runtime_setup", conversation_id,
                model=setup.model,
                tool_count=len(setup.tool_schemas),
            )

            while state.iteration < MAX_ITERATIONS:
                state.iteration += 1
                try:
                    request = self._build_request(conversation_id, setup)
                except Exception as exc:
                    logger.exception(
                        "Request build failed %s",
                        format_log_context(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            stage="request_build",
                            model=setup.model,
                        ),
                        extra=build_log_extra(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            stage="request_build",
                            model=setup.model,
                        ),
                    )
                    failed = self._append_failed(
                        conversation_id,
                        reason="runtime_error",
                        stage="request_build",
                        message=str(exc),
                    )
                    self._trace("run_failed", conversation_id, reason="runtime_error", stage="request_build")
                    yield failed
                    return

                try:
                    response = self._llm_backend.complete(request)
                    message = response.message
                except Exception as exc:
                    logger.exception(
                        "LLM backend failed %s",
                        format_log_context(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            model=setup.model,
                        ),
                        extra=build_log_extra(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            model=setup.model,
                        ),
                    )
                    failed = self._append_failed(
                        conversation_id,
                        reason="llm_backend_error",
                        message=str(exc),
                    )
                    self._trace("run_failed", conversation_id, reason="llm_backend_error")
                    yield failed
                    return

                if not message.tool_calls:
                    final_content = self._finalize_assistant_content(
                        conversation_id=conversation_id,
                        content=message.content,
                        consecutive_exceptional_tool_failures=state.consecutive_exceptional_failures,
                    )
                    assistant_event = assistant_message(final_content)
                    self._event_store.append(conversation_id, assistant_event)
                    yield assistant_event

                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    completed = JournalEntry(
                        type="run.completed",
                        data={"finish_reason": response.finish_reason or "stop"},
                    )
                    self._event_store.append(conversation_id, completed)
                    logger.info(
                        "Run completed %s",
                        format_log_context(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            finish_reason=response.finish_reason or "stop",
                            elapsed_ms=elapsed_ms,
                        ),
                        extra=build_log_extra(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            finish_reason=response.finish_reason or "stop",
                            elapsed_ms=elapsed_ms,
                        ),
                    )
                    self._trace(
                        "run_completed", conversation_id,
                        finish_reason=response.finish_reason or "stop",
                        iterations=state.iteration,
                        elapsed_ms=elapsed_ms,
                        final_output=final_content,
                    )
                    yield completed
                    return

                for event in self._process_tool_calls(
                    conversation_id=conversation_id,
                    user_id=conversation.user_id,
                    policy=setup.policy,
                    content=message.content,
                    tool_calls=message.tool_calls,
                    state=state,
                ):
                    yield event
                    if event.type in {"run.failed", "run.completed"}:
                        return
                    if (
                        event.type == "run.tool_failed"
                        and self._counts_as_exceptional_tool_failure(event)
                        and state.consecutive_exceptional_failures
                        >= MAX_CONSECUTIVE_TOOL_ERRORS
                    ):
                        for terminal_event in self._complete_with_tool_failure_summary(
                            conversation_id=conversation_id,
                            consecutive_exceptional_tool_failures=state.consecutive_exceptional_failures,
                        ):
                            yield terminal_event
                        return

            stopped = self._append_failed(conversation_id, reason="iteration_limit")
            logger.warning(
                "Run hit iteration limit %s",
                format_log_context(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_id=conversation.user_id,
                    elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                ),
                extra=build_log_extra(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_id=conversation.user_id,
                    elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                ),
            )
            self._trace("run_failed", conversation_id, reason="iteration_limit")
            yield stopped
        finally:
            self._lock_manager.release(conversation_id)

    def run_stream(
        self,
        *,
        conversation_id: str,
        principal_id: str,
        user_content: str,
    ) -> Iterator[JournalEntry]:
        conversation = self._conversation_service.get_conversation(principal_id, conversation_id)
        if not self._lock_manager.acquire(conversation_id):
            logger.warning(
                "Streaming run rejected because conversation is busy %s",
                format_log_context(conversation_id=conversation_id, principal_id=principal_id),
                extra=build_log_extra(conversation_id=conversation_id, principal_id=principal_id),
            )
            failed = JournalEntry(type="run.failed", data={"reason": "conversation_busy"})
            yield failed
            return

        state = _AgentRunState()
        started_at = time.perf_counter()
        try:
            logger.info(
                "Streaming run started %s",
                format_log_context(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_id=conversation.user_id,
                ),
                extra=build_log_extra(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_id=conversation.user_id,
                ),
            )
            user_event = user_message(user_content)
            self._event_store.append(conversation_id, user_event)

            started = JournalEntry(type="run.started", data={"conversation_id": conversation_id})
            self._event_store.append(conversation_id, started)
            yield started
            self._trace("run_started", conversation_id, user_id=conversation.user_id, user_query=user_content)

            try:
                setup = self._build_runtime_setup(conversation)
                # Phase 1a: inject read-later skill into system prompt for URL messages
                _injection = _build_read_later_prompt_injection(user_content)
                if _injection:
                    setup = setup._replace(system_prompt=setup.system_prompt + "\n\n" + _injection)
            except Exception as exc:
                logger.exception(
                    "Runtime setup failed %s",
                    format_log_context(
                        conversation_id=conversation_id,
                        principal_id=principal_id,
                        user_id=conversation.user_id,
                        stage="runtime_setup",
                    ),
                    extra=build_log_extra(
                        conversation_id=conversation_id,
                        principal_id=principal_id,
                        user_id=conversation.user_id,
                        stage="runtime_setup",
                    ),
                )
                failed = self._append_failed(
                    conversation_id,
                    reason="runtime_error",
                    stage="runtime_setup",
                    message=str(exc),
                )
                self._trace("run_failed", conversation_id, reason="runtime_error", stage="runtime_setup")
                yield failed
                return

            self._trace(
                "runtime_setup", conversation_id,
                model=setup.model,
                tool_count=len(setup.tool_schemas),
            )

            while state.iteration < MAX_ITERATIONS:
                state.iteration += 1
                try:
                    request = self._build_request(conversation_id, setup)
                except Exception as exc:
                    logger.exception(
                        "Request build failed %s",
                        format_log_context(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            stage="request_build",
                            model=setup.model,
                        ),
                        extra=build_log_extra(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            stage="request_build",
                            model=setup.model,
                        ),
                    )
                    failed = self._append_failed(
                        conversation_id,
                        reason="runtime_error",
                        stage="request_build",
                        message=str(exc),
                    )
                    self._trace("run_failed", conversation_id, reason="runtime_error", stage="request_build")
                    yield failed
                    return

                content_chunks: list[str] = []
                tool_calls = []
                finish_reason = "stop"
                try:
                    stream_method = getattr(self._llm_backend, "stream", None)
                    if callable(stream_method):
                        for stream_event in stream_method(request):
                            if stream_event.type == "text" and stream_event.text:
                                content_chunks.append(stream_event.text)
                                yield JournalEntry(
                                    type="message.assistant_delta",
                                    role="assistant",
                                    content=stream_event.text,
                                )
                                continue
                            if stream_event.type == "tool_call" and stream_event.tool_call is not None:
                                tool_calls.append(stream_event.tool_call)
                                continue
                            if stream_event.type == "done":
                                finish_reason = stream_event.finish_reason or finish_reason
                    else:
                        response = self._llm_backend.complete(request)
                        message = response.message
                        if message.content:
                            content_chunks.append(message.content)
                            yield JournalEntry(
                                type="message.assistant_delta",
                                role="assistant",
                                content=message.content,
                            )
                        tool_calls = list(message.tool_calls)
                        finish_reason = response.finish_reason or (
                            "tool_calls" if tool_calls else "stop"
                        )
                except Exception as exc:
                    logger.exception(
                        "LLM backend failed %s",
                        format_log_context(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            model=setup.model,
                        ),
                        extra=build_log_extra(
                            conversation_id=conversation_id,
                            principal_id=principal_id,
                            user_id=conversation.user_id,
                            model=setup.model,
                        ),
                    )
                    failed = self._append_failed(
                        conversation_id,
                        reason="llm_backend_error",
                        message=str(exc),
                    )
                    self._trace("run_failed", conversation_id, reason="llm_backend_error")
                    yield failed
                    return

                content = "".join(content_chunks)
                if tool_calls:
                    for event in self._process_tool_calls(
                        conversation_id=conversation_id,
                        user_id=conversation.user_id,
                        policy=setup.policy,
                        content=content,
                        tool_calls=tool_calls,
                        state=state,
                    ):
                        yield event
                        if event.type in {"run.failed", "run.completed"}:
                            return
                        if (
                            event.type == "run.tool_failed"
                            and self._counts_as_exceptional_tool_failure(event)
                            and state.consecutive_exceptional_failures
                            >= MAX_CONSECUTIVE_TOOL_ERRORS
                        ):
                            for terminal_event in self._complete_with_tool_failure_summary(
                                conversation_id=conversation_id,
                                consecutive_exceptional_tool_failures=state.consecutive_exceptional_failures,
                            ):
                                yield terminal_event
                            return
                    continue

                final_content = self._finalize_assistant_content(
                    conversation_id=conversation_id,
                    content=content,
                    consecutive_exceptional_tool_failures=state.consecutive_exceptional_failures,
                )
                assistant_event = assistant_message(final_content)
                self._event_store.append(conversation_id, assistant_event)
                yield assistant_event

                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                completed = JournalEntry(
                    type="run.completed",
                    data={"finish_reason": finish_reason or "stop"},
                )
                self._event_store.append(conversation_id, completed)
                logger.info(
                    "Streaming run completed %s",
                    format_log_context(
                        conversation_id=conversation_id,
                        principal_id=principal_id,
                        user_id=conversation.user_id,
                        finish_reason=finish_reason or "stop",
                        elapsed_ms=elapsed_ms,
                    ),
                    extra=build_log_extra(
                        conversation_id=conversation_id,
                        principal_id=principal_id,
                        user_id=conversation.user_id,
                        finish_reason=finish_reason or "stop",
                        elapsed_ms=elapsed_ms,
                    ),
                )
                self._trace(
                    "run_completed", conversation_id,
                    finish_reason=finish_reason or "stop",
                    iterations=state.iteration,
                    elapsed_ms=elapsed_ms,
                )
                yield completed
                return

            stopped = self._append_failed(conversation_id, reason="iteration_limit")
            logger.warning(
                "Streaming run hit iteration limit %s",
                format_log_context(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_id=conversation.user_id,
                    elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                ),
                extra=build_log_extra(
                    conversation_id=conversation_id,
                    principal_id=principal_id,
                    user_id=conversation.user_id,
                    elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                ),
            )
            self._trace("run_failed", conversation_id, reason="iteration_limit")
            yield stopped
        finally:
            self._lock_manager.release(conversation_id)

    def _resolve_model(self) -> str:
        return self._model_router.resolve(self._settings.default_model_alias)

    def _append_failed(
        self,
        conversation_id: str,
        *,
        reason: str,
        message: str | None = None,
        capability_id: str | None = None,
        stage: str | None = None,
    ) -> JournalEntry:
        data: dict[str, str] = {"reason": reason}
        if message is not None:
            data["message"] = message
        if capability_id is not None:
            data["capability_id"] = capability_id
        if stage is not None:
            data["stage"] = stage
        event = JournalEntry(type="run.failed", data=data)
        self._event_store.append(conversation_id, event)
        return event

    def _build_runtime_setup(self, conversation) -> _RuntimeSetup:
        allowed_capability_ids = self._capability_executor.registry.default_enabled_tool_ids()
        if conversation.policy_snapshot.allowed_capability_ids:
            policy_allowed = set(conversation.policy_snapshot.allowed_capability_ids)
            allowed_capability_ids = [
                capability_id
                for capability_id in allowed_capability_ids
                if capability_id in policy_allowed
            ]
        capability_descriptions = self._describe_allowed_tools(
            allowed_capability_ids, conversation.user_skill_snapshot.documents
        )
        tool_schemas = self._tool_schemas(
            allowed_capability_ids, conversation.user_skill_snapshot.documents
        )

        memory_context = self._build_memory_context(conversation)

        system_prompt = self._prompt_compiler.compile(
            AgentProfile(
                user_skill_snapshot=conversation.user_skill_snapshot,
                capability_descriptions=capability_descriptions,
                user_prompt_preferences=conversation.user_prompt_preferences_snapshot,
                session_prompt_overrides=conversation.session_prompt_overrides,
                memory_context=memory_context,
            )
        ).text
        return _RuntimeSetup(
            model=self._resolve_model(),
            policy=ToolGuard(set(allowed_capability_ids)),
            system_prompt=system_prompt,
            tool_schemas=tool_schemas,
        )

    def _build_memory_context(self, conversation) -> MemorySnapshot:
        """Combine static snapshot memory with dynamic hot memory from store."""
        summary_parts: list[str] = []
        static = (conversation.memory_context.summary_text or "").strip()
        if static:
            summary_parts.append(static)
        items: list[str] = []
        if self._memory is not None and self._bridge is not None:
            try:
                hot = self._bridge.run(
                    self._memory.get_hot_memory_prompt(conversation.user_id),
                    timeout=5.0,
                )
                if hot:
                    items.append(hot)
            except Exception:
                logger.debug("Failed to fetch hot memory", exc_info=True)
        return MemorySnapshot(
            summary_text="\n\n".join(summary_parts),
            items=items,
        )

    def _describe_allowed_tools(
        self,
        capability_ids: list[str],
        skill_documents,
    ) -> list[str]:
        descriptions: list[str] = []
        for capability_id in capability_ids:
            manifest = self._capability_executor.registry.spec_for(capability_id)
            description = (
                build_skill_tool_description(skill_documents)
                if capability_id == SKILL_TOOL_NAME
                else manifest.description
            )
            descriptions.append(f"{capability_id}: {description}" if description else capability_id)
        return descriptions

    def _tool_schemas(
        self,
        capability_ids: list[str],
        skill_documents,
    ) -> list[ToolSchema]:
        definitions: list[ToolSchema] = []
        for capability_id in capability_ids:
            manifest = self._capability_executor.registry.spec_for(capability_id)
            description = (
                build_skill_tool_description(skill_documents)
                if capability_id == SKILL_TOOL_NAME
                else manifest.description
            )
            definitions.append(
                ToolSchema(
                    name=capability_id,
                    description=description,
                    parameters=manifest.parameters,
                )
            )
        return definitions

    def _build_request(self, conversation_id: str, setup: _RuntimeSetup) -> ModelRequest:
        events = self._event_store.list_events(conversation_id)
        transcript = self._projector.project(events).transcript
        return ModelRequest(
            model=setup.model,
            messages=[ChatMessage(role="system", content=setup.system_prompt), *transcript],
            tools=setup.tool_schemas,
        )

    def _process_tool_calls(
        self,
        *,
        conversation_id: str,
        user_id: str,
        policy: ToolGuard,
        content: str,
        tool_calls: list,
        state: _AgentRunState | None = None,
    ) -> Iterator[JournalEntry]:
        tool_call_event = assistant_tool_calls(content, tool_calls)
        self._event_store.append(conversation_id, tool_call_event)
        logger.info(
            "Assistant emitted tool calls %s",
            format_log_context(
                conversation_id=conversation_id,
                user_id=user_id,
                tool_count=len(tool_calls),
            ),
            extra=build_log_extra(
                conversation_id=conversation_id,
                user_id=user_id,
                tool_count=len(tool_calls),
            ),
        )
        yield tool_call_event

        for tool_call in tool_calls:
            try:
                policy.authorize(tool_call.name)
                validated_arguments = self._argument_validator.check(
                    manifest=self._capability_executor.registry.spec_for(tool_call.name),
                    arguments=tool_call.arguments,
                )
            except ToolAccessDenied as exc:
                logger.warning(
                    "Tool authorization denied %s",
                    format_log_context(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        capability_id=tool_call.name,
                        tool_call_id=tool_call.id,
                    ),
                    extra=build_log_extra(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        capability_id=tool_call.name,
                        tool_call_id=tool_call.id,
                    ),
                )
                failed = JournalEntry(
                    type="run.failed",
                    data={
                        "reason": "capability_denied",
                        "capability_id": tool_call.name,
                        "message": str(exc),
                    },
                )
                self._event_store.append(conversation_id, failed)
                yield failed
                return
            except KeyError:
                logger.warning(
                    "Tool capability unavailable %s",
                    format_log_context(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        capability_id=tool_call.name,
                        tool_call_id=tool_call.id,
                    ),
                    extra=build_log_extra(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        capability_id=tool_call.name,
                        tool_call_id=tool_call.id,
                    ),
                )
                failed = JournalEntry(
                    type="run.failed",
                    data={
                        "reason": "capability_unavailable",
                        "capability_id": tool_call.name,
                    },
                )
                self._event_store.append(conversation_id, failed)
                yield failed
                return
            except ArgumentError as exc:
                logger.warning(
                    "Tool arguments rejected %s",
                    format_log_context(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        capability_id=tool_call.name,
                        tool_call_id=tool_call.id,
                    ),
                    extra=build_log_extra(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        capability_id=tool_call.name,
                        tool_call_id=tool_call.id,
                    ),
                )
                failed = self._tool_result_event(
                    tool_call_id=tool_call.id,
                    capability_id=tool_call.name,
                    result=ToolResult(
                        status="error",
                        error_code="invalid_arguments",
                        content={
                            "success": False,
                            "error": "invalid_arguments",
                            "message": str(exc),
                            "details": {
                                "capability_id": tool_call.name,
                            },
                        },
                    ),
                )
                self._event_store.append(conversation_id, failed)
                yield failed
                continue

            requested = JournalEntry(
                type="run.tool_requested",
                data={
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": validated_arguments,
                },
            )
            self._event_store.append(conversation_id, requested)
            logger.info(
                "Tool execution requested %s arguments=%s",
                format_log_context(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    capability_id=tool_call.name,
                    tool_call_id=tool_call.id,
                ),
                _to_full_json(validated_arguments),
                extra=build_log_extra(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    capability_id=tool_call.name,
                    tool_call_id=tool_call.id,
                    arguments=validated_arguments,
                ),
            )
            yield requested

            execution = self._execute_tool_once(
                conversation_id=conversation_id,
                user_id=user_id,
                tool_call_id=tool_call.id,
                capability_id=tool_call.name,
                arguments=validated_arguments,
                state=state,
            )
            for event in execution.events:
                yield event
            if execution.events and execution.events[-1].type == "run.failed":
                return

    def _complete_with_tool_failure_summary(
        self,
        *,
        conversation_id: str,
        consecutive_exceptional_tool_failures: int = 0,
    ) -> list[JournalEntry]:
        summary = self._fallback_answer_for_tool_failures(
            conversation_id=conversation_id,
            consecutive_exceptional_tool_failures=consecutive_exceptional_tool_failures,
        )
        assistant_event = assistant_message(summary)
        self._event_store.append(conversation_id, assistant_event)
        completed = JournalEntry(
            type="run.completed",
            data={"finish_reason": "tool_failure_limit"},
        )
        self._event_store.append(conversation_id, completed)
        return [assistant_event, completed]

    class _ExecutionResult(NamedTuple):
        result: object | None
        events: list[JournalEntry]

    def _execute_tool_once(
        self,
        *,
        conversation_id: str,
        user_id: str,
        tool_call_id: str,
        capability_id: str,
        arguments: dict[str, object],
        state: _AgentRunState | None = None,
    ) -> _ExecutionResult:
        events: list[JournalEntry] = []
        attempt_started_at = time.perf_counter()
        try:
            result = self._capability_executor.execute(
                ToolRequest(
                    capability_id=capability_id,
                    arguments=arguments,
                    context={"user_id": user_id},
                )
            )
        except ToolAccessDenied as exc:
            logger.warning(
                "Tool execution denied %s",
                format_log_context(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    capability_id=capability_id,
                    tool_call_id=tool_call_id,
                ),
                extra=build_log_extra(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    capability_id=capability_id,
                    tool_call_id=tool_call_id,
                ),
            )
            failed = JournalEntry(
                type="run.failed",
                data={
                    "reason": "capability_denied",
                    "capability_id": capability_id,
                    "message": str(exc),
                },
            )
            self._event_store.append(conversation_id, failed)
            events.append(failed)
            return self._ExecutionResult(result=None, events=events)
        except KeyError:
            logger.warning(
                "Tool execution missing capability %s",
                format_log_context(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    capability_id=capability_id,
                    tool_call_id=tool_call_id,
                ),
                extra=build_log_extra(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    capability_id=capability_id,
                    tool_call_id=tool_call_id,
                ),
            )
            failed = JournalEntry(
                type="run.failed",
                data={
                    "reason": "capability_unavailable",
                    "capability_id": capability_id,
                },
            )
            self._event_store.append(conversation_id, failed)
            events.append(failed)
            return self._ExecutionResult(result=None, events=events)
        except Exception as exc:
            logger.exception(
                "Tool execution crashed %s",
                format_log_context(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    capability_id=capability_id,
                    tool_call_id=tool_call_id,
                ),
                extra=build_log_extra(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    capability_id=capability_id,
                    tool_call_id=tool_call_id,
                ),
            )
            failed = self._append_failed(
                conversation_id,
                reason="capability_execution_error",
                capability_id=capability_id,
                message=str(exc),
            )
            events.append(failed)
            return self._ExecutionResult(result=None, events=events)

        completion_event = self._tool_result_event(
            tool_call_id=tool_call_id,
            capability_id=capability_id,
            result=result,
        )
        self._event_store.append(conversation_id, completion_event)
        events.append(completion_event)
        elapsed_ms = int((time.perf_counter() - attempt_started_at) * 1000)
        logger.log(
            logging.INFO if result.status == "ok" else logging.WARNING,
            "Tool execution finished %s",
            format_log_context(
                conversation_id=conversation_id,
                user_id=user_id,
                capability_id=capability_id,
                tool_call_id=tool_call_id,
                status=result.status,
                error_code=result.error_code,
                result=result.content,
                elapsed_ms=elapsed_ms,
            ),
            extra=build_log_extra(
                conversation_id=conversation_id,
                user_id=user_id,
                capability_id=capability_id,
                tool_call_id=tool_call_id,
                status=result.status,
                error_code=result.error_code,
                result=result.content,
                elapsed_ms=elapsed_ms,
            ),
        )

        self._trace(
            "tool_executed", conversation_id,
            capability_id=capability_id,
            status=result.status,
            error_code=result.error_code,
            elapsed_ms=elapsed_ms,
        )

        if state is not None:
            if result.status == "ok":
                state.consecutive_exceptional_failures = 0
                state.tool_results.append({
                    "capability_id": capability_id,
                    "status": "ok",
                    "arguments": arguments,
                })
            elif self._counts_as_exceptional_tool_failure(completion_event):
                state.consecutive_exceptional_failures += 1

        self._maybe_save_facts(
            user_id=user_id,
            capability_id=capability_id,
            arguments=arguments,
            result=result,
        )

        return self._ExecutionResult(result=result, events=events)

    @staticmethod
    def _tool_result_event(
        *,
        tool_call_id: str,
        capability_id: str,
        result,
    ) -> JournalEntry:
        payload = result.content if isinstance(result.content, dict) else {}
        message = str(payload.get("message", "")) if isinstance(payload, dict) else ""
        details = payload.get("details") if isinstance(payload, dict) else None
        return JournalEntry(
            type="run.tool_completed" if result.status == "ok" else "run.tool_failed",
            data={
                "tool_call_id": tool_call_id,
                "name": capability_id,
                "result": result.content,
                "status": result.status,
                "error_code": result.error_code,
                "message": message,
                "details": details,
            },
        )

    # ------------------------------------------------------------------
    # Trace / Memory helpers
    # ------------------------------------------------------------------

    def _trace(self, event_type: str, conversation_id: str, **payload: object) -> None:
        """Fire-and-forget trace write (non-blocking, best-effort)."""
        if self._trace_writer is None or self._bridge is None:
            return
        try:
            self._bridge.fire(
                self._trace_writer.log(
                    conversation_id=conversation_id,
                    agent_name="cagent_os",
                    event_type=event_type,
                    **payload,
                )
            )
        except Exception:
            logger.debug("Trace write skipped", exc_info=True)

    @staticmethod
    def _extract_tickers(arguments: dict[str, object]) -> list[str]:
        """Heuristic ticker extraction from tool call arguments."""
        tickers: list[str] = []
        for key in ("symbol", "symbols", "ticker", "tickers"):
            val = arguments.get(key)
            if isinstance(val, str):
                tickers.append(val.upper())
            elif isinstance(val, list):
                tickers.extend(str(v).upper() for v in val)
        return tickers

    def _maybe_save_facts(
        self,
        *,
        user_id: str,
        capability_id: str,
        arguments: dict[str, object],
        result: object,
    ) -> None:
        """Auto-save ticker query facts to memory after tool execution."""
        if self._memory is None or self._bridge is None:
            return
        tickers = self._extract_tickers(arguments)
        if not tickers:
            return
        content = getattr(result, "content", None)
        for ticker in tickers:
            try:
                summary = {}
                if isinstance(content, dict):
                    items = content.get("items", [])
                    if items and isinstance(items[0], dict):
                        item = items[0]
                        summary = {
                            k: item[k] for k in ("price", "currency", "data_source")
                            if k in item
                        }
                fact = UserFact(
                    user_id=user_id,
                    key=f"last_query_{ticker}",
                    value={"capability": capability_id, "at": datetime.datetime.utcnow().isoformat(), **summary},
                    source="auto",
                )
                self._bridge.fire(self._memory.save_fact(fact))
            except Exception:
                logger.debug("Auto-save fact skipped for %s", ticker, exc_info=True)

    def _finalize_assistant_content(
        self,
        *,
        conversation_id: str,
        content: str,
        consecutive_exceptional_tool_failures: int,
    ) -> str:
        if str(content or "").strip():
            return content
        fallback = self._fallback_answer_for_tool_failures(
            conversation_id=conversation_id,
            consecutive_exceptional_tool_failures=consecutive_exceptional_tool_failures,
        )
        return fallback or content

    def _fallback_answer_for_tool_failures(
        self,
        *,
        conversation_id: str,
        consecutive_exceptional_tool_failures: int,
    ) -> str:
        last_failure = self._latest_tool_failure(conversation_id)
        if last_failure is None:
            return ""
        error_code = str(last_failure.data.get("error_code", "")).strip() or "tool_failed"
        if consecutive_exceptional_tool_failures >= MAX_CONSECUTIVE_TOOL_ERRORS:
            return (
                "I hit 3 consecutive tool exceptions and stopped the live-tool attempt to avoid a silent failure. "
                f"Latest error: `{error_code}`. I do not have enough reliable data to answer safely from tools alone."
            )
        return (
            "I could not complete all live tool calls, so I do not have enough reliable tool data for a grounded answer. "
            f"Latest error: `{error_code}`."
        )

    def _latest_tool_failure(self, conversation_id: str) -> JournalEntry | None:
        events = self._event_store.list_events(conversation_id)
        for event in reversed(events):
            if event.type == "run.started":
                break
            if event.type == "run.tool_failed":
                return event
        return None

    @staticmethod
    def _counts_as_exceptional_tool_failure(event: JournalEntry) -> bool:
        if event.type != "run.tool_failed":
            return False
        error_code = str(event.data.get("error_code", "")).strip()
        if error_code in SOFT_ERROR_CODES:
            return False
        result = event.data.get("result")
        if isinstance(result, dict):
            raw_error = str(result.get("error", "")).strip()
            if raw_error in SOFT_ERROR_CODES:
                return False
        return True


_URL_PATTERN = re.compile(r"https?://\S+")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _build_read_later_prompt_injection(user_content: str) -> str:
    """Build a routing hint when user sends a URL.

    Intent priority (highest to lowest):
    1. Keywords present (存档/save/rL/收藏/摘录/L1) → MUST call Skill(skill="read-later")
    2. Bare URL (no accompanying text/question) → default to archive → call Skill(skill="read-later")
    3. URL + question → just web.fetch directly, do NOT load read-later
    """
    if not _URL_PATTERN.search(user_content):
        return ""
    _hint = (
        "# URL Routing Hint\n"
    )
    _archive_kw = ("存档", "save", "rL", "rl", "read later", "收藏", "摘录", "L1")
    _is_bare = _URL_PATTERN.sub("", user_content).strip() == ""
    _has_kw = any(kw.lower() in user_content.lower() for kw in _archive_kw)
    if _has_kw or _is_bare:
        _hint += (
            'User sent a URL with archive intent. You MUST call `Skill` with '
            '`skill="read-later"` to activate the L1/L2/L3 progressive disclosure '
            'protocol. Do NOT produce a full summary directly — follow the '
            "skill's workflow: fetch → L1 card → write.file to knowledge/00_Inbox/."
        )
    else:
        _hint += (
            "User sent a URL with a specific question. Answer directly using "
            "`web.fetch` — do NOT load the read-later skill."
        )
    return _hint
