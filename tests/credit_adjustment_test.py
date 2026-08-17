"""Compensating credit adjustments — the repair SURFACES §1 promised and nobody built.

`credit_topup_test.py` covers money going ON to a wallet. This covers the only supported
way of taking a wrong entry back OFF one, and every property here exists because the
alternative is a ledger that stays wrong:

- the correction is a NEW ROW; the entry it corrects is bit-for-bit untouched, and the
  database trigger still refuses UPDATE and DELETE on this table (hard rule 4),
- a second click deducts NOTHING — the key is derived from (entry, amount), so the
  replay lands on the row the first click wrote,
- the balance MAY go negative, because a wrong credit that was partly spent cannot be
  fully reversed otherwise, and what that costs the client is REPORTED rather than
  hidden: `stops_dialling` is the dial gate's own predicate,
- an entry on another tenant's wallet is not findable at all (RLS),
- taking credit AWAY needs the step-up header; crediting back does not,
- nothing moves without an audit row, and a replay writes no second one,
- no correction may take back more than the entry put in, cumulatively.

Mounted the way `credit_topup_test.py` mounts it: a bare app with the real error
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
from apps.api.billing.credit_routes import credit_adjustment_confirmation
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.service import adjustment_ref, record_entry, reversed_amounts
from apps.api.compliance.service import credits_exhausted
from apps.api.core.context import Principal
from apps.api.core.errors import install_error_handlers
from apps.api.core.stepup import StepUp
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(credit_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id, "role": role},
        )
    return f"dev:admin:{clerk_id}"


async def _tenant(plan_tier: str = "self_serve") -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Adjustment Clinic",
        slug=f"adj-{uuid.uuid4().hex[:8]}",
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
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:i, :c, :e, now(), now())"
            ),
            {"i": user_id, "c": clerk_id, "e": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, 'owner', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    return f"dev:client:{clerk_id}"


def _headers(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


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


def _adjust_body(entry_id: str, amount: str, reason: str = "credited to the wrong client") -> dict:
    return {"corrects_entry_id": entry_id, "amount_inr": amount, "reason": reason}


# --- the property the whole slice exists for -----------------------------------


async def test_an_adjustment_appends_a_row_and_leaves_the_original_untouched() -> None:
    """₹50,000 to the wrong client, put right the only way an append-only ledger allows.

    The wrong entry is still there afterwards, with the same delta and the same
    `balance_after` it was written with — it is the evidence that it happened, and the
    correction is a SECOND row whose sign was derived from it.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "50000.00", "UTR-WRONG-CLIENT")
    before = await _entry_row(tenant_id, wrong)

    async with _client() as http:
        adjusted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong))),
            json=_adjust_body(wrong, "50000.00"),
        )

    assert adjusted.status_code == 200, adjusted.text
    body = adjusted.json()
    assert body["recorded"] is True
    assert body["corrects_entry_id"] == wrong
    # The operator sent a POSITIVE magnitude; the route derived the direction from the
    # entry, which is the one thing a form must not be trusted to get right.
    assert body["delta_inr"] == "-50000.00"
    assert body["balance_inr"] == "0.00"
    assert body["ref"] == f"adjust:{wrong}:50000.00"

    entries = await _ledger(tenant_id)
    assert len(entries) == 2, f"the wrong entry STAYS and a new one cancels it, got {entries}"
    assert entries[0][:3] == ("topup", Decimal("50000.0000"), "UTR-WRONG-CLIENT")
    assert entries[1][0] == "adjustment"
    assert entries[1][1] == Decimal("-50000.0000")

    after = await _entry_row(tenant_id, wrong)
    assert after is not None and before is not None
    assert tuple(after) == tuple(before), "the corrected row was EDITED, not compensated"


async def test_the_ledger_still_refuses_update_and_delete() -> None:
    """The trigger the whole design rests on. If this ever stops raising, "compensating
    entry" becomes a convention rather than a guarantee, and the route above becomes one
    of several ways to change a balance instead of the only one."""
    token = await _make_admin()
    tenant_id = await _tenant()
    entry_id = await _credit(token, tenant_id, "100.00", "UTR-IMMUTABLE")

    async with tenant_session(tenant_id) as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE credit_ledger SET delta = 0 WHERE tenant_id = :t AND id = :i"),
                {"t": tenant_id, "i": entry_id},
            )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("DELETE FROM credit_ledger WHERE tenant_id = :t AND id = :i"),
                {"t": tenant_id, "i": entry_id},
            )

    entries = await _ledger(tenant_id)
    assert len(entries) == 1 and entries[0][1] == Decimal("100.0000")


