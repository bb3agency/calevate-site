"""The English gloss: what it is, which chunks need one, and when retrieval may read it.

WHY A GLOSS EXISTS AT ALL — MEASURED, NOT ASSUMED. `docs/evidence/telugu-embedding-quality.md`
(the model half of the D-28 gate, measured on this repo's own seeded verticals, n=24) found
that the query form production actually produces is the one retrieval is worst at. Sarvam's
Saaras STT returns **Tenglish** — Telugu grammar in Latin script, studded with English nouns
— and against a Telugu-script corpus that scored **recall@1 0.250** where an English control
on the same facts scored **0.958**. Storing the same fact in English as well took the worst
cell to **0.750**. The mitigation is bought at ingestion, once per chunk, and it is bought
now because retrofitting it means re-ingesting every client's knowledge base.

WHAT A GLOSS IS NOT, AND THIS IS THE LOAD-BEARING SENTENCE. **A gloss is a RETRIEVAL KEY,
never an utterance.** It is matched against a question and it is never returned, quoted,
compiled into a prompt, or pushed to the engine. `retrieval/compiled_facts.py` scores it and
then returns the ORIGINAL approved line. So a machine translation cannot widen what a
client's agent may say: the human approved Telugu, the agent still says Telugu, and the only
thing the gloss changes is whether a Tenglish question finds it. That is why the gloss does
not need an approval gate of its own — a mistranslation costs a WRONG MATCH (the client's
own approved words, retrieved for the wrong question), never a wrong SENTENCE. It is still
shown, marked, at the existing preview-and-approve screen, because a reviewer who can see it
can report a bad one.

THE SCRIPT GATE, AND THE TRAP IT AVOIDS. The same measurement found that the obvious
implementation BACKFIRES: an unconditional RRF hybrid over dense+lexical arms dropped
cross-script recall from 0.708 to 0.375, because an arm that matches essentially nothing
still averages its arbitrary ranking into the fused result. Its conclusion — *"a hybrid must
gate its lexical arm"* — is `gloss_applies` below, expressed for the ranker this repo
actually has (deterministic token overlap, `retrieval/compiled_facts.py`) rather than for the
dense+BM25 pair the spike measured: **the gloss arm runs only when the question and the
passage are in different scripts.** Same-script retrieval therefore cannot be perturbed at
all — the gloss is not consulted, so the score is byte-identical to the score before this
feature existed. `tests/kb_gloss_retrieval_test.py` measures all three arms over the spike's
own 24-fact corpus and pins the result.
"""

from __future__ import annotations

import re
from typing import Final

#: `kb_documents.gloss_state`. A CLOSED vocabulary, rendered verbatim into the CHECK
#: constraint by migration `a7f4c31d95e8`.
#:
#: The three states exist because "no gloss" has TWO causes that must never be confused:
#: a chunk nobody has looked at yet, and a chunk that was looked at and correctly needs
#: nothing. Collapsing them into `gloss IS NULL` would make the sweep re-select every
#: English chunk on every tick forever — it would re-pay a model call to reach the same
#: "no" — which is precisely the idempotency the worker is required to have.
GLOSS_PENDING: Final = "pending"
GLOSS_READY: Final = "ready"
GLOSS_NOT_NEEDED: Final = "not_needed"

GLOSS_STATES: Final[tuple[str, ...]] = (GLOSS_PENDING, GLOSS_READY, GLOSS_NOT_NEEDED)

#: Telugu, as Unicode defines it (block U+0C00 to U+0C7F). Named by its block rather than by a
#: language guess: this is a question about CHARACTERS, which is decidable, and not about
#: language, which is not. A romanised Telugu sentence is Latin script and this function
#: says so — which is the whole point, because that is the form Saaras returns and the form
#: a Telugu-script passage cannot match.
_TELUGU = re.compile(r"[\u0c00-\u0c7f]")

#: Latin letters. ASCII plus the Latin-1/Extended-A ranges, so an accented borrowing does
#: not silently fall through to "other".
_LATIN = re.compile(r"[A-Za-z\u00c0-\u024f]")

#: The script names this module returns. `other` is a real answer, not a failure: a chunk of
#: pure digits, Devanagari, or emoji is none of the two scripts this product's retrieval
#: problem is about, and pretending otherwise would gloss text nobody asked about.
SCRIPT_TELUGU: Final = "telugu"
SCRIPT_LATIN: Final = "latin"
SCRIPT_OTHER: Final = "other"

#: How much of one script it takes to call a mixed string that script.
#:
#: A Telugu passage naturally carries Latin fragments — "WhatsApp", "Star Health", "9 am" —
#: and a majority rule on raw counts would flip a genuinely Telugu chunk to `latin` the
#: moment it quoted a brand name. Two-thirds of the *letters that carry script at all*
#: (digits, spaces and punctuation are excluded by both patterns) is comfortably above the
#: borrowing rate of the seeded verticals' own text and comfortably below a genuine mix.
#: A string that reaches neither share is `other` and is left alone.
_DOMINANCE: Final = 2 / 3


def dominant_script(value: str) -> str:
    """`telugu`, `latin` or `other` — the script a reader would say this text is in.

    Counts characters rather than words on purpose: Telugu is agglutinative and written
    without spaces between many morphemes, so a word count is a different measurement in
    the two scripts and would not compare.
    """
    telugu = len(_TELUGU.findall(value))
    latin = len(_LATIN.findall(value))
    total = telugu + latin
    if total == 0:
        return SCRIPT_OTHER
    if telugu / total >= _DOMINANCE:
        return SCRIPT_TELUGU
    if latin / total >= _DOMINANCE:
        return SCRIPT_LATIN
    return SCRIPT_OTHER


def needs_gloss(content: str) -> bool:
    """Does this chunk earn an English rendering?

    ONLY TELUGU-SCRIPT TEXT DOES, and the asymmetry is the finding rather than a shortcut.
    The measurement's binding constraint is a Latin-script question against a Telugu-script
    passage; an English passage is ALREADY the thing a gloss would produce, so glossing it
    would pay a model call to store a second copy of the same string and then — because
    `gloss_applies` gates on a script DIFFERENCE that a copy does not create — never read
    it. `other` is left alone for the same reason with less confidence: nobody has measured
    retrieval on a script this product does not yet serve, and inventing a translation for
    it would be spend against an unmeasured benefit.
    """
    return dominant_script(content) == SCRIPT_TELUGU


def gloss_applies(*, question: str, passage: str) -> bool:
    """THE SCRIPT GATE. May a passage's gloss be scored against this question?

    Only when the two are in DIFFERENT scripts — which is exactly the case the original
    passage cannot serve, and exactly the case the spike measured a 0.250 → 0.750 gain on.
    When they agree, the gate is shut and the gloss is never read, so a same-script question
    scores precisely what it scored before glosses existed. That is a structural guarantee
    rather than a measured one: there is no code path from a gloss to a same-script score.

    `other` on either side shuts the gate too. A question of pure digits ("8000") has no
    script to differ from, and letting it through would open the gloss arm on every passage
    at once — the ungated blend whose cost the spike put a number on.
    """
    q = dominant_script(question)
    if q == SCRIPT_OTHER:
        return False
    p = dominant_script(passage)
    if p == SCRIPT_OTHER:
        return False
    return q != p


__all__ = [
    "GLOSS_NOT_NEEDED",
    "GLOSS_PENDING",
    "GLOSS_READY",
    "GLOSS_STATES",
    "SCRIPT_LATIN",
    "SCRIPT_OTHER",
    "SCRIPT_TELUGU",
    "dominant_script",
    "gloss_applies",
    "needs_gloss",
]
