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
persona fields (`gender`, `languages`) for that reason. Today the docs still name no
speakers (see below), so the catalog offers Bulbul v3 without inventing speaker ids or
genders; real personas land here the moment the pilot enumerates `GET /me/voices`.

WHAT IS GROUNDED, AND WHERE
---------------------------
Everything the entry below asserts about the MODEL comes from the docs set:

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
   catalog offers Bulbul v3 and offers no named speakers, which the docs do not support.
   No speaker id in this file is invented, because no speaker id is in this file — the
   persona dimension is real but empty until the pilot reads `GET /me/voices`.
2. **`bulbul:v3` IS the literal string, and named speakers DO exist (D-358).** Bolna's
   own `create-agent/SKILL.md` posts `"provider": "sarvam"` with
   `"provider_config": {"model": "bulbul:v3", "voice": "Ashutosh", "voice_id":
   "ashutosh"}`, and `GET /me/voices` lists the speakers once a TTS provider is
   configured (VERIFIED-VENDOR-REPO, `bolna-ai/skills@28b24aa`). So point 1 above is now
   only half true: the model string is confirmed, and "no Sarvam voice list exists" was
   a statement about what we could reach, not about what the vendor has. **What this
   catalog offers is still the MODEL in the `voice` slot, which is the wrong slot** — the
   adapter sends it as `provider_config.voice` where the vendor wants
   `provider_config.model`. Fixing it means `ModelConfig` grows a `tts_model` and this
   catalog grows real speaker ids read from `GET /me/voices`, which needs the account:
   D-358, and OPERATIONS §2 gate 3 still owns "Confirm **Bulbul V3 is selectable**".
3. **Which Bulbul v3 speaker sounds best in Telugu is an EAR TEST, not a spec fact**
   (docs/BRD.md:242 R-10, docs/TRD.md:478). `is_default` below encodes the single-tier
   default (Bulbul v3), not a measurement of ours.
4. **`gender` is `None` on the entry, on purpose.** The docs record no speaker genders,
   so there is nothing to state. The persona fields exist because the UI will need them
   the moment the pilot enumerates real speakers; leaving `gender` null is the honest
   value, and inventing "female" for a model id would be worse than an empty column.

When the pilot answers (1)-(3), the shape here already accommodates the result: an id
becomes `bulbul:v3:<speaker>` while `tts_model` stays `bulbul:v3`, several persona
entries share one `tts_model`, and `verified` flips to True. That is why `id` and
`tts_model` are separate fields even though they coincide in today's one-entry catalog.

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
from typing import Final, Literal

from calevate_shared.engine import SpeechControl, VoiceEngine
from pydantic import BaseModel, ConfigDict

# The languages the PRODUCT sells today (`CreateOrgIn.language`), Telugu first — we are
# Telugu-first (BRD §1), so the ordering here is the ordering a picker should render.
Language = Literal["te-IN", "hi-IN", "en-IN"]

# The one voice model the single-tier decision adopts (TRD §10.1 rate card). Not an
# exhaustive list of what Sarvam sells — the one model this product runs on. Kept as a
# Literal (rather than a bare str) so a persona entry cannot name a model we do not offer.
TtsModel = Literal["bulbul:v3"]

Gender = Literal["female", "male", "neutral"]


class Voice(BaseModel):
    """One selectable voice. Doubles as the API response model — the catalog IS the
    contract, so there is nothing to keep in sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Written VERBATIM into `agents.tts_voice`. Stable: it is stored on agent rows, so
    # renaming one is a data migration, not an edit to this file.
    id: str
    # What a human picks from. A persona label (speaker/tone), NOT a quality tier —
    # there is one quality now (Bulbul v3), so price is not a question this answers.
    label: str
    provider: Literal["sarvam"]
    # Which Sarvam model serves this voice. Separate from `id` so that named speakers
    # can be added later without every persona entry becoming its own model.
    tts_model: TtsModel
    # Telugu first. A subset of Bulbul V3's documented 11 Indian languages (TRD §5) —
    # the three the product offers, not a claim about the other eight.
    languages: tuple[Language, ...]
    # Always None today: the docs record no speaker genders and we will not invent one.
    # A persona-selection field, populated once the pilot enumerates real speakers.
    gender: Gender | None = None
    # The single-tier default (Bulbul v3), not a measurement (the Telugu ear test is
    # pilot gate 3).
    is_default: bool = False
    # False until the Bolna pilot confirms the string is selectable (OPERATIONS §2
    # gate 3). Shipped as data so the admin UI can label the choice honestly.
    verified: bool = False
    # One line an operator can read in a dropdown, with the cost consequence in it.
    note: str


CATALOG: tuple[Voice, ...] = (
    Voice(
        id="bulbul:v3",
        label="Bulbul v3",
        provider="sarvam",
        tts_model="bulbul:v3",
        languages=("te-IN", "hi-IN", "en-IN"),
        gender=None,
        is_default=True,
        verified=False,
        note=(
            "The single voice quality (supersedes the old v3/v2 ladder). ₹30 per 10k "
            "characters. Named Bulbul v3 personas land here once the pilot reads "
            "GET /me/voices (D-358); which speaker sounds best in Telugu is an ear test."
        ),
    ),
)

_BY_ID: dict[str, Voice] = {voice.id: voice for voice in CATALOG}

# One quality, and exactly one default. Cheap enough to assert at import rather than hope
# for. `tts_model` is a single-member Literal, so "every entry is Bulbul v3" is enforced
# by the type; the assertions guard the two things the type cannot: id uniqueness (persona
# entries added later must not collide) and a single default persona for the picker.
assert len(_BY_ID) == len(CATALOG), "duplicate voice id in CATALOG"
assert sum(1 for voice in CATALOG if voice.is_default) == 1, "exactly one default persona"


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
    "ENGINE_DICTATES_TTS_REASON",
    "Gender",
    "Language",
    "TtsModel",
    "Voice",
    "VoiceSelectionCapability",
    "default_voice",
    "get_voice",
    "is_supported_voice",
    "voice_ids",
    "voice_selection_capability",
]
