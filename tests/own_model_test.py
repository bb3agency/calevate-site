"""Our own model on ThinnestAI (D-764): the adapter's wire, the workspace set-up, readiness,
billing and the publish seam.

Vendor shapes are the 13 Oct 2026 snapshot (`thinnest-findings/mirror/snapshots/2026-10-13/
pages/api-reference/`): `bring-your-own-keys.md`, `agents/set-agent-byok-model.md`,
`agents/update-agent.md` (`byok`) and `calls/get-call.md` (`usage`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.agents import own_model
from apps.api.agents import studio_voices as studio_module
from apps.api.agents.own_model import (
    OWN_MODEL_NOT_OFFERED,
    OWN_MODEL_NOT_READY,
    ensure_own_model_in,
    own_model_for,
    own_model_key_ready,
    own_model_label,
    own_model_of_choice,
    own_model_rate_key,
    refuse_own_model_choice,
)
from apps.api.agents.verification import _own_voice_key_verdict
from apps.api.billing import engine_minutes, rates
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.catalogue import OwnVoiceKeyState
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine, parse_llm_usage
from apps.api.engine.thinnest_workspace import in_workspace
from apps.workers import pipeline
from calevate_shared.engine import THINNEST_OWN_MODEL_DEFAULT, AgentConfig, AgentSnapshot
from calevate_shared.events import CallLlmUsage
from tests.hosted_voice_fakes import HostingEngine

Handler = Callable[[httpx.Request], httpx.Response]
WS = "org_own-model-client"
TENANT = UUID("00000000-0000-0000-0000-0000000000a1")
_KEYS_OFF = OwnVoiceKeyState(enabled=False, scope=None, complete=False, using="none")

_OWN_STATUS: dict[str, Any] = {
    "enabled": True,
    "scope": "llm",
    "usingScope": "llm",
    "using": "own",
    "complete": True,
    "credentials": [
        {
            "kind": "llm",
            "provider": "google",
            "model": "gemini-2.5-flash-lite",
            "verifiedAt": "2026-10-13T10:00:00Z",
        }
    ],
}


def _engine(handler: Handler) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


class _Vendor:
    """Answers by (method, path, workspace); records every request and its body."""

    def __init__(self, routes: dict[tuple[str, str, str | None], httpx.Response]):
        self.routes = routes
        self.seen: list[tuple[str, str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content) if request.content else None
        self.seen.append((request.method, path, body))
        key = (request.method, path, request.headers.get("Thinnest-Workspace"))
        if key not in self.routes and path.endswith("/tools"):
            from tests.thinnest_engine_test import tools_state

            return httpx.Response(200, json=tools_state(body))
        return self.routes.get(key, httpx.Response(404, json={"error": "x"}))


def _ok(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _cfg(**over: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "tenant_id": str(TENANT),
        "agent_id": "00000000-0000-0000-0000-000000000002",
        "name": "Reception",
        "system_prompt": "Be kind.",
        "opening_line": "Namaste.",
        "language_primary": "te-IN",
        "direction": "inbound",
    }
    return AgentConfig.model_validate({**base, **over})


# --- the adapter --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("own_voice", "model", "sent"),
    [
        (False, None, "off"),
        (True, None, "workspace"),
        (False, "gemini-2.5-flash-lite", "llm"),
        (True, "gemini-2.5-flash-lite", "llm_voice"),
    ],
)
def test_each_agent_names_its_own_scope(own_voice: bool, model: str | None, sent: str) -> None:
    body = _engine(_Vendor({}))._agent_body(
        _cfg(engine_own_voice_key=own_voice, engine_own_model=model)
    )
    assert body["byok"] == sent


async def test_our_model_key_is_installed_and_switched_on_with_scope_llm() -> None:
    vendor = _Vendor(
        {
            ("PUT", "/byok/credentials", WS): _ok({"kind": "llm"}),
            ("PATCH", "/byok", WS): _ok({"enabled": True}),
            ("GET", "/byok", WS): _ok(_OWN_STATUS),
        }
    )
    engine = _engine(vendor)
    with in_workspace(WS):
        await engine.install_own_model_key(
            provider="google", api_key="AIza-test", model="gemini-2.5-flash-lite"
        )
        state = await engine.enable_own_model_key()
    assert [body for _m, _p, body in vendor.seen if _m != "GET"] == [
        {
            "kind": "llm",
            "provider": "google",
            "credentials": {"apiKey": "AIza-test", "model": "gemini-2.5-flash-lite"},
        },
        {"enabled": True, "scope": "llm"},
    ]
    assert state.llm_provider == "google" and state.llm_model == "gemini-2.5-flash-lite"
    assert state.llm_verified and own_model_key_ready(state)


@pytest.mark.parametrize(
    ("status", "code"), [(400, "engine_model_key_rejected"), (502, "engine_rejected")]
)
async def test_a_rejected_model_key_is_said_in_our_words(status: int, code: str) -> None:
    vendor = _Vendor({("PUT", "/byok/credentials", None): _ok({"error": "x"}, status)})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).install_own_model_key(provider="google", api_key="k", model="m")
    assert caught.value.code == code


async def test_switching_on_a_model_key_that_is_not_ready_is_said_plainly() -> None:
    vendor = _Vendor({("PATCH", "/byok", WS): _ok({"error": "x"}, 409)})
    with in_workspace(WS), pytest.raises(ProblemError) as caught:
        await _engine(vendor).enable_own_model_key()
    assert caught.value.code == "engine_model_key_not_ready"


async def test_an_agent_on_our_model_is_put_on_its_model_after_every_write() -> None:
    agent = {"id": "ag_9", "greeting": "g", "instructions": "x"}
    vendor = _Vendor(
        {
            ("GET", "/agents", WS): _ok({"items": [], "nextCursor": None}),
            ("POST", "/agents", WS): _ok(agent),
            ("PATCH", "/agents/ag_9", WS): _ok(agent),
            ("PUT", "/agents/ag_9/byok-model", WS): _ok({"model": "gemini-2.5-flash"}),
        }
    )
    engine = _engine(vendor)
    cfg = _cfg(engine_own_voice_key=False, engine_own_model="gemini-2.5-flash", engine_workspace=WS)
    ref = await engine.create_agent(cfg)
    await engine.update_agent(ref, cfg)
    puts = [body for m, p, body in vendor.seen if p.endswith("/byok-model")]
    assert puts == [{"model": "gemini-2.5-flash"}, {"model": "gemini-2.5-flash"}]


async def test_an_agent_off_our_model_sends_no_model_of_our_key() -> None:
    agent = {"id": "ag_9", "greeting": "g", "instructions": "x"}
    vendor = _Vendor({("PATCH", "/agents/ag_9", WS): _ok(agent)})
    await _engine(vendor).update_agent(f"ag_9@{WS}", _cfg(engine_own_voice_key=False))
    assert not any(p.endswith("/byok-model") for _m, p, _b in vendor.seen)


async def test_a_refused_model_is_said_in_our_words() -> None:
    agent = {"id": "ag_9", "greeting": "g", "instructions": "x"}
    vendor = _Vendor(
        {
            ("PATCH", "/agents/ag_9", WS): _ok(agent),
            ("PUT", "/agents/ag_9/byok-model", WS): _ok({"error": "x"}, 400),
        }
    )
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).update_agent(
            f"ag_9@{WS}", _cfg(engine_own_voice_key=True, engine_own_model="gemini-2.5-flash")
        )
    assert caught.value.code == "engine_own_model_unavailable"


def _clear_on_old_platform(key_model: str) -> _Vendor:
    """A workspace whose key runs `key_model`, on a platform that still answers a Clear
    agent's model with `409` (set-agent-byok-model.md:471-478 in snapshots/2026-10-13)."""
    status = {**_OWN_STATUS, "credentials": [{**_OWN_STATUS["credentials"][0], "model": key_model}]}
    agent = {"id": "ag_9", "greeting": "g", "instructions": "x"}
    return _Vendor(
        {
            ("PATCH", "/agents/ag_9", WS): _ok(agent),
            ("PUT", "/agents/ag_9/byok-model", WS): _ok({"error": "not own keys"}, 409),
            ("GET", "/byok", WS): _ok(status),
        }
    )


