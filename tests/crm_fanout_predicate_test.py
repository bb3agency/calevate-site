"""One rule, one spelling: which endpoints does `call.completed` fan out to?

`integrations.enqueue_events` writes one outbox row per endpoint matching
`active = true AND kind = ANY(DELIVERABLE_KINDS) AND :event = ANY(events)`.
`pipeline._pipeline_settled`'s `crm_fanout_owed` probe — whose own docstring said it
mirrors that predicate — asked `active = true AND 'call.completed' = ANY(events)` and
left the `kind` half out (correctness finding 5).

**Why that is worth a test rather than a shrug.** The two agree today only by accident:
`ck_outbound_webhooks_kind_enum` allows exactly `('webhook', 'google_sheets')`, which is
exactly `DELIVERABLE_KINDS`. The day a third kind lands in the CHECK ahead of its
delivery worker — the ordinary way a third kind arrives — `enqueue_events` writes zero
rows for that tenant, `crm_notified_at` stays NULL, and the probe expects the artefact
anyway. Every completed call for that tenant then reads `unfinished_pipeline` forever and
the poller re-drives the whole pipeline once an hour, **including a billed extraction**.

The divergence is therefore exercised the only way it can be while the CHECK constraint
still holds: by narrowing `DELIVERABLE_KINDS` for the duration of one test, which is the
same move a third kind makes from the other direction. Both call sites read that tuple at
query time, so one patch moves both — and that is itself the property under test.
"""

from __future__ import annotations

import uuid
from typing import Any

import apps.workers.pipeline as pipeline_module
import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.integrations import service as integrations
from sqlalchemy import text
from tests.poller_guarantee_test import _age, _staged


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recording copy needs a bucket; nothing here is about object storage."""

    async def _fake_copy(
        *, source_url: str, tenant_id: uuid.UUID, call_id: uuid.UUID, leg: str = "call"
    ) -> str:
        # `leg` NAMES WHICH OF A CALL'S TWO RECORDINGS (D-533): a call handed to a
        # person has a second one, and the two must not land on one key. Defaulted so
        # this stub reads the way the pipeline calls it for an ordinary call.
        suffix = "" if leg == "call" else "-transfer"
        return f"recordings/{tenant_id}/{call_id}{suffix}.wav"

    monkeypatch.setattr(pipeline_module, "copy_recording", _fake_copy)


async def _forget_queued_work(tenant_id: uuid.UUID) -> None:
    """Delete the outbox rows this test's pipeline run left PENDING.

    Not tidiness: `claim_outbox_batch` is oldest-first over the whole table, so rows no
    worker in this suite will ever publish accumulate at the head of every dispatcher's
    queue and eventually fail a neighbour's claim test —
    `tests/shared_state_assertion_guard_test.py` documents that exact incident. Scoped by
    tenant id, never a bare `DELETE FROM outbox_messages`, which is the same
    whole-database mutation the guard exists to prevent.
    """
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE payload::text LIKE :needle"),
            {"needle": f"%{tenant_id}%"},
        )


async def _webhook_endpoint(tenant_id: uuid.UUID) -> uuid.UUID:
    """An ACTIVE endpoint subscribed to `call.completed`. `kind` is `webhook` because the
    CHECK constraint permits nothing else — the test moves `DELIVERABLE_KINDS` instead."""
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, active, created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example/hook', 'whsec_fanout_predicate', "
                "ARRAY['call.completed'], CAST('{}' AS jsonb), true, now(), now())"
            ),
            {"id": endpoint_id, "tid": tenant_id},
        )
    return endpoint_id


async def _settled_call(tenant_id: uuid.UUID, agent_ref: str, execution_id: str) -> Any:
    """Drive one call all the way through, with NO endpoint configured yet, and age it
    past `PIPELINE_STALL_AFTER` so the probe judges artefacts rather than granting grace.

    Every artefact but the CRM fan-out is therefore present and stays present, which is
    what isolates the predicate: the endpoint is added AFTERWARDS, so `crm_notified_at`
    is legitimately NULL and `crm_fanout_owed` is the only thing left deciding the
    verdict. An endpoint configured after a call is also the ordinary way this happens.
    """
    await pipeline_module.ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar_one()
    await pipeline_module.run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )
    await _age(tenant_id, execution_id, minutes=18)
    snapshot = await get_engine().get_execution(execution_id)
    assert await pipeline_module._pipeline_settled("fake", snapshot) == "settled", (
        "premise: with no endpoint configured, this call owes nothing and is settled"
    )
    return snapshot


async def test_an_endpoint_of_an_undeliverable_kind_is_owed_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE DIVERGENCE, made reachable. An active endpoint subscribed to `call.completed`
    whose kind has no delivery worker gets ZERO outbox rows from `enqueue_events` — so a
    probe that expects a fan-out artefact anyway condemns every completed call for that
    tenant to a permanent `unfinished_pipeline`, re-driven hourly with a billed
    extraction.
    """
    tenant_id, agent_ref, execution_id = await _staged("fanoutkind")
    snapshot = await _settled_call(tenant_id, agent_ref, execution_id)
    await _webhook_endpoint(tenant_id)

    # The third-kind world, from the other side: `webhook` is a kind that EXISTS and is
    # not deliverable. This is exactly the state a new kind in the CHECK constraint puts
    # its predecessors' assumptions in.
    monkeypatch.setattr(integrations, "DELIVERABLE_KINDS", (integrations.SHEET_KIND,))

    async with tenant_session(tenant_id) as session:
        written = await integrations.enqueue_events(
            session,
            tenant_id=tenant_id,
            event="call.completed",
            rows=[{"id": str(uuid7()), "name": "probe"}],
        )
    assert written == 0, "premise: an undeliverable kind is fanned out to by nothing"

    verdict = await pipeline_module._pipeline_settled("fake", snapshot)
    assert verdict != "unfinished_pipeline", (
        "the probe expected a CRM fan-out that `enqueue_events` will never write — every "
        "completed call for this tenant is now a permanent repair with a billed "
        "extraction on every tick"
    )
    await _forget_queued_work(tenant_id)


