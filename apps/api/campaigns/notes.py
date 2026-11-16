"""What a campaign's calls note (D-1003, "What it notes" per campaign).

A campaign may keep its own list of details to write down from each call
(`campaigns.extraction_fields`, the extraction-schema field shape). Empty means its agent's
list, so every campaign made before this notes exactly what it did. The list is read in two
places, and both read it from here or from the same column:

* the campaign's engine agent asks for these details (`script_builder.campaign_collect_fields`
  compiles them into its script);
* the post-call pipeline notes them (`workers/pipeline._load_call_context` picks the call's
  holder's list: the campaign's, else the line's, else the agent's).

The list is held to the same rules as an agent's (`agents/extraction_routes._validate_fields`)
and saved whole under a compare-and-set on the digest of the list the editor was showing, so
two people saving at once cannot drop each other's details.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import business_only
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.extraction_routes import _validate_fields
from apps.api.core.errors import ProblemError


@dataclass(frozen=True, slots=True)
class CampaignNotes:
    campaign_id: UUID
    agent_id: UUID
    agent_name: str
    #: The campaign's own list; empty means it notes what its agent notes.
    fields: tuple[ExtractionField, ...]
    #: Its agent's list, which its calls note while `fields` is empty.
    agent_fields: tuple[ExtractionField, ...]
    #: The digest of `fields` as stored, sent back with a save.
    digest: str


def digest_of(raw: Any) -> str:
    return hashlib.sha256(json.dumps(raw or [], sort_keys=True).encode()).hexdigest()


def _fields(raw: Any) -> tuple[ExtractionField, ...]:
    return tuple(business_only([ExtractionField.model_validate(f) for f in (raw or [])]))


async def read_notes(session: AsyncSession, campaign_id: UUID) -> CampaignNotes:
    row = (
        await session.execute(
            text(
                "SELECT g.agent_id, a.name, g.extraction_fields, es.fields FROM campaigns g "
                "JOIN agents a ON a.id = g.agent_id "
                "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                "WHERE g.id = :cid AND g.archived_at IS NULL"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return CampaignNotes(
        campaign_id=campaign_id,
        agent_id=UUID(str(row[0])),
        agent_name=str(row[1]),
        fields=_fields(row[2]),
        agent_fields=_fields(row[3]),
        digest=digest_of(row[2]),
    )


async def save_notes(
    session: AsyncSession,
    campaign_id: UUID,
    fields: list[ExtractionField],
    *,
    expected_digest: str | None,
) -> bool:
    """Replace the campaign's list, or clear it to follow the agent's. Refused when the list
    changed since the editor read it (`expected_digest`). True when something changed."""
    own = business_only(fields)
    _validate_fields(own)
    current = (
        await session.execute(
            text(
                "SELECT extraction_fields FROM campaigns WHERE id = :cid "
                "AND archived_at IS NULL FOR UPDATE"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if current is None:
        raise ProblemError.not_found("Campaign")
    stored = [field.model_dump(mode="json", exclude_none=True) for field in own]
    # Asked before the compare-and-set: a list that already holds exactly what is sent loses
    # nobody's change, and it is what a Save again sends after a save whose put-live was
    # refused, from an editor still holding the digest of the list before that save.
    if digest_of(stored) == digest_of(current[0]):
        return False
    if expected_digest is not None and digest_of(current[0]) != expected_digest:
        raise ProblemError.conflict(
            "campaign_notes_changed_elsewhere",
            "Someone else changed what this campaign notes while you were editing.",
            remediation="Load the current list, then make your change again.",
        )
    await session.execute(
        text(
            "UPDATE campaigns SET extraction_fields = CAST(:f AS jsonb), updated_at = now() "
            "WHERE id = :cid"
        ),
        {"f": json.dumps(stored), "cid": campaign_id},
    )
    return True


__all__ = ["CampaignNotes", "digest_of", "read_notes", "save_notes"]
