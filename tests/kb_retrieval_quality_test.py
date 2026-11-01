"""Retrieval quality over a fixed corpus, through the one entry point (`retrieval.service.
look_up`), with the KEYWORD arm alone so it runs with no network in CI.

Three business types, questions in English (short and long, natural), Tenglish and Telugu
script, with facts that live in spreadsheet rows and in a price list longer than T0's
budget. The floors are measured on this corpus and only go up; a change that loses a
question shows here as a number, not as a client's "the agent did not know".

Also the individual defects the golden set guards: the keyword arm ANDing every word, the
price question routed to T0 alone, the source name missing from the keyword key, and Pip
seeing part of a passage or only the undelivered ones.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.copilot import tools as copilot_tools
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval import service as retrieval_service
from apps.api.retrieval.pgvector import PgVectorRetriever
from apps.api.retrieval.routing import classify
from apps.api.retrieval.shadow import SHADOW_OFF
from calevate_shared.retrieval import Passage, Provenance, RetrievalRequest, RetrievalResult
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

# --- the corpus ------------------------------------------------------------------------

_MENU_ROWS = [
    ("Plain dosa", 60),
    ("Masala dosa", 80),
    ("Onion uttapam", 90),
    ("Idli (2 pieces)", 40),
    ("Medu vada (2 pieces)", 50),
    ("Pongal", 70),
    ("Upma", 55),
    ("Puri with potato curry", 75),
    ("Veg meals (unlimited)", 150),
    ("Curd rice", 80),
    ("Lemon rice", 75),
    ("Tomato rice", 75),
    ("Veg fried rice", 140),
    ("Egg fried rice", 160),
    ("Chicken fried rice", 190),
    ("Gobi manchurian", 150),
    ("Paneer butter masala", 210),
    ("Kadai paneer", 220),
    ("Dal tadka", 140),
    ("Butter naan", 45),
    ("Tandoori roti", 30),
    ("Veg biryani", 180),
    ("Egg biryani", 200),
    ("Chicken dum biryani", 260),
    ("Chicken biryani (family pack)", 720),
    ("Mutton biryani", 340),
    ("Mutton biryani (family pack)", 950),
    ("Chicken 65", 230),
    ("Apollo fish", 280),
    ("Prawns fry", 320),
    ("Chilli chicken", 240),
    ("Tomato soup", 90),
    ("Sweet corn soup", 100),
    ("Gulab jamun (2 pieces)", 60),
    ("Double ka meetha", 90),
    ("Qubani ka meetha", 120),
    ("Filter coffee", 30),
    ("Masala tea", 25),
    ("Fresh lime soda", 60),
    ("Mango lassi", 90),
    ("Buttermilk", 30),
]

_MENU = "\n".join(f"{item} - Rs {price} per serving, made fresh" for item, price in _MENU_ROWS)

RESTAURANT: dict[str, str] = {
    "Menu": _MENU,
    "Timings": (
        "We are open from 11 am to 11 pm every day. The kitchen closes at 10:30 pm. "
        "Breakfast is served on Sundays from 8 am to 11 am."
    ),
    "Delivery": (
        "Home delivery is available within 5 km of the restaurant. The delivery charge is "
        "Rs 30 for orders below Rs 300 and free above Rs 300. Bulk orders for parties need "
        "one day notice."
    ),
    "తెలుగు మెనూ": "దోశ - 60 రూపాయలు\nఇడ్లీ - 40 రూపాయలు\nబిర్యానీ - 260 రూపాయలు",
}

#: (question, a substring the right passage holds)
RESTAURANT_QUESTIONS: list[tuple[str, str]] = [
    ("How much is the mutton biryani family pack?", "Rs 950"),
    ("mutton biryani family pack rate entha", "Rs 950"),
    (
        "Could you please tell me what you charge for two pieces of gulab jamun these days?",
        "Gulab jamun",
    ),
    ("gulab jamun price", "Gulab jamun"),
    ("veg fried rice entha", "Veg fried rice"),
    ("paneer butter masala cost", "Paneer butter masala"),
    ("qubani ka meetha undha", "Qubani"),
    ("mango lassi rate", "Mango lassi"),
    ("What time do you open in the morning and when do you close at night?", "11 am to 11 pm"),
    ("Sunday breakfast untunda?", "Breakfast is served on Sundays"),
    ("Is there a delivery charge if my order is less than three hundred rupees?", "Rs 30"),
    ("delivery free aa above 300", "Rs 30"),
    ("party bulk orders ki notice entha", "Bulk orders"),
    (
        "Do you deliver to homes that are more than five kilometres away from the restaurant?",
        "within 5 km",
    ),
    ("దోశ ధర", "దోశ"),
    ("ఇడ్లీ", "ఇడ్లీ"),
]

GUEST_HOUSE: dict[str, str] = {
    # Spreadsheet rows, the shape `workers/document_text.py` hands the chunker.
    "Room tariff": "\n".join(
        [
            "Room type: Standard | Price per night: Rs 1800 | Guests: 2 | AC: No",
            "Room type: Deluxe | Price per night: Rs 2500 | Guests: 2 | AC: Yes",
            "Room type: Family suite | Price per night: Rs 3500 | Guests: 4 | AC: Yes",
            "Room type: Dormitory bed | Price per night: Rs 600 | Guests: 1 | AC: No",
            "Extra bed: Rs 500 per night",
            "Breakfast: Rs 150 per guest",
        ]
    ),
    "Stay rules": (
        "Check-in is from 12 noon and check-out is by 11 am. Every guest must show a "
        "government photo ID at check-in. Pets are not allowed. Early check-in from 8 am "
        "costs Rs 300, subject to availability."
    ),
    "Location and parking": (
        "We are 2 km from the bus stand, opposite the city park. Free parking for "
        "two-wheelers and cars inside the compound."
    ),
    "గది ధరలు": "\n".join(
        ["సాధారణ గది - 1800 రూపాయలు", "డీలక్స్ గది - 2500 రూపాయలు", "ఫ్యామిలీ గది - 3500 రూపాయలు"]
    ),
}

GUEST_HOUSE_QUESTIONS: list[tuple[str, str]] = [
    ("What is the price of a deluxe room for one night?", "Rs 2500"),
    ("deluxe room rent entha", "Rs 2500"),
    ("family suite tariff", "Family suite"),
    ("How many guests can stay in the family suite?", "Guests: 4"),
    ("dormitory bed price", "Dormitory"),
    ("extra bed charges", "Extra bed"),
    ("Is breakfast included or do I have to pay for it separately?", "Breakfast: Rs 150"),
    ("check out time enti", "check-out is by 11 am"),
    ("What time can I check in if my bus arrives very early in the morning?", "Early check-in"),
    ("Do I need to carry any identity proof when I come to stay?", "photo ID"),
    ("pets allowed aa", "Pets are not allowed"),
    ("Where exactly are you located and is it far from the bus stand?", "bus stand"),
    ("car parking undha", "parking"),
    ("డీలక్స్ గది", "డీలక్స్"),
    ("ఫ్యామిలీ గది ధర", "ఫ్యామిలీ"),
]

COACHING: dict[str, str] = {
    "Course fees": "\n".join(
        [
            "Course: Spoken English | Duration: 3 months | Fee: Rs 6000",
            "Course: Python programming | Duration: 2 months | Fee: Rs 8000",
            "Course: Tally accounting | Duration: 6 weeks | Fee: Rs 4500",
            "Course: Group 2 exam coaching | Duration: 6 months | Fee: Rs 15000",
            "Course: Basic computers | Duration: 1 month | Fee: Rs 2500",
            "Study material: Rs 800, paid once",
        ]
    ),
    "Batch timings": (
        "Morning batch runs from 7 am to 9 am. Evening batch runs from 6 pm to 8 pm. "
        "Weekend batch runs on Saturday and Sunday from 10 am to 1 pm."
    ),
    "Refund policy": (
        "Fees are refunded in full if you cancel within 7 days of joining. After 7 days "
        "there is no refund, but you may move to a later batch once."
    ),
    "Demo class": (
        "A free demo class is held every Monday at 5 pm. Register by WhatsApp on the "
        "number on our board."
    ),
    "కోర్సు ఫీజు": "స్పోకెన్ ఇంగ్లీష్ - 6000 రూపాయలు\nపైథాన్ - 8000 రూపాయలు",
}

COACHING_QUESTIONS: list[tuple[str, str]] = [
    ("How much is the fee for the spoken English course?", "Rs 6000"),
    ("spoken english fee entha", "Rs 6000"),
    ("python course fees", "Python"),
    ("How long does the Tally accounting course take to complete?", "6 weeks"),
    ("group 2 coaching fee", "Group 2"),
    ("basic computers course cost", "Basic computers"),
    ("study material ki extra charge unda", "Study material"),
    ("evening batch timings", "6 pm to 8 pm"),
    ("Is there a batch on weekends for people who work during the week?", "Weekend batch"),
    ("morning batch enni gantalaku", "7 am to 9 am"),
    ("Can I get my money back if I decide to leave after joining the course?", "refunded"),
    ("refund policy", "refunded"),
    ("free demo class eppudu", "demo class"),
    ("స్పోకెన్ ఇంగ్లీష్", "స్పోకెన్"),
    ("పైథాన్ ఫీజు", "పైథాన్"),
]

#: recall@5 measured on this corpus with the keyword arm alone. Raise, never lower.
FLOORS: dict[str, float] = {"restaurant": 1.0, "guest_house": 1.0, "coaching": 1.0}

CORPORA: dict[str, tuple[dict[str, str], list[tuple[str, str]]]] = {
    "restaurant": (RESTAURANT, RESTAURANT_QUESTIONS),
    "guest_house": (GUEST_HOUSE, GUEST_HOUSE_QUESTIONS),
    "coaching": (COACHING, COACHING_QUESTIONS),
}


# --- helpers -----------------------------------------------------------------------------


async def _no_question_vector(_self: Any, _request: RetrievalRequest) -> None:
    return None


@pytest.fixture
def keyword_arm_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pgvector store, with the dense arm switched off: no provider is ever called."""
    monkeypatch.setattr(PgVectorRetriever, "_question_vector", _no_question_vector)
    monkeypatch.setattr(get_settings(), "retrieval_provider", "pgvector")
    monkeypatch.setattr(get_settings(), "retrieval_shadow_arm", SHADOW_OFF)


