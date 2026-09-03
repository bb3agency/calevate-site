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
4. a dial that does not connect ENDS the contact, and the two ways it can fail are not
   the same rule: a vendor refusal that proves no line was seized walks the retry
   ladder and ends it on the last rung, while one that cannot rule out a ringing phone
   ends the contact immediately, whatever rung it was on. Both are counted, and neither
   is re-rung forever.

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
from apps.api.agents.service import UNCONFIRMED_ENGINE_CALL_PREFIX
from apps.api.campaigns import service as campaigns
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.api.engine.vendor_http import EngineRejectedError
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import ACTIVE_STATUSES, TenantWork
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.national_dnd_test import record_test_scrub


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
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
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


async def _dlt_rows(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """ONE registered 140 header bound to `agent_id`, and one approved template (D-424).

    One, and shared by every campaign in a test: the launch gate refuses a campaign whose
    approved number is not the number its agent dials from, and `resolve_caller_id`
    refuses an agent that carries two registered headers. A header per campaign would
    satisfy the first rule by breaking the second, and the dispatcher under test here
    would then place no calls while the budget assertions still read green.
    """
    number_id, template_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, '140', 'registered', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
            },
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
        # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9).
        # A promotional campaign is launch-ready only once an access provider has
        # preference-scrubbed its list, so this fixture supplies the fact through the
        # production writer — `tests/national_dnd_test.py` proves the refusal is real.
        await record_test_scrub(session, campaign_id)
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


def _capture_alert_details(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Like `_capture_alerts`, but keeps the `detail` — an alarm whose detail does not
    name WHO was starved is a page with no next step, so the detail is under test."""
    fired: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        campaign_dispatch,
        "alert",
        lambda stage, code, **kwargs: fired.append((stage, code, str(kwargs.get("detail", "")))),
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
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
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
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
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
    _pin_scan(monkeypatch, [TenantWork(tenant_id, 5, True, False, False)])

    outcome = await campaign_dispatch._run_tick()

    assert outcome.startswith("dialled=1 "), outcome
    assert await _calls_placed(tenant_id) == 1, "the pool held one line and one call went out"
    assert [status for status, _ in await _contacts(tenant_id, first)] == ["dialing", "pending"], (
        "the oldest campaign spends the last line, one contact at a time"
    )
    assert await _contacts(tenant_id, second) == [("pending", 0), ("pending", 0)], (
        "the second campaign is not even claimed: no attempts spent waiting for a line"
    )


# ------------------------------------ the spend order does not rotate, and says so


async def test_a_tenant_that_gets_no_line_before_the_budget_runs_out_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**Starvation is indefinite here, so it must not also be invisible.**

    The tick spends `global_budget` down `running` in `dispatch_scan()`'s order, which is
    `ORDER BY tenant_id` over uuid_v7 — TIME-ORDERED. Nothing rotates, so the tenant at
    the tail of a saturated pool dials zero on this tick and on every following tick,
    while the tick's own return string reports a perfectly healthy `dialled=1`.

    The fix here is deliberately NOT rotation (see the comment at the `break` in
    `_run_tick`: floors-then-proportional-surplus is the durable answer and it is a plan
    column, and a second ordering mechanism would have to be removed again). What is
    fixed is that the fact is now recoverable by an operator: a count in the return
    string and an alarm naming the tenant ids.

    Two tenants, one line left. The first spends it; the second must be REPORTED, not
    merely skipped.
    """
    first_id, first_agent = await _tenant()
    second_id, second_agent = await _tenant()
    first_number, first_template = await _dlt_rows(first_id, first_agent)
    second_number, second_template = await _dlt_rows(second_id, second_agent)
    await _launched_campaign(
        first_id,
        first_agent,
        first_number,
        first_template,
        name="Ahead in the order",
        phones=("9876640001",),
    )
    starved_campaign = await _launched_campaign(
        second_id,
        second_agent,
        second_number,
        second_template,
        name="Behind in the order",
        phones=("9876640002",),
    )

    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10)
    # pool = 6, five lines already busy platform-wide: exactly one dial this tick, and
    # the tenant holding those five is ahead in the spend order.
    _pin_scan(
        monkeypatch,
        [TenantWork(first_id, 5, True, False, False), TenantWork(second_id, 0, True, False, False)],
    )
    fired = _capture_alert_details(monkeypatch)

    outcome = await campaign_dispatch._run_tick()

    assert " starved=1" in outcome, outcome
    assert outcome.startswith("dialled=1 "), (
        "the tick looks healthy from its dial count alone — that is the whole problem"
    )
    assert [(stage, code) for stage, code, _ in fired] == [
        ("WORKER_STALL", "dispatch_budget_starved")
    ], fired
    detail = fired[0][2]
    assert str(second_id) in detail, "an alarm that does not name who was starved is a dead end"
    assert str(first_id) not in detail, "the tenant that DID dial is not starved"
    assert "9876640002" not in detail, "hard rule 6: ids, never phone numbers"
    assert await _calls_placed(second_id) == 0
    assert await _contacts(second_id, starved_campaign) == [("pending", 0)], (
        "and no attempt burned on the tenant that never got a line"
    )


