"""How long a waiting opening waits, and an operator's per-agent turn detection (D-901).

`voice.openingWaitSeconds` is sent only with `openingWaitsForCaller` on and only once the
console's `thinnest_opening_wait_ms` is set; it inherits agent -> account -> console like the
other call settings and is drift-checked under `opening_waits_for_caller`. `agents.
turn_detection` puts one agent on its own mode over the console's.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from apps.api.agents import prompts
from apps.api.agents.call_handling import (
    CallSettings,
    refuse_invalid_settings,
    resolve_settings,
)
from apps.api.agents.service import _call_settings_fields, _load_agent, _to_config
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import thinnest
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.ops.config_service import validated_value
from sqlalchemy import text
from tests.call_handling_test import _client, _make_live, _operator, _runs, _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import WS, _cfg, tools_state

pytestmark = [pytest.mark.rls]

AGENT = f"ag_1@{WS}"


@pytest.fixture
def console_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """The console's wait set, as the founder will set it on 28 Oct 2026."""
    monkeypatch.setattr(get_settings(), "thinnest_opening_wait_ms", 1500)


def _voice(**update: object) -> dict[str, Any]:
    voice: dict[str, Any] = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(**update))[
        "voice"
    ]
    return voice


# --- the wire -----------------------------------------------------------------------------


def test_sent_in_seconds_only_beside_the_switch() -> None:
    assert _voice(opening_waits_for_caller=True, opening_wait_ms=1500)["openingWaitSeconds"] == 1.5
    # Never null: the field means nothing without the switch, and an unknown field could
    # refuse the write before the vendor accepts it.
    assert "openingWaitSeconds" not in _voice(opening_waits_for_caller=False, opening_wait_ms=1500)
    assert "openingWaitSeconds" not in _voice(opening_waits_for_caller=True)
    assert "opening_wait_ms" not in _cfg(opening_wait_ms=1500).model_dump()


async def test_a_console_change_is_drift_and_repair_sends_both_fields() -> None:
    cfg = _cfg(opening_waits_for_caller=True, opening_wait_ms=1500)
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    held = {**wanted, "voice": {**wanted["voice"], "openingWaitSeconds": None}}
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state(engine.built_in_tools_body(cfg)))
        if request.method == "GET":
            return httpx.Response(200, json=held)
        sent.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={})

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )
    drifted = await engine.settings_drift(AGENT, cfg)
    assert drifted == ["opening_wait"]
    await engine.repair_settings(AGENT, cfg, drifted)
    assert sent == [{"voice": {"openingWaitsForCaller": True, "openingWaitSeconds": 1.5}}]
    # `1.50` read back is the same wait; an unstated wait is not compared.
    same = {**wanted, "voice": {**wanted["voice"], "openingWaitSeconds": 1.50}}
    assert thinnest._settings_drift(wanted, same) == []
    unstated = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg())
    vendor_set = {**unstated, "voice": {**unstated["voice"], "openingWaitSeconds": 2}}
    assert thinnest._settings_drift(unstated, vendor_set) == []


# --- the console --------------------------------------------------------------------------


def test_the_console_starts_unset_takes_tenths_and_republishes() -> None:
    assert get_settings().thinnest_opening_wait_ms is None
    assert validated_value("thinnest_opening_wait_ms", 1500) == 1500
    for bad in (400, 1550, 10_100):
        with pytest.raises(ProblemError):
            validated_value("thinnest_opening_wait_ms", bad)
    assert applies_rule("thinnest_opening_wait_ms").applies == LIVE_AGENTS


# --- resolution and refusals --------------------------------------------------------------


def test_unset_console_refuses_any_wait_and_resolves_to_not_sent() -> None:
    with pytest.raises(ProblemError) as refused:
        refuse_invalid_settings(CallSettings(opening_wait_ms=1500))
    assert refused.value.code == "opening_wait_unavailable"
    refuse_invalid_settings(CallSettings(opening_wait_ms=None))
    resolved = resolve_settings(CallSettings(), CallSettings())
    assert (resolved.values.opening_wait_ms, resolved.sources["opening_wait_ms"]) == (
        None,
        "platform",
    )


@pytest.mark.usefixtures("console_wait")
def test_the_console_is_calevates_level_and_each_level_above_wins() -> None:
    assert resolve_settings(CallSettings(), CallSettings()).values.opening_wait_ms == 1500
    account = CallSettings(opening_wait_ms=2000)
    assert resolve_settings(CallSettings(), account).sources["opening_wait_ms"] == "organization"
    own = resolve_settings(CallSettings(opening_wait_ms=800), account)
    assert (own.values.opening_wait_ms, own.sources["opening_wait_ms"]) == (800, "agent")
    for bad in (400, 1550, 10_100):
        with pytest.raises(ProblemError) as refused:
            refuse_invalid_settings(CallSettings(opening_wait_ms=bad))
        assert refused.value.code == "call_setting_out_of_range"


