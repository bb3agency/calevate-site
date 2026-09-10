"""An agent that cannot say it is an AI stops ANSWERING, not only dialling (D-564).

THE SEAM THIS FILE CLOSES. D-562 made the half-hourly drift sweep's
`truthful_answer_missing` verdict a dial refusal: an agent proven to be running a prompt
with no truthful-answer directive in it may not place a call. The inbound half was left
open, and inbound is the half where the caller did not choose to be in the conversation —
the agent went on picking up its number and telling anyone who asked whether they were
talking to a machine whatever the vendor's own console was last used to write.

WHAT IS ASSERTED HERE, and the middle two are the ones that fail silently:

    1. A PROVEN-MISSING directive takes the agent's NUMBERS AWAY, so nothing answers.
       Not a neutral message: the one instrument that could speak is the prompt that has
       just been proven not to hold our words, and it is not read back
       (`reconcile_inbound_truthful_answer` argues this at length).
    2. THIRTEEN REPUBLISH PATHS DO NOT UNDO IT. A voice change, a cap change or a prompt
       rollback rebinds the numbers as its last act, and a publish whose read-back proved
       NOTHING must put them straight back down.
    3. A WALLET DOES NOT END IT, in either direction. A top-up restores a credit silence
       and must leave a compliance one exactly where it is.
    4. A PUBLISH THAT *PROVES* THE DIRECTIVE ENDS IT, because that is the remedy the
       client is told to perform, and because the read-back is real evidence.
    5. THE LAUNCH GATE SAYS SO BEFORE a campaign is launched into a wall of refusals.

Every verdict here comes from an engine that was actually READ — `TruncatingEngine` cuts
the floor off what the vendor ANSWERS, which is the one instrument in this suite able to
reproduce a prompt-length truncation or a console edit — never from a row a test wrote.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.agents.publishing import engine_drift_for
from apps.api.agents.reconciliation import TRUTHFUL_ANSWER_MISSING
from apps.api.billing.service import record_entry
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.service import TRUTHFUL_ANSWER_DRIFT_RULE
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import DEFAULT_FAKE_CAPABILITIES, FakeEngine
from apps.workers.engine_reconciliation import sweep_engine_drift
from calevate_shared.engine import AgentSnapshot, EngineAgentRef, ProvisionedNumber
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.truthful_answer_enforcement_test import TruncatingEngine, _engine, _only

SCRIPT = "Sunrise Clinic receptionist. Greet in Telugu, then take the appointment."


class UnreadableEngine(FakeEngine):
    """An engine that ANSWERS with no prompt at all.

    The publish read-back then proves nothing — `verification.judge` scores the
    truthful-answer property `None`, the publish is recorded `unreadable` and is NOT
    refused (only `not_applied` refuses). That is the case property 2 turns on: thirteen
    console actions republish an agent, and on an engine like this every one of them
    reaches the end of `publish_agent` having confirmed nothing at all.
    """

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        return snapshot.model_copy(update={"system_prompt": None})


async def _clinic(engine: FakeEngine, *, credit: str = "500") -> tuple[UUID, UUID, str, str]:
    """A tenant with one INBOUND agent live on `engine`, answering one number.

    FUNDED by default, and that is not padding: a fresh prepaid organisation starts at a
    zero wallet, which is itself a reason to silence inbound (D-551). A fixture that left
    it there would let a test about the compliance mechanism pass on the credit one.

    Returns the tenant, the agent, the vendor's handle for the agent and the vendor's
    handle for the number — the pair `FakeEngine.inbound_agent_for` joins, which is how
    every assertion below reads "does this number ring anything" off the ENGINE rather
    than off a column of ours.
    """
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Silence Clinic",
        slug=f"sil-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    number_ref = f"num-{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        if credit != "0":
            await record_entry(session, tenant_id=tenant_id, delta=Decimal(credit), reason="topup")
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=SCRIPT,
            notes=None,
            created_by=None,
        )
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"),
            {"a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                "dlt_status, engine_number_ref, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, '160', 'registered', :ref, now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "e": f"+9116{uuid.uuid4().int % 10**8:08d}",
                "ref": number_ref,
            },
        )
    with _engine(engine):
        async with tenant_session(tenant_id) as session:
            ref = await agents_service.publish_agent(
                session, tenant_id=tenant_id, agent_id=agent_id
            )
    return tenant_id, agent_id, ref, number_ref


async def _reconcile(
    engine: FakeEngine, tenant_id: UUID, agent_id: UUID, ref: str
) -> tuple[str, str | None]:
    """THE WORKER EDGE, driven exactly as `workers/engine_reconciliation._reconcile_one`
    will drive it: the drift read the sweep already has in hand, handed straight to the
    reconciler. Nothing here invents the verdict.

    Returns the outcome word and, beside it, the field the reconciler acted on — so a
    test that passes cannot be passing on a measurement that was never taken.
    """
    with _engine(engine):
        drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref)
        async with tenant_session(tenant_id) as session:
            outcome = await agents_service.reconcile_inbound_truthful_answer(
                session,
                engine,
                tenant_id=tenant_id,
                agent_id=agent_id,
                truthful_answer_applied=drift.truthful_answer_applied,
            )
    return outcome, drift.state


async def _silence(tenant_id: UUID, agent_id: UUID) -> tuple[datetime | None, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT inbound_silenced_at, inbound_silence_reason FROM agents WHERE id = :a"
                ),
                {"a": agent_id},
            )
        ).one()
    return row[0], row[1]


# --- 1. the vocabulary is the database's, not a comment -------------------------------


async def test_the_reason_vocabulary_is_exactly_what_the_check_constraint_allows() -> None:
    """The reasons the code can write and the reasons the table will accept are one set.

    A migration spells its own literals (`f4a2c7e19d63` says why), so the only thing
    holding the two together is this assertion — the shape
    `engine_drift_reconciliation_test` uses for `drift_state`. A third reason added to the
    constant without a migration would fail a CHECK at 03:00 on a live agent instead.
    """
    async with untenanted_session() as session:
        clause = (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_agents_inbound_silence_reason'"
                )
            )
        ).scalar()
    assert clause is not None, "the CHECK is not on the table"
    for reason in agents_service.INBOUND_SILENCE_REASONS:
        assert f"'{reason}'" in clause, f"the database will not accept {reason!r}"
    assert clause.count("::text") - clause.count("inbound_silence_reason") <= len(
        agents_service.INBOUND_SILENCE_REASONS
    ), f"the constraint allows a value the code has no name for: {clause}"


async def test_a_stamp_without_a_reason_is_refused_by_the_database() -> None:
    """The equivalence, asserted against the engine of record.

    A silence with no reason is one nothing can correctly end — every reader below
    branches on the reason — and it is the state a half-written UPDATE would produce.
    """
    engine = FakeEngine()
    tenant_id, agent_id, _ref, _num = await _clinic(engine)
    async with tenant_session(tenant_id) as session:
        try:
            await session.execute(
                text("UPDATE agents SET inbound_silenced_at = now() WHERE id = :a"),
                {"a": agent_id},
            )
            await session.flush()
        except Exception as exc:
            assert "ck_agents_inbound_silence_reason" in str(exc)
        else:  # pragma: no cover - the assertion below is the failure message
            raise AssertionError("the database accepted a silence with no reason")


# --- 2. the silencing itself ----------------------------------------------------------


async def test_a_proven_missing_directive_takes_the_agents_numbers_away() -> None:
    """THE HEADLINE. The sweep proves the floor is gone; the number stops ringing.

    Driven end to end: the real sweep records the real verdict off a real read-back, and
    the reconciler acts on the same drift the sweep held. Asserted against the ENGINE —
    "which agent would this number reach" — because a column saying `silenced` over a
    number that still rings is the exact lie this whole mechanism exists to prevent.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    assert engine.inbound_agent_for(number_ref) == ref, "the fixture never answered"

    engine.truncating = True
    await _only(ref)
    with _engine(engine):
        await sweep_engine_drift({"job_try": 1})
    async with untenanted_session() as session:
        verdict = (
            await session.execute(
                text("SELECT drift_state FROM engine_agent_routes WHERE engine_agent_ref = :r"),
                {"r": ref},
            )
        ).scalar()
    assert verdict == TRUTHFUL_ANSWER_MISSING, "the sweep did not record the compliance verdict"

    # THE SWEEP ITSELF TOOK THE NUMBER AWAY, and this used to be asserted of a manual
    # `_reconcile` call because the worker edge was not wired yet (D-564 landed the
    # reconciler and left `engine_reconciliation._reconcile_one` to a later change). The
    # assertion moved UP rather than being relaxed: what protects a caller is that the
    # half-hourly tick does this unattended, not that a function does it when called.
    assert engine.inbound_agent_for(number_ref) is None, (
        "the number still rings an agent that has been PROVEN unable to tell a caller it "
        "is an AI — hard rule 5's floor, on a live inbound call"
    )

    # And the reconciler is idempotent over the sweep's own work: a second pass costs no
    # vendor round trip and must not report a change it did not make.
    outcome, state = await _reconcile(engine, tenant_id, agent_id, ref)
    assert (outcome, state) == ("unchanged", "not_applied")
    silenced_at, reason = await _silence(tenant_id, agent_id)
    assert silenced_at is not None
    assert reason == agents_service.INBOUND_SILENCE_TRUTHFUL_ANSWER


