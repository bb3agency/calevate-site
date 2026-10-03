"""The client's number rental (D-665).

What is pinned here:

1. the period arithmetic — anchored on the purchase date, clamped at month ends, never
   chained from the previous renewal;
2. the purchase debits the first month in the transaction that records the number;
3. the daily renewal debits the current period once, however often it runs, lands as an
   overdraft when the wallet cannot cover it, and skips released numbers;
4. the client sees it as "Phone number rental" — its own drawdown bucket, a ledger label
   and a statement line — and never our cost;
5. the founder's four rules of 3 Oct 2026: a managed account is invoiced rather than
   debited, a closed account is charged nothing, a number recorded before D-665 starts at
   its next renewal, and a period that begins in a trial is free on either route.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import number_rental
from apps.api.billing.invoice import build_invoice
from apps.api.billing.number_rental import (
    INVOICED_RENTAL_KIND,
    RENTAL_CHARGE_LABEL,
    RENTAL_CHARGE_META_KIND,
    charge_number_rental,
    collect_number_rental,
    rental_period_start,
    rental_ref,
)
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.service import get_balance, record_entry
from apps.api.billing.wallet import read_runway
from apps.api.campaigns import number_catalog
from apps.api.core.alarm_severity import ALARM_SEVERITY
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers.number_rental import renew_number_rentals
from sqlalchemy import text
from tests.number_provisioning_flow_test import (  # noqa: F401 - `authorized` is a fixture
    _attest_price,
    _pattern,
    _verify_kyc,
    _with_holder,
    authorized,
)
from tests.number_provisioning_flow_test import _tenant as _purchasing_tenant

# --------------------------------------------------------------- 1. the period arithmetic


def test_the_first_period_starts_on_the_purchase_day() -> None:
    anchor = date(2026, 3, 14)
    assert rental_period_start(anchor, anchor) == anchor
    assert rental_period_start(anchor, date(2026, 4, 13)) == anchor


def test_a_renewal_falls_on_the_same_day_of_the_next_month() -> None:
    anchor = date(2026, 3, 14)
    assert rental_period_start(anchor, date(2026, 4, 14)) == date(2026, 4, 14)
    assert rental_period_start(anchor, date(2027, 1, 20)) == date(2027, 1, 14)


def test_a_number_bought_on_the_31st_renews_on_short_month_ends_and_returns_to_the_31st() -> None:
    """Computed from the anchor, never chained: a chained walk would stay on the 28th."""
    anchor = date(2026, 1, 31)
    assert rental_period_start(anchor, date(2026, 2, 28)) == date(2026, 2, 28)
    assert rental_period_start(anchor, date(2026, 3, 30)) == date(2026, 2, 28)
    assert rental_period_start(anchor, date(2026, 3, 31)) == date(2026, 3, 31)
    assert rental_period_start(anchor, date(2026, 4, 30)) == date(2026, 4, 30)


def test_every_period_starts_in_its_own_calendar_month() -> None:
    """The ref keys a period by the month it starts in, so two periods in one month would
    collide and the second would never be charged."""
    for day in (1, 15, 28, 29, 30, 31):
        anchor = date(2026, 1, day)
        months: set[str] = set()
        on = anchor
        while on < date(2028, 1, 1):
            months.add(rental_period_start(anchor, on).strftime("%Y-%m"))
            on += timedelta(days=1)
        assert len(months) == 24, (day, len(months))


def test_a_day_before_the_purchase_belongs_to_no_period() -> None:
    with pytest.raises(ValueError):
        rental_period_start(date(2026, 3, 14), date(2026, 3, 13))


async def test_a_charge_for_a_day_that_is_not_a_renewal_date_is_refused() -> None:
    with pytest.raises(ValueError):
        await charge_number_rental(
            None,  # type: ignore[arg-type] - refused before the session is touched
            tenant_id=uuid.uuid4(),
            number_id=uuid.uuid4(),
            anchor=date(2026, 3, 14),
            period_start=date(2026, 3, 20),
            inr_per_month=Decimal("999.00"),
        )


async def test_a_zero_price_is_refused_rather_than_charged() -> None:
    with pytest.raises(ValueError):
        await charge_number_rental(
            None,  # type: ignore[arg-type] - refused before the session is touched
            tenant_id=uuid.uuid4(),
            number_id=uuid.uuid4(),
            anchor=date(2026, 3, 14),
            period_start=date(2026, 3, 14),
            inr_per_month=Decimal("0"),
        )


def test_the_renewal_alarm_is_classified() -> None:
    """`scripts/check_alarm_wiring.py` also requires the index row; this is the cheap half."""
    assert ALARM_SEVERITY["number_rental_renewals_unrecorded"] == "attention"


# ------------------------------------------------------------------ DB fixtures


async def _wallet_tenant(*, credit: str = "5000.00", tier: str | None = None) -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Rental Clinic",
        slug=f"rent-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        if tier is not None:
            await session.execute(
                text("UPDATE organizations SET plan_tier = :t WHERE id = :tid"),
                {"t": tier, "tid": tenant_id},
            )
        if Decimal(credit) > 0:
            await record_entry(
                session,
                tenant_id=tenant_id,
                delta=Decimal(credit),
                reason="topup",
                ref=f"UTR-{uuid.uuid4().hex[:10]}",
            )
    return tenant_id


async def _priced_number(
    tenant_id: uuid.UUID,
    *,
    bought_days_ago: int = 0,
    inr: str | None = "999.00",
    released: bool = False,
    charged_from: date | None = None,
    created_at: datetime | None = None,
) -> tuple[uuid.UUID, date]:
    """A client-priced number recorded `bought_days_ago`, written directly so its first
    period was never charged and only the renewal job is under test."""
    number_id = uuid7()
    created_at = created_at or datetime.now(UTC) - timedelta(days=bought_days_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, client_inr_per_month, "
                "released_at, rental_charged_from, created_at, updated_at) VALUES (:id, :tid, "
                ":e, 'standard', :inr, CASE WHEN :released THEN now() ELSE NULL END, "
                ":charged_from, :at, now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "e": f"+9180{uuid.uuid4().int % 100_000_000:08d}",
                "inr": Decimal(inr) if inr is not None else None,
                "released": released,
                "charged_from": charged_from,
                "at": created_at,
            },
        )
    return number_id, number_rental.ist_date(created_at)


async def _invoiced_rows(tenant_id: uuid.UUID, number_id: uuid.UUID) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT ref, amount, billing_month, description FROM one_time_charges "
                        "WHERE tenant_id = :tid AND kind = :kind AND ref LIKE :prefix "
                        "ORDER BY occurred_at"
                    ),
                    {
                        "tid": tenant_id,
                        "kind": INVOICED_RENTAL_KIND,
                        "prefix": f"number_rental:{number_id}:%",
                    },
                )
            ).all()
        )


async def _close(tenant_id: uuid.UUID) -> None:
    """Closed and not erased: `closed_at` set, `deleted_at` not (D-538)."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned', closed_at = now() WHERE id = :tid"),
            {"tid": tenant_id},
        )


