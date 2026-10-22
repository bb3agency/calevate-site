"""The client health overview — the board that says WHICH account breaks this week.

    GET /v1/admin/client-health   (apps/api/admin/health.py)

The board is a judgement, not a counter, and a judgement that is wrong is worse than no
board: an operator who phones a four-day-old account to ask why its calls stopped, or who
is told an account is fine while the client stares at a refusal, stops trusting the screen
and goes back to opening N dashboards. So these tests pin the properties that make the
judgement trustworthy rather than the arithmetic that produces it.

1. **A trend is only reported on a basis that earns it.** `calls_basis` is the
   `after_hours_basis` precedent applied to an accusation: a new account and an account
   with four calls last week both produce a small number, and neither is a collapse. The
   signal must be ABSENT, and the basis must say which of the two it is.
2. **The signals are the GATES, not a copy of them.** The outbound signals compose
   `campaigns.service.account_outbound_blockers` (the account half of the launch screen)
   or, for a free-trial account, `compliance.service.account_dial_blockers` (what a test
   call meets), so the board cannot disagree with the refusal. Pinned by asserting the
   rule NAMES those gates use. Who clears each one decides the signal: ours is broken now,
   the client's is waiting on the client, and a trial's test-calls-only limit is a state.
3. **Hard rule 1.** A cross-tenant read from the admin realm that widens nothing: the
   `app.admin` session still cannot see a call, a delivery or a knowledge source, and a
   client-realm session still sees zero rows of another tenant.
4. **Hard rule 6.** Accounts and rule names, never a person: no phone number, no
   transcript, no reviewer prose, and the response body is asserted whole.
5. **D-22.** It is a read, so it is readable with a read permission — and the realm, not
   the permission, is what keeps a client token out.

Run: uv run pytest -q tests/client_health_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin.health import (
    TREND_BASELINE_MIN,
    WINDOW_DAYS,
    Account,
    CallVolume,
    ClientHealth,
    HealthSignal,
    _triage_order,
    cause_owner,
    tenant_health,
)
from apps.api.billing.service import current_billing_month
from apps.api.billing.trials import start_trial
from apps.api.core.rbac import MUTATING_PERMISSIONS, iter_api_routes
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import _owner_of, accept_agreements, create_org_with_receptionist, fund_wallet

pytestmark = [pytest.mark.rls]

BOARD_PATH = "/v1/admin/client-health"

# An account old enough that a week-on-week comparison is entitled to be made. The
# fixtures set `organizations.created_at` back rather than sleeping.
AGED = timedelta(days=WINDOW_DAYS * 4)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
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


async def _make_member(tenant_id: uuid.UUID) -> str:
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
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return f"dev:client:{user_id}"


async def _account(
    *,
    aged: bool = True,
    plan_tier: str = "managed",
    agreements: bool = True,
    kyc_and_pledge: bool = False,
) -> Account:
    """A client, optionally old enough for a week-on-week comparison to be legitimate.

    `agreements=False` leaves the four blocking agreements unaccepted, the state of a client
    that has not yet re-accepted a materially changed document."""
    created = await create_org_with_receptionist(
        name=f"Health Motors {uuid.uuid4().hex[:6]}",
        slug=f"health-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    if agreements:
        await accept_agreements(uuid.UUID(str(created["id"])), kyc_and_pledge=kyc_and_pledge)
    tenant_id = uuid.UUID(str(created["id"]))
    created_at = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        # Inside the tenant's own session: `organizations` is RLS'd on `app.tenant_id`,
        # so an untenanted UPDATE matches zero rows silently.
        if aged:
            created_at = datetime.now(UTC) - AGED
            await session.execute(
                text("UPDATE organizations SET created_at = :at WHERE id = :tid"),
                {"at": created_at, "tid": tenant_id},
            )
        if plan_tier != "managed":
            await session.execute(
                text("UPDATE organizations SET plan_tier = :tier WHERE id = :tid"),
                {"tier": plan_tier, "tid": tenant_id},
            )
    return Account(
        tenant_id=tenant_id,
        name=str(created["slug"]),
        slug=str(created["slug"]),
        plan_tier=plan_tier,
        status="onboarding",
        created_at=created_at,
    )


async def _agent_id(account: Account) -> uuid.UUID:
    async with tenant_session(account.tenant_id) as session:
        found = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
    return uuid.UUID(str(found))


async def _calls(account: Account, *, count: int, days_ago: int) -> None:
    agent_id = await _agent_id(account)
    async with tenant_session(account.tenant_id) as session:
        for _ in range(count):
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, started_at, created_at, updated_at) VALUES (:i, :t, :a, "
                    ":e, 'inbound', '+919876500001', 'completed', :at, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": account.tenant_id,
                    "a": agent_id,
                    "e": f"health_{uuid.uuid4().hex[:12]}",
                    "at": datetime.now(UTC) - timedelta(days=days_ago),
                },
            )


async def _make_outbound(account: Account) -> None:
    """Give the account a reason to care about outbound at all (`_dials_out`)."""
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'both' WHERE tenant_id = :tid"),
            {"tid": account.tenant_id},
        )


async def _start_trial(account: Account, *, pledged: bool = True) -> None:
    """Put the account on an unpaid free trial (D-697), with the no-cold-calls pledge a
    test call needs accepted unless `pledged=False`."""
    from apps.api.compliance.outbound_pledge import (
        PLEDGE_TEXT_SHA256,
        PLEDGE_VERSION,
        accept_pledge,
    )

    async with tenant_session(account.tenant_id) as session:
        await start_trial(
            session, tenant_id=account.tenant_id, days=14, actor_user_id=None, free_minutes=30
        )
    if pledged:
        user_id = await _owner_of(account.tenant_id)
        async with tenant_session(account.tenant_id) as session:
            await accept_pledge(
                session,
                tenant_id=account.tenant_id,
                user_id=user_id,
                version=PLEDGE_VERSION,
                text_sha256=PLEDGE_TEXT_SHA256,
                ip=None,
            )


async def _kb_pending(account: Account, name: str = "Opening hours") -> None:
    """A knowledge source the client submitted and nobody here has approved."""
    agent_id = await _agent_id(account)
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, 'text', :n, 'pending_approval', "
                "now(), now())"
            ),
            {"i": uuid7(), "t": account.tenant_id, "a": agent_id, "n": name},
        )


async def _failed_delivery(account: Account) -> None:
    """One outbound delivery that did not arrive.

    Scoped through `outbound_webhooks` because `webhook_deliveries` has no RLS policy of
    its own by design (migration 4be32bf3d12c) — the endpoint is what makes a delivery a
    tenant's, which is exactly the join the board reads it through.
    """
    async with tenant_session(account.tenant_id) as session:
        endpoint_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, events, active, "
                "created_at, updated_at) VALUES (:i, :t, 'webhook', 'https://example.test/h', "
                "ARRAY['lead.created'], true, now(), now())"
            ),
            {"i": endpoint_id, "t": account.tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO webhook_deliveries (id, endpoint_id, direction, event_type, "
                "status, attempts, first_at, last_at, created_at) VALUES (:i, :e, 'out', "
                "'lead.created', 'failed', 3, now(), now(), now())"
            ),
            {"i": uuid7(), "e": endpoint_id},
        )


async def _judge(account: Account, *, now: datetime | None = None) -> ClientHealth | None:
    async with tenant_session(account.tenant_id) as session:
        return await tenant_health(session, account=account, now=now)


def _signal(row: ClientHealth | None, rule: str) -> Any:
    assert row is not None, f"expected a row carrying {rule}"
    return next((signal for signal in row.signals if signal.rule == rule), None)


def _rules(row: ClientHealth | None) -> set[str]:
    return {signal.rule for signal in row.signals} if row is not None else set()


# ------------------------------------------------- the honesty rule: an earned basis


async def test_a_brand_new_account_says_it_is_too_new_rather_than_short_of_calls() -> None:
    """The failure this board would otherwise ship with, and the ONE assertion that
    catches it.

    An account that signed up on Thursday has no previous week, so a naive ratio reads its
    zero-against-zero as a collapse and sends an operator to ask a four-day-old client why
    their calls stopped. Suppressing the SIGNAL is not enough and asserting only its
    absence is a test that passes vacuously — a young account has few prior calls too, so
    the `no_baseline` floor would hide a broken age guard. What the age guard actually
    owns is the SENTENCE: this account has not had time to trade, which is a different
    thing from having traded and barely, and an operator told the wrong one waits for a
    baseline that either has already arrived or cannot yet.

    So the account is put ON the board for an unrelated reason (a failed delivery) and the
    basis is asserted directly. Removing the age check turns `too_new` into `no_baseline`
    and this fails.
    """
    account = await _account(aged=False)
    await _failed_delivery(account)

    row = await _judge(account)
    assert row is not None, "a failed delivery puts even a brand-new account on the board"
    assert row.volume.basis == "too_new", (
        "a four-day-old account has no previous week; saying it is short of calls sends "
        "the operator to the wrong conclusion"
    )
    assert "calls_stopped" not in _rules(row), "and it is never accused of a collapse"


async def test_an_account_with_no_baseline_is_a_different_unknown_from_a_new_one() -> None:
    """`no_baseline` and `too_new` are separate facts with separate next actions.

    A client that traded four calls last week HAS traded — waiting for a baseline that
    has already passed is the wrong conclusion, and so is calling it a collapse.

    Put on the board by a failed delivery for the reason the test above is: `row is None or
    …` would pass without the basis ever being computed, which is a test that asserts
    nothing on the day the code breaks.
    """
    account = await _account()
    await _calls(account, count=TREND_BASELINE_MIN - 1, days_ago=WINDOW_DAYS + 2)
    await _failed_delivery(account)
    row = await _judge(account)

    assert row is not None
    assert row.volume.basis == "no_baseline", "it traded; it is not too new"
    assert "calls_stopped" not in _rules(row)


async def test_a_real_collapse_on_a_real_baseline_is_a_stop() -> None:
    """The signal doing its job: a week of traffic, then silence."""
    account = await _account()
    await _calls(account, count=TREND_BASELINE_MIN + 5, days_ago=WINDOW_DAYS + 2)
    row = await _judge(account)

    signal = _signal(row, "calls_stopped")
    assert signal is not None, "a baseline week followed by silence is the churn signal"
    assert signal.severity == "stop"
    assert row is not None and row.volume.basis == "measured"
    assert row.volume.calls_7d == 0
    assert row.volume.calls_prev_7d == TREND_BASELINE_MIN + 5


async def test_a_steady_account_carries_no_trend_signal() -> None:
    """The other half of the same claim: a client that kept trading is not on the board
    for trading. A signal that fires on a healthy account is a signal operators learn to
    scroll past."""
    account = await _account()
    await _calls(account, count=TREND_BASELINE_MIN + 5, days_ago=WINDOW_DAYS + 2)
    await _calls(account, count=TREND_BASELINE_MIN + 5, days_ago=1)
    row = await _judge(account)

    assert "calls_stopped" not in _rules(row)


# --------------------------------------------- the signals ARE the gates, not a copy


async def test_outbound_signals_name_the_gates_own_rules() -> None:
    """The board composes the predicates that refuse the dial.

    A fresh account with an outbound-capable agent has no verified KYC and no accepted
    no-cold-calls pledge, which is what `campaigns.service.launch_blockers` refuses its
    launch with since D-692. The board must use THOSE names, in that order — an operator
    and a client on the phone have to be naming one condition identically — and must not
    name the retired DLT entity chain, which the founder saw on this panel after D-692.
    Both are the client's to clear, so they wait on the client and are not broken.
    """
    from apps.api.campaigns.service import account_outbound_blockers

    account = await _account()
    await _make_outbound(account)
    async with tenant_session(account.tenant_id) as session:
        row = await tenant_health(session, account=account)
        launch = [
            rule
            for rule, _ in await account_outbound_blockers(session, tenant_id=account.tenant_id)
        ]

    signal = _signal(row, "outbound_waiting_on_client")
    assert signal is not None
    assert (signal.severity, signal.waiting_on) == ("warn", "client")
    assert list(signal.causes) == [rule for rule in launch if cause_owner(rule) == "client"]
    assert "kyc_missing" in signal.causes
    assert "outbound_pledge_missing" in signal.causes
    assert _signal(row, "outbound_blocked") is None, "nothing here is ours to fix"
    assert row is not None and row.severity == "warn"
    every_cause = [cause for each in row.signals for cause in each.causes]
    retired = {"pe_registration_missing", "pe_registration_not_active", "tm_link_not_active"}
    assert retired.isdisjoint(every_cause)


async def test_a_self_serve_account_carries_the_holds_from_one_predicate() -> None:
    """`read_tenant_holds` is the hold queue's predicate and the directory's flag; the
    board is its THIRD caller and must not become a third definition."""
    from apps.api.admin.holds import read_tenant_holds

    account = await _account(plan_tier="self_serve")
    await _make_outbound(account)

    async with tenant_session(account.tenant_id) as session:
        holds = await read_tenant_holds(session, tenant_id=account.tenant_id)
        row = await tenant_health(session, account=account)

    assert row is not None
    causes = {cause for signal in row.signals for cause in signal.causes}
    assert set(holds.rules) <= causes, (
        "every gate holding this account must appear as a cause, from the same predicate"
    )
    waiting = _signal(row, "outbound_waiting_on_client")
    assert waiting is not None and "kyc_missing" in waiting.causes


async def test_an_inbound_only_account_is_not_told_its_outbound_is_broken() -> None:
    """The clinic that only answers the phone bought no outbound capability. Reporting
    its missing DLT paperwork as a live problem would be a red row about a thing that is
    not broken — and a board full of those is a board nobody reads."""
    account = await _account()
    # The default agent from the wizard is `inbound`, and no campaign exists.
    row = await _judge(account)

    assert "outbound_blocked" not in _rules(row)


# ------------------------------------------- a trial is a state; whose move it is decides


async def test_a_trial_account_placing_test_calls_is_not_broken() -> None:
    """The false alarm of 11 Oct 2026: a trial account whose test calls were completing
    showed "Broken now: Cannot dial out", because it was judged by the campaign launch
    screen, which refuses every trial campaign by design (D-697).

    The board now asks what the test call itself is asked, and the test call is allowed, so
    nothing is wrong with the account. The launch screen still refuses its campaigns: the
    gate did not move, only the question the board asks.
    """
    from apps.api.campaigns.service import account_outbound_blockers
    from apps.api.compliance.service import account_dial_blockers

    account = await _account()
    await _make_outbound(account)
    await _start_trial(account)

    async with tenant_session(account.tenant_id) as session:
        test_call = await account_dial_blockers(
            session, tenant_id=account.tenant_id, trial_call=True
        )
        launch = [
            rule
            for rule, _ in await account_outbound_blockers(session, tenant_id=account.tenant_id)
        ]
        row = await tenant_health(session, account=account)

    assert test_call == [], "the dial gate lets this account's test calls through"
    assert "trial_campaigns_unavailable" in launch, "campaigns are still refused on a trial"
    assert row is None, "an account doing what its trial allows is not on the board"

    token = await _make_admin()
    async with _client() as http:
        response = await http.get(
            f"{BOARD_PATH}/{account.tenant_id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["severity"], body["signals"], body["on_trial"]) == (None, [], True)


async def test_a_trial_waiting_on_its_agreements_is_waiting_on_the_client() -> None:
    """Outstanding agreements DO refuse a test call (`check_dispatch` asks them on every
    dial), so the board reports them, as the client's step and in the gate's own words, and
    never as broken."""
    from apps.api.compliance.service import account_dial_blockers

    account = await _account(agreements=False)
    await _make_outbound(account)
    await _start_trial(account)

    async with tenant_session(account.tenant_id) as session:
        test_call = [
            rule
            for rule, _ in await account_dial_blockers(
                session, tenant_id=account.tenant_id, trial_call=True
            )
        ]
        row = await tenant_health(session, account=account)

    assert "agreements_not_accepted" in test_call
    assert row is not None and row.on_trial
    waiting = _signal(row, "outbound_waiting_on_client")
    assert waiting is not None
    assert (waiting.severity, waiting.waiting_on) == ("warn", "client")
    assert list(waiting.causes) == test_call
    assert "outbound_blocked" not in _rules(row)
    assert row.severity == "warn", "waiting on the client is never broken now"


async def test_a_refusal_only_we_can_clear_is_broken_now() -> None:
    """The signal that keeps its red: a verified, pledged, agreed account whose spend cap
    has bitten is refused every dial until somebody raises the ceiling."""
    account = await _account(kyc_and_pledge=True)
    await _make_outbound(account)
    await fund_wallet(account.tenant_id)
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:t, :m, 0, 0, 0, true, now(), now())"
            ),
            {"t": account.tenant_id, "m": current_billing_month()},
        )

    row = await _judge(account)
    signal = _signal(row, "outbound_blocked")
    assert signal is not None
    assert (signal.severity, signal.waiting_on, tuple(signal.causes)) == (
        "stop",
        "calevate",
        ("spend_cap",),
    )
    assert "outbound_waiting_on_client" not in _rules(row)
    assert row is not None and row.severity == "stop" and not row.on_trial


def test_who_clears_each_cause() -> None:
    """States are no signal, the client's steps wait on the client, and a rule nobody has
    classified counts as ours, so a new gate shows up red rather than vanishing."""
    assert cause_owner("trial_campaigns_unavailable") is None
    assert cause_owner("trial_daily_cap") is None
    assert cause_owner("agreements_not_accepted") == "client"
    assert cause_owner("trial_ended") == "client"
    assert cause_owner("kyc_not_verified") == "calevate"
    assert cause_owner("a_gate_added_tomorrow") == "calevate"


def test_waiting_on_the_client_ranks_below_what_will_break() -> None:
    volume = CallVolume(calls_7d=0, calls_prev_7d=0, basis="no_baseline", last_call_at=None)

    def row(name: str, *signals: HealthSignal) -> ClientHealth:
        return ClientHealth(
            tenant_id=uuid.uuid4(),
            name=name,
            slug=name,
            plan_tier="prepaid",
            status="active",
            severity="warn",
            signals=signals,
            volume=volume,
            on_trial=False,
            spend_used_inr=Decimal(0),
            spend_cap_inr=None,
        )

    waiting = row(
        "a-waiting",
        HealthSignal(rule="outbound_waiting_on_client", severity="warn", waiting_on="client"),
    )
    warned = row("b-warned", HealthSignal(rule="knowledge_waiting", severity="warn", count=1))
    assert sorted([waiting, warned], key=_triage_order) == [warned, waiting]


# --------------------------------------------------------------- the other signals


async def test_a_failed_delivery_puts_the_account_on_the_board() -> None:
    """Leads not reaching the client's own system is the failure they read as "the
    product stopped working", and it was visible only on their own screen."""
    account = await _account()
    await _failed_delivery(account)

    signal = _signal(await _judge(account), "deliveries_failing")
    assert signal is not None
    assert (signal.severity, signal.count) == ("stop", 1)