async def test_a_clear_agent_refused_its_model_publishes_when_the_key_runs_that_model() -> None:
    vendor = _clear_on_old_platform("gemini-2.5-flash-lite")
    await _engine(vendor).update_agent(
        f"ag_9@{WS}", _cfg(engine_own_voice_key=False, engine_own_model="gemini-2.5-flash-lite")
    )
    assert ("GET", "/byok", None) in vendor.seen


async def test_a_clear_agent_refused_another_model_than_the_keys_is_refused() -> None:
    with pytest.raises(ProblemError) as caught:
        await _engine(_clear_on_old_platform("gemini-2.5-flash-lite")).update_agent(
            f"ag_9@{WS}", _cfg(engine_own_voice_key=False, engine_own_model="gemini-2.5-flash")
        )
    assert caught.value.code == "engine_own_model_unavailable"


async def test_a_studio_agent_refused_its_model_is_refused_whatever_the_key_runs() -> None:
    with pytest.raises(ProblemError) as caught:
        await _engine(_clear_on_old_platform("gemini-2.5-flash-lite")).update_agent(
            f"ag_9@{WS}", _cfg(engine_own_voice_key=True, engine_own_model="gemini-2.5-flash-lite")
        )
    assert caught.value.code == "engine_own_model_unavailable"


