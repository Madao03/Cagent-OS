from __future__ import annotations

from dataclasses import replace

from cagent_os.llm.capabilities import ModelCapabilities
from cagent_os.llm.protocol import ModelRequest


class RequestNegotiator:
    def negotiate(self, request: ModelRequest, capabilities: ModelCapabilities) -> ModelRequest:
        if not capabilities.parameter_support_known:
            return request

        options = request.options
        tools = request.tools

        if not capabilities.supports_tools:
            tools = []
            options = replace(options, tool_choice=None, parallel_tool_calls=None)

        if not capabilities.supports_reasoning:
            options = replace(options, reasoning=None)

        if not capabilities.supports_structured_outputs:
            options = replace(options, response_format=None)

        return replace(request, tools=tools, options=options)