async def test_it_is_idempotent_and_costs_no_second_round_trip() -> None:
    """The mirror is what makes this callable from every edge. A second pass over an
    already-silenced agent must not spend a vendor call to discover there is nothing to do.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"
    before = engine.inbound_agent_for(number_ref)
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "unchanged"
    assert engine.inbound_agent_for(number_ref) == before


async def test_a_read_back_that_could_not_tell_leaves_the_phone_alone() -> None:
    """ "We could not tell" is not evidence of a missing directive.

    The `AgentSnapshot` doctrine held to the end of the line: a phone that goes dead
    because a vendor was briefly slow is how an enforcement gets disarmed.
    """
    engine = UnreadableEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    outcome, _state = await _reconcile(engine, tenant_id, agent_id, ref)
    assert outcome == "indeterminate"
    assert engine.inbound_agent_for(number_ref) == ref
    assert (await _silence(tenant_id, agent_id)) == (None, None)


# --- 3. the republish preservation ----------------------------------------------------


async def test_a_republish_that_proves_nothing_leaves_the_agent_silent() -> None:
    """THE SUBTLE HALF. Thirteen call sites republish an agent for reasons that have
    nothing to do with compliance, and each one rebinds its numbers as its last act.

    Here the read-back proves NOTHING (`UnreadableEngine`), so the publish has no evidence
    that the fault is fixed — and the numbers must go straight back down. Without this,
    an unrelated voice change quietly puts a non-compliant agent back on the phone, with
    our own column still claiming it is silent, which is the failure that looks handled.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"
    assert engine.inbound_agent_for(number_ref) is None

    blind = UnreadableEngine()
    blind._agents = engine._agents
    blind._inbound = engine._inbound
    with _engine(blind):
        async with tenant_session(tenant_id) as session:
            await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert blind.inbound_agent_for(number_ref) is None, (
        "a republish that proved nothing gave a proven-non-compliant agent its phone back"
    )
    _at, reason = await _silence(tenant_id, agent_id)
    assert reason == agents_service.INBOUND_SILENCE_TRUTHFUL_ANSWER


