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
from apps.api.admin import service as admin_service
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
from tests.conftest import _owner_of, accept_agreements, fund_wallet

pytestmark = pytest.mark.asyncio

TRIAL_NUMBER = "+918045678901"


async def _trial_tenant(
    *, minutes: int | None = 30, pledged: bool = True, direction: str = "outbound"
) -> tuple[uuid.UUID, uuid.UUID]:
    """An unpaid account on a trial, with one published agent. KYC is NOT verified: a test
    call must not need it."""
    created = await admin_service.create_organization(
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
    created = await admin_service.create_organization(
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


async def test_only_a_trial_account_places_test_calls(open_hours: None) -> None:
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
    assert decision.rule == "trial_call_not_on_trial"


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


def test_trial_dial_carries_the_number_and_the_limit() -> None:
    dial = TrialDial(from_e164=TRIAL_NUMBER, max_call_seconds=180)
    assert dial.from_e164 == TRIAL_NUMBER and dial.max_call_seconds == 180


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
    body = json.loads(seen[-1].content)
    assert body["from"] == TRIAL_NUMBER
    assert body["overrides"] == {"maxCallSeconds": 180}


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
