"""**THE MEASUREMENT IS WIRED TO THE ARITHMETIC, AND CANNOT QUIETLY COME UNWIRED (D-557).**

`billing/tts_speaking_rate.py` measured the fleet's chars-per-call-minute from our own
transcripts, published pooled/p50/p95 on an operator's board — and nothing consumed it.
Every cost floor, margin and break-even still divided by TRD §10.1's assumed 540, the one
input in the whole model that the doc itself calls unmeasured (pilot gate 12) and the one
worth the most: ₹1.12 a minute between the ends of the band. A number that is measured,
displayed and then ignored by the arithmetic it was built to correct is a half-wired
feature in CLAUDE.md's exact sense.

Six properties, each of which is a way the loop could reopen while every screen still
looked right:

- **The floor is the function, and the constant is the function at the assumed basis.** One
  arithmetic, so the measured figure and the frozen refusal can differ by BASIS and never by
  rounding.
- **A figure below the bar cannot be called a measurement.** The type refuses to hold that
  combination at all (`SpeakingRateBasis.__post_init__`), rather than leaving four consumers
  to remember the check — hard rule 11 applied to our own data.
- **The counter and the walk are two spellings of ONE measurement.** The board walks the
  client book for its percentiles; the cost model reads a platform counter in one row. If
  they ever disagree about the pooled rate, one of them is wrong.
- **The meter moves the counter, for EVERY voice, exactly once.** A counter nobody
  increments reads zero for ever, and zero here means "nobody has spoken", which would keep
  the assumption in force silently.
- **The consumers say which rate they used.** A margin from a measurement and a margin from
  an assumption are different claims; both wire blocks carry the basis, the sample size and
  the window.
- **The refusal stays frozen.** D-556's settlement one leg over: the veto is a structural
  bound, the moving figure is a loud warning. A refusal that moved with a measurement would
  refuse tomorrow the card it accepted today because twenty more calls were answered.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.rates import (
    ASSUMED_SPEAKING_RATE,
    SELF_SERVE_COST_FLOOR_INR_PER_MIN,
    TTS_ASSUMED_CHARS_PER_CALL_MINUTE,
    SpeakingRateBasis,
    assumed_speaking_rate,
    cost_floor_inr_per_min,
    sarvam_cost_floor_at,
    tts_inr_per_call_minute,
)
from apps.api.billing.tts_speaking_rate import (
    TTS_SPEAKING_RATE_MIN_CALLS,
    FleetSpeakingRate,
    bump_speaking_rate,
    fleet_speaking_rate,
    sample_tenant,
    summarize,
)
from apps.api.core.fx import UsdInrRate
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops import config_routes
from sqlalchemy import text


#: A month of this case's own, from a range no real row can be in — the counter is a SHARED
#: platform row keyed by month, so two cases writing the same one would pool each other's
#: calls into a fleet speaking rate. `tests/cartesia_volume_test.py` carries the same trap
#: for the same reason.
def _month() -> str:
    return f"{3000 + uuid.uuid4().int % 6000}-{1 + uuid.uuid4().int % 12:02d}"


@pytest.fixture(autouse=True)
async def _purge_counter_rows() -> AsyncIterator[None]:
    """Remove the counter rows these cases wrote.

    `platform_speaking_rate` is NOT append-only — it is a counter — so an ordinary session
    may delete from it. Only the absurd months this file uses are removed; the real month
    the end-to-end case meters into is asserted by DELTA and deliberately left alone, since
    the calls behind it are real rows in the archive and the counter is supposed to hold
    them.
    """
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM platform_speaking_rate WHERE month ~ '^[3-8][0-9]{3}-'")
        )


async def _tenant() -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name="Loop Clinic",
        slug=f"ttsloop-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
        plan_tier="managed",
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    assert isinstance(tenant_id, UUID) and isinstance(agent_id, UUID)
    return tenant_id, agent_id


async def _call(
    tenant_id: UUID, agent_id: UUID, *, seconds: int, turns: Sequence[tuple[str, str]]
) -> UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, started_at, duration_s, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'inbound', '+919876500001', 'completed', now(), :d, now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "d": seconds,
            },
        )
        for idx, (speaker, body) in enumerate(turns):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, :idx, :s, :v, "
                    ":v, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "idx": idx,
                    "s": speaker,
                    "v": body,
                },
            )
    return call_id


# --- the floor is the function, and the constant is one point on it -------------------


def test_the_frozen_floor_is_this_function_at_the_assumed_basis() -> None:
    """ONE ARITHMETIC. If the constant were summed separately it could drift from the
    measured figure by rounding, and a screen showing both would be showing two models."""
    assert (
        sarvam_cost_floor_at(ASSUMED_SPEAKING_RATE).inr_per_min == SELF_SERVE_COST_FLOOR_INR_PER_MIN
    )
    assert cost_floor_inr_per_min("sarvam") == SELF_SERVE_COST_FLOOR_INR_PER_MIN
    assert ASSUMED_SPEAKING_RATE.chars_per_call_minute == TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]


def test_the_measured_floor_moves_by_exactly_the_tts_leg_and_nothing_else() -> None:
    """The speaking rate is the ONLY input that varies: the difference between two floors is
    the difference between their TTS legs, to the paise. A change anywhere else in the sum
    would show up here as a residue."""
    measured = SpeakingRateBasis(
        chars_per_call_minute=Decimal("400"),
        measured=True,
        calls=TTS_SPEAKING_RATE_MIN_CALLS,
        minimum_calls=TTS_SPEAKING_RATE_MIN_CALLS,
        window="2026-08..2026-09",
    )
    floor = sarvam_cost_floor_at(measured)
    assert floor.refusal_inr_per_min == SELF_SERVE_COST_FLOOR_INR_PER_MIN
    assert floor.inr_per_min == Decimal("3.7011")
    assert SELF_SERVE_COST_FLOOR_INR_PER_MIN - floor.inr_per_min == (
        tts_inr_per_call_minute(TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1])
        - tts_inr_per_call_minute(Decimal("400"))
    )
    # BELOW the frozen bound: the fleet talks less than the model assumes, so the card is
    # safe and the veto is merely conservative.
    assert floor.above_refusal is False


def test_a_fleet_that_talks_more_than_the_model_assumes_is_flagged_not_swallowed() -> None:
    """**THE EXPENSIVE DIRECTION**, and the one the whole feature exists to surface: Indic
    character density is exactly the risk TRD §10.1 names. The refusal stays frozen (D-556's
    settlement) and the console must say the real floor is above it."""
    talkative = SpeakingRateBasis(
        chars_per_call_minute=Decimal("700"),
        measured=True,
        calls=50,
        minimum_calls=TTS_SPEAKING_RATE_MIN_CALLS,
        window="2026-09",
    )
    floor = sarvam_cost_floor_at(talkative)
    assert floor.inr_per_min > floor.refusal_inr_per_min
    assert floor.above_refusal is True
    # And the veto itself has NOT moved: a card recordable this morning is recordable now.
    assert cost_floor_inr_per_min("sarvam") == SELF_SERVE_COST_FLOOR_INR_PER_MIN


# --- a figure below the bar may be shown and may not be called a measurement ----------


def test_the_type_refuses_to_hold_a_measurement_that_never_cleared_the_bar() -> None:
    """Hard rule 11 in a `__post_init__`. Four consumers cannot each remember the check, so
    the value object refuses the combination and there is nowhere else to build one."""
    with pytest.raises(ValueError, match="below the"):
        SpeakingRateBasis(
            chars_per_call_minute=Decimal("400"),
            measured=True,
            calls=TTS_SPEAKING_RATE_MIN_CALLS - 1,
            minimum_calls=TTS_SPEAKING_RATE_MIN_CALLS,
            window="2026-09",
        )
    with pytest.raises(ValueError, match="window"):
        SpeakingRateBasis(
            chars_per_call_minute=Decimal("400"),
            measured=True,
            calls=99,
            minimum_calls=20,
            window=None,
        )
    with pytest.raises(ValueError, match="window"):
        SpeakingRateBasis(
            chars_per_call_minute=Decimal("540"),
            measured=False,
            calls=0,
            minimum_calls=20,
            window="2026-09",
        )
    with pytest.raises(ValueError, match="must be positive"):
        SpeakingRateBasis(
            chars_per_call_minute=Decimal("0"),
            measured=False,
            calls=0,
            minimum_calls=0,
            window=None,
        )
    with pytest.raises(ValueError, match="cannot be negative"):
        assumed_speaking_rate(calls=-1)


def test_the_basis_says_what_it_is_in_one_line() -> None:
    """A screen never composes this from the fields, so two screens cannot compose it two
    ways. The bar-of-zero case is the module constant, struck before anything was counted —
    printing "0 of 0 calls" against it would read as a failed measurement."""
    assert ASSUMED_SPEAKING_RATE.label == (
        "assumed 540 chars/call-min (TRD 10.1, unmeasured - pilot gate 12)"
    )
    short = assumed_speaking_rate(calls=7, minimum_calls=20)
    assert short.label.endswith("; 7 of 20 calls measured")
    measured = SpeakingRateBasis(Decimal("412.5000"), True, 84, 20, "2026-07..2026-09")
    assert measured.label == "measured 412.5000 chars/call-min over 84 calls, 2026-07..2026-09"


# --- the counter -----------------------------------------------------------------------


async def test_the_counter_pools_three_totals_and_publishes_only_above_the_bar() -> None:
    """Sigma chars x 60 / Sigma seconds, exactly `summarize`'s pooled arithmetic — and the
    SAME twenty-call bar, applied to a reader that has no per-call samples to count."""
    month = _month()
    async with untenanted_session() as session:
        empty = await fleet_speaking_rate(session, months=[month])
        assert (empty.calls, empty.agent_chars, empty.call_seconds) == (0, 0, Decimal("0"))
        # A fleet that has spoken nothing has NO rate. Zero would price the TTS leg at
        # nothing, which is the direction that flatters us.
        assert empty.pooled_chars_per_minute is None
        assert empty.window is None
        assert empty.basis().measured is False

        for _ in range(TTS_SPEAKING_RATE_MIN_CALLS - 1):
            await bump_speaking_rate(
                session, month=month, agent_chars=300, call_seconds=Decimal("60")
            )
        short = await fleet_speaking_rate(session, months=[month])
    # 19 calls at 300 chars a minute: the rate is computable and MAY NOT be published.
    assert short.calls == TTS_SPEAKING_RATE_MIN_CALLS - 1
    assert short.pooled_chars_per_minute == Decimal("300")
    basis = short.basis()
    assert basis.measured is False
    assert basis.chars_per_call_minute == TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]
    assert (basis.calls, basis.minimum_calls) == (19, TTS_SPEAKING_RATE_MIN_CALLS)
    assert sarvam_cost_floor_at(basis).inr_per_min == SELF_SERVE_COST_FLOOR_INR_PER_MIN

    async with untenanted_session() as session:
        # The twentieth call, and a longer one, so the pooled figure is not the same number
        # arrived at trivially: 19 x 300 + 900 chars over 19 x 60 + 120 s.
        await bump_speaking_rate(session, month=month, agent_chars=900, call_seconds=Decimal("120"))
        full = await fleet_speaking_rate(session, months=[month])
    assert full.calls == TTS_SPEAKING_RATE_MIN_CALLS
    assert (full.agent_chars, full.call_seconds) == (6600, Decimal("1260"))
    # 6,600 x 60 / 1,260 = 314.285714...
    assert full.pooled_chars_per_minute == Decimal("6600") * 60 / Decimal("1260")
    published = full.basis()
    assert published.measured is True
    assert published.chars_per_call_minute == Decimal("314.2857")
    assert published.window == month
    # ...and the floor really moved, in the arithmetic the card is judged by.
    assert sarvam_cost_floor_at(published).inr_per_min < SELF_SERVE_COST_FLOOR_INR_PER_MIN


async def test_a_call_with_no_seconds_is_not_a_sample() -> None:
    """It contributes nothing to either total and would still raise the divisor of the
    publication threshold — the one way a counter can launder an absence into a rate. It is
    the walk's own predicate (`duration_s > 0`)."""
    month = _month()
    async with untenanted_session() as session:
        await bump_speaking_rate(session, month=month, agent_chars=500, call_seconds=Decimal("0"))
        assert (await fleet_speaking_rate(session, months=[month])).calls == 0
        # A call whose agent said nothing IS a sample: it really spoke no characters in real
        # seconds, and dropping it would bias the fleet rate upward.
        await bump_speaking_rate(session, month=month, agent_chars=0, call_seconds=Decimal("60"))
        held = await fleet_speaking_rate(session, months=[month])
    assert held.calls == 1 and held.call_seconds == Decimal("60")
    assert held.pooled_chars_per_minute is None


