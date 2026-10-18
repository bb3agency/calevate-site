"""Our own language model on ThinnestAI calls (D-764): Gemini on our Google key.

THE TWO SET-UPS (founder, 13 Oct 2026), both switched OFF until `Settings.thinnest_own_model`:

* **Clear**: ThinnestAI's speech-to-text and voice, our model. The agent's `byok` is `llm`,
  billed at the voice band's own minute ("You pay the same per-minute voice plan as any other
  call", `thinnest-findings/mirror/snapshots/2026-10-13/pages/api-reference/
  bring-your-own-keys.md:21-24,31-33`), so its rate key stays the band's.
* **Studio**: ThinnestAI's speech-to-text, our Cartesia voice, our model. The agent's `byok`
  is `llm_voice`, a flat minute (:18-20,26-29) an operator attests as `byok_llm_voice`.

WHERE THE KEY LIVES. In each paying client's own workspace, installed and read back by
`ensure_own_model_in` the first time that client publishes on our model, in the order
`studio_voices.ensure_studio_in` uses for our Cartesia key (D-717). Never in our developer
workspace: a customer workspace without keys of its own inherits the developer's (:180-184),
so a key there would reach every client that has none. Free-trial agents, which live in the
developer workspace (D-697), stay on ThinnestAI's model.

THE WORKSPACE SCOPE RULE. One workspace may hold Clear and Studio agents at once. A scope is
per agent ("one agent can run on `llm` ... while another runs on `llm_voice`", :88-90) and
needs only that the workspace holds checked keys for it (:92-97); the workspace default
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

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, cast
from uuid import UUID

from calevate_shared.engine import VoiceEngine
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.llm_models import (
    dashboard_data_use_attested,
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
from apps.api.core.settings import get_settings
from apps.api.db.session import joined_tenant_session
from apps.api.engine.catalogue import HostsVoices, OwnVoiceKeyState, RunsOwnModel
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.tenancy.engine_workspace import (
    StudioWorkspace,
    own_model_workspaces,
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
    #: An operator attested our Google project is on the paid tier with log sharing off
    #: (OPERATIONS §2 gate 41): raw caller speech goes through this key on every turn.
    data_use_attested: bool
    #: The `byok_llm_voice` minute a Studio call on our model bills at is attested.
    llm_voice_minute_attested: bool
    offerable_models: tuple[str, ...] = ()
    workspaces: tuple[StudioWorkspace, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.google_key
            and self.default_offerable
            and self.data_use_attested
            and self.llm_voice_minute_attested
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
                "(Models, dashboard data use: google; OPERATIONS gate 41)."
            )
        if not self.llm_voice_minute_attested:
            steps.append("Attest the own-voice-and-model (byok_llm_voice) per-minute rate.")
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
    return OwnModelReadiness(
        switched_on=settings.thinnest_own_model,
        default_model=default,
        google_key=bool(settings.gemini_api_key),
        default_offerable=reason is None,
        default_reason=reason,
        data_use_attested=OWN_MODEL_PROVIDER in dashboard_data_use_attested(),
        llm_voice_minute_attested=BYOK_LLM_VOICE_RATE_KEY in attested,
        offerable_models=offerable_own_models(),
        workspaces=tuple(await own_model_workspaces()),
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
        if own_model_key_ready(state):
            return state
        if not (state.llm_provider == OWN_MODEL_PROVIDER and state.llm_verified):
            settings = get_settings()
            if not settings.gemini_api_key:
                raise _no_google_key()
            await runs.install_own_model_key(
                provider=OWN_MODEL_PROVIDER,
                api_key=settings.gemini_api_key,
                model=settings.thinnest_own_model_default,
            )
        if not state.enabled:
            unconfirmed = await keep_clear_agents_off(
                session, engine, tenant_id=tenant_id, workspace=workspace
            )
            if unconfirmed:
                raise _agents_not_kept_off(unconfirmed)
            await runs.enable_own_model_key()
        return await runs.own_key_state()


async def ensure_own_model_in(
    session: AsyncSession,
    engine: HostsVoices,
    *,
    tenant_id: UUID,
    workspace: str,
    audience: str = "client",
) -> OwnVoiceKeyState:
    """Our Google key installed, checked and in use in this client's workspace, read back.
    IDEMPOTENT: a workspace that already answers ready is only recorded as checked. Written
    in the caller's tenant session, so a publish that fails later rolls the record back.
    A failure is recorded and refused: to a client with a sentence naming no vendor, to an
    operator with the cause."""
    if not isinstance(engine, RunsOwnModel):
        raise own_model_account_not_ready()
    try:
        state = await _switch_on(session, engine, tenant_id=tenant_id, workspace=workspace)
        if not own_model_key_ready(state):
            raise _workspace_not_ready(state)
    except ProblemError as exc:
        await record_own_model_check(session, tenant_id, error_code=exc.code)
        log.warning(
            "own_model_workspace_enable_failed",
            extra={"tenant_id": str(tenant_id), "reason": exc.code},
        )
        if audience == "client":
            raise own_model_account_not_ready() from exc
        raise
    await record_own_model_check(session, tenant_id, error_code=None)
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


__all__ = [
    "OWN_MODEL_ACCOUNT_NOT_READY",
    "OWN_MODEL_CHOICE_PREFIX",
    "OWN_MODEL_NOT_OFFERED",
    "OWN_MODEL_NOT_READY",
    "OWN_MODEL_PROVIDER",
    "OwnModelReadiness",
    "assert_own_model_default_offerable",
    "assert_own_model_ready",
    "ensure_own_model_in",
    "ensure_own_model_workspace",
    "offerable_own_models",
    "own_model_account_not_ready",
    "own_model_choice_id",
    "own_model_for",
    "own_model_key_ready",
    "own_model_label",
    "own_model_of_choice",
    "own_model_on",
    "own_model_rate_key",
    "own_model_readiness",
    "refuse_own_model_choice",
    "refuse_unofferable_own_model",
]
