"""Restating an UNDER-credited payment — the repair D-87 left open (D-89).

`credit_topup_test.py` covers money going on to a wallet and `credit_adjustment_test.py`
covers taking a wrong entry back off one. Neither could answer the mirror-image mistake:
₹5,000 recorded against a UTR the bank actually moved ₹50,000 on. Re-posting the
reference is a 409 (deliberately — that refusal is what stops one transfer being credited
twice) and an adjustment only ever takes credit AWAY, bounded by the entry it names.

Every property here exists because the alternative is either a wrong wallet or a
reconciliation that silently stops balancing:

- the correction is a SECOND `topup` row for the SAME bank transfer, and the ledger
  still reads as ONE payment — which the old `UTR-123-part2` workaround destroyed,
- the operator states the TOTAL the bank moved and never the difference; a total at or
  below what the reference credits is refused by name and pointed at `/adjustments`,
- the key is the (reference, total), so a second click credits NOTHING and a third
  restatement to a higher total still converges on that total rather than compounding,
- every call needs the step-up, and it echoes the AMOUNT — this correction has no
  ceiling but the statement in front of the operator,
- the refusal leaks nothing: no header is a 403 whether or not the reference exists,
- `record_topup` answers on the reference's TOTAL, so the 409 that reveals the shortfall
  names the route that repairs it and the repaired payment re-posts as a replay,
- nothing moves without an audit row, and a replay writes no second one.

Mounted the way `credit_adjustment_test.py` mounts it: a bare app with the real error
handlers, so the RBAC boot assertion is exercised against this router too.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import credit_routes
from apps.api.billing.credit_routes import (
    credit_adjustment_confirmation,
    topup_restatement_confirmation,
)
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.service import record_entry, recorded_payments, restatement_ref
from apps.api.core.context import Principal
from apps.api.core.errors import install_error_handlers
from apps.api.core.stepup import StepUp
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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


async def _tenant(plan_tier: str = "self_serve") -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Restatement Clinic",
        slug=f"rst-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :i"),
            {"tier": plan_tier, "i": tenant_id},
        )
    return tenant_id


async def _owner_token(tenant_id: uuid.UUID) -> str:
    """A REAL client-realm owner — the strongest form of the refusal test."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, 'owner', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    return f"dev:client:{user_id}"


def _headers(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


def _confirm(token: str, ref: str, total: str) -> dict[str, str]:
    """The headers a console sends: the step-up echoes BOTH the reference and the total."""
    return _headers(token, topup_restatement_confirmation(ref, Decimal(total)))


async def _ledger(tenant_id: uuid.UUID) -> list[tuple[str, Decimal, str | None, Decimal]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT reason, delta, ref, balance_after FROM credit_ledger "
                    "WHERE tenant_id = :t ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), Decimal(str(r[1])), r[2], Decimal(str(r[3]))) for r in rows]


async def _entry_row(tenant_id: uuid.UUID, entry_id: str) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT delta, reason, ref, balance_after, occurred_at, meta "
                    "FROM credit_ledger WHERE tenant_id = :t AND id = :i"
                ),
                {"t": tenant_id, "i": entry_id},
            )
        ).first()


async def _credit(token: str, tenant_id: uuid.UUID, amount: str, ref: str) -> str:
    """Put a top-up on the wallet through the real route and return its entry id."""
    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": amount, "payment_ref": ref},
        )
    assert posted.status_code == 200, posted.text
    entry_id: str = posted.json()["entry_id"]
    return entry_id


def _body(ref: str, total: str, reason: str = "the bank moved more than we recorded") -> dict:
    return {"payment_ref": ref, "corrected_amount_inr": total, "reason": reason}


async def _restate(
    token: str, tenant_id: uuid.UUID, ref: str, total: str, reason: str | None = None
) -> Any:
    body = _body(ref, total) if reason is None else _body(ref, total, reason)
    async with _client() as http:
        return await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/restatements",
            headers=_confirm(token, ref, total),
            json=body,
        )


# --- the property the whole slice exists for -----------------------------------


