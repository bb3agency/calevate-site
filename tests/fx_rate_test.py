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
    FBIL_AUTHENTICATED,
    FBIL_DIRECT_RUNG,
    FBIL_URL,
    FBIL_WINDOW,
    FRANKFURTER_DEFAULT_RUNG,
    FRANKFURTER_FBIL_RUNG,
    LADDER,
    PREFERRED_RUNG,
    PULL_MINUTES,
    FxFeedUnreachableError,
    FxPullError,
    FxRung,
    fetch_published_rate,
    parse_fbil_response,
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
        await fetch_published_rate(FRANKFURTER_FBIL_RUNG, client)
    await client.aclose()


async def test_a_transport_failure_is_a_failed_pull() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(FxPullError):
        await fetch_published_rate(FRANKFURTER_FBIL_RUNG, client)
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
    await fetch_published_rate(FRANKFURTER_FBIL_RUNG, client)
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
        raise FxFeedUnreachableError("the endpoint answered HTTP 503")

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


def _test_rung(source: str, why: str) -> FxRung:
    """A rung whose request and parser are never reached — `_install_ladder` replaces
    `fetch_published_rate` wholesale, so what is under test here is the WALK. The real
    rungs' requests and parsers are asserted directly from the constants below."""
    return FxRung(
        source=source,
        url_for=lambda today: f"https://example.invalid/{source}?on={today.isoformat()}",
        parse=parse_rate_response,
        why=why,
    )


_LADDER_DIRECT = _test_rung("test:direct", "the preferred test rung")
_LADDER_FBIL = _test_rung("test:fbil", "the first fallback test rung")
_LADDER_DEFAULT = _test_rung("test:default", "the last fallback test rung")

# The two numbers the founder actually measured, which is why they are these and not round
# ones: they are 0.9% apart, so the ladder's own descent can never be confused with the
# plausibility band refusing a 10% move.
FBIL_RATE = Decimal("94.4914")
DEFAULT_RATE = Decimal("95.3900")


def _stale_date() -> date:
    """Seven days back — exactly the gap the live deployment was carrying."""
    return date.today() - MAX_QUOTE_AGE - timedelta(days=2)


