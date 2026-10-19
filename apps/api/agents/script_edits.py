"""Small, targeted edits to a call script: what "Improve my agent" proposes (D-823).

Founder, 18 Oct 2026: the improver returns a list of edits, each validated on its own and
kept or left by the owner with its own tick box, never a whole script. A whole-script answer
was the expensive and fragile shape: it is long (the standby model truncated it), it can
silently change parts nobody asked about, and one broken field threw away every fix in it.
Aider's edit-format notes say the same of whole-file output, "slow and costly because the
LLM has to return the entire file even if just a few lines are edited"
(aider.chat/docs/more/edit-formats.html, read 18 Oct 2026).

An edit is applied to a script by `apply_edit`, which refuses one that no longer fits (its
step is gone, the step limit is reached, the result would not validate) with the field and
the rule, never the text. The same function builds the proposal from the script it was made
from and applies the kept edits to the owner's current copy, so the two cannot disagree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Final, Literal, get_args

from calevate_shared.call_script import (
    MAX_SCRIPT_OBJECTIONS,
    MAX_SCRIPT_STAGES,
    STAGE_TITLE_MAX,
    CallScript,
    ConversationStage,
    Objection,
)
from calevate_shared.spoken_guard import english_problem, textbook_problem
from pydantic import ValidationError

EditOp = Literal["set_step", "add_step", "set_objection", "set_part"]
EditPart = Literal[
    "opening_line", "ending", "identity", "goal", "business_line", "outbound_purpose"
]

EDIT_OPS: Final[tuple[str, ...]] = get_args(EditOp)
EDIT_PARTS: Final[tuple[str, ...]] = get_args(EditPart)

#: The owner's names for the parts, as the script builder labels them (`scriptDiff.ts`).
PART_LABELS: Final[dict[str, str]] = {
    "business_line": "Your business in one line",
    "identity": "Its role",
    "goal": "The goal",
    "outbound_purpose": "Why you are calling",
    "opening_line": "Opening line",
    "ending": "How it ends the call",
}

#: Characters of a model-written field before it is cut: the longest a script field holds.
_TEXT_MAX: Final = 1000
#: The most edits one proposal keeps: one per failed test is asked for, and a run holds
#: about a dozen tests.
MAX_EDITS: Final = 12


class EditRejectedError(ValueError):
    """An edit that does not fit the script. `field` and `rule` name where and why; neither
    carries the edit's text, which is the client's script."""

    def __init__(self, field: str, rule: str) -> None:
        super().__init__(f"{field}: {rule}")
        self.field = field
        self.rule = rule


@dataclass(frozen=True, slots=True)
class ScriptEdit:
    """One edit. `step_id` is the step changed (`set_step`) or the step a new one follows
    (`add_step`, empty for the end); `name` is a new step's name; `objection` what the caller
    says; `text` the new words; `because` the test it fixes."""

    id: str
    op: str
    step_id: str = ""
    part: str = ""
    name: str = ""
    objection: str = ""
    text: str = ""
    because: str | None = None
    why: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def of(cls, raw: dict[str, Any]) -> ScriptEdit:
        return cls(
            id=str(raw.get("id") or ""),
            op=str(raw.get("op") or ""),
            step_id=str(raw.get("step_id") or ""),
            part=str(raw.get("part") or ""),
            name=str(raw.get("name") or ""),
            objection=str(raw.get("objection") or ""),
            text=str(raw.get("text") or ""),
            because=raw.get("because") or None,
            why=str(raw.get("why") or ""),
        )

    @property
    def target(self) -> str:
        """What the edit changes; two edits with one target cannot both be kept."""
        if self.op == "set_step":
            return f"step:{self.step_id}"
        if self.op == "set_part":
            return f"part:{self.part}"
        if self.op == "set_objection":
            return f"objection:{_norm(self.objection)}"
        return f"add:{_norm(self.name)}"


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def clip(value: Any, limit: int = _TEXT_MAX) -> str:
    return " ".join(str(value or "").split())[:limit]


def _next_stage_id(script: CallScript) -> str:
    taken = {stage.id for stage in script.stages}
    n = len(script.stages) + 1
    while f"s{n}" in taken:
        n += 1
    return f"s{n}"


def _validated(script: CallScript, update: dict[str, Any]) -> CallScript:
    try:
        return CallScript.model_validate({**script.model_dump(), **update})
    except ValidationError as invalid:
        error = invalid.errors(include_input=False, include_url=False)[0]
        raise EditRejectedError(
            ".".join(str(part) for part in error["loc"]) or "script", error["type"]
        ) from invalid


def _stage(raw: dict[str, Any]) -> ConversationStage:
    try:
        return ConversationStage.model_validate(raw)
    except ValidationError as invalid:
        error = invalid.errors(include_input=False, include_url=False)[0]
        where = ".".join(str(part) for part in error["loc"])
        raise EditRejectedError(f"text{'.' + where if where else ''}", error["type"]) from invalid


def apply_edit(script: CallScript, edit: ScriptEdit) -> CallScript:
    """`script` with `edit` made, validated like any save. Raises `EditRejectedError`."""
    if edit.op not in EDIT_OPS:
        raise EditRejectedError("op", "unknown_op")
    if not edit.text.strip():
        raise EditRejectedError("text", "empty")
    if edit.op == "set_step":
        index = next((i for i, s in enumerate(script.stages) if s.id == edit.step_id), None)
        if index is None:
            raise EditRejectedError("step_id", "unknown_step")
        current = script.stages[index]
        if _norm(current.instruction) == _norm(edit.text):
            raise EditRejectedError("text", "unchanged")
        stages = list(script.stages)
        stages[index] = _stage({**current.model_dump(), "instruction": edit.text})
        return _validated(script, {"stages": [s.model_dump() for s in stages]})
    if edit.op == "add_step":
        if len(script.stages) >= MAX_SCRIPT_STAGES:
            raise EditRejectedError("op", "too_many_steps")
        name = clip(edit.name, STAGE_TITLE_MAX)
        if not name:
            raise EditRejectedError("name", "empty")
        if any(_norm(s.name) == _norm(name) for s in script.stages):
            raise EditRejectedError("name", "step_exists")
        at = len(script.stages)
        if edit.step_id:
            after = next((i for i, s in enumerate(script.stages) if s.id == edit.step_id), None)
            if after is None:
                raise EditRejectedError("step_id", "unknown_step")
            at = after + 1
        added = _stage({"id": _next_stage_id(script), "name": name, "instruction": edit.text})
        stages = [*script.stages[:at], added, *script.stages[at:]]
        return _validated(script, {"stages": [s.model_dump() for s in stages]})
    if edit.op == "set_objection":
        if not edit.objection.strip():
            raise EditRejectedError("objection", "empty")
        try:
            line = Objection(objection=edit.objection, response=edit.text)
        except ValidationError as invalid:
            error = invalid.errors(include_input=False, include_url=False)[0]
            raise EditRejectedError(
                ".".join(str(p) for p in error["loc"]), error["type"]
            ) from invalid
        objections = list(script.objections)
        index = next(
            (i for i, o in enumerate(objections) if _norm(o.objection) == _norm(edit.objection)),
            None,
        )
        if index is not None:
            if _norm(objections[index].response) == _norm(edit.text):
                raise EditRejectedError("text", "unchanged")
            objections[index] = line
        elif len(objections) >= MAX_SCRIPT_OBJECTIONS:
            raise EditRejectedError("op", "too_many_objections")
        else:
            objections.append(line)
        return _validated(script, {"objections": [o.model_dump() for o in objections]})
    if edit.part not in EDIT_PARTS:
        raise EditRejectedError("part", "unknown_part")
    if _norm(str(getattr(script, edit.part))) == _norm(edit.text):
        raise EditRejectedError("text", "unchanged")
    return _validated(script, {edit.part: edit.text})


def language_problem(
    edit: ScriptEdit, script: CallScript, language: str | None, *, where: str
) -> str | None:
    """What breaks the language rules in an edit the AI proposed (D-831), or None.

    The new words are an instruction (plain English) unless they are said: the opening line
    and a "say" step, which must not use a textbook word. Only for the improver's answer:
    `apply_edit` applies the owner's kept edits and never judges their language."""
    spoken = edit.op == "set_part" and edit.part == "opening_line"
    if edit.op == "set_step":
        stage = next((s for s in script.stages if s.id == edit.step_id), None)
        spoken = stage is not None and stage.mode == "say"
    if spoken:
        return textbook_problem(where, edit.text, language)
    return english_problem(where, edit.text)