async def test_a_deliverable_endpoint_is_still_owed_a_fanout() -> None:
    """The counterweight, and the reason the `kind` half cannot simply be dropped from
    both sides: a real subscribed endpoint that WAS owed a delivery and did not get one is
    the whole point of the probe (P6.4). Narrowing the predicate must not narrow this."""
    tenant_id, agent_ref, execution_id = await _staged("fanoutowed")
    snapshot = await _settled_call(tenant_id, agent_ref, execution_id)
    await _webhook_endpoint(tenant_id)

    assert await pipeline_module._pipeline_settled("fake", snapshot) == "unfinished_pipeline", (
        "a tenant with a live CRM endpoint and no fan-out is exactly the call the poller "
        "exists to re-drive"
    )
    await _forget_queued_work(tenant_id)


def test_the_predicate_has_one_definition_and_both_callers_read_it() -> None:
    """Structural, and deliberately so: the behaviour above proves they AGREE today, and
    this proves they cannot drift tomorrow, which is the actual finding. A restated
    predicate that happens to match is the defect — not the mismatch it eventually
    becomes."""
    import inspect

    sql = integrations.subscribed_endpoint_sql("w")
    assert "w.kind = ANY(:kinds)" in sql and ":event = ANY(w.events)" in sql
    assert "w.active = true" in sql

    for owner in (integrations.enqueue_events, pipeline_module._pipeline_settled):
        source = inspect.getsource(owner)
        assert "subscribed_endpoint_sql" in source, (
            f"{owner.__qualname__} spells the endpoint predicate itself again. Two "
            "spellings of one rule is a defect even while both agree."
        )
        assert "= ANY(w.events)" not in source, "the restatement came back alongside the import"
