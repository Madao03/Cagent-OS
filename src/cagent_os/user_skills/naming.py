from __future__ import annotations

import hashlib
import re
import unicodedata

_NON_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_MAX_SKILL_NAME_LENGTH = 64


def normalize_skill_name(skill_name: str) -> str:
    raw = str(skill_name or "").strip()
    if not raw:
        return "custom-skill"

    normalized = (
        unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii").lower()
    )
    slug = _NON_SLUG_PATTERN.sub("-", normalized).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)

    if not slug:
        slug = f"skill-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"

    slug = slug[:_MAX_SKILL_NAME_LENGTH].strip("-")
    return slug or "custom-skill"
