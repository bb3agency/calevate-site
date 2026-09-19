"""A behavioural scenario harness for the Pipecat leg, run in-process against a fake transport.

**WHY THIS EXISTS.** `CLAUDE.md` names the gap: *"NO REAL CALL HAS EVER BEEN PLACED ON
THIS PRODUCT (BLOCKER-1), so a scenario suite is the only thing that can show the agent
greets, answers truthfully when asked whether it is an AI (hard rule 5), searches the
knowledge base instead of answering from memory, respects found / ambiguous / not_found,
and replies in the caller's language — before a caller is the one who finds out."*

═══ WHAT THE PINNED PIPECAT SHIPS, AND WHY THIS FILE IS NOT IT ═══

`pipecat-ai==1.10.0` **does** ship a behavioural eval harness, `pipecat.evals`
(`AGENTS.md:213-288`), and every one of its modules imports under our pin. It offers:

* two KINDS of scenario — SCRIPTED (`turns:`, `pipecat/evals/script.py:8-21`) and
  SIMULATED (`persona:`, an LLM plays the caller and a judge scores the transcript,
  `pipecat/evals/scenario.py:16-24`);
* two MODALITIES, text and audio (`AGENTS.md:286`);
* assertion types per expected event: `text_contains`, `within_ms`, `calls:` for a
  `function_call` with its arguments, `absent: true`, and `eval:` — a natural-language
  criterion scored by a judge LLM (`pipecat/evals/script.py:49-96`);
* a library entry point, `EvalScriptSession.from_scenario(scenario, ws_url).run()`
  (`pipecat/evals/script_session.py:9-22`), driving a bot that is running with the
  `EvalTransport` — a plain WebSocket server speaking RTVI
  (`pipecat/evals/transport.py:8`), i.e. no carrier and no telephony.

**IT WAS TRIED AGAINST THIS PIPELINE AND IT CONNECTS AND DRIVES.** Two things stop it
being the suite in CI, and neither is a reason to pretend it does not exist:

1. **`punkt_tab`.** Every RTVI semantic event the harness asserts on passes through
   `match_endofsentence` (`pipecat/processors/frameworks/rtvi/observer.py:777`), which
   loads NLTK's `punkt_tab` and **downloads it on first use** if it is absent
   (`pipecat/utils/string.py:52-69`). This container has no copy and cannot fetch one, so
   the observer's task dies and no `response` / `llm_response` event is ever produced — a
   scenario then fails for a reason that is not about the agent. (That same fact is a
   production defect in its own right, and `apps/voice-worker/Dockerfile` now bundles the
   data at build time; see the note there.)
2. **The judge.** `eval:` criteria, `success:` and judged `metrics:` need an LLM
   (`AGENTS.md:225`). We have no key in CI and no local Ollama, and a suite whose verdict
   needs a model is not a suite that can gate a push.

So this file is the *deterministic* half, run over the real assembled pipeline with the
vendor's own processors, and the vendor harness stays available for the pre-ship pass on a
machine that has the data and a judge.

═══ WHAT THIS HARNESS ACTUALLY PROVES, AND WHAT IT CANNOT ═══

The model is a stand-in (`PromptFollowingModel`), so **nothing here is evidence about how
a real LLM behaves.** What every scenario asserts is the SEAM: that the rule reached the
model at all, that the wiring around it carries what the model produced, and that our own
code does the thing the rule requires of it. The stand-in is deliberately literal-minded
and *derives* its behaviour from the prompt it is handed — it tells the truth about being
an AI only when the truthful floor is actually present in that prompt, speaks plainly only
when the style guidance is actually present, mirrors the caller's language only when the
mirroring sentence is actually present. That is what makes the scenarios fail for a real
reason: strip the rule from the composition and the scenario goes red, which is exactly
the class of regression hard rule 5 exists to stop.

**WHAT IS STILL UNPROVEN WITHOUT A REAL CALL**: that a real model obeys any of these
instructions, that Silero VAD segments real Telugu PSTN audio into the turns this harness
injects by hand, that Saaras transcribes it, that a carrier's audio arrives at all. Those
are `docs/pre-build-blockers` §3.6 M-1..M-3 measurements, not unit tests.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from calevate_shared.engine import (
    PLATFORM_RULES_PREAMBLE,
    TRUTHFUL_ANSWER_MARKER,
    VOICE_STYLE_GUIDANCE,
    AgentConfig,
    DisclosurePosture,
    ModelConfig,
    azure_openai_base_url,
    compose_engine_prompt,
    compose_opening_line,
)
from calevate_shared.events import CallDirection, CallEvent, TranscriptTurn
from pipecat.frames.frames import (
    Frame,
    FunctionCallFromLLM,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner
from voice_worker import pipeline
from voice_worker.knowledge import SessionKnowledge

# ======================================================================================
# The rules, taken from the platform constants rather than retyped.
#
# Every marker below is DERIVED. A harness that retyped the sentences would keep passing
# after somebody reworded the prompt, which is the one failure it must not have: these are
# the strings the stand-in model looks for to decide whether a rule reached it.
# ======================================================================================


def _bullet_containing(block: str, needle: str) -> str:
    """The one line of a platform constant that contains `needle`, or raise.

    Raising is the point. If a rewrite drops or splits the line, this module fails at
    import with the needle named, instead of every scenario quietly asserting nothing.
    """
    matches = [line.strip() for line in block.splitlines() if needle in line]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one line containing {needle!r} in the platform constant, "
            f"found {len(matches)}. The constant was reworded; re-derive this marker."
        )
    return matches[0]


#: The style rule that forbids spoken markdown (`AGENTS.md:180` is the vendor's version of
#: the same instruction; ours is `VOICE_STYLE_GUIDANCE`).
NO_MARKDOWN_RULE: Final[str] = _bullet_containing(VOICE_STYLE_GUIDANCE, "markdown")

#: The style rule that makes phone numbers, OTPs and reference codes spoken digit by digit.
DIGIT_BY_DIGIT_RULE: Final[str] = _bullet_containing(VOICE_STYLE_GUIDANCE, "one digit at a time")

#: The style rule that makes the agent mirror the caller's language. Telugu-first product.
MIRROR_LANGUAGE_RULE: Final[str] = _bullet_containing(VOICE_STYLE_GUIDANCE, "same language")

#: The clause of the truthful-answer directive that answers the recording question. Which
#: of the two variants an agent carries is a fact about its engine
#: (`truthful_answer_directive(call_is_recorded=...)`), so the stand-in reads it rather
#: than assuming "yes".
_RECORDED_YES_MARKER: Final[str] = "say yes: this call is recorded"
_RECORDED_NO_MARKER: Final[str] = "the audio is not recorded"


# ======================================================================================
# Spoken-output checkers.
#
# These are the "assert a property, not a transcript" half. Each is unit-tested in both
# directions in `tests/scenario_voice_worker_test.py`, because a checker that cannot fail
# makes every scenario that uses it worthless.
# ======================================================================================

#: Characters and shapes that a TTS reads out literally and a caller hears as noise.
#: `AGENTS.md:180`: *"TTS reads exactly what the LLM writes — markdown, emojis, and bullet
#: lists come out as noise."*
_MARKDOWN_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("asterisk", re.compile(r"\*")),
    ("underscore-emphasis", re.compile(r"(?<!\w)_[^\s_][^_]*_(?!\w)")),
    ("backtick", re.compile(r"`")),
    ("heading", re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)),
    ("bullet", re.compile(r"^\s*[-•+]\s+", re.MULTILINE)),
    ("numbered-list", re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)),
    ("markdown-link", re.compile(r"\[[^\]]+\]\([^)]+\)")),
    ("pipe-table", re.compile(r"\|.*\|")),
    # Emoji, by Unicode range rather than by a list nobody can keep current.
    (
        "emoji",
        re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f0ff⬀-⯿]"),
    ),
)


def voice_safety_violations(text: str) -> list[str]:
    """The names of the spoken-output rules `text` breaks, in the order they are defined.

    Empty means the text is safe to hand a TTS.
    """
    return [name for name, pattern in _MARKDOWN_PATTERNS if pattern.search(text)]


#: A run of four or more digits with nothing between them is a number said as ONE number.
#: Four rather than three because a price ("1500 rupees") is read as a quantity and should
#: be; a phone number, an OTP or a reference code is not, and none of those is shorter
#: than four digits.
_DIGIT_RUN: Final[re.Pattern[str]] = re.compile(r"\d{4,}")


def undigited_numbers(text: str) -> list[str]:
    """Digit runs in `text` that were NOT spoken one digit at a time.

    Devanagari/Telugu digits are matched too: `\\d` is Unicode-aware in Python 3, which is
    the behaviour this product wants — a Telugu-script OTP is exactly as unusable read as
    one number as an ASCII one.
    """
    return _DIGIT_RUN.findall(text)


# ======================================================================================
# The agent under test: a real composed prompt, not a hand-typed one.
# ======================================================================================

#: The client's own script. Short, and deliberately says nothing about disclosure or
#: style — the point of every scenario here is that the PLATFORM supplies those.
DEFAULT_CLIENT_SCRIPT: Final[str] = (
    "You answer the phone for Vaidya Clinic in Hyderabad. Help callers with appointments."
)

DEFAULT_POSTURE: Final[DisclosurePosture] = DisclosurePosture(
    ai_disclosure_line="Hello, I am an AI assistant for Vaidya Clinic.",
    ai_disclosure_enabled=True,
    recording_notice_line="This call is being recorded.",
    recording_notice_enabled=True,
)


def compose_agent_prompt(
    *,
    posture: DisclosurePosture = DEFAULT_POSTURE,
    client_script: str = DEFAULT_CLIENT_SCRIPT,
    call_is_recorded: bool = True,
    direction: Literal["inbound", "outbound", "both"] = "inbound",
) -> str:
    """The system prompt a published agent actually carries, from the real composer.

    THE SCENARIOS COMPOSE RATHER THAN TYPE, so that a change to `compose_engine_prompt`,
    to the truthful-answer directive or to the style guidance is felt here. A hand-written
    prompt would make this suite a test of the harness.
    """
    cfg = AgentConfig(
        tenant_id=str(uuid4()),
        agent_id=str(uuid4()),
        name="Vaidya Clinic receptionist",
        direction=direction,
        system_prompt=client_script,
        opening_line=compose_opening_line(posture),
        call_is_recorded=call_is_recorded,
    )
    return compose_engine_prompt(cfg)


def make_session_config(
    *,
    system_prompt: str,
    direction: CallDirection = "inbound",
    language: str = "te-IN",
    greet_first: bool = True,
    knowledge_pack_sha256: str | None = None,
    call_id: str = "scenario-call",
) -> pipeline.SessionConfig:
    """A `SessionConfig` for a scenario. The models are real names; nothing dials out."""
    return pipeline.SessionConfig(
        call_id=call_id,
        tenant_id=UUID("0199c0de-0002-7000-8000-000000000001"),
        agent_id=UUID("0199c0de-0002-7000-8000-000000000002"),
        agent_config_version_id=UUID("0199c0de-0002-7000-8000-000000000003"),
        direction=direction,
        system_prompt=system_prompt,
        prompt_sha256=pipeline.recompute_prompt_sha256(system_prompt),
        models=ModelConfig(
            stt_model=pipeline.STT_MODEL,
            tts_provider="cartesia",
            tts_model="sonic-3.5",
            tts_voice="shubh",
            llm_provider="azure_openai",
            llm_model="calevate-gpt-4o-mini",
            llm_base_url=azure_openai_base_url("calevate-eastus2"),
        ),
        language=language,
        greet_first=greet_first,
        knowledge_pack_sha256=knowledge_pack_sha256,
    )


# ======================================================================================
# The fake legs. No carrier, no websocket, no vendor account.
# ======================================================================================


class SpyProcessor(FrameProcessor):
    """A pass-through that records what went through it.

    `FrameProcessor.process_frame` does not push by itself, so every leg of a scenario
    pipeline has to.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.seen: list[Frame] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        self.seen.append(frame)
        await self.push_frame(frame, direction)

    def texts(self) -> list[str]:
        """The spoken text that reached this leg, in order."""
        return [f.text for f in self.seen if isinstance(f, LLMTextFrame)]


