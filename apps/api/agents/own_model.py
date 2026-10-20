"""Our own language model on ThinnestAI calls (D-764, D-834): Gemini on our Google key.

THE TWO SET-UPS (founder, 13 Oct 2026; every agent, free-trial ones included, 19 Oct 2026,
D-834), both switched OFF until `Settings.thinnest_own_model`:

* **Clear**: ThinnestAI's speech-to-text and voice, our model. The agent's `byok` is `llm`,
  billed at the voice band's own minute ("You pay the same per-minute voice plan as any other
  call", `thinnest-findings/mirror/snapshots/2026-10-13/pages/api-reference/
  bring-your-own-keys.md:21-24,31-33`), so its rate key stays the band's.
* **Studio**: ThinnestAI's speech-to-text, our Cartesia voice, our model. The agent's `byok`
  is `llm_voice`, a flat minute (:18-20,26-29) an operator attests as `byok_llm_voice`.

WHERE THE KEY LIVES. In each paying client's own workspace, installed and read back by
`ensure_own_model_in` the first time that client publishes on our model, in the order
`studio_voices.ensure_studio_in` uses for our Cartesia key (D-717). And in our developer
workspace, where free-trial agents live (D-697), by `ensure_developer_own_model`: the
operator's "Set up developer workspace" act, the hourly repair and a key rotation; a trial
publish only verifies it (`require_developer_own_model`), as a trial Studio publish verifies
our Cartesia key there (D-727). A customer workspace without a complete set of its own
inherits the developer's keys under the developer's DEFAULT scope (`thinnest-findings/
mirror/snapshots/2026-10-18/pages/api-reference/bring-your-own-keys.md:186-190`), and a
default already set is never moved here: it stays `voice` once Studio ready has run, so our
Google key there changes no agent that follows a workspace. Only an agent naming `llm` or
`llm_voice` uses it, and every agent we publish names its scope. A developer workspace whose
keys are off is switched on with `llm` after every agent that would follow it is set `off`,
as for a client workspace; Studio ready later moves that default to `voice`.

THE WORKSPACE SCOPE RULE. One workspace may hold Clear and Studio agents at once. A scope is
per agent ("one agent can run on `llm` ... while another runs on `llm_voice`", 2026-10-18
snapshot :82-90) and needs only that the workspace holds checked keys for it (:92-97); the
workspace default
applies only to an agent that follows it. So every agent names its scope and the default is
left as it is: a Studio workspace stays on `voice`, so a Studio agent not yet republished
keeps running, and billing, exactly as before; a workspace whose own keys are off is switched
on with `llm`, the only scope its own keys then cover (:271-274). A call already running keeps
its stack (:121-125).

WHICH MODEL. The Google models of `agents/llm_models.own_model_offerable_models` (permitted
on this leg, not limited by Google to earlier users, our Google key installed, price
attested: hard rule 7), chosen per agent by an operator as `byok:<model>` in
`agents.engine_model_id`, else `Settings.thinnest_own_model_default`. On calls ThinnestAI asks
a Gemini 2.5 or 3 model to think less (`snapshots/2026-10-18/.../bring-your-own-keys.md:
167-169`), which is why `gemini-3.1-flash-lite`, refused where our code runs a call, is
permitted here (D-817). A console default Google no longer serves to our project (a stored
Gemini 2.5 value) leaves readiness false and refuses every publish on our model rather than
placing calls that would fail.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Final, cast
from uuid import UUID

from calevate_shared.engine import VoiceEngine
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.llm_models import (
    own_model_offerable_models,
    unofferable_reason,
)
from apps.api.billing.engine_minutes import (
    ATTESTED_MINUTE_ENGINES,
    BYOK_LLM_VOICE_RATE_KEY,
    BYOK_VOICE_RATE_KEY,
    EngineRateKey,
    attested_rate_keys,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import joined_tenant_session, untenanted_session
from apps.api.engine.catalogue import HostsVoices, OwnVoiceKeyState, RunsOwnModel
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.ops.model_pricing import in_call_permitted_providers
from apps.api.tenancy.engine_workspace import (
    DeveloperOwnModelRecord,
    StudioWorkspace,
    active_workspaces_of,
    own_model_workspaces,
    read_developer_own_model,
    record_developer_own_model_check,
    record_own_model_check,
)

log = get_logger(__name__)

#: ThinnestAI's provider id for Google Gemini as an LLM key (`thinnest-findings/mirror/
#: snapshots/2026-10-13/pages/api-reference/bring-your-own-keys/add-byok-key.md:589-601`).
OWN_MODEL_PROVIDER: Final = "google"
#: How an agent's own-model choice is stored in `agents.engine_model_id`, beside the
#: engine's own model ids, as `byok:<id>` names a voice of our key in the voice catalogue.
OWN_MODEL_CHOICE_PREFIX: Final = "byok:"

#: A client publishing on our model reads this when its workspace could not be set up. No
#: vendor name (D-679).
OWN_MODEL_ACCOUNT_NOT_READY: Final = "own_model_account_not_ready"
OWN_MODEL_NOT_READY: Final = "own_model_not_ready"
OWN_MODEL_NOT_OFFERED: Final = "own_model_not_offered"


def own_model_on(engine: VoiceEngine) -> bool:
    """Do agents on `engine` answer on our model? The console switch, on ThinnestAI only."""
    from apps.api.agents.engine_choice import byok_in_force

    return (
        engine.name == "thinnest"
        and isinstance(engine, RunsOwnModel)
        and get_settings().thinnest_own_model
        and not byok_in_force(engine)
    )


def offerable_own_models() -> tuple[str, ...]:
    """The Google models an agent may run on our key right now, sorted."""
    return tuple(sorted(own_model_offerable_models()))


def own_model_choice_id(model: str) -> str:
    return f"{OWN_MODEL_CHOICE_PREFIX}{model}"


def own_model_of_choice(value: str | None) -> str | None:
    """The Google model an `engine_model_id` names, or None when it names an engine model."""
    if value is None or not value.startswith(OWN_MODEL_CHOICE_PREFIX):
        return None
    return value.removeprefix(OWN_MODEL_CHOICE_PREFIX)


def own_model_label(model: str) -> str:
    """An operator's name for a Google model id: `gemini-2.5-flash-lite` is "Gemini 2.5
    Flash-Lite (our key)"."""
    family, _, rest = model.partition("-")
    version, _, variant = rest.partition("-")
    words = "-".join(part.capitalize() for part in variant.split("-")) if variant else ""
    return f"{family.capitalize()} {version} {words} (our key)".replace("  ", " ")


