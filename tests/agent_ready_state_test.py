"""D-838: the agents lane of the founder's 20 Oct 2026 decisions.

WHAT IS UNDER TEST:

1. **Ready, not taking calls.** `POST /v1/agents/{id}/prepare` publishes a draft so it can be
   tried in the chat, binds no number, leaves it non-live, asks no business-profile facts and
   is allowed for a free trial's answer-only agent; a live agent is left as it is.
2. **A main-language change rewrites the three notices** in the same transaction, and the
   opening line is only offered (into the draft).
3. **A builder save rebases over the platform's own recompiles** instead of refusing with
   `script_changed_elsewhere`, and still refuses a colleague's authored change.
4. **Pinned facts not yet on an agent are named**, with the reason.
5. **A contact who takes calls is asked only of an agent that needs one.**
6. **A promotional campaign is refused** while the telemarketer registration is not live.
7. **A refused apply after "Put it live" says the version is saved** and how to finish.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import lifecycle, publishing, script_builder, starters
from apps.api.agents.routes import router as agents_router
from apps.api.agents.script_routes import router as script_router
from apps.api.billing.trials import start_trial
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.disclosure import (
    ai_disclosure_for,
    caller_memory_notice_for,
    recording_notice_for,
)
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import tenant_session
from apps.api.teach import pinned as pinned_store
from apps.api.tenancy import business_profile as bp
from calevate_shared.call_script import CallScript
from calevate_shared.spoken_style import opening_in
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_lifecycle_test import _code, _fresh_engine, _number, _tenant, _write_script
from tests.tm_registration_test import _with_platform_tm

pytestmark = pytest.mark.asyncio


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(agents_router)
    application.include_router(script_router)
    assert_policy_registry_complete(application)
    return application


async def _post(token: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        response = await http.post(
            path, json=body or {}, headers={"Authorization": f"Bearer {token}"}
        )
    return response.status_code, response.json()


async def _agent(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT status, engine_agent_ref, language_primary, ai_disclosure_line, "
                    "recording_notice_line, caller_memory_notice_line, disclosure_line, "
                    "ai_disclosure_enabled, recording_notice_enabled FROM agents WHERE id = :a"
                ),
                {"a": agent_id},
            )
        ).one()


async def _empty_profile(tenant_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM business_profiles WHERE tenant_id = :t"), {"t": tenant_id}
        )


# --- 1. ready, not taking calls -----------------------------------------------------------


async def test_getting_ready_publishes_without_taking_a_call() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await _number(tenant_id, agent_id, ref="num_ready_1")
    await _empty_profile(tenant_id)

    code, body = await _post(token, f"/v1/agents/{agent_id}/prepare")
    assert code == 200, body
    assert (body["status"], body["changed"]) == ("paused", True)
    row = await _agent(tenant_id, agent_id)
    assert row.status == "paused" and row.engine_agent_ref, "not published to the engine"
    assert engine.inbound_agent_for("num_ready_1") is None, "a ready agent answers its number"

    # Again: republished as it stands, no move recorded.
    code, body = await _post(token, f"/v1/agents/{agent_id}/prepare")
    assert (code, body["status"], body["changed"]) == (200, "paused", False)

    # Going live still asks the business facts that getting ready did not.
    code, body = await _post(token, f"/v1/agents/{agent_id}/activate")
    assert (code, _code(body)) == (409, "business_profile_incomplete"), body


async def test_a_live_agent_is_left_on_its_line() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await _number(tenant_id, agent_id, ref="num_ready_2")
    code, body = await _post(token, f"/v1/agents/{agent_id}/activate")
    assert code == 200, body
    code, body = await _post(token, f"/v1/agents/{agent_id}/prepare")
    assert (code, body["status"], body["changed"]) == (200, "live", False)
    assert engine.inbound_agent_for("num_ready_2") is not None


async def test_a_trial_answer_only_agent_can_be_readied_but_not_switched_on() -> None:
    _fresh_engine()
    tenant_id, _, token = await _tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Desk",
            direction="inbound",
            language_primary="te-IN",
        )
        await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)
    await _write_script(tenant_id, agent_id)

    code, body = await _post(token, f"/v1/agents/{agent_id}/prepare")
    assert code == 200, body
    code, body = await _post(token, f"/v1/agents/{agent_id}/activate")
    assert (code, _code(body)) == (422, "trial_inbound_unavailable"), body
    assert (await _agent(tenant_id, agent_id)).status == "paused"


async def test_a_trial_sees_answer_my_calls_locked_with_the_reason() -> None:
    tenant_id, _, token = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        before = (
            await http.get("/v1/agents/starters", headers={"Authorization": f"Bearer {token}"})
        ).json()
        async with tenant_session(tenant_id) as session:
            await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)
        after = (
            await http.get("/v1/agents/starters", headers={"Authorization": f"Bearer {token}"})
        ).json()
    assert [s["locked_reason"] for s in before["starters"]] == [None, None]
    locked = {s["job"]: s["locked_reason"] for s in after["starters"]}
    assert locked["call_leads"] is None
    assert locked["answer_calls"] and "chat" in locked["answer_calls"]


async def test_the_starter_preview_greets_in_the_language_asked_for() -> None:
    _, _, token = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        english = (
            await http.get("/v1/agents/starters", headers={"Authorization": f"Bearer {token}"})
        ).json()
        telugu = (
            await http.get(
                "/v1/agents/starters?language=te-IN",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        refused = await http.get(
            "/v1/agents/starters?language=xx-YY", headers={"Authorization": f"Bearer {token}"}
        )
    expected = opening_in("te-IN", "inbound")
    assert expected is not None
    assert english["starters"][0]["opening_line"].startswith("Hello")
    assert telugu["starters"][0]["opening_line"] == expected.replace(
        "{business}", "Lifecycle Clinic"
    )
    assert refused.status_code == 422


# --- 2. a language change ---------------------------------------------------------------


async def test_changing_the_main_language_rewrites_the_notices_and_keeps_the_toggles() -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _tenant()
    before = await _agent(tenant_id, agent_id)
    assert before.language_primary == "te-IN"

    # Only the extras: nothing is rewritten.
    async with tenant_session(tenant_id) as session:
        await lifecycle.update_agent(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            language_primary="te-IN",
            languages_extra=["en-IN"],
        )
    unchanged = await _agent(tenant_id, agent_id)
    assert unchanged.ai_disclosure_line == before.ai_disclosure_line

    async with tenant_session(tenant_id) as session:
        await lifecycle.update_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, language_primary="hi-IN"
        )
    after = await _agent(tenant_id, agent_id)
    ai_line = ai_disclosure_for(language="hi-IN", business="Lifecycle Clinic")
    assert after.ai_disclosure_line == ai_line
    assert after.recording_notice_line == recording_notice_for(language="hi-IN")
    assert after.caller_memory_notice_line == caller_memory_notice_for(language="hi-IN")
    assert after.ai_disclosure_line != before.ai_disclosure_line
    assert ai_line in after.disclosure_line
    assert (after.ai_disclosure_enabled, after.recording_notice_enabled) == (
        before.ai_disclosure_enabled,
        before.recording_notice_enabled,
    )


async def test_the_opening_line_in_the_new_language_goes_into_the_draft_only() -> None:
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(schema_version=2, identity="You answer.", opening_line="Hi there."),
            notes=None,
            created_by=None,
        )
        await lifecycle.update_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, language_primary="hi-IN"
        )
    code, body = await _post(token, f"/v1/agents/{agent_id}/script/opening-line/in-language")
    assert code == 200, body
    expected = starters.starter_for("clinic", "answer_calls").opening_for(
        "Lifecycle Clinic", "hi-IN"
    )
    assert body["opening_line"] == expected
    async with tenant_session(tenant_id) as session:
        draft = await script_builder.read_draft(session, agent_id)
        saved = await script_builder.load_agent_script(session, agent_id)
    assert draft is not None and draft.script.opening_line == expected
    assert draft.script.identity == "You answer."
    assert saved.script.opening_line == "Hi there.", "the saved script was changed"


# --- 3. a save over the platform's recompiles -------------------------------------------


async def test_a_save_rebases_over_a_pinned_fact_recompile_but_not_over_an_edit() -> None:
    tenant_id, agent_id, _ = await _tenant()
    script = CallScript(schema_version=2, identity="You answer for the shop.")
    async with tenant_session(tenant_id) as session:
        loaded = await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script,
            notes=None,
            created_by=None,
        )
        await pinned_store.add_pinned(
            session,
            tenant_id=tenant_id,
            question="Hours?",
            answer="9 to 9.",
            origin="quick_fact",
            created_by=None,
        )
        assert await pinned_store.recompile_agent(session, tenant_id=tenant_id, agent_id=agent_id)

        edited = script.model_copy(update={"identity": "You answer for the shop, warmly."})
        saved = await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=edited,
            notes=None,
            created_by=None,
            check_version=True,
            expected_version=loaded.version,
        )
        assert saved.version == loaded.version + 2

        with pytest.raises(ProblemError) as refused:
            await script_builder.save_agent_script(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                script=script,
                notes=None,
                created_by=None,
                check_version=True,
                expected_version=loaded.version,
            )
    assert refused.value.code == "script_changed_elsewhere"


# --- 4. pinned facts not yet on an agent ---------------------------------------------------


async def test_an_agent_with_a_staged_edit_is_named_until_it_is_put_live() -> None:
    _fresh_engine()
    tenant_id, agent_id, _ = await _tenant()
    await _write_script(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await lifecycle.activate_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(schema_version=2, identity="Staged words."),
            notes=None,
            created_by=None,
        )
        assert await pinned_store.not_yet_on(session) == []
        await pinned_store.add_pinned(
            session,
            tenant_id=tenant_id,
            question=None,
            answer="Closed on Sundays.",
            origin="quick_fact",
            created_by=None,
        )
        queued = await pinned_store.not_yet_on(session)
        assert [(n.agent_id, n.reason) for n in queued] == [(agent_id, "on_the_way")]

        await pinned_store.recompile_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        waiting = await pinned_store.not_yet_on(session)
    assert [(n.agent_id, n.reason) for n in waiting] == [(agent_id, "waiting_put_live")]
    assert "Script tab" in waiting[0].sentence

    await publishing.apply_to_live(tenant_id=tenant_id, agent_id=agent_id)
    async with tenant_session(tenant_id) as session:
        assert await pinned_store.not_yet_on(session) == []


# --- 5. who needs a contact ----------------------------------------------------------------


async def test_a_contact_is_needed_only_where_an_agent_hands_over_or_answers() -> None:
    profile = bp.Profile(
        tenant_id=uuid.uuid4(),
        hours={"mon": {"opens": "09:00", "closes": "18:00"}},
        branches=[bp.Branch(label="Main", address="1 Road")],
        services=[bp.ServiceItem(name="Visit")],
    )
    assert bp.go_live_blockers(profile) == ["escalation_contact_missing"]
    assert bp.go_live_blockers(profile, needs_contact=False) == []
    assert "contacts" not in bp.required_steps(needs_contact=False)

    tenant_id, agent_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await bp.account_needs_contact(session), "the seeded receptionist answers calls"
        await session.execute(
            text("UPDATE agents SET direction = 'outbound', handoff_enabled = false WHERE id = :a"),
            {"a": agent_id},
        )
        assert not await bp.account_needs_contact(session)
        await session.execute(
            text("UPDATE agents SET handoff_enabled = true WHERE id = :a"), {"a": agent_id}
        )
        assert await bp.account_needs_contact(session)


# --- 6. promotional campaigns -----------------------------------------------------------


async def test_a_promotional_campaign_waits_for_the_telemarketer_registration() -> None:
    tenant_id, agent_id, _ = await _tenant()

    async def _create(session: Any) -> str:
        with pytest.raises(ProblemError) as refused:
            await campaigns_service.create_campaign(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Diwali offer",
                classification="promotional",
                number_id=None,
                dlt_template_id=None,
                concurrency=1,
            )
        service_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Reminders",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
        )
        assert service_id is not None
        return refused.value.code

    assert await _with_platform_tm(tenant_id, "not_registered", _create) == (
        "promotional_campaigns_unavailable"
    )


# --- 7. a refused apply after the version is saved -------------------------------------


async def test_a_refused_apply_says_the_version_is_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, token = await _tenant()

    async def _refuse(**_: Any) -> Any:
        raise ProblemError.conflict(
            "engine_unreachable_test", "The calling system did not answer.", remediation="Wait."
        )

    monkeypatch.setattr(publishing, "apply_to_live", _refuse)
    code, body = await _post(
        token,
        f"/v1/agents/{agent_id}/script/publish",
        {"summary": "New greeting", "script": {"schema_version": 2, "identity": "Hello."}},
    )
    assert code == 409, body
    assert _code(body) == "engine_unreachable_test"
    assert "saved as version" in body["detail"] and "did not answer" in body["detail"]
    assert body["remediation"].startswith("Press Put it live again")
    async with tenant_session(tenant_id) as session:
        loaded = await script_builder.load_agent_script(session, agent_id)
    assert loaded.script.identity == "Hello."
