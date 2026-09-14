"""In-call knowledge search: the four states, the gate, the cross-tenant cache, every script.

Everything here drives the real thing — a real `KnowledgePack`, a real BM25 index, real
questions in real scripts. The only fake is the object-storage fetcher, which is a protocol
precisely so this file needs no network (`voice_worker.knowledge.PackFetcher`).

The Tenglish fixtures follow `tests/fixtures/golden_transcripts.json`'s register: Telugu
grammar in Latin script studded with English nouns, which is the form `docs/evidence/
telugu-embedding-quality.md` §2.1 records Sarvam Saaras actually returning.

**THE SCRIPT FIXTURES ARE REAL SENTENCES, ONE PER SCRIPT, AND THAT IS LOAD-BEARING.** The
product is not Telugu-first: it has to answer a caller in any Indian language our speech
vendors process, and a script suite written in lorem ipsum or in one script's words
transliterated into another's letters would prove nothing about the abugida rules the
romaniser applies. `_SCRIPT_SAMPLES` below is an ordinary small-business question — when do
you open, how much, do you deliver — written once per script, so the assertions are about
text a real caller could have said.
"""

from __future__ import annotations

import sys
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from calevate_shared.knowledge_pack import KnowledgePack, PackEntry, pack_object_key
from loguru import logger
from voice_worker.knowledge import (
    _BRAHMIC_SCRIPT_NAMES,
    _TOKEN_RE,
    AMBIGUITY_MARGIN,
    INDIAN_SCRIPT_NAMES,
    LexicalIndex,
    PackCache,
    SessionKnowledge,
    _classify,
    has_indian_script,
    indian_scripts_in,
    load_session_knowledge,
    query_forms,
    transliterate_indic,
)

# ---------------------------------------------------------------------------------------
# Fixtures: one clinic's published knowledge, and one estate agent's, as real packs.
# ---------------------------------------------------------------------------------------

CLINIC_TENANT = UUID("0199c0de-0000-7000-8000-00000000000a")
CLINIC_AGENT = UUID("0199c0de-0000-7000-8000-00000000000b")
ESTATE_TENANT = UUID("0199c0de-0000-7000-8000-00000000001a")
ESTATE_AGENT = UUID("0199c0de-0000-7000-8000-00000000001b")

HOURS_DOC = UUID("0199c0de-0001-7000-8000-000000000001")
APPOINTMENT_DOC = UUID("0199c0de-0001-7000-8000-000000000002")
INSURANCE_DOC = UUID("0199c0de-0001-7000-8000-000000000003")
CONSULTATION_DOC = UUID("0199c0de-0001-7000-8000-000000000004")
SCAN_DOC = UUID("0199c0de-0001-7000-8000-000000000005")
PARKING_DOC = UUID("0199c0de-0001-7000-8000-000000000006")

#: The Telugu-script half of the clinic's corpus. Written in the register an SMB leaflet
#: uses, same as the evidence document's harness corpus.
HOURS_TE = "క్లినిక్ ఉదయం 9 గంటల నుండి రాత్రి 8 గంటల వరకు తెరిచి ఉంటుంది."
APPOINTMENT_TE = "అపాయింట్‌మెంట్ కోసం రిసెప్షన్‌లో అడగండి."


def _entry(
    document_id: UUID,
    text: str,
    gloss: str | None = None,
    version: int = 1,
) -> PackEntry:
    return PackEntry(
        chunk_id=uuid4(),
        document_id=document_id,
        document_version=version,
        text=text,
        gloss=gloss,
    )


def clinic_entries() -> tuple[PackEntry, ...]:
    return (
        _entry(HOURS_DOC, HOURS_TE, "The clinic is open from 9 am to 8 pm on weekdays.", 3),
        _entry(APPOINTMENT_DOC, APPOINTMENT_TE, "Appointment: call the front desk to book a slot."),
        # ENGLISH ONLY, NO GLOSS — the entry that can only be reached from a Telugu-script
        # question by way of transliteration, which is what makes that test a real one.
        _entry(INSURANCE_DOC, "Arogyasri cashless insurance is accepted at the reception."),
        # Two documents, near-identical shape, same fee. The `ambiguous` fixture: a caller
        # asking about "fees" has named a category, not a thing.
        _entry(CONSULTATION_DOC, "Consultation fee is five hundred rupees."),
        _entry(SCAN_DOC, "Scan fee is five hundred rupees."),
        _entry(PARKING_DOC, "Parking is available in the basement for two wheelers."),
    )


