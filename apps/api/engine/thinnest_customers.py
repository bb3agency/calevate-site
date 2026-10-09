"""ThinnestAI customer workspaces over REST: the one place their `/customers` shape is read.

One customer workspace per Calevate client (D-693). VERIFIED-VENDOR-DOCS,
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/`:

* `POST /customers {name, externalId, metadata, timezone}` → 201 with `id` (`org_…`); an
  `Idempotency-Key` makes a retry within 24 hours return the first answer; 402 when the
  plan's customer limit is reached, 409 when the `externalId` is taken; needs a full key
  (`customers.md:18-66`; `customers/create-customer.md:7, :327-418`).
* `GET /customers?externalId=` — exact match, live ones only unless `archived=true`
  (`customers/list-customers.md:7, :20-52`).
* `GET /customers/{id}`, `DELETE /customers/{id}` (refused with 409 while it holds a rented
  number or WhatsApp; requests into it answer 410 from then on; erased 30 days later),
  `POST /customers/{id}/restore` until then (`customers.md:104-161`).
* Plan caps: 3 customers on Free and pay-as-you-go, 100 on Pro, 1,000 on Scale, 10,000 on
  Enterprise; "a deleted customer counts until it is erased" (`customers.md:191-200`).

All of these act on OUR account and never carry the workspace header (the vendor refuses
`/customers/*` with one, `customers.md:102`); `engine/thinnest_workspace.py` enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import httpx

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL, IDEMPOTENCY_HEADER
from apps.api.engine.thinnest_workspace import remember_developer_workspace, workspace_headers
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, vendor_request

ENGINE: Final = "thinnest"

#: `name` is 1-120 characters; `externalId` 1-128 of letters, digits, `.` `_` `:` `-`
#: (customers.md:52-57).
NAME_MAX: Final = 120

#: How many customer workspaces each plan allows (customers.md:191-198). Vendor facts,
#: VERIFIED-VENDOR-DOCS 2026-10-08; which plan we are on is an operator setting.
PLAN_CUSTOMER_CAPS: Final[dict[str, int]] = {
    "payg": 3,
    "pro": 100,
    "scale": 1_000,
    "enterprise": 10_000,
}


@dataclass(frozen=True, slots=True)
class DeveloperWorkspace:
    workspace_id: str
    #: The workspace's display name in their console; None if the answer carried none.
    name: str | None


@dataclass(frozen=True, slots=True)
class Customer:
    workspace_id: str
    external_id: str | None
    archived_at: datetime | None
    erase_after: datetime | None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _dt(value: Any) -> datetime | None:
    raw = _str(value)
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _customer(row: dict[str, Any]) -> Customer:
    workspace = _str(row.get("id"))
    if workspace is None:
        raise ProblemError(
            kind="dependency",
            code="engine_bad_response",
            title="Voice engine returned an unusable response",
            detail="The voice platform answered in a shape we could not read.",
            failure_stage="CORE_LOGIC",
            remediation="ThinnestAI /customers returned a customer without an id.",
        )
    return Customer(
        workspace_id=workspace,
        external_id=_str(row.get("externalId")),
        archived_at=_dt(row.get("archivedAt")),
        erase_after=_dt(row.get("eraseAfter")),
    )


class ThinnestCustomers:
    """`/customers`, on our own account only. Tests hand in a mock transport."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._api_key:
                raise engine_not_configured(f"{NO_CREDENTIALS_REASON}:{ENGINE}")
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}"},
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        route: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await vendor_request(
            self._http(),
            method,
            path,
            engine=ENGINE,
            route=route,
            headers={**(headers or {}), **workspace_headers(method, route, None)},
            **kwargs,
        )

    async def find(self, external_id: str, *, archived: bool = False) -> Customer | None:
        """The customer carrying our reference, live or (with `archived`) deleted and not yet
        erased. Exact match, so at most one."""
        payload = await self._request(
            "GET",
            "/customers",
            route="/customers",
            params={"externalId": external_id, "archived": "true" if archived else "false"},
        )
        rows = payload.get("items")
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("externalId") == external_id:
                return _customer(row)
        return None

    async def create(self, *, name: str, external_id: str, timezone: str) -> Customer:
        """Raises `EngineRejectedError` with `vendor_status` 402 at the plan's cap and 409
        when the reference is taken; the idempotency key is our reference, so a retry of a
        create whose answer was lost returns the same workspace."""
        return _customer(
            await self._request(
                "POST",
                "/customers",
                route="/customers",
                headers={IDEMPOTENCY_HEADER: f"calevate-customer-{external_id}"},
                json={
                    "name": name.strip()[:NAME_MAX] or external_id,
                    "externalId": external_id,
                    "timezone": timezone,
                },
                extra_refused_statuses=frozenset({402, 409}),
            )
        )

    async def developer_workspace_id(self) -> str:
        """Our own workspace's id; see `developer_workspace`."""
        return (await self.developer_workspace()).workspace_id

    async def developer_workspace(self) -> DeveloperWorkspace:
        """Our own workspace, from `GET /workspace` without the header
        (`api-reference/workspace/get-workspace.md:327-351`, `id` and `name` required),
        remembered for this process so it is never taken for a client's
        (`thinnest_workspace.is_developer_workspace`)."""
        row = await self._request("GET", "/workspace", route="/workspace")
        workspace = _customer(row).workspace_id
        remember_developer_workspace(workspace)
        return DeveloperWorkspace(workspace_id=workspace, name=_str(row.get("name")))

    async def get(self, workspace_id: str) -> Customer:
        return _customer(
            await self._request("GET", f"/customers/{workspace_id}", route="/customers/{id}")
        )

    async def delete(self, workspace_id: str) -> None:
        """Delete the customer; erased by the vendor 30 days later unless restored. 409 while
        it holds a rented number. Absent is success."""
        await self._request(
            "DELETE",
            f"/customers/{workspace_id}",
            route="/customers/{id}",
            absent_is_success=True,
            extra_refused_statuses=frozenset({409}),
        )

    async def restore(self, workspace_id: str) -> Customer:
        return _customer(
            await self._request(
                "POST", f"/customers/{workspace_id}/restore", route="/customers/{id}/restore"
            )
        )


_DEFAULT: ThinnestCustomers | None = None


def thinnest_customers() -> ThinnestCustomers:
    global _DEFAULT
    if _DEFAULT is None:
        cfg = get_settings()
        _DEFAULT = ThinnestCustomers(
            api_key=cfg.thinnest_api_key, base_url=cfg.thinnest_api_base_url
        )
    return _DEFAULT


def set_thinnest_customers(client: ThinnestCustomers | None) -> None:
    """Test seam: install a client built on a mock transport, or reset to settings."""
    global _DEFAULT
    _DEFAULT = client


__all__ = [
    "PLAN_CUSTOMER_CAPS",
    "Customer",
    "DeveloperWorkspace",
    "ThinnestCustomers",
    "set_thinnest_customers",
    "thinnest_customers",
]
