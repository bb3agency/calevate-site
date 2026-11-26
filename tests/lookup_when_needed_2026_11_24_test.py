"""Lookups when they were needed (founder, 24 Nov 2026).

"Replies that looked up your information: 0 of 12" read as a failure on a step-by-step call
that needed no lookup. The call page now counts only the replies that needed one: a caller
stuck on a step, a question the agent could not answer, or a business question the script
and the known facts do not cover. A needed reply on a call with no lookup is the mistake
`missed_lookup`, which no script line causes, so the healer writes no script fix for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.agents import turn_checks
from apps.api.agents.call_mistakes import LESSONS, lookup_figures, lookup_mistakes, needs_lookup
from apps.api.agents.script_checks import SCRIPT_FIXABLE_KINDS
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.api.main import app
from apps.workers.pipeline import run_post_call_pipeline
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import CallQuality, TranscriptTurn
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.a2p_declaration_test import _org_headers
from tests.conftest import create_org_with_receptionist, turn_pip_on_for_tests


@dataclass(frozen=True)
class _T:
    idx: int
    speaker: str
    text: str


def _call(*lines: tuple[str, str]) -> list[_T]:
    return [_T(i, who, words) for i, (who, words) in enumerate(lines)]


#: A step-by-step install call: the caller follows each step and never gets stuck.
STEPS = _call(
    ("agent", "Hello, this is Asha from Rytu Khata. Shall I help you set up the app now?"),
    ("caller", "Yes, go ahead."),
    ("agent", "Open the Play Store and search for Rytu Khata."),
    ("caller", "Okay, I opened it."),
    ("agent", "Tap Install, and tell me when it finishes."),
    ("caller", "Done, it is installed."),
    ("agent", "Now open the app and enter your mobile number."),
    ("caller", "Okay, I entered it."),
)

#: The same call with one stuck turn: the option the agent named is not on the screen.
STUCK = _call(
    ("agent", "Hello, this is Asha from Rytu Khata. Shall I help you set up the app now?"),
    ("caller", "Yes, go ahead."),
    ("agent", "Open the app and tap Khata in the menu."),
    ("caller", "I can't find it, the Khata option is not there."),
    ("agent", "Look again at the menu and tap Khata."),
    ("caller", "Okay."),
)

#: A business question, answered.
PRICE = _call(
    ("agent", "Hello, this is Asha from Sri Stores. How can I help?"),
    ("caller", "How much does the cold-pressed oil cost?"),
    ("agent", "One litre is two hundred and forty rupees."),
)


def test_a_step_by_step_call_needs_no_lookup() -> None:
    figures = lookup_figures(STEPS, knowledge_turns=0, replies_counted=3)
    assert (figures.needed, figures.looked_up_min, figures.looked_up_max) == (0, 0, 0)
    assert lookup_mistakes(figures) == {}


def test_a_stuck_turn_with_no_lookup_is_zero_of_one_and_a_mistake() -> None:
    figures = lookup_figures(STUCK, knowledge_turns=0, replies_counted=2)
    assert (figures.needed, figures.looked_up_min, figures.looked_up_max) == (1, 0, 0)
    # The reply to the stuck line is turn 4.
    assert lookup_mistakes(figures) == {"missed_lookup": 4}


def test_a_business_question_answered_with_a_lookup_is_one_of_one() -> None:
    figures = lookup_figures(PRICE, knowledge_turns=1, replies_counted=1)
    assert (figures.needed, figures.looked_up_min, figures.looked_up_max) == (1, 1, 1)
    assert lookup_mistakes(figures) == {}


def test_a_question_the_facts_already_answer_needs_no_lookup() -> None:
    figures = lookup_figures(PRICE, covered={"pricing"}, knowledge_turns=0, replies_counted=1)
    assert figures.needed == 0 and lookup_mistakes(figures) == {}


def test_a_count_that_cannot_say_which_reply_is_a_range_and_no_mistake() -> None:
    """Two lookups on a call of three replies with one needed: that one may or may not have
    had one. Some lookups and fewer than needed is a certain miss on an unknown turn, which
    is not pinned to a line."""
    figures = lookup_figures(STUCK, knowledge_turns=1, replies_counted=3)
    assert (figures.needed, figures.looked_up_min, figures.looked_up_max) == (1, 0, 1)
    assert lookup_mistakes(figures) == {}
    assert lookup_figures(STUCK, knowledge_turns=None).looked_up_max is None


@pytest.mark.parametrize(
    ("said", "reply", "needed"),
    [
        ("I am stuck on this step.", "Tap the green button.", True),
        ("It's not showing on my screen.", "Scroll down a little.", True),
        ("Do you deliver to Guntur?", "I don't know, sorry.", True),
        ("How are you?", "I am well, thank you. Shall we go on?", False),
        ("My husband is not there right now.", "Shall I call back later?", False),
        ("Can you repeat that, I could not hear.", "Tap Install.", False),
        ("That's all, bye.", "Thank you, goodbye.", False),
    ],
)
def test_what_needs_a_lookup(said: str, reply: str, needed: bool) -> None:
    assert needs_lookup(said, reply) is needed


def test_the_mistake_is_an_in_call_kind_the_healer_never_fixes_in_a_script() -> None:
    assert "missed_lookup" in LESSONS and "missed_lookup" in turn_checks.JOB_KINDS
    assert "missed_lookup" in turn_checks.IN_CALL_KINDS
    assert "missed_lookup" not in SCRIPT_FIXABLE_KINDS


# --- end to end: the pipeline records it and the owner reads it -----------------------------


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Lookup Stores",
        slug=f"lkp-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    await turn_pip_on_for_tests(uuid.UUID(str(created["id"])))
    return created["id"], created["agent_id"]


async def _real_call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    lines: list[_T],
    quality: CallQuality,
    monkeypatch: pytest.MonkeyPatch,
) -> uuid.UUID:
    reset_engine_cache()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    call_id = uuid7()
    # The ingest writes the platform's figures on the call before it queues the pipeline.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, engine_quality, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'outbound', 'completed', now(), CAST(:q AS jsonb), now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": execution_id,
                "q": quality.model_dump_json(),
            },
        )
    now = datetime.now(UTC)
    snapshot = ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref="unused-direct-run",
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=59),
        ended_at=now,
        duration_s=59,
        from_e164="+911140000000",
        to_e164="+919876500002",
        recording_url=None,
        transcript=[
            TranscriptTurn(call_id=execution_id, idx=t.idx, speaker=t.speaker, text=t.text)  # type: ignore[arg-type]
            for t in lines
        ],
        quality=quality,
        cost=None,
        engine="fake",
    )

    async def _get(self: FakeEngine, cid: str) -> ExecutionSnapshot:
        return snapshot

    monkeypatch.setattr(FakeEngine, "get_execution", _get)
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )
    return call_id


@pytest.mark.rls
async def test_the_owner_reads_the_lookups_and_the_mistake_and_another_account_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    stuck = await _real_call(
        tenant_id, agent_id, STUCK, CallQuality(turns=2, knowledge_turns=0), monkeypatch
    )
    steps = await _real_call(
        tenant_id, agent_id, STEPS, CallQuality(turns=3, knowledge_turns=0), monkeypatch
    )
    async with tenant_session(tenant_id) as session:
        kinds = (
            await session.execute(
                text("SELECT kind, turn_idx FROM call_mistakes WHERE call_id = :c"), {"c": stuck}
            )
        ).all()
        opened = (
            await session.execute(
                text("SELECT count(*) FROM agent_mistake_fixes WHERE kind = 'missed_lookup'")
            )
        ).scalar_one()
    assert ("missed_lookup", 4) in [tuple(k) for k in kinds]
    # An in-call behaviour: no script fix is opened for it.
    assert opened == 0

    headers = await _org_headers(tenant_id)
    other_id, _other_agent = await _tenant()
    other = await _org_headers(other_id)
    async with _client() as http:
        detail = (await http.get(f"/v1/calls/{stuck}", headers=headers)).json()
        plain = (await http.get(f"/v1/calls/{steps}", headers=headers)).json()
        foreign = await http.get(f"/v1/calls/{stuck}", headers=other)
    quality = detail["quality"]
    assert (
        quality["lookups_needed"],
        quality["lookups_needed_done_min"],
        quality["lookups_needed_done_max"],
    ) == (1, 0, 0)
    mistake = next(m for m in detail["mistakes"] if m["kind"] == "missed_lookup")
    assert mistake["label"] == LESSONS["missed_lookup"].label and mistake["turn_idx"] == 4
    assert plain["quality"]["lookups_needed"] == 0
    assert all(m["kind"] != "missed_lookup" for m in plain["mistakes"])
    assert foreign.status_code == 404
