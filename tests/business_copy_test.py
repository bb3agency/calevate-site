"""D-827: each client's AI-written examples and suggestions.

The shape and its text rules, the Gemini-only ladder, the job (inputs hash, allowance, trial
absorption, metering, failure), the row's tenancy and erasure, the starter lines that never
replace an owner's words, the routes and the wiring. The model is faked at `ask_json` or at
`chat.complete`; the database, the ledger and the outbox are real.
"""

from __future__ import annotations

import copy as copylib
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.agents import starters
from apps.api.billing import rates
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.billing.models import (
    ABSORBED_ASSIST_FEATURES,
    ASSIST_FEATURE_BUSINESS_COPY,
    ASSIST_FEATURE_BUSINESS_COPY_ABSORBED,
)
from apps.api.core import provider_health
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from apps.api.tenancy import business_copy
from apps.api.tenancy.models import BUSINESS_COPY_STOP_REASONS, BUSINESS_COPY_TRIGGERS
from apps.workers import business_copy as worker
from apps.workers import chat, retention, script_assist
from apps.workers.extraction import GOOGLE_PROVIDER, AssistCapability, TenantModelLeg
from apps.workers.settings import CRON_JOBS, WorkerSettings
from calevate_shared.call_script import SOUNDS_LIKE_MAX, ConversationStage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.conftest import create_org_with_receptionist

MODEL = "gemini-3.1-flash-lite"
LEG = TenantModelLeg(model=MODEL, provider="google", serves_dashboard=True)


def _starter_count(job: str) -> int:
    return len(starters.CATALOGUE[(starters.NEUTRAL_VERTICAL, job)].steps)  # type: ignore[index]


#: The keys prompt version 2 added; a copy stored under version 1 has none of them.
V2_PLACEHOLDERS: dict[str, str] = {
    "teach_note": "Groundnut oil is 320 rupees a litre. We deliver in Miyapur. No stock promises.",
    "business_line": "a cold-pressed oil shop in Kukatpally",
    "agent_role": "You answer the phone for the oil shop. You help callers choose and order.",
    "call_goal": "Answer their question and take the order with the delivery area.",
    "outbound_purpose": "You asked about our groundnut oil last week, so I am calling to help.",
    "call_ending": "Confirm the order and the delivery area, thank them and say goodbye.",
    "pronounce_word": "Kukatpally",
    "pronounce_say_as": "Koo-kut-pul-lee",
    "script_change": "When someone asks for a discount, offer free delivery instead",
    "script_change_idea": "Ask the delivery area before the order",
    "fact_question": "Do you deliver on Sundays?",
    "fact_answer": "No, we deliver Monday to Saturday.",
    "test_expectation": "Look up groundnut oil in our knowledge and give the price.",
    "campaign_name": "New batch reminder",
    "message_title": "Order ready",
    "message_body": "Your oil order is ready for pickup, {{1}}. Thank you.",
    "outcome_label": "Wants to order",
    "outcome_meaning": "The caller wants to order oil from us.",
}


def copy_dict() -> dict[str, Any]:
    """A valid answer for a neutral (non-clinic) account."""
    return {
        "placeholders": {
            "branch_label": "Kukatpally shop",
            "service_name": "Cold-pressed groundnut oil (1 litre)",
            "service_price": "320",
            "service_note": "Fresh batch every Monday",
            "ask_on_arrival": "depends on the day's stock",
            "faq_question": "Do you deliver to Miyapur?",
            "staff_name": "Ramesh Rao",
            "staff_spoken": "RAA-mesh RAO",
            "staff_role": "Owner",
            "staff_why_it_matters": "regular customers ask for the owner by name",
            "booking_rules": "Orders before 6 pm are packed the same day. Never promise stock.",
            "contact_name": "Shop counter",
            "knowledge_title": "This week's oil prices",
            "knowledge_answer": "Free home delivery on orders above 500 rupees within 5 km.",
            "extraction_reason": "so we can pack the order before the customer arrives",
            "script_brief": "We sell cold-pressed oils in Hyderabad. Take the order.",
            "extraction_label": "Oil wanted",
            "extraction_options": "Pickup, Home delivery",
            "end_call_rules": "Never promise stock without checking.\nAlways offer a call back.",
            "lead_search": "groundnut oil for Saturday",
            "booking_job_title": "Take orders",
            "booking_job_line": "Your agent can check your calendar and book pickup times.",
            **V2_PLACEHOLDERS,
        },
        "steps": [
            {"name": "Find out what they need", "example_line": "Cheppandi andi, em kavali?"},
            {"name": "Take the order", "example_line": "Enni litres kavali andi?"},
            {"name": "Confirm and close", "example_line": "Sare andi, order ready chestham."},
        ],
        "starter_lines": {
            job: [f"Line {chr(65 + i)} andi" for i in range(_starter_count(job))]
            for job in starters.LINE_SETS
        },
        "caller_details": ["Oil wanted", "Quantity", "Delivery area"],
        "example_questions": [
            "Do you deliver on Sundays?",
            "Is the oil cold-pressed?",
            "Can I pay on delivery?",
        ],
    }


