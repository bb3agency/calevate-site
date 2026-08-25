"""The admin surface that writes a client's commercial terms (SURFACES §1 "Commercials").

THE DEFECT. `plans` has carried the whole commercial relationship since the first
migration — setup fee, retainer, included minutes, overage rate, the admin ceilings and
the valid-time window that dates them — and **nothing in this product ever wrote one**.
The only writer was `billing/caps.py::apply_client_caps`, which mints a row carrying
nothing but the client's own stop button. So the invoice, the margin panel, the dispatch
ceiling and the D-64 setup-fee cron all resolved a row that an operator had to INSERT by
hand against production, and `docs/SURFACES.md` §1 has promised the surface since v1.0.

What is asserted here, in the order it matters:

1. **A plan change is a NEW DATED ROW.** The row that priced a month the client has
   already been billed for is never touched — including through this route, and
   including when the change is written months later. `tests/plan_effective_dating_test`
   pins the RESOLVER; this pins the WRITER, which is the half that can rewrite history.
2. **The past cannot be re-priced at all**: a row dated into a closed billing month is
   refused, because an invoice here is derived and re-rendering it reads `plans` again.
3. **Idempotence**: submitting the terms already in effect writes no row and no audit
   entry — the "audit follows a real transition, not a button press" convention.
4. **Loosening a spend ceiling needs a superadmin AND a step-up**, bound to the tenant;
   tightening one, or setting a first one, is ordinary operator work.
5. **Money is exact.** Every amount crosses the wire as a string and comes back as the
   digits that were stored; a JSON float is refused at the boundary (hard rule 7).
6. **RLS**: an operator's write lands in the named tenant and is invisible to every
   other one; a neighbour's tenant id reads zero rows.
7. **`overage_rate_value` is settable and unset.** The retail value-tier rate is an open
   founder decision; the SURFACE is not blocked on the NUMBER, and no default is
   invented anywhere.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created, so
this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.api.admin import service as admin_service
from apps.api.billing import service as billing
from apps.api.billing.plans import IST, parse_billing_month
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

TERMS = "/v1/admin/tenants/{tenant_id}/commercial-terms"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """A real `admin_users` row plus the dev-token spelling of its realm — the idiom
    `route_shape_test` and `ops_spend_cap_recompute_test` both use."""
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


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Commercial Terms Clinic",
        slug=f"terms-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _post(
    token: str, tenant_id: UUID, body: dict[str, Any], *, confirm: str | None = None
) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    async with _client() as http:
        return await http.post(TERMS.format(tenant_id=tenant_id), headers=headers, json=body)


async def _get(token: str, tenant_id: UUID) -> Any:
    async with _client() as http:
        return await http.get(
            TERMS.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )


def _month_start_ist(month: str) -> datetime:
    year, mon = parse_billing_month(month)
    return datetime(year, mon, 1, tzinfo=IST).astimezone(UTC)


def _previous_month(month: str) -> str:
    year, mon = parse_billing_month(month)
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


def _next_month(month: str) -> str:
    year, mon = parse_billing_month(month)
    return f"{year + 1}-01" if mon == 12 else f"{year}-{mon + 1:02d}"


async def _plan_rows(tenant_id: UUID) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT id, monthly_fee, overage_rate, effective_from FROM plans "
                        "WHERE tenant_id = :t ORDER BY created_at"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        )


async def _usage(tenant_id: UUID, *, minutes: int, occurred_at: datetime) -> None:
    """One completed call worth `minutes`, stamped into whichever IST month the test
    means — the same fixture shape `plan_effective_dating_test` uses."""
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT id FROM agents WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}
            )
        ).scalar()
        call_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', :at, :at)"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "at": occurred_at,
            },
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                ":qty, 0.5000, :at, :at)"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "c": call_id,
                "qty": Decimal(minutes * 60),
                "at": occurred_at,
            },
        )


# ============================================================================
# 1. A tenant is born with no commercial terms, and the surface SAYS so
# ============================================================================


async def test_a_new_tenant_has_no_commercial_terms_and_the_state_names_it() -> None:
    """The decision this slice had to make, asserted rather than described.

    Onboarding does NOT seed a plan row. A seeded row would carry either invented
    numbers (forbidden) or all NULLs — and an all-NULL row is, for every reader in this
    codebase, exactly equivalent to no row at all, so it would buy nothing but the
    appearance of a configured account while destroying the distinction
    `warn_no_plan_in_effect` depends on. The absence is surfaced as a NAMED state
    instead, which is what a screen can render as a refusal to be resolved.
    """
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    response = await _get(token, tenant_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "none", "a tenant nobody has priced must say so, not read as ₹0"
    assert body["in_effect"] is None
    assert body["history"] == []
    assert await _plan_rows(tenant_id) == [], "onboarding must not invent a plan row"


async def test_a_cap_only_row_is_reported_as_unpriced_rather_than_as_terms() -> None:
    """`apply_client_caps` mints a row carrying nothing but the client's own stop
    button. It is "in effect" for every reader while agreeing no price at all, and an
    operator screen that counted it as commercial terms would report the account as
    priced when nobody had priced them."""
    from apps.api.billing.caps import apply_client_caps

    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await apply_client_caps(session, tenant_id=tenant_id, cap_min=50, cap_spend=None)

    body = (await _get(await _make_admin("operator"), tenant_id)).json()

    assert body["state"] == "unpriced"
    assert body["in_effect"]["states_pricing"] is False
    assert body["in_effect"]["client_cap_minutes"] == 50, (
        "the client's own half of the cap is shown, because the cap in force is the "
        "stricter of the pair and a panel without it cannot explain itself"
    )


# ============================================================================
# 2. The write, and what it must never do to history
# ============================================================================


async def test_recording_terms_prices_the_client_and_the_panel_agrees() -> None:
    """End to end: an operator agrees terms, and the client's own usage summary — the
    computation the invoice is derived from — prices against them from that moment."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    response = await _post(
        token,
        tenant_id,
        {
            "setup_fee_inr": "5000.00",
            "monthly_fee_inr": "9999.00",
            "included_minutes": 100,
            "overage_rate_inr": "8.0000",
            "hard_cap_minutes": 500,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["changed"] is True
    assert response.json()["state"] == "set"

    await _usage(tenant_id, minutes=120, occurred_at=datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)

    assert summary["monthly_fee_inr"] == Decimal("9999.00")
    assert summary["included_minutes"] == 100
    # 120 used - 100 included = 20 overage minutes at ₹8. Exact NUMERIC, no float.
    assert summary["overage_cost_inr"] == Decimal("160.00")


async def test_a_plan_change_is_a_new_row_and_the_old_month_keeps_its_price() -> None:
    """THE property this whole surface exists to protect.

    An invoice in this product is a DERIVED statement — re-rendering July reads `plans`
    again — so a price change that EDITED the row which priced July would silently
    rewrite a bill the client has already paid. The route inserts; the predecessor is
    left exactly as it was; and the closed month still resolves the terms that priced it.
    """
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    this_month = billing.current_billing_month()
    last_month = _previous_month(this_month)

    # July's terms, dated to have ended when this month began — the row that priced it.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "effective_to, created_at, updated_at) VALUES (:i, :t, 1000.00, 0, 5.0000, "
                ":to, clock_timestamp(), clock_timestamp())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "to": _month_start_ist(this_month)},
        )
    await _usage(
        tenant_id, minutes=10, occurred_at=_month_start_ist(this_month) - timedelta(days=2)
    )
    before = await _plan_rows(tenant_id)

    # August's terms, agreed through the surface.
    response = await _post(
        token,
        tenant_id,
        {
            "monthly_fee_inr": "2000.00",
            "included_minutes": 0,
            "overage_rate_inr": "9.0000",
            "effective_from": _month_start_ist(this_month).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    await _usage(tenant_id, minutes=10, occurred_at=datetime.now(UTC))

    after = await _plan_rows(tenant_id)
    assert len(after) == len(before) + 1, "a plan change must ADD a row"
    assert after[0] == before[0], (
        "the row that priced the closed month was modified — this is the money bug: "
        "the client's July statement now says something else than when they paid it"
    )

    async with tenant_session(tenant_id) as session:
        july = await billing.usage_summary(session, tenant_id=tenant_id, month=last_month)
        august = await billing.usage_summary(session, tenant_id=tenant_id, month=this_month)

    assert july["monthly_fee_inr"] == Decimal("1000.00"), "the closed month keeps its price"
    assert july["overage_cost_inr"] == Decimal("50.00"), "and its rate"
    assert august["monthly_fee_inr"] == Decimal("2000.00")
    assert august["overage_cost_inr"] == Decimal("90.00")


async def test_terms_dated_for_next_month_do_not_price_today() -> None:
    """Preparing a change in advance is what the columns are FOR, and it must not move
    today's bill the moment the row lands (`plan_effective_dating_test` pins the same
    property against a hand-written row; this pins it through the route)."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    next_start = _month_start_ist(_next_month(billing.current_billing_month()))

    await _post(
        token,
        tenant_id,
        {"monthly_fee_inr": "9999.00", "included_minutes": 100, "overage_rate_inr": "8.0000"},
    )
    assert (
        await _post(
            token,
            tenant_id,
            {
                "monthly_fee_inr": "19999.00",
                "included_minutes": 50,
                "overage_rate_inr": "20.0000",
                "effective_from": next_start.isoformat(),
            },
        )
    ).status_code == 201

    await _usage(tenant_id, minutes=120, occurred_at=datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)

    assert summary["monthly_fee_inr"] == Decimal("9999.00")
    assert summary["overage_cost_inr"] == Decimal("160.00"), "this month's ₹8, not next's ₹20"


async def test_a_row_dated_into_a_closed_month_is_refused() -> None:
    """Backdating is the other way to rewrite a paid statement, and an INSERT can do it
    just as well as an UPDATE: a row dated into July wins the resolver's total order
    there. Refused at the boundary with a message naming the field."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    last_month_start = _month_start_ist(_previous_month(billing.current_billing_month()))

    response = await _post(
        token,
        tenant_id,
        {"monthly_fee_inr": "1.00", "effective_from": last_month_start.isoformat()},
    )

    assert response.status_code == 422, response.text
    assert "closed billing month" in response.text
    assert await _plan_rows(tenant_id) == [], "a refused write must write nothing"


async def test_a_window_that_ends_before_it_starts_is_refused() -> None:
    """A row whose `effective_to` is at or before its `effective_from` matches at NO
    instant — an agreement that prices nothing, silently. Refused here, and by
    `ck_plans_window_ordered` underneath (migration a1c4f70b9e28)."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    start = datetime.now(UTC) + timedelta(days=10)

    response = await _post(
        token,
        tenant_id,
        {
            "monthly_fee_inr": "100.00",
            "effective_from": start.isoformat(),
            "effective_to": (start - timedelta(days=1)).isoformat(),
        },
    )

    assert response.status_code == 422, response.text
    assert await _plan_rows(tenant_id) == []


# ============================================================================
# 3. Idempotence, and the audit row that follows a real change
# ============================================================================


async def _audit_rows(tenant_id: UUID, action: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action = :a"),
                    {"t": tenant_id, "a": action},
                )
            ).scalar()
            or 0
        )


async def test_resubmitting_the_same_terms_writes_neither_a_row_nor_an_audit_entry() -> None:
    """The console saves on a button an operator can press twice. A duplicate row would
    leave two identical agreements resolved by a tie-break — history nobody agreed to —
    and a second audit row would make "who changed what this client pays" harder to
    answer, not easier (the convention `approve_kb` established)."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    body = {"monthly_fee_inr": "7000.00", "included_minutes": 200, "overage_rate_inr": "6.0000"}

    first = await _post(token, tenant_id, body)
    second = await _post(token, tenant_id, body)

    assert first.status_code == 201 and first.json()["changed"] is True
    assert second.status_code == 201, second.text
    assert second.json()["changed"] is False
    assert second.json()["plan_id"] == first.json()["plan_id"]
    assert len(await _plan_rows(tenant_id)) == 1, "the second press must write no row"
    assert await _audit_rows(tenant_id, "plan.terms_recorded") == 1


async def test_a_real_change_is_audited() -> None:
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    await _post(token, tenant_id, {"monthly_fee_inr": "1000.00"})
    await _post(token, tenant_id, {"monthly_fee_inr": "2000.00"})

    assert await _audit_rows(tenant_id, "plan.terms_recorded") == 2


# ============================================================================
# 4. The ceiling is the dangerous field, and loosening it needs the second key
# ============================================================================


def _confirmation(tenant_id: UUID) -> str:
    """Spelled out rather than imported, for the reason `ops_spend_cap_recompute_test`
    spells its own out: the string is part of an operator procedure, so a change of
    shape has to fail a test rather than silently ask for a header nobody sends."""
    return f"raise_spend_ceiling:{tenant_id}"


async def test_an_operator_may_set_and_tighten_a_ceiling() -> None:
    """Setting the first ceiling a tenant has ever had is not a raise — they are
    unlimited right now (`caps.over_cap_sql`: an absent ceiling is an absent
    constraint) — and tightening one is ordinary onboarding work. Neither may need a
    superadmin, or an operator cannot finish an onboarding."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    first = await _post(token, tenant_id, {"monthly_fee_inr": "100.00", "hard_cap_minutes": 500})
    tighter = await _post(token, tenant_id, {"monthly_fee_inr": "100.00", "hard_cap_minutes": 100})

    assert first.status_code == 201, first.text
    assert tighter.status_code == 201, tighter.text


async def test_an_operator_may_not_raise_a_ceiling() -> None:
    """`core/rbac.py`'s role table reserves cap raises for `superadmin`, and
    `plans.hard_cap_*` is the ceiling the dispatch gate enforces."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    await _post(token, tenant_id, {"monthly_fee_inr": "100.00", "hard_cap_spend_inr": "1000.00"})

    raised = await _post(
        token,
        tenant_id,
        {"monthly_fee_inr": "100.00", "hard_cap_spend_inr": "9000.00"},
        confirm=_confirmation(tenant_id),
    )

    assert raised.status_code == 403, raised.text
    assert "superadmin" in raised.text


async def test_removing_a_ceiling_counts_as_loosening_it() -> None:
    """`null` is the LOOSEST value there is — the tenant becomes unlimited — so it takes
    the same authority as raising the number, not less."""
    tenant_id = await _tenant()
    operator = await _make_admin("operator")
    await _post(operator, tenant_id, {"monthly_fee_inr": "100.00", "hard_cap_minutes": 100})

    removed = await _post(
        operator, tenant_id, {"monthly_fee_inr": "100.00"}, confirm=_confirmation(tenant_id)
    )

    assert removed.status_code == 403, removed.text


async def test_a_superadmin_raising_a_ceiling_still_needs_the_confirmation() -> None:
    """Two keys, not one: the role says who may, the step-up says this request meant to.
    And the header is bound to the TENANT, so a confirmation captured while raising one
    client's ceiling cannot be replayed against another's."""
    tenant_id = await _tenant()
    other_id = await _tenant()
    token = await _make_admin("superadmin")
    await _post(token, tenant_id, {"monthly_fee_inr": "100.00", "hard_cap_minutes": 100})
    raise_body = {"monthly_fee_inr": "100.00", "hard_cap_minutes": 900}

    unconfirmed = await _post(token, tenant_id, raise_body)
    wrong_tenant = await _post(token, tenant_id, raise_body, confirm=_confirmation(other_id))
    confirmed = await _post(token, tenant_id, raise_body, confirm=_confirmation(tenant_id))

    assert unconfirmed.status_code == 403 and "step_up_required" in unconfirmed.text
    assert wrong_tenant.status_code == 403, "a confirmation for another tenant is not consent"
    assert confirmed.status_code == 201, confirmed.text
    assert len(await _plan_rows(tenant_id)) == 2, "only the confirmed write may have landed"


# ============================================================================
# 5. Money, exactly (hard rule 7)
# ============================================================================


async def test_money_crosses_the_wire_as_a_string_and_a_float_is_refused() -> None:
    """`2500.10` as a JSON number has already been through a binary float by the time
    Pydantic sees it. The rate keeps FOUR decimal places on the way out, unrounded,
    because the invoice's `qty x unit = amount` only holds if it does."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    floated = await _post(token, tenant_id, {"monthly_fee_inr": 2500.10})
    exact = await _post(
        token, tenant_id, {"monthly_fee_inr": "2500.10", "overage_rate_inr": "7.1250"}
    )

    assert floated.status_code == 422, floated.text
    assert exact.status_code == 201, exact.text
    body = (await _get(token, tenant_id)).json()["in_effect"]
    assert body["monthly_fee_inr"] == "2500.1000"
    assert body["overage_rate_inr"] == "7.1250", "a rate is published unrounded"


async def test_the_value_tier_rate_is_settable_and_stays_unset_by_default() -> None:
    """The retail value-tier rate is an OPEN FOUNDER DECISION. The surface is not
    blocked on it and no default is invented: a plan written without it stores NULL,
    which billing reads as "this plan quotes no separate value rate"."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    await _post(token, tenant_id, {"monthly_fee_inr": "100.00", "overage_rate_inr": "8.0000"})
    unset = (await _get(token, tenant_id)).json()["in_effect"]
    await _post(
        token,
        tenant_id,
        {
            "monthly_fee_inr": "100.00",
            "overage_rate_inr": "8.0000",
            "overage_rate_value_inr": "5.5000",
        },
    )
    set_now = (await _get(token, tenant_id)).json()["in_effect"]

    assert unset["overage_rate_value_inr"] is None, "no default may be invented"
    assert set_now["overage_rate_value_inr"] == "5.5000"


# ============================================================================
# 6. Tenancy (hard rule 1)
# ============================================================================


async def test_terms_written_for_one_tenant_are_invisible_to_another() -> None:
    """The cross-tenant zero-rows assertion. `plans` is FORCE RLS'd and the route works
    inside `tenant_session(tenant_id)`, so the policy — not the query — is what isolates
    a client's commercial terms."""
    tenant_id = await _tenant()
    neighbour_id = await _tenant()
    token = await _make_admin("operator")

    await _post(token, tenant_id, {"monthly_fee_inr": "4242.00"})

    async with tenant_session(neighbour_id) as session:
        visible = (
            await session.execute(
                text("SELECT count(*) FROM plans WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert visible == 0, "a neighbour's session must see zero rows of another's plans"

    neighbour_body = (await _get(token, neighbour_id)).json()
    assert neighbour_body["state"] == "none"
    assert neighbour_body["history"] == []


async def test_recording_terms_against_a_tenant_that_does_not_exist_is_a_404() -> None:
    """A mistyped uuid must not reach the FK as a 500 — and must certainly not mint a
    plan row nobody can find."""
    token = await _make_admin("operator")
    response = await _post(token, uuid.uuid4(), {"monthly_fee_inr": "100.00"})
    assert response.status_code == 404, response.text


async def test_terms_whose_window_has_closed_report_lapsed_not_none() -> None:
    """The fourth `state`, and the only one that means "somebody priced this and the
    pricing RAN OUT".

    `none` and `lapsed` are both "no terms in effect right now" and an operator must be
    able to tell them apart, because they call for opposite actions: `none` is a tenant
    nobody has priced yet, `lapsed` is a tenant who WAS priced and whose window closed —
    an account that is currently billing nothing while still placing calls. Collapsing
    them would hide the second inside the first, and the first looks like ordinary
    new-tenant paperwork.

    Reached by dating a window that has already ended, which is the shape a fixed-term
    agreement leaves behind on its own. The row is written through the route so this pins
    the state the SCREEN receives, not one assembled in the test.
    """
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    this_month_start = _month_start_ist(billing.current_billing_month())

    # A window that opened and closed before the current month began. Backdating is
    # refused for CLOSED billing months, so the row is written open-ended first and its
    # end date is set directly — the same row a term that simply expired would leave.
    assert (
        await _post(
            token,
            tenant_id,
            {"monthly_fee_inr": "5000.00", "included_minutes": 100, "overage_rate_inr": "5.0000"},
        )
    ).status_code == 201
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE plans SET effective_to = :end WHERE tenant_id = :tid"),
            {"end": this_month_start, "tid": tenant_id},
        )

    body = (await _get(token, tenant_id)).json()

    assert body["state"] == "lapsed", "priced-then-expired is not the same as never priced"
    assert body["in_effect"] is None
    assert len(body["history"]) == 1, "the expired row is still history, not nothing"


# ------------------------------------------------------------------ the margin guard
#
# D-469. A committed-volume bundle sells minutes the same way a prepaid pack does, so it
# answers to the same floor — but a pack's bonus is capped by code review and a CI guard,
# while these terms are typed into a console during an onboarding call with neither. These
# tests pin the POSTURE, which is deliberately two different answers to two different
# facts: a guaranteed loss is refused, a thin deal is allowed and said out loud.


async def test_terms_that_price_a_minute_below_cost_are_refused() -> None:
    """The one shape nobody intends. ₹7,000 for 2,000 minutes is ₹3.50/min against a ₹3.70
    floor — it loses money on every minute, and worse the harder the client uses it."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    response = await _post(
        token,
        tenant_id,
        {"monthly_fee_inr": "7000.00", "included_minutes": 2000, "overage_rate_inr": "8.0000"},
    )

    assert response.status_code == 422, response.text
    body = response.json()
    # RFC-9457: the machine-readable code is the tail of `type`, not a bare field.
    assert body["type"].endswith("/plan_below_cost")
    # The refusal has to name WHICH rate and WHAT it must clear, or the operator is left
    # guessing which of the three numbers they typed to move.
    assert "committed" in body["detail"]
    assert "3.70" in body["detail"]
    assert body["remediation"]

    # And nothing was written: a refused agreement must not leave a plan row behind.
    assert await _plan_rows(tenant_id) == []


async def test_a_below_cost_overage_is_refused_even_behind_a_healthy_bundle() -> None:
    """A comfortable committed rate does not launder the overage — the client pays that
    one on exactly the minutes they use hardest."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    response = await _post(
        token,
        tenant_id,
        {"monthly_fee_inr": "10000.00", "included_minutes": 2000, "overage_rate_inr": "2.0000"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/plan_below_cost")
    assert "overage" in response.json()["detail"]


async def test_a_thin_but_profitable_bundle_is_accepted_and_flagged() -> None:
    """₹4.00/min clears the ₹3.70 cost but not the 20% target. That is a founder's call to
    make — a lighthouse client, a displacement — so the route records it and SAYS so
    rather than standing in the way of a commercial decision."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    response = await _post(
        token,
        tenant_id,
        {"monthly_fee_inr": "4000.00", "included_minutes": 1000},
    )

    assert response.status_code == 201, response.text
    margin = response.json()["margin"]
    assert margin["below_target_margin"] == ["committed"]
    assert margin["effective_committed_rate_inr_per_min"] == "4.00"
    # 7.5% of each rupee is ours; published as a FRACTION so it compares directly against
    # `min_gross_margin` in the same payload.
    assert margin["committed_gross_margin"] == "0.0750"
    assert margin["min_gross_margin"] == "0.20"
    assert margin["cost_floor_inr_per_min"] == "3.70"
    # The agreement really was recorded — a warning is not a refusal.
    assert len(await _plan_rows(tenant_id)) == 1


async def test_every_plan_read_carries_its_margin() -> None:
    """The margin of a bundle is a number on the screen that SETS it, not something
    discovered months later when a client reconciles."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    assert (
        await _post(
            token,
            tenant_id,
            {"monthly_fee_inr": "10000.00", "included_minutes": 2000, "overage_rate_inr": "8.0000"},
        )
    ).status_code == 201

    in_effect = (await _get(token, tenant_id)).json()["in_effect"]

    # ₹10,000 / 2,000 = ₹5.00/min, 26% margin at the ₹3.70 floor.
    assert in_effect["margin"]["effective_committed_rate_inr_per_min"] == "5.00"
    assert in_effect["margin"]["committed_gross_margin"] == "0.2600"
    assert in_effect["margin"]["overage_rate_inr_per_min"] == "8.0000"
    assert in_effect["margin"]["below_target_margin"] == []


async def test_a_retainer_with_no_bundled_minutes_quotes_no_committed_rate() -> None:
    """Unset is not zero. A fee with no included minutes has no per-minute rate to judge,
    and reading it as ₹0.00 would refuse an ordinary agreement as a below-cost sale."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    response = await _post(token, tenant_id, {"monthly_fee_inr": "9999.00"})

    assert response.status_code == 201, response.text
    margin = response.json()["margin"]
    assert margin["effective_committed_rate_inr_per_min"] is None
    assert margin["committed_gross_margin"] is None
    assert margin["overage_rate_inr_per_min"] is None
    assert margin["below_target_margin"] == []
