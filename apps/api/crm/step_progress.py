"""Where a call got to: which of its script's steps reached their outcome (founder, 24 Nov 2026:
the outcomes must "actually do something").

The after-call judge (`workers/step_progress`) reads the redacted transcript against the
script of the campaign or inbound line the call was on and stores one reading per step on the
call (`calls.step_progress`): `reached` (with the caller turn that shows it, quote-checked by
code), `not_reached` (with the agent turn that moved on, when it did) or `unclear`. Step names
and turn indexes only, never the words (hard rule 6): the call page shows the words from the
transcript it already holds.

The reading is the structural source for three things:

* the call page's "Where the call got to";
* a progress-type detail the call notes (a choice field whose choices follow the steps, or a
  true/false detail that means one step's outcome), whose value is taken from the furthest
  step reached rather than the extraction model's own guess (`progress_values`), so a call
  that never got past step 2 cannot be noted as step 4;
* the campaign goal verdict and the business outcome, through the step each means
  (`goal_step`, `outcomes`; `workers/step_truth` applies them);
* the review kind `moved_on_unconfirmed` (`call_mistakes.step_mistakes`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from calevate_shared.extraction import ExtractionSchemaSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

StepState = Literal["reached", "not_reached", "unclear"]
STEP_STATES: Final = ("reached", "not_reached", "unclear")
NAME_MAX: Final = 200


@dataclass(frozen=True, slots=True)
class StepReading:
    step: int
    #: The step's scenario names when it was judged (the script may change afterwards).
    name: str
    state: StepState
    #: `reached`: the caller turn whose words show it.
    turn_idx: int | None = None
    #: `not_reached`: the agent turn that went on to a later step without a way out.
    moved_on_turn: int | None = None


@dataclass(frozen=True, slots=True)
class StepProgress:
    steps: tuple[StepReading, ...]
    #: Each progress-type detail of the call's notes: {field key: {choice: step}}. A
    #: true/false detail maps the one choice "true".
    fields: dict[str, dict[str, int]] = field(default_factory=dict)
    #: The step whose outcome means the campaign's goal is met; None when no step does.
    goal_step: int | None = None
    #: The agent's business outcomes that mean a step's outcome: {outcome key: step}.
    outcomes: dict[str, int] = field(default_factory=dict)

    @property
    def furthest(self) -> int | None:
        reached = [s.step for s in self.steps if s.state == "reached"]
        return max(reached) if reached else None

    def state_of(self, step: int) -> StepState | None:
        return next((s.state for s in self.steps if s.step == step), None)

    def shows_reached(self, step: int) -> bool:
        """Reached itself, or at or before the furthest step reached."""
        furthest = self.furthest
        return self.state_of(step) == "reached" or (furthest is not None and step <= furthest)


def progress_json(progress: StepProgress) -> str:
    return json.dumps(
        {
            "steps": [
                {
                    "step": s.step,
                    "name": s.name,
                    "state": s.state,
                    "turn_idx": s.turn_idx,
                    "moved_on_turn": s.moved_on_turn,
                }
                for s in progress.steps
            ],
            "fields": progress.fields,
            "goal_step": progress.goal_step,
            "outcomes": progress.outcomes,
        }
    )


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_progress(raw: Any) -> StepProgress | None:
    """The stored reading, or None for a call never judged. Read defensively: the column is
    ours, and one malformed entry must not hide the rest."""
    if not isinstance(raw, dict):
        return None
    steps: list[StepReading] = []
    for row in raw.get("steps") or []:
        if not isinstance(row, dict) or row.get("state") not in STEP_STATES:
            continue
        step = _int(row.get("step"))
        if step is None:
            continue
        steps.append(
            StepReading(
                step=step,
                name=str(row.get("name") or "")[:NAME_MAX],
                state=row["state"],
                turn_idx=_int(row.get("turn_idx")),
                moved_on_turn=_int(row.get("moved_on_turn")),
            )
        )
    fields: dict[str, dict[str, int]] = {}
    for key, mapping in (raw.get("fields") or {}).items():
        if isinstance(mapping, dict):
            steps_of = {str(choice): _int(step) for choice, step in mapping.items()}
            fields[str(key)] = {c: s for c, s in steps_of.items() if s is not None}
    outcomes = raw.get("outcomes")
    return StepProgress(
        steps=tuple(sorted(steps, key=lambda s: s.step)),
        fields=fields,
        goal_step=_int(raw.get("goal_step")),
        outcomes=(
            {str(k): v for k, v in outcomes.items() if _int(v) is not None}
            if isinstance(outcomes, dict)
            else {}
        ),
    )


async def stored_progress(session: AsyncSession, call_id: UUID) -> StepProgress | None:
    raw = (
        await session.execute(text("SELECT step_progress FROM calls WHERE id = :c"), {"c": call_id})
    ).scalar()
    return read_progress(raw)


async def store_progress(session: AsyncSession, call_id: UUID, progress: StepProgress) -> None:
    await session.execute(
        text("UPDATE calls SET step_progress = CAST(:p AS jsonb) WHERE id = :c"),
        {"p": progress_json(progress), "c": call_id},
    )


#: The script a call followed: its campaign's, its inbound line's, or, for a campaign's Test
#: call (kept out of `calls.campaign_id`), the campaign that placed it.
_HOLDER_SCRIPT_SQL: Final = text(
    "SELECT COALESCE("
    "  (SELECT g.script FROM campaigns g WHERE g.id = c.campaign_id),"
    "  (SELECT l.script FROM inbound_lines l WHERE l.id = c.inbound_line_id),"
    "  (SELECT g.script FROM campaigns g WHERE c.id = ANY(g.test_call_ids) LIMIT 1)"
    ") FROM calls c WHERE c.id = :c"
)


async def holder_script(session: AsyncSession, call_id: UUID) -> CallScript | None:
    raw = (await session.execute(_HOLDER_SCRIPT_SQL, {"c": call_id})).scalar()
    if not raw:
        return None
    script = CallScript.model_validate(raw)
    return None if script.raw_override is not None or not script.stages else script


def progress_values(
    progress: StepProgress, data: Mapping[str, Any], spec: ExtractionSchemaSpec
) -> dict[str, Any]:
    """What each progress-type detail of `data` becomes under the reading; a value of None
    means the detail is dropped (shown as not mentioned).

    A choice field takes the choice of the furthest step reached: the choice mapped to the
    highest step at or before it. A noted choice that names a later step than the furthest
    reached, with no earlier choice to fall back to, is dropped, as is any mapped choice on a
    call where no step was reached: the reading governs (call review of 25 Nov 2026, "First
    expense recorded" noted on a call that stopped at step 3). With no step reached and no
    noted choice beyond it, the detail is left alone.

    A true/false detail mapped to one step ("true" means that step's outcome) noted true for a
    step the call did not reach becomes false when the step is shown not reached, else is
    dropped."""
    furthest = progress.furthest
    types = {f.key: f.type for f in spec.fields}
    out: dict[str, Any] = {}
    for key, mapping in progress.fields.items():
        if key not in data:
            continue
        noted = data[key]
        if types.get(key) == "bool":
            step = mapping.get("true")
            if noted is True and step is not None and not progress.shows_reached(step):
                out[key] = False if progress.state_of(step) == "not_reached" else None
            continue
        upto = [(step, choice) for choice, step in mapping.items()]
        upto = [pair for pair in upto if furthest is not None and pair[0] <= furthest]
        if upto:
            out[key] = max(upto, key=lambda pair: pair[0])[1]
            continue
        noted_step = mapping.get(str(noted)) if isinstance(noted, str) else None
        if noted_step is not None and (furthest is None or noted_step > furthest):
            out[key] = None
    return {key: value for key, value in out.items() if data.get(key) != value}


__all__ = [
    "STEP_STATES",
    "StepProgress",
    "StepReading",
    "StepState",
    "holder_script",
    "progress_json",
    "progress_values",
    "read_progress",
    "store_progress",
    "stored_progress",
]
