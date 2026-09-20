"""In-call knowledge search: one `KnowledgePack` in RAM, lexical first, dense on the misses.

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
* **transliterated** — produced only when the text contains a BRAHMIC script (see
  `INDIAN_SCRIPT_NAMES`); Perso-Arabic is detected and deliberately not transliterated, for
  the reason `transliterate_indic` records.

⚠ **TRANSLITERATION IS NOT TRANSLATION AND MUST NEVER BE DESCRIBED AS ONE.** It produces a
ROMANISED form of the SAME language: `డాక్టర్` becomes `ḍākṭar`, `डॉक्टर` becomes `ḍôkṭara`,
neither of which lexically matches an English gloss containing "doctor" and neither of which
was ever going to. What it buys is narrower and real — a query in an Indian script has ZERO
tokens in common with a Latin-script corpus, and after transliteration it has a chance of
matching the romanised words a code-mixed entry contains. It converts an impossible match
into a possible one; it does not translate.

**The reason the lexical arm works in production is different, and it is measured.** Saaras
returns **Tenglish** — Telugu grammar in Latin script, studded with English nouns
("Appointment ela book cheskovali?", `tests/fixtures/golden_transcripts.json`). Those nouns
are already Latin and already match the English gloss, with no transliteration involved.
Transliteration is the fallback for the Indian-script minority of turns, not the mechanism.

**NO LLM CALL, EVER, ON THIS PATH.** A translation hop mid-turn is a network round trip,
which is the single thing this design exists to avoid. A question we cannot resolve is
`ambiguous`, and the agent asks one clarifying question — which costs nothing and is what a
human receptionist does.

**IS IT WORTH KEEPING AT ALL? MEASURED, AND YES — BARELY, AND THAT IS THE HONEST ANSWER.**
`tests/in_call_retrieval_recall_test.py` scores a Telugu-script question against an
English-only index at **0.083 recall@1, 22 of 24 `not_found`**, which reads like a table of
dead code. It is not: ABLATING the transliterated form (the same harness, 14 Sep 2026, with
`transliterate_indic` replaced by the identity function) takes that row to **0.000 recall@1,
24 of 24 `not_found`**, while `query_en` (0.833) and `query_tenglish` (0.583) do not move at
all. So the form earns two facts out of twenty-four and costs nothing anywhere else, and the
CI floor of 0.04 in that file is a floor UNDER a live mechanism rather than over a corpse.
Two facts on a phone call are two callers who got an answer.

Those two are the shape the mechanism actually has: a proper noun or a loanword the corpus
spells in Latin the same way the romaniser spells it. That is why it is NOT worth nine
hand-written tables — and why it did not need them.

**ONE TABLE FOR NINE SCRIPTS, KEYED ON UNICODE'S OWN NAMES.** Every Brahmic script encodes
the same akshara inventory, and the Unicode character NAME says which akshara a codepoint
is, in a vocabulary that is identical across the blocks: U+0C15 is `TELUGU LETTER KA`,
U+0915 is `DEVANAGARI LETTER KA`, U+0B95 is `TAMIL LETTER KA`. So the table below is keyed
on the name ELEMENT (`KA`, `VOWEL SIGN AA`, `SIGN VIRAMA`) and the codepoints are looked up
from `unicodedata` — the standard library's copy of UnicodeData.txt — rather than typed.
Not one codepoint of any script is written out in this module, which is the point: a
hand-typed range or a hand-typed table is a claim about the outside world under hard rule
11, and this one derives itself from the authority instead.

Rejected: nine transliteration tables (nine claims nobody in this repo can verify, for a
mechanism worth 2/24 on the one script we measured); a transliteration dependency (hard
rule 9 — a new transitive tree for ~90 lines); and romanising straight from the name element
itself (`TELUGU LETTER TTA` → `tta`, where the corpus and the mark-folder both want `t` —
the element table is what converts Unicode's spelling into a matchable one).

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

## The SECOND arm, and the three sentences that decide when it runs

The paragraph above ("no network on the turn") was true of every turn until 14 Sep 2026 and
is now true of almost every turn, which is a different claim and is worth stating exactly.

**WHAT CHANGED IS A MEASUREMENT.** The founder ran `scripts/gemini_embedding_harness.py`
against the live Gemini API with their own key (14 Sep 2026, `models/gemini-embedding-001`,
3072 dimensions, n=24, English-only index — VENDOR-PUBLISHED, founder-relayed; `ai.google.dev`
is egress-blocked from this container and nothing here claims to have read it):

    query form        recall@1   recall@3   MRR        this module, same corpus
    query_en            0.9583     1.0000   0.9722     0.833
    query_tenglish      1.0000     1.0000   1.0000     0.583
    query_te            0.9583     1.0000   0.9792     **0.083, 22 of 24 `not_found`**

The Telugu-script row is the finding. Two hits in twenty-four becomes twenty-three, which is
not a better ranking of the same answers — it is the removal of the English-paraphrase
dependency this index has, and `docs/PIPECAT-MIGRATION.md` §9.4 records that dependency as
load-bearing ("if it ever stops, in-call retrieval does not degrade, it stops").

**THE PASSAGE VECTORS COST A CALL NOTHING, AND THAT IS THE WHOLE DESIGN.** They are computed
at PUBLISH by `apps/api/kb/pack_vectors.py` and travel inside the pack, so the corpus side of
the dense arm is already in this process's memory by the time the phone is answered. What is
left on the call path is ONE query vector.

**IT FIRES ONLY ON `not_found` AND `ambiguous`, AND THOSE WORDS ARE THE TRIGGER BECAUSE THEY
ARE ALREADY THE ANSWER.** The gate above computes them before any of this: `not_found` means
nothing the caller said is informative about this corpus, `ambiguous` means two documents
scored the same. Both are turns on which the agent was about to tell the caller it has
nothing useful — so the second arm is spent only where the first already lost, and the ~0.5 ms
`found` path is byte-for-byte what it was. A hybrid that fused on every turn would spend a
network round trip on the 83% of English questions the lexical arm answers correctly, and
§4(b) of the evidence file is the measurement that unconditional fusion makes cells WORSE.

**IT CAN ONLY ADD, NEVER SUBTRACT.** A dense pass that clears `DENSE_MIN_COSINE` replaces the
answer; one that does not leaves the lexical answer exactly as it stood. So the cost of that
threshold being set too HIGH is today's behaviour, and the cost of the arm being absent, off,
unpriced or broken is also today's behaviour. There is no configuration of this module in
which adding the arm made an answer worse than the one before it.

**AND IT IS HONEST ABOUT ITS OWN FAILURE.** Once we have decided to consult a second arm we
have said, in code, that the lexical answer is not authoritative for this question. If the
embedder then times out, `not_found` would be asserting "this business publishes nothing
about that" on the strength of an arm we had just declined to trust. So a failed dense pass
answers `temporarily_unavailable` — "we could not look" — which is the distinction
`RetrievalOutcome` exists for, and it is why `QueryEmbedder.embed` returns `None` rather
than raising.

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
import sys
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Final, Literal, Protocol
from uuid import UUID

from calevate_shared.knowledge_pack import (
    SUPPORTED_PACK_FORMAT_VERSIONS,
    KnowledgePack,
    PackEntry,
    RetrievalOutcome,
    decode_vector,
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
#: ⚠ **A STARTING POINT TO BE MEASURED ON REAL CALLS.** Nobody has run this
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
#: ⚠ **A STARTING POINT TO BE MEASURED ON REAL CALLS.** The reasoning it
#: encodes is only this: two entries from DIFFERENT documents scoring within a few percent
#: of each other is the shape of a question that named a category rather than a thing
#: ("what are your charges?" against a pack with consultation, scan and procedure fees),
#: and guessing between them on a phone call is worse than asking which one. Entries from
#: the SAME document do not trigger it — they are two spans of one answer, not two answers.
AMBIGUITY_MARGIN: Final[float] = 0.15

#: How many competing entries an `ambiguous` answer hands back, and therefore how many
#: alternatives the agent has to offer the caller.
#:
#: TWO, because the clarifying question has to be SPOKEN. An either/or a caller can hold in
#: their head is a question; a third option makes it a list they have to remember while it
#: is still being read, which is the shape `VOICE_STYLE_GUIDANCE` tells every agent not to
#: speak. It is also all the state has: the margin rule that produces `ambiguous` compares
#: the top entry against the runner-up and nothing further down.
AMBIGUOUS_CANDIDATES: Final[int] = 2

#: Passages returned on a `found`. TRD §6's in-call number, which is also
#: `calevate_shared.retrieval.RetrievalRequest.k`'s default — the one k in this repo that
#: was chosen rather than picked.
DEFAULT_TOP_K: Final[int] = 3

#: How many distinct packs one warm container keeps. A pack is kilobytes, and a container
#: serves one session at a time, so this is a bound against unbounded growth across a long-
#: lived instance rather than a working-set estimate. Pipecat Cloud's documented maximum
#: pool size is 50 CONTAINERS, which is not a number of packs and is not this number.
MAX_CACHED_PACKS: Final[int] = 8

#: How close a passage vector must be to the question's, as a cosine, before the DENSE arm is
#: allowed to overrule what the lexical arm said.
#:
#: ⚠ **A STARTING POINT TO BE MEASURED, AND UNLIKE ITS THREE NEIGHBOURS ABOVE IT CANNOT BE
#: DERIVED FROM THE MEASUREMENT THAT MOTIVATED IT.** The founder's harness reports RANKS —
#: recall@1, recall@3, MRR — and prints no similarity SCORES at all, so nothing in this
#: repository says where a matching passage sits on this model's cosine scale or where an
#: unrelated one does. Inventing a number and presenting it as the model's separation point
#: would be exactly the laundering hard rule 11 forbids, so this is 0.5 — the midpoint of the
#: range a same-direction cosine occupies — chosen to be argued with rather than believed.
#: What replaces this comment is a harness run that prints the score distribution for a
#: matching and a deliberately unrelated query on a real corpus.
#:
#: **WHAT MAKES AN UNMEASURED NUMBER SAFE HERE IS THE DIRECTION OF ITS TWO FAILURES, AND THAT
#: IS A PROPERTY OF THE DESIGN RATHER THAN OF THE VALUE.** Too HIGH: the dense arm declines,
#: the lexical answer stands, and the caller gets precisely what they get today. Too LOW: the
#: nearest passage in a corpus that has nothing to say is presented as an answer — which is
#: the trap the lexical gate exists for, repeated on the other arm. So the conservative side
#: is UP, and this sits on it. `_dense_pass` can only ever REPLACE a `not_found` or an
#: `ambiguous`; it is never consulted on a `found` and can never turn one into anything else.
DENSE_MIN_COSINE: Final[float] = 0.5

#: The lexical outcomes that DO reach the dense arm — the trigger, stated as data so that a
#: test can assert the set rather than re-derive it from a branch.
#:
#: `found` is absent because the fast path is the product: a network round trip on a turn the
#: index already answered correctly would spend a second of a caller's time to re-confirm
#: 83% of English questions (`docs/PIPECAT-MIGRATION.md` §9.4), which is the unconditional
#: fusion §4(b) measured going backwards. `temporarily_unavailable` is absent because it
#: means there is no pack in memory at all — there is nothing for a query vector to be
#: compared against, so buying one would be money spent on an empty corpus.
_DENSE_TRIGGERS: Final[frozenset[str]] = frozenset({"not_found", "ambiguous"})

#: Why a pack could not be loaded. Each is an OPERATOR-facing word: the caller only ever
#: hears the agent say it cannot verify something right now.
UnavailableReason = Literal["fetch_failed", "absent", "unsupported_format", "identity_mismatch"]


# ---------------------------------------------------------------------------------------
# Script detection and romanisation. ONE element table, nine scripts, zero typed codepoints.
# ---------------------------------------------------------------------------------------

#: The Unicode scripts the languages our speech vendors process are written in, spelled as
#: the first word of `unicodedata.name()` for every codepoint in them. That spelling is the
#: lookup key AND the detector: `unicodedata` is the standard library's copy of
#: UnicodeData.txt, so nothing here is a range somebody remembered.
#:
#: The list is derived from the VENDOR's own tables in the installed
#: pipecat 1.10.0 (`pipecat-ai==1.10.0`, `.venv/lib/python3.12/site-packages/pipecat/`):
#:
#:   * STT, `services/sarvam/stt.py:801-826` — `SUPPORTED_LANGUAGES` for
#:     `saaras:v3-realtime` holds 24 entries: `auto` plus 23 languages (as, bn, brx, doi,
#:     en, gu, hi, kn, kok, ks, mai, ml, mni, mr, ne, or, pa, sa, sat, sd, ta, te, ur).
#:   * TTS, `services/sarvam/tts.py:218-242` — 11 India locales, a SUBSET of the above.
#:
#: ⚠ **THE LANGUAGE LIST IS THE VENDOR FACT; WHICH SCRIPT EACH LANGUAGE IS WRITTEN IN IS
#: NOT** — the per-entry comments below are general knowledge, read from no source (hard
#: rule 11). Nothing depends on that mapping being right or exhaustive: detection reads the
#: SCRIPT of the text in front of it, so a language written in a script this set does not
#: name simply scores its Latin tokens and is answered honestly. The comments are a
#: reader's aid; the set is the contract.
#:
#: ⚠ **THE TWO FILES SPELL ODIA DIFFERENTLY AND NEITHER SPELLING IS A SCRIPT NAME.** STT's
#: `SUPPORTED_LANGUAGES` says `or-IN` (`stt.py:809`) while both its own enum map
#: (`stt.py:86`) and TTS (`tts.py:234-235`) say `od-IN`. It does not reach this module —
#: what we key on is the SCRIPT, whose Unicode name is `ORIYA` — and it is recorded because
#: a caller who round-trips a locale code between those two tables will hit it.
#:
#: **THE SCRIPTS OF `sat-IN` AND `mni-IN` ARE DELIBERATELY ABSENT, AND THAT IS A STATED GAP
#: RATHER THAN AN OVERSIGHT.** Neither is named here, so a question written in one is not
#: detected, scores whatever Latin tokens it contains, and is answered `not_found` rather
#: than wrongly — the same outcome a Perso-Arabic question gets, and the right one. Adding a
#: script is adding its name to this set; adding its ROMANISATION is adding name elements to
#: the tables below, and neither is done on a guess about a script nobody here can read.
INDIAN_SCRIPT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "BENGALI",  # bn-IN, as-IN
        "DEVANAGARI",  # hi-IN, mr-IN, mai-IN, kok-IN, ne-IN, sa-IN, brx-IN, doi-IN
        "GUJARATI",  # gu-IN
        "GURMUKHI",  # pa-IN
        "KANNADA",  # kn-IN
        "MALAYALAM",  # ml-IN
        "ORIYA",  # or-IN / od-IN
        "TAMIL",  # ta-IN
        "TELUGU",  # te-IN
        "ARABIC",  # ur-IN, sd-IN, ks-IN — DETECTED, not romanised. See below.
    }
)

#: The subset that is an ABUGIDA and therefore romanisable by the one algorithm in
#: `transliterate_indic`: a consonant carries an inherent vowel, a vowel sign replaces it,
#: a virama removes it.
#:
#: **PERSO-ARABIC IS OUT ON PURPOSE AND THE REASON IS NOT EFFORT.** It is an abjad: Urdu and
#: Sindhi do not write short vowels, so `کلینک` romanises to the consonant skeleton `klnk`
#: — which is not the spelling any corpus in this repo uses and matches nothing, while
#: looking exactly like a word to the next reader. Transliteration's only measured payoff is
#: a loanword the corpus happens to spell the same way (see the module docstring's 2-of-24),
#: and a skeleton cannot collect it. Detection still covers Urdu and Sindhi: the question
#: tokenises, scores its Latin terms and is answered honestly.
_BRAHMIC_SCRIPT_NAMES: Final[frozenset[str]] = INDIAN_SCRIPT_NAMES - {"ARABIC"}

# `fmt: off` around the tables below: these are GRIDS, and the formatter's magic-trailing-
# comma rule would explode them to one entry per line. A romanisation table read one row
# per akshara is unreviewable; read as a grid it is checkable against a chart.
# fmt: off
#: Name element → vowel, for BOTH `<SCRIPT> LETTER <E>` (independent) and
#: `<SCRIPT> VOWEL SIGN <E>` (dependent). Unicode uses one element vocabulary for both, and
#: so does this table; what differs is what the algorithm does with the inherent vowel.
#: ISO 15919 values, because the mark-folded form (`_fold_latin_marks`) reduces them to the
#: bare Latin letter a code-mixed corpus actually writes: `ā`→`a`, `ē`→`e`, `r̥`→`r`.
_VOWEL_ELEMENTS: Final[dict[str, str]] = {
    "A": "a", "AA": "ā", "I": "i", "II": "ī", "ARCHAIC II": "ī",
    "U": "u", "UU": "ū", "UE": "u", "UUE": "ū",
    "VOCALIC R": "r̥", "VOCALIC RR": "r̥̄", "VOCALIC L": "l̥", "VOCALIC LL": "l̥̄",
    "E": "e", "EE": "ē", "AI": "ai", "AY": "ai",
    "O": "o", "OO": "ō", "AU": "au", "AW": "au", "OE": "o", "OOE": "ō",
    "SHORT A": "a", "SHORT E": "e", "SHORT O": "o",
    "CANDRA A": "ê", "CANDRA E": "ê", "CANDRA O": "ô", "CANDRA LONG E": "ê",
    "PRISHTHAMATRA E": "e",
}
# fmt: on

# fmt: off
#: Name element → consonant WITHOUT its inherent vowel. The algorithm adds the `a`.
#:
#: The retroflex/dental distinction is Unicode's doubled-letter convention (`TTA` is ట/ट/ட,
#: `TA` is త/त/த), and it is kept as ISO's underdot rather than flattened here, because the
#: mark fold flattens it downstream and the unfolded form is the one that matches a corpus
#: romanised WITH diacritics.
_CONSONANT_ELEMENTS: Final[dict[str, str]] = {
    "KA": "k", "KHA": "kh", "GA": "g", "GHA": "gh", "NGA": "ṅ",
    "CA": "c", "CHA": "ch", "JA": "j", "JHA": "jh", "NYA": "ñ",
    "TTA": "ṭ", "TTHA": "ṭh", "DDA": "ḍ", "DDHA": "ḍh", "NNA": "ṇ",
    "TA": "t", "THA": "th", "DA": "d", "DHA": "dh", "NA": "n",
    "PA": "p", "PHA": "ph", "BA": "b", "BHA": "bh", "MA": "m",
    "YA": "y", "RA": "r", "RRA": "ṟ", "LA": "l", "LLA": "ḷ", "LLLA": "ḻ",
    "VA": "v", "SHA": "ś", "SSA": "ṣ", "SA": "s", "HA": "h",
    # Tamil and Malayalam extras: the alveolar nasal, the alveolar stop, the alveolar rhotic.
    "NNNA": "ṉ", "TTTA": "ṯ", "RRRA": "ṟ",
    # Assamese, which Unicode encodes as two Bengali letters of its own (bn-IN/as-IN share
    # the block): ৰ is Assamese `ra` and ৱ is Assamese `wa`.
    "RA WITH MIDDLE DIAGONAL": "r", "RA WITH LOWER DIAGONAL": "w", "WA": "w",
    # Perso-Arabic borrowings written in Devanagari and Gurmukhi — Urdu and Sindhi words as
    # Hindi and Punjabi spell them.
    "QA": "q", "KHHA": "kh", "GHHA": "gh", "ZA": "z", "FA": "f", "ZHA": "zh",
    "RHA": "ṛh", "DDDHA": "ṛ", "YYA": "y",
    # Sindhi implosives and the affricates Telugu writes for Marathi loans.
    "GGA": "g", "JJA": "j", "BBA": "b", "DDDA": "d", "MARWARI DDA": "ḍ",
    "DZA": "dz", "TSA": "ts", "HEAVY YA": "y",
}
# fmt: on

# fmt: off
#: Consonants that carry NO inherent vowel: Malayalam's chillu letters and the Bengali
#: khanda ta are, by definition, a consonant at the end of a syllable. Emitting the `a`
#: would turn `മലയാളം`-final `ൻ` into `na` and lengthen every word that ends in one.
_DEAD_CONSONANT_ELEMENTS: Final[dict[str, str]] = {
    "CHILLU K": "k", "CHILLU L": "l", "CHILLU LL": "ḷ", "CHILLU LLL": "ḻ",
    "CHILLU M": "m", "CHILLU N": "n", "CHILLU NN": "ṇ", "CHILLU RR": "ṟ",
    "CHILLU Y": "y", "KHANDA TA": "t",
    # Telugu/Kannada nakaara pollu and Malayalam dot reph: the same idea under other names,
    # a syllable-final nasal and a syllable-final rhotic.
    "NAKAARA POLLU": "n", "DOT REPH": "r",
}
# fmt: on

#: Name element (the WHOLE rest of the name, not a suffix) → romanisation, for the marks
#: that are neither a consonant nor a vowel.
#:
#: ⚠ ANUSVARA IS ROMANISED `n`, NOT ISO 15919's `ṁ`, AND THAT IS A DELIBERATE DEPARTURE FROM
#: THE STANDARD. The output of this function is never shown to anybody — it exists only to
#: be matched lexically against a corpus that code-mixing speakers wrote, and they write the
#: nasal as `n` ("undi", "bangaram", "Bengaluru"). `ṁ` is the correct scholarly romanisation
#: and matches nothing. Gurmukhi's bindi, adak bindi and tippi are the same nasal by other
#: names, and Devanagari's candrabindu likewise.
_SIGN_ELEMENTS: Final[dict[str, str]] = {
    "SIGN ANUSVARA": "n",
    "SIGN CANDRABINDU": "n",
    "SIGN BINDI": "n",
    "SIGN ADAK BINDI": "n",
    "TIPPI": "n",
    "SIGN VISARGA": "h",
    # Gemination (Gurmukhi addak) and the elided-vowel mark: written, but not a sound this
    # romanisation can spell without lookahead, and silence matches better than a guess.
    "ADDAK": "",
    "SIGN AVAGRAHA": "",
}


def _nukta_compositions() -> dict[str, str]:
    """Base consonant → the PRECOMPOSED letter that base-plus-nukta spells, DERIVED.

    **THE BUG THIS EXISTS TO FIX, FOUND BY ADDING A SECOND SCRIPT (D-612).** A nukta is a
    dot under a consonant that makes it a DIFFERENT consonant — Devanagari `ज`+nukta is
    `ज़` /z/, `फ`+nukta is `फ़` /f/, `ड`+nukta is `ड़` /ɽ/ — and Unicode spells each of
    those two ways: one precomposed codepoint (U+095B ZA) and the base-plus-mark sequence.
    A walk that skips past the mark and keeps the BASE's romanisation gives `दफ़्तर` →
    `daphtara` instead of `daftara` and `काग़ज़` → `kāgaja` instead of `kāgaza`, while the
    PRECOMPOSED spelling of the same word romanises correctly — one character, two Unicode
    spellings, two answers.

    ⚠ **THE SEQUENCE SPELLING IS THE ONE REAL TEXT CARRIES.** U+0958..U+095F are on
    Unicode's composition-exclusion list, so NFC does NOT compose them: normalising Hindi
    leaves the base-plus-mark sequence standing, and `query_forms` NFKC-normalises before it
    tokenises. Handling only the precomposed branch gets the rare case right.

    Telugu has no nukta, which is why a Telugu-only corpus never touched this. The scripts
    that do — Devanagari, Bengali, Gurmukhi, Oriya — are four of the ten in
    `INDIAN_SCRIPT_NAMES`, so this was a generalisation the one-table design asserted and
    had never been asked to keep.

    DERIVED FROM UNICODE'S OWN CANONICAL DECOMPOSITIONS, never typed: a letter belongs here
    exactly when the standard says it decomposes to a base plus a mark whose name ends in
    NUKTA. Twenty-five entries on Unicode 15.0 across five scripts — the fifth is Kaithi,
    which `_classify` does not cover and which therefore still falls through unchanged.
    A typed table would be a claim about Unicode; this one reads it (hard rule 11).

    **COST: ~155ms, ONCE, AT IMPORT** (measured 15 Sep 2026, CPython 3.12.3 / unidata
    15.0.0), for the same reason `_combining_mark_ranges` pays ~102ms there: a container
    start is not a turn. Deferring it behind an `lru_cache` was rejected — it moves the
    scan onto the FIRST TURN CONTAINING A NUKTA, i.e. 155ms inside a 350ms TTFT budget, on
    a live call, and only ever for callers in the four scripts that have one. Merging it
    into the mark scan was measured and saves nothing (~281ms in one pass against ~257ms in
    two): `unicodedata.decomposition`, not the loop, is what costs.
    """
    compositions: dict[str, str] = {}
    for codepoint in range(sys.maxunicode + 1):
        composed = chr(codepoint)
        decomposition = unicodedata.decomposition(composed)
        # A `<compat>`-tagged decomposition is a different character, not a spelling of it.
        if not decomposition or "<" in decomposition:
            continue
        parts = decomposition.split()
        if len(parts) != 2:
            continue
        base, mark = (chr(int(part, 16)) for part in parts)
        if unicodedata.name(mark, "").endswith("NUKTA"):
            compositions[base] = composed
    return compositions


#: Built at IMPORT, not on first use — see the function's docstring for the 155ms and for
#: why a lazy cache would spend it on somebody's phone call instead.
_NUKTA_COMPOSITIONS: Final[Mapping[str, str]] = _nukta_compositions()


#: What one codepoint does to the romanisation in progress. A closed set, so the walk in
#: `transliterate_indic` is a dispatch rather than a chain of membership tests.
_Akshara = Literal["consonant", "dead_consonant", "standalone", "vowel_sign", "virama", "nukta"]

_INHERENT_VOWEL: Final[str] = "a"


def _script_of(ch: str) -> str | None:
    """Which of `INDIAN_SCRIPT_NAMES` `ch` belongs to, by its Unicode NAME, else `None`.

    The ASCII short-circuit is not premature optimisation: the overwhelming majority of
    characters this module ever sees are ASCII (§9.1 step 2 hands this index an English
    query), and `unicodedata.name` is a table lookup we can skip for all of them.
    """
    if ch.isascii():
        return None
    head = unicodedata.name(ch, "").partition(" ")[0]
    return head if head in INDIAN_SCRIPT_NAMES else None


@lru_cache(maxsize=4096)
def _classify(ch: str) -> tuple[_Akshara, str] | None:
    """One codepoint's romanisation role, derived from `unicodedata.name()`.

    `None` means "not a Brahmic character this table knows", and the caller passes it
    through untouched — a Latin letter, a digit, a space, a Perso-Arabic letter, or an
    akshara of a script the element tables do not cover all take that path.

    Cached because a phone conversation reuses a small alphabet many times over, and the
    cache is bounded because unbounded is a leak (`MAX_CACHED_PACKS` has the same reasoning
    one layer up). 4096 is several times the combined repertoire of the nine scripts.
    """
    script = _script_of(ch)
    if script is None or script not in _BRAHMIC_SCRIPT_NAMES:
        return None
    element = unicodedata.name(ch, "").partition(" ")[2]
    if element in _SIGN_ELEMENTS:
        return ("standalone", _SIGN_ELEMENTS[element])
    if element.endswith("VIRAMA"):
        # Malayalam spells its own two ("circular", "vertical bar") alongside the plain one,
        # and all three do the same thing to the inherent vowel.
        return ("virama", "")
    if element.endswith("NUKTA"):
        return ("nukta", "")
    letter = element.removeprefix("LETTER ") if element.startswith("LETTER ") else None
    if letter is not None:
        if letter in _CONSONANT_ELEMENTS:
            return ("consonant", _CONSONANT_ELEMENTS[letter])
        if letter in _DEAD_CONSONANT_ELEMENTS:
            return ("dead_consonant", _DEAD_CONSONANT_ELEMENTS[letter])
        if letter in _VOWEL_ELEMENTS:
            return ("standalone", _VOWEL_ELEMENTS[letter])
        return None
    if element.startswith("VOWEL SIGN "):
        sign = _VOWEL_ELEMENTS.get(element.removeprefix("VOWEL SIGN "))
        return None if sign is None else ("vowel_sign", sign)
    if element.startswith("DIGIT "):
        # `unicodedata.digit` rather than a ten-row table per script, so "౧౦ గంటలు" and
        # "१० बजे" both tokenise as the ASCII digits an English corpus spells.
        digit = unicodedata.digit(ch, None)
        return None if digit is None else ("standalone", str(digit))
    return None


def indian_scripts_in(text: str) -> frozenset[str]:
    """Which of `INDIAN_SCRIPT_NAMES` occur in `text`. Empty for pure Latin.

    A SET rather than a bool because "which script" is the question a caller mixing two of
    them asks, and because a test can then assert a script by name instead of asserting that
    something non-Latin was noticed.
    """
    return frozenset(script for script in (_script_of(ch) for ch in text) if script is not None)


def has_indian_script(text: str) -> bool:
    """Is any of `text` written in a script one of our vendors' Indian languages uses?"""
    return any(_script_of(ch) is not None for ch in text)


