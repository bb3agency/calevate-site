"""The first run's rows and its vocabulary (D-855, migration f8d2a6c4b1e7).

One `first_runs` row per client holds where the owner is in "Meet your agent"; one
`first_run_recordings` row per spoken piece of the brief. The states are closed sets the
migration's CHECKs spell too.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal, get_args
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

QuestionsStatus = Literal["idle", "writing", "ready", "failed"]
QUESTIONS_STATES: Final[tuple[QuestionsStatus, ...]] = get_args(QuestionsStatus)

BuildStatus = Literal["idle", "building", "built", "failed"]
BUILD_STATES: Final[tuple[BuildStatus, ...]] = get_args(BuildStatus)

RecordingStatus = Literal["queued", "hearing", "heard", "failed"]
RECORDING_STATES: Final[tuple[RecordingStatus, ...]] = get_args(RecordingStatus)

#: The build's steps in the order the worker takes them. The voice comes first because the
#: agent's name is suggested to suit the voice, and the agent is created with its name.
BuildStep = Literal["voice", "script", "greeting", "notice"]
BUILD_STEPS: Final[tuple[BuildStep, ...]] = get_args(BuildStep)

#: The jobs, as `agents/starters.STARTER_JOBS` spells them (the migration's CHECK too).
FIRST_RUN_JOBS: Final = ("answer_calls", "call_new_leads", "call_leads")

#: The brief: long enough for a few paragraphs, short enough to stay one model prompt.
MAX_BRIEF_CHARS: Final = 4000
#: Below this the brief says nothing the ready-made script does not, so the build keeps the
#: ready-made script and asks no model.
MIN_BRIEF_CHARS: Final = 20
#: Up to three spoken pieces of 30 s each (founder, 23 Oct 2026).
MAX_RECORDINGS: Final = 3
MAX_RECORDING_WORDS: Final = 2000
#: How often the model may be asked per first run, each way. A bound on our cost: the owner
#: can still edit everything on the agent's own page afterwards.
MAX_QUESTION_RUNS: Final = 3
MAX_BUILD_RUNS: Final = 3

#: The four questions at most that follow the brief (D-863).
MAX_QUESTIONS: Final = 4

#: One agent does every job picked, so at most all three (D-863).
MAX_JOBS: Final = len(FIRST_RUN_JOBS)

_JOBS_SQL: Final = f"job IS NULL OR job IN {FIRST_RUN_JOBS!r}"
_JOBS_ARRAY_SQL: Final = (
    "jobs <@ ARRAY["
    + ", ".join(f"'{job}'" for job in FIRST_RUN_JOBS)
    + f"]::text[] AND cardinality(jobs) <= {MAX_JOBS}"
)


class FirstRun(PKMixin, TimestampMixin, Base):
    """Where one client's owner is in "Meet your agent", and the agent it built."""

    __tablename__ = "first_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_first_runs_tenant"),
        CheckConstraint(_JOBS_SQL, name="job_enum"),
        CheckConstraint(_JOBS_ARRAY_SQL, name="jobs_enum"),
        CheckConstraint("jsonb_typeof(answers) = 'array'", name="answers_is_array"),
        CheckConstraint(f"questions_status IN {QUESTIONS_STATES!r}", name="questions_status_enum"),
        CheckConstraint(f"build_status IN {BUILD_STATES!r}", name="build_status_enum"),
        CheckConstraint("jsonb_typeof(questions) = 'array'", name="questions_is_array"),
        CheckConstraint("jsonb_typeof(build_steps) = 'object'", name="build_steps_is_object"),
        CheckConstraint(
            f"brief IS NULL OR char_length(brief) <= {MAX_BRIEF_CHARS}", name="brief_length"
        ),
        CheckConstraint("question_runs >= 0 AND build_runs >= 0", name="runs_not_negative"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    #: Read by the release before D-863 only; nothing writes it now. Dropped in the release
    #: after (hard rule 8's two steps).
    job: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The jobs picked, in the order the owner sees them; one agent does them all (D-863).
    jobs: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    language_primary: Mapped[str | None] = mapped_column(Text, nullable=True)
    languages_extra: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    #: The owner's own description of the agent's work, typed or spoken.
    brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    questions_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="idle")
    #: The questions as asked, in order (`questions.Question.stored`); a row from before
    #: D-863 holds `[{"key": <ProfileTopic>}]` (`questions.legacy_questions`).
    questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    #: Each answer the owner gave, with its question's words (`service.StoredAnswer`), for
    #: the script writer.
    answers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    #: The fallback model's disclosure (D-127 G-6), when another model wrote them.
    questions_disclosure: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: sha256 of the brief the questions were written from, so an unchanged brief is not
    #: sent to the model twice.
    questions_brief_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_runs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    build_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="idle")
    #: `{step: {"state": "done" | "kept" | "skipped", ...}}` as each step lands.
    build_steps: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    build_disclosure: Mapped[str | None] = mapped_column(Text, nullable=True)
    build_runs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    build_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FirstRunRecording(PKMixin, TimestampMixin, Base):
    """One spoken piece of the brief: its audio until heard, then only its words."""

    __tablename__ = "first_run_recordings"
    __table_args__ = (
        CheckConstraint(f"status IN {RECORDING_STATES!r}", name="status_enum"),
        CheckConstraint(
            f"words IS NULL OR char_length(words) <= {MAX_RECORDING_WORDS}", name="words_length"
        ),
        Index("ix_first_run_recordings_run", "first_run_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    first_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("first_runs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    #: The language the owner speaks it in, sent to speech-to-text as a hint.
    language: Mapped[str] = mapped_column(Text, nullable=False)
    #: The audio's object key until the worker has heard it and deleted the audio.
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    words: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "BUILD_STATES",
    "BUILD_STEPS",
    "FIRST_RUN_JOBS",
    "MAX_BRIEF_CHARS",
    "MAX_BUILD_RUNS",
    "MAX_JOBS",
    "MAX_QUESTIONS",
    "MAX_QUESTION_RUNS",
    "MAX_RECORDINGS",
    "MAX_RECORDING_WORDS",
    "MIN_BRIEF_CHARS",
    "QUESTIONS_STATES",
    "RECORDING_STATES",
    "BuildStatus",
    "BuildStep",
    "FirstRun",
    "FirstRunRecording",
    "QuestionsStatus",
    "RecordingStatus",
]
