"""The script change Pip prepares for an agent, waiting on the Script page (D-820).

Pip is the one AI assistant (founder, 18 Oct 2026). A person asks Pip to change an agent's
script, to draft the whole script from the six owner questions, or to turn a hand-written
script into steps; the `agent_script_propose` action (`copilot/script_actions.py`) records
the request here and queues `draft_script_proposal` (`workers/script_proposal.py`), which
writes it with `workers/script_assist.draft_script` — the one script-writing path, with its
repair, refusals, metering and disclosure. The owner then keeps the proposal part by part
into their draft, or discards it, on the Script page. Nothing here writes the draft and
nothing here reaches a call.

ONE PROPOSAL PER AGENT, ON THE AGENT ROW (`agents.script_proposal`), rather than a table:
it is the agent's own pending state like `script_draft`, it is replaced by the next request
and cleared by the review, so a table would only add rows nobody reads, plus a policy for a
tenant scope `agents` already carries.

The stored shape (JSON): `id`, `mode`, `status` (`drafting` | `ready` | `failed`), `request`
(the person's change, or null), `answers` (the six owner answers, `whole` only),
`base_script` (the script it was made from, fixed at request time), `requested_by`,
`requested_at`, and for `knowledge` (D-923) `documents` and `document_names` (the uploads it
is written from); once written `script`, `unplaced` (`steps` only) and `disclosure` (D-127
G-6); on failure `note`, in the owner's words. Every write after the request is a
compare-and-set on `id`, so a discarded or replaced request is never resurrected by the job
that was drafting it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, get_args
from uuid import UUID

from calevate_shared.call_script import CallScript, upgrade_to_v2
from calevate_shared.engine import introduces_itself
from calevate_shared.spoken_style import style_for
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_builder
from apps.api.agents.capability_manifest import manifest_for, owner_facts
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.first_run.models import MAX_DOCUMENTS
from apps.api.reliability.service import enqueue_outbox, enqueue_outbox_once
from apps.workers.script_assist import OWNER_QUESTIONS, ScriptBrief

#: The outbox job that writes a requested proposal (`workers/script_proposal.py`).
PROPOSAL_JOB: Final = "draft_script_proposal"
#: The outbox job that queues a `knowledge` proposal for every agent once a file added to the
#: knowledge is live (`workers/script_proposal.suggest_scripts_from_document`, D-923).
SUGGEST_JOB: Final = "suggest_scripts_from_document"

#: `change`: one change in the person's words to the script in steps. `whole`: the whole
#: script from the owner's answers to `OWNER_QUESTIONS`. `steps`: a hand-written script
#: turned into steps (`script_assist.CONVERT_INSTRUCTION`).
ProposalMode = Literal["change", "whole", "steps"]
PROPOSAL_MODES: Final[tuple[ProposalMode, ...]] = get_args(ProposalMode)
#: `knowledge` (D-923): the current script with what newly added documents tell callers worked
#: in, made by us when a document goes live after onboarding, never asked of Pip. So it is a
#: stored mode and not a `ProposalMode` a request can name.
KNOWLEDGE_MODE: Final = "knowledge"
StoredMode = Literal["change", "whole", "steps", "knowledge"]

ProposalStatus = Literal["drafting", "ready", "failed"]

#: The longest a person's change may be: the old helper's field, `AssistIn.change`.
MAX_CHANGE_CHARS: Final = 600
#: Each of the five answers, as the helper's fields took them.
MAX_ANSWER_CHARS: Final = 600
#: The fewest characters a request must carry, the helper's `has_enough` floor: below it
#: the draft would be written from nothing the owner said.
MIN_REQUEST_CHARS: Final = 10

#: A request still `drafting` after this long is reported as failed. The job finishes or
#: records its failure well inside it (`workers/script_assist` spends at most three model
#: budgets); past it the job was lost, and a screen waiting forever is the worse answer.
DRAFTING_STALE_AFTER: Final = timedelta(minutes=10)

STALE_NOTE: Final = (
    "This suggestion could not be finished. Ask Pip again; if it keeps happening, contact us."
)

#: The job's own fallback when the failure is not one of the AI refusals.
FAILED_NOTE: Final = (
    "The suggestion could not be written this time. Ask Pip again in a few minutes; if it "
    "keeps happening, contact us."
)


@dataclass(frozen=True, slots=True)
class ScriptProposal:
    id: UUID
    mode: StoredMode
    status: ProposalStatus
    request: str | None
    answers: dict[str, str]
    base_script: CallScript
    requested_by: UUID | None
    requested_at: datetime
    script: CallScript | None = None
    unplaced: list[str] = field(default_factory=list)
    disclosure: str | None = None
    note: str | None = None
    #: The knowledge uploads a `knowledge` proposal is written from, and their names.
    documents: list[UUID] = field(default_factory=list)
    document_names: list[str] = field(default_factory=list)


def _parse(raw: dict[str, Any], *, now: datetime) -> ScriptProposal:
    status: ProposalStatus = raw.get("status", "drafting")
    requested_at = datetime.fromisoformat(str(raw["requested_at"]))
    note = raw.get("note")
    if status == "drafting" and now - requested_at > DRAFTING_STALE_AFTER:
        status, note = "failed", STALE_NOTE
    script = raw.get("script")
    by = raw.get("requested_by")
    return ScriptProposal(
        id=UUID(str(raw["id"])),
        mode=raw["mode"],
        status=status,
        request=raw.get("request"),
        answers={str(k): str(v) for k, v in (raw.get("answers") or {}).items()},
        base_script=CallScript.model_validate(raw["base_script"]),
        requested_by=UUID(str(by)) if by else None,
        requested_at=requested_at,
        script=CallScript.model_validate(script) if script is not None else None,
        unplaced=[str(line) for line in raw.get("unplaced") or []],
        disclosure=raw.get("disclosure"),
        note=note,
        documents=[UUID(str(d)) for d in raw.get("documents") or []],
        document_names=[str(n) for n in raw.get("document_names") or []],
    )


async def read_proposal(session: AsyncSession, agent_id: UUID) -> ScriptProposal | None:
    """The agent's pending proposal, or None. 404 for an agent this tenant cannot see."""
    row = (
        await session.execute(
            text("SELECT script_proposal FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _parse(row[0], now=datetime.now(UTC)) if row[0] else None


async def working_script(session: AsyncSession, agent_id: UUID) -> CallScript:
    """What the owner is editing: the autosaved draft, else the script on file, in steps
    form as the builder opens it."""
    draft = await script_builder.read_draft(session, agent_id)
    if draft is not None:
        return upgrade_to_v2(draft.script)
    return upgrade_to_v2((await script_builder.load_agent_script(session, agent_id)).script)


def request_text(
    mode: ProposalMode, change: str | None, answers: dict[str, str], base: CallScript
) -> str:
    """The owner's words the draft is written from; empty when there are none."""
    if mode == "change":
        return (change or "").strip()
    if mode == "whole":
        return "".join(v.strip() for k, v in answers.items() if k in OWNER_QUESTIONS)
    return (base.raw_override or "").strip()


async def request_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    mode: ProposalMode,
    change: str | None,
    answers: dict[str, str],
    requested_by: UUID,
) -> ScriptProposal:
    """Record the request and queue the job that writes it, in the caller's transaction.

    It replaces any proposal still waiting for review; one still being drafted is refused,
    so two requests cannot race to write the same review."""
    await session.execute(
        text("SELECT 1 FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"),
        {"aid": agent_id},
    )
    pending = await read_proposal(session, agent_id)
    if pending is not None and pending.status == "drafting":
        raise ProblemError.conflict(
            "script_proposal_in_progress",
            "Pip is still preparing the last change to this script.",
            remediation="Wait for it to appear on the Script page, then ask for the next one.",
        )
    base = await working_script(session, agent_id)
    proposal_id = uuid7()
    now = datetime.now(UTC)
    record = {
        "id": str(proposal_id),
        "mode": mode,
        "status": "drafting",
        "request": (change or "").strip()[:MAX_CHANGE_CHARS] if mode == "change" else None,
        "answers": {
            k: v.strip()[:MAX_ANSWER_CHARS]
            for k, v in answers.items()
            if k in OWNER_QUESTIONS and v.strip()
        }
        if mode == "whole"
        else {},
        "base_script": base.model_dump(mode="json"),
        "requested_by": str(requested_by),
        "requested_at": now.isoformat(),
    }
    await session.execute(
        text("UPDATE agents SET script_proposal = CAST(:p AS jsonb) WHERE id = :aid"),
        {"aid": agent_id, "p": json.dumps(record)},
    )
    await enqueue_outbox(
        session,
        job=PROPOSAL_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "proposal_id": str(proposal_id),
        },
    )
    return _parse(record, now=now)


async def queue_document_suggestions(
    session: AsyncSession, *, tenant_id: UUID, upload_id: UUID
) -> None:
    """Queue `SUGGEST_JOB` for a file now live in the knowledge, in the caller's transaction.
    Once per upload, so a re-drive or a re-read of the same upload never suggests it twice."""
    await enqueue_outbox_once(
        session,
        job=SUGGEST_JOB,
        payload={"tenant_id": str(tenant_id), "upload_id": str(upload_id)},
        dedupe_key=f"{SUGGEST_JOB}:{upload_id}",
    )


#: The most documents one `knowledge` proposal is written from, the newest kept: onboarding's
#: limit, so their shared word budget (`first_run.models.DOCUMENT_CHARS`) is never split
#: thinner than it is there.
MAX_KNOWLEDGE_DOCUMENTS: Final = MAX_DOCUMENTS


async def request_knowledge_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    upload_ids: list[UUID],
    names: list[str],
) -> ScriptProposal | None:
    """Queue a `knowledge` proposal for one agent (D-923), in the caller's transaction, or
    None when the agent is gone or a suggestion the owner asked for is waiting.

    A waiting `knowledge` proposal is replaced by one written from its documents and these,
    so two uploads in a row give one suggestion carrying both. One the owner asked Pip for is
    never replaced: their request is theirs, and a document can be suggested again by
    dismissing it and re-adding the file."""
    found = (
        await session.execute(
            text(
                "SELECT 1 FROM agents WHERE id = :aid AND deleted_at IS NULL "
                "AND status <> 'archived' FOR UPDATE"
            ),
            {"aid": agent_id},
        )
    ).first()
    if found is None:
        return None
    pending = await read_proposal(session, agent_id)
    earlier: dict[UUID, str] = {}
    if pending is not None:
        if pending.mode != KNOWLEDGE_MODE and pending.status != "failed":
            return None
        if pending.mode == KNOWLEDGE_MODE:
            earlier = dict(zip(pending.documents, pending.document_names, strict=False))
    chosen = list({**earlier, **dict(zip(upload_ids, names, strict=True))}.items())
    chosen = chosen[-MAX_KNOWLEDGE_DOCUMENTS:]
    base = await working_script(session, agent_id)
    if base.raw_override:
        # A script written as one piece has no parts to work a document into; turning it
        # into steps is the owner's call (`steps`).
        return None
    proposal_id = uuid7()
    now = datetime.now(UTC)
    record = {
        "id": str(proposal_id),
        "mode": KNOWLEDGE_MODE,
        "status": "drafting",
        "request": None,
        "answers": {},
        "documents": [str(upload) for upload, _ in chosen],
        "document_names": [name for _, name in chosen],
        "base_script": base.model_dump(mode="json"),
        "requested_by": None,
        "requested_at": now.isoformat(),
    }
    await session.execute(
        text("UPDATE agents SET script_proposal = CAST(:p AS jsonb) WHERE id = :aid"),
        {"aid": agent_id, "p": json.dumps(record)},
    )
    await enqueue_outbox(
        session,
        job=PROPOSAL_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "proposal_id": str(proposal_id),
        },
    )
    return _parse(record, now=now)


