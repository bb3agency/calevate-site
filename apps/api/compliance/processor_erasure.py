"""The record of an erasure obligation we cannot discharge in code (D-433).

**The hole this fills.** `execute_deletion_request` erases a data principal from our
Postgres and our object storage and writes a certificate. Vendors that handled the call
keep copies this system cannot delete: the telephone carrier documents no route of ours
that deletes a call record, and the speech and language vendors publish no per-subject
deletion either.

So for a per-subject erasure there is no API to call, and the obligation does not go away
because there is no API to call. What is left is a written request to the vendor — a thing
a human does — and the failure mode of a human obligation with no record is that it is
believed to have happened. That is the defect class this repo cares most about: a control
that reports success for work it did not do.

**What this module is, and the three things it deliberately is not.**

It is a TASK LIST with a clock. One row per (erasure request x processor that holds a copy
we could not reach). It is opened automatically by the erasure worker so nobody has to
remember, it is closed by a human recording what the vendor actually said, and it goes
overdue loudly.

1. **It is not a workflow engine.** Four states, one forward direction, no branching, no
   assignment, no escalation ladder. `open → requested → confirmed | refused`. Anything
   more would be a product nobody asked for standing between an operator and an email.
2. **It does not send anything.** The same reasoning `scripts/breach_notice.py` records:
   a tool that can mail a vendor on behalf of a compliance obligation is a blast radius
   rather than a control, and the wording of a deletion demand is a human's to write.
3. **It is not append-only, and that is deliberate.** Hard rule 4's ledgers are evidence
   that something WAS true at an instant. This is a task whose whole purpose is to change
   state — an append-only version would need a second table to answer "is it done?", which
   is the one question it exists to answer. The audit trail of the transitions is
   `audit_log`, which already is append-only and already covers this actor.

**Hard rule 6, and the near-miss that shapes the schema.** A row here must be enough for
an operator to write the vendor a specific, actionable request — "delete these executions"
— without ever holding the caller's number. So:

* `subject_ref` is the sha256 hash the certificate already carries, never `phone_e164`.
  It is what lets an operator holding the number confirm they are looking at the right
  task, and tells anyone who does not hold the number nothing.
* `vendor_refs` carries OPAQUE VENDOR IDENTIFIERS ONLY — execution ids and agent ids, the
  strings the vendor itself minted. They are the thing the vendor needs quoted back to
  act, they name no person, and they are exactly what `alarm-index.md` already tells an
  operator to quote at that support desk. Nothing derived from a phone number, no
  transcript text, no name, ever goes in this column.

That distinction is not theoretical here: a defect was fixed the night before this module
was written in which the consent ledger's evidence field was storing raw phone numbers.
The column is JSONB and would accept anything; `assert_vendor_refs_are_id_shaped` is what
makes the rule enforceable rather than aspirational.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from calevate_shared.engine import tenant_of_pipecat_ref
from calevate_shared.engine_scope import raw_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.deletion import RECORDING_FLOOR_DAYS
from apps.api.db.base import uuid7

__all__ = [
    "CALL_CLOCK_SQL",
    "CALL_COPY_SAFE_SQL",
    "CONTACT_HELD",
    "CONTACT_NOT_ASKED",
    "HELD_UNTIL_SQL",
    "NOT_HELD_SQL",
    "OVERDUE_AFTER_DAYS",
    "OWN_RUNTIME_ENGINES",
    "PROCESSORS",
    "STATUSES",
    "VOICE_PLATFORM_CONTENT_AND_CONTACT_DELETION",
    "VOICE_PLATFORM_CONTENT_AND_CONTACT_SENTENCE",
    "VOICE_PLATFORM_CONTENT_DELETION",
    "VOICE_PLATFORM_CONTENT_DELETION_SENTENCE",
    "VOICE_PLATFORM_DELETING_ENGINES",
    "VOICE_PLATFORM_ERASURE_REQUESTED",
    "VOICE_PLATFORM_ERASURE_SENTENCE",
    "VOICE_PLATFORM_RETAINED",
    "VOICE_PLATFORM_RETAINED_SENTENCE",
    "VOICE_PLATFORM_TENANT_CONTENT_SENTENCE",
    "ProcessorErasureTask",
    "VendorRefRejectedError",
    "assert_vendor_refs_are_id_shaped",
    "engine_held_call_refs",
    "held_contact_erasures",
    "held_contacts",
    "mark_task_requested",
    "open_tasks_for_request",
    "overdue_tasks",
    "record_answer",
    "record_contact_erased",
    "record_engine_contact_progress",
    "record_request_sent",
    "settle_voice_engine_task",
    "settled_tasks",
]

#: The processors that hold call content and publish no subject-granular deletion.
#:
#: A CLOSED vocabulary rather than free text, because the register in `deletion.py` names
#: exactly these and a vendor's name written in their place would silently create a task
#: nobody's runbook covers. Adding a processor means adding it here, to the register, and to
#: `docs/evidence/subprocessor-erasure-reach.md` §3 — three edits, on purpose.
#:
#: They are named by ROLE and not by vendor. The vendor is a config choice (D-31 has an
#: engine port, D-36 a speech tier, D-410 a model leg); the obligation attaches to the
#: role, and a row written today must still be readable after a vendor swap.
#:
#: `telephony` is the carrier, where the call's audio terminates, so it holds the numbers,
#: its call records and the sound of the call. Calls placed on our former carrier leg carry
#: its call ids (`calls.carrier_call_id`) and recording ids (`calls.carrier_recording_id`),
#: and both erasures quote them in a `telephony` task; the "telephone carrier" entry in
#: `deletion.ERASURE_EXCEPTIONS` is the certificate's side of the same obligation.
#:
#: `voice_engine` is a third-party platform that ran the call and holds its own execution
#: record. Calls our former owned runtime ran (`OWN_RUNTIME_ENGINES`) have no such record to
#: ask for: the call row, the turns and the outcome are ours and the erasure reaches them.
PROCESSORS: Final = ("voice_engine", "speech", "llm", "telephony")

#: The former owned-runtime engine, whose refs (`pipecat:<tenant>:<id>`, `pckb_<digest>`)
#: still sit on historical call rows and name rows in OUR database rather than objects at a
#: vendor. Quoting them in a vendor request would ask a vendor to delete something it never
#: held — and the `pipecat:` refs are not id-shaped, so the task INSERT would raise and take
#: the whole erasure down with it.
OWN_RUNTIME_ENGINES: Final = frozenset({"pipecat"})

#: `open` — the erasure ran, this processor holds a copy, nobody has asked yet.
#: `requested` — a human sent the written request; `requested_at` says when.
#: `confirmed` — the vendor confirmed deletion in writing.
#: `refused` — the vendor declined, or said it cannot. A terminal state that is NOT a
#: failure of this system, and must be visible as such: it is the fact that makes the
#: contract clause (OPERATIONS §2 gate 36) urgent rather than tidy.
STATUSES: Final = ("open", "requested", "confirmed", "refused")

#: How long an unanswered task may sit before `processor_erasure_overdue` pages.
#:
#: 30 days is not a number chosen for comfort: it is the period the DPA clause we are
#: seeking demands of the vendor (`docs/evidence/subprocessor-erasure-reach.md` §6), and
#: DPDP Rule 13(2) gives a Data Fiduciary a comparable window to act on a principal's
#: request. An alarm that fires later than the obligation it guards is decoration.
OVERDUE_AFTER_DAYS: Final = 30

#: A call (alias `c`) whose recording the voice platform cannot hold the only copy of: we
#: hold the AI leg's audio ourselves (its pointer, or an erasure's hold on it, since an
#: erasure clears the pointer first), or the call never connected. A call outside this
#: waits for `deletion.RECORDING_FLOOR_DAYS` past `CALL_CLOCK_SQL` before the platform's
#: copy may go (D-803's `engine_content._READY_SQL`, D-810's contact hold).
CALL_COPY_SAFE_SQL: Final = (
    "(c.recording_url IS NOT NULL "
    "OR c.status IN ('failed', 'no_answer', 'busy') "
    "OR EXISTS (SELECT 1 FROM recording_erasure_holds h WHERE h.call_id = c.id "
    "AND h.object_key NOT LIKE '%-transfer.wav'))"
)
#: The call's clock, `workers/retention._call_clock`'s, spelled here because the API does
#: not import the worker.
CALL_CLOCK_SQL: Final = (
    "COALESCE(c.ended_at, c.created_at + make_interval(secs => COALESCE(c.duration_s, 0)))"
)

#: The instant a `voice_engine` task (alias `t`) stops waiting for our own recording copy:
#: the latest floor date among the calls it names that are not `CALL_COPY_SAFE_SQL`. NULL
#: for a task that waits on none, and for every other processor. Takes `:floor`.
HELD_UNTIL_SQL: Final = (
    f"(SELECT max({CALL_CLOCK_SQL}) + make_interval(days => :floor) FROM calls c "
    "WHERE t.processor = 'voice_engine' "
    "AND split_part(c.engine_call_id, '@', 1) IN "
    "(SELECT jsonb_array_elements_text(t.vendor_refs)) "
    f"AND NOT {CALL_COPY_SAFE_SQL})"
)

#: Whether a task (alias `t`) may count as overdue at all: it is not waiting by design for
#: a recording floor still to pass. A task an erasure holds for our copy (D-803's content
#: deletion, D-810's contact DELETE) goes on its own once the copy lands or the floor
#: passes, so paging for it before then would ask an operator to do nothing, daily, for up
#: to 60 days; one still open after its floor date is stuck and counts. Takes `:floor`. The
#: alarm (`workers/dispatcher`) and `overdue_tasks` share it, so the page and the
#: operator's list agree.
NOT_HELD_SQL: Final = f"COALESCE({HELD_UNTIL_SQL}, '-infinity'::timestamptz) <= now()"

# An opaque vendor identifier: uuids, the vendor's own prefixed ids, Twilio-shaped SIDs.
# Deliberately NOT permissive — the point is to REFUSE anything that could be a phone
# number, a name or a sentence, so the character class excludes '+', spaces and every
# separator a number is ever written with, and the length is bounded well below prose.
_ID_SHAPED = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# An element that is ENTIRELY digits is a phone number wearing an id's clothes:
# "919876543210" passes the character class above. Checked separately from the shape so
# the refusal can say which rule was broken.
#
# "Entirely digits" and NOT "contains a digit run", which is what this was first written
# as. That version rejected a real execution id — `b7140255-af33-4608-8e97-04dd944b8e48`
# contains "7140255" — so it would have refused legitimate tasks. A uuid always carries a
# hyphen or a letter; a bare number never does. The DB CHECK
# `vendor_refs_carry_no_phone_number` is anchored on the same rule.
_BARE_NUMBER = re.compile(r"^\d{7,}$")


class VendorRefRejectedError(ValueError):
    """A value offered as a vendor reference is not id-shaped (hard rule 6).

    Raised rather than filtered. Dropping the offending entry would leave a task that
    silently names fewer executions than the erasure found, and an operator would send
    the vendor an incomplete list believing it complete.
    """


def assert_vendor_refs_are_id_shaped(refs: list[str]) -> None:
    """Refuse to store anything that is not an opaque vendor identifier.

    The whole hard-rule-6 surface of this table is one JSONB column, so this is the one
    place it can be enforced. Called by every writer.
    """
    for ref in refs:
        if not _ID_SHAPED.match(ref):
            raise VendorRefRejectedError(
                "vendor_refs takes opaque vendor identifiers only; "
                f"{len(ref)}-char value is not id-shaped"
            )
        if _BARE_NUMBER.match(ref):
            raise VendorRefRejectedError(
                "vendor_refs value is entirely digits — that is a phone number shape, "
                "and hard rule 6 forbids it on this table. If a vendor really mints "
                "all-digit ids, it is indistinguishable from a number here and needs a "
                "prefix before it can be stored."
            )


#: Engines that delete one call's content at our request (D-798). ThinnestAI's
#: `DELETE /calls/{id}/content` removes a call's recording (its own, the carrier's and any
#: training copy), its transcript turns, summary and collected fields, and keeps only the
#: billing record (`thinnest-findings/mirror/snapshots/2026-10-15/pages/api-reference/
#: post-call/delete-call-content.md:443-533`). A call row belongs to one tenant, so it is
#: asked in whichever workspace holds the call, our developer workspace included
#: (`workers/engine_customer_data.delete_engine_call_content`). Its contact erasure,
#: `DELETE /contacts/{id}`, still acts on a whole workspace and is asked only in the
#: client's own (D-691).
VOICE_PLATFORM_DELETING_ENGINES: Final = frozenset({"thinnest"})

#: The proof's `engine_deletion` for an erasure whose calls' content was asked deleted at
#: the voice platform, in a workspace shared with other businesses where the person's
#: contact entry is not erased. Durable wire tokens (hard rule 4): never renamed once
#: written.
VOICE_PLATFORM_CONTENT_DELETION: Final = "call_content_deletion_requested"
VOICE_PLATFORM_CONTENT_DELETION_SENTENCE: Final = (
    "deletion of each call's recording, transcript, summary and collected details requested "
    "at the voice platform; the platform's contact entry for this number is shared with "
    "other businesses there and is not deleted; the outcome is recorded on the erasure task"
)
#: The same in the client's own workspace, where the contact is erased too.
VOICE_PLATFORM_CONTENT_AND_CONTACT_DELETION: Final = "call_content_and_contact_erasure_requested"
VOICE_PLATFORM_CONTENT_AND_CONTACT_SENTENCE: Final = (
    "deletion of each call's recording, transcript, summary and collected details, and "
    "erasure of this person's contact in the voice platform workspace held for this "
    "business, requested; the outcome is recorded on the erasure task"
)

#: A tenant erasure's sentence for the calls the platform holds for the client.
VOICE_PLATFORM_TENANT_CONTENT_SENTENCE: Final = (
    "deletion of each call's recording, transcript, summary and collected details requested "
    "at the voice platform"
)

#: Tokens and sentences proofs issued before D-798 carry: before the platform deleted one
#: call, an erasure either left its copy to expire with the plan's retention or erased the
#: contact in the client's own workspace. Read by the certificate renderers for those
#: proofs; nothing new writes them.
VOICE_PLATFORM_RETAINED: Final = "not_deleted_expires_with_plan_retention"
VOICE_PLATFORM_RETAINED_SENTENCE: Final = (
    "not deleted at the voice platform; expires with its plan retention"
)
VOICE_PLATFORM_ERASURE_REQUESTED: Final = "contact_erasure_requested_in_client_workspace"
VOICE_PLATFORM_ERASURE_SENTENCE: Final = (
    "erasure of this person's contact requested in the voice platform workspace held for "
    "this business, recordings included; the outcome is recorded on the erasure task"
)

#: A `voice_engine` task's contact half when no contact erasure was asked (the tenant had
#: no workspace of its own), written where the per-contact progress otherwise goes.
CONTACT_NOT_ASKED: Final = "contact-not-asked"
#: What `record_engine_contact_progress` writes when the workspace held no contact.
_NO_CONTACT: Final = "no-contact"
#: A contact found and not yet asked deleted, written `<contact id>=held`: its DELETE waits
#: until we hold our own copy of every recording it would take (D-810,
#: `engine_content.calls_awaiting_our_copy`).
CONTACT_HELD: Final = "held"


def engine_held_call_refs(engine_call_ids: Iterable[str]) -> list[str]:
    """The vendor's own ids of the `calls.engine_call_id` values that name an execution at a
    third-party engine.

    `calls` carries no engine column, so the ref's own shape is the discriminator: an id our
    runtime minted parses to a tenant (`calevate_shared.engine.tenant_of_pipecat_ref`) and
    is dropped. A client workspace's handle is `<raw>@<org_…>` (D-693); the task quotes the
    raw id the vendor knows, which is also the only form `vendor_refs` accepts. Order is
    preserved so the task lists calls the way the erasure read them.
    """
    return [raw_of(ref) for ref in engine_call_ids if tenant_of_pipecat_ref(ref) is None]


@dataclass(frozen=True, slots=True)
class ProcessorErasureTask:
    """One outstanding vendor-side erasure obligation, in the form an operator reads."""

    id: UUID
    processor: str
    status: str
    subject_ref: str | None
    vendor_refs: list[str]
    days_open: int
    #: When the vendor answered, on a settled task. `None` while it is still outstanding.
    #: This is the fact a compliance officer needs before answering a data principal —
    #: "the platform confirmed deletion on this date" — and it is the reason `settled_tasks`
    #: exists rather than the answer being written and forgotten.
    answered_at: datetime | None = None
    #: The floor date a `voice_engine` task waits for before the platform's copy may go
    #: (`HELD_UNTIL_SQL`); `None` when it waits on nothing.
    held_until: datetime | None = None


async def open_tasks_for_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_ref: UUID,
    request_kind: str,
    subject_ref: str | None,
    vendor_refs: list[str],
    processors: tuple[str, ...] = PROCESSORS,
    vendor_reference: str | None = None,
) -> int:
    """Open one task per processor that holds a copy this erasure could not reach.

    `vendor_reference` starts the task's progress record where the opener already knows
    part of it (`CONTACT_NOT_ASKED`).

    Called from INSIDE the erasure's own transaction, so the tasks and the certificate
    commit together or not at all. That is the same argument `deletion.py` makes for
    writing the request row and the outbox job in one transaction: a certificate that
    tells a data principal "a written request will be made" while no task exists is a
    promise with no keeper, and it is worse than the certificate not saying it.

    Idempotent on `(request_ref, processor)` — the erasure job has a retry ladder, and a
    replay must not hand an operator the same vendor request twice.
    """
    assert_vendor_refs_are_id_shaped(vendor_refs)
    if request_kind not in ("subject", "tenant"):
        raise ValueError(f"unknown request_kind {request_kind!r}")

    # VALIDATED AS A SET, BEFORE THE LOOP, and that ordering is the whole point. This
    # check used to sit inside the loop, which meant a tuple like ("voice_engine",
    # "azure") opened the first task and THEN raised — some obligations filed, one lost,
    # and a caller holding an exception that does not say which. The docstring above is
    # right that our own callers run this inside the erasure's transaction, so a rollback
    # would undo the partial write; that is a promise about every caller forever, and it
    # is cheaper to make the function incapable of a partial application than to keep
    # requiring it. Sorted so the message is stable for a caller that passed a set.
    unknown = sorted(set(processors) - set(PROCESSORS))
    if unknown:
        raise ValueError(f"unknown processor {unknown[0]!r}")

    opened = 0
    for processor in processors:
        result = await session.execute(
            text(
                "INSERT INTO processor_erasure_tasks "
                "(id, tenant_id, request_ref, request_kind, processor, status, "
                " subject_ref, vendor_refs, vendor_reference) "
                "VALUES (:id, :tid, :ref, :kind, :proc, 'open', :subj, "
                "        CAST(:refs AS jsonb), :vref) "
                "ON CONFLICT (request_ref, processor) DO NOTHING "
                "RETURNING id"
            ),
            {
                "id": str(uuid7()),
                "tid": str(tenant_id),
                "ref": str(request_ref),
                "kind": request_kind,
                "proc": processor,
                "subj": subject_ref,
                "refs": _json_array(vendor_refs),
                "vref": vendor_reference,
            },
        )
        opened += len(result.fetchall())
    return opened


async def record_request_sent(
    session: AsyncSession, *, task_id: UUID, vendor_reference: str | None
) -> bool:
    """Record that a human sent the written deletion request. Returns False if not open.

    `vendor_reference` is the vendor's own ticket id where they gave one — the handle a
    follow-up quotes. Nullable, because a vendor who answers an email with an email gives
    no ticket id and inventing one would be worse than the gap.

    The guard is `status = 'open'` rather than a blind UPDATE so that re-running the
    operator command cannot silently reset the clock on a task somebody has already
    answered.
    """
    result = await session.execute(
        text(
            "UPDATE processor_erasure_tasks "
            "SET status = 'requested', requested_at = now(), "
            "    vendor_reference = :vref, updated_at = now() "
            "WHERE id = :tid AND status = 'open' RETURNING id"
        ),
        {"tid": str(task_id), "vref": vendor_reference},
    )
    return result.first() is not None


def _progress_of(reference: str | None) -> dict[str, int]:
    """`ct_a=2,ct_b=0` as `{contact id: recordings still pending}`; anything else, empty."""
    progress: dict[str, int] = {}
    for part in (reference or "").split(","):
        contact, sep, pending = part.partition("=")
        if sep and _ID_SHAPED.match(contact) and pending.isdigit():
            progress[contact] = int(pending)
    return progress


def held_contacts(reference: str | None) -> list[str]:
    """The contacts a task records as found and held back (`CONTACT_HELD`), sorted."""
    held: list[str] = []
    for part in (reference or "").split(","):
        contact, sep, mark = part.partition("=")
        if sep and _ID_SHAPED.match(contact) and mark == CONTACT_HELD:
            held.append(contact)
    return sorted(held)


async def record_engine_contact_progress(
    session: AsyncSession,
    *,
    task_id: UUID,
    progress: dict[str, int],
    held: Iterable[str] = (),
) -> dict[str, int]:
    """Merge one attempt's contact erasures into the task, and return everything known.

    A voice-platform contact erasure answers `recordingsPending` once, on the DELETE that
    removed the contact; a retry finds the contact gone and learns nothing (`thinnest-
    findings/mirror/snapshots/2026-10-08/pages/api-reference/contacts/delete-contact.md:7`).
    So each contact's count is kept on the task as `<contact id>=<pending>` the moment it is
    known, and an attempt's view is always this merged record, never its own. Contact ids
    only (hard rule 6).

    `held` records contacts found but not yet asked deleted; a count for one later replaces
    its mark. A write that asks something of the platform moves an open task to
    `requested`; a write of held contacts only does not, because nothing was asked."""
    held = list(held)
    assert_vendor_refs_are_id_shaped([*progress, *held])
    current = (
        await session.execute(
            text("SELECT vendor_reference FROM processor_erasure_tasks WHERE id = :tid FOR UPDATE"),
            {"tid": str(task_id)},
        )
    ).scalar()
    merged = {**_progress_of(current), **progress}
    entries: dict[str, str] = dict.fromkeys(set(held_contacts(current)) | set(held), CONTACT_HELD)
    entries.update({contact: str(n) for contact, n in merged.items()})
    await session.execute(
        text(
            "UPDATE processor_erasure_tasks SET vendor_reference = :vref, "
            "requested_at = CASE WHEN CAST(:asked AS boolean) "
            "THEN COALESCE(requested_at, now()) ELSE requested_at END, "
            "status = CASE WHEN CAST(:asked AS boolean) AND status = 'open' "
            "THEN 'requested' ELSE status END, "
            "updated_at = now() WHERE id = :tid"
        ),
        {
            "tid": str(task_id),
            "asked": not held,
            # "no-contact" when nothing was ever found: the vendor reference an operator reads.
            "vref": ",".join(f"{contact}={mark}" for contact, mark in sorted(entries.items()))
            or "no-contact",
        },
    )
    return merged


async def record_answer(
    session: AsyncSession, *, task_id: UUID, outcome: str, note: str | None
) -> bool:
    """Record what the vendor said. Returns False if the task was not awaiting an answer.

    `refused` is a first-class outcome and not an error. A vendor who says "we cannot
    delete one caller's executions" has told us the most important thing anyone will
    learn on this axis, and burying it in a failure path would lose it.
    """
    if outcome not in ("confirmed", "refused"):
        raise ValueError(f"outcome must be confirmed or refused, not {outcome!r}")
    result = await session.execute(
        text(
            "UPDATE processor_erasure_tasks "
            "SET status = :outcome, answered_at = now(), note = :note, "
            "    updated_at = now() "
            "WHERE id = :tid AND status = 'requested' RETURNING id"
        ),
        {"tid": str(task_id), "outcome": outcome, "note": note},
    )
    return result.first() is not None


async def mark_task_requested(session: AsyncSession, *, task_id: UUID) -> None:
    """Move an open task to `requested`: the voice platform has been asked by code."""
    await session.execute(
        text(
            "UPDATE processor_erasure_tasks SET status = 'requested', "
            "requested_at = COALESCE(requested_at, now()), updated_at = now() "
            "WHERE id = :tid AND status = 'open'"
        ),
        {"tid": str(task_id)},
    )


#: The calls a `voice_engine` task names whose content the platform has not yet confirmed
#: gone: not deleted, or deleted with recording files still queued. Matched on the vendor's
#: raw id, the form the task quotes (`engine_held_call_refs`); RLS keeps it to the tenant.
_CALLS_OWED_SQL: Final = (
    "SELECT count(*) FROM calls WHERE split_part(engine_call_id, '@', 1) = ANY(:refs) "
    "AND (engine_content_deleted_at IS NULL OR COALESCE(engine_content_recordings_pending, 0) > 0)"
)


def _contacts_settled(reference: str | None) -> bool:
    """The contact half of a `voice_engine` task is done: none was asked, the workspace held
    none, or every contact it erased reported its last recording gone. A contact still held
    back is not done."""
    if reference in (CONTACT_NOT_ASKED, _NO_CONTACT):
        return True
    if held_contacts(reference):
        return False
    progress = _progress_of(reference)
    return bool(progress) and all(pending == 0 for pending in progress.values())


async def settle_voice_engine_task(session: AsyncSession, *, task_id: UUID) -> bool:
    """Confirm a `voice_engine` task once both halves of the platform's erasure are done:
    every call it names has its content deleted with no recording left queued, and the
    contact half is settled (`_contacts_settled`). True when this call confirmed it.

    Asked by each job that moves either half (the call content deletion, the contact
    erasure, a `contact.erased` delivery), so whichever finishes last closes the task, and
    the task row is locked so two finishing together confirm it once."""
    row = (
        await session.execute(
            text(
                "SELECT status, vendor_refs, vendor_reference FROM processor_erasure_tasks "
                "WHERE id = :tid AND processor = 'voice_engine' FOR UPDATE"
            ),
            {"tid": str(task_id)},
        )
    ).first()
    if row is None or row.status != "requested" or not _contacts_settled(row.vendor_reference):
        return False
    refs = [str(ref) for ref in (row.vendor_refs or [])]
    owed = (await session.execute(text(_CALLS_OWED_SQL), {"refs": refs})).scalar_one()
    if owed:
        return False
    contacts = _progress_of(row.vendor_reference)
    note = f"content of {len(refs)} call(s) deleted at the voice platform" + (
        f"; {len(contacts)} contact(s) erased in the client's workspace, recordings included"
        if contacts
        else ""
    )
    return await record_answer(session, task_id=task_id, outcome="confirmed", note=note)


async def record_contact_erased(session: AsyncSession, *, contact_id: str) -> list[UUID]:
    """The voice platform says this contact's last recording is gone (`contact.erased`):
    mark it so on every awaiting `voice_engine` task of the session's tenant that erased it,
    and confirm each one that is now complete. Returns the tasks it touched; none when no
    erasure of ours is waiting on that contact (a contact someone else deleted).

    Called in the tenant's own session: RLS keeps a delivery for one client's workspace
    from reaching another client's tasks. A contact still held back (`CONTACT_HELD`) that
    someone else erased is gone all the same, so it is settled too."""
    assert_vendor_refs_are_id_shaped([contact_id])
    rows = (
        await session.execute(
            text(
                "SELECT id, vendor_reference FROM processor_erasure_tasks "
                "WHERE processor = 'voice_engine' AND status IN ('open', 'requested') "
                "ORDER BY id"
            )
        )
    ).all()
    touched: list[UUID] = []
    for task_id, reference in rows:
        if contact_id not in _progress_of(reference) and contact_id not in held_contacts(reference):
            continue
        await record_engine_contact_progress(session, task_id=task_id, progress={contact_id: 0})
        await settle_voice_engine_task(session, task_id=task_id)
        touched.append(UUID(str(task_id)))
    return touched


async def held_contact_erasures(session: AsyncSession) -> list[UUID]:
    """The erasure requests of the session's tenant whose contact erasure is held back, for
    the nightly backstop that asks each one again (`retention._release_held_contacts`)."""
    rows = (
        await session.execute(
            text(
                "SELECT request_ref, vendor_reference FROM processor_erasure_tasks "
                "WHERE processor = 'voice_engine' AND status IN ('open', 'requested') "
                "AND vendor_reference LIKE :held ORDER BY opened_at"
            ),
            {"held": f"%={CONTACT_HELD}%"},
        )
    ).all()
    return [UUID(str(ref)) for ref, reference in rows if held_contacts(reference)]


async def overdue_tasks(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    min_days: int | None = None,
    include_held: bool = False,
) -> list[ProcessorErasureTask]:
    """Every task still unanswered past `min_days`, oldest first.

    Both `open` and `requested` count as overdue, and collapsing them would hide the
    more serious of the two: an `open` task is OUR failure to ask, a `requested` one is
    the vendor's failure to answer, and only the first is fixable from here.

    `min_days` defaults to `OVERDUE_AFTER_DAYS`, which is what the alarm asks for. The
    operator script passes 0 for `list --all`, because someone who has just been paged
    about one tenant usually wants to send every outstanding request in one email rather
    than the ones that happen to have crossed a 30-day line.

    A task held for a recording floor still to pass (`NOT_HELD_SQL`) is the alarm's
    exception and is left out unless `include_held`; `--all` includes it, with its
    `held_until`, so the operator sees what it waits for.
    """
    days = OVERDUE_AFTER_DAYS if min_days is None else min_days
    rows = await session.execute(
        text(
            "SELECT t.id, t.processor, t.status, t.subject_ref, t.vendor_refs, t.answered_at, "
            "       EXTRACT(DAY FROM now() - t.opened_at)::int AS days_open, "
            f"      {HELD_UNTIL_SQL} AS held_until "
            "FROM processor_erasure_tasks t "
            "WHERE t.tenant_id = :tid AND t.status IN ('open', 'requested') "
            # `<=` and not `<`: `now()` is TRANSACTION start time, and a task opened
            # earlier in this same transaction has `opened_at` exactly equal to it.
            # With a strict `<` the operator script's `--all` (min_days=0) returned
            # an empty list for tasks it had just opened. At the 30-day default the
            # two spellings differ only on an exact boundary instant.
            "  AND t.opened_at <= now() - make_interval(days => :days) "
            f"  AND (CAST(:include_held AS boolean) OR {NOT_HELD_SQL}) "
            "ORDER BY t.opened_at"
        ),
        {
            "tid": str(tenant_id),
            "days": days,
            "floor": RECORDING_FLOOR_DAYS,
            "include_held": include_held,
        },
    )
    return [
        ProcessorErasureTask(
            id=row.id,
            processor=row.processor,
            status=row.status,
            subject_ref=row.subject_ref,
            vendor_refs=list(row.vendor_refs or []),
            days_open=row.days_open,
            answered_at=row.answered_at,
            held_until=row.held_until,
        )
        for row in rows
    ]


async def settled_tasks(session: AsyncSession, *, tenant_id: UUID) -> list[ProcessorErasureTask]:
    """Every obligation the vendor has ANSWERED, newest first.

    The reader for `answered_at`, and the question it answers is the one that decides
    what a client may tell a data principal: *has the platform confirmed it deleted its
    copy, and on what date?* The certificate cannot carry that — it is issued weeks
    earlier and nothing back-fills a stored proof (hard rule 4) — so this is where the
    answer lives.

    `refused` rows come back too, and they are the important ones: a refusal is the
    evidence that the gap is structural and belongs in front of whoever is negotiating
    the vendor DPA (OPERATIONS §2 gate 36).
    """
    rows = await session.execute(
        text(
            "SELECT id, processor, status, subject_ref, vendor_refs, answered_at, "
            "       EXTRACT(DAY FROM answered_at - opened_at)::int AS days_open "
            "FROM processor_erasure_tasks "
            "WHERE tenant_id = :tid AND status IN ('confirmed', 'refused') "
            "ORDER BY answered_at DESC"
        ),
        {"tid": str(tenant_id)},
    )
    return [
        ProcessorErasureTask(
            id=row.id,
            processor=row.processor,
            status=row.status,
            subject_ref=row.subject_ref,
            vendor_refs=list(row.vendor_refs or []),
            days_open=row.days_open,
            answered_at=row.answered_at,
        )
        for row in rows
    ]


def _json_array(values: list[str]) -> str:
    import json

    return json.dumps(values)
