"""The company training describes the business, in fixed sections whose every line the code
finds in the material (founder, 24 Nov 2026).

Rytu Khata's training described the company as "helping farmers install the app" and carried
a campaign's opening and steps, because the writer blended a guide written for one campaign
into free text. Now the writer fills fixed sections with a quote per item; the code keeps an
item only when its quote is in the material, builds the text under fixed headings, and names
the business parts no source gave so the owner is asked for them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.workers.company_training_draft import TRAINING_ASK
from apps.workers.training_sections import (
    MISSING_PARTS,
    SCHEMA,
    SECTIONS,
    corpus_of,
    written,
)

MATERIAL = (
    "Rytu Khata is an app where farmers keep their farm accounts. "
    "It records crop expenses and sales and shows the totals on the Dashboard. "
    "Address everyone as andi. Never say anna."
)


def _answer(**sections: list[dict[str, str]]) -> dict[str, Any]:
    raw: dict[str, Any] = {key: [] for key, _heading in SECTIONS}
    raw.update(sections)
    return raw


def test_a_line_whose_quote_is_in_the_material_is_kept_under_its_heading() -> None:
    built = written(
        _answer(
            business=[
                {
                    "text": "Rytu Khata is an app where farmers keep their farm accounts",
                    "quote": "rytu khata is an app where farmers keep their farm accounts",
                }
            ],
            speaking=[{"text": "Address everyone as andi", "quote": "Address everyone as andi."}],
        ),
        MATERIAL,
    )
    assert built.text == (
        "About the business:\nRytu Khata is an app where farmers keep their farm accounts.\n\n"
        "How agents speak:\nAddress everyone as andi."
    )
    assert built.unsourced == 0


def test_a_line_the_material_does_not_say_is_dropped() -> None:
    built = written(
        _answer(
            business=[
                {
                    "text": "Rytu Khata helps farmers install the app",
                    "quote": "We help farmers install the app",
                }
            ]
        ),
        MATERIAL,
    )
    assert built.text == "" and built.unsourced == 1
    assert built.missing == MISSING_PARTS


def test_business_parts_with_nothing_found_are_named_for_the_owner() -> None:
    built = written(
        _answer(
            offer=[
                {
                    "text": "It records crop expenses and sales",
                    "quote": "It records crop expenses and sales",
                }
            ]
        ),
        MATERIAL,
    )
    assert built.missing == ("business", "customers")


def test_questions_read_as_asked_and_answered() -> None:
    built = written(
        _answer(
            questions=[
                {
                    "question": "Where do I see my totals",
                    "answer": "On the Dashboard",
                    "quote": "shows the totals on the Dashboard",
                }
            ]
        ),
        MATERIAL,
    )
    assert "Questions callers ask:\nAsked: Where do I see my totals. Answer: On the Dashboard." in (
        built.text
    )


def test_the_owners_edits_count_as_material() -> None:
    corpus = corpus_of(MATERIAL, ["We are open on Sundays."])
    built = written(
        _answer(policies=[{"text": "Open on Sundays", "quote": "We are open on Sundays"}]),
        corpus,
    )
    assert "Policies:\nOpen on Sundays." in built.text


def test_there_is_no_section_for_one_piece_of_work() -> None:
    keys = {key for key, _heading in SECTIONS}
    assert set(SCHEMA["required"]) == keys  # type: ignore[call-overload]
    for work in ("opening", "steps", "flow", "goal", "purpose", "reason"):
        assert not any(work in key for key in keys), work


def test_the_ask_keeps_one_piece_of_work_out_and_names_no_business() -> None:
    assert "how it opens or its steps" in TRAINING_ASK
    assert "Leave a list empty rather than fill it" in TRAINING_ASK
    for word in ("Rytu", "farmer", "install"):
        assert word.lower() not in TRAINING_ASK.lower(), word


def test_the_screen_is_told_what_is_missing() -> None:
    from apps.api.agents.company_training import _last_write
    from apps.api.agents.company_training_routes import _last_write as out

    stored = {"at": datetime.now(UTC).isoformat(), "missing": ["business", "offer"]}
    read = _last_write(stored)
    assert read is not None and read.missing == ("business", "offer")
    shown = out(read)
    assert shown is not None and shown.missing == ["business", "offer"]
    older = _last_write({"at": datetime.now(UTC).isoformat()})
    assert older is not None and older.missing == ()
