"""The client's record that they gave their access provider advance notice of autodialling.

WHAT THE OBLIGATION IS, AND HOW SURE WE ARE OF IT
-------------------------------------------------
TCCCPR 2018 as amended, **Regulation 4**, relayed as:

    "Every Sender shall notify the Originating Access Provider, in advance, about the use
    of Auto Dialer or Robo-Calls as well as the intended objective of such calls in
    writing."

**EVIDENCE CLASS: REPORTED — research-agent reading of TCCCPR 2018 and its Second
Amendment (12 Feb 2025), founder-relayed, 13 Sep 2026**
(`docs/evidence/number-series-inbound-vs-outbound-2026-09-13.md` §3.3). `trai.gov.in` is
egress-blocked from this container (CONNECT 403, measured 20 Sep 2026), so **nobody in
this repository has opened the regulation**. Under hard rule 11 that is below
VENDOR-PUBLISHED and may not reach a client-facing compliance CLAIM without a re-read —
which is why nothing here tells a client they are compliant. It tells them what their
access provider requires of them and records what they say they did.

**WHAT THE TEXT DOES NOT SAY, AND WHAT WE THEREFORE DO NOT MODEL.** The same evidence
records, in terms: *"Whether it is per sender, per campaign, per number or per objective
is not stated."* Nor is any advance PERIOD stated — "in advance" carries no number of days.
So this record is keyed on the SENDER, which is the one unit the text names, and the gate
asks one question only: has this sender told their access provider, before today, that
they autodial. It does not match a campaign's purpose against the recorded objective and
it does not enforce a notice period, because inventing either would be inventing the shape
of a legal obligation.

WHOSE OBLIGATION THIS IS
------------------------
Regulation 4 binds the **Sender**. Under our operating model the client business owns the
number, asserts the CLI and benefits from the calls, so the client is the Sender
(`docs/evidence/dlt-roles-and-operating-model-2026-09-18.md`, TCCCPR Reg 2(bf)) — exactly
as with the DLT Principal Entity registration and the ordinary-DID sender attestation.

**CALEVATE DOES NOT NOTIFY ON A CLIENT'S BEHALF, AND NOTHING HERE MAY IMPLY THAT WE DO.**
The client writes to their own Originating Access Provider; we record that they did, and
refuse to dial until they have. The alternative — a platform-level notice covering every
tenant — was rejected because it is a claim about a relationship we are not party to: the
OAP's counterparty is the Sender, and a vendor's assurance that "notice was given" is
worth nothing to the regulator holding the Sender liable.

INBOUND IS UNTOUCHED
--------------------
Regulation 4 is about *the use of* an autodialer, i.e. placing calls. A receptionist
answering a call the customer placed dials nothing, and the evidence document's §1 finding
is that inbound is not commercial communication at all. This predicate is reached only
from outbound paths and there is no inbound surface that asks it.

WHAT IS NOT HERE
----------------
* **No write route and no console screen.** The recording surface is a separate change;
  until it ships nothing in production can create one of these rows. That is stated here
  rather than implied, because a gate with no door is the half-wired shape the quality bar
  refuses to let pass silently.
* **No document bytes.** `notice_reference` holds the client's own handle for the letter
  or email they sent (a ticket number, a subject line). We are not the custodian of their
  correspondence with their carrier, and a second document-upload seam beside
  `carrier_application.py`'s would be a second way to do one thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final, Literal
from uuid import UUID

from calevate_shared.calling_window import ist_wall_clock
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: The two states a sender's notice can be in. `withdrawn` exists because a business that
#: stops autodialling can tell its access provider so, and because a record that could only
#: ever say "yes" would drift into saying yes about a notice that had been retracted.
NoticeState = Literal["notified", "withdrawn"]

NOTICE_STATES: Final[tuple[NoticeState, ...]] = ("notified", "withdrawn")

#: The longest access-provider name and objective we accept. Refused at the door rather
#: than by a CHECK constraint, for `carrier_application.py`'s reason: a limit that is ours
#: rather than a regulator's should be correctable without a migration.
MAX_ACCESS_PROVIDER_CHARS: Final = 120
#: The objective is the half of the notice the regulation names explicitly ("the intended
#: objective of such calls"), so it gets room for a sentence rather than a label.
MAX_OBJECTIVE_CHARS: Final = 500
MAX_NOTICE_REFERENCE_CHARS: Final = 200

AUTODIALER_NOTICE_MISSING_RULE: Final = "autodialer_notice_missing"
AUTODIALER_NOTICE_WITHDRAWN_RULE: Final = "autodialer_notice_withdrawn"
AUTODIALER_NOTICE_NOT_YET_EFFECTIVE_RULE: Final = "autodialer_notice_not_yet_effective"

#: Client-facing, and every word of it is the client's next action rather than ours. It
#: says WHO must write (them), TO WHOM (their own access provider), WHAT the letter must
#: contain (the autodialer use and the objective), and that inbound keeps working — the
#: last clause because a clinic reading a refusal needs to know their phone still answers.
AUTODIALER_NOTICE_MISSING_REASON: Final = (
    "Your business has not recorded that it told its telecom access provider, in writing "
    "and in advance, that these calls are placed by an automated dialler and what they "
    "are for. TRAI requires the sender of the calls to give that notice, so it has to "
    "come from you rather than from Calevate. Send it to the provider that supplies your "
    "outbound line, then record the date here. Answering incoming calls is unaffected."
)
AUTODIALER_NOTICE_WITHDRAWN_REASON: Final = (
    "Your business has withdrawn the notice it gave its telecom access provider about "
    "using an automated dialler, so outbound campaigns cannot run. Give the notice again "
    "and record it here to resume. Answering incoming calls is unaffected."
)


def autodialer_notice_not_yet_effective_reason(effective_on: date) -> str:
    """The client-facing wording when the recorded notice is dated in the future.

    Its own reason string rather than the missing one, because the next action is
    different: nothing is wrong with the paperwork, it simply has not taken effect yet.
    """
    return (
        f"The notice your business gave its telecom access provider about using an "
        f"automated dialler is dated {effective_on.isoformat()}, which is in the future. "
        "Regulation 4 requires the notice to be given in advance of the calls, so "
        "outbound campaigns can start from that date. Answering incoming calls is "
        "unaffected."
    )


@dataclass(frozen=True, slots=True)
class AutodialerNotice:
    """The latest notice a sender has recorded, read as an answer rather than a history.

    `recorded` is False for a tenant with no row at all, which is the normal state of
    every new account and a different fact from a withdrawn one — they send the client to
    different next actions, so `read_autodialer_notice` never returns `None` and no caller
    has to invent the "nothing filed yet" shape (`registration.PeRegistration`'s reason).
    """

    recorded: bool
    state: NoticeState | None
    access_provider: str | None
    objective: str | None
    notified_on: date | None
    notice_reference: str | None
    created_at: datetime | None

    def is_effective(self, *, today: date | None = None) -> bool:
        """Is this sender covered, as of `today` in IST?

        IST because "in advance" is a date a human wrote on a letter in India, and
        comparing it against a UTC calendar day would refuse a notice dated today for the
        first five and a half hours of it. `ist_wall_clock` is the repo's one spelling of
        that shift (hard rule: one way per problem).
        """
        if not self.recorded or self.state != "notified" or self.notified_on is None:
            return False
        return self.notified_on <= (today or ist_wall_clock(datetime.now(UTC)).date())


NOT_RECORDED: Final = AutodialerNotice(
    recorded=False,
    state=None,
    access_provider=None,
    objective=None,
    notified_on=None,
    notice_reference=None,
    created_at=None,
)

# Ordered by `id` after `created_at` because two rows written inside one transaction share
# `now()`, and a withdrawal that sorted before the notice it retracts would report the
# opposite of the truth. uuid7 is time-ordered, so the tiebreak is still chronological.
_LATEST_SQL = text(
    "SELECT state, access_provider, objective, notified_on, notice_reference, created_at "
    "FROM autodialer_notices WHERE tenant_id = :tid "
    "ORDER BY created_at DESC, id DESC LIMIT 1"
)


async def read_autodialer_notice(session: AsyncSession, *, tenant_id: UUID) -> AutodialerNotice:
    """This tenant's latest recorded notice, on the caller's RLS-scoped session.

    Hard rule 1: the query carries `tenant_id` as a predicate AND runs under RLS. The
    predicate is not the isolation — the GUC is — but a read whose predicate names the
    tenant returns zero rows twice over if a policy is ever loosened.
    """
    row = (await session.execute(_LATEST_SQL, {"tid": tenant_id})).first()
    if row is None:
        return NOT_RECORDED
    state = str(row[0])
    return AutodialerNotice(
        recorded=True,
        state="withdrawn" if state == "withdrawn" else "notified",
        access_provider=str(row[1]),
        objective=str(row[2]),
        notified_on=row[3],
        notice_reference=row[4],
        created_at=row[5],
    )


async def autodialer_notice_blocker(
    session: AsyncSession, *, tenant_id: UUID
) -> tuple[str, str] | None:
    """`(rule, reason)` if Regulation 4 blocks this sender's outbound, else None.

    The same shape `kyc_blocker`, `carrier_application_blocker` and
    `pe_registration_blocker` return, so every gate composes it identically and the launch
    preview and the dial gate name the condition with one string.

    THREE RULES RATHER THAN ONE, for the reason `kyc_blocker` returns a pair: "you have
    not told them", "you told them and took it back" and "the notice starts next week" are
    different facts with different next actions, and collapsing them would send a client
    to the wrong one.

    TENANT-SCOPED, NOT PER CAMPAIGN AND NOT PER NUMBER. The regulation names the Sender
    and our evidence says explicitly that the unit is not stated; the sender is the one
    unit we can support from the text. If an access provider later answers that the notice
    is per objective or per number, this predicate grows an argument — it does not have to
    be rebuilt, because the row already carries the objective it was given for.
    """
    notice = await read_autodialer_notice(session, tenant_id=tenant_id)
    if not notice.recorded:
        return (AUTODIALER_NOTICE_MISSING_RULE, AUTODIALER_NOTICE_MISSING_REASON)
    if notice.state != "notified":
        return (AUTODIALER_NOTICE_WITHDRAWN_RULE, AUTODIALER_NOTICE_WITHDRAWN_REASON)
    if not notice.is_effective():
        assert notice.notified_on is not None  # `is_effective` is False without one
        return (
            AUTODIALER_NOTICE_NOT_YET_EFFECTIVE_RULE,
            autodialer_notice_not_yet_effective_reason(notice.notified_on),
        )
    return None


async def record_autodialer_notice(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    access_provider: str,
    objective: str,
    notified_on: date,
    recorded_by: UUID,
    notice_reference: str | None = None,
    withdraw: bool = False,
) -> UUID:
    """Append one notice or withdrawal. INSERT-only (hard rule 4).

    A withdrawal is a new row carrying the same three facts, so the history reads as "they
    told Airtel this, on this date, and then retracted it" rather than losing the notice
    that was live while last month's calls were placed — `consent_ledger`'s rule applied to
    the sender's own declaration.

    **A FUTURE-DATED NOTICE IS ACCEPTED AND THEN REFUSED BY THE GATE, RATHER THAN REFUSED
    HERE.** A client who has written to their provider today naming a start date next
    Monday has done the right thing and should be able to record it; what must not happen
    is that it opens the gate before Monday. Rejecting the write would push them to record
    a date they did not write, which is worse evidence than a true one that does not yet
    count. `autodialer_notice_blocker` holds that line.
    """
    provider = access_provider.strip()
    stated_objective = objective.strip()
    reference = (notice_reference or "").strip() or None
    if not provider or len(provider) > MAX_ACCESS_PROVIDER_CHARS:
        raise ProblemError.business_rule(
            "autodialer_notice_provider_invalid",
            "Name the telecom access provider you sent the notice to.",
            remediation=f"Use between 1 and {MAX_ACCESS_PROVIDER_CHARS} characters.",
        )
    # The objective is required even on a WITHDRAWAL: the row has to say which notice was
    # withdrawn, and a withdrawal that named nothing would be unreadable a year later
    # beside three notices for three different purposes.
    if not stated_objective or len(stated_objective) > MAX_OBJECTIVE_CHARS:
        raise ProblemError.business_rule(
            "autodialer_notice_objective_invalid",
            "State what these automated calls are for, as your notice states it.",
            remediation=f"Use between 1 and {MAX_OBJECTIVE_CHARS} characters.",
        )
    if reference is not None and len(reference) > MAX_NOTICE_REFERENCE_CHARS:
        raise ProblemError.business_rule(
            "autodialer_notice_reference_invalid",
            "That reference for your notice is too long.",
            remediation=f"Use at most {MAX_NOTICE_REFERENCE_CHARS} characters.",
        )
    row_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO autodialer_notices "
            "(id, tenant_id, state, access_provider, objective, notified_on, "
            "notice_reference, recorded_by) "
            "VALUES (:id, :tid, :state, :ap, :obj, :on, :ref, :by)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "state": "withdrawn" if withdraw else "notified",
            "ap": provider,
            "obj": stated_objective,
            "on": notified_on,
            "ref": reference,
            "by": recorded_by,
        },
    )
    return row_id


__all__ = [
    "AUTODIALER_NOTICE_MISSING_REASON",
    "AUTODIALER_NOTICE_MISSING_RULE",
    "AUTODIALER_NOTICE_NOT_YET_EFFECTIVE_RULE",
    "AUTODIALER_NOTICE_WITHDRAWN_REASON",
    "AUTODIALER_NOTICE_WITHDRAWN_RULE",
    "MAX_ACCESS_PROVIDER_CHARS",
    "MAX_NOTICE_REFERENCE_CHARS",
    "MAX_OBJECTIVE_CHARS",
    "NOTICE_STATES",
    "NOT_RECORDED",
    "AutodialerNotice",
    "NoticeState",
    "autodialer_notice_blocker",
    "autodialer_notice_not_yet_effective_reason",
    "read_autodialer_notice",
    "record_autodialer_notice",
]