async def _publish(tenant_id: uuid.UUID, name: str, body: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(submitted["id"]))


async def _tenant_knowing(sources: dict[str, str]) -> uuid.UUID:
    tenant_id, _agent_id = await _tenant_with_published_agent()
    tenant_id = uuid.UUID(str(tenant_id))
    for name, body in sources.items():
        await _publish(tenant_id, name, body)
    return tenant_id


async def _top(tenant_id: uuid.UUID, question: str, k: int = 5) -> RetrievalResult:
    async with tenant_session(tenant_id) as session:
        _decision, result = await retrieval_service.look_up(
            session, tenant_id=tenant_id, question=question, k=k
        )
    return result


# --- the golden set ----------------------------------------------------------------------


def test_the_menu_is_longer_than_the_compiled_block_holds() -> None:
    """The price list must exceed T0's budget, or this corpus does not test the fusion."""
    from apps.api.agents.t0 import KNOWLEDGE_CHAR_BUDGET

    assert len(_MENU) > KNOWLEDGE_CHAR_BUDGET
    assert sum(len(questions) for _, questions in CORPORA.values()) >= 40


@pytest.mark.usefixtures("keyword_arm_only")
@pytest.mark.parametrize("business", sorted(CORPORA))
async def test_recall_at_5_over_the_golden_set(business: str) -> None:
    sources, questions = CORPORA[business]
    tenant_id = await _tenant_knowing(sources)
    missed: list[str] = []
    for question, expected in questions:
        result = await _top(tenant_id, question)
        if not any(expected in passage.text for passage in result.passages[:5]):
            missed.append(question)
    recall = 1 - len(missed) / len(questions)
    assert recall >= FLOORS[business], f"{business} recall@5 {recall:.2f}; missed: {missed}"


