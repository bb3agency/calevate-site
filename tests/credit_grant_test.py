"""Credit granted out of nothing (D-535) — the ledger row, the ceiling, and the split.

The founder: *"the admin should be able to add any no.of credits without any payments
record to any client but it is audited"*, with three guardrails they chose themselves —
shown separately from paid credit, a ceiling per grant, and audited.

Each of those is a test here, and so is the one property that is easy to get wrong in the
other direction: a grant is idempotent on a reference the OPERATOR supplies, so a second
click converges and a second genuine gift of the same size does not.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.billing import credit_routes
from apps.api.billing.credit_routes import credit_grant_confirmation
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.models import CREDIT_REASONS, GRANTED_CREDIT_REASONS, PAID_CREDIT_REASONS
from apps.api.billing.service import (
    MAX_GRANT_INR,
    MIN_GRANT_INR,
    CreditReason,
    credit_totals,
    get_balance,
    grant_ref,
    record_entry,
)
from apps.api.core.context import Principal
from apps.api.core.errors import install_error_handlers
from apps.api.core.stepup import StepUp
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio


async def _tenant(plan_tier: str = "prepaid") -> uuid.UUID:
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Grant Clinic",
        slug=f"grant-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": plan_tier, "i": tenant_id},
        )
    return tenant_id


async def test_the_reason_vocabulary_and_its_type_agree() -> None:
    """`CreditReason` is a hand-written Literal (a `Literal[*tuple]` is not a static type
    mypy can check), so nothing but a test holds it equal to the tuple the DB CHECK is
    built from. A reason in one and not the other is either a value the ORM admits and the
    type refuses, or one the type admits and Postgres rejects at 2am."""
    from typing import get_args

    assert set(get_args(CreditReason)) == set(CREDIT_REASONS)


async def test_every_reason_is_either_paid_or_granted_or_neither_deliberately() -> None:
    """The two sets are the definition of "bought" and "given", and they must not overlap.
    `usage`, `adjustment` and `refund` are in NEITHER on purpose — they are movements, not
    origins, and letting a correction subtract from what a client was given would
    understate the gift."""
    assert not set(PAID_CREDIT_REASONS) & set(GRANTED_CREDIT_REASONS)
    assert set(PAID_CREDIT_REASONS) | set(GRANTED_CREDIT_REASONS) <= set(CREDIT_REASONS)
    assert "grant" in GRANTED_CREDIT_REASONS
    assert "topup" in PAID_CREDIT_REASONS


async def test_a_grant_lands_on_the_balance_and_is_counted_as_given_not_paid() -> None:
    """The founder's first guardrail, as arithmetic: the wallet goes up by the grant and
    the REVENUE side does not move. Granted credit reading as paid is what would inflate
    our own margin figures."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("2000"), reason="topup", ref="UTR-1"
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500"),
            reason="grant",
            ref=grant_ref(reference="goodwill-1"),
        )
        balance = await get_balance(session, tenant_id=tenant_id)
        totals = await credit_totals(session, tenant_id=tenant_id)

    assert balance.amount_inr == Decimal("2500.0000")
    assert totals.paid_inr == Decimal("2000.0000")
    assert totals.granted_inr == Decimal("500.0000")


async def test_a_wallet_with_no_ledger_at_all_reports_zero_of_each() -> None:
    """The empty wallet, which every client has for the length of their first minute. A
    `SUM` over no rows is NULL and the `COALESCE` is what makes it ₹0.00 — the reason
    `credit_totals` can take the row it is handed unconditionally rather than guarding a
    "no row" case that an aggregate cannot produce."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        totals = await credit_totals(session, tenant_id=tenant_id)
    assert totals.paid_inr == Decimal("0")
    assert totals.granted_inr == Decimal("0")


async def test_a_pack_bonus_counts_as_given_too() -> None:
    """`bonus` is credit WE fund — a promotional grant earned on a pack — so counting it
    as revenue would be the same lie a grant would be. It is a distinct REASON from
    `grant` (a bonus is clawed back when its payment is refunded, and a goodwill grant must
    not be), and the same side of the split."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("100"), reason="bonus", ref="pay_1"
        )
        totals = await credit_totals(session, tenant_id=tenant_id)
    assert totals.granted_inr == Decimal("100.0000")
    assert totals.paid_inr == Decimal("0")


