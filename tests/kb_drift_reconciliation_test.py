"""The periodic KB drift sweep: what the voice platform is HOLDING, between publishes.

`kb/service._reconcile_engine_state` reads the engine back and refuses to publish onto an
agent carrying a copy no row of ours mentions. It runs at PUBLISH TIME and nowhere else,
and a knowledge base is the object in this system with the longest gap between writes — a
client pastes a price list once and does not touch it for months. So the two divergences
that read exists for were, until this sweep, invisible for exactly that long:

    A VENDOR-DASHBOARD EDIT   a knowledge base added, replaced or DELETED in Bolna's own
                              console. Nothing of ours ran, so every table we own agrees
                              with itself and is wrong.
    A LOST-RESPONSE PUBLISH   the vendor took the attach and our COMMIT failed after it.
                              Our rows rolled back; the engine kept the document. The
                              divergence points the other way, and re-reading our own
                              tables can never find it — `publish_source` says so in its
                              own last paragraph.

**EVERY ASSERTION IS AGAINST WHAT THE SWEEP RECORDED AND WHAT THE ENGINE STILL HOLDS**,
never only against our own rows: the defect class here IS our database agreeing with
itself. `test_the_sweep_only_ever_reads` is not decoration either — the "obvious" repair
for a KB drift is `detach_kb`, an irreversible delete at the vendor of a document our
tables cannot describe, and the only way that argument survives a future refactor is a
test that fails when somebody helpfully adds one.

Run: uv run pytest -q tests/kb_drift_reconciliation_test.py
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from apps.api.kb import service as kb_service
from apps.api.kb.reconciliation import (
    KB_DRIFT_STATES,
    claim_kb_drift_batch,
    classify_kb_drift,
    read_kb_drift,
    record_kb_drift,
)
from apps.workers import kb_reconciliation
from apps.workers.kb_reconciliation import KB_SWEEP_INTERVAL_S, sweep_kb_drift
from apps.workers.settings import WorkerSettings
from arq import Retry
from calevate_shared.engine import EngineAgentRef, EngineKBRef, KBSourceRef
from sqlalchemy import text

FEES = "A consultation costs 500 rupees and is payable at reception."
HOURS = "The clinic is open from 9am to 8pm, Monday to Saturday."
DASHBOARD_PASTE = "Whatever somebody typed into the vendor's console at 3am."


# --- doubles -----------------------------------------------------------------


class RecordingEngine(FakeEngine):
    """`FakeEngine` that remembers which KB methods it was asked for, in order.

    The base class keeps what it HOLDS; what no other instrument can see is the SEQUENCE
    of calls, and "did the sweep write anything back?" is a question about the sequence.
    """

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.calls: list[tuple[str, str]] = []

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        handle = await super().attach_kb(ref, source)
        self.calls.append(("attach_kb", handle))
        return handle

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        self.calls.append(("detach_kb", kb))
        await super().detach_kb(ref, kb)

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        self.calls.append(("list_kb", ref))
        return await super().list_kb(ref)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class UnreachableOnListEngine(RecordingEngine):
    """Attaches and detaches normally; every listing fails. The `unreachable` verdict."""

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        self.calls.append(("list_kb", ref))
        raise ProblemError(
            kind="dependency",
            code="engine_unavailable",
            title="Voice engine unavailable",
            detail="The voice platform did not answer.",
        )


class LinkageBlindEngine(RecordingEngine):
    """Holds documents and reports NOBODY's — pilot gate 8's open question, as a double.

    `bolna.list_kb` reads `GET /knowledgebase/all` and keeps rows whose `agent_id` matches
    the ref. If the vendor's rows do not carry that field the filter matches nothing and
    every agent on the platform lists empty, while every document is still attached and
    still being read out on calls. This is that world, and the sweep must not report it as
    a fleet of agents that lost their knowledge.
    """

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        self.calls.append(("list_kb", ref))
        await super(RecordingEngine, self).list_kb(ref)  # capability check still applies
        return []


@contextmanager
def _engine(instance: FakeEngine) -> Iterator[FakeEngine]:
    """Run the block against `instance`, restoring the cache afterwards. Reaches into
    `apps.api.engine`'s instance cache because that is what `get_engine()` resolves
    through — the shape `engine_drift_reconciliation_test._engine` established."""
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


@contextmanager
def _batch_size(size: int) -> Iterator[None]:
    previous = kb_reconciliation.KB_SWEEP_BATCH_SIZE
    kb_reconciliation.KB_SWEEP_BATCH_SIZE = size
    try:
        yield
    finally:
        kb_reconciliation.KB_SWEEP_BATCH_SIZE = previous


# --- fixtures ----------------------------------------------------------------


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, body: str) -> uuid.UUID:
    """Submit, approve and publish one named source. The whole FLOWS §7 gate."""
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name=name, body=body
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
    source_id = uuid.UUID(str(submitted["id"]))
    async with tenant_session(tenant_id) as session:
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    return source_id


async def _agent_ref(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar()
        )


def _scoped(cls: type[FakeEngine] = RecordingEngine, **kw: Any) -> FakeEngine:
    """An adapter with a NAME NOBODY ELSE USES, which is how this suite stays isolated.

    THE SHARED DATABASE IS THE PROBLEM AND `active` IS NOT THE ANSWER. Nothing truncates
    between test files, so by the time this module runs there are routing rows from every
    other suite that has ever published an agent, and the sweep is deliberately GLOBAL.
    `engine_drift_reconciliation_test` narrows its scope by flipping `active` false on
    every other row in the table — which works when it is the only suite running and is
    hostile when it is not: it deactivates rows another test session is relying on, and
    another session's inserts land inside its own window. Both directions are real; the
    failures are intermittent and land on whoever is unlucky.

    Scoping by ENGINE NAME needs no write at all. `claim_kb_drift_batch`, `read_kb_drift`
    and `record_kb_drift` all filter on `engine`, `get_engine()` keys its instance cache on
    the CONFIGURED name (so an instance registered under "fake" still reports whatever name
    it was built with), and `engine_agent_routes` puts no CHECK on the column. So each test
    gets a private universe of routes that no other suite can see or disturb, and this file
    mutates nothing it did not create.
    """
    return cls(name=f"fake-kb-{uuid.uuid4().hex[:10]}", **kw)


async def _agent_with_knowledge(
    engine: FakeEngine, *sources: tuple[str, str]
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A tenant with a live agent holding `sources`, routed under `engine.name`."""
    created = await admin_service.create_organization(
        name="KB Drift Clinic",
        slug=f"kbd-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_kbd_{uuid.uuid4().hex[:8]}"
    # `engine_agent_ref` ONLY — deliberately not `status = 'live'`, which the other KB
    # suites set. `publish_source` ends in `recompile_t0`, and that re-publishes a LIVE
    # agent through `agents.service.publish_agent`, which writes
    # `agents.engine = get_engine().name` into a column whose CHECK admits exactly the
    # three selectable engines — so a per-test engine name could not survive it. Nothing
    # under test here notices: the sweep's scope is `engine_agent_routes.active`, which is
    # set truthfully below, `agents.status` appears in none of its queries, and the T0
    # recompile it skips is `t0_recompile_test`'s subject rather than this file's. The
    # publish path itself is exercised in full, which is what this suite needs from it —
    # the handles it records are the thing the sweep reads back.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) "
                "VALUES (:e, :r, :t, :a, true, now(), now())"
            ),
            {"e": engine.name, "r": ref, "t": tenant_id, "a": agent_id},
        )
    with _engine(engine):
        for name, body in sources:
            await _publish(tenant_id, agent_id, name, body)
    return tenant_id, agent_id, ref


