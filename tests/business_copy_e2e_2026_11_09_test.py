"""The business copy end to end, after a client's panel stayed on "Still learning what this
business does" with every run refused by our checks (founder, 9 Nov 2026).

What made it stick, each pinned here:

* the instruction never named several rules the checks enforce (the medical word list, the
  symbols, the ellipsis, the spoken push-backs, the caps), so a sensible answer was refused
  for a rule the model was never told;
* a refused medical or provider word was not named in the repair, so the one repair could
  not find it;
* one refused example line threw away the whole answer, the capability profile with it;
* the run recorded nothing an operator could read about why it failed;
* "Last written" named the trigger of the last run, not of the run that wrote the copy;
* an operator's capability decision on a copy written before the profile existed was
  recorded and then shown nowhere.

The model is faked at `chat.complete`, so the real `ask_json` ladder (first answer, one
repair) and the real parse run; the database and the ledger are real.
"""

from __future__ import annotations

import copy as copylib
import json
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from apps.api.admin.capability_overrides import OVERRIDE_REASON
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.api.tenancy import business_copy
from apps.workers import business_copy as worker
from apps.workers import chat
from calevate_shared.call_script import SOUNDS_LIKE_MAX
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.business_copy_test import (
    LEG,
    V4_PROFILE,
    _inputs,
    _superadmin,
    _trial,
    copy_dict,
    keyed,  # noqa: F401  (fixture)
    priced,  # noqa: F401  (fixture)
)

# --- the instruction states what the checks enforce ------------------------------------------


def test_the_instruction_names_every_rule_the_checks_enforce() -> None:
    """FAILS IF: an answer can be refused for a rule the model was never told: a word on the
    medical list ("OPD" or "dental" is not obvious to anyone who has not seen the list),
    a symbol the markdown check refuses, an ellipsis in a spoken line, digits in a caller's
    push-back, or a length the shape caps."""
    instruction = worker.instruction_for(_inputs())
    for word in business_copy.CLINIC_WORD_LIST:
        assert word in instruction, word
    for mark in ("* # ` _ ~ | [ ] < >",):
        assert mark in instruction
    assert "ellipsis" in instruction
    assert "caller_says" in instruction.split("never digits")[0]
    assert str(SOUNDS_LIKE_MAX) in instruction
    assert f"capability reason under {business_copy.LINE_MAX}" in instruction


def test_the_prompt_version_moved_so_every_account_is_rewritten() -> None:
    """FAILS IF: the new instruction reaches an account only at its next 15-day check, which
    for a copy stuck behind the prompt was never."""
    assert worker.PROMPT_VERSION >= 6


# --- a refused word is named, and the owner's own words are theirs ----------------------------


def test_a_refused_medical_or_provider_word_is_named_for_the_repair() -> None:
    """FAILS IF: the repair says only "medical words" or "a technology company", leaving the
    model to guess which of some forty strings to change."""
    raw = copy_dict()
    raw["example_questions"][0] = "Can I see the doctor on Sunday?"
    raw["placeholders"]["knowledge_title"] = "Ask Gemini about prices"
    _copy, problems = worker.answer_problems(raw, inputs=_inputs())
    assert (
        "example_questions.0: medical words (doctor), and this business is not a health "
        "business" in problems
    )
    assert "placeholders.knowledge_title: names a technology company (gemini)" in problems


def test_appointment_is_a_word_any_business_may_use() -> None:
    """FAILS IF: a salon, garage, CA or tutor that books appointments has its copy refused
    for a medical word, while the clinical nouns stay refused."""
    assert "appointment" not in business_copy.CLINIC_WORD_LIST
    assert (
        business_copy.health_words_problem("x", "Book an appointment for a haircut", health=False)
        is None
    )
    assert business_copy.health_words_problem("x", "Ask the doctor", health=False) is not None


def test_the_owners_own_words_may_name_a_company_the_copy_then_repeats() -> None:
    """FAILS IF: a business whose owner wrote "find us on Google Maps" is refused every time
    the model repeats it, as a medical word the owner used already is not."""
    raw = copy_dict()
    raw["placeholders"]["knowledge_title"] = "Finding us on Google Maps"
    owner = "Business name: Green Oils. Find us on Google Maps."
    _copy, problems = worker.answer_problems(raw, inputs=_inputs(owner_words=owner))
    assert not [p for p in problems if "technology company" in p]
    _copy, problems = worker.answer_problems(raw, inputs=_inputs())
    assert "placeholders.knowledge_title: names a technology company (google)" in problems


# --- keeping what passed -------------------------------------------------------------------


