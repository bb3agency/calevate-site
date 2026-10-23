"""A free trial is outbound test calls from one shared number; the first payment unlocks the
rest (D-697).

Vendor shapes from `thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/`:
`PATCH /phone-numbers/{number}` takes `agent` (null makes nothing answer it) and
`callingAgent` (`phone-numbers/update-phone-number.md:451-470`); `POST /calls` takes `from`
(one of the agent's numbers, its own or lent) and `overrides.maxCallSeconds`, 60..1200
(`calls/place-call.md:971-977,1103-1126`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.agents import lifecycle as agent_lifecycle
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.agents.service import TrialDial, publish_agent
from apps.api.billing.first_payment import has_paid, on_payment_credited
from apps.api.billing.service import record_entry
from apps.api.billing.trials import read_trial, start_trial
from apps.api.campaigns import engine_numbers
from apps.api.campaigns.engine_number_purchase import purchase_readiness
from apps.api.compliance import service as compliance_service
from apps.api.compliance.kyc_routes import _kyc_writer
from apps.api.compliance.outbound_pledge import PLEDGE_TEXT_SHA256, PLEDGE_VERSION, accept_pledge
from apps.api.compliance.service import check_dispatch
from apps.api.compliance.trial_access import (
    TRIAL_REFUSALS,
    ist_day_start,
    read_trial_access,
    restricting_trial,
    trial_blocker,
)
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.engine.thinnest_numbers import ThinnestNumbers, set_thinnest_numbers
from apps.api.engine.thinnest_workspace import (
    trial_agent_in_developer_workspace,
    workspace_headers,
)
from apps.workers import engine_workspaces
from apps.workers import trials as trial_sweep
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.conftest import _owner_of, accept_agreements, create_org_with_receptionist, fund_wallet

pytestmark = pytest.mark.asyncio

TRIAL_NUMBER = "+918045678901"


async def _trial_tenant(
    *, minutes: int | None = 30, pledged: bool = True, direction: str = "outbound"
) -> tuple[uuid.UUID, uuid.UUID]:
    """An unpaid account on a trial, with one published agent. KYC is NOT verified: a test
    call must not need it."""
    created = await create_org_with_receptionist(
        name="Trial Tea House",
        slug=f"tt-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        agent_id = await agent_lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Test caller",
            direction=direction,
            language_primary="te-IN",
        )
        await session.commit()
    # No KYC and no pledge: a test call must not need KYC, and the pledge is the test's.
    await accept_agreements(tenant_id, kyc_and_pledge=False)
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Trial Tea House.\n",
            notes=None,
            created_by=None,
        )
        await start_trial(
            session, tenant_id=tenant_id, days=14, actor_user_id=None, free_minutes=minutes
        )
    if direction != "inbound":
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    if pledged:
        user_id = await _owner_of(tenant_id)
        async with tenant_session(tenant_id) as session:
            await accept_pledge(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                version=PLEDGE_VERSION,
                text_sha256=PLEDGE_TEXT_SHA256,
                ip=None,
            )
    return tenant_id, agent_id


@pytest.fixture
def open_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda *a, **k: True)


async def _trial_call_row(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, status: str, seconds: int | None = None
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "trial_call, status, duration_s, created_at, updated_at) VALUES (:id, :tid, "
                ":aid, :ecid, 'outbound', '+919876543210', true, :status, :secs, now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"out_{uuid.uuid4().hex}",
                "status": status,
                "secs": seconds,
            },
        )


# --- who is a trial account --------------------------------------------------------


async def test_an_unpaid_trial_account_is_restricted_and_a_paid_one_is_not() -> None:
    tenant_id, _ = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        assert await restricting_trial(session, tenant_id=tenant_id) is not None
    await fund_wallet(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert await restricting_trial(session, tenant_id=tenant_id) is None


async def test_an_account_with_no_trial_is_never_a_trial_account() -> None:
    created = await create_org_with_receptionist(
        name="No Trial Co",
        slug=f"nt-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        assert await read_trial_access(session, tenant_id=tenant_id) is None
        for locked in TRIAL_REFUSALS:
            assert await trial_blocker(session, tenant_id=tenant_id, locked=locked) is None


# --- the dial gate -----------------------------------------------------------------


async def test_a_trial_account_places_a_test_call_without_kyc(open_hours: None) -> None:
    tenant_id, agent_id = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
        )
    assert decision.allowed, decision


async def test_a_trial_account_may_not_place_any_other_outbound_call(open_hours: None) -> None:
    tenant_id, agent_id = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876543210"
        )
    assert not decision.allowed
    assert decision.rule == "trial_live_outbound_unavailable"
    assert decision.reason == TRIAL_REFUSALS["live_outbound"][1]


async def test_an_account_with_neither_a_trial_nor_a_payment_places_no_test_call(
    open_hours: None,
) -> None:
    tenant_id, agent_id = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM tenant_trials WHERE tenant_id = :t"), {"t": tenant_id}
        )
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
        )
    assert decision.rule == "trial_call_not_on_trial"


async def test_a_paid_account_passes_the_account_gate_for_its_own_test_call(
    open_hours: None,
) -> None:
    """After payment the test call is the paid one (D-859); what it needs beyond the dial
    gate (a moved agent with its own number) is `agents/paid_test_calls`'s."""
    tenant_id, agent_id = await _trial_tenant()
    await fund_wallet(tenant_id)
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
        )
    assert decision.rule != "trial_call_not_on_trial"


