"""Planned maintenance: the window, the two states, and the drain that separates them.

D-544. The founder's sentence is the specification and every design decision below comes
out of one clause of it:

    "We can have scheduled maintenances also which can be scheduled from the admin
    panel. And this maintenance should also handle in-process actions, and maintenance
    mode is fully activated in the backend also ONLY when there are no active calls or
    active jobs across the whole of Calevate and every client. And during maintenance the
    clients will not be able to access their portal at all."

═══ THE TWO STATES, WHICH ARE THE WHOLE FEATURE ═══

`scheduled -> draining -> active -> completed`, plus `cancelled` off the first two.

* **`draining` is not `active`.** When the window opens the platform STOPS ACCEPTING new
  work and does not touch the work already running: no new dial leaves `check_dispatch`,
  the campaign tick claims no contacts, and inbound agents start answering with the
  maintenance message instead of doing business (`workers/maintenance.py`). Calls that
  were already up stay up; jobs already queued still run; their webhooks still land,
  because `/hooks` is in `loadshed.ALWAYS_ALLOWED_PREFIXES` and voice-runtime mounts no
  shed middleware at all. **The portal is still open in `draining`** — the client sees the
  banner, not the door.
* **`active` is reached ONLY when in-flight work is zero**, which is the founder's "ONLY
  when", or when the drain deadline passes (below). Entering it writes
  `platform_state.load_shed_mode = 'maintenance'`, which is what actually shuts the client
  surface — this module adds no second enforcement mechanism, because the shed already
  refuses every client read and write and already exempts health, the engine's webhooks
  and the whole operator console (`core/loadshed.py`, BACKEND-PATTERNS §6).

Nothing here is a second big red switch. The window is a SCHEDULE over the lever that
already exists; `set_platform_status` remains the only writer of the mode.

═══ THE DRAIN IS BOUNDED, AND WHAT HAPPENS AT THE DEADLINE ═══

An unbounded drain is not a design, it is a hope: one call that never hangs up, one job
wedged on a vendor socket, and the window sits at 98% for ever with an operator watching a
spinner. So `drain_deadline_at = draining_since + max_drain_minutes` is stamped on the row
when draining starts, is visible on the console from that second, and is the operator's to
extend while the drain runs.

At the deadline the window goes ACTIVE anyway, `forced = true`, and the counts that were
still outstanding are written to `stragglers` and alerted on
(`WORKER_STALL`/`maintenance_drain_forced`). **What does NOT happen at the deadline is
anything to the stragglers themselves.** A live call is not hung up: a caller mid-sentence
is a person, the recording and consent obligations around them do not pause for our
convenience, and the post-call pipeline behind them survives the window untouched for the
reason above (the webhook path is never shed). A wedged job is not killed either — arq
owns that ladder and killing it here would only lose the alert. The deadline decides when
the PLATFORM stops serving clients; it does not decide when other people's work stops.

That is the honest reading of "bounded": bounded WAIT, not bounded work. The operator
gets a number and a list instead of a spinner, and the thing they were going to do next —
take the API down, run a migration — is theirs to start knowing exactly what is still
moving.

═══ WHAT AN ANNOUNCED WINDOW MAY STILL BECOME ═══

A window clients have been TOLD about is a commitment, and **the commitment is kept by
RE-ANNOUNCING, not by freezing** (the founder's decision, reversing this module's first
rule):

* a `scheduled` window may be moved — start, end, wording, drain bound — announced or not.
  The first version of this refused to move an announced START and told the operator to
  cancel and re-schedule. That was two audited actions producing three client emails for
  one change of mind, and it made the honest thing (moving a window by an hour) more
  expensive than the dishonest one (leaving it wrong);
* **every client-visible change to an announced window re-announces.** `amend_window`
  CLEARS `amended_notice_at`, the tick claims it and mails everybody the window as it now
  is. So the last message a client holds about a window always describes the window that
  is actually going to happen — which is the property "frozen" was reaching for, obtained
  by telling people rather than by refusing;
* **a window that has BEGUN is not rescheduled.** `draining` and `active` have already
  paused the campaigns and changed what agents say; their start is history and there is no
  coherent meaning to moving it. The verb from those states is END, which puts everything
  back. That half of the original rule stands.

⚠ **N MOVES DO NOT ALWAYS MEAN N EMAILS, AND THAT IS THE DESIGN.** The claim is a stamp,
so each move re-opens it and the next tick sends one notice describing the state AFTER
that move. Two moves either side of a tick send two notices; two moves inside the same
fifteen seconds send ONE, naming the final time. The second is strictly better than the
alternative — a client does not need a correction to a correction they never received —
and what is guaranteed is the part that matters: **no move ever goes unannounced, and no
notice ever describes a state the window has already left.**

═══ WHY THE STATE MACHINE IS CAS AND NOTHING ELSE ═══

`db/transition.transition_status` is the repo's one transition primitive (BACKEND-PATTERNS
§5) and every move below goes through it, including the ones the worker makes. That
matters more here than on a campaign: the tick runs on every worker process, so two of
them will race to activate the same window on the same second, and exactly one may write
the audit row, mail the clients and flip the load-shed mode. `rowcount == 0` is the loser,
and losing is a no-op rather than an error.

The notice stamps use the same primitive in its narrowest form — `UPDATE ... WHERE id = :id
AND <stamp> IS NULL` — which is what makes each of the three client notices exactly-once
across an arbitrary number of processes with no lock and no second table.
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

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.result import rowcount_of
from apps.api.db.transition import transition_status
from apps.api.ops.models import DEFAULT_MAX_DRAIN_MINUTES, MAINTENANCE_OPEN_STATES

log = get_logger(__name__)

MaintenanceState = Literal["scheduled", "draining", "active", "completed", "cancelled"]

#: The kinds of client notice a window can owe, and the column each is stamped in. The
#: mapping is the ONE place the two vocabularies meet: `claim_notice` interpolates the
#: column name from this dict and from nowhere else, so a caller cannot name a column.
NOTICE_COLUMNS: Final[Mapping[str, str]] = {
    "advance": "advance_notice_at",
    "amended": "amended_notice_at",
    "active": "active_notice_at",
    "ended": "ended_notice_at",
}
NoticeKind = Literal["advance", "amended", "active", "ended"]


def advance_notice_lead() -> timedelta:
    """How far ahead of a window clients are told, as the OPERATOR has set it.

    A function rather than a constant because the founder made it a dial: it is
    `Settings.maintenance_notice_lead_hours`, managed from the ops console, classified
    `live` in `core/platform_config.FIELD_APPLIES`, and bounded 1..720 hours at the field
    (a zero lead is not a shorter notice, it is no notice; a lead longer than
    `MAX_LEAD_TIME` would announce every window the instant it was created).

    ⚠ **CHANGING IT CANNOT RE-NOTIFY OR UN-NOTIFY AN ANNOUNCED WINDOW.** The announcement
    is a CLAIM on a row — `advance_notice_at`, stamped once by a CAS — not a value
    recomputed from this setting on every tick. Shortening the lead cannot retract a mail
    that has been sent; lengthening it cannot make an announced window announce again. The
    one thing this decides is when a window that has NOT been announced becomes due, which
    is why `FIELD_APPLIES` can honestly classify it `live` with no caveat.
    """
    return timedelta(hours=get_settings().maintenance_notice_lead_hours)


#: The shortest window an operator may schedule. Not a nicety: `starts_at` in the past
#: would open a window the tick drains on its next pass with no notice sent at all, and
#: `ends_at` a minute later would complete it before the drain finished. Five minutes is
#: longer than one drain probe and shorter than any real maintenance.
MIN_WINDOW = timedelta(minutes=5)

#: The furthest ahead a window may be scheduled. A year-out window is a row nobody will
#: remember, sitting in the singleton slot and blocking every real one.
MAX_LEAD_TIME = timedelta(days=90)

_COLUMNS = (
    "id, reason, starts_at, ends_at, state, max_drain_minutes, draining_since, "
    "drain_deadline_at, activated_at, forced, stragglers, in_flight, probed_at, "
    "ended_at, cancelled_at, "
    "restore_load_shed_mode, advance_notice_at, amended_notice_at, active_notice_at, "
    "ended_notice_at, created_at"
)


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    """One window, as every surface reads it.

    A dataclass rather than the ORM row for the reason every other `ops/` read gives: the
    console, the worker tick and the client-facing banner all want the same nineteen
    values and none of them wants a session-bound object that lazy-loads.
    """

    id: UUID
    reason: str
    starts_at: datetime
    ends_at: datetime
    state: MaintenanceState
    max_drain_minutes: int
    draining_since: datetime | None
    drain_deadline_at: datetime | None
    activated_at: datetime | None
    forced: bool
    stragglers: dict[str, Any] | None
    in_flight: dict[str, Any] | None
    probed_at: datetime | None
    ended_at: datetime | None
    cancelled_at: datetime | None
    restore_load_shed_mode: str | None
    advance_notice_at: datetime | None
    amended_notice_at: datetime | None
    active_notice_at: datetime | None
    ended_notice_at: datetime | None
    created_at: datetime

    def short_notice(self, lead: timedelta) -> bool:
        """Was this window scheduled closer than the configured notice period?

        ═══ SCHEDULING INSIDE THE LEAD IS ALLOWED, AND ANNOUNCES IMMEDIATELY ═══

        The decision, made explicitly rather than left to fall out of the tick's
        arithmetic. `_tick_scheduled` announces as soon as `now >= starts_at - lead`, so a
        window scheduled two hours out under a 24-hour lead is already past that instant
        and its advance notice goes on the next tick — clients get two hours' notice
        instead of a day.

        REFUSING IT WAS THE ALTERNATIVE AND IT IS WORSE, in the way that matters: an
        emergency window at two hours' notice is a real and ordinary need, and an API that
        refused it would push an operator to drop the platform-wide lead setting to two
        hours (which quietly degrades every future window) or to skip the window and take
        the platform down with no notice at all (which is the state this feature exists to
        replace). A control that people route around is worse than no control.

        So it is allowed and RECORDED: `ops.maintenance_scheduled` carries `short_notice`
        and the lead in force, so "why did they only get two hours" has an answer
        afterwards, and the console shows the configured lead beside the form so the
        operator knows before they press it.
        """
        return self.starts_at - self.created_at < lead

    @property
    def announced(self) -> bool:
        """Have clients been told about this window? The one predicate the edit rules turn
        on — see the module docstring."""
        return self.advance_notice_at is not None

    @property
    def open(self) -> bool:
        return self.state in MAINTENANCE_OPEN_STATES

    def drain_overdue(self, now: datetime) -> bool:
        """Has the drain run past its deadline? False for any state but `draining`, so a
        caller cannot force a window that is not draining."""
        return (
            self.state == "draining"
            and self.drain_deadline_at is not None
            and now >= self.drain_deadline_at
        )


def _row_to_window(row: Sequence[Any]) -> MaintenanceWindow:
    return MaintenanceWindow(
        id=row[0],
        reason=str(row[1]),
        starts_at=row[2],
        ends_at=row[3],
        state=_coerce_state(row[4]),
        max_drain_minutes=int(row[5]),
        draining_since=row[6],
        drain_deadline_at=row[7],
        activated_at=row[8],
        forced=bool(row[9]),
        stragglers=row[10],
        in_flight=row[11],
        probed_at=row[12],
        ended_at=row[13],
        cancelled_at=row[14],
        restore_load_shed_mode=row[15],
        advance_notice_at=row[16],
        amended_notice_at=row[17],
        active_notice_at=row[18],
        ended_notice_at=row[19],
        created_at=row[20],
    )


def _coerce_state(value: object) -> MaintenanceState:
    """The CHECK constraint is the guarantee; this is the type narrowing.

    Unlike `loadshed._coerce_mode` there is no fail-open default, because there is no safe
    guess: a window in an unknown state must not be silently treated as `scheduled` (the
    tick would drain the platform) or as `completed` (the tick would never end it). A row
    the database should not have been able to store is a bug, and it says so.
    """
    if value in ("scheduled", "draining", "active", "completed", "cancelled"):
        return value
    raise ValueError(f"unknown maintenance state {value!r}")


async def read_open_window(session: AsyncSession) -> MaintenanceWindow | None:
    """The one window that is scheduled, draining or active — or None.

    ONE, as a database fact: `ux_platform_maintenance_windows_open` is unique over the
    open states, so this cannot silently return the first of several. The ORDER BY is
    belt-and-braces for a schema somebody drops that index from.
    """
    row = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM platform_maintenance_windows "
                "WHERE state IN ('scheduled', 'draining', 'active') "
                "ORDER BY starts_at LIMIT 1"
            )
        )
    ).first()
    return None if row is None else _row_to_window(row)


async def read_window(session: AsyncSession, window_id: UUID) -> MaintenanceWindow:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM platform_maintenance_windows WHERE id = :id"),
            {"id": window_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Maintenance window")
    return _row_to_window(row)


async def list_windows(session: AsyncSession, *, limit: int) -> list[MaintenanceWindow]:
    """Newest first, bounded by the caller's `limit` (`check_list_bounds`)."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM platform_maintenance_windows "
                "ORDER BY starts_at DESC, id DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    return [_row_to_window(row) for row in rows]


