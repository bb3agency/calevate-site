"""Restoring a person's opt-out that was recorded by mistake, or that they have withdrawn.

A consumer's opt-out cannot be REMOVED by the client (`dnc_test.py`). It can be RESTORED on
one of two attested grounds, and these tests hold the shape of that: the number becomes
dialable again, the reversal is in the hash-chained audit log under its ground, no consent
is fabricated in the append-only ledger, a newer opt-out the client was not shown is never
undone, regulator and platform-wide entries stay out of reach, and no number is logged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.compliance import dnc
from apps.api.compliance.optout import (
    DETECTED_BY_ENGINE,
    DETECTED_POST_CALL,
    OptOutSignal,
    record_call_optout,
)
from apps.api.compliance.service import check_dispatch
from apps.api.core.logging import JsonFormatter
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.dnc_test import _client, _code, _headers, _insert_global, _number, _tenant


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, `dnc_test`'s reason: `calling_hours` must not stand in for `dnc`."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', "
                ":to, 'completed', now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"out_{uuid.uuid4()}",
                "to": phone,
            },
        )
    return call_id


async def _opted_out(
    tenant_id: uuid.UUID,
    phone: str,
    *,
    call_id: uuid.UUID | None,
    detected_by: str = DETECTED_BY_ENGINE,
    matched: str = "",
) -> uuid.UUID:
    """An opt-out filed through the one writer, as the engine signal files it."""
    async with tenant_session(tenant_id) as session:
        await record_call_optout(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            call_id=call_id,
            detected_by=detected_by,
            signal=OptOutSignal(
                rule="engine_contact_opted_out" if not matched else "do_not_call",
                language="unknown" if not matched else "en",
                turn_idx=None if not matched else 1,
                matched=matched,
            ),
        )
        entry_id = (
            await session.execute(
                text("SELECT id FROM dnc_list WHERE tenant_id = :t AND phone_e164 = :p"),
                {"t": tenant_id, "p": phone},
            )
        ).scalar()
    assert entry_id is not None
    return uuid.UUID(str(entry_id))


async def _evidence(token: str, slug: str, entry_id: uuid.UUID) -> dict[str, Any]:
    async with _client() as http:
        response = await http.get(f"/v1/dnc/{entry_id}/evidence", headers=_headers(token, slug))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _ledger_rows(tenant_id: uuid.UUID, phone: str) -> list[tuple[str, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT purpose, status FROM consent_ledger "
                    "WHERE tenant_id = :t AND phone_e164 = :p ORDER BY captured_at"
                ),
                {"t": tenant_id, "p": phone},
            )
        ).all()
    return [(str(row[0]), str(row[1])) for row in rows]


async def test_a_mistaken_engine_opt_out_is_shown_with_its_call_and_can_be_restored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id, agent_id, slug, token = await _tenant()
    phone = _number()
    call_id = await _call(tenant_id, agent_id, phone)
    entry_id = await _opted_out(tenant_id, phone, call_id=call_id)

    async with _client() as http:
        listed = await http.get("/v1/dnc", headers=_headers(token, slug))
    [entry] = [e for e in listed.json() if e["id"] == str(entry_id)]
    assert entry["removable"] is False and entry["restorable"] is True

    evidence = await _evidence(token, slug, entry_id)
    assert evidence["restorable"] is True
    [record] = evidence["records"]
    assert record["call_id"] == str(call_id)
    assert record["detected_by"] == DETECTED_BY_ENGINE
    # The platform's agent reports that it recorded it, not the words.
    assert record["matched_redacted"] is None
    ledger_before = await _ledger_rows(tenant_id, phone)

    formatter = JsonFormatter()
    with caplog.at_level(logging.INFO):
        async with _client() as http:
            restored = await http.post(
                f"/v1/dnc/{entry_id}/restore",
                headers=_headers(token, slug),
                json={"ground": "never_asked", "latest_evidence_id": record["id"]},
            )
    assert restored.status_code == 204, restored.text
    assert restored.content == b""

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )
    assert decision.rule != "dnc", "a restored number must be dialable as far as the list goes"

    # No consent was invented: the ledger holds exactly the opt-out it held before.
    assert await _ledger_rows(tenant_id, phone) == ledger_before == [("marketing", "withdrawn")]

    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT action, object_id, actor_type FROM audit_log WHERE tenant_id = :t "
                    "AND action LIKE 'dnc.optout_restored.%'"
                ),
                {"t": tenant_id},
            )
        ).all()
    assert [tuple(row) for row in audited] == [
        ("dnc.optout_restored.never_asked", str(entry_id), "user")
    ]
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert phone not in rendered and phone.lstrip("+") not in rendered


async def test_since_asked_needs_a_note_and_the_note_never_keeps_a_number(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id, _agent_id, slug, token = await _tenant()
    phone = _number()
    entry_id = await _opted_out(
        tenant_id,
        phone,
        call_id=None,
        detected_by=DETECTED_POST_CALL,
        matched="dont call me again",
    )
    [record] = (await _evidence(token, slug, entry_id))["records"]
    assert record["matched_redacted"] == "dont call me again"

    async with _client() as http:
        bare = await http.post(
            f"/v1/dnc/{entry_id}/restore",
            headers=_headers(token, slug),
            json={"ground": "asked_to_be_called", "latest_evidence_id": record["id"]},
        )
        assert bare.status_code == 422
        assert _code(bare) == "dnc_restore_note_required"

        formatter = JsonFormatter()
        with caplog.at_level(logging.INFO):
            done = await http.post(
                f"/v1/dnc/{entry_id}/restore",
                headers=_headers(token, slug),
                json={
                    "ground": "asked_to_be_called",
                    "note": "Rang the office on 3 Oct from 9876543210 asking for a call back",
                    "latest_evidence_id": record["id"],
                },
            )
    assert done.status_code == 204, done.text
    rendered = "\n".join(formatter.format(r) for r in caplog.records)
    assert "asked_to_be_called" in rendered
    assert "asking for a call back" in rendered, "the note is the evidence; it is kept"
    assert "9876543210" not in rendered


async def test_a_newer_opt_out_than_the_one_shown_is_never_undone() -> None:
    tenant_id, agent_id, slug, token = await _tenant()
    phone = _number()
    first_call = await _call(tenant_id, agent_id, phone)
    entry_id = await _opted_out(tenant_id, phone, call_id=first_call)
    [shown] = (await _evidence(token, slug, entry_id))["records"]

    # The person opts out again on another call while the dialog is open.
    await _opted_out(tenant_id, phone, call_id=await _call(tenant_id, agent_id, phone))

    async with _client() as http:
        stale = await http.post(
            f"/v1/dnc/{entry_id}/restore",
            headers=_headers(token, slug),
            json={"ground": "never_asked", "latest_evidence_id": shown["id"]},
        )
    assert stale.status_code == 409
    assert _code(stale) == "dnc_restore_stale"
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )
    assert decision.rule == "dnc"


@pytest.mark.parametrize(
    ("source", "code"), [("regulator", "dnc_not_restorable"), ("manual", "dnc_not_restorable")]
)
async def test_only_a_persons_own_opt_out_is_restorable(source: str, code: str) -> None:
    tenant_id, _agent_id, slug, token = await _tenant()
    phone = _number()
    async with tenant_session(tenant_id) as session:
        await dnc.add_numbers(session, tenant_id=tenant_id, raw_numbers=[phone], source=source)
        entry_id = (
            await session.execute(
                text("SELECT id FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert (await _evidence(token, slug, uuid.UUID(str(entry_id))))["restorable"] is False
    async with _client() as http:
        refused = await http.post(
            f"/v1/dnc/{entry_id}/restore",
            headers=_headers(token, slug),
            json={"ground": "never_asked", "latest_evidence_id": None},
        )
    assert refused.status_code == 422
    assert _code(refused) == code


async def test_a_platform_wide_entry_is_never_restorable_by_a_client() -> None:
    _tenant_id, _agent_id, slug, token = await _tenant()
    entry_id = await _insert_global(_number())
    async with _client() as http:
        refused = await http.post(
            f"/v1/dnc/{entry_id}/restore",
            headers=_headers(token, slug),
            json={"ground": "never_asked", "latest_evidence_id": None},
        )
    assert refused.status_code == 422
    assert _code(refused) == "dnc_global_entry"


async def test_another_clients_opt_out_is_not_found_and_stays_suppressed() -> None:
    owner_id, owner_agent, _slug_a, _token_a = await _tenant()
    _other_id, _other_agent, slug_b, token_b = await _tenant()
    phone = _number()
    entry_id = await _opted_out(owner_id, phone, call_id=None)

    async with _client() as http:
        peek = await http.get(f"/v1/dnc/{entry_id}/evidence", headers=_headers(token_b, slug_b))
        attempt = await http.post(
            f"/v1/dnc/{entry_id}/restore",
            headers=_headers(token_b, slug_b),
            json={"ground": "never_asked", "latest_evidence_id": None},
        )
    assert peek.status_code == 404
    assert attempt.status_code == 404
    async with tenant_session(owner_id) as session:
        decision = await check_dispatch(
            session, tenant_id=owner_id, agent_id=owner_agent, phone_e164=phone
        )
    assert decision.rule == "dnc"


async def test_staff_cannot_restore() -> None:
    """`leads:dispatch` is the owner's: putting a number back in the dial pool is the same
    authority as dialling it."""
    tenant_id, _agent_id, slug, token = await _tenant(role="staff")
    entry_id = await _opted_out(tenant_id, _number(), call_id=None)
    async with _client() as http:
        refused = await http.post(
            f"/v1/dnc/{entry_id}/restore",
            headers=_headers(token, slug),
            json={"ground": "never_asked", "latest_evidence_id": None},
        )
    assert refused.status_code == 403
