"""Per-agent and per-call attribution of both directions of the money (D-12, hard rule 7).

Four properties, and every one of them is about a number being right rather than roughly
right:

- **Our supplier cost never reaches the client realm.** `unit_cost_paid` is the figure
  D-12 put on every usage row so margin is a query, and it is commercially ours. The one
  regression here that would cost real money is a serializer widened to publish it, so it
  is asserted twice: over the response MODELS' own field lists (a static property of the
  types, which fails the day someone adds the field) and over the live JSON of the client
  route (which fails the day someone adds it somewhere the field walk cannot see).
- **Every breakdown is a partition.** Minutes, cost and charge each add up to the figure
  another surface already publishes — `usage_summary.minutes_used`,
  `margin_for_tenant.cost_inr`, `usage_summary.spend_used_inr` — exactly, not to within a
  paisa.
- **A fact is labelled a fact and a share is labelled a share.** A prepaid client's
  per-call charge is the rupees that left their wallet; a managed client's is an
  allocation, and `charge_basis` says which.
- **Decimal end to end.** A float anywhere on this path is how a client dispute starts.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import attribution, spend_routes
from apps.api.billing import service as billing
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.billing.attribution import period_attribution
from apps.api.billing.service import to_paise
from apps.api.billing.spend_routes import (
    AgentChargeOut,
    CallChargeOut,
    SpendOut,
)
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# Anything whose NAME would be our supplier pricing. Substrings rather than an exact
# match: the field this test exists to catch would be called `cost_inr`, `unit_cost_paid`,
# `supplier_cost` or `margin_inr`, and an exact-name list would miss every one of those
# spellings but the one somebody happened to write down.
COST_SHAPED = ("cost", "paid", "margin", "supplier")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_member(tenant_id: UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{user_id}"


async def _make_admin() -> str:
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


async def _tenant(
    *,
    monthly_fee: str | None = "9999.00",
    included_min: int = 100,
    overage_rate: str = "8.0000",
    overage_rate_value: str | None = None,
) -> tuple[UUID, UUID]:
    """A fresh org with a plan. Returns (tenant_id, its first agent's id)."""
    created = await admin_service.create_organization(
        name="Spend Clinic",
        slug=f"spend-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    assert isinstance(tenant_id, UUID) and isinstance(agent_id, UUID)
    if monthly_fee is not None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                    "overage_rate_value, concurrency_ceiling, created_at, updated_at) "
                    "VALUES (:i, :t, :fee, :inc, :rate, :vrate, 10, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "fee": Decimal(monthly_fee),
                    "inc": included_min,
                    "rate": Decimal(overage_rate),
                    "vrate": Decimal(overage_rate_value) if overage_rate_value else None,
                },
            )
    return tenant_id, agent_id


async def _second_agent(tenant_id: UUID, name: str = "Outbound") -> UUID:
    agent_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, created_at, "
                "updated_at) VALUES (:id, :tid, :name, 'outbound', 'Idi AI assistant.', "
                "'Idi AI assistant.', 'This call is being recorded.', 'live', 'fake', "
                "now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "name": name},
        )
    return agent_id


async def _metered_call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    seconds: int,
    unit_cost: str,
    tts_tier: str | None = "premium",
    currency_stated: bool = False,
    source_currency: str | None = "USD",
    at: datetime | None = None,
) -> UUID:
    """One completed call with one `telephony_s` row, the shape `pipeline._meter` writes.

    `at` stamps `occurred_at` — the column every money window is cut on — so a test can
    place a call on either side of an IST month boundary. `None` is `now()`, which is what
    the meter itself writes and what every other case here wants.
    """
    call_id = uuid7()
    meta: dict[str, Any] = {
        "engine": "fake",
        "tts_tier": tts_tier,
        "tts_tier_source": "agent_config",
        "currency_stated": currency_stated,
    }
    if source_currency is not None:
        meta["source_currency"] = source_currency
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, started_at, duration_s, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500001', 'completed', now(), :d, now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "d": seconds,
            },
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'telephony_s', :qty, :cost, COALESCE(:at, now()), CAST(:m AS jsonb), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "qty": Decimal(seconds),
                "cost": Decimal(unit_cost),
                "at": at,
                "m": json.dumps(meta),
            },
        )
    return call_id


async def _metered_assist(
    tenant_id: UUID,
    *,
    tokens_in: int = 5_000,
    tokens_out: int = 1_500,
    feature: str | None = None,
) -> Decimal:
    """One dashboard-AI assist, metered exactly as the copilot route meters it.

    Goes through the real writer (`record_ai_assist_usage`) rather than an INSERT, so the
    row shape — `ai_assist_ktok_*` unit types, `call_id NULL`, server-minted `ref`, price
    derived from the model — is the one production produces. Returns the rupees it cost us.
    """
    from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
    from apps.api.core.settings import get_settings
    from apps.api.crm.assist import ASSIST_FEATURE_COPILOT

    async with tenant_session(tenant_id) as session:
        metered = await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=get_settings().azure_openai_model,
            feature=feature or ASSIST_FEATURE_COPILOT,
        )
    assert metered.recorded, "the assist did not land"
    return metered.cost_inr


def _field_names(model: type[BaseModel], depth: int = 0) -> set[str]:
    """Every field name reachable from a response model, nested models included.

    Walks the ANNOTATIONS rather than an instance, so an optional branch that happens to
    be None on the day the test runs is still inspected.
    """
    names: set[str] = set()
    if depth > 4:
        return names
    for name, field in model.model_fields.items():
        names.add(name)
        candidates = [field.annotation, *getattr(field.annotation, "__args__", ())]
        for candidate in candidates:
            for arg in (candidate, *getattr(candidate, "__args__", ())):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    names |= _field_names(arg, depth + 1)
    return names


# --------------------------------------------------- the one that would cost real money


