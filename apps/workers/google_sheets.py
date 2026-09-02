"""The Google Sheets adapter behind `sheets_sync.SheetsTransport` (D-23).

This is the vendor half of the sheets slice. `apps/workers/sheets_sync.py` owns the
mapping and the refusals, `apps/workers/outbound_webhooks.py` owns the delivery id, the
forensic row and the retry ladder, and NOTHING about "we delivered a lead" is redefined
here — this module only knows how to put a list of strings into someone else's document
and how to report what happened.

It runs in a WORKER. No request handler reaches Google: an append is two to three
round-trips to a third party, and the API's own budget for a request handler does not
include waiting on `oauth2.googleapis.com`.

--------------------------------------------------------------------------------------
WHY A SERVICE ACCOUNT, NOT AN INSTALLED-APP OAUTH FLOW
--------------------------------------------------------------------------------------
Both models can write to a spreadsheet a CUSTOMER owns. The choice was made on who
holds what, and it is a per-document share:

* **Service account + the client shares their sheet with our robot address.** Access is
  granted, and revoked, by the client in the Sheets UI they already know — "Share" →
  paste the address → Editor. Our side holds ONE key pair, no per-tenant refresh token,
  and the blast radius of that key is exactly the set of documents clients chose to
  share. Revocation is a client action that needs no call to us and no code from us.
* **OAuth installed-app / web flow.** Requires a per-tenant consent screen, a refresh
  token PER TENANT held by us in perpetuity (a credential store we do not have and
  would have to build), and — because `.../auth/spreadsheets` is a sensitive scope —
  Google's app-verification review before any client outside our own domain can
  consent. It also authorises against a HUMAN's whole Drive rather than one document:
  the token we would be storing can read every spreadsheet that person can, which is a
  far worse thing to hold than a robot identity with three documents shared to it.

Domain-wide delegation is refused outright, and would be even if we had a Workspace
domain to attach it to: it exists to bypass user consent across an entire organisation,
Google's own guidance is to avoid it where an alternative exists, and our clients are
Indian SMBs largely on personal Gmail accounts where it does not apply at all.
  - https://developers.google.com/identity/protocols/oauth2/service-account (JWT-bearer
    server-to-server flow, RFC 7523 profile: `grant_type=urn:ietf:params:oauth:grant-
    type:jwt-bearer`, RS256 assertion, `aud` = the token endpoint)
  - https://support.google.com/a/answer/14437356 (Google: use domain-wide delegation
    only with a critical business case; prefer OAuth consent or per-resource sharing)

Scope is `https://www.googleapis.com/auth/spreadsheets`, which the Sheets discovery
document lists as one of three that authorise `values.append`. `drive.file` — the
narrower one — grants access only to files the APP created, so it cannot reach a
document the client made and shared, and `drive` is broader than anything we do.

--------------------------------------------------------------------------------------
THE HARD PART: AN APPEND IS NOT IDEMPOTENT AND THE API HAS NO REQUEST KEY
--------------------------------------------------------------------------------------
`spreadsheets.values.append` takes no idempotency token — there is no `requestId` on
the method and no conditional-write header on the values resource (verified against the
live discovery document, rev 20260810,
`https://sheets.googleapis.com/$discovery/rest?version=v4`). So a job that appends, then
crashes before its transaction commits, will append the SAME lead again when arq replays
it, and a duplicate row in a document a human is reading cannot be un-seen.

Three layers close it, in the order they are cheap:

1. **The delivery log.** `deliver_outbound_webhook` refuses to append a delivery already
   recorded `delivered`. That covers every retry that follows a committed attempt.
2. **A read-back probe on RETRIES ONLY.** Layer 1's residual is the crash between Google
   accepting the append and our commit — which by definition can only be observed on
   attempt ≥ 2. So when the worker says this is a retry, we READ the delivery-id column
   (`service.SHEET_DELIVERY_HEADER` is the last column of every row we write, which is
   what makes the document reconcilable at all) and, if this delivery id is already
   there, report `ALREADY_PRESENT` instead of appending. Steady state pays nothing:
   first attempts never read.
3. **A failed probe blocks the append.** If the read itself fails we return a transient
   failure rather than appending blind. Delaying a lead by two minutes is recoverable;
   a duplicate row is not.

The residual after all three is a crash between Google accepting the append and Google
having it readable, which is inside one Google transaction and not observable by us.

Idempotency of the HEADER write is structural instead: it is a `values.update` against
the fixed range `A1`, so writing it twice writes the same cells twice. Two workers
racing on a brand-new sheet both read an empty row 1, both write the identical header,
and both then append — the append is what allocates a row, so no row is lost and no
header is duplicated. (An append-based header could not say that.)

--------------------------------------------------------------------------------------
QUOTAS AND BACKOFF
--------------------------------------------------------------------------------------
Sheets v4 is quota'd per minute, per project AND per user: 300 read requests/min/project
and 60 write requests/min/user/project, exceeded → HTTP 429, with truncated exponential
backoff plus jitter as the documented remedy
(https://developers.google.com/workspace/sheets/api/limits — the page is egress-blocked
from this environment, so those figures are recorded here as documentation-sourced and
still owed a live confirmation, exactly like the vendor claims in OPERATIONS §2).

We do NOT implement a second backoff loop here. 429 and 5xx are reported transient and
the SHARED ladder in `outbound_webhooks.RETRY_BACKOFF_S` (30s, 120s, then a loud
exhaustion alert) walks them, because a client asking why their lead is late must not
get an answer that depends on which transport carried it. What this module DOES do is
mint at most one token per hour per process and read only on retries, so the steady
state is one write request per lead — the quota that matters is the write one, and 60
leads a minute for a single SMB is not a number this product produces.

Hard rule 6 throughout: a row IS the PII. Nothing here logs a cell, a header value, a
spreadsheet id, a credential reference, an access token or a vendor error string.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx

from apps.api.core.logging import get_logger
from apps.api.integrations import service
from apps.workers.google_oauth import (
    access_token,
    parse_service_account,
    reset_token_cache,
)
from apps.workers.sheets_sync import (
    VALUE_INPUT_OPTION,
    AppendResult,
    AppendStatus,
    SheetAppend,
)

# The import goes ONE way: this module depends on the seam, never the reverse at module
# scope. `sheets_sync.get_sheets_transport` imports this file inside the function body
# for exactly that reason — the alternative is an import cycle, and the alternative to
# THAT is duplicating `AppendStatus` on this side, which is how two vocabularies of
# "what happened to the row" get born.

log = get_logger(__name__)

# The provider name that selects this adapter (`GOOGLE_SHEETS_PROVIDER`).
PROVIDER = "service_account"

SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
# See the module docstring: narrower scopes cannot reach a document the client created.
SCOPE = "https://www.googleapis.com/auth/spreadsheets"

# `TOKEN_URL`, `JWT_BEARER_GRANT`, `TOKEN_TTL_S`, `TOKEN_REFRESH_SKEW_S`,
# `ServiceAccount`, `parse_service_account` and the token exchange itself MOVED to
# `apps/workers/google_oauth.py` when Vertex AI (D-127) needed the identical RFC 7523
# flow with a different scope. They are NOT re-exported from here: a name with two
# import paths is the drift this repo treats as a defect even when both work, so the
# callers moved in the same change. What stays is this module's own vocabulary — the
# Sheets scope, the credential reference namespace, and the authored reason codes.

# The only credential reference this deployment can resolve. The scheme is a namespace
# so that a value from a DATABASE ROW can never name arbitrary key material: `secret_ref`
# is client-adjacent config, and a resolver that accepted `sm://platform/kek` would be a
# tenancy hole wearing a config field's clothes.
CREDENTIAL_REF_PREFIX = "sm://google-sheets/"
DEPLOYMENT_CREDENTIAL_NAME = "default"

# Authored reason codes — never vendor prose. A Google error string may quote the row we
# just handed it, and these land in an alert and on a client's own screen.
CREDENTIAL_REF_UNKNOWN_REASON = "credential_ref_unknown"
CREDENTIAL_UNRESOLVABLE_REASON = "google_credential_unresolvable"
AUTH_FAILED_REASON = "google_auth_failed"
SHEET_NOT_SHARED_REASON = "sheet_not_shared"
SPREADSHEET_NOT_FOUND_REASON = "spreadsheet_not_found"
WORKSHEET_REJECTED_REASON = "worksheet_not_found"
RATE_LIMITED_REASON = "google_rate_limited"
UNAVAILABLE_REASON = "google_unavailable"
PROBE_FAILED_REASON = "dedupe_probe_failed"
APPEND_DEADLINE_REASON = "google_deadline_exceeded"

# THE WHOLE-APPEND DEADLINE, and the reason it exists rather than being left to httpx.
# `httpx.Timeout(10.0)` is FOUR ten-second budgets — connect, write, read and pool — and
# the READ one is the maximum wait for A CHUNK, not for the response: it restarts on every
# byte that arrives. Measured on the sibling path (`integrations/service.deliver`,
# `tests/outbound_delivery_deadline_test.py`), a counterparty dribbling one byte every
# three seconds held that call for over 45 seconds under a "10 second" timeout. An append
# is up to FOUR round trips (token, dedupe probe, header read, header write, append), so
# the same stall multiplies, and the only thing that would ever stop it is arq's
# 300-second `job_timeout` — which cancels the JOB, so `record_delivery` never runs and
# the attempt is missing from the client's delivery screen rather than failed on it.
#
# 30 seconds = three `DELIVERY_TIMEOUT_S` round trips, which is the steady state plus one.
# It sits well inside `job_timeout` and inside the shared ladder's 30s first backoff, so
# an attempt that hits this deadline still leaves room for the two that follow it.
APPEND_BUDGET_S = 3 * service.DELIVERY_TIMEOUT_S

# HTTP statuses that mean "the request was fine, the moment was not".
_TRANSIENT_STATUS = frozenset({408, 429})


# --- credentials ------------------------------------------------------------------
# `ServiceAccount` and `parse_service_account` live in `google_oauth` now (see above).


def credential_name(ref: str) -> str | None:
    """The credential a `secret_ref` names, or None if it is not one of ours.

    Deliberately strict about the prefix and about what may follow it. This value comes
    off a row an operator writes; the resolver's whole job is that no row can widen what
    a worker will read.
    """
    if not ref.startswith(CREDENTIAL_REF_PREFIX):
        return None
    name = ref[len(CREDENTIAL_REF_PREFIX) :].strip()
    if not name or "/" in name:
        return None
    return name


# --- caches ------------------------------------------------------------------------
# The TOKEN cache moved to `google_oauth` with the flow that fills it. What stays here is
# the one cache that is about SPREADSHEETS rather than about Google auth.

# (spreadsheet_id, worksheet) pairs this process has confirmed already carry a header.
# Monotonic in practice — a header, once written, stays — and a stale MISS costs one
# extra read plus an idempotent re-write, never a wrong row.
_HEADERED: set[tuple[str, str]] = set()


def reset_caches() -> None:
    """Drop the process-level token and header caches. For tests and for an operator
    rotating the service-account key without a restart.

    Still clears BOTH, even though the token cache is no longer this module's: four test
    files and the rotation runbook call this one verb, and leaving them to remember a
    second one is how a rotation drill starts passing while a stale token keeps being
    sent.
    """
    reset_token_cache()
    _HEADERED.clear()


# --- A1 notation ------------------------------------------------------------------


def a1_sheet(worksheet: str) -> str:
    """A worksheet name as an A1 range prefix.

    Quoted always, and internal apostrophes doubled, which is A1's own escape. A tab
    called `Leads 2026` or `Ravi's leads` is an ordinary thing for a client to make, and
    an unquoted range would be rejected by the API as unparseable — reported to that
    client as "your tab does not exist", which would be a lie about their own sheet.
    """
    return "'" + worksheet.replace("'", "''") + "'"


def column_letter(index: int) -> str:
    """0-based column index → A1 letters (0 → A, 25 → Z, 26 → AA).

    Bijective base-26, which is what spreadsheets use and what a plain base-26 gets
    wrong: there is no zero digit, so column 26 is `AA` and not `BA`.
    """
    letters = ""
    position = index + 1
    while position > 0:
        position, remainder = divmod(position - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _quote_range(a1: str) -> str:
    """A1 ranges go in the URL PATH, where `!`, `'` and space are all meaningful."""
    return quote(a1, safe="")


# --- the transport ----------------------------------------------------------------


class GoogleSheetsTransport:
    """The real thing: OAuth2 JWT-bearer → `values.append`, with a retry-time probe.

    One instance per append is fine and expected — every cache it uses is module-level,
    because the object's lifetime is one delivery and the facts it caches outlive it.
    """

    name = PROVIDER

    def __init__(self, raw_credential: str, *, client: httpx.AsyncClient | None = None) -> None:
        # Parsed once, here, so a malformed key is one refusal rather than a parse
        # failure inside every append.
        self._account = parse_service_account(raw_credential)
        # Same injection seam, and the same ownership rule, as `service.deliver`: a
        # caller-supplied client is the caller's to close. It exists so the tests drive
        # this adapter through httpx's real request plumbing (`httpx.MockTransport`)
        # rather than through a hand-written stand-in that cannot get a URL wrong.
        self._client = client

    async def append(self, request: SheetAppend) -> AppendResult:
        if credential_name(request.credential_ref) != DEPLOYMENT_CREDENTIAL_NAME:
            # The endpoint names a credential this deployment does not hold. An operator
            # error, and specifically the one that must not silently fall back to "well,
            # use the only key we have" — an endpoint pointed at a credential we cannot
            # resolve has not been configured yet.
            return AppendResult(AppendStatus.REJECTED, reason=CREDENTIAL_REF_UNKNOWN_REASON)
        account = self._account
        if account is None:
            return AppendResult(AppendStatus.REJECTED, reason=CREDENTIAL_UNRESOLVABLE_REASON)

        owns_client = self._client is None
        http = self._client or httpx.AsyncClient(
            timeout=service.DELIVERY_TIMEOUT_S, follow_redirects=False
        )
        try:
            # A WALL-CLOCK DEADLINE OVER THE WHOLE APPEND — see `APPEND_BUDGET_S`. httpx
            # has no whole-request deadline at all, so without this an append is four
            # round trips each of which a stalled response can hold indefinitely.
            async with asyncio.timeout(APPEND_BUDGET_S):
                token = await access_token(http, account, scope=SCOPE)
                if token is None:
                    # Could be a network blip or a bad key; the token endpoint does not
                    # let us tell those apart without reading a body we will not read.
                    # Transient so the shared ladder tries twice more, then alerts loudly.
                    return AppendResult(AppendStatus.TRANSPORT_FAILED, reason=AUTH_FAILED_REASON)
                return await self._append_with_token(http, token, request)
        except TimeoutError:
            # Reported like any other transport failure, and TRANSIENT: a deadline says
            # Google was slow, not that this row may never be written. Crucially it must
            # NOT be allowed to escape — an exception out of here is not a `Retry`, so arq
            # would finish the job after one attempt and no delivery row would ever say
            # what happened (`outbound_webhooks.py` documents that mechanism at length).
            log.warning("sheet_append_deadline", extra={"worksheet": request.worksheet})
            return AppendResult(AppendStatus.TRANSPORT_FAILED, reason=APPEND_DEADLINE_REASON)
        finally:
            if owns_client:
                await http.aclose()

    async def _append_with_token(
        self, http: httpx.AsyncClient, token: str, request: SheetAppend
    ) -> AppendResult:
        headers = {"Authorization": f"Bearer {token}"}
        sheet_key = (request.spreadsheet_id, request.worksheet)

        if request.dedupe_probe:
            # Layer 2 of the idempotency argument in the module docstring. A retry may be
            # following an append Google already accepted, so look before writing.
            seen, failure = await self._delivery_ids(http, headers, request)
            if failure is not None:
                return failure
            if seen is not None and request.values and request.values[-1] in seen:
                log.info("sheet_append_already_present", extra={"worksheet": request.worksheet})
                return AppendResult(AppendStatus.ALREADY_PRESENT)
            if seen:
                # A non-empty delivery column is proof the header row exists, so the
                # header check below can be skipped for free.
                _HEADERED.add(sheet_key)

        if sheet_key not in _HEADERED:
            failure = await self._ensure_header(http, headers, request)
            if failure is not None:
                return failure
            _HEADERED.add(sheet_key)

        # `insertDataOption=INSERT_ROWS` rather than the `OVERWRITE` default: OVERWRITE
        # writes into whatever cells follow the detected table, so a client with a
        # totals block or a second table below their leads would have it silently
        # overwritten by a lead. INSERT_ROWS pushes rows down instead (discovery doc:
        # "Rows are inserted for the new data").
        params = {
            # `RAW`, from the one constant that defines it: `sheets_sync` is where the
            # argument for RAW-over-USER_ENTERED lives (a client-supplied lead name must
            # never become a formula), and a second literal here would be a second place
            # for that decision to be quietly changed.
            "valueInputOption": VALUE_INPUT_OPTION,
            "insertDataOption": "INSERT_ROWS",
            # We do not need the appended values echoed back, and asking for them would
            # put the lead's own cells into an HTTP response we then have to be careful
            # with. Stated rather than left to the default, because the default is what
            # a future edit changes by accident.
            "includeValuesInResponse": "false",
        }
        # The range is the whole worksheet: the API searches it for the "table" and
        # appends after the last row of it (discovery doc, `values.append`).
        whole_sheet = _quote_range(a1_sheet(request.worksheet))
        url = f"{SHEETS_BASE}/{request.spreadsheet_id}/values/{whole_sheet}:append"
        try:
            response = await http.post(
                url,
                params=params,
                json={"values": [list(request.values)]},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            return AppendResult(AppendStatus.TRANSPORT_FAILED, reason=type(exc).__name__)
        if response.status_code == 200:
            log.info(
                "sheet_append_ok",
                # Shape only — never a cell, never the document id (a capability).
                extra={"worksheet": request.worksheet, "cells": len(request.values)},
            )
            return AppendResult(AppendStatus.APPENDED)
        return _classify(response.status_code)

    async def _delivery_ids(
        self, http: httpx.AsyncClient, headers: dict[str, str], request: SheetAppend
    ) -> tuple[list[str] | None, AppendResult | None]:
        """Every delivery id already in the sheet, or a failure that must stop the append.

        Reads ONE column — the last one, which is where `service.sheet_row` puts the
        delivery id — as a single `values.get`. `majorDimension=COLUMNS` so the response
        is one list rather than one list per row.
        """
        column = column_letter(len(request.header) - 1)
        a1 = f"{a1_sheet(request.worksheet)}!{column}:{column}"
        url = f"{SHEETS_BASE}/{request.spreadsheet_id}/values/{_quote_range(a1)}"
        try:
            response = await http.get(url, params={"majorDimension": "COLUMNS"}, headers=headers)
        except httpx.HTTPError as exc:
            # Could not check, so must not append: a blind append here is exactly the
            # duplicate row this probe exists to prevent.
            return None, AppendResult(AppendStatus.TRANSPORT_FAILED, reason=type(exc).__name__)
        if response.status_code != 200:
            classified = _classify(response.status_code)
            if classified.status is AppendStatus.TRANSPORT_FAILED:
                return None, AppendResult(AppendStatus.TRANSPORT_FAILED, reason=PROBE_FAILED_REASON)
            return None, classified
        try:
            values: list[list[Any]] = response.json().get("values") or []
        except ValueError:
            return None, AppendResult(AppendStatus.TRANSPORT_FAILED, reason=PROBE_FAILED_REASON)
        if not values:
            return [], None
        return [str(cell) for cell in values[0]], None

    async def _ensure_header(
        self, http: httpx.AsyncClient, headers: dict[str, str], request: SheetAppend
    ) -> AppendResult | None:
        """Write the header row iff row 1 is empty. None means "carry on".

        `values.update` against the fixed range starting at A1, NOT an append: writing
        the same header twice is a no-op, so two workers racing on a brand-new sheet
        cannot produce two header rows (see the module docstring). An append-based
        header could, and the loser's row would sit under a duplicated heading forever.
        """
        row_one = f"{a1_sheet(request.worksheet)}!1:1"
        url = f"{SHEETS_BASE}/{request.spreadsheet_id}/values/{_quote_range(row_one)}"
        try:
            response = await http.get(url, headers=headers)
        except httpx.HTTPError as exc:
            return AppendResult(AppendStatus.TRANSPORT_FAILED, reason=type(exc).__name__)
        if response.status_code != 200:
            return _classify(response.status_code)
        try:
            existing = response.json().get("values") or []
        except ValueError:
            existing = []
        if existing:
            # The client's sheet already has a first row. It is THEIR document; we do not
            # decide their headings are wrong, we just stop checking.
            return None

        last = column_letter(len(request.header) - 1)
        target = f"{a1_sheet(request.worksheet)}!A1:{last}1"
        write_url = f"{SHEETS_BASE}/{request.spreadsheet_id}/values/{_quote_range(target)}"
        try:
            written = await http.put(
                write_url,
                params={"valueInputOption": VALUE_INPUT_OPTION},
                json={"values": [list(request.header)]},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            return AppendResult(AppendStatus.TRANSPORT_FAILED, reason=type(exc).__name__)
        if written.status_code != 200:
            return _classify(written.status_code)
        log.info("sheet_header_written", extra={"worksheet": request.worksheet})
        return None


def _classify(status: int) -> AppendResult:
    """One HTTP status → one authored reason, and a verdict on whether to try again.

    The permanent ones are permanent for a reason a HUMAN can act on, which is the whole
    point: `sheet_not_shared` tells a client to share their document, and no number of
    retries will do it for them.
    """
    if status in _TRANSIENT_STATUS:
        return AppendResult(AppendStatus.TRANSPORT_FAILED, reason=RATE_LIMITED_REASON)
    if status >= 500:
        return AppendResult(AppendStatus.TRANSPORT_FAILED, reason=UNAVAILABLE_REASON)
    if status == 401:
        # See `google_oauth.TOKEN_REFRESH_SKEW_S`: our tokens are never near expiry, so a
        # 401 is a statement about the KEY.
        return AppendResult(AppendStatus.REJECTED, reason=AUTH_FAILED_REASON)
    if status == 403:
        # ⚠ MARKED ASSUMPTION, NOT A VERIFIED FACT (CLAUDE.md hard rule 11). This treats
        # 403 as "the client has not shared the document" — permanent, and the client-
        # facing sentence tells them to share it. Google's APIs have historically also
        # answered 403 for QUOTA (`rateLimitExceeded` / `userRateLimitExceeded` /
        # `quotaExceeded`), which would be TRANSIENT and would need the opposite verdict
        # and a different sentence. Whether Sheets v4 does that TODAY is UNKNOWN here:
        # `developers.google.com` is refused by this environment's egress proxy
        # (WebFetch → EGRESS_BLOCKED, re-measured 2 Sep 2026), so nobody in this repo has
        # read the page, and the quota figures in this module's docstring are
        # documentation-sourced for the same reason.
        #
        # Deliberately NOT guessed either way. Telling a quota-limited client to re-share
        # a document they already shared is a wrong instruction; classifying a genuine
        # permission failure as transient buries it under three silent retries and an
        # `google_unavailable` that nobody can act on. Closing this needs one reading of
        # the live API — the `error.status`/`errors[].reason` a real 403 carries — which
        # is the same operator errand as the other Google claims here.
        return AppendResult(AppendStatus.REJECTED, reason=SHEET_NOT_SHARED_REASON)
    if status == 404:
        return AppendResult(AppendStatus.REJECTED, reason=SPREADSHEET_NOT_FOUND_REASON)
    # 400 is overwhelmingly "Unable to parse range", i.e. the named tab is not in the
    # document. Everything else in the 4xx band is a request WE built being wrong, and
    # repeating it cannot fix it either.
    return AppendResult(AppendStatus.REJECTED, reason=WORKSHEET_REJECTED_REASON)


__all__ = [
    "APPEND_BUDGET_S",
    "APPEND_DEADLINE_REASON",
    "AUTH_FAILED_REASON",
    "CREDENTIAL_REF_PREFIX",
    "CREDENTIAL_REF_UNKNOWN_REASON",
    "CREDENTIAL_UNRESOLVABLE_REASON",
    "DEPLOYMENT_CREDENTIAL_NAME",
    "PROBE_FAILED_REASON",
    "PROVIDER",
    "RATE_LIMITED_REASON",
    "SCOPE",
    "SHEET_NOT_SHARED_REASON",
    "SPREADSHEET_NOT_FOUND_REASON",
    "UNAVAILABLE_REASON",
    "WORKSHEET_REJECTED_REASON",
    "GoogleSheetsTransport",
    "a1_sheet",
    "column_letter",
    "credential_name",
    "reset_caches",
]
