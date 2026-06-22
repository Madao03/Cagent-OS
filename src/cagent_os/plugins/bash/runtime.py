from __future__ import annotations

import logging
from pathlib import Path
import subprocess

from cagent_os.shared.errors import ToolAccessDenied
from cagent_os.shared.logging_utils import build_log_extra, format_log_context, summarize_command

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 120_000
MAX_TIMEOUT_MS = 600_000
DEFAULT_MAX_OUTPUT_CHARS = 30_000


class BashRuntime:
    def __init__(
        self,
        *,
        allowed_roots: list[str | Path],
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        self._allowed_roots = [Path(root).resolve() for root in allowed_roots]
        self._max_output_chars = max_output_chars

    def execute(
        self,
        *,
        command: str,
        workdir: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        stdin: str | None = None,
    ) -> dict[str, object]:
        normalized_command = str(command or "").strip()
        if not normalized_command:
            logger.warning("Bash command rejected because it is empty")
            raise ToolAccessDenied("Empty command is not allowed.")

        resolved_workdir = Path(workdir).resolve()
        if not any(root == resolved_workdir or root in resolved_workdir.parents for root in self._allowed_roots):
            logger.warning(
                "Bash command rejected because workdir is not allowed %s",
                format_log_context(workdir=str(resolved_workdir)),
                extra=build_log_extra(workdir=str(resolved_workdir)),
            )
            raise ToolAccessDenied("Working directory is not allowed.")

        normalized_timeout_ms = max(1, min(int(timeout_ms), MAX_TIMEOUT_MS))
        try:
            result = subprocess.run(
                ["/bin/bash", "-lc", f"set -o pipefail\n{normalized_command}"],
                cwd=resolved_workdir,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=normalized_timeout_ms / 1000,
                stdin=None if stdin is not None else subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "").strip()
            stderr = (exc.stderr or "").strip()
            stdout, stderr, truncated = self._truncate_output(stdout, stderr)
            logger.warning(
                "Bash command timed out %s",
                format_log_context(
                    workdir=str(resolved_workdir),
                    timeout_ms=normalized_timeout_ms,
                    command=summarize_command(normalized_command),
                ),
                extra=build_log_extra(
                    workdir=str(resolved_workdir),
                    timeout_ms=normalized_timeout_ms,
                    command_summary=summarize_command(normalized_command),
                ),
            )
            return {
                "stdout": stdout,
                "stderr": stderr,
                "code": 143,
                "timed_out": True,
                "truncated": truncated,
            }

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        stdout, stderr, truncated = self._truncate_output(stdout, stderr)
        logger.log(
            logging.INFO if result.returncode == 0 else logging.WARNING,
            "Bash command finished %s",
            format_log_context(
                workdir=str(resolved_workdir),
                code=int(result.returncode),
                timed_out=False,
                truncated=truncated,
                command=summarize_command(normalized_command),
            ),
            extra=build_log_extra(
                workdir=str(resolved_workdir),
                code=int(result.returncode),
                timed_out=False,
                truncated=truncated,
                command_summary=summarize_command(normalized_command),
            ),
        )
        return {
            "stdout": stdout,
            "stderr": stderr,
            "code": int(result.returncode),
            "timed_out": False,
            "truncated": truncated,
        }

    def _truncate_output(self, stdout: str, stderr: str) -> tuple[str, str, bool]:
        total = len(stdout) + len(stderr)
        if total <= self._max_output_chars:
            return stdout, stderr, False
        remaining = self._max_output_chars
        truncated_stdout = stdout[:remaining]
        remaining = max(0, remaining - len(truncated_stdout))
        truncated_stderr = stderr[:remaining]
        return truncated_stdout, truncated_stderr, True
