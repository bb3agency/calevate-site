"""Publishing to an engine that does not host agents of ours (D-280 … D-282).

WHAT WAS WRONG. `VoiceEngine` required `create_agent` and a prompt read-back, and Cartesia
Line offers neither — its agents are programs deployed from a git repository, its
`AgentSummary` carries no prompt, greeting or model, and there is no `POST /agents` in
either of its generated clients (D-270, `docs/vendor/cartesia/agents-control-plane.md`).
`ENGINE=cartesia` was therefore a deployment where pressing Publish produced a 404 out of
the middle of a transaction that had already written half of itself — indistinguishable
from a vendor outage, so an operator retries a structural fact for ever.

WHAT IS PINNED HERE, and it is the seam rather than the adapter (the adapter's own five
refusals are in `tests/engine_capability_test.py`):

1. **`publish_agent` refuses by name, and refuses FIRST** — before the row lock and before
   the vendor, so nothing is written and no orphan can exist at the third party.
2. **Nothing is recorded as live.** `agents.status`, `engine_agent_ref` and
   `engine_agent_routes` are all untouched, which is what "a publish that silently
   succeeds is the defect we are removing" has to mean in the database.
3. **The console is told before it offers the button** —
   `PendingState.engine_verification.publishable` is False and carries the sentence,
   derived from the same capability the route refuses on. A screen and a route that
   disagree about what the platform can do is the divergence D-93 exists to remove.
4. **The drift read stays truthful.** `engine_drift_for` answers `not_published`, because
   the agent genuinely is not on the platform — no new state, no migration, and no
   `verify_publish` call against an engine with no prompt to read back.
5. **A `control_plane` engine is unaffected.** Asserted rather than assumed: a guard that
   also refused Bolna would take the whole product down to protect a vendor we do not run.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents.publishing import engine_drift_for, pending_state_for
from apps.api.agents.service import _load_agent, publish_agent
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine.capabilities import ENGINE_CAPABILITY_ABSENT, EngineCapabilityAbsentError
from apps.api.engine.fake import EXTERNAL_DEPLOYMENT_CAPABILITIES, FakeEngine
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


@pytest.fixture
def externally_deployed_engine() -> Iterator[FakeEngine]:
    """Run the platform against an engine whose agents are deployed to it from elsewhere.

    Through `apps.api.engine`'s instance cache because that is what `publish_agent` and the
    publishing reads both resolve through, and restored afterwards for `agent_voice_test`'s
    reason: a leaked descriptor makes an unrelated suite fail a long way from here.
    """
    import apps.api.engine as engine_module

    engine = FakeEngine(capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES)
    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = engine
    try:
        yield engine
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


async def _publishable_agent() -> tuple[uuid.UUID, uuid.UUID]:
    """A fresh org with a script, so a refusal below is THIS rule and not `agent_has_no_script`."""
    created = await admin_service.create_organization(
        name="Deployed Clinic",
        slug=f"dep-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Deployed Clinic.\n",
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


async def _agent_row(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM agents WHERE id = :id"),
                {"id": agent_id},
            )
        ).one()
    return str(row.status), row.engine_agent_ref


async def _route_count(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM engine_agent_routes WHERE agent_id = :id"),
                    {"id": agent_id},
                )
            ).scalar_one()
        )


async def test_publishing_is_refused_by_name_and_records_nothing(
    externally_deployed_engine: FakeEngine,
) -> None:
    """The refusal, and the absence of every claim a successful publish would have made."""
    tenant_id, agent_id = await _publishable_agent()

    with pytest.raises(EngineCapabilityAbsentError) as raised:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert raised.value.capability == "agent_hosting", (
        "the refusal does not name the capability, so a console cannot tell a platform "
        "that will never host this agent from a platform having a bad day"
    )
    problem = raised.value.as_problem()
    assert problem["type"].rsplit("/", 1)[-1] == ENGINE_CAPABILITY_ABSENT
    assert problem["remediation"], "an operator who cannot publish must be told what to do"

    status, ref = await _agent_row(tenant_id, agent_id)
    assert status == "draft", "the agent was recorded live against an engine that refused it"
    assert ref is None, (
        "an `engine_agent_ref` was written for an agent no engine holds — every inbound "
        "webhook resolver and the orphan compensator both join on that column"
    )
    assert await _route_count(tenant_id, agent_id) == 0, (
        "a routing row was written, so the receiver would map a vendor's webhook to an "
        "agent that was never created"
    )


async def test_the_refusal_comes_before_the_agent_row_is_even_read(
    externally_deployed_engine: FakeEngine,
) -> None:
    """FIRST, not last — and this is the assertion that can tell the difference.

    The adapter refuses too (`FakeEngine.create_agent` asks the same capability), so a
    check placed AFTER the vendor call would still raise, still name `agent_hosting`, and
    still leave the engine's agent store empty. Every obvious assertion passes either way,
    which is exactly the sabotage a test like this has to survive.

    What only the EARLY check produces is this: an agent with **no script at all** is
    refused for the hosting reason rather than for the script. `_assert_has_a_script` runs
    inside `_to_config`, after `_load_agent` and its row lock — so if the capability check
    moved down, this agent would be told `agent_has_no_script`, which is a fixable problem
    an operator would go and fix, and then discover the real one. Telling somebody to write
    a script for an agent that can never be published is worse than telling them nothing.

    On a real vendor the same ordering is what keeps the third party untouched, which is
    the difference between a refusal and a billed object nobody can address.
    """
    created = await admin_service.create_organization(
        name="Scriptless Clinic",
        slug=f"nos-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert raised.value.code == ENGINE_CAPABILITY_ABSENT, (
        "the publish got as far as reading the agent row before asking whether this "
        f"platform hosts agents at all — it answered `{raised.value.code}`, which sends an "
        "operator off to fix something that would not have helped"
    )
    assert externally_deployed_engine._agents == {}


async def test_the_dial_context_carries_the_floor_only_where_the_engine_needs_it() -> None:
    """`_call_prompt_for` is the one production writer of `CallContext.system_prompt`.

    IT IS TESTED DIRECTLY, and the reason is worth stating rather than hiding: no
    externally-deployed engine is publishable today (the whole point of this file), so
    `dispatch_call` cannot currently reach its own external-deployment branch — an agent
    with no `engine_agent_ref` is refused before the dial. That is a TRUE state of the
    world, recorded in OPERATIONS §2 gate 19(b), not a half-wired feature: the writer, the
    field, the guard and the adapter that reads it are all in place and all exercised, and
    what is missing is one vendor observation nobody here can make.

    So the contract is pinned where it lives. Both directions, because only the pair is
    falsifiable: a writer that always composed would put a second authority on every Bolna
    agent's script, and one that never composed would make every dial on the other shape
    refuse — the safe direction, and still a broken product.
    """
    from apps.api.agents.service import _call_prompt_for
    from calevate_shared.engine import TRUTHFUL_ANSWER_MARKER

    tenant_id, agent_id = await _publishable_agent()
    async with tenant_session(tenant_id) as session:
        row = await _load_agent(session, tenant_id, agent_id)

    hosting = FakeEngine()
    assert _call_prompt_for(hosting, tenant_id, row) is None, (
        "a control-plane engine was handed a per-call prompt, so one agent's script now "
        "has two authorities — the agent record and the dial — and they can disagree"
    )

    deployed = FakeEngine(capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES)
    prompt = _call_prompt_for(deployed, tenant_id, row)
    assert prompt is not None, (
        "no prompt is composed for an engine that holds none, so every dial there would "
        "be refused by the compliance floor — safe, and a product that cannot dial"
    )
    assert TRUTHFUL_ANSWER_MARKER in prompt, (
        "the composed per-call prompt does not carry the rule a client cannot switch off, "
        "which on this shape is the only place it could have ridden"
    )
    assert "receptionist for Deployed Clinic" in prompt, (
        "the client's own script is not in the per-call prompt, so the agent would answer "
        "truthfully about being an AI and about nothing else"
    )


async def test_the_console_is_told_before_it_offers_the_button(
    externally_deployed_engine: FakeEngine,
) -> None:
    """`publishable` is False and the headline says why, from the same capability.

    A route that refuses and a screen that offers are two answers to one question, and the
    second is what puts an operator in front of a button that cannot work. This is the
    field that stops that, and it is on the object the publish screen already reads rather
    than on a second endpoint it might not ask.
    """
    tenant_id, agent_id = await _publishable_agent()
    state = await pending_state_for(tenant_id=tenant_id, agent_id=agent_id)

    assert state.engine_verification.publishable is False
    assert state.engine_verification.confirmed is False
    assert "does not host agents built here" in state.engine_verification.headline
    # OUR vocabulary, never the vendor's (hard rule 2): which engine is running is a
    # deployment detail a client cannot act on.
    assert "fake" not in state.engine_verification.headline.lower()


async def test_the_drift_read_reports_not_published_rather_than_asking_the_engine(
    externally_deployed_engine: FakeEngine,
) -> None:
    """`not_published` is TRUE here, not a convenient fallback.

    No agent on such an engine can hold an `engine_agent_ref` — publishing refuses — so the
    sweep takes the branch that needs no new state and no migration. What it must never do
    is fall through to `verify_publish`, which would ask an engine with no prompt to read
    back and record `unreachable` about a vendor that answered perfectly.
    """
    tenant_id, agent_id = await _publishable_agent()
    drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)

    assert drift.checked is False
    assert drift.state == "not_published"
    assert drift.engine_agent_ref is None
    assert drift.truthful_answer_applied is None, (
        "a verdict about the truthful-answer rule was recorded for an agent no engine "
        "holds, which is a claim about a phone line that does not exist"
    )


async def test_an_engine_that_hosts_agents_still_publishes() -> None:
    """The other half, asserted rather than assumed.

    A guard that refused every engine would protect a vendor we do not run by taking the
    product down. The default `fake` engine is `control_plane`, so nothing about this path
    changes: the agent goes live and carries a ref.
    """
    tenant_id, agent_id = await _publishable_agent()
    async with tenant_session(tenant_id) as session:
        ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        await session.commit()

    assert ref
    status, stored = await _agent_row(tenant_id, agent_id)
    assert status == "live"
    assert stored == ref


async def test_the_pending_read_says_publishable_on_a_control_plane_engine() -> None:
    """And the console offers the button there — the same field, the other answer."""
    tenant_id, agent_id = await _publishable_agent()
    state = await pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.engine_verification.publishable is True
