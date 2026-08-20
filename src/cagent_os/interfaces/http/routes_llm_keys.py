"""LLM key management routes — BYOK (bring your own key) settings API.

Endpoints (all require auth):
  GET    /api/v1/llm/settings   — current config (key masked)
  PUT    /api/v1/llm/settings   — save provider + key + default model
  DELETE /api/v1/llm/settings   — clear (fall back to platform key)
  POST   /api/v1/llm/test       — test the stored key with a tiny completion
  GET    /api/v1/llm/models     — list models for the configured provider
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cagent_os.auth.user_llm_key_store import UserLLMKeyStore
from cagent_os.interfaces.http.auth_context import require_principal_id
from cagent_os.llm.backend_registry import BackendRegistry
from cagent_os.llm.factory import _DEFAULT_BASE_URLS

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = [
    "openrouter", "openai", "anthropic", "deepseek", "groq",
    "siliconflow", "together", "zhipu", "moonshot", "qwen",
]


class LLMSettingsPayload(BaseModel):
    provider: str
    api_key: str
    default_model: str | None = None


_COMMON_MODELS: dict[str, list[str]] = {
    "openrouter": [
        "anthropic/claude-sonnet-4",
        "anthropic/claude-3.5-haiku",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "deepseek/deepseek-chat",
        "google/gemini-flash-1.5",
        "qwen/qwen-2.5-72b-instruct",
    ],
    "openai": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    "anthropic": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "groq": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
    "siliconflow": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"],
    "together": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    "zhipu": ["glm-4-plus", "glm-4-air", "glm-4-flash"],
    "moonshot": ["moonshot-v1-128k", "moonshot-v1-32k", "kimi-k2-0711-preview"],
    "qwen": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen2.5-72b-instruct"],
}


def build_llm_keys_router(key_store: UserLLMKeyStore, registry: BackendRegistry) -> APIRouter:
    router = APIRouter()
    @router.get("/api/v1/llm/settings")
    def get_settings(request: Request) -> dict:
        user_id = require_principal_id(request)
        cfg = key_store.get(user_id)
        if cfg is None:
            return {"configured": False, "supported_providers": SUPPORTED_PROVIDERS}
        return {
            "configured": True,
            "provider": cfg.provider,
            "api_key_masked": key_store.mask_key(cfg.api_key),
            "default_model": cfg.default_model,
            "supported_providers": SUPPORTED_PROVIDERS,
        }

    @router.put("/api/v1/llm/settings")
    def put_settings(payload: LLMSettingsPayload, request: Request) -> dict:
        user_id = require_principal_id(request)
        provider = payload.provider.lower().strip()
        if provider not in SUPPORTED_PROVIDERS:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Unsupported provider '{provider}'. Supported: {SUPPORTED_PROVIDERS}"},
            )
        if not payload.api_key.strip():
            return JSONResponse(status_code=400, content={"detail": "api_key is required"})
        try:
            key_store.upsert(
                user_id,
                provider=provider,
                api_key=payload.api_key.strip(),
                default_model=payload.default_model,
            )
        except Exception as exc:
            logger.exception("Failed to store user LLM key user=%s", user_id)
            return JSONResponse(status_code=500, content={"detail": str(exc)})
        registry.invalidate(user_id)
        return {"ok": True, "provider": provider, "default_model": payload.default_model}

    @router.delete("/api/v1/llm/settings")
    def delete_settings(request: Request) -> dict:
        user_id = require_principal_id(request)
        key_store.delete(user_id)
        registry.invalidate(user_id)
        return {"ok": True, "cleared": True}

    @router.post("/api/v1/llm/test")
    def test_key(request: Request) -> dict:
        """Send a 1-token completion to verify the stored key works."""
        user_id = require_principal_id(request)
        resolved = registry.resolve_for(user_id)
        if not resolved.is_user_key:
            return {"ok": False, "detail": "No user key configured — testing platform key."}
        try:
            from cagent_os.llm.protocol import ChatMessage, InferenceOptions, ModelRequest
            req = ModelRequest(
                model=resolved.default_model or "gpt-4o-mini",
                messages=[ChatMessage(role="user", content="ping")],
                options=InferenceOptions(max_tokens=1),
            )
            resolved.backend.complete(req)
            return {"ok": True, "provider": resolved.provider, "model": resolved.default_model}
        except Exception as exc:
            return {"ok": False, "provider": resolved.provider, "detail": str(exc)[:200]}

    @router.get("/api/v1/llm/models")
    def list_models(request: Request) -> dict:
        """List a few common models per provider (static list — no API call)."""
        user_id = require_principal_id(request)
        cfg = key_store.get(user_id)
        provider = cfg.provider if cfg else None
        return {
            "configured_provider": provider,
            "models_by_provider": _COMMON_MODELS,
        }

    return router
