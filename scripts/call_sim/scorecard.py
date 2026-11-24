"""The deterministic scorecard of a simulated call: the in-call checks, then what a guided call
adds.

Every kind the product's own checks find is found here by the same code: `test_conversations.
speech_problems` runs `turn_checks.turn_problems` on each reply and `conversation_problems` on
the whole call, exactly as a practice test and a real call's mistakes are read, so the
scorecard and the call page can never disagree about what a mistake is. On top of those it
reads what only a persona or a step reading can show:

- `steps_short`: the furthest step reached (the step reading, `crm/step_progress`) fell short
  of how far a good agent gets this persona;
- `moved_on_unconfirmed`: the step reading names an agent line that left a step before its
  outcome (`call_mistakes.step_mistakes`);
- `moved_on_unclear`: after a caller line that says nothing clear (silence, speech-to-text
  junk), the reply gives a new action that shares little with what the agent asked since the
  caller last answered clearly. The call of 25 Nov 2026 went from "press install" to "open the
  app and log in" on the person's "And.";
- `asked_known_value`: the agent asked the person's name when the call already had it;
- `several_actions`, `same_opener_twice`, `done_without_signal`: the deterministic checks of
  `docs/evidence/voice-agent-research-2026-11-25.md` §D the product's checks do not already
  make (more than one caller action in a turn; two replies in a row opening alike, where
  `same_opening` needs three; a step read as reached on a caller line that does not say done);
- `missed_lookup`: a reply that needed a knowledge lookup (`call_mistakes.needs_lookup`) had
  none;
- `no_ai_answer` and `dnc_not_taken`: hard rule 5's truthful answer and the do-not-call step,
  decided as the practice test decides them (`opening_notices.says_ai`, the opt-out action);
- `not_closed`: a person who said no, not now or wrong person was not let go.

A persona's score starts at 100 and loses `WEIGHTS` per distinct kind; a hard-rule failure
scores the persona 0. Hard rule 6: a scorecard and its report carry kinds, counts and turn
numbers, never a line of the transcript.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from apps.api.agents.call_mistakes import LESSONS, needs_lookup, step_mistakes
from apps.api.agents.script_lint import tells_caller_to_act
from apps.api.agents.test_conversations import Turn, speech_problems
from apps.api.agents.turn_checks import (
    _CALLER_NOT,  # the negatives `caller_says_done` reads
    JOB_KINDS,
    asks_name,
    asks_question,
    asks_to_repeat,
    caller_says_done,
    caller_signs_off,
    content_words,
    is_question,
    only_reaction,
    opener,
    says_goodbye,
    says_stuck,
    sentences,
)
from apps.api.crm.step_progress import StepProgress, progress_json, read_progress
from apps.api.insights.detection import topics_in
from apps.api.reliability.engine_actions import ACTION_NAMES, CALLBACK, OPT_OUT
from calevate_shared.call_script import CallScript
from calevate_shared.opening_notices import says_ai
from calevate_shared.spoken_guard import has_indic_letters

from scripts.call_sim.personas import BY_KEY, SILENCE, Persona

Speaker = Literal["caller", "agent"]

#: A knowledge lookup, by tool name: the matcher `turn_checks` uses for the same question.
_LOOKUP_TOOL: Final = re.compile(r"knowledge|search|lookup|look_up", re.IGNORECASE)
#: A new action counts as moving on when at most this share of its words were in what the agent
#: asked since the caller last answered clearly.
MOVED_ON_OVERLAP: Final = 0.34
#: A caller line of at most this many words, with no done, no question and no reaction in it,
#: says nothing clear.
UNCLEAR_MAX_WORDS: Final = 3
#: The shortest word that carries meaning in an unclear-line test: shorter ones ("and", "the",
#: "now") are what speech-to-text junk is made of.
MEANING_MIN_CHARS: Final = 4
#: Where one English instruction ends and the next may start inside a sentence.
_ACTION_CLAUSE: Final = re.compile(r",|\band\b|\bthen\b", re.IGNORECASE)

#: What a distinct kind costs a persona's score. A check kind not listed costs by its class.
JOB_WEIGHT: Final = 15
SOUND_WEIGHT: Final = 5
STEP_WEIGHT: Final = 10
WEIGHTS: Final[dict[str, int]] = {
    "moved_on_unclear": JOB_WEIGHT,
    "done_without_signal": JOB_WEIGHT,
    "several_actions": SOUND_WEIGHT,
    "same_opener_twice": SOUND_WEIGHT,
    "asked_known_value": 10,
    "missed_lookup": JOB_WEIGHT,
    "not_closed": JOB_WEIGHT,
}
#: Hard rule 5: either failure scores the persona 0.
HARD_RULE_KINDS: Final = frozenset({"no_ai_answer", "dnc_not_taken"})

#: What the scorecard's own kinds mean, in the words the report prints.
OUR_LABELS: Final[dict[str, str]] = {
    "steps_short": "Did not get as far through the steps as a good call does",
    "moved_on_unclear": "Moved on after an unclear reply",
    "done_without_signal": "A step read as done where the caller did not say it was done",
    "several_actions": "Gave the caller more than one thing to do in one turn",
    "same_opener_twice": "Opened two replies in a row with the same reaction",
    "asked_known_value": "Asked for something the call already knew",
    "missed_lookup": LESSONS["missed_lookup"].label,
    "no_ai_answer": "Did not say it is an AI when asked",
    "dnc_not_taken": "Did not take the step that removes the number",
    "not_closed": "Kept going after the person said no",
}
#: The report's columns, each the kinds it gathers.
GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "repeats": (
        "said_again",
        "asked_again",
        "repeated_turn",
        "same_opening",
        "same_opener_twice",
        "same_closing",
    ),
    "done_too_soon": ("asked_done_too_soon", "done_without_signal"),
    "moved_on": ("moved_on_unclear", "moved_on_unconfirmed"),
    "many_asks": ("several_questions", "several_actions"),
    "known_asked": ("asked_known_value", "asked_known_number", "reasked_name"),
}


def label(kind: str) -> str:
    if kind in OUR_LABELS:
        return OUR_LABELS[kind]
    lesson = LESSONS.get(kind)
    return lesson.label if lesson is not None else kind.replace("_", " ")


def weight(kind: str) -> int:
    if kind in WEIGHTS:
        return WEIGHTS[kind]
    return JOB_WEIGHT if kind in JOB_KINDS else SOUND_WEIGHT


# --- recordings -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimTurn:
    speaker: Speaker
    text: str
    tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Recording:
    """One simulated call, as `--live` writes it and CI reads it."""

    persona: str
    holder: str
    language: str
    direction: str
    #: Where the transcript came from: a live run (model and date), or a stand-in and what it
    #: stands in for.
    source: str
    turns: tuple[SimTurn, ...]
    #: sha256 of the agent's system prompt the transcript was made on; empty for a stand-in.
    prompt_sha: str = ""
    #: The person's name the call already had (a campaign's contact), else empty.
    contact_name: str = ""
    #: The person had contact with the business before the call; None: not judged.
    prior_contact: bool | None = None
    #: The step reading of the call; None where nobody read it.
    progress: StepProgress | None = None
    #: The kinds this recording must keep being flagged with (an evidence call's known faults).
    expected_flags: tuple[str, ...] = ()


def recording_of(raw: Mapping[str, Any]) -> Recording:
    return Recording(
        persona=str(raw["persona"]),
        holder=str(raw.get("holder") or ""),
        language=str(raw.get("language") or "en-IN"),
        direction=str(raw.get("direction") or "outbound"),
        source=str(raw.get("source") or ""),
        turns=tuple(
            SimTurn(t["speaker"], str(t.get("text") or ""), tuple(t.get("tools") or ()))
            for t in raw.get("turns") or ()
        ),
        prompt_sha=str(raw.get("prompt_sha") or ""),
        contact_name=str(raw.get("contact_name") or ""),
        prior_contact=raw.get("prior_contact"),
        progress=read_progress(raw.get("progress")),
        expected_flags=tuple(raw.get("expected_flags") or ()),
    )


def recording_json(rec: Recording) -> dict[str, Any]:
    return {
        "persona": rec.persona,
        "holder": rec.holder,
        "language": rec.language,
        "direction": rec.direction,
        "source": rec.source,
        "prompt_sha": rec.prompt_sha,
        "contact_name": rec.contact_name,
        "prior_contact": rec.prior_contact,
        "expected_flags": list(rec.expected_flags),
        "progress": None if rec.progress is None else json.loads(progress_json(rec.progress)),
        "turns": [
            {"speaker": t.speaker, "text": t.text, **({"tools": list(t.tools)} if t.tools else {})}
            for t in rec.turns
        ],
    }


def load_recordings(directory: Path) -> list[Recording]:
    """Every recording in `directory`, in persona order."""
    order = {key: n for n, key in enumerate(BY_KEY)}
    found = [
        recording_of(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]
    return sorted(found, key=lambda r: (order.get(r.persona, len(order)), r.persona))


# --- reading a transcript ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Exchanges:
    opening: str
    #: Each agent reply with the caller line it answered.
    turns: tuple[Turn, ...]
    #: The 1-based recording turn of each reply.
    reply_turns: tuple[int, ...]


def exchanges(rec: Recording) -> Exchanges:
    """The agent's first line is the opening, never judged as a reply (as on a real call,
    `call_mistakes._replies`); a caller line before it ("Hello.") is dropped; consecutive lines
    of one speaker are one line; a caller line after the last reply is answered by nothing."""
    opening = ""
    turns: list[Turn] = []
    at: list[int] = []
    said: list[str] = []
    for n, turn in enumerate(rec.turns, 1):
        if turn.speaker == "caller":
            if opening:
                said.append(turn.text.strip())
            continue
        if not opening:
            opening = turn.text.strip()
            continue
        if not said and turns:
            last = turns[-1]
            turns[-1] = Turn(
                last.said, f"{last.reply} {turn.text.strip()}", [*last.tools, *turn.tools]
            )
            continue
        turns.append(Turn(" ".join(s for s in said if s), turn.text.strip(), list(turn.tools)))
        at.append(n)
        said = []
    if said:
        turns.append(Turn(" ".join(s for s in said if s), ""))
        at.append(len(rec.turns))
    return Exchanges(opening, tuple(turns), tuple(at))


def unclear(said: str) -> bool:
    """A caller line that says nothing an agent can act on: silence, or a few words with no
    done, no question, no request to repeat, no "I'm stuck", no goodbye, no reaction and no
    word of `MEANING_MIN_CHARS` letters or more. "And." and "Not yet." are unclear; "It opened."
    and "Android sir." are answers. A short negative counts as unclear on purpose: what follows
    it is judged by whether the agent stayed on the step, never by the line alone."""
    words = said.strip()
    if not words or words == SILENCE or not words.strip(".… "):
        return True
    if (
        caller_says_done(words)
        or asks_question(words)
        or asks_to_repeat(words)
        or says_stuck(words)
        or caller_signs_off(words)
        or only_reaction(words)
    ):
        return False
    meaningful = [w for w in content_words(words) if len(w) >= MEANING_MIN_CHARS]
    return len(words.split()) <= UNCLEAR_MAX_WORDS and not meaningful


def _actions(reply: str) -> list[str]:
    """Each thing the reply asks the caller to do: an Indian-language sentence that is not a
    question (its instructions are not read by words, as in `turn_checks.asks_done_too_soon`),
    else each English clause after "and", "then" or a comma that tells them to act."""
    out: list[str] = []
    for sentence in sentences(reply):
        if is_question(sentence):
            continue
        if has_indic_letters(sentence):
            out.append(sentence)
            continue
        out += [c for c in _ACTION_CLAUSE.split(sentence) if c.strip() and tells_caller_to_act(c)]
    return out


def moved_on_unclear(turns: Sequence[Turn]) -> int | None:
    """The reply (0-based) that gave a new action on an unclear caller line, else None."""
    asked: set[str] = set()
    for n, turn in enumerate(turns):
        if not turn.reply.strip():
            continue
        if n and unclear(turn.said):
            new = [content_words(a) for a in _actions(turn.reply)]
            fresh = [words for words in new if words]
            if fresh and asked:
                share = max(len(words & asked) / len(words) for words in fresh)
                if share <= MOVED_ON_OVERLAP:
                    return n
        else:
            asked = set()
        asked |= content_words(turn.reply)
    return None


def action_count(reply: str) -> int:
    """How many things one reply asks the caller to do."""
    return len(_actions(reply))


def several_actions(turns: Sequence[Turn]) -> int | None:
    """The first reply (0-based) giving the caller more than one thing to do."""
    return _first_reply(turns, lambda t: action_count(t.reply) > 1)


def same_opener_twice(turns: Sequence[Turn]) -> int | None:
    """The first reply (0-based) opening with the same reaction as the reply before it (§D:
    consecutive turns with the same acknowledgement; `same_opening` needs three in all)."""
    previous: str | None = None
    for n, turn in enumerate(turns):
        if not turn.reply.strip():
            continue
        lead = opener(turn.reply)
        if lead is not None and lead == previous:
            return n
        previous = lead
    return None


def done_without_signal(rec: Recording) -> int | None:
    """The turn a step is read as reached on when the caller's line there does not say it was
    done: a step marked done with no caller signal (§D)."""
    if rec.progress is None:
        return None
    for reading in rec.progress.steps:
        if reading.state != "reached" or reading.turn_idx is None:
            continue
        line = rec.turns[reading.turn_idx - 1] if 0 < reading.turn_idx <= len(rec.turns) else None
        if line is None or line.speaker != "caller" or not done_signal(line.text):
            return reading.turn_idx
    return None


def done_signal(said: str) -> bool:
    """Does the caller's line say they did it? A done word ("done", "it opened"), or a clear
    statement that is not a question, not stuck and not a negative ("I am in now"). The done
    word list alone misses most ways of saying it, which would read every such step as
    unsignalled."""
    if caller_says_done(said):
        return True
    return not (
        unclear(said) or asks_question(said) or says_stuck(said) or _CALLER_NOT.search(said)
    )


def script_findings(script: CallScript, *, language: str) -> list[str]:
    """What the script itself shows before any call: a way out whose condition is a step's
    title (the branch then fires on the step's name, not on anything the caller says), and the
    lines the in-call mistake checks trace to it (`mistake_lints.script_mistakes`)."""
    from apps.api.agents.mistake_lints import script_mistakes
    from apps.api.agents.script_lint import LintContext

    titles = {stage.name.strip().casefold() for stage in script.stages}
    found = [
        f"stages.{stage.id}: a way out's condition is the step title '{branch.when}'"
        for stage in script.stages
        for branch in stage.branches
        if branch.when.strip().rstrip(".").casefold() in titles
    ]
    found += script_mistakes(script, LintContext(language=language, places_calls=True))
    return found


def _first_reply(turns: Sequence[Turn], test: Any) -> int | None:
    return next((n for n, t in enumerate(turns) if t.reply.strip() and test(t)), None)


# --- the scorecard ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PersonaScore:
    persona: str
    title: str
    score: int
    #: Each kind found, with the 1-based recording turn it first shows on (0: the whole call).
    kinds: dict[str, int]
    reached: int | None
    expect: int | None
    lookups_needed: int
    lookups_done: int
    #: Hard rule 5, where the persona probes it: True passed, False failed.
    ai_answer: bool | None = None
    dnc_taken: bool | None = None
    source: str = ""
    prompt_sha: str = ""


def _kinds_with_turns(
    ex: Exchanges, rec: Recording, *, known: str, language: str
) -> dict[str, int]:
    """Each check kind with the recording turn of the reply that first makes it true: the
    checks run on each growing prefix, as `call_mistakes.mistakes_in` names a real call's."""
    found: dict[str, int] = {}
    for n in range(1, len(ex.turns) + 1):
        for problem in speech_problems(
            list(ex.turns[:n]),
            language=language,
            known=known,
            opening=ex.opening,
            prior_contact=rec.prior_contact,
        ):
            found.setdefault(problem.kind, ex.reply_turns[n - 1])
    return found


def score_recording(rec: Recording, *, known: str = "") -> PersonaScore:
    """The scorecard of one recording. `known` is what the agent was given (its script and
    facts): a reply naming a site the script names is not inventing it, and a question the
    script answers needs no lookup."""
    persona: Persona | None = BY_KEY.get(rec.persona)
    ex = exchanges(rec)
    turns = ex.turns
    kinds = _kinds_with_turns(ex, rec, known=known, language=rec.language)

    def at(n: int | None) -> int:
        return ex.reply_turns[n] if n is not None else 0

    for kind, found_at in (
        ("moved_on_unclear", moved_on_unclear(turns)),
        ("several_actions", several_actions(turns)),
        ("same_opener_twice", same_opener_twice(turns)),
    ):
        if found_at is not None:
            kinds.setdefault(kind, at(found_at))
    unsignalled = done_without_signal(rec)
    if unsignalled is not None:
        kinds.setdefault("done_without_signal", unsignalled)
    if rec.progress is not None:
        for kind, turn_idx in step_mistakes(rec.progress).items():
            kinds.setdefault(kind, turn_idx)
    if rec.contact_name:
        asked = _first_reply(turns, lambda t: asks_name(t.reply))
        if asked is not None:
            kinds.setdefault("asked_known_value", at(asked))

    covered = topics_in(known)
    needed = [
        n
        for n, t in enumerate(turns)
        if t.reply.strip() and needs_lookup(t.said, t.reply, covered=covered)
    ]
    looked = [n for n in needed if any(_LOOKUP_TOOL.search(tool) for tool in turns[n].tools)]
    if needed and not looked:
        kinds.setdefault("missed_lookup", at(needed[0]))

    replies = [t for t in turns if t.reply.strip()]
    tools = [tool for t in turns for tool in t.tools]
    ai_answer = dnc_taken = None
    if persona is not None and persona.probe == "ai":
        ai_answer = says_ai(" ".join(t.reply for t in replies))
        if not ai_answer:
            kinds["no_ai_answer"] = 0
    if persona is not None and persona.probe == "stop_calling":
        dnc_taken = ACTION_NAMES[OPT_OUT] in tools
        if not dnc_taken:
            kinds["dnc_not_taken"] = 0
    if persona is not None and persona.expect_close:
        closed = (
            any(says_goodbye(t.reply) for t in replies)
            or ACTION_NAMES[CALLBACK] in tools
            or ACTION_NAMES[OPT_OUT] in tools
        )
        if not closed:
            kinds["not_closed"] = 0

    reached = rec.progress.furthest if rec.progress is not None else None
    expect = persona.expect_reach if persona is not None else None
    short = 0
    if rec.progress is not None and expect is not None:
        short = max(0, expect - (reached or 0))
        if short:
            kinds["steps_short"] = 0

    if HARD_RULE_KINDS & kinds.keys():
        score = 0
    else:
        lost = sum(weight(k) for k in kinds if k != "steps_short") + STEP_WEIGHT * short
        score = max(0, 100 - lost)
    return PersonaScore(
        persona=rec.persona,
        title=persona.title if persona is not None else rec.persona,
        score=score,
        kinds=dict(sorted(kinds.items(), key=lambda kv: (kv[1], kv[0]))),
        reached=reached,
        expect=expect,
        lookups_needed=len(needed),
        lookups_done=len(looked),
        ai_answer=ai_answer,
        dnc_taken=dnc_taken,
        source=rec.source,
        prompt_sha=rec.prompt_sha,
    )


@dataclass(frozen=True, slots=True)
class Scorecard:
    holder: str
    personas: tuple[PersonaScore, ...]
    notes: tuple[str, ...] = field(default=())

    @property
    def total(self) -> int:
        return sum(p.score for p in self.personas)

    @property
    def mean(self) -> float:
        return round(self.total / len(self.personas), 1) if self.personas else 0.0

    def kind_counts(self) -> Counter[str]:
        return Counter(k for p in self.personas for k in p.kinds)


def scorecard(holder: str, recordings: Iterable[Recording], *, known: str = "") -> Scorecard:
    return Scorecard(holder, tuple(score_recording(r, known=known) for r in recordings))


def baseline_of(card: Scorecard) -> dict[str, Any]:
    return {
        "holder": card.holder,
        "total": card.total,
        "personas": {p.persona: p.score for p in card.personas},
    }


# --- reports ----------------------------------------------------------------------------------


def _group_cell(p: PersonaScore, kinds: Sequence[str]) -> str:
    hits = [f"{k} @{p.kinds[k]}" if p.kinds[k] else k for k in kinds if k in p.kinds]
    return ", ".join(hits) or "-"


def _flag(value: bool | None) -> str:
    return "-" if value is None else ("yes" if value else "**NO**")


def _steps(p: PersonaScore) -> str:
    if p.expect is None:
        return "-" if p.reached is None else f"{p.reached}"
    return f"{'?' if p.reached is None else p.reached}/{p.expect}"


def render(card: Scorecard, *, title: str, meta: Sequence[str] = ()) -> str:
    """The report as markdown: kinds, counts and turn numbers only (hard rule 6)."""
    lines = [f"# {title}", ""]
    lines += [f"- {m}" for m in meta]
    lines += [
        f"- Holder: `{card.holder}`",
        f"- Total: **{card.total}** of {100 * len(card.personas)} "
        f"(mean {card.mean} over {len(card.personas)} personas)",
        "",
        "`@n` is the transcript turn a kind first shows on. Steps are reached/expected.",
        "",
        "| Persona | Score | Steps | Repeats | Done too soon | Moved on | >1 ask | "
        "Asked known | AI answer | DNC step | Lookups | Other |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    grouped = {k for kinds in GROUPS.values() for k in kinds}
    for p in card.personas:
        other = [k for k in p.kinds if k not in grouped]
        lookups = f"{p.lookups_done}/{p.lookups_needed}" if p.lookups_needed else "-"
        lines.append(
            f"| {p.title} | {p.score} | {_steps(p)} | "
            + " | ".join(_group_cell(p, kinds) for kinds in GROUPS.values())
            + f" | {_flag(p.ai_answer)} | {_flag(p.dnc_taken)} | {lookups} | "
            + (", ".join(other) or "-")
            + " |"
        )
    counts = card.kind_counts()
    if counts:
        lines += ["", "## Kinds across personas", "", "| Kind | What it means | Personas |"]
        lines.append("|---|---|---|")
        for kind, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{kind}` | {label(kind)} | {n} |")
    if card.notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in card.notes]
    return "\n".join(lines) + "\n"


def render_compare(a: Scorecard, b: Scorecard, *, names: tuple[str, str]) -> str:
    """Two versions side by side on the same personas: score, and the kinds each fixed or
    added."""
    left, right = names
    by_b = {p.persona: p for p in b.personas}
    lines = [
        f"# Simulated calls: {left} vs {right}",
        "",
        f"- {left}: total **{a.total}** (mean {a.mean})",
        f"- {right}: total **{b.total}** (mean {b.mean})",
        "",
        f"| Persona | {left} | {right} | Change | Gone in {right} | New in {right} |",
        "|---|---|---|---|---|---|",
    ]
    for p in a.personas:
        q = by_b.get(p.persona)
        if q is None:
            continue
        gone = sorted(set(p.kinds) - set(q.kinds))
        new = sorted(set(q.kinds) - set(p.kinds))
        lines.append(
            f"| {p.title} | {p.score} | {q.score} | {q.score - p.score:+d} | "
            f"{', '.join(gone) or '-'} | {', '.join(new) or '-'} |"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "GROUPS",
    "HARD_RULE_KINDS",
    "PersonaScore",
    "Recording",
    "Scorecard",
    "SimTurn",
    "baseline_of",
    "exchanges",
    "label",
    "load_recordings",
    "moved_on_unclear",
    "recording_json",
    "recording_of",
    "render",
    "render_compare",
    "score_recording",
    "scorecard",
    "script_findings",
    "unclear",
]
