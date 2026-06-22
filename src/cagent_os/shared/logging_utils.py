from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_LOG_DIR = Path("logs")
_LOG_FILE = _LOG_DIR / "cagentos.log"
_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_LOG_BACKUP_COUNT = 5               # keep last 5 rotated files


def configure_logging(*, debug: bool, log_file: str | Path | None = None) -> None:
    level = logging.DEBUG if debug else logging.INFO
    root_logger = logging.getLogger()
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (always)
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        console.setLevel(level)
        root_logger.addHandler(console)

    # File handler (persistent, tail-able from another terminal)
    log_path = Path(log_file) if log_file else _LOG_FILE
    log_path = log_path.resolve()
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG)  # file always at DEBUG for troubleshooting
        root_logger.addHandler(file_handler)
    except OSError:
        pass  # file logging is best-effort; console always works

    root_logger.setLevel(level)


def build_log_extra(**kwargs: Any) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if value is not None}


def format_log_context(**kwargs: Any) -> str:
    parts: list[str] = []
    for key, value in kwargs.items():
        if value is None:
            continue
        parts.append(f"{key}={_serialize_log_value(value)}")
    return " ".join(parts)


def summarize_text(value: str, *, limit: int = 120) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def summarize_command(value: str, *, limit: int = 120) -> str:
    return summarize_text(value, limit=limit)


def _serialize_log_value(value: Any) -> str:
    if isinstance(value, str):
        return summarize_text(value, limit=160)
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return summarize_text(json.dumps(value, ensure_ascii=False, sort_keys=True), limit=160)
    except TypeError:
        return summarize_text(repr(value), limit=160)
