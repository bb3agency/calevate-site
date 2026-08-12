"""What the engine holds when a publish does not run to completion.

`kb_lifecycle_test` pins the supersede ordering: detach the old, attach the new, refuse
if the detach is not confirmed. It pins that ordering against the ENGINE refusing a
call. This file pins the two cases where nothing refuses anything and the divergence
happens anyway.

1. **Publishing a version that is already live.** `_superseded_versions` excludes the
   row being published (`id <> :sid`), so a re-publish detaches nothing and attaches
   again. On the fake adapter that is invisible — it de-duplicates by our `kb_id` and
   mints a stable handle — but `attach_kb` on the real engine is `POST /knowledgebase`,
   which creates a new `rag_id` every time and de-duplicates nothing. Two copies
   attached, one handle recorded: the older one can never be addressed again, is
   retrievable by the agent forever, and is billed forever. The trigger is a
   double-clicked Publish button or a retry after a timeout.

2. **The engine accepted the work and our transaction did not commit.** The publish
   runs inside the caller's transaction, so a commit failure after a successful attach
   rolls back every row while the engine keeps the document. Our tables then describe a
   world that no longer exists: the superseded version is recorded as live under a
   handle the engine has already deleted, and the version the agent is actually
   answering from is recorded as not live. Nothing in the happy path can detect it.

The tests below use the fake adapter but do not ask it to model Bolna's non-idempotent
POST. They assert on the CALL SEQUENCE our code makes and on what the engine reports
through `list_kb` — both adapter-independent, both exactly what the vendor sees.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.kb import service as kb_service
from calevate_shared.engine import EngineAgentRef, EngineKBRef, KBSourceRef
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent


async def _submit_and_approve(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, body: str
) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
    return uuid.UUID(str(submitted["id"]))


async def _publish(tenant_id: uuid.UUID, source_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)


async def _publish_new_version(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, body: str
) -> uuid.UUID:
    source_id = await _submit_and_approve(tenant_id, agent_id, name, body)
    await _publish(tenant_id, source_id)
    return source_id


async def _engine_ref(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar()
        )


async def _recorded_handle(tenant_id: uuid.UUID, source_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return await kb_service._engine_kb_ref(session, source_id)


class _Spy:
    """Records every KB call our code makes to the engine, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def install(self, patch: pytest.MonkeyPatch) -> None:
        engine = get_engine()
        real_attach, real_detach = engine.attach_kb, engine.detach_kb

        async def attach(ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
            handle = await real_attach(ref, source)
            self.calls.append(("attach", handle))
            return handle

        async def detach(ref: EngineAgentRef, kb: EngineKBRef) -> None:
            self.calls.append(("detach", kb))
            await real_detach(ref, kb)

        patch.setattr(engine, "attach_kb", attach)
        patch.setattr(engine, "detach_kb", detach)

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]


# --------------------------------------------------------------------------------
# 1. Re-publishing a live version must not attach a second copy
# --------------------------------------------------------------------------------


async def test_republishing_the_live_version_withdraws_its_own_copy_first() -> None:
    """A publish attaches at most one copy of a source, and never over an old one.

    Asserted on the call sequence rather than on the fake's store, because the fake is
    the one adapter that would survive the bug: it keys its store on our `kb_id`, so a
    second attach silently replaces the first. `POST /knowledgebase` does not. The
    invariant our code owes the engine is "nothing of this source is attached when I
    attach", and only the sequence shows whether we honoured it.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish_new_version(
        tenant_id, agent_id, "Fees", "A consultation costs 500 rupees."
    )
    first_handle = await _recorded_handle(tenant_id, source_id)
    assert first_handle

    spy = _Spy()
    with pytest.MonkeyPatch.context() as patch:
        spy.install(patch)
        await _publish(tenant_id, source_id)

    assert spy.kinds() == ["detach", "attach"], (
        "re-publishing an already-live source attached a second copy without "
        "withdrawing the first — on the real engine that copy is unaddressable and "
        "billed forever"
    )
    assert spy.calls[0][1] == first_handle, "the wrong handle was withdrawn"

    ref = await _engine_ref(tenant_id, agent_id)
    assert len(await get_engine().list_kb(ref)) == 1
    assert await _recorded_handle(tenant_id, source_id) == spy.calls[1][1]


async def test_a_first_publish_withdraws_nothing() -> None:
    """The counterpart. A source with no recorded handle has nothing attached, so the
    withdrawal must not fire — and must not refuse the way an unaddressable LIVE version
    does. `engine_kb_ref IS NULL` means two different things depending on whose row it
    is: on the version being published it means "we have attached nothing yet"; on a
    different version that is still live it means "the engine is serving something we
    cannot name"."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit_and_approve(tenant_id, agent_id, "Hours", "Open 9am to 8pm.")

    spy = _Spy()
    with pytest.MonkeyPatch.context() as patch:
        spy.install(patch)
        await _publish(tenant_id, source_id)

    assert spy.kinds() == ["attach"]


