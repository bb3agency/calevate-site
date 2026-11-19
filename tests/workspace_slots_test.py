"""Calling setups: what holds them, how a full workspace is refused, and where test calls ring
from (D-1018, D-1020).

1. A paying account with a number of its own in its workspace tests a draft campaign, a draft
   line and a plain agent from that number, through a short-lived holder made in its own
   workspace (D-1020): the campaign's calling number, one of the line's numbers, else the
   account's first. With no free engine agent there it falls back to our developer workspace
   and the shared test line, and says so. A paying account with no number, like a trial,
   tests drafts from the shared line; a running campaign is still tested on its own engine
   agent.
2. Idle test holders are retired: a draft line's, a draft campaign's, and an agent's
   client-workspace test copy, which counts as a calling setup while it exists.
3. A full workspace is refused in the words of what was pressed, never "at once" or Start on
   a test call, and names each holder (kind, name, id, being removed), never another
   account's.

The engine is the test deployment's fake; a client workspace is put in place by replacing
`_in_client_workspace`, and the shared number's lend is the placement test's recorder.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import paid_test_calls, trial_calls
from apps.api.agents import service as agents_service
from apps.api.agents.workspace_slots import (
    ENGINE_AGENT_ALLOWANCE_FULL_RULE,
    EngineAgentAllowanceFull,
    SlotHolder,
    allowance_remediation,
    slot_holders,
)
from apps.api.campaigns import engine_agent
from apps.api.campaigns import service as campaigns_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.inbound import lines
from calevate_shared.call_script import CallScript
from calevate_shared.engine import AgentConfig
from sqlalchemy import text
from tests.campaign_engine_agents_test import _campaign, _live_agent, _publish
from tests.trial_call_placement_test import Line, _account, line  # noqa: F401
from tests.trial_test_calls_test import TRIAL_NUMBER

pytestmark = [pytest.mark.rls]

SCRIPT = CallScript(opening_line="Namaste, Trial Tea House calling about your order.")
_REAL_LINE_OF = paid_test_calls.line_of


def _workspace() -> str:
    return f"org_{uuid.uuid4().hex[:12]}"


async def _fill(tenant_id: UUID, agent_id: UUID, workspace: str, count: int = 2) -> list[str]:
    """`count` engine agents of `agent_id` in `workspace`, as an agent's own would be routed."""
    refs = [f"agent_{n}_{uuid.uuid4().hex[:6]}@{workspace}" for n in range(count)]
    async with tenant_session(tenant_id) as session:
        for ref in refs:
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, created_at, updated_at) VALUES (:e, :r, :t, :a, true, "
                    "now(), now())"
                ),
                {"e": get_engine().name, "r": ref, "t": tenant_id, "a": agent_id},
            )
    return refs


def _client_workspace(monkeypatch: pytest.MonkeyPatch, workspace: str) -> None:
    """A paying client's own workspace: every publish outside our developer workspace is
    placed in `workspace`, as `_in_client_workspace` does on an engine with workspaces."""

    async def placed(
        _session: Any, _engine: Any, *, config: AgentConfig, trial: bool = False, **_k: Any
    ) -> AgentConfig:
        return config if trial else config.model_copy(update={"engine_workspace": workspace})

    monkeypatch.setattr(agents_service, "_in_client_workspace", placed)


async def _paid_with_own_number(line: Line, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    tenant_id, agent_id, principal = await _account(line)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE organizations SET first_paid_at = now(), first_paid_via = 'manual_topup' "
                "WHERE id = :t"
            ),
            {"t": tenant_id},
        )
    # The agent answers its own number in the client's workspace, so before D-1018 its
    # campaign's test was readied there.
    monkeypatch.setattr(paid_test_calls, "line_of", lambda *_a, **_k: "own_number")
    # A paid test call from the client's own number is offered only on the real engine.
    monkeypatch.setattr(trial_calls, "TRIAL_CALL_ENGINES", frozenset({get_engine().name}))
    return tenant_id, agent_id, principal


