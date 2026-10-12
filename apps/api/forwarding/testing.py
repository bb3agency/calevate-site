"""The forwarding verification call (D-746): does a call to the client's published number
arrive at its Calevate number, with whose number, and do two at once both get through?

WHAT IT IS, AND WHY IT IS NOT A CAMPAIGN CALL. A business asks us, from its own account, to
ring the number it has just told us is its own, so it can see its forward work. Nothing is
offered or sold, nobody but the business is rung, and the business is the one who asked:
TCCCPR's "commercial communication" is one whose "primary purpose is to inform about or
advertise or solicit business" (TCCCPR 2018 reg. 2, read 11 Oct 2026 on a third-party copy,
web-secondary), which this is not. So it does not go through `dispatch_call` and the
campaign gate, whose questions (consent, DNC, KYC, the pledge) are about calling the
public. It has its own, narrower checks instead, every one of them explicit here:

* the platform halt and the maintenance drain, and the account not stopped;
* only `org:manage` may run it, and only on a number a person of the business confirmed is
  its own (`forwarded_lines.attested_*`); it can dial nothing else, because the number is
  read from that row and never taken from the request;
* 09:00 to 21:00 IST (the voice platform refuses outside it anyway, place-call.md:12-13);
* a daily cap per client (`forwarding_test_daily_cap`) and one open test per client;
* every run is audited.

Whether TRAI's autodialer notice (TCCCPR reg. 4 as amended 12 Feb 2025, web-secondary)
reaches a non-commercial test call is not settled: OPERATIONS gate F-6.

HOW IT RUNS. Leg 1 rings from the shared trial number, leg 2 (when an operator has chosen a
second number) from that one, each placed by its own developer-workspace agent
(`engine/forwarding_probe.py`). They share the trial number's one line with free-trial calls,
so the trial line lock (`agents.service.TRIAL_LINE_LOCK_KEY`) is taken and both kinds of
use are counted. The forwarded arrival is seen twice, and the larger count wins because the
two see different ids for the same call: the caller lookup, before the client's agent
answers (`record_lookup_arrival`, which also hangs our legs up a few seconds later), and the
post-call pipeline (`claim_inbound_call`). Settlement runs after the window and reads each
leg back from the platform.

COST. Every minute is ours (`forwarding_test_min`, absorbed): our legs at the attested
per-minute rate, and the arrival on the client's number, which the pipeline meters to that
unit instead of the client's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from calevate_shared.calling_window import ist_wall_clock
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.engine_minutes import (
    BASE_RATE_KEY,
    PULSE_SECONDS,
    attested_minute_prices,
    billed_minutes,
    cost_with_fee,
    topup_fee,
)
from apps.api.billing.models import FORWARDING_TEST_UNIT_TYPE
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import account_stopped_blocker
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.forwarding_probe import PlacesForwardingTests
from apps.api.forwarding.service import (
    platform_caller_numbers,
    published_numbers,
    read_line,
)

log = get_logger(__name__)

#: Arrivals are accepted for this long after the legs are placed: up to 30 s of ringing on
#: the published phone before a no-answer forward, the forward itself, and margin.
ARRIVAL_WINDOW: Final = timedelta(seconds=120)
#: After an arrival is seen, the legs are hung up this much later: long enough for the
#: client's agent to answer, so the call record exists, short enough to cost one pulse.
HANG_UP_AFTER_ARRIVAL_S: Final = 8
#: Settlement waits this long past the window for the post-call pipeline's own match.
SETTLE_GRACE: Final = timedelta(seconds=90)
#: A leg left in `placing`/`live` longer than this no longer holds the shared line.
LEG_HORIZON: Final = timedelta(minutes=10)
OPENS: Final = time(9, 0)
CLOSES: Final = time(21, 0)

SETTLE_JOB: Final = "settle_forwarding_test"
HANG_UP_JOB: Final = "hang_up_forwarding_test"

ENGINES: Final = frozenset({"thinnest"})

Finding = Literal["caller_shown", "business_number_shown", "other_number_shown"]


def _refuse(code: str, title: str, remediation: str) -> ProblemError:
    return ProblemError.business_rule(code, title, remediation=remediation)


def forwarding_calls_ready() -> bool:
    settings = get_settings()
    return (
        settings.engine in ENGINES
        and settings.trial_caller_number is not None
        and isinstance(get_engine(), PlacesForwardingTests)
    )


@dataclass(frozen=True, slots=True)
class ForwardingTestView:
    id: UUID
    line_id: UUID
    status: str
    outcome: str | None
    legs_placed: int
    caller_id_finding: str | None
    concurrency_finding: str | None
    failure_code: str | None
    created_at: datetime
    settled_at: datetime | None


_TEST_SQL: Final = (
    "SELECT id, line_id, status, outcome, legs_placed, caller_id_finding, "
    "concurrency_finding, failure_code, created_at, settled_at FROM forwarding_tests "
)


async def read_test(session: AsyncSession, test_id: UUID) -> ForwardingTestView:
    row = (await session.execute(text(_TEST_SQL + "WHERE id = :id"), {"id": test_id})).first()
    if row is None:
        raise ProblemError.not_found("Forwarding test")
    return ForwardingTestView(*row)


async def recent_tests(
    session: AsyncSession, line_id: UUID, *, limit: int
) -> list[ForwardingTestView]:
    rows = (
        await session.execute(
            text(_TEST_SQL + "WHERE line_id = :lid ORDER BY created_at DESC LIMIT :limit"),
            {"lid": line_id, "limit": limit},
        )
    ).all()
    return [ForwardingTestView(*row) for row in rows]


# --- the line lock shared with free-trial calls --------------------------------------------


async def forwarding_legs_in_use(session: AsyncSession) -> int:
    """Live forwarding-test legs platform-wide (the legs table is not tenant-isolated)."""
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM forwarding_test_legs "
                    "WHERE status IN ('placing', 'live') "
                    "AND created_at > now() - make_interval(secs => :horizon)"
                ),
                {"horizon": LEG_HORIZON.total_seconds()},
            )
        ).scalar_one()
    )


async def _hold_shared_line(session: AsyncSession) -> None:
    """The trial line's own lock, then both kinds of use counted (see the module)."""
    from apps.api.agents.service import TRIAL_LINE_LOCK_KEY
    from apps.api.compliance.trial_access import trial_line_horizon

    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": TRIAL_LINE_LOCK_KEY})
    trial = int(
        (
            await session.execute(
                text("SELECT trial_lines_in_use(make_interval(secs => :horizon))"),
                {"horizon": trial_line_horizon().total_seconds()},
            )
        ).scalar_one()
    )
    if trial > 0 or await forwarding_legs_in_use(session) > 0:
        raise ProblemError.conflict(
            "forwarding_test_line_busy",
            "Another test call is in progress.",
            remediation="Try again in a minute.",
        )


