"""A campaign's own main task, materials and script (D-992, founder 15 Nov 2026: "The agent is
just a voice which will deliver the message ... The campaign will control what and how the
agents deliver").

The campaign holds what its calls say; the agent it is given is the voice. Pip writes the
script from the main task and the materials (`workers/campaign_script.py`, through the one
script writer `workers/script_assist.draft_script`), the owner reviews it with the same
review the Script page uses, and Start puts it live on the agent through the agent's own
publish (`agents/script_publish.put_draft_live`): version history, the compliance read-back
and the audit all apply exactly as they do to an agent script.

Why put live at Start rather than send the script with every call: a per-call override
(`overrides.callInstructions`) holds 4,000 characters (place-call.md, 6 Oct 2026 mirror), and
the bare built-in starter scripts already compile to 2,100-3,500 before any FAQ or document
is worked in. The agent's own instructions hold 20,000 (`engine/thinnest.INSTRUCTIONS_MAX_CHARS`).
The cost is that a voice speaks one campaign's script at a time, which Start enforces.

The pending Pip draft lives on the campaign row (`campaigns.script_proposal`), one at a time,
the same shape and compare-and-set discipline as `agents.script_proposal`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import CallScript
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import script_proposals
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
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
MaterialKind = Literal["file", "link", "note"]


@dataclass(frozen=True)
class Material:
    id: UUID
    kind: str
    source: str
    title: str
    url: str | None
    note: str | None
    kb_upload_id: UUID | None
    created_at: datetime


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


@dataclass(frozen=True)
class Workspace:
    campaign_id: UUID
    agent_id: UUID
    status: str
    main_task: str
    script: CallScript | None
    script_live_version: int | None
    proposal: CampaignProposal | None
    materials: list[Material]


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
    )


async def _campaign_row(session: AsyncSession, campaign_id: UUID, *, lock: bool = False) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT id, agent_id, status, main_task, script, script_proposal, "
                "script_live_version FROM campaigns WHERE id = :cid AND archived_at IS NULL"
                + (" FOR UPDATE" if lock else "")
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return row


async def list_materials(session: AsyncSession, campaign_id: UUID) -> list[Material]:
    rows = (
        await session.execute(
            text(
                "SELECT id, kind, source, title, url, note, kb_upload_id, created_at "
                "FROM campaign_materials WHERE campaign_id = :cid AND archived_at IS NULL "
                "ORDER BY created_at"
            ),
            {"cid": campaign_id},
        )
    ).all()
    return [Material(*row) for row in rows]


async def read_workspace(session: AsyncSession, campaign_id: UUID) -> Workspace:
    row = await _campaign_row(session, campaign_id)
    return Workspace(
        campaign_id=row.id,
        agent_id=row.agent_id,
        status=row.status,
        main_task=row.main_task or "",
        script=_script(row.script),
        script_live_version=row.script_live_version,
        proposal=_proposal(row.script_proposal, now=datetime.now(UTC)),
        materials=await list_materials(session, campaign_id),
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


async def add_material(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    kind: MaterialKind,
    title: str,
    url: str | None,
    note: str | None,
    kb_upload_id: UUID | None,
    created_by: UUID | None,
    source: Literal["owner", "call"] = "owner",
) -> Material:
    await _campaign_row(session, campaign_id)
    title = _clean(title, limit=TITLE_MAX, field="title")
    if not title:
        raise _invalid("title_required", "Name this material", "Give it a short name.")
    if kind == "note" and not (note or "").strip():
        raise _invalid("note_required", "The note is empty", "Write the note.")
    if kind == "file" and kb_upload_id is None:
        raise _invalid("file_required", "No file uploaded yet", "Upload the file first.")
    if kb_upload_id is not None:
        # RLS scopes this read to the caller's account, so another account's upload is absent.
        found = (
            await session.execute(
                text("SELECT 1 FROM kb_uploads WHERE id = :u"), {"u": kb_upload_id}
            )
        ).first()
        if found is None:
            raise ProblemError.not_found("Upload")
    material_id = uuid7()
    row = (
        await session.execute(
            text(
                "INSERT INTO campaign_materials (id, tenant_id, campaign_id, kind, source, title, "
                "url, note, kb_upload_id, created_by) VALUES (:id, :t, :c, :k, :s, :ti, :u, :n, "
                ":kb, :by) RETURNING id, kind, source, title, url, note, kb_upload_id, created_at"
            ),
            {
                "id": material_id,
                "t": tenant_id,
                "c": campaign_id,
                "k": kind,
                "s": source,
                "ti": title,
                "u": (url or "").strip() or None,
                "n": _clean(note or "", limit=NOTE_MAX, field="note") or None,
                "kb": kb_upload_id,
                "by": created_by,
            },
        )
    ).one()
    return Material(*row)


async def archive_material(session: AsyncSession, campaign_id: UUID, material_id: UUID) -> None:
    """Removing a material archives it (business data is never deleted in code)."""
    done = (
        await session.execute(
            text(
                "UPDATE campaign_materials SET archived_at = now(), updated_at = now() "
                "WHERE id = :m AND campaign_id = :c AND archived_at IS NULL RETURNING id"
            ),
            {"m": material_id, "c": campaign_id},
        )
    ).first()
    if done is None:
        raise ProblemError.not_found("Material")


async def request_proposal(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID, requested_by: UUID | None
) -> CampaignProposal:
    """Ask Pip for the campaign's script. Needs a main task; replaces a ready draft; refused
    while one is still being written, so a second click does not spend twice."""
    row = await _campaign_row(session, campaign_id, lock=True)
    if not (row.main_task or "").strip():
        raise _invalid(
            "main_task_required",
            "Write the main task first",
            "Write the main task first, so Pip knows what the calls are for.",
        )
    now = datetime.now(UTC)
    pending = _proposal(row.script_proposal, now=now)
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
    opening, the setting overrides and the live materials. Pip's unreviewed proposal and the
    agent hold are not copied: the first belongs to the old draft's review, the second to
    whichever campaign last started."""
    await session.execute(
        text(
            "UPDATE campaigns AS t SET main_task = s.main_task, script = s.script, "
            "opening_b = s.opening_b, settings_overrides = s.settings_overrides, "
            "updated_at = now() FROM campaigns AS s WHERE t.id = :t AND s.id = :s"
        ),
        {"t": target_id, "s": source_id},
    )
    materials = (
        await session.execute(
            text(
                "SELECT kind, source, title, url, note, kb_upload_id, created_by "
                "FROM campaign_materials WHERE campaign_id = :s AND archived_at IS NULL "
                "ORDER BY created_at, id"
            ),
            {"s": source_id},
        )
    ).all()
    for kind, source, title, url, note, kb_upload_id, created_by in materials:
        await session.execute(
            text(
                "INSERT INTO campaign_materials (id, tenant_id, campaign_id, kind, source, title, "
                "url, note, kb_upload_id, created_by) VALUES (:id, :tn, :c, :k, :src, :ti, :u, "
                ":n, :kb, :by)"
            ),
            {
                "id": uuid7(),
                "tn": tenant_id,
                "c": target_id,
                "k": kind,
                "src": source,
                "ti": title,
                "u": url,
                "n": note,
                "kb": kb_upload_id,
                "by": created_by,
            },
        )


