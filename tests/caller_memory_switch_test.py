"""The switch, end to end: from the client's click to what the phone line actually does.

Caller memory is the engine's (D-973); `caller_memory_notice_test.py` proves the SENTENCE is
composed. This is the file that connects the switch to them (D-513): flipping the column is
supposed to change three things at once — what callers hear, what the agent's instructions
contain, and whether a call-back can be booked at all — and the compliance guarantee is that
none of them can move without the others.

1. **THE PERMISSION IS A REFUSAL FIRST.** An account that has not said what its calls
   collect is told no, with the statement to confirm; a business whose kind cannot use this
   at all is told no permanently and cannot attest past it. Neither state is a column
   somebody can set by accident.
2. **THE SENTENCE FOLLOWS THE SWITCH IN BOTH DIRECTIONS.** "Remembers a caller without
   saying so" is the state D-507 made unconstructible; this is the test that would fail if
   somebody made it constructible again.
3. **THE PROMPT SECTION IS ABSENT ON AN AGENT THAT DOES NOT REMEMBER.** An empty labelled
   memory block on an agent with no memory is a section describing a capability it does not
   have, and a model reading one invents content for it.
"""

from __future__ import annotations

import json
import uuid

import pytest
from apps.api.agents import lifecycle as agent_lifecycle
from apps.api.agents.publishing import set_caller_memory
from apps.api.agents.roster import agent_by_id
from apps.api.agents.service import _load_agent
from apps.api.compliance.caller_memory import (
    CALLER_MEMORY_ATTESTATION,
    CALLER_MEMORY_ATTESTATION_VERSION,
    CALLER_MEMORY_ATTESTATIONS,
)
from apps.api.core.errors import ProblemError
from apps.api.crm.attention import attention_queue
from apps.api.db.session import tenant_session
from calevate_shared.engine import (
    ENGINE_MEMORY_RULE,
    AgentConfig,
    DisclosurePosture,
    ModelConfig,
    compose_engine_prompt,
    compose_opening_line,
)
from sqlalchemy import text
from tests.business_copy_test import copy_dict
from tests.conftest import _owner_of, create_org_with_receptionist

pytestmark = pytest.mark.anyio


async def _tenant(vertical: str = "real_estate") -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Switch Estates",
        slug=f"sw-{uuid.uuid4().hex[:8]}",
        vertical_template=vertical,
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # `_owner_of` rather than a membership read of our own: a tenant minted by
    # `create_organization(created_by=None)` HAS no owner row, and reading one back would
    # hand `attested_by=None` to a function whose whole first branch is "was an
    # attestation offered". The shared helper mints a stand-in person without inserting a
    # membership other fixtures count — its own docstring argues why.
    owner = await _owner_of(created["id"])
    return created["id"], created["agent_id"], owner


async def _column(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        return bool(
            (
                await session.execute(
                    text("SELECT caller_memory_enabled FROM agents WHERE id = :aid"),
                    {"aid": agent_id},
                )
            ).scalar_one()
        )


# --- the permission ------------------------------------------------------------------


async def test_switching_it_on_is_refused_until_the_account_says_what_its_calls_hold() -> None:
    """The attestation is the per-tenant instrument `SPDI_REFUSED_VERTICALS` describes
    itself as a weak proxy for. The refusal CARRIES the statement, so the screen and the
    refusal cannot describe different promises — and the column does not move."""
    tenant_id, agent_id, _owner = await _tenant()
    with pytest.raises(ProblemError) as refusal:
        await set_caller_memory(
            tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=None
        )
    assert refusal.value.code == "caller_memory_attestation_required"
    assert refusal.value.remediation == CALLER_MEMORY_ATTESTATION
    assert await _column(tenant_id, agent_id) is False


async def test_the_account_attests_once_and_a_second_agent_is_not_asked_again() -> None:
    """It is recorded on the BUSINESS because the attested fact is about the business. A
    client with four agents answers once — which is also why the result carries who
    confirmed it, so "we did not ask you this time" is explicable on the screen."""
    tenant_id, agent_id, owner = await _tenant()
    first = await set_caller_memory(
        tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
    )
    assert first.enabled is True
    assert first.attested_at is not None
    assert first.attested_by_name

    # A SECOND agent on the same account, switched on with NO attestation offered.
    # `create_agent` rather than a hand-written INSERT: it is THE one insert into `agents`
    # on any path that produces an agent a client uses, and four of the columns it fills
    # are hard rule 5. A fixture that wrote its own would be the second such place.
    async with tenant_session(tenant_id) as session:
        second_agent = await agent_lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Second receptionist",
            direction="inbound",
            language_primary="te-IN",
        )
        await session.commit()

    again = await set_caller_memory(
        tenant_id=tenant_id, agent_id=second_agent, enabled=True, attested_by=None
    )
    assert again.enabled is True


