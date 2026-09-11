"""D-576: `phone_numbers.agent_id` has a writer after the INSERT, and detaching reaches
the engine.

**THE DEFECT.** The column had exactly one writer and it was the INSERT. The only UPDATEs
anywhere in the tree set `dlt_status`, `engine_number_ref` and — on a release —
`agent_id = NULL`; nothing set it to a VALUE afterwards, and neither console hook supplied
one at create time. So `_AGENT_NUMBERS_SQL` returned zero rows for every number this
platform holds, `route_inbound_numbers` returned `bound=0`, and `publish_agent` reported
SUCCESS while the phone never rang. That is verbatim the D-420 defect the routing function
was written to close, reintroduced one layer up — and it was unrecoverable through the
product, because `release_number` refuses a client-owned connection and `phone_numbers.e164`
is globally UNIQUE, so a wrong attachment burned that E.164 on this platform for good.

What is proven here, in the order the defect happens:

1. **Attaching makes the phone ring** — the engine's own read-back, not our column.
2. **Detaching RELEASES at the engine.** A detach that nulled the column and left the
   binding would leave a client's line answered by an agent our screens say is not on it —
   the mirror-lies class D-564 exists for.
3. **Cross-tenant is refused** (hard rule 1): tenant A cannot point its number at tenant
   B's agent, and the refusal is RLS's answer, not a comparison of two supplied ids.
4. The refusals an operator would otherwise meet as silence: a deleted agent, an
   outbound-only agent, a released number.
5. **A publish that answers nothing is loud** when the client holds a number attached to
   nobody — and silent when they simply have no number yet, which is the ordinary
   onboarding order.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle, prompts
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements

NUMBER_AGENT = "/v1/admin/tenants/{tenant_id}/numbers/{number_id}/agent"


def _e164(series: str = "160") -> str:
    """A run-unique number whose PREFIX MATCHES ITS SERIES — `provision_number` checks.

    Run-unique because `phone_numbers.e164` is globally UNIQUE across tenants: a literal
    would collide with every other suite sharing this Postgres, which is also the
    constraint that made this defect unrecoverable.
    """
    prefix = "98" if series == "standard" else series
    digits = 10 - len(prefix)
    return f"+91{prefix}{uuid.uuid4().int % 10**digits:0{digits}d}"


def _alerts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The alert CODES raised. The code is the contract; the message is prose."""
    return [
        str(record.__dict__.get("code")) for record in caplog.records if record.message == "alert"
    ]


async def _tenant(name: str = "Attach Clinic") -> tuple[uuid.UUID, uuid.UUID, str]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name=name,
        slug=f"attach-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        # A script, so the publish below is not refused as `agent_has_no_script` — the
        # publish is a means here, not the subject.
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist.\n",
            notes=None,
            created_by=None,
        )
    await accept_agreements(tenant_id)
    return tenant_id, agent_id, str(created["slug"])


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, direction: str = "inbound") -> str:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = :d WHERE id = :a"),
            {"d": direction, "a": agent_id},
        )
        return await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def _record_number(
    tenant_id: uuid.UUID, *, ref: str | None = "num_attach_1", agent_id: uuid.UUID | None = None
) -> uuid.UUID:
    """A recorded client connection, through the production path an operator uses."""
    async with tenant_session(tenant_id) as session:
        return await agents_service.provision_number(
            session,
            tenant_id=tenant_id,
            e164=_e164("160"),
            series="160",
            agent_id=agent_id,
            provider="plivo",
            purpose="reception",
            engine_number_ref=ref,
        )


async def _attached_agent(tenant_id: uuid.UUID, number_id: uuid.UUID) -> uuid.UUID | None:
    """Read the column back under the tenant's OWN scope.

    `untenanted_session` would answer `None` for every number on the platform — FORCEd RLS
    with no tenant set matches no row — which reads exactly like "not attached" and would
    make this file green against a version that writes nothing.
    """
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT agent_id FROM phone_numbers WHERE id = :n"), {"n": number_id}
            )
        ).scalar()
    return None if value is None else uuid.UUID(str(value))


# --- the two halves the defect was made of -------------------------------------------


async def test_attaching_a_number_to_a_live_agent_makes_the_phone_ring() -> None:
    """THE DEFECT, INVERTED — and asserted at the ENGINE, never at our column.

    Our column was never the thing that was broken in a way a reader could see: it held
    NULL and every screen agreed with it. What nobody could see is that no path existed to
    move it, so the receptionist a client was sold answered nothing. `inbound_agent_for` is
    the only place "attached" and "answering" look different.
    """
    tenant_id, agent_id, _ = await _tenant()
    ref = await _publish(tenant_id, agent_id)
    number_id = await _record_number(tenant_id, ref="num_attach_ring")

    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine.inbound_agent_for("num_attach_ring") is None, "fixture already bound"

    async with tenant_session(tenant_id) as session:
        routing = await agents_service.attach_number_to_agent(
            session, number_id=number_id, agent_id=agent_id
        )

    assert routing.bound == 1, "the attach reported binding nothing at the voice platform"
    assert routing.failed == 0
    assert engine.inbound_agent_for("num_attach_ring") == ref, (
        "the number is attached in our database and the voice platform was never told — "
        "an incoming call reaches whatever the vendor console was last set to"
    )
    assert await _attached_agent(tenant_id, number_id) == agent_id


