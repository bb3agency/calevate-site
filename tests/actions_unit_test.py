"""ACTIONS feature — DB-free unit tests for the parts that carry the most risk: the
engine-neutral declaration, parameter binding, the external request builders, and the
executor's dispatch/opt-in/egress behaviour.

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

# --------------------------------------------------------------- declaration ----


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
    inbound = _to_spec(_loaded(params=params), direction="inbound")
    outbound = _to_spec(_loaded(params=params), direction="outbound")
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


@pytest.mark.asyncio
async def test_whatsapp_send_is_addressed_to_the_number_the_gate_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate and the consent read are asked about the NORMALIZED number, so the message
    must go to that number too, not to the raw string the model or engine supplied."""
    asked: list[str] = []

    async def _check(session: Any, **kwargs: Any) -> Any:
        asked.append(kwargs["phone_e164"])
        return DispatchDecision(allowed=True)

    monkeypatch.setattr(execution, "resolve_secret", _fake_secret("KEY"))
    monkeypatch.setattr(whatsapp, "check_dispatch", _check)
    monkeypatch.setattr(whatsapp, "read_messaging_consent", _fake_consent(messageable=True))
    tool = _loaded(
        kind="whatsapp",
        provider="aisensy",
        credential_id=uuid4(),
        config=WhatsAppConfig(recipient_param="caller", template="c", body_params=[]).model_dump(),
        params=[{"name": "caller", "source": "ai", "type": "string", "description": "number"}],
    )
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    async with _mock_client(handler) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"caller": "098765 43210"},
            source="in_call",
            client=client,
            audit=False,
        )
    assert result.ok is True
    assert asked == ["+919876543210"]
    assert sent["destination"] == "+919876543210"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["aisensy", "meta_cloud", "interakt"])
async def test_a_missing_template_value_is_not_filled_by_the_next_one(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    """Template variables are POSITIONAL ({{1}}, {{2}}, ...). Dropping the one the model did
    not supply shifts every later value into its slot, so "Hi {{1}}, see you at {{2}}"
    would greet the customer by the appointment time. Nothing may be sent; the model is
    told which value it still needs, so it can ask the caller."""
    monkeypatch.setattr(execution, "resolve_secret", _fake_secret("KEY"))
    monkeypatch.setattr(whatsapp, "check_dispatch", _fake_allowed_dispatch())
    monkeypatch.setattr(whatsapp, "read_messaging_consent", _fake_consent(messageable=True))
    tool = _loaded(
        kind="whatsapp",
        provider=provider,
        credential_id=uuid4(),
        config=WhatsAppConfig(
            recipient_param="caller",
            template="booking_confirmed",
            language="en",
            phone_number_id="1234567890",
            body_params=["customer_name", "slot"],
        ).model_dump(),
        params=[
            {"name": "caller", "source": "lead_var", "lead_var": "caller_phone"},
            {"name": "customer_name", "source": "ai", "type": "string", "description": "name"},
            {"name": "slot", "source": "ai", "type": "string", "description": "time"},
        ],
    )
    sent: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(200, json={"ok": True})

    async with _mock_client(handler) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"caller": "+919000000000", "slot": "10:30 AM"},
            source="in_call",
            client=client,
            audit=False,
        )
    assert sent == [], "a template with a value in the wrong slot was sent to a customer"
    assert result.ok is False
    assert result.status == "missing_template_value"
    assert result.payload == {"error": "missing_template_value", "missing": ["customer_name"]}


def _calendar_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """The platform OAuth client configured, the refresh token resolvable, and Google's
    hosts resolving to a public address through the guard's own seam."""
    from apps.api.core.settings import get_settings
    from apps.api.integrations import egress_guard

    settings = get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://app.test/cb")
    monkeypatch.setattr(execution, "resolve_secret", _fake_secret("refresh-token"))

    async def _public(host: str, port: int) -> tuple[str, ...]:
        return ("142.250.183.10",)

    monkeypatch.setattr(egress_guard, "resolve_addresses", _public)


def _calendar_tool(**config: Any) -> LoadedTool:
    from apps.api.actions.schema import CalendarConfig

    return _loaded(
        kind="calendar",
        provider="google",
        credential_id=uuid4(),
        config=CalendarConfig(**config).model_dump(),
        params=[
            {"name": "start", "source": "ai", "type": "string", "description": "start"},
            {"name": "end", "source": "ai", "type": "string", "description": "end"},
        ],
    )


def _google(seen: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "access"})
        if request.url.path.endswith("/freeBusy"):
            return httpx.Response(200, json={"calendars": {"primary": {"busy": []}}})
        return httpx.Response(200, json={"id": "evt_1"})

    return handler


@pytest.mark.asyncio
async def test_an_availability_check_with_no_end_time_is_not_answered_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A window from a time to the same time contains nothing, so no calendar can be busy
    in it: querying it answers "available" for a slot that is already booked, and the
    agent then offers it to the caller."""
    _calendar_ready(monkeypatch)
    seen: list[httpx.Request] = []
    tool = _calendar_tool(operation="check", start_param="start", end_param="end")
    async with _mock_client(_google(seen)) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"start": "2026-10-01T10:00:00+05:30"},
            source="in_call",
            client=client,
            audit=False,
        )
    assert not any(r.url.path.endswith("/freeBusy") for r in seen)
    assert result.ok is False
    assert result.status == "no_end_time"


@pytest.mark.asyncio
async def test_a_time_with_no_offset_is_sent_as_ist(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC 3339 (which Google's `dateTime` is) requires an offset; a model that says
    "2026-10-01T10:00:00" means ten in the morning where the caller is, and every caller
    of this India-only product is on IST."""
    _calendar_ready(monkeypatch)
    seen: list[httpx.Request] = []
    tool = _calendar_tool(operation="book", start_param="start", duration_min=30)
    async with _mock_client(_google(seen)) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"start": "2026-10-01T10:00:00"},
            source="in_call",
            client=client,
            audit=False,
        )
    assert result.ok is True, result
    (book,) = [r for r in seen if r.url.path.endswith("/events")]
    body = json.loads(book.content)
    assert body["start"] == {"dateTime": "2026-10-01T10:00:00+05:30"}
    assert body["end"] == {"dateTime": "2026-10-01T10:30:00+05:30"}


@pytest.mark.asyncio
async def test_an_unreadable_time_is_refused_before_google_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calendar_ready(monkeypatch)
    seen: list[httpx.Request] = []
    tool = _calendar_tool(operation="book", start_param="start", duration_min=30)
    async with _mock_client(_google(seen)) as client:
        result = await execution.execute_action(
            _FakeSession(),
            tool=tool,
            received={"start": "tomorrow at ten"},
            source="in_call",
            client=client,
            audit=False,
        )
    assert not any(r.url.path.endswith("/events") for r in seen)
    assert result.ok is False
    assert result.status == "unreadable_time"


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
