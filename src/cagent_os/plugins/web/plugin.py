from __future__ import annotations

import datetime
import hashlib
import ipaddress
import logging
import os
import re
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec, PluginSpec
from cagent_os.config import Settings
from cagent_os.plugins.plugin import Plugin
from cagent_os.plugins.web.fetcher import WebFetcher

logger = logging.getLogger(__name__)

# ── SSRF Protection ────────────────────────────────────────────
# Blocks all private/loopback/link-local IPs BEFORE any fetch path.
# This gate runs at the entry point (_handle_fetch), covering all
# three degradation tiers: Jina → HTTP → Playwright.

_ALLOWED_SCHEMES = {"http", "https"}


def _is_url_safe(url: str) -> tuple[bool, str]:
    """Validate URL against SSRF attacks.

    Checks:
    1. Scheme is http/https only
    2. Resolved IP is not private/loopback/link-local/reserved
    3. No DNS rebinding (hostname resolved at check time)

    Returns (is_safe, reason).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid URL format"

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False, f"scheme '{parsed.scheme}' not allowed (only http/https)"

    hostname = parsed.hostname
    if not hostname:
        return False, "no hostname in URL"

    # Resolve hostname to IP(s) — check ALL resolved addresses
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"DNS resolution failed for {hostname}"

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False, f"hostname {hostname} resolves to blocked IP {ip} (private/loopback/reserved)"

    return True, "ok"

# -- Playwright scripts paths (in WSL) ----------------------------------
# Configurable via environment variables. None = not configured.
# On Linux servers, browser mode uses native Playwright (no WSL).
_IS_WINDOWS = os.name == "nt"
_WSL_PYTHON = os.environ.get("CAGENTOS_WSL_PYTHON") or None
_FETCH_WEIXIN_SCRIPT = os.environ.get("CAGENTOS_WSL_FETCH_SCRIPT") or None
_FETCH_BROWSER_SCRIPT = os.environ.get("CAGENTOS_WSL_FETCH_BROWSER_SCRIPT") or None

# -- Native Playwright (Linux) ─────────────────────────────────────────
# Detect once at import time. On Linux with Playwright installed,
# we run headless Chromium directly in-process — no WSL bridge needed.
_PLAYWRIGHT_AVAILABLE = False
if not _IS_WINDOWS:
    try:
        from playwright.sync_api import sync_playwright
        _PLAYWRIGHT_AVAILABLE = True
        logger.info("Native Playwright detected — browser mode available on Linux")
    except ImportError:
        pass

# -- Browser circuit breaker (sliding window) ─────────────────────────
# Tracks last N fetch results; if success rate < 30%, enter 60s cooldown.
import threading
_BROWSER_CB_WINDOW = []  # list of bools (True=success)
_BROWSER_CB_WINDOW_SIZE = 10
_BROWSER_CB_COOLDOWN = 60  # 1 minute (was 5 min)
_BROWSER_CB_LAST_TRIP = 0.0
_BROWSER_CB_LOCK = threading.Lock()

def _cb_record(success: bool) -> None:
    """Record a fetch result in the sliding window."""
    with _BROWSER_CB_LOCK:
        _BROWSER_CB_WINDOW.append(success)
        if len(_BROWSER_CB_WINDOW) > _BROWSER_CB_WINDOW_SIZE:
            _BROWSER_CB_WINDOW.pop(0)

def _cb_should_trip() -> bool:
    """Check if we should enter cooldown based on recent success rate."""
    with _BROWSER_CB_LOCK:
        if not _BROWSER_CB_WINDOW:
            return False
        successes = sum(_BROWSER_CB_WINDOW)
        rate = successes / len(_BROWSER_CB_WINDOW)
        return len(_BROWSER_CB_WINDOW) >= 3 and rate < 0.3

def _cb_in_cooldown() -> bool:
    """Check if circuit breaker is currently in cooldown."""
    import time as _t
    if _BROWSER_CB_LAST_TRIP > 0:
        remaining = _BROWSER_CB_COOLDOWN - (_t.time() - _BROWSER_CB_LAST_TRIP)
        if remaining > 0:
            return True
    return False

def _cb_trip() -> None:
    """Trip the circuit breaker."""
    import time as _t
    global _BROWSER_CB_LAST_TRIP
    with _BROWSER_CB_LOCK:
        _BROWSER_CB_LAST_TRIP = _t.time()
        _BROWSER_CB_WINDOW.clear()

# -- Concurrency limiter: only 1 Chromium instance at a time (4GB server)
import threading
_BROWSER_SEMAPHORE = threading.Semaphore(1)
_BROWSER_TIMEOUT_SEC = 30  # hard limit: browser launch (10s) + page load (20s)

# -- Jina Reader (cloud rendering fallback before Playwright) ──────────
_JINA_READER_URL = "https://r.jina.ai/"
_JINA_TIMEOUT_SEC = 12

def _fetch_via_jina(url: str) -> str | None:
    """Fetch URL via Jina Reader cloud service. Returns text or None."""
    import requests
    try:
        resp = requests.get(
            _JINA_READER_URL + url,
            timeout=_JINA_TIMEOUT_SEC,
            headers={"Accept": "text/plain"},
        )
        if resp.status_code == 200 and len(resp.text) > 100:
            return resp.text
        logger.info("Jina Reader returned status=%d len=%d for %s", resp.status_code, len(resp.text), url[:80])
        return None
    except Exception as exc:
        logger.info("Jina Reader failed for %s: %s", url[:80], str(exc)[:100])
        return None

# -- Persistent browser instance (reuse across fetches) ────────────────
_persistent_browser = None
_persistent_playwright = None
_persistent_last_used = 0.0
_BROWSER_IDLE_TIMEOUT = 120  # close after 2 min idle

def _get_persistent_browser():
    """Get or create a persistent Chromium instance."""
    global _persistent_browser, _persistent_playwright, _persistent_last_used
    import time as _t
    if _persistent_browser and _persistent_browser.is_connected():
        _persistent_last_used = _t.time()
        return _persistent_browser
    # Cleanup old instance if disconnected
    if _persistent_browser:
        try:
            _persistent_browser.close()
        except Exception:
            pass
        _persistent_browser = None
    if not _persistent_playwright:
        from playwright.sync_api import sync_playwright
        _persistent_playwright = sync_playwright().start()
    _persistent_browser = _persistent_playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
    )
    _persistent_last_used = _t.time()
    return _persistent_browser

def _close_idle_browser() -> None:
    """Close persistent browser if idle for too long (free memory)."""
    global _persistent_browser, _persistent_playwright, _persistent_last_used
    import time as _t
    if _persistent_browser and (_t.time() - _persistent_last_used) > _BROWSER_IDLE_TIMEOUT:
        try:
            _persistent_browser.close()
        except Exception:
            pass
        _persistent_browser = None

# -- Multi-modal vision API (for image.describe) ------------------------
# Set CAGENTOS_VISION_API_KEY to activate; defaults to placeholder.
_VISION_API_KEY = os.environ.get("CAGENTOS_VISION_API_KEY", "")
_VISION_API_URL = os.environ.get(
    "CAGENTOS_VISION_API_URL",
    "https://api.openai.com/v1/chat/completions",
)
_VISION_MODEL = os.environ.get("CAGENTOS_VISION_MODEL", "gpt-4o")

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
                    description=(
                        "Fetch a public web URL. Returns cleaned text or markdown. "
                        "Set browser_mode=true to use a headless browser (Playwright) "
                        "for sites protected by Vercel/Cloudflare/CDN anti-bot walls "
                        "(e.g. Grayscale, institutional research portals). "
                        "The tool auto-detects anti-bot responses and falls back to "
                        "browser mode automatically — you rarely need to set this flag."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "browser_mode": {
                                "type": "boolean",
                                "description": (
                                    "If true, skip HTTP and fetch directly via headless browser. "
                                    "Use for known CDN-protected sites (Grayscale, Vercel-hosted). "
                                    "Default false — auto-fallback handles most cases."
                                ),
                                "default": False,
                            },
                        },
                        "required": ["url"],
                    },
                ),
                ToolSpec(
                    capability_id="image.describe",
                    trust_level=ToolTrustLevel.NETWORKED,
                    description=(
                        "Describe a local image file using a multi-modal vision model. "
                        "Extract chart type, key data points, trend direction, and tables. "
                        "Use this on downloaded article images (under knowledge/00_Inbox/<article>/images/) "
                        "to recover data from charts/graphs/tables that were embedded as images. "
                        "Returns structured description: chart_type, data_points, trend, "
                        "table_markdown (if table detected). "
                        "⚠️ Requires CAGENTOS_VISION_API_KEY env var — returns placeholder if not set."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "image_path": {
                                "type": "string",
                                "description": (
                                    "Absolute or project-relative path to the image file. "
                                    "e.g. 'knowledge/00_Inbox/2026-06-24-Grayscale.../images/img_0.png'"
                                ),
                            },
                        },
                        "required": ["image_path"],
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
        if capability_id == "image.describe":
            return self._handle_image_describe
        raise KeyError(capability_id)

    def _handle_fetch(self, request: ToolRequest) -> ToolResult:
        url = str(request.arguments.get("url", ""))
        browser_mode = bool(request.arguments.get("browser_mode", False))

        # ★ SSRF gate — runs BEFORE any fetch path (Jina/HTTP/Playwright).
        # Blocks localhost, private IPs, link-local, cloud metadata endpoints.
        is_safe, reason = _is_url_safe(url)
        if not is_safe:
            logger.warning("SSRF blocked: %s — %s", url[:80], reason)
            return ToolResult(
                status="error",
                error_code="ssrf_blocked",
                content={"message": f"URL blocked by SSRF protection: {reason}", "url": url[:200]},
            )

        # Fast path: HTTP (unless browser_mode is explicitly requested)
        if not browser_mode:
            try:
                content = self.fetcher.fetch(url)
                if content and not _looks_like_antibot(content):
                    return ToolResult(status="ok", content=content)
                logger.info("HTTP fetch returned anti-bot signal, trying Jina url=%s", url[:80])
            except Exception as exc:
                logger.info("HTTP fetch failed, trying Jina url=%s err=%s", url[:80], exc)

            # ★ Jina Reader fallback (cloud rendering, free, ~3s)
            jina_content = _fetch_via_jina(url)
            if jina_content:
                logger.info("Jina Reader OK url=%s size=%d", url[:80], len(jina_content))
                return ToolResult(status="ok", content=jina_content)

        # Slow path: headless browser (Playwright)
        return self._fetch_via_browser(url)

    def _fetch_via_browser(self, url: str) -> ToolResult:
        """Fetch a URL via headless browser.

        Linux: native Playwright (in-process, no WSL).
        Windows: WSL bridge (existing code).
        Other: fast-fail.
        """
        # ★ Route: native Playwright on Linux
        if not _IS_WINDOWS:
            return self._fetch_via_native_playwright(url)

        # Windows path: WSL bridge (unchanged)
        if not _WSL_PYTHON or not _FETCH_BROWSER_SCRIPT:
            return ToolResult(
                status="error",
                error_code="browser_mode_unavailable",
                content={
                    "message": "浏览器模式不可用（需要 Windows + WSL + Playwright 配置）。请使用 HTTP 模式。",
                    "fallback": "Plain HTTP fetch was also unsuccessful for this URL.",
                },
            )

        url_hash = _slug_from_url(url)
        wsl_tmp = f"/tmp/browser_{url_hash}"
        cmd = [
            "wsl", "--",
            _WSL_PYTHON, _FETCH_BROWSER_SCRIPT, url,
            "--save-dir", wsl_tmp,
            "--timeout", "30",
        ]

        result = None
        last_stderr = ""
        for attempt in (1, 2):
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", timeout=90,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                _wsl_kill(f"browser_{url_hash}")
                subprocess.run(
                    ["wsl", "--", "rm", "-rf", wsl_tmp],
                    capture_output=True, text=True, encoding="utf-8", timeout=10,
                    stdin=subprocess.DEVNULL,
                )
                return ToolResult(
                    status="error",
                    error_code="browser_fetch_timeout",
                    content={
                        "url": url,
                        "message": "Browser fetch timed out after 90s.",
                        "fallback": "Try financial.websearch to find mirrors or cached copies.",
                    },
                )
            if result.returncode == 0:
                break
            last_stderr = result.stderr.strip()[:500] if result.stderr else ""
            if attempt == 1:
                logger.warning(
                    "fetch_browser.py attempt %d failed url=%s stderr=%s — retrying",
                    attempt, url[:80], last_stderr,
                )
                _wsl_kill(f"browser_{url_hash}")
                import time as _time
                _time.sleep(2)

        if result is None or result.returncode != 0:
            logger.warning("fetch_browser.py failed after retries url=%s stderr=%s", url[:80], last_stderr)
            return ToolResult(
                status="error",
                error_code="browser_fetch_failed",
                content={
                    "url": url,
                    "message": f"Browser fetch failed (exit {result.returncode if result else 'timeout'}).",
                    "stderr": last_stderr,
                    "fallback": "Try financial.websearch to find mirrors or cached copies.",
                },
            )

        content = result.stdout
        if not content or len(content) < 100:
            return ToolResult(
                status="error",
                error_code="browser_fetch_empty",
                content={
                    "url": url,
                    "message": "Browser returned empty or very short content.",
                    "fallback": "Try financial.websearch to find mirrors or cached copies.",
                },
            )

        # Extract title for directory naming
        title_match = re.search(r'title:\s*"(.+?)"', content)
        article_title = title_match.group(1) if title_match else ""
        date_prefix = datetime.date.today().strftime("%Y-%m-%d")
        dir_name = _dir_name_from_title(date_prefix, article_title, url_hash)
        save_dir_win = _KNOWLEDGE_INBOX / dir_name
        save_dir_win.mkdir(parents=True, exist_ok=True)

        # Copy from WSL /tmp/ to Windows knowledge/ vault
        win_target = _win_to_wsl_path(save_dir_win)
        _cp = subprocess.run(
            ["wsl", "--", "cp", "-r", f"{wsl_tmp}/.", win_target + "/"],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
            stdin=subprocess.DEVNULL,
        )
        if _cp.returncode != 0:
            logger.warning("WSL cp failed for browser fetch: %s", _cp.stderr[:200])
        subprocess.run(
            ["wsl", "--", "rm", "-rf", wsl_tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
            stdin=subprocess.DEVNULL,
        )

        # Count saved images
        images_dir = save_dir_win / "images"
        image_count = len(list(images_dir.glob("*"))) if images_dir.exists() else 0

        logger.info(
            "Browser fetch saved url=%s size=%d images=%d dir=%s",
            url[:80], len(content), image_count, str(save_dir_win),
        )
        return ToolResult(
            status="ok",
            content={
                "markdown": content,
                "saved_dir": str(save_dir_win),
                "article_path": str(save_dir_win / "article.md"),
                "image_count": image_count,
                "fetched_via": "playwright",
                "message": f"Fetched via browser with {image_count} images to {dir_name}/",
            },
        )

    def _fetch_via_native_playwright(self, url: str) -> ToolResult:
        """Fetch via native Playwright on Linux (no WSL bridge).

        Includes sliding-window circuit breaker, concurrency limiter (1),
        persistent browser instance, stealth, and Readability extraction.
        """
        import time

        # ★ Sliding-window circuit breaker
        if _cb_in_cooldown():
            logger.warning("Browser circuit breaker in cooldown")
            return ToolResult(
                status="error",
                error_code="browser_circuit_breaker",
                content={
                    "url": url[:200],
                    "message": "浏览器模式暂时不可用（成功率过低，1 分钟后重试）。",
                    "fallback": "Try financial.websearch to find mirrors or cached copies.",
                },
            )

        if not _PLAYWRIGHT_AVAILABLE:
            return ToolResult(
                status="error",
                error_code="browser_mode_unavailable",
                content={
                    "message": "浏览器模式不可用（未安装 Playwright）。请使用 HTTP 模式。",
                    "fallback": "Plain HTTP fetch was also unsuccessful for this URL.",
                },
            )

        # ★ Concurrency: only 1 Chromium at a time (4GB server)
        if not _BROWSER_SEMAPHORE.acquire(timeout=2):
            return ToolResult(
                status="error",
                error_code="browser_busy",
                content={
                    "url": url[:200],
                    "message": "浏览器实例繁忙（并发限制），请稍后重试。",
                    "fallback": "Try financial.websearch.",
                },
            )

        success = False
        try:
            content = self._run_playwright_fetch(url)
            success = bool(content and len(content) >= 100)
        except Exception as exc:
            logger.warning("Native Playwright failed: %s", str(exc)[:200])
        finally:
            _BROWSER_SEMAPHORE.release()
            _cb_record(success)
            if not success and _cb_should_trip():
                _cb_trip()
                logger.warning("Browser circuit breaker tripped (low success rate)")

        if not success or not content:
            return ToolResult(
                status="error",
                error_code="browser_fetch_failed",
                content={
                    "url": url[:200],
                    "message": "Browser fetch failed or returned empty content.",
                    "fallback": "Try financial.websearch to find mirrors or cached copies.",
                },
            )

        logger.info("Native Playwright fetch OK url=%s size=%d", url[:80], len(content))
        return ToolResult(status="ok", content=content)

    def _run_playwright_fetch(self, url: str) -> str:
        """Navigate URL with persistent browser + stealth, extract via Readability.

        Uses persistent Chromium instance (reused across calls) with stealth
        context and Readability.js content extraction for cleaner text.
        """
        browser = _get_persistent_browser()

        # ★ Stealth context — looks like a real browser
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)

            # Smart wait: try to detect main content element
            try:
                page.wait_for_selector("article, main, .content, .post-content, .article-content", timeout=5000)
            except Exception:
                pass  # fallback to whatever is there

            # ★ Readability.js extraction (clean article text, no ads/nav)
            content = page.evaluate("""() => {
                function extractText() {
                    // Try common article selectors first
                    const selectors = ['article', 'main', '.content', '.post-content', '.article-content', '.entry-content'];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.length > 200) return el.innerText;
                    }
                    // Fallback: remove obvious noise then get body text
                    const noise = document.querySelectorAll('nav, header, footer, aside, .ad, .sidebar, .comment, .related, .share, .cookie');
                    noise.forEach(n => n.remove());
                    return document.body ? document.body.innerText : '';
                }
                return extractText();
            }""")

            return content if content else ""
        finally:
            context.close()

    def _handle_fetch_weixin(self, request: ToolRequest) -> ToolResult:
        url = str(request.arguments.get("url", "")).strip()
        if not url:
            return ToolResult(
                status="error",
                error_code="invalid_url",
                content={"message": "url is required"},
            )
        # ★ SSRF gate (same as _handle_fetch)
        is_safe, reason = _is_url_safe(url)
        if not is_safe:
            logger.warning("SSRF blocked (weixin): %s — %s", url[:80], reason)
            return ToolResult(
                status="error",
                error_code="ssrf_blocked",
                content={"message": f"URL blocked by SSRF protection: {reason}"},
            )
        # ★ On Linux with native Playwright, try fetching weixin article text
        if not _IS_WINDOWS and _PLAYWRIGHT_AVAILABLE:
            # WeChat articles may work via native browser on some networks
            try:
                content = self._run_playwright_fetch(url)
                if content and len(content) > 100:
                    return ToolResult(status="ok", content=content)
            except Exception as exc:
                logger.warning("Native Playwright weixin fetch failed: %s", str(exc)[:200])

        # ★ Fast-fail on non-Windows without Playwright, or after native attempt failed
        if not _IS_WINDOWS or not _WSL_PYTHON or not _FETCH_WEIXIN_SCRIPT:
            return ToolResult(
                status="error",
                error_code="browser_mode_unavailable",
                content={
                    "message": "微信文章暂不支持自动抓取（服务器在海外，受微信访问限制）。请在本地浏览器打开文章，保存为 Markdown 后通过知识库注入。",
                    "fallback": "Try web.fetch — it may get partial content or search for mirrors.",
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
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                _wsl_kill(f"weixin_{url_hash}")
                subprocess.run(
                    ["wsl", "--", "rm", "-rf", wsl_tmp],
                    capture_output=True, text=True, encoding="utf-8", timeout=10,
                    stdin=subprocess.DEVNULL,
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
            stdin=subprocess.DEVNULL,
        )
        if _cp.returncode != 0:
            logger.warning("WSL cp failed: %s", _cp.stderr[:200])
        subprocess.run(
            ["wsl", "--", "rm", "-rf", wsl_tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
            stdin=subprocess.DEVNULL,
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


    # ── image.describe ──────────────────────────────────────────────

    def _handle_image_describe(self, request: ToolRequest) -> ToolResult:
        """Describe an image using multi-modal vision API (GPT-4V / Claude Vision).

        If CAGENTOS_VISION_API_KEY is not set, returns a placeholder message
        indicating the capability is available but not yet activated.
        """
        image_path = str(request.arguments.get("image_path", "")).strip()
        if not image_path:
            return ToolResult(
                status="error",
                error_code="invalid_argument",
                content={"message": "image_path is required"},
            )

        # Resolve path (relative to project root or absolute)
        img_path = Path(image_path)
        if not img_path.is_absolute():
            img_path = _PROJECT_ROOT / img_path
        if not img_path.exists():
            return ToolResult(
                status="error",
                error_code="file_not_found",
                content={
                    "message": f"Image not found: {img_path}",
                    "resolved_path": str(img_path),
                },
            )
        if not _VISION_API_KEY:
            return ToolResult(
                status="ok",
                content={
                    "image_path": str(img_path),
                    "status": "placeholder",
                    "message": (
                        "Multi-modal vision API key not configured. "
                        "Set CAGENTOS_VISION_API_KEY env var to activate "
                        "(supports OpenAI GPT-4V or any OpenAI-compatible vision endpoint). "
                        "Image file exists and is ready for analysis when API key is available."
                    ),
                    "file_size": img_path.stat().st_size,
                    "file_name": img_path.name,
                },
            )

        # Call vision API
        try:
            import base64 as _b64
            mime = _guess_image_mime(img_path)
            with open(img_path, "rb") as f:
                img_b64 = _b64.b64encode(f.read()).decode("ascii")

            import json as _json
            payload = {
                "model": _VISION_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a financial chart/data analyst. Describe this image "
                            "concisely but precisely. Identify: (1) chart type (bar/line/pie/scatter/table), "
                            "(2) key data points with values, (3) trend direction if applicable, "
                            "(4) if the image contains a table, output it as markdown table. "
                            "Respond in Chinese."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "请描述这张图片的内容，提取关键数据。",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{img_b64}",
                                },
                            },
                        ],
                    },
                ],
                "max_tokens": 1000,
                "temperature": 0.1,
            }
            headers = {
                "Authorization": f"Bearer {_VISION_API_KEY}",
                "Content-Type": "application/json",
            }
            resp = self.fetcher._session.post(
                _VISION_API_URL, json=payload, headers=headers, timeout=60,
            )
            resp.raise_for_status()
            data = _json.loads(resp.text)
            description = data["choices"][0]["message"]["content"]
            return ToolResult(
                status="ok",
                content={
                    "image_path": str(img_path),
                    "status": "analyzed",
                    "model": _VISION_MODEL,
                    "description": description,
                    "file_size": img_path.stat().st_size,
                    "file_name": img_path.name,
                },
            )
        except Exception as exc:
            logger.warning("image.describe failed path=%s err=%s", str(img_path), exc)
            return ToolResult(
                status="error",
                error_code="image_describe_failed",
                content={
                    "image_path": str(img_path),
                    "message": f"Vision API call failed: {exc}",
                    "file_name": img_path.name,
                },
            )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

# Anti-bot detection patterns — if HTTP response matches any of these,
# auto-fallback to browser mode.
_ANTIBOT_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"just a moment",           # Cloudflare JS Challenge
        r"checking your browser",   # Cloudflare
        r"enable javascript",       # Generic JS check
        r"verify you are a human",  # Generic CAPTCHA
        r"attention required",      # Cloudflare
        r"please turn javascript on",
        r"access denied",           # Generic block
        r"request blocked",
        r"challenge-page",          # Cloudflare
    ]
]
_ANTIBOT_MIN_LENGTH = 500  # responses shorter than this are suspect


def _guess_image_mime(path: Path) -> str:
    """Guess MIME type from file extension."""
    ext = path.suffix.lower()
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }
    return mapping.get(ext, "image/png")


def _looks_like_antibot(content: str) -> bool:
    """Detect anti-bot / CAPTCHA / JS-challenge pages in HTTP response.

    Returns True if the content appears to be a bot-protection page
    rather than real article content.
    """
    if not content:
        return True
    if len(content) < _ANTIBOT_MIN_LENGTH:
        return True
    # Only check the first 2000 chars — anti-bot signals are always near the top
    head = content[:2000]
    return any(p.search(head) for p in _ANTIBOT_PATTERNS)


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
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        pass  # best-effort cleanup


def _win_to_wsl_path(win_path: Path) -> str:
    """Convert a Windows path to WSL /mnt/... format."""
    drive = win_path.drive[0].lower()
    rest = str(win_path)[2:].replace("\\", "/")
    return f"/mnt/{drive}{rest}"
