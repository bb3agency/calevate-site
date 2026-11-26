"""A campaign to write a script for, and its helpers, shared by the holder-writer tests.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.script_lint import LintContext
from apps.api.campaigns import workspace
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from calevate_shared.call_script import CallScript, ConversationStage
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.rls

LINT = LintContext(promo=False)
MAIN_TASK = "Get every past customer to install the new app and open it once."
OPENING = "Hello, this is Asha from Sunrise Homes. Is now a good time?"
THREE_QUESTIONS = "What is your name? Which phone do you use? When can you install it?"
ONE_QUESTION = "Which phone do you use?"


def _stage(sid: str, line: str) -> ConversationStage:
    return ConversationStage(id=sid, name=sid.title(), instruction="Help them.", sounds_like=line)


#: The step that asks what every job's calls ask (`script_builder.job_details`): the core
#: name, call-back time and other number, under the platform's names for them.
ASKS_DETAILS = ConversationStage(
    id="details",
    name="Details",
    instruction="Ask their name if it is not known.",
    sounds_like="Is this the best number to reach you on?",
    collect=["Name", "Preferred time", "Other number"],
)


def _script(*lines: str) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=OPENING,
        stages=[
            *(_stage(f"s{i}", line) for i, line in enumerate(lines)),
            ASKS_DETAILS,
            _stage("close", "Thank you."),
        ],
    )


async def _campaign(script: CallScript | None = None) -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Sunrise Homes",
        slug=f"cpw-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, campaign_id = UUID(str(created["id"])), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, script) "
                "VALUES (:id, :t, :a, 'Install the app', 'service', CAST(:s AS jsonb))"
            ),
            {
                "id": campaign_id,
                "t": tenant_id,
                "a": created["agent_id"],
                "s": None if script is None else script.model_dump_json(),
            },
        )
        await workspace.save_main_task(session, campaign_id, MAIN_TASK)
        # A live note in What your agents know, picked by the campaign, and one it did not
        # pick, which the writer must not read.
        picked, other = uuid7(), uuid7()
        for source_id, name, words in (
            (picked, "Offer", "Tell them the first month is free."),
            (other, "Old offer", "Tell them the first year is free."),
        ):
            await session.execute(
                text(
                    "INSERT INTO kb_sources (id, tenant_id, kind, name, status, version, "
                    "is_active, created_at, updated_at) VALUES (:i, :t, 'text', :n, "
                    "'approved', 1, true, now(), now())"
                ),
                {"i": source_id, "t": tenant_id, "n": name},
            )
            await session.execute(
                text(
                    "INSERT INTO kb_documents (id, tenant_id, source_id, idx, content, "
                    "created_at, updated_at) VALUES (:id, :t, :s, 0, :w, now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "s": source_id, "w": words},
            )
        await workspace.set_sources(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            kb_source_ids=[picked],
            created_by=None,
        )
    return tenant_id, campaign_id


def _answer(script: CallScript, disclosure: str | None = None) -> Any:
    return SimpleNamespace(
        script=script,
        capability=SimpleNamespace(disclosure=disclosure),
        usage=None,
        model="gemini-2.5-flash-lite",
        earlier=(),
        left_out=(),
    )
