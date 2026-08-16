"""Money audit — the properties every rupee path must hold (hard rules 4 and 7).

These are not surface tests; `credits_test`, `credit_topup_test`, `billing_surfaces_test`
and `invoice_test` already cover the happy shapes. This file exists for the four things
that only break when you go looking:

- **No float ever touches a rupee.** Proven where it is claimed, not assumed: the SQL
  that divides seconds into minutes, the SQL that sums our supplier cost, and every JSON
  body an admin surface emits (a JSON number with a decimal point parses back as a
  Python float, so scanning the parsed body finds any leak).
- **Rounding is deliberate.** ONE mode (half-up, `billing.to_paise`), applied at the
  boundary, immune to the ambient `decimal` context — a global anyone in the process can
  change. And an invoice line multiplies out: `qty * unit == amount`, or the client who
  checks it by hand finds a rupee we cannot explain.
- **Ledger arithmetic is race-free.** Every concurrency test here uses OVERLAPPING
  transactions held open at an explicit barrier, never `gather()` on two calls and a
  hope that they interleave. A test that passes because the race did not happen is a
  test that will pass forever and protect nothing.
- **The panels cannot disagree.** Usage, margin and invoice derive from one computation;
  the runway never promises minutes the compliance gate will refuse.
"""

from __future__ import annotations

import asyncio
import contextlib
import decimal
import uuid
from decimal import ROUND_DOWN, Decimal
from typing import Any

from apps.api.admin import service as admin_service
from apps.api.billing import credit_routes
from apps.api.billing import service as billing
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.invoice import build_invoice
from apps.api.billing.routes import router as invoice_router
from apps.api.billing.service import charge_for_call, get_balance, record_entry
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import install_error_handlers
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# A barrier this test file waits on is either released by the other party (the race
# happened) or times out (the lock stopped the other party getting that far). Both are
# information; neither may hang the suite.
BARRIER_TIMEOUT = 1.0


# --------------------------------------------------------------------- fixtures


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(credit_router)
    application.include_router(invoice_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _admin_token() -> str:
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', 'operator', now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id},
        )
    return f"dev:admin:{clerk_id}"


async def _tenant(plan_tier: str = "self_serve") -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Audit Clinic",
        slug=f"aud-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="books@example.com",
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :i"),
            {"tier": plan_tier, "i": tenant_id},
        )
    return tenant_id, agent_id


async def _verify_kyc(tenant_id: uuid.UUID) -> None:
    """Clear this tenant's subscriber KYC (migration a3f6b1e02d95), so a wallet test
    reaches the wallet question instead of stopping at the identity one."""
    from apps.api.compliance.kyc import record_kyc

    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id, "cid": f"admin_{uuid.uuid4().hex[:12]}"},
        )
    async with tenant_session(tenant_id) as session:
        await record_kyc(
            session,
            tenant_id=tenant_id,
            status="verified",
            document_kind="cin",
            document_ref="U74999TG2026PTC000002",
            verified_by_admin_id=admin_id,
        )


async def _seed_usage(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    minutes: int = 120,
    unit_cost: str = "0.5000",
    monthly_fee: str | None = "9999.00",
    included_min: int = 100,
    overage_rate: str = "8.0000",
) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        if monthly_fee is not None:
            await session.execute(
                text(
                    "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                    "concurrency_ceiling, created_at, updated_at) VALUES (:i, :t, :fee, :inc, "
                    ":rate, 10, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "fee": Decimal(monthly_fee),
                    "inc": included_min,
                    "rate": Decimal(overage_rate),
                },
            )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                ":qty, :cost, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "qty": Decimal(minutes * 60),
                "cost": Decimal(unit_cost),
            },
        )
    return call_id


async def _ledger(tenant_id: uuid.UUID, reason: str | None = None) -> list[tuple[str, Decimal]]:
    sql = "SELECT reason, delta FROM credit_ledger WHERE tenant_id = :t"
    params: dict[str, Any] = {"t": tenant_id}
    if reason is not None:
        sql += " AND reason = :r"
        params["r"] = reason
    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(text(sql + " ORDER BY occurred_at, id"), params)).all()
    return [(str(r[0]), Decimal(str(r[1]))) for r in rows]


