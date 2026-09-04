"""Closing a client business from the console, and taking it back (D-538).

    GET    /v1/admin/tenants/{tenant_id}/closure   what state is this account in
    POST   /v1/admin/tenants/{tenant_id}/closure   close now, erase after the grace window
    DELETE /v1/admin/tenants/{tenant_id}/closure   undo, while nothing has been deleted

The founder's *"the admins should be able to delete a clients business"* with the decision
taken on it: close now, erase after a grace period, undo during it. `tenancy/closure.py`
carries the whole argument — what the close switches off, what survives it, why the window
is 30 days, and why the undo is safe. This module is the door.

═══ WHY IT IS NOT ON `POST /tenants/{id}/status` ═══

That route already moves an account to `churned` and already demands a step-up. Adding a
"…and schedule the erasure" flag to it would have been the smaller diff and it is the wrong
shape, because the two acts have different consequences and must have different audit rows:
`tenant.churned` says a commercial relationship ended, and `tenant.closed` says a date has
been set after which a business's records are destroyed. A client asking "who decided to
delete our data, and when" must not have to infer it from a boolean inside a status change.

The status route is left exactly as it was — `_LIFECYCLE_FROM` still lists no source for
`churned`, so that route still cannot reopen an account — and it is still the right
control for suspending, reactivating, or ending a relationship whose records we are
keeping. **This module is the ONLY way back from `churned`, and that is deliberate rather
than an omission.** Widening `_LIFECYCLE_FROM` would let the status screen move a CLOSED
account to `active` while `closed_at` and `erase_after` were still set — a row the
database refuses (`ck_organizations_closed_implies_churned`, migration e6c1a49d2f70), so
the operator would get a 500 for pressing a button the console offered them. One door
back, which clears all four columns together and tells the client, is the shape that
cannot produce that.

═══ THE TWO KEYS ON THE CLOSE, AND THE ONE ON THE UNDO ═══

Closing takes the same shape as `record_commercial_terms` and the tenant erasure: the ROLE
check first, then `StepUp.require` bound to this tenant's id. A step-up header is a
confirmation, not an authorisation, so an operator who may not do this at all is told so
rather than asked to type a header — and a confirm dialog in the browser is not a guard,
because it is absent from curl.

`admin:tenants` and NOT `ops:manage`, which is the difference from the erasure route next
door and it is deliberate. Erasing is superadmin-only because it destroys; closing is
reversible for thirty days and is the ordinary offboarding motion an operator runs. The
step-up is what makes it a deliberate act; the superadmin gate is what makes the
irreversible one rare.

**The UNDO carries no step-up at all**, and that asymmetry is the point rather than an
oversight. The step-up exists to stop an unattended console ending a client relationship;
restoring an account ends nothing, destroys nothing and is the recovery path from exactly
the mistake the step-up is guarding against. Putting a second factor in front of the undo
would mean the operator who closed the wrong client at a coffee shop cannot fix it from
the same coffee shop. It keeps `admin:tenants` and an audit row, which is what an act of
this size needs.

═══ EVERY ONE OF THESE IS AUDITED, AND THE READ IS NOT ═══

The close, the undo and the erasure-date change each write to `audit_log` in the SAME
transaction as the write they describe (`write_audit` appends in the caller's transaction
by design). The GET writes no audit row for the reason `holds_routes.py` gives about its
own queue: it discloses no personal data, it is the page an operator refreshes while
talking to a client, and a chain that grows a row per poll stops being readable.

It DOES record an impersonation read (`record_admin_tenant_read`, D-482 L-1) for the same
reason the invitation list does: what it renders — the business's closure reason, the date
their records go — is the client's own data being looked at by us.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy import closure
from apps.workers.account_closure import NOTICE_CLOSED, NOTICE_JOB, NOTICE_RESTORED

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/closure", tags=["admin"])

# `core.deps.db` resolves the tenant from the PRINCIPAL and an admin principal has none,
# so every route here opens `tenant_session(tenant_id)` on the path parameter by hand —
# the house pattern for admin-realm work on one client, and the only shape D-22 leaves
# callable. `audit_log` is not tenant-policied, so its row rides that same transaction.
Closer = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
Reader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]


def close_account_confirmation(tenant_id: UUID) -> str:
    """The `X-Confirm-Action` string for closing THIS client and starting their clock.

    A named function rather than an inline f-string, for the reason
    `spend_ceiling_confirmation` gives: the value is part of an operator procedure typed
    from a runbook, so changing its shape has to be a deliberate edit that fails a test
    rather than a reformat that leaves the console sending a header the API refuses.

    Deliberately DIFFERENT from `admin/routes.close_account_confirmation`
    (`close_account:<id>`), which guards the plain status move. A confirmation captured
    for "end this relationship" must not be replayable as "and destroy their records in
    thirty days" — the two acts have different consequences and therefore different
    words, and both are bound to the tenant so neither replays against another client.
    """
    return f"close_and_schedule_erasure:{tenant_id}"


class ClosureOut(BaseModel):
    """One account's closure state, as the console renders it.

    No personal data by construction: an organisation id, three instants, the operator's
    own recorded words and the id of the operator.

    `days_remaining` is computed SERVER-SIDE and shipped, rather than left to the browser
    to derive from `erase_after`. The countdown and the deadline it counts down to must be
    read off one clock — a number computed from the viewer's laptop disagrees with the
    sweep by whatever that laptop's clock is wrong by, and this is a countdown to
    destruction.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    status: str
    closed_at: datetime | None
    erase_after: datetime | None
    reason: str | None
    closed_by: UUID | None
    erased_at: datetime | None
    #: True while the close can still be taken back — i.e. nothing has been erased. The
    #: console renders its Undo button from this and nothing else, so the button and the
    #: refusal cannot disagree.
    restorable: bool
    #: Whole days from now until the erasure is due, floored at zero. `None` when no
    #: erasure is scheduled. Zero means "today, at the next hourly sweep", NOT "already
    #: gone" — `erased_at` is the only field that says that.
    days_remaining: int | None


