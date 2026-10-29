"""What a Follow-up says, as data: its trigger, its steps and its settings (D-940).

Pydantic v2 discriminated unions, so a step's fields are the ones its `kind` allows and a
stored definition round-trips exactly. Two layers of checking, deliberately apart:

* **shape** (this module, no database): field types and ranges, step ids unique, every exit
  naming a step that exists and comes LATER in the list. Exits may only point forward, so a
  run always ends: the longest path is the step count, and `settings.max_days` ends
  anything still waiting (call retries are the one repeat, and they are bounded by `retries`).
* **references** (`service.problems_of`): the agent, template, teammate, team address and
  action each exist in this account. They need a session.

Both report the same `Problem(step_id, code, message)`, which is what the screen lists as
buttons and what Pip reads to fix a draft before the person sees it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

MAX_STEPS: Final = 30
MAX_SOURCES: Final = 50
MAX_AGENTS: Final = 50
MAX_OUTCOMES: Final = 30
MAX_VALUES: Final = 10
MAX_WHY_CHARS: Final = 120
MAX_TEXT_VALUE_CHARS: Final = 200
#: The longest a run may stay open, and the default (docs/FOLLOW-UPS.md, Settings).
MAX_DAYS_CAP: Final = 30
MAX_DAYS_DEFAULT: Final = 14
#: A call step's limits. `retry_minutes` keeps the old new-lead plan's floor of ten minutes,
#: so every plan the migration carried over stays valid.
CALL_WAIT_MAX_MINUTES: Final = 1440
CALL_WAIT_MAX_SECONDS: Final = 3600
CALL_RETRIES_MAX: Final = 3
RETRY_MINUTES_MIN: Final = 10
RETRY_MINUTES_MAX: Final = 1440
WAIT_MAX_DAYS: Final = 30
OFFSET_DAYS_MAX: Final = 30

StepId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,15}$")]
FieldKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
OutcomeKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
ClockTime = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
Target = StepId | None

LeadStatus = Literal["new", "contacted", "interested", "hot", "won", "lost"]
SettableStatus = Literal["contacted", "interested", "hot", "won", "lost"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- triggers -------------------------------------------------------------------------


class FieldEquals(_Strict):
    key: FieldKey
    equals: str = Field(min_length=1, max_length=MAX_TEXT_VALUE_CHARS)


class OnlyIf(_Strict):
    """Narrows any trigger. Every condition given must hold."""

    lead_status: list[LeadStatus] | None = Field(default=None, min_length=1, max_length=6)
    source_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=MAX_SOURCES)
    field: FieldEquals | None = None


class NewLeadTrigger(_Strict):
    kind: Literal["new_lead"]
    #: Null: a lead from any source.
    source_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=MAX_SOURCES)
    only_if: OnlyIf | None = None


class CallEndedTrigger(_Strict):
    kind: Literal["call_ended"]
    agent_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=MAX_AGENTS)
    calls: Literal["inbound", "outbound", "both"] = "both"
    #: The call's outcome (`missed`, `answered`, ...) or one of the agent's business
    #: outcomes. Null: any outcome.
    outcomes: list[OutcomeKey] | None = Field(default=None, min_length=1, max_length=MAX_OUTCOMES)
    only_if: OnlyIf | None = None


class ManualTrigger(_Strict):
    kind: Literal["manual"]
    only_if: OnlyIf | None = None


class LeadDateTrigger(_Strict):
    kind: Literal["lead_date"]
    #: A lead detail holding a date as `YYYY-MM-DD`.
    field: FieldKey
    offset_days: int = Field(0, ge=-OFFSET_DAYS_MAX, le=OFFSET_DAYS_MAX)
    #: IST wall clock.
    at: ClockTime = "10:00"
    only_if: OnlyIf | None = None


Trigger = Annotated[
    NewLeadTrigger | CallEndedTrigger | ManualTrigger | LeadDateTrigger,
    Field(discriminator="kind"),
]

# --- steps ----------------------------------------------------------------------------


class CallExits(_Strict):
    answered: Target = None
    not_reached: Target = None


class SendExits(_Strict):
    sent: Target = None
    not_sent: Target = None


class ActionExits(_Strict):
    done: Target = None
    failed: Target = None


class CallStep(_Strict):
    id: StepId
    kind: Literal["call"]
    #: Null: the lead's own agent (the agent its source or call gave it).
    agent_id: UUID | None = None
    wait_minutes: int = Field(0, ge=0, le=CALL_WAIT_MAX_MINUTES)
    #: An exact wait carried over from the old new-lead plan, which counted seconds. When
    #: set it wins over `wait_minutes`; any edit of the wait clears it.
    wait_seconds: int | None = Field(default=None, ge=0, le=CALL_WAIT_MAX_SECONDS)
    retries: int = Field(0, ge=0, le=CALL_RETRIES_MAX)
    retry_minutes: int = Field(60, ge=RETRY_MINUTES_MIN, le=RETRY_MINUTES_MAX)
    next: CallExits = Field(default_factory=CallExits)

    @property
    def wait_s(self) -> int:
        return self.wait_seconds if self.wait_seconds is not None else self.wait_minutes * 60


class DecideStep(_Strict):
    id: StepId
    kind: Literal["decide"]
    #: Outcome key (`answered`, `missed`, ... or a business outcome) -> the step it leads to.
    on: dict[OutcomeKey, Target] = Field(default_factory=dict, max_length=MAX_OUTCOMES)
    other: Target = None


class WaitStep(_Strict):
    id: StepId
    kind: Literal["wait"]
    minutes: int | None = Field(default=None, ge=1, le=WAIT_MAX_DAYS * 1440)
    hours: int | None = Field(default=None, ge=1, le=WAIT_MAX_DAYS * 24)
    days: int | None = Field(default=None, ge=1, le=WAIT_MAX_DAYS)
    until_field: FieldKey | None = None
    offset_days: int = Field(0, ge=-OFFSET_DAYS_MAX, le=OFFSET_DAYS_MAX)
    at: ClockTime | None = None
    next: Target = None


class TemplateValue(_Strict):
    """What fills one blank of a WhatsApp template."""

    source: Literal["lead_field", "lead_name", "agent_name", "business_name", "text"]
    key: FieldKey | None = None
    text: str | None = Field(default=None, max_length=MAX_TEXT_VALUE_CHARS)


class WhatsAppStep(_Strict):
    id: StepId
    kind: Literal["whatsapp"]
    template_id: UUID
    values: list[TemplateValue] = Field(default_factory=list, max_length=MAX_VALUES)
    next: SendExits = Field(default_factory=SendExits)


class AssignStep(_Strict):
    id: StepId
    kind: Literal["assign"]
    user_id: UUID
    next: Target = None


class SetStatusStep(_Strict):
    id: StepId
    kind: Literal["set_status"]
    status: SettableStatus
    next: Target = None


class TellTeamStep(_Strict):
    id: StepId
    kind: Literal["tell_team"]
    #: Null: the account's default team address.
    contact_id: UUID | None = None
    why: str = Field(min_length=1, max_length=MAX_WHY_CHARS)
    next: Target = None


class ActionStep(_Strict):
    id: StepId
    kind: Literal["action"]
    action_id: UUID
    next: ActionExits = Field(default_factory=ActionExits)


class EndStep(_Strict):
    id: StepId
    kind: Literal["end"]
    goal: bool = False


Step = Annotated[
    CallStep
    | DecideStep
    | WaitStep
    | WhatsAppStep
    | AssignStep
    | SetStatusStep
    | TellTeamStep
    | ActionStep
    | EndStep,
    Field(discriminator="kind"),
]
StepKind = Literal[
    "call", "decide", "wait", "whatsapp", "assign", "set_status", "tell_team", "action", "end"
]


class Settings(_Strict):
    #: An outcome key; a run whose `decide` lands on it, or an `end` with `goal`, reached it.
    goal: OutcomeKey | None = None
    stop_on_reply: bool = True
    stop_on_won_lost: bool = True
    again: Literal["never", "after_last", "after_30_days"] = "after_last"
    max_days: int = Field(MAX_DAYS_DEFAULT, ge=1, le=MAX_DAYS_CAP)
    #: At most this many runs start in any hour; the rest wait their turn.
    starts_per_hour: int | None = Field(default=None, ge=1, le=10_000)


STEPS: Final[TypeAdapter[list[Step]]] = TypeAdapter(list[Step])
TRIGGER: Final[TypeAdapter[Trigger]] = TypeAdapter(Trigger)
AnyTrigger = NewLeadTrigger | CallEndedTrigger | ManualTrigger | LeadDateTrigger
AnyStep = (
    CallStep
    | DecideStep
    | WaitStep
    | WhatsAppStep
    | AssignStep
    | SetStatusStep
    | TellTeamStep
    | ActionStep
    | EndStep
)


@dataclass(frozen=True, slots=True)
class Problem:
    """One thing that stops a publish. `step_id` is None for the trigger or settings."""

    step_id: str | None
    code: str
    message: str


# --- reading stored definitions --------------------------------------------------------


def load_steps(raw: Any) -> list[AnyStep]:
    """A stored step list (validated when it was written)."""
    return list(STEPS.validate_python(raw or []))


def load_trigger(raw: Any) -> AnyTrigger:
    return TRIGGER.validate_python(raw)


def load_settings(raw: Any) -> Settings:
    return Settings.model_validate(raw or {})


def dump_steps(steps: list[AnyStep]) -> list[dict[str, Any]]:
    return [step.model_dump(mode="json", exclude_none=False) for step in steps]


def dump_trigger(trigger: AnyTrigger) -> dict[str, Any]:
    return trigger.model_dump(mode="json")


def dump_settings(settings: Settings) -> dict[str, Any]:
    return settings.model_dump(mode="json")


_LOC_STEP = re.compile(r"^\d+$")


def parse_steps(raw: Any) -> tuple[list[AnyStep], list[Problem]]:
    """Steps from untyped input (Pip's draft), with every shape error as a `Problem`."""
    try:
        return load_steps(raw), []
    except ValidationError as exc:
        problems: list[Problem] = []
        items = raw if isinstance(raw, list) else []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", ())]
            step_id = None
            if loc and _LOC_STEP.match(loc[0]) and int(loc[0]) < len(items):
                item = items[int(loc[0])]
                step_id = str(item.get("id")) if isinstance(item, dict) else None
            where = ".".join(loc[1:]) or "step"
            problems.append(Problem(step_id, "step_invalid", f"{where}: {err.get('msg', '')}"))
        return [], problems or [Problem(None, "steps_invalid", "The steps could not be read.")]


# --- exits ----------------------------------------------------------------------------


def exits_of(step: AnyStep) -> dict[str, str | None]:
    """Every exit of a step and where it leads (None ends the run)."""
    if isinstance(step, CallStep | WhatsAppStep | ActionStep):
        return dict(step.next.model_dump())
    if isinstance(step, DecideStep):
        return {**step.on, "other": step.other}
    if isinstance(step, EndStep):
        return {}
    return {"next": step.next}


def step_by_id(steps: list[AnyStep], step_id: str) -> AnyStep | None:
    return next((s for s in steps if s.id == step_id), None)


def first_step(steps: list[AnyStep]) -> AnyStep | None:
    return steps[0] if steps else None


def _needs_a_call(step: AnyStep) -> bool:
    return isinstance(step, DecideStep | TellTeamStep | ActionStep)


def shape_problems(trigger: AnyTrigger, steps: list[AnyStep], settings: Settings) -> list[Problem]:
    """What is wrong with a definition before any database is asked."""
    problems: list[Problem] = []
    if not steps:
        return [Problem(None, "no_steps", "Add at least one step.")]
    if len(steps) > MAX_STEPS:
        problems.append(Problem(None, "too_many_steps", f"Use at most {MAX_STEPS} steps."))
    position: dict[str, int] = {}
    for index, step in enumerate(steps):
        if step.id in position:
            problems.append(Problem(step.id, "step_id_repeated", "Two steps share this id."))
        position.setdefault(step.id, index)
    call_before = isinstance(trigger, CallEndedTrigger)
    for index, step in enumerate(steps):
        for exit_name, target in exits_of(step).items():
            if target is None:
                continue
            if target not in position:
                problems.append(
                    Problem(step.id, "step_missing", f"'{exit_name}' leads to a step that is gone.")
                )
            elif position[target] <= index:
                problems.append(
                    Problem(
                        step.id,
                        "step_goes_back",
                        f"'{exit_name}' leads back to an earlier step. Steps only go forward.",
                    )
                )
        if _needs_a_call(step) and not call_before:
            problems.append(Problem(step.id, "needs_a_call", "Put a call step before this one."))
        if isinstance(step, CallStep):
            call_before = True
        if isinstance(step, WaitStep):
            given = [v for v in (step.minutes, step.hours, step.days) if v is not None]
            if len(given) + (step.until_field is not None) != 1:
                problems.append(
                    Problem(
                        step.id,
                        "wait_unclear",
                        "Say how long to wait, or which date on the lead to wait for.",
                    )
                )
            if step.until_field is None and step.at is not None:
                problems.append(
                    Problem(step.id, "wait_unclear", "A time of day goes with a date to wait for.")
                )
        if isinstance(step, WhatsAppStep):
            for value in step.values:
                if value.source == "lead_field" and value.key is None:
                    problems.append(
                        Problem(step.id, "value_unclear", "Choose which lead detail fills a blank.")
                    )
                if value.source == "text" and not (value.text or "").strip():
                    problems.append(
                        Problem(step.id, "value_unclear", "Write the text for a blank.")
                    )
        if isinstance(step, DecideStep) and not step.on:
            problems.append(Problem(step.id, "decide_empty", "Say which call outcomes lead where."))
    if settings.goal is not None and not any(
        settings.goal in step.on for step in steps if isinstance(step, DecideStep)
    ):
        problems.append(
            Problem(None, "goal_unused", "The goal must be an outcome one of the steps checks.")
        )
    return problems


# --- summaries ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Names:
    """Display names for the ids steps refer to. Missing ids read as a neutral word."""

    agents: dict[UUID, str]
    templates: dict[UUID, str]
    users: dict[UUID, str]
    actions: dict[UUID, str]


def _span(minutes: int) -> str:
    if minutes % 1440 == 0:
        days = minutes // 1440
        return "a day" if days == 1 else f"{days} days"
    if minutes % 60 == 0:
        hours = minutes // 60
        return "an hour" if hours == 1 else f"{hours} hours"
    return "a minute" if minutes == 1 else f"{minutes} minutes"


def _wait_s(seconds: int) -> str:
    if seconds == 0:
        return "straight away"
    if seconds < 60:
        return f"after {seconds} seconds"
    return f"after {_span(-(-seconds // 60))}"


_STATUS_WORDS: Final = {
    "contacted": "contacted",
    "interested": "interested",
    "hot": "hot",
    "won": "won",
    "lost": "lost",
}


def summary(step: AnyStep, names: Names) -> str:
    """One plain line the screen and Pip both show for a step."""
    if isinstance(step, CallStep):
        who = names.agents.get(step.agent_id, "your agent") if step.agent_id else "their agent"
        line = f"Call with {who} {_wait_s(step.wait_s)}"
        if step.retries:
            tries = step.retries + 1
            line += f", try {tries} times, {_span(step.retry_minutes)} apart"
        return line
    if isinstance(step, DecideStep):
        return "Check how the call went"
    if isinstance(step, WaitStep):
        if step.until_field is not None:
            side = "before" if step.offset_days < 0 else "after"
            when = "" if step.offset_days == 0 else f"{abs(step.offset_days)} day(s) {side} "
            return f"Wait until {when}the lead's {step.until_field.replace('_', ' ')}"
        minutes = (step.minutes or 0) + (step.hours or 0) * 60 + (step.days or 0) * 1440
        return f"Wait {_span(minutes)}"
    if isinstance(step, WhatsAppStep):
        return f'Send the WhatsApp "{names.templates.get(step.template_id, "message")}"'
    if isinstance(step, AssignStep):
        return f"Give the lead to {names.users.get(step.user_id, 'a teammate')}"
    if isinstance(step, SetStatusStep):
        return f"Mark the lead {_STATUS_WORDS[step.status]}"
    if isinstance(step, TellTeamStep):
        return f"Tell the team: {step.why}"
    if isinstance(step, ActionStep):
        return f'Run "{names.actions.get(step.action_id, "an action")}"'
    return "Finish (goal reached)" if step.goal else "Finish"


def clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


__all__ = [
    "MAX_STEPS",
    "ActionStep",
    "AnyStep",
    "AnyTrigger",
    "AssignStep",
    "CallEndedTrigger",
    "CallStep",
    "DecideStep",
    "EndStep",
    "LeadDateTrigger",
    "ManualTrigger",
    "Names",
    "NewLeadTrigger",
    "OnlyIf",
    "Problem",
    "SetStatusStep",
    "Settings",
    "Step",
    "TellTeamStep",
    "TemplateValue",
    "Trigger",
    "WaitStep",
    "WhatsAppStep",
    "clock",
    "dump_settings",
    "dump_steps",
    "dump_trigger",
    "exits_of",
    "first_step",
    "load_settings",
    "load_steps",
    "load_trigger",
    "parse_steps",
    "shape_problems",
    "step_by_id",
    "summary",
]
