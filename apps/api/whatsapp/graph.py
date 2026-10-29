"""Meta's Graph API calls for a client's WhatsApp Business Account (D-784).

Every call here is made with the CLIENT's business token (one per client, sealed as their
`integration_credentials` row), except the code exchange, which uses Calevate's app id and
app secret. Nothing here logs a token, a body or a number (hard rule 6): failures carry
Meta's numeric error code and the HTTP status, which is what an operator can act on.

Wire facts, each read on Meta's own pages on 15 Oct 2026 (VERIFIED-VENDOR-DOCS, base
`developers.facebook.com/documentation/business-messaging/whatsapp/`):

* Code exchange: `GET /oauth/access_token?client_id&client_secret&code`, server to server;
  "The exchangeable token code has a time-to-live of 30 seconds" (embedded-signup/
  implementation.md). The response is shown only as `<BUSINESS_TOKEN>` with no field names
  (embedded-signup/onboarding-customers-as-a-tech-provider.md), so both a JSON
  `access_token` and a bare token body are accepted.
* Subscribe: `POST /<WABA_ID>/subscribed_apps` with the business token, `{"success": true}`.
* Register: `POST /<PHONE_NUMBER_ID>/register {"messaging_product": "whatsapp", "pin"}`; the
  6-digit pin "will be the business phone number's two-step verification PIN" (same page).
  Coexistence numbers "skip the phone number registration step" (onboarding-business-app-
  users.md). "There is no endpoint to disable two-step verification"
  (business-phone-numbers/two-step-verification.md).
* Number fields: `display_phone_number`, `verified_name`, `quality_rating`, `name_status`
  (reference/whatsapp-business-phone-number/...); `messaging_limit_tier` "has been
  deprecated. Request the `whatsapp_business_manager_messaging_limit` field instead"
  (messaging-limits.md).
* Templates: `POST /<WABA_ID>/message_templates` with `name`, `language`, `category`,
  `components` (positional `{{1}}` blanks with `example.body_text`); names are "lowercase
  alphanumeric characters and underscores"; review "can take up to 24 hours"
  (templates/overview.md, templates/template-review.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlencode

import httpx

from apps.api.actions.whatsapp import META_GRAPH_VERSION
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.integrations.egress_guard import egress_client

log = get_logger(__name__)

GRAPH_BASE: Final = f"https://graph.facebook.com/{META_GRAPH_VERSION}"
#: One Graph request. The code exchange must finish inside Meta's 30 seconds, and every
#: other call runs on a person's connect click or in a worker.
GRAPH_TIMEOUT_S: Final = 8.0
#: The phone number fields read after connecting and on every account refresh.
PHONE_FIELDS: Final = (
    "display_phone_number,verified_name,quality_rating,name_status,"
    "whatsapp_business_manager_messaging_limit"
)


class GraphError(ProblemError):
    """Meta refused or could not be reached. `meta_code` is Meta's numeric error code."""

    def __init__(self, step: str, *, status: int, meta_code: int | None) -> None:
        super().__init__(
            kind="dependency",
            code=f"whatsapp_{step}_failed",
            title="Meta did not accept this step",
            detail="Meta refused a WhatsApp set-up step. Nothing was charged.",
            remediation="Try again in a minute. If it keeps failing, contact Calevate support.",
        )
        self.step = step
        self.status = status
        self.meta_code = meta_code


@dataclass(frozen=True, slots=True)
class PhoneInfo:
    display_phone_number: str | None
    verified_name: str | None
    quality_rating: str | None
    name_status: str | None
    messaging_limit: str | None


def _meta_code(body: Any) -> int | None:
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