def own_model_for(choice: str | None) -> str:
    """The model an agent answers with on our key: its own offerable choice, else the console
    default. A choice no longer offerable falls back to the default rather than failing a
    republish; the default itself is checked when the switch goes on and at every publish."""
    chosen = own_model_of_choice(choice)
    if chosen is not None and chosen in offerable_own_models():
        return chosen
    return get_settings().thinnest_own_model_default


def own_model_rate_key(rate_key: EngineRateKey) -> EngineRateKey:
    """The rate key a voice's minute bills at once the agent answers on our model: a Studio
    voice moves to the own-voice-and-model minute, a band voice keeps its band (:21-24)."""
    return BYOK_LLM_VOICE_RATE_KEY if rate_key == BYOK_VOICE_RATE_KEY else rate_key


def refuse_own_model_choice(engine: VoiceEngine, choice: str) -> None:
    """Refuse an agent's choice of one of our models (`byok:<id>`) unless our model is on and
    the model is offerable."""
    model = own_model_of_choice(choice)
    if model is None:
        return
    if not own_model_on(engine):
        raise ProblemError(
            kind="business_rule",
            code=OWN_MODEL_NOT_OFFERED,
            title="This language model cannot be used",
            detail="This language model is not available on this account.",
            remediation="Choose another model, or clear the choice to use the default.",
        )
    refuse_unofferable_own_model(model)


