"""D-889: choice lists that follow the business.

A caller on 25 Oct 2026 asked for five bedrooms and was saved as 3BHK: a closed list makes the
reader pick the nearest wrong choice. These pin: a choice field the caller answered outside its
list stays empty and keeps the caller's words; those words show on the call and the lead and
are erased with the rest of the extraction; the second caller asking for the same thing queues
a suggestion pass; the pass's answer is cleaned before an owner sees it (never a choice callers
are choosing removed, never a detail every lead already has, never one the owner turned down);
accepting writes a new version through the editor's one write path and rebuilds what a live
agent asks; and the owner's and operator's routes.
"""

from __future__ import annotations

import copy as copylib
import dataclasses
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import field_suggestion_routes, field_suggestions
from apps.api.agents.extraction_routes import write_schema
from apps.api.agents.field_suggestions import Suggestion, applicable, apply, suggestion_fingerprint
from apps.api.billing import rates
from apps.api.billing.models import (
    ABSORBED_ASSIST_FEATURES,
    ASSIST_FEATURE_FIELD_SUGGESTIONS,
    ASSIST_FEATURE_FIELD_SUGGESTIONS_ABSORBED,
)
from apps.api.core.errors import ProblemError
from apps.api.crm import service as crm_service
from apps.api.crm.captured import lead_unlisted
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.main import app
from apps.workers import chat, retention, script_assist
from apps.workers import extraction as extraction_module
from apps.workers import field_suggestions as passer
from apps.workers.extraction import (
    GOOGLE_PROVIDER,
    AssistCapability,
    build_response_schema,
    extract_call,
)
from apps.workers.pipeline import ingest_engine_event
from apps.workers.settings import WorkerSettings
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionSchemaSpec,
    build_extraction_prompt,
    clean_unlisted,
)
from calevate_shared.lead_fields import OUTPUT_KEYS
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_account_management_test import _operator
from tests.api_security_test import _make_tenant
from tests.pipeline_audit_test import _run_pipeline, _scalar
from tests.pipeline_audit_test import _stub_storage as _stub_storage
from tests.smoke_pipeline_test import _seed_tenant

BHK = ExtractionField(
    key="bhk_size",
    label="BHK",
    type="enum",
    enum_values=["1BHK", "2BHK", "3BHK", "4BHK", "5BHK+"],
    reason="Number of bedrooms the caller asked for.",
)
AREA = ExtractionField(key="preferred_location", label="Location", type="text")
SPEC = ExtractionSchemaSpec(fields=[BHK, AREA])
MODEL = "gemini-3.1-flash-lite"


# --- 1. the extraction keeps the caller's words instead of the nearest choice ------------


def test_the_prompt_asks_for_unlisted_words_only_with_choice_fields() -> None:
    with_choice = build_extraction_prompt(SPEC, "caller: hi")
    assert '"unlisted"' in with_choice and "(bhk_size)" in with_choice
    assert "never the nearest choice" in with_choice
    without = build_extraction_prompt(ExtractionSchemaSpec(fields=[AREA]), "caller: hi")
    assert '"unlisted"' not in without


def test_the_strict_schema_carries_one_nullable_answer_per_choice_field() -> None:
    schema = build_response_schema(SPEC)
    unlisted = schema["properties"]["unlisted"]
    assert unlisted["required"] == ["bhk_size"]
    assert unlisted["properties"] == {"bhk_size": {"type": ["string", "null"]}}
    assert unlisted["additionalProperties"] is False and "unlisted" in schema["required"]
    plain = build_response_schema(ExtractionSchemaSpec(fields=[AREA]))
    assert "unlisted" not in plain["properties"]


