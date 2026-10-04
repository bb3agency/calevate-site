"""Scenarios for the first live Vobiz call: what must hold before a caller is on the line.

Read `tests/scenario_harness.py` first. The model is a stand-in that derives its behaviour
from the prompt it is handed, so these assert the SEAM: that a rule reached the model, that
the pipeline carries what the model produced in the right order, and that our own code does
what the rule requires. Whether a real model obeys is a live-call question, not one these
can answer. Every behaviour has a negative control beside it, for the reason
`tests/scenario_voice_worker_test.py` gives.

The postures here are the ones a new agent actually gets: both D-163 notices OFF (D-669),
read off the ORM column defaults rather than typed, and the recording answer composed from
the Vobiz capability profile (`engine/pipecat.capabilities_for_carrier`), which is what a
published agent's `call_is_recorded` comes from.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from apps.api.agents.models import Agent
from apps.api.engine.pipecat import capabilities_for_carrier
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_MARKER,
    DisclosurePosture,
    compose_opening_line,
    truthful_answer_directive,
)
from calevate_shared.worker_api import (
    CallbackBookIn,
    CallbackCancelIn,
    CallbackCancelOut,
    CallbackToolOut,
    HandoffToolIn,
    HandoffToolOut,
    OptOutToolIn,
    OptOutToolOut,
)
from pipecat.frames.frames import (
    EndFrame,
    EndWorkerFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.services.cartesia.tts import language_to_cartesia_language
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.transcriptions.language import Language
from scenario_harness import (
    DEFAULT_CLIENT_SCRIPT,
    DEFAULT_POSTURE,
    GOODBYE_REPLY,
    CallerTurn,
    ScenarioRun,
    compose_agent_prompt,
    make_session_config,
    run_scenario,
    undigited_numbers,
    voice_safety_violations,
)
from scenario_voice_worker_test import (
    CONSULTATION_DOC,
    HOURS_DOC,
    SCAN_DOC,
    build_knowledge,
)
from voice_worker import pipeline
from voice_worker.call_tools import END_CALL_REASON, END_CALL_TOOL_NAME

# --------------------------------------------------------------------------------------
# Fixtures.
# --------------------------------------------------------------------------------------


def _column_default(name: str) -> bool:
    """The `server_default` of a boolean column on `agents`, as the database applies it."""
    default = Agent.__table__.c[name].server_default
    arg = getattr(default, "arg", None)
    assert arg in ("true", "false"), f"agents.{name} has no boolean server_default: {arg!r}"
    return arg == "true"


def new_agent_posture() -> DisclosurePosture:
    """The posture an agent created today has: D-669's column defaults, the harness's lines."""
    return DisclosurePosture(
        ai_disclosure_line=DEFAULT_POSTURE.ai_disclosure_line,
        ai_disclosure_enabled=_column_default("ai_disclosure_enabled"),
        recording_notice_line=DEFAULT_POSTURE.recording_notice_line,
        recording_notice_enabled=_column_default("recording_notice_enabled"),
    )


def vobiz_records(recording_enabled: bool) -> bool:
    """`call_is_recorded` for an agent published on Vobiz with the carrier switch as given."""
    return capabilities_for_carrier("vobiz", recording_enabled=recording_enabled).records_audio


def new_agent_config(*, recorded: bool, **overrides: Any) -> pipeline.SessionConfig:
    posture = new_agent_posture()
    return make_session_config(
        system_prompt=compose_agent_prompt(posture=posture, call_is_recorded=recorded),
        opening_line=compose_opening_line(posture, call_is_recorded=recorded),
        **overrides,
    )


class NoActsToolApi:
    """A worker API that refuses every act. `end_call` needs no API; it is advertised only
    beside the acts, so a scenario about hanging up has to supply one."""

    async def opt_out(self, engine_call_id: str, request: OptOutToolIn) -> OptOutToolOut:
        raise AssertionError("no scenario here opts anybody out")

    async def book_callback(self, engine_call_id: str, request: CallbackBookIn) -> CallbackToolOut:
        raise AssertionError("no scenario here books a call-back")

    async def cancel_callback(
        self, engine_call_id: str, request: CallbackCancelIn
    ) -> CallbackCancelOut:
        raise AssertionError("no scenario here cancels a call-back")

    async def handoff(self, engine_call_id: str, request: HandoffToolIn) -> HandoffToolOut:
        raise AssertionError("no scenario here asks for a person")


CREDENTIALS = pipeline.VendorCredentials(
    sarvam_api_key="sarvam-test", llm_api_key="llm-test", cartesia_api_key="cartesia-test"
)


def developer_messages(run: ScenarioRun) -> list[str]:
    return [
        str(message.get("content"))
        for message in run.call.context.get_messages()
        if isinstance(message, dict) and message.get("role") == "developer"
    ]


def tool_results(run: ScenarioRun) -> list[dict[str, Any]]:
    """Every tool result the model was handed, decoded as the assistant aggregator stored it."""
    results: list[dict[str, Any]] = []
    for message in run.call.context.get_messages():
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.startswith("{"):
            results.append(json.loads(content))
    return results


def tts_input(run: ScenarioRun) -> list[str]:
    """Every text the speech leg was handed: the model's tokens and anything spoken verbatim."""
    return [frame.text for frame in run.tts.seen if isinstance(frame, LLMTextFrame | TTSSpeakFrame)]


