"""The live USD→INR rate: the parse, the ceiling, the pin, the store, the conversion.

Ranked by what each failure costs, worst first:

1. **A costing cannot straddle a rate change.** One call, one rate, on the total and on
   every leg — and the rate it used is on the row. A call billed at two rates is a WRONG
   number in an append-only ledger, and it is the defect this whole seam is shaped around.
2. **A stale rate stops being used, and is not silently replaced.** Past the ceiling the
   conversion falls back to the operator's configured value and says so on the row; the
   ceiling is re-decided on every READ, so a dead refresher cannot leave a month of calls
   costed off a number nobody was watching.
3. **The rate never passes through a binary float.** The vendor publishes a JSON number;
   `json.loads` would make it a `float`; a rate that cannot be written down exactly is a
   multiplier nobody can reconcile an invoice against (hard rule 7).
4. **A response this parser does not recognise is refused, never guessed at.** The live
   endpoint is egress-blocked here, so the parser is the only thing standing between a
   changed feed and every invoice.
5. **Two pulls cannot write two rows for one instant**, and the history cannot be edited
   after a bill was computed from it.

`fx_rate_observations` is a SHARED, GLOBAL, append-only table. Every row written here
carries a `test:` source and `_purge` removes exactly those, as the table owner — the only
role that can, because the table is append-only ON PURPOSE.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.core import fx as fx_module
from apps.api.core.fx import MAX_QUOTE_AGE, FxQuote, current_fx_quote, fx_scope, install_fx_quote
from apps.api.db.session import untenanted_session
from apps.api.engine.bolna import BolnaEngine
from apps.api.ops.fx_rates import (
    ImplausibleRateError,
    latest_observation,
    observation_key,
    recent_observations,
    record_observation,
    refresh_fx_snapshot,
)
from apps.api.ops.fx_routes import _build
from apps.workers.fx_pull import (
    DEFAULT_RUNG,
    FBIL_RUNG,
    LADDER,
    PREFERRED_RUNG,
    PULL_MINUTES,
    FxFeedUnreachableError,
    FxPullError,
    FxRung,
    fetch_published_rate,
    parse_rate_response,
    pull_fx_rate,
)
from calevate_shared.config import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_SOURCE = "test:fx"
FALLBACK = Decimal("88.00")
# A rate with four decimals that a binary float cannot hold exactly — the whole point of
# tests 3 below. `float("88.4275")` is 88.4274999999999948840923025272786617279052734375.
PUBLISHED = Decimal("88.4275")


def _body(**overrides: Any) -> str:
    """The vendor's documented response shape, verbatim from their OpenAPI example's
    structure (`lib/public/v2/openapi.json`, `Rate`): `date`, `base`, `quote`, `rate`."""
    payload: dict[str, Any] = {
        "date": date.today().isoformat(),
        "base": "USD",
        "quote": "INR",
        "rate": 88.4275,
    }
    payload.update(overrides)
    return json.dumps(payload)


async def _purge() -> None:
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: fx_rate_observations is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            modes = (
                await conn.execute(
                    text(
                        "SELECT tgname, tgenabled FROM pg_trigger "
                        "WHERE tgrelid = 'fx_rate_observations'::regclass AND NOT tgisinternal"
                    )
                )
            ).all()
            await conn.execute(text("ALTER TABLE fx_rate_observations DISABLE TRIGGER USER"))
            await conn.execute(text("DELETE FROM fx_rate_observations WHERE source LIKE 'test:%'"))
            for name, mode in modes:
                verb = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA", "D": "DISABLE"}.get(
                    str(mode), "ENABLE"
                )
                await conn.execute(
                    text(f'ALTER TABLE fx_rate_observations {verb} TRIGGER "{name}"')
                )
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    fx_module.reset_for_test()
    yield
    fx_module.reset_for_test()
    await _purge()


def _engine() -> BolnaEngine:
    """An adapter carrying the CONFIGURED fallback, exactly as `build_engine` constructs it."""
    return BolnaEngine(api_key="k", fx_rate=FALLBACK)


def _cost_payload(total_cents: int = 100, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "exec-1",
        "total_cost": total_cents,
        "cost_breakdown": {"platform": 60, "network": 40},
    }
    payload.update(overrides)
    return payload


# --- 1. one unit of work, one rate ----------------------------------------------------


def test_a_costing_uses_one_rate_for_the_total_and_every_leg() -> None:
    """The property the ledger depends on: `total_inr` and its parts are one conversion.

    Asserted as EXACT arithmetic rather than "close enough": a few paise of disagreement
    between a total and its own legs is precisely the size of defect that gets dismissed.
    """
    install_fx_quote(
        FxQuote(
            rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, observed_at=datetime.now(UTC)
        )
    )
    cost = _engine()._cost(_cost_payload())
    assert cost is not None
    assert cost.fx_rate == PUBLISHED
    # 100 cents = 1 USD; 60 + 40 cents = the same dollar, split. Quantized to
    # NUMERIC(12,4) — `unit_cost_paid`'s own scale — with ROUND_HALF_UP (`billing/rates
    # .ROUNDING`), never the ambient decimal context's banker's rounding.
    assert cost.total_inr == Decimal("88.4275")
    assert cost.platform_inr == Decimal("53.0565")
    assert cost.network_inr == Decimal("35.3710")
    assert cost.source_amount is not None
    assert cost.source_amount * cost.fx_rate == cost.total_inr
    assert cost.platform_inr + cost.network_inr == cost.total_inr


def test_a_rate_installed_mid_job_does_not_reach_a_job_already_running() -> None:
    """THE IN-FLIGHT GUARANTEE. `fx_scope()` resolves once; a refresher swapping the
    process-wide quote underneath must not change what this unit of work is costing at."""
    first = FxQuote(
        rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, observed_at=datetime.now(UTC)
    )
    install_fx_quote(first)
    with fx_scope() as pinned:
        assert pinned is not None and pinned.rate == PUBLISHED
        install_fx_quote(
            FxQuote(
                rate=Decimal("95.0000"),
                as_of=date.today(),
                source=TEST_SOURCE,
                observed_at=datetime.now(UTC),
            )
        )
        assert current_fx_quote() is first, "the pin must survive an install"
        cost = _engine()._cost(_cost_payload())
        assert cost is not None and cost.fx_rate == PUBLISHED
    # Outside the scope the process has moved on — the next unit of work gets the new rate.
    after = current_fx_quote()
    assert after is not None and after.rate == Decimal("95.0000")


def test_a_nested_scope_reuses_the_outer_pin() -> None:
    """An inner unit of work is part of the outer one; re-resolving would reintroduce the
    straddle the scope exists to prevent."""
    install_fx_quote(
        FxQuote(
            rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, observed_at=datetime.now(UTC)
        )
    )
    with fx_scope() as outer:
        install_fx_quote(None)
        with fx_scope() as inner:
            assert inner is outer


def test_the_pin_distinguishes_no_usable_rate_from_no_scope() -> None:
    """A job that opened with a stale feed must STAY on the fallback for its whole life,
    even if a fresh rate lands halfway through — otherwise its first rows and its last are
    converted at different numbers."""
    install_fx_quote(None)
    with fx_scope() as pinned:
        assert pinned is None
        install_fx_quote(
            FxQuote(
                rate=PUBLISHED,
                as_of=date.today(),
                source=TEST_SOURCE,
                observed_at=datetime.now(UTC),
            )
        )
        assert current_fx_quote() is None
        cost = _engine()._cost(_cost_payload())
        assert cost is not None and cost.fx_rate == FALLBACK


# --- 2. the staleness ceiling ---------------------------------------------------------


def test_a_rate_past_the_ceiling_is_refused_on_the_read_not_at_install() -> None:
    """The ceiling is a property of the PROCESS, not of the refresher's liveness: a poller
    that died leaves the quote installed, and the read is what must still refuse it."""
    stale = FxQuote(
        rate=PUBLISHED,
        as_of=(datetime.now(UTC) - MAX_QUOTE_AGE - timedelta(days=1)).date(),
        source=TEST_SOURCE,
        observed_at=datetime.now(UTC),
    )
    install_fx_quote(stale)
    assert stale.usable() is False
    assert current_fx_quote() is None
    cost = _engine()._cost(_cost_payload())
    assert cost is not None
    assert cost.fx_rate == FALLBACK, "past the ceiling, money converts at the configured rate"
    assert cost.fx_source == "configured:usd_inr_rate"
    assert cost.fx_as_of is None


def test_the_ceiling_is_measured_from_the_end_of_the_publication_day() -> None:
    """A rate published today is age zero all day. Measuring from midnight would make
    every afternoon's perfectly fresh quote look half a day old, and a ceiling that drifts
    with the clock is one nobody can reason about."""
    today = FxQuote(
        rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, observed_at=datetime.now(UTC)
    )
    assert today.age() == timedelta(0)
    edge = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    exactly_at_ceiling = FxQuote(
        rate=PUBLISHED,
        as_of=(edge - MAX_QUOTE_AGE).date(),
        source=TEST_SOURCE,
        observed_at=edge,
    )
    assert exactly_at_ceiling.usable(edge) is True, "the ceiling is inclusive"


def test_a_conversion_records_which_rate_it_used() -> None:
    """`fx_rate` says WHAT; `fx_source`/`fx_as_of` say WHICH. Six months into a
    reconciliation, "was this call billed off a live rate?" is the first question, and it
    is not re-derivable from the number."""
    as_of = date.today() - timedelta(days=1)
    install_fx_quote(
        FxQuote(rate=PUBLISHED, as_of=as_of, source=TEST_SOURCE, observed_at=datetime.now(UTC))
    )
    cost = _engine()._cost(_cost_payload())
    assert cost is not None
    assert cost.fx_source == TEST_SOURCE
    assert cost.fx_as_of == as_of


def test_an_inr_payload_is_never_multiplied_by_any_rate() -> None:
    """The 83x error the branch exists to prevent, re-asserted now that the rate is live:
    an INR-denominated payload must be untouched by whatever the feed is doing. It is
    refused for the separate unit reason (D-411), and never converted."""
    install_fx_quote(
        FxQuote(
            rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, observed_at=datetime.now(UTC)
        )
    )
    assert _engine()._cost(_cost_payload(currency="INR")) is None


# --- 3/4. the parse: NUMERIC end to end, and refusal over guessing --------------------


def test_the_published_rate_never_passes_through_a_float() -> None:
    """The vendor publishes `rate` as a JSON number. `json.loads` would hand back a
    `float` and `Decimal(float)` would carry its error into every invoice; the parser
    takes the parser's own TEXT slice instead."""
    rate, as_of = parse_rate_response(_body())
    assert isinstance(rate, Decimal)
    assert str(rate) == "88.4275", "the exact digits the vendor published, not a float's"
    assert rate == PUBLISHED
    # What a float round-trip would have produced, spelled out rather than computed, so
    # the assertion still means something if someone "tidies" `Decimal(float)` away.
    assert rate != Decimal("88.42749999999999488409230252727866172790527343750")
    assert as_of == date.today()