def test_only_a_short_answer_for_an_empty_choice_field_stands() -> None:
    empty: dict[str, Any] = {"bhk_size": None}
    said = {"bhk_size": "caller:  6   BHK", "preferred_location": "Kondapur"}
    assert clean_unlisted(SPEC, said, empty) == {"bhk_size": "6 BHK"}
    assert clean_unlisted(SPEC, {"bhk_size": "6 BHK"}, {"bhk_size": "5BHK+"}) == {}, (
        "a captured choice is the answer; there is nothing unlisted"
    )
    for bad in ("N/A", "unknown", "x" * 61, "call me on 98765 43210", "agent", None, 5):
        assert clean_unlisted(SPEC, {"bhk_size": bad}, empty) == {}, bad
    assert clean_unlisted(SPEC, "6 BHK", empty) == {}


def test_no_lead_field_may_be_called_unlisted() -> None:
    assert "unlisted" in OUTPUT_KEYS


class _Runner:
    model_name = "fake-model"

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer

    async def run(self, spec: ExtractionSchemaSpec, transcript: str, **_: Any) -> dict[str, Any]:
        return dict(self.answer)


SIX = {
    "bhk_size": None,
    "unlisted": {"bhk_size": "6 BHK"},
    "summary": "Asked for a six bedroom flat.",
    "outcome_tag": "answered",
    "sentiment": "neutral",
}


async def test_six_bedrooms_stays_unlisted_rather_than_the_nearest_choice() -> None:
    out = await extract_call(SPEC, "caller: aaru bedroom kavali", extractor=_Runner(SIX))
    assert out.data.get("bhk_size") is None
    assert out.unlisted == {"bhk_size": "6 BHK"}


# --- 2. the pass's answer is cleaned before an owner sees it -----------------------------


INPUTS = passer.Inputs(
    description="d",
    fields=[BHK, AREA],
    unlisted={"bhk_size": [("6 BHK", 3), ("Penthouse", 1)]},
    captured={"bhk_size": {"2BHK": 4}},
)


def _item(kind: str, **kw: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "field_key": kw.get("field_key", "bhk_size"),
        "label": kw.get("label"),
        "values": kw.get("values", []),
        "hint": kw.get("hint"),
        "reason": kw.get("reason", "Because."),
        "source": kw.get("source", "calls"),
    }


def _clean(*items: dict[str, Any], inputs: passer.Inputs = INPUTS) -> list[Suggestion]:
    return passer.suggestions_from_model({"suggestions": list(items)}, inputs)


def test_added_choices_are_new_ones_and_count_the_callers_they_catch() -> None:
    (got,) = _clean(_item("add_choices", values=["6BHK", "2bhk", " 6 bhk "]))
    assert got.values == ["6BHK"], "a choice already listed, in any spelling, is not added"
    assert got.callers == 3 and got.field_label == "BHK"


def test_a_choice_callers_are_choosing_is_never_removed_and_two_always_remain() -> None:
    (got,) = _clean(_item("remove_choices", values=["2bhk", "5BHK+"], source="script"))
    assert got.values == ["5BHK+"], "2BHK was captured recently, so it stays"
    assert _clean(_item("remove_choices", values=["1BHK", "3BHK", "4BHK", "5BHK+"])) == [], (
        "a list is never cut below two choices"
    )


def test_a_new_detail_is_never_one_the_agent_or_every_lead_already_has() -> None:
    assert _clean(_item("new_field", label="Name", source="script")) == []
    assert _clean(_item("new_field", label="location", source="script")) == []
    car, visit = _clean(
        _item("new_field", label="Car model", values=["Swift", "City"], hint="Which car."),
        _item("new_field", label="Visit day", values=["only one"]),
    )
    assert car.field is not None and car.field.type == "enum" and car.field_key == "car_model"
    assert car.field.enum_values == ["Swift", "City"] and car.field.reason == "Which car."
    assert visit.field is not None and visit.field.type == "text" and visit.values == []