def _install_ladder(
    monkeypatch: pytest.MonkeyPatch,
    answers: dict[str, Any],
    rungs: tuple[FxRung, ...] = (_LADDER_FBIL, _LADDER_DEFAULT),
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

    async def fake_fetch(
        rung: FxRung, client: Any = None, *, today: date | None = None
    ) -> tuple[Decimal, date]:
        fetched.append(rung.source)
        answer = answers[rung.source]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def record(_stage: str, code: str, **kwargs: Any) -> None:
        alerts.append((code, {k: str(v) for k, v in kwargs.items() if k != "detail"}))

    monkeypatch.setattr(job_module, "LADDER", rungs)
    monkeypatch.setattr(job_module, "PREFERRED_RUNG", rungs[0])
    monkeypatch.setattr(job_module, "fetch_published_rate", fake_fetch)
    monkeypatch.setattr(job_module, "alert", record)
    monkeypatch.setattr(store_module, "alert", record)
    return alerts, fetched


def test_the_rungs_are_distinguishable_on_a_ledger_row() -> None:
    """The source string is stamped on every `usage_events` row the rate converts, and
    hard rule 4 means that row can never be annotated afterwards — so "which rung priced
    this minute" has to be legible from the string alone, six months later.

    D-609 put the administrator's own endpoint on top. The order IS the rule and nothing
    else in this repo encodes it, so it is asserted as an equality rather than by
    membership: a rung appended in the wrong place would still pass an `in`."""
    assert FBIL_DIRECT_RUNG.source == "fbil:refrates"
    assert FRANKFURTER_FBIL_RUNG.source == "frankfurter:FBIL"
    assert FRANKFURTER_DEFAULT_RUNG.source == "frankfurter:default"
    assert LADDER == (FBIL_DIRECT_RUNG, FRANKFURTER_FBIL_RUNG, FRANKFURTER_DEFAULT_RUNG)
    assert PREFERRED_RUNG is FBIL_DIRECT_RUNG, "the benchmark's own publisher is preferred"
    assert len({rung.source for rung in LADDER}) == len(LADDER), "two rungs, one row, no clue"

    # The URL stored on the row is the request an operator re-runs by hand, query string
    # and all — it is not reconstructed by a reader, so every rung is reproducible.
    day = date(2026, 9, 15)
    assert FBIL_DIRECT_RUNG.url_for(day) == (
        "https://www.fbil.org.in/wasdm/refrates/fetchfiltered"
        "?fromDate=2026-09-05&toDate=2026-09-15&authenticated=false"
    )
    assert FRANKFURTER_FBIL_RUNG.url_for(day) == (
        "https://api.frankfurter.dev/v2/rate/USD/INR?providers=FBIL"
    )
    assert FRANKFURTER_DEFAULT_RUNG.url_for(day) == "https://api.frankfurter.dev/v2/rate/USD/INR"
    assert "providers" not in FRANKFURTER_DEFAULT_RUNG.url_for(day), "it IS the unfiltered request"


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
    assert stored["test:default"].source_url == _LADDER_DEFAULT.url_for(date.today())

    # STATE 1 OF 3: degraded. Published rate, moved provenance, not urgent.
    assert [code for code, _ in alerts] == ["fx_source_degraded"]
    assert alerts[0][1] == {
        "source": "test:default",
        "preferred_source": "test:fbil",
        "reason": "stale_publication",
        # A rung that ANSWERED and was merely behind has no error to name, so the alarm's
        # `code` falls back to the reason rather than inventing one. The three refusals
        # that DO have a code are asserted below.
        "refusal_code": "stale_publication",
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
            "test:fbil": FxPullError(
                "the response carried no numeric `rate`", code="rate_not_numeric"
            ),
            "test:default": (DEFAULT_RATE, date.today()),
        },
    )
    await pull_fx_rate({"job_try": 1})
    assert alerts[0][1]["reason"] == "unusable_response"
    # AND the precise thing that was wrong, which is what an operator goes and looks at.
    # `unusable_response` alone used to carry four unlike failures to one playbook.
    assert alerts[0][1]["refusal_code"] == "rate_not_numeric"


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


async def test_both_frankfurter_rungs_are_read_by_one_parser() -> None:
    """Rung 3 is rung 2's endpoint with one query parameter removed, so it has the same
    landmines — a future `date` that would disable the staleness ceiling, a pair that is
    not the one we asked for, a `rate` whose type changed. A second parser is a second
    place those get fixed one at a time, so there is not one."""
    import httpx

    poisoned = _body(date=(date.today() + timedelta(days=30)).isoformat())
    for rung in (FRANKFURTER_FBIL_RUNG, FRANKFURTER_DEFAULT_RUNG):
        assert rung.parse is parse_rate_response
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=poisoned))
        )
        with pytest.raises(FxPullError):
            await fetch_published_rate(rung, client)
        await client.aclose()


def test_the_wire_is_decoded_in_exactly_one_place() -> None:
    """D-609 put a SECOND grammar on the ladder, which is the moment a second
    `json.loads` becomes tempting — and `parse_float=Decimal` is the one keyword whose
    omission is invisible until an invoice is wrong (hard rule 7). Structural, not
    behavioural: the two parsers differ in what they read, never in how the bytes become
    numbers."""
    import inspect

    import apps.workers.fx_pull as job_module

    source = inspect.getsource(job_module)
    assert source.count("json.loads(") == 1, "one decoder, one place the Decimal rule lives"


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
    await fetch_published_rate(FRANKFURTER_DEFAULT_RUNG, client)
    await fetch_published_rate(FRANKFURTER_FBIL_RUNG, client)
    await client.aclose()
    assert seen == [
        "https://api.frankfurter.dev/v2/rate/USD/INR",
        "https://api.frankfurter.dev/v2/rate/USD/INR?providers=FBIL",
    ]


