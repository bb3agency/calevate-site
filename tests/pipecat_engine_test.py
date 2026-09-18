"""`PipecatEngine` against the real database — the half the conformance suite cannot reach.

`packages/shared/tests/engine_conformance/` runs every clause of the port against this
adapter over an in-memory double, because that suite must be runnable with no database and
no worker. What it therefore CANNOT measure is the two things this adapter actually is:

* **the SQL control plane** — that a publish really mints a version and a runtime row, that
  a delete really removes one, that the knowledge objects really outlive the agent;
* **the WITNESS** — that `get_agent` answers from `agent_config_attestations` written by
  something else, and reports "nobody has confirmed this" when nothing has. The double
  plays a worker that always agrees, which is the right fixture for the other 50 clauses
  and is exactly the shape that cannot fail the one clause D-592 exists for.

So the clauses here are the ones whose subject is a second writer, plus the refusals whose
ground is a fact about the world rather than about a capability flag.

SHARED DATABASE DISCIPLINE: every case mints its own organisation and scopes every
assertion to its own ids. Nothing counts rows globally.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.config_versions import (
    latest_attestation,
    prompt_digest,
    record_attestation,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.capabilities import EngineCapabilityAbsentError
from apps.api.engine.pipecat import (
    PIPECAT_CAPABILITIES,
    PipecatEngine,
    engine_agent_ref_for,
)
from apps.api.kb import service as kb_service
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    HandoffSpec,
    KBSourceRef,
    ModelConfig,
    compose_engine_prompt,
)
from sqlalchemy import text
from tests.conftest import accept_agreements

OPENING = "Idi AI assistant. Ee call record avutundi."


async def _org() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Pipecat Adapter",
        slug=f"pipecat-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id, uuid.UUID(str(created["agent_id"]))


async def _make_the_agent_live(tenant_id: uuid.UUID, agent_id: uuid.UUID, ref: str) -> None:
    """The state a KB publish requires: a live agent with a script and a route.

    `create_organization` mints the receptionist with no `prompt_versions` row at all
    (FLOWS §1's step-3-before-step-7), and `publish_agent` refuses an agent with no script
    — so a fixture that only flipped `status` would report `agent_not_published` in place
    of the answer under test. Same fixture `kb_workflow_test.give_agent_a_script` builds
    for the fake engine; it is spelled here rather than imported because the ref and the
    route's engine name have to be this adapter's.
    """
    prompt_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, tenant_id, agent_id, version, body, "
                "created_at, updated_at) VALUES (:p, :t, :a, 1, :body, now(), now())"
            ),
            {
                "p": prompt_id,
                "t": tenant_id,
                "a": agent_id,
                "body": "You are the receptionist for Sunrise Clinic. Answer callers.",
            },
        )
        await session.execute(
            text(
                "UPDATE agents SET engine_agent_ref = :r, status = 'live', "
                "system_prompt_id = :p, live_prompt_id = :p WHERE id = :a"
            ),
            {"r": ref, "p": prompt_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) "
                "VALUES ('pipecat', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )


def _config(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    name: str = "Sunrise Clinic receptionist",
    system_prompt: str = "You are the receptionist for Sunrise Clinic.",
    handoff: HandoffSpec | None = None,
) -> AgentConfig:
    return AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        name=name,
        direction="inbound",
        language_primary="te-IN",
        system_prompt=system_prompt,
        opening_line=OPENING,
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="sarvam-105b",
            tts_provider="sarvam",
            tts_model="bulbul:v3",
            tts_voice="anushka",
        ),
        handoff=handoff,
    )


async def _attest_as_worker(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, cfg: AgentConfig, *, digest: str | None = None
) -> None:
    """Play the worker: recompute the prompt digest and write what it loaded.

    `digest` overrides it, which is the only way the disagreement branch is reachable — a
    worker that always recomputes correctly can never produce the finding the whole
    arrangement exists to catch.
    """
    async with tenant_session(tenant_id) as session:
        version = (
            await session.execute(
                text(
                    "SELECT id FROM agent_config_versions WHERE agent_id = :aid "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"aid": agent_id},
            )
        ).first()
        assert version is not None, "the publish minted no config version"
        await record_attestation(
            session,
            tenant_id,
            agent_id=agent_id,
            agent_config_version_id=version[0],
            prompt_sha256=digest if digest is not None else prompt_digest(cfg),
        )


# --- the witness (§1.1) --------------------------------------------------------


async def test_a_published_agent_no_worker_has_run_reads_back_as_unconfirmed() -> None:
    """ "NOBODY HAS ATTESTED" IS A REAL ANSWER, and the one a vendor read-back never had.

    An agent published and never dialled has no witness, so the compliance fields come back
    `None` with `_readable` False — which is the tri-state's own meaning ("the adapter could
    not FIND it") and makes `verification.judge` score the publish `unreadable` rather than
    applied. An adapter that answered from the config version it had just written would
    report `applied` here, agree with every caller for ever, and turn gate 2's property from
    false into unfalsifiable.
    """
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(tenant_id, agent_id)

    ref = await engine.create_agent(cfg)
    snapshot = await engine.get_agent(ref)

    assert snapshot.engine_agent_ref == ref
    assert snapshot.system_prompt_readable is False
    assert snapshot.system_prompt is None
    assert snapshot.greeting_readable is False
    assert snapshot.models_readable is False
    # The tri-state's derived readers must answer "cannot tell" rather than False — a
    # caller that collapsed them would record "the truthful-answer rule is absent" about an
    # agent nothing has looked at.
    assert snapshot.carries_prompt_marker(TRUTHFUL_ANSWER_MARKER) is None
    assert snapshot.carries_greeting_marker(OPENING) is None
    # The agent's NAME is ours to know without a witness and has no tri-state, so it is
    # reported: it carries no compliance claim.
    assert snapshot.name == cfg.name


async def test_the_read_back_is_what_the_worker_attested() -> None:
    """The witness agrees, so the content it confirmed is reportable — by content
    addressing rather than by assumption."""
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(tenant_id, agent_id, system_prompt="Receptionist. marker-alpha")

    ref = await engine.create_agent(cfg)
    await _attest_as_worker(tenant_id, agent_id, cfg)
    snapshot = await engine.get_agent(ref)

    assert snapshot.system_prompt_readable is True
    assert snapshot.carries_prompt_marker("marker-alpha") is True
    assert snapshot.carries_prompt_marker(TRUTHFUL_ANSWER_MARKER) is True
    assert snapshot.greeting_readable is True
    assert snapshot.carries_greeting_marker(OPENING) is True
    assert snapshot.models_readable is True
    assert snapshot.models is not None
    assert snapshot.models.tts_voice == "anushka"
    assert snapshot.models.stt_model == "saaras:v3"


async def test_a_worker_running_something_else_is_reported_as_unreadable() -> None:
    """THE CLAUSE THE WHOLE ARRANGEMENT EXISTS FOR (§1.1).

    The worker recomputed a digest that does not match the version it says it loaded — a
    stale deploy, a truncated prompt, a version published mid-session. We know it is running
    SOMETHING ELSE and we have no bytes that describe it, so the honest snapshot says the
    prompt could not be read, and the publish scores `unreadable` rather than applied.

    Reporting the version's own text here would be the defect in its purest form: an
    adapter claiming a process holds words it has just demonstrated it does not.
    """
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(tenant_id, agent_id)

    ref = await engine.create_agent(cfg)
    await _attest_as_worker(tenant_id, agent_id, cfg, digest="0" * 64)
    snapshot = await engine.get_agent(ref)

    assert snapshot.system_prompt_readable is False
    assert snapshot.system_prompt is None
    assert snapshot.models_readable is False
    async with tenant_session(tenant_id) as session:
        attestation = await latest_attestation(session, agent_id)
    assert attestation is not None
    assert attestation.matches is False, "the mismatch must survive as evidence in the row"


async def test_an_update_the_worker_has_not_picked_up_is_visible_as_a_disagreement() -> None:
    """A worker on the PREVIOUS version is the ordinary case of the same finding.

    It attested faithfully — its digest matches the version it loaded — so the read-back is
    readable and carries the OLD script, which is exactly what a caller needs to see: the
    update was accepted and is not yet applied. That distinction is the one thing a 2xx
    could never give us and the reason `get_agent` exists at all.
    """
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    first = _config(tenant_id, agent_id, system_prompt="Receptionist. marker-old")

    ref = await engine.create_agent(first)
    await _attest_as_worker(tenant_id, agent_id, first)
    await engine.update_agent(ref, _config(tenant_id, agent_id, system_prompt="marker-new"))

    snapshot = await engine.get_agent(ref)
    assert snapshot.carries_prompt_marker("marker-old") is True
    assert snapshot.carries_prompt_marker("marker-new") is False, (
        "the read-back reported the version the control plane published rather than the "
        "one the worker attested — the vendor read-back's defect, rebuilt without a vendor"
    )


# --- the SQL control plane -----------------------------------------------------


async def test_publishing_twice_mints_one_version_and_one_ref() -> None:
    """Content-addressed: republishing an unchanged agent writes no second version, and the
    ref is a pure function of the two ids rather than a value a round trip discovers."""
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(tenant_id, agent_id)

    first = await engine.create_agent(cfg)
    second = await engine.create_agent(cfg)
    assert first == second == engine_agent_ref_for(str(tenant_id), str(agent_id))

    async with tenant_session(tenant_id) as session:
        versions = (
            await session.execute(
                text("SELECT count(*) FROM agent_config_versions WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
        rows = (
            await session.execute(
                text("SELECT count(*) FROM pipecat_agents WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).scalar_one()
    assert versions == 1, "an unchanged republish minted a second version"
    assert rows == 1, "one agent must have one engine record"


async def test_a_version_carries_the_content_its_digests_are_taken_over() -> None:
    """A row that holds only hashes is a row the worker cannot LOAD (migration
    `e2f5a91c8d47`), which is what `PIPECAT-MIGRATION.md` §2 requires it to do."""
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(tenant_id, agent_id)
    await engine.create_agent(cfg)

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT composed_prompt, opening_line, prompt_sha256 "
                    "FROM agent_config_versions WHERE agent_id = :aid"
                ),
                {"aid": agent_id},
            )
        ).one()
    assert row[0] == compose_engine_prompt(cfg), "the stored prompt is not what was digested"
    assert row[1] == OPENING
    assert row[2] == prompt_digest(cfg)


async def test_deleting_an_agent_is_idempotent_and_keeps_its_knowledge_objects() -> None:
    """`delete_agent` is idempotent by contract, and the ACCOUNT's objects outlive it.

    The asymmetry is the harder answer on purpose: an object no agent references is exactly
    the residue every failure in the KB seam leaves, and a delete that tidied it away would
    make `list_account_kb` structurally incapable of reporting one.
    """
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(tenant_id, agent_id)
    ref = await engine.create_agent(cfg)
    handle = await engine.attach_kb(
        ref, KBSourceRef(kb_id=str(uuid.uuid4()), title="Fees", text="A consultation costs 500.")
    )

    await engine.delete_agent(ref)
    await engine.delete_agent(ref)  # absent is the post-condition already satisfied

    with pytest.raises(ProblemError) as raised:
        await engine.get_agent(ref)
    assert raised.value.code == "engine_rejected"

    listing = await engine.list_account_kb()
    assert handle in {obj.handle for obj in listing.objects}, (
        "the account's object went with its agent, so an orphan could never be reported"
    )
    assert listing.complete is True


async def test_the_account_listing_sees_an_object_no_agent_references() -> None:
    """`list_account_kb`'s whole job, against the real tables: it reads the OBJECT store,
    never the agent, so a detached-by-deletion object is still visible."""
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    ref = await engine.create_agent(_config(tenant_id, agent_id))
    kept = await engine.attach_kb(
        ref, KBSourceRef(kb_id=str(uuid.uuid4()), title="Parking", text="Parking is free.")
    )
    assert await engine.list_kb(ref) == [kept]

    await engine.delete_agent(ref)

    handles = {obj.handle for obj in (await engine.list_account_kb()).objects}
    assert kept in handles


async def test_a_detach_that_removed_nothing_raises() -> None:
    """The publisher's next act is to attach the replacement, and it is entitled to know
    the old text is gone — deliberately NOT `delete_agent`'s absent-is-success."""
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    ref = await engine.create_agent(_config(tenant_id, agent_id))

    with pytest.raises(ProblemError) as raised:
        await engine.detach_kb(ref, "pckb_never_issued")
    assert raised.value.code == "engine_rejected"


async def test_a_script_override_changes_the_words_and_keeps_the_name() -> None:
    """D-544 against the real store: the override mints a new version a worker can attest,
    and the field the same write could also have moved is untouched."""
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(tenant_id, agent_id)
    ref = await engine.create_agent(cfg)

    await engine.override_call_script(
        ref,
        opening_line="Calevate is down for planned maintenance until 02:30.",
        system_prompt="Say the maintenance sentence, then end the call politely.",
    )
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT composed_prompt, opening_line FROM agent_config_versions "
                    "WHERE agent_id = :aid ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"aid": agent_id},
            )
        ).one()
    assert "Say the maintenance sentence" in row[0]
    assert row[1] == "Calevate is down for planned maintenance until 02:30."
    # Still carries the floor: the override goes through the one composer, so a maintenance
    # script cannot be a way to publish an agent that will not say it is an AI.
    assert TRUTHFUL_ANSWER_MARKER in row[0]

    snapshot = await engine.get_agent(ref)
    assert snapshot.name == cfg.name, "the override moved a field it was not asked to move"


