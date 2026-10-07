"""The enforcement half of D-674: the agent may not read its instructions to a caller.

`calevate_shared.engine.CONFIDENTIALITY_RULE` asks the model to decline. A prompt is not a
security control — OWASP LLM07:2025 says the system prompt "should not be considered a
secret, nor should it be used as a security control" and asks for "a system of guardrails
outside of the LLM itself" (genai.owasp.org/llmrisk/llm072025-system-prompt-leakage, read
5 Oct 2026); OWASP LLM01:2025 mitigation 3 is output filtering with "string-checking", and
Anthropic's "Reduce prompt leak" guide names a post-processing filter over the model's
output as the second layer (docs.claude.com, read 5 Oct 2026). This module is that layer:
it reads every sentence the LLM produces BEFORE the TTS speaks it, and a sentence that
reproduces the agent's own instructions is never synthesised.

WHERE IT SITS, AND WHY THAT COSTS NO LATENCY. Between the LLM and the TTS — the position
Pipecat's own `LLMTextProcessor` occupies, which converts `LLMTextFrame` tokens into
sentence `AggregatedTextFrame`s "to handle or manipulate LLM text frames before they are
sent to ... TTS services" (`pipecat/processors/aggregators/llm_text_processor.py`). Every
TTS this worker builds runs in `TextAggregationMode.SENTENCE` (the default,
`pipecat/services/tts_service.py:298-299`), so the TTS already holds each sentence until
the first non-whitespace character after its terminal punctuation; it synthesises an
`AggregatedTextFrame` immediately (`tts_service.py:765-766`). So sentence buffering moves
here from inside the TTS rather than being added in front of it, and the only new cost on
the turn is the check itself (measured in `tests/voice_worker_output_guard_test.py`).

WHAT COUNTS AS A LEAK. Word 5-gram ("shingle") overlap with a REFERENCE built once per call
from the prompt the session was published with:

* **Platform text** — everything outside the client-script fence, the structured scaffold
  the platform writes inside it, and every tool's description. Never legitimately spoken,
  so the bar is low: a run of 10 consecutive words verbatim in one sentence, or 12 distinct
  matched shingles accumulated over the call (the piecemeal "and the next rule?" attack).
* **Client script** — legitimately spoken in part (facts written into a raw script), so
  the bar is a turn reproducing 24 or more words of it verbatim, beyond the "one or two
  short sentences" the style rules allow a turn.
* **Excluded on purpose**, because the agent is SUPPOSED to say them: the truthful-answer
  block (hard rule 5 makes its substance a required answer), the opening line, the
  `[T0 FACTS]` and `[OPENING]` sections, FAQ answers and the FAQ fallback, the caller-memory
  facts (filled per call, never in the reference) and anything a tool returns, which is
  where knowledge-base text arrives. A KB answer is the product working, not a leak.

Only runs of 3 or more consecutive matching shingles (7+ words) count at all, so a stock
phrase the model shares with the rules by coincidence ("a call back or a person") cannot
accumulate into a suppression over a long call.

Machine identifiers are a separate, simpler check: a tool name, a `snake_case` code or a
UUID is never speech, so a sentence carrying one is dropped.

WHAT IT DOES NOT CATCH, said plainly: a paraphrase, a translation (the prompt is English
and most calls are Telugu) or a spelled-out leak. Those are the prompt rule's job; this
layer bounds the verbatim case, which is the one an attacker can verify.

HARD RULE 6: the suppression log line carries ids, a reason word and a count. Never text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from calevate_shared.call_script import BUILTIN_END_CALL_RULE, GUARDRAILS_BLOCK
from calevate_shared.engine import (
    CLIENT_SCRIPT_CLOSE,
    CLIENT_SCRIPT_OPEN,
    PLATFORM_RULES_TAIL_HEADER,
)
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import (
    AggregatedTextFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.text.base_text_aggregator import AggregationType
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

#: Words per shingle. Five is long enough that ordinary speech rarely shares one with a
#: block of instructions by chance, and short enough that a one-line rule still yields
#: several.
SHINGLE_WORDS: Final = 5

#: Consecutive matching shingles below which a match is ignored entirely (7 words).
MIN_COUNTED_RUN: Final = 3

#: One run this long in one sentence is a platform leak (10 consecutive words verbatim).
PLATFORM_RUN_LIMIT: Final = 6

#: Distinct platform shingles over the whole call that make any further match a leak.
PLATFORM_CALL_LIMIT: Final = 12

#: Distinct client-script shingles in one turn that make it a leak (about 24 words).
CLIENT_TURN_LIMIT: Final = 20

#: Sections of a compiled script whose body is meant to be spoken (`call_script.py`,
#: `agents/t0.py`). A section runs to the next line starting with `[`, the rule both T0
#: splicers already use.
_SPOKEN_SECTIONS: Final = ("[T0 FACTS]", "[OPENING]")

#: FAQ lines that are spoken: an answer, and the header that carries the fallback sentence.
_SPOKEN_LINE_PREFIXES: Final = ("A:", "[FAQ]")

_UUID: Final = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
_SNAKE: Final = re.compile(r"(?<![\w@.])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![\w@])")

#: What the agent says instead of a suppressed leak, by primary language subtag. Neutral in
#: register and in grammatical gender. Spoken in the agent's PRIMARY language because that
#: is the language its voice is configured for (`pipeline._build_tts`).
DECLINES: Final[dict[str, str]] = {
    "en": "Sorry, I can't share that. Is there anything else I can help you with?",
    "te": "క్షమించండి, ఆ వివరాలు నేను చెప్పలేను. మీకు ఇంకేమైనా సహాయం కావాలా?",
    "hi": "माफ़ कीजिए, यह जानकारी बताई नहीं जा सकती। क्या मैं किसी और चीज़ में आपकी मदद करूँ?",
}


def decline_for(language: str | None) -> str:
    """The decline in the agent's primary language, English when there is no row for it."""
    subtag = (language or "en").split("-")[0].lower()
    return DECLINES.get(subtag, DECLINES["en"])


