"""In-call knowledge search: the four states, the gate, and the cross-tenant cache property.

Everything here drives the real thing — a real `KnowledgePack`, a real BM25 index, real
Telugu and Tenglish questions. The only fake is the object-storage fetcher, which is a
protocol precisely so this file needs no network (`voice_worker.knowledge.PackFetcher`).

The Telugu and Tenglish fixtures below follow `tests/fixtures/golden_transcripts.json`'s
register: Telugu grammar in Latin script studded with English nouns, which is the form
`docs/evidence/telugu-embedding-quality.md` §2.1 records Sarvam Saaras actually returning.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from calevate_shared.knowledge_pack import KnowledgePack, PackEntry, pack_object_key
from loguru import logger
from voice_worker.knowledge import (
    AMBIGUITY_MARGIN,
    LexicalIndex,
    PackCache,
    SessionKnowledge,
    has_telugu_script,
    load_session_knowledge,
    query_forms,
    transliterate_telugu,
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
    """The virama deletes the inherent vowel; a vowel sign replaces it."""
    assert transliterate_telugu("డాక్టర్") == "ḍākṭar"
    assert transliterate_telugu("ఆరోగ్యశ్రీ") == "ārōgyaśrī"
    assert transliterate_telugu("appointment") == "appointment"


def test_transliteration_is_not_translation() -> None:
    """The load-bearing negative: romanised Telugu does not match an English gloss.

    If this ever starts passing as equality, somebody has quietly added a translation hop —
    which on this path is a network round trip mid-turn, the one thing the design forbids.
    """
    assert "doctor" not in transliterate_telugu("డాక్టర్")
    assert has_telugu_script("డాక్టర్")
    assert not has_telugu_script("Appointment ela book cheskovali?")


def test_query_forms_add_transliteration_only_for_telugu_script() -> None:
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
