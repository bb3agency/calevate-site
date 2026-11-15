"""Pip writes a campaign's script from its main task and materials (D-992).

Queued by `campaigns/workspace.request_proposal`. The script is written by the one script
writer (`workers/script_assist.draft_script`) in the campaign agent's language and business
context (`agents/script_proposals.brief_for`), as an edit of the campaign's current script
when it has one, so the owner's own wording survives wherever the materials do not change
it. Documents are read the way onboarding reads them (`first_run.documents_block`: redacted,
fenced, one word budget). Every write back is a compare-and-set on the proposal id, so a
draft the owner stopped or replaced is never resurrected.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text

from apps.api.agents import script_proposals
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.campaigns import workspace
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.first_run.documents import document_words, read_documents
from apps.workers.first_run import documents_block
from apps.workers.script_assist import AskTrace, ScriptDraft, draft_script

# The agent proposal job's budget: a job nobody waits on gives a long script more time and tokens.
from apps.workers.script_proposal import PROPOSAL_MAX_TOKENS, PROPOSAL_REQUEST_TIMEOUT_S

log = get_logger(__name__)

CAMPAIGN_CHANGE: Final = (
    "Write this campaign's call script. Every call this agent places for the campaign follows "
    "it. The campaign's main task, in the owner's words, says what the calls must achieve; the "
    "owner's notes, links and documents below say what to tell people and how. Write the "
    "opening line for the call it places, the steps that get to the main task one at a time, "
    "quick facts (the faqs list: a question people ask and a short spoken answer, at most "
    "eight), the objections people raise with how to answer, and how the call ends. Where a "
    "note or document says how the agent should handle the call, follow it. Keep anything "
    "already in the script that the main task and materials do not change.\n"
    "MAIN TASK:\n{main_task}\n"
)


async def _claim(tenant_id: UUID, campaign_id: UUID, proposal_id: UUID) -> bool:
    """Take the request once: the outbox delivers at least once."""
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE campaigns SET script_proposal = script_proposal || "
                    "jsonb_build_object('claimed', true) WHERE id = :cid "
                    "AND script_proposal->>'id' = :pid "
                    "AND script_proposal->>'status' = 'drafting' "
                    "AND script_proposal->>'claimed' IS NULL RETURNING id"
                ),
                {"cid": campaign_id, "pid": str(proposal_id)},
            )
        ).first()
    return claimed is not None


async def _store(
    tenant_id: UUID, campaign_id: UUID, proposal_id: UUID, update: dict[str, Any]
) -> bool:
    async with tenant_session(tenant_id) as session:
        done = (
            await session.execute(
                text(
                    "UPDATE campaigns SET script_proposal = script_proposal || CAST(:u AS jsonb) "
                    "WHERE id = :cid AND script_proposal->>'id' = :pid RETURNING id"
                ),
                {"cid": campaign_id, "pid": str(proposal_id), "u": json.dumps(update)},
            )
        ).first()
    return done is not None


def _materials_text(materials: list[workspace.Material]) -> str:
    """Notes and links as plain lines; documents are read separately, in full."""
    lines: list[str] = []
    for item in materials:
        if item.kind == "note" and item.note:
            label = "Learned from calls" if item.source == "call" else "Note"
            lines.append(f"{label} ({item.title}): {item.note}")
        elif item.kind == "link" and item.url:
            lines.append(f"Link ({item.title}): {item.url}")
    return "\n".join(lines)


async def draft_campaign_script(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    campaign_id = UUID(str(payload["campaign_id"]))
    proposal_id = UUID(str(payload["proposal_id"]))
    if not await _claim(tenant_id, campaign_id, proposal_id):
        return "not_pending"

    async with tenant_session(tenant_id) as session:
        space = await workspace.read_workspace(session, campaign_id)
        uploads = [m.kb_upload_id for m in space.materials if m.kb_upload_id is not None]
        found = await read_documents(session, uploads)
        words = [
            (doc.name, await document_words(session, doc.upload_id))
            for doc in found
            if doc.state == "read"
        ]
        context = await script_proposals.brief_for(session, tenant_id, space.agent_id)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)

    change = CAMPAIGN_CHANGE.format(main_task=space.main_task)
    notes = _materials_text(space.materials)
    if notes:
        change += f"OWNER'S NOTES AND LINKS:\n{notes}\n"
    documents = documents_block(words)
    if documents:
        change += documents
    base = space.script or CallScript()
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    trace = AskTrace()
    try:
        draft: ScriptDraft = await draft_script(
            context,
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling or quota.platform_paused,
            edit_of=base,
            change=change,
            timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
            max_tokens=PROPOSAL_MAX_TOKENS,
            trace=trace,
        )
    except ProblemError as refused:
        log.info(
            "campaign_script_refused",
            extra={"campaign_id": str(campaign_id), "reason": refused.code},
        )
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        await _store(
            tenant_id,
            campaign_id,
            proposal_id,
            {"status": "failed", "note": refused.detail or workspace.FAILED_NOTE},
        )
        return "refused"
    except Exception:
        log.exception("campaign_script_crashed", extra={"campaign_id": str(campaign_id)})
        await _store(
            tenant_id, campaign_id, proposal_id, {"status": "failed", "note": workspace.FAILED_NOTE}
        )
        return "failed"

    # A completed run is money spent: metered in the same transaction that stores the draft.
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(
                    "UPDATE campaigns SET script_proposal = script_proposal || CAST(:u AS jsonb) "
                    "WHERE id = :cid AND script_proposal->>'id' = :pid RETURNING id"
                ),
                {
                    "cid": campaign_id,
                    "pid": str(proposal_id),
                    "u": json.dumps(
                        {"status": "ready", "script": draft.script.model_dump(mode="json")}
                    ),
                },
            )
        ).first()
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=draft.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=draft,
            model=draft.model,
            feature=feature,
        )
    log.info(
        "campaign_script_written",
        extra={
            "campaign_id": str(campaign_id),
            "stored": stored is not None,
            "repairs": trace.repairs,
        },
    )
    return "ready" if stored is not None else "not_pending"


__all__ = ["draft_campaign_script"]