def test_the_client_spend_models_declare_no_cost_field_anywhere() -> None:
    """`unit_cost_paid` is OUR supplier pricing and a client who can see it is a client
    negotiating against it (`admin/routes.py::tenant_margin`, `crm/schemas.UsagePanelOut`).

    Asserted over the TYPES rather than over one response, because the failure this
    guards against is a serializer widened months from now — and a widening is a field
    added to a model, which this sees whether or not any fixture happens to populate it.
    """
    for model in (SpendOut, AgentChargeOut, CallChargeOut):
        leaked = sorted(
            name
            for name in _field_names(model)
            if any(shape in name.lower() for shape in COST_SHAPED)
        )
        assert not leaked, (
            f"{model.__name__} publishes {leaked} to the CLIENT realm — our supplier "
            "cost and our margin belong to the admin spend page (hard rule 7 / D-12). "
            "If a shared serializer would expose it, split the serializer."
        )


async def test_the_client_spend_route_returns_no_cost_bearing_key() -> None:
    """The same rule over the live JSON, which catches what a field walk cannot: a key
    added by a serializer override, an alias, or a nested `extra` that slipped through."""
    tenant_id, agent_id = await _tenant()
    await _metered_call(tenant_id, agent_id, seconds=600, unit_cost="0.5000")
    token = await _make_member(tenant_id)

    async with _client() as http:
        response = await http.get("/v1/billing/spend", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    body = response.json()

    def walk(node: object, path: str = "") -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if any(shape in key.lower() for shape in COST_SHAPED):
                    found.append(f"{path}.{key}")
                found += walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found += walk(value, f"{path}[{index}]")
        return found

    assert walk(body) == [], "the client spend page must never carry our supplier cost"
    # And the page really did have something to say — an empty response would pass the
    # assertion above for the wrong reason.
    assert body["calls"] == 1
    assert body["by_agent"][0]["charged_inr"] is not None


# ------------------------------------------------------------------- cost attribution


async def test_cost_is_attributed_to_the_agent_that_ran_the_call() -> None:
    """The join through `calls.agent_id` is the whole feature: no `agent_id` column on
    `usage_events`, and the answer is still per agent."""
    tenant_id, reception = await _tenant()
    outbound = await _second_agent(tenant_id, "Outbound Sales")
    # 600 s at ₹0.50/s = ₹300; 120 s at ₹0.25/s = ₹30.
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")
    await _metered_call(tenant_id, outbound, seconds=120, unit_cost="0.2500")

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)
        # The NAME is read back from `agents` rather than typed here: the seeded
        # receptionist is named from the vertical template, and a literal in this test
        # would pin the template instead of the join it is about.
        seeded = (
            await session.execute(text("SELECT name FROM agents WHERE id = :a"), {"a": reception})
        ).scalar()

    by_id = {a.agent_id: a for a in period.by_agent}
    assert by_id[reception].cost_inr == Decimal("300.00")
    assert by_id[reception].agent_name == seeded
    assert by_id[outbound].cost_inr == Decimal("30.00")
    assert by_id[outbound].agent_name == "Outbound Sales"
    assert by_id[reception].calls == 1 and by_id[outbound].calls == 1


async def test_every_breakdown_sums_to_the_figure_another_panel_already_publishes() -> None:
    """Three partitions, three identities, and `allocate_paise` is what makes them exact.

    The costs are chosen to carry four decimals per call (601 s and 401 s at ₹0.0125/s are
    ₹7.5125 and ₹5.0125) — the same shape that made `tier_usage`'s rungs publish ₹12.52
    beside a `cost_inr` of ₹12.53 before D-371.
    """
    tenant_id, reception = await _tenant()
    outbound = await _second_agent(tenant_id)
    await _metered_call(tenant_id, reception, seconds=601, unit_cost="0.0125")
    await _metered_call(tenant_id, outbound, seconds=401, unit_cost="0.0125")

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)
        usage = await billing.usage_summary(session, tenant_id=tenant_id)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)

    assert sum(c.minutes for c in period.by_call) == usage["minutes_used"]
    assert sum(c.cost_inr for c in period.by_call) == margin["cost_inr"] == period.cost_inr
    assert sum(u.cost_inr for u in period.by_unit) == period.cost_inr
    assert sum(a.cost_inr for a in period.by_agent) == period.cost_inr
    assert sum(a.minutes for a in period.by_agent) == usage["minutes_used"]
    assert sum(a.charged_inr for a in period.by_agent) == period.itemised_charge_inr


# ---------------------------------------------------------------- charge attribution


async def test_a_managed_month_divides_its_calling_charge_across_its_calls_exactly() -> None:
    """120 minutes, 100 included, ₹8/min → ₹160.00 of overage, and the per-call shares add
    to ₹160.00 — not ₹159.99, which is what `to_paise` on each share would publish."""
    tenant_id, reception = await _tenant(included_min=100, overage_rate="8.0000")
    outbound = await _second_agent(tenant_id)
    # Three calls whose minute shares do not divide into paise cleanly.
    await _metered_call(tenant_id, reception, seconds=3607, unit_cost="0.0100")
    await _metered_call(tenant_id, reception, seconds=2003, unit_cost="0.0100")
    await _metered_call(tenant_id, outbound, seconds=1590, unit_cost="0.0100")

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)
        usage = await billing.usage_summary(session, tenant_id=tenant_id)

    assert period.charge_basis == "allocated"
    # THE INVOICE'S OWN FIGURE, not the cap counter. `spend_used_inr` reads
    # `spend_state.billed_inr` while a month is open, and that counter moves only when
    # the METER runs -- so anchoring the itemisation there published a page of 0.00
    # beside an overage of 160.00. This assertion is what pins the anchor.
    assert period.period_charge_inr == usage["overage_cost_inr"] == Decimal("160.00")
    assert period.itemised_charge_inr == period.period_charge_inr
    assert period.itemisation_residual_inr == Decimal("0.00")
    assert period.residual_reason is None, "nothing to explain when the parts add up"
    assert sum(c.charged_inr for c in period.by_call) == period.period_charge_inr
    # ...and the retainer plus the calling charge IS the margin card's revenue, so the
    # client's page and the operator's cannot describe one month with two totals.
    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
    assert (period.retainer_inr or Decimal("0.00")) + period.period_charge_inr == margin[
        "revenue_inr"
    ]


