"""The voice vocabulary: tiers, curation states, voice ids, and the cached voice catalogue.

`voice_tier()` is the ONE derivation of an agent's billing rung from the voice on its row
(plan §2.3 invariant 7): the rung is derived from the id's own model prefix through the one
model->provider registry (`calevate_shared.model_lifecycle.TTS_MODEL_LIFECYCLE`) and is
stored nowhere it could disagree. Rungs are `clear`/`studio` (`billing/rates.VoiceTier`);
providers are vendors. An id naming none of our models bills on the Clear rung, because
Studio is chosen, never inherited.

The catalogue itself is DATA, cached in `platform_voice_catalog` and installed as a process
snapshot by `agents/voice_sync.load_voice_catalogue`, so a stored voice id from an earlier
catalogue still reads back as itself (`get_voice`, `speech_for_voice_id`). Voices an engine
HOSTS (ThinnestAI, D-687) are read and curated by `agents/hosted_voices.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, cast, get_args

from calevate_shared.model_lifecycle import TTS_MODEL_LIFECYCLE, TtsProvider
from pydantic import BaseModel, ConfigDict

from apps.api.agents.languages import Language
from apps.api.billing.rates import PREMIUM_VOICE_TIER, VALUE_VOICE_TIER, voice_tier_label
from apps.api.billing.rates import VoiceTier as BillingVoiceTier

# `Language` MOVED TO `agents/languages.py` AND IS IMPORTED, NOT DECLARED (see that
# module's docstring). It was declared here while "which languages do we sell" had nowhere
# else to live, and that made the answer a property of the VOICE CATALOGUE — so the copilot
# and the org-create route imported a catalogue to learn a commercial fact, and the vendor
# capability behind it (Sarvam's 11-language TTS enum, which this comment used to cite)
# looked like the same question. It is not: the speech stack can converse in eleven
# languages (`calevate_shared.languages`), and the product sells three.
#
# Imported and NOT re-exported: `Voice.languages` below is annotated with it, and every
# other caller takes it from `agents/languages.py`. Two import paths to one name is the
# same drift in a smaller font.

# The TTS models a cached catalogue row may name. A Literal so a catalogue entry cannot name
# a model we do not price, and so `TTS_MODEL_LIFECYCLE` can be checked against exactly this
# set (`scripts/check_model_lifecycle`).
TtsModel = Literal["sonic-3.5"]

#: Who synthesises a voice — and, by plan §2.3 invariant 7, the agent's VOICE TIER. ONE
#: definition, shared with the lifecycle registry so the two cannot spell a provider
#: differently. `voice_tier()` returns it; nothing stores it beside the voice.
VoiceProvider = TtsProvider

#: The tier vocabulary a consumer (the pipeline's `meta.voice_tier`, the lot debit, the
#: runway) reads.
#:
#: `billing/rates.VoiceTier` imported, so there is exactly one place a tier is named. A
#: PROVIDER is not automatically a tier: `voice_tier()` maps provider to tier and REFUSES
#: where the mapping is empty, so no unpriced minute enters the money lane (hard rule 7).
#: It is `meta.voice_tier`, not `meta.tts_tier`, which is the plan's overage rung.
VoiceTier = BillingVoiceTier

Gender = Literal["female", "male", "neutral"]

#: WHAT A CURATED VOICE'S STATE IS, in the vocabulary the console writes and the offer
#: seam reads (D-588). It lives here because it is a fact
#: ABOUT A VOICE — stored on `platform_voice_catalog`, checked by a DB constraint, rendered
#: in a table — while the VERDICT it feeds is the offer seam's.
#:
#: * `enabled`   — an operator has chosen to offer this voice. The ONLY offerable state.
#: * `disabled`  — synced and known, deliberately not offered. The state a voice ARRIVES in
#:                 (the column default), so a voice the vendor adds to their platform never
#:                 reaches a client without somebody deciding.
#: * `archived`  — retired by an operator: not offered, and filed away from the working
#:                 list. It is not a delete, because the row is also what stops a returning
#:                 voice re-arriving as a fresh un-curated one.
#:
#: **`archived` AND `disabled` DIFFER TO A HUMAN AND NOT TO THE OFFER SEAM.** Neither is
#: offerable; the distinction is which list an operator finds it in and which sentence they
#: read. Collapsing them to a boolean was the first shape and it lost the only thing the
#: founder asked for beyond on/off — a way to put a voice away without it cluttering the
#: screen every time the vendor's list is re-read.
CurationState = Literal["enabled", "disabled", "archived"]

#: The state a NEWLY SYNCED voice arrives in. Named once so the column default, the sync's
#: reasoning and the console's empty state cannot come to disagree about it.
#:
#: DISABLED, and this is the whole of the founder's requirement in one constant: *only the
#: voices they add there are selectable*. A voice defaulting to `enabled` would mean the
#: vendor adding a persona to their platform silently puts it in front of every client of
#: every tenant, with no operator in the loop — the failure direction that cannot be undone
#: by noticing it later, because by then somebody's agent is speaking it.
ARRIVAL_CURATION_STATE: Final[CurationState] = "disabled"

#: WHY A CATALOGUE ROW EXISTS (D-590). `synced` — a sync read it off the voice platform's
#: list; `operator` — somebody typed its facts and they were verified against that list.
#:
#: The two are IDENTICAL everywhere else on purpose: one row shape, one `Voice`, one picker,
#: one publish path, so nothing downstream branches on provenance. What it buys is the two
#: things provenance is actually needed for — a console that opens with the voices an
#: operator added rather than with the vendor's whole catalogue, and a sync that cannot
#: reclassify a typed row as a cache line it may overwrite.
VoiceOrigin = Literal["synced", "operator"]

#: The provenance a row gets when nothing says otherwise — the column default, and what the
#: sync produces. Named so the migration, the model and the sync cannot disagree.
DEFAULT_VOICE_ORIGIN: Final[VoiceOrigin] = "synced"


#: There is no default TTS model: an agent with no voice id speaks whatever the leg that runs
#: the call defaults to, and `voice_tier()` prices it on the Clear rung.


def voice_id_for(tts_model: str, speaker: str) -> str:
    """THE id spelling, in one place: `<tts_model>:<speaker>`.

    Every catalogue id, the migration's backfill target and `publish_agent`'s mirror write
    all come through here or through `voice_id_of` below. A second `f"{model}:{speaker}"`
    anywhere is a second definition of a value stored on agent rows — i.e. a data
    migration waiting to be caused by a typo.
    """
    return f"{tts_model}:{speaker}"


def voice_id_of(tts_model: str | None, speaker: str | None) -> str | None:
    """`voice_id_for`'s inverse-facing partner: the catalogue id a published `ModelConfig`
    TTS pair names, or None when it names no voice at all.

    `publish_agent` records what it SENT in `agents.live_tts_voice`, and what it sent is
    the split pair — while the column, `agents.tts_voice` and `publishing.py`'s divergence
    check are all written in catalogue IDs. Recomposing here rather than re-reading the row
    keeps `publish_agent`'s own rule (record the config you just handed the engine, never a
    re-read that a concurrent voice write could have moved underneath you).

    A speaker with no model — the unrecognised free-text id `speech_for_voice_id` passes
    through — recomposes to itself, so a legacy row still round-trips to the value it holds
    instead of gaining a prefix nothing wrote.
    """
    if speaker is None:
        return None
    if tts_model is None:
        return speaker
    return voice_id_for(tts_model, speaker)


def speech_for_voice_id(voice_id: str | None) -> tuple[str | None, str | None]:
    """`(tts_model, speaker)` for a stored voice id — THE splitter, and the only one.

    CATALOGUE LOOKUP, NEVER STRING SURGERY, and the difference is a live defect rather
    than a preference. Splitting on the last colon turns a free-text value with a
    colon in it into a model and a speaker the vendor has never heard of, sent
    confidently. The catalogue knows which ids it composed; anything else is not ours to
    take apart.

    An id we do not recognise returns `(None, voice_id)`: it travels in the speaker slot
    exactly as it did before this split existed. That is deliberate and is the same
    argument `_agent_voice` makes in `publishing.py` — `agents.tts_voice` is free text, and
    a value we no longer offer must read back as itself rather than be dropped or guessed
    at. Migration `f1c9d4a72b06` backfills the rows this repository actually wrote.
    """
    if not voice_id:
        return (None, None)
    voice = _snapshot.by_id.get(voice_id)
    if voice is None:
        return (None, voice_id)
    return (voice.tts_model, voice.speaker)


class Voice(BaseModel):
    """One selectable voice. Doubles as the API response model — the catalog IS the
    contract, so there is nothing to keep in sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Written VERBATIM into `agents.tts_voice`. Stable: it is stored on agent rows, so
    # renaming one is a data migration, not an edit to this file. `<tts_model>:<speaker>`,
    # composed by `voice_id_for` — see the module docstring for why the pair is spelled
    # into one string here and split back apart in `ModelConfig`.
    id: str
    # What a human picks from. A persona label (speaker), NOT a tier — the tier is
    # `provider`, and price is a question the credit lot answers, not this field.
    #
    # It is also a wire value (`ModelConfig.tts_voice_label`): a cloned voice's name has no
    # derivable relationship to its id, so it can only come from where the voice was listed.
    label: str
    #: Who synthesises it — and therefore the agent's voice tier (`voice_tier()`).
    provider: VoiceProvider
    # Which model serves this voice. Separate from `id` so that named speakers
    # do not each become their own model.
    tts_model: TtsModel
    # THE SPEAKER, which is the half that was missing and the whole of D-358's second
    # defect: the model string used to be sent in the vendor's speaker slot.
    #
    # A BARE `str`, and it is the honest type. The two providers name a voice
    # differently — a Cartesia voice is a generated id,
    # a CLONE is whatever the founder called it — and none of the three is a set this
    # repository is entitled to enumerate. It was a `Literal` of the model vendor's 44
    # names until D-588; that Literal was the defect, not the guarantee.
    speaker: str
    # Telugu first. The three languages the product offers, a subset of the vendor's own
    # 11-code TTS enum — not a claim about the other eight.
    languages: tuple[Language, ...]
    # ALWAYS None, and it is a decision rather than a gap. The SDK's speaker type is a bare
    # name Literal carrying NO gender metadata, so there is nothing to state and a name is
    # not evidence. The field stays for the day a vendor enumeration carries one.
    gender: Gender | None = None
    # TRUE ON EVERY ENTRY NOW, AND IT MEANS ONE NARROW THING: the ENGINE's own
    # voice-config API listed this voice, on our own account, for a model we offer. It is
    # not an ear test. The field survives the seed's deletion because it is the only place
    # that distinction is stated on the wire, and because an entry that is ever built from
    # anything other than a live listing must be able to say so.
    verified: bool = False
    # One line an operator can read in a dropdown, with the cost consequence in it.
    note: str