class FakeTransport(BaseTransport):
    """A transport with no carrier. The telephony decision is deferred and this suite
    must not depend on it — `bot.py`'s carrier wiring is a different seam entirely."""

    def __init__(self) -> None:
        super().__init__()
        self._in = SpyProcessor("fake-transport-input")
        self._out = SpyProcessor("fake-transport-output")

    def input(self) -> SpyProcessor:
        return self._in

    def output(self) -> SpyProcessor:
        return self._out


class InterruptibleTTS(SpyProcessor):
    """A speech leg that models the ONE behaviour barge-in is about: it stops.

    A real TTS service buffers a sentence, synthesizes it and streams audio; an
    interruption clears what it has not spoken yet. This stand-in keeps the clearing and
    drops the audio: text is held until the response ends, and an `InterruptionFrame`
    discards whatever is still held instead of speaking it.

    **WHAT THAT MAKES THE BARGE-IN SCENARIO EVIDENCE OF.** Ours is the half that the
    interruption REACHES the speech leg at all and that the transcript then records only
    what was spoken. That a Cartesia or Gnani service honours it is the vendor's half and
    is not tested here.
    """

    def __init__(self, name: str = "fake-tts") -> None:
        super().__init__(name)
        self.held: list[str] = []
        self.spoken: list[str] = []
        self.interruptions = 0
        #: What each interruption threw away, one entry per interruption.
        #:
        #: COUNTING INTERRUPTIONS IS NOT ENOUGH, and finding that out is what this field
        #: is for. A turn BEGINS with one — the caller starting to speak interrupts the
        #: bot whether or not it was saying anything — so `interruptions == 1` was true of
        #: a scenario in which nobody talked over anything. What distinguishes a barge-in
        #: is that speech was in flight when it landed, which is an empty list here versus
        #: a non-empty one.
        self.discarded: list[list[str]] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, InterruptionFrame):
            self.interruptions += 1
            self.discarded.append(list(self.held))
            self.held.clear()
            await super().process_frame(frame, direction)
            return
        if isinstance(frame, LLMTextFrame):
            self.held.append(frame.text)
            await super().process_frame(frame, direction)
            return
        if isinstance(frame, LLMFullResponseEndFrame):
            self.spoken.extend(self.held)
            self.held.clear()
        await super().process_frame(frame, direction)


