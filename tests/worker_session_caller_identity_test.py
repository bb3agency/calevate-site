"""Who was on the call, carried from the carrier handshake to the column that needs it.

**THE HOP THAT DID NOT EXIST.** `calls.from_e164` had no producer on this engine at all,
and that is not a missing screen field: `leads.phone_e164` is NOT NULL and is derived from
it, caller memory filters on `IS NOT NULL` as a hard condition, a DPDP erasure takes its
SUBJECT from it, and an opt-out is keyed on it. `voice_worker/carrier.CallerIdentity` now
answers the question as a four-state verdict rather than a nullable string; this file holds
down the two ends of the hop that carries the answer —
`pipeline.NormalizedEventBoundary._event` stamping it onto every `CallEvent`, and
`worker/service.record_observations` reading it off there when the batch names no party.

**THE STATE IS THE POINT, NOT THE NUMBER.** A `None` that means four unrelated things
cannot be triaged, which is exactly how this column came to be empty on every call with
nothing anywhere saying why. So the tests below assert that the THREE not-known states each
leave the column NULL and that only `known` fills it — a verdict that leaked a number under
`withheld_by_carrier` would be a claim about a caller nobody made.

HARD RULE 6: the number is carried into a field and never into a log line.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from apps.api.db.session import tenant_session
from calevate_shared.events import CallEvent
from calevate_shared.worker_api import ObservationBatch
from sqlalchemy import text
from tests.voice_worker_pipeline_test import RecordingSink, make_config
from tests.worker_api_harness import (
    call_ref,
    declare_pipecat_engine,
    published_agent,
    worker_client,
)
from voice_worker.carrier import CallerIdentity
from voice_worker.pipeline import NormalizedEventBoundary

CALLER = "+919812345672"


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield from declare_pipecat_engine(monkeypatch)


async def one_event(caller: CallerIdentity | None, direction: str) -> CallEvent:
    sink = RecordingSink()
    boundary = NormalizedEventBoundary(
        config=make_config(direction=direction), sink=sink, caller=caller
    )
    await boundary.call_started()
    return sink.events[0]


@pytest.mark.asyncio
async def test_a_known_caller_is_stamped_on_the_event_as_the_calling_party() -> None:
    """The real `CallerIdentity`, matched structurally by `CallerIdentityLike`.

    Using the carrier's own type rather than a stub is the point of the test: the Protocol
    exists to avoid a `pipeline` -> `carrier` import cycle, and a stub shaped to the
    Protocol would prove only that the Protocol matches itself.
    """
    identity = CallerIdentity(state="known", ground="read from the handshake", e164=CALLER)
    event = await one_event(identity, "inbound")
    assert event.from_e164 == CALLER
    assert event.to_e164 is None


@pytest.mark.asyncio
async def test_the_same_person_is_the_dialled_party_on_an_outbound_call() -> None:
    """Putting it on the wrong end would suppress, remember and erase against our own
    header — `workers/optout` and `workers/callbacks._subject` choose by direction for
    exactly this reason, and the server's `_subject` reads it back the same way."""
    identity = CallerIdentity(state="known", ground="read from the handshake", e164=CALLER)
    event = await one_event(identity, "outbound")
    assert event.to_e164 == CALLER
    assert event.from_e164 is None


@pytest.mark.parametrize("state", ["withheld_by_carrier", "unparsed_by_client", "not_read"])
@pytest.mark.asyncio
async def test_no_state_but_known_puts_a_number_on_the_wire(state: str) -> None:
    """Each of the three means we do NOT have a number, for a different reason. None of them
    is a number, and inventing one would file a lead against the wrong person."""
    identity = CallerIdentity(state=state, ground="test", e164=CALLER)  # type: ignore[arg-type]
    event = await one_event(identity, "inbound")
    assert event.from_e164 is None
    assert event.to_e164 is None


@pytest.mark.asyncio
async def test_a_call_with_no_identity_at_all_is_an_ordinary_call() -> None:
    """`None` is the same as `not_read` and is what a local run, a replay or a test gets."""
    event = await one_event(None, "inbound")
    assert event.from_e164 is None