async def test_the_value_rung_carries_less_of_the_bill_than_the_premium_one() -> None:
    """The allocation is by relative sales value, so two calls of EQUAL length on
    different rungs do not carry equal shares when the plan quotes two rates.

    Where a plan quotes ONE rate the same expression reduces to plain minutes, which is
    what the test above already pins — this is the half that would be silently wrong if
    the weight ignored the rung.
    """
    tenant_id, reception = await _tenant(
        included_min=0, overage_rate="8.0000", overage_rate_value="2.0000"
    )
    premium = await _metered_call(
        tenant_id, reception, seconds=600, unit_cost="0.0100", tts_tier="premium"
    )
    value = await _metered_call(
        tenant_id, reception, seconds=600, unit_cost="0.0100", tts_tier="value"
    )

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)

    charged = {c.call_id: c.charged_inr for c in period.by_call}
    # ₹8 against ₹2 is a 4:1 weight on equal minutes.
    assert charged[premium] == charged[value] * 4
    assert charged[premium] + charged[value] == period.period_charge_inr


async def test_a_prepaid_call_is_charged_what_actually_left_the_wallet() -> None:
    """A fact, not a share: `charge_for_call` debits the wallet once per call keyed by
    `call_id`, and that row is what a prepaid client can check this page against."""
    tenant_id, reception = await _tenant(monthly_fee=None)
    call_id = await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.0100")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
        await billing.record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500.00"), reason="topup", ref="rzp_spend"
        )
        # ₹6.00/min list price x 10 minutes.
        await billing.charge_for_call(
            session, tenant_id=tenant_id, call_id=call_id, amount_inr=Decimal("60.0000")
        )
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.charge_basis == "wallet_debit"
    assert period.by_call[0].call_id == call_id
    assert period.by_call[0].charged_inr == Decimal("60.00")
    assert period.itemised_charge_inr == Decimal("60.00")


async def test_a_call_that_took_nothing_off_the_wallet_is_charged_zero_not_a_share() -> None:
    """`charge_for_call` returns early on a non-positive amount, so a prepaid call can
    legitimately have no debit. It must publish ₹0.00 — an allocation would invent a
    charge the client's balance never saw."""
    tenant_id, reception = await _tenant(monthly_fee=None)
    await _metered_call(tenant_id, reception, seconds=3, unit_cost="0.0100")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.by_call[0].charged_inr == Decimal("0.00")
    assert period.itemised_charge_inr == Decimal("0.00")


# ----------------------------------------------------------------- honesty about cost


async def test_a_cost_read_in_an_assumed_currency_says_so() -> None:
    """OPERATIONS §2 gate 7: `AgentExecution` declares no `currency`, so `currency_stated`
    is False on every row the adapter writes today and every cost figure on the admin page
    is scaled by an assumption. A page that presented it as certain would be the quiet
    failure `runbooks/vendor-cost-unit.md` exists for."""
    tenant_id, reception = await _tenant()
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.cost_currency == "USD"
    assert period.cost_currency_stated is False
    assert period.by_call[0].cost_currency_assumed is True
    assert period.by_agent[0].cost_currency_assumed is True


async def test_a_vendor_stated_currency_is_not_reported_as_an_assumption() -> None:
    """The flag is read off what the LEDGER recorded, not inferred — so the day the vendor
    starts naming its currency the page stops warning about it, without a code change."""
    tenant_id, reception = await _tenant()
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000", currency_stated=True)

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.cost_currency_stated is True
    assert period.by_call[0].cost_currency_assumed is False


# -------------------------------------------------------------------- realms and RLS


async def test_one_tenants_calls_never_appear_in_anothers_attribution() -> None:
    a_tenant, a_agent = await _tenant()
    b_tenant, b_agent = await _tenant()
    await _metered_call(a_tenant, a_agent, seconds=600, unit_cost="0.5000")
    await _metered_call(b_tenant, b_agent, seconds=60, unit_cost="0.1000")

    async with tenant_session(a_tenant) as session:
        a_period = await period_attribution(session, tenant_id=a_tenant)
    async with tenant_session(b_tenant) as session:
        b_period = await period_attribution(session, tenant_id=b_tenant)

    assert a_period.cost_inr == Decimal("300.00") and a_period.calls == 1
    assert b_period.cost_inr == Decimal("6.00") and b_period.calls == 1
    assert {c.call_id for c in a_period.by_call} & {c.call_id for c in b_period.by_call} == set()


async def test_the_admin_page_publishes_the_margin_cards_own_numbers() -> None:
    """ONE definition of margin. A second one computed on this page is the drift
    `billing/service.py` has already paid for twice."""
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, reception, seconds=7200, unit_cost="0.5000")
    token = await _make_admin()

    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/spend", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()

    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)

    assert body["revenue_inr"] == str(margin["revenue_inr"])
    assert body["cost_inr"] == str(margin["cost_inr"])
    assert body["margin_inr"] == str(margin["margin_inr"])
    assert body["margin_pct"] == str(margin["margin_pct"])
    # And the itemisation really is beside it, with our cost on every row.
    assert body["by_agent"][0]["cost_inr"] == "3600.00"
    assert body["top_calls"][0]["cost_inr"] == "3600.00"
    assert body["cost_currency_stated"] is False