async def _call(
    step: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    url = f"{GRAPH_BASE}{path}" + (f"?{urlencode(query)}" if query else "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with egress_client(timeout=GRAPH_TIMEOUT_S, follow_redirects=False) as http:
            response = await http.request(method, url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        log.warning("whatsapp_graph_unreachable", extra={"step": step, "error": type(exc).__name__})
        raise GraphError(step, status=0, meta_code=None) from exc
    parsed = _json(response)
    if not 200 <= response.status_code < 300:
        code = _meta_code(parsed)
        log.warning(
            "whatsapp_graph_refused",
            extra={"step": step, "status": response.status_code, "meta_code": code},
        )
        raise GraphError(step, status=response.status_code, meta_code=code)
    return parsed if parsed is not None else response.text


async def exchange_code(*, app_id: str, app_secret: str, code: str) -> str:
    """The client's business token for the signup code. Must run within 30 seconds."""
    answer = await _call(
        "code_exchange",
        "GET",
        "/oauth/access_token",
        query={"client_id": app_id, "client_secret": app_secret, "code": code},
    )
    token = answer.get("access_token") if isinstance(answer, dict) else answer
    if not isinstance(token, str) or not token.strip() or len(token) > 4096:
        raise GraphError("code_exchange", status=200, meta_code=None)
    return token.strip()


async def subscribe_app(*, waba_id: str, token: str) -> None:
    await _call("subscribe", "POST", f"/{waba_id}/subscribed_apps", token=token)


async def register_number(*, phone_number_id: str, token: str, pin: str) -> None:
    await _call(
        "register",
        "POST",
        f"/{phone_number_id}/register",
        token=token,
        body={"messaging_product": "whatsapp", "pin": pin},
    )


def _text(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()[:200]
    if isinstance(value, dict):
        # The messaging limit may arrive as an object; keep its tier word only.
        inner = value.get("current_limit") or value.get("tier")
        return str(inner)[:32] if isinstance(inner, str) else None
    return None


async def phone_info(*, phone_number_id: str, token: str) -> PhoneInfo:
    body = await _call(
        "phone_info", "GET", f"/{phone_number_id}", token=token, query={"fields": PHONE_FIELDS}
    )
    data = body if isinstance(body, dict) else {}
    return PhoneInfo(
        display_phone_number=_text(data, "display_phone_number"),
        verified_name=_text(data, "verified_name"),
        quality_rating=_text(data, "quality_rating"),
        name_status=_text(data, "name_status"),
        messaging_limit=_text(data, "whatsapp_business_manager_messaging_limit"),
    )


async def first_phone_number_id(*, waba_id: str, token: str) -> str | None:
    """The WABA's first number, for a coexistence signup whose event names only the WABA."""
    body = await _call(
        "phone_list", "GET", f"/{waba_id}/phone_numbers", token=token, query={"fields": "id"}
    )
    rows = body.get("data") if isinstance(body, dict) else None
    for row in rows if isinstance(rows, list) else []:
        number_id = row.get("id") if isinstance(row, dict) else None
        if isinstance(number_id, str) and number_id.isdigit():
            return number_id
    return None


async def create_template(
    *,
    waba_id: str,
    token: str,
    name: str,
    language: str,
    category: str,
    body: str,
    examples: list[str],
) -> tuple[str | None, str | None]:
    """Submit one template. Returns (Meta's template id, Meta's status word)."""
    component: dict[str, Any] = {"type": "BODY", "text": body}
    if examples:
        component["example"] = {"body_text": [examples]}
    answer = await _call(
        "template_create",
        "POST",
        f"/{waba_id}/message_templates",
        token=token,
        body={"name": name, "language": language, "category": category, "components": [component]},
    )
    data = answer if isinstance(answer, dict) else {}
    template_id = data.get("id")
    status = data.get("status")
    return (
        template_id if isinstance(template_id, str) and template_id.isdigit() else None,
        status if isinstance(status, str) else None,
    )


async def template_status(*, template_id: str, token: str) -> tuple[str | None, str | None]:
    """Read one template's review state: (Meta's status word, its rejected reason).

    `GET /<TEMPLATE_ID>` returns `status` by default and lists `rejected_reason` as a field
    (developers.facebook.com/docs/graph-api/reference/whatsapp-business-hsm/, read 29 Oct
    2026, VERIFIED-VENDOR-DOCS); both are asked for by name.
    """
    answer = await _call(
        "template_read",
        "GET",
        f"/{template_id}",
        token=token,
        query={"fields": "status,rejected_reason"},
    )
    data = answer if isinstance(answer, dict) else {}
    status, reason = data.get("status"), data.get("rejected_reason")
    return (
        status if isinstance(status, str) else None,
        reason if isinstance(reason, str) else None,
    )


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = [
    "GRAPH_BASE",
    "GraphError",
    "PhoneInfo",
    "create_template",
    "dumps",
    "exchange_code",
    "first_phone_number_id",
    "phone_info",
    "register_number",
    "subscribe_app",
    "template_status",
]
