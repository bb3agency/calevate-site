"""The campaign LAUNCH gate asks the autodialer-notice question the dial gate asks.

`compliance.service.check_dispatch` refuses every outbound dial whose sender has no
effective Regulation 4 notice, or whose notice does not declare the number the agent
calls from (`compliance/autodialer.py`). A launch gate that did not ask the same question
let such a campaign go `running` and then had every contact claimed, refused and
rescheduled for ever — the outcome `campaigns.service.launch_blockers` exists to prevent.

Each case is asserted twice: the launch refuses by the rule's own name, and the dial gate,
asked about the same agent, refuses by the same name. The second half is what keeps the
two gates from drifting apart.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service as campaigns
from apps.api.compliance.autodialer import (
    AUTODIALER_NOTICE_CLI_UNDECLARED_RULE,
    AUTODIALER_NOTICE_MISSING_RULE,
    AUTODIALER_NOTICE_NOT_YET_EFFECTIVE_RULE,
    AUTODIALER_NOTICE_WITHDRAWN_RULE,
    record_autodialer_notice,
)
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.conftest import (
    accept_agreements,
    bind_number_for_tests,
    fund_wallet,
    record_autodialer_notice_for_tests,
)
from tests.national_dnd_test import record_test_scrub

pytestmark = pytest.mark.rls

_UNRELATED_NUMBER = "+919800000001"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so the dial gate's answer is never the calling-hours rule."""
    fixed = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _campaign_ready_but_for_the_notice() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant, agent, campaign): every launch condition met, and NO notice on file."""
    created = await admin_service.create_organization(
        name="Notice Motors",
        slug=f"ntc-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    await fund_wallet(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Notice Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
        number_id = await bind_number_for_tests(
            session, tenant_id, agent_id, autodialer_notice=False
        )
        template_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
        )
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Notice test",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=1,
            calling_hours=None,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await campaigns.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": "9876530001"}],
        )
        await record_test_scrub(session, campaign_id)
    return tenant_id, agent_id, campaign_id


async def _notify(
    tenant_id: uuid.UUID,
    *,
    days_ago: int = 7,
    declared: list[str] | None = None,
    withdraw: bool = False,
) -> None:
    """Append a notice row. `declared=None` declares the agent's own number."""
    async with tenant_session(tenant_id) as session:
        user_id = (
            await session.execute(
                text("SELECT user_id FROM memberships WHERE tenant_id = :t LIMIT 1"),
                {"t": tenant_id},
            )
        ).scalar()
        if user_id is None:
            user_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO users (id, email, created_at, updated_at) "
                    "VALUES (:id, :e, now(), now())"
                ),
                {"id": user_id, "e": f"owner-{user_id}@example.test"},
            )
            await session.execute(
                text(
                    "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, "
                    "updated_at) VALUES (:id, :t, :u, 'owner', now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "u": user_id},
            )
        if declared is None:
            declared = [
                str(row[0])
                for row in (
                    await session.execute(
                        text("SELECT e164 FROM phone_numbers WHERE agent_id IS NOT NULL")
                    )
                ).all()
            ]
        await record_autodialer_notice(
            session,
            tenant_id=tenant_id,
            access_provider="Airtel",
            objective="Service reminders for our own customers",
            notified_on=(datetime.now(UTC) - timedelta(days=days_ago)).date(),
            declared_clis=declared,
            recorded_by=user_id,
            withdraw=withdraw,
        )


async def _launch_refusal(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> set[str]:
    """The rules `launch_campaign` refused with; empty if it launched."""
    async with tenant_session(tenant_id) as session:
        try:
            await campaigns.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        except ProblemError as refused:
            assert refused.code == "campaign_launch_blocked"
            return {str(field["rule"]) for field in refused.fields or []}
    return set()


async def _dial_rule(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876530001"
        )
    return None if decision.allowed else decision.rule


async def _assert_both_gates_refuse(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, campaign_id: uuid.UUID, rule: str
) -> None:
    # The notice is the only thing missing, so it is the only launch blocker.
    assert await _launch_refusal(tenant_id, campaign_id) == {rule}
    assert await _dial_rule(tenant_id, agent_id) == rule
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    assert status == "draft"


async def test_a_campaign_with_no_notice_on_file_does_not_launch() -> None:
    tenant_id, agent_id, campaign_id = await _campaign_ready_but_for_the_notice()
    await _assert_both_gates_refuse(
        tenant_id, agent_id, campaign_id, AUTODIALER_NOTICE_MISSING_RULE
    )


async def test_a_campaign_whose_notice_was_withdrawn_does_not_launch() -> None:
    tenant_id, agent_id, campaign_id = await _campaign_ready_but_for_the_notice()
    await _notify(tenant_id)
    await _notify(tenant_id, withdraw=True)
    await _assert_both_gates_refuse(
        tenant_id, agent_id, campaign_id, AUTODIALER_NOTICE_WITHDRAWN_RULE
    )


async def test_a_campaign_whose_notice_is_dated_in_the_future_does_not_launch() -> None:
    tenant_id, agent_id, campaign_id = await _campaign_ready_but_for_the_notice()
    await _notify(tenant_id, days_ago=-5)
    await _assert_both_gates_refuse(
        tenant_id, agent_id, campaign_id, AUTODIALER_NOTICE_NOT_YET_EFFECTIVE_RULE
    )


async def test_a_campaign_whose_agent_calls_from_an_undeclared_number_does_not_launch() -> None:
    """The notice is on file and in force, but names a different number — the agent's
    header would carry every call, so every call would be refused."""
    tenant_id, agent_id, campaign_id = await _campaign_ready_but_for_the_notice()
    await _notify(tenant_id, declared=[_UNRELATED_NUMBER])
    await _assert_both_gates_refuse(
        tenant_id, agent_id, campaign_id, AUTODIALER_NOTICE_CLI_UNDECLARED_RULE
    )


async def test_a_notice_that_declares_the_agents_number_lets_the_campaign_launch() -> None:
    tenant_id, agent_id, campaign_id = await _campaign_ready_but_for_the_notice()
    await _notify(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert (
            await campaigns.launch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)
            == []
        )
    assert await _dial_rule(tenant_id, agent_id) is None
    assert await _launch_refusal(tenant_id, campaign_id) == set()


async def test_the_fixture_that_binds_a_number_declares_it() -> None:
    """`bind_number_for_tests` is how every campaign fixture gives an agent a number, and
    the reason those fixtures stay green without knowing this rule exists. If it stopped
    declaring the number, this is the test that names why a hundred others went red."""
    tenant_id, agent_id, campaign_id = await _campaign_ready_but_for_the_notice()
    await record_autodialer_notice_for_tests(tenant_id)
    async with tenant_session(tenant_id) as session:
        await bind_number_for_tests(session, tenant_id, agent_id, series="160")
        blockers = await campaigns.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert AUTODIALER_NOTICE_CLI_UNDECLARED_RULE not in {b.rule for b in blockers}
