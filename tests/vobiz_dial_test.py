"""`PipecatEngine` dialling, hanging up and binding numbers through the Vobiz carrier.

The adapter runs for real over a store double (what `SqlControlPlane` would answer) and the
real `VobizCarrier` over a transport stub. What is asserted is the part the conformance
suite does not pin: the URLs a dial hands the carrier, the ceiling it sets, and that every
refusal before the request is one `dial_was_not_placed` recognises.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
import pytest
from apps.api.agents.service import dial_was_not_placed
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine import vendor_http
from apps.api.engine.carrier import RING_TIMEOUT_S
from apps.api.engine.pipecat import (
    CARRIER_TIME_LIMIT_CEILING_S,
    CARRIER_TIME_LIMIT_MARGIN_S,
    CarrierCallRecord,
    PipecatEngine,
    RuntimeAgent,
    engine_agent_ref_for,
)
from apps.api.engine.vobiz import VobizCarrier
from calevate_shared.engine import (
    AgentConfig,
    CallContext,
    ModelConfig,
    ProvisionedNumber,
    RecallOutcome,
    pipecat_call_ref,
)

pytestmark = pytest.mark.anyio

BASE = "https://api.vobiz.ai/api/v1"
HOOKS = "https://hooks.example.test"
TENANT = "0199a0b0-0000-7000-8000-00000000aa01"
AGENT = "0199a0b0-0000-7000-8000-00000000aa02"
CALLER_ID = "+911140000000"
#: A test caller-claim key, long enough for `usable_caller_claim_key`. Not a real secret.
CLAIM_SECRET = "vobiz-dial-test-claim-key-not-a-real-secret-012345"


@pytest.fixture(autouse=True)
def _public_hooks(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("WEBHOOK_BASE_URL", HOOKS + "/")

    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _instant)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Store:
    """What `SqlControlPlane` answers for the methods the carrier half uses."""

    def __init__(self, *, cap_s: int = 600, held: bool = True, recorded: bool = False) -> None:
        self.dials: list[dict[str, str]] = []
        self.bindings: dict[str, str] = {}
        self._cap_s = cap_s
        self._held = held
        # Published NOT announcing a recording unless a test says so: the answer URL then
        # carries no recorded segment (`answer_path(recorded=...)`, D-668).
        self._recorded = recorded

    async def runtime_agent(self, ref: str) -> RuntimeAgent | None:
        if not self._held:
            return None
        cfg = AgentConfig(
            tenant_id=TENANT,
            agent_id=AGENT,
            name="Receptionist",
            direction="both",
            language_primary="te-IN",
            system_prompt="You are the receptionist.",
            opening_line="Namaskaram.",
            models=ModelConfig(),
            max_call_duration_s=self._cap_s,
            call_is_recorded=self._recorded,
        )
        return RuntimeAgent(
            engine_agent_ref=ref,
            tenant_id=UUID(TENANT),
            agent_id=UUID(AGENT),
            name=cfg.name,
            agent_config_version_id=uuid4(),
            published_at=datetime.now(UTC),
            config=cfg,
        )

    async def record_dial(self, ref: str, **fields: str) -> None:
        self.dials.append({"ref": ref, **fields})

    async def carrier_call_of(self, call_ref: str) -> CarrierCallRecord | None:
        for dial in self.dials:
            if pipecat_call_ref(TENANT, dial["call_id"]) == call_ref:
                return CarrierCallRecord(dial["carrier_call_id"], dial["carrier"])
        return None

    async def record_number_binding(self, ref: str, *, e164: str, binding_id: str) -> None:
        self.bindings[e164] = binding_id

    async def number_binding(self, ref: str, *, e164: str) -> str | None:
        return self.bindings.get(e164)


class _Vobiz:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def _engine(
    stub: _Vobiz, store: _Store | None = None, *, claim_secret: str | None = CLAIM_SECRET
) -> tuple[PipecatEngine, _Store]:
    held = store or _Store()
    carrier = VobizCarrier(
        auth_id="MA_X",
        auth_token="t",
        base_url=BASE,
        client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(stub)),
    )
    engine = PipecatEngine(
        store=held,  # type: ignore[arg-type]
        carrier=carrier,
        caller_claim_secret=claim_secret,
    )
    return engine, held


REF = engine_agent_ref_for(TENANT, AGENT)


def _ctx(**overrides: Any) -> CallContext:
    values: dict[str, Any] = {"call_id": str(uuid4()), "from_e164": CALLER_ID}
    values.update(overrides)
    return CallContext(**values)


async def test_a_dial_names_our_call_in_the_callback_path_and_stamps_the_carrier_id() -> None:
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "vz-1"}))
    engine, store = _engine(stub)
    ctx = _ctx()

    handle = await engine.start_outbound_call(REF, "+919876543210", ctx)

    assert handle == pipecat_call_ref(TENANT, ctx.call_id)
    body = json.loads(stub.requests[0].content)
    segment = quote(REF, safe="")
    assert body["answer_url"] == f"{HOOKS}/carrier/v1/vobiz/answer/{segment}/outbound/{ctx.call_id}"
    assert body["hangup_url"] == f"{HOOKS}/carrier/v1/vobiz/events/{segment}/outbound/{ctx.call_id}"
    assert body["ring_url"] == body["hangup_url"]
    assert "?" not in body["answer_url"], "a query is not covered by Vobiz's signature"
    assert body["from"] == CALLER_ID
    assert body["time_limit"] == 600 + CARRIER_TIME_LIMIT_MARGIN_S
    assert body["ring_timeout"] == RING_TIMEOUT_S
    assert "hangup_on_ring" not in body, "it would cap the answered call, not the ring"
    assert store.dials == [
        {
            "ref": REF,
            "call_id": ctx.call_id,
            "carrier_call_id": "vz-1",
            "from_e164": CALLER_ID,
            "carrier": "vobiz",
        }
    ]


async def test_the_carrier_time_limit_never_exceeds_the_vendor_default() -> None:
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "vz-2"}))
    engine, _ = _engine(stub, _Store(cap_s=86_400))
    await engine.start_outbound_call(REF, "+919876543210", _ctx())
    assert json.loads(stub.requests[0].content)["time_limit"] == CARRIER_TIME_LIMIT_CEILING_S


@pytest.mark.parametrize(
    ("ctx_overrides", "store", "code"),
    [
        ({"from_e164": None}, None, "engine_caller_id_not_configured"),
        ({"call_id": None}, None, "carrier_dial_precondition_failed"),
        ({}, _Store(held=False), "carrier_dial_precondition_failed"),
    ],
)
async def test_a_dial_missing_a_fact_is_refused_before_any_request(
    ctx_overrides: dict[str, Any], store: _Store | None, code: str
) -> None:
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "never"}))
    engine, _ = _engine(stub, store)
    with pytest.raises(ProblemError) as raised:
        await engine.start_outbound_call(REF, "+919876543210", _ctx(**ctx_overrides))
    assert raised.value.code == code
    assert dial_was_not_placed(raised.value) is True
    assert stub.requests == []


async def test_a_ref_this_engine_did_not_mint_is_refused_before_any_request() -> None:
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "never"}))
    engine, _ = _engine(stub)
    with pytest.raises(ProblemError) as raised:
        await engine.start_outbound_call("someone-else:ref", "+919876543210", _ctx())
    assert dial_was_not_placed(raised.value) is True
    assert stub.requests == []


async def test_a_missing_public_address_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.engine import pipecat as pipecat_module

    class _NoHooks:
        webhook_base_url = ""
        carrier_recording_enabled = False  # D-668: read when the dial profile is chosen

    monkeypatch.setattr(pipecat_module, "get_settings", lambda: _NoHooks())
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "never"}))
    engine, _ = _engine(stub)
    with pytest.raises(ProblemError) as raised:
        await engine.start_outbound_call(REF, "+919876543210", _ctx())
    assert raised.value.code == "carrier_dial_precondition_failed"
    with pytest.raises(ProblemError):
        await engine.bind_inbound_number(
            REF, ProvisionedNumber(e164=CALLER_ID, engine_number_ref="n-1")
        )
    assert stub.requests == []


@pytest.mark.parametrize(
    ("response", "placed_proven_absent"),
    [
        (httpx.Response(402, json={"error": "balance"}), True),
        (httpx.Response(401, json={"error": "credentials"}), True),
        (httpx.Response(400, json={"error": "bad"}), True),
        (httpx.Response(429), True),
        (httpx.Response(500), False),
        (httpx.Response(503), False),
    ],
)
async def test_dial_outcomes_are_read_the_way_dispatch_reads_them(
    response: httpx.Response, placed_proven_absent: bool
) -> None:
    engine, store = _engine(_Vobiz(response))
    with pytest.raises(ProblemError) as raised:
        await engine.start_outbound_call(REF, "+919876543210", _ctx())
    assert dial_was_not_placed(raised.value) is placed_proven_absent
    assert store.dials == []


async def test_a_dial_whose_answer_is_lost_may_be_ringing() -> None:
    def lost(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("connection reset", request=request)

    engine, _ = _engine(lost)  # type: ignore[arg-type]
    with pytest.raises(ProblemError) as raised:
        await engine.start_outbound_call(REF, "+919876543210", _ctx())
    assert raised.value.code == "engine_unreachable"
    assert dial_was_not_placed(raised.value) is False


async def test_a_hang_up_reaches_the_carrier_and_never_claims_prevention() -> None:
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "vz-9"}), httpx.Response(204))
    engine, _ = _engine(stub)
    handle = await engine.start_outbound_call(REF, "+919876543210", _ctx())

    assert await engine.end_call(handle) is RecallOutcome.UNKNOWN
    assert stub.requests[-1].method == "DELETE"
    assert stub.requests[-1].url.raw_path.decode().endswith("/Call/vz-9/")

    with pytest.raises(ProblemError) as raised:
        await engine.end_call(pipecat_call_ref(TENANT, uuid4()))
    assert raised.value.code == "engine_rejected"


async def test_vobiz_declares_what_it_does() -> None:
    engine, _ = _engine(_Vobiz(httpx.Response(200)))
    caps = engine.capabilities
    assert caps.caller_id is True
    assert caps.inbound_binding is True
    assert caps.transfer is False
    assert caps.in_call_handoff is False
    assert caps.number_series == frozenset()


async def test_a_dial_without_a_usable_claim_key_is_refused_before_any_request() -> None:
    """Without the key the answer leg signs no call claim, the worker reads the call as
    inbound, and the intent row this dial stamps would never settle."""
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "never"}))
    for secret in (None, "too-short"):
        engine, store = _engine(stub, claim_secret=secret)
        with pytest.raises(ProblemError) as raised:
            await engine.start_outbound_call(REF, "+919876543210", _ctx())
        assert raised.value.code == "carrier_dial_precondition_failed"
        assert dial_was_not_placed(raised.value) is True
        assert store.dials == []
    assert stub.requests == []


@pytest.mark.parametrize(
    "base",
    [
        "http://localhost:8100",
        "https://127.0.0.1",
        "http://hooks.example.test",
        "https://localhost",
    ],
)
async def test_outside_local_a_callback_base_a_carrier_cannot_reach_is_refused(
    monkeypatch: pytest.MonkeyPatch, base: str
) -> None:
    from apps.api.engine import pipecat as pipecat_module

    class _Deployed:
        app_env = "production"
        webhook_base_url = base
        carrier_recording_enabled = False

    monkeypatch.setattr(pipecat_module, "get_settings", lambda: _Deployed())
    stub = _Vobiz(httpx.Response(200, json={"request_uuid": "never"}))
    engine, _ = _engine(stub)
    with pytest.raises(ProblemError) as raised:
        await engine.start_outbound_call(REF, "+919876543210", _ctx())
    assert raised.value.code == "carrier_dial_precondition_failed"
    assert "public callback address" in str(raised.value.detail)
    assert stub.requests == []


async def test_the_carriers_number_list_is_read_page_by_page() -> None:
    first = {"items": [{"id": f"n-{i}", "e164": f"+9111400000{i:02d}"} for i in range(25)]}
    second = {"items": [{"id": "n-25", "e164": CALLER_ID}], "total": 26}
    stub = _Vobiz(httpx.Response(200, json=first), httpx.Response(200, json=second))
    engine, _ = _engine(stub)

    numbers = await engine.list_engine_numbers()

    assert len(numbers) == 26
    assert numbers[-1].e164 == CALLER_ID
    assert numbers[-1].engine_number_ref == "n-25"
    assert [r.url.params["page"] for r in stub.requests] == ["1", "2"]


async def test_retiring_an_agent_deletes_its_application_at_the_carrier() -> None:
    listing = {"objects": [{"app_name": f"calevate-{AGENT}", "app_id": "app-7"}]}
    stub = _Vobiz(httpx.Response(200, json=listing), httpx.Response(204))
    engine, _ = _engine(stub)

    assert await engine.retire_agent_bindings(REF) is True

    assert [r.method for r in stub.requests] == ["GET", "DELETE"]
    assert stub.requests[-1].url.raw_path.decode().endswith("/Application/app-7/")


async def test_an_agent_with_no_application_has_nothing_to_retire() -> None:
    stub = _Vobiz(httpx.Response(200, json={"objects": []}))
    engine, _ = _engine(stub)
    assert await engine.retire_agent_bindings(REF) is False
    assert [r.method for r in stub.requests] == ["GET"]

    unpublished, _ = _engine(_Vobiz(httpx.Response(200)), _Store(held=False))
    assert await unpublished.retire_agent_bindings(REF) is False