def transliterate_indic(text: str) -> str:
    """Brahmic script → the SAME language romanised. Deterministic, table-driven, no model.

    ⚠ **This is not a translation.** `డాక్టర్` → `ḍākṭar` and `डॉक्टर` → `ḍôkṭara`, neither
    of which will match an English gloss saying "doctor". See the module docstring for what
    it does buy, and for the ablation that says the buy is real but small.

    **THE TRAILING `a` IN `ḍôkṭara` IS CORRECT HERE AND IS NOT A BUG TO BE FIXED.** Hindi
    deletes that final schwa in speech and Devanagari does not write the virama for it, so a
    faithful romanisation keeps it. Deleting it would take a SCHWA-DELETION RULE, which is a
    property of the LANGUAGE (Hindi and Bengali delete it, Marathi partly, Telugu and Tamil
    never) and not of the script — and the script is all this module can see. Guessing the
    language from the script would be wrong for Marathi in the same block as Hindi, and the
    two facts this form is worth do not pay for it (see the module docstring's ablation).

    Characters this table does not know — Latin, Perso-Arabic, punctuation, an akshara of a
    script we do not cover — pass through untouched, so a code-mixed sentence with a few
    Indic words in it comes out wholly Latin rather than half-transliterated.

    The algorithm is the abugida rule and nothing else: a consonant carries an inherent `a`
    which the NEXT character either replaces (a vowel sign), removes (a virama) or leaves
    standing (anything else, including end of text).
    """
    out: list[str] = []
    pending_consonant = False
    previous: str | None = None
    for ch in text:
        classified = _classify(ch)
        if classified is None:
            if pending_consonant:
                out.append(_INHERENT_VOWEL)
                pending_consonant = False
            out.append(ch)
            previous = ch
            continue
        kind, roman = classified
        if kind == "consonant":
            if pending_consonant:
                out.append(_INHERENT_VOWEL)
            out.append(roman)
            pending_consonant = True
        elif kind == "dead_consonant":
            if pending_consonant:
                out.append(_INHERENT_VOWEL)
            out.append(roman)
            pending_consonant = False
        elif kind == "vowel_sign":
            # The sign supplies the vowel, so the inherent one is never emitted.
            out.append(roman)
            pending_consonant = False
        elif kind == "virama":
            # Bare consonant: drop the inherent vowel entirely. This is what makes `డాక్టర్`
            # come out as `ḍākṭar` rather than `ḍākaṭara`.
            pending_consonant = False
        elif kind == "nukta":
            # A nukta REPLACES the consonant already emitted with a different one (`ज` +
            # nukta = `ज़`, `ja` → `za`), so the character that was just written is rewritten
            # rather than the mark being dropped — see `_nukta_compositions` for the bug that
            # dropping it was. It still must NOT close the syllable: the inherent vowel is
            # pending behind it either way. A base with no composed form (a script
            # `_classify` does not cover, or a nukta after something that is not a letter)
            # keeps the old behaviour and passes through.
            composed = _NUKTA_COMPOSITIONS.get(previous or "")
            reclassified = _classify(composed) if composed is not None else None
            if reclassified is not None and out:
                out[-1] = reclassified[1]
                pending_consonant = reclassified[0] == "consonant"
            previous = ch
            continue
        else:  # "standalone": an independent vowel, a digit, an anusvara, a visarga.
            if pending_consonant:
                out.append(_INHERENT_VOWEL)
                pending_consonant = False
            out.append(roman)
        previous = ch
    if pending_consonant:
        out.append(_INHERENT_VOWEL)
    return "".join(out)


