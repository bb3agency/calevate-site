"""In-call knowledge search: one `KnowledgePack` in RAM, lexical, gated, four answers.

**WHAT THIS IS.** The consumer side of `calevate_shared.knowledge_pack` (D-599). The pack is
built once at publish and stored immutably; this module fetches it once while the phone is
ringing, builds a BM25 index over it, and answers every turn in-process. No network on the
turn, no inference on the turn, no vendor on the turn — which is the entire reason the pack
exists, and the contract's docstring carries the measurement that decided it (a query
embedding is an ocean crossing against a 100 ms budget, and the only local encoder cheap
enough on 1-2 shared cores has no Telugu number at all).

**HARD RULE 2.** Nothing here imports a vendor SDK or sees a vendor payload. What it hands
out is `calevate_shared.retrieval.Passage` — ours. The one seam to the outside world is
`PackFetcher`, a protocol taking an object key and returning bytes, so whichever client
eventually reads object storage is somebody else's import and not this module's.

**HARD RULE 6.** The caller's question, a passage and a gloss are all conversation content
and none of them is ever logged. What is logged is ids, counts, the outcome word and the
elapsed milliseconds — see `_log_answer`, which is the only log call in the module.

---

## The ranking function, and why it is BM25 and nothing else

`docs/evidence/telugu-embedding-quality.md` §4 measured, on the Tenglish queries Sarvam's
Saaras STT actually returns, BM25 (k1=1.5, b=0.75) scoring **0.042 recall@1 against a
Telugu-script corpus and 0.625 against an English one**. The English gloss on every
`PackEntry` is what converts the first number into the second, and it was written for a
lexical arm specifically. `BM25_K1`/`BM25_B` below are that harness's parameters verbatim,
so the ranker those figures describe is the ranker that runs here rather than a cousin of
it.

Rejected: TF-IDF cosine (no length normalisation, and a four-sentence chunk would beat a
one-line opening-hours entry on term count alone); plain term-overlap counting (no IDF, so
"what" and "time" weigh the same); and anything dense (see the contract's docstring — the
measurement, not an omission).

## The gate, which is the part that is not optional

§4(b) of the same file records **unconditional RRF fusion making two cells WORSE** —
0.708 → 0.375 and 0.625 → 0.292 — because it averaged in a ranking from an arm that matched
nothing. We have one arm, so the equivalent trap is not fusion: it is scoring a question
whose words do not occur in this corpus at all, and presenting whatever floated to the top
as an answer. BM25 always returns SOMETHING for any query sharing one token with any
document, and "the" is a token.

So a score is not sufficient evidence of an answer. Two conditions gate `found`:

1. the query must contain at least one INFORMATIVE term that occurs in the corpus —
   informative meaning it survived `_QUERY_STOPWORDS` and, on a corpus large enough for
   document frequency to mean anything, occurs in at most `MAX_INFORMATIVE_DF_RATIO` of the
   entries; and
2. the top-scoring entry must be one such a term actually matched.

Neither holding is `not_found`, which on a call is "we do not publish that" — a fact the
caller can act on — and never a low-scoring best guess dressed as knowledge.

**AN ABSOLUTE IDF THRESHOLD WAS TRIED HERE FIRST AND IS WRONG, WHICH IS WORTH RECORDING
BECAUSE IT LOOKS RIGHT.** IDF collapses on a small corpus: in a two-entry pack about one
branch's opening hours, "Kukatpally" occurs in both, scores `ln(1.2) = 0.18`, and any
threshold that rejects filler words in a 300-entry pack also rejects the only content word
a two-entry pack has. The client with two chunks would have been answered `not_found` for
every question they published knowledge to answer. Hence the ratio, and hence
`DF_GATE_MIN_ENTRIES` standing the ratio down below the size where it is measuring
anything.

**AND THE DEGENERATE CASE THE GATE NO LONGER HAS TO CATCH IS CAUGHT BY THE NEXT RULE.** A
term occurring in every entry of a large pack gives every entry nearly the same score, and
near-equal top two from different documents is exactly what `AMBIGUITY_MARGIN` calls
`ambiguous` — one clarifying question, rather than a coin flip presented as a fact.

## The query forms, and what transliteration does NOT buy

Three deterministic forms, searched independently, per-entry score taken as the MAX across
them (never a sum and never a fusion — §4(b) again: a form that matched nothing must not be
able to move a form that did):

* **raw** — the transcript as STT returned it, case-folded and split, diacritics INTACT, so
  a romanised-Telugu gloss written with diacritics matches on the nose;
* **normalised** — NFKC, case-folded, punctuation to whitespace, and Latin combining marks
  stripped, so `ḍākṭar` also matches a corpus that spelled it `dakter`. Marks are stripped
  only where the base character is Latin: dropping them from Telugu would delete the vowel
  signs and turn the script into consonant soup;
* **transliterated** — produced only when the text contains Telugu script (U+0C00-U+0C7F).

⚠ **TRANSLITERATION IS NOT TRANSLATION AND MUST NEVER BE DESCRIBED AS ONE.** It produces
ROMANISED TELUGU: `డాక్టర్` becomes `ḍākṭar`, which does **not** lexically match an English
gloss containing "doctor" and was never going to. What it buys is narrower and real — a
query in Telugu script has ZERO tokens in common with a Latin-script corpus, and after
transliteration it has a chance of matching the romanised words a Tenglish-written entry
contains. It converts an impossible match into a possible one; it does not translate.

**The reason the lexical arm works in production is different, and it is measured.** Saaras
returns **Tenglish** — Telugu grammar in Latin script, studded with English nouns
("Appointment ela book cheskovali?", `tests/fixtures/golden_transcripts.json`). Those nouns
are already Latin and already match the English gloss, with no transliteration involved.
Transliteration is the fallback for the Telugu-script minority of turns, not the mechanism.

**NO LLM CALL, EVER, ON THIS PATH.** A translation hop mid-turn is a network round trip,
which is the single thing this design exists to avoid. A question we cannot resolve is
`ambiguous`, and the agent asks one clarifying question — which costs nothing and is what a
human receptionist does.

The transliterator is a mapping in this module (`_TELUGU_*` below), not a dependency: it is
~90 codepoints of table plus three rules, and hard rule 9 makes a new transitive dependency
tree a cost to be justified rather than a convenience.

## The cache, and the tenancy property it has by construction

Pipecat Cloud **reuses containers across sessions** ("a warm instance is kept running and
can immediately be used to serve an active session"), so a pack loaded for clinic A's call
outlives that call inside a process that may next serve clinic B. `PackCache` is keyed on
`content_sha256` — the pack's content hash, which is what the digest is FOR — and a key
that cannot name two different byte strings cannot serve A's knowledge into B's call. The
cache is bounded (`MAX_CACHED_PACKS`, LRU) because unbounded is a leak, and every hit is
re-checked against the tenant and agent the session asked for: a hit whose identity
disagrees is evicted and answered as unavailable rather than trusted. That second check is
redundant against a correctly-built pack — tenant and agent are inside the digest — and it
stays because the cost is two comparisons and the failure it catches is cross-tenant
disclosure on a live call.

## Failure is a STATE

A fetch that failed, a format version this build does not understand, a pack that is not
there: none of them raises past `load_session_knowledge`. Each produces a `SessionKnowledge`
whose every answer is `temporarily_unavailable`, and the call continues. The contract's
docstring argues why that is a different word from `not_found` — one is knowledge about the
corpus, the other is knowledge about ourselves, and only one should page anybody.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol
from uuid import UUID

from calevate_shared.knowledge_pack import (
    PACK_FORMAT_VERSION,
    KnowledgePack,
    PackEntry,
    RetrievalOutcome,
    pack_object_key,
)
from calevate_shared.retrieval import Passage, Provenance
from loguru import logger

# ---------------------------------------------------------------------------------------
# Ranking constants. ONE of these is measured; the rest say plainly that they are not.
# ---------------------------------------------------------------------------------------

#: BM25 term-frequency saturation. **MEASURED-ADJACENT, not a guess**: k1=1.5 / b=0.75 are
#: the parameters `docs/evidence/telugu-embedding-quality.md` §4 ran its lexical column
#: with, so the 0.042-vs-0.625 Telugu/English gloss finding describes THIS ranker. Changing
#: either number silently invalidates that citation.
BM25_K1: Final[float] = 1.5

#: BM25 length normalisation. Same provenance as `BM25_K1`.
BM25_B: Final[float] = 0.75

#: The largest share of the corpus a query term may occur in and still count as evidence
#: about WHICH entry to return. A term true of every entry says nothing about which one.
#:
#: ⚠ **A STARTING POINT TO BE MEASURED ON REAL CALLS, NOT A FINDING.** Nobody has run this
#: gate against a recorded Telugu call. Half is the round number that admits a term shared
#: by a topical cluster and rejects one that is true of the whole pack; what replaces this
#: comment is a number from call recordings, not a better argument.
MAX_INFORMATIVE_DF_RATIO: Final[float] = 0.5

#: Below this many entries the document-frequency ratio is switched OFF and only
#: `_QUERY_STOPWORDS` gates.
#:
#: ⚠ **A STARTING POINT TO BE MEASURED ON REAL CALLS, NOT A FINDING** — but the reasoning
#: is not arbitrary: "in 2 of 2 entries" and "in 200 of 200 entries" are not the same
#: evidence, and a ratio computed over a handful of chunks is measuring the sample, not the
#: vocabulary. Ten is the smallest corpus at which a half-the-pack threshold can distinguish
#: more than two buckets.
DF_GATE_MIN_ENTRIES: Final[int] = 10

#: How far clear of the runner-up the top entry must be, as a fraction of the top score,
#: before we call it `found` rather than `ambiguous`.
#:
#: ⚠ **A STARTING POINT TO BE MEASURED ON REAL CALLS, NOT A FINDING.** The reasoning it
#: encodes is only this: two entries from DIFFERENT documents scoring within a few percent
#: of each other is the shape of a question that named a category rather than a thing
#: ("what are your charges?" against a pack with consultation, scan and procedure fees),
#: and guessing between them on a phone call is worse than asking which one. Entries from
#: the SAME document do not trigger it — they are two spans of one answer, not two answers.
AMBIGUITY_MARGIN: Final[float] = 0.15

#: Passages returned on a `found`. TRD §6's in-call number, which is also
#: `calevate_shared.retrieval.RetrievalRequest.k`'s default — the one k in this repo that
#: was chosen rather than picked.
DEFAULT_TOP_K: Final[int] = 3

#: How many distinct packs one warm container keeps. A pack is kilobytes, and a container
#: serves one session at a time, so this is a bound against unbounded growth across a long-
#: lived instance rather than a working-set estimate. Pipecat Cloud's documented maximum
#: pool size is 50 CONTAINERS, which is not a number of packs and is not this number.
MAX_CACHED_PACKS: Final[int] = 8

#: The Telugu Unicode block. Presence of any codepoint in it is what turns the
#: transliterated query form on.
_TELUGU_BLOCK_START: Final[int] = 0x0C00
_TELUGU_BLOCK_END: Final[int] = 0x0C7F

#: Why a pack could not be loaded. Each is an OPERATOR-facing word: the caller only ever
#: hears the agent say it cannot verify something right now.
UnavailableReason = Literal["fetch_failed", "absent", "unsupported_format", "identity_mismatch"]


# ---------------------------------------------------------------------------------------
# Transliteration — Telugu script to romanised Telugu. A table, not a dependency.
# ---------------------------------------------------------------------------------------

# `fmt: off` around the tables below: these are GRIDS, and the formatter's magic-trailing-
# comma rule would explode ~150 codepoints to one per line. A transliteration table read
# one row per character is unreviewable; read as a grid it is checkable against a chart.
# fmt: off
#: Independent vowels (U+0C05..U+0C14, plus the two vocalic letters at U+0C60/U+0C61).
_TELUGU_VOWELS: Final[dict[str, str]] = {
    "అ": "a", "ఆ": "ā", "ఇ": "i", "ఈ": "ī",
    "ఉ": "u", "ఊ": "ū", "ఋ": "r̥", "ఌ": "l̥",
    "ఎ": "e", "ఏ": "ē", "ఐ": "ai",
    "ఒ": "o", "ఓ": "ō", "ఔ": "au",
    "ౠ": "r̥̄", "ౡ": "l̥̄",
}
# fmt: on

# fmt: off
#: Consonants (U+0C15..U+0C39). Each carries the inherent vowel `a`, which a vowel SIGN
#: replaces and the virama removes — the two rules in `transliterate_telugu`.
_TELUGU_CONSONANTS: Final[dict[str, str]] = {
    "క": "k", "ఖ": "kh", "గ": "g", "ఘ": "gh", "ఙ": "ṅ",
    "చ": "c", "ఛ": "ch", "జ": "j", "ఝ": "jh", "ఞ": "ñ",
    "ట": "ṭ", "ఠ": "ṭh", "డ": "ḍ", "ఢ": "ḍh", "ణ": "ṇ",
    "త": "t", "థ": "th", "ద": "d", "ధ": "dh", "న": "n",
    "ప": "p", "ఫ": "ph", "బ": "b", "భ": "bh", "మ": "m",
    "య": "y", "ర": "r", "ఱ": "ṟ", "ల": "l", "ళ": "ḷ",
    "ఴ": "ḻ", "వ": "v", "శ": "ś", "ష": "ṣ", "స": "s",
    "హ": "h",
}
# fmt: on

# fmt: off
#: Dependent vowel signs (U+0C3E..U+0C4C). Each REPLACES the inherent `a` of the consonant
#: it follows.
_TELUGU_VOWEL_SIGNS: Final[dict[str, str]] = {
    "ా": "ā", "ి": "i", "ీ": "ī", "ు": "u", "ూ": "ū",
    "ృ": "r̥", "ౄ": "r̥̄", "ె": "e", "ే": "ē", "ై": "ai",
    "ొ": "o", "ో": "ō", "ౌ": "au",
}
# fmt: on

# fmt: off
#: Anusvara, visarga, candrabindu and the Telugu digits — carried so a number in a question
#: ("౧౦ గంటలు") tokenises as the same digits the corpus spells in ASCII.
_TELUGU_SIGNS: Final[dict[str, str]] = {
    # ⚠ ANUSVARA IS ROMANISED `n`, NOT ISO 15919's `ṁ`, AND THAT IS A DELIBERATE
    # DEPARTURE FROM THE STANDARD. The output of this function is never shown to anybody —
    # it exists only to be matched lexically against a corpus that Tenglish speakers wrote,
    # and Tenglish writes the anusvara as `n` ("undi", "bangaram", "chandamama"). `ṁ` is
    # the correct scholarly romanisation and matches nothing.
    "ఁ": "n", "ం": "n", "ః": "h",  # noqa: RUF001
    "౦": "0", "౧": "1", "౨": "2", "౩": "3", "౪": "4",  # noqa: RUF001
    "౫": "5", "౬": "6", "౭": "7", "౮": "8", "౯": "9",
}
# fmt: on

#: Virama: deletes the inherent vowel of the preceding consonant, which is what makes
#: `డాక్టర్` come out as `ḍākṭar` rather than `ḍākaṭara`.
_TELUGU_VIRAMA: Final[str] = "్"

_INHERENT_VOWEL: Final[str] = "a"

#: A token starts with an alphanumeric and may continue with COMBINING MARKS as well.
#: The trailing class is not decoration: Telugu vowel signs and the virama are category Mn
#: and Mc, so a plain `\w+` splits `ఆరోగ్యశ్రీ` into four fragments at the signs, and the
#: Latin combining marks the transliterator emits (`r̥`) break a token the same way.
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"[^\W_](?:[^\W_]|[\u0300-\u036F\u0C00-\u0C7F])*", re.UNICODE
)

# fmt: off
#: Function words dropped from the QUERY and kept in the INDEX.
#:
#: **THE ASYMMETRY IS THE POINT.** IDF already makes a word occurring everywhere score
#: nothing, so stopwords barely move a ranking — but the GATE asks whether the caller said
#: anything informative at all, and on a pack of a few dozen entries even "in" clears an IDF
#: threshold by accident (a term in 2 of 6 entries scores 1.03). A question made entirely of
#: function words would then pass the gate and be answered from whichever entry happened to
#: contain "in". Dropping them from the index instead would falsify every document length
#: and therefore the length normalisation BM25 is chosen for, so they stay there.
#:
#: ⚠ **A STARTING POINT TO BE MEASURED ON REAL CALLS.** English function words plus the
#: highest-frequency Tenglish interrogatives and copulas — the words `tests/fixtures/
#: golden_transcripts.json` shows Saaras returning in every question ("Appointment ela book
#: cheskovali?"). It is deliberately short: a word wrongly listed here is a question the
#: agent cannot answer, which is a worse failure than a word wrongly kept.
#:
#: "us" IS NOT HERE, AND THAT IS A GUARD SPEAKING, NOT A LINGUIST. `scripts/check_model_
#: residency.py` refuses a bare `"us"` anywhere in `apps/` that is not a `Final` constant's
#: value, because OpenAI's residency regions are two-letter and a loose one is a region pin
#: no check can see. Its own docstring names a future locale or dict key as the cost and
#: calls the trade correct. Dropping the pronoun is the right side of this list's bias
#: anyway: "us" is never a topic word, and a query carrying it loses nothing.
_QUERY_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        # English
        "a", "an", "and", "any", "are", "at", "be", "by", "can", "could", "do", "does",
        "for", "from", "have", "how", "i", "in", "is", "it", "me", "my", "of", "on", "or",
        "please", "tell", "that", "the", "there", "this", "to", "was", "we", "what",
        "when", "where", "which", "who", "will", "with", "would", "you", "your",
        # Tenglish / romanised Telugu function words
        "ela", "emi", "enti", "ekkada", "eppudu", "evaru", "kavali", "meeru", "mee",
        "naaku", "nenu", "unda", "undi", "undaa", "vundi", "cheyali", "cheskovali",
        "chestara", "avutundi", "ki", "ku", "lo", "tho", "kosam", "gurinchi",
    }
)
# fmt: on


def has_telugu_script(text: str) -> bool:
    """Does `text` contain a codepoint in the Telugu block (U+0C00-U+0C7F)?"""
    return any(_TELUGU_BLOCK_START <= ord(ch) <= _TELUGU_BLOCK_END for ch in text)


def transliterate_telugu(text: str) -> str:
    """Telugu script → ROMANISED TELUGU. Deterministic, table-driven, no model.

    ⚠ **This is not a translation.** `డాక్టర్` → `ḍākṭar`, which will not match an English
    gloss saying "doctor". See the module docstring for what it does buy and why that is
    still worth the table.

    Non-Telugu characters pass through untouched, so a Tenglish sentence with a few Telugu
    words in it comes out wholly Latin rather than half-transliterated.
    """
    out: list[str] = []
    pending_consonant = False
    for ch in text:
        if ch in _TELUGU_CONSONANTS:
            if pending_consonant:
                out.append(_INHERENT_VOWEL)
            out.append(_TELUGU_CONSONANTS[ch])
            pending_consonant = True
            continue
        if ch in _TELUGU_VOWEL_SIGNS:
            # The sign supplies the vowel, so the inherent one is never emitted.
            out.append(_TELUGU_VOWEL_SIGNS[ch])
            pending_consonant = False
            continue
        if ch == _TELUGU_VIRAMA:
            # Bare consonant: drop the inherent vowel entirely.
            pending_consonant = False
            continue
        if pending_consonant:
            out.append(_INHERENT_VOWEL)
            pending_consonant = False
        if ch in _TELUGU_VOWELS:
            out.append(_TELUGU_VOWELS[ch])
        elif ch in _TELUGU_SIGNS:
            out.append(_TELUGU_SIGNS[ch])
        else:
            out.append(ch)
    if pending_consonant:
        out.append(_INHERENT_VOWEL)
    return "".join(out)


def _fold_latin_marks(text: str) -> str:
    """Strip combining marks, but ONLY where the base character is Latin.

    `ḍākṭar` → `dakțar`-without-marks → `daktar`, so a corpus that romanised without
    diacritics still matches. Applying the same fold to Telugu would delete the vowel signs
    — `కాలం` would become `కలం`, a different word — so the base character decides.
    """
    decomposed = unicodedata.normalize("NFD", text)
    out: list[str] = []
    base_is_latin = False
    for ch in decomposed:
        if unicodedata.combining(ch):
            if not base_is_latin:
                out.append(ch)
            continue
        base_is_latin = ch.isascii() and ch.isalpha()
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def _tokenise(text: str, *, fold_marks: bool) -> tuple[str, ...]:
    """Case-folded alphanumeric runs. `fold_marks` is what separates the raw and normalised
    query forms — see the module docstring."""
    prepared = unicodedata.normalize("NFKC", text) if fold_marks else text
    if fold_marks:
        prepared = _fold_latin_marks(prepared)
    return tuple(match.group(0).casefold() for match in _TOKEN_RE.finditer(prepared))


def query_forms(question: str) -> tuple[tuple[str, ...], ...]:
    """Every deterministic token form of one question, de-duplicated, order stable.

    Deterministic is the whole specification: no model, no network, no vendor. A form that
    collapses onto another (the usual case for a pure-ASCII question, where raw and
    normalised tokenise identically) is dropped rather than scored twice, and a form left
    empty by `_QUERY_STOPWORDS` is dropped too — a question made of nothing but function
    words is a question with no topic in it.
    """
    forms: list[tuple[str, ...]] = []
    candidates = [
        _tokenise(question, fold_marks=False),
        _tokenise(question, fold_marks=True),
    ]
    if has_telugu_script(question):
        candidates.append(_tokenise(transliterate_telugu(question), fold_marks=True))
    for raw_form in candidates:
        form = tuple(token for token in raw_form if token not in _QUERY_STOPWORDS)
        if form and form not in forms:
            forms.append(form)
    return tuple(forms)


# ---------------------------------------------------------------------------------------
# The index.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Scored:
    """One entry's standing after every query form has been scored against it."""

    score: float
    #: Did an INFORMATIVE term actually match this entry (see `_informative_terms`)? A score
    #: built entirely out of corpus-wide filler words is not evidence, and the gate reads
    #: this rather than the number.
    informative: bool