# --- starting a test -----------------------------------------------------------------------


async def _gate(session: AsyncSession, *, tenant_id: UUID, now: datetime) -> None:
    if not forwarding_calls_ready():
        raise _refuse(
            "forwarding_test_unavailable",
            "Test calls are not available yet.",
            "Please try again later.",
        )
    platform = await get_platform_status()
    if platform.outbound_halted or not platform.accepting_new_work:
        raise _refuse(
            "forwarding_test_paused",
            "Calls are paused across the service right now.",
            "Try the test again later.",
        )
    stopped = await account_stopped_blocker(session, tenant_id=tenant_id)
    if stopped is not None:
        raise _refuse(stopped[0], stopped[1], "Contact us about your account.")
    wall = ist_wall_clock(now).time()
    if not OPENS <= wall < CLOSES:
        raise _refuse(
            "forwarding_test_outside_hours",
            "Test calls run between 9 am and 9 pm.",
            "Try again after 9 am.",
        )
    cap = get_settings().forwarding_test_daily_cap
    today = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM forwarding_tests WHERE (created_at AT TIME ZONE "
                    "'Asia/Kolkata')::date = (now() AT TIME ZONE 'Asia/Kolkata')::date"
                )
            )
        ).scalar_one()
    )
    if today >= cap:
        raise ProblemError(
            kind="business_rule",
            code="forwarding_test_daily_cap",
            title=f"You have run {cap} tests today",
            detail="Each test is a real call, so the number per day is limited.",
            remediation="Try again tomorrow.",
            status=429,
        )
    open_test = (
        await session.execute(
            text("SELECT 1 FROM forwarding_tests WHERE status IN ('placing', 'ringing') LIMIT 1")
        )
    ).first()
    if open_test is not None:
        raise ProblemError.conflict(
            "forwarding_test_running",
            "A test is already running.",
            remediation="Wait for it to finish, about two minutes.",
        )


