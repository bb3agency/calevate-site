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
is written from); once written `script`, `unplaced` (`steps` only), `disclosure` (D-127
G-6) and `left_out` (the parts kept as the owner had them, each `part`, `name`, `rule`,
`added`); on failure `note`, in the owner's words, `reason` (the refusal code) and
`left_out` (the parts that could not be written). Either outcome records `repairs` (how many
repairs were asked for) and `truncated` (an answer was cut off at its token ceiling), for an
operator reading the row. Every write after the request is a
compare-and-set on `id`, so a discarded or replaced request is never resurrected by the job
that was drafting it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, get_args
from uuid import UUID

from calevate_shared.call_script import (
    MAX_STAGE_COLLECT,
    CallScript,
    ConversationStage,
    ScriptPolicies,
    upgrade_to_v2,
)
from calevate_shared.engine import introduces_itself
from calevate_shared.lead_fields import business_only
from calevate_shared.opening_notices import WovenNotices
from calevate_shared.spoken_style import style_for
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_builder
from apps.api.agents.business_fit import business_fit
from apps.api.agents.capability_manifest import manifest_for, owner_facts
from apps.api.agents.script_lint import order_problems, placeholder_instruction
from apps.api.agents.starter_plans import stored_plans
from apps.api.agents.starters import JOB_STEP_COUNTS
from apps.api.agents.write_guard import archived_refusal
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.engine import engine_capabilities
from apps.api.first_run.models import MAX_DOCUMENTS
from apps.api.reliability.service import enqueue_outbox, enqueue_outbox_once
from apps.workers.script_assist import (
    OWNER_QUESTIONS,
    LeftOut,
    ScriptBrief,
    ways_to_kept_steps,
    without_placeholder_steps,
)

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
#: `opening` (D-865): the opening line written again to be said after the agent's own
#: introduction, asked from the refusal to switch the AI notice on over an opening that
#: already says who is calling (`publishing.OPENING_INTRODUCES_CODE`). A stored mode for
#: `knowledge`'s reason.
OPENING_MODE: Final = "opening"
#: `written` (D-965): the agent's opening lines written for this business in its main
#: language, asked after the main language changes and queued when an agent is made from a
#: ready-made starter, whose openings are left empty rather than the same for every business.
#: A stored mode for `knowledge`'s reason.
WRITTEN_MODE: Final = "written"
#: `starter`: the whole script written for this business when an agent is made from a job,
#: so its steps, objections and ending are the business's own rather than the job's list
#: kept for every business. An opening the owner typed at creation is kept as typed.
#: A stored mode for `knowledge`'s reason.
STARTER_MODE: Final = "starter"
#: The job that drafts a new agent's details from its script (`workers/agent_fields_draft`).
AGENT_FIELDS_JOB: Final = "draft_agent_fields"
StoredMode = Literal["change", "whole", "steps", "knowledge", "opening", "written", "starter"]

ProposalStatus = Literal["drafting", "ready", "failed"]

#: The longest a person's change may be, the same as each of Pip's answer fields. A brief
#: setting out a whole call (its purpose and its steps) runs to about 1,400 characters, and
#: the old 600 cut it without a word (founder, 2 Nov 2026).
MAX_CHANGE_CHARS: Final = 2000
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

#: When the answer was cut off at its token ceiling and nothing usable came back: the one
#: failure the owner fixes by asking for less at a time.
TOO_BIG_NOTE: Final = (
    "This change was too big for Pip to write in one go. Ask for one part at a time, for "
    "example the opening first, then the steps."
)

#: What a part of the script is called on the Script tab, for a field a left-out part names.
_PART_LABELS: Final[dict[str, str]] = {
    "stages": "The list of steps",
    "opening_line": "The opening line",
    "outbound_opening_line": "The opening line for calls it makes",
    "goal": "The main task",
    "business_line": "What the business does",
    "identity": "Who the agent is",
    "outbound_purpose": "Why it calls",
    "faqs": "Quick facts",
    "objections": "Answers to worries",
    "ending": "How it ends the call",
    "example_exchange": "The example call",
    "style": "How it speaks",
    # A warning a fix still leaves that is about the steps as a whole ("no step asks for").
    "script": "The script",
}