# ------------------- rule 3 under rules 1+2: a ceiling above the pool is not a ceiling


async def test_a_tenant_ceiling_can_never_exceed_the_pool_that_exists() -> None:
    """The relationship between the two constants is ASSERTED here, not coincidental.

    This shipped as `PLATFORM_LINES_TOTAL = 10`, `MIN_INBOUND_RESERVE = 4` (outbound pool
    = 6) and `DEFAULT_CONCURRENCY_CEILING = 10` — a per-tenant ceiling half again larger
    than the entire platform, which is not a ceiling at all. It was only ever safe
    because a SECOND check downstream (`global_budget`) happened to catch it.

    Two things are asserted, because two different edits break this:

    1. the default ceiling is DERIVED from the line total, so raising one without the
       other is not something a person can do by typing;
    2. `_tenant_ceiling` clamps, so a `plans` row selling 50 lines on a 6-line platform
       narrows to 6 rather than granting a tenant the switchboard.
    """
    assert campaign_dispatch.DEFAULT_CONCURRENCY_CEILING <= campaign_dispatch.PLATFORM_LINES_TOTAL
    pool = campaign_dispatch._outbound_pool()
    assert pool > 0, "the fixture depends on a non-empty pool"
    for configured in (None, 0, 1, pool, pool + 1, 50, 10_000):
        effective = campaign_dispatch._tenant_ceiling(configured, pool)
        assert 0 <= effective <= pool, (configured, effective, pool)
    assert campaign_dispatch._tenant_ceiling(None, pool) == pool, (
        "a tenant with no plans row gets the pool, not a number typed beside it"
    )
    assert campaign_dispatch._tenant_ceiling(2, pool) == 2, "the clamp narrows, never widens"


async def test_a_ceiling_above_the_pool_does_not_let_one_tenant_claim_lines_that_do_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One tenant, three campaigns, a 6-line pool and no `plans` row.

    Rule 3 is a TENANT budget spent once across that tenant's campaigns. With the ceiling
    clamped to the pool that budget is 6, so the third campaign is never handed slots —
    the tick does not promise lines the platform does not have. With the shipped ceiling
    of 10 it WAS handed slots: the tenant claimed 9 lines out of a 6-line platform and
    the surplus was only caught by the platform budget one loop later.

    `_dispatch_for_campaign` is pinned so the slots the tick HANDS OUT are observable
    rather than inferred from dials — and returning zero dials keeps `global_budget`
    from masking the tenant-level arithmetic under test, which is exactly the masking
    that let this defect ship.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    for name in ("First", "Second", "Third"):
        await _launched_campaign(
            tenant_id,
            agent_id,
            number_id,
            template_id,
            name=f"{name} of three",
            phones=(f"98766{abs(hash(name)) % 100000:05d}",),
        )
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10)
    pool = campaign_dispatch._outbound_pool()
    assert pool == 6, pool
    _pin_scan(monkeypatch, [TenantWork(tenant_id, 0, True, False, False)])

    handed: list[int] = []

    async def _record(
        _t: uuid.UUID, _c: uuid.UUID, slots: int, _r: dict[str, object]
    ) -> dict[str, int]:
        handed.append(slots)
        return {"dialled": 0, "blocked": 0, "exhausted": 0}

    monkeypatch.setattr(campaign_dispatch, "_dispatch_for_campaign", _record)

    await campaign_dispatch._run_tick()

    assert sum(handed) <= pool, (
        f"the tick handed one tenant {sum(handed)} lines out of a {pool}-line platform"
    )
    assert handed == [3, 3], handed


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
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Paused", phones=("9876630001",)
    )
    async with tenant_session(tenant_id) as session:
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )
    # The scan's answer, as it was a moment BEFORE the pause committed.
    _pin_scan(monkeypatch, [TenantWork(tenant_id, 0, True, False, False)])

    outcome = await campaign_dispatch._run_tick()

    assert outcome == "no_running_campaigns started=0 callbacks=0", outcome
    assert await _calls_placed(tenant_id) == 0, "a paused campaign dials nobody"
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0)]


