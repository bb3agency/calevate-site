"""Every refusal `check_dispatch` can give is a deliberate SETTLE-or-RETRY decision.

**THIS BUG HAS SHIPPED TWICE AND BOTH TIMES IT LOOKED LIKE NOTHING.** A refusal the
dispatcher treats as transient is re-claimed, re-gated, refunded and rescheduled every
thirty minutes. When the underlying fact can never change, that is for ever: the contact
never leaves `pending`, so the campaign never auto-completes and its `campaign.completed`
event never fires, and the client is shown a campaign that says "running" and calls nobody
with nothing on the screen to say why. Nothing errors. No alarm has anything to fire on.

* `no_consent` — D-117.
* `destination_not_india` — found in the voice round, 2 Sep 2026. `add_contacts` had
  closed the INGRESS and its own comment predicted this exact livelock for the dispatcher;
  closing the door did not settle who was already inside.
* `consent_expired` — found while building auto-reschedule callbacks, 2 Sep 2026 (D-510),
  and it was sitting in THIS FILE'S transient list wearing a considered-looking reason.
  The reason ("the person grants consent again") is true and was still the wrong side: it
  is true word for word of `no_consent`, whose `withdrawn` arm the same re-grant lifts and
  which is settled. An `expires_at` in the past only ever recedes further, so nothing the
  dispatcher does or waits for lifts it. The test that decides is not "can the fact ever
  change" — every fact can — it is **"can WAITING change it"**, and only an affirmative act
  by the PERSON lifts this one. `calling_hours` is the contrast that keeps the line honest:
  it is about the clock and becomes false by waiting alone.

Three times is a class with a pattern, so the fourth one is caught here rather than in
production. This file does not decide which side a rule belongs on — that is
`PERSON_LEVEL_REFUSALS`' docstring, and the test it applies is stated there: a
person-level refusal is a fact about the PERSON or the DESTINATION, not about the
account, the clock, or the paperwork. What this file refuses
to allow is a rule that nobody DECIDED about, which is how each of the above got in.

Run: uv run pytest tests/dispatch_refusal_settlement_test.py -q
"""

from __future__ import annotations

import ast
from pathlib import Path

