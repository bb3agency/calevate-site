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
   requests both read "no open request" under READ COMMITTED and both insert. Migration
   e2c47b90d5a1 added the partial unique index on `(tenant_id, phone_e164) WHERE
   completed_at IS NULL`, so that is now a database fact rather than a convention, and
   the lock demotes to belt-and-braces: it still serialises the two requesters so the
   loser receives the WINNER'S request (`already_open=True`) instead of an integrity
   error, which is what this surface should return. A caller who forgets the lock now
   gets a refusal from Postgres rather than a second certificate.

   The dedupe reads `phone_e164` rather than `subject_ref` deliberately: it is the index's
   own key, so the lookup and the constraint cannot drift apart, and an OPEN request
   always carries the number (a CHECK, see below).

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
`execute_deletion_request` clears `calls.recording_url` unconditionally, at any age. So
today the *pointer* goes immediately (nothing in our system can reach the audio) and the
*bytes* survive the request. That is a defensible reading, but it is a reading, and this
module does not launder it into a claim. `ERASURE_LIMITATIONS` and `ERASURE_EXCEPTIONS`
state the position and name both sections so that whoever hands the certificate to a data
principal knows they are standing on an unresolved question. Resolving it is a docs
decision (a decision-log entry against SEC-COMP), not something a producer module gets to
settle.

