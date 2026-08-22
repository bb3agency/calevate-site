"""Admin credit top-ups (the write side of D-34/D-39's wallet).

`credits_test.py` covers the ledger primitive; this covers the surface ops actually
uses when an SMB pays us by NEFT/UPI. The properties worth protecting are the ones
that involve someone's money:

- crediting raises the balance, and the ledger shows it,
- the SAME bank reference recorded twice credits ONCE — including when two operators
  click at the same moment,
- a client-realm token cannot record a payment at all (realms never share session
  logic, TRD §11),
- every credit carries an audit row, in the same transaction,
- a zero, negative or float amount is refused by name (hard rule 7).

The router is deliberately not mounted in `main.py` (the integrator owns that), so
these tests mount it on a bare app with the real error handlers — which is also how
the RBAC boot assertion gets exercised against it.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import credit_routes
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.service import record_entry
from apps.api.core.context import Principal
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(credit_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
    """The admin_security_test shape: an `admin_users` row + a local dev token."""
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
        name="Topup Clinic",
        slug=f"top-{uuid.uuid4().hex[:8]}",
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
    """A REAL client-realm owner of this tenant — the strongest form of the refusal
    test: someone who genuinely holds `billing:read` in the client realm."""
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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_a_topup_raises_the_balance_and_lands_on_the_ledger() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "2500.00", "payment_ref": "UTR900011", "note": "NEFT, ICICI"},
        )
        read = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))

    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["recorded"] is True
    # Money is a STRING on the wire in both directions (hard rule 7) — never a float.
    assert body["amount_inr"] == "2500.00"
    assert body["balance_inr"] == "2500.00"
    assert body["is_low"] is False

    assert read.status_code == 200, read.text
    panel = read.json()
    assert panel["balance_inr"] == "2500.00"
    assert len(panel["entries"]) == 1
    entry = panel["entries"][0]
    assert entry["id"] == body["entry_id"]
    assert entry["reason"] == "topup"
    assert entry["ref"] == "UTR900011"
    assert entry["delta_inr"] == "2500.00"
    assert entry["balance_after_inr"] == "2500.00"


async def test_the_same_payment_reference_credits_exactly_once() -> None:
    """The whole point of the endpoint being idempotent by the bank reference: ops
    re-entering a UTR (or a retried request) must not credit the client twice."""
    token = await _make_admin()
    tenant_id = await _tenant()
    payload = {"amount_inr": "1000.00", "payment_ref": "UTR-DUPLICATE-1"}

    async with _client() as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=payload
        )
        second = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=payload
        )
        # Trailing whitespace is the same reference, not a new one.
        third = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={**payload, "payment_ref": " UTR-DUPLICATE-1 "},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert third.status_code == 200, third.text
    assert first.json()["recorded"] is True
    assert second.json()["recorded"] is False, "a replay records nothing"
    assert third.json()["recorded"] is False
    assert second.json()["entry_id"] == first.json()["entry_id"], "the EXISTING entry comes back"
    assert third.json()["entry_id"] == first.json()["entry_id"]
    assert second.json()["balance_inr"] == "1000.00"

    entries = await _ledger(tenant_id)
    assert len(entries) == 1, f"one payment, one ledger row, got {entries}"
    assert entries[0] == ("topup", Decimal("1000.0000"), "UTR-DUPLICATE-1")


async def test_a_reference_that_is_only_whitespace_is_refused_before_it_becomes_a_key() -> None:
    """The payment reference IS the idempotency key, and it is normalized by stripping —
    which is what makes `"UTR-1 "` and `"UTR-1"` one payment instead of two.

    That normalization has a hole at the bottom that `min_length` alone does not close:
    `"   "` is three characters, so it passes the length constraint and then strips to
    nothing. An empty key on an append-only ledger is the worst kind: the NEXT payment
    recorded with a blank reference collides with it, so an operator who fat-fingered
    the field once would see a real second payment answered "already recorded" and a
    client would be short the money with no row to point at.

    So it is refused at the boundary as a field error naming `payment_ref` — before a
    transaction opens, and with nothing on the ledger.
    """
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        for ref in ("   ", "\t\n ", " a "):
            response = await http.post(
                f"/v1/admin/tenants/{tenant_id}/credits",
                headers=_headers(token),
                json={"amount_inr": "1000.00", "payment_ref": ref},
            )
            assert response.status_code == 422, f"{ref!r}: {response.text}"
            assert response.json()["fields"][0]["field"] == "payment_ref", ref

    assert await _ledger(tenant_id) == [], "a refused reference never reaches the ledger"


async def test_two_operators_recording_one_payment_at_once_credit_it_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the advisory lock is taken BEFORE the lookup: without it both
    requests read "no such reference" and both insert.

    The overlap is FORCED rather than hoped for. `asyncio.gather` on two posts does not
    reliably interleave: with the route's lock removed, the plain-gather shape still
    reported "one entry" on one run in six — it was passing without exercising the race
    at all, which is a test that will keep passing after the lock is deleted. So the
    second operator is released only once the first is inside the critical section, and
    the MECHANISM is asserted alongside the outcome: while the first request holds the
    lock, the second must not be able to reach the reference lookup at all.
    """
    token = await _make_admin()
    tenant_id = await _tenant()
    payload = {"amount_inr": "750.00", "payment_ref": "UTR-RACE-7"}

    first_looked = asyncio.Event()
    second_looked = asyncio.Event()
    seen: dict[str, bool] = {}
    holder: asyncio.Task[Any] | None = None
    real_find = credit_routes._find_topup

    async def traced(session: Any, *, tenant_id: uuid.UUID, ref: str) -> Any:
        nonlocal holder
        task = asyncio.current_task()
        if holder is None:
            holder = task
            found = await real_find(session, tenant_id=tenant_id, ref=ref)
            first_looked.set()
            # If the lock does its job the second request cannot get here, so this
            # times out — that timeout IS the passing case, and the sample below is
            # taken while the first request still holds its transaction open.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(second_looked.wait(), timeout=1.0)
            seen["second_looked_while_first_open"] = second_looked.is_set()
            return found
        if task is not holder:
            second_looked.set()
        return await real_find(session, tenant_id=tenant_id, ref=ref)

    monkeypatch.setattr(credit_routes, "_find_topup", traced)

    async def post(second: bool) -> int:
        if second:
            await first_looked.wait()
        async with _client() as http:
            response = await http.post(
                f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=payload
            )
        return response.status_code

    statuses = await asyncio.gather(post(False), post(True))
    assert statuses == [200, 200], statuses
    assert seen.get("second_looked_while_first_open") is False, (
        "the second operator read the reference while the first was still open — the "
        "advisory lock is not covering the check-then-write"
    )

    entries = await _ledger(tenant_id)
    assert len(entries) == 1, f"exactly one credit for one payment, got {entries}"
    async with tenant_session(tenant_id) as session:
        balance = (
            await session.execute(
                text("SELECT balance_after FROM credit_ledger WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert Decimal(str(balance)) == Decimal("750.0000")


async def test_a_client_realm_owner_cannot_record_a_payment() -> None:
    """Realms never share session logic (TRD §11). An owner holds `billing:read` in
    their own realm; that is not authority to move money on our books."""
    tenant_id = await _tenant()
    client_token = await _owner_token(tenant_id)

    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(client_token),
            json={"amount_inr": "5000.00", "payment_ref": "UTR-CLIENT-1"},
        )
        read = await http.get(
            f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(client_token)
        )
        anonymous = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            json={"amount_inr": "5000.00", "payment_ref": "UTR-ANON-1"},
        )

    assert posted.status_code in (401, 403), posted.text
    assert read.status_code in (401, 403), read.text
    assert anonymous.status_code == 401
    assert await _ledger(tenant_id) == [], "a refused request writes nothing"


async def test_the_credit_carries_an_audit_row() -> None:
    """Money moving without an audit row is not a state this endpoint can produce —
    `write_audit` runs in the SAME transaction as the ledger insert."""
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "300.00", "payment_ref": "UTR-AUDIT-1"},
        )
    assert posted.status_code == 200, posted.text

    # audit_log is global (not tenant-RLS'd) and INSERT-only.
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, actor_type, object_type, object_id, entry_hash "
                    "FROM audit_log WHERE tenant_id = :t ORDER BY at DESC"
                ),
                {"t": tenant_id},
            )
        ).all()

    topups = [r for r in rows if r[0] == "credit.topup"]
    assert len(topups) == 1, f"one credit, one audit row, got {[r[0] for r in rows]}"
    _action, actor_type, object_type, object_id, entry_hash = topups[0]
    assert actor_type == "admin"
    assert object_type == "credit_ledger"
    assert object_id == posted.json()["entry_id"], "the audit row names the entry it created"
    assert entry_hash, "the tamper-evident chain covers it like every other entry"