def test_the_current_statement_says_callers_are_not_told_on_the_call() -> None:
    """D-971 (founder, 5 Nov 2026, "Drop it entirely"): nothing about memory is said on a
    call, so the statement the owner accepts says their own notice is how callers learn it.
    Earlier versions are kept word for word for the accounts that accepted them."""
    assert CALLER_MEMORY_ATTESTATION_VERSION == 3 == max(CALLER_MEMORY_ATTESTATIONS)
    assert CALLER_MEMORY_ATTESTATIONS[3] == CALLER_MEMORY_ATTESTATION
    assert "do not tell callers this on the call" in CALLER_MEMORY_ATTESTATION
    assert "my own notice is how they learn it" in CALLER_MEMORY_ATTESTATION
    assert "will say so before ending each call" in CALLER_MEMORY_ATTESTATIONS[2]
    assert "will say so at the start of every call" in CALLER_MEMORY_ATTESTATIONS[1]


async def test_a_new_acceptance_records_the_current_version() -> None:
    tenant_id, agent_id, owner = await _tenant()
    result = await set_caller_memory(
        tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
    )
    assert result.attested_version == CALLER_MEMORY_ATTESTATION_VERSION
    assert result.statement_accepted == CALLER_MEMORY_ATTESTATION_VERSION


# --- an account on the old statement (D-900) ------------------------------------------


async def _on_old_statement(version: int = 2) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An account that accepted an earlier statement and switched its agent on before the
    change: version 1 as migration f5cd440f4e1c left it, version 2 as every account that
    accepted before D-971."""
    tenant_id, agent_id, owner = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE organizations SET caller_memory_attested_at = now(), "
                "caller_memory_attested_by = :by, caller_memory_attestation_version = :v "
                "WHERE id = :tid"
            ),
            {"by": owner, "tid": tenant_id, "v": version},
        )
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = true WHERE id = :aid"),
            {"aid": agent_id},
        )
        await session.commit()
    return tenant_id, agent_id, owner


async def _remembers(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> bool:
    """Whether a publish of this agent tells the engine to remember callers."""
    async with tenant_session(tenant_id) as session:
        agent = await _load_agent(session, tenant_id, agent_id)
    return bool(agent["caller_memory_enabled"])


async def _paused_item(tenant_id: uuid.UUID) -> dict[str, object] | None:
    async with tenant_session(tenant_id) as session:
        queue = await attention_queue(session)
    return next((i for i in queue["items"] if i["kind"] == "caller_memory_paused"), None)


@pytest.mark.parametrize("version", [1, 2])
async def test_an_account_on_the_old_statement_is_asked_and_its_agents_are_paused(
    version: int,
) -> None:
    """Versions 1 and 2 said the agent mentions the note on the call; since D-971 it says
    nothing. Until the owner accepts version 3 the account is treated as one that never
    accepted: nothing is remembered, and switching memory on asks for the statement. The
    agent's own switch stays where the owner left it."""
    tenant_id, agent_id, _owner = await _on_old_statement(version)

    assert await _remembers(tenant_id, agent_id) is False
    assert await _column(tenant_id, agent_id) is True

    async with tenant_session(tenant_id) as session:
        shown = await agent_by_id(session, agent_id)
    assert shown is not None
    assert shown.caller_memory_enabled is True
    assert shown.caller_memory_paused is True
    assert shown.caller_memory_statement == CALLER_MEMORY_ATTESTATION

    item = await _paused_item(tenant_id)
    assert item is not None
    assert item["title"] == "Caller memory is paused"
    assert item["href"] == f"/agents/{agent_id}?section=settings#call-handling"

    async with tenant_session(tenant_id) as session:
        second = await agent_lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Second receptionist",
            direction="inbound",
            language_primary="te-IN",
        )
        await session.commit()
    with pytest.raises(ProblemError) as refusal:
        await set_caller_memory(
            tenant_id=tenant_id, agent_id=second, enabled=True, attested_by=None
        )
    assert refusal.value.code == "caller_memory_attestation_required"
    assert refusal.value.remediation == CALLER_MEMORY_ATTESTATION


