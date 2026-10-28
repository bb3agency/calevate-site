"""A file added to the knowledge after onboarding shapes every agent's script, as a
suggestion the owner keeps or dismisses (D-923, founder 28 Oct 2026): the same effect an
onboarding document has on the first agent's script, without overwriting what they wrote."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_proposals
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.first_run import service as first_run
from apps.api.kb import service as kb_service
from apps.api.kb import uploads
from apps.workers import script_proposal as worker
from calevate_shared.call_script import CallScript
from sqlalchemy import text
from tests.conftest import FakeS3, create_org_with_receptionist

pytestmark = [pytest.mark.rls]

PHONE = "9876543210"
PRICE_LIST = f"Price list: 2BHK from Rs 65 lakh. Site visits daily 10 to 6. Call Ravi on {PHONE}."


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Madhav Homes",
        slug=f"know-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _file(tenant_id: uuid.UUID, words: str, name: str = "prices.txt") -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        made = await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            name=None,
            filename=name,
            content_type="text/plain",
            data=b"placeholder",
            submitted_by=None,
            auto_approve=True,
        )
        upload_id = uuid.UUID(str(made["id"]))
        source_id = (
            await session.execute(
                text("SELECT source_id FROM kb_uploads WHERE id = :id"), {"id": upload_id}
            )
        ).scalar_one()
        await kb_service.store_extracted_text(
            session, tenant_id=tenant_id, source_id=source_id, body=words
        )
    return upload_id


async def _suggest(tenant_id: uuid.UUID, upload_id: uuid.UUID) -> str:
    return await worker.suggest_scripts_from_document(
        {}, {"tenant_id": str(tenant_id), "upload_id": str(upload_id)}
    )


async def _proposal(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return await script_proposals.read_proposal(session, agent_id)


async def _jobs(agent_id: uuid.UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = await session.execute(
            text("SELECT job FROM outbox_messages WHERE payload->>'agent_id' = :aid"),
            {"aid": str(agent_id)},
        )
        return [str(r[0]) for r in rows]


async def test_a_new_file_queues_a_suggestion_for_every_agent(s3: FakeS3) -> None:
    del s3
    tenant_id, agent_id = await _tenant()
    upload_id = await _file(tenant_id, PRICE_LIST)
    assert await _suggest(tenant_id, upload_id) == "suggested:1"
    proposal = await _proposal(tenant_id, agent_id)
    assert proposal.mode == script_proposals.KNOWLEDGE_MODE
    assert proposal.status == "drafting"
    assert proposal.documents == [upload_id]
    assert proposal.document_names == ["prices.txt"]
    assert proposal.requested_by is None
    assert script_proposals.PROPOSAL_JOB in await _jobs(agent_id)


async def test_an_onboarding_document_is_not_suggested_again(s3: FakeS3) -> None:
    del s3
    tenant_id, agent_id = await _tenant()
    upload_id = await _file(tenant_id, PRICE_LIST)
    async with tenant_session(tenant_id) as session:
        await first_run.add_document(session, tenant_id=tenant_id, upload_id=upload_id)
    assert await _suggest(tenant_id, upload_id) == "onboarding_document"
    assert await _proposal(tenant_id, agent_id) is None


async def test_the_owners_own_waiting_request_is_never_replaced(s3: FakeS3) -> None:
    del s3
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        asked = await script_proposals.request_proposal(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            mode="change",
            change="Ask for the budget before the area.",
            answers={},
            requested_by=uuid.uuid4(),
        )
    upload_id = await _file(tenant_id, PRICE_LIST)
    assert await _suggest(tenant_id, upload_id) == "suggested:0"
    kept = await _proposal(tenant_id, agent_id)
    assert kept.id == asked.id and kept.mode == "change"


async def test_a_second_file_joins_the_waiting_suggestion(s3: FakeS3) -> None:
    del s3
    tenant_id, agent_id = await _tenant()
    first = await _file(tenant_id, PRICE_LIST)
    second = await _file(tenant_id, "Open Sunday 9 to 1.", name="hours.txt")
    await _suggest(tenant_id, first)
    await _suggest(tenant_id, second)
    proposal = await _proposal(tenant_id, agent_id)
    assert proposal.documents == [first, second]
    assert proposal.document_names == ["prices.txt", "hours.txt"]


async def test_a_file_with_no_words_suggests_nothing(s3: FakeS3) -> None:
    del s3
    tenant_id, agent_id = await _tenant()
    upload_id = await _file(tenant_id, PRICE_LIST)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "DELETE FROM kb_documents WHERE source_id = "
                "(SELECT source_id FROM kb_uploads WHERE id = :id)"
            ),
            {"id": upload_id},
        )
    assert await _suggest(tenant_id, upload_id) == "no_words"
    assert await _proposal(tenant_id, agent_id) is None


async def test_the_draft_edits_the_current_script_with_the_file_redacted(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    del s3
    tenant_id, agent_id = await _tenant()
    upload_id = await _file(tenant_id, PRICE_LIST)
    await _suggest(tenant_id, upload_id)
    seen: dict[str, Any] = {}

    async def draft(_brief: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(
            script=CallScript(opening_line="Namaste!"),
            earlier=(),
            model="gemini-2.5-flash-lite",
            capability=SimpleNamespace(disclosure=None),
        )

    async def meter(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "draft_script", draft)
    monkeypatch.setattr(worker.crm_assist, "meter_earlier", meter)
    monkeypatch.setattr(worker.crm_assist, "meter_assist", meter)
    proposal = await _proposal(tenant_id, agent_id)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal.id),
    }
    assert await worker.draft_script_proposal({}, payload) == "ready"
    # An edit of the script the owner has, so their own lines stay.
    assert seen["edit_of"] == proposal.base_script
    change = seen["change"]
    assert change.startswith("The owner added the documents below")
    assert "65 lakh" in change
    # Redacted before any model sees it, as at onboarding.
    assert PHONE not in change
    assert (await _proposal(tenant_id, agent_id)).status == "ready"


def test_a_both_agent_is_asked_for_its_calling_opening_too() -> None:
    assert "the opening line when it calls" in worker.knowledge_change("x", both=True)
    assert "when it calls" not in worker.knowledge_change("x", both=False)
