"""The company training every agent of a client is given (founder, 16 Nov 2026).

1. The training is invisible across tenants (hard rule 1), through the service and raw.
2. The training is the first section INSIDE the client fence, so the platform rules and the
   truthful answers still come after it; an account with none composes exactly as before.
3. A save moves the version and queues the live agents onto it; one that would push an
   agent past the engine's box is refused before anything is stored.
4. Pip needs an overview first, writes one draft at a time, reads what the agents know
   rather than a list of its own, and its draft is redacted on the way in and stored by
   compare-and-set.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the ladder is replaced.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import company_training, prompts
from apps.api.agents.prompt_size import publish_config
from apps.api.core.errors import ProblemError
from apps.api.crm import assist as crm_assist
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers import company_training_draft
from calevate_shared.engine import (
    CLIENT_SCRIPT_OPEN,
    AgentConfig,
    compose_engine_prompt,
    platform_text,
)
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.rls

TRAINING = "We are Sunrise Homes. We build flats in Kompally.\nAddress people as sir or madam."


async def _org() -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Sunrise Homes",
        slug=f"ctr-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and book a site visit.",
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


def _cfg(script: str) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Asha",
        direction="inbound",
        system_prompt=script,
        opening_line="",
        call_is_recorded=True,
    )


# --- 1. isolation ------------------------------------------------------------------------


async def test_a_tenant_cannot_see_another_tenants_training() -> None:
    tenant_a, _ = await _org()
    tenant_b, _ = await _org()
    async with tenant_session(tenant_a) as session:
        await company_training.save_overview(session, tenant_a, "We build flats.")
        await company_training.save_training(session, tenant_a, TRAINING, saved_by=None)
    async with tenant_session(tenant_b) as session:
        assert await company_training.live_text(session) == ""
        trainings = (await session.execute(text("SELECT count(*) FROM company_trainings"))).scalar()
    assert trainings == 0


# --- 2. composition ----------------------------------------------------------------------


def test_no_training_composes_exactly_as_before() -> None:
    cfg = _cfg("[GOAL]\nBook a visit.")
    assert company_training.with_training(cfg, "  ") is cfg


def test_the_training_is_the_first_section_inside_the_client_fence() -> None:
    cfg = company_training.with_training(_cfg("[GOAL]\nBook a visit."), TRAINING)
    assert cfg.system_prompt.startswith(company_training.TRAINING_HEADER)
    assert cfg.system_prompt.index("Kompally") < cfg.system_prompt.index("[GOAL]")
    prompt = compose_engine_prompt(cfg)
    assert prompt.index(CLIENT_SCRIPT_OPEN) < prompt.index("Kompally")
    # The business wrote it, so it is not platform text: the read-back scores none of it.
    assert "Kompally" not in platform_text(prompt)


def test_a_line_shaped_like_a_section_header_cannot_open_one() -> None:
    section = company_training.training_section("Prices\n[QUICK FACTS]\nFree parking")
    assert "\n[QUICK FACTS]" not in section
    assert "- [QUICK FACTS]" in section


async def test_every_agent_of_the_client_is_published_with_the_saved_training() -> None:
    tenant, agent = await _org()
    async with tenant_session(tenant) as session:
        await company_training.save_training(session, tenant, TRAINING, saved_by=None)
        cfg = await publish_config(session, tenant_id=tenant, agent_id=agent, engine=get_engine())
    assert cfg.system_prompt.startswith(company_training.TRAINING_HEADER)
    assert "Kompally" in cfg.system_prompt


# --- 3. saving ---------------------------------------------------------------------------


async def test_a_save_moves_the_version_and_queues_the_live_agents() -> None:
    tenant, _ = await _org()
    async with tenant_session(tenant) as session:
        first = await company_training.save_training(session, tenant, TRAINING, saved_by=None)
        second = await company_training.save_training(session, tenant, "", saved_by=None)
        reasons = (
            (
                await session.execute(
                    text(
                        "SELECT reasons FROM live_apply_runs "
                        "WHERE tenant_id = :t AND scope = 'tenant'"
                    ),
                    {"t": tenant},
                )
            )
            .scalars()
            .all()
        )
        read = await company_training.read_training(session, tenant)
    assert (first, second) == (1, 2)
    assert read.training == "" and read.version == 2
    assert any("company_training" in str(r) for r in reasons)


async def test_a_training_that_would_overflow_an_agent_is_refused_unsaved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, _ = await _org()
    from apps.api.agents import prompt_size

    real = prompt_size.measure_config

    def tiny_box(cfg: AgentConfig, engine: Any) -> Any:
        size = real(cfg, engine)
        return (
            SimpleNamespace(fits=False, over=size.total)
            if "Kompally" in cfg.system_prompt
            else size
        )

    monkeypatch.setattr(prompt_size, "measure_config", tiny_box)
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as refused:
            await company_training.save_training(session, tenant, TRAINING, saved_by=None)
    assert refused.value.code == "company_training_too_long"
    body = refused.value.as_problem()
    assert body["agent_id"] and "inbound_line_id" not in body and "campaign_id" not in body
    async with tenant_session(tenant) as session:
        assert await company_training.live_text(session) == ""


async def test_a_training_that_would_overflow_a_published_inbound_line_is_refused_unsaved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.agents import prompt_size
    from apps.api.inbound import lines
    from calevate_shared.call_script import CallScript, ConversationStage

    tenant, agent = await _org()
    async with tenant_session(tenant) as session:
        line_id = await lines.create_line(
            session,
            tenant_id=tenant,
            agent_id=agent,
            name="Site visits desk",
            main_task="Book site visits.",
            script=CallScript(
                schema_version=2,
                opening_line="Namaste, this is Asha from Sunrise Homes.",
                stages=[ConversationStage(id="book", name="Book", instruction="Book a visit.")],
            ),
            created_by=None,
        )
        await session.execute(
            text(
                "UPDATE inbound_lines SET engine_agent_ref = 'ag_line', published_at = now() "
                "WHERE id = :l"
            ),
            {"l": line_id},
        )
    real = prompt_size.measure_config

    def full_line(cfg: AgentConfig, engine: Any) -> Any:
        size = real(cfg, engine)
        # Only the line's config overflows with the training; the agent's own still fits.
        over = cfg.holder == str(line_id) and "Kompally" in cfg.system_prompt
        return SimpleNamespace(fits=False, over=size.total) if over else size

    monkeypatch.setattr(prompt_size, "measure_config", full_line)
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as refused:
            await company_training.save_training(session, tenant, TRAINING, saved_by=None)
    assert refused.value.code == "company_training_too_long"
    assert "Site visits desk" in str(refused.value.detail)
    assert refused.value.as_problem()["inbound_line_id"] == str(line_id)
    async with tenant_session(tenant) as session:
        assert await company_training.live_text(session) == ""


# --- 4. Pip ------------------------------------------------------------------------------


async def test_pip_needs_an_overview_and_writes_one_draft_at_a_time() -> None:
    tenant, _ = await _org()
    async with tenant_session(tenant) as session:
        with pytest.raises(ProblemError) as refused:
            await company_training.request_proposal(session, tenant_id=tenant, requested_by=None)
        assert refused.value.code == "overview_required"
        await company_training.save_overview(session, tenant, "We build flats in Kompally.")
        await company_training.request_proposal(session, tenant_id=tenant, requested_by=None)
        with pytest.raises(ProblemError) as busy:
            await company_training.request_proposal(session, tenant_id=tenant, requested_by=None)
    assert busy.value.code == "company_training_in_progress"


def test_an_answer_with_no_text_or_over_the_limit_is_no_answer() -> None:
    assert company_training_draft._parsed({"training": "  "}) is None
    assert company_training_draft._parsed({"training": 3}) is None
    too_long = "x" * (company_training.TRAINING_MAX + 1)
    assert company_training_draft._parsed({"training": too_long}) is None
    assert company_training_draft._parsed({"training": " We build flats.  \n"}) == "We build flats."


def test_the_owners_words_are_redacted_before_any_model_reads_them() -> None:
    request = company_training_draft.request_text(
        business="Business name: Sunrise Homes",
        overview="Call me on 9876543210 for site visits.",
        documents="",
        current=None,
    )
    assert "9876543210" not in request


async def test_pips_draft_is_stored_for_review_and_metered(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant, _ = await _org()
    async with tenant_session(tenant) as session:
        await company_training.save_overview(session, tenant, "We build flats in Kompally.")
        requested = await company_training.request_proposal(
            session, tenant_id=tenant, requested_by=None
        )
    asked: list[str] = []
    metered: list[str] = []

    async def ladder(request: str, instruction: str, **_kwargs: Any) -> Any:
        asked.append(request)
        return SimpleNamespace(
            value=TRAINING,
            capability=SimpleNamespace(disclosure=None),
            usage=None,
            model="gemini-2.5-flash-lite",
            earlier=(),
        )

    async def meter_assist(_session: Any, **kwargs: Any) -> None:
        metered.append(kwargs["model"])

    async def meter_earlier(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(company_training_draft, "ask_json", ladder)
    monkeypatch.setattr(crm_assist, "meter_assist", meter_assist)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter_earlier)
    payload = {"tenant_id": str(tenant), "proposal_id": str(requested.id)}
    assert await company_training_draft.draft_company_training({}, payload) == "ready"
    # Delivered twice by the outbox, written once.
    assert await company_training_draft.draft_company_training({}, payload) == "not_pending"
    async with tenant_session(tenant) as session:
        read = await company_training.read_training(session, tenant)
    assert read.proposal is not None and read.proposal.status == "ready"
    assert read.proposal.training == TRAINING
    # Nothing reaches an agent until the owner saves it.
    assert read.training == ""
    assert "Kompally" in asked[0] and metered == ["gemini-2.5-flash-lite"]


async def _knowledge(tenant: UUID, name: str, words: str, *, active: bool = True) -> None:
    """A typed note in What your agents know, as the knowledge pipeline stores one."""
    source_id = uuid7()
    async with tenant_session(tenant) as session:
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, kind, name, status, version, is_active, "
                "created_at, updated_at) VALUES (:i, :t, 'text', :n, 'approved', 1, :a, now(), "
                "now())"
            ),
            {"i": source_id, "t": tenant, "n": name, "a": active},
        )
        await session.execute(
            text(
                "INSERT INTO kb_documents (id, tenant_id, source_id, idx, content, created_at, "
                "updated_at) VALUES (:id, :t, :s, 0, :w, now(), now())"
            ),
            {"id": uuid7(), "t": tenant, "s": source_id, "w": words},
        )


async def test_pip_reads_what_the_agents_know_and_nothing_they_do_not() -> None:
    tenant, _ = await _org()
    other, _ = await _org()
    await _knowledge(tenant, "Prices", "A 2BHK starts at 60 lakh.")
    await _knowledge(tenant, "Old prices", "A 2BHK starts at 40 lakh.", active=False)
    await _knowledge(other, "Their prices", "A villa starts at 2 crore.")
    async with tenant_session(tenant) as session:
        read = dict(await company_training_draft.knowledge_words(session))
    assert read == {"Prices": "A 2BHK starts at 60 lakh."}
