"""HTTP routes for knowledge base management — Phase 4c.

Endpoints:
  GET /api/v1/knowledge/triage          — list triaged articles from 分诊台账.md
  GET /api/v1/knowledge/triage?level=A  — filter by priority level (A/B/C)
  GET /api/v1/knowledge/articles        — list all articles under knowledge/
  GET /api/v1/knowledge/articles/{path} — read a specific article

The triage endpoint looks for 分诊台账.md in (priority order):
  1. knowledge/00_Inbox/分诊台账.md  (Researcher agent's canonical location)
  2. knowledge/分诊台账.md           (legacy/manual location)

Supports two formats (auto-detected):

  Format A — heading + bullet fields:
      ## 2026-06-16 | Title | Author
      - **来源**: ...
      - **文件**: knowledge/00_Inbox/...
      - **分诊等级**: ⭐⭐⭐ L2-高价值

  Format B — markdown table (Researcher agent output):
      | 日期 | 标题 | 来源 | 相关 | 新信息 | 总分 | 类别 | 关联标的 | 一句话理由 |
      | 2026-06-16 | NVDA Q2 财报 | 一手 | 2 | 2 | 9 | A | NVDA | Blackwell ramp |

  Tables in practice have inconsistent column counts (manually maintained),
  so the parser is defensive: it extracts what it can and skips bad rows.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriageEntry:
    """One triaged article."""
    date: str
    title: str
    author: str
    source: str
    file_path: str
    level: str            # canonical A/B/C/?
    raw_level: str
    topic: str
    score: str
    reason: str
    summary: str

    def to_dict(self) -> dict:
        return {
            "date": self.date, "title": self.title, "author": self.author,
            "source": self.source, "file_path": self.file_path,
            "level": self.level, "raw_level": self.raw_level,
            "topic": self.topic, "score": self.score, "reason": self.reason,
            "summary": self.summary,
        }


# ── Level normalization ───────────────────────────────────────────────

_LEVEL_LETTER_RE = re.compile(r"\b([ABC])\b", re.IGNORECASE)


def _normalize_level(raw: str) -> str:
    """Map raw level strings to canonical A/B/C.

    Handles: 'A', '**A**', 'A · 精读', 'L1/L2/L3', '⭐⭐⭐'
    """
    if not raw:
        return "?"
    m = re.search(r"L([123])", raw, re.IGNORECASE)
    if m:
        return {"3": "A", "2": "B", "1": "C"}[m.group(1)]
    cleaned = raw.replace("*", "").strip()
    m = _LEVEL_LETTER_RE.search(cleaned)
    if m:
        return m.group(1).upper()
    stars = raw.count("⭐")
    if stars >= 3: return "A"
    if stars == 2: return "B"
    if stars == 1: return "C"
    return "?"


# ── Format A: heading + bullet fields ─────────────────────────────────

_HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$")
_FIELD_RE = re.compile(r"^-\s+\*\*(.+?)\*\*\s*:\s*(.+?)\s*$")


def _parse_format_a(content: str) -> list[TriageEntry]:
    entries: list[TriageEntry] = []
    current: dict | None = None

    def _flush():
        nonlocal current
        if current is None: return
        file_path = (current.get("文件") or "").strip().strip("`")
        if file_path.startswith("knowledge/"):
            file_path = file_path[len("knowledge/"):]
        raw_level = current.get("分诊等级", "")
        entries.append(TriageEntry(
            date=current.get("_date", ""), title=current.get("_title", ""),
            author=current.get("_author", ""), source=current.get("来源", ""),
            file_path=file_path, level=_normalize_level(raw_level),
            raw_level=raw_level, topic=current.get("主题", ""),
            score="", reason=current.get("建议动作", current.get("核心增量信息", ""))[:200],
            summary="; ".join(f"{k}={v[:60]}" for k, v in current.items()
                              if not k.startswith("_") and v)[:400],
        ))
        current = None

    for line in content.splitlines():
        h = _HEADING_RE.match(line)
        if h:
            _flush()
            current = {"_date": h.group(1), "_title": h.group(2).strip(), "_author": h.group(3).strip()}
            continue
        if current is None: continue
        f = _FIELD_RE.match(line)
        if f:
            current[f.group(1).strip()] = f.group(2).strip()
    _flush()
    return entries


# ── Format B: markdown table ──────────────────────────────────────────

_DATE_VAL_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _strip_md_link(s: str) -> tuple[str, str]:
    """If s contains [text](url), return (text, url). Else (s, '')."""
    m = _MD_LINK_RE.search(s)
    if m: return m.group(1).strip(), m.group(2).strip()
    return s.strip(), ""


def _find_col(headers: list[str], *patterns) -> int:
    """Find first column whose header matches any of the regex patterns."""
    for i, name in enumerate(headers):
        for pat in patterns:
            if pat.search(name):
                return i
    return -1


def _parse_format_b(content: str) -> list[TriageEntry]:
    """Parse markdown table. Defensive against column-count variation."""
    entries: list[TriageEntry] = []
    table_lines = [l for l in content.splitlines() if l.strip().startswith("|")]
    if len(table_lines) < 2:
        return entries

    # Header
    headers = [f.strip() for f in table_lines[0].split("|")[1:-1]]
    C = {
        "date": _find_col(headers, re.compile(r"日期|date", re.I)),
        "title": _find_col(headers, re.compile(r"标题|title", re.I)),
        "source": _find_col(headers, re.compile(r"来源|source", re.I)),
        "score": _find_col(headers, re.compile(r"总分|score", re.I)),
        "category": _find_col(headers, re.compile(r"类别|category|分类", re.I)),
        "ticker": _find_col(headers, re.compile(r"标的|ticker|关联", re.I)),
        "reason": _find_col(headers, re.compile(r"理由|reason|一句话", re.I)),
    }

    for line in table_lines[1:]:
        if set(line.replace("|", "").strip()) <= {"-", ":"}:
            continue  # separator row
        fields = [f.strip() for f in line.split("|")[1:-1]]
        if len(fields) < 3: continue

        def _g(key: str) -> str:
            idx = C[key]
            return fields[idx] if 0 <= idx < len(fields) else ""

        # Date
        date_raw = _g("date")
        if not date_raw:
            for f in fields:
                m = _DATE_VAL_RE.search(f)
                if m: date_raw = m.group(1); break

        # Title (+ URL if markdown link)
        title_raw = _g("title")
        title, url = _strip_md_link(title_raw)

        # Source
        source = _g("source")
        if not source and url: source = url

        # Level — usually in category column; if not A/B/C, scan all fields
        raw_level = _g("category")
        if _normalize_level(raw_level) == "?":
            for f in fields:
                lv = _normalize_level(f)
                if lv != "?":
                    raw_level = f; break

        # Topic — category if it's not A/B/C; else ticker
        topic = ""
        if C["category"] >= 0 and _normalize_level(_g("category")) == "?":
            topic = _g("category")
        if not topic and C["ticker"] >= 0:
            topic = _g("ticker")

        score = _g("score")
        # Reason: prefer dedicated column; fall back to last non-empty field
        # (tables are inconsistent — some rows have fewer columns)
        reason = _g("reason")
        if not reason:
            # Walk fields from the end, skip level-like and score-like fields
            for f in reversed(fields):
                f_clean = f.strip()
                if not f_clean: continue
                # Skip if it's the level (A/B/C) or score (number)
                if _normalize_level(f_clean) != "?": continue
                if f_clean.replace("*", "").strip().isdigit(): continue
                # Skip if it's the topic or ticker (already used)
                if f_clean == topic: continue
                # This is likely the reason column
                reason = f_clean
                break

        if not title: continue

        entries.append(TriageEntry(
            date=date_raw, title=title, author="", source=source,
            file_path="", level=_normalize_level(raw_level), raw_level=raw_level,
            topic=topic, score=score, reason=reason[:200],
            summary=f"{title} | {topic} | {raw_level} | {reason[:80]}",
        ))
    return entries


def parse_triage_ledger(content: str) -> list[TriageEntry]:
    """Auto-detect format and parse. Both formats can coexist."""
    entries: list[TriageEntry] = []
    if _HEADING_RE.search(content):
        entries.extend(_parse_format_a(content))
    if "|" in content and any(l.strip().startswith("|") for l in content.splitlines()):
        entries.extend(_parse_format_b(content))

    # Dedupe by (date, title)
    seen, unique = set(), []
    for e in entries:
        key = (e.date, e.title)
        if key not in seen:
            seen.add(key); unique.append(e)
    unique.sort(key=lambda e: e.date, reverse=True)
    return unique


# ── Router ─────────────────────────────────────────────────────────────

def build_knowledge_router(knowledge_dir: Path) -> APIRouter:
    router = APIRouter()

    def _find_triage_ledger() -> Path | None:
        """Find triage ledger. Priority: 00_Inbox/分诊台账.md > 分诊台账.md"""
        for p in [knowledge_dir / "00_Inbox" / "分诊台账.md", knowledge_dir / "分诊台账.md"]:
            if p.exists(): return p
        return None

    def _resolve_file_path(title: str) -> str:
        """Fuzzy-match a triage entry title to a local archived article.

        Strategy (in priority order):
          1. Exact: normalized title === normalized directory name
          2. Substring: normalized title is a substring of dir name (or vice versa)
          3. Keyword overlap: significant keywords overlap

        Normalization strips: whitespace, date prefixes, ALL punctuation
        (ASCII + Chinese full-width: ，、。！？：；""''【】（）｜—… etc).
        """
        if not title:
            return ""

        def _normalize(s: str) -> str:
            """Strip ALL punctuation + whitespace + date prefixes for matching."""
            # Remove date prefix like "2026-06-24-"
            s = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", s)
            # Remove ALL punctuation (ASCII + CJK full-width)
            # Includes: ,，、。！？：；""''""''【】()（）[]［］｜|—–-…·#0123456789$.%&
            s = re.sub(
                r"[\s,，、。！？：；""''""''【】\[\]（）()［］｜|…—–\-·#\"\'+=*$%&/\\@]+",
                "", s.lower()
            )
            return s

        clean_title = _normalize(title)
        if len(clean_title) < 4:
            return ""

        inbox_dir = knowledge_dir / "00_Inbox"
        if not inbox_dir.exists():
            return ""

        # Build list of (cleaned_dir_name, original_dir, article_path)
        candidates: list[tuple[str, Path, Path]] = []
        for d in inbox_dir.iterdir():
            if not d.is_dir():
                continue
            article = d / "article.md"
            if not article.exists():
                continue
            cd = _normalize(d.name)
            if cd:
                candidates.append((cd, d, article))

        # Strategy 1: exact match (after normalization)
        for cd, d, article in candidates:
            if clean_title == cd:
                return f"00_Inbox/{d.name}/article.md"

        # Strategy 2: substring (one is prefix/substring of the other)
        # Use the shorter string as probe; require ≥6 char overlap
        substring_matches = []
        probe = clean_title[:12]  # use first 12 chars of title as probe
        for cd, d, article in candidates:
            if len(cd) < 4: continue
            if probe in cd or cd[:12] in clean_title:
                substring_matches.append((cd, d, article))
        if len(substring_matches) == 1:
            return f"00_Inbox/{substring_matches[0][1].name}/article.md"

        # Strategy 3: character-overlap score (Jaccard-like)
        # Best for cases where word order differs or title is partial
        title_chars = set(clean_title)
        best_match = ""
        best_score = 0.0
        for cd, d, article in candidates:
            dir_chars = set(cd)
            if not dir_chars: continue
            # Intersection / min length (how much of the shorter string is covered)
            overlap = len(title_chars & dir_chars)
            shorter = min(len(clean_title), len(cd))
            score = overlap / shorter if shorter else 0
            # Require ≥80% char overlap AND length within 30% of each other
            if score >= 0.8 and abs(len(clean_title) - len(cd)) / max(1, len(cd)) < 0.35:
                if score > best_score:
                    best_score = score
                    best_match = f"00_Inbox/{d.name}/article.md"

        return best_match

    @router.get("/api/v1/knowledge/triage")
    def list_triage(level: str | None = Query(None)) -> dict:
        ledger = _find_triage_ledger()
        if ledger is None:
            return {"entries": [], "total": 0, "filtered": 0, "note": "分诊台账.md not found"}
        try:
            content = ledger.read_text(encoding="utf-8")
        except Exception as exc:
            return {"entries": [], "total": 0, "filtered": 0, "error": str(exc)}

        entries = parse_triage_ledger(content)
        if level:
            level = level.upper()
            entries = [e for e in entries if e.level == level]

        # Resolve file_path: if entry has none, fuzzy-match against 00_Inbox/ archives
        resolved = []
        for e in entries:
            if e.file_path:
                resolved.append(e)
            else:
                fp = _resolve_file_path(e.title)
                if fp:
                    resolved.append(TriageEntry(
                        date=e.date, title=e.title, author=e.author, source=e.source,
                        file_path=fp, level=e.level, raw_level=e.raw_level,
                        topic=e.topic, score=e.score, reason=e.reason, summary=e.summary,
                    ))
                else:
                    resolved.append(e)  # keep with empty file_path

        return {
            "entries": [e.to_dict() for e in resolved],
            "total": len(resolved),
            "filtered": len(resolved),
            "level_filter": level,
            "source_file": str(ledger.relative_to(knowledge_dir)).replace("\\", "/"),
            "matched_articles": sum(1 for e in resolved if e.file_path),
        }

    @router.get("/api/v1/knowledge/articles")
    def list_articles(subdir: str = Query("")) -> dict:
        base = knowledge_dir / subdir if subdir else knowledge_dir
        if not base.exists() or not base.is_dir():
            return {"articles": [], "total": 0}
        articles = []
        for md_file in base.rglob("*.md"):
            if "images" in md_file.parts: continue
            rel = md_file.relative_to(knowledge_dir)
            try:
                stat = md_file.stat()
                first = md_file.read_text(encoding="utf-8", errors="replace").splitlines()[0:1]
                title = first[0].lstrip("# ").strip() if first else md_file.name
            except Exception:
                stat = None; title = md_file.name
            articles.append({
                "path": str(rel).replace("\\", "/"),
                "title": title[:100],
                "size_bytes": stat.st_size if stat else 0,
                "modified_at": stat.st_mtime if stat else 0,
            })
        articles.sort(key=lambda a: a.get("modified_at", 0), reverse=True)
        return {"articles": articles, "total": len(articles)}

    @router.get("/api/v1/knowledge/articles/{article_path:path}")
    def read_article(article_path: str) -> dict:
        full = knowledge_dir / article_path
        try:
            full.resolve().relative_to(knowledge_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid article path")
        if not full.exists() or not full.is_file():
            raise HTTPException(status_code=404, detail=f"Article not found: {article_path}")
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read: {exc}")
        return {"path": article_path, "content": content, "size_bytes": len(content.encode("utf-8"))}

    return router
