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
(`tests/fixtures/code_mixed_queries.json`). Recall counts the fact's OWN document among the
passages the caller's turn would actually have received, which means an `ambiguous` answer
contributes its two passages and a `not_found` contributes none. That is deliberate: recall
computed over an internal ranking rather than over the returned answer would score a hit the
caller never heard.

**MEASURED 14 Sep 2026, at the commit that wrote this file** (n=24, English-only index,
`DEFAULT_TOP_K`=3):

    query form        recall@1   recall@3   outcomes
    query_en           0.833      0.875     20 found, 4 ambiguous
    query_tenglish     0.583      0.708     17 found, 4 ambiguous, 3 not_found
    query_te           0.083      0.083      2 found, 22 not_found
    code-mixed (n=10)  1.000      1.000     10 found

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
Telugu is not English — `voice_worker.knowledge.transliterate_telugu`'s own docstring says
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
from voice_worker.knowledge import DEFAULT_TOP_K, LexicalIndex, SessionKnowledge

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


def _hits(
    session: SessionKnowledge, documents: dict[UUID, str], question: str
) -> tuple[list[str], str]:
    """The `fact_id`s this turn would have handed the model, best first, and the outcome."""
    answer = session.search(question)
    return [documents[p.provenance.source_id] for p in answer.passages], answer.outcome


def _recall(
    facts: list[dict[str, Any]], query_key: str, label: str, *, k: int
) -> tuple[float, dict[str, int]]:
    """recall@k over the ANSWER, plus the outcome census that explains it.

    A miss is a miss whichever state produced it: `not_found` (the gate refused), `ambiguous`
    (two near-equal candidates, neither the right one) and a confident wrong `found` all
    cost the caller the same thing.
    """
    session, documents = _pack_from(facts, label)
    outcomes: dict[str, int] = {}
    hits = 0
    for fact in facts:
        got, outcome = _hits(session, documents, fact[query_key])
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if fact["fact_id"] in got[:k]:
            hits += 1
    return hits / len(facts), outcomes


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


# --- the floors -------------------------------------------------------------------------


def test_english_queries_hold_their_recall_floor() -> None:
    """THE CONTROL, and the one form production actually runs (§9.1 step 2).

    FAILS IF the index, the tokeniser, the informative-term gate or the ambiguity margin
    stops finding facts for a well-formed English question — the shape of every retrieval
    regression that is not about language at all.
    """
    at_1, outcomes = _recall(_CORPUS, "query_en", "corpus-en", k=1)
    at_3, _ = _recall(_CORPUS, "query_en", "corpus-en", k=DEFAULT_TOP_K)
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
    at_1, outcomes = _recall(_CORPUS, "query_tenglish", "corpus-tenglish", k=1)
    at_3, _ = _recall(_CORPUS, "query_tenglish", "corpus-tenglish", k=DEFAULT_TOP_K)
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
    at_1, outcomes = _recall(_CORPUS, "query_te", "corpus-te", k=1)
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
    english, _ = _recall(_CORPUS, "query_en", "corpus-en", k=1)
    tenglish, _ = _recall(_CORPUS, "query_tenglish", "corpus-tenglish", k=1)
    telugu, _ = _recall(_CORPUS, "query_te", "corpus-te", k=1)
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
    at_1, outcomes = _recall(_CODE_MIXED, "query_code_mixed", "shop-1", k=1)
    at_3, _ = _recall(_CODE_MIXED, "query_code_mixed", "shop-3", k=DEFAULT_TOP_K)
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
        if _hits(session, documents, fact["query_code_mixed"])[1] == "not_found"
    ]
    assert not silent, f"code-mixed questions answered not_found: {silent}"


def test_the_whole_golden_set_runs_without_a_network_a_model_or_a_database() -> None:
    """The property that lets this live in CI at all: a pack in memory, a BM25 index, a dict
    walk. FAILS IF an answer ever comes back `temporarily_unavailable`, which is the state
    every load failure collapses into — i.e. the one that would prove this harness quietly
    measured nothing at all.
    """
    for facts, key, label in (
        (_CORPUS, "query_en", "smoke-corpus"),
        (_CODE_MIXED, "query_code_mixed", "smoke-shop"),
    ):
        session, documents = _pack_from(facts, label)
        for fact in facts:
            _, outcome = _hits(session, documents, fact[key])
            assert outcome != "temporarily_unavailable"
