"""TENANT-level erasure — the writer `organizations.deleted_at` never had (FLOWS §9).

`organizations.deleted_at` has been read by nine places since the first migration and
written by nothing in `apps/`: `core/auth.py`'s membership resolution and its
impersonation slug lookup, `compliance.service.account_stopped_blocker`,
`admin.service.tenant_exists` (and through it the lifecycle switch and every route that
names a tenant in its path), `admin.service.assert_account_open` at both ends of an
invitation, the admin directory, the health board, `quality/service.py` +
`quality/sampling_routes.py` and `workers/qa_sampling.py`. Every one of those readers is
correct and tested. The act that SETS the column did not exist, so a whole column of
load-bearing behaviour was unreachable — recorded as a gap in D-120 and closed here.

--------------------------------------------------------------------------------
THE THREE STATES, AND WHY THERE IS NO FOURTH
--------------------------------------------------------------------------------

`status` and `deleted_at` are two facts about different things, and the repo already
treats them as related-but-distinct in `admin.service.assert_account_open` and
`core/auth.py`. Stated here once, because a writer that disagreed with any reader would
be worse than no writer at all:

- **`status`** is the COMMERCIAL relationship. `active` / `suspended` / `churned` are
  what we have agreed with this business today; `churned` is terminal
  (`admin/routes.py::_LIFECYCLE_FROM` has no exit) and reversal is a new agreement.
  Data is untouched by any of them: FLOWS §9 is explicit that `apply_retention` keeps
  running for a churned tenant, so their recordings and leads age out on exactly the
  schedule their own policies name.
- **`deleted_at`** is a fact about the DATA, not the contract: *we have executed a
  tenant-level erasure and this client's caller data is gone from our stores.* It is set
  once, by this module's worker, and nothing anywhere clears it.
- **"account closed"** is the UNION of the two — `deleted_at IS NOT NULL OR status =
  'churned'` — and it is the predicate, not a state. `assert_account_open` and
  `compliance.service.account_stopped_blocker` both compute it, under the same rule name
  (`account_closed`), which is why an operator sees one problem rather than two.

**The invariant that makes the nine readers agree: an erased tenant is always churned.**
Some readers filter on `deleted_at` alone (the directory, `tenant_exists`, the QA
sampler); some on `status` alone; some on both. That is only safe if `deleted_at` is a
STRICT REFINEMENT of `churned` — otherwise a "deleted" tenant that was still `active`
would be absent from the directory and present in the auth path, and the two halves of
the console would disagree about whether a business exists. So:

    deleted_at IS NOT NULL  =>  status = 'churned'

is enforced in three places, deliberately redundantly: this module refuses to FILE an
erasure for a tenant that is not already `churned`, the worker's UPDATE carries
`AND status = 'churned'` in its WHERE clause, and migration ``f3a71c9e26b4`` puts
`ck_organizations_deleted_implies_churned` on the table so no future writer — a script,
a hand-run UPDATE, a second code path — can break it. The database is the one that
actually holds it; the other two are there so the failure is a clear refusal rather than
an integrity error surfacing as a 500.

The fourth state that is NOT invented: there is no `erasing` status and no `deleting`
flag. A filed-but-unexecuted erasure is a row in `tenant_erasure_requests` with
`completed_at IS NULL`, exactly as a filed-but-unexecuted subject erasure is a row in
`deletion_requests`; the tenant meanwhile is `churned` and dials nothing, which is
already the correct behaviour for the window. Adding a lifecycle value would have meant
touching the CHECK on `organizations.status` and every screen that renders it, to
describe a state that lasts seconds.

--------------------------------------------------------------------------------
WHY THIS IS NOT A `deletion_requests` ROW (the subjects are different)
--------------------------------------------------------------------------------

`deletion_requests` is the DPDP §12 right of ONE DATA PRINCIPAL, exercised by the client
against their own caller records: keyed by `phone_e164`, deduped per subject, and its
certificate is a document the client hands to the person who asked. We are the Processor
there and the client is the Fiduciary.

A tenant erasure has a different subject and a different requester. The instruction comes
from the CLIENT ORGANISATION (or from us, on their behalf, at the end of the engagement),
it covers every data principal in the account at once, and the certificate is filed
between us and the client. Under DPDP §8 the Fiduciary is responsible for processing
carried out on its behalf by a Processor and must have the Processor erase on
instruction; a tenant erasure IS that instruction being executed, not a §12 request. See
the register below.

Conflating them would have had concrete, ugly consequences rather than merely conceptual
ones. `deletion_requests` is a CLIENT-realm surface (`deletion_routes.py`), so tenant
rows would appear in a client's own erasure register; `subject_ref` is
`sha256(phone)[:32]` and a tenant row has no phone to hash; the `open_request_names_its_
subject` CHECK forbids an open row without a number; and the alternative — fanning a
tenant erasure out into one `deletion_requests` row per distinct caller — would mint
tens of thousands of certificates attesting to a §12 request nobody made.

**What IS reused, because the mechanism is genuinely one mechanism:** the transactional
outbox (row + job in one transaction), the ARQ worker module (`apps/workers/retention.py`,
which already owns every statement that erases a call, a turn, an extraction, a lead, a
delivered webhook body and a recording), `recording_erasure_holds` for audio still inside
the TRAI floor, `ErasureLimitation` and the register/certificate doctrine, and
`deletion_proof.notice_version`. The only new code is what is genuinely new: the
precondition, the tenant-wide iteration, and the `deleted_at` write.

--------------------------------------------------------------------------------
BLAST RADIUS AND THE TWO KEYS
--------------------------------------------------------------------------------

This is the most destructive operation in the product, so it is gated like the other
irreversible ones rather than more gently. `tenant_erasure_routes.py` applies the shape
`admin/routes.py::record_commercial_terms` established for loosening a spend ceiling —
the ROLE check first (`ops:manage`, i.e. superadmin), then `require_step_up` bound to
this tenant's id — because a step-up header is a confirmation, not an authorisation. A
confirm dialog in the browser is not a guard: it is absent from curl.

`admin:tenants` is the declared permission on the write (it is in `MUTATING_PERMISSIONS`,
so D-22 refuses it to an impersonating admin — a read-only "view as client" session must
never be able to erase the client it is viewing). The status read declares `org:read`,
which is looser on purpose: the certificate carries counts and timestamps and no personal
data, and an operator who may not CAUSE an erasure should still be able to CONFIRM one.
Both strings are members of `get_args(Permission)` and both are held by roles — D-119
exists because a permission that no role holds is a dead route that reads as a guarded
one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.deletion import ErasureLimitation
from apps.api.compliance.deletion_proof import notice_version
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

# The ARQ function name registered in `apps/workers/settings.FUNCTIONS`. The outbox
# dispatcher publishes `job` verbatim, so this string IS the contract with the worker
# (`tests/job_registration_test.py` is what stops it becoming a DLQ generator).
TENANT_ERASURE_JOB: Final = "execute_tenant_erasure"
TENANT_ERASURE_QUEUE: Final = "default"

STATUS_PENDING: Final = "pending"
STATUS_COMPLETED: Final = "completed"

#: The lifecycle state a tenant must already be in before its data may be erased. See
#: the module docstring: this is what keeps `deleted_at` a strict refinement of
#: `churned`, and therefore what keeps the nine readers of the column consistent.
REQUIRED_STATUS: Final = "churned"

#: Same ceiling and same reasoning as `deletion.MAX_LIST`: a list nobody paginates is a
#: list that silently truncates. Far smaller here — this is one row per client we have
#: ever erased, not one per data subject.
MAX_LIST: Final = 200


def tenant_erasure_confirmation(tenant_id: UUID) -> str:
    """The `X-Confirm-Action` string for erasing THIS client's data.

    Bound to the tenant id for the reason `spend_ceiling_confirmation` is: a confirmation
    captured for one client must not be replayable against another. It is a literal an
    operator may have to type from a runbook mid-offboarding, so it stays short and it
    stays here, next to the route that demands it (`core/stepup.py` explains why the
    comparison is shared and the vocabulary is not).
    """
    return f"erase_tenant_data:{tenant_id}"


# --- What a tenant erasure does NOT destroy ----------------------------------------
#
# Same doctrine as `deletion.ERASURE_LIMITATIONS`, same dataclass, and shipped with every
# response on this surface AND written into the certificate: the client files this
# document, and a certificate that lists what it cleared while staying silent about what
# survived is the overclaim SEC-COMP §4 exists to prevent.
#
# Index-aligned with `TENANT_ERASURE_EXCEPTIONS`. Adding one means adding both, and
# `notice_version` changes when either does, so two copies of a certificate for the same
# erasure can be told apart.

TENANT_ERASURE_LIMITATIONS: tuple[str, ...] = (
    "The append-only ledgers are retained: billing usage, the credit ledger, one-time "
    "charges, the consent ledger, the WhatsApp alert opt-in ledger, the national-DND "
    "scrub records and the audit log. They are INSERT-only by construction (hard rule "
    "4) — a correction is a new entry, never an edit — and between them they are the "
    "evidence that the calls were consented to, that the minutes were real and that the "
    "invoices were right. The consent ledger and the audit log carry caller numbers; "
    "the others carry none.",
    "Do-not-call suppressions are retained, both this client's own and the national "
    "ones. Removing them would make the suppressed people callable again by whoever "
    "holds the number next, which is the opposite of what suppression is for.",
    "Call rows survive with their personal fields cleared — both numbers, the summary "
    "and the link to the audio — rather than being deleted, so the minutes that were "
    "billed stay countable against the invoices that were issued.",
    "Audio recordings still inside the 90-day period Indian telecom rules require call "
    "recordings to be retained for are not destroyed early. They are not kept "
    "indefinitely either: each is scheduled, and this certificate states the date the "
    "last of them is destroyed on, which happens without a second request.",
    "Copies held by the voice engine are reported as 'unconfirmed_pending_vendor_api'. "
    "The engine's deletion API is undocumented (pilot gate), so this certificate does "
    "not claim a deletion it cannot show. Confirm the engine-side erasure in writing "
    "before telling the client their data is gone everywhere.",
    "The knowledge base this client's agents answered from is not erased — the sources "
    "they uploaded, every published version of them, and the copies held by the managed "
    "retrieval service. Nothing in this system deletes a knowledge document today and "
    "no retention period expires one; the per-subject erasure register says the same "
    "thing about the same store. Removing it is manual work on both copies.",
    "The people at this client — their user accounts, their memberships and who did "
    "what in the console — are retained. Their access ends the moment this erasure "
    "completes, because every membership resolution and every dial gate refuses an "
    "erased organisation, but the records of who they were remain. That is client "
    "account data rather than caller data, it is the subject of a different erasure "
    "right, and destroying it would break the audit log's account of who ran this very "
    "erasure.",
)

TENANT_ERASURE_EXCEPTIONS: tuple[ErasureLimitation, ...] = (
    ErasureLimitation(
        what="The append-only ledgers.",
        keyword="ledger",
        outcome="retained_as_evidence",
        why=(
            "Usage events, the credit ledger, one-time charges, the consent ledger, the "
            "WhatsApp alert opt-in ledger, the national-DND scrub records and the audit "
            "log are INSERT-only. They are the evidence that the calls were lawful and "
            "that the money was right, and an erasure that rewrote them would destroy "
            "the proof rather than reduce what is known about anyone. The consent "
            "ledger and the audit log do carry caller numbers; the rest carry none."
        ),
        authority=(
            "Hard rule 4 (append-only ledgers); SECURITY-COMPLIANCE §4. DPDP §8(7) "
            "requires erasure once the purpose is served 'unless retention … is "
            "necessary for compliance with any law for the time being in force', and "
            "the lawfulness evidence for calls already placed is exactly that case."
        ),
    ),
    ErasureLimitation(
        what="Do-not-call suppressions.",
        keyword="do-not-call",
        outcome="retained_as_suppression",
        why=(
            "A suppression records a number and a scope and nothing else about the "
            "person. Deleting it would make them callable again, which is the opposite "
            "of what they asked for."
        ),
        authority="Hard rule 5 (DNC additions propagate before the next dispatch tick).",
    ),
    ErasureLimitation(
        what="The call rows themselves.",
        keyword="call rows",
        outcome="retained_stripped",
        why=(
            "Each call survives as a row with its personal fields emptied rather than "
            "being deleted outright, so the minutes that were billed stay countable. "
            "What is left is a duration, a timestamp and identifiers that point at no "
            "person."
        ),
        authority=(
            "SECURITY-COMPLIANCE §4 — erasure removes the personal data, not the fact "
            "that a call happened and was billed."
        ),
    ),
    ErasureLimitation(
        what="Audio recordings still inside their mandatory retention period.",
        keyword="recording",
        outcome="retained_under_legal_floor",
        why=(
            "The link this system held to every recording was cleared, so nothing in "
            "Calevate can play, download or export any of them, and every audio file "
            "past the 90-day floor was destroyed. The ones still inside it are not "
            "destroyed early and are not kept: each has a destruction date fixed at the "
            "moment this erasure ran, and the nightly sweep destroys it on that date "
            "without anyone filing a second request."
        ),
        authority=(
            "The 90-day recording-retention floor (SECURITY-COMPLIANCE §1) read against "
            "DPDP §12(3) — erasure is required 'unless retention of the same is "
            "necessary … for compliance with any law', so a retention obligation defers "
            "an erasure rather than cancelling it — and DPDP §8(7), which makes keeping "
            "the data past the end of that obligation a breach in itself. Whether an "
            "under-age recording should be destroyed on request anyway is the open "
            "decision recorded in SECURITY-COMPLIANCE §4; nothing here takes it."
        ),
    ),
    ErasureLimitation(
        what="Copies held by the voice engine that carried these calls.",
        keyword="engine",
        outcome="unconfirmed",
        why=(
            "The engine is a third-party platform and its deletion API is undocumented, "
            "so this certificate reports engine-side deletion as "
            "'unconfirmed_pending_vendor_api' rather than claiming something it cannot "
            "show."
        ),
        authority=(
            "SECURITY-COMPLIANCE §4 — the vendor erasure commitment is an open "
            "contractual item (pilot gate 12(f))."
        ),
    ),
    ErasureLimitation(
        what="The knowledge base this client's agents answered from.",
        keyword="knowledge base",
        outcome="not_searched",
        why=(
            "The sources this client uploaded, every published version of them, and the "
            "copies held by the managed retrieval service are neither read nor changed "
            "by this erasure. Nothing in this system deletes a knowledge document and "
            "no retention period expires one. If caller details were put into that "
            "content, finding and removing them is manual work on both copies."
        ),
        authority=(
            "SECURITY-COMPLIANCE §4 enumerates the erasure scope as calls, transcript "
            "turns, extracted fields, leads and recordings; DATA-MODEL §9's retention "
            "categories do not cover knowledge content. The same gap is stated in the "
            "per-subject register (`deletion.KB_OUTCOME`) and pinned by "
            "`tests/kb_retention_gap_test.py`; one gap, one statement, not two."
        ),
    ),
    ErasureLimitation(
        what="The client's own people — users, memberships and console history.",
        keyword="memberships",
        outcome="retained_account_data",
        why=(
            "Their access ends when this erasure completes: every membership resolution "
            "and every dial gate refuses an erased organisation. The records of who "
            "they were remain, because they are client ACCOUNT data rather than the "
            "caller data this erasure covers, and because the audit log's account of "
            "who ran this erasure names them."
        ),
        authority=(
            "SECURITY-COMPLIANCE §4 — we are the Processor for callers' data and the "
            "Fiduciary for client-account data; the two are separate DPDP relationships "
            "and this instruction covers the first. A person at the client exercising "
            "their own §12 right against us is a different request."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class TenantErasureRecord:
    """One tenant erasure, in the form that may leave the building.

    No personal data by construction: an organisation id, timestamps, and a proof made
    of counts. `already_open` is True when the caller asked for an erasure that was
    already in flight and got that one back instead of a second.
    """

    id: UUID
    tenant_id: UUID
    status: str
    reason: str
    requested_at: datetime
    completed_at: datetime | None
    proof: dict[str, Any] | None
    already_open: bool = False


def _record(row: Any, *, already_open: bool) -> TenantErasureRecord:
    """Build the record from `id, tenant_id, reason, requested_at, completed_at, proof`."""
    completed_at = row[4]
    return TenantErasureRecord(
        id=row[0],
        tenant_id=row[1],
        status=STATUS_PENDING if completed_at is None else STATUS_COMPLETED,
        reason=str(row[2]),
        requested_at=row[3],
        completed_at=completed_at,
        proof=row[5],
        already_open=already_open,
    )


_SELECT = (
    "SELECT id, tenant_id, reason, requested_at, completed_at, proof FROM tenant_erasure_requests"
)


async def assert_erasable(session: AsyncSession, *, tenant_id: UUID) -> None:
    """May this client's data be erased at all? Absent → 404, not closed → 409.

    THE PRECONDITION THAT KEEPS THE COLUMN'S MEANING (module docstring): an erased tenant
    must already be `churned`, or `deleted_at` stops being a refinement of "account
    closed" and the readers that filter on only one of the two disagree with each other.

    Refuses an already-erased tenant separately and by name. `deleted_at` is set once and
    never cleared, so "erase it again" is not a retry — it is a request whose whole
    subject is already gone, and answering it with a second certificate would attest to
    an erasure that did nothing.

    Deliberately NOT `admin.service.tenant_exists`: that predicate treats a soft-deleted
    tenant as ABSENT, which is right for every surface that manages a live client and
    wrong for the one surface whose job is to talk about the deletion. A 404 here would
    tell an operator the client never existed.
    """
    row = (
        await session.execute(
            text("SELECT status, deleted_at FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Client")
    status, deleted_at = str(row[0]), row[1]
    if deleted_at is not None:
        raise ProblemError.conflict(
            "tenant_already_erased",
            "This client's data has already been erased.",
            remediation=(
                "Erasure runs once and cannot be repeated. Open the erasure record for "
                "this client to read the certificate."
            ),
        )
    if status != REQUIRED_STATUS:
        raise ProblemError.conflict(
            "tenant_not_closed",
            "This client's account is still open, so its data cannot be erased.",
            remediation=(
                "Close the account first on the Account state screen — erasing the data "
                "of a client we are still contracted to would be an outage, not an "
                "offboarding."
            ),
        )


async def request_tenant_erasure(
    session: AsyncSession, *, tenant_id: UUID, reason: str
) -> TenantErasureRecord:
    """File the tenant erasure and queue its execution. Does not commit.

    Returns the OPEN request — the one just created, or the one already in flight
    (`already_open=True`, which the route turns into a 200). The row, the queued job and
    the caller's `audit_log` entry share one transaction on purpose: a row with no job is
    an offboarding that silently never runs, and a job with no row has nothing to
    certify.

    The advisory lock is taken BEFORE the "is one already open?" read, for the reason
    `deletion._lock_subject` gives: a dedupe check outside a lock is the check-then-write
    hole two concurrent requests both walk through. The partial unique index added by the
    migration makes the guarantee a database fact regardless; the lock is what makes the
    loser receive the WINNER'S request rather than an integrity error.
    """
    await assert_erasable(session, tenant_id=tenant_id)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"tenant_erasure:{tenant_id}"},
    )

    existing = (
        await session.execute(
            text(f"{_SELECT} WHERE completed_at IS NULL ORDER BY requested_at ASC, id ASC LIMIT 1")
        )
    ).first()
    if existing is not None:
        log.info(
            "tenant_erasure_deduped",
            extra={"tenant_id": str(tenant_id), "request_id": str(existing[0])},
        )
        return _record(existing, already_open=True)

    request_id = uuid7()
    inserted = (
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests "
                "(id, tenant_id, reason, requested_at, created_at) "
                "VALUES (:id, :tid, :reason, now(), now()) "
                "RETURNING id, tenant_id, reason, requested_at, completed_at, proof"
            ),
            {"id": request_id, "tid": tenant_id, "reason": reason},
        )
    ).first()
    assert inserted is not None  # RETURNING on a single-row INSERT

    await enqueue_outbox(
        session,
        queue=TENANT_ERASURE_QUEUE,
        job=TENANT_ERASURE_JOB,
        payload={"tenant_id": str(tenant_id), "request_id": str(request_id)},
    )
    log.info(
        "tenant_erasure_requested",
        extra={"tenant_id": str(tenant_id), "request_id": str(request_id)},
    )
    return _record(inserted, already_open=False)


async def get_tenant_erasure(session: AsyncSession, *, request_id: UUID) -> TenantErasureRecord:
    """One erasure record by id. RLS scopes it, so another tenant's request is not found
    — the same answer a nonexistent id gets, deliberately."""
    row = (await session.execute(text(f"{_SELECT} WHERE id = :rid"), {"rid": request_id})).first()
    if row is None:
        raise ProblemError.not_found("Erasure request")
    return _record(row, already_open=False)


async def list_tenant_erasures(
    session: AsyncSession, *, limit: int = MAX_LIST
) -> list[TenantErasureRecord]:
    """This tenant's erasure records, newest first.

    READABLE AFTER THE ERASURE, which is the point and is why nothing on this surface
    goes through `tenant_exists`: the certificate is the artifact the whole operation
    exists to produce, and a screen that 404s the moment the erasure succeeds would make
    it unreachable at exactly the moment somebody needs it.
    """
    rows = (
        await session.execute(
            text(f"{_SELECT} ORDER BY requested_at DESC, id DESC LIMIT :limit"), {"limit": limit}
        )
    ).all()
    return [_record(row, already_open=False) for row in rows]


# --- The certificate ---------------------------------------------------------------


def _count(value: Any) -> int | None:
    """A count from a durable JSON document, or None when it is not a count.

    ABSENT IS NOT ZERO, for the reason `deletion_proof` gives about the same field class:
    a recorded 0 is the claim "there were none", a missing key means the proof was
    written by a worker that did not record it, and hard rule 4 forbids back-filling the
    row to say otherwise.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def certificate(stored: dict[str, Any] | None) -> dict[str, Any] | None:
    """Render the document from the proof the worker stored. `None` in, `None` out.

    THE STORED PROOF IS READ BY NAME, NEVER SPLATTED — the same rule
    `deletion_proof.certificate` states and the same 500 it avoids: the response model is
    `extra="forbid"`, so `Model(**stored)` would turn "a later worker recorded one more
    fact" into an error on the endpoint whose only subject is an erasure that already
    happened. This renderer takes what it understands and ignores the rest.
    """
    if stored is None:
        return None
    scope = stored.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    actions = stored.get("actions")
    actions = actions if isinstance(actions, dict) else {}
    return {
        "tenant_id": str(stored.get("tenant_id") or ""),
        "executed_at": str(stored.get("executed_at") or ""),
        "scope": {key: _count(scope.get(key)) for key in _SCOPE_COUNTS},
        "recording_hold_until": (
            str(scope["recording_hold_until"])
            if isinstance(scope.get("recording_hold_until"), str)
            else None
        ),
        "actions": {str(k): str(v) for k, v in actions.items()},
        "engine_deletion": str(stored.get("engine_deletion") or ""),
        "not_erased": [
            {
                "what": entry.what,
                "outcome": entry.outcome,
                "why": entry.why,
                "authority": entry.authority,
            }
            for entry in TENANT_ERASURE_EXCEPTIONS
        ],
        "limitations": list(TENANT_ERASURE_LIMITATIONS),
        "limitations_version": notice_version(
            TENANT_ERASURE_LIMITATIONS, TENANT_ERASURE_EXCEPTIONS
        ),
    }


#: The counted facts the certificate reports, in the order a reader wants them. A fixed
#: list rather than "whatever the proof carries", so the response model stays a
#: whitelist and a worker that records a new key cannot widen the API by accident.
_SCOPE_COUNTS: Final = (
    "calls_erased",
    "transcript_turns_erased",
    "call_extractions_erased",
    "leads_erased",
    "campaign_contacts_erased",
    "recordings_destroyed",
    "recordings_within_trai_floor",
    "webhook_bodies_erased",
)


__all__ = [
    "MAX_LIST",
    "REQUIRED_STATUS",
    "STATUS_COMPLETED",
    "STATUS_PENDING",
    "TENANT_ERASURE_EXCEPTIONS",
    "TENANT_ERASURE_JOB",
    "TENANT_ERASURE_LIMITATIONS",
    "TENANT_ERASURE_QUEUE",
    "TenantErasureRecord",
    "assert_erasable",
    "certificate",
    "get_tenant_erasure",
    "list_tenant_erasures",
    "request_tenant_erasure",
    "tenant_erasure_confirmation",
]
