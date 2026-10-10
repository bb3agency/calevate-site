"""'What it knows': the business's facts (pinned first) and its documents, photos and
web pages. Longer notes typed before the teach box keep their own list and states
(`GET /v1/kb/sources`, kind `text`). All of it is shared by every agent of the account
(D-689). The list is bounded by its sources' own ceilings, so the screen searches it in the
browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.kb import uploads
from apps.api.teach import facts as fact_store

ItemKind = Literal["document", "photo", "page"]
ItemState = Literal["live", "getting_ready", "in_review", "needs_attention"]

_STUCK = ("conversion_unavailable", "conversion_failed", "error")


@dataclass(frozen=True, slots=True)
class KnownItem:
    id: UUID
    kind: ItemKind
    name: str
    state: ItemState
    url: str | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class Knows:
    facts: list[fact_store.Fact]
    facts_state: fact_store.FactsState
    items: list[KnownItem]


def _upload_state(row: dict[str, object]) -> ItemState:
    if row["is_live"]:
        return "live"
    if row["ingest_status"] in _STUCK or row["review_state"] == "rejected":
        return "needs_attention"
    if row["review_state"] == "pending_approval":
        return "in_review"
    return "getting_ready"


async def what_it_knows(session: AsyncSession) -> Knows:
    items: list[KnownItem] = []
    for row in await uploads.list_uploads(session):
        if row["review_state"] == "archived":
            continue
        kind: ItemKind = (
            "page"
            if row["source_kind"] == "url"
            else "photo"
            if row["source_kind"] == "image"
            else "document"
        )
        items.append(
            KnownItem(
                id=row["id"],
                kind=kind,
                name=str(row["name"]),
                state=_upload_state(row),
                url=row["source_url"] if kind == "page" else None,
                updated_at=row["updated_at"],
            )
        )
    items.sort(
        key=lambda item: item.updated_at.timestamp() if item.updated_at else 0.0, reverse=True
    )
    return Knows(
        facts=await fact_store.list_facts(session),
        facts_state=await fact_store.facts_state(session),
        items=items,
    )


__all__ = ["ItemKind", "ItemState", "KnownItem", "Knows", "what_it_knows"]
