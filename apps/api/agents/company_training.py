"""The company training: one per client, given to every agent (founder, 16 Nov 2026).

A real calling company gives every person it hires the same overview of the business before
assigning them to work. Calevate does the same: Pip writes the training from the business
profile, the client's knowledge and the owner's own words (`workers/company_training_draft.
py`), and every agent of the client is given it, ahead of its own script. It is shown as the
"How they speak" tab of What your agents know: the knowledge holds the facts agents look up,
the training holds how they behave.

WRITTEN IN THE BACKGROUND, LIVE AT ONCE (D-1034, founder 23 Nov 2026). Nobody presses a
button: the first agent's creation queues the first write, and every change to what it is
written from (a knowledge source going live or coming down, the business profile, the
owner's overview) queues a rewrite (`schedule_write`). Changes are debounced per client
(`WRITE_DEBOUNCE_S`, at most `WRITE_MAX_WAIT_S` after the first), so a burst of uploads is
one rewrite: the trailing-edge debounce with a cap that lodash's `debounce(..., {maxWait})`
names (lodash.com/docs/#debounce). What Pip writes is saved live only after its grounding
review passes; otherwise the previous training stays.

THE OWNER'S EDITS ARE KEPT. The owner can still edit and save the training. `pip_training`
holds what Pip last saved, so the live text differing from it is the owner's edits; the next
rewrite is given them as constraints it must carry (`owner_edits`), and its review checks
that each one survived. A Pip save is a compare-and-set on `version`, so a rewrite started
before an owner's save never overwrites it.

WHERE IT SITS IN THE PROMPT. Inside the client fence, as the first section of the script
(`with_training`), not as a platform layer beside it: the business's material is fenced like
everything else the business wrote (`CLIENT_SCRIPT_OPEN`), and the platform rules,
confidentiality and the truthful answers still come after it and win. Its lead sentence says
the script below wins where the two differ, so a campaign may change a company fact for its
own calls (founder, 16 Nov 2026). An agent of a client with no training composes byte for
byte as before.

A save reaches live agents through the live-apply seam (`queue_live_apply`, scope tenant), in
the transaction that saved it, and is refused first if any agent's instructions would no
longer fit the engine's box with it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Final, Literal
from uuid import UUID

from calevate_shared.engine import AgentConfig, VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompt_size import measure_config
from apps.api.core.errors import ProblemError, ProblemExtension
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox

OVERVIEW_MAX: Final = 4_000
#: The training shares the engine's 20,000-character box with the agent's script and our
#: rules; this keeps room for both.
TRAINING_MAX: Final = 6_000
#: The job that writes the training (`workers/company_training_draft.py`).
TRAINING_DRAFT_JOB: Final = "draft_company_training"
#: A change waits this long for the next one before Pip writes.
WRITE_DEBOUNCE_S: Final = 60
#: ... and never longer than this after the first change it waits with.
WRITE_MAX_WAIT_S: Final = 10 * 60
#: A write still "drafting" this long after it was taken, or still "queued" this long after
#: it was due, is shown as failed: the job died without writing. The next change replaces it.
STALE_AFTER_S: Final = 15 * 60
FAILED_NOTE: Final = "Pip could not write the training this time. Try again."

#: The script section the training is composed as. `prompt_size.SCRIPT_SECTION_LABELS` names it.
TRAINING_HEADER: Final = "[COMPANY TRAINING]"
TRAINING_LEAD: Final = (
    "Every agent of this business is trained on this. Where the script after it says "
    "something different, follow the script."
)

ProposalStatus = Literal["queued", "drafting", "failed"]
#: Why Pip writes: the client's first agent, a knowledge source going live or coming down,
#: the business profile, the owner's overview, or the owner pressing Rewrite now.
WriteReason = Literal[
    "first_agent", "knowledge_changed", "profile_changed", "owner_words", "owner_asked"
]
WRITE_REASONS: Final[tuple[str, ...]] = (
    "first_agent",
    "knowledge_changed",
    "profile_changed",
    "owner_words",
    "owner_asked",
)


@dataclass(frozen=True)
class TrainingProposal:
    """The pending background write: queued (waiting out the debounce), drafting, or failed."""

    id: UUID
    status: ProposalStatus
    requested_at: datetime
    #: When a queued write starts.
    due_at: datetime | None
    reasons: tuple[str, ...]
    note: str | None
    #: Failed: the refusal's code, `crashed`, `ungrounded`, `too_long`, or `stale` for a job
    #: that never wrote back.
    reason: str | None = None


@dataclass(frozen=True)
class LastWrite:
    """What Pip's last saved write was, for the screen."""

    at: datetime
    reasons: tuple[str, ...]
    #: The owner's edits it carried.
    owner_edits_kept: int
    #: Owner's facts newer knowledge replaced, each as the owner had written it.
    superseded: tuple[str, ...]
    #: It was shortened to fit beside the longest script.
    shortened: bool
    #: Who wrote it when it was not the account's own model (D-127 G-6).
    disclosure: str | None
    #: What the material did not state well enough to write: business, offer, customers.
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class Training:
    overview: str
    training: str
    version: int
    updated_at: datetime | None
    proposal: TrainingProposal | None
    last_write: LastWrite | None
    #: The live text holds edits Pip has not written into it yet: the owner's own.
    owner_edited: bool


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


