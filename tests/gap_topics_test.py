"""Knowledge-gap topics named from the business, not a fixed shop menu (G5-4, L5-16).

FAILS IF: a call's gaps queue no naming job; the model's answer is used when it does not file
every question once, or names a topic with a figure in it; two questions the model files
under one topic stay two gaps; a known topic is not reused by its key; a renaming lands on
gaps a re-drive replaced meanwhile; or no model, no allowance or a refusal changes anything.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

import pytest
from apps.api.core.errors import ProblemError
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.insights import service as gap_service
from apps.workers import gap_topics
from apps.workers.script_assist import JsonAnswer
from sqlalchemy import text
from tests.conftest import accept_agreements, create_org_with_receptionist


@dataclass(frozen=True)
class _Turn:
    speaker: Any
    text: str


KNOWN = {"pricing": "Pricing", "t_soil_testing": "Soil testing"}


def test_a_known_key_is_reused_and_a_new_name_becomes_a_key() -> None:
    raw = {
        "topics": [
            {"n": 2, "key": "pricing", "name": "Prices"},
            {"n": 1, "key": None, "name": " crop  insurance claims "},
            {"n": 3, "key": None, "name": "Soil testing"},
        ]
    }
    assert gap_topics.parse_topics(raw, 3, KNOWN) == [
        ("t_crop_insurance_claims", "Crop insurance claims"),
        ("pricing", "Pricing"),
        ("t_soil_testing", "Soil testing"),
    ]


@pytest.mark.parametrize(
    "raw",
    [
        {"topics": [{"n": 1, "key": None, "name": "Fees"}]},
        {"topics": [{"n": 1, "key": None, "name": "A"}, {"n": 1, "key": None, "name": "B"}]},
        {"topics": [{"n": 1, "key": None, "name": "A"}, {"n": 2, "key": None, "name": "Plan 2"}]},
        {"topics": [{"n": 1, "key": None, "name": "A"}, {"n": 2, "key": None, "name": ""}]},
        {"topics": [{"n": 1, "key": None, "name": "A"}, {"n": 3, "key": None, "name": "B"}]},
        {"topics": "pricing"},
    ],
)
def test_an_answer_that_does_not_file_every_question_once_is_unusable(
    raw: dict[str, Any],
) -> None:
    assert gap_topics.parse_topics(raw, 2, KNOWN) is None


def test_a_name_with_no_letters_a_key_can_hold_is_unusable() -> None:
    assert gap_topics.named_topic("...", KNOWN) is None
    assert gap_topics.named_topic("x" * (gap_topics.MAX_TOPIC_CHARS + 1), KNOWN) is None


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Gap Topics Farm Records",
        slug=f"gt-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id, uuid.UUID(str(created["agent_id"]))


async def _call_with_gaps(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'inbound', 'completed', now(), now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"gt-{call_id.hex}"},
        )
    # Two questions about one thing, phrased so no keyword topic hears either.
    await gap_service.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        turns=[
            _Turn("caller", "Can my soil sample be checked?"),
            _Turn("agent", "I don't know about that."),
            _Turn("caller", "Who examines the earth from my field?"),
            _Turn("agent", "I'm not sure, sorry."),
        ],
    )
    return call_id


async def _topics(tenant_id: uuid.UUID) -> list[tuple[str, str, int]]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT topic_key, topic_label, occurrence_count FROM knowledge_gaps "
                "ORDER BY topic_key"
            )
        )
        return [(str(r[0]), str(r[1]), int(r[2])) for r in rows]


def _model(monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any] | None) -> dict[str, Any]:
    seen: dict[str, Any] = {"asked": 0}

    class _Capability:
        available = True
        reason = None
        disclosure = None

    class _Leg:
        serves_dashboard = True

    async def fake_ask_json(description: str, instruction: str, **kwargs: Any) -> Any:
        seen["asked"] += 1
        seen["prompt"] = description
        seen["gemini_only"] = kwargs["gemini_only"]
        if answer is None:
            raise ProblemError.conflict("assistant_unavailable", "No model.")
        value = kwargs["parse"](answer)
        assert value is not None
        return JsonAnswer(value=value, capability=cast(Any, _Capability()))

    async def nothing(*args: Any, **kwargs: Any) -> None:
        return None

    async def context(tenant_id: uuid.UUID) -> tuple[str, str | None]:
        return ("A free app farmers keep crop records in.", None)

    monkeypatch.setattr(gap_topics, "ask_json", fake_ask_json)
    monkeypatch.setattr(gap_topics, "google_assist_leg", lambda: _Leg())
    monkeypatch.setattr(gap_topics, "require_ai_assist", nothing)
    monkeypatch.setattr(gap_topics, "business_context", context)
    monkeypatch.setattr(crm_assist, "meter_assist", nothing)
    monkeypatch.setattr(crm_assist, "meter_earlier", nothing)
    monkeypatch.setattr(crm_assist, "meter_refusal", nothing)
    return seen


async def test_a_calls_gaps_are_refiled_under_the_topic_the_model_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call_with_gaps(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'call_id' = :cid"
                ),
                {"job": gap_service.NAME_TOPICS_JOB, "cid": str(call_id)},
            )
        ).scalar_one()
    assert queued == 1
    before = await _topics(tenant_id)
    assert len(before) == 2 and all(key.startswith("q_") for key, _, _ in before)

    seen = _model(
        monkeypatch,
        {
            "topics": [
                {"n": 1, "key": None, "name": "Soil testing"},
                {"n": 2, "key": None, "name": "soil testing"},
            ]
        },
    )
    outcome = await gap_topics.name_gap_topics(
        {}, {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "call_id": str(call_id)}
    )
    assert outcome == "named"
    assert seen["gemini_only"] is True
    assert "Can my soil sample be checked?" in seen["prompt"]
    assert "A free app farmers keep crop records in." in seen["prompt"]
    assert await _topics(tenant_id) == [("t_soil_testing", "Soil testing", 2)]

    # The next call's question about the same thing is filed under the business's own topic.
    second = await _call_with_gaps(tenant_id, agent_id)
    seen = _model(
        monkeypatch,
        {
            "topics": [
                {"n": 1, "key": "t_soil_testing", "name": "Soil"},
                {"n": 2, "key": "t_soil_testing", "name": "Soil"},
            ]
        },
    )
    assert "t_soil_testing: Soil testing" in gap_topics.prompt_for(
        "", await gap_topics._known_topics(tenant_id), []
    )
    await gap_topics.name_gap_topics(
        {}, {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "call_id": str(second)}
    )
    assert await _topics(tenant_id) == [("t_soil_testing", "Soil testing", 4)]


async def test_a_renaming_of_gaps_a_redrive_replaced_changes_nothing() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call_with_gaps(tenant_id, agent_id)
    before = await _topics(tenant_id)
    renamed = await gap_service.rename_call_topics(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        named=[("q_something_else", ("t_soil_testing", "Soil testing"))],
    )
    assert renamed is False
    assert await _topics(tenant_id) == before


async def test_without_a_model_the_keyword_topics_stay(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call_with_gaps(tenant_id, agent_id)
    before = await _topics(tenant_id)
    _model(monkeypatch, None)
    outcome = await gap_topics.name_gap_topics(
        {}, {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "call_id": str(call_id)}
    )
    assert outcome == "refused"
    assert await _topics(tenant_id) == before