async def test_the_drift_repair_reads_a_clear_agents_409_the_same_way() -> None:
    vendor = _clear_on_old_platform("gemini-2.5-flash-lite")
    await _engine(vendor).set_agent_own_keys(
        f"ag_9@{WS}", own_voice=False, own_model="gemini-2.5-flash-lite"
    )
    assert [(m, p) for m, p, _b in vendor.seen] == [
        ("PATCH", "/agents/ag_9"),
        ("PUT", "/agents/ag_9/byok-model"),
        ("GET", "/byok"),
    ]


@pytest.mark.parametrize(
    ("byok", "answer", "own_voice", "model", "readable"),
    [
        ("llm_voice", _ok({"model": "gemini-2.5-flash"}), True, "gemini-2.5-flash", True),
        ("llm", _ok({"model": None}), False, "", True),
        # A Clear agent the platform will not give a model of its own (before ThinnestAI's
        # 18 Oct release) runs the key's own model, read from `GET /byok`.
        ("llm", _ok({"error": "x"}, 409), False, "gemini-2.5-flash-lite", True),
        ("llm_voice", _ok({"error": "x"}, 409), True, "", True),
        ("off", None, False, None, True),
        ("all", None, None, None, False),
    ],
)
async def test_the_agents_scope_and_model_are_read_back(
    byok: str, answer: httpx.Response | None, own_voice: bool | None, model: Any, readable: bool
) -> None:
    routes = {
        ("GET", "/agents/ag_9", None): _ok({"id": "ag_9", "instructions": "x", "byok": byok}),
        ("GET", "/agents/ag_9/knowledge", None): _ok({"items": [], "nextCursor": None}),
        ("GET", "/byok", None): _ok(_OWN_STATUS),
    }
    if answer is not None:
        routes[("GET", "/agents/ag_9/byok-model", None)] = answer
    snapshot = await _engine(_Vendor(routes)).get_agent("ag_9")
    assert snapshot.engine_own_voice_key is own_voice
    assert snapshot.engine_own_model == model
    assert snapshot.engine_own_model_readable is readable


async def test_both_switches_are_put_back_without_touching_anything_else() -> None:
    vendor = _Vendor(
        {
            ("PATCH", "/agents/ag_9", WS): _ok({"id": "ag_9"}),
            ("PUT", "/agents/ag_9/byok-model", WS): _ok({"model": "gemini-2.5-flash-lite"}),
        }
    )
    await _engine(vendor).set_agent_own_keys(
        f"ag_9@{WS}", own_voice=True, own_model="gemini-2.5-flash-lite"
    )
    assert [body for _m, _p, body in vendor.seen] == [
        {"byok": "llm_voice"},
        {"model": "gemini-2.5-flash-lite"},
    ]


def test_the_calls_tokens_are_read_in_our_names() -> None:
    usage = parse_llm_usage({"inputTokens": 23500, "outputTokens": 310, "cachedInputTokens": None})
    assert usage == CallLlmUsage(input_tokens=23500, output_tokens=310, cached_input_tokens=None)
    assert parse_llm_usage(None) is None
    assert parse_llm_usage({"inputTokens": -1, "outputTokens": True}) == CallLlmUsage()


# --- read-back verdict ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("held_model", "readable", "wanted", "verdict"),
    [
        ("gemini-2.5-flash", True, "gemini-2.5-flash", True),
        ("", True, "gemini-2.5-flash", False),
        ("gemini-2.5-flash", True, None, False),
        (None, False, None, True),
        (None, False, "gemini-2.5-flash", None),
    ],
)
def test_the_model_of_our_key_is_part_of_the_key_verdict(
    held_model: str | None, readable: bool, wanted: str | None, verdict: bool | None
) -> None:
    snapshot = AgentSnapshot(
        engine_agent_ref="ag_9",
        engine="thinnest",
        engine_own_voice_key=False,
        engine_own_model=held_model,
        engine_own_model_readable=readable,
    )
    cfg = _cfg(engine_own_voice_key=False, engine_own_model=wanted)
    assert _own_voice_key_verdict(cfg, snapshot) is verdict


# --- choice and price -----------------------------------------------------------------