def give_way(
    compose: Callable[[str], AgentConfig], training: str, engine: VoiceEngine
) -> AgentConfig:
    """`compose(training)`, or, when that is over the engine's instructions box, `compose` of
    the training's longest leading run of whole lines that fits, with `training_cut_chars`
    saying how much was left out.

    The training is the one part of a holder's instructions nobody wrote for that holder, so
    it gives way rather than the publish being refused: a script that fits on its own is
    never refused because the training beside it is long. Line by line from the end, since
    the training leads with the business and ends with detail. Where the script is over even
    with no training, the training is left out entirely and the publish still refuses, naming
    the script's own parts. Binary search, because each `compose` cuts the known facts to fit
    again (`hot_facts.with_known_facts`), and fitting is monotone in the lines kept.

    The cut is recorded on the route at publish (`published_training_cut_chars`) and shown to
    the owner on the training screen (`shortened_for`).
    """
    whole = compose(training)
    if not training.strip() or measure_config(whole, engine).fits:
        return whole
    full = len(training_section(training))
    lines = training.strip().splitlines()
    best = compose("")
    if not measure_config(best, engine).fits:
        return best.model_copy(update={"training_cut_chars": full})
    kept, too_many = 0, len(lines)
    while too_many - kept > 1:
        mid = (kept + too_many) // 2
        candidate = compose("\n".join(lines[:mid]))
        if measure_config(candidate, engine).fits:
            kept, best = mid, candidate
        else:
            too_many = mid
    cut = full - len(training_section("\n".join(lines[:kept])))
    return best.model_copy(update={"training_cut_chars": cut})


@dataclass(frozen=True)
class ShortenedFor:
    """A holder whose last publish left part of the training out so its instructions fit."""

    kind: Literal["line", "campaign", "test_copy", "agent"]
    holder_id: UUID | None
    agent_id: UUID
    name: str
    cut_chars: int


#: Each live engine agent whose last publish recorded a cut, named as the owner knows it.
#: Tenant session: the route table is written under the tenant and read here under it too.
_SHORTENED_SQL: Final = text(
    "SELECT CASE WHEN l.id IS NOT NULL THEN 'line' WHEN c.id IS NOT NULL THEN 'campaign' "
    "WHEN t.agent_id IS NOT NULL THEN 'test_copy' ELSE 'agent' END AS kind, "
    "COALESCE(l.id, c.id) AS holder_id, a.id AS agent_id, "
    "COALESCE(l.name, c.name, a.name) AS name, r.published_training_cut_chars AS cut "
    "FROM engine_agent_routes r JOIN agents a ON a.id = r.agent_id AND a.deleted_at IS NULL "
    "LEFT JOIN inbound_lines l ON l.engine_agent_ref = r.engine_agent_ref "
    "AND l.archived_at IS NULL "
    "LEFT JOIN campaigns c ON c.engine_agent_ref = r.engine_agent_ref AND c.archived_at IS NULL "
    "LEFT JOIN agent_test_copies t ON t.engine_agent_ref = r.engine_agent_ref "
    "WHERE r.tenant_id = :t AND r.active AND r.published_training_cut_chars > 0 "
    "AND (l.id IS NOT NULL OR c.id IS NOT NULL OR t.agent_id IS NOT NULL "
    "OR a.engine_agent_ref = r.engine_agent_ref) "
    "ORDER BY name, r.engine_agent_ref LIMIT 20"
)