async def test_a_correction_belongs_to_neither_total() -> None:
    """An adjustment that takes a wrong grant back reduces the BALANCE and must not reduce
    `granted_inr`: what a client was given is a historical fact, and the correction is its
    own row that a reader can find beside it."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500"),
            reason="grant",
            ref=grant_ref(reference="oops"),
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-500"),
            reason="adjustment",
            ref="adjust:x",
            allow_negative=True,
        )
        balance = await get_balance(session, tenant_id=tenant_id)
        totals = await credit_totals(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("0.0000")
    assert totals.granted_inr == Decimal("500.0000")


async def test_the_database_refuses_a_second_grant_under_one_reference() -> None:
    """`ux_credit_ledger_grant_ref` is the backstop the route's advisory lock is the
    primary guarantee for (D-63). A future writer that forgets the lock gets a UNIQUE
    violation rather than crediting the gift twice."""
    tenant_id = await _tenant()
    ref = grant_ref(reference="twice")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("100"), reason="grant", ref=ref
        )
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await record_entry(
                session, tenant_id=tenant_id, delta=Decimal("100"), reason="grant", ref=ref
            )


async def test_two_genuinely_distinct_grants_of_the_same_size_both_land() -> None:
    """THE REASON THE KEY IS THE OPERATOR'S AND NOT A CONTENT ADDRESS. Two goodwill grants
    of ₹500 to one client two months apart are ordinary; a key derived from (amount,
    reason) would report the second as a replay of the first — a gift the client never
    received, reported as delivered."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500"),
            reason="grant",
            ref=grant_ref(reference="jan-goodwill"),
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500"),
            reason="grant",
            ref=grant_ref(reference="feb-goodwill"),
        )
        totals = await credit_totals(session, tenant_id=tenant_id)
    assert totals.granted_inr == Decimal("1000.0000")


async def test_the_ceiling_catches_the_founders_own_example() -> None:
    """*"a fat-finger (₹5,00,000 instead of ₹5,000) is refused rather than posted"*. The
    ceiling has to sit an order of magnitude above the honest figure and an order of
    magnitude below the slip, or it refuses real work while stopping nobody."""
    assert Decimal("500000.00") > MAX_GRANT_INR
    assert Decimal("5000.00") * 5 < MAX_GRANT_INR
    assert MIN_GRANT_INR > 0