async def test_the_pledge_comes_before_the_first_test_call(open_hours: None) -> None:
    tenant_id, agent_id = await _trial_tenant(pledged=False)
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
        )
    assert decision.rule == "outbound_pledge_missing"


async def test_a_test_call_still_meets_dnc_hours_and_india_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _trial_tenant()
    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda *a, **k: False)
    async with tenant_session(tenant_id) as session:
        hours = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
        )
    assert hours.rule == "calling_hours"
    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda *a, **k: True)
    async with tenant_session(tenant_id) as session:
        abroad = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+14155550100",
            trial_call=True,
        )
        await compliance_service.add_to_dnc(
            session, tenant_id=tenant_id, phone_e164="+919876543211", source="manual"
        )
        dnc = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543211",
            trial_call=True,
        )
    assert abroad.rule == "destination_not_india"
    assert dnc.rule == "dnc"


async def test_used_minutes_end_the_trial_calls(open_hours: None) -> None:
    tenant_id, agent_id = await _trial_tenant(minutes=2)
    await _trial_call_row(tenant_id, agent_id, status="completed", seconds=121)
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
        )
        access = await read_trial_access(session, tenant_id=tenant_id)
    assert decision.rule == "trial_minutes_used"
    assert access is not None and access.minutes_used == 3 and access.minutes_left == 0


async def test_the_daily_cap_counts_todays_test_calls(
    open_hours: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "trial_daily_call_cap", 2)
    tenant_id, agent_id = await _trial_tenant()
    for _ in range(2):
        await _trial_call_row(tenant_id, agent_id, status="completed", seconds=30)
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
        )
    assert decision.rule == "trial_daily_cap"
    assert "2 test calls" in (decision.reason or "")


async def test_a_trial_past_its_end_date_stops_test_calls(open_hours: None) -> None:
    tenant_id, agent_id = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE tenant_trials SET started_at = now() - interval '20 days', "
                "ends_at = now() - interval '1 day' WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=True,
        )
    assert decision.rule == "trial_ended"
    assert decision.reason == "Your free trial has ended. Add credit to continue."


def test_the_daily_window_starts_at_ist_midnight() -> None:
    at = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)  # 01:30 IST on the 10th
    assert ist_day_start(at) == datetime(2026, 10, 9, 18, 30, tzinfo=UTC)


# --- the other gates ---------------------------------------------------------------


async def test_numbers_are_refused_with_the_add_credit_step() -> None:
    tenant_id, agent_id = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        readiness = await purchase_readiness(session, tenant_id=tenant_id)
        assert readiness.step == "add_credit"
        assert readiness.blocker == "trial_numbers_unavailable"
        with pytest.raises(ProblemError) as refused:
            await agents_service.provision_number(
                session,
                tenant_id=tenant_id,
                e164="+918012345678",
                series="standard",
                agent_id=agent_id,
                provider=None,
                purpose=None,
            )
    assert refused.value.code == "trial_numbers_unavailable"