# --------------------------------------------- rule 4: the ladder ends, and it counts


class _RefusingEngine(FakeEngine):
    """The engine raising out of the vendor call ITSELF — a 5xx, a reset, a proxy that
    gave up after the request had already gone.

    Not a rate limit, which this used to name and which now belongs to
    `_ThrottledEngine` below. D-181 turns on exactly that distinction: a failure raised
    from inside the call cannot rule out a ringing phone, so `dispatch_call` answers
    `DialUnconfirmedError`; one refused before the request left the process can, so the
    original `ProblemError` propagates and the retry ladder still means something.
    """

    async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
        raise RuntimeError("engine refused the dial")


async def test_a_dial_the_vendor_may_have_started_ends_the_contact_rather_than_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ladder is NOT walked when the phone may already be ringing.

    D-181's third outcome on the campaign path. The engine raised from inside the vendor
    call, so nothing here can say whether a line was seized — and a retry would be a
    second unsolicited call to somebody who may already have been rung, which is the
    thing the compliance gate exists to prevent. The contact is therefore settled
    TERMINALLY, whatever rung it was on, and the tick counts it: from the client's side
    this lead was not reached and nobody will try again, so the escalation
    (`enqueue_campaign_escalation`, FLOWS §4.5) is all that stands between them and
    silence.

    The sibling below is the other half — a refusal that PROVES no line was seized,
    which does walk the ladder — and the two are told apart by the `calls` row rather
    than by the count: the unconfirmed intent row asserted here keeps the id we minted,
    while the refused one is closed as `failed`.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Last rung", phones=("9876640001",)
    )
    # Two attempts already spent; the claim below burns the third. Both outcomes end
    # the contact here, which is why the assertions below reach for the call row.
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
    # ONE call row, and it is the INTENT row (D-181): the engine raised out of
    # `start_outbound_call` with no code that proves it seized no line, so the platform
    # records a call it may have been charged for rather than nothing at all. The
    # `engine_call_id` is one we minted, which is how that state is told apart from a
    # dial the vendor named.
    assert await _calls_placed(tenant_id) == 1
    async with tenant_session(tenant_id) as session:
        engine_call_id = (
            await session.execute(
                text("SELECT engine_call_id FROM calls WHERE direction = 'outbound'")
            )
        ).scalar()
    assert str(engine_call_id).startswith(UNCONFIRMED_ENGINE_CALL_PREFIX), engine_call_id
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


class _ThrottledEngine(FakeEngine):
    """The engine refusing the dial with a code that PROVES no line was seized.

    `engine_rate_limited` is the adapter's own 429-with-the-ladder-exhausted, and the
    adapter raises it instead of sending the request. That is the difference this class
    exists to express: `_RefusingEngine` above raises out of the vendor call and cannot
    rule out a ringing phone, so `dispatch_call` answers `DialUnconfirmedError`; this one
    is refused BEFORE the request leaves the process, so the original `ProblemError`
    propagates and the contact keeps its retry ladder.
    """

    async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
        raise ProblemError(
            kind="dependency",
            code="engine_rate_limited",
            title="Voice engine is throttling us",
            detail="The voice platform refused the request without placing a call.",
        )


