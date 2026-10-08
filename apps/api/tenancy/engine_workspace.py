"""Which ThinnestAI workspace holds a client's data: the one resolver (D-691).

The founder has decided (8 Oct 2026) that every client gets its OWN ThinnestAI customer
workspace (`POST /customers`; every request about it carries `Thinnest-Workspace: <org_ id>`,
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/customers.md`). Two
writes that reach a person's data are allowed ONLY there: pushing a do-not-call addition and
erasing a contact. Sent without the header they would act on our DEVELOPER workspace, which
holds every client's calls today — one client's erasure would delete another's history.

So both ask this module first, and act only on `is_own_workspace(...)`. Until the
workspace lane provisions them, `workspace_for_tenant` answers "not provisioned" for every
tenant, and both writes are skipped: the do-not-call list stays ours alone and an erasure
records that the platform's copy expires with its plan retention. That lane replaces the
body of `workspace_for_tenant` and nothing else.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

#: The only shape a customer workspace id takes (`org_…`, customers.md). Anything else —
#: absent, empty, our own developer workspace — is refused by `is_own_workspace`.
WORKSPACE_PREFIX: Final = "org_"


async def workspace_for_tenant(tenant_id: UUID) -> str | None:
    """The tenant's own customer workspace id, or None while it is not provisioned."""
    return None


def is_own_workspace(workspace: str | None) -> bool:
    """True only for a customer workspace id. The developer workspace is never one."""
    return (
        isinstance(workspace, str)
        and workspace.startswith(WORKSPACE_PREFIX)
        and len(workspace) > len(WORKSPACE_PREFIX)
    )


async def own_workspace(tenant_id: UUID) -> str | None:
    """The tenant's own workspace when it is provisioned, else None — the question both
    person-level writes ask before anything leaves this system."""
    workspace = await workspace_for_tenant(tenant_id)
    return workspace if is_own_workspace(workspace) else None


__all__ = ["WORKSPACE_PREFIX", "is_own_workspace", "own_workspace", "workspace_for_tenant"]
