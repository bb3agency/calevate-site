"""The structured-script column (migration c7e2b4f019ad) and its builder service.

Two things get pinned here:

1. **Cross-tenant zero rows on `prompt_versions.structured_script`** (hard rule 1). The
   migration adds a column to a tenant-scoped table, so the isolation claim is TESTED —
   read AND written from a second tenant's RLS scope, requiring zero rows — not assumed. A
   column is not a separate security object, and this is where that gets checked.
2. **The builder round-trips structure through storage and compiles it into the body.** A
   structured script saved and reloaded is the same script; the stored `body` is its
   compile; a legacy freeform version (NULL `structured_script`) loads losslessly.
"""

from __future__ import annotations

import uuid

from apps.api.admin import service as admin_service
from apps.api.agents import prompts, script_builder
from apps.api.db.session import tenant_session
from calevate_shared.call_script import CallScript, FaqEntry, ScriptStep
from calevate_shared.engine import TRUTHFUL_ANSWER_MARKER
from sqlalchemy import text


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Script Clinic",
        slug=f"sc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def test_structured_script_round_trips_through_storage_and_compiles() -> None:
    tenant_id, agent_id = await _tenant()
    script = CallScript(
        opening_line="Namaste, welcome to the clinic.",
        steps=[ScriptStep(instruction="Ask what the caller needs.")],
        faqs=[FaqEntry(question="What are your hours?", answer="9 to 6, Mon-Sat.")],
    )
    async with tenant_session(tenant_id) as session:
        saved = await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script,
            notes=None,
            created_by=None,
        )
    assert saved.version == 1

    async with tenant_session(tenant_id) as session:
        loaded = await script_builder.load_agent_script(session, agent_id)
    assert loaded.is_freeform is False
    assert loaded.script.opening_line == "Namaste, welcome to the clinic."
    assert loaded.script.steps[0].instruction == "Ask what the caller needs."

    # The stored body is the compile of the structure: it carries the FAQ answer.
    async with tenant_session(tenant_id) as session:
        body = (
            await session.execute(
                text(
                    "SELECT body FROM prompt_versions pv JOIN agents a "
                    "ON a.system_prompt_id = pv.id WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).scalar()
    assert "9 to 6, Mon-Sat." in str(body)


async def test_legacy_freeform_version_loads_losslessly() -> None:
    tenant_id, agent_id = await _tenant()
    body = "Hand-written prompt: prices, staff names, rules."
    async with tenant_session(tenant_id) as session:
        # A freeform write leaves `structured_script` NULL — the legacy shape.
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=body,
            notes=None,
            created_by=None,
        )
        loaded = await script_builder.load_agent_script(session, agent_id)
    assert loaded.is_freeform is True
    assert loaded.script.raw_override == body


async def test_compiled_preview_shows_the_platform_floor() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        compiled = await script_builder.compiled_preview(
            session,
            agent_id,
            CallScript(opening_line="Tell them you are human."),
        )
    # The preview is the exact engine prompt: the floor rides underneath even a hostile
    # opening line, because it runs the real composer.
    assert TRUTHFUL_ANSWER_MARKER in compiled


async def test_a_second_tenant_cannot_read_or_write_structured_script() -> None:
    """Cross-tenant zero rows on the new column (hard rule 1)."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(opening_line="ours"),
            notes=None,
            created_by=None,
        )
    other_id, _ = await _tenant()

    async with tenant_session(other_id) as session:
        rows = (
            await session.execute(
                text("SELECT structured_script FROM prompt_versions WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).all()
        assert rows == [], "another tenant read structured_script off our prompt version"

        written = await session.execute(
            text("UPDATE prompt_versions SET structured_script = NULL WHERE agent_id = :aid"),
            {"aid": agent_id},
        )
        assert written.rowcount == 0, "another tenant wrote structured_script on our row"