def test_an_integral_rate_is_still_a_decimal() -> None:
    """`90` rather than `90.0` is a JSON int, which `parse_float` does not cover."""
    rate, _ = parse_rate_response(_body(rate=90))
    assert isinstance(rate, Decimal) and rate == Decimal(90)


@pytest.mark.parametrize(
    ("body", "because"),
    [
        ("not json at all", "a proxy error page is not a rate"),
        ('["a", "list"]', "the documented response is an object"),
        (_body(base="EUR"), "a redirect or a changed route must never be converted at"),
        (_body(quote="USD"), "the identity pair would make every dollar one rupee"),
        (_body(rate="88.4275"), "a feed that changed its money field's type must be read"),
        (_body(rate=0), "a zero makes every vendor minute free"),
        (_body(rate=-1), "a negative rate is not a rate"),
        (json.dumps({"base": "USD", "quote": "INR", "rate": 88.0}), "no date, no ceiling"),
        (_body(date="27-08-2026"), "an unparseable date is not a publication date"),
    ],
)
def test_a_response_this_parser_does_not_recognise_is_refused(body: str, because: str) -> None:
    """The live endpoint is unreachable from here, so this parser is the only thing between
    a changed feed and every invoice. Nothing is coerced, defaulted or guessed."""
    with pytest.raises(FxPullError):
        parse_rate_response(body)


