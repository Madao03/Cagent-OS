"""Chunker — split knowledge base content into retrieval-ready chunks.

Two schemes (simplified from NashNova's 6-scheme chunk_validator):
  - Scheme 1 (news):    flat mode, chunk_size=512, overlap=50
  - Scheme 2 (research): parent-child mode, parent=1500, child=300, overlap=0

Preprocessing:
  - Noise header filtering (disclaimer / analyst certification / compliance)

Inputs:
  - knowledge/00_Inbox/**/*.md        (article.md + 分诊台账.md)
  - knowledge/01_Assets/**/*.json     (asset.json, if content-assetize produced any)

Output: list of Chunk objects, ready for embedding.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    """A single retrieval-ready text chunk with metadata."""
    id: str
    text: str
    source: str          # file path relative to knowledge/
    title: str           # article title or ledger
    section: str         # markdown header context (e.g. "## 核心观点")
    chunk_type: str      # "research" | "news" | "earnings" | "social" | "ledger" | "asset_fact" | "asset_opinion" | "asset_framework"
    date: str            # date extracted from folder name or frontmatter
    parent_index: int = -1   # -1 = flat mode (no parent)


# ------------------------------------------------------------------
# Noise header patterns (simplified from chunk_validator.py)
# ------------------------------------------------------------------

_NOISE_PATTERNS = [
    # Chinese compliance / disclaimer
    re.compile(r"^#{1,3}\s*(风险提示|免责声明|分析师声明|重要声明|法律声明|信息披露|评级说明)", re.MULTILINE),
    re.compile(r"^#{1,3}\s*(证券分析师声明|一般声明|投资评级说明|分析师承诺)", re.MULTILINE),
    # English compliance
    re.compile(r"^#{1,3}\s*(Disclaimer|Risk\s+Factors?|Disclosure|Analyst\s+Certification)", re.MULTILINE | re.IGNORECASE),
    # Wechat boilerplate
    re.compile(r"^#{1,3}\s*(更多精彩|关注公众号|扫码|二维码|点赞|在看|分享)", re.MULTILINE),
]

# Hard cutoff: everything from this line onward gets dropped
_HARD_CUTOFF = [
    re.compile(r"^#{1,3}\s*(免责声明|重要声明|法律声明)", re.MULTILINE),
    re.compile(r"^#{1,3}\s*(Disclosure\s+Appendix|IMPORTANT\s+DISCLOSURES)", re.MULTILINE | re.IGNORECASE),
]


def _preprocess(markdown: str) -> str:
    """Remove YAML frontmatter, noise headers, and hard-cutoff compliance sections."""
    # Remove YAML frontmatter (--- at start ... ---)
    if markdown.startswith("---"):
        end = markdown.find("\n---", 3)
        if end != -1:
            markdown = markdown[end + 4:]

    # Hard cutoff: find first match, drop everything after
    for pattern in _HARD_CUTOFF:
        match = pattern.search(markdown)
        if match:
            markdown = markdown[:match.start()]

    # Noise header removal: remove matching lines
    lines = markdown.split("\n")
    cleaned = []
    for line in lines:
        is_noise = False
        for pattern in _NOISE_PATTERNS:
            if pattern.match(line):
                is_noise = True
                break
        if not is_noise:
            cleaned.append(line)

    # Collapse excessive blank lines
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ------------------------------------------------------------------
# Text splitter (simplified from TextSplitter.py)
# ------------------------------------------------------------------

# Protected patterns — don't split inside these
_PROTECTED_REGEX = [
    r"```[\s\S]*?```",              # code blocks
    r"\$\$[\s\S]*?\$\$",              # math blocks
    r"!\[.*?\]\(.*?\)",               # images
    r"(?:\|.+\|\n){2,}",             # full tables (2+ consecutive pipe rows = header + separator + data)
]


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Recursive text splitter with overlap and protected patterns."""
    if not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text.strip()]

    # Protect code blocks and tables from being split
    protected = []
    for pattern in _PROTECTED_REGEX:
        for match in re.finditer(pattern, text):
            placeholder = f"__PROTECTED_{len(protected)}__"
            protected.append(match.group())
            text = text.replace(match.group(), placeholder, 1)

    # Split by separators recursively
    chunks = _recursive_split(text, chunk_size, overlap)

    # Restore protected content
    restored = []
    for chunk in chunks:
        for i, content in enumerate(protected):
            chunk = chunk.replace(f"__PROTECTED_{i}__", content)
        if chunk.strip():
            restored.append(chunk.strip())

    return restored