def test_publish_sends_nothing_while_the_console_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wait left on a row after the console was cleared is not sent either."""
    row: Any = {"call_settings": CallSettings(opening_wait_ms=800)}
    assert _call_settings_fields(row, languages=("te-IN",))["opening_wait_ms"] is None
    monkeypatch.setattr(get_settings(), "thinnest_opening_wait_ms", 1500)
    assert _call_settings_fields(row, languages=("te-IN",))["opening_wait_ms"] == 800


# --- the routes ---------------------------------------------------------------------------


async def test_the_owner_cannot_set_a_wait_before_the_console_offers_one() -> None:
    _tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        read = await client.get(f"/v1/agents/{agent_id}/call-handling", headers=headers)
        write = await client.patch(
            f"/v1/agents/{agent_id}/call-handling", headers=headers, json={"opening_wait_ms": 1500}
        )
    assert read.status_code == 200, read.text
    bounds = read.json()["bounds"]
    assert (bounds["opening_wait_available"], bounds["platform_opening_wait_ms"]) == (False, None)
    assert read.json()["opening_wait_ms_effective"] is None
    assert write.status_code == 422, write.text
    assert write.json()["type"].endswith("/opening_wait_unavailable")


@pytest.mark.usefixtures("console_wait")
async def test_the_owner_sets_it_for_one_agent_or_all_and_the_live_agent_follows() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    path = f"/v1/agents/{agent_id}/call-handling"
    async with _client() as client:
        before = (await client.get(path, headers=headers)).json()
        own = await client.patch(path, headers=headers, json={"opening_wait_ms": 800})
        everyone = await client.post(
            "/v1/organization/call-handling/all-agents",
            headers=headers,
            json={"opening_wait_ms": 2000},
        )
        after = (await client.get(path, headers=headers)).json()
    assert (before["opening_wait_ms_effective"], before["opening_wait_ms_source"]) == (
        1500,
        "platform",
    )
    assert before["bounds"]["opening_wait_available"] is True
    assert own.status_code == 200, own.text
    assert (own.json()["opening_wait_ms"], own.json()["opening_wait_ms_source"]) == (800, "agent")
    assert everyone.status_code == 200, everyone.text
    assert everyone.json()["agents_reset"] == 1
    assert (after["opening_wait_ms"], after["opening_wait_ms_effective"]) == (None, 2000)
    assert after["opening_wait_ms_source"] == "organization"
    # The agent's own run and the account's are one queued run by the time it is read.
    assert any("call_handling" in reasons for _scope, _aid, reasons in await _runs(tenant_id))


# --- an operator's turn detection ---------------------------------------------------------


async def test_an_operator_puts_one_agent_on_its_own_mode() -> None:
    tenant_id, agent_id, owner = await _tenant()
    await _make_live(tenant_id, agent_id)
    headers = await _operator()
    path = f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/turn-detection"
    async with _client() as client:
        before = await client.get(path, headers=headers)
        put = await client.put(path, headers=headers, json={"turn_detection": "timer"})
        bad = await client.put(path, headers=headers, json={"turn_detection": "fast"})
        client_door = await client.put(path, headers=owner, json={"turn_detection": "ear"})
    assert before.status_code == 200, before.text
    assert before.json()["turn_detection"] is None
    assert put.status_code == 200, put.text
    assert (put.json()["turn_detection"], put.json()["turn_detection_effective"]) == (
        "timer",
        "timer",
    )
    assert bad.status_code == 422, bad.text
    assert client_door.status_code in (401, 403), client_door.text
    assert ("agent", agent_id, ["turn_detection"]) in await _runs(tenant_id)
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'admin.agent_turn_detection_set'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert audited == 1


async def test_publish_uses_the_agents_mode_over_the_consoles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _headers = await _tenant()
    monkeypatch.setattr(get_settings(), "thinnest_turn_detection", "ear")
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and take their order.",
            notes=None,
            created_by=None,
        )
        console = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
        await session.execute(
            text("UPDATE agents SET turn_detection = 'timer' WHERE id = :id"), {"id": agent_id}
        )
        own = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
    assert (console.turn_detection, own.turn_detection) == ("ear", "timer")


async def test_one_client_cannot_read_anothers_agent_through_the_operators_door() -> None:
    """The admin route runs in the named tenant's session: another tenant's agent is a 404."""
    tenant_a, _agent_a, _ = await _tenant()
    _tenant_b, agent_b, _ = await _tenant()
    headers = await _operator()
    async with _client() as client:
        response = await client.put(
            f"/v1/admin/tenants/{tenant_a}/agents/{agent_b}/turn-detection",
            headers=headers,
            json={"turn_detection": "timer"},
        )
    assert response.status_code == 404, response.text
