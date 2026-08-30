"""Action-tool CRUD, validation, and the publish-time engine declaration.

This module owns the RULES of the ACTIONS feature that are not vendor-specific:
what a valid tool looks like, how its parameter bindings cross-check against its config,
which tools become engine functions at publish, and how a stored tool is loaded for
execution. The vendor rendering is in `engine/bolna.py` (hard rule 2); the external calls
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

from apps.api.actions.models import ACTION_KINDS, ACTION_PROVIDERS, ACTION_TRIGGERS
from apps.api.actions.schema import (
    CALL_VARS,
    CalendarConfig,
    CustomApiConfig,
    ParamSpec,
    WhatsAppConfig,
)
from apps.api.core.errors import ProblemError, validation_fields
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.integrations.egress_guard import assert_public_http_url

# A function name the LLM can call and Bolna accepts: snake_case, so it cannot collide with
# the format specifiers or carry spaces (custom-function-calls.md best practice, "use
# snake_case e.g. get_order_status").
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

# Ceilings on the caller-controlled counts this feature exposes in a response. A tenant mints
# tools (like endpoints or knowledge sources), and `ActionsSettingsOut.tools` /
# `ToolOut.params` echo the stored rows in full — so the counts get a stated bound rather
# than trusting that operators keep them small (`scripts/check_list_bounds.py`, D-302). Both
# are generous relative to any real agent; a request past them is misuse, not a shape we
# materialise. `MAX_TOOL_PARAMS` also bounds the request model in `actions/routes.py`.
MAX_TOOLS_PER_AGENT = 100
MAX_TOOL_PARAMS = 50

# The WhatsApp providers the WhatsApp kind may use, and the calendar providers the calendar
# kind may use. Derived from the shared enum so a new provider is added in one place.
_WHATSAPP_PROVIDERS = ("aisensy", "meta_cloud", "interakt", "custom")
_CALENDAR_PROVIDERS = ("google",)


@dataclass(frozen=True, slots=True)
class LoadedTool:
    """A stored tool parsed for execution — what the voice-runtime endpoint and the
    post-call worker both need, with no ORM object crossing the boundary."""

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


def _parse_config(
    kind: str, config: dict[str, Any]
) -> CustomApiConfig | WhatsAppConfig | CalendarConfig:
    """Validate a raw config dict against its kind's model, as a client-facing refusal."""
    try:
        if kind == "custom_api":
            return CustomApiConfig.model_validate(config)
        if kind == "whatsapp":
            return WhatsAppConfig.model_validate(config)
        return CalendarConfig.model_validate(config)
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
            detail="One or more fields are invalid.",
            fields=validation_fields(exc),
            remediation="Check the fields for this integration and try again.",
        ) from exc