async def test_campaigns_and_kyc_writes_are_refused_until_paid() -> None:
    tenant_id, _ = await _trial_tenant()
    principal = Principal(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner", realm="client")
    async with tenant_session(tenant_id) as session:
        assert (
            await trial_blocker(session, tenant_id=tenant_id, locked="campaigns")
            == (TRIAL_REFUSALS["campaigns"])
        )
        with pytest.raises(ProblemError) as refused:
            await _kyc_writer(principal, session)
    assert refused.value.code == "trial_kyc_unavailable"
    await fund_wallet(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert await _kyc_writer(principal, session) is principal


async def test_an_answer_only_agent_cannot_be_published_on_a_trial() -> None:
    tenant_id, agent_id = await _trial_tenant(direction="inbound")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert refused.value.code == "trial_inbound_unavailable"


# --- D-853: a test call from any READY agent ---------------------------------------------


async def _ready(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """ "Get it ready" (D-838): published, taking no calls."""
    async with tenant_session(tenant_id) as session:
        await agent_lifecycle.prepare_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def _decide(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, trial_call: bool
) -> compliance_service.DispatchDecision:
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            trial_call=trial_call,
        )


async def test_a_ready_answer_only_agent_places_a_test_call(open_hours: None) -> None:
    """The founder's rule (22 Oct 2026): during a trial any ready agent may ring the owner,
    including one that only answers calls, with no "Taking calls" switch."""
    tenant_id, agent_id = await _trial_tenant(direction="inbound")
    await _ready(tenant_id, agent_id)
    decision = await _decide(tenant_id, agent_id, trial_call=True)
    assert decision.allowed, decision


async def test_every_other_dial_still_refuses_a_ready_or_answer_only_agent(
    open_hours: None,
) -> None:
    """The exception is the trial test call's alone: the same ready agent placing any other
    call is still refused as not live."""
    tenant_id, agent_id = await _trial_tenant(direction="inbound")
    await _ready(tenant_id, agent_id)
    decision = await _decide(tenant_id, agent_id, trial_call=False)
    assert not decision.allowed
    assert decision.rule == "agent_not_live"


async def test_a_draft_agent_is_told_to_get_ready_first(open_hours: None) -> None:
    tenant_id, agent_id = await _trial_tenant(direction="inbound")
    decision = await _decide(tenant_id, agent_id, trial_call=True)
    assert not decision.allowed
    assert decision.rule == compliance_service.AGENT_NOT_READY_RULE
    assert "Get it ready" in (decision.reason or "")


async def test_a_switched_off_calling_agent_still_places_a_test_call(open_hours: None) -> None:
    """Switched off is published and taking no calls, which is ready."""
    tenant_id, agent_id = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        await agent_lifecycle.deactivate_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert (await _decide(tenant_id, agent_id, trial_call=True)).allowed
    assert (await _decide(tenant_id, agent_id, trial_call=False)).rule == "agent_not_live"


async def test_a_paused_agent_with_no_engine_agent_is_not_ready(open_hours: None) -> None:
    """Ready means published: a paused row the engine never received cannot place a call."""
    tenant_id, agent_id = await _trial_tenant(direction="inbound")
    await _ready(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :aid"), {"aid": agent_id}
        )
    decision = await _decide(tenant_id, agent_id, trial_call=True)
    assert decision.rule == compliance_service.AGENT_NOT_READY_RULE


# --- the shared number ---------------------------------------------------------------


class _Numbers:
    def __init__(self) -> None:
        self.row: dict[str, Any] = {
            "number": TRIAL_NUMBER.removeprefix("+"),
            "label": None,
            "source": "rented",
            "agent": "ag_founder",
            "since": "2026-10-08T07:15:40Z",
            "provider": None,
            "callingAgent": None,
        }
        self.patches: list[dict[str, Any]] = []
        self.refuse = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=self.row)
        body = json.loads(request.content)
        self.patches.append(body)
        if self.refuse:
            return httpx.Response(409, json={"error": "Turn voice on.", "code": "conflict"})
        self.row.update(body)
        return httpx.Response(200, json=self.row)


@pytest.fixture
def numbers(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Numbers]:
    fake = _Numbers()
    set_thinnest_numbers(
        ThinnestNumbers(
            api_key="ta_live_test",
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(fake.handler), base_url=BASE_URL
            ),
        )
    )
    monkeypatch.setattr(get_settings(), "trial_caller_number", TRIAL_NUMBER)
    yield fake
    set_thinnest_numbers(None)


