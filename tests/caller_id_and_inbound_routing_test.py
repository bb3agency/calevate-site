"""D-420: the number the gate approves is the number that dials, and an assigned
receptionist reaches the engine.

Three symptoms with one root cause — `phone_numbers` carries `e164`, `series`, `provider`
and `agent_id`, and the `VoiceEngine` port could express none of it:

* the DLT-registered header never reached the dial. `campaigns.service._channel_blockers`
  refused a launch and every dispatch tick unless the campaign's number carried the right
  140/160 series and `dlt_status = 'registered'`, while `start_outbound_call` sent no
  caller id at all and the engine answered from its own pool. **A compliance control that
  controls nothing and reports green** — worse than an absent one.
* assigning an agent to a number wrote `phone_numbers.agent_id` and stopped at our
  database. Inbound is half this product and its first configuration step was a screen
  with nothing behind it.

The port half is proven by the conformance suite (`packages/shared/tests/
engine_conformance`), which holds every adapter to both claims. What is proven HERE is the
half that suite cannot see: that OUR resolution reads the right rows, that the refusals
fire where a wrong answer would be a DLT violation, and that a binding that could not be
made is ALARMED rather than reported as done.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.campaigns import service as campaigns_service
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import EXTERNAL_DEPLOYMENT_CAPABILITIES, FakeEngine
from sqlalchemy import text


def _header(series: str = "160") -> str:
    """A fresh header in `series`. Fresh because `phone_numbers.e164` is globally UNIQUE
    across every tenant — the constraint that makes a number one account's or nobody's —
    so a constant here would make these tests collide with each other and with every other
    file in the suite. 160 is the default: that is the class every agent this platform
    publishes runs on today (D-05), and the one a `service` campaign may dial from."""
    return f"+91{series}{uuid.uuid4().int % 1000000:06d}"


#: What `FakeEngine` dials from when nobody named a number — i.e. what a callee sees when
#: the caller id never reached the wire. Asserted against rather than merely "not ours", so
#: a test that starts passing because the fake changed its fallback fails loudly instead.
ENGINE_POOL_NUMBER = "+911140000000"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inside TRAI's calling window, so nothing here is refused for the hour."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


def _alerts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The alert codes raised during this test. The code is the contract; the message is
    prose an operator edits (`tests/ai_quota_test.py` makes the same distinction)."""
    return [
        str(record.__dict__.get("code")) for record in caplog.records if record.message == "alert"
    ]


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Header Clinic",
        slug=f"header-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    # A script, so nothing below is refused as `agent_has_no_script` — the publish path is
    # a means here, not the subject.
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Header Clinic.\n",
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, direction: str = "both") -> str:
    """Put the agent live on the fake engine the way production does — through
    `publish_agent`, so the inbound routing step this file is about actually runs."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = :d WHERE id = :a"),
            {"d": direction, "a": agent_id},
        )
        return await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def _number(
    tenant_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None,
    dlt_status: str = "registered",
    series: str = "160",
    engine_number_ref: str | None = None,
) -> tuple[uuid.UUID, str]:
    """A provisioned number, in whatever state the test needs.

    Written directly rather than through `agents_service.provision_number` because two of
    the columns — `dlt_status` and `engine_number_ref` — are set by other steps entirely
    (an audited admin action and the telephony vendor's own onboarding), and a fixture that
    could only produce the freshly-provisioned state could not set up any of these cases.
    """
    number_id, e164 = uuid7(), _header(series)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                "dlt_status, engine_number_ref, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, :s, :st, :ref, now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": e164,
                "s": series,
                "st": dlt_status,
                "ref": engine_number_ref,
            },
        )
    return number_id, e164


async def _dial(tenant_id: uuid.UUID, agent_id: uuid.UUID, to: str) -> str:
    async with tenant_session(tenant_id) as session:
        return await agents_service.dispatch_call(
            session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None, phone_e164=to
        )


# --- the caller id -------------------------------------------------------------------


async def test_a_dial_presents_the_agents_own_registered_header() -> None:
    """THE DEFECT, INVERTED: the number our gate approves is now the number that rings.

    Asserted through the engine's own execution record rather than by inspecting what
    `dispatch_call` passed, because that is the only place the two possible outcomes look
    different: `start_outbound_call` returns a handle, so "we sent the header" and "we
    dropped it and the vendor used its pool" are otherwise the same observation — which is
    precisely why this went unnoticed.
    """
    tenant_id, agent_id = await _tenant()
    _, header = await _number(tenant_id, agent_id=agent_id)
    await _publish(tenant_id, agent_id)

    handle = await _dial(tenant_id, agent_id, "+919876500001")

    snapshot = await get_engine().get_execution(handle)
    assert snapshot.from_e164 == header, (
        "the callee saw a number this account's DLT registration does not cover"
    )


async def test_a_header_that_is_not_registered_yet_is_not_presented() -> None:
    """`dlt_status` is part of the resolution, not a check somewhere else.

    The campaign gate refuses a campaign whose number is not `registered`, so a number
    this resolution would skip is a number no campaign can be dialling on — the two are
    one fact rather than two opinions. Presenting a `pending` header would be dialling
    from an unregistered header, which is the misclassification that gets the traffic
    dropped as spam and the complaints filed against the client's Principal Entity.
    """
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id, dlt_status="pending")
    await _publish(tenant_id, agent_id)

    handle = await _dial(tenant_id, agent_id, "+919876500002")

    snapshot = await get_engine().get_execution(handle)
    assert snapshot.from_e164 == ENGINE_POOL_NUMBER, (
        "an unregistered header reached the dial — the gate's whole subject is which "
        "header may place a call"
    )


async def test_an_agent_with_two_registered_headers_refuses_the_dial_rather_than_picking() -> None:
    """A coin toss between a 140 and a 160 header is a DLT misclassification.

    Nothing on this path says which classification is dialling — `dispatch_call` is also
    the single-lead and callback entry point — so any pick would be arbitrary, and the one
    that is wrong puts promotional traffic on a transactional header with the client's
    Principal Entity on the complaint. Refusing costs an operator one configuration change;
    picking costs the client their registration.

    NO CALL ROW EITHER: the refusal is raised before the intent row is written, so nothing
    is left `queued` for a dial that was never going to be placed, and the code is in
    `DIAL_NOT_PLACED_CODES` so a campaign contact keeps its place on the ladder.
    """
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id)
    await _number(tenant_id, agent_id=agent_id, series="140")
    await _publish(tenant_id, agent_id)

    with pytest.raises(ProblemError) as excinfo:
        await _dial(tenant_id, agent_id, "+919876500003")

    assert excinfo.value.code == "agent_caller_id_ambiguous", excinfo.value.code
    assert excinfo.value.remediation, "a refusal an operator cannot act on is a dead end"
    assert excinfo.value.code in agents_service.DIAL_NOT_PLACED_CODES, (
        "nothing was seized, so the contact must keep its place on the retry ladder"
    )
    async with tenant_session(tenant_id) as session:
        placed = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
    assert placed == 0


async def test_an_account_with_no_registered_header_still_dials() -> None:
    """NONE IS A LEGITIMATE ANSWER, and this is the clause that keeps it one.

    A D-21 "call this lead" click, a CRM callback and an account whose DLT paperwork is
    still in flight all dial on the engine's own number today, and refusing them would be
    a self-inflicted outage on a rule that governs CAMPAIGNS. The campaign side is where
    the header is made mandatory — a campaign cannot launch without a registered number.
    """
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id)

    handle = await _dial(tenant_id, agent_id, "+919876500004")

    assert (await get_engine().get_execution(handle)).from_e164 == ENGINE_POOL_NUMBER


async def test_another_agents_number_cannot_be_the_campaigns_approved_header() -> None:
    """The launch gate refuses the contradiction it could not previously see.

    The header a dial presents is resolved from the number bound to the AGENT, so a
    campaign whose approved number belongs to a different agent is a campaign whose
    series check, header registration and whole PE/TM model describe one number while
    another one dials.
    """
    tenant_id, agent_id = await _tenant()
    other_agent = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            # A COPY of the seeded agent, so the second agent differs from the first in
            # exactly one thing: which one this campaign names. Column list read off the
            # row rather than typed, so a schema change cannot make this fixture describe
            # an agent shape that no longer exists.
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, created_at, updated_at) "
                "SELECT :new, tenant_id, 'Second agent', direction, status, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, now(), now() FROM agents "
                "WHERE id = :src"
            ),
            {"new": other_agent, "src": agent_id},
        )
    number_id, _ = await _number(tenant_id, agent_id=other_agent)

    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Reminders",
            classification="service",
            number_id=number_id,
            dlt_template_id=None,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        rules = {
            blocker.rule
            for blocker in await campaigns_service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        }
    assert "number_not_bound_to_agent" in rules, (
        "the gate approved a header that this campaign's agent will never dial from"
    )


async def test_a_number_bound_to_nobody_cannot_be_the_campaigns_approved_header() -> None:
    """The other half of the same claim, and the one with the wider blast radius (D-424).

    An approved number bound to a DIFFERENT agent at least dials SOME registered header.
    A number bound to NO agent resolves to nothing — `resolve_caller_id` returns None,
    which is a legitimate answer on the single-lead and callback paths — and the dial then
    goes out on the engine's own pool. So every campaign on the platform would present the
    vendor's number while its 140/160 series check, its header registration and its whole
    PE/TM model described a number nobody heard.

    Asked at BOTH gates on purpose. `launch_blockers` is a photograph taken when the
    button was clicked; a number can be unassigned from an agent while the campaign runs,
    and `dispatch_blockers` is what re-reads it on every tick.
    """
    tenant_id, agent_id = await _tenant()
    number_id, _ = await _number(tenant_id, agent_id=None)

    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Reminders",
            classification="service",
            number_id=number_id,
            dlt_template_id=None,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        at_launch = {
            blocker.rule: blocker.reason
            for blocker in await campaigns_service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        }
        per_tick = {
            blocker.rule
            for blocker in await campaigns_service.dispatch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        }

    assert "number_not_bound_to_agent" in at_launch, (
        "the gate approved a header no agent dials from, so the campaign would have gone "
        "out on the engine's own pool with our own records showing it cleared"
    )
    assert "number_not_bound_to_agent" in per_tick, (
        "the rule is a photograph at launch only — a number unassigned mid-campaign "
        "would keep dialling"
    )
    # The VERDICT is shared; the REMEDIATION is not. A client who never assigned the
    # number and a client who assigned it elsewhere have different next actions, and a
    # single sentence covering both would be actionable for neither.
    assert at_launch["number_not_bound_to_agent"] == campaigns_service.UNBOUND_NUMBER_REASON
    assert campaigns_service.UNBOUND_NUMBER_REASON != campaigns_service.OTHER_AGENT_NUMBER_REASON, (
        "two states, two next actions, and the client can only act on the one they are in"
    )


# --- inbound routing -----------------------------------------------------------------


async def test_publishing_an_inbound_agent_makes_the_engine_answer_its_numbers() -> None:
    """The step that used to end at our database.

    `phone_numbers.agent_id` said the receptionist was assigned; the engine had never been
    told, so an incoming call reached whatever the vendor console was last set to — or
    nothing at all.
    """
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id, engine_number_ref="num_clinic_1")

    ref = await _publish(tenant_id, agent_id, direction="inbound")

    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine.inbound_agent_for("num_clinic_1") == ref, (
        "the engine does not know which agent answers this number, so the number is dark"
    )


async def test_an_agent_switched_to_outbound_only_stops_answering() -> None:
    """The half a symmetry-free implementation would have missed.

    `agents.direction` is editable. An agent that was a receptionist and is republished as
    outbound-only must STOP answering; leaving the engine's binding in place keeps a
    receptionist live on a number whose owner has just switched it off in our console —
    the same lie in the opposite direction.
    """
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id, engine_number_ref="num_clinic_2")
    await _publish(tenant_id, agent_id, direction="both")
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine.inbound_agent_for("num_clinic_2") is not None

    await _publish(tenant_id, agent_id, direction="outbound")

    assert engine.inbound_agent_for("num_clinic_2") is None, (
        "an outbound-only agent is still answering a number at the engine"
    )


async def test_a_number_the_engine_has_never_heard_of_is_alarmed_not_reported_done(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The failure that must never look like success.

    Numbers are bought from the telephony vendor directly (D-05), so a number with no
    `engine_number_ref` is the ORDINARY state and there is nothing to bind — the publish
    still succeeds (the agent itself is live and verified) and the operator is paged with
    the agent id, the number's row id and the refusal code. What is not acceptable, and was
    the state this closes, is neither: a console reporting an assignment that reached
    nobody.
    """
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id, engine_number_ref=None)

    with caplog.at_level("ERROR"):
        ref = await _publish(tenant_id, agent_id, direction="inbound")

    assert ref, "the agent itself publishes — a number binding is not a publish failure"
    assert "engine_inbound_binding_failed" in _alerts(caplog), (
        "a number nobody could route was recorded as routed"
    )