async def _number(tenant_id: UUID, workspace: str, *, line_id: UUID | None = None) -> UUID:
    """A number of the client's in `workspace` it can call out from, answering `line_id`."""
    number_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, direction, "
                "engine_number_ref, inbound_line_id, created_at, updated_at) VALUES (:id, :t, "
                ":e, '160', 'both', :ref, :line, now(), now())"
            ),
            {
                "id": number_id,
                "t": tenant_id,
                "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
                "ref": f"num_{uuid.uuid4().hex[:8]}@{workspace}",
                "line": line_id,
            },
        )
    return number_id


async def _e164(tenant_id: UUID, number_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT e164 FROM phone_numbers WHERE id = :n"), {"n": number_id}
                )
            ).scalar_one()
        )


async def _paid_with_a_number_in(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[UUID, UUID, Any, str]:
    """A paying account whose own workspace holds a number of its own (D-1020), two calling
    setups allowed there, and its agent holding no engine agent of its own (D-1019)."""
    tenant_id, agent_id, principal = await _paid_with_own_number(line, monkeypatch)
    # Which line the agent takes is decided here, not assumed.
    monkeypatch.setattr(paid_test_calls, "line_of", _REAL_LINE_OF)
    workspace = _workspace()
    _client_workspace(monkeypatch, workspace)

    async def resolve(_session: Any, _tenant: UUID) -> str:
        return workspace

    monkeypatch.setattr(paid_test_calls, "resolve_workspace", resolve)
    monkeypatch.setattr(agents_service.get_settings(), "thinnest_agents_per_workspace", 2)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )
    return tenant_id, agent_id, principal, workspace


async def _call(tenant_id: UUID, call_id: UUID | None) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT from_e164, engine_agent_ref, paid_test_call, trial_call "
                    "FROM calls WHERE id = :c"
                ),
                {"c": call_id},
            )
        ).one()


# ------------------------------------- 1. a paying account's tests ring from its own number


async def test_a_draft_campaign_is_tested_from_its_calling_number_in_the_clients_workspace(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    await _number(tenant_id, workspace)
    chosen = await _number(tenant_id, workspace)
    campaign_id = await _campaign(tenant_id, agent_id, script=SCRIPT)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET number_id = :n WHERE id = :c"),
            {"n": chosen, "c": campaign_id},
        )

    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            campaign_id=campaign_id,
        )

    assert placed.status == "queued", placed
    assert placed.caller_number is None and not placed.shared_fallback
    assert line.lent_to == [], "the shared test number is not used"
    call = await _call(tenant_id, placed.call_id)
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref, status FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).one()
    assert str(ref.engine_agent_ref).endswith(f"@{workspace}"), "made in the client's workspace"
    assert ref.status == "draft"
    assert call.engine_agent_ref == ref.engine_agent_ref
    assert call.from_e164 == await _e164(tenant_id, chosen), "the campaign's calling number"
    assert call.paid_test_call and not call.trial_call, "billed as any paid test call"
    async with tenant_session(tenant_id) as session:
        holders = await slot_holders(
            session, tenant_id=tenant_id, engine=get_engine().name, workspace=workspace
        )
    assert [(h.kind, h.id, h.removing) for h in holders] == [("campaign", campaign_id, False)]


async def test_a_draft_line_is_tested_from_its_own_number_and_stays_a_draft(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    await _number(tenant_id, workspace)
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )
        await lines.save_script(session, line_id, SCRIPT)
    its_own = await _number(tenant_id, workspace, line_id=line_id)

    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            line_id=line_id,
        )

    assert placed.status == "queued", placed
    assert placed.caller_number is None and not placed.shared_fallback
    async with tenant_session(tenant_id) as session:
        held = await lines.read_line(session, line_id)
    assert held.engine_agent_ref and held.engine_agent_ref.endswith(f"@{workspace}")
    assert not held.live, "a test leaves the line a draft"
    call = await _call(tenant_id, placed.call_id)
    assert call.from_e164 == await _e164(tenant_id, its_own), "one of the line's numbers"
    assert call.engine_agent_ref == held.engine_agent_ref


