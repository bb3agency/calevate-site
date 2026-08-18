"""A global DNC suppression survives every verb a tenant session can aim at it (D-192).

`scope='global'` is an ABSOLUTE platform-wide suppression — a regulator or TSP instruction
naming a number, or our own permanent refusal (DATA-MODEL §6) — and hard rule 1 says the
TABLE enforces that, not a route. Two migrations have now had to say so:

  * `e4f2a86b13d7` closed DELETE. `WITH CHECK` is not consulted on DELETE, so the
    permissive `USING` (which must admit `tenant_id IS NULL`, or a nationally suppressed
    number keeps getting dialled) let every tenant delete every global row.
  * `e7b45c19a308` closed UPDATE. `e4f2a86b13d7` had CHECKED update and cleared it, with a
    probe that only tried `SET source = 'hijacked'` — a statement that leaves the row
    GLOBAL and therefore fails `WITH CHECK` for a tenant session. The update that MOVES
    the row (`SET tenant_id = <me>, scope = 'tenant'`) satisfies `WITH CHECK` exactly,
    because the new row IS a legitimate row for that tenant. Two statements — re-tenant,
    then delete what you now own — lifted the suppression for every other client.

WHY THIS FILE RATHER THAN `rls_sweep_test.py`. That sweep asks "can tenant A touch tenant
B's rows", and a global row belongs to NO tenant: `tenant_id IS NULL` is outside every
probe there by construction. `dnc_list` is the only table in this schema whose `USING`
mentions `tenant_id IS NULL`, so the blast radius is this table and the gap is this shape.

WHY NOT THROUGH THE ROUTE. `dnc_test.py::
test_a_global_suppression_is_visible_to_a_tenant_and_not_removable` already drives
`DELETE /v1/dnc/{id}` and asserts the 422. That is `remove_entry`'s application check, and
it was written believing RLS refused the write underneath it. It did not. These tests go
straight at the table on a tenant-scoped session, which is the only altitude at which the
claim "no tenant can lift a global suppression" is actually testable.

CONCURRENCY: every test mints its own phone number, so this file runs beside the other
suites on the shared Postgres and asserts nothing about global counts.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.settings import Settings
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


#: A fresh dialable Indian mobile per test. `dnc_list` global rows outlive a test (they
#: belong to no tenant and no fixture tears them down), so a constant would couple runs.
def _number() -> str:
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


async def _tenant_id() -> uuid.UUID:
    """An organization to attack FROM, minted the one way this repo mints them.

    Not a hand-written INSERT: `organizations`' own WITH CHECK is `id = app.tenant_id`, so
    an untenanted session cannot write one at all — which is itself the §1 pattern working,
    and is why `admin_service.create_organization` exists.
    """
    created = await admin_service.create_organization(
        name="DNC Scope",
        slug=f"dnc-scope-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _insert_global(phone: str) -> uuid.UUID:
    """The ops write, on the owner connection. A tenant session cannot make one of these
    — that half has been true since `a1c8e40f27b9` — so the fixture must not pretend to."""
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: a global DNC row bypasses RLS"
    entry_id = uuid.uuid4()
    owner = create_async_engine(owner_url)
    try:
        async with owner.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, "
                    "added_at, created_at) VALUES (:id, NULL, :phone, 'global', "
                    "'regulator', now(), now())"
                ),
                {"id": entry_id, "phone": phone},
            )
    finally:
        await owner.dispose()
    return entry_id


async def _survives(entry_id: uuid.UUID) -> tuple[uuid.UUID | None, str | None]:
    """(tenant_id, scope) as the OWNER sees it — RLS-bypassing ground truth. Asking the
    attacker's own session whether the row is still global would let a successful
    re-tenanting answer 'yes, it is mine now' and read as a pass."""
    owner_url = Settings().alembic_database_url
    assert owner_url
    owner = create_async_engine(owner_url)
    try:
        async with owner.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT tenant_id, scope FROM dnc_list WHERE id = :id"),
                    {"id": entry_id},
                )
            ).first()
    finally:
        await owner.dispose()
    return (None, None) if row is None else (row[0], row[1])


async def test_a_tenant_session_cannot_re_tenant_a_global_suppression() -> None:
    """THE HOLE `e7b45c19a308` CLOSED. Red against `c7a1e93d40b8`: the UPDATE matched one
    row and the suppression became the attacker's, at which point deleting it is allowed
    by the very policy that is supposed to protect it."""
    tenant_id = await _tenant_id()
    phone = _number()
    entry_id = await _insert_global(phone)

    async with tenant_session(tenant_id) as session:
        moved = await session.execute(
            text(
                "UPDATE dnc_list SET tenant_id = :tid, scope = 'tenant' "
                "WHERE phone_e164 = :phone AND tenant_id IS NULL"
            ),
            {"tid": tenant_id, "phone": phone},
        )
        assert moved.rowcount == 0, (
            "a tenant session re-tenanted a global DNC row: the FOR ALL policy's USING "
            "admits tenant_id IS NULL and its WITH CHECK is satisfied by the NEW row, so "
            "nothing refused the move. dnc_list_update_scope is missing."
        )

    owner_tenant, owner_scope = await _survives(entry_id)
    assert owner_tenant is None and owner_scope == "global", (
        f"the platform-wide suppression is now {owner_scope!r} owned by {owner_tenant!r}"
    )


async def test_a_tenant_session_cannot_delete_a_global_suppression() -> None:
    """`e4f2a86b13d7`'s property, kept beside its sibling so the two verbs are read
    together — a future policy edit that fixes one by rewriting the shared permissive
    policy must not silently reopen the other."""
    tenant_id = await _tenant_id()
    phone = _number()
    entry_id = await _insert_global(phone)

    async with tenant_session(tenant_id) as session:
        removed = await session.execute(
            text("DELETE FROM dnc_list WHERE phone_e164 = :phone AND tenant_id IS NULL"),
            {"phone": phone},
        )
        assert removed.rowcount == 0, "a tenant session deleted a global DNC row"

    owner_tenant, owner_scope = await _survives(entry_id)
    assert owner_tenant is None and owner_scope == "global"


async def test_a_tenant_still_sees_a_global_suppression() -> None:
    """The clause the fix must NOT have narrowed. A restrictive FOR UPDATE policy is ANDed
    into UPDATE only; if it were written FOR ALL it would subtract from SELECT too, and a
    nationally suppressed number invisible to the gate is a number that keeps being
    dialled — the failure the asymmetric USING exists to prevent."""
    tenant_id = await _tenant_id()
    phone = _number()
    await _insert_global(phone)

    async with tenant_session(tenant_id) as session:
        scope = (
            await session.execute(
                text("SELECT scope FROM dnc_list WHERE phone_e164 = :phone"), {"phone": phone}
            )
        ).scalar()
    assert scope == "global"


async def test_a_tenant_can_still_edit_and_remove_its_own_entry() -> None:
    """The other half of "nothing may break to accommodate it": the restrictive policy's
    first branch has to keep a tenant's own tenant-scoped row fully writable."""
    tenant_id = await _tenant_id()
    phone = _number()
    entry_id = uuid.uuid4()

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:id, :tid, :phone, 'tenant', 'manual', now(), now())"
            ),
            {"id": entry_id, "tid": tenant_id, "phone": phone},
        )
        edited = await session.execute(
            text("UPDATE dnc_list SET source = 'manual' WHERE id = :id"), {"id": entry_id}
        )
        removed = await session.execute(
            text("DELETE FROM dnc_list WHERE id = :id"), {"id": entry_id}
        )
    assert edited.rowcount == 1 and removed.rowcount == 1


