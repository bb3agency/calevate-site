"""D-887: how a call reads back, from three production test calls of 25 Oct 2026.

- A call that agreed a site visit read "Answered — no follow-up is due" beside "Next step:
  confirm the site visit for tomorrow morning". A next step means something is left to do.
- A mixed English/Telugu call's English summary was romanised Telugu ("Customer Badangpet lo
  5-bedroom house kavali ani..."). Latin letters do not make a summary English.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.crm.outcomes import CallFacts, derive_outcome
from apps.api.crm.service import CALLBACK_OUTCOMES
from apps.api.db.session import tenant_session
from apps.workers import call_language, chat, pipeline
from apps.workers.call_language import LanguagePass, reads_as_romanised
from apps.workers.pipeline import _settle_summaries
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _scalar

# The recording copy is an environment concern; the stub is `pipeline_audit_test`'s.
from tests.pipeline_audit_test import _stub_storage as _stub_storage

#: The first sentence is the production summary of 25 Oct 2026 as quoted in the review; the
#: second is written in the same form.
ROMANISED = (
    "Customer Badangpet lo 5-bedroom house kavali ani, budget 45 lakhs undi ani chepparu. "
    "Repu morning site visit ki vastanu ani annaru."
)
ENGLISH = (
    "The caller wants a 5-bedroom house in Badangpet with a budget of 45 lakhs and agreed "
    "to a site visit tomorrow morning."
)
TELUGU = "కస్టమర్ బడంగ్‌పేట్ లో 5 బెడ్ రూమ్ ఇల్లు కావాలి అన్నారు."


def _facts(**overrides: Any) -> CallFacts:
    base: dict[str, Any] = {
        "status": "completed",
        "duration_s": 95,
        "caller_turns": 6,
        "callback_booked": False,
        "handoff_outcome": None,
        "hint": "answered",
        "callback_requested": False,
        "out_of_scope": False,
    }
    base.update(overrides)
    return CallFacts(**base)


# --- the agreed visit ------------------------------------------------------------------


def test_an_answered_reading_with_a_next_step_needs_a_person() -> None:
    """FAILS IF: a call whose reading names a next step for the business ("Confirm the site
    visit for tomorrow morning") reads `answered`, which the follow-up panel turns into "no
    follow-up is due"."""
    assert derive_outcome(_facts(next_step_due=True)) == "needs_you"
    assert derive_outcome(_facts(next_step_due=True)) in CALLBACK_OUTCOMES
    # Nothing left to do is still answered, and the facts still outrank the step.
    assert derive_outcome(_facts()) == "answered"
    assert derive_outcome(_facts(next_step_due=True, callback_booked=True)) == "call_back_booked"
    assert derive_outcome(_facts(next_step_due=True, hint="hung_up_early")) == "hung_up_early"
    assert derive_outcome(_facts(next_step_due=True, hint=None)) is None


async def test_the_pipeline_reads_the_stored_next_step_into_the_outcome() -> None:
    """The 25 Oct call end to end at STEP 3e: the reading said `answered` and wrote a next
    step; the call's outcome is `needs_you`."""
    tenant_id, execution_id, call_id = await _completed_call("visit_agreed")
    await _run_pipeline(tenant_id, call_id, execution_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE call_extractions SET outcome_hint = 'answered', out_of_scope = false "
                "WHERE call_id = :c"
            ),
            {"c": call_id},
        )
        await session.execute(
            text(
                "UPDATE calls SET callback_requested = false, "
                "next_step = 'Confirm the site visit for tomorrow morning.' WHERE id = :c"
            ),
            {"c": call_id},
        )
    snapshot = SimpleNamespace(status="completed", duration_s=95, transcript=[])
    outcome = await pipeline._record_outcome(tenant_id, call_id, snapshot)  # type: ignore[arg-type]
    assert outcome == "needs_you"
    assert (
        await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id)
        == "needs_you"
    )

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET next_step = NULL WHERE id = :c"), {"c": call_id}
        )
    assert await pipeline._record_outcome(tenant_id, call_id, snapshot) == "answered"  # type: ignore[arg-type]


# --- English means English ---------------------------------------------------------------


def test_romanised_telugu_and_hindi_are_told_from_english() -> None:
    assert reads_as_romanised(ROMANISED)
    assert reads_as_romanised(
        "Customer ko 2BHK chahiye aur budget 50 lakh hai, visit bhi karna hai."
    )
    assert not reads_as_romanised(ENGLISH)
    # One Telugu word quoted inside an English sentence is still English.
    assert not reads_as_romanised("The caller said 'kavali' twice and wants a 3BHK in Kondapur.")
    assert not reads_as_romanised(TELUGU), "Telugu letters are the other test"
    assert not reads_as_romanised("")


