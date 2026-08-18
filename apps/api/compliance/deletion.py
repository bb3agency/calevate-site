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

---

**A second gap, disclosed and then closed on both halves it owned: the knowledge base.**

Migration `842ba923796d` created `kb_sources`/`kb_documents` and said that provider-side
ids live in `kb_documents.meta`, "which is also what lets a DPDP erasure prove it removed
both copies" — prose that `kb/models.py`, `kb/service.py`, DATA-MODEL §7 and BUILD-LOG
§18 all repeat. For a long time no erasure removed either copy and no retention period
reached them: this module's worker did not name those tables, nothing in the repository
deleted a `kb_documents` row (publishing a new version archives the old `kb_sources` row
and leaves its chunks intact), and `retention_policies.data_category` admitted only
`recording|transcript|lead|consent_log`. A client's uploaded knowledge was kept
indefinitely, every version of it, and the certificate's only honest move was to say so
(`KB_OUTCOME = "not_searched"`).

D-179 closes the two halves that were engineering rather than judgement, and the entry is
now a NARROWER limitation than it was — which is the direction SEC-COMP §4 does not permit
lightly, so both halves are mechanisms and not wording:

* **A clock.** `retention_policies.data_category` gained `kb` (migration c4d1f7b83e26).
  The nightly sweep deletes SUPERSEDED and REJECTED versions past the tenant's TTL, never
  the live one, and never one the engine still holds a handle for.
* **A search.** `execute_deletion_request` now looks for the subject's number in the
  tenant's knowledge documents — digits-normalised, because a client pastes "98765 43210"
  and never an E.164 string — and records the count in the proof.

What is still NOT done, and the register says it in the words a data principal reads: the
content is not CHANGED. Deleting a line out of a live price list would silently change
what the agent says on the next call, we cannot tell a caller's callback number from the
shop's own landline, and the voice platform holds its own copy of the live version. So the
certificate hands the client a number and names the manual step, which is a task rather
than the shrug "not searched" was. `tests/kb_retention_test.py` holds all of it.

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

from collections.abc import Iterable
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

# The key the erasure job writes into the stored proof's `scope`: how many recordings
# this request collided with the floor over. Spelled the same in both halves —
# `apps.workers.retention.FLOOR_COUNT_KEY` duplicates it deliberately (neither package
# imports the other), and the tests on each side pin the two spellings together.
#
# ABSENT IS NOT ZERO on this field, and the distinction is the whole reason it is
# nullable. A recorded `0` is the claim "no recording was inside the window"; a MISSING
# key means the proof was written before the job recorded it, and hard rule 4 forbids
# back-filling those rows to say otherwise. So the certificate reports the two states in
# different words — see `deletion_proof._floor_sentence`.
FLOOR_COUNT_KEY: Final = "recordings_within_trai_floor"

# The other two facts the proof records about the audio, duplicated from
# `apps.workers.retention` for the reason above and pinned to it by
# `tests/recording_erasure_test.py`:
#
#   `recordings_destroyed`   how many audio files the request actually destroyed — the
#                            ones past the floor, where no law required their retention.
#   `recording_hold_until`   the ISO instant the LAST deferred one is destroyed on, or
#                            null when nothing was deferred.
#
# ABSENT IS NOT ZERO on both, for the same reason it is not zero on the floor count: no
# proof written before the recording bytes were reachable carries them, and hard rule 4
# forbids back-filling those rows.
DESTROYED_COUNT_KEY: Final = "recordings_destroyed"
HOLD_UNTIL_KEY: Final = "recording_hold_until"

# The one exception the floor count belongs to. Matched on the outcome rather than on a
# list index so that reordering the register cannot silently attach the count to the
# wrong statement.
FLOOR_OUTCOME: Final = "retained_under_legal_floor"

# The knowledge-base entry's outcome, for the same reason: `tests/kb_retention_test`
# finds it by verdict, not by position. It was `not_searched` until D-179 and is now
# `searched_not_erased`, which is a NARROWER limitation and therefore had to be earned
# rather than reworded: the erasure now runs a digits-normalised search of the tenant's
# knowledge documents for the subject's number and reports the count, and what it still
# does not do is CHANGE that content. See the register entry for what the client is told
# and `retention._search_knowledge_base` for why deleting would be the wrong move.
KB_OUTCOME: Final = "searched_not_erased"

