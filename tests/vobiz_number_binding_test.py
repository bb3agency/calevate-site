"""Pointing a number at an agent on Vobiz, recording the binding, and the credential probe."""

from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.parse import quote

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.pipecat import PipecatEngine, engine_agent_ref_for
from apps.api.engine.plivo_carrier import PlivoCarrier
from apps.api.engine.vobiz import VobizCarrier
from apps.api.ops import secret_probes
from calevate_shared.engine import ProvisionedNumber
from tests.vobiz_dial_test import AGENT, TENANT, _Store

pytestmark = pytest.mark.anyio

BASE = "https://api.vobiz.ai/api/v1"
HOOKS = "https://hooks.example.test"
REF = engine_agent_ref_for(TENANT, AGENT)
LINKED = ProvisionedNumber(e164="+911140000000", provider="vobiz", engine_number_ref="vz-num-1")
UNLINKED = ProvisionedNumber(e164="+911140000001", provider="vobiz")


@pytest.fixture(autouse=True)
def _public_hooks(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("WEBHOOK_BASE_URL", HOOKS)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Stub:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def _vobiz(stub: _Stub) -> VobizCarrier:
    return VobizCarrier(
        auth_id="MA_X",
        auth_token="t",
        base_url=BASE,
        client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(stub)),
    )


async def test_binding_routes_the_number_to_the_agents_answer_path_and_records_it() -> None:
    stub = _Stub(
        httpx.Response(200, json={"objects": []}),
        httpx.Response(201, json={"app_id": "app-1"}),
        httpx.Response(200, json={"message": "attached"}),
    )
    store = _Store()
    engine = PipecatEngine(store=store, carrier=_vobiz(stub))  # type: ignore[arg-type]

    await engine.bind_inbound_number(REF, LINKED)

    created = json.loads(stub.requests[1].content)
    segment = quote(REF, safe="")
    # Routing stays in the path we mint (D-603): no call id on an inbound answer URL.
    assert created["answer_url"] == f"{HOOKS}/carrier/v1/vobiz/answer/{segment}"
    assert created["hangup_url"] == f"{HOOKS}/carrier/v1/vobiz/events/{segment}"
    assert created["app_name"].startswith("calevate-")
    assert store.bindings == {LINKED.e164: "app-1"}


async def test_a_number_the_carrier_was_never_told_about_is_refused_by_name() -> None:
    stub = _Stub(httpx.Response(200))
    engine = PipecatEngine(store=_Store(), carrier=_vobiz(stub))  # type: ignore[arg-type]
    with pytest.raises(ProblemError) as raised:
        await engine.bind_inbound_number(REF, UNLINKED)
    assert raised.value.code == "engine_number_not_linked"
    assert stub.requests == []


async def test_unbinding_detaches_and_an_unlinked_number_needs_nothing() -> None:
    stub = _Stub(httpx.Response(200, json={"message": "detached"}))
    engine = PipecatEngine(store=_Store(), carrier=_vobiz(stub))  # type: ignore[arg-type]
    await engine.unbind_inbound_number(UNLINKED)
    assert stub.requests == []
    await engine.unbind_inbound_number(LINKED)
    assert stub.requests[0].method == "DELETE"


async def test_plivo_refuses_binding_by_capability() -> None:
    engine = PipecatEngine(store=_Store(), carrier=PlivoCarrier())  # type: ignore[arg-type]
    for call in (
        engine.bind_inbound_number(REF, LINKED),
        engine.unbind_inbound_number(LINKED),
    ):
        with pytest.raises(ProblemError) as raised:
            await call
        assert getattr(raised.value, "capability", None) == "inbound_binding"


async def test_the_credential_probe_uses_the_carrier_and_the_configured_other_half(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    def build(cfg: object, name: object) -> VobizCarrier:
        seen.append(getattr(cfg, "vobiz_auth_token", None))
        stub = _Stub(httpx.Response(200, json={"auth_id": "MA_X"}))
        return VobizCarrier(
            auth_id=getattr(cfg, "vobiz_auth_id", None),
            auth_token=getattr(cfg, "vobiz_auth_token", None),
            base_url=BASE,
            client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(stub)),
        )

    monkeypatch.setattr(secret_probes, "build_carrier", build)
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_X")
    get_settings.cache_clear()

    result = await secret_probes.probe_credential("vobiz_auth_token", "candidate")
    assert result.outcome == "accepted"
    assert seen == ["candidate"]


async def test_the_probe_reports_a_refusal_and_an_unchecked_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = {"code": 401}

    def build(cfg: object, name: object) -> VobizCarrier:
        stub = _Stub(httpx.Response(status["code"]))
        return VobizCarrier(
            auth_id=getattr(cfg, "vobiz_auth_id", None),
            auth_token=getattr(cfg, "vobiz_auth_token", None),
            base_url=BASE,
            client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(stub)),
        )

    monkeypatch.setattr(secret_probes, "build_carrier", build)
    monkeypatch.delenv("VOBIZ_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("VOBIZ_AUTH_ID", raising=False)
    get_settings.cache_clear()
    half = await secret_probes.probe_credential("vobiz_auth_id", "MA_X")
    assert half.outcome == "unreachable"

    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "configured")
    get_settings.cache_clear()
    refused = await secret_probes.probe_credential("vobiz_auth_id", "MA_X")
    assert refused.outcome == "rejected"

    status["code"] = 500
    broken = await secret_probes.probe_credential("vobiz_auth_id", "MA_X")
    assert broken.outcome == "unreachable"


async def test_a_rebind_hands_the_carrier_the_binding_it_remembers() -> None:
    stub = _Stub(
        httpx.Response(200, json={"app_id": "app-1", "app_name": f"calevate-{AGENT}"}),
        httpx.Response(200, json={"message": "changed"}),
        httpx.Response(200, json={"message": "attached"}),
    )
    store = _Store()
    store.bindings[LINKED.e164] = "app-1"
    engine = PipecatEngine(store=store, carrier=_vobiz(stub))  # type: ignore[arg-type]
    await engine.bind_inbound_number(REF, LINKED)
    assert stub.requests[0].method == "GET"
    assert stub.requests[0].url.raw_path.decode().endswith("/Application/app-1/")