async def test_an_under_credited_payment_is_restated_and_still_reads_as_one_payment() -> None:
    """₹5,000 recorded for a UTR the bank moved ₹50,000 on.

    The anchor row is bit-for-bit untouched — it is the evidence — and a SECOND `topup`
    row carries the difference against the same reference. What makes this a repair
    rather than the `UTR-123-part2` lie it replaces is the last assertion: the wallet
    publishes ONE payment for ONE bank transfer, at the figure the statement shows.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    anchor = await _credit(token, tenant_id, "5000.00", "UTR-SHORT")
    before = await _entry_row(tenant_id, anchor)

    restated = await _restate(token, tenant_id, "UTR-SHORT", "50000.00")

    assert restated.status_code == 200, restated.text
    body = restated.json()
    assert body["recorded"] is True
    assert body["payment_ref"] == "UTR-SHORT"
    # The operator sent the TOTAL; the route worked out what was missing.
    assert body["added_inr"] == "45000.00"
    assert body["credited_inr"] == "50000.00"
    assert body["balance_inr"] == "50000.00"
    assert body["ref"] == "restated:UTR-SHORT:50000.00"

    entries = await _ledger(tenant_id)
    assert len(entries) == 2, f"the anchor STAYS and a second row completes it, got {entries}"
    assert entries[0][:3] == ("topup", Decimal("5000.0000"), "UTR-SHORT")
    # `topup`, NOT `adjustment`: the money genuinely arrived by bank transfer, so
    # "payments received this month" must count it.
    assert entries[1][0] == "topup"
    assert entries[1][1] == Decimal("45000.0000")

    after = await _entry_row(tenant_id, anchor)
    assert after is not None and before is not None
    assert tuple(after) == tuple(before), "the under-credited row was EDITED, not completed"

    async with _client() as http:
        panel = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
    payments = panel.json()["payments"]
    assert len(payments) == 1, f"one bank transfer, one line, got {payments}"
    assert payments[0]["payment_ref"] == "UTR-SHORT"
    assert payments[0]["credited_inr"] == "50000.00", (
        "the figure a bank statement is checked against"
    )
    assert payments[0]["entries"] == 2, "…and how many rows it took to get there"


async def test_the_restating_row_names_the_payment_in_its_meta_and_in_its_ref() -> None:
    """The two links that make the pair one payment, asserted separately.

    `meta.payment_ref` is the machine link `PAYMENT_REF_SQL` reads; the row's own `ref`
    carries the reference visibly, so a human scanning the ledger's reference column
    pairs the two rows without opening `meta`. Losing either one turns a restatement back
    into an orphan credit under a reference the bank never printed.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "100.00", "UTR-LINKED")

    restated = await _restate(token, tenant_id, "UTR-LINKED", "250.00", "statement says 250")
    assert restated.status_code == 200, restated.text

    row = await _entry_row(tenant_id, restated.json()["entry_id"])
    assert row is not None
    assert row[2] == "restated:UTR-LINKED:250.00"
    assert "UTR-LINKED" in str(row[2]), "the reference is legible without opening meta"
    meta = row[5]
    assert meta["payment_ref"] == "UTR-LINKED"
    assert meta["kind"] == "topup_restatement"
    assert meta["reason"] == "statement says 250"
    # The ASSERTION is recorded, because it cannot be reconstructed later: what the
    # reference credited before, and what it was said to have moved.
    assert meta["credited_before_inr"] == "100.00"
    assert meta["credited_after_inr"] == "250.00"
    assert meta["added_inr"] == "150.00"


# --- idempotency and convergence -----------------------------------------------


async def test_a_second_click_credits_nothing() -> None:
    """The key is (reference, TOTAL), so the same assertion twice is one credit."""
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-DOUBLE-CLICK")

    first = await _restate(token, tenant_id, "UTR-DOUBLE-CLICK", "50000.00")
    second = await _restate(token, tenant_id, "UTR-DOUBLE-CLICK", "50000.00")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["recorded"] is True
    assert second.json()["recorded"] is False, "a replay credits nothing"
    assert second.json()["entry_id"] == first.json()["entry_id"], "the EXISTING entry comes back"
    assert second.json()["credited_inr"] == "50000.00"
    assert second.json()["balance_inr"] == "50000.00"

    entries = await _ledger(tenant_id)
    assert len(entries) == 2, f"two clicks, ONE credit, got {entries}"
    assert entries[-1][3] == Decimal("50000.0000"), "the balance moved once"