def test_unusable_items_are_dropped() -> None:
    assert (
        _clean(
            _item("add_choices", field_key="nope", values=["x"]),
            _item("add_choices", field_key="preferred_location", values=["x"]),
            _item("add_choices", values=["7BHK"], reason=""),
            _item("add_choices", values=["7BHK"], source="vendor"),
            _item("rename", values=["7BHK"]),
            "not an item",  # type: ignore[arg-type]
        )
        == []
    )
    assert passer.suggestions_from_model({"suggestions": "no"}, INPUTS) == []


def test_a_dismissed_suggestion_is_not_offered_again_in_any_spelling() -> None:
    (first,) = _clean(_item("add_choices", values=["6 BHK"]))
    assert first.id == suggestion_fingerprint("add_choices", "bhk_size", ["6bhk"])
    turned_down = dataclasses.replace(INPUTS, dismissed=frozenset({first.id}))
    assert _clean(_item("add_choices", values=["6BHK"]), inputs=turned_down) == []


def test_at_most_six_suggestions() -> None:
    items = [_item("add_choices", values=[f"{n}BHK"]) for n in range(6, 14)]
    assert len(_clean(*items)) == 6


def test_a_second_caller_changes_the_inputs_and_a_third_does_not() -> None:
    def digest(n: int) -> str:
        return dataclasses.replace(INPUTS, unlisted={"bhk_size": [("6 BHK", n)]}).digest()

    assert digest(1) != digest(2)
    assert digest(2) == digest(3)


def test_the_script_is_read_for_what_the_business_sells() -> None:
    body = passer.script_text(
        {
            "business_line": "Flats in Kondapur",
            "faqs": [{"question": "Which sizes?", "answer": "2 and 3 BHK only"}],
            "stages": [{"name": "Size", "instruction": "Ask the size they want"}],
            "objections": [{"objection": "too far", "response": "Metro is near"}],
        }
    )
    assert "Flats in Kondapur" in body and "2 and 3 BHK only" in body
    assert "Ask the size they want" in body and "Metro is near" in body
    assert passer.script_text(None) == "" and passer.script_text({"stages": "x"}) == ""


def test_a_change_applies_by_spelling_and_a_stale_one_does_not_apply() -> None:
    (add,) = _clean(_item("add_choices", values=["6BHK"]))
    changed = apply(add, [BHK, AREA])
    assert changed[0].enum_values == [*(BHK.enum_values or []), "6BHK"]
    assert not applicable(add, changed), "already made"
    assert not applicable(add, [AREA]), "the field is gone"
    (gone,) = _clean(_item("remove_choices", values=["5bhk+"]))
    assert apply(gone, [BHK])[0].enum_values == ["1BHK", "2BHK", "3BHK", "4BHK"]


# --- 3. queuing a pass --------------------------------------------------------------------


async def _agent_of(tenant_id: UUID) -> UUID:
    return UUID(str(await _scalar(tenant_id, "SELECT id FROM agents LIMIT 1")))


async def _jobs(job: str, agent_id: UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'agent_id' = :a ORDER BY created_at"
                ),
                {"job": job, "a": str(agent_id)},
            )
        ).scalars()
        return [dict(r) for r in rows]


async def _queue(tenant_id: UUID, agent_id: UUID, *, force: bool = False) -> bool:
    async with tenant_session(tenant_id) as session:
        return await field_suggestions.queue_pass(
            session, tenant_id=tenant_id, agent_id=agent_id, force=force
        )


async def _set_state(tenant_id: UUID, agent_id: UUID, state: str, age: str = "0 minutes") -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET field_suggestions_state = :s, "
                "field_suggestions_at = now() - CAST(:age AS interval) WHERE id = :a"
            ),
            {"s": state, "age": age, "a": agent_id},
        )