async def _route(
    engine: FakeEngine, ref: str
) -> tuple[str | None, datetime | None, datetime | None]:
    """(kb_drift_state, kb_drift_checked_at, kb_drift_detected_at) for one vendor object."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT kb_drift_state, kb_drift_checked_at, kb_drift_detected_at "
                    "FROM engine_agent_routes WHERE engine = :e AND engine_agent_ref = :r"
                ),
                {"e": engine.name, "r": ref},
            )
        ).first()
    assert row is not None, "the fixture did not write a routing row"
    return row[0], row[1], row[2]


# --- 1. the schema and the code agree on the vocabulary ----------------------


async def test_the_stored_verdicts_are_exactly_the_ones_the_check_constraint_allows() -> None:
    """A verdict the application can produce and the database rejects is a sweep that
    starts failing every write at 00:23 with nothing on any screen to explain it. Compared
    against the LIVE constraint rather than against the migration's source, so a hand-
    applied schema cannot pass this by agreeing with a file nobody ran."""
    async with untenanted_session() as session:
        clause = (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_engine_agent_routes_kb_drift_state'"
                )
            )
        ).scalar_one()
    in_constraint = {word.strip("'") for word in str(clause).split("'") if word.strip("', ()")}
    assert in_constraint >= KB_DRIFT_STATES, (
        "the application can produce a verdict the database will reject: "
        + str(sorted(KB_DRIFT_STATES - in_constraint))
    )


# --- 2. the classifier, as a pure decision ------------------------------------


def test_the_classifier_names_both_directions_and_refuses_to_guess() -> None:
    """The whole verdict, without a database or a vendor. Each row is a different thing
    for an operator to do, which is why they are different words."""
    assert (
        classify_kb_drift(
            attached={"a", "b"}, recorded={"a", "b"}, listing_attributes_by_agent=True
        )
        == "in_sync"
    )
    assert (
        classify_kb_drift(attached={"a", "x"}, recorded={"a"}, listing_attributes_by_agent=True)
        == "unaccounted"
    ), "a document the engine holds that no row of ours names is the dangerous direction"
    assert (
        classify_kb_drift(attached={"a"}, recorded={"a", "b"}, listing_attributes_by_agent=True)
        == "missing"
    ), "a handle we recorded that the engine does not list is knowledge the client lost"
    assert (
        classify_kb_drift(attached={"x"}, recorded={"a"}, listing_attributes_by_agent=True)
        == "divergent"
    ), "both directions at once must not be reported as only the one an operator fixes"
    assert (
        classify_kb_drift(attached=None, recorded={"a"}, listing_attributes_by_agent=True)
        == "unreachable"
    )
    # Nothing expected and nothing held is not a claim about anything.
    assert (
        classify_kb_drift(attached=set(), recorded=set(), listing_attributes_by_agent=False)
        == "in_sync"
    )


def test_an_empty_listing_is_only_evidence_once_the_linkage_is_proven() -> None:
    """PILOT GATE 8, AS A BRANCH. `bolna.list_kb` filters `GET /knowledgebase/all` on a
    field whose existence is a hand-maintained claim; if it is absent, EVERY agent lists
    empty while every document is still attached and still being read out.

    Reporting that as `missing` is a fleet-wide false alarm arriving on a schedule — the
    exact failure the `unreadable`/evidence split exists to prevent. So the same two sets
    give two different verdicts depending on whether anything in the tick proved the
    vendor attributes its listing by agent.
    """
    assert (
        classify_kb_drift(attached=set(), recorded={"a"}, listing_attributes_by_agent=False)
        == "unreadable"
    ), "an empty listing with no positive control was reported as proven evidence"
    assert (
        classify_kb_drift(attached=set(), recorded={"a"}, listing_attributes_by_agent=True)
        == "missing"
    ), "a proven-attributing listing that returned nothing IS evidence and was discarded"


# --- 3. the divergences only a sweep can see ----------------------------------


async def test_the_sweep_finds_knowledge_added_in_the_vendors_dashboard() -> None:
    """DRIFT ONE, the dangerous direction. Somebody pastes a knowledge base into Bolna's
    own console: no gate, no approval, no row of ours — and the agent will read it aloud
    to callers under the client's own PE registration."""
    engine = _scoped()
    tenant_id, agent_id, ref = await _agent_with_knowledge(engine, ("Fees", FEES))

    with _engine(engine):
        # Clean first, so a green verdict is proved reachable and the red one below is not
        # simply "this sweep always says something is wrong".
        assert await sweep_kb_drift({}) == "checked=1 drifted=0"
        clean_state, clean_checked, clean_detected = await _route(engine, ref)
        assert clean_state == "in_sync"
        assert clean_checked is not None
        assert clean_detected is None, "an in-sync agent was stamped as drifted"

        # The dashboard edit. Straight into the engine's store — no code of ours runs,
        # which is the entire point.
        engine._kb[ref] = [
            *engine._kb.get(ref, []),
            KBSourceRef(kb_id="pasted-by-hand", title="Offers", text=DASHBOARD_PASTE),
        ]
        assert await sweep_kb_drift({}) == "checked=1 drifted=1"

    state, checked_at, detected_at = await _route(engine, ref)
    assert state == "unaccounted"
    assert checked_at is not None
    assert detected_at is not None, "a drift with no start date cannot be aged by an operator"
    # THE READ PROPERTY: the vendor's document is still standing.
    assert any(s.kb_id == "pasted-by-hand" for s in engine._kb[ref])
    # And our own tables are untouched and self-consistent — the reason nothing but a read
    # of THEIRS could have found this.
    async with tenant_session(tenant_id) as session:
        recorded = await kb_service.recorded_handles_of_agent(session, agent_id)
    assert len(recorded) == 1