#: The shared half of every Cartesia entry's `note`, for the same reason and through the
#: same label. The Telugu sentence is not decoration: Cartesia documents Hinglish
#: code-switching and says NOTHING about Telugu-English, so a screen that let a client infer
#: it from "Telugu is supported" would be promising something no page states (module
#: docstring, hard rule 11).
#:
#: It names none of our own settings: a catalogue note is client-readable and cannot know
#: whether the key is installed or the price attested.
_CARTESIA_NOTE: Final = (
    f"The {voice_tier_label('cartesia')} voice tier, billed at the higher per-minute rate on "
    "every credit lot. Telugu is supported. Mixing Telugu and English inside one sentence is "
    "not a case the voice is made for, so do not promise it."
)


def catalogue_note(provider: VoiceProvider) -> str:
    """THE one line an operator or client reads beside a voice, per provider.

    Public because `agents/voice_sync.py` builds every catalogue entry from the ENGINE's
    cached rows and needs one sentence per provider — a second string composed there would be the
    copy that drifts the day the tier labels change, which is the whole reason each note is
    composed from `voice_tier_label` rather than typed.
    """
    del provider
    return _CARTESIA_NOTE


#: Where the voices currently in force came from. `"engine"` means a sync read them off the
#: engine account; `"unsynced"` means no sync has ever succeeded on this process, so there
#: are NO voices and nobody can be offered one. Carried on the API response so an operator
#: or a client reading an empty picker is told which of those two they are looking at,
#: instead of guessing at a bug.
#:
#: ⚠ **THE THIRD VALUE, `"seed"`, IS GONE (D-588)** — there is no compiled fallback any
#: more. A surface that still branches on it is reading a state this process cannot be in.
CatalogueSource = Literal["unsynced", "engine"]


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """The voices in force, their id index and where they came from — as ONE value.

    One object rather than three module globals for `VoiceSelectionCapability`'s reason: a
    reader that took the list from one place and the index from another could observe a
    half-applied refresh. Installing a snapshot is a single rebind, so every reader sees
    either the whole old catalogue or the whole new one.
    """

    voices: tuple[Voice, ...]
    by_id: dict[str, Voice]
    source: CatalogueSource