def test_a_choice_of_our_model_is_its_own_vocabulary() -> None:
    assert own_model_of_choice("byok:gemini-2.5-flash") == "gemini-2.5-flash"
    assert own_model_of_choice("gpt-oss-120b") is None
    assert own_model_label("gemini-2.5-flash-lite") == "Gemini 2.5 Flash-Lite (our key)"


def test_an_agent_runs_its_own_offerable_choice_else_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(own_model, "offerable_own_models", lambda: ("gemini-2.5-flash",))
    assert own_model_for("byok:gemini-2.5-flash") == "gemini-2.5-flash"
    default = get_settings().thinnest_own_model_default
    assert own_model_for("byok:gemini-3.8-flash") == default
    assert own_model_for(None) == default


def test_a_studio_minute_on_our_model_moves_to_the_own_voice_and_model_rate() -> None:
    assert own_model_rate_key("byok_voice") == "byok_llm_voice"
    assert own_model_rate_key("premium") == "premium"
    assert engine_minutes.client_voice_tier("thinnest", "byok_llm_voice") == "studio"


def test_the_own_voice_and_model_minute_is_sold_only_while_our_model_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "byok_llm_voice" not in (engine_minutes.client_rungs("thinnest") or {})
    monkeypatch.setattr(get_settings(), "thinnest_own_model", True)
    assert (engine_minutes.client_rungs("thinnest") or {})["byok_llm_voice"] == "studio"


def test_a_choice_of_our_model_is_refused_while_our_model_is_off() -> None:
    with pytest.raises(ProblemError) as caught:
        refuse_own_model_choice(HostingEngine(), "byok:gemini-2.5-flash")
    assert caught.value.code == OWN_MODEL_NOT_OFFERED


def test_the_floors_add_our_models_cost_while_it_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_off = rates.cost_floor_inr_per_min("clear", engine="thinnest", clear_band="premium")
    studio_off = rates.cost_floor_inr_per_min("studio", engine="thinnest")
    monkeypatch.setattr(get_settings(), "thinnest_own_model", True)
    model_cost = rates.own_model_floor_inr_per_min(get_settings().thinnest_own_model_default)
    assert model_cost > 0
    clear_on = rates.cost_floor_inr_per_min("clear", engine="thinnest", clear_band="premium")
    assert clear_on == clear_off + model_cost
    studio_on = rates.cost_floor_inr_per_min("studio", engine="thinnest")
    own_minute = rates.THINNEST_OWN_VOICE_AND_MODEL_INR_PER_MIN * (1 + rates.THINNEST_TOPUP_FEE)
    old_minute = rates.THINNEST_OWN_VOICE_INR_PER_MIN * (1 + rates.THINNEST_TOPUP_FEE)
    assert studio_on == (studio_off - old_minute + own_minute + model_cost).quantize(rates.MONEY_Q)


# --- metering --------------------------------------------------------------------------


def test_a_calls_tokens_are_metered_per_thousand_at_the_models_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "llm_price_is_billable", lambda model: True)
    monkeypatch.setattr(
        pipeline,
        "llm_inr_per_ktok",
        lambda model: {"in": Decimal("0.0096"), "out": Decimal("0.0384")},
    )
    rows = pipeline._own_model_rows(
        "gemini-2.5-flash-lite",
        CallLlmUsage(input_tokens=23500, output_tokens=300, cached_input_tokens=1000),
        tenant_id=TENANT,
        call_id=uuid.uuid4(),
    )
    assert rows == [
        ("llm_ktok_in", Decimal("23.5"), Decimal("0.0096")),
        ("llm_ktok_out", Decimal("0.3"), Decimal("0.0384")),
    ]


def test_an_unpriced_model_meters_its_tokens_with_no_cost_and_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alarms: list[str] = []
    monkeypatch.setattr(pipeline, "llm_price_is_billable", lambda model: False)
    monkeypatch.setattr(pipeline, "alert", lambda _stage, code, **_: alarms.append(code))
    rows = pipeline._own_model_rows(
        "gemini-2.5-flash",
        CallLlmUsage(input_tokens=1000, output_tokens=10),
        tenant_id=TENANT,
        call_id=uuid.uuid4(),
    )
    assert [cost for _u, _q, cost in rows] == [None, None]
    assert alarms == ["own_model_tokens_unpriced"]


def test_a_call_that_never_reached_the_model_meters_nothing() -> None:
    assert pipeline._own_model_rows("m", None, tenant_id=TENANT, call_id=uuid.uuid4()) == []
    assert (
        pipeline._own_model_rows("m", CallLlmUsage(), tenant_id=TENANT, call_id=uuid.uuid4()) == []
    )