def estate_entries() -> tuple[PackEntry, ...]:
    return (
        _entry(uuid4(), "The Kondapur project has 2BHK and 3BHK flats facing east."),
        _entry(uuid4(), "Site visits happen on Saturday and Sunday between 10 am and 5 pm."),
    )


def build_pack(tenant_id: UUID, agent_id: UUID, entries: tuple[PackEntry, ...]) -> KnowledgePack:
    return KnowledgePack(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content_sha256=KnowledgePack.digest(tenant_id, agent_id, entries),
        built_at=datetime(2026, 9, 14, 6, 0, tzinfo=UTC),
        entries=entries,
    )


class DictFetcher:
    """Object storage as a dict. Satisfies `PackFetcher` structurally, nothing more."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}
        self.calls: list[str] = []

    def store(self, pack: KnowledgePack) -> None:
        key = pack_object_key(pack.tenant_id, pack.agent_id, pack.content_sha256)
        self.objects[key] = pack.model_dump_json().encode()

    async def fetch(self, object_key: str) -> bytes | None:
        self.calls.append(object_key)
        return self.objects.get(object_key)


class ExplodingFetcher:
    async def fetch(self, object_key: str) -> bytes | None:
        raise TimeoutError("object storage did not answer")


async def load_clinic(
    cache: PackCache | None = None,
    fetcher: DictFetcher | None = None,
) -> tuple[SessionKnowledge, KnowledgePack, DictFetcher, PackCache]:
    pack = build_pack(CLINIC_TENANT, CLINIC_AGENT, clinic_entries())
    fetcher = fetcher or DictFetcher()
    fetcher.store(pack)
    cache = cache or PackCache()
    session = await load_session_knowledge(
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256=pack.content_sha256,
        fetcher=fetcher,
        cache=cache,
    )
    return session, pack, fetcher, cache


# ---------------------------------------------------------------------------------------
# Transliteration — what it does, and the thing it explicitly does NOT do.
# ---------------------------------------------------------------------------------------


def test_transliteration_is_akshara_correct() -> None:
    """The virama deletes the inherent vowel; a vowel sign replaces it.

    Telugu and Devanagari side by side, because the rule is the SCRIPT-INDEPENDENT abugida
    rule and these two exercise it from different blocks with one table. The Telugu values
    are unchanged from the hand-written table this replaced, which is how we know the
    generalisation did not quietly move the one script we have a measurement for.
    """
    assert transliterate_indic("డాక్టర్") == "ḍākṭar"
    assert transliterate_indic("ఆరోగ్యశ్రీ") == "ārōgyaśrī"
    assert transliterate_indic("appointment") == "appointment"
    # Devanagari: the same virama, the same inherent vowel, no second table.
    assert transliterate_indic("दुकान") == "dukāna"
    assert transliterate_indic("मुंबई") == "munbaī"


def test_a_final_schwa_is_kept_because_deleting_it_needs_a_language_we_do_not_have() -> None:
    """Hindi speech drops the last `a` of `डॉक्टर`; Devanagari does not write that, and this
    module sees a SCRIPT and never a language. The romanisation is faithful to what is
    written — see `transliterate_indic`'s docstring for why guessing is worse."""
    assert transliterate_indic("डॉक्टर") == "ḍôkṭara"


def test_transliteration_is_not_translation() -> None:
    """The load-bearing negative: romanised Telugu does not match an English gloss.

    If this ever starts passing as equality, somebody has quietly added a translation hop —
    which on this path is a network round trip mid-turn, the one thing the design forbids.
    """
    assert "doctor" not in transliterate_indic("డాక్టర్")
    assert "doctor" not in transliterate_indic("डॉक्टर")
    assert has_indian_script("డాక్టర్")
    assert not has_indian_script("Appointment ela book cheskovali?")


