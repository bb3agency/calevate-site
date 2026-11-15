"""The company training: one per client, given to every agent (founder, 16 Nov 2026).

A real calling company gives every person it hires the same overview of the business before
assigning them to work. Calevate does the same: the owner describes the business in their own
words and adds documents, links and notes; Pip writes the training from them
(`workers/company_training_draft.py`); the owner reviews it and saves it; every agent of the
client is then given it, ahead of its own script.

WHERE IT SITS IN THE PROMPT. Inside the client fence, as the first section of the script
(`with_training`), not as a platform layer beside it: the business wrote it, so it is fenced
like everything else the business wrote (`CLIENT_SCRIPT_OPEN`), and the platform rules,
confidentiality and the truthful answers still come after it and win. Its lead sentence says
the script below wins where the two differ, so a campaign may change a company fact for its
own calls (founder, 16 Nov 2026). An agent of a client with no training composes byte for
byte as before.

A save reaches live agents through the live-apply seam (`queue_live_apply`, scope tenant), in
the transaction that saved it, and is refused first if any agent's instructions would no
longer fit the engine's box with it.

The pending Pip draft lives on the row (`company_trainings.proposal`), one at a time, with the
same compare-and-set discipline as `campaigns.script_proposal`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.engine import AgentConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox

OVERVIEW_MAX: Final = 4_000
#: The training shares the engine's 20,000-character box with the agent's script and our
#: rules; this keeps room for both.
TRAINING_MAX: Final = 6_000
NOTE_MAX: Final = 4_000
TITLE_MAX: Final = 200
#: The job that writes the training (`workers/company_training_draft.py`).
TRAINING_DRAFT_JOB: Final = "draft_company_training"
#: A draft still "drafting" after this long is shown as failed: the job died without writing.
STALE_AFTER_S: Final = 15 * 60
FAILED_NOTE: Final = "Pip could not write the training this time. Try again."

#: The script section the training is composed as. `prompt_size.SCRIPT_SECTION_LABELS` names it.
TRAINING_HEADER: Final = "[COMPANY TRAINING]"
TRAINING_LEAD: Final = (
    "Every agent of this business is trained on this. Where the script after it says "
    "something different, follow the script."
)

ProposalStatus = Literal["drafting", "ready", "failed"]
MaterialKind = Literal["file", "link", "note"]


@dataclass(frozen=True)
class Material:
    id: UUID
    kind: str
    title: str
    url: str | None
    note: str | None
    kb_upload_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class TrainingProposal:
    id: UUID
    status: ProposalStatus
    requested_at: datetime
    #: The training it was written from (None for the first one).
    base_training: str | None
    training: str | None
    note: str | None
    #: Who wrote it when it was not the account's own model (D-127 G-6), shown with it.
    disclosure: str | None = None
    #: Failed: the refusal's code, `crashed`, or `stale` for a job that never wrote back.
    reason: str | None = None


@dataclass(frozen=True)
class Training:
    overview: str
    training: str
    version: int
    updated_at: datetime | None
    proposal: TrainingProposal | None
    materials: list[Material]


# --- composing it into an agent ------------------------------------------------------------


def _unbracketed(line: str) -> str:
    """A line the owner starts with `[` would read as a new script section to every splicer
    that walks the script by its headers (`prompt_size.script_parts`, the known-facts and T0
    splicers), so it is indented out of that shape."""
    return f"- {line}" if line.startswith("[") else line


def training_section(training: str) -> str:
    """The training as the script section every agent carries, or '' with none."""
    body = training.strip()
    if not body:
        return ""
    lines = "\n".join(_unbracketed(line) for line in body.splitlines())
    return f"{TRAINING_HEADER}\n{TRAINING_LEAD}\n{lines}"


def with_training(cfg: AgentConfig, training: str) -> AgentConfig:
    """`cfg` with the company training as the first section of its script. A no-op without
    a training, so an agent of a client that has none composes exactly as before."""
    section = training_section(training)
    if not section:
        return cfg
    script = (cfg.system_prompt or "").strip()
    combined = f"{section}\n\n{script}" if script else section
    return cfg.model_copy(update={"system_prompt": combined})


async def live_text(session: AsyncSession) -> str:
    """The saved training of the session's client, '' when it has none. RLS scopes the read."""
    found = (
        await session.execute(text("SELECT training FROM company_trainings LIMIT 1"))
    ).scalar_one_or_none()
    return str(found or "")


# --- reading -----------------------------------------------------------------------------