async def test_knowledge_waiting_on_us_is_ours_to_see() -> None:
    """`crm/attention.py` deliberately keeps `pending_approval` off the CLIENT's queue
    ("waiting for us is not the client's to-do"), which makes the operator console the
    only correct home for it — and it had none."""
    account = await _account()
    await _kb_pending(account)

    signal = _signal(await _judge(account), "knowledge_waiting")
    assert signal is not None
    assert (signal.severity, signal.count) == ("warn", 1)


async def test_a_cap_about_to_bite_warns_and_a_cap_that_has_bitten_does_not() -> None:
    """The forward-looking signal, and the reason it stops when the cap arrives: having
    ARRIVED is `outbound_blocked`'s `spend_cap` cause, and one fact must not wear two
    rows."""
    account = await _account()
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, hard_cap_spend, created_at, updated_at) "
                "VALUES (:i, :t, 1000, now(), now())"
            ),
            {"i": uuid7(), "t": account.tenant_id},
        )
        await session.execute(
            text(
                # `billed_inr` is the column the cap and this panel now read (P1.3);
                # `spend_used` is our supplier cost and stays the margin panel's.
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:t, :m, 0, 900, 900, false, now(), now())"
            ),
            {"t": account.tenant_id, "m": current_billing_month()},
        )

    signal = _signal(await _judge(account), "spend_cap_near")
    assert signal is not None
    assert (signal.severity, signal.count) == ("warn", 90)

    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text("UPDATE spend_state SET capped = true WHERE tenant_id = :t"),
            {"t": account.tenant_id},
        )
    assert "spend_cap_near" not in _rules(await _judge(account)), (
        "a cap that has already bitten is reported once, as a blocker, not twice"
    )


