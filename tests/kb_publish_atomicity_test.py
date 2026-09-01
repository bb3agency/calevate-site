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
   double-clicked Publish button or a retry after a timeout. Since the renderer seam was
   wired, the re-upload guard short-circuits this for UNCHANGED content — the two cases
   are now separate clauses below, because "the guard fired" and "the withdrawal fired"
   are different properties and a single test could pass while either one was broken.

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

import asyncio
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

    def install(self, patch: pytest.MonkeyPatch, *, mints_fresh_handles: bool = False) -> None:
        """`mints_fresh_handles` makes the fake behave like a CREATE-only engine.

        The fake files attachments under OUR `kb_id`, so re-attaching one source replaces
        it and hands back the same handle. A real knowledge base has no update route: every
        attach is a new object with a new id, and the copy it replaced stays until somebody
        deletes it. Filing under a distinct id per call reproduces that, which is the only
        way a clause about re-publishing the SAME source can see the second copy at all.
        """
        engine = get_engine()
        real_attach, real_detach = engine.attach_kb, engine.detach_kb

        async def attach(ref: EngineAgentRef, source: KBSourceRef, **kwargs: Any) -> EngineKBRef:
            if mints_fresh_handles:
                source = source.model_copy(update={"kb_id": f"{source.kb_id}#{len(self.calls)}"})
            handle = await real_attach(ref, source, **kwargs)
            self.calls.append(("attach", handle))
            return handle

        async def detach(ref: EngineAgentRef, kb: EngineKBRef, **kwargs: Any) -> None:
            self.calls.append(("detach", kb))
            await real_detach(ref, kb, **kwargs)

        patch.setattr(engine, "attach_kb", attach)
        patch.setattr(engine, "detach_kb", detach)

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]


# --------------------------------------------------------------------------------
# 1. Re-publishing a live version must not attach a second copy
# --------------------------------------------------------------------------------


async def test_republishing_unchanged_content_calls_the_vendor_not_at_all() -> None:
    """THE RE-UPLOAD GUARD, and it only started working when the renderer seam was wired.

    This clause used to assert `["attach", "detach"]` for this exact scenario, and it was
    right to at the time: `_render_document` resolved a renderer that did not exist, so
    the digest was `None`, so `unchanged` could never be true and EVERY republish uploaded
    a fresh copy and withdrew the old one. That is two vendor calls, a new billed object
    and an indexing wait, to end up exactly where we started.

    With the renderer wired the digest is real, and a republish of byte-identical content
    is now what the guard's own comment always claimed it was: nothing. Double-clicked
    Publish, a retry after a timeout, and FLOWS §7's rollback onto the version already
    live all cost zero vendor calls.

    `mints_fresh_handles=True` is kept deliberately. It makes the fake behave like a
    CREATE-only engine, so if the guard ever stops firing this test fails LOUDLY with a
    second copy rather than passing on the fake's de-duplication.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish_new_version(
        tenant_id, agent_id, "Fees", "A consultation costs 500 rupees."
    )
    first_handle = await _recorded_handle(tenant_id, source_id)
    assert first_handle

    spy = _Spy()
    with pytest.MonkeyPatch.context() as patch:
        spy.install(patch, mints_fresh_handles=True)
        await _publish(tenant_id, source_id)

    assert spy.kinds() == [], (
        "re-publishing byte-identical content reached the vendor — the re-upload guard "
        "is not firing, and on a CREATE-only engine every republish mints a billed copy"
    )
    ref = await _engine_ref(tenant_id, agent_id)
    assert len(await get_engine().list_kb(ref)) == 1
    assert await _recorded_handle(tenant_id, source_id) == first_handle


async def test_republishing_changed_content_withdraws_its_own_copy_after_attaching() -> None:
    """A publish leaves at most one copy of a source attached, and never two.

    The property this file was written for, moved onto the case that still reaches the
    vendor: the content actually changed, so the guard correctly does NOT skip, and the
    old copy must be withdrawn — on the real engine it is unaddressable and billed forever
    otherwise.

    **THE FAKE IS THE ONE ADAPTER THAT WOULD SURVIVE THIS BUG, so it is made to behave
    like the engine that would not.** It keys its store on OUR `kb_id`, so a second attach
    silently REPLACES the first and returns the same handle; `POST /knowledgebase` mints a
    new object every time and de-duplicates nothing, because there is no update route on
    that object.

    **THE ORDER IS `attach` THEN `detach` SINCE D-488, AND THIS USED TO ASSERT THE
    REVERSE.** What it protects is unchanged: exactly one copy afterwards, the OLD handle
    withdrawn, and the recorded handle equal to the one now attached. What changed is that
    the withdrawal happens second, because a real attach is an upload plus an indexing
    wait and detaching first would blank the agent for the whole of it.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish_new_version(
        tenant_id, agent_id, "Fees", "A consultation costs 500 rupees."
    )
    first_handle = await _recorded_handle(tenant_id, source_id)
    assert first_handle

    # The approved text moves under the same source row — a curation edit, not a new
    # version. This is what makes the render produce different bytes and therefore a
    # different digest, which is the ONLY thing that should send us back to the vendor.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE kb_documents SET content = :c, updated_at = now() "
                "WHERE source_id = :s AND idx = 0"
            ),
            {"c": "A consultation costs 750 rupees.", "s": source_id},
        )

    spy = _Spy()
    with pytest.MonkeyPatch.context() as patch:
        spy.install(patch, mints_fresh_handles=True)
        await _publish(tenant_id, source_id)

    assert spy.kinds() == ["attach", "detach"], (
        "re-publishing changed content did not withdraw the copy it replaced — "
        "on the real engine that copy is unaddressable and billed forever"
    )
    assert spy.calls[1][1] == first_handle, "the wrong handle was withdrawn"

    ref = await _engine_ref(tenant_id, agent_id)
    assert len(await get_engine().list_kb(ref)) == 1
    assert await _recorded_handle(tenant_id, source_id) == spy.calls[0][1]


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


