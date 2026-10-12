"""ThinnestAI's 12 Oct 2026 answers, as the adapter sends and reads them (founder decisions
F1-F10, `docs/vendor/thinnest-build-plan-2026-10-12.md`).

Every field name, range and default is docs.thinnest.ai as read 12 Oct 2026:
`api-reference/agents/update-agent` and `get-agent` (`voice`), `errors`, `models/list-models`,
`customers/update-customer`, `phone-numbers/rent-phone-number`.

1. **Where an agent answers (F1).** Phone only once a number is attached, nowhere before; a
   409 `phone_number_required` is a refusal in words.
2. **Voice settings (F3, F4, F9, F10).** The client's and the platform's values are sent on
   every write, read back, and repaired under our own labels.
3. **Model tiers.** `callTier` and the minute price are read and checked against the
   recorded band; nothing is billed from them.
4. **Call lines per customer.** Set and read back.
5. **Renting a number.** Our purchase id as the idempotency key; an attempt still in
   flight is read back, never taken as nothing bought.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.agents.engine_model_bands import band_disagrees
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.core.errors import ProblemError
from apps.api.engine.catalogue import CatalogueModel
from apps.api.engine.thinnest import (
    _SETTING_KEYS,
    BASE_URL,
    PLATFORM_VOICE_VALUES,
    ThinnestEngine,
)
from apps.api.engine.thinnest_customers import ThinnestCustomers
from apps.api.engine.thinnest_numbers import ThinnestNumbers
from apps.api.engine.vendor_http import EngineRejectedError
from tests.thinnest_engine_test import (
    WS,
    _agent_write,
    _body,
    _cfg,
    _engine,
    _recorder,
    tools_state,
)

AGENT = f"ag_1@{WS}"


def _held(cfg: Any) -> dict[str, Any]:
    """`GET /agents/{id}` for an agent holding exactly what a publish of `cfg` sends."""
    return ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)


def _settings_engine(cfg: Any, held: dict[str, Any], sent: list[dict[str, Any]]) -> ThinnestEngine:
    engine = ThinnestEngine(api_key="ta_live_test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state(engine.built_in_tools_body(cfg)))
        if request.method == "GET":
            return httpx.Response(200, json=held)
        sent.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={})

    engine._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE_URL)
    return engine


# --- 1. where an agent answers -----------------------------------------------------------


async def test_an_agent_with_a_number_answers_the_phone_only() -> None:
    handler, seen = _recorder(
        {
            ("GET", "/agents"): httpx.Response(200, json={"items": [], "nextCursor": None}),
            ("POST", "/agents"): httpx.Response(201, json={"id": "ag_1"}),
        }
    )
    await _engine(handler).create_agent(_cfg(has_phone_number=True))
    assert _body(_agent_write(seen))["voice"]["surfaces"] == ["phone"]


async def test_an_agent_without_a_number_answers_nowhere_yet() -> None:
    """Naming phone before a number is attached is a 409; the website button and WhatsApp a
    new agent starts with are never wanted."""
    handler, seen = _recorder({("PATCH", "/agents/ag_1"): httpx.Response(200, json={})})
    await _engine(handler).update_agent(AGENT, _cfg(has_phone_number=False))
    assert _body(_agent_write(seen))["voice"]["surfaces"] == []


async def test_phone_number_required_is_refused_in_words() -> None:
    handler, _seen = _recorder(
        {
            ("PATCH", "/agents/ag_1"): httpx.Response(
                409,
                json={
                    "error": "`voice.surfaces` includes `phone`, but this agent has no phone "
                    "number. Attach one first.",
                    "code": "phone_number_required",
                },
            )
        }
    )
    with pytest.raises(ProblemError) as refused:
        await _engine(handler).update_agent(AGENT, _cfg(has_phone_number=True))
    assert refused.value.code == "engine_agent_number_missing"
    assert not isinstance(refused.value, EngineRejectedError)
    assert "ThinnestAI" not in f"{refused.value.title} {refused.value.detail}"


async def test_a_refused_empty_list_saves_the_agent_without_it_and_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The docs do not say whether `surfaces: []` is accepted; if it is not, a write to an
    agent with no number must still go through, or every such agent stops updating."""
    import apps.api.engine.thinnest as thinnest

    alarms: list[str] = []
    monkeypatch.setattr(thinnest, "alert", lambda _kind, code, **_kw: alarms.append(code))
    writes: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            if request.method == "PATCH":
                return httpx.Response(200, json=tools_state(json.loads(request.content)))
            return httpx.Response(200, json=tools_state())
        body = json.loads(request.content or b"{}")
        writes.append(body)
        if "surfaces" in body.get("voice", {}):
            return httpx.Response(400, json={"error": "invalid", "code": "invalid_request"})
        return httpx.Response(200, json={})

    await _engine(handler).update_agent(AGENT, _cfg(has_phone_number=False))
    assert [w["voice"].get("surfaces", "absent") for w in writes] == [[], "absent"]
    assert alarms == ["engine_agent_surfaces_refused"]