async def test_lending_sets_nothing_to_answer_and_lends_to_the_agent(numbers: _Numbers) -> None:
    assert await engine_numbers.lend_trial_line("ag_trial")
    assert numbers.patches == [{"agent": None, "callingAgent": "ag_trial"}]


async def test_a_refused_lend_is_reported_not_placed(numbers: _Numbers) -> None:
    numbers.refuse = True
    assert not await engine_numbers.lend_trial_line("ag_trial")


async def test_the_trial_number_is_never_recorded_against_a_client(numbers: _Numbers) -> None:
    tenant_id, _ = await _trial_tenant()
    await fund_wallet(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await engine_numbers.record_engine_number(
                session,
                tenant_id=tenant_id,
                e164=TRIAL_NUMBER,
                direction="inbound",
                agent_id=None,
                purpose=None,
            )
    assert refused.value.code in {
        "engine_number_is_trial_number",
        "number_provider_not_on_this_engine",
    }


async def test_one_test_call_at_a_time_across_every_trial_account() -> None:
    first, first_agent = await _trial_tenant()
    second, _ = await _trial_tenant()
    await _trial_call_row(first, first_agent, status="queued")
    async with tenant_session(second) as session:
        with pytest.raises(ProblemError) as busy:
            await agents_service._hold_trial_line(session)
    assert busy.value.code == "trial_line_busy"
    assert busy.value.detail == "Another test call is in progress."
    async with tenant_session(first) as session:
        await session.execute(
            text("UPDATE calls SET status = 'completed' WHERE tenant_id = :t AND trial_call"),
            {"t": first},
        )
    async with tenant_session(second) as session:
        await agents_service._hold_trial_line(session)


async def test_a_lost_end_ages_out_of_the_line() -> None:
    tenant_id, agent_id = await _trial_tenant()
    await _trial_call_row(tenant_id, agent_id, status="queued")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET created_at = now() - interval '1 hour' "
                "WHERE tenant_id = :t AND trial_call"
            ),
            {"t": tenant_id},
        )
        await agents_service._hold_trial_line(session)


async def test_the_adapter_sends_from_and_the_per_call_limit() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"id": "ag_1", "greeting": "Idi AI assistant."})
        return httpx.Response(200, json={"id": "out_1", "status": "ringing"})

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )
    await engine.start_outbound_call(
        "ag_1",
        "+919876543210",
        CallContext(from_e164=TRIAL_NUMBER, max_call_seconds=180, call_id=str(uuid.uuid4())),
    )
    call = seen[-1]
    body = json.loads(call.content)
    # The trial agent is named and rings from the lent shared number, in our developer
    # workspace (place-call `agent`, `from`: "its own, or one lent to it for calling").
    assert body["agent"] == "ag_1"
    assert body["from"] == TRIAL_NUMBER
    assert body["overrides"] == {"maxCallSeconds": 180}
    assert "Thinnest-Workspace" not in call.headers


def test_a_trial_agent_may_be_created_in_the_developer_workspace_and_nothing_else() -> None:
    with pytest.raises(ProblemError):
        workspace_headers("POST", "/agents", None)
    with trial_agent_in_developer_workspace():
        assert workspace_headers("POST", "/agents", None) == {}
        with pytest.raises(ProblemError):
            workspace_headers("POST", "/do-not-call", None)
    with pytest.raises(ProblemError):
        workspace_headers("POST", "/agents", None)


# --- the first payment -----------------------------------------------------------------


async def test_the_first_payment_ends_the_trial_and_owes_a_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _ = await _trial_tenant()
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500.00"), reason="topup", ref="pay_1"
        )
        assert await on_payment_credited(
            session, tenant_id=tenant_id, amount_inr=Decimal("500.00"), via="wallet_topup"
        )
        trial = await read_trial(session, tenant_id=tenant_id)
        workspace = (
            await session.execute(
                text("SELECT status FROM tenant_engine_workspaces WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
        owed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = 'provision_engine_workspace' "
                    "AND payload ->> 'tenant_id' = :t"
                ),
                {"t": str(tenant_id)},
            )
        ).scalar()
        assert await has_paid(session, tenant_id=tenant_id)
        assert await restricting_trial(session, tenant_id=tenant_id) is None
        # Once: a second payment changes nothing.
        assert not await on_payment_credited(
            session, tenant_id=tenant_id, amount_inr=Decimal("500.00"), via="wallet_topup"
        )
    assert trial is not None and trial.status == "converted" and trial.erase_after is None
    assert workspace == "pending"
    assert owed == 1


