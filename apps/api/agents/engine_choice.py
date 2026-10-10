"""An agent's voice and model on an engine that HOSTS them: check it, and price it.

On an engine that dictates its speech and model legs (ThinnestAI), an agent names one of the
voices the engine hosts that an operator offered (`agents.engine_voice_id`, our catalogue id,
`agents/hosted_voices.py`) and may name one of the engine's models (`agents.engine_model_id`).
Both are checked here before anything is written to the vendor, and the answer is the rate
key the agent's minutes are metered at:

* nothing chosen — `platform`, with no read, which is every agent's path on other engines;
* a voice — its rate key: the engine's band sold as Clear (`Settings.thinnest_clear_voice_band`)
  or a voice of our own Cartesia key (`byok_voice`, sold as Studio), D-687, D-688. A voice
  the operator has not added and enabled, that the engine no longer lists, or whose minute is
  unattested is refused
  (hard rule 7, through `billing/engine_minutes.attested_rate_keys`).

A PUBLISH also refuses an agent with no voice (`engine_voice_required`) and the workspace on
all three of its own keys (`engine_own_keys_not_on_sale`). Whether our Cartesia key is on in
the client's own workspace is not decided here: the publish switches it on there and reads it
back (`agents/studio_voices.ensure_studio_workspace`, D-717).

The refusals are in the CLIENT's audience: a publish refusal can reach a client's screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from calevate_shared.engine import VoiceEngine
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.engine_catalogue_offer import NOT_ON_OFFER_CLIENT, model_unofferable_reason
from apps.api.agents.hosted_voices import (
    STUDIO_VOICE_PROVIDER,
    HostedVoiceRow,
    hosted_voice_unofferable_reason,
    read_hosted_voice,
)
from apps.api.agents.voice_offer import tts_price_is_billable
from apps.api.billing.engine_minutes import BASE_RATE_KEY, EngineRateKey, attested_rate_keys
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.engine import get_engine
from apps.api.engine.catalogue import EngineCatalogue, HoldsCatalogue, HostsVoices, ReportsOwnKeys
from apps.api.engine.hosted_platform import engine_platform_label

log = get_logger(__name__)

#: Machine codes (the last segment of the problem `type`).
VOICE_CHOICE_NOT_OFFERED: Final = "engine_voice_choice_not_offered"
MODEL_CHOICE_NOT_OFFERED: Final = "engine_model_choice_not_offered"
CATALOGUE_INCOMPLETE: Final = "engine_catalogue_incomplete"
VOICE_NOT_IN_CATALOGUE: Final = "engine_voice_not_in_catalogue"
VOICE_TIER_UNPRICED: Final = "engine_voice_tier_unpriced"
MODEL_NOT_IN_CATALOGUE: Final = "engine_model_not_in_catalogue"
MODEL_NOT_CALL_CAPABLE: Final = "engine_model_not_call_capable"
MODEL_NOT_ON_PLAN: Final = "engine_model_not_on_plan"
#: A Studio voice runs the call on the engine's low-cost models only (D-687).
MODEL_NOT_WITH_OWN_VOICE: Final = "engine_model_not_with_studio_voice"
CHOICE_UNDER_BYOK: Final = "engine_choice_under_byok"
VOICE_NOT_ON_OFFER: Final = "engine_voice_not_on_offer"
VOICE_REQUIRED: Final = "engine_voice_required"
KEYS_NOT_ON_SALE: Final = "engine_own_keys_not_on_sale"
#: The operator's `THINNEST_BYOK_ENABLED` and the vendor's `GET /byok` disagree.
KEYS_MODE_MISMATCH: Final = "engine_byok_mismatch"
#: A free-trial account's agents live in our developer workspace, whose own-keys switch stays
#: off (D-697, D-717), so they speak Clear voices only.
STUDIO_AFTER_GO_LIVE: Final = "studio_after_go_live"
#: What a trial account reads wherever Studio is held from it. No vendor name (D-679).
STUDIO_AFTER_GO_LIVE_NOTE: Final = "Studio voices are available once you go live."

#: The sentence the pickers lock on, and the refusal's detail. No vendor name: a client reads it.
BYOK_CHOICE_NOTE: Final = (
    "This account's voice platform runs on the account's own speech, model and voice "
    "keys, so the voice and the language model are set once for the whole account and "
    "cannot be chosen per agent."
)


def byok_in_force(engine: VoiceEngine) -> bool:
    """Does `engine`'s own (developer) workspace run on all three of its own keys
    (`Settings.thinnest_byok_enabled`)? Then a per-agent choice does not apply and every
    minute is the `platform` rate. Not voice-only BYOK, which is how the Studio rung is sold,
    per agent (D-688)."""
    return engine.name == "thinnest" and get_settings().thinnest_byok_enabled


def refuse_choice_under_byok(
    engine: VoiceEngine, *, voice_id: str | None, model_id: str | None
) -> None:
    if (voice_id is not None or model_id is not None) and byok_in_force(engine):
        raise _refusal(
            CHOICE_UNDER_BYOK,
            title="The voice and model are set for the whole account",
            detail=BYOK_CHOICE_NOTE,
            remediation="Leave the voice and model on the platform default for this agent.",
        )


async def _require_keys_mode_matches(engine: VoiceEngine) -> None:
    """Refuse a publish when the operator's BYOK setting and the vendor's disagree.

    The setting decides which rate a publish stamps and whether a catalogue voice is sent;
    the vendor decides which keys actually run the call and what it bills. Either
    disagreement mis-prices every minute.
    """
    if not isinstance(engine, ReportsOwnKeys):
        return
    if await engine.own_keys_in_use() != byok_in_force(engine):
        raise _refusal(
            KEYS_MODE_MISMATCH,
            title="The account's key setting does not match the voice platform",
            detail=(
                "The voice platform's own-keys mode and this account's setting for it "
                "disagree, so this agent's calls could not be priced correctly."
            ),
            remediation="Contact us before publishing this agent.",
        )


def _refusal(code: str, *, title: str, detail: str, remediation: str) -> ProblemError:
    log.warning("agent_engine_choice_refused", extra={"reason": code})
    return ProblemError(
        kind="business_rule", code=code, title=title, detail=detail, remediation=remediation
    )


def _not_offered(code: str, what: str) -> ProblemError:
    return _refusal(
        code,
        title=f"This account does not choose a {what} this way",
        detail=(
            f"The voice platform this account uses runs Calevate's own {what}s, so a "
            f"{what} from the platform's own list cannot be set."
        ),
        remediation=f"Choose the {what} from the agent's voice and model settings instead.",
    )


def _incomplete() -> ProblemError:
    return _refusal(
        CATALOGUE_INCOMPLETE,
        title="The voice platform's list could not be read in full",
        detail="We could not confirm the chosen model is on the platform's list.",
        remediation="Try again. If it keeps failing, contact us.",
    )


def _not_in_catalogue() -> ProblemError:
    return _refusal(
        VOICE_NOT_IN_CATALOGUE,
        title="This voice is not offered",
        detail="The chosen voice is not on this account's list of voices.",
        remediation="Choose a voice from the list on the agent's voice settings.",
    )


@dataclass(frozen=True, slots=True)
class HostedChoice:
    """A checked voice: its catalogue row, and so its source and rate key."""

    row: HostedVoiceRow

    @property
    def rate_key(self) -> EngineRateKey:
        return self.row.rate_key

    @property
    def speaks_own_key(self) -> bool:
        return self.row.source == "byok"


async def _check_voice(
    session: AsyncSession, voice_id: str, *, attested: frozenset[str], platform: str
) -> HostedChoice:
    try:
        row = await read_hosted_voice(session, voice_id)
    except ProblemError:
        raise _not_in_catalogue() from None
    if not row.offered:
        raise _refusal(
            VOICE_NOT_ON_OFFER,
            title="This voice is not on offer",
            detail=NOT_ON_OFFER_CLIENT,
            remediation="Choose another voice from the list.",
        )
    reason = hosted_voice_unofferable_reason(
        row,
        attested=attested,
        voice_key_priced=tts_price_is_billable(STUDIO_VOICE_PROVIDER),
        platform=platform,
        audience="client",
    )
    if reason is not None:
        raise _refusal(
            VOICE_TIER_UNPRICED,
            title="This voice has not been priced yet",
            detail=reason,
            remediation="Choose another voice.",
        )
    return HostedChoice(row=row)


def _check_model(
    catalogue: EngineCatalogue,
    model_id: str,
    *,
    attested: frozenset[str],
    platform: str,
    with_own_voice: bool,
    voice_rate_key: str | None = None,
) -> None:
    model = next((m for m in catalogue.models if m.model_id == model_id), None)
    if model is None:
        if not catalogue.complete:
            raise _incomplete()
        raise _refusal(
            MODEL_NOT_IN_CATALOGUE,
            title="This language model is not offered",
            detail="The chosen model is not on the voice platform's list for this account.",
            remediation="Choose another model, or clear the choice to use the default.",
        )
    reason = model_unofferable_reason(
        model, attested=attested, platform=platform, audience="client"
    )
    if reason is not None:
        code = MODEL_NOT_CALL_CAPABLE if not model.call_capable else MODEL_NOT_ON_PLAN
        raise _refusal(
            code,
            title="This language model cannot be used",
            detail=reason,
            remediation="Choose another model, or clear the choice to use the default.",
        )
    if model.surcharge == "premium" and voice_rate_key not in _AT_LEAST_PREMIUM:
        # The model lifts the call to the Premium band; a voice sold below it would meter
        # the minute at a lower rate than the engine charges.
        raise _refusal(
            MODEL_ABOVE_VOICE_RATE,
            title="This language model costs more than this voice's rate",
            detail="Calls on this model are charged at a higher rate than the chosen voice.",
            remediation="Choose another model, or clear the choice to use the default.",
        )
    if with_own_voice and not model.voice_only_byok:
        # A call speaking our own voice key runs only on the engine's low-cost models, and
        # setting another is refused with a 400 (snapshots/2026-10-07b/pages/api-reference/
        # bring-your-own-keys.md:44-63).
        raise _refusal(
            MODEL_NOT_WITH_OWN_VOICE,
            title="This language model cannot be used with a Studio voice",
            detail="A Studio voice runs the call on the platform's standard models only.",
            remediation="Choose a standard model, or clear the choice to use the default.",
        )


def refuse_studio_on_trial() -> ProblemError:
    """The refusal a free-trial account gets for a Studio voice at publish."""
    return _refusal(
        STUDIO_AFTER_GO_LIVE,
        title="Studio voices are available once you go live",
        detail=(
            "During the free trial your agents speak Clear voices. You can still play the "
            "Studio voices to hear them."
        ),
        remediation="Choose a Clear voice for now, or add credit from Billing to go live.",
    )


async def require_engine_choice(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    voice_id: str | None,
    model_id: str | None,
    for_publish: bool = False,
) -> EngineRateKey:
    """Refuse a choice the engine cannot run or we cannot price; else its rate key.

    `for_publish` adds what only a publish needs: on an engine that hosts its voices an
    agent must name one (the platform default speaks a voice nobody priced), the developer
    workspace must not be on all three of its own keys. A draft save may leave the voice empty.
    """
    caps = engine.capabilities
    refuse_choice_under_byok(engine, voice_id=voice_id, model_id=model_id)
    hosts = isinstance(engine, HostsVoices) and not caps.is_ours("tts")
    if for_publish and hosts:
        await _require_keys_mode_matches(engine)
        if byok_in_force(engine):
            raise _refusal(
                KEYS_NOT_ON_SALE,
                title="Calls on the account's own keys are not on sale yet",
                detail=(
                    "This account's voice platform is set to run on the account's own "
                    "speech, model and voice keys, and calls in that mode are not on sale "
                    "yet."
                ),
                remediation="Contact us before publishing this agent.",
            )
        if voice_id is None:
            raise _refusal(
                VOICE_REQUIRED,
                title="Choose a voice before publishing",
                detail="This agent has no voice chosen, so its calls cannot be priced.",
                remediation="Choose a voice from the list on the agent's voice settings.",
            )
    if voice_id is not None and caps.is_ours("tts"):
        raise _not_offered(VOICE_CHOICE_NOT_OFFERED, "voice")
    if model_id is not None and caps.is_ours("llm"):
        raise _not_offered(MODEL_CHOICE_NOT_OFFERED, "language model")
    if voice_id is None and model_id is None:
        return BASE_RATE_KEY
    hosting = engine if isinstance(engine, HostsVoices) else None
    holder = engine if isinstance(engine, HoldsCatalogue) else None
    if voice_id is not None and hosting is None:
        raise _not_offered(VOICE_CHOICE_NOT_OFFERED, "voice")
    if model_id is not None and holder is None:
        raise _not_offered(MODEL_CHOICE_NOT_OFFERED, "language model")
    attested = await attested_rate_keys(session, engine=engine.name, at=datetime.now(UTC))
    platform = engine_platform_label(engine)
    choice: HostedChoice | None = None
    if voice_id is not None and hosting is not None:
        choice = await _check_voice(session, voice_id, attested=attested, platform=platform)
    if model_id is not None and holder is not None:
        _check_model(
            await holder.read_catalogue(),
            model_id,
            attested=attested,
            platform=platform,
            with_own_voice=choice is not None and choice.speaks_own_key,
            voice_rate_key=choice.rate_key if choice is not None else None,
        )
    return BASE_RATE_KEY if choice is None else choice.rate_key


#: Refused when the in-call default setting names a model the engine would not run a call on.
IN_CALL_DEFAULT_UNUSABLE: Final = "engine_in_call_default_unusable"
#: A model that lifts the call to a dearer band than the chosen voice is sold at.
MODEL_ABOVE_VOICE_RATE: Final = "engine_model_above_voice_rate"
#: The voice rate keys a Premium-band model may run beside: the minute is metered at the
#: voice's key, so it must be at least the band the model lifts the call to.
_AT_LEAST_PREMIUM: Final = frozenset({"premium", "studio"})


def in_call_default_model(engine: VoiceEngine, *, voice_id: str | None) -> str | None:
    """The in-call model an agent that chose none is sent (`thinnest_in_call_default_model`).

    Only on ThinnestAI and only while the workspace is not on all three of its own keys. A
    Studio voice (our voice key) gets it too (D-717): a voice-only BYOK call runs only on the
    vendor's `voiceOnlyByok` models, GPT-OSS 120B among them (`bring-your-own-keys.md:44-58`),
    and `resolve_in_call_default` refuses a default outside that list, so the setting can
    never make a Studio agent unpublishable. `None` (the setting unset, its default) keeps
    the vendor default, Prana [Voice] (update-agent.md:539-545).
    """
    del voice_id  # Clear and Studio alike since D-717; kept so callers state the voice.
    if engine.name != "thinnest" or byok_in_force(engine) or engine.capabilities.is_ours("llm"):
        return None
    return get_settings().thinnest_in_call_default_model


async def resolve_in_call_default(value: str | None) -> str | None:
    """The model id to store for the in-call default, or a refusal.

    Accepts the model's id or its console name ("GPT-OSS 120B"), because ThinnestAI
    documents names but not every id, and stores the id the live `GET /models` gives for it,
    so publish, drift and the read-back all compare ids. Refuses a model the engine does not
    list as call-capable on our plan, whose price band is not on record, or that a Studio
    agent may not run (`voiceOnlyByok` false: setting it on a voice-only BYOK agent is a 400,
    `bring-your-own-keys.md:60-63`), so the console cannot point any agent at a model the
    vendor would refuse or bill unpriced. The stricter rule is deliberate (D-717): applying
    the default to Clear only would leave Studio agents on Prana [Voice].
    Off ThinnestAI there is nothing to check.
    """
    engine = get_engine()
    if value is None or engine.name != "thinnest" or not isinstance(engine, HoldsCatalogue):
        return value
    catalogue = await engine.read_catalogue()
    wanted = value.strip()
    model = next((m for m in catalogue.models if m.model_id == wanted), None) or next(
        (m for m in catalogue.models if m.label.casefold() == wanted.casefold()), None
    )
    clear_band = get_settings().thinnest_clear_voice_band
    if (
        model is not None
        and model.call_capable
        and model.plan_allows
        and model.surcharge is not None
        and (model.surcharge == "none" or clear_band in _AT_LEAST_PREMIUM)
        and model.voice_only_byok
    ):
        return model.model_id
    if model is None and not catalogue.complete:
        raise _incomplete()
    raise ProblemError(
        kind="validation",
        code=IN_CALL_DEFAULT_UNUSABLE,
        title="That model cannot answer calls on this account",
        detail=(
            "The voice platform does not list this model as fast enough for calls, available "
            "on the current plan and allowed with Studio voices, or its per-minute price is "
            "not on record."
            if model is not None
            else "The voice platform lists no model with this id or name."
        ),
        remediation=(
            "Choose a model the platform's list marks as usable for calls and with Studio "
            "voices, such as GPT-OSS 120B."
        ),
    )


async def engine_rate_key_for(
    session: AsyncSession, engine: VoiceEngine, *, voice_id: str | None, model_id: str | None
) -> EngineRateKey:
    """`require_engine_choice` for the agent a publish is about to send."""
    return await require_engine_choice(
        session, engine, voice_id=voice_id, model_id=model_id, for_publish=True
    )


__all__ = [
    "BYOK_CHOICE_NOTE",
    "CATALOGUE_INCOMPLETE",
    "CHOICE_UNDER_BYOK",
    "IN_CALL_DEFAULT_UNUSABLE",
    "KEYS_MODE_MISMATCH",
    "KEYS_NOT_ON_SALE",
    "MODEL_ABOVE_VOICE_RATE",
    "MODEL_CHOICE_NOT_OFFERED",
    "MODEL_NOT_CALL_CAPABLE",
    "MODEL_NOT_IN_CATALOGUE",
    "MODEL_NOT_ON_PLAN",
    "MODEL_NOT_WITH_OWN_VOICE",
    "STUDIO_AFTER_GO_LIVE",
    "STUDIO_AFTER_GO_LIVE_NOTE",
    "VOICE_CHOICE_NOT_OFFERED",
    "VOICE_NOT_IN_CATALOGUE",
    "VOICE_NOT_ON_OFFER",
    "VOICE_REQUIRED",
    "VOICE_TIER_UNPRICED",
    "HostedChoice",
    "byok_in_force",
    "engine_rate_key_for",
    "in_call_default_model",
    "refuse_choice_under_byok",
    "refuse_studio_on_trial",
    "require_engine_choice",
    "resolve_in_call_default",
]
