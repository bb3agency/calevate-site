"""ACTIONS routes — the engine-facing execution endpoint and the client-realm config API.

Two audiences, one module:

* `POST /v1/actions/invoke/{engine}/{tool_id}` is called by the ENGINE (Bolna) mid-call. It
  is unauthenticated and source-IP gated exactly like the webhook receiver — the tenant is
  resolved from the injected `{agent_id}` through `engine_agent_routes` (the same non-RLS
  bridge the receiver uses), then the tool is loaded under that tenant's RLS. It runs here,
  not in voice-runtime, because a data-returning action makes a synchronous external call
  and a credential decrypt (hard rule 3 keeps that off the latency-critical receiver).

* Everything under `/v1/agents/{agent_id}/actions` and `/v1/integrations/credentials` is the
  CLIENT realm — the Actions tab. `org:manage` on the writes (configuring what an agent may
  do mid-call is an account-level decision), `org:read` on the reads.

Secrets never appear in a response (credentials show a fingerprint) and never reach Bolna
(the credential is applied by the executor, not the engine config).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from calevate_shared.config import SOURCE_IP_ALLOWLIST_BY_ENGINE
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import credentials as creds
from apps.api.actions import service
from apps.api.actions.calendar import (
    authorize_url,
    calendar_configured,
    calendar_unavailable,
    token_exchange_request,
)
from apps.api.actions.execution import execute_action
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["actions"])
Session = Annotated[AsyncSession, Depends(db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# =============================================================== execution ====


@router.post(
    "/actions/invoke/{engine}/{tool_id}",
    summary="Engine-called: run one in-call action and return its result to the LLM",
)
async def invoke_action(engine: str, tool_id: UUID, request: Request) -> dict[str, Any]:
    """Bolna calls this for a during-call tool. Verifies the source, resolves the tenant
    from the injected agent ref, loads the tool under that tenant's RLS, and executes.

    The response body IS the tool result the LLM reads back. Failures are returned as a
    structured payload (not a 5xx) so the agent can relay them to the caller rather than the
    call hearing dead air.
    """
    # The trusted-proxy predicate, not the raw socket peer — behind nginx the peer is the
    # edge (SEC-COMP §5, D-131). `client_request_ip` is the one door to that judgement in
    # `apps/api` (`scripts/check_audit_ip.py`), and it is the same `client_ip` call the
    # webhook receiver authenticates an unsigned engine with.
    source_ip = client_request_ip(request)
    resolver = SOURCE_IP_ALLOWLIST_BY_ENGINE.get(engine)
    if resolver is None or source_ip is None or source_ip not in resolver(get_settings()):
        # Same posture as the webhook receiver: an unrecognised or unallowlisted caller is
        # refused before a byte of body is trusted. Never echoes the engine string.
        raise ProblemError.unauthorized("This caller is not permitted to invoke actions.")

    raw = await request.body()
    try:
        received = json.loads(raw or b"{}")
    except ValueError:
        received = {}
    if not isinstance(received, dict):
        received = {}

    agent_ref = received.get("_agent_ref")
    if not isinstance(agent_ref, str) or not agent_ref:
        raise ProblemError(
            kind="validation",
            code="action_missing_agent_ref",
            title="The tool call did not identify its agent",
            detail="No agent reference was supplied, so the tenant could not be resolved.",
            status=422,
        )

    # Cross-tenant bridge, non-RLS, exactly as the webhook receiver resolves an agent.
    async with untenanted_session() as anon:
        row = (
            await anon.execute(
                text(
                    "SELECT tenant_id, agent_id FROM engine_agent_routes "
                    "WHERE engine_agent_ref = :ref AND engine = :engine AND active"
                ),
                {"ref": agent_ref, "engine": engine},
            )
        ).first()
    if row is None:
        raise ProblemError.unauthorized("This agent is not recognised.")
    tenant_id: UUID = row[0]
    route_agent_id: UUID = row[1]

    async with tenant_session(tenant_id) as session:
        # BOUND TO THE AGENT THE REF RESOLVED, which is what the comment below used to
        # claim and `get_tool` could not do — see `service.get_agent_tool`. The ref is the
        # only thing the engine authenticates with here, so the tool it may reach has to
        # be the one that ref's agent owns.
        tool = await service.get_agent_tool(session, agent_id=route_agent_id, tool_id=tool_id)
        # RLS makes a tool from another tenant invisible → None, indistinguishable from a
        # deleted one (hard rule 1), and a tool belonging to a different agent is now the
        # same `None` for the same reason. A disabled tool is refused too, and so is one
        # whose agent has the master API-actions switch off — a client who turns that
        # switch off has withdrawn every tool on the agent, and the in-call path must
        # honour that rather than only the publish path that declares the tool list.
        if tool is None or not tool.enabled:
            raise ProblemError.not_found("Action")
        if not await service.actions_enabled(session, agent_id=route_agent_id):
            raise ProblemError.not_found("Action")
        result = await execute_action(session, tool=tool, received=received, source="in_call")
    return result.payload


# ============================================================= credentials ====


class CreateCredentialIn(Strict):
    kind: Literal["aisensy", "meta_cloud", "interakt", "custom_api", "google_calendar"]
    label: str = Field(min_length=1, max_length=200)
    secret: str = Field(min_length=1, max_length=8192)
    non_secret: dict[str, Any] | None = None


class RotateCredentialIn(Strict):
    secret: str = Field(min_length=1, max_length=8192)
    expected_version: int = Field(ge=1)


class CredentialOut(Strict):
    id: UUID
    kind: str
    label: str
    last_four: str
    version: int
    non_secret: dict[str, Any] | None
    created_at: str
    updated_at: str


def _cred_out(r: creds.CredentialRecord) -> CredentialOut:
    return CredentialOut(
        id=r.id,
        kind=r.kind,
        label=r.label,
        last_four=r.last_four,
        version=r.version,
        non_secret=r.non_secret,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


@router.get(
    "/integrations/credentials",
    response_model=list[CredentialOut],
    openapi_extra=permission_meta("org:read"),
    summary="Saved integration credentials — fingerprints only, never the secret",
)
async def list_credentials(
    session: Session, _: Principal = Depends(requires("org:read"))
) -> list[CredentialOut]:
    return [_cred_out(r) for r in await creds.list_credentials(session)]


@router.post(
    "/integrations/credentials",
    response_model=CredentialOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Save a reusable integration credential (envelope-encrypted)",
)
async def create_credential(
    payload: CreateCredentialIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> CredentialOut:
    assert principal.tenant_id is not None
    record = await creds.create_credential(
        session,
        tenant_id=principal.tenant_id,
        kind=payload.kind,
        label=payload.label,
        secret=payload.secret,
        non_secret=payload.non_secret,
    )
    await write_audit(
        session,
        action="integration_credential.created",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="integration_credential",
        object_id=str(record.id),
        ip=client_request_ip(request),
        summary={"kind": payload.kind, "last_four": record.last_four},
    )
    return _cred_out(record)


@router.post(
    "/integrations/credentials/{credential_id}/rotate",
    response_model=CredentialOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Rotate a credential in place — every tool using it picks up the new value",
)
async def rotate_credential(
    credential_id: UUID,
    payload: RotateCredentialIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> CredentialOut:
    assert principal.tenant_id is not None
    record = await creds.rotate_credential(
        session,
        tenant_id=principal.tenant_id,
        credential_id=credential_id,
        secret=payload.secret,
        expected_version=payload.expected_version,
    )
    await write_audit(
        session,
        action="integration_credential.rotated",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="integration_credential",
        object_id=str(credential_id),
        ip=client_request_ip(request),
        summary={"version": record.version},
    )
    return _cred_out(record)


@router.delete(
    "/integrations/credentials/{credential_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Delete a saved credential (tools using it become visibly broken)",
)
async def delete_credential(
    credential_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> None:
    assert principal.tenant_id is not None
    if await creds.delete_credential(session, credential_id=credential_id):
        await write_audit(
            session,
            action="integration_credential.deleted",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="integration_credential",
            object_id=str(credential_id),
            ip=client_request_ip(request),
        )
    else:
        raise ProblemError.not_found("Credential")


# =================================================================== tools ====


class ParamIn(Strict):
    name: str = Field(min_length=1, max_length=64)
    source: Literal["static", "lead_var", "ai"]
    value: str | None = None
    lead_var: str | None = None
    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str = ""
    required: bool = False


class ToolIn(Strict):
    kind: Literal["custom_api", "whatsapp", "calendar"]
    provider: str | None = None
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2000)
    trigger: Literal["during_call", "after_call"] = "during_call"
    pre_call_message: str | None = Field(default=None, max_length=500)
    credential_id: UUID | None = None
    # A tool's parameters are a hand-authored binding list, but still caller-controlled, and
    # `ToolOut.params` echoes them in full — so the count is bounded on the request model
    # rather than left to grow (`scripts/check_list_bounds.py`, D-302). Generous vs any real
    # action; a request past it is a misuse, not a shape we materialise.
    params: list[ParamIn] = Field(default_factory=list, max_length=service.MAX_TOOL_PARAMS)
    config: dict[str, Any]


class ToolOut(Strict):
    id: UUID
    agent_id: UUID
    kind: str
    provider: str | None
    name: str
    description: str
    enabled: bool
    trigger: str
    pre_call_message: str | None
    credential_id: UUID | None
    params: list[dict[str, Any]]
    config: dict[str, Any]


def _tool_out(t: service.LoadedTool) -> ToolOut:
    return ToolOut(
        id=t.id,
        agent_id=t.agent_id,
        kind=t.kind,
        provider=t.provider,
        name=t.name,
        description=t.description,
        enabled=t.enabled,
        trigger=t.trigger,
        pre_call_message=t.pre_call_message,
        credential_id=t.credential_id,
        params=t.params,
        config=t.config,
    )


class ActionsSettingsOut(Strict):
    """The agent's master switch and its tools, for the Actions tab in one read."""

    api_actions_enabled: bool
    tools: list[ToolOut]
    # Whether Google Calendar can be offered on this deployment (an OAuth client exists).
    calendar_available: bool