async def test_an_account_on_the_current_statement_is_not_asked() -> None:
    tenant_id, agent_id, owner = await _tenant()
    await set_caller_memory(tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner)

    assert await _remembers(tenant_id, agent_id) is True
    async with tenant_session(tenant_id) as session:
        shown = await agent_by_id(session, agent_id)
    assert shown is not None
    assert shown.caller_memory_paused is False
    assert shown.caller_memory_statement is None
    assert await _paused_item(tenant_id) is None


async def test_re_accepting_records_the_new_version_and_resumes_every_agent() -> None:
    """Re-acceptance goes through the same switch, on an agent that is already on. It
    records the current version for the account, resumes memory, and walks the account's live
    agents so the ones the owner left on are republished remembering."""
    tenant_id, agent_id, owner = await _on_old_statement()

    again = await set_caller_memory(
        tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
    )
    assert again.unchanged is True
    assert again.statement_accepted == CALLER_MEMORY_ATTESTATION_VERSION
    assert again.attested_version == CALLER_MEMORY_ATTESTATION_VERSION

    assert await _remembers(tenant_id, agent_id) is True
    assert await _paused_item(tenant_id) is None
    async with tenant_session(tenant_id) as session:
        walks = (
            await session.execute(
                text(
                    "SELECT count(*) FROM live_apply_runs WHERE scope = 'tenant' "
                    "AND tenant_id = :tid AND reasons ? 'caller_memory_statement'"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    assert walks == 1

    # Accepted once: the next switch-on on this account is not asked again.
    repeat = await set_caller_memory(
        tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=None
    )
    assert repeat.statement_accepted is None


async def test_switching_off_on_the_old_statement_needs_no_acceptance() -> None:
    tenant_id, agent_id, _owner = await _on_old_statement()
    off = await set_caller_memory(
        tenant_id=tenant_id, agent_id=agent_id, enabled=False, attested_by=None
    )
    assert off.enabled is False and off.statement_accepted is None
    assert await _paused_item(tenant_id) is None


async def test_a_clinic_cannot_attest_its_way_past_the_refusal() -> None:
    """D-507(b). The proxy stays ABOVE the attestation because a vertical is a RECORD and
    an attestation is a CLAIM."""
    tenant_id, agent_id, owner = await _tenant(vertical="clinic")
    with pytest.raises(ProblemError) as refusal:
        await set_caller_memory(
            tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
        )
    assert refusal.value.code == "caller_memory_refused_for_vertical"
    assert await _column(tenant_id, agent_id) is False


async def _judged(tenant_id: uuid.UUID, *, health: bool) -> None:
    raw = copy_dict()
    raw["capabilities"]["health_business"] = {"reason": "Judged for the test.", "applies": health}
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_copies (id, tenant_id, generated) "
                "VALUES (:id, :t, CAST(:g AS jsonb))"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "g": json.dumps(raw)},
        )


async def test_a_business_judged_to_give_health_care_is_refused_under_any_type() -> None:
    """FAILS IF: a pharmacy or lab filed as retail switches memory on because only the
    listed type was read (D-507(b))."""
    tenant_id, agent_id, owner = await _tenant(vertical="retail")
    await _judged(tenant_id, health=True)
    with pytest.raises(ProblemError) as refusal:
        await set_caller_memory(
            tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
        )
    assert refusal.value.code == "caller_memory_refused_for_vertical"
    assert await _column(tenant_id, agent_id) is False


async def test_a_business_judged_not_to_give_health_care_may_switch_it_on() -> None:
    """FAILS IF: the judgement refuses a business it found gives no health care."""
    tenant_id, agent_id, owner = await _tenant(vertical="retail")
    await _judged(tenant_id, health=False)
    on = await set_caller_memory(
        tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
    )
    assert on.enabled is True


async def test_a_clinic_judged_otherwise_is_still_refused() -> None:
    """FAILS IF: the judgement lifts the listed-type refusal; it may only add one."""
    tenant_id, agent_id, owner = await _tenant(vertical="clinic")
    await _judged(tenant_id, health=False)
    with pytest.raises(ProblemError) as refusal:
        await set_caller_memory(
            tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner
        )
    assert refusal.value.code == "caller_memory_refused_for_vertical"


async def test_switching_it_off_needs_no_attestation_and_is_idempotent() -> None:
    """A permission is asked for when the RISK is taken, never when it is given up. And
    re-asserting the state an agent is already in publishes nothing and says so, which is
    what lets the route write one audit row per decision rather than per double-click."""
    tenant_id, agent_id, owner = await _tenant()
    await set_caller_memory(tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner)
    off = await set_caller_memory(
        tenant_id=tenant_id, agent_id=agent_id, enabled=False, attested_by=None
    )
    assert off.enabled is False and off.unchanged is False
    twice = await set_caller_memory(
        tenant_id=tenant_id, agent_id=agent_id, enabled=False, attested_by=None
    )
    assert twice.unchanged is True


# --- what the caller hears -------------------------------------------------------------


def test_the_memory_sentence_never_enters_the_opening_line() -> None:
    """Whatever `caller_memory_enabled` says, the opening is the AI and recording notices
    only (D-865)."""
    posture = DisclosurePosture(
        ai_disclosure_line="This is an AI assistant.",
        ai_disclosure_enabled=True,
        recording_notice_line="This call is recorded.",
        recording_notice_enabled=True,
        caller_memory_notice_line="We keep a short note of what you ask about.",
        caller_memory_enabled=False,
    )
    assert "short note" not in compose_opening_line(posture, call_is_recorded=True)
    remembering = posture.model_copy(update={"caller_memory_enabled": True})
    assert compose_opening_line(remembering, call_is_recorded=True) == (
        "This is an AI assistant. This call is recorded."
    )


# --- what the agent is told ------------------------------------------------------------


SCRIPT = "Answer questions about listings."


def _config(**overrides: object) -> AgentConfig:
    base: dict[str, object] = {
        "tenant_id": "0199a0b0-0000-7000-8000-000000000001",
        "agent_id": "0199a0b0-0000-7000-8000-000000000002",
        "name": "Sunrise Estates receptionist",
        "direction": "inbound",
        "system_prompt": SCRIPT,
        "opening_line": "This is an AI assistant.",
        "models": ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="sarvam-105b",
            tts_provider="cartesia",
            tts_voice="ashutosh",
        ),
    }
    base.update(overrides)
    return AgentConfig(**base)  # type: ignore[arg-type]


def test_an_agent_that_does_not_remember_carries_no_memory_section() -> None:
    """Absent entirely, which is every agent by default."""
    prompt = compose_engine_prompt(
        _config(caller_memory_enabled=False, caller_memory_in_engine=True)
    )
    assert ENGINE_MEMORY_RULE not in prompt


def test_an_agent_that_remembers_on_the_engine_carries_only_the_engine_rule() -> None:
    """The memory is the engine's (D-973); the prompt says only not to invent one."""
    prompt = compose_engine_prompt(
        _config(caller_memory_enabled=True, caller_memory_in_engine=True)
    )
    assert ENGINE_MEMORY_RULE in prompt
    assert prompt.index(ENGINE_MEMORY_RULE) < prompt.index(SCRIPT)


def test_an_engine_that_keeps_no_memory_gets_no_memory_section() -> None:
    """With our own store retired, an engine that keeps none gives the agent no memory, so the
    prompt must not describe one."""
    prompt = compose_engine_prompt(_config(caller_memory_enabled=True))
    assert ENGINE_MEMORY_RULE not in prompt
