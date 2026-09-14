"""WHICH LANGUAGES AN AGENT CAN ACTUALLY HOLD A CONVERSATION IN — and which it can only
hear.

WHY THIS FILE EXISTS. Nothing in this repository declared an agent's languages. What
existed instead was the same three strings spelled independently in TWELVE places —
`agents/voices.py::Language`, `agents/voice_sync._PRODUCT_LANGUAGES`,
`copilot/agent_actions._LANGUAGES` and a second `_LANGUAGE_LABELS`,
`engine/bolna._VOICE_LANGUAGES`, `admin/routes.CreateOrgIn.language`,
`tenancy/signup_routes.Language`, and three tables of labels in the frontend
(`admin/new/languages.ts`, `lib/api/signup.ts`, `lib/agentState.ts`) plus a union
hand-written twice in `admin/ops/voices/page.tsx` — each its own `te-IN`/`hi-IN`/`en-IN`
tuple with its own labels, none derived from another. That is the "one way per problem"
defect on a value the picker, the publish path, the DLT script review and the disclosure
copy all read, and it had already drifted: `en-IN` was "Indian English" on the copilot's
confirmation card and "English (India)" on every screen that card refers to.

**EVERY ONE OF THOSE NOW DERIVES FROM HERE**, with exactly two exceptions that cannot:
`agents/languages.Language` (Pydantic needs a static `Literal` to emit the OpenAPI enum
the whole typed frontend is built on) and migration `c7a41e8b52d9` (a migration is a
snapshot of the schema on the day it ran). Both are held equal to `offered_language_
tags()` by `tests/product_languages_test.py`, which also walks every source file in
`apps/` and `packages/shared/src` and fails if any of them starts spelling the set again.
It was also a list that could not GROW: a product sold as Telugu-first to Indian SMBs has
to be able to answer a Marathi caller, and adding Marathi used to mean finding all twelve
copies. It is now one line here plus the things a language genuinely needs — see
`OFFERED_LANGUAGE_IDS`.

**THE DISTINCTION THIS FILE EXISTS TO PROTECT: STT HEARS MORE THAN TTS CAN SPEAK.**
Sarvam's own SDK declares 23 languages its speech-to-text accepts and 11 its text-to-
speech can produce. An agent holds a conversation in the INTERSECTION and nowhere else.
Offer a caller one of the other twelve and you have built an agent that understands the
question perfectly and then cannot say anything back — a failure that does not appear in
any test, any staging click-through or any screenshot, only on a live call with a real
customer on the line. So "understood" and "answerable" are TWO FIELDS here and are never
collapsed into one boolean, and nothing wider than `conversational_languages()` may ever
reach a picker.

**CAPABLE IS NOT OFFERED, AND THE TWO ARE SEPARATE DECLARATIONS ON PURPOSE.** Eleven
languages are conversational; the product SELLS three (`OFFERED_LANGUAGE_IDS` below, and
`offered_languages()` is what every picker, column, enum and label in `apps/` derives
from). Widening the capability set is a VENDOR fact and lands here when somebody reads a
vendor's list; widening the offer is a COMMERCIAL decision — a language needs disclosure
and recording sentences written in it (`compliance/disclosure.py`), a voice the engine
account actually holds, and somebody willing to answer a caller's second question in it —
and it belongs to the founder, not to whoever is editing this file. Collapsing the two
would make reading a vendor's SDK put eight languages on a client's screen.

The containment runs one way and is asserted, not assumed: every offered language is
conversational (`tests/product_languages_test.py`), so the dead-air failure above cannot
be reached by widening the offer.

WHERE THE VENDOR FACTS COME FROM
--------------------------------------------------------------------------------------
EVIDENCE CLASS: **VERIFIED-VENDOR-SDK** — the vendor's own installed package, read in
this tree on **14 Sep 2026**:

* STT — `sarvamai==0.1.28`, `.venv/lib/python3.12/site-packages/sarvamai/types/
  speech_to_text_language.py:5-31`: a `Literal` of `"unknown"` plus 23 language codes.
  `"unknown"` is Sarvam's auto-detect placeholder, not a language, and is excluded.
* TTS — same wheel, `types/text_to_speech_language.py:5-7`: a `Literal` of exactly 11.

CORROBORATED INDEPENDENTLY, which is why the STT number is 23 and not 17. `pipecat-ai==
1.10.0` carries FOUR Sarvam language tables and they do not agree with each other:
`services/sarvam/stt.py:801-825` (`SUPPORTED_LANGUAGES`) lists the same 23 as the vendor
SDK; `stt.py:738-757` (`_map_language_code_to_enum`) carries only 17 of them;
`stt.py:76-88` carries 12; `stt.py:864-882` (realtime) carries 15. Two independent
sources — the vendor's own API definition and the framework's validation set — agree on
the SET of 23, so that is what is declared here. The framework's shorter tables are a
FRAMEWORK limitation, recorded at `STT_LANGUAGES_PIPECAT_CANNOT_LABEL` below, not a
vendor one: a language outside them is still transcribed, it just arrives with
`TranscriptionFrame.language` unset. None of those twelve is conversational anyway, so
the gap costs a label and never a reply.

**THE ODIA TRAP, CONFIRMED.** Sarvam spells Odia **`od-IN`**, which is NOT its BCP-47
code — ISO 639-1 for Odia is `or`, and `or-IN` is what every standards-driven layer will
produce. Both of the vendor's own literals say `od-IN` (`speech_to_text_language.py:13`,
`text_to_speech_language.py:6`), so the vendor is at least self-consistent. **Pipecat is
not.** It emits `od-IN` from `stt.py:86` and `tts.py:234-235`, accepts `od-IN` at
`stt.py:748`, and emits `or-IN` from `stt.py:877` while validating against a
`SUPPORTED_LANGUAGES` that contains `or-IN` and NOT `od-IN` (`stt.py:809`). So on the
realtime STT path the two spellings are exactly inverted: passing the vendor's own code
is rejected by the framework, and the code the framework sends is absent from the
vendor's literal. Whoever wires Odia meets this on the first call and has no reason to
suspect a one-letter difference.

The response is that **`bcp47` and the vendor wire code are separate fields** and nothing
derives one from the other. `KNOWN_WIRE_CODE_ANOMALIES` is the ledger of every place they
differ, and `tests/languages_test.py` asserts the derived set of differences EQUALS it —
so a second vendor with its own spelling fails the suite rather than a call. The rejected
alternative was to normalise `od-IN` to `or-IN` on the way in and out, which is worse in
the way that matters: it makes the discrepancy invisible, so the next person to read this
table has no way to learn that it is there.

WHAT IS UNVERIFIED, AND WHY THAT IS A VALUE RATHER THAN AN OMISSION
--------------------------------------------------------------------------------------
Support is THREE-VALUED — `supported` / `unsupported` / `unverified` — because
"this vendor cannot speak Maithili" and "nobody has read this vendor's language list" are
different facts with the same shape, and only the first is safe to render as a ✗ on a
client's screen.

* **CARTESIA (TTS, D-547's premium tier): UNVERIFIED here.** Cartesia's own SDK is not
  installed in this tree, and its docs host was not read this session. `pipecat-ai`
  carries a 44-entry Cartesia map (`services/cartesia/tts.py:91-134`) — but that is
  PIPECAT's claim about Cartesia, one evidence class down from the vendor's own
  definition, and the whole point of the class system is that we do not launder the
  second into the first. `agents/voices.py` separately records a founder reading of
  Cartesia's per-snapshot list; that is a repo-internal claim about a page nobody here
  opened (hard rule 11), so it is not restated as verification either.
* **GNANI (STT/TTS): UNVERIFIED.** No Gnani SDK, no docs, no mirror in this tree. Nothing
  at all is known about its language coverage, and Sarvam's list must not be assumed to
  apply to it.

Because `unverified` never counts as support, an unread vendor can only ever SHRINK what
we offer, never silently widen it. Adding Cartesia is then a two-line change and no
rewrite: move its pair into `VERIFIED_VENDOR_LEGS` and add its codes to the rows it
covers. Rows for languages it does not cover are not touched.

THE DISPLAY FIELDS ARE A WEAKER CLASS THAN THE WIRE FIELDS, DELIBERATELY
--------------------------------------------------------------------------------------
`endonym`, `english_name` and `script` are REFERENCE knowledge — ISO 15924 script codes
and the Eighth Schedule's own names. **No primary source was read for them this session**
and they are not labelled as though one had been. That is tolerable only because of how
they are used: they are display strings, they reach a screen and never a wire, and the
one field that DOES reach a wire (`wire_code`) comes from the vendor's own literal. A
wrong endonym is a typo somebody reports; a wrong wire code is a dropped call. Where a
language is genuinely written in more than one script in India the row carries the
official one and says so in a comment rather than picking silently.

`direction` is on the SCRIPT rather than the language because that is where the property
lives, and it is here at all because three of the comprehension-only languages (Urdu,
Kashmiri, Sindhi) are right-to-left: a transcript panel or a disclosure line rendered
without it is not merely ugly, it is unreadable.

HARD RULE 2. This module imports nothing but the standard library. The vendor tables
above were READ as evidence and transcribed; they are not imported, and `calevate_shared`
must never import `pipecat`, `sarvamai` or any other vendor SDK — those live only in
`apps/api/engine/`, its voice-runtime twin, and `apps/voice-worker/`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "KNOWN_WIRE_CODE_ANOMALIES",
    "LANGUAGES",
    "OFFERED_LANGUAGE_IDS",
    "STT_LANGUAGES_PIPECAT_CANNOT_LABEL",
    "UNVERIFIED_VENDOR_LEGS",
    "VERIFIED_VENDOR_LEGS",
    "Language",
    "LanguageId",
    "Script",
    "SpeechLeg",
    "SpeechVendor",
    "Support",
    "TextDirection",
    "comprehension_only_languages",
    "conversational_languages",
    "find_language",
    "get_language",
    "offered_language_tags",
    "offered_languages",
]

#: Our own stable identifier for a language. It is NOT a BCP-47 code and NOT a vendor
#: code, which is the point: the two of those already disagree about Odia, and a key that
#: is neither cannot inherit either one's drift. Stored in columns and sent on our own
#: wire; the vendor codes stay inside the adapters.
LanguageId = Literal[
    "telugu",
    "hindi",
    "english_india",
    "bengali",
    "gujarati",
    "kannada",
    "malayalam",
    "marathi",
    "odia",
    "punjabi",
    "tamil",
    "assamese",
    "bodo",
    "dogri",
    "kashmiri",
    "konkani",
    "maithili",
    "manipuri",
    "nepali",
    "sanskrit",
    "santali",
    "sindhi",
    "urdu",
]

#: Which half of the speech stack. Named for the leg rather than the vendor because the
#: two legs are separately sourced (CLAUDE.md: STT is Sarvam throughout, TTS is chosen
#: per agent, D-547) and the whole finding of this module is that they differ.
SpeechLeg = Literal["stt", "tts"]

#: Speech vendors this product has named. Membership here is NOT a claim that we know
#: what a vendor supports — see `VERIFIED_VENDOR_LEGS`.
SpeechVendor = Literal["sarvam", "cartesia", "gnani"]

#: Three-valued on purpose. `unverified` is not a softer `unsupported`: it says nobody
#: read the vendor's list, and it is the only one of the three that a human can close.
Support = Literal["supported", "unsupported", "unverified"]

TextDirection = Literal["ltr", "rtl"]


@dataclass(frozen=True, slots=True)
class Script:
    """A writing system, by its ISO 15924 code.

    A value object rather than a bare string so `direction` travels with it. Every layout
    that has to decide `dir="rtl"` then asks the script, and cannot get the answer right
    for Urdu and wrong for Kashmiri.
    """

    iso15924: str
    english_name: str
    direction: TextDirection


_ARAB: Final = Script("Arab", "Perso-Arabic", "rtl")
_BENG: Final = Script("Beng", "Bengali-Assamese", "ltr")
_DEVA: Final = Script("Deva", "Devanagari", "ltr")
_GUJR: Final = Script("Gujr", "Gujarati", "ltr")
_GURU: Final = Script("Guru", "Gurmukhi", "ltr")
_KNDA: Final = Script("Knda", "Kannada", "ltr")
_LATN: Final = Script("Latn", "Latin", "ltr")
_MLYM: Final = Script("Mlym", "Malayalam", "ltr")
_MTEI: Final = Script("Mtei", "Meetei Mayek", "ltr")
_OLCK: Final = Script("Olck", "Ol Chiki", "ltr")
_ORYA: Final = Script("Orya", "Odia", "ltr")
_TAML: Final = Script("Taml", "Tamil", "ltr")
_TELU: Final = Script("Telu", "Telugu", "ltr")


#: The (vendor, leg) pairs whose language list was read from the VENDOR'S OWN definition.
#: Only these can produce `supported` or `unsupported`; everything else is `unverified`.
VERIFIED_VENDOR_LEGS: Final[frozenset[tuple[SpeechVendor, SpeechLeg]]] = frozenset(
    {
        # sarvamai==0.1.28, types/speech_to_text_language.py:5-31 (read 14 Sep 2026).
        ("sarvam", "stt"),
        # sarvamai==0.1.28, types/text_to_speech_language.py:5-7 (read 14 Sep 2026).
        ("sarvam", "tts"),
    }
)

#: Named so the gap has a name and an owner, rather than being an absence. Each of these
#: is a leg this product either runs or plans to, whose language coverage NOBODY HAS READ
#: from the vendor. Closing one means reading that vendor's own list — not pipecat's map
#: of it, and not a figure already in this repository (hard rule 11).
UNVERIFIED_VENDOR_LEGS: Final[frozenset[tuple[SpeechVendor, SpeechLeg]]] = frozenset(
    {
        # D-547's premium TTS rung. Cartesia's SDK is not installed in this tree.
        ("cartesia", "tts"),
        # Gnani: no SDK, no docs, no mirror here. Nothing is known either way.
        ("gnani", "stt"),
        ("gnani", "tts"),
    }
)


@dataclass(frozen=True, slots=True)
class Language:
    """One language, and what each speech leg can do with it.

    `codes` is keyed by `(vendor, leg)` and holds the code AS THAT VENDOR SPELLS IT.
    Presence means supported; absence means unsupported on a verified leg and unverified
    on any other. Keying it this way is what lets a second TTS vendor be added without
    touching a single row it does not cover.
    """

    id: LanguageId
    #: The BCP-47 tag. OURS to emit, never assumed to be what a vendor accepts — see the
    #: Odia trap in the module docstring.
    bcp47: str
    #: The language's name in its own script, for a picker a caller's own staff will read.
    endonym: str
    english_name: str
    script: Script
    codes: Mapping[tuple[SpeechVendor, SpeechLeg], str]

    def support(self, vendor: SpeechVendor, leg: SpeechLeg) -> Support:
        """What we can honestly say about this vendor's leg for this language."""
        if (vendor, leg) in self.codes:
            return "supported"
        if (vendor, leg) in VERIFIED_VENDOR_LEGS:
            return "unsupported"
        return "unverified"

    def wire_code(self, vendor: SpeechVendor, leg: SpeechLeg) -> str | None:
        """The code to put on that vendor's wire, or `None` if it cannot take this one."""
        return self.codes.get((vendor, leg))

    @property
    def understood(self) -> bool:
        """Some VERIFIED STT leg can transcribe it."""
        return any(
            self.support(v, leg) == "supported" for v, leg in VERIFIED_VENDOR_LEGS if leg == "stt"
        )

    @property
    def answerable(self) -> bool:
        """Some VERIFIED TTS leg can speak it."""
        return any(
            self.support(v, leg) == "supported" for v, leg in VERIFIED_VENDOR_LEGS if leg == "tts"
        )

    @property
    def conversational(self) -> bool:
        """BOTH legs. The only property a language picker may offer a client.

        Not stored as a column: a stored boolean can disagree with the two legs it was
        derived from, and the disagreement surfaces as an agent that hears a caller and
        says nothing.
        """
        return self.understood and self.answerable

    @property
    def comprehension_only(self) -> bool:
        """Heard but not answerable. Useful for transcription-only surfaces; never a
        language an agent may be configured to converse in."""
        return self.understood and not self.answerable