async def put_script_live(
    *, tenant_id: UUID, campaign_id: UUID, campaign_name: str, user_id: UUID | None
) -> int | None:
    """Start's first step: the campaign's script becomes the agent's live script.

    Refused while another running or scheduled campaign has put its own script on the same
    agent, because a voice speaks one script at a time. A campaign with no script of its own
    leaves the agent's script as it is (campaigns made before D-992)."""
    from apps.api.agents import script_publish
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        row = await _campaign_row(session, campaign_id)
        script = _script(row.script)
        if script is None:
            return None
        clash = (
            await session.execute(
                text(
                    "SELECT name FROM campaigns WHERE agent_id = :a AND id <> :c "
                    "AND archived_at IS NULL AND script IS NOT NULL "
                    "AND status IN ('running', 'scheduled') LIMIT 1"
                ),
                {"a": row.agent_id, "c": campaign_id},
            )
        ).first()
        if clash is not None:
            raise ProblemError.conflict(
                "agent_busy_with_campaign",
                f"This agent is already speaking the campaign “{clash.name}”.",
                remediation="Pause that campaign first, or choose another agent for this one.",
            )
    # This campaign holds the agent from now: its settings overrides are what the publish
    # below, and every later drift repair, lay over the agent's defaults (D-994). Marked first
    # so the publish reads them; put back if the publish fails.
    async with tenant_session(tenant_id) as session:
        held_before = (
            await session.execute(
                text(
                    "UPDATE campaigns c SET agent_held_at = now() FROM "
                    "(SELECT agent_held_at AS before FROM campaigns WHERE id = :cid) old "
                    "WHERE c.id = :cid RETURNING old.before"
                ),
                {"cid": campaign_id},
            )
        ).scalar_one_or_none()
    try:
        done = await script_publish.put_draft_live(
            tenant_id=tenant_id,
            agent_id=row.agent_id,
            summary=f"Campaign: {campaign_name}"[:200],
            created_by=user_id,
            script=script,
            check_version=False,
            expected_version=None,
        )
    except BaseException:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE campaigns SET agent_held_at = :b WHERE id = :cid"),
                {"b": held_before, "cid": campaign_id},
            )
        raise
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script_live_version = :v WHERE id = :cid"),
            {"v": done.version, "cid": campaign_id},
        )
    return done.version


__all__ = [
    "CAMPAIGN_SCRIPT_JOB",
    "MAIN_TASK_MAX",
    "CampaignProposal",
    "Material",
    "Workspace",
    "add_material",
    "archive_material",
    "clear_proposal",
    "list_materials",
    "put_script_live",
    "read_workspace",
    "request_proposal",
    "save_main_task",
    "save_script",
]
