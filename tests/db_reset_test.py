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

THAT PROMISE IS NOW STRUCTURAL, AND IT USED TO BE AN ACCIDENT. `db_reset` read
`os.environ` alone, so `monkeypatch.delenv("ALEMBIC_DATABASE_URL")` genuinely left it
with no database to drop. The moment the script started reading `.env` too — which it had
to, because `make db-reset` could not otherwise run at all (D-394) — that deletion stopped
neutralising anything and the refusal test dropped the developer's schema instead of
asserting a refusal. `_hermetic_env` below is what makes the promise hold on purpose: no
test in this file can see a DSN it did not write down.
"""

from __future__ import annotations

import pathlib

import pytest
from scripts import db_reset
from scripts.db_reset import reset_schema

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Every read `db_reset` makes, answered from a dict this file owns.

    AUTOUSE AND EMPTY BY DEFAULT, so the failure mode is a refusal rather than a drop: a
    test that forgets to declare a DSN gets "ALEMBIC_DATABASE_URL is not set", which is
    the safe direction and also the assertion one of them wants. `monkeypatch.setenv`
    cannot serve here — the point is precisely that `db_reset` no longer reads only the
    process environment, and a test that pretended otherwise would be testing the
    accident this fixture replaces.
    """
    declared: dict[str, str] = {}
    monkeypatch.setattr(db_reset, "_env", lambda: declared)
    return declared


def test_it_refuses_outside_a_local_environment(_hermetic_env: dict[str, str]) -> None:
    _hermetic_env["APP_ENV"] = "prod"
    _hermetic_env["ALEMBIC_DATABASE_URL"] = (
        "postgresql+psycopg://calevate:calevate@localhost:5433/anything"
    )
    with pytest.raises(SystemExit) as refused:
        reset_schema()
    assert "APP_ENV" in str(refused.value)


def test_it_refuses_a_dsn_that_is_not_loopback(_hermetic_env: dict[str, str]) -> None:
    """The second, independent fact. A copied `.env` keeps `APP_ENV=local` while pointing
    somewhere real, which is one mistake — this guard needs two."""
    _hermetic_env["APP_ENV"] = "local"
    _hermetic_env["ALEMBIC_DATABASE_URL"] = (
        "postgresql+psycopg://calevate:calevate@db.example.com:5432/prod"
    )
    with pytest.raises(SystemExit) as refused:
        reset_schema()
    assert "loopback" in str(refused.value)


def test_it_refuses_without_the_owner_dsn(_hermetic_env: dict[str, str]) -> None:
    """The app role is `NOSUPERUSER NOBYPASSRLS` and cannot drop a schema it does not own,
    so falling back to `DATABASE_URL` would fail halfway through with a permission error
    naming whichever object needed the privilege first — the same argument `alembic/env.py`
    makes about never falling back."""
    _hermetic_env["APP_ENV"] = "local"
    with pytest.raises(SystemExit) as refused:
        reset_schema()
    assert "ALEMBIC_DATABASE_URL" in str(refused.value)


def test_the_reset_recipe_no_longer_walks_the_chain_backwards() -> None:
    """The seam, asserted where it is actually wired. `scripts/db_reset.py` existing is
    worth nothing if `make db-reset` still calls `alembic downgrade base`."""
    commands: list[str] = []
    inside = False
    for line in (REPO / "Makefile").read_text(encoding="utf-8").splitlines():
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
