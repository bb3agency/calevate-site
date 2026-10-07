"""WHAT A CLIENT CHOOSES IS A TIER, NEVER A MODEL (D-680, under D-679's white label).

A client reads "Standard", "Plus" or "Pro". Which company's model answers each tier is ours:
three live settings an operator sets in the ops console (`Settings.llm_tier_*_model`). The
client realm's wire carries the tier and never a model id or a provider; the admin realm
keeps the real models (`llm_routes.LlmDefaultsOut`).

THE TIER IS RESOLVED AT THE MOMENT OF CHOOSING AND THE MODEL IS WHAT IS STORED. The columns
(`agents.llm_model`, `organizations.default_llm_model`), the publish path, metering and the
surcharge rule (`billing/rates.is_surchargeable_llm_model`) all keep reading a model, so hard
rule 7 and D-455 apply to the resolved model exactly as they did before tiers. The rejected
alternative was storing the tier and resolving it at publish: re-pointing a tier would then
move every account on it — what they run and, through the surcharge rule, what they are
billed — without any of them choosing. Storing the model means a re-point moves the next
choice and nothing else.

DISPLAY RUNS THE OTHER WAY. A stored model is shown as the tier currently pointed at it, or —
for a model no tier points at (a choice made before tiers existed, or one an operator set in
the admin console) — as the tier its price falls in (`cost_tier`). Re-saving the tier an
account is already shown as keeps its stored model (`resolve_tier_choice`), so opening the
screen and pressing Save never changes what anybody runs or pays.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, get_args

from calevate_shared.engine import LLM_MODELS, LlmTier

from apps.api.agents.llm_models import (
    LlmReasonAudience,
    offerable_models,
    platform_default_model,
    unofferable_reason,
)
from apps.api.billing.rates import is_surchargeable_llm_model
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine import get_engine
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue, HoldsCatalogue

#: Cheapest first; the order every picker renders in.
LLM_TIERS: Final[tuple[LlmTier, ...]] = get_args(LlmTier)

LLM_TIER_LABELS: Final[Mapping[LlmTier, str]] = {
    "standard": "Standard",
    "plus": "Plus",
    "pro": "Pro",
}

#: Capability and cost, never a vendor: the sentence under each tier on the client picker.
LLM_TIER_DESCRIPTIONS: Final[Mapping[LlmTier, str]] = {
    "standard": "Quick, natural replies for everyday calls. Our lowest-cost option.",
    "plus": "Stronger reasoning for longer calls and detailed questions.",
    "pro": "Our most capable option, for the most involved conversations.",
}

#: What a client reads for a model no tier describes — an id outside the catalogue. Every
#: catalogue model has a tier through `cost_tier`, so this is reached only by a value an
#: operator wrote by hand.
UNTIERED_LABEL: Final = "Custom"

#: The input price at and above which a model is "pro". Input is the axis that decides the
#: in-call bill: the whole conversation is resent on every turn (TRD §6.1), so most of a
#: minute's language cost is input. `gpt-5.4-mini` lists at $0.75 (`LLM_MODELS`).
PRO_INPUT_USD_PER_MTOK: Final = Decimal("0.75")


def cost_tier(model: str) -> LlmTier | None:
    """The tier a catalogue model's PRICE puts it in, independent of what any tier points at.

    Standard is exactly the set the plan surcharge never applies to (`is_surchargeable_llm_
    model` is False: at or below the base rate on a leg), so a client shown "Standard" is never
    surprised by an upgrade line. Derived from the catalogue rather than listed, so a model
    added to `LLM_MODELS` is classified the day it lands.
    """
    spec = LLM_MODELS.get(model)
    if spec is None:
        return None
    if not is_surchargeable_llm_model(model):
        return "standard"
    if spec.price.input_usd_per_mtok >= PRO_INPUT_USD_PER_MTOK:
        return "pro"
    return "plus"


def tier_models() -> dict[LlmTier, str]:
    """Which model each tier resolves to right now — the live settings, read per call."""
    settings = get_settings()
    return {
        "standard": settings.llm_tier_standard_model,
        "plus": settings.llm_tier_plus_model,
        "pro": settings.llm_tier_pro_model,
    }


def tier_model(tier: LlmTier) -> str:
    return tier_models()[tier]


def tier_of_model(model: str | None) -> LlmTier | None:
    """The tier a stored model is SHOWN as: the first tier pointed at it, else its price class.

    The pointed-at tier wins so that a choice made through a tier reads back as that tier even
    when an operator has pointed a tier outside the model's price class. `None` only for an
    id outside the catalogue.
    """
    if model is None:
        return None
    for tier, mapped in tier_models().items():
        if mapped == model:
            return tier
    return cost_tier(model)


def tier_label(tier: LlmTier | None) -> str:
    return LLM_TIER_LABELS[tier] if tier is not None else UNTIERED_LABEL


def client_model_label(model: str | None, *, unclassified: str = UNTIERED_LABEL) -> str:
    """What a client reads in place of a model id anywhere it would otherwise appear — a
    statement line, a usage panel, a quality report. `unclassified` is the word for an id
    outside the catalogue, which a caller naming a non-conversation model can make fit."""
    tier = tier_of_model(model)
    return LLM_TIER_LABELS[tier] if tier is not None else unclassified


def client_model_labels(models: Sequence[str]) -> list[str]:
    """`client_model_label` over several models, de-duplicated in order — two models can
    share a tier, and a statement naming "Plus, Plus" says nothing twice."""
    labels: list[str] = []
    for model in models:
        label = client_model_label(model)
        if label not in labels:
            labels.append(label)
    return labels


@dataclass(frozen=True)
class TierOption:
    """One row of the client's picker. Carries the resolved model for the SERVER's use (the
    surcharge and the offer check); the route never puts it on the client's wire."""

    tier: LlmTier
    model: str
    is_surcharged: bool
    is_platform_default: bool
    unavailable_reason: str | None

    @property
    def is_available(self) -> bool:
        return self.unavailable_reason is None