async def test_a_payment_under_the_minimum_is_not_the_first_payment() -> None:
    tenant_id, _ = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        assert not await on_payment_credited(
            session, tenant_id=tenant_id, amount_inr=Decimal("99.99"), via="manual_topup"
        )
        assert not await has_paid(session, tenant_id=tenant_id)


async def test_a_grant_is_not_a_payment() -> None:
    tenant_id, _ = await _trial_tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("500.00"), reason="grant", ref="grant:x"
        )
        assert not await has_paid(session, tenant_id=tenant_id)
        assert await restricting_trial(session, tenant_id=tenant_id) is not None


async def test_the_backfill_owes_a_workspace_only_to_paid_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unpaid, _ = await _trial_tenant()
    paid, _ = await _trial_tenant()
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    await fund_wallet(paid)
    queued: list[uuid.UUID] = []

    async def record(session: Any, *, tenant_id: uuid.UUID, reopen: bool = False) -> bool:
        queued.append(tenant_id)
        return True

    monkeypatch.setattr(engine_workspaces, "queue_workspace_provisioning", record)
    monkeypatch.setattr(engine_workspaces, "PROVISION_SWEEP_BUDGET", 10_000)
    await engine_workspaces.retry_engine_workspaces({})
    assert paid in queued
    assert unpaid not in queued


async def test_the_sweep_ends_a_trial_whose_minutes_are_used() -> None:
    tenant_id, agent_id = await _trial_tenant(minutes=1)
    await _trial_call_row(tenant_id, agent_id, status="completed", seconds=75)
    assert await trial_sweep._close_if_expired(tenant_id, now=datetime.now(UTC))
    async with tenant_session(tenant_id) as session:
        trial = await read_trial(session, tenant_id=tenant_id)
    assert trial is not None and trial.status == "expired"
    assert trial.ended_reason == "The trial's free minutes were used."
    assert trial.ends_at > datetime.now(UTC) - timedelta(minutes=1)


# --- the shared number in the ops console ---------------------------------------------


@pytest.fixture
def platform_numbers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The developer workspace's numbers as `GET /phone-numbers` would list them."""
    from apps.api.campaigns import engine_numbers as numbers_module
    from apps.api.ops import trial_number
    from calevate_shared.engine import ProvisionedNumber

    held = [TRIAL_NUMBER, "+918045678902"]

    async def listed(workspace: str | None) -> list[ProvisionedNumber]:
        assert workspace is None, "only the developer workspace is read"
        return [
            ProvisionedNumber(
                e164=e164, provider=None, engine_number_ref=e164[1:], engine_owned=True
            )
            for e164 in held
        ]

    async def recorded() -> set[str]:
        return {"918045678902"}

    monkeypatch.setattr(numbers_module, "vendor_numbers", listed)
    monkeypatch.setattr(trial_number, "_recorded_digits", recorded)
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    return held


async def test_only_unrecorded_platform_held_numbers_are_offered(
    platform_numbers: list[str],
) -> None:
    from apps.api.ops.trial_number import trial_number_candidates

    offered = [candidate.e164 for candidate in await trial_number_candidates()]
    assert offered == [TRIAL_NUMBER]


async def test_the_setting_refuses_a_number_the_platform_does_not_hold_unrecorded(
    platform_numbers: list[str],
) -> None:
    from apps.api.ops.trial_number import assert_trial_number_selectable

    await assert_trial_number_selectable(TRIAL_NUMBER)
    await assert_trial_number_selectable(None)
    for wrong in ("+918045678902", "+918000000000"):
        with pytest.raises(ProblemError) as refused:
            await assert_trial_number_selectable(wrong)
        assert refused.value.code == "trial_number_not_platform_held"