async def shortened_for(session: AsyncSession, tenant_id: UUID) -> tuple[ShortenedFor, ...]:
    """The holders whose live engine agent carries a shortened training, at most 20."""
    rows = (await session.execute(_SHORTENED_SQL, {"t": tenant_id})).all()
    return tuple(
        ShortenedFor(
            kind=row.kind,
            holder_id=row.holder_id,
            agent_id=row.agent_id,
            name=str(row.name or ""),
            cut_chars=int(row.cut),
        )
        for row in rows
    )


async def live_text(session: AsyncSession) -> str:
    """The saved training of the session's client, '' when it has none. RLS scopes the read."""
    found = (
        await session.execute(text("SELECT training FROM company_trainings LIMIT 1"))
    ).scalar_one_or_none()
    return str(found or "")


# --- reading -----------------------------------------------------------------------------


def _when(raw: Any) -> datetime | None:
    return datetime.fromisoformat(str(raw)) if raw else None


def proposal_of(raw: Any, *, now: datetime) -> TrainingProposal | None:
    """The pending write a row holds, None for none. A review draft written before D-1034
    (`ready`) is no longer a state: it reads as none, and the next write replaces it."""
    if not raw or raw.get("status") not in ("queued", "drafting", "failed"):
        return None
    requested_at = datetime.fromisoformat(str(raw["requested_at"]))
    due_at = _when(raw.get("due_at"))
    status: ProposalStatus = raw["status"]
    note, reason = raw.get("note"), raw.get("reason")
    taken = _when(raw.get("claimed_at")) or requested_at
    stale = (status == "drafting" and (now - taken).total_seconds() > STALE_AFTER_S) or (
        status == "queued" and due_at is not None and (now - due_at).total_seconds() > STALE_AFTER_S
    )
    if stale:
        status, note, reason = "failed", FAILED_NOTE, "stale"
    return TrainingProposal(
        id=UUID(str(raw["id"])),
        status=status,
        requested_at=requested_at,
        due_at=due_at,
        reasons=tuple(str(r) for r in raw.get("reasons") or ()),
        note=note,
        reason=reason,
    )


def _last_write(raw: Any) -> LastWrite | None:
    if not raw or not raw.get("at"):
        return None
    return LastWrite(
        at=datetime.fromisoformat(str(raw["at"])),
        reasons=tuple(str(r) for r in raw.get("reasons") or ()),
        owner_edits_kept=int(raw.get("owner_edits_kept") or 0),
        superseded=tuple(str(s) for s in raw.get("superseded") or ()),
        shortened=bool(raw.get("shortened")),
        disclosure=raw.get("disclosure"),
        missing=tuple(str(m) for m in raw.get("missing") or ()),
    )


_ROW_SQL: Final = (
    "SELECT overview, training, proposal, version, updated_at, pip_training, owner_edits, "
    "last_write FROM company_trainings WHERE tenant_id = :t"
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
        await session.execute(text(_ROW_SQL + (" FOR UPDATE" if lock else "")), {"t": tenant_id})
    ).one()


def owner_edited(training: str, pip_training: str | None) -> bool:
    """Whether the live text holds words Pip did not write: a hand edit, or a training the
    owner wrote or kept before Pip wrote any."""
    live = training.strip()
    return bool(live) and live != (pip_training or "").strip()


async def read_training(session: AsyncSession, tenant_id: UUID) -> Training:
    row = await _row(session, tenant_id)
    return Training(
        overview=row.overview or "",
        training=row.training or "",
        version=int(row.version),
        updated_at=row.updated_at if row.version else None,
        proposal=proposal_of(row.proposal, now=datetime.now(UTC)),
        last_write=_last_write(row.last_write),
        owner_edited=owner_edited(row.training or "", row.pip_training),
    )


# --- scheduling Pip's write ----------------------------------------------------------------


async def _has_agent(session: AsyncSession, tenant_id: UUID) -> bool:
    found = await session.execute(
        text(
            "SELECT 1 FROM agents WHERE tenant_id = :t AND deleted_at IS NULL "
            "AND archived_at IS NULL LIMIT 1"
        ),
        {"t": tenant_id},
    )
    return found.first() is not None


