"""Plans: one card, one click, exact execution (D-893 F3, PIP-AGENT-PLAN §3).

An action that touches a SET (many leads, many calls) is not confirmed target by target and
not run from the conversation. It becomes a plan: the targets are frozen server-side when
the plan is built, the people it leaves out are recorded with the reason, the cost is
estimated, and a SHA-256 over all of it is what an approval binds (`plan_hash`). Approving
runs exactly those targets in a worker (`run_copilot_plan`), each one re-checked against the
world at that moment; a target that no longer qualifies is skipped with a reason, never
swapped for another.

Why a table and not a signed token like `write_tools` proposals: a set has no size limit
(founder, 26 Oct 2026), so it cannot ride in a JWT, and the model must never carry it
(§2a). The plan row is the proposal; the confirm token signs its id and hash.

HOW A TOOL BECOMES PLAN-BACKED. `set_action_tool(...)` builds an `ActionTool` whose
planner builds the plan and whose executor approves it, so `plan_write`, `confirm`,
`stage_for_approval` and `approve` (the Approvals inbox) work unchanged. A tool supplies a
`SetAction`: `prepare` (model arguments -> the ordered targets, the lens as a person reads
it, and the canonical change), `exclude` (who is left out and why, with the checks dispatch
uses), `estimate` (Decimal INR from attested rates, or "not known") and either `run_one`
(one target, inside its own transaction) or `dial` (a pip campaign over the targets, so
the line limit, pacing, calling hours and retries of a campaign apply).

THE PLANNER WRITES, and that is the one departure from `actions.Plan`'s "produced by a read".
What it writes is the proposal itself — rows nothing acts on until a person approves them,
which expire — not a change to the account.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.display import display_inr
from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
)
from apps.api.copilot.plan_models import MAX_TARGET_REASON, PlanOrigin, TargetType
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import Permission
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The worker job that runs an approved plan (`apps/workers/copilot_plans.py`).
RUN_PLAN_JOB: Final = "run_copilot_plan"

#: How long a proposed plan waits for its approval: the Approvals inbox's own window
#: (`action_log.APPROVAL_TTL`). An interactive card's token expires sooner (5 minutes).
PLAN_TTL: Final = timedelta(hours=24)

#: Targets per transaction in the worker: progress is visible and a cancel is honoured at
#: least this often.
BATCH: Final = 25

#: How many target rows one read returns.
MAX_TARGET_PAGE: Final = 100

TargetVerdict = Literal["done", "skipped", "failed"]


@dataclass(frozen=True, slots=True)
class Prepared:
    """What `SetAction.prepare` resolved from the model's (or the screen's) arguments."""

    #: The targets, in the order they will run. Frozen into the plan.
    targets: Sequence[UUID]
    #: Which rows, in the words a person reads on the card ("leads stage hot, ...").
    lens_text: str
    title: str
    #: Why, in one sentence ("mark them contacted").
    why: str
    #: The canonical change every target gets (ids, statuses, times — never a caller's data).
    change: dict[str, Any]
    #: When it runs; None is "as soon as it is approved".
    run_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Estimate:
    """`inr` None means "not known", never zero; `note` says how it was reached."""

    inr: Decimal | None
    note: str


NO_COST: Final = Estimate(inr=Decimal("0"), note="This costs nothing.")


@dataclass(frozen=True, slots=True)
class TargetOutcome:
    status: TargetVerdict
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DialStart:
    """A dialling plan's campaign, and what happened to each target when it was added."""

    campaign_id: UUID
    outcomes: Mapping[UUID, TargetOutcome]