async def test_the_replay_answers_before_the_not_an_increase_check_does() -> None:
    """The ordering that decides which answer a double-click gets.

    After the first restatement the reference credits exactly the total that was
    asserted, so `corrected <= credited` is TRUE for the request that just succeeded. A
    bound check placed first would answer the second click with
    `restatement_not_an_increase` — a 422 that reads like a refusal, on a request that
    changed nothing. The replay lookup runs first, so the operator is told the truth.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "800.00", "UTR-ORDERING")

    await _restate(token, tenant_id, "UTR-ORDERING", "1200.00")
    replay = await _restate(token, tenant_id, "UTR-ORDERING", "1200.00")

    assert replay.status_code == 200, replay.text
    assert replay.json()["recorded"] is False


async def test_restating_twice_converges_on_the_total_rather_than_compounding() -> None:
    """The property that makes the TOTAL shape safe where a difference would not be.

    ₹5,000 → ₹50,000 → ₹55,000 leaves the reference crediting ₹55,000, because each
    restatement asserts a STATE and the route derives the movement. Had the operator
    been asked for differences, the same three transcriptions would have to be
    ₹45,000 and ₹5,000 — two subtractions, done by a human, with nothing able to check
    either of them.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-CONVERGE")

    first = await _restate(token, tenant_id, "UTR-CONVERGE", "50000.00")
    second = await _restate(token, tenant_id, "UTR-CONVERGE", "55000.00")

    assert first.json()["added_inr"] == "45000.00", first.text
    assert second.json()["added_inr"] == "5000.00", second.text
    assert second.json()["credited_inr"] == "55000.00"
    assert second.json()["balance_inr"] == "55000.00"
    # Three rows, three different keys — and still ONE bank transfer.
    entries = await _ledger(tenant_id)
    assert len(entries) == 3
    assert [e[2] for e in entries] == [
        "UTR-CONVERGE",
        restatement_ref(payment_ref="UTR-CONVERGE", credited_total_inr=Decimal("50000")),
        restatement_ref(payment_ref="UTR-CONVERGE", credited_total_inr=Decimal("55000.00")),
    ]

    async with _client() as http:
        panel = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
    assert panel.json()["payments"] == [
        {
            "payment_ref": "UTR-CONVERGE",
            "credited_inr": "55000.00",
            "entries": 3,
            "first_at": panel.json()["payments"][0]["first_at"],
        }
    ]


async def test_the_key_quantizes_so_one_total_is_one_key() -> None:
    """`50000.0` and `50000.00` are the same assertion, so they must be the same key —
    otherwise a console that trimmed a trailing zero would credit the difference twice."""
    assert restatement_ref(
        payment_ref="UTR-Q", credited_total_inr=Decimal("50000.0")
    ) == restatement_ref(payment_ref="UTR-Q", credited_total_inr=Decimal("50000.00"))
    # …and the step-up string quantizes with it, or the key would deduplicate requests
    # the header had already refused.
    assert topup_restatement_confirmation("UTR-Q", Decimal("50000.0")) == (
        topup_restatement_confirmation("UTR-Q", Decimal("50000.00"))
    )


async def test_two_operators_restating_one_payment_at_once_credit_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the advisory lock is taken BEFORE the payment read.

    Forced rather than hoped for, exactly as `credit_topup_test` and
    `credit_adjustment_test` force theirs: the second operator is released only once the
    first is inside the critical section, and the MECHANISM is asserted next to the
    outcome — while the first request holds the lock, the second must not be able to
    reach the credited-total read at all. Without it both measure the shortfall from
    ₹5,000 and both credit ₹45,000.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-RACE")

    first_read = asyncio.Event()
    second_read = asyncio.Event()
    seen: dict[str, bool] = {}
    holder: asyncio.Task[Any] | None = None
    real_read = credit_routes._read_recorded_payment

    async def traced(session: Any, *, tenant_id: uuid.UUID, payment_ref: str) -> Any:
        nonlocal holder
        task = asyncio.current_task()
        if holder is None:
            holder = task
            found = await real_read(session, tenant_id=tenant_id, payment_ref=payment_ref)
            first_read.set()
            # If the lock does its job the second request cannot get here, so this times
            # out — the timeout IS the passing case.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(second_read.wait(), timeout=1.0)
            seen["second_read_while_first_open"] = second_read.is_set()
            return found
        if task is not holder:
            second_read.set()
        return await real_read(session, tenant_id=tenant_id, payment_ref=payment_ref)

    monkeypatch.setattr(credit_routes, "_read_recorded_payment", traced)

    async def post(second: bool) -> int:
        if second:
            await first_read.wait()
        async with _client() as http:
            response = await http.post(
                f"/v1/admin/tenants/{tenant_id}/credits/restatements",
                headers=_confirm(token, "UTR-RACE", "50000.00"),
                json=_body("UTR-RACE", "50000.00"),
            )
        return response.status_code

    statuses = await asyncio.gather(post(False), post(True))
    assert statuses == [200, 200], statuses
    assert seen.get("second_read_while_first_open") is False, (
        "the second operator read the payment while the first was still open — the "
        "advisory lock is not covering the check-then-write"
    )

    entries = await _ledger(tenant_id)
    assert len(entries) == 2, f"two clicks, ONE credit, got {entries}"
    assert entries[-1][3] == Decimal("50000.0000")


# --- the total, never the difference -------------------------------------------