async def test_a_pass_is_queued_once_and_a_running_one_queues_the_next_itself() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    assert await _queue(tenant_id, agent_id) is True
    assert await _queue(tenant_id, agent_id) is False, "already queued"
    assert len(await _jobs(field_suggestions.JOB, agent_id)) == 1

    await _set_state(tenant_id, agent_id, "running")
    assert await _queue(tenant_id, agent_id) is False, "the running pass queues the next"
    assert (
        await _scalar(
            tenant_id, "SELECT field_suggestions_state FROM agents WHERE id = :a", a=agent_id
        )
        == "queued"
    )
    assert len(await _jobs(field_suggestions.JOB, agent_id)) == 1

    await _set_state(tenant_id, agent_id, "queued", age="1 hour")
    assert await _queue(tenant_id, agent_id, force=True) is True, "a dead pass gets a new job"
    jobs = await _jobs(field_suggestions.JOB, agent_id)
    assert len(jobs) == 2
    assert (
        await _scalar(
            tenant_id, "SELECT field_suggestions_inputs FROM agents WHERE id = :a", a=agent_id
        )
        is None
    ), "Check again forgets the last reading"


async def test_saving_lead_details_rebuilds_what_the_agent_asks_only_when_they_changed() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert (await write_schema(session, agent_id=agent_id, fields=[BHK])).changed
    async with tenant_session(tenant_id) as session:
        assert not (await write_schema(session, agent_id=agent_id, fields=[BHK])).changed
    assert len(await _jobs(field_suggestions.RECOMPILE_COLLECT_JOB, agent_id)) == 1
    assert (
        await passer.rebuild_collect({}, {"tenant_id": str(tenant_id), "agent_id": str(agent_id)})
        == "unchanged"
    ), "an agent with no script has nothing to rebuild"


def test_both_jobs_are_registered() -> None:
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert {field_suggestions.JOB, field_suggestions.RECOMPILE_COLLECT_JOB} <= names
    assert passer.JOB_NAME == "suggest_lead_details"
    assert passer.COLLECT_JOB_NAME == "rebuild_collect"


# --- 4. one pass, end to end ---------------------------------------------------------------


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


ANSWER: dict[str, Any] = {
    "suggestions": [_item("add_choices", values=["6BHK"], reason="Callers asked for 6BHK.")]
}


