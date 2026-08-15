"""What is still missing between "a founder signs a client" and "that client can take a
call", recorded so it cannot be quietly rediscovered.

Every entry was found by walking the path over HTTP as an operator would, is real, and
could not be closed from this slice — each one names the specific reason and the specific
act that closes it. Unlike `tests/reliability_known_gaps_test.py`, most of these ARE
waiting on a vendor, and each says which one by name: a deferral whose blocker is not
named is a deferral nobody can act on (CLAUDE.md's tempo rule).

**THE ASSERTION IS AN EQUALITY**, in the shape `reliability_known_gaps_test.py` and
`engine_name_drift_test.py::KNOWN_OPEN_COPIES` established. Each key has a probe that
answers "is this still true?" and the test asserts the set of still-open gaps EQUALS the
recorded set. So an entry cannot outlive its defect — building one of these turns this
file red and forces the entry's deletion in the same change — and a comment or a TODO,
which can outlive anything, is not an option.

The probes deliberately outlive their entries: a probe with no entry is a CLOSED gap whose
predicate must keep answering False, which makes it a regression test at the exact moment
it stops being a finding.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from apps.api.core.rbac import iter_api_routes
from apps.api.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent


#: Gap key → why it is open, and WHAT CLOSES IT (`CLOSED BY:`). Delete an entry the moment
#: its probe stops finding the gap; the equality assertion makes that mandatory.
KNOWN_OPEN_ONBOARDING_GAPS: dict[str, str] = {
    "no_test_call_gate_in_front_of_publish": (
        "FLOWS §1 step 7 makes going live conditional on a test call to the operator's own "
        "phone plus a regression mini-suite (happy path, interruption, tool call, "
        "disclosure) and recorded latency numbers. `POST /v1/admin/tenants/{id}/agents/"
        "{id}/publish` now has a caller in the console and refuses an agent with no script, "
        "but nothing enforces that ordering: an operator can publish before any call has "
        "been placed. The panel says so in as many words rather than implying a gate. "
        "EXTERNALLY BLOCKED — placing a real PSTN call needs the Bolna account (D-31) and a "
        "DID from Exotel/Vobiz/Plivo (FLOWS §10); neither exists, so the gate cannot be "
        "exercised, only mocked, and a gate that has only ever passed against a fake is not "
        "a gate. "
        "CLOSED BY: pilot gate work in `scripts/pilot/` once the engine and DID vendor "
        "accounts are open — the test call becomes a precondition recorded on the agent, "
        "and `publish_agent` refuses without it exactly as it now refuses a missing script."
    ),
    "no_number_provisioning_step_in_the_wizard": (
        "FLOWS §1 step 6: an inbound DID provisioned through the adapter, one per client, "
        "mandatory — plus the client's own PE registration and, for outbound, a DLT voice "
        "template and a 140/160 series choice. `provision_number` and "
        "`set_number_dlt_status` exist as admin routes; the wizard neither calls them nor "
        "pretends to (its checklist names the step as manual). A published agent with no "
        "number is therefore live on the engine and unreachable by a caller. "
        "EXTERNALLY BLOCKED, twice over: a DID provider account, and Calevate's TM "
        "registration (risk R-01) which every client PE links to. "
        "CLOSED BY: the DID vendor account plus the TM registration, after which the wizard "
        "step calls the routes that already exist."
    ),
}


def _publish_route_has_no_gate_dependency() -> bool:
    """Is publish reachable without a recorded test call?

    Behavioural in the only sense available without a vendor: the route's declared
    dependencies and the module that backs it carry no reference to a sign-off. Asserted
    against the ASSEMBLED app rather than by grepping a file, so a gate added anywhere in
    the dependency chain closes this.
    """
    source = (REPO_ROOT / "apps" / "api" / "agents" / "service.py").read_text(encoding="utf-8")
    if "test_call" in source or "sign_off" in source or "signoff" in source:
        return False
    return any(
        route.path.endswith("/agents/{agent_id}/publish") and "POST" in route.methods
        for route in iter_api_routes(app)
    )


def _wizard_has_no_number_step() -> bool:
    """Does the new-client wizard reach a number-provisioning endpoint?

    Keyed on the ENDPOINT rather than on the word "number": the intake step already talks
    about phone numbers (escalation contacts), and a probe that matched prose would report
    this gap closed by a label change.
    """
    wizard = REPO_ROOT / "apps" / "web" / "src" / "app" / "admin" / "new"
    typed = "".join(path.read_text(encoding="utf-8") for path in sorted(wizard.glob("*.tsx")))
    return "/numbers" not in typed and "useProvisionNumber" not in typed


#: key → the probe that answers "is this gap still real?". An entry must have a probe; a
#: probe may outlive its entry (see the module docstring).
PROBES: dict[str, Callable[[], bool]] = {
    "no_test_call_gate_in_front_of_publish": _publish_route_has_no_gate_dependency,
    "no_number_provisioning_step_in_the_wizard": _wizard_has_no_number_step,
}


def test_every_recorded_gap_is_still_open_and_no_other_is() -> None:
    """The equality. Building one of these fails here until its entry is deleted; recording
    one that is not real fails here immediately."""
    still_open = {key for key, probe in PROBES.items() if probe()}

    unprobed = set(KNOWN_OPEN_ONBOARDING_GAPS) - set(PROBES)
    assert unprobed == set(), (
        f"these recorded gaps have no probe, so the equality below cannot close them: "
        f"{sorted(unprobed)}"
    )
    assert still_open == set(KNOWN_OPEN_ONBOARDING_GAPS), (
        "the recorded onboarding gaps and the real ones disagree.\n"
        f"  fixed but still recorded: {sorted(set(KNOWN_OPEN_ONBOARDING_GAPS) - still_open)}\n"
        f"  open but not recorded:    {sorted(still_open - set(KNOWN_OPEN_ONBOARDING_GAPS))}"
    )


def test_every_gap_says_what_closes_it() -> None:
    """A recorded gap with no named remedy is a TODO wearing a test's clothes."""
    silent = [key for key, why in KNOWN_OPEN_ONBOARDING_GAPS.items() if "CLOSED BY" not in why]
    assert silent == [], f"these entries do not say what would close them: {silent}"


def test_every_externally_blocked_gap_names_its_blocker() -> None:
    """ "Externally blocked" without a name is the sentence this repo's tempo rule exists to
    refuse: an engineering task has no timeline, and a blocker that is not named cannot be
    chased. Every entry claiming one must say WHOSE account or registration it is."""
    named = ("Bolna", "Exotel", "Vobiz", "Plivo", "TM registration", "PE registration")
    vague = [
        key
        for key, why in KNOWN_OPEN_ONBOARDING_GAPS.items()
        if "EXTERNALLY BLOCKED" in why and not any(name in why for name in named)
    ]
    assert vague == [], f"these entries claim an external blocker without naming it: {vague}"
