"""The hold queue — which accounts are waiting on a human, and on what.

Subscriber KYC (`compliance/kyc.py`) blocks a tenant until a person at Calevate acts.
It shipped without the other half of the control. An operator found out an account was
held when the client emailed to ask why nothing worked, which makes a mitigation depend
on the client complaining — that is a support queue, not a control, and it is worst for
exactly the accounts that never complain and simply churn.

WHY THIS IS NOT A CROSS-TENANT QUERY (hard rule 1, decided rather than deferred)
-------------------------------------------------------------------------------
Listing held accounts is a cross-tenant read from the admin realm, and `app.admin`
widens `USING` on `organizations` and nothing else (migration b57e2f9c4a13). Three
shapes were available:

1. **Widen `kyc_records` for `app.admin`** the way
   `organizations` was widened, and answer the question in one SQL statement. Rejected.
   A policy is table-scoped, not column-scoped: widening `kyc_records` hands every
   future query on an admin session the signatory's name, the document reference and
   the rejection prose — a permanent grant, to answer a question that needs none of
   them. It also forces the "is this tenant waiting" condition to be re-expressed in
   SQL beside the Python one the gates ask, and two spellings of one compliance
   condition is the drift this module is written to prevent. b57e2f9c4a13's own
   argument is "the narrowest fix that works"; here a narrower one exists.
2. **Surface the state on the tenant DIRECTORY instead.** This is half of what this module does:
   `admin.service.tenant_overview` now carries `holds` on every row, from
   the function below, so the screen an operator already reads shows the flag.
3. **The queue itself: the directory, then each tenant's record under its own policy.**
   Enumerate tenants under `app.admin`, then read every candidate's KYC record with
   `kyc_hold_scan()` (migration f2c6a8d4b1e3), a SECURITY INVOKER function that sets
   `app.tenant_id` to one tenant at a time, and ask `compliance.service.kyc_rule` — the
   decision `kyc_blocker` makes for the dial. Nothing is widened, no policy changes, and
   the answer comes from the same predicate that refuses the client's dial.

This was a `tenant_session()` per tenant until the KYC review queue measured that shape at
26 s for 7.7k tenants (A7-21); the scan is two statements whatever the tenant count.

WHAT IS ON IT, AND WHAT DELIBERATELY IS NOT (hard rule 6)
---------------------------------------------------------
Accounts, not people. The row carries the tenant, its motion, when it signed up and
which RULES hold it — the same rule names the launch preview and the client's own
screen use, so one condition is never explained in two vocabularies. It carries no
phone number, no document reference, no signatory and no reviewer's note: the reasons
the blockers return are dropped here on purpose: the queue names conditions, and the
client-facing wording stays with the screens that own it. Everything identifying stays
one click away on the account's own screen, behind the permission that opens it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.kyc import NOT_RECORDED, KycRecord, read_kyc
from apps.api.compliance.service import SELF_SERVE_TIERS, kyc_rule


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

    Composed of the gate itself rather than re-derived: `kyc_rule` is the decision
    `kyc_blocker` makes to refuse the dial, so a queue built from it cannot tell an
    operator an account is clear while the client is staring at a refusal. It fails
    CLOSED to held (absence of a record IS the held state), so this function adds no
    judgement of its own.

    The `reason` half of each blocker is discarded on purpose — see the module
    docstring, hard rule 6.
    """
    return _holds(await read_kyc(session, tenant_id=tenant_id))


def _holds(record: KycRecord) -> TenantHolds:
    blockers = (kyc_rule(record),)
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
    # When the account arrived. The wait started then: the gate is "since you signed
    # up, nobody has looked", and a per-record timestamp would be a second answer to one
    # question (a KYC record filed later does not restart the account's wait).
    signed_up_at: datetime
    rules: tuple[str, ...]


# The self-serve tiers only. Since D-692 `kyc_blocker` applies to every tier, but a
# managed or prepaid client waiting on a KYC review is listed by the review queue
# (`GET /v1/admin/kyc/reviews`), which reads the waiting records directly; this queue stays
# the stranger-signup work list the self-serve tier line defines. A pre-FILTER on the
# candidate set, never a second copy of a rule — the blockers below still decide.
_DIRECTORY = (
    "SELECT id, name, slug, plan_tier, created_at FROM organizations "
    "WHERE deleted_at IS NULL AND plan_tier = ANY(:tiers) "
    "ORDER BY created_at"
)

#: Each candidate's KYC record, read under that tenant's own policy (migration f2c6a8d4b1e3).
_HOLD_SCAN: Final = (
    "SELECT scanned_tenant_id, recorded, status, digilocker_required, digilocker_required_at, "
    "digilocker_verified_at FROM kyc_hold_scan(CAST(:ids AS uuid[]))"
)


async def held_tenants(directory: AsyncSession) -> list[HeldTenant]:
    """Every account waiting on a human, oldest signup first.

    `directory` must be an `admin_session()` — the only session that can enumerate
    tenants (b57e2f9c4a13). The KYC records come from `kyc_hold_scan()` (migration
    f2c6a8d4b1e3), which reads each tenant's record with `app.tenant_id` set to that tenant
    alone, so they are read under ordinary RLS, in one statement rather than a session per
    tenant, and this function holds no cross-tenant view of the table at any point. A
    tenant the scan did not return is one the directory listed and the scan could not see
    (deleted between the two statements); it is left off rather than guessed at.

    Oldest first because that is the triage order: the account nobody has looked at for
    three weeks is the one that has quietly stopped trying.
    """
    rows = (await directory.execute(text(_DIRECTORY), {"tiers": list(SELF_SERVE_TIERS)})).all()
    records = {
        UUID(str(r[0])): replace(
            NOT_RECORDED,
            recorded=bool(r[1]),
            status=r[2],
            digilocker_required=bool(r[3]),
            digilocker_required_at=r[4],
            digilocker_verified_at=r[5],
        )
        for r in await directory.execute(text(_HOLD_SCAN), {"ids": [org[0] for org in rows]})
    }

    queue: list[HeldTenant] = []
    for org in rows:
        tenant_id = UUID(str(org[0]))
        record = records.get(tenant_id)
        if record is None:
            continue
        holds = _holds(record)
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
