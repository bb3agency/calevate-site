"""The compliance gate — the ONE function every dispatch path must call.

Hard rule 5, stated as code: campaign launch, the D-21 "call this lead" button and the
instant-lead-callback webhook all place outbound calls, so they all pass through here.
There is **no bypass flag, not even for testing** — staging fixtures exist for that. A
`for_testing=True` parameter on this function would be the single most likely cause of
a real TRAI violation, because the one place it gets left on is production.

Checks, in the order that fails cheapest-first:

1. **Big red switch** — a global outbound halt beats every other consideration.
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
3. **Calling hours** — per-tenant window in IST (SEC-COMP §3).
4. **DNC** — global + tenant entries, read LIVE. Additions must take effect before the
   next dispatch tick (hard rule 5), so this must never be cached.
5. **Disclosure line** — an agent without one may not dial at all.

Inbound calls never reach this function: the caller initiated them, which is the
consent-clean property D-38 leads with.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.service import current_billing_month, get_balance, plan_tier_of
from apps.api.compliance.kyc import KYC_MISSING_REASON, kyc_not_verified_reason, read_kyc
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
    current = (now_ist or ist_now()).time()
    start, end = window
    return start <= current <= end


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

    agent = (
        await session.execute(
            text(
                "SELECT disclosure_line, status, direction FROM agents "
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
    dnc_list migration) — the RLS WITH CHECK enforces that, not this function."""
    await session.execute(
        text(
            "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
            "created_at) VALUES (gen_random_uuid(), :tid, :phone, 'tenant', :source, now(), "
            "now()) ON CONFLICT (tenant_id, phone_e164) DO NOTHING"
        ),
        {"tid": tenant_id, "phone": phone_e164, "source": source},
    )


__all__ = [
    "DEFAULT_WINDOW",
    "IST",
    "NO_CREDITS_REASON",
    "SELF_SERVE_TIERS",
    "SPEND_CAP_REASON",
    "DispatchDecision",
    "add_to_dnc",
    "assert_dispatch_allowed",
    "check_dispatch",
    "credits_exhausted",
    "ist_now",
    "kyc_blocker",
    "spend_capped",
    "within_calling_hours",
]
