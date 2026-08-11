"""The "needs attention" queue (SURFACES §2b).

Everything this platform refuses to do quietly ends up here. That is the design claim
and it is worth stating plainly: the compliance gate blocks dials, the DNC list ends
campaigns' contacts, endpoints reject deliveries, and campaigns pause — and every one
of those is *correct behaviour* that nonetheless leaves a human with something to
decide. A product that enforces rules without surfacing their consequences reads as
broken (SURFACES §2b: "blocked features visibly explained").

Each source is its own small query rather than one clever UNION. They have different
shapes, different fixes and different urgencies, and a union would force them into a
lowest-common-denominator row that helps nobody. The cost is a handful of indexed
counts per page load, against tables the tenant's own RLS already scopes.

Deliberately NOT here: anything the client cannot act on. A failed engine webhook is
our problem and belongs in ops alerting, not in a business owner's queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.crm.service import mask_phone

# How far back the queue looks. A blocked dial from last month is history, not a
# to-do; leaving it in the list is how a queue becomes wallpaper nobody reads.
WINDOW_DAYS = 14

# Rules the CLIENT can do something about, mapped to what they should do. A rule
# missing from here still appears — with its raw name — because silently dropping an
# item is worse than showing one whose copy we have not written yet.
BLOCK_REMEDIES: dict[str, str] = {
    "dnc": "This person asked not to be called. Nothing to do — we will not dial them.",
    "calling_hours": "Outside 9am to 9pm. We will try again in the next window.",
    "spend_cap": "Your monthly cap is reached. Raise it with your account manager to resume.",
    "no_credits": "Your calling credit ran out. Top up to resume outgoing calls.",
    "no_form_consent": "The form did not confirm permission to call. Add the consent "
    "checkbox to your form, or call them yourself.",
    "agent_not_live": "Your agent is not published yet.",
    "big_red_switch": "Outgoing calls are paused platform-wide. We are on it.",
    "disclosure_missing": "The agent has no AI disclosure line, so it may not dial.",
}


@dataclass(frozen=True, slots=True)
class AttentionItem:
    kind: str
    id: str
    title: str
    detail: str
    rule: str | None
    occurred_at: Any
    href: str | None = None


async def blocked_leads(session: AsyncSession, *, limit: int = 25) -> list[AttentionItem]:
    """Leads whose dial the compliance gate refused (FLOWS §4).

    The lead landed — that is the module's whole promise — and the timeline says which
    rule stopped the call. This turns "why didn't anyone ring them?" from a support
    ticket into a line the owner can read.
    """
    rows = (
        await session.execute(
            text(
                "SELECT e.id, e.lead_id, e.payload, e.created_at, l.name, l.phone_e164 "
                "FROM lead_events e JOIN leads l ON l.id = e.lead_id "
                "WHERE e.type = 'note' AND e.payload->>'kind' = 'blocked' "
                f"  AND e.created_at > now() - interval '{WINDOW_DAYS} days' "
                "  AND l.deleted_at IS NULL AND l.status = 'new' "
                "ORDER BY e.created_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    items: list[AttentionItem] = []
    for row in rows:
        rule = str((row[2] or {}).get("rule") or "unknown")
        who = row[4] or mask_phone(row[5])
        items.append(
            AttentionItem(
                kind="lead_blocked",
                id=str(row[1]),
                title=f"{who} was not called",
                detail=BLOCK_REMEDIES.get(rule, f"Blocked by the {rule} rule."),
                rule=rule,
                occurred_at=row[3],
                href="/leads",
            )
        )
    return items


async def failed_deliveries(session: AsyncSession, *, limit: int = 25) -> list[AttentionItem]:
    """Webhook deliveries the client's own endpoint rejected (D-23).

    Scoped through `outbound_webhooks` because `webhook_deliveries` has no RLS policy
    of its own by design — see migration 4be32bf3d12c.
    """
    rows = (
        await session.execute(
            text(
                "SELECT d.id, d.event_type, d.attempts, d.last_at, d.source, w.url "
                "FROM webhook_deliveries d JOIN outbound_webhooks w ON w.id = d.endpoint_id "
                "WHERE d.direction = 'out' AND d.status = 'failed' "
                f"  AND d.last_at > now() - interval '{WINDOW_DAYS} days' "
                "ORDER BY d.last_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    return [
        AttentionItem(
            kind="delivery_failed",
            id=str(row[0]),
            title=f"{row[1]} did not reach your system",
            detail=(
                f"Your endpoint answered {row[4] or 'an error'} after {row[2]} attempts. "
                "Check that it is reachable and returns 2xx."
            ),
            rule=None,
            occurred_at=row[3],
            href="/integrations",
        )
        for row in rows
    ]


async def stalled_campaigns(session: AsyncSession, *, limit: int = 25) -> list[AttentionItem]:
    """Campaigns that are paused, or running with nothing left they can dial.

    A campaign whose remaining contacts are all `dnc_blocked` or `failed` will never
    finish on its own and will never dial again — from the dashboard it looks busy, and
    that silence is exactly what this queue exists to break.
    """
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.name, c.status, c.updated_at, "
                "  count(cc.id) FILTER (WHERE cc.status = 'pending') AS pending, "
                "  count(cc.id) FILTER (WHERE cc.status = 'dnc_blocked') AS blocked "
                "FROM campaigns c LEFT JOIN campaign_contacts cc ON cc.campaign_id = c.id "
                "WHERE c.status IN ('paused', 'running') "
                "GROUP BY c.id ORDER BY c.updated_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    items: list[AttentionItem] = []
    for campaign_id, name, status, updated_at, pending, blocked in rows:
        if status == "paused":
            detail = f"Paused with {pending} contacts still to call."
        elif not pending:
            detail = (
                f"Running, but nothing left to dial — {blocked} numbers are on the "
                "do-not-call list."
                if blocked
                else "Running, but every contact has been attempted."
            )
        else:
            continue
        items.append(
            AttentionItem(
                kind="campaign_stalled",
                id=str(campaign_id),
                title=f"Campaign “{name}” is not making calls",
                detail=detail,
                rule=status,
                occurred_at=updated_at,
                href="/campaigns",
            )
        )
    return items


async def knowledge_waiting(session: AsyncSession, *, limit: int = 25) -> list[AttentionItem]:
    """Knowledge the client submitted that we rejected (FLOWS §7).

    `pending_approval` is deliberately excluded: waiting for us is not the client's
    to-do, and putting it here would make our review queue look like their backlog.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, name, updated_at, rejection_reason FROM kb_sources "
                f"WHERE status = 'rejected' AND updated_at > now() - interval '{WINDOW_DAYS} days' "
                "ORDER BY updated_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    return [
        AttentionItem(
            kind="kb_rejected",
            id=str(row[0]),
            title=f"“{row[1]}” was not added to your agent",
            detail=str(row[3] or "Your account manager left no note."),
            rule=None,
            occurred_at=row[2],
            href="/knowledge",
        )
        for row in rows
    ]


async def attention_queue(session: AsyncSession, *, limit: int = 50) -> dict[str, Any]:
    """All four sources, newest first, with per-kind counts for the nav badge."""
    groups = [
        await blocked_leads(session),
        await failed_deliveries(session),
        await stalled_campaigns(session),
        await knowledge_waiting(session),
    ]
    items = sorted(
        (item for group in groups for item in group),
        key=lambda item: item.occurred_at,
        reverse=True,
    )[:limit]
    counts: dict[str, int] = {}
    for group in groups:
        for item in group:
            counts[item.kind] = counts.get(item.kind, 0) + 1
    return {
        "total": sum(counts.values()),
        "counts": counts,
        "items": [
            {
                "kind": item.kind,
                "id": item.id,
                "title": item.title,
                "detail": item.detail,
                "rule": item.rule,
                "occurred_at": item.occurred_at,
                "href": item.href,
            }
            for item in items
        ],
    }


__all__ = [
    "BLOCK_REMEDIES",
    "WINDOW_DAYS",
    "AttentionItem",
    "attention_queue",
    "blocked_leads",
    "failed_deliveries",
    "knowledge_waiting",
    "stalled_campaigns",
]