Preparer = Callable[[AsyncSession, ToolActor, Mapping[str, Any]], Awaitable[Prepared]]
Excluder = Callable[
    [AsyncSession, ToolActor, Mapping[str, Any], Sequence[UUID]], Awaitable[dict[UUID, str]]
]
Estimator = Callable[[AsyncSession, ToolActor, Mapping[str, Any], int], Awaitable[Estimate]]
RunOne = Callable[[AsyncSession, ToolActor, Mapping[str, Any], UUID], Awaitable[TargetOutcome]]
Dialler = Callable[
    [AsyncSession, ToolActor, Mapping[str, Any], str, Sequence[UUID]], Awaitable[DialStart]
]


@dataclass(frozen=True, slots=True)
class SetAction:
    """How one set action prepares, excludes, estimates and runs (module docstring)."""

    target_type: TargetType
    prepare: Preparer
    exclude: Excluder
    estimate: Estimator
    run_one: RunOne | None = None
    dial: Dialler | None = None

    def __post_init__(self) -> None:
        if (self.run_one is None) == (self.dial is None):
            raise ValueError("a set action runs per target or dials, exactly one of the two")


_SET_ACTIONS: dict[str, SetAction] = {}


def set_action_of(tool: str) -> SetAction | None:
    """The set action registered under this tool name, if it is plan-backed."""
    return _SET_ACTIONS.get(tool)


# --- the plan row --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanRow:
    id: UUID
    user_id: UUID
    origin: str
    tool: str
    target_type: str
    args: dict[str, Any]
    title: str
    why: str
    lens_text: str
    run_at: datetime | None
    target_count: int
    excluded_count: int
    exclusions: dict[str, int]
    estimate_inr: Decimal | None
    estimate_note: str
    plan_hash: str
    status: str
    expires_at: datetime
    approved_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    done_count: int
    skipped_count: int
    failed_count: int
    result: str | None
    campaign_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @property
    def pending_count(self) -> int:
        return max(self.target_count - self.done_count - self.skipped_count - self.failed_count, 0)


_PLAN_COLUMNS: Final = (
    "id, user_id, origin, tool, target_type, args, title, why, lens_text, run_at, "
    "target_count, excluded_count, exclusions, estimate_inr, estimate_note, plan_hash, status, "
    "expires_at, approved_at, started_at, finished_at, done_count, skipped_count, "
    "failed_count, result, campaign_id, created_at, updated_at"
)


