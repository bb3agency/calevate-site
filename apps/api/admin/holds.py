"""The hold queue — which accounts are waiting on a human, and on what.

Two R-11 mitigations block a tenant until a person at Calevate acts: subscriber KYC
(`compliance/kyc.py`) and the first-campaign review (`compliance/first_campaign.py`).
Both shipped without the other half of the control. An operator found out an account was
held when the client emailed to ask why nothing worked, which makes a mitigation depend
on the client complaining — that is a support queue, not a control, and it is worst for
exactly the accounts that never complain and simply churn.

WHY THIS IS NOT A CROSS-TENANT QUERY (hard rule 1, decided rather than deferred)
-------------------------------------------------------------------------------
Listing held accounts is a cross-tenant read from the admin realm, and `app.admin`
widens `USING` on `organizations` and nothing else (migration b57e2f9c4a13). Three
shapes were available:

1. **Widen `kyc_records` and `first_campaign_reviews` for `app.admin`** the way
   `organizations` was widened, and answer the question in one SQL statement. Rejected.
   A policy is table-scoped, not column-scoped: widening `kyc_records` hands every
   future query on an admin session the signatory's name, the document reference and
   the rejection prose — a permanent grant, to answer a question that needs none of
   them. It also forces the "is this tenant waiting" condition to be re-expressed in
   SQL beside the Python one the gates ask, and two spellings of one compliance
   condition is the drift both modules are written to prevent. b57e2f9c4a13's own
   argument is "the narrowest fix that works"; here a narrower one exists.
2. **Surface the state on the tenant DIRECTORY instead.** This is what
   `first_campaign_routes.py` said the answer should be, and it is half of what this
   module does: `admin.service.tenant_overview` now carries `holds` on every row, from
   the function below, so the screen an operator already reads shows the flag.
3. **The queue itself: the directory, then the tenant's own RLS session.** Which is
   shape 2's mechanism, and the mechanism `tenant_overview` has always used to count a
   client's calls: enumerate tenants under `app.admin`, then enter each tenant with
   `tenant_session()` and ask the ordinary gate. Nothing is widened, no policy changes,
   and the answer comes from the same predicate that refuses the client's dial.

The cost is N+1 by construction — the same trade `tenant_overview` documents, bounded
here by the tier pre-filter below, and payable at M1 scale (one to a few dozen
self-serve accounts) against widening RLS for a work list. A materialized queue is the
answer if it ever gets long enough to notice; it is not the answer today.

WHAT IS ON IT, AND WHAT DELIBERATELY IS NOT (hard rule 6)
---------------------------------------------------------
Accounts, not people. The row carries the tenant, its motion, when it signed up and
which RULES hold it — the same rule names the launch preview and the client's own
screen use, so one condition is never explained in two vocabularies. It carries no
phone number, no document reference, no signatory and no reviewer's note: the reasons
the blockers return are dropped here on purpose, because
`first_campaign_rejected_reason` interpolates an operator's free text and free text can
carry anything into the widest-read list in the console. Everything identifying stays
one click away on the account's own screen, behind the permission that opens it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.service import (
    SELF_SERVE_TIERS,
    first_campaign_hold_blocker,
    kyc_blocker,
)
from apps.api.db.session import tenant_session


@dataclass(frozen=True, slots=True)
class TenantHolds:
    """Which human-action gates are holding this tenant, if any."""

    # The gates' own rule names, in the order they are asked. Empty = nobody is waiting.
    rules: tuple[str, ...]

    @property
    def held(self) -> bool:
        return bool(self.rules)


#: "Nobody is waiting on us for this account", as a value rather than as a literal.
#:
#: It exists because a caller that can decide the answer WITHOUT asking still has to
#: produce the same type `read_tenant_holds` produces — `tenant_overview` skips the read
#: entirely for a tier no blocker applies to (D-218). Spelling `TenantHolds(rules=())` at
#: that call site would be a second place that knows what an empty answer looks like, and
#: the first thing to drift if this dataclass ever grows a field.
NO_HOLDS = TenantHolds(rules=())


async def read_tenant_holds(session: AsyncSession, *, tenant_id: UUID) -> TenantHolds:
    """THE "is this tenant waiting on us" predicate, on the caller's RLS-scoped session.

    Composed of the gates themselves rather than re-derived: `kyc_blocker` is what
    refuses the dial and `first_campaign_hold_blocker` is what refuses the launch, so a
    queue built from them cannot tell an operator an account is clear while the client
    is staring at a refusal — or leave an account off the list because the queue's own
    copy of the tier line drifted from `SELF_SERVE_TIERS`. Both already fail CLOSED to
    held (absence of a record IS the held state) and both already answer `None` for the
    tiers the controls do not apply to, so this function adds no judgement of its own.

    The `reason` half of each blocker is discarded on purpose — see the module
    docstring, hard rule 6.
    """
    blockers = (
        await kyc_blocker(session, tenant_id=tenant_id),
        await first_campaign_hold_blocker(session, tenant_id=tenant_id),
    )
    # `blocker[0]` is the rule name; `blocker[1]` is the client-facing reason, which
    # stops here.
    return TenantHolds(rules=tuple(blocker[0] for blocker in blockers if blocker is not None))


@dataclass(frozen=True, slots=True)
class HeldTenant:
    """One line of the ops work list."""

    tenant_id: UUID
    name: str
    slug: str
    plan_tier: str
    # When the account arrived. The wait started then: both gates are "since you signed
    # up, nobody has looked", and a per-gate timestamp would be a second answer to one
    # question (a KYC record filed later does not restart the account's wait).
    signed_up_at: datetime
    rules: tuple[str, ...]


# Only these tiers can be held: both blockers return None for every other motion. This
# is the same constant the gates draw their line with, imported rather than repeated, so
# it is a pre-FILTER on the candidate set and never a second copy of the RULE — the
# blocker below still decides, and a tenant this filter let through is dropped by it.
_DIRECTORY = (
    "SELECT id, name, slug, plan_tier, created_at FROM organizations "
    "WHERE deleted_at IS NULL AND plan_tier = ANY(:tiers) "
    "ORDER BY created_at"
)


async def held_tenants(directory: AsyncSession) -> list[HeldTenant]:
    """Every account waiting on a human, oldest signup first.

    `directory` must be an `admin_session()` — the only session that can enumerate
    tenants (b57e2f9c4a13). Each tenant is then ENTERED with its own GUC, so the
    compliance rows are read under ordinary RLS and this function holds no cross-tenant
    view of either table at any point.

    Oldest first because that is the triage order: the account nobody has looked at for
    three weeks is the one that has quietly stopped trying.
    """
    rows = (await directory.execute(text(_DIRECTORY), {"tiers": list(SELF_SERVE_TIERS)})).all()

    queue: list[HeldTenant] = []
    for org in rows:
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            holds = await read_tenant_holds(scoped, tenant_id=tenant_id)
        if not holds.held:
            continue
        queue.append(
            HeldTenant(
                tenant_id=tenant_id,
                name=str(org[1]),
                slug=str(org[2]),
                plan_tier=str(org[3]),
                signed_up_at=org[4],
                rules=holds.rules,
            )
        )
    return queue


__all__ = [
    "NO_HOLDS",
    "HeldTenant",
    "TenantHolds",
    "held_tenants",
    "read_tenant_holds",
]