async def test_assigning_a_number_to_a_published_agent_reaches_the_engine_at_once() -> None:
    """Provisioning is the other order, and it must not wait for the next publish.

    An admin who assigns a number to an agent that is ALREADY live expects the number to
    start answering now; a binding that only landed if somebody happened to edit the agent
    afterwards would be the same screen-with-nothing-behind-it one step over.
    """
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id, direction="inbound")

    async with tenant_session(tenant_id) as session:
        number_id = await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=_header(),
            series="160",
            agent_id=agent_id,
            provider="plivo",
            purpose="reception",
        )
        # The engine's own handle for the number, which the telephony onboarding supplies.
        await session.execute(
            text("UPDATE phone_numbers SET engine_number_ref = :ref WHERE id = :id"),
            {"ref": "num_clinic_3", "id": number_id},
        )
        await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=_header(),
            series="160",
            agent_id=agent_id,
            provider="plivo",
            purpose="reception",
        )

    # Re-assigning through the same path once the handle exists is what an operator does
    # after the vendor has been given the number.
    async with tenant_session(tenant_id) as session:
        engine = get_engine()
        assert isinstance(engine, FakeEngine)
        await agents_service.route_inbound_numbers(
            session,
            engine,
            agent_id=agent_id,
            ref=str(
                (
                    await session.execute(
                        text("SELECT engine_agent_ref FROM agents WHERE id = :a"),
                        {"a": agent_id},
                    )
                ).scalar()
            ),
            answers=True,
        )
    assert engine.inbound_agent_for("num_clinic_3") is not None