def _row(r: Any) -> PlanRow:
    return PlanRow(
        id=UUID(str(r.id)),
        user_id=UUID(str(r.user_id)),
        origin=str(r.origin),
        tool=str(r.tool),
        target_type=str(r.target_type),
        args=dict(r.args or {}),
        title=str(r.title),
        why=str(r.why),
        lens_text=str(r.lens_text),
        run_at=r.run_at,
        target_count=int(r.target_count),
        excluded_count=int(r.excluded_count),
        exclusions={str(k): int(v) for k, v in dict(r.exclusions or {}).items()},
        estimate_inr=r.estimate_inr,
        estimate_note=str(r.estimate_note),
        plan_hash=str(r.plan_hash),
        status=str(r.status),
        expires_at=r.expires_at,
        approved_at=r.approved_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        done_count=int(r.done_count),
        skipped_count=int(r.skipped_count),
        failed_count=int(r.failed_count),
        result=r.result,
        campaign_id=None if r.campaign_id is None else UUID(str(r.campaign_id)),
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


async def read_plan(
    session: AsyncSession, plan_id: UUID, *, for_update: bool = False
) -> PlanRow | None:
    """The plan, under the caller's RLS session; None for another account's id."""
    lock = " FOR UPDATE" if for_update else ""
    row = (
        await session.execute(
            text(f"SELECT {_PLAN_COLUMNS} FROM copilot_plans WHERE id = :id{lock}"),
            {"id": plan_id},
        )
    ).first()
    return None if row is None else _row(row)


async def plan_of(session: AsyncSession, plan_id: UUID, *, user_id: UUID) -> PlanRow:
    """The person's own plan, or 404 — another person's plan and another account's are
    the same answer, as for the activity log."""
    plan = await read_plan(session, plan_id)
    if plan is None or plan.user_id != user_id:
        raise ProblemError.not_found("Plan")
    return await _expire_if_due(session, plan)


async def _expire_if_due(session: AsyncSession, plan: PlanRow) -> PlanRow:
    if plan.status != "proposed" or plan.expires_at > datetime.now(UTC):
        return plan
    await session.execute(
        text(
            "UPDATE copilot_plans SET status = 'expired', updated_at = now() "
            "WHERE id = :id AND status = 'proposed'"
        ),
        {"id": plan.id},
    )
    refreshed = await read_plan(session, plan.id)
    assert refreshed is not None
    return refreshed


def plan_hash(
    *,
    tool: str,
    change: Mapping[str, Any],
    targets: Sequence[UUID],
    excluded: Mapping[UUID, str],
    estimate: Estimate,
    run_at: datetime | None,
) -> str:
    """SHA-256 over everything an approval agrees to, in a canonical encoding."""
    body = {
        "tool": tool,
        "change": change,
        "targets": [str(target) for target in targets],
        "excluded": {str(k): v for k, v in sorted(excluded.items(), key=lambda kv: str(kv[0]))},
        "estimate": None if estimate.inr is None else str(estimate.inr),
        "run_at": None if run_at is None else run_at.isoformat(),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reason(text_: str) -> str:
    cleaned = strip_invisible(text_).strip() or "left out"
    return cleaned[:MAX_TARGET_REASON]


async def build_plan(
    session: AsyncSession,
    actor: ToolActor,
    *,
    tool: str,
    action: SetAction,
    args: Mapping[str, Any],
    origin: PlanOrigin,
) -> PlanRow:
    """Resolve, exclude, estimate, hash and freeze a plan. Refuses a set with nobody in it."""
    prepared = await action.prepare(session, actor, args)
    targets = list(dict.fromkeys(prepared.targets))
    if not targets:
        raise WriteRefusedError(
            "nothing matches those filters, so there is no plan to make; tell the person "
            "and ask whether they meant something else"
        )
    excluded = {
        target: _reason(reason)
        for target, reason in (
            await action.exclude(session, actor, prepared.change, targets)
        ).items()
        if target in set(targets)
    }
    going = len(targets) - len(excluded)
    estimate = await action.estimate(session, actor, prepared.change, going) if going else NO_COST
    digest = plan_hash(
        tool=tool,
        change=prepared.change,
        targets=targets,
        excluded=excluded,
        estimate=estimate,
        run_at=prepared.run_at,
    )
    exclusions: dict[str, int] = {}
    for reason in excluded.values():
        exclusions[reason] = exclusions.get(reason, 0) + 1
    plan_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO copilot_plans (id, tenant_id, user_id, origin, tool, target_type, args, "
            "title, why, lens_text, run_at, target_count, excluded_count, exclusions, "
            "estimate_inr, estimate_note, plan_hash, status, expires_at, created_at, "
            "updated_at) VALUES (:id, :tid, :uid, :origin, :tool, :tt, CAST(:args AS jsonb), "
            ":title, :why, :lens, :run_at, :n, :x, CAST(:exclusions AS jsonb), :inr, :note, "
            ":hash, 'proposed', :expires, now(), now())"
        ),
        {
            "id": plan_id,
            "tid": actor.tenant_id,
            "uid": actor.user_id,
            "origin": origin,
            "tool": tool,
            "tt": action.target_type,
            "args": json.dumps(prepared.change),
            "title": strip_invisible(prepared.title)[:200],
            "why": strip_invisible(prepared.why)[:500],
            # The lens as the person typed it can hold a name or digits they searched for.
            "lens": redact(strip_invisible(prepared.lens_text)).text[:500],
            "run_at": prepared.run_at,
            "n": len(targets),
            "x": len(excluded),
            "exclusions": json.dumps(exclusions),
            "inr": estimate.inr,
            "note": estimate.note,
            "hash": digest,
            "expires": datetime.now(UTC) + PLAN_TTL,
        },
    )
    await session.execute(
        text(
            "INSERT INTO copilot_plan_targets (id, tenant_id, plan_id, target_id, position, "
            "excluded, status, reason, created_at, updated_at) "
            "SELECT u.id, :tid, :pid, u.target, u.pos, u.excluded, "
            "CASE WHEN u.excluded THEN 'skipped' ELSE 'pending' END, u.reason, now(), now() "
            "FROM unnest(CAST(:ids AS uuid[]), CAST(:targets AS uuid[]), CAST(:positions AS "
            "int[]), CAST(:excluded AS boolean[]), CAST(:reasons AS text[])) "
            "AS u(id, target, pos, excluded, reason)"
        ),
        {
            "tid": actor.tenant_id,
            "pid": plan_id,
            "ids": [uuid7() for _ in targets],
            "targets": targets,
            "positions": list(range(len(targets))),
            "excluded": [target in excluded for target in targets],
            "reasons": [excluded.get(target) for target in targets],
        },
    )
    if excluded:
        await session.execute(
            text("UPDATE copilot_plans SET skipped_count = :n WHERE id = :id"),
            {"n": len(excluded), "id": plan_id},
        )
    row = await read_plan(session, plan_id)
    assert row is not None
    log.info(
        "copilot_plan_built",
        extra={"plan_id": str(plan_id), "tool": tool, "targets": len(targets)},
    )
    return row


def _approval_refused(code: str, detail: str) -> ProblemError:
    return ProblemError(
        kind="conflict",
        code=code,
        title="That plan could not be approved",
        detail=detail,
        remediation="Ask again to see the plan as it is now — nothing has been changed.",
    )


async def approve(
    session: AsyncSession, actor: ToolActor, *, plan_id: UUID, expected_hash: str
) -> PlanRow:
    """Approve exactly this plan and queue its run, in the caller's transaction.

    The row is locked, so two clicks approve once: the second sees `approved` and is
    refused. A hash that differs from the stored one is refused — the approval is for the
    plan the person was shown, not for whatever the id names now."""
    plan = await read_plan(session, plan_id, for_update=True)
    if plan is None or plan.user_id != actor.user_id:
        raise ProblemError.not_found("Plan")
    plan = await _expire_if_due(session, plan)
    if plan.status == "expired":
        raise _approval_refused("copilot_plan_expired", "This plan has expired.")
    if plan.status != "proposed":
        raise _approval_refused(
            "copilot_plan_decided", f"This plan has already been {plan.status}."
        )
    if plan.plan_hash != expected_hash:
        raise _approval_refused(
            "copilot_plan_changed", "This plan is not the one that was shown to you."
        )
    await session.execute(
        text(
            "UPDATE copilot_plans SET status = 'approved', approved_at = now(), "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": plan_id},
    )
    await enqueue_outbox(
        session,
        job=RUN_PLAN_JOB,
        payload={"tenant_id": str(actor.tenant_id), "plan_id": str(plan_id)},
    )
    approved = await read_plan(session, plan_id)
    assert approved is not None
    return approved


async def cancel(session: AsyncSession, *, plan_id: UUID, user_id: UUID) -> PlanRow:
    """Stop a plan: before approval nothing runs; while running, the worker stops before
    its next batch and every target not yet reached is skipped."""
    plan = await read_plan(session, plan_id, for_update=True)
    if plan is None or plan.user_id != user_id:
        raise ProblemError.not_found("Plan")
    if plan.status not in ("proposed", "approved", "running"):
        raise ProblemError(
            kind="conflict",
            code="copilot_plan_not_cancellable",
            title="That plan can't be stopped",
            detail=f"This plan is already {plan.status}.",
            remediation="Nothing more will run under it.",
        )
    await session.execute(
        text(
            "UPDATE copilot_plan_targets SET status = 'skipped', reason = 'Cancelled before "
            "it was reached.', finished_at = now(), updated_at = now() "
            "WHERE plan_id = :id AND status = 'pending'"
        ),
        {"id": plan_id},
    )
    await _recount(session, plan_id)
    await session.execute(
        text(
            "UPDATE copilot_plans SET status = 'cancelled', finished_at = now(), "
            "result = :result, updated_at = now() WHERE id = :id"
        ),
        {"id": plan_id, "result": _result_sentence(await _tallies(session, plan_id), True)},
    )
    cancelled = await read_plan(session, plan_id)
    assert cancelled is not None
    return cancelled


# --- running -----------------------------------------------------------------------------


async def _tallies(session: AsyncSession, plan_id: UUID) -> dict[str, int]:
    rows = await session.execute(
        text(
            "SELECT status, count(*) FROM copilot_plan_targets WHERE plan_id = :id GROUP BY status"
        ),
        {"id": plan_id},
    )
    return {str(status): int(n) for status, n in rows.all()}


async def _recount(session: AsyncSession, plan_id: UUID) -> None:
    tallies = await _tallies(session, plan_id)
    await session.execute(
        text(
            "UPDATE copilot_plans SET done_count = :d, skipped_count = :s, failed_count = :f, "
            "updated_at = now() WHERE id = :id"
        ),
        {
            "id": plan_id,
            "d": tallies.get("done", 0),
            "s": tallies.get("skipped", 0),
            "f": tallies.get("failed", 0),
        },
    )


def _result_sentence(tallies: Mapping[str, int], cancelled: bool) -> str:
    done, skipped, failed = (tallies.get(k, 0) for k in ("done", "skipped", "failed"))
    head = "Stopped." if cancelled else "Finished."
    parts = [f"{done} done"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if failed:
        parts.append(f"{failed} failed")
    return f"{head} {', '.join(parts)}."


async def claim_run(session: AsyncSession, plan_id: UUID) -> PlanRow | None:
    """Move an approved plan to running (or keep a running one, for a resume). None when
    there is nothing to run: cancelled, done, or never approved."""
    row = (
        await session.execute(
            text(
                "UPDATE copilot_plans SET status = 'running', "
                "started_at = COALESCE(started_at, now()), updated_at = now() "
                "WHERE id = :id AND status IN ('approved', 'running') RETURNING id"
            ),
            {"id": plan_id},
        )
    ).first()
    if row is None:
        return None
    return await read_plan(session, plan_id)


async def pending_batch(session: AsyncSession, plan_id: UUID, *, size: int) -> list[UUID]:
    """The next pending targets, locked so a second worker on the same plan skips them."""
    rows = await session.execute(
        text(
            "SELECT target_id FROM copilot_plan_targets WHERE plan_id = :id "
            "AND status = 'pending' ORDER BY position LIMIT :n FOR UPDATE SKIP LOCKED"
        ),
        {"id": plan_id, "n": size},
    )
    return [UUID(str(r[0])) for r in rows.all()]


async def record_outcome(
    session: AsyncSession, plan_id: UUID, target_id: UUID, outcome: TargetOutcome
) -> bool:
    """Settle one target; False when it was already settled (a resumed run). The
    compare-and-set on `pending` is the per-target idempotency."""
    reason = None if outcome.reason is None else _reason(outcome.reason)
    row = (
        await session.execute(
            text(
                "UPDATE copilot_plan_targets SET status = :status, reason = :reason, "
                "finished_at = now(), updated_at = now() "
                "WHERE plan_id = :pid AND target_id = :tid AND status = 'pending' RETURNING id"
            ),
            {"pid": plan_id, "tid": target_id, "status": outcome.status, "reason": reason},
        )
    ).first()
    return row is not None


async def still_running(session: AsyncSession, plan_id: UUID) -> bool:
    status = (
        await session.execute(
            text("SELECT status FROM copilot_plans WHERE id = :id"), {"id": plan_id}
        )
    ).scalar_one_or_none()
    return status == "running"


async def heartbeat(session: AsyncSession, plan_id: UUID) -> None:
    """Progress readable on the card, and proof to the resume sweep that a worker holds it."""
    await _recount(session, plan_id)


async def finish(session: AsyncSession, plan_id: UUID, *, note: str | None = None) -> None:
    """Close a running plan with its result sentence."""
    await _recount(session, plan_id)
    sentence = _result_sentence(await _tallies(session, plan_id), False)
    if note:
        sentence = f"{sentence} {note}"
    await session.execute(
        text(
            "UPDATE copilot_plans SET status = 'done', finished_at = now(), result = :result, "
            "updated_at = now() WHERE id = :id AND status = 'running'"
        ),
        {"id": plan_id, "result": sentence[:500]},
    )


async def skip_rest(session: AsyncSession, plan_id: UUID, *, reason: str) -> None:
    """Every target not yet reached is skipped with this reason (the approver left, the
    account is closed, a dial plan's campaign could not start)."""
    await session.execute(
        text(
            "UPDATE copilot_plan_targets SET status = 'skipped', reason = :reason, "
            "finished_at = now(), updated_at = now() "
            "WHERE plan_id = :id AND status = 'pending'"
        ),
        {"id": plan_id, "reason": _reason(reason)},
    )


async def attach_campaign(session: AsyncSession, plan_id: UUID, campaign_id: UUID) -> None:
    await session.execute(
        text("UPDATE copilot_plans SET campaign_id = :cid, updated_at = now() WHERE id = :id"),
        {"cid": campaign_id, "id": plan_id},
    )


# --- reading for the card ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetRow:
    target_id: UUID
    position: int
    excluded: bool
    status: str
    reason: str | None
    label: str | None
    finished_at: datetime | None


async def targets_page(
    session: AsyncSession,
    plan: PlanRow,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[TargetRow], int]:
    """One page of a plan's targets, with the lead's name when the target is a lead (read
    through the lead, never copied into the plan)."""
    params: dict[str, Any] = {
        "id": plan.id,
        "lim": min(max(limit, 1), MAX_TARGET_PAGE),
        "off": max(offset, 0),
    }
    where = "t.plan_id = :id"
    if status is not None:
        where += " AND t.status = :status"
        params["status"] = status
    label = (
        "(SELECT l.name FROM leads l WHERE l.id = t.target_id AND l.deleted_at IS NULL)"
        if plan.target_type == "lead"
        else "NULL"
    )
    rows = await session.execute(
        text(
            f"SELECT t.target_id, t.position, t.excluded, t.status, t.reason, {label}, "
            f"t.finished_at, count(*) OVER () FROM copilot_plan_targets t WHERE {where} "
            "ORDER BY t.position LIMIT :lim OFFSET :off"
        ),
        params,
    )
    found = rows.all()
    total = int(found[0][7]) if found else 0
    return [
        TargetRow(
            target_id=UUID(str(r[0])),
            position=int(r[1]),
            excluded=bool(r[2]),
            status=str(r[3]),
            reason=r[4],
            label=None if r[5] is None else strip_invisible(str(r[5])),
            finished_at=r[6],
        )
        for r in found
    ], total


async def recent_plans(session: AsyncSession, *, user_id: UUID, limit: int) -> list[PlanRow]:
    rows = await session.execute(
        text(
            f"SELECT {_PLAN_COLUMNS} FROM copilot_plans WHERE user_id = :uid "
            "ORDER BY created_at DESC, id DESC LIMIT :lim"
        ),
        {"uid": user_id, "lim": min(max(limit, 1), 50)},
    )
    return [_row(r) for r in rows.all()]


# --- the ActionTool adapter ----------------------------------------------------------------


def _money(inr: Decimal | None, note: str) -> str:
    if inr is None:
        return f"Cost not known. {note}"
    if inr == 0:
        return note
    return f"About {display_inr(inr)}. {note}"


def plan_card(plan: PlanRow) -> Plan:
    """The proposal card's words for a plan; `args` carry only the id and the hash, which
    is what the confirm token signs."""
    going = plan.target_count - plan.excluded_count
    left_out = (
        f" {plan.excluded_count} left out: "
        + "; ".join(f"{reason} ({n})" for reason, n in plan.exclusions.items())
        + "."
        if plan.excluded_count
        else ""
    )
    when = "as soon as you approve" if plan.run_at is None else f"at {plan.run_at.isoformat()}"
    return Plan(
        object_id=str(plan.id),
        title=plan.title,
        summary=f"{plan.why}: {going} of {plan.lens_text}, {when}.{left_out}",
        current=None,
        proposed=f"{going} {plan.target_type}(s)",
        cost=_money(plan.estimate_inr, plan.estimate_note),
        reversal=(
            "You can stop it while it runs; what has already been done stays done and "
            "each one can be changed back on its own screen."
        ),
        args={"plan_id": str(plan.id), "plan_hash": plan.plan_hash},
    )


def set_action_tool(
    *,
    name: str,
    permission: Permission,
    object_type: str,
    audit_action: str,
    where: str,
    description: str,
    properties: dict[str, Any],
    action: SetAction,
) -> ActionTool:
    """A confirm-tier `ActionTool` whose card is a plan (module docstring)."""
    from apps.api.copilot.actions import action_schema

    async def _plan(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
        if "plan_id" in args:
            # The Approvals inbox re-plans with the staged arguments: the same plan, if it
            # is still the one that was staged.
            plan = await plan_of(session, UUID(str(args["plan_id"])), user_id=actor.user_id)
            if plan.status != "proposed" or plan.plan_hash != args.get("plan_hash"):
                raise WriteRefusedError(f"that plan is {plan.status} now, so nothing was run")
            return plan_card(plan)
        built = await build_plan(session, actor, tool=name, action=action, args=args, origin="pip")
        return plan_card(built)

    async def _execute(
        session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
    ) -> Executed:
        plan = await approve(
            session,
            actor,
            plan_id=UUID(str(args["plan_id"])),
            expected_hash=str(args.get("plan_hash", "")),
        )
        going = plan.target_count - plan.excluded_count
        return Executed(
            applied=True,
            detail=f"Approved. Working through {going} now; you will see the result here.",
            audit_summary={
                "plan_id": str(plan.id),
                "targets": plan.target_count,
                "excluded": plan.excluded_count,
            },
            object_id=str(plan.id),
        )

    _SET_ACTIONS[name] = action
    return ActionTool(
        name=name,
        tier="confirm",
        undo=None,
        permission=permission,
        object_type=object_type,
        audit_action=audit_action,
        where=where,
        schema=action_schema(name, description + PROPOSES_ONLY, properties),
        plan=_plan,
        execute=_execute,
    )


def plan_id_of(args: Mapping[str, Any] | None) -> str | None:
    """The plan a confirm or an approval is about, read from its canonical arguments."""
    if not args:
        return None
    value = args.get("plan_id")
    return str(value) if isinstance(value, str) else None


__all__ = [
    "BATCH",
    "MAX_TARGET_PAGE",
    "NO_COST",
    "PLAN_TTL",
    "RUN_PLAN_JOB",
    "DialStart",
    "Estimate",
    "PlanRow",
    "Prepared",
    "SetAction",
    "TargetOutcome",
    "TargetRow",
    "approve",
    "attach_campaign",
    "build_plan",
    "cancel",
    "claim_run",
    "finish",
    "heartbeat",
    "pending_batch",
    "plan_card",
    "plan_hash",
    "plan_id_of",
    "plan_of",
    "read_plan",
    "recent_plans",
    "record_outcome",
    "set_action_of",
    "set_action_tool",
    "skip_rest",
    "still_running",
    "targets_page",
]