#: Unicode general categories of a COMBINING MARK: non-spacing, spacing-combining,
#: enclosing. Every Indian script's vowel signs, viramas, nuktas and anusvaras are one of
#: these, and so are the Latin marks `transliterate_indic` emits (`r̥`, `ā`).
_MARK_CATEGORIES: Final[frozenset[str]] = frozenset({"Mc", "Me", "Mn"})


def _combining_mark_ranges() -> str:
    r"""Every combining mark Unicode has, as a regex character class, DERIVED not typed.

    A token has to continue across marks: a plain `\w+` splits Telugu `ఆరోగ్యశ్రీ` into four
    fragments at the vowel signs and Devanagari `अपॉइंटमेंट` into five, because `\w` is
    alphanumeric and a vowel sign is category Mc. Python's `re` has no `\p{M}`, so the class
    has to be enumerated — and enumerating it from `unicodedata.category` is the difference
    between a fact and a recollection (hard rule 11: a range typed from memory is a claim
    about Unicode, and this one reads the standard library's own table).

    **EVERY PLANE, NOT JUST THE BMP, AND THE 96ms DIFFERENCE IS THE CHEAPEST THING IN THIS
    FILE.** The first draft scanned U+0000..U+FFFF (5.8ms) on the premise that no script we
    cover keeps a combining mark above it. That premise was TRUE on Python 3.11's Unicode
    14.0 and FALSE on the Unicode 15.0 this repo runs, which added the Arabic Extended-C
    marks at U+10EFC..U+10EFF — so the cheap scan silently stopped covering Urdu and Sindhi
    between two interpreter versions, with no error anywhere. A full scan costs ~102ms
    against ~6ms (measured 14 Sep 2026, CPython 3.12.3 / unidata 15.0.0), once at IMPORT —
    a container start, never a turn, and this module is imported beside `pipecat` — and it
    has no premise in it at all. A hundred milliseconds of cold start is worth more than a
    claim about Unicode that a patch release can quietly falsify.
    """
    marks = [
        cp for cp in range(sys.maxunicode + 1) if unicodedata.category(chr(cp)) in _MARK_CATEGORIES
    ]
    spans: list[tuple[int, int]] = []
    for cp in marks:
        if spans and cp == spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], cp)
        else:
            spans.append((cp, cp))
    # `\U` with EIGHT digits for every codepoint, never `\u` with four. A five-digit `\u`
    # escape does not fail — `re` reads the first four and treats the fifth as a literal, so
    # `\u1D165-\u1D169` silently becomes the RANGE `5` to `U+1D16`, which swallows `?`, `a`
    # and most of ASCII. The class then matched every character and the tokeniser stopped
    # splitting on punctuation at all. Nothing raised; one unrelated assertion caught it.
    return "".join(
        f"\\U{low:08X}" if low == high else f"\\U{low:08X}-\\U{high:08X}" for low, high in spans
    )


