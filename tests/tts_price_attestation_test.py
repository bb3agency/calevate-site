"""The TTS price is an OPERATOR ATTESTATION, and a voice with none may not be metered.

D-547 / plan §3.5. Bolna's own pricing page says a BYOK component costs nothing from the
engine (plan ADDENDUM 3 §3.5), so the synthesizer figure the pipeline writes as
`unit_cost_paid` is ₹0 for a Cartesia call — and what Cartesia actually bills is a MONTHLY
PLAN with a character allotment, which no payload can report. The cost of a Cartesia
character is therefore a figure only a human holding the invoice can state, and hard rule
7 says a figure nobody read may not reach `unit_cost_paid`.

These tests pin the three properties that makes true: the price is effective-dated (so a
re-rendered month resolves the figure its minutes were metered at), it is append-only (a
correction is a new instant, never an edit), and `tts_price_is_billable` is the ONE door
that decides whether a voice tier may be offered at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_args

import pytest
from apps.api.agents.voices import VOICE_TIER_OF_PROVIDER, VoiceProvider
from apps.api.billing.lots import VoiceTier
from apps.api.core.errors import ProblemError
from apps.api.db.session import untenanted_session
from apps.api.ops.model_pricing import (
    TTS_PROVIDERS,
    attest_tts_price,
    attested_tts_prices,
    tts_price_is_billable,
)
from sqlalchemy import text


async def _operator() -> uuid.UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


def test_the_provider_vocabulary_is_the_voice_catalogues_and_the_ledgers() -> None:
    """TWO spellings of a vendor held equal, because they are two files apart and each one
    alone looks right: `agents/voices.VoiceProvider` (who synthesises) and `TTS_PROVIDERS`
    (whose price an operator may attest). A vendor added to one and not the other is a
    price attested under a name the pipeline never stamps — the leg then meters as free
    while the console shows it priced, which is the one failure nobody investigates.

    ⚠ **THIS WAS A THREE-WAY EQUALITY WITH `VoiceTier` UNTIL D-618, AND THE THIRD MEMBER
    HAD TO GO — NOT BE WIDENED.** A TIER is a price: a label, a cost floor, and two rates
    frozen on every credit lot. A PROVIDER is who synthesises. They were one Literal only
    while the two happened to spell the same.

    ⚠ **AND THE TWO VOCABULARIES ARE NOW DISJOINT (19 Sep 2026).** Two moves got them
    there. D-629 withdrew the Sarvam TEXT-TO-SPEECH leg, which left `sarvam` a TIER token
    naming no provider; D-630 then renamed the rungs to `clear` / `studio`, so no token is
    both a tier and a provider any more. (Sarvam remains the STT vendor; that leg has never
    been in either of these vocabularies.) What this clause pins is the relation that still
    has to hold across the two sets: every provider is attestable, and every provider bills
    on a rung that is a real tier.
    """
    assert set(TTS_PROVIDERS) == set(get_args(VoiceProvider))
    assert "sarvam" not in TTS_PROVIDERS, (
        "the Sarvam TTS leg is withdrawn; a price attested under that name would be "
        "attached to a provider the pipeline can no longer stamp"
    )
    assert set(VOICE_TIER_OF_PROVIDER) == set(get_args(VoiceProvider))
    assert {t for t in VOICE_TIER_OF_PROVIDER.values() if t is not None} <= set(get_args(VoiceTier))
    assert set(get_args(VoiceTier)) == {"clear", "studio"}, (
        "the tier tokens are money vocabulary frozen onto credit lots and their columns "
        "(`credit_lots.clear_inr_per_min` / `studio_inr_per_min`), so renaming one from "
        "here on restates terms somebody has bought — D-630 could rename them only because "
        "the table was empty, and its migration `f1c40d8b6e93` refuses against a table that "
        "is not"
    )
    assert not set(get_args(VoiceTier)) & set(get_args(VoiceProvider)), (
        "a token that is BOTH a rung and a provider is what let three screens look a rate "
        "up by provider among rows keyed by tier and resolve for the wrong reason (D-630); "
        "the two vocabularies must stay disjoint"
    )


async def test_an_attested_price_reads_back_at_its_own_instant() -> None:
    operator = await _operator()
    at = datetime.now(UTC)
    async with untenanted_session() as session:
        written = await attest_tts_price(
            session,
            provider="cartesia",
            inr_per_1k_chars=Decimal("3.4496"),
            effective_from=at,
            source_note="Cartesia Startup plan ₹4,312 / 1.25M chars, invoice of 1 Sep 2026",
            actor_id=operator,
        )
        prices = await attested_tts_prices(session, at=at)
    assert written.inr_per_1k_chars == Decimal("3.4496")
    assert prices["cartesia"].inr_per_1k_chars == Decimal("3.4496")
    # THE MULTIPLICATION, in one place: 1,000 characters cost exactly the attested rate.
    assert prices["cartesia"].inr_for_chars(Decimal("1000")) == Decimal("3.4496")
    assert prices["cartesia"].inr_for_chars(Decimal("500")) == Decimal("1.7248")


async def test_a_price_is_invisible_before_the_instant_it_becomes_effective() -> None:
    """The property a re-rendered invoice depends on: last month resolves last month's
    figure, not the correction somebody typed today."""
    operator = await _operator()
    later = datetime.now(UTC) + timedelta(days=30)
    async with untenanted_session() as session:
        await attest_tts_price(
            session,
            provider="cartesia",
            inr_per_1k_chars=Decimal("2.0000"),
            effective_from=later,
            source_note="the plan we move to next month",
            actor_id=operator,
        )
        before = await attested_tts_prices(session, at=later - timedelta(days=1))
        after = await attested_tts_prices(session, at=later)
    assert "cartesia" not in before or before["cartesia"].inr_per_1k_chars != Decimal("2.0000")
    assert after["cartesia"].inr_per_1k_chars == Decimal("2.0000")


async def test_a_second_attestation_at_the_same_instant_is_refused_by_name() -> None:
    """A correction is a NEW effective instant. Colliding on one is the single write an
    append-only table cannot express, and it must read as a sentence rather than a 500."""
    operator = await _operator()
    at = datetime.now(UTC)
    async with untenanted_session() as session:
        await attest_tts_price(
            session,
            provider="cartesia",
            inr_per_1k_chars=Decimal("3.4496"),
            effective_from=at,
            source_note="Startup plan",
            actor_id=operator,
        )
        with pytest.raises(ProblemError) as raised:
            await attest_tts_price(
                session,
                provider="cartesia",
                inr_per_1k_chars=Decimal("3.9000"),
                effective_from=at,
                source_note="a typo being fixed in place",
                actor_id=operator,
            )
    assert raised.value.code == "tts_price_duplicate_instant"


async def test_a_zero_price_is_refused() -> None:
    """An attested ₹0 meters every character on this voice at nothing while looking like a
    working leg — the one metering failure nobody investigates."""
    operator = await _operator()
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await attest_tts_price(
                session,
                provider="cartesia",
                inr_per_1k_chars=Decimal("0"),
                effective_from=datetime.now(UTC),
                source_note="it is included in the plan",
                actor_id=operator,
            )
    assert raised.value.code == "tts_price_not_positive"


async def test_a_provider_outside_the_catalogue_cannot_be_priced() -> None:
    operator = await _operator()
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await attest_tts_price(
                session,
                provider="elevenlabs",
                inr_per_1k_chars=Decimal("1.00"),
                effective_from=datetime.now(UTC),
                source_note="a vendor we do not synthesise with",
                actor_id=operator,
            )
    assert raised.value.code == "tts_price_unknown_provider"


async def test_no_leg_is_billable_without_an_attestation_any_more() -> None:
    """⚠ **SARVAM USED TO BE, AND IT WAS A MEASUREMENT RATHER THAN AN EXEMPTION.** The
    ENGINE billed us for the Sarvam synthesizer leg and reported what it charged, so that
    leg carried a measured cost on every row and had no attestation to make. The founder
    withdrew that leg on 18 Sep 2026; both survivors are BYOK — the engine charges nothing
    and reports ₹0 — so neither has any cost at all without an operator's figure, and
    `sarvam` is not even a provider this store accepts a price under.

    That is the whole of hard rule 7 on this leg, with the exemption gone rather than
    widened."""
    async with untenanted_session() as session:
        for provider in TTS_PROVIDERS:
            assert not await tts_price_is_billable(
                session,
                provider=provider,
                # An instant before this repository existed: whatever a live deployment has
                # attested since, nobody had read an invoice then.
                at=datetime(2024, 1, 1, tzinfo=UTC),
            ), provider
        with pytest.raises(ProblemError, match="tts_price_unknown_provider"):
            await tts_price_is_billable(session, provider="sarvam", at=datetime.now(UTC))


async def test_cartesia_is_not_billable_before_anyone_has_read_an_invoice() -> None:
    """Hard rule 7 with no REPORTED tier: at an instant before any attestation exists there
    is no figure, so the tier is not billable and `offerable_voices` refuses it by name
    rather than offering a voice whose minutes would meter as free."""
    async with untenanted_session() as session:
        assert not await tts_price_is_billable(
            session,
            provider="cartesia",
            # An instant before this repository existed: whatever a live deployment has
            # attested since, nobody had read an invoice then.
            at=datetime(2024, 1, 1, tzinfo=UTC),
        )


async def test_a_naive_instant_is_refused_rather_than_guessed_at() -> None:
    """A month is a fact about a timezone (IST at the edge), and a naive instant has none."""
    async with untenanted_session() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            await attested_tts_prices(session, at=datetime(2026, 9, 1))
