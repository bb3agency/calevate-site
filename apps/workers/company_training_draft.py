"""Pip writes the company training from the owner's overview and what the agents already know
(founder, 16 Nov 2026: the same general overview and training for every employee a company
hires, written from the knowledge rather than from a second list of sources).

Queued by `agents/company_training.request_proposal`. One answer on the dashboard AI ladder
(`script_assist.ask_json`), written from what is known about the business
(`lead_fields_draft.business_context`, already redacted), the owner's overview (redacted here,
D-127 G-1), and every source the agents use (`knowledge_words`: files, links' read copies and
typed notes, with the call instructions read out of files), read the way onboarding reads
documents (`first_run.documents_block`: redacted, fenced, one word budget).

What Pip writes is a proposal: the owner reviews it on the page and saves it, and only a save
reaches the agents. The one exception is the first run's (founder, 16 Nov 2026): asked for
with `auto_save`, it is saved at once as version 1 (`_save_if_asked`). Every write back is a compare-and-set on the proposal id, so a draft the
owner stopped or replaced is never resurrected. Metered as a script draft, which it is.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import company_training
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.first_run.documents import document_words
from apps.api.teach.facts import FACTS_SOURCE_NAME
from apps.workers.first_run import documents_block
from apps.workers.lead_fields_draft import business_context
from apps.workers.redaction import redact
from apps.workers.script_assist import JsonAnswer, ask_json
from apps.workers.script_proposal import PROPOSAL_MAX_TOKENS, PROPOSAL_REQUEST_TIMEOUT_S

log = get_logger(__name__)

#: The ARQ name; `company_training.TRAINING_DRAFT_JOB` is the enqueue side's spelling.
JOB_NAME: Final = company_training.TRAINING_DRAFT_JOB

TRAINING_ASK: Final = (
    "Write the training this business gives every phone agent it puts on calls, the way a "
    "company trains every new employee before giving them work. Each agent also gets its "
    "own script for each piece of work; this training is what they all share. Cover, in "
    "this order and only where the material below says it: who the business is and what it "
    "offers; who its customers are; how the agents speak to callers (tone, how to address "
    "people, phrases the owner uses); names and how to say them; policies (prices, hours, "
    "delivery, payment, returns); the questions callers ask, each with a short spoken "
    "answer; objections and how to answer them. Use ONLY what the owner's words and the "
    "sources below say: never add a price, place, offer, time, product or promise they do "
    "not state, and leave a part out rather than guess it. Write plain sentences under short "
    "plain headings in English, keeping names and the owner's own phrases exactly as they "
    "wrote them. No markdown, no bullets or asterisks, no emoji: agents read it before they "
    "speak. Return JSON with one key, training, holding the whole text."
)
EDIT_TAIL: Final = (
    " A training exists already, under CURRENT TRAINING: keep its wording wherever the "
    "material below does not change it."
)

_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"training": {"type": "string"}},
    "required": ["training"],
    "additionalProperties": False,
}

_STORE: Final = text(
    "UPDATE company_trainings SET proposal = proposal || CAST(:u AS jsonb) "
    "WHERE tenant_id = :t AND proposal->>'id' = :pid RETURNING id"
)


def _parsed(raw: dict[str, Any]) -> str | None:
    """The training text, or None for an answer that holds none or is over the limit."""
    value = raw.get("training")
    if not isinstance(value, str):
        return None
    cleaned = "\n".join(line.rstrip() for line in value.strip().splitlines())
    if not cleaned or len(cleaned) > company_training.TRAINING_MAX:
        return None
    return cleaned


#: The newest sources Pip reads; `documents_block` shares one word budget among them, so more
#: would only shorten each.
KNOWLEDGE_SOURCES_READ: Final = 20

#: Every source the agents use, newest first: an upload (file or link) or a typed note. The
#: taught facts are left out: they reach every agent already, as known facts.
_KNOWLEDGE_SQL: Final = text(
    "SELECT s.id, s.name, u.id AS upload_id FROM kb_sources s "
    "LEFT JOIN kb_uploads u ON u.source_id = s.id "
    "WHERE s.is_active AND s.name <> :facts "
    "AND (CAST(:only AS uuid[]) IS NULL OR s.id = ANY(CAST(:only AS uuid[]))) "
    "ORDER BY s.updated_at DESC, s.id DESC LIMIT :n"
)
_NOTE_WORDS_SQL: Final = text("SELECT content FROM kb_documents WHERE source_id = :s ORDER BY idx")


async def knowledge_words(
    session: AsyncSession, only: Sequence[UUID] | None = None
) -> list[tuple[str, str]]:
    """(name, words) of each source the agents use, or of the ones `only` names (the sources
    an inbound line was written from), unredacted: `documents_block` redacts."""
    rows = (
        await session.execute(
            _KNOWLEDGE_SQL,
            {
                "facts": FACTS_SOURCE_NAME,
                "n": KNOWLEDGE_SOURCES_READ,
                "only": None if only is None else [str(i) for i in only],
            },
        )
    ).all()
    found: list[tuple[str, str]] = []
    for source_id, name, upload_id in rows:
        if upload_id is not None:
            words = await document_words(session, upload_id)
        else:
            chunks = (await session.execute(_NOTE_WORDS_SQL, {"s": source_id})).scalars()
            words = "\n\n".join(str(c) for c in chunks)
        if words.strip():
            found.append((str(name), words))
    return found


def request_text(*, business: str, overview: str, documents: str, current: str | None) -> str:
    """What the training is written from, in the order the ask names it."""
    parts = [f"WHAT IS KNOWN ABOUT THE BUSINESS:\n{business}"]
    parts.append(f"THE OWNER'S OVERVIEW, IN THEIR WORDS:\n{redact(overview.strip()).text}")
    if current:
        parts.append(f"CURRENT TRAINING:\n{redact(current).text}")
    if documents:
        parts.append(documents)
    return "\n\n".join(parts)


async def _claim(tenant_id: UUID, proposal_id: UUID) -> bool:
    """Take the request once: the outbox delivers at least once."""
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE company_trainings SET proposal = proposal || "
                    "jsonb_build_object('claimed', true) WHERE tenant_id = :t "
                    "AND proposal->>'id' = :pid AND proposal->>'status' = 'drafting' "
                    "AND proposal->>'claimed' IS NULL RETURNING id"
                ),
                {"t": tenant_id, "pid": str(proposal_id)},
            )
        ).first()
    return claimed is not None


async def _store(tenant_id: UUID, proposal_id: UUID, update: dict[str, Any]) -> bool:
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                _STORE, {"t": tenant_id, "pid": str(proposal_id), "u": json.dumps(update)}
            )
        ).first()
    return stored is not None


async def _save_if_asked(
    session: AsyncSession, tenant_id: UUID, proposal_id: UUID, training: str
) -> None:
    """A draft asked for with `auto_save` (the first run's) is saved as the training at once,
    while none has been saved yet (version 0): a training the owner saved is never replaced.
    Through `save_training`, so the box is measured and live agents are brought onto it; a
    draft refused there stays for the owner to review."""
    row = (
        await session.execute(
            text(
                "SELECT version, proposal->>'auto_save' AS auto FROM company_trainings "
                "WHERE tenant_id = :t AND proposal->>'id' = :pid"
            ),
            {"t": tenant_id, "pid": str(proposal_id)},
        )
    ).first()
    if row is None or row.auto != "true" or int(row.version) != 0:
        return
    try:
        async with session.begin_nested():
            await company_training.save_training(session, tenant_id, training, saved_by=None)
            await company_training.clear_proposal(session, tenant_id, proposal_id)
    except ProblemError as refused:
        log.info("company_training_kept_for_review", extra={"reason": refused.code})


async def draft_company_training(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    proposal_id = UUID(str(payload["proposal_id"]))
    if not await _claim(tenant_id, proposal_id):
        return "not_pending"
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    try:
        business, _vertical = await business_context(tenant_id)
        async with tenant_session(tenant_id) as session:
            current = await company_training.read_training(session, tenant_id)
            words = await knowledge_words(session)
            tenant_leg = await account_assist_leg(session)
            quota = await read_ai_quota(session, tenant_id=tenant_id)
        # Written from the training the request was made from, which the review compares
        # against: a training saved since would otherwise read as Pip's change.
        base = current.proposal.base_training if current.proposal is not None else None
        request = request_text(
            business=business,
            overview=current.overview,
            documents=documents_block(words),
            current=base,
        )
        try:
            answer: JsonAnswer[str] = await ask_json(
                request,
                TRAINING_ASK + (EDIT_TAIL if base else ""),
                parse=_parsed,
                azure_format={
                    "type": "json_schema",
                    "json_schema": {"name": "company_training", "strict": True, "schema": _SCHEMA},
                },
                tenant_leg=tenant_leg,
                quota_exhausted=quota.at_ceiling or quota.platform_paused,
                max_tokens=PROPOSAL_MAX_TOKENS,
                temperature=0.3,
                timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
            )
        except ProblemError as refused:
            async with tenant_session(tenant_id) as session:
                await crm_assist.meter_refusal(
                    session, tenant_id=tenant_id, refusal=refused, feature=feature
                )
            log.info("company_training_refused", extra={"reason": refused.code})
            await _store(
                tenant_id,
                proposal_id,
                {"status": "failed", "note": company_training.FAILED_NOTE, "reason": refused.code},
            )
            return "refused"
    except Exception:
        log.exception("company_training_crashed")
        await _store(
            tenant_id,
            proposal_id,
            {"status": "failed", "note": company_training.FAILED_NOTE, "reason": "crashed"},
        )
        return "failed"

    update = {
        "status": "ready",
        "training": answer.value,
        # A draft the standby answered is disclosed with it (D-127 G-6).
        "disclosure": answer.capability.disclosure,
    }
    # A completed run is money spent: metered in the same transaction that stores the draft.
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                _STORE, {"t": tenant_id, "pid": str(proposal_id), "u": json.dumps(update)}
            )
        ).first()
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            model=answer.model,
            feature=feature,
        )
        if stored is not None:
            await _save_if_asked(session, tenant_id, proposal_id, answer.value)
    log.info("company_training_written", extra={"stored": stored is not None})
    return "ready" if stored is not None else "not_pending"


__all__ = [
    "JOB_NAME",
    "KNOWLEDGE_SOURCES_READ",
    "TRAINING_ASK",
    "draft_company_training",
    "knowledge_words",
    "request_text",
]