# --- readiness ---------------------------------------------------------------------------


@pytest.fixture
def readiness_inputs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Every readiness input, all satisfied; a test turns one off."""
    state: dict[str, Any] = {"attested": frozenset({"byok_llm_voice"}), "data_use": {"google"}}

    async def _attested(_session: Any, *, engine: str, at: Any) -> frozenset[str]:
        return frozenset(state["attested"])

    async def _workspaces() -> list[Any]:
        return []

    monkeypatch.setattr(own_model, "attested_rate_keys", _attested)
    monkeypatch.setattr(own_model, "own_model_workspaces", _workspaces)
    monkeypatch.setattr(own_model, "dashboard_data_use_attested", lambda: state["data_use"])
    monkeypatch.setattr(own_model, "unofferable_reason", lambda model, **_: None)
    monkeypatch.setattr(
        own_model, "own_model_offerable_models", lambda: frozenset({"gemini-3.1-flash-lite"})
    )
    monkeypatch.setattr(get_settings(), "gemini_api_key", "AIza-test")
    return state


async def test_our_model_may_be_switched_on_once_everything_is_in_place(
    readiness_inputs: dict[str, Any],
) -> None:
    readiness = await own_model.own_model_readiness(object(), engine="thinnest")  # type: ignore[arg-type]
    assert readiness.ready and readiness.missing() == []
    await own_model.assert_own_model_ready(object(), True)  # type: ignore[arg-type]


@pytest.mark.parametrize("gap", ["key", "data_use", "minute"])
async def test_switching_our_model_on_is_refused_naming_what_is_missing(
    readiness_inputs: dict[str, Any], monkeypatch: pytest.MonkeyPatch, gap: str
) -> None:
    if gap == "key":
        monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    elif gap == "data_use":
        readiness_inputs["data_use"] = set()
    else:
        readiness_inputs["attested"] = frozenset()
    with pytest.raises(ProblemError) as caught:
        await own_model.assert_own_model_ready(object(), True)  # type: ignore[arg-type]
    assert caught.value.code == OWN_MODEL_NOT_READY
    words = {"key": "Google (Gemini) API key", "data_use": "gate 41", "minute": "byok_llm_voice"}
    assert words[gap] in (caught.value.detail or "")
    # Switching off is never refused.
    await own_model.assert_own_model_ready(object(), False)  # type: ignore[arg-type]


# --- one client's workspace ---------------------------------------------------------------


class _OwnModelEngine(HostingEngine):
    """A hosting engine that also takes our model key, holding the vendor's `GET /byok`."""

    def __init__(self, state: OwnVoiceKeyState, **kw: Any) -> None:
        super().__init__(key_state=state, **kw)
        self.state = state
        self.calls: list[str] = []

    async def own_key_state(self) -> OwnVoiceKeyState:
        return self.state

    async def install_own_model_key(self, *, provider: str, api_key: str, model: str) -> None:
        self.calls.append(f"install:{provider}:{model}")
        self.state = self.state.model_copy(
            update={"llm_provider": provider, "llm_model": model, "llm_verified": True}
        )

    async def enable_own_model_key(self) -> OwnVoiceKeyState:
        self.calls.append("enable")
        self.state = self.state.model_copy(update={"enabled": True, "using": "own"})
        return self.state

    async def set_agent_own_keys(self, ref: str, *, own_voice: bool, own_model: str | None) -> None:
        self.calls.append(f"agent:{ref}")


@pytest.fixture
def records(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    recorded: list[str | None] = []

    async def _record(_session: Any, _tenant: UUID, *, error_code: str | None) -> None:
        recorded.append(error_code)

    async def _kept_off(*_a: Any, **_k: Any) -> int:
        return 0

    monkeypatch.setattr(own_model, "record_own_model_check", _record)
    monkeypatch.setattr(studio_module, "keep_clear_agents_off", _kept_off)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "AIza-test")
    return recorded


async def test_a_workspace_with_its_keys_off_gets_our_key_and_scope_llm(
    records: list[str | None],
) -> None:
    engine = _OwnModelEngine(
        OwnVoiceKeyState(enabled=False, scope=None, complete=False, using="none")
    )
    await ensure_own_model_in(object(), engine, tenant_id=TENANT, workspace=WS)  # type: ignore[arg-type]
    default = get_settings().thinnest_own_model_default
    assert engine.calls == [f"install:google:{default}", "enable"]
    assert records == [None]


