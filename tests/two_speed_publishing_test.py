"""Two-speed publishing (SURFACES §2b:101) — the API half.

    "script/flow/actions/webhook edits require an explicit 'Apply to live calls';
     voice, extraction fields and training apply immediately. Split by blast radius,
     with an unsaved-changes banner offering Apply or Undo. Nothing goes live
     silently."

What these tests pin, and why each one is a separate assertion rather than a bigger
happy-path case:

1. **Nothing goes live silently.** Writing a script version for a LIVE agent must not
   reach the engine. This is the behaviour that INVERTED before this wave —
   `write_prompt_version` re-published in the same transaction, so the slow lane was
   the fastest thing in the system.
2. **The engine keeps the APPLIED script while a draft is staged.** The whole risk of
   a fast lane is that publishing a voice drags an unapproved script onto a live
   phone line, because `publish_agent` sends one `AgentConfig` for everything.
3. **Apply is explicit, CAS-guarded and idempotent** — a double-clicked button is not
   an error, but applying a draft that moved under you is.
4. **Undo moves the DRAFT pointer only.** History rows stay immutable and the applied
   pointer never moves backwards, so the `agents/prompts.py` invariant survives.
5. **Rollback still applies immediately**, and that is a decision, not an oversight:
   FLOWS §7 defines rollback as "republish an earlier version", which IS an apply. A
   client hitting rollback during a bad call is not asking to stage anything.
6. **Cross-tenant zero rows on the new columns** (hard rule 1) — the migration adds
   two columns to a tenant-scoped table, so the isolation claim is tested, not assumed.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts, publishing, t0
from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from sqlalchemy import text
from tests.conftest import accept_agreements

APPLIED = "Applied script: greet in Telugu, then take the appointment details."
STAGED = "Staged script: greet in Telugu, then upsell the whitening package."


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Two Speed Clinic",
        slug=f"ts-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    return created["id"], created["agent_id"]


async def _make_live(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    """The `prompt_rollback_test` shape: a fake engine ref plus the routing row."""
    ref = f"fakeagent_ts_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return ref


async def _pointers(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[int | None, int | None]:
    """(draft version, applied version) — the two pointers, as version NUMBERS."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT d.version, l.version FROM agents a "
                    "LEFT JOIN prompt_versions d ON d.id = a.system_prompt_id "
                    "LEFT JOIN prompt_versions l ON l.id = a.live_prompt_id "
                    "WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()
    assert row is not None
    return (
        int(row[0]) if row[0] is not None else None,
        int(row[1]) if row[1] is not None else None,
    )


async def _live_agent_with_a_staged_draft() -> tuple[uuid.UUID, uuid.UUID, str, FakeEngine]:
    """A live, published agent running APPLIED with STAGED waiting behind Apply."""
    reset_engine_cache()
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=APPLIED,
            notes=None,
            created_by=None,
        )
    ref = await _make_live(tenant_id, agent_id)
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    # Publish once so the engine really holds APPLIED — the baseline every assertion
    # about "what the caller hears" is measured against.
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert engine._agents[ref].system_prompt == APPLIED

    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=STAGED,
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id, ref, engine


# --- 1. nothing goes live silently -------------------------------------------


async def test_a_script_edit_on_a_live_agent_does_not_reach_the_engine() -> None:
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()

    assert engine._agents[ref].system_prompt == APPLIED, (
        "the slow lane published silently: a script edit reached a live client's phone "
        "line without anyone pressing Apply"
    )
    draft, applied = await _pointers(tenant_id, agent_id)
    assert draft is not None and applied is not None
    assert draft > applied, "the draft pointer moved, the applied pointer did not"


