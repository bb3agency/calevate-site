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
    PULL_MINUTES,
    FxPullError,
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
        await fetch_published_rate(client)
    await client.aclose()


async def test_a_transport_failure_is_a_failed_pull() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(FxPullError):
        await fetch_published_rate(client)
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
    await fetch_published_rate(client)
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
