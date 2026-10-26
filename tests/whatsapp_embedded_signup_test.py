"""Clients' own WhatsApp through Meta's Embedded Signup (D-784): connect, tenancy, templates,
Meta's signed webhook, and the in-call opt-in the agent asks for.

Graph is never reached: `apps.api.whatsapp.graph` calls are replaced per test. Each test
mints its own tenant, so the file runs beside other suites on the shared Postgres.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.actions import whatsapp as wa
from apps.api.actions.schema import CALLER_AGREED_ARG, CALLER_WORDS_ARG, WhatsAppConfig
from apps.api.compliance import spoken_consent
from apps.api.compliance.consent import read_messaging_consent
from apps.api.compliance.service import DispatchDecision
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session, whatsapp_waba_session
from apps.api.main import app as api_app
from apps.api.reliability import engine_actions
from apps.api.whatsapp import graph, hook_routes, routes, signup, templates, webhooks
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from tests.conftest import create_org_with_receptionist

pytestmark = [pytest.mark.rls]

APP_SECRET = "test-meta-app-secret-0123456789"


async def _client() -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="WhatsApp Business",
        slug=f"wa-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"]))


def _waba() -> str:
    return str(10**14 + uuid.uuid4().int % 10**14)


@pytest.fixture
def meta_app(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "meta_app_id", "123456789012345")
    monkeypatch.setattr(s, "meta_app_secret", APP_SECRET)
    monkeypatch.setattr(s, "whatsapp_signup_config_id", "987654321098765")
    monkeypatch.setattr(s, "whatsapp_webhook_verify_token", "verify-me")
    monkeypatch.setattr(s, "whatsapp_onboarding_weekly_limit", 1000)


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"register": [], "subscribe": [], "templates": []}

    async def exchange(*, app_id: str, app_secret: str, code: str) -> str:
        assert app_secret == APP_SECRET
        return f"business-token-for-{code}"

    async def subscribe(*, waba_id: str, token: str) -> None:
        calls["subscribe"].append(waba_id)

    async def register(*, phone_number_id: str, token: str, pin: str) -> None:
        calls["register"].append((phone_number_id, pin))

    async def info(*, phone_number_id: str, token: str) -> graph.PhoneInfo:
        return graph.PhoneInfo(
            "+91 98765 43210", "Lakshmi Traders", "GREEN", "APPROVED", "TIER_250"
        )

    async def create(**kw: Any) -> tuple[str, str]:
        calls["templates"].append(kw)
        return str(len(calls["templates"]) + 1000), "PENDING"

    monkeypatch.setattr(graph, "exchange_code", exchange)
    monkeypatch.setattr(graph, "subscribe_app", subscribe)
    monkeypatch.setattr(graph, "register_number", register)
    monkeypatch.setattr(graph, "phone_info", info)
    monkeypatch.setattr(graph, "create_template", create)
    return calls


async def _connect(tenant_id: UUID, user_id: UUID, waba: str, **kw: Any) -> signup.ConnectOutcome:
    async with tenant_session(tenant_id) as session:
        _setup, state = await signup.start(session, tenant_id=tenant_id, user_id=user_id)
        return await signup.connect(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            payload=signup.ConnectIn(
                state=kw.get("state", state),
                code="abc",
                event=kw.get("event", "FINISH"),
                waba_id=waba,
                phone_number_id=kw.get("phone_number_id", "555000111"),
                business_id="777",
            ),
        )


# --- connect ---------------------------------------------------------------------------


async def test_a_signup_seals_the_token_registers_the_number_and_shows_the_pin_once(
    meta_app: None, fake_graph: dict[str, list[Any]]
) -> None:
    tenant_id, _ = await _client()
    user_id = uuid.uuid4()
    waba = _waba()
    outcome = await _connect(tenant_id, user_id, waba)
    assert outcome.status == "connected"
    assert outcome.pin is not None and len(outcome.pin) == 6 and outcome.pin.isdigit()
    assert fake_graph["subscribe"] == [waba]
    assert fake_graph["register"] == [("555000111", outcome.pin)]
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT a.status, a.verified_name, c.kind, c.non_secret->>'phone_number_id' "
                    "FROM whatsapp_accounts a JOIN integration_credentials c "
                    "ON c.id = a.credential_id WHERE a.id = :id"
                ),
                {"id": outcome.account_id},
            )
        ).one()
        # The PIN is nowhere in the database.
        dump = (
            await session.execute(
                text("SELECT row_to_json(a)::text FROM whatsapp_accounts a WHERE id = :id"),
                {"id": outcome.account_id},
            )
        ).scalar_one()
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :j "
                    "AND payload->>'account_id' = :a"
                ),
                {"j": signup.SEED_TEMPLATES_JOB, "a": str(outcome.account_id)},
            )
        ).scalar_one()
    assert tuple(row) == ("connected", "Lakshmi Traders", "meta_cloud", "555000111")
    assert outcome.pin not in dump
    assert queued == 1


async def test_a_business_app_number_is_not_registered_again(
    meta_app: None, fake_graph: dict[str, list[Any]]
) -> None:
    tenant_id, _ = await _client()
    outcome = await _connect(
        tenant_id, uuid.uuid4(), _waba(), event="FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"
    )
    assert outcome.status == "connected"
    assert outcome.pin is None
    assert fake_graph["register"] == []


async def test_a_state_from_another_person_or_a_replay_is_refused(
    meta_app: None, fake_graph: dict[str, list[Any]]
) -> None:
    tenant_id, _ = await _client()
    async with tenant_session(tenant_id) as session:
        _setup, state = await signup.start(session, tenant_id=tenant_id, user_id=uuid.uuid4())
    with pytest.raises(ProblemError) as caught:
        await _connect(tenant_id, uuid.uuid4(), _waba(), state=state)
    assert caught.value.code == "whatsapp_signup_state_invalid"
    assert fake_graph["subscribe"] == []


async def test_one_whatsapp_account_cannot_be_connected_to_two_clients(
    meta_app: None, fake_graph: dict[str, list[Any]]
) -> None:
    first, _ = await _client()
    second, _ = await _client()
    waba = _waba()
    await _connect(first, uuid.uuid4(), waba)
    with pytest.raises(ProblemError) as caught:
        await _connect(second, uuid.uuid4(), waba)
    assert caught.value.code == "whatsapp_account_already_connected"


async def test_a_failed_step_leaves_the_account_needing_attention_and_finish_resumes_it(
    meta_app: None, fake_graph: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.whatsapp import accounts

    ok_register = graph.register_number

    async def refuse(**kw: Any) -> None:
        raise graph.GraphError("register", status=400, meta_code=133005)

    monkeypatch.setattr(graph, "register_number", refuse)
    tenant_id, _ = await _client()
    outcome = await _connect(tenant_id, uuid.uuid4(), _waba())
    assert (outcome.status, outcome.failed_step) == ("needs_attention", "register")
    monkeypatch.setattr(graph, "register_number", ok_register)
    async with tenant_session(tenant_id) as session:
        again = await accounts.finish_setup(
            session, tenant_id=tenant_id, account_id=outcome.account_id
        )
    assert again.status == "connected"
    # Webhooks were already subscribed and are not subscribed twice.
    assert len(fake_graph["subscribe"]) == 1


async def test_signup_is_not_offered_until_calevates_meta_app_is_configured() -> None:
    async with untenanted_session() as session:
        setup = await signup.signup_setup(session)
    if get_settings().meta_app_id:
        pytest.skip("this environment configures a Meta app")
    assert (setup.available, setup.reason) == (False, "not_configured")


def test_coexistence_signup_asks_meta_for_the_business_app_flow() -> None:
    assert routes.extras_for("business_app")["featureType"] == "whatsapp_business_app_onboarding"
    assert routes.extras_for("new") == {"setup": {}}


# --- tenancy ---------------------------------------------------------------------------


async def test_a_neighbour_sees_none_of_another_clients_whatsapp(
    meta_app: None, fake_graph: dict[str, list[Any]]
) -> None:
    owner_tenant, _ = await _client()
    neighbour, _ = await _client()
    waba = _waba()
    outcome = await _connect(owner_tenant, uuid.uuid4(), waba)
    async with tenant_session(owner_tenant) as session:
        await templates.insert_template(
            session,
            tenant_id=owner_tenant,
            account_id=outcome.account_id,
            name="order_ready",
            language="en",
            category="UTILITY",
            body="Your order is ready, {{1}}. Thank you.",
            variables=[{"label": "Name", "example": "Ravi"}],
            origin="client",
            purpose=None,
        )
    async with tenant_session(neighbour) as session:
        for table in ("whatsapp_accounts", "whatsapp_templates"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == 0, table
    async with untenanted_session() as session:
        assert (
            await session.execute(text("SELECT count(*) FROM whatsapp_accounts"))
        ).scalar_one() == 0
    # A verified webhook's WABA opens exactly that one row, and writes nothing.
    async with whatsapp_waba_session(waba) as session:
        rows = (await session.execute(text("SELECT tenant_id FROM whatsapp_accounts"))).all()
        assert [UUID(str(r[0])) for r in rows] == [owner_tenant]
        # The row is readable, so the UPDATE finds it and WITH CHECK refuses the write.
        with pytest.raises(ProgrammingError, match="row-level security"):
            async with session.begin_nested():
                await session.execute(
                    text("UPDATE whatsapp_accounts SET verified_name = 'x' WHERE waba_id = :w"),
                    {"w": waba},
                )


# --- templates -------------------------------------------------------------------------


@pytest.mark.parametrize("standard", templates.STANDARD, ids=lambda t: t.purpose)
def test_every_standard_template_passes_metas_rules_in_every_language(
    standard: templates.StandardTemplate,
) -> None:
    for language in templates.STANDARD_LANGUAGES:
        templates.check_template(
            name=standard.name,
            language=language,
            category="UTILITY",
            body=standard.bodies[language],
            examples=list(standard.examples),
        )


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("{{1}} your order is ready.", "whatsapp_template_blank_at_edge"),
        ("Your order is ready {{1}}.", "whatsapp_template_blank_at_edge"),
        ("Hello {{2}}, thank you.", "whatsapp_template_blanks_order"),
        ("Hello {1}, your order is ready.", "whatsapp_template_blank_shape"),
        ("Hello {{1}, your order is ready.", "whatsapp_template_blank_shape"),
        ("Hello {1}}, your order is ready.", "whatsapp_template_blank_shape"),
    ],
)
def test_a_template_meta_would_refuse_is_refused_here_first(body: str, code: str) -> None:
    with pytest.raises(ProblemError) as caught:
        templates.check_template(
            name="order_ready", language="en", category="UTILITY", body=body, examples=["x"]
        )
    assert caught.value.code == code


async def test_metas_verdict_reaches_the_template(
    meta_app: None, fake_graph: dict[str, list[Any]]
) -> None:
    tenant_id, _ = await _client()
    outcome = await _connect(tenant_id, uuid.uuid4(), _waba())
    async with tenant_session(tenant_id) as session:
        counts = await templates.seed_standard(
            session,
            tenant_id=tenant_id,
            account_id=outcome.account_id,
            waba_id="1",
            token="t",
        )
        assert counts["submitted"] == len(templates.STANDARD) * len(templates.STANDARD_LANGUAGES)
        status = await templates.apply_status_update(
            session,
            account_id=outcome.account_id,
            update=templates.StatusUpdate(
                meta_template_id=None,
                name="calevate_payment_link",
                language="hi",
                event="REJECTED",
                reason="INVALID_FORMAT",
            ),
        )
    assert status == "rejected"


# --- the webhook -----------------------------------------------------------------------


def _signed(body: bytes) -> dict[str, str]:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"}


def _delivery(waba: str) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": waba,
                "changes": [
                    {
                        "field": "message_template_status_update",
                        "value": {
                            "event": "APPROVED",
                            "message_template_id": 1234,
                            "message_template_name": "calevate_payment_link",
                            "message_template_language": "te",
                        },
                    },
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.X",
                                    "status": "failed",
                                    "recipient_id": "919876543210",
                                    "errors": [{"code": 131042, "title": "Payment issue"}],
                                }
                            ]
                        },
                    },
                ],
            }
        ],
    }


def test_a_delivery_keeps_codes_and_ids_and_drops_the_recipients_number() -> None:
    events = webhooks.extract_events(_delivery("123"))
    assert [e.kind for e in events] == ["template_status", "send_failed"]
    assert events[1].code == "131042"
    assert "919876543210" not in json.dumps([e.payload() for e in events])
    assert webhooks.extract_events({"object": "page", "entry": []}) == []


async def test_an_unsigned_delivery_is_refused_and_a_signed_one_is_queued_once(
    meta_app: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[dict[str, Any]] = []

    async def fake_enqueue(job: str, payload: dict[str, Any], **kw: Any) -> str:
        assert job == hook_routes.INGEST_JOB
        queued.append(payload)
        return "job"

    monkeypatch.setattr(hook_routes, "enqueue", fake_enqueue)
    body = json.dumps(_delivery(_waba())).encode()
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        refused = await http.post("/hooks/v1/meta/whatsapp", content=body)
        first = await http.post("/hooks/v1/meta/whatsapp", content=body, headers=_signed(body))
        again = await http.post("/hooks/v1/meta/whatsapp", content=body, headers=_signed(body))
    assert refused.status_code == 401
    assert first.status_code == 200 and first.json() == {
        "received": 2,
        "accepted": 2,
        "duplicate": 0,
    }
    assert again.json() == {"received": 2, "accepted": 0, "duplicate": 2}
    assert len(queued) == 2


async def test_the_handshake_echoes_only_for_our_verify_token(meta_app: None) -> None:
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        ok = await http.get(
            "/hooks/v1/meta/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "42",
            },
        )
        bad = await http.get(
            "/hooks/v1/meta/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"},
        )
    assert (ok.status_code, ok.text) == (200, "42")
    assert bad.status_code == 403


# --- the in-call opt-in ------------------------------------------------------------------


async def _call_row(tenant_id: UUID, agent_id: UUID, caller: str) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "from_e164, status, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'inbound', :f, 'in_progress', now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"wa-{call_id}", "f": caller},
        )
    return call_id


@pytest.fixture
def gate_open(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allowed(session: Any, **kw: Any) -> DispatchDecision:
        return DispatchDecision(allowed=True)

    monkeypatch.setattr(wa, "check_dispatch", allowed)


def _spoken(answer: str, words: str, call_id: UUID | None) -> wa.SpokenConsent:
    return wa.spoken_consent_from_args(
        {CALLER_AGREED_ARG: answer, CALLER_WORDS_ARG: words},
        call_id=call_id,
        call_ref="vendor-call",
        action_id=uuid.uuid4(),
    )


async def test_a_yes_on_the_call_is_recorded_with_the_call_then_the_send_may_go(
    gate_open: None,
) -> None:
    tenant_id, agent_id = await _client()
    caller = f"+919{uuid.uuid4().int % 10**9:09d}"
    call_id = await _call_row(tenant_id, agent_id, caller)
    async with tenant_session(tenant_id) as session:
        number = await wa.assert_recipient_may_be_messaged(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            recipient_e164=caller,
            spoken=_spoken("yes", "haan, bhej do", call_id),
        )
        consent = await read_messaging_consent(session, tenant_id=tenant_id, raw_phone=caller)
        row = (
            await session.execute(
                text(
                    "SELECT consent_source, call_id, evidence->>'caller_words' FROM consent_ledger "
                    "WHERE phone_e164 = :p AND purpose = 'messaging'"
                ),
                {"p": caller},
            )
        ).one()
    assert number == caller
    assert consent.messageable
    assert tuple(row) == ("in_call_agent_question", call_id, "haan, bhej do")


async def test_a_no_is_recorded_as_declined_and_nothing_is_sent(gate_open: None) -> None:
    tenant_id, agent_id = await _client()
    caller = f"+919{uuid.uuid4().int % 10**9:09d}"
    call_id = await _call_row(tenant_id, agent_id, caller)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(wa.WhatsAppCallerDeclinedError):
            await wa.assert_recipient_may_be_messaged(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                recipient_e164=caller,
                spoken=_spoken("no", "vaddu", call_id),
            )
        consent = await read_messaging_consent(session, tenant_id=tenant_id, raw_phone=caller)
    assert consent.status == "declined"


@pytest.mark.parametrize(("answer", "words"), [("", ""), ("yes", "")])
async def test_no_answer_or_no_words_is_not_consent(
    gate_open: None, answer: str, words: str
) -> None:
    tenant_id, agent_id = await _client()
    caller = f"+919{uuid.uuid4().int % 10**9:09d}"
    call_id = await _call_row(tenant_id, agent_id, caller)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(wa.WhatsAppConsentNotAskedError):
            await wa.assert_recipient_may_be_messaged(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                recipient_e164=caller,
                spoken=_spoken(answer, words, call_id),
            )
        rows = (
            await session.execute(
                text("SELECT count(*) FROM consent_ledger WHERE phone_e164 = :p"), {"p": caller}
            )
        ).scalar_one()
    assert rows == 0


async def test_a_reported_yes_the_caller_never_said_is_audited_after_the_call(
    gate_open: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    raised: list[str] = []
    monkeypatch.setattr(spoken_consent, "alert", lambda stage, code, **kw: raised.append(code))
    tenant_id, agent_id = await _client()
    caller = f"+919{uuid.uuid4().int % 10**9:09d}"
    call_id = await _call_row(tenant_id, agent_id, caller)
    async with tenant_session(tenant_id) as session:
        await wa.assert_recipient_may_be_messaged(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            recipient_e164=caller,
            spoken=_spoken("yes", "yes please send it", call_id),
        )
    async with tenant_session(tenant_id) as session:
        said = await spoken_consent.check_call(
            session, tenant_id=tenant_id, call_id=call_id, caller_turns=["Yes, please send it."]
        )
        unsaid = await spoken_consent.check_call(
            session, tenant_id=tenant_id, call_id=call_id, caller_turns=["What are your hours?"]
        )
        # Re-running the pipeline does not audit it twice.
        await spoken_consent.check_call(
            session, tenant_id=tenant_id, call_id=call_id, caller_turns=["What are your hours?"]
        )
        audits = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action = :a AND tenant_id = :t"),
                {"a": spoken_consent.UNCONFIRMED_ACTION, "t": tenant_id},
            )
        ).scalar_one()
    assert (said, unsaid) == (0, 1)
    assert audits == 1
    assert raised == ["whatsapp_spoken_consent_unconfirmed"]


def test_the_words_match_across_punctuation_case_and_script() -> None:
    assert spoken_consent.words_were_said("haan bhej do", ["Haan, bhej do!"])
    assert spoken_consent.words_were_said("సరే పంపండి", ["సరే, పంపండి."])
    assert not spoken_consent.words_were_said("yes", ["no thanks"])
    assert not spoken_consent.words_were_said("", ["yes"])


def test_the_words_may_be_trimmed_or_reordered_and_a_silent_turn_is_passed_over() -> None:
    """A turn that is only punctuation says nothing and the next turn is still read; and
    the model may reorder or trim the caller's words, so most of them in one turn is enough
    where the exact phrase is not there."""
    assert spoken_consent.words_were_said("haan bhej do", ["...", "do bhej haan"])
    assert spoken_consent.words_were_said("yes please send it", ["yes send it"])
    assert not spoken_consent.words_were_said("yes please send it", ["send", "?!"])


def test_a_whatsapp_action_asks_the_question_and_declares_the_answer() -> None:
    names = [p.name for p in engine_actions.WHATSAPP_CONSENT_PARAMS]
    assert names == [CALLER_AGREED_ARG, CALLER_WORDS_ARG]
    assert wa.SPOKEN_QUESTION in engine_actions.WHATSAPP_CONSENT_TIMING


# --- the senders -------------------------------------------------------------------------


def test_aisensy_files_the_contact_under_the_callers_name_never_ours() -> None:
    cfg = WhatsAppConfig(recipient_param="caller", template="t", body_params=[])
    named = wa.build_aisensy(
        cfg, api_key="k", recipient_e164="+919000000000", body_values=[], recipient_name="Ravi"
    )
    assert named.json_body is not None and named.json_body["userName"] == "Ravi"


def test_a_connected_number_sends_without_a_typed_phone_number_id() -> None:
    cfg = WhatsAppConfig(recipient_param="caller", template="t", language="te", body_params=[])
    req = wa.build_meta_cloud(
        cfg,
        access_token="tok",
        recipient_e164="+919000000000",
        header_value=None,
        body_values=[],
        connected_number_id="555000111",
    )
    assert req.url.endswith("/555000111/messages")
