from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .models import UserSkillDocument
from .parsing import extract_skill_description
from .store import UserSkillStore

import re

_USER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+$")
_INVALID_SKILL_NAME_CHARS = set('/\\:*?"<>|')


class FilesystemUserSkillStore(UserSkillStore):
    def __init__(
        self,
        data_dir: Path | str,
        *,
        shared_skills_dir: Path | str | None = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._shared_skills_dir = Path(shared_skills_dir) if shared_skills_dir else None

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def shared_skills_dir(self) -> Path | None:
        return self._shared_skills_dir

    def load_user_skills(self, user_id: str) -> Sequence[UserSkillDocument]:
        self._validate_user_id(user_id)
        return self._load_user_skills(user_id)

    def load_runtime_skills(self, user_id: str) -> Sequence[UserSkillDocument]:
        self._validate_user_id(user_id)
        documents_by_name = {document.name: document for document in self._load_shared_skills()}
        for document in self._load_user_skills(user_id):
            documents_by_name[document.name] = document
        return tuple(documents_by_name[name] for name in sorted(documents_by_name))

    def save_user_skill(self, user_id: str, skill_name: str, content: str) -> UserSkillDocument:
        self._validate_user_id(user_id)
        self._validate_skill_name(skill_name)
        skills_dir = self._data_dir / user_id / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        path = skills_dir / f"{skill_name}.md"
        path.write_text(content, encoding="utf-8")
        return UserSkillDocument(
            id=f"{user_id}:{path.name}",
            name=skill_name,
            content=content,
            description=extract_skill_description(content),
        )

    def _validate_user_id(self, user_id: str) -> None:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError(f"invalid user_id: {user_id!r}")

    def _validate_skill_name(self, skill_name: str) -> None:
        normalized = str(skill_name).strip()
        if not normalized or normalized in {".", ".."}:
            raise ValueError(f"invalid skill_name: {skill_name!r}")
        if any(char in _INVALID_SKILL_NAME_CHARS for char in normalized):
            raise ValueError(f"invalid skill_name: {skill_name!r}")
        if any(ord(char) < 32 for char in normalized):
            raise ValueError(f"invalid skill_name: {skill_name!r}")

    def _load_user_skills(self, user_id: str) -> tuple[UserSkillDocument, ...]:
        skills_dir = self._data_dir / user_id / "skills"
        if not skills_dir.exists() or not skills_dir.is_dir():
            return ()
        markdown_files = sorted(
            (
                path
                for path in skills_dir.iterdir()
                if path.is_file() and path.suffix.lower() == ".md"
            ),
            key=lambda path: path.name,
        )
        return tuple(
            self._build_document(
                id=f"{user_id}:{path.name}",
                name=path.stem,
                content=path.read_text(encoding="utf-8"),
            )
            for path in markdown_files
        )

    def _load_shared_skills(self) -> tuple[UserSkillDocument, ...]:
        shared_dir = self._shared_skills_dir
        if shared_dir is None or not shared_dir.exists() or not shared_dir.is_dir():
            return ()
        skill_files = sorted(
            (
                path / "SKILL.md"
                for path in shared_dir.iterdir()
                if path.is_dir() and (path / "SKILL.md").is_file()
            ),
            key=lambda path: path.parent.name,
        )
        return tuple(
            self._build_document(
                id=f"shared:{path.parent.name}",
                name=path.parent.name,
                content=path.read_text(encoding="utf-8"),
            )
            for path in skill_files
        )

    @staticmethod
    def _build_document(*, id: str, name: str, content: str) -> UserSkillDocument:
        return UserSkillDocument(
            id=id,
            name=name,
            content=content,
            description=extract_skill_description(content),
        )
