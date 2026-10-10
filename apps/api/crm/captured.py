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

from apps.api.crm.schemas import CapturedFieldOut

_VERSIONS_SQL: Final = (
    "SELECT version, fields FROM extraction_schemas WHERE agent_id = :aid "
    "ORDER BY version DESC LIMIT 200"
)


def _humanised(key: str) -> str:
    return key.replace("_", " ").strip().capitalize() or key


async def captured_fields(
    session: AsyncSession,
    *,
    agent_id: UUID | None,
    schema_version: int | None,
    data: dict[str, Any],
) -> list[CapturedFieldOut]:
    """Every field of the capturing version (value or not), then any other captured value.

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
    for field in with_core(capturing):
        listed.add(field.key)
        out.append(
            CapturedFieldOut(
                key=field.key,
                label=field.label,
                type=field.type,
                core=field.key in CORE_KEYS,
                current=field.key in CORE_KEYS or field.key in newest_keys,
                value=data.get(field.key),
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


__all__ = ["captured_fields"]
