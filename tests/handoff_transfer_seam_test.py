"""Putting a live caller through to a person: the seam, its refusals and its one honest path.

Every case here is a state a CALLER can be in, and the property under test is always the
same one: what the agent is allowed to say next. A seam that placed no leg and let the
agent say "putting you through" would pass a status-code test and fail the only rule that
matters (hard rule 5).

WHAT IS DELIBERATELY PROVEN AGAINST THE IN-HOUSE ADAPTER. No carrier's transfer contract
is readable from this environment (`agents/transfer_providers/plivo.py`), so without
`FakeTransfers` the whole ladder — the fail-closed order, the caller-ID rule, the whisper,
the attempt row, the four unsuccessful endings and the degradation to a call-back — would
be code nothing has ever executed, on a product where no real call has ever been placed.

SHARED DATABASE DISCIPLINE: every organisation is minted here, every assertion is scoped
to ids this module created, and nothing counts rows globally.

Run: uv run pytest -q tests/handoff_transfer_seam_test.py
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.handoff import _UNAVAILABLE_REASONS, MAX_BRIEF_CHARS, spec_for
from apps.api.agents.handoff_execution import (
    ACCEPT_KEY,
    AGENT_UNKNOWN,
    ALREADY_HANDED_OVER,
    CARRIER_REFUSED,
    HANDOFF_DEGRADED_SAY,
    MAX_WHISPER_ABOUT,
    NO_PRESENTABLE_CLI,
    OUTCOME_ARRIVES_LATE,
    OUTCOME_UNREPORTABLE,
    HandoffPlacement,
    compose_whisper,
    place_handoff,
)
from apps.api.agents.transfer_providers import (
    NOT_OUR_CARRIER_LEG,
    PLATFORM_CANNOT_TRANSFER,
    PROVIDER_CONTRACT_UNVERIFIED,
    PROVIDER_NOT_LICENSED,
    CallTransferProvider,
    TransferContractUnverifiedError,
    TransferRefusedError,
    TransferRequest,
    TransferStarted,
    available_transfer,
    registry,
    transfer_blocked_reason,
)
from apps.api.agents.transfer_providers.fake import FakeTransfers
from apps.api.agents.transfer_providers.plivo import PlivoTransfers
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.fake import (
    DEFAULT_FAKE_CAPABILITIES,
    OWNED_RUNTIME_CAPABILITIES,
    FakeEngine,
)
from apps.api.engine.pipecat import PipecatEngine
from apps.api.worker.tools import ENGINE_CANNOT_TRANSFER, request_handoff
from calevate_shared.engine import (
    EngineCapabilities,
    HandoffSpec,
    VoiceEngine,
    pipecat_call_ref,
)
from calevate_shared.worker_api import HandoffToolIn
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.worker_api_harness import declare_pipecat_engine

pytestmark = pytest.mark.asyncio

#: The client's own registered header. The second leg must present THIS and never the
#: caller's number.
OUR_NUMBER = "+919000000001"
#: The person on the roster.
STAFF = "+919812345601"
#: Whoever rang in.
CALLER = "+919812345699"


def owned_runtime_engine() -> VoiceEngine:
    """The fake engine wearing the hosting shape this seam exists for.

    `OWNED_RUNTIME_CAPABILITIES` is the fixture that declares `agent_hosting=
    "owned_runtime"`, which is what makes the second leg ours to place, and the registry
    maps this engine's name onto the in-house adapter.
    """
    return FakeEngine(capabilities=OWNED_RUNTIME_CAPABILITIES)


def _without_in_call_handoff(capabilities: EngineCapabilities) -> EngineCapabilities:
    """The same engine with its own in-call handover taken away — the shape `pipecat`
    really has, and the one where our seam is the only mechanism left."""
    return capabilities.model_copy(update={"in_call_handoff": False})


# ---------------------------------------------------------------- the registry, closed


async def test_an_engine_that_holds_the_call_is_not_this_seams_business() -> None:
    """A rented control plane runs its own handover from a destination fixed at publish.
    Two mechanisms for one caller is the "one way per problem" defect with somebody on the
    line, so the seam answers that the leg is not ours rather than placing a second one."""
    capability = available_transfer(FakeEngine(capabilities=DEFAULT_FAKE_CAPABILITIES))
    assert not capability.available
    assert capability.reason == NOT_OUR_CARRIER_LEG


async def test_the_real_owned_runtime_has_no_transfer_because_nobody_read_the_carriers_docs() -> (
    None
):
    """The state of every deployment today, and the whole reason this seam exists. It is
    the adapter's own `contract_verified` that refuses — not a missing credential, not a
    flag somebody forgot."""
    capability = available_transfer(PipecatEngine())
    assert not capability.available
    assert capability.reason == PROVIDER_CONTRACT_UNVERIFIED
    assert PlivoTransfers().contract_verified is False


async def test_the_in_house_adapter_is_not_selectable_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It places no leg. Selecting it on a real deployment would answer `bridged` to a
    caller whose phone is connected to nobody — the exact state accept-before-bridge
    exists to make unreachable, arriving through the configuration instead of the wire."""
    monkeypatch.setattr(get_settings(), "app_env", "prod", raising=False)
    capability = available_transfer(owned_runtime_engine())
    assert not capability.available
    assert capability.reason == PROVIDER_NOT_LICENSED