def _snapshot_of(voices: tuple[Voice, ...], source: CatalogueSource) -> _Snapshot:
    return _Snapshot(voices=voices, by_id={voice.id: voice for voice in voices}, source=source)


#: NO VOICES, BECAUSE NOBODY HAS SYNCED. The state a process boots in and the state it
#: returns to when the cache is empty — not an error, and not a shorter list.
_UNSYNCED_SNAPSHOT: Final = _snapshot_of((), "unsynced")

#: THE CATALOGUE IN FORCE. Rebound by `install_voice_catalogue`; never mutated in place.
_snapshot: _Snapshot = _UNSYNCED_SNAPSHOT


def install_voice_catalogue(voices: tuple[Voice, ...] | None) -> None:
    """Install the synced catalogue for this process. `None` or `()` means "none in force".

    THE SAME SHAPE AS EVERY OTHER PLATFORM-SCOPED FACT THIS TREE SERVES OFF A SNAPSHOT —
    `voice_offer.install_tts_price_reader`, `billing/rates.install_llm_price_attestations`,
    `ops/pricing_snapshot.install_pricing_readers`. It is deliberately NOT an async read
    per request: `get_voice`, `speech_for_voice_id` and `voice_tier` are called from the
    publish path, the splitter and the money lane, all of which are synchronous by design
    and some of which hold no session. Turning them async to fetch platform-scoped rows
    that change when an operator presses a button would be a database round trip on every
    agent publish for a value that moves monthly.

    `agents/voice_sync.load_voice_catalogue` is the one caller in production (at API and
    worker startup, and after every sync); tests drive it directly and reset with `None`.

    ⚠ **AN EMPTY TUPLE USED TO RAISE, AND NOW INSTALLS.** The refusal existed to protect a
    SEED — "a picker with no voices is indistinguishable from a platform with no voices" was
    true only while a compiled fallback meant the second could not happen. D-588 deleted the
    seed, so "no voices in force" became a real, correct and reachable state: a deployment
    where nobody has synced. Refusing it would leave a process serving whatever it happened
    to load last, forever, with no way to observe that the cache behind it is empty.

    **What the refusal actually protected has NOT moved and has NOT weakened.** A SYNC that
    reads nothing is still refused at the place that can tell the difference —
    `voice_sync.sync_voice_catalogue` alerts (`voice_catalogue_empty`) and writes nothing, so
    a revoked credential or a moved route leaves the TABLE standing and this function is
    never called with `()` on that path. Only an honestly empty table reaches here.
    """
    global _snapshot
    if not voices:
        _snapshot = _UNSYNCED_SNAPSHOT
        return
    _snapshot = _snapshot_of(voices, "engine")


