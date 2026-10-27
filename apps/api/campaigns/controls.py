"""What a client can do to a campaign besides launch it and pause it (D-773).

Edit and delete a draft, stop a campaign for good, copy one (optionally with the people it
never reached), add CRM leads to one, confirm a complaint-spike review, and the two
automatic pauses about money: out of credit and the monthly spending cap.

Every state change is a compare-and-swap on `campaigns.status` (BACKEND-PATTERNS §5); the
routes write the audit rows, except the automatic ones here, which have no route and write
their own as `system`.

THE TWO MONEY PAUSES BEHAVE DIFFERENTLY, ON PURPOSE.

* **Out of credit resumes by itself.** A top-up that takes the wallet back over zero is
  published by `billing.service.record_entry` as the `apply_inbound_credit_state` job,
  which already brings the client's answering agents back; it calls
  `resume_campaigns_after_credit` too, so one edge restarts both. The client paused
  nothing and decided nothing: they ran out, they paid, the calls continue.
* **The spending cap does not.** A cap is a brake the client (or their agreed plan) set on
  purpose, and raising it, or a new month starting, is a decision about money, not about
  whether to start ringing people again. A campaign that silently restarted at 09:00 on
  the 1st would be the surprise the cap exists to prevent. The client presses Resume, which
  is refused while the cap still binds.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.lifecycle import assert_assignable
from apps.api.campaigns.service import (
    add_contacts,
    create_campaign,
    set_campaign_status,
    validated_window,
)
from apps.api.compliance.audit import write_audit
from apps.api.compliance.registration import refuse_promotional_without_registration
from apps.api.compliance.service import (
    NO_CREDITS_REASON,
    SPEND_CAP_REASON,
    credits_exhausted,
    spend_capped,
)
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.ownership import assert_visible
from apps.api.db.result import rowcount_of
from apps.api.db.transition import transition_status

log = get_logger(__name__)

#: The most leads one "add from my leads" request may add. The same ceiling as one CSV
#: upload (`routes.AddContactsIn`), so the two ways in cannot differ in what they allow.
MAX_LEADS_PER_ADD = 5000
#: The most contacts one removal may name.
MAX_CONTACTS_PER_REMOVE = 1000

#: The columns a draft edit may set, and nothing else: the SET clause is built from these
#: names only, never from a caller's keys.
_EDITABLE = (
    "name",
    "agent_id",
    "number_id",
    "classification",
    "concurrency",
    "calling_hours",
    "retry_policy",
)
_JSON_COLUMNS = frozenset({"calling_hours", "retry_policy"})

#: Contact statuses that mean "this person was never reached": still waiting, or the tries
#: ran out. `connected` was reached and `dnc_blocked` asked not to be called; `dialing` is a
#: call in progress. `no_answer` is in the CHECK and written by nothing, kept here so a row
#: carrying it is not silently dropped from a re-call.
UNREACHED_STATUSES = ("pending", "failed", "no_answer")

AccountPauseReason = Literal["out_of_credit", "spend_cap"]


async def _status_or_404(session: AsyncSession, campaign_id: UUID) -> str:
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    if status is None:
        raise ProblemError.not_found("Campaign")
    return str(status)


def _not_a_draft(status: str, action: str) -> ProblemError:
    return ProblemError.business_rule(
        "campaign_not_draft",
        f"Only a draft can be {action}. This campaign is {status}.",
        remediation=(
            "Cancel its start to turn it back into a draft, or stop it for good."
            if status == "scheduled"
            else "Duplicate it to start a new draft from the same settings."
        ),
    )


async def update_draft(
    session: AsyncSession, *, campaign_id: UUID, changes: dict[str, Any]
) -> list[str]:
    """Change a draft's settings. Returns the names of the columns written.

    Only a DRAFT: a scheduled campaign is a start somebody already authorised, and changing
    who it calls with or how often behind that authorisation would make the start mean
    something else. Every id is resolved under the caller's own RLS before it is stored
    (`db/ownership.py`), and the agent must still be assignable (D-440), exactly as at create.
    """
    unknown = set(changes) - set(_EDITABLE)
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    if not changes:
        await _status_or_404(session, campaign_id)
        return []
    if "agent_id" in changes:
        await assert_visible(session, "agent", changes["agent_id"])
        await assert_assignable(session, changes["agent_id"])
    if "number_id" in changes:
        await assert_visible(session, "phone_number", changes["number_id"])
    if "classification" in changes:
        await refuse_promotional_without_registration(
            session, classification=str(changes["classification"])
        )
    values = dict(changes)
    if values.get("calling_hours") is not None:
        values["calling_hours"] = validated_window(values["calling_hours"])

    assignments: list[str] = []
    params: dict[str, Any] = {"cid": campaign_id}
    for column in _EDITABLE:
        if column not in values:
            continue
        if column in _JSON_COLUMNS:
            assignments.append(f"{column} = CAST(:{column} AS jsonb)")
            params[column] = None if values[column] is None else json.dumps(values[column])
        else:
            assignments.append(f"{column} = :{column}")
            params[column] = values[column]
    result = await session.execute(
        text(
            f"UPDATE campaigns SET {', '.join(assignments)}, updated_at = now() "
            "WHERE id = :cid AND status = 'draft'"
        ),
        params,
    )
    if rowcount_of(result) == 0:
        raise _not_a_draft(await _status_or_404(session, campaign_id), "edited")
    return [column for column in _EDITABLE if column in values]


async def remove_contacts(
    session: AsyncSession, *, campaign_id: UUID, contact_ids: list[UUID]
) -> int:
    """Take people off a campaign that has not started. Returns how many were removed.

    Only contacts never tried: a row with an attempt is the record of a call that happened,
    which a later re-run of a repeating campaign still has to be able to show.
    """
    status = await _status_or_404(session, campaign_id)
    if status not in ("draft", "scheduled"):
        raise ProblemError.business_rule(
            "campaign_not_draft",
            "People can only be taken off a campaign before it starts calling.",
        )
    result = await session.execute(
        text(
            "DELETE FROM campaign_contacts WHERE campaign_id = :cid AND id = ANY(:ids) "
            "AND attempts = 0 AND status = 'pending'"
        ),
        {"cid": campaign_id, "ids": list(dict.fromkeys(contact_ids))},
    )
    return rowcount_of(result)


async def delete_draft(
    session: AsyncSession, *, campaign_id: UUID
) -> Literal["deleted", "stopped"]:
    """Delete a draft, or keep it as stopped when something else points at it.

    A draft that never dialled and that no evidence row names is deleted, contacts and all
    (they cascade). A draft with a history keeps its row and becomes `cancelled`, because
    deleting it would either orphan its calls (`calls.campaign_id` is no foreign key) or
    try to null the campaign pointer on an append-only evidence row
    (`preference_scrub_runs`), which the ledger trigger refuses.
    That happens to a repeating campaign that ran and was then unscheduled back to draft.

    The row is locked first, so a concurrent launch either finds it gone or waits.
    """
    row = (
        await session.execute(
            text(
                "SELECT c.status, c.launched_at IS NOT NULL "
                "  OR EXISTS (SELECT 1 FROM calls k WHERE k.campaign_id = c.id) "
                "  OR EXISTS (SELECT 1 FROM preference_scrub_runs p WHERE p.campaign_id = c.id) "
                "FROM campaigns c WHERE c.id = :cid FOR UPDATE OF c"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    if row[0] != "draft":
        raise _not_a_draft(str(row[0]), "deleted")
    if row[1]:
        await session.execute(
            text(
                "UPDATE campaigns SET status = 'cancelled', schedule = NULL, updated_at = now() "
                "WHERE id = :cid AND status = 'draft'"
            ),
            {"cid": campaign_id},
        )
        return "stopped"
    await session.execute(
        text("DELETE FROM campaigns WHERE id = :cid AND status = 'draft'"), {"cid": campaign_id}
    )
    return "deleted"


async def stop_campaign(session: AsyncSession, *, campaign_id: UUID) -> bool:
    """Stop for good: running, paused or scheduled → cancelled. True when this call moved it.

    The people not yet called stay `pending` and are never dialled: the dispatcher claims
    only for `running` campaigns. A call already ringing finishes, and its result still
    lands on its contact. The repeat goes too (`schedule = NULL`), since a stopped campaign
    with a next Tuesday is not stopped. Idempotent like pause: stopping a stopped campaign
    answers success without a second audit row.
    """
    return await transition_status(
        session,
        table="campaigns",
        entity="Campaign",
        row_id=campaign_id,
        to_status="cancelled",
        from_statuses=("running", "paused", "scheduled"),
        extra_set=(
            "schedule = NULL, auto_pause_reason = NULL, "
            "paused_by_maintenance_id = NULL, paused_by_heal_id = NULL"
        ),
    )


async def duplicate_campaign(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    source_id: UUID,
    name: str | None,
    with_unreached: bool,
) -> tuple[UUID, int]:
    """A new draft from another campaign's settings; with `with_unreached`, also its
    contacts that were never reached. Returns the new id and how many contacts it got.

    The consent declaration is NOT copied: it is a statement the client makes about a list,
    and the gate asks for it again on the copy. The copilot's `campaign_clone` calls this.

    Re-calling needs the source to be finished (completed or stopped): while it runs, its
    own retries are still working through the same people.
    """
    row = (
        await session.execute(
            text(
                "SELECT name, agent_id, classification, number_id, dlt_template_id, "
                "concurrency, calling_hours, retry_policy, status "
                "FROM campaigns WHERE id = :cid"
            ),
            {"cid": source_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    if with_unreached and row[8] not in ("completed", "cancelled"):
        raise ProblemError.business_rule(
            "campaign_still_running",
            "People can be called again once this campaign has finished or been stopped.",
            remediation="Stop it for good first, or wait for it to finish its retries.",
        )
    prefix = "Call again: " if with_unreached else "Copy of "
    new_name = (name or f"{prefix}{row[0]}").strip()[:120]
    campaign_id = await create_campaign(
        session,
        tenant_id=tenant_id,
        agent_id=UUID(str(row[1])),
        name=new_name,
        classification=str(row[2]),
        number_id=None if row[3] is None else UUID(str(row[3])),
        dlt_template_id=None if row[4] is None else UUID(str(row[4])),
        concurrency=int(row[5]),
        calling_hours=row[6] if isinstance(row[6], dict) else None,
        retry_policy=row[7] if isinstance(row[7], dict) else None,
    )
    if not with_unreached:
        return campaign_id, 0
    contacts = (
        await session.execute(
            text(
                "SELECT phone_e164, name, custom FROM campaign_contacts "
                "WHERE campaign_id = :cid AND status = ANY(:unreached) ORDER BY created_at, id"
            ),
            {"cid": source_id, "unreached": list(UNREACHED_STATUSES)},
        )
    ).all()
    result = await add_contacts(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        contacts=[
            {**(custom if isinstance(custom, dict) else {}), "phone": phone, "name": person}
            for phone, person, custom in contacts
        ],
    )
    return campaign_id, result["added"]


async def add_leads(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID, lead_ids: list[UUID]
) -> dict[str, int]:
    """Add CRM leads to a draft or scheduled campaign, from the leads' own records.

    The numbers are read here, server-side, so none passes through a browser or a model.
    Consent is unchanged: the campaign's own provenance declaration still covers the whole
    list and the launch gate still asks for it. `add_contacts` does the deduping, the
    India-only rule and the pre-launch status check, exactly as for a CSV.
    """
    rows = (
        await session.execute(
            text("SELECT phone_e164, name FROM leads WHERE id = ANY(:ids) AND deleted_at IS NULL"),
            {"ids": list(dict.fromkeys(lead_ids))},
        )
    ).all()
    result = await add_contacts(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        contacts=[{"phone": phone, "name": name} for phone, name in rows],
    )
    return {**result, "leads": len(rows)}


async def acknowledge_complaint_review(session: AsyncSession, *, campaign_id: UUID) -> bool:
    """Record that the client reviewed the opt-outs behind a complaint-spike pause.

    True when this call recorded it; False when it was already recorded (a second click).
    Refused when the campaign is not paused for a complaint spike, because there is
    nothing to confirm.
    """
    recorded = (
        await session.execute(
            text(
                "UPDATE campaigns SET complaint_reviewed_at = now(), updated_at = now() "
                "WHERE id = :cid AND status = 'paused' "
                "AND auto_pause_reason = 'complaint_spike' AND complaint_reviewed_at IS NULL "
                "RETURNING id"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if recorded is not None:
        return True
    row = (
        await session.execute(
            text(
                "SELECT status, auto_pause_reason, complaint_reviewed_at FROM campaigns "
                "WHERE id = :cid"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    if row[0] == "paused" and row[1] == "complaint_spike" and row[2] is not None:
        return False
    raise ProblemError.business_rule(
        "complaint_review_not_needed",
        "This campaign is not paused for a rise in opt-outs, so there is nothing to confirm.",
    )


async def assert_resumable(session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID) -> None:
    """Refuse Resume while the reason for an automatic pause still holds.

    Not a compliance gate: the per-dial check is still the enforcement. These are the
    pauses whose cause a resume cannot clear, and resuming into one would only pause the
    campaign again on the next tick with the client none the wiser. The complaint-spike
    review is the founder's rule (D-773): the client must look at what the callers said
    before the calls continue.

    The row is locked so the review, the top-up resume and this read agree.
    """
    row = (
        await session.execute(
            text(
                "SELECT auto_pause_reason, complaint_reviewed_at FROM campaigns "
                "WHERE id = :cid FOR UPDATE"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    reason, reviewed_at = row
    if reason == "complaint_spike" and reviewed_at is None:
        raise ProblemError.business_rule(
            "complaint_review_required",
            "Too many people on this campaign asked not to be called. Review what they said "
            "and confirm before the calls continue.",
            remediation="Open the opt-outs on this campaign, read them, then confirm.",
        )
    if reason == "out_of_credit" and await credits_exhausted(session, tenant_id=tenant_id):
        raise ProblemError.business_rule(
            "no_credits",
            NO_CREDITS_REASON,
            remediation="Add credit. The campaign resumes by itself.",
        )
    if reason == "spend_cap" and await spend_capped(session, tenant_id=tenant_id):
        raise ProblemError.business_rule(
            "spend_cap",
            SPEND_CAP_REASON,
            remediation="Raise your monthly spending limit, then resume.",
        )


async def account_pause_reason(
    session: AsyncSession, *, tenant_id: UUID
) -> AccountPauseReason | None:
    """Should this account's running campaigns pause for money? The spending cap first,
    in the order `compliance.service.account_dial_blockers` asks them."""
    if await spend_capped(session, tenant_id=tenant_id):
        return "spend_cap"
    if await credits_exhausted(session, tenant_id=tenant_id):
        return "out_of_credit"
    return None


async def auto_pause(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID, reason: AccountPauseReason
) -> bool:
    """Pause a running campaign for a money reason. True when this call paused it.

    A CAS from `running`, so a campaign a person paused, stopped or that finished in the
    meantime is left alone. Audited as `system`: "who stopped the calls" has an answer
    whether it was a person or us.
    """
    try:
        paused = await set_campaign_status(
            session,
            campaign_id=campaign_id,
            to_status="paused",
            from_statuses=("running",),
            auto_pause_reason=reason,
        )
    except InvalidStatusTransitionError:
        return False
    if paused:
        await write_audit(
            session,
            action="campaign.paused",
            actor_type="system",
            tenant_id=tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            summary={"reason": reason},
        )
        log.info("campaign_auto_paused", extra={"campaign_id": str(campaign_id), "reason": reason})
    return paused


async def resume_campaigns_after_credit(session: AsyncSession, *, tenant_id: UUID) -> list[UUID]:
    """Restart the campaigns this account's empty wallet paused. Returns the ones restarted.

    Called by the top-up job once it has re-read that the account is no longer out of
    credit. A set-based CAS on `paused` + `out_of_credit`, so a second run of the job, or a
    campaign the client stopped meanwhile, changes nothing. A campaign whose agent was
    archived while it waited stays paused: the client has to point it at another agent.
    """
    rows = (
        await session.execute(
            text(
                "UPDATE campaigns c SET status = 'running', auto_pause_reason = NULL, "
                "updated_at = now() "
                "WHERE c.status = 'paused' AND c.auto_pause_reason = 'out_of_credit' "
                "AND EXISTS (SELECT 1 FROM agents a WHERE a.id = c.agent_id "
                "  AND a.status <> 'archived' AND a.deleted_at IS NULL) "
                "RETURNING c.id"
            )
        )
    ).all()
    resumed = [UUID(str(r[0])) for r in rows]
    for campaign_id in resumed:
        await write_audit(
            session,
            action="campaign.resumed",
            actor_type="system",
            tenant_id=tenant_id,
            object_type="campaign",
            object_id=str(campaign_id),
            summary={"reason": "credit_added"},
        )
    if resumed:
        log.info(
            "campaigns_resumed_after_credit",
            extra={"tenant_id": str(tenant_id), "count": len(resumed)},
        )
    return resumed


__all__ = [
    "MAX_CONTACTS_PER_REMOVE",
    "MAX_LEADS_PER_ADD",
    "UNREACHED_STATUSES",
    "AccountPauseReason",
    "account_pause_reason",
    "acknowledge_complaint_review",
    "add_leads",
    "assert_resumable",
    "auto_pause",
    "delete_draft",
    "duplicate_campaign",
    "remove_contacts",
    "resume_campaigns_after_credit",
    "stop_campaign",
    "update_draft",
]