async def start_test(
    session: AsyncSession,
    *,
    principal: Principal,
    tenant_id: UUID,
    line_id: UUID,
    ip: str | None,
) -> ForwardingTestView:
    """Check, reserve the shared line, place the legs. Raises a refusal before anything
    rings; a leg the platform refuses leaves the test `failed` with the code."""
    now = datetime.now(UTC)
    line = await read_line(session, line_id)
    if line.calevate_number_e164 is None:
        raise _refuse(
            "forwarding_needs_calevate_number",
            "This number does not point at a Calevate number any more.",
            "Choose your Calevate number for it, then test again.",
        )
    await _gate(session, tenant_id=tenant_id, now=now)
    second = get_settings().forwarding_test_second_number
    legs = 2 if second is not None else 1
    test_id = uuid7()
    # The reservation commits on its own before any vendor round trip, so the line is held
    # from the moment we decide to ring until the legs are reported over.
    async with tenant_session(tenant_id) as hold:
        await _hold_shared_line(hold)
        await hold.execute(
            text(
                "INSERT INTO forwarding_tests (id, tenant_id, line_id, requested_by, status) "
                "VALUES (:id, :tid, :lid, :by, 'placing')"
            ),
            {"id": test_id, "tid": tenant_id, "lid": line_id, "by": principal.client_user_id},
        )
        for leg in range(1, legs + 1):
            await hold.execute(
                text(
                    "INSERT INTO forwarding_test_legs (id, test_id, tenant_id, leg, status) "
                    "VALUES (:id, :tid_test, :tid, :leg, 'placing')"
                ),
                {"id": uuid7(), "tid_test": test_id, "tid": tenant_id, "leg": leg},
            )
        await hold.execute(
            text(
                "UPDATE forwarded_lines SET status = 'testing', updated_at = now() WHERE id = :id"
            ),
            {"id": line_id},
        )
        await write_audit(
            hold,
            actor=principal,
            action="forwarding.test_started",
            tenant_id=tenant_id,
            object_type="forwarding_test",
            object_id=str(test_id),
            ip=ip,
            summary={"line_id": str(line_id), "legs": str(legs)},
        )
    await place_legs(tenant_id, test_id, to_e164=line.e164)
    return await read_test(session, test_id)


async def place_legs(tenant_id: UUID, test_id: UUID, *, to_e164: str) -> None:
    """Lend each platform number to its test agent and ring the published number. Both legs
    are placed back to back so they reach the published phone together."""
    from apps.api.campaigns.engine_numbers import lend_platform_line

    engine = get_engine()
    assert isinstance(engine, PlacesForwardingTests)
    settings = get_settings()
    sources = [settings.trial_caller_number, settings.forwarding_test_second_number]
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id, leg FROM forwarding_test_legs WHERE test_id = :t ORDER BY leg"),
                {"t": test_id},
            )
        ).all()
    placed = 0
    failure: str | None = None
    for leg_id, leg in rows:
        source = sources[int(leg) - 1]
        try:
            if source is None:
                raise _refuse("forwarding_test_unavailable", "No number to call from.", "Later.")
            agent_ref = await engine.converge_forwarding_test_agent(int(leg))
            number = "".join(ch for ch in source if ch.isdigit())
            if not await lend_platform_line(number, agent_ref):
                raise _refuse("trial_line_unavailable", "The test line is not ready.", "Later.")
            handle = await engine.place_forwarding_test_call(
                agent_ref=agent_ref, from_e164=source, to_e164=to_e164, reference=str(leg_id)
            )
        except ProblemError as exc:
            failure = failure or exc.code
            log.warning(
                "forwarding_test_leg_refused",
                extra={"tenant_id": str(tenant_id), "test_id": str(test_id), "code": exc.code},
            )
            await _close_leg(tenant_id, leg_id, status="failed")
            continue
        placed += 1
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE forwarding_test_legs SET status = 'live', engine_call_ref = :ref, "
                    "updated_at = now() WHERE id = :id AND status = 'placing'"
                ),
                {"id": leg_id, "ref": handle},
            )
    async with tenant_session(tenant_id) as session:
        if placed == 0:
            await session.execute(
                text(
                    "UPDATE forwarding_tests SET status = 'failed', outcome = 'not_placed', "
                    "failure_code = :code, settled_at = now(), updated_at = now() "
                    "WHERE id = :id AND status = 'placing'"
                ),
                {"id": test_id, "code": failure or "not_placed"},
            )
            await session.execute(
                text(
                    # Back to what the last finished test said: nothing rang this time.
                    "UPDATE forwarded_lines SET status = COALESCE((SELECT CASE WHEN "
                    "t.outcome = 'arrived' THEN 'working' ELSE 'not_working' END "
                    "FROM forwarding_tests t WHERE t.id = forwarded_lines.last_test_id), "
                    "'untested'), updated_at = now() "
                    "WHERE id = (SELECT line_id FROM forwarding_tests WHERE id = :id)"
                ),
                {"id": test_id},
            )
            return
        window_ends = datetime.now(UTC) + ARRIVAL_WINDOW
        await session.execute(
            text(
                "UPDATE forwarding_tests SET status = 'ringing', legs_placed = :placed, "
                "placed_at = now(), window_ends_at = :ends, updated_at = now() "
                "WHERE id = :id AND status = 'placing'"
            ),
            {"id": test_id, "placed": placed, "ends": window_ends},
        )
    payload = {"tenant_id": str(tenant_id), "test_id": str(test_id)}
    await enqueue(
        HANG_UP_JOB,
        payload,
        job_id=f"{HANG_UP_JOB}:{test_id}:window",
        _defer_by=ARRIVAL_WINDOW,
    )
    await enqueue(
        SETTLE_JOB,
        payload,
        job_id=f"{SETTLE_JOB}:{test_id}",
        _defer_by=ARRIVAL_WINDOW + SETTLE_GRACE,
    )


