"""The shared trial number's own line (D-742): one never-answering agent in our developer
workspace whose `voice.unavailableMessage` tells whoever rings back what the number is
(docs.thinnest.ai api-reference/agents/create-agent `AgentVoiceInput`, channels/voice "When
Answer calls is off", read 11 Oct 2026). Made once, found by its name, repaired on drift,
kept as the number's line while each test call borrows it for calling out.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from apps.api.campaigns import engine_numbers
from apps.api.core.settings import get_settings
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.engine.thinnest_numbers import ThinnestNumbers, set_thinnest_numbers
from apps.api.engine.trial_line import TRIAL_LINE_AGENT_NAME

TRIAL = "+918049990001"
BASE_URL = "https://app.thinnest.ai/api/v1"


class Platform:
    """The developer workspace's agents and the shared number, in memory."""

    def __init__(self) -> None:
        self.agents: dict[str, dict[str, Any]] = {}
        self.number: dict[str, Any] = {
            "number": TRIAL.removeprefix("+"),
            "source": "rented",
            "agent": None,
            "callingAgent": None,
        }
        self.requests: list[tuple[str, str, Any]] = []
        #: The platform refuses a number's line to an agent whose voice is off.
        self.needs_voice_on = False
        #: The platform refuses `phone` to an agent with no number to answer or call from.
        self.refuse_phone = False
        #: The platform answers the agent write without keeping `phone`.
        self.drop_phone = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert "Thinnest-Workspace" not in request.headers
        path = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))
        if path == "/agents" and request.method == "GET":
            return httpx.Response(
                200, json={"items": list(self.agents.values()), "nextCursor": None}
            )
        if path == "/agents" and request.method == "POST":
            ref = f"ag_{len(self.agents) + 1}"
            self.agents[ref] = {"id": ref, "name": body["name"], "voice": dict(body["voice"])}
            return httpx.Response(201, json=self.agents[ref])
        if path.startswith("/agents/") and request.method == "PATCH":
            if self.refuse_phone and "phone" in body["voice"].get("surfaces", ()):
                return httpx.Response(
                    409, json={"error": "No number.", "code": "phone_number_required"}
                )
            row = self.agents[path.removeprefix("/agents/")]
            if not self.drop_phone:
                row["voice"].update(body["voice"])
            return httpx.Response(200, json=row)
        if path.startswith("/phone-numbers/"):
            if request.method == "PATCH":
                wanted = body.get("agent")
                if (
                    wanted
                    and self.needs_voice_on
                    and not self.agents[wanted]["voice"]["answersCalls"]
                ):
                    return httpx.Response(
                        409, json={"error": "Turn voice on.", "code": "agent_voice_off"}
                    )
                self.number.update(body)
            return httpx.Response(200, json=self.number)
        return httpx.Response(404, json={"error": "no", "code": "not_found"})


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[Platform]:
    fake = Platform()
    transport = httpx.MockTransport(fake.handler)
    engine = ThinnestEngine(
        api_key="ta_live_test", client=httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    )
    set_thinnest_numbers(
        ThinnestNumbers(
            api_key="ta_live_test",
            client=httpx.AsyncClient(transport=transport, base_url=BASE_URL),
        )
    )
    monkeypatch.setattr(engine_numbers, "get_engine", lambda: engine)
    monkeypatch.setattr(engine_numbers, "_TRIAL_LINE_AGENT", None)
    monkeypatch.setattr(get_settings(), "trial_caller_number", TRIAL)
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    yield fake
    set_thinnest_numbers(None)


def test_the_message_fits_the_platforms_limit_and_names_no_provider() -> None:
    assert len(engine_numbers.TRIAL_LINE_MESSAGE) <= 300
    assert "thinnest" not in engine_numbers.TRIAL_LINE_MESSAGE.lower()