async def _put(session: AsyncSession, tenant_id: UUID, record: dict[str, Any] | None) -> None:
    await session.execute(
        text("UPDATE company_trainings SET proposal = CAST(:p AS jsonb) WHERE tenant_id = :t"),
        {"p": None if record is None else json.dumps(record), "t": tenant_id},
    )


def _with_reason(reasons: Any, reason: str) -> list[str]:
    known = [str(r) for r in reasons or ()]
    return known if reason in known else [*known, reason]


async def _deliver(session: AsyncSession, tenant_id: UUID, proposal_id: str) -> None:
    await enqueue_outbox(
        session,
        job=TRAINING_DRAFT_JOB,
        payload={"tenant_id": str(tenant_id), "proposal_id": proposal_id},
    )


async def schedule_write(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    reason: WriteReason | str,
    at_once: bool = False,
    requested_by: UUID | None = None,
) -> TrainingProposal | None:
    """Queue Pip's write of the training, in the caller's transaction. Returns the pending
    write, or None when the client has no agent yet (there is nobody to train; the first
    agent's creation queues it).

    One write per client at a time. A change while one is queued pushes it back by
    `WRITE_DEBOUNCE_S`, never past `WRITE_MAX_WAIT_S` after the first; a change while one is
    being written is noted on it, and the job queues one more write when it finishes, so the
    change is never lost and never written twice at once. `at_once` (Rewrite now) starts it
    without waiting, and is refused while one is being written.
    """
    from apps.api.agents.live_apply import lock_tenant_target

    if reason not in WRITE_REASONS:
        raise ValueError(f"unknown company training write reason {reason!r}")
    await lock_tenant_target(session, tenant_id)
    if not at_once and not await _has_agent(session, tenant_id):
        return None
    row = await _row(session, tenant_id, lock=True)
    now = datetime.now(UTC)
    pending = proposal_of(row.proposal, now=now)
    raw: dict[str, Any] = dict(row.proposal or {})
    if pending is not None and pending.status == "drafting":
        if at_once:
            raise ProblemError.conflict(
                "company_training_in_progress",
                "Pip is writing the training now.",
                remediation="Wait for it to finish; it is saved for every agent when done.",
            )
        raw["again"] = _with_reason(raw.get("again"), reason)
        await _put(session, tenant_id, raw)
        return pending
    if pending is not None and pending.status == "queued":
        first = _when(raw.get("first_at")) or pending.requested_at
        due = (
            now
            if at_once
            else min(
                now + timedelta(seconds=WRITE_DEBOUNCE_S),
                first + timedelta(seconds=WRITE_MAX_WAIT_S),
            )
        )
        raw.update(due_at=due.isoformat(), reasons=_with_reason(raw.get("reasons"), reason))
        await _put(session, tenant_id, raw)
        if at_once:
            # The queued delivery sleeps until the old due time; this one runs now, and the
            # claim's compare-and-set lets only one of the two write.
            await _deliver(session, tenant_id, str(pending.id))
        return proposal_of(raw, now=now)
    proposal_id = str(uuid7())
    record: dict[str, Any] = {
        "id": proposal_id,
        "status": "queued",
        "requested_at": now.isoformat(),
        "first_at": now.isoformat(),
        "due_at": (now if at_once else now + timedelta(seconds=WRITE_DEBOUNCE_S)).isoformat(),
        "reasons": [reason],
        "requested_by": None if requested_by is None else str(requested_by),
    }
    await _put(session, tenant_id, record)
    await _deliver(session, tenant_id, proposal_id)
    return proposal_of(record, now=now)


async def schedule_first_write(session: AsyncSession, tenant_id: UUID) -> None:
    """An agent was made: queue the first training if the client has none yet."""
    row = await _locked(session, tenant_id)
    if int(row.version) == 0:
        await schedule_write(session, tenant_id, reason="first_agent")


async def request_rewrite(
    session: AsyncSession, *, tenant_id: UUID, requested_by: UUID | None
) -> TrainingProposal:
    """The owner's Rewrite now: the same background write, started without waiting."""
    proposal = await schedule_write(
        session, tenant_id, reason="owner_asked", at_once=True, requested_by=requested_by
    )
    assert proposal is not None
    return proposal


