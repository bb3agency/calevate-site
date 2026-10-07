"""What a client is told about their own trial (D-536), through the client realm.

The client console's trial strip, its credit tile and its billing screen all read the
`trial` block on `GET /v1/billing/wallet`, and the dashboard's spend tile reads the one on
`GET /v1/usage`. Both are built from `billing/trials.read_trial`, the same row the
operator's trial panel writes, so there is no second source to drift. What is pinned here:

* an active trial publishes its end instant and the rounded-up day count, and the gate's
  verdict beside it says an empty wallet stops nothing;
* a trial past its end date reads as over before the nightly sweep has closed it;
* an account that never had a trial gets `null`, not an inactive block;
* one tenant's trial is invisible to another (RLS on `tenant_trials`);
* neither client payload carries what the trial costs Calevate — that figure is the
  operator's (`trial_routes.TrialStatusOut.cost_to_us_inr`) and no client panel shows it;
* the low-balance email does not tell a client on a trial that their calls have stopped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import WALLET_LEVEL_EMPTY
from apps.api.billing.trial_routes import TrialStatusOut
from apps.api.billing.trials import end_trial, start_trial
from apps.api.billing.wallet_routes import WalletTrialOut, read_wallet_summary
from apps.api.core.context import Principal
from apps.api.crm.routes import usage_panel
from apps.api.db.session import tenant_session
from apps.workers.wallet_alerts import notify_low_balance
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = [pytest.mark.rls]


async def _tenant(plan_tier: str = "self_serve") -> UUID:
    created = await admin_service.create_organization(
        name="Raghava Organics",
        slug=f"trialview-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :i"),
            {"tier": plan_tier, "i": tenant_id},
        )
    return tenant_id


def _owner(tenant_id: UUID) -> Principal:
    return Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


async def _open_trial(tenant_id: UUID, *, days: int, at: datetime | None = None) -> datetime:
    async with tenant_session(tenant_id) as session:
        state = await start_trial(
            session, tenant_id=tenant_id, days=days, actor_user_id=None, at=at
        )
    return state.ends_at


async def test_an_active_trial_tells_the_client_until_when_calls_are_on_us() -> None:
    tenant_id = await _tenant()
    ends_at = await _open_trial(tenant_id, days=3)

    out = await read_wallet_summary(_owner(tenant_id))

    assert out.trial is not None
    assert out.trial.active is True
    assert out.trial.status == "active"
    assert out.trial.ends_at == ends_at
    # Rounded UP: a trial opened a moment ago with three days on it has three days left.
    assert out.trial.days_remaining == 3
    # The founder's screenshot: ₹0.00 in the wallet, and the gate says nothing is stopped.
    assert out.balance_inr == Decimal("0.00")
    assert out.outbound_stopped is False
    assert out.minutes_left is None


async def test_a_trial_past_its_end_reads_as_over_before_any_sweep_closes_it() -> None:
    tenant_id = await _tenant()
    await _open_trial(tenant_id, days=1, at=datetime.now(UTC) - timedelta(days=3))

    out = await read_wallet_summary(_owner(tenant_id))

    assert out.trial is not None
    assert out.trial.status == "active", "the nightly sweep has not run in this test"
    assert out.trial.active is False
    assert out.trial.days_remaining is None
    # And the gate agrees: an empty wallet stops calls again the moment the trial ends.
    assert out.outbound_stopped is True


async def test_an_ended_trial_is_published_as_ended_with_its_date() -> None:
    tenant_id = await _tenant()
    await _open_trial(tenant_id, days=7)
    async with tenant_session(tenant_id) as session:
        await end_trial(session, tenant_id=tenant_id, outcome="converted", reason="They bought.")

    out = await read_wallet_summary(_owner(tenant_id))

    assert out.trial is not None
    assert out.trial.active is False
    assert out.trial.status == "converted"
    assert out.trial.ended_at is not None


async def test_an_account_that_never_had_a_trial_gets_null() -> None:
    tenant_id = await _tenant()
    out = await read_wallet_summary(_owner(tenant_id))
    assert out.trial is None


async def test_one_client_never_sees_another_clients_trial() -> None:
    on_trial = await _tenant()
    neighbour = await _tenant()
    await _open_trial(on_trial, days=14)

    assert (await read_wallet_summary(_owner(neighbour))).trial is None
    async with tenant_session(neighbour) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM tenant_trials WHERE tenant_id = :t"),
                {"t": on_trial},
            )
        ).scalar()
    assert rows == 0, "RLS must hide another tenant's trial row"


async def test_no_client_payload_carries_what_the_trial_costs_us() -> None:
    tenant_id = await _tenant()
    await _open_trial(tenant_id, days=3)

    wallet = await read_wallet_summary(_owner(tenant_id))
    async with tenant_session(tenant_id) as session:
        usage = await usage_panel(session=session, month=None, principal=_owner(tenant_id))

    # The client's trial block is exactly dates and a count.
    assert set(WalletTrialOut.model_fields) == {
        "active",
        "status",
        "days",
        "started_at",
        "ends_at",
        "days_remaining",
        "ended_at",
    }
    # The operator's read DOES carry the figure, so the absence below is a choice and not
    # an accident of naming.
    assert "cost_to_us_inr" in TrialStatusOut.model_fields
    for payload in (wallet.model_dump_json(), usage.model_dump_json()):
        assert "cost_to_us" not in payload
        assert "unit_cost" not in payload
    assert usage.trial.active is True
    assert usage.month_charges_inr == "0.00"


async def test_the_low_balance_mail_is_not_sent_while_a_trial_runs() -> None:
    """The empty-wallet mail opens "your calls have stopped". During a trial an empty
    wallet stops nothing, so the mail would be false; the job returns before composing it."""
    tenant_id = await _tenant()
    await _open_trial(tenant_id, days=3)

    outcome = await notify_low_balance(
        {"job_try": 1},
        {"tenant_id": str(tenant_id), "level": WALLET_LEVEL_EMPTY, "balance_inr": "0.00"},
    )

    assert outcome == "trial_active"