async def test_the_line_is_made_once_paused_with_our_message_and_attached(
    platform: Platform,
) -> None:
    state = await engine_numbers.converge_trial_line()
    assert state.state == "ready"
    (agent,) = platform.agents.values()
    assert agent["name"] == TRIAL_LINE_AGENT_NAME
    assert agent["voice"] == {
        "answersCalls": False,
        "unavailableMessage": engine_numbers.TRIAL_LINE_MESSAGE,
    }
    assert platform.number["agent"] == agent["id"]
    again = await engine_numbers.converge_trial_line()
    assert again.state == "ready" and len(platform.agents) == 1
    assert (await engine_numbers.read_trial_line()).state == "ready"


async def test_a_line_switched_on_or_reworded_in_the_console_is_put_back(
    platform: Platform,
) -> None:
    await engine_numbers.converge_trial_line()
    (agent,) = platform.agents.values()
    agent["voice"].update(answersCalls=True, unavailableMessage="Hello")
    assert (await engine_numbers.read_trial_line()).state == "drifted"
    await engine_numbers.converge_trial_line()
    assert agent["voice"]["answersCalls"] is False
    assert agent["voice"]["unavailableMessage"] == engine_numbers.TRIAL_LINE_MESSAGE


async def test_an_attach_refused_for_voice_off_switches_it_on_only_for_the_attach(
    platform: Platform,
) -> None:
    platform.needs_voice_on = True
    state = await engine_numbers.converge_trial_line()
    (agent,) = platform.agents.values()
    assert state.state == "ready" and platform.number["agent"] == agent["id"]
    assert agent["voice"]["answersCalls"] is False


def _trial_agent(platform: Platform) -> dict[str, Any]:
    """A client's trial agent as a publish leaves it: answering, on no surface (F1)."""
    platform.agents["ag_trial"] = {
        "id": "ag_trial",
        "name": "Receptionist",
        "voice": {"answersCalls": True, "surfaces": []},
    }
    return platform.agents["ag_trial"]


async def test_a_test_call_borrows_the_number_and_its_line_stays_the_paused_agent(
    platform: Platform,
) -> None:
    """The borrower gets `phone`, so the platform will place its call (`calling_not_set_up`
    otherwise, incident 15 Oct 2026); the number's line stays the agent that answers
    nobody, so a caller ringing back hears the trial message."""
    trial = _trial_agent(platform)
    assert await engine_numbers.lend_trial_line("ag_trial")
    line = next(a for a in platform.agents.values() if a["name"] == TRIAL_LINE_AGENT_NAME)
    assert platform.number["agent"] == line["id"]
    assert platform.number["callingAgent"] == "ag_trial"
    assert trial["voice"]["surfaces"] == ["phone"]
    assert line["voice"]["answersCalls"] is False
    assert line["voice"]["unavailableMessage"] == engine_numbers.TRIAL_LINE_MESSAGE


@pytest.mark.parametrize("refusal", ["refuse_phone", "drop_phone"])
async def test_a_borrower_refused_the_phone_is_reported_not_lent(
    platform: Platform, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    _trial_agent(platform)
    await engine_numbers.converge_trial_line()
    setattr(platform, refusal, True)
    alarms: list[str] = []
    monkeypatch.setattr(engine_numbers, "alert", lambda _s, code, **_: alarms.append(code))
    assert not await engine_numbers.lend_trial_line("ag_trial")
    assert alarms == ["trial_line_lend_failed"]


async def test_a_borrower_whose_line_is_paused_is_reported_and_left_paused(
    platform: Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Place Call needs the borrower's Answer calls on as well as `phone` (ThinnestAI,
    18 Oct 2026). Off is our pause, so it is reported rather than switched back on."""
    trial = _trial_agent(platform)
    trial["voice"]["answersCalls"] = False
    await engine_numbers.converge_trial_line()
    alarms: list[str] = []
    monkeypatch.setattr(engine_numbers, "alert", lambda _s, code, **_: alarms.append(code))
    assert not await engine_numbers.lend_trial_line("ag_trial")
    assert alarms == ["trial_line_lend_failed"]
    assert trial["voice"]["answersCalls"] is False


async def test_without_a_number_nothing_is_made(
    platform: Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "trial_caller_number", None)
    assert (await engine_numbers.converge_trial_line()).state == "no_number"
    assert platform.agents == {}