def apply_edits(
    script: CallScript, edits: list[ScriptEdit]
) -> tuple[CallScript, list[str], list[tuple[ScriptEdit, EditRejectedError]]]:
    """Each edit in order onto `script`: the result, the ids applied, and the edits that did
    not fit with why. An edit that does not fit leaves the script as it was before it."""
    applied: list[str] = []
    rejected: list[tuple[ScriptEdit, EditRejectedError]] = []
    for edit in edits:
        try:
            script = apply_edit(script, edit)
        except EditRejectedError as refused:
            rejected.append((edit, refused))
            continue
        applied.append(edit.id)
    return script, applied, rejected


def describe(edit: ScriptEdit, base: CallScript) -> dict[str, str]:
    """What the owner reads above an edit's tick box: what it changes, before and after."""
    if edit.op == "set_step":
        stage = next((s for s in base.stages if s.id == edit.step_id), None)
        name = stage.name if stage is not None else edit.step_id
        return {
            "label": f"Step “{name}”",
            "before": stage.instruction if stage is not None else "",
            "after": edit.text,
        }
    if edit.op == "add_step":
        after = next((s for s in base.stages if s.id == edit.step_id), None)
        where = f" after “{after.name}”" if after is not None else " at the end"
        return {"label": f"New step “{edit.name}”{where}", "before": "", "after": edit.text}
    if edit.op == "set_objection":
        existing = next(
            (o for o in base.objections if _norm(o.objection) == _norm(edit.objection)), None
        )
        return {
            "label": f"When a caller says “{edit.objection}”",
            "before": existing.response if existing is not None else "",
            "after": edit.text,
        }
    return {
        "label": PART_LABELS.get(edit.part, edit.part),
        "before": str(getattr(base, edit.part, "")),
        "after": edit.text,
    }


__all__ = [
    "EDIT_OPS",
    "EDIT_PARTS",
    "MAX_EDITS",
    "PART_LABELS",
    "EditOp",
    "EditPart",
    "EditRejectedError",
    "ScriptEdit",
    "apply_edit",
    "apply_edits",
    "clip",
    "describe",
    "language_problem",
]
