"""D-836: each agent's own call outcomes, beside the system-fact outcome.

The founder's 20 Oct 2026 call (a caller asked to buy 2 kg of chilli delivered to Guntur) read
"No outcome". These pin: the model's word for a hint is read however it is spelled; the
agent's outcomes reach the prompt and the strict schema; the model's choice lands on the call
with its label and moves the lead through the ladder; the one AI draft is queued once, billed
like the D-827 copy and never overwrites the owner's list; and the owner's routes.
"""

from __future__ import annotations

import copy as copylib
import json
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import call_outcomes
from apps.api.billing import rates
from apps.api.billing.models import (
    ABSORBED_ASSIST_FEATURES,
    ASSIST_FEATURE_BUSINESS_OUTCOMES,
    ASSIST_FEATURE_BUSINESS_OUTCOMES_ABSORBED,
)
from apps.api.core.errors import ProblemError
from apps.api.crm.outcomes import hint_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import business_outcomes_draft as drafter
from apps.workers import chat, script_assist
from apps.workers import extraction as extraction_module
from apps.workers.extraction import (
    GOOGLE_PROVIDER,
    AssistCapability,
    build_response_schema,
    extract_call,
)
from apps.workers.pipeline import after_call_status
from apps.workers.settings import WorkerSettings
from calevate_shared.business_outcomes import (
    MAX_BUSINESS_OUTCOMES,
    STARTING_OUTCOMES,
    BusinessOutcome,
    match_outcome,
    outcome_key,
    outcome_problems,
)
from calevate_shared.extraction import ExtractionSchemaSpec, build_extraction_prompt
from calevate_shared.lead_fields import OUTPUT_KEYS
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _scalar
from tests.pipeline_audit_test import _stub_storage as _stub_storage

SHOP: tuple[BusinessOutcome, ...] = (
    BusinessOutcome(
        key="wants_to_buy",
        label="Wants to buy",
        meaning="The caller wants to order chilli or chilli powder.",
        lead_status="interested",
    ),
    BusinessOutcome(key="asked_price_only", label="Asked price only", lead_status="contacted"),
    BusinessOutcome(key="ready_to_pay", label="Ready to pay now", lead_status="hot"),
)
SPEC = ExtractionSchemaSpec(fields=[])
MODEL = "gemini-3.1-flash-lite"


# --- 1. the vocabulary ------------------------------------------------------------------


def test_a_hint_is_read_however_the_model_spells_it() -> None:
    """One path to a NULL outcome (20 Oct 2026): a hint written as a person would write it
    was dropped as unknown."""
    assert hint_of("Needs you") == "needs_you"
    assert hint_of("needs-you") == "needs_you"
    assert hint_of(" HUNG UP EARLY ") == "hung_up_early"
    assert hint_of("wants to buy") is None


def test_the_starting_set_names_a_buyer_and_an_interested_caller_and_no_trade() -> None:
    moves = {o.key: o.lead_status for o in STARTING_OUTCOMES}
    assert moves["wants_to_buy"] == "interested" and moves["interested"] == "interested"
    words = " ".join(f"{o.label} {o.meaning}" for o in STARTING_OUTCOMES).lower()
    for clinic in ("patient", "doctor", "clinic", "appointment", "symptom"):
        assert clinic not in words
    assert not outcome_problems(STARTING_OUTCOMES)


def test_a_business_outcome_can_never_spell_a_system_one() -> None:
    with pytest.raises(ValueError):
        BusinessOutcome(key="missed", label="Missed")
    assert outcome_key("Missed", ()) == "missed_2"
    assert outcome_key("Wants to buy!", {"wants_to_buy"}) == "wants_to_buy_2"
    assert outcome_key("123", ()) is None


def test_the_list_is_bounded_and_its_names_distinct() -> None:
    many = [BusinessOutcome(key=f"k{i}", label=f"Outcome {i}") for i in range(9)]
    assert outcome_problems(many) == [f"An agent has at most {MAX_BUSINESS_OUTCOMES} outcomes."]
    twins = [BusinessOutcome(key="a", label="Wants"), BusinessOutcome(key="b", label="wants")]
    assert outcome_problems(twins) == ["Two outcomes have the same name."]