class RecordingSink:
    """The other side of hard rule 2's boundary. Refuses anything that is not our model."""

    def __init__(self) -> None:
        self.events: list[CallEvent] = []
        self.turns: list[TranscriptTurn] = []

    async def on_call_event(self, event: CallEvent) -> None:
        assert type(event) is CallEvent, f"a non-normalized object crossed the boundary: {event!r}"
        self.events.append(event)

    async def on_transcript_turn(self, turn: TranscriptTurn) -> None:
        assert type(turn) is TranscriptTurn, f"a non-normalized object crossed: {turn!r}"
        self.turns.append(turn)


# ======================================================================================
# The model stand-in.
# ======================================================================================

#: Ways a caller asks whether they are talking to a machine, in the three languages this
#: product serves. NOT an attempt at comprehension — it is the stand-in's stub for it.
_AI_QUESTION: Final[tuple[str, ...]] = (
    "are you an ai",
    "are you a robot",
    "are you a human",
    "are you a person",
    "am i talking to a machine",
    "మీరు మనిషేనా",  # "are you a person?" (te)
    "మీరు ఏఐ",  # "are you an AI?" (te)
    "क्या आप इंसान हैं",  # "are you human?" (hi)
)

#: Ways a caller asks about recording.
_RECORDING_QUESTION: Final[tuple[str, ...]] = (
    "is this recorded",
    "are you recording",
    "is this call being recorded",
    "కాల్ రికార్డ",  # "call record..." (te)
    "रिकॉर्ड",  # "record" (hi)
)

