"""Action-tool CRUD, validation, and the publish-time engine declaration.

This module owns the RULES of the ACTIONS feature that are not vendor-specific:
what a valid tool looks like, how its parameter bindings cross-check against its config,
which tools become engine functions at publish, and how a stored tool is loaded for
execution. The vendor rendering is an adapter's (hard rule 2); the external calls
are in `whatsapp.py` / `calendar.py` / the custom-API path in `execution.py`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from calevate_shared.engine import ActionToolParam, ActionToolSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions.credentials import credential_kind
from apps.api.actions.models import ACTION_KINDS, ACTION_PROVIDERS, ACTION_TRIGGERS
from apps.api.actions.schema import (
    CalendarConfig,
    CallerLookupConfig,
    CrmConfig,
    CustomApiConfig,
    ParamSpec,
    PaymentLinkConfig,
    SheetsConfig,
    WhatsAppConfig,
)
from apps.api.core.errors import ProblemError, validation_fields
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible
from apps.api.db.result import rowcount_of
from apps.api.integrations.egress_guard import assert_public_http_url

# A function name the LLM can call. The voice platform's own rule, because every enabled
# during-call action becomes one of its custom actions under this name: 3 to 40 characters,
# lower case letters, numbers and underscores, starting with a letter
# (thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/actions/
# create-action.md, `name` pattern `^[a-z][a-z0-9_]{2,39}$`).
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")

#: Names a client action may not take: the platform's built-in tools, which it refuses
#: (agent/custom-api.md:123-124), and our own in-call actions
#: (`reliability/engine_actions.ACTION_NAMES`), which a client action would shadow.
RESERVED_ACTION_NAMES: frozenset[str] = frozenset(
    {
        "search_knowledge",
        "capture_lead",
        "escalate_to_human",
        "send_media",
        "send_link",
        "record_do_not_call",
        "schedule_call_back",
        "cancel_call_back",
        "request_human_handoff",
    }
)

# Ceilings on the caller-controlled counts this feature exposes in a response. A tenant mints
# tools (like endpoints or knowledge sources), and `ActionsSettingsOut.tools` /
# `ToolOut.params` echo the stored rows in full — so the counts get a stated bound rather
# than trusting that operators keep them small (`scripts/check_list_bounds.py`, D-302). Both
# are generous relative to any real agent; a request past them is misuse, not a shape we
# materialise. `MAX_TOOL_PARAMS` also bounds the request model in `actions/routes.py`.
MAX_TOOLS_PER_AGENT = 100
MAX_TOOL_PARAMS = 50
#: The voice platform takes up to 20 parameters on an action (create-action.md,
#: `parameters.maxItems`); the agent-filled ones are what it declares.
MAX_AGENT_FILLED_PARAMS = 20
#: The voice platform's floor for an action description (create-action.md, `description`
#: minLength 10): the model decides whether to call the action from this alone.
MIN_DESCRIPTION_CHARS = 10

#: Which providers each action kind may name. `None` in a set means "no provider".
_KIND_PROVIDERS: dict[str, frozenset[str | None]] = {
    "custom_api": frozenset({None}),
    "whatsapp": frozenset({"aisensy", "meta_cloud", "interakt", "custom"}),
    "calendar": frozenset({"google"}),
    "sheets": frozenset({None}),
    "payment_link": frozenset({"razorpay"}),
    "crm": frozenset({"zoho", "hubspot"}),
    "caller_lookup": frozenset({"zoho", "hubspot", "sheet", "api"}),
}

#: The saved-credential kind each (action kind, provider) must use; absent means the action
#: takes no credential of its own.
_CREDENTIAL_KIND: dict[tuple[str, str | None], str] = {
    ("custom_api", None): "custom_api",
    ("whatsapp", "aisensy"): "aisensy",
    ("whatsapp", "meta_cloud"): "meta_cloud",
    ("whatsapp", "interakt"): "interakt",
    ("calendar", "google"): "google_calendar",
    ("sheets", None): "google_sheets",
    ("caller_lookup", "sheet"): "google_sheets",
    ("payment_link", "razorpay"): "razorpay",
    ("crm", "zoho"): "zoho_crm",
    ("crm", "hubspot"): "hubspot",
    ("caller_lookup", "zoho"): "zoho_crm",
    ("caller_lookup", "hubspot"): "hubspot",
    ("caller_lookup", "api"): "custom_api",
}
#: Kinds whose credential is REQUIRED (the custom API's is optional: an open endpoint).
_CREDENTIAL_REQUIRED: frozenset[tuple[str, str | None]] = frozenset(
    key for key in _CREDENTIAL_KIND if key not in {("custom_api", None), ("caller_lookup", "api")}
)
#: Kinds that only make sense while the caller is on the line.
_DURING_CALL_ONLY: frozenset[str] = frozenset({"caller_lookup", "payment_link"})

ActionConfig = (
    CustomApiConfig
    | WhatsAppConfig
    | CalendarConfig
    | SheetsConfig
    | PaymentLinkConfig
    | CrmConfig
    | CallerLookupConfig
)
_CONFIG_MODELS: dict[str, type[ActionConfig]] = {
    "custom_api": CustomApiConfig,
    "whatsapp": WhatsAppConfig,
    "calendar": CalendarConfig,
    "sheets": SheetsConfig,
    "payment_link": PaymentLinkConfig,
    "crm": CrmConfig,
    "caller_lookup": CallerLookupConfig,
}


@dataclass(frozen=True, slots=True)
class LoadedTool:
    """A stored tool parsed for execution — what every in-call door and the background
    job need, with no ORM object crossing the boundary."""

    id: UUID
    tenant_id: UUID
    agent_id: UUID
    kind: str
    provider: str | None
    name: str
    description: str
    pre_call_message: str | None
    trigger: str
    enabled: bool
    credential_id: UUID | None
    config: dict[str, Any]
    params: list[dict[str, Any]]


def _parse_config(kind: str, config: dict[str, Any]) -> ActionConfig:
    """Validate a raw config dict against its kind's model, as a client-facing refusal."""
    try:
        return _CONFIG_MODELS[kind].model_validate(config)
    except ValueError as exc:
        # `detail=str(exc)` here round-tripped the operator's own submitted config back to
        # them, and a `custom_api` action config can contain a credential they typed — in
        # pydantic v2 `str(ValidationError)` embeds `input_value=…`. Emit the flat field
        # triple instead (field name + rule, value dropped), which is what they need to fix
        # it, via the one converter the global validation handler's shape comes from.
        raise ProblemError(
            kind="validation",
            code="action_config_invalid",
            title="That action is not configured correctly",
            detail="Some of the settings for this action need another look.",
            fields=validation_fields(exc),
            remediation="Check the highlighted settings and save again.",
        ) from exc