class LexicalIndex:
    """BM25 over `text` AND `gloss`, built once at load.

    Both fields go into ONE bag of words rather than two scored fields: the gloss is a
    retrieval KEY for the same fact, not a competing document, and scoring them separately
    would let an entry with a gloss outrank the same entry without one for reasons that are
    about our ingestion pipeline rather than about the caller's question.

    A few hundred entries and a few thousand terms, so building is microseconds and one
    query is a dict walk over the query's own terms. No network, no inference, no vendor.
    """

    __slots__ = ("_avgdl", "_doc_len", "_entries", "_idf", "_postings")

    def __init__(self, entries: Sequence[PackEntry]) -> None:
        self._entries: tuple[PackEntry, ...] = tuple(entries)
        self._postings: dict[str, dict[int, int]] = {}
        self._doc_len: list[int] = []
        for position, entry in enumerate(self._entries):
            tokens = self._entry_tokens(entry)
            self._doc_len.append(len(tokens))
            for token in tokens:
                self._postings.setdefault(token, {})
                self._postings[token][position] = self._postings[token].get(position, 0) + 1
        total = sum(self._doc_len)
        # An empty pack has no average length; 1.0 keeps the arithmetic finite and every
        # query returns nothing anyway, because there are no postings to walk.
        self._avgdl: float = (total / len(self._doc_len)) if self._doc_len and total else 1.0
        count = len(self._entries)
        self._idf: dict[str, float] = {
            term: math.log(1.0 + (count - len(postings) + 0.5) / (len(postings) + 0.5))
            for term, postings in self._postings.items()
        }

    @staticmethod
    def _entry_tokens(entry: PackEntry) -> tuple[str, ...]:
        """Indexed in BOTH the raw and mark-folded forms, so an entry romanised WITH
        diacritics is reachable from a query that has none and vice versa. Duplicating the
        identical tokens of an ASCII entry would double its term frequencies and flatter it
        against its neighbours, so the folded pass only contributes tokens the raw pass did
        not already produce."""
        body = entry.text if entry.gloss is None else f"{entry.text}\n{entry.gloss}"
        raw = _tokenise(body, fold_marks=False)
        folded = _tokenise(body, fold_marks=True)
        seen = set(raw)
        return raw + tuple(token for token in folded if token not in seen)

    @property
    def entries(self) -> tuple[PackEntry, ...]:
        return self._entries

    def search(self, forms: Iterable[tuple[str, ...]]) -> dict[int, _Scored]:
        """Score every form, keep the per-entry MAXIMUM.

        MAX rather than sum or RRF, and that choice is the §4(b) finding applied to forms
        instead of arms: a transliterated form that matched nothing must not be able to move
        the ranking a Tenglish form got right. A maximum cannot; an average can and did.
        """
        best: dict[int, _Scored] = {}
        for form in forms:
            for position, scored in self._score_form(form).items():
                current = best.get(position)
                if current is None or scored.score > current.score:
                    best[position] = scored
        return best

    def _is_informative(self, term: str) -> bool:
        """Does matching `term` tell us anything about WHICH entry to return?

        On a corpus too small for document frequency to be a measurement, the answer is yes
        for anything that survived `_QUERY_STOPWORDS` — see the module docstring for the
        two-entry pack this protects.
        """
        postings = self._postings.get(term)
        if postings is None:
            return False
        count = len(self._entries)
        if count < DF_GATE_MIN_ENTRIES:
            return True
        return len(postings) / count <= MAX_INFORMATIVE_DF_RATIO

    def _score_form(self, terms: Sequence[str]) -> dict[int, _Scored]:
        scores: dict[int, float] = {}
        informative_hits: set[int] = set()
        # De-duplicated: a caller repeating a word is emphasis, not evidence, and query-side
        # term frequency is noise at this length.
        for term in dict.fromkeys(terms):
            postings = self._postings.get(term)
            if postings is None:
                continue
            idf = self._idf[term]
            informative = self._is_informative(term)
            for position, tf in postings.items():
                norm = 1.0 - BM25_B + BM25_B * (self._doc_len[position] / self._avgdl)
                scores[position] = scores.get(position, 0.0) + idf * (
                    tf * (BM25_K1 + 1.0) / (tf + BM25_K1 * norm)
                )
                if informative:
                    informative_hits.add(position)
        return {
            position: _Scored(score=score, informative=position in informative_hits)
            for position, score in scores.items()
        }