async def test_a_plain_agent_test_rings_through_a_client_copy_that_is_given_back_once_idle(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers.campaign_engine_agents import _retire_unneeded

    tenant_id, agent_id, principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    first = await _number(tenant_id, workspace)
    await _number(tenant_id, workspace)

    async def place() -> trial_calls.TrialCallResult:
        async with tenant_session(tenant_id) as session:
            return await trial_calls.place_trial_call(
                session,
                principal=principal,
                agent_id=agent_id,
                number="98765 43210",
                idempotency_key=str(uuid.uuid4()),
                own_number_attested=True,
            )

    placed = await place()
    assert placed.status == "queued", placed
    assert placed.caller_number is None and not placed.shared_fallback
    async with tenant_session(tenant_id) as session:
        copy_ref = await agents_service.test_copy_ref(session, agent_id)
    assert copy_ref is not None and copy_ref.endswith(f"@{workspace}")
    call = await _call(tenant_id, placed.call_id)
    assert (call.engine_agent_ref, call.from_e164) == (copy_ref, await _e164(tenant_id, first))
    assert line.lent_to == []

    # It is a calling setup while it exists, named as a test call.
    async with tenant_session(tenant_id) as session:
        holders = await slot_holders(
            session, tenant_id=tenant_id, engine=get_engine().name, workspace=workspace
        )
    assert [(h.kind, h.id, h.removing) for h in holders] == [("test_call", agent_id, False)]

    # The D-1019 sweeps read it as the agent's test copy, and the copies sweep leaves it to
    # the idle rule even though the client has a number.
    from apps.api.agents.reconciliation import route_holder
    from apps.workers.agent_moves import _retire_test_copies

    async with tenant_session(tenant_id) as session:
        held = await route_holder(session, agent_id=agent_id, engine_agent_ref=copy_ref)
        assert held is not None and (held.kind, held.business_only) == ("test_copy", True)
        assert await _retire_test_copies(session, tenant_id=tenant_id, workspace=workspace) == 0

    # A repeat straight away reuses it, once the first call has ended.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = 'completed' WHERE id = :c"), {"c": placed.call_id}
        )
    again = await place()
    assert again.status == "queued", again
    async with tenant_session(tenant_id) as session:
        assert await agents_service.test_copy_ref(session, agent_id) == copy_ref
        await session.execute(
            text("UPDATE calls SET status = 'completed' WHERE id = :c"), {"c": again.call_id}
        )
        # Fresh: an owner may be testing it again in a minute.
        assert await _retire_unneeded(session, tenant_id=tenant_id) == 0
        await session.execute(
            text(
                "UPDATE agent_test_copies SET last_used_at = now() - interval '2 hours', "
                "created_at = now() - interval '2 hours' WHERE agent_id = :a"
            ),
            {"a": agent_id},
        )
        assert await _retire_unneeded(session, tenant_id=tenant_id) == 1
        assert await agents_service.test_copy_ref(session, agent_id) is None
        owed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'old_ref' = :ref"
                ),
                {"job": agents_service.RETIRE_MOVED_AGENT_JOB, "ref": copy_ref},
            )
        ).scalar_one()
    assert owed == 1, "the vendor agent's deletion is owed, freeing the slot"


