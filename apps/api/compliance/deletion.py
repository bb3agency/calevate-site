"""DPDP erasure REQUEST path — the producer for `execute_deletion_request`
(SEC-COMP §4, FLOWS §9).

`apps/workers/retention.execute_deletion_request` has always worked and has always been
registered in `WorkerSettings.FUNCTIONS`, but nothing in the repository inserted a
`deletion_requests` row or queued the job, so the DPDP erasure right — the one
obligation whose whole point is that a person can *invoke* it — could not be exercised
at all. This module is the missing half. It does three things and refuses to do a
fourth:

1. **Writes the row and queues the job in ONE transaction.** The row goes to
   `deletion_requests` (RLS-scoped) and the job goes to `outbox_messages` through
   `enqueue_outbox`, both on the caller's session. That is the transactional outbox
   (BACKEND-PATTERNS §4) and it is load-bearing here rather than decorative: a row with
   no job is a promise nobody kept — a request that sits `pending` forever while the
   client believes an erasure is running — and a job with no row is untraceable, because
   the worker resolves the subject *from* the row and would find nothing to erase or
   certify. Enqueuing to ARQ directly from the handler would produce exactly one of
   those two failures on every rollback.

2. **Is idempotent on (tenant, subject) restricted to OPEN requests** — i.e.
   `phone_e164 = :phone AND completed_at IS NULL`, under RLS so `tenant_id` is implied.
   The key is deliberately NOT "this subject, ever". Erasure is not a terminal state for
   a phone number: the same person can call the same client again next month and
   generate fresh personal data, and DPDP §12 lets them exercise the right again over
   it. A forever-key would make the second genuine request unanswerable — a compliance
   bug wearing a safety feature's clothes. What must never happen twice is a *queued,
   unexecuted* erasure: a support agent double-clicking, or two staff filing the same
   caller's request an hour apart, must converge on one certificate. Restricting the key
   to open requests is exactly that statement and no more.

   The check-then-write runs under `pg_advisory_xact_lock` on the same key, for the
   reason `billing/service.lock_tenant_credits` spells out: without it two concurrent
   requests both read "no open request" under READ COMMITTED and both insert. A partial
   unique index on `(tenant_id, phone_e164) WHERE completed_at IS NULL` would be the
   stronger guarantee, but that needs a migration and this table is used as-is.

3. **States what the erasure cannot do** (`ERASURE_LIMITATIONS`), because the client
   hands this to a data principal and an overclaiming certificate is worse than a candid
   one — the same reasoning that makes the worker record `engine_deletion` as
   `unconfirmed` rather than asserting it.

The fourth thing, refused: `deletion_requests.scope` is written as the constant `"all"`
and is NOT taken from the caller. The worker ignores the column entirely — it erases
everything it can reach for that number — so accepting `scope: "transcripts_only"` from
an API client would record a promise nothing in the system keeps.

---

**A conflict in our own documents, surfaced rather than resolved.**

SEC-COMP §4 describes the erasure workflow as covering "calls/turns/leads/**recordings**
… covers our object storage AND engine copies". SEC-COMP §1 records the TRAI rule as a
**90-day minimum retention of call recordings on Indian infrastructure**, a floor the
codebase treats as binding in two places (`retention_policies` has a DB CHECK, and
`apply_retention` refuses to act below `RECORDING_FLOOR_DAYS`). For a recording less
than 90 days old these instructions point in opposite directions: §4 says erase it on
request, §1 says retaining it is mandatory.

The code as it stands has already half-picked, probably without anyone deciding to:
`execute_deletion_request` clears `calls.recording_url` unconditionally, at any age,
while the audio bytes are removed by the object-store lifecycle rule that follows the
retention policy — and that rule is floored at 90 days. So today the *pointer* goes
immediately (nothing in our system can reach the audio) and the *bytes* may lawfully
survive the request. That is a defensible reading, but it is a reading, and this module
does not launder it into a claim. `ERASURE_LIMITATIONS` states the position and names
both sections so that whoever hands the certificate to a data principal knows they are
standing on an unresolved question. Resolving it is a docs decision (a decision-log
entry against SEC-COMP), not something a producer module gets to settle.

**Permission: `org:manage`.** Owner-only in the client realm, operator/superadmin in the
admin realm, and — the part that matters — a member of `MUTATING_PERMISSIONS`, so D-22
refuses it to an impersonating admin. That refusal is the point. The subject-access
export next door explicitly rejected `org:manage` *because* being mutating would block
an impersonating admin from a harmless read; erasure is the mirror image, and an admin
"viewing as client" triggering an irreversible destruction of that client's records is
precisely what read-only impersonation exists to prevent. `calls:read_raw` (the export's
permission) is disqualified for the same reason in reverse: it is not mutating, so it
would let an impersonating admin erase. `staff` holds neither and should not — deleting
the client's records is not a shift-worker decision.

Reading a status is `org:read` instead, deliberately looser: the response carries no
personal data (a `subject_ref` hash, timestamps, and a proof made of hashes and counts),
"has this been done?" is the question support gets asked, and an admin who may not
*cause* an erasure should still be able to *confirm* one. Read-as, never act-as.

Nothing here filters on `tenant_id` in SQL — the session's transaction carries
`app.tenant_id` and RLS does the isolation (hard rule 1). `tenant_id` is taken as an
argument so the caller's scope is explicit at the call site and can be logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.export import subject_ref
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

# The ARQ function name registered in `apps/workers/settings.FUNCTIONS`. The outbox
# dispatcher publishes `job` verbatim, so this string IS the contract with the worker.
DELETION_JOB = "execute_deletion_request"
# Queue name, matching every other outbox producer.
DELETION_QUEUE = "default"
# Written, never accepted from a caller — see the module docstring.
DELETION_SCOPE = "all"

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"

# What the erasure does NOT do. Shipped with every response on this surface because the
# client forwards it to a data principal, and a certificate that quietly overclaims is
# the failure mode DPDP's "erasure with proof" wording exists to prevent.
ERASURE_LIMITATIONS: tuple[str, ...] = (
    "Call recordings: the pointer to the audio is cleared immediately, so nothing in "
    "this system can reach it. The stored audio itself is removed by the object-store "
    "lifecycle rule, which is floored at 90 days by the TRAI retention rule "
    "(SECURITY-COMPLIANCE §1), so a recording younger than that may survive this "
    "request. SECURITY-COMPLIANCE §4 describes erasure as covering recordings; the two "
    "sections are in tension and this notice states the position rather than resolving "
    "it.",
    "consent_ledger entries are retained. They are the append-only proof that the calls "
    "were lawful (hard rule 4); destroying them would remove the evidence, not the "
    "personal data.",
    "usage_events are retained. They are an append-only billing ledger carrying no "
    "personal data, and deleting them would silently rewrite a closed billing period.",
    "Call rows survive with their personal fields cleared rather than being deleted, so "
    "the minutes that were billed stay countable.",
    "Engine-side copies are reported in the certificate as "
    "'unconfirmed_pending_vendor_api'. The voice engine's deletion API is undocumented "
    "(pilot gate), so the certificate does not claim a deletion it cannot show.",
    "This request record itself retains the number, because the queued worker has to be "
    "able to find the subject; it is not cleared when the erasure completes.",
)


@dataclass(frozen=True, slots=True)
class DeletionRequestRecord:
    """One erasure request, in the form that may leave the building.

    Carries `subject_ref` and never `phone_e164`: the row keeps the number so the worker
    can locate the subject, but a status page is read by more people than the request
    was filed by, and the audit trail must not become an index of who exercised a right
    (hard rule 6).
    """

    id: UUID
    subject_ref: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    proof: dict[str, Any] | None
    # True when this request already existed and was returned instead of a new one.
    already_open: bool = False


def _record(row: Any, *, phone_e164: str, already_open: bool) -> DeletionRequestRecord:
    completed_at = row[2]
    return DeletionRequestRecord(
        id=row[0],
        subject_ref=subject_ref(phone_e164),
        status=STATUS_PENDING if completed_at is None else STATUS_COMPLETED,
        requested_at=row[1],
        completed_at=completed_at,
        proof=row[3],
        already_open=already_open,
    )


async def _lock_subject(session: AsyncSession, *, tenant_id: UUID, phone_e164: str) -> None:
    """Serialize every erasure decision for this subject for the rest of the transaction.

    Taken BEFORE the "is one already open?" read, not after: a dedupe check outside the
    lock is the same check-then-write hole the credit ledger documents — two concurrent
    requests both see "none open" and both insert. Keyed on the hash rather than the
    number so the lock key is not another place the number appears.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"deletion:{tenant_id}:{subject_ref(phone_e164)}"},
    )