def _validate_span(*, starts_at: datetime, ends_at: datetime, now: datetime) -> None:
    """The four refusals a schedule can earn, each with a sentence an operator can act on.

    Raised rather than returned because there is no partial answer: a window with a bad
    span is not a window. The CHECK constraint holds `ends_at > starts_at` too; this is
    the boundary version, which exists so the operator reads a sentence rather than a
    constraint name.
    """
    if starts_at <= now:
        raise ProblemError(
            kind="validation",
            code="maintenance_starts_in_the_past",
            title="Start the window in the future",
            detail=(
                "A maintenance window has to be scheduled ahead of itself — clients are "
                "told before it opens, and a window that starts in the past would drain "
                "the platform on the next tick with no notice sent."
            ),
        )
    if ends_at - starts_at < MIN_WINDOW:
        raise ProblemError(
            kind="validation",
            code="maintenance_window_too_short",
            title="The window is too short",
            detail=(
                f"A window must last at least {int(MIN_WINDOW.total_seconds() // 60)} "
                "minutes; a shorter one can complete before the drain has finished."
            ),
        )
    if starts_at - now > MAX_LEAD_TIME:
        raise ProblemError(
            kind="validation",
            code="maintenance_too_far_ahead",
            title="That is too far ahead",
            detail=(
                f"Schedule a window no more than {MAX_LEAD_TIME.days} days out. It holds "
                "the platform's single maintenance slot until it runs or is cancelled."
            ),
        )


