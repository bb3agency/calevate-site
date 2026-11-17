"""Each campaign speaks through its own engine agent (D-1003, Phase 2 of the campaign plan).

1. A campaign's engine agent is its own: published beside its agent's, never over it, with the
   campaign's script and settings, routed for intake; two campaigns share one voice.
2. A dial for the campaign rings that engine agent, records it on the call, and intake stamps
   the campaign from the route (never on a test call).
3. The truthful-answer verdict is read per holder: a campaign that lost the rule stops its own
   calls, not its agent's.
4. Ending a campaign retires its engine agent; the drift sweep does not compare a retired one.
5. The workspace allowance refuses plainly; the deploy sweep gives an agent its own script back.
6. "What it notes" is the campaign's when it has one, saved under a compare-and-set, and
   invisible to another account.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents.publishing import engine_drift_for
from apps.api.agents.reconciliation import TRUTHFUL_ANSWER_MISSING
from apps.api.campaigns import engine_agent, notes
from apps.api.campaigns.controls import stop_campaign
from apps.api.compliance.service import (
    TRUTHFUL_ANSWER_DRIFT_RULE,
    truthful_answer_drift_blocker,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.campaign_engine_agents import own_script_version
from apps.workers.pipeline import _STAMP_CAMPAIGN_SQL
from calevate_shared.call_script import CallScript
from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine, _move, _number, _tenant, _write_script

pytestmark = pytest.mark.rls

SCRIPT = CallScript(opening_line="Namaste, this is Lifecycle Clinic calling about your check-up.")
OTHER = CallScript(opening_line="Namaste, Lifecycle Clinic here about the new evening hours.")


async def _live_agent() -> tuple[UUID, UUID]:
    tenant_id, agent_id, token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'both' WHERE id = :a"), {"a": agent_id}
        )
    await _write_script(tenant_id, agent_id)
    code, body = await _move(token, agent_id, "activate")
    assert code == 200, body
    return tenant_id, agent_id


async def _campaign(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    script: CallScript | None = SCRIPT,
    status: str = "draft",
    overrides: dict[str, Any] | None = None,
) -> UUID:
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, script, "
                "status, settings_overrides) VALUES (:id, :t, :a, :n, 'service', "
                "CAST(:s AS jsonb), :st, CAST(:o AS jsonb))"
            ),
            {
                "id": campaign_id,
                "t": tenant_id,
                "a": agent_id,
                "n": f"Calls {campaign_id.hex[:6]}",
                "s": None if script is None else script.model_dump_json(),
                "st": status,
                "o": None if overrides is None else __import__("json").dumps(overrides),
            },
        )
    return campaign_id


async def _publish(tenant_id: UUID, campaign_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )


async def _agent_ref(tenant_id: UUID, agent_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert isinstance(ref, str)
    return ref


async def test_a_campaigns_engine_agent_is_its_own_and_two_share_one_voice() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    agent_ref = await _agent_ref(tenant_id, agent_id)
    agent_prompt = engine._agents[agent_ref].system_prompt
    first = await _campaign(tenant_id, agent_id, overrides={"max_call_duration_s": 300})
    second = await _campaign(tenant_id, agent_id, script=OTHER, status="running")

    ref_one = await _publish(tenant_id, first)
    ref_two = await _publish(tenant_id, second)

    assert len({agent_ref, ref_one, ref_two}) == 3, "a campaign was written over another holder"
    assert engine._agents[agent_ref].system_prompt == agent_prompt, "the agent's script moved"
    one, two = engine._agents[ref_one], engine._agents[ref_two]
    assert "check-up" in one.system_prompt and "evening hours" in two.system_prompt
    assert one.direction == "outbound" and one.max_call_duration_s == 300
    assert engine._agents[agent_ref].max_call_duration_s != 300, "an override reached the agent"
    async with tenant_session(tenant_id) as session:
        route = (
            await session.execute(
                text(
                    "SELECT agent_id, campaign_id FROM engine_agent_routes "
                    "WHERE engine_agent_ref = :r"
                ),
                {"r": ref_one},
            )
        ).one()
        stored = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :c"), {"c": first}
            )
        ).scalar_one()
    assert (route.agent_id, route.campaign_id) == (agent_id, first)
    assert stored == ref_one
    # A second publish updates the same engine agent rather than making another.
    assert await _publish(tenant_id, first) == ref_one


async def test_a_campaign_with_nothing_of_its_own_dials_through_its_agent() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, script=None, status="running")
    assert (
        await engine_agent.put_campaign_live(tenant_id=tenant_id, campaign_id=campaign_id) is None
    )
    assert await engine_agent.dial_for(tenant_id=tenant_id, campaign_id=campaign_id) is None


async def test_a_campaign_dial_rings_its_engine_agent_and_intake_stamps_the_campaign() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _number(tenant_id, agent_id, ref="num_campaign_1")
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    via = await engine_agent.dial_for(tenant_id=tenant_id, campaign_id=campaign_id)
    assert via is not None

    async with tenant_session(tenant_id) as session:
        handle = await agents_service.dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164="+919000000123",
            campaign=via,
        )
    assert engine._calls[handle]["agent_ref"] == via.ref
    async with tenant_session(tenant_id) as session:
        call = (
            await session.execute(
                text(
                    "SELECT id, engine_agent_ref, campaign_id FROM calls WHERE engine_call_id = :h"
                ),
                {"h": handle},
            )
        ).one()
        assert call.engine_agent_ref == via.ref
        assert call.campaign_id is None
        await session.execute(
            text(_STAMP_CAMPAIGN_SQL), {"cid": call.id, "ref": via.ref, "tid": tenant_id}
        )
        stamped = (
            await session.execute(
                text("SELECT campaign_id FROM calls WHERE id = :c"), {"c": call.id}
            )
        ).scalar_one()
    assert stamped == campaign_id


async def test_a_test_call_through_the_campaign_is_never_counted_in_its_results() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    ref = await _publish(tenant_id, campaign_id)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "trial_call, status, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'outbound', true, 'completed', now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"test-{call_id}"},
        )
        await session.execute(
            text(_STAMP_CAMPAIGN_SQL), {"cid": call_id, "ref": ref, "tid": tenant_id}
        )
        stamped = (
            await session.execute(
                text("SELECT campaign_id FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar_one()
    assert stamped is None


async def _mark_missing(tenant_id: UUID, ref: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET drift_state = :s, drift_checked_at = now() "
                "WHERE engine_agent_ref = :r"
            ),
            {"s": TRUTHFUL_ANSWER_MISSING, "r": ref},
        )


async def test_the_truthful_answer_verdict_is_read_per_holder() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    broken = await _campaign(tenant_id, agent_id, status="running")
    sound = await _campaign(tenant_id, agent_id, script=OTHER, status="running")
    await _mark_missing(tenant_id, await _publish(tenant_id, broken))
    await _publish(tenant_id, sound)
    async with tenant_session(tenant_id) as session:
        refused = await truthful_answer_drift_blocker(
            session, tenant_id=tenant_id, agent_id=agent_id, campaign_id=broken
        )
        other = await truthful_answer_drift_blocker(
            session, tenant_id=tenant_id, agent_id=agent_id, campaign_id=sound
        )
        own = await truthful_answer_drift_blocker(session, tenant_id=tenant_id, agent_id=agent_id)
        every = await truthful_answer_drift_blocker(
            session, tenant_id=tenant_id, agent_id=agent_id, every_holder=True
        )
    assert refused is not None and refused[0] == TRUTHFUL_ANSWER_DRIFT_RULE
    assert other is None, "one campaign's verdict stopped another campaign in the same voice"
    assert own is None, "a campaign's verdict stopped its agent's own calls"
    assert every is not None


async def test_stopping_a_campaign_retires_its_engine_agent_and_drift_leaves_it_alone() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    ref = await _publish(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        assert await stop_campaign(session, campaign_id=campaign_id)
        held = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
        owed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = 'retire_moved_engine_agent' "
                    "AND payload->>'old_ref' = :r"
                ),
                {"r": ref},
            )
        ).scalar_one()
    assert held is None
    assert owed == 1
    drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref)
    assert drift.state == "not_published", "a retired campaign was compared against its agent"


async def test_drift_compares_a_campaigns_engine_agent_with_the_campaigns_config() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    ref = await _publish(tenant_id, campaign_id)
    drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref)
    assert drift.engine_agent_ref == ref
    assert drift.state != "not_applied", drift.detail


async def test_a_full_workspace_is_refused_plainly_before_a_new_engine_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    workspace = f"org_{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        for n in range(2):
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, created_at, updated_at) VALUES ('fake', :r, :t, :a, "
                    "true, now(), now())"
                ),
                {
                    "r": f"agent_{n}_{uuid.uuid4().hex[:6]}@{workspace}",
                    "t": tenant_id,
                    "a": agent_id,
                },
            )

    async def resolve(_session: Any, _tenant: UUID) -> str:
        return workspace

    monkeypatch.setattr(agents_service, "engine_has_workspaces", lambda *_a, **_k: True)
    monkeypatch.setattr(agents_service, "resolve_workspace", resolve)
    async with tenant_session(tenant_id) as session:
        blocked = await agents_service.engine_agent_allowance_blocker(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        with pytest.raises(ProblemError) as refused:
            await agents_service._refuse_if_allowance_full(
                session, tenant_id=tenant_id, workspace=workspace, context="start"
            )
    assert blocked is not None and blocked[0] == agents_service.ENGINE_AGENT_ALLOWANCE_FULL_RULE
    assert refused.value.code == agents_service.ENGINE_AGENT_ALLOWANCE_FULL_RULE
    assert refused.value.detail.startswith(
        "Starting needs a free calling setup. Your account can have 2, and both are in use:"
    )


def test_the_agent_is_given_back_the_version_from_before_the_campaigns() -> None:
    from apps.api.agents.opening_notices import WEAVE_NOTE

    versions = [
        (9, WEAVE_NOTE),
        (8, "Campaign: Diwali offer"),
        (7, "Campaign: Check-ups"),
        (6, WEAVE_NOTE),
        (5, "Script written for the business"),
    ]
    assert own_script_version(versions) == 6
    # An owner's edit on top of the campaign's means the live script is theirs: left alone.
    assert own_script_version([(4, ""), (3, "Campaign: Check-ups"), (2, "")]) is None
    # A campaign's script with nothing older to go back to is left alone too.
    assert own_script_version([(1, "Campaign: First run")]) is None


async def _live_body(tenant_id: UUID, agent_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text(
                        "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                        "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) "
                        "WHERE a.id = :a"
                    ),
                    {"a": agent_id},
                )
            ).scalar_one()
        )


async def test_an_agent_a_campaign_held_before_d1003_gets_its_own_script_back() -> None:
    from apps.api.agents.prompts import insert_prompt_version
    from apps.workers.campaign_engine_agents import _restore_held

    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    own = await _live_body(tenant_id, agent_id)
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    async with tenant_session(tenant_id) as session:
        # What `put_script_live` left behind: the campaign's script as the agent's live
        # version, and the campaign marked as holding the agent.
        await insert_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou call people about their check-up.\n",
            notes="Campaign: Check-ups",
            created_by=None,
            apply_live=True,
        )
        await session.execute(
            text("UPDATE campaigns SET agent_held_at = now() WHERE id = :c"), {"c": campaign_id}
        )
    async with tenant_session(tenant_id) as session:
        # Its campaign still dials through it: it is left as it is.
        assert await _restore_held(session, tenant_id=tenant_id) == (0, 1)
    assert "check-up" in await _live_body(tenant_id, agent_id)

    await _publish(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        assert await _restore_held(session, tenant_id=tenant_id) == (1, 0)
        held = (
            await session.execute(
                text("SELECT agent_held_at FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert await _live_body(tenant_id, agent_id) == own
    assert held is None
    async with tenant_session(tenant_id) as session:
        # Idempotent: nothing is marked any more.
        assert await _restore_held(session, tenant_id=tenant_id) == (0, 0)


async def test_the_hourly_sweep_reaches_an_account_whose_held_campaign_ended_before_d1003() -> None:
    """A campaign that held its agent and completed before D-1003 never gets an engine agent
    of its own, so its account has no campaign route; the sweep must still give the agent
    its own script back."""
    from apps.api.agents.prompts import insert_prompt_version
    from apps.workers.campaign_engine_agents import sweep_campaign_engine_agents

    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    own = await _live_body(tenant_id, agent_id)
    campaign_id = await _campaign(tenant_id, agent_id, status="completed")
    async with tenant_session(tenant_id) as session:
        await insert_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou call people about their check-up.\n",
            notes="Campaign: Check-ups",
            created_by=None,
            apply_live=True,
        )
        await session.execute(
            text("UPDATE campaigns SET agent_held_at = now() WHERE id = :c"), {"c": campaign_id}
        )
        routes = (
            await session.execute(
                text(
                    "SELECT count(*) FROM engine_agent_routes "
                    "WHERE tenant_id = :t AND campaign_id IS NOT NULL"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert routes == 0

    await sweep_campaign_engine_agents({})

    assert await _live_body(tenant_id, agent_id) == own, "the campaign's script stayed live"


async def test_an_account_the_sweep_could_not_handle_raises_an_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import campaign_engine_agents

    await _live_agent()
    raised: list[str] = []

    async def broken(*_: object, **__: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(campaign_engine_agents, "_retire_unneeded", broken)
    monkeypatch.setattr(
        campaign_engine_agents, "alert", lambda _stage, code, **_kw: raised.append(code)
    )
    result = await campaign_engine_agents.sweep_campaign_engine_agents({})
    assert "failed=0" not in result
    assert raised == ["campaign_engine_agent_sweep_failed"]


async def test_an_unused_test_holder_of_a_draft_is_retired_and_a_running_one_kept() -> None:
    from apps.workers.campaign_engine_agents import _retire_unneeded

    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    draft = await _campaign(tenant_id, agent_id)
    running = await _campaign(tenant_id, agent_id, script=OTHER, status="running")
    async with tenant_session(tenant_id) as session:
        await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=draft, test=True
        )
    await _publish(tenant_id, running)
    async with tenant_session(tenant_id) as session:
        # Fresh: an owner may be testing it again in a minute.
        assert await _retire_unneeded(session, tenant_id=tenant_id) == 0
        await session.execute(
            text("UPDATE campaigns SET engine_agent_at = now() - interval '2 hours'")
        )
        assert await _retire_unneeded(session, tenant_id=tenant_id) == 1
        refs = dict(
            (
                await session.execute(
                    text("SELECT id, engine_agent_ref FROM campaigns WHERE id = ANY(:ids)"),
                    {"ids": [draft, running]},
                )
            ).all()
        )
    assert refs[draft] is None and refs[running] is not None


async def test_a_running_campaigns_test_call_never_moves_its_engine_agent_to_our_workspace() -> (
    None
):
    """A draft campaign's test holder is made in our developer workspace (D-1018). Doing that
    for a running campaign would move the engine agent its dials ring through into our
    workspace, where the client's numbers cannot reach it."""
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    running = await _campaign(tenant_id, agent_id, status="running")
    draft = await _campaign(tenant_id, agent_id, script=OTHER)
    live_ref = f"{await _publish(tenant_id, running)}@org_{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET engine_agent_ref = :r WHERE id = :c"),
            {"r": live_ref, "c": running},
        )

    tested = await engine_agent.campaign_test_dial(tenant_id=tenant_id, campaign_id=running)
    assert tested.ref == live_ref
    assert tested.developer is False
    async with tenant_session(tenant_id) as session:
        kept = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :c"), {"c": running}
            )
        ).scalar_one()
    assert kept == live_ref

    # A draft campaign is still tested from our workspace on the shared trial line.
    assert (
        await engine_agent.campaign_test_dial(tenant_id=tenant_id, campaign_id=draft)
    ).developer is True