# ======================================================================================
# 1. A new agent opens with its greeting only (D-669).
# ======================================================================================


def test_a_new_agent_volunteers_neither_notice() -> None:
    """The premise of every scenario below. If D-669 is reversed, this fails first and
    names it, rather than the greeting scenario failing for an unstated reason."""
    posture = new_agent_posture()
    assert posture.ai_disclosure_enabled is False
    assert posture.recording_notice_enabled is False


@pytest.mark.parametrize("carrier_recording", [True, False])
async def test_a_new_agent_opens_with_its_greeting_and_no_announcement(
    carrier_recording: bool,
) -> None:
    recorded = vobiz_records(carrier_recording)
    config = new_agent_config(recorded=recorded)
    assert config.opening_line == ""

    run = await run_scenario([], config=config)

    assert len(run.agent_utterances) == 1, "the opening was more than the greeting"
    greeting = run.agent_utterances[0]
    assert "Vaidya Clinic" in greeting, "the opening did not come from the client's script"
    assert DEFAULT_POSTURE.ai_disclosure_line not in greeting
    assert DEFAULT_POSTURE.recording_notice_line not in greeting
    assert "AI" not in greeting and "record" not in greeting.lower()
    # Nothing was spoken verbatim, and the model was asked to greet rather than told a
    # notice had already been said.
    assert not any(isinstance(frame, TTSSpeakFrame) for frame in run.tts.seen)
    assert developer_messages(run) == [pipeline.GREETING_INSTRUCTION]
    assert DEFAULT_POSTURE.ai_disclosure_line not in run.model.system_prompt_seen


async def test_with_the_notices_on_the_opening_is_spoken_verbatim_first() -> None:
    """NEGATIVE CONTROL: the assertions above can fail. Switch both notices on and the
    first thing said is the verbatim notice, through the speak path the default skips."""
    posture = DisclosurePosture(
        ai_disclosure_line=DEFAULT_POSTURE.ai_disclosure_line,
        ai_disclosure_enabled=True,
        recording_notice_line=DEFAULT_POSTURE.recording_notice_line,
        recording_notice_enabled=True,
    )
    opening = compose_opening_line(posture, call_is_recorded=vobiz_records(True))
    run = await run_scenario(
        [],
        config=make_session_config(
            system_prompt=compose_agent_prompt(posture=posture), opening_line=opening
        ),
    )
    assert run.agent_utterances[0] == opening
    assert DEFAULT_POSTURE.ai_disclosure_line in run.agent_utterances[0]
    assert any(isinstance(frame, TTSSpeakFrame) for frame in run.tts.seen)
    assert developer_messages(run) != [pipeline.GREETING_INSTRUCTION]


# ======================================================================================
# 2. Hard rule 5 with both notices off: the answer when asked does not depend on them.
# ======================================================================================

ASKS_IF_ROBOT = CallerTurn("am I talking to a robot?")
ASKS_IF_RECORDED = CallerTurn("is this call recorded?")


