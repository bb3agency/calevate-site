"""`make db-reset` drops the schema instead of walking the chain backwards (D-208).

THE DEFECT, PROVEN BY CAUSING IT. On a scratch database at head, seeded, holding one
first-party operator (`admin_users.clerk_user_id IS NULL` — what
`scripts/bootstrap_admin.py` writes), `alembic downgrade base` fails:

    psycopg.errors.NotNullViolation: column "clerk_user_id" of relation "admin_users"
    contains null values
    [SQL: ALTER TABLE admin_users ALTER COLUMN clerk_user_id SET NOT NULL]

and STOPS MID-CHAIN with `alembic_version` at `b3d9f6a2c815` while 62 tables are still
there. That stranded shape — version table disagreeing with the schema — is the state the
shared development database was found in, where every subsequent `upgrade head` then failed
on an object that already existed.

`b3d9f6a2c815`'s refusal is correct and this file does not touch it: past that revision a
downgrade is a restore, not a rollback, and re-imposing the constraint on rows that violate
it must fail. What was wrong was routing a RESET through it.

WHAT IS TESTED HERE, and what deliberately is not. The destructive path is not driven —
a test that drops the schema out from under four concurrently running suites is a worse
defect than the one it checks. What IS driven is the GUARD, which is the part with a
decision in it, plus the shape of the recipe, because a script nothing invokes is the
half-wired change this repo names by name.
"""

from __future__ import annotations

import pathlib

import pytest
from scripts.db_reset import reset_schema

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_it_refuses_outside_a_local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv(
        "ALEMBIC_DATABASE_URL", "postgresql+psycopg://calevate:calevate@localhost:5433/anything"
    )
    with pytest.raises(SystemExit) as refused:
        reset_schema()
    assert "APP_ENV" in str(refused.value)


def test_it_refuses_a_dsn_that_is_not_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second, independent fact. A copied `.env` keeps `APP_ENV=local` while pointing
    somewhere real, which is one mistake — this guard needs two."""
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv(
        "ALEMBIC_DATABASE_URL", "postgresql+psycopg://calevate:calevate@db.example.com:5432/prod"
    )
    with pytest.raises(SystemExit) as refused:
        reset_schema()
    assert "loopback" in str(refused.value)


def test_it_refuses_without_the_owner_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app role is `NOSUPERUSER NOBYPASSRLS` and cannot drop a schema it does not own,
    so falling back to `DATABASE_URL` would fail halfway through with a permission error
    naming whichever object needed the privilege first — the same argument `alembic/env.py`
    makes about never falling back."""
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    with pytest.raises(SystemExit) as refused:
        reset_schema()
    assert "ALEMBIC_DATABASE_URL" in str(refused.value)


def test_the_reset_recipe_no_longer_walks_the_chain_backwards() -> None:
    """The seam, asserted where it is actually wired. `scripts/db_reset.py` existing is
    worth nothing if `make db-reset` still calls `alembic downgrade base`."""
    commands: list[str] = []
    inside = False
    for line in (REPO / "Makefile").read_text().splitlines():
        if line.startswith("db-reset:"):
            inside = True
            continue
        if not inside:
            continue
        if line and not line.startswith("\t"):
            break
        stripped = line.strip()
        # Comment lines inside the recipe explain the change; they are not what runs.
        if stripped and not stripped.startswith("#"):
            commands.append(stripped)

    assert commands, "the db-reset target is gone"
    body = "\n".join(commands)
    assert "scripts.db_reset" in body, "db-reset no longer calls the reset script"
    assert "upgrade head" in body, "db-reset drops the schema and never rebuilds it"
    assert "downgrade base" not in body, (
        "db-reset walks the chain backwards again: a downgrade can be refused by the data "
        "the database holds, and it fails mid-chain rather than atomically"
    )
