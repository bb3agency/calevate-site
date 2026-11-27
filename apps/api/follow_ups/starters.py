"""The ready-made Follow-ups (docs/FOLLOW-UPS.md, Starters), filled in for one account.

Filled with what the account already has: its first agent that places calls, its first
approved WhatsApp message, its owner for "give the lead to". Whatever it lacks is listed in
`needs` and left as the nil id, which `service.problems_of` reports at publish, so a starter
is always a valid draft and never a silent guess.

THE BRANCHES FOLLOW THE AGENT'S OWN OUTCOMES (D-836). "Qualify new leads" hands over every
outcome of that agent that moves a lead to interested or hot, whatever it is called, rather
than the fixed key `interested` a business's own outcomes rarely use. A reminder starter
exists only when an agent's lead details hold a date to remind about: a reminder keyed on a
field nobody captures never runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.call_outcomes import outcomes_in_use
from apps.api.campaigns.notes import account_fields
from apps.api.follow_ups import definition as d
from apps.api.follow_ups.models import MAX_NAME_CHARS

NIL: Final = UUID(int=0)
#: The platform outcome of a call that never connected (`crm/outcomes`, rule 1).
MISSED: Final = "missed"
MISSED_CALL_STARTER: Final = "missed_call_callback"
Need = Literal["outbound_agent", "whatsapp_template"]


@dataclass(frozen=True, slots=True)
class Starter:
    key: str
    name: str
    description: str
    trigger: d.AnyTrigger
    steps: list[d.AnyStep]
    settings: d.Settings
    available: bool
    needs: list[Need]


#: The outcome a lead who said no lands on: the starting set's key, which a drafted list keeps
#: when it has one.
NOT_INTERESTED: Final = "not_interested"
#: A date detail whose label says this is when a payment falls due.
_PAYMENT_WORDS: Final = ("pay", "due", "instal", "emi")


@dataclass(frozen=True, slots=True)
class DateField:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class _Account:
    agent: UUID | None
    template: UUID | None
    owner: UUID | None
    has_call_new_leads: bool
    #: The outcomes of the agent the starters call with (the starting set without one).
    outcomes: tuple[BusinessOutcome, ...] = ()
    #: The date details the account's agents capture, in agent order.
    date_fields: tuple[DateField, ...] = ()


def interested_keys(outcomes: tuple[BusinessOutcome, ...]) -> list[str]:
    """The outcome keys that hand a lead to the team: each that moves it to interested or
    hot, and the voice platform's own `interested` reading, which the decide step also
    matches (`runner._decide`)."""
    keys = [o.key for o in outcomes if o.lead_status in ("interested", "hot")]
    return keys if "interested" in keys else [*keys, "interested"]


def _date_fields(fields: list[ExtractionField]) -> tuple[DateField, ...]:
    return tuple(
        DateField(key=f.key, label=" ".join(f.label.split())) for f in fields if f.type == "date"
    )


def _payment_field(fields: tuple[DateField, ...]) -> DateField | None:
    return next(
        (f for f in fields if any(word in f.label.lower() for word in _PAYMENT_WORDS)), None
    )


async def _first(session: AsyncSession, sql: str) -> UUID | None:
    value = (await session.execute(text(sql))).scalar()
    return UUID(str(value)) if value is not None else None


async def _account(session: AsyncSession) -> _Account:
    from apps.api.agents.dial_through import holder_resolves_sql

    # The oldest calling agent a follow-up's call can be placed through (D-1019).
    agent = await _first(
        session,
        "SELECT id FROM agents WHERE deleted_at IS NULL AND archived_at IS NULL "
        f"AND direction IN ('outbound', 'both') AND {holder_resolves_sql('agents')} "
        "ORDER BY created_at LIMIT 1",
    )
    raw_outcomes = (
        await session.execute(
            text("SELECT business_outcomes FROM agents WHERE id = :aid"), {"aid": agent}
        )
    ).scalar()
    # The dates the account's campaigns and lines note (D-1028).
    noted = await account_fields(session)
    return _Account(
        agent=agent,
        outcomes=tuple(outcomes_in_use(raw_outcomes)[0]),
        date_fields=_date_fields(noted),
        template=await _first(
            session,
            "SELECT id FROM whatsapp_templates WHERE status = 'approved' ORDER BY name LIMIT 1",
        ),
        owner=await _first(
            session,
            "SELECT m.user_id FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.role = 'owner' AND u.deactivated_at IS NULL ORDER BY m.created_at LIMIT 1",
        ),
        has_call_new_leads=(
            await session.execute(
                text("SELECT 1 FROM follow_ups WHERE starter = 'call_new_leads' LIMIT 1")
            )
        ).first()
        is not None,
    )


def _steps(raw: list[dict[str, Any]]) -> list[d.AnyStep]:
    return d.load_steps(raw)


def build(account: _Account) -> list[Starter]:
    return [
        *_lead_starters(account),
        *_reminders(account),
    ]


def _lead_starters(account: _Account) -> list[Starter]:
    agent = str(account.agent or NIL)
    template = str(account.template or NIL)
    owner = str(account.owner or NIL)
    blank = [{"source": "lead_name"}]

    def needs(*kinds: Need) -> list[Need]:
        return _needs(account, *kinds)

    decide: dict[str, str] = dict.fromkeys(interested_keys(account.outcomes), "s3")
    decide["call_back_booked"] = "s5"
    decide[NOT_INTERESTED] = "s7"

    return [
        Starter(
            key="call_new_leads",
            name="Call new leads",
            description="Call every new lead as soon as it arrives.",
            trigger=d.NewLeadTrigger(kind="new_lead"),
            steps=_steps([{"id": "s1", "kind": "call", "agent_id": agent}]),
            settings=d.Settings(),
            available=not account.has_call_new_leads,
            needs=needs("outbound_agent"),
        ),
        Starter(
            key="qualify_new_leads",
            name="Qualify new leads",
            description=(
                "Call new leads, hand the interested ones to your team, call back those who "
                "ask, and send a WhatsApp to those we could not reach."
            ),
            trigger=d.NewLeadTrigger(kind="new_lead"),
            steps=_steps(
                [
                    {
                        "id": "s1",
                        "kind": "call",
                        "agent_id": agent,
                        "next": {"answered": "s2", "not_reached": "s8"},
                    },
                    {"id": "s2", "kind": "decide", "on": decide},
                    {"id": "s3", "kind": "assign", "user_id": owner, "next": "s4"},
                    {"id": "s4", "kind": "tell_team", "why": "An interested lead", "next": "s9"},
                    {"id": "s5", "kind": "wait", "days": 1, "next": "s6"},
                    {"id": "s6", "kind": "call", "agent_id": agent},
                    {"id": "s7", "kind": "set_status", "status": "lost"},
                    {"id": "s8", "kind": "whatsapp", "template_id": template, "values": blank},
                    {"id": "s9", "kind": "end", "goal": True},
                ]
            ),
            settings=d.Settings(),
            available=True,
            needs=needs("outbound_agent", "whatsapp_template"),
        ),
        Starter(
            key="missed_call_callback",
            name="Call back missed calls",
            description="Five minutes after a call you missed, call them back.",
            trigger=d.CallEndedTrigger(kind="call_ended", calls="inbound", outcomes=[MISSED]),
            steps=_missed_call_steps(agent),
            settings=d.Settings(goal="answered"),
            available=True,
            needs=needs("outbound_agent"),
        ),
    ]


def _missed_call_steps(agent: str) -> list[d.AnyStep]:
    """Five minutes after the missed call, one call back (no retries). The call step books a
    call-back that the call-back tick dials through the dispatch gate, inside the account's
    calling hours, like every other call (`runner` module docstring)."""
    return _steps(
        [
            {"id": "s1", "kind": "wait", "minutes": 5, "next": "s2"},
            {"id": "s2", "kind": "call", "agent_id": agent, "next": {"answered": "s3"}},
            {"id": "s3", "kind": "decide", "on": {"answered": None}},
        ]
    )


def _needs(account: _Account, *kinds: Need) -> list[Need]:
    have: dict[Need, bool] = {
        "outbound_agent": account.agent is not None,
        "whatsapp_template": account.template is not None,
    }
    return [k for k in kinds if not have[k]]


def _reminder(
    account: _Account, *, key: str, name: str, description: str, field: DateField, **when: Any
) -> Starter:
    agent = str(account.agent or NIL)
    template = str(account.template or NIL)
    offset, at, wait = when["offset_days"], when["at"], when["wait"]
    return Starter(
        key=key,
        name=name,
        description=description,
        trigger=d.LeadDateTrigger(kind="lead_date", field=field.key, offset_days=offset, at=at),
        steps=_steps(
            [
                {
                    "id": "s1",
                    "kind": "whatsapp",
                    "template_id": template,
                    "values": [{"source": "lead_name"}],
                    "next": {"sent": "s2", "not_sent": "s2"},
                },
                {"id": "s2", "kind": "wait", **wait, "next": "s3"},
                {"id": "s3", "kind": "call", "agent_id": agent},
            ]
        ),
        settings=d.Settings(),
        available=True,
        needs=_needs(account, "outbound_agent", "whatsapp_template"),
    )


def _reminders(account: _Account) -> list[Starter]:
    """A reminder per kind of date the agents capture: a payment date gets the payment
    reminder, any other date the reminder before it. None without a date detail."""
    payment = _payment_field(account.date_fields)
    other = next((f for f in account.date_fields if f != payment), None)
    out: list[Starter] = []
    if other is not None:
        out.append(
            _reminder(
                account,
                key="appointment_reminder",
                name=f"{other.label} reminder",
                description=(
                    f"The day before the {other.label.lower()}, send a reminder; three hours "
                    "later, call."
                ),
                field=other,
                offset_days=-1,
                at="10:00",
                wait={"hours": 3},
            )
        )
    if payment is not None:
        out.append(
            _reminder(
                account,
                key="payment_reminder",
                name="Payment reminder",
                description=(
                    f"Two days before the {payment.label.lower()}, send a reminder; a day "
                    "later, call."
                ),
                field=payment,
                offset_days=-2,
                at="11:00",
                wait={"days": 1},
            )
        )
    return out


async def for_account(session: AsyncSession) -> list[Starter]:
    return build(await _account(session))


# --- one inbound line's "call back missed callers" switch ------------------------------
#
# The line page's switch is this account's `missed_call_callback` Follow-up narrowed to the
# line (`CallEndedTrigger.inbound_line_ids`). It is a Follow-up like any other, listed on
# Follow-ups with its runs, rather than a second mechanism beside them: its call books a
# call-back that the call-back tick dials through the dispatch gate, so Do not call,
# calling hours and the pacing rules apply exactly as they do to every call.
#
# No column names the line, so the row is found by its trigger and a double press is
# serialised by an advisory lock on the line rather than by a unique index.

LineCallBackState = Literal["on", "off", "covered", "cannot"]

_LINE_FOLLOW_UP_SQL: Final = (
    "SELECT id FROM follow_ups WHERE starter = :starter "
    "AND trigger->'inbound_line_ids' @> CAST(:line AS jsonb) "
    "ORDER BY created_at, id LIMIT 1"
)


@dataclass(frozen=True, slots=True)
class LineCallBack:
    #: `covered`: a live Follow-up made on Follow-ups already rings this line's missed
    #: callers back. `cannot`: no agent of the account can place the call.
    state: LineCallBackState
    #: The line's own Follow-up, once one was made.
    follow_up_id: UUID | None
    covered_by: UUID | None = None
    covered_by_name: str | None = None


def line_call_back_definition(
    *, line_id: UUID, agent_id: UUID
) -> tuple[d.CallEndedTrigger, list[d.AnyStep], d.Settings]:
    trigger = d.CallEndedTrigger(
        kind="call_ended", calls="inbound", outcomes=[MISSED], inbound_line_ids=[line_id]
    )
    return trigger, _missed_call_steps(str(agent_id)), d.Settings(goal="answered")


async def _line(session: AsyncSession, line_id: UUID) -> tuple[UUID, str]:
    from apps.api.core.errors import ProblemError

    row = (
        await session.execute(
            text(
                "SELECT agent_id, name FROM inbound_lines WHERE id = :lid AND archived_at IS NULL"
            ),
            {"lid": line_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Inbound line")
    return UUID(str(row[0])), str(row[1])


async def _own(session: AsyncSession, line_id: UUID) -> UUID | None:
    found = (
        await session.execute(
            text(_LINE_FOLLOW_UP_SQL),
            {"starter": MISSED_CALL_STARTER, "line": json.dumps([str(line_id)])},
        )
    ).scalar()
    return UUID(str(found)) if found is not None else None


async def line_calling_agent(session: AsyncSession, line_agent_id: UUID) -> UUID | None:
    """Who rings the line's missed callers back: the line's own voice when it can place
    calls, else the account's oldest agent that can (the starters' choice)."""
    from apps.api.agents.dial_through import holder_resolves_sql

    value = (
        await session.execute(
            text(
                "SELECT id FROM agents WHERE deleted_at IS NULL AND archived_at IS NULL "
                f"AND direction IN ('outbound', 'both') AND {holder_resolves_sql('agents')} "
                "ORDER BY (id = :aid) DESC, created_at LIMIT 1"
            ),
            {"aid": line_agent_id},
        )
    ).scalar()
    return UUID(str(value)) if value is not None else None


def _covers(trigger: d.AnyTrigger, *, line_id: UUID, agent_id: UUID) -> bool:
    """A live trigger that starts on EVERY missed call this line takes. One narrowed by a
    condition (`only_if`, campaigns) might not, so it is never said to cover the line."""
    return (
        isinstance(trigger, d.CallEndedTrigger)
        and trigger.calls in ("inbound", "both")
        and (trigger.outcomes is None or MISSED in trigger.outcomes)
        and trigger.campaign_ids is None
        and trigger.only_if is None
        and (trigger.inbound_line_ids is None or line_id in trigger.inbound_line_ids)
        and (trigger.agent_ids is None or agent_id in trigger.agent_ids)
    )


async def line_call_back(session: AsyncSession, line_id: UUID) -> LineCallBack:
    """The switch's real state, read from the live Follow-ups rather than remembered."""
    from apps.api.follow_ups import runner

    agent_id, _name = await _line(session, line_id)
    own = await _own(session, line_id)
    covering = [
        f
        for f in await runner.live_follow_ups(session, "call_ended")
        if _covers(f.trigger, line_id=line_id, agent_id=agent_id)
    ]
    if own is not None and any(f.id == own for f in covering):
        return LineCallBack(state="on", follow_up_id=own)
    if covering:
        other = covering[0].id
        name = (
            await session.execute(
                text("SELECT name FROM follow_ups WHERE id = :fid"), {"fid": other}
            )
        ).scalar()
        return LineCallBack(
            state="covered", follow_up_id=own, covered_by=other, covered_by_name=str(name)
        )
    if await line_calling_agent(session, agent_id) is None:
        return LineCallBack(state="cannot", follow_up_id=own)
    return LineCallBack(state="off", follow_up_id=own)