# ---------------------------------------------------------------------------------------
# The cache.
# ---------------------------------------------------------------------------------------


class PackCache:
    """Bounded LRU of built indexes, keyed on the pack's CONTENT DIGEST.

    The key is why this is safe in a container Pipecat Cloud reuses across sessions: a
    content hash cannot name two different byte strings, and `KnowledgePack.digest` hashes
    the tenant and the agent along with the entries, so clinic A's pack and clinic B's pack
    cannot collide on a key however similar their knowledge is.

    Not thread-safe and deliberately not locked: one container runs one asyncio loop, and a
    lock around a dict access on the audio path buys nothing. Two coroutines racing the same
    cold key both fetch and the second overwrites the first with identical bytes, which is
    wasted work rather than a wrong answer.
    """

    __slots__ = ("_entries", "_max_entries")

    def __init__(self, max_entries: int = MAX_CACHED_PACKS) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[KnowledgePack, LexicalIndex]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def keys(self) -> tuple[str, ...]:
        """Digests currently held, LRU first. For tests and operator inspection; a digest is
        an id, so logging one does not breach hard rule 6."""
        return tuple(self._entries)

    def get(
        self, content_sha256: str, *, tenant_id: UUID, agent_id: UUID
    ) -> tuple[KnowledgePack, LexicalIndex] | None:
        """A hit only if the digest matches AND the pack is this tenant's and this agent's.

        The identity re-check is redundant against a correctly built pack — both ids are
        inside the digest — and it stays because it costs two comparisons and the failure it
        would catch is cross-tenant disclosure on a live call. A disagreeing entry is
        EVICTED, not merely ignored: if it is wrong for this caller it is wrong for the next
        one, and leaving it in place would hand it to them.
        """
        held = self._entries.get(content_sha256)
        if held is None:
            return None
        pack, _index = held
        if pack.tenant_id != tenant_id or pack.agent_id != agent_id:
            del self._entries[content_sha256]
            logger.error(
                "knowledge pack identity mismatch, evicted",
                digest=content_sha256,
                tenant_id=str(tenant_id),
                agent_id=str(agent_id),
            )
            return None
        self._entries.move_to_end(content_sha256)
        return held

    def put(self, pack: KnowledgePack, index: LexicalIndex) -> None:
        self._entries[pack.content_sha256] = (pack, index)
        self._entries.move_to_end(pack.content_sha256)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