def _broken_in_droppable_parts() -> dict[str, Any]:
    """A realistic final answer: right everywhere but a push-back with a price in digits, an
    ellipsis in one ready-made line, a fourth example question with a medical word, and a
    message body with its blank at the end."""
    raw = copy_dict()
    raw["objections"][0]["caller_says"] = "Rendu vandala rupayalu ekkuva andi, 200 ki ivvandi"
    raw["starter_lines"]["answer_calls"][2] = "Oka nimisham andi…"
    raw["example_questions"].append("Is there a doctor at the shop?")
    raw["placeholders"]["message_body"] = "Your oil order is ready, {{1}}"
    return raw


def test_a_final_answer_keeps_its_profile_when_only_examples_fail() -> None:
    """FAILS IF: one refused example throws away the capability judgement with it."""
    kept = worker.salvage(
        _broken_in_droppable_parts(),
        worker.answer_problems(_broken_in_droppable_parts(), inputs=_inputs())[1],
        inputs=_inputs(),
    )
    assert kept is not None
    copy, why = kept
    assert copy.capabilities is not None and copy.capabilities.judged
    assert copy.caller_noun == "customer"
    assert copy.objections == []
    assert copy.starter_lines.answer_calls == []
    assert len(copy.starter_lines.call_leads) > 0
    assert len(copy.example_questions) == 3
    assert copy.placeholders.message_body is None
    assert any(p.startswith("objections.0.caller_says") for p in why)
    assert any(p.startswith("starter_lines.answer_calls.2") for p in why)


def test_a_screen_guess_the_ready_made_words_and_a_step_can_each_be_left_out() -> None:
    """FAILS IF: a refused on-screen judgement, ready-made words or one of several steps
    throws away a copy whose profile is sound; each reads as "not written yet" downstream."""
    raw = copy_dict()
    raw["screen_guide"] = {"suggested": False, "reason": "They never use an app."}
    raw["starter_words"]["caution"] = "Never promise a slot with the dentist."
    raw["steps"].append({"name": "Say the price", "example_line": "100 rupayalu andi"})
    _copy, problems = worker.answer_problems(raw, inputs=_inputs())
    kept = worker.salvage(raw, problems, inputs=_inputs())
    assert kept is not None
    copy, _why = kept
    assert copy.screen_guide is None and copy.starter_words is None
    assert [s.name for s in copy.steps] == [s["name"] for s in copy_dict()["steps"]]
    assert copy.capabilities is not None and copy.capabilities.judged


def test_a_part_refused_in_two_places_is_still_left_out_whole() -> None:
    """FAILS IF: two refused fields of one whole part (two of the ready-made words, here)
    read as "already out and still refused" within one pass, so the whole copy and its
    profile were thrown away instead of that one part (audit 9 Nov 2026, round 4, X6)."""
    raw = copy_dict()
    raw["starter_words"]["caution"] = "Never promise a slot with the dentist."
    raw["starter_words"]["topics"] = "the doctor's timings and prices"
    _copy, problems = worker.answer_problems(raw, inputs=_inputs())
    assert {p.partition(": ")[0] for p in problems} == {
        "starter_words.caution",
        "starter_words.topics",
    }
    kept = worker.salvage(raw, problems, inputs=_inputs())
    assert kept is not None
    copy, _why = kept
    assert copy.starter_words is None
    assert copy.capabilities is not None and copy.capabilities.judged


@pytest.mark.parametrize("noun", ["రైతు", "our valued customers here", "farmer/user"])
def test_a_refused_caller_noun_is_left_out_and_the_profile_kept(noun: str) -> None:
    """FAILS IF: one refused caller noun throws away the whole copy (production, 9 Nov 2026:
    Rytu Khata's profile stayed unjudged on "What it calls its callers: not in the expected
    form"); every reader says "person" or "caller" without it."""
    raw = copy_dict()
    raw["caller_noun"] = noun
    _copy, problems = worker.answer_problems(raw, inputs=_inputs())
    assert any(p.startswith("caller_noun") for p in problems)
    kept = worker.salvage(raw, problems, inputs=_inputs())
    assert kept is not None
    copy, _why = kept
    assert copy.caller_noun is None
    assert copy.capabilities is not None and copy.capabilities.judged


@pytest.mark.parametrize("noun", ["Farmer.", '"customer"', " member, "])
def test_a_caller_noun_in_stray_marks_is_kept_as_the_word(noun: str) -> None:
    raw = copy_dict()
    raw["caller_noun"] = noun
    copy, problems = worker.answer_problems(raw, inputs=_inputs())
    assert not problems and copy is not None
    assert copy.caller_noun == noun.strip(' .,"').lower()


def test_a_rule_hidden_behind_a_shape_error_is_still_checked() -> None:
    """FAILS IF: a copy is stored once its shape errors are trimmed without the text rules
    those errors hid being checked (a required example with a medical word here)."""
    raw = copy_dict()
    raw["objections"][0]["caller_says"] = "a" * 400
    raw["placeholders"]["knowledge_title"] = "Doctor's timings"
    _copy, problems = worker.answer_problems(raw, inputs=_inputs())
    assert problems == ["objections.0.caller_says: string_too_long"]
    assert worker.salvage(raw, problems, inputs=_inputs()) is None