async def test_an_engine_that_cannot_route_numbers_reports_it_once_and_pages_nobody(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The `unsupported` arm, driven by the second shape rather than reasoned about.

    `EXTERNAL_DEPLOYMENT_CAPABILITIES` is an engine with no agent object of ours for a
    number to be bound to, so it answers `inbound_binding=False` — and that answer is what
    makes this arm executable code rather than an interface obligation nothing runs. The
    real `cartesia` adapter cannot reach it through `publish_agent` (it has no agent to
    publish), which is exactly why the profile exists: the capability difference needs no
    vendor contract to express, and this function's contract is per-ENGINE, not per-vendor.

    TWO claims, and the second is the one a naive implementation gets wrong. A platform
    that cannot route numbers at all is a DEPLOYMENT FACT, not an incident — it refuses at
    the console through the same capability — so the numbers are reported `unsupported`
    and NOBODY IS PAGED. Paging per number per publish would wake an operator about a
    property of the platform they chose, on every publish, forever; and the count has to
    be right, because a caller that reported `unsupported=0` would tell an admin the
    assignment landed.
    """
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id, engine_number_ref="num_deployed_1")
    await _number(tenant_id, agent_id=agent_id, engine_number_ref="num_deployed_2")

    engine = FakeEngine(capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES, name="fake-deployed")
    with caplog.at_level("INFO"):
        async with tenant_session(tenant_id) as session:
            routing = await agents_service.route_inbound_numbers(
                session,
                engine,
                agent_id=agent_id,
                ref="deployment_receptionist",
                answers=True,
            )

    assert routing == agents_service.InboundRouting(bound=0, released=0, failed=0, unsupported=2), (
        "an engine that cannot route a number reported numbers it had routed"
    )
    assert engine.inbound_agent_for("num_deployed_1") is None
    assert "engine_inbound_binding_failed" not in _alerts(caplog), (
        "a platform property paged an operator — and would do so on every publish"
    )
    assert [r.message for r in caplog.records].count("engine_inbound_binding_unsupported") == 1, (
        "asked once per publish is the whole point: one line per NUMBER is the noise this "
        "arm exists to avoid"
    )