def refuse_unofferable_own_model(model: str) -> None:
    """Refuse a model our key may not run here, in a client's words (hard rule 7)."""
    if model in offerable_own_models():
        return
    log.warning("own_model_not_offered", extra={"model": model})
    raise ProblemError(
        kind="business_rule",
        code=OWN_MODEL_NOT_OFFERED,
        title="This language model cannot be used",
        detail=unofferable_reason(model, audience="client", own_model_call=True)
        or "This language model is not available on this account.",
        remediation="Choose another model, or clear the choice to use the default.",
    )


# --- readiness -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OwnModelReadiness:
    """Whether our model can be switched on for calls, and what is missing."""

    switched_on: bool
    default_model: str
    google_key: bool
    #: The default model is `own_model_offerable_models`: permitted on this leg, no Google
    #: access limit, its key installed and its price attested.
    default_offerable: bool
    #: Why it is not, for an operator; None when it is.
    default_reason: str | None
    #: The latest IN-CALL data-use attestation for our Google project (D-839, OPERATIONS §2
    #: gate 41) confirms the paid tier with log sharing off: raw caller speech goes through
    #: this key on every turn. The dashboard attestation is a separate statement.
    data_use_attested: bool
    #: The `byok_llm_voice` minute a Studio call on our model bills at is attested.
    llm_voice_minute_attested: bool
    #: What our developer workspace last answered about our Google key (D-834): free-trial
    #: agents answer on it there, and the switch-on republishes them.
    developer: DeveloperOwnModelRecord = field(
        default_factory=lambda: DeveloperOwnModelRecord(None, None, None)
    )
    offerable_models: tuple[str, ...] = ()
    workspaces: tuple[StudioWorkspace, ...] = field(default_factory=tuple)
    #: Client workspaces where switching our key on failed and never succeeded.
    pending: tuple[PendingWorkspace, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.google_key
            and self.default_offerable
            and self.data_use_attested
            and self.llm_voice_minute_attested
            and self.developer.ready
        )

    def missing(self) -> list[str]:
        """What an operator still has to do, in order."""
        steps = []
        if not self.google_key:
            steps.append("Save the Google (Gemini) API key in the ops console Secrets panel.")
        if not self.default_offerable:
            steps.append(
                f"Make {self.default_model} offerable: {self.default_reason or 'not offered'}."
            )
        if not self.data_use_attested:
            steps.append(
                "Attest that our Google project is on the paid tier with log sharing off "
                "for caller speech (Language models, In-call data use: google; OPERATIONS "
                "gate 41)."
            )
        if not self.llm_voice_minute_attested:
            steps.append("Attest the own-voice-and-model (byok_llm_voice) per-minute rate.")
        if not self.developer.ready:
            failed = (
                f" (last error: {self.developer.error_code})" if self.developer.error_code else ""
            )
            steps.append(
                "Set up our Google key in the developer workspace, where free-trial agents "
                f"live (Voices, Our own model, Set up developer workspace){failed}."
            )
        return steps


async def own_model_readiness(session: AsyncSession, *, engine: str) -> OwnModelReadiness:
    settings = get_settings()
    default = settings.thinnest_own_model_default
    reason = unofferable_reason(default, own_model_call=True)
    attested = (
        await attested_rate_keys(session, engine=engine, at=datetime.now(UTC))
        if engine in ATTESTED_MINUTE_ENGINES
        else frozenset()
    )
    failures = await own_model_failures()
    workspaces = tuple(
        replace(w, error_code=w.error_code or failures.get(w.tenant_id))
        for w in await own_model_workspaces()
    )
    enabled = frozenset(w.tenant_id for w in workspaces)
    return OwnModelReadiness(
        switched_on=settings.thinnest_own_model,
        default_model=default,
        google_key=bool(settings.gemini_api_key),
        default_offerable=reason is None,
        default_reason=reason,
        data_use_attested=OWN_MODEL_PROVIDER in await in_call_permitted_providers(session),
        llm_voice_minute_attested=BYOK_LLM_VOICE_RATE_KEY in attested,
        developer=await read_developer_own_model(session),
        offerable_models=offerable_own_models(),
        workspaces=workspaces,
        pending=tuple(await pending_own_model_workspaces(enabled, failures)),
    )


