"""The two speech legs actually reach the wire, in the slots the vendor reads them from.

TWO DEFECTS, ONE FILE, because they are the same defect at two ends of one block and a
reviewer who fixes one will be looking at the other.

**DEFECT 2 — THE STT LEG WAS NEVER WRITTEN.** `agents.stt_provider` and `agents.stt_model`
are nullable Text columns with no writer anywhere in the tree: no route, no service, no
seed, no migration default. `_to_config` read them faithfully, the rented engine's adapter
forwarded them faithfully, and every published agent sent `"transcriber": {"provider": null,
"model": null}` — so the engine picked its own default transcriber on a Telugu-first
product. Nothing caught it: `require_speech_leg` returns early on `None`, and a
wrong-language transcript has no vendor-side symptom at all. The downstream cost is
compliance-shaped rather than cosmetic (`compliance/optout.py` hunts romanised Telugu
opt-out phrases, which an English transcript does not contain).

**DEFECT 3 — THE MODEL WAS SENT IN THE SPEAKER SLOT.** `cfg.models.tts_voice` held
`bulbul:v3`, a MODEL, and the adapter pasted it into `synthesizer.provider_config.voice`,
which is where the vendor reads a SPEAKER. Their own worked example separates them:
`{"model": "bulbul:v3", "voice": "Ashutosh", "voice_id": "ashutosh"}`
(VERIFIED-VENDOR-REPO, `bolna-ai/skills@28b24aa`, `create-agent/SKILL.md`). It was not
fixed earlier because no speaker list was known; Sarvam's own SDK enumerates all 44
(VERIFIED-VENDOR-SDK: sarvamai==0.1.31 (PyPI wheel), `types/text_to_speech_speaker.py`,
read 27 Aug 2026), so that premise is dead.

How an adapter renders these facts onto its own wire is that adapter's test; this file
pins the resolver (`in_call_speech`) that decides them.
"""

from __future__ import annotations

import os
from typing import Any
from unittest import mock

from apps.api.agents.service import in_call_speech
from apps.api.agents.voices import CARTESIA_TTS_MODEL
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import require_speech_leg
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from calevate_shared.engine import (
    SARVAM_DEFAULT_STT,
    SARVAM_STT_PROVIDER,
    SARVAM_TRANSLATING_STT,
)
from tests.voice_fixture import TEST_SPEAKER, TEST_VOICE_ID

# The row shape `in_call_speech` reads, as the three keys it touches. A dict rather than a
# database row: this resolver's whole job is a pure decision over four column values and an
# engine descriptor, and giving it a session would hide that.
_UNCONFIGURED: dict[str, Any] = {
    "stt_provider": None,
    "stt_model": None,
    "tts_voice": TEST_VOICE_ID,
}


def _row(**overrides: Any) -> Any:
    return {**_UNCONFIGURED, **overrides}


# --- the STT leg (defect 2) ---------------------------------------------------


def test_an_agent_that_configured_no_transcriber_still_publishes_one() -> None:
    """THE DEFECT, stated as the property that was false. Every agent row in this
    repository has NULL in both STT columns, so before this resolver every published agent
    named no transcriber and the engine chose."""
    speech = in_call_speech(_row(), engine=FakeEngine())

    assert speech["stt_provider"] == SARVAM_STT_PROVIDER
    assert speech["stt_model"] == SARVAM_DEFAULT_STT
    assert speech["stt_model"] not in SARVAM_TRANSLATING_STT, (
        "the default must return the caller's own words, not an English translation"
    )


def test_a_row_that_names_a_transcriber_keeps_it() -> None:
    """The default is a FALLBACK, not an override. A row value wins, which is what makes
    this a platform default rather than a hard-coded leg — the same precedence
    `resolved_llm_model` applies one field over."""
    speech = in_call_speech(_row(stt_provider="deepgram", stt_model="nova-2"), engine=FakeEngine())

    assert (speech["stt_provider"], speech["stt_model"]) == ("deepgram", "nova-2")