# ---------------------------------------------------------------------------------------
# Loading.
# ---------------------------------------------------------------------------------------


class PackFetcher(Protocol):
    """The one seam to the outside world: an object key in, bytes out.

    A PROTOCOL rather than an object-storage client, for hard rule 2's reason one layer
    down — whichever client eventually reads the bucket is that module's import, and this
    one stays free of vendor shapes and testable without a network. `None` means the object
    is not there, which is a different fact from a fetch that failed and is reported as one.
    """

    async def fetch(self, object_key: str) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class KnowledgeAnswer:
    """What one in-call lookup produced: a state, its evidence, and how long it took.

    `RetrievalResult` from `calevate_shared.retrieval` is deliberately NOT used: it has no
    field for the outcome word, forbids extras, and carries a `provider`/`served_tier`
    vocabulary that belongs to the port `apps/api/retrieval` implements. The four states are
    the contract here (`RetrievalOutcome`), and the passages are the shared `Passage` so
    provenance travels in one vocabulary.
    """

    outcome: RetrievalOutcome
    passages: tuple[Passage, ...] = ()
    #: Wall clock inside the search, milliseconds. Every latency number in this repo is
    #: measured (hard rule 11); this is where the in-call retrieval one is measured.
    elapsed_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class SessionKnowledge:
    """One session's knowledge, or the named reason there is none.

    Constructed by `load_session_knowledge` and held for the life of the call. A failure to
    load is a STATE carried here, not an exception thrown at the pipeline: the call
    continues and every question answers `temporarily_unavailable`.
    """

    tenant_id: UUID
    agent_id: UUID
    #: `None` exactly when `unavailable_reason` is set.
    pack: KnowledgePack | None = None
    index: LexicalIndex | None = None
    unavailable_reason: UnavailableReason | None = None
    #: The digest asked for, which is an id and therefore loggable, and which is present
    #: even on the failure path so an operator can find the object that did not load.
    requested_digest: str = ""

    @property
    def available(self) -> bool:
        return self.index is not None

    def search(self, question: str, *, k: int = DEFAULT_TOP_K) -> KnowledgeAnswer:
        """Answer one turn. Four states, never an exception, never a network call."""
        started = time.perf_counter()
        answer = self._search(question, k=k, started=started)
        _log_answer(self, answer)
        return answer

    def _search(self, question: str, *, k: int, started: float) -> KnowledgeAnswer:
        index = self.index
        if index is None:
            return KnowledgeAnswer("temporarily_unavailable", (), _elapsed_ms(started))
        forms = query_forms(question)
        if not forms:
            return KnowledgeAnswer("not_found", (), _elapsed_ms(started))

        scored = index.search(forms)
        # THE GATE (§4(b)'s trap in its one-armed form). Nothing the caller said carries
        # information about which entry to return, so there is no best match — there is an
        # absence, and `not_found` is what an absence is called.
        ranked = sorted(
            (
                (position, hit)
                for position, hit in scored.items()
                if hit.score > 0.0 and hit.informative
            ),
            key=lambda item: (-item[1].score, str(index.entries[item[0]].chunk_id)),
        )
        if not ranked:
            return KnowledgeAnswer("not_found", (), _elapsed_ms(started))

        top_position, top_hit = ranked[0]
        entries = index.entries
        if len(ranked) > 1:
            runner_position, runner_hit = ranked[1]
            different_document = (
                entries[runner_position].document_id != entries[top_position].document_id
            )
            margin = (top_hit.score - runner_hit.score) / top_hit.score
            if different_document and margin < AMBIGUITY_MARGIN:
                return KnowledgeAnswer(
                    "ambiguous",
                    tuple(
                        self._passage(entries[position], hit.score) for position, hit in ranked[:2]
                    ),
                    _elapsed_ms(started),
                )

        return KnowledgeAnswer(
            "found",
            tuple(self._passage(entries[position], hit.score) for position, hit in ranked[:k]),
            _elapsed_ms(started),
        )

    def _passage(self, entry: PackEntry, score: float) -> Passage:
        """The entry's OWN words, with provenance that traces back to published text.

        `text` and never `gloss`: the gloss is a retrieval key written for a lexical arm,
        not a sentence anybody approved for a caller to hear.

        The revision is MACHINE-READABLE, in `Provenance.document_version`, and not merely
        rendered into the label. A pack is frozen at publish, so this passage can name the
        exact words that were published when the answer was given — which is what a dispute
        asks for, and what a number inside a human sentence can only approximate. The field
        was added to the shared model for this (D-599); the first draft of this method put
        the revision in the label because it had nowhere else to go, and the label is where
        a person reads it rather than where a report queries it.
        """
        return Passage(
            text=entry.text,
            score=score,
            provenance=Provenance(
                label="published knowledge",
                tier="t3",
                agent_id=self.agent_id,
                source_id=entry.document_id,
                document_version=entry.document_version,
            ),
        )


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000.0)


