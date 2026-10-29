"""D-935: Pip's troubleshoot mode. Each question family, on a seeded failure, names the right
first cause and fix; it writes nothing; it cannot see a neighbour's rows; and the panel gets
the checklist on the step frame. Every test mints its own tenant."""

from __future__ import annotations

import inspect
import json
import re
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import diagnostics, service, tools
from apps.api.copilot.screens import CLIENT_SCREENS
from apps.api.db.session import tenant_session
from apps.api.ops.service import HaltState
from apps.workers import chat


@pytest.fixture
def paid_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wallet is not what these tests are about; `credit_test` asks it on its own."""

    async def _never(*_a: Any, **_k: Any) -> bool:
        return False

    monkeypatch.setattr("apps.api.compliance.service.credits_exhausted", _never)


async def _agent(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        return UUID(str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()))


async def _diagnose(name: str, tenant_id: UUID, role: str = "owner", **args: Any) -> str:
    return await tools.run_read_tool(
        name,
        json.dumps(args),
        context=tools.ToolContext(tenant_id=tenant_id, role=role),
        registry=service._read_tool_registry("client"),
    )


def _dx(result: str) -> diagnostics.Diagnosis:
    assert isinstance(result, diagnostics.DiagnosisText), result
    return result.diagnosis


def _cause(result: str) -> diagnostics.Check:
    cause = _dx(result).cause
    assert cause is not None, result
    return cause


async def _call(tenant_id: UUID, *, direction: str, status: str, summary: str = "ready") -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "summary_state, to_e164, started_at, created_at, updated_at) "
                "SELECT :id, :t, id, :e, :d, :s, :sum, :to, now(), now(), now() "
                "FROM agents LIMIT 1"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "e": f"dx-{uuid.uuid4().hex}",
                "d": direction,
                "s": status,
                "sum": summary,
                "to": f"+9198{uuid.uuid4().int % 100000000:08d}",
            },
        )
    return call_id


async def _campaign(tenant_id: UUID, status: str) -> UUID:
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'outbound'"),
        )
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status, "
                "created_at, updated_at) SELECT :id, :t, id, 'Diwali offer', 'service', :s, "
                "now(), now() FROM agents LIMIT 1"
            ),
            {"id": campaign_id, "t": tenant_id, "s": status},
        )
    return campaign_id


# --- the families --------------------------------------------------------------------------


@pytest.mark.usefixtures("paid_up")
async def test_an_agent_with_no_number_is_told_to_attach_one() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    result = await _diagnose("agent_diagnose", tenant_id, agent_id=str(await _agent(tenant_id)))
    cause = _cause(result)
    assert cause.key == "number"
    assert cause.detail == "No phone number is attached to Reception."
    assert cause.fix is not None and cause.fix.ask == "Attach a phone number to Reception"
    # Every check before the cause passed: the order is the diagnosis.
    keys = [check.key for check in _dx(result).checks]
    assert keys[: keys.index("number")] == ["agent", "credit", "silence", "workspace"]
    before = _dx(result).checks[: keys.index("number")]
    assert all(check.status == "ok" for check in before), before


@pytest.mark.usefixtures("paid_up")
async def test_a_paused_agent_is_the_cause_before_its_number() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE agents SET status = 'paused'"))
    cause = _cause(await _diagnose("agent_diagnose", tenant_id, agent_id=str(agent_id)))
    assert (cause.key, cause.detail) == ("agent", "Reception is paused.")
    assert cause.fix is not None and cause.fix.ask == "Switch Reception back on"


async def test_an_empty_wallet_is_the_cause_and_opens_billing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _empty(*_a: Any, **_k: Any) -> bool:
        return True

    monkeypatch.setattr("apps.api.compliance.service.credits_exhausted", _empty)
    tenant_id, _slug, _token = await _make_tenant()
    cause = _cause(
        await _diagnose("agent_diagnose", tenant_id, agent_id=str(await _agent(tenant_id)))
    )
    assert cause.key == "credit"
    assert cause.fix is not None and cause.fix.screen == "Credits & billing"
    assert cause.fix.route == "/c/{slug}/billing"


async def test_an_unanswered_outbound_call_says_so() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    call_id = await _call(tenant_id, direction="outbound", status="no_answer")
    cause = _cause(await _diagnose("call_diagnose", tenant_id, call_id=str(call_id)))
    assert (cause.key, cause.detail) == ("record", "They did not pick up.")
    assert f"call_id {call_id}" in cause.evidence


async def test_a_completed_call_whose_summary_failed_offers_a_second_summary() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    call_id = await _call(tenant_id, direction="inbound", status="completed", summary="failed")
    result = await _diagnose("call_diagnose", tenant_id, call_id=str(call_id))
    cause = _cause(result)
    assert cause.key == "summary"
    assert cause.fix is not None and cause.fix.ask == "Summarise this call again"
    # An inbound call is not asked the outbound gates.
    assert "platform" not in [check.key for check in _dx(result).checks]


async def test_a_draft_campaign_has_not_been_launched() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, "draft")
    cause = _cause(await _diagnose("campaign_diagnose", tenant_id, campaign_id=str(campaign_id)))
    assert (cause.key, cause.detail) == ("state", "Diwali offer has not been launched.")
    assert cause.fix is not None and cause.fix.ask == "Launch the campaign Diwali offer"


async def test_the_big_red_switch_explains_a_paused_campaign_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _halted(_session: Any) -> HaltState:
        return HaltState(outbound_halted=True, reason="incident")

    monkeypatch.setattr("apps.api.ops.service.read_halt_state", _halted)
    tenant_id, _slug, _token = await _make_tenant()
    campaign_id = await _campaign(tenant_id, "paused")
    result = await _diagnose("campaign_diagnose", tenant_id, campaign_id=str(campaign_id))
    cause = _cause(result)
    assert cause.key == "platform_halt"
    assert cause.fix is None  # an operator's switch: nothing for the client to press
    # The pause is still on the card, after the cause.
    assert any(c.key == "state" and c.status == "problem" for c in _dx(result).checks)


async def test_no_sheet_connection_points_at_integrations() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    result = await _diagnose("delivery_diagnose", tenant_id, channel="sheet", call_id=None)
    cause = _cause(result)
    assert cause.key == "connected"
    assert cause.detail == "Nothing sends leads to your Google Sheet yet."
    assert cause.fix is not None and cause.fix.screen == "Integrations"
    # No call named is an unknown, not a guess.
    this_call = next(c for c in _dx(result).checks if c.key == "this_call")
    assert this_call.status == "unknown"


async def test_no_whatsapp_contact_points_at_alerts() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    cause = _cause(
        await _diagnose("delivery_diagnose", tenant_id, channel="whatsapp", call_id=None)
    )
    assert cause.key == "connected"
    assert cause.fix is not None and cause.fix.screen == "Alerts"


async def test_an_account_with_no_knowledge_is_told_to_add_some() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    result = await _diagnose("knowledge_diagnose", tenant_id, agent_id=None)
    cause = _cause(result)
    assert cause.key == "added"
    assert cause.fix is not None and cause.fix.screen == "What your agents know"
    on_agent = next(c for c in _dx(result).checks if c.key == "on_agent")
    assert on_agent.status == "unknown"


async def test_a_bad_id_is_a_sentence_the_model_can_act_on() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    for name, key in (
        ("agent_diagnose", "agent_id"),
        ("call_diagnose", "call_id"),
        ("campaign_diagnose", "campaign_id"),
    ):
        result = await _diagnose(name, tenant_id, **{key: "not-an-id"})
        assert f"`{key}` was missing" in result, name
    assert "`channel` must be one of" in await _diagnose(
        "delivery_diagnose", tenant_id, channel="fax", call_id=None
    )


# --- isolation, reads only, permissions -------------------------------------------------------


@pytest.mark.usefixtures("paid_up")
async def test_a_neighbours_objects_are_invisible() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    other_id, _s, _t = await _make_tenant()
    other_call = await _call(other_id, direction="outbound", status="no_answer")
    other_campaign = await _campaign(other_id, "draft")
    agent = _cause(
        await _diagnose("agent_diagnose", tenant_id, agent_id=str(await _agent(other_id)))
    )
    assert (agent.key, agent.detail) == ("agent", "That agent has been deleted.")
    call = _cause(await _diagnose("call_diagnose", tenant_id, call_id=str(other_call)))
    assert call.detail == "No call with that id in this account."
    campaign = _cause(
        await _diagnose("campaign_diagnose", tenant_id, campaign_id=str(other_campaign))
    )
    assert campaign.detail == "No campaign with that id in this account."


def test_the_module_never_writes() -> None:
    source = inspect.getsource(diagnostics).lower()
    for verb in ("insert into", "update ", "delete from", "session.add", "commit(", "flush("):
        assert not re.search(rf"\b{re.escape(verb)}", source), verb


@pytest.mark.usefixtures("paid_up")
async def test_running_every_family_leaves_the_tenant_unchanged() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    call_id = await _call(tenant_id, direction="outbound", status="busy")
    campaign_id = await _campaign(tenant_id, "draft")

    async def snapshot() -> list[Any]:
        async with tenant_session(tenant_id) as session:
            return [
                (
                    await session.execute(text(f"SELECT md5(string_agg(t::text, '')) FROM {t} t"))
                ).scalar()
                for t in ("agents", "calls", "campaigns", "leads", "organizations")
            ]

    before = await snapshot()
    await _diagnose("agent_diagnose", tenant_id, agent_id=str(agent_id))
    await _diagnose("call_diagnose", tenant_id, call_id=str(call_id))
    await _diagnose("campaign_diagnose", tenant_id, campaign_id=str(campaign_id))
    for channel in diagnostics.CHANNELS:
        await _diagnose("delivery_diagnose", tenant_id, channel=channel, call_id=str(call_id))
    await _diagnose("knowledge_diagnose", tenant_id, agent_id=str(agent_id))
    assert await snapshot() == before


async def test_the_screen_permission_holds() -> None:
    """`calls:read` is the call screen's; a role without it is refused before anything runs."""
    tenant_id, _slug, _token = await _make_tenant()
    result = await _diagnose("call_diagnose", tenant_id, role="nobody", call_id=str(uuid.uuid4()))
    assert result.startswith("Refused")