#: A token starts with an alphanumeric and may continue with combining marks as well, so an
#: akshara cluster and a romanisation carrying diacritics are each ONE token.
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    rf"[^\W_](?:[^\W_]|[{_combining_mark_ranges()}])*", re.UNICODE
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
#:
#: ⚠ **IT IS ENGLISH + TENGLISH ONLY, DELIBERATELY.** Romanised Hindi `hai`/`kya`, Tamil `enna`
#: and their nine cousins are absent, so they reach the gate as content words. That is the
#: SAFE side of this list's own stated bias: an unlisted function word can only fail to
#: match a corpus that does not contain it, while a wrongly listed one deletes a question
#: the agent could have answered. Filling it in would take the thing every other line here
#: has and this one would not — a recording of a real call in that language. It is a
#: measurement to take, not a list to guess.
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


def _fold_latin_marks(text: str) -> str:
    """Strip combining marks, but ONLY where the base character is Latin.

    `ḍākṭar` → `dakțar`-without-marks → `daktar`, so a corpus that romanised without
    diacritics still matches. Applying the same fold to an Indian script would delete the
    vowel signs — Telugu `కాలం` would become `కలం` and Devanagari `काम` would become `कम`,
    different words in both — so the base character decides, script by script and for every
    script at once.
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
    # Brahmic only: `transliterate_indic` is the identity on Perso-Arabic (and on Latin),
    # so building the form for an Urdu question would cost a walk to produce a duplicate the
    # de-duplication below would drop anyway.
    if indian_scripts_in(question) - {"ARABIC"}:
        candidates.append(_tokenise(transliterate_indic(question), fold_marks=True))
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


class DenseIndex:
    """Cosine over the passage vectors the pack already carries. No model, no network, no
    vendor — the encoder ran at publish, and what is left here is arithmetic.

    **UNIT VECTORS ARE STORED, NOT RAW ONES.** Cosine is a dot product divided by two norms;
    the passage norms are the same on every turn of every call, so dividing them out ONCE at
    load turns each of the thousands of per-turn similarity computations into a bare dot
    product. That is the standard move in every vector store and it is taken here for the
    standard reason.

    **`math.sumprod` RATHER THAN A PYTHON LOOP OR A NEW DEPENDENCY.** It is C-implemented and
    stdlib from 3.12, which this workspace pins (`requires-python = ">=3.12,<3.13"`). The
    alternative — `numpy` — is installed transitively under `onnxruntime` but is NOT declared
    by `apps/voice-worker/pyproject.toml`, and importing an undeclared transitive dependency
    into a latency-critical container is how a resolver change becomes an outage. A hand
    written `sum(a * b for ...)` over 3072 floats is the third option and is the slow one.

    A zero vector is dropped at construction rather than divided by: it has no direction, so
    its cosine against anything is undefined, and an entry with one is simply unreachable by
    this arm — the state the format already has for an entry with no vector at all.
    """

    __slots__ = ("_dimensions", "_model", "_units")

    def __init__(self, pack: KnowledgePack) -> None:
        self._model: str | None = pack.embedding_model
        self._dimensions: int | None = pack.embedding_dimensions
        #: position in `pack.entries` → that entry's unit vector.
        self._units: dict[int, tuple[float, ...]] = {}
        if self._dimensions is None:
            return
        for position, entry in enumerate(pack.entries):
            if entry.vector_f32_b64 is None:
                continue
            values = decode_vector(entry.vector_f32_b64, dimensions=self._dimensions)
            if values is None:
                continue
            unit = _unit(values)
            if unit is not None:
                self._units[position] = unit

    def __len__(self) -> int:
        return len(self._units)

    @property
    def model(self) -> str | None:
        """Which encoder produced these vectors, or `None` when there are none to compare."""
        return self._model

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    def usable_with(self, *, model: str, dimensions: int) -> bool:
        """May a query vector from THIS encoder be compared against these passages?

        **A MISMATCH IS REFUSED RATHER THAN TOLERATED, AND THE REASON IS THAT IT DOES NOT
        RAISE.** Two encoders' vectors of the same width are both just 3072 floats: a dot
        product between them computes happily and means nothing, so a pack embedded under
        last month's model and a worker configured with this month's would produce a dense
        arm that ranks confidently and wrongly, with no error anywhere and nothing in a log.
        The width is checked too, because a mismatch there is the same failure one layer down.
        """
        return bool(self._units) and self._model == model and self._dimensions == dimensions

    def search(self, query: tuple[float, ...]) -> list[tuple[int, float]]:
        """Every passage with a usable vector, as (position, cosine), best first.

        Ties broken by POSITION rather than left to `sort`'s stability over a dict iteration
        order, so two passages at the same distance rank the same way on every call — the
        `str(chunk_id)` tie-break the lexical arm uses, one field cheaper because position is
        already the pack's canonical `chunk_id` order (`KnowledgePack.digest` sorts by it and
        `kb/pack.read_entries` stores it that way).
        """
        unit = _unit(query)
        if unit is None:
            return []
        scored = [
            (position, math.sumprod(unit, values)) for position, values in self._units.items()
        ]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored


def _unit(values: tuple[float, ...]) -> tuple[float, ...] | None:
    """`values` scaled to length 1, or `None` for the zero vector, which has no direction."""
    norm = math.sqrt(math.sumprod(values, values))
    if norm == 0.0:
        return None
    return tuple(value / norm for value in values)


@dataclass(frozen=True, slots=True)
class QueryVector:
    """One bought query vector and what it cost, as a QUANTITY rather than a rupee figure.

    `tokens` is the vendor's own reported usage and `None` where it reported none. It is
    carried rather than dropped because hard rule 7 needs the quantity at the point of
    purchase: the PRICE is `apps/api/billing/rates.llm_inr_per_ktok`'s, from an operator
    attestation, in a process this container deliberately cannot reach (`storage.py` argues
    why). A token count re-derived downstream from a character length would be a second and
    wrong answer to a question the vendor already answered.

    It lives HERE and not in `embedding.py` so that this module stays free of `httpx` and of
    every other import the production embedder needs — the same reason `PackFetcher` is a
    Protocol here and `ObjectStorePackFetcher` is a class over there.
    """

    values: tuple[float, ...]
    tokens: int | None = None


class QueryEmbedder(Protocol):
    """The second seam to the outside world: a question in, a vector or `None` out.

    A PROTOCOL for `PackFetcher`'s reason — whichever client eventually speaks HTTP is that
    module's import and not this one's, and the tests that prove the four outcomes hand
    `SessionKnowledge` a three-line fake rather than a transport.

    **`embed` MUST NOT RAISE, AND THAT IS PART OF THE CONTRACT RATHER THAN A HOPE.** A
    timeout, a 5xx, a rotated key, a body that is not JSON and a width that disagrees are all
    the same fact to the caller — we did not get a vector — and every one of them has to
    arrive as `None`, because the caller is a live phone call and the alternative is a tool
    handler that "failed and returned no result" instead of an agent saying it cannot check.

    `model` and `dimensions` are on the Protocol so the pack's declaration can be compared
    against this process's configuration BEFORE a request is paid for: a query vector bought
    from an encoder the pack was not built with is money spent on a comparison that cannot
    mean anything.
    """

    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, question: str) -> QueryVector | None: ...


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
        #: The two indexes are cached TOGETHER with the pack, not rebuilt per session. The
        #: dense one decodes and normalises every passage vector, which is the one part of
        #: loading that is proportional to the corpus times the width — a warm container
        #: re-doing it per call would spend the saving the cache exists for.
        self._entries: OrderedDict[str, tuple[KnowledgePack, LexicalIndex, DenseIndex]] = (
            OrderedDict()
        )

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def keys(self) -> tuple[str, ...]:
        """Digests currently held, LRU first. For tests and operator inspection; a digest is
        an id, so logging one does not breach hard rule 6."""
        return tuple(self._entries)

    def get(
        self, content_sha256: str, *, tenant_id: UUID, agent_id: UUID
    ) -> tuple[KnowledgePack, LexicalIndex, DenseIndex] | None:
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
        pack = held[0]
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

    def put(self, pack: KnowledgePack, index: LexicalIndex, dense: DenseIndex) -> None:
        self._entries[pack.content_sha256] = (pack, index, dense)
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
    #: Which arm produced this answer, for the operator log and for the tests that prove the
    #: dense one did NOT run on a `found`. `"lexical"` on every turn the fast path settled,
    #: `"dense"` where the second arm replaced it, `"dense_failed"` where it was consulted
    #: and could not answer — which is the only path that turns a `not_found` into
    #: `temporarily_unavailable`, and an operator needs to see the difference.
    arm: Literal["lexical", "dense", "dense_failed"] = "lexical"
    #: Tokens the query embedding actually cost, straight from the vendor's `usage`. `None`
    #: on every turn that bought nothing. Hard rule 7 needs the QUANTITY at the point of
    #: purchase; the price is an operator attestation in a process this container cannot
    #: reach, so what travels out of here is the number that was bought and never a rupee
    #: figure computed from it.
    embedding_tokens: int | None = None


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
    #: The dense arm's half of the corpus. Always present alongside `index` and EMPTY for a
    #: v1 pack or a pack built without vectors, which is why it is not another `| None`: an
    #: index with nothing in it already answers every question this object asks of it, and a
    #: second nullable would put the same state in two places.
    dense: DenseIndex | None = None
    unavailable_reason: UnavailableReason | None = None
    #: The digest asked for, which is an id and therefore loggable, and which is present
    #: even on the failure path so an operator can find the object that did not load.
    requested_digest: str = ""

    @property
    def available(self) -> bool:
        return self.index is not None

    async def answer(
        self,
        question: str,
        *,
        k: int = DEFAULT_TOP_K,
        embedder: QueryEmbedder | None = None,
    ) -> KnowledgeAnswer:
        """**THE in-call entry point.** Lexical first; dense only where that already lost.

        This and `search` are one layer and not two ways of doing one thing: `search` IS the
        lexical index lookup — free, deterministic, offline, and the thing
        `tests/in_call_retrieval_recall_test.py` scores — while this is the ANSWER a turn
        gets, which consults it and may then buy a query vector. Everything that decides
        whether to spend money lives here, in one function, and `pipeline.py` calls nothing
        else.

        `embedder=None` is the complete off state and it is the default: no embedder, no
        request, no spend, and the answer is exactly `search`'s. That is what a deployment
        with no attested embedding price runs (hard rule 7 — `embedding.py`'s docstring has
        where that pre-flight lives and why it cannot live in this container).
        """
        started = time.perf_counter()
        answer = self._search(question, k=k, started=started)
        if embedder is not None and answer.outcome in _DENSE_TRIGGERS:
            answer = await self._dense_pass(
                question, k=k, started=started, embedder=embedder, lexical=answer
            )
        _log_answer(self, answer)
        return answer

    def search(self, question: str, *, k: int = DEFAULT_TOP_K) -> KnowledgeAnswer:
        """The LEXICAL answer alone. Four states, never an exception, never a network call.

        Kept as its own callable — rather than folded into `answer` behind `embedder=None` —
        because it is what the recall harness measures and what the sub-millisecond budget
        claim is about (`tests/in_call_lookup_latency_test.py`: p50 0.31 ms on a 400-entry
        pack, conditions stated there), and a measurement whose subject can only be reached
        through an `await` and an optional argument is a measurement that will quietly start
        including something else.
        It logs, like `answer` does, because a turn that never reaches the second arm is
        still a turn an operator counts.
        """
        started = time.perf_counter()
        answer = self._search(question, k=k, started=started)
        _log_answer(self, answer)
        return answer

    async def _dense_pass(
        self,
        question: str,
        *,
        k: int,
        started: float,
        embedder: QueryEmbedder,
        lexical: KnowledgeAnswer,
    ) -> KnowledgeAnswer:
        """Buy one query vector and rank the passage vectors already in memory.

        **THE FOUR REFUSALS BEFORE ANY MONEY MOVES**, in the order they cost least to check:
        no dense index at all (a v1 pack, or a pack built with no vectors); a pack whose
        declared encoder is not this process's, where a dot product would compute happily and
        mean nothing (`DenseIndex.usable_with`); a vector the provider did not give us; and a
        best match below `DENSE_MIN_COSINE`. Each leaves the lexical answer standing UNCHANGED
        except the third, which is the one that is our fault rather than the corpus's.

        **A FAILED EMBEDDING IS `temporarily_unavailable` AND NOT THE LEXICAL ANSWER, WHICH IS
        THE ONE PLACE THIS ARM CAN MAKE A TURN WORSE AND IS DELIBERATE.** Reaching here means
        the code has already decided the lexical answer is not authoritative for this
        question. Passing `not_found` through would tell the caller "this business publishes
        nothing about that" on the strength of an arm we had just declined to trust — a claim
        about a client's business made out of our own outage. "I cannot check that right now"
        is the truth, and `RetrievalOutcome` has the word for it precisely so that this
        distinction can be spoken.

        **`ambiguous` IS PRESERVED THE SAME WAY `_search` COMPUTES IT**: two top passages from
        different documents, within `AMBIGUITY_MARGIN` of each other. Same constant, same
        rule, one arm further out — a caller who asked about a category rather than a thing
        asked about a category however the passages were ranked, and the agent should still
        ask one short question rather than guess.
        """
        dense = self.dense
        if dense is None or not dense.usable_with(
            model=embedder.model, dimensions=embedder.dimensions
        ):
            return lexical

        query = await embedder.embed(question)
        if query is None:
            return KnowledgeAnswer(
                "temporarily_unavailable", (), _elapsed_ms(started), arm="dense_failed"
            )

        ranked = dense.search(query.values)
        if not ranked or ranked[0][1] < DENSE_MIN_COSINE:
            # The corpus genuinely has nothing near this question. The lexical answer already
            # said so in its own vocabulary; replacing it with an identical word would only
            # lose the `arm` the operator log reads.
            return lexical

        entries = self.entries_or_empty()
        top = [(position, score) for position, score in ranked if score >= DENSE_MIN_COSINE]
        if len(top) > 1:
            margin = (top[0][1] - top[1][1]) / top[0][1]
            different_document = entries[top[1][0]].document_id != entries[top[0][0]].document_id
            if different_document and margin < AMBIGUITY_MARGIN:
                return KnowledgeAnswer(
                    "ambiguous",
                    tuple(
                        self._passage(entries[position], score)
                        for position, score in top[:AMBIGUOUS_CANDIDATES]
                    ),
                    _elapsed_ms(started),
                    arm="dense",
                    embedding_tokens=query.tokens,
                )
        return KnowledgeAnswer(
            "found",
            tuple(self._passage(entries[position], score) for position, score in top[:k]),
            _elapsed_ms(started),
            arm="dense",
            embedding_tokens=query.tokens,
        )

    def entries_or_empty(self) -> tuple[PackEntry, ...]:
        """The pack's entries, or nothing when no pack loaded. `DenseIndex` indexes BY
        POSITION into exactly this tuple, so the two must be read from one place."""
        return () if self.pack is None else self.pack.entries

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
            # TIES BROKEN BY POSITION, THE SAME RULE `DenseIndex.search` ALREADY USES, and
            # for the reason that method's docstring gives: position IS the pack's canonical
            # `chunk_id` order. `kb/pack.read_entries` returns
            # `sorted(entries, key=lambda e: str(e.chunk_id))` (`kb/pack.py:171`) and
            # `KnowledgePack.digest` hashes the same sort (`knowledge_pack.py:330`), so on
            # every pack this worker can load the two keys produce the IDENTICAL ranking,
            # one `str()` per comparison cheaper.
            #
            # ⚠ IT IS THE DIFFERENCE BETWEEN A MEASUREMENT AND A COIN FLIP. The two keys
            # diverge only on a pack whose entries are NOT in chunk_id order, which is what a
            # harness builds: `tests/in_call_retrieval_recall_test.py` derives its chunk ids
            # from a fixture label, so an undeclared tie-break made the SAME corpus report
            # recall@1 of 0.583 or 0.625. A tie-break cannot make a tie meaningful, but it
            # must not make a published number depend on something nobody declared.
            key=lambda item: (-item[1].score, item[0]),
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
                        self._passage(entries[position], hit.score)
                        for position, hit in ranked[:AMBIGUOUS_CANDIDATES]
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

    `arm` and `embedding_tokens` join that list and neither widens it: one is a word out of a
    closed three-value set and the other is a count the vendor reported. A COSINE would not
    be admissible on the same reasoning that keeps a BM25 score out — a similarity against a
    named chunk id is a statement about what the caller asked.
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
        arm=answer.arm,
        embedding_tokens=answer.embedding_tokens,
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
        pack, index, dense = held
        logger.info(
            "knowledge pack cache hit",
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            digest=content_sha256,
            entries=len(pack.entries),
            vectors=len(dense),
        )
        return SessionKnowledge(
            tenant_id=tenant_id,
            agent_id=agent_id,
            pack=pack,
            index=index,
            dense=dense,
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
    # silently lost half its corpus cannot tell it is missing knowledge it thinks it has.
    # The SET rather than the builder's constant, because v2 is a strict superset of v1 and
    # refusing every pack published before this deploy would be an outage on every agent
    # until each client happened to republish — the contract's
    # `SUPPORTED_PACK_FORMAT_VERSIONS` docstring argues both halves.
    if pack.format_version not in SUPPORTED_PACK_FORMAT_VERSIONS:
        return _unavailable(tenant_id, agent_id, content_sha256, "unsupported_format", None)

    # The bytes must be the pack we asked for and the pack must belong to this session.
    # Both are checked before anything is cached, so a wrong object can never become a warm
    # container's answer for the next caller.
    if pack.content_sha256 != content_sha256:
        return _unavailable(tenant_id, agent_id, content_sha256, "identity_mismatch", None)
    if pack.tenant_id != tenant_id or pack.agent_id != agent_id:
        return _unavailable(tenant_id, agent_id, content_sha256, "identity_mismatch", None)

    index = LexicalIndex(pack.entries)
    dense = DenseIndex(pack)
    cache.put(pack, index, dense)
    logger.info(
        "knowledge pack loaded",
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        digest=content_sha256,
        entries=len(pack.entries),
        format_version=pack.format_version,
        # A count and a model name, both ids rather than content. Zero vectors against a
        # non-empty pack is the state an operator most needs to see: it means the deployment
        # that PUBLISHED this pack had no attested embedding price or no Google credential,
        # and the dense arm is off for this agent for a reason outside this container.
        vectors=len(dense),
        embedding_model=pack.embedding_model,
    )
    return SessionKnowledge(
        tenant_id=tenant_id,
        agent_id=agent_id,
        pack=pack,
        index=index,
        dense=dense,
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
    "AMBIGUOUS_CANDIDATES",
    "BM25_B",
    "BM25_K1",
    "DEFAULT_TOP_K",
    "DENSE_MIN_COSINE",
    "DF_GATE_MIN_ENTRIES",
    "INDIAN_SCRIPT_NAMES",
    "MAX_CACHED_PACKS",
    "MAX_INFORMATIVE_DF_RATIO",
    "DenseIndex",
    "KnowledgeAnswer",
    "LexicalIndex",
    "PackCache",
    "PackFetcher",
    "QueryEmbedder",
    "QueryVector",
    "SessionKnowledge",
    "UnavailableReason",
    "has_indian_script",
    "indian_scripts_in",
    "load_session_knowledge",
    "query_forms",
    "transliterate_indic",
]