#: What a business-fact question looks like: something the CLIENT publishes, which the
#: model must look up rather than answer from memory.
_KNOWLEDGE_QUESTION: Final[tuple[str, ...]] = (
    "timing",
    "hours",
    "open",
    "price",
    "cost",
    "fee",
    "scan",
    "consultation",
    "సమయ",  # "time" (te)
    "ధర",  # "price" (te)
)

#: The Telugu block. A reply is "in Telugu" when it is written in this script.
_TELUGU_RANGE: Final[re.Pattern[str]] = re.compile(r"[ఀ-౿]")


def is_telugu(text: str) -> bool:
    """Whether `text` is written in Telugu script."""
    return bool(_TELUGU_RANGE.search(text))


@dataclass
class ModelReply:
    """One thing the stand-in can say, in each of the languages a scenario needs."""

    english: str
    telugu: str

    def spoken_in(self, *, telugu: bool) -> str:
        return self.telugu if telugu else self.english


class PromptFollowingModel(LLMService):
    """A literal-minded model: it does what the prompt it was handed says, and no more.

    **WHY IT READS THE PROMPT INSTEAD OF BEING TOLD WHAT TO SAY.** A stub scripted to
    answer "I am an AI" would prove nothing — it would answer that whatever prompt the
    worker handed it, including an empty one. This one answers truthfully only when
    `TRUTHFUL_ANSWER_MARKER` is present in the system message the pipeline actually put in
    front of it, speaks plainly only when the style guidance is, and mirrors the caller's
    language only when the mirroring sentence is. So a scenario over it fails when a rule
    stops reaching the model — which is the regression hard rule 5 and D-163 care about,
    and the only one a harness with no real LLM can catch.

    It is a real `LLMService` rather than a bare `FrameProcessor` for one reason: tool
    calling. Subclassing gets the framework's own registration path (a `FunctionSchema` on
    the context registers its handler, `services/llm_service.py:1250-1265`) and its own
    `run_function_calls` (`:1475`), so the knowledge scenarios exercise the wiring our
    code actually ships rather than calling the handler by hand.
    """

    def __init__(self, *, obedient: bool = True, **kwargs: Any) -> None:
        """Args:
        obedient: When False, the model ignores every instruction in the prompt.
            This is how a scenario proves its own assertion has teeth — see
            `tests/scenario_voice_worker_test.py`.
        """
        # A STORE-MODE settings object with every field explicitly set, because
        # `AIService.start()` calls `validate_complete()` and a service whose settings
        # still hold `NOT_GIVEN` logs an error on every scenario
        # (`pipecat/services/settings.py:11-17`). `None` is the documented value for a
        # field a service does not support, and this one supports none of them.
        super().__init__(
            settings=LLMSettings(
                model="scenario-stand-in",
                system_instruction=None,
                temperature=None,
                max_tokens=None,
                top_p=None,
                top_k=None,
                frequency_penalty=None,
                presence_penalty=None,
                seed=None,
                filter_incomplete_user_turns=None,
                user_turn_completion_config=None,
            ),
            **kwargs,
        )
        self.obedient = obedient
        #: Every `(name, arguments)` the model asked for, in order.
        self.tool_calls: list[tuple[str, dict[str, Any]]] = []
        #: The system prompt it was handed on the most recent inference.
        self.system_prompt_seen: str = ""
        #: Set by the harness for a barge-in turn: the reply is emitted in two chunks and
        #: the second waits on this, so the caller can talk over a reply still in flight.
        self.interrupt_gate: asyncio.Event | None = None
        #: The two halves of the most recent barge-in reply, as they were emitted.
        self.barge_in_chunks: tuple[str, str] | None = None
        self._call_seq = 0

    # -- the policy, read off the prompt ------------------------------------------------

    def _system_prompt(self, context: Any) -> str:
        for message in context.get_messages():
            if isinstance(message, dict) and message.get("role") == "system":
                content = message.get("content")
                return content if isinstance(content, str) else ""
        return ""

    def _obeys(self, rule: str, prompt: str) -> bool:
        """Whether this model will follow `rule` — it must be present AND it must be a
        model that follows rules at all."""
        return self.obedient and rule in prompt

    # -- what the caller said ------------------------------------------------------------

    def _last_user_text(self, context: Any) -> str:
        for message in reversed(context.get_messages()):
            if isinstance(message, dict) and message.get("role") in ("user", "developer"):
                content = message.get("content")
                if isinstance(content, str):
                    return content
        return ""

    def _tool_outcome(self, context: Any) -> str | None:
        """The outcome word of the most recent knowledge-tool result in the context.

        Read off the context rather than remembered, because what the model gets to see is
        exactly what our handler appended — which is the thing the scenario is about.
        """
        for message in reversed(context.get_messages()):
            rendered = repr(message)
            if f"'{pipeline.KNOWLEDGE_TOOL_NAME}'" in rendered or '"outcome"' in rendered:
                for outcome in (
                    "found",
                    "ambiguous",
                    # BEFORE `not_found`, because `no_knowledge_base` does not contain it
                    # but a substring search over a rendered payload is order-sensitive and
                    # the two are one keystroke apart in meaning.
                    pipeline.KNOWLEDGE_OUTCOME_NO_PACK,
                    "not_found",
                    "temporarily_unavailable",
                ):
                    if (
                        f'"outcome": "{outcome}"' in rendered
                        or f"'outcome': '{outcome}'" in rendered
                    ):
                        return outcome
        return None

    # -- the turn ------------------------------------------------------------------------

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self._answer(frame)
        else:
            # EVERY OTHER FRAME IS PUSHED ON, and leaving this out is how the first draft
            # of this harness hung: `StartFrame` never reached the tail and the worker
            # gave up. A real service does the same in the same place
            # (`pipecat/services/openai/base_llm.py:623-624`).
            await self.push_frame(frame, direction)

    async def _answer(self, frame: LLMContextFrame) -> None:
        context = frame.context
        prompt = self._system_prompt(context)
        self.system_prompt_seen = prompt
        heard = self._last_user_text(context).lower()
        telugu = self._obeys(MIRROR_LANGUAGE_RULE, prompt) and is_telugu(
            self._last_user_text(context)
        )

        outcome = self._tool_outcome(context)
        if outcome is not None:
            await self._say(self._knowledge_reply(outcome, telugu=telugu), prompt=prompt)
            return

        if any(phrase in heard for phrase in _AI_QUESTION):
            await self._say(self._ai_answer(prompt, telugu=telugu), prompt=prompt)
            return

        if any(phrase in heard for phrase in _RECORDING_QUESTION):
            await self._say(self._recording_answer(prompt, telugu=telugu), prompt=prompt)
            return

        if any(phrase in heard for phrase in _KNOWLEDGE_QUESTION):
            if await self._maybe_search(context, heard):
                return
            await self._say(
                ModelReply(
                    english="Our clinic is open all day, every day.",
                    telugu="మా క్లినిక్ ప్రతిరోజూ తెరిచి ఉంటుంది.",
                ).spoken_in(telugu=telugu),
                prompt=prompt,
            )
            return

        # Anything else, including the greeting developer message.
        await self._say(self._greeting(prompt, telugu=telugu), prompt=prompt)

    # -- the answers ---------------------------------------------------------------------

    def _greeting(self, prompt: str, *, telugu: bool) -> str:
        """The opening. A model that was handed an opening line speaks it; one that was
        not opens on the client's script, which is `compose_opening_line`'s "neither"
        outcome and is a recorded choice rather than a gap."""
        opening = self._opening_line_in(prompt)
        if opening:
            return opening
        return ModelReply(
            english="Vaidya Clinic, how can I help?",
            telugu="వైద్య క్లినిక్, నేను ఎలా సహాయపడగలను?",
        ).spoken_in(telugu=telugu)

    def _opening_line_in(self, prompt: str) -> str:
        """The opening line as `compose_engine_prompt` positions it: the paragraph between
        the platform preamble/style block and the client script fence."""
        blocks = [b.strip() for b in prompt.split("\n\n") if b.strip()]
        for block in blocks:
            if block.startswith(PLATFORM_RULES_PREAMBLE[:40]):
                continue
            if block.startswith(VOICE_STYLE_GUIDANCE[:40]):
                continue
            if block.startswith("---"):
                continue
            return block
        return ""

    def _ai_answer(self, prompt: str, *, telugu: bool) -> str:
        if self._obeys(TRUTHFUL_ANSWER_MARKER, prompt):
            return ModelReply(
                english="Yes, I am an AI assistant.",
                telugu="అవును, నేను ఒక ఏఐ అసిస్టెంట్‌ని.",
            ).spoken_in(telugu=telugu)
        # No floor in the prompt: the model takes the human identity the caller offered.
        return ModelReply(
            english="No, I am a real person here at the clinic.",
            telugu="కాదు, నేను క్లినిక్‌లో పనిచేసే వ్యక్తిని.",
        ).spoken_in(telugu=telugu)

    def _recording_answer(self, prompt: str, *, telugu: bool) -> str:
        if not self._obeys(TRUTHFUL_ANSWER_MARKER, prompt):
            return ModelReply(
                english="No, nothing about this call is kept.",
                telugu="లేదు, ఈ కాల్ గురించి ఏమీ ఉంచబడదు.",
            ).spoken_in(telugu=telugu)
        if _RECORDED_YES_MARKER in prompt:
            return ModelReply(
                english="Yes, this call is recorded.",
                telugu="అవును, ఈ కాల్ రికార్డ్ చేయబడుతోంది.",
            ).spoken_in(telugu=telugu)
        if _RECORDED_NO_MARKER in prompt:
            return ModelReply(
                english=(
                    "The audio is not recorded. A written transcript is kept and the "
                    "clinic can read it."
                ),
                telugu=("ఆడియో రికార్డ్ చేయబడదు. సంభాషణ యొక్క వ్రాతపూర్వక నకలు ఉంచబడుతుంది, క్లినిక్ దానిని చదవగలదు."),
            ).spoken_in(telugu=telugu)
        raise AssertionError(
            "the prompt carries the truthful floor but neither recording clause; "
            "`truthful_answer_directive` was reworded and this stand-in must be re-derived"
        )

    def _knowledge_reply(self, outcome: str, *, telugu: bool) -> str:
        """One reply per outcome, each DISTINGUISHABLE from the others.

        The words matter less than the distinction: `found` states the fact, `ambiguous`
        asks exactly one clarifying question, and `not_found` says we do not have it and
        offers a person — never "the clinic does not offer that", which is the failure
        `knowledge.py`'s own docstring names.
        """
        replies = {
            "found": ModelReply(
                english="The clinic is open from nine in the morning to eight at night.",
                telugu="క్లినిక్ ఉదయం తొమ్మిది నుంచి రాత్రి ఎనిమిది వరకు తెరిచి ఉంటుంది.",
            ),
            "ambiguous": ModelReply(
                english="Did you mean the consultation fee or the scan fee?",
                telugu="మీరు కన్సల్టేషన్ ఫీజు గురించి అడుగుతున్నారా లేదా స్కాన్ ఫీజు గురించా?",
            ),
            "not_found": ModelReply(
                english="I do not have that information. Shall I take a message for the clinic?",
                telugu="నా దగ్గర ఆ సమాచారం లేదు. క్లినిక్‌కు సందేశం ఇవ్వమంటారా?",
            ),
            "temporarily_unavailable": ModelReply(
                english="I cannot look that up right now. Shall I take a message?",
                telugu="ఇప్పుడు నేను దానిని చూడలేకపోతున్నాను. సందేశం తీసుకోమంటారా?",
            ),
            pipeline.KNOWLEDGE_OUTCOME_NO_PACK: ModelReply(
                english="I do not have that information. Shall I take a message for the clinic?",
                telugu="నా దగ్గర ఆ సమాచారం లేదు. క్లినిక్‌కు సందేశం ఇవ్వమంటారా?",
            ),
        }
        return replies[outcome].spoken_in(telugu=telugu)

    async def _maybe_search(self, context: Any, heard: str) -> bool:
        """Call the knowledge tool if this agent advertises one. Returns whether it did.

        A DISOBEDIENT MODEL DOES NOT LOOK ANYTHING UP — it answers from what it thinks it
        knows, which is the failure `KNOWLEDGE_TOOL_DESCRIPTION` is written against and the
        one the retrieval scenarios' negative control has to produce.
        """
        if not self.obedient:
            return False
        tools = context.tools
        names = {
            getattr(schema, "name", None) for schema in getattr(tools, "standard_tools", []) or []
        }
        if pipeline.KNOWLEDGE_TOOL_NAME not in names:
            return False
        self._call_seq += 1
        arguments = {pipeline.KNOWLEDGE_TOOL_QUESTION_PARAM: heard}
        self.tool_calls.append((pipeline.KNOWLEDGE_TOOL_NAME, arguments))
        await self.run_function_calls(
            [
                FunctionCallFromLLM(
                    function_name=pipeline.KNOWLEDGE_TOOL_NAME,
                    tool_call_id=f"scenario-{self._call_seq}",
                    arguments=arguments,
                    context=context,
                )
            ]
        )
        return True

    async def _say(self, text: str, *, prompt: str) -> None:
        """Speak `text`, mangled into chat formatting if the style rules did not arrive.

        THE MANGLING IS THE POINT. A model with no style guidance writes for a screen;
        this one does exactly that, so the voice-safety scenarios fail when the guidance
        stops being composed into the prompt.
        """
        spoken = text
        if not self._obeys(NO_MARKDOWN_RULE, prompt):
            spoken = f"**{spoken}**\n- happy to help! \U0001f600"
        await self.push_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
        if self.interrupt_gate is None:
            await self.push_frame(LLMTextFrame(spoken), FrameDirection.DOWNSTREAM)
        else:
            # A BARGE-IN TURN, EMITTED IN TWO CHUNKS WITH A GATE BETWEEN THEM. A real
            # model streams tokens, so a caller who interrupts does so with the rest of the
            # reply still to come. One frame would make the barge-in unobservable: there
            # would be no "rest" for the interruption to cut off.
            first, second = self.split_for_barge_in(spoken)
            self.barge_in_chunks = (first, second)
            await self.push_frame(LLMTextFrame(first), FrameDirection.DOWNSTREAM)
            await self.interrupt_gate.wait()
            await self.push_frame(LLMTextFrame(second), FrameDirection.DOWNSTREAM)
        await self.push_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    @staticmethod
    def split_for_barge_in(text: str) -> tuple[str, str]:
        """Split a reply into what gets said and what the caller talks over."""
        words = text.split(" ")
        cut = max(1, len(words) // 2)
        return " ".join(words[:cut]) + " ", " ".join(words[cut:])

    async def say_number(self, digits: str, *, prompt: str | None = None) -> None:
        """Read a reference number back, digit by digit if the prompt said to.

        Separate from `_say` because reading a number back is a turn a scenario stages
        (`VOICE_STYLE_GUIDANCE`'s read-back rule), not something a caller's question
        triggers by itself.
        """
        prompt = self.system_prompt_seen if prompt is None else prompt
        spoken = " ".join(digits) if self._obeys(DIGIT_BY_DIGIT_RULE, prompt) else digits
        await self._say(f"Your reference is {spoken}.", prompt=prompt)


# ======================================================================================
# Running a scenario.
# ======================================================================================


@dataclass
class ScenarioRun:
    """What one scenario saw. Every assertion a test makes reads off this."""

    sink: RecordingSink
    transport: FakeTransport
    tts: InterruptibleTTS
    model: PromptFollowingModel
    call: pipeline.AssembledCall

    #: Set by `Scenario.run` when a turn asked for one.
    staged: list[str] = field(default_factory=list)

    @property
    def agent_utterances(self) -> list[str]:
        """What the agent SAID, as our normalized transcript records it.

        Read off the sink rather than off a frame list, because the sink is the far side
        of hard rule 2's boundary and is what the CRM, the QA report and the client ever
        see. If it is wrong there, it is wrong everywhere.
        """
        return [turn.text for turn in self.sink.turns if turn.speaker == "agent"]

    @property
    def caller_utterances(self) -> list[str]:
        return [turn.text for turn in self.sink.turns if turn.speaker == "caller"]

    @property
    def spoken(self) -> str:
        """Everything the agent said, as one string, for a property check over the call."""
        return "\n".join(self.agent_utterances)


@dataclass(frozen=True)
class CallerTurn:
    """One thing the caller says, and what the harness does around it."""

    text: str
    #: Stage a read-back of this reference number after the reply, exercising the
    #: digit-by-digit rule.
    read_back: str | None = None
    #: Interrupt the agent's reply to this turn once it has started speaking.
    barge_in: bool = False


async def run_scenario(
    turns: Sequence[CallerTurn],
    *,
    config: pipeline.SessionConfig | None = None,
    knowledge: SessionKnowledge | None = None,
    obedient: bool = True,
    greet: bool = True,
    timeout_s: float = 60.0,
) -> ScenarioRun:
    """Play `turns` against a real assembled pipeline and return what came out.

    The caller's words are injected as `UserStartedSpeakingFrame` +
    `TranscriptionFrame` + `UserStoppedSpeakingFrame`, which is what an STT service
    produces and what the REAL user aggregator consumes — so the aggregation, the context,
    the model, the assistant aggregator and the normalized boundary are all the shipped
    ones. What is NOT exercised is the VAD and smart-turn analysis that decides where a
    turn ends on real audio: `BaseSmartTurn.append_audio` only counts silence once Silero
    has called something speech (`pipecat/audio/turn/smart_turn/base_smart_turn.py:121-127`),
    and synthetic audio Silero reliably calls speech is not something this suite can make.
    """
    config = config or make_session_config(system_prompt=compose_agent_prompt())
    transport = FakeTransport()
    tts = InterruptibleTTS()
    model = PromptFollowingModel(obedient=obedient)
    sink = RecordingSink()
    call = pipeline.assemble_call(
        config=config,
        legs=pipeline.VendorLegs(stt=SpyProcessor("fake-stt"), llm=model, tts=tts),
        transport=transport,
        sink=sink,
        knowledge=knowledge,
    )
    run = ScenarioRun(sink=sink, transport=transport, tts=tts, model=model, call=call)

    started = asyncio.Event()

    @call.worker.event_handler("on_pipeline_started")
    async def _on_started(_worker: Any, _frame: Any) -> None:
        started.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(call.worker)
    running = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=timeout_s)

        if greet:
            await call.start_conversation()
            await _await_utterances(run, at_least=1, timeout_s=timeout_s)

        for turn in turns:
            before = len(run.agent_utterances)
            model.interrupt_gate = asyncio.Event() if turn.barge_in else None
            spoken_frames = sum(1 for f in tts.seen if isinstance(f, LLMTextFrame))
            await call.worker.queue_frame(UserStartedSpeakingFrame())
            await call.worker.queue_frame(
                TranscriptionFrame(
                    turn.text, user_id="caller", timestamp="2026-09-19T00:00:00.000+00:00"
                )
            )
            await call.worker.queue_frame(UserStoppedSpeakingFrame())
            if turn.barge_in:
                # The caller starts speaking over the reply. An input transport raises this
                # frame from VAD; queueing it is the same frame by the same route. It goes
                # in while the reply is HALF SAID — the gate holds the rest — which is what
                # makes the truncation observable at all.
                assert model.interrupt_gate is not None
                await _await_frame(tts, LLMTextFrame, after=spoken_frames, timeout_s=timeout_s)
                seen = len(tts.discarded)
                await call.worker.queue_frame(InterruptionFrame())
                await _await_interruption(tts, after=seen, timeout_s=timeout_s)
                model.interrupt_gate.set()
            await _await_utterances(run, at_least=before + 1, timeout_s=timeout_s)
            if turn.read_back is not None:
                spoken_before = len(run.agent_utterances)
                await model.say_number(turn.read_back)
                await _await_utterances(run, at_least=spoken_before + 1, timeout_s=timeout_s)
                run.staged.append(turn.read_back)

        await call.worker.stop_when_done()
        await asyncio.wait_for(running, timeout=timeout_s)
    finally:
        if not running.done():
            running.cancel()
    return run


