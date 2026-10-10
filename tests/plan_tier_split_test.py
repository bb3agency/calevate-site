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


async def test_the_dial_gate_refuses_an_inbound_agent_for_its_direction_not_its_wallet() -> None:
    """⚠ **THIS USED TO BE NAMED "an inbound-only agent still answers at a zero balance",
    AND D-551 (8 Sep 2026) WITHDREW THAT CLAIM.** It is not the claim this test ever
    proved, which is why the rename is the whole correction: the assertion below is about
    the ORDER of `check_dispatch`, and that order is unchanged.

    What the gate says, still: an inbound-only agent is refused with `agent_inbound_only`
    BEFORE any money is read, and no inbound path calls the gate at all. So a wallet-empty
    prepaid tenant is refused for the DIRECTION and never for the balance — which is what
    would break the day somebody moved the credit check up the ladder.

    What that no longer implies: that the phone is answered. Since D-551 the enforcement
    of an empty wallet on the inbound leg is not this gate at all — it is durable state at
    the engine, applied on the ledger's crossing of zero
    (`agents.service.reconcile_inbound_answering`, `tests/inbound_credit_cutover_test.py`),
    so a clinic at ₹0 is refused here for its direction AND is not answering its phone.
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


# --- D-707: no way back to the invoiced motion ---------------------------------------


def test_the_plan_tier_route_is_gone_and_no_production_caller_writes_a_retired_tier() -> None:
    """D-707: one pricing model. The route that put a client on the invoiced motion is
    deleted, signup's tier type admits only its own two tiers, and the operator wizard
    passes no tier at all — so nothing in production can write `managed`."""
    from typing import get_args

    from apps.api.tenancy.models import RETIRED_PLAN_TIERS
    from apps.api.tenancy.signup import SelfServeTier

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/v1/admin/tenants/{tenant_id}/plan-tier" not in paths
    assert not set(get_args(SelfServeTier)) & set(RETIRED_PLAN_TIERS)
    wizard = (REPO_ROOT / "apps" / "api" / "admin" / "routes.py").read_text(encoding="utf-8")
    assert "plan_tier=" not in wizard.split("service.create_organization(", 1)[1].split(")", 1)[0]