_ASIDE: Final = re.compile(r"\s*\([^)]*\)")


def part_label(part: LeftOut) -> str:
    """The part's name as the owner knows it: a step by its name, a field by its label."""
    if part.part.startswith("stages."):
        return f"Step “{part.name}”" if part.name else "A step"
    return _PART_LABELS.get(part.part, part.part.replace("_", " ").capitalize())


def owner_rule(rule: str) -> str:
    """A rule the model was told it broke, as the owner reads it: an aside in brackets goes,
    since it may name the vendor a line mentioned (D-679), and the sentence is closed."""
    said = _ASIDE.sub("", rule).strip().rstrip(".;")
    return f"{said[:1].upper()}{said[1:]}." if said else "It broke one of the call rules."


def unwritten_note(parts: Sequence[LeftOut]) -> str:
    """The failure note when the parts Pip could not write are known: which, and why."""
    shown = [f"{part_label(p)}: {owner_rule(p.rule).rstrip('.')}" for p in parts[:3]]
    more = f" and {len(parts) - 3} more" if len(parts) > 3 else ""
    return (
        f"Pip could not write a clean version of {'; '.join(shown)}{more}. Edit those parts "
        "yourself, or ask Pip to change one of them at a time."
    )


def left_out_record(parts: Sequence[LeftOut]) -> list[dict[str, Any]]:
    return [
        {
            "part": p.part,
            "name": p.name,
            "rule": owner_rule(p.rule),
            "added": p.added,
            "unfixed": p.unfixed,
        }
        for p in parts
    ]


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
    #: The only lines a fix may change ("Fix them first"): the paths the script check named
    #: (`script_lint.script_problems`). Empty for every other proposal.
    paths: list[str] = field(default_factory=list)
    #: Ready: the parts kept as the owner had them, and each warning a fix or the
    #: call-mistake check of Pip's writing still leaves (`fix_left`, D-989). Failed: the
    #: parts that could not be written. Each `rule` is already in the owner's words
    #: (`owner_rule`).
    left_out: list[LeftOut] = field(default_factory=list)
    #: Failed: the refusal code (`assist_answer_unusable`, `provider_unavailable`, ...).
    reason: str | None = None
    #: A fix the healer asked for (D-985): the call mistake its findings are read for.
    mistake_kind: str | None = None


def left_out_of(raw: Any) -> list[LeftOut]:
    return [
        LeftOut(
            part=str(item.get("part", "")),
            name=str(item.get("name", "")),
            rule=str(item.get("rule", "")),
            added=bool(item.get("added", False)),
            unfixed=bool(item.get("unfixed", False)),
        )
        for item in raw or []
        if isinstance(item, dict)
    ]


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
        paths=[str(p) for p in raw.get("paths") or []],
        left_out=left_out_of(raw.get("left_out")),
        reason=raw.get("reason"),
        mistake_kind=raw.get("mistake_kind"),
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
    requested_by: UUID | None,
    paths: Sequence[str] = (),
    replace_ready: bool = True,
    mistake_kind: str | None = None,
) -> ScriptProposal:
    """Record the request and queue the job that writes it, in the caller's transaction.

    One still being drafted is refused, so two requests cannot race to write the same
    review. One waiting for review is replaced only with `replace_ready`: a screen whose
    owner has not seen it passes False and gets `script_suggestion_waiting`, so a suggestion
    (and their rewording of it) is never thrown away unseen. `paths`: a fix, which may
    change only those lines (`kept_to_paths`). `requested_by` None: the healer asked
    (D-985), and `mistake_kind` is the call mistake whose script check (`mistake_lints`)
    names the findings at `paths`, in place of `script_lint.script_problems`."""
    return await _request(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        mode=mode,
        change=change,
        answers=answers,
        requested_by=requested_by,
        paths=paths,
        replace_ready=replace_ready,
        mistake_kind=mistake_kind,
    )