def test_query_forms_add_transliteration_only_for_an_indian_script() -> None:
    tenglish = query_forms("Appointment ela book cheskovali?")
    assert tenglish == (("appointment", "book"),)  # `ela`/`cheskovali` are function words

    telugu = query_forms("ఆరోగ్యశ్రీ ఉందా?")
    assert telugu[0] == ("ఆరోగ్యశ్రీ", "ఉందా")
    assert ("arogyasri",) in telugu


def test_query_forms_drop_a_question_with_no_topic_in_it() -> None:
    assert query_forms("What is it?") == ()


# ---------------------------------------------------------------------------------------
# The four states.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenglish_question_finds_the_english_gloss() -> None:
    """THE POINT OF THE GLOSS, measured in §4 and asserted here.

    The question is Telugu grammar in Latin script; the entry it must find is a Telugu-script
    passage whose only English is its gloss.
    """
    session, _pack, _fetcher, _cache = await load_clinic()
    answer = session.search("Appointment ela book cheskovali?")

    assert answer.outcome == "found"
    assert answer.passages[0].provenance.source_id == APPOINTMENT_DOC
    # The caller is answered from the APPROVED text, never from the retrieval key.
    assert answer.passages[0].text == APPOINTMENT_TE
    assert answer.elapsed_ms > 0.0


@pytest.mark.asyncio
async def test_telugu_script_question_finds_its_telugu_passage() -> None:
    session, _pack, _fetcher, _cache = await load_clinic()
    answer = session.search("క్లినిక్ ఎన్ని గంటలకు తెరుస్తారు?")

    assert answer.outcome == "found"
    assert answer.passages[0].provenance.source_id == HOURS_DOC
    # Provenance carries the revision that was published, so an answer given on a call is
    # traceable to the words that were live when it was given.
    # The revision is asserted on the FIELD, not on the sentence. It moved there when
    # `Provenance.document_version` landed (D-599): a report asking which words were
    # published when an answer was given can query an int and cannot parse prose.
    assert answer.passages[0].provenance.document_version == 3
    assert answer.passages[0].provenance.label == "published knowledge"
    assert answer.passages[0].provenance.agent_id == CLINIC_AGENT
    assert answer.passages[0].provenance.tier == "t3"


@pytest.mark.asyncio
async def test_transliteration_reaches_an_english_only_entry() -> None:
    """A Telugu-script question against an English-only entry: zero shared tokens before
    transliteration, a match after. This is the whole and only claim made for it."""
    session, _pack, _fetcher, _cache = await load_clinic()
    index = session.index
    assert index is not None

    raw_form = query_forms("ఆరోగ్యశ్రీ ఉందా?")[0]
    assert index.search([raw_form]) == {}  # nothing, without transliteration

    answer = session.search("ఆరోగ్యశ్రీ ఉందా?")
    assert answer.outcome == "found"
    assert answer.passages[0].provenance.source_id == INSURANCE_DOC


@pytest.mark.asyncio
async def test_a_question_the_corpus_says_nothing_about_is_not_found() -> None:
    """THE GATE. `telugu-embedding-quality.md` §4(b) is the reason this test exists: a
    ranking built from words that carry no information about the corpus is not a weak
    answer, it is an absence, and presenting the top row of it would be an invention."""
    session, _pack, _fetcher, _cache = await load_clinic()
    answer = session.search("Do you rent bicycles in Warangal?")

    assert answer.outcome == "not_found"
    assert answer.passages == ()
    assert answer.elapsed_ms > 0.0


@pytest.mark.asyncio
async def test_a_category_question_across_two_documents_is_ambiguous() -> None:
    session, _pack, _fetcher, _cache = await load_clinic()
    answer = session.search("What is the fee?")

    assert answer.outcome == "ambiguous"
    assert len(answer.passages) == 2
    documents = {passage.provenance.source_id for passage in answer.passages}
    assert documents == {CONSULTATION_DOC, SCAN_DOC}