async def _close_leg(tenant_id: UUID, leg_id: UUID, *, status: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE forwarding_test_legs SET status = :status, updated_at = now() "
                "WHERE id = :id AND status IN ('placing', 'live')"
            ),
            {"id": leg_id, "status": status},
        )


# --- seeing the arrival --------------------------------------------------------------------


def classify_caller(caller_e164: str, *, published: frozenset[str]) -> Finding:
    """Which number the forwarded call showed: ours (the network kept the caller's
    number), the client's own published number (it replaced it), or something else."""
    if caller_e164 in platform_caller_numbers():
        return "caller_shown"
    if caller_e164 in published:
        return "business_number_shown"
    return "other_number_shown"


_OPEN_TEST_SQL: Final = (
    "SELECT id FROM forwarding_tests WHERE status = 'ringing' "
    "AND placed_at <= :at AND window_ends_at >= :at ORDER BY placed_at DESC LIMIT 1"
)


async def _record_finding(session: AsyncSession, test_id: UUID, finding: Finding) -> None:
    """A test keeps the first finding that showed the caller's own number, which is the
    one the agent can use; otherwise the first seen."""
    await session.execute(
        text(
            "UPDATE forwarding_tests SET caller_id_finding = CASE "
            "WHEN caller_id_finding IS NULL OR :f = 'caller_shown' THEN :f "
            "ELSE caller_id_finding END, updated_at = now() WHERE id = :id"
        ),
        {"id": test_id, "f": finding},
    )


@dataclass(frozen=True, slots=True)
class LookupVerdict:
    #: This call is our test arriving.
    test_id: UUID | None
    #: The network showed the client's own number instead of the caller's.
    caller_hidden: bool


async def record_lookup_arrival(
    session: AsyncSession, *, tenant_id: UUID, caller_e164: str, engine_call_id: str | None
) -> LookupVerdict:
    """At the caller lookup, before the client's agent answers. Records a test arrival and
    hangs the legs up shortly after; otherwise says whether the caller's number is hidden."""
    published = await published_numbers(session)
    if not published:
        return LookupVerdict(test_id=None, caller_hidden=False)
    finding = classify_caller(caller_e164, published=published)
    hidden = finding == "business_number_shown"
    if finding == "other_number_shown":
        return LookupVerdict(test_id=None, caller_hidden=False)
    row = (await session.execute(text(_OPEN_TEST_SQL), {"at": datetime.now(UTC)})).first()
    if row is None:
        return LookupVerdict(test_id=None, caller_hidden=hidden)
    test_id = UUID(str(row[0]))
    if engine_call_id:
        await session.execute(
            text(
                "UPDATE forwarding_tests SET lookup_arrivals = array_append(lookup_arrivals, "
                "CAST(:ref AS text)), updated_at = now() WHERE id = :id "
                "AND NOT (CAST(:ref AS text) = ANY(lookup_arrivals))"
            ),
            {"id": test_id, "ref": engine_call_id},
        )
    await _record_finding(session, test_id, finding)
    log.info(
        "forwarding_test_arrived",
        extra={"tenant_id": str(tenant_id), "test_id": str(test_id), "finding": finding},
    )
    return LookupVerdict(test_id=test_id, caller_hidden=False)


