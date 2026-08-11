"""Structured JSON logging with a redaction path list (BACKEND-PATTERNS §2 step 4).

Hard rule 6 is absolute: never log phone numbers, transcript text or extraction
payloads — log ids. Two defences, because one is never enough:

1. `REDACT_KEYS` — any log-record extra whose key matches is replaced with '[redacted]'
   before it reaches a handler. Substring match, so `caller_phone`/`phone_e164`/
   `from_e164` are all covered by `phone`.
2. `redact_text()` — a value-level scrubber for the places where free text is
   unavoidable (an upstream error string that may quote a payload). E.164-shaped
   digit runs and long text blobs are masked.

The same pair backs the Langfuse redaction hook and the serializer-exposure guardrail.
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
_STASH = "\x00"
_MAX_FREE_TEXT = 200


def redact_text(value: str) -> str:
    """Mask phone-shaped digit runs and cap length. Used on strings we did not author."""
    held: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        held.append(match.group(0))
        return f"{_STASH}{len(held) - 1}{_STASH}"

    held_ids = _HEX_ID_RE.sub(_hold, _UUID_RE.sub(_hold, value))
    masked = _PHONE_RE.sub("[phone]", held_ids)
    for index, original in enumerate(held):
        masked = masked.replace(f"{_STASH}{index}{_STASH}", original)
    # Truncation runs LAST, on the restored text, so the cap measures what a reader
    # will actually see rather than the placeholder form.
    if len(masked) > _MAX_FREE_TEXT:
        masked = masked[:_MAX_FREE_TEXT] + "…[truncated]"
    return masked


def redact_mapping(data: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    """Depth-capped, key-pattern-redacted copy (the audit summary sanitizer, §7)."""
    if depth >= 4:
        return {"…": "[depth-capped]"}
    out: dict[str, Any] = {}
    for key, value in data.items():
        if any(marker in key.lower() for marker in REDACT_KEYS):
            out[key] = REDACTED
        elif isinstance(value, dict):
            out[key] = redact_mapping(value, depth=depth + 1)
        elif isinstance(value, str):
            out[key] = redact_text(value)
        elif isinstance(value, list):
            out[key] = f"[{len(value)} items]"
        else:
            out[key] = value
    return out


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
            "msg": record.getMessage(),
        }
        correlation_id = correlation_id_var.get()
        if correlation_id:
            payload["trace_id"] = correlation_id
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            payload.update(redact_mapping(extras))
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
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


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


__all__ = [
    "REDACTED",
    "REDACT_KEYS",
    "configure_logging",
    "get_logger",
    "redact_mapping",
    "redact_text",
]