def test_a_romanised_summary_is_never_the_english_one() -> None:
    """FAILS IF: a Latin-letter summary in the call's language fills the English slot."""
    english, local, source, romanised = _settle_summaries(
        engine_summary=ROMANISED, model_summary="", stored_local="", language="te-IN"
    )
    assert (english, local, source, romanised) == ("", "", None, ROMANISED)

    # The extraction's English takes the slot the engine's romanised one could not.
    english, _local, source, romanised = _settle_summaries(
        engine_summary=ROMANISED, model_summary=ENGLISH, stored_local="", language="te-IN"
    )
    assert (english, source, romanised) == (ENGLISH, "extraction", "")

    # Same test for the extraction's own summary.
    english, _local, source, romanised = _settle_summaries(
        engine_summary="", model_summary=ROMANISED, stored_local="", language="te-IN"
    )
    assert (english, source, romanised) == ("", None, ROMANISED)

    # An English call has nothing to translate into: its words are its summary.
    english, local, source, romanised = _settle_summaries(
        engine_summary=ROMANISED, model_summary="", stored_local="", language="en-IN"
    )
    assert (english, local, source, romanised) == (ROMANISED, "", "engine", "")


async def test_the_pipeline_writes_both_summaries_from_a_romanised_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mixed call end to end at STEP 3d: the romanised summary goes to the language pass
    as the source of both, and what is stored is English and Telugu letters."""
    original = pipeline.post_call_truth

    async def _truth(*args: Any, **kwargs: Any) -> Any:
        snapshot = await original(*args, **kwargs)
        return snapshot.model_copy(update={"engine_summary": ROMANISED})

    seen: dict[str, Any] = {}

    async def _pass(**kwargs: Any) -> LanguagePass:
        seen.update(kwargs)
        return LanguagePass(
            turns_en={idx: f"english {idx}" for idx, _ in kwargs["turns"]},
            summary_en=ENGLISH,
            summary_local=TELUGU,
        )

    monkeypatch.setattr(pipeline, "post_call_truth", _truth)
    monkeypatch.setattr(call_language, "run_language_pass", _pass)
    monkeypatch.setattr(pipeline, "get_settings", lambda: SimpleNamespace(sarvam_api_key="k"))
    tenant_id, execution_id, call_id = await _completed_call("romanised")
    await _run_pipeline(tenant_id, call_id, execution_id)

    assert seen["summary_romanised"] == ROMANISED
    assert seen["summary_en"] == "" and seen["summary_local"] == ""
    summary = await _scalar(tenant_id, "SELECT summary FROM calls WHERE id = :c", c=call_id)
    local = await _scalar(tenant_id, "SELECT summary_local FROM calls WHERE id = :c", c=call_id)
    assert (summary, local) == (ENGLISH, TELUGU)


async def test_the_language_pass_asks_for_both_in_the_right_forms_and_drops_the_wrong_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the pass asks for the call-language summary without naming its script, or
    keeps an answer in the wrong form: an "English" one in romanised Telugu, a Telugu one in
    Latin letters."""
    prompts: list[str] = []

    async def _complete(leg: chat.ChatLeg, messages: Any, **kw: Any) -> chat.ChatOutcome:
        prompts.append(messages[0]["content"])
        body = {"turns": [], "summary_en": ROMANISED, "summary_local": ROMANISED}
        return chat.ChatOutcome(content=json.dumps(body), finish_reason="stop", usage=None)

    monkeypatch.setattr(chat, "complete", _complete)
    done = await call_language.run_language_pass(
        api_key="k",
        language="te-IN",
        turns=[],
        summary_en="",
        summary_local="",
        summary_romanised=ROMANISED,
    )
    prompt = prompts[0]
    assert '"summary_en"' in prompt and '"summary_local"' in prompt
    assert "Telugu script (తెలుగు), never in Latin letters" in prompt
    assert ROMANISED in prompt
    assert (done.summary_en, done.summary_local) == ("", "")

    prompts.clear()

    async def _right(leg: chat.ChatLeg, messages: Any, **kw: Any) -> chat.ChatOutcome:
        prompts.append(messages[0]["content"])
        body = {"turns": [], "summary_local": TELUGU}
        return chat.ChatOutcome(content=json.dumps(body), finish_reason="stop", usage=None)

    monkeypatch.setattr(chat, "complete", _right)
    done = await call_language.run_language_pass(
        api_key="k", language="te-IN", turns=[], summary_en=ENGLISH, summary_local=""
    )
    assert done.summary_local == TELUGU
    assert "never in Latin letters" in prompts[0]
    assert '"summary_en"' not in prompts[0]
