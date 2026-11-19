"""The pieces every script Pip writes shares, whatever holds the script (D-820, D-1005).

Pip writes an Inbound line's script and a campaign's (`workers/campaign_script`), and the fix
of a mistake on real calls as a draft on that line or campaign (`workers/script_proposal.
draft_mistake_fix`). They share what is here: the brief a draft is written from (`brief_for`),
the request a written script is checked against (`ScriptProposal`, read by `script_proposal.
finish_written`), the targeted fix of named lines (`kept_to_paths`, `fix_change`, `fix_left`,
`finding_key`), and the owner's words for the parts a draft left out.

An agent has no script of its own (D-997, D-1000), so the agent's own suggestion that lived on
`agents.script_proposal` is retired (D-1005); the column is kept unwritten under hard rule 8.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import (
    MAX_STAGE_COLLECT,
    CallScript,
    ConversationStage,
    ScriptPolicies,
)
from calevate_shared.engine import introduces_itself
from calevate_shared.opening_notices import WovenNotices
from calevate_shared.spoken_style import style_for
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_builder
from apps.api.agents.business_fit import business_fit
from apps.api.agents.capability_manifest import manifest_for, owner_facts
from apps.api.agents.script_lint import order_problems, placeholder_instruction
from apps.api.agents.starter_plans import stored_plans
from apps.api.agents.starters import JOB_STEP_COUNTS
from apps.api.core.errors import ProblemError
from apps.api.engine import engine_capabilities
from apps.workers.script_assist import (
    LeftOut,
    ScriptBrief,
    ways_to_kept_steps,
    without_placeholder_steps,
)

#: `change`: an edit of the holder's script. `whole`: a first script, written whole.
ProposalMode = Literal["change", "whole"]

ProposalStatus = Literal["drafting", "ready", "failed"]

#: The job's own fallback when the failure is not one of the AI refusals.
FAILED_NOTE: Final = (
    "The suggestion could not be written this time. Ask Pip again in a few minutes; if it "
    "keeps happening, contact us."
)

#: When the answer was cut off at its token ceiling and nothing usable came back: the one
#: failure the owner fixes by asking for less at a time.
TOO_BIG_NOTE: Final = (
    "This change was too big for Pip to write in one go. Ask for one part at a time, for "
    "example the opening first, then the steps."
)

#: What a part of the script is called on the Script tab, for a field a left-out part names.
_PART_LABELS: Final[dict[str, str]] = {
    "stages": "The list of steps",
    "opening_line": "The opening line",
    "outbound_opening_line": "The opening line for calls it makes",
    "goal": "The main task",
    "business_line": "What the business does",
    "identity": "Who the agent is",
    "outbound_purpose": "Why it calls",
    "faqs": "Quick facts",
    "objections": "Answers to worries",
    "ending": "How it ends the call",
    "example_exchange": "The example call",
    "style": "How it speaks",
    # A warning a fix still leaves that is about the steps as a whole ("no step asks for").
    "script": "The script",
}

_ASIDE: Final = re.compile(r"\s*\([^)]*\)")


def part_label(part: LeftOut) -> str:
    """The part's name as the owner knows it: a step by its name, a field by its label."""
    if part.part.startswith("stages."):
        return f"Step “{part.name}”" if part.name else "A step"
    return _PART_LABELS.get(part.part, part.part.replace("_", " ").capitalize())


def owner_rule(rule: str) -> str:
    """A rule the model was told it broke, as the owner reads it: an aside in brackets goes,
    since it may name the vendor a line mentioned (D-679), and the sentence is closed."""
    said = _ASIDE.sub("", rule).strip().rstrip(".;")
    return f"{said[:1].upper()}{said[1:]}." if said else "It broke one of the call rules."


def unwritten_note(parts: Sequence[LeftOut]) -> str:
    """The failure note when the parts Pip could not write are known: which, and why."""
    shown = [f"{part_label(p)}: {owner_rule(p.rule).rstrip('.')}" for p in parts[:3]]
    more = f" and {len(parts) - 3} more" if len(parts) > 3 else ""
    return (
        f"Pip could not write a clean version of {'; '.join(shown)}{more}. Edit those parts "
        "yourself, or ask Pip to change one of them at a time."
    )


