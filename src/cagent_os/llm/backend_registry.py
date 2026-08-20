"""Backend registry — per-user LLM backend cache for BYOK.

Replaces the singleton backend for users who configured their own API key.
Falls back to the platform backend for everyone else.

Usage:
    registry = BackendRegistry(
        default_backend=create_backend(settings),
        key_store=UserLLMKeyStore(db_path),
    )
    backend, model, is_user_key = registry.resolve_for(user_id)
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, replace

from cagent_os.auth.user_llm_key_store import UserLLMConfig, UserLLMKeyStore
from cagent_os.config import Settings
from cagent_os.llm.base import LLMBackend
from cagent_os.llm.factory import _DEFAULT_BASE_URLS
from cagent_os.llm.protocol import ModelRequest, ModelResponse, StreamChunk

logger = logging.getLogger(__name__)

_CACHE_MAX = 50          # max cached backends
_CACHE_TTL_SEC = 3600    # 1 hour

# Secret-looking tokens that must never appear in logs (API keys, Bearer tokens)
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9_\-.]{6,})")


def redact_secrets(text: str) -> str:
    """Mask anything that looks like an API key before it reaches a log line."""
    return _SECRET_RE.sub(lambda m: m.group(0)[:5] + "***REDACTED***", text)


class FallbackBackend(LLMBackend):
    """Wraps a user-key backend; on failure, retries once with the platform backend.

    - ``complete()``: any primary failure → retry on platform.
    - ``stream()``: only falls back if *nothing* was yielded yet (retrying
      mid-stream would duplicate output).
    - Retargets ``model`` to the platform default — user-chosen model names
      (e.g. glm-4-flash) don't exist on the platform provider.
    - ``fallback_used`` is inspected after a run for cost attribution
      (billed_to: platform_key vs user_key).
    """

    def __init__(
        self,
        primary: LLMBackend,
        fallback: LLMBackend,
        *,
        user_id: str,
        provider: str,
        platform_model: str | None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._user_id = user_id
        self._provider = provider
        self._platform_model = platform_model
        self.fallback_used = False

    # ── LLMBackend API ──

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            return self._primary.complete(request)
        except Exception as exc:
            self._log_fallback(exc, request)
            return self._fallback.complete(self._retarget(request))

    def stream(self, request: ModelRequest) -> Iterator[StreamChunk]:
        emitted = False
        try:
            for chunk in self._primary.stream(request):
                emitted = True
                yield chunk
            return
        except Exception as exc:
            if emitted:
                # Mid-stream failure — retrying would duplicate output.
                raise
            self._log_fallback(exc, request)
        yield from self._fallback.stream(self._retarget(request))

    # ── Internals ──

    def _retarget(self, request: ModelRequest) -> ModelRequest:
        if self._platform_model and request.model != self._platform_model:
            return replace(request, model=self._platform_model)
        return request

    def _log_fallback(self, exc: Exception, request: ModelRequest) -> None:
        self.fallback_used = True
        logger.warning(
            "BYOK backend failed — falling back to platform key "
            "(user=%s provider=%s model=%s error=%s: %s)",
            self._user_id,
            self._provider,
            request.model,
            type(exc).__name__,
            redact_secrets(str(exc))[:300],
        )


@dataclass(frozen=True)
class ResolvedBackend:
    backend: LLMBackend
    default_model: str | None
    is_user_key: bool
    provider: str


def _build_user_backend(cfg: UserLLMConfig, settings: Settings) -> LLMBackend:
    """Instantiate a backend from a user's stored config."""
    provider = cfg.provider.lower().strip()

    if provider == "openrouter":
        from cagent_os.llm.openrouter_backend import OpenRouterBackend
        # Inject user key by cloning settings with overridden key.
        from dataclasses import replace
        user_settings = replace(settings, openrouter_api_key=cfg.api_key)
        return OpenRouterBackend(settings=user_settings)

    if provider == "custom":
        from cagent_os.llm.openai_compatible_backend import OpenAICompatibleBackend
        return OpenAICompatibleBackend(
            api_key=cfg.api_key,
            base_url=settings.llm_base_url,
            settings=settings,
        )

    base_url = _DEFAULT_BASE_URLS.get(provider)
    if base_url is None:
        raise ValueError(
            f"Unsupported provider for BYOK: '{provider}'. "
            f"Supported: openrouter, openai, anthropic, deepseek, groq, siliconflow, "
            f"together, zhipu, moonshot, qwen, custom."
        )
    from cagent_os.llm.openai_compatible_backend import OpenAICompatibleBackend
    return OpenAICompatibleBackend(api_key=cfg.api_key, base_url=base_url, settings=settings)


