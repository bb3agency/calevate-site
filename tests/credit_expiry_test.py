"""Pack credit lapses 12 months after purchase, as Terms 6.1 (revision 19) says (D-840)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.billing import credit_expiry
from apps.api.billing import lots as credit_lots
from apps.api.billing.credit_expiry import (
    assert_expiry_may_switch_on,
    credit_expiry_months,
    due_lots,
    expire_lot,
    expires_at_for,
)
from apps.api.billing.plans import IST
from apps.api.billing.service import (
    LotRates,
    apply_credit_to_lots,
    find_entry_by_ref,
    get_balance,
    record_entry,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.credit_expiry import expire_credit_lots
from sqlalchemy import text
from tests.spend_attribution_test import _tenant


@pytest.fixture
def expiry_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twelve months, pinned so an ambient console value cannot change the term under test."""
    monkeypatch.setattr(get_settings(), "credit_pack_expiry_months", 12)


@pytest.fixture
def expiry_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The console row cleared: credit bought now carries no term."""
    monkeypatch.setattr(get_settings(), "credit_pack_expiry_months", None)


async def _buy(tenant_id: uuid.UUID, amount: str) -> uuid.UUID:
    """A pack purchase: the ledger credit, then its lot, in one transaction."""
    ref = f"TEST-{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        balance = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal(amount), reason="topup", ref=ref
        )
        entry = await find_entry_by_ref(session, tenant_id=tenant_id, reason="topup", ref=ref)
        assert entry is not None
        credited = await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal(amount),
            balance_after=balance.amount_inr,
            rates=LotRates(clear_inr_per_min=Decimal("4.50"), studio_inr_per_min=Decimal("6.00")),
            source="topup",
            pack_id="starter",
            ledger_entry_id=entry.entry_id,
        )
    assert credited.lot_id is not None
    return credited.lot_id


def test_the_term_is_calendar_months_in_ist_clamped_to_the_month() -> None:
    bought = datetime(2026, 1, 31, 10, 0, tzinfo=IST)
    assert expires_at_for(bought, months=1) == datetime(2026, 2, 28, 10, 0, tzinfo=IST)
    assert expires_at_for(bought, months=12) == datetime(2027, 1, 31, 10, 0, tzinfo=IST)
    # 20:00 UTC on 31 Mar is 01:30 IST on 1 Apr: the IST date is what is counted from.
    late = datetime(2026, 3, 31, 20, 0, tzinfo=UTC)
    assert expires_at_for(late, months=1) == datetime(2026, 5, 1, 1, 30, tzinfo=IST)


def test_expiry_is_on_by_default_and_names_a_published_terms_revision() -> None:
    from apps.api.legal.catalogue import DOCUMENTS
    from calevate_shared.config import Settings

    terms = next(doc for doc in DOCUMENTS if doc.slug == "terms")
    stating = next(
        rev
        for rev in terms.revisions
        if rev.revision == credit_expiry.TERMS_REVISION_STATING_EXPIRY
    )
    assert stating.material, "a revision that makes bought credit lapse must re-ask acceptance"
    assert Settings.model_fields["credit_pack_expiry_months"].default == 12
    assert credit_expiry.TERMS_EXPIRY_MONTHS == 12


def test_the_setting_is_accepted_at_or_above_the_promised_term(expiry_on: None) -> None:
    assert credit_expiry_months() == 12
    for months in (12, 24, 60, None):
        assert_expiry_may_switch_on(months)
    with pytest.raises(ProblemError) as caught:
        assert_expiry_may_switch_on(11)
    assert caught.value.code == "credit_expiry_shorter_than_terms"


def test_the_setting_is_refused_and_ignored_without_a_terms_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credit_expiry, "TERMS_REVISION_STATING_EXPIRY", None)
    monkeypatch.setattr(get_settings(), "credit_pack_expiry_months", 12)
    assert credit_expiry_months() is None
    with pytest.raises(ProblemError) as caught:
        assert_expiry_may_switch_on(12)
    assert caught.value.code == "credit_expiry_terms_not_published"
    assert_expiry_may_switch_on(None)


async def test_credit_bought_while_expiry_is_off_never_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lot opened before the switch keeps no term after it: the term is frozen at purchase."""
    monkeypatch.setattr(get_settings(), "credit_pack_expiry_months", None)
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lot_id = await _buy(tenant_id, "1000")
    monkeypatch.setattr(get_settings(), "credit_pack_expiry_months", 12)
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
        far = datetime.now(UTC) + timedelta(days=3650)
        assert await due_lots(session, now=far) == []
    assert lot is not None and lot.expires_at is None