async def test_the_sweep_finds_knowledge_deleted_in_the_vendors_dashboard() -> None:
    """DRIFT TWO. The other direction: the client's agent now knows LESS than was
    approved, so it refuses-and-escalates where it should quote a price.

    TWO sources, and only one deleted, deliberately. A non-empty listing is what proves
    the vendor attributes its rows by agent, which is what makes the absence of the other
    one evidence rather than "we could not tell" — see
    `test_an_empty_listing_is_only_evidence_once_the_linkage_is_proven`.
    """
    engine = _scoped()
    _, _, ref = await _agent_with_knowledge(engine, ("Fees", FEES), ("Hours", HOURS))

    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=1 drifted=0"
        # Deleted at the vendor. Our rows still record its handle.
        engine._kb[ref] = [s for s in engine._kb[ref] if s.title != "Hours"]
        assert await sweep_kb_drift({}) == "checked=1 drifted=1"

    state, _, detected_at = await _route(engine, ref)
    assert state == "missing"
    assert detected_at is not None


async def test_the_sweep_finds_a_publish_that_landed_after_our_side_failed() -> None:
    """DRIFT THREE, and the one no re-reading of our own tables can ever find.

    The engine took the attach and our COMMIT failed after it, so every row rolled back
    while the document stayed attached. `publish_source`'s own last paragraph says this is
    undetectable from our side — "a COMMIT that fails after a successful attach leaves the
    engine holding a document none of our rows mention" — and this is the read that finds
    it without waiting for the next publish to trip over it.
    """
    engine = _scoped()
    tenant_id, agent_id, ref = await _agent_with_knowledge(engine)

    with _engine(engine):
        async with tenant_session(tenant_id) as session:
            submitted = await kb_service.submit_source(
                session, tenant_id=tenant_id, agent_id=agent_id, name="Fees", body=FEES
            )
            await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        source_id = uuid.UUID(str(submitted["id"]))

        # The publish succeeds AT THE VENDOR and the transaction never commits.
        with pytest.raises(RuntimeError):
            async with tenant_session(tenant_id) as session:
                await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
                raise RuntimeError("the connection dropped before COMMIT")

        # OUR OWN TABLES ARE CONSISTENT AND WRONG: no handle, nothing live, no trace.
        async with tenant_session(tenant_id) as session:
            recorded = await kb_service.recorded_handles_of_agent(session, agent_id)
        assert recorded == set(), (
            "the rolled-back publish left a handle behind, so this test is measuring "
            "something other than the lost-response divergence"
        )
        assert engine._kb.get(ref), "premise: the vendor kept the document"

        assert await sweep_kb_drift({}) == "checked=1 drifted=1"

    assert (await _route(engine, ref))[0] == "unaccounted"


