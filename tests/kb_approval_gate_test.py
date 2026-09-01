"""The approval gate, attacked from the three directions that are not "publish early".

`kb_workflow_test` proves the front door is locked: submit, then publish, and the
publish is refused with `kb_not_approved`. That is the case everyone thinks of, and it
is not the one that would let unapproved text reach a caller.

The gate's real statement is narrower than "approved sources publish": it is that
`approved_at IS NOT NULL` is the eligibility fact, deliberately in place of
`status = 'approved'`, because FLOWS §7's rollback republishes a row this same function
rewrote to `archived`. Widening eligibility to a second status is exactly the kind of
change that quietly admits a fourth case nobody enumerated, so the widening is pinned
here from the inside: a row wearing the archived status without the approval fact is
still refused.

The other two directions are lateral. An agent's knowledge is keyed by `(agent_id,
name)`, and a tenant usually has more than one agent — so "approved for agent B" must
not be authority over agent A, and publishing agent A's "Fees" must not withdraw agent
B's "Fees". Neither is covered by any test that uses a single agent.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.kb import service
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent, give_agent_a_script


async def _second_published_agent(tenant_id: uuid.UUID) -> uuid.UUID:
    """A second live agent in the SAME tenant — the normal shape of a client with an
    inbound receptionist and an outbound campaign agent."""
    agent_id = uuid.uuid4()
    ref = f"fakeagent_kb2_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, language_primary, "
                "disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, engine, engine_agent_ref, created_at, updated_at) "
                "VALUES (:id, :t, 'Second', 'outbound', 'live', 'te-IN', 'This is an AI "
                "assistant calling on behalf of the clinic.', 'This is an AI assistant calling "
                "on behalf of the clinic.', 'This call is being recorded.', 'I keep a short "
                "note of what you ask about.', 'fake', :r, now(), now())"
            ),
            {"id": agent_id, "t": tenant_id, "r": ref},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) VALUES ('fake', :r, :t, :a, "
                "true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    # A live agent has an applied script; see `give_agent_a_script`.
    await give_agent_a_script(tenant_id, agent_id)
    return agent_id


async def _submit(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, body: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
    return uuid.UUID(str(submitted["id"]))


async def _attached_count(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    return len(await get_engine().list_kb(str(ref)))


# --- The eligibility fact, and the status it is deliberately not ---------------------


async def test_a_rejected_source_can_never_be_published() -> None:
    """Rejection is the gate's whole output when a human says no.

    It works because rejection never writes `approved_at`, not because it writes
    `status = 'rejected'` — which matters, since `status` is the field publish stopped
    trusting. A rejected source must stay unpublishable for the rest of its life, and
    resubmitting is how a client tries again.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit(
        tenant_id, agent_id, "Fees", "A consultation costs 500 rupees, cash only."
    )
    async with tenant_session(tenant_id) as session:
        await service.reject_source(session, source_id=source_id, reason="Prices are out of date.")

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    assert raised.value.code == "kb_not_approved"
    assert await _attached_count(tenant_id, agent_id) == 0

    # And it cannot be smuggled through by approving it afterwards: approval is a CAS on
    # `pending_approval`, so a rejected row is not a candidate. The refusal now NAMES the
    # state it found — "rejected" is what the reviewer needs to know, and it is the
    # branch that must stay distinct from "already approved", which is a success.
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as approve_failed:
            await service.approve_source(session, source_id=source_id, approved_by=None)
    assert approve_failed.value.code == "invalid_status_transition"
    assert approve_failed.value.status == 409
    assert "rejected" in approve_failed.value.detail


