"""Who hears about hot leads (D-904) and when (D-1040), as endpoints.

    GET    /v1/team-alerts/contacts                    the team addresses
    POST   /v1/team-alerts/contacts                    add one; a code is mailed to it (owner)
    POST   /v1/team-alerts/contacts/{id}/code          mail a new code (owner)
    POST   /v1/team-alerts/contacts/{id}/verify        enter the code (owner)
    DELETE /v1/team-alerts/contacts/{id}               stop sending there (owner)
    GET    /v1/agents/{agent_id}/team-alert            the agent's in-call switch, its jobs
    PUT    /v1/agents/{agent_id}/team-alert            set the switch (owner)
    GET    /v1/campaigns/{campaign_id}/team-alert      which of its calls alert
    PUT    /v1/campaigns/{campaign_id}/team-alert      set them (owner)
    GET    /v1/inbound-lines/{line_id}/team-alert      which of its calls alert
    PUT    /v1/inbound-lines/{line_id}/team-alert      set them (owner)

The owner is on the list without an entry here: their email always, their WhatsApp once they
opt in (`compliance/whatsapp_optin_routes.py`).

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
from apps.api.team_alerts.service import MAX_FIELD_TRIGGERS, FieldTrigger, Rule

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
    #: Outcomes only: it makes the caller a lead, so it is ticked until the owner saves.
    positive: bool
    #: Outcomes only: it moves the lead to Hot, the business's goal.
    goal: bool


class TeamAlertJobOut(BaseModel):
    """A campaign or inbound line in the agent's voice, whose page sets its own alerts."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["campaign", "line"]
    id: UUID
    name: str


class AgentTeamAlertOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The agent may message the team while a caller is on the line.
    in_call: bool
    #: Whether it can now: switched on and a confirmed team address hears.
    in_call_live: bool
    #: Confirmed team addresses that hear now; the owner hears besides.
    team_addresses: int
    #: Its open campaigns and lines, each with its own after-call alerts, newest first.
    jobs: list[TeamAlertJobOut]


class AgentTeamAlertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_call: bool


class JobTeamAlertOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["campaign", "line"]
    id: UUID
    name: str
    agent_id: UUID
    on_outcomes: list[str]
    on_fields: list[FieldTriggerIO]
    #: Whether the owner saved this rule; until then it is every positive outcome.
    saved: bool
    #: Confirmed team addresses that hear now; the owner hears besides.
    team_addresses: int
    #: The agent's outcomes, which this job's calls end on.
    outcomes: list[TeamAlertChoiceOut]
    #: The choice details on this job's own "What it notes" list.
    fields: list[TeamAlertChoiceOut]


class JobTeamAlertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_outcomes: list[Annotated[str, Field(max_length=_VALUE_MAX)]] = Field(
        default_factory=list, max_length=_OUTCOMES_MAX
    )
    on_fields: list[FieldTriggerIO] = Field(default_factory=list, max_length=MAX_FIELD_TRIGGERS)


def _contact_out(contact: service.Contact) -> TeamContactOut:
    return TeamContactOut(
        id=contact.id,
        channel="whatsapp" if contact.channel == "whatsapp" else "email",
        address=contact.address,
        verified=contact.verified,
        whatsapp_account_id=contact.whatsapp_account_id,
    )


def _choice_out(choice: service.Choice) -> TeamAlertChoiceOut:
    return TeamAlertChoiceOut(
        key=choice.key,
        label=choice.label,
        values=list(choice.values),
        positive=choice.positive,
        goal=choice.goal,
    )


def _agent_out(view: service.AgentAlertsView) -> AgentTeamAlertOut:
    return AgentTeamAlertOut(
        in_call=view.in_call,
        in_call_live=view.in_call_live,
        team_addresses=view.team_addresses,
        jobs=[TeamAlertJobOut(kind=j.ref.kind, id=j.ref.id, name=j.name) for j in view.jobs],
    )