def _floats(value: Any, path: str = "$") -> list[str]:
    """Every float reachable in a parsed JSON body, by path. `json.loads` turns a JSON
    number with a decimal point into a Python float, so this finds a money field that
    crossed the wire as a number instead of a string."""
    if isinstance(value, bool):
        return []
    if isinstance(value, float):
        return [f"{path}={value!r}"]
    if isinstance(value, dict):
        return [hit for k, v in value.items() for hit in _floats(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [hit for i, v in enumerate(value) for hit in _floats(v, f"{path}[{i}]")]
    return []


# ------------------------------------------------------- ledger race conditions


async def test_two_overlapping_charges_for_one_call_charge_it_once(monkeypatch: Any) -> None:
    """The post-call pipeline is re-runnable and ARQ retries can overlap, so the two
    runs of ONE call can be in flight at the same moment.

    `charge_for_call` deduplicates on `ref`. If that lookup happens OUTSIDE the
    per-tenant advisory lock, both runs read "not charged yet" and both append — the
    exact check-then-write hole `record_topup` takes the lock early to avoid.

    The barrier makes the overlap certain instead of likely: charge A is held inside
    `record_entry` until charge B has passed its own dedupe (or until the lock proves B
    could not get that far).
    """
    tenant_id, _ = await _tenant()
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500"), reason="topup", ref="seed"
        )

    a_inside = asyncio.Event()
    b_past_dedupe = asyncio.Event()
    seen: dict[str, bool] = {}
    holder: asyncio.Task[Any] | None = None
    real_record_entry = billing.record_entry

    async def traced(session: Any, **kwargs: Any) -> Any:
        nonlocal holder
        task = asyncio.current_task()
        if holder is None:
            holder = task
            a_inside.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(b_past_dedupe.wait(), timeout=BARRIER_TIMEOUT)
            # Sampled while A still holds its transaction open: if B got past its own
            # dedupe in that window, the dedupe is not covered by the lock.
            seen["b_past_dedupe_while_a_open"] = b_past_dedupe.is_set()
        elif task is not holder:
            b_past_dedupe.set()
        return await real_record_entry(session, **kwargs)

    monkeypatch.setattr(billing, "record_entry", traced)

    async def charge(second: bool) -> None:
        if second:
            await a_inside.wait()
        async with tenant_session(tenant_id) as session:
            await charge_for_call(
                session, tenant_id=tenant_id, call_id=call_id, amount_inr=Decimal("30")
            )

    await asyncio.gather(charge(False), charge(True))

    assert seen.get("b_past_dedupe_while_a_open") is False, (
        "the second run reached the ledger writer while the first was still open — "
        "the idempotency check is not inside the advisory lock"
    )
    usage = await _ledger(tenant_id, "usage")
    assert usage == [("usage", Decimal("-30.0000"))], f"one call, one charge, got {usage}"
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("470.0000")


async def test_two_overlapping_topups_of_one_reference_credit_it_once(monkeypatch: Any) -> None:
    """The top-up path's own claim, proved with a barrier rather than a coin flip: the
    advisory lock is taken BEFORE the reference lookup, so a second operator recording
    the same UTR cannot even reach the lookup while the first is open."""
    token = await _admin_token()
    tenant_id, _ = await _tenant()
    ref = f"UTR-BARRIER-{uuid.uuid4().hex[:8]}"
    payload = {"amount_inr": "750.00", "payment_ref": ref}

    a_looked = asyncio.Event()
    b_looked = asyncio.Event()
    seen: dict[str, bool] = {}
    holder: asyncio.Task[Any] | None = None
    real_find = credit_routes._find_topup

    async def traced(session: Any, *, tenant_id: uuid.UUID, ref: str) -> Any:
        nonlocal holder
        task = asyncio.current_task()
        if holder is None:
            holder = task
            found = await real_find(session, tenant_id=tenant_id, ref=ref)
            a_looked.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(b_looked.wait(), timeout=BARRIER_TIMEOUT)
            seen["b_looked_while_a_open"] = b_looked.is_set()
            return found
        if task is not holder:
            b_looked.set()
        return await real_find(session, tenant_id=tenant_id, ref=ref)

    monkeypatch.setattr(credit_routes, "_find_topup", traced)

    async def post(second: bool) -> tuple[int, dict[str, Any]]:
        if second:
            await a_looked.wait()
        async with _client() as http:
            response = await http.post(
                f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=payload
            )
        return response.status_code, response.json()

    results = await asyncio.gather(post(False), post(True))

    assert [status for status, _ in results] == [200, 200], results
    assert seen.get("b_looked_while_a_open") is False, (
        "the second operator read the reference while the first was still open — "
        "the advisory lock is not serializing the check-then-write"
    )
    assert sorted(body["recorded"] for _, body in results) == [False, True]
    assert await _ledger(tenant_id) == [("topup", Decimal("750.0000"))]


async def test_two_overlapping_charges_cannot_both_spend_the_same_balance() -> None:
    """₹100 in the wallet, two ₹80 charges genuinely in flight together. Both
    transactions are open and rendezvous before either touches the ledger, so the
    advisory lock — not the scheduler — is what decides the outcome."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("100"), reason="topup")

    both_open = asyncio.Event()
    opened = 0

    async def charge() -> str:
        nonlocal opened
        try:
            async with tenant_session(tenant_id) as session:
                # Force the transaction to actually start before the rendezvous.
                await session.execute(text("SELECT 1"))
                opened += 1
                if opened == 2:
                    both_open.set()
                await asyncio.wait_for(both_open.wait(), timeout=5.0)
                await record_entry(
                    session, tenant_id=tenant_id, delta=Decimal("-80"), reason="usage"
                )
            return "ok"
        except Exception:
            return "refused"

    results = await asyncio.gather(charge(), charge())
    assert results.count("ok") == 1, f"exactly one charge may succeed, got {results}"

    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == Decimal("20.0000"), "the wallet cannot go below what it held"


async def test_the_balance_is_the_last_entry_written_not_the_last_transaction_started() -> None:
    """`occurred_at DEFAULT now()` is TRANSACTION-start time, not insert time, so two
    correctly serialized writers can land rows in the opposite order to their
    timestamps: a long-running transaction (the post-call pipeline does plenty of work
    before it charges) writes its entry with a timestamp older than a top-up that
    started later and committed first.

    `get_balance` then reads `ORDER BY occurred_at DESC LIMIT 1` and returns the OLDER
    row's `balance_after` — a balance missing a real entry. Everything downstream
    inherits it: the next charge computes from it, the compliance gate gates on it, and
    the credits panel documents that `entries[0].balance_after_inr IS the balance`.
    """
    tenant_id, _ = await _tenant()
    started_early = asyncio.Event()
    late_committed = asyncio.Event()

    async def early_transaction() -> None:
        async with tenant_session(tenant_id) as session:
            # Fixes this transaction's now() before the other one even begins.
            await session.execute(text("SELECT 1"))
            started_early.set()
            await asyncio.wait_for(late_committed.wait(), timeout=5.0)
            await record_entry(
                session, tenant_id=tenant_id, delta=Decimal("50"), reason="topup", ref="early"
            )

    async def late_transaction() -> None:
        await started_early.wait()
        await asyncio.sleep(0.05)  # a strictly later transaction timestamp
        async with tenant_session(tenant_id) as session:
            await record_entry(
                session, tenant_id=tenant_id, delta=Decimal("100"), reason="topup", ref="late"
            )
        late_committed.set()

    await asyncio.gather(early_transaction(), late_transaction())

    entries = await _ledger(tenant_id)
    assert len(entries) == 2, entries
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
    assert balance.amount_inr == sum((delta for _, delta in entries), start=Decimal("0"))
    assert balance.amount_inr == Decimal("150.0000")


async def test_the_newest_entry_the_panel_shows_carries_the_balance_it_reports() -> None:
    """The credits panel's documented invariant (`entries[0].balance_after_inr` IS
    `balance_inr`) — it holds only if the ledger's ordering matches write order."""
    token = await _admin_token()
    tenant_id, _ = await _tenant()
    started_early = asyncio.Event()
    late_committed = asyncio.Event()

    async def early_transaction() -> None:
        async with tenant_session(tenant_id) as session:
            await session.execute(text("SELECT 1"))
            started_early.set()
            await asyncio.wait_for(late_committed.wait(), timeout=5.0)
            await record_entry(
                session, tenant_id=tenant_id, delta=Decimal("25"), reason="adjustment", ref="early"
            )

    async def late_transaction() -> None:
        await started_early.wait()
        await asyncio.sleep(0.05)
        async with tenant_session(tenant_id) as session:
            await record_entry(
                session, tenant_id=tenant_id, delta=Decimal("400"), reason="topup", ref="late"
            )
        late_committed.set()

    await asyncio.gather(early_transaction(), late_transaction())

    async with _client() as http:
        read = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
    body = read.json()
    assert body["balance_inr"] == "425.00"
    assert body["entries"][0]["balance_after_inr"] == body["balance_inr"]


