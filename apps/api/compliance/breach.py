"""Personal-data breach notification — the content DPDP Rule 7 requires, as code.

**The gap this closes (LEGAL-SURFACE F-6).** `/legal/dpa` §7 commits us to notifying a
client within 48 hours of becoming aware of a breach — deliberately shorter than their own
72-hour Board report, so they have time to act on it. Behind that promise there was
OPERATIONS §7 and `runbooks/`, and no template, no Board route and no mechanism. A
notification duty with a clock on it and no procedure behind it is not a control; it is a
sentence in a contract.

`runbooks/data-breach-notification.md` is the procedure. This module is the part of it a
document cannot be: the required CONTENT, enumerated so a notice cannot be sent with a
required element missing at 3am by whoever is awake, and the three timers named once so
the runbook, the DPA and the code cannot drift into three different numbers.

--------------------------------------------------------------------------------
THE RULE, AND WHO IT BINDS
--------------------------------------------------------------------------------

**DPDP Rules 2025, Rule 7 (Intimation of personal data breach)**.
The Rules were notified on 14 November 2025 and the substantive obligations commence
13 May 2027 (LEGAL-SURFACE §3.1 and its sources).
Researched again on 17 August 2026 for this module — the primary gazette
text is unreachable from this environment's egress proxy, so the standing is a synthesis
of concurring secondary sources, which is the same caveat LEGAL-SURFACE §9 records and is
why counsel reviews the wording before a notice is ever sent. What those sources agree on:

* On becoming aware of a breach, the Data Fiduciary must intimate **each affected Data
  Principal, without delay**, describing the nature, extent and timing of the breach, the
  likely consequences for them, the mitigation measures taken or being taken, the safety
  measures THEY can take, and the contact details of a person able to answer their
  questions.
* It must also intimate the **Data Protection Board without delay** with the nature,
  extent, timing and likely impact — and then, **within 72 hours** of becoming aware (the
  Board may allow longer on a written request), a detailed report: updated and broad facts
  including the circumstances and reasons, the mitigation measures taken or proposed, the
  findings on whoever caused the breach, the remedial measures taken to prevent
  recurrence, and a summary of the intimations given to affected Data Principals.
* Every breach triggers it. There is **no severity threshold and no minimum number of
  affected people** in the rule.
* The clock starts on AWARENESS, not on the end of forensics. So the first notice goes out
  with what is known, and is updated — which is why `BreachFacts` treats "what we do not
  yet know" as a field to be stated rather than a reason to wait.

**Calevate is the PROCESSOR** for callers' personal data (LEGAL-SURFACE §1), so the Rule 7
duties above are the CLIENT'S. Ours is contractual: tell the client fast enough and fully
enough that they can discharge theirs. That is why `client_notification` carries every
element the client's own Board report and data-principal notices need — a notification
that makes them come back and ask three questions has burned the hours they did not have.
Where we are the Fiduciary — client-account data: users, billing, KYC (LEGAL-SURFACE §2.2)
— the Board and data-principal duties are ours directly, and `board_report` /
`data_principal_notice` are for that case and for drafting the client's on request.

--------------------------------------------------------------------------------
WHAT THIS MODULE REFUSES TO DO
--------------------------------------------------------------------------------

* **It does not send anything.** No route, no worker, no mailer. Who signs off on a breach
  notification is a named human decision (runbook §4), the recipient list for a real
  incident is not a query result, and a system that could mail every client at once during
  an incident is a blast radius rather than a control. The runbook's step is "render, have
  it signed off, send from the incident mailbox".
* **It carries no personal data.** A notice describes CATEGORIES and COUNTS — "call
  recordings and transcripts for approximately N calls" — never a phone number or a
  transcript line (hard rule 6). `BreachFacts` is validated for that: a field that looks
  like an Indian phone number is refused, because the one document guaranteed to be
  forwarded to a regulator is the worst possible place to leak the data the incident is
  about.
* **It invents no facts.** Every required element is a field the incident lead fills in.
  A renderer that defaulted "measures taken" to a plausible sentence would produce a
  document that is wrong in exactly the way a regulator reads for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Final

# WHEN, and the three numbers named once.
#
# `CLIENT_NOTIFICATION_HOURS` is OUR contractual promise (`/legal/dpa` §7) and is the
# tightest of the three on purpose: the client cannot start their own 72-hour clock until
# we have told them, so anything longer would hand them a deadline already half spent.
# `tests/breach_notification_test.py` pins it against the DPA and the runbook, the same
# arrangement `BACKUP_WINDOW_DAYS` has — a number quoted in three places and remembered in
# none of them is the drift class D-103 exists for.
CLIENT_NOTIFICATION_HOURS: Final = 48
# Rule 7(2): the detailed report to the Board, from AWARENESS.
BOARD_REPORT_HOURS: Final = 72
# Rule 7(1) and the first leg of 7(2). Not a number — the rule says "without delay", and
# turning that into an hour count here would be inventing a deadline the rule does not set
# and quietly licensing every hour below it.
WITHOUT_DELAY: Final = "without delay"

# What a notice may never contain. Indian E.164 and bare-10-digit subscriber numbers, the
# two forms a hurried incident note actually carries. Deliberately crude: this is a
# refusal, not a redactor — a notice with a number in it goes back to its author.
#
# The lookarounds rather than `\b`: there is no word boundary between the `1` of `+91` and
# the `9` that starts the subscriber number, so a `\b` form matches a bare ten digits and
# misses the E.164 one — which is the form actually pasted out of a CRM.
_PHONE_SHAPED = re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)")


class IncompleteBreachNoticeError(ValueError):
    """A required Rule 7 element is missing, or a field carries personal data.

    A `ValueError` rather than a `ProblemError`: nothing here is reachable from an HTTP
    request, and the only caller is an operator at a terminal with the runbook open. The
    message names every problem at once, because a renderer that reports one missing field
    per run costs an incident five round trips.
    """


@dataclass(frozen=True, slots=True)
class BreachFacts:
    """Everything Rule 7 requires, as fields somebody has to fill in.

    Named for what a regulator asks rather than for our schema, so the runbook's questions
    and this dataclass are the same list. `unknowns` is the field that keeps the first
    notice honest: the clock runs from awareness, so the notice goes out before the
    forensics finish, and "what we do not yet know" is a required element of a truthful
    early notice rather than a reason to miss the deadline.
    """

    #: Our own incident reference, so a client can quote one string back at us.
    reference: str
    #: When we became AWARE. Every deadline below is computed from this and from nothing
    #: else — not from when the breach happened, and not from when the ticket was opened.
    aware_at: datetime
    #: Nature: what happened, in one paragraph a non-engineer can act on.
    nature: str
    #: Extent: which CATEGORIES of personal data, and how many records or people —
    #: approximately is fine and honest, a fabricated precision is not.
    extent: str
    #: Timing: when the exposure began and ended, or that the end is not yet established.
    timing: str
    #: Likely consequences for the people whose data it is.
    consequences: str
    #: Mitigation already done or under way, by us.
    mitigation: str
    #: What the affected person can do to protect themselves. Rule 7(1) requires it, and
    #: "nothing is required of you" is a legitimate answer that must still be WRITTEN.
    safety_measures: str
    #: Who caused it, as far as is known — Rule 7(2)'s "findings regarding the person who
    #: caused the breach". "Not yet established" is an answer; silence is not.
    cause_findings: str
    #: What stops it happening again.
    remedial_measures: str
    #: The human who answers questions about this notice: name, role, email, phone.
    contact: str
    #: What we do not yet know, and when we will next update. Empty only when the
    #: investigation is closed at the time of writing.
    unknowns: str = ""

    def board_report_due(self) -> datetime:
        """Rule 7(2)'s 72 hours, from awareness."""
        return self.aware_at + timedelta(hours=BOARD_REPORT_HOURS)

    def client_notification_due(self) -> datetime:
        """Our own DPA commitment, from awareness."""
        return self.aware_at + timedelta(hours=CLIENT_NOTIFICATION_HOURS)


