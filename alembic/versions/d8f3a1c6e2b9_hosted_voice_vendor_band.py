"""Cache every band of an engine's own voices, with the band (D-687)

Revision ID: d8f3a1c6e2b9
Revises: c7d4e2a9f1b6
Create Date: 2026-10-08 18:00:00.000000

The ThinnestAI voice sync kept only the engine's Studio band, so on a plan below Pro (which
lists no Studio voices) the operator saw an empty platform and a refresh that blamed the
credential. The sync now caches every voice the engine lists with its price band, and only
the Studio band can be added and offered.

`vendor_band` is nullable: Pipecat rows and own-key (`byok:`) rows have no engine band. Every
`engine:` row already cached was written by a sync that kept only the Studio band, or is one
of our clones (Studio band too), so they are backfilled as `studio`.

Downgrade deletes the non-Studio `engine:` rows this revision made writable (a re-derivable
cache; the previous sync never wrote them) and drops the column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d8f3a1c6e2b9"
down_revision: str | None = "c7d4e2a9f1b6"
branch_labels: str | None = None
depends_on: str | None = None

_CATALOG = "platform_voice_catalog"
_BAND_CK = "ck_platform_voice_catalog_vendor_band"
# Frozen copy of `engine/catalogue.HostedVoiceBand` at this revision.
_BANDS = "('standard', 'premium', 'studio')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(_CATALOG, sa.Column("vendor_band", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f(_BAND_CK), _CATALOG, f"vendor_band IS NULL OR vendor_band IN {_BANDS}"
    )
    op.execute(f"UPDATE {_CATALOG} SET vendor_band = 'studio' WHERE tts_model = 'engine'")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        f"DELETE FROM {_CATALOG} WHERE tts_model = 'engine' "
        "AND vendor_band IS DISTINCT FROM 'studio'"
    )
    op.drop_constraint(op.f(_BAND_CK), _CATALOG, type_="check")
    op.drop_column(_CATALOG, "vendor_band")
