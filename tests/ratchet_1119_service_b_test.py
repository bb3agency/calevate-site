"""The campaign holder, caller and dial-path branches of `agents/service` (D-1003, D-1019,
D-1020) that the full run left unexercised: a campaign that is not there or archived, a
campaign engine agent that must be recreated in another workspace, a publish the platform
does not run or that fails after the create, a campaign's calling number no longer usable,
first words of a call placed through an inbound line, and the dial's own argument checks.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine
from tests.campaign_engine_agents_test import SCRIPT, _campaign, _live_agent, _publish

pytestmark = pytest.mark.rls


def _workspace() -> str:
    return f"org_{uuid.uuid4().hex[:12]}"


async def _campaign_ref(tenant_id: UUID, campaign_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    return None if ref is None else str(ref)


async def _set_campaign_ref(tenant_id: UUID, campaign_id: UUID, ref: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET engine_agent_ref = :r WHERE id = :c"),
            {"r": ref, "c": campaign_id},
        )


async def _retire_jobs(tenant_id: UUID, ref: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'old_ref' = :ref"
                    ),
                    {"job": agents_service.RETIRE_MOVED_AGENT_JOB, "ref": ref},
                )
            ).scalar_one()
        )


# --- a campaign that is not there, or archived -------------------------------------------


async def test_a_missing_campaign_is_not_found_on_every_reader() -> None:
    tenant_id, _agent_id = await _live_agent()
    missing = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as holder:
            await agents_service.publish_campaign_agent(
                session, tenant_id=tenant_id, campaign_id=missing
            )
        with pytest.raises(ProblemError) as row:
            await agents_service.campaign_agent_row(
                session, tenant_id=tenant_id, campaign_id=missing
            )
    assert holder.value.code == row.value.code == "not_found"


async def test_a_campaign_row_and_config_read_the_agent_themselves_when_not_handed_it() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        row = await agents_service.campaign_agent_row(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        config = await agents_service.campaign_config(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert row["id"] == agent_id and row["direction"] == "outbound"
    assert "check-up" in str(row["prompt"]), "the campaign's own script"
    assert config.holder == f"campaign:{campaign_id}"
    assert "check-up" in config.system_prompt


async def test_an_archived_campaign_is_never_published() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET archived_at = now() WHERE id = :c"), {"c": campaign_id}
        )
    with pytest.raises(ProblemError) as refused:
        await _publish(tenant_id, campaign_id)
    assert refused.value.code == "not_found"
    assert await _campaign_ref(tenant_id, campaign_id) is None


# --- the Start pre-flight ------------------------------------------------------------------


async def test_the_start_preflight_passes_a_campaign_already_in_the_workspace_or_with_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _live_agent()
    workspace = _workspace()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")

    async def resolve(_session: Any, _tenant: UUID) -> str:
        return workspace

    monkeypatch.setattr(agents_service, "engine_has_workspaces", lambda *_a, **_k: True)
    monkeypatch.setattr(agents_service, "resolve_workspace", resolve)
    monkeypatch.setattr(agents_service.get_settings(), "thinnest_agents_per_workspace", 2)
    async with tenant_session(tenant_id) as session:
        # No engine agent yet, but the workspace has room.
        room = await agents_service.engine_agent_allowance_blocker(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
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
        full = await agents_service.engine_agent_allowance_blocker(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        # Its own engine agent is already there: Start makes none, so a full workspace is fine.
        await session.execute(
            text("UPDATE campaigns SET engine_agent_ref = :r WHERE id = :c"),
            {"r": f"agent_own@{workspace}", "c": campaign_id},
        )
        held = await agents_service.engine_agent_allowance_blocker(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert room is None
    assert full is not None and full[0] == agents_service.ENGINE_AGENT_ALLOWANCE_FULL_RULE
    assert held is None


# --- publishing a campaign's engine agent --------------------------------------------------


async def test_a_test_holder_in_a_client_workspace_is_recreated_in_ours_and_the_old_retired() -> (
    None
):
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)  # a draft: its test is made in ours
    old = f"agent_old_{uuid.uuid4().hex[:6]}@{_workspace()}"
    await _set_campaign_ref(tenant_id, campaign_id, old)

    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id, test=True
        )

    assert ref != old and ref in engine._agents
    assert await _campaign_ref(tenant_id, campaign_id) == ref
    assert await _retire_jobs(tenant_id, old) == 1, "the old engine agent's deletion is owed"


async def test_a_campaign_publish_the_platform_does_not_run_is_refused_and_its_agent_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    before = set(engine._agents)

    async def not_applied(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(state="not_applied", detail="The opening is not the one we sent.")

    monkeypatch.setattr(agents_service, "verify_publish", not_applied)
    with pytest.raises(ProblemError) as refused:
        await _publish(tenant_id, campaign_id)

    assert refused.value.code == "engine_publish_not_applied"
    assert refused.value.detail == "The opening is not the one we sent."
    assert set(engine._agents) == before, "the engine agent it made was deleted again"
    assert await _campaign_ref(tenant_id, campaign_id) is None


async def test_an_updated_campaign_agent_the_platform_does_not_run_is_left_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    ref = await _publish(tenant_id, campaign_id)

    async def not_applied(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(state="not_applied", detail="not running it")

    monkeypatch.setattr(agents_service, "verify_publish", not_applied)
    with pytest.raises(ProblemError):
        await _publish(tenant_id, campaign_id)
    assert ref in engine._agents, "an engine agent we did not just make is never deleted"
    assert await _campaign_ref(tenant_id, campaign_id) == ref


async def test_a_campaign_publish_failing_after_the_create_reclaims_the_new_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    before = set(engine._agents)

    async def webhook_down(*_a: Any, **_k: Any) -> None:
        raise ProblemError(
            kind="dependency",
            code="engine_unreachable",
            title="The voice platform did not answer",
            detail="Nothing changed.",
        )

    monkeypatch.setattr(agents_service, "_ensure_results_webhook", webhook_down)
    with pytest.raises(ProblemError) as failed:
        await _publish(tenant_id, campaign_id)
    assert failed.value.code == "engine_unreachable"
    assert set(engine._agents) == before


async def test_an_existing_campaign_agent_is_kept_when_a_republish_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    ref = await _publish(tenant_id, campaign_id)

    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("actions down")

    monkeypatch.setattr(agents_service, "_ensure_in_call_actions", boom)
    with pytest.raises(RuntimeError):
        await _publish(tenant_id, campaign_id)
    assert ref in engine._agents


async def test_retiring_a_campaign_with_no_engine_agent_retires_nothing() -> None:
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, status="completed")
    async with tenant_session(tenant_id) as session:
        retired = await agents_service.retire_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert retired is None


# --- idle test copies in the client's workspace -------------------------------------------


async def test_a_test_copy_used_between_the_idle_read_and_its_deletion_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _live_agent()
    ref = f"agent_copy_{uuid.uuid4().hex[:6]}@{_workspace()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref, "
                "business_only, last_used_at) VALUES (:i, :t, :a, :r, false, "
                "now() - interval '2 hours')"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "a": agent_id, "r": ref},
        )

    async with tenant_session(tenant_id) as session:
        real_execute = session.execute

        async def used_meanwhile(statement: Any, *args: Any, **kwargs: Any) -> Any:
            # A test call takes the copy after the idle read and before its deletion.
            if str(statement).startswith("DELETE FROM agent_test_copies"):
                await real_execute(
                    text("UPDATE agent_test_copies SET last_used_at = now() WHERE agent_id = :a"),
                    {"a": agent_id},
                )
            return await real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", used_meanwhile)
        retired = await agents_service.retire_idle_client_test_copies(
            session, tenant_id=tenant_id, idle_seconds=3600
        )
        monkeypatch.undo()
        assert await agents_service.test_copy_ref(session, agent_id) == ref
    assert retired == 0
    assert await _retire_jobs(tenant_id, ref) == 0


# --- the number a campaign's call rings from ---------------------------------------------


async def test_a_campaign_number_no_longer_usable_is_refused_and_declares_nothing() -> None:
    tenant_id, agent_id = await _live_agent()
    gone = uuid.uuid4()
    ref = f"agent_c_{uuid.uuid4().hex[:6]}@{_workspace()}"
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await agents_service._campaign_caller(
                session, agent_id=agent_id, number_id=gone, ref=ref
            )
        declared = await agents_service.presented_caller_ids(
            session, agent_id=agent_id, number_id=gone, campaign_ref=ref
        )
    assert refused.value.code == agents_service.CAMPAIGN_NUMBER_UNAVAILABLE_CODE
    assert declared == [], "a number the dial would refuse is not one it presents"


# --- first words -----------------------------------------------------------------------------


async def _agent_row(tenant_id: UUID, agent_id: UUID) -> agents_service.AgentRow:
    async with tenant_session(tenant_id) as session:
        return await agents_service._load_agent(session, tenant_id, agent_id)


async def test_a_campaign_opens_with_its_own_line_and_the_agents_name() -> None:
    tenant_id, agent_id = await _live_agent()
    agent = await _agent_row(tenant_id, agent_id)
    words = agents_service.campaign_first_words(agent, SCRIPT.opening_line, call_is_recorded=True)
    assert SCRIPT.opening_line in words


async def test_an_answering_agent_calling_through_its_line_opens_as_a_both_agent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id, agent_id = await _live_agent()
    agent = dict(await _agent_row(tenant_id, agent_id))
    inbound = agents_service.cast(agents_service.AgentRow, {**agent, "direction": "inbound"})
    both = agents_service.cast(agents_service.AgentRow, {**agent, "direction": "both"})
    caplog.set_level(logging.WARNING)
    through = agents_service.dial_first_words(
        inbound, test_call=False, call_is_recorded=True, through_line=True
    )
    assert through is not None
    assert "placed_call_opening_ready_made" not in caplog.text, (
        "the language's business line is expected here, not a gap to close"
    )
    assert through == agents_service.dial_first_words(
        both, test_call=False, call_is_recorded=True
    ), "its greeting thanks the caller, so it opens as a placed call"
    # Not through a line, an answering agent's own call opens with its greeting.
    assert (
        agents_service.dial_first_words(inbound, test_call=False, call_is_recorded=True) != through
    )


# --- the dial's own argument checks ----------------------------------------------------------


def _owner_test() -> agents_service.OwnerTestDial:
    return agents_service.OwnerTestDial(
        max_call_seconds=180, daily_cap=10, day_start=datetime.now(UTC)
    )


async def test_a_dial_refuses_a_line_test_or_copy_test_outside_a_test_call() -> None:
    tenant_id, agent_id = await _live_agent()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError, match="line_test is for a test call only"):
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876543210",
                line_test=agents_service.LineTestDial(ref="agent_x", line_id=uuid.uuid4()),
            )
        with pytest.raises(ValueError, match="copy_test is a paying account"):
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876543210",
                copy_test=agents_service.CopyTestDial(ref="agent_x"),
            )


async def test_a_copy_test_with_no_number_left_in_its_workspace_is_refused_before_the_dial() -> (
    None
):
    tenant_id, agent_id = await _live_agent()
    copy = agents_service.CopyTestDial(ref=f"agent_copy_{uuid.uuid4().hex[:6]}@{_workspace()}")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876543210",
                owner_test=_owner_test(),
                copy_test=copy,
            )
        placed = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert refused.value.code == agents_service.CLIENT_NUMBER_UNAVAILABLE_RULE
    assert placed == 0, "nothing was written for a dial that was never placed"