async def clear_proposal(session: AsyncSession, tenant_id: UUID, proposal_id: UUID) -> bool:
    """Dismiss a failed write, or stop one. The job's own writes are compare-and-sets on the
    id, so a stopped write is never saved."""
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
    """The owner's own words about the business. Pip reads them; agents do not. A change
    queues a rewrite."""
    row = await _locked(session, tenant_id)
    overview = _clean(value, limit=OVERVIEW_MAX, field="overview")
    await session.execute(
        text("UPDATE company_trainings SET overview = :o, updated_at = now() WHERE tenant_id = :t"),
        {"o": overview or None, "t": tenant_id},
    )
    if overview != (row.overview or "").strip():
        await schedule_write(session, tenant_id, reason="owner_words")
    return overview


class CompanyTrainingTooLong(ProblemExtension):
    """What the training would push past the calling system's box, so the screen can link
    straight to it. Exactly one of the three is set."""

    code: ClassVar[str] = "company_training_too_long"
    status: ClassVar[int] = 422

    agent_id: UUID | None = None
    inbound_line_id: UUID | None = None
    campaign_id: UUID | None = None


@dataclass(frozen=True)
class Overflow:
    """The first script the training would push past the engine's box, and by how much."""

    over: int
    detail: str
    remediation: str
    extension: CompanyTrainingTooLong


async def overflow_of(session: AsyncSession, tenant_id: UUID, training: str) -> Overflow | None:
    """The first agent, Inbound line or campaign whose instructions would no longer fit the
    engine's box with `training`, or None. The published Inbound lines and the campaigns
    holding an engine agent are measured too: each carries the training over its own script
    (D-997, D-1003), and a save's live apply republishes them (`service.republish_lines`,
    `republish_campaign_agents`), so a line the training pushes over the box would otherwise
    fail there, after the save.

    Measured with the whole training (`training_gives_way=False`): a publish lets the
    training give way where a script leaves it no room (`give_way`), but the owner saving it
    is told it does not fit rather than having it shortened unseen."""
    # Looked up at call time, so a test can stand in a smaller box for the save measure.
    from apps.api.agents.prompt_size import measure_config, publish_config
    from apps.api.engine import get_engine

    engine = get_engine()
    found = await _job_overflow(session, tenant_id, training)
    if found is not None:
        return found
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
                training_gives_way=False,
            )
        except ProblemError:
            # An agent with no script yet has nothing to measure; its first publish is
            # measured with the training then.
            continue
        size = measure_config(cfg, engine)
        if not size.fits:
            return Overflow(
                over=size.over,
                detail=f"With this training, {name}'s instructions are {size.over:,} "
                "characters too long for the calling system.",
                remediation=(
                    "Shorten the training, or move product and price details into "
                    "Knowledge, which every agent searches."
                ),
                extension=CompanyTrainingTooLong(agent_id=agent_id),
            )
    return None


async def _job_overflow(session: AsyncSession, tenant_id: UUID, training: str) -> Overflow | None:
    """The Inbound lines and campaigns half of `overflow_of`: exactly the ones a save
    republishes."""
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
                    session,
                    tenant_id=tenant_id,
                    line_id=job_id,
                    agent=agents[agent_id],
                    training_gives_way=False,
                )
            else:
                cfg = await campaign_config(
                    session,
                    tenant_id=tenant_id,
                    campaign_id=job_id,
                    agent=agents[agent_id],
                    training_gives_way=False,
                )
        except ProblemError:
            # Not publishable as it stands for another reason; that publish says why.
            continue
        size = measure_config(cfg, engine)
        if not size.fits:
            where = "Inbound line" if kind == "line" else "campaign"
            return Overflow(
                over=size.over,
                detail=f"With this training, the script of the {where} {name} is "
                f"{size.over:,} characters too long for the calling system.",
                remediation=(
                    f"Shorten the training or that {where}'s script, or move product and "
                    "price details into Knowledge, which every agent searches."
                ),
                extension=(
                    CompanyTrainingTooLong(inbound_line_id=job_id)
                    if kind == "line"
                    else CompanyTrainingTooLong(campaign_id=job_id)
                ),
            )
    return None


async def _refuse_if_any_agent_overflows(
    session: AsyncSession, tenant_id: UUID, training: str
) -> None:
    """Refuse a training with which some script would no longer fit the engine's box, naming
    it, before anything is stored or sent."""
    found = await overflow_of(session, tenant_id, training)
    if found is not None:
        raise ProblemError.business_rule(
            "company_training_too_long",
            found.detail,
            remediation=found.remediation,
            extensions=found.extension,
        )


