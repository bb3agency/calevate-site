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
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
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
        # `preview` refuses rather than returning `[]` — the same 404-not-409 doctrine
        # the sibling test below states for approve/publish. An empty preview was
        # isolation-safe (RLS hid the chunks either way) and was indistinguishable from
        # a real source of your own with nothing in it, which is what
        # `tests/kb_review_routes_test.py::test_a_neighbours_source_is_not_found_rather_
        # than_empty` drives through the route.
        with pytest.raises(ProblemError):
            await service.preview(session, source_id)
        assert await service.list_sources(session) == []

    async with tenant_session(tenant_a) as session:
        assert len(await service.preview(session, source_id)) == 1


async def test_tenant_b_cannot_approve_or_publish_tenant_as_source() -> None:
    """Naming another tenant's source id is not authority over it.

    Both mutations are CAS UPDATEs whose WHERE clause runs under the caller's RLS, so
    the row is not merely un-updatable, it is not there. The observable result is the
    conflict/not-found ladder rather than a silent no-op, which is the difference
    between an operator seeing a refusal and an operator seeing "approved".

    The answer is 404, not 409: a conflict asserts that a row exists in some other
    state, and asserting that about a neighbour's id is an existence oracle as well as
    a false statement. `ProblemError.not_found` documents "absent" and "another
    tenant's" as deliberately the same answer.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, _ = await _tenant_with_published_agent()
    submitted = await _submit(tenant_a, agent_a, "Fees")
    source_id = uuid.UUID(str(submitted["id"]))

    async with tenant_session(tenant_b) as session:
        with pytest.raises(ProblemError) as approve_failed:
            await service.approve_source(session, source_id=source_id, approved_by=None)
    assert approve_failed.value.code == "not_found"
    assert approve_failed.value.status == 404

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
    isolation has to come from OUR side refusing to look it up.

    **THE MECHANISM CHANGED AND THE PROPERTY DID NOT (D-519).** The handle used to live in
    `kb_documents.meta`, a tenant-scoped row, and now lives in `engine_kb_routes`, which is
    GLOBALLY READABLE — it has to be, or the orphan sweep cannot ask which objects on the
    shared account no tenant claims. So the per-source reads join `kb_sources` (FORCE-RLS)
    and a foreign session sees no source row and therefore no handle. This test is what
    says the exemption bought a cross-tenant QUESTION and not a cross-tenant ANSWER.
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


# --------------------------------------------------------------------------------
# The layer RLS does not reach at all: the store the agent actually retrieves from
# --------------------------------------------------------------------------------


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, body: str) -> uuid.UUID:
    submitted = await _submit(tenant_id, agent_id, name, body)
    source_id = uuid.UUID(str(submitted["id"]))
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=source_id, approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    return source_id


async def _agent_ref(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar()
        )


async def test_the_store_the_agent_retrieves_from_holds_no_other_tenants_knowledge() -> None:
    """Isolation asked of the RETRIEVAL store, not of Postgres.

    Every other test in this file proves a row-visibility property, and row visibility
    is not where in-call retrieval happens. D-33 keeps T3 cold lookup inside the
    engine's own knowledge base, which is a store OUTSIDE our database with no row
    security, no tenant column and — on Bolna — one account holding every tenant's
    agents. So "tenant B cannot SELECT tenant A's chunk" says nothing about whether B's
    caller can be READ A's chunk down the phone, and that is the question a client asks.

    The isolation there rests on exactly one thing: the namespace key. A source is
    attached to an `engine_agent_ref`, retrieval is scoped to the agent the call is
    running on, and the two tenants' agents must therefore never share a ref. Asserted
    through the Protocol rather than by reading the fake's store, because the question
    is "what does the engine say this agent references" — `AgentSnapshot.references_kb`
    is the engine's own answer and the one D-41 already trusts.

    Note what this can and cannot settle. It settles OUR side — the ref we attach to and
    the handles we record. It cannot settle the vendor's: whether Bolna's retrieval is
    genuinely partitioned by `agent_id`, or whether a `rag_id` from another agent in the
    same account is reachable, is pilot gate 8 and is not a claim this repository can
    make. Every vendor host is egress-blocked from this environment.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, agent_b = await _tenant_with_published_agent()
    await _publish(tenant_a, agent_a, "Fees", "Tenant A charges 500 rupees for a consultation.")
    await _publish(tenant_b, agent_b, "Fees", "Tenant B charges 900 rupees for a consultation.")

    ref_a, ref_b = await _agent_ref(tenant_a, agent_a), await _agent_ref(tenant_b, agent_b)
    assert ref_a != ref_b, "two tenants share one retrieval namespace"

    engine = get_engine()
    handles_a, handles_b = await engine.list_kb(ref_a), await engine.list_kb(ref_b)
    assert handles_a and handles_b, "premise: both tenants published something"
    assert not set(handles_a) & set(handles_b), (
        f"one knowledge document is attached to both tenants' agents: "
        f"{sorted(set(handles_a) & set(handles_b))}"
    )

    # The engine's own answer, per agent: A's agent references none of B's documents.
    snapshot_a = await engine.get_agent(ref_a)
    for handle in handles_b:
        assert snapshot_a.references_kb(handle) is False, (
            "tenant A's agent references a knowledge document of tenant B's — a caller "
            "on A's line can be read B's text, and no row-level policy can see it"
        )

    # And every handle A's agent holds is one A's OWN rows account for. This is the join
    # between the two layers: `_reconcile_engine_state` refuses to publish onto an agent
    # holding a copy our rows cannot name, and that refusal is only isolation if the
    # rows it consults are the caller's own.
    async with tenant_session(tenant_a) as session:
        recorded_a = await service.recorded_handles_of_agent(session, agent_a)
    assert set(handles_a) == recorded_a
    assert not recorded_a & set(handles_b)


