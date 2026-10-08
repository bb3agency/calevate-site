"""ThinnestAI custom actions and live calls over REST: the one place their shapes are read.

Every fact cites the hash-pinned snapshot `thinnest-findings/mirror/snapshots/2026-10-07/
pages/` (VERIFIED-VENDOR-DOCS), abbreviated `snap:` below:

* `POST /agents/{id}/actions` creates an action SWITCHED OFF; sending `enabled` is refused
  (snap:api-reference/actions/create-action.md:7). `name` matches `^[a-z][a-z0-9_]{2,39}$`
  (:412), `description` is at least 10 characters (:418), `headers` are up to 10, sealed on
  arrival and never returned — only `headerNames` (:457, :7).
* `PATCH /agents/{id}/actions/{actionId}` changes any field or `enabled`; leaving `headers`
  out keeps the saved ones and sending any replaces the whole set
  (snap:api-reference/actions/update-action.md:7).
* `GET /agents/{id}/actions` pages with `limit`/`cursor` and answers `{items, nextCursor}`
  (snap:api-reference/actions/list-actions.md:15-16, :133-147).
* `POST …/actions/{actionId}/test` makes the call once, for real, also while the action is
  off; a failed call is still `200` with `ok: false` (snap:api-reference/actions/
  test-action.md:7, :99-118).
* A 429 carries `Retry-After` (snap:api-reference/actions/create-action.md:614-616); the
  shared ladder in `vendor_http` honours it.
* `GET /calls?agent=&status=connected` lists the agent's live calls, each with `direction`
  and `phone`, "the customer's number" (snap:api-reference/calls/list-calls.md:262, :277,
  :494-504).

What crosses out of this module is OURS: `VendorAction` and `LiveCall` carry ids, our own
url and the customer's number for matching — never a vendor error sentence.

WHICH CALL. Placeholders with a dot are filled by the platform, never the model, so a caller
cannot talk the agent into a different value: `{{call.id}}` is the id `GET /calls` lists,
and every action call also carries an `X-Call-Id` header
(snapshots/2026-10-08/pages/agent/custom-api.md:84-119; api-reference/actions/
create-action.md:7). Every body of ours carries `{{call.id}}` as `call_id`, and the receiver
reads the call itself with `GET /calls/{id}` (`call`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

import httpx

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, vendor_request

ENGINE: Final = "thinnest"

#: The header our actions carry. The vendor's own guide names it (agent/custom-api.md:131,
#: guides/order-status.md:24); the value is ours and per agent.
SECRET_HEADER: Final = "X-Agent-Secret"

_PAGE_SIZE: Final = 100
_MAX_PAGES: Final = 5

#: The body field naming the call an action was made on, and the platform placeholder that
#: fills it (agent/custom-api.md:90-96). Not a declared parameter: the model never sees it.
CALL_ID_FIELD: Final = "call_id"
CALL_ID_PLACEHOLDER: Final = "{{call.id}}"
#: The header the platform sends with every action call naming the same call (:116-119).
CALL_ID_HEADER: Final = "X-Call-Id"


@dataclass(frozen=True, slots=True)
class ActionParam:
    name: str
    description: str
    required: bool


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """One action as we want it to exist at the vendor. Every string is platform-written."""

    name: str
    description: str
    url: str
    parameters: tuple[ActionParam, ...]

    def body_template(self) -> str:
        """A JSON object of every parameter, each placeholder QUOTED, as the vendor requires
        (snap:api-reference/actions/create-action.md:201-209), plus the call it was made on."""
        return json.dumps(
            {
                CALL_ID_FIELD: CALL_ID_PLACEHOLDER,
                **{p.name: "{{" + p.name + "}}" for p in self.parameters},
            }
        )

    def wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "method": "POST",
            "url": self.url,
            "parameters": [
                {"name": p.name, "description": p.description, "required": p.required}
                for p in self.parameters
            ],
            "bodyTemplate": self.body_template(),
        }


@dataclass(frozen=True, slots=True)
class VendorAction:
    action_id: str
    name: str
    description: str
    method: str
    url: str
    parameters: tuple[ActionParam, ...]
    body_template: str | None
    header_names: frozenset[str]
    enabled: bool

    def matches(self, wanted: ActionDefinition) -> bool:
        """Does the vendor hold exactly what we would send, our header included?"""
        return (
            self.description == wanted.description
            and self.method.upper() == "POST"
            and self.url == wanted.url
            and self.parameters == wanted.parameters
            and _same_json(self.body_template, wanted.body_template())
            and SECRET_HEADER.lower() in {h.lower() for h in self.header_names}
        )


@dataclass(frozen=True, slots=True)
class LiveCall:
    """One call as the vendor describes it (`GET /calls/{id}`)."""

    engine_call_id: str
    direction: str | None
    #: The customer's number as the vendor prints it (no `+`, list-calls.md:504-505).
    phone: str | None
    #: Our `reference` on a call we placed — our `calls.id` (`ThinnestEngine.start_outbound_call`).
    reference: str | None
    #: The vendor agent that is on the call.
    agent_ref: str | None = None
    #: The vendor's status word: `ringing` or `connected` while it is live.
    status: str | None = None

    @property
    def live(self) -> bool:
        return self.status in ("ringing", "connected")


@dataclass(frozen=True, slots=True)
class ActionTestResult:
    ok: bool
    status: int


def _same_json(held: str | None, wanted: str) -> bool:
    if held is None:
        return False
    try:
        return bool(json.loads(held) == json.loads(wanted))
    except ValueError:
        return False


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _bad(detail: str) -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_bad_response",
        title="Voice engine returned an unusable response",
        detail="The voice platform answered in a shape we could not read.",
        failure_stage="CORE_LOGIC",
        remediation=f"ThinnestAI {detail}.",
    )


def _param(row: Any) -> ActionParam | None:
    if not isinstance(row, dict) or _str(row.get("name")) is None:
        return None
    return ActionParam(
        name=str(row["name"]),
        description=_text(row.get("description")),
        required=row.get("required") is True,
    )


def _action(row: dict[str, Any]) -> VendorAction:
    action_id = _str(row.get("id"))
    name = _str(row.get("name"))
    if action_id is None or name is None:
        raise _bad("/actions returned an action without an id or name")
    params = tuple(p for p in (_param(r) for r in row.get("parameters") or ()) if p is not None)
    headers = row.get("headerNames")
    return VendorAction(
        action_id=action_id,
        name=name,
        description=_text(row.get("description")),
        method=_str(row.get("method")) or "GET",
        url=_str(row.get("url")) or "",
        parameters=params,
        body_template=row.get("bodyTemplate") if isinstance(row.get("bodyTemplate"), str) else None,
        header_names=frozenset(h for h in headers if isinstance(h, str))
        if isinstance(headers, list)
        else frozenset(),
        # Absent is read as off: the converge then switches it on, which is harmless.
        enabled=row.get("enabled") is True,
    )


class ThinnestActions:
    """`/agents/{id}/actions` CRUD plus the live-call list. Tests hand in a mock transport."""

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
        self, method: str, path: str, *, route: str, agent_ref: str, **kwargs: Any
    ) -> dict[str, Any]:
        """`path` names `{agent}` where the vendor agent id goes."""
        return await vendor_request(
            self._http(),
            method,
            path.replace("{agent}", agent_ref),
            engine=ENGINE,
            route=route,
            **kwargs,
        )

    async def list_actions(self, agent_ref: str) -> list[VendorAction]:
        """Every action on the agent. Refuses rather than answering a partial list: a
        converge over a partial list would create a second action under a name we hold."""
        actions: list[VendorAction] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            params: dict[str, Any] = {"limit": _PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            page = await self._request(
                "GET",
                "/agents/{agent}/actions",
                route="/agents/{id}/actions",
                agent_ref=agent_ref,
                params=params,
            )
            rows = page.get("items")
            if not isinstance(rows, list):
                raise _bad("/actions returned a list without `items`")
            actions.extend(_action(r) for r in rows if isinstance(r, dict))
            cursor = _str(page.get("nextCursor"))
            if cursor is None:
                return actions
        raise _bad(f"/actions listed more than {_MAX_PAGES} pages")

    async def create(
        self, agent_ref: str, definition: ActionDefinition, *, secret: str
    ) -> VendorAction:
        return _action(
            await self._request(
                "POST",
                "/agents/{agent}/actions",
                route="/agents/{id}/actions",
                agent_ref=agent_ref,
                json={**definition.wire(), "headers": {SECRET_HEADER: secret}},
            )
        )

    async def update(
        self,
        agent_ref: str,
        action_id: str,
        *,
        definition: ActionDefinition | None = None,
        secret: str | None = None,
        enabled: bool | None = None,
    ) -> VendorAction:
        body: dict[str, Any] = dict(definition.wire()) if definition is not None else {}
        if secret is not None:
            body["headers"] = {SECRET_HEADER: secret}
        if enabled is not None:
            body["enabled"] = enabled
        return _action(
            await self._request(
                "PATCH",
                f"/agents/{{agent}}/actions/{action_id}",
                route="/agents/{id}/actions/{actionId}",
                agent_ref=agent_ref,
                json=body,
            )
        )

    async def delete(self, agent_ref: str, action_id: str) -> None:
        await self._request(
            "DELETE",
            f"/agents/{{agent}}/actions/{action_id}",
            route="/agents/{id}/actions/{actionId}",
            agent_ref=agent_ref,
            absent_is_success=True,
        )

    async def test(
        self, agent_ref: str, action_id: str, arguments: dict[str, str]
    ) -> ActionTestResult:
        """One real call through the vendor to our endpoint. A failed call is `ok: false`."""
        data = await self._request(
            "POST",
            f"/agents/{{agent}}/actions/{action_id}/test",
            route="/agents/{id}/actions/{actionId}/test",
            agent_ref=agent_ref,
            json={"arguments": arguments},
        )
        status = data.get("status")
        return ActionTestResult(
            ok=data.get("ok") is True, status=status if isinstance(status, int) else 0
        )

    async def call(self, agent_ref: str, call_id: str) -> LiveCall | None:
        """`GET /calls/{id}`: the call an action names, or None when the vendor holds no
        such call. `agent` is `{id, name}` and `phone` the customer's number
        (snapshots/2026-10-08/pages/api-reference/calls/get-call.md:7)."""
        row = await self._request(
            "GET",
            f"/calls/{quote(call_id, safe='')}",
            route="/calls/{id}",
            agent_ref=agent_ref,
            absent_is_success=True,
        )
        if _str(row.get("id")) is None:
            return None
        agent = row.get("agent")
        return LiveCall(
            engine_call_id=str(row["id"]),
            direction=_str(row.get("direction")),
            phone=_str(row.get("phone")),
            reference=_str(row.get("reference")),
            agent_ref=_str(agent.get("id")) if isinstance(agent, dict) else _str(agent),
            status=_str(row.get("status")),
        )


_DEFAULT: ThinnestActions | None = None


def thinnest_actions() -> ThinnestActions:
    global _DEFAULT
    if _DEFAULT is None:
        cfg = get_settings()
        _DEFAULT = ThinnestActions(api_key=cfg.thinnest_api_key, base_url=cfg.thinnest_api_base_url)
    return _DEFAULT


def set_thinnest_actions(client: ThinnestActions | None) -> None:
    """Test seam: install a client built on a mock transport, or reset to settings."""
    global _DEFAULT
    _DEFAULT = client


__all__ = [
    "CALL_ID_FIELD",
    "CALL_ID_HEADER",
    "CALL_ID_PLACEHOLDER",
    "SECRET_HEADER",
    "ActionDefinition",
    "ActionParam",
    "ActionTestResult",
    "LiveCall",
    "ThinnestActions",
    "VendorAction",
    "set_thinnest_actions",
    "thinnest_actions",
]
