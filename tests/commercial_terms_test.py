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
7. **Retainer terms are refused (D-707).** A setup fee, monthly fee, included minutes or
   overage rate is a 422 naming the field; rows written before D-707 still read, so an
   invoice already issued renders as it did.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created, so
this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
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
                        "SELECT id, llm_model_surcharge, hard_cap_min, effective_from FROM plans "
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


async def test_retainer_terms_are_refused_and_a_model_surcharge_is_recorded() -> None:
    """D-707: every client buys prepaid credits, so no new terms may quote a setup fee, a
    monthly fee, included minutes or an overage rate — each is refused by name and nothing
    is written. What an operator still agrees here is the ceilings and the model surcharge,
    and the client's own usage summary prices that surcharge from the moment it lands."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    retainer = await _post(
        token,
        tenant_id,
        {
            "setup_fee_inr": "5000.00",
            "monthly_fee_inr": "9999.00",
            "included_minutes": 100,
            "overage_rate_inr": "8.0000",
        },
    )
    assert retainer.status_code == 422, retainer.text
    assert "retainer terms have ended" in retainer.text.lower()
    for field in ("setup fee", "monthly fee", "included minutes", "overage rate"):
        assert field in retainer.text.lower()
    assert await _plan_rows(tenant_id) == [], "a refused write must write nothing"

    response = await _post(
        token, tenant_id, {"llm_model_surcharge_inr": "1.5000", "hard_cap_minutes": 500}
    )
    assert response.status_code == 201, response.text
    assert response.json()["changed"] is True
    assert response.json()["state"] == "set"

    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
    assert summary["llm_surcharge_rate_inr"] == Decimal("1.5000")
    assert summary["monthly_fee_inr"] is None, "no retainer is raised after D-707"


async def test_a_plan_change_is_a_new_row_and_the_old_month_keeps_its_price() -> None:
    """THE property this whole surface exists to protect, and the one D-707 leans on to
    honour invoices already issued: an invoice is a DERIVED statement — re-rendering last
    month reads `plans` again — so a change that EDITED the row which priced it would
    silently rewrite a bill the client has already paid. The route inserts; the
    predecessor is left exactly as it was; and the closed month still resolves its terms,
    retainer fee included."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    this_month = billing.current_billing_month()
    last_month = _previous_month(this_month)

    # Last month's terms, written before D-707 and dated to have ended when this month
    # began — the row that priced it.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "llm_model_surcharge, effective_to, created_at, updated_at) VALUES (:i, :t, "
                "1000.00, 0, 5.0000, 1.0000, :to, clock_timestamp(), clock_timestamp())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "to": _month_start_ist(this_month)},
        )
    before = await _plan_rows(tenant_id)

    response = await _post(
        token,
        tenant_id,
        {
            "llm_model_surcharge_inr": "2.0000",
            "effective_from": _month_start_ist(this_month).isoformat(),
        },
    )
    assert response.status_code == 201, response.text

    after = await _plan_rows(tenant_id)
    assert len(after) == len(before) + 1, "a plan change must ADD a row"
    assert after[0] == before[0], (
        "the row that priced the closed month was modified — this is the money bug: "
        "the client's statement now says something else than when they paid it"
    )

    async with tenant_session(tenant_id) as session:
        closed = await billing.usage_summary(session, tenant_id=tenant_id, month=last_month)
        current = await billing.usage_summary(session, tenant_id=tenant_id, month=this_month)

    assert closed["monthly_fee_inr"] == Decimal("1000.00"), "an issued invoice keeps its fee"
    assert closed["llm_surcharge_rate_inr"] == Decimal("1.0000")
    assert current["monthly_fee_inr"] is None
    assert current["llm_surcharge_rate_inr"] == Decimal("2.0000")


async def test_terms_dated_for_next_month_do_not_price_today() -> None:
    """Preparing a change in advance is what the columns are FOR, and it must not move
    today's bill the moment the row lands."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    next_start = _month_start_ist(_next_month(billing.current_billing_month()))

    await _post(token, tenant_id, {"llm_model_surcharge_inr": "1.0000"})
    assert (
        await _post(
            token,
            tenant_id,
            {"llm_model_surcharge_inr": "3.0000", "effective_from": next_start.isoformat()},
        )
    ).status_code == 201

    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)

    assert summary["llm_surcharge_rate_inr"] == Decimal("1.0000"), "this month's, not next's"


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
        {"llm_model_surcharge_inr": "1.0000", "effective_from": last_month_start.isoformat()},
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
            "llm_model_surcharge_inr": "1.0000",
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
    body = {"llm_model_surcharge_inr": "1.2500", "hard_cap_minutes": 200}

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

    await _post(token, tenant_id, {"llm_model_surcharge_inr": "1.0000"})
    await _post(token, tenant_id, {"llm_model_surcharge_inr": "2.0000"})

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

    first = await _post(
        token, tenant_id, {"llm_model_surcharge_inr": "1.0000", "hard_cap_minutes": 500}
    )
    tighter = await _post(
        token, tenant_id, {"llm_model_surcharge_inr": "1.0000", "hard_cap_minutes": 100}
    )

    assert first.status_code == 201, first.text
    assert tighter.status_code == 201, tighter.text


async def test_an_operator_may_not_raise_a_ceiling() -> None:
    """`core/rbac.py`'s role table reserves cap raises for `superadmin`, and
    `plans.hard_cap_*` is the ceiling the dispatch gate enforces."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    await _post(
        token, tenant_id, {"llm_model_surcharge_inr": "1.0000", "hard_cap_spend_inr": "1000.00"}
    )

    raised = await _post(
        token,
        tenant_id,
        {"llm_model_surcharge_inr": "1.0000", "hard_cap_spend_inr": "9000.00"},
        confirm=_confirmation(tenant_id),
    )

    assert raised.status_code == 403, raised.text
    assert "superadmin" in raised.text