# ------------------------------------------------------------- rounding & floats


async def test_gst_rounds_half_up_at_the_paise_boundary() -> None:
    """₹100.25 subtotal → 18% is ₹18.045 exactly, i.e. a half-paise. Half-up gives
    ₹18.05; banker's rounding (the `decimal` module's silent default) gives ₹18.04.
    Indian tax invoices round half UP, and whichever we pick it has to be a decision
    written down, not whatever the ambient context happened to be."""
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(tenant_id, agent_id, minutes=0, monthly_fee="100.25", included_min=100)
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert invoice["subtotal_inr"] == Decimal("100.25")
    assert invoice["gst_inr"] == Decimal("18.05")
    assert invoice["total_inr"] == Decimal("118.30")


async def test_money_rounding_ignores_the_ambient_decimal_context() -> None:
    """`Decimal.quantize` with no `rounding=` reads a PROCESS-GLOBAL context that any
    library in the image may set. A rupee amount that changes because someone else
    changed a global is not an amount we can defend to a client."""
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(tenant_id, agent_id, minutes=0, monthly_fee="100.27", included_min=100)

    previous = decimal.getcontext().rounding
    decimal.getcontext().rounding = ROUND_DOWN
    try:
        async with tenant_session(tenant_id) as session:
            invoice = await build_invoice(session, tenant_id=tenant_id)
            summary = await billing.usage_summary(session, tenant_id=tenant_id)
    finally:
        decimal.getcontext().rounding = previous

    # 100.27 * 0.18 = 18.0486 → half-up ₹18.05, truncation ₹18.04.
    assert invoice["gst_inr"] == Decimal("18.05")
    assert invoice["total_inr"] == Decimal("118.32")
    assert summary["monthly_fee_inr"] == Decimal("100.27")