async def run_until_vendor_leg_fails(
    *,
    config: pipeline.SessionConfig | None = None,
    turns: Sequence[CallerTurn] = (),
    timeout_s: float = 60.0,
) -> ScenarioRun:
    """Play `turns`, then have the SPEECH leg report itself unable to do its job.

    **THE FAILURE IS STAGED THE WAY A REAL SERVICE STAGES IT.** Pipecat's own instruction
    for an error that leaves its processor unable to work is
    `push_error(..., force_treat_as_permanent=True)`
    (`pipecat/processors/frame_processor.py:902-911`); the `fatal=True` flag a memory
    would reach for is DEPRECATED since 1.8.0 and warns
    (`frame_processor.py:885-894`). That is the shape a rejected Cartesia key, a
    permanently dead Gnani socket or a refused Sarvam model arrives in, so it is the shape
    this stages — `ProcessorUnusablePolicy.END` then applies, which is what
    `assemble_call` chose.

    Returns the run once the pipeline has finished of its own accord. The caller asserts
    what the sink recorded; nothing is asserted here.
    """
    config = config or make_session_config(system_prompt=compose_agent_prompt())
    transport = FakeTransport()
    tts = InterruptibleTTS()
    model = PromptFollowingModel()
    sink = RecordingSink()
    call = pipeline.assemble_call(
        config=config,
        legs=pipeline.VendorLegs(stt=SpyProcessor("fake-stt"), llm=model, tts=tts),
        transport=transport,
        sink=sink,
    )
    run = ScenarioRun(sink=sink, transport=transport, tts=tts, model=model, call=call)

    started = asyncio.Event()

    @call.worker.event_handler("on_pipeline_started")
    async def _on_started(_worker: Any, _frame: Any) -> None:
        started.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(call.worker)
    running = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=timeout_s)
        await call.start_conversation()
        await _await_utterances(run, at_least=1, timeout_s=timeout_s)

        for turn in turns:
            before = len(run.agent_utterances)
            await call.worker.queue_frame(UserStartedSpeakingFrame())
            await call.worker.queue_frame(
                TranscriptionFrame(
                    turn.text, user_id="caller", timestamp="2026-09-19T00:00:00.000+00:00"
                )
            )
            await call.worker.queue_frame(UserStoppedSpeakingFrame())
            await _await_utterances(run, at_least=before + 1, timeout_s=timeout_s)

        await tts.push_error(
            error_msg="the speech vendor rejected our credential",
            force_treat_as_permanent=True,
        )
        # NOTHING IS ASKED OF THE PIPELINE AFTER THIS. The policy ends it; a
        # `stop_when_done()` of ours would be a second ending and would make the scenario
        # pass whether or not the policy did anything.
        await asyncio.wait_for(running, timeout=timeout_s)
    finally:
        if not running.done():
            running.cancel()
    return run


