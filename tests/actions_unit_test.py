"""ACTIONS feature — DB-free unit tests for the parts that carry the most risk: the Bolna
declaration shape (an unverified vendor envelope, gate 18), parameter binding, the external
request builders, and the executor's dispatch/opt-in/egress behaviour.

These run without Postgres by injecting a fake httpx transport and monkeypatching the two
DB-backed helpers the executor calls (`resolve_secret`, `read_messaging_consent`). The
DB-backed suite (`tests/actions_rls_test.py`, `tests/actions_routes_test.py`) proves RLS,
the credential envelope round trip and the route layer and needs a migrated database.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from apps.api.actions import execution, whatsapp
from apps.api.actions.schema import CustomApiConfig, WhatsAppConfig
from apps.api.actions.service import LoadedTool, _to_spec
from apps.api.compliance.consent import MessagingConsent
from apps.api.compliance.service import DispatchDecision
from apps.api.engine.bolna import _api_tools, _one_api_tool
from calevate_shared.engine import ActionToolParam, ActionToolSpec

# --------------------------------------------------------------- declaration ----


def _spec(**kw: Any) -> ActionToolSpec:
    base: dict[str, Any] = dict(  # noqa: C408 — kwargs form reads better beside the update
        name="get_order_status",
        description="Use when the caller asks about their order.",
        pre_call_message="Let me check that.",
        method="POST",
        url="https://api.calevate.test/v1/actions/invoke/bolna/" + str(uuid4()),
        params=(
            ActionToolParam(
                name="order_id", fill="ai", type="string", description="Order id", required=True
            ),
            ActionToolParam(name="qty", fill="ai", type="integer", description="Quantity"),
            ActionToolParam(name="caller", fill="context", context_ref="{from_number}"),
        ),
    )
    base.update(kw)
    return ActionToolSpec(**base)  # type: ignore[arg-type]


def test_one_api_tool_splits_definition_and_params_with_custom_task() -> None:
    definition, exec_params = _one_api_tool(_spec())
    # The LLM-facing definition carries only AI params, with the right JSON-schema types.
    assert definition["name"] == "get_order_status"
    assert set(definition["parameters"]["properties"]) == {"order_id", "qty"}
    assert definition["parameters"]["properties"]["qty"]["type"] == "integer"
    assert definition["parameters"]["required"] == ["order_id"]
    # The execution block carries the mandatory fixed key and POST, and maps EVERY param —
    # ai as a %-format specifier, context as the Bolna system variable — but no credential.
    assert exec_params["key"] == "custom_task"
    assert exec_params["method"] == "POST"
    assert exec_params["param"]["order_id"] == "%(order_id)s"
    assert exec_params["param"]["qty"] == "%(qty)i"
    assert exec_params["param"]["caller"] == "{from_number}"
    assert "api_token" not in exec_params
    assert exec_params["pre_call_message"] == "Let me check that."


def test_api_tools_envelope_is_json_string_plus_named_params() -> None:
    from calevate_shared.engine import AgentConfig, ModelConfig

    cfg = AgentConfig(
        tenant_id=str(uuid4()),
        agent_id=str(uuid4()),
        name="A",
        direction="inbound",
        system_prompt="hi",
        opening_line="",
        models=ModelConfig(),
        action_tools=(_spec(name="tool_a"), _spec(name="tool_b")),
    )
    block = _api_tools(cfg)
    assert block is not None
    # `tools` is a JSON STRING (the field's own description), decoding to the definitions;
    # `tools_params` is keyed by tool name (the OAS structure). See the gate-18 note.
    tools = json.loads(block["tools"])
    assert {t["name"] for t in tools} == {"tool_a", "tool_b"}
    assert set(block["tools_params"]) == {"tool_a", "tool_b"}


def test_no_actions_emits_no_api_tools_block() -> None:
    from calevate_shared.engine import AgentConfig, ModelConfig

    cfg = AgentConfig(
        tenant_id=str(uuid4()),
        agent_id=str(uuid4()),
        name="A",
        direction="inbound",
        system_prompt="hi",
        opening_line="",
        models=ModelConfig(),
    )
    assert _api_tools(cfg) is None


def _loaded(**kw: Any) -> LoadedTool:
    base: dict[str, Any] = dict(  # noqa: C408 — kwargs form reads better beside the update
        id=uuid4(),
        tenant_id=uuid4(),
        agent_id=uuid4(),
        kind="custom_api",
        provider=None,
        name="get_order_status",
        description="when asked about an order",
        pre_call_message=None,
        trigger="during_call",
        enabled=True,
        credential_id=None,
        config={},
        params=[],
    )
    base.update(kw)
    return LoadedTool(**base)  # type: ignore[arg-type]


def test_to_spec_resolves_caller_phone_by_direction_and_injects_agent_ref() -> None:
    params = [
        {
            "name": "order_id",
            "source": "ai",
            "type": "string",
            "description": "id",
            "required": True,
        },
        {"name": "caller", "source": "lead_var", "lead_var": "caller_phone"},
        {"name": "store", "source": "static", "value": "S1"},
    ]
    inbound = _to_spec(_loaded(params=params), engine="bolna", direction="inbound")
    outbound = _to_spec(_loaded(params=params), engine="bolna", direction="outbound")
    names = {p.name: p for p in inbound.params}
    # static param is NOT declared to the engine; ai + lead_var + the injected agent ref are.
    assert "store" not in names
    assert names["order_id"].fill == "ai"
    assert names["caller"].context_ref == "{from_number}"  # inbound: caller is from_number
    assert {p.name: p.context_ref for p in outbound.params}["caller"] == "{to_number}"
    assert names["_agent_ref"].context_ref == "{agent_id}"


# ------------------------------------------------------------- param binding ----


def test_resolve_values_applies_static_and_reads_received() -> None:
    params = [
        {"name": "store", "source": "static", "value": "S1"},
        {"name": "order_id", "source": "ai", "type": "string", "description": "id"},
        {"name": "caller", "source": "lead_var", "lead_var": "caller_phone"},
    ]
    values = execution.resolve_values(params, {"order_id": "ORD-9", "caller": "+919000000000"})
    assert values == {"store": "S1", "order_id": "ORD-9", "caller": "+919000000000"}


# ------------------------------------------------------------ whatsapp builders ----


def test_build_aisensy_puts_key_in_body_and_campaign_as_template() -> None:
    cfg = WhatsAppConfig(
        recipient_param="caller", template="price_list_campaign", body_params=["p1"]
    )
    req = whatsapp.build_aisensy(
        cfg, api_key="AKEY", recipient_e164="+919000000000", body_values=["Rs 500"]
    )
    assert req.url == "https://backend.aisensy.com/campaign/t1/api/v2"
    assert req.json_body == {
        "apiKey": "AKEY",
        "campaignName": "price_list_campaign",
        "destination": "+919000000000",
        "userName": "Calevate",
        "templateParams": ["Rs 500"],
    }


def test_build_meta_cloud_uses_phone_number_id_and_bearer() -> None:
    cfg = WhatsAppConfig(
        recipient_param="caller",
        template="hello",
        language="en",
        phone_number_id="123456",
        body_params=["a"],
    )
    req = whatsapp.build_meta_cloud(
        cfg,
        access_token="TOK",
        recipient_e164="+919000000000",
        header_value=None,
        body_values=["Ravi"],
    )
    assert req.url == "https://graph.facebook.com/v20.0/123456/messages"
    assert req.headers["Authorization"] == "Bearer TOK"
    assert req.json_body is not None
    assert req.json_body["to"] == "919000000000"
    template = req.json_body["template"]
    assert isinstance(template, dict)
    assert template["name"] == "hello"


def test_build_interakt_splits_country_code_and_uses_basic_auth() -> None:
    cfg = WhatsAppConfig(
        recipient_param="caller", template="hello", language="en", body_params=["a"]
    )
    req = whatsapp.build_interakt(
        cfg,
        api_key="BASE64KEY",
        recipient_e164="+919876543210",
        header_value=None,
        body_values=["Ravi"],
    )
    assert req.url == "https://api.interakt.ai/v1/public/message/"
    assert req.headers["Authorization"] == "Basic BASE64KEY"
    assert req.json_body == {
        "countryCode": "+91",
        "phoneNumber": "9876543210",
        "type": "Template",
        "template": {"name": "hello", "languageCode": "en", "bodyValues": ["Ravi"]},
    }


# --------------------------------------------------------------- execution ----


def _mock_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_custom_api_execution_builds_request_and_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execution, "resolve_secret", _fake_secret("SEKRIT"))
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "shipped"})

    tool = _loaded(
        credential_id=uuid4(),
        config=CustomApiConfig(
            method="POST",
            url="https://api.store.test/orders",
            body=[{"key": "order_id", "param": "order_id"}],
        ).model_dump(),
        params=[{"name": "order_id", "source": "ai", "type": "string", "description": "id"}],
    )
    async with _mock_client(handler) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"order_id": "ORD-9"},
            source="test",
            client=client,
            audit=False,
        )
    assert result.ok is True
    assert result.payload["data"] == {"status": "shipped"}
    assert seen["auth"] == "Bearer SEKRIT"
    assert seen["body"] == {"order_id": "ORD-9"}


@pytest.mark.asyncio
async def test_egress_guard_blocks_a_private_custom_api_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Make DNS resolve the client's URL to a PRIVATE (RFC 1918) address — the rebinding
    # shape the guard exists to refuse — via its own resolver seam, so no real network is
    # touched. Private (not loopback) because loopback is deliberately allowed under
    # APP_ENV=local, while an internal-network address stays refused everywhere.
    from apps.api.integrations import egress_guard

    async def _private(host: str, port: int) -> tuple[str, ...]:
        return ("192.168.1.50",)

    monkeypatch.setattr(egress_guard, "resolve_addresses", _private)
    tool = _loaded(
        config=CustomApiConfig(method="GET", url="https://evil.test/x").model_dump(), params=[]
    )
    async with _mock_client(lambda r: httpx.Response(200)) as client:
        result = await execution.execute_action(
            _FakeSession(), tool=tool, received={}, source="test", client=client, audit=False
        )
    assert result.ok is False
    assert result.status == "webhook_url_not_public"


@pytest.mark.asyncio
async def test_whatsapp_send_blocked_when_not_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "resolve_secret", _fake_secret("KEY"))
    monkeypatch.setattr(whatsapp, "check_dispatch", _fake_allowed_dispatch())
    monkeypatch.setattr(whatsapp, "read_messaging_consent", _fake_consent(messageable=False))
    tool = _loaded(
        kind="whatsapp",
        provider="aisensy",
        credential_id=uuid4(),
        config=WhatsAppConfig(recipient_param="caller", template="c", body_params=[]).model_dump(),
        params=[{"name": "caller", "source": "lead_var", "lead_var": "caller_phone"}],
    )
    sent = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent = True
        return httpx.Response(200)

    async with _mock_client(handler) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"caller": "+919000000000"},
            source="in_call",
            client=client,
            audit=False,
        )
    assert result.status == "not_opted_in"
    assert result.ok is False
    assert sent is False  # the send never went out


@pytest.mark.asyncio
async def test_whatsapp_send_blocked_when_the_dispatch_gate_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE TWO PATHS ASK THE SAME QUESTION. `workers/whatsapp._send_escalation` has always
    run `check_dispatch(dlt_governed=False)` before the opt-in; this in-call action path
    ran only the opt-in — so a number on the tenant's DNC list that had once granted
    messaging consent was refused by the campaign leg and messaged by this one. One
    outbound channel, one answer (hard rule 5).

    The consent stub says MESSAGEABLE, so the only thing that can stop this send is the
    gate. Without it the test would pass on the opt-in refusal and prove nothing.
    """
    monkeypatch.setattr(execution, "resolve_secret", _fake_secret("KEY"))
    monkeypatch.setattr(whatsapp, "check_dispatch", _fake_blocked_dispatch("dnc"))
    monkeypatch.setattr(whatsapp, "read_messaging_consent", _fake_consent(messageable=True))
    tool = _loaded(
        kind="whatsapp",
        provider="aisensy",
        credential_id=uuid4(),
        config=WhatsAppConfig(recipient_param="caller", template="c", body_params=[]).model_dump(),
        params=[{"name": "caller", "source": "lead_var", "lead_var": "caller_phone"}],
    )
    sent = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent = True
        return httpx.Response(200)

    async with _mock_client(handler) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"caller": "+919000000000"},
            source="in_call",
            client=client,
            audit=False,
        )
    assert result.ok is False
    assert result.status == "blocked"
    # The RULE reaches the client's payload, never the number (hard rule 6).
    assert result.payload == {"error": "whatsapp_blocked_dnc"}
    assert sent is False