def test_the_models_answer_matches_by_key_or_by_label_and_nothing_else() -> None:
    assert match_outcome("wants_to_buy", SHOP) == SHOP[0]
    assert match_outcome("Wants to buy", SHOP) == SHOP[0]
    assert match_outcome("asked-price-only", SHOP) == SHOP[1]
    assert match_outcome("interested", SHOP) is None
    assert match_outcome(None, SHOP) is None


def test_no_lead_field_may_be_called_business_outcome() -> None:
    assert "business_outcome" in OUTPUT_KEYS


# --- 2. the extraction ------------------------------------------------------------------


def test_the_prompt_lists_the_agents_outcomes_and_is_unchanged_without_them() -> None:
    plain = build_extraction_prompt(SPEC, "caller: 2 kg chilli kavali")
    assert "business_outcome" not in plain
    offered = build_extraction_prompt(SPEC, "caller: 2 kg chilli kavali", outcomes=SHOP)
    assert '"business_outcome"' in offered
    assert "wants_to_buy" in offered and "The caller wants to order chilli" in offered
    section = offered[offered.index('- "business_outcome"') : offered.index('- "out_of_scope"')]
    assert offered.replace(section, "") == plain, (
        "the outcomes add one block and change nothing else"
    )


def test_the_strict_schema_offers_the_keys_and_null() -> None:
    schema = build_response_schema(SPEC, outcomes=SHOP)
    assert schema["properties"]["business_outcome"] == {
        "type": ["string", "null"],
        "enum": ["wants_to_buy", "asked_price_only", "ready_to_pay", None],
    }
    assert "business_outcome" in schema["required"]
    assert "business_outcome" not in build_response_schema(SPEC)["properties"]


class _Runner:
    """A model runner that reads the outcomes and answers with `answer`."""

    model_name = "fake-model"
    reads_outcomes = True

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.offered: Sequence[BusinessOutcome] = ()

    async def run(
        self,
        spec: ExtractionSchemaSpec,
        transcript: str,
        *,
        outcomes: Sequence[BusinessOutcome] = (),
    ) -> dict[str, Any]:
        self.offered = outcomes
        return dict(self.answer)


async def test_extraction_keeps_only_a_choice_it_offered() -> None:
    runner = _Runner(
        {"summary": "s", "outcome_tag": "answered", "business_outcome": "Wants to buy"}
    )
    out = await extract_call(SPEC, "caller: chilli", extractor=runner, outcomes=SHOP)
    assert out.business_outcome == "wants_to_buy" and runner.offered == SHOP
    runner.answer["business_outcome"] = "bought a car"
    assert (
        await extract_call(SPEC, "caller: x", extractor=runner, outcomes=SHOP)
    ).business_outcome is None


def test_a_business_outcome_moves_the_lead_up_and_never_down() -> None:
    assert (
        after_call_status(
            outcome="answered",
            connected=True,
            callback_requested=False,
            sentiment="neutral",
            business_move="interested",
        )
        == "interested"
    )
    assert (
        after_call_status(
            outcome="answered",
            connected=True,
            callback_requested=True,
            sentiment="neutral",
            business_move="contacted",
        )
        == "interested"
    ), "a lower business move never undoes a higher rule"
    assert (
        after_call_status(
            outcome="missed",
            connected=False,
            callback_requested=False,
            sentiment=None,
            business_move="hot",
        )
        is None
    ), "a call that did not connect moves nothing"


# --- 3. the pipeline --------------------------------------------------------------------