async def _locked(session: AsyncSession, tenant_id: UUID) -> Any:
    """The row, locked after the client's live-apply lock, the order every writer of it takes
    (`live_apply.lock_tenant_target`)."""
    from apps.api.agents.live_apply import lock_tenant_target

    await lock_tenant_target(session, tenant_id)
    return await _row(session, tenant_id, lock=True)


async def save_training(
    session: AsyncSession,
    tenant_id: UUID,
    value: str,
    *,
    saved_by: UUID | None,
    edited_version: int | None = None,
) -> int:
    """The owner's save of the training every agent is given; brings live agents onto it.
    Returns the new version. An empty training is allowed: agents then carry their own
    scripts alone. `pip_training` is left as Pip last wrote it, which is how the next rewrite
    tells the owner's edits apart. A failed write's note is settled by it.

    `edited_version` is the version the owner's edit began from. Pip saves in the background
    while the editor may be open, so a save over a newer version is refused rather than
    silently replacing Pip's rewrite with an edit of the text before it."""
    from apps.api.agents.live_apply import queue_live_apply

    row = await _locked(session, tenant_id)
    if edited_version is not None and int(row.version) != edited_version:
        raise ProblemError.conflict(
            "company_training_changed",
            "Pip saved a new training while you were editing.",
            remediation="Copy your changes, press Cancel to see the new training, and edit "
            "that one.",
        )
    training = _clean(value, limit=TRAINING_MAX, field="training")
    await _refuse_if_any_agent_overflows(session, tenant_id, training)
    version = (
        await session.execute(
            text(
                "UPDATE company_trainings SET training = :tr, version = version + 1, "
                "updated_by = :by, updated_at = now(), proposal = CASE WHEN "
                "proposal->>'status' = 'failed' THEN NULL ELSE proposal END "
                "WHERE tenant_id = :t RETURNING version"
            ),
            {"tr": training or None, "by": saved_by, "t": tenant_id},
        )
    ).scalar_one()
    await queue_live_apply(session, scope="tenant", tenant_id=tenant_id, reason="company_training")
    return int(version)


async def save_written(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    training: str,
    base_version: int,
    owner_edits: dict[str, Any],
    last_write: dict[str, Any],
) -> int | None:
    """Pip's save: live at once, and only over the version it was written from. Returns the
    new version, or None when the owner saved in between (their text is never overwritten by
    a rewrite of what they had before). Refused like the owner's save when a script would no
    longer fit the engine's box."""
    from apps.api.agents.live_apply import queue_live_apply

    row = await _locked(session, tenant_id)
    if int(row.version) != base_version:
        return None
    cleaned = _clean(training, limit=TRAINING_MAX, field="training")
    await _refuse_if_any_agent_overflows(session, tenant_id, cleaned)
    version = (
        await session.execute(
            text(
                "UPDATE company_trainings SET training = :tr, pip_training = :tr, "
                "owner_edits = CAST(:oe AS jsonb), last_write = CAST(:lw AS jsonb), "
                "version = version + 1, updated_by = NULL, updated_at = now() "
                "WHERE tenant_id = :t RETURNING version"
            ),
            {
                "tr": cleaned,
                "oe": json.dumps(owner_edits),
                "lw": json.dumps(last_write),
                "t": tenant_id,
            },
        )
    ).scalar_one()
    await queue_live_apply(session, scope="tenant", tenant_id=tenant_id, reason="company_training")
    return int(version)


__all__ = [
    "FAILED_NOTE",
    "OVERVIEW_MAX",
    "TRAINING_DRAFT_JOB",
    "TRAINING_HEADER",
    "TRAINING_MAX",
    "WRITE_DEBOUNCE_S",
    "WRITE_MAX_WAIT_S",
    "WRITE_REASONS",
    "LastWrite",
    "Overflow",
    "Training",
    "TrainingProposal",
    "clear_proposal",
    "live_text",
    "overflow_of",
    "owner_edited",
    "proposal_of",
    "read_training",
    "request_rewrite",
    "save_overview",
    "save_training",
    "save_written",
    "schedule_first_write",
    "schedule_write",
    "training_section",
    "with_training",
]
