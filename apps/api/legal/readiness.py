"""Everything standing between one organisation and operating, in one answer.

WHY THIS EXISTS. Every condition below already had a gate. None of them had a SCREEN:
`launch_blockers` renders them the moment somebody presses Launch, `check_dispatch`
renders one of them on a disabled button, and a client who has not yet built a campaign
had no way to find out that their DLT entity was never linked or that their first campaign
is waiting on a human. The worst moment to learn what a launch needs is while pressing
Launch.

THE SET IS THE ORGANISATION-LEVEL ONE, DELIBERATELY, AND THE LINE IS NOT ARBITRARY.
`launch_blockers` composes two families: facts about the TENANT (its account status, its
verification, its registrations, its money, its agreements) and facts about ONE CAMPAIGN
(its template, its number, its contact list, its agent). Only the first family belongs
here — a campaign's own template is answered on the campaign screen, where the campaign
is. Rendering `dlt_template_missing` on an account screen would name a to-do item that
belongs to a thing this page cannot see.

The one exception is the national preference scrub, which IS per campaign, and it is here
as a COUNT (`campaigns_awaiting_scrub`) because the founder asked for it and because the
client's action does not vary by campaign: they cannot scrub anything — it is ours to run
— so "two of your campaigns are waiting on us" is the whole of the actionable fact.

EVERY REASON COMES FROM THE PREDICATE THAT ALREADY OWNS IT. This module composes
`account_stopped_blocker`, `kyc_blocker`, `outbound_entity_blockers`,
`first_campaign_hold_blocker`, `spend_capped`, `credits_exhausted`,
`legal.service.agreements_blocker` and the platform halt — the same functions the gates
call, returning the same `(rule, reason)` pairs. Nothing here re-derives a verdict, for the
reason `lib/api/aiQuota.ts` states one level up: a second implementation of a compliance
answer is two answers that disagree on the day it matters.

WHAT THIS MODULE ADDS is the two things the pairs never carried — a TITLE naming the
condition, and WHOSE MOVE it is. `ROW_COPY` below is that layer, keyed by rule name, and
`tests/legal_agreements_test.py` asserts every key is a rule the code really emits (it
reads `scripts.check_docs_drift.emitted_rule_names`, the same vocabulary SEC-COMP §3 is
checked against) so a rename cannot leave a screen explaining a rule that no longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.preference_scrub import campaigns_awaiting_scrub
from apps.api.compliance.registration import outbound_entity_blockers
from apps.api.compliance.service import (
    NO_CREDITS_REASON,
    SPEND_CAP_REASON,
    account_stopped_blocker,
    credits_exhausted,
    first_campaign_hold_blocker,
    kyc_blocker,
    spend_capped,
)
from apps.api.core.loadshed import get_platform_status
from apps.api.legal import service as legal_service

#: Whose move it is. Two values and no third: an item is either something this client can
#: act on or something Calevate must do.
#:
#: THE DLT SPLIT IS THE CASE TO GET RIGHT, and this comment used to get it backwards. It
#: claimed "waiting on a registrar is still OURS — we hold the DLT login", which is false
#: and disagreed with the table three screens below it, where `pe_registration_missing` is
#: `client`. LEGAL-OPS-PLAYBOOK §10.4 (docs/legal/LEGAL-OPS-PLAYBOOK.md:351-362, read 26
#: Aug 2026) states the real division: the CLIENT signs up as the Principal Entity with
#: their own PAN/Udyam/GST, registers their own headers and templates, and pastes OUR
#: TM-ID into their own PE-TM chain; we hold our TM login and accept the chain from it. So
#: their PE registration and the chain they authorise are theirs, and our telemarketer
#: registration and the preference scrub we run from our login are ours. Neither party can
#: do the other's half, which is exactly why the column exists.
Actor = Literal["client", "calevate"]


@dataclass(frozen=True, slots=True)
class ReadinessRow:
    """One thing standing in the way, in the three parts a client needs."""

    rule: str
    #: What the condition IS, as a heading. Never a restatement of the reason.
    title: str
    #: WHY it is in the way — the gate's own sentence, verbatim.
    reason: str
    #: WHOSE move.
    actor: Actor
    #: WHAT clears it. The client's next action, or what we are doing about it.
    next_step: str


@dataclass(frozen=True, slots=True)
class _Copy:
    title: str
    actor: Actor
    next_step: str


#: `rule -> (title, whose move, what clears it)`.
#:
#: Only the ORGANISATION-level rules are here; the campaign-level ones are the campaign
#: screen's. A rule this map does not know still renders — see `_row` — because a screen
#: that silently dropped a live blocker would tell a client they are ready when they are
#: not.
ROW_COPY: dict[str, _Copy] = {
    legal_service.AGREEMENTS_RULE: _Copy(
        title="Agreements not accepted",
        actor="client",
        next_step=(
            "The account owner reads each agreement and accepts it on this screen. "
            "Nobody else — not another admin here, not Calevate — can accept for them."
        ),
    ),
    "big_red_switch": _Copy(
        title="Outbound calling is halted platform-wide",
        actor="calevate",
        next_step=(
            "Nothing to do at your end. Our operations team has stopped all outgoing "
            "calls across the platform and will release them. Calls coming in are "
            "unaffected."
        ),
    ),
    "account_closed": _Copy(
        title="This account is closed",
        actor="calevate",
        next_step="Talk to us before doing anything else — nothing on this screen will help.",
    ),
    "account_missing": _Copy(
        title="We could not confirm this account",
        actor="calevate",
        next_step="Contact support. Outgoing calls stay stopped until we can read the account.",
    ),
    "kyc_missing": _Copy(
        title="Business not verified",
        actor="client",
        next_step=(
            "Send us your business registration number and we will record it for you. "
            "There is nothing to upload — it is a public registration number, never a "
            "document. The Verification screen then shows what we hold."
        ),
    ),
    "kyc_not_verified": _Copy(
        title="Business verification not cleared",
        actor="calevate",
        next_step=(
            "The Verification screen says which state it is in and whether we owe you a "
            "review or you owe us a correction."
        ),
    ),
    "tm_registration_missing": _Copy(
        title="Calevate's telemarketer registration",
        actor="calevate",
        next_step=(
            "Nothing to do at your end. This is our own registration with an access "
            "provider, and no client can place campaign calls until it is live."
        ),
    ),
    "pe_registration_missing": _Copy(
        title="Your DLT registration",
        actor="client",
        next_step=(
            "Register your business as a Principal Entity on an access provider's DLT "
            "platform, then send us the registration id and we will record it. The "
            "Verification screen shows it once it is on file."
        ),
    ),
    "pe_registration_not_active": _Copy(
        title="Your DLT registration is not active",
        actor="client",
        next_step=(
            "The Verification screen shows what the registrar says. A suspended or "
            "rejected registration is settled with the registrar, not with us."
        ),
    ),
    "tm_link_not_active": _Copy(
        title="Calevate is not authorised on your DLT account",
        actor="client",
        next_step=(
            "On your DLT platform, authorise Calevate as your telemarketer. Until that "
            "link is active nobody may dial on your behalf, whatever else is in order."
        ),
    ),
    "first_campaign_review_pending": _Copy(
        title="Your first campaign is with us for review",
        actor="calevate",
        next_step=(
            "Nothing to do at your end. A person here checks the first campaign of every "
            "self-serve account before it dials."
        ),
    ),
    "first_campaign_review_rejected": _Copy(
        title="Your first campaign was not released",
        actor="client",
        next_step="The reason is beside this item. Fix what it names and ask us to look again.",
    ),
    "spend_cap": _Copy(
        title="Monthly spending cap reached",
        actor="client",
        next_step="Raise the cap on the Spend screen, or wait for the month to roll over.",
    ),
    "no_credits": _Copy(
        title="No calling credit left",
        actor="client",
        next_step="Top up on the Usage screen. Calls resume as soon as the payment clears.",
    ),
    "national_dnd_scrub_missing": _Copy(
        title="Campaigns waiting on a DND scrub",
        actor="calevate",
        next_step=(
            "Nothing to do at your end. Before a promotional campaign dials, we scrub its "
            "list against the national customer preference register on an access "
            "provider's DLT platform, and that scrub is only good until the end of the "
            "day it was run."
        ),
    ),
}

#: What a rule this module has never heard of renders as. It is deliberately OURS to
#: explain: if the platform cannot say whose move a refusal is, telling the client to go
#: and do something is worse than admitting we owe them the answer.
_UNKNOWN = _Copy(
    title="Something else is blocking outgoing calls",
    actor="calevate",
    next_step="Contact support with this screen open — we will say what this one is.",
)


def _row(rule: str, reason: str) -> ReadinessRow:
    copy = ROW_COPY.get(rule, _UNKNOWN)
    return ReadinessRow(
        rule=rule, title=copy.title, reason=reason, actor=copy.actor, next_step=copy.next_step
    )


async def readiness_rows(session: AsyncSession, *, tenant_id: UUID) -> list[ReadinessRow]:
    """Every organisation-level condition currently stopping this client's outbound.

    ORDERED THE WAY THE GATES ORDER THEIR REFUSALS, and for their reason rather than for
    tidiness: the platform halt and the account's own lifecycle outrank everything —
    telling a suspended client to top up is advice they cannot act on — then who we are
    allowed to dial as, then the agreements, then the money, then the per-campaign
    paperwork. `check_dispatch` and `launch_blockers` both compose in this sequence.

    Exhaustive rather than fail-fast, like `launch_blockers`: a client fixes a list, not
    one 422 at a time.
    """
    rows: list[ReadinessRow] = []

    platform = await get_platform_status()
    if platform.outbound_halted:
        rows.append(
            _row(
                "big_red_switch",
                "Outbound calling is halted platform-wide by the operations team.",
            )
        )

    stopped = await account_stopped_blocker(session, tenant_id=tenant_id)
    if stopped is not None:
        rows.append(_row(*stopped))

    blocked_on_kyc = await kyc_blocker(session, tenant_id=tenant_id)
    if blocked_on_kyc is not None:
        rows.append(_row(*blocked_on_kyc))

    rows.extend(
        _row(*pair) for pair in await outbound_entity_blockers(session, tenant_id=tenant_id)
    )

    agreements = await legal_service.agreements_blocker(session, tenant_id=tenant_id)
    if agreements is not None:
        rows.append(_row(*agreements))

    held = await first_campaign_hold_blocker(session, tenant_id=tenant_id)
    if held is not None:
        rows.append(_row(*held))

    if await spend_capped(session, tenant_id=tenant_id):
        rows.append(_row("spend_cap", SPEND_CAP_REASON))
    if await credits_exhausted(session, tenant_id=tenant_id):
        rows.append(_row("no_credits", NO_CREDITS_REASON))

    waiting = await campaigns_awaiting_scrub(session, tenant_id=tenant_id)
    if waiting:
        rows.append(
            _row(
                "national_dnd_scrub_missing",
                f"{waiting} promotional campaign{'s' if waiting != 1 else ''} "
                f"{'have' if waiting != 1 else 'has'} no current scrub against the "
                "national customer preference register.",
            )
        )

    return rows


__all__ = ["ROW_COPY", "Actor", "ReadinessRow", "readiness_rows"]
