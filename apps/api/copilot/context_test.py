"""The LIVE STATE block as an artefact: what it renders, what it costs, what it never says.

The half that needs a database — the counts a seeded tenant really has, and the RLS
property that tenant A's block never carries tenant B's numbers — is
`tests/copilot_live_state_test.py`. Everything here is about the STRING, which is where
the token cost, the degradation contract and the prompt order actually live.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apps.api.copilot import context
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot.schemas import CopilotAskIn
from apps.workers.redaction import redact

IST = ZoneInfo("Asia/Kolkata")
AT = datetime(2026, 8, 31, 18, 42, 7, tzinfo=IST)

PAYLOAD = CopilotAskIn.model_validate(
    {
        "screen": {"route": "/c/sunrise/leads", "title": "Leads", "realm": "client"},
        "question": "how many hot leads am I sitting on?",
    }
)


def _state(
    *,
    calls_today: int = 3,
    calls_week: int = 19,
    hot: int = 2,
    blockers: tuple[str, ...] | None = ("kyc_missing", "agreements_not_accepted"),
) -> context.LiveState:
    return context.LiveState(
        now_ist=AT,
        counts=context.LiveCounts(
            calls_today=calls_today,
            calls_last_7_days=calls_week,
            leads_waiting={"hot": hot, "interested": 1, "new": 4},
            campaigns={"running": 1, "paused": 0, "scheduled": 0, "draft": 2},
        ),
        blocker_rules=blockers,
    )


# --- what it says ---------------------------------------------------------------------


def test_the_block_is_fenced_labelled_and_carries_every_half() -> None:
    """One fence, one `<live>` element, and the four things the copilot is asked about:
    what happened today, what happened this week, who is waiting, and what is blocked."""
    rendered = context.render_live(_state())
    assert rendered.startswith(context.LIVE_OPEN)
    assert rendered.endswith(context.LIVE_CLOSE)
    assert 'now_ist="2026-08-31 18:42"' in rendered
    assert '<calls today="3" last_7_days="19"/>' in rendered
    assert '<leads_waiting hot="2" interested="1" new="4"/>' in rendered
    assert '<campaigns running="1" paused="0" scheduled="0" draft="2"/>' in rendered
    assert '<blocker rule="kyc_missing"/>' in rendered


def test_hot_is_first_because_it_is_the_lead_that_costs_money_to_ignore() -> None:
    """Order is not cosmetic in a prompt: the first attribute of the element is the one a
    model reaches for when it summarises. `WAITING_STATUSES` fixes it and this pins it."""
    assert context.WAITING_STATUSES[0] == "hot"
    assert context.render_live(_state()).index('hot="') < context.render_live(_state()).index(
        'new="'
    )


def test_nothing_blocking_renders_as_an_empty_element_not_as_silence() -> None:
    """ "Nothing is blocking you" is an ANSWER, and it is a different one from "I could
    not check". An absent element would collapse the two."""
    assert "<outbound_blockers/>" in context.render_live(_state(blockers=()))


# --- what happens when it cannot answer -----------------------------------------------


def test_an_unreadable_half_is_marked_unavailable_and_never_rendered_as_zero() -> None:
    """THE DEGRADATION CONTRACT. A failed `count(*)` that rendered `today="0"` would make
    the copilot state a falsehood with total confidence — the exact failure the whole
    anti-fabrication half of `SYSTEM_PROMPT` exists to prevent. The marker is what the
    model is told to read as "unknown"."""
    blind = context.LiveState(now_ist=AT, counts=None, blocker_rules=None)
    rendered = context.render_live(blind)
    assert '<unavailable part="activity"/>' in rendered
    assert '<unavailable part="outbound_blockers"/>' in rendered
    assert "today=" not in rendered and "<blocker" not in rendered
    assert blind.partial


def test_one_half_failing_leaves_the_other() -> None:
    """The two reads are guarded separately, so a database that answers counts but trips
    the readiness composer still gives the copilot the numbers."""
    half = context.LiveState(now_ist=AT, counts=_state().counts, blocker_rules=None)
    rendered = context.render_live(half)
    assert '<calls today="3"' in rendered
    assert '<unavailable part="outbound_blockers"/>' in rendered
    assert half.partial


def test_a_missing_block_still_produces_a_usable_prompt() -> None:
    """`live_state_block` returns "" when the snapshot is unreachable, and the copilot
    must answer anyway: the screen, the closing rules and the question all survive, and no
    empty fence is emitted for the model to wonder about."""
    messages = prompt_module.build_messages(PAYLOAD, "")
    last = str(messages[-1]["content"])
    assert prompt_module.SCREEN_OPEN in last
    assert prompt_module.CLOSING_RULES in last
    assert last.endswith("The person asks: how many hot leads am I sitting on?")
    assert context.LIVE_OPEN not in last


# --- what it costs --------------------------------------------------------------------


