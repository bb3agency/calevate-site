"""The adoption job (D-1019): each agent's own engine agent goes to what uses it, or is retired.

1. Its table is invisible across tenants (hard rule 1).
2. One draft line with numbers adopts the agent's engine agent in place: the same vendor
   object, renamed to the line's tag, the number still bound to it and never unbound; a line
   nobody edited takes the agent's applied script. One running campaign adopts it the same way.
3. One nothing uses is retired through the outbox; the agent's knowledge claims move to the
   adopter or go with the vendor agent.
4. Anything else is held, alarmed once per cause; a failed read-back rolls everything back and
   waits. A rerun is idempotent, a dry run writes nothing, and nothing runs while agents still
   get an engine agent of their own.
5. Running script tests are concluded first (E2). The admin console runs it for one client,
   the sweep only when its setting is on.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import engine_retirement, prompts
from apps.api.agents import service as agents_service
from apps.api.agents.engine_retirement import RetirementRun, retire_agent, retire_for_tenant
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.api.inbound import lines
from apps.api.inbound.publish import route_numbers
from apps.api.main import app
from apps.workers import agent_engine_retirement
from calevate_shared.call_script import CallScript
from calevate_shared.engine import AgentConfig, EngineAgentRef
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine, _move, _number, _tenant, _write_script

pytestmark = pytest.mark.rls

SCRIPT = CallScript(opening_line="Namaste, Lifecycle Clinic. How can I help you today?")
#: The real check, before the fixture below replaces it for every other test.
_STILL_GET_THEIR_OWN = engine_retirement.agents_still_get_their_own


@pytest.fixture(autouse=True)
def _creation_off(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Agents no longer get an engine agent of their own (WP-B's setting off), and every
    alarm the job raises is recorded."""
    monkeypatch.setattr(engine_retirement, "agents_still_get_their_own", lambda: False)
    raised: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        engine_retirement, "alert", lambda _stage, code, **kw: raised.append((code, kw))
    )
    return raised


async def _live_agent(direction: str = "inbound", *, numbers: int = 0) -> tuple[UUID, UUID]:
    tenant_id, agent_id, token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = :d WHERE id = :a"), {"d": direction, "a": agent_id}
        )
    for _ in range(numbers):
        await _number(tenant_id, agent_id, ref=f"num_{uuid.uuid4().hex[:10]}")
    await _write_script(tenant_id, agent_id)
    code, body = await _move(token, agent_id, "activate")
    assert code == 200, body
    return tenant_id, agent_id


async def _agent_ref(tenant_id: UUID, agent_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    return None if value is None else str(value)


async def _numbers(tenant_id: UUID) -> list[tuple[UUID, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id, engine_number_ref FROM phone_numbers ORDER BY created_at, id")
            )
        ).all()
    return [(UUID(str(r[0])), str(r[1])) for r in rows]


async def _draft_line(tenant_id: UUID, agent_id: UUID, number_id: UUID, *, edit: bool) -> UUID:
    """A draft line holding `number_id`, as the D-997 backfill made them: answered by the
    agent's own engine agent until it is put live."""
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )
        if edit:
            await lines.save_script(session, line_id, SCRIPT)
        else:
            await session.execute(
                text("UPDATE inbound_lines SET script = CAST(:s AS jsonb) WHERE id = :l"),
                {"s": SCRIPT.model_dump_json(), "l": line_id},
            )
        await lines.assign_number(session, line_id, number_id)
    await route_numbers(tenant_id=tenant_id, line_id=line_id)
    return line_id


async def _record(tenant_id: UUID, agent_id: UUID) -> tuple[Any, ...] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT outcome, holder_id, reason, old_ref FROM agent_engine_retirements "
                    "WHERE agent_id = :a"
                ),
                {"a": agent_id},
            )
        ).first()
    return None if row is None else tuple(row)


