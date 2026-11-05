"""Per-agent judgement of whether callers follow along on their phone (founder, 5 Nov 2026).

The screen guide (D-906) and "Give callers time" (D-907) are suggested from what one agent
does: its script, its small steps and its campaigns. The model is a stub here; what is tested
is what the pass reads, how it cleans an answer, when it runs, what it costs, and what the
owner's routes answer.
"""

from __future__ import annotations

import copy as copylib
import dataclasses
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import caller_help, patient_caller, script_builder
from apps.api.billing import rates
from apps.api.billing.models import (
    ABSORBED_ASSIST_FEATURES,
    ASSIST_FEATURE_CALLER_HELP,
    ASSIST_FEATURE_CALLER_HELP_ABSORBED,
)
from apps.api.campaigns import service as campaigns_service
from apps.api.copilot.agent_setup_actions import screen_guide_hint
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import caller_help as passer
from apps.workers import chat, script_assist
from apps.workers.extraction import GOOGLE_PROVIDER, AssistCapability
from apps.workers.settings import WorkerSettings
from calevate_shared.call_script import CallScript, ConversationStage, ProcedureStep
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

MODEL = "gemini-3.1-flash-lite"
INSTALL_REASON = "She walks farmers through installing the app step by step."

GUIDED = CallScript(
    schema_version=2,
    identity="You are Varsha, calling farmers who signed up for the ledger app.",
    goal="Get the farmer to install the app and add their first entry.",
    stages=[
        ConversationStage(
            id="install",
            name="Install the app",
            instruction="Help the farmer install the app on their phone.",
            procedure=[
                ProcedureStep(action="Ask them to open the Play Store", wait_for="they see it"),
                ProcedureStep(action="Ask them to search for the app and tap Install"),
            ],
        )
    ],
)
RECEPTIONIST = CallScript(
    schema_version=2,
    identity="You answer calls for a grocery shop.",
    goal="Answer questions about stock and take orders for delivery.",
)


@pytest.fixture(autouse=True)
def _priced() -> Iterator[None]:
    rates.install_llm_price_attestations(
        lambda: {
            MODEL: rates.LlmPriceAttestation(
                model=MODEL,
                input_usd_per_mtok=Decimal("0.25"),
                output_usd_per_mtok=Decimal("1.50"),
                read_on=date(2026, 10, 18),
                attested_by="founder",
                source="test fixture",
            )
        }
    )
    yield
    rates.install_llm_price_attestations(None)


