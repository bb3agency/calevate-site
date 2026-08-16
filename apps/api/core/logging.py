"""Structured JSON logging with a redaction path list (BACKEND-PATTERNS §2 step 4).

Hard rule 6 is absolute: never log phone numbers, transcript text or extraction
payloads — log ids. Two defences, because one is never enough:

1. `REDACT_KEYS` — any log-record extra whose key matches is replaced with '[redacted]'
   before it reaches a handler. Substring match, so `caller_phone`/`phone_e164`/
   `from_e164` are all covered by `phone`.
2. `redact_text()` — a value-level scrubber for the places where free text is
   unavoidable (an upstream error string that may quote a payload). E.164-shaped
   digit runs and long text blobs are masked.

The same pair backs the Sentry scrubber (`core/observability.scrub_event`) and the
serializer-exposure guardrail.

WHAT PASSES THROUGH THE FORMATTER, AND WHY THERE IS NO FOURTH PLACE TO FORGET. A log
record carries three payloads and all three reach a handler: the extras, the rendered
MESSAGE, and the exception text. Only the first was scrubbed for most of this file's
life — `record.getMessage()` went out verbatim, so one `log.info("delivering to %s",
phone)` anywhere in the tree would have shipped a number that `redact_mapping` never
saw. Nothing in `apps/` does that today (every log message in the tree is a static
token; `tests/log_redaction_test.py` pins both facts), which is exactly the state in
which a rule survives only as long as everybody remembers it. The formatter is the one
seam every record passes through, so all three go through the redactor here.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from apps.api.core.context import correlation_id_var

REDACT_KEYS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "set-cookie",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "phone",
    "e164",
    "recipient",
    "transcript",
    "text",
    "body",
    "extraction",
    "payload",
    "email",
)

REDACTED = "[redacted]"

# +91XXXXXXXXXX and friends: 8+ digits with optional +, spaces or dashes.
_PHONE_RE = re.compile(r"\+?\d[\d\s-]{7,}\d")
# A uuid is digits and hyphens too, and uuid_v7 is TIME-PREFIXED, so its leading
# segments are mostly decimal — `019fef30-ef78-7420-900b-c603a569b465` contains
# `78-7420-900`, which the phone pattern matches. Masking it corrupts the one thing a
# log line exists to carry: the id you correlate on. It bit us as an intermittently
# failing audit test — intermittent because whether a given uuid contains a
# phone-shaped run is luck. So uuids are lifted out before the phone pass and put back
# after, rather than the phone pattern being loosened (which would risk the opposite,
# and far worse, error).
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# The same hazard for hex digests, and this one is worse. `subject_ref` (sha256[:32])
# is what ties a DPDP access request to the erasure that answered it, and the audit
# chain's `entry_hash` is what proves the chain was not edited — and a digest is a third
# digits by construction, so a phone-shaped run inside one is not unlikely, it is
# routine: `67f5cc9ca451c598d14313258429e5c9` contains `14313258429`. No phone number is
# 32 characters long, so holding runs of 32+ hex digits back cannot hide one.
_HEX_ID_RE = re.compile(r"\b[0-9a-fA-F]{32,64}\b")
# The third identifier shape that is mostly digits and separators, and the one that was
# still being destroyed: an ISO-8601 date. `2026-08-16` is ten characters of
# digits-and-dashes, so the phone pattern matched it whole and `billing/plans.py`'s
# `"at": ...isoformat()` extra rendered as `[phone]T02:00:00+00:00` — a mangled instant
# that reads like a redaction failure, which is worse than a missing field because it
# invites the reader to believe a caller's number was there. Same remedy as the uuid and
# the digest: hold it out of the phone pass rather than loosen the phone pass.
#
# The month and day ranges are what make holding it SAFE. A ten-digit Indian mobile
# written with dashes in date positions (`9812-31-1234`) fails the day range and is
# still masked; only the literal `YYYY-(01..12)-(01..31)` shape is held, which carries
# eight digits in fixed positions and cannot spell an E.164 number. Holding the DATE is
# enough for a full timestamp, because the time half (`T09:34:30+00:00`) is broken up by
# colons the phone pattern does not accept.
#
# The tail is `(?!\d)` and NOT `\b`, which was the first spelling and was wrong: `\b`
# needs a non-word character after the day, and the character after the day in an ISO
# instant is `T`. `(?!\d)` says the only thing that actually matters — that the run does
# not continue into more digits — so `2026-08-16T09:34:30` is held whole and
# `2026-08-1698765432` is not held at all and is masked as the digit run it is.
_ISO_DATE_RE = re.compile(r"\b\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\d)")
_STASH = "\x00"
_MAX_FREE_TEXT = 200

# A traceback is bounded by LINE COUNT rather than by characters (see
# `redact_exception`). A recursion error renders a thousand identical frames and a log
# line is not the place for them; 96 lines is past any real stack in this repo — the
# deepest measured, an exception through the full ASGI middleware chain into a worker
# job, is 61 — and the split keeps the head (where the request entered) and the tail
# (where it died, and the exception line).
_MAX_TRACEBACK_LINES = 96
_TRACEBACK_HEAD_LINES = 24
_TRACEBACK_TAIL_LINES = _MAX_TRACEBACK_LINES - _TRACEBACK_HEAD_LINES


def _mask(value: str) -> str:
    """Phone-shaped digit runs replaced, identifier shapes held back. No length cap."""
    held: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        held.append(match.group(0))
        return f"{_STASH}{len(held) - 1}{_STASH}"

    held_ids = _ISO_DATE_RE.sub(_hold, _HEX_ID_RE.sub(_hold, _UUID_RE.sub(_hold, value)))
    masked = _PHONE_RE.sub("[phone]", held_ids)
    for index, original in enumerate(held):
        masked = masked.replace(f"{_STASH}{index}{_STASH}", original)
    return masked


def redact_text(value: str) -> str:
    """Mask phone-shaped digit runs and cap length. Used on strings we did not author."""
    # Truncation runs LAST, on the restored text, so the cap measures what a reader
    # will actually see rather than the placeholder form.
    masked = _mask(value)
    if len(masked) > _MAX_FREE_TEXT:
        masked = masked[:_MAX_FREE_TEXT] + "…[truncated]"
    return masked


# CPython's own traceback shape, which is what makes the split below a READ rather than
# a guess: `traceback.format_exception` emits these three fixed banners at column 0,
# every frame line and source line INDENTED, and each exception rendered as
# `format_exception_only` does it — `<dotted.TypeName>: <str(exc)>`, or the type alone
# when the exception has no message.
_TRACEBACK_BANNERS = frozenset(
    {
        "Traceback (most recent call last):",
        "During handling of the above exception, another exception occurred:",
        "The above exception was the direct cause of the following exception:",
    }
)
_DOTTED_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
#: What replaces an exception message everywhere one would otherwise be rendered — the
#: log traceback here and `observability.scrub_event`'s `exception.values[].value`. One
#: constant so the two cannot drift, and so an operator who meets it in Sentry can grep
#: the tree and find the reason.
MESSAGE_WITHHELD = "[message withheld]"


def redact_exception(rendered: str) -> str:
    """A traceback that keeps WHERE and WHAT CLASS, and never the exception message.

    Two defects, pulling opposite ways, and both fixed here.

    THE MESSAGE WAS NEVER SAFE. `redact_text` masks phone-shaped digit runs and caps
    length; it cannot recognise a caller's NAME or a Telugu sentence, and an exception
    message is prose assembled upstream. `pydantic.ValidationError` renders
    `input_value=…` — the extraction payload — into `str(exc)` by design; a library we
    hand a value to may echo it; our own `raise ValueError(f"… {turn}")` would too. So
    there is no way to prove a message is not one of hard rule 6's three data classes,
    and the length cap was not a control anyway: whether a message fell inside 200
    characters depended on how deep the stack happened to be. `route_shape_test` says
    the same thing about the same class of accident — "a coincidence, not a control, and
    hard rule 6 does not have a length exemption". The type survives; the message does
    not. Same verdict, same reasoning and the same shape as
    `observability._redacted_events`, which drops `exception.message` off every span.

    THE FRAMES WERE COLLATERAL DAMAGE. The old code ran `redact_text` over the WHOLE
    rendered traceback, and its cap is measured from the start — so a 334-character
    twelve-frame stack was cut off inside frame three. `install_error_handlers` writes
    the only durable record of a 500 on a deployment with no Sentry DSN, the alert body
    tells the operator to "search the logs for code=… for the full context", and there
    was none there to find. Frames are file paths, line numbers, function names and the
    SOURCE line — all authored by us, none of them a runtime value, because CPython
    renders the source text and not the locals. They are kept in full, masked only as a
    backstop against a literal in source.

    What that combination actually reads like is better than it sounds: the source line
    of the `raise` is right there above the withheld message, so `raise ValueError(f"…
    {turn}")` tells the operator exactly what happened without the turn in it.
    """
    lines = rendered.splitlines()
    if len(lines) > _MAX_TRACEBACK_LINES:
        elided = len(lines) - _TRACEBACK_HEAD_LINES - _TRACEBACK_TAIL_LINES
        lines = [
            *lines[:_TRACEBACK_HEAD_LINES],
            f"  …[{elided} traceback lines elided]",
            *lines[-_TRACEBACK_TAIL_LINES:],
        ]
    kept = (_redact_traceback_line(line) for line in lines)
    return "\n".join(line for line in kept if line is not None)


def _redact_traceback_line(line: str) -> str | None:
    """One traceback line, or None for a line that is part of a withheld message."""
    if not line or line[:1].isspace() or line in _TRACEBACK_BANNERS:
        return _mask(line)
    type_name, separator, _message = line.partition(": ")
    if _DOTTED_NAME_RE.match(type_name):
        return f"{type_name}: {MESSAGE_WITHHELD}" if separator else type_name
    # A column-0 line that is not a banner and does not START with a dotted type name is
    # a continuation of the message above it — SQLAlchemy's `[SQL: …]` block, a
    # `DETAIL:` line from the server. The type line already says the message was
    # withheld, so these are dropped rather than annotated one by one.
    return None


def redact_mapping(data: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    """Depth-capped, key-pattern-redacted copy (the audit summary sanitizer, §7)."""
    if depth >= 4:
        return {"…": "[depth-capped]"}
    out: dict[str, Any] = {}
    for key, value in data.items():
        if any(marker in key.lower() for marker in REDACT_KEYS):
            out[key] = REDACTED
        else:
            out[key] = _redact_value(value, depth=depth)
    return out


def _redact_value(value: Any, *, depth: int) -> Any:
    """One extra's value, made safe to serialize.

    FAILS CLOSED ON TYPE, which it did not. The old shape handled `dict`, `str` and
    `list` and let EVERYTHING ELSE through untouched, straight into
    `json.dumps(..., default=str)` — so the object's `repr()` was the log line. A
    `tuple` of turns serialized as a JSON array of raw transcript strings; a Pydantic
    model (this repo puts Pydantic at every boundary) rendered as
    `role='user' text='<the turn>'`; a dataclass and a `bytes` blob did the same. No
    call site in `apps/` does that today — a probe over the whole suite saw 20,377
    records with extras and not one non-scalar — and that is the point: the hole was
    invisible precisely because nothing had fallen in it yet, and the next person to
    write `extra={"turn": turn}` would have had no failing test to stop them.

    Numeric and boolean scalars pass through unchanged because the metric recorders in
    `alerting.py` ride this path and a masked count is a broken SLO. Everything else is
    rendered by US and then masked, so an object cannot decide its own log
    representation.

    THREE TREATMENTS, and the split is by what the value IS rather than by a type list
    to keep in step with the stdlib:

    * A CONTAINER — a mapping is walked, a sequence collapses to a count. Its ELEMENTS
      are the payload and the count is the only part of it a log line wanted.
    * A RECORD — a Pydantic model or a dataclass: a bag of named fields whose `repr()`
      IS a payload. Rendered as its class name and nothing else, which is the same
      fail-closed verdict `observability.sanitize_attributes` reaches for a span
      attribute.
    * A SCALAR — everything else. Numbers and bools pass through untouched, because the
      metric recorders in `alerting.py` ride this path and a masked count is a broken
      SLO; anything else is stringified by US and then masked, so a `Decimal` amount, a
      `UUID`, a `datetime`, an `Enum` member and an `IPv4Address` still render while an
      object cannot choose its own log representation.
    """
    if isinstance(value, dict):
        return redact_mapping(value, depth=depth + 1)
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list | tuple | set | frozenset):
        return f"[{len(value)} items]"
    if value is None or isinstance(value, bool | int | float):
        return value
    # Probed on the TYPE, not imported: `apps/voice-runtime` holds this module on its
    # 500ms ack path (hard rule 3) and must not gain pydantic through it — and reading
    # `model_fields` off the class rather than the instance is also what pydantic 2.11+
    # asks for. `__dataclass_fields__` is `dataclasses.is_dataclass`'s own test.
    kind = type(value)
    if hasattr(kind, "model_fields") or hasattr(kind, "__dataclass_fields__"):
        return f"<{kind.__name__}>"
    return redact_text(str(value))


_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            # Through the redactor like everything else. Every log message in this repo
            # is a static event token, so this is normally an identity transform — but
            # `getMessage()` also renders `%`-args and an f-string, and those are the two
            # spellings that would carry a value into a field nothing else inspects.
            # Measured on a metric record with four extras: 15.6us -> 16.8us per record,
            # which is off the ack path entirely (a handler formats after the response)
            # and 8% of a cost the extras already dominate. See the module docstring.
            "msg": redact_text(record.getMessage()),
        }
        correlation_id = correlation_id_var.get()
        if correlation_id:
            payload["trace_id"] = correlation_id
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            payload.update(redact_mapping(extras))
        if record.exc_info:
            payload["exc"] = redact_exception(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn duplicates access lines through its own handlers; keep one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False

    # httpx logs every OUTBOUND request at INFO as `HTTP Request: <method> <full url>`,
    # and a full URL is not ours to print. Ours carry a client's own webhook endpoint
    # (D-23 — those routinely embed a token in the query string, e.g. Zapier and Make
    # catch hooks), a Google spreadsheet id, which is the capability that names a
    # client's document, and an object-storage presigned URL, which IS the credential.
    # None of that is redactable after the fact by `redact_mapping`, because it arrives
    # as prose inside `msg` rather than as an extra.
    #
    # WARNING, not silence: a transport failure httpx wants to report still gets through.
    # What is dropped is the routine success line, whose only content is the URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


__all__ = [
    "MESSAGE_WITHHELD",
    "REDACTED",
    "REDACT_KEYS",
    "configure_logging",
    "get_logger",
    "redact_exception",
    "redact_mapping",
    "redact_text",
]