async def test_a_refusal_that_proves_no_line_was_seized_spends_the_ladder_and_counts_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OTHER end of the ladder, and the one D-181 left untested.

    `DIAL_NOT_PLACED_CODES` is the whole reason the ladder still exists after D-181: a
    vendor refusal that happened before any request went out is the only kind that can
    honestly be retried, so it is the only kind routed to `_record_failure` rather than
    to the terminal unconfirmed path. When that refusal lands on the LAST rung the
    contact is finished with, and the tick must count it — `exhausted` is what turns
    "this lead was never reached" into an escalation somebody acts on.

    The call row is where the two outcomes are told apart, and it is asserted here for
    that reason: `failed`, because the vendor proved nothing rang, rather than the
    `queued` intent row the unconfirmed path deliberately leaves for the reaper.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Throttled", phones=("9876660001",)
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaign_contacts SET attempts = 2 WHERE campaign_id = :c"),
            {"c": campaign_id},
        )

    monkeypatch.setattr("apps.api.agents.service.get_engine", lambda: _ThrottledEngine())

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    assert result == {"dialled": 0, "blocked": 0, "exhausted": 1}, result
    assert await _contacts(tenant_id, campaign_id) == [("failed", 3)], (
        "the last rung of the ladder is the end of it"
    )
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(text("SELECT status FROM calls WHERE direction = 'outbound'"))
        ).all()
    assert [str(r[0]) for r in rows] == ["failed"], (
        "a vendor that refused before dialling leaves a CLOSED row, not one the reaper "
        "has to settle — an intent row left `queued` here reads as a call that might yet "
        "connect and holds an outbound line for an hour"
    )
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


class _VendorRefusingEngine(FakeEngine):
    """The vendor answering `POST /call` with a documented refusal of the REQUEST.

    `400 {"error": 1001, "message": "agent_id is required"}` is the vendor's own first
    worked example for this endpoint (`bolna-findings/mirror/pages/api-reference/calls/
    make.md:62`), and `errors.md:15` defines the status as *"Invalid or missing parameter"*
    — a statement about the request, so no line was seized and nobody's phone rang.

    It is raised the way the real ladder raises it (`vendor_http.EngineRejectedError`, the
    exception `vendor_request` builds from the response) rather than as a bare
    `ProblemError`, because the status is the whole fact under test.
    """

    async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
        raise EngineRejectedError(status=400, vendor_error=1001)


async def test_a_documented_vendor_refusal_keeps_the_contact_on_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `400` from the vendor is not "this person may have been rung".

    THE DEFECT THIS PINS. Every 4xx and every 5xx used to arrive as one indistinguishable
    `engine_rejected`, and `dispatch_call` classified the whole of it as unconfirmed — so
    a stale `engine_agent_ref`, a revoked API key or a mistyped calling number settled
    each contact TERMINALLY on its FIRST attempt, with an escalation telling the client a
    human should check a call that was never placed. One config mistake consumed a whole
    contact list irreversibly, because "failed, may have rung" is not a state anything
    re-dials from.

    The vendor documents four statuses as refusals of the request
    (`vendor_http.REQUEST_REFUSED_STATUSES`), so this contact keeps its place: one attempt
    spent, back to `pending`, nothing exhausted and nobody escalated. The `calls` row is
    the other half of the proof — `failed`, closed by `_close_unplaced_dial`, rather than
    the `queued` intent row the unconfirmed path deliberately leaves behind.

    Its sibling above (`_RefusingEngine`, a raise from inside the vendor call) is the
    behaviour that must NOT change: ambiguity still ends the contact.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Bad param", phones=("9876670001",)
    )

    monkeypatch.setattr("apps.api.agents.service.get_engine", lambda: _VendorRefusingEngine())

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    assert result == {"dialled": 0, "blocked": 0, "exhausted": 0}, result
    assert await _contacts(tenant_id, campaign_id) == [("pending", 1)], (
        "a refusal the vendor documents as 'I did not do this' must spend one rung of the "
        "ladder, not the whole contact"
    )
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(text("SELECT status FROM calls WHERE direction = 'outbound'"))
        ).all()
    assert [str(r[0]) for r in rows] == ["failed"], (
        "the intent row must be CLOSED: the vendor proved nothing rang, so leaving it "
        "`queued` would hold an outbound line for an hour over a typo"
    )
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
    assert int(escalations or 0) == 0, (
        "nothing is exhausted, so nobody is told this lead could not be reached"
    )


