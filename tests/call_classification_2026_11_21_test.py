"""What a finished walkthrough call is filed as (21 Nov 2026 call review): a detail is the
caller's only when the caller said it, a next step only when the call raised one, and the
owner's own test call books no call back and raises no "needs a person" nudge."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.api.tenancy.setup_nudges import setup_nudges
from apps.workers import extraction as extraction_module
from apps.workers.caller_evidence import borrowed_keys, brief_texts, without_borrowed
from apps.workers.extraction import build_response_schema, extract_call
from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionSchemaSpec,
    MomentsBrief,
    build_extraction_prompt,
    settled_next_step,
)
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _scalar
from tests.pipeline_audit_test import _stub_storage as _stub_storage

SPEC = ExtractionSchemaSpec(
    fields=[
        ExtractionField(key="purpose", label="Purpose of usage", type="text"),
        ExtractionField(key="current_user", label="Is currently using the app?", type="bool"),
        ExtractionField(key="village", label="Village", type="text"),
    ]
)

BRIEF = MomentsBrief(
    business_line="An app that helps people manage farm details and expenses.",
    agent_goal="Help the caller add the app, log in, add a farm and record an expense.",
    script_steps=["Add the app to the home screen", "Add a farm", "Add an expense"],
)


@dataclass(frozen=True)
class _Turn:
    idx: int
    speaker: str
    text: str
    start_ms: int | None = 0
    start_approximate: bool = False


#: The shape of the reviewed call, in romanised lines: every caller answer is about the step
#: in hand, and none of them says why they use the app.
WALKTHROUGH = [
    _Turn(0, "agent", "Mee phone Android aa iPhone aa?"),
    _Turn(1, "caller", "Android andi"),
    _Turn(2, "agent", "Language select cheyandi. This app helps you manage farm details."),
    _Turn(3, "caller", "Select cheshanu Telugu bhasha"),
    _Turn(4, "agent", "Ippudu farm add cheyandi, tarvata expense add cheyandi."),
    _Turn(5, "caller", "Farm add chesanu"),
    _Turn(6, "caller", "Ayindandi"),
]


# --- 2. a value copied from the business's side is not the caller's ----------------------


def test_a_purpose_copied_from_the_business_description_is_dropped() -> None:
    data = {"purpose": "To manage farm details and expenses", "current_user": True}
    kept, dropped = without_borrowed(
        data, SPEC, turns=WALKTHROUGH, business_texts=brief_texts(BRIEF)
    )
    assert dropped == {"purpose"}
    assert kept == {"current_user": True}, "only text values are judged"


def test_a_value_the_caller_said_is_kept() -> None:
    turns = [*WALKTHROUGH, _Turn(7, "caller", "Naa farm expenses track cheyadaniki use chestanu")]
    data = {"purpose": "To track farm expenses"}
    assert borrowed_keys(data, SPEC, turns=turns, business_texts=brief_texts(BRIEF)) == set()


def test_a_short_or_unrelated_value_is_not_judged() -> None:
    texts = brief_texts(BRIEF)
    # Two content words: a translated answer is usually this short and shares nothing.
    assert (
        borrowed_keys({"village": "Near Guntur"}, SPEC, turns=WALKTHROUGH, business_texts=texts)
        == set()
    )
    unrelated = {"purpose": "Grows paddy beside the canal road"}
    assert borrowed_keys(unrelated, SPEC, turns=WALKTHROUGH, business_texts=texts) == set()


def test_caller_lines_with_no_latin_words_are_not_compared() -> None:
    letters = "".join(chr(0x0C15 + n) for n in range(5))
    turns = [
        _Turn(0, "agent", "This app helps you manage farm details."),
        _Turn(1, "caller", letters),
    ]
    data = {"purpose": "To manage farm details and expenses"}
    assert borrowed_keys(data, SPEC, turns=turns, business_texts=brief_texts(BRIEF)) == set()


# --- 1. a short reply answers only its own question ---------------------------------------


def test_the_prompt_ties_a_short_reply_to_the_question_before_it() -> None:
    prompt = build_extraction_prompt(SPEC, "caller: Android andi", moments=BRIEF)
    assert "answers only the question\n  asked just before it" in prompt
    assert "says nothing about what they had, did or used before the call" in prompt
    assert "never a source for\na field" in prompt


# --- 4. a next step only when the call raised one ------------------------------------------


def test_the_prompt_and_schema_ask_why_before_the_step() -> None:
    prompt = build_extraction_prompt(SPEC, "caller: Ayindandi")
    assert prompt.index('"next_step_why"') < prompt.index('"next_step":')
    keys = list(build_response_schema(SPEC)["properties"])
    assert keys.index("next_step_why") < keys.index("next_step")
    assert build_response_schema(SPEC)["properties"]["next_step_why"] == {
        "type": "string",
        "enum": ["caller_asked", "agreed", "left_undone", "none"],
    }


def test_a_step_nothing_called_for_is_cleared() -> None:
    step = "Call them back to confirm they can navigate the app independently."
    assert settled_next_step(
        step, "business", "None", callback_requested=False, out_of_scope=False
    ) == ("", "nobody")
    for why in ("left_undone", "agreed", "caller_asked", None, "nonsense"):
        assert settled_next_step(
            step, "business", why, callback_requested=False, out_of_scope=False
        ) == (step, "business")
    # A requested call back and an unanswered question are facts, whatever `why` says.
    assert settled_next_step(step, "business", "none", callback_requested=True, out_of_scope=False)[
        0
    ]
    assert settled_next_step(step, "business", "none", callback_requested=False, out_of_scope=True)[
        0
    ]
    assert settled_next_step(step, None, "none", callback_requested=False, out_of_scope=False) == (
        "",
        None,
    )


class _Runner:
    """A model runner that answers with `answer`."""

    model_name = "fake-model"
    reads_outcomes = True

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer

    async def run(
        self,
        spec: ExtractionSchemaSpec,
        transcript: str,
        *,
        outcomes: Sequence[BusinessOutcome] = (),
    ) -> dict[str, Any]:
        return dict(self.answer)


_FINISHED = {
    "summary": "The caller added the app, logged in, added a farm and an expense.",
    "outcome_tag": "answered",
    "next_step_why": "none",
    "next_step": "Call them back to confirm they can navigate the app independently.",
    "next_step_by": "business",
    "callback_requested": False,
}


async def test_extract_call_clears_an_invented_step() -> None:
    out = await extract_call(SPEC, "caller: Ayindandi", extractor=_Runner(_FINISHED))
    assert (out.next_step, out.next_step_by) == ("", "nobody")


async def test_a_finished_walkthrough_is_not_needs_you(monkeypatch: pytest.MonkeyPatch) -> None:
    # `need` is a core text field; this value is the fake call's agent lines restated.
    answer = {**_FINISHED, "need": "Doctor available evening at Sunrise Clinic"}
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: _Runner(answer))
    tenant_id, execution_id, call_id = await _completed_call("walkthrough")
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id) == (
        "answered"
    )
    assert await _scalar(tenant_id, "SELECT next_step FROM calls WHERE id = :c", c=call_id) in (
        "",
        None,
    )
    data = await _scalar(
        tenant_id, "SELECT data FROM call_extractions WHERE call_id = :c", c=call_id
    )
    assert "need" not in data, "the agent's own words are not the caller's need"


# --- 5. the owner's test call -------------------------------------------------------------


async def test_a_test_call_books_no_call_back(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = {
        "summary": "s",
        "outcome_tag": "needs_you",
        "next_step_why": "caller_asked",
        "next_step": "Call them back.",
        "next_step_by": "business",
        "callback_requested": True,
    }
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: _Runner(answer))
    tenant_id, execution_id, call_id = await _completed_call("papertest")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET paid_test_call = true WHERE id = :c"), {"c": call_id}
        )
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert (
        await _scalar(
            tenant_id,
            "SELECT count(*) FROM scheduled_callbacks WHERE source_call_id = :c",
            c=call_id,
        )
        == 0
    )


async def test_a_test_call_raises_no_needed_a_person_nudge() -> None:
    tenant_id, _execution_id, call_id = await _completed_call("nudgetest")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET outcome_tag = 'needs_you', paid_test_call = true, "
                "ended_at = now() WHERE id = :c"
            ),
            {"c": call_id},
        )
        nudges = await setup_nudges(
            session, tenant_id=tenant_id, open_steps={"contacts"}, dismissed_at=None
        )
        assert [n.cause for n in nudges] == []
        await session.execute(
            text("UPDATE calls SET paid_test_call = false WHERE id = :c"), {"c": call_id}
        )
        nudges = await setup_nudges(
            session,
            tenant_id=tenant_id,
            open_steps={"contacts"},
            dismissed_at=None,
            now=datetime.now(UTC),
        )
        assert [n.cause for n in nudges] == ["needed_a_person"]
