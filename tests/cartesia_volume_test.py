"""**THE OPS CONSOLE MUST NOT PRINT A BEST CASE UNDER A COLUMN HEADED "COSTS US".**

THE DEFECT THESE TESTS EXIST FOR (founder, 9 Sep 2026). The platform-configuration screen
rendered ₹4.3639 for every Studio rung in a column headed "COSTS US". That figure was the $49
Startup plan fee spread over the ~2,315 Cartesia call-minutes a month at which its allotment
is exactly consumed — the cheapest a Cartesia minute can EVER be, at a volume this platform
has never run — with no volume assumption anywhere on the screen. The arithmetic was right
and the screen was lying.

What is pinned here is the SEAM rather than the arithmetic (`tests/cost_floor_test.py` owns
that): that the platform-wide volume can be read at all under FORCEd RLS, that it is two
independent counts rather than one figure times an assumed speaking rate, and that the wire
carries the volume, the FX provenance and a per-rung break-even beside every cost — so a
future edit that quietly drops the caveat fails here rather than on a founder's screen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.rates import CARTESIA_EVIDENCE_USD_INR, CARTESIA_VOLUME_LADDER_CALL_MINUTES
from apps.api.billing.spend_routes import _CHARS_PER_KCHAR
from apps.api.billing.tts_volume import (
    CHARS_PER_KCHAR,
    PLAN_BILLED_VOICE,
    CartesiaVolume,
    bump_cartesia_volume,
    fleet_cartesia_volume,
)
from apps.api.core.fx import UsdInrRate
from apps.api.db.session import untenanted_session
from apps.api.ops import config_routes
from sqlalchemy import text


def _month() -> str:
    """A billing month of this case's own, from a range no real row can be in.

    The counter is a SHARED platform row keyed by month, so two cases writing the same month
    would add each other's characters — a flake that reads as a metering defect. The range
    is deliberately absurd (six thousand years wide, starting a millennium out) so two cases
    in one run, two runs, or two lanes against one database cannot collide.
    """
    return f"{3000 + uuid.uuid4().int % 6000}-{1 + uuid.uuid4().int % 12:02d}"


@pytest.fixture(autouse=True)
async def _purge_counter_rows() -> AsyncIterator[None]:
    """Remove the counter rows these cases wrote.

    `platform_tts_volume` is NOT append-only — it is a counter, which is why an ordinary
    session may delete from it and no owner-role trigger dance is needed. The months are
    unique per case, so this only ever removes rows this file created.
    """
    yield
    async with untenanted_session() as session:
        # The absurd months the pure cases use, AND the real month the end-to-end case
        # meters into: nothing else in this repository writes this counter (the Cartesia
        # voice catalogue is empty, so no other test can produce a Studio call), so leaving
        # its row behind would make a later run of THIS file start from a non-zero total.
        # The assertions below are deltas and would survive that; the row is still removed,
        # because a counter left holding a test's minutes is a fleet cost figure nobody
        # wrote.
        await session.execute(
            text(
                "DELETE FROM platform_tts_volume WHERE month ~ '^[3-8][0-9]{3}-' OR provider = :p"
            ),
            {"p": PLAN_BILLED_VOICE},
        )


async def test_the_counter_is_the_fleet_total_and_is_readable_from_any_session() -> None:
    """**THE READ THE OLD SCREEN COULD NOT DO.**

    The Cartesia allotment is bought once for the whole deployment, so the volume that
    prices it is the sum over every client. `usage_events` is FORCE RLS'd and
    `admin_session` widens the policy on `organizations` ALONE, so that sum is unaskable in
    app code — which is why this is a counter with no `tenant_id` and no policy, and why it
    answers the same on any session. `billing/ai_quota.read_platform_ai_spend` is in the
    same corner for the same reason.
    """
    month = _month()
    async with untenanted_session() as session:
        empty = await fleet_cartesia_volume(session, month=month)
        # A month with no row is ZERO and not an error: nothing has been spoken yet.
        assert empty.characters == Decimal("0")
        assert empty.call_minutes == Decimal("0")

        await bump_cartesia_volume(
            session, month=month, characters=Decimal("60000"), call_minutes=Decimal("120")
        )
        await bump_cartesia_volume(
            session, month=month, characters=Decimal("48000"), call_minutes=Decimal("80")
        )

    async with untenanted_session() as session:
        total = await fleet_cartesia_volume(session, month=month)
    # TWO CALLS, ONE ROW, SUMMED — the `ON CONFLICT DO UPDATE` is what makes the counter a
    # total rather than a last-writer-wins.
    assert total.characters == Decimal("108000")
    assert total.call_minutes == Decimal("200")
    assert total.month == month


async def test_a_call_that_spoke_nothing_creates_no_month_row() -> None:
    """A Sarvam call, or a Cartesia call that synthesized nothing, must not put a row in the
    counter: a month row saying zero and a month with no row are the same number, but the
    first asserts a Studio call happened when none did."""
    month = _month()
    async with untenanted_session() as session:
        await bump_cartesia_volume(
            session, month=month, characters=Decimal("0"), call_minutes=Decimal("0")
        )
        rows = (
            await session.execute(
                text("SELECT count(*) FROM platform_tts_volume WHERE month = :m"), {"m": month}
            )
        ).scalar_one()
    assert rows == 0


async def test_the_counter_refuses_to_go_backwards() -> None:
    """A volume that can fall is a cost figure that can be talked down by a bug, in the
    direction that flatters us — the reasoning `ck_platform_ai_spend_non_negative` carries,
    here as a CHECK constraint and as a clamp in the writer."""
    month = _month()
    async with untenanted_session() as session:
        await bump_cartesia_volume(
            session, month=month, characters=Decimal("-500"), call_minutes=Decimal("10")
        )
        total = await fleet_cartesia_volume(session, month=month)
    assert total.characters == Decimal("0")
    assert total.call_minutes == Decimal("10")


def test_the_two_readers_of_a_kchars_row_agree_about_the_quantum() -> None:
    """`billing/tts_volume` and `billing/spend_routes` both multiply `qty` back to characters.
    Two spellings of one quantum is where a fleet cost figure and a spend board come to
    disagree about a month by a factor of a thousand."""
    assert CHARS_PER_KCHAR == _CHARS_PER_KCHAR == Decimal("1000")


def test_the_counter_tracks_the_voice_the_rate_card_prices() -> None:
    """One vendor, named once. A `usage_events` row carries no vendor, so a second
    plan-billed voice is a migration and not an edit to a constant — the same bound
    `ops/model_pricing.PLAN_BILLED_TTS_PROVIDERS` is pinned at."""
    assert PLAN_BILLED_VOICE == "cartesia"


def test_the_wire_carries_the_volume_the_fx_and_a_breakeven_for_every_studio_rung() -> None:
    """**THE CAVEAT IS ON THE WIRE, NOT IN A COMMENT.** If a later edit drops the volume
    block, the FX provenance or the per-rung break-even, this fails — which is the whole
    point of pinning a screen's honesty in a test rather than trusting a reviewer to notice
    a missing column.
    """
    fx = UsdInrRate(rate=CARTESIA_EVIDENCE_USD_INR, source="frankfurter:FBIL", as_of=None)
    cells = config_routes._cells_out(PACK_CATALOGUE, measured_cost=Decimal("6.9011"), fx=fx)
    studio = [cell for cell in cells if cell.voice_tier == "cartesia"]
    assert len(studio) == len(PACK_CATALOGUE)
    for cell in studio:
        assert cell.breakeven_call_minutes is not None, cell.pack_id
        assert cell.cost_inr_per_min_at_volume == "6.9011"
    # At ₹6.9011 a minute — 100 platform call-minutes a month — the four cheapest Studio
    # rungs are UNDER WATER, and the console has to say so. Under the retired ₹4.3639
    # "floor" every one of them read as comfortably profitable.
    assert sorted(cell.pack_id for cell in studio if cell.below_floor_at_volume) == [
        "max",
        "plus",
        "pro",
        "scale",
    ]
    # ...while the STRUCTURAL verdict on the same cells refuses nothing, which is why the
    # card is still recordable and the at-volume figure is a warning (D-556).
    assert not any(cell.below_floor for cell in studio)

    # Sarvam is priced per character in rupees: its at-volume cost is its floor, the same
    # number twice, and it has no break-even because its cost does not move with volume.
    clear = [cell for cell in cells if cell.voice_tier == "sarvam"]
    assert all(cell.breakeven_call_minutes is None for cell in clear)
    assert all(cell.cost_inr_per_min_at_volume == cell.cost_floor_inr_per_min for cell in clear)


def test_the_volume_block_names_its_fx_rate_and_its_fallback() -> None:
    """A floor quietly struck at an operator's typed number is the same "best case presented
    as fact" defect one layer down, so WHICH rate and how old it is are on the wire.
    `fx_as_of` is `null` exactly when the configured fallback was used — a typed number has
    no publication date, and inventing today's would make a stale fallback look fresh."""
    volume = CartesiaVolume(
        month="2026-09", characters=Decimal("108000"), call_minutes=Decimal("200")
    )
    published = config_routes._cartesia_volume_out(
        volume,
        fx=UsdInrRate(
            rate=Decimal("95.66"), source="frankfurter:FBIL", as_of=datetime.now(UTC).date()
        ),
    )
    assert published.fx_usd_inr == "95.66"
    assert published.fx_source == "frankfurter:FBIL"
    assert published.fx_as_of is not None
    # The LIVE floor at ₹95.66 is above the founder's cheapest Studio rung, and the FROZEN
    # bound the write path refuses on is not — the two are published separately for exactly
    # this reason (D-556).
    assert published.floor_inr_per_min == "6.0120"
    assert published.refusal_floor_inr_per_min == "5.5899"
    assert Decimal(published.floor_inr_per_min) > min(
        pack.cartesia_inr_per_min for pack in PACK_CATALOGUE
    )
    assert Decimal(published.refusal_floor_inr_per_min) < min(
        pack.cartesia_inr_per_min for pack in PACK_CATALOGUE
    )

    fallback = config_routes._cartesia_volume_out(
        volume,
        fx=UsdInrRate(rate=Decimal("88"), source="configured:usd_inr_rate", as_of=None),
    )
    assert fallback.fx_as_of is None
    assert fallback.fx_source == "configured:usd_inr_rate"
    assert fallback.floor_inr_per_min == "5.5899"

    # The ladder is the curve, at the volumes the console prints, and it always contains a
    # point at which some Studio rung is under water.
    assert [point.call_minutes for point in fallback.ladder] == [
        str(minutes) for minutes in CARTESIA_VOLUME_LADDER_CALL_MINUTES
    ]
    assert fallback.ladder[0].cost_inr_per_min == "6.9011"
    assert fallback.cost_inr_per_min == "4.9299"
    assert fallback.plan_id == "pro"