def _count_unbinds(engine: FakeEngine, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    unbound: list[str] = []
    original = engine.unbind_inbound_number

    async def spy(number: Any) -> None:
        unbound.append(str(number.engine_number_ref))
        await original(number)

    monkeypatch.setattr(engine, "unbind_inbound_number", spy)
    return unbound


# --- 1. hard rule 1 -------------------------------------------------------------------


async def test_another_tenant_reads_zero_rows() -> None:
    mine, mine_agent, _ = await _tenant()
    theirs, _, _ = await _tenant()
    async with tenant_session(mine) as session:
        await session.execute(
            text(
                "INSERT INTO agent_engine_retirements (id, tenant_id, agent_id, old_ref, outcome) "
                "VALUES (:i, :t, :a, 'fakeagent_x', 'retired')"
            ),
            {"i": uuid7(), "t": mine, "a": mine_agent},
        )
    async with tenant_session(theirs) as session:
        seen = (
            await session.execute(text("SELECT count(*) FROM agent_engine_retirements"))
        ).scalar()
    assert seen == 0
    with pytest.raises(Exception, match="row-level security"):
        async with tenant_session(theirs) as session:
            await session.execute(
                text(
                    "INSERT INTO agent_engine_retirements (id, tenant_id, agent_id, old_ref, "
                    "outcome) VALUES (:i, :t, :a, 'fakeagent_y', 'held')"
                ),
                {"i": uuid7(), "t": mine, "a": mine_agent},
            )


# --- 2. adoption ----------------------------------------------------------------------


async def test_a_draft_line_adopts_the_agents_engine_agent_with_no_unbind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent(numbers=1)
    ref = await _agent_ref(tenant_id, agent_id)
    assert ref is not None
    ((number_id, number_ref),) = await _numbers(tenant_id)
    line_id = await _draft_line(tenant_id, agent_id, number_id, edit=True)
    assert engine.inbound_agent_for(number_ref) == ref, "the draft line rang the agent before"
    agent_tag = engine.name_tag_of(ref)
    unbound = _count_unbinds(engine, monkeypatch)

    run = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)

    assert [(a.outcome, a.holder_id) for a in run.agents] == [("adopted_line", line_id)]
    assert unbound == [], "adopting the engine agent unbound a number"
    assert engine.inbound_agent_for(number_ref) == ref, "the number moved off the same object"
    assert engine.name_tag_of(ref) != agent_tag, "the vendor agent kept the agent's tag"
    assert "Front desk" in engine._agents[ref].name
    assert await _agent_ref(tenant_id, agent_id) is None
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
        route = (
            await session.execute(
                text("SELECT inbound_line_id FROM engine_agent_routes WHERE engine_agent_ref = :r"),
                {"r": ref},
            )
        ).scalar_one()
    assert line.live and line.engine_agent_ref == ref
    assert route == line_id
    assert await _record(tenant_id, agent_id) == ("adopted_line", line_id, None, ref)

    # A publish for the line's holder now finds the adopted object by its tag.
    assert await engine.create_agent(engine._agents[ref]) == ref

    # Idempotent: the agent holds no ref, so a rerun has nothing to do.
    again = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)
    assert again.agents == ()
    assert await _record(tenant_id, agent_id) == ("adopted_line", line_id, None, ref)


async def test_a_line_nobody_edited_takes_the_agents_applied_script() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent(numbers=1)
    ((number_id, _),) = await _numbers(tenant_id)
    line_id = await _draft_line(tenant_id, agent_id, number_id, edit=False)
    applied = CallScript(opening_line="Namaste, the applied opening of this agent.")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE prompt_versions SET structured_script = CAST(:s AS jsonb) WHERE id = ("
                "SELECT COALESCE(live_prompt_id, system_prompt_id) FROM agents WHERE id = :a)"
            ),
            {"s": applied.model_dump_json(), "a": agent_id},
        )

    await retire_for_tenant(tenant_id=tenant_id, dry_run=False)

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT script, version FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).one()
    assert CallScript.model_validate(row.script).opening_line == applied.opening_line
    assert row.version == 1


