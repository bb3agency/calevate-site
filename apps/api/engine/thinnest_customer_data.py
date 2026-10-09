"""ThinnestAI person-level writes in a CLIENT's own workspace: do-not-call and erasure.

VERIFIED-VENDOR-DOCS, `thinnest-findings/mirror/snapshots/2026-10-08/pages/`:

* `POST /do-not-call {phone, reason}` — 201 added, 200 already there and unchanged
  (`api-reference/do-not-call/add-do-not-call-number.md:7, :340-380`);
* `GET /contacts?phone=` — the contact on that number, "in any format a person would type
  it" (`api-reference/contacts/list-contacts.md:7, :355-363`);
* `DELETE /contacts/{id}` — erases the contact, its conversations, calls and recordings;
  204 when every recording is gone, 200 `{recordingsPending}` when some are queued for the
  nightly retry (`api-reference/contacts/delete-contact.md:7, :365-390`;
  `workspace/data-and-erasure.md:14-56`).

EVERY REQUEST CARRIES `Thinnest-Workspace`, AND ONE WITHOUT A CUSTOMER WORKSPACE IS REFUSED
BEFORE IT IS BUILT: these are tenant-only routes in `engine/thinnest_workspace.py`, the one
builder of the header. Without it they would act on our developer workspace, which holds
every legacy client's data.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL
from apps.api.engine.thinnest_workspace import WORKSPACE_HEADER, workspace_headers
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, EngineRejectedError, vendor_request

ENGINE: Final = "thinnest"

#: Why we added a number, in the vendor's 200-character `reason`.
DNC_REASON: Final = "Opted out with this business (Calevate do-not-call list)"


class ThinnestCustomerData:
    """Do-not-call and contact erasure, always inside one customer workspace."""

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
        self, workspace: str, method: str, path: str, *, route: str, **kwargs: Any
    ) -> dict[str, Any]:
        headers = workspace_headers(method, route, workspace)
        response = await vendor_request(
            self._http(),
            method,
            path,
            engine=ENGINE,
            route=route,
            headers=headers,
            **kwargs,
        )
        return response or {}

    async def add_do_not_call(self, workspace: str, phone_e164: str) -> None:
        await self._request(
            workspace,
            "POST",
            "/do-not-call",
            route="/do-not-call",
            json={"phone": phone_e164, "reason": DNC_REASON},
        )

    async def contact_ids(self, workspace: str, phone_e164: str) -> list[str]:
        payload = await self._request(
            workspace, "GET", "/contacts", route="/contacts", params={"phone": phone_e164}
        )
        rows = payload.get("items")
        if not isinstance(rows, list):
            return []
        return [
            str(row["id"])
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"]
        ]

    async def delete_contact(self, workspace: str, contact_id: str) -> int:
        """Erase one contact. Returns the recordings still queued (0 when all are gone)."""
        try:
            payload = await self._request(
                workspace, "DELETE", f"/contacts/{contact_id}", route="/contacts/{id}"
            )
        except EngineRejectedError as exc:
            # A 404 for the CONTACT (`not_found`) is the erasure's postcondition: it is
            # gone. A 404 for the WORKSPACE (`workspace_not_found`, errors.md:90) erased
            # nothing and must not read as erased.
            if exc.vendor_status == 404 and exc.vendor_code != "workspace_not_found":
                return 0
            raise
        pending = payload.get("recordingsPending")
        return pending if isinstance(pending, int) and not isinstance(pending, bool) else 0


_DEFAULT: ThinnestCustomerData | None = None


def thinnest_customer_data() -> ThinnestCustomerData:
    global _DEFAULT
    if _DEFAULT is None:
        cfg = get_settings()
        _DEFAULT = ThinnestCustomerData(
            api_key=cfg.thinnest_api_key, base_url=cfg.thinnest_api_base_url
        )
    return _DEFAULT


def set_thinnest_customer_data(client: ThinnestCustomerData | None) -> None:
    """Test seam: install a client built on a mock transport, or reset to settings."""
    global _DEFAULT
    _DEFAULT = client


__all__ = [
    "WORKSPACE_HEADER",
    "ThinnestCustomerData",
    "set_thinnest_customer_data",
    "thinnest_customer_data",
]