async def test_a_replayed_reference_does_not_write_a_second_audit_row() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()
    payload = {"amount_inr": "120.00", "payment_ref": "UTR-AUDIT-REPLAY"}

    async with _client() as http:
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=payload
        )
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=payload
        )

    async with untenanted_session() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'credit.topup'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert count == 1, "nothing moved the second time, so nothing is audited the second time"


async def test_a_zero_or_negative_amount_is_refused_by_name() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        zero = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "0", "payment_ref": "UTR-ZERO"},
        )
        negative = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "-500.00", "payment_ref": "UTR-NEGATIVE"},
        )

    for response in (zero, negative):
        assert response.status_code == 422, response.text
        assert response.json()["type"].endswith("/invalid_topup_amount"), response.text
        assert response.json()["kind"] == "business_rule"
    assert await _ledger(tenant_id) == [], "a refused amount never reaches the ledger"


async def test_a_json_float_amount_is_refused_rather_than_rounded() -> None:
    """Hard rule 7 at the boundary: `2500.10` as a JSON number has already been through
    a binary float by the time we see it. Send the string."""
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": 2500.10, "payment_ref": "UTR-FLOAT"},
        )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["type"].endswith("/validation_failed")
    assert body["fields"][0]["field"] == "amount_inr"
    assert await _ledger(tenant_id) == []


