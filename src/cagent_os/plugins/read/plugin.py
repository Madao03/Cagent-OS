from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec, PluginSpec
from cagent_os.config import Settings
from cagent_os.plugins.plugin import Plugin
from cagent_os.plugins.read.document_reader import DocumentReader, docling_available
from cagent_os.shared.logging_utils import build_log_extra, format_log_context

logger = logging.getLogger(__name__)


class ReadPlugin(Plugin):
    def __init__(self, settings: Settings, reader: DocumentReader | None = None) -> None:
        self._settings = settings
        self._reader = reader

    def manifest(self) -> PluginSpec:
        return PluginSpec(
            plugin_id="read",
            default_enabled=True,
            capabilities=[
                ToolSpec(
                    capability_id="docs.read",
                    trust_level=ToolTrustLevel.FILESYSTEM,
                    description="Read a local file from disk (markdown, text, PDF, etc.). Use this to read any file on the local filesystem — skill references, watchlist, existing notes, knowledge base files. DO NOT use web.fetch for local file paths.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "output_format": {"type": "string", "default": "markdown"},
                            "max_chars": {"type": "integer", "default": 20000},
                            "max_pages": {"type": "integer"},
                            "max_file_size_mb": {"type": "integer"},
                        },
                        "required": ["source"],
                    },
                )
            ],
        )

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        if capability_id != "docs.read":
            raise KeyError(capability_id)
        return lambda request: self.execute(request.arguments)

    _TEXT_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".json", ".csv", ".py", ".log", ".xml", ".html", ".css", ".js", ".ts", ".sh", ".toml", ".ini", ".cfg", ".env", ".gitignore", ".mdx"}

    def execute(self, arguments: dict) -> ToolResult:
        if self._reader is None and not docling_available():
            # Fallback: read text files directly without docling
            source = str(arguments.get("source", ""))
            resolved = self._resolve_path(source, arguments)
            if resolved and resolved.suffix.lower() in self._TEXT_EXTENSIONS:
                return self._read_text_fallback(resolved, int(arguments.get("max_chars", 20000)))
            logger.warning(
                "Read capability unavailable %s",
                format_log_context(source=source, reason="docling_not_installed"),
                extra=build_log_extra(source=source, reason="docling_not_installed"),
            )
            return ToolResult(
                status="error",
                error_code="capability_unavailable",
                content={"reason": "docling_not_installed", "arguments": arguments},
            )
        payload = self._get_reader().read(
            workdir=Path(arguments.get("workdir", ".")).resolve(),
            source=str(arguments["source"]),
            output_format=str(arguments.get("output_format", "markdown")),
            max_chars=int(arguments.get("max_chars", 20000)),
            max_pages=self._as_optional_int(arguments.get("max_pages")),
            max_file_size_mb=self._as_optional_int(arguments.get("max_file_size_mb")),
        )
        if "error" in payload:
            logger.warning(
                "Read capability failed %s",
                format_log_context(source=str(arguments.get("source", "")), pipeline=payload.get("pipeline")),
                extra=build_log_extra(source=str(arguments.get("source", "")), pipeline=payload.get("pipeline")),
            )
            return ToolResult(
                status="error",
                error_code="capability_unavailable",
                content=payload,
            )
        return ToolResult(status="ok", content=payload)

    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

    @classmethod
    def _resolve_path(cls, source: str, arguments: dict) -> Path | None:
        """Resolve a source path against multiple base directories."""
        path = Path(source)
        if path.is_absolute():
            return path if path.exists() and path.is_file() else None
        # Try: project root, then CWD, then explicit workdir
        bases = [cls._PROJECT_ROOT, Path.cwd()]
        workdir_arg = arguments.get("workdir")
        if workdir_arg:
            bases.insert(0, Path(workdir_arg))
        for base in bases:
            candidate = (base / path).resolve()
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _read_text_fallback(path: Path, max_chars: int) -> ToolResult:
        try:
            text = path.read_text(encoding="utf-8")
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n... [truncated at {max_chars} chars]"
            logger.info("Text file read via fallback path=%s size=%d", str(path), len(text))
            return ToolResult(status="ok", content=text)
        except Exception as exc:
            return ToolResult(
                status="error",
                error_code="read_failed",
                content={"message": str(exc), "path": str(path)},
            )

    def _get_reader(self) -> DocumentReader:
        if self._reader is None:
            self._reader = DocumentReader(settings=self._settings)
        return self._reader

    @staticmethod
    def _as_optional_int(value) -> int | None:
        if value is None:
            return None
        return int(value)