async def test_a_buying_call_reads_as_the_agents_outcome_and_moves_the_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 20 Oct call: the agent had no outcomes of its own yet, so the starting set is
    offered, the model picks "wants to buy", the call shows it, and the lead is Interested.
    The agent's one draft is queued by that first call."""
    runner = _Runner(
        {
            "summary": "Asked for 2 kg of dried chilli delivered to Guntur.",
            "outcome_tag": "answered",
            "business_outcome": "wants_to_buy",
            "sentiment": "neutral",
        }
    )
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: runner)
    tenant_id, execution_id, call_id = await _completed_call("buyer")
    await _run_pipeline(tenant_id, call_id, execution_id)

    assert [o.key for o in runner.offered] == [o.key for o in STARTING_OUTCOMES]
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.business_outcome, c.business_outcome_label, c.outcome_tag, "
                    "l.status, a.business_outcomes_draft, ce.business_outcome "
                    "FROM calls c JOIN leads l ON l.id = c.lead_id "
                    "JOIN agents a ON a.id = c.agent_id "
                    "JOIN call_extractions ce ON ce.call_id = c.id WHERE c.id = :c"
                ),
                {"c": call_id},
            )
        ).one()
    assert row[0] == row[5] == "wants_to_buy" and row[1] == "Wants to buy or book"
    assert row[2] == "answered", "the system-fact outcome is kept beside it"
    assert row[3] in ("interested", "hot")
    assert row[4] == "queued"
    agent_id = await _scalar(tenant_id, "SELECT agent_id FROM calls WHERE id = :c", c=call_id)
    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'agent_id' = :aid"
                ),
                {"job": call_outcomes.DRAFT_JOB, "aid": str(agent_id)},
            )
        ).scalar()
    assert queued == 1

    # A re-drive reuses the stored choice and queues nothing more.
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert (
        await _scalar(tenant_id, "SELECT business_outcome FROM calls WHERE id = :c", c=call_id)
        == "wants_to_buy"
    )
    async with untenanted_session() as session:
        again = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'agent_id' = :aid"
                ),
                {"job": call_outcomes.DRAFT_JOB, "aid": str(agent_id)},
            )
        ).scalar()
    assert again == 1


# --- 4. the one AI draft ----------------------------------------------------------------


def _drafted() -> dict[str, Any]:
    return {
        "outcomes": [
            {"label": "Wants to buy", "meaning": "Wants chilli.", "lead_status": "interested"},
            {
                "label": "Asked price only",
                "meaning": "Only asked a price.",
                "lead_status": "contacted",
            },
            {"label": "Missed", "meaning": "A system word.", "lead_status": "contacted"},
            {"label": "wants to buy", "meaning": "A repeat.", "lead_status": "hot"},
            {"label": "Ready to pay", "meaning": "Pays now.", "lead_status": "won"},
        ]
    }


def test_the_draft_keeps_only_usable_outcomes() -> None:
    kept = drafter.outcomes_from_model(_drafted())
    assert [(o.key, o.lead_status) for o in kept] == [
        ("wants_to_buy", "interested"),
        ("asked_price_only", "contacted"),
    ], "a system word, a repeated name and a won/lost move are all dropped"