async def test_the_sweep_only_ever_reads() -> None:
    """D-121's argument, held as a property rather than a comment, and it bites harder
    here than on the agent sweep.

    The repair a KB drift superficially invites is `detach_kb` — an irreversible DELETE at
    the vendor of a document our tables, by hypothesis, cannot describe. Doing that
    unattended, platform-wide, on a schedule, would destroy the only copy of text somebody
    added by hand, plausibly during an incident. So the sweep may call `list_kb` and
    nothing else, and this fails the day somebody adds a helpful tidy-up.
    """
    engine = _scoped()
    _, _, ref = await _agent_with_knowledge(engine, ("Fees", FEES))
    engine._kb[ref] = [
        *engine._kb[ref],
        KBSourceRef(kb_id="pasted-by-hand", title="Offers", text=DASHBOARD_PASTE),
    ]
    engine.calls.clear()

    with _engine(engine):
        await sweep_kb_drift({})

    assert engine.names() == ["list_kb"], (
        "the sweep did more than read: " + str(engine.names()) + ". Reconciliation "
        "reports; a detach is an irreversible delete at the vendor and belongs to a human."
    )
    assert any(s.kb_id == "pasted-by-hand" for s in engine._kb[ref])


async def test_a_linkage_blind_vendor_is_undetermined_and_never_an_alarm() -> None:
    """PILOT GATE 8, END TO END. The vendor holds every document and attributes none of
    them, so every listing is empty. The sweep must report "we could not tell" for the
    whole platform rather than "every client lost their knowledge" — an alarm of that
    size, arriving hourly, is an alarm somebody mutes in a week, and it would be muted
    over the one tick that later carries a real dashboard edit."""
    engine = _scoped(LinkageBlindEngine)
    _, _, ref_a = await _agent_with_knowledge(engine, ("Fees", FEES))
    _, _, ref_b = await _agent_with_knowledge(engine, ("Hours", HOURS))

    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=2 drifted=0", (
            "a vendor whose listing carries no agent linkage was reported as a fleet of "
            "agents that lost their knowledge"
        )

    for ref in (ref_a, ref_b):
        state, checked_at, detected_at = await _route(engine, ref)
        assert state == "unreadable"
        assert checked_at is not None, "an attempt that decided nothing was not recorded"
        assert detected_at is None, "an undetermined read was filed as a proven drift"

    # And it is VISIBLE rather than silent: the ops summary counts it as undetermined,
    # which is the number that says "go and look at the vendor", not "go and look at the
    # clients".
    async with untenanted_session() as session:
        summary = await read_kb_drift(session, engine=engine.name)
    assert summary.undetermined == 2 and summary.out_of_sync == 0


async def test_an_agent_that_should_hold_nothing_and_holds_nothing_is_in_sync() -> None:
    """The empty/empty case is not a claim about the vendor's linkage at all, so it must
    not be swept into `unreadable` — a platform of agents with no knowledge yet would
    otherwise report as permanently undetermined and drown the number that matters."""
    engine = _scoped(LinkageBlindEngine)
    _, _, ref = await _agent_with_knowledge(engine)
    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=1 drifted=0"
    assert (await _route(engine, ref))[0] == "in_sync"


# --- 4. isolation (hard rule 1) ------------------------------------------------


async def test_one_tenants_knowledge_never_accounts_for_anothers() -> None:
    """THE CROSS-TENANT ZERO-ROWS PROPERTY, on the read this sweep is built out of.

    The sweep asks "which handles do we believe are attached" per candidate, and it must
    ask under THAT tenant's session. Two failures live here and both are silent:

    * reading UNTENANTED — `kb_sources`/`kb_documents` are FORCE-RLS'd, so the answer is
      zero rows for every agent and every document on the platform reads `unaccounted`.
      An alarm that fires on all of them is one nobody can act on;
    * reading the WRONG tenant's rows — tenant B's handles accounting for tenant A's
      engine copies, which would mask a real divergence rather than invent one.

    Driven rather than asserted: two tenants, each with knowledge, swept in one tick.
    """
    engine = _scoped()
    tenant_a, agent_a, ref_a = await _agent_with_knowledge(engine, ("Fees", FEES))
    tenant_b, agent_b, ref_b = await _agent_with_knowledge(engine, ("Hours", HOURS))
    assert tenant_a != tenant_b

    async with tenant_session(tenant_a) as session:
        handles_a = await kb_service.recorded_handles_of_agent(session, agent_a)
        # The neighbour's agent, asked for on A's session: RLS makes its rows invisible,
        # so the honest answer is the empty set — never B's handles.
        leaked = await kb_service.recorded_handles_of_agent(session, agent_b)
    assert handles_a and not leaked, "one tenant's session can read another's KB handles"

    # An untenanted read is what the sweep must NOT do, and here is what it would cost.
    async with untenanted_session() as session:
        assert await kb_service.recorded_handles_of_agent(session, agent_a) == set()

    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=2 drifted=0", (
            "the sweep read our handles from the wrong session: with RLS returning zero "
            "rows every published document on the platform reads as unaccounted"
        )
    assert (await _route(engine, ref_a))[0] == "in_sync"
    assert (await _route(engine, ref_b))[0] == "in_sync"


