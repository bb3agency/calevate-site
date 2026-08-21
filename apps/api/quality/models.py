"""The stored QA report and the QA call sample (migration d5b8a2c60e17).

Both are tenant-scoped and FORCE-RLS'd; the policies ship in that migration and the
coverage guardrail asserts they exist (`db/registry.TENANT_TABLES`).
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TenantMixin, TimestampMixin

#: What a reviewer can conclude about a sampled call. An enum, never free text: this
#: queue is read across tenants and an operator's prose can carry anything into it
#: (hard rule 6, the argument `admin/holds.py` makes about rejection reasons).
#:
#: The TYPE lives here beside the tuple rather than in `sampling_routes.py`, where it was
#: a second spelling of the same three strings. One of the two drove the DB CHECK and the
#: other drove the API model, nothing tied them together, and widening either alone was a
#: silent bug in whichever direction it went. `QA_VERDICTS` is now annotated WITH it, so
#: the tuple that builds the constraint cannot hold a value the Literal does not name.
Verdict = Literal["clean", "concern", "defect"]
QA_VERDICTS: tuple[Verdict, ...] = ("clean", "concern", "defect")

#: 5% of calls per client per week (SURFACES §1). One definition, read by the weekly
#: job that draws the sample and by the queue that explains it.
QA_SAMPLE_RATE = 0.05


class QaReport(PKMixin, TenantMixin, TimestampMixin, Base):
    """One monthly report, as COMPUTED — the CLI writes it, the client's screen reads it.

    `data` is `calevate_shared.qa_report.QaReport`, which is the single computation the
    Markdown is also rendered from. The Markdown is deliberately NOT stored beside it:
    two representations of one document is a chance for them to disagree.
    """

    __tablename__ = "qa_reports"
    __table_args__ = (
        # One report per month per vertical; a regeneration replaces it (the document is
        # a pure function of its inputs, so a second run is the same document).
        UniqueConstraint("tenant_id", "as_of", "vertical", name="tenant_month_vertical"),
    )

    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    vertical: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(nullable=False)


class QaCallSample(PKMixin, TenantMixin, TimestampMixin, Base):
    """One call drawn for the weekly spot-check, and what a reviewer concluded.

    The columns that make the draw defensible are `population`, `target`,
    `selection_rank` and `selection_seed`: together they are the whole answer to "why
    this call and not that one", recomputable by anyone with the seed and one `md5()`.
    """

    __tablename__ = "qa_call_samples"
    __table_args__ = (
        # THE no-re-sampling guarantee — the weekly job inserts ON CONFLICT DO NOTHING.
        UniqueConstraint("tenant_id", "call_id", name="tenant_call"),
        CheckConstraint(f"verdict IS NULL OR verdict IN {QA_VERDICTS!r}", name="verdict_enum"),
        CheckConstraint(
            "(verdict IS NULL AND reviewed_at IS NULL AND reviewed_by_admin_id IS NULL) "
            "OR (verdict IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND reviewed_by_admin_id IS NOT NULL)",
            name="review_is_complete_or_absent",
        ),
        CheckConstraint(
            "selection_rank >= 1 AND selection_rank <= target AND target <= population",
            name="draw_fits_its_frame",
        ),
    )

    # CASCADE: an erasure or a retention sweep must never be blocked by a work list.
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    population: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_seed: Mapped[str] = mapped_column(String, nullable=False)
    selected_at: Mapped[datetime] = mapped_column(nullable=False)
    verdict: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column()
    reviewed_by_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