class _Model:
    def __init__(self, *, fail: ProblemError | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def __call__(self, description: str, instruction: str, **kw: Any) -> Any:
        self.calls.append({"description": description, "instruction": instruction, **kw})
        if self.fail is not None:
            raise self.fail
        return script_assist.JsonAnswer(
            value=kw["parse"](copylib.deepcopy(_drafted())),
            capability=AssistCapability(available=True, provider=GOOGLE_PROVIDER),
            usage=chat.TokenUsage(prompt_tokens=2_000, output_tokens=300),
            model=MODEL,
        )


@pytest.fixture(autouse=True)
def _priced() -> Iterator[None]:
    """The draft's model priced from an attestation, as hard rule 7 requires to meter it."""
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


def _trial(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    async def _active(session: Any, *, tenant_id: Any, at: Any = None) -> bool:
        return on

    monkeypatch.setattr(drafter, "trial_billing_active", _active)


async def _agent_of(tenant_id: UUID) -> UUID:
    return UUID(str(await _scalar(tenant_id, "SELECT id FROM agents LIMIT 1")))


async def _queue(tenant_id: UUID, agent_id: UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        return await call_outcomes.queue_draft(session, tenant_id=tenant_id, agent_id=agent_id)


async def _draft(tenant_id: UUID, agent_id: UUID) -> str:
    return await drafter.draft_business_outcomes(
        {}, {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    )


async def _agent_row(tenant_id: UUID, agent_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT business_outcomes, business_outcomes_draft FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).one()


async def _features(tenant_id: UUID) -> set[str]:
    async with tenant_session(tenant_id) as session:
        return {
            str(r[0])
            for r in (
                await session.execute(
                    text(
                        "SELECT meta->>'feature' FROM usage_events "
                        "WHERE tenant_id = :t AND unit_type LIKE 'ai_assist%'"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        }


async def test_the_draft_is_queued_once_and_stored_on_the_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _Model()
    monkeypatch.setattr(drafter, "ask_json", model)
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    assert await _queue(tenant_id, agent_id) is True
    assert await _queue(tenant_id, agent_id) is False, "once per agent"

    assert await _draft(tenant_id, agent_id) == "stored"
    stored, state = await _agent_row(tenant_id, agent_id)
    assert state == "done" and [o["key"] for o in stored] == ["wants_to_buy", "asked_price_only"]
    assert "Business name:" in model.calls[0]["description"]
    assert "never propose them" in model.calls[0]["instruction"]
    assert model.calls[0]["health_leg"] == "business_outcomes"
    assert await _features(tenant_id) == {ASSIST_FEATURE_BUSINESS_OUTCOMES}
    assert ASSIST_FEATURE_BUSINESS_OUTCOMES not in ABSORBED_ASSIST_FEATURES
    assert await _draft(tenant_id, agent_id) == "not_queued", "never drafted twice"
    assert await _queue(tenant_id, agent_id) is False


async def test_a_trials_draft_is_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drafter, "ask_json", _Model())
    _trial(monkeypatch, True)
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _queue(tenant_id, agent_id)
    assert await _draft(tenant_id, agent_id) == "stored"
    assert await _features(tenant_id) == {ASSIST_FEATURE_BUSINESS_OUTCOMES_ABSORBED}
    assert ASSIST_FEATURE_BUSINESS_OUTCOMES_ABSORBED in ABSORBED_ASSIST_FEATURES


async def test_a_used_up_allowance_skips_the_draft_and_spends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _Model()
    monkeypatch.setattr(drafter, "ask_json", model)
    _trial(monkeypatch, False)

    async def _ceiling(session: Any, *, tenant_id: Any) -> None:
        raise ProblemError.business_rule("ai_quota_exceeded", "used up")

    monkeypatch.setattr(drafter, "require_ai_assist", _ceiling)
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _queue(tenant_id, agent_id)
    assert await _draft(tenant_id, agent_id) == "skipped"
    assert tuple(await _agent_row(tenant_id, agent_id)) == (None, "skipped")
    assert model.calls == []


async def test_the_owners_list_wins_over_a_draft_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drafter, "ask_json", _Model())
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _queue(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await call_outcomes.save_outcomes(
            session,
            agent_id=agent_id,
            items=[call_outcomes.OutcomeDraft(None, "Booked a pickup", "", "interested")],
        )
    assert await _draft(tenant_id, agent_id) == "kept_own"
    stored, state = await _agent_row(tenant_id, agent_id)
    assert [o["label"] for o in stored] == ["Booked a pickup"] and state == "done"


async def test_a_failed_draft_is_recorded_and_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        drafter, "ask_json", _Model(fail=ProblemError.business_rule("ai_unavailable", "down"))
    )
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _queue(tenant_id, agent_id)
    assert await _draft(tenant_id, agent_id) == "failed"
    assert tuple(await _agent_row(tenant_id, agent_id)) == (None, "failed")
    assert await _queue(tenant_id, agent_id) is False


def test_the_draft_job_is_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert drafter.JOB_NAME == call_outcomes.DRAFT_JOB
    assert drafter.JOB_NAME in names


# --- 5. the owner's routes --------------------------------------------------------------


async def _http(method: str, path: str, token: str, slug: str, body: Any = None) -> Any:
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.request(method, path, headers=headers, json=body)


async def test_the_owner_reads_the_starting_set_and_saves_their_own() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    got = await _http("GET", "/v1/call-outcomes", token, slug)
    assert got.status_code == 200, got.text
    agent = got.json()["agents"][0]
    assert agent["starting"] is True and agent["draft"] is None
    assert [o["key"] for o in agent["outcomes"]] == [o.key for o in STARTING_OUTCOMES]

    body = {
        "outcomes": [
            {"key": "wants_to_buy", "label": "Wants to buy", "meaning": "", "lead_status": "hot"},
            {"label": "Asked price only", "meaning": "Only a price.", "lead_status": "contacted"},
        ]
    }
    put = await _http("PUT", f"/v1/agents/{agent_id}/call-outcomes", token, slug, body)
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["starting"] is False
    assert [(o["key"], o["lead_status"]) for o in saved["outcomes"]] == [
        ("wants_to_buy", "hot"),
        ("asked_price_only", "contacted"),
    ]
    stored = await _scalar(
        tenant_id, "SELECT business_outcomes FROM agents WHERE id = :a", a=agent_id
    )
    assert json.loads(json.dumps(stored))[1]["label"] == "Asked price only"


async def test_two_outcomes_with_one_name_are_refused() -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    body = {"outcomes": [{"label": "Wants"}, {"label": "wants"}]}
    put = await _http("PUT", f"/v1/agents/{agent_id}/call-outcomes", token, slug, body)
    assert put.status_code == 422 and put.json()["type"].endswith("/call_outcomes_invalid")


async def test_staff_cannot_change_them_and_nobody_reaches_another_accounts_agent() -> None:
    _mine, slug, staff = await _make_tenant(role="staff")
    theirs, _s, _t = await _make_tenant()
    their_agent = await _agent_of(theirs)
    body = {"outcomes": [{"label": "Wants to buy"}]}
    refused = await _http("PUT", f"/v1/agents/{their_agent}/call-outcomes", staff, slug, body)
    assert refused.status_code == 403
    _owner_tenant, owner_slug, owner = await _make_tenant()
    hidden = await _http("PUT", f"/v1/agents/{their_agent}/call-outcomes", owner, owner_slug, body)
    assert hidden.status_code == 404
    assert (
        await _scalar(theirs, "SELECT business_outcomes FROM agents WHERE id = :a", a=their_agent)
        is None
    )


# --- 6. a draft that died, and "Write them for me" (D-841) -------------------------------


async def _outbox_drafts(agent_id: UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'agent_id' = :a"
                    ),
                    {"job": call_outcomes.DRAFT_JOB, "a": str(agent_id)},
                )
            ).scalar_one()
        )


def _route_trial(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    from apps.api.agents import call_outcomes_routes

    async def _active(session: Any, *, tenant_id: Any, at: Any = None) -> bool:
        return on

    monkeypatch.setattr(call_outcomes_routes, "trial_billing_active", _active)


async def test_a_draft_whose_worker_died_reads_failed_and_the_owner_can_ask_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_trial(monkeypatch, True)
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _queue(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        # The claim, then a worker killed before it wrote anything else.
        await session.execute(
            text("UPDATE agents SET business_outcomes_draft = 'running' WHERE id = :a"),
            {"a": agent_id},
        )
    got = await _http("GET", "/v1/call-outcomes", token, slug)
    assert got.json()["agents"][0]["draft"] == "running", "a run in progress is not dead"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET updated_at = now() - make_interval(mins => :m) WHERE id = :a"),
            {"a": agent_id, "m": call_outcomes.DRAFT_STALE_MINUTES + 1},
        )
    got = await _http("GET", "/v1/call-outcomes", token, slug)
    assert got.json()["agents"][0]["draft"] == "failed"

    before = await _outbox_drafts(agent_id)
    asked = await _http("POST", f"/v1/agents/{agent_id}/call-outcomes/draft", token, slug)
    assert asked.status_code == 202, asked.text
    assert asked.json()["draft"] == "queued"
    assert await _outbox_drafts(agent_id) == before + 1
    again = await _http("POST", f"/v1/agents/{agent_id}/call-outcomes/draft", token, slug)
    assert again.status_code == 202 and await _outbox_drafts(agent_id) == before + 1, (
        "a draft already queued is not queued twice"
    )


async def test_write_them_for_me_spends_the_allowance_and_is_refused_when_it_is_used_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.agents import call_outcomes_routes

    _route_trial(monkeypatch, False)

    async def _ceiling(session: Any, *, tenant_id: Any) -> None:
        raise ProblemError.business_rule("ai_quota_exceeded", "used up")

    monkeypatch.setattr(call_outcomes_routes, "require_ai_assist", _ceiling)
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    refused = await _http("POST", f"/v1/agents/{agent_id}/call-outcomes/draft", token, slug)
    assert refused.status_code == 422 and refused.json()["type"].endswith("/ai_quota_exceeded")
    assert await _outbox_drafts(agent_id) == 0


async def test_write_them_for_me_never_replaces_the_owners_own_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_trial(monkeypatch, True)
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    body = {"outcomes": [{"label": "Booked a pickup", "lead_status": "interested"}]}
    assert (
        await _http("PUT", f"/v1/agents/{agent_id}/call-outcomes", token, slug, body)
    ).is_success
    asked = await _http("POST", f"/v1/agents/{agent_id}/call-outcomes/draft", token, slug)
    assert asked.status_code == 409 and asked.json()["type"].endswith(
        "/call_outcomes_already_written"
    )
    assert await _outbox_drafts(agent_id) == 0