async def test_removing_a_ceiling_counts_as_loosening_it() -> None:
    """`null` is the LOOSEST value there is — the tenant becomes unlimited — so it takes
    the same authority as raising the number, not less."""
    tenant_id = await _tenant()
    operator = await _make_admin("operator")
    await _post(operator, tenant_id, {"llm_model_surcharge_inr": "1.0000", "hard_cap_minutes": 100})

    removed = await _post(
        operator, tenant_id, {"llm_model_surcharge_inr": "1.0000"}, confirm=_confirmation(tenant_id)
    )

    assert removed.status_code == 403, removed.text


async def test_a_superadmin_raising_a_ceiling_still_needs_the_confirmation() -> None:
    """Two keys, not one: the role says who may, the step-up says this request meant to.
    And the header is bound to the TENANT, so a confirmation captured while raising one
    client's ceiling cannot be replayed against another's."""
    tenant_id = await _tenant()
    other_id = await _tenant()
    token = await _make_admin("superadmin")
    await _post(token, tenant_id, {"llm_model_surcharge_inr": "1.0000", "hard_cap_minutes": 100})
    raise_body = {"llm_model_surcharge_inr": "1.0000", "hard_cap_minutes": 900}

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
    """`2.5` as a JSON number has already been through a binary float by the time Pydantic
    sees it. The rate keeps FOUR decimal places on the way out, unrounded, because the
    invoice's `qty x unit = amount` only holds if it does."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    floated = await _post(token, tenant_id, {"llm_model_surcharge_inr": 2.5})
    exact = await _post(token, tenant_id, {"llm_model_surcharge_inr": "7.1250"})

    assert floated.status_code == 422, floated.text
    assert exact.status_code == 201, exact.text
    body = (await _get(token, tenant_id)).json()["in_effect"]
    assert body["llm_model_surcharge_inr"] == "7.1250", "a rate is published unrounded"


async def test_the_retired_fields_are_still_accepted_as_null_from_an_older_console() -> None:
    """Hard rule 8's two-step: a console one release behind still sends every retainer
    field, as null. That must still record its ceilings, and the read still publishes the
    retired columns (null) so an older console renders."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    response = await _post(
        token,
        tenant_id,
        {
            "setup_fee_inr": None,
            "monthly_fee_inr": None,
            "included_minutes": None,
            "overage_rate_inr": None,
            "overage_rate_second_inr": None,
            "overage_rate_value_inr": None,
            "hard_cap_minutes": 300,
        },
    )
    assert response.status_code == 201, response.text
    row = (await _get(token, tenant_id)).json()["in_effect"]
    assert row["hard_cap_minutes"] == 300
    assert row["monthly_fee_inr"] is None and row["overage_rate_second_inr"] is None


@pytest.mark.parametrize(
    "field,value,label",
    [
        ("overage_rate_second_inr", "5.5000", "second overage rate"),
        ("overage_rate_value_inr", "4.2500", "second overage rate (old name)"),
        ("included_minutes", 100, "included minutes"),
    ],
)
async def test_each_retainer_field_is_refused_on_its_own(
    field: str, value: object, label: str
) -> None:
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    response = await _post(token, tenant_id, {field: value})
    assert response.status_code == 422, response.text
    assert label in response.text.lower()
    assert await _plan_rows(tenant_id) == []


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

    await _post(token, tenant_id, {"llm_model_surcharge_inr": "4.2420"})

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
    response = await _post(token, uuid.uuid4(), {"llm_model_surcharge_inr": "1.0000"})
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
            {"llm_model_surcharge_inr": "1.5000", "hard_cap_minutes": 100},
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


async def test_a_retainer_row_from_before_d706_still_reads_with_its_margin() -> None:
    """Invoices already issued are honoured, so a retainer row written before D-707 is
    still history an operator reads — with the margin it was struck at."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "created_at, updated_at) VALUES (:i, :t, 9999.00, 2000, 8.0000, "
                "clock_timestamp(), clock_timestamp())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id},
        )
    body = (await _get(await _make_admin("operator"), tenant_id)).json()
    assert body["state"] == "set"
    assert body["in_effect"]["monthly_fee_inr"] == "9999.0000"
    assert Decimal(body["in_effect"]["margin"]["effective_committed_rate_inr_per_min"]) == Decimal(
        "4.9995"
    )