async def test_detaching_releases_the_binding_at_the_engine_and_not_only_the_column() -> None:
    """A detach that stopped at our database would be a mirror that lies.

    Inbound is answered by whatever the vendor holds against the number; nothing of ours is
    consulted. So "detached" in our console with the binding still live at the engine is
    the worst of the three states — a client's line answered by an agent every screen we
    own says is not on it.
    """
    tenant_id, agent_id, _ = await _tenant()
    ref = await _publish(tenant_id, agent_id)
    number_id = await _record_number(tenant_id, ref="num_attach_detach")
    async with tenant_session(tenant_id) as session:
        await agents_service.attach_number_to_agent(session, number_id=number_id, agent_id=agent_id)
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine.inbound_agent_for("num_attach_detach") == ref, "nothing to detach"

    async with tenant_session(tenant_id) as session:
        routing = await agents_service.attach_number_to_agent(
            session, number_id=number_id, agent_id=None
        )

    assert routing.released == 1, "the detach reported releasing nothing"
    assert engine.inbound_agent_for("num_attach_detach") is None, (
        "the column was nulled and the voice platform still answers this number with the "
        "agent it was detached from"
    )
    assert await _attached_agent(tenant_id, number_id) is None


async def test_re_pointing_a_number_moves_it_and_leaves_the_old_agents_other_numbers_alone() -> (
    None
):
    """The trap in reusing `route_inbound_numbers` for one number.

    Reconciling the LEAVING agent after the column moved would release every OTHER number
    that agent still answers — a re-point that silently darkens a second line. So the
    engine is told about exactly the one number, and `bind_inbound_number` is last-write-
    wins by contract, which is why no unbind precedes it.
    """
    tenant_id, first_agent, _ = await _tenant()
    first_ref = await _publish(tenant_id, first_agent)
    moving = await _record_number(tenant_id, ref="num_attach_moving")
    staying = await _record_number(tenant_id, ref="num_attach_staying")
    async with tenant_session(tenant_id) as session:
        for number_id in (moving, staying):
            await agents_service.attach_number_to_agent(
                session, number_id=number_id, agent_id=first_agent
            )

    async with tenant_session(tenant_id) as session:
        # Through `lifecycle.create_agent`, which is the ONE insert into `agents` on any
        # path that produces an agent a client uses — a hand-written INSERT here would
        # skip four hard-rule-5 columns and prove nothing about a real second desk.
        second_agent = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Second desk",
            direction="inbound",
            language_primary="te-IN",
        )
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=second_agent,
            body="[IDENTITY]\nYou are the second desk.\n",
            notes=None,
            created_by=None,
        )
    second_ref = await _publish(tenant_id, second_agent)

    async with tenant_session(tenant_id) as session:
        await agents_service.attach_number_to_agent(
            session, number_id=moving, agent_id=second_agent
        )

    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine.inbound_agent_for("num_attach_moving") == second_ref
    assert engine.inbound_agent_for("num_attach_staying") == first_ref, (
        "re-pointing one number released another number the leaving agent still answers"
    )


# --- hard rule 1 ----------------------------------------------------------------------


async def test_a_number_cannot_be_attached_to_another_tenants_agent() -> None:
    """MANDATORY (hard rule 1). Tenant A names tenant B's agent and gets a 404.

    `phone_numbers.agent_id` is a foreign key, and PostgreSQL validates a foreign key with
    row security BYPASSED — which is exactly how D-331's create-time hole worked: the
    INSERT succeeded and left one client's calling number pointing at a neighbour's agent.
    The answer is `assert_visible`, resolving the row under THIS session's RLS before
    anything is written, and this drives it on the new path.
    """
    tenant_a, _, _ = await _tenant("Clinic A")
    tenant_b, agent_b, _ = await _tenant("Clinic B")
    number_id = await _record_number(tenant_a, ref="num_attach_crosstenant")

    with pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_a) as session:
            await agents_service.attach_number_to_agent(
                session, number_id=number_id, agent_id=agent_b
            )

    assert caught.value.status == 404, "a neighbour's agent id was accepted or leaked a 409"
    assert await _attached_agent(tenant_a, number_id) is None, (
        "the cross-tenant attachment was written"
    )
    async with tenant_session(tenant_b) as session:
        assert (await session.execute(text("SELECT count(*) FROM phone_numbers"))).scalar() == 0, (
            "the neighbour ended up holding one of A's numbers"
        )


