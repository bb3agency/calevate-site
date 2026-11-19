"""Test holders give their calling setup back on time, and only when nobody is using them.

1. A draft line's test holder ages by `inbound_lines.engine_agent_at`, which only its own
   publish writes: the drift, webhook, facts and rate sweeps rewrite the route's `updated_at`
   and used to keep it young for ever.
2. The hourly sweep reads its candidates without a lock; a test call or a Start between that
   read and the retire keeps the engine agent (the predicate is asked again under the row).
3. A Start or a line put live in a full workspace first gives back the test holders there
   that no call is on, and only then refuses; the refusal never tells the owner to archive a
   draft line or stop a campaign that has not started to free a test holder.
4. A draft line whose test holder the platform no longer has makes a new one.
5. The deletion job leaves alone a vendor agent a line or campaign holds again by its tag.
6. A scheduled start the platform refuses for a full workspace says so, not "not ready".

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents.workspace_slots import SlotHolder, allowance_remediation
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.workers import engine_workspaces as jobs
from apps.workers.campaign_engine_agents import (
    _IDLE_LINE_HOLDERS_SQL,
    _TO_RETIRE_SQL,
    TEST_HOLDER_IDLE,
    _retire_unneeded,
)
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine
from tests.campaign_engine_agents_test import SCRIPT, _campaign, _live_agent

pytestmark = pytest.mark.rls

IDLE = TEST_HOLDER_IDLE.total_seconds()


def _workspace() -> str:
    return f"org_{uuid.uuid4().hex[:12]}"


async def _draft_line(tenant_id: UUID, agent_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="After hours", created_by=None
        )
        await lines.save_script(session, line_id, SCRIPT)
    return line_id


async def _test_holder(tenant_id: UUID, line_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return await agents_service.publish_line(
            session, tenant_id=tenant_id, line_id=line_id, test=True
        )


async def _scalar(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).scalar()


async def _exec(tenant_id: UUID, sql: str, **params: Any) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(text(sql), params)


async def _hold(
    tenant_id: UUID,
    agent_id: UUID,
    ref: str,
    *,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
    aged: str = "10 minutes",
) -> None:
    """`ref` held by a draft line or a campaign in the client's workspace, last published
    `aged` ago, with its active route."""
    async with tenant_session(tenant_id) as session:
        if line_id is not None:
            await session.execute(
                text(
                    "UPDATE inbound_lines SET engine_agent_ref = :r, "
                    "engine_agent_at = now() - CAST(:aged AS interval) WHERE id = :l"
                ),
                {"r": ref, "aged": aged, "l": line_id},
            )
        if campaign_id is not None:
            await session.execute(
                text(
                    "UPDATE campaigns SET engine_agent_ref = :r, "
                    "engine_agent_at = now() - CAST(:aged AS interval) WHERE id = :c"
                ),
                {"r": ref, "aged": aged, "c": campaign_id},
            )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "inbound_line_id, campaign_id, active, created_at, updated_at) VALUES ('fake', "
                ":r, :t, :a, :l, :c, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id, "l": line_id, "c": campaign_id},
        )


async def _active(tenant_id: UUID, ref: str) -> bool:
    return bool(
        await _scalar(
            tenant_id, "SELECT active FROM engine_agent_routes WHERE engine_agent_ref = :r", r=ref
        )
    )


async def _owed(tenant_id: UUID, ref: str) -> int:
    return int(
        await _scalar(
            tenant_id,
            "SELECT count(*) FROM outbox_messages WHERE job = :job AND payload->>'old_ref' = :r",
            job=agents_service.RETIRE_MOVED_AGENT_JOB,
            r=ref,
        )
    )


def _client_workspace(monkeypatch: pytest.MonkeyPatch, workspace: str, limit: int = 2) -> None:
    async def resolve(_session: Any, _tenant: UUID) -> str:
        return workspace

    monkeypatch.setattr(agents_service, "engine_has_workspaces", lambda *_a, **_k: True)
    monkeypatch.setattr(agents_service, "resolve_workspace", resolve)
    monkeypatch.setattr(agents_service.get_settings(), "thinnest_agents_per_workspace", limit)


# --- 1. a draft line's holder ages by its own stamp --------------------------------------


async def test_a_line_test_holder_ages_by_its_own_publish_not_its_routes_upkeep() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _draft_line(tenant_id, agent_id)
    ref = await _test_holder(tenant_id, line_id)
    stamped = await _scalar(
        tenant_id, "SELECT engine_agent_at FROM inbound_lines WHERE id = :l", l=line_id
    )
    assert isinstance(stamped, datetime)

    # Published a minute ago, and the sweeps left its route old: kept.
    await _exec(
        tenant_id,
        "UPDATE engine_agent_routes SET updated_at = now() - interval '3 hours' "
        "WHERE engine_agent_ref = :r",
        r=ref,
    )
    async with tenant_session(tenant_id) as session:
        assert await _retire_unneeded(session, tenant_id=tenant_id) == 0

    # Unused for two hours, and a drift sweep touched its route a second ago: retired.
    await _exec(
        tenant_id,
        "UPDATE inbound_lines SET engine_agent_at = now() - interval '2 hours' WHERE id = :l",
        l=line_id,
    )
    await _exec(
        tenant_id,
        "UPDATE engine_agent_routes SET updated_at = now() WHERE engine_agent_ref = :r",
        r=ref,
    )
    async with tenant_session(tenant_id) as session:
        assert await _retire_unneeded(session, tenant_id=tenant_id) == 1
    row = await _scalar(
        tenant_id,
        "SELECT engine_agent_ref IS NULL AND engine_agent_at IS NULL FROM inbound_lines "
        "WHERE id = :l",
        l=line_id,
    )
    assert row is True
    assert await _owed(tenant_id, ref) == 1


# --- 2. the sweep re-asks under the row lock ----------------------------------------------


async def test_a_test_call_between_the_sweeps_read_and_its_retire_keeps_the_line_holder() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _draft_line(tenant_id, agent_id)
    ref = await _test_holder(tenant_id, line_id)
    await _exec(
        tenant_id,
        "UPDATE inbound_lines SET engine_agent_at = now() - interval '2 hours' WHERE id = :l",
        l=line_id,
    )
    async with tenant_session(tenant_id) as session:
        candidates = list(
            (await session.execute(text(_IDLE_LINE_HOLDERS_SQL), {"idle": IDLE})).scalars()
        )
    assert line_id in candidates
    assert await _test_holder(tenant_id, line_id) == ref  # the owner's test call
    async with tenant_session(tenant_id) as session:
        assert (
            await agents_service.retire_line_test_holder(
                session, tenant_id=tenant_id, line_id=line_id, idle_seconds=IDLE
            )
            is None
        )
    held = await _scalar(
        tenant_id, "SELECT engine_agent_ref FROM inbound_lines WHERE id = :l", l=line_id
    )
    assert held == ref
    assert await _owed(tenant_id, ref) == 0


async def test_a_start_between_the_sweeps_read_and_its_retire_keeps_the_campaigns_agent() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id, test=True
        )
    await _exec(
        tenant_id,
        "UPDATE campaigns SET engine_agent_at = now() - interval '2 hours' WHERE id = :c",
        c=campaign_id,
    )
    async with tenant_session(tenant_id) as session:
        candidates = list(
            (
                await session.execute(
                    text(_TO_RETIRE_SQL),
                    {"holding": list(agents_service.CAMPAIGN_HOLDING_STATUSES), "idle": IDLE},
                )
            ).scalars()
        )
    assert campaign_id in candidates
    # Start: the campaign turns running on a freshly published engine agent.
    await _exec(
        tenant_id,
        "UPDATE campaigns SET status = 'running', engine_agent_at = now() WHERE id = :c",
        c=campaign_id,
    )
    async with tenant_session(tenant_id) as session:
        assert (
            await agents_service.retire_campaign_agent(
                session, tenant_id=tenant_id, campaign_id=campaign_id, idle_seconds=IDLE
            )
            is None
        )
    held = await _scalar(
        tenant_id, "SELECT engine_agent_ref FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert held == ref
    assert await _owed(tenant_id, ref) == 0


# --- 3. a full workspace gives back idle test holders first --------------------------------


async def test_putting_a_line_live_gives_back_idle_test_holders_before_refusing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    workspace = _workspace()
    _client_workspace(monkeypatch, workspace)
    draft = await _draft_line(tenant_id, agent_id)
    campaign_id = await _campaign(tenant_id, agent_id)
    line_ref = f"line_{uuid.uuid4().hex[:6]}@{workspace}"
    campaign_ref = f"camp_{uuid.uuid4().hex[:6]}@{workspace}"
    await _hold(tenant_id, agent_id, line_ref, line_id=draft)
    await _hold(tenant_id, agent_id, campaign_ref, campaign_id=campaign_id)
    async with tenant_session(tenant_id) as session:
        # The launch check counts them as room: Start would free them.
        assert (
            await agents_service.engine_agent_allowance_blocker(
                session, tenant_id=tenant_id, campaign_id=uuid7()
            )
            is None
        )
        await agents_service._refuse_if_allowance_full(
            session, tenant_id=tenant_id, workspace=workspace, context="line_live"
        )
    assert not await _active(tenant_id, line_ref)
    assert not await _active(tenant_id, campaign_ref)
    assert line_ref not in engine._agents and campaign_ref not in engine._agents
    # Deleted now, so nothing is owed to the outbox.
    assert await _owed(tenant_id, line_ref) == 0 and await _owed(tenant_id, campaign_ref) == 0
    assert (
        await _scalar(
            tenant_id, "SELECT engine_agent_ref FROM inbound_lines WHERE id = :l", l=draft
        )
        is None
    )
    assert (
        await _scalar(
            tenant_id, "SELECT engine_agent_ref FROM campaigns WHERE id = :c", c=campaign_id
        )
        is None
    )


async def test_a_test_holder_on_a_call_or_just_published_is_kept_and_described_as_such(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    workspace = _workspace()
    _client_workspace(monkeypatch, workspace)
    on_call, fresh = await _draft_line(tenant_id, agent_id), await _draft_line(tenant_id, agent_id)
    on_call_ref = f"busy_{uuid.uuid4().hex[:6]}@{workspace}"
    fresh_ref = f"fresh_{uuid.uuid4().hex[:6]}@{workspace}"
    await _hold(tenant_id, agent_id, on_call_ref, line_id=on_call)
    await _hold(tenant_id, agent_id, fresh_ref, line_id=fresh, aged="10 seconds")
    await _exec(
        tenant_id,
        "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
        "paid_test_call, inbound_line_id, engine_agent_ref, status, created_at, updated_at) "
        "VALUES (:id, :t, :a, :e, 'outbound', '+919876543210', true, :l, :r, 'ringing', "
        "now(), now())",
        id=uuid7(),
        t=tenant_id,
        a=agent_id,
        e=f"ring-{uuid.uuid4().hex}",
        l=on_call,
        r=on_call_ref,
    )
    async with tenant_session(tenant_id) as session:
        assert await agents_service.idle_test_holders_in(session, workspace=workspace) == 0
        with pytest.raises(ProblemError) as refused:
            await agents_service._refuse_if_allowance_full(
                session, tenant_id=tenant_id, workspace=workspace, context="start"
            )
    assert await _active(tenant_id, on_call_ref) and await _active(tenant_id, fresh_ref)
    problem = refused.value
    assert problem.code == agents_service.ENGINE_AGENT_ALLOWANCE_FULL_RULE
    remediation = problem.remediation or ""
    assert "archive" not in remediation.lower() and "stop a campaign" not in remediation.lower()
    assert "held for test calls" in remediation
    holders = problem.as_problem()["holders"]
    assert {(h["kind"], h["test_only"]) for h in holders} == {("inbound_line", True)}


async def test_a_test_call_needing_a_setup_takes_nobody_elses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    workspace = _workspace()
    _client_workspace(monkeypatch, workspace)
    draft = await _draft_line(tenant_id, agent_id)
    ref = f"line_{uuid.uuid4().hex[:6]}@{workspace}"
    await _hold(tenant_id, agent_id, ref, line_id=draft)
    await _exec(
        tenant_id,
        "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
        "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())",
        r=f"own_{uuid.uuid4().hex[:6]}@{workspace}",
        t=tenant_id,
        a=agent_id,
    )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError):
            await agents_service._refuse_if_allowance_full(
                session, tenant_id=tenant_id, workspace=workspace, context="test_call"
            )
    assert await _active(tenant_id, ref)


def _holder(kind: Any, *, removing: bool = False, test_only: bool = False) -> SlotHolder:
    return SlotHolder(kind=kind, id=uuid.uuid4(), name="x", removing=removing, test_only=test_only)


def test_a_draft_lines_or_unstarted_campaigns_holder_is_not_offered_as_one_to_free() -> None:
    said = allowance_remediation(
        [_holder("inbound_line", test_only=True), _holder("campaign", test_only=True)]
    )
    assert said == (
        "A setup held for test calls is freed an hour after the last one, or when you start a "
        "campaign or put a line live with no test call on it. To have more, ask us to raise "
        "your limit."
    )
    both = allowance_remediation([_holder("inbound_line"), _holder("campaign", test_only=True)])
    assert both.startswith("Archive an inbound line you no longer use to free one. A setup")


# --- 4. a test holder the platform lost is made again --------------------------------------


async def test_a_draft_lines_test_holder_gone_at_the_platform_is_made_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _draft_line(tenant_id, agent_id)
    gone = f"gone_{uuid.uuid4().hex[:8]}"
    await _hold(tenant_id, agent_id, gone, line_id=line_id, aged="5 minutes")
    real_update = engine.update_agent

    async def update(ref: str, cfg: Any) -> None:
        if ref == gone:
            raise ProblemError.not_found("Agent")
        await real_update(ref, cfg)

    monkeypatch.setattr(engine, "update_agent", update)
    ref = await _test_holder(tenant_id, line_id)
    assert ref != gone and ref in engine._agents
    assert not await _active(tenant_id, gone)
    held = await _scalar(
        tenant_id, "SELECT engine_agent_ref FROM inbound_lines WHERE id = :l", l=line_id
    )
    assert held == ref

    # Putting it live is not a test call: a lost engine agent there is the publish's failure.
    await _hold(tenant_id, agent_id, f"{gone}b", line_id=line_id)

    async def update_live(ref: str, cfg: Any) -> None:
        if ref == f"{gone}b":
            raise ProblemError.not_found("Agent")
        await real_update(ref, cfg)

    monkeypatch.setattr(engine, "update_agent", update_live)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await agents_service.publish_line(session, tenant_id=tenant_id, line_id=line_id)
    assert refused.value.kind == "not_found"


# --- 5. the deletion job leaves a holder held again ----------------------------------------


async def test_the_deletion_job_leaves_a_line_holder_its_line_took_back_by_its_tag() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _draft_line(tenant_id, agent_id)
    ref = await _test_holder(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        assert await agents_service.retire_line_test_holder(
            session, tenant_id=tenant_id, line_id=line_id
        )
    # The next test call found the same vendor agent by its name tag before the job ran.
    assert await _test_holder(tenant_id, line_id) == ref
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": ref}
    assert await jobs.retire_moved_engine_agent({"job_try": 1}, payload) == "held_again"
    assert await _active(tenant_id, ref)


async def test_the_deletion_job_deletes_a_holder_nobody_names_any_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id = await _draft_line(tenant_id, agent_id)
    ref = await _test_holder(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        await agents_service.retire_line_test_holder(session, tenant_id=tenant_id, line_id=line_id)

    class _NoCalls:
        async def has_live_call(self, _ref: str) -> bool:
            return False

    async def _no_actions(*, agent_id: Any, ref: Any) -> int:
        return 0

    monkeypatch.setattr(jobs, "thinnest_actions", lambda: _NoCalls())
    monkeypatch.setattr(jobs, "retire_in_call_actions", _no_actions)
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": ref}
    assert await jobs.retire_moved_engine_agent({"job_try": 1}, payload) == "retired"
    assert ref not in engine._agents
    assert not await _active(tenant_id, ref)