async def test_a_total_that_is_not_an_increase_is_refused_and_points_at_the_adjustment() -> None:
    """The one shape refused at the boundary rather than absorbed.

    A total at or below what the reference credits is either an operator who typed the
    DIFFERENCE, or one trying to correct downwards. Both are real intentions and neither
    belongs here: the first would credit the wrong figure silently, and the second has a
    surface that bounds itself by the entry it names.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-NOT-UP")

    same = await _restate(token, tenant_id, "UTR-NOT-UP", "5000.00")
    lower = await _restate(token, tenant_id, "UTR-NOT-UP", "1000.00")

    for response in (same, lower):
        assert response.status_code == 422, response.text
        assert response.json()["type"].endswith("/restatement_not_an_increase")
        assert "₹5,000.00".replace(",", "") in response.json()["detail"]
        assert "/credits/adjustments" in response.json()["remediation"]
        assert "not the difference" in response.json()["remediation"]
    assert len(await _ledger(tenant_id)) == 1, "a refused restatement never reaches the ledger"


async def test_a_zero_or_negative_total_is_refused_by_name() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "300.00", "UTR-SIGN")

    zero = await _restate(token, tenant_id, "UTR-SIGN", "0")
    negative = await _restate(token, tenant_id, "UTR-SIGN", "-300.00")

    for response in (zero, negative):
        assert response.status_code == 422, response.text
        assert response.json()["type"].endswith("/invalid_restatement_amount")
    assert len(await _ledger(tenant_id)) == 1


async def test_a_json_float_total_is_refused_rather_than_rounded() -> None:
    """Hard rule 7 at the boundary, on the third write as on the first two. The shared
    `refuse_json_float` is what makes that true by construction rather than by memory —
    this body cannot inherit `MoneyIn`, because its amount is a TOTAL and not a
    movement, so the rule is shared as a function instead of as a field."""
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "300.10", "UTR-FLOAT")

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/restatements",
            headers=_confirm(token, "UTR-FLOAT", "500.10"),
            json={
                "payment_ref": "UTR-FLOAT",
                "corrected_amount_inr": 500.10,
                "reason": "statement says more",
            },
        )

    assert response.status_code == 422, response.text
    assert response.json()["fields"][0]["field"] == "corrected_amount_inr"
    assert len(await _ledger(tenant_id)) == 1


async def test_a_reason_is_required_and_whitespace_is_not_one() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "300.00", "UTR-REASONLESS")

    async with _client() as http:
        missing = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/restatements",
            headers=_confirm(token, "UTR-REASONLESS", "900.00"),
            json={"payment_ref": "UTR-REASONLESS", "corrected_amount_inr": "900.00"},
        )
        blank = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/restatements",
            headers=_confirm(token, "UTR-REASONLESS", "900.00"),
            json=_body("UTR-REASONLESS", "900.00", "   "),
        )

    for response in (missing, blank):
        assert response.status_code == 422, response.text
        assert response.json()["fields"][0]["field"] == "reason"
    assert len(await _ledger(tenant_id)) == 1


async def test_a_reference_that_strips_to_nothing_is_refused_not_looked_up() -> None:
    """`_trimmed`'s floor, on the restatement side.

    A blank reference here cannot credit a payment twice — it can do the mirror-image
    damage: `_restate` keys the compensating row on `restated:{ref}:{total}`, so a
    reference that strips to nothing would put an unattributable restatement key on an
    append-only ledger, and the operator's next real restatement of a different payment
    for the same total would be answered "already done" and credit nothing.

    Refused as a field error on `payment_ref`, which is also the honest message: the
    lookup that would otherwise 404 would send the operator hunting for a payment that
    is on their screen, when what is wrong is the box they typed it into.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "300.00", "UTR-BLANKREF")

    for ref in ("   ", " x "):
        response = await _restate(token, tenant_id, ref, "900.00")
        assert response.status_code == 422, f"{ref!r}: {response.text}"
        assert response.json()["fields"][0]["field"] == "payment_ref", ref

    assert len(await _ledger(tenant_id)) == 1, "the wallet is untouched by a refused reference"


async def test_a_padded_reference_still_finds_the_payment() -> None:
    """`_trimmed`, for the mirror-image reason the top-up needs it: a trailing space
    there credits a payment twice, and here it restates a payment that does not exist —
    a 404 an operator cannot explain about a reference visibly on their screen."""
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "400.00", "UTR-PADDED")

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/restatements",
            headers=_confirm(token, "UTR-PADDED", "900.00"),
            json=_body("  UTR-PADDED  ", "900.00"),
        )

    assert response.status_code == 200, response.text
    assert response.json()["payment_ref"] == "UTR-PADDED"
    assert response.json()["ref"] == "restated:UTR-PADDED:900.00"


# --- authority ------------------------------------------------------------------


