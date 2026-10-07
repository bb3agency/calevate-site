"""An agent's voice and model from the ENGINE'S OWN catalogue: check it, and price it (D-678).

On an engine that dictates its speech and model legs (ThinnestAI), an agent may name one of
the engine's own voices (`agents.engine_voice_id`) and models (`agents.engine_model_id`).
Both are checked here against a live read of the catalogue, before anything is written to
the vendor, and the answer is the rate key the agent's minutes are metered at:

* nothing chosen — `platform`, with no catalogue read, which is every agent's path before
  this existed;
* a voice — its `price_band` (`standard` / `premium` / `studio`), because the engine bills a
  call at the band of the voice it speaks (`thinnest-findings/mirror/pages/api-reference/
  voices-and-models.md:30-31`). An unattested band is refused: a minute nobody priced may
  not be sold (hard rule 7, through `billing/engine_minutes.engine_minute_is_billable`).

Which bands a client may be sold is a founder decision (D-681, 7 Oct 2026): on ThinnestAI
only Premium, billed as the Clear rung (`billing/engine_minutes.CLIENT_RUNG_OF_RATE_KEY`).
A Standard or Studio voice is refused (`engine_voice_not_on_offer`), and a PUBLISH also
refuses an agent with no voice (`engine_voice_required`) and the workspace-keys mode
(`engine_own_keys_not_on_sale`), since neither names a band that is on sale.

The refusals reuse `engine_catalogue_offer`'s sentences in the CLIENT's audience: a publish
refusal can reach a client's screen, and the operator wording names the vendor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, cast

from calevate_shared.engine import AgentConfig, VoiceEngine
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.engine_catalogue_offer import (
    NOT_ON_OFFER_CLIENT,
    model_unofferable_reason,
    voice_unofferable_reason,
)
from apps.api.billing.engine_minutes import (
    BASE_RATE_KEY,
    ENGINE_RATE_KEYS,
    EngineRateKey,
    attested_rate_keys,
    sold_rate_keys,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.engine.catalogue import EngineCatalogue, HoldsCatalogue, ReportsOwnKeys
from apps.api.engine.hosted_platform import engine_platform_label

log = get_logger(__name__)

#: Machine codes (the last segment of the problem `type`).
VOICE_CHOICE_NOT_OFFERED: Final = "engine_voice_choice_not_offered"
MODEL_CHOICE_NOT_OFFERED: Final = "engine_model_choice_not_offered"
CATALOGUE_INCOMPLETE: Final = "engine_catalogue_incomplete"
VOICE_NOT_IN_CATALOGUE: Final = "engine_voice_not_in_catalogue"
VOICE_TIER_UNPRICED: Final = "engine_voice_tier_unpriced"
VOICE_TIER_UNKNOWN: Final = "engine_voice_tier_unknown"
MODEL_NOT_IN_CATALOGUE: Final = "engine_model_not_in_catalogue"
MODEL_NOT_CALL_CAPABLE: Final = "engine_model_not_call_capable"
MODEL_NOT_ON_PLAN: Final = "engine_model_not_on_plan"
CHOICE_UNDER_BYOK: Final = "engine_choice_under_byok"
VOICE_NOT_ON_OFFER: Final = "engine_voice_not_on_offer"
VOICE_REQUIRED: Final = "engine_voice_required"
KEYS_NOT_ON_SALE: Final = "engine_own_keys_not_on_sale"
#: The operator's `THINNEST_BYOK_ENABLED` and the vendor's `GET /byok` disagree.
KEYS_MODE_MISMATCH: Final = "engine_byok_mismatch"

#: The sentence the pickers lock on, and the refusal's detail. No vendor name: a client reads it.
BYOK_CHOICE_NOTE: Final = (
    "This account's voice platform runs on the account's own speech, model and voice "
    "keys, so the voice and the language model are set once for the whole account and "
    "cannot be chosen per agent."
)


def byok_in_force(engine: VoiceEngine) -> bool:
    """Does `engine` run on the workspace's own keys (`Settings.thinnest_byok_enabled`)? Then
    a per-agent catalogue choice does not apply and every minute is the `platform` rate."""
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
    disagreement mis-prices every minute: the ₹1 BYOK rate on calls billed at catalogue
    rates, or a catalogue voice that does not speak while the client is billed for it.
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
        detail="We could not confirm the chosen voice or model is on the platform's list.",
        remediation="Try again. If it keeps failing, contact us.",
    )


def _check_voice(
    catalogue: EngineCatalogue,
    voice_id: str,
    *,
    attested: frozenset[str],
    platform: str,
    sold: frozenset[str] | None,
) -> EngineRateKey:
    voice = next((v for v in catalogue.voices if v.voice_id == voice_id), None)
    if voice is None:
        if not catalogue.complete:
            raise _incomplete()
        raise _refusal(
            VOICE_NOT_IN_CATALOGUE,
            title="This voice is not offered",
            detail="The chosen voice is not on the voice platform's list for this account.",
            remediation="Choose another voice, or clear the choice to use the default.",
        )
    if voice.price_band not in ENGINE_RATE_KEYS:
        # A band we hold no rate key for cannot be attested, so it can never be priced.
        log.warning("agent_engine_voice_band_unknown", extra={"band": voice.price_band})
        raise _refusal(
            VOICE_TIER_UNKNOWN,
            title="This voice cannot be priced",
            detail="The chosen voice is in a price band Calevate does not meter.",
            remediation="Choose another voice, or clear the choice to use the default.",
        )
    if sold is not None and voice.price_band not in sold:
        raise _refusal(
            VOICE_NOT_ON_OFFER,
            title="This voice is not on offer yet",
            detail=NOT_ON_OFFER_CLIENT,
            remediation="Choose another voice from the list.",
        )
    reason = voice_unofferable_reason(
        voice, attested=attested, platform=platform, audience="client", sold=sold
    )
    if reason is not None:
        raise _refusal(
            VOICE_TIER_UNPRICED,
            title="This voice has not been priced yet",
            detail=reason,
            remediation="Choose another voice, or clear the choice to use the default.",
        )
    return cast(EngineRateKey, voice.price_band)


def _check_model(
    catalogue: EngineCatalogue, model_id: str, *, attested: frozenset[str], platform: str
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
    if reason is None:
        return
    code = MODEL_NOT_CALL_CAPABLE if not model.call_capable else MODEL_NOT_ON_PLAN
    raise _refusal(
        code,
        title="This language model cannot be used",
        detail=reason,
        remediation="Choose another model, or clear the choice to use the default.",
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

    `for_publish` adds what only a publish needs (D-681): on an engine whose bands are sold
    selectively, an agent must name a voice on a sold band — the platform default speaks a
    band nobody can see, and the workspace-keys mode has no band at all. A draft save may
    leave the voice empty.
    """
    caps = engine.capabilities
    refuse_choice_under_byok(engine, voice_id=voice_id, model_id=model_id)
    sold = sold_rate_keys(engine.name)
    # Only where a voice CAN be chosen: an adapter with no catalogue offers none, and
    # requiring one there would make the engine unpublishable rather than priced.
    choosable = isinstance(engine, HoldsCatalogue) and not caps.is_ours("tts")
    if for_publish and sold is not None and choosable:
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
    if not isinstance(engine, HoldsCatalogue):
        raise _not_offered(
            VOICE_CHOICE_NOT_OFFERED if voice_id is not None else MODEL_CHOICE_NOT_OFFERED,
            "voice" if voice_id is not None else "language model",
        )
    catalogue = await engine.read_catalogue()
    attested = await attested_rate_keys(session, engine=engine.name, at=datetime.now(UTC))
    platform = engine_platform_label(engine)
    if model_id is not None:
        _check_model(catalogue, model_id, attested=attested, platform=platform)
    if voice_id is None:
        return BASE_RATE_KEY
    return _check_voice(catalogue, voice_id, attested=attested, platform=platform, sold=sold)