# How many knowledge documents mentioned the subject, as the worker records it in the
# proof's `scope`. Duplicated from `apps.workers.retention.KB_MATCH_KEY` exactly as the
# three keys above are, and pinned to it by `tests/kb_retention_test.py`.
#
# ABSENT IS NOT ZERO, and here the distinction is load-bearing in a way it is not
# elsewhere: every proof written before D-179 carries no key at all, and rendering that
# as `0` would tell a data principal "we searched your client's knowledge base and found
# nothing" about an erasure that never searched it.
KB_MATCH_KEY: Final = "knowledge_base_documents_matched"

#: A backup taken before the erasure still holds the record until the window closes. Its
#: own outcome word rather than `retained_as_record`: nothing is being KEPT here as a
#: matter of policy — the record is gone from every live system, and what remains is a
#: bounded lag in a medium that must not be edited. A client reading the certificate
#: needs to tell "we hold this deliberately" from "this expires shortly".
BACKUP_OUTCOME: Final = "expires_with_backup"


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


#: How long a backup can still contain a record this request erased.
#:
#: NOT a policy set here — it is `infra/backup/README.md` §"Retention", where BOTH arms
#: (R2 point-in-time via `wal-g delete retain FULL 35`, and the offsite dumps via
#: `rclone delete --min-age 35d`) are pruned on the same clock. That file already reasons
#: about this exact consequence: "every extra day of retention is an extra day in which an
#: erasure request cannot fully reach our data", and 35 is the smallest window that still
#: covers the longest routine reason to restore.
#:
#: It is a constant HERE because the certificate now states it to a data principal, and a
#: number quoted in prose that must match an ops runbook is the drift class D-103 exists
#: for. If the runbook's window changes, this changes with it.
BACKUP_WINDOW_DAYS = 35


# What the erasure does NOT do. Shipped with every response on this surface AND written
# into the certificate itself (`deletion_proof.certificate`), because the client forwards
# the certificate to a data principal and a document that quietly overclaims is the
# failure mode DPDP's "erasure with proof" wording exists to prevent.
#
# Index-aligned with `ERASURE_EXCEPTIONS` below. Adding a limitation means adding both.
ERASURE_LIMITATIONS: tuple[str, ...] = (
    "Call recordings: the pointer to the audio is cleared immediately, so nothing in "
    "this system can reach, play or export it. The audio files themselves are destroyed "
    "by this request too, EXCEPT any that are still inside the "
    f"{RECORDING_FLOOR_DAYS}-day period Indian telecom rules require call recordings to "
    "be retained for (SECURITY-COMPLIANCE §1). Those are not destroyed early and they "
    "are not kept indefinitely either: each one is scheduled, and the certificate states "
    "the date the last of them is destroyed on. SECURITY-COMPLIANCE §4 describes erasure "
    "as covering recordings and §1 requires the retention period; whether an under-age "
    "recording should be destroyed on request ANYWAY is an open decision, and this "
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
    "The knowledge base is SEARCHED by this request but never changed. The knowledge "
    "sources a client uploads for their agents — FAQs, price lists, staff and contact "
    "details — are content they wrote rather than a record of a caller, so this request "
    "reads them for the number and reports how many documents mention it, and stops "
    "there: removing a line from a live price list would change what the agent says on "
    "the next call, and the voice platform holds its own copy of the same source. So if "
    "the count below is not zero, removing this person from that content is a manual "
    "step on both copies. Superseded versions are no longer kept for ever — every "
    "version this client has replaced or had rejected is deleted once it passes their "
    "knowledge-base retention period — but the version currently live is kept for as "
    "long as it is live.",
    "Backups: this erasure runs against the live systems, and a backup taken BEFORE it "
    f"still contains the erased records until that backup ages out — up to "
    f"{BACKUP_WINDOW_DAYS} days. Backups are never searched or edited to remove one "
    "person: a backup that has been rewritten is no longer a backup, and the ability to "
    "restore is itself a protection this data depends on. Nothing reads a backup in "
    "normal operation. If one is ever restored, the erasure is re-applied to the "
    "restored copy as part of the restore.",
)

