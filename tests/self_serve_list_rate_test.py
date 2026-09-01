"""A closed month renders at the list rate that was in force, not at today's (D-492).

THE DEFECT, in one sentence: `Settings.self_serve_inr_per_min` is ONE number with no
history — `platform_settings` is keyed by `key`, so changing the price OVERWRITES the row —
and two money readers were asking it a question it cannot answer.

* `billing/service.calling_revenue_inr` priced a CLOSED month's minutes at the LIVE
  setting. A prepaid client's settled statement, and the admin margin panel beside it,
  were therefore re-priced by every later rate move: 14.83 minutes rendered ₹88.98 and
  then ₹133.47 once the rate went 6 -> 9, against wallet debits of ₹89.00 that had already
  been taken and cannot change. Client-reachable at `GET /usage?month=`.
* `workers/pipeline` debited a LATE-SETTLING call at the LIVE setting while the
  `llm_surcharge` added to it IN THE SAME EXPRESSION was resolved at
  `month_pricing_instant`. A call that settles after the IST month rolls — the
  reconciliation poller's window straddling midnight on the 1st, an ARQ retry ladder
  crossing it, a vendor that takes minutes to price a call — was charged at NEXT month's
  price. The `month_pricing_instant` fix that landed before this one covered only the
  `plans` read.

THE FIX is an effective-dated home for the number (`platform_list_rates`, migration
d3b81f5c02ae, read and written through `billing/list_rates.py`) and both readers moved onto
it, so there is ONE answer to "what did a minute cost in month M".

WHY EVERY TEST HERE SETS THE LIVE SETTING TO THE *WRONG* RATE. The fixture puts ₹6 in the
ledger for the closed month, ₹9 in the ledger from this month, AND ₹9 in `Settings`. Every
assertion is then ₹6: against the unfixed code each one reads ₹9 out of `Settings` and
fails by 50%, so none of them can pass for the wrong reason.

`platform_list_rates` IS A SHARED, GLOBAL, APPEND-ONLY TABLE. Every test here writes rows
under the real `self_serve_inr_per_min` key and the autouse fixture removes them as the
OWNER afterwards — the only role that can, because the table is append-only on purpose.
Leaving one behind would change what `self_serve_rate_at` answers for every other suite on
this database (`margin_prepaid_revenue_test` asserts against the `Settings` fallback), so
the cleanup is not tidiness.

Run: uv run pytest -q tests/self_serve_list_rate_test.py
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.attribution import period_attribution
from apps.api.billing.list_rates import SELF_SERVE_PER_MIN, record_list_rate, self_serve_rate_at
from apps.api.billing.plans import ist_billing_month, ist_month_end, month_pricing_instant
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.billing.service import margin_for_tenant, to_paise, usage_summary
from apps.api.core.settings import Settings, get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops.config_routes import _record_list_rate
from apps.api.ops.config_service import WriteResult
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.spend_caps_test import _bill, _spend_state, _tenant

#: Far apart on purpose, and in the ratio the audit measured: a wrong rate is then half
#: the bill again, never a rounding argument.
_OLD_RATE = Decimal("6.0000")
_NEW_RATE = Decimal("9.0000")

#: 890s = 14.8333.. minutes, which the panel publishes as 14.83 — the exact figure the
#: audit reproduced the defect on (₹88.98 at ₹6, ₹133.47 at ₹9).
_SECONDS = 890

#: What the engine charged US, deliberately unrelated to either list rate.
_SUPPLIER_COST = "1.9000"


def _debit(rate: Decimal) -> Decimal:
    """What one `_SECONDS` call takes off the wallet at `rate`.

    `billing/rates.prepaid_billed_inr`'s own rule, spelled out rather than called, so this
    asserts the RATE without asserting itself: exact seconds -> minutes, times the rate,
    quantized ONCE at `MONEY_Q` through `ROUNDING` (never the process-global decimal
    context, hard rule 7). Quantizing the MINUTES first is a different and wrong number —
    it gives ₹88.9998 where the ledger holds ₹89.0000.
    """
    return (Decimal(_SECONDS) / 60 * rate).quantize(MONEY_Q, rounding=ROUNDING)


# --- fixture plumbing ------------------------------------------------------------


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


async def _publish(amount: Decimal, *, effective_from: datetime, by: UUID) -> None:
    """A published rate at a CHOSEN instant.

    Raw SQL rather than `record_list_rate`, deliberately: the production writer always
    means "from now" (it runs inside the ops config write it dates) and giving it an
    `effective_from` argument only tests could pass is how a test-only parameter reaches
    production. Dating history is exactly what this test needs and nothing else may do.
    """
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_list_rates (rate_key, effective_from, inr_amount, "
                "recorded_by, source_note) VALUES (:k, :ef, :amt, :by, 'list-rate test')"
            ),
            {"k": SELF_SERVE_PER_MIN, "ef": effective_from, "amt": amount, "by": by},
        )


async def _purge() -> None:
    """Remove every row this suite could have written, as the OWNER — the only role that
    can, because the table is append-only ON PURPOSE.

    `ENABLE TRIGGER` is not the inverse of `DISABLE` (plain ENABLE demotes an
    `ENABLE ALWAYS` trigger to ORIGIN), so each trigger's mode is read first and put back
    verbatim — the trap `platform_secrets_test` documents and `model_pricing_test` reuses.
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
            await conn.execute(
                text("DELETE FROM platform_list_rates WHERE rate_key = :k"),
                {"k": SELF_SERVE_PER_MIN},
            )
            for name, mode in modes:
                verb = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA", "D": "DISABLE"}.get(
                    str(mode), "ENABLE"
                )
                await conn.execute(text(f'ALTER TABLE platform_list_rates {verb} TRIGGER "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    await _purge()


def _this_months_first_instant(now: datetime) -> datetime:
    """The instant the CURRENT IST billing month opened, as UTC.

    Derived from the PREVIOUS month's last instant through the one function that knows when
    an IST month ends, rather than by truncating a UTC date: a UTC month boundary is 05:30
    IST, so a truncated date would put the changeover in the wrong billing month for five
    and a half hours of every month (`late_call_prices_at_its_own_month_test`'s own note).
    """
    month = ist_billing_month(now)
    year, mon = int(month[:4]), int(month[5:])
    previous = f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"
    return ist_month_end(previous) + timedelta(microseconds=1)


async def _priced_history(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, str, datetime]:
    """₹6 for the closed month, ₹9 from this month, and ₹9 live in `Settings`.

    The live setting is the NEW rate on purpose: it is what the unfixed code reads, so every
    assertion built on this fixture fails loudly rather than passing by coincidence.
    """
    admin = await _admin()
    now = datetime.now(UTC)
    changeover = _this_months_first_instant(now)
    ended = changeover - timedelta(hours=6)
    closed_month = ist_billing_month(ended)
    assert closed_month != ist_billing_month(now), "the fixture must straddle the roll"

    # Dated before the closed month opened, so it is the row in force for the whole of it.
    await _publish(_OLD_RATE, effective_from=changeover - timedelta(days=40), by=admin)
    await _publish(_NEW_RATE, effective_from=changeover, by=admin)
    monkeypatch.setattr(get_settings(), "self_serve_inr_per_min", _NEW_RATE)

    tenant_id, agent_id, _ref = await _tenant(f"listrate{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": tenant_id},
        )
    return tenant_id, agent_id, closed_month, ended


# --- the two defect sites --------------------------------------------------------


async def test_a_late_settling_call_is_charged_at_its_own_months_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE PIPELINE HALF. A call that ends in the closed month and meters now must be
    debited at that month's rate.

    Both money writes are asserted, because they are two facts that must agree to the
    paisa: the WALLET (`credit_ledger`, which IS a prepaid client's bill) and
    `spend_state.billed_inr` (the counter the spend cap is judged against). Before the fix
    both read the live setting and came out 50% high on a call whose month had closed.
    """
    tenant_id, agent_id, closed_month, ended = await _priced_history(monkeypatch)
    await _bill(tenant_id, agent_id, seconds=_SECONDS, spend=_SUPPLIER_COST, ended=ended)

    expected = _debit(_OLD_RATE)

    month, _minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    assert month == closed_month, "the call counts into the month it ended in"
    assert billed == expected, (
        f"the counter charged {billed} where the month's own rate makes it {expected} "
        f"(at today's ₹{_NEW_RATE} it would be {_debit(_NEW_RATE)})"
    )

    async with tenant_session(tenant_id) as session:
        debited = (
            await session.execute(
                text(
                    "SELECT -sum(delta) FROM credit_ledger "
                    "WHERE tenant_id = :t AND reason = 'usage'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert debited == expected, "the wallet is a prepaid client's bill and must agree"


async def test_a_closed_months_statement_is_not_repriced_by_a_later_rate_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE STATEMENT HALF, and the client-reachable one (`GET /usage?month=`).

    The month was consumed and paid for out of the wallet at ₹6. Rendering it at ₹9 does
    not merely mis-state a total: it contradicts the debits the same client can read in
    their own credit history, on a screen whose whole purpose is that they can check it.
    """
    tenant_id, agent_id, closed_month, ended = await _priced_history(monkeypatch)
    await _bill(tenant_id, agent_id, seconds=_SECONDS, spend=_SUPPLIER_COST, ended=ended)

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id, month=closed_month)

    minutes = summary["minutes_used"]
    assert minutes == Decimal("14.83"), "the panel's published minute count"
    at_the_old_rate = to_paise(minutes * _OLD_RATE)
    at_todays_rate = to_paise(minutes * _NEW_RATE)
    assert at_the_old_rate != at_todays_rate, "the fixture must be able to tell them apart"

    assert summary["spend_used_inr"] == at_the_old_rate, (
        f"the closed month rendered at {summary['spend_used_inr']}; it was charged at "
        f"{at_the_old_rate} and re-pricing it at today's rate gives {at_todays_rate}"
    )
    assert summary["month_charges_inr"] == at_the_old_rate, "the published total too"


async def test_the_admin_margin_panel_books_the_same_revenue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the client owes and what we book are one number seen from two sides.

    `margin_for_tenant` re-resolves the rate at its own month instant rather than taking
    `usage_summary`'s, so this is the assertion that the two resolutions agree — a margin
    panel reading a closed month at today's rate reports a margin the client never paid.
    """
    tenant_id, agent_id, closed_month, ended = await _priced_history(monkeypatch)
    await _bill(tenant_id, agent_id, seconds=_SECONDS, spend=_SUPPLIER_COST, ended=ended)

    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id, month=closed_month)
        attribution = await period_attribution(session, tenant_id=tenant_id, month=closed_month)

    expected = to_paise(Decimal(str(margin["minutes_used"])) * _OLD_RATE)
    assert margin["revenue_inr"] == expected
    assert attribution.period_charge_inr == expected, (
        "the per-call itemisation divides the same rupees as the statement"
    )


async def test_an_open_month_still_prices_at_the_rate_in_force_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of `month_pricing_instant`, so the fix cannot become a blanket
    'always price at the month end': a call in the OPEN month is charged at today's rate,
    which here is the ₹9 row that came into force when the month turned."""
    tenant_id, agent_id, _closed, _ended = await _priced_history(monkeypatch)
    await _bill(
        tenant_id, agent_id, seconds=_SECONDS, spend=_SUPPLIER_COST, ended=datetime.now(UTC)
    )

    _month, _m, _s, _c, billed = await _spend_state(tenant_id)
    assert billed == _debit(_NEW_RATE)


# --- the store itself ------------------------------------------------------------


async def test_the_resolver_returns_the_row_in_force_and_falls_back_honestly() -> None:
    """Greatest `effective_from <= at`, and the live setting when there is nothing.

    The fallback is a STATED LIMIT, not a backfill: no history was ever recorded, so for a
    month before the first console price change the current rate is the only rate we know
    (hard rule 11). Seeding the beginning of time with today's figure would assert
    something nobody here can.
    """
    admin = await _admin()
    async with untenanted_session() as session:
        assert (
            await self_serve_rate_at(session, at=datetime(2026, 1, 1, tzinfo=UTC))
            == get_settings().self_serve_inr_per_min
        ), "empty table: the live setting, honestly"

    await _publish(_OLD_RATE, effective_from=datetime(2026, 2, 1, tzinfo=UTC), by=admin)
    await _publish(_NEW_RATE, effective_from=datetime(2026, 5, 1, tzinfo=UTC), by=admin)
    async with untenanted_session() as session:
        assert (
            await self_serve_rate_at(session, at=datetime(2026, 1, 31, tzinfo=UTC))
            == get_settings().self_serve_inr_per_min
        ), "before the first row there is still no history to read"
        assert await self_serve_rate_at(session, at=datetime(2026, 2, 1, tzinfo=UTC)) == _OLD_RATE
        assert await self_serve_rate_at(session, at=datetime(2026, 4, 30, tzinfo=UTC)) == _OLD_RATE
        assert await self_serve_rate_at(session, at=datetime(2026, 9, 1, tzinfo=UTC)) == _NEW_RATE


async def test_a_naive_instant_is_refused_rather_than_read_in_local_time() -> None:
    """`effective_from` is `timestamptz`; a naive instant would be read in the process's
    timezone, so a UTC container and an IST laptop would price the same month differently."""
    async with untenanted_session() as session:
        with pytest.raises(ValueError, match="aware instant"):
            await self_serve_rate_at(session, at=datetime(2026, 2, 1))


async def test_a_published_rate_cannot_be_edited_or_deleted() -> None:
    """The append-only boundary at the database (hard rule 4). Editing the row that priced
    a closed month does not change the price going forward — it silently rewrites a
    statement the client has already paid, which is the defect this table exists to end."""
    admin = await _admin()
    await _publish(_OLD_RATE, effective_from=datetime(2026, 2, 1, tzinfo=UTC), by=admin)
    for statement in (
        "UPDATE platform_list_rates SET inr_amount = 99 WHERE rate_key = :k",
        "UPDATE platform_list_rates SET source_note = 'x' WHERE rate_key = :k",
        "DELETE FROM platform_list_rates WHERE rate_key = :k",
    ):
        with pytest.raises(Exception) as raised:
            async with untenanted_session() as session:
                await session.execute(text(statement), {"k": SELF_SERVE_PER_MIN})
        assert "append-only" in str(raised.value), statement


async def test_the_rate_is_platform_state_and_reads_the_same_from_any_tenant_session() -> None:
    """THE HARD-RULE-1 QUESTION, answered for the shape this table actually has.

    There is no `tenant_id` to isolate: one published price for the whole self-serve motion
    at an instant, and a MANAGED client's price is their `plans` row. So the property that
    replaces "a cross-tenant read returns zero rows" is that it is NOT tenant data at all —
    two different tenants' sessions resolve the identical figure, and the table carries no
    column that could ever make them differ. `db/registry.RLS_EXEMPT_TENANT_COLUMNS` is
    where that is registered and reviewed, and `tests/guardrail_audit_test.py` pins it.
    """
    admin = await _admin()
    await _publish(_OLD_RATE, effective_from=datetime(2026, 2, 1, tzinfo=UTC), by=admin)
    at = datetime(2026, 6, 1, tzinfo=UTC)

    async with untenanted_session() as session:
        columns = (
            await session.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'platform_list_rates' AND column_name = 'tenant_id'"
                )
            )
        ).scalar_one()
    assert columns == 0, "a decorative tenant_id would invite a policy that could hide a price"

    first, _a, _r = await _tenant(f"scopea{uuid.uuid4().hex[:6]}")
    second, _b, _r2 = await _tenant(f"scopeb{uuid.uuid4().hex[:6]}")
    async with tenant_session(first) as session:
        one = await self_serve_rate_at(session, at=at)
    async with tenant_session(second) as session:
        two = await self_serve_rate_at(session, at=at)
    assert one == two == _OLD_RATE