# --- refusals, by the refusal a caller actually gets ---------------------------


async def test_a_publish_carrying_a_handoff_is_refused_rather_than_dropped() -> None:
    """`in_call_handoff=False` while the carrier leg is unwritten (D-533).

    Refused, never dropped: an agent published with the tool silently missing is a client
    whose callers ask for a person and are told, plausibly, to wait.
    """
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(
        tenant_id,
        agent_id,
        handoff=HandoffSpec(
            destination_e164="+919000000042",
            trigger="Hand over when the caller asks for a person.",
            spoken_line="Putting you through now.",
        ),
    )

    with pytest.raises(EngineCapabilityAbsentError) as raised:
        await engine.create_agent(cfg)
    assert raised.value.capability == "in_call_handoff"
    assert raised.value.as_problem()["remediation"]


async def test_the_llm_credential_refusal_names_a_ground_the_old_gate_could_not() -> None:
    """§9.1's finding, as a test: `capabilities.is_ours("llm")` is TRUE here, so the gate
    every other adapter refuses through would have PASSED and the rotation would have
    reported success against a store that does not exist."""
    assert PIPECAT_CAPABILITIES.is_ours("llm") is True
    engine = PipecatEngine()

    with pytest.raises(ProblemError) as raised:
        await engine.set_llm_credential("ya29.rotated", provider="azure_openai")
    assert raised.value.code == "engine_capability_unverified"
    assert raised.value.remediation, "a key-holder was left with no next step"


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("end_call", ("call_1",)),
        ("list_engine_numbers", ()),
    ],
)
async def test_the_carrier_methods_refuse_with_the_ground_and_a_next_step(
    method: str, args: tuple[object, ...]
) -> None:
    """Every carrier refusal names the same unread evidence and points at the document that
    closes it — never `engine_capability_absent`, which would tell an operator to go and
    find a different platform."""
    engine = PipecatEngine()
    with pytest.raises(ProblemError) as raised:
        await getattr(engine, method)(*args)
    assert raised.value.code == "engine_capability_unverified"
    assert "pre-build-blockers" in (raised.value.remediation or "")