# --- the defects it guards -----------------------------------------------------------------


@pytest.mark.usefixtures("keyword_arm_only")
async def test_a_long_natural_question_still_finds_the_chunk_by_keyword() -> None:
    """AND over every lexeme found nothing for a question carrying one word the chunk lacks."""
    tenant_id = await _tenant_knowing({"Parking": "Valet parking is free for every guest."})
    async with tenant_session(tenant_id) as session:
        result = await PgVectorRetriever(session).retrieve(
            RetrievalRequest(
                tenant_id=tenant_id,
                question="Could you tell me what the valet parking charges are on weekends",
                tier="t3",
            )
        )
    assert [p.text for p in result.passages] == ["Valet parking is free for every guest."]


@pytest.mark.usefixtures("keyword_arm_only")
async def test_a_price_question_reaches_a_price_list_the_compiled_block_skipped() -> None:
    """A price question routes to T0, and T0 skips a source longer than its budget whole."""
    tenant_id = await _tenant_knowing({"Menu": _MENU})
    result = await _top(tenant_id, "what is the price of the qubani ka meetha")
    assert result.requested_tier == "t0"
    assert result.served_tier == "t3", "the store filled what T0 could not, and says so"
    assert any("Qubani ka meetha - Rs 120" in p.text for p in result.passages)


