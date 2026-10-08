"""Switching Studio voices on and off in our one ThinnestAI workspace (D-688).

Studio is our Cartesia key, installed as the developer workspace's voice-only own key (BYOK
scope `voice`), and spoken by every agent whose `byok` is `workspace`; Clear agents are set to
`off` and stay on ThinnestAI's own voices whatever the workspace does (LIVE-DOCS
`docs.thinnest.ai/api-reference/agents/update-agent`, 8 Oct 2026; evaluation §12 item 1).

The ORDER of `enable_studio_voices` is the safety property. Turning voice-only BYOK on moves
every agent that is not `off` onto Cartesia at the Studio rate (evaluation §12, "What changes
for Calevate"), so every published agent that is not on a Studio voice is set to `off` and read
back FIRST, and nothing is switched on while any of them is not. Then our key is installed,
unless the workspace already holds a Cartesia voice key, then switched on, then read back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.hosted_voices import (
    STUDIO_VOICE_PROVIDER,
    own_voice_key_ready,
    withdraw_own_key_voices,
)
from apps.api.billing.engine_minutes import BYOK_VOICE_RATE_KEY
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.engine.catalogue import HostsVoices, OwnVoiceKeyState

log = get_logger(__name__)

#: Published vendor agents on this engine, and whether each was published on a Studio voice
#: (its route carries the own-voice-key rate key). Arms of a running experiment included.
_PUBLISHED_ROUTES_SQL: Final = (
    "SELECT engine_agent_ref, engine_rate_key = :studio_key FROM engine_agent_routes "
    "WHERE active AND engine = :engine ORDER BY engine_agent_ref"
)


@dataclass(frozen=True, slots=True)
class PublishedRoute:
    engine_agent_ref: str
    on_studio_voice: bool


async def published_routes(session: AsyncSession, *, engine: str) -> list[PublishedRoute]:
    rows = (
        await session.execute(
            text(_PUBLISHED_ROUTES_SQL), {"engine": engine, "studio_key": BYOK_VOICE_RATE_KEY}
        )
    ).all()
    return [PublishedRoute(engine_agent_ref=str(ref), on_studio_voice=bool(on)) for ref, on in rows]


@dataclass(frozen=True, slots=True)
class StudioSwitchResult:
    state: OwnVoiceKeyState
    #: Agents set to stay off our voice key before it was switched on.
    agents_kept_off: int
    #: Our Cartesia key was installed by this call (False: the workspace already held one).
    key_installed: bool


def _agents_not_kept_off(count: int) -> ProblemError:
    return ProblemError(
        kind="conflict",
        code="studio_agents_not_kept_off",
        title="Studio voices were not switched on",
        detail=(
            f"{count} published agent(s) could not be confirmed as staying on the voice "
            "platform's own voices, and switching Studio voices on would move them onto our "
            "Cartesia key at the Studio rate. Nothing was switched on."
        ),
        remediation="Try again. If it keeps failing, check those agents on the voice platform.",
    )


def _no_cartesia_key() -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code="studio_voice_key_missing",
        title="No Cartesia key is installed",
        detail="Studio voices speak on our Cartesia key, and none is set on this deployment.",
        remediation="Install the Cartesia API key in the ops console, then run this again.",
    )


async def enable_studio_voices(
    session: AsyncSession, engine: HostsVoices, *, model: str | None = None
) -> StudioSwitchResult:
    """Switch voice-only BYOK on in the workspace, in the order the module docstring argues.
    IDEMPOTENT: an agent already `off` is set again, an installed Cartesia key is kept."""
    routes = [
        r for r in await published_routes(session, engine=engine.name) if not r.on_studio_voice
    ]
    unconfirmed = 0
    for route in routes:
        try:
            await engine.set_agent_own_voice_key(route.engine_agent_ref, on=False)
            held = await engine.agent_own_voice_key(route.engine_agent_ref)
        except ProblemError as exc:
            log.warning("studio_enable_agent_not_set", extra={"reason": exc.code})
            held = None
        if held is not False:
            unconfirmed += 1
    if unconfirmed:
        raise _agents_not_kept_off(unconfirmed)
    state = await engine.own_key_state()
    installed = False
    if state.voice_provider != STUDIO_VOICE_PROVIDER:
        api_key = get_settings().cartesia_api_key
        if not api_key:
            raise _no_cartesia_key()
        await engine.install_own_voice_key(
            provider=STUDIO_VOICE_PROVIDER, api_key=api_key, model=model
        )
        installed = True
    await engine.enable_own_voice_key()
    state = await engine.own_key_state()
    log.info(
        "studio_voices_enabled",
        extra={
            "agents_kept_off": len(routes),
            "key_installed": installed,
            "ready": own_voice_key_ready(state),
        },
    )
    return StudioSwitchResult(state=state, agents_kept_off=len(routes), key_installed=installed)


async def disable_studio_voices(session: AsyncSession, engine: HostsVoices) -> OwnVoiceKeyState:
    """Switch voice-only BYOK off and take every Studio voice off offer. Agents on a Studio
    voice speak the platform's default voice from their next call. The caller commits."""
    state = await engine.disable_own_voice_key()
    await withdraw_own_key_voices(session)
    return state


__all__ = [
    "PublishedRoute",
    "StudioSwitchResult",
    "disable_studio_voices",
    "enable_studio_voices",
    "published_routes",
]