async def test_a_republish_that_proves_the_directive_gives_the_phone_back() -> None:
    """The remedy the client is actually told to perform
    (`TRUTHFUL_ANSWER_DRIFT_REASON`: "Publishing the agent again restores the rule").

    A publish read-back that scored the truthful-answer property TRUE is evidence in our
    own hand that the fault is gone, and a silence that outlived it would leave a client
    who did exactly what we asked with a dead line and no next action.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"

    engine.truncating = False
    with _engine(engine):
        async with tenant_session(tenant_id) as session:
            await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert engine.inbound_agent_for(number_ref) == ref
    assert (await _silence(tenant_id, agent_id)) == (None, None)


async def test_the_sweep_itself_gives_the_phone_back_without_republishing() -> None:
    """The recovery path that does NOT need a human: the console edit is undone at the
    vendor, the next sweep reads the directive back, and the numbers are returned.

    It restores through the numbers rather than through `publish_agent` deliberately —
    D-121 refuses to let a scheduled sweep overwrite whatever the vendor console holds.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"
    engine.truncating = False
    outcome, state = await _reconcile(engine, tenant_id, agent_id, ref)
    assert (outcome, state) == ("restored", "applied")
    assert engine.inbound_agent_for(number_ref) == ref
    assert (await _silence(tenant_id, agent_id)) == (None, None)


