"""Pip writes the outcome of each step that has none, and rewrites its own, for one campaign or
inbound line (D-1036).

Queued by `campaigns/step_outcomes.queue_after_save` and by the hourly sweep below. One answer
on the account's dashboard AI ladder (`script_assist.ask_json`), written from each step's own
name, instruction, lines and procedure, the holder's main task and aims, what is known about
the business (`lead_fields_draft.business_context`) and the sources the holder is written from
(`company_training_draft.knowledge_words`, read as onboarding reads documents:
`first_run.documents_block`). Everything sent is redacted (D-127 G-1).

GROUNDED OR NOT KEPT. Each outcome comes with a word-for-word quote of the material it rests
on, which the CODE must find there (`campaign_script_ask.quoted_in`), and every figure in it
must be one the material has, so an outcome that invents a fact is dropped rather than saved
(company training's rule, `company_training_draft`). An outcome that names a technology
company the material does not is dropped too (D-679: the owner reads it).

TRUE FOR EVERY CALLER. An outcome is what holds when the step is done whichever case the
caller is in (founder, 24 Nov 2026: a step whose one scenario was the Android install got an
Android-only outcome, though iPhone callers pass through it too). The code enforces what it
can see: an outcome that names some but not all of a set of alternatives is refused. The sets
are the capitalised "X or Y" / "X/Y" lists in the main task, the goal and the steps
(`case_sets`), plus the sets the model declares, each option of which must be in the material.
Alternatives written any other way, or in another language, are left to the instruction.

ONE SUBJECT. Every outcome begins with "The <subject>", one word for the person called for the
whole call: the one already recorded for the holder while the material still uses it,
otherwise the model's choice in the same answer, which must be a word the main task, goal or
holder's name uses, or "person". It is recorded with the outcomes (`PipRecord`).

PIP'S OWN, NEVER THE OWNER'S. The pass writes the steps with no outcome and rewrites the ones
still exactly as Pip wrote them under an older `RULES_VERSION`; an outcome the owner typed or
edited is never touched (`campaigns/step_outcomes.pip_steps`). The save is a compare-and-set
on the script as it was read (a line's `version`, a campaign's script itself, which has no
version), under the holder's row lock, so an owner's save made while Pip wrote wins and its
own pass follows.
The save is the holder's own column write, not `save_script`, because that would queue this
pass again; the length check it makes (`script_builder.refuse_job_if_too_long`) is made here.
A live line or a campaign holding its engine agent is then put live, as an owner's save is.

Metered as a script draft (hard rule 7), in the transaction that saves.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import (
    STEP_OUTCOME_MAX,
    CallScript,
    ConversationStage,
    StepOutcome,
    stage_steps,
)
from sqlalchemy import text

from apps.api.agents import agent_pass
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.campaigns.step_outcomes import (
    DEBOUNCE_S,
    DEFAULT_SUBJECT,
    RULES_VERSION,
    SLOTS,
    HolderKind,
    PipRecord,
    missing_steps,
    pip_steps,
    record_json,
    table_of,
)
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.crm import assist as crm_assist
from apps.api.db.session import admin_session, tenant_session
from apps.api.first_run.models import KNOWLEDGE_DOCUMENT_CHARS
from apps.api.tenancy.business_copy import provider_words
from apps.workers.campaign_script_ask import quoted_in
from apps.workers.company_training_draft import figures_in, knowledge_words
from apps.workers.first_run import documents_block
from apps.workers.fleet_walk import WalkBudget, resumed_walk
from apps.workers.lead_fields_draft import business_context
from apps.workers.opening_notices import put_holder_live
from apps.workers.redaction import redact
from apps.workers.script_assist import JsonAnswer, UnusableAnswerError, ask_json
from apps.workers.script_proposal import PROPOSAL_REQUEST_TIMEOUT_S

log = get_logger(__name__)

#: `campaigns/step_outcomes.JOB`; a literal here so `scripts/check_job_wiring` can read this
#: file's own deferred enqueue (`_defer`).
JOB_NAME: Final = "write_step_outcomes"
SWEEP_JOB: Final = "sweep_step_outcomes"
#: Room for twelve one-sentence outcomes and their quotes, with headroom for a repair.
MAX_TOKENS: Final = 4_000
_QUOTE_MAX: Final = 300

#: The sweep's cadence and bounds. Hourly at :47, a minute no other fleet walk takes. Each
#: holder it queues is one model call, so `HOLDERS_PER_TICK` is the most it spends in an hour;
#: the next tick resumes after the last account reached, so a backlog drains in turn.
SWEEP_MINUTE: Final = 47
HOLDERS_PER_TICK: Final = 50
SWEEP_BUDGET: Final = timedelta(seconds=120)
#: A pass that failed is tried again by the sweep after this long; one whose
#: inputs did not change since costs nothing (`_digest`).
RETRY_MINUTES: Final = 6 * 60

#: Changing this is a change of the writer's rules: raise `RULES_VERSION` with it when the
#: outcomes already written should follow.
ASK: Final = (
    "You write the outcome of each step listed under STEPS TO WRITE in a phone agent's call "
    "script. An outcome is one plain English sentence saying what is true once that step is "
    "done, checkable from what the person says on the call (for example: The person says the "
    "app is open on their phone). It must be true for every caller who goes through the step, "
    "whichever case they are in: when the main task, the goal, the steps or the knowledge show "
    "alternatives (devices, plans, branches, languages, yes or no), the outcome covers all of "
    "them or names the result they share, never one case alone. A step's scenarios, their "
    "names and instructions are examples of how the call may reach the outcome, never its "
    "definition: a step with one scenario still has callers in the other cases. The call's "
    "opening (the greeting, who is calling, asking whether now is a good time to talk, the "
    "notices) is said before step 1 and is not a step: no outcome is about it or repeats it. "
    "Under subject put the one word every outcome uses for the person called: the word the "
    "main task, the goal or the name uses for them, in the singular, or person when they use "
    "none; when THE PERSON CALLED gives the word, use it. Begin every outcome with The and that "
    "word. Under alternatives list each set of alternatives a caller may be in, each option "
    "written as the material writes it. Write each outcome from that step's own name, "
    "instruction, lines and procedure, with the main task and the goal; the other steps are "
    "listed so each outcome covers only its own step. Use only what the material states: "
    "never add a price, product, place, time, promise or detail it does not state, and keep "
    "the names of products, screens and buttons exactly as written. For each outcome, put "
    "under quote a short passage copied word for word from the main task, the goal, or that "
    "step's name, instruction or other material, that the outcome rests on. At most 300 "
    "characters per outcome. No markdown, no emoji. Return one entry per listed step."
)

_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "step_outcomes",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "alternatives": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "outcomes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "integer"},
                            "outcome": {"type": "string"},
                            "quote": {"type": "string"},
                        },
                        "required": ["step", "outcome", "quote"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["subject", "alternatives", "outcomes"],
            "additionalProperties": False,
        },
    },
}

#: A word in a list of alternatives; `case_sets` keeps a list only when every option carries a
#: capital (Android, iPhone, WhatsApp, Gold), as names of things do.
_CASE_WORD: Final = r"[^\W\d_][\w-]*"
_LISTED: Final = re.compile(rf"((?:\b{_CASE_WORD},\s+)*)\b({_CASE_WORD}),?\s+or\s+({_CASE_WORD})\b")
_SLASHED: Final = re.compile(rf"\b({_CASE_WORD})/({_CASE_WORD})\b")


@dataclass(frozen=True)
class Holder:
    """One campaign or line as the pass read it."""

    kind: HolderKind
    id: UUID
    script: CallScript
    #: The script column exactly as stored, for the campaign's compare-and-set.
    stored: Any
    #: A line's version, for its compare-and-set; None for a campaign.
    version: int | None
    main_task: str
    aims: str
    source_ids: tuple[UUID, ...]
    #: The campaign's or line's name, which may name the people called.
    name: str = ""
    record: PipRecord = field(default_factory=PipRecord)


@dataclass(frozen=True)
class Written:
    """The outcomes the code accepted, by step, and the subject they share."""

    subject: str
    outcomes: dict[int, str]


@dataclass(frozen=True)
class Request:
    """What one pass sends and checks against, all redacted."""

    text: str
    #: Where an outcome's quote must be found.
    material: str
    #: Where the subject must be found: the main task, the aims and the name.
    naming: str
    #: The sets of alternatives the code found in the call's own words (`case_sets`).
    cases: tuple[frozenset[str], ...]
    targets: tuple[int, ...]
    #: The subject decided before the pass, or None when the answer chooses it.
    subject: str | None


def _clean(value: str) -> str:
    return redact(" ".join(value.split())).text


def step_material(stages: list[ConversationStage]) -> str:
    """One step's scenarios as the model reads them: name, instruction, how it sounds, its
    procedure, its lines, its questions and answers and its ways out."""
    parts: list[str] = []
    for stage in stages:
        parts.append(f"Scenario: {stage.name}")
        parts.append(f"Instruction: {stage.instruction}")
        if stage.sounds_like:
            parts.append(f"How it sounds: {stage.sounds_like}")
        for item in stage.procedure:
            wait = f" (wait for: {item.wait_for})" if item.wait_for else ""
            parts.append(f"Procedure: {item.action}{wait}")
        for language, line in stage.scripts.items():
            parts.append(f"Line ({language}): {line}")
        for qa in stage.qa:
            parts.append(f"If asked: {qa.question} Answer: {qa.answer}")
        for branch in stage.branches:
            parts.append(f"Way out when: {branch.when}")
    return "\n".join(_clean(p) for p in parts if p.strip())


def _by_step(script: CallScript) -> dict[int, list[ConversationStage]]:
    out: dict[int, list[ConversationStage]] = defaultdict(list)
    for stage, step in zip(script.stages, stage_steps(script.stages), strict=True):
        out[step].append(stage)
    return dict(out)


def _is_case(word: str) -> bool:
    return any(ch.isupper() for ch in word)


def case_sets(text: str) -> tuple[frozenset[str], ...]:
    """The alternatives the text lists as "A or B", "A, B or C" or "A/B", where every option
    carries a capital, as names of devices, apps, plans and languages do. Lower-case pairs
    ("remember or not") are left out: read as cases they would refuse ordinary outcomes."""
    found: list[frozenset[str]] = []
    for match in _LISTED.finditer(text):
        before = [w.strip() for w in match.group(1).split(",") if w.strip()]
        while before and not _is_case(before[0]):
            before.pop(0)
        options = [*before, match.group(2), match.group(3)]
        if all(_is_case(w) for w in options):
            found.append(frozenset(options))
    for match in _SLASHED.finditer(text):
        if _is_case(match.group(1)) and _is_case(match.group(2)):
            found.append(frozenset(match.groups()))
    return tuple(dict.fromkeys(s for s in found if len({w.casefold() for w in s}) > 1))


def one_case_of(sentence: str, sets: Iterable[frozenset[str]]) -> tuple[list[str], list[str]]:
    """(the options it names, the ones it leaves out) for the first set `sentence` names only
    part of; two empty lists when it names every option of each set it touches, or none."""
    for options in sets:
        named = sorted(o for o in options if quoted_in(o, sentence))
        if named and len(named) < len(options):
            return named, sorted(set(options) - set(named))
    return [], []


def _bare_subject(word: str) -> str:
    said = " ".join(word.split()).casefold()
    return said[4:] if said.startswith("the ") else said


def subject_holds(subject: str, *, naming: str, cases: Iterable[frozenset[str]]) -> bool:
    """A subject may be `DEFAULT_SUBJECT`, or a word the main task, aims or name use for the
    people called (its plural counts), and never one case of a set of alternatives."""
    bare = _bare_subject(subject)
    if not bare:
        return False
    if bare == DEFAULT_SUBJECT:
        return True
    if not any(quoted_in(form, naming) for form in (bare, f"{bare}s", f"{bare}es")):
        return False
    return not one_case_of(bare, cases)[0]


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _starts_with(sentence: str, subject: str) -> bool:
    return f"{_words(sentence)} ".startswith(f"the {_words(subject)} ")


def targets_of(holder: Holder, cases: tuple[frozenset[str], ...]) -> tuple[list[int], str | None]:
    """(the steps this pass writes, the subject decided before it). The steps are those with
    no outcome and those whose outcome is still Pip's from an older `RULES_VERSION`; while
    the holder has no subject that still holds, Pip's outcomes are all rewritten, so they
    share the one the answer picks."""
    script = holder.script
    subject = holder.record.subject
    naming = _naming(holder)
    fixed = subject if subject and subject_holds(subject, naming=naming, cases=cases) else None
    mine = pip_steps(script, holder.record)
    stale = {n for n, v in mine.items() if v < RULES_VERSION or fixed is None}
    return sorted(set(missing_steps(script)) | stale), fixed


def _naming(holder: Holder) -> str:
    return "\n".join(_clean(p) for p in (holder.main_task, holder.aims, holder.name) if p)


def _call_text(holder: Holder) -> str:
    steps = _by_step(holder.script)
    return "\n".join([_naming(holder), *(step_material(steps[n]) for n in sorted(steps))])


def request_text(holder: Holder, *, business: str, documents: str) -> Request:
    """What this pass asks and what its answer is checked against, all redacted."""
    script = holder.script
    steps = _by_step(script)
    cases = case_sets(_call_text(holder))
    targets, subject = targets_of(holder, cases)
    said = {o.step: o.outcome for o in script.step_outcomes if o.step not in targets}
    flow = [
        f"Step {n}: {', '.join(s.name for s in stages)}"
        + (f" (outcome: {said[n]})" if n in said else "")
        for n, stages in sorted(steps.items())
    ]
    flow_text = "\n".join(_clean(line) for line in flow)
    names = "\n".join(
        _clean(f"Step {n}: " + ", ".join(s.name for s in stages))
        for n, stages in sorted(steps.items())
    )
    blocks = [f"STEP {n}\n{step_material(steps[n])}" for n in targets]
    main = _clean(holder.main_task) or "Not written."
    aims = _clean(holder.aims)
    name = _clean(holder.name)
    person = (
        f'Every outcome begins with "The {subject}".'
        if subject
        else "Choose the subject as the instruction says."
    )
    alternatives = "\n".join(" / ".join(sorted(s, key=str.casefold)) for s in cases)
    text = "\n\n".join(
        part
        for part in [
            f"MAIN TASK\n{main}",
            f"GOAL\n{aims}" if aims else "",
            f"NAME\n{name}" if name else "",
            f"THE BUSINESS\n{business}" if business else "",
            "THE CALL'S STEPS\n" + flow_text,
            "STEPS TO WRITE\n" + "\n\n".join(blocks),
            f"THE PERSON CALLED\n{person}",
            f"ALTERNATIVES THE CALL NAMES\n{alternatives}" if alternatives else "",
            documents,
        ]
        if part
    )
    return Request(
        text=text,
        material="\n\n".join([main, aims, name, names, *blocks, documents]),
        naming=_naming(holder),
        cases=cases,
        targets=tuple(targets),
        subject=subject,
    )


def _declared_sets(raw: dict[str, Any], material: str) -> list[frozenset[str]]:
    """The model's sets of alternatives, each option kept only where the material has it."""
    out: list[frozenset[str]] = []
    rows = raw.get("alternatives")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, list):
            continue
        options = {
            " ".join(o.split())
            for o in row
            if isinstance(o, str) and o.strip() and quoted_in(o, material)
        }
        if len({o.casefold() for o in options}) > 1:
            out.append(frozenset(options))
    return out


