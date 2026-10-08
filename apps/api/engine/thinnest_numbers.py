"""ThinnestAI phone numbers over REST: the one place their `/phone-numbers` shape is read.

Renting a number stays a console step; what the API does is list the numbers a workspace
holds, say who answers and who calls out on each, move those two, and report the workspace's
business-details application. VERIFIED-VENDOR-DOCS, all under
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/phone-numbers/`:

* `GET /phone-numbers` (every number, not paged) is read by the adapter's
  `list_engine_numbers`, which the admin numbers screen already uses; this module does not
  read it a second way.
* `GET /phone-numbers/{number}` — one number, with `callingAgent`, the agent it is lent to for
  calling out (`get-phone-number.md:7, :405-418`). A number in another workspace is a 404.
* `PATCH /phone-numbers/{number}` `{label, agent, callingAgent}` — applied in that order, and
  "a refusal stops there with the earlier changes kept"; a 409 when the agent already answers
  it or it is already that agent's line; needs a full key (`update-phone-number.md:7,
  :344-469, :401-405`). The number is named "in any spelling — compared on its digits".
* `GET /phone-numbers/business-details` — the workspace's application for Indian numbers:
  `none`, `draft`, `submitted`, `accepted`, `rejected`, `suspended`, `expired`, with `canRent`
  (`get-business-details.md:7, :412-470`).

What crosses out of this module is OURS: `EngineNumber` and `BusinessDetails`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

import httpx

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, EngineRejectedError, vendor_request

ENGINE: Final = "thinnest"

BusinessStatus = Literal[
    "none", "draft", "submitted", "accepted", "rejected", "suspended", "expired", "unknown"
]
_STATUSES: Final = frozenset(
    {"none", "draft", "submitted", "accepted", "rejected", "suspended", "expired"}
)


@dataclass(frozen=True, slots=True)
class EngineNumber:
    #: The vendor's spelling, which is also what a call's `from` and the path take.
    number: str
    e164: str
    #: Rented here and charged monthly, or brought on a carrier account and never billed.
    rented: bool
    #: The agent whose line it is (`agent`), or None.
    answering_agent: str | None
    #: The agent lent it for calling out (`callingAgent`), which "may differ from `agent`".
    calling_agent: str | None


@dataclass(frozen=True, slots=True)
class BusinessDetails:
    status: BusinessStatus
    business_name: str | None
    can_rent: bool
    submitted_at: datetime | None
    #: Present on a `rejected` application: what to correct. The vendor's sentence about our
    #: own application, shown to an operator only.
    review_note: str | None


#: The outcome of telling the vendor who answers a number and who calls out on it.
AttachmentOutcome = Literal["unchanged", "applied", "partial", "refused"]


@dataclass(frozen=True, slots=True)
class Attachment:
    outcome: AttachmentOutcome
    #: The number as the vendor holds it AFTER the attempt, read back on a refusal.
    state: EngineNumber
    #: Our code for the refusal, when there was one.
    refusal: str | None = None


def digits(number: str) -> str:
    """The digits of a number: how the vendor compares them, and the path we send."""
    return "".join(ch for ch in number if ch.isdigit())


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _bad(detail: str) -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_bad_response",
        title="Voice engine returned an unusable response",
        detail="The voice platform answered in a shape we could not read.",
        failure_stage="CORE_LOGIC",
        remediation=f"ThinnestAI /phone-numbers returned {detail}.",
    )


def _number(row: dict[str, Any]) -> EngineNumber | None:
    raw = _str(row.get("number"))
    if raw is None or not digits(raw):
        return None
    return EngineNumber(
        number=raw,
        e164=f"+{digits(raw)}",
        rented=row.get("source") == "rented",
        answering_agent=_str(row.get("agent")),
        calling_agent=_str(row.get("callingAgent")),
    )


def _business(row: dict[str, Any]) -> BusinessDetails:
    raw = _str(row.get("status"))
    status: BusinessStatus = raw if raw in _STATUSES else "unknown"  # type: ignore[assignment]
    submitted = _str(row.get("submittedAt"))
    try:
        at = datetime.fromisoformat(submitted.replace("Z", "+00:00")) if submitted else None
    except ValueError:
        at = None
    return BusinessDetails(
        status=status,
        business_name=_str(row.get("businessName")),
        can_rent=row.get("canRent") is True,
        submitted_at=at,
        review_note=_str(row.get("reviewNote")),
    )


class ThinnestNumbers:
    """`/phone-numbers`. One client per instance; tests hand in a mock transport."""

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
        self, method: str, path: str, *, route: str, **kwargs: Any
    ) -> dict[str, Any]:
        return await vendor_request(
            self._http(), method, path, engine=ENGINE, route=route, **kwargs
        )

    async def get_number(self, number: str) -> EngineNumber:
        row = await self._request(
            "GET", f"/phone-numbers/{digits(number)}", route="/phone-numbers/{number}"
        )
        parsed = _number(row)
        if parsed is None:
            raise _bad("a number without its `number`")
        return parsed

    async def attach(
        self, number: str, *, agent: str | None, calling_agent: str | None
    ) -> Attachment:
        """Make `agent` answer the number and `calling_agent` call out on it, sending only
        what differs: re-sending a field already in place is a 409 (`update-phone-number.md:
        401-405`). On a refusal the number is read back, because the vendor keeps whatever
        it applied before the refusal — `agent` goes before `callingAgent`."""
        current = await self.get_number(number)
        body: dict[str, str | None] = {}
        if current.answering_agent != agent:
            body["agent"] = agent
        if current.calling_agent != calling_agent:
            body["callingAgent"] = calling_agent
        if not body:
            return Attachment(outcome="unchanged", state=current)
        try:
            row = await self._request(
                "PATCH",
                f"/phone-numbers/{digits(number)}",
                route="/phone-numbers/{number}",
                json=body,
            )
        except EngineRejectedError as exc:
            after = await self.get_number(number)
            moved = (after.answering_agent, after.calling_agent) != (
                current.answering_agent,
                current.calling_agent,
            )
            return Attachment(
                outcome="partial" if moved else "refused", state=after, refusal=exc.code
            )
        state = _number(row)
        if state is None:
            raise _bad("an updated number without its `number`")
        return Attachment(outcome="applied", state=state)

    async def business_details(self) -> BusinessDetails:
        return _business(
            await self._request(
                "GET",
                "/phone-numbers/business-details",
                route="/phone-numbers/business-details",
            )
        )


_DEFAULT: ThinnestNumbers | None = None


def thinnest_numbers() -> ThinnestNumbers:
    """The process's client, built from the same settings the adapter reads. An unset key
    means "not configured", which refuses by name."""
    global _DEFAULT
    if _DEFAULT is None:
        cfg = get_settings()
        _DEFAULT = ThinnestNumbers(api_key=cfg.thinnest_api_key, base_url=cfg.thinnest_api_base_url)
    return _DEFAULT


def set_thinnest_numbers(client: ThinnestNumbers | None) -> None:
    """Test seam: install a client built on a mock transport, or reset to settings."""
    global _DEFAULT
    _DEFAULT = client


__all__ = [
    "Attachment",
    "AttachmentOutcome",
    "BusinessDetails",
    "BusinessStatus",
    "EngineNumber",
    "ThinnestNumbers",
    "digits",
    "set_thinnest_numbers",
    "thinnest_numbers",
]