def _validate(
    *,
    kind: str,
    provider: str | None,
    name: str,
    description: str,
    trigger: str,
    params_raw: list[dict[str, Any]],
    config_raw: dict[str, Any],
) -> tuple[list[ParamSpec], ActionConfig]:
    """Every rule a tool must satisfy before it can be stored, as actionable refusals."""
    if kind not in ACTION_KINDS:
        raise ProblemError.business_rule(
            "action_kind_unknown",
            f"{kind!r} is not an action type.",
            remediation=f"Use one of: {', '.join(ACTION_KINDS)}.",
        )
    if trigger not in ACTION_TRIGGERS:
        raise ProblemError.business_rule(
            "action_trigger_unknown",
            f"{trigger!r} is not a valid trigger.",
            remediation=f"Use one of: {', '.join(ACTION_TRIGGERS)}.",
        )
    if trigger == "after_call" and kind in _DURING_CALL_ONLY:
        raise ProblemError.business_rule(
            "action_during_call_only",
            "This action only works while the caller is on the line.",
            remediation="Set it to run during the call.",
        )
    if not _NAME_RE.match(name):
        raise ProblemError(
            kind="validation",
            code="action_name_invalid",
            title="That action name will not work",
            detail=(
                "An action name must be 3 to 40 characters: lowercase letters, digits and "
                "underscores, starting with a letter."
            ),
            remediation="For example: send_price_list or book_a_slot.",
        )
    if len(description.strip()) < MIN_DESCRIPTION_CHARS:
        raise ProblemError(
            kind="validation",
            code="action_description_too_short",
            title="Say a little more about when to use this",
            detail=(
                f"The agent decides from this sentence alone; write at least "
                f"{MIN_DESCRIPTION_CHARS} characters."
            ),
            remediation="Say when the agent should use it, and when not to.",
        )
    if name in RESERVED_ACTION_NAMES:
        raise ProblemError(
            kind="validation",
            code="action_name_reserved",
            title="That name is already used by the agent",
            detail="Your agent already has a built-in ability with this name.",
            remediation="Choose a different name for this action.",
        )
    if provider is not None and provider not in ACTION_PROVIDERS:
        raise ProblemError.business_rule(
            "action_provider_unknown",
            f"{provider!r} is not a known provider.",
            remediation=f"Use one of: {', '.join(ACTION_PROVIDERS)}.",
        )
    allowed = _KIND_PROVIDERS[kind]
    if provider not in allowed:
        choices = sorted(p for p in allowed if p is not None)
        raise ProblemError.business_rule(
            "action_provider_required" if choices else "action_provider_unexpected",
            "This action needs a provider." if choices else "This action takes no provider.",
            remediation=(
                f"Use one of: {', '.join(choices)}." if choices else "Leave the provider unset."
            ),
        )

    params = [ParamSpec.model_validate(p) for p in params_raw]
    names = [p.name for p in params]
    if len(names) != len(set(names)):
        raise ProblemError(
            kind="validation",
            code="action_param_duplicate",
            title="Two parameters share a name",
            detail="Each parameter must have a unique name within an action.",
            remediation="Rename the duplicate.",
        )
    if "call_id" in names:
        # Our body template names the call `call_id`, filled by the platform; a client
        # parameter of that name would be overwritten by it, or overwrite it.
        raise ProblemError(
            kind="validation",
            code="action_param_reserved",
            title="That parameter name is reserved",
            detail="`call_id` is filled in by Calevate on every call.",
            remediation="Rename the parameter.",
        )
    if sum(1 for p in params if p.source == "ai") > MAX_AGENT_FILLED_PARAMS:
        raise ProblemError.business_rule(
            "action_too_many_questions",
            f"An action may ask the agent for at most {MAX_AGENT_FILLED_PARAMS} values.",
            remediation="Remove some of the values the agent collects.",
        )
    known = set(names)
    config = _parse_config(kind, config_raw)
    _cross_check(config, known, provider=provider)
    return params, config


