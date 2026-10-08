"""Engine handles scoped to an engine sub-account (D-687).

An engine that hosts agents in more than one sub-account of one API key (ThinnestAI's
customer workspaces) issues agent, call and webhook ids that are only meaningful inside the
sub-account that made them. We keep the sub-account WITH the handle, as `<raw>@<scope>`, so
every caller that stores or passes a handle keeps working unchanged and the adapter can
address the right sub-account from the handle alone. A handle with no scope is the account
itself, which is every handle issued before D-687.

Ours rather than a vendor shape: the `@` form is never sent to the vendor. It lives in
`calevate_shared` because voice-runtime matches a delivery's agent against the handle its
url carries, and voice-runtime may not import the API's engine package (hard rule 3).
"""

from __future__ import annotations

from typing import Final

SCOPE_SEPARATOR: Final = "@"


def scoped_handle(raw: str, scope: str | None) -> str:
    """`raw` as held by us: unchanged for the account itself, `<raw>@<scope>` otherwise."""
    if SCOPE_SEPARATOR in raw:
        raise ValueError("an engine handle may not already carry a scope")
    return raw if not scope else f"{raw}{SCOPE_SEPARATOR}{scope}"


def split_handle(handle: str) -> tuple[str, str | None]:
    """`(raw vendor id, scope or None)`. Splits on the LAST separator, since the scope is
    ours and never contains one."""
    raw, separator, scope = handle.rpartition(SCOPE_SEPARATOR)
    if not separator or not raw or not scope:
        return handle, None
    return raw, scope


def scope_of(handle: str | None) -> str | None:
    return None if not handle else split_handle(handle)[1]


__all__ = ["SCOPE_SEPARATOR", "scope_of", "scoped_handle", "split_handle"]
