"""The move's per-agent record and the go-live guide's marker (D-859, migration b5d8f2a9c741).

The states are closed sets the migration's CHECKs spell too.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal, get_args
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: `waiting`: owed, or being retried after something that may pass. `moved`: the agent now
#: lives in the target workspace. `held`: refused for a reason only an operator or the voice
#: platform can lift (the plan's agent allowance, a voice the plan does not list); the agent
#: keeps working where it was and the hourly sweep tries again. `failed`: every retry spent on
#: an unexpected error; alarmed, and the sweep tries again.
MoveState = Literal["waiting", "moved", "held", "failed"]
MOVE_STATES: Final[tuple[MoveState, ...]] = get_args(MoveState)


class AgentWorkspaceMove(PKMixin, TimestampMixin, Base):
    """One agent's move into one client workspace."""

    __tablename__ = "agent_workspace_moves"
    __table_args__ = (
        UniqueConstraint("agent_id", "workspace_id", name="uq_agent_workspace_moves_agent"),
        CheckConstraint(f"status IN {MOVE_STATES!r}", name="status_enum"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        CheckConstraint("(status = 'moved') = (moved_at IS NOT NULL)", name="moved_stamped"),
        Index("ix_agent_workspace_moves_tenant", "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="waiting")
    #: Our code for the last refusal; never vendor text.
    reason_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: The code an operator was last alarmed with, so a retry that meets the same refusal
    #: does not page again.
    alarmed_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GoLiveGuide(PKMixin, TimestampMixin, Base):
    """Whether the owner is still owed the go-live guide."""

    __tablename__ = "go_live_guides"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_go_live_guides_tenant"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    #: The first payment's instant: from then the guide is offered.
    owed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["MOVE_STATES", "AgentWorkspaceMove", "GoLiveGuide", "MoveState"]
