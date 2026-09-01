"""What the ENGINE holds after a publish, a rollback, and a half-failed publish.

`kb_workflow_test` pins the approval gate and our own rows. This file pins the other
half — the copy the caller actually hears. The two can disagree, and when they do it is
our tables that look right: a client approves v2, `kb_sources` says v2 is live, and the
agent goes on quoting v1's prices because archiving a row never told the engine
anything. FLOWS §7 calls the step "engine KB sync"; these tests are what makes the word
"sync" checkable.

The publish path detaches the superseded version BEFORE attaching its replacement, so
the interesting cases are the failures around that ordering: what a client is left with
when the engine refuses the detach, and what they are left with when it accepts the
detach and then refuses the attach.

Concurrency: every test builds its own tenant, agent and engine agent ref (the harness
in `kb_workflow_test` mints a run-unique one), so the engine state read here belongs to
this test alone even though the adapter instance is process-wide.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.kb import service as kb_service
from calevate_shared.engine import EngineAgentRef, EngineKBRef, KBSourceRef, VoiceEngine
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


def _attached(ref: str) -> list[KBSourceRef]:
    """What the engine would retrieve from, for this agent.

    Reading the fake adapter's own store is the point: it is the closest thing a test
    has to listening to the call. `list_kb` proves the COUNT adapter-independently
    (the conformance suite leans on it); the text is what tells us WHICH version
    survived, and only the fake can be asked that offline.
    """
    return list(getattr(get_engine(), "_kb", {}).get(ref, []))


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


# --------------------------------------------------------------------------------
# The happy path, read back from the engine
# --------------------------------------------------------------------------------


async def test_publishing_a_new_version_leaves_exactly_one_copy_on_the_engine() -> None:
    """The superseded text is GONE from the engine, not merely archived in our tables.

    Both halves matter. "v2 is attached" was always true; "v1 is not" is the property
    the approval gate depends on, because a retrieval hit on v1 is the client's agent
    quoting a price the client withdrew.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    ref = await _engine_ref(tenant_id, agent_id)
    attached = _attached(ref)
    assert len(attached) == 1, "the engine holds more than one version of one named source"
    assert "800 rupees" in attached[0].text
    assert "500 rupees" not in attached[0].text
    assert len(await get_engine().list_kb(ref)) == 1


async def test_the_superseded_version_is_withdrawn_before_the_new_one_is_pushed() -> None:
    """Ordering, asserted rather than assumed — **AND IT REVERSED IN D-488.**

    This clause used to assert `["detach", "attach"]` and its docstring argued for it:
    attach-first has a window in which both versions answer, detach-first trades it for a
    window with NO copy attached, and degrading to T4 ("I don't know") beats degrading to
    a wrong answer. **The trade was priced on an attach that was one call.** It is not one
    call on a real engine: it is a document upload plus an indexing wait the vendor
    publishes no bound for, so detach-first takes a client's knowledge away for MINUTES on
    every republish — every caller in that window told "I don't know" because somebody
    corrected a price.

    So the window moved rather than closed, and what this clause now pins is the shape of
    the window: an OVERLAP of one detach round trip, not a gap of an indexing wait. The
    "if the detach then fails the window never closes" objection is answered separately
    and by code rather than by ordering — `_undo_attach` removes what the publish added,
    and `test_a_failed_detach_refuses_the_publish_and_leaves_the_old_version_live` proves
    the engine is left holding exactly the previously approved version.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Hours", "Open 9am to 8pm.")

    engine = get_engine()
    calls: list[str] = []
    real_attach, real_detach = engine.attach_kb, engine.detach_kb

    async def _spy_attach(ref: EngineAgentRef, source: KBSourceRef, **kwargs: Any) -> EngineKBRef:
        calls.append("attach")
        return await real_attach(ref, source, **kwargs)

    async def _spy_detach(ref: EngineAgentRef, kb: EngineKBRef, **kwargs: Any) -> None:
        calls.append("detach")
        await real_detach(ref, kb, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(engine, "attach_kb", _spy_attach)
        patch.setattr(engine, "detach_kb", _spy_detach)
        await _publish_new_version(tenant_id, agent_id, "Hours", "Open 10am to 6pm.")

    assert calls == ["attach", "detach"], (
        "the agent was left with no copy of this source for the length of an upload"
    )


async def test_a_rollback_restores_exactly_one_version_on_the_engine() -> None:
    """FLOWS §7's recovery path, checked where it counts.

    Rollback exists for the moment a bad update is already telling callers the wrong
    thing, so "reactivate the prior version" has to mean the engine stops serving the
    bad one. Before the detach existed this path was the worst case in the system: every
    version ever published stayed attached, so rolling back ADDED the old text to the
    new instead of replacing it.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    v1 = await _publish_new_version(tenant_id, agent_id, "Prices", "An X-ray costs 400 rupees.")
    await _publish_new_version(tenant_id, agent_id, "Prices", "An X-ray costs 900 rupees.")

    await _publish(tenant_id, v1)

    ref = await _engine_ref(tenant_id, agent_id)
    attached = _attached(ref)
    assert len(attached) == 1, "a rollback left more than one version attached"
    assert "400 rupees" in attached[0].text
    assert "900 rupees" not in attached[0].text
    assert await _live_versions(tenant_id, agent_id, "Prices") == [1]


