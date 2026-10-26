"""An agent's in-call actions, changed: the writes behind the Actions tab's buttons and Pip's
`agent_action_*` tools (D-700, D-893).

Each function is the service step plus the re-sync of the live agent's vendor actions
(`reliability/engine_actions.sync_client_actions_now`), so a switched-off action leaves a live
agent in the same request whichever door changed it. The audit row stays with the caller:
the route writes its own, and Pip's framework writes the tool's.

View-as (D-587, D-700): an operator may set an action up and switch it off, never switch one
on, so an action an operator creates or edits is left off. `impersonating` carries that.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import service
from apps.api.core.errors import ProblemError
from apps.api.reliability.engine_actions import sync_client_actions_now


async def assert_agent(session: AsyncSession, agent_id: UUID) -> None:
    """The agent must belong to this tenant (RLS) and exist. A tool for an agent the caller
    cannot see is 404, indistinguishable from one that never existed."""
    row = (
        await session.execute(
            text("SELECT 1 FROM agents WHERE id = :id AND deleted_at IS NULL"), {"id": agent_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")


async def add_action(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    impersonating: bool,
    kind: str,
    provider: str | None,
    name: str,
    description: str,
    trigger: str,
    pre_call_message: str | None,
    credential_id: UUID | None,
    params: list[dict[str, Any]],
    config: dict[str, Any],
) -> service.LoadedTool:
    await assert_agent(session, agent_id)
    tool = await service.create_tool(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        kind=kind,
        provider=provider,
        name=name,
        description=description,
        trigger=trigger,
        pre_call_message=pre_call_message,
        credential_id=credential_id,
        params=params,
        config=config,
        # An operator may set an action up; switching it on is the owner's.
        enabled=not impersonating,
    )
    await sync_client_actions_now(session, agent_id=agent_id)
    return tool


async def edit_action(
    session: AsyncSession,
    *,
    agent_id: UUID,
    tool_id: UUID,
    impersonating: bool,
    kind: str,
    provider: str | None,
    name: str,
    description: str,
    trigger: str,
    pre_call_message: str | None,
    credential_id: UUID | None,
    params: list[dict[str, Any]],
    config: dict[str, Any],
) -> service.LoadedTool:
    await assert_agent(session, agent_id)
    if await service.get_agent_tool(session, agent_id=agent_id, tool_id=tool_id) is None:
        raise ProblemError.not_found("Action")
    tool = await service.update_tool(
        session,
        tool_id=tool_id,
        kind=kind,
        provider=provider,
        name=name,
        description=description,
        trigger=trigger,
        pre_call_message=pre_call_message,
        credential_id=credential_id,
        params=params,
        config=config,
    )
    # An operator's edit switches the action off, the rule `add_action` applies to a new one.
    # Otherwise view-as could re-point a live action — its URL and the stored key sent with
    # it — without the owner ever switching that configuration on.
    if impersonating and tool.enabled:
        await service.set_enabled(session, agent_id=agent_id, tool_id=tool_id, enabled=False)
        reread = await service.get_agent_tool(session, agent_id=agent_id, tool_id=tool_id)
        assert reread is not None
        tool = reread
    await sync_client_actions_now(session, agent_id=agent_id)
    return tool


async def switch_action(
    session: AsyncSession, *, agent_id: UUID, tool_id: UUID, enabled: bool
) -> service.LoadedTool:
    """One action on or off. The caller checks view-as may switch ON (`actions.switch_on`)."""
    await assert_agent(session, agent_id)
    if not await service.set_enabled(session, agent_id=agent_id, tool_id=tool_id, enabled=enabled):
        raise ProblemError.not_found("Action")
    await sync_client_actions_now(session, agent_id=agent_id)
    tool = await service.get_agent_tool(session, agent_id=agent_id, tool_id=tool_id)
    assert tool is not None
    return tool


async def switch_all(session: AsyncSession, *, agent_id: UUID, enabled: bool) -> None:
    """The agent's master "Enable actions" switch."""
    await assert_agent(session, agent_id)
    await service.set_actions_enabled(session, agent_id=agent_id, enabled=enabled)
    await sync_client_actions_now(session, agent_id=agent_id)


async def remove_action(session: AsyncSession, *, agent_id: UUID, tool_id: UUID) -> None:
    await assert_agent(session, agent_id)
    if not await service.delete_tool(session, agent_id=agent_id, tool_id=tool_id):
        raise ProblemError.not_found("Action")
    await sync_client_actions_now(session, agent_id=agent_id)


__all__ = [
    "add_action",
    "assert_agent",
    "edit_action",
    "remove_action",
    "switch_action",
    "switch_all",
]
