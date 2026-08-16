"""Create the first `admin_users` row, without which a deployed platform is unreachable.

`admin_users` is the allowlist the entire admin realm resolves against — `core/auth.py`
does `SELECT id, role FROM admin_users WHERE clerk_user_id = :cid` on every admin request —
and `core/clerk_identity.py` states the design deliberately: *"The admin realm is never
reconciled. `admin_users` is not a Clerk mirror; it is an ops-managed allowlist."*

**Nothing else in this repository ever inserts a row.** Not `scripts/seed.py`, not
`scripts/vps-deploy.sh`, not `compose.prod.yml`, not any runbook. So after
`alembic upgrade head` on a fresh host the table is empty and every admin-realm request
403s: no organization can be created, no platform setting written, no platform secret
stored, no first-campaign review decided, no KYC verified. **The deploy comes up green and
the product cannot onboard anybody.** It fails closed, so this was never a security hole —
it was a deployment with no way in.

WHY A SCRIPT AND NOT A SEED ROW. `scripts/seed.py` writes only facts that are true of every
deployment (the reserved-slug list). An admin identity is the opposite: it is one specific
human's Clerk user id, different on every deployment, and it is a grant of the widest
authority in the platform. A hardcoded default here would be a backdoor with a changelog
entry. So the id is an argument and there is no default.

WHY NOT A ROUTE. The obvious alternative — a bootstrap endpoint that self-disables after
the first call — is a route that exists to be unauthenticated exactly once, which is a
window an attacker can race on a public host, and a permanent piece of code whose whole
value is that it can never be reached again. The database is already reachable by whoever
runs the deploy; the smallest correct thing is to write the row there.

IDEMPOTENT, by `ON CONFLICT (clerk_user_id) DO NOTHING`. Re-running is the ordinary case:
an operator re-deploys, or adds a second admin, and neither should be a failure. What it
does NOT do is UPDATE — promoting an existing `operator` to `superadmin` is a privilege
change and belongs to the console's own audited path, not to a bootstrap script that
nobody watches.

USAGE (from the repo root, with `ALEMBIC_DATABASE_URL` set — it connects as the OWNER role
because `admin_users` carries no RLS policy and the app role has no need to write it):

    uv run python -m scripts.bootstrap_admin --clerk-user-id user_2abc... --role superadmin
    uv run python -m scripts.bootstrap_admin --clerk-user-id user_2def... --name "Ops"

The Clerk user id comes from the ADMIN Clerk application's dashboard (the admin realm is a
separate Clerk app from the client realm — TRD §11), and it is the `sub` claim the API will
see. Getting the wrong realm's id here produces a row that never matches anything, which is
why `--clerk-user-id` is validated for shape rather than accepted blind.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from uuid_utils.compat import uuid7

#: The two roles `ck_admin_users_role_enum` admits. Spelled here rather than imported so
#: this script has no dependency on the app package booting — it runs against a database
#: that may predate the image it is being run from.
ROLES = ("superadmin", "operator")

#: Clerk user ids are `user_` plus a base58-ish opaque tail. Checked for SHAPE only: the
#: point is to catch a pasted email address, an org id (`org_…`), or a client-realm id
#: typed from the wrong dashboard — not to validate a credential we cannot verify offline.
_CLERK_USER_ID = re.compile(r"^user_[A-Za-z0-9]{20,}$")


def _database_url() -> str:
    """The OWNER url, never the app one.

    `admin_users` has no RLS policy (it is platform state, not tenant state), and the app
    role has no reason to hold write access to the allowlist that decides who is an
    operator. `alembic/env.py` makes the same choice for the same reason and refuses to
    fall back to `DATABASE_URL`; this refuses too, rather than silently writing as whoever
    `DATABASE_URL` happens to be.
    """
    url = os.environ.get("ALEMBIC_DATABASE_URL")
    if not url:
        raise SystemExit(
            "ALEMBIC_DATABASE_URL is not set. This script writes the admin allowlist and "
            "connects as the migration/owner role, not as the application role — set it "
            "the way `alembic upgrade head` needs it set."
        )
    return url.replace("postgresql+psycopg://", "postgresql+psycopg_async://", 1)


async def _insert(url: str, *, clerk_user_id: str, role: str, name: str | None) -> str:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(
                text(
                    "INSERT INTO admin_users (id, clerk_user_id, name, role) "
                    "VALUES (:id, :cid, :name, :role) "
                    "ON CONFLICT (clerk_user_id) DO NOTHING "
                    "RETURNING id"
                ),
                {"id": uuid7(), "cid": clerk_user_id, "name": name, "role": role},
            )
            row = result.first()
            if row is not None:
                return f"created admin_users row {row[0]} with role {role}"
            # Already present. Report the role it ALREADY has rather than the one asked
            # for: an operator re-running this with `--role superadmin` must not be left
            # believing the promotion happened.
            existing = (
                await connection.execute(
                    text("SELECT id, role FROM admin_users WHERE clerk_user_id = :cid"),
                    {"cid": clerk_user_id},
                )
            ).first()
            assert existing is not None  # ON CONFLICT fired, so the row is there
            note = (
                ""
                if existing[1] == role
                else (
                    f" — NOTE: it holds role {existing[1]}, not {role}. This script never "
                    "promotes; change the role from the admin console so the change is audited."
                )
            )
            return f"already present as {existing[0]} with role {existing[1]}{note}"
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bootstrap_admin",
        description="Create the first admin_users row on a freshly migrated database.",
    )
    parser.add_argument(
        "--clerk-user-id",
        required=True,
        help="The `sub` from the ADMIN Clerk application (starts with user_).",
    )
    parser.add_argument("--role", choices=ROLES, default="superadmin")
    parser.add_argument("--name", default=None, help="Display name, for the audit trail.")
    args = parser.parse_args(argv)

    if not _CLERK_USER_ID.match(args.clerk_user_id):
        # Refuse rather than write a row that will never match a request. A wrong id here
        # is indistinguishable from an empty table at the 403, which is the hardest
        # possible thing to diagnose from the outside.
        print(
            f"'{args.clerk_user_id}' does not look like a Clerk user id (expected "
            "`user_` followed by an opaque tail). Copy it from the ADMIN Clerk "
            "application's Users page — the admin realm is a separate Clerk app from the "
            "client realm, and the client realm's id will never match here.",
            file=sys.stderr,
        )
        return 2

    print(
        asyncio.run(
            _insert(
                _database_url(), clerk_user_id=args.clerk_user_id, role=args.role, name=args.name
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