async def schedule_window(
    session: AsyncSession,
    *,
    reason: str,
    starts_at: datetime,
    ends_at: datetime,
    max_drain_minutes: int = DEFAULT_MAX_DRAIN_MINUTES,
    actor_id: UUID | None,
) -> MaintenanceWindow:
    """Create the window. Refuses while another is open.

    THE REFUSAL IS A READ AND THEN A UNIQUE INDEX, not a read alone. The read is what
    produces a sentence naming the window in the way; the index is what makes the answer
    true under two operators pressing the button at the same instant. Without the index
    this would be the read-then-write race BACKEND-PATTERNS §5 exists to forbid; without
    the read the operator would get a constraint violation instead of an explanation.
    """
    now = datetime.now(UTC)
    _validate_span(starts_at=starts_at, ends_at=ends_at, now=now)
    existing = await read_open_window(session)
    if existing is not None:
        raise ProblemError(
            kind="business_rule",
            code="maintenance_window_exists",
            title="A maintenance window is already open",
            detail=(
                f"A window is already {existing.state} (starting "
                f"{existing.starts_at.isoformat()}). Cancel or end it before scheduling "
                "another — the platform has one maintenance slot."
            ),
            status=409,
            remediation="Cancel the open window, then schedule the new one.",
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO platform_maintenance_windows "
                "(id, reason, starts_at, ends_at, max_drain_minutes, created_by) "
                "VALUES (gen_random_uuid(), :reason, :starts_at, :ends_at, :drain, "
                "CAST(NULLIF(:actor, '') AS uuid)) "
                f"RETURNING {_COLUMNS}"
            ),
            {
                "reason": reason,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "drain": max_drain_minutes,
                "actor": str(actor_id) if actor_id else "",
            },
        )
    ).one()
    window = _row_to_window(row)
    log.info(
        "maintenance_window_scheduled",
        extra={
            "window_id": str(window.id),
            "starts_at": window.starts_at.isoformat(),
            "ends_at": window.ends_at.isoformat(),
        },
    )
    return window


