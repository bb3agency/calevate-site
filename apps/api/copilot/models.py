"""`copilot_memories` — the one table this package owns (migration `d4a9c17e6b02`).

The migration is the schema of record and carries the reasoning; this file exists so
`Base.metadata` is complete, because `alembic/env.py` autogenerates against it and a
column or index the model does not declare is one the next `--autogenerate` proposes
DROPping into a diff a human is asked to skim (`db/base.TenantMixin` records that exact
defect happening twice).

So every physical object is declared here, including the two a model normally would not:
the GENERATED `search` column and the GIN index over it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: The two kinds, closed. `episodic` is what happened; `semantic` is what was learned from
#: a run of episodes. Rendered into `ck_copilot_memories_kind_enum`.
MEMORY_KINDS: Final[tuple[str, ...]] = ("episodic", "semantic")

#: The DB's own ceiling on one row's `content`, repeated here so a writer can refuse
#: BEFORE the round trip and say something useful instead of surfacing a constraint name.
#: Same number as `copilot/schemas._MAX_TEXT`, for that constant's reason.
MAX_CONTENT_CHARS: Final = 2_000

#: The text-search configuration the generated column uses. `simple`, not `english` — see
#: the migration: this console is Telugu-first and English stemming helps none of it.
SEARCH_CONFIG: Final = "simple"


class CopilotMemory(PKMixin, TimestampMixin, Base):
    """One thing the copilot remembers, for one person, inside one tenant.

    RLS answers "which tenant" and never "which person" (`crm/models.LeadSavedView` says
    the same), so `user_id` is an explicit predicate in every read `copilot/memory.py`
    issues. Sharing one colleague's console conversation with another is not a tenancy
    breach and is still wrong.
    """

    __tablename__ = "copilot_memories"
    __table_args__ = (
        CheckConstraint("kind IN ('episodic', 'semantic')", name="kind_enum"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint(f"length(content) <= {MAX_CONTENT_CHARS}", name="content_cap"),
        CheckConstraint(
            "kind <> 'semantic' OR screen_route IS NULL", name="semantic_has_no_screen"
        ),
        CheckConstraint(
            "kind = 'episodic' OR distilled_at IS NULL", name="only_episodic_is_distilled"
        ),
        Index(
            "ix_copilot_memories_tenant_user_recent",
            "tenant_id",
            "user_id",
            text("created_at DESC"),
        ),
        Index("ix_copilot_memories_search", "search", postgresql_using="gin"),
        Index(
            "ix_copilot_memories_pending_distillation",
            "tenant_id",
            "user_id",
            "screen_route",
            "created_at",
            postgresql_where=text("kind = 'episodic' AND distilled_at IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    #: CASCADE, not RESTRICT: a deleted user's console memories have no subject left, and
    #: RESTRICT would make this row block the deletion of the person it is about.
    #: `lead_saved_views` made the same call for the same class of per-user console state.
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    #: Already through `workers.redaction.redact` before it gets here — see
    #: `copilot/memory.py::redacted_content`, which is the only sanctioned writer.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: The route template the browser reported, which is a screen NAME and not a record
    #: (`copilot/routes.py` audits the same value). NULL on a semantic row.
    screen_route: Mapped[str | None] = mapped_column(String(200))
    #: Counts, ids and flags only. Never prose — that is `content`, the one column the
    #: redaction pass covers and the one the sweep and the erasure both name.
    meta: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    #: Stamped by `apps/workers/copilot_memory.py` in the same transaction as the semantic
    #: rows it produced. That stamp IS the job's idempotency.
    distilled_at: Mapped[datetime | None]
    #: GENERATED ALWAYS ... STORED. Declared so autogenerate does not propose dropping it;
    #: never written by the ORM (`Computed` marks it read-only, so an INSERT omits it).
    search: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(f"to_tsvector('{SEARCH_CONFIG}'::regconfig, content)", persisted=True),
    )


__all__ = ["MAX_CONTENT_CHARS", "MEMORY_KINDS", "SEARCH_CONFIG", "CopilotMemory"]
