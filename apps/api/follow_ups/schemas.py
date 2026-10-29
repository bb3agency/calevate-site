"""The HTTP shapes of `/v1/follow-ups` (docs/FOLLOW-UPS.md, HTTP contract). The response
models are the output whitelist: ids, names, counts and short codes, never a phone number."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.crm.schemas import LeadLensIn
from apps.api.follow_ups import definition as d
from apps.api.follow_ups.models import MAX_NAME_CHARS

FollowUpStatus = Literal["draft", "live", "paused", "off"]
RunStatus = Literal["running", "waiting", "done", "stopped"]
StarterKey = Literal[
    "call_new_leads",
    "qualify_new_leads",
    "missed_call_callback",
    "appointment_reminder",
    "payment_reminder",
    "win_back",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Every step in an answer also carries `summary`, one plain line the screen and Pip show.


class CallStepOut(d.CallStep):
    summary: str


class DecideStepOut(d.DecideStep):
    summary: str


class WaitStepOut(d.WaitStep):
    summary: str


class WhatsAppStepOut(d.WhatsAppStep):
    summary: str


class AssignStepOut(d.AssignStep):
    summary: str


class SetStatusStepOut(d.SetStatusStep):
    summary: str


class TellTeamStepOut(d.TellTeamStep):
    summary: str


class ActionStepOut(d.ActionStep):
    summary: str


class EndStepOut(d.EndStep):
    summary: str


StepOut = Annotated[
    CallStepOut
    | DecideStepOut
    | WaitStepOut
    | WhatsAppStepOut
    | AssignStepOut
    | SetStatusStepOut
    | TellTeamStepOut
    | ActionStepOut
    | EndStepOut,
    Field(discriminator="kind"),
]


class ProblemOut(_Strict):
    #: Null: the problem is with the trigger or the settings.
    step_id: str | None
    code: str
    message: str


class LiveVersionOut(_Strict):
    number: int
    published_at: datetime


class CountsOut(_Strict):
    running: int
    waiting: int
    done_30d: int
    goal_30d: int


class FollowUpOut(_Strict):
    id: UUID
    name: str
    status: FollowUpStatus
    starter: StarterKey | None
    trigger: d.Trigger
    settings: d.Settings
    #: The draft if there is one, else the live version's steps.
    steps: list[StepOut]
    has_unpublished_changes: bool
    live_version: LiveVersionOut | None
    counts: CountsOut
    problems: list[ProblemOut]
    updated_at: datetime


class FollowUpSummaryOut(_Strict):
    id: UUID
    name: str
    status: FollowUpStatus
    starter: StarterKey | None
    trigger: d.Trigger
    #: What starts it, as one plain line.
    starts_when: str
    has_unpublished_changes: bool
    counts: CountsOut
    updated_at: datetime


class FollowUpListOut(_Strict):
    items: list[FollowUpSummaryOut]


class FollowUpCreateIn(_Strict):
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    trigger: d.Trigger
    steps: list[d.Step] = Field(min_length=1, max_length=d.MAX_STEPS)
    settings: d.Settings | None = None
    starter: StarterKey | None = None


class WaitEditIn(_Strict):
    """A new wait: one of minutes, hours or days."""

    minutes: int | None = Field(default=None, ge=0, le=d.WAIT_MAX_DAYS * 1440)
    hours: int | None = Field(default=None, ge=0, le=d.WAIT_MAX_DAYS * 24)
    days: int | None = Field(default=None, ge=0, le=d.WAIT_MAX_DAYS)

    def total_minutes(self) -> int:
        return (self.minutes or 0) + (self.hours or 0) * 60 + (self.days or 0) * 1440


class StepEditIn(_Strict):
    step_id: str = Field(min_length=1, max_length=16)
    wait: WaitEditIn | None = None
    template_id: UUID | None = None
    values: list[d.TemplateValue] | None = Field(default=None, max_length=d.MAX_VALUES)
    agent_id: UUID | None = None
    remove: bool = False


class FollowUpEditIn(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_CHARS)
    step_edits: list[StepEditIn] | None = Field(default=None, max_length=d.MAX_STEPS)
    settings: d.Settings | None = None


class FollowUpDraftIn(_Strict):
    trigger: d.Trigger
    steps: list[d.Step] = Field(min_length=1, max_length=d.MAX_STEPS)
    settings: d.Settings


class FollowUpPublishIn(_Strict):
    expected_updated_at: datetime


class FollowUpStartIn(_Strict):
    lead_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=200)
    lens: LeadLensIn | None = None
    expected_count: int | None = Field(default=None, ge=0)


class FollowUpStartOut(_Strict):
    started: int
    skipped: int
    plan_id: UUID | None = None


class RunEventOut(_Strict):
    step_id: str
    kind: str
    result: str
    at: datetime
    call_id: UUID | None


class FollowUpRunOut(_Strict):
    id: UUID
    lead_id: UUID | None
    lead_name: str | None
    status: RunStatus
    step_id: str
    #: The current step as one plain line, when the step still exists in its version.
    step_summary: str | None
    attempt: int
    #: When a waiting run is next due (a wait ending); null while it waits on a call.
    wake_at: datetime | None
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    goal_reached: bool
    last_result: str | None
    #: Only on `GET .../runs/{run_id}`.
    events: list[RunEventOut] | None = None


class FollowUpRunsOut(_Strict):
    items: list[FollowUpRunOut]
    next_cursor: str | None


class StepResultOut(_Strict):
    step_id: str
    reached: int
    exits: dict[str, int]


class FollowUpResultsOut(_Strict):
    days: int
    started: int
    finished: int
    goal_reached: int
    steps: list[StepResultOut]


class FollowUpStarterOut(_Strict):
    key: StarterKey
    name: str
    description: str
    trigger: d.Trigger
    steps: list[StepOut]
    settings: d.Settings
    #: False when the account already has it (only "Call new leads" is one per account).
    available: bool
    #: What the account still has to set up for it to publish (an approved WhatsApp
    #: message, an agent that calls, a team address). Empty when it can publish as it is.
    needs: list[Literal["outbound_agent", "whatsapp_template", "team_address"]]


class FollowUpStartersOut(_Strict):
    items: list[FollowUpStarterOut]


__all__ = [
    "FollowUpCreateIn",
    "FollowUpDraftIn",
    "FollowUpEditIn",
    "FollowUpListOut",
    "FollowUpOut",
    "FollowUpPublishIn",
    "FollowUpResultsOut",
    "FollowUpRunOut",
    "FollowUpRunsOut",
    "FollowUpStartIn",
    "FollowUpStartOut",
    "FollowUpStartersOut",
    "FollowUpSummaryOut",
    "StepEditIn",
    "StepOut",
]