async def test_money_stays_numeric_in_the_service_and_becomes_a_string_on_the_wire() -> None:
    """Hard rule 7 on both sides of the boundary. `Number()` on INR is how ₹10,159.00
    becomes ₹10,158.999999999998 (`UsagePanelOut`), so the wire value is a string — and
    the service value is a Decimal, never a float that was rounded on the way here."""
    from apps.api.admin.health_routes import _out

    account = await _account()
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, hard_cap_spend, created_at, updated_at) "
                "VALUES (:i, :t, 1000, now(), now())"
            ),
            {"i": uuid7(), "t": account.tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:t, :m, 0, 900.5000, 900.5000, false, now(), now())"
            ),
            {"t": account.tenant_id, "m": current_billing_month()},
        )

    row = await _judge(account)
    assert row is not None
    assert isinstance(row.spend_used_inr, Decimal)
    assert row.spend_used_inr == Decimal("900.5000")

    wire = _out(row)
    # PAISE on the wire, storage precision in the row. The ledger keeps NUMERIC(12,4);
    # `_out` quantizes because `formatINR` truncates — see the next test for the value
    # where the two answers differ.
    assert isinstance(wire.spend_used_inr, str) and wire.spend_used_inr == "900.50"
    assert wire.spend_cap_inr == "1000.00"


