"""Studio voices on ThinnestAI: our Cartesia key, switched on (voice-only BYOK) in our developer
workspace, where trial agents live (D-727), and in the customer workspace of each paying client
that uses Studio (D-717).

WHAT A SWITCHED-ON WORKSPACE DOES. With BYOK on, an agent whose `byok` is `workspace` (the
vendor's default) speaks on our key, and one set `off` never does and bills at the vendor's own
rate (`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/
bring-your-own-keys.md:69-79,304-306`). A customer workspace that brings no key of its own
inherits the developer workspace's keys and switch (:128-133). So every agent we publish states
`byok` (the adapter refuses one that does not, `engine_agent_byok_unstated`), and before any
switch goes on every published non-Studio agent that would follow it is set `off` and read back.

THREE PLACES, THREE JOBS:

* the DEVELOPER workspace holds our key with its switch ON (`ensure_developer_studio`, run by
  the ops "Studio ready" act and repaired by the hourly check), so a free-trial agent can
  publish on a Studio voice with `byok: workspace`, and Studio voices are listed and
  previewed there. A trial publish only verifies the switch (`require_developer_studio`); it
  never switches a platform-wide setting on from a client's request.
* each paying STUDIO CLIENT's workspace gets the key, the switch (`scope: voice`) and a
  read-back, automatically and idempotently, when its first Studio agent publishes
  (`ensure_studio_workspace`). A client workspace with its own complete key keeps using it
  (:132-133), so rotation and repair are per workspace.
* the catalogue lists and previews Studio voices in the first workspace that answers ready,
  the developer one first (`hosted_voices.studio_listing_workspace`).

A client with no Studio agent left keeps the key and the switch: every Clear agent is sent
`byok: "off"` on every publish and repaired by the drift sweep, so a switched-on workspace
costs nothing while nothing follows it.
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
    studio_voices_ready,
)
from apps.api.agents.voice_offer import tts_price_is_billable
from apps.api.billing.engine_minutes import (
    BYOK_VOICE_RATE_KEY,
    OWN_VOICE_RATE_KEYS,
    attested_rate_keys,
)
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

#: Published vendor agents on this engine, their rate key and the model of our key each
#: answers with. Arms of a running experiment included.
_PUBLISHED_ROUTES_SQL: Final = (
    "SELECT engine_agent_ref, engine_rate_key, tenant_id, engine_own_model "
    "FROM engine_agent_routes WHERE active AND engine = :engine ORDER BY engine_agent_ref"
)


@dataclass(frozen=True, slots=True)
class PublishedRoute:
    engine_agent_ref: str
    on_studio_voice: bool
    tenant_id: UUID | None = None
    #: The model of our key it answers with (D-764); None on the engine's own model. Such an
    #: agent names its own `byok` scope and follows no workspace switch.
    own_model: str | None = None


async def published_routes(session: AsyncSession, *, engine: str) -> list[PublishedRoute]:
    rows = (await session.execute(text(_PUBLISHED_ROUTES_SQL), {"engine": engine})).all()
    return [
        PublishedRoute(
            engine_agent_ref=str(ref),
            on_studio_voice=key in OWN_VOICE_RATE_KEYS,
            tenant_id=UUID(str(tid)) if tid is not None else None,
            own_model=str(model) if model else None,
        )
        for ref, key, tid, model in rows
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
            f"{count} published agent(s) that would follow this workspace's switch could not "
            "be confirmed as staying on the voice platform's own voices, and switching Studio "
            "on would move them onto our Cartesia key. Nothing was switched on."
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


async def _set_off_and_confirm(engine: HostsVoices, route: PublishedRoute) -> bool:
    try:
        with in_workspace(scope_of(route.engine_agent_ref)):
            await engine.set_agent_own_voice_key(route.engine_agent_ref, on=False)
            held = await engine.agent_own_voice_key(route.engine_agent_ref)
    except ProblemError as exc:
        log.warning("studio_enable_agent_not_set", extra={"reason": exc.code})
        held = None
    return held is False


async def keep_clear_agents_off(
    session: AsyncSession, engine: HostsVoices, *, tenant_id: UUID, workspace: str
) -> int:
    """Set every published non-Studio agent of `tenant_id` living in `workspace` that would
    follow the workspace's switch to `byok: off` and read each back. An agent on our model
    names its own scope (`llm`) and is left alone. Answers how many could not be confirmed."""
    unconfirmed = 0
    for route in await published_routes(session, engine=engine.name):
        if route.on_studio_voice or route.own_model or route.tenant_id != tenant_id:
            continue
        if scope_of(route.engine_agent_ref) != workspace:
            continue
        if not await _set_off_and_confirm(engine, route):
            unconfirmed += 1
    return unconfirmed


async def _keep_inheriting_agents_off(session: AsyncSession, engine: HostsVoices) -> int:
    """Before the developer workspace's switch goes on: set every published non-Studio agent
    that would follow it to `byok: off` and read each back. That is every such agent in the
    developer workspace, and in each customer workspace not on a key of its own, which
    inherits the developer one's (:128-133). Answers how many could not be confirmed."""
    on_own_key: dict[str, bool] = {}
    unconfirmed = 0
    for route in await published_routes(session, engine=engine.name):
        if route.on_studio_voice or route.own_model:
            continue
        workspace = scope_of(route.engine_agent_ref)
        if workspace is not None:
            if workspace not in on_own_key:
                try:
                    with in_workspace(workspace):
                        on_own_key[workspace] = own_voice_key_ready(await engine.own_key_state())
                except ProblemError as exc:
                    log.warning("studio_enable_workspace_unreadable", extra={"reason": exc.code})
                    on_own_key[workspace] = False
            if on_own_key[workspace]:
                continue
        if not await _set_off_and_confirm(engine, route):
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
        unconfirmed = await keep_clear_agents_off(
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
            session,
            engine,
            tenant_id=tenant_id,
            workspace=workspace,
            model=model,
            audience=audience,
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
        state = await _switch_on(
            session, engine, tenant_id=tenant_id, workspace=workspace, model=model
        )
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


# --- the developer workspace: "Studio ready" and trial agents (D-727) --------------------


def _developer_not_ready(state: OwnVoiceKeyState) -> ProblemError:
    log.warning(
        "studio_developer_not_ready",
        extra={
            "enabled": state.enabled,
            "scope": state.scope,
            "complete": state.complete,
            "using": state.using,
            "voice_provider": state.voice_provider,
        },
    )
    return ProblemError(
        kind="dependency",
        code="studio_developer_not_ready",
        title="Studio did not switch on in our developer workspace",
        detail=(
            "The voice platform did not report our Cartesia key as on, complete and in use "
            "for the voice in our developer workspace."
        ),
        remediation="Run Studio ready again. If it keeps failing, check the developer "
        "workspace's own keys on the voice platform.",
    )


async def ensure_developer_studio(
    session: AsyncSession, engine: HostsVoices, *, model: str | None = None
) -> OwnVoiceKeyState:
    """Our Cartesia key installed and switched on (voice only) in our developer workspace,
    read back ready. IDEMPOTENT: a workspace that already answers ready is left alone.

    In this order: every published non-Studio agent that would follow the switch is set
    `off` and read back (refused, nothing switched, if any cannot be confirmed); the key is
    installed unless a Cartesia voice key is there; the switch goes on with `scope: voice`;
    the state is read back. `session` must see every tenant's routes (an operator's or a
    worker's untenanted session)."""
    state = await engine.own_key_state()
    if own_voice_key_ready(state):
        return state
    unconfirmed = await _keep_inheriting_agents_off(session, engine)
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
    state = await engine.own_key_state()
    if not own_voice_key_ready(state):
        raise _developer_not_ready(state)
    log.info("studio_developer_ready")
    return state


async def require_developer_studio(engine: HostsVoices) -> None:
    """A trial agent's Studio publish: our developer workspace must answer ready. Read live,
    never switched on from here; the operator's Studio ready and the hourly repair do that."""
    state = await engine.own_key_state()
    if not own_voice_key_ready(state):
        log.warning("studio_trial_publish_developer_not_ready", extra={"using": state.using})
        raise studio_account_not_ready()


@dataclass(frozen=True, slots=True)
class StudioReadiness:
    """Whether Studio can be sold on this deployment, and what is missing."""

    console_key: bool
    #: The developer workspace holds a Cartesia voice key.
    developer_holds_key: bool
    #: The developer workspace speaks on that key for the voice: switched on, scope voice,
    #: complete and in use (D-727).
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
            and self.developer_switch_on
            and self.minute_attested
            and self.synthesis_priced
            and self.voices_listed
        )

    def missing(self) -> list[str]:
        """What an operator still has to do, in order."""
        steps = []
        if not self.console_key:
            steps.append("Save the Cartesia API key in the ops console Secrets panel.")
        if not (self.developer_holds_key and self.developer_switch_on):
            steps.append("Run Studio ready to switch our key on in the developer workspace.")
        if not self.minute_attested:
            steps.append("Attest the voice-only own-key (byok_voice) per-minute rate.")
        if not self.synthesis_priced:
            steps.append("Attest the Cartesia TTS price.")
        if not self.voices_listed:
            steps.append("Run Studio ready again to list the Studio voices.")
        return steps


