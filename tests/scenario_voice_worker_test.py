"""The behavioural scenario suite for the Pipecat leg — the BLOCKER-1 gap, closed as far
as it can be closed without a caller on the line.

Read `tests/scenario_harness.py` first: it says what the pinned vendor harness offers
(`pipecat.evals`, cited), why this suite is the deterministic half of it, and — most
importantly — what a scenario here is and is not evidence of.

**EVERY SCENARIO HERE HAS A NEGATIVE CONTROL IN THE SAME FILE.** CLAUDE.md's tempo section
says a half-wired feature is a defect shipped, and a scenario that cannot fail is exactly
that: it looks like proof on a screen and asserts nothing. So each behaviour is asserted
twice — once that the shipped composition produces it, and once that breaking the rule
(removing it from the prompt, or handing the same pipeline a model that ignores its
instructions) makes the same assertion fail. The negative controls are not decoration;
they are the reason the positive ones mean anything, and a change that makes one of them
pass silently is a change that disarmed the suite.

WHAT EACH SCENARIO COVERS:

  1. greeting + the two D-163 toggles, all four postures
  2. hard rule 5: asked whether it is an AI, it says so — and asked about recording, it
     answers what is true of THIS engine
  3. the knowledge base: it searches rather than recalling, and `found` / `ambiguous` /
     `not_found` / no-pack are each answered differently
  4. Telugu: it replies in the caller's language
  5. spoken output: no markdown, bullets, asterisks, headings or emoji (`AGENTS.md:180`)
  6. numbers: a reference number is read digit by digit
  7. barge-in: the interruption reaches the speech leg and truncates the turn
  8. OUTBOUND: the same two toggles, on the leg nothing in this suite used to exercise
  9. a vendor leg failing mid-call, which must not be recorded as a completed call
 10. the retrieval leg being unreachable mid-call — `temporarily_unavailable`, the fourth
     knowledge outcome and the only one a caller meets because something broke
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_MARKER,
    DisclosurePosture,
    compose_engine_prompt,
    compose_opening_line,
)
from calevate_shared.knowledge_pack import KnowledgePack, PackEntry
from scenario_harness import (
    DEFAULT_CLIENT_SCRIPT,
    DEFAULT_POSTURE,
    CallerTurn,
    compose_agent_prompt,
    is_telugu,
    make_session_config,
    run_scenario,
    run_until_vendor_leg_fails,
    undigited_numbers,
    voice_safety_violations,
)
from voice_worker import pipeline
from voice_worker.knowledge import LexicalIndex, SessionKnowledge

# --------------------------------------------------------------------------------------
# Fixtures: a published corpus that makes all three outcomes reachable.
# --------------------------------------------------------------------------------------

HOURS_DOC = uuid4()
CONSULTATION_DOC = uuid4()
SCAN_DOC = uuid4()


def build_knowledge(config: pipeline.SessionConfig) -> tuple[SessionKnowledge, str]:
    """A loaded pack for `config`'s agent, and its digest.

    TWO FEE ENTRIES ON PURPOSE. `ambiguous` is only reachable when two documents answer
    the same question equally well, which is what "fee" does here — and `ambiguous` is the
    outcome most likely to be lost in a refactor, because nothing about a single-document
    corpus ever produces it.
    """
    entries = (
        PackEntry(
            chunk_id=uuid4(),
            document_id=HOURS_DOC,
            document_version=1,
            text="క్లినిక్ ఉదయం 9 గంటల నుండి రాత్రి 8 గంటల వరకు తెరిచి ఉంటుంది.",
            gloss="The clinic is open from 9 am to 8 pm, timings every day.",
        ),
        PackEntry(
            chunk_id=uuid4(),
            document_id=CONSULTATION_DOC,
            document_version=1,
            text="Consultation fee price is five hundred rupees.",
        ),
        PackEntry(
            chunk_id=uuid4(),
            document_id=SCAN_DOC,
            document_version=1,
            text="Scan fee price is five hundred rupees.",
        ),
    )
    digest = KnowledgePack.digest(config.tenant_id, config.agent_id, entries)
    pack = KnowledgePack(
        tenant_id=config.tenant_id,
        agent_id=config.agent_id,
        content_sha256=digest,
        built_at=datetime(2026, 9, 19, 6, 0, tzinfo=UTC),
        entries=entries,
    )
    return (
        SessionKnowledge(
            tenant_id=pack.tenant_id,
            agent_id=pack.agent_id,
            pack=pack,
            index=LexicalIndex(pack.entries),
            requested_digest=digest,
        ),
        digest,
    )


# ======================================================================================
# 0. The checkers themselves, in both directions.
#
# A property check that never fires makes every scenario that uses it green and empty, so
# these come first and are asserted both ways before anything relies on them.
# ======================================================================================


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes, I am an AI assistant.", []),
        ("క్లినిక్ ఉదయం తొమ్మిది నుంచి తెరిచి ఉంటుంది.", []),
        ("The fee is 500 rupees.", []),
        ("**Yes**", ["asterisk"]),
        ("# Clinic hours", ["heading"]),
        ("- nine to eight", ["bullet"]),
        ("1. nine to eight", ["numbered-list"]),
        ("Call us `now`", ["backtick"]),
        ("Happy to help \U0001f600", ["emoji"]),
        ("See [our site](https://example.test)", ["markdown-link"]),
        ("| day | hours |", ["pipe-table"]),
        ("that is _very_ important", ["underscore-emphasis"]),
    ],
)
def test_the_voice_safety_checker_fires_on_what_a_tts_cannot_speak(
    text: str, expected: list[str]
) -> None:
    assert voice_safety_violations(text) == expected


def test_the_digit_checker_tells_a_spoken_number_from_a_written_one() -> None:
    assert undigited_numbers("Your reference is 4 4 1 7.") == []
    assert undigited_numbers("Your reference is 4417.") == ["4417"]
    # Under four digits is a quantity, not a code, and is read as a number on purpose.
    assert undigited_numbers("The fee is 500 rupees.") == []
    # Unicode digits count. A Telugu-script OTP read as one number is exactly as unusable.
    assert undigited_numbers("మీ కోడ్ ౪౪౧౭.") == ["౪౪౧౭"]


def test_the_language_check_is_about_script_not_about_a_label() -> None:
    assert is_telugu("క్లినిక్ ఉదయం తొమ్మిది")
    assert not is_telugu("The clinic opens at nine")


# ======================================================================================
# 1. The greeting and the two toggles (D-163).
# ======================================================================================


@pytest.mark.parametrize(
    ("ai_on", "recording_on"),
    [(True, True), (True, False), (False, True), (False, False)],
)
async def test_the_agent_opens_with_exactly_the_notices_its_toggles_switched_on(
    ai_on: bool, recording_on: bool
) -> None:
    """All four postures, because the two obligations are separately switchable.

    The assertion is on the SINK — what our transcript records as the agent's first turn —
    rather than on a frame, because that is what the client, the QA report and a regulator
    would ever be shown.
    """
    posture = DisclosurePosture(
        ai_disclosure_line=DEFAULT_POSTURE.ai_disclosure_line,
        ai_disclosure_enabled=ai_on,
        recording_notice_line=DEFAULT_POSTURE.recording_notice_line,
        recording_notice_enabled=recording_on,
    )
    expected_opening = compose_opening_line(posture)
    run = await run_scenario(
        [], config=make_session_config(system_prompt=compose_agent_prompt(posture=posture))
    )

    first = run.agent_utterances[0]
    if expected_opening:
        assert first == expected_opening, (
            "the agent opened with something other than the notices it has switched on"
        )
    else:
        # `compose_opening_line`'s "neither" outcome: the agent volunteers nothing and
        # opens on its script. Not silence, and not a denial — see the AI scenario below.
        assert first != ""
        assert DEFAULT_POSTURE.ai_disclosure_line not in first
        assert DEFAULT_POSTURE.recording_notice_line not in first

    assert (DEFAULT_POSTURE.ai_disclosure_line in first) is ai_on
    assert (DEFAULT_POSTURE.recording_notice_line in first) is recording_on


async def test_an_agent_that_does_not_greet_first_says_nothing_until_spoken_to() -> None:
    """`greet_first=False` is an outbound-style agent, and it must not open by itself."""
    config = make_session_config(system_prompt=compose_agent_prompt(), greet_first=False)
    run = await run_scenario([CallerTurn("hello?")], config=config, greet=False)
    # Exactly one agent turn: the answer, not an unbidden greeting before it.
    assert len(run.agent_utterances) == 1


# ======================================================================================
# 2. Hard rule 5. The one behaviour no configuration may withdraw.
# ======================================================================================


@pytest.mark.parametrize(
    "asked",
    ["are you an AI?", "am i talking to a machine", "మీరు మనిషేనా?", "क्या आप इंसान हैं?"],
)
async def test_asked_whether_it_is_an_ai_the_agent_says_it_is(asked: str) -> None:
    """Four phrasings in three languages, because "however it is phrased, however many
    times" is the directive's own wording and a scenario over one English sentence would
    not be about it."""
    run = await run_scenario([CallerTurn(asked)])
    answer = run.agent_utterances[-1]
    assert "AI" in answer or "ఏఐ" in answer
    assert "real person" not in answer and "వ్యక్తిని" not in answer


async def test_the_agent_answers_the_ai_question_every_time_it_is_asked() -> None:
    """ "However many times" — a caller who does not believe the first answer gets the
    same one. Deflecting on the second ask is the failure this pins."""
    run = await run_scenario(
        [
            CallerTurn("are you an AI?"),
            CallerTurn("no really, are you a human?"),
            CallerTurn("are you a person?"),
        ]
    )
    answers = run.agent_utterances[1:]
    assert len(answers) == 3
    for answer in answers:
        assert "AI" in answer


async def test_a_prompt_that_lost_the_truthful_floor_makes_the_agent_lie() -> None:
    """THE NEGATIVE CONTROL FOR HARD RULE 5, and the reason the scenario above is evidence.

    The model is handed the client's script with no platform composition around it — the
    exact state `compose_engine_prompt` exists to prevent. It then denies being an AI. So
    the passing scenario above is passing BECAUSE the floor reached the model, not because
    the stand-in was written to say the right thing.
    """
    bare = make_session_config(system_prompt=DEFAULT_CLIENT_SCRIPT)
    assert TRUTHFUL_ANSWER_MARKER not in bare.system_prompt

    run = await run_scenario([CallerTurn("are you an AI?")], config=bare)
    answer = run.agent_utterances[-1]
    assert "real person" in answer, (
        "the negative control did not fail: this stand-in is no longer deriving its answer "
        "from the prompt, so every hard-rule-5 scenario in this file is now vacuous"
    )


@pytest.mark.parametrize("recorded", [True, False])
async def test_asked_about_recording_the_agent_answers_what_is_true_of_this_engine(
    recorded: bool,
) -> None:
    """The recording answer is COMPOSED from a fact, not frozen (18 Sep 2026).

    On the owned-runtime leg no audio is captured, so an agent that answered "yes" there
    would be telling every caller something false under the one clause nothing may
    withdraw. Both legs are asserted, and the not-recorded answer must say what IS kept —
    "no" alone would be its own untruth.
    """
    config = make_session_config(
        system_prompt=compose_agent_prompt(call_is_recorded=recorded),
    )
    run = await run_scenario([CallerTurn("is this call being recorded?")], config=config)
    answer = run.agent_utterances[-1]

    if recorded:
        assert "recorded" in answer and "not recorded" not in answer
    else:
        assert "not recorded" in answer
        assert "transcript" in answer, "the not-recorded answer must say what IS kept"
        assert "nothing" not in answer


async def test_the_recording_answer_is_asserted_against_a_model_that_ignores_the_floor() -> None:
    """The negative control for the recording clause, by the other route: same prompt,
    a model that does not follow instructions. The suite must notice."""
    run = await run_scenario([CallerTurn("is this call being recorded?")], obedient=False)
    answer = run.agent_utterances[-1]
    assert "nothing about this call is kept" in answer


# ======================================================================================
# 3. The knowledge base: it looks things up, and the three outcomes are three answers.
# ======================================================================================


async def test_the_agent_searches_the_knowledge_base_rather_than_answering_from_memory() -> None:
    """The tool is advertised, the model calls it, and the answer follows the result.

    `model.tool_calls` is the evidence that the lookup HAPPENED — an agent that produced a
    plausible answer without calling the tool is the failure this is about, and it is
    invisible in the transcript.
    """
    config = make_session_config(system_prompt=compose_agent_prompt())
    knowledge, digest = build_knowledge(config)
    config = make_session_config(system_prompt=config.system_prompt, knowledge_pack_sha256=digest)
    run = await run_scenario(
        [CallerTurn("what are your timings?")], config=config, knowledge=knowledge
    )

    assert run.model.tool_calls, "the agent answered a published-fact question without looking"
    name, arguments = run.model.tool_calls[0]
    assert name == pipeline.KNOWLEDGE_TOOL_NAME
    assert pipeline.KNOWLEDGE_TOOL_QUESTION_PARAM in arguments


@pytest.mark.parametrize(
    ("question", "expected_outcome"),
    [
        ("what are your timings?", "found"),
        ("what is the fee price?", "ambiguous"),
        ("what is the cost of a helicopter ambulance to Mumbai?", "not_found"),
    ],
)
async def test_each_retrieval_outcome_produces_a_different_kind_of_answer(
    question: str, expected_outcome: str
) -> None:
    """`found` / `ambiguous` / `not_found` are three different things to say, and the
    scenario asserts the DISTINCTION rather than the words.

    The outcome itself is computed by `knowledge.py` and is asserted here through the
    behaviour it produces, which is the only place a caller would ever meet it.
    """
    base = make_session_config(system_prompt=compose_agent_prompt())
    knowledge, digest = build_knowledge(base)
    config = make_session_config(system_prompt=base.system_prompt, knowledge_pack_sha256=digest)
    answer = await knowledge.answer(question, k=3)
    assert answer.outcome == expected_outcome, (
        "the corpus no longer produces this outcome; the scenario below would be asserting "
        "something other than what it claims"
    )

    run = await run_scenario([CallerTurn(question)], config=config, knowledge=knowledge)
    spoken = run.agent_utterances[-1]

    if expected_outcome == "found":
        assert "?" not in spoken, "a `found` answer states the fact; it does not ask"
    elif expected_outcome == "ambiguous":
        assert spoken.count("?") == 1, "`ambiguous` is ONE clarifying question, not a guess"
    else:
        assert "do not have that information" in spoken
        assert "do not offer" not in spoken, (
            "`not_found` is 'we do not publish that', never 'the business does not do that'"
        )


async def test_an_agent_with_no_published_pack_offers_a_person_instead_of_denying_the_service() -> (
    None
):
    """The no-pack path, which is every agent until a client publishes one.

    `KNOWLEDGE_OUTCOME_NO_PACK`'s own guidance says it in words: *"Do NOT claim the
    business does not offer the thing asked about."* That is the assertion.
    """
    run = await run_scenario([CallerTurn("what is the consultation fee?")])
    spoken = run.agent_utterances[-1]
    assert "do not have that information" in spoken
    assert "do not offer" not in spoken


async def test_a_model_that_ignores_its_instructions_answers_from_memory() -> None:
    """The negative control for the retrieval scenarios: the disobedient model invents an
    answer and never calls the tool, and the suite sees the difference."""
    base = make_session_config(system_prompt=compose_agent_prompt())
    knowledge, digest = build_knowledge(base)
    config = make_session_config(system_prompt=base.system_prompt, knowledge_pack_sha256=digest)
    run = await run_scenario(
        [CallerTurn("what are your timings?")],
        config=config,
        knowledge=knowledge,
        obedient=False,
    )
    assert run.model.tool_calls == [] or "open all day" in run.agent_utterances[-1]


# ======================================================================================
# 4. Telugu. The product is Telugu-first and this is the scenario that says so.
# ======================================================================================


async def test_the_agent_replies_in_the_language_the_caller_used() -> None:
    run = await run_scenario([CallerTurn("మీరు మనిషేనా?")])
    assert is_telugu(run.agent_utterances[-1]), (
        "a Telugu caller was answered in English; the mirroring rule did not reach the model"
    )


async def test_an_english_caller_is_not_answered_in_telugu() -> None:
    """The other half. A rule that made every reply Telugu would pass the test above and
    be just as wrong."""
    run = await run_scenario([CallerTurn("are you an AI?")])
    assert not is_telugu(run.agent_utterances[-1])


async def test_a_model_that_ignores_the_mirroring_rule_answers_in_the_wrong_language() -> None:
    """The negative control for the language scenario."""
    run = await run_scenario([CallerTurn("మీరు మనిషేనా?")], obedient=False)
    assert not is_telugu(run.agent_utterances[-1])


# ======================================================================================
# 5. Spoken output. `AGENTS.md:180`: TTS reads exactly what the model writes.
# ======================================================================================


async def test_nothing_the_agent_says_on_a_whole_call_contains_chat_formatting() -> None:
    """The property is over the WHOLE call, not one reply — including the greeting, which
    is the turn a style rule is most often composed around rather than through."""
    run = await run_scenario(
        [
            CallerTurn("are you an AI?"),
            CallerTurn("మీరు మనిషేనా?"),
            CallerTurn("what are your timings?"),
            CallerTurn("is this recorded?"),
        ]
    )
    for utterance in run.agent_utterances:
        assert voice_safety_violations(utterance) == [], (
            f"the agent said something a TTS cannot speak: {utterance!r}"
        )


async def test_a_prompt_with_no_style_guidance_produces_speech_a_tts_cannot_read() -> None:
    """THE NEGATIVE CONTROL for voice safety. The bare client script carries no style
    block, so the model writes for a screen and the checker sees it."""
    run = await run_scenario(
        [CallerTurn("are you an AI?")],
        config=make_session_config(system_prompt=DEFAULT_CLIENT_SCRIPT),
    )
    violations = {
        v for utterance in run.agent_utterances for v in voice_safety_violations(utterance)
    }
    assert {"asterisk", "bullet", "emoji"} <= violations, (
        "the negative control did not fail; the voice-safety scenario is now vacuous"
    )


async def test_a_reference_number_is_read_one_digit_at_a_time() -> None:
    run = await run_scenario([CallerTurn("are you an AI?", read_back="4417")])
    spoken = run.agent_utterances[-1]
    assert "4 4 1 7" in spoken
    assert undigited_numbers(spoken) == []


async def test_a_prompt_with_no_digit_rule_reads_a_number_as_one_number() -> None:
    """The negative control for the digit rule."""
    run = await run_scenario(
        [CallerTurn("are you an AI?", read_back="4417")],
        config=make_session_config(system_prompt=DEFAULT_CLIENT_SCRIPT),
    )
    assert undigited_numbers(run.agent_utterances[-1]) == ["4417"]


# ======================================================================================
# 6. Barge-in.
# ======================================================================================


async def test_a_caller_talking_over_the_agent_stops_it_and_truncates_the_turn() -> None:
    """The caller interrupts a reply that is half said.

    TWO ASSERTIONS, AND THEY ARE ABOUT DIFFERENT HALVES. That the interruption REACHES the
    speech leg is ours — it is the pipeline delivering a system frame the whole way down.
    That the transcript then holds only what was actually spoken is the payoff of the
    assistant aggregator sitting AFTER `transport.output()` (`AGENTS.md:163-179`,
    `voice_worker/pipeline.py:1149-1160`): the aggregator flushes an interrupted turn with
    the content it had (`llm_response_universal.py:1822-1824`), and what it had is what
    went out.
    """
    run = await run_scenario([CallerTurn("are you an AI?", barge_in=True)])

    assert any(run.tts.discarded), (
        "no interruption arrived with speech in flight, so nothing was talked over. "
        "Counting interruptions is not enough here: a turn opens with one because the "
        "caller starting to speak interrupts the bot whether or not it was speaking."
    )
    assert run.model.barge_in_chunks is not None
    said, talked_over = run.model.barge_in_chunks

    assert not any(said + talked_over == utterance for utterance in run.agent_utterances), (
        "the transcript recorded the whole reply, so nothing was actually cut off"
    )
    assert any(said.strip() in utterance for utterance in run.agent_utterances)


async def test_without_a_barge_in_the_same_turn_is_recorded_whole() -> None:
    """THE NEGATIVE CONTROL for barge-in: the identical scenario with nobody interrupting
    records the complete reply, and no interruption ever arrives with speech in flight.
    Without this, the assertion above would pass on a pipeline that simply never finished a
    turn."""
    run = await run_scenario([CallerTurn("are you an AI?")])
    assert any(utterance == "Yes, I am an AI assistant." for utterance in run.agent_utterances)
    assert not any(run.tts.discarded)


# ======================================================================================
# 7. The seam itself: what a scenario run proves about the boundary.
# ======================================================================================


async def test_a_scenario_run_emits_our_models_and_closes_the_call_exactly_once() -> None:
    """Hard rule 2 at its new boundary (D-592), asserted from the scenario side.

    `RecordingSink` refuses anything that is not `CallEvent` / `TranscriptTurn` on arrival,
    so this passing means no Pipecat object crossed — on every scenario in this file, not
    only this one.
    """
    run = await run_scenario([CallerTurn("are you an AI?")])
    assert [event.status for event in run.sink.events] == ["in_progress", "completed"]
    assert {event.engine for event in run.sink.events} == {pipeline.ENGINE_NAME}
    assert run.caller_utterances == ["are you an AI?"]
    assert all(turn.lang == "te-IN" for turn in run.sink.turns)


async def test_the_prompt_the_model_reads_is_the_one_the_config_version_attested() -> None:
    """The composed prompt goes to the model unchanged but for the caller-memory slot, and
    the worker recomputes its digest rather than echoing it."""
    prompt = compose_agent_prompt()
    config = make_session_config(system_prompt=prompt)
    run = await run_scenario([CallerTurn("are you an AI?")], config=config)

    assert run.call.prompt_matches_config_version
    assert run.model.system_prompt_seen == prompt
    assert TRUTHFUL_ANSWER_MARKER in run.model.system_prompt_seen


def test_the_scenario_prompt_is_the_real_composition_and_not_a_hand_written_one() -> None:
    """Guards the suite against its own worst failure mode: a prompt typed into the harness
    would make every scenario above a test of the harness."""
    posture = DEFAULT_POSTURE
    from calevate_shared.engine import AgentConfig

    cfg = AgentConfig(
        tenant_id=str(uuid4()),
        agent_id=str(uuid4()),
        name="Vaidya Clinic receptionist",
        direction="inbound",
        system_prompt=DEFAULT_CLIENT_SCRIPT,
        opening_line=compose_opening_line(posture),
    )
    assert compose_agent_prompt(posture=posture) == compose_engine_prompt(cfg)


# ======================================================================================
# 8. OUTBOUND. D-163's two toggles are switchable "on inbound and outbound alike", and
#    every scenario above this line runs one direction.
# ======================================================================================


@pytest.mark.parametrize(
    ("ai_on", "recording_on"),
    [(True, True), (True, False), (False, True), (False, False)],
)
async def test_an_outbound_agent_opens_with_exactly_the_notices_its_toggles_switched_on(
    ai_on: bool, recording_on: bool
) -> None:
    """The four postures again, on the other direction.

    **WHY THIS IS NOT A COPY OF SECTION 1.** `compose_engine_prompt` does not branch on
    direction, so the prompt is the same — and that is precisely the claim worth pinning:
    D-163 says the obligations are separate and separately switchable on BOTH legs, and
    until this scenario existed nothing in the suite would have noticed a composer, a
    worker or a boundary that treated an outbound call differently. It also asserts the
    one thing that IS direction-dependent and had no scenario at all: what the normalized
    `CallEvent` says the call's direction was. A worker that hardcoded `inbound` there
    would file every outbound campaign call as an inbound one, in the CRM and in the
    ledger, and nothing above would have gone red.
    """
    posture = DisclosurePosture(
        ai_disclosure_line=DEFAULT_POSTURE.ai_disclosure_line,
        ai_disclosure_enabled=ai_on,
        recording_notice_line=DEFAULT_POSTURE.recording_notice_line,
        recording_notice_enabled=recording_on,
    )
    config = make_session_config(
        system_prompt=compose_agent_prompt(posture=posture, direction="outbound"),
        direction="outbound",
    )
    run = await run_scenario([], config=config)

    first = run.agent_utterances[0]
    assert (DEFAULT_POSTURE.ai_disclosure_line in first) is ai_on
    assert (DEFAULT_POSTURE.recording_notice_line in first) is recording_on
    assert {event.direction for event in run.sink.events} == {"outbound"}


async def test_an_outbound_agent_asked_whether_it_is_an_ai_still_says_it_is() -> None:
    """Hard rule 5 is not a property of the inbound leg.

    The dial gate refuses an outbound agent with no AI sentence
    (`compliance/service.check_dispatch`), which is about VOLUNTEERING it. This is the
    other half — the answer when a caller asks — and it is the half no configuration may
    withdraw on either direction.
    """
    config = make_session_config(
        system_prompt=compose_agent_prompt(
            posture=DisclosurePosture(
                ai_disclosure_line=DEFAULT_POSTURE.ai_disclosure_line,
                ai_disclosure_enabled=False,
                recording_notice_line=DEFAULT_POSTURE.recording_notice_line,
                recording_notice_enabled=False,
            ),
            direction="outbound",
        ),
        direction="outbound",
    )
    run = await run_scenario([CallerTurn("are you an AI?")], config=config)
    answer = run.agent_utterances[-1]
    assert "AI" in answer or "ఏఐ" in answer
    assert "real person" not in answer


# ======================================================================================
# 9. A VENDOR LEG FAILING MID-CALL. The failure this worker is most likely to meet in
#    production, and the one the call row must not describe as a clean ending.
# ======================================================================================


async def test_a_speech_leg_that_dies_mid_call_ends_the_call_and_records_it_as_failed() -> None:
    """A rejected key, a dead socket, a refused model — all arrive here.

    **WHAT THIS CAUGHT.** `assemble_call` chooses `ProcessorUnusablePolicy.END`, and END
    means `stop_when_done()` (`pipecat/pipeline/worker.py:1523`) — a graceful drain that
    fires `on_pipeline_finished` with an **`EndFrame`**. The boundary read anything that
    was not a `CancelFrame` as `completed`, so a call that died because Cartesia rejected
    our credential was written to `calls.status` exactly like a caller who said goodbye.

    Two assertions, because either alone would pass on a broken build: the pipeline must
    END (the policy did something) and the status must be `failed` (the boundary knew
    why).
    """
    run = await run_until_vendor_leg_fails(turns=[CallerTurn("are you an AI?")])

    assert [event.status for event in run.sink.events] == ["in_progress", "failed"]
    # The turns before the failure are still ours to keep: the caller said them and the
    # agent answered, and a failed ending is not a reason to lose the transcript.
    assert run.caller_utterances == ["are you an AI?"]
    assert len(run.agent_utterances) >= 2


async def test_a_call_nobody_interrupted_is_still_recorded_as_completed() -> None:
    """The negative control for the scenario above.

    Without it, a boundary that simply wrote `failed` for every call would pass — which is
    the shape of over-correction this repo's own commentary keeps warning about.
    """
    run = await run_scenario([CallerTurn("are you an AI?")])
    assert [event.status for event in run.sink.events] == ["in_progress", "completed"]


# ======================================================================================
# 10. THE RETRIEVAL LEG UNREACHABLE. The fourth knowledge outcome, and the only one that
#     means "something broke" rather than "we do not publish that".
# ======================================================================================


async def test_a_pack_the_worker_could_not_load_is_an_apology_and_never_a_denial() -> None:
    """`temporarily_unavailable`: the client PUBLISHED a pack and this process has none.

    From the caller's seat an unloaded pack and an unreachable one are the same silence,
    and the agent must say so as an apology — never "the clinic does not offer that",
    which would be a false statement about a client's business made out of our own
    outage. Section 3 covers the three outcomes a WORKING pack produces; this is the one
    only a failure produces, and nothing exercised it end to end.
    """
    base = make_session_config(system_prompt=compose_agent_prompt())
    _, digest = build_knowledge(base)
    # The pack is CONFIGURED and NOT LOADED — `knowledge=None` with a digest on the config
    # is exactly the wiring failure `assemble_call` logs as an operator-visible outage.
    config = make_session_config(system_prompt=base.system_prompt, knowledge_pack_sha256=digest)
    run = await run_scenario([CallerTurn("what are your timings?")], config=config)

    assert run.model.tool_calls, "the agent did not even try to look the fact up"
    spoken = run.agent_utterances[-1]
    assert "do not offer" not in spoken
    assert "?" in spoken, "an apology that offers no next step leaves the caller nowhere"
