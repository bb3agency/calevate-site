"""Archive, restore and delete a campaign — the ONE implementation every door calls (F-10).

The client's buttons (`campaigns/routes.py`), the operator's (`campaigns/archive_admin_routes`)
and Pip's `campaign_delete` all come here, so the rules are the same whoever asks:

- **Archive** puts any campaign away: hidden from the default list, shown under "Archived",
  never dialled, and every call, lead, consent row and charge it made kept. A running
  campaign is PAUSED first through the same CAS the Pause button uses (never stopped
  mid-dial: a call already ringing finishes, and nobody new is claimed), and a scheduled
  one goes back to draft through the same unschedule the Stop-schedule button uses, so
  nothing it was waiting to start can start.
- **Restore** clears the archive and leaves the status as archive left it (paused, draft,
  completed or cancelled). Nothing restores to running: the owner resumes it, through the
  resume path and its checks.
- **Delete** removes only a draft that never dialled and that no evidence row names
  (`controls.delete_draft`). Anything else is refused with `campaign_has_history`, whose
  remedy is archiving: its calls, consent and billing must stay (hard rules 4 and 8).

The row is locked first in every one, so a concurrent launch, resume or tick waits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import controls
from apps.api.campaigns.scheduling import unschedule_campaign
from apps.api.campaigns.service import set_campaign_status
from apps.api.core.errors import ProblemError

ArchiveRealm = Literal["client", "admin"]

#: The shortest reason an operator may give; the client reads it.
MIN_REASON_CHARS: Final = 3
MAX_REASON_CHARS: Final = 280


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    #: False when it was already archived (a second press): nothing moved, nothing to audit.
    changed: bool
    name: str
    #: The status before the archive and after it (a running campaign is paused).
    status_before: str
    status_after: str
    #: On a restore: who had archived it and from which realm, for the audit row ("our
    #: team restored what the client put away" reads differently from the reverse).
    undid: tuple[UUID | None, str | None] = (None, None)


async def _locked(session: AsyncSession, campaign_id: UUID) -> tuple[str, str, bool, UUID]:
    row = (
        await session.execute(
            text(
                "SELECT name, status, archived_at IS NOT NULL, tenant_id FROM campaigns "
                "WHERE id = :cid FOR UPDATE"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        # Absent, or another tenant's: RLS makes those one answer on purpose.
        raise ProblemError.not_found("Campaign")
    return str(row[0]), str(row[1]), bool(row[2]), UUID(str(row[3]))


def clean_reason(reason: str | None, *, required: bool) -> str | None:
    """One line, trimmed; refused when an operator gives none (the client is told it)."""
    line = " ".join((reason or "").split())[:MAX_REASON_CHARS]
    if required and len(line) < MIN_REASON_CHARS:
        raise ProblemError(
            kind="validation",
            code="archive_reason_required",
            title="Say why",
            detail="The client is told why their campaign was archived.",
            remediation="Write a short reason, at least three letters.",
        )
    return line or None


async def archive_campaign(
    session: AsyncSession,
    *,
    campaign_id: UUID,
    by: UUID | None,
    realm: ArchiveRealm,
    reason: str | None = None,
) -> ArchiveResult:
    """Put a campaign away. Idempotent: archiving an archived campaign changes nothing."""
    reason = clean_reason(reason, required=realm == "admin")
    name, status, archived, tenant_id = await _locked(session, campaign_id)
    if archived:
        return ArchiveResult(changed=False, name=name, status_before=status, status_after=status)
    after = status
    if status == "running":
        await set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )
        after = "paused"
    elif status == "scheduled":
        cancelled = await unschedule_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        after = cancelled.status
    await session.execute(
        text(
            "UPDATE campaigns SET archived_at = now(), archived_by = :by, "
            "archived_by_realm = :realm, archive_reason = :reason, schedule = NULL, "
            "updated_at = now() WHERE id = :cid AND archived_at IS NULL"
        ),
        {"cid": campaign_id, "by": by, "realm": realm, "reason": reason},
    )
    return ArchiveResult(changed=True, name=name, status_before=status, status_after=after)


async def restore_campaign(session: AsyncSession, *, campaign_id: UUID) -> ArchiveResult:
    """Bring a campaign back, as archive left it. Never to running."""
    name, status, archived, _tenant = await _locked(session, campaign_id)
    undid: tuple[UUID | None, str | None] = (None, None)
    if archived:
        row = (
            await session.execute(
                text(
                    "UPDATE campaigns c SET archived_at = NULL, archived_by = NULL, "
                    "archived_by_realm = NULL, archive_reason = NULL, updated_at = now() "
                    "FROM campaigns before WHERE before.id = c.id AND c.id = :cid "
                    "RETURNING before.archived_by, before.archived_by_realm"
                ),
                {"cid": campaign_id},
            )
        ).first()
        if row is not None:
            undid = (UUID(str(row[0])) if row[0] else None, str(row[1]) if row[1] else None)
    return ArchiveResult(
        changed=archived, name=name, status_before=status, status_after=status, undid=undid
    )


async def delete_campaign(session: AsyncSession, *, campaign_id: UUID) -> str:
    """Delete a draft that never dialled; refuse anything else with `campaign_has_history`
    (archive it instead). Returns the deleted campaign's name, for the audit row."""
    name, _status, _archived, _tenant = await _locked(session, campaign_id)
    await controls.delete_draft(session, campaign_id=campaign_id)
    return name


__all__ = [
    "MAX_REASON_CHARS",
    "ArchiveRealm",
    "ArchiveResult",
    "archive_campaign",
    "clean_reason",
    "delete_campaign",
    "restore_campaign",
]