async def test_the_licence_check_runs_before_the_contract_check() -> None:
    """ORDERING, not coincidence: the in-house adapter's contract IS verified (it is
    ours), so if the ladder asked that first it would hand a production deployment a
    provider that rings nobody. The licence rung has to come first or it never fires."""
    assert FakeTransfers().contract_verified is True
    assert available_transfer(owned_runtime_engine()).available is True


async def test_a_carrier_with_no_adapter_at_all_is_a_refusal_and_not_a_crash() -> None:
    """D-05 puts Exotel in this product's future and nobody has written a transfer for it.
    A carrier reaching the builder with no adapter must name what it would take rather
    than raise something a client's screen cannot render."""
    with pytest.raises(TransferContractUnverifiedError, match="exotel"):
        registry._build("exotel")


async def test_the_unimplemented_adapter_raises_rather_than_answering_quietly() -> None:
    """A carrier adapter that returned a polite failure would let a caller treat the seam
    as working-and-unlucky. It is neither, and the difference is the whole of hard rule 11
    on this path."""
    with pytest.raises(TransferContractUnverifiedError, match="egress-blocked"):
        await PlivoTransfers().start_transfer(
            TransferRequest(
                call_ref="c",
                to_e164=STAFF,
                present_as=OUR_NUMBER,
                whisper="w",
                accept_key=ACCEPT_KEY,
                ring_timeout_s=1,
                whisper_timeout_s=1,
            )
        )


async def test_the_platform_gate_and_the_seam_answer_different_questions() -> None:
    """`transfer_blocked_reason` asks whether a caller can reach a person by ANY route —
    the publish path's and the client screen's question — so an engine with its own
    in-call handover passes it while the seam still declines to be the mechanism."""
    assert transfer_blocked_reason(FakeEngine(capabilities=DEFAULT_FAKE_CAPABILITIES)) is None
    assert transfer_blocked_reason(PipecatEngine()) == PLATFORM_CANNOT_TRANSFER
    stripped = FakeEngine(capabilities=_without_in_call_handoff(OWNED_RUNTIME_CAPABILITIES))
    # Our seam IS available on this shape, so the platform is not blocked.
    assert transfer_blocked_reason(stripped) is None


async def test_the_client_is_given_a_sentence_for_the_platform_reason() -> None:
    """`PLATFORM_CANNOT_TRANSFER` reaches a client's own handover screen, so it owes them
    a sentence and a next step — even when the next step is "nothing, this is ours"."""
    assert PLATFORM_CANNOT_TRANSFER in _UNAVAILABLE_REASONS
    assert "call-back" in _UNAVAILABLE_REASONS[PLATFORM_CANNOT_TRANSFER]


# ------------------------------------------------------------------------ the whisper


async def test_the_whisper_names_the_caller_the_person_and_the_key() -> None:
    """The four things it must say in one breath. A whisper missing the key is a phone
    ringing with nothing to press; missing the caller is a person deciding on nothing."""
    whisper = compose_whisper(
        language="en-IN", label="Priya", caller_e164=CALLER, about="billing dispute"
    )
    assert "Priya" in whisper
    assert CALLER in whisper
    assert "billing dispute" in whisper
    assert f"Press {ACCEPT_KEY}" in whisper