def _cross_check(config: ActionConfig, known: set[str], *, provider: str | None) -> None:
    """Every binding NAME a config references must exist in `params`. A config that names a
    binding nobody defined is a request field that would be silently dropped."""

    def require(name: str | None) -> None:
        if name is not None and name not in known:
            raise ProblemError(
                kind="validation",
                code="action_param_unbound",
                title="An action field points at a missing parameter",
                detail=f"The field references parameter {name!r}, which is not defined.",
                remediation="Add the parameter, or point the field at an existing one.",
            )

    def needs(field: str, present: object) -> None:
        if not present:
            raise ProblemError(
                kind="validation",
                code="action_config_incomplete",
                title="That action is missing a setting",
                detail=f"This kind of action needs {field}.",
                remediation="Fill it in and save again.",
            )

    if isinstance(config, CustomApiConfig):
        for field in (*config.headers, *config.query, *config.body):
            require(field.param)
    elif isinstance(config, WhatsAppConfig):
        require(config.recipient_param)
        require(config.header_param)
        for name in config.body_params:
            require(name)
    elif isinstance(config, CalendarConfig):
        require(config.start_param)
        require(config.end_param)
        require(config.summary_param)
    elif isinstance(config, SheetsConfig):
        for column in config.columns:
            require(column.param)
    elif isinstance(config, PaymentLinkConfig):
        require(config.amount_param)
    elif isinstance(config, CrmConfig):
        for crm_field in config.fields:
            require(crm_field.param)
        valid = ("Leads", "Contacts") if provider == "zoho" else ("contacts",)
        if config.module not in valid:
            raise ProblemError.business_rule(
                "crm_module_invalid",
                "That record type does not exist in this CRM.",
                remediation=f"Use one of: {', '.join(valid)}.",
            )
    elif provider == "sheet":
        needs("the spreadsheet", config.spreadsheet_id)
        needs("the sheet tab", config.worksheet)
        needs("the phone number column", config.match_header)
        needs("the columns to read", config.return_headers)
    elif provider == "api":
        needs("the address", config.url)
        if not (config.url or "").lower().startswith("https://"):
            raise ProblemError(
                kind="validation",
                code="action_url_not_https",
                title="The address must be secure",
                detail="Only https:// addresses can be called during a call.",
                remediation="Use the https:// address of your API.",
            )


