"""D-521: prepaid is the default motion, and the two tier questions are not one question.

The defect: `DEFAULT_PLAN_TIER` was `managed`, so EVERY account was created invoiced —
its wallet inert, the credits portal dead to it, and nothing stopping its dialling for
want of credit. The founder opened a real client's credits screen and read "this account
is invoiced, not prepaid", which is the screen a client sees when the product's default
is the motion the product does not sell.

The fix is a fourth tier rather than a rename, and this file pins the part of it that is
easy to get wrong. `plan_tier` answers TWO questions that had identical answers until now:

  * **does this account pay from a wallet?** — `billing.rates.PREPAID_TIERS`, which gains
    `prepaid` and is now the common case;
  * **did a stranger open this account unattended?** — `compliance.service
    .SELF_SERVE_TIERS`, which does NOT, because that is what the subscriber-KYC dial gate
    (D-47) and the first-campaign hold (D-51) key on.

`SELF_SERVE_TIERS` was literally `= PREPAID_TIERS` before this change. Had it stayed an
alias, the migration that moved every existing tenant onto prepaid would have refused
every one of their dials with `kyc_missing` and held every campaign for review — a
platform-wide outage delivered as a billing change. Half the assertions here exist to make
that re-derivation fail loudly.

CONCURRENCY: every case mints its own tenant, so this file runs beside the other suites on
the shared Postgres.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.ai_quota import AI_QUOTA_INR
from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import plan_tier_of, record_entry
from apps.api.compliance.service import (
    SELF_SERVE_TIERS,
    check_dispatch,
    credits_exhausted,
    first_campaign_hold_blocker,
    kyc_blocker,
)
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from apps.api.tenancy.models import DEFAULT_PLAN_TIER, PLAN_TIERS
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements

REPO_ROOT = Path(__file__).resolve().parents[1]


async def _tenant(plan_tier: str | None = None) -> uuid.UUID:
    """A live tenant, on the DEFAULT tier unless a case names another.

    `plan_tier=None` deliberately passes nothing to `create_organization`, because "what
    does a new account get" is the question this file is about.
    """
    created = await admin_service.create_organization(
        name="Tier Split Clinic",
        slug=f"tier-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
        plan_tier=plan_tier,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id


async def _outbound_agent(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    return uuid.UUID(str(agent_id))


# --- the constants -------------------------------------------------------------------


def test_the_default_is_a_prepaid_tier() -> None:
    """The whole decision in one assertion. `DEFAULT_PLAN_TIER` was `managed`."""
    assert DEFAULT_PLAN_TIER == "prepaid"
    assert DEFAULT_PLAN_TIER in PREPAID_TIERS
    assert DEFAULT_PLAN_TIER in PLAN_TIERS, "the default must be a value the CHECK admits"


def test_every_unattended_signup_tier_is_also_prepaid() -> None:
    """CONTAINMENT is what survived the split, and it is the property the old
    `SELF_SERVE_TIERS = PREPAID_TIERS` alias was really protecting: a tier whose wallet
    the meter drains while the dial gate does not stop it runs negative forever."""
    assert set(SELF_SERVE_TIERS) <= set(PREPAID_TIERS)


def test_the_default_tier_does_not_pick_up_the_identity_gates() -> None:
    """The half that would have turned this billing change into an outage.

    `kyc_blocker` and `first_campaign_hold_blocker` exist because on the self-serve motion
    the applicant is a stranger (D-47/D-51). An operator who creates a client has met them,
    so the tier every operator-created account now gets must NOT be in that set.
    """
    assert DEFAULT_PLAN_TIER not in SELF_SERVE_TIERS
    assert set(SELF_SERVE_TIERS) == {"self_serve", "trial"}


def test_every_declared_tier_is_accounted_for_by_one_branch_or_the_other() -> None:
    """A fifth tier added to the enum and to neither predicate is an account that pays
    from no wallet and is invoiced against no retainer — which reads, everywhere, as
    "dial for free"."""
    invoiced = {"managed"}
    assert set(PLAN_TIERS) == set(PREPAID_TIERS) | invoiced


def test_every_tier_has_an_ai_allowance() -> None:
    """`AI_QUOTA_INR.get(tier, AI_QUOTA_INR["trial"])` falls back SILENTLY, so a tier
    missing here does not raise — it quietly gives that account the trial allowance. The
    migration moved live accounts onto `prepaid`; ₹250 -> ₹40 with no error anywhere is
    exactly the silent reduction a data migration may not make."""
    assert set(AI_QUOTA_INR) == set(PLAN_TIERS)
    assert AI_QUOTA_INR["prepaid"] == AI_QUOTA_INR["managed"], (
        "a migrated account must not lose allowance it already had"
    )


def test_the_browser_mirrors_the_servers_prepaid_set() -> None:
    """`apps/web/src/lib/api/billing.ts` decides which of the two credits screens a client
    sees. If it drifts, a prepaid client is offered the invoiced card — the exact screen
    this decision exists to stop — and no Python test would notice."""
    source = (REPO_ROOT / "apps/web/src/lib/api/billing.ts").read_text(encoding="utf-8")
    rendered = ", ".join(f'"{tier}"' for tier in PREPAID_TIERS)
    assert f"export const PREPAID_TIERS = [{rendered}] as const;" in source, (
        "the browser's PREPAID_TIERS no longer matches billing/rates.py"
    )


# --- what a new account actually gets -------------------------------------------------


async def test_a_new_account_is_created_prepaid() -> None:
    """Through `create_organization`, which is what BOTH doors call — the admin wizard
    passes no tier at all, and this is the line that used to make it `managed`."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await plan_tier_of(session, tenant_id) == "prepaid"


