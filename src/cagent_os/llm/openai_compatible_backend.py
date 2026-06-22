"""Generic LLM backend for any OpenAI-compatible API (DeepSeek, OpenAI, Groq, etc.)."""

from __future__ import annotations

import json
from collections.abc import Iterator
import logging
import time
from typing import Any

import httpx

from cagent_os.config import Settings, get_settings
from cagent_os.llm.base import LLMBackend
from cagent_os.llm.capabilities import ModelCapabilities
from cagent_os.llm.negotiation import RequestNegotiator
from cagent_os.llm.protocol import StreamChunk, ChatMessage, ModelRequest, ModelResponse, ToolCall
from cagent_os.shared.logging_utils import build_log_extra, format_log_context

logger = logging.getLogger(__name__)


class OpenAICompatibleBackend(LLMBackend):
    """Backend for any OpenAI-compatible API: DeepSeek, OpenAI, Groq, Together, etc.

    Applies dot-encoding to tool names (``.`` → ``__dot__``) so providers with
    strict name validation (DeepSeek: ``^[a-zA-Z0-9_-]+$``) work correctly.
    Does NOT add OpenRouter-specific HTTP headers or capabilities lookups.
    """

    _DOT_TOKEN = "__dot__"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        settings: Settings | None = None,
        client: Any | None = None,
        negotiator: RequestNegotiator | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._settings = settings or get_settings()
        self._negotiator = negotiator or RequestNegotiator()
        self._client = client

    # ── Public API ──

    def complete(self, request: ModelRequest) -> ModelResponse:
        started_at = time.perf_counter()
        negotiated = self._negotiate(request)
        try:
            response = self._ensure_client().chat.completions.create(**self._build_payload(negotiated))
        except Exception:
            logger.exception(
                "LLM completion failed %s",
                format_log_context(model=request.model, message_count=len(request.messages)),
                extra=build_log_extra(model=request.model, message_count=len(request.messages)),
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
            "LLM completion succeeded %s",
            format_log_context(
                model=request.model,
                finish_reason=choice.finish_reason,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            ),
            extra=build_log_extra(
                model=request.model,
                finish_reason=choice.finish_reason,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
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
                "LLM stream failed to start %s",
                format_log_context(model=request.model, message_count=len(request.messages)),
                extra=build_log_extra(model=request.model, message_count=len(request.messages)),
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
                    entry = tool_call_chunks.setdefault(index, {"id": "", "name": "", "arguments": ""})
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
                    "LLM stream decode failed %s",
                    format_log_context(model=request.model, tool_call_id=chunk["id"]),
                    extra=build_log_extra(model=request.model, tool_call_id=chunk["id"]),
                )
                raise
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id=chunk["id"],
                    name=self._decode_tool_name(chunk["name"]),
                    arguments=arguments,
                ),
            )
        logger.info(
            "LLM stream completed %s",
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

    # ── Internal helpers ──

    def _build_client(self):
        from openai import OpenAI

        if not self._api_key:
            raise RuntimeError("API key is not configured for the selected LLM provider")

        return OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
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
        capabilities = ModelCapabilities.unknown(request.model)
        return self._negotiator.negotiate(request, capabilities)

    def _build_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": self._encode_messages([m.to_openai() for m in request.messages]),
            "max_tokens": request.options.max_tokens,
        }
        if request.tools:
            payload["tools"] = self._encode_tools([t.to_openai() for t in request.tools])
        if request.options.temperature is not None:
            payload["temperature"] = request.options.temperature
        if request.options.reasoning is not None:
            payload["reasoning"] = {"effort": request.options.reasoning.effort}
            if request.options.reasoning.include_reasoning:
                payload["include_reasoning"] = True
        if request.options.response_format is not None:
            payload["response_format"] = request.options.response_format
        if request.options.tool_choice is not None:
            payload["tool_choice"] = self._encode_tool_choice(request.options.tool_choice)
        if request.options.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = request.options.parallel_tool_calls
        return payload

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
                    name=self._decode_tool_name(getattr(function, "name", "") if function else ""),
                    arguments=arguments,
                )
            )
        return ChatMessage(
            role=getattr(message, "role", "assistant"),
            content=getattr(message, "content", "") or "",
            tool_calls=tool_calls,
        )

    # ── Tool name encoding (DeepSeek rejects dots in tool names) ──

    def _encode_tool_name(self, name: str) -> str:
        return name.replace(".", self._DOT_TOKEN)

    def _decode_tool_name(self, name: str) -> str:
        return name.replace(self._DOT_TOKEN, ".")

    def _encode_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tool in tools:
            t = dict(tool)
            func = dict(t.get("function", {}))
            func["name"] = self._encode_tool_name(str(func.get("name", "")))
            t["function"] = func
            result.append(t)
        return result

    def _encode_tool_choice(self, tool_choice: str | dict[str, Any]) -> str | dict[str, Any]:
        if isinstance(tool_choice, dict):
            func = tool_choice.get("function", {})
            if isinstance(func, dict) and "name" in func:
                return {**tool_choice, "function": {**func, "name": self._encode_tool_name(str(func["name"]))}}
        return tool_choice

    def _encode_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            m = dict(msg)
            tool_calls = m.get("tool_calls")
            if tool_calls:
                encoded_tcs = []
                for tc in tool_calls:
                    t = dict(tc)
                    func = dict(t.get("function", {}))
                    func["name"] = self._encode_tool_name(str(func.get("name", "")))
                    t["function"] = func
                    encoded_tcs.append(t)
                m["tool_calls"] = encoded_tcs
            result.append(m)
        return result

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