async def test_a_restore_into_an_empty_wallet_lands_on_the_credit_stop_script() -> None:
    """Ending a compliance silence is not a reward. An agent that was silent on the way in
    and belongs to a client with no calling credit is landed on the credit-stop script,
    not handed a fully working phone — that is PRESERVING a silence rather than starting
    one, which is the line `_settle_inbound_silence` draws.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine, credit="0")
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"
    engine.truncating = False
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "restored"

    assert engine.inbound_agent_for(number_ref) == ref, "the number never came back"
    assert (await _silence(tenant_id, agent_id))[1] == agents_service.INBOUND_SILENCE_CREDITS
    with _engine(engine):
        snapshot = await engine.get_agent(ref)
    assert agents_service.CREDIT_STOP_MESSAGE in str(snapshot.greeting)


# --- 4. the wallet may not decide a compliance question -------------------------------


async def test_a_top_up_does_not_end_a_compliance_silence() -> None:
    """`reconcile_inbound_answering` is the WALLET's reconciler, and a paid bill is not
    evidence about a prompt. Restoring here would put a caller in front of an agent proven
    unable to tell them it is a machine, decided by a money question that knows nothing
    about it.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"

    with _engine(engine):
        async with tenant_session(tenant_id) as session:
            outcome = await agents_service.reconcile_inbound_answering(
                session, engine, tenant_id=tenant_id, exhausted=False
            )
    assert outcome.withheld == 1 and outcome.restored == 0
    assert engine.inbound_agent_for(number_ref) is None
    assert (await _silence(tenant_id, agent_id))[1] == TRUTHFUL_ANSWER_MISSING


async def test_an_emptying_wallet_does_not_overwrite_a_compliance_silence() -> None:
    """The other direction, and it is not symmetry for its own sake: overriding the script
    of an agent whose numbers are already unbound spends a vendor round trip to change
    what a caller who cannot reach it would have heard, and would rewrite the reason to
    one whose remedy — a top-up — does not fix the fault.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"

    with _engine(engine):
        async with tenant_session(tenant_id) as session:
            outcome = await agents_service.reconcile_inbound_answering(
                session, engine, tenant_id=tenant_id, exhausted=True
            )
    assert outcome.withheld == 1 and outcome.silenced == 0
    assert engine.inbound_agent_for(number_ref) is None
    assert (await _silence(tenant_id, agent_id))[1] == TRUTHFUL_ANSWER_MISSING


# --- 5. the launch gate ---------------------------------------------------------------


async def test_the_launch_gate_refuses_a_campaign_against_a_drifted_agent() -> None:
    """Not a compliance hole — every dial is refused at `check_dispatch` either way — but
    a campaign that launches, goes `running` and then refuses every single contact is the
    outcome `launch_blockers` exists to prevent, in its own words.

    The rule name and the sentence come from the dial gate's own predicate, so the launch
    screen and the refused dial cannot explain one condition two ways.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, _num = await _clinic(engine)
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Reminders",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
        )
        clean = await campaigns_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert TRUTHFUL_ANSWER_DRIFT_RULE not in {b.rule for b in clean}, (
        "a compliant agent is being refused a launch by the drift gate"
    )

    engine.truncating = True
    await _only(ref)
    with _engine(engine):
        await sweep_engine_drift({"job_try": 1})
    async with tenant_session(tenant_id) as session:
        drifted = await campaigns_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    named = {b.rule: b.reason for b in drifted}
    assert TRUTHFUL_ANSWER_DRIFT_RULE in named, (
        "a campaign can be launched against an agent whose every dial will be refused"
    )
    assert "publish" in named[TRUTHFUL_ANSWER_DRIFT_RULE].lower(), (
        "the blocker does not tell the client the one action that fixes it"
    )


