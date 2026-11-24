"""D-1041: a campaign's "Follow up on WhatsApp" card sets the follow-up up in one press.

The model is a stub, so what is asserted is the seam: without a connected WhatsApp nothing is
made; a press queues Pip's pass; the pass saves a draft scoped to this campaign with a grounded
message and the campaign's own outcomes; nothing starts until the switch is on, which waits
for WhatsApp's approval; a second press reuses the Follow-up; another account sees none of it;
and Pip's tool goes through the same function.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.campaigns import service as campaigns
from apps.api.copilot import write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.follow_up_actions_test import _actor, _done
from apps.api.core.errors import ProblemError
from apps.api.crm import swipe
from apps.api.db.session import tenant_session
from apps.api.follow_ups import campaign_whatsapp as cw
from apps.api.follow_ups import definition as d
from apps.api.follow_ups import runner, service
from apps.api.whatsapp import accounts, graph
from apps.workers import campaign_whatsapp_follow_up as worker
from apps.workers.extraction import (
    PROVIDER_UNAVAILABLE_REASON,
    QUOTA_EXHAUSTED_REASON,
    AssistCapability,
    PaidTurn,
    SpentRefusalError,
    assist_unavailable,
)
from apps.workers.script_assist import ANSWER_UNUSABLE_CODE
from sqlalchemy import text
from tests.follow_ups_runs_test import _call
from tests.lead_columns_test import Tenant, _client, _lead, _tenant

pytestmark = pytest.mark.anyio

MAIN_TASK = "Tell farmers the Rytu Khata app keeps their crop accounts. Install it from Play Store."
OUTCOMES = [
    {"key": "wants_details", "label": "Wants details", "meaning": "Asked to be sent details."},
    {
        "key": "installed",
        "label": "Installed",
        "meaning": "Installed the app.",
        "lead_status": "hot",
    },
]


async def _campaign(t: Tenant, *, main_task: str = MAIN_TASK) -> UUID:
    async with tenant_session(t.tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            name="Rytu Khata installs",
            classification="promotional",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
        )
        await session.execute(
            text("UPDATE campaigns SET main_task = :m WHERE id = :c"),
            {"m": main_task, "c": campaign_id},
        )
        await session.execute(
            text(
                "UPDATE agents SET business_outcomes = CAST(:o AS jsonb), "
                "language_primary = 'en-IN' WHERE id = :a"
            ),
            {"o": json.dumps(OUTCOMES), "a": t.agent_id},
        )
    return campaign_id


@pytest.fixture
def no_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(_session: Any) -> None:
        return None

    monkeypatch.setattr(swipe, "connected_account", none)


async def _connect(t: Tenant, monkeypatch: pytest.MonkeyPatch) -> UUID:
    """A connected WhatsApp account; WhatsApp's review answers PENDING."""
    account_id = uuid.uuid4()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO whatsapp_accounts (id, tenant_id, waba_id, onboarding, status) "
                "VALUES (:i, :t, '1' || abs(hashtext(CAST(:i AS text)))::text, 'new', "
                "'connected')"
            ),
            {"i": account_id, "t": t.tenant_id},
        )
    account = SimpleNamespace(id=account_id, waba_id="1234567", phone_number_id="99")

    async def connected(_session: Any) -> Any:
        return account

    async def token(_session: Any, **_kwargs: Any) -> str:
        return "test-token"

    async def create_template(**_kwargs: Any) -> tuple[str, str]:
        return "777", "PENDING"

    monkeypatch.setattr(swipe, "connected_account", connected)
    monkeypatch.setattr(accounts, "account_token", token)
    monkeypatch.setattr(graph, "create_template", create_template)
    return account_id


def _stub_model(monkeypatch: pytest.MonkeyPatch, raw: dict[str, Any]) -> None:
    async def fake_ask_json(_request: str, _instruction: str, **kwargs: Any) -> Any:
        value = kwargs["parse"](raw)
        if value is None:
            # As the ladder ends on an answer `accepted` refused: the paid turn rides along.
            raise SpentRefusalError(
                assist_unavailable(
                    AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
                ),
                [PaidTurn(usage=None, capability=AssistCapability(available=True))],
            )
        return SimpleNamespace(value=value, earlier=(), model=None, capability=None)

    async def no_meter(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "ask_json", fake_ask_json)
    monkeypatch.setattr(worker.crm_assist, "meter_assist", no_meter)
    monkeypatch.setattr(worker.crm_assist, "meter_earlier", no_meter)
    monkeypatch.setattr(worker.crm_assist, "meter_refusal", no_meter)