# --- idempotency ---------------------------------------------------------------


async def test_a_second_click_deducts_nothing() -> None:
    """An adjustment has no UTR, so its key is derived from (entry, amount). The same
    correction submitted twice returns the entry that already exists."""
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "5000.00", "UTR-DOUBLE-CLICK")
    body = _adjust_body(wrong, "5000.00")
    headers = _headers(token, credit_adjustment_confirmation(uuid.UUID(wrong)))

    async with _client() as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments", headers=headers, json=body
        )
        second = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments", headers=headers, json=body
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["recorded"] is True
    assert second.json()["recorded"] is False, "a replay deducts nothing"
    assert second.json()["entry_id"] == first.json()["entry_id"], "the EXISTING entry comes back"
    assert second.json()["balance_inr"] == "0.00"

    entries = await _ledger(tenant_id)
    assert len(entries) == 2, f"one correction, one compensating row, got {entries}"
    assert entries[-1][3] == Decimal("0.0000"), "the balance moved once"


async def test_the_replay_answers_before_the_remaining_ceiling_does() -> None:
    """The ordering that decides which answer a double-click gets.

    After the first correction the entry has nothing left to give, so a bound check
    placed first would answer the second click with `adjustment_exceeds_entry` — a 422
    that reads like a refusal, on a request that changed nothing. The replay lookup runs
    first, so the operator is told the truth: already recorded, nothing moved.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "800.00", "UTR-ORDERING")
    body = _adjust_body(wrong, "800.00")
    headers = _headers(token, credit_adjustment_confirmation(uuid.UUID(wrong)))

    async with _client() as http:
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments", headers=headers, json=body
        )
        replay = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments", headers=headers, json=body
        )

    assert replay.status_code == 200, replay.text
    assert replay.json()["recorded"] is False


async def test_two_operators_correcting_one_entry_at_once_deduct_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the advisory lock is taken BEFORE the target read.

    Forced rather than hoped for, exactly as `credit_topup_test` forces its race: the
    second operator is released only once the first is inside the critical section, and
    the MECHANISM is asserted next to the outcome — while the first request holds the
    lock, the second must not be able to reach the target read at all.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "1200.00", "UTR-ADJ-RACE")
    body = _adjust_body(wrong, "1200.00")
    headers = _headers(token, credit_adjustment_confirmation(uuid.UUID(wrong)))

    first_read = asyncio.Event()
    second_read = asyncio.Event()
    seen: dict[str, bool] = {}
    holder: asyncio.Task[Any] | None = None
    real_read = credit_routes._read_correctable_entry

    async def traced(session: Any, *, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> Any:
        nonlocal holder
        task = asyncio.current_task()
        if holder is None:
            holder = task
            found = await real_read(session, tenant_id=tenant_id, entry_id=entry_id)
            first_read.set()
            # If the lock does its job the second request cannot get here, so this times
            # out — the timeout IS the passing case.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(second_read.wait(), timeout=1.0)
            seen["second_read_while_first_open"] = second_read.is_set()
            return found
        if task is not holder:
            second_read.set()
        return await real_read(session, tenant_id=tenant_id, entry_id=entry_id)

    monkeypatch.setattr(credit_routes, "_read_correctable_entry", traced)

    async def post(second: bool) -> int:
        if second:
            await first_read.wait()
        async with _client() as http:
            response = await http.post(
                f"/v1/admin/tenants/{tenant_id}/credits/adjustments", headers=headers, json=body
            )
        return response.status_code

    statuses = await asyncio.gather(post(False), post(True))
    assert statuses == [200, 200], statuses
    assert seen.get("second_read_while_first_open") is False, (
        "the second operator read the entry while the first was still open — the "
        "advisory lock is not covering the check-then-write"
    )

    entries = await _ledger(tenant_id)
    assert len(entries) == 2, f"two clicks, ONE deduction, got {entries}"
    assert entries[-1][3] == Decimal("0.0000")


async def test_the_key_is_the_entry_and_the_amount() -> None:
    """Two PARTIAL corrections of one entry are two different keys, so both land — the
    property that stops idempotency from silently swallowing a second, genuine fix."""
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "1000.00", "UTR-PARTIAL")
    headers = _headers(token, credit_adjustment_confirmation(uuid.UUID(wrong)))

    async with _client() as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=headers,
            json=_adjust_body(wrong, "400.00", "the transfer was ₹600, not ₹1000"),
        )
        second = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=headers,
            json=_adjust_body(wrong, "150.00", "and ₹150 of that was a second client's"),
        )

    assert first.json()["recorded"] is True, first.text
    assert second.json()["recorded"] is True, second.text
    assert second.json()["balance_inr"] == "450.00"
    # The refs differ only in the amount, which is what makes them different keys.
    assert first.json()["ref"] == adjustment_ref(
        entry_id=uuid.UUID(wrong), amount_inr=Decimal("400.00")
    )
    assert second.json()["ref"] == adjustment_ref(
        entry_id=uuid.UUID(wrong), amount_inr=Decimal("150.00")
    )
    # …and `50000.0` / `50000.00` are ONE key, not two.
    assert (
        adjustment_ref(entry_id=uuid.UUID(wrong), amount_inr=Decimal("400.0"))
        == (first.json()["ref"])
    )


# --- the balance may go negative, and the dial gate is told ---------------------


async def test_a_wrong_credit_that_was_spent_reverses_into_a_negative_balance() -> None:
    """The case that decides the whole design.

    ₹50,000 lands on the wrong wallet and ₹12,000 of it is spent before anyone notices.
    Reversing the credit in full leaves the balance at -₹12,000, and that is the honest
    number: the client never had the money. Refusing the correction because it overdraws
    would leave the ledger permanently claiming credit that does not exist, which is the
    exact condition `scripts/reconcile_credit_ledger.py` passes `allow_negative` to end.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "50000.00", "UTR-SPENT")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-12000.00"),
            reason="usage",
            ref=str(uuid.uuid4()),
        )

    async with _client() as http:
        adjusted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong))),
            json=_adjust_body(wrong, "50000.00"),
        )

    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["balance_inr"] == "-12000.00"
    assert adjusted.json()["is_low"] is True
    entries = await _ledger(tenant_id)
    assert entries[-1][3] == Decimal("-12000.0000")


