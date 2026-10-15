"""Meta's WhatsApp webhooks, normalized to OUR events (D-784).

Calevate runs one Meta app for every client, so every client's WABA delivers to one
callback (`hook_routes.py`). Each delivery is `{"object": "whatsapp_business_account",
"entry": [{"id": <WABA id>, "changes": [{"field", "value"}]}]}` and may batch up to 1,000
updates; Meta retries a failed delivery "for up to 7 days" and asks receivers to deduplicate
(webhooks/overview.md, webhooks/create-webhook-endpoint.md, read 15 Oct 2026).

WHAT IS KEPT, WHAT IS DROPPED (hard rule 6). Only what an operator or the client acts on
leaves this module: a template's verdict, an account or quality event's code, a failed
delivery's error code and Meta's message id. A status's `recipient_id` is a person's number
and is dropped here; an inbound customer message is counted and dropped (Calevate keeps no
WhatsApp inbox — founder decision 6, send-only). Coexistence echoes (`smb_message_echoes`)
are likewise not stored while coexistence is off; showing them is a condition of turning it
on (OPERATIONS gate W-6).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Final

from apps.api.ingest.meta import MAX_OBJECT_ID_LEN
from apps.api.whatsapp import graph

WABA_OBJECT: Final = "whatsapp_business_account"
#: The most events one delivery may put us to work for. Meta batches "a maximum of 1000
#: updates"; each of ours is one inbox claim and one queued job.
MAX_EVENTS_PER_DELIVERY: Final = 1000

TEMPLATE_STATUS: Final = "message_template_status_update"
TEMPLATE_CATEGORY: Final = "template_category_update"
TEMPLATE_QUALITY: Final = "message_template_quality_update"
ACCOUNT_FIELDS: Final = frozenset(
    {"account_update", "account_alerts", "business_capability_update", "account_review_update"}
)
PHONE_QUALITY: Final = "phone_number_quality_update"
PHONE_NAME: Final = "phone_number_name_update"
MESSAGES: Final = "messages"


@dataclass(frozen=True, slots=True)
class WabaEvent:
    """One thing Meta told us about one WABA, in our words. `kind` decides the handler."""

    waba_id: str
    kind: str
    change: str
    code: str | None = None
    detail: dict[str, str] = field(default_factory=dict)

    def key(self) -> str:
        """The dedupe key: the same event redelivered hashes the same."""
        return hashlib.sha256(graph.dumps(asdict(self)).encode()).hexdigest()

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def _s(value: Any, limit: int = 128) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        cleaned = "".join(ch for ch in value.strip() if ch.isprintable())
        return cleaned[:limit] or None
    return None


def _id(value: Any) -> str | None:
    found = _s(value, MAX_OBJECT_ID_LEN)
    return found if found is not None and found.isdigit() else None


def _detail(**values: Any) -> dict[str, str]:
    return {k: v for k, v in values.items() if isinstance(v, str)}


def _from_change(waba_id: str, name: str, value: dict[str, Any]) -> list[WabaEvent]:
    if name == TEMPLATE_STATUS:
        rejection = value.get("rejection_info")
        reason = _s(value.get("reason")) or (
            _s(rejection.get("reason")) if isinstance(rejection, dict) else None
        )
        return [
            WabaEvent(
                waba_id,
                "template_status",
                name,
                _s(value.get("event"), 32),
                _detail(
                    template_id=_id(value.get("message_template_id")),
                    name=_s(value.get("message_template_name"), 512),
                    language=_s(value.get("message_template_language"), 16),
                    reason=reason,
                ),
            )
        ]
    if name == TEMPLATE_CATEGORY:
        return [
            WabaEvent(
                waba_id,
                "template_category",
                name,
                _s(value.get("new_category"), 32),
                _detail(
                    template_id=_id(value.get("message_template_id")),
                    name=_s(value.get("message_template_name"), 512),
                    language=_s(value.get("message_template_language"), 16),
                    previous=_s(value.get("previous_category"), 32),
                ),
            )
        ]
    if name == TEMPLATE_QUALITY:
        return [
            WabaEvent(
                waba_id,
                "template_quality",
                name,
                _s(value.get("new_quality_score"), 32),
                _detail(
                    template_id=_id(value.get("message_template_id")),
                    name=_s(value.get("message_template_name"), 512),
                    language=_s(value.get("message_template_language"), 16),
                ),
            )
        ]
    if name in ACCOUNT_FIELDS:
        code = (
            _s(value.get("event"), 64)
            or _s(value.get("alert_type"), 64)
            or _s(value.get("decision"), 64)
        )
        return [WabaEvent(waba_id, "account", name, code)]
    if name == PHONE_QUALITY:
        return [
            WabaEvent(
                waba_id,
                "phone_quality",
                name,
                _s(value.get("event"), 32),
                _detail(limit=_s(value.get("current_limit"), 32)),
            )
        ]
    if name == PHONE_NAME:
        return [WabaEvent(waba_id, "phone_name", name, _s(value.get("decision"), 32))]
    if name == MESSAGES:
        events: list[WabaEvent] = []
        statuses = value.get("statuses")
        for status in statuses if isinstance(statuses, list) else []:
            if not isinstance(status, dict) or _s(status.get("status"), 16) != "failed":
                continue
            errors = status.get("errors")
            first = errors[0] if isinstance(errors, list) and errors else {}
            code = _s(first.get("code"), 16) if isinstance(first, dict) else None
            events.append(
                WabaEvent(
                    waba_id,
                    "send_failed",
                    name,
                    code,
                    _detail(message_id=_s(status.get("id"), 256)),
                )
            )
        return events
    return []


def extract_events(payload: Any) -> list[WabaEvent]:
    """Meta's delivery → our events. Anything not ours is skipped, never an error: a 4xx
    would make Meta retry a delivery that is fine."""
    if not isinstance(payload, dict) or payload.get("object") != WABA_OBJECT:
        return []
    entries = payload.get("entry")
    found: list[WabaEvent] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        waba_id = _id(entry.get("id"))
        changes = entry.get("changes")
        if waba_id is None or not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get("value"), dict):
                continue
            name = _s(change.get("field"), 64) or ""
            produced = _from_change(waba_id, name, change["value"])
            # Every change, even one we do not act on, is proof the account's webhooks work.
            found.extend(produced or [WabaEvent(waba_id, "activity", name)])
    return found


def event_from_payload(raw: dict[str, Any]) -> WabaEvent:
    detail = raw.get("detail")
    return WabaEvent(
        waba_id=str(raw["waba_id"]),
        kind=str(raw["kind"]),
        change=str(raw.get("change") or ""),
        code=raw.get("code") if isinstance(raw.get("code"), str) else None,
        detail={str(k): str(v) for k, v in detail.items()} if isinstance(detail, dict) else {},
    )


__all__ = [
    "MAX_EVENTS_PER_DELIVERY",
    "WABA_OBJECT",
    "WabaEvent",
    "event_from_payload",
    "extract_events",
]