# --- 5. the concurrency the publish path guarantees ---------------------------


async def test_an_agent_mid_publish_is_skipped_rather_than_reported_as_drifted() -> None:
    """`publish_source` DETACHES BEFORE IT ATTACHES (D-41), so every publish contains a
    stretch in which the engine holds fewer documents than our rows record. That is not a
    rare race — it is a false verdict this sweep would produce on demand, every time a
    client updated a price list.

    The publisher holds `pg_advisory_xact_lock(kb:publish:<agent>)` across exactly that
    stretch, so the sweep takes the same lock with `pg_try_advisory_xact_lock` and steps
    over an agent it cannot get. Driven with a real held lock on a second connection
    rather than by patching, because the property under test is that the two callers agree
    on the KEY — which a patched-out lock could not show.
    """
    engine = _scoped()
    tenant_id, agent_id, ref = await _agent_with_knowledge(engine, ("Fees", FEES))
    engine.calls.clear()

    async with tenant_session(tenant_id) as holder:
        # Exactly what `_lock_agent_publishes` takes, through the shared key helper.
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": kb_service.publish_lock_key(agent_id)},
        )
        with _engine(engine):
            assert await sweep_kb_drift({}) == "checked=0 drifted=0"

    assert engine.names() == [], "the sweep spent a vendor round trip on an agent mid-publish"
    assert (await _route(engine, ref))[0] is None, (
        "an agent the sweep deliberately stepped over was stamped as checked, so it drops "
        "to the back of the staleness queue without anyone having looked at it"
    )

    # And the next tick, with the lock released, does the work that was deferred.
    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=1 drifted=0"


async def test_handles_moving_under_the_listing_is_a_skip_and_not_a_verdict() -> None:
    """The other half of the bracket. A publish that begins AND commits between the two
    reads never holds the lock when either one asks for it, so the only thing that can
    catch it is the reads disagreeing — and they do, because `attach_kb` mints a handle."""
    engine = _scoped()
    tenant_id, agent_id, ref = await _agent_with_knowledge(engine, ("Fees", FEES))

    real_list = kb_reconciliation.engine_list_kb
    published: list[str] = []

    async def publish_mid_listing(candidate: Any) -> list[str]:
        result = await real_list(candidate)
        # A whole publish lands while the listing is in the air.
        if not published:
            published.append("Hours")
            with _engine(engine):
                await _publish(tenant_id, agent_id, "Hours", HOURS)
        return result

    kb_reconciliation.engine_list_kb = publish_mid_listing  # type: ignore[assignment]
    try:
        with _engine(engine):
            assert await sweep_kb_drift({}) == "checked=0 drifted=0"
    finally:
        kb_reconciliation.engine_list_kb = real_list  # type: ignore[assignment]

    assert (await _route(engine, ref))[0] is None, (
        "a listing taken before a publish was scored against rows taken after it — the "
        "sweep reported a routine knowledge update as a divergence"
    )
    # The next tick, with nothing in flight, agrees with the engine.
    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=1 drifted=0"
    assert (await _route(engine, ref))[0] == "in_sync"


# --- 6. the bounds -------------------------------------------------------------


async def test_the_batch_is_bounded_and_ordered_by_staleness() -> None:
    """One vendor round trip per agent per tick is the whole bill — and on Bolna that trip
    pulls the WHOLE ACCOUNT's knowledge list, so the cap matters more here than on the
    agent sweep. The ORDERING is what makes a cap fair instead of starving: a never-checked
    agent outranks every checked one, and among checked ones, oldest first."""
    engine = _scoped()
    refs = [(await _agent_with_knowledge(engine, ("Fees", FEES)))[2] for _ in range(3)]
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        for ref, age_h in ((refs[0], 1), (refs[1], 9)):
            await session.execute(
                text(
                    "UPDATE engine_agent_routes SET kb_drift_state = 'in_sync', "
                    "kb_drift_checked_at = :t WHERE engine_agent_ref = :r"
                ),
                {"t": now - timedelta(hours=age_h), "r": ref},
            )

    async with untenanted_session() as session:
        batch = await claim_kb_drift_batch(session, engine=engine.name, limit=2)
    assert [c.engine_agent_ref for c in batch] == [refs[2], refs[1]], (
        "the batch is not stalest-first: a never-checked agent must outrank a stale one, "
        "and without that ordering the cap starves whatever sorts last forever"
    )

    engine.calls.clear()
    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=3 drifted=0"
    assert engine.names().count("list_kb") == 3


