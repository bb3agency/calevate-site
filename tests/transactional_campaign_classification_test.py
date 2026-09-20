"""A campaign may not be filed as `transactional`.

Amended TCCCPR Regulation 2(bt) defines a transactional voice call as one made *"in
response to Customer initiated transaction within thirty minutes of the transaction"*, and
non-promotional with it. That is a property of ONE call measured from ONE recipient's own
action; a campaign is a list dialled over hours or days, so no campaign can hold it. The
classification was a dropdown choice with nothing behind it.

**EVIDENCE CLASS: REPORTED** — a research agent's reading of the Second Amendment
Regulations 2025, relayed by the founder and recorded at
`docs/evidence/number-series-inbound-vs-outbound-2026-09-13.md` §3.1, which states the rule
these tests enforce: nothing in our vocabulary or our gate should let "transactional" and
"service" be used interchangeably. `trai.gov.in` is egress-blocked from this container, so
nobody in this repository has opened the gazette text.

WHAT THIS DOES NOT CLAIM, because the overclaim is the tempting one: refusing
`transactional` closes no escape that `service` does not equally offer — both sit on 160,
both are outside the preference scrub, both are attestable on an ordinary DID. What stops a
promotional list being filed under either is `dlt_template_mismatch`, which requires a
registrar-approved template OF THE CAMPAIGN'S OWN CLASS.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

from apps.api.campaigns.models import CAMPAIGN_CLASSIFICATIONS
from apps.api.campaigns.service import (
    CLASSIFICATION_REFUSALS,
    DIALABLE_CAMPAIGN_CLASSIFICATIONS,
    _CampaignFacts,
    _channel_blockers,
    _classification_blocker,
    dispatch_blockers,
    launch_blockers,
)

_AGENT_ID = uuid4()


def _facts(classification: str, **overrides: object) -> _CampaignFacts:
    """A campaign with every OTHER launch condition already satisfied, so a blocker in the
    result is attributable to the classification and to nothing else."""
    defaults: dict[str, object] = {
        "status": "draft",
        "classification": classification,
        "template_id": uuid4(),
        "template_status": "approved",
        "template_cls": classification,
        "series": "160" if classification != "promotional" else "140",
        "number_id": uuid4(),
        "number_dlt_status": "registered",
        "number_agent_id": _AGENT_ID,
        "agent_id": _AGENT_ID,
        "agent_status": "published",
        "disclosure": "This is an AI assistant.",
        "agent_direction": "outbound",
        "agent_deleted": False,
        "consent_source": "web_form",
        "consent_collected_at": None,
    }
    defaults.update(overrides)
    return _CampaignFacts(**defaults)  # type: ignore[arg-type]


def _rules(blockers: list[object]) -> set[str]:
    return {b.rule for b in blockers}  # type: ignore[attr-defined]


def test_transactional_is_not_a_classification_a_campaign_may_carry() -> None:
    assert "transactional" not in DIALABLE_CAMPAIGN_CLASSIFICATIONS
    assert frozenset({"promotional", "service"}) == DIALABLE_CAMPAIGN_CLASSIFICATIONS


def test_the_dialable_set_is_drawn_from_the_column_s_own_vocabulary() -> None:
    """A classification the gate allows that the column cannot hold would be dead config."""
    assert set(CAMPAIGN_CLASSIFICATIONS) >= DIALABLE_CAMPAIGN_CLASSIFICATIONS


def test_every_refused_classification_has_wording_of_its_own() -> None:
    """The generic fallback exists for safety, not as the answer. A classification we
    deliberately refuse is one somebody can be told WHY about."""
    refused = set(CAMPAIGN_CLASSIFICATIONS) - DIALABLE_CAMPAIGN_CLASSIFICATIONS
    assert refused == set(CLASSIFICATION_REFUSALS)


def test_an_otherwise_perfect_transactional_campaign_is_refused() -> None:
    blockers = _channel_blockers(_facts("transactional"))
    assert _rules(blockers) == {"classification_not_campaignable"}


def test_the_refusal_says_what_to_file_instead() -> None:
    blocker = _classification_blocker("transactional")
    assert blocker is not None
    reason = blocker.reason.lower()
    assert "thirty minutes" in reason
    assert "service campaign" in reason
    assert "promotional" in reason
    assert "instant-callback" in reason


def test_a_refused_campaign_is_not_also_told_to_fix_its_template_or_its_series() -> None:
    """Both of those advise the client to make paperwork match a classification we have
    just refused — a to-do list that cannot end in a launchable campaign."""
    mismatched = _facts("transactional", template_cls="promotional", series="140")
    assert _rules(_channel_blockers(mismatched)) == {"classification_not_campaignable"}


def test_the_rules_that_do_not_depend_on_classification_still_fire() -> None:
    """The guard narrows the two derived checks and nothing else: a transactional campaign
    with a missing template, an unregistered number and a number bound elsewhere is told
    all of it, because every one of those is wrong whatever the campaign calls itself."""
    broken = _facts(
        "transactional",
        template_id=None,
        number_dlt_status="pending",
        number_agent_id=uuid4(),
    )
    assert _rules(_channel_blockers(broken)) == {
        "classification_not_campaignable",
        "dlt_template_missing",
        "number_not_bound_to_agent",
        "number_not_registered",
    }


def test_service_and_promotional_campaigns_are_untouched() -> None:
    """The control. A refusal that also broke the two lawful classifications would be an
    outage wearing a compliance argument."""
    for classification in ("service", "promotional"):
        assert _classification_blocker(classification) is None
        assert _channel_blockers(_facts(classification)) == []


def test_an_unrecognised_classification_refuses_rather_than_falls_through() -> None:
    """The verdict is membership of the allowed set, so a fourth classification added to
    the column is refused until somebody decides it belongs. For a gate that governs who
    may be telephoned, that is the safe direction to default in."""
    blocker = _classification_blocker("notification")
    assert blocker is not None
    assert blocker.rule == "classification_not_campaignable"
    assert "notification" in blocker.reason


def test_both_gates_ask_it_so_a_running_campaign_stops_too() -> None:
    """`launch_blockers` is a photograph taken when the button was clicked. A campaign
    filed as transactional before this rule existed would otherwise dial to the end of its
    list; it is refused on the next dispatch tick because both gates share the one
    implementation rather than each carrying a copy."""
    for gate in (launch_blockers, dispatch_blockers):
        assert "_channel_blockers(" in inspect.getsource(gate)