async def queue_early_hang_up(tenant_id: UUID, test_id: UUID) -> None:
    await enqueue(
        HANG_UP_JOB,
        {"tenant_id": str(tenant_id), "test_id": str(test_id)},
        job_id=f"{HANG_UP_JOB}:{test_id}:arrived",
        _defer_by=timedelta(seconds=HANG_UP_AFTER_ARRIVAL_S),
    )


@dataclass(frozen=True, slots=True)
class InboundClaim:
    test_id: UUID | None
    caller_hidden: bool


async def claim_inbound_call(
    session: AsyncSession,
    *,
    call_id: UUID,
    from_e164: str | None,
    started_at: datetime | None,
) -> InboundClaim:
    """In the post-call pipeline, for an inbound call: is it our test arriving (then it is
    marked so its minutes are ours and it files no lead), or a forwarded call that hid the
    caller's number (then the lead is filed under the call-back number the caller gave)?"""
    if not from_e164:
        return InboundClaim(test_id=None, caller_hidden=False)
    published = await published_numbers(session)
    if not published:
        return InboundClaim(test_id=None, caller_hidden=False)
    finding = classify_caller(from_e164, published=published)
    if finding == "other_number_shown":
        return InboundClaim(test_id=None, caller_hidden=False)
    at = started_at or datetime.now(UTC)
    row = (await session.execute(text(_OPEN_TEST_SQL), {"at": at})).first()
    if row is None:
        if finding != "business_number_shown":
            return InboundClaim(test_id=None, caller_hidden=False)
        await session.execute(
            text(
                "UPDATE calls SET caller_id_hidden = true, updated_at = now() "
                "WHERE id = :cid AND NOT caller_id_hidden"
            ),
            {"cid": call_id},
        )
        return InboundClaim(test_id=None, caller_hidden=True)
    test_id = UUID(str(row[0]))
    await session.execute(
        text(
            "UPDATE calls SET forwarding_test_id = :t, updated_at = now() "
            "WHERE id = :cid AND forwarding_test_id IS NULL"
        ),
        {"t": test_id, "cid": call_id},
    )
    await session.execute(
        text(
            "UPDATE forwarding_tests SET call_arrivals = array_append(call_arrivals, "
            "CAST(:cid AS text)), updated_at = now() WHERE id = :id "
            "AND NOT (CAST(:cid AS text) = ANY(call_arrivals))"
        ),
        {"id": test_id, "cid": str(call_id)},
    )
    await _record_finding(session, test_id, finding)
    return InboundClaim(test_id=test_id, caller_hidden=False)


async def meter_test_arrival(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, minutes: Decimal, cost: Decimal
) -> bool:
    """The arrival on the client's number is ours: one `forwarding_test_min` row instead of
    the client's minute. False when this call is not a test arrival. Called under the
    pipeline's call lock, so the existence check cannot race a second run."""
    test = (
        await session.execute(
            text("SELECT forwarding_test_id FROM calls WHERE id = :cid"), {"cid": call_id}
        )
    ).scalar()
    if test is None:
        return False
    already = (
        await session.execute(
            text("SELECT 1 FROM usage_events WHERE call_id = :cid LIMIT 1"), {"cid": call_id}
        )
    ).first()
    if already is not None:
        return True
    unit = (cost / minutes).quantize(MONEY_Q, rounding=ROUNDING) if minutes > 0 else Decimal(0)
    await session.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid, "
            "occurred_at, meta, created_at) VALUES (:id, :tid, :cid, :unit, :qty, :cost, now(), "
            "CAST(:meta AS jsonb), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "cid": call_id,
            "unit": FORWARDING_TEST_UNIT_TYPE,
            "qty": minutes,
            "cost": unit,
            "meta": '{"kind": "forwarding_test", "leg": "arrival"}',
        },
    )
    await session.execute(
        text(
            "UPDATE forwarding_tests SET cost_inr = COALESCE(cost_inr, 0) + :c, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": test, "c": (unit * minutes).quantize(MONEY_Q, rounding=ROUNDING)},
    )
    return True