def test_a_future_publication_date_is_refused() -> None:
    """`as_of` is what the staleness ceiling is measured against, so a bad feed could use
    it to disable the ceiling entirely — a rate dated 2030 would never go stale."""
    with pytest.raises(FxPullError):
        parse_rate_response(_body(date=(date.today() + timedelta(days=30)).isoformat()))


async def test_a_non_200_is_a_failed_pull_and_not_a_rate() -> None:
    """Their 404 means "no data found", which for a single-provider filter is a real
    possibility. It is as much a failed pull as a 500 and neither is guessed around."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(FxPullError):
        await fetch_published_rate(FBIL_RUNG, client)
    await client.aclose()


async def test_a_transport_failure_is_a_failed_pull() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(FxPullError):
        await fetch_published_rate(FBIL_RUNG, client)
    await client.aclose()


async def test_the_request_asks_for_the_pair_and_the_provider_it_documents() -> None:
    """The URL and the provider filter are what the module's evidence block is ABOUT, so
    they are asserted rather than trusted to a comment."""
    import httpx

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, text=_body())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await fetch_published_rate(FBIL_RUNG, client)
    await client.aclose()
    assert seen["url"] == "https://api.frankfurter.dev/v2/rate/USD/INR?providers=FBIL"


# --- 5. the store: idempotent, single-flight, immutable -------------------------------


async def test_two_concurrent_pulls_write_one_row() -> None:
    """Two workers ticking at the same second. The advisory lock serialises them and the
    unique key makes the loser a no-op — not a duplicate, and not an error either."""
    as_of = date.today()

    async def one() -> bool:
        async with untenanted_session() as session:
            _, inserted = await record_observation(
                session, rate=PUBLISHED, as_of=as_of, source=TEST_SOURCE, source_url="u"
            )
            return inserted

    results = await asyncio.gather(one(), one(), one())
    assert sorted(results) == [False, False, True], "exactly one writer inserts"
    async with untenanted_session() as session:
        assert len(await recent_observations(session, limit=50)) == 1


async def test_a_repeat_pull_of_the_same_publication_is_a_no_op() -> None:
    """The founder asked for five minutes; the source publishes once a day. 287 of the
    day's 288 ticks must store nothing rather than 287 duplicate rows."""
    async with untenanted_session() as session:
        _, first = await record_observation(
            session, rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, source_url="u"
        )
        _, second = await record_observation(
            session, rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, source_url="u"
        )
    assert (first, second) == (True, False)