async def test_the_config_write_checks_the_trial_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.ops import config_service, trial_number

    async def refuse(e164: str | None) -> None:
        raise ProblemError.business_rule("trial_number_not_platform_held", "no")

    monkeypatch.setattr(trial_number, "assert_trial_number_selectable", refuse)
    from apps.api.db.session import untenanted_session

    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as refused:
            await config_service.set_value(
                session,
                key="trial_caller_number",
                value=TRIAL_NUMBER,
                note="test",
                actor_id=uuid.uuid4(),
                expected_revision=0,
            )
    assert refused.value.code == "trial_number_not_platform_held"


async def test_an_operator_can_run_the_smoke_call_path(
    open_hours: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The admin smoke route runs the client's own path: here it stops at "not available
    yet" because no trial number is set, which proves the gate it reaches."""
    from apps.api.agents.trial_calls import place_trial_call

    tenant_id, agent_id = await _trial_tenant()
    monkeypatch.setattr(get_settings(), "trial_caller_number", None)
    operator = Principal(user_id=uuid.uuid4(), tenant_id=None, role="operator", realm="admin")
    async with tenant_session(tenant_id) as session:
        result = await place_trial_call(
            session,
            principal=operator,
            tenant_id=tenant_id,
            agent_id=agent_id,
            number="9876543210",
            idempotency_key=str(uuid.uuid4()),
            ip=None,
        )
    assert result.status == "blocked"
    assert result.blocked_rule == "trial_calling_not_ready"


# --- Studio minutes on a trial (D-727) ----------------------------------------------------


async def _on_studio(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, studio: bool = True, key: str = "byok_voice"
) -> None:
    """Stamp the agent's live route with a Studio rate key, as a Studio publish does: `byok_voice`,
    or `byok_llm_voice` once the agent answers on our own model (`own_model_rate_key`)."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET engine_rate_key = :key "
                "WHERE agent_id = :aid AND active"
            ),
            {"key": key if studio else None, "aid": agent_id},
        )


async def _refusal(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
    from apps.api.compliance.trial_access import refuse_trial_studio_over_cap

    async with tenant_session(tenant_id) as session:
        try:
            await refuse_trial_studio_over_cap(session, tenant_id=tenant_id, agent_id=agent_id)
        except ProblemError as exc:
            return exc.code
    return None


@pytest.mark.parametrize("key", ["byok_voice", "byok_llm_voice"])
async def test_studio_test_calls_stop_at_the_trials_studio_minutes(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setattr(get_settings(), "trial_studio_minutes", 2)
    tenant_id, agent_id = await _trial_tenant()
    await _on_studio(tenant_id, agent_id, key=key)
    await _trial_call_row(tenant_id, agent_id, status="completed", seconds=60)
    assert await _refusal(tenant_id, agent_id) is None
    await _trial_call_row(tenant_id, agent_id, status="completed", seconds=60)
    assert await _refusal(tenant_id, agent_id) == "trial_studio_minutes_used"
    # A Clear agent of the same account is not asked.
    await _on_studio(tenant_id, agent_id, studio=False)
    assert await _refusal(tenant_id, agent_id) is None


async def _end_trial_calls_of(tenant_id: uuid.UUID) -> None:
    """End this account's open test calls, so the shared line is free for the next test."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET status = 'completed' WHERE tenant_id = :t AND trial_call "
                "AND status IN ('queued', 'ringing', 'in_progress')"
            ),
            {"t": tenant_id},
        )