async def _assert_credential_fits(
    session: AsyncSession,
    *,
    kind: str,
    provider: str | None,
    credential_id: UUID | None,
    config: ActionConfig,
) -> None:
    """The credential must be this tenant's AND of the vendor this action talks to: an AiSensy
    key on a Meta action would send one vendor's secret to another.

    Proved BEFORE anything is written: RLS cannot do it, because the FK from
    `action_tools.credential_id` is checked by a system trigger that bypasses row security,
    so a caller-supplied id belonging to another tenant would otherwise be stored as a live
    cross-tenant reference. `assert_visible` answers 404, the doctrine every other
    caller-supplied ref in this tree follows.
    """
    await assert_visible(session, "credential", credential_id)
    expected = _CREDENTIAL_KIND.get((kind, provider))
    if credential_id is None:
        if (kind, provider) in _CREDENTIAL_REQUIRED:
            raise ProblemError.business_rule(
                "action_credential_required",
                "This action needs a connected account.",
                remediation="Connect the account on the Connections screen, then choose it here.",
            )
    elif (
        expected is None or await credential_kind(session, credential_id=credential_id) != expected
    ):
        raise ProblemError.business_rule(
            "action_credential_wrong_kind",
            "That connected account is for a different service.",
            remediation="Choose the account for the service this action uses.",
        )
    if isinstance(config, PaymentLinkConfig):
        message = config.message
        await assert_visible(session, "credential", message.credential_id)
        if await credential_kind(session, credential_id=message.credential_id) != message.provider:
            raise ProblemError.business_rule(
                "action_credential_wrong_kind",
                "The WhatsApp account chosen for the payment message is for a different service.",
                remediation="Choose the WhatsApp account that matches the provider.",
            )


async def _vet_urls(config: ActionConfig) -> None:
    """SSRF-vet a client-chosen address before the row exists — and again at execution,
    because the tenant owns that name's DNS (egress_guard's TOCTOU argument)."""
    url = config.url if isinstance(config, CustomApiConfig | CallerLookupConfig) else None
    if url:
        await assert_public_http_url(url, field="config.url")


# ---------------------------------------------------------------- CRUD ----


async def list_tools(session: AsyncSession, *, agent_id: UUID) -> list[LoadedTool]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_TOOL_COLUMNS} FROM action_tools "
                "WHERE agent_id = :aid ORDER BY created_at"
            ),
            {"aid": agent_id},
        )
    ).all()
    return [_loaded(r) for r in rows]


async def get_tool(session: AsyncSession, *, tool_id: UUID) -> LoadedTool | None:
    """A tool by id alone, WITHIN THE TENANT (RLS).

    FOR THE WRITERS IN THIS MODULE ONLY — `create_tool` and `update_tool` re-read the row
    they just wrote inside the same transaction, where the agent is not in question. A
    ROUTE must not use this: the id in a route's URL is the caller's to choose, and this
    function cannot tell whether the tool belongs to the agent the URL also names. Use
    `get_agent_tool`, which is why it exists.
    """
    row = (
        await session.execute(
            text(f"SELECT {_TOOL_COLUMNS} FROM action_tools WHERE id = :id"),
            {"id": tool_id},
        )
    ).first()
    return _loaded(row) if row is not None else None


