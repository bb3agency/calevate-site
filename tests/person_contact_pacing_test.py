"""At most `person_daily_call_cap` calls to one person in 24 hours, on every dial path (D-1046).

The cap is counted from `calls`, which every door writes before the phone can ring, and asked
in the one dial gate. So the doors are told apart here by the marks their rows carry (a
campaign's `campaign_id`, a follow-up's `callback_of_call_id`, Make a call's
`placed_by_person`, a new lead's first call with none), and the fourth call is asked through
the gate and through Make a call's own route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.compliance import pacing
from apps.api.compliance.service import (
    PERSON_CONTACT_PACING_RULE,
    PERSON_LEVEL_REFUSALS,
    person_contact_pacing_refusal,
)
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from calevate_shared.calling_window import IST
from sqlalchemy import text
from tests.lead_dial_routes_test import _client, _dialable_tenant, _lead
from tests.outbound_consent_policy_test import _fresh_phone, _gate
from tests.outbound_consent_policy_test import _tenant as _gate_tenant

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so a refusal here is never the clock's."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    phone: str,
    *,
    ago: timedelta,
    direction: str = "outbound",
    status: str = "completed",
    not_placed_reason: str | None = None,
    placed_by_person: bool = False,
    callback_of: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, not_placed_reason, placed_by_person, callback_of_call_id, campaign_id, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, :dir, :to, :status, "
                ":npr, :pbp, :cb, :cid, now() - make_interval(secs => :ago), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"pacing-{call_id}",
                "dir": direction,
                "to": phone,
                "status": status,
                "npr": not_placed_reason,
                "pbp": placed_by_person,
                "cb": callback_of,
                "cid": campaign_id,
                "ago": ago.total_seconds(),
            },
        )
    return call_id


async def _three_doors(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> None:
    """A new lead's first call, a follow-up of it, and a campaign's call."""
    first = await _call(tenant_id, agent_id, phone, ago=timedelta(hours=20))
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=6), callback_of=first)
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=1), campaign_id=uuid.uuid4())


async def test_the_fourth_call_in_24_hours_is_refused_until_the_oldest_ages_out() -> None:
    tenant_id, agent_id = await _gate_tenant("pace4")
    phone = _fresh_phone()
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=20))
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=6))
    assert (await _gate(tenant_id, agent_id, phone)).allowed is True, "two calls are fine"

    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=1), placed_by_person=True)
    decision = await _gate(tenant_id, agent_id, phone)

    assert decision.allowed is False
    assert decision.rule == PERSON_CONTACT_PACING_RULE
    assert decision.opens_at is not None
    expected = datetime.now(UTC) + timedelta(hours=4)
    assert abs((decision.opens_at - expected).total_seconds()) < 60, decision.opens_at
    assert decision.reason is not None and decision.reason.startswith(
        "Called 3 times in the last 24 hours. Can call again "
    )
    assert PERSON_CONTACT_PACING_RULE not in PERSON_LEVEL_REFUSALS, "it lifts by waiting"


async def test_every_door_counts_and_the_refusal_reaches_make_a_call() -> None:
    """Three calls from three other doors, then Make a call: refused, with the sentence."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    await _three_doors(tenant_id, agent_id, phone)

    async with _client() as http:
        response = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={**headers, "Idempotency-Key": f"pace-{lead_id}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked_rule"] == PERSON_CONTACT_PACING_RULE, body
    assert body["blocked_reason"].startswith("Called 3 times in the last 24 hours."), body


async def test_calls_that_never_rang_inbound_calls_and_old_calls_are_not_counted() -> None:
    tenant_id, agent_id = await _gate_tenant("pace-uncounted")
    phone = _fresh_phone()
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=2), not_placed_reason="lines_full")
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=2), direction="inbound")
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=25))
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=3))
    await _call(tenant_id, agent_id, phone, ago=timedelta(hours=1))
    assert (await _gate(tenant_id, agent_id, phone)).allowed is True


async def test_the_window_rolls_over_midnight_ist_rather_than_resetting() -> None:
    """Three calls late yesterday evening still count this morning: the cap is 24 hours of
    the person's phone, not a calendar day of ours."""
    tenant_id, agent_id = await _gate_tenant("pace-roll")
    phone = _fresh_phone()
    for hours in (13, 12.5, 12):
        await _call(tenant_id, agent_id, phone, ago=timedelta(hours=hours))
    decision = await _gate(tenant_id, agent_id, phone)
    assert decision.rule == PERSON_CONTACT_PACING_RULE


async def test_one_accounts_calls_never_count_against_another() -> None:
    first, first_agent = await _gate_tenant("pace-a")
    second, second_agent = await _gate_tenant("pace-b")
    phone = _fresh_phone()
    for hours in (3, 2, 1):
        await _call(first, first_agent, phone, ago=timedelta(hours=hours))
    assert (await _gate(first, first_agent, phone)).rule == PERSON_CONTACT_PACING_RULE
    assert (await _gate(second, second_agent, phone)).allowed is True


async def test_the_cap_is_the_console_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.core.settings import get_settings

    tenant_id, agent_id = await _gate_tenant("pace-cap")
    phone = _fresh_phone()
    for hours in (3, 2, 1):
        await _call(tenant_id, agent_id, phone, ago=timedelta(hours=hours))
    monkeypatch.setattr(get_settings(), "person_daily_call_cap", 4)
    assert (await _gate(tenant_id, agent_id, phone)).allowed is True


async def test_a_test_call_to_the_owners_own_number_is_not_capped_and_any_other_is() -> None:
    tenant_id, agent_id = await _gate_tenant("pace-own")
    phone = _fresh_phone()
    for hours in (3, 2, 1):
        await _call(tenant_id, agent_id, phone, ago=timedelta(hours=hours))
    async with tenant_session(tenant_id) as session:
        own = await person_contact_pacing_refusal(
            session,
            tenant_id=tenant_id,
            phone_e164=phone,
            trial_call=True,
            own_number_attested=True,
        )
        other = await person_contact_pacing_refusal(
            session,
            tenant_id=tenant_id,
            phone_e164=phone,
            trial_call=True,
            own_number_attested=False,
        )
    assert own is None
    assert other is not None and other.rule == PERSON_CONTACT_PACING_RULE


def test_the_owner_is_told_a_time_the_calling_hours_will_allow() -> None:
    now = datetime(2026, 11, 28, 10, 0, tzinfo=IST)
    assert pacing.when_text(datetime(2026, 11, 28, 16, 10, tzinfo=IST), now=now) == "at 4:10 PM"
    assert (
        pacing.when_text(datetime(2026, 11, 28, 22, 15, tzinfo=IST), now=now)
        == "tomorrow at 9:00 AM"
    )
    assert pacing.when_text(datetime(2026, 11, 29, 7, 0, tzinfo=IST), now=now) == (
        "tomorrow at 9:00 AM"
    )
    assert pacing.when_text(datetime(2026, 12, 3, 12, 5, tzinfo=IST), now=now) == (
        "on 3 Dec at 12:05 PM"
    )
    assert pacing.pacing_reason(1, datetime(2026, 11, 28, 16, 10, tzinfo=IST), now=now) == (
        "Called once in the last 24 hours. Can call again at 4:10 PM."
    )
    assert pacing.pacing_reason(2, datetime(2026, 11, 28, 16, 10, tzinfo=IST), now=now).startswith(
        "Called twice"
    )
