"""D-788: Pip is off for a client account until its owner turns it on, and then it sends
what it is given unmasked to its primary model — never to the standby, never to a log.

Every test mints its own tenant.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import ai_quota
from apps.api.copilot import admin_routes, consent, service, tools
from apps.api.copilot.schemas import CopilotAskIn
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import credential_session, tenant_session, untenanted_session
from apps.api.main import app
from apps.workers import chat, copilot_jobs
from apps.workers.extraction import SARVAM_PROVIDER, AssistCapability
from calevate_shared.engine import AZURE_OPENAI_DEFAULT_MODEL
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.conftest import make_tenant_with_pip, turn_pip_on_for_tests
from tests.impersonation_grant_test import _headers as _view_as_headers
from tests.impersonation_grant_test import _make_admin, _make_org, _mint_over_http

ASK = "/v1/copilot/ask"
CONSENT = "/v1/copilot/consent"
CONVERSATION = "/v1/copilot/conversation"
NUMBER = "8019857559"

BODY: dict[str, Any] = {
    "screen": {"route": "/c/x/leads", "title": "Leads", "realm": "client"},
    "question": f"ok call this number {NUMBER}",
    "fields": [],
    "facts": [],
    "history": [],
}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


@pytest.fixture(autouse=True)
def _the_platform_brake_is_not_this_suites_business(monkeypatch: pytest.MonkeyPatch) -> None:
    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


@pytest.fixture
def azure_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Azure as the only tool-capable leg, so the fake `chat.stream` is what answers."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    monkeypatch.setattr(settings, "platform_llm_model", AZURE_OPENAI_DEFAULT_MODEL, raising=False)
    monkeypatch.setattr(settings, "copilot_azure_fallback", True, raising=False)


def _model(monkeypatch: pytest.MonkeyPatch) -> list[list[Any]]:
    """Replace `chat.stream`; return every message list the model leg was sent."""
    sent: list[list[Any]] = []

    def _stream(leg: chat.ChatLeg, messages: Any, **kwargs: Any) -> AsyncIterator[chat.StreamEvent]:
        sent.append(list(messages))

        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            yield chat.StreamEvent(text="Calling now.")
            yield chat.StreamEvent(
                outcome=chat.ChatOutcome(
                    content="Calling now.",
                    tool_calls=(),
                    finish_reason="stop",
                    usage=chat.TokenUsage(prompt_tokens=10, output_tokens=5),
                )
            )

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    return sent


async def _events(http: AsyncClient, path: str, headers: dict[str, str], body: Any) -> list[Any]:
    out: list[tuple[str, Any]] = []
    async with http.stream("POST", path, headers=headers, json=body) as response:
        assert response.status_code == 200, await response.aread()
        name: str | None = None
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:") and name is not None:
                out.append((name, json.loads(line[len("data:") :].strip())))
                name = None
    return out


def _text_of(messages: list[Any]) -> str:
    return json.dumps(messages, ensure_ascii=False)


def _accept_body() -> dict[str, str]:
    return {"version": consent.DISCLOSURE_VERSION, "text_sha256": consent.DISCLOSURE_TEXT_SHA256}


# --- the gate -------------------------------------------------------------------------


async def test_pip_is_locked_until_the_owner_turns_it_on(
    azure_leg: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tenant_id, slug, token = await _make_tenant()
    sent = _model(monkeypatch)

    async with _client() as http:
        events = await _events(http, ASK, _headers(token, slug), BODY)

    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["type"].endswith("/copilot_consent_required")
    assert "account owner" in events[0][1]["detail"]
    assert sent == [], "a locked account must not reach a model"


async def _live_run(subject: UUID) -> None:
    """A live sign-in run for a dev token (`copilot_live_sync_test`'s idiom): the upload
    route checks the run before it checks anything else."""
    async with credential_session() as credentials:
        session_id = uuid.uuid4()
        await credentials.execute(
            text(
                "INSERT INTO auth_sessions (id, family_id, realm, subject_id, token_hash, "
                "last_seen_at, idle_expires_at, absolute_expires_at, created_at, updated_at) "
                "VALUES (:id, :fid, 'client', :sid, :hash, now(), now() + interval '1 hour', "
                "now() + interval '1 hour', now() - interval '1 minute', now())"
            ),
            {"id": session_id, "fid": uuid.uuid4(), "sid": subject, "hash": session_id.bytes},
        )


async def test_an_upload_is_refused_before_consent() -> None:
    _tenant_id, slug, token = await _make_tenant()
    await _live_run(UUID(token.rsplit(":", 1)[1]))
    async with _client() as http:
        refused = await http.post(
            "/v1/copilot/uploads",
            headers={
                **_headers(token, slug),
                "X-Upload-Name": "a.txt",
                "Content-Type": "text/plain",
            },
            content=b"hello",
        )
    assert refused.status_code == 403, refused.text
    assert refused.json()["type"].endswith("/copilot_consent_required")


async def test_the_owner_sees_the_step_and_can_turn_pip_on() -> None:
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        before = (await http.get(CONVERSATION, headers=_headers(token, slug))).json()["consent"]
        accepted = await http.post(CONSENT, headers=_headers(token, slug), json=_accept_body())
        after = (await http.get(CONVERSATION, headers=_headers(token, slug))).json()["consent"]

    assert before["status"] == "required" and before["can_accept"] is True
    assert before["text"] == consent.DISCLOSURE_TEXT
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert after["status"] == "accepted" and after["can_accept"] is False
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT disclosure_version, text_sha256, accepted_by_user_id "
                    "FROM copilot_consents"
                )
            )
        ).one()
    assert row[0] == consent.DISCLOSURE_VERSION
    assert row[1] == consent.DISCLOSURE_TEXT_SHA256
    assert str(row[2]) == token.rsplit(":", 1)[1]
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'copilot.consent_accepted'"
                ),
                {"t": str(tenant_id)},
            )
        ).scalar_one()
    assert audited == 1


async def test_a_non_owner_sees_the_lock_and_cannot_turn_pip_on() -> None:
    _tenant_id, slug, token = await _make_tenant(role="staff")
    async with _client() as http:
        seen = (await http.get(CONVERSATION, headers=_headers(token, slug))).json()["consent"]
        refused = await http.post(CONSENT, headers=_headers(token, slug), json=_accept_body())

    assert seen["status"] == "required" and seen["can_accept"] is False
    assert refused.status_code == 403, refused.text


async def test_a_view_as_session_cannot_turn_pip_on() -> None:
    _admin_id, admin_token = await _make_admin()
    org = await _make_org()
    async with _client() as http:
        grant = await _mint_over_http(http, admin_token, str(org["slug"]))
        refused = await http.post(
            CONSENT,
            headers=_view_as_headers(admin_token, str(org["slug"]), grant),
            json=_accept_body(),
        )
    assert refused.status_code == 403, refused.text
    async with tenant_session(org["id"]) as session:
        rows = (await session.execute(text("SELECT count(*) FROM copilot_consents"))).scalar_one()
    assert rows == 0


async def test_a_stale_disclosure_is_refused_rather_than_recorded() -> None:
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        refused = await http.post(
            CONSENT,
            headers=_headers(token, slug),
            json={"version": consent.DISCLOSURE_VERSION, "text_sha256": "0" * 64},
        )
    assert refused.status_code == 409, refused.text
    assert refused.json()["type"].endswith("/copilot_consent_outdated")


async def test_a_consent_is_invisible_to_another_tenant() -> None:
    """Hard rule 1: zero rows across the tenant boundary."""
    tenant_a, _slug, _token = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    await turn_pip_on_for_tests(tenant_a)

    async with tenant_session(tenant_b) as session:
        seen = (await session.execute(text("SELECT count(*) FROM copilot_consents"))).scalar_one()
        state = await consent.read_consent(session, tenant_id=tenant_a)
    assert seen == 0
    assert state.status == "required"


def test_a_material_revision_asks_the_owner_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """The legal catalogue's rule, reused: a material step re-asks, a cosmetic one does not."""
    from apps.api.legal.catalogue import LegalDocumentSpec, Revision, reacceptance_required

    def spec(*material: bool) -> LegalDocumentSpec:
        revisions = tuple(
            Revision(revision=str(index + 1), material=flag, note="t")
            for index, flag in enumerate(material)
        )
        return LegalDocumentSpec(
            slug="pip-disclosure", title="t", blocking=False, revisions=revisions
        )

    assert reacceptance_required(spec(True, False), "1") is False
    assert reacceptance_required(spec(True, True), "1") is True


# --- unmasked after consent -----------------------------------------------------------


async def test_a_number_in_the_question_reaches_the_model_as_typed(
    azure_leg: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _tenant_id, slug, token = await make_tenant_with_pip()
    sent = _model(monkeypatch)

    with caplog.at_level(logging.DEBUG):
        async with _client() as http:
            events = await _events(http, ASK, _headers(token, slug), BODY)

    assert [name for name, _ in events][-1] == "done", events
    assert sent and NUMBER in _text_of(sent[0])
    # Hard rule 6: the number reached the model and no log line.
    assert NUMBER not in caplog.text


async def _lead(tenant_id: UUID, phone: str) -> UUID:
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        lead_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Ravi', 'inbound_call', "
                "'new', CAST(:d AS jsonb), now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": phone, "d": '{"city": "Guntur"}'},
        )
    return lead_id


