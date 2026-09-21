"""Behavioural scenarios for handing a caller to a person — the in-call half.

Read `tests/scenario_harness.py` first: it says what a scenario here is and is not evidence
of. The short version is that the model is a stand-in, so what these assert is the SEAM —
that the outcome word reached the model at all, and that our own code never licenses the one
claim a failed handover must not produce.

**WHY THIS DESERVES ITS OWN FILE RATHER THAN A TENTH SCENARIO IN THE SUITE NEXT DOOR.**
Every other scenario over there is about what the agent SAYS. These are about what it says
when it has just been told it cannot do the thing a caller asked for, which is the moment a
model improvises — and the improvisation is "I am putting you through now", followed by
silence, followed by a disconnect. That is the worst outcome this feature has, worse than
refusing plainly, because the caller acts on it: they wait.

**THE DEFAULT PATH IS THE UNAVAILABLE ONE, AND IT IS FIRST HERE FOR THAT REASON.** No
deployment can transfer a caller today: `engine/pipecat.PIPECAT_CAPABILITIES` declares
`transfer=False` and `in_call_handoff=False`, because a transfer is an operation against the
carrier and the carrier's API is unread. So `not_available` is what every real call gets,
and the other outcomes are the ones the seam must already be honest about on the day a
carrier leg lands.

**NOTHING HERE IS VERTICAL-SPECIFIC.** The caller could be ringing a dealership, a coaching
centre, a law office or a clinic; the sentences are the same and the mechanism is the same.
WHEN an agent decides a person is needed is the client's own script and is deliberately not
simulated, asserted or encoded — see `_PERSON_REQUEST` in the harness.

**EVERY SCENARIO HAS A NEGATIVE CONTROL**, per the suite's own rule: a model that ignores
its instructions promises the transfer, so an assertion that the shipped path does not
promise one has something that really would have.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from calevate_shared.worker_api import (
    CallbackBookIn,
    CallbackCancelIn,
    CallbackCancelOut,
    CallbackToolOut,
    HandoffOutcome,
    HandoffToolIn,
    HandoffToolOut,
    OptOutToolIn,
    OptOutToolOut,
)
from scenario_harness import (
    CallerTurn,
    compose_agent_prompt,
    is_telugu,
    make_session_config,
    run_scenario,
    voice_safety_violations,
)
from voice_worker.api_client import WorkerApiError
from voice_worker.call_tools import HANDOFF_TOOL_NAME

#: What a caller hears and then WAITS on. Any of these in a reply to a failed handover is
#: the defect: the caller has been told a person is coming and they are not.
_TRANSFER_PROMISES: tuple[str, ...] = (
    "putting you through",
    "please hold",
    "connecting you now",
)


def transfer_promises(text: str) -> list[str]:
    """The promises `text` makes about a transfer, in the order they are defined."""
    lowered = text.lower()
    return [phrase for phrase in _TRANSFER_PROMISES if phrase in lowered]


@dataclass
class ScenarioToolApi:
    """The in-call tool API, staged. One programmed handover answer, nothing else faked.

    `unreachable` raises what the real client raises, which is the state every deployment
    meets eventually: the container is on Pipecat Cloud and our API is on a VPS in another
    country, with a caller on the line while the two fail to reach each other.
    """

    answer: HandoffToolOut
    unreachable: bool = False
    handoffs: list[HandoffToolIn] = field(default_factory=list)
    booked: list[CallbackBookIn] = field(default_factory=list)

    async def handoff(self, engine_call_id: str, request: HandoffToolIn) -> HandoffToolOut:
        if self.unreachable:
            raise WorkerApiError("the worker API could not be reached")
        self.handoffs.append(request)
        return self.answer

    async def opt_out(self, engine_call_id: str, request: OptOutToolIn) -> OptOutToolOut:
        raise AssertionError("no scenario here opts anybody out")

    async def book_callback(self, engine_call_id: str, request: CallbackBookIn) -> CallbackToolOut:
        self.booked.append(request)
        return CallbackToolOut(
            status="booked", say="booked", booked_for="Tuesday 22 September at 10:00 AM"
        )

    async def cancel_callback(
        self, engine_call_id: str, request: CallbackCancelIn
    ) -> CallbackCancelOut:
        raise AssertionError("no scenario here cancels a call-back")


def answering(outcome: HandoffOutcome, *, reason: str = "", say: str = "") -> ScenarioToolApi:
    return ScenarioToolApi(answer=HandoffToolOut(status=outcome, say=say, reason=reason))


ASKS_FOR_A_PERSON = CallerTurn(text="Can I speak to a person please?")


# --------------------------------------------------------------------------------------
# 1. The default path: this deployment cannot transfer anybody, and never could.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_caller_asks_for_a_person_and_this_line_cannot_transfer_one() -> None:
    """WHAT HAPPENS ON EVERY REAL CALL TODAY, and it must be good rather than merely safe.

    The server answers with the wide word plus the one reason we can name
    (`worker/tools.request_handoff`), the worker narrows it to `not_available`, and the
    agent says plainly that it cannot connect them and offers a call back instead.
    """
    api = answering("not_transferred", reason="engine_cannot_transfer")
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=api)

    assert [name for name, _ in run.model.tool_calls] == [HANDOFF_TOOL_NAME]
    assert transfer_promises(run.spoken) == []
    assert "not able to connect you" in run.spoken
    assert "call you back" in run.spoken


@pytest.mark.asyncio
async def test_the_tool_is_asked_before_the_agent_says_anything_about_connecting() -> None:
    """ORDERING IS THE PROPERTY, and it is the reason the tool exists at all. An agent that
    speaks first and asks afterwards has already made the promise by the time it learns the
    promise is false."""
    api = answering("not_transferred", reason="engine_cannot_transfer")
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=api)
    # The greeting is the only thing said before the request, and the reply after it is the
    # first sentence about a person — so a handover was recorded before any reply to the ask.
    assert len(api.handoffs) == 1
    assert len(run.agent_utterances) == 2


@pytest.mark.asyncio
async def test_a_model_that_ignores_its_instructions_promises_the_transfer() -> None:
    """THE NEGATIVE CONTROL FOR EVERY SCENARIO IN THIS FILE.

    Without the tool being consulted, "can I speak to a person" is answered from the
    model's priors — and what a model says is that it is putting you through. If this ever
    goes green the assertions above are asserting nothing.
    """
    api = answering("not_transferred", reason="engine_cannot_transfer")
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=api, obedient=False)

    assert api.handoffs == []
    assert transfer_promises(run.spoken) == ["putting you through", "please hold"]


@pytest.mark.asyncio
async def test_an_agent_with_no_tool_at_all_is_the_state_this_feature_replaced() -> None:
    """`build_call_tools` advertises nothing when there is no API to perform an act, so a
    local run and a replay have no handover tool. The same improvisation follows, which is
    why a production session always has one."""
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=None)
    assert run.model.tool_calls == []
    assert transfer_promises(run.spoken) == ["putting you through", "please hold"]


# --------------------------------------------------------------------------------------
# 2. A person is available and accepts.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_person_accepts_and_only_then_is_the_caller_told_they_are_connected() -> None:
    """THE ONLY OUTCOME THAT LICENSES THE CLAIM, and it means ACCEPTED — not dialled, not
    ringing. The destination pattern is whisper-then-accept: the person we ring hears who is
    calling and about what, and has to accept before the bridge."""
    api = answering("connected")
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=api)

    assert [name for name, _ in run.model.tool_calls] == [HANDOFF_TOOL_NAME]
    assert transfer_promises(run.spoken) == ["connecting you now"]
    assert "call you back" not in run.spoken


@pytest.mark.asyncio
async def test_what_the_person_taking_the_call_over_is_told() -> None:
    """Requirement of the brief: whoever picks this up is not starting cold. The model's own
    summary of what the caller wants travels with the request, unread by this container and
    never logged (hard rule 6)."""
    api = answering("connected")
    await run_scenario(
        [CallerTurn(text="I need to speak to a person about my order")], tool_api=api
    )
    assert api.handoffs[0].summary
    assert api.handoffs[0].reason


# --------------------------------------------------------------------------------------
# 3. Nobody accepts, and 4. nobody is on duty. Two different sentences.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nobody_accepts_the_handover_and_the_caller_is_not_left_holding() -> None:
    """Rung, and not picked up. The caller must not be told a person is coming, and the
    conversation must go somewhere rather than stopping at an apology."""
    api = answering("no_answer", reason="declined")
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=api)

    assert transfer_promises(run.spoken) == []
    assert "call you back" in run.spoken


@pytest.mark.asyncio
async def test_the_caller_asks_after_hours_and_nobody_is_on_duty() -> None:
    """NOBODY WAS RUNG, so the agent must not say it tried.

    Whether anybody is on duty is the server's decision — `agents/handoff.on_duty` walks the
    roster and its third answer is "we do not know", which also means nobody. What this
    asserts is the half that runs on a vendor's infrastructure: the agent hears that word
    and does not promise a person.
    """
    api = answering("nobody_on_duty", reason="after_hours")
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=api)

    assert transfer_promises(run.spoken) == []
    assert "call you back" in run.spoken


@pytest.mark.asyncio
async def test_the_api_cannot_be_reached_and_nothing_was_tried() -> None:
    """The one outcome this container authors by itself. It knows the handover did not
    happen and does NOT know whether it could have, so it says the smaller thing."""
    api = ScenarioToolApi(answer=HandoffToolOut(status="connected", say=""), unreachable=True)
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=api)

    assert transfer_promises(run.spoken) == []
    assert "call you back" in run.spoken


# --------------------------------------------------------------------------------------
# 5. The distressed caller, in the language they are distressed in.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_caller_who_asks_in_telugu_is_refused_a_transfer_in_telugu() -> None:
    """A distressed caller is the case this whole tool is for, and being answered in a
    language they did not use is the second-worst thing that can happen on the turn."""
    api = answering("nobody_on_duty", reason="after_hours")
    run = await run_scenario(
        [CallerTurn(text="నాకు ఒక మనిషితో మాట్లాడాలి")],
        tool_api=api,
        config=make_session_config(system_prompt=compose_agent_prompt()),
    )

    reply = run.agent_utterances[-1]
    assert is_telugu(reply)
    assert transfer_promises(run.spoken) == []


@pytest.mark.asyncio
async def test_nothing_said_about_a_handover_is_unspeakable() -> None:
    """The style floor applies to the hardest turn in the call too: no markdown, no bullets,
    no emoji. `AGENTS.md:180` — TTS reads exactly what the LLM writes."""
    api = answering("no_answer", reason="declined")
    run = await run_scenario([ASKS_FOR_A_PERSON], tool_api=api)
    assert voice_safety_violations(run.spoken) == []