async def _trial(tenant_id: uuid.UUID, *, started_days_ago: int, ends_in_days: int) -> None:
    """A trial from `started_days_ago` to `ends_in_days` from now; negative means it ended."""
    now = datetime.now(UTC)
    started = now - timedelta(days=started_days_ago)
    ends = now + timedelta(days=ends_in_days)
    active = ends > now
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_trials (id, tenant_id, days, started_at, ends_at, status, "
                "ended_at) VALUES (:id, :tid, :days, :start, :ends, :status, :ended)"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "days": started_days_ago + ends_in_days,
                "start": started,
                "ends": ends,
                "status": "active" if active else "expired",
                "ended": None if active else ends,
            },
        )


def _next_renewal(anchor: date, after: date) -> date:
    """The first renewal date strictly after `after`, walked day by day as a reference."""
    day = after + timedelta(days=1)
    while rental_period_start(anchor, day) != day:
        day += timedelta(days=1)
    return day


async def _rental_rows(tenant_id: uuid.UUID, number_id: uuid.UUID) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT delta, ref, meta->>'kind', meta->>'period_start' "
                        "FROM credit_ledger WHERE tenant_id = :tid AND reason = 'usage' "
                        "AND meta->>'number_id' = :nid ORDER BY occurred_at"
                    ),
                    {"tid": tenant_id, "nid": str(number_id)},
                )
            ).all()
        )


