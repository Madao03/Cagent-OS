from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec, PluginSpec
from cagent_os.plugins.plugin import Plugin
from cagent_os.shared.prompt_time import render_prompt_datetime_context
from cagent_os.user_skills.models import UserSkillDocument
from cagent_os.user_skills.parsing import extract_skill_body
from cagent_os.user_skills import UserSkillService

logger = logging.getLogger(__name__)

SKILL_TOOL_NAME = "Skill"


def build_skill_tool_description(documents: list[UserSkillDocument] | tuple[UserSkillDocument, ...]) -> str:
    if not documents:
        descriptions = "(no skills available)"
    else:
        descriptions = "\n".join(
            f"- {document.name}: {document.description}" for document in documents
        )
    return f"""Load a skill to gain specialized knowledge for a task.

Available skills:
{descriptions}

When to use:
- IMMEDIATELY when user task matches a skill description
- Before attempting domain-specific work (PDF, MCP, etc.)

The skill content will be injected into the conversation, giving you
detailed instructions and access to resources."""


class SkillsPlugin(Plugin):
    def __init__(
        self,
        *,
        user_skill_service: UserSkillService,
        skills_data_dir: Path | str,
        shared_skills_dir: Path | str | None = None,
    ) -> None:
        self._user_skill_service = user_skill_service
        self._skills_data_dir = Path(skills_data_dir)
        self._shared_skills_dir = Path(shared_skills_dir) if shared_skills_dir else None

    def manifest(self) -> PluginSpec:
        return PluginSpec(
            plugin_id="skills",
            default_enabled=True,
            capabilities=[
                ToolSpec(
                    capability_id=SKILL_TOOL_NAME,
                    trust_level=ToolTrustLevel.FILESYSTEM,
                    description=build_skill_tool_description(()),
                    parameters={
                        "type": "object",
                        "properties": {
                            "skill": {
                                "type": "string",
                                "description": "Name of the skill to load",
                            },
                        },
                        "required": ["skill"],
                    },
                )
            ],
        )

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        if capability_id != SKILL_TOOL_NAME:
            raise KeyError(capability_id)
        return self._handle_load

    def _handle_load(self, request: ToolRequest) -> ToolResult:
        user_id = str(request.context.get("user_id", "")).strip()
        if not user_id:
            return ToolResult(
                status="error",
                error_code="missing_user_context",
                content="Error: user_id context is required for Skill.",
            )
        skill_name = str(request.arguments.get("skill", "")).strip()
        logger.info(
            "Skill load requested user_id=%s skill_name=%s cwd=%s",
            user_id, skill_name, str(Path.cwd()),
        )
        try:
            skill = self._user_skill_service.get_skill(user_id, skill_name)
            logger.info("Skill loaded successfully name=%s", skill.name)
        except KeyError:
            # Debug: list runtime skills directly from store
            if hasattr(self._user_skill_service._store, "load_runtime_skills"):
                runtime = self._user_skill_service._store.load_runtime_skills(user_id)
                logger.warning(
                    "Skill not found user_id=%s skill_name=%s runtime_skills=%s",
                    user_id, skill_name, [d.name for d in runtime],
                )
            all_skills = self._user_skill_service.list_skills(user_id)
            available = ", ".join(document.name for document in all_skills) or "none"
            logger.warning(
                "Skill not found user_id=%s skill_name=%s available=%s",
                user_id, skill_name, available,
            )
            return ToolResult(
                status="error",
                error_code="skill_not_found",
                content=f"Error: Unknown skill '{skill_name}'. Available: {available}",
            )

        return ToolResult(status="ok", content=self._render_skill_content(user_id=user_id, skill=skill))

    def _render_skill_content(self, *, user_id: str, skill: UserSkillDocument) -> str:
        content = "\n\n".join(
            [
                render_prompt_datetime_context(),
                f"# Skill: {skill.name}",
                extract_skill_body(skill.content),
            ]
        )
        skill_dir = self._resolve_skill_dir(user_id=user_id, skill_name=skill.name)
        resources = self._list_resources(skill_dir)
        if resources:
            content += f"\n\n**Available resources in {skill_dir}:**\n"
            content += "\n".join(f"- {resource}" for resource in resources)
        return f"""<skill-loaded name="{skill.name}">
{content}
</skill-loaded>

Follow the instructions in the skill above to complete the user's task."""

    def _resolve_skill_dir(self, *, user_id: str, skill_name: str) -> Path:
        user_skill_dir = self._skills_data_dir / user_id / "skills" / skill_name
        if user_skill_dir.exists() and user_skill_dir.is_dir():
            return user_skill_dir
        if self._shared_skills_dir is not None:
            shared_skill_dir = self._shared_skills_dir / skill_name
            if shared_skill_dir.exists() and shared_skill_dir.is_dir():
                return shared_skill_dir
        return user_skill_dir

    def _list_resources(self, skill_dir: Path) -> list[str]:
        if not skill_dir.exists() or not skill_dir.is_dir():
            return []
        resources: list[str] = []
        for folder_name, label in (
            ("scripts", "Scripts"),
            ("references", "References"),
            ("assets", "Assets"),
        ):
            folder = skill_dir / folder_name
            if not folder.exists() or not folder.is_dir():
                continue
            files = [path.name for path in sorted(folder.iterdir()) if path.is_file()]
            if files:
                resources.append(f"{label}: {', '.join(files)}")
        return resources
