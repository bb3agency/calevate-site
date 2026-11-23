"""Pip's campaign and line scripts are grounded in what the owner gave (21 Nov 2026).

The Rytu Khata campaign's script told a farmer, as a fact, that their name was in the
business's records, and padded the call with stock lines
(docs/evidence/script-generation-2026-11-21/GROUNDING.md).

1. The brief carries the campaign's own settings and the person and specificity rules.
2. The review's sourcing verdict is decided by the code: a claim is sourced only when its
   quote is really in the sources.
3. A claim about the person told rather than asked is a finding even when sourced.
4. The review's findings on steps join the one repair loop and clear when the line is
   rewritten; findings on parts that loop never rewrites stay warnings.

The model is never called.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.core.settings import get_settings
from apps.workers import campaign_script
from apps.workers import campaign_script_ask as ask
from apps.workers.campaign_script_ask import Review
from apps.workers.script_proposal import Noted, text_at
from calevate_shared.call_script import CallScript, ConversationStage, FaqEntry
from tests.campaign_script_writer_2026_11_15_test import ONE_QUESTION, _answer, _campaign, _script
from tests.campaign_script_writer_2026_11_16_test import _review, _run

SOURCES = ask.review_sources(
    "Help farmers who registered install the app.",
    "DOCUMENT Offer: The first month is free for every farmer.",
    ("Open 9 to 5",),
    business_name="Rytu Khata",
)


def _claim(
    part: str, claim: str, evidence: str, *, about: bool = False, asked: bool = False
) -> dict[str, Any]:
    return {
        "part": part,
        "claim": claim,
        "evidence": evidence,
        "about_person": about,
        "asked": asked,
    }


def _parsed(claims: list[dict[str, Any]], problems: list[dict[str, Any]] | None = None) -> Review:
    raw = {
        "notes": [{"part": "stages.s1", "why": "From the offer."}],
        "claims": claims,
        "problems": problems or [],
    }
    review = ask.parsed_review(raw, ["stages.s1", "faqs"], sources=SOURCES)
    assert review is not None
    return review


def test_the_asks_carry_the_person_and_specificity_rules() -> None:
    """FAILS IF: a writer is no longer told to ask, not tell, what it says about the person,
    or to write only what fits this campaign."""
    for written in (ask.CAMPAIGN_ASK, ask.LINE_ASK):
        assert ask.PERSON_RULE in written and ask.SPECIFIC_RULE in written
    assert ask.PERSON_RULE in ask.PART_ASK and ask.PERSON_RULE in ask.FLOW_ASK


def test_the_situation_names_the_campaign_and_how_the_business_has_the_numbers() -> None:
    block = ask.situation_block(
        agent_name="Varsha",
        holder_name="App install",
        purpose="Help registered farmers install the app",
        goal="They open the app once",
        consent_source="offline_form_optin",
    )
    assert block.startswith("THE CAMPAIGN:\n")
    for said in ("App install", "Help registered farmers", "open the app once", "Varsha"):
        assert said in block
    assert "paper form" in block and "never tells the person what they did" in block
    # A refused or unknown source says nothing about how the numbers came.
    assert "numbers" not in ask.situation_block(consent_source="purchased_list")
    assert ask.situation_block() == ""
    assert ask.situation_block(holder_name="Front desk", inbound=True).startswith("THE LINE:")
    change = ask.campaign_change("Main.", "", "", edit=False, situation=block)
    assert change.index("MAIN TASK:") < change.index("THE CAMPAIGN:")


def test_a_quote_counts_only_when_it_is_in_the_sources() -> None:
    assert ask.quoted_in("the FIRST month is free", SOURCES)
    assert ask.quoted_in("first   month, is free.", SOURCES)
    assert not ask.quoted_in("the first month costs nothing", SOURCES)
    assert not ask.quoted_in("", SOURCES)
    assert not ask.quoted_in("  ...  ", SOURCES)
    # Part of a word is not a quote of it.
    assert not ask.quoted_in("onth is fre", SOURCES)


def test_the_code_decides_whether_a_claim_is_sourced() -> None:
    """FAILS IF: the review's own word that a claim is sourced is trusted without its quote
    being found (judge leniency), or a quoted claim is flagged."""
    review = _parsed(
        [
            _claim("stages.s1", "first month free", "The first month is free for every farmer"),
            _claim("faqs", "a free tractor", "every farmer gets a free tractor"),
            _claim("faqs", "a discount", ""),
        ]
    )
    assert "stages.s1" not in review.unsourced
    assert review.unsourced == {"faqs": "a free tractor and a discount"}
    [problem] = review.problems("faqs")
    assert problem == ask.UNSOURCED_PROBLEM.format(claim="a free tractor and a discount")


def test_a_claim_about_the_person_is_asked_even_when_sourced() -> None:
    """FAILS IF: "your name is in our records" passes because the brief said they registered:
    the person may not remember, so it must be asked."""
    review = _parsed(
        [
            _claim("stages.s1", "they registered", "farmers who registered", about=True),
            _claim("faqs", "they use the app", "farmers who registered", about=True, asked=True),
        ]
    )
    assert review.asserted == {"stages.s1": "they registered"}
    assert "stages.s1" not in review.unsourced
    assert review.problems("stages.s1") == [ask.ASSERTED_PROBLEM.format(claim="they registered")]
    assert review.problems("faqs") == []


def test_the_rubric_problems_are_kept_to_their_kinds() -> None:
    review = _parsed(
        [],
        [
            {"part": "stages.s1", "kind": "generic", "detail": "a thank-you that fits anyone."},
            {"part": "faqs", "kind": "praise", "detail": "not a kind"},
            {"part": "stages.s9", "kind": "repeats", "detail": "not a part given"},
        ],
    )
    assert review.weak == {
        "stages.s1": ask.WEAK_PROBLEMS["generic"].format(detail="a thank-you that fits anyone")
    }
    assert review.flagged() == ["stages.s1"]


def _two_steps() -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line="Hello, this is Varsha from Rytu Khata. Is now a good time?",
        stages=[
            ConversationStage(
                id="s1", name="Install", instruction="Help them install.", sounds_like="Ready?"
            ),
            ConversationStage(id="s2", name="Finalise the call", instruction="Close."),
        ],
        faqs=[FaqEntry(question="Price?", answer="Free.")],
        ending="Thank them.",
    )


def test_findings_on_steps_go_to_the_repair_and_the_rest_are_warnings() -> None:
    script = _two_steps()
    review = Review(
        notes={"stages.s1": "x"},
        asserted={"stages.s1": "their name is on record", "opening_line": "they enquired"},
        unsourced={"faqs": "it is free", "ending": "a gift"},
    )
    found = campaign_script.review_findings(review, script)
    paths = sorted(n.finding.partition(": ")[0] for n in found.noted)
    # A quick fact answer is repaired too since 23 Nov 2026: an unsourced promise in one was
    # only ever a warning before.
    assert paths == ["ending", "faqs.0.answer", "stages.0.instruction", "stages.0.sounds_like"]
    assert sorted(left.part for left, _ in found.warned) == ["opening_line"]
    # The opening repair rewrote the opening afterwards: its warning is about a line gone.
    later = script.model_copy(update={"opening_line": "Hello, can you talk?"})
    assert [left.part for left in campaign_script.still_warned(found, script)] == ["opening_line"]
    assert campaign_script.still_warned(found, later) == []


def test_a_noted_finding_clears_once_any_line_of_its_part_is_rewritten() -> None:
    script = _two_steps()
    part = (("stages.0.instruction", "Help them install."), ("stages.0.sounds_like", "Ready?"))
    noted = Noted("stages.0.sounds_like: tells the person as a fact that x", part)
    assert noted.stands(script)
    rewritten = script.model_copy(
        update={"stages": [script.stages[0].model_copy(update={"sounds_like": "Shall we?"})]}
    )
    assert not noted.stands(rewritten)
    assert text_at(script, "faqs.0.answer") == "Free." and text_at(script, "stages.9.x") is None


@pytest.mark.rls
async def test_a_told_claim_about_the_person_is_repaired_in_the_one_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the review's finding never reaches a repair, a second loop is added, or a
    finding still warns after the repair rewrote its step."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 1)
    tenant_id, campaign_id = await _campaign()
    drafted = _script(ONE_QUESTION)
    fixed = drafted.model_copy(
        update={
            "stages": [
                drafted.stages[0].model_copy(update={"sounds_like": "Did you register?"}),
                *drafted.stages[1:],
            ]
        }
    )
    review = _review({"stages.s0": "Asks which phone."})
    review.value = Review(notes={"stages.s0": "x"}, asserted={"stages.s0": "they are on record"})
    proposal, calls, metered, reviewed = await _run(
        monkeypatch,
        tenant_id,
        campaign_id,
        # The draft, its refining edit (D-1031), then the repair.
        [_answer(drafted), _answer(drafted), _answer(fixed)],
        review=review,
    )
    # The brief carried the campaign; the review read it among its sources.
    assert "THE CAMPAIGN:\nCampaign name: Install the app" in calls[0]["brief"].description
    [message] = reviewed
    assert message.index("Campaign name: Install the app") < message.index("THE SCRIPT'S PARTS")
    # One repair, asked with the review's finding, and nothing left to warn about.
    assert len(calls) == 3
    assert ask.ASSERTED_PROBLEM.format(claim="they are on record") in calls[2]["change"]
    assert proposal.script is not None
    assert proposal.script.stages[0].sounds_like == "Did you register?"
    assert not [part for part in proposal.left_out if part.part == "stages.s0"]
    # The draft, the refining edit, the review and the repair: each metered.
    assert len(metered) == 4