def _validate(
    *,
    kind: str,
    provider: str | None,
    name: str,
    trigger: str,
    params_raw: list[dict[str, Any]],
    config_raw: dict[str, Any],
) -> tuple[list[ParamSpec], CustomApiConfig | WhatsAppConfig | CalendarConfig]:
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
    if not _NAME_RE.match(name):
        raise ProblemError(
            kind="validation",
            code="action_name_invalid",
            title="That tool name will not work",
            detail="A tool name must be snake_case: lowercase letters, digits and underscores.",
            remediation="For example: send_price_list or book_appointment.",
        )
    # Provider is required for whatsapp/calendar, forbidden for custom_api.
    if kind == "whatsapp" and provider not in _WHATSAPP_PROVIDERS:
        raise ProblemError.business_rule(
            "action_provider_required",
            "A WhatsApp action needs a provider (AiSensy, Meta Cloud, Interakt or custom).",
            remediation=f"Use one of: {', '.join(_WHATSAPP_PROVIDERS)}.",
        )
    if kind == "calendar" and provider not in _CALENDAR_PROVIDERS:
        raise ProblemError.business_rule(
            "action_provider_required",
            "A calendar action needs a provider.",
            remediation=f"Use one of: {', '.join(_CALENDAR_PROVIDERS)}.",
        )
    if kind == "custom_api" and provider is not None:
        raise ProblemError.business_rule(
            "action_provider_unexpected",
            "A custom API action takes no provider.",
            remediation="Leave the provider unset for a custom API action.",
        )
    if provider is not None and provider not in ACTION_PROVIDERS:
        raise ProblemError.business_rule(
            "action_provider_unknown",
            f"{provider!r} is not a known provider.",
            remediation=f"Use one of: {', '.join(ACTION_PROVIDERS)}.",
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
    known = set(names)
    config = _parse_config(kind, config_raw)
    _cross_check(kind, config, known)
    return params, config


def _cross_check(
    kind: str, config: CustomApiConfig | WhatsAppConfig | CalendarConfig, known: set[str]
) -> None:
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

    if isinstance(config, CustomApiConfig):
        for field in (*config.headers, *config.query, *config.body):
            require(field.param)
    elif isinstance(config, WhatsAppConfig):
        require(config.recipient_param)
        require(config.header_param)
        for name in config.body_params:
            require(name)
    else:  # CalendarConfig
        require(config.start_param)
        require(config.end_param)
        require(config.summary_param)


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

    ═══ THE ROUTES CLAIMED THIS CHECK AND DID NOT MAKE IT. ═══

    `routes.invoke_action` carried the comment "Also refuse a disabled tool or one
    belonging to a different agent than the ref resolved" above a line that read
    `if tool is None or not tool.enabled`. There was no agent comparison anywhere: the
    bridge query selected `tenant_id` only, and `get_tool` is a bare `WHERE id = :id`.
    So an in-call tool call carrying agent A's ref could execute a tool configured for
    agent B — including one on an agent whose actions are switched off — and use that
    tool's `integration_credentials` through a binding nobody verified. The three sibling
    routes (`enabled`, `delete`, `test`) had the same shape: `_assert_agent` proved the
    AGENT was the caller's and then the tool was fetched by id, so any agent id in the
    URL paired with any tool id.

    RLS keeps this inside one tenant, so it is not a cross-tenant hole (hard rule 1 is
    intact). What it broke is that the URL did not mean what it said, and a comment
    asserted a control that was never written — which is the more expensive half, because
    the next reader budgets for it.

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
) -> LoadedTool:
    parsed_params, parsed_config = _validate(
        kind=kind,
        provider=provider,
        name=name,
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
    if isinstance(parsed_config, CustomApiConfig):
        # SSRF-vet the external URL before the row exists — and again at execution, because
        # the tenant owns that name's DNS (egress_guard's TOCTOU argument).
        await assert_public_http_url(parsed_config.url, field="config.url")
    tool_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO action_tools (id, tenant_id, agent_id, kind, provider, name, "
            "description, enabled, trigger, pre_call_message, credential_id, config, params, "
            "created_at, updated_at) VALUES (:id, :tid, :aid, :kind, :prov, :name, :desc, "
            "true, :trig, :pcm, :cid, CAST(:config AS jsonb), CAST(:params AS jsonb), "
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
        ),
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
    parsed_params, parsed_config = _validate(
        kind=kind,
        provider=provider,
        name=name,
        trigger=trigger,
        params_raw=params,
        config_raw=config,
    )
    if isinstance(parsed_config, CustomApiConfig):
        await assert_public_http_url(parsed_config.url, field="config.url")
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
    config: CustomApiConfig | WhatsAppConfig | CalendarConfig,
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


def action_tool_url(engine: str, tool_id: UUID) -> str:
    """The apps/api endpoint Bolna calls for this tool. ONE spelling, shared with the route
    that serves it (`apps/api/actions/routes.invoke_action`).

    It is apps/api, NOT voice-runtime: executing a data-returning action makes a synchronous
    external call plus a credential decrypt, which hard rule 3 keeps off the latency-critical
    receiver. `actions_callback_base_url` is that origin (see the setting)."""
    base = get_settings().actions_callback_base_url.rstrip("/")
    return f"{base}/v1/actions/invoke/{engine}/{tool_id}"


def _context_ref(lead_var: str, direction: str) -> str:
    """The Bolna system variable a lead-var binding substitutes, resolved per direction.

    `caller_phone` is the other party on the call, which is `from_number` on an inbound
    call and `to_number` on an outbound one (using-context.md:47-49). A `both`-direction
    agent cannot be resolved statically; it falls back to `from_number` (the inbound case,
    which is where a during-call WhatsApp send almost always happens) — documented rather
    than silent.
    """
    if lead_var == "caller_phone":
        return "{to_number}" if direction == "outbound" else "{from_number}"
    return CALL_VARS[lead_var]


async def declare(
    session: AsyncSession, *, agent_id: UUID, engine: str, direction: str
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
        specs.append(_to_spec(tool, engine=engine, direction=direction))
    return tuple(specs)


def _to_spec(tool: LoadedTool, *, engine: str, direction: str) -> ActionToolSpec:
    """One stored tool → the engine-facing `ActionToolSpec`.

    Only `ai` and `lead_var` params become engine parameter slots; `static` ones are
    applied by our executor and never sent. The tool's `name`/`description`/pre-call line
    carry through; `description` already holds the during-call condition for WhatsApp.
    """
    engine_params: list[ActionToolParam] = []
    for raw in tool.params:
        spec = ParamSpec.model_validate(raw)
        if spec.source == "ai":
            engine_params.append(
                ActionToolParam(
                    name=spec.name,
                    fill="ai",
                    type=spec.type,
                    description=spec.description,
                    required=spec.required,
                )
            )
        elif spec.source == "lead_var":
            assert spec.lead_var is not None
            engine_params.append(
                ActionToolParam(
                    name=spec.name,
                    fill="context",
                    context_ref=_context_ref(spec.lead_var, direction),
                )
            )
    # Always inject the agent ref so our endpoint can resolve the tenant WITHOUT a session
    # (the tool endpoint is unauthenticated + source-IP gated, like the webhook receiver).
    # Bolna substitutes `{agent_id}` — its own agent id, which is our `engine_agent_ref` —
    # and `apps/api/actions/routes.invoke_action` maps it through `engine_agent_routes`
    # (the same non-RLS bridge the webhook path uses) to the tenant, then loads the tool
    # under that tenant's RLS. A reserved underscore name so no client param collides.
    engine_params.append(
        ActionToolParam(name="_agent_ref", fill="context", context_ref="{agent_id}")
    )
    # The (agent, name) unique index guarantees the function name is unique within the one
    # agent this declaration is for, which is the scope the engine resolves calls in.
    return ActionToolSpec(
        name=tool.name,
        description=tool.description,
        pre_call_message=tool.pre_call_message,
        method="POST",
        url=action_tool_url(engine, tool.id),
        params=tuple(engine_params),
    )


__all__ = [
    "LoadedTool",
    "action_tool_url",
    "actions_enabled",
    "create_tool",
    "declare",
    "delete_tool",
    "get_agent_tool",
    "get_tool",
    "list_tools",
    "set_actions_enabled",
    "set_enabled",
    "update_tool",
]