async def test_republishing_does_not_disturb_the_agents_other_sources() -> None:
    """`name` is the unit of supersession; the self-withdrawal must not widen it."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Parking", "Parking is free.")
    fees = await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500.")

    await _publish(tenant_id, fees)

    ref = await _engine_ref(tenant_id, agent_id)
    assert len(await get_engine().list_kb(ref)) == 2


# --------------------------------------------------------------------------------
# 2. The engine accepted the work and our transaction did not commit
# --------------------------------------------------------------------------------


async def _simulate_commit_failure(tenant_id: uuid.UUID, source_id: uuid.UUID) -> None:
    """Run a publish to completion against the engine, then lose every row.

    This is what a lost connection, a serialisation failure or a statement timeout at
    COMMIT leaves behind: the engine calls happened, none of the rows did. Reproduced by
    rolling the transaction back explicitly rather than by patching the driver, because
    the property under test is about the ORDER of side effects, not about how the
    rollback was triggered.
    """
    async with tenant_session(tenant_id) as session:
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
        await session.rollback()


async def test_an_engine_copy_we_never_recorded_stops_the_next_publish() -> None:
    """The orphan must be found before we make a second one.

    After a commit failure the engine holds the new version under a handle no row of
    ours mentions, and our tables still describe the superseded version as live under a
    handle the engine has already deleted. Both statements are wrong and neither is
    visible from our side alone.

    What the next publish attempt did before this check existed: read the superseded
    version's stale handle, ask the engine to delete it, get a 404, and refuse with
    `kb_detach_failed` — whose remediation reads "the previously approved version is
    still live. Try publishing again." Every clause of that is false. The version is not
    live, retrying cannot succeed, and the client's agent is answering from a version we
    believe is not published. A refusal that sends an operator in a circle is worse than
    no refusal, because it looks handled.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    v2 = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    await _simulate_commit_failure(tenant_id, v2)

    ref = await _engine_ref(tenant_id, agent_id)
    on_engine = await get_engine().list_kb(ref)
    assert len(on_engine) == 1, "premise: the engine kept the work the commit lost"

    with pytest.raises(ProblemError) as raised:
        await _publish(tenant_id, v2)

    assert raised.value.code == "kb_engine_out_of_sync", (
        f"the retry refused with {raised.value.code!r}, which sends the operator to "
        "retry a publish that cannot succeed"
    )
    assert raised.value.remediation, "a refusal an operator cannot act on is a dead end"
    # Nothing was made worse: no second copy was attached while we were finding out.
    assert await get_engine().list_kb(ref) == on_engine


async def test_the_reconciliation_never_blocks_an_agent_whose_engine_state_agrees() -> None:
    """The guard must be silent on every ordinary publish, including an agent with
    several named sources — otherwise it is a gate that fails clients for being normal.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Parking", "Parking is free.")
    await _publish_new_version(tenant_id, agent_id, "Hours", "Open 9am to 8pm.")
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    ref = await _engine_ref(tenant_id, agent_id)
    assert len(await get_engine().list_kb(ref)) == 3


async def test_an_engine_that_cannot_be_listed_does_not_block_the_publish(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reconciliation is evidence, not a dependency.

    `list_kb` reads an endpoint whose response shape is an unverified claim until pilot
    gate 8 (`apps/api/engine/bolna.py`), and a knowledge update is a client waiting on a
    correction to what their agent says. So a listing we could not obtain is logged and
    stepped over — it can prove a divergence, it can never prove the absence of one, and
    refusing on "we did not manage to look" would convert a vendor's flaky GET into an
    outage of our approval workflow.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 500.")

    async def _boom(ref: EngineAgentRef) -> list[EngineKBRef]:
        raise ProblemError(
            kind="dependency",
            code="engine_unavailable",
            title="Voice engine unreachable",
            detail="The platform did not respond.",
        )

    engine = get_engine()
    with (
        pytest.MonkeyPatch.context() as patch,
        caplog.at_level("WARNING", logger="apps.api.kb.service"),
    ):
        patch.setattr(engine, "list_kb", _boom)
        await _publish(tenant_id, source_id)

    assert [r for r in caplog.records if r.message == "kb_reconcile_unavailable"], (
        "the publish went ahead on unverified engine state and said nothing"
    )
    assert await _recorded_handle(tenant_id, source_id)


# --------------------------------------------------------------------------------
# 3. Nothing about KB CONTENT reaches a log line (hard rule 6)
# --------------------------------------------------------------------------------


async def test_no_publish_log_line_carries_knowledge_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """KB documents are the one place a client's own staff names and phone numbers are
    typed in deliberately, so the publish path is the likeliest accidental exit. Every
    log line it emits must be ids and counts.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    secret = "Dr Rao on 9876543210 handles the emergency line after 8pm."
    source_id = await _submit_and_approve(tenant_id, agent_id, "Escalation", secret)

    with caplog.at_level("DEBUG", logger="apps.api.kb.service"):
        await _publish(tenant_id, source_id)
        # And the failure paths, which are where detail usually leaks.
        v2 = await _submit_and_approve(tenant_id, agent_id, "Escalation", secret + " Updated.")
        engine = get_engine()

        async def _refuse(*args: Any, **kwargs: Any) -> None:
            raise ProblemError(
                kind="dependency", code="engine_rejected", title="No", detail="Refused."
            )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(engine, "detach_kb", _refuse)
            with pytest.raises(ProblemError):
                await _publish(tenant_id, v2)

    assert caplog.records, "premise: the publish path logs something"
    for record in caplog.records:
        rendered = record.getMessage() + repr(getattr(record, "__dict__", {}))
        assert "9876543210" not in rendered, f"a phone number reached {record.message!r}"
        assert "Dr Rao" not in rendered, f"a staff name reached {record.message!r}"
        assert "emergency line" not in rendered, f"KB content reached {record.message!r}"
