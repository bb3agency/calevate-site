"""A campaign skips people another campaign or call reached recently (D-1046).

`campaigns.skip_recent_days` (default 7, NULL off) is asked by the dispatcher, per contact,
after the dial gate. A held contact waits, attempt refunded, until the last call that reached
the person is that many days old. The per-person 24-hour cap is asked by the gate on the same
path, and a contact it holds waits the same way rather than being settled.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.campaigns import service as campaigns
from apps.api.compliance.pacing import RECENT_SKIP_DEFAULT_DAYS, recently_called_waiting
from apps.api.db.session import tenant_session
from apps.workers import campaign_dispatch
from sqlalchemy import text
from tests.dispatch_budget_test import (
    _daytime,  # noqa: F401  (autouse: the dial runs inside calling hours)
    _dlt_rows,
    _launched_campaign,
    _settle_what_this_module_started,  # noqa: F401  (autouse: leaves no running campaign)
    _tenant,
)
from tests.person_contact_pacing_test import _call

pytestmark = pytest.mark.anyio


async def _tick(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> dict[str, int]:
    return await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )


async def _contact(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> tuple[str, int, datetime]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempts, next_attempt_at FROM campaign_contacts "
                    "WHERE campaign_id = :c"
                ),
                {"c": campaign_id},
            )
        ).one()
    return str(row[0]), int(row[1]), row[2]


async def _age_calls(tenant_id: uuid.UUID, days: float) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET created_at = created_at - make_interval(secs => :s), "
                "status = 'completed'"
            ),
            {"s": days * 86400},
        )
        await session.execute(
            text("UPDATE campaign_contacts SET next_attempt_at = now() WHERE status = 'pending'")
        )


async def test_a_person_campaign_a_reached_is_skipped_by_campaign_b_until_the_week_is_up() -> None:
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    first = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Campaign A", phones=("9876610001",)
    )
    assert (await _tick(tenant_id, first))["dialled"] == 1

    second = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Campaign B", phones=("9876610001",)
    )
    async with tenant_session(tenant_id) as session:
        held = await recently_called_waiting(
            session, campaign_id=second, days=RECENT_SKIP_DEFAULT_DAYS
        )
    assert held == 1, "the campaign says how many people the skip holds"

    # Day 3: still inside the week.
    await _age_calls(tenant_id, 2)
    result = await _tick(tenant_id, second)
    assert result == {"dialled": 0, "blocked": 1, "exhausted": 0}, result
    status, attempts, next_at = await _contact(tenant_id, second)
    assert (status, attempts) == ("pending", 0), "held, never settled, the attempt refunded"
    assert next_at > datetime.now(UTC) + timedelta(days=4), next_at

    # Day 8: the call that reached them is more than a week old.
    await _age_calls(tenant_id, 6)
    assert (await _tick(tenant_id, second))["dialled"] == 1


async def test_an_instant_lead_call_holds_the_campaign_and_an_unanswered_one_does_not() -> None:
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    await _call(tenant_id, agent_id, "+919876610003", ago=timedelta(hours=30), status="no_answer")
    await _call(tenant_id, agent_id, "+919876610002", ago=timedelta(days=2))
    campaign = await _launched_campaign(
        tenant_id,
        agent_id,
        number_id,
        template_id,
        name="After the lead",
        phones=("9876610002", "9876610003"),
    )
    result = await _tick(tenant_id, campaign)
    assert result["dialled"] == 1 and result["blocked"] == 1, result


async def test_the_skip_switched_off_dials_and_the_campaigns_own_tries_never_hold_it() -> None:
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    await _call(tenant_id, agent_id, "+919876610004", ago=timedelta(days=1))
    campaign = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="No skip", phones=("9876610004",)
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET skip_recent_days = NULL WHERE id = :c"), {"c": campaign}
        )
    assert (await _tick(tenant_id, campaign))["dialled"] == 1

    # Its own call, answered, then a retry due: the campaign's own call never holds it.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET skip_recent_days = 7 WHERE id = :c"), {"c": campaign}
        )
        await session.execute(
            text(
                "DELETE FROM calls WHERE campaign_id IS NULL AND to_e164 = '+919876610004' "
                "AND engine_call_id LIKE 'pacing-%'"
            )
        )
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'pending', next_attempt_at = now() "
                "WHERE campaign_id = :c"
            ),
            {"c": campaign},
        )
    assert (await _tick(tenant_id, campaign))["dialled"] == 1


async def test_a_person_rung_three_times_today_waits_for_the_cap_not_thirty_minutes() -> None:
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    for hours in (10, 5, 1):
        await _call(
            tenant_id, agent_id, "+919876610005", ago=timedelta(hours=hours), status="no_answer"
        )
    campaign = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Capped", phones=("9876610005",)
    )
    result = await _tick(tenant_id, campaign)
    assert result == {"dialled": 0, "blocked": 1, "exhausted": 0}, result
    status, attempts, next_at = await _contact(tenant_id, campaign)
    assert (status, attempts) == ("pending", 0)
    expected = datetime.now(UTC) + timedelta(hours=14)
    assert abs((next_at - expected).total_seconds()) < 120, next_at


async def test_the_skip_is_a_setting_a_started_campaign_may_change() -> None:
    from apps.api.campaigns.controls import STARTED_EDITABLE

    assert "skip_recent_days" in STARTED_EDITABLE