async def amend_window(
    session: AsyncSession,
    *,
    window_id: UUID,
    reason: str | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    max_drain_minutes: int | None = None,
) -> MaintenanceWindow:
    """Edit an open window, under the announcement rules in the module docstring.

    Returns the amended row. `amended_notice_at` is CLEARED by any change that a client
    can see (the wording, the end, the start), so the tick re-announces; a change to the
    drain bound alone is invisible to clients and does not.
    """
    now = datetime.now(UTC)
    window = await read_window(session, window_id)
    if not window.open:
        raise ProblemError(
            kind="business_rule",
            code="maintenance_window_closed",
            title="That window is over",
            detail=f"The window is {window.state} and can no longer be edited.",
            status=409,
        )
    # A WINDOW THAT HAS BEGUN IS NOT RESCHEDULED. The start of a draining or active window
    # is history — the campaigns are already paused and the agents are already saying
    # something else — and there is no coherent meaning to moving it. The verb for "not at
    # this time after all" from those states is END (`complete_window`), which puts
    # everything back. A `scheduled` window moves freely, announced or not; the commitment
    # is kept by re-announcing, which the module docstring argues.
    if starts_at is not None and starts_at != window.starts_at and window.state != "scheduled":
        raise ProblemError(
            kind="business_rule",
            code="maintenance_started",
            title="The window has already begun",
            detail=(
                "This window is already draining or active, so its start time is "
                "history. Extend the end time or end it early instead."
            ),
            status=409,
        )
    new_start = starts_at or window.starts_at
    new_end = ends_at or window.ends_at
    if new_end <= new_start:
        raise ProblemError(
            kind="validation",
            code="maintenance_window_too_short",
            title="The window would end before it starts",
            detail="The end of a maintenance window must be after its start.",
        )
    if window.state == "scheduled" and starts_at is not None:
        _validate_span(starts_at=new_start, ends_at=new_end, now=now)

    client_visible = (
        (reason is not None and reason != window.reason)
        or (ends_at is not None and ends_at != window.ends_at)
        or (starts_at is not None and starts_at != window.starts_at)
    )

    # ONE STATEMENT. The deadline is recomputed here rather than by a second UPDATE
    # because an extended drain bound with a stale deadline is a bound that does not
    # apply — and the two writes could interleave with the tick reading between them.
    await session.execute(
        text(
            "UPDATE platform_maintenance_windows SET "
            "reason = COALESCE(:reason, reason), "
            "starts_at = COALESCE(:starts_at, starts_at), "
            "ends_at = COALESCE(:ends_at, ends_at), "
            "max_drain_minutes = COALESCE(:drain, max_drain_minutes), "
            "drain_deadline_at = CASE WHEN draining_since IS NULL THEN drain_deadline_at "
            "  ELSE draining_since + make_interval(mins => COALESCE(:drain, "
            "       max_drain_minutes)) END, "
            "amended_notice_at = CASE WHEN :client_visible THEN NULL "
            "  ELSE amended_notice_at END, "
            "updated_at = now() "
            "WHERE id = :id"
        ),
        {
            "id": window_id,
            "reason": reason,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "drain": max_drain_minutes,
            "client_visible": client_visible and window.announced,
        },
    )
    return await read_window(session, window_id)