@pytest.mark.asyncio
async def test_two_spans_of_one_document_are_not_ambiguous() -> None:
    """Ambiguity is about two ANSWERS, not two chunks of one. Same document, same fact."""
    entries = (
        _entry(HOURS_DOC, "Weekday hours are 9 am to 8 pm at the Kukatpally branch."),
        _entry(HOURS_DOC, "Weekend hours are 9 am to 1 pm at the Kukatpally branch."),
    )
    pack = build_pack(CLINIC_TENANT, CLINIC_AGENT, entries)
    fetcher = DictFetcher()
    fetcher.store(pack)
    session = await load_session_knowledge(
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256=pack.content_sha256,
        fetcher=fetcher,
        cache=PackCache(),
    )
    answer = session.search("Kukatpally hours?")
    assert answer.outcome == "found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fetcher_factory", "reason"),
    [
        (lambda pack: ExplodingFetcher(), "fetch_failed"),
        (lambda pack: DictFetcher(), "absent"),
    ],
)
async def test_a_pack_that_does_not_load_is_a_state_not_an_exception(
    fetcher_factory: Any, reason: str
) -> None:
    pack = build_pack(CLINIC_TENANT, CLINIC_AGENT, clinic_entries())
    session = await load_session_knowledge(
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256=pack.content_sha256,
        fetcher=fetcher_factory(pack),
        cache=PackCache(),
    )

    assert session.unavailable_reason == reason
    assert not session.available
    answer = session.search("Appointment ela book cheskovali?")
    assert answer.outcome == "temporarily_unavailable"
    assert answer.passages == ()
    assert answer.elapsed_ms > 0.0


@pytest.mark.asyncio
async def test_an_unknown_format_version_is_refused_rather_than_half_parsed() -> None:
    entries = clinic_entries()
    digest = KnowledgePack.digest(CLINIC_TENANT, CLINIC_AGENT, entries)
    future = KnowledgePack(
        format_version=2,
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256=digest,
        built_at=datetime(2026, 9, 14, 6, 0, tzinfo=UTC),
        entries=entries,
    )
    key = pack_object_key(CLINIC_TENANT, CLINIC_AGENT, digest)
    fetcher = DictFetcher({key: future.model_dump_json().encode()})

    session = await load_session_knowledge(
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256=digest,
        fetcher=fetcher,
        cache=PackCache(),
    )
    assert session.unavailable_reason == "unsupported_format"
    assert session.search("fee?").outcome == "temporarily_unavailable"


# ---------------------------------------------------------------------------------------
# The cache, and the property a reused container has to have.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_warm_container_serves_the_second_session_from_cache() -> None:
    session, pack, fetcher, cache = await load_clinic()
    assert session.available
    assert len(fetcher.calls) == 1

    again = await load_session_knowledge(
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256=pack.content_sha256,
        fetcher=fetcher,
        cache=cache,
    )
    assert again.available
    assert len(fetcher.calls) == 1  # no second fetch
    assert again.search("Appointment ela book cheskovali?").outcome == "found"


@pytest.mark.asyncio
async def test_clinic_a_cannot_be_answered_out_of_clinic_bs_pack() -> None:
    """THE TENANCY PROPERTY, on the container Pipecat Cloud reuses.

    One cache, two tenants, in the order a warm instance would actually see them. The second
    session must see only its own knowledge — not because anybody remembered to clear
    anything, but because a content digest cannot name two different byte strings.
    """
    cache = PackCache()
    clinic_session, clinic_pack, fetcher, _cache = await load_clinic(cache=cache)
    estate_pack = build_pack(ESTATE_TENANT, ESTATE_AGENT, estate_entries())
    fetcher.store(estate_pack)

    estate_session = await load_session_knowledge(
        tenant_id=ESTATE_TENANT,
        agent_id=ESTATE_AGENT,
        content_sha256=estate_pack.content_sha256,
        fetcher=fetcher,
        cache=cache,
    )

    assert clinic_pack.content_sha256 != estate_pack.content_sha256
    assert estate_session.search("Arogyasri insurance accepted?").outcome == "not_found"
    assert estate_session.search("Kondapur 2BHK flats?").outcome == "found"
    # ... and the clinic's own session is untouched by any of it.
    assert clinic_session.search("Arogyasri insurance accepted?").outcome == "found"


def test_a_cached_pack_whose_identity_disagrees_is_evicted_not_served() -> None:
    """The belt beside the braces: a hit is re-checked against the session's tenant and
    agent, and a disagreeing entry is REMOVED so the next caller cannot be handed it."""
    cache = PackCache()
    pack = build_pack(CLINIC_TENANT, CLINIC_AGENT, clinic_entries())
    cache.put(pack, LexicalIndex(pack.entries))

    assert cache.get(pack.content_sha256, tenant_id=ESTATE_TENANT, agent_id=ESTATE_AGENT) is None
    assert cache.keys == ()
    assert cache.get(pack.content_sha256, tenant_id=CLINIC_TENANT, agent_id=CLINIC_AGENT) is None


