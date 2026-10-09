"""Google Sheets actions: write the call into the client's sheet, or answer from it (D-700).

THE SAME IDENTITY AS THE LEAD-DELIVERY SHEETS (D-23), deliberately. The client shares their
spreadsheet with our service account's address (Share → paste → Editor) and the agent reads
and writes that one document; we hold no per-client Google token for it. The brief asked for
OAuth here, and `apps/workers/google_sheets.py` records why D-23 chose the share instead:
`spreadsheets` is a SENSITIVE scope that authorises a person's whole Drive, while a share
grants exactly one document and is revoked in the Sheets UI the client already knows. The
narrow OAuth alternative, `drive.file`, reaches an existing sheet only when the client picks
it through Google's Picker (developers.google.com/workspace/drive/api/guides/
api-specific-auth, read 9 Oct 2026). One way to reach a client's sheet, not two; D-700 records
the choice for the founder to overturn.

VERIFIED-VENDOR-DOCS, read 9 Oct 2026 (developers.google.com/workspace/sheets/api/reference/
rest/v4/spreadsheets.values/…):

* `GET …/spreadsheets/{id}/values/{range}` answers a ValueRange `{range, majorDimension,
  values}` (…/get).
* `POST …/values/{range}:append?valueInputOption=&insertDataOption=INSERT_ROWS` (…/append).
* `POST …/values:batchUpdate` with `{valueInputOption, data: [ValueRange]}` (…/batchUpdate).
* `valueInputOption=RAW` stores values as typed; `USER_ENTERED` would parse a caller's
  `=IMPORTXML(…)` as a formula (…/ValueInputOption), which is why RAW is pinned, as the
  lead sheets pin it (`sheets_sync.VALUE_INPUT_OPTION`).
* Limits: 60 reads and 60 writes a minute per user per project; a 429 asks for backoff
  (…/sheets/api/limits). An in-call lookup is one read.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import quote

import httpx

from apps.api.actions.schema import PreparedRequest
from apps.api.core.settings import get_settings
from apps.workers.google_oauth import ServiceAccount, access_token, parse_service_account
from apps.workers.google_sheets import SCOPE, SHEETS_BASE, a1_sheet, column_letter
from apps.workers.sheets_sync import SERVICE_ACCOUNT_PROVIDER, VALUE_INPUT_OPTION

#: The column of OUR call reference, the key a second write on the same call updates by.
CALL_COLUMN_HEADER: Final = "Calevate call"

#: How many rows a lookup reads. A phone-call lookup in a sheet bigger than this belongs in
#: a CRM; past it the answer is "not found", never a guess.
LOOKUP_MAX_ROWS: Final = 5000


def service_account() -> ServiceAccount | None:
    """The deployment's Google identity, or None when sheets are not configured."""
    settings = get_settings()
    if (settings.google_sheets_provider or "").strip().lower() != SERVICE_ACCOUNT_PROVIDER:
        return None
    raw = (settings.google_sheets_service_account_json or "").strip()
    return parse_service_account(raw) if raw else None


def robot_email() -> str | None:
    """The address a client shares their sheet with."""
    account = service_account()
    return account.client_email if account is not None else None


async def bearer(http: httpx.AsyncClient) -> str | None:
    account = service_account()
    if account is None:
        return None
    return await access_token(http, account, scope=SCOPE)


def _url(spreadsheet_id: str, a1: str, suffix: str = "") -> str:
    return f"{SHEETS_BASE}/{quote(spreadsheet_id, safe='')}/values/{quote(a1, safe='')}{suffix}"


def read_range(*, spreadsheet_id: str, a1: str, token: str) -> PreparedRequest:
    return PreparedRequest(
        method="GET",
        url=_url(spreadsheet_id, a1),
        headers={"Authorization": f"Bearer {token}"},
    )


def append_row(
    *, spreadsheet_id: str, worksheet: str, row: list[str], token: str
) -> PreparedRequest:
    return PreparedRequest(
        method="POST",
        url=_url(
            spreadsheet_id,
            a1_sheet(worksheet),
            f":append?valueInputOption={VALUE_INPUT_OPTION}&insertDataOption=INSERT_ROWS",
        ),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json_body={"majorDimension": "ROWS", "values": [row]},
    )


def write_cells(
    *, spreadsheet_id: str, cells: list[tuple[str, str]], token: str
) -> PreparedRequest:
    """Write individual cells (`(a1, value)`), leaving every other cell of the row alone."""
    return PreparedRequest(
        method="POST",
        url=f"{SHEETS_BASE}/{quote(spreadsheet_id, safe='')}/values:batchUpdate",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json_body={
            "valueInputOption": VALUE_INPUT_OPTION,
            "data": [
                {"range": a1, "majorDimension": "ROWS", "values": [[value]]} for a1, value in cells
            ],
        },
    )


def cell(worksheet: str, column: int, row: int) -> str:
    """A1 of one cell; `column` 0-based, `row` 1-based."""
    return f"{a1_sheet(worksheet)}!{column_letter(column)}{row}"


def rows_of(body: object) -> list[list[str]]:
    """The `values` of a ValueRange as strings; anything else is no rows."""
    values = body.get("values") if isinstance(body, dict) else None
    if not isinstance(values, list):
        return []
    return [[str(v) for v in row] if isinstance(row, list) else [] for row in values]


def digits_tail(raw: str, n: int = 10) -> str:
    """The last `n` digits of a phone number as typed in a sheet (`098765 43210`,
    `+91-98765-43210`), so two spellings of one Indian mobile compare equal."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[-n:] if len(digits) >= n else ""


def find_row(rows: list[list[str]], *, column: int, phone_e164: str) -> int | None:
    """The 0-based index of the first data row (after the header) whose `column` holds the
    caller's number, or None."""
    wanted = digits_tail(phone_e164)
    if not wanted:
        return None
    for index, row in enumerate(rows[1:LOOKUP_MAX_ROWS], start=1):
        if column < len(row) and digits_tail(row[column]) == wanted:
            return index
    return None


__all__ = [
    "CALL_COLUMN_HEADER",
    "LOOKUP_MAX_ROWS",
    "a1_sheet",
    "append_row",
    "bearer",
    "cell",
    "column_letter",
    "digits_tail",
    "find_row",
    "read_range",
    "robot_email",
    "rows_of",
    "service_account",
    "write_cells",
]
