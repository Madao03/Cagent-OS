"""Generate invitation codes for CagentOS 内测.

Usage:
    python scripts/generate_invitation_codes.py --count 10
    python scripts/generate_invitation_codes.py --count 5 --note "for 王老板 team"
    python scripts/generate_invitation_codes.py --list           # show all codes
    python scripts/generate_invitation_codes.py --list-available # only unused

Codes are 8-char base32 (no confusing chars 0/O/1/I/L).
"""
from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

# Add project src to path so we can import cagent_os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cagent_os.auth import InvitationCodeStore

# Alphabet without confusing chars (no 0, O, 1, I, L)
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8


def generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate invitation codes")
    parser.add_argument("--count", type=int, default=10, help="How many codes to generate")
    parser.add_argument("--note", default="", help="Optional note attached to each code")
    parser.add_argument("--list", action="store_true", help="List all codes and exit")
    parser.add_argument("--list-available", action="store_true", help="List only unused codes")
    parser.add_argument(
        "--db", default="data/invitation_codes.db",
        help="Path to invitation codes DB (default: data/invitation_codes.db)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.is_absolute():
        # Resolve relative to project root
        project_root = Path(__file__).resolve().parent.parent
        db_path = project_root / db_path

    store = InvitationCodeStore(str(db_path))

    if args.list or args.list_available:
        codes = store.list_available() if args.list_available else store.list_all()
        if not codes:
            print(f"No {'available ' if args.list_available else ''}codes in {db_path}")
            return 0
        print(f"{'CODE':<12} {'STATUS':<10} {'CREATED':<22} {'USED_BY':<10} NOTE")
        print("-" * 80)
        for c in codes:
            status = "USED" if c["used_by"] else "available"
            used = c["used_by"][:8] if c["used_by"] else "-"
            note = c.get("note") or ""
            print(f"{c['code']:<12} {status:<10} {c['created_at'][:19]:<22} {used:<10} {note}")
        avail = sum(1 for c in codes if not c["used_by"])
        print(f"\nTotal: {len(codes)} codes, {avail} available")
        return 0

    # Generate
    codes = [generate_code() for _ in range(args.count)]
    n = store.add_many(codes, created_by="cli", note=args.note)
    print(f"Generated {n} invitation codes (DB: {db_path}):")
    for c in codes:
        print(f"  {c}")
    if args.note:
        print(f"Note: {args.note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
