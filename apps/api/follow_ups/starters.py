"""The ready-made Follow-ups (docs/FOLLOW-UPS.md, Starters), filled in for one account.

Filled with what the account already has: its first agent that places calls, its first
approved WhatsApp message, its owner for "give the lead to". Whatever it lacks is listed in
`needs` and left as the nil id, which `service.problems_of` reports at publish, so a starter
is always a valid draft and never a silent guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.follow_ups import definition as d

NIL: Final = UUID(int=0)
Need = Literal["outbound_agent", "whatsapp_template", "team_address"]


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


@dataclass(frozen=True, slots=True)
class _Account:
    agent: UUID | None
    template: UUID | None
    owner: UUID | None
    has_team_address: bool
    has_call_new_leads: bool


async def _first(session: AsyncSession, sql: str) -> UUID | None:
    value = (await session.execute(text(sql))).scalar()
    return UUID(str(value)) if value is not None else None


async def _account(session: AsyncSession) -> _Account:
    return _Account(
        agent=await _first(
            session,
            "SELECT id FROM agents WHERE deleted_at IS NULL AND archived_at IS NULL "
            "AND direction IN ('outbound', 'both') AND engine_agent_ref IS NOT NULL "
            "ORDER BY created_at LIMIT 1",
        ),
        template=await _first(
            session,
            "SELECT id FROM whatsapp_templates WHERE status = 'approved' ORDER BY name LIMIT 1",
        ),
        owner=await _first(
            session,
            "SELECT m.user_id FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.role = 'owner' AND u.deactivated_at IS NULL ORDER BY m.created_at LIMIT 1",
        ),
        has_team_address=(
            await session.execute(
                text(
                    "SELECT 1 FROM team_alert_contacts WHERE is_default AND removed_at IS NULL "
                    "AND verified_at IS NOT NULL LIMIT 1"
                )
            )
        ).first()
        is not None,
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
    agent = str(account.agent or NIL)
    template = str(account.template or NIL)
    owner = str(account.owner or NIL)
    blank = [{"source": "lead_name"}]

    def needs(*kinds: Need) -> list[Need]:
        have: dict[Need, bool] = {
            "outbound_agent": account.agent is not None,
            "whatsapp_template": account.template is not None,
            "team_address": account.has_team_address,
        }
        return [k for k in kinds if not have[k]]

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
                    {
                        "id": "s2",
                        "kind": "decide",
                        "on": {
                            "interested": "s3",
                            "call_back_booked": "s5",
                            "not_interested": "s7",
                        },
                    },
                    {"id": "s3", "kind": "assign", "user_id": owner, "next": "s4"},
                    {"id": "s4", "kind": "tell_team", "why": "An interested lead"},
                    {"id": "s5", "kind": "wait", "days": 1, "next": "s6"},
                    {"id": "s6", "kind": "call", "agent_id": agent},
                    {"id": "s7", "kind": "set_status", "status": "lost"},
                    {"id": "s8", "kind": "whatsapp", "template_id": template, "values": blank},
                ]
            ),
            settings=d.Settings(goal="interested"),
            available=True,
            needs=needs("outbound_agent", "whatsapp_template", "team_address"),
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
        Starter(
            key="appointment_reminder",
            name="Appointment reminder",
            description="The day before a visit, send a reminder; three hours later, call.",
            trigger=d.LeadDateTrigger(
                kind="lead_date", field="visit_date", offset_days=-1, at="10:00"
            ),
            steps=_steps(
                [
                    {
                        "id": "s1",
                        "kind": "whatsapp",
                        "template_id": template,
                        "values": blank,
                        "next": {"sent": "s2", "not_sent": "s2"},
                    },
                    {"id": "s2", "kind": "wait", "hours": 3, "next": "s3"},
                    {"id": "s3", "kind": "call", "agent_id": agent},
                ]
            ),
            settings=d.Settings(),
            available=True,
            needs=needs("outbound_agent", "whatsapp_template"),
        ),
        Starter(
            key="payment_reminder",
            name="Payment reminder",
            description="Two days before a payment is due, send a reminder; a day later, call.",
            trigger=d.LeadDateTrigger(
                kind="lead_date", field="due_date", offset_days=-2, at="11:00"
            ),
            steps=_steps(
                [
                    {
                        "id": "s1",
                        "kind": "whatsapp",
                        "template_id": template,
                        "values": blank,
                        "next": {"sent": "s2", "not_sent": "s2"},
                    },
                    {"id": "s2", "kind": "wait", "days": 1, "next": "s3"},
                    {"id": "s3", "kind": "call", "agent_id": agent},
                ]
            ),
            settings=d.Settings(),
            available=True,
            needs=needs("outbound_agent", "whatsapp_template"),
        ),
        Starter(
            key="win_back",
            name="Win back old leads",
            description="Call leads you pick; send a WhatsApp to those not interested yet.",
            trigger=d.ManualTrigger(kind="manual"),
            steps=_steps(
                [
                    {
                        "id": "s1",
                        "kind": "call",
                        "agent_id": agent,
                        "next": {"answered": "s2", "not_reached": "s3"},
                    },
                    {"id": "s2", "kind": "decide", "on": {"interested": None}, "other": "s3"},
                    {"id": "s3", "kind": "whatsapp", "template_id": template, "values": blank},
                ]
            ),
            settings=d.Settings(goal="interested"),
            available=True,
            needs=needs("outbound_agent", "whatsapp_template"),
        ),
    ]


async def for_account(session: AsyncSession) -> list[Starter]:
    return build(await _account(session))


__all__ = ["NIL", "Starter", "build", "for_account"]
