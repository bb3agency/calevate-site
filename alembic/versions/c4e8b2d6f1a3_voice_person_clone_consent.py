"""A voice cloned from a real person carries that person's consent (D-721)

Revision ID: c4e8b2d6f1a3
Revises: a2d8e6c4f1b7
Create Date: 2026-10-11 09:00:00.000000

The founder's own Instant clone in our Cartesia account is offered to every Studio client
under a name the operator gives it. A voice an operator marks as a clone of a real person
cannot be offered until a consent record exists: the speaker's name, the statement they
consented to, the date, the scope, and the operator who recorded it, with an optional sealed
copy of the signed document.

Also adds `gender` (the own-key listing's word for it, list-byok-voices.md:576-580) and
`display_label` (the name clients see; the sync never writes it).

A record outlives its mark: unmarking a voice keeps the consent and its document as evidence.

Downgrade drops the columns, and with them any consent records; `audit_log` keeps who
recorded each and when. Export them first if a downgrade is ever run on real data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "c4e8b2d6f1a3"
down_revision: str | None = "a2d8e6c4f1b7"
branch_labels: str | None = None
depends_on: str | None = None

_CATALOG = "platform_voice_catalog"
_CONSENT_WHOLE = "ck_platform_voice_catalog_clone_consent_whole"
_DOCUMENT_WITH_CONSENT = "ck_platform_voice_catalog_consent_document"
_DISPLAY_LABEL = "ck_platform_voice_catalog_display_label"
_RECORDED_BY_FK = "fk_platform_voice_catalog_consent_recorded_by_admin_users"

_CONSENT_FIELDS = (
    "consent_speaker_name",
    "consent_statement",
    "consent_given_on",
    "consent_scope",
    "consent_recorded_by",
    "consent_recorded_at",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(_CATALOG, sa.Column("gender", sa.Text(), nullable=True))
    op.add_column(_CATALOG, sa.Column("display_label", sa.Text(), nullable=True))
    op.add_column(
        _CATALOG,
        sa.Column("person_clone", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(_CATALOG, sa.Column("consent_speaker_name", sa.Text(), nullable=True))
    op.add_column(_CATALOG, sa.Column("consent_statement", sa.Text(), nullable=True))
    op.add_column(_CATALOG, sa.Column("consent_given_on", sa.Date(), nullable=True))
    op.add_column(_CATALOG, sa.Column("consent_scope", sa.Text(), nullable=True))
    op.add_column(_CATALOG, sa.Column("consent_recorded_by", UUID(as_uuid=True), nullable=True))
    op.add_column(
        _CATALOG, sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(_CATALOG, sa.Column("consent_document_key", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f(_RECORDED_BY_FK),
        _CATALOG,
        "admin_users",
        ["consent_recorded_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    all_null = " AND ".join(f"{c} IS NULL" for c in _CONSENT_FIELDS)
    all_set = " AND ".join(f"{c} IS NOT NULL" for c in _CONSENT_FIELDS)
    op.create_check_constraint(op.f(_CONSENT_WHOLE), _CATALOG, f"({all_null}) OR ({all_set})")
    op.create_check_constraint(
        op.f(_DOCUMENT_WITH_CONSENT),
        _CATALOG,
        "consent_document_key IS NULL OR consent_recorded_at IS NOT NULL",
    )
    op.create_check_constraint(
        op.f(_DISPLAY_LABEL),
        _CATALOG,
        "display_label IS NULL OR char_length(btrim(display_label)) BETWEEN 1 AND 60",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name in (_DISPLAY_LABEL, _DOCUMENT_WITH_CONSENT, _CONSENT_WHOLE):
        op.drop_constraint(op.f(name), _CATALOG, type_="check")
    op.drop_constraint(op.f(_RECORDED_BY_FK), _CATALOG, type_="foreignkey")
    for column in (
        "consent_document_key",
        *reversed(_CONSENT_FIELDS),
        "person_clone",
        "display_label",
        "gender",
    ):
        op.drop_column(_CATALOG, column)
