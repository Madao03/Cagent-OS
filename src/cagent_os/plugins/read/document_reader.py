from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

from cagent_os.config import Settings
from cagent_os.shared.logging_utils import build_log_extra, format_log_context

logger = logging.getLogger(__name__)


def docling_available() -> bool:
    return importlib.util.find_spec("docling") is not None


class DocumentReader:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def read(
        self,
        *,
        workdir: Path,
        source: str,
        output_format: str = "markdown",
        max_chars: int = 20000,
        max_pages: int | None = None,
        max_file_size_mb: int | None = None,
    ) -> dict[str, Any]:
        resolved_source = self._resolve_source(workdir, source)

        if not docling_available():
            return {
                "error": "Docling is not installed.",
                "hint": "Install with: pip install docling",
                "source": source,
                "resolved_source": resolved_source,
            }

        try:
            from docling.document_converter import DocumentConverter

            converter = DocumentConverter()
            kwargs: dict[str, Any] = {}
            if max_pages is not None:
                kwargs["max_num_pages"] = max_pages
            if max_file_size_mb is not None:
                kwargs["max_file_size"] = max_file_size_mb * 1024 * 1024

            conversion = converter.convert(resolved_source, **kwargs)
            document = conversion.document

            if output_format == "markdown":
                content = document.export_to_markdown()
            elif output_format == "text":
                content = document.export_to_text()
            elif output_format == "html":
                content = document.export_to_html()
            elif output_format == "json":
                content = json.dumps(document.export_to_dict(), ensure_ascii=False)
            else:
                raise ValueError(f"unsupported output_format: {output_format}")

            truncated = len(content) > max_chars
            return {
                "source": source,
                "resolved_source": resolved_source,
                "output_format": output_format,
                "pipeline": "docling",
                "content": content[:max_chars],
                "truncated": truncated,
            }
        except Exception as exc:
            logger.warning(
                "Document read failed %s",
                format_log_context(source=source, resolved_source=resolved_source),
                extra=build_log_extra(source=source, resolved_source=resolved_source),
                exc_info=True,
            )
            return {
                "error": str(exc),
                "source": source,
                "resolved_source": resolved_source,
            }

    @staticmethod
    def _resolve_source(workdir: Path, source: str) -> str:
        if source.startswith(("http://", "https://")):
            return source
        path = Path(source)
        if not path.is_absolute():
            path = (workdir / source).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(source)
        return str(path)
