"""LLM Backend factory — instantiates the correct backend based on LLM_PROVIDER setting."""

from __future__ import annotations

import logging

from cagent_os.config import Settings, get_settings
from cagent_os.llm.base import LLMBackend

logger = logging.getLogger(__name__)

# Provider → default base URL
_DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "together": "https://api.together.xyz/v1",
}


def create_backend(settings: Settings | None = None) -> LLMBackend:
    """Instantiate the LLM backend based on LLM_PROVIDER configuration.

    Supported providers:
      - openrouter  → OpenRouterBackend (existing, dot-encoding + capabilities)
      - deepseek    → OpenAICompatibleBackend at api.deepseek.com
      - openai      → OpenAICompatibleBackend at api.openai.com
      - anthropic   → OpenAICompatibleBackend at api.anthropic.com (compat endpoint)
      - groq / siliconflow / together  → OpenAICompatibleBackend at their endpoints
      - custom      → OpenAICompatibleBackend at user-provided base URL
    """
    settings = settings or get_settings()
    provider = settings.llm_provider.lower().strip()

    if provider == "openrouter":
        from cagent_os.llm.openrouter_backend import OpenRouterBackend
        return OpenRouterBackend(settings=settings)

    if provider == "custom":
        from cagent_os.llm.openai_compatible_backend import OpenAICompatibleBackend
        api_key = settings.llm_api_key
        base_url = settings.llm_base_url
        if not base_url:
            raise RuntimeError("LLM_BASE_URL is required when LLM_PROVIDER=custom")
        if not api_key:
            raise RuntimeError("LLM_API_KEY is required when LLM_PROVIDER=custom")
        logger.info("Using custom LLM endpoint: %s", base_url)
        return OpenAICompatibleBackend(api_key=api_key, base_url=base_url, settings=settings)

    # ── Known OpenAI-compatible providers ──
    base_url = _DEFAULT_BASE_URLS.get(provider)
    if base_url is not None:
        from cagent_os.llm.openai_compatible_backend import OpenAICompatibleBackend
        api_key = _resolve_api_key(settings, provider)
        if not api_key:
            raise RuntimeError(
                f"API key not configured for provider '{provider}'. "
                f"Set {provider.upper()}_API_KEY or LLM_API_KEY."
            )
        return OpenAICompatibleBackend(api_key=api_key, base_url=base_url, settings=settings)

    raise ValueError(
        f"Unknown LLM provider: '{settings.llm_provider}'. "
        f"Supported: openrouter, deepseek, openai, anthropic, groq, siliconflow, together, custom."
    )


def _resolve_api_key(settings: Settings, provider: str) -> str:
    """Resolve API key: try provider-specific key first, then generic LLM_API_KEY."""
    provider_key_map: dict[str, str] = {
        "deepseek": settings.deepseek_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
    }
    specific = provider_key_map.get(provider, "")
    return specific or settings.llm_api_key