def _out(record: closure.ClosureRecord, *, now: datetime) -> ClosureOut:
    remaining: int | None = None
    if record.erase_after is not None and not record.is_erased:
        remaining = max((record.erase_after - now).days, 0)
    return ClosureOut(
        tenant_id=record.tenant_id,
        status=record.status,
        closed_at=record.closed_at,
        erase_after=record.erase_after,
        reason=record.reason,
        closed_by=record.closed_by,
        erased_at=record.erased_at,
        restorable=record.restorable,
        days_remaining=remaining,
    )


class CloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Goes into the audit row AND onto the client's own closure notice, verbatim. Required
    #: and non-trivial for the reason `LifecycleIn` requires one on its stopping states: a
    #: closed account with no recorded reason is the support ticket nobody can close, and
    #: here it is also the only answer the client's email can give to the only question it
    #: raises.
    reason: str = Field(min_length=3, max_length=500)
    #: Days before the erasure becomes due. Defaults to `closure.GRACE_DAYS`.
    #:
    #: BOUNDED AT BOTH ENDS, and the upper bound is the load-bearing one. A window longer
    #: than our own backup-retention window would outlive the restore it is a cheaper form
    #: of, and — the reason that actually matters — holding a client's caller data past the
    #: point their purpose ended is retention we would have to justify under DPDP §8(7) and
    #: have no basis for. Zero is admitted deliberately: "erase at the next sweep" is what
    #: a client asking us to erase now is owed, and refusing it would push them to a
    #: separate, less audited path.
    grace_days: int = Field(default=closure.GRACE_DAYS, ge=0, le=35)


@router.get(
    "",
    response_model=ClosureOut,
    openapi_extra=permission_meta("org:read"),
    summary="Is this client closed, and when do their records go?",
    description=(
        "The closure state of one client: whether the account is closed, why, when, by "
        "whom, the date the erasure becomes due and how many days are left. Reads after "
        "the erasure too — it is the screen that explains what happened to an account "
        "that is no longer anywhere else in the console."
    ),
)
async def read_closure(tenant_id: UUID, request: Request, principal: Reader) -> ClosureOut:
    """`org:read`, NOT `admin:tenants`, and D-22 is why.

    `admin:tenants` is in `MUTATING_PERMISSIONS`, so gating this read on it would hide
    "what happened to this client" from exactly the read-only support session whose job
    is to answer that question. Both admin roles hold `org:read`.
    """
    async with tenant_session(tenant_id) as scoped:
        record = await closure.read_closure(scoped, tenant_id=tenant_id)
        # The reason and the erasure date are this business's own facts about itself, so
        # an operator reading them is an impersonation read (D-482 L-1).
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return _out(record, now=datetime.now(UTC))


