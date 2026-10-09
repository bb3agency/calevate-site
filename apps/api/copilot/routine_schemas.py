"""The wire shapes of the assistant workspace's own routes: routines and approval previews."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.copilot.routine_models import MAX_ROUTINE_INSTRUCTION, MAX_ROUTINE_NAME
from apps.api.copilot.routines import Weekday

#: "HH:MM", 24-hour, IST.
_CLOCK = r"^([01]\d|2[0-3]):[0-5]\d$"


class CopilotRoutineSchedule(BaseModel):
    """When a routine runs: on these days, at this time, in India's time."""

    model_config = ConfigDict(extra="forbid")

    days: Annotated[list[Weekday], Field(min_length=1, max_length=7)]
    time: Annotated[str, Field(pattern=_CLOCK, description="24-hour HH:MM, IST.")]

    @field_validator("days")
    @classmethod
    def _distinct(cls, days: list[Weekday]) -> list[Weekday]:
        if len(set(days)) != len(days):
            raise ValueError("each day may appear once")
        return days


class CopilotRoutineIn(BaseModel):
    """`POST /v1/copilot/routines`."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=MAX_ROUTINE_NAME)]
    instruction: Annotated[str, Field(min_length=1, max_length=MAX_ROUTINE_INSTRUCTION)]
    schedule: CopilotRoutineSchedule
    enabled: bool = True


class CopilotRoutinePatch(BaseModel):
    """`PATCH /v1/copilot/routines/{id}` — only what is sent changes."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=1, max_length=MAX_ROUTINE_NAME)] = None
    instruction: Annotated[str | None, Field(min_length=1, max_length=MAX_ROUTINE_INSTRUCTION)] = (
        None
    )
    schedule: CopilotRoutineSchedule | None = None
    enabled: bool | None = None


class CopilotRoutineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    #: As stored: redacted on write, so a number typed into it reads as a placeholder.
    instruction: str
    schedule: CopilotRoutineSchedule
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CopilotRoutinePageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routines: list[CopilotRoutineOut] = []


class CopilotRoutineRunOut(BaseModel):
    """One run of a routine: the task it queued, or why it was skipped."""

    model_config = ConfigDict(extra="forbid")

    id: str
    routine_id: str
    slot_at: datetime
    trigger: Literal["schedule", "manual"]
    status: Literal["queued", "skipped"]
    reason: str | None
    job_id: str | None
    #: The task's own state now (`queued`, `running`, `done`, `failed`, `cancelled`), or
    #: None when no task was queued or it has since been erased.
    job_status: str | None
    created_at: datetime


class CopilotRoutineRunPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[CopilotRoutineRunOut] = []


class CopilotApprovalPreviewOut(BaseModel):
    """What approving one waiting action would do NOW — the planner's own reading.

    `still_applies` is False when the step would be refused (it was decided, it expired, the
    person's role does not allow it, or the world changed), and `refusal` then says why.
    """

    model_config = ConfigDict(extra="forbid")

    action_id: str
    tool: str
    object_type: str
    title: str
    summary: str
    current: str | None = None
    proposed: str | None = None
    #: What it costs, in a sentence; None means it costs nothing.
    cost: str | None = None
    #: Whether and how it can be taken back. Never softened.
    reversal: str | None = None
    still_applies: bool
    refusal: str | None
    expires_at: datetime