def catalogue() -> tuple[Voice, ...]:
    """THE voices in force — synced from the engine, or EMPTY until one lands.

    Every reader goes through here rather than through a module constant, because the
    catalogue is now DATA THAT MOVES: an operator clones a voice on the voice platform,
    refreshes, enables it, and the picker has to show it without a deploy.

    ⚠ **THIS IS THE LOOKUP LAYER, NOT THE OFFER LAYER.** It answers with every voice the
    engine account lists, INCLUDING ones an operator has disabled or archived, because its
    callers are `get_voice`, `speech_for_voice_id` and the publish path — which must keep
    resolving the id a live agent is already speaking however the console has been clicked
    since.
    """
    return _snapshot.voices


def catalogue_source() -> CatalogueSource:
    """`"unsynced"` or `"engine"` — see `CatalogueSource` for why a caller must be able to
    tell an empty picker on a fresh deployment from a broken one."""
    return _snapshot.source


def get_voice(voice_id: str) -> Voice | None:
    """The catalog entry for `voice_id`, or None if we do not offer it.

    Exact match, no normalisation: `agents.tts_voice` is pasted into a vendor request
    verbatim, so accepting `Sonic-3.5:…` here would store a string that differs from the
    one we tested, which is the entire failure this module exists to prevent.
    """
    return _snapshot.by_id.get(voice_id)


