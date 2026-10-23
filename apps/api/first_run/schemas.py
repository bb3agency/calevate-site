"""What "Meet your agent" sends and reads (D-855). The response models are the whitelist."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.agents.languages import OfferedLanguage
from apps.api.agents.starters import StarterJob
from apps.api.first_run.models import MAX_BRIEF_CHARS, MAX_JOBS, MAX_QUESTIONS, MAX_RECORDINGS
from apps.api.first_run.questions import MAX_OPTIONS, ProfileTopic, QuestionKind
from apps.api.tenancy.business_profile import ServiceItem

_HHMM = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionOut(Strict):
    #: `q1`.. in the order asked; an answer names its question by it.
    id: str
    prompt: str
    hint: str
    #: `choices` = tick all that apply; `single_choice` = pick one.
    kind: QuestionKind
    #: The choices of a `choices` or `single_choice` question; empty otherwise.
    options: list[str]
    #: The business-profile section the answer is saved into, or null when it only informs
    #: the script.
    maps_to: ProfileTopic | None


class QuestionsOut(Strict):
    #: `idle` (no brief yet) · `writing` · `ready` · `failed`.
    status: str
    items: list[QuestionOut]
    #: The fallback model's disclosure when it chose them (D-127 G-6).
    disclosure: str | None


class BuildStepOut(Strict):
    step: Literal["voice", "script", "greeting", "notice"]
    #: `waiting` until the worker reaches it; then `done`, `ready_made` (the ready-made
    #: version was kept), `kept` (what it had stays), `none` (no voice could be chosen),
    #: `missing`, and on the notice step `off` (the owner switched the AI notice off) or
    #: `no_room` (the greeting leaves no room for it within the engine's limit).
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
    #: The jobs picked, in the order chosen; one agent does them all. Empty until chosen.
    jobs: list[StarterJob]
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
    #: One to three jobs, each once, in the order the owner sees them.
    jobs: list[StarterJob] = Field(min_length=1, max_length=MAX_JOBS)
    language_primary: OfferedLanguage
    #: The languages it also speaks, after the main one.
    languages_extra: list[OfferedLanguage] = Field(default_factory=list, max_length=3)

    @field_validator("jobs")
    @classmethod
    def _each_job_once(cls, value: list[StarterJob]) -> list[StarterJob]:
        if len(set(value)) != len(value):
            raise ValueError("pick each job once")
        return value


class BriefIn(Strict):
    brief: str = Field(max_length=MAX_BRIEF_CHARS)


class HoursIn(Strict):
    opens: str = Field(pattern=_HHMM)
    closes: str = Field(pattern=_HHMM)
    closed: list[Day] = Field(default_factory=list, max_length=7)


class AnswerIn(Strict):
    """One answer, in the field its question's kind uses: `choices` for `choices` and
    `single_choice` (exactly one), `text` for `text` and `address`, `services`, `hours`."""

    id: str = Field(min_length=1, max_length=8)
    choices: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    services: list[ServiceItem] = Field(default_factory=list, max_length=20)
    hours: HoursIn | None = None


class AnswersIn(Strict):
    """The follow-up answers the owner gave. A question skipped is simply left out."""

    answers: list[AnswerIn] = Field(default_factory=list, max_length=MAX_QUESTIONS)

    @field_validator("answers")
    @classmethod
    def _one_answer_per_question(cls, value: list[AnswerIn]) -> list[AnswerIn]:
        if len({a.id for a in value}) != len(value):
            raise ValueError("answer each question once")
        return value


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
    "AnswerIn",
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