def judged(raw: dict[str, Any], request: Request) -> tuple[Written, list[str]]:
    """The outcomes the code can stand behind, and what it refused, as a note the model can
    act on. An outcome is kept for a step this pass writes when it is one sentence of the
    allowed length, begins with "The <subject>", names no single case of a set of
    alternatives, its quote is in the material, and it has no figure and no provider name
    the material lacks."""
    material = request.material
    figures = figures_in(material)
    named = provider_words(material)
    problems: list[str] = []
    subject = request.subject
    if subject is None:
        chosen = raw.get("subject")
        if isinstance(chosen, str) and subject_holds(
            chosen, naming=request.naming, cases=request.cases
        ):
            subject = _bare_subject(chosen)
        else:
            problems.append(
                "subject: use a word the main task, goal or name uses for the people called, "
                f"that is not one case of the alternatives, or {DEFAULT_SUBJECT}"
            )
            subject = DEFAULT_SUBJECT
    sets = [*request.cases, *_declared_sets(raw, material)]
    out: dict[int, str] = {}
    rows = raw.get("outcomes")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        step, outcome, quote = row.get("step"), row.get("outcome"), row.get("quote")
        if not isinstance(step, int) or step not in request.targets or step in out:
            continue
        if not isinstance(outcome, str) or not isinstance(quote, str):
            continue
        sentence = " ".join(outcome.split())
        if not sentence or len(sentence) > STEP_OUTCOME_MAX:
            problems.append(f"step {step}: one sentence of at most {STEP_OUTCOME_MAX} characters")
            continue
        if not _starts_with(sentence, subject):
            problems.append(f'step {step}: begin the outcome with "The {subject}"')
            continue
        only, left = one_case_of(sentence, sets)
        if only:
            problems.append(
                f"step {step}: the outcome names only {', '.join(only)}, but callers may be "
                f"in {', '.join(left)} too; write what is true for every case"
            )
            continue
        if not quoted_in(" ".join(quote.split())[:_QUOTE_MAX], material):
            problems.append(f"step {step}: the quote is not word for word in the material")
            continue
        if not figures_in(sentence) <= figures or not provider_words(sentence) <= named:
            problems.append(f"step {step}: a figure or name the material does not have")
            continue
        out[step] = sentence
    refused = {p.split(":", 1)[0] for p in problems}
    problems += [
        f"step {n}: no outcome"
        for n in request.targets
        if n not in out and f"step {n}" not in refused
    ]
    return Written(subject=subject, outcomes=out), problems


