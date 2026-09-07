"""THE DATED CARD: twelve `pack:*:*` rates at ONE instant, and the resolution rule (D-547).

`platform_list_rates` acquired a valid time for ONE number (D-492, `self_serve_inr_per_min`).
Under credit lots the thing that has to acquire one is the whole CARD, because Phase B
freezes a purchase's two rates onto its lot from the card in force at the moment the
purchase lands. What this file protects:

- **One `effective_from` for the whole card.** Twelve `record_list_rate` calls would stamp
  twelve `clock_timestamp()` values microseconds apart (the statement clock genuinely
  advances inside a transaction — `tests/self_serve_list_rate_test.py` asserts that it
  does), and a lot opened in that window would freeze a card that is half old and half new.
- **The same greatest-`effective_from`-≤-`at` rule** `self_serve_rate_at` uses, per key, so
  a card is resolved the way a rate is and there is no second mechanism.
- **The static catalogue is the fallback, per CELL**, never a backfill: nobody recorded a
  card before this landed, and asserting today's rates were in force in every past month is
  a claim nobody here can make (hard rule 11).
- **A key this build cannot interpret is skipped, not fatal.** The rows are append-only
  history; a card recorded by an older build can name a pack or a voice this one has
  forgotten, and a statement-rendering read must not die on it.
- **The legacy `self_serve_inr_per_min` row is written alongside**, at the same instant,
  because every reader of it is still live (plan §10's two-step).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.credit_packs import PACK_CATALOGUE, CreditPack
from apps.api.billing.list_rates import (
    PACK_RATE_KEY_PREFIX,
    SELF_SERVE_PER_MIN,
    card_at,
    pack_rate_key,
    record_card,
    self_serve_rate_at,
)
from apps.api.billing.rates import VOICE_TIERS
from apps.api.core.settings import Settings
from apps.api.db.session import untenanted_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

LEGACY_RATE = Decimal("5.0000")


async def _admin() -> UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def _purge() -> None:
    """Remove every row this suite wrote, as the OWNER — the only role that can, because
    the table is append-only ON PURPOSE (hard rule 4).

    `platform_list_rates` is GLOBAL, not tenant-scoped, so a row left behind changes what
    every other suite's `self_serve_rate_at` and `card_at` resolve — the contamination
    `tests/self_serve_list_rate_test.py` documents at length. `ENABLE TRIGGER` is not the
    inverse of `DISABLE` (plain ENABLE demotes an `ENABLE ALWAYS` trigger to ORIGIN), so
    each trigger's mode is read first and put back verbatim: the trap
    `platform_secrets_test` documents and two other suites already reuse.
    """
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: platform_list_rates is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            modes = (
                await conn.execute(
                    text(
                        "SELECT tgname, tgenabled FROM pg_trigger "
                        "WHERE tgrelid = 'platform_list_rates'::regclass AND NOT tgisinternal"
                    )
                )
            ).all()
            await conn.execute(text("ALTER TABLE platform_list_rates DISABLE TRIGGER USER"))
            await conn.execute(text("DELETE FROM platform_list_rates"))
            for name, mode in modes:
                verb = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA", "D": "DISABLE"}.get(
                    str(mode), "ENABLE"
                )
                await conn.execute(text(f'ALTER TABLE platform_list_rates {verb} TRIGGER "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _isolated_history() -> AsyncIterator[None]:
    await _purge()
    yield
    await _purge()


def test_a_card_key_round_trips_through_its_spelling() -> None:
    """`pack:<pack_id>:<voice>` — built by a function so the writer and the reader cannot
    come to disagree about the spelling, which two matching string literals would."""
    assert pack_rate_key("plus", "cartesia") == "pack:plus:cartesia"
    assert pack_rate_key("plus", "cartesia").startswith(f"{PACK_RATE_KEY_PREFIX}:")


async def test_a_card_write_lands_twelve_rates_and_the_legacy_key_at_one_instant() -> None:
    """THE CORE PROPERTY. Every cell of the card shares one `effective_from`, so a lot
    opened at any instant freezes a card that is entirely old or entirely new."""
    admin = await _admin()
    async with untenanted_session() as session:
        at = await record_card(
            session,
            self_serve_inr_per_min=LEGACY_RATE,
            recorded_by=admin,
            note="the founder's card",
        )
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT rate_key, effective_from, inr_amount FROM platform_list_rates")
            )
        ).all()
    assert len(rows) == len(PACK_CATALOGUE) * len(VOICE_TIERS) + 1
    assert {row[1] for row in rows} == {at}, "one card, one effective_from"
    published = {row[0]: Decimal(str(row[2])) for row in rows}
    assert published[SELF_SERVE_PER_MIN] == LEGACY_RATE
    for pack in PACK_CATALOGUE:
        for voice in VOICE_TIERS:
            assert published[pack_rate_key(pack.pack_id, voice)] == pack.inr_per_min(voice)


async def test_the_card_resolves_to_the_greatest_effective_from_at_or_before_the_instant() -> None:
    """The same rule `self_serve_rate_at` uses, applied per key. A card recorded later must
    not reach back and reprice a lot opened before it."""
    admin = await _admin()
    cheaper = tuple(
        CreditPack(
            pack_id=pack.pack_id,
            amount_inr=pack.amount_inr,
            sarvam_inr_per_min=pack.sarvam_inr_per_min - Decimal("0.25"),
            cartesia_inr_per_min=pack.cartesia_inr_per_min - Decimal("0.25"),
        )
        for pack in PACK_CATALOGUE
    )
    async with untenanted_session() as session:
        first = await record_card(
            session, self_serve_inr_per_min=LEGACY_RATE, recorded_by=admin, note="launch"
        )
    async with untenanted_session() as session:
        second = await record_card(
            session,
            card=cheaper,
            self_serve_inr_per_min=Decimal("4.7500"),
            recorded_by=admin,
            note="a price cut",
        )
    assert second > first

    async with untenanted_session() as session:
        before = await card_at(session, at=first + timedelta(microseconds=1))
        after = await card_at(session, at=second + timedelta(seconds=1))
    assert before["plus"]["sarvam"] == Decimal("4.70")
    assert after["plus"]["sarvam"] == Decimal("4.45")
    assert after["plus"]["cartesia"] == Decimal("6.25")


async def test_an_instant_before_any_card_falls_back_to_the_static_catalogue() -> None:
    """NOT A BACKFILL. No card was ever recorded before this landed, so seeding one at the
    beginning of time would assert that today's rates were in force in every past month.
    The catalogue is what this build sells and is the honest answer for an unrecorded
    instant — which is also why landing this re-prices nobody."""
    async with untenanted_session() as session:
        card = await card_at(session, at=datetime(2026, 1, 1, tzinfo=UTC))
    assert card == {
        pack.pack_id: {voice: pack.inr_per_min(voice) for voice in VOICE_TIERS}
        for pack in PACK_CATALOGUE
    }


async def test_the_fallback_is_per_cell_so_a_card_missing_a_pack_keeps_the_rest() -> None:
    """A card recorded before `plus` existed resolves the packs it recorded and answers the
    catalogue for the one it does not. Per CELL rather than per card, because the only other
    reading silently DROPS a pack from a rate card, and a dropped pack is a purchase nobody
    can price."""
    admin = await _admin()
    older = tuple(pack for pack in PACK_CATALOGUE if pack.pack_id != "plus")
    async with untenanted_session() as session:
        at = await record_card(
            session,
            card=older,
            self_serve_inr_per_min=LEGACY_RATE,
            recorded_by=admin,
            note="before the ₹15,000 rung existed",
        )
    async with untenanted_session() as session:
        card = await card_at(session, at=at + timedelta(seconds=1))
    assert set(card) == {pack.pack_id for pack in PACK_CATALOGUE}
    plus = next(pack for pack in PACK_CATALOGUE if pack.pack_id == "plus")
    assert card["plus"] == {voice: plus.inr_per_min(voice) for voice in VOICE_TIERS}


async def test_a_key_this_build_cannot_interpret_is_skipped_not_fatal() -> None:
    """Append-only history outlives a build. A row naming a retired pack or a voice tier we
    no longer carry is not a cell this build can resolve, and the honest answer is to skip
    it — never to fail the read that renders somebody's statement."""
    admin = await _admin()
    async with untenanted_session() as session:
        at = await record_card(
            session, self_serve_inr_per_min=LEGACY_RATE, recorded_by=admin, note="current"
        )
        for key in ("pack:retired-2024:sarvam", "pack:plus:elevenlabs", "pack:sarvam", "pack::x"):
            await session.execute(
                text(
                    "INSERT INTO platform_list_rates "
                    "(rate_key, effective_from, inr_amount, recorded_by, source_note) "
                    "VALUES (:k, clock_timestamp(), 1.0000, :by, 'from an older build')"
                ),
                {"k": key, "by": admin},
            )
    async with untenanted_session() as session:
        card = await card_at(session, at=at + timedelta(seconds=1))
    assert set(card) == {pack.pack_id for pack in PACK_CATALOGUE}
    assert card["plus"]["cartesia"] == Decimal("6.50")


async def test_a_card_is_resolved_at_an_aware_instant_only() -> None:
    """`self_serve_rate_at`'s rule, for the same reason: `effective_from` is `timestamptz`,
    and a naive instant would be read in the process's local timezone — a UTC container and
    an IST laptop would then resolve different cards for the same month."""
    async with untenanted_session() as session:
        with pytest.raises(ValueError, match="aware instant"):
            await card_at(session, at=datetime(2026, 2, 1))


async def test_the_legacy_rate_stays_readable_through_its_own_reader() -> None:
    """Plan §10: `self_serve_rate_at` is what `billing/service`, `billing/attribution` and
    `workers/pipeline` still price a closed month with. Writing a card must keep answering
    them, or landing this release breaks every one of them at once."""
    admin = await _admin()
    async with untenanted_session() as session:
        at = await record_card(
            session, self_serve_inr_per_min=Decimal("5.5000"), recorded_by=admin, note="x"
        )
    async with untenanted_session() as session:
        assert await self_serve_rate_at(session, at=at + timedelta(seconds=1)) == Decimal("5.5000")
