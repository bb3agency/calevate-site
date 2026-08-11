"""Calevate's own DLT telemarketer registration — the platform-level compliance fact.

SEC-COMP §3's first bullet has two halves and they live in two different places:

- the CLIENT is the Principal Entity — per tenant, in `dlt_registrations`, recorded by
  the admin surface and read by the launch gate as `pe_registration_*`;
- **CALEVATE is the registered Telemarketer** — one fact for the whole platform, in
  `platform_state`, recorded here and read by the launch gate as
  `tm_registration_missing`.

A per-tenant copy of the second would be N copies of one fact, and the first time two
of them disagreed there would be no way to say which one was the platform. So it sits
beside the load-shed mode and the big red switch, in the single global row, and every
tenant's launch preview reads the same value.

**Read on the CALLER'S session, deliberately.** `launch_blockers` already holds a
tenant session; reading the row on it costs one query on a connection that is already
open, and — unlike `core.loadshed`'s three-layer cache — it is never stale. The
load-shed mode is read on every request and is allowed a 15-second window; a compliance
gate is read once per launch and is not: a TM registration revoked ten seconds ago must
block the campaign being launched right now.

**Fails CLOSED, unlike `loadshed`.** A missing `platform_state` row makes `loadshed`
answer "normal" — a fresh database is not an emergency, and refusing every request
because a seed row is absent would be a self-inflicted outage. The opposite default is
right here: an unreadable registration is not evidence of a registration, and the cost
of guessing wrong is dialling India's network as an unregistered telemarketer. No row,
no registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.reliability.models import (
    TM_REGISTRATION_STATUSES as _TM_REGISTRATION_STATUSES,
)

# The registrar's lifecycle, same shape as the PE statuses in `compliance.models`.
# `suspended` and `revoked` are separate states because the way back differs: a
# suspension is lifted, a revocation is re-applied for.
# Re-exported from the model that declares the column, so the CHECK constraint, the
# ORM and this validator are one list rather than three that agree today.
TM_REGISTRATION_STATUSES = _TM_REGISTRATION_STATUSES

# Client-facing wording for the launch blocker. It says "Calevate", not "you": a client
# reading this has done nothing wrong and has nothing to fix, and a blocker that reads
# like a to-do item they cannot action is worse than no message at all.
TM_REGISTRATION_MISSING_REASON = (
    "Calevate's own telemarketer (TM) registration with the DLT registrar is not "
    "active, so no outbound campaign can be dialled on any account right now. Your "
    "agents keep answering inbound calls normally. Nothing to do at your end — we are "
    "on it."
)


@dataclass(frozen=True, slots=True)
class TmRegistration:
    """What the registrar says about Calevate, as the platform last verified it."""

    status: str
    tm_id: str | None
    registered_at: datetime | None
    verified_at: datetime | None

    @property
    def is_live(self) -> bool:
        """The ONE definition of 'we may place commercial calls'.

        `submitted` is not live — an application in flight registers nothing — and
        neither is `suspended`, which is the state a spam-complaint run puts a
        telemarketer into (SEC-COMP §1: 5+ complaints in a rolling 10 days ⇒ TSP
        enforcement within 5 days) and is precisely when dialling must stop.
        """
        return self.status == "active"


async def read_tm_registration(session: AsyncSession) -> TmRegistration:
    """The platform's TM registration, read on the caller's connection.

    Safe on a tenant-scoped session: `platform_state` carries no `tenant_id` and no
    RLS policy, so the tenant GUC neither hides it nor is needed to see it.
    """
    row = (
        await session.execute(
            text(
                "SELECT tm_registration_status, tm_id, tm_registered_at, tm_verified_at "
                "FROM platform_state WHERE id = 1"
            )
        )
    ).first()
    if row is None:
        # Fail closed — see the module docstring.
        return TmRegistration(
            status="not_registered", tm_id=None, registered_at=None, verified_at=None
        )
    return TmRegistration(
        status=str(row[0]), tm_id=row[1], registered_at=row[2], verified_at=row[3]
    )


async def set_tm_registration(
    session: AsyncSession,
    *,
    status: str,
    tm_id: str | None,
    registered_at: datetime | None = None,
) -> TmRegistration:
    """Record what the registrar says about US. Ops-only, audited by the caller.

    Deliberately NOT idempotent-by-key and deliberately a full overwrite: there is one
    registration and this is its current state. Every write also stamps
    `tm_verified_at = now()` — when we last LOOKED, which is the only honest reading of
    a fact that changes underneath us.

    The caller MUST have passed the step-up confirmation and MUST write the audit row
    in the same transaction (the row is mutable; `audit_log` is the history).
    """
    if status not in TM_REGISTRATION_STATUSES:
        raise ProblemError(
            kind="validation",
            code="tm_registration_status_invalid",
            title="Unrecognised registration status",
            detail=(
                f"A TM registration status must be one of: {', '.join(TM_REGISTRATION_STATUSES)}."
            ),
        )
    if status == "active" and not (tm_id or "").strip():
        # The DB CHECK enforces this too; raising here turns a 500-shaped constraint
        # violation into the problem+json the operator can act on. An "active"
        # registration that cannot name itself is a claim, not a fact.
        raise ProblemError(
            kind="validation",
            code="tm_registration_id_required",
            title="A registration number is required",
            detail="Recording the TM registration as active needs the registrar's TM id.",
            remediation="Send tm_id with the registration number the registrar issued.",
        )

    registered = registered_at or (datetime.now(UTC) if status == "active" else None)
    row = (
        await session.execute(
            text(
                "UPDATE platform_state SET tm_registration_status = :st, "
                "tm_id = :tm, tm_registered_at = :reg, tm_verified_at = now(), "
                "changed_at = now(), updated_at = now() WHERE id = 1 "
                "RETURNING tm_registration_status, tm_id, tm_registered_at, tm_verified_at"
            ),
            {"st": status, "tm": (tm_id or None), "reg": registered},
        )
    ).first()
    if row is None:
        # The singleton is created by migration 769a9152cb06 and seeded there. Its
        # absence means a database nobody migrated, not a state to paper over.
        raise ProblemError(
            kind="conflict",
            code="platform_state_missing",
            title="Platform state row is missing",
            detail="The platform state singleton does not exist.",
            remediation="Run the migrations (`alembic upgrade head`) on this database.",
        )
    return TmRegistration(
        status=str(row[0]), tm_id=row[1], registered_at=row[2], verified_at=row[3]
    )


__all__ = [
    "TM_REGISTRATION_MISSING_REASON",
    "TM_REGISTRATION_STATUSES",
    "TmRegistration",
    "read_tm_registration",
    "set_tm_registration",
]