async def test_the_operators_spend_line_and_the_clients_agree_to_the_paisa() -> None:
    """The same defect D-375 fixed on the client's wallet, on the operator's screen.

    `spend_state.billed_inr` is NUMERIC(12,4) and four decimals is what it ORDINARILY
    holds — a prepaid call is debited `rates.prepaid_billed_inr`, quantized at `MONEY_Q`,
    so any `self_serve_inr_per_min` that is not a divisor of 60 produces one on the first
    call (95 seconds at ₹6.50/min is ₹10.2917). This screen stringified that figure raw
    while `billing/cap_routes.py` — the CLIENT's view of the very same row — already sent
    it through `to_paise`.

    The two ends round in OPPOSITE directions, which is what turns a formatting
    inconsistency into a disagreement: `to_paise` is ROUND_HALF_UP (`billing.rates
    .ROUNDING`, the repo's one mode, chosen because it is what an Indian tax invoice is
    checked against) and `apps/web`'s `formatINR` TRUNCATES the fraction to two digits —
    deliberately, because it formats digits without ever parsing them (hard rule 7's
    frontend shadow). So ₹489.7050 read ₹489.70 to the operator and ₹489.71 to the
    client, off one row, in one instant, on the line an operator quotes while deciding
    whether to raise a ceiling.

    ₹489.7050 rather than a round figure for the reason `money_walk_test` states about
    every fixture in this repo: a rounding defect cannot show itself against round
    numbers, and the assertion this replaces pinned ₹900.5000, which quantizes to itself.
    """
    from apps.api.admin.health_routes import _out
    from apps.api.billing.service import to_paise

    account = await _account()
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, hard_cap_spend, created_at, updated_at) "
                "VALUES (:i, :t, 500, now(), now())"
            ),
            {"i": uuid7(), "t": account.tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:t, :m, 0, 489.7050, 489.7050, false, now(), now())"
            ),
            {"t": account.tenant_id, "m": current_billing_month()},
        )

    row = await _judge(account)
    assert row is not None
    assert row.spend_used_inr == Decimal("489.7050"), (
        "the LEDGER keeps its full precision — only the wire is quantized"
    )

    wire = _out(row)
    assert wire.spend_used_inr == str(to_paise(row.spend_used_inr)) == "489.71", (
        "the operator's spend line must be the same paisa the client's own cap screen "
        "shows; publishing the storage precision hands it to a formatter that truncates"
    )