async def assert_own_model_ready(session: AsyncSession, value: object) -> None:
    """The console's refusal to switch our model on before it is ready. Switching off, and
    any write on another engine, is never refused."""
    if value is not True:
        return
    readiness = await own_model_readiness(session, engine="thinnest")
    if readiness.ready:
        return
    raise ProblemError(
        kind="business_rule",
        code=OWN_MODEL_NOT_READY,
        title="Our own model cannot be switched on yet",
        detail="Calls would answer on a key or at a price nobody has set up: "
        + " ".join(readiness.missing()),
        remediation="Finish those steps (ops Voices, Our own model shows each), then switch "
        "it on again.",
    )


async def assert_own_model_default_offerable(value: object) -> None:
    """The console default must be a Google model our key may run here."""
    if isinstance(value, str) and value not in offerable_own_models():
        raise ProblemError(
            kind="validation",
            code=OWN_MODEL_NOT_OFFERED,
            title="That model cannot answer calls on our key",
            detail=unofferable_reason(value, own_model_call=True)
            or "This model is not offered on this deployment.",
            remediation="Install the Google key and attest the model's price first, or choose "
            "another Gemini model.",
        )


# --- a client's own workspace -----------------------------------------------------------


def own_model_key_ready(state: OwnVoiceKeyState) -> bool:
    """Does the workspace hold our Google key, checked, with a model, and use its own keys?
    The one test of the vendor's report, used by the publish gate, the sweep and the console."""
    return (
        state.enabled
        and state.using == "own"
        and state.llm_provider == OWN_MODEL_PROVIDER
        and state.llm_model is not None
        and state.llm_verified
    )


def own_model_account_not_ready() -> ProblemError:
    return ProblemError(
        kind="dependency",
        code=OWN_MODEL_ACCOUNT_NOT_READY,
        title="This agent's language model could not be set up for this account",
        detail=(
            "This agent was not published and nothing changed for your callers. The language "
            "model needs a short setup on our side for this account, and it did not finish."
        ),
        remediation="Try publishing again in a few minutes. If it keeps failing, contact us.",
        status=503,
    )


def _no_google_key() -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code="own_model_key_missing",
        title="No Google key is installed",
        detail="Agents answer on our own model through our Google key, and none is set.",
        remediation="Install the Google (Gemini) API key in the ops console, then try again.",
    )


def _agents_not_kept_off(count: int) -> ProblemError:
    return ProblemError(
        kind="conflict",
        code="own_model_agents_not_kept_off",
        title="Our model key was not switched on",
        detail=(
            f"{count} published agent(s) that would follow this workspace's own keys could "
            "not be confirmed as staying on the voice platform's own model. Nothing was "
            "switched on."
        ),
        remediation="Try again. If it keeps failing, check those agents on the voice platform.",
    )


def _workspace_not_ready(state: OwnVoiceKeyState) -> ProblemError:
    log.warning(
        "own_model_workspace_not_ready",
        extra={
            "enabled": state.enabled,
            "scope": state.scope,
            "using": state.using,
            "llm_provider": state.llm_provider,
            "llm_verified": state.llm_verified,
        },
    )
    return ProblemError(
        kind="dependency",
        code="own_model_workspace_not_ready",
        title="Our model key did not switch on in the client's workspace",
        detail="The voice platform did not report our Google key as checked, with a model and "
        "in use in this client's workspace.",
        remediation="Try again. If it keeps failing, check the workspace's own keys on the "
        "voice platform.",
    )