def left_out_record(parts: Sequence[LeftOut]) -> list[dict[str, Any]]:
    return [
        {
            "part": p.part,
            "name": p.name,
            "rule": owner_rule(p.rule),
            "added": p.added,
            "unfixed": p.unfixed,
        }
        for p in parts
    ]


@dataclass(frozen=True, slots=True)
class ScriptProposal:
    """What a written script is checked against before an owner reviews it
    (`script_proposal.finish_written`): the script it was made from and the owner's words."""

    id: UUID
    mode: ProposalMode
    status: ProposalStatus
    request: str | None
    answers: dict[str, str]
    base_script: CallScript
    requested_by: UUID | None
    requested_at: datetime
    #: A fix (D-985, D-1005): the only lines it may change, the paths the check named.
    paths: list[str] = field(default_factory=list)


def left_out_of(raw: Any) -> list[LeftOut]:
    return [
        LeftOut(
            part=str(item.get("part", "")),
            name=str(item.get("name", "")),
            rule=str(item.get("rule", "")),
            added=bool(item.get("added", False)),
            unfixed=bool(item.get("unfixed", False)),
        )
        for item in raw or []
        if isinstance(item, dict)
    ]


async def brief_for(
    session: AsyncSession, tenant_id: UUID, agent_id: UUID, *, language: str | None = None
) -> ScriptBrief:
    """What every draft is written from besides the owner's words: the business, the
    agent's direction and call language with its spoken register, the details it collects
    and the knowledge titles, what it can do on a call and the owner's facts (D-945).
    `language` writes it in another language than the agent's own (a campaign's main
    language). Tenant-authored configuration only (D-127 G-2)."""
    row = (
        await session.execute(
            text(
                "SELECT a.direction, a.language_primary, o.vertical_template, o.name, a.name, "
                "CASE WHEN o.notice_ai_enabled THEN a.ai_disclosure_line ELSE '' END, "
                "o.notice_ai_enabled, o.notice_recording_enabled "
                "FROM agents a JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL AND o.id = :tid"
            ),
            {"aid": agent_id, "tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    language = language or str(row[1])
    style = style_for(language)
    titles = await session.execute(
        text(
            "SELECT name FROM kb_sources WHERE is_active AND published_at IS NOT NULL "
            "ORDER BY published_at DESC LIMIT 20"
        )
    )
    return ScriptBrief(
        business_name=str(row[3] or ""),
        agent_name=str(row[4] or ""),
        business_type=str(row[2] or "custom"),
        direction=str(row[0]),
        language=language,
        register=(f"{style.register_name}. {style.register}" if style is not None else ""),
        collect=tuple(f.label for f in await script_builder.collect_fields(session, agent_id)),
        knowledge_titles=tuple(str(r[0])[:120] for r in titles),
        introduced=introduces_itself(ai_notice=str(row[5]), language=language),
        woven=WovenNotices(
            ai=bool(row[6]),
            recording=bool(row[7]) and engine_capabilities().records_audio,
        ),
        capabilities=await manifest_for(session, tenant_id=tenant_id, agent_id=agent_id),
        facts=await owner_facts(session, tenant_id=tenant_id, agent_id=agent_id),
        step_plans=tuple(
            (await stored_plans(session, tenant_id=tenant_id, shapes=JOB_STEP_COUNTS)).items()
        ),
        # The agent's own job, as the switches the owner is editing say it (G1-2): the
        # autosaved working copy when there is one, else the draft version.
        fit=(await business_fit(session, tenant_id)).for_agent(
            await _edited_policies(session, agent_id)
        ),
    )


async def _edited_policies(session: AsyncSession, agent_id: UUID) -> ScriptPolicies:
    draft = await script_builder.read_draft(session, agent_id)
    if draft is not None:
        return draft.script.policies
    return (await script_builder.load_agent_script(session, agent_id)).script.policies


def _stage_index(script: CallScript, stage_id: str) -> int | None:
    return next((i for i, s in enumerate(script.stages) if s.id == stage_id), None)


def _at(data: Any, parts: list[str]) -> Any:
    for part in parts:
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return None
    return data


def _put(data: Any, parts: list[str], value: str) -> None:
    for part in parts[:-1]:
        data = data[int(part)] if isinstance(data, list) else data[part]
    last = parts[-1]
    if isinstance(data, list):
        data[int(last)] = value
    else:
        data[last] = value


def kept_to_paths(
    written: CallScript,
    base: CallScript,
    paths: Sequence[str],
    *,
    unasked: Sequence[str] = (),
) -> CallScript:
    """`base` with only the lines at `paths` taken from `written` (A-02): a fix asked for
    the lines the script check named and may change nothing else, whatever the model
    returned. A step is matched by its id, since the model may reorder steps; a line the
    model emptied, or a path it no longer has, stays as the owner wrote it. A finding about
    the whole script ("no step asks for X") may reword step instructions and add each label
    in `unasked` to the details one step collects (`_collect_from`), nothing more. The two
    findings about the call's shape are the exception, below."""
    allowed = {p for p in paths if p != "script"}
    if "script" in paths:
        allowed |= {f"stages.{i}.instruction" for i in range(len(base.stages))}
    out = base.model_dump(mode="json")
    new = written.model_dump(mode="json")
    for path in sorted(allowed):
        parts = path.split(".")
        source = parts
        if parts[0] == "stages" and len(parts) > 2 and parts[1].isdigit():
            index = int(parts[1])
            if index >= len(base.stages):
                continue
            moved = _stage_index(written, base.stages[index].id)
            if moved is None:
                continue
            source = ["stages", str(moved), *parts[2:]]
        before, after = _at(out, parts), _at(new, source)
        if isinstance(before, str) and isinstance(after, str) and after.strip():
            _put(out, parts, after)
    _fit_step_details(out, base, written)
    kept = CallScript.model_validate(out)
    if "script" in paths and unasked:
        kept = _collect_from(written, kept, unasked)
    # Two findings are about the call's shape, not a line, and their fix is not a reworded
    # instruction (`script_lint.flow_problems`): a step in the wrong place on the call is
    # fixed by its ways out or its place, and a placeholder step by taking it out.
    named = {p for p in paths if p.startswith("stages.")}
    misplaced = {p.partition(":")[0] for p in order_problems(base)}
    if named & misplaced:
        kept = _ways_from(written, kept)
    return without_placeholder_steps(kept) if named & _placeholder_paths(base) else kept


def _fit_step_details(out: dict[str, Any], base: CallScript, written: CallScript) -> None:
    """Each step of `out` whose instruction and "sounds like" line no longer fit one step
    detail together (`ConversationStage._detail_fits_a_step`), one taken from `written` and
    the other kept: the written step's pair, which fit together there, else the owner's step
    as it was. A step that failed validation here crashed the job after the model was paid."""
    by_id = {stage.id: stage for stage in written.stages}
    for i, raw in enumerate(out["stages"]):
        if _fits(raw):
            continue
        own = base.stages[i]
        fixed = by_id.get(own.id)
        paired = (
            {**raw, "instruction": fixed.instruction, "sounds_like": fixed.sounds_like}
            if fixed is not None
            else None
        )
        out["stages"][i] = (
            paired if paired is not None and _fits(paired) else own.model_dump(mode="json")
        )


def _fits(raw: dict[str, Any]) -> bool:
    try:
        ConversationStage.model_validate(raw)
    except ValidationError:
        return False
    return True


def _placeholder_paths(script: CallScript) -> set[str]:
    """The instructions of the steps a fix may take out: placeholders, never the close."""
    return {
        f"stages.{i}.instruction"
        for i, stage in enumerate(script.stages[:-1])
        if placeholder_instruction(stage.instruction)
    }


def _ways_from(written: CallScript, kept: CallScript) -> CallScript:
    """`kept` with each step's ways out, and the steps' order, as `written` has them. A step
    `written` dropped keeps its own; a way to a step `kept` lacks goes (`ways_to_kept_steps`)."""
    by_id = {stage.id: stage for stage in written.stages}
    stages = [
        stage.model_copy(
            update={"branches": by_id[stage.id].branches, "otherwise": by_id[stage.id].otherwise}
        )
        if stage.id in by_id
        else stage
        for stage in kept.stages
    ]
    if set(by_id) == {stage.id for stage in stages}:
        rank = {stage_id: i for i, stage_id in enumerate(by_id)}
        stages.sort(key=lambda stage: rank[stage.id])
    return CallScript.model_validate(
        {
            **kept.model_dump(mode="json"),
            "stages": ways_to_kept_steps([stage.model_dump(mode="json") for stage in stages]),
        }
    )


def _collect_from(written: CallScript, kept: CallScript, unasked: Sequence[str]) -> CallScript:
    """`kept` with each label in `unasked` added to the details of the first step that
    `written` (matched by id) has collecting it, while that step has room. Only those labels
    are taken: any other detail the model put in a list stays out. A step's `collect` is what
    `script_lint.unasked_details` accepts as asking for a detail in any language, where its
    English-word reading of an instruction cannot see a step written in Telugu or Hindi."""
    stages = list(kept.stages)
    collects = {s.id: {c.casefold() for c in s.collect} for s in written.stages}
    for raw in unasked:
        label = " ".join(raw.split())[:80]
        key = label.casefold()
        for i, stage in enumerate(stages):
            has = {c.casefold() for c in stage.collect}
            if key in collects.get(stage.id, set()) and key not in has:
                if len(stage.collect) < MAX_STAGE_COLLECT:
                    stages[i] = stage.model_copy(update={"collect": [*stage.collect, label]})
                break
    return kept.model_copy(update={"stages": stages})


def finding_key(problem: str, script: CallScript) -> str:
    """Where a script check finding is, by the step's id rather than its place, so a finding
    is still recognised after a fix moved or removed a step before it."""
    path = problem.partition(": ")[0]
    head, _, rest = path.partition(".")
    index, _, field_path = rest.partition(".")
    if head == "stages" and index.isdigit() and int(index) < len(script.stages):
        return f"stages#{script.stages[int(index)].id}.{field_path}"
    return path


#: How a fix finding that no step asks for a detail is fixed, in any call language.
_UNASKED_FIX: Final = (
    'For a detail no step asks for: add that detail, word for word as quoted, to the "collect" '
    "list of the one step where the call reaches it, and have that step's instruction ask it "
    "as one question. Change no other step for it."
)


def fix_change(problems: Sequence[str], script: CallScript) -> str:
    """What the writer is asked for when fixing script check findings: each finding at its
    real place in the script JSON it is given (`stages.9.sounds_like`, numbered from 0, with
    the step's id and name), not the owner's "Step 10", which named the step after it."""

    def where(problem: str) -> str:
        path, _, rest = problem.partition(": ")
        parts = path.split(".")
        if parts[0] == "stages" and len(parts) > 1 and parts[1].isdigit():
            index = int(parts[1])
            if index < len(script.stages):
                stage = script.stages[index]
                return f'{path} (step id "{stage.id}", named "{stage.name}"): {rest}'
        return f"{path}: {rest}"

    lines = [
        "Fix only these problems the script check found, and change nothing else. Each "
        "starts with the field it is in, as a path in the script JSON (stages counted from 0).",
        *(f"- {where(problem)}" for problem in problems),
    ]
    if any(problem.startswith("script: ") for problem in problems):
        lines.append(_UNASKED_FIX)
    return "\n".join(lines)


def fix_left(problems: Sequence[str], script: CallScript) -> list[LeftOut]:
    """Each finding a fix could not clear, as a part of the proposal the owner reads: the
    step it is in (by id and name) or the field, and the warning itself."""
    left: list[LeftOut] = []
    for problem in problems:
        path, _, rest = problem.partition(": ")
        parts = path.split(".")
        part, name = parts[0], ""
        if part == "stages" and len(parts) > 1 and parts[1].isdigit():
            index = int(parts[1])
            if index < len(script.stages):
                part, name = f"stages.{script.stages[index].id}", script.stages[index].name
        left.append(LeftOut(part, name, f"Still to fix: {rest}", unfixed=True))
    return left


__all__ = [
    "FAILED_NOTE",
    "TOO_BIG_NOTE",
    "ProposalMode",
    "ProposalStatus",
    "ScriptProposal",
    "brief_for",
    "finding_key",
    "fix_change",
    "fix_left",
    "kept_to_paths",
    "left_out_of",
    "left_out_record",
    "owner_rule",
    "part_label",
    "unwritten_note",
]
