"""A month's calling total may not quietly LOSE a wallet debit it cannot classify.

THE DEFECT, found 19 Sep 2026. `billing/service.voice_tier_usage` read the month's `call`
splits out of `credit_ledger.meta.lots` — the rupees the wallet was actually debited — and
then composed its answer with a comprehension over `VOICE_TIER_LABELS`:

    by_voice={tier: found.get(tier, ZERO) for tier in VOICE_TIER_LABELS}

Every split naming a rung outside that mapping was therefore DISCARDED. Not reported, not
raised — dropped, from a figure that is not a display nicety: `LotCharges.total_inr` sums
`by_voice`, and `calling_revenue_inr` returns `total_inr` verbatim for every prepaid
tenant. So the money went missing from the client's "this month" total, from the admin
margin board's revenue, and from the base `billing/attribution` measures its residual
against, all three at once, while the append-only ledger behind them said otherwise.

WHY SUCH A ROW IS REACHABLE AT ALL, AND WHY THE ANSWER IS TWO ANSWERS. The rungs were
spelled `sarvam` / `cartesia` until D-630 renamed them to `clear` / `studio` on
19 Sep 2026. `meta.lots` is history on a ledger whose rows cannot be rewritten (hard
rule 4), so a debit written the day before carries the old spelling for ever. That rupee is
NOT unreadable — the rung still exists under a new name — so it is FOLDED onto it through
`rates.stored_voice_tier`, the one place this tree writes the historical spellings down. A
token that names no rung at all is a different case and RAISES, because the alternative is
a statement that disagrees with the ledger it is derived from and says nothing about it.

(Nothing has been sold yet — migration `f1c40d8b6e93` refuses to run against a non-empty
`credit_lots` and it ran — so no production row holds an old spelling today. The hole
predates the rename and outlives it: the next rung added or renamed re-opens it.)

SABOTAGE-VERIFIED, both halves. Restoring the comprehension makes the fold clause read
₹60.00 where ₹180.00 was debited; removing the `is None` raise makes the unknown-token
clause pass with a silently short total.

Run: uv run pytest -q tests/billing_voice_split_totality_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing import service as billing
from apps.api.billing.service import current_billing_month, record_entry
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.credit_lots_helpers import credit_entry, make_tenant


async def _prepaid(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": tenant_id},
        )


async def _metered_call(session: AsyncSession, *, tenant_id: UUID, minutes: Decimal) -> UUID:
    """A completed call and its `usage_events` row.

    The usage row is load-bearing rather than decoration: `service._CALL_IN_MONTH` windows a
    debit on the CALL's instant, taken from the usage rows the same call wrote, because a
    late-settling call's ledger row lands in the next month. Without it the debit below is
    outside every month and the reader would answer zero for the right reason, which would
    make this file pass while proving nothing.
    """
    call_id = uuid.uuid4()
    agent_id = (
        await session.execute(
            text("SELECT id FROM agents WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
            "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
            "'+919876500002', 'completed', now(), now())"
        ),
        {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
    )
    await session.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
            "unit_cost_paid, occurred_at, meta, created_at) VALUES (gen_random_uuid(), :tid, "
            ":cid, 'telephony_s', :qty, '0.0100', now(), CAST(:meta AS jsonb), now())"
        ),
        {
            "tid": tenant_id,
            "cid": call_id,
            "qty": minutes * 60,
            "meta": '{"tts_tier": "premium"}',
        },
    )
    return call_id


async def _debit_at_rungs(*debits: tuple[str, str, str]) -> UUID:
    """A prepaid tenant whose month holds one call debit per `(rung, rupees, minutes)`.

    The splits are written by hand rather than through `lots.consume`, and they have to be:
    `CallDemand.voice_tier` is a `VoiceTier`, so the live write path cannot PRODUCE a rung
    outside the Literal. What can produce one is history — a row an earlier build wrote
    before D-630 — and history is what arrives through this table, not through that type.
    """
    tenant_id = await make_tenant(prefix="rung")
    await _prepaid(tenant_id)
    await credit_entry(tenant_id, amount="10000.00")
    async with tenant_session(tenant_id) as session:
        for rung, rupees, minutes in debits:
            call_id = await _metered_call(session, tenant_id=tenant_id, minutes=Decimal(minutes))
            await record_entry(
                session,
                tenant_id=tenant_id,
                delta=-Decimal(rupees),
                reason="usage",
                ref=str(call_id),
                # Digit STRINGS and an absent-key discipline, the shape `lots.split_meta`
                # writes — see hard rule 7: a rupee amount that crosses JSONB as a NUMBER
                # comes back a binary float in whichever reader deserialises it next.
                meta={
                    "lots": [
                        {
                            "kind": "call",
                            "credits": rupees,
                            "minutes": minutes,
                            "inr_per_min": "6.00",
                            "voice_tier": rung,
                        }
                    ]
                },
            )
    return tenant_id


async def _retire(tenant_id: UUID) -> None:
    """Take the REFUSING fixture's tenant out of the fleet directory before the suite ends.

    ⚠ **NOT TIDINESS — IT IS CONTAINMENT, AND THE THING IT CONTAINS IS A REAL FINDING.**
    The debit cannot be deleted: `credit_ledger` is append-only and a database trigger
    refuses a DELETE (hard rule 4), so once this row exists it exists for the life of the
    database. And `billing/spend_routes.fleet_spend` walks EVERY organisation with
    `deleted_at IS NULL` and a live status, calling `margin_for_tenant` — hence
    `usage_summary`, hence `voice_tier_usage` — on each, with no per-tenant isolation. So
    one tenant this build cannot price takes the WHOLE admin money board to a 500, for every
    other client on it. Measured, not reasoned: leaving this fixture live turned
    `tests/spend_attribution_test.py::test_the_fleet_board_sums_the_clients_it_walked` red
    with exactly that 500, in a shared development database, two files later.

    That fragility is `fleet_spend`'s to fix — a tenant whose figures cannot be derived
    belongs on the board as a NAMED error row, not as the reason nobody can open it — and it
    is reported rather than fixed here. Meanwhile this suite may not leave a landmine for
    every other file that runs after it, so the fixture is retired as a churned client is.

    The FOLD fixture below needs none of this: its rupees resolve, so it is an ordinary
    tenant with an ordinary month.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :i"), {"i": tenant_id}
        )


