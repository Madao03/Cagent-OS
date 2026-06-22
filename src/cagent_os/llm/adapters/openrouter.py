from __future__ import annotations

from typing import Any

from cagent_os.llm.protocol import ModelRequest


class OpenRouterAdapter:
    _DOT_TOKEN = "__dot__"

    def build_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [self._encode_message(message.to_openai()) for message in request.messages],
            "max_tokens": request.options.max_tokens,
        }
        if request.tools:
            payload["tools"] = [self._encode_tool(tool.to_openai()) for tool in request.tools]
        if request.options.temperature is not None:
            payload["temperature"] = request.options.temperature
        if request.options.reasoning is not None:
            payload["reasoning"] = {"effort": request.options.reasoning.effort}
            if request.options.reasoning.include_reasoning:
                payload["include_reasoning"] = True
        if request.options.response_format is not None:
            payload["response_format"] = request.options.response_format
        if request.options.tool_choice is not None:
            payload["tool_choice"] = request.options.tool_choice
        if request.options.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = request.options.parallel_tool_calls
        return payload

    @classmethod
    def encode_tool_name(cls, name: str) -> str:
        return name.replace(".", cls._DOT_TOKEN)

    @classmethod
    def decode_tool_name(cls, name: str) -> str:
        return name.replace(cls._DOT_TOKEN, ".")

    def _encode_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        function = dict(payload.get("function", {}))
        function["name"] = self.encode_tool_name(str(function.get("name", "")))
        return {**payload, "function": function}

    def _encode_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool_calls = payload.get("tool_calls")
        if not tool_calls:
            return payload
        encoded_tool_calls = []
        for tool_call in tool_calls:
            function = dict(tool_call.get("function", {}))
            function["name"] = self.encode_tool_name(str(function.get("name", "")))
            encoded_tool_calls.append({**tool_call, "function": function})
        return {**payload, "tool_calls": encoded_tool_calls}
