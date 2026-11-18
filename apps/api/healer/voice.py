"""The voice an agent falls back to when callers cannot hear it (D-987).

Founder, 12 Nov 2026: on a voice failure the healer moves the agent to its LAST WORKING
VOICE (Clear or Studio), tells the owner, and moves it back once the failed voice works
again; each call is billed on the voice that spoke it (`billing/engine_minutes.rate_key_ran`).
This amends D-701's "voice changes are only proposed".

This module holds the facts the playbook (`workers/voice_fallback`) decides on:

* **The record of working voices** (`agent_voice_history`): per agent and voice, when its
  calls last went through with nothing the caller heard going wrong, and when one last
  failed. Updated from the scored calls (`record_window`) and at once on a failure the
  platform reports (`record_failure`). A call's voice is the one it was published with
  (`calls.voice_settings ->> 'engine_voice'`, `agents/voice_stamp.ENGINE_VOICE`).
* **The failure domain** of a voice: every Studio voice speaks on our one Cartesia key, so
  they fail together and a Studio agent's backup is a Clear voice; a Clear voice is its own
  catalogue voice on the platform, so its backup is Studio or another Clear voice.
* **The backup voices** (`backup_voices`): the agent's working voices outside the failed
  domain, newest first, then the voices an operator added and enabled for clients
  (`hosted_voices.offered_hosted_voices`, the client picker's own list and pricing ground)
  that speak the agent's language. Always the SAME GENDER as the voice it replaces, because
  the agent's AI sentence is rendered in its voice's gender (`lifecycle._rerender_ai_line`)
  and the healer never changes the notices: a same-gender voice re-renders the identical
  sentence, so the switch writes nothing to it.
* **The probe** of a Studio voice (`probe_studio_voice`): one short line spoken on our key
  (`preview_own_key_voice`, billed per character, so the first words of the agent's own
  greeting from `spoken_style`, cut to `healer_voice_probe_max_chars`). A Clear catalogue
  voice has no preview on the platform's API (thinnest-findings/mirror/snapshots/
  2026-11-12/pages/channels/voice.md:270-273, :294: previews and "Test a call" are console
  features), so a Clear voice is judged by real calls only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from calevate_shared.spoken_style import opening_in
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.hosted_voices import (
    STUDIO_VOICE_PROVIDER,
    HostedVoiceRow,
    hosted_voice_unofferable_reason,
    offered_hosted_voices,
    parse_hosted_voice_id,
    studio_listing_workspace,
)
from apps.api.agents.voice_offer import tts_price_is_billable
from apps.api.agents.voice_pick import gender_of, studio_hindrance
from apps.api.agents.voice_stamp import ENGINE_VOICE
from apps.api.agents.voice_tuning import is_studio_voice
from apps.api.billing.engine_minutes import attested_rate_keys
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.hosted_platform import engine_platform_label
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.healer.health import HEARD_SQL, call_check_params

log = get_logger(__name__)

Rung = Literal["clear", "studio"]
#: The one failure domain every Studio voice shares: our own voice key.
OWN_VOICE_DOMAIN: Final = "own_voice_key"


def rung_of(voice_id: str | None) -> Rung:
    return "studio" if is_studio_voice(voice_id) else "clear"


def failure_domain(voice_id: str | None) -> str:
    """What fails together with this voice: our voice key for Studio, else the voice."""
    if is_studio_voice(voice_id):
        return OWN_VOICE_DOMAIN
    return voice_id or "none"


# --- the record of working voices ---------------------------------------------------------

#: One upsert per (agent, voice) from a span of calls; GREATEST and LEAST ignore NULLs, so a
#: span re-scored (the scorer reads each window twice) changes nothing it already recorded.
_RECORD_WINDOW = (
    "INSERT INTO agent_voice_history (id, tenant_id, agent_id, engine_voice_id, "
    "first_good_at, last_good_at, last_failed_at, created_at, updated_at) "
    "SELECT gen_random_uuid(), :tid, c.agent_id, c.voice_settings ->> '" + ENGINE_VOICE + "', "
    "min(coalesce(c.started_at, c.created_at)) FILTER (WHERE NOT " + HEARD_SQL + "), "
    "max(coalesce(c.started_at, c.created_at)) FILTER (WHERE NOT " + HEARD_SQL + "), "
    "max(coalesce(c.started_at, c.created_at)) FILTER (WHERE " + HEARD_SQL + "), now(), now() "
    "FROM calls c WHERE c.created_at >= :start AND c.created_at < :end "
    "AND c.status = 'completed' AND c.agent_id IS NOT NULL "
    "AND c.voice_settings ->> '" + ENGINE_VOICE + "' IS NOT NULL GROUP BY c.agent_id, "
    "c.voice_settings ->> '" + ENGINE_VOICE + "' "
    "ON CONFLICT (agent_id, engine_voice_id) DO UPDATE SET "
    "first_good_at = LEAST(agent_voice_history.first_good_at, EXCLUDED.first_good_at), "
    "last_good_at = GREATEST(agent_voice_history.last_good_at, EXCLUDED.last_good_at), "
    "last_failed_at = GREATEST(agent_voice_history.last_failed_at, EXCLUDED.last_failed_at), "
    "updated_at = now()"
)


async def record_window(
    session: AsyncSession, *, tenant_id: UUID, start: datetime, end: datetime
) -> int:
    """Fold one span of this tenant's finished calls into the record of working voices."""
    result = await session.execute(
        text(_RECORD_WINDOW),
        {"tid": tenant_id, "start": start, "end": end, **call_check_params(datetime.now(UTC))},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def record_failure(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, voice_id: str, at: datetime
) -> None:
    """A failure the platform reported on a live call of this voice, recorded at once."""
    await session.execute(
        text(
            "INSERT INTO agent_voice_history (id, tenant_id, agent_id, engine_voice_id, "
            "last_failed_at, created_at, updated_at) VALUES (:id, :tid, :aid, :v, :at, now(), "
            "now()) ON CONFLICT (agent_id, engine_voice_id) DO UPDATE SET last_failed_at = "
            "GREATEST(agent_voice_history.last_failed_at, EXCLUDED.last_failed_at), "
            "updated_at = now()"
        ),
        {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "v": voice_id, "at": at},
    )


async def working_voices(session: AsyncSession, *, agent_id: UUID) -> list[str]:
    """This agent's voices whose last call went through after their last failure, newest
    first."""
    rows = (
        await session.execute(
            text(
                "SELECT engine_voice_id FROM agent_voice_history WHERE agent_id = :aid "
                "AND last_good_at IS NOT NULL AND (last_failed_at IS NULL OR last_good_at > "
                "last_failed_at) ORDER BY last_good_at DESC LIMIT 50"
            ),
            {"aid": agent_id},
        )
    ).all()
    return [str(r[0]) for r in rows]


# --- the agent the playbook moves ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentVoice:
    voice_id: str | None
    language: str
    direction: str
    business: str
    published: bool


async def agent_voice(session: AsyncSession, agent_id: UUID) -> AgentVoice | None:
    row = (
        await session.execute(
            text(
                "SELECT a.engine_voice_id, a.language_primary, a.direction, o.name, "
                "a.status IN ('live', 'paused') "
                "FROM agents a JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        return None
    return AgentVoice(
        voice_id=row[0],
        language=str(row[1]),
        direction=str(row[2]),
        business=str(row[3]),
        published=bool(row[4]),
    )


# --- backup voices ------------------------------------------------------------------------


def _fits(row: HostedVoiceRow, *, failed: str, gender: str | None, language: str) -> bool:
    if row.voice_id == failed or failure_domain(row.voice_id) == failure_domain(failed):
        return False
    if gender_of(row.gender) != gender:
        return False
    return not row.languages or language in row.languages


async def backup_voices(
    tenant_id: UUID, agent_id: UUID, *, failed: str, language: str
) -> list[str]:
    """The voices this agent may be moved to, best first, at most `healer_voice_candidates`:
    its own working voices outside the failed domain, then the client picker's voices that
    speak its language. Every one is offerable today and the same gender as `failed`."""
    engine = get_engine()
    limit = get_settings().healer_voice_candidates
    async with untenanted_session() as session:
        attested = await attested_rate_keys(session, engine=engine.name, at=datetime.now(UTC))
        offered = await offered_hosted_voices(session)
    gender = next((gender_of(r.gender) for r in offered if r.voice_id == failed), None)
    if gender is None:
        async with untenanted_session() as session:
            stated = (
                await session.execute(
                    text("SELECT gender FROM platform_voice_catalog WHERE voice_id = :v"),
                    {"v": failed},
                )
            ).scalar()
        gender = gender_of(None if stated is None else str(stated))
    studio_ok = await studio_hindrance(tenant_id) is None
    priced = tts_price_is_billable(STUDIO_VOICE_PROVIDER)
    platform = engine_platform_label(engine)
    usable = {
        row.voice_id: row
        for row in offered
        if _fits(row, failed=failed, gender=gender, language=language)
        and (studio_ok or rung_of(row.voice_id) != "studio")
        and hosted_voice_unofferable_reason(
            row,
            attested=attested,
            voice_key_priced=priced,
            platform=platform,
            audience="client",
        )
        is None
    }
    async with tenant_session(tenant_id) as session:
        worked = [v for v in await working_voices(session, agent_id=agent_id) if v in usable]
    other_rung = "clear" if rung_of(failed) == "studio" else "studio"
    rest = sorted(
        (v for v in usable if v not in worked),
        key=lambda v: (rung_of(v) != other_rung, usable[v].label, v),
    )
    return (worked + rest)[:limit]


# --- the probe ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Probe:
    ok: bool
    #: Ids and short codes only: it is written to the ledger.
    why: str


def probe_line(*, language: str, direction: str, business: str) -> str | None:
    """The first words of the agent's own greeting in its language, at most
    `healer_voice_probe_max_chars`, cut at a word. None where the table has no greeting,
    and the platform then speaks its own short greeting in that language."""
    template = opening_in(language, "outbound" if direction == "outbound" else "inbound")
    if template is None:
        return None
    line = template.replace("{business}", business).strip()
    cap = get_settings().healer_voice_probe_max_chars
    if len(line) <= cap:
        return line or None
    cut = line[: cap + 1].rsplit(" ", 1)[0].strip()
    return cut or None


async def probe_studio_voice(voice_id: str, agent: AgentVoice) -> Probe:
    """Speak one short line in a Studio voice on our key. Never raises."""
    ref = parse_hosted_voice_id(voice_id)
    engine = get_engine()
    if ref is None or ref.source != "byok" or not isinstance(engine, HostsVoices):
        return Probe(ok=False, why="not_a_studio_voice")
    try:
        found = await studio_listing_workspace(engine)
        if found is None:
            return Probe(ok=False, why="no_workspace_ready_on_our_voice_key")
        with in_workspace(found.workspace):
            audio = await engine.preview_own_key_voice(
                voice_id=ref.vendor_id,
                text=probe_line(
                    language=agent.language, direction=agent.direction, business=agent.business
                ),
                language=agent.language,
            )
    except Exception as exc:
        log.warning("healer_voice_probe_failed", extra={"error": type(exc).__name__})
        return Probe(ok=False, why=type(exc).__name__)
    if not audio.data:
        return Probe(ok=False, why="no_audio")
    return Probe(ok=True, why=f"spoke {len(audio.data)} bytes")


__all__ = [
    "OWN_VOICE_DOMAIN",
    "AgentVoice",
    "Probe",
    "Rung",
    "agent_voice",
    "backup_voices",
    "failure_domain",
    "probe_line",
    "probe_studio_voice",
    "record_failure",
    "record_window",
    "rung_of",
    "working_voices",
]