async def test_absorbed_ai_cost_surfaces_on_the_admin_board_with_zero_calls() -> None:
    """THE REPORTED DEFECT: a client running the in-app copilot generates absorbed AI cost
    that the money board could not see, because `period_attribution` filters `_NOT_AI_UNITS`
    (the D-127 G-3 rule that keeps our absorbed cost out of the CALL margin). With no calls
    the whole board read ₹0.00 / "No metered units" while we were spending real rupees on
    the client's copilot.

    The header call-margin figures stay call-only — the absorbed cost is its OWN line and
    is NOT folded into `cost_inr`/`margin_inr`, so the partition the rest of the page rests
    on is untouched — and the copilot spend is now visible where an operator looks.
    """
    tenant_id, _ = await _tenant(monthly_fee="9999.00", included_min=100)
    cost = await _metered_assist(tenant_id)
    token = await _make_admin()

    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/spend", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()

    # The board is no longer blind to it.
    assert body["ai_assist"] is not None, "the absorbed copilot cost must be visible"
    assert body["ai_assist"]["requests"] == 1
    assert Decimal(body["ai_assist"]["used_inr"]) > 0
    # ...and it equals the AI ledger's own reader to the paisa — one computation, not a
    # second spelling.
    async with tenant_session(tenant_id) as session:
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    assert Decimal(body["ai_assist"]["used_inr"]) == to_paise(quota.used_inr)
    assert to_paise(cost) == to_paise(quota.used_inr), "the writer and the reader agree"

    # The CALL margin is call-only and undisturbed: no calls, so ₹0 cost, and the absorbed
    # AI rupees are NOT in it.
    assert body["calls"] == 0
    assert body["cost_inr"] == "0.00", "absorbed AI cost must not enter the call cost"
    assert body["by_unit"] == [], "AI units never appear in the call-cost partition"
    assert not any(u["unit_type"].startswith("ai_assist") for u in body["by_unit"])