async def test_a_script_edit_on_a_draft_agent_is_applied_immediately() -> None:
    """A draft agent has no blast radius: nothing is on the engine to disturb, so
    staging would only manufacture a pending change the client cannot see the point
    of. Two-speed publishing exists for LIVE agents."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=APPLIED,
            notes=None,
            created_by=None,
        )
    draft, applied = await _pointers(tenant_id, agent_id)
    assert draft == applied, "a draft agent's edits are applied as they are written"

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.has_pending is False
    assert state.published is False


# --- 2. the fast lane cannot drag the draft script live ----------------------


async def test_publishing_a_live_agent_sends_the_applied_script_not_the_draft() -> None:
    """The reason `live_prompt_id` exists. `publish_agent` sends ONE AgentConfig, so
    before this pointer a fast-lane republish (voice, cap) had no way to avoid
    carrying whatever was in `system_prompt_id`."""
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()

    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert engine._agents[ref].system_prompt == APPLIED, (
        "a republish leaked the unapplied draft script onto a live agent"
    )


# --- 3. apply is explicit, CAS-guarded and idempotent ------------------------


async def test_apply_pushes_the_staged_script_and_moves_the_applied_pointer() -> None:
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()
    draft, _applied = await _pointers(tenant_id, agent_id)
    assert draft is not None

    result = await publishing.apply_to_live(
        tenant_id=tenant_id, agent_id=agent_id, expected_version=draft
    )

    assert result.applied is True
    assert result.live_version == draft
    assert engine._agents[ref].system_prompt == STAGED, "Apply is what reaches the engine"
    assert await _pointers(tenant_id, agent_id) == (draft, draft)


async def test_apply_with_nothing_pending_is_a_no_op_not_an_error() -> None:
    """A double-clicked Apply, a retried request, a second operator on the same
    screen. BACKEND-PATTERNS §5: idempotent by key, and the key here is the state."""
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    draft, _ = await _pointers(tenant_id, agent_id)
    assert draft is not None

    first = await publishing.apply_to_live(
        tenant_id=tenant_id, agent_id=agent_id, expected_version=draft
    )
    second = await publishing.apply_to_live(
        tenant_id=tenant_id, agent_id=agent_id, expected_version=draft
    )

    assert first.applied is True
    assert second.applied is False, "nothing was pending the second time"
    assert second.live_version == draft


async def test_apply_refuses_a_draft_that_moved_under_the_operator() -> None:
    """CAS on the version the caller actually looked at. Applying "whatever is staged
    now" is how a colleague's half-finished script goes live under your click."""
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    stale, _ = await _pointers(tenant_id, agent_id)
    assert stale is not None

    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="A third script somebody else wrote while the banner was open.",
            notes=None,
            created_by=None,
        )

    with pytest.raises(ProblemError) as exc:
        await publishing.apply_to_live(
            tenant_id=tenant_id, agent_id=agent_id, expected_version=stale
        )
    assert exc.value.kind == "conflict"
    assert exc.value.code == "stale_pending_change"


# --- 4. undo moves the draft pointer only ------------------------------------


async def test_undo_returns_the_draft_to_the_applied_script_without_touching_history() -> None:
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()
    draft, applied = await _pointers(tenant_id, agent_id)
    assert draft is not None and applied is not None

    async with tenant_session(tenant_id) as session:
        before = [
            (int(r[0]), str(r[1]))
            for r in (
                await session.execute(
                    text(
                        "SELECT version, body FROM prompt_versions WHERE agent_id = :a "
                        "ORDER BY version"
                    ),
                    {"a": agent_id},
                )
            ).all()
        ]

    result = await publishing.undo_staged(tenant_id=tenant_id, agent_id=agent_id)

    assert result.undone is True
    assert await _pointers(tenant_id, agent_id) == (applied, applied)
    assert engine._agents[ref].system_prompt == APPLIED, "Undo never touches the engine"

    async with tenant_session(tenant_id) as session:
        after = [
            (int(r[0]), str(r[1]))
            for r in (
                await session.execute(
                    text(
                        "SELECT version, body FROM prompt_versions WHERE agent_id = :a "
                        "ORDER BY version"
                    ),
                    {"a": agent_id},
                )
            ).all()
        ]
    assert after == before, "Undo discards a POINTER, never a version row (immutable history)"

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.has_pending is False


async def test_undo_with_nothing_pending_is_a_no_op() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=APPLIED,
            notes=None,
            created_by=None,
        )
    result = await publishing.undo_staged(tenant_id=tenant_id, agent_id=agent_id)
    assert result.undone is False


# --- 5. the two deliberate exceptions ---------------------------------------


async def test_rollback_still_applies_immediately_because_it_is_itself_an_apply() -> None:
    """FLOWS §7 defines rollback as "republish an earlier version" — the body is one
    this agent has already spoken, and the person clicking it is watching a bad script
    take calls. Making the recovery path wait for a second click is the one place
    where "nothing goes live silently" would cost more than it protects."""
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()
    applied_version = (await _pointers(tenant_id, agent_id))[1]
    assert applied_version is not None

    async with tenant_session(tenant_id) as session:
        rolled = await prompts.rollback_prompt(
            session, tenant_id=tenant_id, agent_id=agent_id, version=applied_version
        )

    assert engine._agents[ref].system_prompt == APPLIED, "rollback did not reach the engine"
    assert await _pointers(tenant_id, agent_id) == (rolled, rolled), (
        "a rollback resets BOTH pointers: it applies, so nothing is left staged"
    )
    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.has_pending is False


