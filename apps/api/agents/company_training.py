"""The company training: one per client, given to every agent (founder, 16 Nov 2026).

A real calling company gives every person it hires the same overview of the business before
assigning them to work. Calevate does the same: the owner describes the business in their own
words; Pip writes the training from them, the business profile and what the agents already
know (`workers/company_training_draft.py`); the owner reviews it and saves it; every agent of
the client is then given it, ahead of its own script. It is shown as the "How they speak" tab
of What your agents know (founder, 16 Nov 2026): the knowledge holds the facts agents look up,
the training holds how they behave, and there is one place to add material for both.

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


async def read_training(session: AsyncSession, tenant_id: UUID) -> Training:
    row = await _row(session, tenant_id)
    return Training(
        overview=row.overview or "",
        training=row.training or "",
        version=int(row.version),
        updated_at=row.updated_at if row.version else None,
        proposal=_proposal(row.proposal, now=datetime.now(UTC)),
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
    engine's box, naming the agent, before anything is stored or sent. The published
    Inbound lines and the campaigns holding an engine agent are measured too: each carries
    the training over its own script (D-997, D-1003), and the save's live apply republishes
    them (`service.republish_lines`, `republish_campaign_agents`), so a line the training
    pushes over the box would otherwise fail there, after the save."""
    from apps.api.agents.prompt_size import measure_config, publish_config
    from apps.api.engine import get_engine

    engine = get_engine()
    await _refuse_if_any_job_overflows(session, tenant_id, training)
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


async def _refuse_if_any_job_overflows(
    session: AsyncSession, tenant_id: UUID, training: str
) -> None:
    """The Inbound lines and campaigns half of `_refuse_if_any_agent_overflows`: exactly the
    ones a save republishes."""
    from apps.api.agents.prompt_size import measure_config
    from apps.api.agents.service import (
        CAMPAIGN_HOLDING_STATUSES,
        _load_agent,
        campaign_config,
        line_config,
    )
    from apps.api.engine import get_engine

    engine = get_engine()
    jobs = (
        await session.execute(
            text(
                "SELECT 'line' AS kind, id, agent_id, name, created_at FROM inbound_lines "
                "WHERE archived_at IS NULL AND engine_agent_ref IS NOT NULL "
                "AND published_at IS NOT NULL AND script IS NOT NULL "
                "UNION ALL SELECT 'campaign', id, agent_id, name, created_at FROM campaigns "
                "WHERE archived_at IS NULL AND engine_agent_ref IS NOT NULL "
                "AND status = ANY(:holding) ORDER BY created_at, id"
            ),
            {"holding": list(CAMPAIGN_HOLDING_STATUSES)},
        )
    ).all()
    agents: dict[UUID, Any] = {}
    for kind, job_id, agent_id, name in (row[:4] for row in jobs):
        if agent_id not in agents:
            row = await _load_agent(session, tenant_id, agent_id)
            agents[agent_id] = {**row, "company_training": training}
        try:
            if kind == "line":
                cfg = await line_config(
                    session, tenant_id=tenant_id, line_id=job_id, agent=agents[agent_id]
                )
            else:
                cfg = await campaign_config(
                    session, tenant_id=tenant_id, campaign_id=job_id, agent=agents[agent_id]
                )
        except ProblemError:
            # Not publishable as it stands for another reason; that publish says why.
            continue
        size = measure_config(cfg, engine)
        if not size.fits:
            where = "Inbound line" if kind == "line" else "campaign"
            raise ProblemError.business_rule(
                "company_training_too_long",
                f"With this training, the script of the {where} {name} is {size.over:,} "
                "characters too long for the calling system.",
                remediation=(
                    f"Shorten the training or that {where}'s script, or move product and "
                    "price details into Knowledge, which every agent searches."
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


async def request_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    requested_by: UUID | None,
    auto_save: bool = False,
) -> TrainingProposal:
    """Ask Pip for the training. Needs an overview; replaces a ready draft; refused while one
    is still being written, so a second click does not spend twice.

    `auto_save`: the draft is saved as the training as soon as it is written, with no review,
    while no training has been saved yet (the first run's version 1, founder 16 Nov 2026)."""
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
    if auto_save:
        record["auto_save"] = True
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
    "Training",
    "TrainingProposal",
    "clear_proposal",
    "live_text",
    "read_training",
    "request_proposal",
    "save_overview",
    "save_training",
    "training_section",
    "with_training",
]