def _proposal(raw: Any, *, now: datetime) -> TrainingProposal | None:
    if not raw:
        return None
    requested_at = datetime.fromisoformat(str(raw["requested_at"]))
    status: ProposalStatus = raw.get("status", "drafting")
    note = raw.get("note")
    reason = raw.get("reason")
    if status == "drafting" and (now - requested_at).total_seconds() > STALE_AFTER_S:
        status, note, reason = "failed", FAILED_NOTE, "stale"
    return TrainingProposal(
        id=UUID(str(raw["id"])),
        status=status,
        requested_at=requested_at,
        base_training=raw.get("base_training"),
        training=raw.get("training"),
        note=note,
        disclosure=raw.get("disclosure"),
        reason=reason,
    )


async def _row(session: AsyncSession, tenant_id: UUID, *, lock: bool = False) -> Any:
    """The client's row, made on first use: every client has exactly one training."""
    await session.execute(
        text(
            "INSERT INTO company_trainings (id, tenant_id) VALUES (:id, :t) "
            "ON CONFLICT (tenant_id) DO NOTHING"
        ),
        {"id": uuid7(), "t": tenant_id},
    )
    return (
        await session.execute(
            text(
                "SELECT overview, training, proposal, version, updated_at FROM company_trainings "
                "WHERE tenant_id = :t" + (" FOR UPDATE" if lock else "")
            ),
            {"t": tenant_id},
        )
    ).one()


async def list_materials(session: AsyncSession) -> list[Material]:
    rows = (
        await session.execute(
            text(
                "SELECT id, kind, title, url, note, kb_upload_id, created_at "
                "FROM company_training_materials WHERE archived_at IS NULL "
                "ORDER BY created_at, id"
            )
        )
    ).all()
    return [Material(*row) for row in rows]


async def read_training(session: AsyncSession, tenant_id: UUID) -> Training:
    row = await _row(session, tenant_id)
    return Training(
        overview=row.overview or "",
        training=row.training or "",
        version=int(row.version),
        updated_at=row.updated_at if row.version else None,
        proposal=_proposal(row.proposal, now=datetime.now(UTC)),
        materials=await list_materials(session),
    )


# --- writing -----------------------------------------------------------------------------


def _invalid(code: str, title: str, detail: str) -> ProblemError:
    return ProblemError(kind="validation", code=code, title=title, detail=detail)