async def test_the_window_spans_the_months_the_counter_holds() -> None:
    first, last = sorted([_month(), _month()])
    async with untenanted_session() as session:
        await bump_speaking_rate(session, month=first, agent_chars=600, call_seconds=Decimal("60"))
        await bump_speaking_rate(session, month=last, agent_chars=600, call_seconds=Decimal("60"))
        both = await fleet_speaking_rate(session, months=[first, last])
        only = await fleet_speaking_rate(session, months=[first])
    assert both.window == f"{first}..{last}"
    assert both.calls == 2
    # The window scopes the read, which is what makes a trailing window one argument away.
    assert only.window == first and only.calls == 1


async def test_the_counter_and_the_walk_are_two_spellings_of_one_measurement() -> None:
    """**THE INVARIANT THAT MAKES THE COUNTER TRUSTWORTHY.** The board walks the client book
    for its percentiles; the cost model reads one row. Over the same calls the POOLED figure
    must be identical to the last place — if it is not, one of the two is wrong and every
    rupee struck at the second one is wrong with it."""
    month = _month()
    tenant_id, agent_id = await _tenant()
    seeded = [(300, 60), (901, 120), (0, 45), (1234, 97)]
    for chars, seconds in seeded:
        await _call(
            tenant_id,
            agent_id,
            seconds=seconds,
            # A caller turn on every call, to prove neither reader counts the human's
            # characters: they cost STT seconds, not TTS characters.
            turns=[("agent", "a" * chars), ("caller", "c" * 500)] if chars else [("caller", "c")],
        )
    async with tenant_session(tenant_id) as session:
        walked = summarize(await sample_tenant(session, tenant_id=tenant_id), minimum_calls=1)
    async with untenanted_session() as session:
        for chars, seconds in seeded:
            await bump_speaking_rate(
                session, month=month, agent_chars=chars, call_seconds=Decimal(seconds)
            )
        counted = await fleet_speaking_rate(session, months=[month])

    assert walked.pooled is not None
    assert counted.calls == walked.calls == len(seeded)
    assert counted.basis(minimum_calls=1).chars_per_call_minute == walked.pooled.chars_per_minute


