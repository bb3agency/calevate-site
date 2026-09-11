"""The two speech legs actually reach the wire, in the slots the vendor reads them from.

TWO DEFECTS, ONE FILE, because they are the same defect at two ends of one block and a
reviewer who fixes one will be looking at the other.

**DEFECT 2 — THE STT LEG WAS NEVER WRITTEN.** `agents.stt_provider` and `agents.stt_model`
are nullable Text columns with no writer anywhere in the tree: no route, no service, no
seed, no migration default. `_to_config` read them faithfully, `engine/bolna.py` forwarded
them faithfully, and every published agent sent `"transcriber": {"provider": null, "model":
null}` — so the engine picked its own default transcriber on a Telugu-first product.
Nothing caught it: `require_speech_leg` returns early on `None`, and a wrong-language
transcript has no vendor-side symptom at all. The downstream cost is compliance-shaped
rather than cosmetic (`compliance/optout.py` hunts romanised Telugu opt-out phrases, which
an English transcript does not contain).

**DEFECT 3 — THE MODEL WAS SENT IN THE SPEAKER SLOT.** `cfg.models.tts_voice` held
`bulbul:v3`, a MODEL, and the adapter pasted it into `synthesizer.provider_config.voice`,
which is where the vendor reads a SPEAKER. Their own worked example separates them:
`{"model": "bulbul:v3", "voice": "Ashutosh", "voice_id": "ashutosh"}`
(VERIFIED-VENDOR-REPO, `bolna-ai/skills@28b24aa`, `create-agent/SKILL.md`). It was not
fixed earlier because no speaker list was known; Sarvam's own SDK enumerates all 44
(VERIFIED-VENDOR-SDK: sarvamai==0.1.31 (PyPI wheel), `types/text_to_speech_speaker.py`,
read 27 Aug 2026), so that premise is dead.

WHAT THIS FILE PINS THAT A UNIT TEST OF EITHER HALF WOULD NOT: the DRIFT PATH. Both fixes
change what goes on the wire, and the read-back (`_agent_models`) is compared against the
config a publish would send. A send/read pair that disagrees does not fail loudly — it
reports every agent in the product as drifted, forever, which teaches an operator to
ignore the one instrument that can see a vendor-side edit. So the round trip is asserted
here as one property, not as two.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any
from unittest import mock

import httpx
from apps.api.agents.service import in_call_speech
from apps.api.agents.voices import DEFAULT_TTS_MODEL
from apps.api.core.settings import get_settings
from apps.api.engine.bolna import (
    BASE_URL,
    BolnaEngine,
    _agent_models,
    _synthesizer_config,
    _transcriber_language,
)
from apps.api.engine.capabilities import require_speech_leg
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from calevate_shared.engine import (
    SARVAM_DEFAULT_STT,
    SARVAM_STT_PROVIDER,
    SARVAM_TRANSLATING_STT,
    AgentConfig,
    ModelConfig,
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


def test_the_transcriber_can_be_told_to_detect_the_language_instead_of_being_told_it() -> None:
    """D-584, and it is a fallback the vendor forced rather than a feature we wanted.

    Four live 400s exhausted their Sarvam model enum against `te-IN` (11 Sep 2026):

        "Provided language: te-IN is not available for the model: saaras:v3"
        "Model 'saarika:v2.5' is deprecated and can no longer be used. Use
         'saaras:v4' instead."
        "Provided language: te-IN is not available for the model: saaras:v4"

    and `saaras:v2.5` transcribes to English (banned by `SARVAM_TRANSLATING_STT`). Their
    `language` enum has one value left — `unknown`, documented for automatic detection
    (`api-reference/agent/v2/create.md:1078-1091`).

    TWO PROPERTIES, and the second is the hard-rule-2 one. The flag on the contract is a
    BOOLEAN about the product question (pinned, or discovered?); the pseudo-language
    `unknown` is the vendor's spelling of the answer and never leaves the adapter. And the
    SPEAKING leg does not inherit it: a sentinel meaning "work it out" is meaningless to a
    TTS provider, and an agent that listens in an unknown language still speaks Telugu.
    """
    assert get_settings().stt_autodetect_language is False, (
        "detection became the default; it is strictly weaker than pinning and unverified "
        "for Telugu, so it may only be turned on deliberately (hard rule 11)"
    )

    pinned = _transcriber_language(_config())
    assert pinned == "te-IN", "an agent that pinned its language stopped pinning it"

    detecting = _config()
    detecting = detecting.model_copy(
        update={"models": detecting.models.model_copy(update={"stt_autodetect": True})}
    )
    assert _transcriber_language(detecting) == "unknown"
    speaks = _synthesizer_config(detecting.models, detecting.language_primary)
    assert speaks["language"] == "te-IN", (
        "the voice leg inherited the transcriber's sentinel; `unknown` is not a language a "
        "TTS provider can speak in, and the agent still speaks Telugu"
    )


# --- the TTS leg (defect 3) ---------------------------------------------------


def test_the_catalogue_id_is_split_into_the_model_and_the_speaker() -> None:
    """`agents.tts_voice` holds OUR id; `ModelConfig` holds the vendor's two facts."""
    speech = in_call_speech(_row(), engine=FakeEngine())

    assert speech["tts_model"] == DEFAULT_TTS_MODEL
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