async def test_a_corrected_rate_for_a_published_date_is_a_new_row() -> None:
    """The rate is INSIDE the idempotency key precisely so a correction is not swallowed
    as a duplicate — and the correction is the one observation nobody may lose."""
    async with untenanted_session() as session:
        await record_observation(
            session, rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, source_url="u"
        )
        corrected, inserted = await record_observation(
            session,
            rate=Decimal("88.5000"),
            as_of=date.today(),
            source=TEST_SOURCE,
            source_url="u",
        )
        assert inserted is True
        current = await latest_observation(session)
    assert current is not None and current.rate == corrected.rate
    assert observation_key(source=TEST_SOURCE, as_of=date.today(), rate=PUBLISHED) != (
        observation_key(source=TEST_SOURCE, as_of=date.today(), rate=Decimal("88.5000"))
    )


async def test_an_implausible_move_is_refused_and_the_previous_rate_keeps_serving() -> None:
    """A vendor that changes its unit is the defect this repo has already paid for once on
    the cost path. A 10x jump is refused; the belief the platform already holds survives."""
    async with untenanted_session() as session:
        await record_observation(
            session, rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, source_url="u"
        )
    with pytest.raises(ImplausibleRateError):
        async with untenanted_session() as session:
            await record_observation(
                session,
                rate=PUBLISHED * 10,
                as_of=date.today(),
                source=TEST_SOURCE,
                source_url="u",
            )
    async with untenanted_session() as session:
        current = await latest_observation(session)
    assert current is not None and current.rate == PUBLISHED


async def test_a_stored_rate_cannot_be_edited_or_deleted() -> None:
    """The append-only boundary at the database. `usage_events.meta.fx_rate` says what a
    call was costed at; this table is the only thing that can say where that came from, and
    an editable history is not evidence."""
    async with untenanted_session() as session:
        await record_observation(
            session, rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, source_url="u"
        )
    for statement in (
        "UPDATE fx_rate_observations SET rate = 9 WHERE source = :s",
        "UPDATE fx_rate_observations SET as_of = now() WHERE source = :s",
        "DELETE FROM fx_rate_observations WHERE source = :s",
    ):
        with pytest.raises(Exception) as raised:
            async with untenanted_session() as session:
                await session.execute(text(statement), {"s": TEST_SOURCE})
        assert "append-only" in str(raised.value), statement


async def test_the_stored_rate_keeps_its_published_digits() -> None:
    """NUMERIC(12,6) end to end: the number read back is the number published, not a
    float's nearest neighbour."""
    async with untenanted_session() as session:
        await record_observation(
            session, rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, source_url="u"
        )
        stored = await latest_observation(session)
    assert stored is not None
    assert isinstance(stored.rate, Decimal)
    assert stored.rate == PUBLISHED
    assert str(stored.rate) == "88.427500", "NUMERIC(12,6) — the value, at the column's scale"


