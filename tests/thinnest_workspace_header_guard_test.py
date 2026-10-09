"""No request about a client's resource leaves without that client's workspace header (D-693).

The header (`Thinnest-Workspace: org_…`) decides whose agents, calls, numbers, contacts and
do-not-call list a ThinnestAI request touches; without it a request lands in our developer
workspace (`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/
customers.md:68-91`). Three guards:

* STATIC — every ThinnestAI client builds its headers through `workspace_headers`, the one
  builder, and every adapter request states its workspace (a required keyword).
* DYNAMIC — every tenant-scoped operation of every client, run against a recording vendor
  with a client's handle, sends that client's header on every request that is not a
  developer-only route; and the developer-only ones send none.
* RULES — the builder refuses a header on our own account's routes, and refuses the
  tenant-only writes without a customer workspace.

This generalises the guard `engine/thinnest_customer_data.py` had for its two routes.
"""

from __future__ import annotations

import ast
import contextlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.catalogue import VoiceCloneSample
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.engine.thinnest_actions import ActionDefinition, ThinnestActions
from apps.api.engine.thinnest_customer_data import ThinnestCustomerData
from apps.api.engine.thinnest_customers import ThinnestCustomers
from apps.api.engine.thinnest_numbers import BusinessDocument, ThinnestNumbers
from apps.api.engine.thinnest_webhooks import ThinnestWebhooks
from apps.api.engine.thinnest_workspace import (
    DEVELOPER_ONLY_ROUTES,
    WORKSPACE_HEADER,
    WorkspaceScopeError,
    in_workspace,
    workspace_headers,
)
from calevate_shared.engine import CallContext, KBSourceRef
from tests.thinnest_engine_test import _cfg, tools_state

ENGINE_DIR = Path(__file__).resolve().parent.parent / "apps" / "api" / "engine"
CLIENT_MODULES = (
    "thinnest.py",
    "thinnest_numbers.py",
    "thinnest_webhooks.py",
    "thinnest_actions.py",
    "thinnest_customer_data.py",
    "thinnest_customers.py",
)
WS = "org_guard-client"
AGENT = f"ag_1@{WS}"
CALL = f"out_1@{WS}"


# --- static -----------------------------------------------------------------------------


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


@pytest.mark.parametrize("module", CLIENT_MODULES)
def test_every_client_builds_its_headers_through_the_one_builder(module: str) -> None:
    tree = ast.parse((ENGINE_DIR / module).read_text(encoding="utf-8"))
    requests = _calls(tree, "vendor_request")
    assert requests, module
    builders = _calls(tree, "workspace_headers")
    assert builders, f"{module} sends requests without the workspace header builder"
    for call in requests:
        headers = next((kw.value for kw in call.keywords if kw.arg == "headers"), None)
        assert headers is not None, f"{module}:{call.lineno} sends no headers= at all"
        assert "workspace_headers" in ast.unparse(headers) or ast.unparse(headers) == "headers", (
            f"{module}:{call.lineno} builds headers without workspace_headers"
        )


def test_every_adapter_request_states_its_workspace() -> None:
    tree = ast.parse((ENGINE_DIR / "thinnest.py").read_text(encoding="utf-8"))
    for name in ("_request", "_walk"):
        for call in _calls(tree, name):
            assert any(kw.arg == "workspace" for kw in call.keywords), (
                f"thinnest.py:{call.lineno} calls {name} without stating its workspace"
            )


# --- rules ------------------------------------------------------------------------------


def test_our_own_accounts_routes_never_carry_a_header() -> None:
    for method, route in DEVELOPER_ONLY_ROUTES:
        assert workspace_headers(method, route, None) == {}
        with pytest.raises(WorkspaceScopeError):
            workspace_headers(method, route, WS)


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("POST", "/agents"),
        ("POST", "/phone-numbers"),
        ("PUT", "/phone-numbers/business-details"),
        ("POST", "/do-not-call"),
        ("DELETE", "/contacts/{id}"),
        ("GET", "/phone-numbers/available"),
    ],
)
def test_a_tenant_only_write_is_refused_without_a_customer_workspace(
    method: str, route: str
) -> None:
    for workspace in (None, "", "ws_dev", "org_"):
        with pytest.raises(ProblemError) as refused:
            workspace_headers(method, route, workspace)
        assert refused.value.code == "engine_workspace_not_provisioned"
    assert workspace_headers(method, route, WS) == {WORKSPACE_HEADER: WS}