async def test_a_whisper_with_no_reason_still_says_what_the_call_is() -> None:
    """The model may give nothing. An empty subject leaves somebody deciding whether to
    accept a call about nothing at all."""
    whisper = compose_whisper(language="en-IN", label="Ravi", caller_e164=CALLER, about=None)
    assert "asked to speak to a person" in whisper


async def test_a_withheld_caller_is_named_as_withheld_rather_than_left_blank() -> None:
    assert "withheld" in compose_whisper(
        language="en-IN", label="Ravi", caller_e164=None, about=None
    )


async def test_model_prose_in_the_whisper_is_bounded() -> None:
    """It is SPOKEN to somebody holding a ringing phone while a caller waits, so an
    unbounded model output is an unbounded delay before the key can be pressed."""
    whisper = compose_whisper(language="en-IN", label="Ravi", caller_e164=CALLER, about="x" * 5_000)
    assert "x" * MAX_WHISPER_ABOUT in whisper
    assert "x" * (MAX_WHISPER_ABOUT + 1) not in whisper


async def test_an_unknown_language_falls_back_rather_than_failing() -> None:
    """A template rendered in a language the business does not speak is worse than the
    lingua franca; a KeyError mid-call is worse than both."""
    assert "Press" in compose_whisper(
        language="fr-FR", label="Ravi", caller_e164=CALLER, about=None
    )


# -------------------------------------------------------- the in-house adapter's contract


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("whisper", "   "),
        ("accept_key", ""),
        ("to_e164", OUR_NUMBER),
        ("ring_timeout_s", 0),
        ("whisper_timeout_s", 0),
    ],
)
async def test_the_in_house_adapter_refuses_a_request_that_breaks_our_own_rules(
    field: str, value: object
) -> None:
    """It is not a yes-machine. Each of these is a mistake the FIRST carrier adapter could
    make, and this is the one adapter that can run to catch them."""
    base = {
        "call_ref": "c",
        "to_e164": STAFF,
        "present_as": OUR_NUMBER,
        "whisper": "hello",
        "accept_key": ACCEPT_KEY,
        "ring_timeout_s": 25,
        "whisper_timeout_s": 10,
    }
    with pytest.raises(TransferRefusedError):
        await FakeTransfers().start_transfer(TransferRequest(**{**base, field: value}))  # type: ignore[arg-type]


# ------------------------------------------------------------------ the seam, end to end


async def _org(
    *, with_number: bool = True, with_roster: bool = True
) -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Handover seam",
        slug=f"handover-seam-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        if with_roster:
            await session.execute(
                text(
                    "INSERT INTO agent_handoff_members "
                    "(id, tenant_id, agent_id, position, label, phone_e164) "
                    "VALUES (:id, :tid, :aid, 0, 'Priya', :phone)"
                ),
                {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "phone": STAFF},
            )
        # Handovers on, hours unset -> `is_after_hours` answers "unknown" for every day,
        # so the roster is only reachable with hours recorded. 24/7 is what a clinic that
        # wants its owner rung whenever the agent asks would set.
        await session.execute(
            text(
                "UPDATE agents SET handoff_enabled = true, business_hours = CAST(:h AS jsonb) "
                "WHERE id = :aid"
            ),
            {
                "aid": agent_id,
                "h": '{"mon":{"opens":"00:00","closes":"23:59"},'
                '"tue":{"opens":"00:00","closes":"23:59"},'
                '"wed":{"opens":"00:00","closes":"23:59"},'
                '"thu":{"opens":"00:00","closes":"23:59"},'
                '"fri":{"opens":"00:00","closes":"23:59"},'
                '"sat":{"opens":"00:00","closes":"23:59"},'
                '"sun":{"opens":"00:00","closes":"23:59"}}',
            },
        )
        if with_number:
            await session.execute(
                text(
                    "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                    "  dlt_status, activated_at) "
                    "VALUES (:id, :tid, :aid, :e164, 'standard', 'registered', :now)"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "e164": f"+9190000{uuid.uuid4().int % 100000:05d}",
                    "now": datetime.now(UTC),
                },
            )
    return tenant_id, agent_id