@pytest.mark.parametrize("carrier_recording", [True, False])
async def test_with_both_notices_off_the_agent_still_answers_both_questions_truthfully(
    carrier_recording: bool,
) -> None:
    recorded = vobiz_records(carrier_recording)
    assert recorded is carrier_recording
    run = await run_scenario(
        [ASKS_IF_ROBOT, ASKS_IF_RECORDED], config=new_agent_config(recorded=recorded)
    )

    # The prompt half: the floor is the last block of what the model actually read, with
    # clause 2 composed from this carrier's recording fact.
    seen = run.model.system_prompt_seen
    assert TRUTHFUL_ANSWER_MARKER in seen
    assert seen.endswith(truthful_answer_directive(call_is_recorded=recorded))

    # The turn half.
    assert len(run.agent_utterances) == 3
    _greeting, robot, recording = run.agent_utterances
    assert "AI" in robot and "real person" not in robot
    if recorded:
        assert "recorded" in recording and "not recorded" not in recording
    else:
        assert "not recorded" in recording
        assert "transcript" in recording, "the not-recorded answer must say what IS kept"


@pytest.mark.parametrize("carrier_recording", [True, False])
async def test_a_new_agent_whose_prompt_lost_the_floor_lies_on_both_questions(
    carrier_recording: bool,
) -> None:
    """NEGATIVE CONTROL: with the notices off, the floor is the only thing standing between
    the caller and a false answer. Strip it from the same prompt and both answers turn."""
    recorded = vobiz_records(carrier_recording)
    config = new_agent_config(recorded=recorded)
    floorless = config.system_prompt.replace(
        truthful_answer_directive(call_is_recorded=recorded), ""
    )
    assert TRUTHFUL_ANSWER_MARKER not in floorless
    run = await run_scenario(
        [ASKS_IF_ROBOT, ASKS_IF_RECORDED],
        config=make_session_config(system_prompt=floorless),
    )
    _greeting, robot, recording = run.agent_utterances
    assert "real person" in robot
    assert "nothing about this call is kept" in recording


# ======================================================================================
# 3. end_call: the agent hangs up after its goodbye; the caller does not have to.
# ======================================================================================

SAYS_GOODBYE = CallerTurn("ok thank you, goodbye")


async def test_a_caller_who_says_goodbye_is_hung_up_on_after_the_agent_says_goodbye() -> None:
    run = await run_scenario(
        [ASKS_IF_ROBOT, SAYS_GOODBYE],
        config=new_agent_config(recorded=vobiz_records(True)),
        tool_api=NoActsToolApi(),
        agent_ends_call=True,
    )

    assert [name for name, _ in run.model.tool_calls] == [END_CALL_TOOL_NAME]
    assert run.agent_utterances[-1] == GOODBYE_REPLY
    assert GOODBYE_REPLY in run.tts.spoken, "the goodbye was cut off by the hang-up"

    # ORDER AT THE SPEECH LEG: the goodbye and the end of its response, then the request
    # to end. Downstream and ordered, so the goodbye is flushed before the pipeline ends.
    # Read downstream only: the worker's upstream echo of the same request is not a second one.
    seen = run.tts.downstream
    goodbye_at = max(
        i for i, f in enumerate(seen) if isinstance(f, LLMTextFrame) and f.text == GOODBYE_REPLY
    )
    response_end_at = next(
        i for i, f in enumerate(seen) if i > goodbye_at and isinstance(f, LLMFullResponseEndFrame)
    )
    end_requests = [(i, f) for i, f in enumerate(seen) if isinstance(f, EndWorkerFrame)]
    assert len(end_requests) == 1
    end_at, end_request = end_requests[0]
    assert end_at > response_end_at
    assert end_request.reason == END_CALL_REASON

    # The pipeline ended on the agent's request, gracefully, and the call is a clean one.
    ends = [f for f in run.transport.output().seen if isinstance(f, EndFrame)]
    assert [f.reason for f in ends] == [END_CALL_REASON]
    assert [event.status for event in run.sink.events] == ["in_progress", "completed"]


