"""A trial client's absorbed usage reaches every admin screen that reports it.

Reproduces the founder's report of 10 Oct 2026 (Raghava Organics: prepaid, on a trial, no
calls, ₹0 credit): the trial panel showed ₹1.08 "cost to Calevate so far" while the client's
Spend screen and Overview showed no usage at all. The production ledger held eight
`ai_assist_ktok_*` rows, all with a `ref`: three assistant answers (`copilot`) and one
standby answer (`assist_standby`). The rows below are those rows' shape and prices.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.trials import start_trial
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

#: (feature, model, qty_in, price_in, qty_out, price_out) — the production rows.
_PROD_ROWS = (
    ("copilot", "gemini-2.5-flash-lite", "34.1280", "0.0096", "0.0710", "0.0383"),
    ("copilot", "gemini-2.5-flash-lite", "33.5190", "0.0096", "0.0850", "0.0383"),
    ("copilot", "gemini-2.5-flash-lite", "16.5670", "0.0096", "0.0290", "0.0383"),
    ("assist_standby", "sarvam-105b", "7.5000", "0.0293", "0.6630", "0.0732"),
)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _admin_token() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


async def _trial_client_with_prod_rows() -> tuple[UUID, Decimal]:
    created = await admin_service.create_organization(
        name="Usage Visibility Organics",
        slug=f"usage-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
        plan_tier="prepaid",
    )
    tenant_id = UUID(str(created["id"]))
    expected = Decimal("0")
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session, tenant_id=tenant_id, days=5, actor_user_id=None, free_minutes=1000
        )
    async with tenant_session(tenant_id) as session:
        for feature, model, q_in, p_in, q_out, p_out in _PROD_ROWS:
            ref = f"assist:{uuid7()}"
            meta = json.dumps({"kind": "ai_assist", "feature": feature, "model": model, "ref": ref})
            for unit, qty, price in (
                ("ai_assist_ktok_in", q_in, p_in),
                ("ai_assist_ktok_out", q_out, p_out),
            ):
                await session.execute(
                    text(
                        "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                        "unit_cost_paid, ref, occurred_at, meta, created_at) VALUES (:id, :tid, "
                        "NULL, :unit, :qty, :price, :ref, now(), CAST(:meta AS jsonb), now())"
                    ),
                    {
                        "id": uuid7(),
                        "tid": tenant_id,
                        "unit": unit,
                        "qty": Decimal(qty),
                        "price": Decimal(price),
                        "ref": ref,
                        "meta": meta,
                    },
                )
                expected += Decimal(qty) * Decimal(price)
    return tenant_id, expected


async def test_spend_and_trial_report_the_same_absorbed_cost_for_a_trial_client() -> None:
    tenant_id, expected = await _trial_client_with_prod_rows()
    token = await _admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as http:
        spend = await http.get(f"/v1/admin/tenants/{tenant_id}/spend", headers=headers)
        trial = await http.get(f"/v1/admin/tenants/{tenant_id}/trial", headers=headers)
    assert spend.status_code == 200, spend.text
    assert trial.status_code == 200, trial.text
    body = spend.json()
    trial_body = trial.json()
    paise = expected.quantize(Decimal("0.01"))

    assert body["ai_assist"] is not None, body
    assert body["ai_assist"]["requests"] == 4
    assert Decimal(body["ai_assist"]["used_inr"]) == paise

    # ONE reader behind all three screens: the month's all-in figure on Spend (which the
    # Overview renders) and the trial's cost are the same rupees, split the same way.
    month, window = body["cost_all_in"], trial_body["cost_breakdown"]
    assert month == window
    assert Decimal(trial_body["cost_to_us_inr"]) == Decimal(month["total_inr"]) == paise
    assert month["assistant_requests"] == 4
    assert Decimal(month["assistant_inr"]) == paise
    assert month["knowledge_inr"] == "0.00" and month["knowledge_requests"] == 0
    assert month["calls_inr"] == "0.00" and month["calls"] == 0
    # The call margin stays call-only (D-127 G-3): the absorbed AI is not in its cost.
    assert body["cost_inr"] == "0.00"


async def test_a_zero_token_ai_leg_costs_nothing_on_the_trial_panel() -> None:
    """An embedding writes its output leg at `qty = 0`. On the AI ledger that is zero
    tokens; the call rows' rule that a zero-`qty` row carries its whole leg cost (D-370)
    must not price it at the per-thousand output rate."""
    tenant_id, expected = await _trial_client_with_prod_rows()
    async with tenant_session(tenant_id) as session:
        ref = f"assist:{uuid7()}"
        meta = json.dumps({"kind": "ai_assist", "feature": "kb_embed", "ref": ref})
        for unit, qty, price in (
            ("ai_assist_ktok_in", Decimal("10.0000"), Decimal("0.0020")),
            ("ai_assist_ktok_out", Decimal("0"), Decimal("0.5000")),
        ):
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, ref, occurred_at, meta, created_at) VALUES (:id, :tid, "
                    "NULL, :unit, :qty, :price, :ref, now(), CAST(:meta AS jsonb), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "unit": unit,
                    "qty": qty,
                    "price": price,
                    "ref": ref,
                    "meta": meta,
                },
            )
    token = await _admin_token()
    async with _client() as http:
        trial = await http.get(
            f"/v1/admin/tenants/{tenant_id}/trial", headers={"Authorization": f"Bearer {token}"}
        )
    assert trial.status_code == 200, trial.text
    body = trial.json()
    total = (expected + Decimal("0.0200")).quantize(Decimal("0.01"))
    assert Decimal(body["cost_to_us_inr"]) == total
    assert body["cost_breakdown"]["knowledge_inr"] == "0.02"
    assert body["cost_breakdown"]["knowledge_requests"] == 1