@router.post(
    "",
    response_model=ClosureOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Close this client now and schedule the erasure of their records",
    description=(
        "Stops the account immediately — nobody at the client can sign in, no outbound "
        "call or campaign runs, no agent can be published, no invitation can be issued or "
        "redeemed — and sets the date their call records, transcripts and leads are "
        "permanently erased. The client is emailed, and messaged on WhatsApp where they "
        "have opted in. NOTHING IS DELETED BY THIS CALL: until the date passes the "
        "closure can be undone with DELETE on this same path. Needs the header "
        "`X-Confirm-Action: close_and_schedule_erasure:<tenant_id>`. Closing an "
        "already-closed account returns its FIRST closure unchanged rather than "
        "restarting the clock. It does NOT take the client's telephone number out of "
        "service — a caller dialling it may still reach an answering agent until that is "
        "arranged with the telephony provider."
    ),
)
async def close(
    tenant_id: UUID,
    payload: CloseIn,
    request: Request,
    principal: Closer,
    # Resolved BEFORE this handler body runs, so its session read cannot happen inside an
    # open transaction (`core/stepup.py` on `max_overflow=0`).
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> ClosureOut:
    """The close, the queued notice and the audit row, in ONE transaction.

    That is not tidiness. A closure that commits with no notice is a client discovering
    from a caller that their account ended; a notice that commits with no closure is a
    client told their business was shut down when it was not. `enqueue_outbox` puts the
    promise to mail in the same transaction as the write it describes (BACKEND-PATTERNS
    §4), so neither state exists.

    The audit row carries the reason verbatim and the deadline, because "who decided to
    destroy this business's records, when, and on what grounds" is the whole question this
    table exists to answer for an act of this size. It carries no address and no phone
    number (hard rule 6); the notice job records its own delivery, by domain.
    """
    step_up.require(x_confirm_action, close_account_confirmation(tenant_id))

    async with tenant_session(tenant_id) as scoped:
        record = await closure.close_account(
            scoped,
            tenant_id=tenant_id,
            reason=payload.reason,
            closed_by=principal.user_id,
            grace_days=payload.grace_days,
        )
        await enqueue_outbox(
            scoped,
            job=NOTICE_JOB,
            payload={
                "tenant_id": str(tenant_id),
                "event": NOTICE_CLOSED,
                # ISO, and DATE-only: the client is being told which day their records
                # go, and a timestamp to the microsecond in an email reads as machine
                # output rather than a deadline a person can act on.
                "erase_on": record.erase_after.date().isoformat() if record.erase_after else None,
                "reason": record.reason,
            },
        )
        await write_audit(
            scoped,
            action="tenant.closed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={
                "reason": record.reason,
                "erase_after": record.erase_after.isoformat() if record.erase_after else None,
                "grace_days": payload.grace_days,
            },
        )
    return _out(record, now=datetime.now(UTC))


@router.delete(
    "",
    response_model=ClosureOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Undo a closure — reopen the account and cancel the scheduled erasure",
    description=(
        "Reverses a close while nothing has been deleted: the account goes back to "
        "`active`, the scheduled erasure is cancelled, and the client is emailed to say "
        "so. Refused with 409 `tenant_already_erased` once the erasure has RUN — that is "
        "the only refusal, and it is a fact about the data rather than a clock, so a "
        "deadline that has passed while the sweep was behind is still reversible. "
        "Reopening an account that is not closed returns its current state unchanged."
    ),
)
async def restore(tenant_id: UUID, request: Request, principal: Closer) -> ClosureOut:
    """No step-up, deliberately — the module docstring argues why at length.

    Idempotent: reopening an account that is not closed returns the current state and
    writes no audit row, because nothing transitioned. `changed` is not a field on this
    response for the reason `closed_at` makes it unnecessary — the caller can see whether
    the account is closed, which is the fact they asked about.
    """
    async with tenant_session(tenant_id) as scoped:
        before = await closure.read_closure(scoped, tenant_id=tenant_id)
        record = await closure.restore_account(scoped, tenant_id=tenant_id)
        if before.is_closed:
            await enqueue_outbox(
                scoped,
                job=NOTICE_JOB,
                payload={"tenant_id": str(tenant_id), "event": NOTICE_RESTORED},
            )
            await write_audit(
                scoped,
                action="tenant.closure_reversed",
                actor=principal,
                tenant_id=tenant_id,
                object_type="organization",
                object_id=str(tenant_id),
                ip=client_request_ip(request),
                # What the reversal UNDID. The reason and the deadline are read off the
                # pre-restore snapshot, because the restore clears both columns and an
                # audit row saying only "reopened" would leave no record anywhere of what
                # the cancelled deadline had been.
                summary={
                    "cancelled_erase_after": (
                        before.erase_after.isoformat() if before.erase_after else None
                    ),
                    "closure_reason": before.reason,
                },
            )
    return _out(record, now=datetime.now(UTC))


__all__ = ["close_account_confirmation", "router"]
