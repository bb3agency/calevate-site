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

⚠ THE CATALOGUE IS NO LONGER COMPILED. IT IS READ FROM THE ENGINE (D-585, 11 Sep 2026)
--------------------------------------------------------------------------------------
This module used to BE the catalogue: 44 speaker names copied from Sarvam's own SDK, and
`CATALOG` was a frozen tuple built from them. **Both halves of that were wrong in a way
only a live call could show.**

1. **We do not publish to Sarvam; we publish through the ENGINE**, whose Sarvam provider
   offers a DIFFERENT SUBSET. A live publish on 11 Sep 2026 returned `400 POST /v2/agent` —
   *"Provided voice: Anushka is not available for the provider: sarvam"*. `anushka` is the
   FIRST name in the vendor SDK's enum. A catalogue compiled from the model vendor is a
   picker that saves a row, publishes, and fails on a client's phone line.
2. **A CLONED voice cannot be in a compiled `Literal` at all, by construction.** The
   founder clones a voice after this code ships; its id exists only on the engine account.
   No amount of care with a hand-written list reaches it.

So the voices in force now come from `agents/voice_sync.py`, which reads the engine's own
two-step voice-config API (`VoiceEngine.list_voices`), caches the rows in
`platform_voice_catalog`, and installs them here as a process snapshot
(`install_voice_catalogue`). **`catalogue()` — never a constant — is what a reader asks.**
`SEED_CATALOG` below is the documented fallback for the window before the first sync, and
it is built from the nine voices a live engine read actually returned, NOT from the 44.

`SPEAKERS` and the `Speaker` Literal survive as the MODEL VENDOR's enum, which is still the
right type for a seed entry (it cannot name a persona Sarvam does not ship) and still the
provenance of `DEFAULT_SPEAKER`. They are no longer a claim about what the engine accepts.

WHAT IS GROUNDED, AND WHERE
---------------------------
- **The 44 speaker ids are the MODEL VENDOR's own closed enum** — a fact about Sarvam's
  API, not about the engine's provider (see above). VERIFIED-VENDOR-SDK:
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
from typing import Final, Literal, cast, get_args

from calevate_shared.engine import SpeechControl, VoiceEngine
from calevate_shared.model_lifecycle import TTS_MODEL_LIFECYCLE, TtsProvider
from pydantic import BaseModel, ConfigDict

from apps.api.billing.rates import voice_tier_label

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

#: The tier vocabulary a consumer (the pipeline's `meta.voice_tier`, the lot debit, the
#: runway) reads. The SAME type as the provider on purpose: the tier IS the provider, and a
#: second Literal would be the place the two could be made to disagree.
#:
#: **IT IS `meta.voice_tier` AND NOT `meta.tts_tier`, AND THIS COMMENT NAMED THE WRONG KEY.**
#: `usage_events.meta.tts_tier` is the PLAN'S OVERAGE RUNG (`BASE_OVERAGE_RUNG`, the
#: `plans.overage_rate` / `overage_rate_second` pair), which is a different fact about the
#: same call; the money lane stamps the two separately and says why in as many words
#: (`apps/workers/pipeline.py`, beside `"tts_tier"`). No code here read it wrongly — the
#: comment was the only thing that would have misled the next reader into folding them.
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

