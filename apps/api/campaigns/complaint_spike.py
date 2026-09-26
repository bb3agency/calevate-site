"""FLOWS §5's mid-campaign complaint-spike safety: pause the dialling, page a human.

WHAT WAS WRONG. FLOWS §5 has promised "complaint-spike alarm (pause + notify)" since the
campaign lifecycle was written, OPERATIONS §4 lists "complaint-spike on campaign" among
the things that trigger an alert, D-149's dispatcher comment names the auto-pause as one
of the two mid-campaign safeties the per-dial re-read exists to honour — and nothing
anywhere measured a complaint. A campaign could dial a bought list all afternoon while
every third person asked never to be called again, and the only trace was rows in
`consent_ledger` nobody was reading and a `dnc_list` that grew.

That is not a monitoring gap. Under TCCCPR the fifth unique complaint against a sender
inside ten days obliges the access provider to SUSPEND that sender's outgoing service and
open an investigation, and the sender is the CLIENT's Principal Entity, not us
(SECURITY-COMPLIANCE §1). The alarm this module raises is the last cheap moment before
someone else takes the decision away from the client.

WHAT WE CAN ACTUALLY COUNT. Not "complaints" — a TRAI complaint is filed with an access
provider and arrives, if it ever does, as a letter. What we hold is the leading
indicator, and it is a strictly larger population: every caller on this campaign who told
the agent to stop, recorded as a `consent_ledger` withdrawal against the call
(`compliance/optout.py`, both detectors). Anybody who registers a complaint said this
first. Counting the superset is what makes the alarm early rather than posthumous, and
the runbook says so plainly so nobody reads "5 opt-outs" as "5 complaints".

THE THREE NUMBERS, EACH ARGUED
-------------------------------
* **`MIN_OPTOUTS = 3`** is TRAI's own number, used deliberately as a CEILING rather than
  a target. The TCCCPR Third Amendment (18 Sep 2026) lets three unique complaints in ten
  days, combined with an operator AI flag on the CLI, trigger action against the sender;
  it was five under the Second Amendment (in force 12 Feb 2025,
  https://www.pib.gov.in/PressReleasePage.aspx?PRID=2102413). The Third Amendment figure
  is REPORTED, an access provider's summary of TRAI press release No. 119/2026
  (`docs/evidence/trai-tcccpr-third-amendment-2026-09-18.md` row 6). We cannot see the
  AI flag, so the count is matched and the flag is assumed.
* **`RATE = 0.10`** is what keeps the count honest on a big campaign, where five opt-outs
  in a thousand conversations is a good list rather than a bad one. The reference point:
  a measured 10,794-call cold outbound study reports 4.1% of calls ending in a
  do-not-call request (https://ccdocs.com/outbound-call-center/). Our clients dial
  CONSENTED lists — existing customers, inbound enquiries, opt-ins; the gate refuses a
  purchased one — so their floor should be well under that number, and one in ten is
  roughly two and a half times worse than cold calling strangers. A campaign there is not
  having a bad hour; its list or its script is wrong.
* **`WINDOW_HOURS = 24`** is one calling day. The platform window is 09:00-21:00 IST, so
  a 24-hour window covers a full day of dialling and no more: a spike stops TODAY, and
  tomorrow starts from a clean measurement. The alternative — measuring since launch —
  would mean a campaign that had one bad morning could never be resumed, and the
  alternative in the other direction (an hour) is short enough that a slow campaign never
  accumulates five of anything.

PER CAMPAIGN AND PER SENDER, BOTH. The regulator now aggregates flags and complaints per
SENDER, the client, across every CLI it uses, so a client running five campaigns that each
lose two callers a day is past the trigger while no single campaign is. The second
measurement is therefore the whole account's outbound calls over `SENDER_WINDOW_DAYS`, the
regulator's own window, and when it trips every running campaign of that client pauses on
its own next tick, because each asks the same question and gets the same answer. It
counts all outbound calls, not only campaigns, since a complaint about an instant lead
call is a complaint against the same sender. It clears only as the ten days roll, which is
as long as the exposure lasts.

BOTH CONDITIONS, NOT EITHER. Count alone pages a large healthy campaign; rate alone pages
a campaign that dialled four people and lost one. The pair is the standard shape for
alerting on a ratio — a significance floor under a rate — and it is the same shape
`ai_quota` uses for the platform AI brake.

RESUMING IS ALLOWED AND WILL RE-PAUSE while the window still holds the spike, and that is
the intended behaviour rather than a rough edge: nothing about a campaign changes in the
ten minutes after somebody presses resume, so a resume that dialled on would be the pause
not meaning anything. What clears it is time (the window rolls) or a new campaign built
on a scrubbed list. The runbook says this in the operator's words.

WHY IT PAUSES RATHER THAN ONLY ALERTING. FLOWS §5 says "pause + notify" and the order is
the point: an alert that arrives while the campaign keeps dialling is an alert that
watches the damage. The pause is a CAS from `running`, so it cannot resurrect a cancelled
or completed campaign, and it is written to `audit_log` like the button in the client's
own screen — "who stopped the calls, and when" must have one answer whether the answer is
a person or us.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.service import set_campaign_status
from apps.api.compliance.audit import write_audit
from apps.api.compliance.optout import OPTOUT_PURPOSE
from apps.api.core.alerting import alert, record_compliance_block
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: See the module docstring: TRAI's complaint trigger, used as a ceiling.
MIN_OPTOUTS = 3
#: Opt-outs per connected call. 0.10 against a 4.1% cold-calling benchmark.
RATE = 0.10
#: One calling day, for one campaign.
WINDOW_HOURS = 24
#: The regulator's window, for the sender as a whole.
SENDER_WINDOW_DAYS = 10

#: The blocker name this refusal is counted under, so `compliance_blocks{rule=...}` can
#: answer "why did this campaign stop" the way `runbooks/campaign-stall.md` §8 promises
#: it can. Not a member of `compliance.service.PERSON_LEVEL_REFUSALS`: this is a fact
#: about a CAMPAIGN, not about a person, and it must never settle a contact terminally.
BLOCK_RULE = "complaint_spike"

#: Connected calls, and how many of them ended in a recorded opt-out. `status =
#: 'completed'` is the denominator because only somebody who had a conversation can ask
#: to be left alone — counting unanswered dials would dilute the rate with the one
#: outcome that carries no opinion. `coalesce(started_at, created_at)` because a call
#: repaired by the reconciliation poller may have no `started_at` and still belongs to
#: the window it was dialled in.
#:
#: RUNS UNDER RLS in the caller's `tenant_session`, so both tables are already scoped to
#: this tenant and the query carries no `tenant_id` predicate of its own (hard rule 1:
#: the policy is the isolation, never a WHERE clause somebody has to remember).
_WINDOW_SQL = text(
    "SELECT count(*) AS connected, count(*) FILTER (WHERE EXISTS ("
    "  SELECT 1 FROM consent_ledger cl WHERE cl.call_id = c.id "
    "  AND cl.status = 'withdrawn' AND cl.purpose = :purpose)) AS optouts "
    "FROM calls c WHERE c.campaign_id = :cid AND c.status = 'completed' "
    "AND coalesce(c.started_at, c.created_at) >= now() - make_interval(hours => :hours)"
)

#: The same measurement over the whole account's OUTBOUND calls. Under RLS like the one
#: above, so "the whole account" is this tenant and nobody else.
_SENDER_WINDOW_SQL = text(
    "SELECT count(*) AS connected, count(*) FILTER (WHERE EXISTS ("
    "  SELECT 1 FROM consent_ledger cl WHERE cl.call_id = c.id "
    "  AND cl.status = 'withdrawn' AND cl.purpose = :purpose)) AS optouts "
    "FROM calls c WHERE c.direction = 'outbound' AND c.status = 'completed' "
    "AND coalesce(c.started_at, c.created_at) >= now() - make_interval(days => :days)"
)

SpikeScope = Literal["campaign", "sender"]


@dataclass(frozen=True, slots=True)
class ComplaintSpike:
    """What the window found. `paused` is False when the CAS lost — another actor (the
    client's own pause button, a cancel) got there first, which is not a failure."""

    optouts: int
    connected: int
    paused: bool
    scope: SpikeScope = "campaign"


async def check_complaint_spike(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> ComplaintSpike | None:
    """None when the campaign is fine. Otherwise: paused, audited, and alerted.

    Called from the dispatch tick BEFORE contacts are claimed, in the same transaction,
    for the reason the standing compliance gate is checked there — a condition that
    blocks every contact of this campaign identically costs no attempts and needs no
    compensating refund if it is asked before the claim rather than after it.
    """
    campaign_row = (
        await session.execute(
            _WINDOW_SQL,
            {"cid": campaign_id, "purpose": OPTOUT_PURPOSE, "hours": WINDOW_HOURS},
        )
    ).one()
    scope: SpikeScope = "campaign"
    connected, optouts = int(campaign_row[0]), int(campaign_row[1])
    if not _spiked(optouts=optouts, connected=connected):
        sender_row = (
            await session.execute(
                _SENDER_WINDOW_SQL, {"purpose": OPTOUT_PURPOSE, "days": SENDER_WINDOW_DAYS}
            )
        ).one()
        scope = "sender"
        connected, optouts = int(sender_row[0]), int(sender_row[1])
        if not _spiked(optouts=optouts, connected=connected):
            return None
    window = f"{WINDOW_HOURS}h" if scope == "campaign" else f"{SENDER_WINDOW_DAYS}d"

    record_compliance_block(rule=BLOCK_RULE)
    try:
        paused = await set_campaign_status(
            session,
            campaign_id=campaign_id,
            to_status="paused",
            from_statuses=("running",),
        )
    except ProblemError:
        # The campaign moved out of `running` between the tick's read and this CAS —
        # cancelled, completed, or paused by the client a second ago. Nothing to stop,
        # and the alert below still fires: the operator needs to know this list produced
        # a spike whoever stopped it.
        paused = False

    if paused:
        await write_audit(
            session,
            action="campaign.paused",
            actor_type="system",
            tenant_id=tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            # The counts go to the LOG stream, not to a column: `write_audit` hashes the
            # row and `audit_log` carries no `summary`, so a field the row does not hold
            # would make the tamper-evident chain unverifiable.
            summary={
                "reason": BLOCK_RULE,
                "scope": scope,
                "optouts": optouts,
                "connected": connected,
                "window": window,
            },
        )

    # Ids and counts only — never a number, never what anybody said (hard rule 6). The
    # detail is a sentence we authored; every variable in it is an integer of ours.
    alert(
        "CORE_LOGIC",
        "campaign_complaint_spike",
        detail=(
            f"{optouts} of {connected} connected "
            + (
                "calls on this campaign"
                if scope == "campaign"
                else "outbound calls on this account"
            )
            + f" ended in an opt-out in the last {window} (threshold: {MIN_OPTOUTS} and "
            f"{RATE:.0%}); " + ("campaign paused" if paused else "campaign was already stopped")
        ),
        tenant_id=str(tenant_id),
        campaign_id=str(campaign_id),
    )
    log.warning(
        "campaign_complaint_spike",
        extra={
            "campaign_id": str(campaign_id),
            "optouts": optouts,
            "connected": connected,
            "paused": paused,
            "scope": scope,
        },
    )
    return ComplaintSpike(optouts=optouts, connected=connected, paused=paused, scope=scope)


def _spiked(*, optouts: int, connected: int) -> bool:
    """Both conditions: enough opt-outs to matter, and too many for the calls they came from.

    `connected` cannot be zero when `optouts` is positive, since an opt-out is recorded
    against a completed call; the guard is kept so a future detector attaching one to an
    uncompleted call cannot divide by zero in the check meant to stop dialling.
    """
    if optouts < MIN_OPTOUTS or connected <= 0:
        return False
    return optouts / connected >= RATE


__all__ = [
    "BLOCK_RULE",
    "MIN_OPTOUTS",
    "RATE",
    "SENDER_WINDOW_DAYS",
    "WINDOW_HOURS",
    "ComplaintSpike",
    "SpikeScope",
    "check_complaint_spike",
]
