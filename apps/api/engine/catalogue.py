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
  (bring-your-own-key, voice only), which speak inside a sub-account (`workspace`).
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from calevate_shared.engine import LlmTier
from pydantic import BaseModel, ConfigDict, Field

HostedVoiceSource = Literal["engine", "byok"]


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


class HostedVoiceListing(BaseModel):
    voices: list[HostedVoice] = Field(default_factory=list)
    #: The voice provider behind a `byok` listing (`cartesia`), None for `engine` voices.
    provider: str | None = None


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
    """An adapter whose engine speaks voices it hosts, which an operator curates (D-687).

    `workspace` is an engine sub-account (`calevate_shared.engine_scope`); None is the
    account itself.
    """

    name: str

    async def list_hosted_voices(self) -> HostedVoiceListing: ...

    async def list_own_key_voices(self, *, workspace: str) -> HostedVoiceListing: ...

    async def preview_own_key_voice(
        self, *, workspace: str, voice_id: str, text: str | None, language: str | None
    ) -> PreviewAudio: ...

    async def create_voice_clone(self, sample: VoiceCloneSample) -> VoiceClone: ...

    async def find_voice_clone(self, voice_id: str) -> VoiceClone | None: ...

    async def delete_voice_clone(self, clone_id: str) -> int: ...

    async def own_key_state(self, *, workspace: str) -> OwnVoiceKeyState: ...

    async def install_own_voice_key(
        self, *, workspace: str, provider: str, api_key: str, model: str | None
    ) -> None: ...

    async def enable_own_voice_key(self, *, workspace: str) -> OwnVoiceKeyState: ...

    async def create_workspace(self, *, name: str, external_id: str) -> str: ...


__all__ = [
    "CatalogueModel",
    "EngineCatalogue",
    "HoldsCatalogue",
    "HostedVoice",
    "HostedVoiceListing",
    "HostedVoiceSource",
    "HostsVoices",
    "OwnVoiceKeyState",
    "PreviewAudio",
    "ReportsOwnKeys",
    "VoiceClone",
    "VoiceCloneSample",
]