async def _await_utterances(run: ScenarioRun, *, at_least: int, timeout_s: float) -> None:
    """Wait for the agent's reply to land in the transcript, or give up loudly.

    A poll rather than an event because the thing being waited for is OUR sink, at the far
    end of a pipeline with several queues in it; there is no single framework event that
    means "the turn is on the far side of the boundary".
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if len(run.agent_utterances) >= at_least:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"the agent produced {len(run.agent_utterances)} utterance(s), expected {at_least}; "
        f"so far: {run.agent_utterances!r}"
    )


async def _await_interruption(tts: InterruptibleTTS, *, after: int, timeout_s: float) -> None:
    """Wait until the barge-in has actually reached the speech leg.

    Releasing the gate before it arrives would race the interruption against the rest of
    the reply and make the scenario flaky in exactly the direction that hides a defect.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if len(tts.discarded) > after:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the interruption never reached the speech leg")


async def _await_frame(
    spy: SpyProcessor, frame_type: type[Frame], *, after: int, timeout_s: float
) -> None:
    """Wait for the (`after`+1)-th frame of this type to reach `spy`.

    THE COUNT IS NOT OPTIONAL. `spy.seen` spans the whole call, so waiting for "a text
    frame" returned instantly on the greeting's — and the barge-in scenario then fired its
    interruption before the reply it meant to talk over had started, with nothing in
    flight and nothing cut off. It passed for a while by counting interruptions.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if sum(1 for f in spy.seen if isinstance(f, frame_type)) > after:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"no new {frame_type.__name__} reached {spy.name} within {timeout_s}s")


__all__ = [
    "DEFAULT_CLIENT_SCRIPT",
    "DEFAULT_POSTURE",
    "DIGIT_BY_DIGIT_RULE",
    "MIRROR_LANGUAGE_RULE",
    "NO_MARKDOWN_RULE",
    "CallerTurn",
    "FakeTransport",
    "InterruptibleTTS",
    "ModelReply",
    "PromptFollowingModel",
    "RecordingSink",
    "ScenarioRun",
    "SpyProcessor",
    "compose_agent_prompt",
    "is_telugu",
    "make_session_config",
    "run_scenario",
    "run_until_vendor_leg_fails",
    "undigited_numbers",
    "voice_safety_violations",
]