async def test_dialling_refuses_and_names_the_caller_id_first_when_one_was_given() -> None:
    """THE ORDER IS THE POINT (D-420). Both refusals are correct; they send an operator to
    two different places, and only one of them is about the number they just configured."""
    tenant_id, agent_id = await _org()
    engine = PipecatEngine()
    cfg = _config(tenant_id, agent_id)
    ref = await engine.create_agent(cfg)

    from calevate_shared.engine import CallContext

    with pytest.raises(EngineCapabilityAbsentError) as named:
        await engine.start_outbound_call(
            ref, "+919876543210", CallContext(from_e164="+911140000000")
        )
    assert named.value.capability == "caller_id"

    with pytest.raises(ProblemError) as generic:
        await engine.start_outbound_call(ref, "+919876543210", CallContext())
    assert generic.value.code == "engine_capability_unverified"


async def test_number_provisioning_refuses_every_series_by_name() -> None:
    """D-596: we do not buy numbers through an API at all, so this never flips — unlike the
    carrier refusals above, which flip when one document is read."""
    engine = PipecatEngine()
    assert PIPECAT_CAPABILITIES.number_series == frozenset()

    from calevate_shared.engine import NumberSearch, NumberSpec, ProvisionedNumber

    for call in (
        lambda: engine.search_numbers(NumberSearch()),
        lambda: engine.provision_number(NumberSpec(series="140")),
        lambda: engine.release_number(ProvisionedNumber(e164="+911400000001")),
    ):
        with pytest.raises(EngineCapabilityAbsentError) as raised:
            await call()
        assert raised.value.capability == "numbers"


