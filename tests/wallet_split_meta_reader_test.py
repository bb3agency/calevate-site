"""A LEDGER ROW THIS BUILD CANNOT READ RENDERS AS NO SPLITS — never as SOME of them.

`meta` is JSONB on an append-only table, so `credit_ledger` holds rows written by every
earlier build of this product: rows from before lots existed, rows from before
`split_meta`'s spelling settled. `wallet_routes._splits_of` is what stands between those
rows and a client's own statement, and it has exactly one rule — what cannot be read as a
list of string-valued objects is reported as NO splits.

WHY THE WHOLE LIST GOES AND NOT JUST THE BAD ITEM. A statement that renders three of a
row's four splits is a statement whose "where did this ₹412 go" answer is quietly wrong,
and nothing on the screen says so: the total still comes from the row's own `delta`, so the
attribution silently stops adding up to it (invariant §2.3.5). Dropping the set makes the
row render as "no attribution recorded", which is TRUE of a row this build cannot read.
Half of it is the failure mode this function exists to prevent, so it is the one asserted
here.

Run: uv run pytest -q tests/wallet_split_meta_reader_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import record_entry
from apps.api.billing.wallet_routes import read_wallet_ledger
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session
from sqlalchemy import text

_GOOD_SPLIT = {
    "kind": "call",
    "credits": "50.0000",
    "lot_id": "01912f1e-0000-7000-8000-000000000001",
    "minutes": "10.00",
    "inr_per_min": "5.0000",
    "voice_tier": "sarvam",
}


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Splits Clinic",
        slug=f"splits-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    return tenant_id


def _owner(tenant_id: uuid.UUID) -> Principal:
    return Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


async def _usage(tenant_id: uuid.UUID, *, ref: str, lots: Any) -> None:
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-50.0000"),
            reason="usage",
            ref=ref,
            meta={"lots": lots},
            allow_negative=True,
        )


@pytest.mark.parametrize(
    ("label", "lots"),
    [
        # The shape a row written before `split_meta` existed can carry: a list of
        # something that is not an object at all.
        ("a bare string beside a good split", [_GOOD_SPLIT, "carried over from the old build"]),
        ("a nested list", [[_GOOD_SPLIT]]),
        ("a null in the list", [_GOOD_SPLIT, None]),
    ],
)
async def test_one_unreadable_item_drops_the_whole_set_rather_than_half_rendering_it(
    label: str, lots: Any
) -> None:
    tenant_id = await _tenant()
    ref = f"call:mixed-{uuid.uuid4().hex[:8]}"
    await _usage(tenant_id, ref=ref, lots=lots)

    body = await read_wallet_ledger(_owner(tenant_id))
    (entry,) = [row for row in body.entries if row.ref == ref]

    assert entry.lots == [], f"{label}: a partially readable set is reported as none of it"
    # The ROW still renders, and still carries the money. Refusing the splits must never
    # become refusing the statement — this is a client-reachable read.
    assert entry.delta_inr == Decimal("-50.00")
    assert entry.reason == "usage"


async def test_a_row_this_build_did_write_still_renders_every_split() -> None:
    """The neighbour that keeps the test above honest: `_splits_of` returning `[]` for
    everything would satisfy it and blank the panel on every real row."""
    tenant_id = await _tenant()
    ref = f"call:good-{uuid.uuid4().hex[:8]}"
    await _usage(tenant_id, ref=ref, lots=[_GOOD_SPLIT])

    body = await read_wallet_ledger(_owner(tenant_id))
    (entry,) = [row for row in body.entries if row.ref == ref]

    assert entry.lots == [_GOOD_SPLIT]
    assert all(isinstance(value, str) for value in entry.lots[0].values()), (
        "every value crosses the wire as a string, never as a JSON number (hard rule 7)"
    )


async def test_a_row_whose_lots_key_is_not_a_list_at_all_renders_no_splits() -> None:
    """The outer guard, and the shape a row from before lots existed actually has: no
    `meta.lots` key at all, which reads back as SQL NULL rather than as a list."""
    tenant_id = await _tenant()
    ref = f"call:legacy-{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-50.0000"),
            reason="usage",
            ref=ref,
            meta={"note": "written before lots existed"},
            allow_negative=True,
        )
        stored = (
            await session.execute(
                text("SELECT meta->'lots' FROM credit_ledger WHERE tenant_id = :t AND ref = :r"),
                {"t": tenant_id, "r": ref},
            )
        ).scalar_one()
    assert stored is None

    body = await read_wallet_ledger(_owner(tenant_id))
    (entry,) = [row for row in body.entries if row.ref == ref]
    assert entry.lots == []