# --- 7. the FBIL rung, called directly (D-609) ----------------------------------------
#
# `www.fbil.org.in` is EGRESS-BLOCKED from this environment — measured 15 Sep 2026,
# `curl: (56) CONNECT tunnel failed, response 403`, HTTP 000 — so NO BYTE OF A LIVE
# RESPONSE HAS BEEN SEEN and every fixture below is derived from the wire contract in the
# module docstring, whose evidence class is VERIFIED-OSS-AT-PINNED-COMMIT
# (`lib/provider/adapters/fbil.rb` at `45e1b89ab0a725aedecdd1fa678a22eff5908a48`) and
# which is FRANKFURTER'S READING OF FBIL, not FBIL's own published documentation. These
# tests therefore pin OUR parser against THAT contract; they are not evidence about the
# live endpoint and OPERATIONS §2 gate 39 is where it is settled.
#
# Ranked by what a failure costs:
#
# 1. **The units division.** `subProdName` carries how many units the rate is quoted per.
#    Assuming 1 on a record that says 100 is a hundredfold error on every invoice — the
#    `_MINOR_UNITS_PER_MAJOR` defect with a new feed to arrive through.
# 2. **The published digits survive.** Same hard rule 7 property the Frankfurter parser
#    has, now through a DIVISION as well as a decode.
# 3. **Four unlike refusals stay four.** A non-200, a body that is not an array, an array
#    with no dollar record and a `subProdName` that does not parse must not all arrive as
#    "the feed is quiet".

#: A published figure with four decimals that a binary float cannot hold exactly, quoted
#: per TEN dollars — so one fixture proves the decode AND the division at once.
#: `float("884.275")` is 884.27499999999997726263245567679405212402343750.
_FBIL_TEN_USD = Decimal("884.275")


def _fbil_record(name: str, *, rate: Any, run_date: str | None = None) -> dict[str, Any]:
    return {
        "subProdName": name,
        "processRunDate": run_date or date.today().isoformat(),
        "rate": rate,
    }


def _fbil_body(*records: dict[str, Any]) -> str:
    """FBIL's documented container: a JSON ARRAY of records, every pair in one response."""
    return json.dumps(list(records))


def test_the_fbil_rate_survives_the_units_division_as_an_exact_decimal() -> None:
    """THE ONE THAT MATTERS. `884.275` quoted per TEN dollars is `88.4275` per dollar, and
    it has to be that number EXACTLY — not a float's nearest neighbour, and not a
    quotient rounded on the way through. `json.loads(parse_float=Decimal)` keeps the
    published digits and the division is `Decimal / Decimal`, so the whole path from their
    wire to `NUMERIC(12,6)` is exact (hard rule 7)."""
    rate, as_of = parse_fbil_response(
        _fbil_body(_fbil_record("INR / 10 USD", rate=float(_FBIL_TEN_USD)))
    )
    assert isinstance(rate, Decimal)
    assert rate == PUBLISHED
    assert str(rate) == "88.4275", "the exact digits the division implies, not a float's"
    # What a float round-trip would have produced, spelled out rather than computed, so
    # the assertion still means something if someone "tidies" the Decimal path away.
    assert rate != Decimal("88.427499999999997726263245567679405212402343750")
    assert as_of == date.today()


def test_the_fbil_units_are_read_and_never_assumed_to_be_one() -> None:
    """Their own comment's example is `"INR / 100 JPY"` — rupees per ONE HUNDRED yen — so
    a feed that ever quoted the dollar per 100 is a shape their client already handles.
    `FxQuote.rate` is rupees per ONE dollar, so the divisor comes from the record."""
    per_one, _ = parse_fbil_response(_fbil_body(_fbil_record("INR / 1 USD", rate=88.4275)))
    per_hundred, _ = parse_fbil_response(_fbil_body(_fbil_record("INR / 100 USD", rate=8842.75)))
    assert per_one == per_hundred == PUBLISHED, "the same rate, quoted two ways"
    # And the wrong reading, named, so this test fails loudly rather than subtly if the
    # divisor is ever dropped: a hundredfold error is what `MAX_PLAUSIBLE_MOVE` catches
    # SECOND, and a guard that has to fire is a guard that was already needed.
    assert per_hundred != Decimal("8842.75")