async def _place(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    engine: VoiceEngine | None = None,
    execution: str | None = None,
    outcome_reaches_agent: bool = True,
    about: str | None = "billing dispute",
) -> HandoffPlacement:
    async with tenant_session(tenant_id) as session:
        return await place_handoff(
            session,
            engine=engine or owned_runtime_engine(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            engine_call_id=execution or f"exec-{uuid.uuid4().hex[:10]}",
            caller_e164=CALLER,
            about=about,
            summary=None,
            outcome_reaches_agent=outcome_reaches_agent,
        )


async def _attempts(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list[tuple[object, ...]]:
    async with tenant_session(tenant_id) as session:
        return [
            tuple(row)
            for row in (
                await session.execute(
                    text(
                        "SELECT outcome, leg_duration_s, destination_e164, settled_at "
                        "FROM handoff_attempts WHERE agent_id = :aid ORDER BY started_at"
                    ),
                    {"aid": agent_id},
                )
            ).all()
        ]


async def test_a_handover_rings_the_person_on_duty_and_presents_our_own_number() -> None:
    """THE ONE SUCCESSFUL PATH, and the three things it must get right: who is dialled,
    what header that leg presents, and what the person hears before anyone is bridged.

    The presented header is the client's REGISTERED number and never the caller's:
    presenting a number we are not the subscriber of is CLI spoofing, and the caller's
    identity travels in the whisper instead, which is a private message to one person
    rather than a claim to the network.
    """
    tenant_id, agent_id = await _org()
    provider = FakeTransfers()
    engine = owned_runtime_engine()
    async with tenant_session(tenant_id) as session, _provider(provider):
        placement = await place_handoff(
            session,
            engine=engine,
            tenant_id=tenant_id,
            agent_id=agent_id,
            engine_call_id=f"exec-{uuid.uuid4().hex[:10]}",
            caller_e164=CALLER,
            about="billing dispute",
            summary="the caller has been charged twice",
            outcome_reaches_agent=True,
        )
    assert placement.placed
    assert placement.outcome == "bridged"
    assert "putting you through" in placement.say.lower()
    (request,) = provider.requests
    assert request.to_e164 == STAFF
    assert request.present_as != CALLER
    assert request.present_as.startswith("+9190000")
    assert CALLER in request.whisper
    assert "billing dispute" in request.whisper
    assert request.accept_key == ACCEPT_KEY
    assert [(o, d) for o, d, _n, _s in await _attempts(tenant_id, agent_id)] == [("connected", 42)]


async def test_a_declined_handover_is_recorded_as_unreached_and_told_truthfully() -> None:
    """The founder's condition: a person who saw the call and said no is not a dead end.
    The caller is told plainly and offered the call-back, and the client's screen carries
    the row so they can see it happened."""
    tenant_id, agent_id = await _org()
    async with _provider(FakeTransfers(outcome="declined")):
        placement = await _place(tenant_id, agent_id)
    assert placement.outcome == "declined"
    assert placement.placed
    assert placement.say == HANDOFF_DEGRADED_SAY, (
        "a leg nobody took must not license the sentence that promises a person"
    )
    rows = await _attempts(tenant_id, agent_id)
    assert [row[0] for row in rows] == ["unreached"]
    assert rows[0][3] is not None, "a settled row must carry its settled_at (the CHECK)"


async def test_a_carrier_that_refuses_leaves_no_row_pretending_to_be_in_progress() -> None:
    """The leg was claimed before it was placed, so a refusal has to close its own row —
    otherwise a client's screen shows a handover in progress for ever. `unknown` and not
    `unreached`: we could not place the leg, which is not evidence nobody would answer."""
    tenant_id, agent_id = await _org()
    async with _provider(_RefusingTransfers()):
        placement = await _place(tenant_id, agent_id)
    assert not placement.placed
    assert placement.reason == CARRIER_REFUSED
    assert placement.say == HANDOFF_DEGRADED_SAY
    assert [row[0] for row in await _attempts(tenant_id, agent_id)] == ["unknown"]


async def test_the_models_prose_is_redacted_before_the_row_or_the_whisper_carries_it() -> None:
    """The in-call tool path writes the same `handoff_attempts.reason`/`summary` columns the
    rented engine's job writes, and those columns hold REDACTED prose (SEC-COMP §4): a
    client reads them and the retention scrub assumes nothing rawer is there. A card number
    the caller read out must not reach the row, and must not be read aloud to staff."""
    tenant_id, agent_id = await _org()
    provider = FakeTransfers()
    card = "4111 1111 1111 1111"
    async with tenant_session(tenant_id) as session, _provider(provider):
        placement = await place_handoff(
            session,
            engine=owned_runtime_engine(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            engine_call_id=f"exec-{uuid.uuid4().hex[:10]}",
            caller_e164=CALLER,
            about=f"caller read out card {card} and wants the owner",
            summary="y" * (MAX_BRIEF_CHARS + 500),
            outcome_reaches_agent=True,
        )
    assert placement.placed
    (request,) = provider.requests
    assert "4111" not in request.whisper
    async with tenant_session(tenant_id) as session:
        reason, summary = (
            await session.execute(
                text("SELECT reason, summary FROM handoff_attempts WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
        ).one()
    assert reason is not None and "4111" not in reason
    assert summary == "y" * MAX_BRIEF_CHARS


async def test_one_conversation_hands_over_once_however_many_times_the_tool_is_called() -> None:
    """A retried tool call is the ordinary consequence of a timeout on a network the
    caller is waiting on. Without the claim-before-place order it would ring a second
    person."""
    tenant_id, agent_id = await _org()
    execution = f"exec-{uuid.uuid4().hex[:10]}"
    provider = FakeTransfers()
    async with _provider(provider):
        first = await _place(tenant_id, agent_id, execution=execution)
        second = await _place(tenant_id, agent_id, execution=execution)
    assert first.placed
    assert not second.placed
    assert second.reason == ALREADY_HANDED_OVER
    assert len(provider.requests) == 1
    assert len(await _attempts(tenant_id, agent_id)) == 1


async def test_a_platform_that_cannot_transfer_never_reads_the_roster() -> None:
    """FAIL-CLOSED ORDERING, and it is also a hard rule 6 property: on a deployment that
    can transfer nobody, a caller's escalation touches no staff member's mobile at all.
    The operator reason names the platform rather than the client's configuration."""
    tenant_id, agent_id = await _org()
    placement = await _place(tenant_id, agent_id, engine=PipecatEngine())
    assert not placement.placed
    assert placement.reason == PROVIDER_CONTRACT_UNVERIFIED
    assert placement.say == HANDOFF_DEGRADED_SAY
    assert await _attempts(tenant_id, agent_id) == []


async def test_a_caller_whose_agent_cannot_be_told_the_outcome_is_not_transferred() -> None:
    """The founder's own condition read strictly: a declined or unanswered handover has to
    come BACK to the agent. A leg placed by a caller that cannot carry the outcome is a
    caller bridged to a person while their agent apologises for failing."""
    tenant_id, agent_id = await _org()
    provider = FakeTransfers()
    async with _provider(provider):
        placement = await _place(tenant_id, agent_id, outcome_reaches_agent=False)
    assert not placement.placed
    assert placement.reason == OUTCOME_UNREPORTABLE
    assert provider.requests == []


async def test_no_registered_header_means_no_second_leg() -> None:
    """The second leg is an outbound call to somebody's mobile. With no number of the
    client's own to present, the only alternatives are the caller's number (spoofing) or
    nothing at all, so the handover degrades instead."""
    tenant_id, agent_id = await _org(with_number=False)
    async with _provider(FakeTransfers()):
        placement = await _place(tenant_id, agent_id)
    assert placement.reason == NO_PRESENTABLE_CLI
    assert await _attempts(tenant_id, agent_id) == []


async def test_an_empty_roster_degrades_with_the_clients_own_reason() -> None:
    """The five roster reasons are passed through unchanged, so the client's screen and
    this path cannot come to disagree about why nobody is available."""
    tenant_id, agent_id = await _org(with_roster=False)
    async with _provider(FakeTransfers()):
        placement = await _place(tenant_id, agent_id)
    assert placement.reason == "no_members"
    assert placement.reason in _UNAVAILABLE_REASONS


async def test_a_carrier_that_would_report_the_ending_later_places_nothing() -> None:
    """The caller's agent is holding a turn open. A carrier that acknowledges the request
    and reports the ending over its own callback leaves the agent with nothing to say for
    the whole whisper-and-accept cycle — so the leg is not placed, and the operator gets a
    reason that names the carrier's own shape rather than the client's configuration."""
    tenant_id, agent_id = await _org()
    provider = _LateTransfers()
    async with _provider(provider):
        placement = await _place(tenant_id, agent_id)
    assert not placement.placed
    assert placement.reason == OUTCOME_ARRIVES_LATE
    assert provider.requests == []
    assert await _attempts(tenant_id, agent_id) == []


async def test_a_leg_with_no_reported_ending_is_never_announced_as_connected() -> None:
    """The row stays at `started` — which is what `workers/handoff.settle_handoff` exists
    to close — and the caller is told nothing that assumes a person. An adapter that
    reports no ending must cost the caller a truthful apology, never a false promise."""
    tenant_id, agent_id = await _org()
    async with _provider(_SilentTransfers()):
        placement = await _place(tenant_id, agent_id)
    assert placement.placed
    assert placement.outcome is None
    assert placement.say == HANDOFF_DEGRADED_SAY
    rows = await _attempts(tenant_id, agent_id)
    assert [row[0] for row in rows] == ["started"]
    assert rows[0][3] is None


# ------------------------------------------------------------------------- hard rule 1


async def test_a_handover_cannot_be_placed_on_another_tenants_agent() -> None:
    """Cross-tenant zero rows, reached through the seam rather than through SQL. The agent
    read is RLS-scoped, so another tenant's agent id resolves to no agent at all — and no
    number of theirs is dialled, which is the outcome that matters."""
    first_tenant, first_agent = await _org()
    second_tenant, second_agent = await _org()
    provider = FakeTransfers()
    async with _provider(provider):
        placement = await _place(first_tenant, second_agent)
    assert not placement.placed
    assert placement.reason == AGENT_UNKNOWN
    assert provider.requests == []
    assert await _attempts(second_tenant, second_agent) == []
    async with tenant_session(second_tenant) as session:
        visible = (
            await session.execute(
                text("SELECT count(*) FROM handoff_attempts WHERE agent_id = :aid"),
                {"aid": first_agent},
            )
        ).scalar()
    assert visible == 0


# ------------------------------------------------------------------- the test's own tools


class _SilentTransfers(FakeTransfers):
    """An adapter that claims a synchronous ending and comes back without one — the shape
    a carrier adapter is most likely to get wrong."""

    async def start_transfer(self, request: TransferRequest) -> TransferStarted:
        self.requests.append(request)
        return TransferStarted(provider_ref="fake-silent", outcome=None)


class _LateTransfers(FakeTransfers):
    """A carrier whose ending arrives over its own callback — the ordinary shape, and the
    one the in-call path cannot use."""

    @property
    def settles_synchronously(self) -> bool:
        return False


class _RefusingTransfers(FakeTransfers):
    """A carrier with an account problem rather than an unread contract — the two are
    separate exceptions because their remedies are opposite."""

    async def start_transfer(self, request: TransferRequest) -> TransferStarted:
        raise TransferRefusedError("no balance on the account")


@contextlib.asynccontextmanager
async def _provider(provider: CallTransferProvider) -> AsyncIterator[None]:
    """Select this adapter for the duration, through the registry's own builder.

    The registry decides the carrier from the ENGINE (one carrier per answer path), so a
    test that wants a dictated ending substitutes the adapter at the one place the registry
    builds one, rather than reaching past the ladder it is here to exercise.
    """
    original = registry._build
    registry._build = lambda carrier: provider if carrier == "fake" else original(carrier)
    try:
        yield
    finally:
        registry._build = original


# --------------------------------------------------------------- the in-call tool's wire


async def test_the_tool_reason_is_the_word_the_worker_actually_matches() -> None:
    """TWO SPELLINGS OF ONE WORD, PINNED. The worker passes this reason through to the
    model, and matches it to recover the narrow sentence from a server old enough to
    answer only `not_transferred` (`call_tools._ENGINE_CANNOT_TRANSFER`); that service may
    not import `apps.api` (hard rule 3), so the agreement is asserted here or nowhere.
    `tests/handoff_tool_test.py` pins `HANDOFF_JOB` the same way for the same reason."""
    from voice_worker.call_tools import _ENGINE_CANNOT_TRANSFER

    assert ENGINE_CANNOT_TRANSFER == _ENGINE_CANNOT_TRANSFER


async def test_the_tool_says_connected_only_when_a_person_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE ONE WORD THAT LICENSES "I AM PUTTING YOU THROUGH", AND THE FOUR THAT DO NOT.

    `voice_worker/call_tools.HANDOFF_GUIDANCE` keys the agent's instruction on this field
    rather than on the prose beside it, so a status that over-claimed would put "a person
    has accepted this call" in front of a caller whose phone is connected to nobody. The
    four unsuccessful endings collapse to one word for the caller and stay four on the
    client's own screen.
    """
    tenant_id, agent_id = await _org()
    ref = pipecat_call_ref(tenant_id, f"call-{uuid.uuid4().hex[:10]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, direction, status, "
                "  engine_call_id, from_e164) "
                "VALUES (:id, :tid, :aid, 'inbound', 'in_progress', :ref, :from)"
            ),
            {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "ref": ref, "from": CALLER},
        )

    async def answering(placement: HandoffPlacement) -> object:
        async def _placed(*_a: object, **_k: object) -> HandoffPlacement:
            return placement

        monkeypatch.setattr("apps.api.worker.tools.place_handoff", _placed)
        return await request_handoff(ref, HandoffToolIn(reason="a person please", summary=None))

    connected = await answering(
        HandoffPlacement(
            provider_ref="fake-1", outcome="bridged", reason=None, say="connecting you now"
        )
    )
    assert connected.status == "connected"

    declined = await answering(
        HandoffPlacement(
            provider_ref="fake-1",
            outcome="declined",
            reason=None,
            say=HANDOFF_DEGRADED_SAY,
        )
    )
    assert declined.status == "no_answer"
    assert "must not say you are transferring them" in declined.say

    off_duty = await answering(
        HandoffPlacement(
            provider_ref=None, outcome=None, reason="outside_hours", say=HANDOFF_DEGRADED_SAY
        )
    )
    assert off_duty.status == "nobody_on_duty"
    assert off_duty.reason == "outside_hours"

    unbuilt = await answering(
        HandoffPlacement(
            provider_ref=None,
            outcome=None,
            reason=PROVIDER_CONTRACT_UNVERIFIED,
            say=HANDOFF_DEGRADED_SAY,
        )
    )
    assert unbuilt.status == "not_available"
    assert unbuilt.reason == ENGINE_CANNOT_TRANSFER


# --------------------------------------------------- the publish refusal, reconsidered


@pytest.fixture
def pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """This deployment IS the owned runtime, which is what `spec_for` reads `get_engine()`
    for. Scoped to the one test that needs it — `worker_api_harness` argues why this is a
    helper rather than a conftest fixture."""
    yield from declare_pipecat_engine(monkeypatch)


async def test_a_roster_no_longer_makes_an_agent_unpublishable(
    pipecat_deployment: None,
) -> None:
    """THE BEHAVIOUR THAT CHANGED, AND THE ONE THAT DID NOT.

    Until now a client with a handover list could not publish their agent on our own
    runtime at all: `spec_for` resolved a destination, the adapter refused the config by
    name, and the whole publish failed. That refusal was correct while there was no
    transfer and no honest degradation — there is one now, so the publish resolves NO
    destination and the client is told which of the two situations they are in.

    Nothing about the caller-facing promise moved: the in-call tool answers
    `not_available`, and the adapter still refuses a config that carries a destination (the
    test below).
    """
    tenant_id, agent_id = await _org()
    async with tenant_session(tenant_id) as session:
        agent = dict(
            (
                await session.execute(
                    text(
                        "SELECT id, handoff_enabled, handoff_trigger, business_hours, "
                        "  language_primary FROM agents WHERE id = :aid"
                    ),
                    {"aid": agent_id},
                )
            )
            .mappings()
            .one()
        )
        spec, duty = await spec_for(session, agent)
    assert spec is None, "a destination on a platform that cannot dial it is a lie"
    assert duty.member is None
    assert duty.reason == PLATFORM_CANNOT_TRANSFER
    assert duty.remediation is not None


async def test_the_adapter_still_refuses_a_config_that_carries_a_destination() -> None:
    """THE BACKSTOP, UNCHANGED. `spec_for` is what stops a destination reaching this
    engine, and an adapter that trusted its callers would be one edit away from accepting
    a number nothing can dial. Dropping it silently is what D-533 wrote this refusal
    against."""
    from tests.voice_worker_session_test import _agent_config

    tenant_id, agent_id = await _org()
    config = _agent_config(tenant_id, agent_id).model_copy(
        update={
            "handoff": HandoffSpec(
                destination_e164=STAFF, trigger="they ask for a person", spoken_line="hold"
            )
        }
    )
    with pytest.raises(ProblemError):
        await PipecatEngine().create_agent(config)