async def test_a_full_workspace_rings_the_draft_from_the_shared_line_and_says_so(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    await _number(tenant_id, workspace)
    await _fill(tenant_id, agent_id, workspace)
    campaign_id = await _campaign(tenant_id, agent_id, script=SCRIPT)

    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            campaign_id=campaign_id,
        )

    assert placed.status == "queued", placed
    assert placed.shared_fallback, "the screen is told both setups were busy"
    assert placed.caller_number == TRIAL_NUMBER
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert ref is not None and not str(ref).endswith(f"@{workspace}")
    assert line.lent_to == [ref]
    call = await _call(tenant_id, placed.call_id)
    assert call.paid_test_call

    # Said before the press: a new campaign's test has nothing in the full workspace yet.
    fresh = await _campaign(tenant_id, agent_id, script=SCRIPT)
    async with tenant_session(tenant_id) as session:
        before = await paid_test_calls.rings_from(
            session, tenant_id=tenant_id, agent_id=agent_id, campaign_id=fresh
        )
    assert before == paid_test_calls.RingsFrom(setups_busy=True)

    # With no shared number either, the full workspace's own refusal, naming what holds it;
    # never "not available yet", which the owner can do nothing about.
    monkeypatch.setattr(trial_calls, "trial_calling_ready", lambda: False)
    async with tenant_session(tenant_id) as session:
        before = await paid_test_calls.rings_from(
            session, tenant_id=tenant_id, agent_id=agent_id, campaign_id=fresh
        )
        refused = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            line_id=None,
            campaign_id=fresh,
        )
    assert (refused.status, refused.blocked_rule) == ("blocked", ENGINE_AGENT_ALLOWANCE_FULL_RULE)
    assert refused.blocked_reason is not None
    assert refused.blocked_reason.startswith("Test calls need a free calling setup.")
    assert "both are in use" in refused.blocked_reason
    assert before.own_number is None and before.unavailable == refused.blocked_reason

    # A test with a setup of its own there already still rings from the account's number.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET engine_agent_ref = :r WHERE id = :c"),
            {"r": f"agent_held@{workspace}", "c": fresh},
        )
        held = await paid_test_calls.rings_from(
            session, tenant_id=tenant_id, agent_id=agent_id, campaign_id=fresh
        )
    assert held.own_number is not None and not held.setups_busy and held.unavailable is None


async def test_the_number_shown_before_a_test_is_the_one_it_rings_and_never_another_accounts(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    first = await _number(tenant_id, workspace)
    chosen = await _number(tenant_id, workspace)
    campaign_id = await _campaign(tenant_id, agent_id, script=SCRIPT)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET number_id = :n WHERE id = :c"),
            {"n": chosen, "c": campaign_id},
        )
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Desk", created_by=None
        )
    its_own = await _number(tenant_id, workspace, line_id=line_id)
    # Another paying account's numbers under the same workspace name stay out.
    other_tenant, other_agent, _other = await _paid_with_own_number(line, monkeypatch)
    await _number(other_tenant, workspace)

    async with tenant_session(tenant_id) as session:
        plain = await paid_test_calls.own_caller_number(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
        of_line = await paid_test_calls.own_caller_number(
            session, tenant_id=tenant_id, agent_id=agent_id, line_id=line_id
        )
        of_campaign = await paid_test_calls.own_caller_number(
            session, tenant_id=tenant_id, agent_id=agent_id, campaign_id=campaign_id
        )
    assert plain == await _e164(tenant_id, first)
    assert of_line == await _e164(tenant_id, its_own)
    assert of_campaign == await _e164(tenant_id, chosen)
    async with tenant_session(other_tenant) as session:
        theirs = await paid_test_calls.own_caller_number(
            session, tenant_id=other_tenant, agent_id=agent_id
        )
    assert theirs not in (plain, of_line, of_campaign)
    async with tenant_session(other_tenant) as session:
        # The other account's own number, not this one's.
        assert (
            theirs
            == (
                await session.execute(
                    text("SELECT e164 FROM phone_numbers WHERE tenant_id = :t"), {"t": other_tenant}
                )
            ).scalar_one()
        )
    del other_agent


async def test_a_free_trial_and_a_paid_account_without_a_number_ring_from_our_test_number(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial_tenant, trial_agent, _p = await _account(line)
    async with tenant_session(trial_tenant) as session:
        assert await paid_test_calls.own_test_workspace(session, tenant_id=trial_tenant) is None
        assert (
            await paid_test_calls.own_caller_number(
                session, tenant_id=trial_tenant, agent_id=trial_agent
            )
            is None
        )
    tenant_id, agent_id, _principal, workspace = await _paid_with_a_number_in(line, monkeypatch)
    # Its only number is in another workspace: none it can ring from here.
    await _number(tenant_id, _workspace())
    async with tenant_session(tenant_id) as session:
        assert await paid_test_calls.own_test_workspace(session, tenant_id=tenant_id) is None
    del agent_id, workspace


async def test_a_paying_account_with_no_number_tests_a_draft_campaign_from_the_shared_line(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal = await _paid_with_own_number(line, monkeypatch)
    workspace = _workspace()
    _client_workspace(monkeypatch, workspace)
    await _fill(tenant_id, agent_id, workspace)
    campaign_id = await _campaign(tenant_id, agent_id, script=SCRIPT)

    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            campaign_id=campaign_id,
        )

    assert placed.status == "queued", placed
    assert placed.caller_number == TRIAL_NUMBER, "it rings from our shared test line"
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
        call = (
            await session.execute(
                text("SELECT paid_test_call, trial_call FROM calls WHERE id = :c"),
                {"c": placed.call_id},
            )
        ).one()
    assert ref is not None and not str(ref).endswith(f"@{workspace}"), "it took a client slot"
    assert line.lent_to == [ref]
    assert call.paid_test_call, "a paying account's test call is billed as before"


async def test_a_running_campaigns_test_rings_through_its_own_engine_agent() -> None:
    tenant_id, agent_id = await _live_agent()
    running = await _campaign(tenant_id, agent_id, status="running")
    live_ref = f"{await _publish(tenant_id, running)}@{_workspace()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET engine_agent_ref = :r WHERE id = :c"),
            {"r": live_ref, "c": running},
        )
    tested = await engine_agent.campaign_test_dial(tenant_id=tenant_id, campaign_id=running)
    assert (tested.ref, tested.developer) == (live_ref, False)


