"""NO CLOSED MONTH MOVED WHEN THE OVERAGE RUNGS WERE RENAMED (D-558).

The rename that this file guards touched three things at once — the wire's field names,
the plan's second-rate COLUMN, and the constants that name the ledger's rung tokens — and
every one of them sits on a money path that prices months a client has already paid. The
whole change is worthless if any figure moved by a paisa, and "the tests still pass" does
not prove that: the tests moved too.

**HOW THIS PROVES IT.** The figures below are not computed and compared with themselves.
They were MEASURED by running this exact fixture against the code as it stood BEFORE the
rename (9 Sep 2026) and are written here as literals. A change that moves a settled
month's arithmetic fails here even if every other test in the suite is rewritten to agree
with it, because there is nothing here for a rewrite to agree with — only the numbers the
old code produced.

**WHY THIS FIXTURE.** July 2026 is a closed month (`occurred_at` inside its IST window,
and `usage_summary(month=...)` prices it at the month's own instant, so the plan row in
effect then is what quotes it). Three deliberate shapes:

* 601 s on the base rung, 401 s on the second rung, 200 s carrying NO rung at all. The
  odd second counts put a remainder into `allocate_paise` on both the minutes and the
  costs, which is where the D-371 partition bug lived — a rename that dropped a bucket or
  reordered `OVERAGE_RUNGS` moves the spare paisa and this notices.
* A plan that quotes BOTH rates (₹8.00 and ₹5.00). That is the branch `_RUNG_WORDING` and
  the two-line invoice are on and it is the branch no real plan has ever taken, so it is
  the one a test has to take deliberately.
* An included allowance (10 min) small enough that the overage splits across both rungs,
  which exercises `split_overage` spending the allowance on the DEARER rung first.

**AND THE LEDGER TOKEN.** The rows are written with `meta.tts_tier` set to the literal
strings `premium` / `value`, spelled out rather than imported. That is the point: those
are the tokens `usage_events` already holds on every row ever written, `usage_events` is
in `db/registry.APPEND_ONLY_TABLES` with a trigger behind it, and no UPDATE can ever
reach them. If a future change starts stamping a new token and does not keep reading this
one, these rows fall to `unattributed` — where `tier_usage` bills them at the CHEAPER
rung — and the assertions below go red rather than a client's settled invoice going
quietly wrong.

CONCURRENCY: every test mints its own tenant and touches no global row.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.invoice import build_invoice
from apps.api.billing.service import margin_for_tenant, tier_usage, usage_summary
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text

MONTH = "2026-07"
#: Inside July's IST window, and comfortably away from either edge so the month this
#: lands in is not itself the thing under test (`tests/ist_month_boundary_test.py` owns
#: that question).
OCCURRED = "2026-07-15 12:00:00+05:30"

BASE_RATE = Decimal("8.0000")
SECOND_RATE = Decimal("5.0000")

#: seconds of talk time, and the rung token stamped on the row. `None` writes no `meta`
#: at all, which is the pre-attribution row shape still sitting in the archive.
LEDGER_ROWS: tuple[tuple[str | None, int], ...] = (("premium", 601), ("value", 401), (None, 200))

#: ₹ per second, four decimals — `MONEY`'s precision, so each bucket's sum of products
#: carries four decimals and the paise allocation has something to allocate.
UNIT_COST = Decimal("0.0125")


# ═══════════════ THE MEASURED FIGURES — do not "fix" these to match new output ═══════════════
#
# Produced by this fixture against the pre-rename code. Every one of them is exact.

BEFORE_USAGE = {
    "minutes_used": Decimal("20.03"),
    "included_minutes": 10,
    "overage_minutes": Decimal("10.03"),
    "overage_minutes_premium": Decimal("0.02"),
    "overage_minutes_value": Decimal("10.01"),
    "overage_cost_inr": Decimal("50.21"),
    "overage_rate_inr": Decimal("8.00"),
    "overage_rate_value_inr": Decimal("5.00"),
    "month_charges_inr": Decimal("1000.00"),
    "monthly_fee_inr": Decimal("1000.00"),
}

BEFORE_TIERS = {
    "minutes_premium": Decimal("10.02"),
    "minutes_value": Decimal("6.68"),
    "minutes_unattributed": Decimal("3.33"),
    "minutes_billable_premium": Decimal("10.02"),
    "minutes_billable_value": Decimal("10.01"),
    "cost_premium_inr": Decimal("7.52"),
    "cost_value_inr": Decimal("5.01"),
    "cost_unattributed_inr": Decimal("2.50"),
}

BEFORE_MARGIN = {
    "cost_inr": Decimal("15.03"),
    "revenue_inr": Decimal("1000.00"),
    "margin_inr": Decimal("984.97"),
    "margin_pct": Decimal("98.5"),
}

#: The statement, line for line. The invoice NUMBER is deliberately absent: it is a digest
#: of the tenant id and this fixture mints a new tenant per run, which is `_tenant_serial_
#: suffix`'s own design and not something a rename could move.
BEFORE_INVOICE_LINES = (
    ("Monthly plan fee", Decimal("1"), Decimal("1000.00"), Decimal("1000.00")),
    (
        "Extra calling minutes, base rate (0.02 min at ₹8.00/min)",
        Decimal("0.02"),
        Decimal("8.00"),
        Decimal("0.16"),
    ),
    (
        "Extra calling minutes, second rate (10.01 min at ₹5.00/min)",
        Decimal("10.01"),
        Decimal("5.00"),
        Decimal("50.05"),
    ),
)
BEFORE_INVOICE_SUBTOTAL = Decimal("1050.21")
BEFORE_INVOICE_TOTAL = Decimal("1050.21")


# ─────────────────────────────────── the fixture ───────────────────────────────────


async def _settled_month(*, second_rate_column: str) -> UUID:
    """A tenant whose July 2026 is closed and priced on both rungs.

    `second_rate_column` is which of the two `plans` columns the fixture writes the second
    rate into — the WHOLE POINT of the deprecation being that both must price identically.
    It is one of two names typed in this file (never a caller's string): a `plans` column
    name reaching SQL from anywhere else would be the injection `scripts/check_raw_sql.py`
    exists for, even in a test.
    """
    assert second_rate_column in ("overage_rate_second", "overage_rate_value")
    created = await admin_service.create_organization(
        name="Settled Month Clinic",
        slug=f"settled-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                f"{second_rate_column}, concurrency_ceiling, effective_from, created_at, "
                "updated_at) VALUES (:i, :t, 1000.00, 10, :rate, :second, 10, "
                "'2026-06-01 00:00:00+05:30', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "rate": BASE_RATE, "second": SECOND_RATE},
        )
        agent_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, status, "
                "engine, created_at, updated_at) VALUES (:a, :t, 'Settled', 'outbound', 'Idi AI "
                "assistant.', 'Idi AI assistant.', 'This call is being recorded.', 'I keep a "
                "short note of what you ask about.', 'live', 'fake', now(), now())"
            ),
            {"a": agent_id, "t": tenant_id},
        )
        for rung, seconds in LEDGER_ROWS:
            call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                    "'outbound', '+919876500001', 'completed', now(), now())"
                ),
                {
                    "i": call_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"exec_{uuid.uuid4().hex[:12]}",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                    "'telephony_s', :qty, :cost, :occ, CAST(:meta AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "qty": seconds,
                    "cost": UNIT_COST,
                    "occ": OCCURRED,
                    "meta": None if rung is None else f'{{"tts_tier": "{rung}"}}',
                },
            )
    return tenant_id


async def _read(tenant_id: UUID) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        return (
            await usage_summary(session, tenant_id=tenant_id, month=MONTH),
            await tier_usage(session, tenant_id=tenant_id, month=MONTH),
            await margin_for_tenant(session, tenant_id=tenant_id, month=MONTH),
        )


def _assert_exact(actual: object, expected: Decimal, where: str) -> None:
    """Decimal identity, not `==` on a float and not `pytest.approx`.

    `Decimal("50.21") == 50.21` is False and `Decimal("50.2100") == Decimal("50.21")` is
    True, so the type is asserted first: a figure that arrived as a float has already lost
    the property hard rule 7 is about, whatever it compares equal to.
    """
    assert isinstance(actual, Decimal), f"{where} is {type(actual).__name__}, not Decimal"
    assert actual == expected, f"{where} moved: {expected} before, {actual} now"


# ═══════════════════════════ 1. THE CLOSED MONTH DID NOT MOVE ═══════════════════════════


@pytest.mark.parametrize("column", ["overage_rate_second", "overage_rate_value"])
async def test_a_settled_months_figures_are_identical_to_the_paisa(column: str) -> None:
    """THE HEADLINE. Every published figure of a closed month, against the pre-rename run.

    Run twice: once on a plan row written into the NEW column and once into the one it
    deprecates. Both must produce the same month, which is what makes the two-step safe —
    a plan row written by a process that has not been redeployed prices exactly as one
    written by a process that has.
    """
    tenant_id = await _settled_month(second_rate_column=column)
    usage, tiers, margin = await _read(tenant_id)

    assert usage["month"] == MONTH
    assert usage["calls"] == 3
    assert usage["included_minutes"] == BEFORE_USAGE["included_minutes"]
    for field in (
        "minutes_used",
        "overage_minutes",
        "overage_minutes_premium",
        "overage_minutes_value",
        "overage_cost_inr",
        "overage_rate_inr",
        "overage_rate_value_inr",
        "month_charges_inr",
        "monthly_fee_inr",
    ):
        _assert_exact(usage[field], BEFORE_USAGE[field], f"usage_summary[{field!r}]")

    for field, expected in BEFORE_TIERS.items():
        _assert_exact(tiers[field], expected, f"tier_usage[{field!r}]")

    for field, expected in BEFORE_MARGIN.items():
        _assert_exact(margin[field], expected, f"margin_for_tenant[{field!r}]")


@pytest.mark.parametrize("column", ["overage_rate_second", "overage_rate_value"])
async def test_the_statement_prints_the_same_lines_it_printed_before(column: str) -> None:
    """The client's own document, line for line and rupee for rupee.

    Checked separately from the panel because it is the artefact a client KEEPS: a figure
    that moved here is a statement that disagrees with the one already in their inbox.
    """
    tenant_id = await _settled_month(second_rate_column=column)
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id, month=MONTH)

    printed = tuple(
        (line["description"], line["qty"], line["unit_inr"], line["amount_inr"])
        for line in invoice["line_items"]
    )
    assert printed == BEFORE_INVOICE_LINES
    _assert_exact(invoice["subtotal_inr"], BEFORE_INVOICE_SUBTOTAL, "invoice subtotal")
    _assert_exact(invoice["total_inr"], BEFORE_INVOICE_TOTAL, "invoice total")


# ═════════════════ 2. THE NEW WIRE NAMES ARE THE OLD FIGURES, NOT NEW ONES ═════════════════


async def test_both_spellings_of_every_renamed_field_carry_one_figure() -> None:
    """Step 1 of the two-step: the pair is emitted, and it is the SAME number twice.

    A deprecation that published two figures under two names would be worse than the name
    it fixed — two readers of one month, which is the one thing two readers of the same
    money may never be.
    """
    tenant_id = await _settled_month(second_rate_column="overage_rate_second")
    usage, tiers, _ = await _read(tenant_id)

    for new, old in (
        ("overage_minutes_base_rung", "overage_minutes_premium"),
        ("overage_minutes_second_rung", "overage_minutes_value"),
        ("overage_rate_second_inr", "overage_rate_value_inr"),
    ):
        assert usage[new] == usage[old], f"usage_summary disagrees about {new} / {old}"

    for new, old in (
        ("minutes_base_rung", "minutes_premium"),
        ("minutes_second_rung", "minutes_value"),
        ("minutes_billable_base_rung", "minutes_billable_premium"),
        ("minutes_billable_second_rung", "minutes_billable_value"),
        ("cost_base_rung_inr", "cost_premium_inr"),
        ("cost_second_rung_inr", "cost_value_inr"),
    ):
        assert tiers[new] == tiers[old], f"tier_usage disagrees about {new} / {old}"


async def test_the_old_wire_names_are_still_emitted() -> None:
    """WHAT FAILS IF SOMEBODY FINISHES STEP 2 EARLY.

    Deleting the old names is a whole release away (hard rule 8): a console bundle one
    deploy behind reads them, and a bundle is not redeployed in the same instant the API
    is. This test is the thing that says so out loud.
    """
    tenant_id = await _settled_month(second_rate_column="overage_rate_second")
    usage, tiers, _ = await _read(tenant_id)
    for field in ("overage_minutes_premium", "overage_minutes_value", "overage_rate_value_inr"):
        assert field in usage, f"the wire lost the deprecated {field} before its release"
    for field in (
        "minutes_premium",
        "minutes_value",
        "minutes_billable_premium",
        "minutes_billable_value",
        "cost_premium_inr",
        "cost_value_inr",
    ):
        assert field in tiers, f"the wire lost the deprecated {field} before its release"


# ══════════════════ 3. THE LEDGER TOKENS ARE FROZEN, AND HERE IS WHY ══════════════════


def test_the_rung_tokens_are_the_literal_strings_the_archive_already_holds() -> None:
    """THE ONE ASSERTION THAT MAY NOT BE "FIXED" BY EDITING IT.

    `usage_events` is in `apps/api/db/registry.APPEND_ONLY_TABLES` and a database trigger
    enforces it, so every row ever metered carries `meta.tts_tier = "premium"` and no
    UPDATE can reach it — not a backfill, not a migration, not a correction. A change that
    starts stamping a different token therefore does not RENAME anything: it creates a
    second vocabulary that the first can never join, and every reader of a money figure
    owes both of them forever.

    What happens if one reader forgets is not an exception. `_tier_totals` files an
    unrecognised token as `UNATTRIBUTED_RUNG`, `tier_usage` bills unattributed minutes at
    the CHEAPER rung, and `split_overage` spends the included allowance on the dearer one
    first — so every closed month silently re-prices, downwards, in a direction that looks
    like generosity rather than like a bug. That is why the tokens are frozen and the
    CONSTANTS carry the meaning instead.

    Spelled as literals here on purpose. `assert BASE_OVERAGE_RUNG == BASE_OVERAGE_RUNG`
    is what an assertion against the constant would amount to.
    """
    from apps.api.billing import service as billing
    from apps.api.db.registry import APPEND_ONLY_TABLES

    assert "usage_events" in APPEND_ONLY_TABLES, (
        "the whole argument for freezing these tokens is that the rows holding them "
        "cannot be rewritten — if `usage_events` is no longer append-only, that argument "
        "needs re-making before this test is changed"
    )
    assert billing.LEDGER_RUNG_KEY == "tts_tier"
    assert billing.BASE_OVERAGE_RUNG == "premium"
    assert billing.SECOND_OVERAGE_RUNG == "value"
    assert billing.UNATTRIBUTED_RUNG == ""
    assert billing.OVERAGE_RUNGS == ("premium", "value", "")


def test_the_reader_reads_the_key_the_meter_writes() -> None:
    """The writer and the reader are one constant apart, and the SQL proves it.

    They live in two applications — `apps/workers/pipeline.py` stamps the row, `apps/api/
    billing/service.py` groups a month by it — and a key that drifted between them would
    not raise anywhere: the reader would simply find nothing and file every minute as
    unattributed.
    """
    from apps.api.billing import service as billing

    assert billing._ROW_TIER_SQL == "COALESCE(meta->>'tts_tier', '')"


def test_the_meter_stamps_the_frozen_key_and_the_base_rung() -> None:
    """The WRITE side, read off the pipeline's source.

    `tests/tts_tier_metering_test.py` already meters a real call and reads the row back;
    this asserts the narrower thing that test cannot — that the two names the pipeline
    writes with are the module constants and not a pair of literals somebody could edit
    independently of the reader.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "apps/workers/pipeline.py").read_text(
        encoding="utf-8"
    )
    assert "LEDGER_RUNG_KEY: BASE_OVERAGE_RUNG," in source, (
        "the post-call meter no longer stamps the rung through the two constants — a "
        "literal here can drift from `_ROW_TIER_SQL` with nothing to notice"
    )