def _language(
    language_id: LanguageId,
    bcp47: str,
    endonym: str,
    english_name: str,
    script: Script,
    *,
    sarvam_stt: str | None,
    sarvam_tts: str | None = None,
) -> Language:
    """One row. Keyword-only vendor codes so a row cannot silently swap its two legs —
    the legs differ for twelve of the twenty-three, which is exactly where a positional
    mistake would be invisible."""
    codes: dict[tuple[SpeechVendor, SpeechLeg], str] = {}
    if sarvam_stt is not None:
        codes[("sarvam", "stt")] = sarvam_stt
    if sarvam_tts is not None:
        codes[("sarvam", "tts")] = sarvam_tts
    return Language(
        id=language_id,
        bcp47=bcp47,
        endonym=endonym,
        english_name=english_name,
        script=script,
        codes=codes,
    )


# ORDERING IS PRODUCT ORDERING AND A PICKER SHOULD RENDER IT AS WRITTEN. Telugu first
# because we are Telugu-first (BRD §1) and a new agent's `language_primary` server-
# defaults to `te-IN`; then the two the product already sells beside it; then the rest of
# the conversational set; then the comprehension-only tail, which no picker shows.
_ROWS: Final[tuple[Language, ...]] = (
    # ---- CONVERSATIONAL: on both of Sarvam's own literals. -----------------------------
    _language(
        "telugu",
        "te-IN",
        "తెలుగు",
        "Telugu",
        _TELU,
        sarvam_stt="te-IN",
        sarvam_tts="te-IN",
    ),
    _language(
        "hindi",
        "hi-IN",
        "हिन्दी",
        "Hindi",
        _DEVA,
        sarvam_stt="hi-IN",
        sarvam_tts="hi-IN",
    ),
    _language(
        "english_india",
        "en-IN",
        "English",
        "English (India)",
        _LATN,
        sarvam_stt="en-IN",
        sarvam_tts="en-IN",
    ),
    _language(
        "bengali",
        "bn-IN",
        "বাংলা",
        "Bengali",
        _BENG,
        sarvam_stt="bn-IN",
        sarvam_tts="bn-IN",
    ),
    _language(
        "gujarati",
        "gu-IN",
        "ગુજરાતી",
        "Gujarati",
        _GUJR,
        sarvam_stt="gu-IN",
        sarvam_tts="gu-IN",
    ),
    _language(
        "kannada",
        "kn-IN",
        "ಕನ್ನಡ",
        "Kannada",
        _KNDA,
        sarvam_stt="kn-IN",
        sarvam_tts="kn-IN",
    ),
    _language(
        "malayalam",
        "ml-IN",
        "മലയാളം",
        "Malayalam",
        _MLYM,
        sarvam_stt="ml-IN",
        sarvam_tts="ml-IN",
    ),
    _language(
        "marathi",
        "mr-IN",
        "मराठी",
        "Marathi",
        _DEVA,
        sarvam_stt="mr-IN",
        sarvam_tts="mr-IN",
    ),
    # THE ODIA ROW IS THE TRAP. `bcp47` is `or-IN` (ISO 639-1 `or`); Sarvam's own two
    # literals both say `od-IN`; pipecat's realtime STT path says `or-IN` and its
    # validation set rejects `od-IN`. Both spellings are real and neither is wrong — they
    # belong to different layers. See `KNOWN_WIRE_CODE_ANOMALIES`.
    _language(
        "odia",
        "or-IN",
        "ଓଡ଼ିଆ",
        "Odia",
        _ORYA,
        sarvam_stt="od-IN",
        sarvam_tts="od-IN",
    ),
    _language(
        "punjabi",
        "pa-IN",
        "ਪੰਜਾਬੀ",
        "Punjabi",
        _GURU,
        sarvam_stt="pa-IN",
        sarvam_tts="pa-IN",
    ),
    _language(
        "tamil",
        "ta-IN",
        "தமிழ்",
        "Tamil",
        _TAML,
        sarvam_stt="ta-IN",
        sarvam_tts="ta-IN",
    ),
    # ---- COMPREHENSION-ONLY: on Sarvam's STT literal and NOT on its TTS literal. -------
    # An agent can be told what these callers said. It cannot answer them. No picker.
    _language(
        "assamese",
        "as-IN",
        "অসমীয়া",
        "Assamese",
        _BENG,
        sarvam_stt="as-IN",
    ),
    _language(
        "bodo",
        "brx-IN",
        "बर'",
        "Bodo",
        _DEVA,
        sarvam_stt="brx-IN",
    ),
    _language(
        "dogri",
        "doi-IN",
        "डोगरी",
        "Dogri",
        _DEVA,
        sarvam_stt="doi-IN",
    ),
    # Kashmiri: Perso-Arabic is the official script in J&K; also written in Devanagari
    # and Sharada. RTL, which is why `Script` carries direction at all.
    _language(
        "kashmiri",
        "ks-IN",
        "کٲشُر",
        "Kashmiri",
        _ARAB,
        sarvam_stt="ks-IN",
    ),
    # Konkani: Devanagari is the official script (Goa); also written in Kannada, Latin
    # and Malayalam scripts by different communities.
    _language(
        "konkani",
        "kok-IN",
        "कोंकणी",
        "Konkani",
        _DEVA,
        sarvam_stt="kok-IN",
    ),
    _language(
        "maithili",
        "mai-IN",
        "मैथिली",
        "Maithili",
        _DEVA,
        sarvam_stt="mai-IN",
    ),
    # Manipuri (Meitei): Meetei Mayek is the script Manipur made official; the
    # Bengali-Assamese script is still in wide use for the same language.
    _language(
        "manipuri",
        "mni-IN",
        "ꯃꯤꯇꯩ ꯂꯣꯟ",
        "Manipuri (Meitei)",
        _MTEI,
        sarvam_stt="mni-IN",
    ),
    _language(
        "nepali",
        "ne-IN",
        "नेपाली",
        "Nepali",
        _DEVA,
        sarvam_stt="ne-IN",
    ),
    _language(
        "sanskrit",
        "sa-IN",
        "संस्कृतम्",
        "Sanskrit",
        _DEVA,
        sarvam_stt="sa-IN",
    ),
    _language(
        "santali",
        "sat-IN",
        "ᱥᱟᱱᱛᱟᱲᱤ",
        "Santali",
        _OLCK,
        sarvam_stt="sat-IN",
    ),
    # Sindhi in India is official in BOTH Perso-Arabic and Devanagari. Perso-Arabic is
    # recorded here; a surface that needs the other must carry it as a second row, not
    # flip this one.
    _language(
        "sindhi",
        "sd-IN",
        "سنڌي",
        "Sindhi",
        _ARAB,
        sarvam_stt="sd-IN",
    ),
    _language(
        "urdu",
        "ur-IN",
        "اردو",
        "Urdu",
        _ARAB,
        sarvam_stt="ur-IN",
    ),
)

