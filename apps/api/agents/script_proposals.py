"""The pieces every script Pip writes shares, whatever holds the script (D-820, D-1005).

Pip writes an Inbound line's script and a campaign's through one writer
(`workers/script_writer.write_script`). They share what is here: the brief a draft is written
from (`brief_for`), where a check finding is (`finding_key`) and the warning it leaves
(`fix_left`), the paths of a part the owner names (`part_paths`), and the owner's words for
the parts a draft left out.

An agent has no script of its own (D-997, D-1000), so the agent's own suggestion that lived on
`agents.script_proposal` is retired (D-1005); the column is kept unwritten under hard rule 8.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import (
    CallScript,
    ConversationStage,
    ScriptPolicies,
)
from calevate_shared.engine import introduces_itself
from calevate_shared.opening_notices import WovenNotices
from calevate_shared.spoken_style import style_for
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_builder
from apps.api.agents.business_fit import business_fit
from apps.api.agents.capability_manifest import manifest_for, owner_facts
from apps.api.agents.script_lint import plain
from apps.api.agents.starter_plans import stored_plans
from apps.api.agents.starters import JOB_STEP_COUNTS
from apps.api.core.errors import ProblemError
from apps.api.engine import engine_capabilities
from apps.workers.script_assist import LeftOut, ScriptBrief

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
    "step_outcomes": "What each step must reach",
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


def part_paths(script: CallScript, label: str) -> list[str]:
    """The text paths of the part an owner names by its Script tab label ("Quick facts",
    "How it ends the call"), for a one-part rewrite of a part that is not a step; [] when
    the label names none."""
    folded = " ".join(label.split()).casefold()
    field = next((key for key, name in _PART_LABELS.items() if name.casefold() in folded), None)
    if field == "faqs":
        return [f"faqs.{i}.answer" for i in range(len(script.faqs))]
    if field == "objections":
        return [f"objections.{i}.response" for i in range(len(script.objections))]
    if field is not None and isinstance(getattr(script, field, None), str):
        return [field] if str(getattr(script, field)).strip() else []
    return []


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
        # An agent's own script asks for no details: its jobs' lists do (D-1028).
        collect=(),
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


def finding_key(problem: str, script: CallScript) -> str:
    """Where a script check finding is, by the step's id rather than its place, so a finding
    is still recognised after a fix moved or removed a step before it."""
    path = problem.partition(": ")[0]
    head, _, rest = path.partition(".")
    index, _, field_path = rest.partition(".")
    if head == "stages" and index.isdigit() and int(index) < len(script.stages):
        return f"stages#{script.stages[int(index)].id}.{field_path}"
    return path


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


#: Where a holder's draft is while Pip writes it, as the draft stream reports it. The job
#: stores the first four on the draft (`workers/campaign_script._phase`); `ready` and `failed`
#: are the draft's own status, and `cancelled` is a draft stopped before it was written.
DraftPhase = Literal["reading", "writing", "checking", "repairing", "ready", "failed", "cancelled"]
WORKING_PHASES: Final[frozenset[str]] = frozenset({"reading", "writing", "checking", "repairing"})


@dataclass(frozen=True, slots=True)
class ScriptLine:
    """One line of words in a script, at its check path (`stages.2.sounds_like`), with the
    owner's name for where it is. `key` matches the same line across two versions: a step's
    lines by the step's id, so a step inserted before it does not read as every later step
    changed."""

    path: str
    label: str
    text: str
    key: str


LineOp = Literal["added", "removed", "changed", "same"]


@dataclass(frozen=True, slots=True)
class LineChange:
    path: str
    label: str
    op: LineOp
    before: str | None
    after: str | None


def line_label(path: str, script: CallScript) -> str:
    """Where `path` is, in the words the client screens already use for it: the script
    check's place names (`script_lint.plain`: "Step 3", "The opening line"), the Script tab's
    part names (`_PART_LABELS`) where those have none, and a step's own name beside its
    number."""
    top = path.split(".")[0]
    place = plain(f"{path}: -").removesuffix(": -")
    if place == top.replace("_", " ").capitalize() and top in _PART_LABELS:
        place = _PART_LABELS[top]
    parts = path.split(".")
    if top == "stages" and len(parts) > 1 and parts[1].isdigit():
        index = int(parts[1])
        if index < len(script.stages) and script.stages[index].name.strip():
            return f"{place} · {script.stages[index].name.strip()}"
    return place


def _stage_lines(stage: ConversationStage, index: int) -> list[tuple[str, str, str]]:
    """(path, key, text) of a step's words, in the order the step editor lists them."""
    at, key = f"stages.{index}", f"stages#{stage.id}"
    rows = [
        ("name", stage.name),
        ("instruction", stage.instruction),
        ("sounds_like", stage.sounds_like),
        *((f"scripts.{tag}", said) for tag, said in sorted(stage.scripts.items())),
        *((f"procedure.{j}.action", p.action) for j, p in enumerate(stage.procedure)),
        *((f"procedure.{j}.wait_for", p.wait_for) for j, p in enumerate(stage.procedure)),
        *((f"qa.{j}.question", qa.question) for j, qa in enumerate(stage.qa)),
        *((f"qa.{j}.answer", qa.answer) for j, qa in enumerate(stage.qa)),
        *((f"branches.{j}.when", b.when) for j, b in enumerate(stage.branches)),
    ]
    return [(f"{at}.{sub}", f"{key}.{sub}", said) for sub, said in rows]