async def test_the_route_refuses_a_cross_tenant_agent_at_the_wire() -> None:
    """The same refusal through the endpoint an operator actually reaches, plus the audit.

    The service test above proves the guard; this proves the ROUTE runs inside
    `tenant_session(tenant_id)` so the guard has a scope to answer from at all — the
    property that makes every other refusal in this file reachable.
    """
    tenant_a, agent_a, _ = await _tenant("Wire A")
    tenant_b, agent_b, _ = await _tenant("Wire B")
    ref = await _publish(tenant_a, agent_a)
    number_id = await _record_number(tenant_a, ref="num_attach_wire")
    token = await _make_admin()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        headers = {"Authorization": f"Bearer {token}"}
        refused = await http.post(
            NUMBER_AGENT.format(tenant_id=tenant_a, number_id=number_id),
            headers=headers,
            json={"agent_id": str(agent_b)},
        )
        allowed = await http.post(
            NUMBER_AGENT.format(tenant_id=tenant_a, number_id=number_id),
            headers=headers,
            json={"agent_id": str(agent_a)},
        )

    assert refused.status_code == 404, refused.text
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["bound"] == 1
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine.inbound_agent_for("num_attach_wire") == ref
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT object_type, object_id FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'number.agent_set'"
                ),
                {"t": tenant_a},
            )
        ).all()
    assert [(str(r[0]), str(r[1])) for r in rows] == [("phone_number", str(number_id))], (
        "changing which agent answers a client's business line left no audit trail"
    )
    assert tenant_b  # the neighbour is untouched; the assertion above is the refusal


# --- the refusals an operator would otherwise meet as silence -------------------------


async def test_an_outbound_only_agent_is_refused_by_name_rather_than_attached() -> None:
    """ "Saved, and nothing happened" is exactly the report this defect was made of.

    An outbound-only agent picks up no incoming call, so attaching a number to it can only
    produce a screen that says it worked and a phone that does not ring.
    """
    tenant_id, agent_id, _ = await _tenant()
    await _publish(tenant_id, agent_id, direction="outbound")
    number_id = await _record_number(tenant_id, ref="num_attach_outbound")

    with pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await agents_service.attach_number_to_agent(
                session, number_id=number_id, agent_id=agent_id
            )

    assert caught.value.code == "agent_does_not_answer_inbound"
    assert await _attached_agent(tenant_id, number_id) is None


async def test_a_deleted_agent_cannot_be_given_a_number() -> None:
    """`assert_agent_writable`, the same guard `provision_number` asks at create time.

    Archiving RELEASES an agent's numbers precisely because inbound is answered by what the
    vendor holds; attaching one afterwards would undo that from a screen.
    """
    tenant_id, agent_id, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    number_id = await _record_number(tenant_id, ref="num_attach_archived")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :a"),
            {"a": agent_id},
        )

    with pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await agents_service.attach_number_to_agent(
                session, number_id=number_id, agent_id=agent_id
            )

    assert caught.value.code == "agent_archived"
    assert await _attached_agent(tenant_id, number_id) is None


async def test_a_released_number_cannot_be_attached() -> None:
    """The record survives a release because a closed month's costs refer to it. It is a
    receipt, not a connection, and an agent attached to it would answer nothing for ever.
    """
    tenant_id, agent_id, _ = await _tenant()
    await _publish(tenant_id, agent_id)
    number_id = await _record_number(tenant_id, ref="num_attach_released")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET released_at = now() WHERE id = :n"), {"n": number_id}
        )

    with pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await agents_service.attach_number_to_agent(
                session, number_id=number_id, agent_id=agent_id
            )

    assert caught.value.code == "number_released"


async def test_attaching_to_an_agent_that_is_not_live_releases_rather_than_binds() -> None:
    """D-440's reasoning, on the later step. A paused agent was deliberately taken off its
    numbers; attaching one from a screen must not put it back on a client's line. The
    attachment is still RECORDED, so `activate` — which republishes and routes every
    attached number — starts it answering the moment it comes back.
    """
    tenant_id, agent_id, _ = await _tenant()
    ref = await _publish(tenant_id, agent_id)
    number_id = await _record_number(tenant_id, ref="num_attach_paused")
    async with tenant_session(tenant_id) as session:
        await agents_service.attach_number_to_agent(session, number_id=number_id, agent_id=agent_id)
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine.inbound_agent_for("num_attach_paused") == ref

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'paused' WHERE id = :a"), {"a": agent_id}
        )
        routing = await agents_service.attach_number_to_agent(
            session, number_id=number_id, agent_id=agent_id
        )

    assert routing.bound == 0 and routing.released == 1
    assert engine.inbound_agent_for("num_attach_paused") is None
    assert await _attached_agent(tenant_id, number_id) == agent_id, (
        "the attachment must survive so `activate` can route it"
    )


