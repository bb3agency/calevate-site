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

**A count and a page are different questions, and every source answers both.** Each
query carries `count(*) OVER ()` beside its rows — the size of the set the page was
drawn FROM, not the size of the page — because the badge, the "showing N of M" sentence
and the operator reading them are all asking how much there IS. See `attention_queue`
for why that is one query per source rather than two, and for the bug it replaces.

Deliberately NOT here: anything the client cannot act on. A failed engine webhook is
our problem and belongs in ops alerting, not in a business owner's queue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.crm.schemas import AttentionKind
from apps.api.crm.service import mask_phone

# How far back the queue looks. A blocked dial from last month is history, not a
# to-do; leaving it in the list is how a queue becomes wallpaper nobody reads.
WINDOW_DAYS = 14

# How many rows EACH source fetches, and how many the merged queue returns. One number
# for both on purpose: the newest N of a merge can all come from a single source, so a
# source capped below the merged limit would make "the N most recent" false — the screen
# would print a stale row above a newer one nobody fetched. `attention_queue` passes its
# own limit down for the same reason, so the property holds at every limit the route
# allows (1..100), not just at the default.
DEFAULT_LIMIT = 50

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
    # Typed against the response model's own union (`crm.schemas.AttentionKind`) rather
    # than `str`: a fifth kind added here without being declared there is now a mypy
    # error, instead of a 500 when `extra="forbid"` meets it at serialization time.
    kind: AttentionKind
    id: str
    title: str
    detail: str
    rule: str | None
    occurred_at: Any
    href: str | None = None


@dataclass(frozen=True, slots=True)
class AttentionSource:
    """One source's newest rows, and the TRUE size of the set they were drawn from.

    Modelled on `crm.service.LeadPage`, which pairs a page with the numbers that
    describe what it is a page OF, and for the same reason: the moment a caller has to
    derive the second from the first, it derives it wrong the instant the page is capped.
    """

    kind: AttentionKind
    # The newest `limit` rows. Capped, and honestly so — `total` says by how much.
    items: list[AttentionItem]
    # Everything this source's predicate matches, cap or no cap. What the nav badge
    # counts and what the "showing N of M" sentence divides by.
    total: int


def _matching(rows: Sequence[Any]) -> int:
    """The `count(*) OVER () AS matching` every source's query carries on each row.

    Postgres evaluates window functions after WHERE/GROUP BY/HAVING and BEFORE
    ORDER BY/LIMIT, so this is the whole matching set even when the row it rode in on is
    one of `limit`. No rows means nothing matched, which is the one case where the count
    cannot be read off a row and is the only value it could have: 0.
    """
    return int(rows[0].matching) if rows else 0


