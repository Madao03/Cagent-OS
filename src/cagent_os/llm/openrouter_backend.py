from __future__ import annotations

import json
from collections.abc import Iterator
import logging
import time
from typing import Any

import httpx

from cagent_os.config import Settings, get_settings
from cagent_os.llm.adapters.openrouter import OpenRouterAdapter
from cagent_os.llm.base import LLMBackend
from cagent_os.llm.capabilities import (
    CapabilitiesResolver,
    ModelCapabilities,
    OpenRouterCapabilitiesProvider,
)
from cagent_os.llm.negotiation import RequestNegotiator
from cagent_os.llm.protocol import StreamChunk, ChatMessage, ModelRequest, ModelResponse, ToolCall
from cagent_os.shared.logging_utils import build_log_extra, format_log_context

logger = logging.getLogger(__name__)


class OpenRouterBackend(LLMBackend):
    def __init__(
        self,
        settings: Settings | None = None,
        capabilities_provider: CapabilitiesResolver | None = None,
        client: Any | None = None,
        negotiator: RequestNegotiator | None = None,
        adapter: OpenRouterAdapter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._capabilities_provider = capabilities_provider or OpenRouterCapabilitiesProvider(self._settings)
        self._negotiator = negotiator or RequestNegotiator()
        self._client = client
        self._adapter = adapter or OpenRouterAdapter()

    def complete(self, request: ModelRequest) -> ModelResponse:
        started_at = time.perf_counter()
        negotiated = self._negotiate(request)
        try:
            response = self._ensure_client().chat.completions.create(**self._build_payload(negotiated))
        except Exception:
            logger.exception(
                "OpenRouter completion failed %s",
                format_log_context(model=request.model, message_count=len(request.messages), tool_count=len(request.tools)),
                extra=build_log_extra(
                    model=request.model,
                    message_count=len(request.messages),
                    tool_count=len(request.tools),
                ),
            )
            raise
        choice = response.choices[0]
        llm_response = ModelResponse(
            message=self._convert_message(choice.message),
            finish_reason=choice.finish_reason,
            usage=self._dump_usage(getattr(response, "usage", None)),
            raw=response,
        )
        usage = llm_response.usage or {}
        logger.info(
            "OpenRouter completion succeeded %s",
            format_log_context(
                model=request.model,
                finish_reason=choice.finish_reason,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
            extra=build_log_extra(
                model=request.model,
                finish_reason=choice.finish_reason,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
        )
        return llm_response

    def stream(self, request: ModelRequest) -> Iterator[StreamChunk]:
        started_at = time.perf_counter()
        negotiated = self._negotiate(request)
        payload = self._build_payload(negotiated)
        payload["stream"] = True
        try:
            stream = self._ensure_client().chat.completions.create(**payload)
        except Exception:
            logger.exception(
                "OpenRouter stream failed to start %s",
                format_log_context(model=request.model, message_count=len(request.messages), tool_count=len(request.tools)),
                extra=build_log_extra(
                    model=request.model,
                    message_count=len(request.messages),
                    tool_count=len(request.tools),
                ),
            )
            raise
        tool_call_chunks: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        for chunk in stream:
            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            if getattr(delta, "content", None):
                yield StreamChunk(type="text", text=delta.content)
            if getattr(delta, "tool_calls", None):
                for tool_call in delta.tool_calls:
                    index = getattr(tool_call, "index", len(tool_call_chunks))
                    entry = tool_call_chunks.setdefault(
                        index,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    entry["id"] = getattr(tool_call, "id", None) or entry["id"]
                    function = getattr(tool_call, "function", None)
                    if function is None:
                        continue
                    entry["name"] = getattr(function, "name", None) or entry["name"]
                    arguments = getattr(function, "arguments", None)
                    if isinstance(arguments, str):
                        entry["arguments"] += arguments
                    elif isinstance(arguments, dict):
                        entry["arguments"] = json.dumps(arguments, ensure_ascii=False)
        for index in sorted(tool_call_chunks):
            chunk = tool_call_chunks[index]
            try:
                arguments = self._decode_stream_arguments(chunk["arguments"])
            except Exception:
                logger.exception(
                    "OpenRouter stream decode failed %s",
                    format_log_context(model=request.model, tool_call_id=chunk["id"]),
                    extra=build_log_extra(model=request.model, tool_call_id=chunk["id"]),
                )
                raise
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id=chunk["id"],
                    name=self._adapter.decode_tool_name(chunk["name"]),
                    arguments=arguments,
                ),
            )
        logger.info(
            "OpenRouter stream completed %s",
            format_log_context(
                model=request.model,
                finish_reason=finish_reason,
                tool_call_count=len(tool_call_chunks),
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
            extra=build_log_extra(
                model=request.model,
                finish_reason=finish_reason,
                tool_call_count=len(tool_call_chunks),
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
        )
        yield StreamChunk(type="done", finish_reason=finish_reason)

    def _build_client(self):
        from openai import OpenAI

        if not self._settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")

        headers = {}
        if self._settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self._settings.openrouter_http_referer
        if self._settings.openrouter_app_name:
            headers["X-Title"] = self._settings.openrouter_app_name

        return OpenAI(
            api_key=self._settings.openrouter_api_key,
            base_url=self._settings.openrouter_base_url,
            default_headers=headers or None,
            http_client=self._build_http_client(),
        )

    def _build_http_client(self):
        proxy = self._settings.effective_proxy
        if not proxy:
            return None
        return httpx.Client(proxy=proxy, trust_env=False)

    def _ensure_client(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _negotiate(self, request: ModelRequest) -> ModelRequest:
        capabilities = self._resolve_capabilities(request.model)
        return self._negotiator.negotiate(request, capabilities)

    def _resolve_capabilities(self, model: str) -> ModelCapabilities:
        provider = self._capabilities_provider
        if hasattr(provider, "get_capabilities"):
            return provider.get_capabilities(model)  # type: ignore[return-value]
        return provider(model)

    def _build_payload(self, request: ModelRequest) -> dict[str, Any]:
        return self._adapter.build_payload(request)

    def _convert_message(self, message: Any) -> ChatMessage:
        tool_calls = []
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = getattr(tool_call, "function", None)
            arguments = getattr(function, "arguments", {}) if function else {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            tool_calls.append(
                ToolCall(
                    id=getattr(tool_call, "id", ""),
                    name=self._adapter.decode_tool_name(
                        getattr(function, "name", "") if function else ""
                    ),
                    arguments=arguments,
                )
            )
        return ChatMessage(
            role=getattr(message, "role", "assistant"),
            content=getattr(message, "content", "") or "",
            tool_calls=tool_calls,
        )

    @staticmethod
    def _dump_usage(usage: Any) -> dict[str, Any] | None:
        if usage is None:
            return None
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if isinstance(usage, dict):
            return usage
        return None

    @staticmethod
    def _decode_stream_arguments(raw_arguments: str) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unable to decode streamed tool arguments: {raw_arguments}") from exc
        if not isinstance(arguments, dict):
            raise RuntimeError("Streamed tool arguments must decode to an object.")
        return arguments
