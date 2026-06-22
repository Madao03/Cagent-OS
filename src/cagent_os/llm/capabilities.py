from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Protocol

import requests

from cagent_os.config import Settings, get_settings
from cagent_os.llm.protocol import ModelRequest
from cagent_os.shared.logging_utils import build_log_extra, format_log_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelCapabilities:
    model: str
    supported_parameters: frozenset[str] = frozenset()
    parameter_support_known: bool = False

    @classmethod
    def unknown(cls, model: str) -> "ModelCapabilities":
        return cls(model=model)

    @property
    def supports_tools(self) -> bool:
        return (not self.parameter_support_known) or ("tools" in self.supported_parameters)

    @property
    def supports_reasoning(self) -> bool:
        return (not self.parameter_support_known) or bool(
            {"reasoning", "reasoning_effort", "include_reasoning"} & self.supported_parameters
        )

    @property
    def supports_structured_outputs(self) -> bool:
        return (not self.parameter_support_known) or (
            "response_format" in self.supported_parameters
            or "structured_outputs" in self.supported_parameters
        )


class CapabilitiesResolver(Protocol):
    def __call__(self, model: str) -> ModelCapabilities:
        ...


class OpenRouterCapabilitiesProvider:
    def __init__(self, settings: Settings | None = None, session: requests.Session | None = None) -> None:
        self._settings = settings or get_settings()
        self._session = session or requests.Session()
        self._session.trust_env = False
        if self._settings.effective_proxy:
            self._session.proxies = {
                "http": self._settings.effective_proxy,
                "https": self._settings.effective_proxy,
            }
        self._cache: dict[str, ModelCapabilities] = {}
        self._loaded = False

    def __call__(self, model: str) -> ModelCapabilities:
        return self.get_capabilities(model)

    def get_capabilities(self, model: str) -> ModelCapabilities:
        if model in self._cache:
            return self._cache[model]
        if not self._loaded:
            self._load_all()
        return self._cache.get(model, ModelCapabilities.unknown(model))

    def _load_all(self) -> None:
        self._loaded = True
        try:
            headers = {}
            if self._settings.openrouter_api_key:
                headers["Authorization"] = f"Bearer {self._settings.openrouter_api_key}"
            response = self._session.get(
                self._settings.openrouter_models_url,
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("data", []):
                model_id = item.get("id")
                if not model_id:
                    continue
                supported_parameters = frozenset(item.get("supported_parameters", []) or [])
                self._cache[model_id] = ModelCapabilities(
                    model=model_id,
                    supported_parameters=supported_parameters,
                    parameter_support_known=bool(supported_parameters),
                )
        except Exception:
            logger.warning(
                "OpenRouter capabilities lookup failed %s",
                format_log_context(models_url=self._settings.openrouter_models_url),
                extra=build_log_extra(models_url=self._settings.openrouter_models_url),
                exc_info=True,
            )
            self._cache = {}