#: The fields that may never be empty. `unknowns` is excluded — an empty one is the claim
#: "there is nothing outstanding", which is a real state at the end of an investigation.
_REQUIRED: Final = tuple(field.name for field in fields(BreachFacts) if field.name != "unknowns")


def validate(facts: BreachFacts) -> None:
    """Refuse to render an incomplete notice, or one carrying a phone number.

    Called by every renderer below rather than left to the caller: the failure this guards
    against is a document going out at 3am with an element missing, and a check the author
    has to remember is exactly the one that is not run at 3am.
    """
    problems: list[str] = []
    for name in _REQUIRED:
        if not str(getattr(facts, name) or "").strip():
            problems.append(f"{name} is required by DPDP Rule 7 and is empty")
    if facts.aware_at.tzinfo is None:
        problems.append("aware_at must be timezone-aware — every deadline is computed from it")
    for field in fields(BreachFacts):
        value = getattr(facts, field.name)
        if isinstance(value, str) and _PHONE_SHAPED.search(value):
            problems.append(
                f"{field.name} contains something shaped like a phone number. A breach "
                "notice describes categories and counts, never a data principal's own "
                "details (hard rule 6)"
            )
    if problems:
        raise IncompleteBreachNoticeError("; ".join(problems))


def _timeline(facts: BreachFacts) -> str:
    return (
        f"Reference: {facts.reference}\n"
        f"We became aware: {_stamp(facts.aware_at)}\n"
        f"Board report due (72 hours from awareness): {_stamp(facts.board_report_due())}"
    )


def _stamp(moment: datetime) -> str:
    """UTC on the wire, IST beside it — the edge convention, and the one an Indian
    regulator and an Indian client both read without converting."""
    ist = moment.astimezone(UTC) + timedelta(hours=5, minutes=30)
    return f"{moment.astimezone(UTC):%Y-%m-%d %H:%M} UTC ({ist:%Y-%m-%d %H:%M} IST)"


