"""ACTIONS routes — the client-realm config API (the Actions and Connections screens).

`/v1/agents/{agent_id}/actions` is an agent's Actions area; `/v1/integrations/credentials`
and `/v1/integrations/oauth/*` are the account's connections. `org:manage` on the writes,
`org:read` on the reads, so only the account OWNER changes them (D-700).

VIEW-AS (D-587, D-700). An operator viewing the account may set actions up and switch them
OFF, never connect an account (`integrations.connect`) or switch an action ON
(`actions.switch_on`): both are the owner's decisions, and a credential is never shown to
anyone in any case — `CredentialOut` has a fingerprint, never a value.

THE VOICE PLATFORM FOLLOWS. Every change to an agent's actions, and every removed
connection, re-syncs that agent's vendor actions at once when it is live on an engine that
hosts them (`reliability/engine_actions.sync_client_actions_now`), so a switched-off action
leaves the live agent in the same request. Every change is audited.

Secrets never appear in a response and never reach an engine: the executor applies the
credential, on our side.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import credentials as creds
from apps.api.actions import oauth, service
from apps.api.actions import payment_links as rzp
from apps.api.actions import sheets as gsheets
from apps.api.actions.calendar import (
    calendar_configured,
    calendar_state_refused,
    calendar_unavailable,
)
from apps.api.actions.crm import zoho_api_domain
from apps.api.actions.execution import CallFacts, access_token_for, execute_action
from apps.api.authn.subjects import load_subject
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.integrations.egress_guard import egress_client
from apps.api.reliability.engine_actions import sync_client_actions_now

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["actions"])
Session = Annotated[AsyncSession, Depends(db)]

#: How many runs the per-action call log shows.
INVOCATION_LOG_LIMIT = 50


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ============================================================= credentials ====


class CreateCredentialIn(Strict):
    # The OAuth kinds (`zoho_crm`, `hubspot`) are created only by their consent flow;
    # `google_calendar` stays accepted for the screens that pasted a token before D-700.
    kind: Literal["aisensy", "meta_cloud", "interakt", "custom_api", "google_calendar", "razorpay"]
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


def _owner_only(principal: Principal) -> UUID:
    """The tenant, after refusing an operator in view-as: connecting is the owner's act."""
    assert principal.tenant_id is not None
    assert_view_as_may(principal, "integrations.connect")
    return principal.tenant_id


def _checked_non_secret(kind: str, non_secret: dict[str, Any] | None) -> dict[str, Any] | None:
    """The non-secret half a kind needs: a Razorpay key pair is a key id beside the secret."""
    if kind != "razorpay":
        return non_secret
    key_id = str((non_secret or {}).get("key_id") or "").strip()
    if not key_id or len(key_id) > 64 or not key_id.isascii():
        raise ProblemError(
            kind="validation",
            code="razorpay_key_id_required",
            title="Add your Razorpay Key ID",
            detail="A Razorpay connection needs the Key ID as well as the Key Secret.",
            remediation="Copy both from Razorpay Dashboard → Account & Settings → API Keys.",
        )
    return {"key_id": key_id}


