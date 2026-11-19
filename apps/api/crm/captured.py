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

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal
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


#: Every agent's schema versions in the account, newest first, then the campaigns' and the
#: lines' own lists (D-1003), so a value one of them noted is labelled as it named it. RLS
#: scopes every branch to the tenant.
_ACCOUNT_VERSIONS_SQL: Final = (
    "SELECT fields FROM (SELECT fields, created_at AS at, 0 AS holder FROM extraction_schemas "
    "UNION ALL SELECT extraction_fields, updated_at, 1 FROM campaigns "
    "WHERE jsonb_array_length(extraction_fields) > 0 "
    "UNION ALL SELECT extraction_fields, updated_at, 2 FROM inbound_lines "
    "WHERE jsonb_array_length(extraction_fields) > 0) lists "
    "ORDER BY holder, at DESC LIMIT 500"
)


#: What each call's holder asks to note (D-1003): the campaign that placed it, else the line
#: that took it, when either has a list of its own. The same pick as the post-call
#: pipeline's `_load_call_context`, so a call is read back under the list it was captured with.
_HOLDER_FIELDS_SQL: Final = (
    "SELECT c.id, CASE WHEN jsonb_array_length(g.extraction_fields) > 0 THEN 'campaign' "
    "WHEN jsonb_array_length(l.extraction_fields) > 0 THEN 'line' END, "
    "CASE WHEN jsonb_array_length(g.extraction_fields) > 0 THEN g.id "
    "WHEN jsonb_array_length(l.extraction_fields) > 0 THEN l.id END, "
    "COALESCE(NULLIF(g.extraction_fields, '[]'::jsonb), "
    "NULLIF(l.extraction_fields, '[]'::jsonb)) FROM calls c "
    "LEFT JOIN campaigns g ON g.id = c.campaign_id "
    "LEFT JOIN inbound_lines l ON l.id = c.inbound_line_id "
    "WHERE c.id = ANY(:ids)"
)

HolderKind = Literal["campaign", "line"]


@dataclass(frozen=True, slots=True)
class CallHolder:
    """The campaign or line whose own list a call was captured under."""

    kind: HolderKind
    id: UUID
    fields: list[ExtractionField]


async def call_holders(session: AsyncSession, call_ids: list[UUID]) -> dict[UUID, CallHolder]:
    """Each call's holder, for the calls whose holder has a list of its own."""
    if not call_ids:
        return {}
    rows = (await session.execute(text(_HOLDER_FIELDS_SQL), {"ids": call_ids})).all()
    return {
        UUID(str(r[0])): CallHolder(
            kind="campaign" if r[1] == "campaign" else "line",
            id=UUID(str(r[2])),
            fields=business_only(r[3]),
        )
        for r in rows
        if r[3]
    }


async def holder_fields(
    session: AsyncSession, call_ids: list[UUID]
) -> dict[UUID, list[ExtractionField]]:
    """Each call's holder's own list, for the calls whose holder has one."""
    return {cid: holder.fields for cid, holder in (await call_holders(session, call_ids)).items()}


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
    holder: list[ExtractionField] | None = None,
) -> list[CapturedFieldOut]:
    """Every field of the capturing version (value or not), then any other captured value.

    `unlisted` is `call_extractions.unlisted`: a choice field with no value carries the
    caller's own words for what they asked (D-889). `holder` is the call's campaign's or
    line's own list (`holder_fields`): when there is one it is what the call captured, and
    the agent's versions only label values it does not list.

    RLS scopes the schema reads to the caller's tenant; an agent id from elsewhere reads as
    an agent with no schemas, and the values are still listed under their keys.
    """
    versions: list[tuple[int, list[ExtractionField]]] = []
    if agent_id is not None:
        rows = (await session.execute(text(_VERSIONS_SQL), {"aid": agent_id})).all()
        versions = [(int(r[0]), business_only(r[1] or [])) for r in rows]

    if holder:
        capturing = holder
        newest_keys = {f.key for f in holder}
    else:
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
            _with_choices(
                CapturedFieldOut(
                    key=field.key,
                    label=field.label,
                    type=field.type,
                    core=field.key in CORE_KEYS,
                    current=field.key in CORE_KEYS or field.key in newest_keys,
                    value=data.get(field.key),
                    unlisted=_said(field, data, unlisted),
                ),
                field,
            )
        )
    known: dict[str, ExtractionField] = {}
    for _version, fields in versions:  # newest first: the latest label for a key wins
        for field in fields:
            known.setdefault(field.key, field)
    # A value captured by ANOTHER of the account's agents (a lead that moved, or one first
    # met by a different agent) is labelled from that agent's fields before falling back to
    # the key, which reads to an owner as "Bhk size" (L3-11).
    orphans = {k for k, v in data.items() if v is not None and k not in listed and k not in known}
    if orphans:
        for row in (await session.execute(text(_ACCOUNT_VERSIONS_SQL))).all():
            for field in business_only(row[0] or []):
                if field.key in orphans:
                    known.setdefault(field.key, field)
    for key, value in data.items():
        if key in listed or value is None:
            continue
        earlier = known.get(key)
        out.append(
            _with_choices(
                CapturedFieldOut(
                    key=key,
                    label=earlier.label if earlier else _humanised(key),
                    type=earlier.type if earlier else "text",
                    core=False,
                    current=key in newest_keys,
                    value=value,
                ),
                earlier,
            )
        )
    return out


