"""TELLING CLIENTS BEFORE THE PRICE MOVES: the fan-out, the exclusion and the wording (D-550).

A rate card is dated thirty days out, and every client whose top-ups it would price is told
when it is RECORDED. What this file protects:

* **The sentence that stops the support call.** "Credit you have already bought is NOT
  affected" is not reassurance — it is how `credit_lots` works, and it is the first thing a
  client wants to know after "your rates are changing". A body without it is a body that
  generates a ticket per client.
* **No rupee figure is a literal.** Every rate in the mail is read back from the card being
  announced, so an email cannot quote a price the platform will not charge.
* **Managed clients are excluded.** Their rates are negotiated in their `plans` row; the
  card does not price them, so telling them their prices are changing would be false.
* **The fan-out is idempotent.** One promise per (date, client), decided by a unique index
  rather than by the job remembering how far it got.
* **No vendor name reaches a client.** They read "Clear" and "Studio".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.credit_packs import PACK_CATALOGUE
from apps.api.billing.list_rates import record_card
from apps.api.billing.rates import VOICE_TIERS, voice_tier_label
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import rate_card_notice
from apps.workers.rate_card_notice import (
    NOTICE_JOB,
    PackRates,
    _aware,
    _retry_after,
    _starts_on,
    compose,
    fan_out_rate_card_notice,
    notify_rate_card_change,
    pack_rates,
)
from arq import Retry
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.conftest import purge_platform_list_rates

CARD_AT = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _isolated_history() -> AsyncIterator[None]:
    await purge_platform_list_rates()
    yield
    await purge_platform_list_rates()


class _Recorder:
    """A transport that remembers what it was handed and whether it agreed to send."""

    def __init__(self, *, delivered: bool = True) -> None:
        self.delivered = delivered
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return self.delivered


async def _tenant(
    plan_tier: str = "self_serve", *, billing_email: str | None = "o@example.test"
) -> UUID:
    created = await admin_service.create_organization(
        name="Rate Card Clinic",
        slug=f"rc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=billing_email,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :i"),
            {"tier": plan_tier, "i": tenant_id},
        )
    return tenant_id


async def _record_a_card(*, rise: str = "0.50") -> None:
    admin = await _make_admin()
    actor = UUID(admin.rsplit(":", 1)[1])
    from apps.api.billing.list_rates import card_list_rate, card_with_rates

    card = card_with_rates(
        {
            pack.pack_id: {voice: pack.inr_per_min(voice) + Decimal(rise) for voice in VOICE_TIERS}
            for pack in PACK_CATALOGUE
        }
    )
    async with untenanted_session() as session:
        await record_card(
            session,
            card=card,
            effective_from=CARD_AT,
            self_serve_inr_per_min=card_list_rate(card),
            recorded_by=actor,
            note="scheduled",
        )


def _payload(tenant_id: UUID) -> dict[str, Any]:
    return {"tenant_id": str(tenant_id), "effective_from": CARD_AT.isoformat()}


# ── the wording ──────────────────────────────────────────────────────────────────────


def test_the_rungs_carry_the_cards_rates_and_the_clients_word_for_each_voice() -> None:
    """`pack_rates` is where a card becomes something a client reads. The AMOUNT is the
    catalogue's (a card dates ₹/min cells and nothing else); the RATES are the card's; the
    voice NAMES are `rates.voice_tier_label`, never a vendor's."""
    cells = {
        pack.pack_id: {voice: pack.inr_per_min(voice) + Decimal("1") for voice in VOICE_TIERS}
        for pack in PACK_CATALOGUE
    }
    rungs = pack_rates(cells)
    assert [rung.amount_inr for rung in rungs] == sorted(pack.amount_inr for pack in PACK_CATALOGUE)
    labels = {label for rung in rungs for label, _ in rung.rates}
    assert labels == {voice_tier_label(voice) for voice in VOICE_TIERS}
    cheapest = min(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)
    assert rungs[0].rates[0][1] == cheapest.inr_per_min(VOICE_TIERS[0]) + Decimal("1")