async def test_a_healthy_account_is_absent_rather_than_green() -> None:
    """The board is an EXCEPTION report; the roster is `GET /v1/admin/tenants`. An
    account with nothing wrong produces no row at all — which is what stops this becoming
    a second client directory."""
    account = await _account()
    await _calls(account, count=TREND_BASELINE_MIN + 5, days_ago=WINDOW_DAYS + 2)
    await _calls(account, count=TREND_BASELINE_MIN + 5, days_ago=1)

    assert await _judge(account) is None


# ------------------------------------------------------------------- hard rule 1


async def test_the_admin_guc_cannot_read_a_single_fact_the_board_reports() -> None:
    """The claim the whole design rests on: nothing was widened.

    Every signal is read inside the tenant's own session, so `app.admin` still opens
    exactly what migration b57e2f9c4a13 said it opens — the directory — and a future
    query on an admin session cannot drift into reading a call or a knowledge source
    because the policy never let it.
    """
    account = await _account()
    await _calls(account, count=3, days_ago=1)
    await _kb_pending(account, "Hours")

    async with admin_session() as session:
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
        sources = (await session.execute(text("SELECT count(*) FROM kb_sources"))).scalar()
        endpoints = (await session.execute(text("SELECT count(*) FROM outbound_webhooks"))).scalar()
        orgs = (await session.execute(text("SELECT count(*) FROM organizations"))).scalar()

    assert orgs and orgs >= 1, "the directory is what app.admin is for"
    assert calls == 0, "app.admin must NOT unlock calls"
    assert sources == 0, "app.admin must NOT unlock knowledge sources"
    assert endpoints == 0, "app.admin must NOT unlock delivery endpoints"


