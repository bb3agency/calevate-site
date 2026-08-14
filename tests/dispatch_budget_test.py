"""The tick's BUDGET arithmetic and its refusals to dial (FLOWS §5 rules 1-4).

`campaign_dispatch_audit_test.py` attacks the paperwork that can lapse under a running
campaign; `campaigns_test.py` proves the launch gate; `dispatch_scale_test.py` measures
the scan. What none of them exercises is the arithmetic that decides HOW MANY dials a
tick may place, and every branch of it is a way for the dispatcher to place a call it
should not have:

1. `platform_lines_total` minus the inbound reserve is the OUTBOUND pool. When the
   reserve swallows the pool there is nothing to spend, and dialling anyway would eat
   the lines another client's receptionist answers on;
2. the pool is spent ONCE across the campaigns of a tick — the second campaign gets
   what the first left, not its own copy;
3. a campaign the client paused between the scan and the budget read is not dialled:
   the scan is a stale observation by construction, and the client wins that race;
4. a contact whose retry ladder is spent on an engine refusal is FAILED and counted,
   not re-rung forever.

The tick is driven through `_run_tick`/`_dispatch_for_campaign` rather than
`dispatch_campaign_tick` so no test in this file takes the platform-wide tick lease —
that lease has its own suite (`dispatch_tick_lease_test.py`), and holding it here would
make two suites contend for one Redis key. Where a test needs the platform's view of
who is holding lines to be a KNOWN number, `_tenants_with_work` is pinned: it is one
query whose own correctness is proved in `campaign_schedule_test` and
`dispatch_scan_rls_test`, and leaving it live would make the arithmetic under test
depend on what every other suite has in flight.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service as campaigns
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import ACTIVE_STATUSES, TenantWork
from calevate_shared.engine import CallContext
from sqlalchemy import text


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST — inside the platform window, so nothing here is refused by the clock."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


_TENANTS: list[uuid.UUID] = []


@pytest.fixture(scope="module", autouse=True)
async def _settle_what_this_module_started() -> AsyncIterator[None]:
    """Leave the shared platform as quiet as we found it — the same reasoning as
    `campaign_dispatch_audit_test`: a `running` campaign left behind is dialled by every
    later platform-wide tick, and a live `calls` row spends a line out of the shared
    pool for an hour. Scoped to the tenants this module created."""
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'cancelled', updated_at = now() "
                    "WHERE status IN ('running', 'paused')"
                )
            )
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    f"WHERE status IN {ACTIVE_STATUSES!r}"
                )
            )


# ------------------------------------------------------------------ fixtures (rows)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose agent is live, published and routable, with its PE paperwork."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Budget Motors",
        slug=f"budg-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_budg_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :ref WHERE id = :a"
            ),
            {"ref": ref, "a": agent_id},
        )
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Budget Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _dlt_rows(tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    number_id, template_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, created_at, "
                "updated_at) VALUES (:id, :tid, :e, '140', 'registered', now(), now())"
            ),
            {"id": number_id, "tid": tenant_id, "e": f"+9180{uuid.uuid4().int % 100000000:08d}"},
        )
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
        )
    return number_id, template_id


async def _launched_campaign(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    number_id: uuid.UUID,
    template_id: uuid.UUID,
    *,
    name: str,
    phones: tuple[str, ...],
    slider: int = 3,
) -> uuid.UUID:
    """One campaign through the REAL launch gate — nothing here is a shortcut past it."""
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=slider,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await campaigns.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
        )
        await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    return campaign_id


async def _contacts(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> list[tuple[str, int]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT status, attempts FROM campaign_contacts WHERE campaign_id = :c "
                    "ORDER BY created_at, id"
                ),
                {"c": campaign_id},
            )
        ).all()
    return [(str(r[0]), int(r[1])) for r in rows]


async def _calls_placed(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM calls WHERE direction = 'outbound'")
                )
            ).scalar()
            or 0
        )


def _capture_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        campaign_dispatch,
        "alert",
        lambda stage, code, **kwargs: fired.append((stage, code)),
    )
    return fired


def _pin_scan(monkeypatch: pytest.MonkeyPatch, work: list[TenantWork]) -> None:
    async def _scan() -> list[TenantWork]:
        return work

    monkeypatch.setattr(campaign_dispatch, "_tenants_with_work", _scan)


# ------------------------------------------------------- rule 1+2: the shared pool


async def test_a_reserve_that_swallows_the_pool_stops_every_dial_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FLOWS §5 rules 1+2: the outbound pool is the platform's lines MINUS the inbound
    reserve. When the reserve is the whole switchboard the pool is zero, and the only
    correct number of dials is zero — spending it anyway takes the line another client's
    receptionist answers on, which rule 1 exists to protect.

    It is also an operator-visible condition rather than a quiet stop: a platform whose
    campaigns have silently stopped dialling looks exactly like a platform with nothing
    to dial, so the tick alerts instead of returning quietly.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Squeezed", phones=("9876610001",)
    )
    # Fewer total lines than the minimum inbound reserve: reserve >= total, pool = 0.
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 3)
    assert campaign_dispatch.MIN_INBOUND_RESERVE == 4, "the fixture depends on this floor"
    fired = _capture_alerts(monkeypatch)

    outcome = await campaign_dispatch._run_tick()

    assert outcome == "no_outbound_pool", outcome
    assert fired == [("WORKER_STALL", "outbound_pool_empty")], fired
    assert await _calls_placed(tenant_id) == 0, "no pool, no dial"
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0)], (
        "and no attempt burned: the tick stopped before claiming anything"
    )


async def test_the_shared_pool_is_spent_once_and_the_second_campaign_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule 1+2 again, from the other side: `global_budget` is what is LEFT of the pool
    after every tenant's live calls, and it is decremented by each campaign that dials.

    Two campaigns, one line left. The first spends it; the second must claim nothing at
    all — not "claim and refuse", which would burn an attempt off every contact it
    touched. A dispatcher that recomputed the budget per campaign would dial both, and
    the extra call comes out of the inbound reserve.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id)
    first = await _launched_campaign(
        tenant_id,
        agent_id,
        number_id,
        template_id,
        name="First in the queue",
        phones=("9876620001", "9876620002"),
    )
    second = await _launched_campaign(
        tenant_id,
        agent_id,
        number_id,
        template_id,
        name="Second in the queue",
        phones=("9876620003", "9876620004"),
    )

    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10)
    # pool = 10 - max(4, 10*0.3) = 6, and five of those lines are already busy
    # platform-wide, so exactly one dial may be placed this tick.
    _pin_scan(monkeypatch, [TenantWork(tenant_id, 5, True, False)])

    outcome = await campaign_dispatch._run_tick()

    assert outcome.startswith("dialled=1 "), outcome
    assert await _calls_placed(tenant_id) == 1, "the pool held one line and one call went out"
    assert [status for status, _ in await _contacts(tenant_id, first)] == ["dialing", "pending"], (
        "the oldest campaign spends the last line, one contact at a time"
    )
    assert await _contacts(tenant_id, second) == [("pending", 0), ("pending", 0)], (
        "the second campaign is not even claimed: no attempts spent waiting for a line"
    )


# ------------------------------- rule 3: the scan is stale, and the client wins races


async def test_a_campaign_paused_between_the_scan_and_the_budget_read_is_not_dialled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`dispatch_scan()` runs in its own transaction, so by the time the tick reads a
    tenant's budget the client may have hit Pause — or a complaint spike may have
    auto-paused the campaign (FLOWS §5's mid-campaign safeties). That race is one the
    client WINS: the budget read returns no running campaigns and the tick moves on,
    costing one session and no dial.

    A pause that still dials the contacts a tick had lined up is a pause the client does
    not believe in, and "stopping fast" is the entire point of those safeties.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Paused", phones=("9876630001",)
    )
    async with tenant_session(tenant_id) as session:
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )
    # The scan's answer, as it was a moment BEFORE the pause committed.
    _pin_scan(monkeypatch, [TenantWork(tenant_id, 0, True, False)])

    outcome = await campaign_dispatch._run_tick()

    assert outcome == "no_running_campaigns started=0", outcome
    assert await _calls_placed(tenant_id) == 0, "a paused campaign dials nobody"
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0)]


# --------------------------------------------- rule 4: the ladder ends, and it counts


class _RefusingEngine(FakeEngine):
    """The engine accepting the agent but refusing the dial — a vendor 5xx, a rate
    limit, a number the carrier will not route."""

    async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
        raise RuntimeError("engine refused the dial")


async def test_a_contact_whose_last_attempt_the_engine_refused_is_failed_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry ladder has an END, and the end is reported.

    A dial the engine refuses walks the contact down the ladder; on the last rung the
    contact goes `failed` and the tick counts an exhaustion — which is what turns "we
    never reached this lead" into an escalation the client can act on
    (`enqueue_campaign_escalation`, FLOWS §4.5) instead of a contact that is quietly
    retried forever.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Last rung", phones=("9876640001",)
    )
    # Two attempts already spent; the claim below burns the third and last.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaign_contacts SET attempts = 2 WHERE campaign_id = :c"),
            {"c": campaign_id},
        )

    monkeypatch.setattr("apps.api.agents.service.get_engine", lambda: _RefusingEngine())

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    assert result == {"dialled": 0, "blocked": 0, "exhausted": 1}, result
    assert await _contacts(tenant_id, campaign_id) == [("failed", 3)], (
        "the ladder is spent, so the contact stops rather than being re-claimed"
    )
    assert await _calls_placed(tenant_id) == 0, "a refused dial writes no call row"
    async with tenant_session(tenant_id) as session:
        escalations = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages "
                    "WHERE payload->>'campaign_id' = :c AND job LIKE '%escalat%'"
                ),
                {"c": str(campaign_id)},
            )
        ).scalar()
    assert int(escalations or 0) == 1, "the exhausted contact is escalated exactly once"


async def test_the_ladder_still_ends_when_the_caller_has_no_campaign_to_escalate_to() -> None:
    """`_record_failure`'s two optional ids are the escalation's context, and its
    docstring promises that without them the contact is still failed correctly and the
    escalation is SKIPPED rather than guessed at.

    Guessing would be the harmful half: an escalation carrying the wrong campaign id
    messages a person about an enquiry they never made. Failing to fail the contact
    would be the other: it stays claimable and the ladder never ends.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="No context", phones=("9876650001",)
    )
    async with tenant_session(tenant_id) as session:
        contact_id = (
            await session.execute(
                text("SELECT id FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar()

        spent = await campaign_dispatch._record_failure(
            session, uuid.UUID(str(contact_id)), 3, 3, campaigns.DEFAULT_RETRY_POLICY
        )

    assert spent is True, "three of three attempts is a spent ladder"
    assert await _contacts(tenant_id, campaign_id) == [("failed", 0)]
    async with tenant_session(tenant_id) as session:
        escalations = (
            await session.execute(
                text("SELECT count(*) FROM outbox_messages WHERE payload->>'contact_id' = :c"),
                {"c": str(contact_id)},
            )
        ).scalar()
    assert int(escalations or 0) == 0, "no context, no message — never a guessed one"


# ------------------------------------------------- the campaign's own status is theirs


async def test_a_campaign_cancelled_during_a_tick_is_not_written_back_to_completed() -> None:
    """The tick ends by settling a campaign with nothing left to dial. That settlement
    is a CAS off `running` (`complete_or_rearm`), so a campaign the client cancelled
    mid-tick keeps the status the client chose.

    Without the CAS the last act of the tick would overwrite `cancelled` with
    `completed` — and a cancelled campaign that reads as completed is one nobody
    investigates, on the surface where "why did this keep dialling" gets asked.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Cancelled", phones=("9876660001",)
    )
    async with tenant_session(tenant_id) as session:
        # Everybody has been reached, and then the client cancels — the state a tick
        # arriving one moment later finds.
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'connected', updated_at = now() "
                "WHERE campaign_id = :c"
            ),
            {"c": campaign_id},
        )
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="cancelled", from_statuses=("running",)
        )

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    assert result == {"dialled": 0, "blocked": 0, "exhausted": 0}, result
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert str(status) == "cancelled", "the client's cancel outlives the tick that raced it"
    assert await _calls_placed(tenant_id) == 0


async def test_a_campaign_cannot_be_created_with_a_slider_of_zero() -> None:
    """Why `slots > 0` in the tick is a guard rather than a reachable branch.

    The tick computes `slots = min(slider, tenant_budget)` AFTER breaking out when the
    budget is spent, so the only way to reach zero there is a campaign whose own slider
    is zero — and the database refuses to hold one (`concurrency BETWEEN 1 AND 10`,
    migration e16c96e68bc5). This test is the check on that claim: if the constraint is
    ever relaxed, it fails here and the branch needs a test of its own rather than an
    argument.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id)

    with pytest.raises(Exception) as excinfo:
        async with tenant_session(tenant_id) as session:
            await campaigns.create_campaign(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Zero slider",
                classification="promotional",
                number_id=number_id,
                dlt_template_id=template_id,
                concurrency=0,
                consent_source="existing_customer",
                consent_collected_at=datetime.now(UTC) - timedelta(days=7),
            )

    assert "concurrency" in str(excinfo.value), excinfo.value