async def test_a_new_accounts_empty_wallet_stops_its_outbound_dialling() -> None:
    """The point of the decision: a new account is credit-gated. Before D-521 this
    returned some other rule (or allowed the dial), because the account was invoiced."""
    tenant_id = await _tenant()
    agent_id = await _outbound_agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id) is True
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500031"
        )
    assert not decision.allowed
    assert decision.rule == "no_credits", decision.rule


async def test_a_topped_up_account_is_not_stopped_by_credits() -> None:
    """The control: `no_credits` must be about the BALANCE and not about the tier."""
    tenant_id = await _tenant()
    agent_id = await _outbound_agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal("500"), reason="topup")
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500032"
        )
    assert decision.rule != "no_credits"


async def test_a_prepaid_account_is_not_held_by_the_stranger_gates() -> None:
    """Asked of the two predicates directly, because `check_dispatch` returns only the
    FIRST refusal: with an empty wallet, `no_credits` would mask a `kyc_missing` that the
    tenant was never supposed to get. KYC outranks credits in that ladder, so a
    regression here would show up as a client told to top up when topping up cannot
    unblock them."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await kyc_blocker(session, tenant_id=tenant_id) is None
        assert await first_campaign_hold_blocker(session, tenant_id=tenant_id) is None


async def test_an_inbound_only_agent_still_answers_at_a_zero_balance() -> None:
    """DECIDED EARLIER IN THIS SESSION AND NOT REVISITED: at zero, outbound campaigns
    stop and inbound calls are still answered. A clinic whose phone stops being answered
    because a top-up lapsed is a clinic that leaves.

    The proof is the ORDER of the gate, not a separate code path: `check_dispatch` refuses
    an inbound-only agent with `agent_inbound_only` BEFORE it reads any money, and no
    inbound path calls it at all. So the assertion is that a wallet-empty prepaid tenant
    with an inbound agent is refused for the direction and never for the balance — which
    is what would break the day somebody moved the credit check up the ladder.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'inbound' WHERE id = :a"),
            {"a": agent_id},
        )
        assert await credits_exhausted(session, tenant_id=tenant_id) is True
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500033"
        )
    assert decision.rule == "agent_inbound_only", (
        "an inbound agent must be refused for its direction, never for its wallet"
    )


