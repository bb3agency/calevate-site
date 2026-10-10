"""The teach box and the improvement loop (first live call review, founder decisions 9 and 11).

Each test names the failure it guards against: a fact that never reaches the agents, a rule
that changes a live agent without the owner putting it live, a teach box that stops working
when AI help runs out, a test case that copies a caller's raw words, and a neighbour's rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine.test_chat import TestChatTurn
from apps.api.insights import service as gap_service
from apps.api.teach import facts as fact_store
from apps.api.teach import knows, rules, struggles, teaching, test_cases
from apps.workers import agent_test_cases as case_worker
from apps.workers import kb_teach
from sqlalchemy import text
from tests.conftest import accept_agreements

PINNED_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "c2f7e8a4d1b6_quick_facts_become_pinned_facts.py"
)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Raghava Organics",
        slug=f"tests-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Front desk",
            direction="inbound",
            language_primary="te-IN",
        )
    return tenant_id, agent_id


async def _call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, outcome: str | None = None
) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "outcome_tag, headline, started_at, created_at, updated_at) VALUES (:id, :tid, "
                ":aid, :ecid, 'inbound', 'completed', :outcome, 'Asked about chilli', now(), "
                "now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"teach-{call_id.hex}",
                "outcome": outcome,
            },
        )
        for idx, (speaker, raw, redacted) in enumerate(
            [
                ("agent", "Namaskaram", "Namaskaram"),
                (
                    "caller",
                    "naa number 9876543210, chilli undha?",
                    "naa number [phone], chilli undha?",
                ),
                ("agent", "I don't know about chilli, sorry.", "I don't know about chilli, sorry."),
                ("caller", "Delivery Kukatpally ki undha?", "Delivery Kukatpally ki undha?"),
            ]
        ):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:id, :tid, :cid, :idx, "
                    ":speaker, :raw, :red, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "idx": idx,
                    "speaker": speaker,
                    "raw": raw,
                    "red": redacted,
                },
            )
    return call_id


# --- sorting ------------------------------------------------------------------------


def test_the_model_answer_is_cut_to_facts_and_rules_and_nothing_else() -> None:
    items = kb_teach.items_from_model(
        {
            "items": [
                {"kind": "fact", "text": "  Red chilli powder is ₹120 for 250 g. "},
                {"kind": "rule", "text": "Never promise same-day delivery."},
                {"kind": "opinion", "text": "We are the best."},
                {"kind": "fact", "text": ""},
                {"kind": "fact", "text": "red chilli powder is ₹120 for 250 g."},
                "not an item",
            ]
        }
    )
    assert items == [
        {"kind": "fact", "text": "Red chilli powder is ₹120 for 250 g."},
        {"kind": "rule", "text": "Never promise same-day delivery."},
    ]


def test_unsorted_words_come_back_line_by_line_and_never_over_the_fact_limit() -> None:
    long_line = "Turmeric is fresh. " * 40
    items = kb_teach.unsorted_items(f"We open at 9.\n\n{long_line}")
    assert items[0] == {"kind": "fact", "text": "We open at 9."}
    assert all(item["kind"] == "fact" for item in items)
    assert all(0 < len(item["text"]) <= 500 for item in items)


def test_the_sorting_instruction_forbids_inventing_or_changing_facts() -> None:
    prompt = kb_teach.SYSTEM_PROMPT
    assert "Never add anything the owner did not say" in prompt
    assert "never change a number, price, name or time" in prompt


# --- facts ----------------------------------------------------------------------------


async def test_a_saved_fact_becomes_a_version_of_the_one_facts_source() -> None:
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        added = await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=["We deliver in Kukatpally.", "we deliver in kukatpally.", "Open 9 to 9."],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
        assert len(added) == 2
        source = (
            await session.execute(
                text(
                    "SELECT s.status, s.version, string_agg(d.content, '|' ORDER BY d.idx) "
                    "FROM kb_sources s JOIN kb_documents d ON d.source_id = s.id "
                    "WHERE s.name = :name GROUP BY s.id ORDER BY s.version DESC LIMIT 1"
                ),
                {"name": fact_store.FACTS_SOURCE_NAME},
            )
        ).one()
        assert source[0] == "approved"
        assert "We deliver in Kukatpally." in source[2] and "Open 9 to 9." in source[2]
        # The publish is queued with the version, so every agent receives it.
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = 'publish_kb_source' "
                    "AND payload->>'tenant_id' = :tid"
                ),
                {"tid": str(tenant_id)},
            )
        ).scalar()
        assert queued and queued >= 1

        await fact_store.remove_fact(
            session, tenant_id=tenant_id, fact_id=added[0], removed_by=None, auto_approve=True
        )
        await fact_store.remove_fact(
            session, tenant_id=tenant_id, fact_id=added[1], removed_by=None, auto_approve=True
        )
        latest = (
            await session.execute(
                text(
                    "SELECT d.content FROM kb_sources s JOIN kb_documents d ON d.source_id = s.id "
                    "WHERE s.name = :name ORDER BY s.version DESC LIMIT 1"
                ),
                {"name": fact_store.FACTS_SOURCE_NAME},
            )
        ).scalar()
        assert latest == fact_store.NO_FACTS_BODY
        assert await fact_store.list_facts(session) == []


async def test_a_pinned_fact_is_listed_first_and_marked() -> None:
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=["Open 9 to 9."],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
        await session.execute(
            text(
                "INSERT INTO kb_facts (id, tenant_id, text, pinned, origin, created_at, "
                "updated_at) VALUES (:id, :tid, 'Closed on Sundays.', true, 'quick_fact', "
                "now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id},
        )
        found = await knows.what_it_knows(session)
    assert [f.text for f in found.facts] == ["Closed on Sundays.", "Open 9 to 9."]
    assert found.facts[0].pinned and found.facts[0].origin == "quick_fact"
    assert found.facts_state == "publishing"


# --- the teach box --------------------------------------------------------------------


async def test_teaching_without_ai_still_reaches_review_with_the_words_unsorted() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        started = await teaching.start_teaching(
            session,
            tenant_id=tenant_id,
            input_kind="text",
            words=teaching.clean_words("Chilli powder 120 rupees.\nAlways greet in Telugu."),
            requested_by=None,
        )
    outcome = await kb_teach.run_kb_teaching(
        {}, {"tenant_id": str(tenant_id), "teaching_id": str(started.id)}
    )
    assert outcome == "ready"
    async with tenant_session(tenant_id) as session:
        ready = await teaching.get_teaching(session, started.id)
    assert ready.status == "ready"
    assert [i.text for i in ready.items] == ["Chilli powder 120 rupees.", "Always greet in Telugu."]
    assert ready.disclosure  # the screen says why it is not sorted

    # The owner marks the second line as a rule and saves.
    async with tenant_session(tenant_id) as session:
        saved = await teaching.save(
            session,
            tenant_id=tenant_id,
            teaching_id=started.id,
            items=[
                teaching.TeachItem(kind="fact", text="Chilli powder 120 rupees."),
                teaching.TeachItem(kind="rule", text="Always greet in Telugu."),
            ],
            agent_id=agent_id,
            saved_by=None,
            client_user_id=None,
            auto_approve=True,
        )
        assert (saved.facts_added, saved.rules_added) == (1, 1)
        waiting = await rules.list_rules(session, agent_id=agent_id)
        assert [r.text for r in waiting] == ["Always greet in Telugu."]
        with pytest.raises(ProblemError) as again:
            await teaching.save(
                session,
                tenant_id=tenant_id,
                teaching_id=started.id,
                items=[teaching.TeachItem(kind="fact", text="x y z")],
                agent_id=None,
                saved_by=None,
                client_user_id=None,
                auto_approve=True,
            )
        assert again.value.code == "teaching_not_ready"


async def test_a_rule_cannot_be_saved_without_naming_its_agent() -> None:
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        started = await teaching.start_teaching(
            session, tenant_id=tenant_id, input_kind="text", words="Be polite.", requested_by=None
        )
        await session.execute(
            text("UPDATE kb_teachings SET status = 'ready' WHERE id = :id"), {"id": started.id}
        )
        with pytest.raises(ProblemError) as refused:
            await teaching.save(
                session,
                tenant_id=tenant_id,
                teaching_id=started.id,
                items=[teaching.TeachItem(kind="rule", text="Be polite.")],
                agent_id=None,
                saved_by=None,
                client_user_id=None,
                auto_approve=True,
            )
    assert refused.value.code == "teaching_rule_needs_agent"


async def test_a_voice_note_stops_for_the_owner_to_check_the_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _ = await _tenant()
    deleted: list[list[str]] = []

    async def _read(key: str) -> bytes:
        return b"voice"

    async def _delete(keys: list[str]) -> int:
        deleted.append(keys)
        return len(keys)

    async def _stt(data: bytes, content_type: str) -> str:
        assert content_type == "audio/webm"
        return "Chilli 250 grams 120 rupees"

    monkeypatch.setattr(kb_teach, "read_kb_object", _read)
    monkeypatch.setattr(kb_teach, "delete_objects", _delete)
    monkeypatch.setattr(kb_teach, "transcribe_voice", _stt)
    async with tenant_session(tenant_id) as session:
        started = await teaching.start_teaching(
            session,
            tenant_id=tenant_id,
            input_kind="voice",
            words=None,
            object_key="kb-uploads/x/y/teach.webm",
            content_type="audio/webm",
            filename="voice-note",
            requested_by=None,
        )
    payload = {"tenant_id": str(tenant_id), "teaching_id": str(started.id)}
    assert await kb_teach.run_kb_teaching({}, payload) == "heard"
    assert deleted == [["kb-uploads/x/y/teach.webm"]]
    async with tenant_session(tenant_id) as session:
        heard = await teaching.get_teaching(session, started.id)
        assert heard.status == "heard" and heard.words == "Chilli 250 grams 120 rupees"
        assert heard.items == []
        await teaching.confirm_words(
            session, tenant_id=tenant_id, teaching_id=started.id, words="Chilli 250 g is ₹120."
        )
    assert await kb_teach.run_kb_teaching({}, payload) == "ready"
    async with tenant_session(tenant_id) as session:
        ready = await teaching.get_teaching(session, started.id)
    assert [i.text for i in ready.items] == ["Chilli 250 g is ₹120."]


async def test_an_unreadable_voice_note_fails_with_a_code_and_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _ = await _tenant()

    async def _read(key: str) -> bytes:
        return b"voice"

    async def _stt(data: bytes, content_type: str) -> str:
        raise RuntimeError("no speech-to-text credential")

    monkeypatch.setattr(kb_teach, "read_kb_object", _read)
    monkeypatch.setattr(kb_teach, "transcribe_voice", _stt)
    async with tenant_session(tenant_id) as session:
        started = await teaching.start_teaching(
            session,
            tenant_id=tenant_id,
            input_kind="voice",
            words=None,
            object_key="kb-uploads/x/y/teach.webm",
            content_type="audio/webm",
            filename="voice-note",
            requested_by=None,
        )
    payload = {"tenant_id": str(tenant_id), "teaching_id": str(started.id)}
    assert await kb_teach.run_kb_teaching({}, payload) == "failed"
    async with tenant_session(tenant_id) as session:
        failed = await teaching.get_teaching(session, started.id)
    assert (failed.status, failed.error_code) == ("failed", "voice_unreadable")


# --- where it struggled, and answering it ------------------------------------------------


@dataclass(frozen=True)
class _Turn:
    speaker: Any
    text: str


async def test_struggles_link_to_the_call_and_answering_one_closes_it() -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id)
    await gap_service.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        turns=[
            _Turn("caller", "Do you have chilli powder?"),
            _Turn("agent", "Sorry, I don't know about that."),
        ],
    )
    needs_you = await _call(tenant_id, agent_id, outcome="needs_you")
    async with tenant_session(tenant_id) as session:
        found = await struggles.list_struggles(session)
    by_kind = {s.kind: s for s in found}
    gap = by_kind["didnt_know"]
    assert gap.last_call_id == call_id and gap.gap_id is not None
    assert by_kind["needed_you"].last_call_id == needs_you

    async with tenant_session(tenant_id) as session:
        started = await teaching.start_teaching(
            session,
            tenant_id=tenant_id,
            input_kind="text",
            words="We sell chilli powder.",
            gap_id=gap.gap_id,
            requested_by=None,
        )
        await session.execute(
            text("UPDATE kb_teachings SET status = 'ready' WHERE id = :id"), {"id": started.id}
        )
        await teaching.save(
            session,
            tenant_id=tenant_id,
            teaching_id=started.id,
            items=[teaching.TeachItem(kind="fact", text="We sell chilli powder.")],
            agent_id=None,
            saved_by=None,
            client_user_id=None,
            auto_approve=True,
        )
        origin = (
            await session.execute(text("SELECT origin FROM kb_facts WHERE removed_at IS NULL"))
        ).scalar()
        assert origin == "call_gap"
        after = await struggles.list_struggles(session)
    assert all(s.gap_id != gap.gap_id for s in after)


# --- make this call a test --------------------------------------------------------------


class _FakeChat:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None]] = []

    async def test_chat(
        self, ref: str, message: str, *, session: str | None = None
    ) -> TestChatTurn:
        self.sent.append((message, session))
        return TestChatTurn(
            session="vr_1", reply=f"reply to {message}", tools=("search_knowledge",)
        )


async def test_a_test_from_a_call_takes_only_the_callers_redacted_lines_and_reruns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        draft = await test_cases.draft_from_call(session, call_id)
        assert draft.agent_id == agent_id
        assert draft.caller_lines == [
            "naa number [phone], chilli undha?",
            "Delivery Kukatpally ki undha?",
        ]
        assert all("9876543210" not in line for line in draft.caller_lines)
        case = await test_cases.create_case(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            agent_id=None,
            title=draft.title,
            caller_lines=draft.caller_lines,
            expected="Looks up chilli in knowledge and gives the price.",
            created_by=None,
        )
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_test' WHERE id = :id"), {"id": agent_id}
        )
        await session.execute(
            text("UPDATE agent_test_cases SET status = 'queued' WHERE id = :id"), {"id": case.id}
        )

    fake = _FakeChat()

    async def _no_pause() -> None:
        return None

    monkeypatch.setattr(case_worker, "get_engine", lambda: fake)
    monkeypatch.setattr(case_worker, "_pause", _no_pause)
    monkeypatch.setattr(
        case_worker,
        "hosted_agent_limits",
        lambda engine: type("L", (), {"knowledge_tool": "search_knowledge"})(),
    )
    outcome = await case_worker.run_agent_test_cases(
        {}, {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    )
    assert outcome == "done"
    # One conversation: the second line continues the session the first opened.
    assert fake.sent == [
        ("naa number [phone], chilli undha?", None),
        ("Delivery Kukatpally ki undha?", "vr_1"),
    ]
    async with tenant_session(tenant_id) as session:
        [stored] = await test_cases.list_cases(session, agent_id)
    assert stored.status == "idle" and stored.last_result is not None
    assert stored.last_result[0]["looked_up_knowledge"] is True

    async with tenant_session(tenant_id) as session:
        # What the DPDP erasure runs for an erased caller's calls (`workers/retention`).
        await session.execute(
            text("DELETE FROM agent_test_cases WHERE source_call_id = ANY(:ids)"),
            {"ids": [call_id]},
        )
        assert await test_cases.list_cases(session, agent_id) == []


# --- isolation ------------------------------------------------------------------------


@pytest.mark.rls
async def test_one_business_never_sees_anothers_teachings_facts_rules_or_tests() -> None:
    tenant_a, agent_a = await _tenant()
    tenant_b, _ = await _tenant()
    call_a = await _call(tenant_a, agent_a)
    async with tenant_session(tenant_a) as session:
        await fact_store.add_facts(
            session,
            tenant_id=tenant_a,
            texts=["Secret price list."],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
        started = await teaching.start_teaching(
            session, tenant_id=tenant_a, input_kind="text", words="abc def", requested_by=None
        )
        await rules.propose_rules(
            session,
            tenant_id=tenant_a,
            agent_id=agent_a,
            texts=["Be brief."],
            teaching_id=started.id,
            created_by=None,
        )
        await test_cases.create_case(
            session,
            tenant_id=tenant_a,
            call_id=call_a,
            agent_id=None,
            title="t",
            caller_lines=["hello"],
            expected="greets",
            created_by=None,
        )
    async with tenant_session(tenant_b) as session:
        for table in ("kb_facts", "kb_teachings", "agent_rule_proposals", "agent_test_cases"):
            seen = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"), {"a": tenant_a}
                )
            ).scalar()
            assert seen == 0, table
        assert (await knows.what_it_knows(session)).facts == []
        assert await rules.list_rules(session, agent_id=agent_a) == []
        assert await test_cases.list_cases(session, agent_a) == []
        with pytest.raises(ProblemError):
            await teaching.get_teaching(session, started.id)
        with pytest.raises(ProblemError):
            await test_cases.draft_from_call(session, call_a)


# --- pinned facts (the old quick facts, founder decision 9) ---------------------------------


def test_splicing_replaces_any_quick_facts_or_old_faq_and_keeps_everything_else() -> None:
    from calevate_shared.call_script import QUICK_FACTS_LEAD, splice_quick_facts

    body = (
        "[IDENTITY]\nYou answer for Raghava.\n\n[FAQ] Answer ONLY from these.\nQ: old\nA: old\n\n"
        "[QUICK FACTS] These win.\nQ: stale\nA: stale\n\n[T0 FACTS]\nHours: 9-9"
    )
    spliced = splice_quick_facts(
        body, [("Do you deliver?", "Yes, in Kukatpally."), ("", "Closed Sunday.")]
    )
    assert "old" not in spliced and "stale" not in spliced
    assert spliced.count(QUICK_FACTS_LEAD) == 1
    assert "Q: Do you deliver?\nA: Yes, in Kukatpally.\n- Closed Sunday." in spliced
    assert spliced.startswith("[IDENTITY]\nYou answer for Raghava.")
    assert spliced.endswith("[T0 FACTS]\nHours: 9-9")
    # No pinned facts: the section goes, nothing else moves.
    assert (
        splice_quick_facts(spliced, [])
        == "[IDENTITY]\nYou answer for Raghava.\n\n[T0 FACTS]\nHours: 9-9"
    )
    # Without a facts block the section goes at the end.
    assert splice_quick_facts("[IDENTITY]\nHi", [("", "Open 9.")]).endswith("- Open 9.")


async def test_the_migration_copies_every_quick_fact_once_per_business() -> None:
    import importlib.util

    from apps.api.agents.prompts import insert_prompt_version

    spec = importlib.util.spec_from_file_location("pinned_migration", PINNED_MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    tenant_id, agent_a = await _tenant()
    long_answer = "A" * 1800
    async with tenant_session(tenant_id) as session:
        agent_b = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Orders",
            direction="outbound",
            language_primary="te-IN",
        )
        for agent_id, faqs in (
            (
                agent_a,
                [
                    {"question": "Hours?", "answer": "9 to 9"},
                    {"question": "Long?", "answer": long_answer},
                ],
            ),
            (
                agent_b,
                [
                    {"question": " hours? ", "answer": "9 TO 9"},
                    {"question": "Delivery?", "answer": "Yes"},
                ],
            ),
        ):
            await insert_prompt_version(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                body="[IDENTITY]\nx",
                notes=None,
                created_by=None,
                structured_script={"schema_version": 2, "faqs": faqs},
                apply_live=True,
            )
        await session.execute(text("DELETE FROM kb_facts"))
        await session.execute(text(migration._COPY))
        copied = await fact_store.list_facts(session, pinned=True)
    assert [(f.question, f.text) for f in copied] == [
        ("Hours?", "9 to 9"),
        ("Long?", long_answer),
        ("Delivery?", "Yes"),
    ]
    assert all(f.origin == "quick_fact" for f in copied)


async def test_a_script_save_moves_its_quick_facts_into_pinned_facts_and_splices_them() -> None:
    from apps.api.agents import script_builder
    from apps.api.teach import pinned as pinned_store
    from calevate_shared.call_script import CallScript, FaqEntry

    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(
                schema_version=2,
                identity="You answer for Raghava Organics.",
                faqs=[FaqEntry(question="Do you deliver?", answer="Yes, in Kukatpally.")],
            ),
            notes=None,
            created_by=None,
        )
        pinned = await pinned_store.list_pinned(session)
        assert [(p.question, p.answer) for p in pinned] == [
            ("Do you deliver?", "Yes, in Kukatpally.")
        ]
        loaded = await script_builder.load_agent_script(session, agent_id)
        assert loaded.script.faqs == []
        body = (
            await session.execute(
                text(
                    "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.system_prompt_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
        assert "Q: Do you deliver?\nA: Yes, in Kukatpally." in body

        # The owner edits the pinned fact in Knowledge: the agent is re-spliced.
        await fact_store.update_fact(
            session,
            tenant_id=tenant_id,
            fact_id=pinned[0].id,
            text_value="Yes, anywhere in Hyderabad.",
            question=None,
            pinned=None,
            edited_by=None,
            auto_approve=True,
        )
        assert await pinned_store.recompile_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        body = (
            await session.execute(
                text(
                    "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.system_prompt_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
        assert "A: Yes, anywhere in Hyderabad." in body and "Kukatpally" not in body
        assert (
            await pinned_store.recompile_agent(session, tenant_id=tenant_id, agent_id=agent_id)
            is None
        )


async def test_pinned_facts_have_a_ceiling_and_reorder_names_every_fact() -> None:
    from apps.api.teach import pinned as pinned_store

    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        first = await pinned_store.add_pinned(
            session,
            tenant_id=tenant_id,
            question="Hours?",
            answer="9 to 9",
            origin="taught",
            created_by=None,
        )
        second = await pinned_store.add_pinned(
            session,
            tenant_id=tenant_id,
            question=None,
            answer="Closed Sunday.",
            origin="taught",
            created_by=None,
        )
        with pytest.raises(ProblemError) as full:
            await pinned_store.add_pinned(
                session,
                tenant_id=tenant_id,
                question=None,
                answer="x" * 1600,
                origin="taught",
                created_by=None,
            )
        assert full.value.code == "pinned_facts_full"
        await pinned_store.reorder(session, tenant_id=tenant_id, ids=[second, first])
        assert [p.id for p in await pinned_store.list_pinned(session)] == [second, first]
        with pytest.raises(ProblemError):
            await pinned_store.reorder(session, tenant_id=tenant_id, ids=[second])
        # Unpinning moves it to the searched facts source.
        await fact_store.update_fact(
            session,
            tenant_id=tenant_id,
            fact_id=second,
            text_value=None,
            question=None,
            pinned=False,
            edited_by=None,
            auto_approve=True,
        )
        searched = await fact_store.list_facts(session, pinned=False)
        assert [f.text for f in searched] == ["Closed Sunday."]
