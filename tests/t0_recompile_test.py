"""T0 regeneration on knowledge change (TRD §6, FLOWS §7) — the behaviour, not the fact.

`kb_tiers_test` asserts the one sentence that used to be doc-only: publishing knowledge
mints a prompt version carrying the newly approved facts. That is the headline, and it
is the least of what has to be true. This file pins the four properties that decide
whether the recompile is safe to leave running unattended on a client's live agent:

1. **It adds knowledge without losing intake.** The block has two halves with two
   owners (`agents/t0.py`), and a recompile that rebuilt the whole thing would drop the
   client's opening hours the first time they pasted an FAQ.
2. **Escalation phone numbers stay out.** `tests/intake_test.py` asserts that the wizard
   never compiles a staff mobile into a prompt the agent can read aloud. A second writer
   of the same block is exactly how that assertion becomes true-but-irrelevant, so it is
   re-asserted here from the other path — end to end, at the engine's copy.
3. **It never promotes an agent.** `publish_agent` writes `status = 'live'`, and FLOWS
   §1 step 7 makes going live a human gate (test call + regression mini-suite). A client
   publishing knowledge onto a PAUSED agent must not be how it comes back.
4. **It is versioning, not editing.** FLOWS §7's rollback republishes an earlier version
   and depends on the earlier rows still saying what they said. Every recompile is an
   INSERT; nothing rewrites history, and an unchanged block writes nothing at all.

Concurrency: every case creates its own run-unique tenant. Nothing counts global rows.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.admin import intake
from apps.api.agents import t0
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.kb import service as kb_service
from sqlalchemy import text
from tests.intake_test import FACTS
from tests.kb_workflow_test import _tenant_with_published_agent

ESCALATION_NUMBER = "+919000000123"


async def _publish_knowledge(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, body: str
) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(submitted["id"]))


async def _versions(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT pv.version, pv.body, coalesce(pv.compiled_t0_context, ''), pv.notes, "
                    "(pv.id = a.system_prompt_id) FROM prompt_versions pv "
                    "JOIN agents a ON a.id = pv.agent_id WHERE pv.agent_id = :aid "
                    "ORDER BY pv.version"
                ),
                {"aid": agent_id},
            )
        ).all()
    return [
        {"version": int(r[0]), "body": r[1], "compiled": r[2], "notes": r[3], "active": bool(r[4])}
        for r in rows
    ]


async def _engine_prompt(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    agents = get_engine()._agents  # type: ignore[attr-defined]
    config = agents.get(str(ref))
    return None if config is None else str(config.system_prompt)


async def _record_intake(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )


# --- 1. the two halves ----------------------------------------------------------------


async def test_publishing_knowledge_keeps_the_facts_the_intake_step_compiled() -> None:
    """The recompile ADDS a half; it does not rebuild the block.

    The intake half's inputs are the wizard's answer sheet, and re-deriving them here
    would be a second compiler for the same facts. This is the assertion that says
    "carried forward" out loud: the client's hours, address and price list survive a
    knowledge publish that knows nothing about them.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _record_intake(tenant_id, agent_id)

    await _publish_knowledge(
        tenant_id, agent_id, "Fees", "A consultation costs 500 rupees, payable at reception."
    )

    latest = (await _versions(tenant_id, agent_id))[-1]
    assert latest["compiled"].startswith(t0.T0_HEADER)
    assert "Root canal" in latest["compiled"], "the intake half was rebuilt instead of carried"
    assert "12 MG Road" in latest["compiled"]
    assert "500 rupees" in latest["compiled"], "the knowledge half never arrived"
    assert latest["compiled"] in latest["body"], "the block and the body disagree"
    assert latest["active"], "the agent still points at an older version"


async def test_a_second_knowledge_publish_does_not_duplicate_the_first() -> None:
    """Regenerating means REPLACING the block (PROMPT-GUIDE §2). A recompile that
    appended would leave the agent holding two price lists and quoting either."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_knowledge(tenant_id, agent_id, "Parking", "Parking is free for patients.")
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")

    latest = (await _versions(tenant_id, agent_id))[-1]
    assert latest["body"].count(t0.T0_HEADER) == 1, "a second [T0 FACTS] block was appended"
    assert latest["compiled"].count(t0.T0_KNOWLEDGE_MARKER) == 1
    assert "Parking is free" in latest["compiled"] and "500 rupees" in latest["compiled"]


async def test_superseding_a_source_replaces_its_facts_rather_than_stacking_them() -> None:
    """The client approved v2. An agent that can still say the v1 price out of its T0
    block is the divergence the approval gate exists to prevent — the same argument
    `publish_source` makes about the engine's copy, applied to the prompt's copy."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    latest = (await _versions(tenant_id, agent_id))[-1]
    assert "800 rupees" in latest["compiled"]
    assert "500 rupees" not in latest["compiled"], "the superseded price is still in the prompt"


