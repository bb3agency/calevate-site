"""What "Meet your agent" sends and reads (D-855). The response models are the whitelist."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.agents.languages import OfferedLanguage
from apps.api.agents.starters import StarterJob
from apps.api.first_run.models import MAX_BRIEF_CHARS, MAX_RECORDINGS
from apps.api.first_run.questions import AnswerKind, QuestionKey
from apps.api.tenancy.business_profile import ServiceItem

_HHMM = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionOut(Strict):
    key: QuestionKey
    prompt: str
    hint: str
    kind: AnswerKind
    #: The choices of a `choices` question; empty otherwise.
    options: list[str]


class QuestionsOut(Strict):
    #: `idle` (no brief yet) · `writing` · `ready` · `failed`.
    status: str
    items: list[QuestionOut]
    #: The fallback model's disclosure when it chose them (D-127 G-6).
    disclosure: str | None


class BuildStepOut(Strict):
    step: Literal["voice", "script", "greeting", "notice"]
    #: `waiting` until the worker reaches it; then `done`, `ready_made` (the ready-made
    #: version was kept), `kept` (what it had stays), `none` (no voice could be chosen) or
    #: `missing`.
    state: str
    #: The chosen voice's name, on the voice step.
    label: str | None
    #: The chosen voice's rung, on the voice step: `studio` first, `clear` when Studio cannot
    #: be used here (D-855).
    rung: Literal["clear", "studio"] | None = None
    #: Why a Clear voice stands in for Studio: `studio_unavailable`, `studio_minutes_used`
    #: (the trial's Studio test minutes are used), `no_studio_voice` or
    #: `no_female_studio_voice` (Studio has no woman's voice for the language). Null otherwise.
    fallback: (
        Literal[
            "studio_unavailable", "studio_minutes_used", "no_studio_voice", "no_female_studio_voice"
        ]
        | None
    ) = None
    #: No woman's voice could be chosen for "Anjali", so the voice step kept the best one.
    not_female: bool = False


class BuildOut(Strict):
    #: `idle` · `building` · `built` · `failed`.
    status: str
    steps: list[BuildStepOut]
    disclosure: str | None
    #: How many more builds this screen allows.
    builds_left: int


class FirstRunOut(Strict):
    #: Is this account's owner still on their first run? The sign-in junction sends them here
    #: while it is.
    due: bool
    job: StarterJob | None
    language_primary: str | None
    languages_extra: list[str]
    brief: str | None
    agent_id: UUID | None
    questions: QuestionsOut
    build: BuildOut
    recordings_left: int = Field(ge=0, le=MAX_RECORDINGS)
    finished_at: datetime | None
    dismissed_at: datetime | None


class JobIn(Strict):
    job: StarterJob
    language_primary: OfferedLanguage
    #: The languages it also speaks, after the main one.
    languages_extra: list[OfferedLanguage] = Field(default_factory=list, max_length=3)


class BriefIn(Strict):
    brief: str = Field(max_length=MAX_BRIEF_CHARS)


class HoursIn(Strict):
    opens: str = Field(pattern=_HHMM)
    closes: str = Field(pattern=_HHMM)
    closed: list[Day] = Field(default_factory=list, max_length=7)


class AnswersIn(Strict):
    """The follow-up answers the owner gave. A question skipped is simply left out."""

    trade: list[str] = Field(default_factory=list, max_length=12)
    location: str | None = Field(default=None, min_length=1, max_length=400)
    offer: list[ServiceItem] = Field(default_factory=list, max_length=20)
    hours: HoursIn | None = None
    booking: str | None = Field(default=None, min_length=1, max_length=2000)


class NameIn(Strict):
    name: str = Field(min_length=1, max_length=60)


class RecordingOut(Strict):
    id: UUID
    #: `queued` · `hearing` · `heard` · `failed`.
    status: str
    words: str | None
    #: Why it failed: `voice_unreadable`, `nothing_heard`, `upload_missing`, `crashed`.
    error_code: str | None


__all__ = [
    "AnswersIn",
    "BriefIn",
    "BuildOut",
    "BuildStepOut",
    "FirstRunOut",
    "HoursIn",
    "JobIn",
    "NameIn",
    "QuestionOut",
    "QuestionsOut",
    "RecordingOut",
]