async def engine_rate_key_for(
    session: AsyncSession, engine: VoiceEngine, cfg: AgentConfig
) -> EngineRateKey:
    """`require_engine_choice` for the config a publish is about to send. On ThinnestAI it
    refuses an agent with no voice, and refuses outright under BYOK (D-681)."""
    return await require_engine_choice(
        session,
        engine,
        voice_id=cfg.engine_voice_id,
        model_id=cfg.engine_model_id,
        for_publish=True,
    )


__all__ = [
    "BYOK_CHOICE_NOTE",
    "CATALOGUE_INCOMPLETE",
    "CHOICE_UNDER_BYOK",
    "KEYS_MODE_MISMATCH",
    "KEYS_NOT_ON_SALE",
    "MODEL_CHOICE_NOT_OFFERED",
    "MODEL_NOT_CALL_CAPABLE",
    "MODEL_NOT_IN_CATALOGUE",
    "MODEL_NOT_ON_PLAN",
    "VOICE_CHOICE_NOT_OFFERED",
    "VOICE_NOT_IN_CATALOGUE",
    "VOICE_NOT_ON_OFFER",
    "VOICE_REQUIRED",
    "VOICE_TIER_UNKNOWN",
    "VOICE_TIER_UNPRICED",
    "byok_in_force",
    "engine_rate_key_for",
    "refuse_choice_under_byok",
    "require_engine_choice",
]