# --- 2. escalation numbers stay out ---------------------------------------------------


async def test_a_knowledge_publish_never_lets_an_escalation_number_into_the_prompt() -> None:
    """`tests/intake_test.py` asserts this of the wizard's path. Asserted here of the
    OTHER writer of the same block, because a second writer is precisely how a rule
    that is enforced in one compiler becomes untrue of the artifact.

    A staff mobile compiled into a system prompt is a number the agent can read out to
    whoever asks for it. It used to live in `agents.escalation_config`; D-533 moved the
    same ordered list to `agent_handoff_members`, where it is now DIALLED rather than
    merely stored, and this guard is re-aimed at that table. The move is exactly the
    moment a leak is most likely, and the premise assertion below is what keeps the
    guard from going vacuous a second time: it fails loudly if the intake stops storing
    a number at all, instead of passing because there is nothing to leak.

    Checked at the engine's copy, which is the only place that decides what the agent
    can say. The number reaching the engine as a TRANSFER DESTINATION is intended and is
    not what this asserts — `handoff_applied`'s read-back owns that; what must never
    happen is the number landing in prose the model can read aloud.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _record_intake(tenant_id, agent_id)
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")

    async with tenant_session(tenant_id) as session:
        roster = (
            (
                await session.execute(
                    text(
                        "SELECT phone_e164 FROM agent_handoff_members "
                        "WHERE agent_id = :aid ORDER BY position"
                    ),
                    {"aid": agent_id},
                )
            )
            .scalars()
            .all()
        )
    assert list(roster)[:1] == [ESCALATION_NUMBER], (
        "premise: the intake stored an escalation number on this agent's handoff roster"
    )

    for version in await _versions(tenant_id, agent_id):
        assert ESCALATION_NUMBER not in version["compiled"], f"v{version['version']} block"
        assert ESCALATION_NUMBER not in version["body"], f"v{version['version']} body"
    published = await _engine_prompt(tenant_id, agent_id)
    assert published is not None and ESCALATION_NUMBER not in published


# --- 3. it never promotes an agent ----------------------------------------------------


async def test_publishing_knowledge_does_not_promote_a_paused_agent() -> None:
    """`publish_agent` writes `status = 'live'`. FLOWS §1 step 7 makes going live a
    human gate — a test call plus the regression mini-suite — and a client pasting an
    FAQ is not that gate. A paused agent is paused for a reason (a complaint, a cap, a
    compliance question), and coming back must be somebody's decision.

    The version is still minted: the recompile is about our records being right, and
    the block is correct the moment an operator does publish.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'paused' WHERE id = :aid"), {"aid": agent_id}
        )
    before = await _engine_prompt(tenant_id, agent_id)

    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    assert status == "paused", "a knowledge publish promoted a paused agent to live"
    assert await _engine_prompt(tenant_id, agent_id) == before, (
        "the paused agent's prompt was pushed to the engine anyway"
    )
    versions = await _versions(tenant_id, agent_id)
    assert versions and "500 rupees" in versions[-1]["compiled"], (
        "the recompile was skipped entirely — the block is wrong the moment it publishes"
    )


async def test_a_live_agent_answers_from_the_newly_approved_facts() -> None:
    """The counterpart, asserted where it matters: the ENGINE's copy of the prompt.

    Not "a row was written". The whole point of T0 is that the agent can answer without
    retrieving, and that is only true once the compiled block has reached the engine.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_knowledge(
        tenant_id, agent_id, "Fees", "A consultation costs 500 rupees, payable at reception."
    )

    published = await _engine_prompt(tenant_id, agent_id)
    assert published is not None, "the live agent was never pushed to the engine"
    assert "500 rupees" in published


# --- 4. versioning, not editing -------------------------------------------------------


async def test_a_recompile_is_a_new_version_and_never_rewrites_an_old_one() -> None:
    """FLOWS §7's rollback republishes an earlier version, which only works while the
    earlier rows still say what they said. Immutability is asserted by comparing every
    prior row across a second publish, not by trusting the INSERT."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    before = await _versions(tenant_id, agent_id)

    await _publish_knowledge(tenant_id, agent_id, "Parking", "Parking is free for patients.")
    after = await _versions(tenant_id, agent_id)

    assert len(after) == len(before) + 1
    assert after[: len(before)] == [{**v, "active": False} for v in before], (
        "an existing prompt version was rewritten by the recompile"
    )
    assert after[-1]["active"] and after[-1]["notes"]