def _job_out(view: service.JobRuleView) -> JobTeamAlertOut:
    return JobTeamAlertOut(
        kind=view.job.kind,
        id=view.job.id,
        name=view.name,
        agent_id=view.agent_id,
        on_outcomes=list(view.rule.on_outcomes),
        on_fields=[FieldTriggerIO(key=t.key, values=list(t.values)) for t in view.rule.on_fields],
        saved=view.saved,
        team_addresses=view.team_addresses,
        outcomes=[_choice_out(o) for o in view.outcomes],
        fields=[_choice_out(f) for f in view.fields],
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
    response_model=AgentTeamAlertOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Whether this agent may message your team during a call, and its jobs' alerts",
)
async def get_agent_team_alert(
    agent_id: UUID, session: Session, _: AgentReader
) -> AgentTeamAlertOut:
    return _agent_out(await service.read_agent_alerts(session, agent_id=agent_id))


@router.put(
    "/v1/agents/{agent_id}/team-alert",
    response_model=AgentTeamAlertOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Let this agent message your team during a call, or stop it",
)
async def set_agent_team_alert(
    agent_id: UUID,
    payload: AgentTeamAlertIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> AgentTeamAlertOut:
    assert principal.tenant_id is not None
    view = await service.save_in_call(
        session, tenant_id=principal.tenant_id, agent_id=agent_id, in_call=payload.in_call
    )
    await write_audit(
        session,
        action="agent.team_alert_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={"in_call": str(payload.in_call)},
    )
    return _agent_out(view)


async def _save_job(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    job: service.HolderRef,
    payload: JobTeamAlertIn,
) -> JobTeamAlertOut:
    assert principal.tenant_id is not None
    rule = Rule(
        on_outcomes=tuple(payload.on_outcomes),
        on_fields=tuple(FieldTrigger(f.key, tuple(f.values)) for f in payload.on_fields),
    )
    view = await service.save_job_rule(session, job, rule)
    await write_audit(
        session,
        action=f"{'campaign' if job.kind == 'campaign' else 'inbound_line'}.team_alert_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign" if job.kind == "campaign" else "inbound_line",
        object_id=str(job.id),
        ip=client_request_ip(request),
        summary={"outcomes": str(len(rule.on_outcomes)), "fields": str(len(rule.on_fields))},
    )
    return _job_out(view)


@router.get(
    "/v1/campaigns/{campaign_id}/team-alert",
    response_model=JobTeamAlertOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Which of this campaign's calls you and your team are told about",
)
async def get_campaign_team_alert(
    campaign_id: UUID, session: Session, _: AgentReader
) -> JobTeamAlertOut:
    return _job_out(
        await service.read_job_rule(session, service.HolderRef("campaign", campaign_id))
    )


@router.put(
    "/v1/campaigns/{campaign_id}/team-alert",
    response_model=JobTeamAlertOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set which of this campaign's calls you and your team are told about",
)
async def set_campaign_team_alert(
    campaign_id: UUID,
    payload: JobTeamAlertIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> JobTeamAlertOut:
    job = service.HolderRef("campaign", campaign_id)
    return await _save_job(session, request, principal, job, payload)


@router.get(
    "/v1/inbound-lines/{line_id}/team-alert",
    response_model=JobTeamAlertOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Which of this line's calls you and your team are told about",
)
async def get_line_team_alert(line_id: UUID, session: Session, _: AgentReader) -> JobTeamAlertOut:
    return _job_out(await service.read_job_rule(session, service.HolderRef("line", line_id)))


@router.put(
    "/v1/inbound-lines/{line_id}/team-alert",
    response_model=JobTeamAlertOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set which of this line's calls you and your team are told about",
)
async def set_line_team_alert(
    line_id: UUID,
    payload: JobTeamAlertIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> JobTeamAlertOut:
    job = service.HolderRef("line", line_id)
    return await _save_job(session, request, principal, job, payload)


__all__ = ["router"]