# --- the poll and the job -------------------------------------------------------------


async def test_the_refresh_installs_the_stored_rate_for_the_conversion_to_read() -> None:
    async with untenanted_session() as session:
        await record_observation(
            session, rate=PUBLISHED, as_of=date.today(), source=TEST_SOURCE, source_url="u"
        )
    quote = await refresh_fx_snapshot()
    assert quote is not None and quote.rate == PUBLISHED
    cost = _engine()._cost(_cost_payload())
    assert cost is not None and cost.fx_rate == PUBLISHED


async def test_a_failed_pull_retries_then_alerts_rather_than_reporting_success() -> None:
    """A tick that returns instead of raising files a failure as a green run. There is no
    arq DLQ, so the last attempt's alert IS the dead-letter mechanism."""
    from arq import Retry

    alerts: list[str] = []

    async def failing(*_args: Any, **_kwargs: Any) -> tuple[Decimal, date]:
        raise FxPullError("the endpoint answered HTTP 503")

    import apps.workers.fx_pull as job_module

    original_fetch = job_module.fetch_published_rate
    original_alert = job_module.alert
    job_module.fetch_published_rate = failing  # type: ignore[assignment]
    job_module.alert = lambda *a, **k: alerts.append(str(a[1]))  # type: ignore[assignment]
    try:
        with pytest.raises(Retry):
            await pull_fx_rate({"job_try": 1})
        assert alerts == [], "an early attempt must not page anybody"
        with pytest.raises(FxPullError):
            await pull_fx_rate({"job_try": 3})
        assert alerts == ["fx_pull_failed"]
    finally:
        job_module.fetch_published_rate = original_fetch  # type: ignore[assignment]
        job_module.alert = original_alert  # type: ignore[assignment]


def test_the_schedule_is_every_five_minutes() -> None:
    """The founder's ask, asserted rather than described in a comment."""
    assert tuple(range(0, 60, 5)) == PULL_MINUTES
    assert len(PULL_MINUTES) == 12


# --- the wire -------------------------------------------------------------------------


def test_the_rate_crosses_the_wire_as_a_string_and_the_server_decides_staleness() -> None:
    """Hard rule 7 does not stop at the database: `88.4275` sent as a JSON number has been
    through a binary double before the screen sees it. And the browser is told the VERDICT,
    not the threshold — `apps/web/src/lib/api/aiQuota.ts:1-26`."""
    from apps.api.ops.fx_rates import FxObservation

    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    fresh = FxObservation(
        id=uuid.uuid4(),
        base_currency="USD",
        quote_currency="INR",
        rate=PUBLISHED,
        as_of=now.date(),
        source=TEST_SOURCE,
        source_url="u",
        observed_at=now - timedelta(minutes=3),
    )
    out = _build(fresh, now=now, fallback=str(FALLBACK), history=[fresh])
    dumped = json.loads(out.model_dump_json())
    assert dumped["effective_rate"] == "88.4275"
    assert isinstance(dumped["effective_rate"], str)
    assert dumped["state"] == "live" and dumped["using_fallback"] is False
    assert dumped["age_label"] == "3 minutes ago"
    assert dumped["history"][0]["rate"] == "88.4275"

    stale = replace(fresh, as_of=(now - MAX_QUOTE_AGE - timedelta(days=1)).date())
    degraded = _build(stale, now=now, fallback=str(FALLBACK), history=[])
    assert degraded.state == "stale"
    assert degraded.using_fallback is True
    assert degraded.effective_rate == str(FALLBACK), "the screen shows what money is using"

    nothing = _build(None, now=now, fallback=str(FALLBACK), history=[])
    assert nothing.state == "never_pulled" and nothing.published_rate is None


# --- 6. the source ladder (D-589) -----------------------------------------------------
#
# The defect these pin is the one measured on the live deployment on 11 Sep 2026: the
# pull HEALTHY, the feed it was pinned to seven days behind, no alarm anywhere on the
# pull path, and every vendor cost quietly converting at a constant typed a fortnight
# earlier. What the ladder must now hold true, in order of what a failure costs:
#
# 1. **The preference is not weakened.** FBIL serves whenever it can, and when it can the
#    lower rung is never even asked — a fallback that fires on a healthy day is a second
#    source of truth nobody chose.
# 2. **A fallback cannot route around the plausibility band.** The guard exists because a
#    vendor's minor-unit assumption once metered every call at 1/100th of cost; a rung
#    that skipped it would be that defect with a ladder to hide in.
# 3. **Provenance is per-rung and permanent.** Hard rule 4: the row can never be
#    annotated later, so the source string it carries is the only explanation there will
#    ever be — and the two rungs must be distinguishable at a glance.
# 4. **The three states are three alarms.** Degraded-but-published, everything-stale, and
#    the puller itself failing used to be two codes, and two of them read identically.