# --- the wire body ------------------------------------------------------------


def _config() -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic receptionist",
        direction="inbound",
        system_prompt="You are the receptionist for Sunrise Clinic.",
        opening_line="Idi AI assistant.",
        # THE FOUR SPEECH FIELDS COME FROM THE RESOLVER, NOT FROM A HAND-TYPED COPY, and
        # that is the point of this fixture rather than a convenience. They were typed out
        # here, and the copy drifted the moment `in_call_speech` started resolving a fifth
        # fact (`tts_voice_label`, D-582): the body under test kept asserting a shape no
        # publish would ever send, and the assertion below went green on a payload
        # production does not produce. A fixture that reproduces the resolver is a second
        # definition of it; this calls it.
        models=ModelConfig(
            llm_model="sarvam-105b",
            tts_provider="sarvam",
            **in_call_speech(_row(), engine=FakeEngine()),
        ),
    )


async def _created_tools() -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"agent_id": "agent_1"})

    engine = BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )
    await engine.create_agent(_config())
    tools: dict[str, Any] = seen["agent_config"]["tasks"][0]["tools_config"]
    return tools


async def test_the_synthesizer_names_the_model_and_the_speaker_in_the_vendors_own_keys() -> None:
    """The exact shape of `create-agent/SKILL.md`'s example. `voice` and `voice_id` are
    BOTH sent because the example sends both, and guessing which one their provider reads
    is the guess this change exists to stop making."""
    synthesizer = (await _created_tools())["synthesizer"]

    assert synthesizer["provider_config"] == {
        "model": "bulbul:v3",
        # The catalogue's LABEL, looked up by the resolver — never `voice_id.capitalize()`.
        # The two are indistinguishable on every Sarvam persona and unrelated on a cloned
        # voice (`api-reference/voice/get_all.md:102-112`), which is why the resolver owns
        # it (D-582).
        "voice": "Ashutosh",
        "voice_id": "ashutosh",
        # The voice block carries its own language, in `provider_config` where the Cartesia
        # arm already put it — their validator demands it ("Voice > Language: This field is
        # required") and the Sarvam arm was dropping the parameter it was handed (D-580).
        "language": "te-IN",
    }
    assert synthesizer["stream"] is True


async def test_the_transcriber_is_no_longer_two_nulls() -> None:
    """Defect 2 at the wire. This block used to be `{"provider": null, "model": null}` on
    every agent this product has ever published."""
    transcriber = (await _created_tools())["transcriber"]

    assert transcriber["provider"] == SARVAM_STT_PROVIDER
    assert transcriber["model"] == SARVAM_DEFAULT_STT


async def test_what_we_send_reads_back_as_what_we_sent() -> None:
    """THE DRIFT PROPERTY, and the reason both halves are pinned in one file.

    `verify_publish` compares the config a publish sends against `_agent_models`' reading
    of the agent the engine returns. Their platform stores `agent_config.model_dump()` and
    returns THAT, so our own request body is the closest thing to a real response this
    suite can construct — and if the send path and the read path disagree about which key
    holds the speaker, every agent in the product reports as drifted forever.
    """
    tools = await _created_tools()

    models, readable = _agent_models({"tasks": [{"tools_config": tools}]})

    assert readable
    assert models is not None
    sent = _config().models
    assert (models.stt_provider, models.stt_model) == (sent.stt_provider, sent.stt_model)
    assert (models.tts_provider, models.tts_model) == (sent.tts_provider, sent.tts_model)
    assert models.tts_voice == sent.tts_voice


def test_an_engine_that_echoes_only_the_display_name_still_reads_back_as_the_speaker() -> None:
    """The fallback, and it is a NORMALISATION named as one.

    We send the speaker twice — `voice` capitalised, `voice_id` lowercase — and which of
    the two their platform stores is not settled (OPERATIONS §2 gate 3). An engine that
    echoes only `voice` must not report a mismatch against our lowercase id: the ids are
    lowercase by the vendor's own enum, so lowering recovers ours for the shape we send.
    """
    models, readable = _agent_models(
        {
            "tasks": [
                {
                    "tools_config": {
                        "llm_agent": {"llm_config": {"model": "sarvam-105b"}},
                        "synthesizer": {
                            "provider": "sarvam",
                            "provider_config": {"model": "bulbul:v3", "voice": "Ashutosh"},
                        },
                        "transcriber": {"provider": "sarvam", "model": SARVAM_DEFAULT_STT},
                    }
                }
            ]
        }
    )

    assert readable
    assert models is not None
    assert models.tts_voice == "ashutosh"
    assert models.tts_model == "bulbul:v3"