@pytest.mark.rls
@pytest.mark.asyncio
async def test_the_party_on_an_event_reaches_the_column_when_the_batch_names_none(
    worker_token: None,
) -> None:
    """THE SERVER HALF. The batch's own fields stay the contract; the events are a FALLBACK.

    They are the same session fact by construction — the boundary stamps every event from
    the one `CallerIdentity` the handshake produced — so reading it off there is not a
    guess, and it closes the hop without a second writer and without a migration while
    `sink.py` catches up.
    """
    tenant_id, agent_id, _ref = await published_agent()
    call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        await api.post_observations(
            ref,
            ObservationBatch(
                agent_id=agent_id,
                direction="inbound",
                # THE BATCH NAMES NOBODY — which is what `sink.py` sends today.
                from_e164=None,
                events=[
                    CallEvent(
                        call_id=call_id,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        direction="inbound",
                        status="in_progress",
                        engine="pipecat",
                        from_e164=CALLER,
                    )
                ],
            ),
        )
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT from_e164 FROM calls WHERE engine_call_id = :r"), {"r": ref}
            )
        ).first()
    assert row is not None and row[0] == CALLER


@pytest.mark.rls
@pytest.mark.asyncio
async def test_the_batch_still_wins_when_it_names_one(worker_token: None) -> None:
    """The fallback must not become a second source: the day `sink.py` sets the field, the
    batch is what is read and the events are not consulted."""
    tenant_id, agent_id, _ref = await published_agent()
    call_id, ref = call_ref(tenant_id)
    other = "+919812345673"
    async with worker_client() as api:
        await api.post_observations(
            ref,
            ObservationBatch(
                agent_id=agent_id,
                direction="inbound",
                from_e164=CALLER,
                events=[
                    CallEvent(
                        call_id=call_id,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        direction="inbound",
                        status="in_progress",
                        engine="pipecat",
                        from_e164=other,
                    )
                ],
            ),
        )
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT from_e164 FROM calls WHERE engine_call_id = :r"), {"r": ref}
            )
        ).first()
    assert row is not None and row[0] == CALLER


@pytest.mark.rls
@pytest.mark.asyncio
async def test_a_call_nobody_could_identify_still_settles_with_a_null_column(
    worker_token: None,
) -> None:
    """Plivo today: our pinned client's branch writes only `streamId`/`callId`
    (`pipecat/runner/utils.py:257-262`), so the state is `unparsed_by_client` and the column
    is NULL — an UNKNOWN about what the carrier sent, not a finding that it sent nothing.
    Every reader tolerates the NULL; what was missing was anything able to say why."""
    tenant_id, agent_id, _ref = await published_agent()
    call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        await api.post_observations(
            ref,
            ObservationBatch(
                agent_id=agent_id,
                direction="inbound",
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
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT from_e164, to_e164 FROM calls WHERE engine_call_id = :r"),
                {"r": ref},
            )
        ).first()
    assert row is not None and row[0] is None and row[1] is None


def test_the_carriers_own_type_satisfies_the_pipelines_protocol() -> None:
    """The structural match, asserted once and explicitly, so a field renamed in `carrier.py`
    fails here rather than silently leaving every event's party unset."""
    identity = CallerIdentity(state="known", ground="g", e164=CALLER)
    assert (identity.state, identity.ground, identity.e164, identity.is_known) == (
        "known",
        "g",
        CALLER,
        True,
    )


def test_a_carrier_state_this_repo_does_not_know_is_refused_rather_than_sent() -> None:
    """The wire vocabulary is closed (`CallerIdentityState`). Pydantic validates it on the
    way into `CallerIdentityIn`, so a fifth state invented anywhere is a 422 at the edge
    rather than a string echoed into an operator's triage."""
    from calevate_shared.worker_api import CallerIdentityIn
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CallerIdentityIn(state="probably_fine")  # type: ignore[arg-type]
