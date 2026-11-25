"""D-1045 (founder, 25 Nov 2026): a campaign's or line's screen frame and its silence question
follow its own script, and a campaign's test call carries the tester's name.

1. A holder whose script asks the caller to act on their phone gets the screen frame (our
   screen call rules, the screen steps, short words held) whatever its agent's switch says;
   one that does not, loses it. A raw script, or none, keeps the agent's switch.
2. "Can you see it?" is the silence question only on such a holder; a holder carrying "Give
   callers time" by the owner's choice on a booking script keeps the ordinary question.
3. A campaign's test call is placed with the tester's own name as `lead_name` when the
   campaign's list carries names; never a name holding a digit, and none from an empty list.
   It only fills `{{lead_name}}`: no contact is filed under it at the engine.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.agents import give_callers_time as gct
from apps.api.agents import service as agents_service
from apps.api.agents import trial_calls
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest import ThinnestEngine
from calevate_shared.call_script import CallScript
from calevate_shared.engine import (
    CALL_INSTRUCTIONS,
    CallContext,
    SCREEN_CALL_INSTRUCTIONS,
    AgentConfig,
    call_instructions,
    compose_engine_prompt,
    screen_steps_bullet,
    sends_our_call_rules,
)
from sqlalchemy import text
from tests.campaign_engine_agents_test import _campaign
from tests.decisions_2026_11_25_test import BOOKING, GUIDED, _campaign_config, _line_config
from tests.notes_per_job_test import _campaign as _dlt_campaign
from tests.notes_per_job_test import _line
from tests.thinnest_engine_test import _agent_with_greeting, _body, _engine, _recorder
from tests.thinnest_publish_limits_test import _agent_with_script
from tests.trial_call_placement_test import Line, line  # noqa: F401
from tests.workspace_slots_test import (
    SCRIPT,
    _client_workspace,
    _fill,
    _paid_with_own_number,
    _workspace,
)

pytestmark = pytest.mark.anyio

RAW = CallScript(raw_override="Greet them, then walk them through installing the app.")


# --- 1. The screen frame per holder -----------------------------------------------------------


def test_the_holders_script_decides_and_a_raw_or_missing_one_keeps_the_agents_switch() -> None:
    assert gct.holder_has_screen(GUIDED, agent_switch=False)
    assert not gct.holder_has_screen(BOOKING, agent_switch=True)
    assert gct.holder_has_screen(RAW, agent_switch=True)
    assert not gct.holder_has_screen(RAW, agent_switch=False)
    assert gct.holder_has_screen(None, agent_switch=True)


def test_the_holder_row_carries_the_scripts_frame_apart_from_the_preset() -> None:
    row: dict[str, Any] = {"caller_has_screen": True, "max_call_duration_s": 300}
    booked = gct.holder_row(row, owner_choice=True, script=BOOKING)
    assert booked["caller_has_screen"] is False
    assert booked[gct.HOLDER_ROW_KEY] is True
    guided = gct.holder_row({"caller_has_screen": False}, owner_choice=False, script=GUIDED)
    assert guided["caller_has_screen"] is True
    assert gct.HOLDER_ROW_KEY not in guided
    assert row["caller_has_screen"] is True, "the agent's row is never written"


def _held(config: AgentConfig) -> dict[str, Any]:
    return ThinnestEngine(api_key="ta_live_test")._agent_body(config)


def _screen_frame(config: AgentConfig) -> None:
    assert config.caller_has_screen
    assert call_instructions(config) == SCREEN_CALL_INSTRUCTIONS
    assert sends_our_call_rules(config)
    assert screen_steps_bullet(config.language_primary) in compose_engine_prompt(config)
    assert _held(config)["voice"]["holdShortSpeech"] is False


def _no_screen_frame(config: AgentConfig) -> None:
    assert not config.caller_has_screen
    assert call_instructions(config) == CALL_INSTRUCTIONS
    assert screen_steps_bullet(config.language_primary) not in compose_engine_prompt(config)
    assert _held(config)["voice"]["holdShortSpeech"] is True


async def _agent_switch(tenant_id: UUID, agent_id: UUID, *, on: bool) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_has_screen = :on WHERE id = :a"),
            {"on": on, "a": agent_id},
        )


async def test_a_guided_holder_on_an_agent_switched_off_speaks_to_a_screen() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    tid, aid = UUID(str(tenant_id)), UUID(str(agent_id))
    campaign_id = await _dlt_campaign(tid, aid)
    line_id = await _line(tid, aid)
    _screen_frame(await _campaign_config(tid, campaign_id, GUIDED))
    _screen_frame(await _line_config(tid, line_id, GUIDED))
    _no_screen_frame(await _campaign_config(tid, campaign_id, BOOKING))

    await _agent_switch(tid, aid, on=True)
    _no_screen_frame(await _campaign_config(tid, campaign_id, BOOKING))
    _no_screen_frame(await _line_config(tid, line_id, BOOKING))
    _screen_frame(await _line_config(tid, line_id, RAW))


# --- 2. "Can you see it?" only where it fits --------------------------------------------------


async def test_the_screen_question_is_asked_only_on_a_guided_holder() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    tid, aid = UUID(str(tenant_id)), UUID(str(agent_id))
    line_id = await _line(tid, aid)
    guided = await _line_config(tid, line_id, GUIDED)
    phrase = gct.NUDGE_PHRASES.get(guided.language_primary)
    assert phrase, "the founder's line exists for the agent's language"
    assert guided.nudge_phrase == phrase

    async with tenant_session(tid) as session:
        await session.execute(
            text("UPDATE inbound_lines SET give_callers_time = true WHERE id = :l"), {"l": line_id}
        )
    booked = await _line_config(tid, line_id, BOOKING)
    assert booked.nudge_after_seconds == gct.NUDGE_AFTER_S, "the preset is still on"
    assert booked.nudge_phrase != phrase
    assert booked.nudge_phrase == (
        agents_service.platform_nudge_phrase([booked.language_primary, *booked.languages_extra])
        or None
    )


# --- 3. A campaign's test call carries the tester's name --------------------------------------


async def _user(name: str | None) -> UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, :name, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com", "name": name},
        )
    return user_id


async def _contact(tenant_id: UUID, campaign_id: UUID, name: str | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, name, "
                "created_at, updated_at) VALUES (:id, :t, :c, :p, :n, now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "c": campaign_id,
                "p": f"+9198{uuid.uuid4().int % 100000000:08d}",
                "n": name,
            },
        )


async def _name_for(tenant_id: UUID, campaign_id: UUID, principal: Principal) -> str | None:
    async with tenant_session(tenant_id) as session:
        return await trial_calls._tester_name(session, principal=principal, campaign_id=campaign_id)


async def test_the_testers_name_is_used_only_where_the_list_carries_names() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    tid, aid = UUID(str(tenant_id)), UUID(str(agent_id))
    campaign_id = await _dlt_campaign(tid, aid)

    def client(user_id: UUID) -> Principal:
        return Principal(realm="client", user_id=user_id, tenant_id=tid, role="owner")

    named = await _user("  Umesh   Kumar ")
    await _contact(tid, campaign_id, None)
    assert await _name_for(tid, campaign_id, client(named)) is None, "no name on the list"
    await _contact(tid, campaign_id, "Lakshmi")
    assert await _name_for(tid, campaign_id, client(named)) == "Umesh Kumar"
    assert await _name_for(tid, campaign_id, client(await _user(None))) is None
    assert await _name_for(tid, campaign_id, client(await _user("+91 98765 43210"))) is None
    admin = Principal(realm="admin", user_id=named, tenant_id=tid, role="operator")
    assert await _name_for(tid, campaign_id, admin) is None


async def test_a_campaigns_test_call_is_placed_with_the_testers_name(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal = await _paid_with_own_number(line, monkeypatch)
    workspace = _workspace()
    _client_workspace(monkeypatch, workspace)
    await _fill(tenant_id, agent_id, workspace)
    campaign_id = await _campaign(tenant_id, agent_id, script=SCRIPT)
    await _contact(tenant_id, campaign_id, "Lakshmi")
    tester = Principal(
        realm="client", user_id=await _user("Umesh"), tenant_id=tenant_id, role="owner"
    )
    del principal

    sent: list[CallContext] = []
    real = FakeEngine.start_outbound_call

    async def recording(self: FakeEngine, ref: str, to: str, ctx: CallContext) -> Any:
        sent.append(ctx)
        return await real(self, ref, to, ctx)

    monkeypatch.setattr(FakeEngine, "start_outbound_call", recording)
    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=tester,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            campaign_id=campaign_id,
        )
    assert placed.status == "queued", placed
    assert [(c.lead_name, c.lead_name_files_contact) for c in sent] == [("Umesh", False)]


async def test_a_test_calls_name_fills_the_variable_and_files_no_contact() -> None:
    handler, seen = _recorder(
        {
            ("GET", "/agents/ag_1"): _agent_with_greeting("Namaskaram {{lead_name}} garu."),
            ("POST", "/calls"): httpx.Response(202, json={"id": "out_1", "status": "ringing"}),
        }
    )
    ctx = CallContext(lead_name="Umesh", lead_name_files_contact=False)
    await _engine(handler).start_outbound_call("ag_1", "+919876543210", ctx)
    body = _body(seen[-1])
    assert body["variables"]["lead_name"] == "Umesh"
    assert "name" not in body, "no contact is filed under the tester's name"
