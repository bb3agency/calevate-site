"""The Gnani voice catalogue (D-618): 24 named voices, in the three languages we sell.

WHY THIS IS A MODULE AND NOT A SYNC
------------------------------------
Every other voice in this product reaches the catalogue through `agents/voice_sync.py`,
because the engine's own voice-config API enumerates what our account may speak and D-585
was caused by compiling a list the engine did not accept. **Gnani has no such API and no
engine in front of it.** The founder's reading of `docs.gnani.ai` on 15 Sep 2026 found ONE
listing page (`/api/TTS/available-voices`, sitemap `lastmod` 2026-08-05) naming 42 voices
for `timbre-v2.5` **by name, with no id of any kind**, and no endpoint that returns them.
`docs.gnani.ai` and `api.vachana.ai` are EGRESS-BLOCKED from this container (measured
HTTP 000, 15 Sep 2026), so nothing here can ask.

So the names are DATA, and the evidence class is the strongest one available for a blocked
host: **VERIFIED-VENDOR-SDK**. `gnani-vachana` 0.7.9 — the vendor's own package, pinned in
`uv.lock` at sha256 `20146a9df14ad3e0942dad5de10d92b1a2a94ecac7b931b3cc2d8f2e8f2fd8e8` —
ships `TIMBRE_V25_VOICES` (`gnani/tts/client.py:45-103`), which was read in the installed
wheel and agrees name-for-name and language-for-language with the founder's reading of the
page. `tests/gnani_voices_test.py` pins this table against that wheel, so a vendor release
that adds, removes or re-languages a voice turns CI red here rather than turning a Telugu
call into an English one. That is exactly the `bulbul:v3` argument this catalogue already
accepts for the Sarvam model string (`voices.py`, "WHAT IS GROUNDED, AND WHERE").

**THE NAMES ARE TYPED OUT AND NOT IMPORTED, AND THAT IS HARD RULE 2.** `apps/api` may not
import a vendor SDK. The wheel is importable in `apps/voice-worker` and in this file's
test, which is where the comparison is made.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
------------------------------------------
* **It does not install these voices into `voices.catalogue()`.** That snapshot is what an
  agent's stored `tts_voice` resolves against and what the picker renders, and D-588's
  requirement is that *only the voices an operator has enabled are selectable by anyone*.
  A compiled list installed at import is by construction a list nobody enabled — the exact
  defect that deleted the old seed. These entries become catalogue rows the day an operator
  admits them, and `gnani_voice_entries()` is what such an admission is built from.
* **It does not put a price anywhere.** Gnani publish none (module `voices.py`'s
  `_GNANI_NOTE`, `VOICE_TIER_OF_PROVIDER["gnani"] is None`, `docs/PIPECAT-MIGRATION.md`
  §7). The ₹27/10 000-character figure that exists in the wild is a RESELLER's price for
  their own platform and is not Gnani's; it may not appear in this product at all.
* **It does not claim a voice can speak a second language.** The vendor groups each voice
  under one locale and says a mismatched `language` *"may reduce quality"*; whether a voice
  can speak OUTSIDE its group is NOT STATED, so `languages` below is a one-element tuple
  per voice rather than a guess in either direction.

ONE SENTENCE IS WRONG THE DAY A GNANI ROW REACHES THE PICKER, AND IT IS NAMED HERE
-----------------------------------------------------------------------------------
`agents/voice_offer.NO_ATTESTED_TTS_PRICE_REASON` is written about Cartesia by name ("what
the Cartesia voice tier costs"), and it is the sentence the offer seam would render for ANY
provider whose price is not billable — including this one. It is unreachable today, because
no Gnani row can enter `voices.catalogue()` at all (see the bullet above), so the wrong
sentence has nothing to be rendered beside. Whoever admits the first Gnani voice must make
that reason per-provider first; it was left alone here because that file is another lane's
and a drive-by edit to a client-facing refusal is how two sentences end up meaning one thing.

THE OTHER 18 VOICES ARE REAL AND ARE NOT HERE
----------------------------------------------
`timbre-v2.5` has 42 voices; Tamil, Kannada, Malayalam, Marathi, Bengali, Gujarati, Punjabi
and Hinglish account for the rest. This product sells three languages
(`agents/languages.Language`), and a catalogue is not the place to widen that — the same
scoping `voices.py` applies to Sarvam's 11-code TTS enum. Adding a language is a
`Language` change plus rows here, in that order.
"""

from __future__ import annotations

from typing import Final

from apps.api.agents.languages import Language
from apps.api.agents.voices import Voice, catalogue_note, voice_id_for

