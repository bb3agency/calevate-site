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

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts, script_builder, t0
from apps.api.agents.t0_block import T0_HEADER
from apps.api.core.errors import ProblemError
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
    assert TRUTHFUL_ANSWER_MARKER in compiled.compiled
    assert compiled.instructions_chars == len(compiled.compiled)


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


# --- the builder and the agent page read one saved script --------------------------------


async def _save(tenant_id: uuid.UUID, agent_id: uuid.UUID, script: CallScript, **check: object):
    async with tenant_session(tenant_id) as session:
        return await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script,
            notes=None,
            created_by=None,
            **check,  # type: ignore[arg-type]
        )


async def test_a_save_from_an_older_copy_is_refused_rather_than_written_over_a_newer_one() -> None:
    """The founder's mismatch: a builder holding v3 saved over v4, and the agent page and
    the builder then showed different opening lines. A save names the version it started
    from and is refused when the draft has moved."""
    tenant_id, agent_id = await _tenant()
    await _save(tenant_id, agent_id, CallScript(opening_line="Namaste!"))
    await _save(tenant_id, agent_id, CallScript(opening_line="Namaste {{lead_name}} garu!"))

    with pytest.raises(ProblemError) as refused:
        await _save(
            tenant_id,
            agent_id,
            CallScript(opening_line="stale copy"),
            check_version=True,
            expected_version=1,
        )
    assert refused.value.code == "script_changed_elsewhere"

    async with tenant_session(tenant_id) as session:
        loaded = await script_builder.load_agent_script(session, agent_id)
    assert loaded.version == 2
    assert loaded.script.opening_line == "Namaste {{lead_name}} garu!"

    saved = await _save(
        tenant_id,
        agent_id,
        CallScript(opening_line="from the current copy"),
        check_version=True,
        expected_version=2,
    )
    assert saved.version == 3


async def test_a_first_save_expects_no_script() -> None:
    tenant_id, agent_id = await _tenant()
    saved = await _save(
        tenant_id,
        agent_id,
        CallScript(opening_line="first"),
        check_version=True,
        expected_version=None,
    )
    assert saved.version == 1
    with pytest.raises(ProblemError):
        await _save(
            tenant_id,
            agent_id,
            CallScript(opening_line="second, from an empty copy"),
            check_version=True,
            expected_version=None,
        )


async def test_a_recompile_keeps_the_script_structured_and_a_save_keeps_the_facts() -> None:
    """A recompile used to drop `structured_script`, so the builder reopened a structured
    script as raw text holding the platform's facts block; and a builder save compiled the
    body without the block, taking the business's facts out of the agent."""
    tenant_id, agent_id = await _tenant()
    await _save(tenant_id, agent_id, CallScript(opening_line="Namaste!"))
    async with tenant_session(tenant_id) as session:
        version = await t0.recompile_t0(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            knowledge=[t0.KnowledgeFact(name="Hours", text="Open 9 to 6, Monday to Saturday.")],
        )
    assert version == 2

    async with tenant_session(tenant_id) as session:
        loaded = await script_builder.load_agent_script(session, agent_id)
    assert loaded.is_freeform is False
    assert loaded.script.opening_line == "Namaste!"
    assert loaded.script.raw_override is None

    await _save(tenant_id, agent_id, CallScript(opening_line="Namaste, welcome."))
    async with tenant_session(tenant_id) as session:
        body = (
            await session.execute(
                text(
                    "SELECT pv.body FROM prompt_versions pv JOIN agents a "
                    "ON a.system_prompt_id = pv.id WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).scalar()
    assert str(body).count(T0_HEADER) == 1
    assert "Open 9 to 6, Monday to Saturday." in str(body)
    assert "Namaste, welcome." in str(body)


async def test_a_rollback_keeps_the_rolled_back_script_structured() -> None:
    tenant_id, agent_id = await _tenant()
    await _save(tenant_id, agent_id, CallScript(opening_line="first"))
    await _save(tenant_id, agent_id, CallScript(opening_line="second"))
    async with tenant_session(tenant_id) as session:
        await prompts.rollback_prompt(
            session, tenant_id=tenant_id, agent_id=agent_id, version=1, created_by=None
        )
        loaded = await script_builder.load_agent_script(session, agent_id)
    assert loaded.version == 3
    assert loaded.is_freeform is False
    assert loaded.script.opening_line == "first"
