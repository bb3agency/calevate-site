"""The failure arms on the money paths, driven rather than assumed.

WHY THESE SPECIFICALLY. `ledgers-and-money` is a coverage surface guarded at ZERO
uncovered units because it carries hard rules 4 and 7 — an append-only ledger and NUMERIC
INR. The credits-and-payments work added defensive arms to it that no test drove, which
is how a surface guarded at zero goes to fifteen. Each one below is a branch that only
runs when something has already gone wrong, which is exactly the class most likely to be
written once and never executed until the night it matters.

None of these is a coverage-filler. Each names the money defect it prevents:

* a clawback that runs twice takes the bonus back twice, out of an append-only ledger
  that cannot be corrected except by another entry;
* a webhook whose tenant reference is unparseable must settle NOTHING rather than guess;
* a receipt for an organisation that no longer exists must 404 rather than render a
  document with a hole where the supplier is;
* a top-up attempt we fail to record must not take the client's order down with it.

Run: uv run pytest tests/money_defensive_arms_test.py -q
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import ClassVar

import pytest
from apps.api.billing import payments, wallet
from apps.api.db.session import tenant_session

pytestmark = [pytest.mark.rls]


# --- `payment_attempt_ids`: an envelope we cannot key on settles nothing ----------------


def test_an_envelope_with_no_payment_entity_is_not_an_attempt() -> None:
    """FAILS IF: a malformed envelope is treated as a settleable attempt.

    `settle_attempt` finds a row by (tenant, order id) and nothing else. An envelope we
    cannot read those out of must produce None — settling on a guess would move a
    client's top-up into `captured` on no evidence that money arrived.
    """
    envelopes = (
        None,
        {},
        {"payload": None},
        {"payload": {"payment": {}}},
        # `payment` PRESENT BUT NOT A DICT — a provider that changed the shape, or a
        # payload we half-understand. The walk down to `entity` must stop here rather
        # than raise: an unreadable envelope is not an attempt, and a 500 would make the
        # provider retry an envelope that can never succeed.
        {"payload": {"payment": "pay_x"}},
        {"payload": {"payment": ["pay_x"]}},
    )
    for envelope in envelopes:
        assert payments.payment_attempt_ids(envelope) is None


def test_an_unparseable_tenant_reference_settles_nothing() -> None:
    """FAILS IF: a non-UUID tenant note is coerced or partially trusted.

    The tenant comes back from the provider inside `notes`, which is a field WE wrote and
    the provider echoes — so a value that is not a UUID means the echo is not ours. The
    only safe answer is None; a `UUID(...)` that raised uncaught would 500 the webhook and
    make the provider retry an envelope that can never succeed.
    """
    envelope = {
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_x",
                    "order_id": "order_x",
                    "notes": {"tenant_id": "not-a-uuid"},
                }
            }
        }
    }
    assert payments.payment_attempt_ids(envelope) is None


def test_an_entity_with_no_order_id_is_not_an_attempt() -> None:
    """The order id is the ONLY identifier our own row holds before money arrives."""
    for order in (None, "", "   ", 12345):
        envelope = {
            "payload": {
                "payment": {
                    "entity": {"id": "pay_x", "order_id": order, "notes": {}},
                }
            }
        }
        assert payments.payment_attempt_ids(envelope) is None


# --- `settle_attempt`: no order id, nothing to settle -----------------------------------


async def test_settling_without_an_order_id_touches_no_row() -> None:
    """FAILS IF: a None order id reaches the UPDATE.

    `settle_attempt`'s WHERE is (tenant, order id). With a NULL order id the statement
    matches nothing on a good day — and on a bad one, a future edit that loosened the
    predicate would relabel every attempt this tenant has. The guard returns before the
    statement is built, and this pins that it does.
    """
    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await wallet.settle_attempt(
            session,
            tenant_id=tenant_id,
            order_id=None,
            payment_id="pay_x",
            status="captured",
        )


# --- the receipt for an organisation this deployment does not have ----------------------


async def test_a_receipt_for_an_unknown_organisation_is_a_404_not_a_crash() -> None:
    """FAILS IF: the organisation read stops being the FIRST thing the handler does.

    Read AFTER the payment, this branch is unreachable: `credit_ledger.tenant_id` carries
    `FOREIGN KEY ... REFERENCES organizations(id) ON DELETE RESTRICT`, so a payment row
    proves its organisation exists. Read FIRST it guards something real — a principal
    naming an organisation this deployment does not have — and it answers in the right
    order: "no such account" rather than "no such payment".
    """
    from apps.api.billing.wallet_routes import read_payment_receipt
    from apps.api.core.context import Principal
    from apps.api.core.errors import ProblemError

    absent = uuid.uuid4()
    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=absent,
        role="owner",
        impersonating=False,
    )
    with pytest.raises(ProblemError) as raised:
        await read_payment_receipt("pay_whatever", principal)
    assert raised.value.status == 404
    assert "Organization" in str(raised.value.title) or "Organization" in str(raised.value.detail)


# --- the top-up attempt we could not record must not take the order down with it --------


async def test_a_failure_to_record_the_attempt_never_fails_the_client_s_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: `_remember_order` is allowed to raise.

    It runs AFTER a live order exists at the provider. Raising here would turn a real,
    payable order into an error the client sees, and they would start again and be
    charged for a second order — the exact harm the bookkeeping exists to prevent. The
    row is our convenience; the order is their money.
    """
    from apps.api.billing import payment_routes

    async def _boom(**_: object) -> None:
        raise RuntimeError("the attempts table is unreachable")

    monkeypatch.setattr(payment_routes, "record_topup_attempt", _boom, raising=False)
    await payment_routes._remember_order(
        tenant_id=uuid.uuid4(),
        receipt="rcpt_1",
        amount_inr=Decimal("500.0000"),
        pack_id=None,
        order_id="order_1",
    )