async def test_the_two_sweeps_do_not_share_a_staleness_queue() -> None:
    """`drift_checked_at` is the AGENT sweep's queue position and `kb_drift_checked_at` is
    this one's. Sharing one column would make each sweep push the other's unread rows out
    of reach — the reason `a7c31e05b8d4` added three columns instead of reusing three."""
    engine = _scoped()
    _, _, ref = await _agent_with_knowledge(engine, ("Fees", FEES))
    with _engine(engine):
        await sweep_kb_drift({})

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT drift_state, drift_checked_at, kb_drift_state, kb_drift_checked_at "
                    "FROM engine_agent_routes WHERE engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).one()
    assert row[2] == "in_sync" and row[3] is not None, "the KB sweep recorded nothing"
    assert row[0] is None and row[1] is None, (
        "the KB sweep wrote the AGENT sweep's columns: the agent queue has been reordered "
        "by a job that never looked at a single prompt"
    )


async def test_a_full_batch_leaves_the_rest_first_in_line_rather_than_unread() -> None:
    """The bound must not become a blind spot. Agents a capped tick did not reach keep
    their old `kb_drift_checked_at`, so the NEXT tick takes them first — which is why the
    sweep needs no cursor and cannot lose its place when a tick dies halfway."""
    engine = _scoped()
    refs = [(await _agent_with_knowledge(engine, ("Fees", FEES)))[2] for _ in range(3)]

    with _engine(engine), _batch_size(1):
        assert await sweep_kb_drift({}) == "checked=1 drifted=0"
        first = {ref for ref in refs if (await _route(engine, ref))[0] is not None}
        assert len(first) == 1

        assert await sweep_kb_drift({}) == "checked=1 drifted=0"
        second = {ref for ref in refs if (await _route(engine, ref))[0] is not None}
    assert len(second) == 2 and first < second, (
        "the second tick re-read what the first already did — the cap is a cap on COVERAGE "
        "rather than on cost, and the tail is never reached"
    )


async def test_a_tick_that_runs_out_of_budget_stops_rather_than_overrunning() -> None:
    """The batch cap bounds the COUNT and this bounds the TIME; they are different
    failures. Running out of budget must not be treated as one — the agents it did not
    reach keep their old `kb_drift_checked_at` and are first next time."""
    engine = _scoped()
    refs = [(await _agent_with_knowledge(engine, ("Fees", FEES)))[2] for _ in range(3)]
    engine.calls.clear()

    previous = kb_reconciliation.KB_SWEEP_BUDGET_S
    kb_reconciliation.KB_SWEEP_BUDGET_S = 0.0
    try:
        with _engine(engine):
            assert await sweep_kb_drift({}) == "checked=0 drifted=0"
    finally:
        kb_reconciliation.KB_SWEEP_BUDGET_S = previous

    assert engine.names() == [], "the budget was exhausted and the sweep dialled anyway"
    for ref in refs:
        assert (await _route(engine, ref))[0] is None
    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=3 drifted=0"


def test_the_tick_cannot_outlive_its_own_interval() -> None:
    """The sweep skips the Redis lease `campaign_dispatch` needs, and the whole licence for
    that is an arithmetic relationship between its budget and its schedule. An assumption
    that has stopped being true must fail at import, not at 00:23."""
    assert kb_reconciliation.KB_SWEEP_BUDGET_S + 60.0 < KB_SWEEP_INTERVAL_S
    kb_reconciliation._assert_the_tick_fits_its_interval()

    previous = kb_reconciliation.KB_SWEEP_BUDGET_S
    kb_reconciliation.KB_SWEEP_BUDGET_S = float(KB_SWEEP_INTERVAL_S)
    try:
        with pytest.raises(AssertionError, match="overlap"):
            kb_reconciliation._assert_the_tick_fits_its_interval()
    finally:
        kb_reconciliation.KB_SWEEP_BUDGET_S = previous


async def test_an_engine_without_a_knowledge_base_costs_no_round_trip() -> None:
    """`publish_source` refuses on the same capability, so on such an engine there are no
    attachments to have drifted. Asking anyway would record `unreachable` for every live
    agent — a permanently red console describing a capability the platform never had."""
    engine = _scoped()
    _, _, ref = await _agent_with_knowledge(engine, ("Fees", FEES))

    blind = _scoped(capabilities=DICTATED_SPEECH_CAPABILITIES)
    assert not blind.capabilities.has("knowledge_base"), "premise: this engine has no KB"
    with _engine(blind):
        assert await sweep_kb_drift({}) == "checked=0 drifted=0"
    assert blind.names() == []
    assert (await _route(engine, ref))[0] is None, (
        "an engine with no knowledge base stamped a verdict about knowledge"
    )


async def test_a_platform_with_nothing_live_costs_no_vendor_round_trip() -> None:
    """The empty batch is a real branch: on a fresh deployment, and on any tick where every
    live agent was checked seconds ago, this is the whole tick."""
    engine = _scoped()
    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=0 drifted=0"
    assert engine.names() == []


# --- 7. failure handling -------------------------------------------------------


async def test_an_unreachable_engine_is_recorded_and_does_not_raise_the_alarm() -> None:
    """One sick agent must not fail the tick for the other fourteen, and must not fire the
    alarm either: `unreachable` is not evidence of a drift, and an alert that treats it as
    one is an alert nobody reads by the second week."""
    engine = _scoped(UnreachableOnListEngine)
    _, _, ref = await _agent_with_knowledge(engine, ("Fees", FEES))
    engine.calls.clear()

    with _engine(engine):
        assert await sweep_kb_drift({}) == "checked=1 drifted=0"
    state, checked_at, detected_at = await _route(engine, ref)
    assert state == "unreachable"
    assert checked_at is not None, "an attempt that failed was not recorded as an attempt"
    assert detected_at is None, "a vendor we could not reach was filed as a proven drift"


