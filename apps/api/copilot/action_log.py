"""The assistant's activity log: one row per action it ran, refused, or is waiting on (D-694).

WHAT A ROW IS FOR. Three readers, three needs:

* the PERSON, reading "what did the assistant do for me" on the workspace's activity log,
  with an Undo on every row whose inverse is still offered;
* the UNDO itself, which needs the state the record was in before the action
  (`prior_state`) and the state the action left it in (`result_state`) — the swap value
  and the compare value of a compare-and-swap;
* the APPROVALS inbox, where a confirm-tier action a background job reached waits for a
  person, holding the exact arguments it would run with until somebody decides.

WHAT IT IS NOT: the audit record. Every executed act still writes its `audit_log` row in
the same transaction as the change; this table is the readable, mutable working copy beside
that append-only chain, which is why it may be UPDATEd (an action becomes `undone`, an
approval is decided) and `audit_log` may not.

REDACTION. Arguments are stored after `workers.redaction.redact`, string by string, and
ids are left alone (a uuid is not personal data and a redactor that read one as a card
number would make the row useless). `pending_args` is the one unredacted copy, because it
has to run; it exists only while the row is pending and is cleared on the decision.

TWO TABLES, ONE MODULE. The client and admin realms keep separate tables
(`copilot/models.py` argues why). Every function here takes the realm and picks the
statement for it; there is no shared table name assembled at runtime.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.models import MAX_ACTION_TEXT
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.redaction import redact

log = get_logger(__name__)

ActionRealm = Literal["client", "admin"]
ActionSource = Literal["interactive", "job"]

#: HOW LONG AN UNDO IS OFFERED. Twenty-four hours: long enough to notice a change the
#: assistant made this morning, short enough that the inverse is still restoring a state
#: somebody remembers. The CAS is what makes a late undo safe; this is what makes it sane.
UNDO_WINDOW: Final = timedelta(hours=24)

#: HOW LONG A PENDING APPROVAL WAITS. The same day: an approval is a decision about the
#: world as it was when the job planned it, and a day-old plan is re-checked anyway (the
#: approve route re-runs the planner) — but a week-old one is a decision nobody is making.
APPROVAL_TTL: Final = timedelta(hours=24)

#: The most rows one page of the activity log returns (`scripts/check_list_bounds.py`).
PAGE_MAX: Final = 100
PAGE_DEFAULT: Final = 30


def _bounded(sentence: str | None) -> str | None:
    """An authored sentence, redacted, stripped of invisible characters, and capped."""
    if sentence is None:
        return None
    cleaned = strip_invisible(redact(sentence).text).strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_ACTION_TEXT:
        cleaned = cleaned[: MAX_ACTION_TEXT - 1].rstrip() + "…"
    return cleaned


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def redact_args(args: Mapping[str, Any]) -> dict[str, Any]:
    """The arguments as the log may hold them: every free string through `redact()`.

    Ids pass untouched and so do the closed-set strings a tool's schema enumerates (a
    status, a direction) — `redact` leaves those alone anyway, but a uuid's digit runs are
    exactly what a card or phone rule could misread, so they are skipped by shape.
    """

    def _clean(value: Any) -> Any:
        if isinstance(value, str):
            return value if _is_uuid(value) else redact(value).text
        if isinstance(value, Mapping):
            return {str(key): _clean(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [_clean(item) for item in value]
        return value

    return {str(key): _clean(value) for key, value in args.items()}


def _json(value: Mapping[str, Any] | None) -> str | None:
    return None if value is None else json.dumps(value, default=str)


# --- writing -------------------------------------------------------------------------

#: THE ACTOR IS RESOLVED THROUGH ITS OWN TABLE, not bound straight into the FK column: a
#: principal whose id names no `users` row (an operator's id on the client realm, a caller
#: built by a harness) records NULL instead of failing the action it describes — the log
#: must never be the reason an act rolls back. `audit_log` still names the principal.
_INSERT_CLIENT = (
    "INSERT INTO copilot_actions (id, tenant_id, actor_user_id, job_id, tool, tier, status, "
    "source, object_type, object_id, args_redacted, prior_state, result_state, pending_args, "
    "summary, refusal_reason, undoable_until, created_at, updated_at) VALUES (:id, :tenant, "
    "(SELECT u.id FROM users u WHERE u.id = :actor), :job, :tool, :tier, :status, :source, "
    ":object_type, :object_id, "
    "CAST(:args AS jsonb), CAST(:prior AS jsonb), CAST(:result AS jsonb), "
    "CAST(:pending AS jsonb), :summary, :reason, :undoable_until, now(), now())"
)

_INSERT_ADMIN = (
    "INSERT INTO admin_copilot_actions (id, admin_user_id, viewing_tenant_id, tool, tier, "
    "status, source, object_type, object_id, args_redacted, prior_state, result_state, "
    "pending_args, summary, refusal_reason, undoable_until, created_at, updated_at) VALUES "
    "(:id, (SELECT a.id FROM admin_users a WHERE a.id = :actor), :tenant, :tool, :tier, "
    ":status, :source, :object_type, :object_id, "
    "CAST(:args AS jsonb), CAST(:prior AS jsonb), CAST(:result AS jsonb), "
    "CAST(:pending AS jsonb), :summary, :reason, :undoable_until, now(), now())"
)


@dataclass(frozen=True, slots=True)
class NewAction:
    """Everything one row says. Built by the caller; written by `insert`."""

    realm: ActionRealm
    tool: str
    tier: str
    status: str
    source: ActionSource
    object_type: str
    actor_id: UUID | None
    #: The tenant on the client realm; the account on screen on the admin realm.
    tenant_id: UUID | None
    object_id: str | None = None
    args: Mapping[str, Any] | None = None
    prior_state: Mapping[str, Any] | None = None
    result_state: Mapping[str, Any] | None = None
    pending_args: Mapping[str, Any] | None = None
    summary: str | None = None
    refusal_reason: str | None = None
    undoable_until: datetime | None = None
    job_id: UUID | None = None


async def insert(session: AsyncSession, row: NewAction) -> UUID:
    """Write one row in the caller's transaction and return its id.

    In the CALLER'S transaction on purpose: an executed action's row commits with the
    change and its `audit_log` row or not at all, so the log can never show an action that
    rolled back, nor miss one that landed.
    """
    action_id = uuid7()
    params: dict[str, Any] = {
        "id": action_id,
        "tenant": row.tenant_id,
        "actor": row.actor_id,
        "tool": row.tool,
        "tier": row.tier,
        "status": row.status,
        "source": row.source,
        "object_type": row.object_type,
        "object_id": (row.object_id or None),
        # A refusal carries no arguments, by constraint and by the founder's rule.
        "args": None if row.args is None else _json(redact_args(row.args)),
        "prior": _json(row.prior_state),
        "result": _json(row.result_state),
        "pending": _json(row.pending_args),
        "summary": _bounded(row.summary),
        "reason": _bounded(row.refusal_reason),
        "undoable_until": row.undoable_until,
    }
    if row.realm == "admin":
        await session.execute(text(_INSERT_ADMIN), params)
    else:
        await session.execute(text(_INSERT_CLIENT), {**params, "job": row.job_id})
    return action_id


async def record_refusal(
    *,
    realm: ActionRealm,
    tenant_id: UUID | None,
    actor_id: UUID | None,
    tool: str,
    tier: str,
    object_type: str,
    reason: str,
    source: ActionSource = "interactive",
    job_id: UUID | None = None,
) -> None:
    """Log one refused attempt, in its own short session. NEVER RAISES.

    Its own session because the refusal usually arrives as an exception that has already
    rolled the action's transaction back. Never raising because a refusal has already been
    decided and is about to be reported to the model; failing to write the log line about
    it must not turn the answer into an error. A client-realm refusal with no tenant (a run
    with no principal) has nowhere to go and is logged as a line only.
    """
    try:
        row = NewAction(
            realm=realm,
            tool=tool,
            tier=tier,
            status="refused",
            source=source,
            object_type=object_type,
            actor_id=actor_id,
            tenant_id=tenant_id,
            refusal_reason=reason,
            job_id=job_id,
        )
        if realm == "admin":
            async with untenanted_session() as session:
                await insert(session, row)
        elif tenant_id is not None:
            async with tenant_session(tenant_id) as session:
                await insert(session, row)
        else:
            log.info("copilot_refusal_unlogged", extra={"tool": tool})
    except Exception:
        # Ids only (hard rule 6). The refusal itself still reaches the model and the person.
        log.exception("copilot_refusal_log_failed", extra={"tool": tool, "realm": realm})


def undoable_until(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + UNDO_WINDOW


# --- reading ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionRow:
    """One row as the routes and the undo read it."""

    id: UUID
    tool: str
    tier: str
    status: str
    source: str
    object_type: str
    object_id: str | None
    args_redacted: dict[str, Any] | None
    prior_state: dict[str, Any] | None
    result_state: dict[str, Any] | None
    pending_args: dict[str, Any] | None
    summary: str | None
    refusal_reason: str | None
    undoable_until: datetime | None
    undone_at: datetime | None
    decided_at: datetime | None
    created_at: datetime
    actor_id: UUID | None
    job_id: UUID | None
    #: Who undid it and who decided an approval — shown in the activity log.
    undone_by: UUID | None = None
    decided_by: UUID | None = None

    def can_undo(self, now: datetime) -> bool:
        return (
            self.status == "done" and self.undoable_until is not None and self.undoable_until > now
        )


_COLUMNS: Final = (
    "id, tool, tier, status, source, object_type, object_id, args_redacted, prior_state, "
    "result_state, pending_args, summary, refusal_reason, undoable_until, undone_at, "
    "decided_at, created_at"
)

_CLIENT_SELECT = (
    f"SELECT {_COLUMNS}, actor_user_id, job_id, undone_by, decided_by FROM copilot_actions"
)
_ADMIN_SELECT = (
    f"SELECT {_COLUMNS}, admin_user_id, NULL::uuid, undone_by, decided_by "
    "FROM admin_copilot_actions"
)


def _row(record: Sequence[Any]) -> ActionRow:
    return ActionRow(
        id=record[0],
        tool=record[1],
        tier=record[2],
        status=record[3],
        source=record[4],
        object_type=record[5],
        object_id=record[6],
        args_redacted=record[7],
        prior_state=record[8],
        result_state=record[9],
        pending_args=record[10],
        summary=record[11],
        refusal_reason=record[12],
        undoable_until=record[13],
        undone_at=record[14],
        decided_at=record[15],
        created_at=record[16],
        actor_id=record[17],
        job_id=record[18],
        undone_by=record[19],
        decided_by=record[20],
    )


async def read_for_update(
    session: AsyncSession, *, realm: ActionRealm, action_id: UUID
) -> ActionRow | None:
    """One row, LOCKED for the rest of the transaction — the undo's and the approval's
    first statement, so two clicks on one Undo serialise and the second sees `undone`."""
    statement = (
        f"{_ADMIN_SELECT} WHERE id = :id FOR UPDATE"
        if realm == "admin"
        else f"{_CLIENT_SELECT} WHERE id = :id FOR UPDATE"
    )
    record = (await session.execute(text(statement), {"id": action_id})).first()
    return None if record is None else _row(record)


async def list_actions(
    session: AsyncSession,
    *,
    realm: ActionRealm,
    actor_id: UUID,
    limit: int,
    before: datetime | None,
    pending_only: bool = False,
) -> tuple[list[ActionRow], bool]:
    """One page of this person's activity, newest first, and whether more exists.

    Scoped on the ACTOR as well as on RLS: RLS answers "which tenant" and never "which
    person", and one colleague's activity log is not another's to read
    (`copilot_conversation_turns` draws the same line).
    """
    bounded = max(1, min(limit, PAGE_MAX))
    actor_column = "admin_user_id" if realm == "admin" else "actor_user_id"
    base = _ADMIN_SELECT if realm == "admin" else _CLIENT_SELECT
    statement = (
        f"{base} WHERE {actor_column} = :actor "
        "AND (CAST(:before AS timestamptz) IS NULL OR created_at < CAST(:before AS timestamptz)) "
        "AND (NOT :pending OR status = 'pending_approval') "
        "ORDER BY created_at DESC LIMIT :limit"
    )
    records = (
        await session.execute(
            text(statement),
            {"actor": actor_id, "before": before, "pending": pending_only, "limit": bounded + 1},
        )
    ).all()
    rows = [_row(record) for record in records[:bounded]]
    return rows, len(records) > bounded


_MARK_UNDONE_CLIENT = (
    "UPDATE copilot_actions SET status = 'undone', undone_at = now(), undone_by = :by, "
    "updated_at = now() WHERE id = :id AND status = 'done'"
)
_MARK_UNDONE_ADMIN = (
    "UPDATE admin_copilot_actions SET status = 'undone', undone_at = now(), undone_by = :by, "
    "updated_at = now() WHERE id = :id AND status = 'done'"
)


async def mark_undone(
    session: AsyncSession, *, realm: ActionRealm, action_id: UUID, by: UUID
) -> bool:
    """`done` → `undone`, as a CAS on the status. False if another click got there first."""
    statement = _MARK_UNDONE_ADMIN if realm == "admin" else _MARK_UNDONE_CLIENT
    result = await session.execute(text(statement), {"id": action_id, "by": by})
    return bool(getattr(result, "rowcount", 0))


_DECIDE_CLIENT = (
    "UPDATE copilot_actions SET status = CAST(:status AS varchar), decided_at = now(), "
    "decided_by = :by, pending_args = NULL, "
    "summary = COALESCE(CAST(:summary AS text), summary), "
    "refusal_reason = COALESCE(CAST(:reason AS text), refusal_reason), "
    "args_redacted = CASE WHEN CAST(:status AS varchar) = 'refused' THEN NULL "
    "ELSE args_redacted END, "
    "updated_at = now() WHERE id = :id AND status = 'pending_approval'"
)


async def decide_approval(
    session: AsyncSession,
    *,
    action_id: UUID,
    status: Literal["done", "rejected", "expired", "refused"],
    by: UUID | None,
    summary: str | None = None,
    reason: str | None = None,
) -> bool:
    """`pending_approval` → its outcome, as a CAS. Clears `pending_args` in the same write."""
    result = await session.execute(
        text(_DECIDE_CLIENT),
        {
            "id": action_id,
            "status": status,
            "by": by,
            "summary": _bounded(summary),
            "reason": _bounded(reason),
        },
    )
    return bool(getattr(result, "rowcount", 0))


_EXPIRE_STALE = (
    "UPDATE copilot_actions SET status = 'expired', decided_at = now(), pending_args = NULL, "
    "updated_at = now() WHERE status = 'pending_approval' AND created_at < :cutoff"
)


async def expire_stale_approvals(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Expire this tenant's approvals older than `APPROVAL_TTL`. Observed lazily, on read —
    expiry is a clock passing, not an event, and the inbox is where it is looked at."""
    cutoff = (now or datetime.now(UTC)) - APPROVAL_TTL
    result = await session.execute(text(_EXPIRE_STALE), {"cutoff": cutoff})
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "APPROVAL_TTL",
    "PAGE_DEFAULT",
    "PAGE_MAX",
    "UNDO_WINDOW",
    "ActionRealm",
    "ActionRow",
    "ActionSource",
    "NewAction",
    "decide_approval",
    "expire_stale_approvals",
    "insert",
    "list_actions",
    "mark_undone",
    "read_for_update",
    "record_refusal",
    "redact_args",
    "undoable_until",
]