# The same register, structured, and the half that rides the CERTIFICATE. Prose is what
# a person reads; these are what a regulator can tabulate and what a machine can check.
# Index-aligned with `ERASURE_LIMITATIONS` — see `ErasureLimitation.keyword`.
ERASURE_EXCEPTIONS: tuple[ErasureLimitation, ...] = (
    ErasureLimitation(
        what="Audio recordings still inside their mandatory retention period.",
        keyword="recording",
        outcome=FLOOR_OUTCOME,
        why=(
            "The link this system held to every recording was cleared, so nothing in "
            "Calevate can play, download or export any of them. The audio files were "
            "destroyed as well — except those less than "
            f"{RECORDING_FLOOR_DAYS} days old, which Indian telecom rules require to be "
            "kept for that long. Those are not destroyed early. They are also not kept: "
            "each one has a destruction date fixed at the moment this request ran, and "
            "the audio is deleted automatically on that date without a second request."
        ),
        authority=(
            f"The {RECORDING_FLOOR_DAYS}-day recording-retention floor "
            "(SECURITY-COMPLIANCE §1) read against the erasure duty in DPDP §12(3), "
            "which requires erasure 'unless retention of the same is necessary for the "
            "specified purpose or for compliance with any law for the time being in "
            "force'. A retention obligation therefore DEFERS an erasure rather than "
            "cancelling it, and DPDP §8(7)'s storage limitation makes keeping the data "
            "beyond that obligation a breach in itself — which is why the deferral is a "
            "scheduled destruction and not an exemption. Whether an under-age recording "
            "should be destroyed on request anyway is an open decision recorded in "
            "SECURITY-COMPLIANCE §4; until it is taken the pointer is cleared at every "
            "age and no under-age audio is destroyed early."
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
    ErasureLimitation(
        what="The knowledge base this client's agents answer from.",
        keyword="knowledge base",
        outcome=KB_OUTCOME,
        why=(
            "A knowledge base is content the client uploaded for their agents to quote — "
            "FAQs, price lists, staff and contact details — rather than a record of a "
            "caller. This request SEARCHES it for the number and reports what it found; "
            "it does not change it. Editing a live knowledge document would change what "
            "the agent says on the next call, and the voice platform holds its own copy "
            "of the same source, so a removal has to be made on both by a person who can "
            "see what the sentence is for. Versions the client has replaced or had "
            "rejected are no longer kept indefinitely: they are deleted once they pass "
            "this account's knowledge-base retention period. The live version is kept "
            "while it is live."
        ),
        authority=(
            "SECURITY-COMPLIANCE §4 enumerates the erasure scope as calls, transcript "
            "turns, extracted fields, leads and recordings — knowledge-base content is "
            "not in it, and D-179 closed the two halves of that gap that were ours: "
            "DATA-MODEL §9's retention categories now include `kb`, which expires "
            "superseded versions, and this request searches the rest. What is left is a "
            "judgement about the client's own words, which is theirs to make."
        ),
    ),
    ErasureLimitation(
        what="Backup copies taken before this erasure ran.",
        keyword="backup",
        outcome=BACKUP_OUTCOME,
        why=(
            "This erasure runs against the live systems. A backup taken before it still "
            "holds the erased records until that backup ages out, which takes up to "
            f"{BACKUP_WINDOW_DAYS} days. Backups are deliberately never searched or "
            "edited to remove one person: a backup that has been rewritten can no "
            "longer be trusted to restore anything, and being able to restore is itself "
            "a protection this data depends on. Nothing reads a backup in normal "
            "operation, and if one is ever restored the erasure is re-applied to the "
            "restored copy as part of the restore."
        ),
        authority=(
            "DPDP §8(7)'s storage limitation read against §8(5)'s duty to keep "
            "reasonable security safeguards: a backup window is a safeguard, and the "
            "erasure is completed rather than cancelled by it — which is why the window "
            "is bounded and stated rather than open-ended. The number is "
            "`infra/backup/README.md`'s retention section, where both arms prune on the "
            "same clock and the file's own reasoning names this consequence: 'every "
            "extra day of retention is an extra day in which an erasure request cannot "
            "fully reach our data.'"
        ),
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


@dataclass(frozen=True, slots=True)
class DeletionRequestSummary:
    """One erasure request as it appears in a LIST, which is a different disclosure from
    one request read by someone who already holds its id.

    Deliberately NOT `DeletionRequestRecord` with `proof=None`: on that record `None`
    means "no certificate was written", and a list that says so about every row would be
    telling a client their completed erasures produced no proof. `has_certificate` is the
    honest form of the same fact and costs a `proof IS NOT NULL` rather than shipping
    every certificate on the account to render an index.
    """

    id: UUID
    subject_ref: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    has_certificate: bool


# A list nobody paginates is a list that silently truncates, so the ceiling is stated
# and the caller can tell "this is all of them" from "this is the first page": the API
# returns at most this many and the screen compares the count it got against the limit it
# asked for. An offset is deliberately not offered yet — an account with more than 500
# open erasure obligations has a problem no pagination control solves.
MAX_LIST: Final = 500


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


async def refile_erasure_for_late_records(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, phones: Iterable[str | None]
) -> UUID | None:
    """The subject's instruction outlives the certificate: re-file it for a call whose
    records arrived AFTER the erasure ran (D-310).

    THE DEFECT THIS CLOSES, measured rather than argued
    (`tests/erasure_late_arrival_test.py`). `execute_deletion_request` erases what exists
    when it runs. A call that was still IN FLIGHT when the request executed has almost
    nothing yet — the `calls` row and nothing else — so the erasure clears its numbers,
    writes the proof, and the client hands the data principal a certificate. The call
    then ends and the ordinary post-call pipeline writes the transcript verbatim, the
    extraction, the summary, the recording, the archived vendor document and a `leads`
    row carrying the very number the certificate says was erased. No replay, no poller,
    no adversary: the two are simply concurrent, and the erasure had no way to reach
    forward. Everything the certificate asserts becomes false within the pipeline's
    two-minute SLO, and nothing anywhere reports it.

    THE BOUNDARY IS THE CALL'S OWN START, and it is the whole rule. A completed erasure
    covers a call that had already STARTED when the erasure executed, whenever that
    call's records land. It does NOT cover a call the same person places next month:
    `request_erasure`'s own docstring says erasure is not a terminal state for a phone
    number, and treating it as one would silently destroy records the person's later
    call lawfully created. Expressed as `completed_at >= COALESCE(started_at,
    created_at)` in one statement over two RLS-scoped tables, so no clock arithmetic
    happens in Python and no second definition of "covered" can drift from this one.

    WHY RE-FILE RATHER THAN ERASE IN PLACE. A second erasure of one subject is exactly
    what `deletion_requests` is: filing one reuses the whole mechanism — the worker, the
    object-store arms, the recording floor holds — instead of adding a second, thinner
    copy of the erase statements that would then have to be kept in step (CLAUDE.md: one
    way per problem). It also produces the artefact the data principal is owed: a second
    proof, stating what the late records were and when they went. Amending the first
    proof was rejected — it has already been handed on, and a certificate that changes
    after the fact is not evidence.

    Returns the request id when one was filed or was already open, else `None`. Does not
    commit: the caller's transaction owns the row and the outbox job together, which is
    the property `request_erasure` is built on.
    """
    candidates = sorted({phone for phone in phones if phone})
    if not candidates:
        return None
    covering = (
        await session.execute(
            text(
                "SELECT d.id FROM deletion_requests d, calls c "
                "WHERE c.id = :cid AND d.subject_ref = ANY(:refs) "
                "AND d.completed_at IS NOT NULL "
                "AND d.completed_at >= COALESCE(c.started_at, c.created_at) "
                "ORDER BY d.completed_at DESC LIMIT 1"
            ),
            {"cid": call_id, "refs": [subject_ref(phone) for phone in candidates]},
        )
    ).first()
    if covering is None:
        return None
    # WHICH of the two numbers was erased is a fact we hold, so it is read back rather
    # than guessed: re-filing for the business's own line would erase the wrong subject.
    erased = {
        str(row[0])
        for row in (
            await session.execute(
                text("SELECT subject_ref FROM deletion_requests WHERE id = :rid"),
                {"rid": covering[0]},
            )
        ).all()
    }
    subject = next((phone for phone in candidates if subject_ref(phone) in erased), None)
    if subject is None:  # pragma: no cover - the covering row was selected by these refs
        return None
    record = await request_erasure(session, tenant_id=tenant_id, phone_e164=subject)
    # Ids and hashes only (hard rule 6). `covered_by` is what makes this legible in an
    # incident: it names the certificate the late records made incomplete.
    log.warning(
        "deletion_refiled_for_late_records",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "covered_by": str(covering[0]),
            "request_id": str(record.id),
        },
    )
    return record.id


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


async def list_requests(session: AsyncSession, *, limit: int = 100) -> list[DeletionRequestSummary]:
    """Every erasure request this tenant has filed, newest first.

    The gap this closes: a filed request was reachable only by its opaque id, so a client
    who closed the tab lost the handle on an in-flight legal obligation that has a
    statutory clock running on it. "Which erasures do I owe an answer on?" is a question
    the fiduciary has to be able to ask of their own account.

    **`phone_e164` is not selected.** An OPEN row still carries the number (the worker has
    to be able to find the subject), so a list is precisely where it would leak in bulk:
    one read would return every number this account has been asked to erase — a ready-made
    index of the people who exercised the right. `subject_ref` is what a list may carry,
    and the column is not even named in the query so a later edit cannot widen it by
    accident (the same construction `export.py` uses to keep raw `text` out of reach).

    `subject_ref` is pseudonymous, NOT anonymous, and the difference is worth stating
    where someone might rely on it: the Indian mobile space is small enough to enumerate,
    so a hash confirms a number to a reader who already has one in mind rather than
    hiding it from a determined one. That is exactly what it is for here — the client
    matching their own case file to a row — and it is why this stays behind `org:read`
    and out of every log line, instead of being treated as safe to publish.

    RLS scopes the query (hard rule 1): there is no `tenant_id` predicate because the
    session's transaction carries `app.tenant_id`, the same contract the rest of this
    module and `crm/service.py` document. `tests/deletion_request_test.py` proves the
    zero-rows case across tenants rather than trusting it.

    Not audited, for the same reason the single-request read is not: it discloses no
    personal data, it is the question support is asked most often, and an audit chain that
    grows a row per page view stops being readable.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, requested_at, completed_at, (proof IS NOT NULL), subject_ref "
                "FROM deletion_requests ORDER BY requested_at DESC, id DESC LIMIT :n"
            ),
            {"n": min(limit, MAX_LIST)},
        )
    ).all()
    return [
        DeletionRequestSummary(
            id=row[0],
            subject_ref=str(row[4]),
            status=STATUS_PENDING if row[2] is None else STATUS_COMPLETED,
            requested_at=row[1],
            completed_at=row[2],
            has_certificate=bool(row[3]),
        )
        for row in rows
    ]


__all__ = [
    "BACKUP_OUTCOME",
    "BACKUP_WINDOW_DAYS",
    "DELETION_JOB",
    "DELETION_SCOPE",
    "ERASURE_EXCEPTIONS",
    "ERASURE_LIMITATIONS",
    "FLOOR_COUNT_KEY",
    "FLOOR_OUTCOME",
    "KB_MATCH_KEY",
    "KB_OUTCOME",
    "MAX_LIST",
    "RECORDING_FLOOR_DAYS",
    "STATUS_COMPLETED",
    "STATUS_PENDING",
    "DeletionRequestRecord",
    "DeletionRequestSummary",
    "ErasureLimitation",
    "get_request",
    "list_requests",
    "refile_erasure_for_late_records",
    "request_erasure",
]