async def studio_readiness(
    session: AsyncSession, engine: HostsVoices, *, developer: OwnVoiceKeyState | None = None
) -> StudioReadiness:
    state = developer if developer is not None else await engine.own_key_state()
    attested = await attested_rate_keys(session, engine=engine.name, at=datetime.now(UTC))
    return StudioReadiness(
        console_key=bool(get_settings().cartesia_api_key),
        developer_holds_key=state.voice_provider == STUDIO_VOICE_PROVIDER,
        developer_switch_on=own_voice_key_ready(state),
        minute_attested=BYOK_VOICE_RATE_KEY in attested,
        synthesis_priced=tts_price_is_billable(STUDIO_VOICE_PROVIDER),
        voices_listed=await studio_voices_ready(session),
        workspaces=tuple(await studio_workspaces()),
    )


@dataclass(frozen=True, slots=True)
class StudioPrepared:
    readiness: StudioReadiness
    #: The developer workspace was not ready and this call switched it on.
    developer_switched_on: bool
    #: The client whose workspace was switched on by this call, when one was named.
    tenant_id: UUID | None = None


async def prepare_studio(
    session: AsyncSession,
    engine: HostsVoices,
    *,
    model: str | None = None,
    tenant_id: UUID | None = None,
) -> StudioPrepared:
    """THE "STUDIO READY" ACT. Switches our Cartesia key on in the developer workspace
    (`ensure_developer_studio`), which is where trial agents speak Studio and where the
    voices are listed. With `tenant_id`, also switches Studio on in that paying client's own
    workspace ahead of its first Studio publish. IDEMPOTENT."""
    if not get_settings().cartesia_api_key:
        raise _no_cartesia_key()
    before = await engine.own_key_state()
    state = await ensure_developer_studio(session, engine, model=model)
    if tenant_id is not None:
        async with joined_tenant_session(tenant_id) as tenant:
            workspace = await resolve_workspace(tenant, tenant_id)
        if workspace is None:
            raise ProblemError(
                kind="business_rule",
                code="engine_workspace_not_provisioned",
                title="That client has no voice workspace yet",
                detail="Studio is switched on in a paying client's own workspace, and this "
                "client has none that is active.",
                remediation="Choose a client whose workspace is active.",
            )
        await ensure_studio_workspace(
            engine, tenant_id=tenant_id, workspace=workspace, model=model, audience="operator"
        )
    readiness = await studio_readiness(session, engine, developer=state)
    switched = not own_voice_key_ready(before)
    log.info(
        "studio_prepared",
        extra={
            "developer_switched_on": switched,
            "ready": readiness.ready,
            "tenant_id": str(tenant_id) if tenant_id else None,
        },
    )
    return StudioPrepared(readiness=readiness, developer_switched_on=switched, tenant_id=tenant_id)


__all__ = [
    "STUDIO_ACCOUNT_NOT_READY",
    "PublishedRoute",
    "StudioPrepared",
    "StudioReadiness",
    "ensure_developer_studio",
    "ensure_studio_in",
    "ensure_studio_workspace",
    "keep_clear_agents_off",
    "prepare_studio",
    "published_routes",
    "require_developer_studio",
    "studio_account_not_ready",
    "studio_readiness",
]
