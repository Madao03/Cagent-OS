from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from cagent_os.conversations.models import JournalEntry


def _preview(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > 220:
        return f"{text[:217]}..."
    return text


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def project_stream_payload(event: JournalEntry, *, conversation_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": event.type,
        "data": _json_safe(event.data),
        "conversation_id": conversation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": "milestone",
        "phase": "event",
        "summary": "Runtime event received.",
        "tool_name": "",
        "tool_status": "",
        "tool_input_preview": "",
        "tool_output_preview": "",
        "tool_error_code": "",
        "tool_message": "",
        "answer_chunk": "",
        "sources": [],
    }
    if event.role is not None:
        payload["role"] = event.role
        payload["content"] = event.content

    if event.type == "run.started":
        payload["phase"] = "start"
        payload["summary"] = "Agent run started."
    elif event.type == "message.assistant_tool_calls_added":
        tool_calls = event.data.get("tool_calls", [])
        payload["phase"] = "tool_plan"
        if tool_calls:
            first = tool_calls[0]
            payload["tool_name"] = str(first.get("name", ""))
            payload["tool_input_preview"] = _preview(first.get("arguments", {}))
    elif event.type == "run.tool_requested":
        payload["phase"] = "tool_call"
        payload["tool_name"] = str(event.data.get("name", ""))
        payload["tool_status"] = "running"
        payload["tool_input_preview"] = _preview(event.data.get("arguments", {}))
    elif event.type == "run.tool_completed":
        payload["phase"] = "tool_result"
        payload["tool_name"] = str(event.data.get("name", ""))
        payload["tool_status"] = str(event.data.get("status", "ok"))
        payload["tool_output_preview"] = _preview(event.data.get("result"))
    elif event.type == "run.tool_failed":
        payload["phase"] = "tool_result"
        payload["tool_name"] = str(event.data.get("name", ""))
        payload["tool_status"] = "error"
        payload["tool_error_code"] = str(event.data.get("error_code", ""))
        payload["tool_message"] = str(event.data.get("message", ""))
    elif event.type == "message.assistant_delta":
        payload["category"] = "incremental"
        payload["phase"] = "answer_delta"
        payload["answer_chunk"] = event.content
    elif event.type == "message.assistant_added":
        payload["phase"] = "final_answer"
        payload["answer_chunk"] = event.content
    elif event.type == "run.completed":
        payload["phase"] = "done"
        payload["summary"] = "Run completed."
    elif event.type == "run.failed":
        payload["category"] = "error"
        payload["phase"] = "error"
        payload["tool_name"] = str(event.data.get("capability_id", ""))
        payload["summary"] = str(event.data.get("message", event.data.get("reason", "Run failed.")))
    return payload
