"""Score Pip's script writer on a fixed set of holders, so a writer change is measured before
it ships rather than judged by the founder's next test call.

    uv run python -m scripts.eval_script_writer                    # recorded outputs, no model
    uv run python -m scripts.eval_script_writer --cases rytu_khata_install,clinic_reminder
    uv run python -m scripts.eval_script_writer --write-report     # under docs/evidence/
    uv run python -m scripts.eval_script_writer --write-baseline   # lock in the counts CI holds
    uv run python -m scripts.eval_script_writer --import-live run.json   # live outputs -> recorded

On the VPS, where our Gemini key is (one command, from the deployed checkout; the case set is
copied into the running workers container because the image carries `scripts/` but not
`tests/`):

    sudo -u calevate bash -lc 'cd /var/www/calevate && C="docker compose -p calevate \
      -f compose.prod.yml" && $C cp tests/fixtures/script_writer_cases workers:/tmp/swc \
      && $C exec -T workers python -m scripts.eval_script_writer --cases-dir /tmp/swc \
      --live --spend --judge --judge-against recorded --format json \
      > docs/evidence/script-writer-eval/live-$(date +%F).json'

THE CASE SET (`tests/fixtures/script_writer_cases/cases/*.json`) is a dozen holders of
different trades, directions and languages, each a business profile, a main task broken into
the items a script must cover, what the holder notes (each marked when it is a judgement read
from the whole call rather than a question), what the calling list already knows, knowledge
snippets and the agent's capabilities. Every text in it is English; a Telugu or Hindi line
only ever comes from the model.

THREE LAYERS, REPORTED APART, deterministic first, as the research's scorecard orders them
(`docs/evidence/voice-agent-research-2026-11-25.md` D; the report maps each of its checks).

1. The repo's own lints, every one: `script_lint.script_problems`, each one-argument
   `script_lint.*_problems` found by name (so a lint added later is scored without an edit
   here), each `mistake_lints` kind and `script_heal.heal_findings`. They are the product's
   checks; this file never re-implements one. A `<check>_problems` named after a structural
   check is scored as that check, not here, so one problem has one count.
2. Structural checks (`CHECKS`), each a deterministic reading of the script against the
   case: a judgement field or a known value asked, a line asking or giving several things,
   a branch that is not a decision, a step after the close, no purpose at the start, a
   main-task item no step covers, what a Telugu or Hindi line says that callers do not (a
   bracketed double, a textbook word, an English word the register data gives a spoken word
   for; other English is ordinary code-mixing), the agent claiming the caller's action, and
   a step outcome written for one scenario. Where `script_lint` has `<check>_problems` it
   makes the check (`_upstream`), so the two never disagree; the eval adds to it only what
   the lint cannot read from the script alone (`EXTENDS`).
3. A judge for naturalness only, on our Gemini leg, optional and never part of CI:
   `--judge` scores each script on `RUBRIC` with the quoted lines first and every quote
   checked against its line; `--judge-against` compares each script with an earlier one,
   asked in both orders, and a verdict the order changes is a split for the founder's ear.
   The report says what it does not control (`JUDGE_CAVEATS`).

RECORDED AND LIVE. Without `--live` the scripts scored are `recorded/<case>.json`: the
production Rytu Khata script of 25 Nov 2026 in English stand-in form, and hand-written fake
model outputs for the rest, which a live run's `--import-live` replaces. A stand-in keyed
`en-IN` names the language it stands for and the words the real line wrote in English
letters, so the register check reads them as it would the real line's. CI scores the recorded
set against `baseline.json`; a count that moved either way fails until the baseline is
rewritten, as `coverage_baseline.json` is held (that file is never touched here).

`--live` runs the writer as a campaign's or line's first script is written
(`workers/campaign_script._write`): the draft from the trade's plan, the one refining edit
with the same ask, then code's mends (`script_structure.settled`). The passes that need the
account in the database are not run (the review's repair, the call-mistake repair rounds and
the opening repair of `script_proposal.finish_written`), so a live score measures the writer
before those rounds. It spends on our key, so it refuses without `--spend` and prints the
tokens used; nothing is metered to an account.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from apps.api.agents import mistake_lints, script_lint, turn_checks
from apps.api.agents.script_heal import heal_findings
from apps.api.agents.script_lint import CapabilityManifest, LintContext
from calevate_shared.call_script import (
    CallScript,
    ConversationStage,
    substitute_variables,
)
from calevate_shared.calling_window import IST
from calevate_shared.extraction import whole_call_detail
from calevate_shared.spoken_guard import (
    OWN_LETTER_LANGUAGES,
    has_indic_letters,
    textbook_problem,
)
from calevate_shared.spoken_style import language_pack

ROOT: Final = Path(__file__).resolve().parent.parent
CASES_DIR: Final = ROOT / "tests" / "fixtures" / "script_writer_cases"
REPORT_DIR: Final = ROOT / "docs" / "evidence" / "script-writer-eval"
BASELINE: Final = CASES_DIR / "baseline.json"

Source = Literal["stand-in", "live"]


# --- the case set --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Noted:
    """One detail the holder notes. `judged`: read from the whole call (an outcome, a level,
    whether the goal was met), never a question anyone can answer."""

    label: str
    reason: str = ""
    judged: bool = False

    def is_judged(self) -> bool:
        return self.judged or whole_call_detail("", self.label)


@dataclass(frozen=True, slots=True)
class TaskItem:
    """One thing the main task asks a call to do. Covered when one step's text holds a word
    of every group in `terms` (`covers`)."""

    id: str
    text: str
    terms: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    title: str
    holder: Literal["campaign", "line"]
    business_name: str
    business_type: str
    agent_name: str
    description: str
    language: str
    languages: tuple[str, ...]
    direction: str
    capabilities: CapabilityManifest
    main_task: str
    items: tuple[TaskItem, ...]
    noted: tuple[Noted, ...]
    #: What the calling list already gives for each person, by label ("name").
    known: tuple[str, ...]
    knowledge: tuple[tuple[str, str], ...]
    #: Words of which one says why we call, for a placed call's start.
    purpose_terms: tuple[str, ...]
    #: Groups of alternatives a call may meet (`("android", "iphone")`): an outcome naming
    #: one of a group and not the rest is written for one scenario.
    variants: tuple[tuple[str, ...], ...] = ()
    #: Words the caller sees on screen or the trade uses in English, beyond the owner's text.
    screen_terms: tuple[str, ...] = ()
    purpose: str = ""
    goal: str = ""
    consent_source: str | None = None

    def places_calls(self) -> bool:
        return self.holder == "campaign"

    def owner_text(self) -> str:
        """Everything the owner wrote: an English word in it is theirs to have said."""
        return " ".join(
            [
                self.business_name,
                self.agent_name,
                self.description,
                self.main_task,
                self.purpose,
                self.goal,
                *(part for pair in self.knowledge for part in pair),
                *self.screen_terms,
            ]
        )

    def collect(self) -> tuple[str, ...]:
        """What the writer is told the holder's calls ask, as `script_builder.job_details`
        tells it: every noted detail but those read from the whole call by their label
        (`whole_call_detail`). A judgement the label does not give away still reaches the
        writer, as it does in production; asking it is then the writer's fault to score."""
        return tuple(
            f"{n.label}: {n.reason}" if n.reason else n.label
            for n in self.noted
            if not whole_call_detail("", n.label)
        )

    def lint_context(self, language: str | None = None) -> LintContext:
        return LintContext(
            manifest=self.capabilities,
            facts=" ".join([self.main_task, *(text for _t, text in self.knowledge)]),
            agent_name=self.agent_name,
            business_name=self.business_name,
            collect=tuple(n.label for n in self.noted if not whole_call_detail("", n.label)),
            judged=tuple(n.label for n in self.noted if whole_call_detail("", n.label)),
            language=self.language if language is None else language,
            places_calls=self.places_calls(),
        )