async def test_a_pack_bought_now_lapses_twelve_ist_calendar_months_after_it_opened(
    expiry_on: None,
) -> None:
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lot_id = await _buy(tenant_id, "1000")
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
    assert lot is not None and lot.expires_at is not None
    # `opened_at` is the database clock and the term the Python one, a moment apart.
    expected = expires_at_for(lot.opened_at, months=12)
    assert abs(lot.expires_at - expected) < timedelta(seconds=5)
    assert lot.expires_at.astimezone(IST).day == lot.opened_at.astimezone(IST).day


async def test_a_grant_carries_no_term(expiry_on: None) -> None:
    tenant_id, _agent = await _tenant(monthly_fee=None)
    async with tenant_session(tenant_id) as session:
        balance = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("200"), reason="grant", ref="GIFT-1"
        )
        entry = await find_entry_by_ref(session, tenant_id=tenant_id, reason="grant", ref="GIFT-1")
        assert entry is not None
        credited = await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("200"),
            balance_after=balance.amount_inr,
            rates=LotRates(clear_inr_per_min=Decimal("4.50"), studio_inr_per_min=Decimal("6.00")),
            source="grant",
            pack_id=None,
            ledger_entry_id=entry.entry_id,
        )
        assert credited.lot_id is not None
        lot = await credit_lots.read_lot(session, lot_id=credited.lot_id)
    assert lot is not None and lot.expires_at is None


async def test_a_pack_bought_with_expiry_on_lapses_once_by_an_appended_row(
    expiry_on: None,
) -> None:
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lot_id = await _buy(tenant_id, "1000")
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
    assert lot is not None and lot.expires_at is not None
    assert timedelta(days=364) < lot.expires_at - lot.opened_at < timedelta(days=367)

    later = lot.expires_at + timedelta(seconds=1)
    async with tenant_session(tenant_id) as session:
        assert await due_lots(session, now=lot.expires_at - timedelta(seconds=1)) == []
        assert await due_lots(session, now=later) == [lot_id]
        expired = await expire_lot(session, tenant_id=tenant_id, lot_id=lot_id, now=later)
    assert expired is not None and expired.credits_inr == Decimal("1000.0000")
    async with tenant_session(tenant_id) as session:
        again = await expire_lot(session, tenant_id=tenant_id, lot_id=lot_id, now=later)
        balance = await get_balance(session, tenant_id=tenant_id)
        rows = (
            await session.execute(
                text(
                    "SELECT delta, reason, meta->>'kind' FROM credit_ledger "
                    "WHERE tenant_id = :t AND ref = :r"
                ),
                {"t": tenant_id, "r": f"credit_expiry:{lot_id}"},
            )
        ).all()
        closed = await credit_lots.read_lot(session, lot_id=lot_id)
    assert again is None, "a second run expires nothing"
    assert balance.amount_inr == Decimal("0")
    assert [(Decimal(str(r[0])), r[1], r[2]) for r in rows] == [
        (Decimal("-1000.00"), "adjustment", "credit_expiry")
    ]
    assert closed is not None and closed.closed_at is not None
    assert closed.credits_remaining == 0


async def test_the_daily_job_expires_only_what_is_due(expiry_on: None) -> None:
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lot_id = await _buy(tenant_id, "500")
    summary = await expire_credit_lots({})
    assert "'failed': 0" in summary
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
    assert lot is not None and lot.closed_at is None, "a lot not yet due was expired"


async def test_a_lot_not_yet_due_is_left_alone_when_asked_directly(expiry_on: None) -> None:
    """`expire_lot` re-reads the lot under the credit lock: a caller holding a stale due list
    must not lapse credit that is not due."""
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lot_id = await _buy(tenant_id, "500")
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
        assert lot is not None and lot.expires_at is not None
        early = lot.expires_at - timedelta(seconds=1)
        assert await expire_lot(session, tenant_id=tenant_id, lot_id=lot_id, now=early) is None
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("500")


