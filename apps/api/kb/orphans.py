"""What is on the engine account that no tenant of ours claims — and what we claim that
is not there (D-519).

THE QUESTION THIS ANSWERS, AND WHY NOTHING ELSE CAN
---------------------------------------------------
`kb/reconciliation.py` sweeps AGENTS: for each one it asks the engine what that agent
references and compares it with what our rows record. That is the right instrument for
"is this client's agent answering from text a human approved", and it is structurally
incapable of seeing an object no agent references — which is exactly what every failure
in this feature leaves behind:

* a create whose response was lost inside the adapter's throttle ladder (`attach_kb` says
  so in its own comment: there is no idempotency key on that route);
* a death between the upload and the agent write;
* a COMMIT that failed after a successful attach (`publish_source`'s last paragraph:
  "nothing here can" prevent it);
* a `_delete_kb_quietly` that itself failed, logged as `kb_orphan_left_on_engine`;
* an agent deleted at the vendor while it still referenced knowledge — and whether THAT
  leaves the knowledge base behind is UNKNOWN (OPERATIONS §2 gate 43f).

We run ONE engine account for every tenant, and on the primary engine a knowledge base is
an account-level object with no owner field of any kind. So an object in that state is a
client's uploaded document — which may hold their customers' names and numbers — sitting
on a shared vendor account, billed for, with nothing anywhere saying whose it is. That is
a DPDP problem before it is an accounting one: an erasure cannot reach what it cannot
name.

**NOTHING HERE DELETES, AND THAT IS THE DECISION RATHER THAN AN OMISSION.**
`kb/reconciliation.py` argues it for drift and every clause transfers with force. An
object this module cannot account for is, by hypothesis, one our tables cannot describe —
so a sweep that "tidied up" would destroy, unattended, the only copy of a document
somebody may have uploaded by hand during an incident, or one belonging to a publish that
is in flight RIGHT NOW. The report is evidence for a human, and the remedy (a `DELETE` at
the vendor) is a human's to take with the client's name in front of them.

WHAT THE VERDICTS MEAN, AND WHY THERE ARE ONLY THREE
----------------------------------------------------
`unrecorded`   the account holds it, our own file-name convention is on it, and no claim
               row of ours names it. The crash window, caught: the object IS attributable
               — `claimed_source_id` names our source — so an operator can say whose it is
               without guessing. Recording the handle by hand is NOT the remedy either
               (the digest and the agent linkage are unknown); the remedy is deleting it
               at the vendor once the client's live version is confirmed good.
`unclaimed`    the account holds it and NOTHING attributes it: no claim row, no name of
               ours. A hand-made upload in the vendor's console, or a build older than the
               convention. This is the one that must never be swept automatically.
`stranded`     WE hold a claim the account does not list. The object was deleted at the
               vendor — a dashboard action, or an agent delete that took its knowledge
               with it — and our tables still promise a client that version is live. The
               agent knows LESS than was approved, which is the direction
               `classify_kb_drift` calls "refuses-and-escalates where it should have
               quoted a price".

An object we hold a claim for and the account still lists is `accounted` and is not
reported: it is counted and nothing else. There is deliberately no fourth verdict for "a
claim whose `kb_sources` row is gone" — that state is CORRECT (the claim outlives our own
rows on purpose, so a tenant erasure can still name the vendor's copy), and it is not
observable from here anyway: this runs untenanted and `kb_sources` is FORCE-RLS'd.

HARD RULE 2. Nothing here sees a vendor payload. What crosses is `AccountKBListing` —
our own model, our own four-value state vocabulary — and the adapter has already done
the attribution from a file name it chose itself.

HARD RULE 6. The report carries opaque vendor handles, our own uuids and counts. No
source name, no chunk, no phone number. `EngineKBRef` is a vendor-issued id, which is the
same class of value `processor_erasure_tasks.vendor_refs` already holds for an operator
to quote at a support desk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from calevate_shared.engine import AccountKBListing, ListingIncompleteReason

#: The closed set of things this report can say about one object. See the module docstring.
KbOrphanVerdict = Literal["unrecorded", "unclaimed", "stranded"]

#: How many rows one report carries. A bound rather than a page, for the reason the
#: platform panel's other counts have one: this is a diagnostic an operator reads to
#: decide whether to act, and the decision is the same at 50 findings as at 5,000 — while
#: an unbounded list is a response that grows with the vendor's account for ever. The
#: COUNTS are exact regardless (they are computed before the truncation), so a truncated
#: report still says how bad it is; `truncated` says the list is not all of it.
MAX_ORPHAN_ROWS = 200

#: How new an unclaimed object may be before it is reported at all.
#:
#: A publish IN FLIGHT looks exactly like an orphan: `attach_kb` creates the vendor object
#: and our claim row is not written until the transaction commits, minutes later on a slow
#: index (`KB_READY_TIMEOUT_S` is 180 seconds by itself). Reporting those would make every
#: normal publish a finding, and a report that cries wolf on routine work is one nobody
#: reads by the time a real stranded document appears. An hour is comfortably longer than
#: the longest publish the adapter permits and far shorter than any interval a human would
#: act on.
MIN_ORPHAN_AGE_S = 3600.0


@dataclass(frozen=True, slots=True)
class KbOrphanRow:
    """One finding, in the form an operator acts on."""

    verdict: KbOrphanVerdict
    #: The vendor's handle. None ONLY where the vendor listed an object it has minted no
    #: reference-able id for yet (still indexing) — a `stranded` row always has one,
    #: because a claim is a handle.
    handle: str | None
    #: Which of our sources this object belongs to, where anything says so. Present on
    #: `stranded` (our claim names it) and on `unrecorded` (the file name does); None on
    #: `unclaimed`, which is the whole meaning of that verdict.
    source_id: UUID | None = None
    #: Whose it is. Only ever known from a claim ROW — the file name attributes an object
    #: to a source, and resolving that source to a tenant is a read of a FORCE-RLS table
    #: this sweep cannot make.
    tenant_id: UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class KbOrphanReport:
    """The whole answer: counts that are always exact, and a bounded list of findings."""

    #: Objects the account holds that a claim row of ours names. The healthy population.
    accounted: int
    unrecorded: int
    unclaimed: int
    stranded: int
    rows: list[KbOrphanRow]
    #: True when `rows` was cut at `MAX_ORPHAN_ROWS`. The counts above are still exact.
    truncated: bool
    #: The adapter's own verdict on its listing, carried through UNCHANGED. A listing that
    #: could not be finished cannot support `unclaimed` or `stranded` at all — the objects
    #: it did not read are indistinguishable from objects that are not there — so the
    #: caller must be able to tell "nothing to report" from "we could not look".
    listing_complete: bool
    listing_incomplete_reason: ListingIncompleteReason | None = None

    @property
    def findings(self) -> int:
        return self.unrecorded + self.unclaimed + self.stranded


async def _claims(session: AsyncSession, *, engine: str) -> dict[str, tuple[UUID, UUID]]:
    """`handle -> (tenant_id, source_id)` for every claim on this engine.

    A GLOBAL read, and the only place in this repository that takes one of these. It is
    what `engine_kb_routes`' RLS exemption was granted for (migration `f1c9e0a73b46`): the
    account is shared by every tenant, so "does anybody claim this object" is a question
    no tenant-scoped session can ask. The per-source reads in `kb/service.py` go through
    `kb_sources` and stay tenant-scoped precisely so this stays the exception.
    """
    rows = await session.execute(
        text(
            "SELECT engine_kb_ref, tenant_id, source_id FROM engine_kb_routes "
            "WHERE engine = :engine"
        ),
        {"engine": engine},
    )
    return {str(handle): (UUID(str(tid)), UUID(str(sid))) for handle, tid, sid in rows}


def _too_new(created_at: datetime | None, *, now: datetime) -> bool:
    """A publish in flight is not an orphan. See `MIN_ORPHAN_AGE_S`.

    An object the vendor gives no `created_at` for is NOT excused: age unknown is not age
    zero, and suppressing a finding on a missing timestamp would hide exactly the objects
    whose provenance is least clear.
    """
    if created_at is None:
        return False
    return (now - created_at).total_seconds() < MIN_ORPHAN_AGE_S


async def reconcile_account_kb(
    session: AsyncSession, listing: AccountKBListing, *, engine: str
) -> KbOrphanReport:
    """Cross the engine account's knowledge bases against every claim we hold.

    Deliberately takes the LISTING rather than the engine: the vendor round trip belongs
    to the caller (a worker tick, or an operator's console read), and a function that
    made it itself could not be tested against a listing shape without a transport stub.
    It also keeps this module free of the adapter entirely, which is what lets it live
    outside `apps/api/engine/` at all.
    """
    claims = await _claims(session, engine=engine)
    now = datetime.now(UTC)
    rows: list[KbOrphanRow] = []
    accounted = unrecorded = unclaimed = 0
    seen: set[str] = set()

    for obj in listing.objects:
        if obj.handle is not None:
            seen.add(obj.handle)
        claim = claims.get(obj.handle) if obj.handle is not None else None
        if claim is not None:
            accounted += 1
            continue
        if _too_new(obj.created_at, now=now):
            # Counted as accounted rather than dropped: it is not a finding and it is not
            # a mystery either — it is a publish that has not committed yet.
            accounted += 1
            continue
        verdict: KbOrphanVerdict = "unrecorded" if obj.claimed_source_id else "unclaimed"
        if verdict == "unrecorded":
            unrecorded += 1
        else:
            unclaimed += 1
        rows.append(
            KbOrphanRow(
                verdict=verdict,
                handle=obj.handle,
                source_id=obj.claimed_source_id,
                created_at=obj.created_at,
            )
        )

    stranded = 0
    if listing.complete:
        # ONLY ON A COMPLETE LISTING. A handle absent from a walk that stopped early is
        # not a handle the account has stopped holding, and reporting it as stranded would
        # tell an operator a client's live knowledge had been deleted on the strength of a
        # read that did not finish. The other two verdicts survive an incomplete listing
        # because they are statements about objects we DID see.
        for handle, (tenant_id, source_id) in sorted(claims.items()):
            if handle in seen:
                continue
            stranded += 1
            rows.append(
                KbOrphanRow(
                    verdict="stranded",
                    handle=handle,
                    source_id=source_id,
                    tenant_id=tenant_id,
                )
            )

    return KbOrphanReport(
        accounted=accounted,
        unrecorded=unrecorded,
        unclaimed=unclaimed,
        stranded=stranded,
        rows=rows[:MAX_ORPHAN_ROWS],
        truncated=len(rows) > MAX_ORPHAN_ROWS,
        listing_complete=listing.complete,
        listing_incomplete_reason=listing.incomplete_reason,
    )


__all__ = [
    "MAX_ORPHAN_ROWS",
    "MIN_ORPHAN_AGE_S",
    "KbOrphanReport",
    "KbOrphanRow",
    "KbOrphanVerdict",
    "reconcile_account_kb",
]
