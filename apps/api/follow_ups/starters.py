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

from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.business_outcomes import BusinessOutcome
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.call_outcomes import outcomes_in_use
from apps.api.follow_ups import definition as d

NIL: Final = UUID(int=0)
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


def _date_fields(rows: list[Any]) -> tuple[DateField, ...]:
    seen: dict[str, DateField] = {}
    for (fields,) in rows:
        for item in fields if isinstance(fields, list) else []:
            if not isinstance(item, dict) or item.get("type") != "date":
                continue
            key, label = item.get("key"), item.get("label")
            if isinstance(key, str) and isinstance(label, str) and key not in seen:
                seen[key] = DateField(key=key, label=" ".join(label.split()))
    return tuple(seen.values())


def _payment_field(fields: tuple[DateField, ...]) -> DateField | None:
    return next(
        (f for f in fields if any(word in f.label.lower() for word in _PAYMENT_WORDS)), None
    )


async def _first(session: AsyncSession, sql: str) -> UUID | None:
    value = (await session.execute(text(sql))).scalar()
    return UUID(str(value)) if value is not None else None


async def _account(session: AsyncSession) -> _Account:
    agent = await _first(
        session,
        "SELECT id FROM agents WHERE deleted_at IS NULL AND archived_at IS NULL "
        "AND direction IN ('outbound', 'both') AND engine_agent_ref IS NOT NULL "
        "ORDER BY created_at LIMIT 1",
    )
    raw_outcomes = (
        await session.execute(
            text("SELECT business_outcomes FROM agents WHERE id = :aid"), {"aid": agent}
        )
    ).scalar()
    fields = (
        await session.execute(
            text(
                "SELECT es.fields FROM agents a "
                "JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                "WHERE a.deleted_at IS NULL AND a.archived_at IS NULL "
                "ORDER BY a.created_at, a.id LIMIT 50"
            )
        )
    ).all()
    return _Account(
        agent=agent,
        outcomes=tuple(outcomes_in_use(raw_outcomes)[0]),
        date_fields=_date_fields(list(fields)),
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
            trigger=d.CallEndedTrigger(kind="call_ended", calls="inbound", outcomes=["missed"]),
            steps=_steps(
                [
                    {"id": "s1", "kind": "wait", "minutes": 5, "next": "s2"},
                    {
                        "id": "s2",
                        "kind": "call",
                        "agent_id": agent,
                        "next": {"answered": "s3"},
                    },
                    {"id": "s3", "kind": "decide", "on": {"answered": None}},
                ]
            ),
            settings=d.Settings(goal="answered"),
            available=True,
            needs=needs("outbound_agent"),
        ),
    ]


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


__all__ = [
    "NIL",
    "NOT_INTERESTED",
    "DateField",
    "Starter",
    "build",
    "for_account",
    "interested_keys",
]
