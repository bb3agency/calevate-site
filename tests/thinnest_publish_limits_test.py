"""Publishing to an engine whose fields have ceilings: refuse before the write, never trim.

ThinnestAI holds at most 20,000 characters of `instructions`, 200 of `greeting`, and needs
a call `purpose` of at most 300 on every outbound dial
(`thinnest-findings/mirror/snapshots/2026-10-07/pages/api-reference/agents/
update-agent.md:426-436`, `calls/place-call.md:7`).
`agents/engine_limits.refuse_over_engine_limits`
is the check; these tests pin that it refuses with a sentence a client can act on, that it
runs BEFORE any vendor call, that the read-back verifier still refuses an agent missing
either rule on this engine, and that no other engine is touched by it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents.engine_limits import (
    OPENING_REQUIRED,
    OPENING_TOO_LONG,
    PROMPT_TOO_LONG,
    refuse_over_engine_limits,
)
from apps.api.agents.service import publish_agent
from apps.api.agents.verification import judge
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from apps.api.engine.hosted_platform import (
    NO_HOSTED_LIMITS,
    THINNEST_LIMITS,
    engine_number_console,
    hosted_agent_limits,
    split_for_text_cap,
)
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    AgentSnapshot,
    EngineAgentRef,
    compose_engine_prompt,
)
from sqlalchemy import text
from tests.conftest import accept_agreements

OPENING = "Idi AI assistant. Ee call record avutundi."


@pytest.fixture(autouse=True)
def _platform_minute_priced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every publish here is on an engine metered by the minute; price its base minute so
    the case under test is the one that decides. One test overrides this."""
    from apps.api.agents import engine_limits

    async def _priced(session: Any, *, engine: str, rate_key: str, at: Any) -> bool:
        return True

    monkeypatch.setattr(engine_limits, "engine_minute_is_billable", _priced)


def _thinnest(**kw: Any) -> FakeEngine:
    """A fake adapter answering to the engine name the limits are keyed by."""
    return FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES, **kw)


def _cfg(**kw: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "tenant_id": str(uuid.uuid4()),
        "agent_id": str(uuid.uuid4()),
        "name": "Sunrise Clinic receptionist",
        "direction": "inbound",
        "system_prompt": "Greet in Telugu, then take the appointment.",
        "opening_line": OPENING,
    }
    return AgentConfig(**{**base, **kw})


def _refusal(engine: FakeEngine, cfg: AgentConfig) -> ProblemError:
    with pytest.raises(ProblemError) as caught:
        refuse_over_engine_limits(engine, cfg)
    return caught.value


# --- the vendor facts --------------------------------------------------------


def test_the_limits_are_the_documented_field_ceilings() -> None:
    assert THINNEST_LIMITS.prompt_chars == 20_000
    assert THINNEST_LIMITS.greeting_chars == 200
    assert THINNEST_LIMITS.call_opening_chars == 300
    assert THINNEST_LIMITS.call_opening_required is True
    assert THINNEST_LIMITS.kb_text_chars == 200_000
    assert hosted_agent_limits(_thinnest()) is THINNEST_LIMITS


def test_no_other_engine_has_limits_or_console_steps() -> None:
    for name in ("pipecat", "fake", "cartesia"):
        engine = FakeEngine(name=name)
        assert hosted_agent_limits(engine) is NO_HOSTED_LIMITS
        assert engine_number_console(engine) is None


def test_an_engine_with_no_limits_publishes_any_length() -> None:
    refuse_over_engine_limits(FakeEngine(), _cfg(system_prompt="x " * 20_000, opening_line=""))


# --- the prompt ceiling --------------------------------------------------------


def test_a_prompt_that_fits_passes() -> None:
    refuse_over_engine_limits(_thinnest(), _cfg())


