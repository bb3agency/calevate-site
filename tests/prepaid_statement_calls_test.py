"""A prepaid statement carries the calling the wallet was debited for.

It printed the phone rental (D-665) and nothing for call minutes, so a prepaid client's
statement did not reconcile to the credit their calls drew. What is asserted:

1. each voice and lot rate the month's calls were drawn at is one line, quoting minutes
   and rate, whose amount is the ledger's debit;
2. the call lines sum to `voice_tier_usage(...).total_inr` — the calling the wallet paid;
3. the model upgrade carried on a call's debit is its own line;
4. a managed account gets no such line (its calls take no debit);
5. still a bill of supply when unregistered (D-659): no tax on these lines either.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.billing import service as billing
from apps.api.billing.invoice import build_invoice
from apps.api.billing.lots import CallDemand
from apps.api.billing.service import LotRates, current_billing_month, voice_tier_usage
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.money_walk_test import _metered_call, _tenant

pytestmark = [pytest.mark.rls]

CLEAR = Decimal("5.00")
STUDIO = Decimal("8.00")


async def _charged_call(tenant_id, agent_id, *, minutes: str, voice: str, extra: str = "0") -> None:
    """A call metered in this month and debited from a wallet with no lots, so the whole
    demand is priced at the fallback pair — one split per call, at a known rate."""
    call_id = await _metered_call(
        tenant_id, agent_id, tier=None, seconds=str(Decimal(minutes) * 60)
    )
    async with tenant_session(tenant_id) as session:
        await billing.charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            demand=CallDemand(
                minutes=Decimal(minutes),
                voice_tier=voice,  # type: ignore[arg-type]
                fallback_rates=LotRates(CLEAR, STUDIO),
            ),
            extra_inr=Decimal(extra),
        )


def _call_lines(invoice: dict) -> list[dict]:
    return [i for i in invoice["line_items"] if i["description"].startswith("Call minutes")]


async def test_each_voice_is_a_line_and_the_lines_are_the_debits() -> None:
    tenant_id, agent_id = await _tenant()
    await _charged_call(tenant_id, agent_id, minutes="3", voice="clear")
    await _charged_call(tenant_id, agent_id, minutes="2", voice="clear")
    await _charged_call(tenant_id, agent_id, minutes="4", voice="studio")

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
        drawn = await voice_tier_usage(session, tenant_id=tenant_id, month=current_billing_month())

    clear, studio = _call_lines(invoice)
    assert (clear["qty"], clear["unit_inr"], clear["amount_inr"]) == (
        Decimal("5.00"),
        Decimal("5.00"),
        Decimal("25.00"),
    )
    assert "Clear" in clear["description"] and "₹5.00/min" in clear["description"]
    assert (studio["qty"], studio["unit_inr"], studio["amount_inr"]) == (
        Decimal("4.00"),
        Decimal("8.00"),
        Decimal("32.00"),
    )
    assert sum((line["amount_inr"] for line in (clear, studio)), Decimal("0")) == (
        billing.to_paise(drawn.total_inr)
    ), "the statement must reconcile to the credit the calls drew"


async def test_the_model_upgrade_on_a_call_is_its_own_line() -> None:
    tenant_id, agent_id = await _tenant()
    await _charged_call(tenant_id, agent_id, minutes="2", voice="clear", extra="1.50")

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    upgrade = [i for i in invoice["line_items"] if i["description"] == "AI model upgrade on calls"]
    assert [line["amount_inr"] for line in upgrade] == [Decimal("1.50")]
    assert invoice["subtotal_inr"] == Decimal("11.50")


async def test_the_statement_balances_and_charges_no_tax_when_unregistered() -> None:
    tenant_id, agent_id = await _tenant()
    await _charged_call(tenant_id, agent_id, minutes="3", voice="studio")

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert invoice["subtotal_inr"] == sum(
        (line["amount_inr"] for line in invoice["line_items"]), Decimal("0")
    )
    if invoice["document_type"] == "bill_of_supply":
        assert invoice["gst_inr"] == Decimal("0.00")
        assert invoice["total_inr"] == invoice["subtotal_inr"]


async def test_a_managed_account_gets_no_prepaid_call_line() -> None:
    """Its calls are priced from the plan; a wallet line beside that would bill twice."""
    tenant_id, agent_id = await _tenant()
    await _charged_call(tenant_id, agent_id, minutes="3", voice="clear")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'managed' WHERE id = :t"),
            {"t": tenant_id},
        )
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert _call_lines(invoice) == []


async def test_a_month_with_no_calls_prints_no_call_line() -> None:
    tenant_id, _agent_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert _call_lines(invoice) == []