async def test_what_a_campaign_notes_is_its_own_saved_under_a_compare_and_set() -> None:
    tenant_id, agent_id = await _live_agent()
    other_tenant, _other_agent = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    field = ExtractionField(key="visit_day", label="Visit day", type="text")
    async with tenant_session(tenant_id) as session:
        before = await notes.read_notes(session, campaign_id)
        assert before.fields == ()
        assert await notes.save_notes(session, campaign_id, [field], expected_digest=before.digest)
        after = await notes.read_notes(session, campaign_id)
        assert [f.key for f in after.fields] == ["visit_day"]
        with pytest.raises(ProblemError) as stale:
            await notes.save_notes(session, campaign_id, [], expected_digest=before.digest)
        assert stale.value.code == "campaign_notes_changed_elsewhere"
    async with tenant_session(other_tenant) as session:
        with pytest.raises(ProblemError) as missing:
            await notes.read_notes(session, campaign_id)
        assert missing.value.status == 404
        seen = (
            await session.execute(
                text("SELECT count(*) FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert seen == 0


async def test_the_pipeline_notes_the_campaigns_list_for_its_calls() -> None:
    from apps.workers.pipeline import _load_call_context

    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    field = ExtractionField(key="visit_day", label="Visit day", type="text")
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await notes.save_notes(session, campaign_id, [field], expected_digest=None)
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, campaign_id, engine_call_id, "
                "direction, status, created_at, updated_at) VALUES (:id, :t, :a, :c, :e, "
                "'outbound', 'completed', now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "c": campaign_id, "e": f"n-{call_id}"},
        )
    spec = (await _load_call_context(tenant_id, call_id))[0]
    assert "visit_day" in {f.key for f in spec.fields}
