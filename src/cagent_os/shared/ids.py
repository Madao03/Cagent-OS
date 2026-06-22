from __future__ import annotations

from uuid import uuid4


def new_conversation_id() -> str:
    return f"conv_{uuid4().hex}"
