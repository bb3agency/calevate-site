"""The voice catalog: which TTS voices an agent may speak in, as DATA.

`agents.tts_voice` is a free-text column (`agents/models.py`, DATA-MODEL §2 lists it
among the "config strings"). Free text is fine for the DB — model choices are config,
not code (D-04/D-20/D-36) — but it is not fine for the UI or the API: an operator who
types `bulbul-v3` or `Anushka` gets a row that looks saved, publishes cleanly, and is
discovered to be wrong at CALL TIME, on a real client's phone. This module is the
allowlist that turns that runtime failure into a 422.

WHAT IS GROUNDED, AND WHERE
---------------------------
Everything the entries below assert about MODELS comes from the docs set:

- D-36 (docs/ROADMAP.md:159) locks the canonical M1 stack and states the tier lever in
  its own words: "**TTS: Sarvam Bulbul v3 default, v2 as the value tier** (₹30 vs ₹15
  per 10k chars)". That single sentence is where `tier` comes from — premium = v3,
  value = v2 — and it is why both rungs exist at all.
- D-35 (docs/ROADMAP.md:161) is the correction that makes the value rung real: Bulbul
  v2 is "NOT discontinued — it is live at ₹15/10,000 chars, half the v3 rate". D-20
  (docs/ROADMAP.md:135) had recorded v2 as discontinued; that was read off a reseller's
  model listing, not Sarvam's rate card (docs/RESEARCH-DISCIPLINE.md:72). Do not
  re-delete v2 from this catalog on the strength of the older doc.
- The rate card that both tiers price off is docs/TRD.md:436-437 (v3 ₹30/10k chars,
  v2 ₹15/10k chars) and the per-call-minute translation is docs/TRD.md:456-457.
- Bulbul V3's language reach — "11 Indian languages" — is docs/TRD.md:77 and D-20.
  The docs give the COUNT, never the LIST, so `languages` below carries only the three
  languages the product itself offers (`CreateOrgIn.language` in
  `apps/api/admin/routes.py`: te-IN, hi-IN, en-IN), Telugu first. That is a subset we
  can stand behind rather than an enumeration we would be inventing.
- The id strings are the ones already flowing through our own engine contract:
  `packages/shared/tests/engine_conformance/contract_test.py:46` uses
  `tts_voice="bulbul:v3"`, and `apps/api/engine/bolna.py:250` puts exactly this column
  into the vendor's `synthesizer.provider_config.voice`.

WHAT IS PROVISIONAL (read this before quoting the catalog at anyone)
--------------------------------------------------------------------
**Every entry here is PROVISIONAL until the Bolna pilot verifies it.** Specifically:

1. **The docs name no voices.** `grep -rn` across `docs/` for speaker names, `voice_id`
   or a Sarvam voice list returns nothing — the only `voice_id` mention is in a
   competitor teardown (docs/TRD.md:501, describing *Outpero's* data model). So this
   catalog deliberately offers a choice of MODEL (v3 vs v2), which the docs do support,
   and offers no named speakers, which they do not. No speaker id in this file is
   invented, because no speaker id is in this file.
2. **Whether `bulbul:v3` is the literal string Bolna accepts is UNVERIFIED.** TRD §5
   says Bolna publishes no OpenAPI spec and the adapter's models are hand-maintained
   from docs + pilot payloads. OPERATIONS.md:33 (pilot gate 3) carries the open item in
   as many words: "Confirm **Bulbul V3 (not v2) is selectable**".
3. **Which of v3/v2 actually sounds better in Telugu is an EAR TEST, not a spec fact**
   (docs/BRD.md:242 R-10, docs/TRD.md:478, the D-35 scorecard item at
   docs/evidence/bolna-pilot-scorecard.md:64). `is_default` below encodes D-36's
   written default (v3), not a measurement of ours.
4. **`gender` is `None` on every entry, on purpose.** The docs record no speaker
   genders, so there is nothing to state. The field exists because the UI will need it
   the moment the pilot enumerates real speakers; leaving it null is the honest value,
   and inventing "female" for a model id would be worse than an empty column.

When the pilot answers (1)-(3), the shape here already accommodates the result: an id
becomes `bulbul:v3:<speaker>` while `tts_model` stays `bulbul:v3`, several entries
share one `tts_model`, and `verified` flips to True. That is why `id` and `tts_model`
are separate fields even though they coincide in today's two-entry catalog.

Deliberately absent: **Cartesia**. TRD §10.3 sketches a "Bulbul v2 → Bulbul v3 →
Cartesia" ladder and D-35/D-36 keep Cartesia as a second TTS candidate — a hedge, not
an adoption. D-36 locks Sarvam, so listing Cartesia would advertise a vendor we have
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
from typing import Final, Literal

from calevate_shared.engine import SpeechControl, VoiceEngine
from pydantic import BaseModel, ConfigDict

# The languages the PRODUCT sells today (`CreateOrgIn.language`), Telugu first — we are
# Telugu-first (BRD §1), so the ordering here is the ordering a picker should render.
Language = Literal["te-IN", "hi-IN", "en-IN"]

# D-36's ladder, in D-36's words: v3 is the default, v2 is "the value tier".
VoiceTier = Literal["premium", "value"]

# Sarvam's two live Bulbul models (TRD §10.1 rate card). Not an exhaustive list of
# what Sarvam sells — an exhaustive list of what D-36 adopted.
TtsModel = Literal["bulbul:v3", "bulbul:v2"]

Gender = Literal["female", "male", "neutral"]


class Voice(BaseModel):
    """One selectable voice. Doubles as the API response model — the catalog IS the
    contract, so there is nothing to keep in sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Written VERBATIM into `agents.tts_voice`. Stable: it is stored on agent rows, so
    # renaming one is a data migration, not an edit to this file.
    id: str
    # What a human picks from. Carries the tier, because "which one is cheaper" is the
    # actual question a client asks (TRD §10.3).
    label: str
    provider: Literal["sarvam"]
    # Which Sarvam model serves this voice. Separate from `id` so that named speakers
    # can be added later without every entry becoming its own model.
    tts_model: TtsModel
    tier: VoiceTier
    # Telugu first. A subset of Bulbul V3's documented 11 Indian languages (TRD §5) —
    # the three the product offers, not a claim about the other eight.
    languages: tuple[Language, ...]
    # Always None today: the docs record no speaker genders and we will not invent one.
    gender: Gender | None = None
    # D-36's written default, not a measurement (the Telugu ear test is pilot gate 3).
    is_default: bool = False
    # False until the Bolna pilot confirms the string is selectable (OPERATIONS §2
    # gate 3). Shipped as data so the admin UI can label the choice honestly.
    verified: bool = False
    # One line an operator can read in a dropdown, with the cost consequence in it.
    note: str