def test_no_default_is_filled_on_an_engine_that_supplies_its_own_transcriber() -> None:
    """THE TRAP, and it is the reason this resolver asks the engine at all.

    `require_speech_leg("stt", ...)` REFUSES a non-None STT selection on an engine whose
    transcriber is its own product. Filling the platform default unconditionally would
    therefore take every agent on such an engine from publishable to unpublishable — a fix
    for a silent defect that causes a loud one. The assertion pairs the resolver's answer
    with the guard that would have refused it, because either one alone would pass while
    the product was broken.
    """
    engine = FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)

    speech = in_call_speech(_row(), engine=engine)

    assert speech["stt_model"] is None
    assert speech["stt_provider"] is None
    # The guard the publish path runs, on the value the resolver just produced. No raise.
    require_speech_leg("stt", engine=engine, value=speech["stt_model"])


def test_the_platform_transcriber_is_a_console_setting_not_a_constant() -> None:
    """D-583: the operator can change which Sarvam model agents publish with, WITHOUT a
    deploy, because the engine's validator enforces a per-model language matrix that no
    published page states:

        400 POST /v2/agent — "Provided language: te-IN is not available for the
        model: saaras:v3"

    Their OpenAPI declares `model` and `language` as independent enums with both values
    present (`api-reference/agent/v2/create.md:1071-1091`) and their transcriber page says
    all four models cover all eleven languages (`providers/transcriber/sarvam.md` §5) — so
    both documents say this publish should work and the validator says otherwise. There is
    no STT discovery endpoint to ask (`voice-config` is TTS-only), which leaves the
    validator as the only instrument and the number of DEPLOYS as the only variable.

    Read at the POINT OF USE, so a console edit reaches the next publish without a restart.
    The setting is `needs_republish` rather than `live` because this resolves at publish
    time into the agent object the engine stores.
    """
    settings = get_settings()
    assert settings.sarvam_stt_model == SARVAM_DEFAULT_STT, (
        "the default moved; it may only move WITH evidence from the validator, never on a "
        "guess about which model serves Telugu (hard rule 11)"
    )

    get_settings.cache_clear()
    try:
        with mock.patch.dict(os.environ, {"SARVAM_STT_MODEL": "saarika:v2.5"}):
            speech = in_call_speech(_row(), engine=FakeEngine())
            assert speech["stt_model"] == "saarika:v2.5", (
                "the resolver captured the constant at import; an operator changing this "
                "on a console would see no effect and reach for a deploy"
            )
    finally:
        get_settings.cache_clear()


def test_language_detection_is_off_unless_an_operator_turns_it_on() -> None:
    """D-584. Detection (`ModelConfig.stt_autodetect`) is strictly weaker than pinning and
    unverified for Telugu, so it may only be turned on deliberately (hard rule 11)."""
    assert get_settings().stt_autodetect_language is False, (
        "detection became the default; it is strictly weaker than pinning and unverified "
        "for Telugu, so it may only be turned on deliberately (hard rule 11)"
    )


# --- the TTS leg (defect 3) ---------------------------------------------------


def test_the_catalogue_id_is_split_into_the_model_and_the_speaker() -> None:
    """`agents.tts_voice` holds OUR id; `ModelConfig` holds the vendor's two facts."""
    speech = in_call_speech(_row(), engine=FakeEngine())

    assert speech["tts_model"] == CARTESIA_TTS_MODEL
    assert speech["tts_voice"] == TEST_SPEAKER
    assert speech["tts_voice"] != speech["tts_model"], "the whole of defect 3 in one line"


def test_a_voice_id_the_catalogue_does_not_offer_travels_as_it_always_did() -> None:
    """A CATALOGUE LOOKUP, NEVER STRING SURGERY. Splitting on the last colon would turn the
    legacy value `bulbul:v3` into model `bulbul` and speaker `v3` — two strings the vendor
    has never heard of, sent confidently. `agents.tts_voice` is free text by design, so an
    id we do not offer keeps the pre-split behaviour: the speaker slot, no model."""
    speech = in_call_speech(_row(tts_voice="bulbul:v3"), engine=FakeEngine())

    assert speech["tts_model"] is None
    assert speech["tts_voice"] == "bulbul:v3"
