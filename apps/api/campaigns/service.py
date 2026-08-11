"""Campaign lifecycle: draft → launch gate → dispatch → retries (FLOWS §5).

The two design centers:

**The launch gate returns NAMED blockers, not a boolean.** SURFACES §2b requires the
launch button to be "disabled with reasons listed until green", and SEC-COMP §3 names
the reasons: template approved, number series matches classification (140⇔promotional,
160/standard⇔service-transactional), contacts DNC-scrubbed, calling window sane. A
boolean gate produces a support ticket; a named gate produces a to-do list.

**Launch scrubs; dispatch re-checks.** The DNC scrub at launch marks known-blocked
contacts `dnc_blocked` so the client sees the real dialable count before committing.
But a number can join the list BETWEEN launch and dial (an opt-out from another call,
hard rule 5's propagation requirement), so the dispatcher runs the full compliance
gate again per contact at dial time. The scrub is UX; the per-dial check is the law.

State transitions are CAS (BACKEND-PATTERNS §5): `rowcount == 0` means someone else
moved the row first, reported as INVALID_STATUS_TRANSITION, never silently retried.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.service import (
    DEFAULT_WINDOW,
    NO_CREDITS_REASON,
    SPEND_CAP_REASON,
    credits_exhausted,
    spend_capped,
)
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.ingest.service import normalize_phone

log = get_logger(__name__)

# Series ⇔ classification (DATA-MODEL §6): 140 dials promotions, 160/standard dials
# service and transactional. A mismatch is a DLT violation, not a preference.
SERIES_FOR_CLASSIFICATION: dict[str, tuple[str, ...]] = {
    "promotional": ("140",),
    "transactional": ("160", "standard"),
    "service": ("160", "standard"),
}

DEFAULT_RETRY_POLICY: dict[str, Any] = {"max_attempts": 3, "backoff_minutes": [30, 120]}


@dataclass(frozen=True, slots=True)
class LaunchBlocker:
    rule: str
    reason: str


def _parse_hhmm(value: object) -> time:
    """Strict HH:MM only — seconds, offsets and prose all fail the same way."""
    return datetime.strptime(str(value), "%H:%M").time()


def _validated_window(calling_hours: dict[str, Any]) -> dict[str, str]:
    """Validate a per-campaign calling window at CREATE time, so an unlawful window
    can never be stored — which is why launch_blockers needs no window check.

    The rule is NARROWING-ONLY: a client may shrink when their campaign dials
    (lunch-hour only), never widen past the platform's 09:00-21:00 IST window.
    That window is TRAI law (hard rule 5), not a default a client can override.
    """
    try:
        start = _parse_hhmm(calling_hours.get("start"))
        end = _parse_hhmm(calling_hours.get("end"))
    except (TypeError, ValueError):
        raise ProblemError(
            kind="validation",
            code="campaign_window_invalid",
            title="Invalid calling window",
            detail='calling_hours must be {"start": "HH:MM", "end": "HH:MM"} in IST.',
        ) from None
    if start >= end:
        raise ProblemError(
            kind="validation",
            code="campaign_window_invalid",
            title="Invalid calling window",
            detail="The window's start must be before its end.",
        )
    platform_start, platform_end = DEFAULT_WINDOW
    if start < platform_start or end > platform_end:
        raise ProblemError(
            kind="validation",
            code="campaign_window_outside_platform_hours",
            title="Calling window outside platform hours",
            detail=(
                "A campaign window may only narrow the platform's 09:00-21:00 IST "
                "calling hours. That window is the law (TRAI), not a default — "
                "nothing dials outside it."
            ),
        )
    # Re-serialize rather than echo the input: the stored shape is exactly two
    # canonical HH:MM strings, nothing a client smuggled alongside them.
    return {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}


def campaign_window_open(calling_hours: dict[str, Any] | None, now_ist: datetime) -> bool:
    """Is this campaign's OWN window open right now (IST)?

    None means "no extra restriction — the platform window applies", so True: this
    helper answers only the narrowing question. The platform's 09:00-21:00 IST
    bound is enforced separately by the per-dial compliance gate, which every
    claimed contact still passes through (defense in depth).
    """
    if calling_hours is None:
        return True
    try:
        start = _parse_hhmm(calling_hours["start"])
        end = _parse_hhmm(calling_hours["end"])
    except (KeyError, TypeError, ValueError):
        # A window we cannot read is a window we cannot honour: fail closed.
        # (Unreachable via create_campaign, which validates before storing.)
        return False
    return start <= now_ist.time() <= end


async def create_campaign(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str,
    classification: str,
    number_id: UUID | None,
    dlt_template_id: UUID | None,
    concurrency: int,
    calling_hours: dict[str, Any] | None = None,
) -> UUID:
    # Validated HERE, at the only write path, so the column can never hold a window
    # the dispatcher would have to second-guess. None = "platform window applies".
    window = _validated_window(calling_hours) if calling_hours is not None else None
    campaign_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, number_id, "
            "dlt_template_id, status, concurrency, retry_policy, calling_hours, "
            "created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :name, :cls, :nid, :dlt, 'draft', :conc, "
            "CAST(:retry AS jsonb), CAST(:window AS jsonb), now(), now())"
        ),
        {
            "id": campaign_id,
            "tid": tenant_id,
            "aid": agent_id,
            "name": name,
            "cls": classification,
            "nid": number_id,
            "dlt": dlt_template_id,
            "conc": concurrency,
            "retry": json.dumps(DEFAULT_RETRY_POLICY),
            "window": json.dumps(window) if window is not None else None,
        },
    )
    return campaign_id


async def add_contacts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    contacts: list[dict[str, Any]],
) -> dict[str, int]:
    """CSV rows → contact rows. Dedupe inside the upload AND against the campaign
    (UNIQUE(campaign_id, phone)); malformed numbers are counted, never guessed at."""
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    if status != "draft":
        raise ProblemError.business_rule(
            "campaign_not_draft", "Contacts can only be added to a draft campaign."
        )

    added, malformed, duplicate = 0, 0, 0
    seen: set[str] = set()
    for row in contacts:
        phone = normalize_phone(str(row.get("phone") or ""))
        if phone is None:
            malformed += 1
            continue
        if phone in seen:
            duplicate += 1
            continue
        seen.add(phone)
        result = await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, name, "
                "custom, status, attempts, dedupe_hash, created_at, updated_at) VALUES "
                "(:id, :tid, :cid, :phone, :name, CAST(:custom AS jsonb), 'pending', 0, :hash, "
                "now(), now()) ON CONFLICT (campaign_id, phone_e164) DO NOTHING"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": campaign_id,
                "phone": phone,
                "name": str(row.get("name") or "").strip() or None,
                "custom": json.dumps({k: v for k, v in row.items() if k not in ("phone", "name")}),
                "hash": hashlib.sha256(phone.encode()).hexdigest()[:16],
            },
        )
        if rowcount_of(result):
            added += 1
        else:
            duplicate += 1
    return {"added": added, "malformed": malformed, "duplicate": duplicate}


async def launch_blockers(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> list[LaunchBlocker]:
    """Every reason the launch button is disabled, by name (SEC-COMP §3).

    Deliberately exhaustive rather than fail-fast: the client fixes them as a list,
    not one 422 at a time.

    The rules that also live in the per-dial gate (`compliance.service.check_dispatch`)
    are asked HERE TOO, under the same names: an agent that may not place calls, a
    tenant at its spend cap, an empty prepaid wallet. Leaving them to dial time
    produces the worst possible outcome — a `running` campaign whose every contact is
    claimed, refused, refunded and rescheduled forever. The client watches a campaign
    that says "running" and never calls anyone, and nothing in the UI says why. The
    per-number rules (DNC, calling hours) stay at dial time only: they are per contact
    and per minute, and a campaign launched at 22:00 to dial tomorrow morning is
    correct, not blocked.
    """
    blockers: list[LaunchBlocker] = []
    row = (
        await session.execute(
            text(
                "SELECT c.status, c.classification, c.agent_id, c.dlt_template_id, "
                "  t.status AS template_status, t.classification AS template_cls, "
                "  n.series, n.dlt_status AS number_dlt_status, "
                "  a.status AS agent_status, a.disclosure_line, "
                "  a.direction AS agent_direction, a.deleted_at AS agent_deleted_at "
                "FROM campaigns c "
                "LEFT JOIN dlt_templates t ON t.id = c.dlt_template_id "
                "LEFT JOIN phone_numbers n ON n.id = c.number_id "
                "JOIN agents a ON a.id = c.agent_id "
                "WHERE c.id = :cid"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    (
        status,
        classification,
        _agent_id,
        template_id,
        template_status,
        template_cls,
        series,
        number_dlt_status,
        agent_status,
        disclosure,
        agent_direction,
        agent_deleted_at,
    ) = row

    if status not in ("draft", "scheduled"):
        blockers.append(LaunchBlocker("status", f"Campaign is {status}, not draft."))
    # `agent_missing` / `agent_inbound_only` are the gate's own names for these two —
    # the dispatcher would refuse every single contact with them.
    if agent_deleted_at is not None:
        blockers.append(
            LaunchBlocker("agent_missing", "The agent this campaign uses has been deleted.")
        )
    elif agent_status != "live":
        blockers.append(LaunchBlocker("agent_not_live", "The agent must be published first."))
    if agent_direction == "inbound":
        blockers.append(
            LaunchBlocker(
                "agent_inbound_only",
                "This agent only answers calls; it cannot place them.",
            )
        )
    if not disclosure or not str(disclosure).strip():
        blockers.append(LaunchBlocker("disclosure_missing", "The agent has no disclosure line."))

    # Tenant-level refusals, asked with the same functions the dial-time gate uses.
    if await spend_capped(session, tenant_id=tenant_id):
        blockers.append(LaunchBlocker("spend_cap", SPEND_CAP_REASON))
    if await credits_exhausted(session, tenant_id=tenant_id):
        blockers.append(LaunchBlocker("no_credits", NO_CREDITS_REASON))

    if template_id is None:
        blockers.append(
            LaunchBlocker("dlt_template_missing", "Attach an approved DLT voice template.")
        )
    elif template_status != "approved":
        blockers.append(
            LaunchBlocker("dlt_template_not_approved", f"The DLT template is {template_status}.")
        )
    elif template_cls != classification:
        blockers.append(
            LaunchBlocker(
                "dlt_template_mismatch",
                f"A {classification} campaign cannot use a {template_cls} template.",
            )
        )

    if series is None:
        blockers.append(LaunchBlocker("number_missing", "Attach a calling number."))
    else:
        if series not in SERIES_FOR_CLASSIFICATION.get(str(classification), ()):
            allowed = "/".join(SERIES_FOR_CLASSIFICATION.get(str(classification), ()))
            blockers.append(
                LaunchBlocker(
                    "number_series_mismatch",
                    f"A {classification} campaign must dial from a {allowed} number, not {series}.",
                )
            )
        # The number-side twin of the template check. `dlt_status` moves to `registered`
        # through an audited admin step for the same reason `set_template_status` does:
        # dialling from an unregistered header is the misclassification that gets the
        # traffic dropped as spam and the complaints filed against the client's PE.
        if number_dlt_status != "registered":
            blockers.append(
                LaunchBlocker(
                    "number_not_registered",
                    f"This number's DLT registration is {number_dlt_status}; only a "
                    "registered number may place campaign calls.",
                )
            )

    # Pending AND dialable are different numbers, and the difference is the whole point
    # of this blocker: the scrub launch is about to run marks every DNC-listed contact
    # terminally. Counting raw `pending` rows told the client "you have contacts" and
    # then launched a campaign with `dialable: 0` — a green button over an empty list.
    counts = (
        await session.execute(
            text(
                "SELECT count(*) AS pending, count(*) FILTER (WHERE NOT EXISTS ("
                "  SELECT 1 FROM dnc_list d WHERE d.phone_e164 = cc.phone_e164 "
                "  AND (d.tenant_id = :tid OR d.tenant_id IS NULL)"
                ")) AS dialable "
                "FROM campaign_contacts cc WHERE cc.campaign_id = :cid "
                "AND cc.status = 'pending'"
            ),
            {"cid": campaign_id, "tid": tenant_id},
        )
    ).first()
    pending, dialable = (int(counts[0] or 0), int(counts[1] or 0)) if counts else (0, 0)
    if not pending:
        blockers.append(LaunchBlocker("no_contacts", "The campaign has no dialable contacts."))
    elif not dialable:
        blockers.append(
            LaunchBlocker(
                "all_contacts_dnc",
                "Every number on this list has opted out of calls, so there is nothing "
                "left to dial.",
            )
        )

    return blockers


async def launch_campaign(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> dict[str, Any]:
    """The gate, then the scrub, then the CAS to `running`.

    Scrub-at-launch marks known-DNC contacts terminally, so the "N contacts will be
    dialled" number the client confirms is true. The per-dial re-check still runs —
    this is UX honesty, not the enforcement.
    """
    blockers = await launch_blockers(session, tenant_id=tenant_id, campaign_id=campaign_id)
    if blockers:
        raise ProblemError(
            kind="business_rule",
            code="campaign_launch_blocked",
            title="Campaign cannot launch",
            detail="One or more launch requirements are not met.",
            fields=[{"field": b.rule, "rule": b.rule, "message": b.reason} for b in blockers],
        )

    scrubbed = await session.execute(
        text(
            "UPDATE campaign_contacts SET status = 'dnc_blocked', updated_at = now() "
            "WHERE campaign_id = :cid AND status = 'pending' AND phone_e164 IN ("
            "  SELECT phone_e164 FROM dnc_list WHERE tenant_id = :tid OR tenant_id IS NULL"
            ")"
        ),
        {"cid": campaign_id, "tid": tenant_id},
    )

    result = await session.execute(
        text(
            "UPDATE campaigns SET status = 'running', launched_at = now(), updated_at = now() "
            "WHERE id = :cid AND status IN ('draft', 'scheduled')"
        ),
        {"cid": campaign_id},
    )
    if rowcount_of(result) == 0:
        raise InvalidStatusTransitionError("campaign", "non-draft", "running")

    dialable = (
        await session.execute(
            text(
                "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                "AND status = 'pending'"
            ),
            {"cid": campaign_id},
        )
    ).scalar()
    log.info(
        "campaign_launched",
        extra={
            "campaign_id": str(campaign_id),
            "dialable": int(dialable or 0),
            "dnc_scrubbed": rowcount_of(scrubbed),
        },
    )
    return {
        "status": "running",
        "dialable": int(dialable or 0),
        "dnc_scrubbed": rowcount_of(scrubbed),
    }


async def set_campaign_status(
    session: AsyncSession, *, campaign_id: UUID, to_status: str, from_statuses: tuple[str, ...]
) -> None:
    """pause/resume/cancel — all the same CAS shape."""
    placeholders = ", ".join(f"'{s}'" for s in from_statuses)
    result = await session.execute(
        text(
            f"UPDATE campaigns SET status = :to, updated_at = now() "
            f"WHERE id = :cid AND status IN ({placeholders})"
        ),
        {"to": to_status, "cid": campaign_id},
    )
    if rowcount_of(result) == 0:
        raise InvalidStatusTransitionError("campaign", f"not in {from_statuses}", to_status)


async def register_dlt_template(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    classification: str,
    body: str,
    dlt_ref: str | None,
) -> UUID:
    """Record the voice template the client registered with their DLT registrar.

    Created `submitted`, never `approved`: approval happens at the registrar, and a
    template we mark approved because we typed it in is how a campaign launches under a
    template the operator never actually registered. `set_template_status` is the
    separate, audited step that records what the registrar decided.
    """
    template_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, dlt_ref, "
            "status, created_at, updated_at) VALUES (:id, :tid, 'voice', :cls, :body, :ref, "
            "'submitted', now(), now())"
        ),
        {
            "id": template_id,
            "tid": tenant_id,
            "cls": classification,
            "body": body,
            "ref": dlt_ref,
        },
    )
    return template_id


async def set_template_status(
    session: AsyncSession, *, template_id: UUID, status: str, dlt_ref: str | None = None
) -> None:
    """What the registrar decided. `approved` is what unlocks the launch gate, so this
    is an audited admin action, not a field the client can edit."""
    result = await session.execute(
        text(
            "UPDATE dlt_templates SET status = :st, "
            "dlt_ref = COALESCE(:ref, dlt_ref), updated_at = now() WHERE id = :id"
        ),
        {"st": status, "ref": dlt_ref, "id": template_id},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("DLT template")


async def list_campaigns(session: AsyncSession) -> list[dict[str, Any]]:
    """Newest first, with the two counts the list actually needs.

    Counting in the query rather than per row: a client with thirty campaigns should
    cost one round trip, and `connected` is the only per-status number worth showing
    before you open one.
    """
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.name, c.classification, c.status, c.launched_at, c.created_at, "
                "  count(cc.id) AS contacts, "
                "  count(cc.id) FILTER (WHERE cc.status = 'connected') AS connected "
                "FROM campaigns c LEFT JOIN campaign_contacts cc ON cc.campaign_id = c.id "
                "GROUP BY c.id ORDER BY c.created_at DESC LIMIT 100"
            )
        )
    ).all()
    return [
        {
            "id": r[0],
            "name": r[1],
            "classification": r[2],
            "status": r[3],
            "launched_at": r[4],
            "created_at": r[5],
            "contacts": int(r[6] or 0),
            "connected": int(r[7] or 0),
        }
        for r in rows
    ]


async def campaign_progress(session: AsyncSession, campaign_id: UUID) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                "SELECT status, count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                "GROUP BY status"
            ),
            {"cid": campaign_id},
        )
    ).all()
    counts = {str(r[0]): int(r[1]) for r in rows}
    campaign = (
        await session.execute(
            text("SELECT status, launched_at, concurrency FROM campaigns WHERE id = :cid"),
            {"cid": campaign_id},
        )
    ).first()
    if campaign is None:
        raise ProblemError.not_found("Campaign")
    return {
        "status": campaign[0],
        "launched_at": campaign[1],
        "concurrency": campaign[2],
        "contacts": counts,
        "total": sum(counts.values()),
    }


__all__ = [
    "DEFAULT_RETRY_POLICY",
    "SERIES_FOR_CLASSIFICATION",
    "LaunchBlocker",
    "add_contacts",
    "campaign_progress",
    "campaign_window_open",
    "create_campaign",
    "launch_blockers",
    "launch_campaign",
    "list_campaigns",
    "register_dlt_template",
    "set_campaign_status",
    "set_template_status",
]