def test_the_body_says_the_date_the_rates_and_that_bought_credit_is_untouched() -> None:
    """THE THREE THINGS THE MAIL EXISTS FOR, and the third is the one that stops a ticket."""
    rungs = pack_rates(
        {
            pack.pack_id: {voice: pack.inr_per_min(voice) for voice in VOICE_TIERS}
            for pack in PACK_CATALOGUE
        }
    )
    body = compose(starts_on="1 December 2026", rungs=rungs, slug="clinic")
    assert "1 December 2026" in body
    assert "already bought is NOT affected" in body
    assert "keeps the rates it was bought at" in body
    for rung in rungs:
        for label, rate in rung.rates:
            assert f"/min on {label}" in body
            assert str(rate.quantize(Decimal("0.01"))) in body
    assert "/c/clinic/credits" in body


def test_the_body_names_no_vendor_and_no_internal_vocabulary() -> None:
    """A client reads about voice QUALITY, never about who speaks it, and never about our
    own machinery — the same rule `wallet_alerts.compose` holds."""
    rungs = pack_rates(
        {
            pack.pack_id: {voice: pack.inr_per_min(voice) for voice in VOICE_TIERS}
            for pack in PACK_CATALOGUE
        }
    )
    body = compose(starts_on="1 December 2026", rungs=rungs, slug="clinic").lower()
    for forbidden in ("sarvam", "cartesia", "lot", "tier", "pack_id", "self_serve", "ledger"):
        assert forbidden not in body


def test_the_date_a_client_reads_is_ist() -> None:
    """UTC in the DB, IST at the edge — and an email is an edge. Midnight UTC on 1 December
    is already the 1st in India by five and a half hours; an instant late on the 30th is
    not."""
    assert _starts_on(datetime(2026, 11, 30, 20, 0, tzinfo=UTC)) == "1 December 2026"
    assert _starts_on(datetime(2026, 11, 30, 12, 0, tzinfo=UTC)) == "30 November 2026"


def test_a_notice_payload_without_an_offset_is_refused() -> None:
    with pytest.raises(ValueError, match="aware instant"):
        _aware("2026-12-01T00:00:00")
    assert _aware(CARD_AT.isoformat()) == CARD_AT


def test_the_retry_ladder_never_indexes_past_its_own_end() -> None:
    assert _retry_after(1) == rate_card_notice.RETRY_BACKOFF_S[0]
    assert _retry_after(0) == rate_card_notice.RETRY_BACKOFF_S[0]
    assert _retry_after(99) == rate_card_notice.RETRY_BACKOFF_S[-1]


# ── the fan-out ──────────────────────────────────────────────────────────────────────


async def _promises(tenant_id: UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT dedupe_key FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :t"
                ),
                {"job": NOTICE_JOB, "t": str(tenant_id)},
            )
        ).all()
    return [str(row[0]) for row in rows]


async def test_the_fan_out_promises_one_notice_per_prepaid_client() -> None:
    prepaid = await _tenant("self_serve")
    result = await fan_out_rate_card_notice({}, {"effective_from": CARD_AT.isoformat()})
    assert result.startswith("enqueued:")
    assert await _promises(prepaid) == [f"rate-card-notice:{CARD_AT.isoformat()}:{prepaid}"]


async def test_the_fan_out_skips_a_managed_client_whose_rates_are_negotiated() -> None:
    """The card does not price an invoiced account, so a notice about it would be false.
    The line comes from `PREPAID_TIERS`, the same constant the dial gate draws it with."""
    managed = await _tenant("managed")
    await fan_out_rate_card_notice({}, {"effective_from": CARD_AT.isoformat()})
    assert await _promises(managed) == []


async def test_running_the_fan_out_twice_promises_nothing_a_second_time() -> None:
    """At-least-once delivery meets a unique index: a parent retried after enqueuing half
    the book converges on exactly one notice each."""
    prepaid = await _tenant("self_serve")
    await fan_out_rate_card_notice({}, {"effective_from": CARD_AT.isoformat()})
    second = await fan_out_rate_card_notice({}, {"effective_from": CARD_AT.isoformat()})
    assert second == "enqueued:0"
    assert len(await _promises(prepaid)) == 1


async def test_the_fan_out_refuses_a_malformed_date_before_enqueuing_anything() -> None:
    """A payload whose date is naive must fail on the PARENT rather than on every one of
    its children, an hour of retries later."""
    prepaid = await _tenant("self_serve")
    with pytest.raises(ValueError, match="aware instant"):
        await fan_out_rate_card_notice({}, {"effective_from": "2026-12-01T00:00:00"})
    assert await _promises(prepaid) == []


