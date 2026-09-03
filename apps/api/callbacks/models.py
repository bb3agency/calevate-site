"""The promise an agent made on a call, as a row (D-510, migration d8f31a7c2409).

DECLARED HERE AND QUERIED IN SQL, which is the seam this repo already uses for
state-machine tables: `callbacks/service.py` writes every statement by hand because the
claim is a `FOR UPDATE SKIP LOCKED` CTE and the upsert is guarded by `booked_at`, neither
of which the ORM expresses without fighting it. The model earns its place anyway — it is
what puts `scheduled_callbacks` in `Base.metadata`, which is what `check_rls_coverage`
reads to prove the table carries `tenant_id` and the FORCEd `tenant_isolation` policy
(hard rule 1), and what alembic's autogenerate compares a future migration against.

`STATUSES` is the vocabulary, and it is spelled ONCE here rather than beside the CHECK in
the migration and again in the service: the migration froze what the schema accepted on
the day (that tree's discipline), and this is what the running code means by it.
`callbacks/service.TERMINAL_STATUSES` is the subset that ends a promise, derived rather
than retyped, so "which endings exist" cannot come to have two answers.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: Every state a promise can be in. The first two are live; the other five are endings.
#: Annotated for `crm/models.CALL_STATUSES`' reason — an invented member here would be a
#: CHECK the service has no sentence for.
STATUSES: tuple[str, ...] = (
    "scheduled",
    "dialing",
    "completed",
    "cancelled",
    "refused",
    "missed",
    "failed",
)


class ScheduledCallback(PKMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_callbacks"
    __table_args__ = (
        CheckConstraint(
            "status IN " + str(STATUSES),
            name="ck_scheduled_callbacks_status",
        ),
        # A settled row names its ending, and an unsettled one does not claim to have one.
        CheckConstraint(
            "(status IN ('scheduled', 'dialing')) = (settled_at IS NULL)",
            name="ck_scheduled_callbacks_settled",
        ),
        # THE IDENTITY: one live promise per conversation, per tenant. The upsert key —
        # see the migration, which argues why it is the execution and not the call.
        Index(
            "uq_scheduled_callbacks_execution",
            "tenant_id",
            "source_execution_id",
            unique=True,
        ),
        Index(
            "ix_scheduled_callbacks_due",
            "tenant_id",
            "requested_at",
            "next_attempt_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
        Index(
            "ix_scheduled_callbacks_phone",
            "tenant_id",
            "phone_e164",
            postgresql_where=text("status IN ('scheduled', 'dialing')"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: WHICH agent rings back — the one the caller was speaking to, resolved from the
    #: execution by the booking worker and never taken from the tool payload (D-31).
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    #: The call the promise was made ON. A POINTER, not the identity: the `calls` row is
    #: written by the status webhook and may not have arrived when this is booked.
    source_call_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    #: The engine's id for that conversation. THE IDENTITY — NOT NULL, unique per tenant.
    source_execution_id: Mapped[str] = mapped_column(Text, nullable=False)
    lead_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL")
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    #: THE PROMISE, UTC (repo convention: timestamptz UTC in the DB, IST at the edge).
    #: It is what the caller was told and it never moves — a transient refusal defers
    #: `next_attempt_at` instead, which is the livelock the migration records.
    requested_at: Mapped[datetime] = mapped_column(nullable=False)
    #: When the caller asked. The upsert's ordering guard, so two bookings in one
    #: conversation land on the caller's LATER word whichever job commits first.
    booked_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="scheduled")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column()
    #: The gate's OWN rule name and OWN sentence for the last refusal. The rule is for the
    #: metric and the runbook; the sentence is what the client reads on their screen.
    last_refusal_rule: Mapped[str | None] = mapped_column(Text)
    last_refusal_reason: Mapped[str | None] = mapped_column(Text)
    last_call_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    settled_at: Mapped[datetime | None] = mapped_column()
    #: What the caller said they wanted the call about, in the agent's own short words.
    #: Bounded where it enters (`callbacks/service.MAX_NOTE`) and spoken back to the agent
    #: on the call-back, so the dial arrives knowing what it is for.
    note: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)


__all__ = ["STATUSES", "ScheduledCallback"]
