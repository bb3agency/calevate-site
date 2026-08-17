"""Suspend, reactivate, close — and the dialling that has to stop when they do.

THE DEFECT. `organizations.status` carried a five-value CHECK from the very first
migration and was READ by the health board's ended-account filter (`admin/health.py`),
but **nothing anywhere wrote it**. There was no suspend, no reactivate and no offboard
route in either realm, so SURFACES §1's "suspend/reactivate, offboarding trigger" was
a column and a hope. Worse than missing: had an operator set it by hand, it would have
changed nothing at all — the dial gate never read it, so a client suspended over
complaints or non-payment would have gone on dialling through every campaign they had
running. That half is compliance-adjacent, which is why it is the first thing asserted
here.

What is pinned:

1. **Suspending stops outbound dialling** — at the dial gate every outbound path calls
   (hard rule 5), and at the campaign launch gate under the same rule name.
2. **Reactivating releases it**, so the control is reversible in one press.
3. **The three transition answers**, which is the whole contract of
   `db/transition.py::transition_status`: already-in-state is a SUCCESS, a different
   state is a 409 NAMING what was found, an absent row is a 404.
4. **`churned` is terminal**, so re-opening an account is a new agreement rather than a
   button that silently un-ends an offboarding.
5. **Audit follows a real transition**, never a button press; and a stopping state must
   explain itself.
6. **Closing an account does not touch `plans`** — the final invoice for the month a
   client churned in still has to resolve the terms that priced it.
7. **RLS**: one tenant's session cannot move another tenant's status.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.db.transition import transition_status
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.commercial_terms_test import _make_admin, _tenant

STATUS = "/v1/admin/tenants/{tenant_id}/status"


@pytest.fixture(autouse=True)
def _gate_reaches_the_account_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The big red switch is checked BEFORE the account state and is global platform
    state a concurrently running suite can flip; calling hours are checked after, so a
    22:00 IST run would mask every "allowed" assertion. Neither stub can manufacture an
    `account_suspended` refusal, which is what the refusal cases assert on. Copied from
    `tests/spend_caps_test.py`, which makes the same two pins for the same reasons."""
    from apps.api.core.loadshed import PlatformStatus

    async def _running(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=False)

    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _running)
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _set_status(token: str, tenant_id: UUID, status: str, reason: str | None = None) -> Any:
    body: dict[str, Any] = {"status": status}
    if reason is not None:
        body["reason"] = reason
    async with _client() as http:
        return await http.post(
            STATUS.format(tenant_id=tenant_id),
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )


async def _dialable_tenant() -> tuple[UUID, UUID]:
    """A tenant with a LIVE OUTBOUND agent — what `check_dispatch` needs before it can
    reach any tenant-level rule at all; an inbound or draft agent is refused earlier."""
    tenant_id = await _tenant()
    agent_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, created_at, "
                "updated_at) VALUES (:id, :tid, 'Follow-up caller', 'outbound', 'Idi AI assistant. "
                "Call record avutundi.', 'Idi AI assistant. Call record avutundi.', 'This call is "
                "being recorded.', 'live', 'fake', now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
    return tenant_id, agent_id


async def _gate(tenant_id: UUID, agent_id: UUID) -> Any:
    """A fresh number every call, so a DNC entry another suite added can never be what
    refuses us."""
    phone = f"+9199{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )


async def _status_of(tenant_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar()
        )