class _Model:
    def __init__(self, *, fail: ProblemError | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def __call__(self, description: str, instruction: str, **kw: Any) -> Any:
        self.calls.append({"description": description, "instruction": instruction, **kw})
        if self.fail is not None:
            raise self.fail
        return script_assist.JsonAnswer(
            value=kw["parse"](copylib.deepcopy(ANSWER)),
            capability=AssistCapability(available=True, provider=GOOGLE_PROVIDER),
            usage=chat.TokenUsage(prompt_tokens=2_000, output_tokens=300),
            model=MODEL,
        )


@dataclasses.dataclass
class _Leg:
    serves_dashboard: bool = True


def _setup(monkeypatch: pytest.MonkeyPatch, *, trial: bool, model: _Model) -> None:
    async def _active(session: Any, *, tenant_id: Any, at: Any = None) -> bool:
        return trial

    monkeypatch.setattr(passer, "trial_billing_active", _active)
    monkeypatch.setattr(field_suggestion_routes, "trial_billing_active", _active)
    monkeypatch.setattr(passer, "ask_json", model)
    monkeypatch.setattr(passer, "google_assist_leg", _Leg)


async def _bhk_agent() -> tuple[UUID, str, str, UUID]:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    async with tenant_session(tenant_id) as session:
        await write_schema(session, agent_id=agent_id, fields=[BHK])
    return tenant_id, slug, token, agent_id


async def _pass(tenant_id: UUID, agent_id: UUID) -> str:
    return await passer.suggest_lead_details(
        {}, {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    )


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


async def test_a_pass_stores_its_suggestions_on_the_allowance_and_spends_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _Model()
    _setup(monkeypatch, trial=False, model=model)
    tenant_id, _slug, _token, agent_id = await _bhk_agent()
    await _queue(tenant_id, agent_id)
    assert await _pass(tenant_id, agent_id) == "stored_1"
    call = model.calls[0]
    assert "bhk_size 'BHK': choices 1BHK, 2BHK" in call["description"]
    assert call["gemini_only"] is True and call["health_leg"] == "lead_suggestions"
    assert await _features(tenant_id) == {ASSIST_FEATURE_FIELD_SUGGESTIONS}
    assert ASSIST_FEATURE_FIELD_SUGGESTIONS not in ABSORBED_ASSIST_FEATURES
    async with tenant_session(tenant_id) as session:
        state = await field_suggestions.read_state(session, agent_id=agent_id)
    assert state.state == "done" and [s.values for s in state.suggestions] == [["6BHK"]]

    await _queue(tenant_id, agent_id)
    assert await _pass(tenant_id, agent_id) == "unchanged", "nothing changed, nothing spent"
    assert len(model.calls) == 1
    await _queue(tenant_id, agent_id)
    await _queue(tenant_id, agent_id, force=True)
    assert await _pass(tenant_id, agent_id) == "stored_1", (
        "Check again reads afresh, even pressed while a pass was already waiting"
    )
    assert len(model.calls) == 2
    assert await _pass(tenant_id, agent_id) == "not_queued"


async def test_a_trials_pass_is_ours_and_a_used_up_allowance_spends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _Model()
    _setup(monkeypatch, trial=True, model=model)
    tenant_id, _slug, _token, agent_id = await _bhk_agent()
    await _queue(tenant_id, agent_id)
    assert await _pass(tenant_id, agent_id) == "stored_1"
    assert await _features(tenant_id) == {ASSIST_FEATURE_FIELD_SUGGESTIONS_ABSORBED}
    assert ASSIST_FEATURE_FIELD_SUGGESTIONS_ABSORBED in ABSORBED_ASSIST_FEATURES

    _setup(monkeypatch, trial=False, model=model)

    async def _ceiling(session: Any, *, tenant_id: Any) -> None:
        raise ProblemError.business_rule("ai_quota_exceeded", "used up")

    monkeypatch.setattr(passer, "require_ai_assist", _ceiling)
    other, _s, _t, other_agent = await _bhk_agent()
    await _queue(other, other_agent)
    assert await _pass(other, other_agent) == "skipped"
    assert len(model.calls) == 1


async def test_a_failed_pass_reads_failed_and_a_change_mid_pass_queues_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(
        monkeypatch,
        trial=False,
        model=_Model(fail=ProblemError.business_rule("ai_unavailable", "down")),
    )
    tenant_id, _slug, _token, agent_id = await _bhk_agent()
    await _queue(tenant_id, agent_id)
    assert await _pass(tenant_id, agent_id) == "failed"
    async with tenant_session(tenant_id) as session:
        assert (await field_suggestions.read_state(session, agent_id=agent_id)).state == "failed"

    model = _Model()
    _setup(monkeypatch, trial=False, model=model)
    original = passer.gather

    async def _changed_meanwhile(tenant: UUID, agent: UUID, *, dismissed: list[str]) -> Any:
        await _queue(tenant, agent)  # the owner saves their script while the pass reads
        return await original(tenant, agent, dismissed=dismissed)

    monkeypatch.setattr(passer, "gather", _changed_meanwhile)
    await _queue(tenant_id, agent_id)
    before = len(await _jobs(field_suggestions.JOB, agent_id))
    assert await _pass(tenant_id, agent_id) == "stored_1"
    assert (
        await _scalar(
            tenant_id, "SELECT field_suggestions_state FROM agents WHERE id = :a", a=agent_id
        )
        == "queued"
    )
    assert len(await _jobs(field_suggestions.JOB, agent_id)) == before + 1


# --- 5. the owner's and operator's routes ----------------------------------------------------


async def _http(method: str, path: str, token: str, slug: str | None = None) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    if slug:
        headers["X-Org-Slug"] = slug
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.request(method, path, headers=headers)


async def _seed(tenant_id: UUID, agent_id: UUID, *items: dict[str, Any]) -> list[Suggestion]:
    inputs = dataclasses.replace(INPUTS, fields=[BHK], captured={})
    made = passer.suggestions_from_model({"suggestions": list(items)}, inputs)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET field_suggestions = CAST(:s AS jsonb), "
                "field_suggestions_state = 'done', field_suggestions_at = now() WHERE id = :a"
            ),
            {"s": json.dumps([s.model_dump(mode="json") for s in made]), "a": agent_id},
        )
    return made