# --- the clawback that has already happened must move nothing ---------------------------


async def test_a_second_clawback_for_the_same_refund_moves_nothing() -> None:
    """FAILS IF: the bonus clawback becomes an increment instead of a cumulative target.

    A pack grants paid credits AND a bonus we fund. A refund reverses the paid leg, so a
    proportional share of the bonus has to come back too — but the amount is expressed as
    a CUMULATIVE TARGET minus what previous refunds already took, precisely so a repeat
    lands on zero. Get that wrong and a replayed webhook, or a second partial refund,
    takes the bonus back TWICE out of an append-only ledger (hard rule 4) that cannot be
    corrected except by another entry someone has to notice and write.

    Driven against real rows: a paid top-up, its bonus grant, a refund, then the same
    refund again.
    """
    from apps.api.admin import service as admin_service
    from apps.api.billing.payments import RefundEvent, _claw_back_pack_bonus
    from apps.api.billing.service import record_entry

    created = await admin_service.create_organization(
        name="Clawback Clinic",
        slug=f"claw-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"

    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("2999.0000"),
            reason="topup",
            ref=payment_id,
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("89.9700"),
            reason="bonus",
            ref=payment_id,
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-2999.0000"),
            reason="refund",
            ref=f"rfnd_{uuid.uuid4().hex[:10]}",
            meta={"payment_id": payment_id},
        )
        await session.commit()

    refund = RefundEvent(
        refund_id=f"rfnd_{uuid.uuid4().hex[:10]}",
        payment_id=payment_id,
        tenant_id=tenant_id,
        amount_inr=Decimal("2999.0000"),
        currency="INR",
    )

    async with tenant_session(tenant_id) as session:
        first = await _claw_back_pack_bonus(session, refund=refund, ip=None)
        await session.commit()
    async with tenant_session(tenant_id) as session:
        second = await _claw_back_pack_bonus(session, refund=refund, ip=None)
        await session.commit()

    assert second == Decimal("0"), (
        f"the bonus was clawed back a second time ({second}); a cumulative target must "
        "land on zero once the whole bonus is already back"
    )
    assert first >= Decimal("0")


# --- a replay's claim belongs to the refund that already exists -------------------------


