"""The ops-realm spend-cap recompute — closing the dead end `runbooks/calls-stopped.md`
found while it was being written.

THE DEAD END. `compliance.spend_capped` reads `spend_state.capped` and nothing else.
Until now that flag had exactly two writers: the post-call meter, which ARMS it, and
`billing.caps.apply_client_caps`, which the CLIENT reaches through
`PUT /v1/billing/caps`. A capped tenant meters nothing, so the meter can never clear
what it set; and `org:manage` is in `MUTATING_PERMISSIONS`, so an impersonating admin
(D-22) cannot press the client's button for them. Raising `plans.hard_cap_*` on the
audited admin path therefore left a capped OUTBOUND-ONLY tenant blocked — with the
ceiling now above their spend, the gate still refusing every dial, and nothing in the
platform able to recompute it until the IST month rolled over.

`POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute` is the third writer, and every
constraint on it is asserted below rather than described:

1. **It closes the dead end** — the sequence from the runbook, end to end: cap, refuse,
   raise the ceiling in SQL, still refused, recompute, dial allowed.
2. **It RECOMPUTES, it does not un-cap.** A tenant still genuinely over its effective
   ceiling stays capped, and the counters are not moved by a single paise. That is the
   discipline `apply_client_caps` follows and the reason the flag has one definition
   (`over_cap_sql`) rather than one per writer.
3. **It is step-up confirmed, and the confirmation is BOUND TO THE TENANT.** A header
   echoing another tenant's action does not authorise this one — the property
   BACKEND-PATTERNS §7 asks for and the one `set_platform`'s generic
   `set_platform_state` confirmation only partly has (the KNOWN GAP its comment
   records). Nothing here widens that gap.
4. **It is audited**, in the same transaction as the write, with the tenant named.
5. **A stale-month row is left alone**, exactly as `apply_client_caps` leaves it:
   `spend_capped` already treats a flag from a closed month as no cap, so rewriting it
   would move a number nobody reads.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created, so
this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.core.rbac import iter_api_routes
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.spend_caps_test import LAST_MONTH, THIS_MONTH, _bill, _gate, _plan, _tenant

ROUTE = "/v1/ops/tenants/{tenant_id}/spend-cap/recompute"


@pytest.fixture(autouse=True)
def _gate_reaches_the_spend_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two pins `tests/spend_caps_test.py` explains: calling hours is checked AFTER
    the spend cap (so a 22:00 IST run would mask every "not capped" assertion) and the
    big red switch is global state a concurrent suite can flip. Neither weakens a
    refusal case — those assert `rule == "spend_cap"`, which no stub can manufacture."""
    from apps.api.core.loadshed import PlatformStatus

    async def _running(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=False)

    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _running)
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """Same idiom as `route_shape_test._make_admin`: a real admin row, dev-token realm."""
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


async def _recompute(token: str, tenant_id: UUID, *, confirm: str | None = None):  # type: ignore[no-untyped-def]
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    async with _client() as http:
        return await http.post(ROUTE.format(tenant_id=tenant_id), headers=headers)


def _confirmation(tenant_id: UUID) -> str:
    """The header an operator sends. Deliberately spelled out here rather than imported
    from the route: if the binding ever changes shape, this test is where it is noticed,
    because the string is part of the ops procedure in `runbooks/calls-stopped.md`."""
    return f"recompute_spend_cap:{tenant_id}"