async def test_a_paying_account_with_no_number_tests_a_draft_line_from_the_shared_line(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal = await _paid_with_own_number(line, monkeypatch)
    workspace = _workspace()
    _client_workspace(monkeypatch, workspace)
    await _fill(tenant_id, agent_id, workspace)
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )
        await lines.save_script(session, line_id, SCRIPT)

    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            line_id=line_id,
        )

    assert placed.status == "queued", placed
    assert placed.caller_number == TRIAL_NUMBER
    async with tenant_session(tenant_id) as session:
        held = await lines.read_line(session, line_id)
    assert held.engine_agent_ref and not held.engine_agent_ref.endswith(f"@{workspace}")
    assert not held.live


# ------------------------------------------------------------- 2. idle holders go back


async def test_an_idle_draft_lines_test_holder_is_retired_and_a_live_ones_kept() -> None:
    from apps.workers.campaign_engine_agents import _retire_unneeded

    tenant_id, agent_id = await _live_agent()
    async with tenant_session(tenant_id) as session:
        draft = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Draft", created_by=None
        )
        live = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Live", created_by=None
        )
        for line_id in (draft, live):
            await lines.save_script(session, line_id, SCRIPT)
    async with tenant_session(tenant_id) as session:
        await agents_service.publish_line(session, tenant_id=tenant_id, line_id=draft, test=True)
        await agents_service.publish_line(session, tenant_id=tenant_id, line_id=live)
    async with tenant_session(tenant_id) as session:
        # Fresh: an owner may be testing it again in a minute.
        assert await _retire_unneeded(session, tenant_id=tenant_id) == 0
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET updated_at = now() - interval '2 hours' "
                "WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        )
        assert await _retire_unneeded(session, tenant_id=tenant_id) == 1
        owed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE payload->>'tenant_id' = :t "
                    "AND job = :job"
                ),
                {"t": str(tenant_id), "job": agents_service.RETIRE_MOVED_AGENT_JOB},
            )
        ).scalar_one()
        refs = dict(
            (
                await session.execute(
                    text("SELECT id, engine_agent_ref FROM inbound_lines WHERE id = ANY(:ids)"),
                    {"ids": [draft, live]},
                )
            ).all()
        )
    assert refs[draft] is None and refs[live] is not None
    assert owed >= 1, "the vendor agent's deletion was not owed"