#: The id the migration backfills a bare `bulbul:v3` row to, and the one the picker
#: pre-selects where the engine still offers it (`_with_one_default`). Named so the two
#: cannot disagree.
DEFAULT_VOICE_ID: Final = f"{DEFAULT_TTS_MODEL}:{DEFAULT_SPEAKER}"


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
    # ⚠ IT IS ALSO A WIRE VALUE, NOT ONLY A HUMAN ONE, AND THAT CHANGED ON 11 SEP 2026.
    # Bolna's synthesizer block REQUIRES a `voice` key beside `voice_id` (their validator:
    # "Voice > Voice: This field is required"), and `voice` is the platform's own NAME for
    # the voice. The adapter used to derive it as `speaker.capitalize()`, which is correct
    # for every Sarvam persona and structurally impossible for a CLONED voice — their own
    # example pairs `voice_id: "sXlZ9Juk5Ji8sZiFjRUV"` with `name: "my-custom-voice"`
    # (VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/api-reference/voice/
    # get_all.md:102-112`). So this field now TRAVELS: `in_call_speech` puts it on
    # `ModelConfig.tts_voice_label` and the adapter decides which key it lands in (hard
    # rule 2 intact — the KEY is still a vendor payload fact; the NAME never was).
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
#:
#: **THE TIER IS NAMED BY `billing/rates.voice_tier_label`, NOT SPELLED HERE.** This string
#: reaches a CLIENT — it rides `OfferedVoiceOut.note` on `GET /v1/agents/voices`, which is
#: `agents:read` in either realm — and it used to read "the Sarvam voice tier", which names
#: the vendor as the product tier the founder's 7 Sep 2026 decision says a client never
#: reads. Composed from the one definition rather than corrected in place, because a typed
#: name here would be the second copy that drifts the day the labels change.
_NOTE: Final = (
    f"Sarvam Bulbul v3 — the {voice_tier_label('sarvam')} voice tier. Which speaker suits "
    "Telugu best is an ear test nobody has run yet (pilot gate 3), and the speaker list is "
    "Sarvam's own; Bolna's acceptance of it is confirmed by GET /me/voices."
)

#: The shared half of every Cartesia entry's `note`, for the same reason and through the
#: same label. The Telugu sentence is not decoration: Cartesia documents Hinglish
#: code-switching and says NOTHING about Telugu-English, so a screen that let a client infer
#: it from "Telugu is supported" would be promising something no page states (module
#: docstring, hard rule 11).
#:
#: IT NO LONGER RESTATES THE THREE OFFERABILITY GROUNDS ("offered only once the Cartesia key
#: is installed, its price attested and the cap not reached"). That sentence named two of our
#: own settings to a client, and it was a SECOND, un-forked copy of an answer
#: `agents/voice_offer.unofferable_reason` already gives per voice, per audience and per
#: deployment — a catalogue note cannot know whether the key is installed, so its version was
#: also the one that could be wrong.
_CARTESIA_NOTE: Final = (
    f"Cartesia Sonic 3.5 — the {voice_tier_label('cartesia')} voice tier, billed at the "
    "higher per-minute rate on every credit lot. Telugu is on Cartesia's language list for "
    "this model. Mixing Telugu and English inside one sentence is NOT one of the cases "
    'Cartesia vouches for (they name Hinglish and Taglish, and say speech outside those "may '
    'sound accented"), so do not promise it.'
)


#: THE SEED SPEAKERS — NOT SARVAM'S 44, AND THE DIFFERENCE IS A LIVE 400 (D-585).
#:
#: `SPEAKERS` above is the MODEL VENDOR's enum. We do not publish to Sarvam; we publish
#: through the ENGINE, whose Sarvam provider offers a different subset — proved on
#: 11 Sep 2026 by a live publish that came back `400 POST /v2/agent`: *"Provided voice:
#: Anushka is not available for the provider: sarvam"*. `anushka` is the FIRST name in the
#: vendor enum. So seeding the catalogue from all 44 would ship a picker that offers at
#: least one voice known to fail on a real client's phone line.
#:
#: These nine are the ones a live `GET /api/v1/voice-config/tts/voices` against the
#: founder's own engine account returned for provider `sarvam` / model `bulbul:v3`, each
#: `source: platform`. EVIDENCE CLASS: **VENDOR-PUBLISHED (live API read by the founder,
#: 11 Sep 2026, relayed)** — `api.bolna.ai` is unreachable from this container, so it was
#: not read here.
#:
#: ⚠ **IT IS A PARTIAL SAMPLE AND MUST NEVER BE READ AS THE COMPLETE LIST.** That response
#: was truncated at about ten of N. This tuple is therefore a FLOOR — the voices we know
#: the engine accepts — and never a ceiling: the complete list is whatever
#: `agents/voice_sync.py` reads from the engine, which is why the seed exists only for the
#: window before the first sync (`catalogue()`).
SEED_SPEAKERS: Final[tuple[Speaker, ...]] = (
    "shubh",
    "priya",
    "suhani",
    "ashutosh",
    "ritu",
    "amit",
    "sumit",
    "pooja",
    "manan",
)