@pytest.mark.asyncio
async def test_whatsapp_send_delivers_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "resolve_secret", _fake_secret("KEY"))
    monkeypatch.setattr(whatsapp, "check_dispatch", _fake_allowed_dispatch())
    monkeypatch.setattr(whatsapp, "read_messaging_consent", _fake_consent(messageable=True))
    tool = _loaded(
        kind="whatsapp",
        provider="aisensy",
        credential_id=uuid4(),
        config=WhatsAppConfig(recipient_param="caller", template="c", body_params=[]).model_dump(),
        params=[{"name": "caller", "source": "lead_var", "lead_var": "caller_phone"}],
    )
    async with _mock_client(lambda r: httpx.Response(200, json={"ok": True})) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"caller": "+919000000000"},
            source="in_call",
            client=client,
            audit=False,
        )
    assert result.ok is True
    assert result.status == "delivered"
    assert result.payload == {"status": "sent"}


# ------------------------------------------------------------------ helpers ----


class _FakeSession:
    """Stand-in for an AsyncSession — the DB helpers the executor calls are monkeypatched,
    so nothing is ever executed against it."""


def _fake_secret(value: str) -> Any:
    async def _resolve(session: Any, *, tenant_id: Any, credential_id: Any) -> str:
        return value

    return _resolve


def _fake_allowed_dispatch() -> Any:
    """`check_dispatch` says yes. Stubbed because these are UNIT tests over the executor
    with a `_FakeSession` — the gate itself is exercised against a real database in
    `tests/compliance_gate_test.py`, and what THIS suite asserts is that the executor
    calls it at all and honours a refusal."""

    async def _check(session: Any, **kwargs: Any) -> Any:
        return DispatchDecision(allowed=True)

    return _check


def _fake_blocked_dispatch(rule: str) -> Any:
    async def _check(session: Any, **kwargs: Any) -> Any:
        return DispatchDecision(allowed=False, rule=rule, reason="blocked")

    return _check


def _fake_consent(*, messageable: bool) -> Any:
    async def _read(session: Any, *, tenant_id: Any, raw_phone: str) -> MessagingConsent:
        from datetime import UTC, datetime, timedelta

        if messageable:
            return MessagingConsent(
                status="granted",
                source="ivr",
                captured_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
        return MessagingConsent(status="none")

    return _read