async def _audit_actions(tenant_id: UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        return [
            str(row[0])
            for row in (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE tenant_id = :t "
                        "AND action LIKE 'tenant.%' ORDER BY created_at"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        ]


# ============================================================================
# 1. A suspended tenant does not dial
# ============================================================================


async def test_suspending_a_tenant_stops_its_outbound_dialling() -> None:
    """The half that makes the status mean something.

    Before this, a suspension was a colour on a screen: the campaign tick, the "call
    this lead" button and the lead-callback webhook all go through `check_dispatch`, and
    `check_dispatch` never read the account's own state. A client we stopped kept
    dialling until somebody deleted their agents by hand.
    """
    tenant_id, agent_id = await _dialable_tenant()
    token = await _make_admin("operator")
    assert (await _gate(tenant_id, agent_id)).allowed is True, "the tenant dials to begin with"

    response = await _set_status(token, tenant_id, "suspended", "non-payment, 60 days")

    assert response.status_code == 200, response.text
    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is False
    assert decision.rule == "account_suspended"
    assert "suspended" in (decision.reason or "")


async def test_reactivating_a_tenant_releases_the_gate_again() -> None:
    """One press back. A control an operator cannot undo in the same screen is a support
    ticket, and suspension is used exactly when the answer might change tomorrow."""
    tenant_id, agent_id = await _dialable_tenant()
    token = await _make_admin("operator")
    await _set_status(token, tenant_id, "suspended", "card declined")

    response = await _set_status(token, tenant_id, "active")

    assert response.status_code == 200, response.text
    assert (await _gate(tenant_id, agent_id)).allowed is True


async def test_a_closed_account_dials_nothing_either() -> None:
    tenant_id, agent_id = await _dialable_tenant()
    token = await _make_admin("operator")

    await _set_status(token, tenant_id, "churned", "offboarded at the client's request")

    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is False and decision.rule == "account_closed"


async def test_the_campaign_launch_gate_names_the_same_rule() -> None:
    """A campaign that launched "ready" and was then refused on every single contact is
    the shape `launch_blockers` exists to prevent — it asks the tenant-level rules under
    the SAME names the dial gate uses, so the two gates cannot explain one condition two
    different ways."""
    from apps.api.campaigns.service import launch_blockers

    tenant_id, agent_id = await _dialable_tenant()
    token = await _make_admin("operator")
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, "
                "classification, created_at, updated_at) VALUES (:id, :tid, :aid, "
                "'Winter checkup', 'draft', 'service', now(), now())"
            ),
            {"id": campaign_id, "tid": tenant_id, "aid": agent_id},
        )
    await _set_status(token, tenant_id, "suspended", "complaints under review")

    async with tenant_session(tenant_id) as session:
        blockers = await launch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)

    assert "account_suspended" in [blocker.rule for blocker in blockers]


# ============================================================================
# 2. The three answers a transition has (db/transition.py)
# ============================================================================


async def test_setting_the_state_an_account_is_already_in_is_a_success() -> None:
    """RFC 9110 §9.2.2: the effect of N identical requests is the effect of one. The
    second click of a button, or the retry of a request whose response was lost, is not
    a conflict — and it writes no second audit row."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    first = await _set_status(token, tenant_id, "suspended", "non-payment")
    second = await _set_status(token, tenant_id, "suspended", "non-payment")

    assert first.status_code == 200 and first.json()["changed"] is True
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is False
    assert await _audit_actions(tenant_id) == ["tenant.suspended"], (
        "the audit log records transitions, not button presses"
    )


async def test_a_move_from_a_state_that_does_not_allow_it_is_a_409_naming_that_state() -> None:
    """`churned` is terminal on this surface: `core/auth.py` already excludes a churned
    org from every membership resolution, so its users are locked out and its data is on
    the retention clock. Re-opening it is a new agreement, not a button. The refusal has
    to NAME the state found, or an operator is told "conflict" and nothing else."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    await _set_status(token, tenant_id, "churned", "offboarded")

    response = await _set_status(token, tenant_id, "active")

    assert response.status_code == 409, response.text
    assert "churned" in response.text
    assert await _status_of(tenant_id) == "churned"


async def test_a_tenant_that_does_not_exist_is_a_404() -> None:
    token = await _make_admin("operator")
    response = await _set_status(token, uuid.uuid4(), "suspended", "typo in the id")
    assert response.status_code == 404, response.text


# ============================================================================
# 3. What the surface refuses to do quietly
# ============================================================================