async def test_the_post_call_meter_moves_the_counter_once_for_a_sarvam_call() -> None:
    """**THE SEAM, END TO END, ON THE VOICE THE STUDIO COUNTER IGNORES.** How fast an agent
    talks is a fact about the AGENT, and it is applied to the Clear floor — which is the
    Sarvam-voiced one. A meter that only counted the plan-billed voice would leave the
    biggest lever in the model measuring the smallest part of the fleet.

    DELTAS, NEVER ABSOLUTES: the counter is a shared platform row keyed by the real IST
    month, so an assertion on its total would pass on a leftover row from an earlier run and
    would have gone green with the increment deleted.
    """
    from apps.workers import pipeline
    from calevate_shared.engine import CostBreakdown, ExecutionSnapshot

    tenant_id, agent_id = await _tenant()
    agent_chars, caller_chars, seconds = 1500, 4000, 240
    call_id = await _call(
        tenant_id,
        agent_id,
        seconds=seconds,
        turns=[("agent", "x" * agent_chars), ("caller", "y" * caller_chars)],
    )
    ended = datetime.now(UTC)
    snapshot = ExecutionSnapshot(
        engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        duration_s=seconds,
        ended_at=ended,
        cost=CostBreakdown(
            total_inr=Decimal("6.0000"),
            platform_inr=Decimal("3.0000"),
            network_inr=Decimal("0.8000"),
            llm_inr=Decimal("0.0000"),
            tts_inr=Decimal("1.2000"),
            stt_inr=Decimal("1.0000"),
            source_currency="INR",
            source_amount=Decimal("6.0000"),
            fx_rate=Decimal("1"),
        ),
        engine="fake",
    )
    month = ist_billing_month(ended)
    async with untenanted_session() as session:
        before = await fleet_speaking_rate(session, months=[month])

    await pipeline._meter(tenant_id, call_id, snapshot)
    async with untenanted_session() as session:
        after = await fleet_speaking_rate(session, months=[month])
    # THE AGENT'S CHARACTERS AND THE CALL'S OWN SECONDS — two counts from two places. If
    # either were derived from the other at 540 chars a minute, these could not both hold:
    # 1,500 characters over four minutes is 375/min, nowhere near the assumption.
    assert after.calls - before.calls == 1
    assert after.agent_chars - before.agent_chars == agent_chars
    assert after.call_seconds - before.call_seconds == Decimal(seconds)

    # A REPLAY MOVES NOTHING: `_meter`'s own "already metered?" guard returns before the
    # bump, which is what makes a counter safe beside an append-only ledger.
    await pipeline._meter(tenant_id, call_id, snapshot)
    async with untenanted_session() as session:
        replay = await fleet_speaking_rate(session, months=[month])
    assert (replay.calls, replay.agent_chars) == (after.calls, after.agent_chars)