async def test_a_negative_balance_stops_a_self_serve_clients_dialling_and_the_route_says_so() -> (
    None
):
    """A correction that silently stops a client calling is the one consequence an
    operator must not learn from the client. `stops_dialling` is the DIAL GATE's own
    predicate, asked of the balance this write produced — not a second copy of the
    rule."""
    token = await _make_admin()
    tenant_id = await _tenant("self_serve")
    wrong = await _credit(token, tenant_id, "3000.00", "UTR-STOPS")

    async with _client() as http:
        adjusted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong))),
            json=_adjust_body(wrong, "3000.00"),
        )

    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["balance_inr"] == "0.00"
    assert adjusted.json()["stops_dialling"] is True
    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id) is True


async def test_a_managed_client_keeps_dialling_on_a_negative_balance() -> None:
    """A managed client is invoiced against a retainer (D-34), so the wallet gates
    nothing for them — `credits_exhausted` is self-serve/trial only. Correcting their
    ledger must therefore never read as "we have just stopped their calls"."""
    token = await _make_admin()
    tenant_id = await _tenant("managed")
    wrong = await _credit(token, tenant_id, "9000.00", "UTR-MANAGED")

    async with _client() as http:
        adjusted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong))),
            json=_adjust_body(wrong, "9000.00"),
        )

    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["balance_inr"] == "0.00"
    assert adjusted.json()["stops_dialling"] is False
    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id) is False


# --- the ceiling ---------------------------------------------------------------


async def test_more_than_the_entry_put_in_is_refused() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "1000.00", "UTR-CEILING")

    async with _client() as http:
        over = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong))),
            json=_adjust_body(wrong, "1000.01"),
        )

    assert over.status_code == 422, over.text
    assert over.json()["type"].endswith("/adjustment_exceeds_entry")
    entries = await _ledger(tenant_id)
    assert len(entries) == 1, "a refused correction never reaches the ledger"


