"""`tenant_feature_flags` — one row per tenant per flag they are OFF THE DEFAULT for.

Tenant-scoped and FORCE-RLS'd; the policy ships in migration 3a91c7e04d58 beside the
table (hard rule 1) and the coverage guardrail asserts it via `db/registry.TENANT_TABLES`.

**Absence is the platform default**, and that is the whole shape: a tenant with no row is
not "unconfigured", it is following the declared default in `flags/registry.py`. Nothing
seeds a row per tenant per flag, so adding a flag costs zero writes and removing one
leaves rows that simply stop being read (`flags/service.resolve_flags` ignores an
undeclared name, and the console offers to clear it — the two-step deprecation hard rule 8
asks for, applied to a row rather than a column).

MUTABLE, and absent from `APPEND_ONLY_TABLES` — the same reasoning as `KycRecord` and
`FirstCampaignReview`. This row is the tenant's CURRENT position on one flag; the
immutable history of who moved it is `audit_log`, where every real change writes an entry
(hard rule 4).

The CHECK constraints mirror migration 3a91c7e04d58 and the migration is the source of
truth (DATA-MODEL §10).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin
from apps.api.flags.registry import FLAG_NAME_PATTERN


class TenantFeatureFlag(PKMixin, TimestampMixin, Base):
    """One tenant's override of one declared flag."""

    __tablename__ = "tenant_feature_flags"
    __table_args__ = (
        # One position per tenant per flag. A second row would be a tenant that is both
        # on and off, resolved by whichever the query happened to read first.
        # Unnamed, so `Base.metadata`'s naming convention generates
        # `uq_tenant_feature_flags_tenant_id_flag` — the exact name the migration spells
        # with `op.f(...)`. An explicit `name=` here would be used verbatim and would
        # leave `alembic check` reporting a permanent drop-and-recreate of this
        # constraint (which is what two older tables in this repo already do).
        UniqueConstraint("tenant_id", "flag"),
        # The NAME's shape, never the SET of names. A CHECK enumerating the declared
        # flags would be a second definition of the registry, and it would have to be
        # migrated in lockstep with `flags/registry.py` forever — including on the way
        # OUT, where a retired flag's rows must stay storable long enough to be cleared.
        CheckConstraint(f"flag ~ '{FLAG_NAME_PATTERN}'", name="flag_name_shape"),
        # WHY this client is off the default. An override nobody can account for later is
        # the finding this column exists to avoid, and an empty string accounts for
        # nothing (`first_campaign_reviews.decision_note` draws the same line).
        CheckConstraint("length(btrim(reason)) >= 3", name="reason_says_why"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    flag: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The override. NOT nullable: "no position" is expressed by the ABSENCE of the row,
    #: so a NULL here would be a second spelling of the same fact — and the one that
    #: silently outranks the default in every `COALESCE` somebody writes later.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    #: An `admin_users.id`, NOT NULL: every write comes from the admin surface, which has
    #: resolved a principal before it reaches the service. An auditor asks who, and the
    #: mutable row should be able to answer without a walk through `audit_log`.
    #
    # `created_at` / `updated_at` come from `TimestampMixin`. `updated_at` is when the
    # position last MOVED, which is what the console renders as "set" — and it moves only
    # on a real change, because `service.set_flag` writes nothing when nothing differs.
    set_by_admin_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=False
    )


__all__ = ["TenantFeatureFlag"]