def _holds_own_google_key(state: OwnVoiceKeyState) -> bool:
    """A checked Google key the workspace runs as its OWN. `using` decides ownership because a
    customer workspace inheriting from our developer workspace answers `using: developer`
    (bring-your-own-keys.md:225-227), and the page does not say whether it then lists the
    inherited credentials; installing again replaces a key of the same provider, keeping its
    model, so a needless install costs one request."""
    return (
        state.llm_provider == OWN_MODEL_PROVIDER
        and state.llm_verified
        and (state.using == "own" or (not state.enabled and state.using == "none"))
    )


async def _install_google_key(runs: RunsOwnModel) -> None:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise _no_google_key()
    await runs.install_own_model_key(
        provider=OWN_MODEL_PROVIDER,
        api_key=settings.gemini_api_key,
        model=settings.thinnest_own_model_default,
    )


async def _switch_on(
    session: AsyncSession, engine: HostsVoices, *, tenant_id: UUID, workspace: str
) -> OwnVoiceKeyState:
    """In `workspace`, in this order: install our key unless a checked Google key is there;
    when its own keys are off, keep its Clear agents that follow the workspace off and switch
    the keys on with `llm`; read it back. A workspace already on keeps its default scope."""
    from apps.api.agents.studio_voices import keep_clear_agents_off

    runs = cast(RunsOwnModel, engine)
    with in_workspace(workspace):
        state = await runs.own_key_state()
        if not own_model_key_ready(state):
            if not _holds_own_google_key(state):
                await _install_google_key(runs)
            if not state.enabled:
                unconfirmed = await keep_clear_agents_off(
                    session, engine, tenant_id=tenant_id, workspace=workspace
                )
                if unconfirmed:
                    raise _agents_not_kept_off(unconfirmed)
                await runs.enable_own_model_key()
            state = await runs.own_key_state()
        if not own_model_key_ready(state):
            return state
        return await align_key_model(runs, state)


#: The last own-model set-up or repair failure per client, by tenant id (D-839).
#:
#: In Redis rather than `tenant_engine_workspaces.own_model_error_code`, and the reason is
#: the transaction: the failure is raised into the caller's transaction, which rolls back,
#: so a row written there was always lost and a client whose set-up failed never showed on
#: the card. A second database connection would nest under the caller's (the session
#: nesting gate) and, on a Studio publish that has already updated this workspace row,
#: wait on the caller that waits on it. A Redis loss forgets only this hint; the next
#: publish or retry writes it again.
_FAILURES_KEY: Final = "calevate:own_model_setup_failures"


@dataclass(frozen=True, slots=True)
class PendingWorkspace:
    """An active client workspace where switching our Google key on failed and never
    succeeded: not on our key yet, with the code of its last failure."""

    tenant_id: UUID
    workspace_id: str
    error_code: str


async def _remember_failure(tenant_id: UUID, error_code: str) -> None:
    try:
        await cast(
            "Awaitable[int]", get_redis().hset(_FAILURES_KEY, str(tenant_id), error_code[:64])
        )
    except RedisError as exc:
        log.warning(
            "own_model_failure_unrecorded",
            extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
        )


async def forget_own_model_failure(tenant_id: UUID) -> None:
    try:
        await cast("Awaitable[int]", get_redis().hdel(_FAILURES_KEY, str(tenant_id)))
    except RedisError as exc:
        log.warning(
            "own_model_failure_not_cleared",
            extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
        )


async def own_model_failures() -> dict[UUID, str]:
    """Each client's last own-model failure code; empty when Redis cannot answer."""
    try:
        raw = await cast("Awaitable[dict[str, str]]", get_redis().hgetall(_FAILURES_KEY))
    except RedisError as exc:
        log.warning("own_model_failures_unreadable", extra={"error": type(exc).__name__})
        return {}
    return {UUID(str(tenant)): str(code) for tenant, code in raw.items()}


