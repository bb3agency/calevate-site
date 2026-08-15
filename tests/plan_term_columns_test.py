"""Every agreed column on `plans` is classified, and the classification is used.

THE DEFECT. `billing/terms.py::TERM_COLUMNS` is the list the SELECT, the INSERT and the
change-detection equality all read, and it grew `overage_rate_value` when D-36's second
TTS rung landed (migration b1d5c8e73f04). `PlanRecord.states_pricing` — the predicate
that decides whether an account HAS a price — carried its own hand-written copy of the
four price columns and did not grow with it.

So a plan quoting only the value-tier rate, which is exactly the row a founder writes the
day that price is decided, answered `states_pricing = False`. `read_terms` filed it as
`unpriced`, and the console renders that state as **"No price agreed … They are still
invoiced nothing"** — over a plan that `usage_summary` bills at ₹5.50 a minute. A screen
telling an operator a paying account is unbilled is the most expensive direction this
class of drift runs in, and it is the same direction D-102 found: the thing was BUILT and
the claim said missing.

The fix is not "add the column to the second list". It is that there is no second list —
`states_pricing` reads `PRICING_COLUMNS` — and that a column belonging to NEITHER kind
fails here rather than shipping.

WHAT THIS PINS, AND WHY EACH HALF IS NEEDED
---------------------------------------------
1. **The partition.** `PRICING_COLUMNS` and `CEILING_COLUMNS` must be disjoint and must
   together be exactly `TERM_COLUMNS`. Adding a column to the terms without saying which
   kind it is fails here — which is the moment the author is thinking about it.
2. **The reader uses it.** `states_pricing` must answer True for a plan carrying ONLY
   that column and nothing else, for every pricing column. A classification nothing reads
   is the same defect one layer along.
3. **The table is covered.** Every column of `plans` is either an agreed term, a client
   cap, part of the valid-time window, or bookkeeping. A NEW money column on the table
   that `terms.py` never learned about is a term an operator cannot set and an invoice
   may still price — so the leftover set is asserted by equality, not by exclusion.
4. **Reading a row is by name.** `_ROW_COLUMNS` interpolates `TERM_COLUMNS`, so a ninth
   agreed column shifts every positional index after it. `_record` used to read
   `values[9]` for `client_cap_min`; the same growth this file is designed to encourage
   would have made it read a rupee ceiling into a minute count with no error anywhere.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from apps.api.billing.models import Plan
from apps.api.billing.terms import (
    CEILING_COLUMNS,
    PRICING_COLUMNS,
    TERM_COLUMNS,
    CommercialTerms,
    PlanRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TERMS_MODULE = REPO_ROOT / "apps/api/billing/terms.py"

#: Columns of `plans` that are NOT terms an operator agrees, and why each one is not.
#: An equality assertion below, so a column added to the table lands in exactly one of
#: two places: `TERM_COLUMNS` (classified as price or ceiling) or here, with a reason.
NOT_AGREED_TERMS: dict[str, str] = {
    "id": "the row's identity",
    "tenant_id": "whose plan it is",
    "client_cap_min": "the CLIENT's own stop button — billing/caps.py owns it, and a new "
    "agreement deliberately does not inherit it",
    "client_cap_spend": "as client_cap_min",
    "effective_from": "valid time, not a term (billing/plans.py)",
    "effective_to": "valid time, not a term",
    "created_at": "bookkeeping",
    "updated_at": "bookkeeping",
}

#: A value of the right shape for each pricing column, so the reader can be exercised one
#: column at a time. `included_min` is an `int` and the money columns are `Decimal`;
#: nothing here is a float (hard rule 7).
ONE_VALUE_EACH: dict[str, Any] = {
    "setup_fee": Decimal("15000.0000"),
    "monthly_fee": Decimal("9999.0000"),
    "included_min": 500,
    "overage_rate": Decimal("8.0000"),
    "overage_rate_value": Decimal("5.5000"),
}


def _terms_source() -> ast.Module:
    return ast.parse(TERMS_MODULE.read_text(encoding="utf-8"), filename=str(TERMS_MODULE))


def test_every_agreed_column_is_classified_as_a_price_or_a_ceiling() -> None:
    """The partition. Disjoint, exhaustive, and in the order the SQL builds — the
    concatenation IS `TERM_COLUMNS`, so `_ROW_COLUMNS` and `_INSERT` cannot be reading a
    list that says something different from the one `states_pricing` reads."""
    overlap = set(PRICING_COLUMNS) & set(CEILING_COLUMNS)
    assert not overlap, f"{sorted(overlap)} is claimed as both a price and a ceiling"
    assert PRICING_COLUMNS + CEILING_COLUMNS == TERM_COLUMNS, (
        "TERM_COLUMNS is no longer the concatenation of the two kinds — a column belongs "
        "to neither, or the SQL's column order has quietly moved"
    )


def test_a_plan_quoting_only_one_price_column_states_a_price() -> None:
    """The reader, one column at a time. `overage_rate_value` is the entry that was
    missing, and the loop is what stops the NEXT one being missed: a pricing column added
    without `states_pricing` learning to read it fails here."""
    for column, value in ONE_VALUE_EACH.items():
        record = PlanRecord(
            id=_any_uuid(),
            terms=CommercialTerms(**{column: value}),
            client_cap_min=None,
            client_cap_spend=None,
            created_at=_any_instant(),
        )
        assert record.states_pricing, (
            f"a plan quoting only {column!r} reports as stating no price, so the console "
            "tells an operator the account is invoiced nothing while billing charges it"
        )
    assert set(ONE_VALUE_EACH) == set(PRICING_COLUMNS), (
        "a pricing column has no sample value here, so the loop above is not exercising "
        "it — add one rather than trusting the four that were already covered"
    )


def test_a_ceiling_alone_is_not_a_price() -> None:
    """The other direction, which is the reason the split exists at all.
    `apply_client_caps` mints a row carrying nothing but a cap, and an operator screen
    that counted it as terms would report a tenant as priced when nobody had priced
    them."""
    ceilings: dict[str, Any] = {
        "hard_cap_min": 1000,
        "hard_cap_spend": Decimal("5000.0000"),
        "concurrency_ceiling": 10,
    }
    assert set(ceilings) == set(CEILING_COLUMNS), "every ceiling column is exercised"
    for column, value in ceilings.items():
        record = PlanRecord(
            id=_any_uuid(),
            terms=CommercialTerms(**{column: value}),
            client_cap_min=None,
            client_cap_spend=None,
            created_at=_any_instant(),
        )
        assert not record.states_pricing, f"{column!r} is a ceiling and is not a price"


def test_the_plans_table_holds_no_column_terms_py_has_never_heard_of() -> None:
    """Coverage of the TABLE, by equality rather than by exclusion.

    A money column added to `plans` that `TERM_COLUMNS` does not carry is a term no
    operator can set through the only writer this product has — and one an invoice may
    still price, because `usage_summary` reads `plans` directly.
    """
    columns = {column.name for column in Plan.__table__.columns}
    assert columns - set(TERM_COLUMNS) == set(NOT_AGREED_TERMS), (
        "the `plans` table and billing/terms.py disagree about which columns are agreed "
        "terms. Add the column to PRICING_COLUMNS or CEILING_COLUMNS, or to "
        "NOT_AGREED_TERMS with the reason it is not something an operator agrees."
    )
    assert set(TERM_COLUMNS) <= columns, (
        f"TERM_COLUMNS names {sorted(set(TERM_COLUMNS) - columns)}, which `plans` does not "
        "have — the INSERT would fail at runtime"
    )


def test_a_plan_row_is_read_by_name_and_never_by_position() -> None:
    """The trap this file would otherwise set. `_ROW_COLUMNS` interpolates
    `TERM_COLUMNS`, so encouraging that list to grow means every positional read after it
    silently shifts — a rupee ceiling landing in a minute count, with no exception and no
    failing test. Asserted on the AST rather than on behaviour, because the behavioural
    symptom only appears on the commit that adds the column."""
    function = next(
        node
        for node in ast.walk(_terms_source())
        if isinstance(node, ast.FunctionDef) and node.name == "_record"
    )
    positional = [
        ast.unparse(node)
        for node in ast.walk(function)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, int)
    ]
    assert not positional, (
        f"_record reads a plan row positionally ({positional}); TERM_COLUMNS is meant to "
        "grow, and every index after the inserted column moves. Read `values._mapping` "
        "by column name."
    )


def _any_uuid() -> UUID:
    """A fixture id. `PlanRecord` requires one; no assertion here reads it."""
    return uuid4()


def _any_instant() -> datetime:
    """As above, for `created_at` — aware, because this repo has no naive instants."""
    return datetime.now(UTC)