def test_only_the_dollar_record_is_read_out_of_a_whole_days_publication() -> None:
    """The array carries every pair FBIL published. Picking the wrong one converts every
    vendor minute at the yen, which the plausibility band would catch and nobody should
    rely on it to."""
    rate, _ = parse_fbil_response(
        _fbil_body(
            _fbil_record("INR / 100 JPY", rate=59.1234),
            _fbil_record("INR / 1 EUR", rate=95.5),
            _fbil_record("INR / 10 USD", rate=float(_FBIL_TEN_USD)),
            _fbil_record("INR / 1 GBP", rate=112.25),
        )
    )
    assert rate == PUBLISHED


def test_the_newest_publication_in_the_window_wins_and_a_correction_supersedes() -> None:
    """The request asks for a WINDOW, so the array can hold several business days. The
    newest `processRunDate` is the rate in force, and among records sharing a date the
    LATER one wins — the same tiebreak `latest_observation` applies, for the same reason:
    a correction is the one observation nobody may lose to an accident of order."""
    older = (date.today() - timedelta(days=3)).isoformat()
    today = date.today().isoformat()
    rate, as_of = parse_fbil_response(
        _fbil_body(
            _fbil_record("INR / 1 USD", rate=90.1111, run_date=older),
            _fbil_record("INR / 1 USD", rate=91.2222, run_date=today),
            _fbil_record("INR / 1 USD", rate=88.4275, run_date=today),
        )
    )
    assert as_of == date.today()
    assert rate == PUBLISHED, "the corrected figure, not the one it corrects"


def test_a_stale_fbil_window_still_produces_a_rate_for_the_ladder_to_judge() -> None:
    """**THE WINDOW IS WIDER THAN THE CEILING ON PURPOSE.** A publication that is merely
    too old must still ARRIVE, be recorded (the eager write) and be refused by the ONE
    staleness predicate — not vanish into "no record found", which is the vocabulary
    reserved for the feed having changed under us."""
    assert FBIL_WINDOW > MAX_QUOTE_AGE, "or 'behind' and 'broken' become the same response"
    behind = date.today() - MAX_QUOTE_AGE - timedelta(days=2)
    rate, as_of = parse_fbil_response(
        _fbil_body(_fbil_record("INR / 1 USD", rate=88.4275, run_date=behind.isoformat()))
    )
    assert (rate, as_of) == (PUBLISHED, behind)
    assert FxQuote(rate=rate, as_of=as_of, source="fbil:refrates", observed_at=datetime.now(UTC))


@pytest.mark.parametrize(
    ("body", "code", "because"),
    [
        ("<html>service unavailable</html>", "not_json", "an error page is not a rate"),
        ('{"rate": 88.4275}', "not_an_array", "the documented container is an ARRAY"),
        ("[]", "no_usd_record", "an empty window is not silence — say so"),
        (
            _fbil_body(_fbil_record("INR / 1 EUR", rate=95.5)),
            "no_usd_record",
            "FBIL answered, about currencies that do not include the dollar",
        ),
        (
            _fbil_body(_fbil_record("USD-INR REFERENCE RATE", rate=88.4275)),
            "sub_prod_name_unparsable",
            "the naming convention carries the UNITS — unreadable means unusable",
        ),
        (
            _fbil_body(_fbil_record("INR / 0 USD", rate=88.4275)),
            "no_usd_record",
            "a zero-unit quote is a publication defect, not a division by zero",
        ),
        (
            _fbil_body(_fbil_record("INR / 1 USD", rate="88.4275")),
            "no_usd_record",
            "a feed that changed the type of its money field must be read about",
        ),
        (
            _fbil_body(_fbil_record("INR / 1 USD", rate=88.4275, run_date="15-09-2026")),
            "date_not_iso",
            # THE MOST LIKELY FIRST FAILURE OF THIS RUNG, and it gets its own word:
            # nothing in this tree has read FBIL's date format, so a dollar record that
            # is skipped for its DATE alone must not report as "FBIL published no dollar".
            "a date this parser cannot read is not coerced into one it can",
        ),
    ],
)
def test_each_fbil_refusal_names_a_different_thing_to_go_and_look_at(
    body: str, code: str, because: str
) -> None:
    """**NEVER A SILENT FALL-THROUGH THAT READS AS "THE FEED IS QUIET".** The live endpoint
    is unreachable from here, so this parser is the only thing between a changed feed and
    every invoice — and an operator who is paged needs the refusal to name the line of the
    playbook, not just the playbook. Nothing is coerced, defaulted or guessed."""
    with pytest.raises(FxPullError) as raised:
        parse_fbil_response(body)
    assert raised.value.code == code, because
    # The tally is what separates "FBIL published no dollar today" from "FBIL's records
    # stopped parsing", and it is COUNTS ONLY — the vendor's bytes never reach a log line.
    assert "88.4275" not in str(raised.value), "a refusal reports counts, never the payload"


