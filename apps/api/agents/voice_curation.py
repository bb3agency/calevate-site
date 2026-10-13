"""How many live agents speak each engine-hosted voice, across every tenant.

The number beside the archive button on the operator's hosted-voices screen
(`ops/hosted_voice_routes.py`): archiving a voice cannot reach a live call, but an operator
should see who would be surprised before they click.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import text

from apps.api.db.session import admin_session, tenant_session

# LIVE tenants only, by `deleted_at IS NULL` — spelled the same way as
# `admin/health.client_health` so the two cannot come to mean different populations.
_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL"

#: One tenant's live agents per ENGINE-HOSTED voice (D-687): `agents.engine_voice_id` holds
#: the hosted catalogue id.
_LIVE_BY_ENGINE_VOICE_SQL: Final = (
    "SELECT engine_voice_id, count(*) FROM agents WHERE status = 'live' "
    "AND deleted_at IS NULL AND engine_voice_id IS NOT NULL GROUP BY engine_voice_id"
)


async def count_live_agents_by_engine_voice() -> dict[str, int]:
    """LIVE agents per hosted voice id, across every tenant.

    The directory-then-enter-each-tenant shape RLS forces: `admin_session()` widens
    `organizations` and nothing else, so a single cross-tenant `SELECT` over `agents` would
    return zero rows — honestly, and misleadingly. N+1 by construction; it runs only on the
    admin console's Voices page, never on a call path.
    """
    async with admin_session() as directory:
        tenants = [row[0] for row in (await directory.execute(text(_DIRECTORY))).all()]
    totals: dict[str, int] = {}
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            for voice_id, held in (await scoped.execute(text(_LIVE_BY_ENGINE_VOICE_SQL))).all():
                totals[str(voice_id)] = totals.get(str(voice_id), 0) + int(held)
    return totals


__all__ = ["count_live_agents_by_engine_voice"]
