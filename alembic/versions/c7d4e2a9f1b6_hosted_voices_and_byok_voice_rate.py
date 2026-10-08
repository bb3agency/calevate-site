"""Voices an engine hosts in the voice catalogue, and the own-voice-key minute rate (D-687)

Revision ID: c7d4e2a9f1b6
Revises: b6e2d94a7c15
Create Date: 2026-10-08 12:00:00.000000

Under `ENGINE=thinnest` the voice catalogue holds the engine's own voices (its Studio band and
our clones, provider `thinnest`) and the voices of our Cartesia key installed in the Studio
workspace (provider `cartesia`, ids `byok:<id>`), so the provider CHECK widens by one value.
Six nullable columns carry what those rows need and Pipecat rows never set: the voice's
accent and description as listed, the clone's id (to delete it), and the stored preview.

The minute rate gains `byok_voice`, the rate a call spoken on our own voice key is metered at,
on both `platform_engine_minute_prices.rate_key` and `engine_agent_routes.engine_rate_key`.

Downgrade refuses while a `byok_voice` price is attested (that table is append-only, hard
rule 4) or a route is stamped with it, and deletes only the rows this revision made
insertable: `thinnest` and `byok:` catalogue rows, which a sync re-derives.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "c7d4e2a9f1b6"
down_revision: str | None = "b6e2d94a7c15"
branch_labels: str | None = None
depends_on: str | None = None

_CATALOG = "platform_voice_catalog"
_PROVIDER_CK = "ck_platform_voice_catalog_provider"
_PROVIDERS_OLD = "provider IN ('cartesia', 'gnani')"
_PROVIDERS_NEW = "provider IN ('cartesia', 'gnani', 'thinnest')"
_PREVIEW_CK = "ck_platform_voice_catalog_preview_whole"
_PREVIEW_SOURCE_CK = "ck_platform_voice_catalog_preview_source"

# Frozen copies, not imports: a migration records what the schema became at this revision.
_RATE_KEYS_OLD = "('platform', 'standard', 'premium', 'studio')"
_RATE_KEYS_NEW = "('platform', 'standard', 'premium', 'studio', 'byok_voice')"
_PRICE_CK = "ck_platform_engine_minute_prices_rate_key"
_ROUTE_CK = "ck_engine_agent_routes_engine_rate_key"

_COLUMNS = (
    "accent",
    "description",
    "engine_clone_id",
    "preview_object_key",
    "preview_content_type",
    "preview_source",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(_PROVIDER_CK), _CATALOG, type_="check")
    op.create_check_constraint(op.f(_PROVIDER_CK), _CATALOG, _PROVIDERS_NEW)
    for column in _COLUMNS:
        op.add_column(_CATALOG, sa.Column(column, sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f(_PREVIEW_CK),
        _CATALOG,
        "(preview_object_key IS NULL) = (preview_content_type IS NULL) "
        "AND (preview_object_key IS NULL) = (preview_source IS NULL)",
    )
    op.create_check_constraint(
        op.f(_PREVIEW_SOURCE_CK),
        _CATALOG,
        "preview_source IS NULL OR preview_source IN ('vendor', 'upload')",
    )

    op.drop_constraint(op.f(_PRICE_CK), "platform_engine_minute_prices", type_="check")
    op.create_check_constraint(
        op.f(_PRICE_CK), "platform_engine_minute_prices", f"rate_key IN {_RATE_KEYS_NEW}"
    )
    op.drop_constraint(op.f(_ROUTE_CK), "engine_agent_routes", type_="check")
    op.create_check_constraint(
        op.f(_ROUTE_CK),
        "engine_agent_routes",
        f"engine_rate_key IS NULL OR engine_rate_key IN {_RATE_KEYS_NEW}",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _refuse_stranded_rates()
    op.drop_constraint(op.f(_ROUTE_CK), "engine_agent_routes", type_="check")
    op.create_check_constraint(
        op.f(_ROUTE_CK),
        "engine_agent_routes",
        f"engine_rate_key IS NULL OR engine_rate_key IN {_RATE_KEYS_OLD}",
    )
    op.drop_constraint(op.f(_PRICE_CK), "platform_engine_minute_prices", type_="check")
    op.create_check_constraint(
        op.f(_PRICE_CK), "platform_engine_minute_prices", f"rate_key IN {_RATE_KEYS_OLD}"
    )

    op.drop_constraint(op.f(_PREVIEW_SOURCE_CK), _CATALOG, type_="check")
    op.drop_constraint(op.f(_PREVIEW_CK), _CATALOG, type_="check")
    for column in reversed(_COLUMNS):
        op.drop_column(_CATALOG, column)
    # Re-derivable cache rows only this revision made insertable (a sync writes them again).
    op.execute(f"DELETE FROM {_CATALOG} WHERE provider = 'thinnest' OR voice_id LIKE 'byok:%'")
    op.drop_constraint(op.f(_PROVIDER_CK), _CATALOG, type_="check")
    op.create_check_constraint(op.f(_PROVIDER_CK), _CATALOG, _PROVIDERS_OLD)


def _refuse_stranded_rates() -> None:
    """Refuse BEFORE anything changes: an attested `byok_voice` price cannot be deleted
    (append-only) and a route stamped with it would fail the narrower CHECK."""
    if probe_skipped_offline(
        "offline `--sql`: the pre-flight that refuses to narrow the minute rate keys while a\n"
        "`byok_voice` price or route exists was NOT run. Check first with:\n"
        "SELECT count(*) FROM platform_engine_minute_prices WHERE rate_key = 'byok_voice';\n"
        "SELECT count(*) FROM engine_agent_routes WHERE engine_rate_key = 'byok_voice';"
    ):
        return
    bind = op.get_bind()
    prices = bind.execute(
        sa.text("SELECT count(*) FROM platform_engine_minute_prices WHERE rate_key = 'byok_voice'")
    ).scalar_one()
    routes = bind.execute(
        sa.text("SELECT count(*) FROM engine_agent_routes WHERE engine_rate_key = 'byok_voice'")
    ).scalar_one()
    if prices or routes:
        raise RuntimeError(
            f"{prices} attested `byok_voice` price row(s) and {routes} route row(s) stamped "
            "with it exist. Prices are append-only and cannot be removed; re-publish those "
            "agents on another voice and keep this revision."
        )