async def test_every_restatement_needs_the_step_up_and_it_names_the_amount() -> None:
    """The departure from D-87, pinned.

    The adjustment gates one DIRECTION because both of its directions are capped by the
    entry they name. This route has one direction, no ceiling but the operator's reading
    of a statement, and it moves money to the party who will not report an error in their
    favour — so every call is gated, and the confirmation echoes the AMOUNT so one
    captured for ₹50,000 cannot be replayed for ₹500,000.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-STEPUP")
    path = f"/v1/admin/tenants/{tenant_id}/credits/restatements"

    async with _client() as http:
        bare = await http.post(path, headers=_headers(token), json=_body("UTR-STEPUP", "50000.00"))
        # A confirmation captured for a DIFFERENT TOTAL against the same reference.
        other_total = await http.post(
            path,
            headers=_confirm(token, "UTR-STEPUP", "50000.00"),
            json=_body("UTR-STEPUP", "500000.00"),
        )
        # …and one captured for a different reference on the same wallet.
        other_ref = await http.post(
            path,
            headers=_confirm(token, "UTR-ELSEWHERE", "50000.00"),
            json=_body("UTR-STEPUP", "50000.00"),
        )
        # The adjustment's confirmation is not this route's confirmation.
        wrong_kind = await http.post(
            path,
            headers=_headers(token, credit_adjustment_confirmation(uuid.uuid4())),
            json=_body("UTR-STEPUP", "50000.00"),
        )

    for response in (bare, other_total, other_ref, wrong_kind):
        assert response.status_code == 403, response.text
        assert response.json()["type"].endswith("/step_up_required")
    assert "restate_topup:UTR-STEPUP:50000.00" in bare.json()["remediation"]
    assert len(await _ledger(tenant_id)) == 1, "a refused confirmation writes nothing"


async def test_the_step_up_refusal_tells_a_caller_nothing_about_the_wallet() -> None:
    """The reason the step-up runs before every read.

    A caller without the header must not be able to tell a real reference from an
    invented one — otherwise the 403/404 boundary is an oracle that enumerates a client's
    bank references to anyone who can reach the route without a confirmation.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-REAL")
    path = f"/v1/admin/tenants/{tenant_id}/credits/restatements"

    async with _client() as http:
        real = await http.post(path, headers=_headers(token), json=_body("UTR-REAL", "9000.00"))
        invented = await http.post(
            path, headers=_headers(token), json=_body("UTR-NEVER-HAPPENED", "9000.00")
        )

    assert real.status_code == 403 and invented.status_code == 403
    assert real.json()["title"] == invented.json()["title"]
    assert real.json()["type"] == invented.json()["type"]


async def test_a_client_realm_owner_cannot_restate_their_own_payment() -> None:
    """Realms never share session logic (TRD §11). An owner holding `billing:read` in
    their own realm is not authority to put money on our books — least of all their own
    balance upwards, which is precisely what this route does."""
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "400.00", "UTR-REALM")
    client_token = await _owner_token(tenant_id)
    path = f"/v1/admin/tenants/{tenant_id}/credits/restatements"

    async with _client() as http:
        posted = await http.post(
            path,
            headers=_confirm(client_token, "UTR-REALM", "40000.00"),
            json=_body("UTR-REALM", "40000.00"),
        )
        anonymous = await http.post(path, json=_body("UTR-REALM", "40000.00"))

    assert posted.status_code in (401, 403), posted.text
    assert anonymous.status_code == 401
    assert len(await _ledger(tenant_id)) == 1, "a refused request writes nothing"


# --- isolation ------------------------------------------------------------------


async def test_a_reference_not_on_this_wallet_is_not_found() -> None:
    """This route CANNOT create a payment — one of the two things standing in for a
    numeric ceiling. A reference nobody recorded is a 404, and an invented one is exactly
    as absent as a real one belonging to somebody else."""
    token = await _make_admin()
    tenant_id = await _tenant()

    missing = await _restate(token, tenant_id, "UTR-NEVER-RECORDED", "50000.00")

    assert missing.status_code == 404, missing.text
    assert missing.json()["title"] == "Payment reference not found"
    assert len(await _ledger(tenant_id)) == 0


async def test_another_tenants_payment_reference_is_not_restatable_here() -> None:
    """Hard rule 1 on the write that puts money on a wallet. Under RLS "no such
    reference" and "somebody else's reference" are the same answer, and crucially the
    credit lands on NEITHER wallet."""
    token = await _make_admin()
    victim = await _tenant()
    other = await _tenant()
    await _credit(token, victim, "7000.00", "UTR-CROSS")

    posted = await _restate(token, other, "UTR-CROSS", "70000.00")

    assert posted.status_code == 404, posted.text
    assert len(await _ledger(other)) == 0, "nothing was written to the wallet in the path"
    victim_entries = await _ledger(victim)
    assert len(victim_entries) == 1 and victim_entries[0][3] == Decimal("7000.0000")


# --- the seam with the top-up route ---------------------------------------------


