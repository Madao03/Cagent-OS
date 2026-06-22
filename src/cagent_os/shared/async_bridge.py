"""AsyncBridge — dedicated event-loop thread for sync→async bridging.

AgentRuntime is a synchronous Iterator. MemoryAPI, TraceWriter, and DataLayer
are all async (aiosqlite under the hood). A single shared event-loop thread
bridges the gap without requiring an async AgentRuntime rewrite.

Usage:
    bridge = AsyncBridge()
    result = bridge.run(memory.get_hot_memory_prompt("user_1"), timeout=5)
    bridge.fire(trace_writer.log(conversation_id="c1", ...))  # no await
    bridge.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Coroutine

logger = logging.getLogger(__name__)


class AsyncBridge:
    """Runs async coroutines on a dedicated daemon thread with its own loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Coroutine[Any, Any, Any], timeout: float = 10.0) -> Any:
        """Schedule *coro* on the bridge loop and block until it completes."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def fire(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule *coro* without waiting (fire-and-forget).

        Suitable for non-critical side effects like trace writes where
        a lost event is preferable to blocking the agent loop.
        """
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception:
            logger.debug("AsyncBridge fire failed", exc_info=True)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def shutdown(self) -> None:
        """Stop the event loop and join the bridge thread.

        Call once on application exit. Stops the loop, then waits
        for the daemon thread to finish (up to 5 seconds) so the
        Python process can actually exit.
        """
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)