@pytest.mark.parametrize(
    ("break_it", "why"),
    [
        (
            lambda raw: raw["capabilities"]["sells"].update(reason="x" * 200),
            "the judgement itself",
        ),
        (
            lambda raw: raw["placeholders"].update(knowledge_title="Doctor's timings"),
            "a required placeholder",
        ),
        (
            lambda raw: raw["example_questions"].__setitem__(0, "Any doctor today?"),
            "a list already at its minimum",
        ),
        (
            lambda raw: raw["placeholders"].update(booking_job_title=""),
            "the booking job, which must agree with the judgement",
        ),
    ],
)
def test_what_every_screen_relies_on_is_never_left_out(break_it: Any, why: str) -> None:
    """FAILS IF: a copy is stored without its profile, its caller noun, a required example,
    too few items, or a booking job that disagrees with the judgement."""
    raw = copy_dict()
    break_it(raw)
    _copy, problems = worker.answer_problems(raw, inputs=_inputs())
    assert problems, why
    assert worker.salvage(raw, problems, inputs=_inputs()) is None, why


def test_the_first_answer_is_sent_back_and_only_the_repair_is_trimmed() -> None:
    """FAILS IF: the first answer is trimmed instead of repaired (the repair usually fixes
    everything), or the repair's leftovers still throw the whole answer away."""
    attempts = worker.Attempts()
    parse = worker._parser(_inputs(), attempts)
    with pytest.raises(worker.UnusableAnswerError):
        parse(_broken_in_droppable_parts())
    copy = parse(_broken_in_droppable_parts())
    assert copy.objections == []
    assert attempts.answers == 2
    assert attempts.record()[0].startswith(business_copy.LEFT_OUT)


# --- the run, end to end --------------------------------------------------------------------


class Answers:
    """`chat.complete` answering with each of `contents` in turn."""

    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.asked = 0

    async def __call__(self, leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        content = self.contents[min(self.asked, len(self.contents) - 1)]
        self.asked += 1
        return chat.ChatOutcome(
            content=content,
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=8_000, output_tokens=2_000),
        )


@pytest.fixture
def leg(monkeypatch: pytest.MonkeyPatch, keyed: None, priced: None) -> None:  # noqa: F811
    monkeypatch.setattr(worker, "google_assist_leg", lambda: LEG)
    monkeypatch.setattr(worker, "alert", lambda *a, **kw: None)
    _trial(monkeypatch, False)


async def _row(tenant_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT generated, stop_reason, last_problems, generated_trigger, "
                    "last_trigger FROM business_copies"
                )
            )
        ).first()


async def _admin(tenant_id: uuid.UUID) -> dict[str, Any]:
    headers = await _superadmin()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        read = await http.get(f"/v1/admin/tenants/{tenant_id}/business-copy", headers=headers)
    assert read.status_code == 200, read.text
    body: dict[str, Any] = read.json()
    return body


async def _run(tenant_id: uuid.UUID, trigger: str) -> str:
    return await worker.generate_business_copy(
        {}, {"tenant_id": str(tenant_id), "trigger": trigger}
    )


async def test_a_repair_that_still_breaks_an_example_stores_the_profile(
    leg: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: the run ends "did not pass our checks" with the profile unjudged when only
    examples were wrong, or the operator cannot see what was left out."""
    broken = json.dumps(_broken_in_droppable_parts())
    monkeypatch.setattr(chat, "complete", Answers(broken, broken))
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "operator") == "stored"
    row = await _row(tenant_id)
    assert row[1] is None
    assert row[0]["capabilities"]["takes_orders"]["applies"] is True
    assert row[0]["objections"] == []
    assert row[3] == "operator"
    assert all(p.startswith(business_copy.LEFT_OUT) for p in row[2])
    shown = await _admin(tenant_id)
    assert shown["generated_trigger"] == "operator"
    assert shown["capabilities"]["sells"]["applies"] is True
    assert any(p.startswith("Left out: Caller push-back 1") for p in shown["last_problems"])
    assert any(
        p.startswith("Left out: Ready-made answering agent, line 3") for p in shown["last_problems"]
    )


async def test_a_refused_run_records_why_and_a_clean_run_clears_it(
    leg: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: an operator reads only "did not pass our checks" with no part and no rule,
    or a later clean run leaves the old failure on screen."""
    raw = copy_dict()
    raw["capabilities"]["sells"]["reason"] = "x" * 200
    bad = json.dumps(raw)
    monkeypatch.setattr(chat, "complete", Answers(bad, bad))
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "operator") == "answer_unusable"
    row = await _row(tenant_id)
    assert row[1] == "answer_unusable"
    assert row[2] == ["capabilities.sells.reason: string_too_long"]
    shown = await _admin(tenant_id)
    assert shown["last_problems"] == ["What the business does 'sells reason': too long"]
    assert shown["last_trigger"] == "operator"
    # Nothing was written: no write trigger is claimed.
    assert shown["generated_trigger"] is None

    monkeypatch.setattr(chat, "complete", Answers(json.dumps(copy_dict())))
    assert await _run(tenant_id, "refresh") == "stored"
    row = await _row(tenant_id)
    assert row[1] is None and row[2] is None and row[3] == "refresh"
    assert (await _admin(tenant_id))["last_problems"] == []