async def test_publishing_one_source_does_not_withdraw_the_others() -> None:
    """`name` is the unit of supersession, not the agent. An agent's KB is several named
    sources (hours, fees, parking); updating one must not silently unpublish the rest."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Parking", "Parking is free.")
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    ref = await _engine_ref(tenant_id, agent_id)
    texts = sorted(source.text for source in _attached(ref))
    assert len(texts) == 2, "publishing one named source disturbed another"
    assert any("Parking is free." in t for t in texts)
    assert any("800 rupees" in t for t in texts)


# --------------------------------------------------------------------------------
# When the engine will not cooperate
# --------------------------------------------------------------------------------


def _refuses(code: str, kind: Any = "dependency") -> Any:
    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise ProblemError(
            kind=kind, code=code, title="Voice engine said no", detail="The platform refused."
        )

    return _boom


async def test_a_failed_detach_refuses_the_publish_and_leaves_the_old_version_live() -> None:
    """The decision this file exists to pin down.

    Publishing over a version we could not withdraw is the original defect: two versions
    attached, the agent free to answer from either, every screen of ours reporting
    success. So the publish stops. What the client is left with is not "no knowledge
    base" — it is the version they previously approved, still answering, plus an error
    that says the update did not happen. The cost of that choice is a stale answer for
    as long as the engine is unwell; the cost of the alternative is a wrong answer the
    client is contractually held to.

    **WHAT CHANGED IN D-488 IS THE WORK THE REFUSAL HAS TO DO, NOT THE DECISION.** While
    the publish detached first, a refusal here cost nothing — nothing had been attached
    yet, so "try again" was free. Now the new copy is already up when the detach fails, so
    refusing means UNDOING it (`_undo_attach`) before raising. The assertions below are the
    same ones and they are stronger for it: exactly one version attached, and it is the
    one the client previously approved. An implementation that raised without compensating
    would leave two.

    `pytest.raises` sits OUTSIDE the session so the transaction unwinds the way it does
    in production — a half-applied publish committing would be its own bug.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    v2 = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    engine = get_engine()
    real_detach = engine.detach_kb
    refused: list[str] = []

    async def _refuses_the_withdrawal_only(
        ref: EngineAgentRef, kb: EngineKBRef, **kwargs: Any
    ) -> None:
        # THE FIRST DETACH ONLY, and the narrowness is the test rather than a convenience.
        # Under attach-first there are TWO detaches on this path: the withdrawal of the
        # superseded version, and `_undo_attach`'s removal of the copy this publish added.
        # Refusing both is a different scenario — the engine is refusing everything, the
        # agent ends up holding both versions, and
        # `test_an_attach_that_cannot_be_undone_leaves_a_loud_trail` is where that is
        # pinned. What THIS clause asserts is the ordinary case: the withdrawal fails, the
        # compensation works, and the client is left with exactly what they approved.
        if not refused:
            refused.append(kb)
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine said no",
                detail="The platform refused.",
            )
        await real_detach(ref, kb, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(engine, "detach_kb", _refuses_the_withdrawal_only)
        with pytest.raises(ProblemError) as raised:
            async with tenant_session(tenant_id) as session:
                await kb_service.publish_source(session, tenant_id=tenant_id, source_id=v2)

    assert raised.value.code == "kb_detach_failed"
    # The adapter's own `kind` survives, so a rate limit stays retryable and a rejection
    # does not — the caller's retry decision is the engine's answer, not our guess.
    assert raised.value.kind == "dependency"

    ref = await _engine_ref(tenant_id, agent_id)
    attached = _attached(ref)
    assert len(attached) == 1, "the refused publish still changed what the engine holds"
    assert "500 rupees" in attached[0].text, "the client was left without their knowledge base"
    assert await _live_versions(tenant_id, agent_id, "Fees") == [1], "our tables moved anyway"


async def test_a_failed_attach_leaves_the_previous_version_untouched() -> None:
    """The other side of the order, and D-488 turned it from a repair into an invariant.

    This clause used to be `test_a_failed_attach_puts_the_withdrawn_version_back`: under
    detach-first the agent knew nothing about this source between the two calls, so a
    failed attach there had to RE-ATTACH the previous version, and the test proved that
    restoration happened. Attach-first deletes the whole failure mode. Nothing has been
    withdrawn when the attach runs, so a refusal leaves the previously approved version
    exactly where it was — no compensation to write, and none to get wrong.

    That is the stronger property and it is asserted the same way: the engine holds one
    version, it is the old one, our tables did not move, and the publish is recoverable.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Hours", "Open 9am to 8pm daily.")
    v2 = await _submit_and_approve(tenant_id, agent_id, "Hours", "Open 10am to 6pm daily.")

    engine = get_engine()
    real_attach = engine.attach_kb

    async def _rejects_only_the_new_version(
        ref: EngineAgentRef, source: KBSourceRef, **kwargs: Any
    ) -> EngineKBRef:
        # The engine refusing ONE document — a parse failure, a size limit, a
        # multilingual-mode rejection.
        if source.kb_id == str(v2):
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine said no",
                detail="The platform refused this document.",
            )
        return await real_attach(ref, source, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(engine, "attach_kb", _rejects_only_the_new_version)
        with pytest.raises(ProblemError):
            async with tenant_session(tenant_id) as session:
                await kb_service.publish_source(session, tenant_id=tenant_id, source_id=v2)

    ref = await _engine_ref(tenant_id, agent_id)
    attached = _attached(ref)
    assert len(attached) == 1, "the engine was left holding the wrong number of versions"
    assert "9am to 8pm" in attached[0].text, (
        "the previously approved version was disturbed by a publish that never succeeded"
    )
    assert await _live_versions(tenant_id, agent_id, "Hours") == [1]

    # And the failure is recoverable rather than terminal: once the engine accepts
    # writes again, the same publish goes through.
    await _publish(tenant_id, v2)
    assert "10am to 6pm" in _attached(ref)[0].text
    assert await _live_versions(tenant_id, agent_id, "Hours") == [2]


async def test_an_attach_that_cannot_be_undone_leaves_a_loud_trail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The residual worst case, stated rather than hidden — **AND IT MOVED IN D-488.**

    Under detach-first the worst arrangement was "detach accepted, every attach refused",
    which left the agent with NO copy of this source and logged `kb_left_detached`. That
    arrangement no longer exists: nothing is withdrawn until the new copy is up, so an
    engine refusing every attach simply refuses the publish and changes nothing.

    The worst case is now its mirror. The attach SUCCEEDS, a detach then fails, and the
    compensating removal of the copy we just added fails too — so the agent is left
    holding both versions and can answer from either. Nothing in-process can fix it: the
    engine is refusing the very call the repair needs. What it must not do is end quietly,
    so `_undo_attach` logs `kb_left_attached` at ERROR with the source id (ids only —
    hard rule 6), which is what an operator gets paged on and what tells them which client
    to look at. `runbooks/kb-out-of-sync.md` names this origin and its repair.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    v2 = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    engine = get_engine()
    with (
        pytest.MonkeyPatch.context() as patch,
        caplog.at_level("ERROR", logger="apps.api.kb.service"),
    ):
        # Every detach refused: the superseded copy will not come down, and neither will
        # the compensating removal of the one just attached.
        patch.setattr(engine, "detach_kb", _refuses("engine_rejected"))
        with pytest.raises(ProblemError):
            async with tenant_session(tenant_id) as session:
                await kb_service.publish_source(session, tenant_id=tenant_id, source_id=v2)

    left_attached = [r for r in caplog.records if r.message == "kb_left_attached"]
    assert left_attached, "an agent was left answering from two versions and nobody was told"
    assert getattr(left_attached[-1], "source_id", None), "the alert does not name the source"
    # Our tables did not move, so the recovery is a re-publish once the engine is back —
    # not a hand-repair of rows.
    assert await _live_versions(tenant_id, agent_id, "Fees") == [1]


async def test_a_live_version_we_cannot_address_blocks_the_publish() -> None:
    """A version published before the engine handle was recorded.

    We cannot delete what we cannot name, and publishing over it would attach a second
    copy — so this refuses for exactly the same reason a failed detach does, and leaves
    the client with the same thing: their approved knowledge, still live. The remediation
    is one manual withdrawal on the engine side, not a code path that guesses.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish_new_version(tenant_id, agent_id, "Fees", "A consultation costs 500 rupees.")
    v2 = await _submit_and_approve(tenant_id, agent_id, "Fees", "A consultation costs 800 rupees.")

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE kb_documents SET meta = coalesce(meta, '{}'::jsonb) - 'engine_kb_ref' "
                "WHERE source_id IN (SELECT id FROM kb_sources WHERE agent_id = :a "
                "AND name = 'Fees' AND is_active = true)"
            ),
            {"a": agent_id},
        )

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await kb_service.publish_source(session, tenant_id=tenant_id, source_id=v2)

    assert raised.value.code == "kb_engine_ref_unknown"
    assert raised.value.remediation, "a refusal an operator cannot act on is a dead end"
    ref = await _engine_ref(tenant_id, agent_id)
    assert "500 rupees" in _attached(ref)[0].text
    assert await _live_versions(tenant_id, agent_id, "Fees") == [1]


# --------------------------------------------------------------------------------
# The contract itself
# --------------------------------------------------------------------------------


def test_the_engine_contract_can_express_a_withdrawal() -> None:
    """The protocol-level regression.

    The defect was not a bug in `apps/api/kb`; it was a contract with no way to say
    "remove this". Any future adapter is written against `VoiceEngine`, so if these
    methods fall off the Protocol the same divergence returns silently for the next
    engine — the conformance suite can only test clauses the contract names.
    """
    for method in ("attach_kb", "detach_kb", "list_kb"):
        assert hasattr(VoiceEngine, method), f"the contract lost `{method}`"
    assert isinstance(get_engine(), VoiceEngine)