def test_every_fix_screen_is_in_the_console_inventory() -> None:
    names = {screen.name for screen in CLIENT_SCREENS}
    for _prefix, _label, screen in diagnostics._RULE_SCREENS:
        assert screen in names
    source = inspect.getsource(diagnostics)
    for screen in re.findall(r'screen_fix\(\s*"[^"]+",\s*"([^"]+)"', source):
        assert screen in names, screen


async def test_a_failed_check_is_unknown_and_the_rest_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _broken(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("wallet unreachable")

    monkeypatch.setattr("apps.api.compliance.service.credits_exhausted", _broken)
    tenant_id, _slug, _token = await _make_tenant()
    result = await _diagnose("agent_diagnose", tenant_id, agent_id=str(await _agent(tenant_id)))
    assert isinstance(result, diagnostics.DiagnosisText)
    credit = next(c for c in _dx(result).checks if c.key == "credit")
    assert credit.status == "unknown"
    assert _cause(result).key == "number"


# --- the panel and the admin twin -----------------------------------------------------------


@pytest.mark.usefixtures("paid_up")
async def test_the_step_frame_carries_the_checklist() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    call = chat.ToolCall(
        id="d1", name="agent_diagnose", arguments=json.dumps({"agent_id": str(agent_id)})
    )
    frame, result = await service._run_one_read_tool(
        call,
        context=tools.ToolContext(tenant_id=tenant_id, role="owner"),
        registry=service._read_tool_registry("client"),
    )
    assert frame.diagnosis is not None
    assert frame.diagnosis.family == "agent"
    assert frame.detail == "No phone number is attached to Reception."
    first = next(c for c in frame.diagnosis.checks if c.status == "problem")
    assert first.key == "number" and first.fix is not None
    assert "No phone number is attached to Reception." in result
    # The model is told to answer in one line, from what is listed.
    assert "one short line" in result


@pytest.mark.usefixtures("paid_up")
async def test_an_operator_diagnoses_the_open_client_with_platform_checks_first() -> None:
    tenant_id, slug, _token = await _make_tenant()
    agent_id = await _agent(tenant_id)
    by_page = await tools.run_read_tool(
        "admin_diagnose",
        json.dumps({"client": None, "question": "agent", "id": str(agent_id)}),
        context=tools.ToolContext(tenant_id=tenant_id, role="superadmin"),
        registry=service._read_tool_registry("admin"),
    )
    assert isinstance(by_page, diagnostics.DiagnosisText)
    keys = [check.key for check in _dx(by_page).checks]
    assert keys[:3] == ["vendor", "outbox", "workspace"]
    assert "number" in keys
    by_slug = await tools.run_read_tool(
        "admin_diagnose",
        json.dumps({"client": slug, "question": "whatsapp", "id": None}),
        context=tools.ToolContext(tenant_id=None, role="superadmin"),
        registry=service._read_tool_registry("admin"),
    )
    assert isinstance(by_slug, diagnostics.DiagnosisText)
    assert _dx(by_slug).family == "delivery"
    nobody = await tools.run_read_tool(
        "admin_diagnose",
        json.dumps({"client": None, "question": "agent", "id": None}),
        context=tools.ToolContext(tenant_id=None, role="superadmin"),
        registry=service._read_tool_registry("admin"),
    )
    assert nobody.startswith("Name the client")


async def test_a_client_cannot_reach_the_admin_twin() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    result = await _diagnose("admin_diagnose", tenant_id, question="agent")
    assert result.startswith("There is no tool called")
