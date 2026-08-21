"""The compliance gate — the ONE function every dispatch path must call.

Hard rule 5, stated as code: campaign launch, the D-21 "call this lead" button and the
instant-lead-callback webhook all place outbound calls, so they all pass through here.
There is **no bypass flag, not even for testing** — staging fixtures exist for that. A
`for_testing=True` parameter on this function would be the single most likely cause of
a real TRAI violation, because the one place it gets left on is production.

Checks, in the order that fails cheapest-first:

1. **Big red switch** — a global outbound halt beats every other consideration.
1b. **Account lifecycle** — a `suspended` or `churned` organization dials nothing. The
   status was written by nothing until the admin lifecycle route landed, so this was
   the check that made suspending a client stop their campaigns rather than recolour a
   row (`account_stopped_blocker`). Inbound is unaffected, like everything here.
2. **Spend caps** — a capped tenant's outbound is refused (TRD §9); inbound is
   unaffected, which is why this gate is outbound-only.
2b. **Prepaid credits** — a self-serve tenant with an empty wallet cannot dial (D-34).
   Checked for `self_serve`/`trial` only: a managed client is invoiced against a
   retainer, and blocking their calls over a credit balance they never bought would be
   an outage caused by a concept that does not apply to them.
2c. **Subscriber KYC** — a self-serve tenant whose business identity we have not
   verified cannot dial (R-11's last mitigation; SURFACES §2b, FLOWS §2). Also
   `self_serve`/`trial` only, and `apps/api/compliance/kyc.py` argues at length why
   that is the right line and where the residual risk is: a managed tenant's identity
   was verified out of band before we bought their number, and is already gated at
   dial time by `pe_registration_*`. Provisioning a NEW number is gated for every
   tier — that gate is in `campaigns/provisioning.py` and has no tier test at all.
3. **Calling hours** — the PLATFORM window, 09:00-21:00 IST (SEC-COMP §2.5). India is
   one timezone, so there is nothing per-tenant to resolve; a campaign may NARROW its
   own window, and because that is a campaign fact rather than a number fact it is
   asked by `campaigns.service.campaign_dialable_now` at the same per-dial moment.
4. **DNC** — global + tenant entries, read LIVE. Additions must take effect before the
   next dispatch tick (hard rule 5), so this must never be cached.
5. **Disclosure line** — an agent without one may not dial at all.

Inbound calls never reach this function: the caller initiated them, which is the
consent-clean property D-38 leads with.

One R-11 predicate in this module is deliberately NOT part of `check_dispatch`:
`first_campaign_hold_blocker` (the manual review of a self-serve account's first
campaign) is a CAMPAIGN rule, asked by `campaigns.service.launch_blockers` and
`dispatch_blockers`. It lives here because this is where the tier line is drawn once;
its docstring and `compliance/first_campaign.py` say why the single-lead paths are out
of its scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.service import current_billing_month, get_balance, plan_tier_of
from apps.api.compliance.dnc_recall import enqueue_dnc_recall
from apps.api.compliance.first_campaign import (
    FIRST_CAMPAIGN_REVIEW_PENDING_REASON,
    first_campaign_rejected_reason,
    read_first_campaign_review,
)
from apps.api.compliance.kyc import KYC_MISSING_REASON, kyc_not_verified_reason, read_kyc
from apps.api.compliance.models import CONSENT_STATUSES, DNC_REMOVABLE_SOURCES
from apps.api.core.alerting import record_compliance_block
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import get_platform_status
from apps.api.core.logging import get_logger

log = get_logger(__name__)

# IST. The DB stores UTC (conventions); the RULE is expressed in the caller's time,
# so the conversion happens here and nowhere else.
IST = timedelta(hours=5, minutes=30)
DEFAULT_WINDOW = (time(9, 0), time(21, 0))

# The client-facing wording of the two tenant-level refusals, shared with the campaign
# launch gate so the same condition never gets explained two different ways.
SPEND_CAP_REASON = "This account has reached its spending cap for the month."
NO_CREDITS_REASON = "This account has no calling credit left."

#: The `consent_ledger` statuses that stop a dial (D-117). Derived from the ledger's own
#: vocabulary rather than spelled here — `granted` is the only member that is not a
#: refusal, so a status added to `CONSENT_STATUSES` tomorrow blocks by default and has to
#: be argued INTO the allowed set, which is the safe direction on a compliance gate.
DIAL_REFUSING_CONSENT_STATUSES: frozenset[str] = frozenset(CONSENT_STATUSES) - {"granted"}

#: The refusals that are facts about the PERSON, not about the account, the agent, the
#: paperwork or the clock — the ones that do not become false by waiting.
#:
#: A batch dialler has to know the difference, because it decides whether a refused
#: contact is SETTLED or goes back on the retry ladder. `dnc` was the dispatcher's own
#: hardcoded answer to that question and `no_consent` (D-117) was added to the gate
#: without it, so a person who had explicitly withdrawn permission was re-claimed,
#: re-gated and refused again every thirty minutes for as long as the campaign
#: existed — and because the contact never left `pending`, the campaign never
#: auto-completed and its `campaign.completed` event never fired.
#:
#: Named HERE, beside the rules that produce it, rather than in the dispatcher: a
#: consumer of this gate must not hold its own opinion about which of our refusals are
#: permanent, and the next per-person rule added to `check_dispatch` has one obvious
#: place to declare itself. Membership is deliberately conservative — everything not
#: listed is treated as transient and retried, which is the safe direction for a
#: SETTLEMENT decision (a retried contact is re-gated; a wrongly-settled one is not).
PERSON_LEVEL_REFUSALS: frozenset[str] = frozenset({"dnc", "no_consent"})


@dataclass(frozen=True, slots=True)
class DispatchDecision:
    allowed: bool
    reason: str | None = None
    rule: str | None = None


def ist_now() -> datetime:
    return datetime.now(UTC) + IST


def within_calling_hours(
    now_ist: datetime | None = None, window: tuple[time, time] = DEFAULT_WINDOW
) -> bool:
    """HALF-OPEN: `start <= t < end`, so 21:00:00 IST is OUTSIDE (D-311).

    The rule is written as a PROHIBITION, not as a permission: TCCCPR 2018 forbids a
    commercial communication "between 2100 hours and 0900 hours" (TRAI's own framing,
    carried forward from TCCCPR 2010 reg. 12 and unchanged by the Second Amendment of
    12 Feb 2025). 21:00:00 is the first instant of the forbidden band, not the last of
    the permitted one — so an inclusive upper bound, which is what this was, put a dial
    on the wrong side of it for the whole of the 21:00:00 second. A subscriber's
    complaint carries a wall-clock time, and "21:00" on a complaint is a violation on
    its face whatever our comparison operator thought.

    It also makes this repo say one thing about a time window: `agents/business_hours.
    is_after_hours` already uses `opens <= t < closes`, and two conventions for one
    concept is the drift CLAUDE.md names as a defect even when both work — with the
    extra property here that the two disagreed in the UNSAFE direction.

    The lower bound stays inclusive, and that asymmetry is the rule's: 09:00:00 is the
    first instant OUTSIDE the forbidden band, so the window opens on it.
    """
    current = (now_ist or ist_now()).time()
    start, end = window
    return start <= current < end


# The client-facing wording of the two lifecycle refusals. Shared with the campaign
# launch gate for the reason `SPEND_CAP_REASON` is: one condition, one sentence.
ACCOUNT_SUSPENDED_REASON = "This account is suspended and cannot place calls."
ACCOUNT_CLOSED_REASON = "This account is closed."

# The `organizations.status` values that stop outbound dialling. `prospect`,
# `onboarding` and `active` all dial: an onboarding client placing their first test call
# is the point of onboarding.
_STOPPED_STATUSES = {"suspended": ACCOUNT_SUSPENDED_REASON, "churned": ACCOUNT_CLOSED_REASON}


async def account_stopped_blocker(
    session: AsyncSession, *, tenant_id: UUID
) -> tuple[str, str] | None:
    """`(rule, reason)` if this ACCOUNT's lifecycle state stops its outbound, else None.

    `organizations.status` carried a five-value CHECK from the first migration and was
    written by NOTHING until the admin lifecycle route landed; the only reader was the
    health board's ended-account filter (`admin/health.py`). That made "suspend this
    client" a change of colour on a screen — the campaigns kept dialling, which for a
    client we suspended over complaints or non-payment is a compliance problem and not
    merely a billing one. This is the predicate that makes the status mean something.

    It sits in the DIAL gate rather than in the dispatcher because `check_dispatch` is
    the one function every outbound path calls (hard rule 5): the campaign tick, the
    D-21 "call this lead" button, the instant-lead-callback webhook and the WhatsApp
    escalation all pass through it, and a suspension has to stop all four. It is asked
    again in `campaigns.service.launch_blockers`, under this same rule name, for the
    reason that gate asks about caps and credits: a campaign that launches "ready" and is
    then refused on every contact is worse than a launch button that says why.

    INBOUND IS UNTOUCHED, deliberately and for the reason the whole gate is
    outbound-only: a suspended client's own customers still ring their number, and
    dropping those calls punishes the caller. Suspension stops US dialling OUT.

    FAILS CLOSED. A tenant whose row is not visible — soft-deleted, or an id from
    another tenant under RLS — is refused rather than waved through: every other answer
    here is "we could not confirm this account may dial", and dialling on that is the
    error that cannot be taken back.
    """
    row = (
        await session.execute(
            text("SELECT status, deleted_at FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        return ("account_missing", ACCOUNT_CLOSED_REASON)
    status, deleted_at = str(row[0]), row[1]
    if deleted_at is not None:
        return ("account_closed", ACCOUNT_CLOSED_REASON)
    reason = _STOPPED_STATUSES.get(status)
    if reason is None:
        return None
    return ("account_suspended" if status == "suspended" else "account_closed", reason)


async def spend_capped(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Has this tenant hit its monthly cap? (TRD §9.)

    Split out of `check_dispatch` because the campaign LAUNCH gate asks the identical
    question (SEC-COMP §3 lists per-tenant caps among the launch blockers). One
    implementation, two callers: a campaign that launches "ready" and is then refused
    on every dial is the shape this prevents.

    **The month is part of the question.** The flag is only ever written by the post-call
    pipeline's meter, which runs when a call completes — so a capped tenant meters
    nothing, and the flag cannot clear itself. For a tenant with inbound traffic that
    resolves on its own (inbound is never gated, so it still meters and rolls the month
    over). For an outbound-only tenant — a campaign client, exactly the kind that hits a
    cap — it is a deadlock: capped in July, refused every dial in August, no call ever
    completes to clear it, forever. Reading the month here makes a stale cap stop being
    a cap at the billing boundary rather than at the mercy of the next metered call. The
    same reasoning applies to a raised ceiling: it takes effect immediately instead of
    on the next call that manages to get through.
    """
    row = (
        await session.execute(
            text("SELECT capped, month FROM spend_state WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or not bool(row[0]):
        return False
    return str(row[1]) == current_billing_month()


async def credits_exhausted(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Self-serve/trial only (D-34). A managed client is invoiced against a retainer,
    so blocking them over a wallet they never bought would be an outage caused by a
    concept that does not apply to them. Shared with the launch gate for the same
    reason `spend_capped` is."""
    tier = await plan_tier_of(session, tenant_id)
    if tier not in ("self_serve", "trial"):
        return False
    balance = await get_balance(session, tenant_id=tenant_id)
    return balance.is_exhausted


# The tiers whose identity we have not verified out of band. `credits_exhausted` draws
# the same line for the same shape of reason, and it is named ONCE so the two predicates
# cannot drift into disagreeing about which motion a tenant is on.
SELF_SERVE_TIERS = ("self_serve", "trial")


async def kyc_blocker(session: AsyncSession, *, tenant_id: UUID) -> tuple[str, str] | None:
    """`(rule, reason)` if subscriber KYC blocks this tenant's outbound, else None.

    Returns the PAIR rather than a bool because the two failures are different facts
    with different next actions — nothing filed at all, versus filed and not cleared —
    and both the dial gate and the launch preview must name them identically. Split out
    here, and not inlined into `check_dispatch`, for exactly the reason `spend_capped`
    is: `campaigns.service.launch_blockers` asks the same question, and a campaign that
    launches "ready" and is then refused on every dial is the shape that produces.

    Self-serve and trial only. The argument for that line — including why a tier-blind
    DIAL gate would block every existing client without closing the risk, while the
    tier-blind PROVISIONING gate does close it — is in `apps/api/compliance/kyc.py`.
    """
    if await plan_tier_of(session, tenant_id) not in SELF_SERVE_TIERS:
        return None
    record = await read_kyc(session, tenant_id=tenant_id)
    if not record.recorded:
        return ("kyc_missing", KYC_MISSING_REASON)
    if not record.is_verified:
        return ("kyc_not_verified", kyc_not_verified_reason(str(record.status)))
    return None


async def first_campaign_hold_blocker(
    session: AsyncSession, *, tenant_id: UUID
) -> tuple[str, str] | None:
    """`(rule, reason)` if this account's campaigns are held for manual review, else None.

    R-11's last mitigation (BRD §245, FLOWS §2, D-34): the first campaign of every
    self-serve account gets a human's eyes before it dials. The shape of "first" — a
    property of the ACCOUNT, so it cannot be skipped by launching two campaigns or by
    deleting the reviewed one — is argued in `apps/api/compliance/first_campaign.py`.

    Returns the PAIR rather than a bool for the reason `kyc_blocker` does: "nobody has
    looked yet" and "a reviewer looked and said no" are different facts with different
    next actions, and the launch preview and the dispatch tick must name them identically.

    Lives HERE, beside `kyc_blocker` / `spend_capped` / `credits_exhausted`, because this
    is where the tier line is drawn once (`SELF_SERVE_TIERS`) and because the campaigns
    module must not grow a second copy of it.

    Deliberately NOT called from `check_dispatch`: that gate is also the D-21 "call this
    lead" button and the instant-callback webhook, which are single calls to a lead who
    just raised their hand rather than campaigns. Every document that asks for this
    control scopes it to the first CAMPAIGN, so it is asked on the campaign paths —
    `launch_blockers` and `dispatch_blockers` — and `first_campaign.py` states the
    residual that leaves.
    """
    if await plan_tier_of(session, tenant_id) not in SELF_SERVE_TIERS:
        return None
    review = await read_first_campaign_review(session, tenant_id=tenant_id)
    if review.is_released:
        return None
    if review.reviewed:
        # Reviewed and refused. The reviewer's own words, because "not released" with no
        # reason is the ticket nobody can close.
        return (
            "first_campaign_review_rejected",
            first_campaign_rejected_reason(review.decision_note or ""),
        )
    return ("first_campaign_review_pending", FIRST_CAMPAIGN_REVIEW_PENDING_REASON)


async def check_dispatch(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    phone_e164: str,
) -> DispatchDecision:
    """Returns a decision rather than raising, so callers can render *why* a button is
    disabled — SURFACES §2b asks for blocked features to be visibly explained instead
    of silently missing."""
    platform = await get_platform_status()
    if platform.outbound_halted:
        return DispatchDecision(
            allowed=False,
            rule="big_red_switch",
            reason="Outbound calling is halted platform-wide by the operations team.",
        )

    # Before the agent, the paperwork and the money: an account we have STOPPED does not
    # get to be told its agent is unpublished. Costs one primary-key read on a row this
    # session is already scoped to.
    stopped = await account_stopped_blocker(session, tenant_id=tenant_id)
    if stopped is not None:
        rule, reason = stopped
        return DispatchDecision(allowed=False, rule=rule, reason=reason)

    agent = (
        await session.execute(
            text(
                # `ai_disclosure_line`, not the legacy bundle (D-163). The gate asks
                # whether this agent HAS an AI disclosure on file, which is still
                # mandatory; `ai_disclosure_enabled` — whether it is volunteered at the
                # top of the call — is the tenant's own decision and is deliberately NOT
                # a dial blocker. Reading the bundled column here would have made the
                # question un-answerable the moment the two halves stopped sharing it.
                "SELECT ai_disclosure_line, status, direction FROM agents "
                "WHERE id = :aid AND tenant_id = :tid AND deleted_at IS NULL"
            ),
            {"aid": agent_id, "tid": tenant_id},
        )
    ).first()
    if agent is None:
        return DispatchDecision(allowed=False, rule="agent_missing", reason="Agent not found.")
    disclosure, status, direction = agent
    if not disclosure or not str(disclosure).strip():
        # Belt and braces: the column is NOT NULL with a length CHECK, so reaching this
        # means something bypassed the schema. Refuse loudly rather than dial.
        return DispatchDecision(
            allowed=False,
            rule="disclosure_missing",
            reason="This agent has no AI disclosure line and may not place calls.",
        )
    if status != "live":
        return DispatchDecision(
            allowed=False, rule="agent_not_live", reason="This agent is not live yet."
        )
    if direction == "inbound":
        return DispatchDecision(
            allowed=False,
            rule="agent_inbound_only",
            reason="This agent only answers calls; it cannot place them.",
        )

    # Before the money questions on purpose: "we do not know who you are" outranks "you
    # have run out of credit", and answering in the other order would tell an unverified
    # account to top up when topping up will not let them dial.
    blocked_on_kyc = await kyc_blocker(session, tenant_id=tenant_id)
    if blocked_on_kyc is not None:
        rule, reason = blocked_on_kyc
        return DispatchDecision(allowed=False, rule=rule, reason=reason)

    if await spend_capped(session, tenant_id=tenant_id):
        return DispatchDecision(
            allowed=False,
            rule="spend_cap",
            reason=SPEND_CAP_REASON,
        )

    # Credits gate the self-serve motion only (D-34: one product, two motions).
    if await credits_exhausted(session, tenant_id=tenant_id):
        return DispatchDecision(
            allowed=False,
            rule="no_credits",
            reason=NO_CREDITS_REASON,
        )

    if not within_calling_hours():
        return DispatchDecision(
            allowed=False,
            rule="calling_hours",
            reason="Outbound calls are only placed between 9:00 and 21:00 IST.",
        )

    # LIVE read, never cached: an opt-out captured mid-call must block the very next
    # dispatch. Covers both the tenant's own list and global entries (RLS lets a tenant
    # read global rows precisely so this query can see them).
    blocked = (
        await session.execute(
            text(
                "SELECT 1 FROM dnc_list WHERE phone_e164 = :phone "
                "AND (tenant_id = :tid OR tenant_id IS NULL) LIMIT 1"
            ),
            {"phone": phone_e164, "tid": tenant_id},
        )
    ).first()
    if blocked:
        return DispatchDecision(
            allowed=False,
            rule="dnc",
            reason="This number is on the do-not-call list.",
        )

    # Beside the DNC list because it is the same KIND of fact — this person, not this
    # account — and different in what it records: DNC is "stop calling me", this is
    # "never agreed to be called at all" (D-117).
    #
    # ABSENCE IS NOT A REFUSAL, and that asymmetry is the whole design. Most dialable
    # leads have no `consent_ledger` row: a number typed in by staff, a CSV import, a
    # caller who rang US. Treating silence as `declined` would refuse every one of them
    # and be met as an outage rather than a rule. So only an explicit latest `declined`
    # or `withdrawn` blocks, which is also the ledger's own doctrine — the current state
    # of a `(tenant, phone, purpose)` is the LATEST row for it, and a withdrawal is a new
    # row rather than an edit of the grant.
    #
    # `callback` rather than `marketing`: this gate governs whether we may TELEPHONE this
    # person, which is what a lead-ad opt-in question does or does not grant. The
    # `messaging` purpose has its own gate on the WhatsApp path and must not be conflated
    # — a person may accept a call and refuse a message, and both answers are theirs.
    consent = (
        await session.execute(
            text(
                "SELECT status FROM consent_ledger "
                "WHERE tenant_id = :tid AND phone_e164 = :phone AND purpose = 'callback' "
                "ORDER BY captured_at DESC, id DESC LIMIT 1"
            ),
            {"phone": phone_e164, "tid": tenant_id},
        )
    ).first()
    if consent is not None and str(consent[0]) in DIAL_REFUSING_CONSENT_STATUSES:
        return DispatchDecision(
            allowed=False,
            rule="no_consent",
            reason=(
                "This person has not agreed to be called. The lead was captured without "
                "an opt-in, or the permission was withdrawn."
            ),
        )

    return DispatchDecision(allowed=True)


async def assert_dispatch_allowed(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, phone_e164: str
) -> None:
    """The raising form, for code paths that have no UI to explain a refusal."""
    decision = await check_dispatch(
        session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone_e164
    )
    if decision.allowed:
        return
    record_compliance_block(rule=decision.rule or "unknown")
    # Log the RULE and the tenant, never the number (hard rule 6).
    log.info("dispatch_blocked", extra={"rule": decision.rule, "tenant_id": str(tenant_id)})
    raise ProblemError.business_rule(
        f"dispatch_blocked_{decision.rule}",
        decision.reason or "This call cannot be placed.",
        remediation="Resolve the blocking condition and try again.",
    )


async def add_to_dnc(
    session: AsyncSession, *, tenant_id: UUID, phone_e164: str, source: str
) -> None:
    """Tenant-scope only. A global entry is not a tenant-reachable write (see the
    dnc_list migration) — the RLS WITH CHECK enforces that, not this function.

    **A SUPPRESSION'S SOURCE ONLY EVER GETS STRONGER (D-189).** This used to be
    `ON CONFLICT DO NOTHING`, which is right for the row and wrong for the `source`
    column, and the gap was reachable by an ordinary sequence: a client pastes a number
    into their do-not-call page (`manual`), that same person later calls and says "stop
    calling me", and `record_call_optout` finds the row already there and changes
    nothing. The entry keeps `source = 'manual'`, `dnc.is_removable` therefore returns
    True, the screen offers a delete button, and `remove_entry` honours it — so the
    caller's opt-out is deleted by the account it was made against and the number goes
    back in the dial pool. That is hard rule 5's "can never be removed" failing on the
    most ordinary path there is, and TCCCPR's ninety-day bar on re-soliciting an
    opted-out subscriber with it (see `compliance/optout.py` for the sourcing).

    So the conflict UPGRADES: an existing row whose source is client-deletable is
    rewritten to the incoming non-deletable one, and nothing else is ever rewritten.
    The predicate is stated in both directions on purpose — the update fires only when
    the OLD source is removable AND the NEW one is not — so the write is monotone: a
    `manual` add can never weaken a `call_optout` row, and two opt-outs on one number
    are still a no-op.

    `added_at` is deliberately left alone. It is when this number stopped being
    dialable, the suppression has been continuous since, and moving it forward would
    misdate a fact the client may have to show a TSP.

    REJECTED: doing the upgrade in `record_call_optout` as a follow-up UPDATE. It is the
    same write, split in two, with a window between them in which the row says something
    neither caller believes — and `add_to_dnc` is the one statement every dial-gate
    reader is documented against.
    """
    await session.execute(
        text(
            "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
            "created_at) VALUES (gen_random_uuid(), :tid, :phone, 'tenant', :source, now(), "
            "now()) ON CONFLICT (tenant_id, phone_e164) DO UPDATE "
            "SET source = EXCLUDED.source "
            "WHERE dnc_list.source = ANY(:removable) AND EXCLUDED.source <> ALL(:removable)"
        ),
        {
            "tid": tenant_id,
            "phone": phone_e164,
            "source": source,
            "removable": list(DNC_REMOVABLE_SOURCES),
        },
    )
    # D-428(b): pull back any dial the vendor is already holding for this number, in this
    # transaction so the recall shares the suppression's fate.
    #
    # UNCONDITIONALLY, unlike the bulk writers, and that is a correctness choice rather
    # than a shortcut. They enqueue only for numbers that were newly inserted because a
    # re-import of an unchanged list would otherwise enqueue the whole list. Here there is
    # no list: the common caller is `record_call_optout`, where somebody is ON a call
    # saying stop, and "the row already existed" does not mean no dial is queued — the
    # earlier recall may have been capped, or a campaign may have queued another dial
    # since. Skipping the case where the suppression is not new would skip exactly the
    # case where a second dial had time to appear.
    await enqueue_dnc_recall(session, tenant_id=tenant_id, phones=[phone_e164])


__all__ = [
    "ACCOUNT_CLOSED_REASON",
    "ACCOUNT_SUSPENDED_REASON",
    "DEFAULT_WINDOW",
    "DIAL_REFUSING_CONSENT_STATUSES",
    "IST",
    "NO_CREDITS_REASON",
    "PERSON_LEVEL_REFUSALS",
    "SELF_SERVE_TIERS",
    "SPEND_CAP_REASON",
    "DispatchDecision",
    "account_stopped_blocker",
    "add_to_dnc",
    "assert_dispatch_allowed",
    "check_dispatch",
    "credits_exhausted",
    "first_campaign_hold_blocker",
    "ist_now",
    "kyc_blocker",
    "spend_capped",
    "within_calling_hours",
]
