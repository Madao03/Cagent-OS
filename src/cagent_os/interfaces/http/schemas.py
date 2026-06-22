from __future__ import annotations

from pydantic import BaseModel, Field


class PostMessageRequest(BaseModel):
    content: str


class OneshotRunRequest(BaseModel):
    user_id: str
    content: str


class OneshotRunResponse(BaseModel):
    user_id: str
    assistant_content: str
    event_types: list[str] = Field(default_factory=list)