async def pending_own_model_workspaces(
    enabled: frozenset[UUID], failures: dict[UUID, str]
) -> list[PendingWorkspace]:
    """Active client workspaces never confirmed on our key whose last attempt failed, in
    tenant order: the card lists them as not on our key yet so an operator can retry."""
    return [
        PendingWorkspace(row.tenant_id, row.workspace_id, failures[row.tenant_id])
        for row in await active_workspaces_of(sorted(failures))
        if row.workspace_id is not None
        and row.tenant_id in failures
        and row.tenant_id not in enabled
    ]


async def ensure_own_model_in(
    session: AsyncSession,
    engine: HostsVoices,
    *,
    tenant_id: UUID,
    workspace: str,
    audience: str = "client",
) -> OwnVoiceKeyState:
    """Our Google key installed, checked and in use in this client's workspace, read back.
    IDEMPOTENT: a workspace that already answers ready is only recorded as checked. A pass
    is written in the caller's tenant session, so a publish that fails later rolls it back.
    A failure is remembered outside that transaction (`_FAILURES_KEY`) and refused: to a
    client with a sentence naming no vendor, to an operator with the cause."""
    if not isinstance(engine, RunsOwnModel):
        raise own_model_account_not_ready()
    try:
        state = await _switch_on(session, engine, tenant_id=tenant_id, workspace=workspace)
        if not own_model_key_ready(state):
            raise _workspace_not_ready(state)
    except ProblemError as exc:
        await _remember_failure(tenant_id, exc.code)
        log.warning(
            "own_model_workspace_enable_failed",
            extra={"tenant_id": str(tenant_id), "reason": exc.code},
        )
        if audience == "client":
            raise own_model_account_not_ready() from exc
        raise
    await record_own_model_check(session, tenant_id, error_code=None)
    await forget_own_model_failure(tenant_id)
    log.info("own_model_workspace_ready", extra={"tenant_id": str(tenant_id)})
    return state


async def ensure_own_model_workspace(
    engine: HostsVoices, *, tenant_id: UUID, workspace: str, audience: str = "client"
) -> OwnVoiceKeyState:
    """`ensure_own_model_in` in the tenant's own session (the sweep and the ops act)."""
    async with joined_tenant_session(tenant_id) as session:
        return await ensure_own_model_in(
            session, engine, tenant_id=tenant_id, workspace=workspace, audience=audience
        )


# --- our developer workspace: free-trial agents (D-834) ----------------------------------


def _developer_not_ready(state: OwnVoiceKeyState) -> ProblemError:
    log.warning(
        "own_model_developer_not_ready",
        extra={
            "enabled": state.enabled,
            "scope": state.scope,
            "using": state.using,
            "llm_provider": state.llm_provider,
            "llm_verified": state.llm_verified,
        },
    )
    return ProblemError(
        kind="dependency",
        code="own_model_developer_not_ready",
        title="Our model key did not switch on in our developer workspace",
        detail="The voice platform did not report our Google key as checked, with a model and "
        "in use in our developer workspace, where free-trial agents live.",
        remediation="Run Set up developer workspace again (Voices, Our own model). If it keeps "
        "failing, check the developer workspace's own keys on the voice platform.",
    )