async def request_opening_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    requested_by: UUID | None,
    replace_ready: bool = True,
) -> ScriptProposal:
    """Ask for the opening line written to follow the agent's introduction (`OPENING_MODE`),
    as `request_proposal` asks for any other."""
    return await _request(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        mode=OPENING_MODE,
        change=None,
        answers={},
        requested_by=requested_by,
        replace_ready=replace_ready,
    )


async def request_written_script(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    requested_by: UUID | None,
    replace_ready: bool = True,
) -> ScriptProposal:
    """Ask for a new agent's whole script written for this business (`STARTER_MODE`), as
    `request_proposal` asks for any other."""
    return await _request(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        mode=STARTER_MODE,
        change=None,
        answers={},
        requested_by=requested_by,
        replace_ready=replace_ready,
    )


async def request_written_opening(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    requested_by: UUID | None,
    replace_ready: bool = True,
) -> ScriptProposal:
    """Ask for the agent's opening lines written for this business in its main language
    (`WRITTEN_MODE`), as `request_proposal` asks for any other."""
    status = (
        await session.execute(
            text("SELECT status FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).scalar_one_or_none()
    if status == "archived":
        raise archived_refusal("edited")
    return await _request(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        mode=WRITTEN_MODE,
        change=None,
        answers={},
        requested_by=requested_by,
        replace_ready=replace_ready,
    )


#: The change asked for by "Re-adjust script" on the agent page (founder, 9 Nov 2026). An
#: ordinary `change` request, so the writer's rules, its repair, the woven notices (D-971) and
#: the review on the Script tab are the ones every Pip change gets. It names the main task
#: rather than leaving the writer to find it in the script, because the owner may have just
#: edited it there and wants the rest of the script brought into line with it.
MAIN_TASK_CHANGE: Final = (
    "Adjust this script to its main task: {goal}\n"
    "Rework the steps, the questions it asks, its answers when callers push back and how it "
    "ends the call so each one serves that task. Keep what already serves it, keep the "
    "opening line unless it works against the task, and change nothing only for the sake of "
    "changing it. A step that takes something about the caller as given (that they use it, "
    "have it or asked for it) is reached only after a step asks it and branches on the "
    "answer; fix any step that does not."
)

#: Refused when the agent has no main task to adjust the script to.
MAIN_TASK_MISSING: Final = "script_main_task_missing"
#: Refused for a script written as one text: the writer edits a script in steps (A-01).
MAIN_TASK_HAND_WRITTEN: Final = "script_main_task_hand_written"


async def request_main_task_fit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    requested_by: UUID | None,
) -> ScriptProposal:
    """Ask for the working script adjusted to its own main task (`CallScript.goal`).

    Made from the working copy, so a main task the owner has just saved into the draft is the
    one used. Never replaces a suggestion waiting for review (A-14)."""
    status = (
        await session.execute(
            text("SELECT status FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).scalar_one_or_none()
    if status is None:
        raise ProblemError.not_found("Agent")
    if status == "archived":
        raise archived_refusal("edited")
    base = await working_script(session, agent_id)
    if base.is_raw:
        raise ProblemError.business_rule(
            MAIN_TASK_HAND_WRITTEN,
            "Pip cannot re-adjust a script written as one text.",
            remediation="Ask Pip to turn it into steps first.",
        )
    goal = base.goal.strip()
    if not goal:
        raise ProblemError.business_rule(
            MAIN_TASK_MISSING,
            "This agent has no main task yet.",
            remediation="Add its main task, then re-adjust the script.",
        )
    return await _request(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        mode="change",
        change=MAIN_TASK_CHANGE.format(goal=goal),
        answers={},
        requested_by=requested_by,
        replace_ready=False,
    )


#: Refused when a new request would replace a suggestion the owner has not kept or
#: discarded yet (A-14).
SUGGESTION_WAITING: Final = "script_suggestion_waiting"


async def _request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    mode: StoredMode,
    change: str | None,
    answers: dict[str, str],
    requested_by: UUID | None,
    paths: Sequence[str] = (),
    replace_ready: bool = True,
    mistake_kind: str | None = None,
) -> ScriptProposal:
    await session.execute(
        text("SELECT 1 FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"),
        {"aid": agent_id},
    )
    pending = await read_proposal(session, agent_id)
    if pending is not None and pending.status == "drafting":
        raise ProblemError.conflict(
            "script_proposal_in_progress",
            "Pip is still preparing the last change to this script.",
            remediation="Wait for it to be ready, then ask for the next one.",
        )
    if pending is not None and pending.status == "ready" and not replace_ready:
        raise ProblemError.conflict(
            SUGGESTION_WAITING,
            "A suggestion from Pip is already waiting.",
            remediation="Keep or discard it first, then ask again.",
        )
    base = await working_script(session, agent_id)
    proposal_id = uuid7()
    now = datetime.now(UTC)
    record: dict[str, Any] = {
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
        "requested_by": None if requested_by is None else str(requested_by),
        "requested_at": now.isoformat(),
        "paths": list(paths),
    }
    if mistake_kind is not None:
        record["mistake_kind"] = mistake_kind
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
    left_out: Sequence[LeftOut] = (),
    repairs: int = 0,
    truncated: bool = False,
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
            "left_out": left_out_record(left_out),
            "repairs": repairs,
            "truncated": truncated,
        },
    )


async def store_failed(
    session: AsyncSession,
    *,
    agent_id: UUID,
    proposal_id: UUID,
    note: str,
    reason: str | None = None,
    left_out: Sequence[LeftOut] = (),
    repairs: int = 0,
    truncated: bool = False,
) -> bool:
    return await _update_if_current(
        session,
        agent_id,
        proposal_id,
        {
            "status": "failed",
            "note": note[:400],
            "reason": reason,
            "left_out": left_out_record(left_out),
            "repairs": repairs,
            "truncated": truncated,
        },
    )


async def apply_untouched_starter(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    proposal: ScriptProposal,
    script: CallScript,
) -> bool:
    """Put a new agent's written script (`STARTER_MODE`) on it at once, instead of leaving it
    a suggestion, while that is safe: the agent is still a draft, so no caller hears it, and
    its script is still the starter it was made with, untouched, with nothing autosaved. Until
    then the agent showed the job's generic goal and steps as its own (founder, 3 Nov 2026).
    False leaves the suggestion for the owner, as before."""
    row = (
        await session.execute(
            text(
                "SELECT status, script_draft IS NULL FROM agents "
                "WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or row[0] != "draft" or not row[1]:
        return False
    current = upgrade_to_v2((await script_builder.load_agent_script(session, agent_id)).script)
    if current != proposal.base_script:
        return False
    await script_builder.save_agent_script(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        script=script,
        notes="Script written for the business",
        created_by=None,
    )
    await session.execute(
        text(
            "UPDATE agents SET script_proposal = NULL "
            "WHERE id = :aid AND script_proposal->>'id' = :pid"
        ),
        {"aid": agent_id, "pid": str(proposal.id)},
    )
    # Its details follow from this script (`workers/agent_fields_draft`), over the set it
    # started with only while that set is untouched.
    await enqueue_outbox_once(
        session,
        job=AGENT_FIELDS_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "fields": await agent_own_fields(session, agent_id),
        },
        dedupe_key=f"agent-fields:{agent_id}",
    )
    return True


async def agent_own_fields(session: AsyncSession, agent_id: UUID) -> list[dict[str, Any]]:
    """The details this agent writes down beyond the core, as stored."""
    row = (
        await session.execute(
            text(
                "SELECT es.fields FROM agents a LEFT JOIN extraction_schemas es "
                "ON es.id = a.extraction_schema_id WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    return [field.model_dump(mode="json") for field in business_only(row[0] if row else None)]


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


async def brief_for(
    session: AsyncSession, tenant_id: UUID, agent_id: UUID, *, language: str | None = None
) -> ScriptBrief:
    """What every draft is written from besides the owner's words: the business, the
    agent's direction and call language with its spoken register, the details it collects
    and the knowledge titles, what it can do on a call and the owner's facts (D-945).
    `language` writes it in another language than the agent's own (a campaign's main
    language). Tenant-authored configuration only (D-127 G-2)."""
    row = (
        await session.execute(
            text(
                "SELECT a.direction, a.language_primary, o.vertical_template, o.name, a.name, "
                "CASE WHEN a.ai_disclosure_enabled THEN a.ai_disclosure_line ELSE '' END, "
                "a.ai_disclosure_enabled, a.recording_notice_enabled "
                "FROM agents a JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL AND o.id = :tid"
            ),
            {"aid": agent_id, "tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    language = language or str(row[1])
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
        woven=WovenNotices(
            ai=bool(row[6]),
            recording=bool(row[7]) and engine_capabilities().records_audio,
        ),
        capabilities=await manifest_for(session, tenant_id=tenant_id, agent_id=agent_id),
        facts=await owner_facts(session, tenant_id=tenant_id, agent_id=agent_id),
        step_plans=tuple(
            (await stored_plans(session, tenant_id=tenant_id, shapes=JOB_STEP_COUNTS)).items()
        ),
        # The agent's own job, as the switches the owner is editing say it (G1-2): the
        # autosaved working copy when there is one, else the draft version.
        fit=(await business_fit(session, tenant_id)).for_agent(
            await _edited_policies(session, agent_id)
        ),
    )


async def _edited_policies(session: AsyncSession, agent_id: UUID) -> ScriptPolicies:
    draft = await script_builder.read_draft(session, agent_id)
    if draft is not None:
        return draft.script.policies
    return (await script_builder.load_agent_script(session, agent_id)).script.policies


def _stage_index(script: CallScript, stage_id: str) -> int | None:
    return next((i for i, s in enumerate(script.stages) if s.id == stage_id), None)


def _at(data: Any, parts: list[str]) -> Any:
    for part in parts:
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return None
    return data


def _put(data: Any, parts: list[str], value: str) -> None:
    for part in parts[:-1]:
        data = data[int(part)] if isinstance(data, list) else data[part]
    last = parts[-1]
    if isinstance(data, list):
        data[int(last)] = value
    else:
        data[last] = value


def kept_to_paths(
    written: CallScript,
    base: CallScript,
    paths: Sequence[str],
    *,
    unasked: Sequence[str] = (),
) -> CallScript:
    """`base` with only the lines at `paths` taken from `written` (A-02): a fix asked for
    the lines the script check named and may change nothing else, whatever the model
    returned. A step is matched by its id, since the model may reorder steps; a line the
    model emptied, or a path it no longer has, stays as the owner wrote it. A finding about
    the whole script ("no step asks for X") may reword step instructions and add each label
    in `unasked` to the details one step collects (`_collect_from`), nothing more. The two
    findings about the call's shape are the exception, below."""
    allowed = {p for p in paths if p != "script"}
    if "script" in paths:
        allowed |= {f"stages.{i}.instruction" for i in range(len(base.stages))}
    out = base.model_dump(mode="json")
    new = written.model_dump(mode="json")
    for path in sorted(allowed):
        parts = path.split(".")
        source = parts
        if parts[0] == "stages" and len(parts) > 2 and parts[1].isdigit():
            index = int(parts[1])
            if index >= len(base.stages):
                continue
            moved = _stage_index(written, base.stages[index].id)
            if moved is None:
                continue
            source = ["stages", str(moved), *parts[2:]]
        before, after = _at(out, parts), _at(new, source)
        if isinstance(before, str) and isinstance(after, str) and after.strip():
            _put(out, parts, after)
    _fit_step_details(out, base, written)
    kept = CallScript.model_validate(out)
    if "script" in paths and unasked:
        kept = _collect_from(written, kept, unasked)
    # Two findings are about the call's shape, not a line, and their fix is not a reworded
    # instruction (`script_lint.flow_problems`): a step in the wrong place on the call is
    # fixed by its ways out or its place, and a placeholder step by taking it out.
    named = {p for p in paths if p.startswith("stages.")}
    misplaced = {p.partition(":")[0] for p in order_problems(base)}
    if named & misplaced:
        kept = _ways_from(written, kept)
    return without_placeholder_steps(kept) if named & _placeholder_paths(base) else kept


def _fit_step_details(out: dict[str, Any], base: CallScript, written: CallScript) -> None:
    """Each step of `out` whose instruction and "sounds like" line no longer fit one step
    detail together (`ConversationStage._detail_fits_a_step`), one taken from `written` and
    the other kept: the written step's pair, which fit together there, else the owner's step
    as it was. A step that failed validation here crashed the job after the model was paid."""
    by_id = {stage.id: stage for stage in written.stages}
    for i, raw in enumerate(out["stages"]):
        if _fits(raw):
            continue
        own = base.stages[i]
        fixed = by_id.get(own.id)
        paired = (
            {**raw, "instruction": fixed.instruction, "sounds_like": fixed.sounds_like}
            if fixed is not None
            else None
        )
        out["stages"][i] = (
            paired if paired is not None and _fits(paired) else own.model_dump(mode="json")
        )


def _fits(raw: dict[str, Any]) -> bool:
    try:
        ConversationStage.model_validate(raw)
    except ValidationError:
        return False
    return True


def _placeholder_paths(script: CallScript) -> set[str]:
    """The instructions of the steps a fix may take out: placeholders, never the close."""
    return {
        f"stages.{i}.instruction"
        for i, stage in enumerate(script.stages[:-1])
        if placeholder_instruction(stage.instruction)
    }


def _ways_from(written: CallScript, kept: CallScript) -> CallScript:
    """`kept` with each step's ways out, and the steps' order, as `written` has them. A step
    `written` dropped keeps its own; a way to a step `kept` lacks goes (`ways_to_kept_steps`)."""
    by_id = {stage.id: stage for stage in written.stages}
    stages = [
        stage.model_copy(
            update={"branches": by_id[stage.id].branches, "otherwise": by_id[stage.id].otherwise}
        )
        if stage.id in by_id
        else stage
        for stage in kept.stages
    ]
    if set(by_id) == {stage.id for stage in stages}:
        rank = {stage_id: i for i, stage_id in enumerate(by_id)}
        stages.sort(key=lambda stage: rank[stage.id])
    return CallScript.model_validate(
        {
            **kept.model_dump(mode="json"),
            "stages": ways_to_kept_steps([stage.model_dump(mode="json") for stage in stages]),
        }
    )


def _collect_from(written: CallScript, kept: CallScript, unasked: Sequence[str]) -> CallScript:
    """`kept` with each label in `unasked` added to the details of the first step that
    `written` (matched by id) has collecting it, while that step has room. Only those labels
    are taken: any other detail the model put in a list stays out. A step's `collect` is what
    `script_lint.unasked_details` accepts as asking for a detail in any language, where its
    English-word reading of an instruction cannot see a step written in Telugu or Hindi."""
    stages = list(kept.stages)
    collects = {s.id: {c.casefold() for c in s.collect} for s in written.stages}
    for raw in unasked:
        label = " ".join(raw.split())[:80]
        key = label.casefold()
        for i, stage in enumerate(stages):
            has = {c.casefold() for c in stage.collect}
            if key in collects.get(stage.id, set()) and key not in has:
                if len(stage.collect) < MAX_STAGE_COLLECT:
                    stages[i] = stage.model_copy(update={"collect": [*stage.collect, label]})
                break
    return kept.model_copy(update={"stages": stages})


def finding_key(problem: str, script: CallScript) -> str:
    """Where a script check finding is, by the step's id rather than its place, so a finding
    is still recognised after a fix moved or removed a step before it."""
    path = problem.partition(": ")[0]
    head, _, rest = path.partition(".")
    index, _, field_path = rest.partition(".")
    if head == "stages" and index.isdigit() and int(index) < len(script.stages):
        return f"stages#{script.stages[int(index)].id}.{field_path}"
    return path


#: How a fix finding that no step asks for a detail is fixed, in any call language.
_UNASKED_FIX: Final = (
    'For a detail no step asks for: add that detail, word for word as quoted, to the "collect" '
    "list of the one step where the call reaches it, and have that step's instruction ask it "
    "as one question. Change no other step for it."
)


def fix_change(problems: Sequence[str], script: CallScript) -> str:
    """What the writer is asked for when fixing script check findings: each finding at its
    real place in the script JSON it is given (`stages.9.sounds_like`, numbered from 0, with
    the step's id and name), not the owner's "Step 10", which named the step after it."""

    def where(problem: str) -> str:
        path, _, rest = problem.partition(": ")
        parts = path.split(".")
        if parts[0] == "stages" and len(parts) > 1 and parts[1].isdigit():
            index = int(parts[1])
            if index < len(script.stages):
                stage = script.stages[index]
                return f'{path} (step id "{stage.id}", named "{stage.name}"): {rest}'
        return f"{path}: {rest}"

    lines = [
        "Fix only these problems the script check found, and change nothing else. Each "
        "starts with the field it is in, as a path in the script JSON (stages counted from 0).",
        *(f"- {where(problem)}" for problem in problems),
    ]
    if any(problem.startswith("script: ") for problem in problems):
        lines.append(_UNASKED_FIX)
    return "\n".join(lines)


def fix_left(problems: Sequence[str], script: CallScript) -> list[LeftOut]:
    """Each finding a fix could not clear, as a part of the proposal the owner reads: the
    step it is in (by id and name) or the field, and the warning itself."""
    left: list[LeftOut] = []
    for problem in problems:
        path, _, rest = problem.partition(": ")
        parts = path.split(".")
        part, name = parts[0], ""
        if part == "stages" and len(parts) > 1 and parts[1].isdigit():
            index = int(parts[1])
            if index < len(script.stages):
                part, name = f"stages.{script.stages[index].id}", script.stages[index].name
        left.append(LeftOut(part, name, f"Still to fix: {rest}", unfixed=True))
    return left


#: The parts an automatic suggestion may not empty (`emptied_kept`).
_KEPT_TEXT: Final = (
    "business_line",
    "identity",
    "goal",
    "outbound_purpose",
    "opening_line",
    "outbound_opening_line",
    "ending",
)
_KEPT_LISTS: Final = ("stages", "objections", "faqs", "example_exchange")


def emptied_kept(written: CallScript, base: CallScript) -> CallScript:
    """`written` with every part `base` had and the model left empty put back (A-02). For a
    suggestion nobody asked for in those words (a document's, a fix): an emptied part is
    never what it was for."""
    restored: dict[str, Any] = {
        name: getattr(base, name)
        for name in (*_KEPT_TEXT, *_KEPT_LISTS)
        if _filled(getattr(base, name)) and not _filled(getattr(written, name))
    }
    return written.model_copy(update=restored) if restored else written


def _filled(value: Any) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


__all__ = [
    "AGENT_FIELDS_JOB",
    "DRAFTING_STALE_AFTER",
    "FAILED_NOTE",
    "KNOWLEDGE_MODE",
    "MAX_ANSWER_CHARS",
    "MAX_CHANGE_CHARS",
    "MAX_KNOWLEDGE_DOCUMENTS",
    "MIN_REQUEST_CHARS",
    "OPENING_MODE",
    "PROPOSAL_JOB",
    "PROPOSAL_MODES",
    "STALE_NOTE",
    "STARTER_MODE",
    "SUGGESTION_WAITING",
    "SUGGEST_JOB",
    "TOO_BIG_NOTE",
    "WRITTEN_MODE",
    "ProposalMode",
    "ProposalStatus",
    "ScriptProposal",
    "brief_for",
    "discard",
    "emptied_kept",
    "finding_key",
    "fix_change",
    "fix_left",
    "kept_to_paths",
    "left_out_of",
    "left_out_record",
    "owner_rule",
    "part_label",
    "queue_document_suggestions",
    "read_proposal",
    "request_knowledge_proposal",
    "request_opening_proposal",
    "request_proposal",
    "request_text",
    "request_written_opening",
    "request_written_script",
    "store_failed",
    "store_ready",
    "unwritten_note",
    "working_script",
]