def _recursive_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text by separators, merging into chunks of ~chunk_size."""
    for sep in ["\n\n", "\n", "。", "！", "？", ". ", "! ", "? ", " "]:
        parts = text.split(sep)
        if len(parts) <= 1:
            continue

        chunks = []
        current = ""
        for part in parts:
            part_with_sep = part + sep if sep != "\n\n" else part + "\n\n"
            if len(current) + len(part_with_sep) <= chunk_size:
                current += part_with_sep
            else:
                if current.strip():
                    chunks.append(current.strip())
                # If the part itself is too long, recurse
                if len(part) > chunk_size:
                    sub = _recursive_split(part, chunk_size, overlap)
                    chunks.extend(sub)
                    current = ""
                else:
                    if overlap > 0 and len(current) > overlap:
                        current = current[-overlap:] + part_with_sep
                    else:
                        current = part_with_sep
        if current.strip():
            chunks.append(current.strip())

        if chunks:
            return chunks

    # Last resort: character split
    return [text[i:i+chunk_size].strip() for i in range(0, len(text), chunk_size - overlap) if text[i:i+chunk_size].strip()]


# ------------------------------------------------------------------
# Header tracking
# ------------------------------------------------------------------

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _extract_headers(text: str) -> list[tuple[int, str, int, int]]:
    """Return [(level, title, start, end)] for all markdown headers."""
    headers = []
    for match in _HEADER_RE.finditer(text):
        level = len(match.group(1))
        title = match.group(2).strip()
        headers.append((level, title, match.start(), match.end()))
    return headers


def _get_section_for_position(headers: list[tuple[int, str, int, int]], pos: int) -> str:
    """Find the nearest preceding header for a character position."""
    section = ""
    for level, title, start, end in headers:
        if start <= pos:
            section = f"{'#' * level} {title}"
        else:
            break
    return section


# ------------------------------------------------------------------
# Chunking schemes
# ------------------------------------------------------------------

def chunk_research(markdown: str, source: str, title: str, date: str) -> list[Chunk]:
    """Scheme 2: parent-child mode. parent=1500, child=300, overlap=0."""
    cleaned = _preprocess(markdown)
    headers = _extract_headers(cleaned)

    # Split into parent chunks (1500 chars)
    parent_chunks = _split_text(cleaned, 1500, 0)

    chunks = []
    char_offset = 0
    for p_idx, parent in enumerate(parent_chunks):
        # Split parent into children (300 chars)
        children = _split_text(parent, 300, 0)
        for c_idx, child in enumerate(children):
            section = _get_section_for_position(headers, char_offset)
            chunk_id = f"{source}__p{p_idx}_c{c_idx}"
            chunks.append(Chunk(
                id=chunk_id,
                text=child,
                source=source,
                title=title,
                section=section,
                chunk_type="research",
                date=date,
                parent_index=p_idx,
            ))
            char_offset += len(child)

    return chunks


def chunk_news(markdown: str, source: str, title: str, date: str) -> list[Chunk]:
    """Scheme 1: flat mode. chunk_size=512, overlap=50."""
    cleaned = _preprocess(markdown)
    headers = _extract_headers(cleaned)
    parts = _split_text(cleaned, 512, 50)

    chunks = []
    char_offset = 0
    for idx, part in enumerate(parts):
        section = _get_section_for_position(headers, char_offset)
        chunk_id = f"{source}__f{idx}"
        chunks.append(Chunk(
            id=chunk_id,
            text=part,
            source=source,
            title=title,
            section=section,
            chunk_type="news",
            date=date,
        ))
        char_offset += len(part) - 50 if len(part) > 50 else 0

    return chunks


def chunk_ledger(markdown: str, source: str, title: str = "分诊台账", date: str = "") -> list[Chunk]:
    """Scheme 3: ledger rows — split markdown table rows into individual chunks."""
    cleaned = _preprocess(markdown)
    chunks = []
    # Find table rows (lines starting and ending with |)
    table_rows = [line.strip() for line in cleaned.split("\n") if line.strip().startswith("|") and "|" in line[2:]]
    # Skip header and separator rows, keep data rows
    data_rows = [r for r in table_rows if not re.match(r"^\|[-\s|]*\|$", r) and "---|---" not in r]
    for idx, row in enumerate(data_rows):
        chunk_id = f"{source}__ledger_{idx}"
        # Extract tickers and key info for metadata
        stripped = row.replace("|", " ").strip()
        chunks.append(Chunk(
            id=chunk_id, text=row, source=source, title=title,
            section="分诊台账", chunk_type="ledger", date=date,
        ))
    return chunks


def chunk_earnings(markdown: str, source: str, title: str, date: str) -> list[Chunk]:
    """Scheme 4: earnings/financial data — larger flat chunks, table-aware."""
    cleaned = _preprocess(markdown)
    headers = _extract_headers(cleaned)
    parts = _split_text(cleaned, 1024, 0)
    chunks = []
    char_offset = 0
    for idx, part in enumerate(parts):
        section = _get_section_for_position(headers, char_offset)
        chunk_id = f"{source}__earn_{idx}"
        chunks.append(Chunk(
            id=chunk_id, text=part, source=source, title=title,
            section=section, chunk_type="earnings", date=date,
        ))
        char_offset += len(part)
    return chunks


def chunk_social(markdown: str, source: str, title: str, date: str) -> list[Chunk]:
    """Scheme 5: KOL/social media — small flat chunks with higher overlap."""
    cleaned = _preprocess(markdown)
    headers = _extract_headers(cleaned)
    parts = _split_text(cleaned, 256, 30)
    chunks = []
    char_offset = 0
    for idx, part in enumerate(parts):
        section = _get_section_for_position(headers, char_offset)
        chunk_id = f"{source}__soc_{idx}"
        chunks.append(Chunk(
            id=chunk_id, text=part, source=source, title=title,
            section=section, chunk_type="social", date=date,
        ))
        char_offset += len(part) - 30 if len(part) > 30 else 0
    return chunks


def _count_tables(markdown: str) -> int:
    """Count markdown tables (consecutive pipe rows with separator line)."""
    return len(re.findall(r"(?:^\|.+?\|\n){2,}", markdown, re.MULTILINE))


def _detect_scheme(markdown: str, filename: str = "") -> str:
    """Auto-detect which chunking scheme to use based on content characteristics.

    Priority (first match wins):
      1. ledger   — file named 分诊台账
      2. earnings — 3+ tables detected
      3. social   — very short (<400 chars) with short paragraphs
      4. news     — mid-length (400-2000 chars)
      5. research — everything else (parent-child)
    """
    if "分诊台账" in filename or "ledger" in filename.lower():
        return "ledger"

    if _count_tables(markdown) >= 3:
        return "earnings"

    lines = [l.strip() for l in markdown.split("\n") if l.strip()]
    if len(markdown) < 400 and all(len(l) < 120 for l in lines[:20]):
        return "social"

    if len(markdown) < 2000:
        return "news"

    return "research"


# Scheme dispatcher
_SCHEME_MAP = {
    "research": chunk_research,
    "news": chunk_news,
    "ledger": chunk_ledger,
    "earnings": chunk_earnings,
    "social": chunk_social,
}


def chunk_json(asset_json: dict, source: str, title: str, date: str) -> list[Chunk]:
    """Scheme 6: asset.json — each fact/opinion/framework is a separate chunk."""
    chunks = []

    for key, chunk_type in [("facts", "asset_fact"), ("opinions", "asset_opinion"), ("frameworks", "asset_framework")]:
        items = asset_json.get(key, [])
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if isinstance(item, dict):
                text = json.dumps(item, ensure_ascii=False)
            else:
                text = str(item)
            if not text.strip():
                continue
            chunk_id = f"{source}__{chunk_type}_{idx}"
            chunks.append(Chunk(
                id=chunk_id,
                text=text,
                source=source,
                title=title,
                section=f"Asset: {key}",
                chunk_type=chunk_type,
                date=date,
            ))

    return chunks


# ------------------------------------------------------------------
# Knowledge base scanner
# ------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _extract_date_from_path(path: Path, knowledge_root: Path) -> str:
    """Extract date from folder name like '2026-06-16-万字科普美联储...'."""
    rel = path.relative_to(knowledge_root)
    parts = rel.parts
    for part in parts:
        match = _DATE_RE.match(part)
        if match:
            return match.group(1)
    return ""


def _extract_title_from_path(path: Path) -> str:
    """Extract article title from folder name."""
    if path.parent.name and path.parent != path:
        name = path.parent.name
    else:
        name = path.stem
    # Remove date prefix
    name = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name)
    return name


def scan_knowledge_base(knowledge_root: Path | str) -> list[Chunk]:
    """Scan knowledge/ directory and chunk all content.

    Scans:
      - knowledge/00_Inbox/**/*.md         → article.md (scheme 2 research)
      - knowledge/00_Inbox/分诊台账.md      → ledger (scheme 1 news)
      - knowledge/00_Inbox/速读_*.md        → quick reads (scheme 1 news)
      - knowledge/01_Assets/**/*.json      → asset.json (per-field chunking)

    Returns:
        List of Chunk objects ready for embedding.
    """
    root = Path(knowledge_root)
    if not root.exists():
        logger.warning("Knowledge root does not exist: %s", root)
        return []

    all_chunks: list[Chunk] = []

    # --- Scan 00_Inbox for article.md ---
    inbox = root / "00_Inbox"
    if inbox.exists():
        for article_path in sorted(inbox.rglob("article.md")):
            relative = str(article_path.relative_to(root))
            title = _extract_title_from_path(article_path)
            date = _extract_date_from_path(article_path, root)
            markdown = article_path.read_text(encoding="utf-8")
            scheme = _detect_scheme(markdown, filename=article_path.name)
            chunk_fn = _SCHEME_MAP.get(scheme, chunk_research)
            chunks = chunk_fn(markdown, source=relative, title=title, date=date)
            all_chunks.extend(chunks)
            logger.info("Chunked %s [%s]: %d chunks", relative, scheme, len(chunks))

        # --- Scan 分诊台账.md (always ledger scheme) ---
        ledger = inbox / "分诊台账.md"
        if ledger.exists():
            markdown = ledger.read_text(encoding="utf-8")
            chunks = chunk_ledger(markdown, source=str(ledger.relative_to(root)),
                                  title="分诊台账", date="")
            all_chunks.extend(chunks)
            logger.info("Chunked 分诊台账.md [ledger]: %d chunks", len(chunks))

        # --- Scan 速读_*.md ---
        for quick_read in sorted(inbox.glob("速读_*.md")):
            relative = str(quick_read.relative_to(root))
            match = _DATE_RE.search(quick_read.name)
            date = match.group(1) if match else ""
            markdown = quick_read.read_text(encoding="utf-8")
            scheme = _detect_scheme(markdown, filename=quick_read.name)
            chunk_fn = _SCHEME_MAP.get(scheme, chunk_news)
            chunks = chunk_fn(markdown, source=relative, title=quick_read.stem, date=date)
            all_chunks.extend(chunks)
            logger.info("Chunked %s [%s]: %d chunks", relative, scheme, len(chunks))

        # --- Scan standalone .md files (use auto-detection) ---
        for md_file in sorted(inbox.glob("*.md")):
            if md_file.name == "分诊台账.md" or md_file.name.startswith("速读_"):
                continue
            relative = str(md_file.relative_to(root))
            match = _DATE_RE.search(md_file.name)
            date = match.group(1) if match else ""
            markdown = md_file.read_text(encoding="utf-8")
            scheme = _detect_scheme(markdown, filename=md_file.name)
            chunk_fn = _SCHEME_MAP.get(scheme, chunk_news)
            chunks = chunk_fn(markdown, source=relative, title=md_file.stem, date=date)
            all_chunks.extend(chunks)
            logger.info("Chunked %s [%s]: %d chunks", relative, scheme, len(chunks))

    # --- Scan 01_Assets for asset.json ---
    assets = root / "01_Assets"
    if assets.exists():
        for asset_path in sorted(assets.rglob("*.json")):
            relative = str(asset_path.relative_to(root))
            date = _extract_date_from_path(asset_path, root)
            try:
                data = json.loads(asset_path.read_text(encoding="utf-8"))
                chunks = chunk_json(data, source=relative, title=asset_path.stem, date=date)
                all_chunks.extend(chunks)
                logger.info("Chunked %s: %d chunks", relative, len(chunks))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to parse %s: %s", relative, e)

    logger.info("Total chunks from knowledge base: %d", len(all_chunks))
    return all_chunks