async def test_two_partial_corrections_cannot_add_up_past_the_whole() -> None:
    """The ceiling is CUMULATIVE, which is the half a per-request check would miss: two
    corrections of ₹600 against a ₹1,000 entry are two different keys and both would
    otherwise land, taking back ₹1,200 the entry never put in."""
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "1000.00", "UTR-CUMULATIVE")
    headers = _headers(token, credit_adjustment_confirmation(uuid.UUID(wrong)))

    async with _client() as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=headers,
            json=_adjust_body(wrong, "600.00"),
        )
        second = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=headers,
            json=_adjust_body(wrong, "600.01"),
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 422, second.text
    assert second.json()["type"].endswith("/adjustment_exceeds_entry")
    assert "400.00" in second.json()["detail"], "the refusal names what is left"


async def test_the_read_publishes_what_is_left_to_take_back() -> None:
    """The console cannot do decimal arithmetic on money (hard rule 7 reaches the
    browser), so the remaining figure is computed here — by the same dataclass the write
    path enforces its ceiling with."""
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "1000.00", "UTR-REVERSIBLE")

    async with _client() as http:
        fresh = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong))),
            json=_adjust_body(wrong, "250.00"),
        )
        after = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))

    assert fresh.json()["entries"][0]["reversible_inr"] == "1000.00"
    entries = {e["id"]: e for e in after.json()["entries"]}
    assert entries[wrong]["reversible_inr"] == "750.00"
    # The compensating entry is itself correctable — "I adjusted the wrong entry" is as
    # likely as "I credited the wrong client", and refusing it would recreate this whole
    # gap one level up.
    correction = next(e for e in after.json()["entries"] if e["reason"] == "adjustment")
    assert correction["reversible_inr"] == "250.00"


