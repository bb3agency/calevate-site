"""May a voice or model from the ENGINE'S OWN catalogue be offered here, right now?

The twin of `agents/voice_offer.py` for an engine that speaks its own voices and runs its
own models (ThinnestAI, `apps.api.engine.catalogue.HoldsCatalogue`). Same shape: a pure
predicate per entry, grounds ordered by whose problem they are, `None` meaning offerable,
and the sentence forked by audience — an operator reads the ground they can fix, a client
reads the one thing they can act on.

THE PRICE GROUNDS ARE HARD RULE 7. A call on such an engine is metered at an
operator-attested rupee rate per minute (`billing/engine_minutes.py`); the engine returns
no per-call cost. So:

1. **No attested base rate** (`BASE_RATE_KEY`) — no minute on the engine can be priced,
   so every voice and model is unavailable for this one reason.
2. **A band we do not sell** (D-681) — on ThinnestAI only Premium voices are sold, as the
   Clear rung (`billing/engine_minutes.CLIENT_RUNG_OF_RATE_KEY`). A Standard or Studio voice
   is refused with "This voice is not on offer yet", whatever is attested.
3. **No attested rate for the voice's price band** — the engine bills a call at the band
   of the voice it speaks (`thinnest-findings/mirror/pages/api-reference/
   voices-and-models.md:30-31`), so a voice in a band nobody has priced would meter at the
   wrong rate. That band's voices are unavailable until an operator attests it.

THE MODEL GROUNDS ARE THE ENGINE'S OWN STATEMENTS, read live from its catalogue
(`voices-and-models.md:63-65`): a model it says is too slow to answer a call, or one the
account's plan does not include, is shown and refused by name rather than hidden.

The attested rate keys are an ARGUMENT (the route reads them in one query through
`billing/engine_minutes.attested_minute_prices`), so every predicate here is pure.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass
from typing import Final

from apps.api.agents.llm_models import LlmReasonAudience
from apps.api.billing.engine_minutes import BASE_RATE_KEY
from apps.api.engine.catalogue import CatalogueModel, CatalogueVoice, EngineCatalogue


@dataclass(frozen=True, slots=True)
class OfferedEngineVoice:
    voice: CatalogueVoice
    reason: str | None

    @property
    def offerable(self) -> bool:
        return self.reason is None


@dataclass(frozen=True, slots=True)
class OfferedEngineModel:
    model: CatalogueModel
    reason: str | None

    @property
    def offerable(self) -> bool:
        return self.reason is None


def _no_base_rate_reason(platform: str, audience: LlmReasonAudience) -> str:
    if audience == "client":
        return "Not available yet: calls on this voice platform have not been priced."
    return (
        f"No rupee-per-minute rate is attested for {platform}, so no call on it can be "
        "metered. Attest the platform rate in the ops console before offering anything on it."
    )


def _no_band_rate_reason(platform: str, band: str, audience: LlmReasonAudience) -> str:
    if audience == "client":
        return f"Not available yet: {band} voices have not been priced."
    return (
        f"No rupee-per-minute rate is attested for {platform}'s {band!r} voice band, and "
        f"{platform} bills a call at the band of the voice it speaks. Attest that band's "
        "rate in the ops console to offer these voices."
    )


#: The client's sentence for a band we do not sell. Plain, no vendor, no band jargon.
NOT_ON_OFFER_CLIENT: Final = "This voice is not on offer yet."


def _not_on_offer_reason(platform: str, band: str, audience: LlmReasonAudience) -> str:
    if audience == "client":
        return NOT_ON_OFFER_CLIENT
    return (
        f"Only {platform}'s Premium voices are sold, as the Clear rung. The "
        f"{band!r} band is not offered: Standard is not sold, and Studio waits on "
        f"{platform}'s answer on per-workspace keys."
    )


def voice_unofferable_reason(
    voice: CatalogueVoice,
    *,
    attested: Set[str],
    platform: str,
    audience: LlmReasonAudience,
    sold: Set[str] | None = None,
) -> str | None:
    """`sold` is the bands a client may be sold on this engine
    (`billing.engine_minutes.sold_rate_keys`); `None` is no such rule. A band we do not
    sell is refused before an unattested one, because attesting it would not offer it."""
    if BASE_RATE_KEY not in attested:
        return _no_base_rate_reason(platform, audience)
    if sold is not None and voice.price_band not in sold:
        return _not_on_offer_reason(platform, voice.price_band, audience)
    if voice.price_band not in attested:
        return _no_band_rate_reason(platform, voice.price_band, audience)
    return None


def model_unofferable_reason(
    model: CatalogueModel,
    *,
    attested: Set[str],
    platform: str,
    audience: LlmReasonAudience,
) -> str | None:
    if BASE_RATE_KEY not in attested:
        return _no_base_rate_reason(platform, audience)
    if not model.call_capable:
        if audience == "client":
            return "Not available: this model is too slow to answer a phone call."
        return f"{platform} lists this model as too slow to answer a phone call."
    if not model.plan_allows:
        if audience == "client":
            return "Not available on this account's plan."
        return (
            f"The {platform} account's plan does not include this model. Upgrading the "
            f"plan in the {platform} console makes it available."
        )
    return None


def offered_catalogue(
    catalogue: EngineCatalogue,
    *,
    attested: Set[str],
    platform: str,
    audience: LlmReasonAudience,
    sold: Set[str] | None = None,
) -> tuple[tuple[OfferedEngineVoice, ...], tuple[OfferedEngineModel, ...]]:
    """Every catalogue entry with its verdict, in the engine's own order."""
    voices = tuple(
        OfferedEngineVoice(
            voice=v,
            reason=voice_unofferable_reason(
                v, attested=attested, platform=platform, audience=audience, sold=sold
            ),
        )
        for v in catalogue.voices
    )
    models = tuple(
        OfferedEngineModel(
            model=m,
            reason=model_unofferable_reason(
                m, attested=attested, platform=platform, audience=audience
            ),
        )
        for m in catalogue.models
    )
    return voices, models


__all__ = [
    "NOT_ON_OFFER_CLIENT",
    "OfferedEngineModel",
    "OfferedEngineVoice",
    "model_unofferable_reason",
    "offered_catalogue",
    "voice_unofferable_reason",
]
