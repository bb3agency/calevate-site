"""Declarative base, naming conventions and shared mixins (DATA-MODEL conventions).

- ids are UUIDv7 generated app-side (uuid-utils; PG16 has no native uuidv7()).
  Time-ordered ids keep b-tree inserts sequential.
- every table: created_at/updated_at timestamptz, server-side defaults.
- every tenant-scoped table: tenant_id + FORCEd RLS (policy lives in the migration,
  hard rule 1). TenantMixin carries the column; the RLS coverage guardrail asserts
  the policy exists for every table that has it.
"""

import uuid
from datetime import datetime

import uuid_utils
from sqlalchemy import DateTime, ForeignKey, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def uuid7() -> uuid.UUID:
    """App-side UUIDv7 as a stdlib UUID (SQLAlchemy needs uuid.UUID, not uuid_utils.UUID)."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Every datetime column is timestamptz (UTC in DB, IST at the edge — conventions).
    type_annotation_map = {datetime: DateTime(timezone=True)}  # noqa: RUF012


class PKMixin:
    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantMixin:
    """tenant_id on every tenant-scoped row. RLS policy ships in the same migration.

    THE FOREIGN KEY IS THE POINT, and for two tables it was missing (D-192). This mixin's
    comment has always said "FK by name (not Column object) so mixin works across modules;
    ondelete RESTRICT: offboarding is an explicit workflow (FLOWS §9), never a cascade" —
    and the `mapped_column()` call it sat inside named no `ForeignKey` at all. Forty-one of
    the forty-three tenant tables never noticed, because they hand-write the column with the
    FK spelled out; the two that trusted the mixin (`qa_reports`, `qa_call_samples`) got an
    ORM column with no relationship to `organizations`.

    That is not cosmetic. `alembic/env.py` generates against `Base.metadata`, so the next
    `--autogenerate` proposed `DROP CONSTRAINT fk_qa_reports_tenant_id_organizations` and its
    twin, in a diff a human is asked to skim — the exact defect class
    `scripts/check_metadata_columns.py` was written for, one op-kind outside the `add_column`
    /`remove_column` scope that file deliberately limits itself to. Dropping it would make
    orphaned rows representable and delete the RESTRICT that makes offboarding a workflow
    rather than a cascade. Proven by running `compare_metadata` against a database migrated
    from base to head: two `remove_fk` ops, both on the two tables that use this mixin.

    NO `index=True` HERE, deliberately. It used to be, and the DB has no
    `ix_qa_reports_tenant_id` or `ix_qa_call_samples_tenant_id` — so the models declared two
    indexes that do not exist and autogenerate proposed CREATEing them. Whether a bare
    `tenant_id` btree earns its write cost beside a composite that leads with `tenant_id` is
    a MEASURED, per-table decision in this repo (DATA-MODEL §10, `b9e5d2c74a18`,
    `tests/prefix_index_audit_test.py`: four dropped, seven kept, each with the plan that
    collapsed without it). A mixin cannot take that decision for a table it has never seen,
    and `e7c3d10a9f52` already recorded what happens when a model out-declares the schema —
    "leaving it would have had the next autogenerate helpfully recreate the index, a
    deprecation that un-deprecates itself". Tables that measured the index in declare it on
    their own column, as all forty-one already do.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            PgUUID(as_uuid=True),
            # FK by name (not Column object) so the mixin works across modules.
            # ondelete RESTRICT: offboarding is an explicit workflow (FLOWS §9),
            # never a cascade.
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        )


# The RLS policy expression every tenant table gets (DATA-MODEL §1). Referenced by
# migrations and by the coverage guardrail — single source of truth. NULLIF: a
# pooled connection that once had the GUC returns '' (not NULL) when unset —
# ''::uuid would ERROR instead of failing closed to zero rows.
RLS_POLICY_SQL = text("tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid")