class _Model:
    """Says yes to both when the agent's own words walk the caller through installing
    something, no otherwise: enough to see the pass carry the script to the model."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, description: str, instruction: str, **kw: Any) -> Any:
        self.calls.append({"description": description, "instruction": instruction, **kw})
        guided = "Small step" in description and "install" in description.lower()
        yes = {"suggested": True, "reason": INSTALL_REASON}
        no = {"suggested": False, "reason": ""}
        raw = {"screen_guide": yes if guided else no, "give_time": yes if guided else no}
        return script_assist.JsonAnswer(
            value=kw["parse"](copylib.deepcopy(raw)),
            capability=AssistCapability(available=True, provider=GOOGLE_PROVIDER),
            usage=chat.TokenUsage(prompt_tokens=900, output_tokens=60),
            model=MODEL,
        )


@dataclasses.dataclass
class _Leg:
    serves_dashboard: bool = True


def _setup(monkeypatch: pytest.MonkeyPatch, *, trial: bool) -> _Model:
    model = _Model()

    async def _active(session: Any, *, tenant_id: Any, at: Any = None) -> bool:
        return trial

    monkeypatch.setattr(passer, "trial_billing_active", _active)
    monkeypatch.setattr(passer, "ask_json", model)
    monkeypatch.setattr(passer, "google_assist_leg", _Leg)
    return model


async def _scalar(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).scalar()


async def _agent() -> tuple[UUID, str, str, UUID]:
    tenant_id, slug, token = await _make_tenant()
    agent_id = UUID(str(await _scalar(tenant_id, "SELECT id FROM agents LIMIT 1")))
    return tenant_id, slug, token, agent_id


async def _save(tenant_id: UUID, agent_id: UUID, script: CallScript) -> None:
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script,
            notes=None,
            created_by=None,
        )


async def _jobs(agent_id: UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'agent_id' = :a"
                    ),
                    {"job": caller_help.JOB, "a": str(agent_id)},
                )
            ).scalar()
            or 0
        )


async def _pass(tenant_id: UUID, agent_id: UUID) -> str:
    return await passer.judge_caller_help(
        {}, {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    )


async def _http(method: str, path: str, token: str, slug: str) -> Any:
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.request(method, path, headers=headers)


async def _features(tenant_id: UUID) -> set[str]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT meta->>'feature' FROM usage_events "
                "WHERE tenant_id = :t AND unit_type LIKE 'ai_assist%'"
            ),
            {"t": tenant_id},
        )
        return {str(r[0]) for r in rows.all()}


# --- cleaning the model's answer -------------------------------------------------------------


def test_a_screen_guided_agent_is_always_given_time_too() -> None:
    got = passer.judgement_from_model(
        {
            "screen_guide": {"suggested": True, "reason": INSTALL_REASON},
            "give_time": {"suggested": False, "reason": ""},
        }
    )
    assert got is not None
    assert got.give_time.suggested and got.give_time.reason == INSTALL_REASON


def test_an_answer_the_owner_cannot_be_given_is_no_answer() -> None:
    no = {"suggested": False, "reason": ""}
    for bad in (
        {"screen_guide": {"suggested": True, "reason": "  "}, "give_time": no},
        {"screen_guide": {"suggested": True, "reason": "Uses Gemini to help."}, "give_time": no},
        {"screen_guide": {"suggested": "yes", "reason": "x"}, "give_time": no},
        {"screen_guide": no},
    ):
        assert passer.judgement_from_model(bad) is None, bad
    neither = passer.judgement_from_model({"screen_guide": no, "give_time": no})
    assert neither is not None and not neither.screen_guide.suggested


def test_the_small_steps_reach_the_model() -> None:
    said = passer.agent_script_text(GUIDED.model_dump(mode="json"))
    assert "Small step in 'Install the app': Ask them to open the Play Store" in said
    assert "(done when: they see it)" in said


# --- the pass, end to end --------------------------------------------------------------------


async def test_an_agent_that_walks_callers_through_their_phone_gets_both_with_a_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _setup(monkeypatch, trial=False)
    tenant_id, slug, token, agent_id = await _agent()
    await _save(tenant_id, agent_id, GUIDED)
    assert await _jobs(agent_id) == 1, "a script save queues the judgement"
    async with tenant_session(tenant_id) as session:
        await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Onboarding",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
            purpose="Help new farmers set up the app",
            goal="First entry added",
        )
    assert await _pass(tenant_id, agent_id) == "stored"
    sent = model.calls[0]
    assert "Small step in 'Install the app'" in sent["description"]
    assert (
        "Campaign 'Onboarding': why it calls: Help new farmers set up the app"
        in (sent["description"])
    )
    assert sent["gemini_only"] is True and sent["health_leg"] == "caller_help"
    assert await _features(tenant_id) == {ASSIST_FEATURE_CALLER_HELP}
    assert ASSIST_FEATURE_CALLER_HELP not in ABSORBED_ASSIST_FEATURES

    got = await _http("GET", f"/v1/agents/{agent_id}/caller-help", token, slug)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["state"] == "done"
    for item in ("screen_guide", "give_time"):
        assert body[item] == {
            "suggested": True,
            "reason": INSTALL_REASON,
            "on": False,
            "dismissed": False,
            "ask": True,
        }


async def test_a_plain_receptionist_gets_neither(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, trial=True)
    tenant_id, slug, token, agent_id = await _agent()
    await _save(tenant_id, agent_id, RECEPTIONIST)
    assert await _pass(tenant_id, agent_id) == "stored"
    assert await _features(tenant_id) == {ASSIST_FEATURE_CALLER_HELP_ABSORBED}, "a trial's is ours"
    assert ASSIST_FEATURE_CALLER_HELP_ABSORBED in ABSORBED_ASSIST_FEATURES
    body = (await _http("GET", f"/v1/agents/{agent_id}/caller-help", token, slug)).json()
    assert not body["screen_guide"]["suggested"] and not body["give_time"]["suggested"]
    assert not body["screen_guide"]["ask"] and not body["give_time"]["ask"]
    assert body["screen_guide"]["reason"] == ""


async def test_an_agent_with_nothing_of_its_own_is_not_asked_about_at_any_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _setup(monkeypatch, trial=False)
    tenant_id, slug, token, agent_id = await _agent()
    await _scalar(
        tenant_id,
        "UPDATE agents SET system_prompt_id = NULL, live_prompt_id = NULL WHERE id = :a "
        "RETURNING id",
        a=agent_id,
    )
    first = (await _http("GET", f"/v1/agents/{agent_id}/caller-help", token, slug)).json()
    assert first["state"] == "queued", "an agent never judged is queued on its first read"
    assert await _pass(tenant_id, agent_id) == "nothing_to_judge"
    assert model.calls == [] and await _features(tenant_id) == set()
    again = (await _http("GET", f"/v1/agents/{agent_id}/caller-help", token, slug)).json()
    assert again["state"] == "done" and not again["give_time"]["suggested"]


async def test_a_script_change_judges_again_and_an_unchanged_one_spends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _setup(monkeypatch, trial=False)
    tenant_id, slug, token, agent_id = await _agent()
    await _save(tenant_id, agent_id, RECEPTIONIST)
    assert await _pass(tenant_id, agent_id) == "stored"
    async with tenant_session(tenant_id) as session:
        await caller_help.queue_pass(session, tenant_id=tenant_id, agent_id=agent_id)
    assert await _pass(tenant_id, agent_id) == "unchanged"
    assert len(model.calls) == 1

    before = await _jobs(agent_id)
    await _save(tenant_id, agent_id, GUIDED)
    assert await _jobs(agent_id) == before + 1
    assert (
        await _scalar(tenant_id, "SELECT caller_help_state FROM agents WHERE id = :a", a=agent_id)
        == "queued"
    )
    assert await _pass(tenant_id, agent_id) == "stored"
    body = (await _http("GET", f"/v1/agents/{agent_id}/caller-help", token, slug)).json()
    assert body["screen_guide"]["ask"] and body["give_time"]["ask"]


async def test_not_now_sticks_and_the_settings_still_say_suggested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch, trial=False)
    tenant_id, slug, token, agent_id = await _agent()
    await _save(tenant_id, agent_id, GUIDED)
    assert await _pass(tenant_id, agent_id) == "stored"
    base = f"/v1/agents/{agent_id}/caller-help"
    answered = await _http("POST", f"{base}/dismiss", token, slug)
    assert answered.status_code == 200, answered.text
    body = answered.json()
    for item in ("screen_guide", "give_time"):
        assert body[item]["suggested"] and body[item]["dismissed"] and not body[item]["ask"]
    assert (
        await _scalar(
            tenant_id,
            "SELECT count(*) FROM audit_log WHERE action = 'agent.caller_help_dismissed' "
            "AND object_id = :a",
            a=str(agent_id),
        )
        == 1
    )
    # A later judgement of a changed script does not ask again.
    async with tenant_session(tenant_id) as session:
        await caller_help.queue_pass(session, tenant_id=tenant_id, agent_id=agent_id, force=True)
    assert await _pass(tenant_id, agent_id) == "stored"
    body = (await _http("GET", base, token, slug)).json()
    assert body["screen_guide"]["dismissed"] and not body["screen_guide"]["ask"]
    assert (await _http("POST", f"{base}/dismiss", token, slug)).status_code == 200
    assert (
        await _scalar(
            tenant_id,
            "SELECT count(*) FROM audit_log WHERE action = 'agent.caller_help_dismissed' "
            "AND object_id = :a",
            a=str(agent_id),
        )
        == 1
    ), "nothing asked, nothing dismissed, nothing audited"


async def test_a_setting_turned_on_is_no_longer_asked_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch, trial=False)
    tenant_id, slug, token, agent_id = await _agent()
    await _save(tenant_id, agent_id, GUIDED)
    assert await _pass(tenant_id, agent_id) == "stored"
    async with tenant_session(tenant_id) as session:
        await patient_caller.apply_patient_caller(session, tenant_id=tenant_id, agent_id=agent_id)
    body = (await _http("GET", f"/v1/agents/{agent_id}/caller-help", token, slug)).json()
    assert body["give_time"]["on"] and not body["give_time"]["ask"]
    assert body["screen_guide"]["ask"], "the other is still asked about"


async def test_pip_follows_the_agents_own_judgement_over_the_words() -> None:
    tenant_id, _slug, _token, agent_id = await _agent()
    judged = caller_help.CallerHelp(
        screen_guide=caller_help.Judgement(suggested=True, reason=INSTALL_REASON),
        give_time=caller_help.Judgement(suggested=True, reason=INSTALL_REASON),
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_help = CAST(:j AS jsonb) WHERE id = :a"),
            {"j": judged.model_dump_json(), "a": agent_id},
        )
        hint = await screen_guide_hint(session, agent_id, "Winter recall")
    assert "switch on the agent's caller_has_screen" in hint


def test_the_job_is_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert caller_help.JOB in names and passer.JOB_NAME == caller_help.JOB
