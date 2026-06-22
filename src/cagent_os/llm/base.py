from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from cagent_os.llm.protocol import StreamChunk, ModelRequest, ModelResponse


class LLMBackend(ABC):
    @abstractmethod
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    @abstractmethod
    def stream(self, request: ModelRequest) -> Iterator[StreamChunk]:
        raise NotImplementedError
