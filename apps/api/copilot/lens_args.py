"""The lens as Pip passes it (D-893 F2): one `lens` argument, the same shape on the `_find`
that reads a set and the `_do` that acts on it.

A find answers with a count, a few examples and the lens as a short JSON handle; the model
copies that handle into the action, so the set stays on the server and is frozen there by
the plan (`copilot/plans.py`), never listed into the conversation (PIP-AGENT-PLAN §2a).

The schemas are strict-shaped (every property listed in `required`, "optional" spelled as
nullable), because the admin realm offers `leads_search` and `calls_recent` as flat strict
tools; the area surface fills an omitted nullable member with null (`areas._with_nulls`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final, get_args

from pydantic import ValidationError

from apps.api.crm.models import CALL_STATUSES
from apps.api.crm.schemas import CallLensIn, LeadLensIn, LeadStatus

_OUTCOMES: Final = [
    "call_back_booked",
    "needs_you",
    "answered",
    "transferred",
    "hung_up_early",
    "missed",
]


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


_DAY: Final = _nullable({"type": "string", "description": "YYYY-MM-DD, India time"})
_FOLLOW_UP: Final = _nullable({"type": "string", "enum": ["done", "not_done"]})

#: The leads lens, as the model sees it.
LEAD_LENS_SCHEMA: Final[dict[str, Any]] = _nullable(
    {
        "type": "object",
        "description": (
            "Which leads; all optional; India days, inclusive; "
            "last_*, direction, follow_up: the latest call."
        ),
        "properties": {
            "status": _nullable({"type": "string", "enum": list(get_args(LeadStatus))}),
            "search": _nullable({"type": "string"}),
            "created_from": _DAY,
            "created_to": _DAY,
            "last_call_from": _DAY,
            "last_call_to": _DAY,
            "last_outcome": _nullable({"type": "string", "enum": _OUTCOMES}),
            "direction": _nullable({"type": "string", "enum": ["inbound", "outbound"]}),
            "test_calls": _nullable({"type": "boolean"}),
            "callback_open": _nullable({"type": "boolean"}),
            "follow_up": _FOLLOW_UP,
            "agent_id": _nullable({"type": "string"}),
            "assigned_to": _nullable({"type": "string"}),
            "campaign_id": _nullable({"type": "string"}),
            "captured": _nullable(
                {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "op": {"type": "string", "enum": ["equals", "contains"]},
                            "value": {"type": "string"},
                        },
                        "required": ["key", "op", "value"],
                        "additionalProperties": False,
                    },
                }
            ),
        },
        "required": [
            "status",
            "search",
            "created_from",
            "created_to",
            "last_call_from",
            "last_call_to",
            "last_outcome",
            "direction",
            "test_calls",
            "callback_open",
            "follow_up",
            "agent_id",
            "assigned_to",
            "campaign_id",
            "captured",
        ],
        "additionalProperties": False,
    }
)

#: The calls lens, as the model sees it.
CALL_LENS_SCHEMA: Final[dict[str, Any]] = _nullable(
    {
        "type": "object",
        "description": "Which calls; all optional; India days, inclusive.",
        "properties": {
            "status": _nullable({"type": "string", "enum": list(CALL_STATUSES)}),
            "outcome": _nullable({"type": "string", "enum": _OUTCOMES}),
            "direction": _nullable({"type": "string", "enum": ["inbound", "outbound"]}),
            "from_day": _DAY,
            "to_day": _DAY,
            "test_calls": _nullable({"type": "boolean"}),
            "follow_up": _FOLLOW_UP,
            "callback_open": _nullable({"type": "boolean"}),
            "agent_id": _nullable({"type": "string"}),
            "campaign_id": _nullable({"type": "string"}),
        },
        "required": [
            "status",
            "outcome",
            "direction",
            "from_day",
            "to_day",
            "test_calls",
            "follow_up",
            "callback_open",
            "agent_id",
            "campaign_id",
        ],
        "additionalProperties": False,
    }
)

#: `detail` on every lens read: a count and a few examples, or the full page.
DETAIL_SCHEMA: Final[dict[str, Any]] = _nullable({"type": "string", "enum": ["summary", "full"]})

#: How many examples a `summary` read shows.
SUMMARY_EXAMPLES: Final = 3


class LensArgumentError(ValueError):
    """A lens the model wrote that the lens model refuses; `reason` names fields only."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _set_members(raw: object) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise LensArgumentError("`lens` must be an object")
    return {key: value for key, value in raw.items() if value is not None}


def _refusal(exc: ValidationError) -> LensArgumentError:
    fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
    named = ", ".join(f"`lens.{field}`" for field in fields) or "`lens`"
    return LensArgumentError(f"{named} was missing or the wrong shape")


def lead_lens(raw: object, **shortcuts: Any) -> LeadLensIn:
    """The model's `lens` as the server's lead lens. `shortcuts` (a tool's own top-level
    `status`/`search`) apply under the lens's members."""
    members = {key: value for key, value in shortcuts.items() if value is not None}
    members |= _set_members(raw)
    try:
        return LeadLensIn.model_validate(members)
    except ValidationError as exc:
        raise _refusal(exc) from exc


def call_lens(raw: object, **shortcuts: Any) -> CallLensIn:
    members = {key: value for key, value in shortcuts.items() if value is not None}
    members |= _set_members(raw)
    try:
        return CallLensIn.model_validate(members)
    except ValidationError as exc:
        raise _refusal(exc) from exc


def handle(lens: LeadLensIn | CallLensIn) -> str:
    """The lens as the short JSON the model copies into an action's `lens`: set members only,
    defaults left out."""
    return json.dumps(
        lens.model_dump(mode="json", exclude_defaults=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = [
    "CALL_LENS_SCHEMA",
    "DETAIL_SCHEMA",
    "LEAD_LENS_SCHEMA",
    "SUMMARY_EXAMPLES",
    "LensArgumentError",
    "call_lens",
    "handle",
    "lead_lens",
]
