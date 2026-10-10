"""An engine's OWN models and voices, in our vocabulary (D-678, D-687).

`VoiceEngine.list_voices` answers a different question — which voices of OUR catalogue the
engine accepts — and refuses by name on an engine that dictates its own speech, which is
what the conformance suite requires. An engine that dictates its speech still offers a
choice from its own catalogue; the reads and writes for that choice are kept off the
Protocol here, so the BYOK contract of `list_voices` is unchanged for every other adapter.

Nothing vendor-shaped crosses: ids and labels are opaque data.

Two kinds of voice an engine may host (D-687):

* `engine` — the engine's own voices, including the ones our account cloned on it;
* `byok` — the voices of the voice provider whose key we installed on the engine
  (bring-your-own-key, voice only). Each agent says whether it speaks on that key (D-688).
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from calevate_shared.engine import LlmTier
from pydantic import BaseModel, ConfigDict, Field

HostedVoiceSource = Literal["engine", "byok"]

#: The price band an engine files each of its own voices under, cheapest first. On
#: ThinnestAI it is `GET /voices` `tier` (snapshots/2026-10-07b/pages/api-reference/voices/
#: list-voices.md:436-442). Every band is stored so an operator sees the whole platform; only
#: the band sold as Clear can be added and offered (`agents/hosted_voices.sold_hosted_band`).
HostedVoiceBand = Literal["standard", "premium", "studio"]


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
    #: The engine lets a call run on this model while only the VOICE is our own key. An
    #: agent speaking a `byok` voice may be set to no other (D-687).
    voice_only_byok: bool = False
    #: The per-minute price band the model lifts a call to, when we have it on record: `none`
    #: (the call bills at its voice's band) or `premium`. `None` is UNKNOWN, and a model with
    #: an unknown band is never offered for calls (hard rule 7): a call on it could bill at
    #: a band nobody priced.
    surcharge: Literal["none", "premium"] | None = None
    #: The reply latency the engine's own console shows for the model, in milliseconds, when
    #: on record. Shown to operators choosing a model; the engine's API returns none.
    console_latency_ms: int | None = None


class EngineCatalogue(BaseModel):
    """The models, and whether the list is all of them — `EngineVoiceListing`'s argument: a
    short page reads as a shorter catalogue, so a caller may not prune on `complete=False`."""

    models: list[CatalogueModel] = Field(default_factory=list)
    complete: bool


class HostedVoice(BaseModel):
    """One voice an engine hosts, as its listing describes it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The engine's own id for the voice: what an agent is set to.
    voice_id: str
    label: str
    source: HostedVoiceSource
    #: Cloned by our account rather than taken from a shared catalogue.
    is_custom: bool = False
    #: The language or accent the listing names, as a tag (`hi`, `en-IN`), when it names one.
    language: str | None = None
    description: str | None = None
    #: A sample clip the listing links to, when it has one. Fetched server-side only.
    sample_url: str | None = None
    #: The engine's price band for one of its own voices; None for a `byok` voice, which is
    #: priced by its own source.
    band: HostedVoiceBand | None = None


class HostedVoiceListing(BaseModel):
    voices: list[HostedVoice] = Field(default_factory=list)
    #: The voice provider behind a `byok` listing (`cartesia`), None for `engine` voices.
    provider: str | None = None
    #: Voices the engine listed in a band we do not read, counted by the engine's own word.
    #: They cannot be priced, so they are not in `voices`, but the operator is told they
    #: exist rather than having them vanish (a renamed or newly added band would otherwise
    #: read as the engine listing nothing in it).
    unread_bands: dict[str, int] = Field(default_factory=dict)


class VoiceCloneSample(BaseModel):
    """What a clone is made from. `consent_*` are the operator's attestations, sent as the
    engine's two required promises."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    content_type: str
    data: bytes
    name: str
    description: str | None = None
    language: str | None = None
    remove_noise: bool = True
    consent_own_voice: bool
    consent_no_impersonation: bool


class VoiceClone(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clone_id: str
    voice_id: str
    label: str
    language: str | None = None
    #: A short-lived link to the clone's preview, or None.
    preview_url: str | None = None
    usable_on_agents: bool


class PreviewAudio(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: bytes
    content_type: str


class OwnVoiceKeyState(BaseModel):
    """A sub-account's own-keys (BYOK) state, as the engine reports it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool
    #: What the sub-account brings: `all`, `voice`, or None.
    scope: str | None
    #: The keys for `scope` are added and checked.
    complete: bool
    #: Whose keys calls run on: `own`, `developer` or `none`.
    using: str
    #: The voice provider installed, when there is one.
    voice_provider: str | None = None

    @property
    def speaks_on_own_voice(self) -> bool:
        """Calls in this sub-account speak on its own voice key, and only the voice is ours."""
        return self.enabled and self.scope == "voice" and self.complete and self.using == "own"


@runtime_checkable
class HoldsCatalogue(Protocol):
    """An adapter whose engine publishes a model catalogue of its own."""

    async def read_catalogue(self) -> EngineCatalogue: ...


@runtime_checkable
class ReportsOwnKeys(Protocol):
    """An adapter whose engine can say whether its account runs on the account's own keys
    (BYOK), so a publish can check the operator's setting against the vendor's state."""

    async def own_keys_in_use(self) -> bool: ...


@runtime_checkable
class HostsVoices(Protocol):
    """An adapter whose engine speaks voices it hosts, which an operator curates (D-687), and
    whose agents each say whether they speak on the account's own voice key (D-688)."""

    name: str

    async def list_hosted_voices(self) -> HostedVoiceListing: ...

    async def list_own_key_voices(self) -> HostedVoiceListing: ...

    async def preview_own_key_voice(
        self, *, voice_id: str, text: str | None, language: str | None
    ) -> PreviewAudio: ...

    async def create_voice_clone(self, sample: VoiceCloneSample) -> VoiceClone: ...

    async def find_voice_clone(self, voice_id: str) -> VoiceClone | None: ...

    async def delete_voice_clone(self, clone_id: str) -> int: ...

    async def own_key_state(self) -> OwnVoiceKeyState: ...

    async def install_own_voice_key(
        self, *, provider: str, api_key: str, model: str | None
    ) -> None: ...

    async def enable_own_voice_key(self) -> OwnVoiceKeyState: ...

    async def disable_own_voice_key(self) -> OwnVoiceKeyState: ...

    async def agent_own_voice_key(self, ref: str) -> bool | None: ...

    async def set_agent_own_voice_key(self, ref: str, *, on: bool) -> None: ...


@runtime_checkable
class ListsVoiceClones(Protocol):
    """An adapter that can list the clones of the workspace it is acting in (D-693), so a
    clone made again in a client's workspace is found by its name rather than made twice."""

    async def list_voice_clones(self) -> list[VoiceClone]: ...


__all__ = [
    "CatalogueModel",
    "EngineCatalogue",
    "HoldsCatalogue",
    "HostedVoice",
    "HostedVoiceBand",
    "HostedVoiceListing",
    "HostedVoiceSource",
    "HostsVoices",
    "ListsVoiceClones",
    "OwnVoiceKeyState",
    "PreviewAudio",
    "ReportsOwnKeys",
    "VoiceClone",
    "VoiceCloneSample",
]