async def test_a_repair_that_comes_back_empty_says_so(
    leg: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: an empty or cut-off second answer reads as the first answer's problems
    alone, hiding that the model returned nothing the second time."""
    raw = copy_dict()
    raw["capabilities"]["sells"]["reason"] = "x" * 200
    monkeypatch.setattr(chat, "complete", Answers(json.dumps(raw), ""))
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "operator") == "answer_unusable"
    row = await _row(tenant_id)
    assert row[2][0] == business_copy.EMPTY_REPAIR


async def test_written_by_names_the_run_that_wrote_the_copy_not_the_last_run(
    leg: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: a copy the owner's refresh wrote reads "(an operator asked)" after an
    operator's refresh failed."""
    monkeypatch.setattr(chat, "complete", Answers(json.dumps(copy_dict())))
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "refresh") == "stored"
    raw = copy_dict()
    raw["capabilities"]["sells"]["reason"] = "x" * 200
    monkeypatch.setattr(chat, "complete", Answers(json.dumps(raw)))
    assert await _run(tenant_id, "operator") == "answer_unusable"
    shown = await _admin(tenant_id)
    assert shown["generated_trigger"] == "refresh"
    assert shown["last_trigger"] == "operator"


# --- an operator's decision on a copy from before the profile -------------------------------


async def test_an_operators_decision_shows_on_a_copy_written_before_the_profile() -> None:
    """FAILS IF: on a copy written before prompt version 4 (no `capabilities` at all), the
    operator's Yes is recorded but every reader still sees "not judged", or clearing it
    leaves a verdict nobody judged."""
    tenant_id, _slug, _token = await _make_tenant()
    old = copylib.deepcopy(copy_dict())
    for key in (*V4_PROFILE, "starter_words"):
        del old[key]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_copies (id, tenant_id, generated) "
                "VALUES (:id, :t, CAST(:g AS jsonb))"
            ),
            {"id": uuid7(), "t": tenant_id, "g": json.dumps(old)},
        )
    headers = await _superadmin()
    path = f"/v1/admin/tenants/{tenant_id}/business-copy/capabilities/takes_bookings"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        decided = await http.put(path, headers=headers, json={"applies": True})
    assert decided.status_code == 200, decided.text
    assert decided.json()["capabilities"]["takes_bookings"] == {
        "reason": OVERRIDE_REASON,
        "applies": True,
    }
    async with tenant_session(tenant_id) as session:
        caps = await business_copy.capabilities_for(session, tenant_id)
    assert caps.takes_bookings.applies is True
    assert caps.sells.applies is None, "a verdict nobody judged was invented"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        cleared = await http.put(path, headers=headers, json={"applies": None})
    assert cleared.status_code == 200, cleared.text
    async with tenant_session(tenant_id) as session:
        back = await business_copy.capabilities_for(session, tenant_id)
    assert back == business_copy.Capabilities.unknown()


# --- the operator's words for a recorded problem -----------------------------------------------


@pytest.mark.parametrize(
    ("recorded", "said"),
    [
        (
            "starter_lines.answer_calls.2: numbers in words, no digits, rupee signs or slashes",
            "Ready-made answering agent, line 3: numbers in words, no digits, rupee signs or "
            "slashes",
        ),
        ("steps.0.example_line: string_too_long", "Suggested step 1 (example line): too long"),
        (
            "starter_lines.call_leads: exactly 6 lines, one per step",
            "Ready-made calling agent: exactly 6 lines, one per step",
        ),
        ("placeholders.teach_note: missing", "Example text 'teach note': missing"),
        (
            "caller_noun: string_pattern_mismatch",
            "What it calls its callers: not in the expected form",
        ),
        (business_copy.EMPTY_REPAIR, "The answer: the second try came back empty or cut off"),
        (
            f"{business_copy.LEFT_OUT}objections.0.caller_says: numbers in words",
            "Left out: Caller push-back 1 (caller says) (numbers in words)",
        ),
    ],
)
def test_a_recorded_problem_reads_in_plain_words(recorded: str, said: str) -> None:
    assert business_copy.explain_problem(recorded) == said
