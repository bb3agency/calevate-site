"""Google Sheets sync — the second half of D-23 (`outbound_webhooks.kind='google_sheets'`).

**This module is a transport and a mapper. It is deliberately NOT a vendor integration.**

The schema has offered `google_sheets` since M1 and nothing has ever delivered it, which
is the worst of the three possible states: a client who picks it configures an
integration that silently never fires. This module removes the silence. What it does not
do is pretend: there is no Google service account in this environment, no OAuth flow, and
no `google-api-python-client` in the lockfile (adding a vendor SDK on a guess is exactly
the supply-chain move hard rule 9 forbids). So what ships is the seam — `SheetsTransport`,
a console dev sink, the row mapping, and a refusal — and the day a service account exists
the vendor work is one class implementing one method.

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

**Idempotency is the delivery log, and it has one honest gap.** An append is not
idempotent at the vendor — Sheets has no request key — and a duplicate row in a document
a human is reading cannot be un-seen. So `deliver_outbound_webhook` refuses to append a
delivery already recorded `delivered`. The residual window is a crash between Google
accepting the append and our transaction committing; closing it needs a READ, which is
why `SHEET_DELIVERY_HEADER` puts the delivery id in the last column of every row: an
adapter can look for it before appending. That read is not written here because it cannot
be tested against a real sheet, and an untested reconciliation path is a claim, not a
mechanism.

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


class AppendStatus(StrEnum):
    APPENDED = "appended"
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
        return self.status is AppendStatus.APPENDED

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
    """Selected by environment, exactly like `transport.get_transport()`.

    There is no `GOOGLE_SHEETS_PROVIDER` setting to consult, and that is the honest
    state rather than an oversight: a provider name would imply an adapter behind it,
    and none exists. Local gets the dev sink so the mapping, the ladder and the delivery
    log are exercisable offline; every other environment gets a refusal until a service
    account is provisioned and an adapter is written against it.
    """
    if get_settings().app_env == "local":
        return ConsoleSheetsTransport()
    return UnconfiguredSheetsTransport(NO_CREDENTIALS_REASON)


# --- the mapping + the one call the delivery worker makes ------------------------


async def append_event(
    *,
    endpoint: dict[str, Any],
    event: str,
    data: dict[str, Any],
    delivery_id: Any,
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
    "NO_CREDENTIALS_REASON",
    "NO_CREDENTIAL_REF_REASON",
    "NO_SPREADSHEET_REASON",
    "VALUE_INPUT_OPTION",
    "AppendResult",
    "AppendStatus",
    "ConsoleSheetsTransport",
    "SheetAppend",
    "SheetsTransport",
    "UnconfiguredSheetsTransport",
    "append_event",
    "get_sheets_transport",
]