def _inputs(*, clinic: bool = False) -> worker.Inputs:
    steps = {
        job: tuple(
            (s.title, s.instruction)
            for s in starters.CATALOGUE[(starters.NEUTRAL_VERTICAL, job)].steps  # type: ignore[index]
        )
        for job in starters.LINE_SETS
    }
    return worker.Inputs(
        description="Business name: Green Oils",
        language="te-IN",
        vertical="clinic" if clinic else "retail",
        clinic=clinic,
        starter_steps=steps,
        inputs_hash="0" * 64,
    )


# --- 1. the shape and its rules -----------------------------------------------------------


def test_a_valid_answer_parses() -> None:
    parsed = worker.parse_answer(copy_dict(), inputs=_inputs())
    assert parsed.placeholders.service_price == "320"
    assert len(parsed.steps) == 3


def test_the_placeholder_keys_are_the_web_tables_keys_less_the_two_shown_before_an_account() -> (
    None
):
    """FAILS IF: the generated set drifts from `verticalExamples.ts`'s keys."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "apps/web/src/lib/verticalExamples.ts"
    ).read_text(encoding="utf-8")
    block = source.split("export interface VerticalExamples {", 1)[1].split("}", 1)[0]
    import re

    web_keys = re.findall(r"readonly (\w+):", block)
    snake = {re.sub(r"(?<!^)([A-Z])", r"_\1", k).lower() for k in web_keys}
    assert snake - {"org_name", "org_slug"} == set(business_copy.PLACEHOLDER_KEYS)


@pytest.mark.parametrize(
    ("path", "value", "rule"),
    [
        (("placeholders", "service_name"), "**Oil**", "no markdown"),
        (("placeholders", "knowledge_title"), "Prices from Gemini", "technology company"),
        (("placeholders", "contact_name"), "Doctor's desk", "medical words"),
        (("placeholders", "faq_question"), "Two\nlines", "one line"),
        (("placeholders", "end_call_rules"), "One\nTwo\nThree", "two rules"),
        (("caller_details", 0), "Area 🙂", "no emoji"),
        (("placeholders", "teach_note"), "We see patients every morning.", "medical words"),
        (("placeholders", "business_line"), "a shop run on **Claude**", "no markdown"),
        (("placeholders", "message_body"), "Your order is ready.", "exactly one {{1}}"),
        (("placeholders", "message_body"), "Hi {{1}}, {{2}} is ready.", "exactly one {{1}}"),
        (("placeholders", "message_body"), "{{1}}, your order is ready.", "inside the sentence"),
        (("placeholders", "message_body"), "Your order is ready, {{1}}.", "inside the sentence"),
    ],
)
def test_a_broken_rule_is_sent_back_by_path_never_by_text(
    path: tuple[Any, ...], value: str, rule: str
) -> None:
    raw = copy_dict()
    raw[path[0]][path[1]] = value
    with pytest.raises(script_assist.UnusableAnswerError) as unusable:
        worker.parse_answer(raw, inputs=_inputs())
    assert rule in unusable.value.problems
    assert value not in unusable.value.problems


def test_a_spoken_line_says_numbers_in_words() -> None:
    raw = copy_dict()
    raw["steps"][0]["example_line"] = "Rs 120 andi"
    with pytest.raises(script_assist.UnusableAnswerError) as unusable:
        worker.parse_answer(raw, inputs=_inputs())
    assert "steps.0.example_line: numbers in words" in unusable.value.problems
    # The same digits are fine in an English placeholder.
    raw = copy_dict()
    raw["placeholders"]["lead_search"] = "2 litres on Saturday"
    worker.parse_answer(raw, inputs=_inputs())


def test_medical_words_are_a_clinics_own() -> None:
    raw = copy_dict()
    raw["placeholders"]["contact_name"] = "Doctor's desk"
    assert worker.parse_answer(raw, inputs=_inputs(clinic=True)).placeholders.contact_name


def test_the_key_set_is_closed_and_the_lengths_are_capped() -> None:
    extra = copy_dict()
    extra["placeholders"]["org_name"] = "Green Oils"
    long = copy_dict()
    long["caller_details"] = ["x" * (business_copy.CHIP_MAX + 1), "a", "b"]
    price = copy_dict()
    price["placeholders"]["service_price"] = "₹500"
    for raw in (extra, long, price):
        with pytest.raises(script_assist.UnusableAnswerError):
            worker.parse_answer(raw, inputs=_inputs())


def test_starter_lines_must_be_one_per_step() -> None:
    raw = copy_dict()
    raw["starter_lines"]["answer_calls"] = raw["starter_lines"]["answer_calls"][:2]
    with pytest.raises(script_assist.UnusableAnswerError) as unusable:
        worker.parse_answer(raw, inputs=_inputs())
    assert "starter_lines.answer_calls: exactly" in unusable.value.problems


def test_a_new_answer_must_fill_every_placeholder() -> None:
    """FAILS IF: a key added after version 1 may be left out of a new answer."""
    raw = copy_dict()
    del raw["placeholders"]["teach_note"]
    with pytest.raises(script_assist.UnusableAnswerError) as unusable:
        worker.parse_answer(raw, inputs=_inputs())
    assert "placeholders.teach_note: missing" in unusable.value.problems


def test_a_copy_stored_before_version_two_still_reads() -> None:
    """FAILS IF: a stored copy without the version-2 keys stops reading, which would drop
    every placeholder the account already had back to the per-trade table."""
    raw = copy_dict()
    for key in V2_PLACEHOLDERS:
        del raw["placeholders"][key]
    stored = business_copy.parse_stored(raw)
    assert stored is not None
    assert stored.placeholders.service_price == "320"
    assert stored.placeholders.teach_note is None
    assert business_copy.copy_problems(stored, clinic=False, language="te-IN") == []
    assert set(business_copy.missing_placeholders(stored.placeholders)) == set(V2_PLACEHOLDERS)


def test_the_instruction_explains_every_placeholder_key() -> None:
    """FAILS IF: a key reaches the strict schema without the instruction saying what it is,
    so the model guesses."""
    assert tuple(worker.PLACEHOLDER_MEANINGS) == business_copy.PLACEHOLDER_KEYS


def test_a_payment_name_is_not_a_provider_and_google_alone_still_is() -> None:
    """FAILS IF: "we take Google Pay" is refused as naming a technology company, or "Google"
    on its own stops being one."""
    assert business_copy.provider_words("Pay by UPI, Google Pay, GPay or G Pay.") == frozenset()
    assert business_copy.provider_words("Ask Google about us.") == {"google"}
    assert business_copy.provider_words("Google Pay works; so does Gemini.") == {"gemini"}


def test_the_closed_sets_agree_with_the_table_and_every_stop_has_words() -> None:
    from typing import get_args

    assert get_args(business_copy.Trigger) == BUSINESS_COPY_TRIGGERS
    assert get_args(business_copy.StopReason) == BUSINESS_COPY_STOP_REASONS
    assert set(business_copy.STOP_MESSAGES) == set(BUSINESS_COPY_STOP_REASONS)
    for words in business_copy.STOP_MESSAGES.values():
        assert not business_copy.VENDOR_WORDS.search(words)


def test_the_instruction_names_the_call_language_and_the_starters() -> None:
    said = worker.instruction_for(_inputs())
    assert "Main call language: Telugu" in said
    assert "Find out what they need" in said
    assert not business_copy.CLINIC_WORDS.search(said)


def test_the_strict_schema_is_closed_and_counts_the_starter_lines() -> None:
    schema = worker.answer_schema({"answer_calls": 6, "call_leads": 6})
    body = schema["json_schema"]["schema"]  # type: ignore[index]
    assert body["additionalProperties"] is False
    placeholders = body["properties"]["placeholders"]
    assert set(placeholders["required"]) == set(business_copy.PLACEHOLDER_KEYS)
    lines = body["properties"]["starter_lines"]["properties"]["answer_calls"]
    assert lines["minItems"] == lines["maxItems"] == 6


# --- 2. the Gemini-only ladder ------------------------------------------------------------


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "g-test", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_resource", "res", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "az", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)

    async def _quiet(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(provider_health, "note_failure", _quiet)
    monkeypatch.setattr(provider_health, "note_success", _quiet)


def _ok(raw: dict[str, Any]) -> bool:
    if not raw.get("ok"):
        raise script_assist.UnusableAnswerError("ok: must be true")
    return True


async def test_gemini_only_never_reaches_the_standby_or_azure(
    keyed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: a Gemini failure on this job falls to Sarvam (ToS s.17.5) or Azure."""
    dialects: list[str] = []

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        dialects.append(leg.dialect)
        return chat.ChatOutcome(
            content='{"ok": false}',
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=10, output_tokens=5),
        )

    monkeypatch.setattr(chat, "complete", _complete)
    with pytest.raises(ProblemError) as refused:
        await script_assist.ask_json("d", "i", parse=_ok, tenant_leg=LEG, gemini_only=True)
    assert dialects == ["google", "google"]
    assert refused.value.code == script_assist.ANSWER_UNUSABLE_CODE
    # Both billed attempts travel with the refusal to the meter.
    assert len(getattr(refused.value, "earlier", ())) == 1