# ------------------------------------------------- 2. the purchase debits the first month


@pytest.mark.rls
@pytest.mark.usefixtures("authorized")
async def test_a_purchase_debits_the_first_month_from_the_wallet() -> None:
    amount = await _attest_price("1234.50")
    org = await _purchasing_tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    await _verify_kyc(tenant_id)
    async with tenant_session(tenant_id) as session:
        before = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session, get_engine(), tenant_id=tenant_id, e164=offers[0].e164, pattern=pattern
        )
    async with tenant_session(tenant_id) as session:
        after = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    assert before - after == amount

    rows = await _rental_rows(tenant_id, bought.number_id)
    assert len(rows) == 1
    delta, ref, kind, period_start = rows[0]
    assert Decimal(str(delta)) == -amount
    assert kind == RENTAL_CHARGE_META_KIND
    assert ref == rental_ref(bought.number_id, period_start[:7])


@pytest.mark.rls
@pytest.mark.usefixtures("authorized")
async def test_the_renewal_job_does_not_charge_the_purchase_month_again() -> None:
    await _attest_price("999.00")
    org = await _purchasing_tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session, get_engine(), tenant_id=tenant_id, e164=offers[0].e164, pattern=pattern
        )
    await renew_number_rentals({})
    assert len(await _rental_rows(tenant_id, bought.number_id)) == 1


# ------------------------------------------------------------------ 3. the renewal


@pytest.mark.rls
async def test_a_renewal_is_charged_once_however_often_the_job_runs() -> None:
    tenant_id = await _wallet_tenant()
    number_id, anchor = await _priced_number(tenant_id, bought_days_ago=40)
    await renew_number_rentals({})
    await renew_number_rentals({})
    rows = await _rental_rows(tenant_id, number_id)
    assert len(rows) == 1
    delta, ref, _kind, period_start = rows[0]
    expected = rental_period_start(anchor, number_rental.today_ist())
    assert period_start == expected.isoformat()
    assert ref == rental_ref(number_id, expected.strftime("%Y-%m"))
    assert Decimal(str(delta)) == Decimal("-999.00")


@pytest.mark.rls
async def test_a_renewal_the_wallet_cannot_cover_lands_as_an_overdraft() -> None:
    tenant_id = await _wallet_tenant(credit="100.00")
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40)
    await renew_number_rentals({})
    assert len(await _rental_rows(tenant_id, number_id)) == 1
    async with tenant_session(tenant_id) as session:
        balance = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    assert balance == Decimal("-899.00"), "the charge lands; the balance carries what is owed"


@pytest.mark.rls
async def test_a_released_number_stops_renewing() -> None:
    tenant_id = await _wallet_tenant()
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40, released=True)
    await renew_number_rentals({})
    assert await _rental_rows(tenant_id, number_id) == []


@pytest.mark.rls
async def test_an_invoiced_account_is_not_debited() -> None:
    tenant_id = await _wallet_tenant(credit="0", tier="managed")
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40)
    await renew_number_rentals({})
    assert await _rental_rows(tenant_id, number_id) == []


@pytest.mark.rls
async def test_an_erased_tenant_is_skipped() -> None:
    tenant_id = await _wallet_tenant()
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET deleted_at = now() WHERE id = :tid"),
            {"tid": tenant_id},
        )
    await renew_number_rentals({})
    assert await _rental_rows(tenant_id, number_id) == []


@pytest.mark.rls
async def test_one_tenant_never_sees_another_tenants_rental() -> None:
    owner = await _wallet_tenant()
    other = await _wallet_tenant()
    number_id, _ = await _priced_number(owner, bought_days_ago=40)
    await renew_number_rentals({})
    assert len(await _rental_rows(owner, number_id)) == 1
    async with tenant_session(other) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE meta->>'number_id' = :nid"),
                {"nid": str(number_id)},
            )
        ).scalar()
    assert seen == 0