async def get_agent_tool(
    session: AsyncSession, *, agent_id: UUID, tool_id: UUID
) -> LoadedTool | None:
    """A tool that belongs to THIS agent, or nothing.

    The failure it prevents: `_assert_agent` proves the AGENT in a route's URL is the
    caller's, and a tool fetched by id alone (`get_tool`) then pairs any agent id with any
    tool id in the same tenant — so a route could toggle, delete or test a tool configured
    for a different agent. RLS keeps that inside one tenant (hard rule 1 is intact); what it
    breaks is that the URL does not mean what it says.

    A FILTER RATHER THAN A COMPARISON, deliberately: `... WHERE id = :id AND agent_id =
    :agent_id` cannot be forgotten by a caller the way an `if` can, and a mismatch returns
    the same `None` a deleted tool returns, so a probe cannot tell "not yours" from "not
    there" (the property `get_tool`'s RLS behaviour already provides across tenants).
    """
    row = (
        await session.execute(
            text(f"SELECT {_TOOL_COLUMNS} FROM action_tools WHERE id = :id AND agent_id = :agent"),
            {"id": tool_id, "agent": agent_id},
        )
    ).first()
    return _loaded(row) if row is not None else None


_TOOL_COLUMNS = (
    "id, tenant_id, agent_id, kind, provider, name, description, pre_call_message, "
    "trigger, enabled, credential_id, config, params"
)


def _loaded(r: Any) -> LoadedTool:
    return LoadedTool(
        id=r[0],
        tenant_id=r[1],
        agent_id=r[2],
        kind=str(r[3]),
        provider=r[4],
        name=str(r[5]),
        description=str(r[6]),
        pre_call_message=r[7],
        trigger=str(r[8]),
        enabled=bool(r[9]),
        credential_id=r[10],
        config=r[11] or {},
        params=list(r[12] or []),
    )


async def create_tool(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    kind: str,
    provider: str | None,
    name: str,
    description: str,
    trigger: str,
    pre_call_message: str | None,
    credential_id: UUID | None,
    params: list[dict[str, Any]],
    config: dict[str, Any],
    enabled: bool = True,
) -> LoadedTool:
    # Proved this tenant's before anything else (`_assert_credential_fits` says why).
    await assert_visible(session, "credential", credential_id)
    parsed_params, parsed_config = _validate(
        kind=kind,
        provider=provider,
        name=name,
        description=description,
        trigger=trigger,
        params_raw=params,
        config_raw=config,
    )
    # A per-agent ceiling so the tool list a tenant can mint (and that every Actions-tab read
    # materialises) cannot grow without bound. Counted under RLS, so it is this tenant's own
    # tools for this agent. Checked before the INSERT rather than trusting the UI.
    existing = (
        await session.execute(
            text("SELECT count(*) FROM action_tools WHERE agent_id = :aid"), {"aid": agent_id}
        )
    ).scalar_one()
    if existing >= MAX_TOOLS_PER_AGENT:
        raise ProblemError.business_rule(
            "action_tool_limit",
            f"An agent may have at most {MAX_TOOLS_PER_AGENT} actions.",
            remediation="Remove an unused action before adding another.",
        )
    await _assert_credential_fits(
        session, kind=kind, provider=provider, credential_id=credential_id, config=parsed_config
    )
    await _vet_urls(parsed_config)
    tool_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO action_tools (id, tenant_id, agent_id, kind, provider, name, "
            "description, enabled, trigger, pre_call_message, credential_id, config, params, "
            "created_at, updated_at) VALUES (:id, :tid, :aid, :kind, :prov, :name, :desc, "
            ":en, :trig, :pcm, :cid, CAST(:config AS jsonb), CAST(:params AS jsonb), "
            "now(), now())"
        ),
        _write_params(
            tool_id,
            tenant_id,
            agent_id,
            kind,
            provider,
            name,
            description,
            trigger,
            pre_call_message,
            credential_id,
            parsed_config,
            parsed_params,
        )
        | {"en": enabled},
    )
    loaded = await get_tool(session, tool_id=tool_id)
    assert loaded is not None
    return loaded