async def test_an_overage_line_multiplies_out_to_its_own_amount() -> None:
    """`overage_rate` is NUMERIC(12,4): a plan may quote ₹7.1250/min. Rounding the rate
    to paise for display while billing the unrounded one makes `qty * unit` disagree
    with `amount` on the line the client checks by hand — 20 * ₹7.12 = ₹142.40 against
    a ₹142.50 charge."""
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(
        tenant_id,
        agent_id,
        minutes=120,
        monthly_fee="1000.00",
        included_min=100,
        overage_rate="7.1250",
    )
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
        summary = await billing.usage_summary(session, tenant_id=tenant_id)

    overage = invoice["line_items"][1]
    assert overage["amount_inr"] == Decimal("142.50")
    assert (overage["qty"] * overage["unit_inr"]).quantize(Decimal("0.01")) == overage["amount_inr"]
    assert "7.125" in overage["description"], overage["description"]
    # One source: the rate on the invoice is the rate the usage panel billed.
    assert overage["unit_inr"] == summary["overage_rate_inr"]


async def test_the_invoice_total_is_exactly_its_lines_plus_gst() -> None:
    """No ₹0.01 drift: subtotal is the sum of the line amounts and nothing else, GST is
    applied once, and the total is those two added."""
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(
        tenant_id,
        agent_id,
        minutes=137,
        monthly_fee="12345.67",
        included_min=100,
        overage_rate="6.5000",
    )
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    lines = sum((item["amount_inr"] for item in invoice["line_items"]), start=Decimal("0"))
    assert invoice["subtotal_inr"] == lines
    assert invoice["gst_inr"] == (lines * invoice["gst_rate_pct"] / Decimal("100")).quantize(
        Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
    )
    assert invoice["total_inr"] == invoice["subtotal_inr"] + invoice["gst_inr"]
    for item in invoice["line_items"]:
        assert isinstance(item["qty"], Decimal), f"a quantity beside money is not an int: {item}"
        assert (item["qty"] * item["unit_inr"]).quantize(Decimal("0.01")) == item["amount_inr"]


