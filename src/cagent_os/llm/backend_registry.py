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
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from cagent_os.auth.user_llm_key_store import UserLLMConfig, UserLLMKeyStore
from cagent_os.config import Settings
from cagent_os.llm.base import LLMBackend
from cagent_os.llm.factory import _DEFAULT_BASE_URLS

logger = logging.getLogger(__name__)

_CACHE_MAX = 50          # max cached backends
_CACHE_TTL_SEC = 3600    # 1 hour


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
            f"Supported: openrouter, openai, anthropic, deepseek, groq, siliconflow, together, custom."
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
                    backend=backend,
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
            backend=backend,
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