# --- ending and settling -------------------------------------------------------------------


async def hang_up_legs(tenant_id: UUID, test_id: UUID) -> int:
    """End every leg of the test that is still on the line. Idempotent."""
    engine = get_engine()
    if not isinstance(engine, PlacesForwardingTests):
        return 0
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT engine_call_ref FROM forwarding_test_legs WHERE test_id = :t "
                    "AND status = 'live' AND engine_call_ref IS NOT NULL"
                ),
                {"t": test_id},
            )
        ).all()
    ended = 0
    for (handle,) in rows:
        try:
            await engine.hang_up_forwarding_leg(str(handle))
            ended += 1
        except ProblemError as exc:
            log.warning(
                "forwarding_test_hang_up_failed",
                extra={"tenant_id": str(tenant_id), "test_id": str(test_id), "code": exc.code},
            )
    return ended


async def _price_leg_seconds(
    session: AsyncSession, seconds: int, at: datetime
) -> tuple[Decimal, Decimal | None]:
    """Minutes and their cost at the attested default-voice rate with the top-up fee.
    None when the rate is unattested: the minute is unpriced, not free."""
    engine = get_settings().engine
    minutes = billed_minutes(Decimal(seconds), pulse_s=PULSE_SECONDS.get(engine, 60))
    price = (await attested_minute_prices(session, engine=engine, at=at)).get(BASE_RATE_KEY)
    if price is None:
        return minutes, None
    return minutes, cost_with_fee(minutes * price.inr_per_min, fee=topup_fee(engine))


async def settle_test(tenant_id: UUID, test_id: UUID) -> str:
    """Read each leg back, hang up any still live, meter our legs, and record the verdict on
    the test and its line. CAS on `ringing`, so a second run settles nothing twice."""
    engine = get_engine()
    await hang_up_legs(tenant_id, test_id)
    async with untenanted_session() as session:
        legs = (
            await session.execute(
                text(
                    "SELECT id, leg, engine_call_ref FROM forwarding_test_legs "
                    "WHERE test_id = :t ORDER BY leg"
                ),
                {"t": test_id},
            )
        ).all()
    answered_any = False
    leg_seconds: list[tuple[int, int]] = []
    for leg_id, leg, handle in legs:
        seconds: int | None = None
        answered: bool | None = None
        if handle and isinstance(engine, PlacesForwardingTests):
            try:
                report = await engine.read_forwarding_leg(str(handle))
                seconds, answered = report.seconds, report.answered
            except ProblemError as exc:
                log.warning("forwarding_test_leg_unread", extra={"code": exc.code})
        answered_any = answered_any or bool(answered)
        if seconds:
            leg_seconds.append((int(leg), seconds))
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE forwarding_test_legs SET status = CASE WHEN status = 'failed' "
                    "THEN 'failed' ELSE 'ended' END, answered = :a, seconds = :s, "
                    "ended_at = now(), updated_at = now() WHERE id = :id"
                ),
                {"id": leg_id, "a": answered, "s": seconds},
            )
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT line_id, legs_placed, cardinality(lookup_arrivals), "
                    "cardinality(call_arrivals), caller_id_finding, placed_at, window_ends_at "
                    "FROM forwarding_tests WHERE id = :id AND status = 'ringing' FOR UPDATE"
                ),
                {"id": test_id},
            )
        ).first()
        if row is None:
            return "already_settled"
        line_id, legs_placed, by_lookup, by_call, finding, placed_at, window_ends = row
        arrivals = max(int(by_lookup), int(by_call))
        if arrivals == 0:
            finding = await _other_number_arrival(session, placed_at, window_ends)
            arrivals = 1 if finding is not None else 0
        outcome = (
            "arrived" if arrivals else ("answered_on_phone" if answered_any else "not_arrived")
        )
        concurrency = (
            "not_tested"
            if int(legs_placed) < 2
            else ("both_arrived" if arrivals >= 2 else "one_arrived" if arrivals == 1 else None)
        )
        cost = Decimal(0)
        now = datetime.now(UTC)
        for leg, seconds in leg_seconds:
            minutes, leg_cost = await _price_leg_seconds(session, seconds, now)
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, ref, occurred_at, meta, created_at) VALUES (:id, :tid, "
                    "NULL, :unit, :qty, :cost, :ref, now(), CAST(:meta AS jsonb), now()) "
                    "ON CONFLICT (tenant_id, unit_type, ref) "
                    "WHERE ref IS NOT NULL AND call_id IS NULL DO NOTHING"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "unit": FORWARDING_TEST_UNIT_TYPE,
                    "qty": minutes,
                    "cost": (
                        (leg_cost / minutes).quantize(MONEY_Q, rounding=ROUNDING)
                        if leg_cost is not None and minutes > 0
                        else leg_cost
                    ),
                    "ref": f"fwdtest:{test_id}:{leg}",
                    "meta": '{"kind": "forwarding_test", "leg": "outbound"}',
                },
            )
            cost += leg_cost or Decimal(0)
        await session.execute(
            text(
                "UPDATE forwarding_tests SET status = 'settled', outcome = :outcome, "
                "caller_id_finding = :finding, concurrency_finding = :conc, "
                "cost_inr = COALESCE(cost_inr, 0) + :cost, settled_at = now(), "
                "updated_at = now() WHERE id = :id AND status = 'ringing'"
            ),
            {
                "id": test_id,
                "outcome": outcome,
                "finding": finding if arrivals else None,
                "conc": concurrency,
                "cost": cost,
            },
        )
        working = outcome == "arrived"
        await session.execute(
            text(
                "UPDATE forwarded_lines SET status = :status, last_test_id = :t, "
                "last_tested_at = now(), "
                "caller_id_finding = COALESCE(:finding, caller_id_finding), "
                "concurrency_finding = COALESCE(:conc, concurrency_finding), "
                "quiet_since = CASE WHEN :working THEN NULL ELSE quiet_since END, "
                "quiet_alerted_at = CASE WHEN :working THEN NULL ELSE quiet_alerted_at END, "
                "updated_at = now() WHERE id = :lid"
            ),
            {
                "lid": line_id,
                "t": test_id,
                "status": "working" if working else "not_working",
                "finding": finding if arrivals else None,
                "conc": concurrency,
                "working": working,
            },
        )
        await write_audit(
            session,
            actor_type="system",
            action="forwarding.test_settled",
            tenant_id=tenant_id,
            object_type="forwarding_test",
            object_id=str(test_id),
            summary={
                "outcome": outcome,
                "caller_id_finding": str(finding) if arrivals else "none",
                "concurrency_finding": str(concurrency),
            },
        )
    log.info(
        "forwarding_test_settled",
        extra={"tenant_id": str(tenant_id), "test_id": str(test_id), "outcome": outcome},
    )
    return outcome