class BackendRegistry:
    """Thread-safe LRU cache of per-user LLM backends."""

    def __init__(self, default_backend: LLMBackend, key_store: UserLLMKeyStore, settings: Settings) -> None:
        self._default_backend = default_backend
        self._key_store = key_store
        self._settings = settings
        self._cache: OrderedDict[str, tuple[LLMBackend, UserLLMConfig, float]] = OrderedDict()
        self._lock = threading.Lock()
        # Platform default model — used when retargeting a fallback request
        # (user-chosen model names don't exist on the platform provider).
        from cagent_os.llm.router import ModelRouter
        self._platform_model = ModelRouter().resolve(settings.default_model_alias)

    def _wrap(self, backend: LLMBackend, user_id: str, provider: str) -> LLMBackend:
        """Wrap a user-key backend with platform fallback (fresh state per run)."""
        return FallbackBackend(
            backend,
            self._default_backend,
            user_id=user_id,
            provider=provider,
            platform_model=self._platform_model,
        )

    def probe_backend(self, user_id: str) -> LLMBackend | None:
        """Raw user backend WITHOUT fallback — for key connectivity testing.

        A broken key must surface as an error here, not be masked by the
        platform fallback.
        """
        cfg = self._key_store.get(user_id)
        if cfg is None:
            return None
        return _build_user_backend(cfg, self._settings)

    def resolve_for(self, user_id: str) -> ResolvedBackend:
        """Get the backend + default model for a user.

        - User has a configured key → per-user backend (from cache or freshly built)
        - No key → platform default backend
        """
        # Fast path: cache hit
        with self._lock:
            entry = self._cache.get(user_id)
            if entry and (time.time() - entry[2]) < _CACHE_TTL_SEC:
                self._cache.move_to_end(user_id)
                backend, cfg, _ = entry
                return ResolvedBackend(
                    backend=self._wrap(backend, user_id, cfg.provider),
                    default_model=cfg.default_model,
                    is_user_key=True,
                    provider=cfg.provider,
                )
            if entry:
                # Expired — evict
                del self._cache[user_id]

        # Slow path: read key store
        cfg = self._key_store.get(user_id)
        if cfg is None:
            return ResolvedBackend(
                backend=self._default_backend,
                default_model=None,
                is_user_key=False,
                provider=self._settings.llm_provider,
            )

        try:
            backend = _build_user_backend(cfg, self._settings)
        except Exception:
            logger.exception("Failed to build user backend user=%s provider=%s — falling back to platform", user_id, cfg.provider)
            return ResolvedBackend(
                backend=self._default_backend,
                default_model=None,
                is_user_key=False,
                provider=self._settings.llm_provider,
            )

        with self._lock:
            self._cache[user_id] = (backend, cfg, time.time())
            self._cache.move_to_end(user_id)
            while len(self._cache) > _CACHE_MAX:
                self._cache.popitem(last=False)

        return ResolvedBackend(
            backend=self._wrap(backend, user_id, cfg.provider),
            default_model=cfg.default_model,
            is_user_key=True,
            provider=cfg.provider,
        )

    def invalidate(self, user_id: str) -> None:
        """Drop cached backend for a user (call after key update/delete)."""
        with self._lock:
            self._cache.pop(user_id, None)

    def clear(self) -> None:
        """Drop all cached backends."""
        with self._lock:
            self._cache.clear()