async def test_without_the_hang_up_tool_a_goodbye_leaves_the_line_open() -> None:
    """NEGATIVE CONTROL for the scenario above, by the harness's own assertion: with no
    tool API there is no `end_call`, the agent says goodbye and the call stays up, so
    `agent_ends_call` fails rather than passing on a call the harness ended itself."""
    with pytest.raises(AssertionError, match="never ended it"):
        await run_scenario([SAYS_GOODBYE], agent_ends_call=True, timeout_s=5.0)


async def test_without_the_hang_up_tool_no_end_is_requested() -> None:
    """The same control, read off the frames: nothing asked the pipeline to end, and the
    `EndFrame` that did end it is the harness's, not the agent's."""
    run = await run_scenario([SAYS_GOODBYE])
    assert run.model.tool_calls == []
    assert run.agent_utterances[-1] == GOODBYE_REPLY
    assert not any(isinstance(frame, EndWorkerFrame) for frame in run.tts.seen)
    ends = [f for f in run.transport.output().seen if isinstance(f, EndFrame)]
    assert all(f.reason != END_CALL_REASON for f in ends)


# ======================================================================================
# 4. Knowledge: looked up before answering, and the result is what the answer follows.
# ======================================================================================


@pytest.mark.parametrize(
    ("question", "outcome", "sources"),
    [
        ("what are your timings?", "found", {HOURS_DOC}),
        ("what is the fee price?", "ambiguous", {CONSULTATION_DOC, SCAN_DOC}),
        ("what is the cost of a helicopter ambulance to Mumbai?", "not_found", set()),
    ],
)
async def test_a_published_fact_question_is_looked_up_and_the_answer_follows_the_result(
    question: str, outcome: str, sources: set[Any]
) -> None:
    base = new_agent_config(recorded=vobiz_records(True))
    knowledge, digest = build_knowledge(base)
    config = new_agent_config(recorded=vobiz_records(True), knowledge_pack_sha256=digest)
    run = await run_scenario([CallerTurn(question)], config=config, knowledge=knowledge)

    # Looked up, once, and nothing was said between the question and the lookup.
    assert [name for name, _ in run.model.tool_calls] == [pipeline.KNOWLEDGE_TOOL_NAME]
    assert len(run.agent_utterances) == 2, "the agent spoke before or instead of looking"

    # What the model was handed: the outcome word and the passages it rests on.
    results = tool_results(run)
    assert [result["outcome"] for result in results] == [outcome]
    passage_sources = {passage["source_id"] for passage in results[0]["passages"]}
    if outcome == "found":
        assert results[0]["passages"][0]["source_id"] == str(HOURS_DOC)
    else:
        assert passage_sources == {str(source) for source in sources}

    answer = run.agent_utterances[-1]
    if outcome == "found":
        assert "?" not in answer, "a `found` answer states the fact; it does not ask"
    elif outcome == "ambiguous":
        assert answer.count("?") == 1, "`ambiguous` is one clarifying question"
    else:
        assert "do not have that information" in answer
        assert "do not offer" not in answer


async def test_a_model_that_ignores_its_instructions_answers_without_looking() -> None:
    """NEGATIVE CONTROL: no lookup, no tool result in the context, and an invented fact."""
    base = new_agent_config(recorded=vobiz_records(True))
    knowledge, digest = build_knowledge(base)
    config = new_agent_config(recorded=vobiz_records(True), knowledge_pack_sha256=digest)
    run = await run_scenario(
        [CallerTurn("what are your timings?")], config=config, knowledge=knowledge, obedient=False
    )
    assert run.model.tool_calls == []
    assert tool_results(run) == []
    assert "open all day" in run.agent_utterances[-1]


# ======================================================================================
# 5. Language (D-666).
# ======================================================================================

EXTRAS = ("hi-IN",)


def test_extra_languages_unpin_the_transcriber_and_keep_the_voice_on_the_primary() -> None:
    config = make_session_config(
        system_prompt=compose_agent_prompt(languages_extra=EXTRAS), languages_extra=EXTRAS
    )
    legs = pipeline.build_vendor_legs(config, CREDENTIALS)

    assert isinstance(legs.stt, SarvamSTTService)
    assert legs.stt._settings.language is None
    assert legs.tts._settings.language == language_to_cartesia_language(Language("te-IN"))


