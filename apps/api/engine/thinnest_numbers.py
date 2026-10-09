"""ThinnestAI phone numbers over REST: the one place their `/phone-numbers` shape is read.

Every request names the workspace the number lives in (D-693): a client's numbers are rented
in its own customer workspace, in its own business name, and a number rented in our developer
workspace before D-693 stays there ("held in the platform account"). The workspace travels in
the number's handle (`<digits>@<org_…>`, `calevate_shared.engine_scope`) or, for a search or a
rent, is passed explicitly. VERIFIED-VENDOR-DOCS, all under
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/phone-numbers/`:

* `GET /phone-numbers` (every number, not paged) is read by the adapter's
  `list_engine_numbers`; this module does not read it a second way.
* `GET /phone-numbers/{number}` — one number, with `callingAgent`, the agent it is lent to for
  calling out (`get-phone-number.md:7, :405-418`). A number in another workspace is a 404.
* `PATCH /phone-numbers/{number}` `{label, agent, callingAgent}` — applied in that order, and
  "a refusal stops there with the earlier changes kept"; a 409 when the agent already answers
  it or it is already that agent's line (`update-phone-number.md:7, :344-469, :401-405`).
* `GET /phone-numbers/available/cities` — the cities search accepts, spelled exactly; empty
  on the Free plan; not paged (`list-available-cities.md:7`).
* `GET /phone-numbers/available?city=&pattern=&cursor=` — up to twenty numbers a page, each
  with the vendor's `monthlyPrice {amountMinor, currency}`; `nextCursor` until there are no
  more; 403 on the Free plan, 503 when the stock cannot be reached
  (`search-available-phone-numbers.md:7`). The vendor's price is OUR cost: it is returned
  here for the operator view and never becomes a client price (hard rule 7).
* `POST /phone-numbers {number}` — rents it and charges the first month at once; "every
  refusal happens before anything is bought or charged"; 409 when somebody holds it or the
  business details are not approved; 402 when our balance cannot pay; 503 "if it was bought,
  it has been handed back and nothing was charged" (`rent-phone-number.md:7`). No
  idempotency key is documented for this route, so none is sent; a lost response is
  resolved by reading the number back.
* `DELETE /phone-numbers/{number}?confirm=release` — a rented number is released for good,
  "this month's rent is not refunded"; without `confirm=release` it is a 409
  (`release-phone-number.md:7`).
* `GET /phone-numbers/business-details` — the workspace's application for Indian numbers:
  `none`, `draft`, `submitted`, `accepted`, `rejected`, `suspended`, `expired`, with `canRent`
  (`get-business-details.md:7, :412-470`).
* `PUT /phone-numbers/business-details` — multipart `businessName`, `gstRegistered`
  (`"true"`/`"false"`), `documentKind` (`gst`, `incorporation`, `udyam`) and ONE `document`
  (PDF, JPG or PNG, at most 5 MB, filename at most 99 characters); 201 a new application,
  200 a rejected one corrected in place, 409 while one is being checked or after approval
  (`send-business-details.md:7, :336-395`).

What crosses out of this module is OURS: `EngineNumber`, `AvailableEngineNumber`,
`BusinessDetails`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

import httpx
from calevate_shared.engine_scope import raw_of, scope_of, scoped_handle

from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL
from apps.api.engine.thinnest_workspace import workspace_headers
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, EngineRejectedError, vendor_request

ENGINE: Final = "thinnest"

BusinessStatus = Literal[
    "none", "draft", "submitted", "accepted", "rejected", "suspended", "expired", "unknown"
]
_STATUSES: Final = frozenset(
    {"none", "draft", "submitted", "accepted", "rejected", "suspended", "expired"}
)

#: `documentKind` values the vendor takes (send-business-details.md:350-360).
DOCUMENT_KINDS: Final = frozenset({"gst", "incorporation", "udyam"})

#: `pattern` is up to ten digits; `city` at most 60 characters (search-available-phone-
#: numbers.md:24-40).
SEARCH_PATTERN_MAX: Final = 10
SEARCH_CITY_MAX: Final = 60


@dataclass(frozen=True, slots=True)
class EngineNumber:
    #: Our handle: the vendor's spelling, scoped to the workspace it lives in.
    number: str
    e164: str
    #: Rented here and charged monthly, or brought on a carrier account and never billed.
    rented: bool
    #: The agent whose line it is (`agent`), as our handle in the same workspace, or None.
    answering_agent: str | None
    #: The agent lent it for calling out (`callingAgent`), which "may differ from `agent`".
    calling_agent: str | None


@dataclass(frozen=True, slots=True)
class AvailableEngineNumber:
    """One number a workspace could rent. `vendor_monthly_inr` is OUR cost, never shown to
    a client as their price."""

    number: str
    e164: str
    city: str | None
    vendor_monthly_inr: Decimal | None


@dataclass(frozen=True, slots=True)
class AvailablePage:
    numbers: list[AvailableEngineNumber]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AvailableCity:
    name: str
    available: int


@dataclass(frozen=True, slots=True)
class BusinessDetails:
    status: BusinessStatus
    business_name: str | None
    can_rent: bool
    submitted_at: datetime | None
    #: Present on a `rejected` application: what to correct.
    review_note: str | None
    document_kind: str | None = None


@dataclass(frozen=True, slots=True)
class BusinessDocument:
    """The one certificate sent with the application, as the KYC lane holds it."""

    filename: str
    content_type: str
    data: bytes


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
    return "".join(ch for ch in raw_of(number) if ch.isdigit())


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


def _scoped(raw: str | None, workspace: str | None) -> str | None:
    return scoped_handle(raw, workspace) if raw else None


def _number(row: dict[str, Any], workspace: str | None) -> EngineNumber | None:
    raw = _str(row.get("number"))
    if raw is None or not digits(raw):
        return None
    return EngineNumber(
        number=scoped_handle(raw, workspace),
        e164=f"+{digits(raw)}",
        rented=row.get("source") == "rented",
        answering_agent=_scoped(_str(row.get("agent")), workspace),
        calling_agent=_scoped(_str(row.get("callingAgent")), workspace),
    )


def _inr(price: Any) -> Decimal | None:
    """`monthlyPrice {amountMinor, currency}` in rupees, or None when it is not rupees."""
    if not isinstance(price, dict) or price.get("currency") != "INR":
        return None
    minor = price.get("amountMinor")
    if isinstance(minor, bool) or not isinstance(minor, int):
        return None
    return Decimal(minor) / Decimal(100)


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
        document_kind=_str(row.get("documentKind")),
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

    async def get_number(self, number: str) -> EngineNumber:
        """One number, by our handle; the workspace is the handle's."""
        workspace = scope_of(number)
        row = await self._request(
            "GET",
            f"/phone-numbers/{digits(number)}",
            route="/phone-numbers/{number}",
            workspace=workspace,
        )
        parsed = _number(row, workspace)
        if parsed is None:
            raise _bad("a number without its `number`")
        return parsed

    async def attach(
        self, number: str, *, agent: str | None, calling_agent: str | None
    ) -> Attachment:
        """Make `agent` answer the number and `calling_agent` call out on it, sending only
        what differs: re-sending a field already in place is a 409 (`update-phone-number.md:
        401-405`). On a refusal the number is read back, because the vendor keeps whatever
        it applied before the refusal — `agent` goes before `callingAgent`.

        Both agents are our handles. An agent in another workspace than the number's is
        refused here: the vendor could not find it, and the number stays as it is."""
        workspace = scope_of(number)
        for handle in (agent, calling_agent):
            if handle is not None and scope_of(handle) != workspace:
                current = await self.get_number(number)
                return Attachment(
                    outcome="refused", state=current, refusal="engine_number_other_workspace"
                )
        current = await self.get_number(number)
        body: dict[str, str | None] = {}
        if current.answering_agent != agent:
            body["agent"] = raw_of(agent) if agent else None
        if current.calling_agent != calling_agent:
            body["callingAgent"] = raw_of(calling_agent) if calling_agent else None
        if not body:
            return Attachment(outcome="unchanged", state=current)
        try:
            row = await self._request(
                "PATCH",
                f"/phone-numbers/{digits(number)}",
                route="/phone-numbers/{number}",
                workspace=workspace,
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
        state = _number(row, workspace)
        if state is None:
            raise _bad("an updated number without its `number`")
        return Attachment(outcome="applied", state=state)

    async def cities(self, workspace: str) -> list[AvailableCity]:
        payload = await self._request(
            "GET",
            "/phone-numbers/available/cities",
            route="/phone-numbers/available/cities",
            workspace=workspace,
        )
        rows = payload.get("items")
        cities: list[AvailableCity] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = _str(row.get("name"))
            count = row.get("available")
            if name is None or isinstance(count, bool) or not isinstance(count, int):
                continue
            cities.append(AvailableCity(name=name, available=count))
        return cities

    async def search(
        self,
        workspace: str,
        *,
        city: str | None,
        pattern: str | None,
        cursor: str | None,
    ) -> AvailablePage:
        params: dict[str, str] = {}
        if city:
            params["city"] = city[:SEARCH_CITY_MAX]
        if pattern:
            params["pattern"] = pattern
        if cursor:
            params["cursor"] = cursor
        payload = await self._request(
            "GET",
            "/phone-numbers/available",
            route="/phone-numbers/available",
            workspace=workspace,
            params=params,
        )
        rows = payload.get("items")
        numbers: list[AvailableEngineNumber] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            raw = _str(row.get("number"))
            if raw is None or not digits(raw):
                continue
            numbers.append(
                AvailableEngineNumber(
                    number=raw,
                    e164=f"+{digits(raw)}",
                    city=_str(row.get("city")),
                    vendor_monthly_inr=_inr(row.get("monthlyPrice")),
                )
            )
        return AvailablePage(numbers=numbers, next_cursor=_str(payload.get("nextCursor")))

    async def rent(self, workspace: str, number: str) -> EngineNumber:
        """Rent `number` in `workspace`. Spends money at the vendor on success only."""
        row = await self._request(
            "POST",
            "/phone-numbers",
            route="/phone-numbers",
            workspace=workspace,
            json={"number": digits(number)},
            # 402 (balance), 409 (held elsewhere, details not approved) are refusals that
            # bought nothing (rent-phone-number.md:7).
            extra_refused_statuses=frozenset({402, 409}),
        )
        parsed = _number(row, workspace)
        if parsed is None:
            raise _bad("a rented number without its `number`")
        return parsed

    async def release(self, number: str) -> None:
        """Give `number` up for good. Absent is success: the postcondition holds."""
        await self._request(
            "DELETE",
            f"/phone-numbers/{digits(number)}",
            route="/phone-numbers/{number}",
            workspace=scope_of(number),
            params={"confirm": "release"},
            absent_is_success=True,
        )

    async def business_details(self, workspace: str | None) -> BusinessDetails:
        return _business(
            await self._request(
                "GET",
                "/phone-numbers/business-details",
                route="/phone-numbers/business-details",
                workspace=workspace,
            )
        )

    async def send_business_details(
        self,
        workspace: str,
        *,
        business_name: str,
        gst_registered: bool,
        document_kind: str,
        document: BusinessDocument,
    ) -> BusinessDetails:
        """`PUT /phone-numbers/business-details` in the client's own workspace."""
        if document_kind not in DOCUMENT_KINDS:
            raise ValueError("documentKind must be gst, incorporation or udyam")
        return _business(
            await self._request(
                "PUT",
                "/phone-numbers/business-details",
                route="/phone-numbers/business-details",
                workspace=workspace,
                data={
                    "businessName": business_name,
                    "gstRegistered": "true" if gst_registered else "false",
                    "documentKind": document_kind,
                },
                files={"document": (document.filename, document.data, document.content_type)},
                extra_refused_statuses=frozenset({409}),
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
    "DOCUMENT_KINDS",
    "Attachment",
    "AttachmentOutcome",
    "AvailableCity",
    "AvailableEngineNumber",
    "AvailablePage",
    "BusinessDetails",
    "BusinessDocument",
    "BusinessStatus",
    "EngineNumber",
    "ThinnestNumbers",
    "digits",
    "set_thinnest_numbers",
    "thinnest_numbers",
]
