from __future__ import annotations

import logging
from typing import Any

import requests

from cagent_os.config import Settings
from cagent_os.plugins.web.sanitizer import sanitize_html
from cagent_os.shared.logging_utils import build_log_extra, format_log_context

logger = logging.getLogger(__name__)


class WebFetcher:
    def __init__(self, settings: Settings, session: requests.Session | Any | None = None) -> None:
        self._settings = settings
        self._session = session or requests.Session()
        self._jina_available: bool | None = None  # cached: None=未检测, True/False=已检测
        if hasattr(self._session, "trust_env"):
            self._session.trust_env = False
        if settings.effective_proxy and hasattr(self._session, "proxies"):
            self._session.proxies = {
                "http": settings.effective_proxy,
                "https": settings.effective_proxy,
            }

    def fetch(self, url: str) -> str:
        # Jina 预检:只检测一次,不可用就跳过(省去每次 5s 超时等待)
        if self._jina_available is None:
            self._jina_available = self._check_jina_available()

        if self._jina_available:
            jina_content = self._fetch_via_jina(url)
            if jina_content:
                return jina_content

        # ★ SSRF redirect protection: disable auto-redirect, validate each hop.
        # Initial URL is already validated by _is_url_safe in plugin.py,
        # but 301/302 to internal IP would bypass that. Here we follow
        # redirects manually, re-validating each Location header.
        from cagent_os.plugins.web.plugin import _is_url_safe

        current_url = url
        for _ in range(5):  # max 5 redirects
            response = self._session.get(current_url, timeout=10, allow_redirects=False)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location", "")
                if not location:
                    break
                # Resolve relative redirects
                from urllib.parse import urljoin
                location = urljoin(current_url, location)
                # ★ Validate redirect target
                safe, reason = _is_url_safe(location)
                if not safe:
                    logger.warning("SSRF redirect blocked: %s → %s (%s)", current_url[:60], location[:60], reason)
                    raise ValueError(f"Redirect to blocked URL: {reason}")
                current_url = location
                continue
            break

        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" in content_type:
            return sanitize_html(response.text)
        return response.text

    def _check_jina_available(self) -> bool:
        """Quick health check: 3s timeout. If Jina is unreachable, skip for entire session."""
        try:
            resp = self._session.get("https://r.jina.ai/", timeout=3)
            return resp.ok or resp.status_code in (400, 404)  # 400/404 means server is up, just no URL
        except Exception:
            logger.info("Jina AI not available, will use direct fetch for all URLs")
            return False

    def _fetch_via_jina(self, url: str) -> str | None:
        headers = {"Accept": "text/markdown"}
        if self._settings.jina_api_key:
            headers["Authorization"] = f"Bearer {self._settings.jina_api_key}"
        try:
            response = self._session.get(f"https://r.jina.ai/{url}", headers=headers, timeout=5)
            if response.ok and response.text.strip():
                return response.text
        except Exception:
            logger.warning(
                "Jina fetch failed %s",
                format_log_context(url=url),
                extra=build_log_extra(url=url),
                exc_info=True,
            )
            return None
        return None
