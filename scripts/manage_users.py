"""User management CLI — list / disable / enable users.

Usage:
    python scripts/manage_users.py list
    python scripts/manage_users.py list --active     # only active users
    python scripts/manage_users.py disable alice
    python scripts/manage_users.py enable alice
    python scripts/manage_users.py invitations       # list all invitation codes

Use this for 内测 user management. Web admin dashboard can be built later.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cagent_os.auth import InvitationCodeStore, UserStore

DB_PATH = Path(r"d:\Projects\cagent-os\data\users.db")
INV_DB_PATH = Path(r"d:\Projects\cagent-os\data\invitation_codes.db")


def cmd_list(args) -> int:
    store = UserStore(str(DB_PATH))
    users = store.list_users(include_disabled=not args.active)
    if not users:
        print("No users registered yet.")
        return 0

    print(f"{'USERNAME':<25} {'STATUS':<10} {'VIA':<12} {'CREATED':<22} INVITATION_CODE")
    print("-" * 100)
    for u in users:
        status = "DISABLED" if u.disabled else "active"
        created = u.created_at[:19] if u.created_at else "?"
        inv = u.invitation_code or "-"
        print(f"{u.username:<25} {status:<10} {u.created_via:<12} {created:<22} {inv}")

    active = sum(1 for u in users if not u.disabled)
    disabled = sum(1 for u in users if u.disabled)
    print(f"\nTotal: {len(users)} users ({active} active, {disabled} disabled)")
    return 0


def cmd_disable(args) -> int:
    store = UserStore(str(DB_PATH))
    try:
        store.set_disabled(args.username, disabled=True)
        print(f"✓ Disabled user: {args.username}")
        return 0
    except Exception as exc:
        print(f"✗ Failed: {exc}")
        return 1


def cmd_enable(args) -> int:
    store = UserStore(str(DB_PATH))
    try:
        store.set_disabled(args.username, disabled=False)
        print(f"✓ Enabled user: {args.username}")
        return 0
    except Exception as exc:
        print(f"✗ Failed: {exc}")
        return 1


def cmd_invitations(args) -> int:
    store = InvitationCodeStore(str(INV_DB_PATH))
    codes = store.list_all()
    if not codes:
        print("No invitation codes. Generate some with:")
        print("  python scripts/generate_invitation_codes.py --count 5")
        return 0

    print(f"{'CODE':<12} {'STATUS':<10} {'CREATED':<22} {'USED_BY':<10} NOTE")
    print("-" * 90)
    for c in codes:
        status = "USED" if c["used_by"] else "available"
        created = c["created_at"][:19] if c["created_at"] else "?"
        used = (c["used_by"] or "-")[:8]
        note = c.get("note") or ""
        print(f"{c['code']:<12} {status:<10} {created:<22} {used:<10} {note}")

    avail = sum(1 for c in codes if not c["used_by"])
    print(f"\nTotal: {len(codes)} codes ({avail} available, {len(codes) - avail} used)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CagentOS user management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List all registered users")
    p_list.add_argument("--active", action="store_true", help="Show only active (non-disabled) users")
    p_list.set_defaults(func=cmd_list)

    p_disable = sub.add_parser("disable", help="Disable a user account")
    p_disable.add_argument("username")
    p_disable.set_defaults(func=cmd_disable)

    p_enable = sub.add_parser("enable", help="Re-enable a disabled user account")
    p_enable.add_argument("username")
    p_enable.set_defaults(func=cmd_enable)

    p_inv = sub.add_parser("invitations", help="List all invitation codes")
    p_inv.set_defaults(func=cmd_invitations)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
