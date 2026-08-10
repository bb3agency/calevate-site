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
_MAX_FREE_TEXT = 200


def redact_text(value: str) -> str:
    """Mask phone-shaped digit runs and cap length. Used on strings we did not author."""
    masked = _PHONE_RE.sub("[phone]", value)
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
