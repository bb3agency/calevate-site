"""Does in-call retrieval still FIND the fact — measured per query form, floored in CI.

**THE CALL THIS FILE IS ABOUT.** A caller asks a question in Telugu. Saaras transcribes it,
the LLM reads it and writes an English search query itself (`docs/PIPECAT-MIGRATION.md`
§9.1 step 2), and `SessionKnowledge.search` runs over an English-only index (§9.2: store
both, index one). Nothing in this repository noticed if that last step got WORSE. The
failure §9.4 names is not a crash and not a wrong sentence — it is retrieval returning
nothing for a fact the client published, which on a phone call is the agent saying "I don't
have that" about their own opening hours. A recall regression is silent everywhere except
here.

**WHAT IS MEASURED.** The real `KnowledgePack`, the real `LexicalIndex`, the real
`SessionKnowledge.search`, over the same 24 facts `docs/evidence/telugu-embedding-quality.md`
measured (`tests/fixtures/telugu_gloss_corpus.json`), each asked three ways — English,
Tenglish, Telugu script — plus a hand-written code-mixed set
(`tests/fixtures/code_mixed_queries.json`) and, since 15 Sep 2026, **a second language's
corpus in Hindi** (`tests/fixtures/hindi_gloss_corpus.json`, 24 facts, the same three forms).
Recall counts the fact's OWN document among the passages the caller's turn would actually
have received, which means an `ambiguous` answer contributes its two passages and a
`not_found` contributes none. That is deliberate: recall computed over an internal ranking
rather than over the returned answer would score a hit the caller never heard.

**WHY A SECOND LANGUAGE AT ALL, AND WHY HINDI (D-612).** With one language measured, every
number in this file is a claim about Telugu that reads like a claim about the product — and
the product is not Telugu-only. `calevate_shared.languages` models exactly this: eleven
languages are CONVERSATIONAL (Sarvam can both hear and speak them), and three of those are
what the product SELLS (`OFFERED_LANGUAGE_IDS` = `telugu`, `hindi`, `english_india`).
English is this index's own language and the control, Telugu is the first arm, so **Hindi is
the only remaining language a client can configure an agent in today** — measuring one of
the other eight conversational languages would be measuring a product nobody may buy, which
is the same objection this file's own "REJECTED" list raises against indexing `passage_te`.

The vendor evidence is the same reading `calevate_shared.languages` cites, and it is the
vendor's own package rather than a framework's map of it — [VERIFIED-VENDOR-SDK:
`sarvamai==0.1.28`, `types/speech_to_text_language.py:5-31` (`hi-IN` on the 23-code STT
literal) and `types/text_to_speech_language.py:5-7` (`hi-IN` on the 11-code TTS literal),
read in this tree 14 Sep 2026]. Both legs, so Hindi is conversational and not
comprehension-only; `pipecat-ai==1.10.0` carries `hi-IN` on both of its Sarvam tables too
(`services/sarvam/stt.py:738-757`, `services/sarvam/tts.py:219-243`), which is corroboration
and not the source.

Hindi is also the harder question for THIS module, which is the second reason: it is written
in Devanagari, and every romanisation rule in `voice_worker.knowledge` was written against
Telugu. `INDIAN_SCRIPT_NAMES` claims ten scripts from one element table, and a claim no
second script had ever tested is a claim. It did not survive intact — see
`test_a_nukta_changes_the_consonant_it_sits_under`.

**WHAT THE TWO DEPTHS MEAN, SINCE 15 Sep 2026.** `recall@1` counts a fact only when its
passage scores STRICTLY above the passage below the cut — the fact was the unambiguous best
match, and no tie-break could have taken it. `recall@3` counts it when it reached the model
at all, `ambiguous`'s two passages included. `_recall`'s docstring argues both, and the
paragraph under the first table is why the distinction had to be made rather than assumed.

**MEASURED 14 Sep 2026, at the commit that wrote this file, re-measured under the
deterministic rules 15 Sep** (n=24, English-only index, `DEFAULT_TOP_K`=3):

    query form        recall@1   recall@3   outcomes
    query_en           0.833      0.875     20 found, 4 ambiguous
    query_tenglish     0.583      0.708     17 found, 4 ambiguous, 3 not_found
    query_te           0.083      0.083      2 found, 22 not_found
    code-mixed (n=10)  1.000      1.000     10 found

⚠ **THAT `query_tenglish` FIGURE WAS BRIEFLY "CORRECTED" TO 0.625 AND THE CORRECTION WAS
WRONG. READ THIS BEFORE TRUSTING ANY NUMBER IN THIS FILE.** On 15 Sep somebody re-ran the
harness, got 0.625 where the table said 0.583, concluded the original had been transcribed
wrong, and pushed 0.625 into this docstring and into `docs/PIPECAT-MIGRATION.md` §9.4 —
citing hard rule 11 while doing it. **Both readings were real and neither was a measurement.**
`re_amenities` scores 2.1917654896 against a competitor scoring exactly 2.1917654896, and
`_search` was breaking that tie on `str(chunk_id)`, which `_pack_from` derives from a fixture
LABEL. So the published number depended on a string nobody had ever thought of as an input,
and re-running the measurement reproduced the coin flip instead of catching it.

The lesson is narrower and sharper than "verify before you state": **re-running a measurement
is not verification if the measurement is not deterministic, and nothing said so.** It is now
said by `test_the_numbers_do_not_depend_on_the_fixture_label`, which sweeps the label and
asserts one value — and by the tie rule in `_recall`, under which this question is a MISS at
rank 1 in every world, because equal-best is not best. 0.583 is what that gives, and it is
stable. The floor was never in question; it sat under every reading.

**THE HINDI ARM, MEASURED 15 Sep 2026** (n=24, same index, same `DEFAULT_TOP_K`=3,
`tests/fixtures/hindi_gloss_corpus.json`):

    query form        recall@1   recall@3   outcomes
    query_en           0.917      1.000     20 found, 4 ambiguous
    query_hinglish     0.750      0.792     18 found, 4 ambiguous, 2 not_found
    query_hi           0.083      0.083      2 found, 22 not_found

**READ THE TWO TABLES AS TWO CORPORA, NOT AS TELUGU AGAINST HINDI.** Hindi scores higher on
the first two rows and that is a property of the CORPUS, not of the language: these 24 facts
are two disjoint verticals (a coaching institute and an insurance agency) where the Telugu
set's 24 are a clinic and a builder, and both of Hindi's remaining `ambiguous` losses are
the two pairs that genuinely overlap (two "office closed" facts, two "batch" facts). What
the second corpus is evidence FOR is the shape, and the shape reproduced exactly: English
wins, the romanised form degrades gradually, **and the native script falls off the same
cliff to the same 2-of-24**. A single-language finding became a two-language one.

⚠ **THE ROMANISED HINDI ROW IS NOT EVIDENCE THAT THE STOPWORD LIST COVERS HINDI.** It does
not — `_QUERY_STOPWORDS` in `voice_worker.knowledge` is English plus romanised TELUGU
function words, and says so in its own docstring; `hai`, `kya`, `kitne` and `ke` reach the
gate as content words. 0.750 is what that costs, measured rather than assumed, and it is the
number to compare against if somebody ever fills that list in from a real Hindi call.

**FLOORS, AND WHY THEY ARE NOT THE MEASURED NUMBERS.** One question changing outcome is
1/24 = 0.042 of the corpus, and the `ambiguous` margin puts several questions within a few
percent of flipping. A floor set AT the measurement would therefore go red for a tokeniser
improvement that helped 23 questions and moved one across the margin — the classic gate
everyone learns to ignore. Each floor below sits roughly one question under what was
measured, which is loose enough to absorb that and tight enough that the regression this
file exists for — a query form collapsing toward zero, the way `query_te` already is — moves
it by several questions and fails. Floors, never equalities, so an improvement is never a
failure; if a number goes UP, raise the floor in the same commit and say so.

**ENGLISH IS THE CONTROL, NOT A LANGUAGE UNDER TEST.** §9.1 step 2 says the query reaching
this index is English, so `query_en` is the form production actually runs. It must score
highest. An English score that is not the best in the table is not a fact about Telugu — it
is a fact about the index, the tokeniser or the gate, and `test_english_the_form_the_llm_
actually_emits_is_the_best_form` is what says so out loud.

**⚠ THE TELUGU-SCRIPT NUMBER IS A REAL RESULT AND IT IS NOT A BUG TO BE FIXED HERE.** 0.083
recall@1, 22 of 24 answered `not_found`: a Telugu-script question put STRAIGHT at an English
index retrieves essentially nothing, and transliteration does not rescue it (romanised
Telugu is not English — `voice_worker.knowledge.transliterate_indic`'s own docstring says
so). That is the measured cost of §9.2, and it is affordable only because step 2 stands
between the caller and this index. **It is pinned here as the load-bearing dependency it is:
if the LLM ever stops paraphrasing into English — a prompt edit, a model swap, a tool
description that stops asking for it — retrieval does not degrade, it stops**, and the
number it degrades to is in this file.

**NO NETWORK, NO MODEL, NO DATABASE.** Pure in-process retrieval over a pack built in
memory, which is the whole point of D-599; the suite runs in well under a second.

REJECTED, and worth recording:

* **Asserting a single recall number per form.** Brittle in the direction that trains people
  to edit the assertion — see the floors paragraph.
* **Asserting an upper bound on `query_te` to "pin the finding".** It would make an
  improvement to the transliterator a red build, and the finding belongs in prose and in the
  docstring table, not in a ceiling.
* **Scoring `LexicalIndex` directly instead of `SessionKnowledge.search`.** It would measure
  a ranking rather than an answer, and would keep passing with the gate or the ambiguity
  margin broken — the two parts most likely to silently swallow a good match.
* **Indexing `passage_te` as well to make the Telugu row look better.** That is precisely the
  design §9.2 rejected on measurement, and a test that quietly does it would be testing a
  product we do not ship.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid5

from calevate_shared.knowledge_pack import KnowledgePack, PackEntry
from voice_worker.knowledge import (
    DEFAULT_TOP_K,
    LexicalIndex,
    SessionKnowledge,
    indian_scripts_in,
    query_forms,
    transliterate_indic,
)

_FIXTURES: Final[pathlib.Path] = pathlib.Path(__file__).parent / "fixtures"

#: The corpus the evidence document measured. NOT modified here, and not extended: it is
#: cited by `tests/kb_gloss_retrieval_test.py` and by `docs/evidence/
#: telugu-embedding-quality.md`, and a corpus that grew or shrank would silently move every
#: figure in both.
_CORPUS: Final[list[dict[str, Any]]] = json.loads(
    (_FIXTURES / "telugu_gloss_corpus.json").read_text()
)

#: The code-mixed set: Telugu or Hindi words inside an English sentence, which is how a
#: person actually asks a shop something on the phone. Ordinary small-business facts on
#: purpose — hours, prices, delivery, returns, an appointment — so the set exercises the
#: register rather than a vertical the other fixture already covers.
_CODE_MIXED: Final[list[dict[str, Any]]] = json.loads(
    (_FIXTURES / "code_mixed_queries.json").read_text()
)

#: THE SECOND LANGUAGE (D-612). Twenty-four facts, asked the same three ways, from two of
#: the four verticals `scripts/seed.py::VERTICAL_TEMPLATES` actually ships — `education` (a
#: coaching institute) and `insurance` (a motor and term-life agency). Deliberately NOT the
#: two the Telugu corpus uses, so the two fixtures together cover all four shipped
#: verticals and neither corpus is the other one translated; and deliberately no clinical
#: scenario, which is a product instruction and not a retrieval one.
_HINDI_CORPUS: Final[list[dict[str, Any]]] = json.loads(
    (_FIXTURES / "hindi_gloss_corpus.json").read_text()
)

#: A fixed namespace, so every id in this file is derived rather than typed and two runs
#: build byte-identical packs (and therefore the same `content_sha256`).
_NS: Final[UUID] = UUID("0199c0de-0000-7000-8000-0000000000ff")

# --- the floors -------------------------------------------------------------------------
# Measured 14 Sep 2026; see the module docstring for the table and for why each floor sits
# about one question (1/24 = 0.042) below what was measured.

_EN_RECALL_AT_1_FLOOR: Final[float] = 0.79  # measured 0.833
_EN_RECALL_AT_3_FLOOR: Final[float] = 0.83  # measured 0.875
_TENGLISH_RECALL_AT_1_FLOOR: Final[float] = 0.54  # measured 0.583
_TENGLISH_RECALL_AT_3_FLOOR: Final[float] = 0.66  # measured 0.708

#: ⚠ NOT A QUALITY BAR — a tripwire under a form that is ALREADY failing (0.083 / 0.083).
#: It exists so that "Telugu script retrieves nothing from an English index" stays a
#: measured statement in CI rather than folklore, and so a change that takes it to a hard
#: zero is visible. Read the module docstring before touching it.
_TELUGU_SCRIPT_RECALL_AT_1_FLOOR: Final[float] = 0.04

#: The code-mixed set measured 1.000 / 1.000, and the floor is well below it because n=10
#: makes one question worth 0.1 — a tenth of the scale per flip is exactly the noise a
#: floor is supposed to absorb. The set is also EASIER than the 24-fact corpus by
#: construction (ten topically disjoint facts, and the English nouns a code-mixed speaker
#: keeps — "delivery", "UPI", "parking" — are the match), so a perfect score here is not
#: evidence that the harder corpus is fine. Both are measured; neither substitutes.
_CODE_MIXED_RECALL_AT_1_FLOOR: Final[float] = 0.80
_CODE_MIXED_RECALL_AT_3_FLOOR: Final[float] = 0.90

# --- the Hindi floors -------------------------------------------------------------------
# Measured 15 Sep 2026 on `hindi_gloss_corpus.json`; same n=24, so one question is again
# 0.042, and every floor below again sits about one question under what was measured. They
# are NOT copies of the Telugu floors and must not be reconciled with them: two corpora,
# two numbers, and a floor that was moved to make the two tables match would be measuring
# nothing.

_HI_EN_RECALL_AT_1_FLOOR: Final[float] = 0.87  # measured 0.917
_HI_EN_RECALL_AT_3_FLOOR: Final[float] = 0.95  # measured 1.000
_HINGLISH_RECALL_AT_1_FLOOR: Final[float] = 0.70  # measured 0.750
_HINGLISH_RECALL_AT_3_FLOOR: Final[float] = 0.75  # measured 0.792

#: ⚠ NOT A QUALITY BAR, for the same reason `_TELUGU_SCRIPT_RECALL_AT_1_FLOOR` is not: a
#: tripwire under a form already at 0.083 (2 of 24 found, 22 `not_found`). That it is the
#: SAME number the Telugu script scored is a real result and not a copied constant — the two
#: facts Devanagari does find are the two whose question carries a token the English passage
#: also carries, an English loanword (`डेमो` → `demo`) and a digit (`12`), which is exactly
#: the mechanism the Telugu row's 2-of-24 runs on.
_DEVANAGARI_RECALL_AT_1_FLOOR: Final[float] = 0.04


def _pack_from(facts: list[dict[str, Any]], label: str) -> tuple[SessionKnowledge, dict[UUID, str]]:
    """An agent whose published knowledge is these facts, ENGLISH TEXT ONLY.

    `gloss` stays `None` and `passage_te` is never indexed: §9.2 ships an index built from
    the English gloss alone, so a harness that also fed it the Telugu would be measuring a
    product nobody deployed. The returned map is document id → `fact_id`, which is how a
    returned `Passage` is scored — `Provenance.source_id` is the document, and one fact is
    one document here.
    """
    tenant_id = uuid5(_NS, f"{label}:tenant")
    agent_id = uuid5(_NS, f"{label}:agent")
    entries: list[PackEntry] = []
    documents: dict[UUID, str] = {}
    for fact in facts:
        document_id = uuid5(_NS, f"{label}:doc:{fact['fact_id']}")
        documents[document_id] = fact["fact_id"]
        entries.append(
            PackEntry(
                chunk_id=uuid5(_NS, f"{label}:chunk:{fact['fact_id']}"),
                document_id=document_id,
                document_version=1,
                text=fact["passage_en"],
                gloss=None,
            )
        )
    frozen = tuple(entries)
    pack = KnowledgePack(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content_sha256=KnowledgePack.digest(tenant_id, agent_id, frozen),
        built_at=datetime(2026, 9, 14, tzinfo=UTC),
        entries=frozen,
    )
    session = SessionKnowledge(
        tenant_id=tenant_id,
        agent_id=agent_id,
        pack=pack,
        index=LexicalIndex(pack.entries),
        requested_digest=pack.content_sha256,
    )
    return session, documents


#: ONE RANK DEEPER THAN THE CALLER IS EVER HANDED, AND THE EXTRA RANK IS NEVER SCORED.
#: `_recall` needs the score of the first passage BELOW each cut to know whether a tie
#: straddles it (see its docstring); that score is invisible if the search returns exactly
#: as many passages as we score. So the harness asks for `DEFAULT_TOP_K + 1` and uses the
#: last one solely as a boundary probe — `passages[:k]` is still exactly the set the
#: caller's turn would have received, because `_search` slices the same ranking. An
#: `ambiguous` answer ignores `k` and returns its two passages either way.
_PROBE_K: Final[int] = DEFAULT_TOP_K + 1


def _hits(
    session: SessionKnowledge, documents: dict[UUID, str], question: str
) -> tuple[list[str], list[float], str]:
    """The `fact_id`s this turn would have handed the model, best first, their scores, and
    the outcome. See `_PROBE_K` for why one more rank comes back than is ever scored."""
    answer = session.search(question, k=_PROBE_K)
    return (
        [documents[p.provenance.source_id] for p in answer.passages],
        [p.score for p in answer.passages],
        answer.outcome,
    )


def _recall(facts: list[dict[str, Any]], query_key: str, label: str) -> tuple[float, float, dict]:
    """recall@1 AND recall@`DEFAULT_TOP_K` over the ANSWER, plus the outcome census.

    A miss is a miss whichever state produced it: `not_found` (the gate refused), `ambiguous`
    (two near-equal candidates, neither the right one) and a confident wrong `found` all
    cost the caller the same thing.

    ⚠ **A TIE AT THE CUT IS NOT A HIT, AND THAT IS THE WHOLE DIFFERENCE BETWEEN A NUMBER AND
    A COIN FLIP** (15 Sep 2026). BM25 produces exact ties — `re_amenities` scores
    2.1917654896 against a competitor's 2.1917654896 — and at an exact tie there IS no rank
    1: whichever entry `_search`'s tie-break puts first, the data did not put it there.
    Counting such a fact as recall@1 reports "the correct fact was the best match" on
    evidence that says "the correct fact was EQUAL-best", so this scores a hit at `k` only
    when the fact's own passage scores STRICTLY higher than the passage just below the cut.
    The two depths then mean two different, and separately useful, things:

      * **recall@1** — the fact was the unambiguous best match. No tie-break could take it.
      * **recall@3** — the fact reached the model at all, which is what §9.4 is about.

    An `ambiguous` answer still contributes its two passages to recall@3, unchanged: the
    model really is handed both, and the caller really can be answered from them. What it no
    longer does is contribute to recall@1 when its two scores are equal.

    ⚠ **BOTH DEPTHS COME OUT OF ONE PACK, AND THAT IS LOAD-BEARING RATHER THAN TIDY.**
    `_pack_from` derives chunk ids from the `label`, so measuring the two depths under two
    labels ranks tied entries two different ways and reports two numbers off one corpus.
    Taking one pack for both makes the label unobservable at the depths; the strict-score
    rule above and `_search`'s position tie-break make it unobservable at the ties.
    `test_the_numbers_do_not_depend_on_the_fixture_label` is the assertion, and it is the
    thing that stops all of this coming back.
    """
    session, documents = _pack_from(facts, label)
    outcomes: dict[str, int] = {}
    at_1 = 0
    at_k = 0
    for fact in facts:
        got, scores, outcome = _hits(session, documents, fact[query_key])
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        for cut, counter in ((1, "at_1"), (DEFAULT_TOP_K, "at_k")):
            if fact["fact_id"] not in got[:cut]:
                continue
            # The passage at index `cut` is the first one BELOW the cut. If the fact ties it,
            # the fact's membership of the top `cut` was decided by the tie-break, not by the
            # search, and this refuses to call that a hit. No passage there means the ranking
            # ran out before the cut, so nothing could have displaced it.
            if len(scores) > cut and scores[got.index(fact["fact_id"])] <= scores[cut]:
                continue
            if counter == "at_1":
                at_1 += 1
            else:
                at_k += 1
    return at_1 / len(facts), at_k / len(facts), outcomes


# --- the fixtures are the ones that were measured ---------------------------------------


def test_the_corpora_are_the_ones_the_floors_were_measured_on() -> None:
    """FAILS IF a fixture grew, shrank or lost a query form — which would move every floor
    below without touching a single number in this file."""
    assert len(_CORPUS) == 24
    for fact in _CORPUS:
        assert fact["passage_en"] and fact["query_en"]
        assert fact["query_tenglish"] and fact["query_te"]

    assert len(_CODE_MIXED) == 10
    assert {fact["fact_id"] for fact in _CODE_MIXED} == {
        "shop_credit",
        "shop_delivery",
        "shop_hours",
        "shop_offer",
        "shop_parking",
        "shop_payment",
        "shop_repair",
        "shop_returns",
        "shop_rice_price",
        "shop_tailoring",
    }
    assert {fact["language_mix"] for fact in _CODE_MIXED} == {"te-en", "hi-en"}

    assert len(_HINDI_CORPUS) == 24
    assert len({fact["fact_id"] for fact in _HINDI_CORPUS}) == 24
    for fact in _HINDI_CORPUS:
        assert fact["passage_en"] and fact["passage_hi"]
        assert fact["query_en"] and fact["query_hinglish"] and fact["query_hi"]
    # Two shipped verticals, and NEITHER of the Telugu corpus's two — a second corpus that
    # reused a vertical would be measuring the same facts in another language rather than a
    # second language's own facts.
    assert {fact["vertical"] for fact in _HINDI_CORPUS} == {"education", "insurance"}
    assert not {fact["vertical"] for fact in _HINDI_CORPUS} & {fact["vertical"] for fact in _CORPUS}


# --- the floors -------------------------------------------------------------------------


def test_english_queries_hold_their_recall_floor() -> None:
    """THE CONTROL, and the one form production actually runs (§9.1 step 2).

    FAILS IF the index, the tokeniser, the informative-term gate or the ambiguity margin
    stops finding facts for a well-formed English question — the shape of every retrieval
    regression that is not about language at all.
    """
    at_1, at_3, outcomes = _recall(_CORPUS, "query_en", "corpus-en")
    assert at_1 >= _EN_RECALL_AT_1_FLOOR, f"english recall@1 {at_1:.3f}, outcomes {outcomes}"
    assert at_3 >= _EN_RECALL_AT_3_FLOOR, f"english recall@3 {at_3:.3f}, outcomes {outcomes}"


def test_tenglish_queries_hold_their_recall_floor() -> None:
    """The form Saaras returns when nobody paraphrases — romanised Telugu studded with
    English nouns (`docs/evidence/telugu-embedding-quality.md` §2.1).

    It is not the in-call path (§9.1 step 2 paraphrases first), and it is measured anyway:
    it is what the index sees if a query ever reaches it unparaphrased, and it is the only
    form in this file that degrades GRADUALLY rather than falling off a cliff. FAILS IF that
    graceful degradation stops being graceful.
    """
    at_1, at_3, outcomes = _recall(_CORPUS, "query_tenglish", "corpus-tenglish")
    assert at_1 >= _TENGLISH_RECALL_AT_1_FLOOR, f"tenglish recall@1 {at_1:.3f}, {outcomes}"
    assert at_3 >= _TENGLISH_RECALL_AT_3_FLOOR, f"tenglish recall@3 {at_3:.3f}, {outcomes}"


def test_telugu_script_against_an_english_index_retrieves_almost_nothing() -> None:
    """THE MEASURED COST OF §9.2, PINNED SO IT CANNOT BECOME FOLKLORE.

    0.083 recall@1 on 14 Sep 2026, with 22 of 24 questions answered `not_found`. This is not
    a defect in the index and must not be "fixed" by indexing Telugu — it is the reason the
    English paraphrase in §9.1 step 2 is load-bearing rather than convenient.

    FAILS IF the floor is breached (a hard zero), and the assertion message is the point:
    whoever reads it should read the number, not silence it.
    """
    at_1, _, outcomes = _recall(_CORPUS, "query_te", "corpus-te")
    assert at_1 >= _TELUGU_SCRIPT_RECALL_AT_1_FLOOR, (
        f"telugu-script recall@1 {at_1:.3f}, outcomes {outcomes} — "
        "this form is already near zero by design (§9.2); read the module docstring"
    )


def test_english_the_form_the_llm_actually_emits_is_the_best_form() -> None:
    """THE ORDERING PROPERTY, which is worth more than any single floor.

    English beats Tenglish beats Telugu script against an English index. FAILS IF that order
    breaks — and a broken order is a statement about the INDEX, not about Telugu: the form
    whose words are the same words as the corpus cannot be beaten by a form whose words are
    not, unless something upstream of the ranking is wrong.
    """
    english, _, _ = _recall(_CORPUS, "query_en", "corpus-en")
    tenglish, _, _ = _recall(_CORPUS, "query_tenglish", "corpus-tenglish")
    telugu, _, _ = _recall(_CORPUS, "query_te", "corpus-te")
    assert english > tenglish > telugu, (
        f"recall@1 en={english:.3f} tenglish={tenglish:.3f} te={telugu:.3f} — "
        "the English control did not win; suspect the index, not the language"
    )


# --- the code-mixed set -----------------------------------------------------------------


def test_code_mixed_questions_retrieve_the_fact_they_ask_about() -> None:
    """How people actually talk on an Indian phone call: "Ghar pe home delivery karte ho kya,
    kitna charge lagta hai?".

    FAILS IF a question built the way a real caller builds one stops reaching the published
    fact. Measured 1.000/1.000 on 14 Sep 2026 — see the floors' comment for why a perfect
    score here is not evidence about the harder corpus.
    """
    at_1, at_3, outcomes = _recall(_CODE_MIXED, "query_code_mixed", "shop")
    assert at_1 >= _CODE_MIXED_RECALL_AT_1_FLOOR, f"code-mixed recall@1 {at_1:.3f}, {outcomes}"
    assert at_3 >= _CODE_MIXED_RECALL_AT_3_FLOOR, f"code-mixed recall@3 {at_3:.3f}, {outcomes}"


def test_no_code_mixed_question_is_answered_with_silence() -> None:
    """THE FAILURE §9.4 NAMES, ASSERTED AS ITSELF rather than as a recall number.

    `not_found` on a question the client published an answer to is the agent telling a
    caller "I don't have that" about its own shop. Recall can absorb one of those inside a
    fraction; this cannot, and it names the offending question when it fires.
    """
    session, documents = _pack_from(_CODE_MIXED, "shop-silence")
    silent = [
        fact["fact_id"]
        for fact in _CODE_MIXED
        if _hits(session, documents, fact["query_code_mixed"])[2] == "not_found"
    ]
    assert not silent, f"code-mixed questions answered not_found: {silent}"


# --- the second language ----------------------------------------------------------------


def test_hindi_corpus_english_queries_hold_their_recall_floor() -> None:
    """THE CONTROL AGAIN, on a second corpus (D-612).

    Same role as the Telugu control and the same failure it catches — the index, the
    tokeniser, the informative-term gate or the ambiguity margin losing a well-formed English
    question. Measured 0.917/1.000 on 15 Sep 2026. It is measured on BOTH corpora because a
    control that exists on only one of them cannot tell a corpus effect from an index effect.
    """
    at_1, at_3, outcomes = _recall(_HINDI_CORPUS, "query_en", "hindi-en")
    assert at_1 >= _HI_EN_RECALL_AT_1_FLOOR, f"hindi-corpus english recall@1 {at_1:.3f}, {outcomes}"
    assert at_3 >= _HI_EN_RECALL_AT_3_FLOOR, f"hindi-corpus english recall@3 {at_3:.3f}, {outcomes}"


def test_hinglish_queries_hold_their_recall_floor() -> None:
    """Romanised Hindi studded with English nouns — "Class 12 science course ki fees kitni
    hai?" — which is what Saaras returns for a Hindi caller when nobody paraphrases.

    The Tenglish row's counterpart, and like it not the in-call path (§9.1 step 2 paraphrases
    first). Measured 0.750/0.792. FAILS IF the graceful degradation stops being graceful.

    ⚠ It scores ABOVE the Tenglish row and that is not a statement that Hindi retrieves
    better: a Hinglish speaker keeps more English nouns than a Tenglish speaker does, and
    those nouns are the match. See the module docstring.
    """
    at_1, at_3, outcomes = _recall(_HINDI_CORPUS, "query_hinglish", "hinglish")
    assert at_1 >= _HINGLISH_RECALL_AT_1_FLOOR, f"hinglish recall@1 {at_1:.3f}, {outcomes}"
    assert at_3 >= _HINGLISH_RECALL_AT_3_FLOOR, f"hinglish recall@3 {at_3:.3f}, {outcomes}"


def test_devanagari_against_an_english_index_retrieves_almost_nothing() -> None:
    """§9.2's COST, REPRODUCED IN A SECOND SCRIPT — which is what makes it a property of the
    design rather than a fact about Telugu.

    0.083 recall@1 on 15 Sep 2026, 22 of 24 `not_found`, the same 2-of-24 the Telugu script
    scores and for the same reason (a loanword and a digit). Like its Telugu twin this is not
    a defect to be "fixed" by indexing `passage_hi`, and the floor is a tripwire under a form
    already at the bottom, not a target.

    **AND IT IS NOT ZERO BECAUSE THE SCRIPT IS UNREADABLE** — the test below proves the
    tokeniser and the romaniser both do their job on Devanagari, so this number is a
    retrieval result rather than a silent tokenisation failure. Those two are the same
    number and completely different findings.
    """
    at_1, _, outcomes = _recall(_HINDI_CORPUS, "query_hi", "hindi-script")
    assert at_1 >= _DEVANAGARI_RECALL_AT_1_FLOOR, (
        f"devanagari recall@1 {at_1:.3f}, outcomes {outcomes} — "
        "this form is already near zero by design (§9.2); read the module docstring"
    )


def test_english_wins_in_hindi_too() -> None:
    """THE ORDERING PROPERTY, ON THE SECOND LANGUAGE. en > hinglish > devanagari.

    One corpus showing this order is a measurement; two corpora in unrelated languages and
    unrelated verticals showing it is the claim §9.4 actually makes — that the English
    paraphrase is load-bearing for EVERY language, not just for the one that was measured.
    """
    english, _, _ = _recall(_HINDI_CORPUS, "query_en", "hindi-en")
    hinglish, _, _ = _recall(_HINDI_CORPUS, "query_hinglish", "hinglish")
    devanagari, _, _ = _recall(_HINDI_CORPUS, "query_hi", "hindi-script")
    assert english > hinglish > devanagari, (
        f"recall@1 en={english:.3f} hinglish={hinglish:.3f} hi={devanagari:.3f} — "
        "the English control did not win; suspect the index, not the language"
    )


def test_every_devanagari_question_tokenises_and_romanises() -> None:
    """THE DISTINCTION THE 0.083 WOULD OTHERWISE BURY: near-zero recall because the index
    has no Devanagari in it, NOT because Devanagari produced no tokens to search with.

    Those two states are indistinguishable in a recall number and have opposite fixes — one
    is the measured cost of §9.2 and the other is a broken tokeniser that would make any
    future dense arm, any future stopword list and any future index change look fine while
    the caller got silence. `INDIAN_SCRIPT_NAMES` claims ten scripts off one element table;
    this is the assertion that the claim holds for the second of them.

    FAILS IF a Devanagari question yields no query form, or yields a romanised form that is
    still unromanised — which is exactly what a script named in `INDIAN_SCRIPT_NAMES` but
    missing from the element tables would do.
    """
    for fact in _HINDI_CORPUS:
        question = fact["query_hi"]
        assert indian_scripts_in(question) == frozenset({"DEVANAGARI"}), fact["fact_id"]

        forms = query_forms(question)
        assert forms, f"{fact['fact_id']}: no query form survived tokenising"
        # The LAST form is the transliterated one (`query_forms` appends it), and it must be
        # wholly Latin: a leftover akshara means the element tables do not cover this script.
        romanised = forms[-1]
        assert romanised, f"{fact['fact_id']}: the romanised form tokenised to nothing"
        assert all(token.isascii() for token in romanised), (
            f"{fact['fact_id']}: romanised form still carries a non-Latin token: {romanised}"
        )
        # And the raw script form must survive tokenising too — a `\w+` tokeniser splits an
        # akshara cluster at every vowel sign, which is the failure `_TOKEN_RE` exists for.
        assert len(forms[0]) >= 2, f"{fact['fact_id']}: raw Devanagari fell apart: {forms[0]}"


def test_a_nukta_changes_the_consonant_it_sits_under() -> None:
    """THE DEFECT THE SECOND SCRIPT FOUND (D-612), pinned so it cannot come back.

    A nukta is a dot that makes a consonant a DIFFERENT consonant. `transliterate_indic` used
    to skip the mark and keep the base's sound, so `दफ़्तर` romanised as `daphtara` instead of
    `daftara` — while the PRECOMPOSED spelling of the very same word came out right. Telugu
    has no nukta, so a Telugu-only corpus could never have caught it.

    The second assertion is the one that matters most: Unicode spells these letters two ways,
    U+0958..U+095F are composition-excluded so NFC keeps the sequence, and the two spellings
    must romanise IDENTICALLY. They did not.
    """
    assert transliterate_indic("दफ़्तर") == "daftara"
    assert transliterate_indic("ज़्यादा") == "zyādā"
    assert transliterate_indic("गाड़ी") == "gāṛī"
    # Precomposed U+095B ZA and the decomposed JA + NUKTA are the same letter. NFC does not
    # unify them, so this module must.
    assert transliterate_indic("\u095b") == transliterate_indic("\u091c\u093c")
    # Not a Devanagari-only fix: Gurmukhi, Bengali and Oriya carry nuktas too, and the map is
    # derived from Unicode's decompositions rather than typed per script.
    assert transliterate_indic("ਜ਼ਰੂਰੀ") == "zarūrī"


# --- the property that makes every number above a measurement ---------------------------

#: The corpus/form pairs every floor in this file is derived from. One place, so the sweep
#: below cannot fall behind the tests it is guarding.
_MEASURED_ROWS: Final[tuple[tuple[str, list[dict[str, Any]], str], ...]] = (
    ("telugu query_en", _CORPUS, "query_en"),
    ("telugu query_tenglish", _CORPUS, "query_tenglish"),
    ("telugu query_te", _CORPUS, "query_te"),
    ("code-mixed", _CODE_MIXED, "query_code_mixed"),
    ("hindi query_en", _HINDI_CORPUS, "query_en"),
    ("hindi query_hinglish", _HINDI_CORPUS, "query_hinglish"),
    ("hindi query_hi", _HINDI_CORPUS, "query_hi"),
)


def test_the_numbers_do_not_depend_on_the_fixture_label() -> None:
    """EVERY ROW ABOVE MUST BE A PROPERTY OF RETRIEVAL AND OF NOTHING ELSE.

    `_pack_from` derives its tenant, agent, document and chunk ids from a `label` that is
    pure harness bookkeeping — it names nothing a client has and reaches no scoring rule. So
    sweeping the label must not move a single figure. It did: BM25 ties exactly, `_search`
    broke those ties on `str(chunk_id)`, and the same corpus reported Telugu `query_tenglish`
    recall@1 as 0.583 or 0.625 and Hindi `query_hinglish` recall@3 as 0.792 or 0.833 purely
    by which string the harness happened to pass. Both readings were then written into this
    file's docstring and into `docs/PIPECAT-MIGRATION.md` §9.4 as findings.

    Two changes closed it and this is the assertion over both: `_search` now breaks ties by
    pack POSITION (the rule `DenseIndex.search` already used, and the order production packs
    are stored in — `kb/pack.py:171`), and `_recall` refuses to score a fact that merely TIES
    the passage below the cut.

    FAILS IF anything reintroduces an id-dependent ordering — a tie-break on a uuid, a dict
    iteration order reaching a rank, a cache keyed on something incidental. It is worth more
    than any floor here, because a floor only catches a number that got worse and this
    catches a number that was never real.
    """
    labels = ("corpus-en", "a", "zzz", "q7", "sweep-4", "0199c0de")
    for name, facts, query_key in _MEASURED_ROWS:
        readings = {_recall(facts, query_key, label)[:2] for label in labels}
        assert len(readings) == 1, (
            f"{name}: recall moved with the fixture label — {sorted(readings)}. "
            "The label names nothing in the product; a number that depends on it is not a "
            "measurement. Read this test's docstring."
        )


def test_the_whole_golden_set_runs_without_a_network_a_model_or_a_database() -> None:
    """The property that lets this live in CI at all: a pack in memory, a BM25 index, a dict
    walk. FAILS IF an answer ever comes back `temporarily_unavailable`, which is the state
    every load failure collapses into — i.e. the one that would prove this harness quietly
    measured nothing at all.
    """
    for facts, key, label in (
        (_CORPUS, "query_en", "smoke-corpus"),
        (_CODE_MIXED, "query_code_mixed", "smoke-shop"),
        (_HINDI_CORPUS, "query_en", "smoke-hindi"),
        (_HINDI_CORPUS, "query_hi", "smoke-hindi-script"),
    ):
        session, documents = _pack_from(facts, label)
        for fact in facts:
            *_, outcome = _hits(session, documents, fact[key])
            assert outcome != "temporarily_unavailable"
