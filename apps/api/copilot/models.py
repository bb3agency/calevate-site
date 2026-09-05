"""The tables this package owns: the distilled memories and the durable transcript.

`copilot_memories` / `admin_copilot_memories` (migration `d4a9c17e6b02`, `f2c81a4d05e7`)
hold DISTILLED facts; `copilot_conversation_turns` / `admin_copilot_conversation_turns`
(migration `c7e0b2a94f13`, D-540) hold the verbatim conversation. Two stores rather than
one because the reads have nothing in common: recall budgets a handful of rows into a
prompt, a transcript is a page a person scrolls.

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
    #:
    #: WRITTEN BY BOTH WRITERS AND READ BY NO CODE, deliberately and said out loud so the
    #: next reader does not go looking for the consumer. It is the forensic half of a
    #: memory row — which realm and provider answered, how many fields were filled, and
    #: (on a semantic row) how many episodes it was distilled from — for an operator
    #: reading rows directly when a memory looks wrong. Nothing branches on it, no screen
    #: renders it, and recall does not select it: a column code read would have to be in
    #: `_RECALL_SQL`, and putting it there would spend prompt tokens on provenance the
    #: model cannot use.
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


class AdminCopilotMemory(PKMixin, TimestampMixin, Base):
    """One thing the ADMIN copilot remembers, for one operator (D-499, `f2c81a4d05e7`).

    A SECOND TABLE RATHER THAN A WIDENED FIRST ONE, and the reason is a foreign key.
    `Principal.user_id` is a `users.id` on the client realm and an `admin_users.id` on the
    admin realm; `copilot_memories.user_id` references `users`. So an operator's memory
    written there is a constraint violation at best and a cross-realm leak at worst — a
    client asking their own copilot a question would get an operator's notes about their
    account recalled back into the answer, because recall's only predicate is `user_id`
    and two id spaces would be sharing one column.

    Widening the client table instead (nullable `tenant_id`, a realm discriminator, the FK
    dropped) was considered and rejected in the migration: a tenant-scoped table with a
    nullable `tenant_id` is one whose RLS policy cannot be written, and it puts two
    populations behind one predicate where a bug is a cross-realm read.

    NO `tenant_id` AND NO RLS POLICY. These rows are the platform's own — an operator's
    questions about platform state — so there is no tenant whose row this could be.
    `viewing_tenant_id` records which account was on screen when the memory formed, so a
    fact learned on one client's page is not recalled as a fact about the platform; it is
    context, and `copilot/admin_memory.py::recall` scopes on it.

    NO `distilled_at` and no pending-distillation index: there is no admin distillation
    worker, and a column nothing writes is the defect CLAUDE.md names by hand. `kind` still
    admits `semantic` because a future distiller writes rows, not DDL.
    """

    __tablename__ = "admin_copilot_memories"
    __table_args__ = (
        CheckConstraint("kind IN ('episodic', 'semantic')", name="kind_enum"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint(f"length(content) <= {MAX_CONTENT_CHARS}", name="content_cap"),
        CheckConstraint(
            "kind <> 'semantic' OR screen_route IS NULL", name="semantic_has_no_screen"
        ),
        Index(
            "ix_admin_copilot_memories_user_recent",
            "admin_user_id",
            text("created_at DESC"),
        ),
        Index("ix_admin_copilot_memories_search", "search", postgresql_using="gin"),
    )

    #: CASCADE for `CopilotMemory.user_id`'s reason: a removed operator's console memories
    #: have no subject left, and RESTRICT would make this row block the deletion of the
    #: person it is about.
    admin_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    screen_route: Mapped[str | None] = mapped_column(String(200))
    #: SET NULL, not RESTRICT: an offboarded tenant must be deletable, and an operator's
    #: memory of supporting them is platform state that outlives the account.
    viewing_tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    meta: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    search: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(f"to_tsvector('{SEARCH_CONFIG}'::regconfig, content)", persisted=True),
    )


#: The roles a stored turn may carry, closed. Rendered into
#: `ck_copilot_conversation_turns_role_enum` and its admin twin.
TURN_ROLES: Final[tuple[str, ...]] = ("user", "assistant")


class _ConversationTurnColumns:
    """The columns both realms' transcripts share (migration `c7e0b2a94f13`, D-540).

    A mixin rather than one table with a realm discriminator, for
    `AdminCopilotMemory`'s reason: `Principal.user_id` is a `users.id` on one realm and an
    `admin_users.id` on the other, and two id spaces behind one column is a cross-realm
    read one forgotten predicate away.
    """

    #: WHICH SIGN-IN RUN this turn belongs to — the instant the user's current unbroken
    #: run of sessions began (`copilot/session_run.py`). It IS the conversation's
    #: lifetime: a turn from an older run is deleted before it is read. A plain instant
    #: and not a FK to `auth_sessions`, because a session row dies on every rotation.
    run_started_at: Mapped[datetime] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    #: Already through `workers.redaction.redact` before it gets here — the wire form,
    #: never the display form with the digits restored. See the migration.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: The screen this turn was said on (founder's decision 3: per message, not per
    #: thread). NOT NULL, unlike `CopilotMemory.screen_route`: every turn has a screen.
    screen_route: Mapped[str] = mapped_column(String(200), nullable=False)


class CopilotConversationTurn(_ConversationTurnColumns, PKMixin, TimestampMixin, Base):
    """One thing said in a client-realm copilot conversation."""

    __tablename__ = "copilot_conversation_turns"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role_enum"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint(f"length(content) <= {MAX_CONTENT_CHARS}", name="content_cap"),
        Index(
            "ix_copilot_conversation_turns_tenant_user_seq",
            "tenant_id",
            "user_id",
            "created_at",
            "id",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    #: CASCADE, for `CopilotMemory.user_id`'s reason.
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class AdminCopilotConversationTurn(_ConversationTurnColumns, PKMixin, TimestampMixin, Base):
    """One thing said in an ADMIN-realm copilot conversation (D-540).

    NO `tenant_id` AND NO RLS POLICY, exactly as `AdminCopilotMemory`: these rows are the
    platform's own. `viewing_tenant_id` records which account was on screen, and is
    context rather than ownership. No retention category either — there is no tenant
    whose policy could name it, and its clock is the admin realm's 8-hour absolute
    session bound, shorter than any period we publish.
    """

    __tablename__ = "admin_copilot_conversation_turns"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role_enum"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint(f"length(content) <= {MAX_CONTENT_CHARS}", name="content_cap"),
        Index(
            "ix_admin_copilot_conversation_turns_user_seq",
            "admin_user_id",
            "created_at",
            "id",
        ),
    )

    admin_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    viewing_tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )


__all__ = [
    "MAX_CONTENT_CHARS",
    "MEMORY_KINDS",
    "SEARCH_CONFIG",
    "TURN_ROLES",
    "AdminCopilotConversationTurn",
    "AdminCopilotMemory",
    "CopilotConversationTurn",
    "CopilotMemory",
]