def test_fbils_real_datetime_publication_stamp_parses() -> None:
    """THE REGRESSION. This exact body is what FBIL actually served, and we refused it.

    `_publication_date` accepted a bare `YYYY-MM-DD` only, on a docstring that asserted
    `date.fromisoformat` "also accepts an ISO DATETIME" — false on 3.12, where only
    `datetime.fromisoformat` took the 3.11 relaxation. So on the first day the direct rung
    ran in production every dollar record was skipped `date_not_iso`, the tally read
    `date_unparsable=2`, and the ladder degraded to `frankfurter:default`. The ladder
    working is why this cost nothing; the parser was still wrong.

    **EVIDENCE: VENDOR-MEASURED, founder-relayed, 15 Sep 2026** — the bytes below are from
    a live GET against `www.fbil.org.in`, which is egress-blocked from CI, so this fixture
    is the only place that reading exists. The per-100 JPY row is kept deliberately: it is
    the live proof that `units` really does vary, and that reading it rather than assuming
    1 is what stands between a rate and a hundredfold error.
    """
    body = (
        '[{"processRunDate":"2026-09-08 00:00:00","subProdName":"INR / 1 USD",'
        '"displayTime":"2026-09-08 13:00:00","rate":94.717800,"comments":""},'
        '{"processRunDate":"2026-09-08 00:00:00","subProdName":"INR / 100 JPY",'
        '"displayTime":"2026-09-08 13:00:00","rate":61.690000,"comments":""},'
        '{"processRunDate":"2026-09-07 00:00:00","subProdName":"INR / 1 USD",'
        '"displayTime":"2026-09-07 13:00:00","rate":94.446700,"comments":""}]'
    )
    rate, as_of = parse_fbil_response(body)
    assert as_of == date(2026, 9, 8), "the newest publication wins, and its TIME is dropped"
    assert rate == Decimal("94.7178"), "the dollar rate, exact and not the yen row"


def test_a_future_fbil_publication_date_is_refused_rather_than_skipped() -> None:
    """`as_of` is what the staleness ceiling is measured against, so a date in the future
    is the one value a bad feed could use to disable the ceiling entirely — a rate dated
    2030 would never go stale. It refuses the whole response rather than quietly falling
    back to an older record, because the older record would then serve under a feed we
    already know is wrong about dates."""
    ahead = (date.today() + timedelta(days=30)).isoformat()
    with pytest.raises(FxPullError) as raised:
        parse_fbil_response(
            _fbil_body(
                _fbil_record("INR / 1 USD", rate=88.4275),
                _fbil_record("INR / 1 USD", rate=88.4275, run_date=ahead),
            )
        )
    assert raised.value.code == "date_in_future"