# --------------------------------------------------------------------------------
# 4. Two publishers, one named source: exactly one version ends live
# --------------------------------------------------------------------------------


async def _live_versions(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str) -> list[int]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT version FROM kb_sources WHERE agent_id = :a AND name = :n "
                    "AND is_active = true ORDER BY version"
                ),
                {"a": agent_id, "n": name},
            )
        ).scalars()
        return [int(v) for v in rows]


async def test_two_publishers_of_one_named_source_leave_exactly_one_version_live() -> None:
    """The race `publish_source` could not detect, driven on two connections.

    The window needs no vendor weirdness and no failure. Two approved versions of ONE
    name with nothing live yet — an admin working an approval queue, two admins, a
    double-click on two rows — and both publishers read `is_active` before either
    COMMITs. Each sees no predecessor, so each withdraws nothing, attaches its own copy,
    and writes `is_active = true` on a row the other's `WHERE ... AND id <> :sid` never
    names. Under READ COMMITTED there is no conflict for Postgres to raise.

    What that leaves is precisely the divergence D-41's detach-then-attach ordering was
    built to prevent, arrived at from the other side: TWO live versions of one source,
    both attached to the engine, the agent free to answer from either, and both rows
    reported live on the client's screen. A client approved v2; the agent quoting v1's
    prices is the whole reason the approval gate exists.

    It only ever bit the FIRST publish of a name — with a live predecessor the second
    detach 404'd and `kb_detach_failed` refused the publish — which is the case a client
    hits exactly once per source and an operator hits on every onboarding.

    Both publishes SUCCEED here, and that is the correct outcome rather than a weaker
    one: publishing is not a compare-and-swap on "nothing is live", it is "make this the
    live one". Serialized, the second publisher sees the first's version as live,
    withdraws it and supersedes it. What must be true either way is the invariant
    `_superseded_versions` says it enforces — one live version, one engine copy.

    MEASURED WITH THE LOCK REMOVED, so the failure is recorded rather than predicted:
    the second publisher raised `kb_engine_out_of_sync`. Its `_reconcile_engine_state`
    saw the first publisher's copy already attached (the engine calls are outside the
    transaction) while the row recording that handle was still uncommitted, so the copy
    was unaccountable and the publish refused — a state whose remediation is "ask
    support to reconcile this agent". Two live versions is the same window read the
    other way, reached when the reconciliation runs before the other attach. Both are
    this assertion; neither is acceptable from two clicks on one queue.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    first = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 500.")
    second = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 900.")

    # Both callers inside `publish_source` before either reaches its first statement —
    # the same instrument, for the same reason, as the concurrent-approval twin.
    both_ready = asyncio.Barrier(2)

    async def publish(source_id: uuid.UUID) -> None:
        async with tenant_session(tenant_id) as session:
            await both_ready.wait()
            await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)

    await asyncio.gather(publish(first), publish(second))

    # ONE live version — not a particular one. The lock serializes; it does not order,
    # and it must not pretend to: two requests arriving together are decided by which
    # acquires second, exactly as any last-write-wins mutation is. Asserting `[2]` would
    # be asserting the scheduler. What a client is owed is that their agent answers from
    # one approved version, and that our tables and the engine name the same one.
    live = await _live_versions(tenant_id, agent_id, "Fees")
    assert len(live) == 1, f"{len(live)} versions of one source are live at once: {live}"

    attached = await get_engine().list_kb(await _engine_ref(tenant_id, agent_id))
    assert len(attached) == 1, (
        f"the engine holds {len(attached)} copies of one named source; the agent can "
        "answer from a version nobody published last"
    )
    async with tenant_session(tenant_id) as session:
        winner = (
            await session.execute(
                text(
                    "SELECT id FROM kb_sources WHERE agent_id = :a AND name = 'Fees' "
                    "AND is_active = true"
                ),
                {"a": agent_id},
            )
        ).scalar()
        recorded = await kb_service._engine_kb_ref(session, uuid.UUID(str(winner)))
    assert recorded == attached[0], (
        "the live version's recorded handle is not the copy the engine is holding"
    )


async def test_two_publishers_of_different_sources_on_one_agent_both_succeed() -> None:
    """The race the name-scoped lock did not cover, and why the lock is agent-wide.

    Different named sources supersede independently, so locking per `(agent, name)` is
    the tighter-looking choice. It leaves this window open: every publish ends in
    `recompile_t0`, and `prompt_versions` is numbered per AGENT under
    `UNIQUE (agent_id, version)`. Two publishes of different names both read
    `max(version)`, both insert `max + 1`, and the loser takes
    `prompt_version_conflict`.

    A 409 would be a defensible answer if it left the world unchanged. It does not: the
    rollback discards our `kb_documents` rows for a copy the engine has ALREADY been
    handed (`attach_kb` is not in the transaction), so the next publish for that agent
    finds a document it cannot account for and refuses with `kb_engine_out_of_sync`,
    whose remediation is "ask support". One operator publishing two FAQs at once must
    not need support afterwards.

    Both publishes complete, both sources end live, and the agent's prompt carries both
    sets of facts — which is also the assertion that the second recompile read the FIRST
    one's committed state rather than clobbering it.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    fees = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 500.")
    parking = await _submit_and_approve(tenant_id, agent_id, "Parking", "Parking is free.")

    both_ready = asyncio.Barrier(2)

    async def publish(source_id: uuid.UUID) -> None:
        async with tenant_session(tenant_id) as session:
            await both_ready.wait()
            await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)

    await asyncio.gather(publish(fees), publish(parking))

    assert await _live_versions(tenant_id, agent_id, "Fees") == [1]
    assert await _live_versions(tenant_id, agent_id, "Parking") == [1]
    assert len(await get_engine().list_kb(await _engine_ref(tenant_id, agent_id))) == 2

    async with tenant_session(tenant_id) as session:
        body = (
            await session.execute(
                text(
                    "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.system_prompt_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar()
    assert body is not None
    assert "costs 500" in body and "Parking is free" in body, (
        "the second recompile did not see the first publish's facts"
    )


# --------------------------------------------------------------------------------
# 4. The source deleted underneath a publish in flight (D-380)
# --------------------------------------------------------------------------------


async def test_a_source_deleted_mid_publish_is_refused_and_the_attach_is_undone() -> None:
    """The nightly retention sweep and FLOWS §7's rollback want the same rows.

    `workers/retention._KB_EXPIRE_SQL` DELETEs `is_active = false AND status IN
    ('archived','rejected')` versions past the tenant's `kb` TTL, from its own
    transaction, taking no part in `_lock_agent_publishes`. FLOWS §7's rollback is
    `publish_source` on an ARCHIVED row — the same population, and one that qualifies:
    `_KB_EXPIRABLE` excludes only versions still holding an `engine_kb_ref`. The
    interleaving below is that collision at its narrowest: the DELETE commits after this
    publish has read the row and after the engine has taken the attach.

    Before D-380 the activation UPDATE matched zero rows, nothing looked, and the function
    RETURNED THE VERSION NUMBER — a reported success for a publish that changed no row of
    ours while the vendor kept the document, unaddressable and unbillable. The assertions
    are the halves of the fix: the caller is told, the engine is put back the way it was
    found, and the version that really is live stays live.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    live = await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500.")
    doomed = await _submit_and_approve(tenant_id, agent_id, "Fees", "It costs 400.")

    engine = get_engine()
    engine_ref = await _engine_ref(tenant_id, agent_id)
    real_attach = engine.attach_kb

    async def attach_then_delete(
        ref: EngineAgentRef, source: KBSourceRef, **kwargs: Any
    ) -> EngineKBRef:
        """The vendor takes the document; the sweep's transaction commits a moment later.

        A separate session is what makes this the real race rather than a self-delete:
        under READ COMMITTED the publisher's next statement sees the committed DELETE.
        """
        handle = await real_attach(ref, source, **kwargs)
        async with tenant_session(tenant_id) as sweeper:
            await sweeper.execute(text("DELETE FROM kb_sources WHERE id = :sid"), {"sid": doomed})
        return handle

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(engine, "attach_kb", attach_then_delete)
        with pytest.raises(ProblemError) as raised:
            await _publish(tenant_id, doomed)
    assert raised.value.code == "kb_source_vanished"

    # The engine holds exactly what it held before: the version that was live, restored
    # by the same compensation a failed attach uses. No orphan, no second copy.
    attached = await engine.list_kb(engine_ref)
    assert len(attached) == 1, f"the engine was left holding {len(attached)} copies"
    assert await _recorded_handle(tenant_id, live) is not None
    assert await _live_versions(tenant_id, agent_id, "Fees") == [1]