# --- dynamic ----------------------------------------------------------------------------


_DEVELOPER_PATHS = {route for _m, route in DEVELOPER_ONLY_ROUTES}


class Recorder:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, str | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        self.seen.append((request.method, path, request.headers.get(WORKSPACE_HEADER)))
        if path.endswith("/tools"):
            sent = json.loads(request.content) if request.content else None
            return httpx.Response(200, json=tools_state(sent))
        if path == "/agents/ag_1":
            return httpx.Response(
                200,
                json={"id": "ag_1", "instructions": "x", "greeting": "Hello", "byok": "off"},
            )
        if path.endswith("/knowledge") and request.method == "POST":
            return httpx.Response(201, json={"id": "kn_1", "status": "ready"})
        if path == "/calls" and request.method == "POST":
            return httpx.Response(201, json={"id": "out_1", "status": "ringing"})
        if path.startswith("/calls/"):
            return httpx.Response(200, json={"id": "out_1", "status": "completed"})
        if path.startswith("/phone-numbers/") and not path.endswith(
            ("/available", "/cities", "/business-details")
        ):
            return httpx.Response(
                200, json={"number": "918011112222", "source": "rented", "agent": None}
            )
        if path.startswith("/webhooks"):
            return httpx.Response(
                200, json={"id": "wh_1", "signingSecret": "s", "enabled": True, "items": []}
            )
        if path.startswith("/customers") or path == "/workspace":
            return httpx.Response(200, json={"id": "org_x", "items": []})
        return httpx.Response(
            200, json={"items": [], "nextCursor": None, "id": "x", "status": "none"}
        )


def _http(recorder: Recorder) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(recorder), base_url=BASE_URL)