def available_tiers(*, audience: LlmReasonAudience = "client") -> tuple[TierOption, ...]:
    """Every tier, each through the SAME offer predicate as a model (`unofferable_reason`):
    a tier is available exactly when the model it resolves to is offerable."""
    default_tier = tier_of_model(platform_default_model())
    mapping = tier_models()
    return tuple(
        TierOption(
            tier=tier,
            model=mapping[tier],
            is_surcharged=is_surchargeable_llm_model(mapping[tier]),
            is_platform_default=tier == default_tier,
            unavailable_reason=unofferable_reason(mapping[tier], audience=audience),
        )
        for tier in LLM_TIERS
    )


def resolve_tier_choice(
    tier: LlmTier | None, *, current_model: str | None, field: str
) -> str | None:
    """The model a client's tier choice stores, or a refusal in tier words.

    `None` is INHERIT and passes through, as `validate_llm_model`'s does. Choosing the tier the
    current model is already shown as keeps that model — it is the no-op it looks like on the
    screen, even when the tier now points somewhere else.
    """
    if tier is None:
        return None
    if current_model is not None and tier_of_model(current_model) == tier:
        return current_model
    model = tier_model(tier)
    offerable = offerable_models()
    if model in offerable:
        return model
    permitted = [LLM_TIER_LABELS[t] for t in LLM_TIERS if tier_model(t) in offerable]
    listed = ", ".join(permitted) or "none"
    label = LLM_TIER_LABELS[tier]
    raise ProblemError(
        kind="validation",
        code="llm_tier_not_available",
        title="That AI model tier is not switched on yet",
        detail=(
            f"{label} isn't switched on for your account yet. The tiers you can choose "
            f"are: {listed}."
        ),
        remediation=f"Choose one of {listed} for now, or ask your Calevate team to enable {label}.",
        fields=[{"name": field, "reason": "this tier is not switched on yet"}],
    )


# --- The engine's own catalogue (D-678) ---------------------------------------------------

#: Prefix of the opaque id a client is given for an engine catalogue model.
ENGINE_MODEL_TOKEN_PREFIX: Final = "m_"


def engine_model_token(model_id: str) -> str:
    """The id a client sees for one of the engine's own models. Deterministic, so the token in
    an agent's read-back matches the picker row; it names nothing a client could read."""
    digest = hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:16]
    return f"{ENGINE_MODEL_TOKEN_PREFIX}{digest}"


def engine_model_for_token(catalogue: EngineCatalogue, token: str) -> str | None:
    """The engine model id behind a client's token, or `None` when the catalogue holds none."""
    return next(
        (m.model_id for m in catalogue.models if engine_model_token(m.model_id) == token), None
    )


async def engine_model_from_client(value: str | None) -> str | None:
    """The engine model id a client's token names, read off the live catalogue.

    Anything that is not a token, or a token the catalogue no longer holds, passes through
    unchanged — `engine_choice.require_engine_choice` then refuses it with the same
    not-in-catalogue (or incomplete-catalogue) answer it gives any unknown id, so this adds
    no second refusal path.
    """
    if value is None or not value.startswith(ENGINE_MODEL_TOKEN_PREFIX):
        return value
    engine = get_engine()
    if not isinstance(engine, HoldsCatalogue):
        return value
    return engine_model_for_token(await engine.read_catalogue(), value) or value


def engine_model_labels(models: Sequence[CatalogueModel]) -> dict[str, str]:
    """What a client reads for each engine model, keyed by model id: the tier the adapter
    classified it as, else "Additional model N" in the engine's own order."""
    labels: dict[str, str] = {}
    unnamed = 0
    for model in models:
        if model.tier is not None:
            labels[model.model_id] = LLM_TIER_LABELS[model.tier]
        else:
            unnamed += 1
            labels[model.model_id] = f"Additional model {unnamed}"
    return labels


__all__ = [
    "ENGINE_MODEL_TOKEN_PREFIX",
    "LLM_TIERS",
    "LLM_TIER_DESCRIPTIONS",
    "LLM_TIER_LABELS",
    "PRO_INPUT_USD_PER_MTOK",
    "UNTIERED_LABEL",
    "TierOption",
    "available_tiers",
    "client_model_label",
    "client_model_labels",
    "cost_tier",
    "engine_model_for_token",
    "engine_model_from_client",
    "engine_model_labels",
    "engine_model_token",
    "resolve_tier_choice",
    "tier_label",
    "tier_model",
    "tier_models",
    "tier_of_model",
]