@pytest.mark.asyncio
async def test_bytes_that_are_not_the_pack_we_asked_for_never_reach_the_cache() -> None:
    """A hostile or misconfigured store serving clinic A's object under clinic B's key."""
    clinic_pack = build_pack(CLINIC_TENANT, CLINIC_AGENT, clinic_entries())
    estate_pack = build_pack(ESTATE_TENANT, ESTATE_AGENT, estate_entries())
    wrong_key = pack_object_key(ESTATE_TENANT, ESTATE_AGENT, estate_pack.content_sha256)
    fetcher = DictFetcher({wrong_key: clinic_pack.model_dump_json().encode()})
    cache = PackCache()

    session = await load_session_knowledge(
        tenant_id=ESTATE_TENANT,
        agent_id=ESTATE_AGENT,
        content_sha256=estate_pack.content_sha256,
        fetcher=fetcher,
        cache=cache,
    )
    assert session.unavailable_reason == "identity_mismatch"
    assert cache.keys == ()
    assert session.search("Kondapur 2BHK flats?").outcome == "temporarily_unavailable"


def test_the_cache_is_bounded_and_evicts_least_recently_used() -> None:
    cache = PackCache(max_entries=2)
    packs = [
        build_pack(uuid4(), uuid4(), (_entry(uuid4(), f"Fact number {n} about the branch."),))
        for n in range(3)
    ]
    for pack in packs[:2]:
        cache.put(pack, LexicalIndex(pack.entries))
    # Touch the oldest so it is no longer least-recently-used.
    cache.get(packs[0].content_sha256, tenant_id=packs[0].tenant_id, agent_id=packs[0].agent_id)
    cache.put(packs[2], LexicalIndex(packs[2].entries))

    assert len(cache) == 2
    assert packs[1].content_sha256 not in cache.keys
    assert packs[0].content_sha256 in cache.keys


# ---------------------------------------------------------------------------------------
# Hard rule 6.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_the_caller_or_the_corpus_said_reaches_the_log() -> None:
    session, _pack, _fetcher, _cache = await load_clinic()
    captured: list[str] = []

    def sink(message: Any) -> None:
        # BOTH halves: loguru's rendered line AND the structured `extra` payload, because a
        # leak into a keyword argument would not show up in the message at all.
        captured.append(str(message) + repr(message.record["extra"]))

    handler = logger.add(sink, level="DEBUG")
    try:
        answer = session.search("Appointment ela book cheskovali?")
    finally:
        logger.remove(handler)

    assert answer.outcome == "found"
    blob = "\n".join(captured)
    assert blob  # the lookup did log something, or this test proves nothing
    for forbidden in (
        "Appointment ela book cheskovali",  # the caller's question
        APPOINTMENT_TE,  # the passage
        "call the front desk to book a slot",  # the gloss
    ):
        assert forbidden not in blob
    assert "found" in blob
    assert "elapsed_ms" in blob


# ---------------------------------------------------------------------------------------
# The thresholds are constants, and they are named as starting points.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_word_true_of_the_whole_pack_is_not_evidence_about_which_entry() -> None:
    """THE DF GATE, on a corpus big enough for document frequency to be a measurement.

    Twelve entries that all say "clinic": a caller who says only that has not told us which
    entry to read, and BM25 will still happily rank them. `not_found` is the honest answer.
    """
    entries = tuple(
        _entry(uuid4(), f"The clinic handles matter number {n} at the Kukatpally branch.")
        for n in range(12)
    )
    pack = build_pack(CLINIC_TENANT, CLINIC_AGENT, entries)
    fetcher = DictFetcher()
    fetcher.store(pack)
    session = await load_session_knowledge(
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256=pack.content_sha256,
        fetcher=fetcher,
        cache=PackCache(),
    )

    assert session.search("clinic").outcome == "not_found"
    # ... while a word that names ONE of them still answers.
    assert session.search("matter number 7").outcome == "found"


