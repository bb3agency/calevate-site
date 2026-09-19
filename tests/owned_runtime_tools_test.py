"""The four in-call tools on the engine we run ourselves, end to end over the real wire.

**WHAT THIS FILE IS DEFENDING.** `apps/voice-runtime/tool_routes.py` serves four custom
functions on the RENTED engine and `voice_worker/pipeline.assemble_call` advertised exactly
one. So on `owned_runtime` a caller saying "stop calling me" reached nothing at all — no
`dnc_list` row, no `consent_ledger` evidence, nothing for the dispatch gate to read. That is
hard rule 5 and SEC-COMP §2.3 failing silently, and it is why the opt-out tests here assert
ROWS rather than status codes: an endpoint that answers 200 and writes nothing is exactly
the failure mode being fixed.

**THE CLIENT IS THE REAL ONE AND THE SERVER IS THE REAL APP**, joined in process by
`httpx.ASGITransport` — `worker_api_harness`'s arrangement, for its reason. A mocked
transport would prove only that one end is self-consistent.

**EVERY OUTCOME EACH TOOL CAN REACH IS HERE, INCLUDING THE REFUSALS**, because the refusals
are where the behaviour lives: an unlawful callback time, an unconfirmed booking, a caller
whose number we do not hold, a cancellation with nothing booked, a handover this engine
cannot perform. Three of those are sentences an agent reads to a person.

SHARED DATABASE DISCIPLINE: every organisation is minted by `published_agent`, and every
assertion is scoped to ids this module created. Nothing counts rows globally.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from apps.api.db.session import tenant_session
from apps.api.main import app as api_app
from calevate_shared.calling_window import IST
from calevate_shared.events import CallEvent
from calevate_shared.worker_api import (
    CallbackBookIn,
    CallbackCancelIn,
    CallerIdentityIn,
    HandoffToolIn,
    ObservationBatch,
    OptOutToolIn,
)
from sqlalchemy import text
from tests.worker_api_harness import (
    TOKEN,
    call_ref,
    declare_pipecat_engine,
    published_agent,
)
from voice_worker.api_client import WorkerApiError
from voice_worker.call_tools import CallToolApiClient

pytestmark = [pytest.mark.rls]

#: A caller whose number we DO hold. E.164, and deliberately a valid Indian mobile so
#: `normalize_phone` keeps it — `record_call_optout` refuses a number it cannot key, and a
#: test that tripped that refusal would be asserting the wrong branch.
CALLER = "+919812345672"


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """These routes refuse a deployment running another engine (D-627)."""
    yield from declare_pipecat_engine(monkeypatch)


def tool_client(token: str = TOKEN) -> CallToolApiClient:
    """`worker_api_harness.worker_client`, as the subclass that carries the four tools."""
    return CallToolApiClient.from_config(
        base_url="http://api",
        token=token,
        transport=httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444)),
    )


async def a_call_in_progress(
    *, caller: str | None = CALLER
) -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """A published agent and a `calls` row mid-call. Returns (tenant, agent, call id, ref).

    THE ROW IS MINTED THE WAY A REAL CALL MINTS IT — by posting an observation batch — so
    the number under test is the one the worker really puts there rather than one a test
    INSERTed in the shape it hoped for.
    """
    tenant_id, agent_id, _agent_ref = await published_agent()
    call_id, ref = call_ref(tenant_id)
    async with tool_client() as api:
        await api.post_observations(
            ref,
            ObservationBatch(
                agent_id=agent_id,
                direction="inbound",
                from_e164=caller,
                events=[
                    CallEvent(
                        call_id=call_id,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        direction="inbound",
                        status="in_progress",
                        engine="pipecat",
                    )
                ],
            ),
        )
    return tenant_id, agent_id, call_id, ref


async def dnc_rows(tenant_id: uuid.UUID, phone: str) -> int:
    async with tenant_session(tenant_id) as session:
        return len(
            (
                await session.execute(
                    text("SELECT 1 FROM dnc_list WHERE tenant_id = :t AND phone_e164 = :p"),
                    {"t": tenant_id, "p": phone},
                )
            ).all()
        )


async def withdrawals(tenant_id: uuid.UUID, phone: str) -> int:
    async with tenant_session(tenant_id) as session:
        return len(
            (
                await session.execute(
                    text(
                        "SELECT 1 FROM consent_ledger WHERE tenant_id = :t AND "
                        "phone_e164 = :p AND status = 'withdrawn'"
                    ),
                    {"t": tenant_id, "p": phone},
                )
            ).all()
        )


def lawful_slot(days_ahead: int = 2) -> tuple[str, str]:
    """A date and time inside the calling window, as the model is told to produce them.

    Computed rather than hardcoded: `resolve_slot` refuses anything more than
    `MAX_AHEAD` (30 days) out, so a literal date would start failing on a fixed day.
    """
    day = (datetime.now(UTC) + IST + timedelta(days=days_ahead)).date()
    return day.isoformat(), "10:00"


# --- the opt-out: the compliance one ------------------------------------------------------


@pytest.mark.asyncio
async def test_opt_out_suppresses_the_caller_and_says_so(worker_token: None) -> None:
    """THE DEFECT, CLOSED: "stop calling me" now reaches `dnc_list` on this engine.

    The row and the `consent_ledger` withdrawal are both asserted, because the suppression
    without the evidence cannot be explained to the client whose registration is on the
    line, and the evidence without the suppression is a record of an instruction we then
    ignored (`record_call_optout`).
    """
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    assert await dnc_rows(tenant_id, CALLER) == 0

    async with tool_client() as api:
        answer = await api.opt_out(ref, OptOutToolIn(reason="stop calling me", language="en-IN"))

    assert answer.status == "recorded"
    assert answer.reason == ""
    # The sentence the agent reads must claim the removal, because the removal happened.
    assert "removed" in answer.say
    assert await dnc_rows(tenant_id, CALLER) == 1
    assert await withdrawals(tenant_id, CALLER) == 1


@pytest.mark.asyncio
async def test_opt_out_refuses_to_claim_success_when_the_caller_is_unknown(
    worker_token: None,
) -> None:
    """THE HONEST DEGRADATION. A caller told "done" when nothing was written will not ring
    back to check — they will simply be called again.

    The `calls` row has no party (Plivo: `unparsed_by_client`) and the container observed
    none either, so there is nothing to key a suppression to. The answer must therefore
    say `not_recorded`, must forbid the agent from claiming the removal, and must name the
    identity STATE so an operator can tell "the carrier withheld it" from "nobody looked".
    """
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress(caller=None)

    async with tool_client() as api:
        answer = await api.opt_out(
            ref,
            OptOutToolIn(
                reason="do not call me again",
                caller=CallerIdentityIn(state="unparsed_by_client"),
            ),
        )

    assert answer.status == "not_recorded"
    assert answer.reason == "caller_number_unknown:unparsed_by_client"
    assert "Do NOT tell them they have been removed" in answer.say
    assert "passed to a person" in answer.say
    # NOTHING WAS WRITTEN, which is the half a status word alone would not prove.
    async with tenant_session(tenant_id) as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one() == 0


@pytest.mark.asyncio
async def test_opt_out_uses_the_number_the_container_observed_when_the_row_has_none(
    worker_token: None,
) -> None:
    """A caller can ask in the first three seconds, before any batch has flushed.

    Refusing them because our own write had not landed yet would be a suppression lost to
    timing. The container's `CallerIdentity` is believed for exactly one state — `known` —
    which is the only one that means a number was really read off a handshake.
    """
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress(caller=None)

    async with tool_client() as api:
        answer = await api.opt_out(
            ref,
            OptOutToolIn(caller=CallerIdentityIn(state="known", e164=CALLER)),
        )

    assert answer.status == "recorded"
    assert await dnc_rows(tenant_id, CALLER) == 1


@pytest.mark.asyncio
async def test_a_number_the_dial_gate_could_never_match_is_not_reported_as_suppressed(
    worker_token: None,
) -> None:
    """`record_call_optout` refuses a number it cannot normalise, and it is RIGHT to: a row
    filed under a string the dispatch gate will never match looks like protection and blocks
    nothing.

    That refusal must not reach the agent as an API error either — a failing tool call reads
    to a model as a misconfiguration and it says something invented. It reaches the caller as
    the same honest sentence an unattributable call gets.
    """
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress(caller="not-a-number")
    async with tool_client() as api:
        answer = await api.opt_out(ref, OptOutToolIn(reason="stop"))
    assert answer.status == "not_recorded"
    assert answer.reason == "not_suppressible"
    assert "Do NOT tell them they have been removed" in answer.say
    async with tenant_session(tenant_id) as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one() == 0


@pytest.mark.asyncio
async def test_opt_out_twice_is_one_suppression_and_the_agent_is_told_it_worked_both_times(
    worker_token: None,
) -> None:
    """A model invoking the function twice must not produce two suppressions — and must not
    produce a second, different answer either. `record_call_optout` is idempotent by
    construction; this proves the tool inherits that rather than re-deciding it."""
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    async with tool_client() as api:
        first = await api.opt_out(ref, OptOutToolIn(reason="stop"))
        second = await api.opt_out(ref, OptOutToolIn(reason="stop"))
    assert (first.status, second.status) == ("recorded", "recorded")
    assert await dnc_rows(tenant_id, CALLER) == 1


@pytest.mark.asyncio
async def test_a_call_this_platform_never_minted_is_refused(worker_token: None) -> None:
    """A ref naming no call of ours is a WIRING fault, not a conversational outcome: the
    agent must hear a failure rather than a sentence about the caller's number."""
    tenant_id, _agent_id, _call_id, _ref = await a_call_in_progress()
    _unknown, stranger_ref = call_ref(tenant_id)
    async with tool_client() as api:
        with pytest.raises(WorkerApiError):
            await api.opt_out(stranger_ref, OptOutToolIn())