async def test_republishing_the_same_knowledge_mints_nothing() -> None:
    """Idempotence, for the same reason the intake step has it: a double-clicked Publish
    button, a retry after a timeout and FLOWS §7's rollback onto the version already
    live must not each mint a version and re-push a live agent. The compiled block is
    deterministic, so "changed nothing" is decidable rather than guessed."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish_knowledge(
        tenant_id, agent_id, "Fees", "A consultation costs 500 rupees."
    )
    before = await _versions(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)

    assert await _versions(tenant_id, agent_id) == before, (
        "re-publishing an unchanged source minted a prompt version"
    )


async def test_a_rollback_to_the_earlier_knowledge_puts_the_earlier_facts_back() -> None:
    """FLOWS §7's rollback is republishing the archived row, and T0 has to follow it —
    a rollback that restored the engine's KB while leaving the superseded price in the
    prompt would leave the agent quoting the version the client just withdrew."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    v1 = await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    async with tenant_session(tenant_id) as session:
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=v1)

    versions = await _versions(tenant_id, agent_id)
    assert "500 rupees" in versions[-1]["compiled"]
    assert "800 rupees" not in versions[-1]["compiled"]
    # FOUR, NOT THREE, SINCE D-488: the fixture agent now starts with the applied SCRIPT
    # that every live agent really has (`give_agent_a_script` — an agent with none cannot
    # be published at all), so version 1 is the script and the three T0 recompiles follow
    # it. The property under test is unchanged and is the one that matters: a rollback
    # MINTS a version rather than editing one, so the count goes up.
    assert len(versions) == 4, "the rollback edited a version instead of minting one"


# --- the budget (PROMPT-GUIDE §2) -----------------------------------------------------


async def test_knowledge_that_does_not_fit_the_budget_stays_in_the_engine_kb() -> None:
    """PROMPT-GUIDE §2: "If [T0 FACTS] pushes past budget, facts move to RAG — that's
    the signal, not an invitation to trim guardrails."

    So an oversized source is skipped WHOLE rather than cut: the same publish attached
    it to the engine's KB, so it is still answerable one retrieval later (T3), whereas
    half a source in the prompt is an agent reading out half a price. The small source
    published afterwards must still make it in — the cap is a budget, not a fuse.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    long_body = "Our returns policy is explained at length. " * 80
    assert len(long_body) > t0.KNOWLEDGE_CHAR_BUDGET, "premise: the source exceeds the budget"

    await _publish_knowledge(tenant_id, agent_id, "Policy", long_body)
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")

    latest = (await _versions(tenant_id, agent_id))[-1]
    assert "500 rupees" in latest["compiled"], (
        "a source that fits was dropped along with the one that did not"
    )
    assert "returns policy" not in latest["compiled"]
    assert len(latest["compiled"]) < t0.KNOWLEDGE_CHAR_BUDGET * 2

    ref = (await _engine_prompt(tenant_id, agent_id)) or ""
    assert "returns policy" not in ref
    async with tenant_session(tenant_id) as session:
        engine_ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    assert len(await get_engine().list_kb(str(engine_ref))) == 2, (
        "the oversized source must still be retrievable at T3 — T0 dropped it, not the KB"
    )


# --- hard rule 6 ----------------------------------------------------------------------


async def test_the_recompile_logs_ids_and_counts_only(caplog: pytest.LogCaptureFixture) -> None:
    """The recompile handles the one text a client types deliberately — their own staff
    names, prices and phone numbers — and it runs on every publish, so it is the newest
    exit for that text. `kb_publish_atomicity_test` makes this check of the KB logger;
    this makes it of the compiler's own."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    secret = "Dr Rao on 9876543210 handles the emergency line after 8pm."

    with caplog.at_level("DEBUG", logger="apps.api.agents.t0"):
        await _publish_knowledge(tenant_id, agent_id, "Escalation", secret)

    records = [r for r in caplog.records if r.name == "apps.api.agents.t0"]
    assert records, "premise: the recompile logs something"
    for record in records:
        rendered = record.getMessage() + repr(record.__dict__)
        assert "9876543210" not in rendered
        assert "Dr Rao" not in rendered
        assert "emergency line" not in rendered


# --- the block format has exactly ONE implementation ---------------------------------