async def _fields(tenant_id: UUID, agent_id: UUID) -> tuple[int, list[dict[str, Any]]]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT es.version, es.fields FROM agents a JOIN extraction_schemas es "
                    "ON es.id = a.extraction_schema_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).one()
    return int(row[0]), list(row[1])


async def test_the_owner_accepts_one_and_turns_one_down() -> None:
    tenant_id, slug, token, agent_id = await _bhk_agent()
    add, new = await _seed(
        tenant_id,
        agent_id,
        _item("add_choices", values=["6BHK"], reason="3 callers asked for 6BHK."),
        _item("new_field", label="Facing", values=["East", "West"], source="script"),
    )
    base = f"/v1/agents/{agent_id}/lead-suggestions"
    got = await _http("GET", base, token, slug)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["state"] == "done" and [s["id"] for s in body["suggestions"]] == [add.id, new.id]
    assert body["suggestions"][1]["field_type"] == "enum"

    version, _ = await _fields(tenant_id, agent_id)
    accepted = await _http("POST", f"{base}/{add.id}/accept", token, slug)
    assert accepted.status_code == 200, accepted.text
    assert [s["id"] for s in accepted.json()["remaining"]["suggestions"]] == [new.id]
    after, fields = await _fields(tenant_id, agent_id)
    assert after == version + 1 and fields[0]["enum_values"][-1] == "6BHK"
    assert len(await _jobs(field_suggestions.RECOMPILE_COLLECT_JOB, agent_id)) == 2, (
        "the accepted change rebuilds what the agent asks, as the editor's save does"
    )

    dismissed = await _http("POST", f"{base}/{new.id}/dismiss", token, slug)
    assert dismissed.status_code == 200 and dismissed.json()["remaining"]["suggestions"] == []
    stored = await _scalar(
        tenant_id, "SELECT field_suggestions_dismissed FROM agents WHERE id = :a", a=agent_id
    )
    assert stored == [new.id]
    again = await _http("POST", f"{base}/{new.id}/accept", token, slug)
    assert again.status_code == 404


async def test_a_suggestion_the_owner_overtook_is_hidden_and_refused() -> None:
    tenant_id, slug, token, agent_id = await _bhk_agent()
    (add,) = await _seed(tenant_id, agent_id, _item("add_choices", values=["6BHK"]))
    async with tenant_session(tenant_id) as session:
        await write_schema(session, agent_id=agent_id, fields=[AREA])
    base = f"/v1/agents/{agent_id}/lead-suggestions"
    assert (await _http("GET", base, token, slug)).json()["suggestions"] == []
    refused = await _http("POST", f"{base}/{add.id}/accept", token, slug)
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/suggestion_out_of_date")


async def test_staff_cannot_answer_and_nobody_reaches_another_accounts_agent() -> None:
    theirs, _s, _t, their_agent = await _bhk_agent()
    (add,) = await _seed(theirs, their_agent, _item("add_choices", values=["6BHK"]))
    _mine, slug, staff = await _make_tenant(role="staff")
    base = f"/v1/agents/{their_agent}/lead-suggestions"
    assert (await _http("POST", f"{base}/{add.id}/accept", staff, slug)).status_code == 403
    _owner_tenant, owner_slug, owner = await _make_tenant()
    assert (await _http("GET", base, owner, owner_slug)).status_code == 404
    assert (await _http("POST", f"{base}/{add.id}/accept", owner, owner_slug)).status_code == 404
    assert (await _http("POST", f"{base}/{add.id}/dismiss", owner, owner_slug)).status_code == 404
    assert (await _fields(theirs, their_agent))[1][0]["enum_values"] == BHK.enum_values


