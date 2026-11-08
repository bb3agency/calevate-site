"""Refile retired caller notes from outbound calls under the person called (L5-02).

The notes themselves are retired (D-973): nothing writes `caller_memories` any more. Rows
written before that stay until the follow-up drop migration, and a DPDP request for the
person called must find theirs, so this repair outlives the store that needed it. Migration
`f5a9c3e1d7b2` queues it per account from the outbox, and its downgrade queues the reverse.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.compliance.caller_ref import CallerRefError, active_caller_ref
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: Frozen in migration `f5a9c3e1d7b2`, which queues this job by name. `file_under` names
#: which number of an outbound call the notes go under: the person called (the fix), or the
#: calling number (the state before it, to undo it).
REFILE_JOB: Final = "refile_caller_memories"
FILE_UNDER_PARTY: Final = "other_party"
FILE_UNDER_CALLING_NUMBER: Final = "calling_number"

_OUTBOUND_MEMORIES_SQL: Final = """
SELECT m.id, c.from_e164, c.to_e164 FROM caller_memories m
JOIN calls c ON c.id = m.source_call_id
WHERE c.direction <> 'inbound' AND m.scrubbed_at IS NULL
"""
_REFILE_SQL: Final = """
UPDATE caller_memories SET subject_ref = :ref, subject_ref_kek_id = :kek, updated_at = now()
WHERE id = :id AND scrubbed_at IS NULL
"""


async def refile_caller_memories(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """File one account's notes from outbound calls under the chosen number of each call.

    Idempotent: a note already under that number is written the same ref again. A call whose
    chosen number is gone (erased) or not canonical keeps its note where it is and is
    counted; the erasure arm still reaches it by `source_call_id`. Counts only in the log
    (hard rule 6).
    """
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    file_under = str(payload.get("file_under") or FILE_UNDER_PARTY)
    if file_under not in (FILE_UNDER_PARTY, FILE_UNDER_CALLING_NUMBER):
        raise ValueError(f"unknown file_under {file_under!r}")
    moved = left = 0
    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(text(_OUTBOUND_MEMORIES_SQL))).all()
        for memory_id, calling_number, party in rows:
            number = party if file_under == FILE_UNDER_PARTY else calling_number
            if not number:
                left += 1
                continue
            try:
                handle = active_caller_ref(tenant_id, str(number))
            except CallerRefError:
                left += 1
                continue
            await session.execute(
                text(_REFILE_SQL), {"ref": handle.ref, "kek": handle.kek_id, "id": memory_id}
            )
            moved += 1
    log.info(
        "caller_memories_refiled",
        extra={"tenant_id": str(tenant_id), "file_under": file_under, "moved": moved, "left": left},
    )
    return f"moved={moved} left={left}"


__all__ = [
    "FILE_UNDER_CALLING_NUMBER",
    "FILE_UNDER_PARTY",
    "REFILE_JOB",
    "refile_caller_memories",
]