def _strings(raw: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in raw) if isinstance(raw, list) else ()


def case_from(raw: dict[str, Any]) -> Case:
    caps = raw.get("capabilities") or {}
    direction = str(raw.get("direction") or "inbound")
    return Case(
        id=str(raw["id"]),
        title=str(raw["title"]),
        holder="campaign" if raw["holder"] == "campaign" else "line",
        business_name=str(raw["business_name"]),
        business_type=str(raw.get("business_type") or "custom"),
        agent_name=str(raw.get("agent_name") or ""),
        description=str(raw.get("description") or ""),
        language=str(raw["language"]),
        languages=_strings(raw.get("languages")) or (str(raw["language"]),),
        direction=direction,
        capabilities=CapabilityManifest(
            booking_tool=bool(caps.get("booking_tool")),
            whatsapp=bool(caps.get("whatsapp")),
            call_backs=bool(caps.get("call_backs")),
            hand_over=bool(caps.get("hand_over")),
            team_alerts=bool(caps.get("team_alerts")),
            direction=direction,
        ),
        main_task=str(raw["main_task"]),
        items=tuple(
            TaskItem(str(item["id"]), str(item["text"]), tuple(_strings(g) for g in item["terms"]))
            for item in raw.get("items", [])
        ),
        noted=tuple(
            Noted(str(n["label"]), str(n.get("reason") or ""), bool(n.get("judged")))
            for n in raw.get("noted", [])
        ),
        known=_strings(raw.get("known")),
        knowledge=tuple((str(k["title"]), str(k["text"])) for k in raw.get("knowledge", [])),
        purpose_terms=_strings(raw.get("purpose_terms")),
        variants=tuple(_strings(g) for g in raw.get("variants", [])),
        screen_terms=_strings(raw.get("screen_terms")),
        purpose=str(raw.get("purpose") or ""),
        goal=str(raw.get("goal") or ""),
        consent_source=raw.get("consent_source"),
    )


@dataclass(frozen=True, slots=True)
class Recorded:
    """One writer output to score. A stand-in's lines are English glosses keyed `en-IN`;
    `stands_for` is the language the real lines were in and `english_words` the words each
    real line wrote in English letters, by path."""

    case_id: str
    source: Source
    script: CallScript
    model: str = ""
    recorded_at: str = ""
    stands_for: str = ""
    english_words: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: str = ""


def recorded_from(raw: dict[str, Any]) -> Recorded:
    stand_in = raw.get("stand_in") or {}
    return Recorded(
        case_id=str(raw["case"]),
        source="live" if raw.get("source") == "live" else "stand-in",
        script=CallScript.model_validate(raw["script"]),
        model=str(raw.get("model") or ""),
        recorded_at=str(raw.get("recorded_at") or ""),
        stands_for=str(stand_in.get("for") or ""),
        english_words={
            str(path): _strings(words)
            for path, words in (stand_in.get("english_words") or {}).items()
        },
        notes=str(raw.get("notes") or ""),
    )