async def test_a_400_about_another_field_raises_the_first_refusal_without_the_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The write without `surfaces` is refused too, so the 400 was about something else:
    the first refusal reaches the caller and no surfaces alarm is raised."""
    import apps.api.engine.thinnest as thinnest

    alarms: list[str] = []
    monkeypatch.setattr(thinnest, "alert", lambda _kind, code, **_kw: alarms.append(code))
    writes: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state())
        body = json.loads(request.content or b"{}")
        writes.append(body)
        code = "first_refusal" if len(writes) == 1 else "second_refusal"
        return httpx.Response(400, json={"error": "invalid", "code": code})

    with pytest.raises(EngineRejectedError) as refused:
        await _engine(handler).update_agent(AGENT, _cfg(has_phone_number=False))
    assert refused.value.vendor_code == "first_refusal"
    assert [w["voice"].get("surfaces", "absent") for w in writes] == [[], "absent"]
    assert alarms == []


async def test_a_400_with_phone_named_is_not_retried() -> None:
    handler, seen = _recorder(
        {("PATCH", "/agents/ag_1"): httpx.Response(400, json={"error": "x", "code": "invalid"})}
    )
    with pytest.raises(EngineRejectedError):
        await _engine(handler).update_agent(AGENT, _cfg(has_phone_number=True))
    agent_writes = [r for r in seen if r.method == "PATCH" and r.url.path.endswith("/agents/ag_1")]
    assert len(agent_writes) == 1


async def test_another_409_on_an_agent_write_is_not_read_as_a_missing_number() -> None:
    handler, _seen = _recorder(
        {("PATCH", "/agents/ag_1"): httpx.Response(409, json={"error": "x", "code": "conflict"})}
    )
    with pytest.raises(EngineRejectedError):
        await _engine(handler).update_agent(AGENT, _cfg())


# --- 2. voice settings ---------------------------------------------------------------------


def test_the_client_settings_and_the_platform_values_are_on_every_agent() -> None:
    voice = _held(
        _cfg(
            nudge_after_seconds=12,
            nudge_count=2,
            nudge_phrase="Are you there?",
            end_after_silence_seconds=40,
            filler_lines=("One moment.", "Let me check."),
            ambience="office-quiet",
            ambience_volume_pct=35,
        )
    )["voice"]
    assert (voice["nudgeAfterSeconds"], voice["nudges"], voice["nudgePhrase"]) == (
        12,
        2,
        "Are you there?",
    )
    assert voice["endAfterSilenceSeconds"] == 40
    assert voice["thinking"] is True
    assert voice["thinkingLines"] == ["One moment.", "Let me check."]
    assert (voice["ambience"], voice["ambienceVolume"]) == ("office-quiet", 0.35)
    for name, value in PLATFORM_VOICE_VALUES.items():
        assert voice[name] == value
    assert voice["endPhrases"] == []
    assert voice["greetingUninterruptible"] is False


def test_the_defaults_leave_the_wording_and_fillers_to_the_platform() -> None:
    """F9: ask after 8 s, once; hang up after 20 s. An empty prompt line or filler list is
    the platform's own, in the caller's language."""
    voice = _held(_cfg())["voice"]
    assert (voice["nudgeAfterSeconds"], voice["nudges"], voice["nudgePhrase"]) == (8, 1, None)
    assert voice["endAfterSilenceSeconds"] == 20
    assert voice["thinkingLines"] == []
    assert (voice["ambience"], voice["ambienceVolume"]) == (None, 0.15)


def test_every_setting_the_adapter_compares_has_one_of_our_labels() -> None:
    assert set(_SETTING_KEYS) <= AGENT_SETTING_LABELS
    for label in _SETTING_KEYS:
        assert "." not in label and not any(ch.isupper() for ch in label)


async def test_a_held_agent_matching_the_publish_has_no_drift() -> None:
    cfg = _cfg(filler_lines=("One moment.",), ambience="office")
    held = _held(cfg)
    # Read back as the vendor stores them: `0.150`, a blank prompt line as null.
    held["voice"]["ambienceVolume"] = 0.150
    assert await _settings_engine(cfg, held, []).settings_drift(AGENT, cfg) == []


@pytest.mark.parametrize(
    ("field", "value", "label"),
    [
        ("nudgeAfterSeconds", None, "silence_prompt"),
        ("nudges", 3, "silence_prompt"),
        ("nudgePhrase", "Hello?", "silence_prompt"),
        ("endAfterSilenceSeconds", 60, "end_after_silence"),
        ("thinkingLines", ["Hmm."], "filler_lines"),
        ("thinking", False, "filler_lines"),
        ("thinkingDelayMs", 400, "filler_timing"),
        ("thinkingAtTurnEnd", True, "filler_timing"),
        ("ambience", "office", "background_sound"),
        ("ambienceVolume", 0.5, "background_sound"),
        ("interruptWords", 1, "interruptions"),
        ("neverInterrupt", True, "interruptions"),
        ("greetingUninterruptible", True, "interruptions"),
        ("holdShortSpeech", False, "interruptions"),
        ("endPhrases", ["bye"], "end_phrases"),
        ("endPhrases", None, "end_phrases"),
    ],
)
async def test_a_console_change_reads_as_drift_and_is_repaired(
    field: str, value: Any, label: str
) -> None:
    cfg = _cfg()
    held = _held(cfg)
    held["voice"][field] = value
    sent: list[dict[str, Any]] = []
    engine = _settings_engine(cfg, held, sent)
    assert await engine.settings_drift(AGENT, cfg) == [label]
    await engine.repair_settings(AGENT, cfg, [label])
    wanted = _held(cfg)["voice"]
    assert sent == [
        {
            "voice": {
                key.removeprefix("voice."): wanted[key.removeprefix("voice.")]
                for key in _SETTING_KEYS[label]
            }
        }
    ]


# --- 3. model tiers ------------------------------------------------------------------------


async def test_the_catalogue_reads_the_platforms_tier_and_minute_price() -> None:
    handler, _seen = _recorder(
        {
            ("GET", "/models"): httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "gpt-5-mini",
                            "name": "GPT-5 Mini",
                            "voice": True,
                            "available": True,
                            "voiceOnlyByok": False,
                            "callTier": "premium",
                            "callPricePerMinuteMicro": 3_000_000,
                            "currency": "INR",
                        },
                        {
                            "id": "prana",
                            "name": "Prana",
                            "voice": True,
                            "available": True,
                            "voiceOnlyByok": True,
                            "callTier": "standard",
                            "callPricePerMinuteMicro": None,
                            "currency": None,
                        },
                        {"id": "odd", "name": "Odd", "callTier": "platinum"},
                    ]
                },
            )
        }
    )
    models = {m.model_id: m for m in (await _engine(handler).read_catalogue()).models}
    mini = models["gpt-5-mini"]
    assert (mini.listed_call_tier, mini.listed_price_per_minute, mini.listed_currency) == (
        "premium",
        Decimal("3"),
        "INR",
    )
    assert isinstance(mini.listed_price_per_minute, Decimal)
    prana = models["prana"]
    assert (prana.listed_call_tier, prana.listed_price_per_minute) == ("standard", None)
    assert models["odd"].listed_call_tier is None
    # The vendor's tier never stands in for the operator's record (hard rule 7).
    assert all(m.surcharge is None and m.tier is None for m in models.values())


def _model(**update: Any) -> CatalogueModel:
    base = CatalogueModel(model_id="m", label="M", call_capable=True, plan_allows=True)
    return base.model_copy(update=update)


@pytest.mark.parametrize(
    ("surcharge", "listed", "disagrees"),
    [
        ("none", "standard", False),
        ("premium", "premium", False),
        ("none", "premium", True),
        ("premium", "standard", True),
        (None, "premium", False),
        ("none", None, False),
    ],
)
def test_a_recorded_band_is_checked_against_the_platforms_tier(
    surcharge: str | None, listed: str | None, disagrees: bool
) -> None:
    assert band_disagrees(_model(surcharge=surcharge, listed_call_tier=listed)) is disagrees


# --- 4. call lines per customer ---------------------------------------------------------------


def _customers(handler: Any) -> ThinnestCustomers:
    return ThinnestCustomers(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


async def test_call_lines_are_set_on_the_customer_and_read_back() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        lines = json.loads(request.content)["allottedCallLines"] if request.content else 2
        return httpx.Response(200, json={"id": "org_c", "allottedCallLines": lines})

    customers = _customers(handler)
    assert await customers.set_customer_call_lines("org_c", 2) == 2
    assert await customers.read_customer_call_lines("org_c") == 2
    patch, get = seen
    assert (patch.method, patch.url.path) == ("PATCH", "/api/v1/customers/org_c")
    assert json.loads(patch.content) == {"allottedCallLines": 2}
    assert get.method == "GET"
    # `/customers/*` acts on our own account: never with the workspace header.
    assert all("Thinnest-Workspace" not in r.headers for r in seen)


async def test_a_cap_read_back_differently_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "org_c", "allottedCallLines": None})

    with pytest.raises(ProblemError) as refused:
        await _customers(handler).set_customer_call_lines("org_c", 1)
    assert refused.value.code == "engine_call_lines_not_saved"


async def test_no_cap_reads_as_none_and_a_missing_field_is_unreadable() -> None:
    answers = iter([{"id": "org_c", "allottedCallLines": None}, {"id": "org_c"}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(answers))

    customers = _customers(handler)
    assert await customers.read_customer_call_lines("org_c") is None
    with pytest.raises(ProblemError) as unreadable:
        await customers.read_customer_call_lines("org_c")
    assert unreadable.value.code == "engine_bad_response"


async def test_a_negative_cap_is_refused_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request")

    with pytest.raises(ProblemError) as refused:
        await _customers(handler).set_customer_call_lines("org_c", -1)
    assert refused.value.code == "engine_call_lines_invalid"


# --- 5. renting a number ---------------------------------------------------------------------


def _numbers(handler: Any) -> ThinnestNumbers:
    return ThinnestNumbers(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


_RENTED = {"number": "+918011112222", "source": "rented"}


async def test_a_rent_carries_our_purchase_id_as_its_idempotency_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_RENTED)

    rented = await _numbers(handler).rent(WS, "918011112222", attempt_id="p-1")
    assert rented.rented
    assert seen[0].headers["Idempotency-Key"] == "calevate-rent-p-1"
    assert seen[0].headers["Thinnest-Workspace"] == WS


async def test_an_attempt_still_in_flight_that_bought_the_number_is_the_number() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                409, json={"error": "still processing", "code": "idempotency_in_progress"}
            )
        return httpx.Response(200, json=_RENTED)

    rented = await _numbers(handler).rent(WS, "918011112222", attempt_id="p-1")
    assert rented.rented


@pytest.mark.parametrize("read_back", [404, 200])
async def test_an_attempt_still_in_flight_is_never_nothing_bought(read_back: int) -> None:
    """Not found yet, or found but not rented: unconfirmed, a problem the purchase
    resolves on the next press, never the refusal that settles it as nothing bought."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                409, json={"error": "still processing", "code": "idempotency_in_progress"}
            )
        if read_back == 404:
            return httpx.Response(404, json={"error": "not found", "code": "not_found"})
        return httpx.Response(200, json={"number": "+918011112222", "source": "imported"})

    with pytest.raises(ProblemError) as unknown:
        await _numbers(handler).rent(WS, "918011112222", attempt_id="p-1")
    assert unknown.value.code == "engine_number_rent_in_progress"
    assert not isinstance(unknown.value, EngineRejectedError)


async def test_a_number_somebody_holds_is_still_a_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "held", "code": "conflict"})

    with pytest.raises(EngineRejectedError) as refused:
        await _numbers(handler).rent(WS, "918011112222", attempt_id="p-1")
    assert refused.value.request_refused


async def test_a_release_told_the_workspace_is_unknown_is_not_taken_as_already_gone() -> None:
    """`404 workspace_not_found` is about the header, not the number (errors.md:90): the
    number may still be rented to us, so the release must not report it gone."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": "Workspace not found.", "code": "workspace_not_found"}
        )

    with pytest.raises(EngineRejectedError) as refused:
        await _numbers(handler).release("918011112222@org_gone")
    assert refused.value.vendor_code == "workspace_not_found"
    assert refused.value.object_absent is False


async def test_a_release_of_a_number_already_gone_is_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": "That number was not found.", "code": "not_found"}
        )

    await _numbers(handler).release("918011112222@org_c")