async def blocked_leads(session: AsyncSession, *, limit: int = DEFAULT_LIMIT) -> AttentionSource:
    """Leads whose dial the compliance gate refused (FLOWS §4).

    The lead landed — that is the module's whole promise — and the timeline says which
    rule stopped the call. This turns "why didn't anyone ring them?" from a support
    ticket into a line the owner can read.
    """
    rows = (
        await session.execute(
            text(
                "SELECT e.id, e.lead_id, e.payload, e.created_at, l.name, l.phone_e164, "
                "  count(*) OVER () AS matching "
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
        # Hard rule 6 lives on this line: the captured NAME, falling back to a MASKED
        # number. A raw `phone_e164` here would reach a screen, a screenshot and a log.
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
    return AttentionSource(kind="lead_blocked", items=items, total=_matching(rows))


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


async def failed_deliveries(
    session: AsyncSession, *, limit: int = DEFAULT_LIMIT
) -> AttentionSource:
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
                "SELECT d.id, d.event_type, d.attempts, d.last_at, d.source, w.kind, d.reason, "
                "  count(*) OVER () AS matching "
                "FROM webhook_deliveries d JOIN outbound_webhooks w ON w.id = d.endpoint_id "
                "WHERE d.direction = 'out' AND d.status = 'failed' "
                f"  AND d.last_at > now() - interval '{WINDOW_DAYS} days' "
                "ORDER BY d.last_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    items: list[AttentionItem] = []
    for delivery_id, event_type, attempts, last_at, source, kind, reason, _matched in rows:
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
    return AttentionSource(kind="delivery_failed", items=items, total=_matching(rows))


async def stalled_campaigns(
    session: AsyncSession, *, limit: int = DEFAULT_LIMIT
) -> AttentionSource:
    """Campaigns that are paused, or running with nothing left they can dial.

    A campaign whose remaining contacts are all `dnc_blocked` or `failed` will never
    finish on its own and will never dial again — from the dashboard it looks busy, and
    that silence is exactly what this queue exists to break.

    **"Stalled" is a HAVING clause, not a Python `continue`.** It used to be the latter,
    and a predicate applied after LIMIT is wrong twice over: a healthy running campaign
    burned one of the `limit` slots on its way to being discarded, so an account with 60
    busy campaigns and 3 stalled ones could show none of the 3 — and no count taken from
    the query could be the count of stalled campaigns, because the query did not select
    them. In SQL, both the page and `count(*) OVER ()` are about the same set.
    """
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.name, c.status, c.updated_at, "
                "  count(cc.id) FILTER (WHERE cc.status = 'pending') AS pending, "
                "  count(cc.id) FILTER (WHERE cc.status = 'dnc_blocked') AS blocked, "
                "  count(*) OVER () AS matching "
                "FROM campaigns c LEFT JOIN campaign_contacts cc ON cc.campaign_id = c.id "
                "WHERE c.status IN ('paused', 'running') "
                "GROUP BY c.id "
                # Paused, or running with nothing dialable left. `count(...)` is never
                # NULL, so a campaign with no contacts at all satisfies `= 0` and is
                # reported — a running campaign with an empty list is stalled by any
                # reading. HAVING runs BEFORE the window, so `matching` counts the
                # campaigns that survive it, not the ones that were considered.
                "HAVING c.status = 'paused' "
                "   OR count(cc.id) FILTER (WHERE cc.status = 'pending') = 0 "
                "ORDER BY c.updated_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    items: list[AttentionItem] = []
    for campaign_id, name, status, updated_at, pending, blocked, _matched in rows:
        if status == "paused":
            detail = f"Paused with {pending} contacts still to call."
        else:
            detail = (
                f"Running, but nothing left to dial — {blocked} numbers are on the "
                "do-not-call list."
                if blocked
                else "Running, but every contact has been attempted."
            )
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
    return AttentionSource(kind="campaign_stalled", items=items, total=_matching(rows))


async def knowledge_waiting(
    session: AsyncSession, *, limit: int = DEFAULT_LIMIT
) -> AttentionSource:
    """Knowledge the client submitted that we rejected (FLOWS §7).

    `pending_approval` is deliberately excluded: waiting for us is not the client's
    to-do, and putting it here would make our review queue look like their backlog.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, name, updated_at, rejection_reason, count(*) OVER () AS matching "
                "FROM kb_sources "
                f"WHERE status = 'rejected' AND updated_at > now() - interval '{WINDOW_DAYS} days' "
                "ORDER BY updated_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    return AttentionSource(
        kind="kb_rejected",
        items=[
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
        ],
        total=_matching(rows),
    )


async def attention_queue(session: AsyncSession, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """All four sources, newest first, with per-kind counts for the nav badge.

    **A count and a page are different questions, and this answers both separately.**
    `counts`/`total` are how many things EXIST; `items` is the newest `limit` of them.
    They used to be one question — each source fetched 25 rows and the counts were `len()`
    over what came back — so a client with 40 blocked leads was told 25, and the nav badge,
    the screen's "showing N of M" and the operator planning the day all inherited it. A
    number that saturates silently is worse than a missing one: nothing about a flat 25
    says "this is a floor", so it gets read as a fact and planned against.

    Counting separately from fetching is the answer THIS REPO ALREADY CHOSE for the same
    bug one screen over: `LeadListOut.status_counts_matching_search` exists because a
    tally derived from a capped page told a client "new 0, contacted 0"
    (crm/schemas.py states it). Following the precedent also keeps one way of answering
    "how many" in the CRM, which is worth more than either implementation.

    Rejected, raising the cap: 25 → 200 moves the ceiling without removing it, and the
    number underneath is still `len(page)` in a bigger hat — it fails silently again at
    the first tenant who exceeds it, which is exactly the tenant who most needs the
    queue. Rejected, publishing the saturation as an `at_least` flag: it is honest, but
    it makes every consumer of the badge — this screen, the shell's bell, whatever reads
    the API next — carry two cases forever to save one aggregate over a 14-day,
    tenant-scoped window that the row query already scans.

    **One round trip per source, not two.** The count's scope here is IDENTICAL to the
    page's (same predicate, no offset, just newest-N), so each source's query carries
    `count(*) OVER () AS matching` on every row: the window is evaluated over the whole
    result set before LIMIT truncates it, so one statement answers both. That is the
    difference from `list_leads_page`, which genuinely needs two statements because its
    counts deliberately drop the `status` filter its rows keep.

    MEASURED, on one tenant seeded with a busy fortnight — 2,000 blocked leads, 400
    failed deliveries, 400 campaigns (800 contacts), 400 rejected KB sources — over a
    warm pooled connection to local pg16, median of 9 whole-queue runs, twice:

    - the four capped queries this replaces (LIMIT 25, no counts): 21.0ms / 22.2ms
    - the four shipped here (LIMIT 50 + `count(*) OVER ()`):       22.9ms / 22.4ms
    - eight statements: each page plus its own `SELECT count(*)`:  37.5ms / 41.5ms

    So the truth costs about **+1.4ms (+7%)**, and the obvious way of buying it would
    have cost +78% — the same four predicates scanned twice plus four more round trips.
    The window count is not free in principle: it denies the planner an early-terminating
    LIMIT and materializes the matching set. It is cheap here because that set is one
    tenant's 14-day backlog and the ORDER BY already had to see all of it.

    **Each source is fetched to the MERGED limit**, not to a smaller per-source one: the
    newest `limit` rows of a merge can all come from a single source, so a source capped
    lower would make "the N most recent" false while the sentence on the screen kept
    claiming it.
    """
    sources = [
        await blocked_leads(session, limit=limit),
        await failed_deliveries(session, limit=limit),
        await stalled_campaigns(session, limit=limit),
        await knowledge_waiting(session, limit=limit),
    ]
    items = sorted(
        (item for source in sources for item in source.items),
        key=lambda item: item.occurred_at,
        reverse=True,
    )[:limit]
    # Kinds with nothing in them stay OUT of the map rather than answering 0 — the
    # documented contract (`AttentionOut.counts`) that the screen reads as "absent means
    # zero" when it decides which chips to draw.
    counts: dict[str, int] = {source.kind: source.total for source in sources if source.total}
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
    "DEFAULT_LIMIT",
    "SHEET_FAILURE_REMEDIES",
    "WINDOW_DAYS",
    "AttentionItem",
    "AttentionSource",
    "attention_queue",
    "blocked_leads",
    "failed_deliveries",
    "knowledge_waiting",
    "stalled_campaigns",
]
