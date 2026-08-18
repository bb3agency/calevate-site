"""The breach notification: the promise, the procedure, and the content the rule requires.

`/legal/dpa` §7 commits Calevate to notifying a client within 48 hours of becoming aware of
a personal data breach. Until D-179 there was nothing behind it — no template, no Board
route, no procedure — which LEGAL-SURFACE F-6 called the highest-value unmet item on the
audit. A clock in a contract with nothing on the other side of it is not a control.

What is now behind it: `runbooks/data-breach-notification.md` (the procedure and the
sign-off), `apps/api/compliance/breach.py` (the Rule 7 content, enforced) and
`scripts/breach_notice.py` (the operator's entry point). These tests hold the three to
each other and to the published promise, because the failure mode is not a crash — it is a
notice going out at 3am with a required element missing, or three documents quoting three
different deadlines.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from apps.api.compliance import breach
from apps.api.compliance.breach import (
    BOARD_REPORT_HOURS,
    CLIENT_NOTIFICATION_HOURS,
    BreachFacts,
    IncompleteBreachNoticeError,
    board_report,
    client_notification,
    data_principal_notice,
)
from scripts.breach_notice import main as render_cli

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "runbooks" / "data-breach-notification.md"
DPA = ROOT / "apps" / "web" / "src" / "lib" / "legal" / "dpa.ts"

AWARE_AT = datetime(2026, 8, 17, 4, 12, tzinfo=UTC)


def _facts(**overrides: object) -> BreachFacts:
    """A complete set, so every test below is about the ONE thing it changes."""
    base: dict[str, object] = {
        "reference": "CAL-BREACH-20260817-1",
        "aware_at": AWARE_AT,
        "nature": "A storage credential was used to list one object-storage prefix.",
        "extent": "Recordings and archived payloads for approximately 1,200 calls, 2 accounts.",
        "timing": "Valid from 2 August; single unauthorised listing on 16 August.",
        "consequences": "Someone outside Calevate may hold the audio and transcript of calls.",
        "mitigation": "The credential was revoked and the public-access block verified.",
        "safety_measures": "Nothing is required of you; do not act on unexpected callers.",
        "cause_findings": "Committed by us and missed by the secret scan. No third party.",
        "remedial_measures": "Secret scanning is blocking and credentials are prefix-scoped.",
        "contact": "Sri J, Data Protection Contact, security@calevate.tech",
        "unknowns": "Whether objects were fetched as well as listed is not yet established.",
    }
    return BreachFacts(**{**base, **overrides})  # type: ignore[arg-type]


# ------------------------------------------------------- 1. one number, three documents


def test_the_48_hour_promise_is_one_number_in_three_places() -> None:
    """The DPA published it, the runbook works to it and the renderer states it.

    A cross-language number kept in step by memory is the drift class D-103 exists for,
    and this one is a contractual commitment: if the DPA is renegotiated, this fails until
    the procedure and the notice follow it.
    """
    window = str(CLIENT_NOTIFICATION_HOURS)
    assert f"{window} hours" in DPA.read_text(encoding="utf-8"), (
        "the DPA no longer promises this window — the runbook and the notice still do"
    )
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert f"**{window} hours**" in runbook
    assert f"{window} hours" in client_notification(_facts())


def test_our_promise_is_tighter_than_the_clients_own_board_deadline() -> None:
    """The reason for 48 rather than 72, asserted rather than left in a comment: the
    client cannot start their Rule 7 clock until we have told them, so a window at or
    above theirs would hand them a deadline already spent."""
    assert CLIENT_NOTIFICATION_HOURS < BOARD_REPORT_HOURS


def test_the_deadlines_are_computed_from_awareness_and_from_nothing_else() -> None:
    """Rule 7's clock starts when the Fiduciary becomes AWARE — not when the breach
    happened, not when the ticket was opened, not when forensics closed."""
    facts = _facts()
    assert (facts.board_report_due() - facts.aware_at).total_seconds() == BOARD_REPORT_HOURS * 3600
    assert (
        facts.client_notification_due() - facts.aware_at
    ).total_seconds() == CLIENT_NOTIFICATION_HOURS * 3600


# ------------------------------------------------- 2. the content Rule 7 actually requires


def test_the_data_principal_notice_carries_every_element_rule_7_1_requires() -> None:
    """Nature, extent, timing, likely consequences, mitigation, what THEY can do, and a
    contact. A notice missing one of these is not a shorter notice; it is a
    non-compliant one, and the person reading it is the one who loses."""
    facts = _facts()
    notice = data_principal_notice(facts)
    for element in (
        facts.nature,
        facts.extent,
        facts.timing,
        facts.consequences,
        facts.mitigation,
        facts.safety_measures,
        facts.contact,
    ):
        assert element in notice, f"the notice to an affected person omits {element!r}"
    assert "Data Protection Board" in notice, "the reader is not told they can complain"


def test_the_board_report_carries_every_element_rule_7_2_requires() -> None:
    """Broad facts and reasons, the mitigation, the findings on who caused it, the
    remedial measures, and a summary of the intimations sent to data principals. The last
    one is a fact about what was sent, so the report leaves a marked slot rather than
    inventing it."""
    facts = _facts()
    report = board_report(facts)
    for element in (
        facts.nature,
        facts.extent,
        facts.timing,
        facts.consequences,
        facts.mitigation,
        facts.cause_findings,
        facts.remedial_measures,
        facts.contact,
    ):
        assert element in report
    assert "SUMMARY OF INTIMATIONS GIVEN TO AFFECTED DATA PRINCIPALS" in report
    assert "runbook §5" in report, "nothing tells the filer where that count comes from"


def test_the_client_notification_says_which_duties_stay_theirs() -> None:
    """We are the Processor for caller data, so the Rule 7 duties are the client's and we
    cannot discharge them. A notification that leaves that to be inferred is one the
    client discovers on day three."""
    notice = client_notification(_facts())
    assert "Data Fiduciary" in notice and "we process" in notice.lower()
    assert "Data Protection Board" in notice
    assert str(BOARD_REPORT_HOURS) in notice, "their own deadline is not stated"
    assert "without delay" in notice


def test_a_notice_states_what_is_not_yet_known_rather_than_waiting_for_it() -> None:
    """The clock runs from awareness, so the first notice goes out mid-investigation.
    Both states are rendered — an outstanding question, and a closed one — because a
    silent template would leave the author choosing between a delay and a false
    impression of completeness."""
    open_notice = client_notification(_facts())
    assert "WHAT WE DO NOT YET KNOW" in open_notice
    assert "not yet established" in open_notice

    closed = client_notification(_facts(unknowns=""))
    assert "investigation is closed" in closed


# ------------------------------------------------------------ 3. what it refuses to render


@pytest.mark.parametrize("missing", ["nature", "extent", "safety_measures", "contact"])
def test_a_notice_missing_a_required_element_is_refused(missing: str) -> None:
    """The 3am failure mode, closed at the renderer rather than in a checklist: a
    checklist is what is not run at 3am."""
    with pytest.raises(IncompleteBreachNoticeError) as raised:
        data_principal_notice(_facts(**{missing: "   "}))
    assert missing in str(raised.value)
    assert "Rule 7" in str(raised.value), "the author is not told which rule they are failing"


def test_every_missing_element_is_reported_at_once() -> None:
    """An incident does not have five round trips in it."""
    with pytest.raises(IncompleteBreachNoticeError) as raised:
        board_report(_facts(nature="", mitigation="", contact=""))
    message = str(raised.value)
    assert "nature" in message and "mitigation" in message and "contact" in message


def test_a_notice_carrying_a_phone_number_is_refused() -> None:
    """Hard rule 6, at the one document guaranteed to be forwarded to a regulator.

    A breach notice describes categories and counts. The number of the person the incident
    is about is the single worst thing to put in the document that will be filed, mailed
    onward and read years later — and an incident note written in a hurry is exactly where
    one gets pasted.
    """
    with pytest.raises(IncompleteBreachNoticeError) as raised:
        client_notification(_facts(extent="The record for +919876543210 was exposed."))
    assert "phone number" in str(raised.value)

    # Bare subscriber form too — the way it gets pasted out of a ticket.
    with pytest.raises(IncompleteBreachNoticeError):
        client_notification(_facts(nature="Caller 9876543210's recording was listed."))


def test_a_naive_awareness_timestamp_is_refused() -> None:
    """Every deadline is computed from `aware_at`. A naive timestamp on an incident that
    spans midnight IST is a missed statutory deadline with a plausible explanation."""
    with pytest.raises(IncompleteBreachNoticeError) as raised:
        client_notification(_facts(aware_at=datetime(2026, 8, 17, 4, 12)))
    assert "timezone-aware" in str(raised.value)


# ------------------------------------------------------------------ 4. the operator's path


def test_the_cli_renders_all_three_notices_from_the_incident_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The runbook's §3 command, exercised end to end — a procedure whose one executable
    step has never been run is a procedure with a defect in it."""
    incident = tmp_path / "incident.json"
    facts = _facts()
    incident.write_text(
        json.dumps(
            {
                **{
                    name: getattr(facts, name)
                    for name in BreachFacts.__dataclass_fields__
                    if name != "aware_at"
                },
                "aware_at": AWARE_AT.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    assert render_cli([str(incident)]) == 0
    printed = capsys.readouterr().out
    assert "CLIENT" in printed and "PRINCIPAL" in printed and "BOARD" in printed
    assert facts.reference in printed


def test_the_cli_reports_an_incomplete_file_instead_of_printing_half_a_notice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    incident = tmp_path / "incident.json"
    incident.write_text(json.dumps({"aware_at": AWARE_AT.isoformat()}), encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        render_cli([str(incident)])
    assert "missing a required key" in str(raised.value)


def test_the_cli_names_a_key_it_does_not_understand(tmp_path: Path) -> None:
    """A silently ignored key is a required element silently absent: `natur` for `nature`
    would render a notice missing the first thing Rule 7 asks for, with nothing to see."""
    incident = tmp_path / "incident.json"
    incident.write_text(
        json.dumps({"aware_at": AWARE_AT.isoformat(), "natur": "typo"}), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as raised:
        render_cli([str(incident)])
    assert "natur" in str(raised.value)


# --------------------------------------------------------------- 5. the procedure exists


def test_the_runbook_names_the_role_split_the_deadlines_and_what_is_still_missing() -> None:
    """The runbook is the deliverable F-6 asked for, and three of its properties are the
    ones that make it usable rather than decorative: it says whose duty each notice is
    (getting that backwards wastes the window), it names the sign-off, and it states in
    writing that the Board's own reporting channel is not recorded — so nobody discovers
    that at 4am."""
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert "Processor" in runbook and "Data Fiduciary" in runbook
    assert "Rule 7" in runbook
    assert "without delay" in runbook
    assert "sign" in runbook.lower(), "nobody owns the decision to send"
    assert "reporting channel is not recorded" in runbook, (
        "the runbook must say plainly that the Board's intake is still to be established, "
        "rather than implying a route exists"
    )
    assert "scripts.breach_notice" in runbook, "the procedure does not name its own tool"


def test_the_rule_is_cited_with_the_date_it_was_read() -> None:
    """Indian data-protection law moved substantially in 2025-2026 and this module states
    what a regulator requires. A citation without a retrieval date is a claim about the
    law today made by somebody who read it at an unknown time."""
    module = Path(breach.__file__).read_text(encoding="utf-8")
    assert "DPDP Rules 2025" in module and "Rule 7" in module
    assert "14 November 2025" in module, "the notification date of the Rules is not stated"
    assert "17 August 2026" in module, "no retrieval date for the reading behind this module"