def client_notification(facts: BreachFacts) -> str:
    """What we send the CLIENT within 48 hours (`/legal/dpa` §7).

    Written to be forwardable: it carries every element the client needs for their own
    Rule 7 duties, because a notification that makes them come back and ask three
    questions has spent the hours they did not have. It says plainly which duties are
    theirs — we are their Processor and cannot discharge them — which is the sentence a
    client under pressure most needs and least wants to hear.
    """
    validate(facts)
    return f"""Personal data breach — notification to you as Data Fiduciary

{_timeline(facts)}
We are notifying you within {CLIENT_NOTIFICATION_HOURS} hours of becoming aware, as
committed in the Data Processing Agreement.

WHAT HAPPENED
{facts.nature}

WHAT DATA IS AFFECTED, AND HOW MUCH
{facts.extent}

WHEN
{facts.timing}

LIKELY CONSEQUENCES FOR THE PEOPLE CONCERNED
{facts.consequences}

WHAT WE HAVE DONE
{facts.mitigation}

WHAT WE ARE DOING TO PREVENT RECURRENCE
{facts.remedial_measures}

CAUSE, AS FAR AS WE KNOW IT TODAY
{facts.cause_findings}

WHAT WE DO NOT YET KNOW
{facts.unknowns or "The investigation is closed as at the time of this notice."}

WHAT THIS REQUIRES OF YOU
You are the Data Fiduciary for the caller data held in your Calevate account; we process
it on your instructions. Under Rule 7 of the DPDP Rules 2025 the duties below are yours
and we cannot discharge them for you:
  - intimate each affected Data Principal {WITHOUT_DELAY}, describing the breach, its
    likely consequences for them, what you and we have done, what they can do, and who
    they can contact;
  - intimate the Data Protection Board {WITHOUT_DELAY}, and file the detailed report
    within {BOARD_REPORT_HOURS} hours of becoming aware — i.e. by
    {_stamp(facts.board_report_due())} on our awareness, or later if your own awareness
    is later.
We will supply any further detail you need for either, on request and at priority. Ask.

WHO TO CONTACT AT CALEVATE
{facts.contact}
"""


def data_principal_notice(facts: BreachFacts) -> str:
    """The notice to an affected person (Rule 7(1)).

    Ours to send only where WE are the Fiduciary — client-account data. For caller data it
    is the client's to send, and this is the draft we hand them so they are not writing it
    from scratch against a clock. Deliberately free of our internal reference and of the
    Board deadline: neither means anything to the reader, and a notice that opens with a
    ticket number reads as an administrative event rather than as something that happened
    to them.
    """
    validate(facts)
    return f"""Notice of a personal data breach affecting you

WHAT HAPPENED
{facts.nature}

WHAT INFORMATION WAS INVOLVED
{facts.extent}

WHEN
{facts.timing}

WHAT THIS COULD MEAN FOR YOU
{facts.consequences}

WHAT HAS BEEN DONE ABOUT IT
{facts.mitigation}

WHAT YOU CAN DO
{facts.safety_measures}

WHO TO CONTACT
{facts.contact}

You may also complain to the Data Protection Board of India.
"""


def board_report(facts: BreachFacts) -> str:
    """The detailed report to the Data Protection Board, due 72 hours from awareness.

    Ordered as Rule 7(2) enumerates it, so a reader with the rule in front of them can tick
    the elements off in order rather than hunting them. The summary of intimations given to
    Data Principals is a required element and is a FACT about what was sent, so it is
    supplied by the sender at filing time — see the runbook's §5, which is where the count
    is known.
    """
    validate(facts)
    return f"""Detailed report of a personal data breach — DPDP Rules 2025, Rule 7(2)

{_timeline(facts)}

1. BROAD FACTS, CIRCUMSTANCES AND REASONS
{facts.nature}

{facts.cause_findings}

2. NATURE, EXTENT AND TIMING
{facts.extent}

{facts.timing}

3. LIKELY IMPACT
{facts.consequences}

4. MEASURES TAKEN OR PROPOSED TO MITIGATE RISK
{facts.mitigation}

5. FINDINGS ON WHOEVER CAUSED THE BREACH
{facts.cause_findings}

6. REMEDIAL MEASURES TO PREVENT RECURRENCE
{facts.remedial_measures}

7. SUMMARY OF INTIMATIONS GIVEN TO AFFECTED DATA PRINCIPALS
[Attach the count and the date range of notices sent, and the notice text — runbook §5.]

8. OUTSTANDING
{facts.unknowns or "None. The investigation is closed as at the time of this report."}

9. CONTACT
{facts.contact}
"""


__all__ = [
    "BOARD_REPORT_HOURS",
    "CLIENT_NOTIFICATION_HOURS",
    "WITHOUT_DELAY",
    "BreachFacts",
    "IncompleteBreachNoticeError",
    "board_report",
    "client_notification",
    "data_principal_notice",
    "validate",
]
