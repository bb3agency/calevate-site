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
* `consent_expired` — found in the campaign round, 2 Sep 2026, and it was the FIRST ONE
  THIS FILE WAS SUPPOSED TO CATCH. It was classified, deliberately, as transient, on the
  argument that "a re-grant makes the number dialable again" — an argument that is true
  word for word of `no_consent`'s `withdrawn` arm, which is settled. An `expires_at` in
  the past only recedes further, so nothing the dispatcher waits for lifts it.

Three times is not a coincidence, and the third one says what the guard below has to be:
the classification is only as good as the INVENTORY it is checked against, and this file's
inventory saw about half the rules the gate can emit until it was taught to follow a
`(rule, reason)` pair out of a local variable (see `_emitted_rules`). This file does not
decide which side a rule belongs on — that is `PERSON_LEVEL_REFUSALS`' docstring, and the
test it applies is stated there: a person-level refusal is a fact about the PERSON or the
DESTINATION, not about the account, the paperwork, or a clock that can run the other way.
What this file refuses to allow is a rule that nobody DECIDED about, which is how all three
of the above got in.

Run: uv run pytest tests/dispatch_refusal_settlement_test.py -q
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from typing import Any

from apps.api.campaigns.service import CAMPAIGN_STOPPED_RULE, CAMPAIGN_WINDOW_CLOSED_RULE
from apps.api.compliance import service as gate_module
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
#:
#: The ACCOUNT, KYC, agreement and DLT-entity entries are the ones the walk below could not
#: see until it learnt to follow a `(rule, reason)` pair out of a local. Every one of them
#: is a fact about the CLIENT or their paperwork rather than about the person being called,
#: which is the membership test stated in `PERSON_LEVEL_REFUSALS`, and settling a contact
#: on one would mean a reinstated account never phoning a lead it is entitled to phone.
#: They are also the entries whose "waiting alone" is weakest — nothing lifts
#: `account_closed` for a churned tenant — and the door that stops those from being a
#: silent livelock is not this file: `dispatch_blockers` refuses the whole campaign for the
#: DLT ones before a contact is ever claimed, and a campaign with nothing left to dial is
#: now completed by `campaign_dispatch._settle_finished_campaign` BEFORE either gate runs.
TRANSIENT_REFUSALS: dict[str, str] = {
    BIG_RED_SWITCH_RULE: "an operator turns the platform halt off",
    "calling_hours": "the clock reaches the permitted window",
    "no_credits": "the account is topped up",
    "spend_cap": "the cap is raised or the period rolls over",
    "agent_missing": "the agent is restored; `archive_agent` refuses to create this state",
    "agent_not_live": "the agent is published; the same two doors apply",
    "agent_inbound_only": "the agent is given an outbound direction",
    "disclosure_missing": "the client fills the disclosure sentence in",
    "account_missing": "the organization row becomes visible again",
    "account_suspended": "operations lifts the suspension",
    "account_closed": "the account is reopened; a churned one dials nothing either way",
    "kyc_missing": "the client files their subscriber KYC",
    "kyc_not_verified": "the filed KYC is verified",
    "agreements_not_accepted": "the client accepts the current Terms/DPA/AUP",
    "tm_registration_missing": "Calevate's telemarketer registration goes live again",
    "pe_registration_missing": "the client records their DLT Principal Entity registration",
    "pe_registration_not_active": "the registrar returns the PE registration to active",
    "pe_verification_stale": "the PE registration is re-verified",
    "tm_link_not_active": "the client re-authorises Calevate as its telemarketer",
    "number_not_bound_to_agent": "the registered number is bound to this campaign's agent",
    "number_not_registered": "the registrar approves the number's DLT header",
    CAMPAIGN_STOPPED_RULE: "the client resumes the campaign",
    CAMPAIGN_WINDOW_CLOSED_RULE: "the clock reaches the campaign's own narrowed window",
}