def _words(text: str) -> list[str]:
    """Casefolded words with surrounding punctuation and symbols stripped.

    Split on whitespace rather than `\\w+`: Python's `\\w` does not match Telugu vowel signs
    (category Mc/Mn), so a regex tokeniser would cut every Telugu word in two.
    """
    words: list[str] = []
    for raw in text.split():
        start, end = 0, len(raw)
        while start < end and unicodedata.category(raw[start])[0] in "PS":
            start += 1
        while end > start and unicodedata.category(raw[end - 1])[0] in "PS":
            end -= 1
        if start < end:
            words.append(raw[start:end].casefold())
    return words


def _shingles(words: Sequence[str]) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)]


def _reference_shingles(texts: Iterable[str]) -> frozenset[tuple[str, ...]]:
    """Shingles of each text separately, so no shingle spans two unrelated sources."""
    out: set[tuple[str, ...]] = set()
    for text in texts:
        out.update(_shingles(_words(text)))
    return frozenset(out)


def _without_spoken_parts(client_body: str) -> str:
    """The client script minus the parts the agent is meant to say out loud."""
    kept: list[str] = []
    skipping = False
    for line in client_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            skipping = stripped.startswith(_SPOKEN_SECTIONS)
        if skipping or stripped.startswith(_SPOKEN_LINE_PREFIXES):
            continue
        kept.append(line)
    return "\n".join(kept)


@dataclass(frozen=True, slots=True)
class LeakReference:
    """What this call's agent must not recite, as shingle sets. Built once per call."""

    platform: frozenset[tuple[str, ...]]
    client: frozenset[tuple[str, ...]]
    #: Tool names, which are identifiers and are matched as raw substrings.
    identifiers: frozenset[str]


def build_leak_reference(
    *, system_prompt: str, opening_line: str, tools: Sequence[FunctionSchema]
) -> LeakReference:
    """Split the published prompt into what is guarded, at which bar, and what is not.

    `system_prompt` is the UNFILLED composed prompt (`SessionConfig.system_prompt`), so the
    caller-memory facts — the caller's own words — are never in the reference.
    """
    head = system_prompt
    tail_at = head.rfind(PLATFORM_RULES_TAIL_HEADER)
    if tail_at != -1:
        # The truthful-answer block and nothing after it: the agent must say its substance.
        head = head[:tail_at]
    client_body = ""
    open_at = head.find(CLIENT_SCRIPT_OPEN)
    close_at = head.rfind(CLIENT_SCRIPT_CLOSE)
    if open_at != -1 and close_at > open_at:
        client_body = head[open_at + len(CLIENT_SCRIPT_OPEN) : close_at]
        head = head[:open_at] + "\n" + head[close_at + len(CLIENT_SCRIPT_CLOSE) :]
    if opening_line.strip():
        head = head.replace(opening_line.strip(), "\n")

    platform_texts = [head]
    # The structured compiler writes these INSIDE the fence; they are ours, not the client's.
    for scaffold in (GUARDRAILS_BLOCK, BUILTIN_END_CALL_RULE):
        if scaffold in client_body:
            client_body = client_body.replace(scaffold, "\n")
            platform_texts.append(scaffold)
    for tool in tools:
        platform_texts.append(tool.description)
        for spec in tool.properties.values():
            description = spec.get("description") if isinstance(spec, dict) else None
            if isinstance(description, str):
                platform_texts.append(description)
    return LeakReference(
        platform=_reference_shingles(platform_texts),
        client=_reference_shingles([_without_spoken_parts(client_body)]),
        identifiers=frozenset(tool.name for tool in tools),
    )