async def test_a_running_campaign_dialling_through_the_agent_adopts_it() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent("outbound")
    ref = await _agent_ref(tenant_id, agent_id)
    assert ref is not None
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :t, :a, 'Check-ups', 'service', 'running')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id},
        )

    run = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)

    assert [(a.outcome, a.holder_id) for a in run.agents] == [("adopted_campaign", campaign_id)]
    assert engine._agents[ref].holder == f"campaign:{campaign_id}"
    assert await _agent_ref(tenant_id, agent_id) is None
    async with tenant_session(tenant_id) as session:
        held = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert held == ref


# --- 3. retirement and knowledge claims ------------------------------------------------


async def test_an_engine_agent_nothing_uses_is_retired_through_the_outbox() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    ref = await _agent_ref(tenant_id, agent_id)

    run = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)

    assert [a.outcome for a in run.agents] == ["retired"]
    assert await _agent_ref(tenant_id, agent_id) is None
    assert ref in engine._agents, "the vendor agent was deleted before the commit"
    async with tenant_session(tenant_id) as session:
        owed = (
            (
                await session.execute(
                    text(
                        "SELECT payload->>'old_ref' FROM outbox_messages WHERE job = :j "
                        "AND payload->>'agent_id' = :a"
                    ),
                    {"j": agents_service.RETIRE_MOVED_AGENT_JOB, "a": str(agent_id)},
                )
            )
            .scalars()
            .all()
        )
    assert owed == [ref]


async def _own_claim(tenant_id: UUID, agent_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_kb_routes (engine, engine_kb_ref, tenant_id, agent_id, "
                "source_id) VALUES ('fake', :r, :t, :a, :s)"
            ),
            {"r": f"kb_{uuid.uuid4().hex}", "t": tenant_id, "a": agent_id, "s": uuid.uuid4()},
        )


async def _claims(tenant_id: UUID, agent_id: UUID) -> list[tuple[Any, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text("SELECT inbound_line_id, campaign_id FROM engine_kb_routes WHERE agent_id = :a"),
            {"a": agent_id},
        )
        return [tuple(r) for r in rows.all()]


async def test_the_agents_claims_move_to_the_adopter_or_go_with_the_vendor_agent() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    ref = await _agent_ref(tenant_id, agent_id)
    assert ref is not None
    line_id = uuid7()
    await _own_claim(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await agents_service.hand_over_engine_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, ref=ref, line_id=line_id
        )
    assert await _claims(tenant_id, agent_id) == [(line_id, None)]
    assert await _agent_ref(tenant_id, agent_id) is None

    other_tenant, other_agent = await _live_agent()
    other_ref = await _agent_ref(other_tenant, other_agent)
    assert other_ref is not None
    await _own_claim(other_tenant, other_agent)
    async with tenant_session(other_tenant) as session:
        await agents_service.hand_over_engine_agent(
            session, tenant_id=other_tenant, agent_id=other_agent, ref=other_ref
        )
    assert await _claims(other_tenant, other_agent) == []


# --- 4. held, rolled back, dry run, refused --------------------------------------------


async def test_two_draft_lines_hold_it_and_alarm_once(
    _creation_off: list[tuple[str, dict[str, Any]]],
) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent(numbers=2)
    ref = await _agent_ref(tenant_id, agent_id)
    for number_id, _ in await _numbers(tenant_id):
        await _draft_line(tenant_id, agent_id, number_id, edit=True)

    first = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)
    second = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)

    assert [a.reason for a in first.agents + second.agents] == [engine_retirement.SEVERAL_USES] * 2
    assert await _agent_ref(tenant_id, agent_id) == ref, "a held agent lost its engine agent"
    assert [code for code, _ in _creation_off] == ["agent_engine_agent_held"]
    assert await _record(tenant_id, agent_id) == ("held", None, "several_uses", ref)


async def test_a_number_on_no_line_holds_it() -> None:
    _fresh_engine()
    tenant_id, _agent_id = await _live_agent(numbers=1)
    run = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)
    assert [(a.outcome, a.reason) for a in run.agents] == [
        ("held", engine_retirement.NUMBER_WITHOUT_LINE)
    ]


