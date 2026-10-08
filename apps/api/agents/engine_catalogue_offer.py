"""May a model from the ENGINE'S OWN catalogue be offered here, right now?

The twin of `agents/voice_offer.py` for an engine that runs its own models (ThinnestAI,
`apps.api.engine.catalogue.HoldsCatalogue`). Same shape: a pure predicate per entry,
grounds ordered by whose problem they are, `None` meaning offerable, and the sentence
forked by audience — an operator reads the ground they can fix, a client reads the one
thing they can act on. The engine's VOICES are offered from the operator's curated list
instead (`agents/hosted_voices.py`, D-687).

THE PRICE GROUND IS HARD RULE 7. A call on such an engine is metered at an
operator-attested rupee rate per minute (`billing/engine_minutes.py`); the engine returns no
per-call cost. With no attested base rate (`BASE_RATE_KEY`) no minute on the engine can be
priced, so every model is unavailable for that one reason.

THE OTHER GROUNDS ARE THE ENGINE'S OWN STATEMENTS, read live from its catalogue
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
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue


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


#: The client's sentence for a voice that is not on offer. Plain, no vendor, no band jargon.
NOT_ON_OFFER_CLIENT: Final = "This voice is not on offer yet."


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


def offered_models(
    catalogue: EngineCatalogue,
    *,
    attested: Set[str],
    platform: str,
    audience: LlmReasonAudience,
) -> tuple[OfferedEngineModel, ...]:
    """Every catalogue model with its verdict, in the engine's own order."""
    return tuple(
        OfferedEngineModel(
            model=m,
            reason=model_unofferable_reason(
                m, attested=attested, platform=platform, audience=audience
            ),
        )
        for m in catalogue.models
    )


__all__ = [
    "NOT_ON_OFFER_CLIENT",
    "OfferedEngineModel",
    "model_unofferable_reason",
    "offered_models",
]
