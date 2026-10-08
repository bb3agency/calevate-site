"""Shared test doubles for engine-hosted voices (D-687): an engine that hosts voices, and
catalogue rows written and removed around a test.

`platform_voice_catalog` is a platform table every test shares, so each row written here
carries a unique id and is deleted when the test ends.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from apps.api.agents.hosted_voices import hosted_voice_id
from apps.api.core.errors import ProblemError
from apps.api.db.session import admin_session
from apps.api.engine.catalogue import (
    CatalogueModel,
    EngineCatalogue,
    HostedVoice,
    HostedVoiceListing,
    HostedVoiceSource,
    OwnVoiceKeyState,
    PreviewAudio,
    VoiceClone,
    VoiceCloneSample,
)
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest import THINNEST_CAPABILITIES
from calevate_shared.engine import AgentConfig, AgentSnapshot, EngineAgentRef
from sqlalchemy import text

PRANA = CatalogueModel(
    model_id="prana-voice",
    label="Prana",
    call_capable=True,
    plan_allows=True,
    voice_only_byok=True,
)
GPT41 = CatalogueModel(model_id="gpt-4.1", label="GPT-4.1", call_capable=True, plan_allows=True)
SLOW = CatalogueModel(model_id="gpt-slow", label="Slow", call_capable=False, plan_allows=True)
LOCKED = CatalogueModel(model_id="gpt-x", label="X", call_capable=True, plan_allows=False)
MODELS = (PRANA, GPT41, SLOW, LOCKED)

READY_KEY = OwnVoiceKeyState(
    enabled=True, scope="voice", complete=True, using="own", voice_provider="cartesia"
)
OFF_KEY = OwnVoiceKeyState(enabled=False, scope=None, complete=False, using="none")


class HostingEngine(FakeEngine):
    """A `HostsVoices` + `HoldsCatalogue` engine named `thinnest`, recording what it was sent,
    with each agent's own-voice-key switch held as the vendor would hold it."""

    def __init__(
        self,
        *,
        hosted: list[HostedVoice] | None = None,
        own_key: list[HostedVoice] | None = None,
        own_key_provider: str | None = "cartesia",
        key_state: OwnVoiceKeyState = READY_KEY,
        models: tuple[CatalogueModel, ...] = MODELS,
        complete: bool = True,
        **kw: Any,
    ) -> None:
        super().__init__(name="thinnest", capabilities=THINNEST_CAPABILITIES, **kw)
        self.hosted = hosted or []
        self.own_key = own_key or []
        self.own_key_provider = own_key_provider
        self.key_state = key_state
        self.models = models
        self.complete = complete
        self.reads = 0
        self.sent: list[AgentConfig] = []
        self.deleted: list[str] = []
        self.clones: dict[str, VoiceClone] = {}
        self.moved = 0
        self.installed: list[tuple[str, str | None]] = []
        self.enabled = 0
        self.disabled = 0
        self.previews: list[str] = []
        self.own_keys_listed = 0
        #: Each agent's `byok`, as ours: True on our voice key. Unset agents read as None.
        self.own_voice_key: dict[str, bool] = {}
        #: Refs whose switch the vendor refuses to change (a failed PATCH).
        self.refuse_switch: set[str] = set()
        #: Refs whose switch reads back unchanged however it is set.
        self.stuck_switch: set[str] = set()

    async def read_catalogue(self) -> EngineCatalogue:
        self.reads += 1
        return EngineCatalogue(models=list(self.models), complete=self.complete)

    async def own_keys_in_use(self) -> bool:
        return False

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        self.sent.append(cfg)
        ref = await super().create_agent(cfg)
        if cfg.engine_own_voice_key is not None:
            self.own_voice_key[ref] = cfg.engine_own_voice_key
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        self.sent.append(cfg)
        await super().update_agent(ref, cfg)
        if cfg.engine_own_voice_key is not None:
            self.own_voice_key[ref] = cfg.engine_own_voice_key

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        return snapshot.model_copy(update={"engine_own_voice_key": self.own_voice_key.get(ref)})

    async def agent_own_voice_key(self, ref: str) -> bool | None:
        return self.own_voice_key.get(ref)

    async def set_agent_own_voice_key(self, ref: str, *, on: bool) -> None:
        if ref in self.refuse_switch:
            raise ProblemError(
                kind="dependency", code="engine_rejected", title="refused", detail="refused"
            )
        if ref not in self.stuck_switch:
            self.own_voice_key[ref] = on

    async def delete_agent(self, ref: EngineAgentRef) -> None:
        self.deleted.append(ref)

    async def list_hosted_voices(self) -> HostedVoiceListing:
        return HostedVoiceListing(voices=self.hosted)

    async def list_own_key_voices(self) -> HostedVoiceListing:
        self.own_keys_listed += 1
        return HostedVoiceListing(voices=self.own_key, provider=self.own_key_provider)

    async def preview_own_key_voice(
        self, *, voice_id: str, text: str | None, language: str | None
    ) -> PreviewAudio:
        self.previews.append(voice_id)
        return PreviewAudio(data=MP3, content_type="audio/mpeg")

    async def create_voice_clone(self, sample: VoiceCloneSample) -> VoiceClone:
        voice_id = f"v-{uuid.uuid4().hex[:10]}"
        clone = VoiceClone(
            clone_id=f"vc_{voice_id}",
            voice_id=voice_id,
            label=sample.name,
            language=sample.language,
            preview_url="https://files.example.com/p.mp3",
            usable_on_agents=True,
        )
        self.clones[voice_id] = clone
        return clone

    async def find_voice_clone(self, voice_id: str) -> VoiceClone | None:
        return self.clones.get(voice_id)

    async def delete_voice_clone(self, clone_id: str) -> int:
        self.clones = {k: v for k, v in self.clones.items() if v.clone_id != clone_id}
        return self.moved

    async def own_key_state(self) -> OwnVoiceKeyState:
        return self.key_state

    async def install_own_voice_key(
        self, *, provider: str, api_key: str, model: str | None
    ) -> None:
        self.installed.append((provider, model))
        self.key_state = self.key_state.model_copy(update={"voice_provider": provider})

    async def enable_own_voice_key(self) -> OwnVoiceKeyState:
        self.enabled += 1
        self.key_state = READY_KEY.model_copy(
            update={"voice_provider": self.key_state.voice_provider}
        )
        return self.key_state

    async def disable_own_voice_key(self) -> OwnVoiceKeyState:
        self.disabled += 1
        self.key_state = self.key_state.model_copy(update={"enabled": False, "using": "none"})
        return self.key_state