def test_a_prompt_over_the_ceiling_is_refused_with_the_numbers_to_cut() -> None:
    cfg = _cfg(system_prompt="word " * 4_200)
    composed = len(compose_engine_prompt(cfg))
    assert composed > 20_000
    problem = _refusal(_thinnest(), cfg)
    assert problem.code == PROMPT_TOO_LONG
    assert problem.status == 422
    assert f"{composed:,}" in problem.detail and "20,000" in problem.detail
    assert f"{composed - 20_000:,}" in (problem.remediation or "")
    # The room left for the script is exact: a script that long fits, one longer does not.
    room = 20_000 - (composed - len(cfg.system_prompt.strip()))
    assert f"{room:,}" in (problem.remediation or "")
    refuse_over_engine_limits(_thinnest(), _cfg(system_prompt="w" * room))
    with pytest.raises(ProblemError):
        refuse_over_engine_limits(_thinnest(), _cfg(system_prompt="w" * (room + 1)))


def test_the_refusal_names_no_vendor_and_no_prompt_text() -> None:
    cfg = _cfg(system_prompt="secret-staff-mobile " * 1_100)
    problem = _refusal(_thinnest(), cfg)
    body = f"{problem.title} {problem.detail} {problem.remediation}"
    assert "ThinnestAI" not in body and "secret-staff-mobile" not in body


# --- the opening line ----------------------------------------------------------


def test_an_opening_line_over_the_greeting_ceiling_is_refused() -> None:
    problem = _refusal(_thinnest(), _cfg(opening_line="a" * 201))
    assert problem.code == OPENING_TOO_LONG
    assert "201" in problem.detail and "200" in problem.detail
    refuse_over_engine_limits(_thinnest(), _cfg(opening_line="a" * 200))


def test_an_outbound_agent_with_no_opening_line_cannot_publish() -> None:
    for direction in ("outbound", "both"):
        problem = _refusal(_thinnest(), _cfg(direction=direction, opening_line=""))
        assert problem.code == OPENING_REQUIRED


def test_an_inbound_agent_with_no_opening_line_publishes() -> None:
    refuse_over_engine_limits(_thinnest(), _cfg(direction="inbound", opening_line=""))


# --- the publish path refuses BEFORE the vendor ---------------------------------


class _CountingEngine(FakeEngine):
    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.writes: list[str] = []

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        self.writes.append("create_agent")
        return await super().create_agent(cfg)

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        self.writes.append("update_agent")
        await super().update_agent(ref, cfg)


@contextmanager
def _selected(instance: FakeEngine) -> Iterator[FakeEngine]:
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


async def _agent_with_script(script: str) -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Limits Clinic",
        slug=f"lim-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    await accept_agreements(uuid.UUID(str(tenant_id)))
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=script,
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


async def test_publish_refuses_an_oversized_prompt_before_any_vendor_write() -> None:
    tenant_id, agent_id = await _agent_with_script("word " * 4_200)
    counting = _CountingEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    with _selected(counting) as e:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as caught:
                await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert caught.value.code == PROMPT_TOO_LONG
    assert isinstance(e, _CountingEngine) and e.writes == []
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).one()
    assert row[1] is None and row[0] != "live"


# --- the read-back still decides on this engine ----------------------------------


def _snapshot(cfg: AgentConfig, prompt: str) -> AgentSnapshot:
    return AgentSnapshot(
        engine_agent_ref="ag_test",
        system_prompt=prompt,
        system_prompt_readable=True,
        greeting=cfg.opening_line,
        greeting_readable=True,
        handoff_destinations_readable=True,
    )


def test_a_held_prompt_with_both_rules_is_applied() -> None:
    cfg = _cfg()
    verdict = judge(_thinnest(), cfg, _snapshot(cfg, compose_engine_prompt(cfg)))
    assert verdict.state == "applied"


@pytest.mark.parametrize("marker", [CONFIDENTIALITY_MARKER, TRUTHFUL_ANSWER_MARKER])
def test_instructions_read_back_without_a_rule_are_refused(marker: str) -> None:
    cfg = _cfg()
    held = compose_engine_prompt(cfg)
    assert marker in held
    verdict = judge(_thinnest(), cfg, _snapshot(cfg, held.replace(marker, "")))
    assert verdict.state == "not_applied"


# --- knowledge text splitting ------------------------------------------------------


def test_text_within_the_cap_is_one_part() -> None:
    assert split_for_text_cap("a\n\nb", 10) == ("a\n\nb",)
    assert split_for_text_cap("", 10) == ()