#: The one Gnani model this product runs. Same string as
#: `voice_worker.gnani_tts.GNANI_TTS_MODEL` and as the `TTS_MODEL_LIFECYCLE` row; the
#: worker's copy is separate because `apps/voice-worker` may not import `apps/api`
#: (D-592) — `tests/gnani_voices_test.py` pins the two together.
GNANI_TTS_MODEL: Final = "timbre-v2.5"

#: The provider name, in the one vocabulary `calevate_shared.model_lifecycle.TtsProvider`
#: defines.
GNANI_PROVIDER: Final = "gnani"

#: VOICE NAME -> the locale the vendor tunes it for. Insertion order is the vendor's own
#: grouping order within each language, and Telugu leads because the product does.
#:
#: Read from `gnani.tts.client.TIMBRE_V25_VOICES` (grouped there by the same comments) and
#: from the founder's reading of `docs.gnani.ai/api/TTS/available-voices`, 15 Sep 2026.
#:
#: ⚠ **`Deepak` IS IN BOTH `TIMBRE_V20_VOICES` AND THE HINDI GROUP OF `TIMBRE_V25_VOICES`,
#: AND `Kaveri` AND `Pranav` LIKEWISE.** They are the same NAMES on two models, not the
#: same catalogue entries: an id here is `timbre-v2.5:<name>`, so nothing collides, and a
#: `timbre-v2.0` voice is not offered at all (see `gnani_tts.GNANI_TTS_MODEL` for why that
#: model is refused rather than defaulted to).
GNANI_VOICE_LANGUAGES: Final[dict[str, Language]] = {
    # Telugu (5)
    "Suhana": "te-IN",
    "Lehara": "te-IN",
    "Lavanya": "te-IN",
    "Yukti": "te-IN",
    "Varuni": "te-IN",
    # Hindi (13)
    "Nalini": "hi-IN",
    "Bhavna": "hi-IN",
    "Yashvi": "hi-IN",
    "Urmila": "hi-IN",
    "Jwala": "hi-IN",
    "Chitra": "hi-IN",
    "Ambuja": "hi-IN",
    "Deepak": "hi-IN",
    "Roopesh": "hi-IN",
    "Vikrant": "hi-IN",
    "Hemraj": "hi-IN",
    "Jalaj": "hi-IN",
    "Omkar": "hi-IN",
    # Indian English (6)
    "Kaveri": "en-IN",
    "Trupti": "en-IN",
    "Devika": "en-IN",
    "Pranav": "en-IN",
    "Shlok": "en-IN",
    "Girish": "en-IN",
}


def gnani_voice_language(name: str) -> Language | None:
    """The locale this Gnani voice is tuned for, or `None` if we do not offer the name.

    `None` covers two real cases and deliberately does not distinguish them, because the
    caller's action is the same in both: a name that is not a Gnani voice at all, and one
    of the 18 that serve a language this product does not sell.
    """
    return GNANI_VOICE_LANGUAGES.get(name)


def gnani_voice_names(language: Language | None = None) -> tuple[str, ...]:
    """Every Gnani voice we offer, or just those tuned for one language, in vendor order."""
    return tuple(
        name
        for name, tuned_for in GNANI_VOICE_LANGUAGES.items()
        if language is None or tuned_for == language
    )


def gnani_voice_entries() -> tuple[Voice, ...]:
    """The 24 voices as catalogue entries — the rows an admission writes, not a snapshot.

    **`verified=False` ON EVERY ENTRY, AND IT IS THE ONLY HONEST VALUE.** `Voice.verified`
    means one narrow thing in this product: a LIVE listing on our own account returned this
    voice. Gnani expose no listing to return anything, this deployment holds no Gnani
    account that anybody here has authenticated against, and no Gnani request has ever been
    made from this product. The field's own comment anticipates exactly this — *"an entry
    that is ever built from anything other than a live listing must be able to say so"* —
    and this is the first entry in the tree that has to say it.

    The note comes from `voices.catalogue_note`, not from a string here, for the reason
    that function exists: one sentence per provider, composed once.
    """
    return tuple(
        Voice(
            id=voice_id_for(GNANI_TTS_MODEL, name),
            label=name,
            provider=GNANI_PROVIDER,
            tts_model=GNANI_TTS_MODEL,
            # The vendor references a voice BY NAME on the wire — `{"voice": "Nalini"}` —
            # so the speaker and the label are the same string here, and that is a fact
            # about Gnani rather than a shortcut. On Cartesia they differ (an id and a
            # name), which is why `Voice` carries both fields at all.
            speaker=name,
            languages=(language,),
            verified=False,
            note=catalogue_note(GNANI_PROVIDER),
        )
        for name, language in GNANI_VOICE_LANGUAGES.items()
    )


__all__ = [
    "GNANI_PROVIDER",
    "GNANI_TTS_MODEL",
    "GNANI_VOICE_LANGUAGES",
    "gnani_voice_entries",
    "gnani_voice_language",
    "gnani_voice_names",
]
