"""Each Pip surface offers a fixed tool list holding every tool that surface can run (D-816).

The before/after proof: the admin array at bdc20490 offered every client write tool and every
account read tool on every admin request. Each tool the new arrays drop is shown here to
refuse on that surface without doing anything, so nothing an operator could use was taken
away; and every tool that could run is still offered.
"""

from __future__ import annotations

import json
import uuid

import pytest

from apps.api.admin import service as admin_service
from apps.api.copilot import admin_actions, admin_screens, admin_tools, tools, write_tools
from apps.api.copilot import service as copilot_service
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.schemas import CopilotRealm
from apps.api.core.context import Principal


def _names(schemas: list[dict[str, object]]) -> list[str]:
    return [str(schema["function"]["name"]) for schema in schemas]  # type: ignore[index]


def _admin_array_before() -> list[str]:
    """The admin array as composed at bdc20490, rebuilt from the same registries."""
    return [
        "set_fields",
        *(tool.name for tool in copilot_service.realm_read_tools("admin")),
        *_names(write_tools.write_tool_schemas()),
        *_names(admin_actions.admin_action_schemas()),
        str(admin_screens.admin_open_screen_tool()["function"]["name"]),
    ]


def test_each_surface_is_one_fixed_list() -> None:
    surfaces: tuple[tuple[CopilotRealm, bool], ...] = (
        ("client", True),
        ("admin", True),
        ("admin", False),
    )
    for realm, account_open in surfaces:
        first = json.dumps(copilot_service.tool_array(realm, account_open=account_open))
        second = json.dumps(copilot_service.tool_array(realm, account_open=account_open))
        assert first == second
    assert copilot_service.tool_array("client", account_open=False) == (
        copilot_service.tool_array("client", account_open=True)
    )


def test_the_client_realm_carries_no_admin_tool() -> None:
    client = set(_names(copilot_service.tool_array("client")))
    admin_only = {tool.name for tool in admin_tools.ADMIN_READ_TOOLS} | set(
        _names(admin_actions.admin_action_schemas())
    )
    assert not client & admin_only


def test_the_admin_surfaces_drop_only_tools_that_could_not_run_there() -> None:
    before = _admin_array_before()
    open_account = _names(copilot_service.tool_array("admin", account_open=True))
    console = _names(copilot_service.tool_array("admin", account_open=False))
    write_names = set(_names(write_tools.write_tool_schemas()))
    account_reads = {
        tool.name for tool in copilot_service.realm_read_tools("admin") if tool.scope == "tenant"
    }
    print(f"\nadmin tools before: {len(before)}")
    print(f"admin with an account open: {len(open_account)}")
    print(f"admin console, no account: {len(console)}")
    print(f"client: {len(copilot_service.tool_array('client'))}")
    assert set(before) - set(open_account) == write_names
    assert set(before) - set(console) == write_names | account_reads
    assert set(open_account) <= set(before) and set(console) <= set(before)
    assert len(open_account) == len(set(open_account))
    # The two admin surfaces share their whole leading run, so the cached prefix carries over.
    assert open_account[: len(console)] == console


async def test_a_client_write_tool_refuses_every_admin_principal() -> None:
    """The two shapes an admin principal has: no tenant, or a tenant inside view-as."""
    created = await admin_service.create_organization(
        name="Surface Clinic",
        slug=f"surface-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    operator = uuid.uuid4()
    console = Principal(realm="admin", user_id=operator, tenant_id=None, role="superadmin")
    viewing = Principal(
        realm="admin",
        user_id=operator,
        tenant_id=created["id"],
        role="superadmin",
        impersonating=True,
    )
    for tool in write_tools.WRITE_TOOLS:
        for principal in (console, viewing):
            actor = write_tools.actor_for(principal)
            with pytest.raises(WriteRefusedError):
                if tool.tier == "confirm":
                    await write_tools.plan_write(tool.name, "{}", actor=actor)
                else:
                    await write_tools.run_immediate(
                        tool.name, "{}", principal=principal, seed="", ip=None
                    )


async def test_an_account_read_refuses_with_no_account_open() -> None:
    context = copilot_service.ToolContext(tenant_id=None, role="superadmin")
    registry = copilot_service._read_tool_registry("admin")
    for tool in copilot_service.realm_read_tools("admin"):
        if tool.scope != "tenant":
            continue
        result = await tools.run_read_tool(tool.name, "{}", context=context, registry=registry)
        assert "no account is open" in result, tool.name
