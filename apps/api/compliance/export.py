"""DPDP data-subject ACCESS / PORTABILITY export (SEC-COMP §4).

The twin of `apps/workers/retention.execute_deletion_request`. Erasure answers "forget
me"; this answers the question that arrives far more often — "what do you hold about
me?". DPDP §11 gives the data principal both rights, and a system that can only delete
is a system that can only ever say *no* to the more common request.

The shape is the same at both ends: locate everything keyed to one phone number across
calls, transcript turns, leads and the consent ledger, and produce ONE document. Where
erasure emits a proof that deliberately contains no personal data, this emits the
personal data itself — so every judgement below is about what may leave the building.

**Whose data is it?** — three decisions, each of which could have gone the other way:

1. **Transcripts are the REDACTED view (`text_redacted`), never raw `text`.** A subject
   access request entitles the subject to *their* personal data, not to everyone
   else's. A transcript is a recording of a conversation, and a caller who reads out a
   relative's number, a doctor's name or an account belonging to someone else has put a
   THIRD PARTY's personal data into our store. Handing the raw column over would
   disclose that third party's data to a stranger, on the strength of a request the
   third party never made — a fresh breach committed in the course of honouring a
   right. Hard rule 5 already makes `text_redacted` the default in every API response
   and puts raw text behind a role check plus an audit write; that default is not
   relaxed here, it is *reinforced*, because this is the one response that leaves the
   client's own screen and travels to an outsider. SEC-COMP §4 says it directly:
   redaction runs BEFORE any transcript leaves our system.

2. **Recordings are reported as a boolean, never as a URL.** `recording_available`
   tells the subject that an audio copy exists — which is the fact they are entitled to
   know, and the fact they need in order to ask for it. A presigned URL embedded in a
   JSON blob is a bearer credential: this document gets emailed, forwarded, and
   attached to a ticket, and every hop carries a working link to the audio with it. The
   client fetches recordings through `GET /v1/calls/{id}/recording`, which is
   role-checked, short-lived and audited per fetch; nothing about a subject access
   request justifies inventing a second, unaudited path to the same bytes.

3. **The queried number appears UNMASKED; every other phone-shaped value does not.**
   Masking the very identifier the subject asked about produces a document that cannot
   be checked ("is this really about me?") and cannot be acted on — a subject access
   response reading `••••••11` is a refusal wearing a disclosure's clothes. The subject
   already knows their own number; it is the key to the query, not a revelation. That
   argument covers exactly one number, so `summary` — free prose a model wrote about
   the conversation, with no schema constraining what can appear in it — has any OTHER
   phone-shaped digit run masked before it ships (`mask_foreign_numbers`). The lead's
   extracted `data` is deliberately NOT put through the same filter: those fields exist
   because the client defined an extraction schema describing THIS caller, so masking
   them would corrupt the very answer being requested.

Timestamps are ISO-8601 strings rather than datetimes: the document is meant to be
serialized to a file and handed over, and "portable" means readable without our code.

Nothing here filters on `tenant_id` in SQL — the session's transaction carries
`app.tenant_id` and RLS is doing the isolation (hard rule 1), exactly as
`apps/api/crm/service.py` explains. `tenant_id` is taken as an argument so the caller's
scope is explicit at the call site and can be logged.

One consequence worth stating: a number that has already been through
`execute_deletion_request` yields an EMPTY document, because erasure nulls the very
columns this locates by. Erase-then-access returning nothing is the correct answer, and
the two halves agreeing on `subject_ref()` is what lets an auditor line them up.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger

log = get_logger(__name__)

# A turn whose `text_redacted` is NULL has not been through the redaction pass yet
# (workers step 2). Falling back to raw `text` would be a hard-rule-5 violation, and
# emitting an empty string would tell the subject a turn was silent when it was not —
# so the document says plainly that this turn is not yet releasable.
REDACTION_PENDING = "[redaction pending]"
FOREIGN_NUMBER_MARK = "[number]"

# Same shape as core.logging._PHONE_RE: 8+ digits with optional +, spaces or dashes.
# Bounded on the right so a run of separators cannot swallow a whole paragraph.
_DIGIT_RUN = re.compile(r"\+?\d[\d\s-]{6,18}\d")
_MIN_PHONE_DIGITS = 8


def subject_ref(phone_e164: str) -> str:
    """A stable, non-reversible handle for one data subject.

    Deliberately the same construction as the erasure proof's `subject_hash`
    (`apps/workers/retention._hash`): an access request and an erasure request for the
    same person must be correlatable in `audit_log` and in the proof archive, and the
    only way to do that without either record carrying the number is for both to derive
    the same reference from it (hard rule 6).
    """
    return hashlib.sha256(phone_e164.encode()).hexdigest()[:32]


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def mask_foreign_numbers(value: str | None, *, subject_phone: str) -> str | None:
    """Mask phone-shaped digit runs that are NOT the subject's own number.

    Applied to model-written prose (`calls.summary`) on its way out. The subject's own
    number survives because this document is addressed to them; anyone else's does not,
    because they did not ask for anything.
    """
    if not value:
        return value
    subject = _digits(subject_phone)
    national = subject[-10:]

    def _replace(match: re.Match[str]) -> str:
        found = _digits(match.group(0))
        if len(found) < _MIN_PHONE_DIGITS:
            return match.group(0)
        # `+919876500011`, `919876500011` and `9876500011` are all the same person.
        if found.endswith(national) or subject.endswith(found):
            return match.group(0)
        return FOREIGN_NUMBER_MARK

    return _DIGIT_RUN.sub(_replace, value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _lead_record(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        # The subject's own number, unmasked — see decision 3 in the module docstring.
        "phone_e164": row[1],
        "name": row[2],
        "status": row[3],
        "source": row[4],
        # Schema-driven extraction fields (TRD §7). Left verbatim: the client defined
        # these fields to describe THIS caller, so they are the subject's own data.
        "data": row[5] or {},
        "schema_version": row[6],
        "call_count": row[7],
        "is_repeat_caller": bool(row[8]),
        "created_at": _iso(row[9]),
        "updated_at": _iso(row[10]),
    }


# Every erasure this tenant has completed for this subject, and whatever audio those
# erasures are still lawfully holding.
#
# KEYED ON `subject_ref`, NOT ON THE NUMBER, and that is the whole reason this query
# exists rather than a join onto `calls`. A completed erasure nulls `from_e164`,
# `to_e164` AND `deletion_requests.phone_e164` in the same statements that create the
# holds, so after it runs NOTHING in this database can be matched to the person by their
# number — every other query in this module returns empty, and the document says "we hold
# nothing about you". That is false while an under-floor recording is still in the bucket
# on a schedule (`recording_erasure_holds`, migration 9c1d3e7a05f4), and a §11 access
# answer that under-reports is the same defect as one that over-reports.
#
# The hash is what survives, by design (D-44): `subject_ref(phone)` is computable from the
# number the requester just supplied and from nothing else, so this discloses to someone
# who already has the number and to no one else.
#
# The holds are reached THROUGH the request rather than by call id, for the same reason:
# the calls no longer name the subject either.
_ERASURE_SQL = """
SELECT d.completed_at,
       count(h.id) FILTER (WHERE h.erased_at IS NULL) AS pending,
       max(h.erase_after) FILTER (WHERE h.erased_at IS NULL) AS last_erase_after
