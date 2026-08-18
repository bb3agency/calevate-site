"""`make db-reset`, as a RESET rather than as a rollback (D-208).

WHAT WAS WRONG WITH `alembic downgrade base`. It is the obvious spelling and it is the
wrong operation, for a reason that is structural rather than incidental: a downgrade
UNDOES revisions in order, so it can be defeated by the DATA the database happens to
hold — and a developer's database always holds some. Two of this repo's own revisions
already refuse:

  * `b3d9f6a2c815` restores `NOT NULL` on `admin_users.clerk_user_id` /
    `users.clerk_user_id`. `scripts/bootstrap_admin.py` — the ordinary way a developer
    gets an operator account — writes a first-party admin with no Clerk id, so the reset
    fails on the row the normal dev flow creates. That migration's docstring argues the
    refusal is CORRECT, and it is: past that point a downgrade is a restore, not a
    rollback. What is not correct is a reset routed through it.
  * `f9c2b41a8e57`'s unique index cannot be re-imposed on a database carrying the
    double-credit residue DATA-MODEL §8 describes (`runbooks/stale-dev-database.md`).

PROVEN, not reasoned. On a scratch database migrated to head, seeded, and given one
first-party operator row, `alembic downgrade base` fails with
`column "clerk_user_id" of relation "admin_users" contains null values` — and stops
mid-chain, leaving `alembic_version` at `b3d9f6a2c815` while the schema still carries 62
tables. That stranded state is not hypothetical either: it is exactly the shape the shared
development database was found in, where the version table and the schema disagreed and
every subsequent `upgrade head` failed on an object that already existed.

WHAT A RESET ACTUALLY IS. Drop the schema, build it once from the chain. That is O(1) in
revisions instead of O(74), it cannot be refused by data because there is no data left to
refuse with, and it cannot half-apply: either `public` is gone and rebuilt or nothing
happened. It is also what every framework in this class does — Django's `flush`/recreate,
Rails' `db:reset`, Prisma's `migrate reset` — all of which drop and re-migrate rather than
walking the chain backwards.

WHY NOT `DROP DATABASE`. The database carries role grants and an owner that
`scripts/dev_bootstrap.sh` created; recreating it would need a connection to `postgres`
and would put this script in the business of provisioning. `DROP SCHEMA public CASCADE`
removes every table, index, policy, trigger, function and type this repo has ever created
— confirmed by the D-192 pass, which found `pg_proc` and `pg_type` empty after a clean
downgrade, so there is nothing of ours outside `public` — and the re-`GRANT` below is the
one thing that does not survive it.

THE GUARD. This script destroys data, so it refuses to run anywhere but a local
development database, and it refuses on TWO independent facts rather than one: `APP_ENV`
must be `local`, and the DSN's host must be a loopback name. Either alone is a single
misconfiguration away from being wrong — a copied `.env` keeps `APP_ENV=local` while
pointing at a remote host, and a tunnel makes a remote database look like `localhost`.
Both together require two mistakes at once.

It runs as the OWNER role (`ALEMBIC_DATABASE_URL`), the same role migrations use and for
the same reason: `calevate_app` is `NOSUPERUSER NOBYPASSRLS` and cannot drop a schema it
does not own. There is deliberately no `--force` flag: a flag that turns the guard off is
the guard nobody has.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

#: Hosts a development database may live on. Names rather than a resolved address: the
#: point is that the DSN a developer is looking at SAYS local, not that a packet happens
#: to stay on the box.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})

#: The role the app connects as. Re-granted after the drop because schema privileges do
#: not survive `DROP SCHEMA`, and the next `alembic upgrade head` would otherwise build a
#: schema the application cannot see into.
APP_ROLE_DEFAULT = "calevate_app"


def _owner_url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL")
    if not url:
        raise SystemExit(
            "ALEMBIC_DATABASE_URL is not set. A reset drops and rebuilds the schema, which "
            "only the OWNER role may do; the app's DATABASE_URL is the unprivileged "
            "calevate_app role. Copy .env.example to .env."
        )
    return url.replace("+asyncpg", "+psycopg")


def _app_role() -> str:
    """The role to re-grant, read off `DATABASE_URL` rather than assumed, so a developer
    who renamed it in `dev_bootstrap.sh` does not get a schema their app cannot use."""
    dsn = os.environ.get("DATABASE_URL", "")
    user = urlsplit(dsn.replace("+psycopg", "").replace("+asyncpg", "")).username
    return user or APP_ROLE_DEFAULT


def _refuse_unless_local(owner_url: str) -> None:
    app_env = os.environ.get("APP_ENV", "")
    host = (urlsplit(owner_url.replace("+psycopg", "").replace("+asyncpg", "")).hostname) or ""
    if app_env != "local":
        raise SystemExit(
            f"db-reset refuses: APP_ENV is {app_env!r}, not 'local'. This drops every table, "
            "policy and row in the target database. If this really is a development "
            "database, say so by setting APP_ENV=local."
        )
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"db-reset refuses: ALEMBIC_DATABASE_URL points at host {host!r}, which is not "
            "loopback. APP_ENV says local and the DSN does not, and the two disagreeing is "
            "exactly the state this guard exists for."
        )


def reset_schema() -> None:
    owner_url = _owner_url()
    _refuse_unless_local(owner_url)
    role = _app_role()

    engine = create_engine(owner_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            database = conn.execute(text("SELECT current_database()")).scalar()
            # CASCADE, because policies, triggers, functions and enum types all hang off
            # the tables. `IF EXISTS` so a reset of a database that never had a schema is
            # a no-op rather than an error a developer has to read.
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            # The two grants `scripts/dev_bootstrap.sh` makes, restated because the drop
            # took them with it. Quoted identifier: the role name comes from a DSN.
            conn.execute(text(f'GRANT ALL ON SCHEMA public TO "{role}"'))
            conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))
        print(f"db-reset: schema public dropped and recreated on {database} (granted to {role})")
    finally:
        engine.dispose()


if __name__ == "__main__":  # pragma: no cover - entrypoint
    reset_schema()
    sys.exit(0)