async def _update_if_current(
    session: AsyncSession, agent_id: UUID, proposal_id: UUID, changes: dict[str, Any]
) -> bool:
    written = (
        await session.execute(
            text(
                "UPDATE agents SET script_proposal = script_proposal || CAST(:c AS jsonb) "
                "WHERE id = :aid AND script_proposal->>'id' = :pid "
                "AND script_proposal->>'status' = 'drafting' RETURNING id"
            ),
            {"aid": agent_id, "pid": str(proposal_id), "c": json.dumps(changes)},
        )
    ).first()
    return written is not None


async def store_ready(
    session: AsyncSession,
    *,
    agent_id: UUID,
    proposal_id: UUID,
    script: CallScript,
    unplaced: list[str],
    disclosure: str | None,
) -> bool:
    """The written proposal. False when the request was discarded or replaced meanwhile."""
    return await _update_if_current(
        session,
        agent_id,
        proposal_id,
        {
            "status": "ready",
            "script": script.model_dump(mode="json"),
            "unplaced": unplaced,
            "disclosure": disclosure,
        },
    )


async def store_failed(
    session: AsyncSession, *, agent_id: UUID, proposal_id: UUID, note: str
) -> bool:
    return await _update_if_current(
        session, agent_id, proposal_id, {"status": "failed", "note": note[:400]}
    )