async def cancel_window(session: AsyncSession, *, window_id: UUID) -> bool:
    """`scheduled -> cancelled`. True when THIS call cancelled it.

    ═══ ONLY FROM `scheduled`, AND THE NARROWNESS IS THE POINT ═══

    A cancellation means NOTHING HAPPENED — so it is available exactly while nothing has.
    The moment a window starts draining it has paused every running campaign in the fleet
    and rewritten what every live inbound agent says, and those have to be put back: the
    load-shed mode restored, the campaigns resumed from where they stopped, the agents
    republished from our own record.

    That work belongs to ONE terminal state, and it is `completed`. It used to be reachable
    from `draining` here too, and that was a hole with no bottom: the tick advances the OPEN
    window, a cancelled window is not open, so a drain cancelled mid-flight left every
    campaign paused and every agent telling callers the platform was down, with nothing that
    would ever put them back. Making the state unreachable is the fix rather than teaching
    the tick to chase terminal windows — a second recovery path for a state that need not
    exist is the worse of the two.

    So the verbs partition cleanly: `scheduled` is cancelled, `draining` and `active` are
    ENDED (`complete_window`), and the route refuses the other pairing by name.
    """
    return await transition_status(
        session,
        table="platform_maintenance_windows",
        entity="Maintenance window",
        row_id=window_id,
        to_status="cancelled",
        from_statuses=("scheduled",),
        status_column="state",
        extra_set="cancelled_at = now()",
    )