async def test_the_fbil_request_is_the_window_the_ceiling_implies() -> None:
    """The exact request is what `source_url` stores and what a human re-runs to reproduce
    a disputed figure, so it is asserted rather than trusted to a comment. `authenticated`
    is the STRING `false`: a Python `False` would go on the wire capitalised, and what an
    undocumented endpoint does with an unrecognised value is not something to find out on
    a money path."""
    import httpx

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=_fbil_body(_fbil_record("INR / 1 USD", rate=88.4275)))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rate, _ = await fetch_published_rate(FBIL_DIRECT_RUNG, client, today=date(2026, 9, 15))
    await client.aclose()
    assert rate == PUBLISHED
    assert seen == [
        f"{FBIL_URL}?fromDate=2026-09-05&toDate=2026-09-15&authenticated={FBIL_AUTHENTICATED}"
    ]
    assert FBIL_AUTHENTICATED == "false" and isinstance(FBIL_AUTHENTICATED, str)


async def test_a_non_200_from_fbil_is_availability_and_not_a_changed_contract() -> None:
    """FBIL's endpoint is undocumented, so a status code from it is not interpreted at all
    — only reported. It is `request_failed`: wait for the next tick, do not go and read
    docs, and do NOT let it read as the feed merely being behind."""
    import httpx

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(503, text="busy"))
    )
    with pytest.raises(FxFeedUnreachableError) as raised:
        await fetch_published_rate(FBIL_DIRECT_RUNG, client)
    await client.aclose()
    assert raised.value.code == "request_failed"
    assert "503" in str(raised.value), "the status is the actionable half"


async def test_the_fbil_rung_is_written_through_the_same_plausibility_door(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The top rung cannot route around `ImplausibleRateError` any more than a fallback
    can — and it is the rung with the units division, i.e. the one whose arithmetic the
    band exists to catch. A hundredfold reading is refused, nothing is stored, and the
    ladder does NOT descend past it."""
    async with untenanted_session() as session:
        await record_observation(
            session, rate=PUBLISHED, as_of=date.today(), source="test:seed", source_url="u"
        )
    alerts, fetched = _install_ladder(
        monkeypatch,
        {
            "test:direct": (PUBLISHED * 100, date.today()),
            "test:fbil": (PUBLISHED, date.today()),
        },
        rungs=(_LADDER_DIRECT, _LADDER_FBIL),
    )
    with pytest.raises(ImplausibleRateError):
        await pull_fx_rate({"job_try": 1})
    assert fetched == ["test:direct"], "a rate we refused hands over to nobody"
    assert [code for code, _ in alerts] == ["fx_rate_implausible"]


async def test_the_ladder_descends_past_two_stale_rungs_to_the_third(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-609 made the ladder three published rungs deep, and the descent is still ONE loop
    over ONE list: rung 1 and rung 2 share a publisher, so when FBIL itself stops
    publishing they go stale TOGETHER and rung 3 is what is left. Every rung fetched is
    recorded, in order, and the newest publication serves with no second spelling of the
    ladder in SQL."""
    alerts, fetched = _install_ladder(
        monkeypatch,
        {
            "test:direct": (FBIL_RATE, _stale_date()),
            "test:fbil": (FBIL_RATE, _stale_date()),
            "test:default": (DEFAULT_RATE, date.today()),
        },
        rungs=(_LADDER_DIRECT, _LADDER_FBIL, _LADDER_DEFAULT),
    )
    summary = json.loads(await pull_fx_rate({"job_try": 1}))
    assert fetched == ["test:direct", "test:fbil", "test:default"], "in preference order"
    assert summary["serving"] == "fallback_source"
    assert summary["source"] == "test:default"
    assert summary["preferred_source"] == "test:direct"

    async with untenanted_session() as session:
        stored = {row.source for row in await recent_observations(session, limit=50)}
    assert stored == {"test:direct", "test:fbil", "test:default"}, "the write is EAGER"

    assert [code for code, _ in alerts] == ["fx_source_degraded"]
    assert alerts[0][1]["preferred_source"] == "test:direct"
    assert alerts[0][1]["reason"] == "stale_publication"

    cost = _engine()._cost(_cost_payload())
    assert cost is not None and cost.fx_source == "test:default"