class _DialRecorder:
    """The configured engine with the dial recorded instead of placed."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.contexts: list[CallContext] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def start_outbound_call(self, ref: Any, to: Any, ctx: CallContext) -> str:
        self.contexts.append(ctx)
        return f"out_{uuid.uuid4().hex}"


@pytest.mark.parametrize(
    ("studio", "used_s", "limit_s"),
    [
        # 13 of 15 Studio minutes used: the call stops at the 2 minutes left, not the 20.
        (True, 13 * 60, 120),
        # 14:30 used: the platform's 60-second minimum.
        (True, 14 * 60 + 30, 60),
        # A Clear test call keeps the general limit.
        (False, 13 * 60, 1200),
    ],
)
async def test_a_studio_test_call_is_cut_at_the_studio_minutes_left(
    monkeypatch: pytest.MonkeyPatch, studio: bool, used_s: int, limit_s: int
) -> None:
    monkeypatch.setattr(get_settings(), "trial_studio_minutes", 15)
    tenant_id, agent_id = await _trial_tenant()
    await _on_studio(tenant_id, agent_id, studio=studio)
    await _trial_call_row(tenant_id, agent_id, status="completed", seconds=used_s)

    async def _lent(*_: Any, **__: Any) -> None:
        return None

    recorder = _DialRecorder(agents_service.get_engine())
    monkeypatch.setattr(agents_service, "_lend_trial_line", _lent)
    monkeypatch.setattr(agents_service, "get_engine", lambda: recorder)
    try:
        async with tenant_session(tenant_id) as session:
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876543210",
                trial=TrialDial(from_e164=TRIAL_NUMBER, max_call_seconds=1200),
            )
    finally:
        await _end_trial_calls_of(tenant_id)
    [ctx] = recorder.contexts
    assert ctx.max_call_seconds == limit_s


async def _trial_dial_context(
    monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> CallContext:
    async def _lent(*_: Any, **__: Any) -> None:
        return None

    recorder = _DialRecorder(agents_service.get_engine())
    monkeypatch.setattr(agents_service, "_lend_trial_line", _lent)
    monkeypatch.setattr(agents_service, "get_engine", lambda: recorder)
    try:
        async with tenant_session(tenant_id) as session:
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876543210",
                trial=TrialDial(from_e164=TRIAL_NUMBER, max_call_seconds=180),
            )
    finally:
        await _end_trial_calls_of(tenant_id)
    [ctx] = recorder.contexts
    return ctx


async def test_an_answer_only_agent_opens_its_test_call_saying_who_is_calling_and_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Founder, 23 Oct 2026: a receptionist ringing its owner does not thank them for calling.
    With its AI notice on, the notice introduces it and the line says only why it rings
    (D-865); with it off, the line says who is calling itself."""
    tenant_id, agent_id = await _trial_tenant(direction="inbound")
    await _ready(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET ai_disclosure_enabled = true WHERE id = :a"), {"a": agent_id}
        )
        ai_line = (
            await session.execute(
                text("SELECT ai_disclosure_line FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    ctx = await _trial_dial_context(monkeypatch, tenant_id, agent_id)
    assert ctx.opening == (f"నమస్కారం అండి, {ai_line.strip()} ఇది మీ కొత్త రిసెప్షనిస్ట్ టెస్ట్ కాల్. ఇప్పుడు మాట్లాడొచ్చా?")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET ai_disclosure_enabled = false WHERE id = :a"), {"a": agent_id}
        )
    ctx = await _trial_dial_context(monkeypatch, tenant_id, agent_id)
    assert ctx.opening == (
        "నమస్కారం అండి, నేను Test caller, Trial Tea House నుంచి, ఇది మీ కొత్త రిసెప్షనిస్ట్ టెస్ట్ కాల్. ఇప్పుడు మాట్లాడొచ్చా?"
    )


async def test_a_calling_agent_keeps_its_own_greeting_on_a_test_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _trial_tenant()
    ctx = await _trial_dial_context(monkeypatch, tenant_id, agent_id)
    assert ctx.opening is None


def test_the_test_call_line_is_the_language_line_then_the_notices() -> None:
    row: dict[str, Any] = {
        "direction": "inbound",
        "language_primary": "en-IN",
        "name": "Anjali",
        "business_name": "Raghava Organics",
        "ai_disclosure_line": "I am an AI assistant.",
        "ai_disclosure_enabled": False,
        "recording_notice_line": "This call is recorded.",
        "recording_notice_enabled": True,
        "caller_memory_notice_line": "",
        "caller_memory_enabled": False,
    }
    said = agents_service.trial_call_first_words(row, call_is_recorded=True)  # type: ignore[arg-type]
    assert said == (
        "Hello, this is Anjali, your new receptionist at Raghava Organics, on a test call. Is "
        "now a good time to talk? This call is recorded."
    )
    # A language with no such line keeps the greeting; so does an agent that calls out.
    assert (
        agents_service.trial_call_first_words(  # type: ignore[arg-type]
            {**row, "language_primary": "bn-IN"}, call_is_recorded=True
        )
        is None
    )
    assert (
        agents_service.trial_call_first_words(  # type: ignore[arg-type]
            {**row, "direction": "outbound"}, call_is_recorded=True
        )
        is None
    )


async def test_the_adapter_speaks_the_dials_own_first_words_and_falls_back_when_too_long() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"id": "ag_1", "greeting": "Thanks for calling."})
        return httpx.Response(200, json={"id": "out_1", "status": "ringing"})

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )
    await engine.start_outbound_call(
        "ag_1", "+919876543210", CallContext(opening="Hello, this is Anjali. Good time?")
    )
    assert [r.method for r in seen] == ["POST"]
    assert json.loads(seen[-1].content)["purpose"] == "Hello, this is Anjali. Good time?"
    seen.clear()
    await engine.start_outbound_call("ag_1", "+919876543210", CallContext(opening="x" * 301))
    assert json.loads(seen[-1].content)["purpose"] == "Thanks for calling."