async def discard(session: AsyncSession, *, agent_id: UUID, proposal_id: UUID) -> bool:
    """Clear this proposal (kept into the draft, or not wanted). False when it is no longer
    the agent's pending one, which is the same outcome to the person: it is gone."""
    await script_builder.assert_agent_visible(session, agent_id)
    cleared = (
        await session.execute(
            text(
                "UPDATE agents SET script_proposal = NULL "
                "WHERE id = :aid AND script_proposal->>'id' = :pid RETURNING id"
            ),
            {"aid": agent_id, "pid": str(proposal_id)},
        )
    ).first()
    return cleared is not None


async def brief_for(session: AsyncSession, tenant_id: UUID, agent_id: UUID) -> ScriptBrief:
    """What every draft is written from besides the owner's words: the business, the
    agent's direction and call language with its spoken register, the details it collects
    and the knowledge titles, what it can do on a call and the owner's facts (D-945).
    Tenant-authored configuration only (D-127 G-2)."""
    row = (
        await session.execute(
            text(
                "SELECT a.direction, a.language_primary, o.vertical_template, o.name, a.name, "
                "CASE WHEN a.ai_disclosure_enabled THEN a.ai_disclosure_line ELSE '' END "
                "FROM agents a JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL AND o.id = :tid"
            ),
            {"aid": agent_id, "tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    language = str(row[1])
    style = style_for(language)
    titles = await session.execute(
        text(
            "SELECT name FROM kb_sources WHERE is_active AND published_at IS NOT NULL "
            "ORDER BY published_at DESC LIMIT 20"
        )
    )
    return ScriptBrief(
        business_name=str(row[3] or ""),
        agent_name=str(row[4] or ""),
        business_type=str(row[2] or "custom"),
        direction=str(row[0]),
        language=language,
        register=(f"{style.register_name}. {style.register}" if style is not None else ""),
        collect=tuple(f.label for f in await script_builder.collect_fields(session, agent_id)),
        knowledge_titles=tuple(str(r[0])[:120] for r in titles),
        introduced=introduces_itself(ai_notice=str(row[5]), language=language),
        capabilities=await manifest_for(session, tenant_id=tenant_id, agent_id=agent_id),
        facts=await owner_facts(session, tenant_id=tenant_id, agent_id=agent_id),
    )


__all__ = [
    "DRAFTING_STALE_AFTER",
    "FAILED_NOTE",
    "KNOWLEDGE_MODE",
    "MAX_ANSWER_CHARS",
    "MAX_CHANGE_CHARS",
    "MAX_KNOWLEDGE_DOCUMENTS",
    "MIN_REQUEST_CHARS",
    "PROPOSAL_JOB",
    "PROPOSAL_MODES",
    "STALE_NOTE",
    "SUGGEST_JOB",
    "ProposalMode",
    "ProposalStatus",
    "ScriptProposal",
    "brief_for",
    "discard",
    "queue_document_suggestions",
    "read_proposal",
    "request_knowledge_proposal",
    "request_proposal",
    "request_text",
    "store_failed",
    "store_ready",
    "working_script",
]
