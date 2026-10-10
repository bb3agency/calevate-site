"""Which ThinnestAI workspace a request acts in: the ONE place the header is derived (D-693).

Every Calevate client has its own ThinnestAI customer workspace. Our one API key reaches any
of them by adding `Thinnest-Workspace: org_…` to a request, which then "runs inside that
customer as if the customer had sent it"; without the header a request acts in our own
developer workspace (`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/
customers.md:68-91`). So the header decides whose agents, numbers, contacts and do-not-call
list a request touches, and a request that drops it lands in the developer workspace.

Every ThinnestAI client in `apps/api/engine/` builds its headers with `workspace_headers`.
Where the workspace comes from:

* an object we already hold — agent, call, webhook, number — carries it in its handle
  (`calevate_shared.engine_scope`, `<raw>@<org_…>`); an unscoped handle names an object in the
  developer workspace, every one of them issued before D-693;
* a NEW tenant object takes the tenant's own workspace from
  `tenancy/engine_workspace.workspace_for_tenant`, passed in explicitly;
* a call that names no object (a listing walked by a sweep) takes the workspace the caller
  opened with `in_workspace`.

Three classes of route, enforced here rather than at each call site:

* DEVELOPER-ONLY — our account itself: customers, the model catalogue and the workspace
  read. A header there is refused before the request is built (the vendor refuses
  `/customers/*` with one, `customers.md:102`).
* The BYOK routes are NOT developer-only (D-717). Our Cartesia key is installed and switched
  on in the customer workspace of each client that uses Studio, and the developer
  workspace's switch stays off so nothing inherits it; every BYOK request "also works for a
  customer, with the `Thinnest-Workspace` header" (`bring-your-own-keys.md:137`). They follow
  the ambient workspace like any handle-less call. Switching the developer workspace's BYOK
  ON is refused by the adapter (`refuse_developer_byok_on`), not here: the header cannot see
  the body.
* TENANT-ONLY — writes that must never land in the developer workspace, which holds every
  legacy client's data: creating an agent, renting a number, sending business details,
  adding to the do-not-call list, finding or erasing a contact. Without a customer workspace
  they are refused here, before anything is sent.
* everything else follows the object: a customer workspace's header, or none for an object
  that lives in the developer workspace.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

from calevate_shared.engine_scope import is_customer_workspace, scope_of

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

WORKSPACE_HEADER: Final = "Thinnest-Workspace"

#: Routes on OUR account. Never sent with a workspace header.
DEVELOPER_ONLY_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("GET", "/customers"),
        ("POST", "/customers"),
        ("GET", "/customers/{id}"),
        ("DELETE", "/customers/{id}"),
        ("POST", "/customers/{id}/restore"),
        ("GET", "/customers/usage"),
        ("GET", "/models"),
        ("GET", "/workspace"),
    }
)

#: The BYOK routes, which act in whichever workspace the caller opened (D-717).
WORKSPACE_BYOK_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("GET", "/byok"),
        ("PUT", "/byok/credentials"),
        ("PATCH", "/byok"),
        ("GET", "/byok/voices"),
        ("POST", "/byok/voices/preview"),
    }
)


def refuse_developer_byok_on(workspace: str | None) -> None:
    """Our developer workspace's BYOK switch stays OFF (D-717): a customer that brings no key
    of its own inherits the developer's keys and scope while it is on, and every Clear agent
    of every client would then follow it unless set `off` (`bring-your-own-keys.md:129-133`).
    Switching it on is a programming error, refused before anything is sent."""
    if workspace is None or is_developer_workspace(workspace):
        raise WorkspaceScopeError("the developer workspace's own-keys switch stays off")


#: Writes that act on a client's own name or a person's data. Refused without a customer
#: workspace: in the developer workspace they would act for every legacy client at once.
TENANT_ONLY_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("POST", "/agents"),
        ("POST", "/phone-numbers"),
        ("PUT", "/phone-numbers/business-details"),
        ("GET", "/phone-numbers/available"),
        ("GET", "/phone-numbers/available/cities"),
        ("POST", "/do-not-call"),
        ("GET", "/contacts"),
        ("DELETE", "/contacts/{id}"),
    }
)

#: The workspace a sweep or a handle-less call acts in, opened by `in_workspace`. None is
#: the developer workspace.
_CURRENT: ContextVar[str | None] = ContextVar("thinnest_workspace", default=None)

#: The one tenant-only write a FREE-TRIAL account may make in the developer workspace:
#: creating its agent (D-697). A trial account has no workspace of its own until it pays, and
#: its agents only place test calls from the shared trial number, which lives there too. Set
#: only by `agents.service.publish_agent` for a trial account, around the create.
_TRIAL_AGENT_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset({("POST", "/agents")})
_TRIAL_AGENT: ContextVar[bool] = ContextVar("thinnest_trial_agent", default=False)


@contextmanager
def trial_agent_in_developer_workspace() -> Iterator[None]:
    """Let the enclosed agent create land in the developer workspace (a trial account)."""
    token = _TRIAL_AGENT.set(True)
    try:
        yield
    finally:
        _TRIAL_AGENT.reset(token)


def trial_agent_allowed() -> bool:
    return _TRIAL_AGENT.get()


#: Our developer workspace's id as read from `GET /workspace` by this process
#: (`remember_developer_workspace`); `Settings.thinnest_developer_workspace_id` covers a
#: process that has not read it.
_DEVELOPER_WORKSPACE: str | None = None


def remember_developer_workspace(workspace: str | None) -> None:
    global _DEVELOPER_WORKSPACE
    _DEVELOPER_WORKSPACE = workspace


def is_developer_workspace(workspace: str | None) -> bool:
    """Is `workspace` OUR developer workspace? Its id is `org_…` like every customer's
    (`api-reference/workspace/get-workspace.md:347`), so the prefix alone cannot tell them
    apart; the id can."""
    if not workspace:
        return False
    known = {_DEVELOPER_WORKSPACE, get_settings().thinnest_developer_workspace_id}
    return workspace in known


class WorkspaceScopeError(RuntimeError):
    """A programming error: a request was about to cross from one workspace into another."""


def workspace_not_provisioned() -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code="engine_workspace_not_provisioned",
        title="This account is not ready for calls yet",
        detail=("Nothing was changed. This account is not set up for calls yet."),
        remediation=(
            "If you have just set it up, try again in a few minutes. Otherwise your Calevate "
            "contact can finish the setup."
        ),
        status=409,
    )


@contextmanager
def in_workspace(workspace: str | None) -> Iterator[None]:
    """Run the enclosed handle-less calls in `workspace` (None: the developer workspace)."""
    if workspace is not None and not is_customer_workspace(workspace):
        raise WorkspaceScopeError("in_workspace takes a customer workspace id or None")
    token = _CURRENT.set(workspace)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_workspace() -> str | None:
    """The workspace `in_workspace` opened, or None."""
    return _CURRENT.get()


def workspace_of(handle: str | None) -> str | None:
    """The workspace a request about `handle` acts in.

    The handle's own scope wins; with no handle, the ambient `in_workspace`. A handle scoped
    to one customer while the caller opened another is refused: one of the two is wrong, and
    sending either would act on the wrong client's data.
    """
    ambient = _CURRENT.get()
    if handle is None:
        return ambient
    scope = scope_of(handle)
    if ambient is not None and scope != ambient:
        raise WorkspaceScopeError("a handle of one workspace was used inside another")
    return scope


def workspace_headers(method: str, route: str, workspace: str | None) -> dict[str, str]:
    """The headers a request on `route` carries for `workspace`. The only builder of the
    workspace header; every ThinnestAI client in this package calls it."""
    key = (method.upper(), route)
    if key in DEVELOPER_ONLY_ROUTES:
        if workspace is not None:
            raise WorkspaceScopeError(f"{method} {route} acts on our own account only")
        return {}
    customer = is_customer_workspace(workspace) and not is_developer_workspace(workspace)
    trial_create = workspace is None and key in _TRIAL_AGENT_ROUTES and _TRIAL_AGENT.get()
    if key in TENANT_ONLY_ROUTES and not customer and not trial_create:
        raise workspace_not_provisioned()
    if workspace is None:
        return {}
    if not customer:
        raise WorkspaceScopeError("a workspace header must name a customer workspace")
    return {WORKSPACE_HEADER: workspace}


__all__ = [
    "DEVELOPER_ONLY_ROUTES",
    "TENANT_ONLY_ROUTES",
    "WORKSPACE_BYOK_ROUTES",
    "WORKSPACE_HEADER",
    "WorkspaceScopeError",
    "current_workspace",
    "in_workspace",
    "is_developer_workspace",
    "refuse_developer_byok_on",
    "remember_developer_workspace",
    "trial_agent_allowed",
    "trial_agent_in_developer_workspace",
    "workspace_headers",
    "workspace_not_provisioned",
    "workspace_of",
]