async def test_the_conflict_that_reveals_the_shortfall_names_the_route_that_repairs_it() -> None:
    """Where an operator actually MEETS this problem.

    They re-post the UTR at the figure the statement shows and get a 409. That refusal is
    the discovery, so it has to carry the remedy — the same lesson D-87 pinned when the
    top-up's negative-amount refusal pointed at an adjustment route that did not exist.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-DISCOVER")

    async with _client() as http:
        clash = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "50000.00", "payment_ref": "UTR-DISCOVER"},
        )
    assert clash.status_code == 409, clash.text
    assert clash.json()["type"].endswith("/topup_reference_conflict")
    remediation = clash.json()["remediation"]
    path = f"/v1/admin/tenants/{tenant_id}/credits/restatements"
    assert path in remediation, remediation
    assert "annotated reference" in remediation, "the workaround is refused by name"

    # The named route is real, and it answers this operator's request.
    repaired = await _restate(token, tenant_id, "UTR-DISCOVER", "50000.00")
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["credited_inr"] == "50000.00"


async def test_the_over_credit_conflict_still_points_at_the_adjustment() -> None:
    """The other direction of the same 409. Two mistakes, two remedies, and the route
    picks the one that matches rather than offering both — a refusal that lists every
    possibility is a refusal that recommends nothing."""
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "50000.00", "UTR-OVER")

    async with _client() as http:
        clash = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "5000.00", "payment_ref": "UTR-OVER"},
        )
    assert clash.status_code == 409, clash.text
    assert "/credits/adjustments" in clash.json()["remediation"]
    assert "/credits/restatements" not in clash.json()["remediation"]


async def test_reposting_a_restated_payment_at_the_corrected_figure_is_a_replay() -> None:
    """The seam that would otherwise trap an operator inside their own repair.

    `record_topup` compares against what the REFERENCE credits, not against the anchor
    row's own amount. Without that, the corrected figure — the only figure the statement
    supports — would come back as a conflicting payment for ever, and the operator would
    have no way to confirm the wallet is now right.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    anchor = await _credit(token, tenant_id, "5000.00", "UTR-CONFIRMABLE")
    await _restate(token, tenant_id, "UTR-CONFIRMABLE", "50000.00")

    async with _client() as http:
        confirmed = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "50000.00", "payment_ref": "UTR-CONFIRMABLE"},
        )
        # …and the pre-correction figure is now the conflict, which is the truth.
        stale = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "5000.00", "payment_ref": "UTR-CONFIRMABLE"},
        )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["recorded"] is False
    assert confirmed.json()["amount_inr"] == "50000.00", "the reference's TOTAL, not the anchor's"
    assert confirmed.json()["entry_id"] == anchor, "the payment is still anchored on its own row"
    assert stale.status_code == 409, stale.text
    assert len(await _ledger(tenant_id)) == 2, "neither post wrote a row"


async def test_an_ordinary_replay_is_unchanged_by_any_of_this() -> None:
    """The regression that matters most: a payment that was never restated must answer
    exactly as it always did, because that is every payment in the system."""
    token = await _make_admin()
    tenant_id = await _tenant()
    entry_id = await _credit(token, tenant_id, "2500.10", "UTR-ORDINARY")

    async with _client() as http:
        again = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "2500.10", "payment_ref": "UTR-ORDINARY"},
        )

    assert again.status_code == 200, again.text
    assert again.json() == {
        "tenant_id": str(tenant_id),
        "entry_id": entry_id,
        "payment_ref": "UTR-ORDINARY",
        "amount_inr": "2500.10",
        "balance_inr": "2500.10",
        "is_low": False,
        "recorded": False,
    }


# --- what the correction does NOT disturb ---------------------------------------


async def test_a_restatement_does_not_eat_the_anchors_reversible_ceiling() -> None:
    """`reversed_amounts` groups on `meta.corrects_entry_id`, so a restatement must never
    carry that key.

    If it did, a +₹45,000 row naming the anchor would read as ₹45,000 already taken back
    from a ₹5,000 entry — clamping its `reversible_inr` to zero and locking the operator
    out of correcting the very payment they just repaired.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    anchor = await _credit(token, tenant_id, "5000.00", "UTR-CEILING")
    restated = await _restate(token, tenant_id, "UTR-CEILING", "50000.00")
    assert restated.status_code == 200, restated.text

    async with _client() as http:
        panel = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
    entries = {e["id"]: e for e in panel.json()["entries"]}
    assert entries[anchor]["reversible_inr"] == "5000.00", "the anchor keeps its own ceiling"
    assert entries[restated.json()["entry_id"]]["reversible_inr"] == "45000.00"

    row = await _entry_row(tenant_id, restated.json()["entry_id"])
    assert row is not None and "corrects_entry_id" not in row[5]


async def test_an_over_shot_restatement_is_recoverable_through_the_adjustment() -> None:
    """The answer to "what stops this being an unbounded credit tool" that the route can
    actually offer: the row it writes is an ordinary `topup` entry, so `/adjustments`
    takes it back bounded by its own magnitude. An operator who typed ₹500,000 for
    ₹50,000 is one correction away from right, not stranded.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-OVERSHOOT")
    overshot = await _restate(token, tenant_id, "UTR-OVERSHOOT", "500000.00")
    assert overshot.status_code == 200, overshot.text
    wrong_row = overshot.json()["entry_id"]

    async with _client() as http:
        fixed = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong_row))),
            json={
                "corrects_entry_id": wrong_row,
                "amount_inr": "450000.00",
                "reason": "restated to 500000 by a typo; the statement says 50000",
            },
        )

    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["balance_inr"] == "50000.00"
    # The wallet is right. The PAYMENT still publishes what the topup rows claim, which
    # is the honest reading: an adjustment is a separate, explained layer, and the
    # residue is a reference whose rows do not match its statement until it is restated
    # rather than adjusted. Stated here so the behaviour is a decision, not a surprise.
    async with _client() as http:
        panel = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
    assert panel.json()["balance_inr"] == "50000.00"
    assert panel.json()["payments"][0]["credited_inr"] == "500000.00"


