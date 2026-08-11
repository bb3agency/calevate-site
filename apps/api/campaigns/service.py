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
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
) -> UUID:
    campaign_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, number_id, "
            "dlt_template_id, status, concurrency, retry_policy, created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :name, :cls, :nid, :dlt, 'draft', :conc, "
            "CAST(:retry AS jsonb), now(), now())"
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
    """
    blockers: list[LaunchBlocker] = []
    row = (
        await session.execute(
            text(
                "SELECT c.status, c.classification, c.agent_id, c.dlt_template_id, "
                "  t.status AS template_status, t.classification AS template_cls, "
                "  n.series, a.status AS agent_status, a.disclosure_line "
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
        agent_status,
        disclosure,
    ) = row

    if status not in ("draft", "scheduled"):
        blockers.append(LaunchBlocker("status", f"Campaign is {status}, not draft."))
    if agent_status != "live":
        blockers.append(LaunchBlocker("agent_not_live", "The agent must be published first."))
    if not disclosure or not str(disclosure).strip():
        blockers.append(LaunchBlocker("disclosure_missing", "The agent has no disclosure line."))

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
    elif series not in SERIES_FOR_CLASSIFICATION.get(str(classification), ()):
        allowed = "/".join(SERIES_FOR_CLASSIFICATION.get(str(classification), ()))
        blockers.append(
            LaunchBlocker(
                "number_series_mismatch",
                f"A {classification} campaign must dial from a {allowed} number, not {series}.",
            )
        )

    pending = (
        await session.execute(
            text(
                "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                "AND status = 'pending'"
            ),
            {"cid": campaign_id},
        )
    ).scalar()
    if not pending:
        blockers.append(LaunchBlocker("no_contacts", "The campaign has no dialable contacts."))

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
    "create_campaign",
    "launch_blockers",
    "launch_campaign",
    "set_campaign_status",
]