#: The smallest bytes our sniff reads as MP3 (an ID3 header).
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
#: A RIFF/WAVE header.
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32


@contextmanager
def selected(instance: FakeEngine) -> Iterator[FakeEngine]:
    """Make `get_engine()` answer `instance` (the settings name the fake engine)."""
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


class CatalogueRows:
    """Writes hosted catalogue rows for one test and removes them afterwards."""

    def __init__(self) -> None:
        self.ids: list[str] = []

    async def add(
        self,
        source: HostedVoiceSource,
        *,
        label: str = "Voice",
        origin: str = "operator",
        state: str = "enabled",
        withdrawn: bool = False,
        clone_id: str | None = None,
        preview: bool = False,
        accent: str | None = "hi",
        vendor_id: str | None = None,
        band: str | None = "premium",
    ) -> str:
        vendor = vendor_id or f"t{uuid.uuid4().hex[:12]}"
        voice_id = hosted_voice_id(source, vendor)
        self.ids.append(voice_id)
        async with admin_session() as session:
            await session.execute(
                text(
                    "INSERT INTO platform_voice_catalog (voice_id, engine_voice_id, label, "
                    "tts_model, provider, languages, is_custom, synced_at, curation_state, "
                    "origin, withdrawn_at, engine_clone_id, accent, preview_object_key, "
                    "preview_content_type, preview_source, vendor_band) "
                    "VALUES (:id, :vendor, :label, "
                    ":source, :provider, ARRAY['te-IN','hi-IN','en-IN'], :custom, now(), "
                    ":state, :origin, :withdrawn, :clone, :accent, :key, :ctype, :psource, :band)"
                ),
                {
                    "id": voice_id,
                    "vendor": vendor,
                    "label": label,
                    "source": source,
                    "provider": "thinnest" if source == "engine" else "cartesia",
                    "custom": clone_id is not None,
                    "state": state,
                    "origin": origin,
                    "withdrawn": datetime.now(UTC) if withdrawn else None,
                    "clone": clone_id,
                    "accent": accent,
                    "key": f"voice-previews/{voice_id}" if preview else None,
                    "ctype": "audio/mpeg" if preview else None,
                    "psource": "upload" if preview else None,
                    # An own-key voice has no engine band.
                    "band": band if source == "engine" else None,
                },
            )
        return voice_id

    def track(self, voice_id: str) -> None:
        self.ids.append(voice_id)

    async def cleanup(self) -> None:
        async with admin_session() as session:
            await session.execute(
                text("DELETE FROM platform_voice_catalog WHERE voice_id = ANY(:ids)"),
                {"ids": self.ids},
            )


__all__ = [
    "GPT41",
    "LOCKED",
    "MODELS",
    "MP3",
    "OFF_KEY",
    "PRANA",
    "READY_KEY",
    "SLOW",
    "WAV",
    "CatalogueRows",
    "HostingEngine",
    "selected",
]