def is_supported_voice(voice_id: str) -> bool:
    """Is this a voice we support? — the question the API must be able to answer
    BEFORE a string reaches an agent row and, from there, the engine."""
    return voice_id in _snapshot.by_id


def voice_ids() -> tuple[str, ...]:
    """Every id we accept, in catalog order — for error remediation text and tests."""
    return tuple(_snapshot.by_id)


def provider_of_tts_model(tts_model: str) -> VoiceProvider | None:
    """Which vendor synthesises this model — from the ONE registry that knows, or None.

    `calevate_shared.model_lifecycle.TTS_MODEL_LIFECYCLE` maps a model string to its
    provider and is already the table `scripts/check_model_lifecycle` holds `TtsModel` to,
    so there is exactly one place a model's provider is written down. A second mapping here
    (a dict beside `TtsModel`, a `startswith("sonic")`) would be the place the two could
    come to disagree about which tier a minute bills at.
    """
    row = TTS_MODEL_LIFECYCLE.get(tts_model)
    return row.provider if row is not None else None


def tts_models_for_provider(provider: str) -> tuple[TtsModel, ...]:
    """Every model WE OFFER on this provider, in `TtsModel` order — the inverse of
    `provider_of_tts_model`, and derived from the same one registry.

    The add form (D-590) asks an operator for a provider AND a model and then cross-checks
    the pair, so it needs to be able to say "this provider runs `sonic-3.5` here" without a
    second mapping beside `TTS_MODEL_LIFECYCLE`. Today each provider has exactly one model,
    which is a fact about our catalogue and not a fact this function is allowed to assume:
    it answers with a tuple so a second model on one provider reaches the form by existing.

    Returns `()` for a provider this product does not have — which is a real answer.
    """
    return tuple(model for model in get_args(TtsModel) if provider_of_tts_model(model) == provider)


def tts_model_of_voice_id(voice_id: str | None) -> TtsModel | None:
    """The MODEL half of a stored voice id, read from the id ITSELF — no catalogue.

    `voice_id_for` composes `<tts_model>:<speaker>`, and every model we offer is a member
    of `TtsModel`, so the model is recoverable from the string by asking which member it is
    prefixed with. Deliberately NOT `rsplit(":", 1)`: a free-text row with one colon in it
    would split to a model no vendor has ever heard of. Matching against
    `get_args(TtsModel)` can only ever answer with a model we actually offer.

    None for a free-text id that names none of our models — which is a real answer and the
    caller must treat it as one (see `voice_tier`).
    """
    if not voice_id:
        return None
    for model in get_args(TtsModel):
        if voice_id == model or voice_id.startswith(f"{model}:"):
            # `get_args` is untyped to mypy; the comparison is what narrows it, and the
            # members it iterates ARE `TtsModel` by construction.
            return cast("TtsModel", model)
    return None


#: WHICH PRICED TIER EACH PROVIDER BILLS ON. Total over `VoiceProvider`, so adding a fourth
#: provider fails `voice_tier` at the type level rather than silently inheriting a rate
#: nobody struck for it.
VOICE_TIER_OF_PROVIDER: Final[Mapping[VoiceProvider, VoiceTier | None]] = {
    "cartesia": PREMIUM_VOICE_TIER,
}


class UnpricedVoiceProviderError(ValueError):
    """A voice was asked what it bills at, on a provider nothing can bill.

    Raised rather than defaulted, for `billing/rates.llm_inr_per_ktok`'s reason:
    *"a leg we cannot
    price raises"*. Defaulting to the value tier would be the same defect D-585's
    catalogue-membership lookup had — a minute billed at a rate nobody struck for it, on an
    append-only ledger, silently.

    ⚠ **NO PROVIDER IN `VOICE_TIER_OF_PROVIDER` MAPS TO `None` TODAY, AND THE ARM STAYS.**
    The arm
    is what makes the mapping's `VoiceTier | None` type mean something: the next provider is
    added as a row, and until somebody decides which rung it bills on it raises here rather
    than inheriting the cheaper one. Deleting it would make the honest answer for a new
    provider "the value rate", chosen by nobody. No shipped provider reaches it.
    """