def _with_choices(out: CapturedFieldOut, field: ExtractionField | None) -> CapturedFieldOut:
    if field is not None and field.type == "enum":
        out._choices = tuple(field.enum_values or ())
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


def _header_key(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def with_list_columns(
    fields: list[CapturedFieldOut], *, columns: dict[str, Any] | None
) -> list[CapturedFieldOut]:
    """`fields` with an empty field filled from the campaign list row this call dialled
    (`campaign_contacts.custom`, D-905), marked `list`. A column matches a field whose key or
    label it spells, folded as `call_variable_key` folds a header ("Village Name" is
    `village_name`). The list already gave the agent that value (D-905's THIS CALL), so the
    call not saying it again is not a gap. A value the call captured is never replaced, and a
    cell that does not read cleanly as the field's type (`_list_value`) fills nothing: a
    number field showing "about ten" would claim a value no reading produced."""
    if not columns:
        return fields
    by_key: dict[str, str] = {}
    for header, raw in columns.items():
        value = " ".join(str(raw).split()) if raw is not None else ""
        key = _header_key(str(header))
        if key and value:
            by_key.setdefault(key, value)
    if not by_key:
        return fields
    out: list[CapturedFieldOut] = []
    for field in fields:
        known = by_key.get(_header_key(field.key)) or by_key.get(_header_key(field.label))
        if known and field.value is None and field.unlisted is None:
            value = _list_value(field, known)
            if value is not None:
                field = field.model_copy(update={"value": value, "source": "list"})
        out.append(field)
    return out


_LIST_NUMBER_RE: Final = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_LIST_YES_NO: Final[dict[str, bool]] = {
    "yes": True,
    "true": True,
    "1": True,
    "no": False,
    "false": False,
    "0": False,
}
_LIST_ISO_DATE_RE: Final = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_LIST_DMY_DATE_RE: Final = re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})")


def _list_value(field: CapturedFieldOut, cell: str) -> Any:
    """A list cell as a value of the field's type, in the shape a reading stores it, or None
    when it does not read cleanly as one. Stricter than `coerce_value`, which reads a model's
    answer ("about 5000 rupees" is 5000): a list cell is the business's own data, so only a
    value with one plain reading is taken. Dates are ISO or DD/MM/YYYY, the day-first order
    Indian lists use."""
    if field.type == "text":
        return cell
    if field.type == "number":
        if not _LIST_NUMBER_RE.fullmatch(cell):
            return None
        return float(cell) if "." in cell else int(cell)
    if field.type == "bool":
        return _LIST_YES_NO.get(cell.lower())
    if field.type == "enum":
        return next((c for c in field._choices if c.strip().lower() == cell.lower()), None)
    iso = _LIST_ISO_DATE_RE.fullmatch(cell)
    dmy = _LIST_DMY_DATE_RE.fullmatch(cell)
    try:
        if iso:
            return date(int(iso[1]), int(iso[2]), int(iso[3])).isoformat()
        if dmy:
            return date(int(dmy[3]), int(dmy[2]), int(dmy[1])).isoformat()
    except ValueError:
        return None
    return None


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


async def lead_holder_fields(session: AsyncSession, lead_id: UUID) -> list[ExtractionField] | None:
    """The own list of the holder of the lead's latest call, when it has one."""
    call_id = (
        await session.execute(
            text("SELECT last_call_id FROM leads WHERE id = :lid AND deleted_at IS NULL"),
            {"lid": lead_id},
        )
    ).scalar()
    if call_id is None:
        return None
    cid = UUID(str(call_id))
    return (await holder_fields(session, [cid])).get(cid)


__all__ = [
    "CallHolder",
    "HolderKind",
    "call_holders",
    "captured_fields",
    "holder_fields",
    "is_name_field",
    "lead_holder_fields",
    "lead_unlisted",
    "unclear_fields",
    "with_known_name",
    "with_list_columns",
]
