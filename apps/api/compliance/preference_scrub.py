"""The NATIONAL half of SEC-COMP §3's DNC promise: the customer preference register.

§3 has always certified a contact list as "DNC-scrubbed (national DND + tenant
`dnc_list`) with scrub timestamp". The tenant half is `compliance/dnc.py` and it works.
The national half was a claim about an empty set: `dnc_list.scope='global'` had no
writer anywhere, so every campaign that passed the gate passed it on half the sentence.
This module is the other half, and the shape it takes is decided by what the register
actually is rather than by what the column suggested.

WHAT THE NATIONAL REGISTER IS, AND WHY THERE IS NOTHING TO DOWNLOAD
-------------------------------------------------------------------
Under TCCCPR 2018 the register is the **National Customer Preference Register (NCPR,
formerly NDNC)** and it lives on the access providers' DLT platform. Every operator's
own DLT documentation says the same thing in the same words: *"the preference and
consent database will not be accessible to telemarketers due to secure controls and use
of blockchain technology on the DLT platform"* — a registered telemarketer submits a
list to the operator's scrub facility and receives back a scrubbed list, a reference
number and **a report carrying only the count, not the mobile numbers**; the scrubbed
file is valid **until 23:59:59** of the day it was produced. (Operator DLT FAQs —
ucc-bsnl.co.in/faq, dltconnect.airtel.in/faq, vilpower.in/faq, ucc-mtnl.in/faq;
TRAI TCCCPR 2018, trai.gov.in/sites/default/files/2024-09/RegulationUcc19072018.pdf;
Second Amendment 12 Feb 2025, trai.gov.in/sites/default/files/2025-02/
Regulation_12022025.pdf. Checked 2026-08.)

So the thing this repo was set up to build — a loader that syncs tens of millions of
NDNC rows into `dnc_list` under `scope='global'` — is a producer for a feed that does
not exist and cannot be obtained. Two independent reasons it would ALSO be wrong if it
did exist:

- **A preference is not an absolute block.** NCPR preferences are category-scoped: a
  subscriber in the fully-blocked category still receives TRANSACTIONAL communication,
  and a "block promotional" preference blocks only promotional traffic. A
  `dnc_list.scope='global'` row is read by `check_dispatch` as an absolute refusal for
  every tenant and every classification, so loading preference data there would refuse
  lawful transactional calls. That is a WRONG answer, not a conservative one.
- **The scrub is per list and per day, not per number and forever.** What a telemarketer
  is given is a decision about the list they submitted, expiring the same evening. The
  durable fact is therefore a SCRUB RUN, not a row per number — which is also the
  "scrub timestamp" §3 promises and which nothing in this repo recorded.

`dnc_list.scope='global'` keeps its meaning and finally gets its writer, but that
meaning is now stated: a platform-wide ABSOLUTE suppression (a regulator or TSP
instruction naming a number, or our own permanent refusal to dial one), written by
`compliance/dnc.py::add_global_numbers` through the audited ops surface. It is not the
NCPR and never was.

WHICH CAMPAIGNS THE SCRUB GATES
-------------------------------
`PREFERENCE_SCRUBBED_CLASSIFICATIONS` is `promotional` ONLY, and that is the register's
own scope rather than a convenience. The DLT content taxonomy has four types, and a
subscriber's preference does not touch two of them: under full DND every category is
blocked EXCEPT service-implicit, transactional traffic (OTPs, transaction alerts,
appointment reminders) is delivered whatever the preference, and it is
service-EXPLICIT — marketing sent under a consent — and promotional that a preference
suppresses. (Operator/aggregator DLT documentation is unanimous on this:
smsgatewaycenter.com/sms-types, plivo.com/blog/implicit-sms-content-template-types-in-india,
fast2sms.com/help/dlt-sms-faq. Checked 2026-08.)

Our three-member `campaigns.classification` maps onto it without interpretation:
`transactional` is transactional; `service` is service-IMPLICIT, because SEC-COMP §2.4
forbids cross-selling on a service call and the platform enforces that with topic
fencing, a 160-series header and a classification-matched template — a service campaign
that carried marketing would be a misclassification, which is a DIFFERENT and already
gated failure (`dlt_template_mismatch`, `number_series_mismatch`), not a reason to scrub
the wrong lists; and `promotional` is the one the register suppresses. Scrubbing a
transactional list would ALSO be wrong rather than merely wasteful: it would drop
delivery of the one class of call a fully-blocked subscriber is entitled to receive.

WHAT IS OURS AND WHAT IS NOT
-----------------------------
Everything here is ours and is built. What is NOT ours is the scrub itself: performing
one requires a Registered Telemarketer relationship with an access provider and a login
to that provider's DLT platform. That is the SAME external relationship that produces
`platform_state.tm_id` — the fact `launch_blockers` already refuses every campaign on as
`tm_registration_missing` — so this gate cannot be a self-inflicted outage: no campaign
on any deployment can dial until that relationship exists, and when it exists the scrub
facility comes with it. Recording a run is an operator action today because the DLT
scrub facility is a web portal; when an access provider exposes it as an API the
producer becomes a worker and this table does not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.service import IST
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import session_tenant
from apps.api.ingest.service import normalize_phone

log = get_logger(__name__)

# The classifications the customer preference register actually suppresses. A tuple
# rather than the bare string, because the DLT taxonomy has a fourth type — service
# EXPLICIT, marketing sent under a consent — which a preference does suppress and which
# `campaigns.classification` cannot yet express; the day it can, it is added here and
# nothing else moves. See the module docstring for the sources.
PREFERENCE_SCRUBBED_CLASSIFICATIONS = ("promotional",)

# A campaign in one of these states has nothing left to scrub: a completed or cancelled
# campaign will not dial again, and recording evidence against it would be evidence of
# nothing.
SCRUBBABLE_CAMPAIGN_STATUSES = ("draft", "scheduled", "running", "paused")

# How many numbers one recorded run may report as preference-blocked. Sized like
# `dnc.MAX_NUMBERS_PER_ADD` and for the same reason: the body is a paste, not a stream.
MAX_BLOCKED_NUMBERS = 5000

# Client-facing wording. It says what happened and who acts, and the answer to "who
# acts" is us — a client holds no DLT login and cannot scrub anything, so a blocker
# phrased as a to-do for them would be worse than no message (the reasoning
# `TM_REGISTRATION_MISSING_REASON` records).
NATIONAL_DND_SCRUB_MISSING_REASON = (
    "This contact list has not been scrubbed against the national customer preference "
    "register (DND). Calevate runs that scrub on an access provider's DLT platform "
    "before a promotional campaign dials, and records the reference the "
    "platform returns. Nothing to do at your end — ask us to run it."
)


def national_dnd_scrub_expired_reason(scrubbed_at: datetime) -> str:
    """The refusal for a run that has aged out, naming the day it was run.

    A date rather than "expired": a scrub is valid only to the end of the day it was
    produced (operator DLT FAQs), preference registrations change daily, and an
    operator reading "expired" cannot tell a scrub run an hour after midnight from one
    run three weeks ago.
    """
    day = (scrubbed_at.astimezone(UTC) + IST).strftime("%d %b %Y")
    return (
        f"The national DND scrub for this list was run on {day} IST, and a scrub is "
        "valid only until the end of the day it was run — preference registrations "
        "change every day. The list has to be scrubbed again before it dials. Nothing "
        "to do at your end."
    )


def national_dnd_scrub_incomplete_reason(added: int) -> str:
    """The refusal for a list that grew after it was scrubbed, naming how much."""
    return (
        f"{added} contact(s) were added to this list after it was scrubbed against the "
        "national customer preference register, so the scrub does not cover them. The "
        "whole list has to be scrubbed again before it dials. Nothing to do at your end."
    )


def scrub_expiry(scrubbed_at: datetime) -> datetime:
    """The last instant a scrub is valid: 23:59:59.999999 IST of the day it was run.

    Stored rather than derived at read time, because the rule belongs to the ARTEFACT:
    a run recorded today keeps the expiry that applied when it was produced even if we
    later learn a provider grants longer. Computed with the same `+ IST` shift
    `compliance.service.ist_now` uses, so there is one spelling of the conversion.
    """
    ist_wall = scrubbed_at.astimezone(UTC) + IST
    end_of_day = ist_wall.replace(hour=23, minute=59, second=59, microsecond=999999)
    return (end_of_day - IST).replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ScrubState:
    """The most recent recorded scrub of one campaign's list, and whether it still holds.

    `is_current` is computed here and nowhere else: the gate, the ops response and the
    client's progress screen must never disagree about whether a scrub is still good,
    and three callers each comparing a timestamp is how they start to.
    """

    recorded: bool
    provider: str | None = None
    scrub_ref: str | None = None
    scrubbed_at: datetime | None = None
    expires_at: datetime | None = None
    #: How many contacts were pending when the run was recorded — the size of the list
    #: the provider's verdict actually covers. Compared against the live pending count
    #: by `national_dnd_blocker`, which is what stops a scrub of three numbers standing
    #: in for a list of five thousand.
    submitted_count: int = 0
    suppressed_count: int | None = None

    @property
    def is_current(self) -> bool:
        if not self.recorded or self.expires_at is None:
            return False
        return self.expires_at > datetime.now(UTC)


NOT_SCRUBBED = ScrubState(recorded=False)


@dataclass(frozen=True, slots=True)
class ScrubRecorded:
    """What one recording did. COUNTS ONLY — the numbers a register suppressed are the
    most sensitive list in the request and none of them belong in a response body, a log
    line or the stored row (hard rule 6)."""

    state: ScrubState
    #: False when this exact (campaign, provider, reference) was already recorded. The
    #: contact marking still ran, because it is idempotent and a replay must not leave
    #: half the work done.
    first_time: bool
    submitted: int
    suppressed: int
    unmatched: int
    malformed: int


async def read_current_scrub(session: AsyncSession, *, campaign_id: UUID) -> ScrubState:
    """The latest recorded run for this campaign, expired or not.

    Latest by `scrubbed_at` — when the PROVIDER ran it — rather than by when we typed it
    in: two runs recorded out of order must still resolve to the newer scrub, and the
    provider's clock is the one the validity window belongs to.
    """
    row = (
        await session.execute(
            text(
                "SELECT provider, scrub_ref, scrubbed_at, expires_at, submitted_count, "
                "suppressed_count FROM preference_scrub_runs WHERE campaign_id = :cid "
                "ORDER BY scrubbed_at DESC, recorded_at DESC LIMIT 1"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        return NOT_SCRUBBED
    return ScrubState(
        recorded=True,
        provider=str(row[0]),
        scrub_ref=str(row[1]),
        scrubbed_at=row[2],
        expires_at=row[3],
        submitted_count=int(row[4]),
        suppressed_count=int(row[5]),
    )


async def national_dnd_blocker(
    session: AsyncSession, *, campaign_id: UUID, classification: str
) -> tuple[str, str] | None:
    """`(rule, reason)` if the national preference scrub blocks this campaign, else None.

    Returns the PAIR for the reason `kyc_blocker` and `first_campaign_hold_blocker` do:
    "nobody has scrubbed this list" and "the scrub has aged out" are different facts
    with the same remedy but very different urgency, and the launch preview, the
    dispatch tick and the ops console must name them identically.

    Asked at LAUNCH and again on every dispatch tick, which for this rule is not
    belt-and-braces: a scrub expires at midnight IST while the campaign keeps running,
    so a campaign that launched on a valid scrub is dialling an unscrubbed list by
    morning. That is the same argument `dispatch_blockers` makes about a registrar
    rejecting a template mid-campaign, with a deadline we can predict to the second.
    """
    if classification not in PREFERENCE_SCRUBBED_CLASSIFICATIONS:
        return None
    state = await read_current_scrub(session, campaign_id=campaign_id)
    if not state.recorded or state.scrubbed_at is None:
        return ("national_dnd_scrub_missing", NATIONAL_DND_SCRUB_MISSING_REASON)
    if not state.is_current:
        return ("national_dnd_scrub_expired", national_dnd_scrub_expired_reason(state.scrubbed_at))
    # A scrub covers the list that was SUBMITTED, and contacts can be uploaded to a
    # draft after one is recorded — scrub three numbers, add five thousand, launch. That
    # sequence needs no bad intent (a client finishes their upload while we are on the
    # portal) and it would let unscrubbed numbers through a gate reporting itself green,
    # so a list that has GROWN since the run is refused by name.
    #
    # Only growth. A pending count BELOW `submitted_count` is the ordinary state of a
    # running campaign — the scrub itself marks contacts `dnc_blocked`, and every dial
    # consumes one — so refusing on any inequality would block every campaign the moment
    # it started working.
    pending = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts "
                    "WHERE campaign_id = :cid AND status = 'pending'"
                ),
                {"cid": campaign_id},
            )
        ).scalar()
        or 0
    )
    if pending > state.submitted_count:
        return (
            "national_dnd_scrub_incomplete",
            national_dnd_scrub_incomplete_reason(pending - state.submitted_count),
        )
    return None


async def _campaign_for_scrub(session: AsyncSession, campaign_id: UUID) -> str:
    """The campaign's status, or the refusal that says why it cannot take a scrub."""
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    if status is None:
        # Absent, or another tenant's — RLS makes those one answer on purpose.
        raise ProblemError.not_found("Campaign")
    if str(status) not in SCRUBBABLE_CAMPAIGN_STATUSES:
        raise ProblemError.business_rule(
            "campaign_not_dialable",
            f"This campaign is {status}, so it will not dial again and a scrub of its "
            "list would record nothing.",
            remediation="Record the scrub against a campaign that can still dial.",
        )
    return str(status)


