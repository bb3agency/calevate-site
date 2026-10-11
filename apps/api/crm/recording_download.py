"""Saving a call recording to the owner's device (founder, 11 Oct 2026).

The same object, role and audit trail as playing it (`crm/routes.get_recording`); what
differs is the signed `Content-Disposition`: `attachment` with a filename, where playback
asks for `inline`. Nothing is copied or re-hosted: the link is a short-lived signature over
OUR copy of the audio, exactly as playback's is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.compliance.deletion import RECORDING_FLOOR_DAYS
from apps.api.core.errors import ProblemError

#: Long enough for the browser to start the download, which is when the signature is
#: checked; a link that is never used is worthless a few minutes later.
DOWNLOAD_LINK_TTL_S: Final = 300
_EXTENSION: Final = re.compile(r"[a-z0-9]{2,4}")


@dataclass(frozen=True, slots=True)
class RecordingDownload:
    key: str
    filename: str


def download_filename(*, business: str, slug: str, at: datetime, key: str) -> str:
    """`<business>-call-<IST yyyy-mm-dd-hhmm>.<ext>`, ASCII only, so the header needs no
    RFC 5987 encoding and no browser renames it. A business name with no Latin letters
    (a Telugu name) falls back to the account's slug. Never the caller's number."""
    name = re.sub(r"[^a-z0-9]+", "-", business.lower()).strip("-")[:40].strip("-")
    stamp = at.astimezone(IST).strftime("%Y-%m-%d-%H%M")
    suffix = PurePosixPath(key).suffix.lstrip(".").lower()
    extension = suffix if _EXTENSION.fullmatch(suffix) else "audio"
    return f"{name or slug}-call-{stamp}.{extension}"


async def recording_download_for(
    session: AsyncSession, call_id: UUID, *, now: datetime | None = None
) -> RecordingDownload:
    """The object and its filename, or a refusal that says which thing is missing: no
    call, a recording deleted under the retention rule, or a call that was never
    recorded."""
    row = (
        await session.execute(
            text(
                "SELECT c.recording_url, COALESCE(c.started_at, c.created_at), o.name, o.slug "
                "FROM calls c JOIN organizations o ON o.id = c.tenant_id WHERE c.id = :cid"
            ),
            {"cid": call_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Call")
    at: datetime = row[1]
    if not row[0]:
        if (now or datetime.now(UTC)) - at >= timedelta(days=RECORDING_FLOOR_DAYS):
            raise ProblemError(
                kind="not_found",
                code="recording_expired",
                title="This recording is no longer kept",
                detail=(
                    f"Recordings are kept for {RECORDING_FLOOR_DAYS} days, and this one "
                    "has been deleted. The transcript and summary stay."
                ),
            )
        raise ProblemError.not_found("Recording")
    key = str(row[0])
    return RecordingDownload(
        key=key,
        filename=download_filename(business=str(row[2] or ""), slug=str(row[3]), at=at, key=key),
    )


__all__ = [
    "DOWNLOAD_LINK_TTL_S",
    "RecordingDownload",
    "download_filename",
    "recording_download_for",
]
