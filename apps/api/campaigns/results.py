"""What a campaign achieved, per person and in total (D-773, FLOWS §5).

Everything is computed here, in SQL, under the caller's RLS session, and every list is
bounded: the per-contact list pages with a `limit` the route caps, and the summary's lists
are bounded by an enum (outcomes, sentiments) or a constant (`RECENT_LEADS`).

ONE OUTCOME VOCABULARY. A contact's own status says only connected, opted out, failed or
still waiting; whether an unconnected try was busy, unanswered or a voicemail is a fact
about its last CALL. `_OUTCOME_SQL` reads both, and both the list and the summary count
through it, so a filter chip and the number on it cannot disagree.

MONEY. What the campaign cost the client is the `usage` debits on `credit_ledger` for its
calls, keyed by call id (`billing.service.charge_for_call`), summed as NUMERIC and returned
as a Decimal (hard rule 7). It is the client's charge, never our cost (`usage_events.
unit_cost_paid` is not read here).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, get_args
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import ROUNDING
from apps.api.compliance.optout import OPTOUT_PURPOSE
from apps.api.core.errors import ProblemError
from apps.api.crm.outcomes import normalise as normalise_outcome
from apps.api.db.like import contains_pattern, suffix_pattern

ContactOutcome = Literal[
    "connected",
    "no_answer",
    "busy",
    "voicemail",
    "failed",
    "do_not_call",
    "calling",
    "not_called",
]
CONTACT_OUTCOMES: tuple[ContactOutcome, ...] = get_args(ContactOutcome)

#: How many of the campaign's leads the summary names.
RECENT_LEADS = 10
#: The most opt-outs one review page lists.
MAX_OPTOUTS_LISTED = 100

#: The contact rows with their outcome. `completed` and `no_answer` contact statuses are in
#: the CHECK and written by nothing; they map to the words they would mean.
_OUTCOME_SQL = """
    SELECT cc.id, cc.name, cc.phone_e164, cc.attempts, cc.last_attempt_at,
           cc.next_attempt_at, cc.last_call_id, cc.status, cc.created_at,
           CASE
             WHEN cc.status IN ('connected', 'completed') THEN 'connected'
             WHEN cc.status = 'dnc_blocked' THEN 'do_not_call'
             WHEN cc.status = 'dialing' THEN 'calling'
             WHEN cc.status = 'pending' AND cc.attempts = 0 THEN 'not_called'
             WHEN k.status IN ('busy', 'no_answer', 'voicemail') THEN k.status
             WHEN cc.status = 'no_answer' THEN 'no_answer'
             ELSE 'failed'
           END AS outcome
    FROM campaign_contacts cc
    LEFT JOIN calls k ON k.id = cc.last_call_id
    WHERE cc.campaign_id = :cid
