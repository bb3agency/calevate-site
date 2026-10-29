"""Follow-ups as the client edits them (D-940): create, edit, draft, publish, pause, resume,
turn off, start leads, stop a run, and read runs, results and the ready-made starters.

A Follow-up's `trigger` and `settings` columns and its `draft` steps are what is being
edited; `follow_up_versions` freezes all three at each publish and runs read only the
frozen copy. `draft` is NULL exactly when the steps equal the live version's, and
`has_unpublished_changes` also counts an edited trigger or settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.follow_ups import definition as d
from apps.api.follow_ups import runner
from apps.api.follow_ups.definition import Problem

#: The most leads one request starts at once (`POST /v1/follow-ups/{id}/start`).
MAX_START_LEADS: Final = 200
RESULT_DAYS: Final = 30
RUNS_PAGE_MAX: Final = 100
LIST_MAX: Final = 200


# --- errors --------------------------------------------------------------------------


class FollowUpInvalidError(ProblemError):
    """422 `follow_up_invalid`, carrying every problem so the screen (and Pip) can list them."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(
            kind="validation",
            code="follow_up_invalid",
            title="This follow-up cannot be published yet",
            detail=problems[0].message
            if len(problems) == 1
            else (f"{len(problems)} things need fixing before it can be published."),
            remediation="Fix each step listed, then publish again.",
            status=422,
        )
        self.problems = problems

    def as_problem(self, instance: str | None = None) -> dict[str, Any]:
        body = super().as_problem(instance)
        body["problems"] = [
            {"step_id": p.step_id, "code": p.code, "message": p.message} for p in self.problems
        ]
        return body


class FollowUpChangedError(ProblemError):
    """409 `follow_up_changed`: somebody saved it since the screen loaded it."""

    def __init__(self, updated_at: datetime) -> None:
        super().__init__(
            kind="conflict",
            code="follow_up_changed",
            title="This follow-up changed",
            detail="Someone changed this follow-up since you opened it, so it was not published.",
            remediation="Look at the latest version, then publish again.",
        )
        self.updated_at = updated_at

    def as_problem(self, instance: str | None = None) -> dict[str, Any]:
        body = super().as_problem(instance)
        body["expected_updated_at"] = self.updated_at.isoformat()
        return body


def _not_live(detail: str) -> ProblemError:
    return ProblemError.conflict("follow_up_not_live", detail)


def _overlap_problem() -> ProblemError:
    return ProblemError.conflict(
        "follow_up_trigger_overlap",
        "Another follow-up already starts for new leads from these sources.",
        remediation="Pause or turn off the other one first, or choose different sources.",
    )


# --- reading -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Row:
    id: UUID
    name: str
    status: str
    starter: str | None
    trigger: d.AnyTrigger
    settings: d.Settings
    steps: list[d.AnyStep]
    draft: list[d.AnyStep] | None
    live_version_id: UUID | None
    live_number: int | None
    live_published_at: datetime | None
    live_trigger: dict[str, Any] | None
    live_settings: dict[str, Any] | None
    updated_at: datetime

    @property
    def has_unpublished_changes(self) -> bool:
        return (
            self.live_version_id is None
            or self.draft is not None
            or self.live_trigger != d.dump_trigger(self.trigger)
            or self.live_settings != d.dump_settings(self.settings)
        )


_ROW_SQL: Final = (
    "SELECT f.id, f.name, f.status, f.starter, f.trigger, f.settings, f.draft, "
    "f.live_version_id, v.number, v.published_at, v.trigger, v.settings, v.steps, f.updated_at "
    "FROM follow_ups f LEFT JOIN follow_up_versions v ON v.id = f.live_version_id "
)


def _row(r: Any) -> Row:
    draft = d.load_steps(r[6]) if r[6] is not None else None
    live_steps = d.load_steps(r[12]) if r[12] is not None else []
    return Row(
        id=UUID(str(r[0])),
        name=str(r[1]),
        status=str(r[2]),
        starter=r[3],
        trigger=d.load_trigger(r[4]),
        settings=d.load_settings(r[5]),
        steps=draft if draft is not None else live_steps,
        draft=draft,
        live_version_id=UUID(str(r[7])) if r[7] is not None else None,
        live_number=r[8],
        live_published_at=r[9],
        live_trigger=r[10],
        live_settings=r[11],
        updated_at=r[13],
    )