def _emitted_rules() -> set[str]:
    """Every rule that can reach `_refuse_contact`'s settle-or-retry decision, from source.

    FROM THE AST, NOT FROM A LIST SOMEBODY MAINTAINS. A hand-kept inventory of refusals is
    the same artefact as the classification it is checking, so it would go stale in the
    same commit and for the same reason — the whole point is to notice a rule nobody
    thought about, and a rule nobody thought about is exactly the one that would not get
    added to a manual list.

    **IT USED TO SEE ABOUT HALF OF THEM, WHICH IS THE DISGUISE THE THIRD TEST BELOW WARNS
    ABOUT WEARING ITSELF.** The walk collected `rule=` only when the argument was a string
    literal or a module constant. But most of `check_dispatch`'s refusals arrive as a
    `(rule, reason)` PAIR from a helper and are passed on as a LOCAL variable —
    `rule, reason = stopped` then `DispatchDecision(rule=rule, ...)` — and a local resolves
    to no module constant, so `account_missing`, `account_suspended`, `account_closed`,
    `kyc_missing`, `kyc_not_verified`, `agreements_not_accepted`, every DLT entity rule and
    both agent-number rules were invisible here: unclassified, and therefore transient by
    default, which is precisely the state this file exists to make impossible. The
    convention that saves it is the repo's own — a blocker "returns the PAIR" and is
    annotated `-> tuple[str, str] | None` — so the resolution is mechanical rather than a
    second list.

    Two sources, because `_refuse_contact` has two:

    * `check_dispatch`, followed through its locals into the helpers, recursively;
    * `campaigns.service.campaign_dialable_now`, whose two rules the dispatcher hands to
      the same function (`campaign_dispatch._dispatch_for_campaign`). They were never in
      scope here and are just as capable of settling a contact wrongly.
    """
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    rules: set[str] = set()
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        bindings = _local_bindings(func)
        for node in ast.walk(func):
            if not isinstance(node, ast.keyword) or node.arg != "rule":
                continue
            rules |= _rules_from(node.value, tree=tree, bindings=bindings)
    # `dial_refusal_for_agent_status` returns its pair rather than passing `rule=`, so it
    # is asked directly. Deny-by-default there means every unknown status maps to one rule.
    for status in ("live", "draft", "paused", "archived", "invented_tomorrow"):
        refusal = dial_refusal_for_agent_status(status)
        if refusal is not None:
            rules.add(refusal[0])
    # The dispatcher's own two, which reach `_refuse_contact` from `campaign_dialable_now`.
    rules |= {CAMPAIGN_STOPPED_RULE, CAMPAIGN_WINDOW_CLOSED_RULE}
    return rules


def _local_bindings(func: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, list[ast.expr]]:
    """`name -> EVERY expression it is assigned`, for simple and tuple targets.

    A LIST, not the last assignment, and that is not tidiness: `check_dispatch` unpacks
    seven different blockers into the same two names (`rule, reason = ...`), so a dict of
    last-writes answers for the seventh and silently drops six — which is how the first
    version of this walk still reported only the number-blocker's rules after being taught
    to follow locals at all.

    Tuple targets map EVERY name to the whole right-hand side, which is what the
    `rule, reason = <blocker call>` shape needs: the rule is element 0 of whatever that
    call returns, and the collector below reads element 0 of the callee's own tuples.
    """
    bindings: dict[str, list[ast.expr]] = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign) or node.value is None:
            continue
        for target in node.targets:
            names = target.elts if isinstance(target, ast.Tuple) else [target]
            for name in names:
                if isinstance(name, ast.Name):
                    bindings.setdefault(name.id, []).append(node.value)
    return bindings