_LADDER_FBIL = FxRung(source="test:fbil", providers="FBIL", why="the preferred test rung")
_LADDER_DEFAULT = FxRung(source="test:default", providers=None, why="the fallback test rung")

# The two numbers the founder actually measured, which is why they are these and not round
# ones: they are 0.9% apart, so the ladder's own descent can never be confused with the
# plausibility band refusing a 10% move.
FBIL_RATE = Decimal("94.4914")
DEFAULT_RATE = Decimal("95.3900")


def _stale_date() -> date:
    """Seven days back — exactly the gap the live deployment was carrying."""
    return date.today() - MAX_QUOTE_AGE - timedelta(days=2)


def _install_ladder(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]
) -> tuple[list[tuple[str, dict[str, str]]], list[str]]:
    """Point the job at two TEST rungs and answer each from `answers`.

    Test sources, not the real ones, for a blunt reason: `fx_rate_observations` is a
    SHARED append-only table and `_purge` can only remove what it can recognise. A test
    that wrote `frankfurter:FBIL` rows would leave them in the store for every later test
    and for whoever runs the suite next. The rungs' real spellings are asserted directly
    from the constants instead (`test_the_two_rungs_are_distinguishable_on_a_ledger_row`).

    Returns `(alerts, fetched)` — every alarm raised by either module, and the rungs that
    were actually asked, in order.
    """
    import apps.api.ops.fx_rates as store_module
    import apps.workers.fx_pull as job_module

    alerts: list[tuple[str, dict[str, str]]] = []
    fetched: list[str] = []

    async def fake_fetch(rung: FxRung, client: Any = None) -> tuple[Decimal, date]:
        fetched.append(rung.source)
        answer = answers[rung.source]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def record(_stage: str, code: str, **kwargs: Any) -> None:
        alerts.append((code, {k: str(v) for k, v in kwargs.items() if k != "detail"}))

    monkeypatch.setattr(job_module, "LADDER", (_LADDER_FBIL, _LADDER_DEFAULT))
    monkeypatch.setattr(job_module, "PREFERRED_RUNG", _LADDER_FBIL)
    monkeypatch.setattr(job_module, "fetch_published_rate", fake_fetch)
    monkeypatch.setattr(job_module, "alert", record)
    monkeypatch.setattr(store_module, "alert", record)
    return alerts, fetched


def test_the_two_rungs_are_distinguishable_on_a_ledger_row() -> None:
    """The source string is stamped on every `usage_events` row the rate converts, and
    hard rule 4 means that row can never be annotated afterwards — so "which rung priced
    this minute" has to be legible from the string alone, six months later."""
    assert FBIL_RUNG.source == "frankfurter:FBIL"
    assert DEFAULT_RUNG.source == "frankfurter:default"
    assert FBIL_RUNG.source != DEFAULT_RUNG.source
    assert LADDER == (FBIL_RUNG, DEFAULT_RUNG), "FBIL is preferred, and the order IS the rule"
    assert PREFERRED_RUNG is FBIL_RUNG
    # The URL stored on the row is the request an operator re-runs by hand, query string
    # and all — it is not reconstructed by a reader, so rung 2 is reproducible too.
    assert FBIL_RUNG.url == "https://api.frankfurter.dev/v2/rate/USD/INR?providers=FBIL"
    assert DEFAULT_RUNG.url == "https://api.frankfurter.dev/v2/rate/USD/INR"
    assert "providers" not in DEFAULT_RUNG.url, "rung 2 IS the unfiltered request"