async def test_a_managed_account_still_dials_with_no_wallet() -> None:
    """`managed` SURVIVES D-521 — the founder chose keeping the seam over deleting it,
    because re-adding a second billing motion later is a much bigger build."""
    tenant_id = await _tenant("managed")
    agent_id = await _outbound_agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id) is False
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876500034"
        )
    assert decision.rule != "no_credits"


async def test_an_invisible_row_reads_as_the_platform_default() -> None:
    """`plan_tier_of` answers for a row it cannot see — a mistyped id, or another
    tenant's row under RLS. The literal `"managed"` it used to return now means
    "invoiced", which every caller reads as a permission: dial on an empty wallet, no
    wallet on the screen, no top-up offered."""
    async with admin_session() as session:
        assert await plan_tier_of(session, uuid.uuid4()) == DEFAULT_PLAN_TIER


# --- the operator's way back ----------------------------------------------------------


async def _operator() -> uuid.UUID:
    admin_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def _audit_actions(tenant_id: uuid.UUID) -> list[str]:
    async with admin_session() as session:
        rows = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE tenant_id = :t ORDER BY created_at"),
                {"t": tenant_id},
            )
        ).all()
    return [str(row[0]) for row in rows]


async def test_an_operator_can_put_a_client_back_on_the_invoiced_motion() -> None:
    """D-521 keeps `managed` so a genuinely invoiced client can be set back to it. Until
    this route existed that was an UPDATE typed into a production database by hand, which
    is not a supported decision — it is an unaudited one.

    Also asserts idempotence: setting the tier an account is already on is a 200 with
    `changed: false` and NO audit row, so the log stays a record of transitions rather
    than of clicks.
    """
    tenant_id = await _tenant()
    admin_id = await _operator()
    headers = {"Authorization": f"Bearer dev:admin:{admin_id}"}
    body = {"plan_tier": "managed", "reason": "invoiced on a retainer from October"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/plan-tier", json=body, headers=headers
        )
        second = await http.post(
            f"/v1/admin/tenants/{tenant_id}/plan-tier", json=body, headers=headers
        )

    assert first.status_code == 200, first.text
    assert first.json() == {
        "tenant_id": str(tenant_id),
        "plan_tier": "managed",
        "previous_plan_tier": "prepaid",
        "changed": True,
    }
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is False
    assert second.json()["previous_plan_tier"] is None

    async with tenant_session(tenant_id) as session:
        assert await plan_tier_of(session, tenant_id) == "managed"
        assert await credits_exhausted(session, tenant_id=tenant_id) is False

    actions = await _audit_actions(tenant_id)
    assert actions.count("tenant.plan_tier_set") == 1, (
        f"expected exactly one transition row, got {actions}"
    )


@pytest.mark.parametrize("tier", ["self_serve", "trial", "enterprise"])
async def test_an_operator_may_not_write_a_signup_tier(tier: str) -> None:
    """`self_serve` and `trial` are not a billing choice — they record that a stranger
    opened the account unattended, and writing one onto an operator-created client would
    refuse that client's next dial with `kyc_missing` for a fact that is not true of them.
    `enterprise` is the control: an unknown tier is refused by the same schema."""
    tenant_id = await _tenant()
    admin_id = await _operator()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/plan-tier",
            json={"plan_tier": tier, "reason": "should not be possible"},
            headers={"Authorization": f"Bearer dev:admin:{admin_id}"},
        )
    assert response.status_code == 422, response.text
    async with tenant_session(tenant_id) as session:
        assert await plan_tier_of(session, tenant_id) == "prepaid"


async def test_the_plan_tier_route_answers_404_for_a_client_that_is_not_there() -> None:
    admin_id = await _operator()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.post(
            f"/v1/admin/tenants/{uuid.uuid4()}/plan-tier",
            json={"plan_tier": "managed", "reason": "nobody is here"},
            headers={"Authorization": f"Bearer dev:admin:{admin_id}"},
        )
    assert response.status_code == 404, response.text
