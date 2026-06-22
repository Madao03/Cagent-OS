from __future__ import annotations

from collections.abc import Mapping

from cagent_os.config import get_settings


class ModelRouter:
    def __init__(self, aliases: Mapping[str, str] | None = None) -> None:
        self._aliases = dict(aliases or get_settings().model_aliases)

    def resolve(self, alias_or_model: str) -> str:
        return self._aliases.get(alias_or_model, alias_or_model)

    def known_aliases(self) -> dict[str, str]:
        return dict(self._aliases)