async def test_the_preferred_rung_serves_and_the_fallback_is_never_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A healthy day: one request, one row, no alarm. The preference costs nothing and
    the platform never learns a number it did not need."""
    alerts, fetched = _install_ladder(
        monkeypatch,
        {
            "test:fbil": (FBIL_RATE, date.today()),
            "test:default": AssertionError("rung 2 must not be fetched while rung 1 serves"),
        },
    )
    summary = json.loads(await pull_fx_rate({"job_try": 1}))
    assert fetched == ["test:fbil"]
    assert summary["serving"] == "preferred"
    assert summary["source"] == "test:fbil"
    assert summary["rate"] == "94.491400"
    assert alerts == []
    cost = _engine()._cost(_cost_payload())
    assert cost is not None and cost.fx_source == "test:fbil" and cost.fx_rate == FBIL_RATE


async def test_the_fallback_rung_serves_when_the_preferred_one_has_gone_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE MEASURED FAILURE, end to end. The benchmark is seven days behind and the API
    around it is current: money converts at the fallback rung's published rate, the row
    says which rung, and an operator is told the provenance moved."""
    alerts, fetched = _install_ladder(
        monkeypatch,
        {
            "test:fbil": (FBIL_RATE, _stale_date()),
            "test:default": (DEFAULT_RATE, date.today()),
        },
    )
    summary = json.loads(await pull_fx_rate({"job_try": 1}))
    assert fetched == ["test:fbil", "test:default"], "the preferred rung is asked FIRST"
    assert summary["serving"] == "fallback_source"
    assert summary["source"] == "test:default"

    # Both rungs are RECORDED — the stale benchmark row is evidence, not noise, and it is
    # what makes "the feed was behind" re-derivable rather than inferred from a silence.
    async with untenanted_session() as session:
        stored = {row.source: row for row in await recent_observations(session, limit=50)}
    assert set(stored) == {"test:fbil", "test:default"}
    assert stored["test:fbil"].as_of == _stale_date()
    assert stored["test:default"].source_url == _LADDER_DEFAULT.url

    # STATE 1 OF 3: degraded. Published rate, moved provenance, not urgent.
    assert [code for code, _ in alerts] == ["fx_source_degraded"]
    assert alerts[0][1] == {
        "source": "test:default",
        "preferred_source": "test:fbil",
        "reason": "stale_publication",
    }

    # And the conversion actually follows: `latest_observation` picks the newest
    # publication, which is the serving rung, with no second spelling of the ladder in SQL.
    cost = _engine()._cost(_cost_payload())
    assert cost is not None
    assert cost.fx_rate == DEFAULT_RATE
    assert cost.fx_source == "test:default", "the ROW says which rung priced this minute"
    assert cost.fx_as_of == date.today()


async def test_a_preferred_rung_that_does_not_answer_still_reaches_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quiet provider and an unreachable one are the same thing to the ladder and
    different things to an operator, so the alarm carries WHICH."""
    alerts, fetched = _install_ladder(
        monkeypatch,
        {
            "test:fbil": FxFeedUnreachableError("the endpoint answered HTTP 503"),
            "test:default": (DEFAULT_RATE, date.today()),
        },
    )
    summary = json.loads(await pull_fx_rate({"job_try": 1}))
    assert fetched == ["test:fbil", "test:default"]
    assert summary["serving"] == "fallback_source"
    assert alerts[0][0] == "fx_source_degraded"
    assert alerts[0][1]["reason"] == "request_failed"


async def test_a_response_the_parser_refuses_is_a_different_reason_than_a_quiet_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`unusable_response` means the vendor's CONTRACT moved, which is the one refusal an
    operator must read docs about rather than wait out. It may not be reported as
    availability."""
    alerts, _ = _install_ladder(
        monkeypatch,
        {
            "test:fbil": FxPullError("the response carried no numeric `rate`"),
            "test:default": (DEFAULT_RATE, date.today()),
        },
    )
    await pull_fx_rate({"job_try": 1})
    assert alerts[0][1]["reason"] == "unusable_response"


async def test_the_typed_constant_serves_only_when_every_published_rung_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STATE 2 OF 3, and the one that used to be indistinguishable from state 1. Both
    published rungs are behind the ceiling, so the operator's number is what money uses —
    and `fx_rate_stale` now means exactly that about the WHOLE ladder."""
    alerts, fetched = _install_ladder(
        monkeypatch,
        {
            "test:fbil": (FBIL_RATE, _stale_date()),
            "test:default": (DEFAULT_RATE, _stale_date()),
        },
    )
    summary = json.loads(await pull_fx_rate({"job_try": 1}))
    assert fetched == ["test:fbil", "test:default"], "every rung is tried before the constant"
    assert summary["serving"] == "configured_fallback"
    assert summary["source"] is None and summary["rate"] is None

    codes = [code for code, _ in alerts]
    assert "fx_rate_stale" in codes, "the bottom of the ladder is the alarm it always was"
    assert "fx_source_degraded" not in codes, "nothing is degraded when nothing is serving"
    assert "fx_pull_failed" not in codes, "the feeds answered — they are behind, not broken"

    cost = _engine()._cost(_cost_payload())
    assert cost is not None
    assert cost.fx_rate == FALLBACK
    assert cost.fx_source == "configured:usd_inr_rate"
    assert cost.fx_as_of is None, "a typed number has no publication date"


async def test_the_plausibility_band_applies_to_the_fallback_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fallback that skipped the guard would be the 1/100th-of-cost defect with a ladder
    to hide in. Rung 2 is written through the same door, so it is judged the same way."""
    alerts, _ = _install_ladder(
        monkeypatch,
        {
            "test:fbil": (FBIL_RATE, _stale_date()),
            "test:default": (FBIL_RATE * 10, date.today()),
        },
    )
    with pytest.raises(ImplausibleRateError):
        await pull_fx_rate({"job_try": 1})
    assert [code for code, _ in alerts] == ["fx_rate_implausible"]
    assert alerts[0][1]["source"] == "test:default", "the alarm names the rung that produced it"
    # The belief the platform already held survives — the refused number is not stored.
    async with untenanted_session() as session:
        assert {row.source for row in await recent_observations(session, limit=50)} == {"test:fbil"}