async def set_line_call_back(
    session: AsyncSession, *, tenant_id: UUID, line_id: UUID, on: bool, user_id: UUID | None
) -> LineCallBack:
    """On: make the line's Follow-up, or put the one made before back on, published. Off:
    turn it off, which also stops the call-backs it booked. A Follow-up covering the whole
    account is left alone: one line's switch cannot turn the account's off."""
    from apps.api.core.errors import ProblemError
    from apps.api.follow_ups import service

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"line-missed-call-back:{line_id}"},
    )
    agent_id, line_name = await _line(session, line_id)
    own = await _own(session, line_id)
    if not on:
        if own is not None and (await service.get(session, own, lock=True)).status in (
            "live",
            "paused",
        ):
            await service.turn_off(session, own)
        return await line_call_back(session, line_id)
    caller = await line_calling_agent(session, agent_id)
    if caller is None:
        raise ProblemError.business_rule(
            "line_call_back_no_caller",
            "None of your agents can place calls yet, so nobody can call them back.",
            remediation="Let an agent place calls, then switch this on.",
        )
    if own is None:
        trigger, steps, settings = line_call_back_definition(line_id=line_id, agent_id=caller)
        row = await service.create(
            session,
            tenant_id=tenant_id,
            name=" ".join(f"Call back missed calls: {line_name}".split())[:MAX_NAME_CHARS],
            trigger=trigger,
            steps=steps,
            settings=settings,
            starter=MISSED_CALL_STARTER,
            user_id=user_id,
        )
    else:
        row = await service.get(session, own, lock=True)
    if row.has_unpublished_changes:
        row = await service.publish(
            session,
            row.id,
            tenant_id=tenant_id,
            expected_updated_at=row.updated_at,
            user_id=user_id,
        )
    if row.status in ("paused", "off"):
        await service.resume(session, row.id, tenant_id=tenant_id)
    return await line_call_back(session, line_id)


async def default_line_call_back(
    session: AsyncSession, *, tenant_id: UUID, line_id: UUID, user_id: UUID | None
) -> bool:
    """A NEW line starts with its switch on when an agent can place the calls (decided for
    lines made from release 0.5.99 on; lines made before keep what they had, so no live
    account starts ringing people back unasked). Inside a savepoint, so a line that cannot
    have it yet is still made, with the switch off and saying why."""
    from apps.api.core.errors import ProblemError

    try:
        async with session.begin_nested():
            state = await set_line_call_back(
                session, tenant_id=tenant_id, line_id=line_id, on=True, user_id=user_id
            )
    except ProblemError:
        return False
    return state.state == "on"


__all__ = [
    "MISSED",
    "MISSED_CALL_STARTER",
    "NIL",
    "NOT_INTERESTED",
    "DateField",
    "LineCallBack",
    "Starter",
    "build",
    "default_line_call_back",
    "for_account",
    "interested_keys",
    "line_call_back",
    "line_call_back_definition",
    "line_calling_agent",
    "set_line_call_back",
]
