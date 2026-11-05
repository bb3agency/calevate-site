"""A call's or a lead's captured details, each under the name it was captured with.

`leads.data` and `call_extractions.data` are keyed by field KEY, and a key's label lives in
the schema version that captured it. A screen that labels them from the agent's CURRENT
fields loses every value whose field was since renamed, removed or replaced — a business
moved from one type's fields to another's would see its old answers vanish. So the labels
come from the version the values were captured under, then from any earlier version of the
same agent that knew the key, and only then from the key itself.

The core every lead carries (`calevate_shared.lead_fields`) is always listed first, so
"what they want" is always present and always in the same place.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import CORE_KEYS, business_only, with_core
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.crm.schemas import CapturedFieldOut, UnclearFieldOut, UnclearKind
from apps.api.tenancy.core_labels import core_labels

_VERSIONS_SQL: Final = (
    "SELECT version, fields FROM extraction_schemas WHERE agent_id = :aid "
    "ORDER BY version DESC LIMIT 200"
)


def _humanised(key: str) -> str:
    return key.replace("_", " ").strip().capitalize() or key


def _said(
    field: ExtractionField, data: dict[str, Any], unlisted: dict[str, Any] | None
) -> str | None:
    if field.type != "enum" or data.get(field.key) is not None or not unlisted:
        return None
    said = unlisted.get(field.key)
    return said if isinstance(said, str) and said else None


async def captured_fields(
    session: AsyncSession,
    *,
    agent_id: UUID | None,
    schema_version: int | None,
    data: dict[str, Any],
    unlisted: dict[str, Any] | None = None,
) -> list[CapturedFieldOut]:
    """Every field of the capturing version (value or not), then any other captured value.

    `unlisted` is `call_extractions.unlisted`: a choice field with no value carries the
    caller's own words for what they asked (D-889).

    RLS scopes the schema reads to the caller's tenant; an agent id from elsewhere reads as
    an agent with no schemas, and the values are still listed under their keys.
    """
    versions: list[tuple[int, list[ExtractionField]]] = []
    if agent_id is not None:
        rows = (await session.execute(text(_VERSIONS_SQL), {"aid": agent_id})).all()
        versions = [(int(r[0]), business_only(r[1] or [])) for r in rows]

    newest_keys = {f.key for f in versions[0][1]} if versions else set()
    capturing = next(
        (fields for version, fields in versions if version == schema_version),
        versions[0][1] if versions else [],
    )
    out: list[CapturedFieldOut] = []
    listed: set[str] = set()
    for field in with_core(capturing, await core_labels(session)):
        listed.add(field.key)
        out.append(
            CapturedFieldOut(
                key=field.key,
                label=field.label,
                type=field.type,
                core=field.key in CORE_KEYS,
                current=field.key in CORE_KEYS or field.key in newest_keys,
                value=data.get(field.key),
                unlisted=_said(field, data, unlisted),
            )
        )
    known: dict[str, ExtractionField] = {}
    for _version, fields in versions:  # newest first: the latest label for a key wins
        for field in fields:
            known.setdefault(field.key, field)
    for key, value in data.items():
        if key in listed or value is None:
            continue
        earlier = known.get(key)
        out.append(
            CapturedFieldOut(
                key=key,
                label=earlier.label if earlier else _humanised(key),
                type=earlier.type if earlier else "text",
                core=False,
                current=key in newest_keys,
                value=value,
            )
        )
    return out


#: The keys and labels that mean "the person's name". A name the call did not capture is
#: filled from the campaign list or the lead (D-905 carries the list's name onto the dial),
#: because "Caller Name: not mentioned" beside a list that named the person reads as a gap
#: the business already filled (4 Nov 2026 call review).
_NAME_KEYS: Final = frozenset(
    {"name", "caller_name", "customer_name", "contact_name", "full_name", "person_name"}
)
_NAME_LABELS: Final = frozenset(
    {"name", "caller name", "customer name", "contact name", "full name", "your name"}
)


def is_name_field(field: CapturedFieldOut) -> bool:
    label = " ".join(field.label.lower().split())
    return field.type == "text" and (field.key in _NAME_KEYS or label in _NAME_LABELS)


def with_known_name(
    fields: list[CapturedFieldOut], *, list_name: str | None, lead_name: str | None
) -> list[CapturedFieldOut]:
    """`fields` with an empty name field filled from the campaign list, else the lead, and
    marked with where it came from. A name the call captured is never replaced."""
    known = next(
        (
            (name.strip(), source)
            for name, source in ((list_name, "list"), (lead_name, "lead"))
            if name and name.strip()
        ),
        None,
    )
    if known is None:
        return fields
    return [
        field.model_copy(update={"value": known[0], "source": known[1]})
        if field.value is None and field.unlisted is None and is_name_field(field)
        else field
        for field in fields
    ]


#: Why a captured detail is unclear, in the owner's words, from the validator's message.
#: Matched on the validator's own fixed wording (`calevate_shared.extraction.coerce_value`),
#: never shown verbatim: those messages quote the value, which can be anything the caller said.
_UNCLEAR_WORDS: Final[dict[str, str]] = {
    "not_a_choice": "What they said is not one of this detail's choices.",
    "not_yes_no": "Their answer was not a clear yes or no.",
    "not_a_number": "No number could be read from their answer.",
    "phone_in_wrong_place": "A phone number was said here, so it was left out.",
    "too_long": "The answer was too long to be one detail.",
    "unreadable": "Their answer could not be read.",
}
_UNCLEAR_MARKERS: Final[tuple[tuple[str, UnclearKind], ...]] = (
    ("is not one of", "not_a_choice"),
    ("could not read yes/no", "not_yes_no"),
    ("could not read a number", "not_a_number"),
    ("expected a number", "not_a_number"),
    ("does not hold phone numbers", "phone_in_wrong_place"),
    ("is a transcript, not a value", "too_long"),
)
#: The validator's wording for a required detail nobody gave: not unclear, only unsaid, and
#: the screen already lists it under "Not mentioned".
_NOT_SAID: Final = "is required but was not captured"


def unclear_fields(errors: Any, fields: list[CapturedFieldOut]) -> list[UnclearFieldOut]:
    """Each captured detail the reading could not use, with the owner's reason.

    `errors` is `call_extractions.errors`. A required detail that was simply not said is left
    out (it is "Not mentioned"), and so is a choice the caller answered outside the list
    (D-889: it shows the caller's words). The provider failing (`_model`) is no one field's
    problem and is not listed here.
    """
    if not isinstance(errors, dict):
        return []
    labels = {field.key: field for field in fields}
    out: list[UnclearFieldOut] = []
    for key, message in errors.items():
        if key.startswith("_") or not isinstance(message, str) or _NOT_SAID in message:
            continue
        field = labels.get(key)
        if field is not None and field.unlisted:
            continue
        kind: UnclearKind = next(
            (kind for marker, kind in _UNCLEAR_MARKERS if marker in message), "unreadable"
        )
        out.append(
            UnclearFieldOut(
                key=key,
                label=field.label if field is not None else _humanised(key),
                kind=kind,
                reason=_UNCLEAR_WORDS[kind],
            )
        )
    return out


async def lead_unlisted(session: AsyncSession, lead_id: UUID) -> dict[str, str]:
    """The caller's own words for each choice field, newest call first, across the lead's
    calls: what `leads.data` cannot hold because no choice fitted (D-889)."""
    rows = (
        await session.execute(
            text(
                "SELECT ce.unlisted FROM call_extractions ce "
                "JOIN calls c ON c.id = ce.call_id AND c.tenant_id = ce.tenant_id "
                "WHERE c.lead_id = :lid AND ce.unlisted IS NOT NULL "
                "ORDER BY c.created_at DESC LIMIT 20"
            ),
            {"lid": lead_id},
        )
    ).scalars()
    out: dict[str, str] = {}
    for said in rows:
        for key, words in (said or {}).items():
            if isinstance(words, str) and words:
                out.setdefault(key, words)
    return out


__all__ = [
    "captured_fields",
    "is_name_field",
    "lead_unlisted",
    "unclear_fields",
    "with_known_name",
]
