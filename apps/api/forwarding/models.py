"""The forwarding tables (migration `d6f2b8a41c73`, D-746), declared so `Base.metadata` is
complete. The migration is the schema of record.

`forwarded_lines` and `forwarding_tests` are the client's own records and FORCE-RLS'd.
`forwarding_test_legs` is platform machinery: the legs ring from the shared trial number in
our developer workspace, so a free-trial call and a forwarding test must see each other's
live legs across clients under one lock, and the voice platform's report of a leg arrives
before any tenant is known. It holds ids, a vendor call id and seconds, never a number.

A test is a CAS-updated row rather than an append-only history: it moves through
`placing -> ringing -> settled | failed`, and each run is also written to `audit_log`, which
is the immutable record (BACKEND-PATTERNS §5).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

LINE_KINDS: Final = ("mobile", "landline", "office_system")
CARRIERS: Final = ("airtel", "jio", "vi", "bsnl", "other")
#: `conditional`: the phone rings first and the agent takes unanswered, busy and unreachable
#: calls (set once). `all_calls`: every call goes straight to the agent.
MODES: Final = ("conditional", "all_calls")
#: The GSM no-reply timer: 5 to 30 seconds in steps of 5 (3GPP TS 22.082 §3.3.3).
RING_SECONDS: Final = (5, 10, 15, 20, 25, 30)
DEFAULT_RING_SECONDS: Final = 20
LINE_STATUSES: Final = ("untested", "testing", "working", "not_working")
#: Which number arrived on the Calevate number when our test call was forwarded.
CALLER_ID_FINDINGS: Final = ("caller_shown", "business_number_shown", "other_number_shown")
CONCURRENCY_FINDINGS: Final = ("both_arrived", "one_arrived", "not_tested")
TEST_STATUSES: Final = ("placing", "ringing", "settled", "failed")
TEST_OUTCOMES: Final = ("arrived", "not_arrived", "answered_on_phone", "not_placed")
LEG_STATUSES: Final = ("placing", "live", "ended", "failed")
SAVE_NUMBER_STATUSES: Final = ("queued", "sent", "refused", "failed")
#: How many published numbers one client may record. A business advertises one or two.
MAX_LINES: Final = 5


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ForwardedLine(PKMixin, TimestampMixin, Base):
    """A number the client already publishes, forwarded by its carrier to its Calevate number."""

    __tablename__ = "forwarded_lines"
    __table_args__ = (
        CheckConstraint(r"e164 ~ '^\+91[0-9]{10}$'", name="e164_india"),
        CheckConstraint(_in("line_kind", LINE_KINDS), name="line_kind_enum"),
        CheckConstraint(_in("carrier", CARRIERS), name="carrier_enum"),
        CheckConstraint(_in("mode", MODES), name="mode_enum"),
        CheckConstraint(
            "(mode = 'all_calls' AND ring_seconds = 0) OR (mode = 'conditional' "
            "AND ring_seconds BETWEEN 5 AND 30 AND ring_seconds % 5 = 0)",
            name="ring_seconds_fit_mode",
        ),
        CheckConstraint(_in("status", LINE_STATUSES), name="status_enum"),
        CheckConstraint(
            "caller_id_finding IS NULL OR " + _in("caller_id_finding", CALLER_ID_FINDINGS),
            name="caller_id_finding_enum",
        ),
        CheckConstraint(
            "concurrency_finding IS NULL OR " + _in("concurrency_finding", CONCURRENCY_FINDINGS),
            name="concurrency_finding_enum",
        ),
        CheckConstraint("(quiet_alerted_at IS NULL) OR (quiet_since IS NOT NULL)", name="quiet"),
        UniqueConstraint("tenant_id", "e164"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: The business's own published number, never a caller's.
    e164: Mapped[str] = mapped_column(String(16), nullable=False)
    line_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    carrier: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    ring_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    #: The client's Calevate number the forward points at.
    calevate_number_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("phone_numbers.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="untested")
    #: A `users.id`: the person who confirmed the number belongs to the business.
    attested_by: Mapped[UUID | None]
    attested_at: Mapped[datetime] = mapped_column(nullable=False)
    last_test_id: Mapped[UUID | None]
    last_tested_at: Mapped[datetime | None]
    caller_id_finding: Mapped[str | None] = mapped_column(String(24))
    concurrency_finding: Mapped[str | None] = mapped_column(String(16))
    #: Set when inbound calls stopped on a line that normally gets them; cleared by a call.
    quiet_since: Mapped[datetime | None]
    quiet_alerted_at: Mapped[datetime | None]


class ForwardingTest(PKMixin, TimestampMixin, Base):
    """One run of the verification call: one or two legs from our side to the published number."""

    __tablename__ = "forwarding_tests"
    __table_args__ = (
        CheckConstraint(_in("status", TEST_STATUSES), name="status_enum"),
        CheckConstraint("outcome IS NULL OR " + _in("outcome", TEST_OUTCOMES), name="outcome_enum"),
        CheckConstraint(
            "caller_id_finding IS NULL OR " + _in("caller_id_finding", CALLER_ID_FINDINGS),
            name="caller_id_finding_enum",
        ),
        CheckConstraint(
            "concurrency_finding IS NULL OR " + _in("concurrency_finding", CONCURRENCY_FINDINGS),
            name="concurrency_finding_enum",
        ),
        CheckConstraint("legs_placed BETWEEN 0 AND 2", name="legs_placed_range"),
        CheckConstraint(
            "(status IN ('settled', 'failed')) = (settled_at IS NOT NULL)", name="settled_iff"
        ),
        Index("ix_forwarding_tests_tenant_recent", "tenant_id", text("created_at DESC")),
        Index(
            "ix_forwarding_tests_open",
            "tenant_id",
            postgresql_where=text("status IN ('placing', 'ringing')"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    line_id: Mapped[UUID] = mapped_column(
        ForeignKey("forwarded_lines.id", ondelete="CASCADE"), nullable=False
    )
    #: A `users.id`, or NULL when an operator ran it from the client's account.
    requested_by: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="placing")
    outcome: Mapped[str | None] = mapped_column(String(24))
    legs_placed: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    #: Inbound calls the caller lookup saw arrive, by the platform's call id.
    lookup_arrivals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    #: Inbound `calls` rows the post-call pipeline matched to this test.
    call_arrivals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    caller_id_finding: Mapped[str | None] = mapped_column(String(24))
    concurrency_finding: Mapped[str | None] = mapped_column(String(16))
    #: Our own refusal code when nothing could be placed.
    failure_code: Mapped[str | None] = mapped_column(String(64))
    placed_at: Mapped[datetime | None]
    #: Arrivals are accepted until this instant; settlement runs after it.
    window_ends_at: Mapped[datetime | None]
    settled_at: Mapped[datetime | None]
    #: What the test cost us, absorbed (`forwarding_test_min`); never charged to the client.
    cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))


class ForwardingTestLeg(PKMixin, TimestampMixin, Base):
    """One outbound call of a test, rung from a platform number in our developer workspace."""

    __tablename__ = "forwarding_test_legs"
    __table_args__ = (
        CheckConstraint(_in("status", LEG_STATUSES), name="status_enum"),
        CheckConstraint("leg BETWEEN 1 AND 2", name="leg_range"),
        CheckConstraint("seconds IS NULL OR seconds >= 0", name="seconds_nonnegative"),
        UniqueConstraint("test_id", "leg"),
        Index(
            "ux_forwarding_test_legs_engine_call",
            "engine_call_ref",
            unique=True,
            postgresql_where=text("engine_call_ref IS NOT NULL"),
        ),
        Index(
            "ix_forwarding_test_legs_live",
            "created_at",
            postgresql_where=text("status IN ('placing', 'live')"),
        ),
    )

    #: Not a foreign key to a tenant table: this row is read untenanted (see the module).
    test_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    leg: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="placing")
    engine_call_ref: Mapped[str | None] = mapped_column(Text)
    answered: Mapped[bool | None]
    seconds: Mapped[int | None]
    ended_at: Mapped[datetime | None]


class SaveNumberMessage(PKMixin, TimestampMixin, Base):
    """One "save our number" WhatsApp to one caller of one client: at most one ever."""

    __tablename__ = "save_number_messages"
    __table_args__ = (
        CheckConstraint(_in("status", SAVE_NUMBER_STATUSES), name="status_enum"),
        UniqueConstraint("tenant_id", "caller_ref"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    #: A keyed hash of the caller's number (`service.caller_ref`), never the number.
    caller_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    refusal_code: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(8))
    sent_at: Mapped[datetime | None]


__all__ = [
    "CALLER_ID_FINDINGS",
    "CARRIERS",
    "CONCURRENCY_FINDINGS",
    "DEFAULT_RING_SECONDS",
    "LINE_KINDS",
    "LINE_STATUSES",
    "MAX_LINES",
    "MODES",
    "RING_SECONDS",
    "ForwardedLine",
    "ForwardingTest",
    "ForwardingTestLeg",
    "SaveNumberMessage",
]
