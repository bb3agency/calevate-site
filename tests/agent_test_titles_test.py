"""Short practice-test titles (D-917): every title fits a phone card in six words."""

from __future__ import annotations

import pytest
from apps.api.agents import script_routes, test_titles
from apps.api.agents.specimen_scenarios import CLASSES
from apps.api.agents.test_conversations import PROBE_TITLES, standard_scenarios
from apps.api.agents.test_titles import MAX_TITLE_WORDS, short_title, title_problem
from apps.api.db.session import tenant_session
from apps.api.teach import routes as teach_routes
from apps.api.teach import test_cases
from apps.api.teach.test_cases import TITLE_HINT, written_title
from apps.workers import agent_test_ai
from apps.workers.script_assist import UnusableAnswerError
from sqlalchemy import text
from tests.teach_loop_test import _call, _tenant

LONG = "Takes the caller's full phone number before booking an appointment for tomorrow morning"


@pytest.mark.parametrize(
    ("title", "card"),
    [
        (LONG, "Takes the caller's full phone number…"),
        ("Asks about products and prices", "Asks about products and prices"),
        ("  Gives   part of another number ", "Gives part of another number"),
        # The framing goes before the cut, so the need fits whole.
        ("The agent confirms the visit on Sunday morning", "Confirms the visit on Sunday morning"),
        ("Caller wants to know the price for two kilos", "Wants to know the price…"),
        # A cut never ends on a connector.
        ("Asks for the price of a plot in the east", "Asks for the price…"),
        ("", ""),
    ],
)
def test_the_card_title_is_six_words_at_most(title: str, card: str) -> None:
    assert short_title(title) == card
    assert len(card.split()) <= MAX_TITLE_WORDS
    assert len(card) <= test_titles.MAX_SHORT_CHARS


def test_a_run_of_long_words_is_cut_by_characters() -> None:
    title = "Supercalifragilistic expialidocious antidisestablishmentarianism words"
    card = short_title(title)
    assert len(card) <= test_titles.MAX_SHORT_CHARS
    assert card.endswith("…")
    assert short_title("x" * 80) == "x" * (test_titles.MAX_SHORT_CHARS - 1) + "…"


def test_title_problem_names_what_to_fix() -> None:
    assert title_problem("Asks to hear it again") is None
    assert title_problem(LONG) == "13 words; use 6 or fewer"
    long_words = "Supercalifragilistic expialidocious antidisestablish"
    assert "characters" in (title_problem(long_words) or "")


def test_every_title_we_wrote_fits_the_card() -> None:
    ours = [
        *(cls.title for cls in CLASSES),
        *PROBE_TITLES.values(),
        *(s.title for s in standard_scenarios("en-IN", "both")),
    ]
    assert ours
    for title in ours:
        assert title_problem(title) is None, title


def test_the_writer_is_told_six_words_and_its_schema_says_so() -> None:
    assert f"title ({MAX_TITLE_WORDS} words or fewer" in agent_test_ai.GENERATE_INSTRUCTION
    title_field = agent_test_ai._SCENARIO_PROPERTIES["title"]
    assert isinstance(title_field, dict)
    assert title_field["type"] == "string"
    # Azure's strict schema refuses `maxLength`; the bound is the server's.
    assert "maxLength" not in title_field


def _answer(title: str) -> dict[str, object]:
    return {
        "scenarios": [
            {
                "title": title,
                "category": "business",
                "probe": "none",
                "caller_turns": ["What is the price?"],
                "expect": "Says the price.",
            }
        ]
    }


def test_a_long_written_title_is_sent_back_once_naming_the_title() -> None:
    with pytest.raises(UnusableAnswerError) as sent_back:
        agent_test_ai.scenarios_from_model(
            _answer(LONG), round_key="r", language="en-IN", send_back_language=True
        )
    assert "scenarios.0.title: 13 words" in sent_back.value.problems


def test_a_repaired_answer_still_too_long_is_cut_not_dropped() -> None:
    scenarios = agent_test_ai.scenarios_from_model(_answer(LONG), round_key="r", language="en-IN")
    assert scenarios is not None
    assert [s.title for s in scenarios] == ["Takes the caller's full phone number…"]


def test_a_short_written_title_is_kept_and_not_sent_back() -> None:
    scenarios = agent_test_ai.scenarios_from_model(
        _answer("Asks the price"), round_key="r", language="en-IN", send_back_language=True
    )
    assert scenarios is not None and scenarios[0].title == "Asks the price"


def test_a_stored_long_title_is_served_whole_with_a_short_form() -> None:
    out = script_routes._result_out({"key": "old_1", "title": LONG, "verdict": "passed"})
    assert out.title == LONG
    assert out.short_title == "Takes the caller's full phone number…"


def test_titles_we_write_for_saved_tests_are_short() -> None:
    assert written_title(LONG) == "Takes the caller's full phone number…"
    assert written_title("   ") is None
    assert written_title(None) is None
    assert str(MAX_TITLE_WORDS) in TITLE_HINT


async def test_saved_tests_we_name_are_short_and_an_owners_title_is_kept_whole() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET headline = :h WHERE id = :id"), {"h": LONG, "id": call_id}
        )
        draft = await test_cases.draft_from_call(session, call_id)
        assert draft.title == "Takes the caller's full phone number…"
        by_hand = await test_cases.create_case(
            session,
            tenant_id=tenant_id,
            call_id=None,
            agent_id=agent_id,
            title="",
            caller_lines=["Do you deliver to Kukatpally on Sunday mornings before ten?"],
            expected="Says what the facts say.",
            created_by=None,
        )
        assert by_hand.title == "Do you deliver to Kukatpally…"
        typed = await test_cases.create_case(
            session,
            tenant_id=tenant_id,
            call_id=None,
            agent_id=agent_id,
            title=LONG,
            caller_lines=["Hello?"],
            expected="Greets.",
            created_by=None,
        )
    assert typed.title == LONG
    served = teach_routes._case_out(typed)
    assert served.title == LONG
    assert served.short_title == "Takes the caller's full phone number…"