def _context(tenant_id: UUID, *, unmasked: bool, role: str = "owner") -> tools.ToolContext:
    actor = Principal(realm="client", user_id=None, tenant_id=tenant_id, role=role)
    return tools.ToolContext(
        tenant_id=tenant_id,
        role=role,
        unmasked=tools.Unmasked(actor=actor, ip="203.0.113.9") if unmasked else None,
    )


async def test_a_tool_result_carries_the_raw_number_only_when_unmasked() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _lead(tenant_id, f"+91{NUMBER}")
    registry = service._read_tool_registry("client")
    args = json.dumps({"status": None, "search": NUMBER[-4:], "limit": None})

    unmasked = await tools.run_read_tool(
        "leads_search", args, context=_context(tenant_id, unmasked=True), registry=registry
    )
    masked = await tools.run_read_tool(
        "leads_search", args, context=_context(tenant_id, unmasked=False), registry=registry
    )

    assert f"+91{NUMBER}" in unmasked and "Ravi" in unmasked
    assert NUMBER not in masked and "[phone ••59]" in masked


async def test_lead_detail_shows_captured_values_only_when_unmasked() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    lead_id = await _lead(tenant_id, f"+91{NUMBER}")
    registry = service._read_tool_registry("client")
    args = json.dumps({"lead_id": str(lead_id)})

    unmasked = await tools.run_read_tool(
        "lead_detail", args, context=_context(tenant_id, unmasked=True), registry=registry
    )
    masked = await tools.run_read_tool(
        "lead_detail", args, context=_context(tenant_id, unmasked=False), registry=registry
    )

    assert "city: Guntur" in unmasked and NUMBER in unmasked
    assert "Guntur" not in masked and NUMBER not in masked