CATALOG: tuple[Voice, ...] = (
    Voice(
        id="bulbul:v3",
        label="Bulbul v3 — premium",
        provider="sarvam",
        tts_model="bulbul:v3",
        tier="premium",
        languages=("te-IN", "hi-IN", "en-IN"),
        gender=None,
        is_default=True,
        verified=False,
        note=(
            "D-36 default. ₹30 per 10k characters (~₹1.08-1.62 per call-minute, "
            "TRD §10.1). Telugu quality versus v2 is a pilot ear test, not a spec fact."
        ),
    ),
    Voice(
        id="bulbul:v2",
        label="Bulbul v2 — value",
        provider="sarvam",
        tts_model="bulbul:v2",
        tier="value",
        languages=("te-IN", "hi-IN", "en-IN"),
        gender=None,
        is_default=False,
        verified=False,
        note=(
            "D-36's value tier; live at half the v3 rate (D-35 corrects D-20's "
            "'discontinued'). ₹15 per 10k characters (~₹0.54-0.81 per call-minute). "
            "With the Sarvam LLM this is the cheapest verified stack, ₹1.04-1.31/min."
        ),
    ),
)

_BY_ID: dict[str, Voice] = {voice.id: voice for voice in CATALOG}

# Two entries, two tiers — the ladder D-36 describes is either complete or this file
# has drifted from it. Cheap enough to assert at import rather than hope for.
assert len(_BY_ID) == len(CATALOG), "duplicate voice id in CATALOG"
assert {voice.tier for voice in CATALOG} == {"premium", "value"}, "D-36 needs both tiers"
assert sum(1 for voice in CATALOG if voice.is_default) == 1, "exactly one D-36 default"


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
    """D-36's default (Bulbul v3). The import-time assertion above guarantees one."""
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


def voice_selection_available() -> bool:
    """The boolean a screen wants — the SAME selector the route uses, so a screen that
    offers the picker and a route that refuses it cannot disagree."""
    return voice_selection_capability().available


__all__ = [
    "CATALOG",
    "ENGINE_DICTATES_TTS_REASON",
    "Gender",
    "Language",
    "TtsModel",
    "Voice",
    "VoiceSelectionCapability",
    "VoiceTier",
    "default_voice",
    "get_voice",
    "is_supported_voice",
    "voice_ids",
    "voice_selection_available",
    "voice_selection_capability",
]
