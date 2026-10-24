"""Which agents use each engine-hosted voice, across every tenant, and in what state.

The number beside each voice on the operator's hosted-voices screen
(`ops/hosted_voice_routes.py`) and the ground for refusing to archive a voice in use
(`hosted_voices.set_hosted_curation`, D-880). Every non-deleted agent counts, not only live
ones: a ready agent (D-838) speaks the voice on its test calls and goes live on it, and a
draft or archived agent can be published or restored onto it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from sqlalchemy import text

from apps.api.agents.models import AGENT_READY_STATUS, is_published
from apps.api.db.session import admin_session, tenant_session

# LIVE tenants only, by `deleted_at IS NULL` — spelled the same way as
# `admin/health.client_health` so the two cannot come to mean different populations.
_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL"

#: One tenant's agents per ENGINE-HOSTED voice (D-687), split the way `use_of` splits one:
#: `agents.engine_voice_id` holds the hosted catalogue id.
_USE_BY_ENGINE_VOICE_SQL: Final = (
    "SELECT engine_voice_id, "
    "count(*) FILTER (WHERE status = 'live' AND coalesce(engine_agent_ref, '') <> ''), "
    "count(*) FILTER (WHERE status = :ready AND coalesce(engine_agent_ref, '') <> ''), "
    "count(*) "
    "FROM agents WHERE deleted_at IS NULL AND engine_voice_id IS NOT NULL "
    "GROUP BY engine_voice_id"
)

#: How an agent uses its voice: on the phone, ready and not taking calls, or not published
#: (a draft, an agent paused before it was ever published, an archived one).
VoiceUse = Literal["live", "ready", "not_published"]


def use_of(status: str, engine_agent_ref: str | None) -> VoiceUse:
    """One agent's use of its voice, by `models.is_published`'s rule."""
    if not is_published(status, engine_agent_ref):
        return "not_published"
    return "live" if status == "live" else "ready"


@dataclass(frozen=True, slots=True)
class VoiceUsage:
    live: int = 0
    ready: int = 0
    not_published: int = 0

    @property
    def total(self) -> int:
        return self.live + self.ready + self.not_published

    @property
    def published(self) -> int:
        """Agents the engine holds on this voice: what a change on the platform reaches."""
        return self.live + self.ready

    def __add__(self, other: VoiceUsage) -> VoiceUsage:
        return VoiceUsage(
            live=self.live + other.live,
            ready=self.ready + other.ready,
            not_published=self.not_published + other.not_published,
        )


NOT_IN_USE: Final = VoiceUsage()


async def count_agents_by_engine_voice() -> dict[str, VoiceUsage]:
    """Every non-deleted agent per hosted voice id, across every tenant, by use.

    The directory-then-enter-each-tenant shape RLS forces: `admin_session()` widens
    `organizations` and nothing else, so a single cross-tenant `SELECT` over `agents` would
    return zero rows — honestly, and misleadingly. N+1 by construction; it runs only on the
    admin console's Voices page and its writes, never on a call path.
    """
    async with admin_session() as directory:
        tenants = [row[0] for row in (await directory.execute(text(_DIRECTORY))).all()]
    totals: dict[str, VoiceUsage] = {}
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            rows = (
                await scoped.execute(text(_USE_BY_ENGINE_VOICE_SQL), {"ready": AGENT_READY_STATUS})
            ).all()
        for voice_id, live, ready, every in rows:
            held = VoiceUsage(
                live=int(live), ready=int(ready), not_published=int(every) - int(live) - int(ready)
            )
            totals[str(voice_id)] = totals.get(str(voice_id), NOT_IN_USE) + held
    return totals


__all__ = [
    "NOT_IN_USE",
    "VoiceUsage",
    "VoiceUse",
    "count_agents_by_engine_voice",
    "use_of",
]