async def test_metered_studio_minutes_count_after_the_agent_moves_to_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metered minutes are counted by the rung stamped on the usage row, so a call made on
    Studio still counts once the agent has moved to Clear and back."""
    monkeypatch.setattr(get_settings(), "trial_studio_minutes", 1)
    tenant_id, agent_id = await _trial_tenant()
    await _trial_call_row(tenant_id, agent_id, status="completed", seconds=90)
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE tenant_id = :t AND trial_call"), {"t": tenant_id}
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:id, :tid, :cid, "
                "'platform_min', 1.5, 1.6500, now(), CAST(:meta AS jsonb), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": call_id,
                "meta": json.dumps({"voice_tier": "studio"}),
            },
        )
    await _on_studio(tenant_id, agent_id)
    assert await _refusal(tenant_id, agent_id) == "trial_studio_minutes_used"


async def test_a_studio_test_call_over_the_cap_is_refused_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "trial_studio_minutes", 0)
    tenant_id, agent_id = await _trial_tenant()
    await _on_studio(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as caught:
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164="+919876543210",
                trial=TrialDial(from_e164=TRIAL_NUMBER, max_call_seconds=180),
            )
    assert caught.value.code == "trial_studio_minutes_used"
    assert caught.value.title == "Your Studio minutes for the trial are used up"
    assert caught.value.remediation == (
        "Switch this agent to a Clear voice, or add credit to keep using Studio."
    )
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert rows == 0


async def test_two_studio_test_calls_at_once_cannot_both_pass_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check runs under the platform's trial-line lock with the new call's row, as
    `dispatch_call` runs it, so the second dial sees the first and cannot slip past."""
    import asyncio

    from apps.api.compliance.trial_access import refuse_trial_studio_over_cap

    monkeypatch.setattr(get_settings(), "trial_studio_minutes", 1)
    tenant_id, agent_id = await _trial_tenant()
    await _end_trial_calls_of(tenant_id)

    async def dial() -> str:
        try:
            async with tenant_session(tenant_id) as session:
                await agents_service._hold_trial_line(session)
                await refuse_trial_studio_over_cap(session, tenant_id=tenant_id, agent_id=agent_id)
                await session.execute(
                    text(
                        "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                        "to_e164, trial_call, status, created_at, updated_at) VALUES (:id, :tid, "
                        ":aid, :ecid, 'outbound', '+919876543210', true, 'queued', now(), now())"
                    ),
                    {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "ecid": uuid.uuid4().hex},
                )
        except ProblemError as exc:
            return exc.code
        return "placed"

    try:
        outcomes = sorted(await asyncio.gather(dial(), dial()))
    finally:
        await _end_trial_calls_of(tenant_id)
    assert outcomes == ["placed", "trial_line_busy"]


async def test_an_account_that_paid_is_not_held_to_the_trials_studio_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A payment between the trial gate and the dial lifts the trial, and with it the cap."""
    monkeypatch.setattr(get_settings(), "trial_studio_minutes", 1)
    tenant_id, agent_id = await _trial_tenant()
    await _on_studio(tenant_id, agent_id)
    await _trial_call_row(tenant_id, agent_id, status="completed", seconds=120)
    assert await _refusal(tenant_id, agent_id) == "trial_studio_minutes_used"
    await fund_wallet(tenant_id)
    assert await _refusal(tenant_id, agent_id) is None