# ------------------------------------------------- 4. what the client sees


@pytest.mark.rls
async def test_the_rental_is_its_own_bucket_label_and_statement_line() -> None:
    tenant_id = await _wallet_tenant()
    await _priced_number(tenant_id, bought_days_ago=40, inr="750.00")
    await renew_number_rentals({})

    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
        _, drawdown = await read_runway(session, tenant_id=tenant_id, balance=balance)
        invoice = await build_invoice(
            session, tenant_id=tenant_id, month=ist_billing_month(datetime.now(UTC))
        )
    assert drawdown.number_rental_inr == Decimal("750.00")
    assert drawdown.calls_inr == Decimal("0"), "a rental is not a call"
    assert drawdown.spent_inr == Decimal("750.00")

    lines = [line for line in invoice["line_items"] if line["description"] == RENTAL_CHARGE_LABEL]
    assert len(lines) == 1
    (line,) = lines
    assert line["qty"] == Decimal("1")
    assert line["unit_inr"] == Decimal("750.00")
    assert line["amount_inr"] == line["qty"] * line["unit_inr"]
    # Bill of supply while unregistered (D-659): the line changes no tax position.
    if invoice["document_type"] == "bill_of_supply":
        assert invoice["gst_inr"] == Decimal("0.00")


@pytest.mark.rls
async def test_the_client_ledger_labels_the_rental_and_carries_no_cost() -> None:
    from apps.api.main import app
    from httpx import ASGITransport, AsyncClient
    from tests.number_provisioning_flow_test import _member

    tenant_id = await _wallet_tenant()
    await _priced_number(tenant_id, bought_days_ago=40)
    await renew_number_rentals({})
    async with tenant_session(tenant_id) as session:
        slug = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
            )
        ).scalar()
    user_id = await _member(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.get(
            "/v1/billing/wallet/ledger",
            headers={"Authorization": f"Bearer dev:client:{user_id}", "X-Org-Slug": str(slug)},
        )
    assert response.status_code == 200, response.text
    rentals = [e for e in response.json()["entries"] if e["label"] == RENTAL_CHARGE_LABEL]
    assert len(rentals) == 1
    assert "usd" not in response.text.lower()


# ------------------------------------------------- 5a. managed accounts are invoiced


def _period_of(anchor: date) -> date:
    return rental_period_start(anchor, number_rental.today_ist())


@pytest.mark.rls
async def test_a_managed_account_gets_one_invoice_line_per_period_and_no_debit() -> None:
    tenant_id = await _wallet_tenant(credit="0", tier="managed")
    number_id, anchor = await _priced_number(tenant_id, bought_days_ago=40, inr="750.00")
    await renew_number_rentals({})
    await renew_number_rentals({})

    assert await _rental_rows(tenant_id, number_id) == [], "a managed account has no wallet"
    month = _period_of(anchor).strftime("%Y-%m")
    rows = await _invoiced_rows(tenant_id, number_id)
    assert len(rows) == 1, "one line per (number, period), however often the job runs"
    ref, amount, billing_month, description = rows[0]
    assert ref == rental_ref(number_id, month)
    assert Decimal(str(amount)) == Decimal("750.00"), "the same frozen client price"
    assert billing_month == month
    assert description == RENTAL_CHARGE_LABEL

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id, month=month)
    lines = [line for line in invoice["line_items"] if line["description"] == RENTAL_CHARGE_LABEL]
    assert len(lines) == 1, "printed once, by the rental reader, not again as a one-time charge"
    (line,) = lines
    assert line["qty"] == Decimal("1")
    assert line["unit_inr"] == Decimal("750.00")
    assert line["amount_inr"] == Decimal("750.00")
    # Bill of supply while unregistered (D-659): the line changes no tax position.
    if invoice["document_type"] == "bill_of_supply":
        assert invoice["gst_inr"] == Decimal("0.00")