async def test_a_metered_call_with_no_transcript_does_not_enter_the_sample() -> None:
    """The other arm of the same guard, driven through the real meter. A call the engine
    never transcribed has no characters to contribute and must not raise the sample size
    that decides whether a figure may be published — that is how a counter launders an
    absence into a low speaking rate, and a low rate makes the floor cheaper than it is."""
    from apps.workers import pipeline
    from calevate_shared.engine import CostBreakdown, ExecutionSnapshot

    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id, seconds=120, turns=[])
    ended = datetime.now(UTC)
    snapshot = ExecutionSnapshot(
        engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        duration_s=120,
        ended_at=ended,
        cost=CostBreakdown(
            total_inr=Decimal("4.0000"),
            platform_inr=Decimal("2.0000"),
            network_inr=Decimal("0.5000"),
            llm_inr=None,
            tts_inr=None,
            stt_inr=Decimal("1.0000"),
            source_currency="INR",
            source_amount=Decimal("4.0000"),
            fx_rate=Decimal("1"),
        ),
        engine="fake",
    )
    month = ist_billing_month(ended)
    async with untenanted_session() as session:
        before = await fleet_speaking_rate(session, months=[month])
    await pipeline._meter(tenant_id, call_id, snapshot)
    async with untenanted_session() as session:
        after = await fleet_speaking_rate(session, months=[month])
    assert (after.calls, after.agent_chars, after.call_seconds) == (
        before.calls,
        before.agent_chars,
        before.call_seconds,
    )