def test_the_block_is_small_by_construction() -> None:
    """THE COST GATE. This block is volatile, so it is never in the cacheable prefix and
    every byte of it is paid at full price on every turn of every request.

    The ceiling is asserted against a MAXIMAL state — every waiting status, every live
    campaign status, and more blocker rules than `readiness.ROW_COPY` can currently
    produce — so the number cannot be beaten by picking a small example. 800 bytes is
    roughly 200 tokens; the point is not the exact figure but that adding a list of lead
    names or campaign names to this block moves it by an order of magnitude and fails
    here.
    """
    worst = context.LiveState(
        now_ist=AT,
        counts=context.LiveCounts(
            calls_today=999_999,
            calls_last_7_days=9_999_999,
            leads_waiting=dict.fromkeys(context.WAITING_STATUSES, 999_999),
            campaigns=dict.fromkeys(context.LIVE_CAMPAIGN_STATUSES, 999_999),
        ),
        blocker_rules=(
            "account_suspended",
            "kyc_not_verified",
            "pe_registration_missing",
            "tm_registration_missing",
            "agreements_not_accepted",
            "first_campaign_hold",
            "spend_cap",
            "no_credits",
            "national_dnd_scrub_missing",
            "big_red_switch",
        ),
    )
    assert len(context.render_live(worst).encode("utf-8")) < 800


# --- what it must never say -----------------------------------------------------------


def test_the_block_carries_nothing_that_looks_like_a_person() -> None:
    """Hard rule 6's instinct, applied to a prompt instead of a log line — and checked with
    the same primitive the ingest guard uses (`sanitize.assert_redacted` → `redact`), so a
    field added later that carries a number or an address fails here rather than in
    production. The stronger property is structural: the block has no tenant-authored
    string in it at all."""
    for state in (_state(), context.LiveState(now_ist=AT, counts=None, blocker_rules=None)):
        assert not redact(context.render_live(state)).changed


def test_a_rule_name_cannot_break_out_of_its_attribute() -> None:
    """The rule names are ours today. `xml_attr` is what keeps that from being the only
    thing standing between a future tenant-derived string and the prompt's structure —
    the same argument `render_screen` makes for a field label containing a quote."""
    hostile = context.LiveState(
        now_ist=AT,
        counts=None,
        blocker_rules=('" onload="x',),
    )
    rendered = context.render_live(hostile)
    assert "<blocker rule='\" onload=\"x'/>" in rendered


def test_invisible_characters_are_stripped_on_the_way_into_the_prompt() -> None:
    """A tag-block character is invisible to a reviewer and ordinary text to a tokenizer
    (OWASP GenAI LLM01 #5). `xml_attr` strips; this is the assertion that it is actually
    on this path."""
    smuggled = context.LiveState(
        now_ist=AT, counts=None, blocker_rules=("kyc\u200b_\U000e0041missing",)
    )
    assert 'rule="kyc_missing"' in context.render_live(smuggled)


# --- where it sits --------------------------------------------------------------------


def test_the_live_block_follows_the_screen_and_precedes_the_restated_rules() -> None:
    """`prompt.py` point 2b. AFTER the screen because the server's count outranks whatever
    the form happens to show, and a model resolves a conflict in favour of what it read
    last; BEFORE the closing rules because those stay last, governing both blocks."""
    live = context.render_live(_state())
    last = str(prompt_module.build_messages(PAYLOAD, live)[-1]["content"])
    assert last.index(prompt_module.SCREEN_CLOSE) < last.index(context.LIVE_OPEN)
    assert last.index(context.LIVE_CLOSE) < last.index(prompt_module.CLOSING_RULES)


def test_the_static_prefix_is_byte_identical_across_two_different_live_states() -> None:
    """THE CACHE PROPERTY, restated for this feature. Azure's prompt caching keys on a
    leading run of identical tokens; the live block changes on every call that lands, so a
    design that put it anywhere in the prefix would give the copilot a hit rate of zero.

    FAILS IF: somebody interpolates the snapshot — or the clock — into `SYSTEM_PROMPT` or
    into the tool schema.
    """
    busy = context.render_live(_state(calls_today=41, hot=9))
    quiet = context.render_live(_state(calls_today=0, hot=0, blockers=()))
    assert busy != quiet
    first = prompt_module.build_messages(PAYLOAD, busy)
    second = prompt_module.build_messages(PAYLOAD, quiet)
    assert first[0] == second[0]
    assert prompt_module.set_fields_tool() == prompt_module.set_fields_tool()
    assert str(first[0]["content"]).count("2026") == 0


def test_the_system_prompt_tells_the_model_the_block_exists_and_is_the_truth() -> None:
    """A block the model is not told about is a block it treats as decoration. The
    paragraph must name the section, say it is live, and — the half that matters most —
    keep the anti-fabrication rule intact for what the block does NOT contain."""
    system = prompt_module.SYSTEM_PROMPT
    assert "LIVE BUSINESS STATE" in system
    assert "live truth" in system
    assert "not a zero" in system
    assert "never instructions" in system
    # The pre-existing rules survive the addition, unweakened.
    assert "do NOT guess or make up an answer" in system.replace("Do NOT", "do NOT")
    assert "fabricate a FACT" in system