from apps.api.compliance.service import (
    BIG_RED_SWITCH_RULE,
    PERSON_LEVEL_REFUSALS,
    dial_refusal_for_agent_status,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "apps" / "api" / "compliance" / "service.py"

#: Refusals that are TRANSIENT ON PURPOSE, each with the fact that can change to lift it.
#: A rule here is a promise that waiting can help — and, where waiting alone cannot, that
#: some other door prevents the campaign from sitting in the state for ever.
#:
#: The three agent-shaped entries are the subtle ones and they are transient CORRECTLY: an
#: archived agent can be un-archived, an inbound-only agent can be given an outbound
#: direction, and a blank disclosure line can be filled in. What stops them livelocking is
#: not this classification but two doors, both already pinned by
#: `tests/agent_lifecycle_test.py`: `agents/lifecycle.archive_agent` refuses to archive an
#: agent a running or scheduled campaign dials through, and
#: `campaigns/service.assert_agent_still_assignable` refuses the resume that would be the
#: other way in. Marking them person-level would SETTLE a contact whose agent comes back —
#: the opposite error, and the more expensive one, because a settled contact is never
#: re-gated.
TRANSIENT_REFUSALS: dict[str, str] = {
    BIG_RED_SWITCH_RULE: "an operator turns the platform halt off",
    "calling_hours": "the clock reaches the permitted window",
    "no_credits": "the account is topped up",
    "spend_cap": "the cap is raised or the period rolls over",
    "agent_missing": "the agent is restored; `archive_agent` refuses to create this state",
    "agent_not_live": "the agent is published; the same two doors apply",
    "agent_inbound_only": "the agent is given an outbound direction",
    "disclosure_missing": "the client fills the disclosure sentence in",
}


def _emitted_rules() -> set[str]:
    """Every `rule=` literal `check_dispatch` and its helpers can return, read from source.

    FROM THE AST, NOT FROM A LIST SOMEBODY MAINTAINS. A hand-kept inventory of refusals is
    the same artefact as the classification it is checking, so it would go stale in the
    same commit and for the same reason — the whole point is to notice a rule nobody
    thought about, and a rule nobody thought about is exactly the one that would not get
    added to a manual list.
    """
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    rules: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "rule":
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            rules.add(value.value)
        elif isinstance(value, ast.Name):
            # `rule=BIG_RED_SWITCH_RULE` and friends: resolve the module constant.
            resolved = _module_constant(tree, value.id)
            if resolved is not None:
                rules.add(resolved)
    # `dial_refusal_for_agent_status` returns its pair rather than passing `rule=`, so it
    # is asked directly. Deny-by-default there means every unknown status maps to one rule.
    for status in ("live", "draft", "paused", "archived", "invented_tomorrow"):
        refusal = dial_refusal_for_agent_status(status)
        if refusal is not None:
            rules.add(refusal[0])
    return rules


def _module_constant(tree: ast.Module, name: str) -> str | None:
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = getattr(node, "value", None)
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
    return None


def test_every_refusal_the_gate_can_give_is_classified_one_way_or_the_other() -> None:
    """FAILS IF: a new refusal rule appears and nobody said whether it settles.

    The failure message is the decision to make, not a puzzle: name the fact that can
    change to lift it (transient) or state why waiting can never help (person-level).
    """
    emitted = _emitted_rules()
    classified = set(PERSON_LEVEL_REFUSALS) | set(TRANSIENT_REFUSALS)
    unclassified = emitted - classified
    assert not unclassified, (
        f"{sorted(unclassified)}: `check_dispatch` can refuse for these and nothing says "
        "whether the refusal SETTLES the contact or retries it. Treated as transient by "
        "default, a permanent fact re-claims, re-gates and refunds the contact every "
        "thirty minutes for ever, the campaign never auto-completes, and no alarm fires. "
        "Add it to `PERSON_LEVEL_REFUSALS` (a fact about the person or the destination "
        "that waiting cannot change) or to `TRANSIENT_REFUSALS` here, naming the fact "
        "that lifts it."
    )


def test_nothing_is_classified_both_ways() -> None:
    """A rule in both sets would settle or retry depending on which reader you asked."""
    both = set(PERSON_LEVEL_REFUSALS) & set(TRANSIENT_REFUSALS)
    assert not both, f"{sorted(both)}: classified as both permanent and transient"


def test_no_rule_is_classified_that_the_gate_cannot_actually_give() -> None:
    """A classification for a rule nothing emits is a decision about nothing.

    It matters because it rots quietly in the direction that hurts: a rule renamed in the
    gate leaves its old spelling behind here, still looking like a considered decision,
    while the NEW spelling is unclassified and silently transient — which is the defect
    this file exists to catch, wearing the disguise of a file that catches it.
    """
    emitted = _emitted_rules()
    stale = (set(PERSON_LEVEL_REFUSALS) | set(TRANSIENT_REFUSALS)) - emitted
    assert not stale, (
        f"{sorted(stale)}: classified here but `check_dispatch` never emits them. If a "
        "rule was renamed, move the classification with it — the new name is unclassified "
        "and therefore transient by default."
    )


def test_the_livelocks_that_shipped_stay_settled() -> None:
    """The regression, named. Each was transient-by-default and each ran for ever."""
    assert "no_consent" in PERSON_LEVEL_REFUSALS, "D-117's livelock is back"
    assert "destination_not_india" in PERSON_LEVEL_REFUSALS, (
        "a foreign number is refused identically for ever — `phone_e164` is written once "
        "and rewritten only by the erasure sweep, which settles the row in the same "
        "statement"
    )
    assert "consent_expired" in PERSON_LEVEL_REFUSALS, (
        "a lapsed permission is not undone by waiting: `expires_at` in the past only "
        "recedes, and only the person re-granting lifts it — the same act that lifts "
        "`no_consent`, which is settled"
    )


def test_the_agent_shaped_refusals_are_transient_and_their_doors_are_named() -> None:
    """Their safety is two doors, not this classification — so say which, here.

    If a third door into "running campaign, unusable agent" is ever opened, these three
    become the livelock `destination_not_india` was, and the reader needs to know from this
    file that the classification was never what was protecting them.
    """
    for rule in ("agent_missing", "agent_not_live", "agent_inbound_only", "disclosure_missing"):
        assert rule in TRANSIENT_REFUSALS, f"{rule} must stay transient — an agent can return"
        assert rule not in PERSON_LEVEL_REFUSALS
    doors = Path(REPO_ROOT / "tests" / "agent_lifecycle_test.py").read_text(encoding="utf-8")
    assert "archive_agent" in doors, "the archive door is no longer pinned by a test"
    assert "assert_agent_still_assignable" in doors or "resume" in doors.lower(), (
        "the resume door is no longer pinned by a test"
    )