async def record_scrub_run(
    session: AsyncSession,
    *,
    campaign_id: UUID,
    provider: str,
    scrub_ref: str,
    scrubbed_at: datetime,
    blocked_numbers: list[str],
    recorded_by_admin_id: UUID | None,
) -> ScrubRecorded:
    """Record one national preference scrub of one campaign's list, and apply its result.

    **`submitted` is counted here, never accepted from the caller.** The obvious API
    takes the count the operator read off the provider's report, and it is the wrong
    one: a number the caller supplies is a number that can disagree with the list about
    to dial, and the disagreement is exactly what the artefact exists to rule out. What
    we can know is how many contacts were pending when the run was recorded, so that is
    what is stored, and it cannot be wrong about our own table.

    Idempotent on `(campaign_id, provider, scrub_ref)`: re-sending a recording — a retry
    whose response was lost, the same reference pasted twice — records nothing new and
    reports `first_time=False`. The contact marking is re-applied regardless, because it
    is a `status='pending'` filter and a replay must not be able to leave the first
    attempt half done.

    `preference_scrub_runs` is INSERT-only (hard rule 4, `APPEND_ONLY_TABLES`): a scrub
    is evidence that a list was clean at an instant, and an UPDATE that moved
    `scrubbed_at` forward would launder a stale scrub into a fresh one, which is the one
    thing this row must be unable to say.
    """
    await _campaign_for_scrub(session, campaign_id)

    if scrubbed_at.tzinfo is None:
        # UTC in the DB, IST at the edge (conventions). A naive instant here would be
        # compared against an aware `now()` and raise; it is pinned, not guessed at.
        scrubbed_at = scrubbed_at.replace(tzinfo=UTC)
    if scrubbed_at > datetime.now(UTC):
        raise ProblemError(
            kind="validation",
            code="preference_scrub_in_the_future",
            title="Scrub timestamp is in the future",
            detail="A scrub timestamp records something a provider already did.",
        )

    normalized: list[str] = []
    malformed = 0
    for raw in blocked_numbers:
        e164 = normalize_phone(raw)
        if e164 is None:
            malformed += 1
            continue
        normalized.append(e164)
    unique = list(dict.fromkeys(normalized))

    submitted = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts "
                    "WHERE campaign_id = :cid AND status = 'pending'"
                ),
                {"cid": campaign_id},
            )
        ).scalar()
        or 0
    )

    suppressed = 0
    if unique:
        marked = await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'dnc_blocked', updated_at = now() "
                "WHERE campaign_id = :cid AND status = 'pending' AND phone_e164 = ANY(:phones)"
            ),
            {"cid": campaign_id, "phones": unique},
        )
        suppressed = rowcount_of(marked)

    # The blocked numbers are NOT written to `dnc_list`, and that is a decision. A
    # preference-blocked number is blocked for THIS class of traffic today, not
    # suppressed for this tenant forever: the same subscriber may lawfully be sent a
    # transactional call tomorrow, and a `dnc_list` row would refuse it. The scrub
    # decides a list; the DNC list decides a person.
    expires_at = scrub_expiry(scrubbed_at)
    inserted = await session.execute(
        text(
            "INSERT INTO preference_scrub_runs (id, tenant_id, campaign_id, provider, "
            "scrub_ref, scrubbed_at, expires_at, submitted_count, suppressed_count, "
            "recorded_by_admin_id, recorded_at, created_at) VALUES (:id, :tid, :cid, "
            ":provider, :ref, :scrubbed, :expires, :submitted, :suppressed, :admin, "
            "now(), now()) ON CONFLICT (campaign_id, provider, scrub_ref) DO NOTHING"
        ),
        {
            "id": uuid7(),
            # Read back off the session rather than taken as an argument: the row's
            # tenant is then the tenant RLS is already enforcing on this connection, so
            # the two cannot disagree. `session_tenant` is the one module that spells
            # the GUC (`db/session.py`).
            "tid": await session_tenant(session),
            "cid": campaign_id,
            "provider": provider.strip(),
            "ref": scrub_ref.strip(),
            "scrubbed": scrubbed_at,
            "expires": expires_at,
            "submitted": submitted,
            "suppressed": suppressed,
            "admin": recorded_by_admin_id,
        },
    )
    first_time = rowcount_of(inserted) == 1

    # Counts, the provider and the reference — never a number (hard rule 6). The
    # reference is a provider-issued identifier for a run, not personal data, and it is
    # the handle an operator needs to find the run on the portal again.
    log.info(
        "preference_scrub_recorded",
        extra={
            "campaign_id": str(campaign_id),
            "provider": provider.strip(),
            "scrub_ref": scrub_ref.strip(),
            "submitted": submitted,
            "suppressed": suppressed,
            "first_time": first_time,
        },
    )
    return ScrubRecorded(
        state=await read_current_scrub(session, campaign_id=campaign_id),
        first_time=first_time,
        submitted=submitted,
        suppressed=suppressed,
        unmatched=len(unique) - suppressed,
        malformed=malformed,
    )


__all__ = [
    "MAX_BLOCKED_NUMBERS",
    "NATIONAL_DND_SCRUB_MISSING_REASON",
    "NOT_SCRUBBED",
    "PREFERENCE_SCRUBBED_CLASSIFICATIONS",
    "SCRUBBABLE_CAMPAIGN_STATUSES",
    "ScrubRecorded",
    "ScrubState",
    "national_dnd_blocker",
    "national_dnd_scrub_expired_reason",
    "national_dnd_scrub_incomplete_reason",
    "read_current_scrub",
    "record_scrub_run",
    "scrub_expiry",
]
