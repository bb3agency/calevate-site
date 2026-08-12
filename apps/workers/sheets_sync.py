"""Google Sheets sync — the second half of D-23 (`outbound_webhooks.kind='google_sheets'`).

**This module is a transport and a mapper. It is deliberately NOT a vendor integration.**

The schema has offered `google_sheets` since M1 and nothing has ever delivered it, which
is the worst of the three possible states: a client who picks it configures an
integration that silently never fires. This module removes the silence by owning the
SEAM — `SheetsTransport`, a console dev sink, the row mapping, and a set of named
refusals — and nothing here knows what Google is.

The vendor half now exists and lives behind that seam in `apps/workers/google_sheets.py`
(`GOOGLE_SHEETS_PROVIDER=service_account`): a service account the client shares their own
document with, minting its own OAuth2 token, calling `spreadsheets.values.append`. It is
selected by config and imported inside `get_sheets_transport`, so a deployment with no
Google credential never loads it and every refusal below still reads the same. No vendor
SDK was added for it — `pyjwt[crypto]` and `httpx` were already in the lockfile and the
API is three REST calls (hard rule 9: a vendor SDK on a guess is the supply-chain move,
and this one would have been a guess).

Shape mirrors `workers/transport.py` and `workers/whatsapp.py` on purpose: a Protocol, a
dev sink that needs no credentials and no network, and the real provider chosen by
config. `append` is async where `WhatsAppTransport.send` is sync, because this one runs
inside `deliver_outbound_webhook` — the same job, the same event loop as the signed POST
next to it — and a blocking HTTP call there would stall every other delivery on the worker.

**There is no second definition of "delivered".** This module owns the mapping and the
transport ONLY. The delivery id, the forensic row in `webhook_deliveries`, the dedupe and
the retry ladder all stay in `outbound_webhooks.py`, shared with the webhook path, because
a client asking "did my lead arrive?" must get an answer built the same way whichever box
they ticked.

**Idempotency is the delivery log, plus one read on retries.** An append is not
idempotent at the vendor — Sheets v4 has no request key on `values.append` (verified
against the live discovery document, rev 20260810) — and a duplicate row in a document a
human is reading cannot be un-seen. Two layers:

1. `deliver_outbound_webhook` refuses to append a delivery already recorded `delivered`,
   which covers every retry that follows a committed attempt.
2. The residual is a crash between Google accepting the append and our transaction
   committing, and that is observable only from attempt 2 onward. So `append_event` sets
   `SheetAppend.dedupe_probe` on retries, and the adapter READS the delivery-id column
   before writing. This is why `SHEET_DELIVERY_HEADER` is the last column of every row:
   the id in the document is what makes the document reconcilable against the log, by an
   adapter and by a human.

First attempts pay nothing for this; only a retry reads.

**Formula injection is a real risk here, unlike on the webhook path.** A lead's name is
written by a caller or a web form and lands in a document a human opens; `=IMPORTXML(…)`
in a name cell exfiltrates the row. `VALUE_INPUT_OPTION` pins the API contract to `RAW`
and `service._disarm` neutralises the leading characters anyway.

Hard rule 6: a row IS the PII — name, and on a per-endpoint opt-in the phone number.
Nothing here logs a cell, a header value, the spreadsheet id or the credential reference.
Ids, the worksheet name and counts only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.integrations import service

log = get_logger(__name__)

# The Sheets API's own parameter name and the ONLY value this integration may use.
# `USER_ENTERED` makes every cell a candidate expression; `RAW` stores what we send.
VALUE_INPUT_OPTION = "RAW"

# Authored reason codes. Never vendor prose — a provider's error string is untrusted
# text that may quote the row we just handed it, and this one lands in an alert.
NO_CREDENTIALS_REASON = "no_google_credentials"
NO_CREDENTIAL_REF_REASON = "no_credential_ref"
NO_SPREADSHEET_REASON = "no_spreadsheet_configured"
# `GOOGLE_SHEETS_PROVIDER=console` outside local: operator error of the kind that
# reports success forever.
DEV_SINK_OUTSIDE_LOCAL_REASON = "dev_sink_refused_outside_local"
# A provider name with no adapter behind it. Suffixed with the name so the alert says
# which one was expected — the name is OUR config, not vendor prose.
PROVIDER_NOT_IMPLEMENTED_REASON = "provider_not_implemented"

# The dev sink. Not a vendor — it writes to a terminal.
CONSOLE_PROVIDER = "console"
# The real one: `apps/workers/google_sheets.py`, a service account the client shares
# their document with. Kept as a name here rather than imported from that module so the
# selector below can decide WITHOUT importing an httpx/JWT stack it may not need.
SERVICE_ACCOUNT_PROVIDER = "service_account"


# --- the request ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SheetAppend:
    """One row, addressed. Everything an adapter needs and nothing it does not.

    `credential_ref` is a secrets-manager REFERENCE (`outbound_webhooks.secret_ref`),
    never a credential: resolving it is the adapter's job at the moment of use, so no
    key material passes through this module, gets held in a dataclass, or reaches a
    traceback.
    """

    spreadsheet_id: str
    worksheet: str
    # Written by an adapter only when the target sheet is empty; we cannot know whether
    # it is without a read, so this travels with every append rather than being guessed.
    header: tuple[str, ...]
    values: tuple[str, ...]
    credential_ref: str
    # "This delivery has been attempted before, so LOOK before you write." Set only on
    # arq attempt ≥ 2 (see `append_event`). It is a request field rather than a second
    # transport method because the check and the write have to be one decision: a
    # transport that could be asked to check and then told to append anyway would let a
    # caller reintroduce the duplicate this exists to prevent.
    dedupe_probe: bool = False


class AppendStatus(StrEnum):
    APPENDED = "appended"
    # The adapter found this delivery id already in the sheet and did NOT append again.
    # Distinct from APPENDED because the two are different events for an operator
    # reading logs — one wrote a row, one prevented a duplicate — and identical for the
    # client, whose lead is in their sheet either way.
    ALREADY_PRESENT = "already_present"
    # The API could not be reached, or reported a condition that may pass (429, 5xx).
    TRANSPORT_FAILED = "transport_failed"
    # A verdict: no service account, sheet not shared with us, tab missing. Retrying
    # reaches the same answer two minutes later.
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AppendResult:
    status: AppendStatus
    reason: str = ""

    @property
    def appended(self) -> bool:
        """Is the row IN THE SHEET? — which is the question the delivery log asks.

        `ALREADY_PRESENT` counts. A retry that discovers its own earlier append did land
        has delivered the lead; recording it `failed` would put a red row on the client's
        screen for a lead sitting in their spreadsheet, and would leave the delivery
        eligible for yet another attempt.
        """
        return self.status in (AppendStatus.APPENDED, AppendStatus.ALREADY_PRESENT)

    @property
    def retryable(self) -> bool:
        return self.status is AppendStatus.TRANSPORT_FAILED


class SheetsTransport(Protocol):
    name: str

    async def append(self, request: SheetAppend) -> AppendResult: ...


# --- transports ------------------------------------------------------------------


class ConsoleSheetsTransport:
    """Local dev + the test suite. No credentials, no network, no Google project.

    Reports APPENDED honestly, for the same reason `ConsoleTransport` reports success:
    the row really did arrive — in the developer's terminal.
    """

    name = "console"

    async def append(self, request: SheetAppend) -> AppendResult:
        # The SHAPE, never the contents: cells carry the caller's name and possibly
        # their number, the header carries the client's own column names, and the
        # spreadsheet id plus the credential ref are both capabilities.
        log.info(
            "sheet_append_console",
            extra={
                "worksheet": request.worksheet,
                "cells": len(request.values),
                "value_input": VALUE_INPUT_OPTION,
            },
        )
        return AppendResult(AppendStatus.APPENDED)


class UnconfiguredSheetsTransport:
    """No usable Google credentials. Reports REJECTED — permanently, and says why.

    Returning APPENDED would put a green `delivered` on the client's own delivery screen
    for a sheet that stayed empty forever, which is the exact failure
    `transport.NullTransport` exists to prevent on the email side. REJECTED rather than
    TRANSPORT_FAILED because three retries cannot provision a service account.
    """

    name = "unconfigured"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def append(self, request: SheetAppend) -> AppendResult:
        log.warning("sheet_no_transport", extra={"reason": self._reason})
        return AppendResult(AppendStatus.REJECTED, reason=self._reason)


def get_sheets_transport() -> SheetsTransport:
    """Selected by config, exactly like `whatsapp.get_whatsapp_transport()`.

    `google_sheets_provider` is the seam where a real adapter lands. Any name other
    than the dev sink resolves to `provider_not_implemented`, on purpose: setting
    `GOOGLE_SHEETS_PROVIDER=gspread` today must fail loudly rather than look configured.

    This used to read `app_env == "local"` and nothing else, which was honest about the
    transport but useless to everything else — "are we on a laptop" is not a statement
    about Google Sheets, so no client-facing surface could gate on it, and the config
    file could not record that a deployment had been given an adapter. The environment
    is now only the FALLBACK, and it is explicit: unset means the dev sink locally and
    a refusal everywhere else.
    """
    settings = get_settings()
    provider = (settings.google_sheets_provider or "").strip().lower()

    if provider == SERVICE_ACCOUNT_PROVIDER:
        # Imported HERE, not at module scope: `apps.workers.google_sheets` imports this
        # module for the Protocol and the result vocabulary, so a top-level import would
        # be a cycle. The seam depends on nothing; the adapter depends on the seam.
        from apps.workers.google_sheets import GoogleSheetsTransport

        raw = (settings.google_sheets_service_account_json or "").strip()
        if not raw:
            # A provider named with no key behind it is the same class of operator error
            # as the dev sink outside local: it would report a transport that cannot
            # authenticate, and `sheets_delivery_available()` — the API's gate — would
            # start offering the checkbox.
            return UnconfiguredSheetsTransport(NO_CREDENTIALS_REASON)
        return GoogleSheetsTransport(raw)

    if provider == CONSOLE_PROVIDER:
        if settings.app_env != "local":
            # An explicit dev sink outside local is operator error, and it is the kind
            # that reports every lead appended forever. Refuse it rather than swallow
            # rows into a terminal nobody reads.
            return UnconfiguredSheetsTransport(DEV_SINK_OUTSIDE_LOCAL_REASON)
        return ConsoleSheetsTransport()
    if provider:
        return UnconfiguredSheetsTransport(f"{PROVIDER_NOT_IMPLEMENTED_REASON}:{provider}")
    if settings.app_env == "local":
        return ConsoleSheetsTransport()
    return UnconfiguredSheetsTransport(NO_CREDENTIALS_REASON)


def sheets_delivery_available() -> bool:
    """Can THIS deployment append to a sheet at all?

    Asked by the config surface (`POST /v1/integrations/endpoints/sheets`) so that a
    client is never handed an endpoint nothing can deliver to. It is deliberately the
    SAME selector the worker calls rather than a second read of the same settings: a
    config screen that decided for itself whether sheets work would eventually disagree
    with the worker, and the disagreement would read as "the screen says configured and
    the spreadsheet stays empty" — the exact defect this module exists to kill.

    It answers for the TRANSPORT only. Whether a particular endpoint has a credential
    reference is a property of that row, checked in `append_event`.
    """
    return not isinstance(get_sheets_transport(), UnconfiguredSheetsTransport)


# --- the mapping + the one call the delivery worker makes ------------------------


async def append_event(
    *,
    endpoint: dict[str, Any],
    event: str,
    data: dict[str, Any],
    delivery_id: Any,
    attempt: int = 1,
) -> service.DeliveryResult:
    """Turn one normalized event into one row and hand it to the transport.

    Returns the SAME `DeliveryResult` the signed POST returns, with `transient` stated
    explicitly — there is no status code here for the ladder to reason about, so an
    unstated result would read as a blip and a permanent refusal would be retried three
    times to reach the same no.

    `data` arrives already redacted per endpoint (`service.enqueue_event` applies the
    `include_raw_phone` opt-in at the fan-out, which is the last point that knows which
    endpoint a payload is for). Nothing is re-masked here and nothing is un-masked.
    """
    mapping = endpoint.get("mapping") or {}

    spreadsheet_id = service.parse_spreadsheet_ref(endpoint.get("url"))
    if spreadsheet_id is None:
        return _refused(NO_SPREADSHEET_REASON)

    credential_ref = str(endpoint.get("secret") or "").strip()
    if not credential_ref:
        # An endpoint with no secrets-manager reference cannot reach any sheet, ever.
        # Saying so on the delivery screen is the entire point of this module.
        return _refused(NO_CREDENTIAL_REF_REASON)

    columns = service.sheet_columns(event, mapping)
    if not columns:
        # We know the payload but not the column ORDER, and guessing it from this row's
        # keys shifts every value the first time a field is absent.
        return _refused(f"no_column_order:{event}")

    result = await get_sheets_transport().append(
        SheetAppend(
            spreadsheet_id=spreadsheet_id,
            worksheet=service.sheet_worksheet(mapping),
            header=tuple(service.sheet_header(columns, mapping)),
            values=tuple(service.sheet_row(data, columns, delivery_id)),
            credential_ref=credential_ref,
            # THE residual window, closed. `deliver_outbound_webhook` already refuses a
            # delivery recorded `delivered`, so the only way a duplicate can happen is a
            # crash between Google accepting the append and our transaction committing —
            # and that is observable only from attempt 2 onward. Probing on the first
            # attempt would buy nothing and cost a read per lead.
            dedupe_probe=attempt > 1,
        )
    )
    return service.DeliveryResult(
        delivered=result.appended,
        status_code=None,
        error=None if result.appended else (result.reason or str(result.status)),
        channel=CHANNEL,
        transient=result.retryable,
    )


CHANNEL = "sheets"


def _refused(reason: str) -> service.DeliveryResult:
    """A config verdict, reached without calling a vendor to discover what we already
    know. Permanent: the same row will be just as unconfigured in two minutes."""
    return service.DeliveryResult(
        delivered=False, status_code=None, error=reason, channel=CHANNEL, transient=False
    )


__all__ = [
    "CHANNEL",
    "CONSOLE_PROVIDER",
    "DEV_SINK_OUTSIDE_LOCAL_REASON",
    "NO_CREDENTIALS_REASON",
    "NO_CREDENTIAL_REF_REASON",
    "NO_SPREADSHEET_REASON",
    "PROVIDER_NOT_IMPLEMENTED_REASON",
    "SERVICE_ACCOUNT_PROVIDER",
    "VALUE_INPUT_OPTION",
    "AppendResult",
    "AppendStatus",
    "ConsoleSheetsTransport",
    "SheetAppend",
    "SheetsTransport",
    "UnconfiguredSheetsTransport",
    "append_event",
    "get_sheets_transport",
    "sheets_delivery_available",
]
