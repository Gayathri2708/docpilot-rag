"""API keys and access groups (RBAC).

Every document belongs to one access group. Every API key may read and write a set of groups,
and always the shared "all" group. Keys are stored only as SHA-256 hashes.

Create a key:  python -m app.auth create-key finance-bot --groups finance
"""

import argparse
import hashlib
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from .db import get_conn

ACCESS_GROUPS = ("all", "hr", "finance", "engineering")

# Well-known keys for local demos and tests. Disable with SEED_DEMO_KEYS=false anywhere real.
DEMO_KEYS = {
    "demo-admin": ("dp_demo_admin", ["hr", "finance", "engineering"]),
    "demo-hr": ("dp_demo_hr", ["hr"]),
    "demo-finance": ("dp_demo_finance", ["finance"]),
    "demo-engineering": ("dp_demo_engineering", ["engineering"]),
}


@dataclass(frozen=True)
class Principal:
    name: str
    groups: tuple[str, ...]  # always includes "all"

    def can_access(self, group: str) -> bool:
        return group in self.groups


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _principal(name: str, groups: list[str]) -> Principal:
    return Principal(name, tuple(dict.fromkeys(["all", *groups])))


def lookup(key: str) -> Principal | None:
    with get_conn() as conn:
        row = conn.execute("SELECT name, groups FROM api_keys WHERE key_hash = %s", (hash_key(key),)).fetchone()
    return _principal(row[0], row[1]) if row else None


def _insert(conn, name: str, key: str, groups: list[str]) -> None:
    unknown = set(groups) - set(ACCESS_GROUPS)
    if unknown:
        raise ValueError(f"Unknown access groups: {sorted(unknown)}")
    conn.execute(
        "INSERT INTO api_keys (name, key_hash, groups) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
        (name, hash_key(key), groups),
    )


def seed_demo_keys() -> None:
    with get_conn() as conn:
        for name, (key, groups) in DEMO_KEYS.items():
            _insert(conn, name, key, groups)


def revoke_demo_keys() -> int:
    """Delete the well-known demo keys, so turning SEED_DEMO_KEYS off also disables ones seeded earlier."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM api_keys WHERE key_hash = ANY(%s)", ([hash_key(k) for k, _ in DEMO_KEYS.values()],)
        )
        return cur.rowcount


_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="DocPilot API key")


def require_principal(key: str | None = Security(_header)) -> Principal:
    principal = lookup(key) if key else None
    if principal is None:
        raise HTTPException(
            401, "Missing or invalid API key. Send it in the X-API-Key header.", headers={"WWW-Authenticate": "APIKey"}
        )
    return principal


def main() -> None:
    from . import db

    parser = argparse.ArgumentParser(description="Manage DocPilot API keys.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-key", help="create a key and print it once")
    create.add_argument("name")
    create.add_argument("--groups", default="", help=f"comma-separated, from {', '.join(ACCESS_GROUPS[1:])}")
    args = parser.parse_args()

    key = f"dp_{secrets.token_urlsafe(24)}"
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    if unknown := sorted(set(groups) - set(ACCESS_GROUPS)):
        raise SystemExit(f"Unknown access groups: {', '.join(unknown)}. Choose from {', '.join(ACCESS_GROUPS[1:])}.")
    db.apply_schema()
    db.open_pool()
    try:
        with get_conn() as conn:
            _insert(conn, args.name, key, groups)
            stored = conn.execute("SELECT key_hash FROM api_keys WHERE name = %s", (args.name,)).fetchone()[0]
            if stored != hash_key(key):  # ON CONFLICT DO NOTHING kept an older key with this name
                raise SystemExit(f"A key named {args.name!r} already exists.")
    finally:
        db.close_pool()
    print(f"{args.name}: {key}  (groups: all, {', '.join(groups) or '-'}). Store it now; it is not shown again.")


if __name__ == "__main__":
    main()