@pytest.mark.rls
async def test_a_managed_accounts_numbers_at_one_price_share_one_line() -> None:
    tenant_id = await _wallet_tenant(credit="0", tier="managed")
    first, anchor = await _priced_number(tenant_id, bought_days_ago=40)
    # A second number anchored on the same IST day, so both periods start in one month.
    same_day = datetime.combine(anchor, datetime.min.time(), tzinfo=number_rental.IST)
    await _priced_number(tenant_id, created_at=same_day + timedelta(hours=12))
    await renew_number_rentals({})
    month = _period_of(anchor).strftime("%Y-%m")
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id, month=month)
    (line,) = [i for i in invoice["line_items"] if i["description"] == RENTAL_CHARGE_LABEL]
    assert line["qty"] == Decimal("2")
    assert line["amount_inr"] == line["qty"] * line["unit_inr"]
    assert len(await _invoiced_rows(tenant_id, first)) == 1


@pytest.mark.rls
@pytest.mark.usefixtures("authorized")
async def test_a_managed_purchase_puts_the_first_month_on_the_invoice() -> None:
    amount = await _attest_price("999.00")
    org = await _purchasing_tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'managed' WHERE id = :tid"),
            {"tid": tenant_id},
        )
    await _with_holder(tenant_id)
    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session, get_engine(), tenant_id=tenant_id, e164=offers[0].e164, pattern=pattern
        )
    assert await _rental_rows(tenant_id, bought.number_id) == []
    rows = await _invoiced_rows(tenant_id, bought.number_id)
    assert len(rows) == 1
    assert Decimal(str(rows[0][1])) == amount
    await renew_number_rentals({})
    assert len(await _invoiced_rows(tenant_id, bought.number_id)) == 1


# ------------------------------------------------- 5b. closed accounts are not charged


@pytest.mark.rls
async def test_a_closed_prepaid_account_is_not_debited() -> None:
    tenant_id = await _wallet_tenant()
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40)
    await _close(tenant_id)
    await renew_number_rentals({})
    assert await _rental_rows(tenant_id, number_id) == []


@pytest.mark.rls
async def test_a_closed_managed_account_gets_no_invoice_line() -> None:
    tenant_id = await _wallet_tenant(credit="0", tier="managed")
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40)
    await _close(tenant_id)
    await renew_number_rentals({})
    assert await _invoiced_rows(tenant_id, number_id) == []


# ------------------------------------------------- 5c. numbers recorded before D-665


async def test_a_period_before_the_first_charged_one_is_collected_from_nobody() -> None:
    outcome = await collect_number_rental(
        None,  # type: ignore[arg-type] - decided before the session is touched
        tenant_id=uuid.uuid4(),
        number_id=uuid.uuid4(),
        recorded_at=datetime(2026, 3, 14, 6, 0, tzinfo=UTC),
        charged_from=date(2026, 4, 14),
        period_start=date(2026, 3, 14),
        inr_per_month=Decimal("999.00"),
    )
    assert outcome == "before_first_period"


@pytest.mark.rls
async def test_a_number_from_before_d665_is_not_charged_for_the_period_under_way() -> None:
    tenant_id = await _wallet_tenant()
    bought_at = datetime.now(UTC) - timedelta(days=40)
    anchor = number_rental.ist_date(bought_at)
    number_id, _ = await _priced_number(
        tenant_id,
        created_at=bought_at,
        charged_from=_next_renewal(anchor, number_rental.today_ist()),
    )
    await renew_number_rentals({})
    assert await _rental_rows(tenant_id, number_id) == []


@pytest.mark.rls
async def test_a_number_from_before_d665_is_charged_from_its_next_renewal() -> None:
    """Its first renewal after the deploy has arrived: `rental_charged_from` is the period
    under way today, so that period is charged, once."""
    tenant_id = await _wallet_tenant()
    bought_at = datetime.now(UTC) - timedelta(days=40)
    current = rental_period_start(number_rental.ist_date(bought_at), number_rental.today_ist())
    number_id, _ = await _priced_number(tenant_id, created_at=bought_at, charged_from=current)
    await renew_number_rentals({})
    await renew_number_rentals({})
    rows = await _rental_rows(tenant_id, number_id)
    assert len(rows) == 1
    assert rows[0][3] == current.isoformat()