# ── the send ─────────────────────────────────────────────────────────────────────────


async def test_one_client_is_sent_the_scheduled_cards_own_rates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE END-TO-END CLAIM: the figures in the mail are the figures a purchase made on the
    day will freeze onto its lot, resolved from the card at its OWN instant."""
    await _record_a_card(rise="0.50")
    tenant_id = await _tenant("self_serve")
    recorder = _Recorder()
    monkeypatch.setattr(rate_card_notice, "get_transport", lambda: recorder)
    assert await notify_rate_card_change({}, _payload(tenant_id)) == "sent"
    body = recorder.sent[0]["body"]
    for pack in PACK_CATALOGUE:
        for voice in VOICE_TIERS:
            raised = (pack.inr_per_min(voice) + Decimal("0.50")).quantize(Decimal("0.01"))
            assert str(raised) in body
    assert _starts_on(CARD_AT) in body


async def test_a_managed_client_is_not_told_even_if_a_promise_reaches_this_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-read here rather than trusted from the fan-out: an account that moved onto an
    invoiced plan in between must not be told about a card that does not price it."""
    tenant_id = await _tenant("managed")
    recorder = _Recorder()
    monkeypatch.setattr(rate_card_notice, "get_transport", lambda: recorder)
    assert await notify_rate_card_change({}, _payload(tenant_id)) == "not_prepaid"
    assert recorder.sent == []


async def test_a_tenant_that_went_away_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An erasure does exactly this between the fan-out and the send."""
    recorder = _Recorder()
    monkeypatch.setattr(rate_card_notice, "get_transport", lambda: recorder)
    assert await notify_rate_card_change({}, _payload(uuid.uuid4())) == "tenant_missing"
    assert recorder.sent == []


async def test_a_client_with_no_address_is_alerted_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOT a retry: the row will be just as empty in five minutes, and burning the ladder to
    discover that hides the real problem — a client whose prices are changing has nobody to
    tell."""
    tenant_id = await _tenant("self_serve", billing_email=None)
    alerted: list[str] = []
    monkeypatch.setattr(rate_card_notice, "alert", lambda channel, key: alerted.append(key))
    monkeypatch.setattr(rate_card_notice, "get_transport", lambda: _Recorder())
    assert await notify_rate_card_change({}, _payload(tenant_id)) == "no_billing_email"
    assert alerted == ["rate_card_notice_no_billing_email"]


async def test_a_transport_that_refuses_asks_arq_to_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """`arq.Retry` and not a plain raise: anything else is terminal on the first attempt and
    `max_tries` decorative."""
    tenant_id = await _tenant("self_serve")
    monkeypatch.setattr(rate_card_notice, "get_transport", lambda: _Recorder(delivered=False))
    with pytest.raises(Retry):
        await notify_rate_card_change({}, _payload(tenant_id))


async def test_the_pack_rates_dataclass_is_frozen() -> None:
    """It crosses a job boundary as the thing the body is rendered from; a mutable one is a
    body that can be edited after it was composed."""
    rung = PackRates(amount_inr=Decimal("2000"), rates=(("Clear", Decimal("5.00")),))
    with pytest.raises(AttributeError):
        rung.amount_inr = Decimal("1")  # type: ignore[misc]


async def test_the_fan_out_alerts_when_it_reaches_its_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client silently missed from a notice is the exact failure this module exists to
    prevent, so the ceiling being reached is something an operator is TOLD about."""
    await _tenant("self_serve")
    alerted: list[str] = []
    monkeypatch.setattr(rate_card_notice, "alert", lambda channel, key: alerted.append(key))
    monkeypatch.setattr(rate_card_notice, "FANOUT_BUDGET", 1)
    await fan_out_rate_card_notice({}, {"effective_from": CARD_AT.isoformat()})
    assert alerted == ["rate_card_notice_fanout_budget_reached"]


def test_the_ist_offset_of_a_card_recorded_far_ahead_is_stable() -> None:
    """A card a year out still renders on the day an operator picked: India keeps one
    offset with no daylight saving, so the rendering cannot drift under it."""
    far = CARD_AT + timedelta(days=365)
    assert _starts_on(far) == "1 December 2027"
