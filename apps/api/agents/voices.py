"""The voice catalog: which TTS voices an agent may speak in, as DATA.

`agents.tts_voice` is a free-text column (`agents/models.py`, DATA-MODEL §2 lists it
among the "config strings"). Free text is fine for the DB — model choices are config,
not code (D-04/D-20/D-36) — but it is not fine for the UI or the API: an operator who
types `bulbul-v3` or `Anushka` gets a row that looks saved, publishes cleanly, and is
discovered to be wrong at CALL TIME, on a real client's phone. This module is the
allowlist that turns that runtime failure into a 422.

SINGLE VOICE TIER (supersedes D-36/D-35/D-34's two-rung ladder)
---------------------------------------------------------------
The founder-approved single-tier voice decision collapses the old premium/value voice
ladder into ONE natural voice quality: **Sarvam Bulbul v3**, priced to the client at a
single ₹5.00/min (`self_serve_inr_per_min`) and costed at ₹30/10,000 chars
(`billing/rates.py::TTS_INR_PER_10K_CHARS`). The v2 "value" rung is withdrawn entirely —
there is no cheaper voice to fall back to and no per-voice rate difference to bill, so
`tier` is gone from this catalog and from the rate card together.

**"One quality" is not "one voice".** Clients still choose a PERSONA — a named speaker
with a gender, tone and language — from Bulbul v3's professional voices; the collapse is
of the QUALITY dimension (v3 vs v2), not of speaker choice. The `Voice` model keeps its
persona fields for that reason. **THE PERSONAS ARE NOW REAL** — see the next section.

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
  read by the founder 27 Aug 2026)). `TtsModel` stays a one-member Literal on that basis.
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

Deliberately absent: **Cartesia**. TRD §10.3 once sketched a "Bulbul v2 → Bulbul v3 →
Cartesia" ladder as a hedge, not an adoption; the single-tier decision keeps Sarvam
Bulbul v3 as the one voice engine, so listing Cartesia would advertise a vendor we have
no key for. It joins this file when a decision-log entry adds it, not before.

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
from pydantic import BaseModel, ConfigDict

# The languages the PRODUCT sells today (`CreateOrgIn.language`), Telugu first — we are
# Telugu-first (BRD §1), so the ordering here is the ordering a picker should render.
# A subset of the vendor's own 11-code TTS enum (VERIFIED-VENDOR-SDK: sarvamai==0.1.31
# (PyPI wheel), `types/text_to_speech_language.py`, read 27 Aug 2026), not a claim about
# the other eight.
Language = Literal["te-IN", "hi-IN", "en-IN"]

# The one voice model the single-tier decision adopts (TRD §10.1 rate card). Not an
# exhaustive list of what Sarvam sells — the one model this product runs on. Kept as a
# Literal (rather than a bare str) so a persona entry cannot name a model we do not offer.
TtsModel = Literal["bulbul:v3"]

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

#: The one model every persona runs on today. Named so `voice_id_for` and the migration's
#: backfill cannot disagree about which model the default id carries.
DEFAULT_TTS_MODEL: Final[TtsModel] = "bulbul:v3"


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
    # What a human picks from. A persona label (speaker), NOT a quality tier — there is one
    # quality now (Bulbul v3), so price is not a question this answers.
    #
    # ⚠ IT IS ALSO A WIRE-ADJACENT VALUE, WHICH IS WORTH KNOWING BEFORE EDITING IT. The
    # vendor's example carries the speaker twice — `"voice": "Ashutosh", "voice_id":
    # "ashutosh"` — so the capitalised form is what their `voice` key holds. The ADAPTER
    # derives that from the speaker (hard rule 2: which key gets which casing is a vendor
    # payload fact and stays inside `apps/api/engine/`); this field is for humans.
    label: str
    provider: Literal["sarvam"]
    # Which Sarvam model serves this voice. Separate from `id` so that named speakers
    # do not each become their own model.
    tts_model: TtsModel
    # THE SPEAKER, which is the half that was missing and the whole of D-358's second
    # defect: the model string used to be sent in the vendor's speaker slot.
    speaker: Speaker
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


#: The shared half of every entry's `note`. One sentence, composed once: 44 hand-written
#: notes would be 44 chances to state a different price for one rate card.
_NOTE: Final = (
    "Sarvam Bulbul v3 — the single voice quality, ₹30 per 10k characters. Which speaker "
    "suits Telugu best is an ear test nobody has run yet (pilot gate 3), and the speaker "
    "list is Sarvam's own; Bolna's acceptance of it is confirmed by GET /me/voices."
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


CATALOG: tuple[Voice, ...] = tuple(_entry(speaker) for speaker in SPEAKERS)

_BY_ID: dict[str, Voice] = {voice.id: voice for voice in CATALOG}

# One quality, and exactly one default. Cheap enough to assert at import rather than hope
# for. `tts_model` and `speaker` are Literals, so "every entry is Bulbul v3" and "no
# invented speaker" are enforced by the type; the assertions guard the two things the type
# cannot: id uniqueness across personas, and a single default persona for the picker.
assert len(_BY_ID) == len(CATALOG), "duplicate voice id in CATALOG"
assert sum(1 for voice in CATALOG if voice.is_default) == 1, "exactly one default persona"

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
    "CATALOG",
    "DEFAULT_SPEAKER",
    "DEFAULT_TTS_MODEL",
    "DEFAULT_VOICE_ID",
    "ENGINE_DICTATES_TTS_REASON",
    "SPEAKERS",
    "Gender",
    "Language",
    "Speaker",
    "TtsModel",
    "Voice",
    "VoiceSelectionCapability",
    "default_voice",
    "get_voice",
    "is_supported_voice",
    "speech_for_voice_id",
    "voice_id_for",
    "voice_id_of",
    "voice_ids",
    "voice_selection_capability",
]