def test_the_ambiguity_margin_is_a_fraction_not_a_score() -> None:
    """It is compared against `(top - runner_up) / top`, so it has to live in (0, 1) — a
    value outside that would make every answer ambiguous or none of them."""
    assert 0.0 < AMBIGUITY_MARGIN < 1.0


# ---------------------------------------------------------------------------------------
# Every script our speech vendors can process, not just the one we happened to start with.
# ---------------------------------------------------------------------------------------

#: One ordinary small-business question per script: opening time, price, delivery, a size.
#: Real words in every case — a transliterated-into-the-wrong-alphabet sample would exercise
#: the tables without exercising the orthography, which is the whole thing under test.
#:
#: ⚠ WHAT THIS SUITE ASSERTS IS SCRIPT HANDLING, NOT TRANSLATION. Nobody here is claiming a
#: gloss for these sentences, and nothing in the module produces one (`transliterate_indic`
#: is romanisation, never translation). The assertions are about detection, the abugida
#: rules and the four outcomes.
#:
#: The script → language mapping is the vendor's, read from the installed pipecat 1.10.0
#: (`pipecat/services/sarvam/stt.py:800-825` for STT's 25 codes, `.../tts.py:218-242` for
#: TTS's 11 locales) — see `INDIAN_SCRIPT_NAMES` for the derivation and for the two vendor
#: languages (Santali, Manipuri) whose scripts are deliberately not covered.
_SCRIPT_SAMPLES: tuple[tuple[str, str], ...] = (
    ("TELUGU", "దుకాణం ఉదయం ఎన్ని గంటలకు తెరుస్తారు?"),  # te-IN
    ("DEVANAGARI", "दुकान कितने बजे खुलती है?"),  # hi-IN, mr-IN, kok-IN, mai-IN
    ("BENGALI", "দোকান কখন খোলে?"),  # bn-IN, as-IN
    ("GUJARATI", "દુકાન કેટલા વાગે ખૂલે છે?"),  # gu-IN
    ("GURMUKHI", "ਦੁਕਾਨ ਕਿੰਨੇ ਵਜੇ ਖੁੱਲ੍ਹਦੀ ਹੈ?"),  # pa-IN
    ("KANNADA", "ಅಂಗಡಿ ಎಷ್ಟು ಗಂಟೆಗೆ ತೆರೆಯುತ್ತದೆ?"),  # kn-IN
    ("MALAYALAM", "കട എപ്പോൾ തുറക്കും?"),  # ml-IN
    ("ORIYA", "ଦୋକାନ କେତେବେଳେ ଖୋଲେ?"),  # or-IN / od-IN — the two spellings, one script
    ("TAMIL", "கடை எத்தனை மணிக்கு திறக்கும்?"),  # ta-IN
    ("ARABIC", "دکان کتنے بجے کھلتی ہے؟"),  # ur-IN, and sd-IN in the same script
)


@pytest.mark.parametrize(("script", "question"), _SCRIPT_SAMPLES)
def test_every_vendor_script_is_detected_as_itself(script: str, question: str) -> None:
    """Detection names the script, and names ONLY that script."""
    assert indian_scripts_in(question) == frozenset({script})
    assert has_indian_script(question)


def test_a_latin_question_is_not_mistaken_for_an_indian_one() -> None:
    """The form production actually runs (`docs/PIPECAT-MIGRATION.md` §9.1 step 2 hands this
    index an ENGLISH query) must not pick up a transliteration pass it has no use for."""
    for question in (
        "What time does the shop open on Sunday?",
        "Appointment ela book cheskovali?",  # Tenglish is Latin script, whatever else it is
        "Delivery charge ₹40 — UPI ok?",  # a currency sign and a dash are not a script
    ):
        assert indian_scripts_in(question) == frozenset()
        assert not has_indian_script(question)
        assert transliterate_indic(question) == question


def test_a_question_mixing_two_scripts_reports_both_and_romanises_both() -> None:
    """A caller who says an English noun, a Telugu verb and a Hindi auxiliary in one breath
    is ordinary, not exotic. Every Indic run romanises; the Latin run is left alone."""
    mixed = "Delivery ఎప్పుడు होगी?"
    assert indian_scripts_in(mixed) == frozenset({"TELUGU", "DEVANAGARI"})

    romanised = transliterate_indic(mixed)
    assert indian_scripts_in(romanised) == frozenset()  # nothing left half-transliterated
    assert "Delivery" in romanised

    forms = query_forms(mixed)
    assert any("delivery" in form for form in forms)