def _log_answer(session: SessionKnowledge, answer: KnowledgeAnswer) -> None:
    """The ONLY log call on the query path, and the only one that could breach hard rule 6.

    It logs ids, counts, the outcome word and the elapsed time. It does NOT log the
    question, a passage, a gloss or a score-bearing excerpt — all four are conversation
    content, and "we only logged the top match" is still logging the transcript.
    """
    logger.info(
        "in-call knowledge lookup",
        tenant_id=str(session.tenant_id),
        agent_id=str(session.agent_id),
        digest=session.requested_digest,
        outcome=answer.outcome,
        passages=len(answer.passages),
        elapsed_ms=round(answer.elapsed_ms, 3),
        unavailable_reason=session.unavailable_reason,
    )


async def load_session_knowledge(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    content_sha256: str,
    fetcher: PackFetcher,
    cache: PackCache,
) -> SessionKnowledge:
    """Fetch (or reuse) one agent's pack and build its index. NEVER RAISES.

    Called once while the phone is ringing, which is wall clock nobody is waiting on. Every
    failure — the fetch, the parse, an unknown format version, an identity that disagrees —
    becomes a `SessionKnowledge` whose answers are `temporarily_unavailable`, because a
    conversation that dies because the knowledge base did not load is a worse outcome than
    one where the agent says it cannot verify something right now (hard rule 5's posture,
    extended to the client's facts — see the contract's `RetrievalOutcome` docstring).
    """
    held = cache.get(content_sha256, tenant_id=tenant_id, agent_id=agent_id)
    if held is not None:
        pack, index = held
        logger.info(
            "knowledge pack cache hit",
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            digest=content_sha256,
            entries=len(pack.entries),
        )
        return SessionKnowledge(
            tenant_id=tenant_id,
            agent_id=agent_id,
            pack=pack,
            index=index,
            requested_digest=content_sha256,
        )

    object_key = pack_object_key(tenant_id, agent_id, content_sha256)
    try:
        raw = await fetcher.fetch(object_key)
    # A fetch failure is a STATE, not a crash: broad on purpose, and narrowed nowhere,
    # because every way object storage can fail ends in the same answer to the caller.
    except Exception as exc:
        return _unavailable(tenant_id, agent_id, content_sha256, "fetch_failed", exc)
    if raw is None:
        return _unavailable(tenant_id, agent_id, content_sha256, "absent", None)

    try:
        pack = KnowledgePack.model_validate_json(raw)
    # Malformed bytes are an outage, not a crash. Same reasoning as the fetch above.
    except Exception as exc:
        return _unavailable(tenant_id, agent_id, content_sha256, "fetch_failed", exc)

    # A version we do not understand is REFUSED rather than parsed partially: an agent that
    # silently lost half its corpus cannot tell it is missing knowledge it thinks it has
    # (the contract's `PACK_FORMAT_VERSION` docstring).
    if pack.format_version != PACK_FORMAT_VERSION:
        return _unavailable(tenant_id, agent_id, content_sha256, "unsupported_format", None)

    # The bytes must be the pack we asked for and the pack must belong to this session.
    # Both are checked before anything is cached, so a wrong object can never become a warm
    # container's answer for the next caller.
    if pack.content_sha256 != content_sha256:
        return _unavailable(tenant_id, agent_id, content_sha256, "identity_mismatch", None)
    if pack.tenant_id != tenant_id or pack.agent_id != agent_id:
        return _unavailable(tenant_id, agent_id, content_sha256, "identity_mismatch", None)

    index = LexicalIndex(pack.entries)
    cache.put(pack, index)
    logger.info(
        "knowledge pack loaded",
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        digest=content_sha256,
        entries=len(pack.entries),
    )
    return SessionKnowledge(
        tenant_id=tenant_id,
        agent_id=agent_id,
        pack=pack,
        index=index,
        requested_digest=content_sha256,
    )