async def test_absorbed_ai_cost_is_absent_from_a_month_that_generated_none() -> None:
    """Null, not ₹0.00: "they ran the copilot and it cost us nothing measurable" and "they
    never opened it" are different facts, the same distinction `unattributed` and
    `margin_pct` already draw on this page."""
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")
    token = await _make_admin()

    async with _client() as http:
        body = (
            await http.get(
                f"/v1/admin/tenants/{tenant_id}/spend",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()

    assert body["ai_assist"] is None
    # The call side is unaffected — the page still works exactly as before for a month with
    # calls and no assists.
    assert body["by_unit"][0]["unit_type"] == "telephony_s"


async def test_absorbed_ai_cost_never_reaches_the_client_spend_realm() -> None:
    """Our absorbed cost is admin-realm only. The client is not billed AI assist — they see
    their AI usage on their own AI-assistance screen (`GET /v1/billing/ai-quota`), never as
    "spend" here — so `SpendOut` carries no `ai_assist` field and the client route's JSON
    carries no such key even on a month that generated one.

    Belt and braces alongside `test_the_client_spend_route_returns_no_cost_bearing_key`,
    which would miss this: `used_inr` matches none of its cost-shaped substrings."""
    tenant_id, _ = await _tenant(monthly_fee=None)
    await _metered_assist(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
    token = await _make_member(tenant_id)

    async with _client() as http:
        response = await http.get("/v1/billing/spend", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "ai_assist" not in body, "absorbed AI cost is admin-realm only"
    assert "ai_assist" not in SpendOut.model_fields


async def test_the_two_tenants_absorbed_ai_costs_do_not_cross() -> None:
    """The absorbed-AI read is inside the client's own `tenant_session`, so RLS scopes it
    exactly as the call attribution beside it — one busy copilot never shows up on another
    client's money board."""
    a_tenant, _ = await _tenant(monthly_fee="9999.00")
    b_tenant, _ = await _tenant(monthly_fee="9999.00")
    await _metered_assist(a_tenant, tokens_in=8_000, tokens_out=2_000)
    token = await _make_admin()

    async with _client() as http:
        a_body = (
            await http.get(
                f"/v1/admin/tenants/{a_tenant}/spend",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        b_body = (
            await http.get(
                f"/v1/admin/tenants/{b_tenant}/spend",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()

    assert a_body["ai_assist"] is not None and a_body["ai_assist"]["requests"] == 1
    assert b_body["ai_assist"] is None, "B ran no assist and must show none of A's"


async def test_a_mistyped_tenant_is_a_404_not_a_page_about_nothing() -> None:
    """A tenant with no usage and a tenant that does not exist both aggregate to zero,
    and a clean ₹0 spend page about a client that is not there is the defect the margin
    card already closed."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{uuid.uuid4()}/spend",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 404


async def test_the_client_route_refuses_a_caller_without_billing_read() -> None:
    """Spend is an owner's business (SEC-COMP §5); `staff` does not hold `billing:read`."""
    tenant_id, agent_id = await _tenant()
    await _metered_call(tenant_id, agent_id, seconds=60, unit_cost="0.1000")
    token = await _make_member(tenant_id, role="staff")
    async with _client() as http:
        response = await http.get("/v1/billing/spend", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


# ------------------------------------------------------------------------- hard rule 7


async def test_money_is_decimal_all_the_way_out() -> None:
    """No float touches this path — not in the dataclass, not in the JSON."""
    tenant_id, reception = await _tenant()
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")
    token = await _make_member(tenant_id)

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)
    for value in (
        period.cost_inr,
        period.period_charge_inr,
        period.itemised_charge_inr,
        period.itemisation_residual_inr,
        period.minutes,
        period.by_call[0].cost_inr,
        period.by_call[0].charged_inr,
        period.by_agent[0].cost_inr,
    ):
        assert isinstance(value, Decimal), "money and minutes are Decimal, never float"

    async with _client() as http:
        raw = (
            await http.get("/v1/billing/spend", headers={"Authorization": f"Bearer {token}"})
        ).text

    # Parsed with `parse_float` armed: a JSON number where a rupee belongs would raise
    # rather than quietly become an IEEE double in a browser.
    def _no_floats(_: str) -> float:
        raise AssertionError("a money field crossed the wire as a JSON number, not a string")

    json.loads(raw, parse_float=_no_floats)


async def test_the_fleet_board_sums_the_clients_it_walked() -> None:
    """Cross-tenant totals are unaskable under FORCEd RLS (`billing/models.PlatformAiSpend`
    records the same constraint), so the board is a walk and its totals are sums of the
    rows it produced — never a query that could see two tenants at once."""
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, reception, seconds=7200, unit_cost="0.5000")
    token = await _make_admin()

    # The budget is lifted for THIS test rather than left to the clock. The walk's cost is
    # a property of how many live accounts the database happens to hold -- a shared
    # development database carries thousands of throwaway tenants -- and a test whose
    # branch depends on that is a test that passes or fails on somebody else's rows.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(spend_routes, "FLEET_BUDGET_S", 3600.0)
        async with _client() as http:
            response = await http.get(
                "/v1/admin/spend", headers={"Authorization": f"Bearer {token}"}
            )
    assert response.status_code == 200, response.text
    body = response.json()

    mine = next(row for row in body["tenants"] if row["tenant_id"] == str(tenant_id))
    assert mine["cost_inr"] == "3600.00"
    assert mine["revenue_inr"] == "10159.00"
    assert Decimal(body["cost_inr"]) >= Decimal(mine["cost_inr"])
    assert Decimal(body["revenue_inr"]) - Decimal(body["cost_inr"]) == Decimal(body["margin_inr"])


# ------------------------------------------------- the arms an ordinary month never takes
#
# `apps/api/billing/*.py` is the `ledgers-and-money` ratchet surface and its budget is ONE
# uncovered unit for the whole tree (D-29). A defensive arm nobody exercises is counted
# exactly like an untested one, which is the rule that makes the ladders below get proved
# rather than merely written.


async def test_a_managed_tenant_with_no_plan_shares_its_month_by_minutes() -> None:
    """A tenant mid-onboarding has usage before they have a `plans` row, so every rate
    quoted is zero and the rung weights carry no information. The minutes still do, and
    equal treatment per minute is the fallback — never a division by a zero weight."""
    tenant_id, reception = await _tenant(monthly_fee=None)
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.0100")
    await _metered_call(tenant_id, reception, seconds=300, unit_cost="0.0100")

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.retainer_inr is None
    # No plan quotes an overage rate, so nothing is billable and every share is 0.00 —
    # but the SHARES were computed, not skipped, and they still add to the total.
    assert period.period_charge_inr == Decimal("0.00")
    assert [c.charged_inr for c in period.by_call] == [Decimal("0.00"), Decimal("0.00")]
    assert period.itemisation_residual_inr == Decimal("0.00")


async def test_a_month_with_cost_but_no_billable_seconds_itemises_nothing() -> None:
    """A call the engine reported as zero-length still costs us (D-370 keeps its whole leg
    cost on the row), but it has no minutes for a share to be proportional to. The whole
    charge is published as the residual with `no_billable_minutes` beside it rather than
    divided by zero."""
    tenant_id, reception = await _tenant(included_min=0, overage_rate="8.0000")
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, started_at, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": reception,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
            },
        )
        # A whole-leg row: `qty = 0`, the cost kept whole (`_ROW_COST_SQL`, D-370).
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'telephony_s', 0, 1.0000, now(), CAST(:m AS jsonb), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "m": json.dumps({"source_currency": "USD", "currency_stated": False}),
            },
        )
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.cost_inr == Decimal("1.00"), "a zero-qty row carries its whole leg cost"
    assert period.minutes == Decimal("0.00")
    assert period.by_call[0].charged_inr == Decimal("0.00")


async def test_an_empty_month_answers_with_zeros_rather_than_an_error() -> None:
    """A prepaid account that placed no calls: no ledger rows to key wallet debits by, no
    unit types to partition, and no currency to report. Every one of those is a real state
    and none of them is an exception."""
    tenant_id, _ = await _tenant(monthly_fee=None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.calls == 0
    assert period.by_call == () and period.by_agent == () and period.by_unit == ()
    assert period.cost_inr == Decimal("0.00")
    assert period.cost_currency is None, "no rows carry a currency, so there is not one"
    assert period.cost_currency_stated is True, "nothing was assumed because nothing was read"
    assert period.unattributed is None


async def test_a_month_whose_rows_disagree_about_the_currency_reports_none() -> None:
    """None is not "we do not know" — it is "the rows do not agree", and an operator has
    to see that rather than have it averaged into one confident answer."""
    tenant_id, reception = await _tenant()
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.0100")
    await _metered_call(
        tenant_id, reception, seconds=600, unit_cost="0.0100", source_currency="INR"
    )

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.cost_currency is None


async def test_cost_that_belongs_to_no_call_stays_inside_the_partition() -> None:
    """`number_rental` carries no `call_id` (OPERATIONS §2 gate 26 turns its writer on).
    It must not be dropped out of `cost_inr` to make the per-call rows add up — the total
    would then be smaller than the ledger's own.

    It carries no CLIENT charge either, and by arithmetic rather than by a special case:
    the only per-second unit is `telephony_s`, a rental row has no duration, so its
    allocation weight is zero and the whole calling charge lands on the calls.
    """
    tenant_id, reception = await _tenant(included_min=0, overage_rate="8.0000")
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.0100")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, unit_type, qty, unit_cost_paid, ref, "
                "occurred_at, created_at) VALUES (:i, :t, 'number_rental', 1, 415.0000, :r, "
                "now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "r": f"num:{uuid.uuid4().hex[:8]}"},
        )
        period = await period_attribution(session, tenant_id=tenant_id)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)

    assert period.unattributed is not None
    assert period.unattributed.cost_inr == Decimal("415.00")
    assert period.cost_inr == margin["cost_inr"] == Decimal("421.00")
    # The per-CALL rows are the rest of it, and the two halves are the whole.
    assert sum(c.cost_inr for c in period.by_call) + period.unattributed.cost_inr == period.cost_inr
    assert sum(u.cost_inr for u in period.by_unit) == period.cost_inr
    # The whole calling charge landed on the CALL, and nothing was lost to the rental.
    assert period.period_charge_inr == Decimal("80.00"), "10 minutes at 8.00/min"
    assert period.by_call[0].charged_inr == Decimal("80.00")
    assert period.itemisation_residual_inr == Decimal("0.00")


async def test_a_prepaid_month_publishes_the_gap_between_the_wallet_and_the_panel() -> None:
    """The wallet is debited per call and the panel prices the month's PUBLISHED minutes at
    the list rate — two arithmetics that cannot both be the itemisation, and whose
    difference is an open founder decision (`calling_revenue_inr`, deepdive-money N-2).

    So the gap is published rather than hidden in a rounded row: the items are the wallet's
    own rupees, and `itemisation_residual_inr` carries the rest with a reason beside it.
    """
    tenant_id, reception = await _tenant(monthly_fee=None)
    call_id = await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.0100")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
        await billing.record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500.00"), reason="topup", ref="rzp_gap"
        )
        # Deliberately NOT the ₹50.00 the panel prices 10 minutes at (₹5/min list rate),
        # so the two disagree the way the measured residual does — the assertion is about
        # the mechanism rather than about a paisa.
        await billing.charge_for_call(
            session, tenant_id=tenant_id, call_id=call_id, amount_inr=Decimal("40.0000")
        )
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.itemised_charge_inr == Decimal("40.00"), "the wallet's own rupees"
    assert period.period_charge_inr == Decimal("50.00"), "the panel's own rupees"
    assert period.itemisation_residual_inr == Decimal("10.00")
    assert period.residual_reason == "prepaid_wallet_vs_panel"


async def test_the_client_page_says_when_it_has_shown_only_the_top_calls() -> None:
    """The rollups are always the WHOLE month — an allocation has to see its own
    denominator — so `limit` bounds the payload and never the arithmetic. A page that
    truncated silently would invite an owner to add up the rows and find them short."""
    tenant_id, reception = await _tenant()
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.0100")
    await _metered_call(tenant_id, reception, seconds=300, unit_cost="0.0100")
    token = await _make_member(tenant_id)

    async with _client() as http:
        response = await http.get(
            "/v1/billing/spend?limit=1", headers={"Authorization": f"Bearer {token}"}
        )
    body = response.json()
    assert len(body["top_calls"]) == 1
    assert body["top_calls_truncated"] is True
    assert body["calls"] == 2, "the COUNT is the month's, not the page's"
    assert body["by_agent"][0]["calls"] == 2, "and so is the agent rollup"


async def test_a_slow_attribution_says_so_rather_than_truncating(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole month is materialised because an allocation needs its own denominator, so
    the only honest response to a month that has outgrown the fold is to name it — the
    trade `client_health_walk_over_budget` already makes one board over."""
    tenant_id, reception = await _tenant()
    await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.0100")

    with caplog.at_level("WARNING"), pytest.MonkeyPatch.context() as patch:
        patch.setattr(attribution, "ATTRIBUTION_BUDGET_S", -1.0)
        async with tenant_session(tenant_id) as session:
            await period_attribution(session, tenant_id=tenant_id)

    over = [r for r in caplog.records if r.message == "spend_attribution_over_budget"]
    assert over, "a fold past its budget was silent"
    assert "remedy" in over[0].__dict__, "an operator needs the next step, not just a number"


async def test_a_slow_fleet_walk_says_so_rather_than_truncating(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same trade on the board that walks every client: truncating would hide the account
    we are losing the most on, which is the one the page was opened for."""
    token = await _make_admin()
    with caplog.at_level("WARNING"), pytest.MonkeyPatch.context() as patch:
        patch.setattr(spend_routes, "FLEET_BUDGET_S", -1.0)
        async with _client() as http:
            response = await http.get(
                "/v1/admin/spend", headers={"Authorization": f"Bearer {token}"}
            )
    assert response.status_code == 200
    assert any(r.message == "fleet_spend_walk_over_budget" for r in caplog.records)


def test_a_period_with_no_revenue_has_no_margin_percentage() -> None:
    """ONE rule, one function, and the arm that matters is the one a fleet with nothing
    billed would take — which no database this test can arrange would ever show."""
    assert billing.margin_pct(margin_inr=Decimal("-12.00"), revenue_inr=Decimal("0.00")) is None
    assert billing.margin_pct(
        margin_inr=Decimal("6559.00"), revenue_inr=Decimal("10159.00")
    ) == Decimal("64.6")


# ------------------------------------------- the month is being written to while it is read
#
# `usage_events` is append-only and the month on screen is usually the OPEN one, which
# `pipeline._meter` writes to all day. Under READ COMMITTED every statement takes a fresh
# snapshot -- inside one transaction as much as across two -- so a page assembled from
# several statements is a page assembled from several instants.


async def _meter_into(tenant_id: UUID, agent_id: UUID, *, seconds: int) -> UUID:
    """A second actor completing a call. Its own session, its own transaction, committed."""
    return await _metered_call(tenant_id, agent_id, seconds=seconds, unit_cost="0.0100")


async def test_a_call_metered_while_the_page_is_being_built_does_not_break_the_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE 500 THIS ANCHORING EXISTS TO PREVENT.

    `period_attribution` reads the plan facts through `usage_summary` and the ledger rows
    through `_read_month`. When the row-derived TOTALS were taken from the first read and
    the PARTS from the second, one ordinary concurrent meter write between them handed
    `allocate_paise` parts that did not add to their total — and it raised, correctly,
    which reached a client's own money page as an unhandled 500.

    The interleaving is arranged rather than raced, so the test is deterministic: a second
    session meters a call at exactly the point production leaves open.
    """
    tenant_id, reception = await _tenant(included_min=0, overage_rate="8.0000")
    await _metered_call(tenant_id, reception, seconds=601, unit_cost="0.0100")

    original = attribution._read_month

    async def racing(*args: Any, **kwargs: Any) -> Any:
        await _meter_into(tenant_id, reception, seconds=421)
        return await original(*args, **kwargs)

    monkeypatch.setattr(attribution, "_read_month", racing)
    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)

    # Both calls are on the page, and every published breakdown still partitions the
    # figure published beside it — the parts and the totals came from one scan.
    assert period.calls == 2
    assert sum(c.minutes for c in period.by_call) == period.minutes
    assert sum(c.cost_inr for c in period.by_call) == period.cost_inr
    assert sum(u.cost_inr for u in period.by_unit) == period.cost_inr
    assert sum(a.minutes for a in period.by_agent) == period.minutes
    assert sum(c.charged_inr for c in period.by_call) == period.period_charge_inr
    assert period.itemisation_residual_inr == Decimal("0.00")


async def test_the_unit_breakdown_and_the_cost_total_are_one_scan_not_two() -> None:
    """`by_unit` partitions `cost_inr`, and the two are folded out of the same statement.

    Asserted over a month with THREE unit types whose costs each carry a residue of
    0.0025 — so `to_paise` on each line rounds all three DOWN while the total rounds UP,
    and the three lines would publish ₹13.53 under a ₹13.54 total. That is D-371's exact
    shape, which is why the identity is the allocation's and not an accident of round
    numbers.
    """
    tenant_id, reception = await _tenant()
    call_id = await _metered_call(tenant_id, reception, seconds=601, unit_cost="0.0125")
    async with tenant_session(tenant_id) as session:
        for unit, qty, cost in (("llm_tok_out", "1", "2.5125"), ("tts_chars", "1", "3.5125")):
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, :u, :q, "
                    ":cost, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "u": unit,
                    "q": Decimal(qty),
                    "cost": Decimal(cost),
                },
            )
        period = await period_attribution(session, tenant_id=tenant_id)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)

    assert {u.unit_type for u in period.by_unit} == {"telephony_s", "llm_tok_out", "tts_chars"}
    assert period.cost_inr == Decimal("13.54"), "7.5125 + 2.5125 + 3.5125, rounded once"
    assert sum(u.cost_inr for u in period.by_unit) == period.cost_inr == margin["cost_inr"]
    # ...and the per-call rows are the same rupees grouped the other way.
    assert sum(c.cost_inr for c in period.by_call) == period.cost_inr


# ------------------------------------------------------- adversarial months, one at a time


async def test_a_calls_row_cannot_be_deleted_out_from_under_its_own_money() -> None:
    """The `LEFT JOIN` to `calls` types `agent_id` nullable, and the database is what makes
    that arm unreachable for a row that HAS a `call_id`: `fk_usage_events_call_id_calls` is
    ON DELETE RESTRICT, so no retention sweep, no erasure and no hand-run DELETE can take
    the call row while the ledger that priced it is still there.

    Asserted rather than assumed, because it is the whole reason `cost_inr` can promise to
    be a partition: the join can only miss for a row that never had a `call_id`
    (`number_rental`), which the test below covers.
    """
    tenant_id, reception = await _tenant()
    call_id = await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.0100")
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(text("DELETE FROM calls WHERE id = :c"), {"c": call_id})


async def test_an_ist_month_boundary_puts_a_late_evening_call_in_the_month_it_was_dialled() -> None:
    """23:00 IST on the 31st is 17:30 UTC on the 31st and is an AUGUST call; 00:30 IST on
    the 1st is 19:00 UTC on the 31st and is a SEPTEMBER one. A window computed in UTC would
    put both in August and move the money by 5h30m at both ends of every month.

    The window is `billing/plans.ist_month_window`'s — the one this repo already has — and
    this pins that the spend page reads it rather than a second one of its own.
    """
    tenant_id, reception = await _tenant(included_min=0, overage_rate="8.0000")
    august = await _metered_call(
        tenant_id,
        reception,
        seconds=600,
        unit_cost="0.0100",
        at=datetime(2026, 8, 31, 17, 30, tzinfo=UTC),
    )
    september = await _metered_call(
        tenant_id,
        reception,
        seconds=300,
        unit_cost="0.0100",
        at=datetime(2026, 8, 31, 19, 0, tzinfo=UTC),
    )

    async with tenant_session(tenant_id) as session:
        aug = await period_attribution(session, tenant_id=tenant_id, month="2026-08")
        sep = await period_attribution(session, tenant_id=tenant_id, month="2026-09")

    assert [c.call_id for c in aug.by_call] == [august]
    assert [c.call_id for c in sep.by_call] == [september]
    assert aug.minutes == Decimal("10.00") and sep.minutes == Decimal("5.00")
    # Each month is a whole month: its own charge, divided across its own calls.
    assert aug.by_call[0].charged_inr == aug.period_charge_inr == Decimal("80.00")
    assert sep.by_call[0].charged_inr == sep.period_charge_inr == Decimal("40.00")


async def test_a_compensating_correction_row_stays_inside_every_total() -> None:
    """A compensating `other` row whose `unit_cost_paid` is a SIGNED delta (hard rule 4 —
    fixes are compensating entries, never an UPDATE) must stay inside the partition. A
    negative delta takes the month's cost DOWN and makes a `by_unit` line negative; a
    breakdown that dropped the negative line would publish a cost total larger than the
    ledger's own.

    The single-tier voice decision removed the TTS-tier correction that used to write this
    kind of row, so the row is inserted directly here — the property under test is the
    partition reader's, not any one correction API's, and `cost_unit.py`'s currency
    restatement still writes exactly this shape.
    """
    tenant_id, reception = await _tenant(included_min=0, overage_rate="8.0000")
    call_id = await _metered_call(tenant_id, reception, seconds=600, unit_cost="0.5000")
    delta = Decimal("-15.0000")
    async with tenant_session(tenant_id) as session:
        # `unit_type = 'other'`, `qty = 1`, `unit_cost_paid` = the signed delta — the
        # compensating-entry shape, stamped on the call it corrects.
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, 'other', "
                "1, :cost, now(), CAST(:m AS jsonb), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "cost": delta,
                "m": '{"kind": "manual_correction"}',
            },
        )
        period = await period_attribution(session, tenant_id=tenant_id)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)

    assert delta < 0, "a credit correction takes our cost down"
    assert period.cost_inr == margin["cost_inr"] == to_paise(Decimal("300") + delta)
    assert sum(u.cost_inr for u in period.by_unit) == period.cost_inr
    assert sum(c.cost_inr for c in period.by_call) == period.cost_inr
    # The correction carries no `source_currency`, so it cannot manufacture a disagreement.
    assert period.cost_currency == "USD"


async def test_a_month_with_no_revenue_and_real_cost_still_partitions() -> None:
    """Every included minute used and nothing billable: the client owes ₹0.00 for calling
    while we paid a real supplier. Every share is ₹0.00 and they still add up — the arm an
    ordinary month never takes, and the one a margin board is opened to look at."""
    tenant_id, reception = await _tenant(monthly_fee="0.00", included_min=1000)
    await _metered_call(tenant_id, reception, seconds=601, unit_cost="0.5000")
    await _metered_call(tenant_id, reception, seconds=401, unit_cost="0.5000")

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)

    assert period.period_charge_inr == Decimal("0.00")
    assert margin["revenue_inr"] == Decimal("0.00")
    assert margin["margin_pct"] is None, "no revenue is not 0% margin"
    assert period.cost_inr == Decimal("501.00") == margin["cost_inr"]
    assert [c.charged_inr for c in period.by_call] == [Decimal("0.00"), Decimal("0.00")]
    assert period.itemisation_residual_inr == Decimal("0.00")
    assert sum(c.cost_inr for c in period.by_call) == period.cost_inr


async def test_the_admin_header_adds_up_to_the_lines_beneath_it_mid_metering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The header is folded out of the SAME scan the breakdown is, so an operator can add
    the lines and land on the total above them — on an open month somebody is dialling in,
    which is the only month this page is ever opened during.

    Reading the header from a second `margin_for_tenant` call made that a coincidence: it
    is another statement at another instant over an append-only ledger, so a call landing
    between the two put a `cost_inr` on the header that the `by_unit` lines did not sum to.
    """
    tenant_id, reception = await _tenant(monthly_fee="9999.00", included_min=0)
    await _metered_call(tenant_id, reception, seconds=601, unit_cost="0.5000")
    token = await _make_admin()

    original = attribution._read_month

    async def racing(*args: Any, **kwargs: Any) -> Any:
        await _metered_call(tenant_id, reception, seconds=421, unit_cost="0.5000")
        return await original(*args, **kwargs)

    monkeypatch.setattr(attribution, "_read_month", racing)
    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/spend", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["calls"] == 2
    assert sum(Decimal(u["cost_inr"]) for u in body["by_unit"]) == Decimal(body["cost_inr"])
    assert sum(Decimal(a["cost_inr"]) for a in body["by_agent"]) == Decimal(body["cost_inr"])
    assert sum(Decimal(c["cost_inr"]) for c in body["top_calls"]) == Decimal(body["cost_inr"])
    assert Decimal(body["retainer_inr"]) + Decimal(body["period_charge_inr"]) == Decimal(
        body["revenue_inr"]
    )
    assert Decimal(body["revenue_inr"]) - Decimal(body["cost_inr"]) == Decimal(body["margin_inr"])


# --------------------------------------------------------------- errors are the interface


async def test_an_unparseable_month_is_a_422_a_reader_can_act_on() -> None:
    """`?month=july` used to aggregate to a clean ₹0.00 page. It reaches
    `parse_billing_month`, which refuses it — and this pins that the refusal arrives as
    RFC-9457 with the format and a remediation on it, on BOTH new routes, rather than as a
    500 or a confidently empty statement."""
    tenant_id, agent_id = await _tenant()
    await _metered_call(tenant_id, agent_id, seconds=60, unit_cost="0.1000")
    client_token = await _make_member(tenant_id)
    admin_token = await _make_admin()

    async with _client() as http:
        for url, token in (
            ("/v1/billing/spend?month=july", client_token),
            (f"/v1/admin/tenants/{tenant_id}/spend?month=july", admin_token),
            ("/v1/admin/spend?month=july", admin_token),
        ):
            response = await http.get(url, headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 422, f"{url} -> {response.status_code}"
            assert response.headers["content-type"].startswith("application/problem+json")
            body = response.json()
            assert body["type"].endswith("/invalid_billing_month")
            assert "YYYY-MM" in body["detail"]
            assert body["remediation"], "a refusal without a next step is not actionable"


async def test_the_itemisation_limit_is_bounded_at_the_boundary() -> None:
    """`limit` bounds the payload and never the arithmetic, so it is validated rather than
    clamped: a silently clamped 5000 would answer a different question from the one asked.
    """
    tenant_id, agent_id = await _tenant()
    await _metered_call(tenant_id, agent_id, seconds=60, unit_cost="0.1000")
    token = await _make_member(tenant_id)
    async with _client() as http:
        headers = {"Authorization": f"Bearer {token}"}
        assert (await http.get("/v1/billing/spend?limit=0", headers=headers)).status_code == 422
        over = await http.get(
            f"/v1/billing/spend?limit={spend_routes.MAX_CALLS + 1}", headers=headers
        )
        assert over.status_code == 422
        assert (
            await http.get(f"/v1/billing/spend?limit={spend_routes.MAX_CALLS}", headers=headers)
        ).status_code == 200