An earlier version of this notice told the data principal the audio was "removed by the
object-store lifecycle rule, which is floored at 90 days". That sentence described a
mechanism nobody has built. SEC-COMP §4 now records what `infra/object-lifecycle/`
actually is: a bucket-wide growth CEILING (`recordings/` expire at 2555 days), static and
prefix-scoped, which *cannot* follow a per-tenant `retention_policies` row — "no
per-tenant mechanism deletes recording bytes". A certificate that hands someone a
deletion date derived from a rule that does not delete on that clock is exactly the
overclaim this register exists to prevent, so the notice now says the audio is not
deleted by the request at all and must be confirmed removed in writing. That is a
WIDENING of the stated limitation, which is what SEC-COMP §4 permits ("do not narrow the
certificate's limitations text"); the erasure BEHAVIOUR is untouched.

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
from typing import Any, Final
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

# TRAI floor (SEC-COMP §1). Duplicated from `apps/workers/retention.RECORDING_FLOOR_DAYS`
# rather than imported, for the reason `infra/object-lifecycle/apply_lifecycle.py`
# duplicates it too: the API has no business importing a worker module — with its
# session factory and its sweep SQL — in order to print a number into a sentence.
# `tests/erasure_certificate_test.py` pins the two together so they cannot drift.
RECORDING_FLOOR_DAYS: Final = 90

# The key the erasure job will write into the stored proof's `scope` when it starts
# recording how many recordings this request collided with. It counts them TODAY
# (`floor_recordings=` on the job result, plus a warning) but writes them nowhere
# durable, so the certificate reports the count as "not stated" rather than as zero —
# see `deletion_proof._floor_sentence`. Named here because both halves of that
# coordinated change spell it the same way: `tests/retention_conflicts_test.py` pins the
# worker's side, `tests/erasure_certificate_test.py` pins this one.
FLOOR_COUNT_KEY: Final = "recordings_within_trai_floor"

# The one exception the floor count belongs to. Matched on the outcome rather than on a
# list index so that reordering the register cannot silently attach the count to the
# wrong statement.
FLOOR_OUTCOME: Final = "retained_under_legal_floor"


@dataclass(frozen=True, slots=True)
class ErasureLimitation:
    """One thing an erasure does NOT destroy, in the form the certificate carries it.

    Written for a reader who has no access to this codebase — a data principal, a
    support agent, a regulator — so `what` names a thing rather than a table, `why` is
    a paragraph they can act on, and `authority` cites the rule by section so the claim
    can be checked against the source rather than taken on our word.

    `keyword` is not part of the document. It is the anchor that pins this entry to the
    prose sentence at the same index in `ERASURE_LIMITATIONS`: two lists that say the
    same thing drift, and the pairing test is what stops one of them being widened
    while the other quietly stays narrow.
    """

    what: str
    keyword: str
    outcome: str
    why: str
    authority: str


# What the erasure does NOT do. Shipped with every response on this surface AND written
# into the certificate itself (`deletion_proof.certificate`), because the client forwards
# the certificate to a data principal and a document that quietly overclaims is the
# failure mode DPDP's "erasure with proof" wording exists to prevent.
#
# Index-aligned with `ERASURE_EXCEPTIONS` below. Adding a limitation means adding both.
ERASURE_LIMITATIONS: tuple[str, ...] = (
    "Call recordings: the pointer to the audio is cleared immediately, so nothing in "
    "this system can reach, play or export it. The audio file itself is NOT deleted by "
    "this request. Indian telecom rules require call recordings to be retained for at "
    f"least {RECORDING_FLOOR_DAYS} days (SECURITY-COMPLIANCE §1), and no automatic "
    "per-tenant process "
    "removes them once that period passes — the bucket-wide storage rule is a growth "
    "ceiling, not a retention mechanism (SECURITY-COMPLIANCE §4). Treat the audio as "
    "still existing until its removal is confirmed in writing. SECURITY-COMPLIANCE §4 "
    "describes erasure as covering recordings; the two sections are in tension and this "
    "notice states the position rather than resolving it.",
    "consent_ledger entries are retained, and they carry the caller's number. They are "
    "the append-only proof that the calls were lawful (hard rule 4); destroying them "
    "would remove the evidence that consent existed. So the number itself survives on "
    "that ledger even though it is cleared everywhere the calls are stored.",
    "usage_events are retained. They are an append-only billing ledger carrying no "
    "personal data, and deleting them would silently rewrite a closed billing period.",
    "Call rows survive with their personal fields cleared rather than being deleted, so "
    "the minutes that were billed stay countable.",
    "Engine-side copies are reported in the certificate as "
    "'unconfirmed_pending_vendor_api'. The voice engine's deletion API is undocumented "
    "(pilot gate), so the certificate does not claim a deletion it cannot show.",
    "This request record holds the number only until the erasure runs — the queued "
    "worker has to be able to find the subject — and it is cleared in the same write "
    "that records the proof. What remains afterwards is a one-way hash "
    "(`subject_ref`), which confirms an erasure to someone who already has the number "
    "and discloses nothing to anyone who does not.",
    "If this number is on a do-not-call list — the client's own or the national one — "
    "that entry is retained. Removing it would make the person callable again, which is "
    "the opposite of what suppression is for. A DNC entry records a number and a scope, "
    "and nothing else about the person.",
)

# The same register, structured, and the half that rides the CERTIFICATE. Prose is what
# a person reads; these are what a regulator can tabulate and what a machine can check.
# Index-aligned with `ERASURE_LIMITATIONS` — see `ErasureLimitation.keyword`.
ERASURE_EXCEPTIONS: tuple[ErasureLimitation, ...] = (
    ErasureLimitation(
        what="The audio recordings of the calls this erasure covered.",
        keyword="recording",
        outcome=FLOOR_OUTCOME,
        why=(
            "The link this system held to each recording was cleared, so nothing in "
            "Calevate can play, download or export the audio. The audio file itself is "
            "still in object storage and this request did not delete it: Indian telecom "
            "rules require call recordings to be kept for at least "
            f"{RECORDING_FLOOR_DAYS} days, and no automatic per-tenant process removes "
            "them once that period passes. Treat the audio as still existing until the "
            "client confirms its removal in writing."
        ),
        authority=(
            f"TRAI {RECORDING_FLOOR_DAYS}-day recording-retention floor "
            "(SECURITY-COMPLIANCE §1), against the erasure duty in SECURITY-COMPLIANCE "
            "§4. Which of the two takes precedence is an open decision recorded in §4; "
            "until it is taken the pointer is cleared at every age and nothing in this "
            "erasure is conditional on the recording's age."
        ),
    ),
    ErasureLimitation(
        what="The consent record for these calls.",
        keyword="consent",
        outcome="retained_as_evidence",
        why=(
            "The consent ledger is the append-only proof that these calls were "
            "permitted. It records the caller's number, so an erasure leaves that "
            "number on the ledger; deleting the entries would destroy the evidence that "
            "the contact was lawful rather than reduce what is known about the person."
        ),
        authority="Hard rule 4 (append-only ledgers); SECURITY-COMPLIANCE §4.",
    ),
    ErasureLimitation(
        what="The billing records for these calls.",
        keyword="usage_events",
        outcome="retained_as_record",
        why=(
            "Usage events are an append-only billing ledger. They count minutes and "
            "money and name no person, and deleting them would silently rewrite a "
            "billing period that has already been invoiced."
        ),
        authority="Hard rule 4 (append-only ledgers); hard rule 7 (money).",
    ),
    ErasureLimitation(
        what="The call rows themselves.",
        keyword="call rows",
        outcome="retained_stripped",
        why=(
            "Each call survives as a row with its personal fields emptied — both "
            "numbers, the summary and the link to the audio are gone — rather than "
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
        what="Copies held by the voice engine that carried these calls.",
        keyword="engine",
        outcome="unconfirmed",
        why=(
            "The engine is a third-party platform and its deletion API is undocumented, "
            "so this certificate reports engine-side deletion as "
            "'unconfirmed_pending_vendor_api' rather than claiming something it cannot "
            "show. Before telling the data principal those copies are gone, ask whether "
            "a written erasure commitment with the vendor is in place."
        ),
        authority=(
            "SECURITY-COMPLIANCE §4 — the vendor erasure commitment is an open "
            "contractual item (pilot gate 12(f))."
        ),
    ),
    ErasureLimitation(
        what="This erasure request record.",
        keyword="subject_ref",
        outcome="retained_hashed",
        why=(
            "The request held the number only for as long as the erasure took, and it "
            "was cleared in the same write that produced this certificate. What remains "
            "is a one-way reference that confirms this erasure to someone who already "
            "knows the number and discloses nothing to anyone who does not."
        ),
        authority="Hard rule 6 (no personal data in logs or trails); migration f4a8e1c07b62.",
    ),
    ErasureLimitation(
        what="Any do-not-call suppression recorded for this number.",
        keyword="do-not-call",
        outcome="retained_as_suppression",
        why=(
            "If the number is on a do-not-call list — the client's own or the national "
            "one — that entry stays. Removing it would make the person callable again, "
            "which is the opposite of what suppression is for. The entry records a "
            "number and a scope, and nothing else about the person."
        ),
        authority="Hard rule 5 (DNC additions propagate before the next dispatch tick).",
    ),
)


@dataclass(frozen=True, slots=True)
class DeletionRequestRecord:
    """One erasure request, in the form that may leave the building.

    Carries `subject_ref` and never `phone_e164`: an OPEN row keeps the number so the
    worker can locate the subject, but a status page is read by more people than the
    request was filed by, and the audit trail must not become an index of who exercised
    a right (hard rule 6). Once the erasure has run the row has no number left to leak
    (migration f4a8e1c07b62) and `subject_ref` is the only handle there is — which is why
    it is READ from the row rather than re-derived from a column that is by then NULL.
    """

    id: UUID
    subject_ref: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    proof: dict[str, Any] | None
    # True when this request already existed and was returned instead of a new one.
    already_open: bool = False


def _record(row: Any, *, already_open: bool) -> DeletionRequestRecord:
    """Build the record from `id, requested_at, completed_at, proof, subject_ref`."""
    completed_at = row[2]
    return DeletionRequestRecord(
        id=row[0],
        subject_ref=str(row[4]),
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
                "SELECT id, requested_at, completed_at, proof, subject_ref "
                "FROM deletion_requests "
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
        return _record(existing, already_open=True)

    request_id = uuid7()
    # `subject_ref` is written at insert time, not derived at read time: the number is
    # cleared when the erasure completes (migration f4a8e1c07b62) and the hash is what
    # remains to answer "have we already erased this person?".
    inserted = (
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, scope, "
                "requested_at, created_at) VALUES (:id, :tid, :phone, :ref, :scope, now(), now()) "
                "RETURNING id, requested_at, completed_at, proof, subject_ref"
            ),
            {
                "id": request_id,
                "tid": tenant_id,
                "phone": phone_e164,
                "ref": subject_ref(phone_e164),
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
    return _record(inserted, already_open=False)


async def get_request(session: AsyncSession, *, request_id: UUID) -> DeletionRequestRecord:
    """The status of one request, including the proof certificate once it exists.

    RLS scopes the lookup, so another tenant's request is simply not found — which is
    also the answer a nonexistent id gets, deliberately (`ProblemError.not_found`).

    Reads `subject_ref` and never `phone_e164`: a completed request no longer holds a
    number, and a status read has no business selecting one when it does.
    """
    row = (
        await session.execute(
            text(
                "SELECT id, requested_at, completed_at, proof, subject_ref "
                "FROM deletion_requests WHERE id = :rid"
            ),
            {"rid": request_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Deletion request")
    return _record(row, already_open=False)


__all__ = [
    "DELETION_JOB",
    "DELETION_QUEUE",
    "DELETION_SCOPE",
    "ERASURE_EXCEPTIONS",
    "ERASURE_LIMITATIONS",
    "FLOOR_COUNT_KEY",
    "FLOOR_OUTCOME",
    "RECORDING_FLOOR_DAYS",
    "STATUS_COMPLETED",
    "STATUS_PENDING",
    "DeletionRequestRecord",
    "ErasureLimitation",
    "get_request",
    "request_erasure",
]