async def test_call_detail_reads_the_raw_transcript_and_audits_it() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, created_at, updated_at) VALUES (:i, :t, :a, :e, 'inbound', "
                "'completed', '+919876500000', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"pc_{call_id.hex[:10]}"},
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:id, :t, :c, 0, 'caller', "
                "'naa number 9876543210', 'naa number [phone ••10]', now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "c": call_id},
        )
    registry = service._read_tool_registry("client")
    args = json.dumps({"call_id": str(call_id)})

    owner = await tools.run_read_tool(
        "call_detail", args, context=_context(tenant_id, unmasked=True), registry=registry
    )
    masked = await tools.run_read_tool(
        "call_detail", args, context=_context(tenant_id, unmasked=False), registry=registry
    )
    # Consent unmasks Pip; it does not hand `staff` the `calls:read_raw` the raw route
    # refuses them (hard rule 5), so their read stays redacted and is not a raw read.
    staff = await tools.run_read_tool(
        "call_detail",
        args,
        context=_context(tenant_id, unmasked=True, role="staff"),
        registry=registry,
    )

    assert "naa number 9876543210" in owner
    assert "9876543210" not in masked and "[phone ••10]" in masked
    assert "9876543210" not in staff and "[phone ••10]" in staff
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'transcript.read_raw' AND object_id = :c"
                ),
                {"t": str(tenant_id), "c": str(call_id)},
            )
        ).scalar_one()
    assert audited == 1, "only the unmasked read is audited, and it is"