async def _lapse(tenant_id: uuid.UUID, lot_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
        assert lot is not None and lot.expires_at is not None
        later = lot.expires_at + timedelta(seconds=1)
        assert await expire_lot(session, tenant_id=tenant_id, lot_id=lot_id, now=later)


async def _entry_of(tenant_id: uuid.UUID, lot_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        entry = (
            await session.execute(
                text("SELECT ledger_entry_id FROM credit_lots WHERE id = :l"), {"l": lot_id}
            )
        ).scalar_one()
    return uuid.UUID(str(entry))


async def _lots_total(tenant_id: uuid.UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        total = (
            await session.execute(
                text("SELECT COALESCE(SUM(credits_remaining), 0) FROM credit_lots")
            )
        ).scalar()
    return Decimal(str(total))


async def test_credit_restated_onto_a_lapsed_purchase_opens_its_own_lot(expiry_on: None) -> None:
    """A restatement grew the purchase's lot through `_RESTATE_LOT`, which REOPENED the lapsed
    lot: its expiry row was already written, so it never lapsed again, and the daily job
    found it due on every run."""
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lapsed_id = await _buy(tenant_id, "1000")
    await _lapse(tenant_id, lapsed_id)
    async with tenant_session(tenant_id) as session:
        balance = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500"), reason="topup", ref="RESTATE-1"
        )
        entry = await find_entry_by_ref(
            session, tenant_id=tenant_id, reason="topup", ref="RESTATE-1"
        )
        assert entry is not None
        credited = await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("500"),
            balance_after=balance.amount_inr,
            rates=LotRates(clear_inr_per_min=Decimal("9"), studio_inr_per_min=Decimal("9")),
            source="topup",
            pack_id=None,
            ledger_entry_id=entry.entry_id,
            restate_lot_id=lapsed_id,
        )
        old = await credit_lots.read_lot(session, lot_id=lapsed_id)
        new = await credit_lots.read_lot(session, lot_id=credited.lot_id)  # type: ignore[arg-type]
    assert credited.lot_id not in (None, lapsed_id)
    assert old is not None and old.closed_at is not None and old.credits_remaining == 0
    assert new is not None and new.credits_remaining == Decimal("500.0000")
    assert (new.clear_inr_per_min, new.studio_inr_per_min) == (Decimal("4.50"), Decimal("6.00"))
    assert new.expires_at is not None and new.expires_at > datetime.now(UTC)


async def test_reversing_a_lapsed_purchase_takes_back_its_lapsed_credit_first(
    expiry_on: None,
) -> None:
    """A reversal of a purchase whose credit had lapsed used to take the WHOLE amount off the
    client's other purchases, so the lapsed rupees were lost twice. It is met first from the
    lapsed credit, given back by a compensating row, and only the rest comes off the queue."""
    from apps.api.billing.service import CREDIT_EXPIRY_RESTATED_META_KIND, remove_credit_from_lots

    tenant_id, _agent = await _tenant(monthly_fee=None)
    first = await _buy(tenant_id, "1000")
    second = await _buy(tenant_id, "1000")
    async with tenant_session(tenant_id) as session:
        spent = await credit_lots.consume(
            session, tenant_id=tenant_id, demand=credit_lots.AiAssistDemand(credits=Decimal("400"))
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-400"),
            reason="usage",
            meta={"lots": [{"lot_id": str(s.lot_id)} for s in spent]},
        )
    await _lapse(tenant_id, first)  # ₹600 of the first purchase lapses
    entry_id = await _entry_of(tenant_id, first)
    async with tenant_session(tenant_id) as session:
        removal = await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=entry_id, amount_inr=Decimal("1000")
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-1000"),
            reason="adjustment",
            ref="REVERSE-LAPSED",
            allow_negative=True,
        )
        balance = (await get_balance(session, tenant_id=tenant_id)).amount_inr
        kinds = (
            (
                await session.execute(
                    text(
                        "SELECT delta FROM credit_ledger WHERE tenant_id = :t "
                        "AND meta->>'kind' = :k"
                    ),
                    {"t": tenant_id, "k": CREDIT_EXPIRY_RESTATED_META_KIND},
                )
            )
            .scalars()
            .all()
        )
        remaining_second = await credit_lots.read_lot(session, lot_id=second)
    assert removal.expiry_restated_inr == Decimal("600.0000")
    assert [Decimal(str(d)) for d in kinds] == [Decimal("600.0000")]
    assert balance == Decimal("600")
    assert remaining_second is not None and remaining_second.credits_remaining == Decimal("600")
    assert await _lots_total(tenant_id) == balance, "the lots still say what the balance says"

    # A second reversal finds nothing left to give back.
    async with tenant_session(tenant_id) as session:
        again = await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=entry_id, amount_inr=Decimal("100")
        )
    assert again.expiry_restated_inr == Decimal("0")