async def test_a_developer_workspace_ref_in_use_is_held(monkeypatch: pytest.MonkeyPatch) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent("outbound")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :t, :a, 'Check-ups', 'service', 'paused')"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id},
        )
    monkeypatch.setattr(engine_retirement, "engine_has_workspaces", lambda: True)
    run = await retire_for_tenant(tenant_id=tenant_id, dry_run=True)
    assert [(a.outcome, a.reason) for a in run.agents] == [
        ("held", engine_retirement.DEVELOPER_WORKSPACE_IN_USE)
    ]


class _StaleUpdateEngine(FakeEngine):
    """Accepts an update and keeps the script it had: the read-back proves it not applied."""

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        before = self._agents[ref]
        await super().update_agent(ref, cfg)
        self._agents[ref] = cfg.model_copy(update={"system_prompt": before.system_prompt})


async def test_a_failed_read_back_rolls_everything_back_and_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.api.engine as engine_module

    _fresh_engine()
    tenant_id, agent_id = await _live_agent(numbers=1)
    ref = await _agent_ref(tenant_id, agent_id)
    assert ref is not None
    ((number_id, _),) = await _numbers(tenant_id)
    line_id = await _draft_line(tenant_id, agent_id, number_id, edit=True)
    stale = _StaleUpdateEngine()
    stale._agents.update(engine_module._instances["fake"]._agents)
    monkeypatch.setitem(engine_module._instances, "fake", stale)

    run = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)

    assert [(a.outcome, a.reason) for a in run.agents] == [
        ("waiting", "engine_publish_not_applied")
    ]
    assert await _agent_ref(tenant_id, agent_id) == ref
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert not line.live and line.engine_agent_ref is None
    assert await _record(tenant_id, agent_id) == (
        "waiting",
        None,
        "engine_publish_not_applied",
        ref,
    )


async def test_a_dry_run_reports_and_writes_nothing() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent(numbers=1)
    ref = await _agent_ref(tenant_id, agent_id)
    ((number_id, _),) = await _numbers(tenant_id)
    line_id = await _draft_line(tenant_id, agent_id, number_id, edit=True)

    run = await retire_for_tenant(tenant_id=tenant_id, dry_run=True)

    assert run.dry_run is True
    assert [(a.outcome, a.holder_id) for a in run.agents] == [("adopted_line", line_id)]
    assert await _agent_ref(tenant_id, agent_id) == ref
    assert await _record(tenant_id, agent_id) is None


async def test_a_real_run_is_refused_while_agents_still_get_their_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_retirement, "agents_still_get_their_own", lambda: True)
    with pytest.raises(ProblemError) as refused:
        await retire_for_tenant(tenant_id=uuid.uuid4(), dry_run=False)
    assert refused.value.code == "agents_still_hold_engine_agents"


def test_agents_still_get_their_own_until_the_setting_says_otherwise() -> None:
    """`agents_hold_engine_agent` is on by default in release R1, and absent counts as on."""
    assert _STILL_GET_THEIR_OWN() is True


async def test_a_ref_that_changed_before_the_lock_waits() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    done = await retire_agent(
        tenant_id=tenant_id, agent_id=agent_id, ref="fakeagent_stale", dry_run=False
    )
    assert (done.outcome, done.reason) == ("waiting", engine_retirement.REF_CHANGED)
    assert await _agent_ref(tenant_id, agent_id) is not None


# --- 5. experiments first, the console, the sweep -------------------------------------


async def test_a_running_script_test_is_concluded_first() -> None:
    from tests.prompt_experiment_test import start_running_test

    _fresh_engine()
    tenant_id, agent_id = await _live_agent("outbound")
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Lifecycle Clinic. Book now.\n",
            notes="challenger",
            created_by=None,
        )
    experiment_id = await start_running_test(
        tenant_id, agent_id, control_version=1, challenger_version=2
    )

    run = await retire_for_tenant(tenant_id=tenant_id, dry_run=False)

    assert [(a.outcome, a.experiments_concluded) for a in run.agents] == [
        ("retired", (experiment_id,))
    ]
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status, promoted_variant_id FROM prompt_experiments WHERE id = :e"),
                {"e": experiment_id},
            )
        ).one()
    assert tuple(status) == ("concluded", None)