async def _resync(session: AsyncSession, agent_ids: list[UUID]) -> None:
    for agent_id in agent_ids:
        await sync_client_actions_now(session, agent_id=agent_id)


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
    summary="Save a reusable integration credential (envelope-encrypted, shown once)",
)
async def create_credential(
    payload: CreateCredentialIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> CredentialOut:
    tenant_id = _owner_only(principal)
    record = await creds.create_credential(
        session,
        tenant_id=tenant_id,
        kind=payload.kind,
        label=payload.label,
        secret=payload.secret,
        non_secret=_checked_non_secret(payload.kind, payload.non_secret),
    )
    await write_audit(
        session,
        action="integration_credential.created",
        actor=principal,
        tenant_id=tenant_id,
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
    tenant_id = _owner_only(principal)
    record = await creds.rotate_credential(
        session,
        tenant_id=tenant_id,
        credential_id=credential_id,
        secret=payload.secret,
        expected_version=payload.expected_version,
    )
    await write_audit(
        session,
        action="integration_credential.rotated",
        actor=principal,
        tenant_id=tenant_id,
        object_type="integration_credential",
        object_id=str(credential_id),
        ip=client_request_ip(request),
        summary={"version": record.version},
    )
    return _cred_out(record)


async def _revoke_at_vendor(resolved: creds.ResolvedCredential | None) -> None:
    """Withdraw our access at the vendor, best effort: the row is gone either way, and a
    vendor that did not answer still holds a token nothing of ours can use."""
    if resolved is None or resolved.kind not in oauth.OAUTH_KINDS:
        return
    accounts = resolved.non_secret.get("accounts_server")
    request = oauth.revoke_request(
        resolved.kind,
        refresh_token=resolved.secret,
        accounts_server=accounts if isinstance(accounts, str) else None,
    )
    if request is None:
        return
    try:
        async with egress_client(timeout=5.0) as http:
            response = await http.request(
                request.method, request.url, headers=request.headers, data=request.form_body
            )
        log.info("oauth_revoked", extra={"kind": resolved.kind, "status": response.status_code})
    except httpx.HTTPError as exc:
        log.warning(
            "oauth_revoke_failed", extra={"kind": resolved.kind, "error": type(exc).__name__}
        )


@router.delete(
    "/integrations/credentials/{credential_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Disconnect an account: its actions leave the live agents and say they cannot help",
)
async def delete_credential(
    credential_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> None:
    tenant_id = _owner_only(principal)
    agents = await service.agents_using_credential(session, credential_id=credential_id)
    try:
        resolved = await creds.resolve_credential(
            session, tenant_id=tenant_id, credential_id=credential_id
        )
    except creds.CredentialUnusableError:
        resolved = None
    if not await creds.delete_credential(session, credential_id=credential_id):
        raise ProblemError.not_found("Credential")
    await write_audit(
        session,
        action="integration_credential.deleted",
        actor=principal,
        tenant_id=tenant_id,
        object_type="integration_credential",
        object_id=str(credential_id),
        ip=client_request_ip(request),
        summary={"agents_resynced": len(agents)},
    )
    await _resync(session, agents)
    await _revoke_at_vendor(resolved)


class CredentialTestOut(Strict):
    ok: bool
    #: What the client is told, in their words.
    message: str


@router.post(
    "/integrations/credentials/{credential_id}/test",
    response_model=CredentialTestOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Check a connection works without sending anything to anyone",
)
async def test_credential(
    credential_id: UUID, session: Session, principal: Principal = Depends(requires("org:manage"))
) -> CredentialTestOut:
    """A read-only proof per kind: Razorpay lists one payment, an OAuth connection mints an
    access token. A WhatsApp key cannot be proved without sending, so it says to use the
    action's "send a test WhatsApp to my number" instead."""
    assert principal.tenant_id is not None
    try:
        resolved = await creds.resolve_credential(
            session, tenant_id=principal.tenant_id, credential_id=credential_id
        )
    except creds.CredentialUnusableError:
        return CredentialTestOut(
            ok=False, message="This connection can't be read. Connect it again."
        )
    if resolved is None:
        raise ProblemError.not_found("Credential")
    async with egress_client(timeout=8.0) as http:
        if resolved.kind == "razorpay":
            req = rzp.probe(
                key_id=str(resolved.non_secret.get("key_id") or ""), key_secret=resolved.secret
            )
            response = await http.request(req.method, req.url, headers=req.headers)
            ok = response.status_code == 200
            message = (
                "Razorpay accepted these keys."
                if ok
                else "Razorpay did not accept these keys. Check the Key ID and Key Secret."
            )
            return CredentialTestOut(ok=ok, message=message)
        if resolved.kind in oauth.OAUTH_KINDS:
            accounts = resolved.non_secret.get("accounts_server")
            req = oauth.refresh_request(
                resolved.kind,
                refresh_token=resolved.secret,
                accounts_server=accounts if isinstance(accounts, str) else None,
            )
            response = await http.request(
                req.method, req.url, data=req.form_body, headers=req.headers
            )
            ok = response.status_code == 200
            label = oauth.label(resolved.kind)
            message = (
                f"{label} is connected."
                if ok
                else f"{label} no longer accepts this connection. Disconnect it and connect again."
            )
            return CredentialTestOut(ok=ok, message=message)
    return CredentialTestOut(
        ok=True,
        message=(
            "This key is saved. To check it end to end, use the test on an action that uses it."
        ),
    )


# ======================================================== oauth connections ====


class ConnectOut(Strict):
    authorize_url: str


class OAuthCallbackIn(Strict):
    code: str = Field(min_length=1, max_length=2048)
    #: The `state` the connect step put in the consent URL. Required: a signed-in session
    #: alone does not stop a planted code — the attack is getting THIS session to redeem a
    #: code from somebody else's consent.
    state: str = Field(min_length=1, max_length=2048)
    label: str | None = Field(default=None, min_length=1, max_length=200)
    #: Zoho's `accounts-server` from the redirect; checked against Zoho's own hosts.
    accounts_server: str | None = Field(default=None, max_length=256)


OAuthKindPath = Literal["google_calendar", "google_sheets", "zoho_crm", "hubspot"]


@router.get(
    "/integrations/oauth/{kind}/connect",
    response_model=ConnectOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Begin connecting a Google, Zoho CRM or HubSpot account — returns the consent URL",
)
async def oauth_connect(
    kind: OAuthKindPath, principal: Principal = Depends(requires("org:manage"))
) -> ConnectOut:
    tenant_id = _owner_only(principal)
    assert principal.user_id is not None
    oauth.require_configured(kind)
    state = oauth.mint_state(kind, tenant_id=tenant_id, user_id=principal.user_id)
    hint = None
    if kind in oauth.GOOGLE_KINDS:
        # The owner's own sign-in address, so Google offers the account they use with us.
        subject = await load_subject("client", principal.user_id)
        hint = subject.email if subject is not None else None
    return ConnectOut(authorize_url=oauth.authorize_url(kind, state=state, login_hint=hint))


async def complete_oauth(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    *,
    kind: oauth.OAuthKind,
    payload: OAuthCallbackIn,
    refusal: ProblemError | None = None,
) -> CredentialOut:
    """Exchange the code and seal the refresh token as this account's connection. The state
    is checked BEFORE the exchange, so a code from a consent this person did not start is
    never redeemed at all."""
    tenant_id = _owner_only(principal)
    assert principal.user_id is not None
    oauth.verify_state(
        kind,
        payload.state,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        refusal=refusal or oauth.state_refused(kind),
    )
    accounts = oauth.zoho_accounts_server(payload.accounts_server) if kind == "zoho_crm" else None
    if kind == "zoho_crm" and payload.accounts_server and accounts is None:
        raise ProblemError(
            kind="validation",
            code="zoho_accounts_server_unknown",
            title="Zoho sent you back from an address we don't recognise",
            detail="The connection was not completed.",
            remediation="Start the connection again from the Connections screen.",
        )
    req = oauth.exchange_request(kind, code=payload.code, accounts_server=accounts)
    async with egress_client(timeout=10.0) as http:
        resp = await http.post(req.url, headers=req.headers, data=req.form_body)
    label = oauth.label(kind)
    if resp.status_code != 200:
        log.info("oauth_exchange_refused", extra={"kind": kind, "status": resp.status_code})
        if kind == "google_calendar":
            raise ProblemError(
                kind="dependency",
                code="calendar_oauth_failed",
                title=f"{label} did not accept the connection",
                detail=f"The {label} authorization could not be completed.",
                remediation="Try connecting again.",
            )
        if kind == "google_sheets":
            raise ProblemError(
                kind="dependency",
                code="sheets_oauth_failed",
                title=f"{label} did not accept the connection",
                detail=f"The {label} authorization could not be completed.",
                remediation="Try connecting again.",
            )
        # The CRMs refuse a code for ordinary reasons (it expired, it was used twice); a
        # refusal the client retries, not a page.
        raise ProblemError(
            kind="business_rule",
            code="crm_oauth_failed",
            title=f"{label} did not accept the connection",
            detail=f"The {label} authorization could not be completed.",
            remediation="Try connecting again.",
        )
    body = resp.json()
    refresh_token = str(body.get("refresh_token") or "")
    if not refresh_token:
        raise ProblemError(
            kind="business_rule",
            code={
                "google_calendar": "calendar_no_refresh_token",
                "google_sheets": "sheets_no_refresh_token",
            }.get(kind, f"{kind}_no_refresh_token"),
            title=f"{label} returned no long-lived connection",
            detail="The connection did not include a refresh token.",
            remediation=(
                f"Remove Calevate from your {label} account's connected apps, then connect again."
            ),
        )
    non_secret: dict[str, Any] = {"scope": str(body.get("scope") or body.get("scopes") or "")}
    if kind == "zoho_crm":
        domain = zoho_api_domain(body.get("api_domain"))
        if domain is None:
            raise ProblemError(
                kind="business_rule",
                code="zoho_api_domain_unknown",
                title="Zoho answered from an address we don't recognise",
                detail="The connection was not saved.",
                remediation="Contact us with the reference on this message.",
            )
        non_secret |= {"api_domain": domain, "accounts_server": accounts or ""}
    if kind == "hubspot" and body.get("hub_id") is not None:
        non_secret["hub_id"] = str(body.get("hub_id"))
    record = await creds.create_credential(
        session,
        tenant_id=tenant_id,
        kind=kind,
        label=payload.label or label,
        secret=refresh_token,
        non_secret=non_secret,
    )
    await write_audit(
        session,
        action="integration_credential.created",
        actor=principal,
        tenant_id=tenant_id,
        object_type="integration_credential",
        object_id=str(record.id),
        ip=client_request_ip(request),
        summary={"kind": kind},
    )
    return _cred_out(record)


@router.post(
    "/integrations/oauth/{kind}/callback",
    response_model=CredentialOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Finish connecting Google Calendar, Zoho CRM or HubSpot",
)
async def oauth_callback(
    kind: OAuthKindPath,
    payload: OAuthCallbackIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> CredentialOut:
    return await complete_oauth(session, request, principal, kind=kind, payload=payload)


class ConnectionsStatusOut(Strict):
    """Which connections this deployment can offer, for the Connections screen."""

    google_calendar: bool
    #: Connecting Google Sheets needs the OAuth app AND the Picker's key and project number.
    google_sheets: bool
    zoho_crm: bool
    hubspot: bool


@router.get(
    "/integrations/connections/status",
    response_model=ConnectionsStatusOut,
    openapi_extra=permission_meta("org:read"),
    summary="Which accounts can be connected on this deployment",
)
async def connections_status(_: Principal = Depends(requires("org:read"))) -> ConnectionsStatusOut:
    return ConnectionsStatusOut(
        google_calendar=oauth.configured("google_calendar"),
        zoho_crm=oauth.configured("zoho_crm"),
        hubspot=oauth.configured("hubspot"),
        google_sheets=gsheets.picker_configured(),
    )


class SheetsPickerOut(Strict):
    """What Google's Picker needs in the browser to show this owner their spreadsheets.

    The access token is short-lived and carries only `drive.file`, which is what the
    Picker uses to share the picked file with Calevate; it is minted from the account's
    own connection and shown only to the owner who connected it.
    """

    developer_key: str
    app_id: str
    access_token: str


@router.post(
    "/integrations/google-sheets/{credential_id}/picker",
    response_model=SheetsPickerOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Open Google's file picker on the connected Google account",
)
async def sheets_picker(
    credential_id: UUID,
    session: Session,
    principal: Principal = Depends(requires("org:manage")),
) -> SheetsPickerOut:
    tenant_id = _owner_only(principal)
    settings = get_settings()
    # Ownership before configuration, so a neighbour's id is a 404 on every deployment.
    kind = await creds.credential_kind(session, credential_id=credential_id)
    if kind != "google_sheets":
        raise ProblemError.not_found("Connect Google Sheets first.")
    if not gsheets.picker_configured():
        raise oauth.unavailable("google_sheets")
    try:
        resolved = await creds.resolve_credential(
            session, tenant_id=tenant_id, credential_id=credential_id
        )
    except creds.CredentialUnusableError:
        resolved = None
    token = None
    if resolved is not None:
        async with egress_client(timeout=10.0) as http:
            token = await access_token_for(resolved, credential_id=credential_id, client=http)
    if token is None:
        raise ProblemError(
            kind="business_rule",
            code="sheets_connection_lapsed",
            title="Google Sheets needs reconnecting",
            detail="Your Google account no longer lets Calevate open its file picker.",
            remediation="Disconnect Google Sheets and connect it again.",
        )
    return SheetsPickerOut(
        developer_key=settings.google_picker_api_key or "",
        app_id=settings.google_cloud_project_number or "",
        access_token=token,
    )


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
    kind: Literal[
        "custom_api", "whatsapp", "calendar", "sheets", "payment_link", "crm", "caller_lookup"
    ]
    provider: str | None = None
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2000)
    trigger: Literal["during_call", "after_call"] = "during_call"
    pre_call_message: str | None = Field(default=None, max_length=200)
    credential_id: UUID | None = None
    # A tool's parameters are a hand-authored binding list, but still caller-controlled, and
    # `ToolOut.params` echoes them in full — so the count is bounded on the request model
    # rather than left to grow (`scripts/check_list_bounds.py`, D-302).
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
    summary="The master 'Enable actions' switch — live calls follow at once",
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
    if payload.enabled:
        assert_view_as_may(principal, "actions.switch_on")
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
    await sync_client_actions_now(session, agent_id=agent_id)
    return await list_agent_actions(agent_id, session, principal)


@router.post(
    "/agents/{agent_id}/actions",
    response_model=ToolOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Add an in-call action to an agent (off when set up in view-as)",
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
        # An operator may set an action up; switching it on is the owner's.
        enabled=not principal.impersonating,
    )
    await write_audit(
        session,
        action="action_tool.created",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="action_tool",
        object_id=str(tool.id),
        ip=client_request_ip(request),
        summary={"kind": tool.kind, "name": tool.name, "enabled": str(tool.enabled)},
    )
    await sync_client_actions_now(session, agent_id=agent_id)
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
    if await service.get_agent_tool(session, agent_id=agent_id, tool_id=tool_id) is None:
        raise ProblemError.not_found("Action")
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
    await sync_client_actions_now(session, agent_id=agent_id)
    return _tool_out(tool)


@router.put(
    "/agents/{agent_id}/actions/{tool_id}/enabled",
    response_model=ToolOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Switch one action on or off — live calls follow at once",
)
async def set_action_enabled(
    agent_id: UUID,
    tool_id: UUID,
    payload: EnableIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> ToolOut:
    assert principal.tenant_id is not None
    await _assert_agent(session, agent_id)
    if payload.enabled:
        assert_view_as_may(principal, "actions.switch_on")
    if not await service.set_enabled(
        session, agent_id=agent_id, tool_id=tool_id, enabled=payload.enabled
    ):
        raise ProblemError.not_found("Action")
    await write_audit(
        session,
        action="action_tool.enabled" if payload.enabled else "action_tool.disabled",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="action_tool",
        object_id=str(tool_id),
        ip=client_request_ip(request),
    )
    await sync_client_actions_now(session, agent_id=agent_id)
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
    if not await service.delete_tool(session, agent_id=agent_id, tool_id=tool_id):
        raise ProblemError.not_found("Action")
    await write_audit(
        session,
        action="action_tool.deleted",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="action_tool",
        object_id=str(tool_id),
        ip=client_request_ip(request),
    )
    await sync_client_actions_now(session, agent_id=agent_id)


# ============================================================= test harness ====


class TestActionIn(Strict):
    """Sample values for the agent-filled params, to run the action before a caller does."""

    values: dict[str, Any] = Field(default_factory=dict, max_length=service.MAX_TOOL_PARAMS)
    #: The number a test treats as the caller's: one of the business's own contact numbers
    #: for a WhatsApp or payment-link test ("send a test WhatsApp to my number").
    test_phone: str | None = Field(default=None, max_length=20)


class TestActionOut(Strict):
    ok: bool
    status: str
    payload: dict[str, Any]


@router.post(
    "/agents/{agent_id}/actions/{tool_id}/test",
    response_model=TestActionOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Run an action once for real with sample values (audited as a test)",
)
async def test_action(
    agent_id: UUID,
    tool_id: UUID,
    payload: TestActionIn,
    session: Session,
    _: Principal = Depends(requires("org:manage")),
) -> TestActionOut:
    """The Test button. Executes the real external call with the client's sample values so a
    misconfiguration is caught before a caller triggers it, audited as `source="test"`. A
    WhatsApp or payment-link test goes only to one of the business's own contact numbers."""
    await _assert_agent(session, agent_id)
    tool = await service.get_agent_tool(session, agent_id=agent_id, tool_id=tool_id)
    if tool is None:
        raise ProblemError.not_found("Action")
    result = await execute_action(
        session,
        tool=tool,
        received=payload.values,
        source="test",
        call=CallFacts(
            call_ref=f"test-{uuid7()}", caller_e164=payload.test_phone, direction="test"
        ),
    )
    return TestActionOut(ok=result.ok, status=result.status, payload=result.payload)


class InvocationOut(Strict):
    at: str
    source: str
    status: str
    duration_ms: int | None


@router.get(
    "/agents/{agent_id}/actions/{tool_id}/log",
    response_model=list[InvocationOut],
    openapi_extra=permission_meta("org:read"),
    summary="The most recent runs of one action: when, from where, and the outcome",
)
async def action_log(
    agent_id: UUID,
    tool_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=INVOCATION_LOG_LIMIT)] = INVOCATION_LOG_LIMIT,
    _: Principal = Depends(requires("org:read")),
) -> list[InvocationOut]:
    await _assert_agent(session, agent_id)
    rows = (
        await session.execute(
            text(
                "SELECT created_at, source, status, duration_ms FROM action_invocations "
                "WHERE tool_id = :tool AND agent_id = :agent ORDER BY created_at DESC LIMIT :n"
            ),
            {"tool": tool_id, "agent": agent_id, "n": limit},
        )
    ).all()
    return [
        InvocationOut(at=r[0].isoformat(), source=str(r[1]), status=str(r[2]), duration_ms=r[3])
        for r in rows
    ]


# ============================================================= calendar oauth ==
# The Calendar connection's original routes, kept for the screens that call them; both
# are the generic OAuth flow above for `google_calendar`.


class CalendarConnectOut(Strict):
    authorize_url: str


@router.get(
    "/actions/calendar/connect",
    response_model=CalendarConnectOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Begin Google Calendar OAuth — returns the consent URL",
)
async def calendar_connect(
    principal: Principal = Depends(requires("org:manage")),
) -> CalendarConnectOut:
    if not calendar_configured():
        raise calendar_unavailable()
    out = await oauth_connect("google_calendar", principal)
    return CalendarConnectOut(authorize_url=out.authorize_url)


class CalendarCallbackIn(Strict):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=2048)
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
    return await complete_oauth(
        session,
        request,
        principal,
        kind="google_calendar",
        payload=OAuthCallbackIn(code=payload.code, state=payload.state, label=payload.label),
        refusal=calendar_state_refused(),
    )


__all__ = ["router"]