async def request_erasure(
    session: AsyncSession, *, tenant_id: UUID, phone_e164: str
) -> DeletionRequestRecord:
    """File a DPDP erasure request for one phone number and queue its execution.

    Returns the OPEN request for this subject — the one just created, or the one that was
    already in flight (`already_open=True`). Does not commit: the row, the outbox job and
    the caller's `audit_log` entry share one transaction on purpose.
    """
    await _lock_subject(session, tenant_id=tenant_id, phone_e164=phone_e164)

    existing = (
        await session.execute(
            text(
                "SELECT id, requested_at, completed_at, proof FROM deletion_requests "
                "WHERE phone_e164 = :phone AND completed_at IS NULL "
                "ORDER BY requested_at ASC, id ASC LIMIT 1"
            ),
            {"phone": phone_e164},
        )
    ).first()
    if existing is not None:
        log.info(
            "deletion_request_deduped",
            extra={
                "tenant_id": str(tenant_id),
                "request_id": str(existing[0]),
                "subject_ref": subject_ref(phone_e164),
            },
        )
        return _record(existing, phone_e164=phone_e164, already_open=True)

    request_id = uuid7()
    inserted = (
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, scope, requested_at, "
                "created_at) VALUES (:id, :tid, :phone, :scope, now(), now()) "
                "RETURNING id, requested_at, completed_at, proof"
            ),
            {
                "id": request_id,
                "tid": tenant_id,
                "phone": phone_e164,
                "scope": DELETION_SCOPE,
            },
        )
    ).first()
    assert inserted is not None  # RETURNING on a single-row INSERT

    # The other half of the same transaction. The payload is exactly the two keys
    # `execute_deletion_request` reads; the number is NOT in it — the worker resolves the
    # subject from the row it is pointed at, so a queue dump is not a list of people who
    # asked to be forgotten (hard rule 6).
    await enqueue_outbox(
        session,
        queue=DELETION_QUEUE,
        job=DELETION_JOB,
        payload={"tenant_id": str(tenant_id), "request_id": str(request_id)},
    )

    log.info(
        "deletion_requested",
        extra={
            "tenant_id": str(tenant_id),
            "request_id": str(request_id),
            "subject_ref": subject_ref(phone_e164),
        },
    )
    return _record(inserted, phone_e164=phone_e164, already_open=False)


async def get_request(session: AsyncSession, *, request_id: UUID) -> DeletionRequestRecord:
    """The status of one request, including the proof certificate once it exists.

    RLS scopes the lookup, so another tenant's request is simply not found — which is
    also the answer a nonexistent id gets, deliberately (`ProblemError.not_found`).
    """
    row = (
        await session.execute(
            text(
                "SELECT id, requested_at, completed_at, proof, phone_e164 "
                "FROM deletion_requests WHERE id = :rid"
            ),
            {"rid": request_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Deletion request")
    return _record(row, phone_e164=str(row[4]), already_open=False)


__all__ = [
    "DELETION_JOB",
    "DELETION_QUEUE",
    "DELETION_SCOPE",
    "ERASURE_LIMITATIONS",
    "STATUS_COMPLETED",
    "STATUS_PENDING",
    "DeletionRequestRecord",
    "get_request",
    "request_erasure",
]