def catalogue_note(provider: VoiceProvider) -> str:
    """THE one line an operator or client reads beside a voice, per provider.

    Public because `agents/voice_sync.py` builds catalogue entries from the ENGINE's rows
    and needs the same sentence the seed entries carry — a second string composed there
    would be the copy that drifts the day the tier labels change, which is the whole reason
    `_NOTE` is composed from `voice_tier_label` rather than typed.
    """
    return _NOTE if provider == "sarvam" else _CARTESIA_NOTE


def _entry(speaker: Speaker) -> Voice:
    """One seed persona from one speaker id. Built rather than typed for `SPEAKERS`'
    reason: every field except the name is identical across them, so writing them out
    would be a further place for the language tuple and the note to drift."""
    return Voice(
        id=voice_id_for(DEFAULT_TTS_MODEL, speaker),
        # `.capitalize()`, matching the live read's own `shubh`/`Shubh` pairing and the
        # vendor's worked example (`"voice": "Ashutosh"` / `"voice_id": "ashutosh"`). A
        # display rule that holds for a Sarvam PERSONA and for nothing else — a cloned
        # voice's name has no derivable relationship to its id, which is exactly why the
        # synced catalogue carries the engine's own `name` instead of deriving one.
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

    ⚠ **SUPERSEDED AS THE ROUTE TO A CARTESIA CATALOGUE (D-585), AND KEPT AS A TYPE.** The
    engine's own voice-config API enumerates EVERY provider it supports, not only Sarvam —
    its documented example answers with ElevenLabs and Sarvam side by side and keys the
    voice fetch on a `model_id` string (VERIFIED-VENDOR-DOCS,
    `bolna-findings/mirror/pages/api-reference/voice/get_providers.md`, read 11 Sep 2026).
    So if the engine account carries Cartesia with `sonic-3.5`, `agents/voice_sync.py`
    fills the Cartesia half of the catalogue with ids somebody READ, through the same seam
    that fills the Sarvam half — which closes the gap this record was shaped to wait for
    without anybody typing a voice id they had not seen.

    The type survives because the gap is not closed until a sync has actually returned
    Cartesia rows, and because Cartesia's own API remains the fallback route if the engine
    does not enumerate that provider for our account. Its translation notes are unchanged
    and still govern any loader built over that API:

    * **LANGUAGE COMES FROM `accents[].locale`, NOT FROM `language`** — the vendor marks the
      top-level `language` field DEPRECATED in its own schema, "prefer accents[].locale".
      ⚠ Telugu's ONLY documented accent id is `telangana`.
    * **`archived` IS FILTERED, NOT STORED** (`status` is `active | archived`).
    * **GENDER IS OURS, TRANSLATED UPSTREAM** — their enum is
      `masculine | feminine | gender_neutral`.

    (VERIFIED-VENDOR-DOCS, `docs.cartesia.ai/api-reference/voices/list`, read 7 Sep 2026,
    relayed in `docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md` ADDENDUM 3 §3.4; that host is
    egress-blocked from this container and was not read here.)
    """

    id: str
    name: str
    #: The product languages this voice serves, mapped from `accents[].locale`.
    languages: tuple[Language, ...]
    gender: Gender | None = None
    #: `status == "archived"` on the vendor's row. An archived voice is never offered.
    archived: bool = False


#: THE CARTESIA SEED — EMPTY, AND NOW EMPTY FOR A BETTER REASON THAN BEFORE. Nobody here
#: has read a Cartesia voice id, and an id nobody read is an id somebody invented. What
#: changed on 11 Sep 2026 is that it no longer has to be typed at all: the engine's
#: voice-config API enumerates its own providers, so a Cartesia voice reaches the catalogue
#: through `agents/voice_sync.py` the moment the engine account offers one. This stays ()
#: because a SEED is what answers before any sync has run, and before any sync has run we
#: know no Cartesia id.
CARTESIA_CATALOG_SOURCE: Final[tuple[CartesiaVoiceRecord, ...]] = ()


def _cartesia_entry(record: CartesiaVoiceRecord) -> Voice:
    """One catalogue entry from one vendor voice record. `verified=False` for `_entry`'s
    reason: a listed voice is not a voice the engine's Cartesia provider has been seen to
    accept (OPERATIONS §2 gate 52)."""
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
    """The Cartesia half of the SEED, from vendor records — THE one filter, in one place.

    An ARCHIVED voice is dropped here rather than at every reader: the vendor's list
    endpoint already omits them by default, so a record marked archived arrived through a
    wider fetch somebody made deliberately, and offering it would put a client on a voice
    the vendor has withdrawn from its own library.
    """
    return tuple(_cartesia_entry(record) for record in records if not record.archived)


#: WHAT THE PRODUCT OFFERS BEFORE ANY SYNC HAS RUN — the documented fallback, and the
#: answer to "what happens when the cache is empty" (D-585).
#:
#: **THE PRODUCT MUST NOT BECOME UNPUBLISHABLE BECAUSE A BACKGROUND JOB HAS NEVER RUN.**
#: The alternative considered was refusing with a named error until a sync lands; it was
#: rejected because the first thing a fresh deployment does is create an agent, the voice
#: picker is on that screen, and a product that cannot make a voice agent until an operator
#: finds an ops route is a half-wired seam by another name.
#:
#: What makes the fallback safe is WHAT IS IN IT: only voices a live engine read returned
#: (`SEED_SPEAKERS`), never the model vendor's wider enum. So the empty-cache state offers
#: a SHORT list of voices the engine is known to accept rather than a long list containing
#: at least one it rejects. `catalogue_source()` reports which of the two is in force, and
#: every surface that renders the picker says so (`GET /v1/agents/voices`).
SEED_CATALOG: Final[tuple[Voice, ...]] = (
    tuple(_entry(speaker) for speaker in SEED_SPEAKERS) + cartesia_catalogue()
)

#: Where the voices currently in force came from. `"engine"` means a sync read them off the
#: engine account; `"seed"` means no sync has ever succeeded on this process and
#: `SEED_CATALOG` is answering. Carried on the API response so an operator reading a short
#: picker is told which of those two they are looking at, instead of guessing.
CatalogueSource = Literal["seed", "engine"]


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


_SEED_SNAPSHOT: Final = _snapshot_of(SEED_CATALOG, "seed")

#: THE CATALOGUE IN FORCE. Rebound by `install_voice_catalogue`; never mutated in place.
_snapshot: _Snapshot = _SEED_SNAPSHOT


def install_voice_catalogue(voices: tuple[Voice, ...] | None) -> None:
    """Install the synced catalogue for this process; `None` restores the seed.

    THE SAME SHAPE AS EVERY OTHER PLATFORM-SCOPED FACT THIS TREE SERVES OFF A SNAPSHOT —
    `voice_offer.install_tts_price_reader`, `billing/rates.install_llm_price_attestations`,
    `ops/pricing_snapshot.install_pricing_readers`. It is deliberately NOT an async read
    per request: `get_voice`, `speech_for_voice_id` and `voice_tier` are called from the
    publish path, the splitter and the money lane, all of which are synchronous by design
    and some of which hold no session. Turning them async to fetch platform-scoped rows
    that change when an operator presses a button would be a database round trip on every
    agent publish for a value that moves monthly.

    `agents/voice_catalogue.py::load_voice_catalogue` is the one caller in production (at
    API and worker startup, and after every sync); tests drive it directly and restore the
    seed with `None`.

    **AN EMPTY TUPLE IS NOT A CATALOGUE AND IS REFUSED.** Installing `()` would take the
    voice picker to zero entries and make every agent's configured voice read as "no longer
    offered" — which is what a sync that read nothing successfully looks like. The caller
    that has nothing to install must leave the previous answer standing.
    """
    global _snapshot
    if voices is None:
        _snapshot = _SEED_SNAPSHOT
        return
    if not voices:
        raise ValueError(
            "refusing to install an empty voice catalogue: a picker with no voices is "
            "indistinguishable from a platform with no voices, and every configured "
            "agent would read as speaking a withdrawn one. Leave the previous catalogue "
            "standing and alert instead."
        )
    _snapshot = _snapshot_of(_with_one_default(voices), "engine")


def _with_one_default(voices: tuple[Voice, ...]) -> tuple[Voice, ...]:
    """Exactly one `is_default` voice, chosen the same way every time.

    The seed's default is an import-time assertion; a SYNCED catalogue cannot have one,
    because whether the engine account still offers `DEFAULT_SPEAKER` is the engine's
    business and not ours. So the flag is (re)stamped here: the configured default id if
    the engine offers it, else the first Sarvam voice it does offer, else the first voice.

    Never zero and never two: the picker pre-selects the default and
    `default_voice()` is called by the agent-create path, so a catalogue with none would
    500 a screen and one with two would pre-select whichever happened to be first.
    """
    preferred = next(
        (voice for voice in voices if voice.id == DEFAULT_VOICE_ID),
        # Cartesia is chosen, never inherited (plan §0 Q9): a default that costs the
        # client more per minute must be a choice they made, so a deployment whose engine
        # no longer offers our configured persona falls to another SARVAM voice first.
        next((voice for voice in voices if voice.provider == "sarvam"), voices[0]),
    )
    return tuple(
        voice.model_copy(update={"is_default": voice.id == preferred.id}) for voice in voices
    )


def catalogue() -> tuple[Voice, ...]:
    """THE voices in force — synced from the engine, or the seed until one lands.

    Every reader goes through here rather than through a module constant, because the
    catalogue is now DATA THAT MOVES: an operator clones a voice and refreshes, and the
    picker has to show it without a deploy.
    """
    return _snapshot.voices


def catalogue_source() -> CatalogueSource:
    """`"seed"` or `"engine"` — see `SEED_CATALOG` for why a caller must be able to say."""
    return _snapshot.source


def default_voice_provider() -> VoiceProvider:
    """The provider of the one default persona. Sarvam wherever the engine offers one
    (`_with_one_default`), and asserted Sarvam on the seed at import (Q9)."""
    return default_voice().provider


# Cheap enough to assert at import rather than hope for, and now asserted over the SEED
# alone — the synced catalogue is checked where it is built (`_with_one_default`,
# `agents/voice_sync.py`), because a vendor's own list is not something an assertion in our
# source gets to veto at import time.
assert len(_SEED_SNAPSHOT.by_id) == len(SEED_CATALOG), "duplicate voice id in SEED_CATALOG"
assert sum(1 for voice in SEED_CATALOG if voice.is_default) == 1, "exactly one default persona"
assert all(voice.speaker in SPEAKERS for voice in SEED_CATALOG if voice.provider == "sarvam"), (
    "a Sarvam seed entry names a speaker outside the vendor's enum"
)
assert all(
    voice.provider == "cartesia" for voice in SEED_CATALOG if voice.tts_model == CARTESIA_TTS_MODEL
), "a Cartesia model is served by a seed entry that does not name the Cartesia provider"


def get_voice(voice_id: str) -> Voice | None:
    """The catalog entry for `voice_id`, or None if we do not offer it.

    Exact match, no normalisation: `agents.tts_voice` is pasted into a vendor request
    verbatim, so accepting `Bulbul:V3` here would store a string that differs from the
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


def default_voice() -> Voice:
    """The default persona. Exactly one exists in either catalogue: the seed asserts it at
    import, and `_with_one_default` re-stamps it on every synced catalogue."""
    return next(voice for voice in catalogue() if voice.is_default)


# THE Q9 MONEY INVARIANT, AND IT LOST ITS GUARD IN THE MOVE TO A DERIVED CATALOGUE.
# `default_voice_provider`'s docstring still said "asserted Sarvam on the seed at import
# (Q9)" while the assertion that did the asserting had been dropped — which also left the
# function referenced by nothing, so `scripts/check_half_wired` caught the orphan without
# being able to see the invariant underneath it.
#
# It is worth keeping rather than deleting the function, because it is a claim about MONEY:
# Cartesia is the dearer tier per minute, and plan §0 Q9 says it is CHOSEN, never inherited
# — a client must not arrive on it because a catalogue happened to order itself that way.
# `_with_one_default` re-stamps the synced catalogue with the same preference, so this
# assertion pins the SEED (the floor every deployment starts from) and that function pins
# the rest.
assert default_voice_provider() == "sarvam", "the default seed voice is Sarvam by decision (Q9)"


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


def tts_model_of_voice_id(voice_id: str | None) -> TtsModel | None:
    """The MODEL half of a stored voice id, read from the id ITSELF — no catalogue.

    `voice_id_for` composes `<tts_model>:<speaker>`, and every model we offer is a member
    of `TtsModel`, so the model is recoverable from the string by asking which member it is
    prefixed with. Deliberately NOT `rsplit(":", 1)`: `bulbul:v3:ashutosh` would split to
    the model `bulbul:v3` correctly and the legacy free-text row `bulbul:v3` would split to
    the model `bulbul`, which is a string no vendor has ever heard of. Matching against
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


def voice_tier(tts_voice: str | None) -> VoiceTier:
    """THE agent's voice tier: the provider of the voice on its row, and nothing else.

    Plan §2.3 invariant 7 and §3.3: the tier is DERIVED, never stored, so an agent cannot
    hold a Cartesia voice and a Sarvam tier. This is the one function that derives it —
    the pipeline's `meta.voice_tier`, the credit-lot debit and the runway all ask here.
    NOT `meta.tts_tier`, which this line used to name: that key carries the plan's OVERAGE
    RUNG and is stamped separately on purpose (see `VoiceTier` above).

    ⚠ **IT IS DERIVED FROM THE ID, NOT FROM CATALOGUE MEMBERSHIP, AND THAT CHANGED ON
    11 SEP 2026 (D-585) — THE CHANGE REACHES MONEY.** This used to look the id up in
    `CATALOG` and return `"sarvam"` when it was absent. That was safe only while the
    catalogue was a frozen compiled constant: every id that could exist was in it. The
    catalogue is now CACHED FROM THE ENGINE (`agents/voice_sync.py`), so "absent" became a
    state a live Cartesia agent can be in — a cache not yet synced, a sync that pruned a
    voice the vendor withdrew, a clone renamed. In every one of those, a Cartesia agent
    would have billed at the SARVAM rate, silently, on an append-only ledger (hard rule 7).

    So the tier comes from the id's own model prefix and the one model→provider registry.
    `bulbul:v3:…` is Sarvam and `sonic-3.5:…` is Cartesia whether or not a row for that
    voice exists anywhere, which is the property the money lane needs.

    `sarvam` for an empty id or one naming none of our models, and that is a decision
    rather than a fallback: an agent with no voice speaks the engine's default Sarvam
    persona, and a legacy free-text row (`bulbul:v3`, the pre-split spelling) is a Sarvam
    row. Cartesia is chosen, never inherited (Q9) — the only way onto the dearer tier is an
    id that names the Cartesia model.
    """
    model = tts_model_of_voice_id(tts_voice)
    provider = provider_of_tts_model(model) if model is not None else None
    return provider if provider is not None else "sarvam"


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
    and the list from `catalogue()` could render a picker on an engine that dictates its
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
    return VoiceSelectionCapability(available=True, control=control, voices=catalogue())


__all__ = [
    "CARTESIA_CATALOG_SOURCE",
    "CARTESIA_TTS_MODEL",
    "DEFAULT_SPEAKER",
    "DEFAULT_TTS_MODEL",
    "DEFAULT_VOICE_ID",
    "ENGINE_DICTATES_TTS_REASON",
    "SEED_CATALOG",
    "SEED_SPEAKERS",
    "SPEAKERS",
    "CartesiaVoiceRecord",
    "CatalogueSource",
    "Gender",
    "Language",
    "Speaker",
    "TtsModel",
    "Voice",
    "VoiceProvider",
    "VoiceSelectionCapability",
    "VoiceTier",
    "cartesia_catalogue",
    "catalogue",
    "catalogue_note",
    "catalogue_source",
    "default_voice",
    "default_voice_provider",
    "get_voice",
    "install_voice_catalogue",
    "is_supported_voice",
    "provider_of_tts_model",
    "speech_for_voice_id",
    "tts_model_of_voice_id",
    "voice_id_for",
    "voice_id_of",
    "voice_ids",
    "voice_selection_capability",
    "voice_tier",
]