def accepted(raw: dict[str, Any], request: Request) -> Written | None:
    """The lenient read: whatever passed, or None when nothing did."""
    written, _problems = judged(raw, request)
    return written if written.outcomes else None


def strict(raw: dict[str, Any], request: Request) -> Written | None:
    """The first read: every step written, or the problems sent back for one repair."""
    written, problems = judged(raw, request)
    if problems:
        raise UnusableAnswerError("; ".join(problems[:12]))
    return written if written.outcomes else None


def with_outcomes(
    script: CallScript, written: dict[int, str], *, replace: Iterable[int] = ()
) -> CallScript:
    """`script` with each written outcome on its step where the step has none or is in
    `replace` (an outcome of Pip's being rewritten); every other outcome is kept as it is."""
    replaced = set(replace)
    have = {o.step for o in script.step_outcomes}
    put = {n: t for n, t in written.items() if n not in have or n in replaced}
    if not put:
        return script
    kept = [o for o in script.step_outcomes if o.step not in put]
    added = [StepOutcome(step=n, outcome=t) for n, t in put.items()]
    return CallScript.model_validate(
        script.model_copy(
            update={"step_outcomes": sorted([*kept, *added], key=lambda o: o.step)}
        ).model_dump()
    )


def _digest(request: str) -> str:
    return hashlib.sha256(f"rules {RULES_VERSION}\n{request}".encode()).hexdigest()