@pytest.mark.asyncio
async def test_every_tool_refuses_a_caller_with_no_token(worker_token: None) -> None:
    """AUTHENTICATION DOES NOT DEGRADE, on the new routes as on the old ones."""
    _tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    async with tool_client(token="not-the-deployments-token") as api:
        for call in (
            api.opt_out(ref, OptOutToolIn()),
            api.book_callback(ref, CallbackBookIn()),
            api.cancel_callback(ref, CallbackCancelIn()),
            api.handoff(ref, HandoffToolIn()),
        ):
            with pytest.raises(WorkerApiError):
                await call


# --- the call-back pair -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_callback_is_not_booked_until_it_has_been_read_back(worker_token: None) -> None:
    """CONFIRM-BEFORE-COMMIT IS A SERVER-SIDE CONTROL, NOT A LINE IN A PROMPT.

    The first call must write nothing and hand back the unambiguous spoken form; the second
    books it. A caller told "four o'clock" who meant the afternoon costs one turn here and a
    phone call at four in the morning if this gate is a prompt instruction instead.
    """
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    date, clock = lawful_slot()

    async with tool_client() as api:
        unconfirmed = await api.book_callback(
            ref, CallbackBookIn(callback_date=date, callback_time=clock)
        )
        assert unconfirmed.status == "needs_confirmation"
        assert unconfirmed.booked_for
        async with tenant_session(tenant_id) as session:
            assert (
                await session.execute(
                    text("SELECT count(*) FROM scheduled_callbacks WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).scalar_one() == 0

        booked = await api.book_callback(
            ref, CallbackBookIn(callback_date=date, callback_time=clock, confirmed=True)
        )

    assert booked.status == "booked"
    # THE SPOKEN FORM IS THE SAME ONE THE AGENT READ OUT. A booking confirmed against one
    # sentence and written against another is the whole failure the confirm step prevents.
    assert booked.booked_for == unconfirmed.booked_for
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT phone_e164 FROM scheduled_callbacks WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).first()
    assert row is not None and row[0] == CALLER


@pytest.mark.asyncio
async def test_an_unlawful_time_is_refused_with_something_to_offer_instead(
    worker_token: None,
) -> None:
    """A time outside 09:00-21:00 IST is unlawful to dial (TCCCPR; SEC-COMP §3), and the
    refusal has to reach the caller while they are still on the phone.

    It is a 200 and not an error: an error tells the agent OUR API is broken, when what it
    needs to hear is what to offer instead (`tool_routes._book_callback`'s argument).
    """
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    date, _clock = lawful_slot()
    async with tool_client() as api:
        answer = await api.book_callback(
            ref, CallbackBookIn(callback_date=date, callback_time="04:00", confirmed=True)
        )
    assert answer.status == "not_booked"
    assert answer.reason == "outside_calling_hours"
    # The nearest lawful slot, so the agent can offer a real alternative rather than asking
    # an open question the caller has already answered.
    assert answer.booked_for
    async with tenant_session(tenant_id) as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM scheduled_callbacks WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one() == 0


@pytest.mark.asyncio
async def test_an_unreadable_time_is_refused_without_a_guess(worker_token: None) -> None:
    """`resolve_slot` refuses; it never repairs. One parser, one set of refusals."""
    _tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    async with tool_client() as api:
        answer = await api.book_callback(
            ref, CallbackBookIn(callback_date="next tuesday", callback_time="4ish", confirmed=True)
        )
    assert answer.status == "not_booked"
    assert answer.reason == "unreadable_time"


@pytest.mark.asyncio
async def test_a_callback_cannot_be_booked_for_a_caller_we_cannot_ring(
    worker_token: None,
) -> None:
    """A promise to ring somebody back needs a number to ring."""
    _tenant_id, _agent_id, _call_id, ref = await a_call_in_progress(caller=None)
    date, clock = lawful_slot()
    async with tool_client() as api:
        answer = await api.book_callback(
            ref, CallbackBookIn(callback_date=date, callback_time=clock, confirmed=True)
        )
    assert answer.status == "not_booked"
    assert answer.reason == "caller_number_unknown:not_read"
    assert "could NOT book" in answer.say


@pytest.mark.asyncio
async def test_a_time_that_cannot_be_saved_is_never_reported_as_booked(
    worker_token: None,
) -> None:
    """ "Book me Tuesday" — "actually cancel it" — "no, make it Wednesday".

    `callbacks.book` will not resurrect a cancelled promise (its upsert carries a
    `status = 'scheduled'` predicate so a late duplicate cannot re-open one the client or
    the gate refused), so the third turn writes NOTHING. An agent that said "Wednesday is
    booked" there would have invented a promise, which is the same class of defect as the
    opt-out claiming a suppression it did not write.
    """
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    first_date, clock = lawful_slot(days_ahead=2)
    second_date, _ = lawful_slot(days_ahead=3)

    async with tool_client() as api:
        await api.book_callback(
            ref, CallbackBookIn(callback_date=first_date, callback_time=clock, confirmed=True)
        )
        await api.cancel_callback(ref, CallbackCancelIn())
        answer = await api.book_callback(
            ref, CallbackBookIn(callback_date=second_date, callback_time=clock, confirmed=True)
        )

    assert answer.status == "not_booked"
    assert answer.reason == "not_bookable_now"
    assert "Do NOT tell the caller it is booked" in answer.say
    # And the cancelled row is still cancelled: nothing was resurrected.
    async with tenant_session(tenant_id) as session:
        statuses = [
            row[0]
            for row in (
                await session.execute(
                    text("SELECT status FROM scheduled_callbacks WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            ).all()
        ]
    assert statuses == ["cancelled"]


@pytest.mark.asyncio
async def test_cancelling_calls_off_the_promise_without_suppressing_the_number(
    worker_token: None,
) -> None:
    """ "Do not ring me back" IS NOT "never call me again".

    Answering a cancellation with a DNC entry would suppress a number on a sentence its
    speaker did not say, so the absence of the `dnc_list` row is asserted here as hard as
    the cancellation itself.
    """
    tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    date, clock = lawful_slot()
    async with tool_client() as api:
        await api.book_callback(
            ref, CallbackBookIn(callback_date=date, callback_time=clock, confirmed=True)
        )
        answer = await api.cancel_callback(ref, CallbackCancelIn())

    assert answer.status == "cancelled"
    assert answer.cancelled == 1
    assert await dnc_rows(tenant_id, CALLER) == 0


@pytest.mark.asyncio
async def test_cancelling_with_nothing_booked_is_a_success_and_not_a_failure(
    worker_token: None,
) -> None:
    """Nobody is going to ring them back, which is what they asked for. Reporting a failure
    would send the agent apologising for a state the caller wanted."""
    _tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    async with tool_client() as api:
        answer = await api.cancel_callback(ref, CallbackCancelIn())
    assert answer.status == "cancelled"
    assert answer.cancelled == 0
    assert answer.reason == "nothing_booked"


@pytest.mark.asyncio
async def test_cancelling_for_an_unknown_caller_does_not_claim_to_have_cancelled(
    worker_token: None,
) -> None:
    _tenant_id, _agent_id, _call_id, ref = await a_call_in_progress(caller=None)
    async with tool_client() as api:
        answer = await api.cancel_callback(ref, CallbackCancelIn())
    assert answer.status == "not_cancelled"
    assert answer.reason == "caller_number_unknown:not_read"


# --- the handoff --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_handoff_tool_refuses_and_tells_the_agent_not_to_promise_a_transfer(
    worker_token: None,
) -> None:
    """THIS ENGINE CANNOT TRANSFER A CALLER AND THE REFUSAL IS THE FEATURE.

    `PIPECAT_CAPABILITIES.in_call_handoff` is False. What this replaces is worse than a
    refusal: with no tool at all the model answered from its priors, said "putting you
    through now", and the caller heard a disconnect. The assertion is on the two
    instructions that prevent that exact sentence.
    """
    _tenant_id, _agent_id, _call_id, ref = await a_call_in_progress()
    async with tool_client() as api:
        answer = await api.handoff(
            ref, HandoffToolIn(reason="caller asked for a person", summary="billing dispute")
        )
    assert answer.status == "not_transferred"
    assert answer.reason == "engine_cannot_transfer"
    assert "must not say you are transferring them" in answer.say
    assert "call them back" in answer.say