async def test_training_applies_immediately_but_waits_behind_a_staged_script() -> None:
    """Training is a fast-lane field (§2b), and the exception is structural rather
    than cautious: the T0 block is spliced into the DRAFT body, so applying a
    recompile while a script edit is staged would publish that script too. Deferring
    costs one retrieval hop — the same sources are attached to the engine's KB by the
    same publish, so what does not reach T0 is still answerable at T3."""
    reset_engine_cache()
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=APPLIED,
            notes=None,
            created_by=None,
        )
    ref = await _make_live(tenant_id, agent_id)
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    # Nothing staged: the recompile applies itself and reaches the engine.
    async with tenant_session(tenant_id) as session:
        first = await t0.recompile_t0(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            knowledge=[t0.KnowledgeFact(name="Fees", text="A consultation costs 500 rupees.")],
        )
    assert first is not None
    assert "500 rupees" in engine._agents[ref].system_prompt, "the fast lane did not apply"
    assert (
        await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    ).has_pending is False

    # Now a script edit is staged; a second recompile must wait with it.
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=STAGED,
            notes=None,
            created_by=None,
        )
        second = await t0.recompile_t0(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            knowledge=[t0.KnowledgeFact(name="Hours", text="Open on Sundays from this month.")],
        )

    assert second is not None, "the recompile still minted a version"
    assert "Sundays" not in engine._agents[ref].system_prompt, (
        "training applied over a staged script and published it"
    )
    assert STAGED not in engine._agents[ref].system_prompt
    draft, applied = await _pointers(tenant_id, agent_id)
    assert draft == second and applied is not None and applied < second


# --- 6. what is pending, and what it says -----------------------------------


async def test_the_pending_state_names_the_change_without_quoting_the_script() -> None:
    """The unsaved-changes banner's payload. Hard rule 6: prompt bodies routinely
    embed a client's prices and staff names, so the API answers with version numbers
    and a lane, never with the text."""
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    draft, applied = await _pointers(tenant_id, agent_id)

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)

    assert state.has_pending is True
    assert state.published is True
    assert [change.field for change in state.pending] == ["script"]
    change = state.pending[0]
    assert change.lane == "staged"
    assert change.staged_version == draft
    assert change.live_version == applied
    rendered = " ".join([change.headline, state.precedence_rule, *(c.why for c in state.pending)])
    assert STAGED not in rendered and APPLIED not in rendered, (
        "the pending payload quoted the script body — hard rule 6"
    )


async def test_the_lane_table_states_the_precedence_rule_surfaces_asks_for() -> None:
    """§2b: "script decides content, rules decide conduct, voice only changes
    delivery" — cheap to say, and it removes a class of support question. The API
    ships it as DATA so a UI cannot paraphrase it into something else."""
    lanes = {entry.field: entry for entry in publishing.LANES}

    assert lanes["script"].lane == "staged"
    assert lanes["voice"].lane == "live"
    assert lanes["extraction_fields"].lane == "live"
    assert lanes["training"].lane == "live"
    # A cap changes conduct, not content: it cannot alter one word the agent says.
    assert lanes["max_call_duration_s"].lane == "live"

    # Content outranks conduct outranks delivery.
    assert lanes["script"].precedence < lanes["max_call_duration_s"].precedence
    assert lanes["max_call_duration_s"].precedence < lanes["voice"].precedence


# --- 7. tenancy (hard rule 1) ------------------------------------------------


async def test_a_second_tenant_sees_no_agent_and_cannot_read_or_write_the_new_columns() -> None:
    """The cross-tenant zero-rows test that ships with the migration. Both new
    columns are read AND written from a second tenant's RLS scope; a column is not a
    separate security object, and this is where that claim gets checked."""
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    other_id, _other_agent = await _tenant()

    async with tenant_session(other_id) as session:
        rows = (
            await session.execute(
                text("SELECT live_prompt_id, max_call_duration_s FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).all()
        assert rows == [], "another tenant read the new columns off our agent"

        written = await session.execute(
            text(
                "UPDATE agents SET live_prompt_id = NULL, max_call_duration_s = 3600 "
                "WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
        assert written.rowcount == 0, "another tenant wrote the new columns on our agent"

    # And the victim's row is untouched.
    draft, applied = await _pointers(tenant_id, agent_id)
    assert draft is not None and applied is not None and draft > applied


async def test_pending_state_for_a_foreign_agent_is_not_found() -> None:
    _tenant_id, agent_id = await _tenant()
    other_id, _ = await _tenant()
    with pytest.raises(ProblemError) as exc:
        await publishing.pending_state_for(tenant_id=other_id, agent_id=agent_id)
    assert exc.value.kind == "not_found"
