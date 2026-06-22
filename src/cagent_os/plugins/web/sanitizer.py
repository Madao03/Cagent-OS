from __future__ import annotations

import re
from html import unescape


def sanitize_html(content: str) -> str:
    without_scripts = re.sub(r"<script\b[^>]*>.*?</script>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    without_styles = re.sub(r"<style\b[^>]*>.*?</style>", " ", without_scripts, flags=re.IGNORECASE | re.DOTALL)

    text: list[str] = []
    inside_tag = False
    for char in without_styles:
        if char == "<":
            inside_tag = True
            continue
        if char == ">":
            inside_tag = False
            text.append(" ")
            continue
        if not inside_tag:
            text.append(char)

    return " ".join(unescape("".join(text)).split())
