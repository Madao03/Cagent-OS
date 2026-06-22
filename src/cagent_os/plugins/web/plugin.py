from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec, PluginSpec
from cagent_os.config import Settings
from cagent_os.plugins.plugin import Plugin
from cagent_os.plugins.web.fetcher import WebFetcher

logger = logging.getLogger(__name__)

# -- Playwright fetch_weixin.py paths (in WSL) ---------------------------
# Configurable via environment variables; defaults work for local dev.
_WSL_PYTHON = os.environ.get("CAGENTOS_WSL_PYTHON", "/tmp/pw_venv/bin/python3")
_FETCH_WEIXIN_SCRIPT = os.environ.get("CAGENTOS_WSL_FETCH_SCRIPT", "/tmp/scripts/fetch_weixin.py")

# -- Project root (for resolving save paths) -----------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_KNOWLEDGE_INBOX = _PROJECT_ROOT / "knowledge" / "00_Inbox"


class WebPlugin(Plugin):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.fetcher = WebFetcher(settings=settings)

    def manifest(self) -> PluginSpec:
        return PluginSpec(
            plugin_id="web",
            capabilities=[
                ToolSpec(
                    capability_id="web.fetch",
                    trust_level=ToolTrustLevel.NETWORKED,
                    description="Fetch a specific public web URL.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                        },
                        "required": ["url"],
                    },
                ),
                ToolSpec(
                    capability_id="web.fetch_weixin",
                    trust_level=ToolTrustLevel.NETWORKED,
                    description=(
                        "Fetch a WeChat Official Account (微信公众号) article via Playwright headless browser. "
                        "Use this for mp.weixin.qq.com URLs — it launches a real Chromium browser in WSL "
                        "to bypass WeChat's anti-scraping protection. Images are downloaded locally into "
                        "knowledge/00_Inbox/<slug>/images/ and referenced with local relative paths — "
                        "Obsidian can render them directly. Returns markdown with YAML frontmatter "
                        "and metadata (saved_dir, article_path, image_count)."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "WeChat Official Account article URL (mp.weixin.qq.com)",
                            },
                        },
                        "required": ["url"],
                    },
                ),
            ],
        )

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        if capability_id == "web.fetch":
            return self._handle_fetch
        if capability_id == "web.fetch_weixin":
            return self._handle_fetch_weixin
        raise KeyError(capability_id)

    def _handle_fetch(self, request: ToolRequest) -> ToolResult:
        url = str(request.arguments.get("url", ""))
        try:
            content = self.fetcher.fetch(url)
        except Exception as exc:
            return ToolResult(
                status="error",
                error_code="web_fetch_failed",
                content={
                    "url": url,
                    "message": str(exc) or type(exc).__name__,
                },
            )
        return ToolResult(status="ok", content=content)

    def _handle_fetch_weixin(self, request: ToolRequest) -> ToolResult:
        url = str(request.arguments.get("url", "")).strip()
        if not url:
            return ToolResult(
                status="error",
                error_code="invalid_url",
                content={"message": "url is required"},
            )
        # Verify WSL is available
        try:
            check = subprocess.run(
                ["wsl", "--", "echo", "ok"],
                capture_output=True, text=True, encoding="utf-8", timeout=5,
            )
            if check.returncode != 0 or "ok" not in check.stdout:
                return ToolResult(
                    status="error",
                    error_code="wsl_unavailable",
                    content={
                        "message": "WSL is not available. web.fetch_weixin requires WSL to run Playwright.",
                        "fallback": "Try web.fetch — it may get partial content or search for mirrors.",
                    },
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ToolResult(
                status="error",
                error_code="wsl_unavailable",
                content={
                    "message": "WSL is not available or not responding.",
                    "fallback": "Try web.fetch or financial.websearch to find article mirrors.",
                },
            )
        # Fetch to WSL /tmp/ first (no Chinese chars → no subprocess encoding issues).
        # After fetching, extract article title to build a human-readable directory name,
        # then copy everything from WSL temp to the Obsidian vault.
        url_hash = _slug_from_url(url)
        wsl_tmp = f"/tmp/weixin_{url_hash}"
        cmd = [
            "wsl", "--",
            _WSL_PYTHON, _FETCH_WEIXIN_SCRIPT, url,
            "--save-dir", wsl_tmp,
        ]
        # Retry: Playwright/Chromium startup failures are often transient
        # (exit code 1 = browser failed to launch). One retry after cleanup.
        result = None
        last_stderr = ""
        for attempt in (1, 2):
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", timeout=60,
                )
            except subprocess.TimeoutExpired:
                _wsl_kill(f"weixin_{url_hash}")
                subprocess.run(
                    ["wsl", "--", "rm", "-rf", wsl_tmp],
                    capture_output=True, text=True, encoding="utf-8", timeout=10,
                )
                return ToolResult(
                    status="error",
                    error_code="weixin_fetch_timeout",
                    content={
                        "url": url,
                        "message": "Playwright fetch timed out after 60s.",
                        "fallback": "Try web.fetch, or financial.websearch to find mirrors.",
                    },
                )
            if result.returncode == 0:
                break
            last_stderr = result.stderr.strip()[:500] if result.stderr else ""
            if attempt == 1:
                logger.warning(
                    "fetch_weixin.py attempt %d failed url=%s stderr=%s — retrying after cleanup",
                    attempt, url[:80], last_stderr,
                )
                _wsl_kill(f"weixin_{url_hash}")
                import time as _time
                _time.sleep(2)

        if result is None or result.returncode != 0:
            logger.warning("fetch_weixin.py failed after retries url=%s stderr=%s", url[:80], last_stderr)
            return ToolResult(
                status="error",
                error_code="weixin_fetch_failed",
                content={
                    "url": url,
                    "message": f"Playwright fetch failed (exit {result.returncode if result else 'timeout'}).",
                    "stderr": last_stderr,
                    "fallback": "Try web.fetch, or financial.websearch to find mirrors.",
                },
            )
        content = result.stdout
        if not content or len(content) < 100:
            return ToolResult(
                status="error",
                error_code="weixin_fetch_empty",
                content={
                    "url": url,
                    "message": "Playwright returned empty or very short content.",
                    "fallback": "Try financial.websearch to find mirrors or cached copies.",
                },
            )
        # Extract title from YAML frontmatter for readable directory name
        title_match = re.search(r'title:\s*"(.+?)"', content)
        article_title = title_match.group(1) if title_match else ""
        date_prefix = datetime.date.today().strftime("%Y-%m-%d")
        dir_name = _dir_name_from_title(date_prefix, article_title, url_hash)
        save_dir_win = _KNOWLEDGE_INBOX / dir_name
        save_dir_win.mkdir(parents=True, exist_ok=True)

        # Copy files from WSL /tmp/ to Windows knowledge/ vault
        win_target = _win_to_wsl_path(save_dir_win)
        _cp = subprocess.run(
            ["wsl", "--", "cp", "-r", f"{wsl_tmp}/.", win_target + "/"],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        if _cp.returncode != 0:
            logger.warning("WSL cp failed: %s", _cp.stderr[:200])
        subprocess.run(
            ["wsl", "--", "rm", "-rf", wsl_tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )

        # Count saved images
        images_dir = save_dir_win / "images"
        image_count = len(list(images_dir.glob("*"))) if images_dir.exists() else 0

        logger.info(
            "WeChat article saved url=%s size=%d images=%d dir=%s",
            url[:80], len(content), image_count, str(save_dir_win),
        )
        return ToolResult(
            status="ok",
            content={
                "markdown": content,
                "saved_dir": str(save_dir_win),
                "article_path": str(save_dir_win / "article.md"),
                "image_count": image_count,
                "message": f"Saved with {image_count} images to {dir_name}/",
            },
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _slug_from_url(url: str) -> str:
    """Generate a short filesystem-safe slug from a URL."""
    # Use URL hash for uniqueness
    hash_hex = hashlib.md5(url.encode()).hexdigest()[:8]
    # Try to extract a readable portion from the URL path
    path_match = re.search(r"/([^/]{4,40})$", url.rstrip("/"))
    if path_match:
        raw = path_match.group(1)
        raw = re.sub(r"[^\w一-鿿-]", "_", raw).strip("_")[:30]
    else:
        raw = ""
    return f"{raw}_{hash_hex}" if raw else hash_hex


def _dir_name_from_title(date_prefix: str, title: str, fallback_hash: str) -> str:
    """Generate a clean directory name from article title.

    Example: "万字科普：美联储观察入门指南" → "2026-06-16-美联储观察入门指南"
    Falls back to URL hash if title is empty or unparseable.
    """
    if not title:
        return f"{date_prefix}-{fallback_hash}"
    # Remove special chars, keep Chinese/English/numbers/spaces/hyphens
    cleaned = re.sub(r"[^\w\s一-鿿-]", "", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Truncate to reasonable length
    if len(cleaned) > 50:
        cleaned = cleaned[:50]
    if not cleaned:
        return f"{date_prefix}-{fallback_hash}"
    return f"{date_prefix}-{cleaned}"


def _wsl_kill(pattern: str) -> None:
    """Force-kill processes matching a pattern inside WSL."""
    try:
        subprocess.run(
            ["wsl", "--", "pkill", "-f", pattern],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except Exception:
        pass  # best-effort cleanup


def _win_to_wsl_path(win_path: Path) -> str:
    """Convert a Windows path to WSL /mnt/... format."""
    drive = win_path.drive[0].lower()
    rest = str(win_path)[2:].replace("\\", "/")
    return f"/mnt/{drive}{rest}"
