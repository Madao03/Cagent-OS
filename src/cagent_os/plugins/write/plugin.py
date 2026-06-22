from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec, PluginSpec
from cagent_os.config import Settings
from cagent_os.plugins.plugin import Plugin

logger = logging.getLogger(__name__)

WRITE_ALLOWED_ROOTS = ["knowledge"]


class WritePlugin(Plugin):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cwd = Path(__file__).resolve().parent.parent.parent.parent.parent

    def manifest(self) -> PluginSpec:
        return PluginSpec(
            plugin_id="write",
            default_enabled=True,
            capabilities=[
                ToolSpec(
                    capability_id="write.file",
                    trust_level=ToolTrustLevel.FILESYSTEM,
                    description=(
                        "Write a file to disk. Use this to persist analysis results, "
                        "save notes, or create markdown files in the knowledge directory. "
                        "`path` is relative to the project root. `content` is the file content (UTF-8). "
                        '`mode` defaults to "overwrite". Use `mode: "append"` to add content '
                        "to the end of an existing file without deleting previous content "
                        "(e.g., for append-only ledgers like 分诊台账.md)."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to project root (e.g., knowledge/00_Inbox/2026-06-15-slug.md)",
                            },
                            "content": {
                                "type": "string",
                                "description": "Content to write to the file (UTF-8 encoded).",
                            },
                            "mode": {
                                "type": "string",
                                "default": "overwrite",
                                "description": 'Write mode: "overwrite" (default) replaces the file; "append" adds to the end.',
                            },
                        },
                        "required": ["path", "content"],
                    },
                ),
            ],
        )

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        if capability_id == "write.file":
            return self._handle_write
        raise KeyError(capability_id)

    def _handle_write(self, request: ToolRequest) -> ToolResult:
        rel_path = str(request.arguments.get("path", "")).strip()
        content = str(request.arguments.get("content", ""))
        mode = str(request.arguments.get("mode", "overwrite")).strip().lower()
        if not rel_path:
            return ToolResult(
                status="error",
                error_code="invalid_path",
                content={"message": "path is required"},
            )
        resolved = (self._cwd / rel_path).resolve()
        if not any(
            str(self._cwd / root) in str(resolved) or str((self._cwd / root).resolve()) in str(resolved)
            for root in WRITE_ALLOWED_ROOTS
        ):
            return ToolResult(
                status="error",
                error_code="path_not_allowed",
                content={
                    "message": f"Write path must be within allowed roots: {WRITE_ALLOWED_ROOTS}. "
                    f"Got: {rel_path}"
                },
            )
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with resolved.open("a", encoding="utf-8") as f:
                    f.write(content)
                action = "appended"
            else:
                resolved.write_text(content, encoding="utf-8")
                action = "written"
            logger.info("File %s path=%s size=%d", action, rel_path, len(content))
        except OSError as exc:
            return ToolResult(
                status="error",
                error_code="write_failed",
                content={"message": str(exc), "path": rel_path},
            )
        return ToolResult(
            status="ok",
            content={
                "path": rel_path,
                "size": len(content),
                "mode": mode,
                "message": f"File {action}: {rel_path}",
            },
        )