async def test_the_sql_behind_the_money_never_returns_a_float() -> None:
    """The two expressions that could quietly become `double precision`: seconds
    divided into minutes, and qty * our supplier unit cost. Postgres keeps both in
    `numeric` — assert it, because `60.0` reads like a float literal and the next
    person to "fix" it into `::float8` would break every rupee downstream in a way no
    other test in this file would notice.

    THE FIRST EXPRESSION NO LONGER LIVES IN `billing/service.py` and this test is kept
    anyway. The seconds-to-minutes division moved into Python (`_SECONDS_PER_MINUTE`,
    a `Decimal`) because the per-rung minutes have to be allocated against their own
    total and two SQL divisions of the same seconds are two roundings — see
    `tests/money_walk_test.py`. What the SQL still returns is the SUM of `telephony_s`,
    and `numeric / numeric` is what a reader will reach for the moment a second caller
    wants minutes out of the database; the day it comes back a float, the Python side
    would build a `Decimal` from binary error. So the assertion outlives the call site
    it was written for, on purpose."""
    async with untenanted_session() as session:
        minutes_type = (
            await session.execute(
                text(
                    "SELECT pg_typeof(COALESCE(SUM(qty) FILTER (WHERE unit_type = "
                    "'telephony_s'), 0) / 60.0) FROM usage_events"
                )
            )
        ).scalar()
        cost_type = (
            await session.execute(
                text(
                    "SELECT pg_typeof(COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0)) "
                    "FROM usage_events"
                )
            )
        ).scalar()
        sample = (
            await session.execute(text("SELECT (20::numeric) / 60.0, (1::numeric) / 3"))
        ).first()

    assert str(minutes_type) == "numeric", minutes_type
    assert str(cost_type) == "numeric", cost_type
    assert sample is not None
    assert isinstance(sample[0], Decimal) and isinstance(sample[1], Decimal)
    # 20 significant digits is numeric division; float64 would stop at ~17.
    assert str(sample[1]).startswith("0.33333333333333333333")


async def test_no_admin_money_surface_puts_a_float_on_the_wire() -> None:
    """A JSON number with a decimal point parses back as a binary float on the client
    side, so money crosses the wire as a STRING in every direction. Scan the whole
    parsed body rather than the fields we remembered to name."""
    token = await _admin_token()
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(
        tenant_id,
        agent_id,
        minutes=137,
        monthly_fee="12345.67",
        included_min=100,
        overage_rate="7.1250",
    )
    async with _client() as http:
        topup = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "2500.10", "payment_ref": f"UTR-{uuid.uuid4().hex[:10]}"},
        )
        wallet = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
        invoice = await http.get(f"/v1/admin/tenants/{tenant_id}/invoice", headers=_headers(token))

    for name, response in (("topup", topup), ("credits", wallet), ("invoice", invoice)):
        assert response.status_code == 200, (name, response.text)
        assert _floats(response.json()) == [], (name, _floats(response.json()))

    assert topup.json()["amount_inr"] == "2500.10"
    assert wallet.json()["balance_inr"] == "2500.10"


async def test_no_money_field_leaves_the_service_layer_as_a_float() -> None:
    """The dicts themselves, before any serializer gets a chance to hide it."""
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(tenant_id, agent_id, minutes=137, monthly_fee="12345.67", included_min=100)
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id)

    for name, payload in (("usage", summary), ("margin", margin), ("invoice", invoice)):
        assert _floats(payload) == [], (name, _floats(payload))


# ------------------------------------------------------- one source of the truth


