"""`tenant_session`'s ambient publication and `joined_tenant_session`'s two refusals.

The mechanism is three lines of `contextvars` and its correctness rests entirely on facts
about how a `ContextVar` behaves around an async generator and around a task — exactly the
class of fact hard rule 11 says to MEASURE rather than recall. So each property has a test
that would fail if the fact were the other way:

* a `set()` inside an `@asynccontextmanager` body reaches the caller, and the `finally`
  clears it on the exception path too;
* a `ContextVar` is COPIED into every child task, so the ambient record carries the task
  that opened it and a child gets its own session rather than driving its parent's
  concurrently;
* sibling tasks never see each other's, which is what makes this safe under `gather`;
* and the one that is not about `contextvars` at all — a join is only ever offered for the
  tenant the caller NAMED. That is hard rule 1, and it is the reason there is no
  `current_tenant_session()` anywhere in this repo.

No organisation rows are minted: every assertion here is about `app.tenant_id` on the
connection, which `session_tenant` reads back out of the GUC itself.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from apps.api.db.session import joined_tenant_session, session_tenant, tenant_session
from sqlalchemy.ext.asyncio import AsyncSession


async def test_a_join_for_the_same_tenant_is_the_callers_own_session() -> None:
    """THE DEFECT'S FIX, at its smallest: no second connection and no second transaction.

    Identity rather than "a session scoped to the same tenant" is the assertion that
    matters — the deadlock was a SECOND TRANSACTION taking `FOR KEY SHARE` on a row the
    first held `FOR UPDATE`, and only the same object can be the same transaction.
    """
    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as outer, joined_tenant_session(tenant_id) as inner:
        assert inner is outer


async def test_a_join_for_a_different_tenant_opens_its_own() -> None:
    """HARD RULE 1, AND IT IS THE POINT OF THE WHOLE DESIGN.

    Reusing a session scoped to another client would write under their GUC — a tenancy
    breach far worse than the deadlock this closes. It is structurally unavailable rather
    than merely avoided: the ambient record is module-private and the only door takes the
    tenant as an ARGUMENT, so a mismatch cannot return the wrong session; it can only open
    a right one.
    """
    one, two = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(one) as outer, joined_tenant_session(two) as inner:
        assert inner is not outer
        assert await session_tenant(inner) == two
        # And the caller's own session is untouched by the callee's.
        assert await session_tenant(outer) == one


async def test_the_ambient_session_is_cleared_when_the_block_raises() -> None:
    """A rolled-back transaction must never be joinable by whatever runs next on this task.

    The `finally` is what guarantees it; without it the `ContextVar` would still name a
    session whose transaction has been rolled back and whose connection is back in the
    pool.
    """
    tenant_id = uuid.uuid4()
    with pytest.raises(RuntimeError, match="deliberate"):
        async with tenant_session(tenant_id):
            raise RuntimeError("deliberate")

    async with joined_tenant_session(tenant_id) as fresh:
        assert fresh.in_transaction()
        assert await session_tenant(fresh) == tenant_id


async def test_no_ambient_session_means_the_join_opens_one() -> None:
    """The worker and poller paths: nobody is in a transaction, so this is `tenant_session`
    with an extra branch and nothing else."""
    tenant_id = uuid.uuid4()
    async with joined_tenant_session(tenant_id) as session:
        assert await session_tenant(session) == tenant_id


async def test_sibling_tasks_do_not_see_each_others_ambient_session() -> None:
    """`gather` snapshots the context per task, so two concurrent requests for two clients
    cannot cross. Asserted rather than assumed: this is the fact the whole mechanism rests
    on, and it is one `ContextVar` semantic away from being a cross-tenant leak."""
    tenants = [uuid.uuid4() for _ in range(4)]

    async def hold(tenant_id: uuid.UUID) -> tuple[AsyncSession, AsyncSession, uuid.UUID]:
        async with tenant_session(tenant_id) as outer:
            # Interleave: every task is inside its own session while the others are.
            await asyncio.sleep(0)
            async with joined_tenant_session(tenant_id) as inner:
                await asyncio.sleep(0)
                return outer, inner, await session_tenant(inner)

    results = await asyncio.gather(*(hold(tenant_id) for tenant_id in tenants))

    for tenant_id, (outer, inner, observed) in zip(tenants, results, strict=True):
        assert inner is outer
        assert observed == tenant_id
    assert len({id(outer) for outer, _, _ in results}) == len(tenants)


async def test_a_child_task_gets_its_own_session_rather_than_its_parents() -> None:
    """THE HAZARD A TENANT CHECK ALONE WOULD NOT CATCH, and the reason the ambient record
    carries a task.

    A `ContextVar` set in a parent IS visible to every task spawned inside it — measured,
    not recalled. So two children of one `tenant_session`, matching on tenant alone, would
    both be handed the SAME `AsyncSession` and would drive it concurrently: SQLAlchemy's
    `InterfaceError` under load, and one transaction carrying two callers' work at best.
    Each child must therefore open its own.
    """
    tenant_id = uuid.uuid4()

    async def child() -> AsyncSession:
        async with joined_tenant_session(tenant_id) as session:
            await asyncio.sleep(0)
            assert await session_tenant(session) == tenant_id
            return session

    async with tenant_session(tenant_id) as parent:
        first, second = await asyncio.gather(
            asyncio.create_task(child()), asyncio.create_task(child())
        )

    assert first is not parent
    assert second is not parent
    assert first is not second