async def update_tool(
    session: AsyncSession,
    *,
    tool_id: UUID,
    kind: str,
    provider: str | None,
    name: str,
    description: str,
    trigger: str,
    pre_call_message: str | None,
    credential_id: UUID | None,
    params: list[dict[str, Any]],
    config: dict[str, Any],
) -> LoadedTool:
    existing = await get_tool(session, tool_id=tool_id)
    if existing is None:
        raise ProblemError.not_found("Action")
    # Proved this tenant's before anything else (`_assert_credential_fits` says why).
    await assert_visible(session, "credential", credential_id)
    parsed_params, parsed_config = _validate(
        kind=kind,
        provider=provider,
        name=name,
        description=description,
        trigger=trigger,
        params_raw=params,
        config_raw=config,
    )
    await _assert_credential_fits(
        session, kind=kind, provider=provider, credential_id=credential_id, config=parsed_config
    )
    await _vet_urls(parsed_config)
    await session.execute(
        text(
            "UPDATE action_tools SET kind = :kind, provider = :prov, name = :name, "
            "description = :desc, trigger = :trig, pre_call_message = :pcm, "
            "credential_id = :cid, config = CAST(:config AS jsonb), "
            "params = CAST(:params AS jsonb), updated_at = now() WHERE id = :id"
        ),
        _write_params(
            tool_id,
            existing.tenant_id,
            existing.agent_id,
            kind,
            provider,
            name,
            description,
            trigger,
            pre_call_message,
            credential_id,
            parsed_config,
            parsed_params,
        ),
    )
    loaded = await get_tool(session, tool_id=tool_id)
    assert loaded is not None
    return loaded


def _write_params(
    tool_id: UUID,
    tenant_id: UUID,
    agent_id: UUID,
    kind: str,
    provider: str | None,
    name: str,
    description: str,
    trigger: str,
    pre_call_message: str | None,
    credential_id: UUID | None,
    config: ActionConfig,
    params: list[ParamSpec],
) -> dict[str, Any]:
    return {
        "id": tool_id,
        "tid": tenant_id,
        "aid": agent_id,
        "kind": kind,
        "prov": provider,
        "name": name,
        "desc": description,
        "trig": trigger,
        "pcm": pre_call_message,
        "cid": credential_id,
        "config": config.model_dump_json(),
        "params": json.dumps([p.model_dump() for p in params]),
    }


async def set_enabled(
    session: AsyncSession, *, agent_id: UUID, tool_id: UUID, enabled: bool
) -> bool:
    """`agent_id` is REQUIRED and is in the WHERE clause — see `get_agent_tool`."""
    result = await session.execute(
        text(
            "UPDATE action_tools SET enabled = :en, updated_at = now() "
            "WHERE id = :id AND agent_id = :agent"
        ),
        {"en": enabled, "id": tool_id, "agent": agent_id},
    )
    return rowcount_of(result) == 1


async def delete_tool(session: AsyncSession, *, agent_id: UUID, tool_id: UUID) -> bool:
    """`agent_id` is REQUIRED and is in the WHERE clause — see `get_agent_tool`."""
    result = await session.execute(
        text("DELETE FROM action_tools WHERE id = :id AND agent_id = :agent"),
        {"id": tool_id, "agent": agent_id},
    )
    return rowcount_of(result) == 1


# ------------------------------------------------ master switch + publish ----


async def actions_enabled(session: AsyncSession, *, agent_id: UUID) -> bool:
    """The agent's master 'Enable API actions' switch. False (default) means no action is
    declared to the engine however many tools exist — one control disables the lot."""
    row = (
        await session.execute(
            text("SELECT api_actions_enabled FROM agents WHERE id = :id"), {"id": agent_id}
        )
    ).first()
    return bool(row[0]) if row is not None else False