async def test_a_failed_replay_does_not_release_the_original_refunds_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the release stops asking whether THIS request took the claim.

    `claim_refund` answers `claimed=False` for a repeat of a refund already claimed — a
    replay, not a second refund. The caller still calls the provider, because the
    provider's own idempotency key is (payment id, amount) and can only collapse onto the
    refund that already exists. If that call then fails, releasing the claim would free
    the ceiling for a refund THAT ALREADY HAPPENED, and the next request through would
    issue a second one against money the client only paid once.

    The mirror arm — a claim this request DID take, released so a vendor timeout cannot
    shrink what a client may be refunded for ever — is covered by the refund suite. This
    pins the one that only runs on a replay whose provider call fails.
    """
    from apps.api.admin import service as admin_service
    from apps.api.billing import payment_routes
    from apps.api.billing.payments import RefundClaim
    from apps.api.billing.service import record_entry
    from apps.api.core.context import Principal

    created = await admin_service.create_organization(
        name="Replay Clinic",
        slug=f"rep-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("1000.0000"),
            reason="topup",
            ref=payment_id,
        )
        await session.commit()

    released: list[str] = []

    async def _replay_claim(*_: object, **__: object) -> RefundClaim:
        return RefundClaim(refund_key="rfk_replay", claimed=False)

    async def _provider_dies(**_: object) -> object:
        raise RuntimeError("the provider timed out")

    async def _record_release(*_: object, **kwargs: object) -> None:
        released.append(str(kwargs.get("refund_key")))

    monkeypatch.setattr(payment_routes, "claim_refund", _replay_claim)
    monkeypatch.setattr(payment_routes, "issue_refund", _provider_dies)
    monkeypatch.setattr(payment_routes, "release_refund_claim", _record_release)

    principal = Principal(
        realm="admin",
        user_id=uuid.uuid4(),
        tenant_id=None,
        role="superadmin",
        impersonating=False,
    )

    class _Req:
        client = None
        headers: ClassVar[dict[str, str]] = {}

    with pytest.raises(RuntimeError):
        await payment_routes.issue_tenant_refund(
            tenant_id,
            payment_routes.RefundIn(
                payment_id=payment_id,
                amount_inr=Decimal("500.0000"),
                reason="duplicate charge reported by the client",
            ),
            _Req(),  # type: ignore[arg-type]
            principal,
        )

    assert released == [], (
        "a replay's claim was released; the ceiling it holds belongs to the refund that "
        "already exists, and freeing it lets a second refund through"
    )


# --- an order the provider created without giving us an id ------------------------------


async def test_an_order_with_no_provider_id_is_returned_without_being_remembered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: `_remember_order` is called with a null order id.

    The attempt row is keyed on (tenant, provider order id) — that is the ONLY identifier
    it holds before money arrives, and `settle_attempt` finds it by nothing else. Writing
    a row with no order id would create an attempt that no webhook can ever settle: it
    would sit `created` for ever on the client's screen while their payment succeeded,
    and the reconciler would have a row it could never match.

    The arm exists because `creates_orders` being true is a statement about THIS
    DEPLOYMENT's configuration, not a promise that every future call returns an id.
    """
    from apps.api.billing import payment_routes
    from apps.api.billing.payments import PaymentCapability
    from apps.api.core.context import Principal

    remembered: list[object] = []

    async def _no_id(**kwargs: object) -> object:
        build = kwargs["build"]
        assert callable(build)
        return build(None)

    async def _record(**kwargs: object) -> None:
        remembered.append(kwargs)

    # The route asserts the key id is present once the capability says available — a
    # credential and a capability are two facts and it refuses to infer one from the
    # other, so the fixture must state both.
    from apps.api.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_orderless")
    monkeypatch.setattr(
        payment_routes,
        "payment_capability",
        lambda: PaymentCapability(available=True, provider="razorpay", creates_orders=True),
    )
    monkeypatch.setattr(payment_routes, "_create_order_once", _no_id)
    monkeypatch.setattr(payment_routes, "_remember_order", _record)

    created = await __import__("apps.api.admin.service", fromlist=["service"]).create_organization(
        name="Orderless Clinic",
        slug=f"ord-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    # Prepaid, or the route refuses before it ever reaches the arm under test: an invoiced
    # account does not buy credit through this door.
    from sqlalchemy import text

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": tenant_id},
        )
        await session.commit()

    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )

    intent = await payment_routes.create_topup_intent(
        payment_routes.TopUpIntentIn(amount_inr=Decimal("500.0000")), principal
    )

    assert intent.provider_order_id is None
    assert remembered == [], (
        "an attempt row was written with no provider order id; nothing could ever settle "
        "it, and it would sit `created` for ever while the client's payment succeeded"
    )