def test_the_block_format_has_a_single_owner() -> None:
    """`agents/t0.py` owns the [T0 FACTS] header and the splice; `admin/intake.py` calls
    it.

    This test used to be the opposite: two byte-identical copies, pinned to the same
    output by a parametrized comparison, deferred with "a one-line change in a module
    this wave does not own". The cycle that was said to force the copy
    (`admin.intake → kb.service → agents.t0 → admin.intake`) never existed — intake has
    always imported `agents.t0`, and `t0` imports nothing from `admin`. Two
    implementations agreeing today is not one implementation; it is the state the drift
    starts from, so the assertion is now that the second one is gone.
    """
    assert not hasattr(intake, "splice_t0_block")
    assert not hasattr(intake, "T0_HEADER")
    assert not hasattr(intake, "_INSERT_BEFORE")


@pytest.mark.parametrize(
    "body",
    [
        "",
        "[IDENTITY] Sunrise Dental receptionist.\n[GUARDRAILS] No medical advice.\n",
        "[IDENTITY] X.\n[T0 FACTS]\nHours: closed on Mondays\n[GUARDRAILS] No advice.\n",
        "[IDENTITY] X.\n[T0 FACTS]\nHours: old\n",
        "Free text with no sections at all.\n",
    ],
)
def test_the_surviving_splice_still_replaces_rather_than_appends(body: str) -> None:
    """The behaviour the two copies were pinned to, kept against the one that remains:
    a prompt never ends up with two [T0 FACTS] blocks, whatever it started as."""
    block = f"{t0.T0_HEADER}\nHours: mon 09:30-18:00"
    spliced = t0.splice_t0_block(body, block, identity="X.")
    assert spliced.count(t0.T0_HEADER) == 1
    assert "Hours: mon 09:30-18:00" in spliced


def test_the_knowledge_half_can_never_end_the_block() -> None:
    """Both splicers end the [T0 FACTS] block at the next line starting with `[`, and
    both find the knowledge half by an exact marker line. A client naming a source
    "[URGENT] Fees", or pasting a line that reads like the marker, would otherwise
    strand every knowledge line in the prompt body on the next intake save.
    """
    compiled = t0.compile_block(
        previous=f"{t0.T0_HEADER}\nHours: mon 09:30-18:00",
        knowledge=[
            t0.KnowledgeFact(name="[URGENT] Fees", text="500 rupees.\n\nPayable at reception."),
            t0.KnowledgeFact(name="Notes", text=f"{t0.T0_KNOWLEDGE_MARKER}\nnot a marker"),
        ],
    )
    lines = compiled.block.splitlines()
    assert lines[0] == t0.T0_HEADER
    assert [line for line in lines[1:] if line.startswith("[")] == []
    assert lines.count(t0.T0_KNOWLEDGE_MARKER) == 1
    assert t0.intake_half(compiled.block) == ["Hours: mon 09:30-18:00"]


# --- the other writer of the block ----------------------------------------------------
#
# Two modules write [T0 FACTS] and each owns one half, so the interesting cases are the
# ones where they meet. This was a strict xfail: the intake step compiled from the answer
# sheet ALONE, so a submit after a knowledge publish silently dropped every fact a client
# had already approved, until the next publish happened to put them back.


async def test_an_intake_submit_keeps_the_published_knowledge_half() -> None:
    """A submit recompiles OUR half and must not erase the other one."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")

    await _record_intake(tenant_id, agent_id)

    latest = (await _versions(tenant_id, agent_id))[-1]
    assert "Root canal" in latest["compiled"], "premise: the intake half recompiled"
    assert "500 rupees" in latest["compiled"]


async def test_an_intake_submit_with_no_published_knowledge_writes_no_marker() -> None:
    """The other direction, so "keep the knowledge half" cannot become "always append a
    heading". An empty `Published knowledge:` line spends prompt budget telling the model
    a section exists and then showing it nothing."""
    tenant_id, agent_id = await _tenant_with_published_agent()

    await _record_intake(tenant_id, agent_id)

    latest = (await _versions(tenant_id, agent_id))[-1]
    assert "Root canal" in latest["compiled"]
    assert t0.T0_KNOWLEDGE_MARKER not in latest["compiled"]


async def test_a_second_identical_submit_still_mints_nothing() -> None:
    """Composing through the compiler must not cost idempotence. `record_intake` returns
    early only when the block it would write is byte-identical to the live one — if the
    knowledge half were ordered or formatted differently on each pass, every save would
    mint a prompt version and re-publish a live agent for no change at all."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_knowledge(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _record_intake(tenant_id, agent_id)
    before = await _versions(tenant_id, agent_id)

    await _record_intake(tenant_id, agent_id)

    assert await _versions(tenant_id, agent_id) == before
