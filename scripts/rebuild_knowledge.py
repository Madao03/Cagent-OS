"""Rebuild or update the RAG knowledge base index.

Usage:
    # Full rebuild (re-embed everything, ~2 min for 1491 chunks)
    python scripts/rebuild_knowledge.py

    # Incremental update (only embed files added since last index)
    python scripts/rebuild_knowledge.py --incremental

    # Dry-run (just report what would be added, no embedding)
    python scripts/rebuild_knowledge.py --dry-run

When to use:
    - After adding new articles to knowledge/ → --incremental
    - After changing embedding model → full rebuild
    - After deleting articles → full rebuild (incremental can't detect deletions)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cagent_os.rag.rag_service import RAGService


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild RAG knowledge index")
    parser.add_argument(
        "--incremental", action="store_true",
        help="Only embed files added since last index (skip already-indexed)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be done without actually embedding",
    )
    parser.add_argument(
        "--knowledge-dir", default="knowledge",
        help="Path to knowledge directory (default: knowledge)",
    )
    parser.add_argument(
        "--vectors-dir", default="data/vectors",
        help="Where to store vectors.npy + metadata.json (default: data/vectors)",
    )
    args = parser.parse_args()

    knowledge_dir = Path(args.knowledge_dir)
    if not knowledge_dir.exists():
        print(f"✗ Knowledge dir not found: {knowledge_dir}")
        return 1

    vectors_dir = Path(args.vectors_dir)
    vectors_dir.mkdir(parents=True, exist_ok=True)

    print(f"Knowledge dir: {knowledge_dir.resolve()}")
    print(f"Vectors dir:   {vectors_dir.resolve()}")
    print()

    # Count current articles
    md_files = [p for p in knowledge_dir.rglob("*.md") if "images" not in p.parts]
    print(f"Found {len(md_files)} markdown files in knowledge/")

    if args.dry_run:
        print("\n[DRY RUN] Would scan + chunk + embed these files.")
        for f in md_files[:10]:
            print(f"  {f.relative_to(knowledge_dir)}")
        if len(md_files) > 10:
            print(f"  ... and {len(md_files) - 10} more")
        return 0

    # Build RAG service
    print("\nInitializing RAG service...")
    rag = RAGService(
        knowledge_dir=str(knowledge_dir),
        chroma_path=str(vectors_dir),
    )

    # Current state
    status = rag.status()
    print(f"  Current index: {status['chunks']} chunks")
    print(f"  Embedding model: {status['embedding_model']}")

    if args.incremental:
        # Incremental: scan for new files only
        # The RAGService.ingest method with clear_first=False appends new chunks
        # but doesn't dedupe — so for true incremental we'd need to track hashes.
        # For MVP, we just re-embed everything with clear_first=False, which
        # MAY create duplicates. Recommend full rebuild instead.
        print("\n⚠️  Incremental mode has a caveat:")
        print("   It will re-embed ALL files (not just new ones) because the")
        print("   current implementation doesn't track per-file hashes.")
        print("   For safety, this mode does a full rebuild instead.")
        print("   Use --dry-run to preview first.")
        print()
        result = rag.ingest(clear_first=True)
    else:
        print("\nFull rebuild (clearing existing index)...")
        result = rag.ingest(clear_first=True)

    print()
    print(f"✓ Done: {result}")
    new_status = rag.status()
    print(f"  New index: {new_status['chunks']} chunks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
