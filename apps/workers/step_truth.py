"""What a call's notes, summary, goal verdict and outcome say, kept true to where the call got
to against its script's steps.

The call review of 25 Nov 2026: a call that stopped on step 4 of 8 ("Where the call got to"
said so) was noted "Setup Progress: First expense recorded", "Interaction Outcome: Setup
successful" and "Campaign Goal Met: Yes", and its summary said an expense was recorded. A
prompt rule asked for the furthest step confirmed and was not followed; the step reading
overrode only a choice field it had mapped, and only after the notes were stored. So the
reading is now taken before the extraction, the extraction is asked against it, and this
module settles what comes back before anything is stored.

Two sources say a step was NOT reached:

* the after-call step reading (`workers/step_progress`), when the owner has turned Pip on: a
  step judged `not_reached` beyond the furthest step reached;
* the transcript itself, whatever the consent: a step whose own words (the distinctive words
  of its scenario names, `step_terms`) the agent raised with no caller line after it was never
  confirmed (`transcript_bound`). The 25 Nov call ended on the agent asking for step 4.

What is settled against them: a status, progress or outcome detail, the notes detail, a goal
detail, the goal verdict, the business outcome, and the summary and headline. A clause that
says an unreached step happened, or that the whole job was done on a call that stopped short
(the agent's own "you have finished the setup" repeated as fact, 27 Nov 2026), is taken out
of prose (`without_unreached`) rather than the
whole sentence, so what did happen stays said. A clause that only says the step was asked
for or explained ("asked the caller to record an expense") is true and kept (`_PENDING`).

A detail the reading says is about one step (`StepProgress.details`) is decided by that step
alone, not by words: it stands when the step was reached, even on a call that stopped short
later, and a value saying it happened goes when the step was not reached.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.call_script import CallScript
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import ExtractionOutput, ExtractionSchemaSpec, whole_call_detail

from apps.api.crm.step_progress import StepProgress, progress_values, side_steps
from apps.workers.redaction import redact
from apps.workers.step_progress import step_names, steps_of

#: The core lead field a model writes free prose into ("Extra Details" on the call page).
NOTES_KEY: Final = "notes"

_WORD: Final = re.compile(r"[A-Za-z]+")
#: Words too general to say which step a sentence is about: the verbs every step uses and
#: the call's own vocabulary. Without them "the agent checked the app" would claim any step
#: named "Check ...".
_GENERAL: Final = frozenset(
    {
        "about", "account", "agent", "already", "call", "caller", "check", "complete",
        "confirm", "customer", "details", "done", "enter", "explain", "final", "finalise",
        "finalize", "finish", "first", "from", "give", "help", "into", "make", "next", "open",
        "person", "phone", "press", "record", "screen", "show", "start", "step", "take",
        "tell", "that", "their", "them", "then", "they", "this", "verify", "what", "when",
        "with", "your",
    }
)  # fmt: skip
#: A scenario named for something NOT being so ("Not registered") is a branch about an
#: absence; its words say nothing about a step being done.
_ABSENCE: Final = re.compile(r"\b(?:not|no|never|without|non)\b", re.I)
#: A clause about the step being asked for, explained or not done is true of a call that
#: never reached it.
_PENDING: Final = re.compile(
    r"(?:\b(?:not|no|never|without|before|until|yet|asked?|asking|told|tell|telling|"
    r"instruct\w*|guid\w*|explain\w*|want\w*|will|would|could|should|about\s+to|going\s+to|"
    r"next|try|tried|trying|attempt\w*|request\w*|suggest\w*|while|remind\w*|unable|"
    r"cannot|pending)\b|n[\u2019']t\b)",
    re.I,
)
#: A value that says the whole job is done. `complet\w*`, not `complete\w*`: "confirmed
#: completion of all steps" kept a summary false on a call that stopped at step 9 of 11
#: (28 Nov 2026).
_DONE: Final = re.compile(
    r"\b(?:success\w*|complet\w*|fully|finish\w*|done|all\s+set|set\s*up|operational|"
    r"working|(?:all|each|every)\s+(?:of\s+)?(?:the\s+)?steps?|everything)\b",
    re.I,
)
#: What keeps a completion word from claiming completion in the summary's prose: a denial,
#: a wish or something still to come. Narrower than `_PENDING`, whose "guided" and
#: "explained" excuse an "asked to record" clause but also let "completed the setup with the
#: agent's guidance" stand on a call that stopped two steps short.
_NOT_DONE: Final = re.compile(
    r"\b(?:not|no|never|yet|before|until|will|would|could|should|about\s+to|going\s+to|"
    r"try|tried|trying|pending|wants?|wanted|asked)\b|n[\u2019']t\b",
    re.I,
)
_SENTENCE: Final = re.compile(r"(?<=[.!?])\s+")
_CLAUSE: Final = re.compile(r"\s*(?:;|,\s*(?:and|but|then)\s+|,\s+|\s+(?:and|but|then)\s+)\s*")
_GOAL_DETAIL: Final = re.compile(r"\bgoals?\b", re.I)
_YES: Final = frozenset({"yes", "true", "met", "reached", "achieved"})
_NO: Final = ("no", "false", "not met", "not reached")


def _stem(word: str) -> str:
    """A crude stem, enough to make "expenses" and "expense" one word: a plural `s` off,
    then the first six letters."""
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w[:6]


_GENERAL_STEMS: Final = frozenset(_stem(w) for w in _GENERAL)


def _stems(text: str) -> set[str]:
    return {
        stem
        for word in _WORD.findall(text)
        if len(word) >= 4 and (stem := _stem(word)) not in _GENERAL_STEMS
    }


def step_terms(script: CallScript) -> dict[int, frozenset[str]]:
    """Each step's distinctive words: from its scenario names, the words no other step's
    names use. A step named for an absence, or with no word of its own, has none."""
    named = {n: [s.name for s in stages] for n, stages in steps_of(script).items()}
    words = {n: set().union(*(_stems(name) for name in names)) for n, names in named.items()}
    out: dict[int, frozenset[str]] = {}
    for n, names in named.items():
        if any(_ABSENCE.search(name) for name in names):
            continue
        others = set().union(*(w for m, w in words.items() if m != n))
        own = words[n] - others
        if own:
            out[n] = frozenset(own)
    return out


def transcript_bound(
    terms: dict[int, frozenset[str]], turns: Sequence[TranscriptTurn]
) -> tuple[frozenset[int], frozenset[int]]:
    """`(possible, unconfirmed)` from the words alone. A step is possible when the caller
    named it, or the agent raised it and the caller spoke after; unconfirmed when the agent
    raised it and the caller never spoke again. A step nobody named is neither: a call in
    another script cannot be read this way, and silence is not evidence."""
    rows = [(turn.speaker, _stems(turn.text)) for turn in turns if turn.text.strip()]
    raised: dict[int, int] = {}
    named: set[int] = set()
    for i, (speaker, stems) in enumerate(rows):
        for step, own in terms.items():
            if not stems & own:
                continue
            if speaker == "caller":
                named.add(step)
            elif speaker == "agent":
                raised.setdefault(step, i)
    answered = {
        step for step, i in raised.items() if any(sp == "caller" for sp, _ in rows[i + 1 :])
    }
    possible = named | answered
    return frozenset(possible), frozenset(set(raised) - possible)


@dataclass(frozen=True, slots=True)
class StepFacts:
    names: dict[int, str]
    terms: dict[int, frozenset[str]]
    #: Steps the call shows reached: the reading's, or with no reading the steps the
    #: transcript makes possible.
    reached: frozenset[int]
    #: Steps the call shows were not reached.
    missed: frozenset[int]
    #: Side steps (`crm/step_progress.side_steps`) and steps named for an absence ("Not
    #: registered"): never the step a call stops short of.
    branches: frozenset[int]
    progress: StepProgress | None
    script_goal: str = ""

    @property
    def incomplete(self) -> bool:
        """The call stopped short. From a reading: the step after the furthest reached was
        not reached, or a step before the script's last was not reached with the steps
        between left unclear (a call judged "reached" to step 2, unclear to 8 and not reached
        at 9 of 10 stopped short as surely as one judged not reached at 3). From the words
        alone: a step went unconfirmed while the script names a later one the call never got
        to. The last step's question going unanswered is how a finished call often ends, and
        is not stopping short."""
        if self.progress is not None:
            after = (self.progress.furthest or 0) + 1
            last = max((n for n in self.names if n not in self.branches), default=0)
            return any(
                step not in self.branches and (step == after or step < last) for step in self.missed
            )
        return any(
            later > step and later not in self.reached and later not in self.branches
            for step in self.missed
            for later in self.terms
        )

    def goal_step(self, goal: str | None) -> int | None:
        """The step that means the goal is met: the reading's mapping, or with no reading the
        last step whose own words the goal uses."""
        if self.progress is not None:
            return self.progress.goal_step
        said = _stems(goal or self.script_goal)
        named = [n for n, own in self.terms.items() if own & said]
        return max(named) if named else None


def facts_of(
    script: CallScript, progress: StepProgress | None, turns: Sequence[TranscriptTurn]
) -> StepFacts:
    names = step_names(script)
    terms = step_terms(script)
    possible, unconfirmed = transcript_bound(terms, turns)
    if progress is not None:
        reached = {n for n in names if progress.shows_reached(n)}
        missed = {
            s.step for s in progress.steps if s.state == "not_reached" and s.step not in reached
        }
    else:
        reached, missed = set(possible), set()
    branches = set(side_steps(script)) | {
        n for n, stages in steps_of(script).items() if any(_ABSENCE.search(s.name) for s in stages)
    }
    return StepFacts(
        names=names,
        terms=terms,
        reached=frozenset(reached),
        missed=frozenset((missed | unconfirmed) - reached),
        branches=frozenset(branches),
        progress=progress,
        script_goal=script.goal or "",
    )


def prompt_note(facts: StepFacts) -> str | None:
    """Where the call got to, for the extraction prompt: the steps reached (only from a
    reading; the transcript alone shows what was possible, not what was done) and the steps
    not reached. None when there is nothing to say."""
    lines = []
    if facts.progress is not None and facts.reached:
        lines.append("Reached: " + "; ".join(facts.names[n] for n in sorted(facts.reached)))
    if facts.missed:
        lines.append("Not reached: " + "; ".join(facts.names[n] for n in sorted(facts.missed)))
    return redact("\n".join(lines)).text if lines else None


def _claims(clause: str, facts: StepFacts) -> bool:
    """Whether a clause says an unreached step happened, or says the whole job got done on
    a call that stopped short ("the agent said the setup was complete")."""
    if _PENDING.search(clause):
        return False
    stems = _stems(clause)
    if any(stems & facts.terms.get(step, frozenset()) for step in facts.missed):
        return True
    return _claims_done(clause, facts)


def claims_unreached(text: str, facts: StepFacts) -> bool:
    """Whether some clause of `text` says a step the call did not reach happened."""
    return any(
        _claims(clause, facts)
        for sentence in _SENTENCE.split(text.strip())
        for clause in _CLAUSE.split(sentence)
    )


def without_unreached(text: str, facts: StepFacts) -> str:
    """`text` with each clause that says an unreached step happened taken out; a sentence
    left with nothing is dropped. Unchanged when nothing claims one."""
    if not facts.missed or not text.strip():
        return text
    return _without_clauses(text, lambda clause: _claims(clause, facts))


def _without_clauses(text: str, claims: Callable[[str], bool]) -> str:
    if not text.strip():
        return text
    kept_sentences: list[str] = []
    changed = False
    for sentence in _SENTENCE.split(text.strip()):
        end = sentence[-1] if sentence[-1:] in (".", "!", "?") else ""
        body = sentence[:-1] if end else sentence
        clauses = [c for c in _CLAUSE.split(body) if c]
        kept = [c for c in clauses if not claims(c)]
        if len(kept) == len(clauses):
            kept_sentences.append(sentence)
            continue
        changed = True
        if kept:
            joined = kept[0] if len(kept) == 1 else ", ".join(kept[:-1]) + " and " + kept[-1]
            kept_sentences.append(joined[:1].upper() + joined[1:] + (end or "."))
    return " ".join(kept_sentences) if changed else text


def _step_name(facts: StepFacts, step: int) -> str:
    return redact(" ".join(facts.names.get(step, "").split())).text.rstrip(".")


def where_it_got_to(facts: StepFacts) -> str | None:
    """The summary's code-built half: one English sentence saying how far the call got
    through its script's main steps (side steps and steps named for an absence are not the
    path a call walks). None when there is nothing the code can say.

    Built rather than asked for because the model's own account was false twice running
    (27 and 28 Nov 2026: "confirmed completion of all steps" on calls that stopped two
    steps short), and scrubbing its words after the fact was widened twice and still
    missed. From a reading: every main step reached, or the furthest reached and the first
    one missed. From the words alone (no reading): only the first step the call did not
    get to, because silence about a step is not evidence it was done."""
    main = sorted(n for n in facts.names if n not in facts.branches)
    if not main:
        return None
    missed = [n for n in main if n in facts.missed]
    if facts.progress is None:
        return f'The call did not get to "{_step_name(facts, missed[0])}".' if missed else None
    reached = [n for n in main if n in facts.reached]
    if reached and len(reached) == len(main):
        return "The call went through every step of the script."
    if not missed:
        return f'The call reached "{_step_name(facts, reached[-1])}".' if reached else None
    stop = next((n for n in missed if not reached or n > reached[-1]), missed[0])
    left = sum(1 for n in main if n > stop and n not in facts.reached)
    more = "" if not left else " or the step after it" if left == 1 else f" or the {left} after it"
    if not reached or stop < reached[0]:
        return f'The call stopped before "{_step_name(facts, stop)}"{more}.'
    return (
        f'The call reached "{_step_name(facts, reached[-1])}" and did not reach '
        f'"{_step_name(facts, stop)}"{more}.'
    )


def with_where_it_got_to(summary: str, facts: StepFacts) -> str:
    """The summary in two parts: the prose with every clause claiming an unreached step or
    the whole job done taken out (`without_unreached`), then `where_it_got_to`. The prose
    is what the caller wanted and said; how far the call got is the code's. Empty prose
    stays empty: a summary still to be written in English (the language pass) is not
    replaced by the clause alone. Composing twice adds the clause once."""
    prose = _true_prose(summary, facts).strip()
    clause = where_it_got_to(facts)
    if not prose or clause is None or clause in prose:
        return prose
    end = "" if prose[-1:] in (".", "!", "?") else "."
    return f"{prose}{end} {clause}"


def _true_prose(text: str, facts: StepFacts) -> str:
    """`text` without a clause claiming an unreached step, nor, on a call that stopped short
    or whose last main step is not shown reached, a clause calling the job done."""
    prose = without_unreached(text, facts)
    if facts.incomplete or _end_unshown(facts):
        prose = _without_clauses(prose, lambda c: _says_done(c, facts) and not _NOT_DONE.search(c))
    return prose


def overstates(text: str, facts: StepFacts) -> bool:
    """Whether some clause of `text` says more than the steps show: what
    `with_where_it_got_to` would take out of it."""
    return bool(text.strip()) and _true_prose(text, facts) != text


def _end_unshown(facts: StepFacts) -> bool:
    """A reading that does not show the script's last main step reached: no prose may then
    call the job done, even when no step was judged `not_reached` (steps left unclear)."""
    main = [n for n in facts.names if n not in facts.branches]
    return facts.progress is not None and bool(main) and max(main) not in facts.reached


def _says_done(value: str, facts: StepFacts) -> bool:
    """A value saying the whole job is done, unless it names a step the call did reach."""
    if not _DONE.search(value):
        return False
    reached = set().union(*(facts.terms.get(n, frozenset()) for n in facts.reached))
    return not _stems(value) & reached


def _claims_done(value: str, facts: StepFacts) -> bool:
    """A value saying the whole job is done ("Setup successful") on a call that stopped
    short, unless it names a step the call did reach ("Installation complete")."""
    return facts.incomplete and _says_done(value, facts)


def _says_it_happened(value: Any) -> bool:
    """Whether a detail's value says what it is about happened: true, or words that do not
    say it is not done, pending or only asked for ("Installed", not "Not installed")."""
    if value is True:
        return True
    return isinstance(value, str) and not _PENDING.search(value)


def _goal_detail_value(field_type: str, choices: Sequence[str], missed: bool) -> Any | None:
    """What a goal detail noted as met becomes when the goal's step was not reached: no, when
    the call shows it missed and the detail can say no; else nothing."""
    if not missed:
        return None
    if field_type == "bool":
        return False
    return next((c for c in choices if c.strip().casefold() in _NO), None)


def settle(
    extraction: ExtractionOutput,
    facts: StepFacts,
    spec: ExtractionSchemaSpec,
    *,
    goal: str | None,
    outcomes: Sequence[BusinessOutcome],
) -> tuple[ExtractionOutput, list[str]]:
    """The extraction with every value that claims an unreached step put right, and the
    names of what changed (field keys and fixed keys, never values: hard rule 6)."""
    data = dict(extraction.data)
    changed: set[str] = set()

    def put(key: str, value: Any | None) -> None:
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        changed.add(key)

    if facts.progress is not None:
        for key, value in progress_values(facts.progress, data, spec).items():
            put(key, value)

    goal_step = facts.goal_step(goal)
    goal_missed = goal_step is not None and goal_step in facts.missed
    goal_unshown = goal_step is not None and goal_step not in facts.reached
    goal_judged = goal_missed or (goal_unshown and facts.progress is not None)

    for field in spec.fields:
        if field.key not in data or field.key in changed:
            continue
        value = data[field.key]
        if _GOAL_DETAIL.search(f"{field.key.replace('_', ' ')} {field.label}") and field.type in (
            "bool",
            "enum",
        ):
            said_met = value is True or (
                isinstance(value, str) and value.strip().casefold() in _YES
            )
            if said_met and goal_judged:
                put(field.key, _goal_detail_value(field.type, field.enum_values or [], goal_missed))
            continue
        about = facts.progress.details.get(field.key) if facts.progress is not None else None
        if about is not None:
            # A detail about one step stands or falls with that step, whatever the steps
            # after it did: "Installation Status" stays on a call that went on to stop at the
            # sale (28 Nov 2026).
            if about not in facts.reached and _says_it_happened(value):
                put(field.key, None)
            continue
        if not isinstance(value, str):
            continue
        if not (whole_call_detail(field.key, field.label) or field.key == NOTES_KEY):
            continue
        if field.type == "enum":
            if claims_unreached(value, facts) or _claims_done(value, facts):
                put(field.key, None)
            continue
        kept = without_unreached(value, facts)
        if not kept.strip() or _claims_done(kept, facts):
            put(field.key, None)
        elif kept != value:
            put(field.key, kept)

    update: dict[str, Any] = {}
    if changed:
        update["data"] = data
    if extraction.goal_reached == "yes" and goal_judged and goal_step is not None:
        name = facts.names.get(goal_step, "")
        update["goal_reached"] = "no" if goal_missed else "unclear"
        update["goal_reason"] = (
            f"The call did not get as far as {name}."
            if goal_missed
            else f"The call does not show that {name} was done."
        )
    elif extraction.goal_reason:
        reason = without_unreached(extraction.goal_reason, facts)
        if reason != extraction.goal_reason:
            update["goal_reason"] = reason
    chosen = next((o for o in outcomes if o.key == extraction.business_outcome), None)
    if chosen is not None:
        step = facts.progress.outcomes.get(chosen.key) if facts.progress is not None else None
        if (
            (step is not None and step not in facts.reached)
            or claims_unreached(chosen.label, facts)
            or _claims_done(chosen.label, facts)
        ):
            update["business_outcome"] = None
    for prose, settled in (
        ("summary", with_where_it_got_to(extraction.summary, facts)),
        ("headline", without_unreached(extraction.headline, facts)),
    ):
        if settled != getattr(extraction, prose):
            update[prose] = settled
    changed.update(k for k in update if k != "data")
    if not update:
        return extraction, []
    return extraction.model_copy(update=update), sorted(changed)


__all__ = [
    "NOTES_KEY",
    "StepFacts",
    "claims_unreached",
    "facts_of",
    "overstates",
    "prompt_note",
    "settle",
    "step_terms",
    "transcript_bound",
    "without_unreached",
]