async def test_an_ops_session_can_still_correct_a_global_row() -> None:
    """The second branch: a session carrying NO tenant is the ops path, and it must keep
    write access to global rows — `remove_global_entry` runs there, and a restrictive
    policy that refused it would break the only way a suppression is ever lifted."""
    phone = _number()
    entry_id = await _insert_global(phone)

    async with untenanted_session() as session:
        edited = await session.execute(
            text("UPDATE dnc_list SET source = 'regulator-restated' WHERE id = :id"),
            {"id": entry_id},
        )
        removed = await session.execute(
            text("DELETE FROM dnc_list WHERE id = :id"), {"id": entry_id}
        )
    assert edited.rowcount == 1 and removed.rowcount == 1


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
async def test_the_restrictive_policy_exists_for_both_write_verbs(verb: str) -> None:
    """The catalog half, because the behavioural tests above would also pass if a future
    migration replaced the permissive policy with something narrower and dropped these.
    Two RESTRICTIVE policies, one per write verb, each ANDed with the permissive one
    (PG16 §5.8) — that shape is the decision, not an implementation detail."""
    owner_url = Settings().alembic_database_url
    assert owner_url
    owner = create_async_engine(owner_url)
    try:
        async with owner.connect() as conn:
            found = (
                (
                    await conn.execute(
                        text(
                            "SELECT p.polname FROM pg_policy p JOIN pg_class c "
                            "ON c.oid = p.polrelid WHERE c.relname = 'dnc_list' "
                            "AND p.polpermissive IS FALSE AND p.polcmd = :cmd"
                        ),
                        {"cmd": "w" if verb == "UPDATE" else "d"},
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await owner.dispose()
    assert found, f"dnc_list has no RESTRICTIVE policy scoped FOR {verb}"
