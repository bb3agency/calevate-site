"""ThinnestAI person-level writes in a CLIENT's own workspace: do-not-call and erasure.

VERIFIED-VENDOR-DOCS, `thinnest-findings/mirror/snapshots/2026-10-08/pages/`:

* `POST /do-not-call {phone, reason}` — 201 added, 200 already there and unchanged
  (`api-reference/do-not-call/add-do-not-call-number.md:7, :340-380`);
* `DELETE /do-not-call/{phone}` — 204 removed, 404 not on the list
  (`api-reference/do-not-call/remove-do-not-call-number.md:7, :327-367`);
* `GET /contacts?phone=` — the contact on that number, "in any format a person would type
  it" (`api-reference/contacts/list-contacts.md:7, :355-363`);
* `DELETE /contacts/{id}` — erases the contact, its conversations, calls and recordings;
  204 when every recording is gone, 200 `{recordingsPending}` when some are queued for the
  nightly retry (`api-reference/contacts/delete-contact.md:7, :365-390`;
  `workspace/data-and-erasure.md:14-56`).

EVERY REQUEST CARRIES `Thinnest-Workspace`, AND ONE WITHOUT A CUSTOMER WORKSPACE IS REFUSED
BEFORE IT IS BUILT: these are tenant-only routes in `engine/thinnest_workspace.py`, the one
builder of the header. Without it they would act on our developer workspace, which holds
every legacy client's data. The one exception is a tenant erasure (D-922), which passes None
inside `thinnest_workspace.tenant_erasure_in_developer_workspace` to erase the contacts that
account's own calls created there.

Two calls here may also act in the developer workspace, because each touches only what one
tenant owns there (VERIFIED-VENDOR-DOCS, `snapshots/2026-10-15/pages/api-reference/`):

* `DELETE /calls/{id}/content` — one call's recording, transcript, summary and collected
  fields; the billing record stays. Idempotent (a repeat answers 200 with the first time).
  Needs a full key (`post-call/delete-call-content.md:443-589`). A call row is one tenant's,
  so a call in the developer workspace (a trial's, or one made before D-693) is deleted there
  with no header.
* `GET`/`PATCH /workspace` `callRetentionDays` — the days a workspace keeps calls' recordings
  and transcripts, 1 to `planRetentionDays` (`workspace/update-workspace.md:528-599`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from urllib.parse import quote

import httpx

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL, KEY_SCOPE_CODES
from apps.api.engine.thinnest_workspace import WORKSPACE_HEADER, workspace_headers
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, EngineRejectedError, vendor_request

ENGINE: Final = "thinnest"

#: Why we added a number, in the vendor's 200-character `reason`.
DNC_REASON: Final = "Opted out with this business (Calevate do-not-call list)"

#: What a per-call content deletion came to:
#: `deleted` — the vendor deleted it, now or on an earlier request;
#: `absent` — 404, the workspace holds no such call, so nothing of it is left to delete;
#: `workspace_deleted` — 410, the whole customer workspace was deleted;
#: `busy` — 409, the call is still live or booked and has not rung; ask again later.
CallContentOutcome = Literal["deleted", "absent", "workspace_deleted", "busy"]


@dataclass(frozen=True, slots=True)
class CallContentDeletion:
    outcome: CallContentOutcome
    #: The vendor's `contentDeletedAt`, the same on every repeat; None unless `deleted`.
    deleted_at: datetime | None = None
    #: Recording files the vendor still retries nightly; 0 when every one is gone.
    recordings_pending: int = 0

    @property
    def settled(self) -> bool:
        """Nothing of the call's content is left at the vendor, nor queued to go."""
        return self.outcome != "busy" and self.recordings_pending == 0


@dataclass(frozen=True, slots=True)
class WorkspaceRetention:
    #: The days set on the workspace; None is the vendor default (recordings for the plan's
    #: window, transcripts with no end).
    call_retention_days: int | None
    #: The most the plan allows: 30 on pay-as-you-go, 49 Pro, 75 Scale, 365 Enterprise.
    plan_retention_days: int


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _bad(detail: str) -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_bad_response",
        title="Voice engine returned an unusable response",
        detail="The voice platform answered in a shape we could not read.",
        failure_stage="CORE_LOGIC",
        remediation=f"ThinnestAI {detail}.",
    )