# --- the consumers say which rate they used -------------------------------------------


def _measured_floor() -> object:
    return sarvam_cost_floor_at(
        SpeakingRateBasis(Decimal("400.0000"), True, 84, TTS_SPEAKING_RATE_MIN_CALLS, "2026-09")
    )


def test_the_rate_card_prices_the_clear_column_at_the_measured_rate() -> None:
    """**THE LOOP, CLOSED, ON THE SCREEN THE FOUNDER READS.** `_volume_cost` used to return
    the structural floor for Sarvam and call that the honest answer; a per-CHARACTER price
    becomes a per-CALL-MINUTE cost only through the speaking rate, so it now returns the
    floor at the fleet's measured rate — and the Studio column, which is measured from two
    counts of a real month, is untouched by the speaking rate entirely."""
    fx = UsdInrRate(rate=Decimal("88"), source="configured:usd_inr_rate", as_of=None)
    clear = _measured_floor()
    cells = config_routes._cells_out(
        PACK_CATALOGUE, measured_cost=Decimal("6.9011"), fx=fx, clear=clear
    )
    sarvam = [cell for cell in cells if cell.voice_tier == "sarvam"]
    assert sarvam, "the card has a Clear column"
    for cell in sarvam:
        # The MEASURED floor, not the frozen one — and they differ, which is the whole point.
        assert cell.cost_inr_per_min_at_volume == "3.7011"
        assert cell.cost_floor_inr_per_min == str(SELF_SERVE_COST_FLOOR_INR_PER_MIN)
        assert cell.cost_inr_per_min_at_volume != cell.cost_floor_inr_per_min
    # THE STUDIO COLUMN DOES NOT MOVE WITH THE SPEAKING RATE, deliberately: two independent
    # counts of a month somebody ran beat any speaking rate, and re-deriving it from one
    # would put the unmeasured band back inside the measurement built to replace it.
    assert all(
        cell.cost_inr_per_min_at_volume == "6.9011"
        for cell in cells
        if cell.voice_tier == "cartesia"
    )


