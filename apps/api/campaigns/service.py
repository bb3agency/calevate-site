"""Campaign lifecycle: draft → launch gate → dispatch → retries (FLOWS §5).

The two design centers:

**The launch gate returns NAMED blockers, not a boolean.** SURFACES §2b requires the
launch button to be "disabled with reasons listed until green", and SEC-COMP §3 names
the reasons: template approved, number series matches classification (140⇔promotional,
160/standard⇔service-transactional), contacts DNC-scrubbed, calling window sane. A
boolean gate produces a support ticket; a named gate produces a to-do list.

**Launch scrubs; dispatch re-checks.** The DNC scrub at launch marks known-blocked
contacts `dnc_blocked` so the client sees the real dialable count before committing.
But a number can join the list BETWEEN launch and dial (an opt-out from another call,
hard rule 5's propagation requirement), so the dispatcher runs the full compliance
gate again per contact at dial time. The scrub is UX; the per-dial check is the law.

**That scrub is the TENANT list, and §3 certifies two.** The national customer
preference register is not ours to read — an access provider's DLT platform scrubs a
list we submit and returns a reference, a count and a verdict valid to the end of the
day (`apps/api/compliance/preference_scrub.py` carries the sources). So the national
half is a recorded RUN rather than a query, `national_dnd_scrub_missing` /
`national_dnd_scrub_expired` refuse a promotional campaign without a current one, and
`dnc_scrubbed_at` finally records when our own scrub happened. Before this
pair, "scrubbed against both lists" and "scrubbed against one" were indistinguishable
from every screen.

**And the paperwork is re-read every tick, not only at launch.** `launch_blockers` is a
photograph of §3 taken when the button was clicked; a campaign then runs for days, over
which a registrar can reject the voice template, a TSP can pull the number's header, a
client's Principal Entity registration can be suspended, and Calevate's own telemarketer
registration can lapse. `dispatch_blockers` asks that subset again, under the SAME rule
names, once per campaign per dispatch tick — see its docstring for why `check_dispatch`
structurally cannot.

State transitions are CAS (BACKEND-PATTERNS §5) and go through
`db.transition.transition_status`, which turns `rowcount == 0` into the three answers it
actually stands for: the campaign already holds the requested status (success — the
second click is the same request), it moved to a DIFFERENT status (409
INVALID_STATUS_TRANSITION, naming what was found), or no visible campaign has that id
(404). Never silently retried, and never a read-then-write.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.models import CONSENT_SOURCES, REFUSED_CONSENT_SOURCES
from apps.api.compliance.models import PE_REGISTRATION_STATUSES, TM_LINK_STATUSES
from apps.api.compliance.preference_scrub import national_dnd_blocker, read_current_scrub
from apps.api.compliance.registration import pe_registration_blocker
from apps.api.compliance.service import (
    DEFAULT_WINDOW,
    NO_CREDITS_REASON,
    SPEND_CAP_REASON,
    account_stopped_blocker,
    credits_exhausted,
    first_campaign_hold_blocker,
    kyc_blocker,
    spend_capped,
)
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible
from apps.api.db.result import rowcount_of
from apps.api.db.transition import transition_status
from apps.api.ingest.service import normalize_phone
from apps.api.ops.service import TM_REGISTRATION_MISSING_REASON, read_tm_registration

log = get_logger(__name__)

# Series ⇔ classification (DATA-MODEL §6): 140 dials promotions, 160/standard dials
# service and transactional. A mismatch is a DLT violation, not a preference.
SERIES_FOR_CLASSIFICATION: dict[str, tuple[str, ...]] = {
    "promotional": ("140",),
    "transactional": ("160", "standard"),
    "service": ("160", "standard"),
}

DEFAULT_RETRY_POLICY: dict[str, Any] = {"max_attempts": 3, "backoff_minutes": [30, 120]}

# The client-facing wording of the two provenance refusals and the two DLT-entity ones,
# kept beside each other so the same condition is never explained two different ways.
NO_PROVENANCE_REASON = (
    "Record where this list's consent came from and when it was collected. A list we "
    "cannot trace to a consent cannot be dialled."
)
PURCHASED_LIST_REASON = (
    "This list is recorded as purchased. Calevate does not dial bought or rented "
    "contact lists — there is no consent artefact behind them (policy, SEC-COMP §3)."
)
# The two DLT-entity reasons moved to `compliance/registration.py`, next to the read of
# `dlt_registrations` and the predicate that emits them — this module held a second
# `SELECT status, tm_link_status` of its own, and one condition with two spellings is the
# drift `_entity_blockers` below now avoids by asking `pe_registration_blocker`.


@dataclass(frozen=True, slots=True)
class LaunchBlocker:
    rule: str
    reason: str


@dataclass(frozen=True, slots=True)
class _CampaignFacts:
    """One read of everything both gates ask about — the campaign, its template, its
    number and its agent. Shared so `launch_blockers` and `dispatch_blockers` cannot
    drift into asking the same question two different ways."""

    status: str
    classification: str
    template_id: UUID | None
    template_status: str | None
    template_cls: str | None
    series: str | None
    number_dlt_status: str | None
    agent_status: str | None
    disclosure: str | None
    agent_direction: str | None
    agent_deleted: bool
    consent_source: str | None


async def _campaign_facts(session: AsyncSession, campaign_id: UUID) -> _CampaignFacts:
    row = (
        await session.execute(
            text(
                "SELECT c.status, c.classification, c.dlt_template_id, "
                "  t.status AS template_status, t.classification AS template_cls, "
                "  n.series, n.dlt_status AS number_dlt_status, "
                # The AI sentence, not the legacy bundle (D-163) — the launch gate asks
                # whether the agent HAS one on file, which is still mandatory. Whether it
                # is volunteered at the top of the call is `ai_disclosure_enabled`, the
                # tenant's own decision, and never a launch blocker.
                "  a.status AS agent_status, a.ai_disclosure_line, "
                "  a.direction AS agent_direction, a.deleted_at AS agent_deleted_at, "
                "  c.consent_source "
                "FROM campaigns c "
                "LEFT JOIN dlt_templates t ON t.id = c.dlt_template_id "
                "LEFT JOIN phone_numbers n ON n.id = c.number_id "
                "JOIN agents a ON a.id = c.agent_id "
                "WHERE c.id = :cid"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return _CampaignFacts(
        status=str(row[0]),
        classification=str(row[1]),
        template_id=row[2],
        template_status=row[3],
        template_cls=row[4],
        series=row[5],
        number_dlt_status=row[6],
        agent_status=row[7],
        disclosure=row[8],
        agent_direction=row[9],
        agent_deleted=row[10] is not None,
        consent_source=row[11],
    )


async def _entity_blockers(
    session: AsyncSession, *, tenant_id: UUID, facts: _CampaignFacts
) -> list[LaunchBlocker]:
    """WHO may place these calls, and on what consent — SEC-COMP §3's first and fourth
    bullets. Calevate's telemarketer registration, the client's Principal Entity
    registration and its TM link, and the provenance of the contact list."""
    blockers: list[LaunchBlocker] = []

    # SEC-COMP §3, first bullet, COMPANY half: "Calevate TM registration exists AND
    # this client's PE registration + TM-link are active". Ours comes first because it
    # is not a fact about this client at all — it is one row in `platform_state`, false
    # for everybody at once, and a campaign dialled while it is not live is not a
    # client with a paperwork gap, it is US dialling as an unregistered telemarketer.
    # Reported alongside the client's own blockers rather than short-circuiting them:
    # a client who fixes their PE registration during our outage should see that
    # progress, and ops watching a launch preview should see the whole list.
    if not (await read_tm_registration(session)).is_live:
        blockers.append(LaunchBlocker("tm_registration_missing", TM_REGISTRATION_MISSING_REASON))

    # SEC-COMP §3, first bullet, CLIENT half: the client's DLT ENTITY registration.
    # Distinct from the header (`number_not_registered`) and the template
    # (`dlt_template_*`) checks — the registrar issues three registrations and none
    # implies another. Asked through `pe_registration_blocker`, exactly as the KYC and
    # first-campaign conditions below are asked through theirs: the condition is a fact
    # about the TENANT, so the launch gate, the dispatch tick and the operator console
    # all read one implementation rather than each carrying its own SQL.
    blocked_on_pe = await pe_registration_blocker(session, tenant_id=tenant_id)
    if blocked_on_pe is not None:
        blockers.append(LaunchBlocker(*blocked_on_pe))

    # SEC-COMP §3, fourth bullet: consent provenance for the list. NULL is "nobody has
    # said", which is what every campaign predating the columns honestly reports —
    # refused by name rather than defaulted into a consent nobody gave.
    if facts.consent_source is None:
        blockers.append(LaunchBlocker("consent_provenance_missing", NO_PROVENANCE_REASON))
    elif facts.consent_source in REFUSED_CONSENT_SOURCES:
        blockers.append(LaunchBlocker("consent_source_refused", PURCHASED_LIST_REASON))

    return blockers


def _channel_blockers(facts: _CampaignFacts) -> list[LaunchBlocker]:
    """WHAT this campaign may say, and from WHERE — SEC-COMP §3's second bullet. The
    registered voice template and the registered header of the right series."""
    blockers: list[LaunchBlocker] = []

    if facts.template_id is None:
        blockers.append(
            LaunchBlocker("dlt_template_missing", "Attach an approved DLT voice template.")
        )
    elif facts.template_status != "approved":
        blockers.append(
            LaunchBlocker(
                "dlt_template_not_approved", f"The DLT template is {facts.template_status}."
            )
        )
    elif facts.template_cls != facts.classification:
        blockers.append(
            LaunchBlocker(
                "dlt_template_mismatch",
                f"A {facts.classification} campaign cannot use a {facts.template_cls} template.",
            )
        )

    if facts.series is None:
        blockers.append(LaunchBlocker("number_missing", "Attach a calling number."))
    else:
        allowed_series = SERIES_FOR_CLASSIFICATION.get(facts.classification, ())
        if facts.series not in allowed_series:
            allowed = "/".join(allowed_series)
            blockers.append(
                LaunchBlocker(
                    "number_series_mismatch",
                    f"A {facts.classification} campaign must dial from a {allowed} number, "
                    f"not {facts.series}.",
                )
            )
        # The number-side twin of the template check. `dlt_status` moves to `registered`
        # through an audited admin step for the same reason `set_template_status` does:
        # dialling from an unregistered header is the misclassification that gets the
        # traffic dropped as spam and the complaints filed against the client's PE.
        if facts.number_dlt_status != "registered":
            blockers.append(
                LaunchBlocker(
                    "number_not_registered",
                    f"This number's DLT registration is {facts.number_dlt_status}; only a "
                    "registered number may place campaign calls.",
                )
            )

    return blockers


async def dispatch_blockers(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> list[LaunchBlocker]:
    """Every §3 condition that must STILL be true at dial time, by the same names.

    **The launch gate is a photograph; a campaign runs for days.** Between the click and
    the ring, the registrar can reject the voice template, a TSP can pull the number's
    header registration, the client's Principal Entity registration can be suspended,
    the client can withdraw Calevate's TM authorisation, and Calevate's own telemarketer
    registration can lapse — SEC-COMP §1's 5-complaints-in-10-days rule suspends a
    telemarketer, which is precisely the moment dialling must stop. None of that is
    exotic; all of it is the registrar and the TSPs doing their job to a live campaign.

    `compliance.service.check_dispatch` cannot ask any of it. That gate is per NUMBER
    and per AGENT — the platform halt, the agent, the tenant's cap and wallet, the hour,
    the DNC list — and it is called from three surfaces that have no campaign at all.
    These are CAMPAIGN facts, so they are asked here, once per campaign per tick, by the
    dispatcher, inside the transaction that claims the contacts.

    What is deliberately NOT here:

    - the launch-only questions — `status`, `no_contacts`, `all_contacts_dnc`. A running
      campaign is not a draft and its contact list is being consumed by design;
    - anything `check_dispatch` already asks per contact (agent, spend cap, credits,
      calling hours, DNC). Asking twice would make the two gates disagree the first time
      one of them changed.

    RESUME is the reason this cannot live only at launch. `set_campaign_status` moves a
    campaign from `paused` back to `running` with a bare CAS and no gate, so a campaign
    can sit paused for a week — long enough for any of the above — and come back running
    with nothing having re-read the paperwork.
    """
    facts = await _campaign_facts(session, campaign_id)
    # The first-campaign hold is asked here as well as at launch, and it is the one
    # tenant-level rule in this list. It belongs to the same family as the rest: a
    # release is WITHDRAWABLE — complaints arrive, a list turns out to be bought — and a
    # campaign that keeps dialling to the end of its list after we revoked the account's
    # clearance is the exact failure this gate exists to prevent. `check_dispatch` cannot
    # carry it: that gate is also the single-lead paths, which are not campaigns
    # (`compliance/first_campaign.py` states the residual that leaves).
    held = await first_campaign_hold_blocker(session, tenant_id=tenant_id)
    # The national DND scrub is the one rule here with a deadline we can predict to the
    # second: a provider's scrub is valid only to 23:59:59 IST of the day it was run, so
    # a campaign that launched on a valid scrub is dialling an unscrubbed list by
    # morning. Asking it once at launch would make the expiry decorative.
    unscrubbed = await national_dnd_blocker(
        session, campaign_id=campaign_id, classification=facts.classification
    )
    return [
        *([LaunchBlocker(*held)] if held is not None else []),
        *(await _entity_blockers(session, tenant_id=tenant_id, facts=facts)),
        *_channel_blockers(facts),
        *([LaunchBlocker(*unscrubbed)] if unscrubbed is not None else []),
    ]


def _parse_hhmm(value: object) -> time:
    """Strict HH:MM only — seconds, offsets and prose all fail the same way."""
    return datetime.strptime(str(value), "%H:%M").time()


def _validated_window(calling_hours: dict[str, Any]) -> dict[str, str]:
    """Validate a per-campaign calling window at CREATE time, so an unlawful window
    can never be stored — which is why launch_blockers needs no window check.

    The rule is NARROWING-ONLY: a client may shrink when their campaign dials
    (lunch-hour only), never widen past the platform's 09:00-21:00 IST window.
    That window is TRAI law (hard rule 5), not a default a client can override.
    """
    try:
        start = _parse_hhmm(calling_hours.get("start"))
        end = _parse_hhmm(calling_hours.get("end"))
    except (TypeError, ValueError):
        raise ProblemError(
            kind="validation",
            code="campaign_window_invalid",
            title="Invalid calling window",
            detail='calling_hours must be {"start": "HH:MM", "end": "HH:MM"} in IST.',
        ) from None
    if start >= end:
        raise ProblemError(
            kind="validation",
            code="campaign_window_invalid",
            title="Invalid calling window",
            detail="The window's start must be before its end.",
        )
    platform_start, platform_end = DEFAULT_WINDOW
    if start < platform_start or end > platform_end:
        raise ProblemError(
            kind="validation",
            code="campaign_window_outside_platform_hours",
            title="Calling window outside platform hours",
            detail=(
                "A campaign window may only narrow the platform's 09:00-21:00 IST "
                "calling hours. That window is the law (TRAI), not a default — "
                "nothing dials outside it."
            ),
        )
    # Re-serialize rather than echo the input: the stored shape is exactly two
    # canonical HH:MM strings, nothing a client smuggled alongside them.
    return {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}


def _validated_provenance(
    consent_source: str | None, consent_collected_at: datetime | None
) -> tuple[str | None, datetime | None]:
    """Validate consent provenance at the write paths, so the column can only ever hold
    an answer the gate can CHECK (SEC-COMP §3).

    `(None, None)` is legal and means "nobody has said yet" — the honest state of every
    campaign that predates the columns, and of a draft whose owner has not been asked.
    The gate refuses it by name; what it must never do is confuse it with an answer.

    Everything else is refused HERE rather than at launch, because a provenance the gate
    would have to interpret is exactly what §3's "source + date" is written to avoid:

    - a source outside the enum — free text is a box someone types "yes" into;
    - half an answer — a source with no date cannot be aged against a consent since
      withdrawn, and a date with no source names nothing;
    - a collection date in the future, which is not a record of anything that happened.
    """
    if (consent_source is None) != (consent_collected_at is None):
        raise ProblemError(
            kind="validation",
            code="consent_provenance_incomplete",
            title="Incomplete consent provenance",
            detail="Consent provenance needs both a source and the date it was collected.",
        )
    if consent_source is None or consent_collected_at is None:
        return None, None
    if consent_source not in CONSENT_SOURCES:
        raise ProblemError(
            kind="validation",
            code="consent_source_invalid",
            title="Unrecognised consent source",
            detail=f"A consent source must be one of: {', '.join(CONSENT_SOURCES)}.",
            fields=[
                {
                    "field": "consent_source",
                    "rule": "enum",
                    "message": "pick the basis this list was collected under",
                }
            ],
        )
    collected = consent_collected_at
    if collected.tzinfo is None:
        # UTC in the DB, IST at the edge (conventions): a naive datetime here would be
        # compared against an aware `now()` and raise, so it is pinned, not guessed at.
        collected = collected.replace(tzinfo=UTC)
    if collected > datetime.now(UTC):
        raise ProblemError(
            kind="validation",
            code="consent_collected_in_future",
            title="Consent collected in the future",
            detail="A consent collection date records something that already happened.",
        )
    return consent_source, collected


def campaign_window_open(calling_hours: dict[str, Any] | None, now_ist: datetime) -> bool:
    """Is this campaign's OWN window open right now (IST)?

    None means "no extra restriction — the platform window applies", so True: this
    helper answers only the narrowing question. The platform's 09:00-21:00 IST
    bound is enforced separately by the per-dial compliance gate, which every
    claimed contact still passes through (defense in depth).
    """
    if calling_hours is None:
        return True
    try:
        start = _parse_hhmm(calling_hours["start"])
        end = _parse_hhmm(calling_hours["end"])
    except (KeyError, TypeError, ValueError):
        # A window we cannot read is a window we cannot honour: fail closed.
        # (Unreachable via create_campaign, which validates before storing.)
        return False
    return start <= now_ist.time() <= end


# The two rules `campaign_dialable_now` can return. Named constants because a runbook,
# a metric label and a test all cite them, and because they join the vocabulary
# `dispatch_blockers` and `check_dispatch` already share.
CAMPAIGN_STOPPED_RULE = "campaign_not_running"
CAMPAIGN_WINDOW_CLOSED_RULE = "campaign_window_closed"


async def campaign_dialable_now(
    session: AsyncSession, *, campaign_id: UUID, now_ist: datetime
) -> str | None:
    """The CAMPAIGN facts that must still hold at the instant of EACH dial, or the rule
    that stops it. `None` means this campaign may place its next call.

    **Both of these were checked once per tick and then not again, and a tick is not an
    instant.** `_dispatch_for_campaign` claims a batch in one transaction and then dials
    it one contact at a time, each in its own short transaction with an engine round
    trip in the middle; `_run_tick` chooses every tenant's campaigns BEFORE any of them
    dials, so the gap between "this campaign may dial" and "this contact is dialling"
    spans every earlier tenant's dials too — bounded only by the 300s job timeout. Two
    things fall through that gap:

    - **the client's pause button.** The campaign's status IS re-read, but inside the
      claiming statement, which is exactly the wrong side of the commit: a pause landing
      while the batch is mid-flight let every remaining contact ring. The mid-campaign
      safeties in FLOWS §5 (a complaint spike, a cap breach) auto-pause for the moment
      when stopping fast is the whole point, and the big red switch already stops a batch
      mid-flight because `check_dispatch` re-reads it per contact. This is the same
      property for the per-campaign switch.
    - **the campaign's own narrowed calling window.** `calling_hours` may only SHRINK the
      platform's 09:00-21:00 IST (`_validated_window`), so `check_dispatch` refusing
      outside the platform window is not enough to honour it: a campaign restricted to
      09:00-12:00 whose window check passed at 11:59 dialled at 12:05, because nothing
      asked again.

    ONE statement, and `status = 'running'` is in the WHERE clause rather than compared
    in Python: paused, cancelled, completed, deleted and another tenant's id are five
    ways of saying the same thing to a dialler — this campaign is not dialling — and
    folding them into the absence of a row means there is no branch that can answer any
    of them differently. Absent therefore fails CLOSED, like every other read on this
    path.

    Asked by the dispatcher and deliberately NOT by `check_dispatch`: that gate is also
    the D-21 single-lead button and the instant callback, neither of which has a
    campaign — the same line `dispatch_blockers` draws for the same reason.
    """
    row = (
        await session.execute(
            text("SELECT calling_hours FROM campaigns WHERE id = :cid AND status = 'running'"),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        return CAMPAIGN_STOPPED_RULE
    if not campaign_window_open(row[0], now_ist):
        return CAMPAIGN_WINDOW_CLOSED_RULE
    return None


async def create_campaign(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str,
    classification: str,
    number_id: UUID | None,
    dlt_template_id: UUID | None,
    concurrency: int,
    calling_hours: dict[str, Any] | None = None,
    consent_source: str | None = None,
    consent_collected_at: datetime | None = None,
) -> UUID:
    """Create a draft campaign.

    Consent provenance (SEC-COMP §3) is accepted here and OPTIONAL here, which is a
    deliberate split of concerns: a draft may be assembled before the client has dug
    out when their list was collected, but it cannot LAUNCH without saying — the gate
    is the enforcement point, not this function. Making it mandatory at creation would
    also make the requirement depend on which version of the frontend the browser
    happens to be running; making it mandatory at the gate makes it depend on nothing.
    """
    # EVERY id the caller supplied, resolved under the caller's own RLS before anything
    # is stored. All three are foreign keys, and PostgreSQL checks those with row
    # security bypassed, so without this a client can file a campaign against a
    # neighbour's agent, dial from their DLT-registered header or cite their registered
    # voice template (`db/ownership.py` carries the mechanism and the harm). Every
    # consumer downstream does fail closed — the launch gate's joins run under this same
    # session, so a foreign number reads back as `number_missing` — but the reference is
    # STORED, one un-scoped join away from disclosure, and the campaign it produces is a
    # row the client owns and can never launch or explain: `_campaign_facts` INNER JOINs
    # `agents`, so its own launch-check answers "Campaign not found".
    await assert_visible(session, "agent", agent_id)
    await assert_visible(session, "phone_number", number_id)
    await assert_visible(session, "dlt_template", dlt_template_id)

    # Validated HERE, at the only write path, so the column can never hold a window
    # the dispatcher would have to second-guess. None = "platform window applies".
    window = _validated_window(calling_hours) if calling_hours is not None else None
    source, collected_at = _validated_provenance(consent_source, consent_collected_at)
    campaign_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, number_id, "
            "dlt_template_id, status, concurrency, retry_policy, calling_hours, "
            "consent_source, consent_collected_at, created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :name, :cls, :nid, :dlt, 'draft', :conc, "
            "CAST(:retry AS jsonb), CAST(:window AS jsonb), :source, :collected, now(), now())"
        ),
        {
            "source": source,
            "collected": collected_at,
            "id": campaign_id,
            "tid": tenant_id,
            "aid": agent_id,
            "name": name,
            "cls": classification,
            "nid": number_id,
            "dlt": dlt_template_id,
            "conc": concurrency,
            "retry": json.dumps(DEFAULT_RETRY_POLICY),
            "window": json.dumps(window) if window is not None else None,
        },
    )
    return campaign_id


async def add_contacts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    contacts: list[dict[str, Any]],
) -> dict[str, int]:
    """CSV rows → contact rows. Dedupe inside the upload AND against the campaign
    (UNIQUE(campaign_id, phone)); malformed numbers are counted, never guessed at.

    `scheduled` is accepted alongside `draft` because both are PRE-LAUNCH states — a
    campaign waiting for Monday has not dialled anyone, and refusing its contact upload
    would leave the client's only route "cancel the schedule, upload, re-pick the date".
    It is the same pairing `declare_consent_provenance` and `launch_blockers` already
    use. What stays refused is everything from `running` on: contacts appearing under a
    campaign mid-dial would move the "N people will be called" number the client
    confirmed at launch.

    ABSENT AND NOT-PRE-LAUNCH ARE TWO DIFFERENT FACTS, and a client fixes only one of
    them. This used to answer `campaign_not_draft` to both, so an id this caller cannot
    see — another tenant's, or one that never existed — came back as "Contacts can only
    be added before a campaign is launched": an instruction to un-launch a campaign
    there is nothing to un-launch, and a claim that the id names something. RLS makes
    absent and another-tenant's indistinguishable here on purpose, which is exactly why
    the answer has to be 404 rather than a sentence about a lifecycle. Same correction
    `kb/service.approve_source` records for the same mistake, and the shape the other
    three readers of this column in this module family already have
    (`declare_consent_provenance`, `_why_not_launchable`,
    `scheduling._why_not_schedulable`) — this was the one that did not.

    The check is also the ONLY thing between the request and an INSERT carrying
    `campaign_id` as a foreign key: admitting a null status would surface as a raw
    integrity error rather than a refusal anyone can read.
    """
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    if status is None:
        raise ProblemError.not_found("Campaign")
    if status not in ("draft", "scheduled"):
        raise ProblemError.business_rule(
            "campaign_not_draft",
            "Contacts can only be added before a campaign is launched.",
        )

    added, malformed, duplicate = 0, 0, 0
    seen: set[str] = set()
    for row in contacts:
        phone = normalize_phone(str(row.get("phone") or ""))
        if phone is None:
            malformed += 1
            continue
        if phone in seen:
            duplicate += 1
            continue
        seen.add(phone)
        # `dedupe_hash` IS NOT WRITTEN, and stopping was the fix rather than finding it a
        # reader. It held `sha256(phone)[:16]`, unsalted — and Indian mobile E.164 is a
        # ~10^9 space anyone enumerates in seconds, so the column was the caller's number
        # in a form that reverses, in a table whose whole erasure story is that the number
        # goes. Nothing has ever read it: this upload dedupes on `seen` within the batch
        # and on `ON CONFLICT (campaign_id, phone_e164)` across batches, both of which use
        # the number itself, and the only other statement naming the column is retention's
        # erasure, which NULLs it. A hash of PII stored for no reader is a DPDP
        # minimisation finding, not a spare index.
        #
        # The column survives this release under hard rule 8 — never DROP in the release
        # that stops writing — so rows already carrying a hash keep being cleared by
        # `_CAMPAIGN_CONTACT_ERASE_SQL`. D-233 names the DROP migration that closes it.
        result = await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, name, "
                "custom, status, attempts, created_at, updated_at) VALUES "
                "(:id, :tid, :cid, :phone, :name, CAST(:custom AS jsonb), 'pending', 0, "
                "now(), now()) ON CONFLICT (campaign_id, phone_e164) DO NOTHING"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": campaign_id,
                "phone": phone,
                "name": str(row.get("name") or "").strip() or None,
                "custom": json.dumps({k: v for k, v in row.items() if k not in ("phone", "name")}),
            },
        )
        if rowcount_of(result):
            added += 1
        else:
            duplicate += 1
    return {"added": added, "malformed": malformed, "duplicate": duplicate}


async def declare_consent_provenance(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    consent_source: str,
    consent_collected_at: datetime,
) -> None:
    """Answer §3's provenance question for a campaign that was created without it.

    This is what stops the migration that added the columns from bricking every draft
    that predates them: a client answers, and the same campaign — its contacts, its
    schedule, its template — launches. Recreating a five-thousand-row list to record a
    date would be a data-loss workaround dressed up as a compliance control.

    BEFORE THE CAMPAIGN STARTS, and that is the whole integrity of the mechanism. If
    provenance could be edited on a `running` campaign, the sequence "dial first, pick a
    lawful-sounding source afterwards" would be available, and the declaration would
    document nothing.

    `scheduled` is inside the window and `draft` is not the only word for it — a client
    who set a Monday start on Friday has dialled nobody, and the gate that reads this
    column runs when the schedule FIRES (`campaigns/scheduling.py` decision 3). The
    statement has always accepted both; the docstring, the route summary and the refusal
    said "draft", which sent a client with a scheduled campaign to cancel a start they
    did not need to cancel (D-189).
    """
    source, collected_at = _validated_provenance(consent_source, consent_collected_at)
    if source is None or collected_at is None:  # pragma: no cover - guarded above
        raise ProblemError(
            kind="validation",
            code="consent_provenance_incomplete",
            title="Incomplete consent provenance",
            detail="Consent provenance needs both a source and the date it was collected.",
        )
    result = await session.execute(
        text(
            "UPDATE campaigns SET consent_source = :source, consent_collected_at = :collected, "
            "updated_at = now() WHERE id = :cid AND tenant_id = :tid "
            "AND status IN ('draft', 'scheduled')"
        ),
        {"source": source, "collected": collected_at, "cid": campaign_id, "tid": tenant_id},
    )
    if rowcount_of(result) == 0:
        # Zero rows is two different facts; a client fixes only one of them.
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
            )
        ).scalar()
        if status is None:
            raise ProblemError.not_found("Campaign")
        raise ProblemError.business_rule(
            "campaign_not_draft",
            "Consent provenance can only be recorded before the campaign starts dialling.",
            remediation=(
                "A draft or a scheduled campaign can still record it; one that has "
                "started cannot, because a source chosen after the calls went out "
                "documents nothing."
            ),
        )


async def record_dlt_registration(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    pe_id: str | None,
    entity_name: str | None,
    status: str,
    tm_link_status: str,
    registered_at: datetime | None = None,
) -> None:
    """Record what the DLT registrar says about this client's Principal Entity.

    An OPERATOR path, deliberately with no client-facing route — the same reason
    `set_template_status` is one. A client who could mark their own PE registration
    `active` would be marking the launch gate green on a registration that does not
    exist, which is precisely the failure the gate is there to catch. It lives beside
    `register_dlt_template` / `set_template_status` because it is the third member of
    the same family (entity, header, template) and they are read by the same gate.

    Upsert on `tenant_id`: a business is one Principal Entity, and re-recording is what
    happens every time we re-verify — hence `verified_at = now()`, which is when WE
    last looked rather than what we last hoped.
    """
    if status not in PE_REGISTRATION_STATUSES:
        raise ProblemError(
            kind="validation",
            code="pe_registration_status_invalid",
            title="Unrecognised registration status",
            detail=(
                f"A PE registration status must be one of: {', '.join(PE_REGISTRATION_STATUSES)}."
            ),
        )
    if tm_link_status not in TM_LINK_STATUSES:
        raise ProblemError(
            kind="validation",
            code="tm_link_status_invalid",
            title="Unrecognised TM link status",
            detail=f"A TM link status must be one of: {', '.join(TM_LINK_STATUSES)}.",
        )
    # An `active` row must carry a registration date (DB CHECK). If the operator did not
    # supply one, the moment we recorded it is the honest answer — decided here rather
    # than in a SQL CASE, which would have to re-read :st and leaves the driver deducing
    # two different types for one parameter.
    registered = registered_at or (datetime.now(UTC) if status == "active" else None)
    await session.execute(
        text(
            "INSERT INTO dlt_registrations (id, tenant_id, pe_id, entity_name, status, "
            "tm_link_status, registered_at, verified_at, created_at, updated_at) VALUES "
            "(:id, :tid, :pe, :ent, :st, :tm, :reg, now(), now(), now()) "
            "ON CONFLICT (tenant_id) DO UPDATE SET pe_id = EXCLUDED.pe_id, "
            "entity_name = EXCLUDED.entity_name, status = EXCLUDED.status, "
            "tm_link_status = EXCLUDED.tm_link_status, "
            "registered_at = EXCLUDED.registered_at, verified_at = now(), updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "pe": pe_id,
            "ent": entity_name,
            "st": status,
            "tm": tm_link_status,
            "reg": registered,
        },
    )


async def launch_blockers(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> list[LaunchBlocker]:
    """Every reason the launch button is disabled, by name (SEC-COMP §3).

    Deliberately exhaustive rather than fail-fast: the client fixes them as a list,
    not one 422 at a time.

    Two of §3's conditions were unenforceable before the migrations b8e4c1d70f92 /
    c5a930e6b1d4 gave them somewhere to live: the client's DLT Principal Entity
    registration (+ its Calevate TM link), and the consent provenance of the contact
    list. Both are asked here, by name. Migration d7f2a3c9b410 added the last piece of
    that first bullet — CALEVATE's own telemarketer registration, one global row rather
    than a per-tenant copy — and it is asked here too, as `tm_registration_missing`.

    The rules that also live in the per-dial gate (`compliance.service.check_dispatch`)
    are asked HERE TOO, under the same names: an agent that may not place calls, a
    tenant at its spend cap, an empty prepaid wallet. Leaving them to dial time
    produces the worst possible outcome — a `running` campaign whose every contact is
    claimed, refused, refunded and rescheduled forever. The client watches a campaign
    that says "running" and never calls anyone, and nothing in the UI says why. The
    per-number rules (DNC, calling hours) stay at dial time only: they are per contact
    and per minute, and a campaign launched at 22:00 to dial tomorrow morning is
    correct, not blocked.

    The DLT-entity, consent-provenance, template and number rules are shared verbatim
    with `dispatch_blockers` — same helpers, same names, same wording — because those
    are the §3 conditions that can stop being true while a campaign RUNS, and a launch
    screen that explained one of them differently from the dispatcher's refusal would
    be two gates disagreeing in front of a client.
    """
    blockers: list[LaunchBlocker] = []
    facts = await _campaign_facts(session, campaign_id)

    if facts.status not in ("draft", "scheduled"):
        blockers.append(LaunchBlocker("status", f"Campaign is {facts.status}, not draft."))
    # `agent_missing` / `agent_inbound_only` are the gate's own names for these two —
    # the dispatcher would refuse every single contact with them.
    if facts.agent_deleted:
        blockers.append(
            LaunchBlocker("agent_missing", "The agent this campaign uses has been deleted.")
        )
    elif facts.agent_status != "live":
        blockers.append(LaunchBlocker("agent_not_live", "The agent must be published first."))
    if facts.agent_direction == "inbound":
        blockers.append(
            LaunchBlocker(
                "agent_inbound_only",
                "This agent only answers calls; it cannot place them.",
            )
        )
    if not facts.disclosure or not str(facts.disclosure).strip():
        blockers.append(LaunchBlocker("disclosure_missing", "The agent has no disclosure line."))

    # WHO may dial, and on what consent (SEC-COMP §3, bullets one and four).
    blockers.extend(await _entity_blockers(session, tenant_id=tenant_id, facts=facts))

    # Tenant-level refusals, asked with the same functions the dial-time gate uses.
    # The ACCOUNT's own lifecycle state first, because it outranks every other tenant
    # refusal: telling a suspended client to top up or to file a document is advice they
    # cannot act on. `check_dispatch` orders it first for the same reason.
    stopped = await account_stopped_blocker(session, tenant_id=tenant_id)
    if stopped is not None:
        blockers.append(LaunchBlocker(*stopped))
    # KYC next, for the reason `check_dispatch` orders it before the money: telling an unverified
    # account to top up when topping up will not let them dial is a worse answer than
    # no answer. Not in `_entity_blockers` despite being an entity question, because
    # that helper is shared with `dispatch_blockers` and `check_dispatch` already asks
    # this per dial — asking twice is how two gates start disagreeing.
    blocked_on_kyc = await kyc_blocker(session, tenant_id=tenant_id)
    if blocked_on_kyc is not None:
        blockers.append(LaunchBlocker(*blocked_on_kyc))
    # R-11's last mitigation: a self-serve account's first campaign waits for a human
    # (BRD §245, FLOWS §2, D-34). Asked here AND in `dispatch_blockers` — see the note
    # in that function for why it is in both and not in `check_dispatch`.
    held = await first_campaign_hold_blocker(session, tenant_id=tenant_id)
    if held is not None:
        blockers.append(LaunchBlocker(*held))
    if await spend_capped(session, tenant_id=tenant_id):
        blockers.append(LaunchBlocker("spend_cap", SPEND_CAP_REASON))
    if await credits_exhausted(session, tenant_id=tenant_id):
        blockers.append(LaunchBlocker("no_credits", NO_CREDITS_REASON))

    # WHAT it may say and from WHERE (SEC-COMP §3, bullet two).
    blockers.extend(_channel_blockers(facts))

    # SEC-COMP §3, third bullet, NATIONAL half. Refused rather than warned about,
    # because the bullet is a legal claim: a promotional campaign dialled without a
    # preference scrub is exactly the traffic that produces the
    # 5-complaints-in-10-days TSP enforcement §1 records, and hard rule 5 forbids
    # softening a gate condition. It cannot be a self-inflicted outage — the DLT scrub
    # facility comes with the same Registered Telemarketer relationship that produces
    # `platform_state.tm_id`, and `tm_registration_missing` above already refuses every
    # campaign until that exists. `transactional` and `service` campaigns are outside
    # it, because a preference does not suppress transactional or service-implicit
    # traffic (`compliance/preference_scrub.py` carries the sources).
    unscrubbed = await national_dnd_blocker(
        session, campaign_id=campaign_id, classification=facts.classification
    )
    if unscrubbed is not None:
        blockers.append(LaunchBlocker(*unscrubbed))

    # Pending AND dialable are different numbers, and the difference is the whole point
    # of this blocker: the scrub launch is about to run marks every DNC-listed contact
    # terminally. Counting raw `pending` rows told the client "you have contacts" and
    # then launched a campaign with `dialable: 0` — a green button over an empty list.
    counts = (
        await session.execute(
            text(
                "SELECT count(*) AS pending, count(*) FILTER (WHERE NOT EXISTS ("
                "  SELECT 1 FROM dnc_list d WHERE d.phone_e164 = cc.phone_e164 "
                "  AND (d.tenant_id = :tid OR d.tenant_id IS NULL)"
                ")) AS dialable "
                "FROM campaign_contacts cc WHERE cc.campaign_id = :cid "
                "AND cc.status = 'pending'"
            ),
            {"cid": campaign_id, "tid": tenant_id},
        )
    ).first()
    pending, dialable = (int(counts[0] or 0), int(counts[1] or 0)) if counts else (0, 0)
    if not pending:
        blockers.append(LaunchBlocker("no_contacts", "The campaign has no dialable contacts."))
    elif not dialable:
        blockers.append(
            LaunchBlocker(
                "all_contacts_dnc",
                "Every number on this list has opted out of calls, so there is nothing "
                "left to dial.",
            )
        )

    return blockers


async def _why_not_launchable(session: AsyncSession, campaign_id: UUID) -> ProblemError:
    """The launch CAS affected no rows. Which of the two facts was it?

    D-65's discriminator, borrowed rather than delegated to (see `launch_campaign`): the
    CAS has already run and written nothing, and this read exists only to name the state
    it found. It cannot reintroduce a read-then-write race because it runs after the
    write and decides nothing but the wording.

    Returns the error rather than raising it, so the caller's `raise` stays visible at
    the call site — the shape `scheduling._why_not_schedulable` already uses.
    """
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    if status is None:
        # Absent, or another tenant's — RLS makes those the same answer on purpose.
        return ProblemError.not_found("Campaign")
    return InvalidStatusTransitionError("campaign", str(status), "running")


async def launch_campaign(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> dict[str, Any]:
    """The gate, then the scrub, then the CAS to `running`.

    Scrub-at-launch marks known-DNC contacts terminally, so the "N contacts will be
    dialled" number the client confirms is true. The per-dial re-check still runs —
    this is UX honesty, not the enforcement.

    **The CAS is NOT `db.transition.transition_status`, and that is a decision rather
    than an oversight (D-65 left this one open).** That helper answers "already in the
    target state" with SUCCESS, which is right for pause/resume and wrong here: launching
    is not idempotent. It scrubs the DNC list, stamps `launched_at`, and both callers
    write a `campaign.launched` row into an append-only ledger and count a start on the
    strength of the return value. A loser that reported success — the tick whose gate read
    happened before the winner committed — would put a SECOND launch in the audit trail
    for one campaign and a phantom start in the dispatch tick's count, which is exactly
    what `tests/campaign_schedule_test.py`'s two-tick test measures.

    What D-65 is actually about is the ERROR NAMING THE STATE IT FOUND, and that part is
    adopted here: `_why_not_launchable` runs the same CAS-first-then-a-write-free-SELECT
    discriminator, so a lost race says `paused`, `cancelled` or `running` instead of the
    place-holder "non-draft" this used to raise, and an id no visible campaign has is a
    404 rather than a 409 asserting a row exists.
    """
    blockers = await launch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)
    if blockers:
        raise ProblemError(
            kind="business_rule",
            code="campaign_launch_blocked",
            title="Campaign cannot launch",
            detail="One or more launch requirements are not met.",
            fields=[{"field": b.rule, "rule": b.rule, "message": b.reason} for b in blockers],
        )

    scrubbed = await session.execute(
        text(
            "UPDATE campaign_contacts SET status = 'dnc_blocked', updated_at = now() "
            "WHERE campaign_id = :cid AND status = 'pending' AND phone_e164 IN ("
            "  SELECT phone_e164 FROM dnc_list WHERE tenant_id = :tid OR tenant_id IS NULL"
            ")"
        ),
        {"cid": campaign_id, "tid": tenant_id},
    )

    # `dnc_scrubbed_at` is stamped in the SAME statement as the transition, not beside
    # it: SEC-COMP §3 promises a scrub timestamp, and a timestamp written by a second
    # UPDATE would survive a CAS that lost its race and claim a scrub for a launch that
    # never happened. It is the moment the scrub above committed, and it records the
    # TENANT-list half only — the national half's timestamp is the provider's, in
    # `preference_scrub_runs.scrubbed_at`, because the two scrubs are run by different
    # parties at different times and one column could only ever be honest about one.
    result = await session.execute(
        text(
            "UPDATE campaigns SET status = 'running', launched_at = now(), "
            "dnc_scrubbed_at = now(), updated_at = now() "
            "WHERE id = :cid AND status IN ('draft', 'scheduled')"
        ),
        {"cid": campaign_id},
    )
    if rowcount_of(result) == 0:
        raise await _why_not_launchable(session, campaign_id)

    dialable = (
        await session.execute(
            text(
                "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                "AND status = 'pending'"
            ),
            {"cid": campaign_id},
        )
    ).scalar()
    log.info(
        "campaign_launched",
        extra={
            "campaign_id": str(campaign_id),
            "dialable": int(dialable or 0),
            "dnc_scrubbed": rowcount_of(scrubbed),
        },
    )
    return {
        "status": "running",
        "dialable": int(dialable or 0),
        "dnc_scrubbed": rowcount_of(scrubbed),
    }


async def set_campaign_status(
    session: AsyncSession, *, campaign_id: UUID, to_status: str, from_statuses: tuple[str, ...]
) -> bool:
    """pause/resume/cancel — all the same CAS shape. True when THIS call moved the row.

    The three answers are `db.transition.transition_status`'s, not this function's:
    already-in-`to_status` is a success (False), a different state is a 409 naming the
    state actually found, and an id no visible campaign has is a 404. This used to
    raise `INVALID_STATUS_TRANSITION` for all three at once, so pausing a campaign that
    was already paused — the second click, or the retry of a request whose response was
    lost — was reported as a conflict, and a campaign id from another tenant was
    reported as one too.

    **No compliance gate here, on the resume path or any other, and that is deliberate**
    (see `dispatch_blockers`): a campaign can sit paused for a week, so a gate at THIS
    moment would prove nothing about the moment it dials. The dial-time check is the
    enforcement — `tests/campaign_dispatch_audit_test.py` pins it. This change moves
    only which of the three answers each caller gets; it adds and removes no gate.
    """
    return await transition_status(
        session,
        table="campaigns",
        entity="Campaign",
        row_id=campaign_id,
        to_status=to_status,
        from_statuses=from_statuses,
    )


async def register_dlt_template(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    classification: str,
    body: str,
    dlt_ref: str | None,
) -> UUID:
    """Record the voice template the client registered with their DLT registrar.

    Created `submitted`, never `approved`: approval happens at the registrar, and a
    template we mark approved because we typed it in is how a campaign launches under a
    template the operator never actually registered. `set_template_status` is the
    separate, audited step that records what the registrar decided.
    """
    template_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, dlt_ref, "
            "status, created_at, updated_at) VALUES (:id, :tid, 'voice', :cls, :body, :ref, "
            "'submitted', now(), now())"
        ),
        {
            "id": template_id,
            "tid": tenant_id,
            "cls": classification,
            "body": body,
            "ref": dlt_ref,
        },
    )
    return template_id


async def set_template_status(
    session: AsyncSession, *, template_id: UUID, status: str, dlt_ref: str | None = None
) -> None:
    """What the registrar decided. `approved` is what unlocks the launch gate, so this
    is an audited admin action, not a field the client can edit."""
    result = await session.execute(
        text(
            "UPDATE dlt_templates SET status = :st, "
            "dlt_ref = COALESCE(:ref, dlt_ref), updated_at = now() WHERE id = :id"
        ),
        {"st": status, "ref": dlt_ref, "id": template_id},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("DLT template")


async def list_campaigns(session: AsyncSession, *, limit: int = 100) -> list[dict[str, Any]]:
    """Newest first, with the two counts the list actually needs — and the one blocker
    the list cannot otherwise see.

    Counting in the query rather than per row: a client with thirty campaigns should
    cost one round trip, and `connected` is the only per-status number worth showing
    before you open one.

    `consent_provenance_blocker` is that round trip's other job. Without it the campaign
    screen knew a row was a `draft` and nothing about its consent, so it had two bad
    options: warn about EVERY draft ("some of these may be blocked"), or run the full
    launch gate once per row to find out. It is DERIVED, and it is named rather than
    boolean, for three reasons:

    - the raw `consent_source` invites `if (consent_source) ok` — which renders a
      purchased list, the one answer the gate refuses outright, as answered and fine;
    - a boolean collapses two states with DIFFERENT remedies into one. "Nobody has said
      yet" is answerable by the client in the provenance form; "this list was bought" is
      a policy refusal no form can clear. A list that shows the same badge for both
      sends half its clicks to a form that cannot help;
    - the values are the launch gate's OWN rule names, so the list links to the same
      wording `/launch-check` renders. A third vocabulary for the same fact is how two
      screens start disagreeing in front of a client.

    NULL for anything past `draft`/`scheduled`, and that is not a shortcut: provenance
    is answerable only while a campaign is a draft (`declare_consent_provenance`), so
    flagging a running campaign that predates the columns would put a to-do on the list
    with no way to do it.
    """
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.name, c.classification, c.status, c.launched_at, c.created_at, "
                "  count(cc.id) AS contacts, "
                "  count(cc.id) FILTER (WHERE cc.status = 'connected') AS connected, "
                "  CASE WHEN c.status IN ('draft', 'scheduled') THEN CASE "
                "    WHEN c.consent_source IS NULL THEN 'consent_provenance_missing' "
                "    WHEN c.consent_source = ANY(:refused) THEN 'consent_source_refused' "
                "  END END AS consent_provenance_blocker "
                "FROM campaigns c LEFT JOIN campaign_contacts cc ON cc.campaign_id = c.id "
                "GROUP BY c.id ORDER BY c.created_at DESC LIMIT :limit"
            ),
            {"refused": list(REFUSED_CONSENT_SOURCES), "limit": limit},
        )
    ).all()
    return [
        {
            "id": r[0],
            "name": r[1],
            "classification": r[2],
            "status": r[3],
            "launched_at": r[4],
            "created_at": r[5],
            "contacts": int(r[6] or 0),
            "connected": int(r[7] or 0),
            "consent_provenance_blocker": r[8],
        }
        for r in rows
    ]


async def campaign_progress(session: AsyncSession, campaign_id: UUID) -> dict[str, Any]:
    """Live progress, plus the pending start if there is one.

    The schedule fields are read from `campaigns.schedule` here rather than through a
    second endpoint, because a screen that shows "scheduled" without saying WHEN — or
    without saying that the last attempt to start was refused — is a state, which §52
    says a screen may not stop at. The two one-time fields are extracted in SQL by key
    rather than handing the whole JSONB to the response model, because a response model
    is an output WHITELIST (BACKEND-PATTERNS §1).

    A REPEAT is read whatever the status, and that asymmetry is deliberate: a one-time
    start is spent the moment it fires (hence the `status = 'scheduled'` guard, so a
    running campaign does not advertise a start that already happened), while a repeat
    outlives every occurrence — a campaign dialling right now still has a next Tuesday,
    and the screen has to be able to say so and offer the stop button.
    `scheduling.describe_recurrence` does the reading, so the JSON shape keeps one owner.
    """
    # Imported here, not at module scope: `scheduling` imports `launch_campaign` from
    # this module (the gate lives on one side of that seam and the column's meaning on
    # the other), so a top-level import would close the cycle.
    from apps.api.campaigns.scheduling import describe_recurrence

    rows = (
        await session.execute(
            text(
                "SELECT status, count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                "GROUP BY status"
            ),
            {"cid": campaign_id},
        )
    ).all()
    counts = {str(r[0]): int(r[1]) for r in rows}
    campaign = (
        await session.execute(
            text(
                # EVERY column is `c.`-qualified since the join arrived, and that is not
                # tidiness: `phone_numbers` has a `status` of its own, so a bare `status`
                # here would be ambiguous — and had it not been, an unqualified name would
                # be one schema change away from silently answering about the number.
                "SELECT c.status, c.launched_at, c.concurrency, "
                # Only while the campaign is still WAITING. `launch_campaign` leaves the
                # column populated on the row it starts (it is the record of why that
                # launch happened, and `_expire` is the only thing that clears it), so an
                # unconditional read would have a running campaign still advertising a
                # start time that has already been honoured.
                "  CASE WHEN c.status = 'scheduled' THEN c.schedule->>'start_at' END, "
                "  CASE WHEN c.status = 'scheduled' THEN c.schedule->'last_blocked'->'rules' END, "
                "  c.schedule, c.dnc_scrubbed_at, "
                # The two facts a launch confirmation has to state and could not read
                # back (P7.4). Both were WRITE-ONLY until now: `calling_hours` and the
                # number were set in the create form, held as local state, and never
                # returned by any endpoint — so the panel that asks a client to authorise
                # ringing N strangers could not tell them WHEN it would ring or WHICH
                # number would appear on the handset. Both are properties of the
                # irreversible act being confirmed.
                "  c.calling_hours, p.e164 "
                # LEFT: `number_id` is nullable and `ON DELETE SET NULL`, so a campaign
                # whose number was released still has to render. NULL means "the platform
                # picks at dial time", which is what the screen must say rather than
                # showing a blank where a number belongs.
                "FROM campaigns c LEFT JOIN phone_numbers p "
                "  ON p.id = c.number_id AND p.tenant_id = c.tenant_id "
                "WHERE c.id = :cid"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if campaign is None:
        raise ProblemError.not_found("Campaign")
    blocked_rules = campaign[4]
    # BOTH scrubs, side by side, and that pairing is the point. SEC-COMP §3 certifies a
    # list as scrubbed against the national DND AND the tenant list; until this pair
    # existed, "scrubbed against both" and "scrubbed against one" rendered identically
    # on every screen an operator or a client could reach. `national_dnd` is None when
    # no run has ever been recorded, which is the honest reading of an absent artefact.
    scrub = await read_current_scrub(session, campaign_id=campaign_id)
    return {
        "status": campaign[0],
        "launched_at": campaign[1],
        "concurrency": campaign[2],
        "contacts": counts,
        "total": sum(counts.values()),
        "scheduled_start_at": campaign[3],
        "schedule_blocked_rules": [str(rule) for rule in blocked_rules] if blocked_rules else [],
        "recurrence": describe_recurrence(campaign[5]),
        "dnc_scrubbed_at": campaign[6],
        "national_dnd_scrub": (
            {
                "provider": scrub.provider,
                "scrub_ref": scrub.scrub_ref,
                "scrubbed_at": scrub.scrubbed_at,
                "expires_at": scrub.expires_at,
                "suppressed_count": scrub.suppressed_count,
                "is_current": scrub.is_current,
            }
            if scrub.recorded
            else None
        ),
        # THE WINDOW, and it is the campaign's own NARROWING or nothing — the platform's
        # 09:00-21:00 IST bound is not restated here. `campaign_window_open` treats a NULL
        # `calling_hours` as "the platform window applies", and a reader that saw the
        # platform hours echoed into this field could not tell a campaign that chose them
        # from one that chose nothing. The screen states the platform bound itself,
        # because it is true of every campaign.
        #
        # Normalised to the two keys `_validated_window` writes rather than handed over
        # whole: a response model is an output WHITELIST (BACKEND-PATTERNS §1), and this
        # column is JSONB that a future field would ride out of on its own.
        "calling_hours": (
            {"start": str(campaign[7]["start"]), "end": str(campaign[7]["end"])}
            if isinstance(campaign[7], dict) and {"start", "end"} <= campaign[7].keys()
            else None
        ),
        # The number that will appear on the handset. None when the campaign has none —
        # which the screen must SAY rather than leave blank, because "the platform picks
        # one at dial time" and "we could not read it" are different facts to a client
        # deciding whether to authorise the calls.
        "number_e164": campaign[8],
    }


__all__ = [
    "CAMPAIGN_STOPPED_RULE",
    "CAMPAIGN_WINDOW_CLOSED_RULE",
    "DEFAULT_RETRY_POLICY",
    "NO_PROVENANCE_REASON",
    "PURCHASED_LIST_REASON",
    "SERIES_FOR_CLASSIFICATION",
    "LaunchBlocker",
    "add_contacts",
    "campaign_dialable_now",
    "campaign_progress",
    "campaign_window_open",
    "create_campaign",
    "declare_consent_provenance",
    "dispatch_blockers",
    "launch_blockers",
    "launch_campaign",
    "list_campaigns",
    "record_dlt_registration",
    "register_dlt_template",
    "set_campaign_status",
    "set_template_status",
]
