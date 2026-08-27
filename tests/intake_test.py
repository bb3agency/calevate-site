"""The wizard's intake step (FLOWS §1 step 3), and the campaign list's provenance flag.

Two gaps, one file, because both are about the same failure mode: a screen that has
the data in front of it and still cannot answer the client's question.

**Intake.** FLOWS §1 step 3 is the step where a client's own business facts are
captured, and §1 says what they are: business hours, address/branches, services +
prices, top FAQs, staff names/pronunciations, booking rules, escalation contacts,
languages — "Output feeds T0 compiled context + KB seed + prompt generation". So the
test that matters is not "the form saved": it is that a fact typed into the form comes
back out of the ENGINE's copy of the agent. An intake that stores answers nothing reads
is a form, not a feature.

**Provenance on the campaign list.** The list screen could see `status` and nothing
about consent, so it either warned about every draft or ran the whole launch gate once
per row. The test below pins the fix at its weakest point: the answer must come out of
the list query, with `launch_blockers` sabotaged so a hidden call to it cannot pass.

Concurrency: every case creates its own run-unique tenant; nothing here counts global
rows or touches another suite's data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import intake
from apps.api.admin import service as admin_service
from apps.api.agents import service as agents_service
from apps.api.agents import t0
from apps.api.agents.prompts import write_prompt_version
from apps.api.campaigns import service as campaigns_service
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import iter_api_routes
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.main import app
from sqlalchemy import text
from tests.conftest import accept_agreements

# One clinic's facts, in the shape FLOWS §1 step 3 lists them. Deliberately mundane:
# every assertion below looks for one of these strings coming back out of somewhere it
# could only have reached through the intake.
FACTS = intake.IntakeFacts(
    business_hours=[
        intake.DayHours(day="mon", opens="09:30", closes="18:00"),
        intake.DayHours(day="sun", closed=True),
    ],
    branches=[intake.Branch(label="Main", address="12 MG Road, Ameerpet, Hyderabad 500016")],
    services=[
        intake.ServiceItem(name="Root canal", price_inr="8000"),
        intake.ServiceItem(name="Cleaning", price_inr="1500", notes="30 minutes"),
    ],
    faqs=[intake.Faq(question="Do you take insurance?", answer="Cashless with four insurers.")],
    staff=[intake.StaffMember(name="Dr. Sowmya", pronunciation="సౌమ్య", role="Dentist")],
    booking_rules="Same-day slots close at 17:00; two chairs run in parallel.",
    escalation_contacts=[
        intake.EscalationContact(name="Reception", phone_e164="+919000000123", hours="09:00-18:00")
    ],
    languages=["te-IN", "en-IN"],
)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Sunrise Dental",
        slug=f"intake-{uuid.uuid4().hex[:8]}",
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
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


# --------------------------------------------------------------------- intake


async def test_intake_facts_reach_the_agent_the_engine_actually_runs() -> None:
    """The whole point of the step, asserted at the far end.

    Not "the row was written" — the fact has to survive compilation into [T0 FACTS],
    the prompt version, the publish, and the adapter, because that chain is what makes
    the agent able to answer a caller who asks the price of a root canal.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        ref = await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    published = get_engine()._agents[ref].system_prompt  # type: ignore[attr-defined]
    assert "09:30" in published, "business hours"
    assert "12 MG Road, Ameerpet, Hyderabad 500016" in published, "address"
    assert "Root canal" in published and "8000" in published, "services + prices"
    assert "Cashless with four insurers." in published, "top FAQs"
    assert "సౌమ్య" in published, "staff pronunciation (PROMPT-GUIDE §3)"
    assert "Same-day slots close at 17:00" in published, "booking rules"
    # Escalation contacts are agent CONFIG, not something the agent reads aloud — a
    # staff mobile number compiled into the system prompt is a number the agent can
    # give to a caller who asks for it.
    assert "+919000000123" not in published, "escalation numbers stay out of the prompt"


async def test_the_structured_facts_land_in_the_columns_that_already_read_them() -> None:
    """Hours, escalation contacts and languages have typed homes on `agents`
    (DATA-MODEL §3). They go there as data, not only as prose inside a prompt."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        row = (
            await session.execute(
                text(
                    "SELECT business_hours, escalation_config, languages_extra FROM agents "
                    "WHERE id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()
    assert row is not None
    hours, escalation, languages = row
    assert hours["mon"] == {"opens": "09:30", "closes": "18:00"}
    assert hours["sun"] is None, "a closed day is recorded closed, not omitted"
    assert escalation["contacts"][0]["phone_e164"] == "+919000000123"
    # The primary language is on the agent already; `languages_extra` is the rest.
    assert languages == ["en-IN"]


async def test_the_compiled_t0_context_is_stored_as_the_build_artifact_it_is() -> None:
    """D-39 reserves `prompt_versions.compiled_t0_context` for exactly this. Storing the
    block beside the body is what lets a later T0 compiler regenerate one without
    reverse-engineering the other."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        result = await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        row = (
            await session.execute(
                text(
                    "SELECT body, compiled_t0_context FROM prompt_versions "
                    "WHERE agent_id = :aid AND version = :v"
                ),
                {"aid": agent_id, "v": result["prompt_version"]},
            )
        ).first()
    assert row is not None
    body, compiled = row
    assert compiled and compiled.startswith(t0.T0_HEADER)
    assert compiled in body, "the body carries the block the artifact records"


