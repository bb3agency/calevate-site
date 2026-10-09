"""Engine handles scoped to a client's own engine workspace (D-693).

ThinnestAI runs one customer workspace per client, all reached with our one API key and a
`Thinnest-Workspace: org_…` header (`thinnest-findings/mirror/snapshots/2026-10-08/pages/
api-reference/customers.md:68-91`). An agent, call, webhook or number issued inside a
customer workspace is only addressable inside it, so we keep the workspace WITH the handle,
as `<raw>@<org_…>`. Every caller that stores or passes a handle keeps working unchanged, and
the adapter addresses the right workspace from the handle alone. A handle with no scope
names an object in our own developer workspace: every handle issued before D-693.

Ours rather than a vendor shape: the `@` form is never sent to the vendor. It lives in
`calevate_shared` because voice-runtime matches a delivery against the handle its url
carries, and voice-runtime may not import the API's engine package (hard rule 3).
"""

from __future__ import annotations

from typing import Final

SCOPE_SEPARATOR: Final = "@"

#: The only shape a customer workspace id takes (`org_…`, customers.md:41). Our developer
#: workspace is never named by one of ours: it is the absence of a scope.
WORKSPACE_PREFIX: Final = "org_"


def is_customer_workspace(workspace: str | None) -> bool:
    """True only for a customer workspace id."""
    return (
        isinstance(workspace, str)
        and workspace.startswith(WORKSPACE_PREFIX)
        and len(workspace) > len(WORKSPACE_PREFIX)
        and SCOPE_SEPARATOR not in workspace
    )


def scoped_handle(raw: str, scope: str | None) -> str:
    """`raw` as held by us: unchanged in the developer workspace, `<raw>@<scope>` otherwise."""
    if SCOPE_SEPARATOR in raw:
        raise ValueError("an engine handle may not already carry a scope")
    return raw if not scope else f"{raw}{SCOPE_SEPARATOR}{scope}"


def split_handle(handle: str) -> tuple[str, str | None]:
    """`(raw vendor id, scope or None)`. Splits on the LAST separator: the scope is ours and
    never contains one."""
    raw, separator, scope = handle.rpartition(SCOPE_SEPARATOR)
    if not separator or not raw or not scope:
        return handle, None
    return raw, scope


def scope_of(handle: str | None) -> str | None:
    """The workspace a handle was issued in; None for the developer workspace."""
    return None if not handle else split_handle(handle)[1]


def raw_of(handle: str) -> str:
    """The vendor's own id, as the vendor spells it."""
    return split_handle(handle)[0]


__all__ = [
    "SCOPE_SEPARATOR",
    "WORKSPACE_PREFIX",
    "is_customer_workspace",
    "raw_of",
    "scope_of",
    "scoped_handle",
    "split_handle",
]
