"""Score Pip's script writer on a fixed set of holders, so a writer change is measured before
it ships rather than judged by the founder's next test call.

    uv run python -m scripts.eval_script_writer                    # recorded outputs, no model
    uv run python -m scripts.eval_script_writer --cases rytu_khata_install,clinic_reminder
    uv run python -m scripts.eval_script_writer --write-report     # under docs/evidence/
    uv run python -m scripts.eval_script_writer --write-baseline   # lock in the counts CI holds
    uv run python -m scripts.eval_script_writer --import-live run.json   # live outputs -> recorded
    uv run python -m scripts.eval_script_writer --cases first_run_rytu,first_run_clinic_inbound

THE FIRST RUN, END TO END (W3.3): `first_run/<id>/` holds a raw brief, how its owner answers
and the run's two model outputs; brief -> questions -> answers -> script is scored by
`score_first_run`, and the command exits 1 unless every case passes. These cases are kept
out of the script case set and its baseline; `tests/call_sim_test.py` holds them.

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
   here), each `script_checks` mistake kind and `script_heal.heal_findings`. They are the product's
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

`--live` runs the one writer as a campaign's or line's first script is written
(`workers/script_writer.write_script`, `whole`): the plan by code, each step by its own
request, checked and rewritten alone, the opening by the opening writer. The context is built
from the case (`case_context`), not read from an account. It spends on our key, so it refuses
without `--spend` and prints the tokens used; nothing is metered to an account.
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

from apps.api.agents import script_checks, script_lint, turn_checks
from apps.api.agents.owner_plan import owner_plan, plan_problems
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
    #: The owner's request for this draft (`campaign_script._Inputs.instruction`), which may
    #: lay out the steps itself (`owner_plan`).
    instruction: str = ""

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
                self.instruction,
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
        instruction=str(raw.get("instruction") or ""),
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


def owner_plan_kept(rec: Recorded, case: Case) -> list[str]:
    """Each place the script departs from the steps the owner's request lays out: the writer's
    own check (`owner_plan.plan_problems`), so the eval and the writer never disagree."""
    return plan_problems(rec.script, owner_plan(case.instruction))


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
    "owner_plan_kept": (owner_plan_kept, lambda c: owner_plan(c.instruction) is not None),
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
    "owner_plan_kept": "step names, step numbers, outcomes and ways out (structure)",
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
    for kind in sorted(script_checks.SCRIPT_FIXABLE_KINDS):
        found[f"mistake.{kind}"] = script_checks.mistake_findings(script, context, kind)
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


def case_context(case: Case) -> Any:
    """`case` as the one writer's context (`workers/script_context.ScriptContext`), as the
    loader reads a holder: its brief, main task, request, sources, settings and details."""
    from uuid import uuid4

    from apps.api.agents.script_builder import JobDetails
    from apps.workers.campaign_script_ask import situation_block
    from apps.workers.script_assist import ScriptBrief
    from apps.workers.script_context import ScriptContext
    from calevate_shared.call_script import CollectField

    asked = tuple(
        CollectField(label=n.label, reason=n.reason)
        for n in case.noted
        if not whole_call_detail("", n.label)
    )
    return ScriptContext(
        tenant_id=uuid4(),
        kind="campaign" if case.places_calls() else "line",
        holder_id=uuid4(),
        agent_id=uuid4(),
        brief=ScriptBrief(
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
        ),
        main_task=case.main_task,
        saved=None,
        asked_from=None,
        words=tuple(case.knowledge),
        situation=situation_block(
            agent_name=case.agent_name,
            holder_name=case.title,
            purpose=case.purpose,
            goal=case.goal,
            consent_source=case.consent_source,
            inbound=not case.places_calls(),
        ),
        details=JobDetails(
            asked=asked,
            judged=tuple(n.label for n in case.noted if n.is_judged()),
        ),
        instruction=case.instruction,
        extra_languages=tuple(tag for tag in case.languages if tag != case.language),
    )


async def write_live(case: Case, spend: Spend) -> CallScript:
    """`case`'s first script as the holder writer writes one: `write_script` in `whole` mode,
    the plan by code and each step by its own request. On our Gemini leg, no account."""
    from apps.api.agents.assist_leg import google_assist_leg
    from apps.workers.script_writer import WriteRequest, write_script

    context = replace(case_context(case), tenant_leg=google_assist_leg())
    result = await write_script(WriteRequest("whole", context))
    for spent in result.spends:
        if not isinstance(spent, Exception):
            spend.add(spent.usage, spent.model)
    return result.script


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


# --- the first run, end to end (W3.3) --------------------------------------------------------
#
# "Meet your agent" turns an owner's brief into follow-up questions, answers, a first work and
# its script. A case under `first_run/<id>/` is that brief verbatim (`brief.txt`), how the owner
# answers (`case.json`) and the two model outputs, the questions and the script
# (`recorded.json`, or `--live`). Everything between the two model calls is the product's own
# code run on the case: the question gate (`first_run/questions.written_questions`), the main
# task, calling window and pinned facts the first run stores (`first_run/work.main_task_of`,
# `calling_hours_of`, `owner_statements`). What a reader expects the brief to yield (its tasks,
# facts, rules, numbers and window) is written in the case by a person, never derived by the
# code under test.

FIRST_RUN_DIR: Final = "first_run"
FirstRunJob = Literal["call_leads", "answer_calls"]


@dataclass(frozen=True, slots=True)
class Answer:
    """How the owner answers a follow-up question: the first answer whose `match` finds the
    question's prompt is used, ticking each offered option that holds one of `ticks` and
    typing `text`. A question no answer matches is skipped, as an owner may."""

    match: str
    ticks: tuple[str, ...] = ()
    text: str = ""


@dataclass(frozen=True, slots=True)
class FirstRunCase:
    id: str
    brief: str
    job: FirstRunJob
    #: Nobody comes to the business and it goes to nobody (an app): no area or address asked.
    remote: bool
    has_premises: bool | None
    goes_ahead: bool | None
    tasks: tuple[TaskItem, ...]
    #: What a reader finds the brief (and the answers) state, each to be pinned word for word.
    facts: tuple[str, ...]
    rules: tuple[str, ...]
    #: Numbers the owner gave that every call must carry (a fee, an urgent number).
    numbers: tuple[str, ...]
    calling_window: dict[str, str] | None
    answers: tuple[Answer, ...]
    one_thing: str
    #: The script case's own fields (`case_from`), its main task filled in by the first run.
    script_case: dict[str, Any]

    def places_calls(self) -> bool:
        return self.job == "call_leads"


def first_run_case_from(directory: Path) -> FirstRunCase:
    raw = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    window = raw.get("calling_window")
    return FirstRunCase(
        id=str(raw["id"]),
        brief=(directory / "brief.txt").read_text(encoding="utf-8").strip(),
        job="answer_calls" if raw["job"] == "answer_calls" else "call_leads",
        remote=bool(raw.get("remote")),
        has_premises=raw.get("has_premises"),
        goes_ahead=raw.get("goes_ahead"),
        tasks=tuple(
            TaskItem(str(item["id"]), str(item["text"]), tuple(_strings(g) for g in item["terms"]))
            for item in raw.get("tasks", [])
        ),
        facts=_strings(raw.get("facts")),
        rules=_strings(raw.get("rules")),
        numbers=_strings(raw.get("numbers")),
        calling_window=(
            {"start": str(window["start"]), "end": str(window["end"])}
            if isinstance(window, dict)
            else None
        ),
        answers=tuple(
            Answer(str(a["match"]), _strings(a.get("ticks")), str(a.get("text") or ""))
            for a in raw.get("answers", [])
        ),
        one_thing=str(raw.get("one_thing") or ""),
        script_case=dict(raw["script_case"]),
    )


def first_run_ids(root: Path = CASES_DIR) -> list[str]:
    folder = root / FIRST_RUN_DIR
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if (p / "case.json").exists())


def load_first_run_cases(only: Sequence[str] = (), root: Path = CASES_DIR) -> list[FirstRunCase]:
    ids = first_run_ids(root)
    unknown = set(only) - set(ids)
    if unknown:
        raise SystemExit(f"no such first-run case: {', '.join(sorted(unknown))}")
    return [first_run_case_from(root / FIRST_RUN_DIR / i) for i in ids if not only or i in only]


@dataclass(frozen=True, slots=True)
class FirstRunRecorded:
    """The two model outputs of one first run: the questions as the model wrote them (before
    the gate) and the script."""

    case_id: str
    source: Source
    questions: tuple[dict[str, Any], ...]
    script: CallScript
    model: str = ""
    recorded_at: str = ""
    notes: str = ""


def first_run_recorded_from(raw: dict[str, Any]) -> FirstRunRecorded:
    return FirstRunRecorded(
        case_id=str(raw["case"]),
        source="live" if raw.get("source") == "live" else "stand-in",
        questions=tuple(q for q in raw.get("questions") or () if isinstance(q, dict)),
        script=CallScript.model_validate(raw["script"]),
        model=str(raw.get("model") or ""),
        recorded_at=str(raw.get("recorded_at") or ""),
        notes=str(raw.get("notes") or ""),
    )


def first_run_recorded_json(rec: FirstRunRecorded) -> dict[str, Any]:
    return {
        "case": rec.case_id,
        "source": rec.source,
        "model": rec.model,
        "recorded_at": rec.recorded_at,
        "notes": rec.notes,
        "questions": list(rec.questions),
        "script": rec.script.model_dump(mode="json", exclude_defaults=True),
    }


def load_first_run_recorded(case: FirstRunCase, root: Path = CASES_DIR) -> FirstRunRecorded:
    path = root / FIRST_RUN_DIR / case.id / "recorded.json"
    return first_run_recorded_from(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True, slots=True)
class FirstRunMade:
    """What the first run makes of the brief between the two model calls, by its own code."""

    questions: tuple[Any, ...]
    #: Each answer as `first_runs.answers` stores it.
    answers: tuple[dict[str, Any], ...]
    main_task: str
    calling_hours: dict[str, str] | None
    #: The pinned facts (question, text) the first run stores before the script is written.
    pinned: tuple[tuple[str, str], ...]


def _answered(question: Any, case: FirstRunCase) -> dict[str, Any] | None:
    from apps.api.first_run.questions import CHOICE_KINDS, ONE_THING

    stored = {"id": question.id, "prompt": question.prompt, "maps_to": question.maps_to}
    if question.id == ONE_THING.id:
        return {**stored, "text": case.one_thing} if case.one_thing else None
    found = next(
        (a for a in case.answers if re.search(a.match, question.prompt, re.IGNORECASE)), None
    )
    if found is None:
        return None
    if question.kind in CHOICE_KINDS:
        ticked = [
            option
            for option in question.options
            if any(t.casefold() in option.casefold() for t in found.ticks)
        ]
        return {**stored, "choices": ticked} if ticked else None
    return {**stored, "text": found.text} if found.text else None


def first_run_made(case: FirstRunCase, raw_questions: Sequence[dict[str, Any]]) -> FirstRunMade:
    """The questions the gate keeps, the owner's answers to them, and the main task, calling
    window and pinned facts the first run stores from the brief and those answers."""
    from types import SimpleNamespace
    from uuid import uuid4

    from apps.api.first_run.questions import (
        QuestionWords,
        given_in,
        with_one_thing,
        written_questions,
    )
    from apps.api.first_run.work import calling_hours_of, main_task_of, owner_statements
    from apps.api.tenancy.business_profile import Profile

    given = given_in(case.brief)
    words = QuestionWords(has_premises=case.has_premises, goes_ahead=case.goes_ahead)
    kept = written_questions(list(raw_questions), Profile(tenant_id=uuid4()), words, given)
    # The run asks the one thing every caller should know when the brief states no fact
    # (`write_first_run_questions`, `ask_one_thing=not given.facts`).
    asked = kept if given.facts else with_one_thing(kept)
    answers = tuple(a for a in (_answered(q, case) for q in asked) if a is not None)
    row = SimpleNamespace(brief=case.brief, answers=list(answers))
    return FirstRunMade(
        questions=tuple(asked),
        answers=answers,
        main_task=main_task_of(row, case.job),
        calling_hours=calling_hours_of(row),
        pinned=tuple(owner_statements(row)),
    )


def first_run_script_case(case: FirstRunCase, made: FirstRunMade) -> Case:
    """The script case the first run's work is: the case's own fields, the main task the first
    run made, and the pinned facts among its knowledge, as every call of the account reads
    them."""
    raw = dict(case.script_case)
    raw.setdefault("id", case.id)
    raw.setdefault("holder", "campaign" if case.places_calls() else "line")
    raw.setdefault("direction", "outbound" if case.places_calls() else "inbound")
    raw["main_task"] = made.main_task
    raw["knowledge"] = [
        *raw.get("knowledge", []),
        *({"title": q or "The owner said", "text": t} for q, t in made.pinned),
    ]
    return case_from(raw)


def _pinned_text(made: FirstRunMade) -> str:
    return " ".join(t for _q, t in made.pinned).casefold()


def _fr_opening(case: FirstRunCase, script: CallScript, base: Case) -> list[str]:
    from apps.api.agents.call_rules import placed_opening_problems

    if case.places_calls():
        line = script.outbound_opening_line or script.opening_line
        if not line.strip():
            return ["opening: the campaign has no opening line"]
        return placed_opening_problems(
            "opening", line, agent_name=base.agent_name, business_name=base.business_name
        )
    return [] if script.opening_line.strip() else ["opening: the line has no greeting"]


def _fr_tasks(case: FirstRunCase, rec: Recorded) -> list[str]:
    """Each owner task in exactly one step, and no step doing two (the founder's "one step
    per task")."""
    found: list[str] = []
    texts = [_stage_text(stage, rec) for stage in rec.script.stages]
    by_stage: dict[int, list[str]] = {}
    for task in case.tasks:
        steps = [n for n, text in enumerate(texts) if covers(text, task)]
        if not steps:
            found.append(f"tasks.{task.id}: no step does '{task.text}'")
        elif len(steps) > 1:
            found.append(f"tasks.{task.id}: '{task.text}' is in steps {steps}")
        for n in steps:
            by_stage.setdefault(n, []).append(task.id)
    found += [
        f"stages.{n}: does {len(ids)} owner tasks ({', '.join(ids)})"
        for n, ids in sorted(by_stage.items())
        if len(ids) > 1
    ]
    return found


def _fr_said(made: FirstRunMade, wanted: Sequence[str], kind: str) -> list[str]:
    pinned = _pinned_text(made)
    return [f"{kind}: '{w}' is not pinned" for w in wanted if w.casefold() not in pinned]


def _fr_numbers(case: FirstRunCase, made: FirstRunMade, script: CallScript) -> list[str]:
    """Each number the owner gave reaches the call: pinned, or in the script itself."""
    from calevate_shared.call_script import compile_call_script

    carried = f"{_pinned_text(made)} {compile_call_script(script)}"
    return [f"numbers: {n} reaches no call" for n in case.numbers if n not in carried]


def _fr_window(case: FirstRunCase, made: FirstRunMade) -> list[str]:
    if not case.places_calls() or made.calling_hours == case.calling_window:
        return []
    return [
        f"calling_window: the campaign calls {made.calling_hours}, the owner said "
        f"{case.calling_window}"
    ]


def _fr_questions(case: FirstRunCase, made: FirstRunMade) -> list[str]:
    """A kept question about where the business is or the areas it serves, for a business
    nobody comes to; or one asking what the brief already says."""
    from apps.api.first_run.questions import (
        _ASKS_SERVICE_AREA,  # the gate's own reading of an areas-served question
        QuestionWords,
        _asks_given,
        given_in,
    )

    given = given_in(case.brief)
    words = QuestionWords(has_premises=case.has_premises, goes_ahead=case.goes_ahead)
    found: list[str] = []
    for q in made.questions:
        if case.remote and (q.maps_to == "location" or _ASKS_SERVICE_AREA.search(q.prompt)):
            found.append(f"questions.{q.id}: asks where a business nobody comes to is or serves")
        if _asks_given(q, given, words):
            found.append(f"questions.{q.id}: asks what the brief already says")
    return found


#: The first-run checks, in the order the owner meets what they check.
FIRST_RUN_CHECKS: Final = (
    "questions",
    "opening",
    "tasks",
    "facts",
    "rules",
    "numbers",
    "calling_window",
)


@dataclass(frozen=True, slots=True)
class FirstRunResult:
    case_id: str
    source: Source
    findings: dict[str, list[str]]
    #: The script scored as every case is (structural checks and lints), reported only.
    script: CaseResult
    questions_written: int
    questions_kept: int
    pinned: int
    #: What the report says beside the checks: how the code read the brief.
    notes: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(self.findings.values())


def score_first_run(case: FirstRunCase, rec: FirstRunRecorded) -> FirstRunResult:
    from apps.api.agents.owner_words import owner_tasks

    made = first_run_made(case, rec.questions)
    read = owner_tasks(case.brief)
    # A note, not a check: `owner_tasks` reads only a list of things the person does, so the
    # work of an answering line ("tell them our timings, book appointments") reads as none
    # and reaches the writer as the brief's own words.
    notes = (
        ()
        if len(read) == len(case.tasks)
        else (
            f"The code reads {len(read)} task(s) from the brief where the case lists "
            f"{len(case.tasks)}; the plan is then the writer's reading of the brief.",
        )
    )
    base = first_run_script_case(case, made)
    as_recorded = Recorded(case.id, rec.source, rec.script, model=rec.model)
    findings = {
        "questions": _fr_questions(case, made),
        "opening": _fr_opening(case, rec.script, base),
        "tasks": _fr_tasks(case, as_recorded),
        "facts": _fr_said(made, case.facts, "facts"),
        "rules": _fr_said(made, case.rules, "rules"),
        "numbers": _fr_numbers(case, made, rec.script),
        "calling_window": _fr_window(case, made),
    }
    return FirstRunResult(
        case_id=case.id,
        source=rec.source,
        findings=findings,
        script=score(as_recorded, base),
        questions_written=len(rec.questions),
        questions_kept=len(made.questions),
        pinned=len(made.pinned),
        notes=notes,
    )


def first_run_report(results: Sequence[FirstRunResult], *, mode: str, when: str) -> str:
    """The first-run checks per case, then the script's own counts; findings name paths and
    case ids, never a model's line."""
    lines = [f"# First-run eval ({mode}, {when})", ""]
    for r in results:
        verdict = "PASS" if r.passed else "FAIL"
        lines += [
            f"## {r.case_id}: {verdict} ({r.source})",
            "",
            f"- Questions: {r.questions_written} written, {r.questions_kept} asked after the "
            f"gate; {r.pinned} pinned facts stored.",
            f"- Script score {r.script.score():.1f} (structural and lint pass rates; reported, "
            "not gated).",
            "",
            "| Check | Findings |",
            "|---|---|",
        ]
        for check in FIRST_RUN_CHECKS:
            found = r.findings.get(check, [])
            lines.append(f"| {check} | {'; '.join(found) if found else '-'} |")
        lines += ["", *(f"- Note: {n}" for n in r.notes), ""] if r.notes else [""]
    return "\n".join(lines)


async def first_run_live(case: FirstRunCase, spend: Spend) -> FirstRunRecorded:
    """Both model calls of the first run on our Gemini leg: the follow-up questions as
    `workers/first_run.write_first_run_questions` asks them (its instruction, the brief, the
    agent's job and what is already given), then the work's script by the one writer."""
    from uuid import uuid4

    from apps.api.agents.assist_leg import google_assist_leg
    from apps.api.first_run.questions import QuestionWords, closed_topics, given_in
    from apps.api.tenancy.business_profile import Profile
    from apps.workers import first_run as fr
    from apps.workers.script_assist import ask_json
    from apps.workers.script_writer import WriteRequest, write_script

    given = given_in(case.brief)
    words = QuestionWords(has_premises=case.has_premises, goes_ahead=case.goes_ahead)
    known = ", ".join(sorted(closed_topics(Profile(tenant_id=uuid4()), words))) or "none"
    # The worker's own request, assembled the same way (`write_first_run_questions`).
    request = (
        f"The owner's description:\n{case.brief}\n\n"
        f"What the agent does: {fr._JOB_CONTEXT[case.job]}"
        f"\nBusiness profile sections already known: {known}"
        + (f"\nAlready given, so never asked: {given.said()}" if given.said() else "")
    )
    leg = google_assist_leg()

    def raw_questions(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
        written = raw.get("questions")
        return [q for q in written if isinstance(q, dict)] if isinstance(written, list) else None

    answer = await ask_json(
        request,
        fr.QUESTIONS_INSTRUCTION,
        parse=raw_questions,
        tenant_leg=leg,
        max_tokens=900,
        temperature=0.3,
        gemini_only=True,
    )
    spend.add(answer.usage, answer.model)
    made = first_run_made(case, answer.value)
    context = replace(case_context(first_run_script_case(case, made)), tenant_leg=leg)
    result = await write_script(WriteRequest("whole", context))
    for spent in result.spends:
        if not isinstance(spent, Exception):
            spend.add(spent.usage, spent.model)
    return FirstRunRecorded(
        case.id,
        "live",
        tuple(answer.value),
        result.script,
        model=",".join(sorted(spend.models)),
        recorded_at=datetime.now(IST).isoformat(timespec="seconds"),
    )


async def run_first_run(args: argparse.Namespace, ids: Sequence[str]) -> int:
    cases = load_first_run_cases(ids, root=args.cases_dir)
    spend = Spend()
    failed: list[str] = []
    pairs: list[tuple[FirstRunCase, FirstRunRecorded]] = []
    if args.live:
        from apps.api.core.errors import ProblemError
        from apps.api.core.platform_config import refresh as refresh_platform_config

        await refresh_platform_config(force=True)
        for case in cases:
            try:
                pairs.append((case, await first_run_live(case, spend)))
            except ProblemError as refused:
                failed.append(f"{case.id}: {refused.code}")
    else:
        pairs = [(case, load_first_run_recorded(case, root=args.cases_dir)) for case in cases]
    results = [score_first_run(case, rec) for case, rec in pairs]
    mode = "live" if args.live else "recorded"
    when = datetime.now(IST).date().isoformat()
    text = first_run_report(results, mode=mode, when=when)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "mode": mode,
                    "when": when,
                    "tokens": spend.tokens,
                    "models": sorted(spend.models),
                    "failed": failed,
                    "passed": {r.case_id: r.passed for r in results},
                    "findings": {r.case_id: r.findings for r in results},
                    "markdown": text,
                    "first_run_outputs": [first_run_recorded_json(rec) for _c, rec in pairs]
                    if args.live
                    else [],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(text)
        if args.live:
            print(f"Tokens used: {spend.tokens}; failed: {', '.join(failed) or 'none'}")
    if args.write_report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"{when}-first-run-{mode}.md").write_text(text, encoding="utf-8")
    return 0 if results and all(r.passed for r in results) and not failed else 1


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
    parser.add_argument(
        "--first-run",
        action="store_true",
        help="score the first-run cases end to end (brief, questions, script); naming only "
        "first-run ids in --cases does the same",
    )
    return parser


def import_live(path: Path, root: Path = CASES_DIR) -> list[str]:
    """Each live output of a `--live --format json` run written as the recorded output of its
    case, replacing the stand-in. Returns the case ids written."""
    bundle = json.loads(path.read_text(encoding="utf-8"))
    written: list[str] = []
    for raw in bundle.get("first_run_outputs", []):
        first = first_run_recorded_from(raw)
        target = root / FIRST_RUN_DIR / first.case_id / "recorded.json"
        target.write_text(
            json.dumps(first_run_recorded_json(first), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(first.case_id)
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
    named = [c for c in args.cases.split(",") if c]
    first_runs = set(first_run_ids(args.cases_dir))
    if args.first_run or (named and set(named) <= first_runs):
        return await run_first_run(args, named)
    if set(named) & first_runs:
        print("Name first-run cases apart from the script cases.", file=sys.stderr)
        return 2
    cases = load_cases(named, root=args.cases_dir)
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