async def test_detaching_a_number_the_platform_never_knew_pages_nobody(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A number with no vendor handle cannot be being answered, so there is nothing to
    release and nothing to alarm about. Sending anyway would raise `engine_number_not_linked`
    and page an operator about a state that is already correct.
    """
    tenant_id, agent_id, _ = await _tenant()
    number_id = await _record_number(tenant_id, ref=None)

    with caplog.at_level("INFO"):
        async with tenant_session(tenant_id) as session:
            routing = await agents_service.attach_number_to_agent(
                session, number_id=number_id, agent_id=None
            )

    assert routing == agents_service.InboundRouting(bound=0, released=0, failed=0, unsupported=0)
    assert "engine_inbound_binding_failed" not in _alerts(caplog)
    assert agent_id  # unused here; the number was never attached


# --- the silent no-op, made loud -------------------------------------------------------


async def test_publishing_an_inbound_agent_that_answers_nothing_raises_an_alarm(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE ALARM THAT WOULD HAVE CAUGHT THIS DEFECT AND D-420 BOTH.

    A publish that binds no number, for an agent that answers incoming calls, while the
    client holds a recorded number attached to nobody, is the whole shape of the bug: the
    operator reads "published" and the phone does not ring.
    """
    tenant_id, agent_id, _ = await _tenant()
    await _record_number(tenant_id, ref="num_attach_orphan")

    with caplog.at_level("INFO"):
        await _publish(tenant_id, agent_id)

    assert "agent_published_answering_no_number" in _alerts(caplog), (
        "a receptionist went live answering nothing and the platform reported success"
    )


async def test_a_client_with_no_number_yet_pages_nobody(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The clause that separates the defect from the ordinary onboarding order.

    `provision_number`'s own docstring says a number recorded before its agent exists is
    the normal sequence, which is why `agent_id` is nullable. An alarm on every first
    publish of every client would train an operator to ignore the code — which is the same
    failure as not raising it.
    """
    tenant_id, agent_id, _ = await _tenant()

    with caplog.at_level("INFO"):
        await _publish(tenant_id, agent_id)

    assert "agent_published_answering_no_number" not in _alerts(caplog)


async def _make_admin(role: str = "operator") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


# --- the two 404s, which are the visibility check and not politeness ------------------


@pytest.mark.asyncio
async def test_a_number_that_does_not_exist_is_a_404_and_not_a_lock_held_for_a_stranger() -> None:
    """The NUMBER has no `assert_visible` of its own, deliberately — the locking read below
    it runs under the same RLS and answers the same question, and asking twice would add a
    branch no test could reach (`attach_number_to_agent` says so where it decides not to).

    Which makes THIS the number's visibility check, not a courtesy 404: under FORCEd RLS a
    neighbour's number and an id that never existed are the same empty result, so the arm
    has to refuse both. Driven with a fresh uuid because a cross-tenant number is covered
    one test up and this is the half that must hold when there is no row at all.
    """
    tenant_id, agent_id, _ = await _tenant("Nonexistent Number Clinic")
    await _publish(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refusal:
            await agents_service.attach_number_to_agent(
                session, number_id=uuid.uuid4(), agent_id=agent_id
            )
    assert refusal.value.kind == "not_found"


@pytest.mark.asyncio
async def test_a_soft_deleted_agent_cannot_be_given_a_number() -> None:
    """The one arm neither guard above it covers, and it is reachable rather than defensive.

    `assert_visible` reads `SELECT 1 FROM agents WHERE id = :rid` with NO `deleted_at`
    filter — a deleted row is still this tenant's row — and `assert_agent_writable` reads
    `WHERE deleted_at IS NULL` and only raises on `archived`, so a deleted agent yields
    `status = None` and it returns SILENT. `_AGENT_FOR_ATTACH_SQL` carries the same
    `deleted_at IS NULL`, so this is where a deleted agent is actually refused — and
    without it the attach would fall through to bind a client's phone to an agent that no
    longer exists.
    """
    tenant_id, agent_id, _ = await _tenant("Deleted Agent Clinic")
    await _publish(tenant_id, agent_id)
    number_id = await _record_number(tenant_id, ref="num_attach_deleted")

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET deleted_at = now() WHERE id = :a"), {"a": agent_id}
        )
        with pytest.raises(ProblemError) as refusal:
            await agents_service.attach_number_to_agent(
                session, number_id=number_id, agent_id=agent_id
            )
    assert refusal.value.kind == "not_found"
    assert await _attached_agent(tenant_id, number_id) is None