async def test_correcting_a_correction_walks_the_chain_rather_than_dead_ending() -> None:
    """The residual `CorrectableEntry.reversible_inr` documents, pinned so it stays a
    decision.

    An adjustment is a ledger entry and may itself be corrected. Doing so does NOT give
    the ORIGINAL entry its ceiling back — that would need an alternating sum over the
    whole chain — and the reason that is acceptable is asserted here: the chain does not
    dead-end. The next correction is made against the NEWEST entry, which carries its own
    full ceiling and is the row at the top of the ledger the operator is looking at.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    original = await _credit(token, tenant_id, "1000.00", "UTR-CHAIN")

    async with _client() as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(original))),
            json=_adjust_body(original, "1000.00", "wrong client"),
        )
        assert first.status_code == 200, first.text
        reversal = first.json()["entry_id"]

        # …and that reversal was itself the mistake. Correcting it puts the money back
        # (a credit, so no step-up) — the balance is the proof.
        undo = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token),
            json=_adjust_body(reversal, "1000.00", "the correction named the wrong entry"),
        )
        assert undo.status_code == 200, undo.text
        assert undo.json()["balance_inr"] == "1000.00"

        panel = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
        entries = {e["id"]: e for e in panel.json()["entries"]}
        # The original still reads as fully corrected — the residual, stated.
        assert entries[original]["reversible_inr"] == "0.00"
        # But the NEWEST entry carries a full ceiling, so the money can still be moved.
        newest = panel.json()["entries"][0]
        assert newest["id"] == undo.json()["entry_id"]
        assert newest["reversible_inr"] == "1000.00"

        again = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(newest["id"]))),
            json=_adjust_body(newest["id"], "1000.00", "and it was wrong after all"),
        )
    assert again.status_code == 200, again.text
    assert again.json()["balance_inr"] == "0.00", "the chain never dead-ends"
    assert len(await _ledger(tenant_id)) == 4, "four rows, none of them edited"


# --- authority -----------------------------------------------------------------


async def test_taking_credit_away_needs_the_step_up_header() -> None:
    """Bound to the DIRECTION, the shape `record_commercial_terms` uses for a spend
    ceiling: the dangerous half of the act is gated, not the endpoint."""
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "2000.00", "UTR-STEPUP")

    async with _client() as http:
        bare = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token),
            json=_adjust_body(wrong, "2000.00"),
        )
        # A confirmation captured for a DIFFERENT entry must not be replayable here.
        wrong_entry = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.uuid4())),
            json=_adjust_body(wrong, "2000.00"),
        )

    for response in (bare, wrong_entry):
        assert response.status_code == 403, response.text
        assert response.json()["type"].endswith("/step_up_required")
        assert f"adjust_credits:{wrong}" in response.json()["remediation"]
    assert len(await _ledger(tenant_id)) == 1, "a refused confirmation writes nothing"


async def test_crediting_back_needs_no_step_up() -> None:
    """Reversing a USAGE charge puts money back on the client's wallet. That is not the
    dangerous direction and gating it would make ordinary support work need a ceremony
    that protects nobody."""
    token = await _make_admin()
    tenant_id = await _tenant()
    await _credit(token, tenant_id, "500.00", "UTR-REFUNDABLE")
    call_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-80.00"),
            reason="usage",
            ref=call_id,
        )
    async with tenant_session(tenant_id) as session:
        charge_id = str(
            (
                await session.execute(
                    text("SELECT id FROM credit_ledger WHERE tenant_id = :t AND ref = :r"),
                    {"t": tenant_id, "r": call_id},
                )
            ).scalar()
        )

    async with _client() as http:
        credited_back = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token),
            json=_adjust_body(charge_id, "80.00", "the call never connected"),
        )

    assert credited_back.status_code == 200, credited_back.text
    assert credited_back.json()["delta_inr"] == "80.00", "the sign follows the entry"
    assert credited_back.json()["balance_inr"] == "500.00"


async def test_a_client_realm_owner_cannot_adjust_their_own_wallet() -> None:
    """Realms never share session logic (TRD §11). An owner holding `billing:read` in
    their own realm is not authority to move money on our books — least of all their
    own balance upwards."""
    token = await _make_admin()
    tenant_id = await _tenant()
    entry_id = await _credit(token, tenant_id, "400.00", "UTR-REALM")
    client_token = await _owner_token(tenant_id)

    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(client_token, credit_adjustment_confirmation(uuid.UUID(entry_id))),
            json=_adjust_body(entry_id, "400.00"),
        )
        anonymous = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            json=_adjust_body(entry_id, "400.00"),
        )

    assert posted.status_code in (401, 403), posted.text
    assert anonymous.status_code == 401
    assert len(await _ledger(tenant_id)) == 1, "a refused request writes nothing"


# --- isolation -----------------------------------------------------------------


async def test_an_entry_on_another_tenants_wallet_is_not_found() -> None:
    """Hard rule 1 on the write that moves money. Under RLS "no such entry" and
    "somebody else's entry" are the same answer, deliberately — and crucially, the
    correction lands on NEITHER wallet."""
    token = await _make_admin()
    victim = await _tenant()
    other = await _tenant()
    theirs = await _credit(token, victim, "7000.00", "UTR-CROSS")

    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{other}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(theirs))),
            json=_adjust_body(theirs, "7000.00"),
        )

    assert posted.status_code == 404, posted.text
    assert len(await _ledger(other)) == 0, "nothing was written to the wallet in the path"
    victim_entries = await _ledger(victim)
    assert len(victim_entries) == 1 and victim_entries[0][3] == Decimal("7000.0000")


# --- the record -----------------------------------------------------------------


async def test_the_adjustment_carries_an_audit_row_naming_who_and_why(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Money leaving a client's account on our say-so. The audit row commits in the SAME
    transaction as the entry, and the operator's own words travel with it — "who took
    ₹50,000 off this client, and why" is the question this record exists to answer.

    Two halves, because `audit_log` carries no summary column deliberately (hashing a
    field the row does not hold would make the chain unverifiable): the ROW, and the
    `audit` log line keyed by the same entry, exactly as the bulk-lead write is pinned.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "50000.00", "UTR-AUDITED")
    reason = "paid by Sri Traders; credited to this account by mistake"

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            adjusted = await http.post(
                f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
                headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong))),
                json=_adjust_body(wrong, "50000.00", reason),
            )
    assert adjusted.status_code == 200, adjusted.text

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id, object_type, object_id, entry_hash "
                    "FROM audit_log WHERE tenant_id = :t AND action = 'credit.adjustment'"
                ),
                {"t": tenant_id},
            )
        ).all()

    assert len(rows) == 1, f"one correction, one audit row, got {len(rows)}"
    actor_type, actor_id, object_type, object_id, entry_hash = rows[0]
    assert actor_type == "admin"
    assert actor_id is not None, "the audit row names WHO"
    assert object_type == "credit_ledger"
    assert object_id == adjusted.json()["entry_id"], "the audit row names the entry it created"
    assert entry_hash, "the tamper-evident chain covers it like every other entry"

    # Selected by the entry it names, not by position: the top-up that set this test up
    # writes an `audit` line of its own, and "the first one" is a selector that depends
    # on which other tests ran first.
    summaries = [
        record
        for record in caplog.records
        if record.getMessage() == "audit"
        and record.__dict__.get("entry_id")
        and record.__dict__.get("corrects_entry_id") == wrong
    ]
    assert len(summaries) == 1, "one correction, one audit summary on the log stream"
    summary = summaries[0]
    assert summary.reason == reason  # type: ignore[attr-defined]
    assert summary.delta_inr == "-50000.00"  # type: ignore[attr-defined]
    assert summary.balance_after_inr == "0.00"  # type: ignore[attr-defined]

    # …and the entry itself carries the same words, so a reader of the LEDGER never has
    # to go and find the audit record to learn why a balance moved.
    row = await _entry_row(tenant_id, adjusted.json()["entry_id"])
    assert row is not None
    assert row[5]["reason"] == reason
    assert row[5]["corrects_entry_id"] == wrong
    assert row[5]["kind"] == "operator_adjustment"


async def test_a_replayed_adjustment_writes_no_second_audit_row() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "600.00", "UTR-AUDIT-REPLAY-ADJ")
    body = _adjust_body(wrong, "600.00")
    headers = _headers(token, credit_adjustment_confirmation(uuid.UUID(wrong)))

    async with _client() as http:
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments", headers=headers, json=body
        )
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments", headers=headers, json=body
        )

    async with untenanted_session() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'credit.adjustment'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert count == 1, "nothing moved the second time, so nothing is audited the second time"


# --- the boundary ---------------------------------------------------------------


async def test_a_reason_is_required_and_whitespace_is_not_one() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "300.00", "UTR-REASONLESS")
    headers = _headers(token, credit_adjustment_confirmation(uuid.UUID(wrong)))

    async with _client() as http:
        missing = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=headers,
            json={"corrects_entry_id": wrong, "amount_inr": "300.00"},
        )
        blank = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=headers,
            json=_adjust_body(wrong, "300.00", "   "),
        )

    for response in (missing, blank):
        assert response.status_code == 422, response.text
        assert response.json()["fields"][0]["field"] == "reason"
    assert len(await _ledger(tenant_id)) == 1


async def test_a_json_float_amount_is_refused_rather_than_rounded() -> None:
    """Hard rule 7 at the boundary, on the second write as on the first — the shared
    `MoneyIn` base is what makes that true by construction rather than by memory."""
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "300.10", "UTR-ADJ-FLOAT")

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(wrong))),
            json={"corrects_entry_id": wrong, "amount_inr": 300.10, "reason": "wrong client"},
        )

    assert response.status_code == 422, response.text
    assert response.json()["fields"][0]["field"] == "amount_inr"
    assert len(await _ledger(tenant_id)) == 1


async def test_a_zero_or_negative_amount_is_refused_by_name() -> None:
    """The sign is derived from the entry, so a signed amount is a caller who has
    misunderstood the contract — told so, rather than silently flipped."""
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "300.00", "UTR-ADJ-SIGN")
    headers = _headers(token, credit_adjustment_confirmation(uuid.UUID(wrong)))

    async with _client() as http:
        zero = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=headers,
            json=_adjust_body(wrong, "0"),
        )
        negative = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=headers,
            json=_adjust_body(wrong, "-300.00"),
        )

    for response in (zero, negative):
        assert response.status_code == 422, response.text
        assert response.json()["type"].endswith("/invalid_adjustment_amount")
    assert len(await _ledger(tenant_id)) == 1


async def test_the_topup_refusal_points_at_a_route_that_exists() -> None:
    """The lie this slice was opened by: `POST .../credits` refused a negative amount
    with "record a compensating adjustment instead" while no such surface existed
    anywhere. The remediation now names the path, and the path answers."""
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        refused = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "-500.00", "payment_ref": "UTR-POINTS-AT"},
        )
        assert refused.status_code == 422, refused.text
        remediation = refused.json()["remediation"]
        path = f"/v1/admin/tenants/{tenant_id}/credits/adjustments"
        assert path in remediation, remediation

        # The named route is real: it answers this operator's token with a business
        # answer (no such entry on this empty wallet), never a 404 for the ROUTE.
        probe = await http.post(
            path,
            headers=_headers(token, credit_adjustment_confirmation(uuid.uuid4())),
            json=_adjust_body(str(uuid.uuid4()), "500.00"),
        )
    assert probe.status_code == 404
    assert probe.json()["title"] == "Ledger entry not found"


# --- the three guards nothing above reaches -------------------------------------


async def test_reversed_amounts_asks_the_database_nothing_when_asked_about_nothing() -> None:
    """An empty page of ledger entries must not become `WHERE id IN ()`.

    `read_credits` calls this with whatever ids the page holds, and a wallet with no
    entries is the FIRST thing every new tenant has. The early return is therefore on
    the commonest path in the product, not an edge: it is what stops an empty page
    building a degenerate `IN ()` predicate whose behaviour differs between databases.

    Asserted against a session that would raise if touched, so the test states the
    property ("it does not query") rather than the result ("it returned {}"), which a
    version that queried and got nothing back would also satisfy.
    """

    class Untouchable:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("reversed_amounts queried the database for zero ids")

    session = cast(AsyncSession, Untouchable())

    assert await reversed_amounts(session, tenant_id=uuid.uuid4(), entry_ids=[]) == {}


async def test_an_entry_that_moved_nothing_is_refused_rather_than_given_a_direction() -> None:
    """A zero-delta row has no sign to derive, so the route refuses instead of guessing.

    `record_entry` returns early on a zero delta, so this route cannot produce such a
    row — which is exactly why the guard needs a test rather than a comment: nothing in
    the product's own paths would ever reach it, and an unexercised branch that faces
    money is a branch nobody knows the behaviour of. The row is inserted directly (an
    INSERT, never an UPDATE — hard rule 4 holds in tests too) to stand for a row that
    arrived from a migration or a fixture.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    entry_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO credit_ledger "
                "(id, tenant_id, delta, balance_after, reason, ref, meta, occurred_at) "
                "VALUES (:i, :t, 0, 0, 'adjustment', :r, '{}'::jsonb, now())"
            ),
            {"i": entry_id, "t": tenant_id, "r": f"legacy-{entry_id}"},
        )

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(entry_id)),
            json=_adjust_body(str(entry_id), "100.00"),
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/entry_moved_nothing")
    # The refusal wrote nothing: the zero row is still the only line on this wallet.
    assert len(await _ledger(tenant_id)) == 1