def _holder_of(payload: dict[str, Any]) -> tuple[HolderKind, UUID]:
    if payload.get("campaign_id"):
        return "campaign", UUID(str(payload["campaign_id"]))
    return "line", UUID(str(payload["line_id"]))


async def _read(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> Holder | None:
    from apps.api.kb.picks import CAMPAIGN_PICKS, LINE_PICKS, read_picks

    async with tenant_session(tenant_id) as session:
        if kind == "campaign":
            row = (
                await session.execute(
                    text(
                        "SELECT script, main_task, purpose, goal, name, step_outcomes_pip "
                        "FROM campaigns "
                        "WHERE id = :h AND archived_at IS NULL"
                    ),
                    {"h": holder_id},
                )
            ).first()
            version = None
        else:
            row = (
                await session.execute(
                    text(
                        "SELECT script, main_task, NULL AS purpose, NULL AS goal, version, name, "
                        "step_outcomes_pip FROM inbound_lines WHERE id = :h AND archived_at IS NULL"
                    ),
                    {"h": holder_id},
                )
            ).first()
            version = None if row is None else int(row.version)
        if row is None or not row.script:
            return None
        picks = await read_picks(
            session, CAMPAIGN_PICKS if kind == "campaign" else LINE_PICKS, [holder_id]
        )
    script = CallScript.model_validate(row.script)
    aims = [str(a) for a in (row.purpose, row.goal, script.goal, script.outbound_purpose) if a]
    return Holder(
        kind=kind,
        id=holder_id,
        script=script,
        stored=row.script,
        version=version,
        main_task=str(row.main_task or ""),
        aims="\n".join(aims),
        source_ids=tuple(picks[holder_id]),
        name=str(row.name or ""),
        record=PipRecord.read(row.step_outcomes_pip),
    )


async def _finish(
    tenant_id: UUID, kind: HolderKind, holder_id: UUID, state: str, digest: str | None = None
) -> None:
    """Close the pass (or start the next one asked for meanwhile), remembering what it read
    when the same read would only fail again, and that it ran under `RULES_VERSION`, so the
    sweep does not ask again until the version moves."""
    async with tenant_session(tenant_id) as session:
        if digest is not None:
            await session.execute(text(_REMEMBER_SQL[kind]), _remember(digest, holder_id))
        await agent_pass.finish(
            session, SLOTS[kind], tenant_id=tenant_id, row_id=holder_id, state=state
        )


#: What a pass that saved nothing remembers: the hash of its read and the rules version it
#: ran under, kept in the record beside the outcomes Pip wrote.
_REMEMBER_SQL: Final[dict[HolderKind, str]] = {
    "campaign": (
        "UPDATE campaigns SET step_outcomes_inputs = :d, step_outcomes_pip = jsonb_set("
        "COALESCE(step_outcomes_pip, '{}'::jsonb), '{rules}', to_jsonb(CAST(:rules AS integer))) "
        "WHERE id = :h"
    ),
    "line": (
        "UPDATE inbound_lines SET step_outcomes_inputs = :d, step_outcomes_pip = jsonb_set("
        "COALESCE(step_outcomes_pip, '{}'::jsonb), '{rules}', to_jsonb(CAST(:rules AS integer))) "
        "WHERE id = :h"
    ),
}


def _remember(digest: str, holder_id: UUID) -> dict[str, object]:
    return {"d": digest, "rules": RULES_VERSION, "h": holder_id}


async def _due(tenant_id: UUID, kind: HolderKind, holder_id: UUID) -> datetime | None:
    """When a waiting pass may start, if that is still ahead: `DEBOUNCE_S` after the last
    save that asked for it."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    f"SELECT step_outcomes_state, step_outcomes_at FROM {table_of(kind)} "
                    "WHERE id = :h"
                ),
                {"h": holder_id},
            )
        ).first()
    if row is None or row[0] != "queued" or row[1] is None:
        return None
    due: datetime = row[1] + timedelta(seconds=DEBOUNCE_S)
    return due if due > datetime.now(UTC) else None


async def _defer(payload: dict[str, Any], holder_id: UUID, due: datetime) -> None:
    """Run again once the burst is over; keyed by the due instant, so each push-back is its
    own delivery and a repeated one is deduped by arq."""
    await enqueue(
        JOB_NAME,
        payload,
        job_id=job_id_for(JOB_NAME, str(holder_id), due.isoformat()),
        _defer_until=due,
    )


async def write_step_outcomes(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    kind, holder_id = _holder_of(payload)
    due = await _due(tenant_id, kind, holder_id)
    if due is not None:
        await _defer(payload, holder_id, due)
        return "deferred"
    async with tenant_session(tenant_id) as session:
        claimed, previous = await agent_pass.claim(session, SLOTS[kind], row_id=holder_id)
    if not claimed:
        return "not_queued"
    try:
        return await _run(tenant_id, kind, holder_id, previous)
    except Exception:
        log.exception("step_outcomes_crashed", extra={"kind": kind, "holder_id": str(holder_id)})
        await _finish(tenant_id, kind, holder_id, "failed")
        return "failed"


async def _run(tenant_id: UUID, kind: HolderKind, holder_id: UUID, previous: str | None) -> str:
    holder = await _read(tenant_id, kind, holder_id)
    targets = targets_of(holder, case_sets(_call_text(holder)))[0] if holder is not None else []
    if holder is None or not targets:
        await _finish(tenant_id, kind, holder_id, "done")
        return "complete"
    async with tenant_session(tenant_id) as session:
        allowed = await account_content_may_reach_models(session, tenant_id=tenant_id)
    if not allowed:
        await _finish(tenant_id, kind, holder_id, "skipped")
        return "skipped"
    async with tenant_session(tenant_id) as session:
        words = await knowledge_words(session, only=holder.source_ids or None)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    business, _vertical = await business_context(tenant_id, include_type=False)
    documents = documents_block(words, budget=KNOWLEDGE_DOCUMENT_CHARS)
    request = request_text(holder, business=business, documents=documents)
    digest = _digest(request.text)
    if previous == digest:
        await _finish(tenant_id, kind, holder_id, "done", digest=digest)
        return "unchanged"

    def parse(raw: dict[str, Any]) -> Written | None:
        return strict(raw, request)

    def salvage(raw: dict[str, Any]) -> Written | None:
        return accepted(raw, request)

    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    try:
        answer: JsonAnswer[Written] = await ask_json(
            request.text,
            ASK,
            parse=parse,
            salvage=salvage,
            azure_format=_FORMAT,
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling or quota.platform_paused,
            max_tokens=MAX_TOKENS,
            temperature=0.2,
            timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        log.info("step_outcomes_refused", extra={"reason": refused.code, "kind": kind})
        # A refusal that can pass (no answer this time) is tried again; one that would only
        # repeat on the same script waits for the script to change.
        await _finish(
            tenant_id,
            kind,
            holder_id,
            "failed",
            digest=None if refused.kind == "transient" else digest,
        )
        return refused.code
    result = await _save(tenant_id, holder, request, answer, digest)
    if result == "saved":
        await put_holder_live(tenant_id, kind, holder_id, event="step_outcomes_not_live")
    log.info(
        "step_outcomes_written",
        extra={
            "kind": kind,
            "holder_id": str(holder_id),
            "targets": len(request.targets),
            "written": len(answer.value.outcomes),
            "result": result,
        },
    )
    return result


async def _save(
    tenant_id: UUID,
    holder: Holder,
    request: Request,
    answer: JsonAnswer[Written],
    digest: str,
) -> str:
    """Meter, then save the outcomes onto the script as it was read, with the record of what
    Pip wrote: `saved`, `stale` (the script changed meanwhile; its own pass follows) or
    `too_long`."""
    from apps.api.agents import script_builder

    kind, table = holder.kind, table_of(holder.kind)
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    written = answer.value
    script = with_outcomes(holder.script, written.outcomes, replace=request.targets)
    record = record_json(script, holder.record, subject=written.subject, written=written.outcomes)
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            model=answer.model,
            feature=feature,
        )
        await session.execute(
            text(f"SELECT 1 FROM {table} WHERE id = :h FOR UPDATE"), {"h": holder.id}
        )
        try:
            async with session.begin_nested():
                await script_builder.refuse_job_if_too_long(
                    session, kind=kind, tenant_id=tenant_id, job_id=holder.id, script=script
                )
        except ProblemError as refused:
            log.info("step_outcomes_too_long", extra={"kind": kind, "reason": refused.code})
            await session.execute(text(_REMEMBER_SQL[kind]), _remember(digest, holder.id))
            await agent_pass.finish(
                session, SLOTS[kind], tenant_id=tenant_id, row_id=holder.id, state="failed"
            )
            return "too_long"
        if kind == "campaign":
            stored = await session.execute(
                text(
                    "UPDATE campaigns SET script = CAST(:s AS jsonb), "
                    "step_outcomes_inputs = :d, step_outcomes_pip = CAST(:pip AS jsonb), "
                    "updated_at = now() "
                    "WHERE id = :h AND script = CAST(:old AS jsonb) RETURNING id"
                ),
                {
                    "s": script.model_dump_json(),
                    "d": digest,
                    "pip": record,
                    "h": holder.id,
                    "old": json.dumps(holder.stored),
                },
            )
        else:
            stored = await session.execute(
                text(
                    "UPDATE inbound_lines SET script = CAST(:s AS jsonb), "
                    "version = version + 1, step_outcomes_inputs = :d, "
                    "step_outcomes_pip = CAST(:pip AS jsonb), updated_at = now() "
                    "WHERE id = :h AND version = :v RETURNING id"
                ),
                {
                    "s": script.model_dump_json(),
                    "d": digest,
                    "pip": record,
                    "h": holder.id,
                    "v": holder.version,
                },
            )
        saved = stored.first() is not None
        await agent_pass.finish(
            session, SLOTS[kind], tenant_id=tenant_id, row_id=holder.id, state="done"
        )
    return "saved" if saved else "stale"


_SCAN_SQL: Final = (
    "SELECT scanned_tenant_id, kind, holder_id FROM step_outcome_scan(:stale, :retry, :rules)"
)


async def sweep_step_outcomes(ctx: dict[str, Any]) -> str:
    """Queue a pass for each open holder lacking an outcome that no pass has covered (scripts
    saved before outcomes were Pip's, a pass that died, accounts that since turned Pip on), and
    for each holding an outcome of Pip's written under an older `RULES_VERSION`.
    One admin read of the worklist (`step_outcome_scan`, a per-tenant loop inside Postgres
    under each tenant's own policy), then one tenant session per account with work, at most
    `HOLDERS_PER_TICK` holders, resuming after the last account reached."""
    del ctx
    async with admin_session() as directory:
        rows = (
            await directory.execute(
                text(_SCAN_SQL),
                {"stale": agent_pass.STALE_MINUTES, "retry": RETRY_MINUTES, "rules": RULES_VERSION},
            )
        ).all()
    holders: dict[UUID, list[tuple[HolderKind, UUID]]] = defaultdict(list)
    for tenant, kind, holder in rows:
        holders[UUID(str(tenant))].append(("campaign" if kind == "campaign" else "line", holder))
    queued = 0
    budget = WalkBudget(SWEEP_BUDGET)
    async for tenant_id in resumed_walk(SWEEP_JOB, list(holders), budget):
        if queued >= HOLDERS_PER_TICK:
            break
        async with tenant_session(tenant_id) as session:
            if not await account_content_may_reach_models(session, tenant_id=tenant_id):
                continue
            for kind, holder_id in holders[tenant_id][: HOLDERS_PER_TICK - queued]:
                queued += await agent_pass.queue(
                    session, SLOTS[kind], tenant_id=tenant_id, row_id=UUID(str(holder_id))
                )
    log.info(
        "step_outcomes_sweep",
        extra={"holders": len(rows), "tenants": len(holders), "queued": queued},
    )
    return f"holders={len(rows)} queued={queued}"


__all__ = [
    "HOLDERS_PER_TICK",
    "JOB_NAME",
    "SWEEP_JOB",
    "SWEEP_MINUTE",
    "Holder",
    "Request",
    "Written",
    "accepted",
    "case_sets",
    "judged",
    "one_case_of",
    "request_text",
    "step_material",
    "strict",
    "subject_holds",
    "sweep_step_outcomes",
    "targets_of",
    "with_outcomes",
    "write_step_outcomes",
]