async def test_a_dispute_on_a_lapsed_purchase_won_back_leaves_the_balance_where_it_was(
    expiry_on: None,
) -> None:
    """The hold is met from the lapsed credit first, so the release gives back only what the
    hold really took; it used to restore lapsed credit as spendable money."""
    from apps.api.billing.disputes import DisputeFacts, apply_dispute_event

    tenant_id, _agent = await _tenant(monthly_fee=None)
    ref = f"TEST-{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        balance = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("1000"), reason="topup", ref=ref
        )
        entry = await find_entry_by_ref(session, tenant_id=tenant_id, reason="topup", ref=ref)
        assert entry is not None
        credited = await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal("1000"),
            balance_after=balance.amount_inr,
            rates=LotRates(clear_inr_per_min=Decimal("4.50"), studio_inr_per_min=Decimal("6.00")),
            source="topup",
            pack_id=None,
            ledger_entry_id=entry.entry_id,
        )
    assert credited.lot_id is not None
    await _lapse(tenant_id, credited.lot_id)
    other = await _buy(tenant_id, "300")
    dispute_id = f"disp_{uuid.uuid4().hex[:12]}"
    for status in ("open", "won"):
        async with tenant_session(tenant_id) as session:
            await apply_dispute_event(
                session,
                tenant_id=tenant_id,
                event=f"payment.dispute.{status}",
                dispute=DisputeFacts(
                    dispute_id=dispute_id,
                    payment_id=ref,
                    amount_inr=Decimal("1000"),
                    status=status,
                    phase="chargeback",
                    reason_code=None,
                    respond_by=None,
                ),
            )
    async with tenant_session(tenant_id) as session:
        final = (await get_balance(session, tenant_id=tenant_id)).amount_inr
        untouched = await credit_lots.read_lot(session, lot_id=other)
    assert final == Decimal("300")
    assert untouched is not None and untouched.credits_remaining == Decimal("300")
    assert await _lots_total(tenant_id) == final


async def test_the_pack_card_states_the_term_and_the_ist_day_it_lapses(expiry_on: None) -> None:
    """Stated at purchase (Terms 6.1): the buy screen and the public price page read these."""
    from apps.api.billing.payment_routes import rate_card_out
    from apps.api.db.session import untenanted_session

    async with untenanted_session() as session:
        card = await rate_card_out(session)
    assert card.credit_expiry_months == 12
    today = datetime.now(UTC)
    assert card.credit_lapses_on_if_bought_now in {
        expires_at_for(today - timedelta(minutes=1), months=12).date(),
        expires_at_for(today, months=12).date(),
    }


async def test_the_pack_card_states_no_term_when_the_console_clears_it(
    expiry_off: None,
) -> None:
    from apps.api.billing.payment_routes import rate_card_out
    from apps.api.db.session import untenanted_session

    async with untenanted_session() as session:
        card = await rate_card_out(session)
    assert card.credit_expiry_months is None
    assert card.credit_lapses_on_if_bought_now is None


class _Mailbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return True


async def _promised_notices(tenant_id: uuid.UUID, lot_id: uuid.UUID) -> int:
    from apps.api.billing.credit_expiry import lapse_notice_key

    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM outbox_messages WHERE dedupe_key = :k"),
                {"k": lapse_notice_key(lot_id)},
            )
        ).scalar_one()
    return int(count)


async def test_a_lot_lapsing_within_thirty_days_is_warned_once_by_email(
    expiry_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.workers import credit_expiry as worker

    tenant_id, _agent = await _tenant(monthly_fee=None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET billing_email = 'owner@example.test' WHERE id = :i"),
            {"i": tenant_id},
        )
    lot_id = await _buy(tenant_id, "750")
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
    assert lot is not None and lot.expires_at is not None

    early = lot.expires_at - timedelta(days=31)
    assert await worker._promise_lapse_notices(tenant_id, now=early) == 0
    inside = lot.expires_at - timedelta(days=10)
    assert await worker._promise_lapse_notices(tenant_id, now=inside) == 1
    assert await worker._promise_lapse_notices(tenant_id, now=inside) == 0, "promised twice"
    assert await _promised_notices(tenant_id, lot_id) == 1

    mailbox = _Mailbox()
    monkeypatch.setattr(worker, "get_transport", lambda: mailbox)
    payload = {"tenant_id": str(tenant_id), "lot_id": str(lot_id)}
    assert await worker.notify_credit_lapsing({"job_try": 1}, payload) == "sent"
    [mail] = mailbox.sent
    assert mail["to"] == "owner@example.test"
    assert "₹750.00" in mail["body"]
    assert worker.ist_moment(lot.expires_at) in mail["body"]
    for vendor in ("Razorpay", "ThinnestAI", "Cartesia", "Sarvam"):
        assert vendor not in mail["body"]

    # Lapsed before the email goes: nothing left to warn about.
    await _lapse(tenant_id, lot_id)
    assert await worker.notify_credit_lapsing({"job_try": 1}, payload) == "nothing_to_lapse"
    assert len(mailbox.sent) == 1