def script_lines(script: CallScript) -> list[ScriptLine]:
    """Every non-blank line of words in `script`, in script order: how the call opens, who
    the agent is and what it is for, how it speaks, the steps, then the answers, the ending
    and the example call. Ids, positions and switches are not words and are not listed."""
    rows: list[tuple[str, str]] = [
        ("opening_line", script.opening_line),
        ("outbound_opening_line", script.outbound_opening_line),
        ("business_line", script.business_line),
        ("identity", script.identity),
        ("goal", script.goal),
        ("outbound_purpose", script.outbound_purpose),
        ("style.tone", script.style.tone),
        ("style.address_form", script.style.address_form),
        *((f"style.sample_phrases.{i}", p) for i, p in enumerate(script.style.sample_phrases)),
        *((f"steps.{i}.instruction", s.instruction) for i, s in enumerate(script.steps)),
    ]
    keyed = [(path, path, said) for path, said in rows]
    for index, stage in enumerate(script.stages):
        keyed += _stage_lines(stage, index)
    tail: list[tuple[str, str]] = [
        *((f"step_outcomes.{i}.outcome", o.outcome) for i, o in enumerate(script.step_outcomes)),
        *((f"faqs.{i}.question", f.question) for i, f in enumerate(script.faqs)),
        *((f"faqs.{i}.answer", f.answer) for i, f in enumerate(script.faqs)),
        *((f"objections.{i}.objection", o.objection) for i, o in enumerate(script.objections)),
        *((f"objections.{i}.response", o.response) for i, o in enumerate(script.objections)),
        ("ending", script.ending),
        *((f"example_exchange.{i}.text", e.text) for i, e in enumerate(script.example_exchange)),
    ]
    keyed += [(path, path, said) for path, said in tail]
    return [
        ScriptLine(path, line_label(path, script), said, key)
        for path, key, said in keyed
        if said.strip()
    ]


def _spoken(text: str) -> str:
    """A line as a caller hears it: a re-wrapped line or a trailing space is no change."""
    return " ".join(text.split())


def script_diff(before: CallScript | None, after: CallScript) -> list[LineChange]:
    """`after` against `before`, line by line in script order. A line `after` no longer has
    is listed where it stood, after the lines that came before it in both."""
    old = script_lines(before) if before is not None else []
    new = script_lines(after)
    old_at = {line.key: index for index, line in enumerate(old)}
    kept = {line.key for line in new}
    changes: list[LineChange] = []
    shown = 0

    def removed_until(stop: int) -> None:
        nonlocal shown
        for line in old[shown:stop]:
            if line.key not in kept:
                changes.append(LineChange(line.path, line.label, "removed", line.text, None))
        shown = max(shown, stop)

    for line in new:
        index = old_at.get(line.key)
        if index is None:
            changes.append(LineChange(line.path, line.label, "added", None, line.text))
            continue
        removed_until(index)
        was = old[index].text
        op: LineOp = "same" if _spoken(was) == _spoken(line.text) else "changed"
        changes.append(LineChange(line.path, line.label, op, was, line.text))
    removed_until(len(old))
    return changes


__all__ = [
    "FAILED_NOTE",
    "TOO_BIG_NOTE",
    "WORKING_PHASES",
    "DraftPhase",
    "LineChange",
    "LineOp",
    "ScriptLine",
    "brief_for",
    "finding_key",
    "fix_left",
    "left_out_of",
    "left_out_record",
    "line_label",
    "owner_rule",
    "part_label",
    "part_paths",
    "script_diff",
    "script_lines",
]