def _clean(value: str, *, limit: int, field: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise _invalid(
            f"{field}_too_long", "That is too long", f"Keep this under {limit:,} characters."
        )
    return cleaned


async def save_overview(session: AsyncSession, tenant_id: UUID, value: str) -> str:
    """The owner's own words about the business. Pip reads them; agents do not."""
    await _row(session, tenant_id)
    overview = _clean(value, limit=OVERVIEW_MAX, field="overview")
    await session.execute(
        text("UPDATE company_trainings SET overview = :o, updated_at = now() WHERE tenant_id = :t"),
        {"o": overview or None, "t": tenant_id},
    )
    return overview


async def _refuse_if_any_agent_overflows(
    session: AsyncSession, tenant_id: UUID, training: str
) -> None:
    """Refuse a training with which some agent's instructions would no longer fit the
    engine's box, naming the agent, before anything is stored or sent."""
    from apps.api.agents.prompt_size import measure_config, publish_config
    from apps.api.engine import get_engine

    engine = get_engine()
    agents = (
        await session.execute(
            text(
                "SELECT id, name FROM agents WHERE deleted_at IS NULL AND archived_at IS NULL "
                "ORDER BY created_at, id"
            )
        )
    ).all()
    for agent_id, name in agents:
        try:
            cfg = await publish_config(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine=engine,
                company_training=training,
            )
        except ProblemError:
            # An agent with no script yet has nothing to measure; its first publish is
            # measured with the training then.
            continue
        size = measure_config(cfg, engine)
        if not size.fits:
            raise ProblemError.business_rule(
                "company_training_too_long",
                f"With this training, {name}'s instructions are {size.over:,} characters "
                "too long for the calling system.",
                remediation=(
                    "Shorten the training, or move product and price details into "
                    "Knowledge, which every agent searches."
                ),
            )


async def save_training(
    session: AsyncSession, tenant_id: UUID, value: str, *, saved_by: UUID | None
) -> int:
    """Save the training every agent is given and bring live agents onto it. Returns the new
    version. An empty training is allowed: agents then carry their own scripts alone."""
    from apps.api.agents.live_apply import queue_live_apply

    await _row(session, tenant_id, lock=True)
    training = _clean(value, limit=TRAINING_MAX, field="training")
    await _refuse_if_any_agent_overflows(session, tenant_id, training)
    version = (
        await session.execute(
            text(
                "UPDATE company_trainings SET training = :tr, version = version + 1, "
                "updated_by = :by, updated_at = now() WHERE tenant_id = :t RETURNING version"
            ),
            {"tr": training or None, "by": saved_by, "t": tenant_id},
        )
    ).scalar_one()
    await queue_live_apply(session, scope="tenant", tenant_id=tenant_id, reason="company_training")
    return int(version)


async def add_material(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: MaterialKind,
    title: str,
    url: str | None,
    note: str | None,
    kb_upload_id: UUID | None,
    created_by: UUID | None,
) -> Material:
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
    row = (
        await session.execute(
            text(
                "INSERT INTO company_training_materials (id, tenant_id, kind, title, url, note, "
                "kb_upload_id, created_by) VALUES (:id, :t, :k, :ti, :u, :n, :kb, :by) "
                "RETURNING id, kind, title, url, note, kb_upload_id, created_at"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "k": kind,
                "ti": title,
                "u": (url or "").strip() or None,
                "n": _clean(note or "", limit=NOTE_MAX, field="note") or None,
                "kb": kb_upload_id,
                "by": created_by,
            },
        )
    ).one()
    return Material(*row)


async def archive_material(session: AsyncSession, material_id: UUID) -> None:
    """Removing a material archives it (business data is never deleted in code)."""
    done = (
        await session.execute(
            text(
                "UPDATE company_training_materials SET archived_at = now(), updated_at = now() "
                "WHERE id = :m AND archived_at IS NULL RETURNING id"
            ),
            {"m": material_id},
        )
    ).first()
    if done is None:
        raise ProblemError.not_found("Material")


async def request_proposal(
    session: AsyncSession, *, tenant_id: UUID, requested_by: UUID | None
) -> TrainingProposal:
    """Ask Pip for the training. Needs an overview; replaces a ready draft; refused while one
    is still being written, so a second click does not spend twice."""
    row = await _row(session, tenant_id, lock=True)
    if not (row.overview or "").strip():
        raise _invalid(
            "overview_required",
            "Describe the business first",
            "Write about the business first, so Pip knows what to teach the agents.",
        )
    now = datetime.now(UTC)
    pending = _proposal(row.proposal, now=now)
    if pending is not None and pending.status == "drafting":
        raise ProblemError.conflict(
            "company_training_in_progress",
            "Pip is still writing the training.",
            remediation="Wait for it to appear, or press Stop first.",
        )
    proposal_id = uuid7()
    record: dict[str, Any] = {
        "id": str(proposal_id),
        "status": "drafting",
        "requested_at": now.isoformat(),
        "requested_by": None if requested_by is None else str(requested_by),
        "base_training": row.training,
    }
    await session.execute(
        text("UPDATE company_trainings SET proposal = CAST(:p AS jsonb) WHERE tenant_id = :t"),
        {"p": json.dumps(record), "t": tenant_id},
    )
    await enqueue_outbox(
        session,
        job=TRAINING_DRAFT_JOB,
        payload={"tenant_id": str(tenant_id), "proposal_id": str(proposal_id)},
    )
    proposal = _proposal(record, now=now)
    assert proposal is not None
    return proposal


async def clear_proposal(session: AsyncSession, tenant_id: UUID, proposal_id: UUID) -> bool:
    """Stop a draft being written, or discard / settle a written one. The job's own write is a
    compare-and-set on the id, so a stopped draft is never written back."""
    done = (
        await session.execute(
            text(
                "UPDATE company_trainings SET proposal = NULL WHERE tenant_id = :t "
                "AND proposal->>'id' = :pid RETURNING id"
            ),
            {"t": tenant_id, "pid": str(proposal_id)},
        )
    ).first()
    if done is None:
        raise ProblemError.not_found("Draft")
    return True


__all__ = [
    "FAILED_NOTE",
    "OVERVIEW_MAX",
    "TRAINING_DRAFT_JOB",
    "TRAINING_HEADER",
    "TRAINING_MAX",
    "Material",
    "Training",
    "TrainingProposal",
    "add_material",
    "archive_material",
    "clear_proposal",
    "list_materials",
    "live_text",
    "read_training",
    "request_proposal",
    "save_overview",
    "save_training",
    "training_section",
    "with_training",
]
