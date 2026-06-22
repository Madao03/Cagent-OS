from __future__ import annotations

import re

_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


def extract_skill_description(content: str) -> str:
    frontmatter = _extract_frontmatter(content)
    if not frontmatter:
        return ""
    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() == "description":
            return value.strip().strip('"').strip("'")
    return ""


def extract_skill_body(content: str) -> str:
    match = _FRONTMATTER_PATTERN.match(content or "")
    if not match:
        return (content or "").strip()
    return (content[match.end() :] or "").strip()


def _extract_frontmatter(content: str) -> str:
    match = _FRONTMATTER_PATTERN.match(content or "")
    if not match:
        return ""
    return match.group(1)