def _counted_matches(
    shingles: Sequence[tuple[str, ...]], reference: frozenset[tuple[str, ...]]
) -> tuple[set[tuple[str, ...]], int]:
    """Shingles inside runs of at least `MIN_COUNTED_RUN`, and the longest run's length."""
    counted: set[tuple[str, ...]] = set()
    longest = 0
    run: list[tuple[str, ...]] = []
    for shingle in [*shingles, None]:
        if shingle is not None and shingle in reference:
            run.append(shingle)
            continue
        if len(run) >= MIN_COUNTED_RUN:
            counted.update(run)
        longest = max(longest, len(run))
        run = []
    return counted, longest


@dataclass(slots=True)
class LeakJudge:
    """Scores sentences for one call. Pure and synchronous, so it is tested and timed alone.

    State spans the call (platform matches, for piecemeal extraction) and the turn (client
    matches, because a long call legitimately reads many facts from a raw script).
    """

    reference: LeakReference
    _call_platform: set[tuple[str, ...]] = field(default_factory=set)
    _turn_client: set[tuple[str, ...]] = field(default_factory=set)

    def start_turn(self) -> None:
        self._turn_client.clear()

    def judge(self, sentence: str) -> str | None:
        """`None` to speak it, or the reason word for suppressing it."""
        if _UUID.search(sentence) or _SNAKE.search(sentence):
            return "internal_identifier"
        if any(name in sentence for name in self.reference.identifiers):
            return "internal_identifier"
        shingles = _shingles(_words(sentence))
        if not shingles:
            return None
        platform, longest = _counted_matches(shingles, self.reference.platform)
        if longest >= PLATFORM_RUN_LIMIT:
            return "platform_rules"
        if platform:
            self._call_platform.update(platform)
            if len(self._call_platform) >= PLATFORM_CALL_LIMIT:
                return "platform_rules"
        client, _ = _counted_matches(shingles, self.reference.client)
        if client:
            self._turn_client.update(client)
            if len(self._turn_client) >= CLIENT_TURN_LIMIT:
                return "client_script"
        return None


class PromptLeakGuard(FrameProcessor):
    """LLM -> [this] -> TTS. Sentence-aggregates the model's text and drops what leaks.

    Mirrors `LLMTextProcessor`'s frame handling (aggregate on `LLMTextFrame`, flush on the
    response end or `EndFrame`, reset on `InterruptionFrame`) and adds the judgement between
    aggregation and push. A leak suppresses that sentence AND the rest of the turn — a
    reply that has started reciting is not going to stop by itself — and the decline is
    spoken once in its place. An identifier drops only its own sentence, silently.
    """

    def __init__(
        self,
        *,
        reference: LeakReference,
        decline: str,
        call_id: str,
        tenant_id: UUID,
        agent_id: UUID,
    ) -> None:
        super().__init__(name="prompt-leak-guard")
        self._judge = LeakJudge(reference)
        self._decline = decline
        self._aggregator = SimpleTextAggregator()  # type: ignore[no-untyped-call]
        self._ids = {"call_id": call_id, "tenant_id": str(tenant_id), "agent_id": str(agent_id)}
        self._turn_suppressed = False
        #: Suppressed sentences this call, by reason. Read by tests; logged per event.
        self.suppressed: dict[str, int] = {}

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            await self._aggregator.handle_interruption()  # type: ignore[no-untyped-call]
            self._start_turn()
            await self.push_frame(frame, direction)
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._start_turn()
            await self.push_frame(frame, direction)
        elif isinstance(frame, LLMTextFrame) and not frame.skip_tts:
            async for aggregation in self._aggregator.aggregate(frame.text):
                await self._release(aggregation.text)
        elif isinstance(frame, LLMFullResponseEndFrame | EndFrame):
            remaining = await self._aggregator.flush()
            if remaining is not None and remaining.text.strip():
                await self._release(remaining.text)
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    def _start_turn(self) -> None:
        self._turn_suppressed = False
        self._judge.start_turn()

    async def _release(self, sentence: str) -> None:
        if self._turn_suppressed:
            self._count("rest_of_turn")
            return
        reason = self._judge.judge(sentence)
        if reason is None:
            await self._speak(sentence)
            return
        self._count(reason)
        logger.warning(
            "output guard suppressed agent speech",
            reason=reason,
            words=len(sentence.split()),
            **self._ids,
        )
        if reason != "internal_identifier":
            self._turn_suppressed = True
            await self._speak(self._decline)

    def _count(self, reason: str) -> None:
        self.suppressed[reason] = self.suppressed.get(reason, 0) + 1

    async def _speak(self, text: str) -> None:
        out = AggregatedTextFrame(text=text, aggregated_by=AggregationType.SENTENCE)
        # As `LLMTextProcessor` sets it: the assistant aggregator records model text.
        out.append_to_context = True
        await self.push_frame(out)


__all__ = [
    "CLIENT_TURN_LIMIT",
    "DECLINES",
    "MIN_COUNTED_RUN",
    "PLATFORM_CALL_LIMIT",
    "PLATFORM_RUN_LIMIT",
    "SHINGLE_WORDS",
    "LeakJudge",
    "LeakReference",
    "PromptLeakGuard",
    "build_leak_reference",
    "decline_for",
]
