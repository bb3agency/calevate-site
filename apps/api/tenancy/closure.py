"""Closing a client business — the founder's delete button, which deletes nothing today.

*"the admins should be able to delete a clients business and it sends a respective alert
also to that client"* (founder, 4 Sep 2026). The decision taken on that (D-538) is **close
now, erase after a grace period, undo during it**, and this module is the whole of the
first two words and the whole of the undo.

═══════════════════════════════════════════════════════════════════════════════════════
WHAT "CLOSE" SWITCHES OFF, AND WHAT IT DELIBERATELY DOES NOT
═══════════════════════════════════════════════════════════════════════════════════════

Closing is `status -> 'churned'` plus a `closed_at`, and `churned` is not a new state
invented here: it already has five readers, every one of them tested, and the whole point
of reusing it is that they need no edit. Enumerated rather than recalled (hard rule 12) —
`grep` for the two predicates, not memory:

* **Outbound calling stops at the next dial.** `compliance.service.account_stopped_blocker`
  returns `("account_closed", …)`, and `check_dispatch` is the one function every outbound
  path calls — the campaign tick, the "call this lead" button, the instant-lead callback,
  the WhatsApp escalation (hard rule 5).
* **Campaign LAUNCH is refused** under the same rule name, via
  `campaigns.service.launch_blockers`, so a campaign cannot be started into the window.
* **Console access stops on the next request.** `core/auth.py` resolves memberships with
  `o.deleted_at IS NULL AND o.status <> 'churned'` on EVERY request, so a live session
  cookie stops working immediately rather than at its expiry. There is no session table to
  sweep and deliberately none is added.
* **Agents cannot be published or re-published.** `tenancy.lifecycle.assert_account_open`
  refuses, which is what stops an operator with a hand-typed uuid putting a closed client's
  agent back on the phone.
* **Invitations cannot be minted or redeemed** — the same predicate at both ends.

**FOUR THINGS SURVIVE A CLOSE, AND THREE OF THEM ARE INTENDED.**

1. **Inbound answering does not stop, and this is the one that is a GAP rather than a
   decision.** `account_stopped_blocker` is outbound-only on purpose (a suspended client's
   own customers must still be able to ring them), and nothing in this repository takes a
   number out of service at the telephony provider. `compliance/tenant_erasure.py`'s
   register already states the consequence in the client's own words — until somebody
   releases the number, a person dialling the old number still reaches an answering
   agent. Closing therefore stops US from calling out and stops the console; it does not
   silence the line. Releasing the number is an act at the vendor
   (`engine.release_number`, D-535) and it is NOT wired into this path — see the closing
   note at the bottom of this docstring for why not, and what closes it.
2. **The retention sweep keeps running**, on this account's own policies. FLOWS §9 is
   explicit about it, and it is right: a closed account's recordings and transcripts age
   out on the schedule the client agreed to, whether or not anybody presses erase.
3. **In-flight work finishes rather than being torn up.** A call already connected is
   between two people and a third party's platform; there is no supported way to end it
   from here and dropping it mid-sentence would be worse for the caller than letting it
   finish. Its post-call pipeline then runs to completion, which is what keeps the minutes
   billable and the consent record complete. Queued campaign contacts are refused
   one-by-one at `check_dispatch` rather than deleted — the campaign row survives, says
   `account_closed`, and is legible afterwards.
4. **The append-only ledgers are untouched, now and after the erasure** (hard rule 4).

═══════════════════════════════════════════════════════════════════════════════════════
THE GRACE WINDOW, AND WHY IT IS 30 DAYS
═══════════════════════════════════════════════════════════════════════════════════════

`GRACE_DAYS = 30`. Two independent reasons, and neither is "it felt about right":

* **It is the settled B2B SaaS convention**, and a client reading our DPA should find the
  number they expect: set `deleted_at` and a `deletion_scheduled_for` ~30 days out, hold
  the erasure in the queue in case the account holder changes their mind or the deletion
  turns out to have been an account takeover, then purge on a scheduled job
  (https://www.buildmvpfast.com/blog/data-retention-policy-saas-startup-guide-2026 and
  https://cadence.withremote.ai/blog/data-deletion-gdpr, both read 4 Sep 2026; EVIDENCE
  CLASS: REPORTED — these are practitioner write-ups, not a standard or a statute, and
  nothing here rests on them being more than that).
* **It is inside our own backup window.** `infra/backup/README.md` prunes both arms at 35
  days, and `deletion.BACKUP_WINDOW_DAYS` states to the data principal that a backup taken
  before an erasure still holds the records for up to that long. A grace LONGER than the
  backup window would mean the restore-from-backup that an undo is a cheaper form of had
  already expired before the undo did.

**The window is a maximum on the delay and not a minimum on the retention.** DPDP §8(7)
requires a Data Fiduciary to erase, and to *"cause its Data Processor to erase"*, personal
data once the purpose is no longer served, unless retention is necessary for compliance
with a law in force (https://www.indiacode.nic.in/ — s.8(7), read via
https://indiankanoon.org/doc/186118625/ on 4 Sep 2026; EVIDENCE CLASS: VENDOR-PUBLISHED —
the statute text, relayed, not fetched from this container, which is egress-limited). We
are the PROCESSOR for the callers' data and the client is the Fiduciary, so 30 days of
holding it is only lawful as an operational reversal window on the Fiduciary's own
instruction — not as a retention period of ours. That is why the grace is short, why the
client is told the date in the same message that tells them the account closed, and why an
operator can bring the date forward but this module offers nobody a way to push it back.

**THE FOUR LEGAL QUESTIONS THIS MODULE DOES NOT SETTLE** are named in
`docs/ROADMAP.md` D-538 rather than answered in a docstring; the load-bearing one is that a
clinic's PATIENTS cannot ask us to erase anything — they must ask the clinic — and closing
the clinic's account does not extinguish the clinic's own duty to them.

═══════════════════════════════════════════════════════════════════════════════════════
WHY THIS IS NOT A SECOND ERASER
═══════════════════════════════════════════════════════════════════════════════════════

It writes no erase statement at all. `compliance/tenant_erasure.request_tenant_erasure` is
the one filing point and `apps/workers/retention.py` owns every statement that destroys
anything; the deadline this module sets is discharged by `workers/account_closure.
sweep_due_erasures`, whose entire body is "for each account past its date, call that
function". What is genuinely new here is the WINDOW and the UNDO, which did not exist:
before D-538 an erasure was filed and executed within seconds of the click, and the only
way to stop it was to be faster than a worker.

**THE SECOND SCHEDULED ERASURE IN THIS TREE, AND HOW THE TWO ARE KEPT APART.** D-536
landed `tenant_trials.erase_after` and `workers/trials.py` on the same day: a trial that
ends without the client converting stamps a grace date on the TRIAL row and files the same
`request_tenant_erasure` when it passes. That is a genuinely different subject — a trial
lapsing is not an operator closing a business — and neither sweep is an eraser, so there
are still exactly one filing point and one eraser. What there are two of is DEADLINES, and
the boundary between them is structural rather than a convention:

* This one is on `organizations` and requires `closed_at IS NOT NULL`, which the database
  enforces. A trial-scheduled erasure never sets that column, so `due_erasures` cannot see
  it.
* The trials one is on `tenant_trials` and requires a trial row. A closure of an account
  that never had a trial has none, so `workers/trials.py` cannot see it.
* An account that is BOTH — a trial client an operator also closed — can be seen by both,
  and that is safe rather than merely tolerable: `request_tenant_erasure` dedupes on the
  open request under an advisory lock and a partial unique index, so the two converge on
  one request and one certificate.

Two columns answering "when is this account's data due" is still one more than a system
should have, and the convergence — trials stamping `organizations.erase_after` through
`close_account` instead of carrying its own date — is the next act rather than a taste
question. It is NOT taken here because it means closing accounts from a nightly job, which
`workers/trials.py` argues at length must stay a human act with a reason attached.

The precondition ordering falls out of the same reuse. `assert_erasable` refuses a tenant
that is not already `churned`; closing IS that transition; so the close must come first
and the sweep files against an account that already satisfies the precondition. Nothing
had to be relaxed to fit.

═══════════════════════════════════════════════════════════════════════════════════════
THE UNDO, AND THE DECISION IT REVERSES
═══════════════════════════════════════════════════════════════════════════════════════

`admin/routes.py::_LIFECYCLE_FROM` listed no source for `churned` and its docstring said
re-opening a client is a new tenant and a new agreement. **D-538 reverses that position for
the grace window**, and the reversal is not a softening — it is a relocation of the
irreversibility onto the act that actually destroys something. Before: an operator could
end a client relationship with one click and could not take it back, while nothing had yet
been deleted. After: the click is reversible for as long as nothing has been deleted, and
becomes irreversible at the instant something has (`deleted_at IS NOT NULL`, refused by
`restore_account` by name).

**`_LIFECYCLE_FROM` ITSELF IS UNCHANGED, AND THAT IS PART OF THE DESIGN.** The manual
status switch still cannot leave `churned`; `restore_account` is the only exit, and it
clears all four closure columns in the same statement that moves the status. Widening that
table instead would have let the status screen move a CLOSED account to `active` while
`closed_at` was still set — a row the database refuses outright
(`ck_organizations_closed_implies_churned`) — so the operator would be handed a 500 for
pressing a button the console offered them. One exit, which cannot leave the row in a
state the CHECKs forbid.

`restore_account` therefore reads `deleted_at` and not a clock. A sweep that has already
filed the erasure but not yet run it is the one genuinely racy state, and it is settled by
the same read plus the erasure request's own status — see that function.

═══════════════════════════════════════════════════════════════════════════════════════
WHAT IS NOT DONE HERE, SAID PLAINLY (CLAUDE.md: leave no half-wired feature)
═══════════════════════════════════════════════════════════════════════════════════════

Closing does not release the client's telephone numbers or delete their agents at the
voice platform, so inbound calls still reach a live agent after a close. D-535 landed
`release_number` on the engine port THIS WEEK and the campaign provisioning path that owns
number lifecycle is being changed by another lane in this same tree; wiring a release into
the closure path across that seam would be two lanes writing one call site. It is recorded
as the open half of D-538 with the act that closes it named, and the client's closure
notice says it in their own words rather than letting them discover it from a caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: The lifecycle value a closed account holds, imported rather than retyped: it is the
#: erasure's own precondition (`tenant_erasure.assert_erasable`), and a close that produced
#: a status the eraser refuses would schedule a deadline nothing can discharge.
from apps.api.compliance.tenant_erasure import REQUIRED_STATUS as CLOSED_STATUS
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: Days between "the account is closed" and "the erasure becomes due". See the module
#: docstring for both grounds and for why nothing here lets an operator extend it.
GRACE_DAYS: Final = 30

#: The states a close may be entered FROM. Identical to `admin/routes.py::
#: _LIFECYCLE_FROM["churned"]` and imported nowhere from it, because that table is the
#: *manual* status switch's rulebook and this is the closure's; they agree today and
#: `tests/tenant_closure_test.py` pins that they still do, which is a better guarantee
#: than one module reaching into another's private mapping.
CLOSEABLE_FROM: Final = ("prospect", "onboarding", "active", "suspended")


@dataclass(frozen=True, slots=True)
class ClosureRecord:
    """One account's closure state, in the form the console renders and the API returns.

    No personal data by construction: an organisation id, three instants, the operator's
    own words for why, and the id of the operator. `days_remaining` is DERIVED here rather
    than in the browser so the screen and the sweep are reading one clock — a countdown
    computed from the viewer's laptop is a countdown that disagrees with the deadline it
    is counting down to.
    """

    tenant_id: UUID
    status: str
    closed_at: datetime | None
    erase_after: datetime | None
    reason: str | None
    closed_by: UUID | None
    #: Set once the erasure has RUN. While this is None the close is reversible.
    erased_at: datetime | None

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None

    @property
    def is_erased(self) -> bool:
        return self.erased_at is not None

    @property
    def restorable(self) -> bool:
        """Can this account still be brought back? The one predicate the console renders
        its Undo button from, and the same one `restore_account` refuses on.

        Not a clock. A deadline that has passed but whose erasure has not executed is
        still restorable — the sweep may be an hour behind, or stopped, and telling an
        operator "too late" while the data is still there would be a false statement that
        costs a client their account.
        """
        return self.is_closed and not self.is_erased


_SELECT = (
    "SELECT status, closed_at, erase_after, closure_reason, closed_by, deleted_at "
    "FROM organizations WHERE id = :tid"
)


def _record(tenant_id: UUID, row: Any) -> ClosureRecord:
    """Build the record from `status, closed_at, erase_after, closure_reason, closed_by,
    deleted_at` — the column order `_SELECT` and every `RETURNING` here share."""
    values = tuple(row)
    return ClosureRecord(
        tenant_id=tenant_id,
        status=str(values[0]),
        closed_at=values[1],
        erase_after=values[2],
        reason=str(values[3]) if values[3] is not None else None,
        closed_by=values[4],
        erased_at=values[5],
    )


async def read_closure(session: AsyncSession, *, tenant_id: UUID) -> ClosureRecord:
    """This account's closure state. 404 when there is no visible row.

    NOT routed through `admin.service.tenant_exists`, which treats a soft-deleted tenant
    as ABSENT: that is right for every surface managing a live client and wrong for the
    one surface whose subject is the deletion — `tenant_erasure.assert_erasable` states
    the same reasoning about the same trap. An operator asking "what happened to this
    client" must not be told the client never existed.

    RLS scopes the read (hard rule 1): `organizations`' policy matches on `id`, so a
    neighbour's id is invisible rather than merely filtered.
    """
    row = (await session.execute(text(_SELECT), {"tid": tenant_id})).first()
    if row is None:
        raise ProblemError.not_found("Client")
    return _record(tenant_id, row)


async def close_account(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    reason: str,
    closed_by: UUID | None,
    grace_days: int = GRACE_DAYS,
) -> ClosureRecord:
    """Stop this account now and set the date its data is erased. Does not commit.

    Returns the resulting state. IDEMPOTENT on an account that is already closed: the
    second call returns the FIRST closure unchanged — its date, its reason, its operator —
    rather than restarting the clock. An operator refreshing a screen must not silently
    give a client thirty more days, and an operator who genuinely wants a different date
    has `bring_erasure_forward` (which only ever shortens).

    **ONE STATEMENT, AND THE CAS IS THE WHOLE SAFETY ARGUMENT.** The status move and the
    deadline are set together with `status = ANY(:from)` in the WHERE clause, so an
    account somebody else closed, restored or erased between this transaction's read and
    its write is not overwritten — the same doctrine `db/transition.py` applies and the
    reason `billing/service.lock_tenant_credits` exists. A read-then-write here would let
    two operators produce one closure with two different deadlines, of which the row keeps
    the later.

    Deliberately does NOT file the erasure. `workers/account_closure.sweep_due_erasures`
    does that when the date arrives, which is what makes the window real; filing now with
    a delayed job would put the erasure in a queue nobody can inspect and no undo can
    reach.

    Deliberately does NOT write the audit row or send the client's notice either. Both are
    the ROUTE's, in this same transaction — `write_audit` appends in the caller's
    transaction by design, and a notice that commits without its closure (or the reverse)
    is the failure BACKEND-PATTERNS §4 puts everything in one transaction to avoid.
    """
    if grace_days < 0:
        # A programming error, not an operator input — the route's schema bounds it. It
        # raises rather than rendering a message, because a negative grace would compute a
        # deadline in the past and the sweep would erase on its next tick.
        raise ValueError("grace_days must not be negative")

    current = await read_closure(session, tenant_id=tenant_id)
    if current.is_erased:
        raise ProblemError.conflict(
            "tenant_already_erased",
            "This client's data has already been erased.",
            remediation=(
                "Erasure runs once and cannot be repeated. Open the erasure record for "
                "this client to read the certificate."
            ),
        )
    if current.is_closed:
        # Already closed. Return the first closure verbatim — see the docstring.
        log.info(
            "account_close_noop",
            extra={"tenant_id": str(tenant_id), "already_closed": True},
        )
        return current

    row = (
        await session.execute(
            text(
                "UPDATE organizations SET status = :closed, closed_at = now(), "
                "erase_after = now() + make_interval(days => :grace), "
                "closure_reason = :reason, closed_by = :by, updated_at = now() "
                "WHERE id = :tid AND deleted_at IS NULL AND status = ANY(:from) "
                "RETURNING status, closed_at, erase_after, closure_reason, closed_by, deleted_at"
            ),
            {
                "tid": tenant_id,
                "closed": CLOSED_STATUS,
                # ONE CLOCK PER DEADLINE (D-322): `now()` is the database's, and the sweep
                # compares `erase_after <= now()` on that same clock. A deadline written
                # from the API process's clock and judged by the database's is wrong by
                # the skew between them.
                "grace": grace_days,
                "reason": reason,
                "by": closed_by,
                "from": list(CLOSEABLE_FROM),
            },
        )
    ).first()
    if row is None:
        # The CAS lost. Another transaction moved this row between our read and our
        # write; re-reading is the honest answer rather than raising, because whatever it
        # now says is the truth and the caller's intent may already be satisfied.
        return await read_closure(session, tenant_id=tenant_id)

    # Ids and the operator's own words never leave in a log line — the reason is in
    # `audit_log`, which is access-controlled, and hard rule 6 keeps free text an operator
    # typed out of a log stream that is forwarded further than the table is.
    log.warning(
        "account_closed",
        extra={"tenant_id": str(tenant_id), "grace_days": grace_days},
    )
    return _record(tenant_id, row)


async def restore_account(
    session: AsyncSession, *, tenant_id: UUID, to_status: str = "active"
) -> ClosureRecord:
    """Undo a close while the window is open. Does not commit.

    Clears `closed_at`, `erase_after`, the reason and the operator, and puts the account
    back into `to_status`. Returns the resulting state.

    **THE ONE REFUSAL, AND IT IS NOT A CLOCK.** `deleted_at IS NOT NULL` — the erasure ran
    — is refused by name, and nothing else is. A deadline that has PASSED without the
    sweep having executed is still restorable, deliberately: the sweep can be an hour
    behind or stopped, the data is still there, and telling an operator "too late" about
    data that still exists would cost a client their account for a cron's tardiness.

    The race with a sweep that has already FILED the erasure is settled by the same read
    plus the CAS. `deleted_at` is written by the erasure WORKER in the same statement that
    completes it (`tenant_erasure`'s invariant), so:

    * filed and not yet executed → this restore succeeds, and the erasure job then finds
      an account that is no longer `churned` and refuses it — `assert_erasable`'s
      `tenant_not_closed`, which is exactly the right verdict and needs no new code;
    * executed → `deleted_at` is set and this refuses.

    There is no window in which both succeed, because both are guarded on the one column
    the erasure writes.

    IDEMPOTENT on an account that is not closed: returns the current state unchanged,
    because "make this account open" is already true and a 409 for a satisfied intent is
    the shape RFC 9110 §9.2.2 argues against.
    """
    current = await read_closure(session, tenant_id=tenant_id)
    if current.is_erased:
        raise ProblemError.conflict(
            "tenant_already_erased",
            "This client's data has been erased, so the account cannot be reopened.",
            remediation=(
                "Erasure is final. Set up a new client account if they are coming back, "
                "and open this client's erasure record if you need the certificate."
            ),
        )
    if not current.is_closed:
        return current

    row = (
        await session.execute(
            text(
                "UPDATE organizations SET status = :to, closed_at = NULL, "
                "erase_after = NULL, closure_reason = NULL, closed_by = NULL, "
                "updated_at = now() "
                "WHERE id = :tid AND deleted_at IS NULL AND closed_at IS NOT NULL "
                "RETURNING status, closed_at, erase_after, closure_reason, closed_by, deleted_at"
            ),
            {"tid": tenant_id, "to": to_status},
        )
    ).first()
    if row is None:
        return await read_closure(session, tenant_id=tenant_id)

    log.warning("account_restored", extra={"tenant_id": str(tenant_id), "status": to_status})
    return _record(tenant_id, row)


async def bring_erasure_forward(
    session: AsyncSession, *, tenant_id: UUID, erase_after: datetime
) -> ClosureRecord:
    """Move a closed account's erasure date EARLIER. Does not commit.

    The asymmetry is the point and it is enforced in SQL (`erase_after > :when`), not in a
    branch that could be reordered: an operator may honour a client asking "erase it now,
    do not hold it for thirty days", and nobody — operator or client — may push the date
    out, because a longer hold is retention we would have to justify under DPDP §8(7) and
    have no basis for.

    A request to move it later matches zero rows and returns the state unchanged, which
    the route reports as `changed: false`. That is a truthful "no" rather than an error:
    the caller asked for a date the account already beats.
    """
    current = await read_closure(session, tenant_id=tenant_id)
    if not current.is_closed or current.is_erased:
        raise ProblemError.conflict(
            "tenant_not_closed",
            "This client's account is not in a closure window.",
            remediation="Close the account first — there is no erasure date to move.",
        )
    row = (
        await session.execute(
            text(
                "UPDATE organizations SET erase_after = :when, updated_at = now() "
                "WHERE id = :tid AND deleted_at IS NULL AND closed_at IS NOT NULL "
                "AND erase_after > :when "
                "RETURNING status, closed_at, erase_after, closure_reason, closed_by, deleted_at"
            ),
            {"tid": tenant_id, "when": erase_after},
        )
    ).first()
    if row is None:
        return await read_closure(session, tenant_id=tenant_id)
    log.warning("account_erasure_brought_forward", extra={"tenant_id": str(tenant_id)})
    return _record(tenant_id, row)


async def due_erasures(session: AsyncSession, *, limit: int = 200) -> list[tuple[UUID, str]]:
    """Every account whose erasure deadline has passed, oldest deadline first.

    **The sweep's only query, and it MUST run on an `admin_session()`** — the one session
    that may enumerate `organizations` across tenants (migration b57e2f9c4a13). It widens
    `USING` on that table and nothing else, so this cannot reach a call, a lead or a
    transcript; the erasure it leads to opens the tenant's own scoped session for that.
    Passing a tenant-scoped session here returns at most this one tenant, which is a
    silently under-swept night — `tests/tenant_closure_test.py` pins the cross-tenant
    behaviour rather than trusting the comment.

    `deleted_at IS NULL` because an account already erased has no deadline left to
    discharge (the database says so too — `ck_organizations_deleted_implies_no_deadline`),
    and `status = 'churned'` because that is what `assert_erasable` requires and a row
    that fails it would produce a 409 from a cron on every tick for ever.

    Returns `(tenant_id, closure_reason)` so the erasure it files can carry the operator's
    own words as its reason, which is what makes a certificate say WHY rather than
    "scheduled". Bounded, like every sweep here: an unbounded query is the one that
    eventually times out on the night it matters.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, closure_reason FROM organizations "
                "WHERE erase_after IS NOT NULL AND erase_after <= now() "
                "AND deleted_at IS NULL AND status = :closed "
                "ORDER BY erase_after ASC, id ASC LIMIT :limit"
            ),
            {"closed": CLOSED_STATUS, "limit": limit},
        )
    ).all()
    return [(row[0], str(row[1] or "")) for row in rows]


__all__ = [
    "CLOSEABLE_FROM",
    "CLOSED_STATUS",
    "GRACE_DAYS",
    "ClosureRecord",
    "bring_erasure_forward",
    "close_account",
    "due_erasures",
    "read_closure",
    "restore_account",
]