#: Every declared language, in product order. A `Mapping`, not a `dict`: callers read.
LANGUAGES: Final[Mapping[LanguageId, Language]] = {row.id: row for row in _ROWS}

#: EVERY PLACE A VENDOR'S CODE IS NOT THE BCP-47 TAG. An equality-asserted ledger, so a
#: second vendor that spells something its own way fails `tests/languages_test.py` rather
#: than one phone call. Today it holds exactly the Odia trap, on both Sarvam legs.
KNOWN_WIRE_CODE_ANOMALIES: Final[Mapping[tuple[SpeechVendor, SpeechLeg, LanguageId], str]] = {
    ("sarvam", "stt", "odia"): "od-IN",
    ("sarvam", "tts", "odia"): "od-IN",
}

#: A FRAMEWORK gap, not a vendor one, and recorded here so nobody re-derives it from a
#: short pipecat table and concludes Sarvam cannot hear these. `pipecat-ai==1.10.0`'s
#: `services/sarvam/stt.py:738-757` maps only 17 of Sarvam's 23 codes back to its own
#: `Language` enum; a transcript in one of these twelve still arrives, with
#: `TranscriptionFrame.language` left unset rather than guessed (the framework says so in
#: that function's own docstring). None is conversational, so the cost is a missing label
#: and never a missing reply. Read 14 Sep 2026.
STT_LANGUAGES_PIPECAT_CANNOT_LABEL: Final[frozenset[LanguageId]] = frozenset(
    {"bodo", "dogri", "kashmiri", "nepali", "sanskrit", "santali"}
)