def load_cases(only: Sequence[str] = (), root: Path = CASES_DIR) -> list[Case]:
    cases = [
        case_from(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted((root / "cases").glob("*.json"))
    ]
    if only:
        unknown = set(only) - {c.id for c in cases}
        if unknown:
            raise SystemExit(f"no such case: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.id in only]
    return cases


def load_recorded(case: Case, root: Path = CASES_DIR) -> Recorded:
    path = root / "recorded" / f"{case.id}.json"
    return recorded_from(json.loads(path.read_text(encoding="utf-8")))


# --- reading a script -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Line:
    path: str
    text: str
    #: The language the line is in, as a tag; "en" for a step's answer, which is English.
    tag: str
    #: Whether its words can be read in English: an English line, or a stand-in's gloss.
    readable: bool
    stage: int | None = None


def _readable(tag: str, rec: Recorded) -> bool:
    return tag.lower().startswith("en") or bool(rec.stands_for)


def spoken_lines(rec: Recorded, case: Case, *, openings: bool = True) -> list[Line]:
    """Every line the agent says or copies, with its language."""
    script = rec.script
    own = (rec.stands_for and "en-IN") or case.language
    out: list[Line] = []
    if openings:
        for name in ("opening_line", "outbound_opening_line"):
            text = getattr(script, name)
            if text.strip():
                out.append(Line(name, text, own, _readable(own, rec)))
    for i, stage in enumerate(script.stages):
        if stage.sounds_like.strip():
            out.append(
                Line(f"stages.{i}.sounds_like", stage.sounds_like, own, _readable(own, rec), i)
            )
        for tag, text in stage.scripts.items():
            out.append(Line(f"stages.{i}.scripts.{tag}", text, tag, _readable(tag, rec), i))
        for j, step in enumerate(stage.procedure):
            out.append(
                Line(f"stages.{i}.procedure.{j}.action", step.action, own, _readable(own, rec), i)
            )
        for j, qa in enumerate(stage.qa):
            out.append(Line(f"stages.{i}.qa.{j}.answer", qa.answer, "en", True, i))
            for tag, said in qa.translations.items():
                if said.answer.strip():
                    out.append(
                        Line(
                            f"stages.{i}.qa.{j}.translations.{tag}.answer",
                            said.answer,
                            tag,
                            _readable(tag, rec),
                            i,
                        )
                    )
    return out


def _stage_text(stage: ConversationStage, rec: Recorded) -> str:
    """A step's own text in English: its name, instruction, small steps, notes and the lines
    that can be read in English."""
    lines = [text for tag, text in stage.scripts.items() if _readable(tag, rec)]
    return " ".join(
        [
            stage.name,
            stage.instruction,
            *(p.action for p in stage.procedure),
            *stage.collect,
            *lines,
        ]
    )


_WORD: Final = re.compile(r"[A-Za-z]+")
#: Words of a label that say nothing about which detail it is.
_GENERIC: Final = frozenset(
    {"the", "and", "for", "any", "your", "their", "caller", "customer", "person", "lead",
     "details", "detail", "other", "what", "which"}
)  # fmt: skip


def _stems(text: str) -> set[str]:
    return {
        w.casefold()[:4]
        for w in _WORD.findall(text)
        if len(w) >= 3 and w.casefold() not in _GENERIC
    }


def mentions(text: str, label: str) -> bool:
    """Whether `text` names the detail `label`: every distinctive word of it, by its first
    four letters ("Technical comfort level" in "their technical comfort levels")."""
    wanted = _stems(label)
    return bool(wanted) and wanted <= _stems(text)


def _has_term(text: str, term: str) -> bool:
    """`term` as a word or the start of one ("install" in "installing"), any case."""
    return re.search(rf"\b{re.escape(term.casefold())}", text.casefold()) is not None


# --- the structural checks ------------------------------------------------------------------

Check = Callable[[Recorded, Case], list[str]]

#: What an instruction says to have the agent ASK. "Note" is left out (noting a judgement is
#: the agent's own reading) and so is "confirm" (reading back a value the list gives is right).
_ASK_VERB: Final = re.compile(
    r"\b(?:ask|asks|asking|collect|collects|get|gets|find out|request)\b",
    re.IGNORECASE,
)


def _asks_for(instruction: str, label: str) -> bool:
    """Whether one sentence of `instruction` both names `label` and says to ask it."""
    return any(
        mentions(sentence, label) and _ASK_VERB.search(sentence)
        for sentence in re.split(r"(?<=[.;!?])\s+", instruction)
    )


def judged_field_asked(rec: Recorded, case: Case) -> list[str]:
    """A detail the case marks as judged whose label `whole_call_detail` does not read ("Lead
    quality"), which a step collects, tells the agent to ask, or a line asks. The details it
    does read are the lint's (`script_lint.judged_field_asked_problems` through
    `LintContext.judged`), as production reads them."""
    found: list[str] = []
    judged = [n for n in case.noted if n.is_judged() and not whole_call_detail("", n.label)]
    for i, stage in enumerate(rec.script.stages):
        for n in judged:
            if any(mentions(entry, n.label) for entry in stage.collect):
                found.append(
                    f'stages.{i}.collect: collects "{n.label}", which is judged, not asked.'
                )
            if _asks_for(stage.instruction, n.label):
                found.append(
                    f'stages.{i}.instruction: has the agent ask "{n.label}", which is judged '
                    "from the call."
                )
    for line in spoken_lines(rec, case):
        if not line.readable or "?" not in line.text:
            continue
        for n in judged:
            if mentions(line.text, n.label):
                found.append(f'{line.path}: asks "{n.label}", which is judged from the call.')
    return found


_ASKS_NAME_IN_INSTRUCTION: Final = re.compile(
    r"\b(?:ask|asks|collect|collects|get|request)\b[^.]{0,80}\bname\b",
    re.IGNORECASE,
)


def known_value_asked(rec: Recorded, case: Case) -> list[str]:
    """A value the calling list already gives (the person's name) that a step asks again:
    the founder's call of 25 Nov 2026 stopped mid-step to ask an existing customer's name."""
    found: list[str] = []
    for label in case.known:
        is_name = "name" in label.casefold()
        for i, stage in enumerate(rec.script.stages):
            if any(mentions(entry, label) for entry in stage.collect):
                found.append(f'stages.{i}.collect: collects "{label}", which the list gives.')
            asks = (
                _ASKS_NAME_IN_INSTRUCTION.search(stage.instruction)
                if is_name
                else _asks_for(stage.instruction, label)
            )
            if asks:
                found.append(f'stages.{i}.instruction: asks "{label}", which the list gives.')
        for line in spoken_lines(rec, case, openings=False):
            heard = substitute_variables(line.text, {})
            asked = turn_checks.asks_name(heard) if is_name else False
            if not asked and line.readable and "?" in line.text:
                asked = mentions(heard, label) and "your" in heard.casefold()
            if asked:
                found.append(f'{line.path}: asks "{label}", which the list gives.')
    return found


def no_purpose_line(rec: Recorded, case: Case) -> list[str]:
    """A placed call whose opening never says why it calls (`script_lint.PLACED_OPENING_BRIEF`:
    "say who is calling and why"), read for the case's purpose words. A first step that
    names the purpose is already giving the first task, so only the openings count. In a
    Telugu or Hindi opening a purpose word is found only where it is kept in English letters."""
    if not case.places_calls() or not case.purpose_terms:
        return []
    said = f"{rec.script.opening_line} {rec.script.outbound_opening_line}"
    if any(_has_term(said, term) for term in case.purpose_terms):
        return []
    return ["opening_line: the opening never says why we are calling."]


def covers(text: str, item: TaskItem) -> bool:
    return all(any(_has_term(text, term) for term in group) for group in item.terms)


def main_task_uncovered(rec: Recorded, case: Case) -> list[str]:
    """A thing the main task asks that no step does, each item read against one step's
    English text (`_stage_text`), or the opening's where it can be read in English: an
    instruction is always English, so this reads a Telugu script's steps as well as an
    English one's."""
    texts = [_stage_text(stage, rec) for stage in rec.script.stages]
    texts += [line.text for line in spoken_lines(rec, case) if line.stage is None and line.readable]
    return [
        f'main_task.{item.id}: no step covers "{item.text}".'
        for item in case.items
        if not any(covers(text, item) for text in texts)
    ]


def _language(tag: str) -> str:
    return tag.split("-")[0].lower()


def spoken_meanings(tag: str) -> frozenset[str]:
    """The English meanings for which the language's register data gives a common spoken
    word (`spoken_style.language_pack(...).say_spoken`): an English word in a line where the
    language has an everyday word of its own. The pack's `say_english` words ("details",
    "price") are what callers say in English and are never among them."""
    pack = language_pack(tag)
    if pack is None:
        return frozenset()
    english = {w.casefold() for w in pack.say_english}
    return frozenset(
        meaning.casefold()
        for _said, meaning in pack.say_spoken
        if meaning.strip() and meaning.casefold() not in english
    )


def register_in_line(rec: Recorded, case: Case) -> list[str]:
    """What a Telugu or Hindi line says that callers do not: a word said again in brackets
    (24 Nov call: a button name in Telugu letters, then in English in brackets), a textbook
    word of the language's spoken-style list (`spoken_guard.textbook_problem`), and an
    English word for which the register data gives a common spoken word (`spoken_meanings`).
    Telugu-English code-mixing is ordinary speech (`docs/evidence/voice-agent-research-
    2026-11-25.md` A4: the highest code-mixing index of the Indian pairs measured), so no
    other English word counts. Hindi writes every word in its own letters (D-861), so there
    any English-letter word but a name counts.

    A stand-in's gloss holds no Indian-language word: its English words are the ones the
    record names, and a textbook word cannot be read in it."""
    names = [n for n in (case.business_name, case.agent_name) if n.strip()]
    found: list[str] = []
    for line in spoken_lines(rec, case):
        tag = rec.stands_for or line.tag
        indic = has_indic_letters(line.text)
        if _language(tag) == "en" or not (rec.stands_for or indic):
            continue
        bracket = script_lint.BRACKETED.search(line.text)
        if bracket is not None:
            found.append(f'{line.path}: says "{bracket.group(0)}" again in brackets.')
        textbook = textbook_problem(line.path, line.text, tag) if indic else None
        if textbook:
            found.append(textbook)
        if rec.stands_for:
            words = list(rec.english_words.get(line.path, ()))
        else:
            heard = substitute_variables(line.text, {})
            for name in names:
                heard = re.sub(re.escape(name), " ", heard, flags=re.IGNORECASE)
            words = list(dict.fromkeys(_WORD.findall(heard)))
        own_letters = _language(tag) in OWN_LETTER_LANGUAGES
        if not own_letters:
            meanings = spoken_meanings(tag)
            words = [w for w in words if w.casefold() in meanings]
        if words:
            quoted = ", ".join(f'"{w}"' for w in words)
            why = (
                "in English letters, where the line writes every word in its own"
                if own_letters
                else "in English, where callers say the word of their own"
            )
            found.append(f"{line.path}: says {quoted} {why}.")
    return found


def outcome_tailored(rec: Recorded, case: Case) -> list[str]:
    """A step outcome written for one scenario: it names one of a group of alternatives
    ("Android") and not the rest, or a word only one of the step's scenarios has."""
    script = rec.script
    found: list[str] = []
    for k, outcome in enumerate(script.step_outcomes):
        text = outcome.outcome
        named = next(
            (
                [t for t in group if _has_term(text, t)]
                for group in case.variants
                if 0 < sum(_has_term(text, t) for t in group) < len(group)
            ),
            None,
        )
        siblings = [s for s in script.stages if s.step == outcome.step]
        only = []
        if len(siblings) > 1:
            words = [{w.casefold() for w in _WORD.findall(s.name) if len(w) >= 4} for s in siblings]
            for own in words:
                rest = set().union(*(w for w in words if w is not own))
                only += [w for w in own - rest - _GENERIC if _has_term(text, w)]
        if named or only:
            said = ", ".join(f'"{w}"' for w in dict.fromkeys([*(named or []), *only]))
            found.append(
                f"step_outcomes.{k}: names {said}, so it fits one scenario of step {outcome.step}."
            )
    return found


#: Each structural check: the eval's own function, or None where the writer's lint
#: `script_lint.<name>_problems` makes it, and whether it applies to a case.
CHECKS: Final[dict[str, tuple[Check | None, Callable[[Case], bool]]]] = {
    "judged_field_asked": (judged_field_asked, lambda c: any(n.is_judged() for n in c.noted)),
    "known_value_asked": (known_value_asked, lambda c: bool(c.known)),
    "multi_question_line": (None, lambda c: True),
    "multi_action_line": (None, lambda c: True),
    "fake_branch": (None, lambda c: True),
    "steps_after_close": (None, lambda c: True),
    "no_purpose_line": (no_purpose_line, lambda c: c.places_calls() and bool(c.purpose_terms)),
    "main_task_uncovered": (main_task_uncovered, lambda c: bool(c.items)),
    "register_in_line": (
        register_in_line,
        lambda c: any(_language(t) != "en" for t in c.languages),
    ),
    "agent_claims_caller_action": (None, lambda c: True),
    "outcome_tailored": (outcome_tailored, lambda c: True),
}

#: Checks the writer's lint of the same name makes only in part, because the lint reads the
#: script alone and the writer is measured against what the case knows. The lint's findings
#: stand and the eval's own are added at the places the lint did not name (`structural`), so
#: the problem keeps one count. Each value is what the eval reads that the lint cannot.
EXTENDS: Final[dict[str, str]] = {
    # The lint reads the job's details whose label `whole_call_detail` judges, as production
    # passes them; a case may mark a judgement whose label does not say so (`Noted.judged`).
    "judged_field_asked": "the details the case marks as judged whose label does not say so",
    # The lint fires only on the name, and only when the opening greets by `{{lead_name}}`;
    # what else the calling list gives (a vehicle number, an order) only the case says.
    "known_value_asked": "every value the case's calling list gives, the name in any wording",
}

#: What each check can read in a Telugu or Hindi script (instructions are always English; a
#: stand-in's glosses read as English).
READS: Final[dict[str, str]] = {
    "judged_field_asked": "instructions and collect lists; lines in English only",
    "known_value_asked": "instructions; the name in any language (`turn_checks.asks_name`)",
    "multi_question_line": "question marks in any language; listed asks in English",
    "multi_action_line": "English lines only",
    "fake_branch": "structure",
    "steps_after_close": "structure; the close by its role (a way on to the end, or an "
    'instruction that closes the call), else by its name, "Finalise the call"',
    "no_purpose_line": "openings; purpose words kept in English letters",
    "main_task_uncovered": "instructions, step names and English lines",
    "register_in_line": "Telugu and Hindi lines, by the register data",
    "agent_claims_caller_action": "English lines only",
    "outcome_tailored": "step outcomes, by their English words",
}


def _upstream(name: str) -> Callable[..., list[str]] | None:
    """`script_lint.<name>_problems` when the writer's checks have one for this check, taking
    the script (and the lint context)."""
    fn = getattr(script_lint, f"{name}_problems", None)
    if not callable(fn):
        return None
    params = list(inspect.signature(fn).parameters)
    return fn if params in (["script"], ["script", "context"]) else None


def _where(finding: str) -> str:
    return finding.partition(": ")[0]


def structural(rec: Recorded, case: Case) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Each applicable check's findings, and where each came from: "eval", the lint, or the
    lint with the eval's additions (`EXTENDS`). A lint present always makes its check, so the
    eval and the writer never disagree on a problem both read."""
    found: dict[str, list[str]] = {}
    origin: dict[str, str] = {}
    for name, (check, applies) in CHECKS.items():
        if not applies(case):
            continue
        theirs = _upstream(name)
        if theirs is None:
            if check is None:
                raise RuntimeError(f"script_lint.{name}_problems is gone and {name} has no check")
            found[name], origin[name] = check(rec, case), "eval"
            continue
        args = (
            [rec.script]
            if len(inspect.signature(theirs).parameters) == 1
            else [rec.script, _context(rec, case)]
        )
        found[name], origin[name] = list(theirs(*args)), f"script_lint.{name}_problems"
        if check is not None and name in EXTENDS:
            named = {_where(f) for f in found[name]}
            found[name] += [f for f in check(rec, case) if _where(f) not in named]
            origin[name] += " + eval"
    return found, origin


# --- the repo's lints ----------------------------------------------------------------------


def _context(rec: Recorded, case: Case) -> LintContext:
    # A stand-in's glosses are English: read as Telugu, every line would be "wrong language".
    return case.lint_context(language="en-IN" if rec.stands_for else None)


def one_argument_lints() -> dict[str, Callable[[CallScript], list[str]]]:
    """Every `script_lint.*_problems` that takes the script alone, by name: those
    `flow_problems` gathers and any added later."""
    out: dict[str, Callable[[CallScript], list[str]]] = {}
    for name, fn in inspect.getmembers(script_lint, inspect.isfunction):
        if (
            name.endswith("_problems")
            and fn.__module__ == script_lint.__name__
            and list(inspect.signature(fn).parameters) == ["script"]
        ):
            out[name] = fn
    return dict(sorted(out.items()))


def lints(rec: Recorded, case: Case) -> dict[str, list[str]]:
    """Every existing lint's findings on the script, by lint, but those a structural check
    scores under its own name (`structural`)."""
    script, context = rec.script, _context(rec, case)
    found = {"script_problems": script_lint.script_problems(script, context)}
    for name, fn in one_argument_lints().items():
        if name.removesuffix("_problems") not in CHECKS:
            found[name] = list(fn(script))
    for kind in sorted(mistake_lints.SCRIPT_FIXABLE_KINDS):
        found[f"mistake.{kind}"] = mistake_lints.mistake_findings(script, context, kind)
    found["heal_findings"] = heal_findings(script, context)
    return found


# --- scoring --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    title: str
    source: Source
    structural: dict[str, list[str]]
    origin: dict[str, str]
    lints: dict[str, list[str]]

    def counts(self) -> dict[str, int]:
        return {
            **{f"check.{k}": len(v) for k, v in self.structural.items()},
            **{f"lint.{k}": len(v) for k, v in self.lints.items()},
        }

    def score(self) -> float:
        """The mean of the structural and the lint pass rates (checks with no finding over
        checks applied). Two halves rather than one pool, because the lints are three dozen
        functions, many gathering others' findings, and pooled they would drown the eleven
        structural checks."""
        return (_rate(self.structural.values()) + _rate(self.lints.values())) / 2


def _rate(groups: Iterable[list[str]]) -> float:
    found = list(groups)
    return 100.0 * sum(1 for g in found if not g) / len(found) if found else 100.0


def score(rec: Recorded, case: Case) -> CaseResult:
    found, origin = structural(rec, case)
    return CaseResult(case.id, case.title, rec.source, found, origin, lints(rec, case))


def summary(results: Sequence[CaseResult]) -> dict[str, Any]:
    structural = _rate(v for r in results for v in r.structural.values())
    linted = _rate(v for r in results for v in r.lints.values())
    return {
        "cases": len(results),
        "score": round((structural + linted) / 2, 1),
        "structural_score": round(structural, 1),
        "lint_score": round(linted, 1),
        "structural_findings": sum(len(v) for r in results for v in r.structural.values()),
        "lint_findings": sum(len(v) for r in results for v in r.lints.values()),
    }


# --- the baseline ratchet --------------------------------------------------------------------


def baseline_of(results: Sequence[CaseResult]) -> dict[str, Any]:
    return {
        "_doc": (
            "Finding counts per recorded case and check that tests/eval_script_writer_test.py "
            "holds the recorded outputs to. Either direction of change fails until this file "
            "is rewritten with `python -m scripts.eval_script_writer --write-baseline`: a "
            "count that went up is a regression to fix, one that went down is progress to "
            "lock in."
        ),
        "counts": {r.case_id: r.counts() for r in results},
    }


def baseline_drift(results: Sequence[CaseResult], baseline: dict[str, Any]) -> list[str]:
    """Each (case, check) whose count is not the baseline's, as a sentence."""
    held = baseline.get("counts", {})
    drift: list[str] = []
    for r in results:
        was = held.get(r.case_id)
        if was is None:
            drift.append(f"{r.case_id}: not in the baseline")
            continue
        now = r.counts()
        for key in sorted(set(was) | set(now)):
            before, after = was.get(key), now.get(key)
            if before != after:
                kind = "REGRESSION" if (after or 0) > (before or 0) else "improvement"
                drift.append(f"{r.case_id} {key}: {before} -> {after} ({kind})")
    return drift


# --- the report ----------------------------------------------------------------------------


def report_markdown(
    results: Sequence[CaseResult],
    *,
    mode: str,
    when: str,
    judged: Sequence[JudgeResult] = (),
    paired: Sequence[PairResult] = (),
) -> str:
    s = summary(results)
    lines = [
        f"# Script writer evaluation, {when} ({mode})",
        "",
        "Made by `python -m scripts.eval_script_writer`. Deterministic checks first; the "
        "rubric judge, when run, is reported apart and never gates CI.",
        "",
        "## Summary",
        "",
        f"- Cases: {s['cases']}",
        f"- Deterministic score (mean of the two pass rates below): **{s['score']}%**",
        f"- Structural checks passed: {s['structural_score']}% "
        f"({s['structural_findings']} findings)",
        f"- Lints passed: {s['lint_score']}% ({s['lint_findings']} findings)",
        "- Register data `register_in_line` reads: the spoken-style word lists in force in this "
        "process (the founder's published layer where it is installed, the file otherwise)",
        "",
        "## Per case",
        "",
        "| Case | Source | Score | Structural findings | Lint findings |",
        "|---|---|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.case_id} | {r.source} | {r.score():.1f}% | "
            f"{sum(len(v) for v in r.structural.values())} | "
            f"{sum(len(v) for v in r.lints.values())} |"
        )
    checks = sorted({k for r in results for k in r.structural})
    lines += [
        "",
        "## Per structural check",
        "",
        "| Check | Made by | Cases with findings | Findings | Reads |",
        "|---|---|---:|---:|---|",
    ]
    for name in checks:
        hits = [len(r.structural.get(name, [])) for r in results if name in r.structural]
        made_by = next(r.origin[name] for r in results if name in r.origin)
        lines.append(
            f"| {name} | {made_by} | {sum(1 for h in hits if h)}/{len(hits)} | {sum(hits)} | "
            f"{READS.get(name, '')} |"
        )
    extended = [name for name in checks if name in EXTENDS]
    if extended:
        lines += ["", "Where the eval adds to a lint, what it reads that the lint cannot:", ""]
        lines += [f"- `{name}`: {EXTENDS[name]}." for name in extended]
    lint_names = sorted({k for r in results for k in r.lints})
    lines += ["", "## Per lint", "", "| Lint | Cases with findings | Findings |", "|---|---:|---:|"]
    for name in lint_names:
        hits = [len(r.lints.get(name, [])) for r in results]
        if sum(hits):
            lines.append(f"| {name} | {sum(1 for h in hits if h)}/{len(hits)} | {sum(hits)} |")
    lines.append("")
    lines.append(
        "Lints with no finding on any case are left out of the table, and so are the "
        "`<check>_problems` lints a structural check scores."
    )
    lines += ["", "## Findings by case"]
    for r in results:
        lines += ["", f"### {r.case_id}: {r.title}", ""]
        for name, found in r.structural.items():
            for finding in found:
                lines.append(f"- `{name}` {finding}")
        for name, found in r.lints.items():
            for finding in found:
                lines.append(f"- `lint.{name}` {finding}")
        if not any(r.structural.values()) and not any(r.lints.values()):
            lines.append("- No finding.")
    if judged:
        lines += [
            "",
            "## Rubric judge (separate; never gates CI)",
            "",
            "Scores 1 to 5; each rests on the quoted line it cites.",
            "",
            "| Case | " + " | ".join(RUBRIC) + " |",
            "|---|" + "---:|" * len(RUBRIC),
        ]
        for j in judged:
            if j.error:
                lines.append(f"| {j.case_id} | " + " | ".join("-" for _ in RUBRIC) + " |")
            else:
                lines.append(
                    f"| {j.case_id} | " + " | ".join(str(j.scores[k].score) for k in RUBRIC) + " |"
                )
        for j in judged:
            lines += ["", f"### Judge on {j.case_id}", ""]
            if j.error:
                lines.append(f"- Not judged: {j.error}")
                continue
            for key in RUBRIC:
                g = j.scores[key]
                cited = "; ".join(f'`{c.path}` "{c.quote}"' for c in g.cites)
                lines.append(f"- **{key}** {g.score}: {g.reason} ({cited})")
    if paired:
        lines += [
            "",
            "## Naturalness, new against old (separate; never gates CI)",
            "",
            "Each case asked twice, once in each order; a verdict the order changed is a "
            "split, for the founder's ear.",
            "",
            "| Case | Winner | First order, second order |",
            "|---|---|---|",
        ]
        for p in paired:
            said = ", ".join(p.verdicts) or p.error
            lines.append(f"| {p.case_id} | {p.winner or '-'} | {said} |")
    if judged or paired:
        lines += ["", *JUDGE_CAVEATS]
    lines += ["", *SECTION_D_MAP]
    return "\n".join(lines) + "\n"


#: What the judge does not control, printed with every judged report.
JUDGE_CAVEATS: Final = (
    "Judge bias controls: evidence is quoted before each score and every quote is checked "
    "against its line; comparisons run in both orders; length is penalised in the rubric. Not "
    "controlled: the judge is Gemini, the writer's own family (self-enhancement, "
    "arXiv:2306.05685), and its agreement with founder-labelled calls has not been measured, "
    "so these scores are UNCALIBRATED.",
)

#: Where each deterministic check of the research's scorecard
#: (`docs/evidence/voice-agent-research-2026-11-25.md` D) is made here.
SECTION_D_MAP: Final = (
    "## The research scorecard's deterministic checks (section D)",
    "",
    "| Section D check | Made by |",
    "|---|---|",
    "| More than one question or caller action in a turn | `multi_question_line`, "
    "`multi_action_line` (`script_lint`) |",
    "| Consecutive turns opening with the same acknowledgement | `lint.same_opener_problems`, "
    "`lint.mistake.same_opening` |",
    "| An exact repeat of an agent sentence | `lint.repeated_line_problems` |",
    "| A known field asked for | `known_value_asked` |",
    "| A step marked done with no caller words meeting its done signal | a call's transcript, "
    "not a script: out of scope here |",
    "| A branch condition equal to a step title | `fake_branch` (`script_lint`) |",
    "| A bracketed duplicate name | `register_in_line`, `lint.bracket_problems` |",
)


def report_json(
    results: Sequence[CaseResult],
    judged: Sequence[JudgeResult] = (),
    paired: Sequence[PairResult] = (),
) -> dict[str, Any]:
    return {
        "summary": summary(results),
        "cases": [
            {
                "case": r.case_id,
                "source": r.source,
                "score": round(r.score(), 1),
                "structural": r.structural,
                "origin": r.origin,
                "lints": r.lints,
            }
            for r in results
        ],
        "judge": [j.as_json() for j in judged],
        "pairs": [
            {"case": p.case_id, "winner": p.winner, "verdicts": list(p.verdicts), "error": p.error}
            for p in paired
        ],
    }


# --- the rubric judge -----------------------------------------------------------------------

#: Naturalness only. Everything a check can decide (one thing a turn, the start, the main
#: task's coverage, a known value asked) is the deterministic layer's, as the research's
#: scorecard (`docs/evidence/voice-agent-research-2026-11-25.md` D) puts the judge after the
#: checks and only on what they cannot read. Length is penalised in the words of each
#: criterion because judges reward verbosity (Zheng et al., arXiv:2306.05685).
RUBRIC: Final[dict[str, str]] = {
    "natural_spoken_flow": "Each line sounds like a person on a phone call: whole spoken "
    "sentences, the way the call goes from one line to the next, never a form or a manual. "
    "A longer line is worse, not better.",
    "everyday_register": "The words are the ones callers use in this language, mixing in "
    "English where people do, never bookish or newsreader words. Extra words score lower.",
}

#: Evidence before the score, for each criterion on its own (G-Eval, arXiv:2303.16634; Wang
#: et al., arXiv:2305.17926).
JUDGE_INSTRUCTION: Final = (
    "You review a phone-call script an AI wrote for a business's voice agent, for how natural "
    "it sounds when spoken. For each criterion of the rubric, first quote the lines your "
    "score rests on (their path exactly as given in brackets, and words copied exactly from "
    "that line), then give the score from 1 (fails) to 5 (fully meets) and one sentence of "
    'reason. Answer JSON only: {"scores": [{"criterion": <name>, "cites": [{"path": <path>, '
    '"quote": <words>}], "score": <1-5>, "reason": <one sentence>}]}.\n'
    "RUBRIC:\n" + "\n".join(f"- {k}: {v}" for k, v in RUBRIC.items())
)

PAIR_INSTRUCTION: Final = (
    "You compare two phone-call scripts written for the same business's voice agent, for how "
    "natural they sound when spoken: "
    + " ".join(RUBRIC.values())
    + " First quote the lines that decide it from each script (their path exactly as given "
    "in brackets, and words copied exactly), then say which is more natural. Answer JSON "
    'only: {"cites": [{"path": <path>, "quote": <words>}], "better": "first" | "second" | '
    '"tie", "reason": <one sentence>}.'
)


@dataclass(frozen=True, slots=True)
class Cite:
    path: str
    quote: str


@dataclass(frozen=True, slots=True)
class Graded:
    score: int
    reason: str
    cites: tuple[Cite, ...]


@dataclass(frozen=True, slots=True)
class JudgeResult:
    case_id: str
    scores: dict[str, Graded] = field(default_factory=dict)
    error: str = ""
    tokens: int = 0

    def as_json(self) -> dict[str, Any]:
        return {
            "case": self.case_id,
            "error": self.error,
            "tokens": self.tokens,
            "scores": {
                k: {
                    "score": g.score,
                    "reason": g.reason,
                    "cites": [{"path": c.path, "quote": c.quote} for c in g.cites],
                }
                for k, g in self.scores.items()
            },
        }


def judge_parts(rec: Recorded, case: Case) -> dict[str, str]:
    """The lines the judge reads, by path: every spoken line and each step's instruction."""
    parts = {line.path: line.text for line in spoken_lines(rec, case)}
    for i, stage in enumerate(rec.script.stages):
        parts[f"stages.{i}.instruction"] = f"{stage.name}: {stage.instruction}"
    return parts


def judge_request(rec: Recorded, case: Case) -> str:
    knowledge = "\n".join(f"- {t}: {x}" for t, x in case.knowledge)
    calls = "places calls" if case.places_calls() else "answers calls"
    lines = [
        f"BUSINESS: {case.business_name} ({case.business_type}); the agent {calls}.",
        f"MAIN TASK:\n{case.main_task}",
        f"KNOWLEDGE:\n{knowledge or '- none'}",
        "THE SCRIPT'S LINES:",
        *(f"[{path}] {text}" for path, text in judge_parts(rec, case).items()),
    ]
    return "\n".join(lines)


def parsed_judgement(raw: dict[str, Any], parts: dict[str, str]) -> dict[str, Graded]:
    """The judge's JSON, every criterion scored 1 to 5 and citing a line that holds its quote
    word for word (`campaign_script_ask.quoted_in`). What is wrong is sent back for one more
    try (`script_assist.UnusableAnswerError`); a citation is the code's to verify, never the
    judge's word."""
    from apps.workers.campaign_script_ask import quoted_in
    from apps.workers.script_assist import UnusableAnswerError

    rows = raw.get("scores")
    if not isinstance(rows, list):
        raise UnusableAnswerError("scores: give a list of criteria")
    graded: dict[str, Graded] = {}
    problems: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("criterion") not in RUBRIC:
            continue
        key = str(row["criterion"])
        score = row.get("score")
        if not isinstance(score, int) or not 1 <= score <= 5:
            problems.append(f"{key}: score must be a whole number from 1 to 5")
            continue
        cites = tuple(
            Cite(str(c.get("path")), str(c.get("quote")))
            for c in row.get("cites") or []
            if isinstance(c, dict)
        )
        good = tuple(c for c in cites if c.path in parts and quoted_in(c.quote, parts[c.path]))
        if not good:
            problems.append(f"{key}: cite a line by its path with a quote copied from it")
            continue
        graded[key] = Graded(score, " ".join(str(row.get("reason") or "").split())[:300], good)
    problems += [
        f"{key}: not scored"
        for key in RUBRIC
        if key not in graded and not any(p.startswith(f"{key}:") for p in problems)
    ]
    if problems:
        raise UnusableAnswerError("; ".join(problems))
    return graded


async def judge(rec: Recorded, case: Case) -> JudgeResult:
    """The rubric judge on our Gemini leg (`assist_leg.google_assist_leg`), with one repair
    round for a citation that does not hold. Its failure is reported, never raised."""
    from functools import partial

    from apps.api.agents.assist_leg import google_assist_leg
    from apps.api.core.errors import ProblemError
    from apps.workers.script_assist import ask_json

    parts = judge_parts(rec, case)
    try:
        answer = await ask_json(
            judge_request(rec, case),
            JUDGE_INSTRUCTION,
            parse=partial(parsed_judgement, parts=parts),
            tenant_leg=google_assist_leg(),
            gemini_only=True,
            temperature=0.0,
            max_tokens=4_000,
            timeout_s=60.0,
            repair_rounds=1,
        )
    except ProblemError as refused:
        return JudgeResult(case.id, error=refused.code)
    usage = answer.usage
    tokens = usage.prompt_tokens + usage.output_tokens if usage else 0
    return JudgeResult(case.id, answer.value, tokens=tokens)


@dataclass(frozen=True, slots=True)
class PairResult:
    """Two scripts of one case compared in both orders. `winner` is "new", "old" or "tie"
    when both orders agree, and "split" when swapping the order changed the verdict: a case
    for the founder's ear, never averaged into a winner."""

    case_id: str
    winner: str = ""
    verdicts: tuple[str, ...] = ()
    error: str = ""
    tokens: int = 0


def pair_parts(first: Recorded, second: Recorded, case: Case) -> dict[str, str]:
    return {
        **{f"first.{p}": t for p, t in judge_parts(first, case).items()},
        **{f"second.{p}": t for p, t in judge_parts(second, case).items()},
    }


def parsed_pair(raw: dict[str, Any], parts: dict[str, str]) -> str:
    """ "first", "second" or "tie", once the answer cites a quoted line of each script."""
    from apps.workers.campaign_script_ask import quoted_in
    from apps.workers.script_assist import UnusableAnswerError

    cites = [c for c in raw.get("cites") or [] if isinstance(c, dict)]
    held = {
        str(c.get("path")).partition(".")[0]
        for c in cites
        if str(c.get("path")) in parts and quoted_in(str(c.get("quote")), parts[str(c["path"])])
    }
    problems = [
        f"cites: quote a line of the {side} script by its path"
        for side in ("first", "second")
        if side not in held
    ]
    better = raw.get("better")
    if better not in ("first", "second", "tie"):
        problems.append('better: say "first", "second" or "tie"')
    if problems:
        raise UnusableAnswerError("; ".join(problems))
    return str(better)


def settle_pair(new_first: str, old_first: str) -> str:
    """The verdict of both orders: the first run had the new script first, the second had the
    old one first (Wang et al., arXiv:2305.17926: swapping the order can flip a verdict)."""
    one = {"first": "new", "second": "old", "tie": "tie"}[new_first]
    two = {"first": "old", "second": "new", "tie": "tie"}[old_first]
    return one if one == two else "split"


async def judge_pair(new: Recorded, old: Recorded, case: Case) -> PairResult:
    """`new` against `old` for naturalness, asked once in each order on our Gemini leg."""
    from functools import partial

    from apps.api.agents.assist_leg import google_assist_leg
    from apps.api.core.errors import ProblemError
    from apps.workers.script_assist import ask_json

    verdicts: list[str] = []
    tokens = 0
    for first, second in ((new, old), (old, new)):
        parts = pair_parts(first, second, case)
        request = "\n".join(
            [
                f"BUSINESS: {case.business_name} ({case.business_type}).",
                f"MAIN TASK:\n{case.main_task}",
                "THE TWO SCRIPTS' LINES:",
                *(f"[{path}] {text}" for path, text in parts.items()),
            ]
        )
        try:
            answer = await ask_json(
                request,
                PAIR_INSTRUCTION,
                parse=partial(parsed_pair, parts=parts),
                tenant_leg=google_assist_leg(),
                gemini_only=True,
                temperature=0.0,
                max_tokens=2_000,
                timeout_s=60.0,
                repair_rounds=1,
            )
        except ProblemError as refused:
            return PairResult(case.id, error=refused.code, tokens=tokens)
        verdicts.append(answer.value)
        if answer.usage:
            tokens += answer.usage.prompt_tokens + answer.usage.output_tokens
    return PairResult(case.id, settle_pair(*verdicts), tuple(verdicts), tokens=tokens)


# --- the live writer ------------------------------------------------------------------------


@dataclass
class Spend:
    tokens: int = 0
    models: set[str] = field(default_factory=set)

    def add(self, usage: Any, model: str | None) -> None:
        if usage is not None:
            self.tokens += int(usage.prompt_tokens) + int(usage.output_tokens)
        if model:
            self.models.add(model)


async def write_live(case: Case, spend: Spend) -> CallScript:
    """`case`'s first script as `campaign_script._write` writes one: the draft from the
    trade's plan with the holder's words as the description, the one refining edit with the
    same ask, then `script_structure.settled`. On our Gemini leg, no account."""
    from apps.api.agents.assist_leg import google_assist_leg
    from apps.api.agents.script_structure import settled
    from apps.api.core.settings import get_settings
    from apps.api.first_run.models import KNOWLEDGE_DOCUMENT_CHARS
    from apps.workers.campaign_script_ask import (
        CAMPAIGN_ASK,
        LINE_ASK,
        campaign_change,
        owners_words,
        situation_block,
    )
    from apps.workers.first_run import documents_block
    from apps.workers.script_assist import ScriptBrief, draft_script
    from apps.workers.script_proposal import PROPOSAL_MAX_TOKENS, PROPOSAL_REQUEST_TIMEOUT_S

    ask = CAMPAIGN_ASK if case.places_calls() else LINE_ASK
    documents = documents_block(list(case.knowledge), budget=KNOWLEDGE_DOCUMENT_CHARS)
    situation = situation_block(
        agent_name=case.agent_name,
        holder_name=case.title,
        purpose=case.purpose,
        goal=case.goal,
        consent_source=case.consent_source,
        inbound=not case.places_calls(),
    )
    change = campaign_change(
        case.main_task, "", documents, edit=False, ask=ask, situation=situation
    )
    owners = owners_words(case.main_task, "")
    brief = ScriptBrief(
        description=case.description,
        business_name=case.business_name,
        agent_name=case.agent_name,
        business_type=case.business_type,
        direction="outbound" if case.places_calls() else case.direction,
        language=case.language,
        collect=case.collect(),
        knowledge_titles=tuple(title for title, _t in case.knowledge),
        capabilities=case.capabilities,
        facts=tuple(text for _t, text in case.knowledge),
        grounding=change,
        placed_calls=case.places_calls(),
    )
    leg = google_assist_leg()
    rounds = get_settings().campaign_script_repair_rounds
    # The first draft reads the holder's words as the owner's description; the refining
    # edit reads the business's own, as `_write` and `_refined` do.
    draft = await draft_script(
        replace(brief, description=change),
        tenant_leg=leg,
        timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
        max_tokens=PROPOSAL_MAX_TOKENS,
        repair_rounds=rounds,
        standby_after_answer=False,
        owners_words=owners,
    )
    spend.add(draft.usage, draft.model)
    refine = campaign_change(
        case.main_task, "", documents, edit=True, refine=True, ask=ask, situation=situation
    )
    refined = await draft_script(
        brief,
        tenant_leg=leg,
        edit_of=draft.script,
        change=refine,
        timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
        max_tokens=PROPOSAL_MAX_TOKENS,
        repair_rounds=rounds,
        standby_after_answer=False,
        owners_words=owners,
    )
    spend.add(refined.usage, refined.model)
    return settled(refined.script, case.lint_context())


def recorded_json(rec: Recorded) -> dict[str, Any]:
    out: dict[str, Any] = {
        "case": rec.case_id,
        "source": rec.source,
        "model": rec.model,
        "recorded_at": rec.recorded_at,
        "notes": rec.notes,
        "script": rec.script.model_dump(mode="json", exclude_defaults=True),
    }
    if rec.stands_for:
        out["stand_in"] = {
            "for": rec.stands_for,
            "english_words": {k: list(v) for k, v in rec.english_words.items()},
        }
    return out


# --- the command ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_script_writer")
    parser.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    parser.add_argument(
        "--cases-dir", type=Path, default=CASES_DIR, help="the case set (the image has no tests/)"
    )
    parser.add_argument("--live", action="store_true", help="write each script with the model")
    parser.add_argument("--spend", action="store_true", help="allow --live/--judge to spend")
    parser.add_argument("--judge", action="store_true", help="run the rubric judge (model)")
    parser.add_argument(
        "--judge-against",
        default="",
        help='compare each script for naturalness, both orders, with "recorded" or a '
        "--format json run's outputs (model)",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--write-report", action="store_true", help=f"write under {REPORT_DIR}")
    parser.add_argument("--write-baseline", action="store_true", help="rewrite baseline.json")
    parser.add_argument("--import-live", type=Path, help="a --live --format json run to record")
    return parser


def import_live(path: Path, root: Path = CASES_DIR) -> list[str]:
    """Each live output of a `--live --format json` run written as the recorded output of its
    case, replacing the stand-in. Returns the case ids written."""
    bundle = json.loads(path.read_text(encoding="utf-8"))
    written: list[str] = []
    for raw in bundle.get("outputs", []):
        rec = recorded_from(raw)
        target = root / "recorded" / f"{rec.case_id}.json"
        target.write_text(
            json.dumps(recorded_json(rec), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written.append(rec.case_id)
    return written


async def _live_outputs(cases: Iterable[Case]) -> tuple[list[Recorded], Spend, list[str]]:
    from apps.api.core.errors import ProblemError
    from apps.api.core.platform_config import refresh as refresh_platform_config

    await refresh_platform_config(force=True)
    spend = Spend()
    out: list[Recorded] = []
    failed: list[str] = []
    when = datetime.now(IST).isoformat(timespec="seconds")
    for case in cases:
        try:
            script = await write_live(case, spend)
        except ProblemError as refused:
            failed.append(f"{case.id}: {refused.code}")
            continue
        out.append(
            Recorded(
                case.id, "live", script, model=",".join(sorted(spend.models)), recorded_at=when
            )
        )
    return out, spend, failed


def earlier_outputs(source: str, cases: Iterable[Case], root: Path) -> dict[str, Recorded]:
    """The scripts to compare against, by case: the recorded set, or a run's outputs."""
    if source == "recorded":
        return {case.id: load_recorded(case, root=root) for case in cases}
    bundle = json.loads(Path(source).read_text(encoding="utf-8"))
    return {rec.case_id: rec for rec in map(recorded_from, bundle.get("outputs", []))}


async def _main(args: argparse.Namespace) -> int:
    if args.import_live:
        for case_id in import_live(args.import_live):
            print(f"recorded {case_id}")
        return 0
    if (args.live or args.judge or args.judge_against) and not args.spend:
        print(
            "--live, --judge and --judge-against call the model on our key; add --spend.",
            file=sys.stderr,
        )
        return 2
    cases = load_cases([c for c in args.cases.split(",") if c], root=args.cases_dir)
    failed: list[str] = []
    spend = Spend()
    if args.live:
        outputs, spend, failed = await _live_outputs(cases)
        by_id = {c.id: c for c in cases}
        pairs = [(rec, by_id[rec.case_id]) for rec in outputs]
    else:
        pairs = [(load_recorded(case, root=args.cases_dir), case) for case in cases]
    results = [score(rec, case) for rec, case in pairs]
    judged = [await judge(rec, case) for rec, case in pairs] if args.judge else []
    paired: list[PairResult] = []
    if args.judge_against:
        old = earlier_outputs(args.judge_against, cases, args.cases_dir)
        paired = [
            await judge_pair(rec, old[case.id], case) for rec, case in pairs if case.id in old
        ]
    spend.tokens += sum(j.tokens for j in judged) + sum(p.tokens for p in paired)
    mode = "live" if args.live else "recorded"
    when = datetime.now(IST).date().isoformat()
    text = report_markdown(results, mode=mode, when=when, judged=judged, paired=paired)
    if args.format == "json":
        bundle = {
            "mode": mode,
            "when": when,
            "tokens": spend.tokens,
            "models": sorted(spend.models),
            "failed": failed,
            "report": report_json(results, judged, paired),
            "markdown": text,
            "outputs": [recorded_json(rec) for rec, _c in pairs] if args.live else [],
        }
        print(json.dumps(bundle, indent=2, ensure_ascii=False))
    else:
        print(text)
        if args.live or args.judge:
            print(f"Tokens used: {spend.tokens}; failed: {', '.join(failed) or 'none'}")
    if args.write_report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"{when}-{mode}.md").write_text(text, encoding="utf-8")
    if args.write_baseline:
        if args.live or args.cases:
            print(
                "--write-baseline scores every recorded case; drop --live and --cases.",
                file=sys.stderr,
            )
            return 2
        BASELINE.write_text(json.dumps(baseline_of(results), indent=2) + "\n", encoding="utf-8")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