def voice_tier(tts_voice: str | None) -> VoiceTier:
    """THE agent's voice tier: the provider of the voice on its row, and nothing else.

    Plan §2.3 invariant 7 and §3.3: the tier is DERIVED, never stored, so an agent cannot
    hold a Studio voice and a Clear tier. This is the one function that derives it — the
    pipeline's `meta.voice_tier`, the credit-lot debit and the runway all ask here.
    NOT `meta.tts_tier`, which this line used to name: that key carries the plan's OVERAGE
    RUNG and is stamped separately on purpose (see `VoiceTier` above).

    ⚠ **IT IS DERIVED FROM THE ID, NOT FROM CATALOGUE MEMBERSHIP, AND THAT CHANGED ON
    11 SEP 2026 (D-585) — THE CHANGE REACHES MONEY.** This used to look the id up in
    `CATALOG` and return the cheaper tier when it was absent. That was safe only while the
    catalogue was a frozen compiled constant: every id that could exist was in it. The
    catalogue is now CACHED FROM THE ENGINE (`agents/voice_sync.py`), so "absent" became a
    state a live Cartesia agent can be in — a cache not yet synced, a sync that pruned a
    voice the vendor withdrew, a clone renamed. In every one of those, a Cartesia agent
    would have billed at the cheaper rate, silently, on an append-only ledger (hard rule 7).

    So the tier comes from the id's own model prefix and the one model→provider registry.
    `sonic-3.5:…` is Studio whether or not a row for that voice
    exists anywhere, which is the property the money lane needs.

    It returns the PRICED tier the provider bills on, through `VOICE_TIER_OF_PROVIDER`, and
    RAISES `UnpricedVoiceProviderError` for a provider that has none.

    **THE VALUE TIER FOR AN EMPTY ID OR ONE NAMING NONE OF OUR MODELS, and that is a
    decision rather than a fallback.** An agent with no voice speaks whatever the leg
    running the call defaults to, and a free-text row this product no longer recognises is
    not evidence of the dearer rung. Cartesia is chosen, never inherited (plan §0 Q9) — the
    only way onto the dearer tier is an id that names the Cartesia model.
    """
    model = tts_model_of_voice_id(tts_voice)
    provider = provider_of_tts_model(model) if model is not None else None
    if provider is None:
        return VALUE_VOICE_TIER
    return voice_tier_of_provider(provider, voice_id=tts_voice)


def voice_tier_of_provider(provider: VoiceProvider, *, voice_id: str | None = None) -> VoiceTier:
    """THE rung a TTS PROVIDER bills on, raising when it bills on none.

    Split out of `voice_tier` on 19 Sep 2026 because it had a second caller — the
    plan-billed volume counter (`billing/tts_volume.PLAN_BILLED_VOICE_TIER`), which knows
    its vendor and needs that vendor's rung. Before the rungs were renamed to
    `clear`/`studio` that counter compared a call's TIER against a constant holding a
    PROVIDER name and matched because both words were `"cartesia"`; deriving the rung here
    is what stops the next provider re-creating that coincidence.

    `voice_id` is for the message only. A caller that has one gets it named in the error,
    because "which voice did this" is the first question an operator asks.
    """
    tier = VOICE_TIER_OF_PROVIDER[provider]
    if tier is None:
        subject = f"voice {voice_id!r} is synthesised by {provider!r}" if voice_id else provider
        raise UnpricedVoiceProviderError(
            f"{subject}, which has no priced tier on this deployment — a minute on it "
            "cannot be billed until an operator attests what it costs (hard rule 7)."
        )
    return tier


__all__ = [
    "ARRIVAL_CURATION_STATE",
    "DEFAULT_VOICE_ORIGIN",
    "VOICE_TIER_OF_PROVIDER",
    "CatalogueSource",
    "CurationState",
    "Gender",
    "TtsModel",
    "UnpricedVoiceProviderError",
    "Voice",
    "VoiceOrigin",
    "VoiceProvider",
    "VoiceTier",
    "catalogue",
    "catalogue_note",
    "catalogue_source",
    "get_voice",
    "install_voice_catalogue",
    "is_supported_voice",
    "provider_of_tts_model",
    "speech_for_voice_id",
    "tts_model_of_voice_id",
    "tts_models_for_provider",
    "voice_id_for",
    "voice_id_of",
    "voice_ids",
    "voice_tier",
    "voice_tier_of_provider",
]