async def test_a_tenant_cannot_point_its_agent_at_another_tenants_retrieval_namespace() -> None:
    """The one write that would defeat the test above, driven rather than assumed.

    Namespace isolation is only as good as the binding between `engine_agent_ref` and a
    tenant, and that binding lives in `engine_agent_routes` — the table the inbound
    webhook resolves a call's tenant from. If tenant B could claim tenant A's ref, B's
    calls would route into A's agent and retrieve from A's knowledge, with every
    `kb_sources` policy still perfectly enforced.

    `engine_agent_routes` is RLS-exempt for READS (the receiver has no tenant yet when
    it resolves one) and RLS'd for WRITES, so the claim is refused rather than silently
    re-tenanting the row — the behaviour migration `c4b70e928a1f` installed. Pinned from
    the KB side because this is the table the KB's isolation actually rests on, and
    nothing here would notice if the policy were dropped.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, agent_b = await _tenant_with_published_agent()
    ref_a = await _agent_ref(tenant_a, agent_a)

    with pytest.raises(Exception) as claimed:
        async with tenant_session(tenant_b) as session:
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, created_at, updated_at) VALUES ('fake', :r, :t, :a, "
                    "true, now(), now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
                    "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id"
                ),
                {"r": ref_a, "t": tenant_b, "a": agent_b},
            )
    assert "row-level security" in str(claimed.value), claimed.value

    # A's route is untouched: the ref still resolves to A.
    async with untenanted_session() as session:
        owner = (
            await session.execute(
                text("SELECT tenant_id FROM engine_agent_routes WHERE engine_agent_ref = :r"),
                {"r": ref_a},
            )
        ).scalar()
    assert uuid.UUID(str(owner)) == tenant_a


# --------------------------------------------------------------------------------
# The claim table itself (D-519): a globally readable row must not be a globally
# writable one, and one vendor object must not have two owners
# --------------------------------------------------------------------------------


async def _claim(source_id: uuid.UUID) -> str | None:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text("SELECT engine_kb_ref FROM engine_kb_routes WHERE source_id = :s"),
                {"s": source_id},
            )
        ).scalar()


async def _published_source(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str) -> uuid.UUID:
    submitted = await _submit(tenant_id, agent_id, name)
    source_id = uuid.UUID(str(submitted["id"]))
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=source_id, approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    return source_id


async def test_a_tenant_cannot_reclaim_another_tenants_vendor_knowledge_base() -> None:
    """`engine_kb_routes` is read-exempt, and the exemption stops at reading.

    The row is the ONLY thing that says whose a vendor knowledge base is: the account is
    shared, the vendor object has no owner field, and possession of the handle is
    possession of the document. So a session that could re-tenant this row could take
    another client's knowledge base — hand it to its own agent, or delete it — with every
    policy on `kb_sources` and `kb_documents` still perfectly enforced.

    The refusal is the FORCEd `tenant_isolation` write policy migration `f1c9e0a73b46`
    installs beside the global read, which is `engine_agent_routes`' shape after
    `c4b70e928a1f` and is here for the same reason: a read-shaped exemption has twice been
    read as covering every verb.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, agent_b = await _tenant_with_published_agent()
    source_a = await _published_source(tenant_a, agent_a, "Fees")
    assert await _claim(source_a), "premise: publishing recorded a claim"

    for statement, params in (
        (
            "UPDATE engine_kb_routes SET tenant_id = :b, agent_id = :ab WHERE source_id = :s",
            {"b": tenant_b, "ab": agent_b, "s": source_a},
        ),
        ("DELETE FROM engine_kb_routes WHERE source_id = :s", {"s": source_a}),
    ):
        async with tenant_session(tenant_b) as session:
            result = await session.execute(text(statement), params)
            assert result.rowcount == 0, (
                "tenant B rewrote or destroyed tenant A's claim on a vendor knowledge base"
            )

    async with untenanted_session() as session:
        claimant = (
            await session.execute(
                text("SELECT tenant_id FROM engine_kb_routes WHERE source_id = :s"),
                {"s": source_a},
            )
        ).scalar()
    assert uuid.UUID(str(claimant)) == tenant_a


async def test_two_sources_cannot_claim_one_vendor_knowledge_base() -> None:
    """The uniqueness a JSONB key could not have.

    Every read of a handle is a read of "which vendor object is MINE", and a detach
    DELETES that object. If two sources — two tenants' sources — could record one handle,
    the first detach would delete a document the second still points at, and the second
    client's agent would go on answering from nothing while every screen of ours reported
    the version live. Nothing in the old home could refuse it; the primary key does.
    """
    tenant_a, agent_a = await _tenant_with_published_agent()
    tenant_b, agent_b = await _tenant_with_published_agent()
    source_a = await _published_source(tenant_a, agent_a, "Fees")
    handle_a = await _claim(source_a)
    assert handle_a

    submitted_b = await _submit(tenant_b, agent_b, "Fees")
    source_b = uuid.UUID(str(submitted_b["id"]))
    with pytest.raises(Exception) as collided:
        async with tenant_session(tenant_b) as session:
            await session.execute(
                text(
                    "INSERT INTO engine_kb_routes (engine, engine_kb_ref, tenant_id, "
                    "agent_id, source_id) VALUES ('fake', :ref, :t, :a, :s)"
                ),
                {"ref": handle_a, "t": tenant_b, "a": agent_b, "s": source_b},
            )
    assert "pk_engine_kb_routes" in str(collided.value), collided.value
