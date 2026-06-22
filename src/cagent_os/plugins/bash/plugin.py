from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec, PluginSpec
from cagent_os.config import Settings
from cagent_os.plugins.bash.runtime import BashRuntime, DEFAULT_TIMEOUT_MS
from cagent_os.plugins.plugin import Plugin


class PublishedFileRegistry:
    """In-memory registry for published files (lightweight, stage 0)."""

    def __init__(self, *, download_path_prefix: str = "/api/v1/files") -> None:
        self._download_path_prefix = download_path_prefix.rstrip("/")
        self._entries: dict[str, dict[str, object]] = {}

    def register(self, *, path: Path, owner_user_id: str) -> dict[str, object]:
        from uuid import uuid4

        resolved = path.resolve()
        file_id = uuid4().hex
        entry = {
            "id": file_id,
            "name": resolved.name,
            "size_bytes": resolved.stat().st_size,
            "download_url": f"{self._download_path_prefix}/{file_id}",
        }
        self._entries[file_id] = entry
        return entry

    def get(self, file_id: str) -> dict[str, object]:
        return self._entries[file_id]


class BashPlugin(Plugin):
    def __init__(
        self,
        settings: Settings,
        *,
        runtime: BashRuntime | None = None,
        allowed_roots: list[str] | None = None,
        published_file_registry: PublishedFileRegistry | None = None,
    ) -> None:
        self._settings = settings
        roots = allowed_roots or [str(Path.cwd()), "/tmp"]
        self._allowed_roots = [Path(root).resolve() for root in roots]
        self.runtime = runtime or BashRuntime(allowed_roots=roots)
        self._published_file_registry = published_file_registry or PublishedFileRegistry()

    def manifest(self) -> PluginSpec:
        return PluginSpec(
            plugin_id="bash",
            default_enabled=True,
            capabilities=[
                ToolSpec(
                    capability_id="bash",
                    trust_level=ToolTrustLevel.PRIVILEGED,
                    description=(
                        "Run a bash shell command and return structured stdout/stderr/exit-code output. "
                        "`command` is required. `workdir`, `timeout_ms`, and `stdin` are optional."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Required. The shell command to execute with `/bin/bash -lc`.",
                            },
                            "workdir": {
                                "type": "string",
                                "default": str(Path.cwd()),
                                "description": (
                                    "Optional. Working directory for the command. "
                                    "Must stay within the allowed workspace roots."
                                ),
                            },
                            "timeout_ms": {
                                "type": "integer",
                                "default": DEFAULT_TIMEOUT_MS,
                                "description": "Optional. Timeout in milliseconds before the command is aborted.",
                            },
                            "stdin": {
                                "type": "string",
                                "description": "Optional. Text sent to the command's stdin.",
                            },
                        },
                        "required": ["command"],
                    },
                ),
                ToolSpec(
                    capability_id="publish_file",
                    trust_level=ToolTrustLevel.FILESYSTEM,
                    description="Register a generated file for download and return its download URL.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the file to publish, relative to the workspace root.",
                            }
                        },
                        "required": ["path"],
                    },
                ),
            ],
        )

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        if capability_id == "bash":
            return self._handle_exec
        if capability_id == "publish_file":
            return self._handle_publish_file
        raise KeyError(capability_id)

    def _handle_exec(self, request: ToolRequest) -> ToolResult:
        result = self.runtime.execute(
            command=str(request.arguments.get("command", "")),
            workdir=str(request.arguments.get("workdir", Path.cwd())),
            timeout_ms=int(request.arguments.get("timeout_ms", DEFAULT_TIMEOUT_MS)),
            stdin=str(request.arguments["stdin"]) if request.arguments.get("stdin") is not None else None,
        )
        if bool(result.get("timed_out")):
            return ToolResult(
                status="error",
                error_code="bash_timeout",
                content={**result, "message": "Bash command timed out."},
            )
        if int(result.get("code", 0)) != 0:
            return ToolResult(
                status="error",
                error_code="bash_nonzero_exit",
                content={**result, "message": f"Bash command exited with code {int(result.get('code', 0))}."},
            )
        return ToolResult(status="ok", content=result)

    def _handle_publish_file(self, request: ToolRequest) -> ToolResult:
        raw_path = str(request.arguments.get("path", "")).strip()
        try:
            file_path = self._resolve_publish_path(raw_path)
        except ValueError as exc:
            return ToolResult(
                status="error",
                error_code="invalid_file_path",
                content={"status": "error", "message": str(exc)},
            )
        owner_user_id = str(request.context.get("user_id", "")).strip()
        file_meta = self._published_file_registry.register(path=file_path, owner_user_id=owner_user_id)
        return ToolResult(
            status="ok",
            content={
                "status": "ok",
                "file": file_meta,
            },
        )

    def _resolve_publish_path(self, path: str) -> Path:
        if not path:
            raise ValueError("path is required")
        candidate = Path(path)
        resolved = (Path.cwd() / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if not any(root == resolved or root in resolved.parents for root in self._allowed_roots):
            raise ValueError("path must stay within the allowed workspace roots")
        if not resolved.exists():
            raise ValueError(f"file not found: {path}")
        if not resolved.is_file():
            raise ValueError(f"path is not a file: {path}")
        return resolved