async def get(session: AsyncSession, follow_up_id: UUID, *, lock: bool = False) -> Row:
    found = (
        await session.execute(
            text(_ROW_SQL + "WHERE f.id = :fid" + (" FOR UPDATE OF f" if lock else "")),
            {"fid": follow_up_id},
        )
    ).first()
    if found is None:
        raise ProblemError.not_found("Follow-up")
    return _row(found)


async def list_all(session: AsyncSession, *, limit: int = LIST_MAX) -> list[Row]:
    rows = (
        await session.execute(
            text(_ROW_SQL + "ORDER BY f.created_at, f.id LIMIT :n"), {"n": min(limit, LIST_MAX)}
        )
    ).all()
    return [_row(r) for r in rows]


@dataclass(frozen=True, slots=True)
class Counts:
    running: int
    waiting: int
    done_30d: int
    goal_30d: int


async def counts(session: AsyncSession, follow_up_ids: list[UUID]) -> dict[UUID, Counts]:
    if not follow_up_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT follow_up_id, count(*) FILTER (WHERE status = 'running'), "
                "count(*) FILTER (WHERE status = 'waiting'), "
                "count(*) FILTER (WHERE status = 'done' AND ended_at > :since), "
                "count(*) FILTER (WHERE goal_reached AND ended_at > :since) "
                "FROM follow_up_runs WHERE follow_up_id = ANY(:ids) "
                "AND (status IN ('running', 'waiting') OR ended_at > :since) "
                "GROUP BY follow_up_id"
            ),
            {"ids": follow_up_ids, "since": datetime.now(UTC) - timedelta(days=RESULT_DAYS)},
        )
    ).all()
    found = {UUID(str(r[0])): Counts(int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in rows}
    return {fid: found.get(fid, Counts(0, 0, 0, 0)) for fid in follow_up_ids}


async def _pairs(session: AsyncSession, sql: str) -> dict[UUID, str]:
    return {UUID(str(r[0])): str(r[1] or "") for r in (await session.execute(text(sql))).all()}


async def names(session: AsyncSession) -> d.Names:
    """Display names for every id a step can name, for the step summaries."""
    return d.Names(
        agents=await _pairs(session, "SELECT id, name FROM agents WHERE deleted_at IS NULL"),
        templates=await _pairs(session, "SELECT id, name FROM whatsapp_templates"),
        users=await _pairs(
            session,
            "SELECT u.id, coalesce(u.name, u.email) FROM memberships m "
            "JOIN users u ON u.id = m.user_id",
        ),
        actions=await _pairs(session, "SELECT id, name FROM action_tools"),
    )


# --- the problems a publish refuses ---------------------------------------------------


async def _exists(session: AsyncSession, sql: str, params: dict[str, Any]) -> bool:
    return (await session.execute(text(sql), params)).first() is not None


async def _call_problems(session: AsyncSession, step: d.CallStep) -> list[Problem]:
    if step.agent_id is None:
        return []
    row = (
        await session.execute(
            text(
                "SELECT direction, engine_agent_ref FROM agents WHERE id = :aid "
                "AND deleted_at IS NULL AND archived_at IS NULL"
            ),
            {"aid": step.agent_id},
        )
    ).first()
    if row is None:
        return [Problem(step.id, "agent_unknown", "Choose an agent of this account.")]
    if str(row[0]) not in ("outbound", "both"):
        return [
            Problem(
                step.id,
                "agent_cannot_call",
                "This agent only answers calls. Choose one that calls.",
            )
        ]
    if not row[1]:
        return [Problem(step.id, "agent_not_published", "Publish this agent before it can call.")]
    return []


async def _whatsapp_problems(session: AsyncSession, step: d.WhatsAppStep) -> list[Problem]:
    from apps.api.whatsapp import templates

    row = (
        await session.execute(
            text("SELECT body FROM whatsapp_templates WHERE id = :tid AND status = 'approved'"),
            {"tid": step.template_id},
        )
    ).first()
    if row is None:
        return [Problem(step.id, "template_unknown", "Choose an approved WhatsApp message.")]
    wanted = len(set(templates.blanks(str(row[0]))))
    if wanted != len(step.values):
        return [
            Problem(
                step.id,
                "template_values",
                f"This message has {wanted} blank(s); say what fills each one.",
            )
        ]
    return []


async def problems_of(
    session: AsyncSession, trigger: d.AnyTrigger, steps: list[d.AnyStep], settings: d.Settings
) -> list[Problem]:
    """Every reason this definition cannot be published, in step order."""
    problems = d.shape_problems(trigger, steps, settings)
    if isinstance(trigger, d.NewLeadTrigger) and trigger.source_ids:
        for source_id in trigger.source_ids:
            if not await _exists(
                session, "SELECT 1 FROM inbound_webhooks WHERE id = :id", {"id": source_id}
            ):
                problems.append(Problem(None, "source_unknown", "A lead source was not found."))
    if isinstance(trigger, d.CallEndedTrigger) and trigger.agent_ids:
        for agent_id in trigger.agent_ids:
            if not await _exists(
                session,
                "SELECT 1 FROM agents WHERE id = :id AND deleted_at IS NULL",
                {"id": agent_id},
            ):
                problems.append(Problem(None, "agent_unknown", "An agent was not found."))
    for step in steps:
        if isinstance(step, d.CallStep):
            problems.extend(await _call_problems(session, step))
        elif isinstance(step, d.WhatsAppStep):
            problems.extend(await _whatsapp_problems(session, step))
        elif isinstance(step, d.AssignStep) and not await _exists(
            session,
            "SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.user_id = :uid AND u.deactivated_at IS NULL",
            {"uid": step.user_id},
        ):
            problems.append(Problem(step.id, "teammate_unknown", "Choose someone on your team."))
        elif isinstance(step, d.TellTeamStep) and not await _exists(
            session,
            "SELECT 1 FROM team_alert_contacts WHERE removed_at IS NULL AND verified_at IS NOT "
            "NULL AND (CASE WHEN CAST(:cid AS uuid) IS NULL THEN is_default "
            "ELSE id = CAST(:cid AS uuid) END)",
            {"cid": step.contact_id},
        ):
            problems.append(
                Problem(step.id, "team_address_missing", "Add and confirm a team address first.")
            )
        elif isinstance(step, d.ActionStep) and not await _exists(
            session, "SELECT 1 FROM action_tools WHERE id = :id AND enabled", {"id": step.action_id}
        ):
            problems.append(Problem(step.id, "action_unknown", "Choose an action that is on."))
    return problems


# --- writing -------------------------------------------------------------------------


def _json(value: Any) -> str:
    import json

    return json.dumps(value)


async def create(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
    trigger: d.AnyTrigger,
    steps: list[d.AnyStep],
    settings: d.Settings | None,
    starter: str | None,
    user_id: UUID | None,
) -> Row:
    """A new Follow-up, as a draft. Nothing runs until it is published."""
    follow_up_id = uuid7()
    if starter == "call_new_leads" and await _exists(
        session, "SELECT 1 FROM follow_ups WHERE starter = 'call_new_leads'", {}
    ):
        raise ProblemError.conflict(
            "follow_up_starter_exists",
            "This account already has Call new leads.",
            remediation="Open it from the list instead.",
        )
    await session.execute(
        text(
            "INSERT INTO follow_ups (id, tenant_id, name, status, trigger, settings, draft, "
            "starter, created_by) VALUES (:id, :tid, :name, 'draft', CAST(:trigger AS jsonb), "
            "CAST(:settings AS jsonb), CAST(:draft AS jsonb), :starter, :by)"
        ),
        {
            "id": follow_up_id,
            "tid": tenant_id,
            "name": name.strip(),
            "trigger": _json(d.dump_trigger(trigger)),
            "settings": _json(d.dump_settings(settings or d.Settings())),
            "draft": _json(d.dump_steps(steps)),
            "starter": starter,
            "by": user_id,
        },
    )
    return await get(session, follow_up_id)


async def _write_draft(
    session: AsyncSession,
    row: Row,
    *,
    name: str | None = None,
    trigger: d.AnyTrigger | None = None,
    steps: list[d.AnyStep] | None = None,
    settings: d.Settings | None = None,
) -> Row:
    live_steps: list[d.AnyStep] = []
    if row.live_version_id is not None:
        live_steps = (await runner.version(session, row.live_version_id)).steps
    new_steps = steps if steps is not None else row.steps
    same = row.live_version_id is not None and d.dump_steps(new_steps) == d.dump_steps(live_steps)
    await session.execute(
        text(
            "UPDATE follow_ups SET name = :name, trigger = CAST(:trigger AS jsonb), "
            "settings = CAST(:settings AS jsonb), draft = CAST(:draft AS jsonb), "
            "updated_at = now() WHERE id = :fid"
        ),
        {
            "fid": row.id,
            "name": (name if name is not None else row.name).strip(),
            "trigger": _json(d.dump_trigger(trigger or row.trigger)),
            "settings": _json(d.dump_settings(settings or row.settings)),
            "draft": None if same else _json(d.dump_steps(new_steps)),
        },
    )
    return await get(session, row.id)


async def save_draft(
    session: AsyncSession,
    follow_up_id: UUID,
    *,
    trigger: d.AnyTrigger,
    steps: list[d.AnyStep],
    settings: d.Settings,
) -> Row:
    """Pip's full rewrite: the trigger, steps and settings, as a draft."""
    row = await get(session, follow_up_id, lock=True)
    return await _write_draft(session, row, trigger=trigger, steps=steps, settings=settings)


@dataclass(frozen=True, slots=True)
class StepEdit:
    step_id: str
    wait_minutes: int | None = None
    template_id: UUID | None = None
    values: list[d.TemplateValue] | None = None
    agent_id: UUID | None = None
    remove: bool = False


def _refuse_edit(step_id: str, detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="follow_up_edit_invalid",
        title="That change does not fit this step",
        detail=detail,
        fields=[{"field": f"step_edits.{step_id}", "rule": "invalid", "message": detail}],
        remediation="Ask Pip to change it.",
    )


def _apply_edit(steps: list[d.AnyStep], edit: StepEdit) -> list[d.AnyStep]:
    step = d.step_by_id(steps, edit.step_id)
    if step is None:
        raise _refuse_edit(edit.step_id, "That step is not in this follow-up.")
    if edit.remove:
        targets = {t for t in d.exits_of(step).values() if t is not None}
        onward = targets.pop() if len(targets) == 1 else None
        kept: list[d.AnyStep] = []
        for other in steps:
            if other.id == step.id:
                continue
            raw = other.model_dump(mode="json")
            _repoint(raw, step.id, onward)
            kept.append(d.load_steps([raw])[0])
        return kept
    changes: dict[str, Any] = {}
    if edit.wait_minutes is not None:
        if isinstance(step, d.CallStep):
            if edit.wait_minutes > d.CALL_WAIT_MAX_MINUTES:
                raise _refuse_edit(step.id, "A call waits at most a day before its first try.")
            changes |= {"wait_minutes": edit.wait_minutes, "wait_seconds": None}
        elif isinstance(step, d.WaitStep) and step.until_field is None:
            if not 1 <= edit.wait_minutes <= d.WAIT_MAX_DAYS * 1440:
                raise _refuse_edit(step.id, "Wait between a minute and 30 days.")
            changes |= {"minutes": edit.wait_minutes, "hours": None, "days": None}
        else:
            raise _refuse_edit(step.id, "This step has no wait to change.")
    if edit.agent_id is not None:
        if not isinstance(step, d.CallStep):
            raise _refuse_edit(step.id, "Only a call step has an agent.")
        changes["agent_id"] = edit.agent_id
    if edit.template_id is not None or edit.values is not None:
        if not isinstance(step, d.WhatsAppStep):
            raise _refuse_edit(step.id, "Only a WhatsApp step has a message.")
        if edit.template_id is not None:
            changes["template_id"] = edit.template_id
        if edit.values is not None:
            changes["values"] = edit.values
    if not changes:
        return steps
    updated = d.load_steps([{**step.model_dump(mode="json"), **_jsonable(changes)}])[0]
    return [updated if s.id == step.id else s for s in steps]


def _jsonable(changes: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in changes.items():
        if isinstance(value, UUID):
            out[key] = str(value)
        elif isinstance(value, list):
            out[key] = [v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in value]
        else:
            out[key] = value
    return out


def _repoint(raw: dict[str, Any], gone: str, onward: str | None) -> None:
    """Exits that led to a removed step lead where that step led."""
    for key in ("next", "other"):
        if raw.get(key) == gone:
            raw[key] = onward
    for key in ("next", "on"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            for exit_name, target in nested.items():
                if target == gone:
                    nested[exit_name] = onward


async def edit(
    session: AsyncSession,
    follow_up_id: UUID,
    *,
    name: str | None,
    step_edits: list[StepEdit],
    settings: d.Settings | None,
) -> Row:
    """The small edits a client makes without Pip; they change the draft."""
    row = await get(session, follow_up_id, lock=True)
    steps = row.steps
    for change in step_edits:
        steps = _apply_edit(steps, change)
    return await _write_draft(session, row, name=name, steps=steps, settings=settings)


async def _overlap(session: AsyncSession, row: Row, trigger: d.AnyTrigger) -> bool:
    """Would this Follow-up, live, start a new lead another live one also starts?"""
    if not isinstance(trigger, d.NewLeadTrigger):
        return False
    for other in await runner.live_follow_ups(session, "new_lead"):
        if other.id == row.id:
            continue
        theirs = other.trigger
        assert isinstance(theirs, d.NewLeadTrigger)
        if trigger.source_ids is None or theirs.source_ids is None:
            return True
        if set(trigger.source_ids) & set(theirs.source_ids):
            return True
    return False


async def _lock_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    # Two publishes of overlapping new-lead triggers must not both pass the overlap check.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"follow-up-trigger:{tenant_id}"},
    )


async def publish(
    session: AsyncSession,
    follow_up_id: UUID,
    *,
    tenant_id: UUID,
    expected_updated_at: datetime,
    user_id: UUID | None,
) -> Row:
    """Freeze the draft as the next version and make it live (a paused one stays paused).
    Runs already going keep their version."""
    await _lock_tenant(session, tenant_id)
    row = await get(session, follow_up_id, lock=True)
    if row.updated_at != expected_updated_at:
        raise FollowUpChangedError(row.updated_at)
    if not row.has_unpublished_changes:
        return row
    problems = await problems_of(session, row.trigger, row.steps, row.settings)
    if problems:
        raise FollowUpInvalidError(problems)
    becomes_live = row.status in ("draft", "live", "off")
    if becomes_live and await _overlap(session, row, row.trigger):
        raise _overlap_problem()
    number = int(
        (
            await session.execute(
                text(
                    "SELECT coalesce(max(number), 0) + 1 FROM follow_up_versions "
                    "WHERE follow_up_id = :fid"
                ),
                {"fid": row.id},
            )
        ).scalar()
        or 1
    )
    version_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO follow_up_versions (id, tenant_id, follow_up_id, number, steps, trigger, "
            "settings, published_by) VALUES (:id, :tid, :fid, :n, CAST(:steps AS jsonb), "
            "CAST(:trigger AS jsonb), CAST(:settings AS jsonb), :by)"
        ),
        {
            "id": version_id,
            "tid": tenant_id,
            "fid": row.id,
            "n": number,
            "steps": _json(d.dump_steps(row.steps)),
            "trigger": _json(d.dump_trigger(row.trigger)),
            "settings": _json(d.dump_settings(row.settings)),
            "by": user_id,
        },
    )
    await session.execute(
        text(
            "UPDATE follow_ups SET live_version_id = :vid, draft = NULL, "
            "status = CASE WHEN status = 'paused' THEN 'paused' ELSE 'live' END, "
            "updated_at = now() WHERE id = :fid"
        ),
        {"vid": version_id, "fid": row.id},
    )
    return await get(session, row.id)


async def pause(session: AsyncSession, follow_up_id: UUID) -> Row:
    """Runs wait where they are; a call already booked is called off and booked again on
    resume."""
    row = await get(session, follow_up_id, lock=True)
    if row.status != "live":
        raise _not_live("Only a follow-up that is on can be paused.")
    await session.execute(
        text("UPDATE follow_ups SET status = 'paused', updated_at = now() WHERE id = :fid"),
        {"fid": row.id},
    )
    run_ids = (
        (
            await session.execute(
                text(
                    "SELECT id FROM follow_up_runs WHERE follow_up_id = :fid "
                    "AND status IN ('running', 'waiting')"
                ),
                {"fid": row.id},
            )
        )
        .scalars()
        .all()
    )
    await runner.cancel_callbacks(
        session, [UUID(str(r)) for r in run_ids], reason=runner.PAUSED_SENTENCE
    )
    return await get(session, row.id)


async def resume(session: AsyncSession, follow_up_id: UUID, *, tenant_id: UUID) -> Row:
    """Back on (from paused or off). A run whose call was called off by the pause is booked
    again at once (`runner._book_call_step` books a fresh key for a step booked before)."""
    await _lock_tenant(session, tenant_id)
    row = await get(session, follow_up_id, lock=True)
    if row.status not in ("paused", "off"):
        raise _not_live("Only a paused or turned-off follow-up can be turned back on.")
    if row.live_version_id is None:
        raise _not_live("Publish this follow-up first.")
    live = await runner.version(session, row.live_version_id)
    if await _overlap(session, row, live.trigger):
        raise _overlap_problem()
    await session.execute(
        text("UPDATE follow_ups SET status = 'live', updated_at = now() WHERE id = :fid"),
        {"fid": row.id},
    )
    await session.execute(
        text(
            "UPDATE follow_up_runs r SET wake_at = now(), updated_at = now() "
            "WHERE r.follow_up_id = :fid AND r.status = 'waiting' AND r.wake_at IS NULL "
            "AND r.waiting_call_id IS NULL AND NOT EXISTS (SELECT 1 FROM scheduled_callbacks c "
            "WHERE c.status IN ('scheduled', 'dialing') AND "
            "left(c.source_execution_id, 10) = 'follow-up:' AND "
            "split_part(c.source_execution_id, ':', 2) = r.id::text) "
            "AND NOT EXISTS (SELECT 1 FROM follow_up_run_events e WHERE e.run_id = r.id "
            "AND e.step_id = r.step_id AND e.kind = 'held')"
        ),
        {"fid": row.id},
    )
    return await get(session, row.id)


async def turn_off(session: AsyncSession, follow_up_id: UUID) -> Row:
    """Off: no new runs, and every run going stops (`follow_up_off`)."""
    row = await get(session, follow_up_id, lock=True)
    if row.status not in ("live", "paused"):
        raise _not_live("This follow-up is not on.")
    await session.execute(
        text("UPDATE follow_ups SET status = 'off', updated_at = now() WHERE id = :fid"),
        {"fid": row.id},
    )
    await runner.stop_runs(
        session, where="r.follow_up_id = :fid", params={"fid": row.id}, reason="follow_up_off"
    )
    return await get(session, row.id)


# --- starting leads ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StartOutcome:
    started: int
    skipped: int


async def start_leads(
    session: AsyncSession,
    follow_up_id: UUID,
    *,
    tenant_id: UUID,
    lead_ids: list[UUID],
) -> StartOutcome:
    """Put picked leads into a live Follow-up. A lead already in it, deleted, or refused by
    its `again` rule is skipped."""
    row = await get(session, follow_up_id)
    if row.status != "live" or row.live_version_id is None:
        raise _not_live("Turn this follow-up on before starting leads.")
    live = await runner.version(session, row.live_version_id)
    leads = (
        await session.execute(
            text("SELECT id, phone_e164 FROM leads WHERE id = ANY(:ids) AND deleted_at IS NULL"),
            {"ids": lead_ids},
        )
    ).all()
    start_id = uuid7()
    started = 0
    for lead_id, phone in leads:
        result = await runner.start_run(
            session,
            tenant_id=tenant_id,
            follow_up=live,
            lead_id=UUID(str(lead_id)),
            phone_e164=str(phone),
            trigger_ref=f"manual:{start_id}",
        )
        started += result.run is not None
    return StartOutcome(started=started, skipped=len(set(lead_ids)) - started)


async def stop_run(session: AsyncSession, follow_up_id: UUID, run_id: UUID) -> None:
    owner = (
        await session.execute(
            text("SELECT follow_up_id FROM follow_up_runs WHERE id = :rid"), {"rid": run_id}
        )
    ).scalar()
    if owner is None or UUID(str(owner)) != follow_up_id:
        raise ProblemError.not_found("Run")
    if not await runner.end_run(session, run_id, reason="stopped_by_client"):
        raise ProblemError.conflict(
            "follow_up_run_not_running", "This lead is no longer going through this follow-up."
        )


# --- runs and results ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunView:
    id: UUID
    lead_id: UUID | None
    lead_name: str | None
    status: str
    step_id: str
    attempt: int
    wake_at: datetime | None
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    goal_reached: bool
    last_result: str | None


_RUN_VIEW_SQL: Final = (
    "SELECT r.id, r.lead_id, l.name, r.status, r.step_id, r.attempt, r.wake_at, r.started_at, "
    "r.ended_at, r.end_reason, r.goal_reached, (SELECT e.result FROM follow_up_run_events e "
    "WHERE e.run_id = r.id ORDER BY e.at DESC, e.id DESC LIMIT 1) "
    "FROM follow_up_runs r LEFT JOIN leads l ON l.id = r.lead_id AND l.deleted_at IS NULL "
)


def _run_view(r: Any) -> RunView:
    return RunView(
        id=UUID(str(r[0])),
        lead_id=UUID(str(r[1])) if r[1] is not None else None,
        lead_name=r[2],
        status=str(r[3]),
        step_id=str(r[4]),
        attempt=int(r[5]),
        wake_at=r[6],
        started_at=r[7],
        ended_at=r[8],
        end_reason=r[9],
        goal_reached=bool(r[10]),
        last_result=r[11],
    )


async def run_steps(session: AsyncSession, run_ids: list[UUID]) -> dict[UUID, list[d.AnyStep]]:
    """Each run's own version's steps (a run keeps the version it started on)."""
    if not run_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT r.id, v.steps FROM follow_up_runs r "
                "JOIN follow_up_versions v ON v.id = r.version_id WHERE r.id = ANY(:ids)"
            ),
            {"ids": run_ids},
        )
    ).all()
    return {UUID(str(r[0])): d.load_steps(r[1]) for r in rows}


