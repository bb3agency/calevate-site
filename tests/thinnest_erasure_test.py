"""An erasure on ThinnestAI erases OUR copies and asks the platform to delete each call (D-798).

ThinnestAI deletes one call's recording, transcript, summary and collected fields on request
(`thinnest-findings/mirror/snapshots/2026-10-15/pages/api-reference/post-call/
delete-call-content.md:443-533`), so every erasure queues that deletion for the subject's
calls, whichever workspace holds them. Its contact erasure is workspace-wide (D-691), so for a
call in our shared developer workspace the contact is NOT asked: the `voice_engine` task says
`contact-not-asked` and waits only on the calls.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.compliance.processor_erasure import (
    CONTACT_NOT_ASKED,
    VOICE_PLATFORM_CONTENT_DELETION,
    VOICE_PLATFORM_CONTENT_DELETION_SENTENCE,
    VOICE_PLATFORM_TENANT_CONTENT_SENTENCE,
)
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers import retention
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist


async def _tenant_with_a_platform_call() -> tuple[uuid.UUID, uuid.UUID, str, str]:
    created = await create_org_with_receptionist(
        name="Erasure on the platform",
        slug=f"tea-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    call_id = uuid.uuid4()
    phone = f"+9198{uuid.uuid4().int % 100000000:08d}"
    engine_call_id = f"out_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "engine_payload_ref, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'outbound', 'completed', '+911140000000', :phone, now(), now(), 61, "
                "'recordings/thinnest.wav', 'Asked for a price', NULL, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": created["agent_id"],
                "e": engine_call_id,
                "phone": phone,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, 0, 'caller', "
                "'naa peru Ravi', 'naa peru Ravi', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id},
        )
    return tenant_id, call_id, phone, engine_call_id


async def _request(tenant_id: uuid.UUID, phone: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return uuid.UUID(
            str(
                (
                    await session.execute(
                        text(
                            "INSERT INTO deletion_requests (id, tenant_id, phone_e164, "
                            "subject_ref, scope, requested_at, created_at) VALUES "
                            "(gen_random_uuid(), :t, :p, :r, 'all', now(), now()) RETURNING id"
                        ),
                        {"t": tenant_id, "p": phone, "r": uuid.uuid4().hex},
                    )
                ).scalar_one()
            )
        )


async def test_our_copies_are_erased_and_each_platform_call_is_asked_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, call_id, phone, engine_call_id = await _tenant_with_a_platform_call()
    request_id = await _request(tenant_id, phone)

    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    async with tenant_session(tenant_id) as session:
        call = (
            await session.execute(
                text("SELECT from_e164, to_e164, recording_url, summary FROM calls WHERE id = :c"),
                {"c": call_id},
            )
        ).one()
        turn = (
            await session.execute(
                text("SELECT text, text_redacted FROM transcript_turns WHERE call_id = :c"),
                {"c": call_id},
            )
        ).one()
        proof: dict[str, Any] = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar_one()
        task = (
            await session.execute(
                text(
                    "SELECT status, vendor_refs, vendor_reference FROM processor_erasure_tasks "
                    "WHERE request_ref = :r AND processor = 'voice_engine'"
                ),
                {"r": request_id},
            )
        ).one()
        requested_at = (
            await session.execute(
                text("SELECT engine_content_delete_requested_at FROM calls WHERE id = :c"),
                {"c": call_id},
            )
        ).scalar_one()
        queued = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE job = 'delete_engine_call_content'")
            )
        ).scalars()
        payloads = [p for p in queued if p.get("tenant_id") == str(tenant_id)]

    # Ours: the numbers, the pointer to our recording copy, the summary and the words.
    assert call[0] is None and call[1] is None and call[2] is None
    assert call[3] in (None, "")
    assert "Ravi" not in f"{turn[0]} {turn[1]}"
    # Theirs: each call queued for deletion; the shared workspace's contact is not asked.
    assert proof["engine_deletion"] == VOICE_PLATFORM_CONTENT_DELETION
    assert proof["actions"]["voice_platform"].endswith(VOICE_PLATFORM_CONTENT_DELETION_SENTENCE)
    assert proof["actions"]["voice_platform"].startswith("1 call record(s)")
    assert task == ("open", [engine_call_id], CONTACT_NOT_ASKED)
    assert requested_at is not None
    assert payloads == [{"tenant_id": str(tenant_id), "call_ids": [str(call_id)]}]


async def test_another_engines_calls_still_open_the_written_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exception is ThinnestAI's alone: elsewhere a third-party engine's record is still
    a written request with a task behind it (D-433)."""
    monkeypatch.setattr(get_settings(), "engine", "cartesia")
    tenant_id, _call_id, phone, engine_call_id = await _tenant_with_a_platform_call()
    request_id = await _request(tenant_id, phone)

    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar_one()
        refs = (
            await session.execute(
                text(
                    "SELECT vendor_refs FROM processor_erasure_tasks WHERE request_ref = :r "
                    "AND processor = 'voice_engine'"
                ),
                {"r": request_id},
            )
        ).scalar_one()
    assert proof["engine_deletion"] == "unconfirmed_pending_vendor_api"
    assert "voice_platform" not in proof["actions"]
    assert refs == [engine_call_id]


async def test_a_tenant_erasure_asks_the_platform_to_delete_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests import tenant_erasure_test as te

    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, _call_id, _phone, _engine_call_id = await _tenant_with_a_platform_call()
    await te._churn(tenant_id)
    token = await te._admin()
    filed = await te._post(token, tenant_id, confirm=te._confirm(tenant_id))
    assert filed.status_code == 201, filed.text
    request_id = filed.json()["request_id"]

    await te._run_worker(tenant_id, request_id)

    async with te._client() as http:
        read = await http.get(
            f"{te.BASE.format(tenant_id=tenant_id)}/{request_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    proof = read.json()["proof"]
    assert proof["actions"]["voice_platform"] == (
        "1 call record(s) also held by the voice platform: "
        f"{VOICE_PLATFORM_TENANT_CONTENT_SENTENCE}"
    )