# --- the admin console is exempt --------------------------------------------------------


async def test_the_admin_consoles_pip_sends_the_number_as_typed(
    azure_leg: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )

    async def _gate(_session: Any) -> None:
        return None

    monkeypatch.setattr(admin_routes, "require_platform_ai", _gate)
    sent = _model(monkeypatch)
    body = {**BODY, "screen": {"route": "/admin/tenants", "title": "Accounts", "realm": "admin"}}

    async with _client() as http:
        events = await _events(
            http, "/v1/admin/copilot/ask", {"Authorization": f"Bearer dev:admin:{admin_id}"}, body
        )
        conversation = await http.get(
            "/v1/admin/copilot/conversation",
            headers={"Authorization": f"Bearer dev:admin:{admin_id}"},
        )

    assert [name for name, _ in events][-1] == "done", events
    assert sent and NUMBER in _text_of(sent[0])
    assert conversation.json()["consent"]["status"] == "not_required"


# --- the standby never receives it ------------------------------------------------------


async def test_the_standby_leg_is_sent_masked_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its terms permit training on inputs (SECURITY-COMPLIANCE §4): consent covers the
    models that answer Pip, not this one."""
    settings = get_settings()
    monkeypatch.setattr(settings, "sarvam_api_key", "k", raising=False)
    sent: list[Any] = []

    async def _complete(leg: chat.ChatLeg, messages: Any, **kwargs: Any) -> chat.ChatOutcome:
        sent.append(list(messages))
        return chat.ChatOutcome(content="ok", tool_calls=(), finish_reason="stop", usage=None)

    monkeypatch.setattr(chat, "complete", _complete)
    payload = CopilotAskIn.model_validate(
        {**BODY, "history": [{"role": "user", "content": f"earlier: {NUMBER}"}]}
    )
    capability = AssistCapability(available=True, provider=SARVAM_PROVIDER)
    events = [event async for event in service._answer_via_sarvam(payload, capability)]

    assert events and sent
    assert NUMBER not in _text_of(sent[0])
    assert "[phone ••59]" in _text_of(sent[0])


# --- a background task waits for the owner too -------------------------------------------


async def test_a_background_task_is_refused_on_an_account_pip_is_off_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    job_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO copilot_jobs (id, tenant_id, user_id, status, goal, screen_route, "
                "created_at, updated_at) VALUES (:i, :t, :u, 'queued', 'tidy the leads', "
                "'/c/x/leads', now(), now())"
            ),
            {"i": job_id, "t": tenant_id, "u": user_id},
        )
    reached: list[Any] = []

    async def _run(*args: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        reached.append(args)
        yield service.CopilotEvent(text="no")

    monkeypatch.setattr(service, "run_copilot", _run)

    outcome = await copilot_jobs.run_copilot_job(
        {}, {"job_id": str(job_id), "tenant_id": str(tenant_id)}
    )

    assert outcome == "copilot_consent_required"
    assert reached == []


def test_the_refusal_names_who_can_unlock_it() -> None:
    problem = consent.consent_required()
    assert isinstance(problem, ProblemError)
    assert problem.code == "copilot_consent_required"
    assert "account owner" in (problem.detail or "")


def test_the_standby_leg_masks_list_form_content_and_drops_parts_it_cannot_read() -> None:
    masked = service.masked_messages(
        [
            {"role": "user", "content": "call 9876543210"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "and 9876500011"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            },
            {"role": "assistant", "content": None},
        ]
    )
    assert "9876543210" not in masked[0]["content"]
    assert masked[1]["content"] == [{"type": "text", "text": masked[1]["content"][0]["text"]}]
    assert "9876500011" not in masked[1]["content"][0]["text"]
    assert masked[2]["content"] is None