GROUNDED = {
    "message": "Thank you for talking with Column Realty. Install the Rytu Khata app from Play "
    "Store to keep your crop accounts.",
    "quote": "Install it from Play Store",
    "outcomes": ["wants_details", "not_an_outcome"],
}


async def _set_up_and_write(
    t: Tenant, campaign_id: UUID, monkeypatch: pytest.MonkeyPatch, raw: dict[str, Any]
) -> str:
    async with tenant_session(t.tenant_id) as session:
        card = await cw.set_up(session, tenant_id=t.tenant_id, campaign_id=campaign_id)
    assert card.phase == "writing"
    _stub_model(monkeypatch, raw)
    return await worker.write_campaign_whatsapp_follow_up(
        {}, {"tenant_id": str(t.tenant_id), "campaign_id": str(campaign_id)}
    )


async def _card(t: Tenant, campaign_id: UUID) -> cw.Card:
    async with tenant_session(t.tenant_id) as session:
        return await cw.card(session, campaign_id)


async def _approve(t: Tenant) -> None:
    async with tenant_session(t.tenant_id) as session:
        await session.execute(text("UPDATE whatsapp_templates SET status = 'approved'"))


async def test_without_whatsapp_the_card_says_so_and_nothing_is_made(no_whatsapp: None) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)

    assert (await _card(t, campaign_id)).phase == "not_connected"
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(t.tenant_id) as session:
            await cw.set_up(session, tenant_id=t.tenant_id, campaign_id=campaign_id)
    assert refused.value.code == "whatsapp_not_connected"
    async with tenant_session(t.tenant_id) as session:
        made = (await session.execute(text("SELECT count(*) FROM follow_ups"))).scalar()
        state = (
            await session.execute(
                text("SELECT whatsapp_follow_up_state FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).scalar()
    assert made == 0
    assert state is None


async def test_the_pass_makes_a_draft_scoped_to_this_campaign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)
    await _connect(t, monkeypatch)

    assert await _set_up_and_write(t, campaign_id, monkeypatch, GROUNDED) == "made"

    card = await _card(t, campaign_id)
    assert card.phase == "made"
    assert card.made is not None
    assert card.made.status == "draft"
    assert card.made.message == GROUNDED["message"]
    assert card.made.message_status == "pending"
    # The platform's "did not finish" and the campaign's own "asked for details"; a key the
    # campaign does not have is dropped.
    assert [o.key for o in card.made.outcomes] == ["hung_up_early", "wants_details"]
    assert [o.label for o in card.made.outcomes] == ["Hung up early", "Wants details"]
    async with tenant_session(t.tenant_id) as session:
        row = await service.get(session, card.made.id)
        stored = (
            await session.execute(
                text(
                    "SELECT f.campaign_id, f.starter, t.language, t.category, t.origin "
                    "FROM follow_ups f, whatsapp_templates t WHERE f.id = :f"
                ),
                {"f": card.made.id},
            )
        ).one()
    assert isinstance(row.trigger, d.CallEndedTrigger)
    assert row.trigger.campaign_ids == [campaign_id]
    assert row.trigger.calls == "outbound"
    assert row.settings.again == "never"
    assert [s.kind for s in row.steps] == ["wait", "whatsapp"]
    assert UUID(str(stored[0])) == campaign_id
    assert tuple(stored[1:]) == ("campaign_whatsapp", "en", "MARKETING", "client")


async def test_a_message_not_grounded_in_the_campaign_is_never_sent_for_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)
    await _connect(t, monkeypatch)
    invented = {**GROUNDED, "quote": "Fifty percent off this week only"}

    assert await _set_up_and_write(t, campaign_id, monkeypatch, invented) == (
        f"assist_{PROVIDER_UNAVAILABLE_REASON}"
    )

    card = await _card(t, campaign_id)
    assert card.phase == "failed"
    assert card.failure == cw.FAILURES["not_written"]
    async with tenant_session(t.tenant_id) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM whatsapp_templates"))
        ).scalar() == 0
        assert (await session.execute(text("SELECT count(*) FROM follow_ups"))).scalar() == 0