def _unavailable(
    tenant_id: UUID,
    agent_id: UUID,
    content_sha256: str,
    reason: UnavailableReason,
    exc: BaseException | None,
) -> SessionKnowledge:
    """One place builds the failure state, so one place decides what an outage logs.

    The exception TYPE is logged and its message is not: a fetch error can carry a signed
    URL or a response body, and neither belongs in a log this container ships.
    """
    logger.error(
        "knowledge pack unavailable",
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        digest=content_sha256,
        reason=reason,
        error_type=type(exc).__name__ if exc is not None else None,
    )
    return SessionKnowledge(
        tenant_id=tenant_id,
        agent_id=agent_id,
        unavailable_reason=reason,
        requested_digest=content_sha256,
    )


__all__ = [
    "AMBIGUITY_MARGIN",
    "BM25_B",
    "BM25_K1",
    "DEFAULT_TOP_K",
    "DF_GATE_MIN_ENTRIES",
    "MAX_CACHED_PACKS",
    "MAX_INFORMATIVE_DF_RATIO",
    "KnowledgeAnswer",
    "LexicalIndex",
    "PackCache",
    "PackFetcher",
    "SessionKnowledge",
    "UnavailableReason",
    "has_telugu_script",
    "load_session_knowledge",
    "query_forms",
    "transliterate_telugu",
]
