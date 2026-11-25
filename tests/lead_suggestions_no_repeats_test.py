"""A suggested new lead detail never repeats one the campaign already records."""

from __future__ import annotations

from apps.workers.field_suggestions import SYSTEM_PROMPT, restates
from calevate_shared.extraction import ExtractionField


def _enum(key: str, label: str, *choices: str) -> ExtractionField:
    return ExtractionField(key=key, label=label, type="enum", enum_values=list(choices))


# The Rytu Khata campaign's details, 25 Nov 2026.
HAVE = [
    _enum("installation_status", "Installation Status", "Installed", "Not installed", "Tried"),
    _enum("setup_progress", "Setup Progress", "Logged in", "Farm added", "Expense entered"),
    _enum(
        "interaction_outcome",
        "Interaction Outcome",
        "Completed",
        "Follow-up required",
        "Refused",
    ),
    _enum("campaign_goal_met", "Campaign Goal Met", "Yes", "No"),
    _enum("technical_comfort", "Technical Comfort Level", "Comfortable", "Needs help"),
    _enum("primary_usage", "Primary Usage Interest", "Expenses", "Sales", "Both"),
    _enum("preferred_language", "Preferred Language", "Telugu", "English"),
    _enum("phone_type", "Phone Type", "Android", "iPhone"),
]


def test_a_second_outcome_detail_is_the_same_detail() -> None:
    call_outcome = _enum(
        "call_outcome",
        "Call Outcome",
        "Installation successful",
        "Setup complete",
        "Follow-up required",
        "Refused support",
    )
    assert restates(call_outcome, HAVE)


def test_a_yes_no_read_off_another_details_choice_is_the_same_detail() -> None:
    assert restates(_enum("follow_up_needed", "Follow Up Needed", "Yes", "No"), HAVE)


def test_a_detail_mostly_made_of_another_ones_choices_is_the_same_detail() -> None:
    assert restates(_enum("app_state", "App State", "Installed", "Not installed", "Other"), HAVE)


def test_a_detail_nothing_records_yet_still_stands() -> None:
    reason = _enum("not_installed_reason", "Reason Not Installed", "No space", "No internet")
    assert not restates(reason, HAVE)
    crop = ExtractionField(key="main_crop", label="Main Crop", type="text")
    assert not restates(crop, HAVE)


def test_generic_words_alone_do_not_make_two_details_the_same() -> None:
    payment = _enum("payment_status", "Payment Status", "Paid", "Pending")
    assert not restates(payment, HAVE)


def test_the_model_is_told_to_add_to_a_detail_rather_than_repeat_it() -> None:
    assert "NONE of the current details records" in SYSTEM_PROMPT
    assert "add_choices to it instead" in SYSTEM_PROMPT
