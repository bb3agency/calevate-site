"""A voice chosen for a new agent, so its first test call can happen at all (D-855).

Publishing refuses an agent with no voice (`engine_choice.VOICE_REQUIRED`): the vendor's
default voice bills at a band we do not sell. An owner meeting their first agent has not
chosen one, so "Meet your agent" chooses for them and shows the choice with "Hear it" and
"Change" before the call.

A STUDIO VOICE FIRST (founder, 23 Oct 2026, superseding the same day's "a Clear voice": "show
the clients the full potential"). Clear is offered under "Change". Studio is chosen only when
the account could really use it:

* Studio is open to this account (`studio_voices.studio_open_to`): for a free trial, our
  developer workspace answered ready at its last check (a trial's Studio publish needs it,
  `require_developer_studio`); and Studio voices are listed at all;
* on a trial, its Studio test minutes are not used up: a Studio test call is refused once they
  reach the console's `trial_studio_minutes` (`trial_access.refuse_trial_studio_over_cap`).

Otherwise a Clear voice, and the reason travels with the choice so the card can say in one
short line why it is not Studio. The candidates are always the client picker's own list
(`hosted_voices.offered_hosted_voices`: added, enabled, still listed) narrowed by the picker's
own pricing ground (`hosted_voice_unofferable_reason`), so this never chooses a voice the owner
could not have chosen themselves.

THE ORDER within a rung: a voice that speaks the agent's language, one whose accent is that
language before the rest, then the catalogue's own order (label), so the same catalogue gives
every new agent of a language the same first voice.

A WOMAN'S VOICE (founder, 23 Oct 2026): the new agent is named "Anjali"
(`first_run/names.FIRST_AGENT_NAME`), so the voice is chosen among female voices first: a
female Studio voice, else a female Clear voice (`no_female_studio_voice` when Studio could have
been used but has no woman's voice for the language). Only when no female voice can be chosen
on either rung is the best voice kept, flagged `not_female` so the card says so. A voice whose
provider states no gender is not counted as female: the name must match what the caller hears.
"""

from __future__ import annotations

from collections.abc import Iterable, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from apps.api.agents.hosted_voices import (
    STUDIO_VOICE_PROVIDER,
    HostedVoiceRow,
    hosted_voice_unofferable_reason,
    offered_hosted_voices,
    rung_of_source,
)
from apps.api.agents.studio_voices import studio_open_to
from apps.api.agents.voice_offer import tts_price_is_billable
from apps.api.billing.engine_minutes import attested_rate_keys
from apps.api.compliance.trial_access import restricting_trial, trial_studio_seconds_used
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.hosted_platform import engine_platform_label

Rung = Literal["clear", "studio"]

#: Why a Clear voice was chosen instead of Studio, for the card's one line.
StudioFallback = Literal[
    "studio_unavailable", "studio_minutes_used", "no_studio_voice", "no_female_studio_voice"
]

FALLBACKS: Final[tuple[str, ...]] = (
    "studio_unavailable",
    "studio_minutes_used",
    "no_studio_voice",
    "no_female_studio_voice",
)

Gender = Literal["female", "male"]


@dataclass(frozen=True, slots=True)
class PickedVoice:
    row: HostedVoiceRow
    rung: Rung
    #: Set when a Clear voice stands in for Studio.
    fallback: StudioFallback | None = None
    #: No female voice could be chosen, so this one is not a woman's (or states no gender).
    not_female: bool = False


def gender_of(stated: str | None) -> Gender | None:
    """The provider's free-text gender as one of ours, or None when it does not say."""
    word = (stated or "").strip().casefold()
    if word.startswith(("f", "w")):
        return "female"
    if word.startswith("m"):
        return "male"
    return None


def _female(rows: list[HostedVoiceRow]) -> list[HostedVoiceRow]:
    return [row for row in rows if gender_of(row.gender) == "female"]


def _base(tag: str | None) -> str:
    return (tag or "").split("-")[0].strip().casefold()


def rank_voices(
    rows: Iterable[HostedVoiceRow],
    *,
    rung: Rung,
    engine: str,
    language: str,
    attested: Set[str],
    platform: str,
    voice_key_priced: bool,
) -> list[HostedVoiceRow]:
    """The voices of `rung` that can be chosen today for an agent speaking `language`, best
    first."""
    fit: list[HostedVoiceRow] = []
    for row in rows:
        if rung_of_source(engine, row.source) != rung:
            continue
        reason = hosted_voice_unofferable_reason(
            row,
            attested=attested,
            voice_key_priced=voice_key_priced,
            platform=platform,
            audience="client",
        )
        if reason is not None:
            continue
        if row.languages and language not in row.languages:
            continue
        fit.append(row)
    wanted = _base(language)
    return sorted(fit, key=lambda row: (_base(row.accent) != wanted, row.label, row.voice_id))


async def studio_hindrance(tenant_id: UUID) -> StudioFallback | None:
    """Why this account cannot be given a Studio voice right now, or None when it can."""
    async with tenant_session(tenant_id) as session:
        if not await studio_open_to(session, tenant_id=tenant_id):
            return "studio_unavailable"
        trial = await restricting_trial(session, tenant_id=tenant_id)
        if trial is None:
            return None
        used = await trial_studio_seconds_used(session, tenant_id=tenant_id, trial=trial)
    if used >= get_settings().trial_studio_minutes * 60:
        return "studio_minutes_used"
    return None


async def pick_voice(tenant_id: UUID, language: str) -> PickedVoice | None:
    """The voice a new agent speaking `language` starts with: Studio when this account can use
    it, else Clear with the reason. None when the engine hosts no voices or none can be chosen
    today. The catalogue is platform-scoped, so it is read on its own short session (as
    `GET /v1/agents/engine-catalogue` reads it)."""
    engine = get_engine()
    if not isinstance(engine, HostsVoices):
        return None
    async with untenanted_session() as session:
        attested = await attested_rate_keys(session, engine=engine.name, at=datetime.now(UTC))
        rows = await offered_hosted_voices(session)
    ranked = {
        rung: rank_voices(
            rows,
            rung=rung,
            engine=engine.name,
            language=language,
            attested=attested,
            platform=engine_platform_label(engine),
            voice_key_priced=tts_price_is_billable(STUDIO_VOICE_PROVIDER),
        )
        for rung in ("studio", "clear")
    }
    return choose_voice(ranked["studio"], ranked["clear"], await studio_hindrance(tenant_id))


def choose_voice(
    studio: list[HostedVoiceRow], clear: list[HostedVoiceRow], hindrance: StudioFallback | None
) -> PickedVoice | None:
    """A female Studio voice when nothing stands in Studio's way, else a female Clear voice with
    the reason; with no female voice on either rung, the best voice as before, flagged."""
    usable_studio = studio if hindrance is None else []
    if female_studio := _female(usable_studio):
        return PickedVoice(row=female_studio[0], rung="studio")
    if female_clear := _female(clear):
        reason: StudioFallback = hindrance or (
            "no_female_studio_voice" if usable_studio else "no_studio_voice"
        )
        return PickedVoice(row=female_clear[0], rung="clear", fallback=reason)
    if usable_studio:
        return PickedVoice(row=usable_studio[0], rung="studio", not_female=True)
    if not clear:
        return None
    return PickedVoice(
        row=clear[0], rung="clear", fallback=hindrance or "no_studio_voice", not_female=True
    )


__all__ = [
    "FALLBACKS",
    "Gender",
    "PickedVoice",
    "Rung",
    "StudioFallback",
    "choose_voice",
    "gender_of",
    "pick_voice",
    "rank_voices",
    "studio_hindrance",
]