async def test_recording_the_same_intake_twice_mints_no_second_prompt_version() -> None:
    """FLOWS §1: "every step idempotent". An operator who reopens the step and saves
    again has changed nothing, and a prompt version per save would turn the history
    into noise and re-publish a live agent for no reason."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        first = await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        second = await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        versions = (
            await session.execute(
                text("SELECT count(*) FROM prompt_versions WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar()
    assert first["prompt_version"] == second["prompt_version"] == 1
    assert second["regenerated"] is False
    assert versions == 1


async def test_regenerating_replaces_the_facts_and_keeps_the_hand_written_sections() -> None:
    """PROMPT-GUIDE §2: [T0 FACTS] is "auto-generated — do not hand-edit; regenerate".
    Regenerating must therefore replace that block and nothing else — a guardrail an
    operator wrote by hand is not the compiler's to delete."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=(
                "[IDENTITY] Sunrise Dental receptionist.\n"
                f"{t0.T0_HEADER}\nHours: closed on Mondays\n"
                "[GUARDRAILS] Never quote a treatment plan over the phone.\n"
            ),
            notes="hand written",
            created_by=None,
        )
        result = await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        body = (
            await session.execute(
                text("SELECT body FROM prompt_versions WHERE agent_id = :aid AND version = :v"),
                {"aid": agent_id, "v": result["prompt_version"]},
            )
        ).scalar()
    assert result["regenerated"] is True and result["prompt_version"] == 2
    assert "closed on Mondays" not in body, "the stale block is replaced, not appended to"
    assert "Never quote a treatment plan" in body, "hand-written sections survive"
    assert "[IDENTITY] Sunrise Dental receptionist." in body
    assert body.index(t0.T0_HEADER) < body.index("[GUARDRAILS]"), "section order held"


async def test_the_intake_seeds_the_knowledge_base_awaiting_approval() -> None:
    """ "Output feeds ... KB seed" — but through the same approval gate as any other
    source (FLOWS §7, D-28). Auto-approving our own seed would be the one upload nobody
    ever looked at."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        result = await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        row = (
            await session.execute(
                text(
                    "SELECT s.status, s.kind, s.approved_at, d.content FROM kb_sources s "
                    "JOIN kb_documents d ON d.source_id = s.id AND d.idx = 0 WHERE s.id = :sid"
                ),
                {"sid": result["kb_source_id"]},
            )
        ).first()
    assert row is not None
    status, kind, approved_at, content = row
    assert (status, kind) == ("pending_approval", "text")
    assert approved_at is None, "a seeded source is not a published source"
    assert "Root canal" in content


async def test_the_intake_of_one_tenant_cannot_be_written_onto_another_s_agent() -> None:
    """RLS is the isolation, and the failure is a clean 404 rather than a write that
    silently lands nowhere."""
    tenant_id, _ = await _tenant()
    _, other_agent = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as caught:
            await intake.record_intake(
                session, tenant_id=tenant_id, agent_id=other_agent, facts=FACTS, recorded_by=None
            )
    assert caught.value.status == 404


async def test_the_intake_route_names_its_tenant_in_the_path() -> None:
    """An admin-realm mutation that infers its tenant from the session is un-callable
    (D-22) — the rule `tests/route_shape_test.py` generalises. Asserted here too so the
    new route is pinned to the house pattern at the point it was added."""
    routes = [r for r in iter_api_routes(app) if r.path.endswith("/intake")]
    assert routes, "the wizard's intake step has a route"
    for route in routes:
        assert route.path.startswith("/v1/admin/tenants/{tenant_id}/")


async def test_what_the_wizard_can_reopen_is_what_is_durably_stored() -> None:
    """Resume-anytime (FLOWS §1) is only as good as what comes back: the structured
    facts round-trip from the columns that already read them, and the prose ones from
    the answer sheet on `organizations.intake`."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        stored = await intake.read_intake(session, agent_id=agent_id)

    assert stored["business_hours"]["mon"] == {"opens": "09:30", "closes": "18:00"}
    assert stored["escalation_contacts"][0]["name"] == "Reception"
    assert stored["languages"] == ["en-IN"]
    assert stored["compiled_t0_context"] and "Root canal" in stored["compiled_t0_context"]