async def test_a_rung_renamed_since_the_debit_is_folded_onto_its_new_name() -> None:
    """THE CASE THAT ACTUALLY HAPPENS. ₹120.00 was taken off this wallet on a rung spelled
    the way it was spelled before D-630, and another ₹60.00 on the same rung under today's
    name — a month straddling the rename, which is the month the rename created.

    The old reader answered ₹60.00 and dropped the rest; nothing raised, and the client's
    panel, the margin board and the attribution residual all took the short figure. The two
    spellings are ONE rung, so they ADD: a reader that let the later one win would be a
    different wrong answer, which is why the fold is `+=` and not an assignment.
    """
    tenant_id = await _debit_at_rungs(
        ("sarvam", "120.00", "20.0000"), ("clear", "60.00", "10.0000")
    )
    async with tenant_session(tenant_id) as session:
        charges = await billing.voice_tier_usage(
            session, tenant_id=tenant_id, month=current_billing_month()
        )
    assert charges.by_voice["clear"].charged_inr == Decimal("180.00")
    assert charges.by_voice["clear"].minutes == Decimal("30.0000")
    # The rung this client did not use is PRESENT at zero rather than absent: a panel that
    # omitted it would make "we never used Studio" and "the field did not load" one screen.
    assert charges.by_voice["studio"].charged_inr == Decimal("0")
    # `total_inr` IS `calling_revenue_inr` for a prepaid tenant, which is the number the
    # dropped split used to be missing from.
    assert charges.total_inr == Decimal("180.00")


async def test_a_token_that_names_no_rung_refuses_rather_than_vanishing() -> None:
    """The other half of the reader's contract, and the reason `stored_voice_tier` answers
    `None` instead of guessing.

    A token this build cannot place on ANY rung is not a rename — it is money on a client's
    ledger that this code cannot attribute, and answering a total short by exactly that
    amount is the failure this whole file is about. The refusal names the token, because an
    operator meeting it has to know which spelling the ledger holds before they can decide
    whether to teach the build about it or to correct the row.
    """
    tenant_id = await _debit_at_rungs(("bulbul", "120.00", "20.0000"))
    try:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ValueError, match="bulbul"):
                await billing.voice_tier_usage(
                    session, tenant_id=tenant_id, month=current_billing_month()
                )
    finally:
        await _retire(tenant_id)