# --------------------------------------------------------- 3. the refusal names holders


async def _holders_account() -> tuple[UUID, UUID, str, dict[str, UUID]]:
    """An account whose workspace holds its agent, a live line, a running campaign and a
    campaign's engine agent being removed."""
    tenant_id, agent_id = await _live_agent()
    workspace = _workspace()
    engine = get_engine().name
    agent_ref = f"own_{uuid.uuid4().hex[:6]}@{workspace}"
    line_ref = f"line_{uuid.uuid4().hex[:6]}@{workspace}"
    run_ref = f"run_{uuid.uuid4().hex[:6]}@{workspace}"
    gone_ref = f"gone_{uuid.uuid4().hex[:6]}@{workspace}"
    running = await _campaign(tenant_id, agent_id, status="running")
    ended = await _campaign(tenant_id, agent_id, status="completed")
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"),
            {"r": agent_ref, "a": agent_id},
        )
        await session.execute(
            text(
                "UPDATE inbound_lines SET engine_agent_ref = :r, published_at = now() WHERE id = :l"
            ),
            {"r": line_ref, "l": line_id},
        )
        await session.execute(
            text("UPDATE campaigns SET engine_agent_ref = :r WHERE id = :c"),
            {"r": run_ref, "c": running},
        )
        await session.execute(
            text("UPDATE engine_agent_routes SET active = false WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        for ref, line_col, campaign_col in (
            (agent_ref, None, None),
            (line_ref, line_id, None),
            (run_ref, None, running),
            (gone_ref, None, ended),
        ):
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, inbound_line_id, campaign_id, active, created_at, updated_at) "
                    "VALUES (:e, :r, :t, :a, :l, :c, true, now(), now())"
                ),
                {
                    "e": engine,
                    "r": ref,
                    "t": tenant_id,
                    "a": agent_id,
                    "l": line_col,
                    "c": campaign_col,
                },
            )
    return tenant_id, agent_id, workspace, {"line": line_id, "running": running, "ended": ended}


async def test_the_holders_are_named_with_their_kind_and_id_and_never_another_accounts() -> None:
    tenant_id, agent_id, workspace, ids = await _holders_account()
    other_tenant, other_agent = await _live_agent()
    # Another account's engine agent under the same workspace name: the tenant filter, not
    # the workspace, keeps it out.
    await _fill(other_tenant, other_agent, workspace, count=1)
    async with tenant_session(tenant_id) as session:
        holders = await slot_holders(
            session, tenant_id=tenant_id, engine=get_engine().name, workspace=workspace
        )
    seen = {(h.kind, h.id, h.removing) for h in holders}
    assert seen == {
        ("agent", agent_id, False),
        ("inbound_line", ids["line"], False),
        ("campaign", ids["running"], False),
        ("campaign", ids["ended"], True),
    }
    assert all(h.id != other_agent for h in holders)
    assert {h.name for h in holders if h.kind == "inbound_line"} == {"Front desk"}
    async with tenant_session(other_tenant) as session:
        theirs = await slot_holders(
            session, tenant_id=other_tenant, engine=get_engine().name, workspace=workspace
        )
    assert [(h.kind, h.id) for h in theirs] == [("agent", other_agent)]


