"""Tell the owner a campaign finished (D-1048, W5.2): a bell item and an email.

Queued by the dispatcher in the transaction that writes the campaign `completed`
(`workers/campaign_dispatch._settle_finished_campaign`), keyed on the campaign and its finish
instant, so a re-run tick never queues it twice and a repeat that finishes again is told
again. The figures are the campaign's own results (`campaigns/results.summary`): people
tried, people who became a lead, and people whose latest answered call booked a call back.
No phone number and no caller's name is in either the bell item or the email.

WhatsApp is not offered: our WhatsApp account has no approved template for this message, and
the hot-lead template carries only a reason (`workers/whatsapp._compose_variables`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.reliability.service import enqueue_outbox_once
from apps.api.tenancy.caller_words import CallerWords

JOB: Final = "notify_campaign_finished"
KIND: Final = "campaign_finished"


def dedupe_key(campaign_id: UUID, finished_at: datetime) -> str:
    return f"campaign-finished:{campaign_id}:{finished_at.isoformat()}"


async def queue(session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID) -> bool:
    """In the caller's transaction, beside the `completed` write. `updated_at` is the finish
    instant: the dispatcher's UPDATE wrote it in this same transaction."""
    finished_at = (
        await session.execute(
            text("SELECT updated_at FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar_one()
    queued = await enqueue_outbox_once(
        session,
        job=JOB,
        payload={
            "tenant_id": str(tenant_id),
            "campaign_id": str(campaign_id),
            "finished_at": finished_at.isoformat(),
        },
        dedupe_key=dedupe_key(campaign_id, finished_at),
    )
    return queued is not None


def _count(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def figures(result: dict[str, Any]) -> tuple[int, int, int]:
    """(called, became a lead, asked for a call back) from `campaigns/results.summary`."""
    tags = result.get("outcome_tags") or {}
    return (
        int(result.get("tried") or 0),
        int(result.get("interested_leads") or 0),
        int(tags.get("call_back_booked") or 0),
    )


def title(name: str, numbers: tuple[int, int, int], words: CallerWords) -> str:
    called, leads, call_backs = numbers
    label = " ".join(name.split())[:80] or "Your campaign"
    return (
        f"{label} finished: {_count(called, 'person', 'people')} called, "
        f"{_count(leads, words.new_lead, words.new_leads)}, "
        f"{_count(call_backs, 'call-back', 'call-backs')} asked for."
    )


__all__ = ["JOB", "KIND", "dedupe_key", "figures", "queue", "title"]
