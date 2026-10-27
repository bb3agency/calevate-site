"""Tell my team (D-904): verified team addresses, per-agent triggers, the in-call action, and
one alert per call and address with the caller's full number."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.actions import in_call
from apps.api.actions.execution import CallFacts
from apps.api.actions.service import RESERVED_ACTION_NAMES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.reliability import engine_actions
from apps.api.team_alerts import service
from apps.api.team_alerts.service import FieldTrigger, Rule
from apps.workers import team_alerts as worker
from arq import Retry
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _tenant

CALLER = "+919812345678"


class _Mail:
    name = "test"

    def __init__(self, delivered: bool = True) -> None:
        self.delivered = delivered
        self.sent: list[tuple[str, str]] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        del html
        self.sent.append((to, body))
        return self.delivered


def _mail(monkeypatch: pytest.MonkeyPatch, *, delivered: bool = True) -> _Mail:
    mail = _Mail(delivered)
    monkeypatch.setattr(worker, "get_transport", lambda: mail)
    return mail


async def _use_schema(t: Tenant) -> None:
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET extraction_schema_id = (SELECT id FROM extraction_schemas "
                "WHERE agent_id = :aid ORDER BY version DESC LIMIT 1) WHERE id = :aid"
            ),
            {"aid": t.agent_id},
        )


async def _code_for(tenant_id: UUID, contact_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        payload = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'contact_id' = :cid ORDER BY created_at DESC LIMIT 1"
                ),
                {"job": service.CODE_JOB, "cid": str(contact_id)},
            )
        ).scalar_one()
    return str(payload["code"])


async def _verified_contact(t: Tenant, address: str = "team@example.com") -> UUID:
    async with tenant_session(t.tenant_id) as session:
        contact = await service.add_contact(session, tenant_id=t.tenant_id, address=address)
    code = await _code_for(t.tenant_id, contact.id)
    assert await service.verify_contact(
        tenant_id=t.tenant_id, contact_id=contact.id, code=code
    ) == ("verified")
    return contact.id


async def _call(t: Tenant, *, direction: str = "inbound") -> UUID:
    call_id = uuid7()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, summary, started_at, created_at, updated_at) VALUES (:id, "
                ":tid, :aid, :e, :dir, 'completed', :from_, :to_, :summary, now(), now(), now())"
            ),
            {
                "id": call_id,
                "tid": t.tenant_id,
                "aid": t.agent_id,
                "e": f"ta-{call_id.hex}",
                "dir": direction,
                "from_": CALLER if direction == "inbound" else "+914000000000",
                "to_": "+914000000000" if direction == "inbound" else CALLER,
                "summary": "Farmer could not log in; call back on 9812345678.",
            },
        )
    return call_id


async def _alert_payloads(tenant_id: UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT o.payload FROM outbox_messages o WHERE o.job = :job "
                    "AND o.payload->>'tenant_id' = :tid"
                ),
                {"job": service.ALERT_JOB, "tid": str(tenant_id)},
            )
        ).all()
    return [dict(r[0]) for r in rows]


# ------------------------------------------------------------------ contacts


async def test_a_team_address_is_verified_by_the_code_mailed_to_it() -> None:
    t = await _tenant()
    async with tenant_session(t.tenant_id) as session:
        contact = await service.add_contact(
            session, tenant_id=t.tenant_id, address=" Team@Example.com "
        )
        again = await service.add_contact(
            session, tenant_id=t.tenant_id, address="team@example.com"
        )
    assert contact.address == "team@example.com" and not contact.verified
    assert contact.is_default, "the first address is the account default"
    assert again.id == contact.id, "the same address is not added twice"
    code = await _code_for(t.tenant_id, contact.id)
    wrong = "000000" if code != "000000" else "111111"

    assert (
        await service.verify_contact(tenant_id=t.tenant_id, contact_id=contact.id, code=wrong)
        == "wrong"
    )
    async with tenant_session(t.tenant_id) as session:
        attempts = (
            await session.execute(
                text("SELECT code_attempts, code_hash FROM team_alert_contacts WHERE id = :id"),
                {"id": contact.id},
            )
        ).first()
    assert attempts is not None and attempts[0] == 1, "a wrong code is counted"
    assert code.encode() not in bytes(attempts[1]), "the code is stored only as a keyed hash"
    assert (
        await service.verify_contact(tenant_id=t.tenant_id, contact_id=contact.id, code=code)
        == "verified"
    )


async def test_too_many_wrong_codes_need_a_new_one() -> None:
    t = await _tenant()
    async with tenant_session(t.tenant_id) as session:
        contact = await service.add_contact(
            session, tenant_id=t.tenant_id, address="desk@example.com"
        )
    code = await _code_for(t.tenant_id, contact.id)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(service.CODE_MAX_ATTEMPTS):
        await service.verify_contact(tenant_id=t.tenant_id, contact_id=contact.id, code=wrong)
    assert (
        await service.verify_contact(tenant_id=t.tenant_id, contact_id=contact.id, code=code)
        == "used_up"
    )


async def test_the_code_email_carries_the_code_and_a_removed_address_gets_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mail = _mail(monkeypatch)
    t = await _tenant()
    async with tenant_session(t.tenant_id) as session:
        contact = await service.add_contact(
            session, tenant_id=t.tenant_id, address="ops@example.com"
        )
    code = await _code_for(t.tenant_id, contact.id)
    payload = {"tenant_id": str(t.tenant_id), "contact_id": str(contact.id), "code": code}
    assert await worker.send_team_contact_code({"job_try": 1}, payload) == "sent"
    assert mail.sent[0][0] == "ops@example.com" and code in mail.sent[0][1]
    async with tenant_session(t.tenant_id) as session:
        await service.remove_contact(session, contact_id=contact.id)
    assert await worker.send_team_contact_code({"job_try": 1}, payload) == "not_needed"


async def test_whatsapp_goes_only_through_the_clients_own_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.actions import credentials as creds
    from apps.api.core.errors import ProblemError
    from apps.api.team_alerts import whatsapp as team_wa

    sent: list[dict[str, Any]] = []

    async def _send(session: Any, **kwargs: Any) -> bool:
        sent.append(kwargs)
        return True

    monkeypatch.setattr(team_wa, "send", _send)
    t = await _tenant()
    setup = service.WhatsAppSetup(
        credential_id=uuid.uuid4(),
        template="team_alert",
        values=("name", "phone", "why", "link"),
        language="en",
    )
    async with tenant_session(t.tenant_id) as session:
        assert await team_wa.accounts(session) == []
        with pytest.raises(ProblemError) as refused:
            await service.add_contact(
                session,
                tenant_id=t.tenant_id,
                address="+91 98765 43210",
                channel="whatsapp",
                whatsapp=setup,
            )
        assert refused.value.code == "team_whatsapp_invalid", "no connection of theirs, no WhatsApp"
        cred = await creds.create_credential(
            session, tenant_id=t.tenant_id, kind="meta_cloud", label="Our WhatsApp", secret="tok-1"
        )
        contact = await service.add_contact(
            session,
            tenant_id=t.tenant_id,
            address="+91 98765 43210",
            channel="whatsapp",
            whatsapp=service.WhatsAppSetup(
                credential_id=cred.id,
                template="team_alert",
                values=("name", "phone", "why", "link"),
                language="en",
            ),
        )
    assert contact.channel == "whatsapp" and contact.address == "+919876543210"
    code = await _code_for(t.tenant_id, contact.id)
    payload = {"tenant_id": str(t.tenant_id), "contact_id": str(contact.id), "code": code}
    assert await worker.send_team_contact_code({"job_try": 1}, payload) == "sent"
    assert sent[0]["credential_id"] == cred.id and sent[0]["number_e164"] == "+919876543210"
    assert code in sent[0]["body_values"][2], "the code rides in the template's 'why' value"

    assert await service.verify_contact(
        tenant_id=t.tenant_id, contact_id=contact.id, code=code
    ) == ("verified")
    async with tenant_session(t.tenant_id) as session:
        await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(contact_id=contact.id, in_call=True),
        )
    call_id = await _call(t)
    assert (
        await service.queue_in_call(
            tenant_id=t.tenant_id, agent_id=t.agent_id, call_id=call_id, problem="Cannot log in"
        )
        == "queued"
    )
    alert_payload = (await _alert_payloads(t.tenant_id))[0]
    assert await worker.deliver_team_alert({"job_try": 1}, alert_payload) == "sent"
    values = sent[1]["body_values"]
    assert values[1] == CALLER and "Cannot log in" in values[2]
    assert values[3].endswith(f"/c/{t.slug}/calls/{call_id}")


# ------------------------------------------------------------------ rules + queueing


async def test_a_rule_names_only_what_the_agent_has() -> None:
    from apps.api.core.errors import ProblemError

    t = await _tenant()
    await _use_schema(t)
    async with tenant_session(t.tenant_id) as session:
        view = await service.read_rule(session, agent_id=t.agent_id)
        assert any(f.key == "budget_band" for f in view.fields)
        assert view.outcomes, "the agent's outcomes (or the starting set) are offered"
        with pytest.raises(ProblemError) as refused:
            await service.save_rule(
                session,
                tenant_id=t.tenant_id,
                agent_id=t.agent_id,
                rule=Rule(contact_id=None, on_fields=(FieldTrigger("budget_band", ("nope",)),)),
            )
    assert refused.value.code == "team_alert_choice_unknown"


async def test_a_chosen_answer_tells_the_team_once_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mail = _mail(monkeypatch)
    t = await _tenant()
    await _use_schema(t)
    contact_id = await _verified_contact(t)
    async with tenant_session(t.tenant_id) as session:
        await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(contact_id=None, on_fields=(FieldTrigger("budget_band", ("over_50l",)),)),
        )
    call_id = await _call(t)

    async def _after(data: dict[str, Any]) -> str:
        async with tenant_session(t.tenant_id) as session:
            return await service.queue_after_call(
                session,
                tenant_id=t.tenant_id,
                agent_id=t.agent_id,
                call_id=call_id,
                outcome_key=None,
                outcome_label=None,
                data=data,
                labels={"budget_band": "Budget band"},
            )

    assert await _after({"budget_band": "under_20l"}) == "no_trigger"
    assert await _after({"budget_band": "over_50l"}) == "queued"
    assert await _after({"budget_band": "over_50l"}) == "already_queued"

    payloads = await _alert_payloads(t.tenant_id)
    assert len(payloads) == 1
    ctx = {"job_try": 1}
    assert await worker.deliver_team_alert(ctx, payloads[0]) == "sent"
    assert await worker.deliver_team_alert(ctx, payloads[0]) == "duplicate"
    to, body = mail.sent[0]
    assert to == "team@example.com"
    assert f"Phone: {CALLER}" in body, "the team gets the full number to ring back"
    assert "Budget band: over_50l" in body
    assert f"/c/{t.slug}/calls/{call_id}" in body
    assert "9812345678" not in body.split("Call summary:")[1], "the summary stays redacted"
    async with tenant_session(t.tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, contact_id FROM team_alerts WHERE call_id = :c"),
                {"c": call_id},
            )
        ).first()
    assert row is not None and row[0] == "sent" and row[1] == contact_id


async def test_without_a_verified_address_nothing_is_queued() -> None:
    t = await _tenant()
    await _use_schema(t)
    async with tenant_session(t.tenant_id) as session:
        await service.add_contact(session, tenant_id=t.tenant_id, address="later@example.com")
        await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(contact_id=None, on_fields=(FieldTrigger("budget_band", ("over_50l",)),)),
        )
        outcome = await service.queue_after_call(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            call_id=await _call(t),
            outcome_key=None,
            outcome_label=None,
            data={"budget_band": "over_50l"},
            labels={},
        )
    assert outcome == "no_contact"


async def test_an_exhausted_alert_is_failed_and_alarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mail(monkeypatch, delivered=False)
    fired: list[str] = []
    monkeypatch.setattr(worker, "alert", lambda stage, code, **_: fired.append(code))
    t = await _tenant()
    await _verified_contact(t)
    async with tenant_session(t.tenant_id) as session:
        await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(contact_id=None, in_call=True),
        )
    call_id = await _call(t)
    assert (
        await service.queue_in_call(
            tenant_id=t.tenant_id, agent_id=t.agent_id, call_id=call_id, problem="Cannot log in"
        )
        == "queued"
    )
    payload = (await _alert_payloads(t.tenant_id))[0]
    with pytest.raises(Retry):
        await worker.deliver_team_alert({"job_try": 1}, payload)
    assert await worker.deliver_team_alert({"job_try": 3}, payload) == "exhausted after 3"
    assert fired == ["team_alert_exhausted"]


# ------------------------------------------------------------------ in call


async def test_the_agent_can_tell_the_team_only_when_it_has_the_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mail = _mail(monkeypatch)
    t = await _tenant()
    call_id = await _call(t)
    facts = CallFacts(
        call_ref=f"ta-{call_id.hex}", caller_e164=CALLER, direction="inbound", call_id=call_id
    )
    args = {"problem": "Forgot the password; my card 4111 1111 1111 1111"}

    refused = await in_call._run_in_call_action(
        tenant_id=t.tenant_id,
        agent_id=t.agent_id,
        name=service.TEAM_ACTION_NAME,
        args=args,
        call=facts,
    )
    assert refused.status == "unavailable" and "Do NOT say" in refused.say

    await _verified_contact(t)
    async with tenant_session(t.tenant_id) as session:
        await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(contact_id=None, in_call=True),
        )
        definitions = await engine_actions.client_definitions(
            session, "thinnest", "ag_x", t.agent_id
        )
    told = [d for d in definitions if d.name == service.TEAM_ACTION_NAME]
    assert told and told[0].parameters[0].name == service.TEAM_PROBLEM_PARAM
    assert "only after the answer says the team was told" in told[0].description

    first = await in_call._run_in_call_action(
        tenant_id=t.tenant_id,
        agent_id=t.agent_id,
        name=service.TEAM_ACTION_NAME,
        args=args,
        call=facts,
    )
    again = await in_call._run_in_call_action(
        tenant_id=t.tenant_id,
        agent_id=t.agent_id,
        name=service.TEAM_ACTION_NAME,
        args=args,
        call=facts,
    )
    assert (first.status, again.status) == ("queued", "already_told")

    payload = (await _alert_payloads(t.tenant_id))[0]
    assert "4111" not in payload["problem"], "the agent's note is redacted"
    assert await worker.deliver_team_alert({"job_try": 1}, payload) == "sent"
    body = mail.sent[0][1]
    assert "What the agent noted: Forgot the password" in body and f"Phone: {CALLER}" in body
    assert "Call summary" not in body, "the in-call alert goes before any summary exists"

    # After the call, the same address is not told again about the same call.
    async with tenant_session(t.tenant_id) as session:
        outcome_key = (await service.read_rule(session, agent_id=t.agent_id)).outcomes[0].key
        await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(contact_id=None, on_outcomes=(outcome_key,), in_call=True),
        )
        after = await service.queue_after_call(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            call_id=call_id,
            outcome_key=outcome_key,
            outcome_label="x",
            data={},
            labels={},
        )
    assert after == "already_queued"


def test_a_client_action_cannot_take_the_team_action_name() -> None:
    assert service.TEAM_ACTION_NAME in RESERVED_ACTION_NAMES
    assert worker.send_team_contact_code.__name__ == service.CODE_JOB
    assert worker.deliver_team_alert.__name__ == service.ALERT_JOB


def test_the_alert_text_keeps_untrusted_values_on_one_line() -> None:
    body = worker.compose_alert(
        agent_name="Rytu",
        caller_name="Ravi\n\nhttps://evil.example",
        phone=CALLER,
        at=datetime(2026, 10, 27, 10, 30, tzinfo=UTC),
        reasons=[{"kind": "outcome", "key": "k", "label": "Needs a reset"}],
        problem="",
        summary=None,
        link="https://app.example/c/x/calls/1",
    )
    assert "Name: Ravi https://evil.example" in body
    assert "27 Oct 2026, 04:00 PM IST" in body
    assert body.rstrip().endswith("https://app.example/c/x/calls/1")


# ------------------------------------------------------------------ tenancy + routes


async def test_another_client_sees_none_of_it() -> None:
    t = await _tenant()
    await _verified_contact(t)
    async with tenant_session(t.tenant_id) as session:
        await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(contact_id=None, in_call=True),
        )
    await service.queue_in_call(
        tenant_id=t.tenant_id, agent_id=t.agent_id, call_id=await _call(t), problem="help"
    )
    other = await _tenant()
    async with tenant_session(other.tenant_id) as session:
        for table in ("team_alert_contacts", "team_alert_rules", "team_alerts"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            assert count == 0, table


async def test_the_routes_serve_the_owner_and_refuse_a_stranger() -> None:
    from apps.api.main import app

    t, stranger = await _tenant(), await _tenant()
    await _use_schema(t)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        added = await client.post(
            "/v1/team-alerts/contacts", json={"address": "Help@Example.com"}, headers=t.headers
        )
        assert added.status_code == 200, added.text
        contact = added.json()["contacts"][0]
        assert contact == {
            "id": contact["id"],
            "channel": "email",
            "address": "help@example.com",
            "is_default": True,
            "verified": False,
            "whatsapp_account_id": None,
        }
        assert added.json()["whatsapp_accounts"] == [], "no connection of theirs, no WhatsApp"
        bad = await client.post(
            "/v1/team-alerts/contacts", json={"address": "not-an-email"}, headers=t.headers
        )
        assert bad.status_code == 422
        code = await _code_for(t.tenant_id, uuid.UUID(contact["id"]))
        wrong = await client.post(
            f"/v1/team-alerts/contacts/{contact['id']}/verify",
            json={"code": "000000" if code != "000000" else "111111"},
            headers=t.headers,
        )
        assert wrong.status_code == 422 and wrong.json()["type"].endswith("/team_code_wrong")
        ok = await client.post(
            f"/v1/team-alerts/contacts/{contact['id']}/verify",
            json={"code": code},
            headers=t.headers,
        )
        assert ok.status_code == 200 and ok.json()["contacts"][0]["verified"] is True

        put = await client.put(
            f"/v1/agents/{t.agent_id}/team-alert",
            json={"on_fields": [{"key": "budget_band", "values": ["over_50l"]}], "in_call": True},
            headers=t.headers,
        )
        assert put.status_code == 200, put.text
        rule = put.json()
        assert rule["sends_to"] == contact["id"] and rule["in_call_live"] is True

        assert (
            await client.get(f"/v1/agents/{t.agent_id}/team-alert", headers=stranger.headers)
        ).status_code == 404
        theirs = await client.get("/v1/team-alerts/contacts", headers=stranger.headers)
        assert theirs.status_code == 200 and theirs.json()["contacts"] == []
        gone = await client.delete(
            f"/v1/team-alerts/contacts/{contact['id']}", headers=stranger.headers
        )
        assert gone.status_code == 404
