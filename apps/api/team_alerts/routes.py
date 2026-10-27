"""Tell my team (D-904), as endpoints.

    GET    /v1/team-alerts/contacts                    the team addresses
    POST   /v1/team-alerts/contacts                    add one; a code is mailed to it (owner)
    POST   /v1/team-alerts/contacts/{id}/code          mail a new code (owner)
    POST   /v1/team-alerts/contacts/{id}/verify        enter the code (owner)
    POST   /v1/team-alerts/contacts/{id}/default       the address agents use by default (owner)
    DELETE /v1/team-alerts/contacts/{id}               stop sending there (owner)
    GET    /v1/agents/{agent_id}/team-alert            when this agent tells the team
    PUT    /v1/agents/{agent_id}/team-alert            set it (owner)

Every write is `org:manage`: these choose who outside the dashboard receives a customer's full
number, which is the owner's decision.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.team_alerts import service
from apps.api.team_alerts import whatsapp as team_whatsapp
from apps.api.team_alerts.service import MAX_FIELD_TRIGGERS, FieldTrigger, Rule, RuleView

Session = Annotated[AsyncSession, Depends(db)]
OrgReader = Annotated[Principal, Depends(requires("org:read"))]
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]

router = APIRouter(tags=["team-alerts"])

_EMAIL: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)

_VALUE_MAX = 200
_VALUES_MAX = 50
_OUTCOMES_MAX = 50


Channel = Literal["email", "whatsapp"]
Slot = Literal["name", "phone", "why", "link"]


class TeamContactOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    channel: Channel
    #: The team's own email address or WhatsApp number, which the owner typed.
    address: str
    is_default: bool
    verified: bool
    #: WhatsApp only: the client's own connection it is sent through; null once that
    #: connection is deleted, and then nothing is sent there.
    whatsapp_account_id: UUID | None


class TeamWhatsAppAccountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    label: str


class TeamContactsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contacts: list[TeamContactOut]
    max_contacts: int
    #: The client's own WhatsApp connections. Empty: WhatsApp is not offered.
    whatsapp_accounts: list[TeamWhatsAppAccountOut]


class TeamWhatsAppIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    template: str = Field(min_length=1, max_length=512)
    language: str | None = Field(default=None, max_length=16)
    phone_number_id: str | None = Field(default=None, max_length=64, pattern=r"^[0-9]*$")
    #: What fills the template's body variables {{1}}, {{2}}, ... in order.
    body_values: list[Slot] = Field(min_length=3, max_length=4)


class TeamContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Channel = "email"
    #: An email address, or for WhatsApp the team's number with its country code.
    address: str = Field(min_length=3, max_length=254)
    whatsapp: TeamWhatsAppIn | None = None

    @model_validator(mode="after")
    def _shape(self) -> TeamContactIn:
        if self.channel == "email":
            try:
                self.address = str(_EMAIL.validate_python(self.address))
            except ValidationError as exc:
                raise ValueError("enter one email address your team reads") from exc
            if self.whatsapp is not None:
                raise ValueError("an email address takes no WhatsApp set-up")
        elif self.whatsapp is None:
            raise ValueError("a WhatsApp number needs the account and template to send through")
        return self


class TeamCodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=4, max_length=12)


class FieldTriggerIO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=40)
    values: list[str] = Field(min_length=1, max_length=_VALUES_MAX)


class TeamAlertChoiceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    values: list[str]


class TeamAlertRuleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Null follows the account's default address.
    contact_id: UUID | None
    on_outcomes: list[str]
    on_fields: list[FieldTriggerIO]
    in_call: bool
    #: The verified address alerts go to now; null when none does, so nothing is sent.
    sends_to: UUID | None
    #: Whether the agent can tell the team during a call now.
    in_call_live: bool
    outcomes: list[TeamAlertChoiceOut]
    fields: list[TeamAlertChoiceOut]


class TeamAlertRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_id: UUID | None = None
    on_outcomes: list[Annotated[str, Field(max_length=_VALUE_MAX)]] = Field(
        default_factory=list, max_length=_OUTCOMES_MAX
    )
    on_fields: list[FieldTriggerIO] = Field(default_factory=list, max_length=MAX_FIELD_TRIGGERS)
    in_call: bool = False


def _contact_out(contact: service.Contact) -> TeamContactOut:
    return TeamContactOut(
        id=contact.id,
        channel="whatsapp" if contact.channel == "whatsapp" else "email",
        address=contact.address,
        is_default=contact.is_default,
        verified=contact.verified,
        whatsapp_account_id=contact.whatsapp_account_id,
    )


def _rule_out(view: RuleView) -> TeamAlertRuleOut:
    return TeamAlertRuleOut(
        contact_id=view.rule.contact_id,
        on_outcomes=list(view.rule.on_outcomes),
        on_fields=[FieldTriggerIO(key=f.key, values=list(f.values)) for f in view.rule.on_fields],
        in_call=view.rule.in_call,
        sends_to=view.sends_to,
        in_call_live=view.in_call_live,
        outcomes=[TeamAlertChoiceOut(key=o.key, label=o.label, values=[]) for o in view.outcomes],
        fields=[
            TeamAlertChoiceOut(key=f.key, label=f.label, values=list(f.values)) for f in view.fields
        ],
    )


async def _contacts_out(session: AsyncSession) -> TeamContactsOut:
    return TeamContactsOut(
        contacts=[_contact_out(c) for c in await service.list_contacts(session)],
        max_contacts=service.MAX_CONTACTS,
        whatsapp_accounts=[
            TeamWhatsAppAccountOut(id=a.id, label=a.label)
            for a in await team_whatsapp.accounts(session)
        ],
    )


async def _audit(
    session: AsyncSession, request: Request, principal: Principal, action: str, object_id: str
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="team_alert_contact",
        object_id=object_id,
        ip=client_request_ip(request),
    )


@router.get(
    "/v1/team-alerts/contacts",
    response_model=TeamContactsOut,
    openapi_extra=permission_meta("org:read"),
    summary="The team addresses that may be told about a caller",
)
async def list_team_contacts(session: Session, _: OrgReader) -> TeamContactsOut:
    return await _contacts_out(session)


@router.post(
    "/v1/team-alerts/contacts",
    response_model=TeamContactsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Add a team address; a six-digit code is emailed to it",
)
async def add_team_contact(
    payload: TeamContactIn, session: Session, request: Request, principal: Owner
) -> TeamContactsOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    setup = (
        service.WhatsAppSetup(
            credential_id=payload.whatsapp.account_id,
            template=payload.whatsapp.template,
            values=tuple(payload.whatsapp.body_values),
            language=payload.whatsapp.language,
            number_id=payload.whatsapp.phone_number_id,
        )
        if payload.whatsapp is not None
        else None
    )
    contact = await service.add_contact(
        session,
        tenant_id=principal.tenant_id,
        address=payload.address,
        channel=payload.channel,
        whatsapp=setup,
    )
    await _audit(session, request, principal, "team_alert.contact_added", str(contact.id))
    return await _contacts_out(session)


@router.post(
    "/v1/team-alerts/contacts/{contact_id}/code",
    response_model=TeamContactsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Email a new code to a team address",
)
async def resend_team_code(
    contact_id: UUID, session: Session, request: Request, principal: Owner
) -> TeamContactsOut:
    assert principal.tenant_id is not None
    await service.resend_code(session, tenant_id=principal.tenant_id, contact_id=contact_id)
    await _audit(session, request, principal, "team_alert.code_sent", str(contact_id))
    return await _contacts_out(session)


@router.post(
    "/v1/team-alerts/contacts/{contact_id}/verify",
    response_model=TeamContactsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Confirm a team address with the code emailed to it",
)
async def verify_team_contact(
    contact_id: UUID, payload: TeamCodeIn, session: Session, request: Request, principal: Owner
) -> TeamContactsOut:
    assert principal.tenant_id is not None
    outcome = await service.verify_contact(
        tenant_id=principal.tenant_id, contact_id=contact_id, code=payload.code
    )
    if outcome != "verified":
        raise service.refuse_verify(outcome)
    await _audit(session, request, principal, "team_alert.contact_verified", str(contact_id))
    await service.resync_agents(session, await service.agents_with_rules(session))
    return await _contacts_out(session)


@router.post(
    "/v1/team-alerts/contacts/{contact_id}/default",
    response_model=TeamContactsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Make a team address the one agents use unless they name another",
)
async def default_team_contact(
    contact_id: UUID, session: Session, request: Request, principal: Owner
) -> TeamContactsOut:
    await service.set_default(session, contact_id=contact_id)
    await _audit(session, request, principal, "team_alert.contact_default", str(contact_id))
    await service.resync_agents(session, await service.agents_with_rules(session))
    return await _contacts_out(session)


@router.delete(
    "/v1/team-alerts/contacts/{contact_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Stop telling this team address about callers",
)
async def remove_team_contact(
    contact_id: UUID, session: Session, request: Request, principal: Owner
) -> Response:
    agents = await service.remove_contact(session, contact_id=contact_id)
    await _audit(session, request, principal, "team_alert.contact_removed", str(contact_id))
    await service.resync_agents(session, agents)
    return Response(status_code=204)


@router.get(
    "/v1/agents/{agent_id}/team-alert",
    response_model=TeamAlertRuleOut,
    openapi_extra=permission_meta("agents:read"),
    summary="When this agent tells your team about a caller",
)
async def get_team_alert_rule(agent_id: UUID, session: Session, _: AgentReader) -> TeamAlertRuleOut:
    return _rule_out(await service.read_rule(session, agent_id=agent_id))


@router.put(
    "/v1/agents/{agent_id}/team-alert",
    response_model=TeamAlertRuleOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set when this agent tells your team about a caller",
)
async def set_team_alert_rule(
    agent_id: UUID,
    payload: TeamAlertRuleIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> TeamAlertRuleOut:
    assert principal.tenant_id is not None
    rule = Rule(
        contact_id=payload.contact_id,
        on_outcomes=tuple(payload.on_outcomes),
        on_fields=tuple(FieldTrigger(f.key, tuple(f.values)) for f in payload.on_fields),
        in_call=payload.in_call,
    )
    view = await service.save_rule(
        session, tenant_id=principal.tenant_id, agent_id=agent_id, rule=rule
    )
    await write_audit(
        session,
        action="agent.team_alert_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={
            "outcomes": str(len(rule.on_outcomes)),
            "fields": str(len(rule.on_fields)),
            "in_call": str(rule.in_call),
            "own_contact": str(rule.contact_id is not None),
        },
    )
    return _rule_out(view)


__all__ = ["router"]
