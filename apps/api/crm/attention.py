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


# What a failed SHEETS delivery means, in the words of the person who has to fix it.
# Keyed by the authored reason codes in `apps/workers/sheets_sync.py` and
# `apps/workers/google_sheets.py` — never by vendor prose, which is untrusted text that
# can quote the lead row we handed Google (hard rule 6).
#
# Every one of these is a sentence a business owner can act on WITHOUT a support call,
# which is the entire test for whether a row belongs in this queue. The ones they cannot
# act on say so and name us as the party who must, rather than leaving a red row with an
# error code on it and no next step.
SHEET_FAILURE_REMEDIES: dict[str, str] = {
    "sheet_not_shared": (
        "We do not have permission to write to your spreadsheet. Open it, click Share, "
        "and give Editor access to the Calevate address your account manager gave you."
    ),
    "spreadsheet_not_found": (
        "That spreadsheet no longer exists, or it was moved to a different account. "
        "Create the endpoint again with the new link."
    ),
    "worksheet_not_found": (
        "The tab we were told to write to is not in that spreadsheet any more. Rename "
        "it back, or set the endpoint up again with the tab you are using now."
    ),
    "no_credential_ref": (
        "Your Google Sheets connection is not finished on our side yet — nothing for "
        "you to do. Contact support if leads are not appearing within a day."
    ),
    "credential_ref_unknown": (
        "Your Google Sheets connection is not finished on our side yet — nothing for "
        "you to do. Contact support if leads are not appearing within a day."
    ),
    "google_credential_unresolvable": (
        "Our connection to Google needs attention — nothing for you to do. We have been alerted."
    ),
    "google_auth_failed": (
        "Our connection to Google needs attention — nothing for you to do. We have been alerted."
    ),
    "google_rate_limited": (
        "Google was busy and would not take the row. We will keep trying; no action "
        "needed unless this repeats for hours."
    ),
    "google_unavailable": (
        "Google Sheets was unavailable. We will keep trying; no action needed unless "
        "this repeats for hours."
    ),
    "dedupe_probe_failed": (
        "We could not check your sheet before writing, so we did not write — that is "
        "deliberate, it prevents a duplicate row. We will try again."
    ),
    "dev_sink_refused_outside_local": (
        "Google Sheets delivery is misconfigured on our side — nothing for you to do. "
        "We have been alerted."
    ),
    "no_spreadsheet_configured": (
        "This endpoint has no valid spreadsheet link. Set it up again with the URL from "
        "your browser while the sheet is open."
    ),
}


def _sheet_failure_detail(reason: str | None) -> str:
    """One sheets failure → one sentence. Unknown codes degrade to something honest.

    A reason we have not written copy for still produces a row that says what happened
    and who is dealing with it, rather than an empty detail or the raw code — the same
    reasoning as `BLOCK_REMEDIES` falling through to the rule name.
    """
    if reason and reason in SHEET_FAILURE_REMEDIES:
        return SHEET_FAILURE_REMEDIES[reason]
    if reason and reason.startswith("provider_not_implemented"):
        return (
            "Google Sheets delivery is not switched on for this account yet — nothing "
            "for you to do. We have been alerted."
        )
    return (
        "We could not write the row to your spreadsheet. Check that it is still shared "
        "with us, or contact support."
    )


async def failed_deliveries(session: AsyncSession, *, limit: int = 25) -> list[AttentionItem]:
    """Outbound deliveries that did not arrive (D-23) — BOTH kinds, worded per kind.

    Scoped through `outbound_webhooks` because `webhook_deliveries` has no RLS policy
    of its own by design — see migration 4be32bf3d12c. That join is also what makes the
    per-kind wording possible: `kind` lives on the endpoint, not on the delivery.

    The two kinds fail in genuinely different ways and the copy has to follow. A webhook
    failure is a statement about a server the client operates ("returns 2xx"); a sheets
    failure is usually a statement about a SHARING decision they made in a Google UI, and
    telling them to check their HTTP status codes would be advice about a thing they do
    not have. Same queue, same query, same row shape — only the sentence differs.
    """
    rows = (
        await session.execute(
            text(
                "SELECT d.id, d.event_type, d.attempts, d.last_at, d.source, w.kind, d.reason "
                "FROM webhook_deliveries d JOIN outbound_webhooks w ON w.id = d.endpoint_id "
                "WHERE d.direction = 'out' AND d.status = 'failed' "
                f"  AND d.last_at > now() - interval '{WINDOW_DAYS} days' "
                "ORDER BY d.last_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    items: list[AttentionItem] = []
    for delivery_id, event_type, attempts, last_at, source, kind, reason in rows:
        if kind == "google_sheets":
            title = f"{event_type} did not reach your spreadsheet"
            detail = _sheet_failure_detail(reason)
            # `rule` is what the client-facing screens group and filter on. Naming the
            # reason here is what lets a support person see six identical
            # `sheet_not_shared` rows and fix one thing.
            rule = reason if reason in SHEET_FAILURE_REMEDIES else None
        else:
            title = f"{event_type} did not reach your system"
            detail = (
                f"Your endpoint answered {source or 'an error'} after {attempts} attempts. "
                "Check that it is reachable and returns 2xx."
            )
            rule = None
        items.append(
            AttentionItem(
                kind="delivery_failed",
                id=str(delivery_id),
                title=title,
                detail=detail,
                rule=rule,
                occurred_at=last_at,
                href="/integrations",
            )
        )
    return items


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
    "SHEET_FAILURE_REMEDIES",
    "WINDOW_DAYS",
    "AttentionItem",
    "attention_queue",
    "blocked_leads",
    "failed_deliveries",
    "knowledge_waiting",
    "stalled_campaigns",
]
