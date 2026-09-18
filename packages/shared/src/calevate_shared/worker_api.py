"""The worker→API wire models (D-621), imported by BOTH sides so they cannot disagree.

**WHY THESE LIVE IN `packages/shared` AND NOT IN EITHER END.** `apps/voice-worker` runs on
Pipecat Cloud and `apps/api` runs on the VPS; between them is the only network hop in this
product where a field name is a deployment contract rather than a function call. Two
declarations of one JSON body is the "one way per problem" defect with a wire between them:
they agree on the day they are written and diverge on the day one is edited, and the failure
is a 422 on a live call rather than a red test. One module, two importers, no drift.

This is the same argument `calevate_shared.events` already rests on — `CallEvent` and
`TranscriptTurn` are shared for exactly this reason, and the batch below simply carries
lists of them rather than restating their fields.

**WHAT THIS CONTRACT IS SHAPED BY — one rule, from `docs/evidence/worker-http-contract.md`:**

    THE WORKER SENDS WHAT IT OBSERVED. THE SERVER DECIDES WHAT THAT MEANS.

The worker is compute on a third party's infrastructure. It reports quantities, turns and
statuses. It does not compute money, hold a rate card, resolve a tenant, or name a row id.
Everything below is readable as an answer to "what did this container witness?", and nothing
below is an instruction to write a particular row. That is what lets `PLATFORM_KEK` and the
database credential stay on our side of the wall (§12.5 gate 6, option 3).

Two consequences that look like omissions and are the design:

* **No `calls.id` anywhere.** The worker knows its own `engine_call_id`
  (`pipecat_call_ref(tenant, call_id)`) and the server resolves it under RLS. A worker that
  could name a row id could name somebody else's.
* **No money in the request.** `unit_cost_inr` and `total_inr` are absent by construction,
  not merely optional. Today the worker cannot price anything anyway — `CallMeter.
  metered_rows` raises on a missing CDR before it reaches a rate (`meter.py:686-704`,
  BLOCKER-1) — and hard rule 7 says the figure that reaches `unit_cost_paid` is an attested
  one. The server holds the rate card; the worker sends QUANTITIES.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from calevate_shared.engine import ModelConfig
from calevate_shared.events import CallDirection, CallEvent, TranscriptTurn

#: Every model here forbids unknown fields. A body carrying a key the server does not know
#: is a client built against a different contract, and answering it 422 at the edge is how
#: that is found on the first call rather than in a column nobody filled.
_STRICT = ConfigDict(extra="forbid")

#: Ceilings on every list a client can grow. `check_list_bounds` governs RESPONSES and
#: correctly does not reach these, but its argument does: *"what needs a ceiling is a list
#: whose length is CALLER-CONTROLLED"*, and from the server's side that is exactly what a
#: request body is. The client here is a container on a third party's infrastructure holding
#: a token; "our own worker would never send a million turns" is a fact about the code we
#: ship today, not about what can arrive on the socket.
#:
#: Both are far above any legitimate batch — `PIPECAT_WORKER_TURN_BATCH_SIZE` defaults to 8
#: (D-620) — so no real flush is ever refused. They exist so that the failure mode of a
#: malformed or hostile body is a 422 at the edge rather than a 1 vCPU host materialising
#: the list in Python and then looping INSERTs over it.
MAX_TURNS_PER_BATCH: Final = 500
MAX_EVENTS_PER_BATCH: Final = 50

#: A settlement carries one quantity per metered leg, and §1.3 declares a handful
#: (`meter.MeteredLeg`). ⚠ **DELIBERATELY NOT `len(MeteredLeg)` AND NOT THAT COUNT WRITTEN
#: OUT.** `packages/shared` may not import `apps/` — that is a kept import contract — so the
#: enum is unreachable from here, and restating its size as a literal would be a number that
#: drifts silently the day a sixth leg is declared (hard rule 4's defect class).
#:
#: So this is a MEMORY BOUND and not a claim about how many legs exist: comfortably above
#: any real settlement, low enough that a malformed body is refused at the edge. The
#: all-or-nothing rule over the real leg set is enforced where the legs are actually known —
#: `worker/service`, against `MeteredLeg` itself.
MAX_QUANTITIES: Final = 32


class WorkerSessionOut(BaseModel):
    """What one published agent is, answered for a worker about to take its call.

    Replaces the SELECT in `voice_worker/config.py`, field for field. `tenant_id` and
    `agent_id` are ANSWERED rather than asked for: the worker presents an
    `engine_agent_ref` and the server resolves it, which is the same direction
    `compliance/caller_data_routes.py` already resolves that ref in.
    """

    model_config = _STRICT

    tenant_id: UUID
    agent_id: UUID
    agent_config_version_id: UUID
    system_prompt: str
    #: The control plane's own hash. The worker RECOMPUTES it rather than trusting it —
    #: that disagreement is §1.1's attestation and it must survive the transport.
    prompt_sha256: str
    models: ModelConfig
    engine_agent_ref: str | None = None
    language: str | None = None
    greet_first: bool = True
    knowledge_pack_sha256: str | None = None
    #: Hard rule 5's sentence, carried so the worker can prove it is in the prompt it runs.
    ai_disclosure_line: str | None = None


class ObservationBatch(BaseModel):
    """What the container witnessed since the last batch: statuses and spoken turns.

    ONE BODY FOR BOTH because they are one fact — what happened on this call — and because
    the server has to order them anyway: a turn may arrive before the status that opened the
    call (Pipecat dispatches every handler as its own task), and the existing sink already
    converges both on one call-row upsert for exactly that reason.

    Empty lists are legal. A flush with nothing in it is a no-op the client is allowed to
    send rather than a condition it must check for.

    ⚠ **`agent_id` AND `direction` ARE ON THE BATCH AND NOT ONLY ON THE EVENTS, AND THAT
    WAS A CORRECTION RATHER THAN A CHOICE (16 Sep 2026).** `TranscriptTurn` carries neither
    and `CallEvent` declares `agent_id` nullable, so the FIRST batch of a call — which is
    routinely a flush of turns, because Pipecat dispatches every handler as its own task and
    a turn can beat the event that opened the call — named nothing the server could mint a
    `calls` row from. The in-process sink never had this problem: it held the session's four
    ids. They are session facts, so they travel with the session's batch; deriving them from
    whichever event happened to be in it would be a guess on a FORCE-RLS'd row's
    `agent_id`.
    """

    model_config = _STRICT

    #: Whose agent this call is running. The server refuses a batch whose events name a
    #: different one (`worker/service._refuse_identity`).
    agent_id: UUID
    direction: CallDirection
    #: THE TWO PARTIES, AND TODAY NOTHING CAN FILL THEM ON PLIVO — WHICH IS THE POINT.
    #:
    #: `calls.from_e164` is not decoration: `leads.phone_e164` is NOT NULL and the post-call
    #: pipeline derives it from this field on inbound (`workers/pipeline.py:1903,1968`);
    #: caller memory filters on `c.from_e164 IS NOT NULL` as a hard condition
    #: (`workers/caller_memory_distil.py:206`); and a DPDP erasure takes its SUBJECT from the
    #: same field (`pipeline.py:1600`). A call with no number files no lead, grows no memory,
    #: and has nothing to erase against.
    #:
    #: On the Bolna leg these rode `ExecutionSnapshot`, the POLLER's record (TRD §5:
    #: "payloads as hints, poller as truth"), which is why `CallEvent` never carried them.
    #: Pipecat has no poller — this contract IS the snapshot — so they belong here, as
    #: session facts, beside `agent_id` and `direction` and for the same reason.
    #:
    #: ⚠ **THE PRODUCER IS UNBUILT AND IS A NAMED GATE, NOT AN OVERSIGHT** (DEPLOYMENT
    #: §12.5 gate 9). Pipecat's Plivo handshake parses neither party (`runner/utils.py:
    #: 250-262`, and `voice_worker/carrier.PlivoHandshake` refuses to model what is always
    #: `None`); the outbound dial is `OUTBOUND_DIAL_UNKNOWN`; and the CDR read that would
    #: supply them waits on a carrier decision. They are declared here because the SERVER's
    #: half must exist before any producer can be wired to it — and because the next carrier
    #: may simply hand them over: Pipecat's Exotel handshake populates both (`ExotelCallData`,
    #: `runner/utils.py:283`). Absent, they leave the column NULL, which every reader above
    #: already tolerates.
    from_e164: str | None = None
    to_e164: str | None = None
    events: list[CallEvent] = Field(default_factory=list, max_length=MAX_EVENTS_PER_BATCH)
    turns: list[TranscriptTurn] = Field(default_factory=list, max_length=MAX_TURNS_PER_BATCH)


class ObservationsOut(BaseModel):
    """What the server did with a batch, in numbers the client can log but not act on.

    `turns_written` is smaller than the batch when a retry re-sent turns the server already
    had — which is the idempotency working, not an error, and the client must not treat the
    difference as loss.
    """

    model_config = _STRICT

    turns_written: int
    turns_already_present: int
    status: str | None = None


#: The widest quantity any leg of one call can honestly report, and the narrowest bound that
#: cannot refuse a real call. A call is capped at `CALL_CAP_MAX_S`; the largest unit any leg
#: counts in is seconds of audio, so six figures is already several orders of magnitude of
#: headroom. The point is not the exact number — it is that SOME number exists.
MAX_METERED_QTY: Final = Decimal("1000000")

#: Prose the server stores verbatim. `call_metering_refusals.detail`/`.remediation` are
#: `TEXT`, and the table is append-only, so an unbounded string is a permanent one.
MAX_REFUSAL_TEXT: Final = 500

#: An identifier the server matches or stores: a leg name, a unit type, a machine code.
MAX_IDENTIFIER: Final = 64

#: The five legs a call can be metered or refused on.
#:
#: ⚠ **THIS LIVES IN THE WIRE MODULE AND THE WORKER'S `MeteredLeg` IS DERIVED FROM IT
#: (18 Sep 2026).** The docstring above used to say the vocabulary was "enforced where the
#: legs are actually known — `worker/service`, against `MeteredLeg` itself", and no such
#: check existed: the enum lived in `apps/voice-worker`, which `apps/api` cannot import, so
#: any string the client sent was echoed into `call_metering_refusals.leg`. A shared
#: contract belongs in the shared contract; a claim that two deployables agree has to be
#: something one of them can actually check.
MeteredLegName = Literal["carrier", "runtime", "stt", "tts", "llm"]

#: The same five as a set, for a caller that needs membership rather than a type.
METERED_LEGS: Final[frozenset[str]] = frozenset(get_args(MeteredLegName))


class MeteredQuantity(BaseModel):
    """One leg's measured quantity, with NO price attached.

    `unit_cost_inr` and `total_inr` are deliberately absent: see this module's docstring.
    The server multiplies, because the server is what holds an attested rate.

    ⚠ **`qty` IS BOUNDED AND SIGNED, AND IT USED TO BE NEITHER (18 Sep 2026).** The server
    refuses to take a PRICE from a worker — that was the whole point of the split — and then
    multiplied whatever magnitude it was handed by an attested rate and INSERTed the product
    into `usage_events`, which hard rule 4 makes INSERT-only. `qty: Decimal` with no `ge`
    accepted `-99999999`, so one holder of the worker token could mint a permanent
    self-issued credit that nothing but a compensating entry could answer; `1e50` was an
    unpayable charge by the same door. `allow_inf_nan=False` because a NaN in a NUMERIC
    column poisons every SUM taken over that tenant's usage for ever.

    A refund is a compensating entry an operator makes. It is not a quantity a container on
    somebody else's infrastructure reports.
    """

    model_config = _STRICT

    leg: MeteredLegName
    unit_type: str = Field(max_length=MAX_IDENTIFIER)
    qty: Decimal = Field(ge=0, le=MAX_METERED_QTY, allow_inf_nan=False)
    #: ⚠ **BOUNDED, AND THE SERVER DECIDES WHICH KEYS SURVIVE.** `worker/service._write_usage`
    #: is the one reader; what it persists is an allow-list, because `meta->>'tts_tier'` is
    #: the rung every client-facing split reads and `meta->>'model'` chooses an LLM rate —
    #: neither is a thing a vendor-hosted container gets to assert about our money.
    meta: dict[str, str] = Field(default_factory=dict, max_length=16)


class SettlementRefusal(BaseModel):
    """Why a leg could not be metered — the shape `call_metering_refusals` already stores.

    A refusal is a FACT the worker observed (it could not read a quantity), which is why it
    travels in the same direction as everything else here. Today it is also the only thing
    that travels: with no CDR there is no priced leg at all (BLOCKER-1).
    """

    model_config = _STRICT

    #: ⚠ **BOUNDED SINCE 18 Sep 2026.** `worker/service` carried a comment calling these
    #: "OUR OWN PROSE. Every refusal string is authored in this repository" — true of the
    #: client we ship and not enforced of any client, while the strings arrive over HTTP and
    #: land in an append-only table as `TEXT`.
    leg: MeteredLegName
    code: str = Field(max_length=MAX_IDENTIFIER)
    detail: str = Field(max_length=MAX_REFUSAL_TEXT)
    remediation: str | None = Field(default=None, max_length=MAX_REFUSAL_TEXT)


class SettlementRequest(BaseModel):
    """The terminal write, and the one that carries D-607.

    **A REFUSAL OR QUANTITIES, NEVER BOTH**, mirroring `sink.settle`'s own branch:
    `metered_rows` is all-or-nothing by design ("THERE IS NO PARTIAL SETTLEMENT"), so a body
    offering three priced legs and one refusal would be a shape the ledger cannot hold. The
    server validates the exclusivity rather than trusting it, because a client is a thing on
    somebody else's infrastructure.

    ⚠ **NEITHER IS LEGAL AND THIS PARAGRAPH USED TO SAY IT WAS NOT.** Both empty is the third
    state `meter.py` distinguishes deliberately — a session that transcribed and synthesised
    nothing has no leg to price, which is not a leg nobody can price — and it still has to
    settle, because the outbox row that starts the post-call pipeline rides the settlement
    (D-607).

    The server writes the call row, the ledger-or-refusal and the outbox row that triggers
    the post-call pipeline IN ONE TRANSACTION, exactly as the sink does today. That
    guarantee is relocated to the side that owns the database, which is where a transaction
    belongs — it is not weakened, and `docs/evidence/worker-http-contract.md` records why.
    """

    model_config = _STRICT

    final_status: Literal["completed", "failed", "no_answer", "busy", "cancelled"]
    direction: CallDirection
    agent_id: UUID
    #: Carried here TOO, and not only on `ObservationBatch`, because settlement upserts the
    #: call row itself: a call that failed before its first flush is minted HERE, and a row
    #: minted without the parties is a lead and an erasure subject lost at the one moment
    #: nothing else will supply them. Same nullability and same gate as the batch's pair.
    from_e164: str | None = None
    to_e164: str | None = None
    refusal: SettlementRefusal | None = None
    quantities: list[MeteredQuantity] = Field(default_factory=list, max_length=MAX_QUANTITIES)


class SettlementOut(BaseModel):
    """What the settlement did, including the answer a RETRY gets.

    `already_settled` is the honest answer to a re-delivery and is not an error: a worker
    whose POST timed out after the server committed must be able to retry, and a second
    attempt has to report "this was already done" rather than either failing or writing the
    ledger twice. An append-only ledger has no UPDATE to correct a double write with.
    """

    model_config = _STRICT

    already_settled: bool
    rows_written: int
    refusal_recorded: bool
    post_call_enqueued: bool


__all__ = [
    "MAX_EVENTS_PER_BATCH",
    "MAX_IDENTIFIER",
    "MAX_METERED_QTY",
    "MAX_QUANTITIES",
    "MAX_REFUSAL_TEXT",
    "MAX_TURNS_PER_BATCH",
    "METERED_LEGS",
    "MeteredLegName",
    "MeteredQuantity",
    "ObservationBatch",
    "ObservationsOut",
    "SettlementOut",
    "SettlementRefusal",
    "SettlementRequest",
    "WorkerSessionOut",
]