def test_only_an_answer_that_failed_its_checks_asks_for_more_detail() -> None:
    nobody = assist_unavailable(
        AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
    )
    paid = [PaidTurn(usage=None, capability=AssistCapability(available=True))]
    used_up = assist_unavailable(AssistCapability(available=False, reason=QUOTA_EXHAUSTED_REASON))
    unusable = ProblemError.business_rule(ANSWER_UNUSABLE_CODE, "Unusable.")
    assert worker.failure_of(nobody) == "unavailable", "no model answered: try again"
    assert worker.failure_of(SpentRefusalError(nobody, paid)) == "not_written"
    assert worker.failure_of(unusable) == "not_written"
    assert worker.failure_of(used_up) == "allowance"
    assert cw.FAILURES["allowance"] != cw.FAILURES["not_written"]


def test_a_figure_or_blank_the_material_lacks_is_refused() -> None:
    campaign = worker.Campaign(
        id=uuid.uuid4(),
        name="x",
        main_task=MAIN_TASK,
        aims="",
        classification="service",
        language="en",
        language_label="English",
        outcomes=(),
        source_ids=(),
    )
    material = MAIN_TASK
    base = {"quote": "Install it from Play Store", "outcomes": []}
    assert worker.accepted(
        {**base, "message": "Install it today."}, campaign=campaign, material=material
    )
    assert not worker.accepted(
        {**base, "message": "Install it for 99 rupees."}, campaign=campaign, material=material
    )
    assert not worker.accepted(
        {**base, "message": "Hello {{1}}, install it."}, campaign=campaign, material=material
    )


async def test_nothing_starts_until_the_owner_turns_it_on_after_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)
    other_campaign = await _campaign(t)
    await _connect(t, monkeypatch)
    await _set_up_and_write(t, campaign_id, monkeypatch, GROUNDED)
    lead_id = await _lead(t)
    phone = "+919800000123"

    async def ended_call(campaign: UUID) -> UUID:
        call_id = await _call(
            t.tenant_id,
            t.agent_id,
            lead_id=lead_id,
            phone=phone,
            direction="outbound",
            outcome="hung_up_early",
        )
        async with tenant_session(t.tenant_id) as session:
            await session.execute(
                text("UPDATE calls SET campaign_id = :c WHERE id = :id"),
                {"c": campaign, "id": call_id},
            )
        return call_id

    async def starts(call_id: UUID) -> list[UUID]:
        async with tenant_session(t.tenant_id) as session:
            return await runner.start_for_call(session, tenant_id=t.tenant_id, call_id=call_id)

    assert await starts(await ended_call(campaign_id)) == []

    with pytest.raises(ProblemError) as refused:
        async with tenant_session(t.tenant_id) as session:
            await cw.switch(
                session, tenant_id=t.tenant_id, campaign_id=campaign_id, on=True, user_id=None
            )
    assert refused.value.code == "whatsapp_message_in_review"

    await _approve(t)
    async with tenant_session(t.tenant_id) as session:
        card = await cw.switch(
            session, tenant_id=t.tenant_id, campaign_id=campaign_id, on=True, user_id=None
        )
    assert card.made is not None
    assert card.made.status == "live"

    assert await starts(await ended_call(other_campaign)) == []
    assert len(await starts(await ended_call(campaign_id))) == 1

    async with tenant_session(t.tenant_id) as session:
        card = await cw.switch(
            session, tenant_id=t.tenant_id, campaign_id=campaign_id, on=False, user_id=None
        )
    assert card.made is not None
    assert card.made.status == "off"


async def test_a_second_press_reuses_the_follow_up(monkeypatch: pytest.MonkeyPatch) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)
    await _connect(t, monkeypatch)
    await _set_up_and_write(t, campaign_id, monkeypatch, GROUNDED)
    first = (await _card(t, campaign_id)).made
    assert first is not None

    async with tenant_session(t.tenant_id) as session:
        again = await cw.set_up(session, tenant_id=t.tenant_id, campaign_id=campaign_id)
        # A twin pass (a double press that slipped past) cannot make a second row either.
        result = await cw.install(
            session,
            tenant_id=t.tenant_id,
            campaign_id=campaign_id,
            name="x",
            body="Install it from Play Store today.",
            language="en",
            category="UTILITY",
            outcomes=[],
            user_id=None,
        )
        count = (await session.execute(text("SELECT count(*) FROM follow_ups"))).scalar()
    assert again.phase == "made"
    assert again.made is not None
    assert again.made.id == first.id
    assert result == "made"
    assert count == 1


