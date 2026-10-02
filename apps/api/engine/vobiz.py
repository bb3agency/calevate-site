"""Vobiz — the carrier the switch selects by default (D-662).

Every request, path and field below is VERIFIED-VENDOR-DOCS, cited into the hash-pinned
mirror `vobiz-findings/mirror/pages/` (index: `docs/evidence/vobiz-api-contract.md`).
What the mirror does not state is named UNKNOWN at the line that depends on it.

Two vendor rules shape every path here:

* `Account` and `Call` are PascalCase and carry a trailing slash; lowercasing or dropping
  the slash answers 401, not 404 (`guides/plivo-to-vobiz/gotchas.md:21-27`). The CDR path is
  the documented exception: `Account` capitalised, `cdr` lowercase, no slash
  (`cdr/get-cdr.md:26`).
* Call create has NO idempotency key (`call/make-call.md:27-72` lists none), so a dial is
  never repeated except on 429, the one status that refused it. That rung lives in
  `vendor_http`, shared with every other adapter.

Hard rule 6: no phone number and no vendor body reaches a log line from this module.
`vendor_http` bounds and redacts what it logs of an error envelope.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from urllib.parse import quote

import httpx
from calevate_shared.carrier import CarrierName
from calevate_shared.config import Settings
from calevate_shared.events import CallDirection, CallStatus

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine.capabilities import engine_not_configured
from apps.api.engine.carrier import CarrierCallEvent, CarrierCdr, PlacedCall
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, EngineRejectedError, vendor_request

log = get_logger(__name__)

#: The label `vendor_http` files this carrier's failures under (`engine_error_spike`).
ENGINE_LABEL: Final = "vobiz"

#: `402 Payment Required` — "Account balance is too low to place the call"
#: (`call/make-call.md:132`). A refusal of the request, so no line was seized.
BALANCE_TOO_LOW: Final = 402
DIAL_REFUSED_STATUSES: Final = frozenset({BALANCE_TOO_LOW})

#: `app_name` admits letters, digits, `-` and `_` only (`applications/create-application.md:29`).
_APP_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
APP_NAME_PREFIX: Final = "calevate-"
#: `limit` is at most 100 (`applications/list-all-applications.md:27`). The page bound
#: keeps a runaway listing from holding a publish open; an account with more applications
#: than this is refused by name rather than given a duplicate.
_APPLICATION_PAGE: Final = 100
_APPLICATION_MAX_PAGES: Final = 20

#: `HangupCause` -> our terminal status (`cdr.md:320-342`). Everything else is `failed`.
_HANGUP_STATUS: Final[dict[str, CallStatus]] = {
    "NORMAL_CLEARING": "completed",
    "USER_BUSY": "busy",
    "NO_ANSWER": "no_answer",
    "ORIGINATOR_CANCEL": "no_answer",
}

#: Stream lifecycle events (`xml/stream.md:68-204`): reported, never a call status.
_STREAM_EVENTS: Final = frozenset(
    {"StartStream", "PlayedStream", "ClearedAudio", "DegradedStream", "DroppedStream", "StopStream"}
)


def application_name(label: str) -> str:
    """The Vobiz application name for one agent: ours, deterministic, and legal there."""
    return APP_NAME_PREFIX + _APP_NAME_UNSAFE.sub("-", label)


def _segment(value: str) -> str:
    """One path segment. A number must be URL-encoded, `+` -> `%2B`
    (`applications/attach-number.md:31`)."""
    return quote(value, safe="")


class VobizCarrier:
    """`CarrierClient` over Vobiz's REST API."""

    def __init__(
        self,
        *,
        auth_id: str | None,
        auth_token: str | None,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._auth_id = auth_id
        self._auth_token = auth_token
        self._base_url = base_url.rstrip("/")
        self._client = client

    @classmethod
    def from_settings(cls, cfg: Settings) -> VobizCarrier:
        return cls(
            auth_id=cfg.vobiz_auth_id,
            auth_token=cfg.vobiz_auth_token,
            base_url=cfg.vobiz_api_base_url,
        )

    @property
    def name(self) -> CarrierName:
        return "vobiz"

    def configured(self) -> bool:
        return bool(self._auth_id and self._auth_token)

    def unavailable(self, operation: str) -> ProblemError | None:
        if self.configured():
            return None
        return engine_not_configured("no_carrier_credentials:vobiz")

    def _new_client(self) -> httpx.AsyncClient:
        """An authenticated client. Both headers on every request
        (`api-reference/authentication.md:12-16`)."""
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-Auth-ID": self._auth_id or "", "X-Auth-Token": self._auth_token or ""},
            timeout=REQUEST_TIMEOUT_S,
        )

    def _account(self, suffix: str) -> str:
        return f"/Account/{quote(self._auth_id or '', safe='')}/{suffix}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """One request, refused before it is built when the credentials are absent.

        On the injected client, or on one opened and closed for this request rather than
        held: `engine/carrier.get_carrier` builds a carrier per operation from the live
        settings, so a held client would be an unclosed connection pool per dial, CDR read
        and binding.
        """
        refusal = self.unavailable("reach its carrier")
        if refusal is not None:
            raise refusal
        if self._client is not None:
            return await vendor_request(self._client, method, path, engine=ENGINE_LABEL, **kwargs)
        async with self._new_client() as client:
            return await vendor_request(client, method, path, engine=ENGINE_LABEL, **kwargs)

    # --- calls ----------------------------------------------------------------------

    async def place_call(
        self,
        *,
        from_e164: str,
        to_e164: str,
        answer_url: str,
        hangup_url: str,
        ring_url: str,
        time_limit_s: int,
    ) -> PlacedCall:
        """`POST /Account/{auth_id}/Call/` (`call/make-call.md:9-72`).

        200 means accepted and queued, not answered (`:122-124`). Numbers are sent in the
        E.164 form the parameter table names (`:31-32`); whether the API also accepts them
        without the `+` its examples print is UNKNOWN and not relied on.
        """
        payload = await self._request(
            "POST",
            self._account("Call/"),
            json={
                "from": from_e164,
                "to": to_e164,
                "answer_url": answer_url,
                "answer_method": "POST",
                "hangup_url": hangup_url,
                "hangup_method": "POST",
                "ring_url": ring_url,
                "ring_method": "POST",
                "time_limit": time_limit_s,
            },
            extra_refused_statuses=DIAL_REFUSED_STATUSES,
        )
        request_uuid = payload.get("request_uuid")
        if not isinstance(request_uuid, str) or not request_uuid:
            # Accepted, and the one field that names the call is missing: the phone may be
            # ringing and we cannot say which call it is. Not a refusal.
            log.warning("carrier_dial_without_call_id", extra={"carrier": self.name})
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unreadable response",
                detail="The telephony carrier accepted the call without naming it.",
                failure_stage="CORE_LOGIC",
            )
        return PlacedCall(carrier=self.name, carrier_call_id=request_uuid)

    async def hang_up(self, carrier_call_id: str) -> bool:
        """`DELETE /Account/{auth_id}/Call/{call_uuid}/` -> 204 (`call/hangup-call.md:9,60`).

        A 404 reads as "nothing to hang up". The hangup page documents no 404; the reading
        is the transfer page's for the same path, "not an active call (already ended or
        never existed)" (`call/transfer-call.md:126`).
        """
        try:
            await self._request("DELETE", self._account(f"Call/{_segment(carrier_call_id)}/"))
        except EngineRejectedError as exc:
            if exc.vendor_status == 404:
                return False
            raise
        return True

    async def transfer(self, carrier_call_id: str, *, redirect_url: str) -> None:
        """`POST /Account/{auth_id}/Call/{call_uuid}/` with `legs=aleg`; 202 Accepted.

        The live flow is interrupted and the XML at `aleg_url` runs immediately
        (`call/transfer-call.md:9-110`). A call that is not in progress answers 404 (`:126`).
        """
        await self._request(
            "POST",
            self._account(f"Call/{_segment(carrier_call_id)}/"),
            json={"legs": "aleg", "aleg_url": redirect_url, "aleg_method": "POST"},
        )

    async def fetch_cdr(self, carrier_call_id: str) -> CarrierCdr | None:
        """`GET /Account/{auth_id}/cdr/{call_uuid}` -> `{data, success}` (`cdr/get-cdr.md:9-26`).

        404 means the record is not there yet: it exists only after the call ends (`:25`).
        Every JSON number is read as `Decimal`, so a cost never passes through a float.
        """
        try:
            payload = await self._request(
                "GET",
                self._account(f"cdr/{_segment(carrier_call_id)}"),
                parse_float=Decimal,
            )
        except EngineRejectedError as exc:
            if exc.vendor_status == 404:
                return None
            raise
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unreadable response",
                detail="The telephony carrier's call record was not in the documented shape.",
                failure_stage="CORE_LOGIC",
            )
        return parse_cdr(data, carrier_call_id=carrier_call_id)

    # --- numbers --------------------------------------------------------------------

    async def bind_number(
        self,
        e164: str,
        *,
        answer_url: str,
        hangup_url: str,
        label: str,
        known_binding_id: str | None = None,
    ) -> str:
        """Point a number at one agent's Application, creating or updating that Application.

        Inbound routing is by Application, not by a per-number URL: the answer URL lives on
        the application and the number points at it (`applications/create-application.md:
        9-49`, `applications/attach-number.md:9-60`). One application per agent, found by
        its deterministic name, so a re-bind updates the URLs rather than leaving a second
        application behind.
        """
        app_name = application_name(label)
        settings = {
            "answer_url": answer_url,
            "answer_method": "POST",
            "hangup_url": hangup_url,
            "hangup_method": "POST",
        }
        app_id = None
        if known_binding_id:
            app_id = await self._application_if_named(known_binding_id, app_name)
        if app_id is None:
            app_id = await self._find_application(app_name)
        if app_id is None:
            created = await self._request(
                "POST", self._account("Application/"), json={"app_name": app_name, **settings}
            )
            app_id = _string_field(created, "app_id")
        else:
            # Partial update (`applications/update-application.md:9-14`).
            await self._request(
                "POST", self._account(f"Application/{_segment(app_id)}/"), json=settings
            )
        await self._request(
            "POST",
            self._account(f"numbers/{_segment(e164)}/application"),
            json={"application_id": app_id},
        )
        return app_id

    async def _application_if_named(self, app_id: str, app_name: str) -> str | None:
        """`app_id` when that application exists and is `app_name`'s, else None.

        `GET /Account/{auth_id}/Application/{app_id}/` (`applications/retrieve-application.
        md:9`). The name check is what makes a remembered id safe: a number last bound to a
        different agent remembers THAT agent's application, and updating it would repoint
        every number still attached to it.
        """
        try:
            found = await self._request("GET", self._account(f"Application/{_segment(app_id)}/"))
        except EngineRejectedError as exc:
            if exc.vendor_status == 404:
                return None
            raise
        return app_id if found.get("app_name") == app_name else None

    async def _find_application(self, app_name: str) -> str | None:
        """The id of the application with this name, or None.

        Paged with `limit`/`offset` (`applications/list-all-applications.md:20-26`).
        """
        for page in range(_APPLICATION_MAX_PAGES):
            listing = await self._request(
                "GET",
                self._account("Application/"),
                params={"limit": _APPLICATION_PAGE, "offset": page * _APPLICATION_PAGE},
            )
            objects = listing.get("objects")
            if not isinstance(objects, list) or not objects:
                return None
            for application in objects:
                if isinstance(application, dict) and application.get("app_name") == app_name:
                    return _string_field(application, "app_id")
            if len(objects) < _APPLICATION_PAGE:
                return None
        raise ProblemError(
            kind="dependency",
            code="carrier_application_listing_too_long",
            title="The carrier account holds too many applications",
            detail="The telephony account holds more applications than we can search.",
            remediation=(
                "Delete unused applications in the Vobiz console, then attach the number again."
            ),
        )

    async def unbind_number(self, e164: str) -> None:
        """`DELETE /Account/{auth_id}/numbers/{number}/application` (`applications/
        detach-number.md:9-60`). A number not in the account answers 404 (`:89`), which is
        the state an unbind wants, so it is success."""
        await self._request(
            "DELETE",
            self._account(f"numbers/{_segment(e164)}/application"),
            absent_is_success=True,
        )

    # --- credentials and callbacks ----------------------------------------------------

    async def probe(self) -> bool:
        """`GET /auth/me` returns the account object for working credentials
        (`api-reference/authentication.md:30-36`). Read-only."""
        try:
            await self._request("GET", "/auth/me")
        except EngineRejectedError as exc:
            if exc.vendor_status in (401, 403):
                return False
            raise
        return True

    def parse_event(self, fields: dict[str, str]) -> CarrierCallEvent | None:
        return parse_event(fields)


def _string_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value:
        raise ProblemError(
            kind="dependency",
            code="engine_bad_response",
            title="Voice engine returned an unreadable response",
            detail="The telephony carrier's answer did not carry the identifier it documents.",
            failure_stage="CORE_LOGIC",
        )
    return value


def parse_event(fields: dict[str, str]) -> CarrierCallEvent | None:
    """One status/hangup callback, normalized (`concepts/callbacks.md:70-105`).

    None when the callback names no call: there is nothing to attribute it to.
    """
    call_id = (fields.get("CallUUID") or "").strip()
    if not call_id:
        return None
    event = (fields.get("Event") or "").strip()
    raw_direction = (fields.get("Direction") or "").strip()
    direction: CallDirection | None = (
        "inbound"
        if raw_direction == "inbound"
        else "outbound"
        if raw_direction == "outbound"
        else None
    )

    def build(kind: Any, status: CallStatus | None, cause: str | None = None) -> CarrierCallEvent:
        return CarrierCallEvent(
            carrier="vobiz",
            carrier_call_id=call_id,
            kind=kind,
            status=status,
            raw_event=event,
            direction=direction,
            hangup_cause=cause,
        )

    if event == "Ring":
        return build("ringing", "ringing")
    if event == "StartApp":
        # Delivered to the answer URL when the called party answers (`:76`).
        return build("answered", "in_progress")
    if event == "Hangup":
        # The authoritative end of the call (`:77`); its status comes from the cause.
        cause = (fields.get("HangupCause") or "").strip() or None
        return build("hangup", _HANGUP_STATUS.get(cause or "", "failed"), cause)
    if event == "MachineDetection":
        return build("machine", "voicemail")
    if event in _STREAM_EVENTS:
        return build("stream", None)
    return build("other", None)


def parse_cdr(data: dict[str, Any], *, carrier_call_id: str) -> CarrierCdr:
    """A CDR object (`cdr.md:257-318`) in our words.

    `billsec` is talk time and is the billable quantity; `duration` is ring plus talk. The
    charge is kept only when the record states it in INR (hard rule 7).
    """
    currency = data.get("currency")
    currency = currency.strip().upper() if isinstance(currency, str) and currency.strip() else None
    total = _decimal(data.get("total_cost"))
    cause = data.get("hangup_cause")
    return CarrierCdr(
        carrier="vobiz",
        carrier_call_id=str(data.get("uuid") or carrier_call_id),
        billed_seconds=_seconds(data.get("billsec")),
        duration_seconds=_seconds(data.get("duration")),
        total_cost_inr=total if currency == "INR" else None,
        currency=currency,
        answered_at=_instant(data.get("answer_time")),
        ended_at=_instant(data.get("end_time")),
        hangup_cause=cause if isinstance(cause, str) and cause else None,
        raw_fields=tuple(sorted(str(key) for key in data)),
    )


def _seconds(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return max(int(value), 0)
    return 0


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return None


def _instant(value: Any) -> datetime | None:
    """An ISO 8601 CDR time (UTC, `Z`-suffixed: `cdr.md:271-276`), or None.

    A time with no offset is refused rather than assumed UTC: the hangup callback's times
    are in the console's local zone (`call/make-call.md:191-194`), and a value that lost
    its zone cannot be told apart from one of those.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = [
    "APP_NAME_PREFIX",
    "BALANCE_TOO_LOW",
    "DIAL_REFUSED_STATUSES",
    "ENGINE_LABEL",
    "VobizCarrier",
    "application_name",
    "parse_cdr",
    "parse_event",
]