def _cutover_migration() -> Any:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    path = next(versions.glob("e8b14d6a2c57_*.py"))
    spec = importlib.util.spec_from_file_location("rental_cutover_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.rls
async def test_the_cutover_stamps_each_existing_number_with_its_next_renewal() -> None:
    """The migration's SQL against the Python period arithmetic, on fresh anchors and on a
    month-end anchor, so the cutover and the job agree about which day is a renewal."""
    tenant_id = await _wallet_tenant()
    today = number_rental.today_ist()
    numbers = [
        await _priced_number(tenant_id, bought_days_ago=days) for days in (0, 3, 29, 40, 75, 400)
    ]
    numbers.append(
        await _priced_number(tenant_id, created_at=datetime(2026, 1, 31, 6, 0, tzinfo=UTC))
    )
    unpriced, _ = await _priced_number(tenant_id, bought_days_ago=40, inr=None)
    # Under the tenant's own session the statement can only reach this tenant's rows, so
    # the migration's NO FORCE bracket is not needed to exercise its arithmetic.
    async with tenant_session(tenant_id) as session:
        await session.execute(text(_cutover_migration()._STAMP_FIRST_RENEWAL))
    async with tenant_session(tenant_id) as session:
        stamped = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    text("SELECT id, rental_charged_from FROM phone_numbers WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).all()
        }
    for number_id, anchor in numbers:
        assert stamped[number_id] == _next_renewal(anchor, today), (anchor, today)
    assert stamped[unpriced] is None, "a number with no client price is never charged"


# ------------------------------------------------- 5d. trials


@pytest.mark.rls
async def test_a_renewal_inside_a_trial_is_not_charged() -> None:
    tenant_id = await _wallet_tenant()
    await _trial(tenant_id, started_days_ago=60, ends_in_days=10)
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40)
    await renew_number_rentals({})
    assert await _rental_rows(tenant_id, number_id) == []


@pytest.mark.rls
async def test_a_period_that_began_in_the_trial_is_not_back_charged_after_it() -> None:
    """The trial ended two days ago, inside the period under way: charging starts at the
    next renewal date, never on the period that opened while the trial ran."""
    tenant_id = await _wallet_tenant()
    await _trial(tenant_id, started_days_ago=60, ends_in_days=-2)
    number_id, anchor = await _priced_number(tenant_id, bought_days_ago=40)
    today = number_rental.today_ist()
    assert rental_period_start(anchor, today) <= today - timedelta(days=8), (
        "the fixture's period must have begun while the trial ran"
    )
    await renew_number_rentals({})
    assert await _rental_rows(tenant_id, number_id) == []


@pytest.mark.rls
async def test_a_period_that_begins_after_the_trial_is_charged() -> None:
    tenant_id = await _wallet_tenant()
    await _trial(tenant_id, started_days_ago=120, ends_in_days=-60)
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40)
    await renew_number_rentals({})
    assert len(await _rental_rows(tenant_id, number_id)) == 1


@pytest.mark.rls
async def test_a_managed_account_in_a_trial_gets_no_invoice_line() -> None:
    tenant_id = await _wallet_tenant(credit="0", tier="managed")
    await _trial(tenant_id, started_days_ago=60, ends_in_days=10)
    number_id, _ = await _priced_number(tenant_id, bought_days_ago=40)
    await renew_number_rentals({})
    assert await _invoiced_rows(tenant_id, number_id) == []


@pytest.mark.rls
@pytest.mark.usefixtures("authorized")
async def test_a_purchase_during_a_trial_debits_nothing_then_or_at_renewal() -> None:
    await _attest_price("999.00")
    org = await _purchasing_tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    await _with_holder(tenant_id)
    await _trial(tenant_id, started_days_ago=1, ends_in_days=13)
    async with tenant_session(tenant_id) as session:
        before = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    pattern = _pattern()
    async with tenant_session(tenant_id) as session:
        offers = await number_catalog.browse_numbers(session, get_engine(), pattern=pattern)
        bought = await number_catalog.purchase_number(
            session, get_engine(), tenant_id=tenant_id, e164=offers[0].e164, pattern=pattern
        )
    await renew_number_rentals({})
    async with tenant_session(tenant_id) as session:
        after = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    assert after == before
    assert await _rental_rows(tenant_id, bought.number_id) == []