async def test_stopping_an_account_must_explain_itself() -> None:
    """Somebody will have to answer "why is this account suspended" later, and a
    suspension with no reason recorded is the ticket nobody can close. Reactivation
    needs none — the state it moves TO is the harmless one."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")

    reasonless = await _set_status(token, tenant_id, "suspended")
    explained = await _set_status(token, tenant_id, "suspended", "chargeback")
    released = await _set_status(token, tenant_id, "active")

    assert reasonless.status_code == 422, reasonless.text
    assert explained.status_code == 200
    assert released.status_code == 200, released.text


async def test_closing_an_account_does_not_end_its_commercial_terms() -> None:
    """A money decision, not an omission. The final invoice for the month a client
    churned in is DERIVED, so a plan window closed at the moment of churn would leave
    that month with no plan in effect and render their last statement at ₹0.00
    (`billing/plans.py`: an ended window prices nothing, on purpose). Terms are ended
    where terms are agreed."""
    tenant_id = await _tenant()
    token = await _make_admin("operator")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, created_at, updated_at) "
                "VALUES (:i, :t, 9999.00, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id},
        )

    await _set_status(token, tenant_id, "churned", "offboarded")

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT effective_to FROM plans WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).first()
    assert row is not None and row[0] is None, (
        "churning a client must not close their plan window — their last statement "
        "would render at zero"
    )


# ============================================================================
# 4. Tenancy (hard rule 1)
# ============================================================================


async def test_one_tenants_session_cannot_move_another_tenants_status() -> None:
    """`organizations` is FORCE RLS'd on `id`, and the route runs inside
    `tenant_session(tenant_id)`. A neighbour's id therefore updates nothing and then
    reads no row — which `transition_status` reports as a 404, deliberately the same
    answer an id that never existed gets."""
    tenant_id = await _tenant()
    neighbour_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await transition_status(
                session,
                table="organizations",
                entity="Client",
                row_id=neighbour_id,
                to_status="suspended",
                from_statuses=("prospect", "onboarding", "active"),
            )
    assert raised.value.status == 404
    assert await _status_of(neighbour_id) == "onboarding", "the neighbour is untouched"


async def test_the_transition_primitive_is_the_one_this_route_uses() -> None:
    """A guard against the second discriminator. If this route ever grows its own
    read-then-write, the 409 below stops naming the state it found and this fails."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await transition_status(
            session,
            table="organizations",
            entity="Client",
            row_id=tenant_id,
            to_status="churned",
            from_statuses=("prospect", "onboarding", "active", "suspended"),
        )
        with pytest.raises(InvalidStatusTransitionError) as raised:
            await transition_status(
                session,
                table="organizations",
                entity="Client",
                row_id=tenant_id,
                to_status="active",
                from_statuses=("prospect", "onboarding", "suspended"),
            )
    assert "churned" in str(raised.value.detail)


async def test_a_soft_deleted_account_dials_nothing() -> None:
    """`account_stopped_blocker` fails CLOSED. A row we cannot confirm — soft-deleted
    here — is refused rather than waved through: dialling on an unconfirmed account is
    the error that cannot be taken back."""
    tenant_id, agent_id = await _dialable_tenant()
    # The tenant's OWN session: `organizations`' policy matches on `id`, so an
    # untenanted session silently matches no row and the fixture would write nothing.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            # `status = 'churned'` in the same statement, because `deleted_at` is not a
            # free-standing flag: `ck_organizations_deleted_implies_churned` (D-122) makes
            # an erased tenant always a churned one, which is what lets the readers of the
            # column filter on different halves of "account closed" and still agree. The
            # real writer (`workers/retention.execute_tenant_erasure`) refuses to run at
            # all unless the account is already churned, so this fixture is now producing
            # a state the product can actually reach rather than one only a test could.
            text("UPDATE organizations SET deleted_at = now(), status = 'churned' WHERE id = :t"),
            {"t": tenant_id},
        )

    decision = await _gate(tenant_id, agent_id)

    assert decision.allowed is False and decision.rule == "account_closed"


async def test_an_account_row_the_session_cannot_read_is_refused_not_waved_through() -> None:
    """The OTHER half of failing closed, and the half a soft-delete cannot reach.

    `account_stopped_blocker` reads one row and decides on its `status`. The soft-delete
    case above proves a row that says "stopped" refuses. This proves the case where there
    is NO row to read at all — the tenant does not exist, or RLS shows the session
    nothing — and it is the more dangerous of the two, because "no row" is what a
    misconfigured session, a typo'd id and a mid-erasure tenant all look like. Read
    literally, `SELECT ... WHERE id = :tid` returning nothing says only "I found no
    reason to stop you", which is exactly the sentence a dial gate must not accept.

    Kept as its own test rather than folded into the soft-delete one because the two
    take different branches (`row is None` vs a populated row) and a single test would
    leave whichever branch it did not take uncovered — which is how this branch was
    uncovered when the coverage ratchet flagged it (hard rule 5 surface, +2 units).
    """
    _, agent_id = await _dialable_tenant()
    # A tenant id that never existed. `check_dispatch` runs under that id's own session,
    # so `organizations`' policy matches nothing and the read comes back empty — the same
    # shape an operator would produce by pointing the gate at a deleted tenant.
    decision = await _gate(uuid7(), agent_id)

    assert decision.allowed is False
    assert decision.rule == "account_missing"
    assert decision.reason, "a refusal a caller cannot read is a refusal they cannot act on"
