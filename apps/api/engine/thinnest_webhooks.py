"""ThinnestAI webhook endpoints over REST: the one place their `/webhooks` shape is read.

Every fact is `thinnest-findings/mirror/pages/api-reference/webhooks.md` (VERIFIED-VENDOR-
DOCS): `POST /webhooks` takes `{agent, url, events}` and returns the endpoint with
`signingSecret` "in the create response and nowhere else" (:9-40); `GET /webhooks?agent=`
lists newest first (:46); `GET /webhooks/{id}` carries `enabled` and `delivery` (:48);
`PATCH /webhooks/{id}` takes `enabled` and "switching an endpoint back on forgives its past
failures" (:49, :78-80); `DELETE /webhooks/{id}` removes it (:50). The current page
(`snapshots/2026-10-08/pages/api-reference/webhooks.md`) adds what the sweep relies on: a
failed attempt is retried after 1m, 5m, 30m, 2h and 6h (:110-117), an endpoint is switched
off after five events in a row that failed every attempt (:149-155), and
`POST /webhooks/{id}/redeliver` re-sends what failed in the last 7 days (:157-187).

An endpoint lives in its agent's workspace (D-693): every request takes the workspace from
the agent's or the endpoint's handle (`calevate_shared.engine_scope`), and the endpoint ids
returned are scoped to it.

What crosses out of this module is OURS: `WebhookEndpoint` holds an id, the url we
registered, `enabled` and the failure count — never `delivery.lastError`, which is the
vendor's sentence about our endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx
from calevate_shared.engine_scope import raw_of, scope_of, scoped_handle

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL, NOTICE_EVENTS
from apps.api.engine.thinnest_workspace import workspace_headers
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, vendor_request

ENGINE: Final = "thinnest"

#: What each agent's endpoint subscribes to (`snapshots/2026-10-08/pages/api-reference/
#: webhooks.md:77-85`): the two the post-call path reads (THINNEST-INTEGRATION §3.1), and
#: `contact.opted_out`, which files the person on the do-not-call list of the client whose
#: agent heard them (D-691), and the engine's notices (`NOTICE_EVENTS`: `lead.captured`,
#: `conversation.escalated`, read by `ThinnestEngine.parse_notice`). Sorted, so the order sent
#: and the order compared are one order.
SUBSCRIBED_EVENTS: Final = tuple(
    sorted({"call.analysed", "call.completed", "contact.opted_out", *NOTICE_EVENTS})
)

#: The query parameter our registered url carries, naming the vendor agent the endpoint
#: belongs to. The receiver selects the signing secret by it rather than by a body field,
#: because the `call.completed` body is undocumented beyond "outcome and duration"
#: (webhooks.md:74), and a signature from that agent's secret is still required.
AGENT_QUERY_PARAM: Final = "agent"


@dataclass(frozen=True, slots=True)
class WebhookEndpoint:
    webhook_id: str
    url: str | None
    enabled: bool
    failures_in_a_row: int
    #: What the endpoint is subscribed to, sorted; `("*",)` for every event.
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreatedEndpoint:
    endpoint: WebhookEndpoint
    #: Returned once (webhooks.md:36-40). Never logged; the caller seals it immediately.
    signing_secret: str


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _endpoint(row: dict[str, Any], workspace: str | None) -> WebhookEndpoint:
    raw = _str(row.get("id"))
    if raw is None:
        raise _bad("a webhook endpoint without an id")
    webhook_id = scoped_handle(raw, workspace)
    delivery = row.get("delivery")
    failures = delivery.get("failuresInARow") if isinstance(delivery, dict) else None
    return WebhookEndpoint(
        webhook_id=webhook_id,
        url=_str(row.get("url")),
        # Absent is read as switched OFF: the sweep then re-enables it, which is harmless
        # on an endpoint that was on, while reading absent as on would leave a dead one.
        enabled=row.get("enabled") is True,
        failures_in_a_row=failures if isinstance(failures, int) else 0,
        events=_events(row.get("events")),
    )


def _events(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted({item for item in value if isinstance(item, str) and item}))


def _bad(detail: str) -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_bad_response",
        title="Voice engine returned an unusable response",
        detail="The voice platform answered in a shape we could not read.",
        failure_stage="CORE_LOGIC",
        remediation=f"ThinnestAI /webhooks returned {detail}.",
    )


class ThinnestWebhooks:
    """`/webhooks` CRUD. One client per instance; tests hand in a mock transport."""

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
        self, method: str, path: str, *, route: str, workspace: str | None, **kwargs: Any
    ) -> dict[str, Any]:
        return await vendor_request(
            self._http(),
            method,
            path,
            engine=ENGINE,
            route=route,
            headers=workspace_headers(method, route, workspace),
            **kwargs,
        )

    async def create(self, *, engine_agent_ref: str, url: str) -> CreatedEndpoint:
        """In the agent's own workspace (its handle's scope); the endpoint id comes back
        scoped to the same workspace."""
        workspace = scope_of(engine_agent_ref)
        row = await self._request(
            "POST",
            "/webhooks",
            route="/webhooks",
            workspace=workspace,
            json={
                "agent": raw_of(engine_agent_ref),
                "url": url,
                "events": list(SUBSCRIBED_EVENTS),
            },
        )
        secret = _str(row.get("signingSecret"))
        if secret is None:
            raise _bad("a created endpoint without its signingSecret")
        return CreatedEndpoint(endpoint=_endpoint(row, workspace), signing_secret=secret)

    async def list_for_agent(self, engine_agent_ref: str) -> list[WebhookEndpoint]:
        """UNVERIFIED: the page documents no cursor for this list (webhooks.md:46), so it is
        read as a single response."""
        workspace = scope_of(engine_agent_ref)
        payload = await self._request(
            "GET",
            "/webhooks",
            route="/webhooks",
            workspace=workspace,
            params={"agent": raw_of(engine_agent_ref)},
        )
        rows = payload.get("items")
        if not isinstance(rows, list):
            raise _bad("a webhook list without `items`")
        return [_endpoint(row, workspace) for row in rows if isinstance(row, dict)]

    async def get(self, webhook_id: str) -> WebhookEndpoint:
        workspace = scope_of(webhook_id)
        return _endpoint(
            await self._request(
                "GET",
                f"/webhooks/{raw_of(webhook_id)}",
                route="/webhooks/{id}",
                workspace=workspace,
            ),
            workspace,
        )

    async def enable(self, webhook_id: str) -> WebhookEndpoint:
        workspace = scope_of(webhook_id)
        return _endpoint(
            await self._request(
                "PATCH",
                f"/webhooks/{raw_of(webhook_id)}",
                route="/webhooks/{id}",
                workspace=workspace,
                json={"enabled": True},
            ),
            workspace,
        )

    async def subscribe(self, webhook_id: str, events: tuple[str, ...]) -> WebhookEndpoint:
        """`PATCH /webhooks/{id}` with `events` (webhooks.md:50): an endpoint registered before
        a subscription was added is brought up to date in place, keeping its secret."""
        workspace = scope_of(webhook_id)
        return _endpoint(
            await self._request(
                "PATCH",
                f"/webhooks/{raw_of(webhook_id)}",
                route="/webhooks/{id}",
                workspace=workspace,
                json={"events": list(events)},
            ),
            workspace,
        )

    async def redeliver_since(self, webhook_id: str, since: datetime) -> int:
        """`POST /webhooks/{id}/redeliver {since}`: every delivery that has not succeeded since
        `since`, at most 7 days back, queued and sent within a minute with the same event id
        (`snapshots/2026-10-08/pages/api-reference/webhooks/redeliver-webhook-events.md:7`).
        Returns the vendor's `queued` count. The endpoint must already be switched on."""
        payload = await self._request(
            "POST",
            f"/webhooks/{raw_of(webhook_id)}/redeliver",
            route="/webhooks/{id}/redeliver",
            workspace=scope_of(webhook_id),
            json={"since": since.astimezone(UTC).isoformat().replace("+00:00", "Z")},
        )
        queued = payload.get("queued")
        return queued if isinstance(queued, int) and not isinstance(queued, bool) else 0

    async def delete(self, webhook_id: str) -> None:
        await self._request(
            "DELETE",
            f"/webhooks/{raw_of(webhook_id)}",
            route="/webhooks/{id}",
            workspace=scope_of(webhook_id),
            absent_is_success=True,
        )


_DEFAULT: ThinnestWebhooks | None = None


def thinnest_webhooks() -> ThinnestWebhooks:
    """The process's client, built from the same settings the adapter reads. An unset key
    means "not configured", which refuses by name."""
    global _DEFAULT
    if _DEFAULT is None:
        cfg = get_settings()
        _DEFAULT = ThinnestWebhooks(
            api_key=cfg.thinnest_api_key, base_url=cfg.thinnest_api_base_url
        )
    return _DEFAULT


def set_thinnest_webhooks(client: ThinnestWebhooks | None) -> None:
    """Test seam: install a client built on a mock transport, or reset to settings."""
    global _DEFAULT
    _DEFAULT = client


__all__ = [
    "AGENT_QUERY_PARAM",
    "SUBSCRIBED_EVENTS",
    "CreatedEndpoint",
    "ThinnestWebhooks",
    "WebhookEndpoint",
    "set_thinnest_webhooks",
    "thinnest_webhooks",
]