async def begin_drain(session: AsyncSession, *, window_id: UUID, max_drain_minutes: int) -> bool:
    """`scheduled -> draining`, stamping the moment and the deadline in one statement."""
    return await transition_status(
        session,
        table="platform_maintenance_windows",
        entity="Maintenance window",
        row_id=window_id,
        to_status="draining",
        from_statuses=("scheduled",),
        status_column="state",
        extra_set=(
            "draining_since = now(), "
            "drain_deadline_at = now() + make_interval(mins => :drain_minutes)"
        ),
        params={"drain_minutes": max_drain_minutes},
    )


async def activate(
    session: AsyncSession,
    *,
    window_id: UUID,
    forced: bool,
    stragglers: str | None,
    restore_mode: str,
) -> bool:
    """`draining -> active`. True when THIS call activated it.

    `stragglers` arrives as a JSON STRING rather than a dict because it is bound into a
    `jsonb` cast: passing a mapping would make psycopg guess an adaptation for a column
    whose type it cannot see through `text()`.

    `restore_mode` is the load-shed mode to put back at the end, read by the CALLER
    immediately before this and written here so the two are one row. A window that opened
    during a `reduced` shed must not end by declaring the platform healthy.
    """
    return await transition_status(
        session,
        table="platform_maintenance_windows",
        entity="Maintenance window",
        row_id=window_id,
        to_status="active",
        from_statuses=("draining",),
        status_column="state",
        extra_set=(
            "activated_at = now(), forced = :forced, "
            "stragglers = CAST(:stragglers AS jsonb), "
            "restore_load_shed_mode = :restore_mode"
        ),
        params={"forced": forced, "stragglers": stragglers, "restore_mode": restore_mode},
    )


async def complete_window(session: AsyncSession, *, window_id: UUID) -> bool:
    """`draining | active -> completed`. True when THIS call ended it.

    BOTH source states, deliberately, and this is the other half of `cancel_window`'s
    argument. Ending from `active` is the ordinary case. Ending from `draining` is the
    operator who watched the drain and changed their mind — and it is a COMPLETION rather
    than a cancellation, because the drain DID happen: campaigns were paused by it and
    agents were switched by it, so the same restoration is owed. One terminal state for
    both is what stops the tick's restoration arm having to know which verb was pressed.
    """
    return await transition_status(
        session,
        table="platform_maintenance_windows",
        entity="Maintenance window",
        row_id=window_id,
        to_status="completed",
        from_statuses=("draining", "active"),
        status_column="state",
        extra_set="ended_at = now()",
    )