async def test_a_full_workspace_on_a_test_call_says_so_without_start_and_lists_holders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent_id, workspace, _ids = await _holders_account()
    monkeypatch.setattr(agents_service.get_settings(), "thinnest_agents_per_workspace", 2)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await agents_service._refuse_if_allowance_full(
                session, tenant_id=tenant_id, workspace=workspace, context="test_call"
            )
    problem = refused.value
    assert problem.code == ENGINE_AGENT_ALLOWANCE_FULL_RULE
    assert problem.detail.startswith(
        "Test calls need a free calling setup. Your account can have 2, and both are in use:"
    )
    assert "1 agent" in problem.detail and "1 being removed" in problem.detail
    for said in (problem.detail, problem.remediation or ""):
        assert "Start" not in said and "at once" not in said
    body = problem.as_problem()
    assert body["context"] == "test_call" and body["limit"] == 2
    assert len(body["holders"]) == 4
    assert {h["kind"] for h in body["holders"]} == {"agent", "inbound_line", "campaign"}
    assert isinstance(problem.extensions, EngineAgentAllowanceFull)


async def test_the_launch_check_names_the_holders_in_start_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, workspace, ids = await _holders_account()
    draft = await _campaign(tenant_id, agent_id)

    async def resolve(_session: Any, _tenant: UUID) -> str:
        return workspace

    monkeypatch.setattr(agents_service, "engine_has_workspaces", lambda *_a, **_k: True)
    monkeypatch.setattr(agents_service, "resolve_workspace", resolve)
    monkeypatch.setattr(agents_service.get_settings(), "thinnest_agents_per_workspace", 2)
    async with tenant_session(tenant_id) as session:
        blockers = await campaigns_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=draft
        )
    full = [b for b in blockers if b.rule == ENGINE_AGENT_ALLOWANCE_FULL_RULE]
    assert len(full) == 1
    assert full[0].reason.startswith("Starting needs a free calling setup.")
    assert "at once" not in full[0].reason
    assert {(h.kind, h.id) for h in full[0].holders} >= {
        ("agent", agent_id),
        ("campaign", ids["running"]),
    }
    # Pip reads the reason: it names kinds and counts, never a client-written name.
    assert "Front desk" not in full[0].reason


def test_the_refusal_is_published_for_the_typed_client() -> None:
    from apps.api.main import app

    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    full = schemas["EngineAgentAllowanceFull"]
    assert full["allOf"][0] == {"$ref": "#/components/schemas/ProblemBody"}
    assert set(full["allOf"][1]["properties"]) == {"context", "limit", "holders"}
    for path, method in (
        ("/v1/campaigns/{campaign_id}/test-call", "post"),
        ("/v1/campaigns/{campaign_id}/launch", "post"),
        ("/v1/inbound-lines/{line_id}/test-call", "post"),
    ):
        refs = spec["paths"][path][method]["responses"]["422"]["content"][
            "application/problem+json"
        ]["schema"]["oneOf"]
        assert {"$ref": "#/components/schemas/EngineAgentAllowanceFull"} in refs, path
    blocker = schemas["BlockerOut"]["properties"]["holders"]
    assert json.dumps(blocker).count("SlotHolder") >= 1


def _holder(kind: Any, *, removing: bool = False) -> SlotHolder:
    return SlotHolder(kind=kind, id=uuid.uuid4(), name="x", removing=removing)


def test_remediation_names_only_what_the_owner_can_free() -> None:
    both = allowance_remediation([_holder("inbound_line"), _holder("campaign")])
    assert both == (
        "Archive an inbound line you no longer use or stop a campaign to free one. "
        "To have more, ask us to raise your limit."
    )
    assert allowance_remediation([_holder("campaign"), _holder("agent")]).startswith(
        "Stop a campaign to free one."
    )


def test_remediation_for_setups_the_owner_cannot_free_asks_us() -> None:
    # Two agents still holding setups of their own: archiving a line or stopping a
    # campaign frees nothing, so the owner is not told to.
    agents = [_holder("agent"), _holder("agent")]
    assert allowance_remediation(agents) == "Ask us to free one or to raise your limit."
    # A line already being removed is not one the owner can archive again.
    assert allowance_remediation(
        [_holder("inbound_line", removing=True), _holder("test_call")]
    ) == ("Ask us to free one or to raise your limit.")
