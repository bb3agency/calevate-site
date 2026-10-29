"""A campaign contact's own values on the calls placed for it (D-905).

The client's list carries columns beside the phone and the name (`campaign_contacts.custom`):
a village, a crop, a registration number. They ride every dial placed for that person as the
call's `contact_details` (`agents.service.dispatch_call`), on the campaign's own dial and on a
call-back booked from one of its calls, which also belongs to the campaign's results. A dial
for a known lead with no list row carries the lead's own stored details the same way
(`lead_details`, D-940).

Client data about a person: never logged (hard rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from calevate_shared.engine import PLATFORM_CALL_VARIABLES, call_variable_key
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.crm.captured import captured_fields


def contact_details_of(custom: Any) -> dict[str, str]:
    """A stored `campaign_contacts.custom` as a dial's `contact_details`: filled cells only,
    as text, headers as the client wrote them."""
    if not isinstance(custom, dict):
        return {}
    return {
        str(header): str(value)
        for header, value in custom.items()
        if value is not None and str(value).strip()
    }


@dataclass(frozen=True, slots=True)
class CallOrigin:
    """Who a call-back is for, from the call it follows."""

    #: The campaign the earlier call belonged to, or None for a call outside any campaign.
    campaign_id: UUID | None = None
    #: The person's name: the list's, else the lead's.
    name: str | None = None
    details: dict[str, str] = field(default_factory=dict)


async def call_origin(
    session: AsyncSession, *, source_call_id: UUID | None, lead_id: UUID | None, phone_e164: str
) -> CallOrigin:
    """The campaign, contact row and name a call-back to `phone_e164` inherits.

    The contact is the campaign's row for the same number (a campaign holds a number once,
    `ON CONFLICT (campaign_id, phone_e164)`), which is how the campaign's opt-out list joins
    a call to its contact too (`campaigns/results.opt_outs`). A call-back of a call-back
    follows the chain for free: the first call-back's own call carries the campaign.
    """
    row = (
        await session.execute(
            text(
                "SELECT k.campaign_id, cc.name, cc.custom, "
                "  (SELECT l.name FROM leads l WHERE l.id = :lid AND l.deleted_at IS NULL) "
                "FROM (SELECT CAST(:call AS uuid) AS id) s "
                "LEFT JOIN calls k ON k.id = s.id "
                "LEFT JOIN campaign_contacts cc ON cc.campaign_id = k.campaign_id "
                "  AND cc.phone_e164 = :phone"
            ),
            {"call": source_call_id, "lid": lead_id, "phone": phone_e164},
        )
    ).one()
    campaign_id, contact_name, custom, lead_name = row
    name = (contact_name or "").strip() or (lead_name or "").strip() or None
    return CallOrigin(
        campaign_id=UUID(str(campaign_id)) if campaign_id else None,
        name=name,
        details=contact_details_of(custom),
    )


#: Lead fields a dial does not carry as details: the name already rides the dial as the
#: person's name, and a second phone number is no detail the agent needs to read out (data
#: minimisation; the number dialled is the call's own).
_NOT_DETAILS: Final = frozenset({"name", "other_number"})


def _detail_value(value: object) -> str | None:
    """A stored lead value as one detail: text, a number or a yes/no. A nested value (our
    own provenance record of where the lead came from) is not a detail."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str | int | float):
        return str(value)
    return None


async def lead_details(session: AsyncSession, *, lead_id: UUID) -> dict[str, str]:
    """A lead's stored details (`leads.data`: the fields a form or webhook sent and the ones
    its calls captured) as a dial's `contact_details`, each under its field's label, in the
    order the lead's screen lists them. Read on the dialling session, so a lead inserted in
    the same transaction (`ingest/service`) is seen. Never synced into the engine's own
    contact store: the details travel with each call and nowhere else."""
    row = (
        await session.execute(
            text(
                "SELECT agent_id, data, schema_version FROM leads "
                "WHERE id = :lid AND deleted_at IS NULL"
            ),
            {"lid": lead_id},
        )
    ).first()
    if row is None or not isinstance(row[1], dict):
        return {}
    fields = await captured_fields(
        session, agent_id=row[0], schema_version=row[2], data=dict(row[1])
    )
    details: dict[str, object] = {}
    for captured in fields:
        value = _detail_value(captured.value)
        if captured.key not in _NOT_DETAILS and value is not None:
            details.setdefault(captured.label, value)
    return contact_details_of(details)


#: How many list columns the script builder offers; a campaign holds at most ten per row.
MAX_LIST_COLUMNS = 30


async def list_columns(session: AsyncSession, *, agent_id: UUID) -> list[tuple[str, str]]:
    """The `{{variable}}` names this agent's campaign lists carry, with the header each came
    from, for the script builder to offer beside the caller's name. Headers with no Latin
    letter have no variable name and are left out (they still reach the call's details)."""
    headers = (
        await session.execute(
            text(
                "SELECT h FROM (SELECT DISTINCT jsonb_object_keys(cc.custom) AS h "
                "  FROM campaign_contacts cc JOIN campaigns c ON c.id = cc.campaign_id "
                "  WHERE c.agent_id = :aid AND jsonb_typeof(cc.custom) = 'object') s "
                "ORDER BY h LIMIT :n"
            ),
            {"aid": agent_id, "n": MAX_LIST_COLUMNS},
        )
    ).scalars()
    out: dict[str, str] = {}
    for header in headers:
        key = call_variable_key(str(header))
        if key is not None and key not in PLATFORM_CALL_VARIABLES:
            out.setdefault(key, str(header))
    return list(out.items())


__all__ = [
    "MAX_LIST_COLUMNS",
    "CallOrigin",
    "call_origin",
    "contact_details_of",
    "lead_details",
    "list_columns",
]