def encode_cursor(view: RunView) -> str:
    return f"{view.started_at.isoformat()}|{view.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        at, _, rid = cursor.partition("|")
        return datetime.fromisoformat(at), UUID(rid)
    except ValueError as exc:
        raise ProblemError(
            kind="validation",
            code="cursor_invalid",
            title="That page link is not valid",
            detail="Reload the list.",
        ) from exc


async def list_runs(
    session: AsyncSession,
    follow_up_id: UUID,
    *,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[RunView], str | None]:
    await get(session, follow_up_id)
    clauses = ["r.follow_up_id = :fid"]
    params: dict[str, Any] = {"fid": follow_up_id, "n": min(limit, RUNS_PAGE_MAX) + 1}
    if status is not None:
        clauses.append("r.status = :status")
        params["status"] = status
    if cursor:
        at, rid = _decode_cursor(cursor)
        clauses.append("(r.started_at, r.id) < (:at, :rid)")
        params |= {"at": at, "rid": rid}
    rows = (
        await session.execute(
            text(
                _RUN_VIEW_SQL
                + "WHERE "
                + " AND ".join(clauses)
                + " ORDER BY r.started_at DESC, r.id DESC LIMIT :n"
            ),
            params,
        )
    ).all()
    views = [_run_view(r) for r in rows]
    page = views[: params["n"] - 1]
    return page, encode_cursor(page[-1]) if len(views) > len(page) else None