class MasterSwitchIn(Strict):
    enabled: bool


class EnableIn(Strict):
    enabled: bool


async def _assert_agent(session: AsyncSession, agent_id: UUID) -> None:
    """The agent must belong to this tenant (RLS) and exist. A tool for an agent the caller
    cannot see is 404, indistinguishable from one that never existed."""
    row = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE id = :id AND deleted_at IS NULL"), {"id": agent_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")


@router.get(
    "/agents/{agent_id}/actions",
    response_model=ActionsSettingsOut,
    openapi_extra=permission_meta("org:read"),
    summary="The Actions tab: master switch + configured tools",
)
async def list_agent_actions(
    agent_id: UUID, session: Session, _: Principal = Depends(requires("org:read"))
) -> ActionsSettingsOut:
    await _assert_agent(session, agent_id)
    return ActionsSettingsOut(
        api_actions_enabled=await service.actions_enabled(session, agent_id=agent_id),
        tools=[_tool_out(t) for t in await service.list_tools(session, agent_id=agent_id)],
        calendar_available=calendar_configured(),
    )


@router.put(
    "/agents/{agent_id}/actions/enabled",
    response_model=ActionsSettingsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="The master 'Enable API actions' switch — applies to live calls at next publish",
)
async def set_master_switch(
    agent_id: UUID,
    payload: MasterSwitchIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> ActionsSettingsOut:
    assert principal.tenant_id is not None
    await _assert_agent(session, agent_id)
    await service.set_actions_enabled(session, agent_id=agent_id, enabled=payload.enabled)
    await write_audit(
        session,
        action="agent_actions.master_switch",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={"enabled": str(payload.enabled)},
    )
    return await list_agent_actions(agent_id, session, principal)


@router.post(
    "/agents/{agent_id}/actions",
    response_model=ToolOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Add an in-call action to an agent",
)
async def create_action(
    agent_id: UUID,
    payload: ToolIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> ToolOut:
    assert principal.tenant_id is not None
    await _assert_agent(session, agent_id)
    tool = await service.create_tool(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        kind=payload.kind,
        provider=payload.provider,
        name=payload.name,
        description=payload.description,
        trigger=payload.trigger,
        pre_call_message=payload.pre_call_message,
        credential_id=payload.credential_id,
        params=[p.model_dump() for p in payload.params],
        config=payload.config,
    )
    await write_audit(
        session,
        action="action_tool.created",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="action_tool",
        object_id=str(tool.id),
        ip=client_request_ip(request),
        summary={"kind": tool.kind, "name": tool.name},
    )
    return _tool_out(tool)


@router.put(
    "/agents/{agent_id}/actions/{tool_id}",
    response_model=ToolOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Edit an in-call action",
)
async def update_action(
    agent_id: UUID,
    tool_id: UUID,
    payload: ToolIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> ToolOut:
    assert principal.tenant_id is not None
    await _assert_agent(session, agent_id)
    tool = await service.update_tool(
        session,
        tool_id=tool_id,
        kind=payload.kind,
        provider=payload.provider,
        name=payload.name,
        description=payload.description,
        trigger=payload.trigger,
        pre_call_message=payload.pre_call_message,
        credential_id=payload.credential_id,
        params=[p.model_dump() for p in payload.params],
        config=payload.config,
    )
    await write_audit(
        session,
        action="action_tool.updated",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="action_tool",
        object_id=str(tool_id),
        ip=client_request_ip(request),
        summary={"kind": tool.kind, "name": tool.name},
    )
    return _tool_out(tool)


@router.put(
    "/agents/{agent_id}/actions/{tool_id}/enabled",
    response_model=ToolOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Enable or disable one action",
)
async def set_action_enabled(
    agent_id: UUID,
    tool_id: UUID,
    payload: EnableIn,
    session: Session,
    _: Principal = Depends(requires("org:manage")),
) -> ToolOut:
    await _assert_agent(session, agent_id)
    if not await service.set_enabled(
        session, agent_id=agent_id, tool_id=tool_id, enabled=payload.enabled
    ):
        raise ProblemError.not_found("Action")
    tool = await service.get_agent_tool(session, agent_id=agent_id, tool_id=tool_id)
    assert tool is not None
    return _tool_out(tool)


@router.delete(
    "/agents/{agent_id}/actions/{tool_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Remove an in-call action",
)
async def delete_action(
    agent_id: UUID,
    tool_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> None:
    assert principal.tenant_id is not None
    await _assert_agent(session, agent_id)
    if await service.delete_tool(session, agent_id=agent_id, tool_id=tool_id):
        await write_audit(
            session,
            action="action_tool.deleted",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="action_tool",
            object_id=str(tool_id),
            ip=client_request_ip(request),
        )
    else:
        raise ProblemError.not_found("Action")


# ============================================================= test harness ====


class TestActionIn(Strict):
    """Sample values for the AI/lead-var params, to run the action before saving it live."""

    values: dict[str, Any] = Field(default_factory=dict)


class TestActionOut(Strict):
    ok: bool
    status: str
    payload: dict[str, Any]


@router.post(
    "/agents/{agent_id}/actions/{tool_id}/test",
    response_model=TestActionOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Run an action with sample values before it goes live (no audit as in-call)",
)
async def test_action(
    agent_id: UUID,
    tool_id: UUID,
    payload: TestActionIn,
    session: Session,
    _: Principal = Depends(requires("org:manage")),
) -> TestActionOut:
    """The 'Test API' tab. Executes the real external call with the operator's sample
    values so a misconfiguration is caught before a caller ever triggers it. Audited as a
    test invocation (`source="test"`) so a live WhatsApp send in testing is still on file.
    """
    await _assert_agent(session, agent_id)
    tool = await service.get_agent_tool(session, agent_id=agent_id, tool_id=tool_id)
    if tool is None:
        raise ProblemError.not_found("Action")
    result = await execute_action(session, tool=tool, received=payload.values, source="test")
    return TestActionOut(ok=result.ok, status=result.status, payload=result.payload)


# ============================================================= calendar oauth ==


class CalendarConnectOut(Strict):
    authorize_url: str


@router.get(
    "/actions/calendar/connect",
    response_model=CalendarConnectOut,
    openapi_extra=permission_meta("org:read"),
    summary="Begin Google Calendar OAuth — returns the consent URL",
)
async def calendar_connect(
    principal: Principal = Depends(requires("org:read")),
) -> CalendarConnectOut:
    """Start the OAuth flow. `state` carries the tenant so the callback can attribute the
    refresh token; it is signed context, not a bearer — the callback re-checks it.

    ⚠ The state here is the tenant id; a production hardening is to sign it (HMAC) to stop a
    forged callback attaching a token to another tenant. Left as a NAMED follow-up because
    the callback also requires an authenticated `org:manage` session, which already binds
    the acting tenant — see `calendar_callback`.
    """
    assert principal.tenant_id is not None
    if not calendar_configured():
        # ONE wording, in `calendar.py` — this site used to carry its own copy of the
        # sentence, addressed to an operator, on a screen only a client reaches.
        raise calendar_unavailable()
    return CalendarConnectOut(authorize_url=authorize_url(state=str(principal.tenant_id)))


class CalendarCallbackIn(Strict):
    code: str = Field(min_length=1, max_length=2048)
    label: str = Field(default="Google Calendar", min_length=1, max_length=200)


@router.post(
    "/actions/calendar/callback",
    response_model=CredentialOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Complete Google Calendar OAuth — stores the refresh token as a credential",
)
async def calendar_callback(
    payload: CalendarCallbackIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> CredentialOut:
    """Exchange the authorization code and save the refresh token as a `google_calendar`
    credential. Bound to the authenticated `org:manage` tenant, so a code cannot be
    redeemed onto another tenant's account."""
    assert principal.tenant_id is not None
    import httpx

    req = token_exchange_request(code=payload.code)
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(req.url, headers=req.headers, data=req.form_body)
    if resp.status_code != 200:
        raise ProblemError(
            kind="dependency",
            code="calendar_oauth_failed",
            title="Google did not accept the authorization",
            detail="The Google authorization code could not be exchanged.",
            remediation="Try connecting again.",
        )
    body = resp.json()
    refresh_token = str(body.get("refresh_token") or "")
    if not refresh_token:
        # No refresh token means Google returned only an access token — usually a re-consent
        # without `prompt=consent`. `authorize_url` sets it, so this is a real failure.
        raise ProblemError(
            kind="business_rule",
            code="calendar_no_refresh_token",
            title="Google returned no long-lived token",
            detail="The connection did not include a refresh token.",
            remediation="Disconnect the app in your Google account, then connect again.",
        )
    record = await creds.create_credential(
        session,
        tenant_id=principal.tenant_id,
        kind="google_calendar",
        label=payload.label,
        secret=refresh_token,
        non_secret={"scope": str(body.get("scope") or "")},
    )
    await write_audit(
        session,
        action="integration_credential.created",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="integration_credential",
        object_id=str(record.id),
        ip=client_request_ip(request),
        summary={"kind": "google_calendar"},
    )
    return _cred_out(record)


__all__ = ["router"]
