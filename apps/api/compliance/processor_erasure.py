"""The record of an erasure obligation we cannot discharge in code (D-433).

**The hole this fills.** `execute_deletion_request` erases a data principal from our
Postgres and our object storage and writes a certificate. The voice platform that carried
the calls keeps its own copy of the recording and the transcript, in the US, and
`docs/evidence/subprocessor-erasure-reach.md` §1 enumerates — across all 335 mirrored
vendor pages — every `DELETE` route that platform documents. Ten routes. Nine delete
configuration objects. The tenth deletes an agent together with *"ALL agent data including
all batches, all executions"*, which is the wrong granularity for a request about one
person: using it would destroy every other caller's records and take the client's live
receptionist off the air.

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
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.base import uuid7

__all__ = [
    "OVERDUE_AFTER_DAYS",
    "PROCESSORS",
    "STATUSES",
    "ProcessorErasureTask",
    "VendorRefRejectedError",
    "assert_vendor_refs_are_id_shaped",
    "open_tasks_for_request",
    "overdue_tasks",
    "record_answer",
    "record_request_sent",
    "settled_tasks",
]

#: The processors that hold call content and publish no subject-granular deletion.
#:
#: A CLOSED vocabulary rather than free text, because the register in `deletion.py` names
#: exactly these and a fourth spelling of "bolna" would silently create a task nobody's
#: runbook covers. Adding a processor means adding it here, to the register, and to
#: `docs/evidence/subprocessor-erasure-reach.md` §3 — three edits, on purpose.
#:
#: They are named by ROLE and not by vendor. The vendor is a config choice (D-31 has an
#: engine port, D-36 a speech tier, D-410 a model leg); the obligation attaches to the
#: role, and a row written today must still be readable after a vendor swap.
PROCESSORS: Final = ("voice_engine", "speech", "llm")

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


async def open_tasks_for_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_ref: UUID,
    request_kind: str,
    subject_ref: str | None,
    vendor_refs: list[str],
    processors: tuple[str, ...] = PROCESSORS,
) -> int:
    """Open one task per processor that holds a copy this erasure could not reach.

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

    opened = 0
    for processor in processors:
        if processor not in PROCESSORS:
            raise ValueError(f"unknown processor {processor!r}")
        result = await session.execute(
            text(
                "INSERT INTO processor_erasure_tasks "
                "(id, tenant_id, request_ref, request_kind, processor, status, "
                " subject_ref, vendor_refs) "
                "VALUES (:id, :tid, :ref, :kind, :proc, 'open', :subj, "
                "        CAST(:refs AS jsonb)) "
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


async def overdue_tasks(
    session: AsyncSession, *, tenant_id: UUID, min_days: int | None = None
) -> list[ProcessorErasureTask]:
    """Every task still unanswered past `min_days`, oldest first.

    Both `open` and `requested` count as overdue, and collapsing them would hide the
    more serious of the two: an `open` task is OUR failure to ask, a `requested` one is
    the vendor's failure to answer, and only the first is fixable from here.

    `min_days` defaults to `OVERDUE_AFTER_DAYS`, which is what the alarm asks for. The
    operator script passes 0 for `list --all`, because someone who has just been paged
    about one tenant usually wants to send every outstanding request in one email rather
    than the ones that happen to have crossed a 30-day line.
    """
    days = OVERDUE_AFTER_DAYS if min_days is None else min_days
    rows = await session.execute(
        text(
            "SELECT id, processor, status, subject_ref, vendor_refs, answered_at, "
            "       EXTRACT(DAY FROM now() - opened_at)::int AS days_open "
            "FROM processor_erasure_tasks "
            "WHERE tenant_id = :tid AND status IN ('open', 'requested') "
            # `<=` and not `<`: `now()` is TRANSACTION start time, and a task opened
            # earlier in this same transaction has `opened_at` exactly equal to it.
            # With a strict `<` the operator script's `--all` (min_days=0) returned
            # an empty list for tasks it had just opened. At the 30-day default the
            # two spellings differ only on an exact boundary instant.
            "  AND opened_at <= now() - make_interval(days => :days) "
            "ORDER BY opened_at"
        ),
        {"tid": str(tenant_id), "days": days},
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