FROM deletion_requests d
LEFT JOIN recording_erasure_holds h ON h.request_id = d.id
WHERE d.subject_ref = :ref AND d.completed_at IS NOT NULL
GROUP BY d.id, d.completed_at
ORDER BY d.completed_at DESC
LIMIT 1
"""


async def _erasure_summary(session: AsyncSession, *, phone_e164: str) -> dict[str, Any] | None:
    """The most recent completed erasure for this subject, or None if there is none.

    `None` and "an erasure with nothing outstanding" are different answers and are not
    merged: the first means nobody has asked, the second means somebody did and it is
    finished. A client reading this to answer a data principal needs to be able to tell
    those apart without reading a count.
    """
    row = (await session.execute(text(_ERASURE_SQL), {"ref": subject_ref(phone_e164)})).first()
    if row is None:
        return None
    return {
        "completed_at": _iso(row[0]),
        # Audio this erasure could not lawfully destroy when it ran and has not destroyed
        # yet. Zero means the erasure is complete down to the bytes.
        "recordings_pending_destruction": int(row[1] or 0),
        # The day the last of it goes. Null when nothing is outstanding.
        "recordings_destroyed_by": _iso(row[2]),
    }


async def build_subject_export(
    session: AsyncSession, *, tenant_id: UUID, phone_e164: str
) -> dict[str, Any]:
    """Everything this tenant holds keyed to `phone_e164`, in portable form.

    A number we hold nothing about is NOT an error: it returns the same document with
    `lead: None` and empty lists. "We hold no data about you" is a complete, valid and
    legally meaningful answer to a subject access request — a 404 would tell the
    requester that their request failed, which is a different and untrue statement.
    """
    call_rows = (
        await session.execute(
            text(
                "SELECT id, direction, started_at, duration_s, outcome_tag, summary, "
                "(recording_url IS NOT NULL) FROM calls "
                "WHERE from_e164 = :phone OR to_e164 = :phone "
                "ORDER BY started_at ASC NULLS LAST, id ASC"
            ),
            {"phone": phone_e164},
        )
    ).all()

    calls: list[dict[str, Any]] = [
        {
            "call_id": str(row[0]),
            "direction": row[1],
            "started_at": _iso(row[2]),
            "duration_s": row[3],
            "outcome_tag": row[4],
            "summary": mask_foreign_numbers(row[5], subject_phone=phone_e164),
            # A boolean, not a link (decision 2). The audited recording endpoint is the
            # only way to the bytes.
            "recording_available": bool(row[6]),
        }
        for row in call_rows
    ]

    transcripts: list[dict[str, Any]] = []
    turn_total = 0
    call_ids = [row[0] for row in call_rows]
    if call_ids:
        turn_rows = (
            await session.execute(
                text(
                    # `text_redacted`, never `text` (decision 1). The raw column is not
                    # even named in this query, so it cannot leak through a later edit.
                    "SELECT call_id, idx, speaker, text_redacted FROM transcript_turns "
                    "WHERE call_id = ANY(:ids) ORDER BY call_id, idx"
                ),
                {"ids": call_ids},
            )
        ).all()
        turn_total = len(turn_rows)
        grouped: dict[str, list[dict[str, Any]]] = {str(call_id): [] for call_id in call_ids}
        for call_id, idx, speaker, redacted in turn_rows:
            grouped[str(call_id)].append(
                {
                    "idx": int(idx),
                    "speaker": speaker,
                    "text": REDACTION_PENDING if redacted is None else redacted,
                }
            )
        transcripts = [
            {"call_id": call_id, "turns": turns} for call_id, turns in grouped.items() if turns
        ]

    lead_rows = (
        await session.execute(
            text(
                "SELECT id, phone_e164, name, status, source, data, schema_version, "
                "call_count, is_repeat_caller, created_at, updated_at FROM leads "
                "WHERE phone_e164 = :phone AND deleted_at IS NULL ORDER BY updated_at DESC"
            ),
            {"phone": phone_e164},
        )
    ).all()
    # `leads` is unique on (tenant_id, phone_e164, agent_id), so a tenant running more
    # than one agent can hold several rows for one person. The document carries the most
    # recently updated one — the record the client actually works — and `counts.leads`
    # states the true total, so a second row is VISIBLE in the answer rather than
    # silently dropped from it.
    lead = _lead_record(lead_rows[0]) if lead_rows else None

    consent_rows = (
        await session.execute(
            text(
                "SELECT call_id, purpose, status, captured_at, (evidence IS NOT NULL) "
                "FROM consent_ledger WHERE phone_e164 = :phone ORDER BY captured_at ASC"
            ),
            {"phone": phone_e164},
        )
    ).all()
    consent: list[dict[str, Any]] = [
        {
            "call_id": str(row[0]) if row[0] is not None else None,
            "purpose": row[1],
            "status": row[2],
            "captured_at": _iso(row[3]),
            # `evidence` is a transcript SPAN — raw text by construction. The subject is
            # told that evidence was captured, on the same reasoning as the recording
            # boolean; the span itself stays behind the audited raw-transcript path.
            "evidence_recorded": bool(row[4]),
        }
        for row in consent_rows
    ]

    # THE SUPPRESSION STATE, which this document omitted entirely.
    #
    # `/legal/privacy` §3 lists the do-not-call entry among the data held about a caller,
    # so leaving it out made the export incomplete against our own published notice — and
    # it is the single fact a complainant most often wants confirmed ("you said you would
    # stop; did you record it?"). The three columns are the three things that answer it:
    # WHICH list (a `global` platform suppression outranks the tenant's own, exactly as
    # `dnc.check_number` ranks them), WHY it is there, and WHEN it was added.
    #
    # A GLOBAL ROW IS INCLUDED, and deliberately, even though it is not this tenant's:
    # the subject is asking what is held about THEM, and "you are suppressed platform-wide
    # and this account cannot lift it" is a truthful and material answer. RLS already
    # permits the read (`DncEntry`'s asymmetric policy — a tenant must be able to see a
    # global entry or it would dial a number it may not).
    # No `tenant_id` predicate, like every other statement here: RLS is the isolation
    # (hard rule 1), and `DncEntry`'s policy deliberately lets a tenant session see the
    # global rows as well as its own.
    dnc_row = (
        await session.execute(
            text(
                "SELECT scope, source, added_at FROM dnc_list WHERE phone_e164 = :phone "
                "ORDER BY (scope = 'global') DESC LIMIT 1"
            ),
            {"phone": phone_e164},
        )
    ).first()
    # `suppressed: False` rather than a missing key: "we hold no suppression for you" is
    # an answer to the question, and an absent field reads as one nobody asked.
    do_not_call: dict[str, Any] = {
        "suppressed": dnc_row is not None,
        "scope": str(dnc_row[0]) if dnc_row is not None else None,
        "source": str(dnc_row[1]) if dnc_row is not None and dnc_row[1] is not None else None,
        "added_at": _iso(dnc_row[2]) if dnc_row is not None else None,
    }

    document: dict[str, Any] = {
        "phone_e164": phone_e164,
        "generated_at": datetime.now(UTC).isoformat(),
        "erasure": await _erasure_summary(session, phone_e164=phone_e164),
        "lead": lead,
        "calls": calls,
        "transcripts": transcripts,
        "consent": consent,
        "do_not_call": do_not_call,
        "counts": {
            "leads": len(lead_rows),
            "calls": len(calls),
            "transcript_turns": turn_total,
            "consent_records": len(consent),
            "recordings_available": sum(1 for call in calls if call["recording_available"]),
        },
    }

    # Ids and counts only (hard rule 6) — the number itself never reaches a log line,
    # which is precisely why `subject_ref` exists.
    log.info(
        "subject_export_built",
        extra={
            "tenant_id": str(tenant_id),
            "subject_ref": subject_ref(phone_e164),
            "calls": len(calls),
            "turns": turn_total,
        },
    )
    return document


__all__ = [
    "FOREIGN_NUMBER_MARK",
    "REDACTION_PENDING",
    "build_subject_export",
    "mask_foreign_numbers",
    "subject_ref",
]