async def test_an_empty_window_is_complete_and_a_populated_one_is_not() -> None:
    """§1.2 as a property: completeness here is about the CARRIER's record, not about pages.

    Nothing has dialled, so there is nothing whose CDR we needed and the window is honestly
    complete. The other direction — sessions we hold and cannot reconcile — is exercised by
    the conformance suite's saturated subject, which is the only place a session can exist
    before the worker does.
    """
    from datetime import UTC, datetime, timedelta

    engine = PipecatEngine()
    listing = await engine.list_executions(since=datetime.now(UTC) - timedelta(hours=1))
    assert listing.snapshots == []
    assert listing.complete is True
    assert listing.incomplete_reason is None

    with pytest.raises(ProblemError) as raised:
        await engine.get_execution("call_nobody_placed")
    assert raised.value.code == "engine_rejected"


# --- the caller's transaction (D-182's other half) -----------------------------


async def test_a_kb_publish_completes_while_the_caller_holds_the_agent_row_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE DEADLOCK, DRIVEN DOWN THE PATH THAT REACHES IT IN PRODUCTION.

    `kb/service.publish_source` → `agents.t0.recompile_t0` → `agents.service.publish_agent`
    → `PipecatEngine.update_agent` → `SqlControlPlane.publish`. `publish_agent` loads the
    `agents` row `FOR UPDATE` and is still holding it, in its own open transaction, when the
    adapter is called — and the two tables the adapter writes, `agent_config_versions` and
    `pipecat_agents`, both carry a foreign key to `agents` (migrations `d4e1c7a09b35` and
    `e2f5a91c8d47`). PostgreSQL validates a foreign key by taking `FOR KEY SHARE` on the
    referenced row, which conflicts with `FOR UPDATE`.

    So while the store opened its OWN session this call could not finish: the second
    transaction waited for a lock only the first could release, and the first was awaiting
    the second. It ended at `statement_timeout` — ten seconds of a held connection and a
    held lock, then a 500 — and no test saw it, because the default test engine is the fake
    and touches no database at all.

    WHAT THIS ASSERTS, beyond "it returned". Both halves of the fix are checked on the
    CALLER's session, before anything commits: the version row and the runtime row are
    visible to it, which is only possible if they were written INSIDE its transaction. A
    store that had opened its own connection could not have made them visible here even if
    it had somehow got the lock.

    The statement budget is dropped to its floor for the duration, so a regression fails in
    seconds rather than pinning a worker for ten. Reverting `SqlControlPlane` to its own
    sessions makes this test fail in 2.3s with the conflict named in full:
    `canceling statement due to statement timeout / CONTEXT: while locking tuple in
    relation "agents" / SQL statement: SELECT 1 FROM ONLY "public"."agents" x WHERE "id"
    = $1 FOR KEY SHARE OF x`, raised by the `agent_config_versions` INSERT (measured
    18 Sep 2026).
    """
    monkeypatch.setenv("ENGINE", "pipecat")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "1000")
    get_settings.cache_clear()
    reset_engine_cache()
    try:
        tenant_id, agent_id = await _org()
        cfg = _config(tenant_id, agent_id)
        ref = await PipecatEngine().create_agent(cfg)
        await _make_the_agent_live(tenant_id, agent_id, ref)

        async with tenant_session(tenant_id) as session:
            source = await kb_service.submit_source(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Clinic hours",
                body="We are open 9am to 8pm.\n\nSunday is closed.",
            )
            await kb_service.approve_source(session, source_id=source["id"], approved_by=None)

        async with tenant_session(tenant_id) as session:
            # The caller's lock, taken explicitly so this test keeps measuring the conflict
            # even if `publish_agent` ever stops taking its own (`_load_agent(for_update=
            # True)` takes the same one a few frames further in).
            locked = (
                await session.execute(
                    text("SELECT id FROM agents WHERE id = :aid FOR UPDATE"), {"aid": agent_id}
                )
            ).first()
            assert locked is not None

            version = await kb_service.publish_source(
                session, tenant_id=tenant_id, source_id=source["id"]
            )
            assert version == 1

            # Written in THIS transaction, and therefore visible to it uncommitted.
            versions = (
                await session.execute(
                    text("SELECT count(*) FROM agent_config_versions WHERE agent_id = :aid"),
                    {"aid": agent_id},
                )
            ).scalar()
            assert versions is not None and versions >= 1
            held = (
                await session.execute(
                    text("SELECT engine_agent_ref FROM pipecat_agents WHERE agent_id = :aid"),
                    {"aid": agent_id},
                )
            ).scalar()
            assert held == ref
    finally:
        get_settings.cache_clear()
        reset_engine_cache()