def _rules_from(
    value: ast.expr, *, tree: ast.Module, bindings: dict[str, list[ast.expr]], depth: int = 0
) -> set[str]:
    """Every rule string `value` can evaluate to."""
    if depth > 4:
        return set()
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value}
    if isinstance(value, ast.IfExp):
        return _rules_from(value.body, tree=tree, bindings=bindings, depth=depth + 1) | _rules_from(
            value.orelse, tree=tree, bindings=bindings, depth=depth + 1
        )
    if isinstance(value, ast.Name):
        constant = _module_constant(tree, value.id)
        if constant is not None:
            return {constant}
        found: set[str] = set()
        for bound in bindings.get(value.id, []):
            if bound is not value:
                found |= _rules_from(bound, tree=tree, bindings=bindings, depth=depth + 1)
        return found
    # `entity[0]` — the first blocker of a list a helper returned.
    if isinstance(value, ast.Subscript):
        return _rules_from(value.value, tree=tree, bindings=bindings, depth=depth + 1)
    if isinstance(value, ast.Await):
        return _rules_from(value.value, tree=tree, bindings=bindings, depth=depth + 1)
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return _blocker_rules(value.func.id)
    return set()


#: What makes a function a blocker, in the repo's own words: it "returns the PAIR". The
#: annotation is the contract, so it is the discriminator — never a list of names here,
#: which would be the maintained inventory this whole file refuses to rely on.
_PAIR_RETURNS = ("tuple[str, str]",)


def _blocker_rules(name: str, *, seen: frozenset[str] = frozenset()) -> set[str]:
    """The rule strings a `(rule, reason)` helper can return, read from ITS source.

    Resolved through the gate module's own globals rather than by walking imports: the
    name in the gate's source is the name bound there, so `getattr` answers exactly what
    Python would call. Recurses into the pair-returning helpers a blocker itself calls —
    `outbound_entity_blockers` appends `pe_registration_blocker`'s pair, so one level
    would have found the TM rule and missed all four PE ones.
    """
    if name in seen:
        return set()
    func = getattr(gate_module, name, None)
    if func is None:
        # Not a name the gate imported — a `DispatchDecision` local, a builtin, a method.
        return set()
    module = inspect.getmodule(func)
    if module is None:
        return set()
    annotations: dict[str, Any] = getattr(func, "__annotations__", {})
    if not any(pair in str(annotations.get("return", "")) for pair in _PAIR_RETURNS):
        return set()
    body = ast.parse(textwrap.dedent(inspect.getsource(func)))
    rules: set[str] = set()
    for node in ast.walk(body):
        if isinstance(node, ast.Tuple) and node.elts:
            rules |= _literal_or_module_constant(node.elts[0], module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            inner = getattr(module, node.func.id, None)
            if inner is not None and inner is not func:
                rules |= _blocker_rules_of(inner, seen=seen | {name})
    return rules


def _blocker_rules_of(func: Any, *, seen: frozenset[str]) -> set[str]:
    """The recursion step, keyed by the callee's own module so nesting keeps working."""
    module = inspect.getmodule(func)
    if module is None:
        return set()
    annotations: dict[str, Any] = getattr(func, "__annotations__", {})
    if not any(pair in str(annotations.get("return", "")) for pair in _PAIR_RETURNS):
        return set()
    body = ast.parse(textwrap.dedent(inspect.getsource(func)))
    rules: set[str] = set()
    for node in ast.walk(body):
        if isinstance(node, ast.Tuple) and node.elts:
            rules |= _literal_or_module_constant(node.elts[0], module)
    return rules


def _literal_or_module_constant(node: ast.expr, module: Any) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _literal_or_module_constant(node.body, module) | _literal_or_module_constant(
            node.orelse, module
        )
    if isinstance(node, ast.Name):
        value = getattr(module, node.id, None)
        if isinstance(value, str):
            return {value}
    return set()


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
    """The regression, named. All three were transient and all three ran for ever."""
    assert "no_consent" in PERSON_LEVEL_REFUSALS, "D-117's livelock is back"
    assert "consent_expired" in PERSON_LEVEL_REFUSALS, (
        "an expired consent is lifted by exactly the act that lifts `no_consent` — the "
        "person granting again — and by nothing the dispatcher can do or wait for. "
        "Transient, it re-claimed, re-gated and refunded the contact every thirty minutes "
        "for the life of the campaign, which never auto-completed"
    )
    assert "destination_not_india" in PERSON_LEVEL_REFUSALS, (
        "a foreign number is refused identically for ever — `phone_e164` is written once "
        "and rewritten only by the erasure sweep, which settles the row in the same "
        "statement"
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