def conversational_languages() -> tuple[Language, ...]:
    """The languages an agent can actually hold a call in, in product order.

    THIS IS THE ONE ANSWER a language picker, the agent-configuration screen and any API
    that offers a choice may use. Anything wider offers a caller an agent that cannot
    reply.
    """
    return tuple(row for row in _ROWS if row.conversational)


#: WHAT THE PRODUCT SELLS, which is a commercial fact and not a vendor one.
#:
#: Three of the eleven conversational languages, Telugu first (BRD §1, and the server
#: default of `agents.language_primary`). It is a SEPARATE declaration from the capability
#: table above for the reason the module docstring gives: reading a vendor's SDK must never
#: be able to put a language on a client's screen.
#:
#: **ADDING ONE IS NOT AN EDIT TO THIS LINE.** A new offered language needs, in the same
#: change: the tag in `apps/api/agents/languages.Language` (the Pydantic/OpenAPI enum), the
#: three spoken sentences in `apps/api/compliance/disclosure.py`, the handover sentence in
#: `apps/api/agents/handoff.py`, a voice in the engine account's catalogue, and the CHECK
#: constraint on `agents.language_primary` widened by a migration. `tests/product_languages_
#: test.py` fails on each of those that is missing, so the requirement is enforced rather
#: than remembered — except the VOICE, which is operational (an engine account's own
#: catalogue, synced and curated) and which no test in this tree can see.
OFFERED_LANGUAGE_IDS: Final[tuple[LanguageId, ...]] = ("telugu", "hindi", "english_india")


