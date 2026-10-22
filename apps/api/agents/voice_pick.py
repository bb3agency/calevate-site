"""A voice chosen for a new agent, so its first test call can happen at all (D-855).

Publishing refuses an agent with no voice (`engine_choice.VOICE_REQUIRED`): the vendor's
default voice bills at a band we do not sell. An owner meeting their first agent has not
chosen one, so "Meet your agent" chooses for them and shows the choice with "Hear it" and
"Change" before the call.

ONLY A CLEAR VOICE (founder, 23 Oct 2026). Studio is offered under "Change", never chosen
automatically: it costs the owner more a minute, which is their decision. The candidates are
the client picker's own list (`hosted_voices.offered_hosted_voices`: added, enabled, still
listed) narrowed by the same pricing ground the picker shows (`hosted_voice_unofferable_
reason`), so this never chooses a voice the owner could not have chosen themselves.

THE ORDER. A voice that speaks the agent's language, one whose accent is that language before
the rest (a Telugu agent with a Telugu accent), then the catalogue's own order (label), so the
same catalogue gives every new agent of a language the same first voice.
"""

from __future__ import annotations

from collections.abc import Iterable, Set
from datetime import UTC, datetime

from apps.api.agents.hosted_voices import (
    HostedVoiceRow,
    hosted_voice_unofferable_reason,
    offered_hosted_voices,
    rung_of_source,
)
from apps.api.billing.engine_minutes import attested_rate_keys
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.hosted_platform import engine_platform_label


def _base(tag: str | None) -> str:
    return (tag or "").split("-")[0].strip().casefold()


def rank_clear_voices(
    rows: Iterable[HostedVoiceRow], *, engine: str, language: str, attested: Set[str], platform: str
) -> list[HostedVoiceRow]:
    """The Clear voices that can be chosen today for an agent speaking `language`, best first."""
    fit: list[HostedVoiceRow] = []
    for row in rows:
        if rung_of_source(engine, row.source) != "clear":
            continue
        reason = hosted_voice_unofferable_reason(
            row, attested=attested, voice_key_priced=False, platform=platform, audience="client"
        )
        if reason is not None:
            continue
        if row.languages and language not in row.languages:
            continue
        fit.append(row)
    wanted = _base(language)
    return sorted(fit, key=lambda row: (_base(row.accent) != wanted, row.label, row.voice_id))


async def pick_clear_voice(language: str) -> HostedVoiceRow | None:
    """The Clear voice a new agent speaking `language` starts with, or None when the engine
    hosts no voices or none can be chosen today. The catalogue is platform-scoped, so it is
    read on its own short session (as `GET /v1/agents/engine-catalogue` reads it)."""
    engine = get_engine()
    if not isinstance(engine, HostsVoices):
        return None
    async with untenanted_session() as session:
        attested = await attested_rate_keys(session, engine=engine.name, at=datetime.now(UTC))
        rows = await offered_hosted_voices(session)
    ranked = rank_clear_voices(
        rows,
        engine=engine.name,
        language=language,
        attested=attested,
        platform=engine_platform_label(engine),
    )
    return ranked[0] if ranked else None


__all__ = ["pick_clear_voice", "rank_clear_voices"]