async def test_gemini_only_refuses_when_the_gemini_leg_cannot_serve(
    keyed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        called.append(leg.dialect)
        raise AssertionError("no leg may be asked")

    monkeypatch.setattr(chat, "complete", _complete)
    blocked = TenantModelLeg(
        model=MODEL, provider="google", serves_dashboard=False, blocked_reason="unpriced"
    )
    with pytest.raises(ProblemError):
        await script_assist.ask_json("d", "i", parse=_ok, tenant_leg=blocked, gemini_only=True)
    assert called == []


async def test_gemini_only_answers_on_gemini(keyed: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        return chat.ChatOutcome(
            content='{"ok": true}',
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=10, output_tokens=5),
        )

    monkeypatch.setattr(chat, "complete", _complete)
    answer = await script_assist.ask_json("d", "i", parse=_ok, tenant_leg=LEG, gemini_only=True)
    assert answer.value is True and answer.model == MODEL
    assert answer.capability.provider == GOOGLE_PROVIDER


# --- 3. the job ---------------------------------------------------------------------------


@pytest.fixture
def priced() -> Iterator[None]:
    rates.install_llm_price_attestations(
        lambda: {
            MODEL: rates.LlmPriceAttestation(
                model=MODEL,
                input_usd_per_mtok=Decimal("0.25"),
                output_usd_per_mtok=Decimal("1.50"),
                read_on=date(2026, 10, 18),
                attested_by="founder",
                source="ai.google.dev/gemini-api/docs/pricing, read 18 Oct 2026",
                cached_input_usd_per_mtok=Decimal("0.025"),
            )
        }
    )
    yield
    rates.install_llm_price_attestations(None)


class FakeModel:
    """`ask_json` as the job calls it: records each call, answers with `copy_dict()`."""

    def __init__(self, *, fail: ProblemError | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail
        self.answer = copy_dict()

    async def __call__(self, description: str, instruction: str, **kw: Any) -> Any:
        self.calls.append({"description": description, **kw})
        if self.fail is not None:
            raise self.fail
        return script_assist.JsonAnswer(
            value=kw["parse"](copylib.deepcopy(self.answer)),
            capability=AssistCapability(available=True, provider=GOOGLE_PROVIDER),
            usage=chat.TokenUsage(
                prompt_tokens=16_000,
                output_tokens=1_000,
                cached_prompt_tokens=12_000,
                cached_reported=True,
            ),
            model=MODEL,
            service_tier="flex" if kw.get("flex") is not None else "standard",
        )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch, priced: None) -> FakeModel:
    fake = FakeModel()
    monkeypatch.setattr(worker, "ask_json", fake)
    monkeypatch.setattr(worker, "google_assist_leg", lambda: LEG)
    return fake


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, str]]]:
    raised: list[tuple[str, dict[str, str]]] = []

    def _alert(stage: str, code: str, **kw: Any) -> None:
        raised.append((code, kw))

    monkeypatch.setattr(worker, "alert", _alert)
    return raised