async def _admin_headers() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def test_the_console_runs_it_for_one_client_dry_run_first() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    url = f"/v1/admin/engine-workspaces/tenants/{tenant_id}/agent-engine-retirement"
    headers = await _admin_headers()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        dry = await http.post(url, json={}, headers=headers)
        unconfirmed = await http.post(url, json={"dry_run": False}, headers=headers)
        real = await http.post(
            url,
            json={"dry_run": False},
            headers={**headers, "X-Confirm-Action": f"retire_agent_engine_agents:{tenant_id}"},
        )
        missing = await http.post(
            f"/v1/admin/engine-workspaces/tenants/{uuid.uuid4()}/agent-engine-retirement",
            json={},
            headers=headers,
        )
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True
    assert [a["outcome"] for a in dry.json()["agents"]] == ["retired"]
    assert unconfirmed.status_code == 403, unconfirmed.text
    assert real.status_code == 200, real.text
    assert [a["agent_id"] for a in real.json()["agents"]] == [str(agent_id)]
    assert await _agent_ref(tenant_id, agent_id) is None
    assert missing.status_code == 404
    async with tenant_session(tenant_id) as session:
        audited = (
            (
                await session.execute(
                    text(
                        "SELECT id FROM audit_log WHERE action = 'agent.engine_agents_retired' "
                        "AND tenant_id = :t"
                    ),
                    {"t": tenant_id},
                )
            )
            .scalars()
            .all()
        )
    assert len(audited) == 1


async def test_the_sweep_runs_only_when_its_setting_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    assert get_settings().agent_engine_retirement_sweep is False
    assert await agent_engine_retirement.sweep_agent_engine_retirement({}) == "off"
    assert await _agent_ref(tenant_id, agent_id) is not None

    monkeypatch.setattr(get_settings(), "agent_engine_retirement_sweep", True)
    monkeypatch.setattr(agent_engine_retirement, "agents_still_get_their_own", lambda: True)
    held = await agent_engine_retirement.sweep_agent_engine_retirement({})
    assert held == "agents_still_hold_engine_agents"

    # Every other account in this shared database is walked too; only this one is acted on.
    async def only_this_one(*, tenant_id: UUID, dry_run: bool) -> RetirementRun:
        if tenant_id != mine:
            return RetirementRun(tenant_id=tenant_id, dry_run=dry_run, agents=())
        return await retire_for_tenant(tenant_id=tenant_id, dry_run=dry_run)

    mine = tenant_id
    monkeypatch.setattr(agent_engine_retirement, "agents_still_get_their_own", lambda: False)
    monkeypatch.setattr(agent_engine_retirement, "retire_for_tenant", only_this_one)
    swept = await agent_engine_retirement.sweep_agent_engine_retirement({})
    assert "failed=0" in swept and "retired=1" in swept, swept
    assert await _agent_ref(tenant_id, agent_id) is None


async def test_the_sweep_reaches_an_account_whose_routes_are_all_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An erased account's routes are deactivated while its agent still holds a ref.
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE engine_agent_routes SET active = false WHERE tenant_id = :t"),
            {"t": tenant_id},
        )

    async def only_this_one(*, tenant_id: UUID, dry_run: bool) -> RetirementRun:
        if tenant_id != mine:
            return RetirementRun(tenant_id=tenant_id, dry_run=dry_run, agents=())
        return await retire_for_tenant(tenant_id=tenant_id, dry_run=dry_run)

    mine = tenant_id
    monkeypatch.setattr(get_settings(), "agent_engine_retirement_sweep", True)
    monkeypatch.setattr(agent_engine_retirement, "agents_still_get_their_own", lambda: False)
    monkeypatch.setattr(agent_engine_retirement, "retire_for_tenant", only_this_one)
    swept = await agent_engine_retirement.sweep_agent_engine_retirement({})
    assert "failed=0" in swept and "retired=1" in swept, swept
    assert await _agent_ref(tenant_id, agent_id) is None