async def test_the_ledger_still_refuses_an_update_to_a_grant() -> None:
    """Hard rule 4 is not weakened by a sixth reason: a wrong grant is corrected by a
    compensating entry, never by an edit, and the DB trigger is what makes that true
    whatever any writer believes."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("100"),
            reason="grant",
            ref=grant_ref(reference="immutable"),
        )
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE credit_ledger SET delta = 1 WHERE tenant_id = :t"),
                {"t": tenant_id},
            )


# --- the route: the three guardrails as HTTP -----------------------------------
#
# Mounted the way `credit_adjustment_test.py` mounts it — a bare app with the real error
# handlers, so the RBAC boot assertion is exercised against this router too.


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(credit_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


def _headers(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


def _grant_body(amount: str, ref: str, reason: str = "goodwill after the outage") -> dict[str, str]:
    return {"amount_inr": amount, "grant_ref": ref, "reason": reason}


async def _ledger(tenant_id: uuid.UUID) -> list[tuple[str, Decimal, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT reason, delta, ref FROM credit_ledger WHERE tenant_id = :t "
                    "ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), Decimal(str(r[1])), r[2]) for r in rows]


async def _audit_rows(tenant_id: uuid.UUID) -> list[tuple[str, str | None, str | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type, object_id FROM audit_log "
                    "WHERE tenant_id = :t AND action = 'credit.grant'"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), r[1], r[2]) for r in rows]


async def test_a_grant_through_the_route_lands_with_its_audit_row_and_its_words() -> None:
    """The whole write, end to end: the wallet moves, the ledger row carries the
    operator's own words, `granted_inr` moves and `paid_inr` does NOT, and the audit row
    committed in the same transaction as the money — the one control the founder named
    that no ceiling substitutes for.
    """
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        granted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=_headers(token, credit_grant_confirmation(Decimal("2500.00"))),
            json=_grant_body("2500.00", "GRANT-OUTAGE-1", "two days of downtime on their line"),
        )

    assert granted.status_code == 201, granted.text
    body = granted.json()
    assert body["recorded"] is True
    assert body["amount_inr"] == "2500.00"
    assert body["balance_inr"] == "2500.00"
    assert body["grant_ref"] == "GRANT-OUTAGE-1"
    assert body["ref"] == grant_ref(reference="GRANT-OUTAGE-1")
    # The split the founder asked for, published on the WRITE and not only on a screen
    # they might not open.
    assert body["granted_inr"] == "2500.00"
    assert body["paid_inr"] == "0.00", "nobody paid for this and the statement must not say so"

    assert await _ledger(tenant_id) == [
        ("grant", Decimal("2500.0000"), grant_ref(reference="GRANT-OUTAGE-1"))
    ]
    async with tenant_session(tenant_id) as session:
        meta = (
            await session.execute(
                text("SELECT meta FROM credit_ledger WHERE id = :i"), {"i": body["entry_id"]}
            )
        ).scalar_one()
    assert meta["reason"] == "two days of downtime on their line"
    assert meta["granted_by"], "the row names the operator who gave it"

    rows = await _audit_rows(tenant_id)
    assert len(rows) == 1, f"one grant, one audit row, got {len(rows)}"
    actor_type, object_type, object_id = rows[0]
    assert actor_type == "admin"
    assert object_type == "credit_ledger"
    assert object_id == body["entry_id"], "the audit row names the entry it created"


async def test_a_second_click_credits_once_and_reports_that_nothing_moved() -> None:
    """The operator-supplied key doing its job. A console that retried, or an operator who
    clicked twice, must not gift the money twice — and the answer says so rather than
    reporting a second delivery."""
    token = await _make_admin()
    tenant_id = await _tenant()
    headers = _headers(token, credit_grant_confirmation(Decimal("500.00")))
    body = _grant_body("500.00", "GRANT-REPLAY-1")

    async with _client() as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants", headers=headers, json=body
        )
        # A trailing space is the SAME reference: `_trimmed` normalizes before the key is
        # minted, or a stray keystroke would gift the credit a second time.
        second = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=headers,
            json=_grant_body("500.00", " GRANT-REPLAY-1 "),
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["recorded"] is True
    assert second.json()["recorded"] is False, "the replay must not report a second gift"
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert second.json()["balance_inr"] == "500.00", "the wallet moved once"
    assert second.json()["granted_inr"] == "500.00"

    assert len(await _ledger(tenant_id)) == 1, "one gift, one row"
    assert len(await _audit_rows(tenant_id)) == 1, "nothing moved, so nothing is audited again"


async def test_one_reference_for_a_different_amount_is_a_conflict_and_moves_nothing() -> None:
    """A reference means ONE act. Crediting the difference would make a second gift look
    like a correction; ignoring it would report a gift that never arrived. Both are worse
    than a 409 naming the two figures and the route that corrects an amount."""
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=_headers(token, credit_grant_confirmation(Decimal("1000.00"))),
            json=_grant_body("1000.00", "GRANT-CONFLICT-1"),
        )
        clashed = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=_headers(token, credit_grant_confirmation(Decimal("1500.00"))),
            json=_grant_body("1500.00", "GRANT-CONFLICT-1"),
        )

    assert clashed.status_code == 409, clashed.text
    problem = clashed.json()
    assert problem["type"].endswith("/grant_reference_conflict")
    assert "1000.00" in problem["detail"] and "1500.00" in problem["detail"], (
        "the operator is told what is already there and what they just asked for"
    )
    assert "/credits/adjustments" in problem["remediation"], (
        "the refusal points at the route that can put an amount right"
    )

    assert await _ledger(tenant_id) == [
        ("grant", Decimal("1000.0000"), grant_ref(reference="GRANT-CONFLICT-1"))
    ], "the balance did not move on the refusal"


async def test_a_figure_outside_the_ceiling_is_refused_by_name_and_names_the_bounds() -> None:
    """The founder's fat-finger guardrail: ₹5,00,000 instead of ₹5,000 is refused rather
    than posted. Checked BEFORE the step-up, so an operator who typed the wrong number is
    told the number is impossible rather than sent to fix a header and re-submit the typo.
    """
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        too_big = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=_headers(token, credit_grant_confirmation(Decimal("500000.00"))),
            json=_grant_body("500000.00", "GRANT-FAT-FINGER"),
        )
        # No confirmation header at all, and still the AMOUNT is what it is told about.
        too_small = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=_headers(token),
            json=_grant_body("0.50", "GRANT-TOO-SMALL"),
        )

    for response in (too_big, too_small):
        assert response.status_code == 422, response.text
        assert response.json()["type"].endswith("/invalid_grant_amount")
        detail = response.json()["detail"]
        assert f"{MIN_GRANT_INR:,.0f}" in detail and f"{MAX_GRANT_INR:,.0f}" in detail, (
            "the refusal names the real bounds, so the operator can pick a figure inside them"
        )
    assert "500000.00" in too_big.json()["detail"], "and names what was actually asked for"
    assert await _ledger(tenant_id) == [], "a refused figure writes nothing"


async def test_a_grant_needs_a_confirmation_bound_to_its_own_amount() -> None:
    """Unconditional and bound to the NUMBER (`credit_grant_confirmation`): this route has
    one direction, it moves money towards the party who will not report an error in their
    favour, and the danger scales with the figure. A confirmation captured for a different
    amount must not be replayable against a larger one."""
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        bare = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=_headers(token),
            json=_grant_body("5000.00", "GRANT-STEPUP-1"),
        )
        wrong_amount = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=_headers(token, credit_grant_confirmation(Decimal("500.00"))),
            json=_grant_body("5000.00", "GRANT-STEPUP-2"),
        )

    for response in (bare, wrong_amount):
        assert response.status_code == 403, response.text
        assert response.json()["type"].endswith("/step_up_required")
        assert "grant_credits:5000.00" in response.json()["remediation"]
    assert await _ledger(tenant_id) == [], "a refused confirmation writes nothing"


async def test_a_reference_or_a_reason_of_only_whitespace_is_refused() -> None:
    """Both are load-bearing and neither may be satisfied with spaces: the reference is the
    IDEMPOTENCY KEY, and credit that appeared on a wallet with no payment behind it and no
    explanation is exactly the row an auditor stops on."""
    token = await _make_admin()
    tenant_id = await _tenant()
    headers = _headers(token, credit_grant_confirmation(Decimal("100.00")))

    async with _client() as http:
        blank_ref = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=headers,
            json=_grant_body("100.00", "   "),
        )
        blank_reason = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=headers,
            json=_grant_body("100.00", "GRANT-REASONLESS", "    "),
        )

    assert blank_ref.status_code == 422, blank_ref.text
    assert blank_ref.json()["fields"][0]["field"] == "grant_ref"
    assert "grant reference is required" in blank_ref.json()["fields"][0]["message"]
    assert blank_reason.status_code == 422, blank_reason.text
    assert blank_reason.json()["fields"][0]["field"] == "reason"
    assert "why this credit is being granted" in blank_reason.json()["fields"][0]["message"]
    assert await _ledger(tenant_id) == []


async def test_an_actor_with_no_user_id_is_recorded_without_a_granted_by() -> None:
    """`meta.granted_by` is omitted, never the string "None" — the failure it prevents is a
    key whose value is four characters that read in an audit export as an operator id and
    cannot be told apart from one afterwards. Called directly, because the admin realm
    fills `user_id` for every token this route can be reached with today.
    """
    tenant_id = await _tenant()

    result = await credit_routes.grant_credits(
        tenant_id=tenant_id,
        payload=credit_routes.GrantIn(
            amount_inr=Decimal("300.00"),
            grant_ref="GRANT-NO-ACTOR",
            reason="granted by a principal with no user row",
        ),
        # No `client` in the scope, which is also what a request through a socket the
        # server cannot name looks like — `ip` is then None rather than a crash.
        request=Request({"type": "http", "method": "POST", "path": "/", "headers": []}),
        principal=Principal(realm="admin", user_id=None, tenant_id=None, role="operator"),
        # The gate a request resolves through `Depends(step_up_gate)`; called directly,
        # the test supplies it. `present=False` is the shape a caller with no first-party
        # admin cookie has (D-178).
        step_up=StepUp(present=False, verified_at=None),
        x_confirm_action=credit_grant_confirmation(Decimal("300.00")),
    )

    assert result.recorded is True
    async with tenant_session(tenant_id) as session:
        meta = (
            await session.execute(
                text("SELECT meta FROM credit_ledger WHERE id = :i"), {"i": result.entry_id}
            )
        ).scalar_one()
    assert "granted_by" not in meta, meta