def test_text_over_the_cap_splits_on_chunk_boundaries_and_loses_nothing() -> None:
    chunks = [f"chunk {i:03d} " + "x" * 80 for i in range(50)]
    text_in = "\n\n".join(chunks)
    parts = split_for_text_cap(text_in, 1_000)
    assert len(parts) > 1
    assert all(len(part) <= 1_000 for part in parts)
    assert "\n\n".join(parts) == text_in


def test_a_single_piece_longer_than_the_cap_is_cut_at_whitespace() -> None:
    piece = " ".join(["word"] * 100)
    parts = split_for_text_cap(piece, 50)
    assert all(len(part) <= 50 for part in parts)
    assert " ".join(parts).split() == piece.split()


# --- the results webhook is registered at publish --------------------------------


class _DeletingEngine(_CountingEngine):
    async def delete_agent(self, ref: EngineAgentRef) -> None:
        self.writes.append("delete_agent")
        await super().delete_agent(ref)


async def test_publish_registers_the_agents_results_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.agents import service

    seen: list[tuple[str, str, bool]] = []

    async def _ensure(session: Any, *, engine: str, engine_agent_ref: str) -> None:
        # The route row the endpoint's secret is stored on must already exist.
        row = (
            await session.execute(
                text("SELECT 1 FROM engine_agent_routes WHERE engine_agent_ref = :r"),
                {"r": engine_agent_ref},
            )
        ).first()
        seen.append((engine, engine_agent_ref, row is not None))

    monkeypatch.setattr(service, "ensure_agent_webhook", _ensure)
    # The in-call actions are registered against the same route row (D-678 phase 2).
    monkeypatch.setattr(service, "ensure_agent_actions", _ensure)
    tenant_id, agent_id = await _agent_with_script("Greet in Telugu, then book.")
    with _selected(_CountingEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)):
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert seen == [("thinnest", ref, True), ("thinnest", ref, True)]
    async with tenant_session(tenant_id) as session:
        rate_key = (
            await session.execute(
                text("SELECT engine_rate_key FROM engine_agent_routes WHERE engine_agent_ref = :r"),
                {"r": ref},
            )
        ).scalar_one()
    assert rate_key == "platform"


async def test_a_failed_webhook_registration_fails_the_publish_and_reclaims_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.agents import service

    async def _refuse(session: Any, *, engine: str, engine_agent_ref: str) -> None:
        raise ProblemError(
            kind="dependency", code="engine_unavailable", title="down", detail="down"
        )

    monkeypatch.setattr(service, "ensure_agent_webhook", _refuse)
    tenant_id, agent_id = await _agent_with_script("Greet in Telugu, then book.")
    engine = _DeletingEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    with _selected(engine), pytest.raises(ProblemError):
        # The refusal leaves the session block, so its transaction rolls back as a
        # route's would.
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert engine.writes == ["create_agent", "delete_agent"]
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert ref is None


async def test_failed_in_call_actions_fail_the_publish_and_reclaim_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An agent live without its opt-out tool is one a caller cannot be removed from mid-call,
    so a failed action registration fails the publish like a failed webhook does."""
    from apps.api.agents import service

    async def _ok(session: Any, *, engine: str, engine_agent_ref: str) -> None:
        return None

    async def _refuse(session: Any, *, engine: str, engine_agent_ref: str) -> None:
        raise ProblemError(
            kind="validation", code="engine_actions_url_not_public", title="no", detail="no"
        )

    monkeypatch.setattr(service, "ensure_agent_webhook", _ok)
    monkeypatch.setattr(service, "ensure_agent_actions", _refuse)
    tenant_id, agent_id = await _agent_with_script("Greet in Telugu, then book.")
    engine = _DeletingEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    with _selected(engine), pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert caught.value.code == "engine_actions_url_not_public"
    assert engine.writes == ["create_agent", "delete_agent"]


async def test_publish_refuses_while_the_platform_minute_is_unpriced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.agents import engine_limits

    async def _unpriced(session: Any, *, engine: str, rate_key: str, at: Any) -> bool:
        return False

    monkeypatch.setattr(engine_limits, "engine_minute_is_billable", _unpriced)
    tenant_id, agent_id = await _agent_with_script("Greet in Telugu, then book.")
    engine = _CountingEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    with _selected(engine), pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert caught.value.code == engine_limits.MINUTE_UNPRICED
    assert engine.writes == []