@pytest.mark.parametrize(("script", "question"), _SCRIPT_SAMPLES)
def test_query_forms_are_usable_for_every_script(script: str, question: str) -> None:
    """Usable means two things, and the Perso-Arabic row differs on the second.

    For every script: at least one form, and no form is empty — a question in an Indian
    script must never arrive at the index as nothing at all.

    For a BRAHMIC script only: one of those forms is the romanised one, and it is plain
    mark-folded Latin, which is the form that can share a token with an English corpus.
    Perso-Arabic gets no such form on purpose (`_BRAHMIC_SCRIPT_NAMES` records why: Urdu
    writes no short vowels, so the romanisation would be a consonant skeleton that matches
    nothing while looking like a word).
    """
    forms = query_forms(question)
    assert forms
    assert all(form for form in forms)

    latin_forms = [form for form in forms if all(token.isascii() for token in form)]
    if script == "ARABIC":
        assert not latin_forms
    else:
        assert latin_forms, "a Brahmic question must reach the index in a Latin form too"
        assert all(token.isalnum() for form in latin_forms for token in form)


@pytest.mark.asyncio
@pytest.mark.parametrize(("script", "question"), _SCRIPT_SAMPLES)
async def test_search_answers_every_script_and_never_raises(script: str, question: str) -> None:
    """THE PUBLIC CONTRACT, over the whole vendor script list.

    "It did not raise" is not the assertion — an outcome that matches its evidence is. The
    Telugu row is the one that FINDS something, and that is not a fixture accident worth
    hiding: this pack has a Telugu-script passage about opening hours, the Telugu question
    shares a written word with it, and the raw query form is the one that carries the match
    (no romanisation involved). Every other script asks the same question of a pack that
    holds nothing in it, and gets the word for an absence.

    Both halves matter. A tokeniser that shattered a script into nothing would answer
    `not_found` too — which is why `test_query_forms_are_usable_for_every_script` stands
    beside this one — and a gate that answered `found` for all of them would be the §4(b)
    trap the module exists to avoid.
    """
    session, _pack, _fetcher, _cache = await load_clinic()
    answer = session.search(question)

    assert answer.outcome in {"found", "ambiguous", "not_found", "temporarily_unavailable"}
    assert answer.outcome == ("found" if script == "TELUGU" else "not_found")
    assert bool(answer.passages) is (answer.outcome != "not_found")
    assert answer.elapsed_ms > 0.0


@pytest.mark.asyncio
async def test_an_unavailable_session_still_answers_every_script() -> None:
    """The failure state has to be script-blind too: the load failed before any question was
    asked, so every script gets the same word and none of them reaches the tokeniser."""
    session = await load_session_knowledge(
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256="0" * 64,
        fetcher=ExplodingFetcher(),
        cache=PackCache(),
    )
    for _script, question in _SCRIPT_SAMPLES:
        assert session.search(question).outcome == "temporarily_unavailable"


@pytest.mark.asyncio
async def test_a_devanagari_question_reaches_a_latin_entry_the_way_a_telugu_one_does() -> None:
    """The mechanism transliteration is worth, proved on a SECOND script and a second block.

    `tests/in_call_retrieval_recall_test.py` measures the whole of it at 2 facts in 24, and
    this is the shape those two have: a word the corpus spells in Latin exactly as the
    romaniser spells it — a dish, a brand, a place. `समोसा` → `samōsā` → mark-folded
    `samosa`, and the entry says "samosa". Before transliteration the question and the
    corpus share NOT ONE token, which is the first assertion here.

    What it does NOT do is translate: `मिठाई` would romanise to `miṭhāī` and would not reach
    an entry that says "sweets". That negative is asserted for Telugu in
    `test_transliteration_is_not_translation` and holds identically here, one table for both.
    """
    entries = (
        _entry(uuid4(), "Samosa is fried fresh every evening at six."),
        _entry(uuid4(), "The shop is closed on Tuesday."),
    )
    pack = build_pack(CLINIC_TENANT, CLINIC_AGENT, entries)
    fetcher = DictFetcher()
    fetcher.store(pack)
    session = await load_session_knowledge(
        tenant_id=CLINIC_TENANT,
        agent_id=CLINIC_AGENT,
        content_sha256=pack.content_sha256,
        fetcher=fetcher,
        cache=PackCache(),
    )
    index = session.index
    assert index is not None

    question = "समोसा कितने बजे बनता है?"
    assert index.search([query_forms(question)[0]]) == {}  # nothing, without transliteration

    answer = session.search(question)
    assert answer.outcome == "found"
    assert answer.passages[0].text.startswith("Samosa")