async def test_a_sweep_that_cannot_run_at_all_climbs_a_ladder_and_then_shouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arq 0.28 retries a job for `arq.Retry` and for NOTHING else, so a sweep that fails
    on its batch read must raise `Retry` explicitly, or every client's published
    knowledge is unwatched until the next hour with nothing marked wrong. The defer
    climbs with the attempt.

    **THE LAST ATTEMPT IS DIFFERENT, AND THIS TEST USED TO ASSERT OTHERWISE** (P6.5). It
    drove `job_try=3` and expected a third `Retry` — but `WORKER_MAX_TRIES` is 3, so that
    IS the last attempt, and arq does not honour a `Retry` on it: the job finishes with
    `JobExecutionFailed` and a `logger.warning` nothing reads. The docstring promised
    "three attempts, then the DLQ", and there is no DLQ — an exhausted arq job is
    `zrem`'d off the queue and written to a result key nothing in this repository reads.
    So the alert on the final attempt IS the dead-letter mechanism, and the test that
    pinned the old shape was pinning the silence.

    Distinct from a VENDOR failure, which is recorded as `unreachable` for that one agent
    and does not escalate.
    """
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        kb_reconciliation,
        "alert",
        lambda stage, code, **kw: fired.append((stage, code)),
    )
    original = kb_reconciliation.claim_kb_drift_batch

    async def broken_claim(session: Any, **kw: Any) -> Any:
        raise RuntimeError("the database went away")

    kb_reconciliation.claim_kb_drift_batch = broken_claim  # type: ignore[assignment]
    try:
        with _engine(_scoped()):
            with pytest.raises(Retry) as first:
                await sweep_kb_drift({"job_try": 1})
            with pytest.raises(Retry) as second:
                await sweep_kb_drift({"job_try": 2})
            # NOT a Retry: the ladder is spent, so the job raises the original error and
            # the alert is what carries the incident out of the worker.
            with pytest.raises(RuntimeError, match="the database went away"):
                await sweep_kb_drift({"job_try": WORKER_MAX_TRIES})
    finally:
        kb_reconciliation.claim_kb_drift_batch = original  # type: ignore[assignment]

    assert first.value.defer_score is not None and second.value.defer_score is not None
    assert second.value.defer_score > first.value.defer_score, (
        "the retry ladder is flat, so three sweeps hit a restarting database in ninety "
        "seconds instead of backing off"
    )
    assert fired == [("WORKER_TERMINAL", "kb_drift_sweep_abandoned")], (
        "the exhausted sweep finished in silence — there is no DLQ to land in, so an "
        "alert on the last attempt is the only thing that tells anybody"
    )


async def test_a_route_deleted_mid_sweep_records_nothing_and_is_not_counted() -> None:
    """A sweep works from a snapshot, so the object can be unpublished between the batch
    read and the record. `record_kb_drift` returns False on zero rows, and that must be a
    non-outcome rather than a verdict: a `checked` count that included objects we never
    recorded would report coverage the console cannot corroborate."""
    engine = _scoped()
    _, _, ref = await _agent_with_knowledge(engine, ("Fees", FEES))
    engine.calls.clear()

    original = kb_reconciliation.claim_kb_drift_batch

    async def deleting_claim(session: Any, **kw: Any) -> Any:
        batch = await original(session, **kw)
        async with untenanted_session() as other:
            await other.execute(
                text("DELETE FROM engine_agent_routes WHERE engine_agent_ref = :r"), {"r": ref}
            )
        return batch

    kb_reconciliation.claim_kb_drift_batch = deleting_claim  # type: ignore[assignment]
    try:
        with _engine(engine):
            assert await sweep_kb_drift({}) == "checked=0 drifted=0"
    finally:
        kb_reconciliation.claim_kb_drift_batch = original  # type: ignore[assignment]
    # The read still happened — the vendor was asked — and nothing was written.
    assert engine.names().count("list_kb") == 1


# --- 8. what an operator can see -----------------------------------------------


async def test_a_drift_that_persists_keeps_the_detection_time_it_was_first_given() -> None:
    """AGE is the number that separates a publish that raced a sweep from a dashboard edit
    nobody has noticed for a month, so re-stamping `kb_drift_detected_at` every tick would
    make an operator triaging by age deprioritise the worst one."""
    engine = _scoped()
    _, _, ref = await _agent_with_knowledge(engine, ("Fees", FEES))
    engine._kb[ref] = [
        *engine._kb[ref],
        KBSourceRef(kb_id="pasted-by-hand", title="Offers", text=DASHBOARD_PASTE),
    ]

    with _engine(engine):
        await sweep_kb_drift({})
        first = (await _route(engine, ref))[2]
        await sweep_kb_drift({})
        second = (await _route(engine, ref))[2]
    assert first is not None and first == second, "the drift clock was reset by re-observing it"

    # And it CLEARS the moment the agent reads back in sync, so a drift somebody fixed
    # stops being counted without anyone having to acknowledge it.
    async with untenanted_session() as session:
        await record_kb_drift(session, engine=engine.name, ref=ref, state="in_sync")
    assert (await _route(engine, ref))[2] is None


async def test_the_ops_summary_counts_drift_undetermined_and_unswept_separately() -> None:
    """A job that writes a state nobody reads is the half-wired-feature defect, so the
    sweep's output has to reach the screen that already carries the DLQ depth — and it has
    to arrive as separate numbers, not one.

    `undetermined` is held out of `out_of_sync` for the reason `verification.py` separates
    them at the source, and it carries more weight here: an empty listing is ambiguous
    between "the documents are gone" and "the vendor does not attribute its listing"
    (pilot gate 8, open), so folding them would report an open vendor question as a fleet
    of clients whose knowledge vanished.
    """
    engine = _scoped()
    drifted_ref = (await _agent_with_knowledge(engine, ("Fees", FEES)))[2]
    clean_ref = (await _agent_with_knowledge(engine, ("Fees", FEES)))[2]
    unread_ref = (await _agent_with_knowledge(engine, ("Fees", FEES)))[2]
    never_ref = (await _agent_with_knowledge(engine, ("Fees", FEES)))[2]

    async with untenanted_session() as session:
        for ref, state in (
            (drifted_ref, "unaccounted"),
            (clean_ref, "in_sync"),
            (unread_ref, "unreadable"),
        ):
            await record_kb_drift(session, engine=engine.name, ref=ref, state=state)

    assert (await _route(engine, never_ref))[0] is None, "premise: one agent was never swept"

    async with untenanted_session() as session:
        summary = await read_kb_drift(session, engine=engine.name)

    assert summary.live_agents == 4
    assert summary.out_of_sync == 1, "the one provably wrong agent is the alarm"
    assert summary.undetermined == 1, "an unreadable listing was counted as a drifted agent"
    assert summary.in_sync == 1
    assert summary.never_checked == 1, "an agent nobody swept was counted as one we liked"
    assert (
        summary.live_agents
        == summary.out_of_sync + summary.undetermined + summary.in_sync + summary.never_checked
    ), "the parts do not sum to the total, so the panel contradicts itself"
    assert summary.oldest_drift_at is not None
    assert summary.oldest_checked_at is not None


async def test_the_verdict_reaches_the_ops_platform_read() -> None:
    """The seam that stops this being a column nobody reads. Asserted through the response
    MODEL the route builds, so a field added to the summary and forgotten on the payload
    fails here rather than in a browser."""
    from apps.api.ops.routes import _platform_out

    engine = _scoped()
    _, _, ref = await _agent_with_knowledge(engine, ("Fees", FEES))
    engine._kb[ref] = [
        *engine._kb[ref],
        KBSourceRef(kb_id="pasted-by-hand", title="Offers", text=DASHBOARD_PASTE),
    ]
    with _engine(engine):
        await sweep_kb_drift({})
        async with untenanted_session() as session:
            payload = await _platform_out(session, load_shed_mode="normal")

    assert payload.kb_drift.live_agents == 1
    assert payload.kb_drift.out_of_sync == 1
    assert payload.kb_drift.oldest_drift_at is not None
    assert payload.kb_drift.oldest_checked_at is not None, (
        "the panel has no pulse: if the cron dies every count freezes and `out_of_sync: 0` "
        "reads as all-clear forever"
    )
    # The two measurements stay separate — an agent whose PROMPT is in sync can still be
    # answering from a knowledge base nobody approved.
    assert payload.engine_drift.never_checked == 1


# --- 9. registration -----------------------------------------------------------


def test_the_sweep_is_on_a_real_worker_schedule_with_an_explicit_max_tries() -> None:
    """Verified against `arq.worker.Worker`, not against `WorkerSettings`.

    `cron()` defaults `max_tries` to 1 and `WorkerSettings.max_tries` does NOT reach a
    function carrying its own, so a sweep that gave up on its first Redis blip would leave
    every client's published knowledge unwatched with the console still green. The
    assertion is made on the schedule a real Worker builds, where the effective value is
    whatever the job will actually run with.
    """
    from arq.worker import Worker

    worker = Worker(
        functions=WorkerSettings.functions,
        cron_jobs=WorkerSettings.cron_jobs,
        redis_settings=WorkerSettings.redis_settings,
        max_tries=WorkerSettings.max_tries,
        burst=True,
        ctx={},
    )
    jobs = {job.name: job for job in worker.cron_jobs}
    assert "cron:sweep_kb_drift" in jobs, "the KB drift sweep must be registered"
    job = jobs["cron:sweep_kb_drift"]
    # The negative control in the same breath: a cron that does NOT pass max_tries comes
    # back as 1 even though `WorkerSettings.max_tries` is 3.
    assert jobs["cron:dispatch_outbox"].max_tries == 1
    assert job.max_tries is not None and job.max_tries > 1, (
        "cron() defaults max_tries to 1; a sweep that gives up on its first failure leaves "
        "every client's published knowledge unwatched with every screen still green"
    )
    assert job.minute == set(kb_reconciliation.KB_SWEEP_MINUTES)
    # It must not land on the AGENT sweep's minutes: two account-wide vendor listings in
    # the same second is the rate-limit incident the bounds exist to avoid.
    assert not job.minute & {7, 37}, "the two drift sweeps were scheduled on top of each other"