async def test_the_same_reference_with_a_different_amount_is_a_conflict() -> None:
    """Reusing a UTR for a second, different payment would silently swallow real
    money. It is refused loudly instead of being absorbed as a replay."""
    token = await _make_admin()
    tenant_id = await _tenant()

    async with _client() as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "1000.00", "payment_ref": "UTR-CONFLICT"},
        )
        clash = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "2000.00", "payment_ref": "UTR-CONFLICT"},
        )

    assert first.status_code == 200, first.text
    assert clash.status_code == 409, clash.text
    assert clash.json()["type"].endswith("/topup_reference_conflict")
    entries = await _ledger(tenant_id)
    assert len(entries) == 1 and entries[0][1] == Decimal("1000.0000")


async def test_the_ledger_reads_newest_first_and_caps_the_limit() -> None:
    token = await _make_admin()
    tenant_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("500"), reason="topup")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("-120.50"), reason="usage")
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("20"), reason="refund")

    async with _client() as http:
        full = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
        capped = await http.get(
            f"/v1/admin/tenants/{tenant_id}/credits?limit=2", headers=_headers(token)
        )
        absurd = await http.get(
            f"/v1/admin/tenants/{tenant_id}/credits?limit=100000", headers=_headers(token)
        )

    assert full.status_code == 200, full.text
    body = full.json()
    assert [e["reason"] for e in body["entries"]] == ["refund", "usage", "topup"]
    assert body["balance_inr"] == "399.50"
    # ₹399.50 clears the ₹200 warning band, and the band is reported so the UI does
    # not have to hardcode it.
    assert body["is_low"] is False
    assert body["low_balance_threshold_inr"] == "200.00"
    assert body["entries"][0]["balance_after_inr"] == body["balance_inr"]

    assert len(capped.json()["entries"]) == 2
    assert capped.json()["balance_inr"] == "399.50", "the balance is not truncated by the limit"
    assert absurd.status_code == 422, "an unbounded page size is not on offer"


async def test_an_unknown_tenant_is_a_404_not_a_500() -> None:
    """A mistyped tenant id on a money route must not become an FK violation, and must
    not answer with a plausible-looking empty wallet."""
    token = await _make_admin()
    missing = uuid.uuid4()

    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{missing}/credits",
            headers=_headers(token),
            json={"amount_inr": "100.00", "payment_ref": "UTR-NOWHERE"},
        )
        read = await http.get(f"/v1/admin/tenants/{missing}/credits", headers=_headers(token))

    assert posted.status_code == 404, posted.text
    assert read.status_code == 404, read.text


async def test_every_route_declares_a_permission() -> None:
    """The boot assertion the integrator's `main.py` runs (BACKEND-PATTERNS §7) — run
    here so a missing declaration fails in this module, not at their mount."""
    application = FastAPI()
    application.include_router(credit_router)
    assert_policy_registry_complete(application)


async def test_a_topup_by_a_principal_with_no_user_records_the_payment_without_a_recorder() -> None:
    """An admin principal carrying no `user_id` — and the audit meta omits the key.

    NOT a hypothetical shape: `Principal(realm="admin", user_id=None, …)` is what the
    platform-config and secrets paths already construct, and `record_topup` guards on
    `if principal.user_id` precisely because it can be absent. The guard's FALSE arm had
    never been driven, so nothing proved what happens on the other side of it — and the
    two candidates are both bad. `str(None)` would write `"recorded_by": "None"` into an
    APPEND-ONLY row (hard rule 4), where it cannot be corrected by an UPDATE and would
    read to an auditor as a recorder named None; a bare `principal.user_id` would write a
    JSON null and make "nobody recorded it" and "we did not capture who" the same value.

    The right answer is the key's ABSENCE, which is what this pins. Money still moves:
    a top-up that refused because nobody was logged in would be a worse failure than a
    slightly thinner audit row.

    FAILS IF: the guard is removed (a `recorded_by` of `"None"` appears), or the route
    starts refusing a principal without a user.
    """
    tenant_id = await _tenant()
    application = _app()
    # The route's OWN dependency object, taken off the annotation. `requires(...)` builds a
    # fresh callable per call, so overriding on a newly-built one keys a different object,
    # the real guard still runs, and the test 401s while proving nothing.
    guard = credit_routes.CreditsWrite.__metadata__[0].dependency
    application.dependency_overrides[guard] = lambda: Principal(
        realm="admin", user_id=None, tenant_id=None, role="operator"
    )

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://api") as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            json={"amount_inr": "1200.00", "payment_ref": "UTR-NO-USER-1", "note": "bank sweep"},
        )

    assert posted.status_code == 200, posted.text
    assert posted.json()["recorded"] is True

    async with tenant_session(tenant_id) as session:
        meta = (
            await session.execute(
                text(
                    "SELECT meta FROM credit_ledger WHERE tenant_id = :t AND ref = 'UTR-NO-USER-1'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()

    assert meta["source"] == "admin_manual"
    assert "recorded_by" not in meta, (
        "an absent recorder must be an absent KEY — writing the string 'None' into an "
        "append-only row names a recorder who does not exist and cannot be corrected"
    )
    assert meta["note"] == "bank sweep"