def test_a_month_with_no_studio_minutes_states_the_absence_rather_than_a_zero() -> None:
    """ "Nobody spoke a Studio minute" and "a minute costs ₹0" are different facts and only
    one of them is true. The subscription is still owed, which is what the plan fee beside it
    says — a zero here would read as "this voice is free"."""
    published = config_routes._cartesia_volume_out(
        CartesiaVolume(month="2026-09", characters=Decimal("0"), call_minutes=Decimal("0")),
        fx=UsdInrRate(rate=Decimal("88"), source="configured:usd_inr_rate", as_of=None),
    )
    assert published.cost_inr_per_min is None
    assert published.plan_id is None
    assert published.measured_call_minutes == "0"


async def test_the_post_call_meter_moves_the_counter_exactly_once_for_a_studio_call() -> None:
    """**THE SEAM, END TO END.** A counter nobody increments reads zero for ever, and zero on
    this screen means "nobody spoke a Studio minute" — the flattering misreading the whole
    change exists to remove. So this drives the real `_meter` and asserts the row moved.

    THE TWO COUNTS COME FROM DIFFERENT PLACES AND THAT IS ASSERTED, not assumed: the
    characters are the ones `_tts_cost_rows` counted off the TRANSCRIPT (via the `tts_kchars`
    row it wrote), and the minutes are the call's own billed duration. If a later edit
    derived one from the other at 540 chars a minute, the two assertions below could not
    both hold.

    `voice_tier` is patched because the Cartesia voice CATALOGUE is empty — the Telugu voice
    ids are behind a login (OPERATIONS §2, blocked outside this repository), so no id in this
    build derives to `cartesia` and a Studio call cannot otherwise be constructed. The patch
    is on the ONE derivation (`agents/voices.voice_tier`, plan §2.3 invariant 7), which is
    exactly the seam a real Cartesia agent would come through.
    """
    from apps.api.admin import service as admin_service
    from apps.api.billing.plans import ist_billing_month
    from apps.api.db.base import uuid7
    from apps.api.db.session import tenant_session
    from apps.api.ops.model_pricing import attest_tts_price
    from apps.workers import pipeline
    from calevate_shared.engine import CostBreakdown, ExecutionSnapshot

    created = await admin_service.create_organization(
        name="Studio Clinic",
        slug=f"cartvol-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
    call_id = uuid7()
    agent_chars = 4000
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500001', 'completed', now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": created["agent_id"],
                "e": f"exec_{uuid.uuid4().hex[:12]}",
            },
        )
        # Only the AGENT's characters are synthesized; the caller's are not ours to pay for.
        for idx, (speaker, body) in enumerate(
            [("agent", "x" * agent_chars), ("caller", "y" * 9000)]
        ):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, "
                    "text, text_redacted, created_at) VALUES (:i, :t, :c, :x, :s, :v, :v, "
                    "now())"
                ),
                {"i": uuid7(), "t": tenant_id, "c": call_id, "x": idx, "s": speaker, "v": body},
            )

    operator = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": operator},
        )
        # The pipeline writes NO cost row it cannot price, so the leg needs an attestation
        # before a `tts_kchars` row exists to count characters off.
        #
        # THE INSTANT IS UNIQUE PER RUN, and that is not decoration: `platform_tts_prices`
        # is APPEND-ONLY, so a fixed `effective_from` is refused as a duplicate the SECOND
        # time this file runs against a development database — a failure that reads as a
        # metering defect and is contamination. `tests/tts_plan_fee_test._unique_month`
        # carries the same trap for the same table's twin. Backdated a year so it is in
        # force for a call ending now, whichever run wrote it.
        await attest_tts_price(
            session,
            provider="cartesia",
            inr_per_1k_chars=Decimal("5.7200"),
            effective_from=datetime.now(UTC).replace(year=datetime.now(UTC).year - 1)
            + timedelta(microseconds=uuid.uuid4().int % 1_000_000),
            actor_id=operator,
            source_note="test",
        )

    ended = datetime.now(UTC)
    snapshot = ExecutionSnapshot(
        engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        duration_s=180,
        ended_at=ended,
        cost=CostBreakdown(
            total_inr=Decimal("6.0000"),
            platform_inr=Decimal("3.0000"),
            network_inr=Decimal("0.8000"),
            llm_inr=Decimal("0.0000"),
            tts_inr=Decimal("0.0000"),
            stt_inr=Decimal("1.0000"),
            source_currency="INR",
            source_amount=Decimal("6.0000"),
            fx_rate=Decimal("1"),
        ),
        engine="fake",
    )
    month = ist_billing_month(ended)

    async with untenanted_session() as session:
        before = await fleet_cartesia_volume(session, month=month)

    original = pipeline.voice_tier
    pipeline.voice_tier = lambda _voice_id: "cartesia"  # type: ignore[assignment]
    try:
        await pipeline._meter(tenant_id, call_id, snapshot)
        async with untenanted_session() as session:
            after_one = await fleet_cartesia_volume(session, month=month)
        # DELTAS, NEVER ABSOLUTES. The counter is a SHARED platform row keyed by the real
        # IST month, so an assertion on its total passes on a leftover row from an earlier
        # run and would have gone green with the increment deleted — measured, on the first
        # draft of this test.
        assert after_one.characters - before.characters == Decimal(agent_chars)
        # THE MINUTES ARE THE CALL'S OWN BILLED DURATION — 180 seconds is 3 minutes, and
        # 4,000 characters over 3 minutes is nowhere near the 540/min the model assumes, so
        # neither figure can have been derived from the other.
        assert after_one.call_minutes - before.call_minutes == Decimal("3")

        # A REPLAY MOVES NOTHING. `_meter`'s own "already metered?" guard returns before the
        # bump, which is what makes a counter safe to keep beside an append-only ledger: the
        # ledger's uniqueness is the counter's exactly-once.
        await pipeline._meter(tenant_id, call_id, snapshot)
        async with untenanted_session() as session:
            after_replay = await fleet_cartesia_volume(session, month=month)
        assert after_replay.characters == after_one.characters
        assert after_replay.call_minutes == after_one.call_minutes
    finally:
        pipeline.voice_tier = original  # type: ignore[assignment]


async def test_a_sarvam_call_does_not_move_the_studio_counter() -> None:
    """The counter prices the CARTESIA subscription. A Sarvam minute in it would inflate the
    denominator and make every Studio rung look cheaper than it is — the same direction as
    the defect this whole change fixes."""
    from apps.api.billing.tts_volume import bump_cartesia_volume as _bump

    # The writer is only reached under `voice == PLAN_BILLED_VOICE` in `workers/pipeline`,
    # and the guard is asserted here as the one-line fact it is: there is no second voice
    # this function will accept, because it takes no voice at all.
    assert "voice" not in _bump.__annotations__
    month = _month()
    async with untenanted_session() as session:
        before = await fleet_cartesia_volume(session, month=month)
    assert before.characters == Decimal("0")
    assert before.call_minutes == Decimal("0")