"""


@dataclass(frozen=True, slots=True)
class ContactsPage:
    items: list[dict[str, Any]]
    total: int
    counts: dict[str, int]


async def _campaign_status(session: AsyncSession, campaign_id: UUID) -> str:
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    if status is None:
        raise ProblemError.not_found("Campaign")
    return str(status)


async def _outcome_counts(session: AsyncSession, campaign_id: UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            text(f"SELECT outcome, count(*) FROM ({_OUTCOME_SQL}) r GROUP BY outcome"),
            {"cid": campaign_id},
        )
    ).all()
    counts: dict[str, int] = dict.fromkeys(CONTACT_OUTCOMES, 0)
    for outcome, count in rows:
        counts[str(outcome)] = int(count)
    return counts


async def contacts_page(
    session: AsyncSession,
    *,
    campaign_id: UUID,
    outcome: ContactOutcome | None,
    search: str | None,
    limit: int,
    offset: int,
) -> ContactsPage:
    """One page of the campaign's people with their outcome, most recently tried first.

    `counts` covers the whole campaign whatever the filter, so every chip can show its
    number. `will_retry` is true only while the campaign can still call them again.
    """
    status = await _campaign_status(session, campaign_id)
    counts = await _outcome_counts(session, campaign_id)
    clauses: list[str] = []
    params: dict[str, Any] = {"cid": campaign_id, "limit": limit, "offset": offset}
    if outcome is not None:
        clauses.append("r.outcome = :outcome")
        params["outcome"] = outcome
    if search:
        clauses.append("(r.name ILIKE :search OR r.phone_e164 LIKE :phone_suffix)")
        params["search"] = contains_pattern(search)
        params["phone_suffix"] = suffix_pattern(search)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = int(
        (
            await session.execute(text(f"SELECT count(*) FROM ({_OUTCOME_SQL}) r {where}"), params)
        ).scalar()
        or 0
    )
    rows = (
        await session.execute(
            text(
                f"SELECT r.id, r.name, r.phone_e164, r.outcome, r.attempts, r.last_attempt_at, "
                f"r.next_attempt_at, r.last_call_id, r.status FROM ({_OUTCOME_SQL}) r {where} "
                # A total order, so OFFSET pages neither repeat nor skip a row.
                "ORDER BY r.last_attempt_at DESC NULLS LAST, r.created_at, r.id "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).all()
    can_retry = status in ("running", "paused")
    items = []
    for r in rows:
        will_retry = can_retry and r[8] == "pending" and int(r[4]) > 0
        items.append(
            {
                "id": r[0],
                "name": r[1],
                "phone_e164": r[2],
                "outcome": r[3],
                "attempts": int(r[4]),
                "last_attempt_at": r[5],
                "will_retry": will_retry,
                "next_attempt_at": r[6] if will_retry else None,
                "call_id": r[7],
            }
        )
    return ContactsPage(items=items, total=total, counts=counts)


async def summary(
    session: AsyncSession, *, campaign_id: UUID, include_spend: bool
) -> dict[str, Any]:
    """The campaign's totals: reach, how the conversations went, leads, and spend.

    `pickup_rate` is connected people over people tried at least once, None until somebody
    has been tried. `average_call_s` covers connected calls only, because an unanswered
    ring has no length worth averaging. Spend is None for a role that may not see billing.
    """
    await _campaign_status(session, campaign_id)
    counts = await _outcome_counts(session, campaign_id)
    tried = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                    "AND last_call_id IS NOT NULL"
                ),
                {"cid": campaign_id},
            )
        ).scalar()
        or 0
    )
    calls = (
        await session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE status = 'completed'), "
                "  round(avg(duration_s) FILTER (WHERE status = 'completed')), "
                "  coalesce(sum(duration_s) FILTER (WHERE status = 'completed'), 0) "
                "FROM calls WHERE campaign_id = :cid"
            ),
            {"cid": campaign_id},
        )
    ).one()
    tag_rows = (
        await session.execute(
            text(
                "SELECT outcome_tag, count(*) FROM calls WHERE campaign_id = :cid "
                "AND status = 'completed' AND outcome_tag IS NOT NULL GROUP BY outcome_tag"
            ),
            {"cid": campaign_id},
        )
    ).all()
    tags: dict[str, int] = {}
    for stored, count in tag_rows:
        word = normalise_outcome(stored)
        if word is not None:
            tags[word] = tags.get(word, 0) + int(count)
    sentiment_rows = (
        await session.execute(
            text(
                "SELECT sentiment, count(*) FROM calls WHERE campaign_id = :cid "
                "AND status = 'completed' AND sentiment IS NOT NULL GROUP BY sentiment"
            ),
            {"cid": campaign_id},
        )
    ).all()
    leads = (
        await session.execute(
            text(
                "SELECT count(DISTINCT l.id), count(DISTINCT l.id) FILTER (WHERE l.status = 'hot') "
                "FROM calls k JOIN leads l ON l.id = k.lead_id "
                "WHERE k.campaign_id = :cid AND l.deleted_at IS NULL"
            ),
            {"cid": campaign_id},
        )
    ).one()
    recent = (
        await session.execute(
            text(
                "SELECT l.id, l.name, l.status, max(l.updated_at) AS updated_at "
                "FROM calls k JOIN leads l ON l.id = k.lead_id "
                "WHERE k.campaign_id = :cid AND l.deleted_at IS NULL "
                "GROUP BY l.id, l.name, l.status "
                "ORDER BY (l.status = 'hot') DESC, updated_at DESC, l.id DESC LIMIT :limit"
            ),
            {"cid": campaign_id, "limit": RECENT_LEADS},
        )
    ).all()
    optouts = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM consent_ledger cl JOIN calls k ON k.id = cl.call_id "
                    "WHERE k.campaign_id = :cid AND cl.status = 'withdrawn' "
                    "AND cl.purpose = :purpose"
                ),
                {"cid": campaign_id, "purpose": OPTOUT_PURPOSE},
            )
        ).scalar()
        or 0
    )
    spend_inr: Decimal | None = None
    if include_spend:
        spent = (
            await session.execute(
                text(
                    "SELECT coalesce(-sum(l.delta), 0) FROM calls k JOIN credit_ledger l "
                    "ON l.tenant_id = k.tenant_id AND l.reason = 'usage' AND l.ref = k.id::text "
                    "WHERE k.campaign_id = :cid AND l.delta < 0"
                ),
                {"cid": campaign_id},
            )
        ).scalar()
        spend_inr = Decimal(spent or 0).quantize(Decimal("0.01"), rounding=ROUNDING)
    connected = counts["connected"]
    return {
        "contacts": sum(counts.values()),
        "outcomes": counts,
        "tried": tried,
        "pickup_rate": round(connected / tried, 3) if tried else None,
        "calls": int(calls[0]),
        "connected_calls": int(calls[1]),
        "average_call_s": int(calls[2]) if calls[2] is not None else None,
        "talk_seconds": int(calls[3]),
        "outcome_tags": tags,
        "sentiment": {str(s): int(c) for s, c in sentiment_rows},
        "leads": int(leads[0]),
        "hot_leads": int(leads[1]),
        "recent_leads": [
            {"id": r[0], "name": r[1], "status": r[2], "updated_at": r[3]} for r in recent
        ],
        "opt_outs": optouts,
        "credits_spent_inr": spend_inr,
    }


async def opt_outs(session: AsyncSession, *, campaign_id: UUID, limit: int) -> list[dict[str, Any]]:
    """The people on this campaign who asked not to be called, newest first.

    What each said is the consent ledger's own evidence phrase, which was passed through
    the transcript redactor before it was stored (`compliance/optout.detect_opt_out`), so
    a number spoken inside it is already masked. Never the raw transcript.
    """
    await _campaign_status(session, campaign_id)
    rows = (
        await session.execute(
            text(
                "SELECT cl.call_id, cl.captured_at, cl.evidence->>'matched', "
                "  (SELECT cc.name FROM campaign_contacts cc WHERE cc.campaign_id = k.campaign_id "
                "   AND cc.phone_e164 = k.to_e164 LIMIT 1) "
                "FROM consent_ledger cl JOIN calls k ON k.id = cl.call_id "
                "WHERE k.campaign_id = :cid AND cl.status = 'withdrawn' AND cl.purpose = :purpose "
                "ORDER BY cl.captured_at DESC, cl.id DESC LIMIT :limit"
            ),
            {"cid": campaign_id, "purpose": OPTOUT_PURPOSE, "limit": limit},
        )
    ).all()
    return [
        {"call_id": r[0], "at": r[1], "words_redacted": r[2], "contact_name": r[3]} for r in rows
    ]


__all__ = [
    "CONTACT_OUTCOMES",
    "MAX_OPTOUTS_LISTED",
    "RECENT_LEADS",
    "ContactOutcome",
    "ContactsPage",
    "contacts_page",
    "opt_outs",
    "summary",
]