async def test_a_restatement_lands_on_a_negative_balance() -> None:
    """`allow_negative=True`, and it is not decoration.

    `record_entry` refuses any write that LEAVES the balance negative, not only one that
    makes it so. A wallet at -₹12,000 (a wrong credit reversed after it was spent) would
    otherwise have a genuine ₹1,000 credit refused as `insufficient_credits` — the
    accounting layer declining to record money that actually arrived.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "1000.00", "UTR-NEGATIVE")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-13000.00"),
            reason="usage",
            ref=str(uuid.uuid4()),
            allow_negative=True,
        )

    restated = await _restate(token, tenant_id, "UTR-NEGATIVE", "2000.00")

    assert restated.status_code == 200, restated.text
    assert restated.json()["added_inr"] == "1000.00"
    assert restated.json()["balance_inr"] == "-11000.00"
    assert restated.json()["is_low"] is True


# --- the record -----------------------------------------------------------------


async def test_the_restatement_carries_an_audit_row_naming_who_and_why(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Money appearing on a client's account on our say-so, with no ceiling above it.

    The audit row commits in the SAME transaction as the entry and the operator's own
    words travel with it — "who put ₹45,000 on this client, and why" is the question this
    record exists to answer, and it is asked more often of an unexplained credit than of
    a debit, because the client never complains about one.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-AUDITED")
    reason = "statement shows 50,000; the 5,000 was a transposition"

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        restated = await _restate(token, tenant_id, "UTR-AUDITED", "50000.00", reason)
    assert restated.status_code == 200, restated.text

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id, object_type, object_id, entry_hash "
                    "FROM audit_log WHERE tenant_id = :t AND action = 'credit.topup_restated'"
                ),
                {"t": tenant_id},
            )
        ).all()

    assert len(rows) == 1, f"one restatement, one audit row, got {len(rows)}"
    actor_type, actor_id, object_type, object_id, entry_hash = rows[0]
    assert actor_type == "admin"
    assert actor_id is not None, "the audit row names WHO"
    assert object_type == "credit_ledger"
    assert object_id == restated.json()["entry_id"], "the audit row names the entry it created"
    assert entry_hash, "the tamper-evident chain covers it like every other entry"

    # Selected by the payment it names AND by a field only this write emits: the top-up
    # route logs an `audit` line carrying `payment_ref` too, so "the one on this
    # reference" is a selector that depends on which other work ran inside the capture.
    summaries = [
        record
        for record in caplog.records
        if record.getMessage() == "audit"
        and record.__dict__.get("payment_ref") == "UTR-AUDITED"
        and "added_inr" in record.__dict__
    ]
    assert len(summaries) == 1, "one restatement, one audit summary on the log stream"
    summary = summaries[0]
    assert summary.reason == reason  # type: ignore[attr-defined]
    assert summary.added_inr == "45000.00"  # type: ignore[attr-defined]
    assert summary.credited_before_inr == "5000.00"  # type: ignore[attr-defined]
    assert summary.credited_after_inr == "50000.00"  # type: ignore[attr-defined]
    assert summary.balance_after_inr == "50000.00"  # type: ignore[attr-defined]


async def test_a_replayed_restatement_writes_no_second_audit_row() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "600.00", "UTR-AUDIT-REPLAY")

    await _restate(token, tenant_id, "UTR-AUDIT-REPLAY", "900.00")
    await _restate(token, tenant_id, "UTR-AUDIT-REPLAY", "900.00")

    async with untenanted_session() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'credit.topup_restated'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert count == 1, "nothing moved the second time, so nothing is audited the second time"


# --- the reconciliation view ----------------------------------------------------


async def test_a_payment_total_is_complete_even_when_its_anchor_is_off_the_page() -> None:
    """The figure a bank statement is checked against must never be a page-local sum.

    The page is bounded (newest N entries) and the payments on it are derived from that
    page, but each total is summed over ALL of that payment's rows. A restated payment
    whose anchor has scrolled off would otherwise publish less than it credits — the one
    kind of wrong this whole slice exists to end.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "5000.00", "UTR-PAGED")
    await _restate(token, tenant_id, "UTR-PAGED", "50000.00")

    async with _client() as http:
        page = await http.get(
            f"/v1/admin/tenants/{tenant_id}/credits?limit=1", headers=_headers(token)
        )

    body = page.json()
    assert len(body["entries"]) == 1, "only the restating row is on this page"
    assert body["entries"][0]["ref"] == "restated:UTR-PAGED:50000.00"
    assert body["payments"] == [
        {
            "payment_ref": "UTR-PAGED",
            "credited_inr": "50000.00",
            "entries": 2,
            "first_at": body["payments"][0]["first_at"],
        }
    ], "the anchor is off the page and still counted"