def offered_languages() -> tuple[Language, ...]:
    """The languages this product SELLS today, in the order a picker renders them.

    A subset of `conversational_languages()` and never wider — see the module docstring.
    Rows rather than tags so a caller that needs a label, a script or a text direction has
    it without a second lookup table.
    """
    return tuple(LANGUAGES[language_id] for language_id in OFFERED_LANGUAGE_IDS)


def offered_language_tags() -> tuple[str, ...]:
    """The same three, as the BCP-47 tags our own wire and our own columns carry.

    OUR tags, never a vendor's: `wire_code()` is the only thing that may reach a vendor,
    and the Odia trap in the module docstring is why the two cannot be the same function.
    """
    return tuple(row.bcp47 for row in offered_languages())


def comprehension_only_languages() -> tuple[Language, ...]:
    """Understood, not answerable. For transcription-only surfaces and for explaining to
    an operator WHY a language they can see in a transcript is not on the picker."""
    return tuple(row for row in _ROWS if row.comprehension_only)


def get_language(language_id: LanguageId) -> Language:
    """Look one up by our own identifier. Raises `KeyError` on an unknown id — this takes
    a `LanguageId`, so an unknown one is a bug rather than bad input."""
    return LANGUAGES[language_id]


def find_language(code: str) -> Language | None:
    """Look one up by ANY code that identifies it — our id, its BCP-47 tag, or any
    vendor's spelling — returning `None` rather than raising, because this is the arm
    that takes a string off a wire or out of a column.

    It accepts vendor spellings on purpose: `od-IN` arriving from Sarvam and `or-IN`
    arriving from pipecat are the same language, and a caller that had to know which
    layer produced the string would be re-deriving the trap this module exists to hold.
    """
    for row in _ROWS:
        if code in (row.id, row.bcp47) or code in row.codes.values():
            return row
    return None
