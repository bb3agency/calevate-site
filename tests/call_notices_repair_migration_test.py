"""`f2477c8d623d` repairs D-1021's account-notice backfill, proved under an owner role that
row-level security binds the way it binds production's.

`c4e8a2f61d93` turned an account's notice switch on wherever one of its agents had it on, with
no `NO FORCE` bracket on `organizations` or `agents`. Its own test passed because the local
owner role is a superuser, and a superuser bypasses RLS whatever FORCE says: the statement saw
every row. Production's owner is `NOSUPERUSER` (DEPLOYMENT §9.3a), FORCE binds it to the
fail-closed tenant policy, and the backfill saw none. So every test here runs the migration as
`rls_bound_owner()`: a role with the owner's privileges through membership and neither
`SUPERUSER` nor `BYPASSRLS`, which is how Postgres decides both who owns a table and whether
its policy applies (`check_enable_rls`). One transaction, always rolled back.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.compliance.audit import write_audit
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from sqlalchemy import Connection, create_engine, text
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.anyio

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
REPAIR = "f2477c8d623d_call_notices_backfill_under_rls"
SHIPPED = "c4e8a2f61d93_call_notices_per_account"
JOB = "refresh_account_notices"


def load_revision(stem: str) -> ModuleType:
    """One alembic revision, loaded from its file the way alembic loads it."""
    spec = importlib.util.spec_from_file_location(f"_revision_{stem}", VERSIONS / f"{stem}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def rls_bound_owner() -> Iterator[tuple[Connection, Callable[[], None]]]:
    """A connection as the migration owner in one transaction, always rolled back, and a call
    that makes it RLS-bound for what follows.

    Before the call the connection is the configured owner, for arranging rows. The call
    switches to a role created in this transaction that is a member of the table owner, so
    it owns the tables as migrations do, and is neither `SUPERUSER` nor `BYPASSRLS`, so FORCE
    binds it. Where the configured owner is already bound (CI or a production-like role), it
    is used as it is."""
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                bypasses, owner = connection.execute(
                    text(
                        "SELECT r.rolsuper OR r.rolbypassrls, t.tableowner FROM pg_roles r, "
                        "pg_tables t WHERE r.rolname = current_user "
                        "AND t.tablename = 'organizations' AND t.schemaname = 'public'"
                    )
                ).one()
                probe = f"migration_probe_{uuid.uuid4().hex[:12]}"
                if bypasses:
                    connection.execute(
                        text(f"CREATE ROLE {probe} NOLOGIN NOSUPERUSER NOBYPASSRLS INHERIT")
                    )
                    connection.execute(text(f'GRANT "{owner}" TO {probe}'))

                def become() -> None:
                    if bypasses:
                        connection.execute(text(f"SET LOCAL ROLE {probe}"))

                yield connection, become
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Repair Notices",
        slug=f"rn-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        created_by=None,
    )
    return created["id"], created["agent_id"]


def _arrange(connection: Connection, tenant_id: uuid.UUID, *, ai: bool, recording: bool) -> None:
    """The state the shipped backfill left in production: the account off, its agents as
    they were the day before."""
    connection.execute(
        text(
            "UPDATE organizations SET notice_ai_enabled = false, "
            "notice_recording_enabled = false WHERE id = :t"
        ),
        {"t": tenant_id},
    )
    connection.execute(
        text(
            "UPDATE agents SET ai_disclosure_enabled = :ai, recording_notice_enabled = :rec "
            "WHERE tenant_id = :t"
        ),
        {"ai": ai, "rec": recording, "t": tenant_id},
    )


def _account(connection: Connection, tenant_id: uuid.UUID) -> tuple[bool, bool]:
    row = connection.execute(
        text("SELECT notice_ai_enabled, notice_recording_enabled FROM organizations WHERE id = :t"),
        {"t": tenant_id},
    ).one()
    return bool(row[0]), bool(row[1])


def _jobs(connection: Connection, tenant_id: uuid.UUID) -> list[Any]:
    return connection.execute(
        text(
            "SELECT payload, min_revision FROM outbox_messages WHERE job = :j "
            "AND payload->>'tenant_id' = :t"
        ),
        {"j": JOB, "t": str(tenant_id)},
    ).all()


def _shipped_backfill() -> list[str]:
    """The UPDATEs `c4e8a2f61d93.upgrade()` issued, taken from the module, not retyped."""
    module = load_revision(SHIPPED)
    captured: list[str] = []
    module.op = SimpleNamespace(  # type: ignore[attr-defined]
        execute=captured.append, add_column=lambda *_a, **_k: None
    )
    module.upgrade()
    return [sql for sql in captured if sql.startswith("UPDATE")]


async def test_the_shipped_backfill_matched_no_row_under_an_rls_bound_owner() -> None:
    """FAILS IF: this harness stops being bound by RLS, which would make every test below
    vacuous in exactly the way `c4e8a2f61d93`'s own test was."""
    tenant_id, _agent = await _tenant()
    with rls_bound_owner() as (connection, become):
        _arrange(connection, tenant_id, ai=True, recording=True)
        become()
        assert connection.execute(text("SELECT count(*) FROM organizations")).scalar_one() == 0
        for sql in _shipped_backfill():
            connection.execute(text(sql))
        connection.execute(text("RESET ROLE"))
        assert _account(connection, tenant_id) == (False, False)


async def test_the_repair_turns_on_what_an_agent_had_on_and_keeps_an_owners_choice() -> None:
    some_on, _a = await _tenant()
    owner_chose, _b = await _tenant()
    none_on, _c = await _tenant()
    # The owner of `owner_chose` switched the AI notice off after the deploy.
    async with tenant_session(owner_chose) as session:
        await write_audit(
            session,
            action="organization.ai_disclosure_disabled",
            tenant_id=owner_chose,
            object_type="organization",
            object_id=str(owner_chose),
        )
    repair = load_revision(REPAIR)
    with rls_bound_owner() as (connection, become):
        _arrange(connection, some_on, ai=True, recording=True)
        _arrange(connection, owner_chose, ai=True, recording=True)
        _arrange(connection, none_on, ai=False, recording=False)
        become()
        with Operations.context(MigrationContext.configure(connection)):
            repair.downgrade()
            repair.upgrade()
            connection.execute(text("RESET ROLE"))
            assert _account(connection, some_on) == (True, True)
            # Only the switch the owner moved is theirs; the recording notice is restored.
            assert _account(connection, owner_chose) == (False, True)
            assert _account(connection, none_on) == (False, False)
            [(payload, stamped)] = _jobs(connection, some_on)
            payload = payload if isinstance(payload, dict) else json.loads(payload)
            assert payload == {"tenant_id": str(some_on), "ai": True, "recording": True}
            assert stamped == "f2477c8d623d", "an older release must not claim the job"
            [(payload, _stamped)] = _jobs(connection, owner_chose)
            payload = payload if isinstance(payload, dict) else json.loads(payload)
            assert (payload["ai"], payload["recording"]) == (False, True)
            assert _jobs(connection, none_on) == []
            generation = connection.execute(
                text("SELECT notice_generation FROM organizations WHERE id = :t"),
                {"t": some_on},
            ).scalar_one()
            assert generation == 1, "the flip is new work for the opening rewrite"

            # Idempotent: run again, nothing is still off, nothing more is queued.
            become()
            repair.downgrade()
            repair.upgrade()
            connection.execute(text("RESET ROLE"))
            assert len(_jobs(connection, some_on)) == 1
            assert _account(connection, owner_chose) == (False, True)
