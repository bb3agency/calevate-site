"""Alerts you can shape (D-1048): what reaches each channel, quiet hours, the daily cap, and the
gate every owner alert passes before it is sent.

THE TABLE. Rows are what happened (`KINDS`), columns are where it arrives (`CHANNELS`). A cell
exists only where something really delivers that kind on that channel today, so the screen
never offers a switch that controls nothing. Kinds marked `always` (money, numbers, KYC, a line
that stopped answering, failed calls) cannot be switched off from the screen or the API: each
is a thing the owner must hear about to keep the account working.

WHOSE ROW DECIDES. Every person has their own row and their own bell and computer columns. The
account email and the owner's WhatsApp are one inbox and one phone, so one row decides them:
the first owner's (`governing_user`). Anyone else sees those cells and the quiet hours and cap
as read-only.

THE GATE (`gate`). Before an owner alert is emailed or sent on WhatsApp, it asks the gate,
which records its answer in `notification_deliveries` under the alert's own dedupe key, so a
retried job gets the same answer:

* `off`: the governing row switched the cell off. Nothing is recorded or sent.
* `held`: inside quiet hours. Released at the window's end as ONE message (`workers/
  notifications.release_held_alerts`).
* `folded`: the day's email cap is reached. Released with the held ones, or at the end of the
  IST day, as one "and N more" message.
* `send`: go ahead; the row counts toward the day's cap.
* `released`: it already went out in a digest; do not send it again.

`always` kinds pass straight through: quiet hours and the cap never delay them. Quiet hours
apply to email and WhatsApp only; the bell is a list the owner opens, and a desktop pop-up is
for someone already at the screen.

The count-then-insert is serialised per (account, channel) by a transaction-scoped advisory
lock, so two alerts finishing together cannot both be the twelfth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

Channel = Literal["bell", "computer", "email", "whatsapp"]
CHANNELS: Final[tuple[Channel, ...]] = ("bell", "computer", "email", "whatsapp")
#: The channels the account's one inbox and one phone carry: decided by the governing row.
ACCOUNT_CHANNELS: Final[frozenset[Channel]] = frozenset({"email", "whatsapp"})
#: The channels quiet hours hold.
HELD_CHANNELS: Final[frozenset[str]] = frozenset({"email", "whatsapp"})

DEFAULT_QUIET_START: Final = 21
DEFAULT_QUIET_END: Final = 8
DEFAULT_DAILY_CAP: Final = 12
MAX_DAILY_CAP: Final = 100


@dataclass(frozen=True, slots=True)
class AlertKind:
    key: str
    label: str
    channels: tuple[Channel, ...]
    always: bool = False
    #: Why an always-on kind cannot be switched off; shown behind the info button.
    why: str | None = None


#: Every row of the table, in the order the screen shows them. `channels` lists only where the
#: kind is really delivered: hot-lead email and WhatsApp (`workers/notifications`), the bell
#: feed (`notifications/service`), desktop pop-ups (`web lib/desktopAlerts.ts`), the low-credit
#: email (`workers/wallet_alerts`), number and KYC emails (`workers/number_holds`,
#: `workers/kyc_notices`), and the campaign-finished email (`workers/notifications`).
KINDS: Final[tuple[AlertKind, ...]] = (
    AlertKind("hot_lead", "A call flagged for you", ("bell", "computer", "email", "whatsapp")),
    AlertKind("callback_asked", "Someone asked for a call back", ("bell",)),
    AlertKind("message_left", "Someone left you a message", ("bell",)),
    AlertKind("campaign_finished", "A campaign finished", ("bell", "email")),
    AlertKind("opt_out", "Someone asked not to be called", ("bell",)),
    AlertKind("reminder", "Reminders to call people", ("bell",)),
    AlertKind("milestone", "Milestones", ("bell",)),
    AlertKind(
        "credit_low",
        "Low credit",
        ("bell", "computer", "email"),
        always=True,
        why="When credit runs out your agents stop calling and answering.",
    ),
    AlertKind(
        "inbound_stopped",
        "A line stopped answering",
        ("bell", "computer"),
        always=True,
        why="Callers are not being answered until this is fixed.",
    ),
    AlertKind(
        "call_failed",
        "A call failed",
        ("bell", "computer"),
        always=True,
        why="A failed call can mean a number or line problem that keeps happening.",
    ),
    AlertKind(
        "numbers",
        "Your phone numbers",
        ("email",),
        always=True,
        why="A number that lapses stops your calls and can be lost for good.",
    ),
    AlertKind(
        "kyc",
        "Your business check",
        ("email",),
        always=True,
        why="Outbound calls wait on this check.",
    ),
)
KIND_BY_KEY: Final[dict[str, AlertKind]] = {k.key: k for k in KINDS}

#: The bell's attention kinds (`crm/schemas.AttentionKind`) as rows of the table. An attention
#: kind not listed here is not switchable: it is shown on every bell.
ATTENTION_KIND: Final[dict[str, str]] = {
    "lead_hot": "hot_lead",
    "credit_low": "credit_low",
    "inbound_stopped": "inbound_stopped",
    "call_failed": "call_failed",
}


def cell(kind: str, channel: str) -> str:
    return f"{kind}:{channel}"


@dataclass(frozen=True, slots=True)
class Preferences:
    off: frozenset[str] = field(default_factory=frozenset)
    quiet_enabled: bool = False
    quiet_start_hour: int = DEFAULT_QUIET_START
    quiet_end_hour: int = DEFAULT_QUIET_END
    daily_cap: int = DEFAULT_DAILY_CAP

    def allows(self, kind: str, channel: str) -> bool:
        """An unknown kind is allowed: only a row of the table can be switched off."""
        spec = KIND_BY_KEY.get(kind)
        if spec is None or spec.always:
            return True
        return cell(kind, channel) not in self.off

    def quiet_at(self, at: datetime) -> bool:
        if not self.quiet_enabled:
            return False
        hour = at.astimezone(IST).hour
        start, end = self.quiet_start_hour, self.quiet_end_hour
        return start <= hour < end if start < end else hour >= start or hour < end

    def quiet_ends(self, at: datetime) -> datetime:
        """The first instant at or after `at` that is outside quiet hours."""
        local = at.astimezone(IST)
        end = datetime.combine(local.date(), time(self.quiet_end_hour), tzinfo=IST)
        if end <= local:
            end += timedelta(days=1)
        return end.astimezone(UTC)


def ist_day_start(at: datetime) -> datetime:
    local = at.astimezone(IST)
    return datetime.combine(local.date(), time.min, tzinfo=IST).astimezone(UTC)


_COLUMNS: Final = "off, quiet_enabled, quiet_start_hour, quiet_end_hour, daily_cap"


def _from_row(row: Any) -> Preferences:
    if row is None:
        return Preferences()
    return Preferences(
        off=frozenset(str(c) for c in (row[0] or [])),
        quiet_enabled=bool(row[1]),
        quiet_start_hour=int(row[2]),
        quiet_end_hour=int(row[3]),
        daily_cap=int(row[4]),
    )


async def read_for(session: AsyncSession, user_id: UUID | None) -> Preferences:
    if user_id is None:
        return Preferences()
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM notification_preferences WHERE user_id = :uid"),
            {"uid": user_id},
        )
    ).first()
    return _from_row(row)


async def governing_user(session: AsyncSession) -> UUID | None:
    """The account's first live owner, whose row decides the account email and WhatsApp."""
    value = (
        await session.execute(
            text(
                "SELECT m.user_id FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.role = 'owner' AND u.deactivated_at IS NULL "
                "ORDER BY m.created_at, m.user_id LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    return UUID(str(value)) if value is not None else None


async def governing(session: AsyncSession) -> Preferences:
    return await read_for(session, await governing_user(session))


# --- the screen's shape ----------------------------------------------------------------

CellState = Literal["on", "off", "always", "none"]


class AlertKindOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    always: bool
    why: str | None
    #: Every channel of `CHANNELS`, `none` where this kind does not arrive.
    cells: dict[str, CellState]


class AlertPreferencesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kinds: list[AlertKindOut]
    quiet_enabled: bool
    quiet_start_hour: int
    quiet_end_hour: int
    daily_cap: int
    #: This person's row decides the account email, WhatsApp, quiet hours and the cap.
    governs_account: bool
    #: Whether this session may change those account cells (the governing owner only).
    account_editable: bool


class AlertPreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The `kind:channel` cells to switch off; every other offered cell is on.
    off: list[str] = Field(default_factory=list, max_length=len(KINDS) * len(CHANNELS))
    quiet_enabled: bool = False
    quiet_start_hour: int = Field(default=DEFAULT_QUIET_START, ge=0, le=23)
    quiet_end_hour: int = Field(default=DEFAULT_QUIET_END, ge=0, le=23)
    daily_cap: int = Field(default=DEFAULT_DAILY_CAP, ge=1, le=MAX_DAILY_CAP)


def _cells(spec: AlertKind, prefs: Preferences, account: Preferences) -> dict[str, CellState]:
    out: dict[str, CellState] = {}
    for channel in CHANNELS:
        if channel not in spec.channels:
            out[channel] = "none"
        elif spec.always:
            out[channel] = "always"
        else:
            source = account if channel in ACCOUNT_CHANNELS else prefs
            out[channel] = "on" if source.allows(spec.key, channel) else "off"
    return out


async def view(
    session: AsyncSession, *, user_id: UUID | None, may_manage: bool
) -> AlertPreferencesOut:
    mine = await read_for(session, user_id)
    owner = await governing_user(session)
    governs = user_id is not None and user_id == owner
    account = mine if governs else await read_for(session, owner)
    return AlertPreferencesOut(
        kinds=[
            AlertKindOut(
                key=k.key, label=k.label, always=k.always, why=k.why, cells=_cells(k, mine, account)
            )
            for k in KINDS
        ],
        quiet_enabled=account.quiet_enabled,
        quiet_start_hour=account.quiet_start_hour,
        quiet_end_hour=account.quiet_end_hour,
        daily_cap=account.daily_cap,
        governs_account=governs,
        account_editable=governs and may_manage,
    )


def _refuse(code: str, title: str, detail: str) -> ProblemError:
    return ProblemError(
        kind="validation", code=code, title=title, detail=detail, remediation="Reload the page."
    )


def _validated_off(raw: list[str]) -> frozenset[str]:
    off: set[str] = set()
    for entry in raw:
        kind, _, channel = entry.partition(":")
        spec = KIND_BY_KEY.get(kind)
        if spec is None or channel not in spec.channels:
            raise _refuse(
                "alert_cell_unknown",
                "That alert is not on the list",
                f"There is no alert for {entry!r}.",
            )
        if spec.always:
            raise _refuse(
                "alert_always_on",
                "This alert is always on",
                f"{spec.label} cannot be switched off. {spec.why or ''}".strip(),
            )
        off.add(entry)
    return frozenset(off)


async def save(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    may_manage: bool,
    payload: AlertPreferencesIn,
) -> AlertPreferencesOut:
    """Write this person's row. The account cells and the quiet hours and cap are taken only
    from the governing owner; anyone else changing them is refused rather than ignored."""
    if payload.quiet_start_hour == payload.quiet_end_hour:
        raise _refuse(
            "alert_quiet_hours_empty",
            "Quiet hours need a start and an end",
            "Quiet hours cannot start and end at the same hour.",
        )
    wanted = _validated_off(payload.off)
    current = await read_for(session, user_id)
    owner = await governing_user(session)
    editable = user_id == owner and may_manage
    account_cells = {c for c in wanted | current.off if c.rpartition(":")[2] in ACCOUNT_CHANNELS}
    changes_account = (
        {c for c in wanted if c in account_cells} != {c for c in current.off if c in account_cells}
        or payload.quiet_enabled != current.quiet_enabled
        or (payload.quiet_start_hour, payload.quiet_end_hour, payload.daily_cap)
        != (current.quiet_start_hour, current.quiet_end_hour, current.daily_cap)
    )
    if changes_account and not editable:
        raise ProblemError(
            kind="permission",
            code="alert_owner_only",
            title="Only the owner can change this",
            detail="Email, WhatsApp, quiet hours and the daily limit are set by the account owner.",
            remediation="Ask the owner, or change only your bell and computer alerts.",
        )
    await session.execute(
        text(
            "INSERT INTO notification_preferences (id, tenant_id, user_id, off, quiet_enabled, "
            "quiet_start_hour, quiet_end_hour, daily_cap, created_at, updated_at) VALUES "
            "(:id, :tid, :uid, CAST(:off AS jsonb), :qe, :qs, :qx, :cap, now(), now()) "
            "ON CONFLICT (tenant_id, user_id) DO UPDATE SET off = EXCLUDED.off, "
            "quiet_enabled = EXCLUDED.quiet_enabled, quiet_start_hour = EXCLUDED.quiet_start_hour, "
            "quiet_end_hour = EXCLUDED.quiet_end_hour, daily_cap = EXCLUDED.daily_cap, "
            "updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "uid": user_id,
            "off": json.dumps(sorted(wanted)),
            "qe": payload.quiet_enabled,
            "qs": payload.quiet_start_hour,
            "qx": payload.quiet_end_hour,
            "cap": payload.daily_cap,
        },
    )
    return await view(session, user_id=user_id, may_manage=may_manage)


# --- the gate --------------------------------------------------------------------------

Decision = Literal["send", "held", "folded", "off", "released"]
#: A stored answer as the gate gives it again to a retried job.
_EARLIER: Final[dict[str, Decision]] = {
    "sent": "send",
    "held": "held",
    "folded": "folded",
    "released": "released",
}


def _fold_until(now: datetime) -> datetime:
    """The end of this IST day; the release sweep then waits out quiet hours if they are on."""
    return ist_day_start(now) + timedelta(days=1)


async def gate(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: str,
    channel: Literal["email", "whatsapp"],
    dedupe_key: str,
    title: str,
    href: str | None = None,
    ref: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Decision:
    """What to do with one owner alert on one channel. Call inside the job's transaction."""
    at = now or datetime.now(UTC)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"alerts:{tenant_id}:{channel}"},
    )
    existing = (
        await session.execute(
            text(
                "SELECT state FROM notification_deliveries "
                "WHERE channel = :ch AND dedupe_key = :key"
            ),
            {"ch": channel, "key": dedupe_key},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _EARLIER[str(existing)]
    prefs = await governing(session)
    spec = KIND_BY_KEY.get(kind)
    always = spec is None or spec.always
    if not prefs.allows(kind, channel):
        return "off"
    state: Literal["sent", "held", "folded"] = "sent"
    due: datetime | None = None
    if not always and prefs.quiet_at(at):
        state, due = "held", prefs.quiet_ends(at)
    elif not always and channel == "email":
        sent_today = (
            await session.execute(
                text(
                    "SELECT count(*) FROM notification_deliveries WHERE channel = 'email' "
                    "AND state = 'sent' AND created_at >= :since"
                ),
                {"since": ist_day_start(at)},
            )
        ).scalar_one()
        if int(sent_today) >= prefs.daily_cap:
            state, due = "folded", _fold_until(at)
    await session.execute(
        text(
            "INSERT INTO notification_deliveries (id, tenant_id, kind, channel, dedupe_key, "
            "state, title, href, ref, due_at, created_at, updated_at) VALUES (:id, :tid, :kind, "
            ":ch, :key, :state, :title, :href, CAST(:ref AS jsonb), :due, :at, :at)"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "kind": kind,
            "ch": channel,
            "key": dedupe_key,
            "state": state,
            "title": title,
            "href": href,
            "ref": None if ref is None else json.dumps(ref),
            "due": due,
            "at": at,
        },
    )
    return "send" if state == "sent" else state


async def post_bell(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: str,
    dedupe_key: str,
    title: str,
    detail: str | None = None,
    href: str | None = None,
    at: datetime | None = None,
) -> bool:
    """Put one item on every bell of the account, once per `dedupe_key`. Whether a person
    sees it is their bell cell for `kind`, read by the feed. True when it was new."""
    inserted = (
        await session.execute(
            text(
                "INSERT INTO notification_deliveries (id, tenant_id, kind, channel, dedupe_key, "
                "state, title, detail, href, created_at, updated_at) VALUES (:id, :tid, :kind, "
                "'bell', :key, 'sent', :title, :detail, :href, :at, :at) "
                "ON CONFLICT (tenant_id, channel, dedupe_key) DO NOTHING RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "kind": kind,
                "key": dedupe_key,
                "title": title,
                "detail": detail,
                "href": href,
                "at": at or datetime.now(UTC),
            },
        )
    ).scalar_one_or_none()
    return inserted is not None


__all__ = [
    "ACCOUNT_CHANNELS",
    "ATTENTION_KIND",
    "CHANNELS",
    "KINDS",
    "KIND_BY_KEY",
    "AlertKind",
    "AlertKindOut",
    "AlertPreferencesIn",
    "AlertPreferencesOut",
    "Decision",
    "Preferences",
    "cell",
    "gate",
    "governing",
    "governing_user",
    "ist_day_start",
    "post_bell",
    "read_for",
    "save",
    "view",
]