# ---------------------------------------------------------------------------------------
# The tables are checked against `unicodedata`, which is the authority they were built from.
# ---------------------------------------------------------------------------------------

#: Letters of a covered script that `_classify` deliberately does not romanise. All three are
#: non-phonemic: two Vedic anusvara LETTERS (the ordinary anusvara is a SIGN and is mapped)
#: and the Devanagari glottal stop, which is a transcription mark for other languages. None
#: occurs in a sentence a caller would say to a shop.
_UNROMANISED_LETTERS: frozenset[str] = frozenset(
    {
        "BENGALI LETTER VEDIC ANUSVARA",
        "MALAYALAM LETTER VEDIC ANUSVARA",
        "DEVANAGARI LETTER GLOTTAL STOP",
    }
)


def test_every_letter_and_vowel_sign_of_every_covered_script_romanises() -> None:
    """THE TABLE IS VERIFIED AGAINST ITS SOURCE, not against the person who typed it.

    `knowledge.py` types no codepoints: it keys on the name ELEMENT and lets `unicodedata`
    supply the characters. This walks the other way — every codepoint whose Unicode name
    says it is a LETTER or a VOWEL SIGN of a script we cover must come back romanised, or be
    one of the three named above.

    If a Unicode upgrade adds a letter to one of these scripts, THIS is the test that fails,
    and the failure is the decision it asks for: what does the new letter romanise to?
    """
    unromanised = set()
    for codepoint in range(0x110000):
        character = chr(codepoint)
        name = unicodedata.name(character, "")
        script, _, element = name.partition(" ")
        if script not in _BRAHMIC_SCRIPT_NAMES:
            continue
        if not element.startswith(("LETTER ", "VOWEL SIGN ")):
            continue
        if _classify(character) is None:
            unromanised.add(name)

    assert unromanised == _UNROMANISED_LETTERS


def test_the_mark_class_covers_every_script_including_above_the_bmp() -> None:
    """The character class is DERIVED, and this is what says the derivation is complete.

    It is here because the first draft of `_combining_mark_ranges` scanned the BMP only, on
    a premise — "no script we cover keeps a combining mark above U+FFFF" — that was true on
    Unicode 14.0 and FALSE on the 15.0 this repo runs, which put the Arabic Extended-C marks
    at U+10EFC. Nothing would have failed: Urdu tokens would just have started splitting in
    a later interpreter. So the assertion is over the WHOLE repertoire of every covered
    script, and it is written against `unicodedata` rather than against a range.
    """
    uncovered = [
        unicodedata.name(chr(codepoint), "")
        for codepoint in range(sys.maxunicode + 1)
        if unicodedata.category(chr(codepoint)) in {"Mc", "Me", "Mn"}
        and unicodedata.name(chr(codepoint), "").partition(" ")[0] in INDIAN_SCRIPT_NAMES
        and not _TOKEN_RE.fullmatch("a" + chr(codepoint))
    ]
    assert uncovered == []


@pytest.mark.parametrize(("script", "question"), _SCRIPT_SAMPLES)
def test_the_tokeniser_does_not_split_a_word_at_its_vowel_signs(script: str, question: str) -> None:
    """A vowel sign is category Mc and `\\w` is alphanumeric, so the naive pattern shatters
    every akshara cluster. One token per written word is the property; the word count comes
    from the spaces in the sample, which is a fact about the string and not about the
    language."""
    words = question.rstrip("?؟").split()
    forms = query_forms(question)
    assert forms
    assert len(forms[0]) <= len(words)
    assert len(forms[0]) >= 1