async def test_a_studio_workspace_keeps_its_scope_and_only_gains_our_key(
    records: list[str | None],
) -> None:
    studio = OwnVoiceKeyState(
        enabled=True, scope="voice", complete=True, using="own", voice_provider="cartesia"
    )
    engine = _OwnModelEngine(studio)
    await ensure_own_model_in(object(), engine, tenant_id=TENANT, workspace=WS)  # type: ignore[arg-type]
    assert engine.calls == [f"install:google:{get_settings().thinnest_own_model_default}"]
    assert engine.state.scope == "voice"


async def test_a_ready_workspace_is_only_recorded(records: list[str | None]) -> None:
    ready = OwnVoiceKeyState(
        enabled=True,
        scope="llm",
        complete=True,
        using="own",
        llm_provider="google",
        llm_model="gemini-2.5-flash-lite",
        llm_verified=True,
    )
    engine = _OwnModelEngine(ready)
    await ensure_own_model_in(object(), engine, tenant_id=TENANT, workspace=WS)  # type: ignore[arg-type]
    assert engine.calls == [] and records == [None]


async def test_a_failed_set_up_is_recorded_and_refused_to_a_client_without_a_vendor_name(
    records: list[str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    engine = _OwnModelEngine(
        OwnVoiceKeyState(enabled=False, scope=None, complete=False, using="none")
    )
    with pytest.raises(ProblemError) as caught:
        await ensure_own_model_in(object(), engine, tenant_id=TENANT, workspace=WS)  # type: ignore[arg-type]
    assert caught.value.code == "own_model_account_not_ready"
    assert "Google" not in (caught.value.detail or "")
    assert records == ["own_model_key_missing"]


async def test_agents_that_would_follow_the_workspace_are_kept_off_before_it_switches_on(
    records: list[str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _one_unconfirmed(*_a: Any, **_k: Any) -> int:
        return 1

    monkeypatch.setattr(studio_module, "keep_clear_agents_off", _one_unconfirmed)
    engine = _OwnModelEngine(
        OwnVoiceKeyState(enabled=False, scope=None, complete=False, using="none")
    )
    with pytest.raises(ProblemError) as caught:
        await ensure_own_model_in(
            object(),  # type: ignore[arg-type]
            engine,
            tenant_id=TENANT,
            workspace=WS,
            audience="operator",
        )
    assert caught.value.code == "own_model_agents_not_kept_off"
    assert "enable" not in engine.calls


# --- the console switch -------------------------------------------------------------------


async def test_the_console_refuses_the_switch_before_it_is_ready_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.db.session import untenanted_session
    from apps.api.ops import config_service
    from sqlalchemy import text

    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as refused:
            await config_service.set_value(
                session,
                key="thinnest_own_model",
                value=True,
                note="own_model_test",
                actor_id=admin_id,
                expected_revision=0,
            )
        stored = (
            await session.execute(
                text("SELECT count(*) FROM platform_settings WHERE key = 'thinnest_own_model'")
            )
        ).scalar_one()
    assert refused.value.code == OWN_MODEL_NOT_READY
    assert "Google (Gemini) API key" in (refused.value.detail or "")
    assert stored == 0


# --- publish on our model -----------------------------------------------------------------

from tests.hosted_voice_fakes import OFF_KEY, CatalogueRows, selected  # noqa: E402
from tests.thinnest_engine_seams_test import (  # noqa: E402
    _agent,
    _publish,
    _set_columns,
    attested,
    no_webhook,
)
from tests.workspace_support import workspace_of  # noqa: E402

__all__ = ["attested", "no_webhook"]  # fixtures, imported for pytest


class _PublishingEngine(HostingEngine):
    """`HostingEngine` that also takes our model key per workspace and holds each agent's
    model of our key as the vendor would."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.models_held: dict[str, str | None] = {}
        self.model_keys_in: list[str | None] = []

    async def install_own_model_key(self, *, provider: str, api_key: str, model: str) -> None:
        from apps.api.engine.thinnest_workspace import current_workspace

        self.model_keys_in.append(current_workspace())
        state = await self.own_key_state()
        self._set_state(
            state.model_copy(
                update={"llm_provider": provider, "llm_model": model, "llm_verified": True}
            )
        )

    async def enable_own_model_key(self) -> OwnVoiceKeyState:
        state = await self.own_key_state()
        self._set_state(state.model_copy(update={"enabled": True, "using": "own", "scope": "llm"}))
        return await self.own_key_state()

    async def set_agent_own_keys(self, ref: str, *, own_voice: bool, own_model: str | None) -> None:
        self.own_voice_key[ref] = own_voice
        self.models_held[ref] = own_model

    async def create_agent(self, cfg: AgentConfig) -> str:
        ref = await super().create_agent(cfg)
        self.models_held[ref] = cfg.engine_own_model
        return ref

    async def update_agent(self, ref: str, cfg: AgentConfig) -> None:
        await super().update_agent(ref, cfg)
        self.models_held[ref] = cfg.engine_own_model

    async def get_agent(self, ref: str) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        return snapshot.model_copy(
            update={
                "engine_own_model": self.models_held.get(ref),
                "engine_own_model_readable": True,
            }
        )


@pytest.fixture
def own_model_on(monkeypatch: pytest.MonkeyPatch, attested: set[str]) -> set[str]:
    from apps.api.agents import service

    async def _keys(_session: Any, *, engine: str, at: Any) -> frozenset[str]:
        return frozenset(attested)

    monkeypatch.setattr(get_settings(), "thinnest_own_model", True)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "AIza-test")
    monkeypatch.setattr(own_model, "offerable_own_models", lambda: (THINNEST_OWN_MODEL_DEFAULT,))
    monkeypatch.setattr(service, "attested_rate_keys", _keys)
    attested.add("byok_llm_voice")
    return attested


async def _route_model(tenant_id: Any, ref: str) -> tuple[str, str | None]:
    from apps.api.db.session import tenant_session
    from sqlalchemy import text

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_rate_key, engine_own_model FROM engine_agent_routes "
                    "WHERE engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).one()
    return str(row[0]), row[1]


async def test_a_clear_agent_on_our_model_keeps_its_band_and_runs_our_key_in_its_workspace(
    own_model_on: set[str], no_webhook: None, hosted_rows: CatalogueRows
) -> None:
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, None)
    with selected(_PublishingEngine(key_state=OFF_KEY)) as engine:
        ref = await _publish(tenant_id, agent_id)
    assert isinstance(engine, _PublishingEngine)
    sent = engine.sent[-1]
    assert (sent.engine_own_voice_key, sent.engine_own_model) == (False, THINNEST_OWN_MODEL_DEFAULT)
    assert engine.model_keys_in == [workspace_of(UUID(str(tenant_id)))]
    assert engine.key_state.llm_provider is None  # never our developer workspace
    assert await _route_model(tenant_id, ref) == ("studio", THINNEST_OWN_MODEL_DEFAULT)


async def test_a_studio_agent_on_our_model_meters_the_own_voice_and_model_minute(
    own_model_on: set[str],
    no_webhook: None,
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "cartesia_api_key", "sk_car_test")
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("byok")
    await _set_columns(tenant_id, agent_id, voice, None)
    with selected(_PublishingEngine(key_state=OFF_KEY)) as engine:
        ref = await _publish(tenant_id, agent_id)
    assert isinstance(engine, _PublishingEngine)
    sent = engine.sent[-1]
    assert (sent.engine_own_voice_key, sent.engine_own_model) == (True, THINNEST_OWN_MODEL_DEFAULT)
    ws = workspace_of(UUID(str(tenant_id)))
    # Studio's workspace keeps its own scope; our model key is added beside our voice key.
    assert engine.workspace_keys[ws].scope == "voice"
    assert engine.workspace_keys[ws].llm_provider == "google"
    assert await _route_model(tenant_id, ref) == ("byok_llm_voice", THINNEST_OWN_MODEL_DEFAULT)


async def test_a_studio_agent_on_our_model_is_refused_while_its_minute_is_unpriced(
    own_model_on: set[str],
    no_webhook: None,
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "cartesia_api_key", "sk_car_test")
    own_model_on.discard("byok_llm_voice")
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("byok")
    await _set_columns(tenant_id, agent_id, voice, None)
    with (
        selected(_PublishingEngine(key_state=OFF_KEY)) as engine,
        pytest.raises(ProblemError) as caught,
    ):
        await _publish(tenant_id, agent_id)
    assert caught.value.code == "own_model_minute_unpriced"
    assert isinstance(engine, _PublishingEngine) and engine.sent == []


async def test_switching_our_model_off_puts_the_agent_back_on_the_platforms_model(
    own_model_on: set[str],
    no_webhook: None,
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, "byok:gemini-2.5-flash-lite")
    engine = _PublishingEngine(key_state=OFF_KEY)
    with selected(engine):
        ref = await _publish(tenant_id, agent_id)
        monkeypatch.setattr(get_settings(), "thinnest_own_model", False)
        await _publish(tenant_id, agent_id)
    sent = engine.sent[-1]
    assert (sent.engine_own_voice_key, sent.engine_own_model) == (False, None)
    assert sent.engine_model_id is None  # a choice of our model is never sent as theirs
    assert await _route_model(tenant_id, ref) == ("studio", None)


async def test_a_free_trial_agent_stays_on_the_platforms_model_with_our_model_on(
    own_model_on: set[str], no_webhook: None, hosted_rows: CatalogueRows
) -> None:
    """A trial agent lives in our developer workspace (D-697), where our model key would
    reach every client without keys of its own: it is published on the platform's model,
    and no key of ours is installed anywhere."""
    from apps.api.billing.trials import start_trial
    from apps.api.db.session import tenant_session
    from sqlalchemy import text

    tenant_id, agent_id = await _agent()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        # A trial agent places test calls and answers nothing (D-697), and an outgoing call
        # opens on its announcement.
        await session.execute(
            text(
                "UPDATE agents SET direction = 'outbound', ai_disclosure_enabled = true "
                "WHERE id = :a"
            ),
            {"a": agent_id},
        )
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, None)
    with selected(_PublishingEngine(key_state=OFF_KEY)) as engine:
        ref = await _publish(tenant_id, agent_id)
    assert isinstance(engine, _PublishingEngine)
    sent = engine.sent[-1]
    assert sent.engine_workspace is None
    assert (sent.engine_own_voice_key, sent.engine_own_model) == (False, None)
    assert engine.model_keys_in == []
    assert await _route_model(tenant_id, ref) == ("studio", None)


# --- D-769: per-agent scope kept, and both Studio keys before the write --------------------


@pytest.mark.parametrize("held", ["workspace", "voice"])
async def test_a_studio_agent_whose_scope_the_platform_did_not_keep_is_refused(held: str) -> None:
    """Per-agent scopes are not live at the vendor until its next release (ThinnestAI, 14 Oct
    2026): an agent sent `llm_voice` that reads back following the workspace, or on `voice`,
    is not answering on our model, and the publish read-back says so."""
    routes = {
        ("GET", "/agents/ag_9", None): _ok({"id": "ag_9", "instructions": "x", "byok": held}),
        ("GET", "/agents/ag_9/knowledge", None): _ok({"items": [], "nextCursor": None}),
    }
    snapshot = await _engine(_Vendor(routes)).get_agent("ag_9")
    cfg = _cfg(engine_own_voice_key=True, engine_own_model="gemini-2.5-flash-lite")
    assert _own_voice_key_verdict(cfg, snapshot) is False


class _KeysAtWriteEngine(_PublishingEngine):
    """Records the client workspace's own-keys state at the moment the agent is written."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.keys_at_write: list[OwnVoiceKeyState] = []

    async def create_agent(self, cfg: AgentConfig) -> str:
        with in_workspace(cfg.engine_workspace):
            self.keys_at_write.append(await self.own_key_state())
        return await super().create_agent(cfg)


async def test_a_studio_agent_on_our_model_is_written_only_after_both_keys_read_back(
    own_model_on: set[str],
    no_webhook: None,
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "cartesia_api_key", "sk_car_test")
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("byok")
    await _set_columns(tenant_id, agent_id, voice, None)
    with selected(_KeysAtWriteEngine(key_state=OFF_KEY)) as engine:
        await _publish(tenant_id, agent_id)
    assert isinstance(engine, _KeysAtWriteEngine)
    [state] = engine.keys_at_write
    assert state.speaks_on_own_voice and state.voice_provider == "cartesia"
    assert (state.llm_provider, state.llm_verified) == ("google", True)


class _VoiceKeyLostEngine(_PublishingEngine):
    """Installing our model key leaves the workspace without its verified voice key."""

    async def install_own_model_key(self, *, provider: str, api_key: str, model: str) -> None:
        await super().install_own_model_key(provider=provider, api_key=api_key, model=model)
        state = await self.own_key_state()
        self._set_state(state.model_copy(update={"voice_provider": None, "complete": False}))


async def test_a_studio_agent_on_our_model_is_refused_when_the_voice_key_is_gone(
    own_model_on: set[str],
    no_webhook: None,
    hosted_rows: CatalogueRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "cartesia_api_key", "sk_car_test")
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("byok")
    await _set_columns(tenant_id, agent_id, voice, None)
    with (
        selected(_VoiceKeyLostEngine(key_state=OFF_KEY)) as engine,
        pytest.raises(ProblemError) as caught,
    ):
        await _publish(tenant_id, agent_id)
    assert caught.value.code == studio_module.STUDIO_ACCOUNT_NOT_READY
    assert isinstance(engine, _VoiceKeyLostEngine) and engine.sent == []