async def test_an_actor_with_no_user_id_is_recorded_without_a_recorded_by() -> None:
    """`meta.recorded_by` is omitted, never the string "None".

    `Principal.user_id` is `UUID | None`, and the admin realm happens to fill it for
    every token this route can be reached with today. That makes the guard unreachable
    through the API and worth pinning anyway: the failure it prevents is a `meta` key
    whose value is the four characters `None`, which reads in an audit export as an
    operator id and cannot be told apart from one after the fact. Called directly,
    because the shape being tested is the one the dependency never produces.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    wrong = await _credit(token, tenant_id, "700.00", "UTR-NO-ACTOR")

    result = await credit_routes.record_adjustment(
        tenant_id=tenant_id,
        payload=credit_routes.AdjustmentIn(
            corrects_entry_id=uuid.UUID(wrong),
            amount_inr=Decimal("700.00"),
            reason="recorded by a principal with no user row",
        ),
        # No `client` in the scope, which is also what a request through a socket the
        # server cannot name looks like — `ip` is then None rather than a crash.
        request=Request({"type": "http", "method": "POST", "path": "/", "headers": []}),
        principal=Principal(
            realm="admin",
            user_id=None,
            clerk_user_id="admin_without_a_row",
            tenant_id=None,
            role="operator",
        ),
        # The gate a request resolves through `Depends(step_up_gate)`; called directly,
        # the test supplies it. `present=False` is the shape a caller with no
        # first-party admin cookie has (D-178).
        step_up=StepUp(present=False, verified_at=None),
        x_confirm_action=credit_adjustment_confirmation(uuid.UUID(wrong)),
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