async def set_actions_enabled(session: AsyncSession, *, agent_id: UUID, enabled: bool) -> bool:
    result = await session.execute(
        text("UPDATE agents SET api_actions_enabled = :en, updated_at = now() WHERE id = :id"),
        {"en": enabled, "id": agent_id},
    )
    return rowcount_of(result) == 1


async def declare(
    session: AsyncSession, *, agent_id: UUID, direction: str
) -> tuple[ActionToolSpec, ...]:
    """The DURING-CALL tools to declare to the engine at publish, or empty.

    Empty when the master switch is off — the adapter then emits no `api_tools` at all.
    After-call tools are NOT declared here: they are not engine functions, they run in the
    post-call pipeline. Disabled tools are skipped.
    """
    if not await actions_enabled(session, agent_id=agent_id):
        return ()
    specs: list[ActionToolSpec] = []
    for tool in await list_tools(session, agent_id=agent_id):
        if not tool.enabled or tool.trigger != "during_call":
            continue
        specs.append(_to_spec(tool, direction=direction))
    return tuple(specs)


def _to_spec(tool: LoadedTool, *, direction: str) -> ActionToolSpec:
    """One stored tool → the engine-facing `ActionToolSpec`.

    Only `ai` params become parameters the model fills. `static` and `lead_var` params are
    applied by our executor and never declared: a lead variable is the call's own data (the
    other party's number, the call id), which an executing route supplies from our record
    of the call rather than trusting a runtime to substitute it. `direction` is kept in the
    signature because it is the declaration's own context, and the caller already has it.
    """
    del direction
    engine_params = [
        ActionToolParam(
            name=spec.name,
            type=spec.type,
            description=spec.description,
            required=spec.required,
        )
        for spec in (ParamSpec.model_validate(raw) for raw in tool.params)
        if spec.source == "ai"
    ]
    # The (agent, name) unique index guarantees the function name is unique within the one
    # agent this declaration is for, which is the scope the engine resolves calls in.
    return ActionToolSpec(
        name=tool.name,
        description=tool.description,
        pre_call_message=tool.pre_call_message,
        params=tuple(engine_params),
    )


async def in_call_tools(session: AsyncSession, *, agent_id: UUID) -> list[LoadedTool]:
    """The during-call actions live on this agent's calls: master switch on, the action
    enabled. THE set an engine that hosts actions on its side registers (ThinnestAI,
    `reliability/engine_actions.py`) and the set an in-call door will execute from."""
    if not await actions_enabled(session, agent_id=agent_id):
        return []
    return [
        tool
        for tool in await list_tools(session, agent_id=agent_id)
        if tool.enabled and tool.trigger == "during_call"
    ]


async def in_call_tool(session: AsyncSession, *, agent_id: UUID, name: str) -> LoadedTool | None:
    """One live during-call action by its name on this agent, or None. A disabled action, or
    one whose agent has the master switch off, is not callable even if a stale vendor
    registration still points at it."""
    return next(
        (t for t in await in_call_tools(session, agent_id=agent_id) if t.name == name), None
    )


async def agents_using_credential(session: AsyncSession, *, credential_id: UUID) -> list[UUID]:
    """Agents with an action that uses this credential, directly or as a payment link's
    WhatsApp account — the agents whose voice-platform actions must be re-synced when it is
    rotated or deleted."""
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT agent_id FROM action_tools WHERE credential_id = :cid "
                "OR config -> 'message' ->> 'credential_id' = :cid_text"
            ),
            {"cid": credential_id, "cid_text": str(credential_id)},
        )
    ).all()
    return [UUID(str(r[0])) for r in rows]


__all__ = [
    "RESERVED_ACTION_NAMES",
    "ActionConfig",
    "LoadedTool",
    "actions_enabled",
    "agents_using_credential",
    "create_tool",
    "declare",
    "delete_tool",
    "get_agent_tool",
    "get_tool",
    "in_call_tool",
    "in_call_tools",
    "list_tools",
    "set_actions_enabled",
    "set_enabled",
    "update_tool",
]
