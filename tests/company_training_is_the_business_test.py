"""The company training describes the business, never one campaign's work.

Founder, 24 Nov 2026: Rytu Khata's training was written as "calling registered farmers to
install the app", the purpose of one campaign, because the guide it read was written for that
campaign. What the company is and does belongs in the training; a piece of work's reason for
calling, goal and steps belong in that campaign's or line's own script.
"""

from __future__ import annotations

from apps.workers.company_training_draft import TRAINING_ASK


def test_the_training_ask_keeps_one_piece_of_work_out() -> None:
    assert "never about one piece of work" in TRAINING_ASK
    assert "why a particular set of people is being called" in TRAINING_ASK
    assert "take from it only what is true on every call" in TRAINING_ASK


def test_the_training_ask_leads_with_what_the_business_does() -> None:
    cover = TRAINING_ASK.index("Cover, in this order")
    assert TRAINING_ASK.index("who the business is, what it does and what it offers") > cover


def test_the_training_ask_names_no_business() -> None:
    for word in ("Rytu", "farmer", "app", "install"):
        assert word.lower() not in TRAINING_ASK.lower(), word


def test_the_writer_reports_what_the_material_leaves_unclear() -> None:
    from apps.workers.company_training_draft import MISSING_PARTS, _missing

    assert MISSING_PARTS == ("business", "offer", "customers")
    assert _missing({"training": "x", "missing": ["customers", "business", "weather"]}) == (
        "business",
        "customers",
    )
    assert _missing({"training": "x"}) == ()
    assert "missing, listing each of business" in TRAINING_ASK


def test_the_screen_is_told_what_is_missing() -> None:
    from datetime import UTC, datetime

    from apps.api.agents.company_training import _last_write
    from apps.api.agents.company_training_routes import _last_write as out

    stored = {"at": datetime.now(UTC).isoformat(), "missing": ["business", "offer"]}
    read = _last_write(stored)
    assert read is not None and read.missing == ("business", "offer")
    shown = out(read)
    assert shown is not None and shown.missing == ["business", "offer"]
    # A write saved before this change says nothing is missing.
    older = _last_write({"at": datetime.now(UTC).isoformat()})
    assert older is not None and older.missing == ()