@dataclass(frozen=True, slots=True)
class InFlight:
    """What the platform was still doing when the drain probe ran.

    THE TWO NUMBERS ARE THE FOUNDER'S TWO NOUNS — "no active calls or active jobs across
    the whole of Calevate and every client" — and each is counted from the DURABLE record
    rather than from a live gauge:

    * **`calls`** is `calls` rows in a non-terminal status
      (`calevate_shared.events.TERMINAL_STATUSES` is the complement), summed one tenant
      session at a time because the table is FORCE-RLS'd.
    * **`jobs`** is queued work that has been ACCEPTED and not yet finished: `outbox_messages`
      still `pending` (a side effect promised inside a committed transaction) plus
      `webhook_inbox_events` still `processing`/`enqueued` (an engine event claimed and not
      yet processed). Both tables are platform-scoped, so this is two counts in one query.

    ⚠ **`jobs` DELIBERATELY DOES NOT COUNT ARQ'S OWN `arq:in-progress:*` KEYS**, and the
    reason is not squeamishness about Redis internals. Three things are wrong with that
    measure and each is fatal on its own: the outbox dispatcher is a cron that fires every
    ten seconds, so the count is essentially never zero and a drain gated on it would
    ALWAYS reach its deadline; the drain probe is itself an arq job, so it counts itself;
    and a Redis key set is not durable truth — the thing a maintenance window is protecting
    is the DATABASE, and what matters is work that has been promised and not yet done, which
    is exactly what these two tables record. The same reasoning is why the poller and not
    the webhook is the truth on the call leg (TRD §5).

    `complete` is False when the walk ran out of budget before reaching every tenant. A
    partial walk's `calls` is a FLOOR, never a total, and a floor of zero is not evidence of
    zero — so `drained` refuses on it. That refusal is what keeps a growing client list from
    silently turning "we reached everybody and found nothing" into "we gave up early".
    """

    calls: int
    jobs: int
    tenants_unreached: int
    complete: bool

    @property
    def drained(self) -> bool:
        """The founder's "ONLY when". Nothing outstanding AND we looked everywhere."""
        return self.complete and self.calls == 0 and self.jobs == 0

    def as_json(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "jobs": self.jobs,
            "tenants_unreached": self.tenants_unreached,
            "complete": self.complete,
        }


async def record_probe(session: AsyncSession, *, window_id: UUID, in_flight: InFlight) -> None:
    """Publish the latest probe onto the window, for the console to read.

    Unconditional and not a CAS: two workers writing the same instant's measurement is
    two writes of nearly the same number, which is harmless, and a CAS here would mean a
    losing worker leaves the console reading a measurement older than the one it just
    took. `probed_at` is the freshness the console renders beside the numbers.
    """
    await session.execute(
        text(
            "UPDATE platform_maintenance_windows "
            "SET in_flight = CAST(:in_flight AS jsonb), probed_at = now(), "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": window_id, "in_flight": json.dumps(in_flight.as_json())},
    )


async def claim_notice(session: AsyncSession, *, window_id: UUID, kind: NoticeKind) -> bool:
    """Claim the right to send ONE notice of `kind` for this window.

    True exactly once per (window, kind) across every process, for ever — the CAS is
    `WHERE <stamp> IS NULL`, so the second caller updates nothing and sends nothing. An
    amendment re-opens the `amended` claim by NULLing the stamp (`amend_window`), which is
    the one intended way a claim comes back.

    ⚠ **THE ADVANCE CLAIM SETTLES THE AMENDMENT SLOT WITH IT, IN THE SAME STATEMENT.** An
    amendment is by definition a change SINCE the announcement, so at the instant the
    announcement goes out there is nothing outstanding — and without this, `amended_notice_at`
    starts life NULL, which the tick reads as "an amendment is owed" and mails every client
    a correction to a window nobody had changed, one tick after telling them about it. One
    statement rather than two so a crash between them cannot leave the spurious notice
    armed.

    The column names are interpolated from `NOTICE_COLUMNS` and from nowhere else: the
    parameter is a `Literal`, the lookup raises on anything else, and `check_raw_sql`
    resolves the dict to our own source text.
    """
    column = NOTICE_COLUMNS[kind]
    settles_amendment = ", amended_notice_at = now()" if kind == "advance" else ""
    result = await session.execute(
        text(
            "UPDATE platform_maintenance_windows "
            f"SET {column} = now(){settles_amendment}, updated_at = now() "
            f"WHERE id = :id AND {column} IS NULL"
        ),
        {"id": window_id},
    )
    return rowcount_of(result) == 1


__all__ = [
    "MAX_LEAD_TIME",
    "MIN_WINDOW",
    "NOTICE_COLUMNS",
    "InFlight",
    "MaintenanceState",
    "MaintenanceWindow",
    "NoticeKind",
    "activate",
    "advance_notice_lead",
    "amend_window",
    "begin_drain",
    "cancel_window",
    "claim_notice",
    "complete_window",
    "list_windows",
    "read_open_window",
    "read_window",
    "record_probe",
    "schedule_window",
]
