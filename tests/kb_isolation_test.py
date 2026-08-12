"""Tenant isolation of knowledge-base content (hard rule 1), and the one hole in it.

`rls_sweep_test` proves the generic property for every tenant table: tenant B's session
counts zero of tenant A's rows. That is READ isolation, and for `kb_sources` /
`kb_documents` it holds. This file is about the half a row-visibility policy cannot
reach.

A KB source is not addressed by its own id alone — it is addressed by `(agent_id, name,
version)`, and that triple is enforced by a UNIQUE INDEX. Unique indexes are not
subject to row-level security; PostgreSQL evaluates them across every row in the table,
visible or not. So a tenant-scoped INSERT can collide with a row its own session cannot
see, and the collision is observable. That is a write reaching across a tenant boundary
through a mechanism RLS does not mediate, which is exactly the shape hard rule 1's
"cross-tenant zero-rows test" is blind to.

The other half of the same hole is the FOREIGN KEY: `kb_sources.agent_id` references
`agents.id`, and referential-integrity checks also bypass RLS by design. Nothing in
`submit_source` checked that the named agent is the caller's own, so the tenant_id on
the row and the agent it points at could belong to different businesses.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.kb import service
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

FEES = "A consultation costs 500 rupees, payable at reception before the appointment."


async def _submit(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, body: str = FEES
) -> dict[str, object]:
    async with tenant_session(tenant_id) as session:
        return await service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )


# --------------------------------------------------------------------------------
# The hole: a write that crosses the boundary the FK and the unique index do not police
# --------------------------------------------------------------------------------


async def test_a_tenant_cannot_file_knowledge_against_another_tenants_agent() -> None:
    """The row must not exist at all — not merely be unpublishable.

    Publishing it was always refused (the publish query joins `agents`, which IS
    RLS'd, so it resolved to nothing). That refusal made the hole look harmless, and it
    is not: the row lands in `kb_sources` with tenant B's `tenant_id` and tenant A's
    `agent_id`, taking a slot in the unique index that A can no longer use, and it does
    so with no authorisation to that agent whatsoever. A row nobody may publish is
    still a row that changes what somebody else may write.
    """
    _, agent_a = await _tenant_with_published_agent()
    tenant_b, _ = await _tenant_with_published_agent()

    with pytest.raises(ProblemError) as raised:
        await _submit(tenant_b, agent_a, "Fees")
    assert raised.value.code in ("not_found", "agent_not_found")


async def test_one_tenant_cannot_wedge_another_tenants_source_name() -> None:
    """The consequence, stated as the client experiences it.

    Tenant B names tenant A's agent first; tenant A then submits its own knowledge
    under an ordinary name and the INSERT collides on `uq_kb_sources_agent_id_name_
    version` — a unique index, evaluated over rows A's session cannot see. Before the
    check in `submit_source`, A got a 500 from a row that was not theirs, forever, for
    every version number B had taken. It is also an existence oracle: the error tells B
    whether A already has a source of that name at that version.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, _ = await _tenant_with_published_agent()

    with pytest.raises(ProblemError):
        await _submit(tenant_b, agent_a, "Fees")

    # A's own submission must be unaffected by anything B did.
    mine = await _submit(tenant_a, agent_a, "Fees")
    assert mine["version"] == 1
    assert mine["status"] == "pending_approval"


async def test_the_agent_check_reads_agents_under_the_callers_own_rls() -> None:
    """The check must be a tenant-scoped read, not a `tenant_id` comparison passed in
    by the caller. `submit_source` receives `tenant_id` as an argument; a check that
    compares two arguments to each other proves nothing about the database."""
    tenant_a, _ = await _tenant_with_published_agent()
    # A nonexistent agent is refused for the same reason a foreign one is: it is not
    # visible in this tenant's session.
    with pytest.raises(ProblemError):
        await _submit(tenant_a, uuid.uuid4(), "Fees")


# --------------------------------------------------------------------------------
# The half that already holds — pinned so it keeps holding
# --------------------------------------------------------------------------------


async def test_tenant_b_reads_none_of_tenant_as_knowledge() -> None:
    """Read isolation through the SERVICE functions, not just the tables.

    `preview` and `list_sources` take no tenant argument at all — they are pure RLS
    plays. That is fine, and this is the test that says so, because a future refactor
    that adds an explicit filter to one and forgets the other would otherwise be
    invisible.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, _ = await _tenant_with_published_agent()
    submitted = await _submit(
        tenant_a, agent_a, "Staff", "Dr Rao consults on Tuesdays and Thursdays after 4pm."
    )
    source_id = uuid.UUID(str(submitted["id"]))

    async with tenant_session(tenant_b) as session:
        assert await service.preview(session, source_id) == []
        assert await service.list_sources(session) == []

    async with tenant_session(tenant_a) as session:
        assert len(await service.preview(session, source_id)) == 1


async def test_tenant_b_cannot_approve_or_publish_tenant_as_source() -> None:
    """Naming another tenant's source id is not authority over it.

    Both mutations are CAS UPDATEs whose WHERE clause runs under the caller's RLS, so
    the row is not merely un-updatable, it is not there. The observable result is the
    conflict/not-found ladder rather than a silent no-op, which is the difference
    between an operator seeing a refusal and an operator seeing "approved".
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, _ = await _tenant_with_published_agent()
    submitted = await _submit(tenant_a, agent_a, "Fees")
    source_id = uuid.UUID(str(submitted["id"]))

    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError) as approve_failed:
            await service.approve_source(session, source_id=source_id, approved_by=None)
    assert approve_failed.value.code == "kb_not_pending"

    # And it really was not approved — A's own session still sees it pending.
    async with tenant_session(tenant_a) as session:
        status = (
            await session.execute(
                text("SELECT status, approved_at FROM kb_sources WHERE id = :s"), {"s": source_id}
            )
        ).first()
    assert status is not None and status[0] == "pending_approval" and status[1] is None

    async with tenant_session(tenant_a) as session:
        await service.approve_source(session, source_id=source_id, approved_by=None)

    with pytest.raises(ProblemError) as publish_failed:
        async with tenant_session(tenant_b) as session:
            await service.publish_source(session, tenant_id=tenant_b, source_id=source_id)
    assert publish_failed.value.code == "not_found"


async def test_the_vendor_handle_is_not_a_capability_another_tenant_can_use() -> None:
    """The vendor's namespace is flat; ours must not be.

    `attach_kb` returns the ENGINE's handle for the attached copy, and that handle is
    the only thing that can delete it. Bolna files every tenant's knowledge bases in one
    account, so possession of a handle is possession of another client's knowledge — the
    isolation has to come from OUR side refusing to look it up, which it does by keeping
    the handle in `kb_documents.meta`, a tenant-scoped row.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, _ = await _tenant_with_published_agent()
    submitted = await _submit(tenant_a, agent_a, "Fees")
    source_id = uuid.UUID(str(submitted["id"]))
    async with tenant_session(tenant_a) as session:
        await service.approve_source(session, source_id=source_id, approved_by=None)
        await service.publish_source(session, tenant_id=tenant_a, source_id=source_id)

    async with tenant_session(tenant_a) as session:
        handle = await service._engine_kb_ref(session, source_id)
    assert handle, "the publish recorded no engine handle"

    async with tenant_session(tenant_b) as session:
        assert await service._engine_kb_ref(session, source_id) is None, (
            "another tenant can read the vendor handle that deletes this client's knowledge"
        )
