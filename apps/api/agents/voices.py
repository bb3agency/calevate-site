"""The voice catalog: which TTS voices an agent may speak in, as DATA.

`agents.tts_voice` is a free-text column (`agents/models.py`, DATA-MODEL §2 lists it
among the "config strings"). Free text is fine for the DB — model choices are config,
not code (D-04/D-20/D-36) — but it is not fine for the UI or the API: an operator who
types `bulbul-v3` or `Anushka` gets a row that looks saved, publishes cleanly, and is
discovered to be wrong at CALL TIME, on a real client's phone. This module is the
allowlist that turns that runtime failure into a 422.

TWO VOICE TIERS, ONE CATALOGUE (D-547 — supersedes the single-tier decision)
------------------------------------------------------------------------------
The single-tier decision collapsed the old premium/value ladder (D-36/D-35/D-34) into ONE
Sarvam quality. D-547 (`docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md`) re-opens the dimension
in a different shape: a **second PROVIDER**, Cartesia `sonic-3.5`, chosen **per agent**,
priced **per credit lot** at that lot's rate for the agent's tier. So a `Voice` now carries
`provider: sarvam | cartesia`, and `voice_tier()` below is the ONE derivation of an
agent's tier — a pure function of its chosen voice's provider (plan §2.3 invariant 7:
there is no way to hold a Cartesia voice and a Sarvam tier, because the tier is not
stored anywhere it could disagree).

**NO PRICE IS WRITTEN IN THIS MODULE.** It used to say "₹5.00/min, ₹30 per 10k chars"
in this docstring and in every entry's note. A rate card belongs to `billing/` — under
D-547 a minute's price is the rate frozen on the credit lot it draws from, and there
are two of them per lot — so a figure here would be a second, stale definition of a
number that reaches money (hard rule 7). What this module says about cost is the TIER,
which is the only pricing fact a voice has.

**"Two providers" is still not "two qualities of Sarvam".** Bulbul v2 stays withdrawn;
clients choose a PERSONA within a provider. The `Voice` model keeps its persona fields.

WHAT IS GROUNDED, AND WHERE
---------------------------
- **The 44 speaker ids are the vendor's own closed enum.** VERIFIED-VENDOR-SDK:
  sarvamai==0.1.31 (PyPI wheel), `types/text_to_speech_speaker.py`, read 27 Aug 2026 —
  `TextToSpeechSpeaker` is a `Literal` of exactly 44 lowercase names, and `SPEAKERS` below
  is that list, in that order, with nothing added.
- **The model string is `bulbul:v3`.** VERIFIED-VENDOR-SDK: same wheel,
  `types/text_to_speech_model.py` (`Literal["bulbul:v2", "bulbul:v3"]`), and Bolna's own
  example posts it (VERIFIED-VENDOR-REPO, `bolna-ai/skills@28b24aa`,
  `create-agent/SKILL.md`: `"provider_config": {"model": "bulbul:v3", "voice": "Ashutosh",
  "voice_id": "ashutosh"}`). Sarvam's dashboard Model Catalogue lists ONLY `bulbul:v3` —
  no v2 row, no v4 — even though the SDK enum still carries `bulbul:v2`
  (VENDOR-PUBLISHED (Sarvam dashboard Model Catalogue, indus.sarvam.ai/model-catalogue,
  read by the founder 27 Aug 2026)). `TtsModel` carries no second Sarvam member on that
  basis; its second member is Cartesia's.
- **Telugu on the TTS leg** is the SDK's `types/text_to_speech_language.py`, which lists 11
  codes INCLUDING `te-IN`, `hi-IN` and `en-IN` (same wheel, same date). That enum is the
  citation, not the marketing count: the founder could not find a dashboard-rendered list
  naming `te-IN` against Bulbul v3 specifically, so the claim stays scoped to the enum.
  `languages` below carries the three the PRODUCT sells (`CreateOrgIn.language`), Telugu
  first, which is a subset of the enum rather than a re-statement of a count.

THE ID SPELLING, WHICH IS A DATA-SHAPE CONTRACT
------------------------------------------------
An id is `<tts_model>:<speaker>` — `bulbul:v3:ashutosh` — composed by `voice_id_for()`,
which is the ONE place the spelling exists. This is the shape this file predicted before
it could be built ("an id becomes `bulbul:v3:<speaker>` while `tts_model` stays
`bulbul:v3`"), and it is why `id`, `tts_model` and `speaker` are three fields: several
personas share one model, and the id has to stay unique across a future second model.

`agents.tts_voice` holds the ID. `ModelConfig.tts_model` / `ModelConfig.tts_voice` hold
the SPLIT — the model and the speaker, one per vendor slot — because the adapter must not
have to know how we spell an id (hard rule 2). `speech_for_voice_id()` is the splitter and
`voice_id_of()` is its inverse, used by `publish_agent` to record what it sent.

WHAT IS STILL PROVISIONAL (read this before quoting the catalog at anyone)
--------------------------------------------------------------------------
1. **`verified` is still False on every entry**, and that is not pedantry. The speaker enum
   is Sarvam's, for Sarvam's own TTS API; what BOLNA's Sarvam provider accepts is their
   business, and the confirming read is `GET /me/voices` on a live account. OPERATIONS §2
   gate 3 owns it. Nothing here claims a speaker was heard.
2. **The SDK does not split the speaker list by model.** `TextToSpeechSpeaker` is one enum
   for a request that takes `model` and `speaker` as independent fields, so "all 44 work on
   `bulbul:v3`" is the strongest reading available and is not a vendor statement. Gate 3
   settles it; a speaker the engine rejects is one line removed from `SPEAKERS`.
3. **Which speaker sounds best in Telugu is an EAR TEST, not a spec fact** (docs/BRD.md:242
   R-10, docs/TRD.md:478). `DEFAULT_SPEAKER` below is a PLACEHOLDER pending that test — it
   is `ashutosh` because that is the speaker the vendor's own worked example uses, which is
   the only non-invented basis available. It is not a measurement and must not be quoted as
   one.
4. **`gender` is `None` on every entry, on purpose.** The SDK carries NO gender metadata for
   speakers — the field is a bare name Literal — and a name is not evidence of a voice. The
   persona field stays because a future vendor enumeration may carry it; guessing "female"
   from "priya" would be exactly the laundering hard rule 11 forbids.

THE CARTESIA HALF: A SHAPE WITH NO ENTRIES YET, AND WHY (D-547 §0 Q1)
------------------------------------------------------------------------
Cartesia's voice library is behind a login (`play.cartesia.ai/voices`, egress-blocked
here), so no voice id can be typed into this file without inventing one — and an
invented id publishes an agent that 422s on a client's phone. The founder's answer is
that the catalogue is BUILT FROM CARTESIA'S OWN VOICES API (`GET /voices`, the endpoint
`ops/secret_probes.py` already hits), filtered to Telugu / Hindi / Indian English, and
the exact field names come from a research report not yet delivered. So this module
ships the SHAPE: `CartesiaVoiceRecord` is the record that report's API output is
dropped into, `CARTESIA_CATALOG_SOURCE` is the (empty) list of them, and
`_cartesia_entry` builds a `Voice` from one. The import-time assertions hold with zero
Cartesia entries, and the offerability seam (`agents/voice_offer.py`) already refuses a
Cartesia voice for the three reasons that will still apply when entries exist.

**`sonic-3` IS DELIBERATELY ABSENT, AND NOW FOR TWO REASONS RATHER THAN ONE.** Bolna
lists three Cartesia models and says which to run: *"use `sonic-3.5` for production
agents that need stable output"* (VERIFIED-VENDOR-DOCS,
`bolna-findings/mirror/pages/providers/voice/cartesia.md:57-67`). And the model vendor
has now DATED it: `sonic-3` (snapshot `sonic-3-2025-10-27`) is deprecated with a
**sunset of 20 Oct 2026**, shared with `sonic-2` and `sonic-turbo` — VENDOR-PUBLISHED
(`docs.cartesia.ai/build-with-cartesia/tts-models/api-changes`, read 7 Sep 2026 and
relayed in `docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md` ADDENDUM 1; the host is
egress-blocked from this container, so it was not read here). It was recorded as
REPORTED until that reading; it is not on Bolna's page, and `TTS_MODEL_LIFECYCLE`
carries it beside the row it explains.

**`sonic-preview` (Sonic 3.6) IS ABSENT ON A CONTRADICTION WE DO NOT GET TO RESOLVE.**
Bolna calls it *"Sonic 3.6 (Beta)"* whose *"output may change"* (`cartesia.md:58-66`);
Cartesia calls `sonic-3.6` stable with no announced retirement (same ADDENDUM 1
reading). **We send the id BOLNA accepts**, because Bolna is what parses it, so the
catalogue stays on `sonic-3.5` (snapshot `sonic-3.5-2026-05-04`, stable, no announced
retirement). The disagreement is recorded in `TTS_MODEL_LIFECYCLE`, not resolved, and
gate 52 is where it is revisited.

**TELUGU IS ON CARTESIA'S LIST; TELUGU-ENGLISH CODE-MIXING IS NOT VOUCHED FOR.** `te`
appears on the per-snapshot language list of `sonic-3.5-2026-05-04` (42 languages) and of
`sonic-3.6-2026-08-27` (44) — same reading. On MIXING, their multilingual guide says it in
their own words: *"Mixing languages inside a single generation works where it's common,
such as Hindi (Hinglish) and Tagalog (Taglish). Outside those cases the speech may sound
accented."* Telugu-English is not among the cases they name. **That is not "unsupported"
and it is not "supported"** — it is outside the two they vouch for, with an accent warning
attached by the vendor. No surface may promise Telugu-English mixing on this tier;
`_CARTESIA_NOTE` carries the caveat so it travels with every entry.

**A CARTESIA VOICE IS PUBLISHABLE — WHAT IS MISSING IS THE IDS, NOT THE WIRE SHAPE.** The
`provider_config` keys are absent from the pinned MIRROR (`api-reference/agent/v2/
create.md:640-644` enumerates only `[polly, elevenlabs, deepgram, styletts]`, already
narrower than what their own provider pages ship) — but they are declared in Bolna's OSS,
which was read: `CartesiaConfig(StandardVoiceConfig)` = `{voice, voice_id, model, language,
speed}` (VERIFIED-OSS, `bolna-ai/bolna`@`ae03977fa2a9ecec3171b45c6cac6d00236b957f`,
`bolna/models.py`; plan ADDENDUM 3 §3.1). `engine/bolna.py::_cartesia_synthesizer_config`
builds that block, works around three defects in that same repository, and refuses ONE
case by name: a Cartesia agent with no voice id — which is exactly what this empty
catalogue produces. ⚠ Whether the HOSTED platform runs that commit is UNKNOWN, so
OPERATIONS §2 gate 52 is narrowed rather than closed: it now asks whether the hosted
platform accepts these fields, not what the fields are.

WHETHER THIS CATALOGUE IS OFFERABLE AT ALL IS A SEPARATE QUESTION (D-93)
------------------------------------------------------------------------
Everything above assumes the engine lets us choose a voice. That is Bolna's answer, not
every engine's: an orchestrator whose TTS is its own product takes its voice id and its
own model, with no provider field to put `sarvam` in, and our `tts_voice` addresses
nothing on it. Against such an engine this catalogue is not a shortened list — it is a
list of voices the caller will never hear, and rendering it is a screen that lies.

So the catalogue is DATA, and `voice_selection_capability()` below is the one selector
that says whether it may be offered. It asks the engine's own `EngineCapabilities`
descriptor rather than a settings flag, for the reason `lead_retrieval_capability` gives:
a capability DERIVED from the thing that implements it cannot disagree with it, while two
independent reads of the same settings eventually do. The picker, the write endpoint and
the publish path all ask this one function.

`SpeechControl` is deliberately carried on the answer rather than reduced to a boolean.
"You may not choose a voice because this engine supplies its own" and "you may not choose
a voice because something is broken" have the same shape and opposite meanings, and only
the first is a sentence a client should be shown calmly.

Engine isolation (hard rule 2) note: these strings are engine-FACING config, but they
are not a vendor payload shape. This module reaches `apps.api.engine` only through the
factory and the capability selector — never an adapter — so the adapter still owns the
only knowledge of where the string is pasted into the vendor's JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

from calevate_shared.engine import SpeechControl, VoiceEngine
from calevate_shared.model_lifecycle import TtsProvider
from pydantic import BaseModel, ConfigDict

# The languages the PRODUCT sells today (`CreateOrgIn.language`), Telugu first — we are
# Telugu-first (BRD §1), so the ordering here is the ordering a picker should render.
# A subset of the vendor's own 11-code TTS enum (VERIFIED-VENDOR-SDK: sarvamai==0.1.31
# (PyPI wheel), `types/text_to_speech_language.py`, read 27 Aug 2026), not a claim about
# the other eight.
Language = Literal["te-IN", "hi-IN", "en-IN"]

# The TTS models this product runs on — one per provider. Not an exhaustive list of what
# either vendor sells; kept as a Literal (rather than a bare str) so a catalogue entry cannot
# name a model we do not offer, and so `calevate_shared.model_lifecycle.TTS_MODEL_LIFECYCLE`
# can be checked against exactly this set (`scripts/check_model_lifecycle`).
#
# `sonic-3.5` and not `sonic-3`: the module docstring carries the vendor's line and the
# REPORTED sunset, in that order of standing.
TtsModel = Literal["bulbul:v3", "sonic-3.5"]

#: Who synthesises a voice — and, by plan §2.3 invariant 7, the agent's VOICE TIER. ONE
#: definition, shared with the lifecycle registry so the two cannot spell a provider
#: differently. `voice_tier()` returns it; nothing stores it beside the voice.
VoiceProvider = TtsProvider

#: The tier vocabulary a consumer (the pipeline's `meta.tts_tier`, the lot debit, the
#: runway) reads. The SAME type as the provider on purpose: the tier IS the provider, and a
#: second Literal would be the place the two could be made to disagree.
VoiceTier = VoiceProvider

Gender = Literal["female", "male", "neutral"]

# THE VENDOR'S OWN SPEAKER ENUM, COPIED AND NOT CURATED.
#
# VERIFIED-VENDOR-SDK: sarvamai==0.1.31 (PyPI wheel), `types/text_to_speech_speaker.py`,
# read 27 Aug 2026 — `TextToSpeechSpeaker` is a `Literal` of exactly these 44 lowercase
# names, in this order. Order is preserved because it is the vendor's, and inventing a
# ranking (alphabetical, "best first") would be a recommendation this file is not entitled
# to make: which speaker sounds best in Telugu is an ear test (gate 3, BRD R-10).
#
# A `Literal` rather than a `frozenset[str]` for `TtsModel`'s reason: a persona entry that
# names a speaker the vendor does not ship should not type-check.
Speaker = Literal[
    "anushka",
    "abhilash",
    "manisha",
    "vidya",
    "arya",
    "karun",
    "hitesh",
    "aditya",
    "ritu",
    "priya",
    "neha",
    "rahul",
    "pooja",
    "rohan",
    "simran",
    "kavya",
    "amit",
    "dev",
    "ishita",
    "shreya",
    "ratan",
    "varun",
    "manan",
    "sumit",
    "roopa",
    "kabir",
    "aayan",
    "shubh",
    "ashutosh",
    "advait",
    "anand",
    "tanya",
    "tarun",
    "sunny",
    "mani",
    "gokul",
    "vijay",
    "shruti",
    "suhani",
    "mohit",
    "kavitha",
    "rehan",
    "soham",
    "rupali",
]

#: The 44, as data, so the catalogue is BUILT from the vendor's enum rather than typed a
#: second time beside it. `get_args` rather than a hand-copied tuple: two spellings of one
#: list is the drift this repo treats as a defect even when both are right today.
SPEAKERS: Final[tuple[Speaker, ...]] = get_args(Speaker)

#: THE PLACEHOLDER DEFAULT PERSONA — pending the Telugu ear test (gate 3), NOT a
#: measurement of ours and not to be quoted as one. It is `ashutosh` for the one
#: non-invented reason available: it is the speaker in the vendor's own worked example
#: (VERIFIED-VENDOR-REPO, `bolna-ai/skills@28b24aa`, `create-agent/SKILL.md`), so it is the
#: single speaker id for which we have seen an end-to-end Bolna request that names it.
DEFAULT_SPEAKER: Final[Speaker] = "ashutosh"

#: The model every SARVAM persona runs on, and the default voice's model. Named so
#: `voice_id_for` and the migration's backfill cannot disagree about which model the
#: default id carries. The default is Sarvam by decision (plan §0 Q9): Cartesia is chosen,
#: never inherited, because a default that costs the client more per minute must be a
#: choice they made.
DEFAULT_TTS_MODEL: Final[TtsModel] = "bulbul:v3"

#: The one Cartesia model this product offers — see `TtsModel` for why not `sonic-3`.
CARTESIA_TTS_MODEL: Final[TtsModel] = "sonic-3.5"


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
    re-read that a concurrent `set_agent_voice` could have moved underneath you).

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
    than a preference. Splitting on the last colon turns the legacy value `bulbul:v3` into
    model `bulbul` and speaker `v3` — two strings the vendor has never heard of, sent
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
    voice = _BY_ID.get(voice_id)
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
    # ⚠ IT IS ALSO A WIRE-ADJACENT VALUE, WHICH IS WORTH KNOWING BEFORE EDITING IT. The
    # vendor's example carries the speaker twice — `"voice": "Ashutosh", "voice_id":
    # "ashutosh"` — so the capitalised form is what their `voice` key holds. The ADAPTER
    # derives that from the speaker (hard rule 2: which key gets which casing is a vendor
    # payload fact and stays inside `apps/api/engine/`); this field is for humans.
    label: str
    #: Who synthesises it — and therefore the agent's voice tier (`voice_tier()`).
    provider: VoiceProvider
    # Which model serves this voice. Separate from `id` so that named speakers
    # do not each become their own model.
    tts_model: TtsModel
    # THE SPEAKER, which is the half that was missing and the whole of D-358's second
    # defect: the model string used to be sent in the vendor's speaker slot.
    #
    # `str` rather than `Speaker`, because the two providers name a voice differently: a
    # Sarvam speaker is one of the vendor's 44 enum names, a Cartesia voice is the id its
    # voices API returns. The enum guarantee is kept where it can be typed — `_entry`
    # takes a `Speaker` — and re-asserted at import below for every Sarvam entry.
    speaker: str
    # Telugu first. The three languages the product offers, a subset of the vendor's own
    # 11-code TTS enum — not a claim about the other eight.
    languages: tuple[Language, ...]
    # ALWAYS None, and it is a decision rather than a gap. The SDK's speaker type is a bare
    # name Literal carrying NO gender metadata, so there is nothing to state and a name is
    # not evidence. The field stays for the day a vendor enumeration carries one.
    gender: Gender | None = None
    # The picker's default persona. A PLACEHOLDER pending the Telugu ear test (gate 3,
    # BRD R-10) — see `DEFAULT_SPEAKER` — never a measurement.
    is_default: bool = False
    # False until the Bolna pilot confirms the string is selectable (OPERATIONS §2
    # gate 3). Shipped as data so the admin UI can label the choice honestly.
    verified: bool = False
    # One line an operator can read in a dropdown, with the cost consequence in it.
    note: str


#: The shared half of every Sarvam entry's `note`. One sentence, composed once: 44
#: hand-written notes would be 44 chances to drift. It carries NO price — it used to say
#: "₹30 per 10k characters", which was a rate card in a dropdown string (see the module
#: docstring); the tier is the cost fact, and it is the `provider` field.
_NOTE: Final = (
    "Sarvam Bulbul v3 — the Sarvam voice tier. Which speaker suits Telugu best is an ear "
    "test nobody has run yet (pilot gate 3), and the speaker list is Sarvam's own; Bolna's "
    "acceptance of it is confirmed by GET /me/voices."
)

#: The shared half of every Cartesia entry's `note`, for the same reason. The Telugu
#: sentence is not decoration: Cartesia documents Hinglish code-switching and says NOTHING
#: about Telugu-English, so a screen that let a client infer it from "Telugu is supported"
#: would be promising something no page states (module docstring, hard rule 11).
_CARTESIA_NOTE: Final = (
    "Cartesia Sonic 3.5 — the Cartesia voice tier, billed at the higher per-minute rate on "
    "every credit lot. Telugu is on Cartesia's language list for this model. Mixing Telugu "
    "and English inside one sentence is NOT one of the cases Cartesia vouches for (they "
    'name Hinglish and Taglish, and say speech outside those "may sound accented"), so '
    "do not promise it. Offered only once the Cartesia key is installed, its price attested "
    "and the platform-wide Cartesia agent cap not reached."
)


def _entry(speaker: Speaker) -> Voice:
    """One persona from one speaker id. Built rather than typed for `SPEAKERS`' reason:
    every field except the name is identical across the 44, so writing them out would be a
    45th place for the price sentence and the language tuple to drift."""
    return Voice(
        id=voice_id_for(DEFAULT_TTS_MODEL, speaker),
        # `.capitalize()`, matching the vendor's own `"voice": "Ashutosh"` /
        # `"voice_id": "ashutosh"` pair. A display rule inferred from one worked example,
        # not a vendor statement — it decides what a human reads in a dropdown, and the
        # adapter's `voice` key is derived independently in `engine/bolna.py`.
        label=speaker.capitalize(),
        provider="sarvam",
        tts_model=DEFAULT_TTS_MODEL,
        speaker=speaker,
        languages=("te-IN", "hi-IN", "en-IN"),
        gender=None,
        is_default=speaker == DEFAULT_SPEAKER,
        verified=False,
        note=_NOTE,
    )


@dataclass(frozen=True, slots=True)
class CartesiaVoiceRecord:
    """ONE ROW OF CARTESIA'S `GET /voices` RESPONSE, in the four facts the catalogue needs.

    **TYPED TO THE VENDOR'S ACTUAL LIST SHAPE, IN OUR VOCABULARY.** Their endpoint returns
    `{data: Voice[], has_more, next_page}` where a `Voice` carries
    `{id, name, tagline, description, gender, language, accents[], is_pro, status, access,
    visibility, created_at}` (VERIFIED-VENDOR-DOCS, `docs.cartesia.ai/api-reference/voices/
    list`, read 7 Sep 2026, relayed in `docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md`
    ADDENDUM 3 §3.4). This record is what that JSON is TRANSLATED INTO, so the vendor's own
    key names and enum spellings never appear in this module (hard rule 2 — the translation
    is the ops probe's or a script's business). Three of the translations are load-bearing:

    * **LANGUAGE COMES FROM `accents[].locale`, NOT FROM `language`.** The vendor marks the
      top-level `language` field DEPRECATED in its own schema, with "prefer accents[].locale"
      written beside it. A loader keyed on the deprecated field would go quietly wrong the
      day they remove it. `languages` here is the already-mapped subset of the three this
      product sells; a voice whose accents name none of them cannot enter the catalogue.
      ⚠ Telugu's ONLY documented accent id is `telangana` — worth knowing before anybody
      concludes from an empty result that Cartesia has no Telugu voices.
    * **`archived` IS FILTERED, NOT STORED.** `status` is `active | archived`; the list
      endpoint excludes archived rows by default (`include_archived=false`). The field is
      here so a catalogue built from a wider fetch still cannot offer one. ⚠ UNKNOWN whether
      an archived voice still resolves at generation time — and we store the id on the agent,
      so a voice archived after we adopted it is a live question, not a housekeeping one.
    * **GENDER IS OURS, TRANSLATED UPSTREAM.** Cartesia's enum is
      `masculine | feminine | gender_neutral`; `Gender` here is the product's own three. Null
      stays null for `_entry`'s reason — a name is not evidence of a voice.

    ⚠ **NO RECORD EXISTS YET AND NONE MAY BE INVENTED.** Voice IDS need an authenticated
    `GET /voices?language=te`, which is a one-command answer once the key is installed — see
    `CARTESIA_CATALOG_SOURCE`.
    """

    id: str
    name: str
    #: The product languages this voice serves, mapped from `accents[].locale`. Telugu first
    #: where present, for `_entry`'s reason: it is the order a picker renders.
    languages: tuple[Language, ...]
    gender: Gender | None = None
    #: `status == "archived"` on the vendor's row. An archived voice is never offered.
    archived: bool = False


#: THE CARTESIA VOICES, AS DATA — EMPTY TODAY, ON PURPOSE. Nobody here has read a Cartesia
#: voice id: the library is behind a login and no unauthenticated list exists, and an id
#: nobody read is an id somebody invented — which publishes an agent that 422s on a real
#: client's phone. ADDENDUM 3 §3.4 turned this from a research question into one command:
#: `GET /voices?language=te` with `Cartesia-Version: 2026-08-14`, once
#: `Settings.cartesia_api_key` is installed. Its rows land here as `CartesiaVoiceRecord`s and
#: everything below already builds from them.
CARTESIA_CATALOG_SOURCE: Final[tuple[CartesiaVoiceRecord, ...]] = ()


def _cartesia_entry(record: CartesiaVoiceRecord) -> Voice:
    """One catalogue entry from one vendor voice record. `verified=False` for `_entry`'s
    reason: a listed voice is not a voice Bolna's Cartesia provider has been seen to accept
    (OPERATIONS §2 gate 52 covers whether the hosted platform takes our block at all; a voice
    the engine rejects is one record removed)."""
    return Voice(
        id=voice_id_for(CARTESIA_TTS_MODEL, record.id),
        label=record.name,
        provider="cartesia",
        tts_model=CARTESIA_TTS_MODEL,
        speaker=record.id,
        languages=record.languages,
        gender=record.gender,
        is_default=False,
        verified=False,
        note=_CARTESIA_NOTE,
    )


def cartesia_catalogue(
    records: tuple[CartesiaVoiceRecord, ...] = CARTESIA_CATALOG_SOURCE,
) -> tuple[Voice, ...]:
    """The Cartesia half of `CATALOG`, from vendor records — THE one filter, in one place.

    An ARCHIVED voice is dropped here rather than at every reader: the vendor's list endpoint
    already omits them by default, so a record marked archived arrived through a wider fetch
    somebody made deliberately, and offering it would put a client on a voice the vendor has
    withdrawn from its own library.
    """
    return tuple(_cartesia_entry(record) for record in records if not record.archived)


def default_voice_provider() -> VoiceProvider:
    """The provider of the one default persona — asserted Sarvam at import (Q9)."""
    return next(voice.provider for voice in CATALOG if voice.is_default)


CATALOG: tuple[Voice, ...] = tuple(_entry(speaker) for speaker in SPEAKERS) + cartesia_catalogue()

_BY_ID: dict[str, Voice] = {voice.id: voice for voice in CATALOG}

# Cheap enough to assert at import rather than hope for. `tts_model` and `provider` are
# Literals, so "no model we do not offer" and "no third provider" are enforced by the type;
# the assertions guard what the type cannot: id uniqueness across providers, a single
# default persona for the picker (Sarvam, Q9), and — since `speaker` had to widen to `str`
# for Cartesia ids — that every Sarvam entry still names one of the vendor's 44. All three
# hold with ZERO Cartesia entries, which is the state this module ships in.
assert len(_BY_ID) == len(CATALOG), "duplicate voice id in CATALOG"
assert sum(1 for voice in CATALOG if voice.is_default) == 1, "exactly one default persona"
assert default_voice_provider() == "sarvam", "the default voice is Sarvam by decision (Q9)"
assert all(voice.speaker in SPEAKERS for voice in CATALOG if voice.provider == "sarvam"), (
    "a Sarvam entry names a speaker outside the vendor's enum"
)
assert all(
    voice.provider == "cartesia" for voice in CATALOG if voice.tts_model == CARTESIA_TTS_MODEL
), "a Cartesia model is served by an entry that does not name the Cartesia provider"

#: The id the migration backfills a bare `bulbul:v3` row to, and the one the picker
#: pre-selects. Named so the two cannot disagree.
DEFAULT_VOICE_ID: Final = voice_id_for(DEFAULT_TTS_MODEL, DEFAULT_SPEAKER)


def get_voice(voice_id: str) -> Voice | None:
    """The catalog entry for `voice_id`, or None if we do not offer it.

    Exact match, no normalisation: `agents.tts_voice` is pasted into a vendor request
    verbatim, so accepting `Bulbul:V3` here would store a string that differs from the
    one we tested, which is the entire failure this module exists to prevent.
    """
    return _BY_ID.get(voice_id)


def is_supported_voice(voice_id: str) -> bool:
    """Is this a voice we support? — the question the API must be able to answer
    BEFORE a string reaches an agent row and, from there, the engine."""
    return voice_id in _BY_ID


def voice_ids() -> tuple[str, ...]:
    """Every id we accept, in catalog order — for error remediation text and tests."""
    return tuple(_BY_ID)


def default_voice() -> Voice:
    """The default persona (Bulbul v3). The import-time assertion above guarantees one."""
    return next(voice for voice in CATALOG if voice.is_default)


def voice_tier(tts_voice: str | None) -> VoiceTier:
    """THE agent's voice tier: the provider of the voice on its row, and nothing else.

    Plan §2.3 invariant 7 and §3.3: the tier is DERIVED, never stored, so an agent cannot
    hold a Cartesia voice and a Sarvam tier. This is the one function that derives it —
    the pipeline's `meta.tts_tier`, the credit-lot debit and the runway all ask here.

    `sarvam` for an empty or unrecognised id, and that is a decision rather than a
    fallback: an agent with no voice speaks the engine's default Sarvam persona, and a
    legacy free-text row (`bulbul:v3`, the pre-split spelling) is a Sarvam row. Cartesia
    is chosen, never inherited (Q9) — the only way to be on the dearer tier is a catalogue
    id whose entry says `cartesia`.
    """
    voice = _BY_ID.get(tts_voice) if tts_voice else None
    return voice.provider if voice is not None else "sarvam"


# --- the capability seam (D-93) -------------------------------------------------
#
# Authored reason codes, never vendor prose: they name OUR state and are stable enough to
# be alert labels and UI branches.

#: The engine supplies its own voices, so ours are not a choice set on it. This is a
#: PRODUCT FACT, not a fault — nothing is broken and nothing needs fixing.
ENGINE_DICTATES_TTS_REASON: Final = "engine_dictates_tts"


@dataclass(frozen=True, slots=True)
class VoiceSelectionCapability:
    """Whether a voice may be chosen here, and what may be chosen, as ONE answer.

    `voices` is carried on the same object rather than fetched separately — the argument
    `PaymentCapability.creates_orders` and `RetrievalCapability.retriever` both make: two
    facts, one lookup, one object. A caller that read "selection is available" from here
    and the list from `CATALOG` could render a picker on an engine that dictates its
    voices, which is the precise failure this seam exists to prevent.

    `reason` is non-None exactly when `available` is False.
    """

    available: bool
    #: Who chooses the TTS leg on the engine actually selected. Carried so a surface can
    #: say WHY calmly ("this platform supplies its own voices") instead of rendering an
    #: error, and so the two unavailable-for-different-reasons cases stay distinguishable.
    control: SpeechControl
    reason: str | None = None
    voices: tuple[Voice, ...] = ()


def voice_selection_capability(engine: VoiceEngine | None = None) -> VoiceSelectionCapability:
    """THE selector. The catalogue endpoint, the write endpoint and the publish path all
    ask this; nothing decides for itself whether a voice is choosable.

    Derived from the engine's own descriptor rather than asserted by config, so "we offer
    a voice picker" and "the engine will accept a voice" cannot disagree. When they did,
    the disagreement was invisible: the picker saved a row, the publish sent it, the
    engine ignored it, and the only place the truth appeared was a caller's handset.
    """
    # Imported here rather than at module scope: this module is imported by
    # `agents/publishing.py` and the route layer, and pulling the engine factory (and
    # through it httpx) in at import time would put a vendor client on the import path of
    # every agents module. The seam depends on nothing; the callers depend on the seam.
    from apps.api.engine import engine_capabilities

    control = engine_capabilities(engine).speech_control("tts")
    if control != "ours":
        return VoiceSelectionCapability(
            available=False, control=control, reason=ENGINE_DICTATES_TTS_REASON
        )
    return VoiceSelectionCapability(available=True, control=control, voices=CATALOG)


__all__ = [
    "CARTESIA_CATALOG_SOURCE",
    "CARTESIA_TTS_MODEL",
    "CATALOG",
    "DEFAULT_SPEAKER",
    "DEFAULT_TTS_MODEL",
    "DEFAULT_VOICE_ID",
    "ENGINE_DICTATES_TTS_REASON",
    "SPEAKERS",
    "CartesiaVoiceRecord",
    "Gender",
    "Language",
    "Speaker",
    "TtsModel",
    "Voice",
    "VoiceProvider",
    "VoiceSelectionCapability",
    "VoiceTier",
    "cartesia_catalogue",
    "default_voice",
    "get_voice",
    "is_supported_voice",
    "speech_for_voice_id",
    "voice_id_for",
    "voice_id_of",
    "voice_ids",
    "voice_selection_capability",
    "voice_tier",
]
