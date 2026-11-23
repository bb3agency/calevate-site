"""A campaign's own main task, sources and script (D-992, founder 15 Nov 2026: "The agent is
just a voice which will deliver the message ... The campaign will control what and how the
agents deliver").

The campaign holds what its calls say; the agent it is given is the voice. Pip writes the
script from the main task and the sources the campaign picked from What your agents know
(founder, 16 Nov 2026: one place to add things; `kb/picks.py`), through
`workers/campaign_script.py` and the one script writer `workers/script_assist.draft_script`;
the owner reviews it with the same
review the Script page uses, and Start puts it live on the campaign's own engine agent, in its
agent's voice (`campaigns/engine_agent.put_campaign_live`, D-1003): the agent's own script and
the numbers it answers are never touched, and any number of campaigns may share one voice.

The pending Pip draft lives on the campaign row (`campaigns.script_proposal`), one at a time,
written with a compare-and-set on its id; the healer's fix of a mistake on the campaign's calls
is written there too (D-1005, `agents/mistake_fixes.request_holder_fix`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_proposals
from apps.api.agents.field_suggestions import queue_job
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.kb.picks import CAMPAIGN_PICKS, add_pick, read_picks, replace_picks
from apps.api.reliability.service import enqueue_outbox
from apps.workers.script_assist import LeftOut

MAIN_TASK_MAX: Final = 4_000
NOTE_MAX: Final = 4_000
TITLE_MAX: Final = 200
#: The job that writes a campaign's script (`workers/campaign_script.py`).
CAMPAIGN_SCRIPT_JOB: Final = "draft_campaign_script"
#: A draft still "drafting" after this long is shown as failed: the job died without writing.
STALE_AFTER_S: Final = 15 * 60
FAILED_NOTE: Final = "Pip could not write the script this time. Try again."

ProposalStatus = Literal["drafting", "ready", "failed"]


@dataclass(frozen=True)
class CampaignProposal:
    id: UUID
    status: ProposalStatus
    requested_at: datetime
    base_script: CallScript | None
    script: CallScript | None
    note: str | None
    #: Who wrote it when it was not the account's own model (D-127 G-6), shown with it.
    disclosure: str | None = None
    #: Ready: parts kept as the owner had them and warnings Pip could not clear. Failed:
    #: the parts it could not write (`script_proposals.LeftOut`).
    left_out: tuple[LeftOut, ...] = ()
    #: Failed: why, as the refusal's code (`assist_answer_unusable`, `ai_quota_exceeded`, ...),
    #: `crashed`, or `stale` for a job that never wrote back; the screen picks its words by it.
    reason: str | None = None
    #: Ready: Pip's one-sentence reason per part it wrote, by the part's key (`opening_line`,
    #: `stages.<id>`, ...), for the owner to read beside it (D-1004).
    why: dict[str, str] = field(default_factory=dict)
    #: A fix the healer asked for (D-1005): the mistake on real calls it fixes, in the
    #: owner's words. None for a draft the owner asked for.
    fixes: str | None = None
    #: The one part asked for (`focus.part`: "flow", "translate", a part's name), or None.
    focus_part: str | None = None


def _why(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str) and v.strip()}


@dataclass(frozen=True)
class Workspace:
    campaign_id: UUID
    agent_id: UUID
    status: str
    main_task: str
    script: CallScript | None
    script_live_version: int | None
    proposal: CampaignProposal | None
    #: The sources from What your agents know it is written from.
    sources: tuple[UUID, ...]
    #: When the copy of the script from before Pip's last draft was taken; None: no copy.
    script_before_pip_at: datetime | None = None


def _script(raw: Any) -> CallScript | None:
    if not raw:
        return None
    return CallScript.model_validate(raw)


def _proposal(raw: Any, *, now: datetime) -> CampaignProposal | None:
    if not raw:
        return None
    requested_at = datetime.fromisoformat(str(raw["requested_at"]))
    status: ProposalStatus = raw.get("status", "drafting")
    note = raw.get("note")
    reason = raw.get("reason")
    if status == "drafting" and (now - requested_at).total_seconds() > STALE_AFTER_S:
        status, note, reason = "failed", FAILED_NOTE, "stale"
    return CampaignProposal(
        id=UUID(str(raw["id"])),
        status=status,
        requested_at=requested_at,
        base_script=_script(raw.get("base_script")),
        script=_script(raw.get("script")),
        note=note,
        disclosure=raw.get("disclosure"),
        left_out=tuple(script_proposals.left_out_of(raw.get("left_out"))),
        reason=reason,
        why=_why(raw.get("why")),
        fixes=raw.get("fix_label"),
        focus_part=str(raw["focus"].get("part"))
        if isinstance(raw.get("focus"), dict) and raw["focus"].get("part")
        else None,
    )


#: The Pip draft and the script in the shape an inbound line keeps them too (D-997): one
#: reader for both holders, so the two review screens cannot read a draft differently.
read_call_script = _script
read_script_proposal = _proposal


async def _campaign_row(session: AsyncSession, campaign_id: UUID, *, lock: bool = False) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT id, agent_id, status, main_task, script, script_proposal, "
                "script_live_version, script_before_pip_at FROM campaigns "
                "WHERE id = :cid AND archived_at IS NULL" + (" FOR UPDATE" if lock else "")
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return row


async def read_workspace(session: AsyncSession, campaign_id: UUID) -> Workspace:
    row = await _campaign_row(session, campaign_id)
    picked = await read_picks(session, CAMPAIGN_PICKS, [campaign_id])
    return Workspace(
        campaign_id=row.id,
        agent_id=row.agent_id,
        status=row.status,
        main_task=row.main_task or "",
        script=_script(row.script),
        script_live_version=row.script_live_version,
        proposal=_proposal(row.script_proposal, now=datetime.now(UTC)),
        sources=tuple(picked[campaign_id]),
        script_before_pip_at=row.script_before_pip_at,
    )


def _invalid(code: str, title: str, detail: str) -> ProblemError:
    return ProblemError(kind="validation", code=code, title=title, detail=detail)


def _clean(value: str, *, limit: int, field: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise _invalid(
            f"{field}_too_long", "That is too long", f"Keep this under {limit:,} characters."
        )
    return cleaned


async def save_main_task(session: AsyncSession, campaign_id: UUID, value: str) -> str:
    await _campaign_row(session, campaign_id)
    task = _clean(value, limit=MAIN_TASK_MAX, field="main_task")
    await session.execute(
        text("UPDATE campaigns SET main_task = :t, updated_at = now() WHERE id = :cid"),
        {"t": task or None, "cid": campaign_id},
    )
    await queue_job(session, "campaign", campaign_id)
    return task


async def save_script(session: AsyncSession, campaign_id: UUID, script: CallScript) -> None:
    """The owner's edit, or a reviewed Pip draft they kept. Held to the agent's own limits
    (`script_builder.refuse_if_too_long`), so Start can never be refused for its length."""
    from apps.api.agents import script_builder

    row = await _campaign_row(session, campaign_id, lock=True)
    await script_builder.refuse_if_too_long(session, row.agent_id, script)
    await session.execute(
        text("UPDATE campaigns SET script = CAST(:s AS jsonb), updated_at = now() WHERE id = :cid"),
        {"s": script.model_dump_json(), "cid": campaign_id},
    )
    await queue_job(session, "campaign", campaign_id)


async def _keep_before_pip(session: AsyncSession, campaign_id: UUID) -> None:
    """Copy the saved script aside before Pip writes (founder, 17 Nov 2026), so whatever the
    owner keeps of the draft, the flow they had can be put back. One copy, the latest."""
    await session.execute(
        text(
            "UPDATE campaigns SET script_before_pip = script, script_before_pip_at = now() "
            "WHERE id = :cid AND script IS NOT NULL"
        ),
        {"cid": campaign_id},
    )


async def restore_before_pip(session: AsyncSession, campaign_id: UUID) -> None:
    """Put back the script from before Pip's last draft. The two swap, so the script it
    replaces is kept as the copy and pressing again brings it back."""
    row = await _campaign_row(session, campaign_id, lock=True)
    held = (
        await session.execute(
            text("SELECT script_before_pip FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar()
    if not held:
        raise _invalid(
            "campaign_no_script_before_pip",
            "There is nothing to put back",
            "Pip has not written this campaign's script since it had one.",
        )
    previous = CallScript.model_validate(held)
    from apps.api.agents import script_builder

    await script_builder.refuse_if_too_long(session, row.agent_id, previous)
    await session.execute(
        text(
            "UPDATE campaigns SET script_before_pip = script, script = script_before_pip, "
            "script_before_pip_at = now(), updated_at = now() WHERE id = :cid"
        ),
        {"cid": campaign_id},
    )


async def set_sources(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    kb_source_ids: list[UUID],
    created_by: UUID | None,
) -> None:
    """The sources from What your agents know that Pip writes this campaign from, replacing
    the last choice. A source of another account is invisible under RLS and refused."""
    await _campaign_row(session, campaign_id, lock=True)
    await replace_picks(
        session,
        CAMPAIGN_PICKS,
        tenant_id=tenant_id,
        holder_id=campaign_id,
        kb_source_ids=kb_source_ids,
        created_by=created_by,
    )


async def pick_source(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    kb_source_id: UUID,
    created_by: UUID | None,
) -> None:
    """Pick one more source, keeping the others: a file or link added from the campaign page
    goes into What your agents know and is picked here."""
    await _campaign_row(session, campaign_id, lock=True)
    await add_pick(
        session,
        CAMPAIGN_PICKS,
        tenant_id=tenant_id,
        holder_id=campaign_id,
        kb_source_id=kb_source_id,
        created_by=created_by,
    )


async def add_note(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    title: str | None,
    note: str,
    created_by: UUID | None,
    auto_approve: bool,
) -> UUID:
    """A note written on the campaign page, or an answer to a question its calls raised, goes
    into What your agents know as a typed note and the campaign picks it. Answers its id.

    The name is made free ("Name (2)") rather than taken as given: a note sharing a name with
    an item already there would be that item's next version and replace it, which nobody
    writing on a campaign page means."""
    from apps.api.kb.service import submit_source
    from apps.api.kb.uploads import name_for_new_item

    await _campaign_row(session, campaign_id, lock=True)
    body = _clean(note, limit=NOTE_MAX, field="note")
    if not body:
        raise _invalid("note_required", "The note is empty", "Write the note.")
    given = _clean(title or "", limit=TITLE_MAX, field="title")
    name = await name_for_new_item(
        session, tenant_id=tenant_id, given=None, fallback=given or body[:60]
    )
    made = await submit_source(
        session,
        tenant_id=tenant_id,
        name=name,
        body=body,
        submitted_by=created_by,
        auto_approve=auto_approve,
    )
    source_id = UUID(str(made["id"]))
    await add_pick(
        session,
        CAMPAIGN_PICKS,
        tenant_id=tenant_id,
        holder_id=campaign_id,
        kb_source_id=source_id,
        created_by=created_by,
    )
    return source_id


async def add_link(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    url: str,
    name: str | None,
    created_by: UUID | None,
    auto_approve: bool,
) -> tuple[UUID, UUID]:
    """A web page added on the campaign page goes into What your agents know exactly as
    `POST /v1/kb/links` puts it, and the campaign picks it. Answers its source and upload ids.

    A name it is given is made free, as `add_note`'s is: taken as given, a name another item
    already has would make the link that item's next version, and publishing it would
    archive the item and take it off every agent."""
    from apps.api.kb.uploads import create_link, name_for_new_item

    await _campaign_row(session, campaign_id, lock=True)
    given = (name or "").strip()
    free = (
        await name_for_new_item(session, tenant_id=tenant_id, given=None, fallback=given)
        if given
        else None
    )
    made = await create_link(
        session,
        tenant_id=tenant_id,
        name=free,
        url=url.strip(),
        submitted_by=created_by,
        auto_approve=auto_approve,
    )
    source_id = UUID(str(made["source_id"]))
    await add_pick(
        session,
        CAMPAIGN_PICKS,
        tenant_id=tenant_id,
        holder_id=campaign_id,
        kb_source_id=source_id,
        created_by=created_by,
    )
    return source_id, UUID(str(made["id"]))


async def request_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    requested_by: UUID | None,
    focus: dict[str, str] | None = None,
    auto_save: bool = False,
    ask: dict[str, str] | None = None,
) -> CampaignProposal:
    """Ask Pip for the campaign's script. Needs a main task; replaces a ready draft; refused
    while one is still being written, so a second click does not spend twice.

    `auto_save`: the draft becomes the campaign's script as soon as it is written, with no
    review, while the campaign has none (the first run's campaign, Phase 3b).

    `focus` (`{"part": <the part's name as the editor shows it>, "language": <tag>}`) asks for
    that one part rewritten in that language, the rest kept (founder, 16 Nov 2026). It is an
    edit of the saved script, reviewed like any other draft, so it needs a script to edit.

    `ask` (`{"tone": ..., "instruction": ...}`, either may be absent) is how the owner wants
    this draft written (D-1004), for the whole script or the one part alike."""
    row = await _campaign_row(session, campaign_id, lock=True)
    if focus is not None and row.script is None:
        raise _invalid(
            "campaign_script_required",
            "Generate the script first",
            "Pip rewrites one part of a script that is already there.",
        )
    if not (row.main_task or "").strip():
        raise _invalid(
            "main_task_required",
            "Write the main task first",
            "Write the main task first, so Pip knows what the calls are for.",
        )
    now = datetime.now(UTC)
    pending = _proposal(row.script_proposal, now=now)
    if pending is None or pending.status != "drafting":
        await _keep_before_pip(session, campaign_id)
    if pending is not None and pending.status == "drafting":
        raise ProblemError.conflict(
            "campaign_script_in_progress",
            "Pip is still writing this campaign's script.",
            remediation="Wait for it to appear, or press Stop first.",
        )
    proposal_id = uuid7()
    record: dict[str, Any] = {
        "id": str(proposal_id),
        "status": "drafting",
        "requested_at": now.isoformat(),
        "requested_by": None if requested_by is None else str(requested_by),
        "base_script": row.script,
    }
    if focus is not None:
        record["focus"] = focus
    if ask:
        record["ask"] = ask
    if auto_save:
        record["auto_save"] = True
    await session.execute(
        text("UPDATE campaigns SET script_proposal = CAST(:p AS jsonb) WHERE id = :cid"),
        {"p": json.dumps(record), "cid": campaign_id},
    )
    await enqueue_outbox(
        session,
        job=CAMPAIGN_SCRIPT_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "campaign_id": str(campaign_id),
            "proposal_id": str(proposal_id),
        },
    )
    proposal = _proposal(record, now=now)
    assert proposal is not None
    return proposal


async def clear_proposal(session: AsyncSession, campaign_id: UUID, proposal_id: UUID) -> bool:
    """Stop a draft being written, or discard / settle a written one. The job's own write is a
    compare-and-set on the id, so a stopped draft is never written back."""
    await _campaign_row(session, campaign_id)
    done = (
        await session.execute(
            text(
                "UPDATE campaigns SET script_proposal = NULL WHERE id = :cid "
                "AND script_proposal->>'id' = :pid RETURNING id"
            ),
            {"cid": campaign_id, "pid": str(proposal_id)},
        )
    ).first()
    return done is not None


async def copy_workspace(
    session: AsyncSession, *, tenant_id: UUID, source_id: UUID, target_id: UUID
) -> None:
    """A copied campaign keeps what it says and how: the main task, the script, the second
    opening, the setting overrides, what it notes and the sources it picked. Pip's unreviewed
    proposal and the engine agent are not copied: the first belongs to the old draft's review,
    the second is made by the copy's own Start or test call."""
    await session.execute(
        text(
            "UPDATE campaigns AS t SET main_task = s.main_task, script = s.script, "
            "opening_b = s.opening_b, settings_overrides = s.settings_overrides, "
            "extraction_fields = s.extraction_fields, "
            "updated_at = now() FROM campaigns AS s WHERE t.id = :t AND s.id = :s"
        ),
        {"t": target_id, "s": source_id},
    )
    for kb_source_id in (await read_picks(session, CAMPAIGN_PICKS, [source_id]))[source_id]:
        await add_pick(
            session,
            CAMPAIGN_PICKS,
            tenant_id=tenant_id,
            holder_id=target_id,
            kb_source_id=kb_source_id,
            created_by=None,
        )


__all__ = [
    "CAMPAIGN_SCRIPT_JOB",
    "MAIN_TASK_MAX",
    "CampaignProposal",
    "Workspace",
    "add_link",
    "add_note",
    "clear_proposal",
    "pick_source",
    "read_call_script",
    "read_script_proposal",
    "read_workspace",
    "request_proposal",
    "save_main_task",
    "save_script",
    "set_sources",
]