async def test_usage_and_adjustment_rows_are_not_payments() -> None:
    """`PAYMENT_REF_SQL` is NULL for anything that is not a top-up, because `ref` is
    three namespaces in one column. A call id folded in beside a UTR would put a debit on
    the panel a person reconciles bank transfers against."""
    token = await _make_admin()
    tenant_id = await _tenant()
    anchor = await _credit(token, tenant_id, "5000.00", "UTR-ONLY-PAYMENT")
    call_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("-80.00"), reason="usage", ref=call_id
        )
    async with _client() as http:
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(anchor))),
            json={
                "corrects_entry_id": anchor,
                "amount_inr": "100.00",
                "reason": "a hundred of it was not ours",
            },
        )
        panel = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))

    body = panel.json()
    assert len(body["entries"]) == 3
    assert [p["payment_ref"] for p in body["payments"]] == ["UTR-ONLY-PAYMENT"]
    # The payment reports what the TOP-UP rows credit; the adjustment is a separate,
    # explained layer and the balance is where the two meet.
    assert body["payments"][0]["credited_inr"] == "5000.00"
    assert body["balance_inr"] == "4820.00"


async def test_recorded_payments_asks_the_database_nothing_when_asked_about_nothing() -> None:
    """An empty page of ledger entries must not become `= ANY('{}')`.

    A wallet with no entries is the FIRST thing every new tenant has, so this early
    return is on the commonest path in the product rather than on an edge — the argument
    `reversed_amounts` makes for its own. Asserted against a session that raises if
    touched, so the test states the property ("it does not query") rather than the result
    ("it returned {}"), which a version that queried and got nothing would also satisfy.
    """

    class Untouchable:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("recorded_payments queried the database for zero references")

    session = cast(AsyncSession, Untouchable())

    assert await recorded_payments(session, tenant_id=uuid.uuid4(), payment_refs=[]) == {}


async def test_an_actor_with_no_user_id_is_recorded_without_a_recorded_by() -> None:
    """`meta.recorded_by` is omitted, never the string "None".

    `Principal.user_id` is `UUID | None` and the admin realm fills it for every token
    this route can be reached with today, which makes the guard unreachable through the
    API and worth pinning anyway: the failure it prevents is a `meta` key whose value is
    the four characters `None`, which reads in an audit export as an operator id and
    cannot be told apart from one after the fact.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "700.00", "UTR-NO-ACTOR")

    result = await credit_routes.record_restatement(
        tenant_id=tenant_id,
        payload=credit_routes.RestatementIn(
            payment_ref="UTR-NO-ACTOR",
            corrected_amount_inr=Decimal("900.00"),
            reason="recorded by a principal with no user row",
        ),
        # No `client` in the scope, which is also what a request through a socket the
        # server cannot name looks like — `ip` is then None rather than a crash.
        request=Request({"type": "http", "method": "POST", "path": "/", "headers": []}),
        principal=Principal(
            realm="admin",
            user_id=None,
            tenant_id=None,
            role="operator",
        ),
        # The gate a request resolves through `Depends(step_up_gate)`; called directly,
        # the test supplies it. `present=False` is the shape a caller with no
        # first-party admin cookie has (D-178).
        step_up=StepUp(present=False, verified_at=None),
        x_confirm_action=topup_restatement_confirmation("UTR-NO-ACTOR", Decimal("900.00")),
    )

    assert result.recorded is True
    async with tenant_session(tenant_id) as session:
        meta = (
            await session.execute(
                text("SELECT meta FROM credit_ledger WHERE id = :i"),
                {"i": result.entry_id},
            )
        ).scalar_one()
    assert "recorded_by" not in meta, meta