async def _other_number_arrival(
    session: AsyncSession, placed_at: datetime | None, window_ends: datetime | None
) -> Finding | None:
    """With nothing arriving from our number or the client's own, an inbound call on the
    client's line inside the window probably IS the test with a third number shown. Said
    as such on screen ("if nobody else rang you just then"), never as certain."""
    if placed_at is None or window_ends is None:
        return None
    seen = (
        await session.execute(
            text(
                "SELECT 1 FROM calls WHERE direction = 'inbound' AND forwarding_test_id IS NULL "
                "AND COALESCE(started_at, created_at) BETWEEN :a AND :b LIMIT 1"
            ),
            {"a": placed_at, "b": window_ends},
        )
    ).first()
    return "other_number_shown" if seen is not None else None


async def is_forwarding_leg(session: AsyncSession, engine_call_id: str) -> bool:
    """Is this execution one of our own test legs (untenanted read)?"""
    return (
        await session.execute(
            text("SELECT 1 FROM forwarding_test_legs WHERE engine_call_ref = :ref"),
            {"ref": engine_call_id},
        )
    ).first() is not None


__all__ = [
    "ARRIVAL_WINDOW",
    "HANG_UP_JOB",
    "SETTLE_JOB",
    "ForwardingTestView",
    "InboundClaim",
    "LookupVerdict",
    "claim_inbound_call",
    "classify_caller",
    "forwarding_calls_ready",
    "forwarding_legs_in_use",
    "hang_up_legs",
    "is_forwarding_leg",
    "meter_test_arrival",
    "place_legs",
    "queue_early_hang_up",
    "read_test",
    "recent_tests",
    "record_lookup_arrival",
    "settle_test",
    "start_test",
]