async def test_the_ladder_does_not_descend_past_a_rate_it_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "The feed is quiet" is what the ladder is for. "The feed answered and we do not
    believe it" is a human's problem from the first occurrence — descending would hand the
    platform to another source without anybody looking at the first one."""
    async with untenanted_session() as session:
        await record_observation(
            session, rate=FBIL_RATE, as_of=date.today(), source="test:seed", source_url="u"
        )
    alerts, fetched = _install_ladder(
        monkeypatch,
        {
            "test:fbil": (FBIL_RATE * 10, date.today()),
            "test:default": (DEFAULT_RATE, date.today()),
        },
    )
    with pytest.raises(ImplausibleRateError):
        await pull_fx_rate({"job_try": 1})
    assert fetched == ["test:fbil"], "rung 2 is NEVER asked after a rate we refused"
    assert [code for code, _ in alerts] == ["fx_rate_implausible"]
    assert alerts[0][1]["source"] == "test:fbil"


async def test_every_rung_failing_is_the_pull_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    """STATE 3 OF 3, unchanged: nothing answered at all, so the retry ladder runs and the
    last attempt pages. A rung that merely published something OLD must never land here —
    that is the distinction `hard_failure` draws and the two states above assert."""
    from arq import Retry

    alerts, _ = _install_ladder(
        monkeypatch,
        {
            "test:fbil": FxFeedUnreachableError("the endpoint answered HTTP 503"),
            "test:default": FxFeedUnreachableError("the endpoint answered HTTP 503"),
        },
    )
    with pytest.raises(Retry):
        await pull_fx_rate({"job_try": 1})
    assert alerts == [], "an early attempt must not page anybody"
    with pytest.raises(FxPullError):
        await pull_fx_rate({"job_try": 3})
    assert [code for code, _ in alerts] == ["fx_pull_failed"]


async def test_both_rungs_are_read_by_one_parser() -> None:
    """Rung 2 is the same endpoint with one query parameter removed, so it has the same
    landmines — a future `date` that would disable the staleness ceiling, a pair that is
    not the one we asked for, a `rate` whose type changed. A second parser is a second
    place those get fixed one at a time, so there is not one."""
    import inspect

    import apps.workers.fx_pull as job_module
    import httpx

    poisoned = _body(date=(date.today() + timedelta(days=30)).isoformat())
    for rung in LADDER:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=poisoned))
        )
        with pytest.raises(FxPullError):
            await fetch_published_rate(rung, client)
        await client.aclose()

    # Structural, not behavioural: the parse happens in exactly one place. A second
    # `json.loads` in this module is a second contract to keep in step with the vendor's.
    source = inspect.getsource(job_module)
    assert source.count("json.loads(") == 1, "one parser, one place the vendor's shape lives"


async def test_the_fallback_rung_asks_for_the_unfiltered_rate() -> None:
    """The whole of rung 2 is the absence of one query parameter, so it is asserted rather
    than trusted to a comment — a fallback that silently still filtered to the dead
    provider would look healthy and fix nothing."""
    import httpx

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=_body())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await fetch_published_rate(DEFAULT_RUNG, client)
    await fetch_published_rate(FBIL_RUNG, client)
    await client.aclose()
    assert seen == [
        "https://api.frankfurter.dev/v2/rate/USD/INR",
        "https://api.frankfurter.dev/v2/rate/USD/INR?providers=FBIL",
    ]