async def test_the_archived_status_alone_does_not_make_a_source_publishable() -> None:
    """The hole the rollback widening could have opened, closed from the inside.

    `publish_source` accepts `status IN ('approved', 'archived')` so that FLOWS §7's
    rollback can republish a row the publish path itself archived. Read carelessly that
    says "archived rows publish", and archived is a status other code paths could set.
    The eligibility fact is `approved_at`, and this proves the status is only ever a
    secondary filter over it.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE kb_sources SET status = 'archived' WHERE id = :s"), {"s": source_id}
        )

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    assert raised.value.code == "kb_not_approved"
    assert await _attached_count(tenant_id, agent_id) == 0


async def test_a_rollback_target_is_a_version_a_human_actually_approved() -> None:
    """The rollback path itself, stated as an approval property rather than a mechanic:
    every version it can restore carries an `approved_at` that a human wrote, and the
    archive step never invents one."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    v1 = await _submit(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=v1, approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=v1)
    v2 = await _submit(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=v2, approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=v2)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT version, status, approved_at IS NOT NULL FROM kb_sources "
                    "WHERE agent_id = :a AND name = 'Fees' ORDER BY version"
                ),
                {"a": agent_id},
            )
        ).all()
    assert [(r[1], r[2]) for r in rows] == [("archived", True), ("approved", True)]

    # The rollback goes through, and lands on the version a human signed off on.
    async with tenant_session(tenant_id) as session:
        assert await service.publish_source(session, tenant_id=tenant_id, source_id=v1) == 1


# --- Lateral: a second agent in the same tenant --------------------------------------


async def test_knowledge_approved_for_one_agent_does_not_reach_another() -> None:
    """`(agent_id, name)` is the address of a knowledge source, and the second agent is
    where a name-only assumption would show up. An approved, published source on the
    second agent must leave the first agent's engine copy untouched."""
    tenant_id, agent_one = await _tenant_with_published_agent()
    agent_two = await _second_published_agent(tenant_id)

    first = await _submit(tenant_id, agent_one, "Fees", "Agent one charges 500 rupees.")
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=first, approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=first)

    # Same NAME, other agent, never approved.
    second = await _submit(tenant_id, agent_two, "Fees", "Agent two charges 900 rupees.")
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await service.publish_source(session, tenant_id=tenant_id, source_id=second)
    assert raised.value.code == "kb_not_approved"

    assert await _attached_count(tenant_id, agent_one) == 1
    assert await _attached_count(tenant_id, agent_two) == 0


async def test_publishing_one_agents_source_does_not_withdraw_the_other_agents() -> None:
    """The supersession query is scoped by agent as well as by name. If it were not, a
    client's second agent would silently lose its knowledge every time the first one was
    updated — and our tables would report both as live."""
    tenant_id, agent_one = await _tenant_with_published_agent()
    agent_two = await _second_published_agent(tenant_id)

    for agent_id, body in ((agent_one, "Agent one charges 500."), (agent_two, "Agent two: 900.")):
        source_id = await _submit(tenant_id, agent_id, "Fees", body + " Payable at reception.")
        async with tenant_session(tenant_id) as session:
            await service.approve_source(session, source_id=source_id, approved_by=None)
            await service.publish_source(session, tenant_id=tenant_id, source_id=source_id)

    # A second version for agent one only.
    v2 = await _submit(tenant_id, agent_one, "Fees", "Agent one now charges 800 at reception.")
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=v2, approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=v2)

    assert await _attached_count(tenant_id, agent_one) == 1
    assert await _attached_count(tenant_id, agent_two) == 1, (
        "updating one agent's knowledge withdrew another agent's"
    )


async def test_a_draft_agent_never_receives_knowledge_even_when_approved() -> None:
    """The gate's other side: approval is necessary, not sufficient. An agent the engine
    has never seen has no handle to attach to, and pushing anyway would be a no-op our
    tables recorded as a publish."""
    created = await admin_service.create_organization(
        name="Draft Clinic",
        slug=f"gate-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    source_id = await _submit(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=source_id, approved_by=None)
        with pytest.raises(ProblemError) as raised:
            await service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    assert raised.value.code == "agent_not_published"