async def test_reopening_the_step_gives_back_the_fields_not_just_the_compiled_block() -> None:
    """The gap this wave closes. The prose answers — branches, services, FAQs, staff
    pronunciations, booking rules — used to survive only as the [T0 FACTS] block and a
    KB source, so reopening the step could repopulate the structured half of the form
    and not the half an operator spent an afternoon typing. A form that cannot show
    what was typed into it is a form that gets retyped.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await intake.record_intake(
            session, tenant_id=tenant_id, agent_id=agent_id, facts=FACTS, recorded_by=None
        )
        stored = await intake.read_intake(session, agent_id=agent_id)

    prose = stored["prose_answers"]
    assert prose is not None, "the raw answers have a durable home"
    assert prose["branches"][0]["address"] == "12 MG Road, Ameerpet, Hyderabad 500016"
    assert [s["name"] for s in prose["services"]] == ["Root canal", "Cleaning"]
    assert prose["services"][1]["notes"] == "30 minutes", "a per-service note survives"
    assert prose["faqs"][0]["question"] == "Do you take insurance?"
    assert prose["staff"][0]["pronunciation"] == "సౌమ్య", "the field, not the sentence"
    assert prose["booking_rules"] == FACTS.booking_rules


# ------------------------------------------------- campaign list: provenance flag


async def _draft(
    session: Any, *, tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, source: str | None
) -> uuid.UUID:
    return await campaigns_service.create_campaign(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name=name,
        classification="service",
        number_id=None,
        dlt_template_id=None,
        concurrency=1,
        consent_source=source,
        consent_collected_at=(
            datetime.now(UTC) - timedelta(days=10) if source is not None else None
        ),
    )


async def test_the_list_says_which_drafts_need_provenance_without_running_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gap the campaigns screen recorded in its own source: the summary carried
    `status` and nothing about consent, so the list either warned about every draft or
    ran the full launch gate once per row.

    `launch_blockers` is sabotaged for the duration: if the answer needs the gate, this
    test fails rather than quietly costing one round trip per campaign.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        unanswered = await _draft(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Unanswered", source=None
        )
        answered = await _draft(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Answered",
            source="web_form_optin",
        )
        purchased = await _draft(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Purchased",
            source="purchased_list",
        )

        def _no_gate(*args: object, **kwargs: object) -> None:
            raise AssertionError("the list must answer from its own query, not the gate")

        monkeypatch.setattr(campaigns_service, "launch_blockers", _no_gate)
        rows = {r["name"]: r for r in await campaigns_service.list_campaigns(session)}

    assert rows["Unanswered"]["consent_provenance_blocker"] == "consent_provenance_missing"
    assert rows["Answered"]["consent_provenance_blocker"] is None
    assert rows["Purchased"]["consent_provenance_blocker"] == "consent_source_refused"
    assert {unanswered, answered, purchased} == {r["id"] for r in rows.values()}


async def test_the_flag_carries_the_gate_s_own_rule_names() -> None:
    """The value is the blocker's `rule`, not a private vocabulary: the list links to
    the same explanation the launch check renders, and a third name for the same fact
    is how the two screens start disagreeing."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await _draft(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Unanswered", source=None
        )
        await _draft(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Purchased",
            source="purchased_list",
        )
        rows = {r["name"]: r for r in await campaigns_service.list_campaigns(session)}
        gate = {
            name: [
                b.rule
                for b in await campaigns_service.launch_blockers(
                    session, tenant_id=tenant_id, campaign_id=row["id"]
                )
            ]
            for name, row in rows.items()
        }

    for name, row in rows.items():
        assert row["consent_provenance_blocker"] in gate[name], name


async def test_a_campaign_past_the_gate_is_not_flagged_for_something_it_cannot_fix() -> None:
    """Provenance is answerable while a campaign is a draft and never afterwards
    (`declare_consent_provenance`). Flagging a running campaign that predates the
    columns would put a to-do on the list with no way to do it."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = await _draft(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Already out", source=None
        )
        # Straight to `running` on purpose: this is the pre-migration campaign the
        # column was added underneath, not a campaign that passed today's gate.
        await session.execute(
            text("UPDATE campaigns SET status = 'running', launched_at = now() WHERE id = :cid"),
            {"cid": campaign_id},
        )
        rows = await campaigns_service.list_campaigns(session)

    assert rows[0]["status"] == "running"
    assert rows[0]["consent_provenance_blocker"] is None
