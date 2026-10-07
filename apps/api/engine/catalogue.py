"""An engine's OWN voice and model catalogue, in our vocabulary (D-678).

`VoiceEngine.list_voices` answers a different question — which voices of OUR catalogue the
engine accepts — and refuses by name on an engine that dictates its own speech, which is
what the conformance suite requires. An engine that dictates its speech can still offer a
choice from its own catalogue, and the offer seam needs to read it to say which entries are
unavailable and why. This module is that read, kept off the Protocol so the BYOK contract
of `list_voices` is unchanged for every other adapter.

Nothing vendor-shaped crosses: ids and labels are opaque data, and `price_band` is the
engine's own tier name, kept verbatim because it is the key an operator attests a rate
against (hard rule 7) and inventing a second name for it would be a mapping nobody can
check.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from calevate_shared.engine import LlmTier
from pydantic import BaseModel, ConfigDict, Field


class CatalogueVoice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    voice_id: str
    label: str
    #: The engine's price band for a minute spoken in this voice.
    price_band: str
    #: Cloned by this account rather than taken from the shared catalogue.
    is_custom: bool = False


class CatalogueModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str
    label: str
    #: The engine says the model is fast enough to answer a phone call.
    call_capable: bool
    #: The engine account's plan may select it today.
    plan_allows: bool
    #: OUR tier for this model (D-680), set by the adapter that knows the engine's ids; `None`
    #: for a model it has not classified. A client is shown the tier, never `label`, because
    #: an engine's model names are the names of the companies that make them (D-679).
    tier: LlmTier | None = None


class EngineCatalogue(BaseModel):
    """Both lists, and whether they are all of them — `EngineVoiceListing`'s argument: a
    short page reads as a shorter catalogue, so a caller may not prune on `complete=False`."""

    voices: list[CatalogueVoice] = Field(default_factory=list)
    models: list[CatalogueModel] = Field(default_factory=list)
    complete: bool


@runtime_checkable
class HoldsCatalogue(Protocol):
    """An adapter whose engine publishes a catalogue of its own."""

    async def read_catalogue(self) -> EngineCatalogue: ...


@runtime_checkable
class ReportsOwnKeys(Protocol):
    """An adapter whose engine can say whether its account runs on the account's own keys
    (BYOK), so a publish can check the operator's setting against the vendor's state."""

    async def own_keys_in_use(self) -> bool: ...


__all__ = [
    "CatalogueModel",
    "CatalogueVoice",
    "EngineCatalogue",
    "HoldsCatalogue",
    "ReportsOwnKeys",
]