async def _raise_the_admin_ceiling(tenant_id: UUID, *, cap_min: int) -> None:
    """What an operator does today: a hand-written UPDATE on the audited admin path
    against the tenant's NEWEST `plans` row (`plans` is effective-dated — every reader
    in the codebase takes `ORDER BY created_at DESC LIMIT 1`). This is precisely the act
    that used to leave the tenant stopped."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE plans SET hard_cap_min = :cap, updated_at = now() WHERE id = "
                "(SELECT id FROM plans WHERE tenant_id = :tid ORDER BY created_at DESC LIMIT 1)"
            ),
            {"cap": cap_min, "tid": tenant_id},
        )


async def _counters(tenant_id: UUID) -> tuple[str, Decimal, Decimal, bool]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT month, minutes_used, spend_used, capped FROM spend_state "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
    assert row is not None, "the meter must have left a spend_state row"
    return str(row[0]), row[1], row[2], bool(row[3])


# ============================================================================
# 1. The dead end, closed
# ============================================================================


async def test_raising_the_plan_ceiling_and_recomputing_releases_a_capped_tenant() -> None:
    """The runbook's step 2 trap, played out in full.

    Every line of this is the incident: the tenant is capped by OUR ceiling, ops raises
    that ceiling the only way there is, and the gate goes on refusing because the flag
    is a derived column nothing recomputed. One ops call — no client action, no month
    rollover — and the next dial is allowed.
    """
    tenant_id, agent_id, _ = await _tenant("opsrecompute")
    await _plan(tenant_id, cap_min=2)
    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=THIS_MONTH)

    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"

    await _raise_the_admin_ceiling(tenant_id, cap_min=500)
    still_refused = await _gate(tenant_id, agent_id)
    assert still_refused.allowed is False and still_refused.rule == "spend_cap", (
        "raising the ceiling alone must NOT release the gate — if this ever passes, the "
        "flag has stopped being the thing the gate reads and this whole surface is moot"
    )

    token = await _make_admin()
    response = await _recompute(token, tenant_id, confirm=_confirmation(tenant_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["capped_before"] is True
    assert body["capped"] is False
    assert body["effective_cap_minutes"] == 500

    released = await _gate(tenant_id, agent_id)
    assert released.allowed is True, (
        f"the tenant is still stopped after the recompute: {released.rule}"
    )


# ============================================================================
# 2. It recomputes — it is not an un-cap button
# ============================================================================


async def test_a_tenant_still_over_its_ceiling_stays_capped() -> None:
    """The reason this is a RECOMPUTE and not a `capped = false`.

    An operator who runs it against a tenant that is genuinely over its ceiling must get
    the truth back, not a released gate. A direct write would make the flag and the
    counters disagree, and the next metered call would arm it again anyway — leaving a
    tenant that dialled for an hour on a ceiling they had exhausted.
    """
    tenant_id, agent_id, _ = await _tenant("stillover")
    await _plan(tenant_id, cap_min=2)
    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=THIS_MONTH)

    token = await _make_admin()
    response = await _recompute(token, tenant_id, confirm=_confirmation(tenant_id))

    assert response.status_code == 200, response.text
    assert response.json()["capped"] is True, "3 minutes against a 2-minute cap is capped"
    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"


async def test_the_recompute_moves_no_total() -> None:
    """It writes the flag and only the flag, from the counters ALREADY in the row.

    A writer that touched `minutes_used` or `spend_used` would be rewriting metered
    usage from an ops console — the thing the invoice is built from.
    """
    tenant_id, agent_id, _ = await _tenant("nototals")
    await _plan(tenant_id, cap_min=2)
    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=THIS_MONTH)
    before = await _counters(tenant_id)

    token = await _make_admin()
    await _raise_the_admin_ceiling(tenant_id, cap_min=500)
    response = await _recompute(token, tenant_id, confirm=_confirmation(tenant_id))
    assert response.status_code == 200, response.text

    month, minutes, spend, capped = await _counters(tenant_id)
    assert (month, minutes, spend) == before[:3], (
        f"the recompute moved a total: {before[:3]} -> {(month, minutes, spend)}"
    )
    assert capped is False, "only the flag may change, and it must reflect the new ceiling"


async def test_a_stale_month_row_is_left_exactly_as_it_was() -> None:
    """A flag belonging to a closed billing month is not a cap — `spend_capped` reads
    `month` too — so there is nothing to recompute and nothing is written.

    Rewriting it against THIS month's ceilings would evaluate last month's counters as
    though they were today's, which is how a tenant gets capped for spending they
    already paid for.
    """
    tenant_id, agent_id, _ = await _tenant("stalemonth")
    await _plan(tenant_id, cap_min=2)
    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=LAST_MONTH)
    before = await _counters(tenant_id)
    assert before[3] is True, "the meter armed the cap in the month it metered"

    token = await _make_admin()
    response = await _recompute(token, tenant_id, confirm=_confirmation(tenant_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["capped"] is False, (
        "a cap from a closed month is not a cap — the response must say what is in "
        "force, which is nothing"
    )
    assert body["minutes_used"] == "0.00" and body["spend_used_inr"] == "0.00", (
        "last month's counters are not this month's spend"
    )
    assert await _counters(tenant_id) == before, "the stale row itself must be untouched"


# ============================================================================
# 3. Step-up confirmation, bound to the tenant
# ============================================================================


async def test_the_recompute_refuses_without_the_step_up_header() -> None:
    tenant_id, _agent_id, _ = await _tenant("nostepup")
    token = await _make_admin()

    response = await _recompute(token, tenant_id)

    assert response.status_code == 403, response.text
    problem = response.json()
    assert problem["kind"] == "permission"
    assert problem["type"].rsplit("/", 1)[-1] == "step_up_required"
    assert str(tenant_id) in problem["remediation"], (
        "the remediation must name the exact header to send, tenant and all — an "
        "operator reading it mid-incident should not have to guess the format"
    )


async def test_a_confirmation_for_one_tenant_does_not_authorise_another() -> None:
    """The property BACKEND-PATTERNS §7 actually asks for: bound to the SPECIFIC action.

    `set_platform`'s confirmation is generic (`set_platform_state` covers both a routine
    load-shed change and releasing the big red switch) and its comment records that as a
    known gap. This route does not repeat it: the tenant is part of the string, so a
    header captured from one operation cannot be replayed against another tenant.
    """
    victim, _agent, _ = await _tenant("wrongtenant-a")
    other, _agent2, _ = await _tenant("wrongtenant-b")
    token = await _make_admin()

    response = await _recompute(token, victim, confirm=_confirmation(other))

    assert response.status_code == 403, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "step_up_required"


async def test_an_operator_without_ops_manage_cannot_recompute() -> None:
    """`ops:manage` is a superadmin permission. An `operator` holds `admin:tenants` and
    every support power, and still may not touch a compliance-adjacent control."""
    tenant_id, _agent_id, _ = await _tenant("operatorrole")
    token = await _make_admin(role="operator")

    response = await _recompute(token, tenant_id, confirm=_confirmation(tenant_id))

    assert response.status_code == 403, response.text


async def test_an_unknown_tenant_is_a_404_not_a_silent_success() -> None:
    """A mistyped uuid must not answer 200 with a cheerful "not capped" — mid-incident
    that reads as "I fixed it" and the real tenant is still stopped."""
    token = await _make_admin()
    missing = uuid.uuid4()

    response = await _recompute(token, missing, confirm=_confirmation(missing))

    assert response.status_code == 404, response.text


# ============================================================================
# 4. Audited, and mounted
# ============================================================================


async def test_the_recompute_writes_one_audit_row_naming_the_tenant() -> None:
    """An ops action on a compliance-adjacent control leaves a record of who ran it
    against whom. `audit_log` is INSERT-only (hard rule 4) and `write_audit` appends in
    the same transaction as the flag write, so a recompute with no audit row is not a
    reachable state."""
    tenant_id, agent_id, _ = await _tenant("auditrow")
    await _plan(tenant_id, cap_min=2)
    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=THIS_MONTH)
    token = await _make_admin()

    response = await _recompute(token, tenant_id, confirm=_confirmation(tenant_id))
    assert response.status_code == 200, response.text

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_type, object_id, actor_type FROM audit_log "
                    "WHERE tenant_id = :tid ORDER BY at DESC"
                ),
                {"tid": tenant_id},
            )
        ).all()

    assert [row[0] for row in rows] == ["ops.recompute_spend_cap"], (
        f"expected exactly one audit row for this tenant, got {[row[0] for row in rows]}"
    )
    assert rows[0][1] == "spend_state" and rows[0][2] == str(tenant_id)
    assert rows[0][3] == "admin"


def test_the_route_is_mounted_and_names_its_tenant_in_the_path() -> None:
    """A router nobody mounted is not a surface. It also has to name its tenant in the
    path: an admin-realm mutation that inferred the tenant from the session would be
    un-callable by construction (D-22, `route_shape_test`)."""
    routes = {route.path: route for route in iter_api_routes(app)}
    assert ROUTE in routes, f"{ROUTE} is not mounted"
    assert "POST" in (routes[ROUTE].methods or set())
    assert "tenant_id" in {param.name for param in routes[ROUTE].dependant.path_params}