@pytest.mark.usefixtures("keyword_arm_only")
async def test_a_question_the_compiled_block_answers_well_stays_t0() -> None:
    tenant_id = await _tenant_knowing(
        {"Timings": "We are open from 11 am to 11 pm every day.", "Parking": "Free parking."}
    )
    result = await _top(tenant_id, "when are you open")
    assert (result.requested_tier, result.served_tier) == ("t0", "t0")
    assert all(p.provenance.tier == "t0" for p in result.passages)


@pytest.mark.usefixtures("keyword_arm_only")
async def test_the_source_name_is_a_keyword_and_existing_keys_are_rebuilt_with_it() -> None:
    tenant_id = await _tenant_knowing({"Room tariff": "Deluxe: 2500 per night."})
    question = RetrievalRequest(tenant_id=tenant_id, question="tariff", tier="t3")
    async with tenant_session(tenant_id) as session:
        found = await PgVectorRetriever(session).retrieve(question)
        assert [p.text for p in found.passages] == ["Deluxe: 2500 per night."]
        # A key written before the name was part of it: content and gloss only.
        await session.execute(
            text(
                "UPDATE kb_chunks c SET tsv = to_tsvector('english', d.content) "
                "FROM kb_documents d WHERE d.id = c.document_id AND c.tenant_id = :t "
                "AND d.content = :body"
            ),
            {"t": tenant_id, "body": "Deluxe: 2500 per night."},
        )
        assert (await PgVectorRetriever(session).retrieve(question)).passages == ()
        rebuilt = await kb_service.refresh_projection_keys(session, tenant_id=tenant_id, limit=50)
        again = await kb_service.refresh_projection_keys(session, tenant_id=tenant_id, limit=50)
        assert (rebuilt, again) == (1, 0)
        assert (await PgVectorRetriever(session).retrieve(question)).passages != ()


# --- what Pip is shown ---------------------------------------------------------------------


def _passage(body: str, source_id: uuid.UUID) -> Passage:
    return Passage(text=body, provenance=Provenance(label="Menu", tier="t3", source_id=source_id))


async def test_pip_sees_whole_chunks_and_deliverable_ones_behind_undelivered_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    undelivered_id, delivered_id = uuid.uuid4(), uuid.uuid4()
    whole = "x" * (kb_service.MAX_CHUNK_CHARS - 10) + " Rs 950 END"
    pool = [_passage(f"link passage {i}", undelivered_id) for i in range(6)]
    pool.append(_passage(whole, delivered_id))
    asked: list[int] = []

    async def _look_up(_session: Any, **kwargs: Any) -> tuple[Any, RetrievalResult]:
        asked.append(kwargs["k"])
        decision = classify(kwargs["question"])
        return decision, RetrievalResult(
            passages=tuple(pool[: kwargs["k"]]),
            requested_tier="t3",
            served_tier="t3",
            provider="knowledge",
        )

    async def _undelivered(_session: Any) -> set[uuid.UUID]:
        return {undelivered_id}

    monkeypatch.setattr(copilot_tools, "look_up", _look_up)
    monkeypatch.setattr(copilot_tools, "undelivered_source_ids", _undelivered)
    answer = await copilot_tools._search_knowledge(
        None,  # type: ignore[arg-type]
        copilot_tools.ToolContext(tenant_id=uuid.uuid4(), role="owner"),
        {"question": "mutton biryani family pack"},
    )
    assert "Rs 950 END" in answer, "the passage was cut before its price"
    assert "link passage" not in answer
    assert asked and asked[0] > copilot_tools.MAX_PASSAGES + 1
