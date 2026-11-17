"""The seeded receptionist reaches `live` (DEV-SETUP §2).

Every publish is refused for an account with no accepted agreements or an incomplete
business profile, so a seed that wrote neither left its agent in `draft` and the documented
"LIVE agent" never existed.
"""

from __future__ import annotations

import uuid

from apps.api.db.session import untenanted_session
from scripts import seed_dev
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist


async def _owner() -> uuid.UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text("INSERT INTO users (id, email, created_at, updated_at) VALUES (:i, :e, now(), now())"),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    return user_id


async def test_the_seeded_agent_is_published_live() -> None:
    owner_id = await _owner()
    created = await create_org_with_receptionist(
        name="Seed Publish Homes",
        slug=f"seedpub-{uuid.uuid4().hex[:8]}",
        vertical_template="custom",
        billing_email=None,
        created_by=None,
        owner_user_id=owner_id,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await seed_dev._ensure_prompt(tenant_id, agent_id)

    await seed_dev._ensure_business_profile(tenant_id)
    await seed_dev._ensure_business_profile(tenant_id)
    await seed_dev._accept_agreements(tenant_id, owner_id)
    await seed_dev._accept_agreements(tenant_id, owner_id)

    assert await seed_dev._publish(tenant_id, agent_id) == "live"
