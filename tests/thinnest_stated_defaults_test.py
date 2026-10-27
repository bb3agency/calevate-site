"""Vendor defaults this adapter now states rather than leaves to ThinnestAI (D-911).

Every field is `thinnest-findings/mirror/snapshots/2026-10-28/openapi.json`: `temperature`
(0-2, default 0.3), `voice.vocabulary` (the recogniser's custom vocabulary), the Ear-only
`backchannelDetection`/`backchannelWords`/`acknowledgementWords`, the tools' `recall` and
`verifyByCode`, `CallBilling.billedOn` and `PublicModel.billing`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.engine import thinnest
from apps.api.engine.hosted_platform import PLATFORM_AGENT_VALUES
from apps.api.engine.thinnest import (
    _SETTING_KEYS,
    AGENT_TEMPERATURE,
    BASE_URL,
    EAR_VOICE_VALUES,
    ThinnestEngine,
    parse_billing,
)
from tests.thinnest_engine_test import WS, _cfg, _engine, _recorder, tools_state

AGENT = f"ag_1@{WS}"


def _body(**update: Any) -> dict[str, Any]:
    return ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(**update))


def _settings_engine(
    cfg: Any, held: dict[str, Any], tools: dict[str, Any], sent: list[tuple[str, Any]]
) -> ThinnestEngine:
    engine = ThinnestEngine(api_key="ta_live_test")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/tools"):
            if request.method == "PATCH":
                sent.append(("tools", body))
                return httpx.Response(200, json=tools_state(body))
            return httpx.Response(200, json=tools)
        if request.method == "GET":
            return httpx.Response(200, json=held)
        sent.append(("agent", body))
        return httpx.Response(200, json={})

    engine._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE_URL)
    return engine


# --- what every write states ----------------------------------------------------------------


def test_every_write_states_the_wording_temperature_at_the_vendors_own_default() -> None:
    assert _body()["temperature"] == AGENT_TEMPERATURE == 0.3


@pytest.mark.parametrize(
    ("business", "vocabulary"),
    [
        ("Sunrise  Dental\tCare", ["Sunrise Dental Care"]),
        ("", []),
        ("   ", []),
        ("x" * 64, ["x" * 64]),
        ("x" * 65, []),
    ],
)
def test_the_business_name_is_the_recognisers_vocabulary(
    business: str, vocabulary: list[str]
) -> None:
    """One term of at most 64 characters; a longer name is left out rather than cut, since a
    cut name is a word nobody says and a longer term is refused with a 400."""
    assert _body(business=business)["voice"]["vocabulary"] == vocabulary


def test_the_backchannel_settings_are_stated_only_under_ear() -> None:
    timer = _body(turn_detection="timer")["voice"]
    assert not set(EAR_VOICE_VALUES) & set(timer)
    ear = _body(turn_detection="ear")["voice"]
    assert {key: ear[key] for key in EAR_VOICE_VALUES} == {
        "backchannelDetection": True,
        "backchannelWords": [],
        "acknowledgementWords": [],
    }


def test_the_tools_state_recall_and_code_verification() -> None:
    body = ThinnestEngine.built_in_tools_body(_cfg())
    assert (body["recall"], body["verifyByCode"]) == ("verified", False)


async def test_a_publish_refuses_tools_that_did_not_save_the_recall() -> None:
    handler, _seen = _recorder(
        {
            ("GET", "/agents"): httpx.Response(200, json={"items": [], "nextCursor": None}),
            ("POST", "/agents"): httpx.Response(201, json={"id": "ag_1"}),
            ("PATCH", "/agents/ag_1/tools"): httpx.Response(
                200, json=tools_state({"recall": "two_tier"})
            ),
        }
    )
    with pytest.raises(Exception) as caught:
        await _engine(handler).create_agent(_cfg())
    assert getattr(caught.value, "code", None) == "engine_tools_not_pinned"


@pytest.mark.parametrize(
    ("held", "drifted"),
    [
        ({"recall": "verified", "verifyByCode": False}, []),
        ({"recall": "two_tier", "verifyByCode": False}, ["recall"]),
        ({"recall": "verified", "verifyByCode": True}, ["verifyByCode"]),
        ({}, ["recall", "verifyByCode"]),
    ],
)
def test_the_tools_read_back_compares_recall_and_code_verification(
    held: dict[str, Any], drifted: list[str]
) -> None:
    wanted = ThinnestEngine.built_in_tools_body(_cfg())
    answer = {k: v for k, v in tools_state(wanted).items() if k not in ("recall", "verifyByCode")}
    assert thinnest._tools_drift(wanted, {**answer, **held}) == drifted


# --- the settings sweep ---------------------------------------------------------------------


def test_the_new_labels_are_ours() -> None:
    assert {"temperature", "vocabulary", "customer_recall"} <= AGENT_SETTING_LABELS
    assert set(_SETTING_KEYS) <= AGENT_SETTING_LABELS


async def test_an_agent_holding_what_we_send_has_no_drift_and_null_lists_are_empty() -> None:
    cfg = _cfg(business="", turn_detection="ear")
    held = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    # How an answer may spell "none": null for each list, a whole-number-looking float.
    held["voice"].update(vocabulary=None, backchannelWords=None, acknowledgementWords=None)
    held["temperature"] = 0.30
    tools = tools_state(ThinnestEngine.built_in_tools_body(cfg))
    assert await _settings_engine(cfg, held, tools, []).settings_drift(AGENT, cfg) == []


@pytest.mark.parametrize(
    ("where", "field", "value", "label"),
    [
        (None, "temperature", 0.7, "temperature"),
        (None, "temperature", None, "temperature"),
        ("voice", "vocabulary", [], "vocabulary"),
        ("voice", "vocabulary", ["Someone Else"], "vocabulary"),
        ("voice", "backchannelDetection", False, "turn_silence"),
        ("voice", "backchannelWords", ["hmm"], "turn_silence"),
    ],
)
async def test_a_console_change_reads_as_drift_and_is_repaired(
    where: str | None, field: str, value: Any, label: str
) -> None:
    cfg = _cfg(business="Sunrise Dental", turn_detection="ear")
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    held = json.loads(json.dumps(wanted))
    (held["voice"] if where else held)[field] = value
    tools = tools_state(ThinnestEngine.built_in_tools_body(cfg))
    sent: list[tuple[str, Any]] = []
    engine = _settings_engine(cfg, held, tools, sent)
    assert await engine.settings_drift(AGENT, cfg) == [label]
    await engine.repair_settings(AGENT, cfg, [label])
    [(route, body)] = sent
    assert route == "agent"
    if where:
        assert body["voice"][field] == wanted["voice"][field]
    else:
        assert body == {field: wanted[field]}


async def test_a_recall_moved_in_the_console_is_drift_and_the_tools_are_written_again() -> None:
    cfg = _cfg()
    held = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    tools = {**tools_state(ThinnestEngine.built_in_tools_body(cfg)), "recall": "trusted"}
    sent: list[tuple[str, Any]] = []
    engine = _settings_engine(cfg, held, tools, sent)
    assert await engine.settings_drift(AGENT, cfg) == ["customer_recall"]
    await engine.repair_settings(AGENT, cfg, ["customer_recall"])
    assert [route for route, _ in sent] == ["tools"]
    assert sent[0][1]["recall"] == "verified"


def test_a_deploy_that_changes_a_stated_default_republishes_every_agent() -> None:
    """Part of `live_apply.platform_prompt_revision`, so a change reaches live agents by the
    worker-start republish rather than as drift on each."""
    values = PLATFORM_AGENT_VALUES["thinnest"]
    assert values["temperature"] == AGENT_TEMPERATURE
    assert (values["recall"], values["verifyByCode"]) == ("verified", False)
    assert values["vocabulary"] == "business_name"
    assert all(values[key] == value for key, value in EAR_VOICE_VALUES.items())


# --- what is read ---------------------------------------------------------------------------

_BILLING = {
    "keys": "off",
    "voicePlan": "premium",
    "ratePerMinuteMicro": 2_000_000,
    "billedSeconds": 60,
    "currency": "INR",
    "chargedMicro": None,
}


@pytest.mark.parametrize(
    ("billed_on", "readable"), [("plan", True), (None, True), ("usage", False)]
)
def test_a_call_billed_on_usage_is_no_billing_we_read(
    billed_on: str | None, readable: bool
) -> None:
    value = dict(_BILLING) if billed_on is None else {**_BILLING, "billedOn": billed_on}
    assert (parse_billing(value) is not None) is readable


async def test_a_model_billed_on_usage_is_never_offered_for_calls() -> None:
    row = {"voice": True, "available": True, "voiceOnlyByok": False, "currency": "INR"}
    handler, _seen = _recorder(
        {
            ("GET", "/models"): httpx.Response(
                200,
                json={
                    "items": [
                        {**row, "id": "plain", "name": "Plain", "billing": "plan"},
                        {**row, "id": "old", "name": "Old"},
                        {**row, "id": "live", "name": "Live", "billing": "usage"},
                    ],
                    "nextCursor": None,
                },
            )
        }
    )
    models = {m.model_id: m for m in (await _engine(handler).read_catalogue()).models}
    assert models["plain"].call_capable and models["old"].call_capable
    assert not models["live"].call_capable
