"""The business types (verticals), read from `verticals.json`: the one list.

Every reader goes through this module: the admin and signup validation, the business-type
suggestion, the lead-detail starting sets, the ready-made agents' words, the cross-call memory
refusal and the business-types endpoint the web pickers read. Adding a type is therefore an
edit to the data file, not to code; the file's own `about` says what each entry holds.

A request names a type as a plain string validated against the loaded set
(`BusinessTypeKey`), not a `Literal`: a `Literal` would put the list back into code and into
the OpenAPI schema, so adding a type would again mean a code change and a regenerated web
client. An unknown or absent type reads as `CUSTOM` wherever a type is looked up (`of`),
never as any named trade.

The file is checked at import, so a malformed entry fails the build rather than a request.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from types import MappingProxyType
from typing import Annotated, Any, Final

from pydantic import AfterValidator, Field

from calevate_shared.extraction import ExtractionField

#: The type a business that fits no other runs as. It must be in the file.
CUSTOM: Final = "custom"

#: The words a ready-made agent of the type uses (`apps/api/agents/starters.Trade`).
STARTER_KEYS: Final = (
    "receptionist_name",
    "caller_name",
    "topics",
    "booking",
    "capture",
    "caution",
)

#: The admin console's per-type placeholders, in the spelling of the account's generated
#: placeholders (`tenancy/business_copy.Placeholders`) plus the two only account creation
#: shows.
EXAMPLE_KEYS: Final = (
    "org_name",
    "org_slug",
    "knowledge_title",
    "knowledge_answer",
    "extraction_reason",
    "script_brief",
    "extraction_label",
    "extraction_options",
    "end_call_rules",
    "lead_search",
    "booking_job_title",
    "booking_job_line",
)

_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass(frozen=True, slots=True)
class Vertical:
    key: str
    label: str
    hint: str
    #: Gives health or medical care: cross-call memory is refused (D-507(b)).
    health: bool
    #: The lead details its agents start with, as `ExtractionField` dicts, notes removed.
    fields: tuple[Mapping[str, Any], ...]
    starter: Mapping[str, str]
    #: Empty when the file gives none.
    examples: Mapping[str, str]

    def field_dicts(self) -> list[dict[str, Any]]:
        """The starting fields as fresh dicts, safe for a caller to change."""
        return [copy.deepcopy(dict(f)) for f in self.fields]


def _vertical(raw: Mapping[str, Any]) -> Vertical:
    key = str(raw["key"])
    if not _KEY.fullmatch(key):
        raise ValueError(f"verticals.json: bad key {key!r}")
    label, hint = str(raw.get("label", "")).strip(), str(raw.get("hint", "")).strip()
    if not label or not hint:
        raise ValueError(f"verticals.json: {key} needs a label and a hint")
    health = raw.get("health")
    if not isinstance(health, bool):
        raise ValueError(f"verticals.json: {key}.health must be true or false")
    fields = tuple(
        MappingProxyType({k: v for k, v in f.items() if k != "note"}) for f in raw["fields"]
    )
    for f in fields:
        ExtractionField.model_validate(dict(f))
    if len({f["key"] for f in fields}) != len(fields):
        raise ValueError(f"verticals.json: {key} repeats a field key")
    starter = raw["starter"]
    if set(starter) != set(STARTER_KEYS) or not all(str(v).strip() for v in starter.values()):
        raise ValueError(f"verticals.json: {key}.starter needs exactly {STARTER_KEYS}")
    examples = raw.get("examples") or {}
    if not set(examples) <= set(EXAMPLE_KEYS):
        raise ValueError(f"verticals.json: {key}.examples has keys outside {EXAMPLE_KEYS}")
    return Vertical(
        key=key,
        label=label,
        hint=hint,
        health=health,
        fields=fields,
        starter=MappingProxyType({k: str(starter[k]) for k in STARTER_KEYS}),
        examples=MappingProxyType({k: str(v) for k, v in examples.items()}),
    )


@cache
def _loaded() -> Mapping[str, Vertical]:
    raw = json.loads(
        resources.files(__package__).joinpath("verticals.json").read_text(encoding="utf-8")
    )
    rows = [_vertical(row) for row in raw["types"]]
    by_key = {row.key: row for row in rows}
    if len(by_key) != len(rows):
        raise ValueError("verticals.json: a key appears twice")
    if CUSTOM not in by_key:
        raise ValueError(f"verticals.json: {CUSTOM!r} must be present")
    return MappingProxyType(by_key)


def all_types() -> tuple[Vertical, ...]:
    """Every type, in picker order."""
    return tuple(_loaded().values())


def all_keys() -> tuple[str, ...]:
    """Every type's key, in picker order."""
    return tuple(_loaded())


def is_known(key: str | None) -> bool:
    return key is not None and key in _loaded()


def get(key: str | None) -> Vertical | None:
    return _loaded().get(key) if key is not None else None


def of(key: str | None) -> Vertical:
    """The type's row, falling back to `CUSTOM` for an unknown or absent one."""
    return get(key) or _loaded()[CUSTOM]


def labels() -> Mapping[str, str]:
    """key -> label, in picker order."""
    return MappingProxyType({row.key: row.label for row in all_types()})


def label_of(key: str | None) -> str:
    """How a stored type reads; an unknown or absent one reads as `CUSTOM`'s label."""
    return of(key).label


def health_keys() -> frozenset[str]:
    """The types that give health or medical care."""
    return frozenset(row.key for row in all_types() if row.health)


def templates() -> Mapping[str, list[dict[str, Any]]]:
    """key -> starting lead fields, for the types that have their own (not `CUSTOM`, nor any
    type whose fields are drafted by AI)."""
    return MappingProxyType({row.key: row.field_dicts() for row in all_types() if row.fields})


def _known(value: str) -> str:
    if not is_known(value):
        raise ValueError(f"unknown business type; one of: {', '.join(all_keys())}")
    return value


#: A business type as a request names it: any key in the file.
BusinessTypeKey = Annotated[str, Field(min_length=1, max_length=40), AfterValidator(_known)]

# Checked at import: a malformed file fails the build, not a request.
_loaded()


__all__ = [
    "CUSTOM",
    "EXAMPLE_KEYS",
    "STARTER_KEYS",
    "BusinessTypeKey",
    "Vertical",
    "all_keys",
    "all_types",
    "get",
    "health_keys",
    "is_known",
    "label_of",
    "labels",
    "of",
    "templates",
]