def key_not_full() -> ProblemError:
    """A 403 on a write that needs a full key: our key is a build or read key. Permanent
    until an operator installs a full key, so it is not retried."""
    return ProblemError(
        kind="business_rule",
        code="engine_key_not_full",
        title="The voice platform key cannot delete call content",
        detail="The voice platform refused the deletion for this key.",
        remediation="Install a full ThinnestAI key (a build or read key cannot delete).",
    )


class ThinnestCustomerData:
    """Do-not-call and contact erasure inside one customer workspace; call content deletion
    and call retention in a customer workspace or (with None) our developer workspace."""

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
        self, workspace: str | None, method: str, path: str, *, route: str, **kwargs: Any
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

    async def remove_do_not_call(self, workspace: str, phone_e164: str) -> None:
        """Take a number off the workspace's list (`DELETE /do-not-call/{phone}`, full key;
        `api-reference/do-not-call/remove-do-not-call-number.md:7, :327-367`).

        Sent as digits only, which the path parameter accepts, so no `+` has to survive URL
        encoding. A 404 for the NUMBER means it is already off the list, which is what was
        asked; a 404 for the WORKSPACE removed nothing and must not read as removed.
        """
        digits = phone_e164.removeprefix("+")
        try:
            await self._request(
                workspace,
                "DELETE",
                f"/do-not-call/{digits}",
                route="/do-not-call/{phone}",
            )
        except EngineRejectedError as exc:
            if exc.vendor_status == 404 and exc.vendor_code != "workspace_not_found":
                return
            raise

    async def contact_ids(self, workspace: str | None, phone_e164: str) -> list[str]:
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

    async def delete_contact(self, workspace: str | None, contact_id: str) -> int:
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

    async def delete_call_content(
        self, workspace: str | None, raw_call_id: str
    ) -> CallContentDeletion:
        """Delete one call's content (`DELETE /calls/{id}/content`, delete-call-content.md:
        443-589). `raw_call_id` is the vendor's own id (`out_…`, `sch_…` or a call ref).

        A 404 naming the WORKSPACE (`workspace_not_found`) deleted nothing and is raised, as
        `delete_contact` does; 429 and 503 ("nothing is lost by trying again") are raised by
        the shared ladder for the caller's retry."""
        try:
            payload = await self._request(
                workspace,
                "DELETE",
                f"/calls/{quote(raw_call_id, safe='')}/content",
                route="/calls/{id}/content",
            )
        except EngineRejectedError as exc:
            if exc.object_absent:
                return CallContentDeletion(outcome="absent")
            if exc.vendor_status == 410:
                return CallContentDeletion(outcome="workspace_deleted")
            if exc.vendor_status == 409:
                return CallContentDeletion(outcome="busy")
            if exc.vendor_status == 403 and exc.vendor_code in KEY_SCOPE_CODES:
                raise key_not_full() from exc
            raise
        if payload.get("contentDeleted") is not True:
            raise _bad("Delete Call Content answered without contentDeleted: true")
        return CallContentDeletion(
            outcome="deleted",
            deleted_at=_instant(payload.get("contentDeletedAt")),
            recordings_pending=max(_int(payload.get("recordingsPending")) or 0, 0),
        )

    async def read_retention(self, workspace: str | None) -> WorkspaceRetention:
        """`GET /workspace` in `workspace` (get-workspace.md:451-452, :514-551)."""
        return _retention(await self._request(workspace, "GET", "/workspace", route="/workspace"))

    async def set_retention(self, workspace: str | None, days: int) -> WorkspaceRetention:
        """`PATCH /workspace {callRetentionDays}` and the workspace as it now is
        (update-workspace.md:528-599). `days` must already be within the plan's window: a
        longer one is refused with a 400."""
        if isinstance(days, bool) or days < 1:
            raise ValueError("callRetentionDays is a whole number of days from 1")
        return _retention(
            await self._request(
                workspace,
                "PATCH",
                "/workspace",
                route="/workspace",
                json={"callRetentionDays": days},
            )
        )


def _retention(row: dict[str, Any]) -> WorkspaceRetention:
    plan = _int(row.get("planRetentionDays"))
    if plan is None or plan < 1:
        raise _bad("/workspace answered without planRetentionDays")
    return WorkspaceRetention(
        call_retention_days=_int(row.get("callRetentionDays")), plan_retention_days=plan
    )


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
    "CallContentDeletion",
    "CallContentOutcome",
    "ThinnestCustomerData",
    "WorkspaceRetention",
    "key_not_full",
    "set_thinnest_customer_data",
    "thinnest_customer_data",
]
