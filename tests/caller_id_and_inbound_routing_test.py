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
half that suite cannot see: that OUR resolution reads the right rows (the agent's outbound
numbers whatever their DLT state, the campaign's chosen one first, D-793), and that a
binding that could not be made is ALARMED rather than reported as done.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import EXTERNAL_DEPLOYMENT_CAPABILITIES, FakeEngine
from sqlalchemy import text
from tests.conftest import accept_agreements, create_org_with_receptionist


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
    created = await create_org_with_receptionist(
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
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away. Since that release every dial gate refuses an organisation that has not
    # accepted them, and a fixture without them makes this file report
    # `agreements_not_accepted` in place of the refusal it is actually about.
    await accept_agreements(tenant_id)
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


async def _dial(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, to: str, *, number_id: uuid.UUID | None = None
) -> str:
    async with tenant_session(tenant_id) as session:
        return await agents_service.dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164=to,
            number_id=number_id,
        )


async def _calls_placed(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int((await session.execute(text("SELECT count(*) FROM calls"))).scalar_one())


# --- the caller id -------------------------------------------------------------------


async def test_a_dial_presents_the_agents_own_number() -> None:
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
    assert snapshot.from_e164 == header, "the callee saw a number other than the agent's own"


async def test_a_number_never_registered_on_dlt_is_presented() -> None:
    """D-793: every number is inserted `pending` and nothing outbound asks for `registered`
    since D-692, so a caller id gated on `dlt_status` was dropped for every client number."""
    tenant_id, agent_id = await _tenant()
    _, number = await _number(tenant_id, agent_id=agent_id, dlt_status="pending")
    await _publish(tenant_id, agent_id)

    handle = await _dial(tenant_id, agent_id, "+919876500002")

    assert (await get_engine().get_execution(handle)).from_e164 == number


async def test_several_numbers_and_no_campaign_choice_leave_the_engine_its_own_line() -> None:
    """Nothing on this path says which number to use, so no `from` is sent and the engine
    rings from the agent's own line — and the call is still placed."""
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id)
    await _number(tenant_id, agent_id=agent_id, dlt_status="pending", series="140")
    await _publish(tenant_id, agent_id)

    handle = await _dial(tenant_id, agent_id, "+919876500003")

    assert (await get_engine().get_execution(handle)).from_e164 == ENGINE_POOL_NUMBER
    assert await _calls_placed(tenant_id) == 1


async def test_the_campaigns_chosen_number_is_presented_among_several() -> None:
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id)
    chosen_id, chosen = await _number(tenant_id, agent_id=agent_id, dlt_status="pending")
    await _publish(tenant_id, agent_id)

    handle = await _dial(tenant_id, agent_id, "+919876500005", number_id=chosen_id)

    assert (await get_engine().get_execution(handle)).from_e164 == chosen


async def test_a_campaign_number_the_client_no_longer_holds_refuses_the_dial() -> None:
    """Sending another number would break the campaign gate's promise that its calls come
    from the number it names; refused before the intent row, so nothing was seized."""
    tenant_id, agent_id = await _tenant()
    await _number(tenant_id, agent_id=agent_id)
    unbound_id, _ = await _number(tenant_id, agent_id=None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET released_at = now() WHERE id = :n"),
            {"n": unbound_id},
        )
    await _publish(tenant_id, agent_id)

    with pytest.raises(ProblemError) as excinfo:
        await _dial(tenant_id, agent_id, "+919876500006", number_id=unbound_id)

    assert excinfo.value.code == agents_service.CAMPAIGN_NUMBER_UNAVAILABLE_CODE
    assert excinfo.value.remediation
    assert agents_service.dial_was_not_placed(excinfo.value)
    assert await _calls_placed(tenant_id) == 0


async def test_an_account_with_no_number_still_dials() -> None:
    """None is a legitimate answer: with no number of its own to name, the dial goes out
    on the engine's own line rather than being refused."""
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id)

    handle = await _dial(tenant_id, agent_id, "+919876500004")

    assert (await get_engine().get_execution(handle)).from_e164 == ENGINE_POOL_NUMBER


async def test_an_agent_with_no_number_of_its_own_rings_from_its_clients_number() -> None:
    """Founder, 4 Nov 2026: a client's number serves all its agents, not only the one that
    answers it."""
    tenant_id, agent_id = await _tenant()
    _, theirs = await _number(tenant_id, agent_id=None)
    await _publish(tenant_id, agent_id)

    handle = await _dial(tenant_id, agent_id, "+919876500007")

    assert (await get_engine().get_execution(handle)).from_e164 == theirs


async def test_a_number_another_agent_is_calling_out_on_is_held_until_its_call_ends() -> None:
    """A number is lent to one agent at a time (`update-phone-number.md:144-145`): while one
    agent's call is live on it, another agent's dial is refused as lines busy (tried again
    later), and the same agent's next call is not."""
    tenant_id, agent_id = await _tenant()
    number_id, e164 = await _number(tenant_id, agent_id=None)
    other = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, "
                "created_at, updated_at) SELECT :new, tenant_id, 'Second agent', direction, "
                "status, disclosure_line, ai_disclosure_line, recording_notice_line, "
                "caller_memory_notice_line, now(), now() FROM agents WHERE id = :src"
            ),
            {"new": other, "src": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "from_e164, to_e164, status, created_at, updated_at) VALUES (:id, :tid, :aid, "
                ":ecid, 'outbound', :e, '+919876500099', 'in_progress', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "aid": other, "ecid": f"x-{uuid7()}", "e": e164},
        )
    line = agents_service.CallerLine(
        number_id=number_id, e164=e164, own=False, engine_number_ref="ref"
    )

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as busy:
            await agents_service._hold_client_number(session, number=line, agent_id=agent_id)
        await agents_service._hold_client_number(session, number=line, agent_id=other)

    assert agents_service.dial_was_not_placed(busy.value)


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
            provider="thinnest",
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
            provider="thinnest",
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


async def test_a_number_held_in_another_workspace_than_the_agent_is_never_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Founder, 4 Nov 2026: a Calevate number not yet moved into the client's workspace was
    chosen for every campaign dial, and the platform refused to lend it to the agent."""
    tenant_id, agent_id = await _tenant()
    waiting_id, _ = await _number(tenant_id, agent_id=None, engine_number_ref="918065580032")
    moved_id, _ = await _number(tenant_id, agent_id=None, engine_number_ref="918065580099@org_c")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE phone_numbers SET provider = 'thinnest', direction = 'both' "
                "WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        )
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_x@org_c' WHERE id = :a"),
            {"a": agent_id},
        )
    monkeypatch.setattr(agents_service, "outbound_number_provider", lambda: "thinnest")
    async with tenant_session(tenant_id) as session:
        lines = await agents_service.caller_lines(session, agent_id=agent_id)
    assert [line.number_id for line in lines] == [moved_id]
    assert waiting_id not in [line.number_id for line in lines]