async def ensure_developer_own_model(
    session: AsyncSession, engine: HostsVoices
) -> OwnVoiceKeyState:
    """Our Google key installed, checked and in use in our developer workspace, read back.
    IDEMPOTENT: a workspace that already answers ready is only recorded as checked.

    In this order: install our key unless the workspace runs a checked Google key of its own;
    if its own keys are off, set every published agent that would follow them `off` and read
    each back (`studio_voices.keep_inheriting_agents_off`: the developer workspace's and
    those of customer workspaces that inherit it, :186-190), then switch them on with `llm`;
    read back. A switch already on keeps its default scope. `session` must see every tenant's
    routes (an operator's or a worker's untenanted session). The outcome is recorded on
    `platform_state` either way; a failure is raised with its cause, for an operator."""
    from apps.api.agents.studio_voices import keep_inheriting_agents_off

    if not isinstance(engine, RunsOwnModel):
        raise own_model_account_not_ready()
    try:
        state = await engine.own_key_state()
        if not own_model_key_ready(state):
            if not _holds_own_google_key(state):
                await _install_google_key(engine)
            if not state.enabled:
                unconfirmed = await keep_inheriting_agents_off(session, engine)
                if unconfirmed:
                    raise _agents_not_kept_off(unconfirmed)
                await engine.enable_own_model_key()
            state = await engine.own_key_state()
            if not own_model_key_ready(state):
                raise _developer_not_ready(state)
        state = await align_key_model(engine, state)
    except ProblemError as exc:
        # In a session of its own: the caller's rolls back with the raise, and the console
        # and the switch-on readiness read this record.
        async with untenanted_session() as own:
            await record_developer_own_model_check(own, error_code=exc.code)
        log.warning("own_model_developer_enable_failed", extra={"reason": exc.code})
        raise
    await record_developer_own_model_check(session, error_code=None)
    log.info("own_model_developer_ready")
    return state


async def align_key_model(runs: RunsOwnModel, state: OwnVoiceKeyState) -> OwnVoiceKeyState:
    """The key of the workspace being acted in runs the console default model, read back.

    A workspace whose default scope is `voice` (our developer workspace, D-727, and a
    client's Studio workspace, D-717) is refused a per-agent model (`PUT /agents/{id}/
    byok-model` answers `409`, set-agent-byok-model.md:514-518), so its agents on our key run
    the KEY's model. A key left on an earlier default after the console default changed would
    make every such publish refuse, so the key follows the default. Only the default: an
    operator's per-agent choice is honoured by `PUT byok-model` where the scope allows it."""
    wanted = get_settings().thinnest_own_model_default
    if state.llm_model == wanted:
        return state
    await runs.set_own_model_key_model(wanted)
    state = await runs.own_key_state()
    log.info("own_model_key_model_aligned", extra={"model": state.llm_model})
    return state


async def require_developer_own_model(engine: HostsVoices) -> OwnVoiceKeyState:
    """A free-trial agent's publish on our model: our developer workspace must answer ready,
    its key on the console default model (`align_key_model`). The keys are never
    installed or switched on from a client's request (they are platform-wide); the operator's
    set-up and the hourly repair do that. Refused to the client in words naming no vendor."""
    if not isinstance(engine, RunsOwnModel):
        raise own_model_account_not_ready()
    state = await engine.own_key_state()
    if not own_model_key_ready(state):
        log.warning(
            "own_model_trial_publish_developer_not_ready",
            extra={"using": state.using, "llm_provider": state.llm_provider},
        )
        raise own_model_account_not_ready()
    return await align_key_model(engine, state)


__all__ = [
    "OWN_MODEL_ACCOUNT_NOT_READY",
    "OWN_MODEL_CHOICE_PREFIX",
    "OWN_MODEL_NOT_OFFERED",
    "OWN_MODEL_NOT_READY",
    "OWN_MODEL_PROVIDER",
    "OwnModelReadiness",
    "PendingWorkspace",
    "align_key_model",
    "assert_own_model_default_offerable",
    "assert_own_model_ready",
    "ensure_developer_own_model",
    "ensure_own_model_in",
    "ensure_own_model_workspace",
    "forget_own_model_failure",
    "offerable_own_models",
    "own_model_account_not_ready",
    "own_model_choice_id",
    "own_model_failures",
    "own_model_for",
    "own_model_key_ready",
    "own_model_label",
    "own_model_of_choice",
    "own_model_on",
    "own_model_rate_key",
    "own_model_readiness",
    "pending_own_model_workspaces",
    "refuse_own_model_choice",
    "refuse_unofferable_own_model",
    "require_developer_own_model",
]
