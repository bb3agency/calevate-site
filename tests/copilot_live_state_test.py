"""The copilot's LIVE STATE block against real rows: the counts, and the tenancy.

The string-shaped properties (token ceiling, degradation markers, prompt order, no PII)
are `apps/api/copilot/context_test.py`. What needs a database is the pair below, and the
second one is the mandatory one: this block puts a tenant's business numbers into a prompt
sent to a US model, so "tenant A's block never carries tenant B's numbers" is hard rule 1
asserted at the surface that would leak it.
"""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from apps.api.admin import service as admin_service
from apps.api.copilot import context
from apps.api.copilot.prompt import CLOSING_RULES, SCREEN_CLOSE, build_messages
from apps.api.copilot.schemas import CopilotAskIn
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.legal.readiness import readiness_rows
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession


async def _tenant(name: str) -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name=name,
        slug=f"live-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, days_ago: int = 0) -> None:
    """One completed call, `days_ago` days back. Written with `started_at` set, because
    the block's "today" counts calls that started (`context._COUNTS_SQL`)."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, duration_s, started_at, created_at, updated_at) "
                "VALUES (:i, :t, :a, :e, 'outbound', '+919876500001', 'completed', 60, "
                "  now() - make_interval(days => :d), now() - make_interval(days => :d), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "e": f"live_{uuid.uuid4().hex[:12]}",
                "d": days_ago,
            },
        )


async def _lead(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, status: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, :p, 'inbound_call', :s, "
                "now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "p": f"+9198{uuid.uuid4().int % 100000000:08d}",
                "s": status,
            },
        )


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, status: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "status, concurrency, created_at, updated_at) VALUES (:i, :t, :a, :n, "
                "'service', :s, 3, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                # A campaign NAME, deliberately distinctive: the block must not carry it.
                "n": f"Kondapur reminders {uuid.uuid4().hex[:6]}",
                "s": status,
            },
        )


async def test_the_block_reports_what_the_tenant_actually_has() -> None:
    """Counts, from real rows, through the one statement — including the zeros, which are
    an answer ("no hot leads") rather than an absence ("could not read")."""
    tenant_id, agent_id = await _tenant("Live Clinic")
    await _call(tenant_id, agent_id)
    await _call(tenant_id, agent_id)
    await _call(tenant_id, agent_id, days_ago=3)
    # Older than the rolling window and older than today: in neither number.
    await _call(tenant_id, agent_id, days_ago=30)
    for status in ("hot", "hot", "interested", "new", "won", "lost"):
        await _lead(tenant_id, agent_id, status=status)
    await _campaign(tenant_id, agent_id, status="running")
    await _campaign(tenant_id, agent_id, status="draft")
    await _campaign(tenant_id, agent_id, status="completed")

    async with tenant_session(tenant_id) as session:
        state = await context.read_live_state(session, tenant_id=tenant_id)

    assert state.counts is not None
    assert state.counts.calls_today == 2
    assert state.counts.calls_last_7_days == 3
    # `won` and `lost` are not waiting on anybody; `contacted` is not a waiting status.
    assert state.counts.leads_waiting == {"hot": 2, "interested": 1, "new": 1}
    assert state.counts.campaigns == {"running": 1, "paused": 0, "scheduled": 0, "draft": 1}
    # THE TOTAL IS EVERY STATUS, NOT THE WAITING THREE (D-497). Six leads went in; four of
    # them are in a waiting status and `won` and `lost` are the two that used to be
    # invisible. A block that reported 4 here would be the bug this field exists to fix.
    assert state.counts.leads_total == 6
    assert state.counts.leads_last_7_days == 6
    # `create_organization` seeds exactly one agent, and it starts as a draft.
    assert state.counts.agents == {"live": 0, "paused": 0, "draft": 1}
    # THE BLOCKERS ARE THE GATES' OWN ANSWER, NOT A SECOND DERIVATION. Asserted against
    # `readiness_rows` for the same tenant rather than against a hand-written list: a
    # literal here would be this test agreeing with a copy of the compliance rules, which
    # is the drift `context.py` refuses to introduce. A brand-new organisation really is
    # blocked (no DLT Principal Entity, no accepted agreements), and the block says so.
    async with tenant_session(tenant_id) as session:
        expected = tuple(row.rule for row in await readiness_rows(session, tenant_id=tenant_id))
    assert state.blocker_rules == expected
    assert "pe_registration_missing" in expected, "a fresh org has not registered its PE"
    assert not state.partial

    rendered = context.render_live(state)
    assert '<calls today="2" last_7_days="3"/>' in rendered
    assert '<leads total="6" last_7_days="6"/>' in rendered
    assert '<leads_waiting hot="2" interested="1" new="1"/>' in rendered
    assert '<agents live="0" paused="0" draft="1"/>' in rendered
    assert "Kondapur" not in rendered, "a campaign NAME is tenant-authored text and costs tokens"


@pytest.mark.rls
async def test_one_tenants_block_never_carries_anothers_numbers() -> None:
    """HARD RULE 1 AT THE SURFACE THAT WOULD LEAK IT. This block is assembled server-side
    and sent to a model — a query that forgot its scope would put one client's pipeline in
    another client's prompt, and nothing downstream could catch it.

    The isolation is RLS's, not this module's: `read_live_state` takes the session it is
    given and `tenant_session` is what scopes it. That is exactly why the test drives the
    real session rather than the SQL.
    """
    quiet_id, _quiet_agent = await _tenant("Quiet Clinic")
    busy_id, busy_agent = await _tenant("Busy Clinic")

    for _ in range(5):
        await _call(busy_id, busy_agent)
    for _ in range(4):
        await _lead(busy_id, busy_agent, status="hot")
    await _campaign(busy_id, busy_agent, status="running")

    async with tenant_session(quiet_id) as session:
        quiet = await context.read_live_state(session, tenant_id=quiet_id)
    async with tenant_session(busy_id) as session:
        busy = await context.read_live_state(session, tenant_id=busy_id)

    assert quiet.counts is not None and busy.counts is not None
    assert quiet.counts.calls_today == 0
    assert quiet.counts.leads_waiting["hot"] == 0
    assert quiet.counts.campaigns["running"] == 0
    assert quiet.counts.leads_total == 0
    assert busy.counts.calls_today == 5
    assert busy.counts.leads_waiting["hot"] == 4
    assert busy.counts.campaigns["running"] == 1
    # THE CROSS-TENANT ZERO FOR EVERY NEW COUNT (hard rule 1). The busy tenant has four
    # leads and an agent of its own; the quiet tenant's total and roster must not see them.
    assert busy.counts.leads_total == 4
    assert quiet.counts.agents["draft"] == 1, "its own seeded agent, and only its own"
    assert busy.counts.agents["draft"] == 1

    # And the rendered artefact — the thing that actually reaches the model.
    assert '<calls today="0" last_7_days="0"/>' in context.render_live(quiet)
    assert '<leads total="0" last_7_days="0"/>' in context.render_live(quiet)
    assert '<leads_waiting hot="0" interested="0" new="0"/>' in context.render_live(quiet)


async def test_the_block_is_composed_from_a_tenant_id_alone_and_never_raises() -> None:
    """`live_state_block` is what the route calls: it opens its own short session, closes
    it before the first token, and hands back a string. A tenant that does not exist is
    the failure closest to hand — RLS answers it with zero rows rather than an error, and
    the readiness gates fail CLOSED, so the block is still a block."""
    tenant_id, agent_id = await _tenant("Block Clinic")
    await _lead(tenant_id, agent_id, status="hot")

    rendered = await context.live_state_block(tenant_id)
    assert context.LIVE_OPEN in rendered
    assert '<leads_waiting hot="1"' in rendered

    stranger = await context.live_state_block(uuid7())
    assert context.LIVE_OPEN in stranger
    assert '<calls today="0"' in stranger
    # `account_stopped_blocker` fails closed on a row it cannot see — the account is
    # reported as blocked rather than as fine, which is the gates' own answer.
    assert '<blocker rule="account_missing"/>' in stranger


class _DeadSession:
    """A session whose every statement fails — what a `statement_timeout`, a killed
    backend or an exhausted pool looks like from inside this module."""

    async def execute(self, *args: object, **kwargs: object) -> object:
        raise OperationalError("SELECT 1", {}, Exception("connection reset"))


async def test_a_failing_snapshot_degrades_instead_of_taking_the_answer_down() -> None:
    """PROPERTY 3, end to end. Both halves are read through the same dead session, both
    fail, and `read_live_state` still returns a `LiveState` — marked partial, rendering
    `unavailable` rather than zeros. A copilot that 500s because a `count(*)` timed out is
    worse than one that says less, and a copilot that reports 0 calls because it could not
    count them is worse than either."""
    state = await context.read_live_state(cast("AsyncSession", _DeadSession()), tenant_id=uuid7())
    assert state.counts is None
    assert state.blocker_rules is None
    assert state.partial
    rendered = context.render_live(state)
    assert '<unavailable part="activity"/>' in rendered
    assert '<unavailable part="outbound_blockers"/>' in rendered

    # And the prompt around it is intact: screen, block, rules, question, in that order.
    payload = CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/x/leads", "title": "Leads", "realm": "client"},
            "question": "what should I do first?",
        }
    )
    last = str(build_messages(payload, rendered)[-1]["content"])
    assert last.index(SCREEN_CLOSE) < last.index(context.LIVE_OPEN) < last.index(CLOSING_RULES)


async def test_a_session_that_cannot_even_open_yields_no_block_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one failure `read_live_state` cannot absorb, because it happens before there is
    anything to read. `live_state_block` swallows it and returns "", and the copilot runs
    on the screen block alone — exactly as it did before this module existed."""

    def _refuse(_tenant_id: uuid.UUID) -> object:
        raise OperationalError("BEGIN", {}, Exception("pool exhausted"))

    monkeypatch.setattr(context, "tenant_session", _refuse)
    assert await context.live_state_block(uuid7()) == ""