async def test_the_judgement_of_another_tenant_sees_zero_rows_of_it() -> None:
    """Cross-tenant zero rows, asserted through the board's OWN entry point.

    Tenant B's session judging tenant A's account must find nothing of A's — not A's
    calls, not A's knowledge queue. The GUC is the isolation, and this proves the board
    inherits it rather than routing around it with a `tenant_id` predicate.
    """
    noisy = await _account()
    quiet = await _account()
    await _calls(noisy, count=TREND_BASELINE_MIN + 5, days_ago=WINDOW_DAYS + 2)
    await _kb_pending(noisy, "Hours")

    # Judge the NOISY account's directory row inside the QUIET tenant's session: the
    # policy, not the predicate, decides what is visible.
    async with tenant_session(quiet.tenant_id) as session:
        leaked = await tenant_health(session, account=noisy)

    assert "calls_stopped" not in _rules(leaked), "tenant B cannot see tenant A's calls"
    assert "knowledge_waiting" not in _rules(leaked), "nor tenant A's knowledge queue"


# ------------------------------------------------------------- hard rule 6 and D-22


async def test_the_board_carries_accounts_and_rule_names_and_nothing_about_a_person() -> None:
    """Asserted against the WHOLE response body, not a field list.

    Everything identifying stays one click away on the account's own screen, behind the
    permission that opens it. A triage list is the widest-read surface in the console and
    has no reason to hold the narrowest data.
    """
    account = await _account()
    await _make_outbound(account)
    await _calls(account, count=3, days_ago=1)

    token = await _make_admin()
    async with _client() as http:
        response = await http.get(BOARD_PATH, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text

    row = next((r for r in response.json() if r["tenant_id"] == str(account.tenant_id)), None)
    assert row is not None, "an account blocked from dialling belongs on the board"
    assert set(row) == {
        "tenant_id",
        "name",
        "slug",
        "plan_tier",
        "status",
        "severity",
        "signals",
        "calls_7d",
        "calls_prev_7d",
        "calls_basis",
        "last_call_at",
        "on_trial",
        "spend_used_inr",
        "spend_cap_inr",
    }
    for signal in row["signals"]:
        assert set(signal) == {"rule", "severity", "causes", "count", "waiting_on"}
    # `+919876500001` is on every call this fixture wrote. No board row may carry it.
    assert "9876500001" not in response.text
    assert isinstance(row["spend_used_inr"], str), "money is a string on the wire"


async def test_the_board_is_readable_with_a_read_permission() -> None:
    """D-22: no GET may require a permission a view-as session is refused.

    `tests/impersonation_reads_test.py` asserts the rule over the whole route table; this
    pins it for the board by name, because "the ops list of clients in trouble" is exactly
    the surface that gets reflexively gated on `admin:tenants`.
    """
    declared = {
        route.path: (route.openapi_extra or {}).get("x-calevate-permission")
        for route in iter_api_routes(app)
    }
    assert BOARD_PATH in declared, f"{BOARD_PATH} is not mounted"
    assert declared[BOARD_PATH] == "org:read"
    assert declared[BOARD_PATH] not in MUTATING_PERMISSIONS


async def test_the_board_refuses_a_client_realm_token_even_with_the_permission() -> None:
    """`org:read` is held by client roles too, so the REALM is what separates the two
    surfaces — and a client reading a list that names other businesses would be a
    cross-tenant disclosure with a valid token behind it."""
    account = await _account()
    token = await _make_member(account.tenant_id)
    async with _client() as http:
        response = await http.get(
            BOARD_PATH,
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": account.slug},
        )
    assert response.status_code in (401, 403), response.text


# ============================================================================
# One client's health: GET /v1/admin/client-health/{tenant_id}
# ============================================================================


async def test_one_clients_health_is_the_boards_judgement_for_that_client() -> None:
    """The per-client read is the same function the board calls, so the two cannot
    disagree about one account; it answers the healthy case instead of omitting it."""
    account = await _account(aged=False)
    await _kb_pending(account)
    token = await _make_admin()

    async with _client() as http:
        response = await http.get(
            f"{BOARD_PATH}/{account.tenant_id}", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    judged = await _judge(account)
    assert judged is not None
    assert body["severity"] == judged.severity
    assert sorted(signal["rule"] for signal in body["signals"]) == sorted(_rules(judged))
    assert "knowledge_waiting" in [signal["rule"] for signal in body["signals"]]


async def test_a_healthy_client_is_answered_not_omitted() -> None:
    account = await _account(aged=False)
    token = await _make_admin()
    judged = await _judge(account)

    async with _client() as http:
        response = await http.get(
            f"{BOARD_PATH}/{account.tenant_id}", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    if judged is None:
        assert body["severity"] is None and body["signals"] == []
    else:  # pragma: no cover — a fresh account carries no signal today
        assert body["severity"] == judged.severity


async def test_one_clients_health_names_no_one_else_and_refuses_unknown_and_client_tokens() -> None:
    account = await _account(aged=False)
    admin = await _make_admin()
    member = await _make_member(account.tenant_id)

    async with _client() as http:
        missing = await http.get(
            f"{BOARD_PATH}/{uuid.uuid4()}", headers={"Authorization": f"Bearer {admin}"}
        )
        as_client = await http.get(
            f"{BOARD_PATH}/{account.tenant_id}", headers={"Authorization": f"Bearer {member}"}
        )

    assert missing.status_code == 404, missing.text
    assert as_client.status_code in (401, 403), "a client token cannot read the operator's view"