async def test_a_turned_down_message_is_written_again_into_the_same_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)
    await _connect(t, monkeypatch)
    await _set_up_and_write(t, campaign_id, monkeypatch, GROUNDED)
    first = (await _card(t, campaign_id)).made
    assert first is not None
    async with tenant_session(t.tenant_id) as session:
        await session.execute(text("UPDATE whatsapp_templates SET status = 'rejected'"))

    assert await _set_up_and_write(t, campaign_id, monkeypatch, GROUNDED) == "made"

    second = (await _card(t, campaign_id)).made
    assert second is not None
    assert second.id == first.id
    assert second.message_status == "pending"


async def test_another_account_sees_none_of_it(monkeypatch: pytest.MonkeyPatch) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)
    await _connect(t, monkeypatch)
    await _set_up_and_write(t, campaign_id, monkeypatch, GROUNDED)
    other = await _tenant()

    async with tenant_session(other.tenant_id) as session:
        assert (await session.execute(text("SELECT count(*) FROM follow_ups"))).scalar() == 0
        assert await cw.made_id(session, campaign_id) is None
    async with _client() as client:
        seen = await client.get(
            f"/v1/campaigns/{campaign_id}/whatsapp-follow-up", headers=other.headers
        )
        mine = await client.get(
            f"/v1/campaigns/{campaign_id}/whatsapp-follow-up", headers=t.headers
        )
    assert seen.status_code == 404
    assert mine.status_code == 200
    assert mine.json()["phase"] == "made"
    assert mine.json()["made"]["message"] == GROUNDED["message"]


async def test_the_routes_refuse_without_whatsapp_and_switch_on_and_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)
    url = f"/v1/campaigns/{campaign_id}/whatsapp-follow-up"

    async def none(_session: Any) -> None:
        return None

    monkeypatch.setattr(swipe, "connected_account", none)
    async with _client() as client:
        refused = await client.post(url, headers=t.headers)
    assert refused.json()["type"].endswith("/whatsapp_not_connected")

    await _connect(t, monkeypatch)
    async with _client() as client:
        pressed = await client.post(url, headers=t.headers)
    assert pressed.status_code == 200
    assert pressed.json()["phase"] == "writing"
    _stub_model(monkeypatch, GROUNDED)
    await worker.write_campaign_whatsapp_follow_up(
        {}, {"tenant_id": str(t.tenant_id), "campaign_id": str(campaign_id)}
    )
    await _approve(t)
    async with _client() as client:
        on = await client.post(f"{url}/switch", json={"on": True}, headers=t.headers)
        off = await client.post(f"{url}/switch", json={"on": False}, headers=t.headers)
    assert on.status_code == 200
    assert on.json()["made"]["status"] == "live"
    assert off.json()["made"]["status"] == "off"


async def test_pips_tool_sets_it_up_through_the_same_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = await _tenant()
    campaign_id = await _campaign(t)
    args = json.dumps({"campaign_id": str(campaign_id)})

    async def none(_session: Any) -> None:
        return None

    monkeypatch.setattr(swipe, "connected_account", none)
    with pytest.raises(WriteRefusedError):
        await write_tools.plan_write("follow_up_campaign_whatsapp", args, actor=_actor(t))

    await _connect(t, monkeypatch)
    proposal = await write_tools.plan_write("follow_up_campaign_whatsapp", args, actor=_actor(t))
    await _done(t, proposal)

    card = await _card(t, campaign_id)
    assert card.phase == "writing"
    _stub_model(monkeypatch, GROUNDED)
    await worker.write_campaign_whatsapp_follow_up(
        {}, {"tenant_id": str(t.tenant_id), "campaign_id": str(campaign_id)}
    )
    made = (await _card(t, campaign_id)).made
    assert made is not None
    assert made.status == "draft"
    with pytest.raises(WriteRefusedError):
        await write_tools.plan_write("follow_up_campaign_whatsapp", args, actor=_actor(t))