async def test_an_undocumented_vendor_status_is_still_treated_as_a_possible_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default has to stay conservative or the fix above becomes the defect.

    A `502` is a proxy answering AFTER the vendor may have committed, and `422` is a
    status Bolna documents on other routes but never as a `POST /call` outcome. Neither
    proves anything, so both keep D-181's terminal treatment — the contact is finished
    with and the client is told, rather than dialled a second time on a guess.
    """
    for status in (500, 502, 504, 409, 422):

        class _Ambiguous(FakeEngine):
            vendor_status = status

            async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
                raise EngineRejectedError(status=self.vendor_status, vendor_error=None)

        tenant_id, agent_id = await _tenant()
        number_id, template_id = await _dlt_rows(tenant_id, agent_id)
        campaign_id = await _launched_campaign(
            tenant_id,
            agent_id,
            number_id,
            template_id,
            name=f"Ambiguous {status}",
            phones=(f"9876{status}001",),
        )
        monkeypatch.setattr("apps.api.agents.service.get_engine", lambda: _Ambiguous())

        result = await campaign_dispatch._dispatch_for_campaign(
            tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
        )

        assert result == {"dialled": 0, "blocked": 0, "exhausted": 1}, (status, result)
        assert await _contacts(tenant_id, campaign_id) == [("failed", 1)], status
        async with tenant_session(tenant_id) as session:
            engine_call_id = (
                await session.execute(
                    text(
                        "SELECT engine_call_id FROM calls WHERE direction = 'outbound' "
                        "ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).scalar()
        assert str(engine_call_id).startswith(UNCONFIRMED_ENGINE_CALL_PREFIX), (
            f"a {status} left a row claiming the vendor named this call"
        )


def test_the_dial_failure_log_line_names_the_refusal_rather_than_the_python_class() -> None:
    """`campaign_dial_failed.reason` is what an operator greps at 3am.

    It was `type(exc).__name__`, which is the constant `ProblemError` for every refusal
    this branch can catch — a log full of lines naming the exception CLASS and no fact
    about the failure. Hard rule 6 is the reason the vendor's human `message` is still
    not here: only our own codes, an HTTP status and the int32 the adapter bounded.
    """
    assert (
        campaign_dispatch._dial_failure_reason(EngineRejectedError(status=400, vendor_error=1001))
        == "engine_rejected:400/1001"
    )
    assert (
        campaign_dispatch._dial_failure_reason(EngineRejectedError(status=503))
        == "engine_rejected:503"
    )
    assert (
        campaign_dispatch._dial_failure_reason(
            ProblemError(
                kind="dependency",
                code="engine_rate_limited",
                title="t",
                detail="d",
            )
        )
        == "engine_rate_limited"
    )
    assert campaign_dispatch._dial_failure_reason(RuntimeError("boom")) == "RuntimeError"


async def test_the_ladder_still_ends_when_the_caller_has_no_campaign_to_escalate_to() -> None:
    """`_record_failure`'s two optional ids are the escalation's context, and its
    docstring promises that without them the contact is still failed correctly and the
    escalation is SKIPPED rather than guessed at.

    Guessing would be the harmful half: an escalation carrying the wrong campaign id
    messages a person about an enquiry they never made. Failing to fail the contact
    would be the other: it stays claimable and the ladder never ends.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
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
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
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
    """Why the tick claims `slots` UNCONDITIONALLY, with no `if slots > 0` around it.

    The tick computes `slots = min(slider, tenant_budget)` AFTER breaking out when the
    budget is spent, so the only way to reach zero there is a campaign whose own slider
    is zero — and the database refuses to hold one (`concurrency BETWEEN 1 AND 10`,
    migration e16c96e68bc5). The guard that used to stand there was therefore a branch no
    state could take: it read as a case that happens and it cost the coverage gate a
    waiver, so it is gone and this test is what holds the argument up. If the constraint
    is ever relaxed, it fails HERE — which is the signal to decide what a zero-line
    campaign should mean (it belongs in the `WHERE c.status = 'running'` query, not in a
    silent skip) rather than to re-add a guard nobody exercises.
    """
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)

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
