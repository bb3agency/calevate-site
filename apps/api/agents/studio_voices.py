"""Studio voices on ThinnestAI: our Cartesia key, switched on only in the customer workspace of
each client that uses Studio (D-717, superseding D-688/D-693's developer-workspace switch).

WHY NOT ONE SWITCH IN THE DEVELOPER WORKSPACE. A customer that brings no key of its own runs
on the developer workspace's keys and scope while BYOK is on there, and every agent follows
the workspace unless it is `byok: "off"` (`thinnest-findings/mirror/snapshots/2026-10-08/
pages/api-reference/bring-your-own-keys.md:67-80,129-133`; re-read live at
docs.thinnest.ai/api-reference/bring-your-own-keys, 10 Oct 2026). One forgotten `off` in any
client's workspace would then speak Cartesia on our key at the Studio rate. So the developer
workspace's switch stays OFF and our key goes only where Studio is sold: "A customer can bring
a complete set of its own for that choice (three keys, or a voice key), which then overrides
yours … A customer with its own complete set and its own switch on keeps using its own"
(:132-133). Every BYOK request "also works for a customer, with the `Thinnest-Workspace`
header" (:137). That a customer's own key works while the developer's switch is OFF is
stated, not yet proved by a call: OPERATIONS gate T-22.

THREE PLACES, THREE JOBS:

* the DEVELOPER workspace HOLDS our key with its switch off (`prepare_studio`), so the key is
  checked by the provider once and an operator can see it is in place. It cannot list or
  preview Cartesia voices: `GET /byok/voices` and its preview answer `409` "when the
  workspace is not using its own keys" (`bring-your-own-keys/list-byok-voices.md:7,376-385`;
  `preview-byok-voice.md:396-397`; both re-read live 10 Oct 2026).
* each STUDIO CLIENT's workspace gets the key, the switch (`scope: voice`) and a read-back,
  automatically and idempotently, when its first Studio agent publishes
  (`ensure_studio_workspace`). Before switching on, every published non-Studio agent of that
  workspace is set `off` and read back, because switching on moves every agent that is not.
* the catalogue lists and previews Studio voices through the first Studio client workspace
  that answers ready (`studio_listing_workspace`). Before any client runs Studio, an
  operator names the first one in "Studio ready" (`prepare_studio(..., tenant_id=)`).

A client with no Studio agent left keeps the key and the switch: every Clear agent is sent
`byok: "off"` on every publish and repaired by the drift sweep, so a switched-on workspace
costs nothing while nothing follows it, and switching off would make the next Studio publish
pay the whole setup again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.hosted_voices import (
    STUDIO_VOICE_PROVIDER,
    own_voice_key_ready,
    studio_listing_workspace,
    studio_voices_ready,
)
from apps.api.agents.voice_offer import tts_price_is_billable
from apps.api.billing.engine_minutes import BYOK_VOICE_RATE_KEY, attested_rate_keys
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import joined_tenant_session
from apps.api.engine.catalogue import HostsVoices, OwnVoiceKeyState
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.tenancy.engine_workspace import (
    StudioWorkspace,
    record_studio_check,
    resolve_workspace,
    studio_workspaces,
)

log = get_logger(__name__)

#: Published vendor agents on this engine, and whether each was published on a Studio voice
#: (its route carries the own-voice-key rate key). Arms of a running experiment included.
_PUBLISHED_ROUTES_SQL: Final = (
    "SELECT engine_agent_ref, engine_rate_key = :studio_key, tenant_id FROM engine_agent_routes "
    "WHERE active AND engine = :engine ORDER BY engine_agent_ref"
)


@dataclass(frozen=True, slots=True)
class PublishedRoute:
    engine_agent_ref: str
    on_studio_voice: bool
    tenant_id: UUID | None = None


async def published_routes(session: AsyncSession, *, engine: str) -> list[PublishedRoute]:
    rows = (
        await session.execute(
            text(_PUBLISHED_ROUTES_SQL), {"engine": engine, "studio_key": BYOK_VOICE_RATE_KEY}
        )
    ).all()
    return [
        PublishedRoute(
            engine_agent_ref=str(ref),
            on_studio_voice=bool(on),
            tenant_id=UUID(str(tid)) if tid is not None else None,
        )
        for ref, on, tid in rows
    ]


# --- refusals ----------------------------------------------------------------------------

#: A client publishing a Studio agent reads this when its workspace could not be switched
#: on. No vendor name (D-679).
STUDIO_ACCOUNT_NOT_READY: Final = "studio_account_not_ready"


def studio_account_not_ready() -> ProblemError:
    return ProblemError(
        kind="dependency",
        code=STUDIO_ACCOUNT_NOT_READY,
        title="Studio voices could not be set up for this account",
        detail=(
            "This agent was not published and nothing changed for your callers. Studio "
            "voices need a short setup on our side for this account, and it did not finish."
        ),
        remediation=(
            "Try publishing again in a few minutes, or choose a Clear voice. If it keeps "
            "failing, contact us."
        ),
        status=503,
    )


def _agents_not_kept_off(count: int) -> ProblemError:
    return ProblemError(
        kind="conflict",
        code="studio_agents_not_kept_off",
        title="Studio voices were not switched on",
        detail=(
            f"{count} published agent(s) in this client's workspace could not be confirmed "
            "as staying on the voice platform's own voices, and switching Studio on there "
            "would move them onto our Cartesia key at the Studio rate. Nothing was switched on."
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


# --- a client's own workspace --------------------------------------------------------------


async def _keep_clear_agents_off(
    session: AsyncSession, engine: HostsVoices, *, tenant_id: UUID, workspace: str
) -> int:
    """Set every published non-Studio agent of `tenant_id` living in `workspace` to `byok:
    off` and read each back. Answers how many could not be confirmed."""
    unconfirmed = 0
    for route in await published_routes(session, engine=engine.name):
        if route.on_studio_voice or route.tenant_id != tenant_id:
            continue
        if scope_of(route.engine_agent_ref) != workspace:
            continue
        try:
            await engine.set_agent_own_voice_key(route.engine_agent_ref, on=False)
            held = await engine.agent_own_voice_key(route.engine_agent_ref)
        except ProblemError as exc:
            log.warning("studio_enable_agent_not_set", extra={"reason": exc.code})
            held = None
        if held is not False:
            unconfirmed += 1
    return unconfirmed


async def _switch_on(
    session: AsyncSession,
    engine: HostsVoices,
    *,
    tenant_id: UUID,
    workspace: str,
    model: str | None,
) -> OwnVoiceKeyState:
    """In `workspace`, in this order: keep its Clear agents off, install our key unless a
    Cartesia voice key is already there, switch voice-only BYOK on, read it back."""
    with in_workspace(workspace):
        state = await engine.own_key_state()
        if own_voice_key_ready(state):
            return state
        unconfirmed = await _keep_clear_agents_off(
            session, engine, tenant_id=tenant_id, workspace=workspace
        )
        if unconfirmed:
            raise _agents_not_kept_off(unconfirmed)
        if state.voice_provider != STUDIO_VOICE_PROVIDER:
            api_key = get_settings().cartesia_api_key
            if not api_key:
                raise _no_cartesia_key()
            await engine.install_own_voice_key(
                provider=STUDIO_VOICE_PROVIDER, api_key=api_key, model=model
            )
        await engine.enable_own_voice_key()
        return await engine.own_key_state()


async def ensure_studio_workspace(
    engine: HostsVoices,
    *,
    tenant_id: UUID,
    workspace: str,
    model: str | None = None,
    audience: str = "client",
) -> OwnVoiceKeyState:
    """Our Cartesia key installed and switched on (voice only) in this client's workspace,
    read back as `using: own`, complete, with a Cartesia voice key. IDEMPOTENT: a workspace
    that already answers ready is only recorded as checked. The record is written in the
    tenant's session (joining the caller's transaction, so a publish that fails later rolls
    it back; the vendor's own state is the truth and is re-read next time).

    A failure is recorded and refused: to a client (`audience="client"`) with a sentence
    naming no vendor, to an operator with the cause."""
    async with joined_tenant_session(tenant_id) as session:
        return await ensure_studio_in(
            session, engine, tenant_id=tenant_id, workspace=workspace, model=model, audience=audience
        )


async def ensure_studio_in(
    session: AsyncSession,
    engine: HostsVoices,
    *,
    tenant_id: UUID,
    workspace: str,
    model: str | None = None,
    audience: str = "client",
) -> OwnVoiceKeyState:
    """`ensure_studio_workspace` in a tenant session the caller already holds for
    `tenant_id`. A publish passes its own, so the check costs no second pooled connection
    under a request that already holds two (`scripts/check_session_nesting`)."""
    try:
        state = await _switch_on(session, engine, tenant_id=tenant_id, workspace=workspace, model=model)
        if not own_voice_key_ready(state):
            log.warning(
                "studio_workspace_not_ready",
                extra={
                    "tenant_id": str(tenant_id),
                    "enabled": state.enabled,
                    "scope": state.scope,
                    "complete": state.complete,
                    "using": state.using,
                    "voice_provider": state.voice_provider,
                },
            )
            raise ProblemError(
                kind="dependency",
                code="studio_workspace_not_ready",
                title="Studio did not switch on in the client's workspace",
                detail=(
                    "The voice platform did not report our Cartesia key as on, complete "
                    "and in use for the voice in this client's workspace."
                ),
                remediation="Try again. If it keeps failing, check the workspace's own "
                "keys on the voice platform.",
            )
    except ProblemError as exc:
        await record_studio_check(session, tenant_id, error_code=exc.code)
        log.warning(
            "studio_workspace_enable_failed",
            extra={"tenant_id": str(tenant_id), "reason": exc.code},
        )
        if audience == "client":
            raise studio_account_not_ready() from exc
        raise
    await record_studio_check(session, tenant_id, error_code=None)
    log.info("studio_workspace_ready", extra={"tenant_id": str(tenant_id)})
    return state


# --- the developer workspace: "Studio ready" -----------------------------------------------


@dataclass(frozen=True, slots=True)
class StudioReadiness:
    """Whether Studio can be sold on this deployment, and what is missing."""

    console_key: bool
    #: The developer workspace holds a Cartesia voice key (its switch is a separate fact).
    developer_holds_key: bool
    #: The developer workspace's BYOK switch is ON. Never by our hand since D-717; a legacy
    #: of the old "Enable Studio voices", migrated off in `switch_developer_off`.
    developer_switch_on: bool
    minute_attested: bool
    synthesis_priced: bool
    voices_listed: bool
    workspaces: tuple[StudioWorkspace, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.console_key
            and self.developer_holds_key
            and self.minute_attested
            and self.synthesis_priced
            and self.voices_listed
        )

    def missing(self) -> list[str]:
        """What an operator still has to do, in order."""
        steps = []
        if not self.console_key:
            steps.append("Save the Cartesia API key in the ops console Secrets panel.")
        if not self.developer_holds_key:
            steps.append("Run Studio ready to hold the key in our developer workspace.")
        if not self.minute_attested:
            steps.append("Attest the voice-only own-key (byok_voice) per-minute rate.")
        if not self.synthesis_priced:
            steps.append("Attest the Cartesia TTS price.")
        if not self.voices_listed:
            steps.append(
                "List Studio voices: run Studio ready naming the first client to use Studio."
            )
        return steps


async def studio_readiness(
    session: AsyncSession, engine: HostsVoices, *, developer: OwnVoiceKeyState | None = None
) -> StudioReadiness:
    state = developer if developer is not None else await engine.own_key_state()
    attested = await attested_rate_keys(session, engine=engine.name, at=datetime.now(UTC))
    return StudioReadiness(
        console_key=bool(get_settings().cartesia_api_key),
        developer_holds_key=state.voice_provider == STUDIO_VOICE_PROVIDER,
        developer_switch_on=state.enabled,
        minute_attested=BYOK_VOICE_RATE_KEY in attested,
        synthesis_priced=tts_price_is_billable(STUDIO_VOICE_PROVIDER),
        voices_listed=await studio_voices_ready(session),
        workspaces=tuple(await studio_workspaces()),
    )


@dataclass(frozen=True, slots=True)
class StudioPrepared:
    readiness: StudioReadiness
    #: Our key was installed in the developer workspace by this call.
    key_installed: bool
    #: The client whose workspace was switched on by this call, when one was named.
    tenant_id: UUID | None = None


async def prepare_studio(
    session: AsyncSession,
    engine: HostsVoices,
    *,
    model: str | None = None,
    tenant_id: UUID | None = None,
) -> StudioPrepared:
    """THE "STUDIO READY" ACT. Holds our Cartesia key in the developer workspace with its
    switch untouched (`PUT /byok/credentials` stores a checked key whatever the switch; its
    only `409` is "BYOK is on, and this key would leave a job without a model",
    `bring-your-own-keys.md:190-194`), unless a Cartesia voice key is already there. With
    `tenant_id`, also switches Studio on in that client's own workspace, which is how the
    first Studio voices become listable. Never switches the developer workspace on.
    IDEMPOTENT."""
    api_key = get_settings().cartesia_api_key
    if not api_key:
        raise _no_cartesia_key()
    state = await engine.own_key_state()
    installed = False
    if state.voice_provider != STUDIO_VOICE_PROVIDER:
        await engine.install_own_voice_key(
            provider=STUDIO_VOICE_PROVIDER, api_key=api_key, model=model
        )
        installed = True
        state = await engine.own_key_state()
    if tenant_id is not None:
        async with joined_tenant_session(tenant_id) as tenant:
            workspace = await resolve_workspace(tenant, tenant_id)
        if workspace is None:
            raise ProblemError(
                kind="business_rule",
                code="engine_workspace_not_provisioned",
                title="That client has no voice workspace yet",
                detail="Studio is switched on in a client's own workspace, and this client "
                "has none that is active.",
                remediation="Choose a client whose workspace is active.",
            )
        await ensure_studio_workspace(
            engine, tenant_id=tenant_id, workspace=workspace, model=model, audience="operator"
        )
    readiness = await studio_readiness(session, engine, developer=state)
    log.info(
        "studio_prepared",
        extra={
            "key_installed": installed,
            "developer_switch_on": readiness.developer_switch_on,
            "ready": readiness.ready,
            "tenant_id": str(tenant_id) if tenant_id else None,
        },
    )
    return StudioPrepared(readiness=readiness, key_installed=installed, tenant_id=tenant_id)


# --- migrating off the developer-workspace switch ------------------------------------------


@dataclass(frozen=True, slots=True)
class StudioClientNotMoved:
    tenant_id: UUID | None
    reason: str


async def clients_not_moved(
    session: AsyncSession, engine: HostsVoices
) -> list[StudioClientNotMoved]:
    """Every published Studio agent that would stop speaking if the developer workspace's
    switch went off now: one living in the developer workspace itself (made before D-693, or
    a trial's), or one whose client workspace does not answer ready on its own key."""
    blockers: list[StudioClientNotMoved] = []
    checked: dict[str, bool] = {}
    for route in await published_routes(session, engine=engine.name):
        if not route.on_studio_voice:
            continue
        workspace = scope_of(route.engine_agent_ref)
        if workspace is None:
            blockers.append(
                StudioClientNotMoved(route.tenant_id, "agent lives in the developer workspace")
            )
            continue
        if workspace not in checked:
            with in_workspace(workspace):
                state = await engine.own_key_state()
            checked[workspace] = state.using == "own" and own_voice_key_ready(state)
        if not checked[workspace]:
            blockers.append(
                StudioClientNotMoved(route.tenant_id, "workspace not on its own Cartesia key")
            )
    return blockers


async def switch_developer_off(session: AsyncSession, engine: HostsVoices) -> OwnVoiceKeyState:
    """Switch the developer workspace's BYOK off — the last step of the migration off the
    old "Enable Studio voices" — only once no published Studio agent depends on it. The key
    stays held there. Refused with `studio_clients_not_moved` naming how many would go
    silent; the runbook says how to move each (`runbooks/thinnest-studio-voices.md`)."""
    blockers = await clients_not_moved(session, engine)
    if blockers:
        raise ProblemError(
            kind="conflict",
            code="studio_clients_not_moved",
            title="Some Studio agents still depend on the developer workspace",
            detail=(
                f"{len(blockers)} published Studio agent(s) would stop speaking their voice: "
                + "; ".join(sorted({b.reason for b in blockers}))
                + "."
            ),
            remediation=(
                "Republish each of those agents (which switches Studio on in its client's own "
                "workspace), then run this again."
            ),
        )
    return await engine.disable_own_voice_key()


__all__ = [
    "STUDIO_ACCOUNT_NOT_READY",
    "PublishedRoute",
    "StudioClientNotMoved",
    "StudioPrepared",
    "StudioReadiness",
    "clients_not_moved",
    "ensure_studio_in",
    "ensure_studio_workspace",
    "prepare_studio",
    "published_routes",
    "studio_account_not_ready",
    "studio_listing_workspace",
    "studio_readiness",
    "switch_developer_off",
]