async def test_check_again_queues_a_fresh_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, trial=True, model=_Model())
    _tenant_id, slug, token, agent_id = await _bhk_agent()
    checked = await _http("POST", f"/v1/agents/{agent_id}/lead-suggestions/check", token, slug)
    assert checked.status_code == 202 and checked.json()["state"] == "queued"
    assert len(await _jobs(field_suggestions.JOB, agent_id)) == 1


async def test_an_operator_reads_and_answers_a_clients_suggestions() -> None:
    tenant_id, _slug, _token, agent_id = await _bhk_agent()
    (add,) = await _seed(tenant_id, agent_id, _item("add_choices", values=["6BHK"]))
    base = f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/lead-suggestions"
    _admin_id, headers = await _operator()
    operator = headers["Authorization"].removeprefix("Bearer ")
    got = await _http("GET", base, operator)
    assert got.status_code == 200, got.text
    assert [s["id"] for s in got.json()["suggestions"]] == [add.id]
    accepted = await _http("POST", f"{base}/{add.id}/accept", operator)
    assert accepted.status_code == 200, accepted.text
    assert (await _fields(tenant_id, agent_id))[1][0]["enum_values"][-1] == "6BHK"


# --- 6. a real call: stored, shown, counted, erased ---------------------------------------------


async def _call_for(tenant_id: UUID, agent_ref: str) -> tuple[str, UUID]:
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    call_id = await _scalar(
        tenant_id, "SELECT id FROM calls WHERE engine_call_id = :e", e=execution_id
    )
    return execution_id, UUID(str(call_id))


async def test_a_call_keeps_the_callers_words_and_the_second_one_brings_a_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: _Runner(SIX))
    agent_ref = f"fakeagent_six_{uuid.uuid4().hex[:8]}"
    tenant_id, agent_id = await _seed_tenant(agent_ref)
    async with tenant_session(tenant_id) as session:
        await write_schema(session, agent_id=agent_id, fields=[BHK, AREA])

    execution_id, call_id = await _call_for(tenant_id, agent_ref)
    await _run_pipeline(tenant_id, call_id, execution_id)
    stored = await _scalar(
        tenant_id, "SELECT unlisted FROM call_extractions WHERE call_id = :c", c=call_id
    )
    assert stored == {"bhk_size": "6 BHK"}
    async with tenant_session(tenant_id) as session:
        detail = await crm_service.get_call(session, call_id)
        lead_id = await _scalar(tenant_id, "SELECT lead_id FROM calls WHERE id = :c", c=call_id)
        assert await lead_unlisted(session, UUID(str(lead_id))) == {"bhk_size": "6 BHK"}
    (bhk,) = [f for f in detail.captured if f.key == "bhk_size"]
    assert bhk.value is None and bhk.unlisted == "6 BHK"
    assert await _jobs(field_suggestions.JOB, agent_id) == [], "one caller is not yet demand"

    second, second_call = await _call_for(tenant_id, agent_ref)
    await _run_pipeline(tenant_id, second_call, second)
    assert len(await _jobs(field_suggestions.JOB, agent_id)) == 1, "the second caller is"
    third, third_call = await _call_for(tenant_id, agent_ref)
    await _run_pipeline(tenant_id, third_call, third)
    assert len(await _jobs(field_suggestions.JOB, agent_id)) == 1, "the third adds nothing"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(retention._EXTRACTION_SQL),
            {"cutoff": datetime(2999, 1, 1, tzinfo=UTC), "batch": 100},
        )
    assert (
        await _scalar(
            tenant_id, "SELECT unlisted FROM call_extractions WHERE call_id = :c", c=call_id
        )
        is None
    ), "the caller's words are erased with the rest of the extraction"