async def test_the_usage_panel_the_margin_panel_and_the_invoice_agree() -> None:
    """Three surfaces, one computation. If any of them re-derives the numbers itself,
    the client's screen and the invoice we send eventually disagree by a rupee and
    nobody can say which is right."""
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(
        tenant_id,
        agent_id,
        minutes=137,
        monthly_fee="12345.67",
        included_min=100,
        overage_rate="6.5000",
        unit_cost="0.4000",
    )
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert summary["minutes_used"] == margin["minutes_used"] == invoice["usage"]["minutes_used"]
    assert summary["calls"] == margin["calls"] == invoice["usage"]["calls"]
    billable = summary["monthly_fee_inr"] + summary["overage_cost_inr"]
    assert invoice["subtotal_inr"] == billable
    assert margin["revenue_inr"] == billable
    assert margin["margin_inr"] == margin["revenue_inr"] - margin["cost_inr"]


async def test_usage_is_scoped_to_the_tenant_the_caller_named() -> None:
    """`usage_summary` reads the plan, the org and the spend state by `tenant_id` but
    left `usage_events` to RLS alone. Under a session scoped to someone else that
    silently pairs THIS tenant's plan with THAT tenant's minutes — a money query whose
    answer depends on which session it happened to be handed."""
    a_tenant, a_agent = await _tenant("managed")
    b_tenant, b_agent = await _tenant("managed")
    await _seed_usage(a_tenant, a_agent, minutes=500, monthly_fee="1000.00", included_min=0)
    await _seed_usage(b_tenant, b_agent, minutes=7, monthly_fee="2000.00", included_min=0)

    async with tenant_session(a_tenant) as session:
        crossed = await billing.usage_summary(session, tenant_id=b_tenant)
    assert crossed["minutes_used"] == Decimal("0.00"), (
        "a tenant-scoped session must not lend its own minutes to another tenant's panel"
    )


async def test_the_runway_never_promises_minutes_the_compliance_gate_will_refuse() -> None:
    """ "About N minutes left" is the number an owner plans around. The gate refuses
    every outbound call the moment `spend_state.capped` is true, so a capped account has
    no minutes left — whatever the plan's hard cap says is still unused."""
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(tenant_id, agent_id, minutes=120, monthly_fee="9999.00", included_min=100)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE plans SET hard_cap_min = 500 WHERE tenant_id = :t"), {"t": tenant_id}
        )
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, capped, "
                "created_at, updated_at) VALUES (:t, :m, 120, 960, true, now(), now()) "
                "ON CONFLICT (tenant_id) DO UPDATE SET capped = true"
            ),
            {"t": tenant_id, "m": billing.current_billing_month()},
        )
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500099"
        )

    assert summary["capped"] is True
    assert decision.allowed is False and decision.rule == "spend_cap"
    assert summary["minutes_left"] == 0, (
        "the panel offered runway on an account the gate refuses to dial for"
    )


async def test_a_managed_tenants_empty_wallet_shortens_neither_the_runway_nor_the_dial() -> None:
    """D-34, both halves of it. The gate checks credits for `self_serve`/`trial` ONLY,
    so a managed client's wallet must not appear in their runway either — clamping the
    panel on a balance the gate ignores would put a number on screen that predicts a
    refusal which never comes."""
    tenant_id, agent_id = await _tenant("managed")
    await _seed_usage(tenant_id, agent_id, minutes=120, monthly_fee="9999.00", included_min=100)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE plans SET hard_cap_min = 500 WHERE tenant_id = :t"), {"t": tenant_id}
        )
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-100"),
            reason="usage",
            allow_negative=True,
        )
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500097"
        )

    assert summary["minutes_left"] == 380, "a managed runway is the cap, never the wallet"
    assert decision.rule != "no_credits"


async def test_an_exhausted_wallet_reads_the_same_on_the_panel_and_at_the_gate() -> None:
    """Self-serve: `Balance.is_exhausted` (`<= 0`) is what the gate enforces, so the
    panel must not show minutes to an account that cannot dial."""
    tenant_id, agent_id = await _tenant("self_serve")
    # Identity before money: `check_dispatch` asks about subscriber KYC before the
    # wallet for a self-serve tenant (migration a3f6b1e02d95), so a test about the
    # WALLET has to clear the identity gate first — exactly as production does.
    await _verify_kyc(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("100"), reason="topup")
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-100"),
            reason="usage",
            allow_negative=True,
        )
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500098"
        )

    assert summary["minutes_left"] == 0
    assert decision.allowed is False and decision.rule == "no_credits"