@dataclass(frozen=True, slots=True)
class EventView:
    step_id: str
    kind: str
    result: str
    at: datetime
    call_id: UUID | None


async def get_run(
    session: AsyncSession, follow_up_id: UUID, run_id: UUID
) -> tuple[RunView, list[EventView]]:
    row = (
        await session.execute(
            text(_RUN_VIEW_SQL + "WHERE r.id = :rid AND r.follow_up_id = :fid"),
            {"rid": run_id, "fid": follow_up_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Run")
    events = (
        await session.execute(
            text(
                "SELECT step_id, kind, result, at, call_id FROM follow_up_run_events "
                "WHERE run_id = :rid ORDER BY at, id"
            ),
            {"rid": run_id},
        )
    ).all()
    return _run_view(row), [
        EventView(str(e[0]), str(e[1]), str(e[2]), e[3], UUID(str(e[4])) if e[4] else None)
        for e in events
    ]


@dataclass(frozen=True, slots=True)
class StepResults:
    step_id: str
    reached: int
    exits: dict[str, int]


@dataclass(frozen=True, slots=True)
class Results:
    started: int
    finished: int
    goal_reached: int
    steps: list[StepResults]


#: Event kinds that are a step's outcome (the rest mark progress: start, booked, held, ...).
_OUTCOME_KINDS: Final = (
    "call",
    "decide",
    "wait",
    "whatsapp",
    "assign",
    "set_status",
    "tell_team",
    "action",
    "end",
)


def _exit_of(kind: str, result: str) -> str:
    if kind == "call":
        return "answered" if result == "answered" else "not_reached"
    if kind == "decide":
        return result.removeprefix("branch:")
    if kind == "whatsapp":
        return "sent" if result == "sent" else "not_sent"
    if kind == "action":
        return "done" if result == "done" else "failed"
    return "next"


async def results(session: AsyncSession, follow_up_id: UUID) -> Results:
    row = await get(session, follow_up_id)
    since = datetime.now(UTC) - timedelta(days=RESULT_DAYS)
    totals = (
        await session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE status = 'done'), "
                "count(*) FILTER (WHERE goal_reached) FROM follow_up_runs "
                "WHERE follow_up_id = :fid AND started_at > :since"
            ),
            {"fid": follow_up_id, "since": since},
        )
    ).one()
    events = (
        await session.execute(
            text(
                "SELECT e.step_id, e.kind, e.result, count(DISTINCT e.run_id), count(*) "
                "FROM follow_up_run_events e JOIN follow_up_runs r ON r.id = e.run_id "
                "WHERE r.follow_up_id = :fid AND r.started_at > :since "
                "AND e.kind = ANY(:kinds) GROUP BY e.step_id, e.kind, e.result"
            ),
            {"fid": follow_up_id, "since": since, "kinds": list(_OUTCOME_KINDS)},
        )
    ).all()
    per_step: dict[str, dict[str, int]] = {}
    reached: dict[str, int] = {}
    for step_id, kind, result, runs, n in events:
        exits = per_step.setdefault(str(step_id), {})
        name = _exit_of(str(kind), str(result))
        exits[name] = exits.get(name, 0) + int(n)
        reached[str(step_id)] = max(reached.get(str(step_id), 0), int(runs))
    return Results(
        started=int(totals[0]),
        finished=int(totals[1]),
        goal_reached=int(totals[2]),
        steps=[StepResults(s.id, reached.get(s.id, 0), per_step.get(s.id, {})) for s in row.steps],
    )


__all__ = [
    "LIST_MAX",
    "MAX_START_LEADS",
    "RESULT_DAYS",
    "RUNS_PAGE_MAX",
    "Counts",
    "EventView",
    "FollowUpChangedError",
    "FollowUpInvalidError",
    "Results",
    "Row",
    "RunView",
    "StartOutcome",
    "StepEdit",
    "counts",
    "create",
    "edit",
    "get",
    "get_run",
    "list_all",
    "list_runs",
    "names",
    "pause",
    "problems_of",
    "publish",
    "results",
    "resume",
    "save_draft",
    "start_leads",
    "stop_run",
    "turn_off",
]
