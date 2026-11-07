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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cagent_os.config import get_settings as get_platform_settings
from cagent_os.auth.user_llm_key_store import DEEPSEEK_MODELS, KeyStoreUnavailable, UserLLMConfig, UserLLMKeyStore
from cagent_os.interfaces.http.auth_context import require_principal_id
from cagent_os.llm.backend_registry import BackendRegistry

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
    "deepseek": list(DEEPSEEK_MODELS),
    "groq": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
    "siliconflow": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"],
    "together": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    "zhipu": ["glm-4-plus", "glm-4-air", "glm-4-flash"],
    "moonshot": ["moonshot-v1-128k", "moonshot-v1-32k", "kimi-k2-0711-preview"],
    "qwen": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen2.5-72b-instruct"],
}


def platform_models() -> list[str]:
    settings = get_platform_settings()
    default = (settings.model_aliases or {}).get(settings.default_model_alias, settings.default_model_alias)
    choices = _COMMON_MODELS["deepseek"] if settings.llm_provider == "deepseek" else []
    return list(dict.fromkeys([default, *choices]))


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

    def requested_config(payload: LLMSettingsPayload, user_id: str) -> UserLLMConfig:
        provider = payload.provider.lower().strip()
        if provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(400, "不支持的模型服务商")
        if provider == "deepseek" and payload.default_model and payload.default_model not in DEEPSEEK_MODELS:
            raise HTTPException(400, "DeepSeek 请选择 V4.1 Flash 或 V4 Pro")
        api_key = payload.api_key.strip()
        if not api_key:
            existing = key_store.get(user_id)
            if existing and existing.provider == provider:
                api_key = existing.api_key
        if not api_key:
            raise HTTPException(400, "请输入该服务商的 API Key")
        return UserLLMConfig(provider, api_key, payload.default_model)

    @router.put("/api/v1/llm/settings")
    def put_settings(payload: LLMSettingsPayload, request: Request) -> dict:
        user_id = require_principal_id(request)
        cfg = requested_config(payload, user_id)
        try:
            key_store.upsert(
                user_id,
                provider=cfg.provider,
                api_key=cfg.api_key,
                default_model=payload.default_model,
            )
        except KeyStoreUnavailable as exc:
            return JSONResponse(status_code=503, content={"detail": str(exc)})
        except Exception:
            logger.exception("Failed to store user LLM key user=%s", user_id)
            return JSONResponse(status_code=500, content={"detail": "保存个人模型设置失败"})
        registry.invalidate(user_id)
        return {"ok": True, "provider": cfg.provider, "default_model": payload.default_model}

    @router.delete("/api/v1/llm/settings")
    def delete_settings(request: Request) -> dict:
        user_id = require_principal_id(request)
        key_store.delete(user_id)
        registry.invalidate(user_id)
        return {"ok": True, "cleared": True}

    @router.post("/api/v1/llm/test")
    def test_key(request: Request, payload: LLMSettingsPayload | None = None) -> dict:
        """Send a 1-token completion to verify the stored key works.

        Uses the RAW user backend (probe_backend) — no platform fallback —
        so a broken key surfaces as an error instead of silently succeeding
        via the platform key.
        """
        user_id = require_principal_id(request)
        cfg = requested_config(payload, user_id) if payload else key_store.get(user_id)
        if cfg is None:
            return {"ok": False, "detail": "请先配置个人模型 API Key"}
        try:
            backend = registry.probe_backend(user_id, cfg)
            if backend is None:
                return {"ok": False, "detail": "请先配置个人模型 API Key"}
            from cagent_os.llm.protocol import ChatMessage, InferenceOptions, ModelRequest
            model = cfg.default_model or _COMMON_MODELS[cfg.provider][0]
            req = ModelRequest(
                model=model,
                messages=[ChatMessage(role="user", content="ping")],
                options=InferenceOptions(max_tokens=1),
            )
            backend.complete(req)
            return {"ok": True, "provider": cfg.provider, "model": model}
        except Exception as exc:
            from cagent_os.llm.backend_registry import redact_secrets
            return {"ok": False, "provider": cfg.provider, "detail": redact_secrets(str(exc))[:200]}

    @router.get("/api/v1/llm/models")
    def list_models(request: Request) -> dict:
        """List a few common models per provider (static list — no API call)."""
        user_id = require_principal_id(request)
        cfg = key_store.get(user_id)
        provider = cfg.provider if cfg else None
        return {
            "platform_models": platform_models(),
            "user_id": user_id,
            "user_default": cfg.default_model if cfg else None,
            "configured_provider": provider,
            "models_by_provider": _COMMON_MODELS,
        }

    return router