def test_a_one_language_agent_pins_the_transcriber() -> None:
    """NEGATIVE CONTROL: without extras the transcriber is pinned to the primary."""
    legs = pipeline.build_vendor_legs(
        make_session_config(system_prompt=compose_agent_prompt()), CREDENTIALS
    )
    assert isinstance(legs.stt, SarvamSTTService)
    assert legs.stt._settings.language == "te-IN"


async def test_a_hindi_turn_on_a_telugu_agent_is_stamped_hindi_in_the_transcript() -> None:
    """Through the whole assembled pipeline: the transcriber's reported language reaches
    our `TranscriptTurn`, per turn, and a turn with none falls back to the primary."""
    prompt = compose_agent_prompt(languages_extra=EXTRAS)
    assert prompt != compose_agent_prompt(), "the extras did not reach the composed prompt"
    config = make_session_config(system_prompt=prompt, languages_extra=EXTRAS)

    run = await run_scenario(
        [
            CallerTurn("मुझे अपॉइंटमेंट चाहिए", language="hi-IN"),
            CallerTurn("నాకు అపాయింట్‌మెంట్ కావాలి", language="te-IN"),
            CallerTurn("ok", language=None),
        ],
        config=config,
    )

    caller_langs = [turn.lang for turn in run.sink.turns if turn.speaker == "caller"]
    assert caller_langs == ["hi-IN", "te-IN", "te-IN"]
    assert {turn.lang for turn in run.sink.turns if turn.speaker == "agent"} == {"te-IN"}
    assert run.model.system_prompt_seen == prompt


# ======================================================================================
# 6. Speaking rules, read at the speech leg's INPUT rather than off the transcript.
# ======================================================================================


async def test_nothing_handed_to_the_speech_leg_on_a_whole_call_breaks_a_speaking_rule() -> None:
    """A whole call, with the notices on so the verbatim path is exercised too: greeting,
    both hard-rule-5 questions, a number read back, a lookup, and the goodbye."""
    posture = DisclosurePosture(
        ai_disclosure_line=DEFAULT_POSTURE.ai_disclosure_line,
        ai_disclosure_enabled=True,
        recording_notice_line=DEFAULT_POSTURE.recording_notice_line,
        recording_notice_enabled=True,
    )
    base = make_session_config(system_prompt=compose_agent_prompt(posture=posture))
    knowledge, digest = build_knowledge(base)
    config = make_session_config(
        system_prompt=base.system_prompt,
        opening_line=compose_opening_line(posture, call_is_recorded=True),
        knowledge_pack_sha256=digest,
    )
    run = await run_scenario(
        [
            ASKS_IF_ROBOT,
            CallerTurn("is this call recorded?", read_back="40917"),
            CallerTurn("what are your timings?"),
            SAYS_GOODBYE,
        ],
        config=config,
        knowledge=knowledge,
        tool_api=NoActsToolApi(),
        agent_ends_call=True,
    )

    handed = tts_input(run)
    assert any(isinstance(frame, TTSSpeakFrame) for frame in run.tts.seen)
    assert len(handed) >= 7, f"fewer texts reached the speech leg than were said: {handed!r}"
    for text in handed:
        assert voice_safety_violations(text) == [], f"the speech leg was handed {text!r}"
        assert undigited_numbers(text) == [], f"a number was handed over whole: {text!r}"
    assert any("4 0 9 1 7" in text for text in handed)


async def test_a_prompt_with_no_speaking_rules_hands_the_speech_leg_chat_text() -> None:
    """NEGATIVE CONTROL: the client script alone carries no speaking rules, and the
    checker sees markdown, emoji and a whole number at the speech leg's input."""
    run = await run_scenario(
        [CallerTurn("is this call recorded?", read_back="40917")],
        config=make_session_config(system_prompt=DEFAULT_CLIENT_SCRIPT),
    )
    handed = tts_input(run)
    violations = {v for text in handed for v in voice_safety_violations(text)}
    assert {"asterisk", "emoji"} <= violations
    assert any(undigited_numbers(text) == ["40917"] for text in handed)
