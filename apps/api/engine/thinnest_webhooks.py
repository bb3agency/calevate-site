"""ThinnestAI webhook endpoints over REST: the one place their `/webhooks` shape is read.

Every fact is `thinnest-findings/mirror/pages/api-reference/webhooks.md` (VERIFIED-VENDOR-
DOCS): `POST /webhooks` takes `{agent, url, events}` and returns the endpoint with
`signingSecret` "in the create response and nowhere else" (:9-40); `GET /webhooks?agent=`
lists newest first (:46); `GET /webhooks/{id}` carries `enabled` and `delivery` (:48);
`PATCH /webhooks/{id}` takes `enabled` and "switching an endpoint back on forgives its past
failures" (:49, :78-80); `DELETE /webhooks/{id}` removes it (:50). An endpoint failing five
deliveries in a row is switched off rather than retried (:84-88).

What crosses out of this module is OURS: `WebhookEndpoint` holds an id, the url we
registered, `enabled` and the failure count — never `delivery.lastError`, which is the
vendor's sentence about our endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, vendor_request

ENGINE: Final = "thinnest"

#: The two events the post-call path reads (THINNEST-INTEGRATION §3.1). `lead.captured`
#: and the conversation events are chat-channel concerns this product does not consume.
CALL_EVENTS: Final = ("call.completed", "call.analysed")

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


@dataclass(frozen=True, slots=True)
class CreatedEndpoint:
    endpoint: WebhookEndpoint
    #: Returned once (webhooks.md:36-40). Never logged; the caller seals it immediately.
    signing_secret: str


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _endpoint(row: dict[str, Any]) -> WebhookEndpoint:
    webhook_id = _str(row.get("id"))
    if webhook_id is None:
        raise _bad("a webhook endpoint without an id")
    delivery = row.get("delivery")
    failures = delivery.get("failuresInARow") if isinstance(delivery, dict) else None
    return WebhookEndpoint(
        webhook_id=webhook_id,
        url=_str(row.get("url")),
        # Absent is read as switched OFF: the sweep then re-enables it, which is harmless
        # on an endpoint that was on, while reading absent as on would leave a dead one.
        enabled=row.get("enabled") is True,
        failures_in_a_row=failures if isinstance(failures, int) else 0,
    )


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
                headers={
                    AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _request(
        self, method: str, path: str, *, route: str, **kwargs: Any
    ) -> dict[str, Any]:
        return await vendor_request(
            self._http(), method, path, engine=ENGINE, route=route, **kwargs
        )

    async def create(self, *, engine_agent_ref: str, url: str) -> CreatedEndpoint:
        row = await self._request(
            "POST",
            "/webhooks",
            route="/webhooks",
            json={"agent": engine_agent_ref, "url": url, "events": list(CALL_EVENTS)},
        )
        secret = _str(row.get("signingSecret"))
        if secret is None:
            raise _bad("a created endpoint without its signingSecret")
        return CreatedEndpoint(endpoint=_endpoint(row), signing_secret=secret)

    async def list_for_agent(self, engine_agent_ref: str) -> list[WebhookEndpoint]:
        """UNVERIFIED: the page documents no cursor for this list (webhooks.md:46), so it is
        read as a single response."""
        payload = await self._request(
            "GET", "/webhooks", route="/webhooks", params={"agent": engine_agent_ref}
        )
        rows = payload.get("items")
        if not isinstance(rows, list):
            raise _bad("a webhook list without `items`")
        return [_endpoint(row) for row in rows if isinstance(row, dict)]

    async def get(self, webhook_id: str) -> WebhookEndpoint:
        return _endpoint(
            await self._request("GET", f"/webhooks/{webhook_id}", route="/webhooks/{id}")
        )

    async def enable(self, webhook_id: str) -> WebhookEndpoint:
        return _endpoint(
            await self._request(
                "PATCH", f"/webhooks/{webhook_id}", route="/webhooks/{id}", json={"enabled": True}
            )
        )

    async def delete(self, webhook_id: str) -> None:
        await self._request(
            "DELETE", f"/webhooks/{webhook_id}", route="/webhooks/{id}", absent_is_success=True
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
    "CALL_EVENTS",
    "CreatedEndpoint",
    "ThinnestWebhooks",
    "WebhookEndpoint",
    "set_thinnest_webhooks",
    "thinnest_webhooks",
]