# --- the writer ------------------------------------------------------------------


async def test_a_console_price_change_dates_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ops config write records the rate that comes into force, in its own transaction.

    Without this the table would only ever be empty and the fallback would be the whole
    story — a fix that is structurally right and does nothing. The value recorded is the
    PROJECTION rather than `result.new`, which is what makes a REVERT (whose `new` is
    `None`, but which still moves the price) record the figure that takes over.
    """
    admin = await _admin()
    async with untenanted_session() as session:
        await _record_list_rate(
            session,
            WriteResult(key=SELF_SERVE_PER_MIN, old=None, new="7.25", version=1, revision=1),
            actor_id=admin,
            reason="Q3 self-serve price change",
        )
    async with untenanted_session() as session:
        rate = await self_serve_rate_at(session, at=datetime.now(UTC) + timedelta(seconds=1))
    assert rate == Decimal("7.25")

    # A no-op Save records nothing: the history is append-only and cannot be corrected by
    # an edit, so a double-clicked button must not put two price changes into it.
    async with untenanted_session() as session:
        await _record_list_rate(
            session,
            WriteResult(
                key=SELF_SERVE_PER_MIN,
                old="7.25",
                new="7.25",
                version=1,
                revision=1,
                recorded=False,
            ),
            actor_id=admin,
            reason="clicked twice",
        )
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM platform_list_rates WHERE rate_key = :k"),
                {"k": SELF_SERVE_PER_MIN},
            )
        ).scalar_one()
    assert rows == 1

    # Another key's write is not this key's history.
    async with untenanted_session() as session:
        await _record_list_rate(
            session,
            WriteResult(key="db_pool_size", old=None, new="12", version=2, revision=1),
            actor_id=admin,
            reason="not a price",
        )
    async with untenanted_session() as session:
        rows = (
            await session.execute(text("SELECT count(*) FROM platform_list_rates"))
        ).scalar_one()
    assert rows == 1


async def test_the_writer_refuses_to_leave_a_gap_in_the_history() -> None:
    """`record_list_rate` stamps `clock_timestamp()`, so a row is always resolvable from
    the instant it was written — and two rows written in one transaction do not collide on
    the primary key, which `now()` (transaction start time) would."""
    admin = await _admin()
    async with untenanted_session() as session:
        await record_list_rate(
            session,
            rate_key=SELF_SERVE_PER_MIN,
            inr_amount=_OLD_RATE,
            recorded_by=admin,
            note="first",
        )
        await record_list_rate(
            session,
            rate_key=SELF_SERVE_PER_MIN,
            inr_amount=_NEW_RATE,
            recorded_by=admin,
            note="second",
        )
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM platform_list_rates WHERE rate_key = :k"),
                {"k": SELF_SERVE_PER_MIN},
            )
        ).scalar_one()
    assert rows == 2, "clock_timestamp() advances inside a transaction; now() does not"

    async with untenanted_session() as session:
        assert (
            await self_serve_rate_at(
                session, at=month_pricing_instant(ist_billing_month(datetime.now(UTC)))
            )
            == _NEW_RATE
        )
