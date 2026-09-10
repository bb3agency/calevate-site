"""The archived-agent guard reads under the CALLER'S tenant, never one the URL named.

THE DEFECT. `guard_agent_write` chose its RLS scope as `_as_uuid(path_tenant) or
tenant_id` — the `{tenant_id}` path parameter WON over the tenant the credential resolved
to, and the winner was not merely compared against anything: it was passed to
`tenant_session`, which SETS `app.tenant_id`. So on any mutating route carrying both
`{tenant_id}` and `{agent_id}`, the caller chose the RLS scope of a read whose two
outcomes are distinguishable (409 `agent_archived` for a deleted agent, silence for one
that does not exist) — a cross-tenant existence oracle over guessed agent ids.

WHY THESE TESTS ARE NOT ROUTE TESTS. Nothing is exploitable through the mounted app
today: every `{tenant_id}` path param is under `/v1/admin/`, and
`rbac.assert_policy_registry_complete` refuses to boot a process in which such a path is
not `realm="admin"`. That is the ROUTE INVENTORY protecting us — the very thing a new
client-realm route changes — so a test driven through the current inventory would pass
whether or not the guard is fixed. Both tests below call the guard directly and assert
the PROPERTY:

1. the scope handed to `tenant_session` is the principal's on a client-realm path, and
   the admin console's path value is still honoured on its own prefixes (it has to be:
   a plain operator's principal carries no tenant at all);
2. and the consequence, against a REAL database with RLS on: a caller in tenant A who
   names tenant B in the URL learns nothing about B's deleted agent.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import write_guard
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from fastapi import Request
from tests.agent_lifecycle_test import _tenant

pytestmark = [pytest.mark.rls]

#: A client-realm mutating route that carries BOTH ids. It deliberately does not exist in
#: the app: what is under test is what the guard does when one is added, since the guard —
#: not the route table — has to be the thing that holds.
CLIENT_PATH_WITH_BOTH = "/v1/agents/{agent_id}/transfer-to/{tenant_id}"
ADMIN_PATH_WITH_BOTH = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish"


def _request(*, route_path: str, path_params: dict[str, Any]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": route_path,
            "headers": [],
            "path_params": path_params,
            "route": SimpleNamespace(path=route_path),
        }
    )


class _ScopeRecorder:
    """Stands in for `tenant_session` and records the GUC it would have set."""

    def __init__(self) -> None:
        self.scopes: list[uuid.UUID] = []

    def __call__(self, scope: uuid.UUID) -> _ScopeRecorder:
        self.scopes.append(scope)
        return self

    async def __aenter__(self) -> Any:
        async def execute(*_args: object, **_kwargs: object) -> Any:
            return SimpleNamespace(scalar=lambda: None)

        return SimpleNamespace(execute=execute)

    async def __aexit__(self, *_exc: object) -> None:
        return None


async def test_the_scope_is_the_principals_on_a_client_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The URL may name any tenant it likes; the GUC is the credential's."""
    recorder = _ScopeRecorder()
    monkeypatch.setattr(write_guard, "tenant_session", recorder)

    mine, neighbour, agent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await write_guard.guard_agent_write(
        _request(
            route_path=CLIENT_PATH_WITH_BOTH,
            path_params={"agent_id": str(agent), "tenant_id": str(neighbour)},
        ),
        tenant_id=mine,
    )
    assert recorder.scopes == [mine], (
        "the path-supplied tenant reached the RLS GUC — the principal must win outside "
        "the admin console's own prefixes"
    )


async def test_the_admin_console_still_scopes_to_the_tenant_its_path_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a concession: `_load_admin_principal` gives a plain operator NO tenant, so
    dropping the path value here would leave every per-tenant console write unguarded."""
    recorder = _ScopeRecorder()
    monkeypatch.setattr(write_guard, "tenant_session", recorder)

    subject, agent = uuid.uuid4(), uuid.uuid4()
    await write_guard.guard_agent_write(
        _request(
            route_path=ADMIN_PATH_WITH_BOTH,
            path_params={"agent_id": str(agent), "tenant_id": str(subject)},
        ),
        tenant_id=None,
    )
    assert recorder.scopes == [subject]


async def test_a_client_cannot_probe_a_neighbours_deleted_agent() -> None:
    """The consequence, end to end against real RLS: no refusal leaks back."""
    from apps.api.agents import lifecycle

    mine, _mine_agent, _t = await _tenant()
    neighbour, neighbour_agent, _t2 = await _tenant()
    async with tenant_session(neighbour) as session:
        await lifecycle.archive_agent(session, tenant_id=neighbour, agent_id=neighbour_agent)

    request = _request(
        route_path=CLIENT_PATH_WITH_BOTH,
        path_params={"agent_id": str(neighbour_agent), "tenant_id": str(neighbour)},
    )
    # Silence is the whole assertion: scoped to `mine`, the neighbour's row is invisible,
    # so the guard has nothing to refuse and nothing to disclose.
    await write_guard.guard_agent_write(request, tenant_id=mine)

    # ...and the guard is not simply inert — the same call, made by the tenant that owns
    # the agent, still refuses. Without this the test above would pass on a guard that
    # had been deleted.
    with pytest.raises(ProblemError) as refused:
        await write_guard.guard_agent_write(request, tenant_id=neighbour)
    assert refused.value.code == "agent_archived"
