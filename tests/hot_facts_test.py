"""Known facts (D-896): the facts an agent knows by heart, chosen per agent by what its callers
ask, spliced into its instructions at publish and cut to fit, never mid-fact."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.agents import hot_facts
from apps.api.agents.hot_facts import (
    ITEM_MAX_CHARS,
    Candidate,
    Evidence,
    block_chars,
    candidates_of,
    choose,
    rank,
    with_known_facts,
)
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import hosted_platform
from apps.api.engine.hosted_platform import THINNEST_LIMITS
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.kb.service import LiveChunk
from calevate_shared.call_script import (
    KNOWN_FACTS_HEADER,
    KNOWN_FACTS_LEAD,
    QUICK_FACTS_LEAD,
    splice_known_facts,
)
from calevate_shared.engine import (
    FACTS_IN_KNOWLEDGE_GUIDANCE,
    FACTS_INLINE_GUIDANCE,
    compose_engine_prompt,
)
from sqlalchemy import text
from tests.lead_columns_test import _tenant
from tests.thinnest_engine_test import _cfg

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)


def _cand(value: str) -> Candidate:
    return Candidate(key=hot_facts.key_of(value), text=value, origin="knowledge")


PRICE = "Dried red chilli costs 450 rupees a kilo."
DELIVERY = "We deliver anywhere in Guntur within two days."
HOURS = "Open every day from 9 in the morning to 8 at night."
ABOUT = "Raghava Organics was started in 2019 by a farming family."


# ------------------------------------------------------------------- the splice


def test_known_facts_go_after_the_quick_facts_and_before_a_per_call_section() -> None:
    body = "\n".join(
        [
            "[IDENTITY]",
            "You are Asha.",
            QUICK_FACTS_LEAD,
            "- Free delivery over 500 rupees.",
            "[ENDING]",
            "Thank {{lead_name}} and say goodbye.",
        ]
    )
    spliced = splice_known_facts(body, [PRICE, "  two\n lines  "])
    lines = spliced.splitlines()
    at = lines.index(KNOWN_FACTS_LEAD)
    assert lines.index(QUICK_FACTS_LEAD) < at < lines.index("[ENDING]")
    assert f"- {PRICE}" in lines and "- two lines" in lines
    # Spliced again with a different list, the old section is replaced, not stacked.
    again = splice_known_facts(spliced, [HOURS])
    assert again.count(KNOWN_FACTS_HEADER) == 1 and PRICE not in again and HOURS in again


def test_with_no_facts_the_body_is_left_byte_identical() -> None:
    body = "[IDENTITY]\nYou are Asha.\n"
    assert splice_known_facts(body, []) == body
    withdrawn = splice_known_facts(splice_known_facts(body, [PRICE]), [])
    assert KNOWN_FACTS_HEADER not in withdrawn and "You are Asha." in withdrawn


# ------------------------------------------------------------------- choosing


def test_candidates_are_whole_deduplicated_items_and_long_ones_stay_searchable() -> None:
    long = "x " * ITEM_MAX_CHARS
    chunk = LiveChunk(
        source="Facts you taught",
        content=f"{PRICE}\n\n{DELIVERY}\n\n{long}\n\nThere are no short facts.",
        gloss=None,
        written_at=NOW,
    )
    out = candidates_of([HOURS, HOURS], [chunk], excluded=["There are no short facts."])
    assert [c.text for c in out] == [HOURS, PRICE, DELIVERY]


def test_what_callers_ask_is_chosen_and_what_nobody_asks_is_looked_up() -> None:
    candidates = [_cand(ABOUT), _cand(HOURS), _cand(PRICE), _cand(DELIVERY)]
    call = uuid.uuid4()
    evidence = [
        Evidence(words="how much is the chilli per kilo", weight=1.0, call_id=call),
        Evidence(words="what is the price of chilli", weight=1.0, call_id=uuid.uuid4()),
        Evidence(words="do you deliver to guntur", weight=0.5, call_id=uuid.uuid4()),
    ]
    ranked = rank(candidates, evidence)
    picked = choose(ranked, budget_chars=10_000)
    assert [c.text for c in picked] == [PRICE, DELIVERY]
    assert picked[0].asks == 2
    # Nobody asked about the founding year or the hours: they are looked up when asked.
    assert ABOUT not in {c.text for c in picked}


def test_an_item_that_does_not_fit_is_skipped_whole_and_a_smaller_one_still_goes_in() -> None:
    big = "Chilli powder, turmeric and coriander prices: " + "chilli " * 60
    candidates = [_cand(big), _cand(PRICE)]
    evidence = [Evidence(words="chilli chilli price", weight=1.0, call_id=uuid.uuid4())]
    budget = block_chars([PRICE])
    picked = choose(rank(candidates, evidence), budget_chars=budget)
    assert [c.text for c in picked] == [PRICE]
    assert all(c.text in (big, PRICE) for c in picked)


def test_a_fact_already_known_keeps_its_place_against_a_near_equal_one() -> None:
    a = _cand("Chilli costs 450 rupees a kilo.")
    b = _cand("Chilli costs 450 rupees per kilo.")
    evidence = [Evidence(words="chilli kilo", weight=1.0)]
    room = block_chars([b.text])  # the longer one: room for either, not both
    assert choose(rank([a, b], evidence, known=[b.key]), budget_chars=room)[0].key == b.key
    assert choose(rank([a, b], evidence, known=[a.key]), budget_chars=room)[0].key == a.key


def test_recent_demand_outweighs_old_demand() -> None:
    assert hot_facts.decay(NOW, now=NOW) == 1.0
    assert hot_facts.decay(NOW - timedelta(days=14), now=NOW) == pytest.approx(0.5)
    assert hot_facts.decay(NOW + timedelta(days=1), now=NOW) == 1.0


# ------------------------------------------------------------------- publish time


def _thinnest() -> ThinnestEngine:
    return ThinnestEngine(api_key="ta_live_test")


def test_known_facts_reach_the_prompt_with_the_answer_first_rule() -> None:
    cfg = _cfg(facts_in_knowledge=True, knowledge_tool="search_knowledge")
    out = with_known_facts(cfg, [PRICE, DELIVERY], _thinnest())
    prompt = compose_engine_prompt(out)
    assert out.facts_inline and f"- {PRICE}" in prompt
    assert FACTS_INLINE_GUIDANCE in prompt and FACTS_IN_KNOWLEDGE_GUIDANCE in prompt
    assert "only for what they do not cover" in prompt
    assert "before answering about the business" not in prompt


def test_switched_off_the_prompt_is_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg(facts_in_knowledge=True, knowledge_tool="search_knowledge")
    monkeypatch.setattr(get_settings(), "hot_facts_enabled", False)
    out = with_known_facts(cfg, [PRICE], _thinnest())
    assert compose_engine_prompt(out) == compose_engine_prompt(cfg)


def test_the_console_ceiling_and_the_engine_limit_cut_whole_facts_from_the_least_asked_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg(facts_in_knowledge=True, knowledge_tool="search_knowledge")
    monkeypatch.setattr(get_settings(), "hot_facts_max_chars", block_chars([PRICE, DELIVERY]))
    out = with_known_facts(cfg, [PRICE, DELIVERY, HOURS], _thinnest())
    assert f"- {DELIVERY}" in (out.system_prompt or "") and HOURS not in (out.system_prompt or "")

    # A script that leaves almost no room under the engine's limit: the facts give way.
    limit = THINNEST_LIMITS.prompt_chars
    assert limit is not None
    monkeypatch.setattr(get_settings(), "hot_facts_max_chars", 12_000)
    room = limit - len(compose_engine_prompt(cfg)) - 40
    padded = cfg.model_copy(update={"system_prompt": (cfg.system_prompt or "") + "a" * room})
    fitted = with_known_facts(padded, [PRICE, DELIVERY], _thinnest())
    assert len(compose_engine_prompt(fitted)) <= limit
    assert PRICE not in (fitted.system_prompt or "")


def test_an_engine_that_holds_the_facts_in_the_prompt_is_untouched() -> None:
    from apps.api.engine import get_engine

    engine = get_engine()
    assert engine.name != "thinnest"
    cfg = _cfg()
    assert with_known_facts(cfg, [PRICE], engine) is cfg


# ------------------------------------------------------------------- the store


async def _agent_with_script(tenant_id: uuid.UUID, agent_id: uuid.UUID, body: str) -> None:
    async with tenant_session(tenant_id) as session:
        pv = uuid7()
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, tenant_id, agent_id, version, body, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, 1, :body, now(), now())"
            ),
            {"id": pv, "tid": tenant_id, "aid": agent_id, "body": body},
        )
        await session.execute(
            text("UPDATE agents SET system_prompt_id = :pv, status = 'draft' WHERE id = :aid"),
            {"pv": pv, "aid": agent_id},
        )
        source = uuid7()
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, kind, name, status, version, is_active, "
                "created_at, updated_at) VALUES (:i, :t, 'text', 'Facts you taught', "
                "'approved', 1, true, now(), now())"
            ),
            {"i": source, "t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO kb_documents (id, tenant_id, source_id, idx, content, created_at, "
                "updated_at) VALUES (:id, :tid, :sid, 0, :c, now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "sid": source, "c": f"{PRICE}\n\n{ABOUT}"},
        )
        call = uuid7()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :e, 'inbound', "
                "'completed', now(), now(), now())"
            ),
            {"id": call, "tid": tenant_id, "aid": agent_id, "e": f"hf-{call.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:id, :tid, :cid, 0, 'caller', "
                "'chilli price enta', 'chilli price enta', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "cid": call},
        )


async def test_a_choice_is_stored_per_agent_and_a_second_run_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.engine import get_engine

    monkeypatch.setitem(hosted_platform._LIMITS_BY_ENGINE, "fake", THINNEST_LIMITS)
    t = await _tenant()
    await _agent_with_script(t.tenant_id, t.agent_id, "[IDENTITY]\nYou sell chilli.")
    engine = get_engine()
    async with tenant_session(t.tenant_id) as session:
        first = await hot_facts.recompute_agent(
            session, tenant_id=t.tenant_id, agent_id=t.agent_id, engine=engine
        )
    async with tenant_session(t.tenant_id) as session:
        second = await hot_facts.recompute_agent(
            session, tenant_id=t.tenant_id, agent_id=t.agent_id, engine=engine
        )
        stored = await hot_facts.load(session, agent_id=t.agent_id)
        seen = await hot_facts.view(
            session, tenant_id=t.tenant_id, agent_id=t.agent_id, engine=engine
        )
    assert (first, second) == ("changed", "unchanged")
    assert stored is not None and [i.text for i in stored.items] == [PRICE]
    assert stored.items[0].asks == 1 and stored.calls_read == 1
    assert [i.text for i in seen.by_heart] == [PRICE]
    assert seen.looked_up == (ABOUT,) and seen.looked_up_total == 1

    # Another client sees none of it (hard rule 1).
    other = await _tenant()
    async with tenant_session(other.tenant_id) as session:
        rows = (await session.execute(text("SELECT count(*) FROM agent_hot_facts"))).scalar()
    assert rows == 0


def test_the_voice_stamp_records_what_the_config_carried() -> None:
    from apps.api.agents.voice_stamp import stamp_of

    cfg = _cfg(facts_in_knowledge=True, turn_detection="ear", early_answers=False)
    stamp = stamp_of(with_known_facts(cfg, [PRICE], _thinnest()), _thinnest())
    assert stamp["turn_detection"] == "ear" and stamp["early_answers"] is False
    assert stamp["filler_delay_ms"] == 2000  # `thinnest.PLATFORM_VOICE_VALUES`
    assert stamp["known_facts"] is True and stamp["known_facts_chars"] > len(PRICE)
    assert stamp_of(cfg, _thinnest())["known_facts"] is False


async def test_a_publish_stamps_the_agent_with_its_voice_settings() -> None:
    from apps.api.agents.service import publish_agent
    from tests.publish_lifecycle_test import _publishable_tenant

    tenant_id, agent_id = await _publishable_tenant()
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    async with tenant_session(tenant_id) as session:
        stamp = (
            await session.execute(
                text("SELECT voice_settings FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).scalar_one()
    assert stamp["turn_detection"] == get_settings().thinnest_turn_detection
    assert stamp["known_facts"] is False  # the test engine holds the facts in the prompt


async def test_pip_reads_what_an_agent_knows_by_heart(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.copilot.console_reads import CONSOLE_READ_TOOLS, _agent_known_facts
    from apps.api.copilot.tools import ToolContext
    from apps.api.engine import get_engine

    tool = next(t for t in CONSOLE_READ_TOOLS if t.name == "agent_known_facts")
    assert tool.permission == "agents:read"
    monkeypatch.setitem(hosted_platform._LIMITS_BY_ENGINE, "fake", THINNEST_LIMITS)
    t = await _tenant()
    await _agent_with_script(t.tenant_id, t.agent_id, "[IDENTITY]\nYou sell chilli.")
    context = ToolContext(tenant_id=t.tenant_id, role="owner")
    async with tenant_session(t.tenant_id) as session:
        await hot_facts.recompute_agent(
            session, tenant_id=t.tenant_id, agent_id=t.agent_id, engine=get_engine()
        )
        answer = await _agent_known_facts(session, context, {"agent_id": str(t.agent_id)})
        missing = await _agent_known_facts(session, context, {"agent_id": "nope"})
    assert "Knows 1 fact(s) by heart and looks up 1 other(s)" in answer
    assert PRICE in answer
    assert "missing" in missing


async def test_the_known_facts_route_answers_for_the_clients_own_agent_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from apps.api.main import app

    monkeypatch.setitem(hosted_platform._LIMITS_BY_ENGINE, "fake", THINNEST_LIMITS)
    t, stranger = await _tenant(), await _tenant()
    await _agent_with_script(t.tenant_id, t.agent_id, "[IDENTITY]\nYou sell chilli.")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        empty = await client.get(f"/v1/agents/{t.agent_id}/known-facts", headers=t.headers)
        assert empty.status_code == 200
        body = empty.json()
        assert body["by_heart"] == [] and body["computed_at"] is None
        assert body["looked_up_total"] == 2
        refused = await client.get(f"/v1/agents/{t.agent_id}/known-facts", headers=stranger.headers)
    assert refused.status_code == 404


async def test_a_first_empty_choice_republishes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switched off, an agent with no stored choice was published with no known facts, so
    the first sweep must not republish it."""
    from apps.api.agents import service as agent_service
    from apps.api.engine import get_engine

    monkeypatch.setitem(hosted_platform._LIMITS_BY_ENGINE, "fake", THINNEST_LIMITS)
    monkeypatch.setattr(get_settings(), "hot_facts_enabled", False)
    published: list[uuid.UUID] = []

    async def _publish(_session: object, *, agent_id: uuid.UUID, **_: object) -> None:
        published.append(agent_id)

    monkeypatch.setattr(agent_service, "publish_agent", _publish)
    t = await _tenant()
    await _agent_with_script(t.tenant_id, t.agent_id, "[IDENTITY]\nYou sell chilli.")
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', engine_agent_ref = 'ref-hf' WHERE id = :a"),
            {"a": t.agent_id},
        )
        outcome = await hot_facts.recompute_agent(
            session, tenant_id=t.tenant_id, agent_id=t.agent_id, engine=get_engine()
        )
        stored = await hot_facts.load(session, agent_id=t.agent_id)
    assert outcome == "unchanged" and published == []
    assert stored is not None and stored.items == ()