# --- 6. the arms where the instrument itself fails ------------------------------------
#
# Everything above proves the mechanism when the vendor cooperates. These prove what it
# says and — much more importantly — what it WRITES DOWN when it does not, because every
# failure here has the same shape: an agent PROVEN unable to tell a caller it is a machine
# is still answering its number. The only thing that separates a handled outage from an
# invisible one is whether `agents.inbound_silence_reason` claims a silence that is not in
# force. A mirror that lies is worse than no mirror, because it is what every later pass
# reads to decide there is nothing left to do.


def _alerts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The alert CODES raised on this surface. Codes, not messages: the message is prose
    an operator edits, the code is the contract (`inbound_credit_cutover_test`'s reason)."""
    return [
        str(record.__dict__.get("code"))
        for record in caplog.records
        if record.message == "alert" and record.__dict__.get("failure_stage") == "CORE_LOGIC"
    ]


#: The default fake with ONE capability taken away. Built by copy rather than by reaching
#: for `EXTERNAL_DEPLOYMENT_CAPABILITIES`, which also lacks `agent_hosting`: an engine that
#: cannot host our agent refuses at `create_agent` one step earlier, so a fixture using it
#: would never reach the arm under test and would pass for the wrong reason. This isolates
#: exactly the property being measured, and it is the shape `inbound_credit_cutover_test`
#: already uses for its own missing capability.
_NO_INBOUND_BINDING = DEFAULT_FAKE_CAPABILITIES.model_copy(update={"inbound_binding": False})


def _routing_refusal(intent: str) -> ProblemError:
    """What a vendor refusing `POST /inbound/setup` reaches this code as.

    `ProblemError` and nothing else, because that is the only class `route_inbound_numbers`
    counts as a per-number failure — a `RuntimeError` would escape it and fail the caller,
    which is a different arm from the one under test.
    """
    return ProblemError(
        kind="dependency",
        code="engine_inbound_number_refused",
        title="The voice platform refused",
        detail=f"the voice platform would not make this number {intent}",
    )


class _RefusesRouting(FakeEngine):
    """The vendor refusing the ONE call this whole mechanism is made of.

    A mixin over the real adapter rather than a second parallel fake: the two doubles this
    suite already has differ in what the engine ANSWERS, and this differs in what it
    ACCEPTS, so composing them is how a test gets an engine that is both blind and
    obstinate — which is exactly the state `_settle_inbound_silence`'s preserve arm has to
    survive. Flags rather than subclasses per direction, so one instance can cooperate for
    the fixture's publish and refuse afterwards; an engine that refused from birth could
    never get an agent live enough to be silenced.
    """

    #: Refuse to make a number ANSWER — the restore direction.
    refuse_bind: bool = False
    #: Refuse to make a number STOP answering — the silencing direction.
    refuse_unbind: bool = False

    async def bind_inbound_number(self, ref: EngineAgentRef, number: ProvisionedNumber) -> None:
        if self.refuse_bind:
            raise _routing_refusal("answer")
        await super().bind_inbound_number(ref, number)

    async def unbind_inbound_number(self, number: ProvisionedNumber) -> None:
        if self.refuse_unbind:
            raise _routing_refusal("stop answering")
        await super().unbind_inbound_number(number)


class RefusingEngine(_RefusesRouting, TruncatingEngine):
    """Truncates its read-back AND can refuse to route. The instrument for both halves of
    the reconciler's vendor-failure story."""


class BlindRefusingEngine(_RefusesRouting, UnreadableEngine):
    """Proves nothing on a read-back AND can refuse to route: a republish that has no
    evidence the fault is fixed and cannot put the numbers back down either."""


#: Every table with a foreign key onto `agents.id`, and the column holding it — asked of
#: the DATABASE rather than listed here. A list would be wrong within a release: this
#: schema gained four such tables in the week before this test was written, and a fixture
#: that had to be edited to keep deleting an agent is one that quietly stops deleting it.
#: None of these is append-only, so none of them is protected by the immutability trigger
#: (hard rule 4) — the ledgers carry no FK to an agent.
_AGENT_CHILDREN_SQL = """
SELECT c.conrelid::regclass::text,
       (SELECT attname FROM pg_attribute
          WHERE attrelid = c.conrelid
            AND attnum = c.conkey[array_position(c.confkey,
                (SELECT attnum FROM pg_attribute
                   WHERE attrelid = c.confrelid AND attname = 'id'))])
FROM pg_constraint c
WHERE c.confrelid = 'agents'::regclass AND c.contype = 'f'
ORDER BY 1
"""


async def _destroy_agent(tenant_id: UUID, agent_id: UUID, ref: str) -> None:
    """Take the agent row out of the database entirely — not `archived_at`, which the
    console's DELETE writes and which leaves the row exactly where the reconciler reads it.

    The window being reproduced is between the sweep's platform-wide read and this write,
    and what closes it is the row's ABSENCE, however it got there.
    """
    async with untenanted_session() as session:
        children = (await session.execute(text(_AGENT_CHILDREN_SQL))).all()
        await session.execute(
            text("DELETE FROM engine_agent_routes WHERE engine_agent_ref = :r"), {"r": ref}
        )
    async with tenant_session(tenant_id) as session:
        for table, column in children:
            await session.execute(
                text(f"DELETE FROM {table} WHERE {column} = :a"),
                {"a": agent_id},
            )
        removed = await session.execute(text("DELETE FROM agents WHERE id = :a"), {"a": agent_id})
        assert removed.rowcount == 1, "the fixture did not actually remove the agent"


async def test_an_agent_deleted_under_the_reconciler_is_a_non_outcome_not_a_crash() -> None:
    """The sweep reads a batch, then reconciles each row — and an agent can be destroyed in
    between. It is a real window, not a theoretical one: the sweep's read is platform-wide
    and its verdicts are acted on one at a time.

    The row is gone, so there is nothing to silence and nothing to record — the same
    non-outcome `record_drift` reports when a route vanishes under it. What must NOT happen
    is a raised exception, which on the worker edge would abandon the REST of the batch:
    one deleted agent would then leave every non-compliant agent after it in the sweep's
    ordering still answering its phone.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, _number_ref = await _clinic(engine)
    engine.truncating = True

    with _engine(engine):
        drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref)
        assert drift.truthful_answer_applied is False, "the fixture never proved the fault"
        await _destroy_agent(tenant_id, agent_id, ref)
        async with tenant_session(tenant_id) as session:
            outcome = await agents_service.reconcile_inbound_truthful_answer(
                session,
                engine,
                tenant_id=tenant_id,
                agent_id=agent_id,
                truthful_answer_applied=drift.truthful_answer_applied,
            )
    assert outcome == "gone"


async def test_an_engine_that_cannot_unbind_a_number_says_so_instead_of_pretending(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE MOST IMPORTANT OF THE FAILURE ARMS, and the one whose whole content is what it
    REFUSES to do.

    An engine with no `inbound_binding` cannot take a number away, so a proven-non-compliant
    agent is STILL ANSWERING and there is no instrument here that can stop it. The two wrong
    answers are both silent: falling back to `override_call_script` would write more text
    down the very channel just proven not to hold our words (the reconciler's docstring
    argues this at length), and returning quietly would leave nobody knowing. So it pages,
    by name, and it does not stamp — a mirror claiming a silence that never happened is
    what stops every later pass from retrying, and would make this permanent.
    """
    engine = TruncatingEngine(capabilities=_NO_INBOUND_BINDING)
    tenant_id, agent_id, ref, _number_ref = await _clinic(engine)
    engine.truncating = True

    with caplog.at_level("ERROR"):
        outcome, state = await _reconcile(engine, tenant_id, agent_id, ref)

    assert (outcome, state) == ("unsupported", "not_applied")
    assert "inbound_truthful_answer_silence_unsupported" in _alerts(caplog), (
        "a proven-non-compliant agent is still answering its phone and nobody was told"
    )
    assert (await _silence(tenant_id, agent_id)) == (None, None), (
        "the mirror claims a silence this engine is incapable of applying"
    )


async def test_a_refused_unbind_is_not_recorded_as_a_silence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The vendor was asked to take the number away and would not.

    The number is therefore still ringing an agent proven unable to say it is an AI, and
    the ONE thing that must not happen is the stamp: `reconcile_inbound_truthful_answer`
    reads it first and returns `unchanged` for free when it is set, so a stamp written over
    a failed unbind would end the retries and make the failure permanent and invisible.
    """
    engine = RefusingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    engine.refuse_unbind = True

    with caplog.at_level("ERROR"):
        outcome, state = await _reconcile(engine, tenant_id, agent_id, ref)

    assert (outcome, state) == ("failed", "not_applied")
    assert engine.inbound_agent_for(number_ref) == ref, "the fixture's number was never bound"
    assert "engine_inbound_binding_failed" in _alerts(caplog)
    assert (await _silence(tenant_id, agent_id)) == (None, None), (
        "the mirror claims a silence the vendor refused to apply, so nothing will retry it"
    )

    # AND THE RETRY IS REAL: the same call, against a vendor that has stopped refusing,
    # silences the agent. This is the property the un-stamped column exists to preserve.
    engine.refuse_unbind = False
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"
    assert engine.inbound_agent_for(number_ref) is None


async def test_a_refused_rebind_leaves_the_silence_in_place_for_the_next_sweep(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The restore direction, and it fails SAFE.

    The agent has been proven compliant again, but the vendor would not give the number
    back. The stamp stays exactly where it is: it still describes what the engine holds —
    nothing answering — and clearing it would leave our column saying the phone is live
    while it is dead, with no later pass able to notice. The client's remedy is unchanged
    and the next sweep tick retries.
    """
    engine = RefusingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"

    engine.truncating = False
    engine.refuse_bind = True
    with caplog.at_level("ERROR"):
        outcome, state = await _reconcile(engine, tenant_id, agent_id, ref)

    assert (outcome, state) == ("failed", "applied")
    assert engine.inbound_agent_for(number_ref) is None, "the number came back on a refusal"
    assert "engine_inbound_binding_failed" in _alerts(caplog)
    _at, reason = await _silence(tenant_id, agent_id)
    assert reason == agents_service.INBOUND_SILENCE_TRUTHFUL_ANSWER

    engine.refuse_bind = False
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "restored"
    assert engine.inbound_agent_for(number_ref) == ref


async def test_a_preserve_whose_unbind_is_refused_stops_the_mirror_claiming_a_silence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE WORST OF THE THREE OUTCOMES, refused explicitly (`_settle_inbound_silence`).

    A republish that proved nothing has just rebound this agent's numbers as its last act,
    so preserving the silence means putting them straight back down — and here the vendor
    refuses. The numbers may now be answering, so the stamp is CLEARED rather than kept:
    a column that goes on claiming a silence which is not in force is the outcome that
    LOOKS handled, and it is the one an operator never investigates. Cleared, the next
    sweep tick re-silences from a fresh verdict; kept, nothing ever does.
    """
    engine = TruncatingEngine()
    tenant_id, agent_id, ref, number_ref = await _clinic(engine)
    engine.truncating = True
    assert (await _reconcile(engine, tenant_id, agent_id, ref))[0] == "silenced"

    blind = BlindRefusingEngine()
    blind._agents = engine._agents
    blind._inbound = engine._inbound
    blind.refuse_unbind = True
    with caplog.at_level("ERROR"), _engine(blind):
        async with tenant_session(tenant_id) as session:
            await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert blind.inbound_agent_for(number_ref) == ref, (
        "the fixture did not reproduce the case: the publish's rebind never landed, so the "
        "preserve arm had nothing to put back down"
    )
    assert "engine_inbound_binding_failed" in _alerts(caplog)
    assert (await _silence(tenant_id, agent_id)) == (None, None), (
        "the mirror still claims a compliance silence over a number that is answering"
    )