def _tenant_ops(rec: Recorder) -> list[Callable[[], Awaitable[Any]]]:
    engine = ThinnestEngine(api_key="ta_live_test", client=_http(rec))
    numbers = ThinnestNumbers(api_key="ta_live_test", client=_http(rec))
    hooks = ThinnestWebhooks(api_key="ta_live_test", client=_http(rec))
    actions = ThinnestActions(api_key="ta_live_test", client=_http(rec))
    data = ThinnestCustomerData(api_key="ta_live_test", client=_http(rec))
    number = f"918011112222@{WS}"
    sample = VoiceCloneSample(
        filename="s.mp3",
        content_type="audio/mpeg",
        data=b"x",
        name="n",
        consent_own_voice=True,
        consent_no_impersonation=True,
    )
    action = ActionDefinition(
        name="opt_out", description="Records an opt-out.", url="https://x/y", parameters=()
    )

    async def scoped(op: Callable[[], Awaitable[Any]]) -> Any:
        with in_workspace(WS):
            return await op()

    return [
        lambda: engine.create_agent(_cfg(engine_workspace=WS)),
        lambda: engine.update_agent(AGENT, _cfg()),
        lambda: engine.get_agent(AGENT),
        lambda: engine.settings_drift(AGENT, _cfg()),
        lambda: engine.repair_settings(AGENT, _cfg(), ["built_in_tools"]),
        lambda: engine.override_call_script(AGENT, opening_line="Hi", system_prompt="x"),
        lambda: engine.delete_agent(AGENT),
        lambda: engine.start_outbound_call(AGENT, "+919876543210", CallContext(call_id="c1")),
        lambda: engine.end_call(CALL),
        lambda: engine.get_execution(CALL),
        lambda: engine.attach_kb(AGENT, KBSourceRef(kb_id="k", title="t", text="x")),
        lambda: engine.detach_kb(AGENT, "kn_1"),
        lambda: engine.list_kb(AGENT),
        lambda: engine.agent_own_voice_key(AGENT),
        lambda: engine.set_agent_own_voice_key(AGENT, on=False),
        lambda: scoped(engine.list_engine_numbers),
        lambda: scoped(engine.list_account_kb),
        lambda: scoped(lambda: engine.list_executions(since=datetime(2026, 10, 1, tzinfo=UTC))),
        lambda: scoped(lambda: engine.list_call_charges(since=date(2026, 10, 1))),
        lambda: scoped(engine.list_voice_clones),
        lambda: scoped(lambda: engine.create_voice_clone(sample)),
        lambda: scoped(lambda: engine.find_voice_clone("v")),
        lambda: scoped(lambda: engine.delete_voice_clone("c")),
        lambda: scoped(engine.own_key_state),
        lambda: scoped(engine.list_hosted_voices),
        lambda: numbers.get_number(number),
        lambda: numbers.attach(number, agent=AGENT, calling_agent=None),
        lambda: numbers.cities(WS),
        lambda: numbers.search(WS, city="Bangalore", pattern=None, cursor=None),
        lambda: numbers.rent(WS, "918011112222"),
        lambda: numbers.release(number),
        lambda: numbers.business_details(WS),
        lambda: numbers.send_business_details(
            WS,
            business_name="Acme",
            gst_registered=True,
            document_kind="gst",
            document=BusinessDocument(filename="g.pdf", content_type="application/pdf", data=b"x"),
        ),
        lambda: hooks.create(engine_agent_ref=AGENT, url="https://hooks.example/x"),
        lambda: hooks.list_for_agent(AGENT),
        lambda: hooks.get(f"wh_1@{WS}"),
        lambda: hooks.enable(f"wh_1@{WS}"),
        lambda: hooks.subscribe(f"wh_1@{WS}", ("call.analysed",)),
        lambda: hooks.redeliver_since(f"wh_1@{WS}", datetime(2026, 10, 1, tzinfo=UTC)),
        lambda: hooks.delete(f"wh_1@{WS}"),
        lambda: actions.list_actions(AGENT),
        lambda: actions.create(AGENT, action, secret="s"),
        lambda: actions.delete(AGENT, "act_1"),
        lambda: actions.call(AGENT, "out_1"),
        lambda: actions.has_live_call(AGENT),
        lambda: data.add_do_not_call(WS, "+919876543210"),
        lambda: data.contact_ids(WS, "+919876543210"),
        lambda: data.delete_contact(WS, "ct_1"),
    ]


async def test_every_tenant_resource_request_carries_the_clients_header() -> None:
    rec = Recorder()
    for op in _tenant_ops(rec):
        with contextlib.suppress(ProblemError):
            await op()
    tenant_requests = [s for s in rec.seen if s[1] not in _DEVELOPER_PATHS]
    assert len(tenant_requests) >= 45
    missing = [(m, p) for m, p, header in tenant_requests if header != WS]
    assert missing == [], f"tenant requests sent without the client's workspace: {missing}"


async def test_our_own_accounts_calls_carry_no_header() -> None:
    rec = Recorder()
    engine = ThinnestEngine(api_key="ta_live_test", client=_http(rec))
    customers = ThinnestCustomers(api_key="ta_live_test", client=_http(rec))
    for op in (
        engine.own_key_state,
        engine.enable_own_voice_key,
        engine.disable_own_voice_key,
        lambda: engine.install_own_voice_key(provider="cartesia", api_key="k", model=None),
        engine.read_catalogue,
        engine.list_own_key_voices,
        engine.list_hosted_voices,
        customers.developer_workspace_id,
        lambda: customers.find("calevate-x"),
        lambda: customers.create(name="Acme", external_id="calevate-x", timezone="Asia/Kolkata"),
        lambda: customers.delete("org_x"),
    ):
        with contextlib.suppress(ProblemError):
            await op()
    assert rec.seen
    assert [s for s in rec.seen if s[2] is not None] == []