def test_the_console_block_carries_the_basis_the_sample_and_the_window() -> None:
    """A margin from a measurement and a margin from an assumption are different claims. The
    wire says which, from how many calls, over which months — and publishes the frozen
    refusal beside the live figure, so an operator can see which number blocks a save."""
    published = config_routes._speaking_rate_out(_measured_floor())
    assert published.measured is True
    assert published.chars_per_call_minute == "400.0000"
    assert published.calls == 84
    assert published.minimum_calls == TTS_SPEAKING_RATE_MIN_CALLS
    assert published.window == "2026-09"
    assert "measured" in published.basis
    assert published.cost_floor_inr_per_min == "3.7011"
    assert published.refusal_floor_inr_per_min == str(SELF_SERVE_COST_FLOOR_INR_PER_MIN)
    assert published.floor_above_refusal is False

    unmeasured = config_routes._speaking_rate_out(sarvam_cost_floor_at(ASSUMED_SPEAKING_RATE))
    assert unmeasured.measured is False
    assert unmeasured.window is None
    # No placeholder rate, and no rate PRETENDING to be measured: the assumption still in
    # force is what is published, labelled as such.
    assert unmeasured.chars_per_call_minute == "540"
    assert unmeasured.cost_floor_inr_per_min == unmeasured.refusal_floor_inr_per_min


def test_the_spend_board_publishes_the_counter_beside_the_walk() -> None:
    """The board's own p50/p95 come from the walk; the block the COST MODEL uses comes from
    the counter, and both are on one response so a disagreement is visible."""
    from apps.api.billing.spend_routes import _fleet_speaking_rate_out

    out = _fleet_speaking_rate_out(
        FleetSpeakingRate(
            calls=84,
            agent_chars=336_000,
            call_seconds=Decimal("50400"),
            first_month="2026-07",
            last_month="2026-09",
        )
    )
    # 336,000 x 60 / 50,400 = 400 chars a call-minute exactly.
    assert out.measured is True
    assert out.chars_per_minute == "400.0000"
    assert out.window == "2026-07..2026-09"
    assert out.cost_floor_inr_per_min == "3.7011"
    assert out.refusal_floor_inr_per_min == str(SELF_SERVE_COST_FLOOR_INR_PER_MIN)
    assert out.floor_above_refusal is False

    short = _fleet_speaking_rate_out(
        FleetSpeakingRate(
            calls=3,
            agent_chars=1000,
            call_seconds=Decimal("180"),
            first_month="2026-09",
            last_month="2026-09",
        )
    )
    assert short.measured is False
    assert short.calls == 3 and short.minimum_calls == TTS_SPEAKING_RATE_MIN_CALLS
    assert short.cost_floor_inr_per_min == str(SELF_SERVE_COST_FLOOR_INR_PER_MIN)


def test_the_committed_plan_panel_names_the_frozen_basis_it_refuses_on() -> None:
    """The one consumer that deliberately does NOT move with the measurement, saying so. It
    is a refusal surface, and D-556's settlement is that a veto does not move under an
    operator — but it must still say which basis it vetoed on."""
    from apps.api.admin.routes import _margin_out
    from apps.api.billing.terms import CommercialTerms

    margin = _margin_out(
        CommercialTerms(monthly_fee=Decimal("10000"), included_min=1000, overage_rate=None)
    )
    assert margin.cost_floor_inr_per_min == str(SELF_SERVE_COST_FLOOR_INR_PER_MIN)
    assert margin.cost_floor_basis == ASSUMED_SPEAKING_RATE.label
    assert "unmeasured" in margin.cost_floor_basis