def _trial(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    async def _active(session: Any, *, tenant_id: Any, at: Any = None) -> bool:
        return on

    monkeypatch.setattr(worker, "trial_billing_active", _active)


async def _row(tenant_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT generated, inputs_hash, cost_inr, absorbed, stop_reason, "
                    "running_since, last_trigger, generated_at FROM business_copies"
                )
            )
        ).first()


async def _ledger(tenant_id: uuid.UUID) -> list[tuple[str, str]]:
    async with tenant_session(tenant_id) as session:
        return [
            (str(r[0]), str(r[1]))
            for r in (
                await session.execute(
                    text(
                        "SELECT unit_type, meta->>'feature' FROM usage_events "
                        "WHERE tenant_id = :t AND unit_type LIKE 'ai_assist%' ORDER BY unit_type"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        ]


async def _run(tenant_id: uuid.UUID, trigger: str) -> str:
    return await worker.generate_business_copy(
        {}, {"tenant_id": str(tenant_id), "trigger": trigger}
    )


async def test_a_refresh_stores_the_copy_and_meters_the_tokens_on_the_allowance(
    model: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: the run is charged a flat fee, skips the cached-input split, or does not
    count against the allowance."""
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        before = await read_ai_quota(session, tenant_id=tenant_id)
    assert await _run(tenant_id, "refresh") == "stored"
    row = await _row(tenant_id)
    assert row is not None and row[0]["placeholders"]["service_price"] == "320"
    assert row[3] is False and row[4] is None and row[5] is None and row[6] == "refresh"
    # 16 x 0.0238 (16k in, 12k of it cached: 4k full + 1.2 x the 10k rung) + 1 x 0.1425
    assert row[2] == Decimal("0.0952") + Decimal("0.02856") + Decimal("0.1425")
    assert await _ledger(tenant_id) == [
        ("ai_assist_10ktok_cached_in", ASSIST_FEATURE_BUSINESS_COPY),
        ("ai_assist_ktok_in", ASSIST_FEATURE_BUSINESS_COPY),
        ("ai_assist_ktok_out", ASSIST_FEATURE_BUSINESS_COPY),
    ]
    async with tenant_session(tenant_id) as session:
        after = await read_ai_quota(session, tenant_id=tenant_id)
    assert after.used_inr - before.used_inr == row[2]
    # The model was told the business, redacted, and asked on Gemini alone.
    assert model.calls[0]["gemini_only"] is True
    assert model.calls[0]["tenant_leg"] == LEG


async def test_a_trials_first_generation_is_ours(
    model: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trial(monkeypatch, True)
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        before = await read_ai_quota(session, tenant_id=tenant_id)
    assert await _run(tenant_id, "signup") == "stored"
    row = await _row(tenant_id)
    assert row[3] is True
    assert {feature for _, feature in await _ledger(tenant_id)} == {
        ASSIST_FEATURE_BUSINESS_COPY_ABSORBED
    }
    assert ASSIST_FEATURE_BUSINESS_COPY_ABSORBED in ABSORBED_ASSIST_FEATURES
    assert ASSIST_FEATURE_BUSINESS_COPY not in ABSORBED_ASSIST_FEATURES
    async with tenant_session(tenant_id) as session:
        after = await read_ai_quota(session, tenant_id=tenant_id)
    assert after.used_inr == before.used_inr


async def test_a_paying_accounts_first_generation_is_on_its_allowance(
    model: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "signup") == "stored"
    assert (await _row(tenant_id))[3] is False


async def test_the_scheduled_check_skips_unchanged_inputs_and_runs_on_a_change(
    model: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "scheduled") == "stored"
    first = await _row(tenant_id)
    assert await _run(tenant_id, "scheduled") == "inputs_unchanged"
    assert len(model.calls) == 1
    kept = await _row(tenant_id)
    assert kept[0] == first[0] and kept[4] == "inputs_unchanged" and kept[7] == first[7]
    # "Refresh now" always runs, changed or not.
    assert await _run(tenant_id, "refresh") == "stored"
    assert len(model.calls) == 2
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET name = 'Green Oils Kukatpally' WHERE id = :t"),
            {"t": tenant_id},
        )
    assert await _run(tenant_id, "scheduled") == "stored"
    assert (await _row(tenant_id))[1] != first[1]


async def test_only_the_daily_check_asks_on_flex_and_its_cost_stays_at_the_standard_rate(
    model: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-930. FAILS IF: a run somebody asked for waits on Flex, or a Flex answer is recorded
    below the attested rate while no Flex rate can be attested (hard rule 7)."""
    _trial(monkeypatch, False)
    asked, _slug, _token = await _make_tenant()
    assert await _run(asked, "refresh") == "stored"
    assert model.calls[-1]["flex"] is None
    scheduled, _slug, _token = await _make_tenant()
    assert await _run(scheduled, "scheduled") == "stored"
    assert model.calls[-1]["flex"].call == "business_copy_scheduled"

    assert (await _row(scheduled))[2] == (await _row(asked))[2]

    async def _meta(tenant_id: uuid.UUID) -> set[tuple[str | None, str | None]]:
        async with tenant_session(tenant_id) as session:
            rows = await session.execute(
                text(
                    "SELECT meta->>'service_tier', meta->>'priced_at' FROM usage_events "
                    "WHERE tenant_id = :t AND unit_type LIKE 'ai_assist%'"
                ),
                {"t": tenant_id},
            )
            return {(r[0], r[1]) for r in rows}

    assert await _meta(scheduled) == {("flex", "standard")}
    assert await _meta(asked) == {(None, None)}


async def test_a_used_up_allowance_skips_the_run_and_keeps_the_copy(
    model: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "refresh") == "stored"
    kept = (await _row(tenant_id))[0]

    async def _ceiling(session: Any, *, tenant_id: Any) -> None:
        raise ProblemError.business_rule("ai_quota_exceeded", "used up")

    monkeypatch.setattr(worker, "require_ai_assist", _ceiling)
    assert await _run(tenant_id, "refresh") == "allowance_used_up"
    row = await _row(tenant_id)
    assert row[0] == kept and row[4] == "allowance_used_up" and row[5] is None
    assert len(model.calls) == 1


async def test_a_gemini_failure_keeps_the_copy_and_raises_the_alarm(
    model: FakeModel,
    monkeypatch: pytest.MonkeyPatch,
    alarms: list[tuple[str, dict[str, str]]],
) -> None:
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "refresh") == "stored"
    kept = (await _row(tenant_id))[0]
    model.fail = ProblemError.business_rule("assist_provider_unavailable", "down")
    assert await _run(tenant_id, "refresh") == "provider_unavailable"
    model.fail = ProblemError.business_rule(script_assist.ANSWER_UNUSABLE_CODE, "shape")
    assert await _run(tenant_id, "refresh") == "answer_unusable"
    assert (await _row(tenant_id))[0] == kept
    assert [(code, kw["reason"]) for code, kw in alarms] == [
        ("business_copy_unavailable", "provider_unavailable"),
        ("business_copy_unavailable", "answer_unusable"),
    ]


async def test_an_unofferable_gemini_leg_stops_before_any_spend(
    model: FakeModel,
    monkeypatch: pytest.MonkeyPatch,
    alarms: list[tuple[str, dict[str, str]]],
) -> None:
    _trial(monkeypatch, False)
    monkeypatch.setattr(
        worker,
        "google_assist_leg",
        lambda: TenantModelLeg(model=MODEL, provider="google", serves_dashboard=False),
    )
    tenant_id, _slug, _token = await _make_tenant()
    assert await _run(tenant_id, "refresh") == "provider_unavailable"
    assert model.calls == [] and await _ledger(tenant_id) == []
    assert alarms and alarms[0][0] == "business_copy_unavailable"


async def test_a_held_row_is_not_run_twice(
    model: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trial(monkeypatch, False)
    tenant_id, _slug, _token = await _make_tenant()
    held = await worker.claim(tenant_id, "refresh")
    assert held is not None
    assert await _run(tenant_id, "refresh") == "busy"
    # A claim past its lifetime belongs to a run that died.
    stale = datetime.now(UTC) - business_copy.CLAIM_TTL - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE business_copies SET running_since = :s"), {"s": stale})
    assert await _run(tenant_id, "refresh") == "stored"


async def test_the_inputs_include_real_gaps_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO knowledge_gaps (id, tenant_id, agent_id, topic_key, topic_label, "
                "status, occurrence_count, call_count, example_question_redacted, "
                "example_answer_redacted, top_signal, first_seen_at, last_seen_at, created_at, "
                "updated_at) VALUES (:id, :t, :a, 'delivery', 'Delivery', 'open', 1, 1, "
                "'Do you deliver to 9876543210 area?', 'not sure', 'dont_know', now(), now(), "
                "now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id},
        )
    inputs = await worker.gather_inputs(tenant_id)
    assert "Do you deliver" in inputs.description
    assert "9876543210" not in inputs.description
    again = await worker.gather_inputs(tenant_id)
    assert again.inputs_hash == inputs.inputs_hash


# --- 4. tenancy and erasure ---------------------------------------------------------------


async def _seed_row(tenant_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_copies (id, tenant_id, generated, language, generated_at) "
                "VALUES (:id, :t, CAST(:g AS jsonb), 'te-IN', now())"
            ),
            {"id": uuid7(), "t": tenant_id, "g": __import__("json").dumps(copy_dict())},
        )


@pytest.mark.rls
async def test_another_tenant_reads_zero_rows() -> None:
    mine, _s, _t = await _make_tenant()
    theirs, _s2, _t2 = await _make_tenant()
    await _seed_row(mine)
    async with tenant_session(theirs) as session:
        assert (await session.execute(text("SELECT count(*) FROM business_copies"))).scalar() == 0
        assert await business_copy.read_state(session) is None
    async with tenant_session(mine) as session:
        state = await business_copy.read_state(session)
    assert state is not None and state.copy is not None


@pytest.mark.rls
async def test_another_tenant_cannot_write_into_my_row() -> None:
    mine, _s, _t = await _make_tenant()
    theirs, _s2, _t2 = await _make_tenant()
    with pytest.raises(Exception, match="row-level security"):
        async with tenant_session(theirs) as session:
            await session.execute(
                text("INSERT INTO business_copies (id, tenant_id) VALUES (:id, :t)"),
                {"id": uuid7(), "t": mine},
            )


async def test_the_account_erasure_deletes_the_copy() -> None:
    tenant_id, _s, _t = await _make_tenant()
    await _seed_row(tenant_id)
    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned', updated_at = now() WHERE id = :t"),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": request_id, "t": tenant_id},
        )
    result = await retention.execute_tenant_erasure(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert result != "not_found"
    async with tenant_session(tenant_id) as session:
        assert (await session.execute(text("SELECT count(*) FROM business_copies"))).scalar() == 0


# --- 5. starter lines never replace an owner's words --------------------------------------


def _script() -> Any:
    return starters.CATALOGUE[(starters.NEUTRAL_VERTICAL, "answer_calls")].call_script(  # type: ignore[index]
        business="Green Oils"
    )


def test_starter_lines_fill_only_empty_example_lines() -> None:
    script = _script()
    typed = ConversationStage.model_validate(
        {**script.stages[0].model_dump(), "sounds_like": "Owner's own words"}
    )
    script = script.model_copy(update={"stages": [typed, *script.stages[1:]]})
    lines = [f"Line {i} andi" for i in range(len(script.stages))]
    filled = starters.with_example_lines(script, lines)
    assert filled.stages[0].sounds_like == "Owner's own words"
    assert [s.sounds_like for s in filled.stages[1:]] == lines[1:]


def test_lines_for_another_number_of_steps_or_too_long_are_not_used() -> None:
    script = _script()
    assert starters.with_example_lines(script, ["one"]) == script
    long = ["x" * SOUNDS_LIKE_MAX] * len(script.stages)
    # Each instruction plus a full-length line still fits, or the line is left out: a stage
    # never fails validation because of it.
    for stage in starters.with_example_lines(script, long).stages:
        ConversationStage.model_validate(stage.model_dump())


async def test_a_new_agent_from_a_starter_gets_the_lines_in_its_language() -> None:
    tenant_id, _s, _t = await _make_tenant()
    await _seed_row(tenant_id)
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await starters.apply_starter(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            job="answer_calls",
            vertical_template=None,
            business="Green Oils",
            created_by=None,
            language="te-IN",
        )
        stored = (
            await session.execute(
                text(
                    "SELECT pv.structured_script FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.system_prompt_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
    assert stored["stages"][1]["sounds_like"] == "Line B andi"


# --- 6. the routes ------------------------------------------------------------------------


async def _get(path: str, headers: dict[str, str]) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.get(path, headers=headers)


async def test_the_screens_read_nothing_until_the_first_copy_lands() -> None:
    tenant_id, slug, token = await _make_tenant(role="staff")
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    empty = await _get("/v1/business-copy", headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["placeholders"] is None and empty.json()["steps"] == []
    await _seed_row(tenant_id)
    landed = (await _get("/v1/business-copy", headers)).json()
    assert landed["placeholders"]["service_price"] == "320"
    assert landed["language"] == "te-IN" and "starter_lines" not in landed


async def _superadmin() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops Lead', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def test_an_operator_sees_the_cost_and_refreshes_at_our_cost() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _seed_row(tenant_id)
    headers = await _superadmin()
    path = f"/v1/admin/tenants/{tenant_id}/business-copy"
    read = await _get(path, headers)
    assert read.status_code == 200, read.text
    assert read.json()["absorbed"] is False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        queued = await http.post(f"{path}/refresh", headers=headers)
    assert queued.status_code == 202, queued.text
    assert queued.json()["refreshing"] is True
    async with tenant_session(tenant_id) as session:
        payloads = (
            (
                await session.execute(
                    text(
                        "SELECT payload FROM outbox_messages WHERE job = :job "
                        "AND payload->>'tenant_id' = :t"
                    ),
                    {"job": business_copy.JOB, "t": str(tenant_id)},
                )
            )
            .scalars()
            .all()
        )
    assert payloads == [{"tenant_id": str(tenant_id), "trigger": "operator"}]
    missing = await _get(f"/v1/admin/tenants/{uuid.uuid4()}/business-copy", headers)
    assert missing.status_code == 404


# --- 7. wiring ----------------------------------------------------------------------------


def test_the_job_and_the_daily_check_are_registered() -> None:
    assert worker.JOB_NAME == business_copy.JOB
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert business_copy.JOB in names or any(
        getattr(f, "coroutine", None) is worker.generate_business_copy
        for f in WorkerSettings.functions
    )
    assert any("sweep_business_copies" in job.name for job in CRON_JOBS)


async def test_a_new_account_queues_its_first_generation() -> None:
    created = await create_org_with_receptionist(
        name="Green Oils",
        slug=f"green-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(created["id"]) as session:
        payloads = (
            (
                await session.execute(
                    text("SELECT payload FROM outbox_messages WHERE job = :job"),
                    {"job": business_copy.JOB},
                )
            )
            .scalars()
            .all()
        )
    assert {"tenant_id": str(created["id"]), "trigger": "signup"} in payloads


async def test_the_daily_check_queues_only_accounts_due_and_never_a_trial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    due, _s, _t = await _make_tenant()
    recent, _s2, _t2 = await _make_tenant()
    async with tenant_session(recent) as session:
        await session.execute(
            text(
                "INSERT INTO business_copies (id, tenant_id, last_attempt_at) VALUES (:id, :t, :at)"
            ),
            {"id": uuid7(), "t": recent, "at": now - timedelta(days=3)},
        )
    _trial(monkeypatch, False)
    assert await worker._due(due, now=now) is True
    assert await worker._due(recent, now=now) is False
    # Idempotent per day: a retried tick queues nothing twice.
    assert await worker._due(due, now=now) is True
    _trial(monkeypatch, True)
    trial, _s3, _t3 = await _make_tenant()
    assert await worker._due(trial, now=now) is False
    async with tenant_session(due) as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :t"
                ),
                {"job": business_copy.JOB, "t": str(due)},
            )
        ).scalar()
    assert count == 1
