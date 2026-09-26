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
  not merely optional. Hard rule 7 says the figure that reaches `unit_cost_paid` is an
  attested one, and the server holds the rate card; the worker sends QUANTITIES.

  `metered_rows` returns the legs it could measure AND a refusal per leg it could not, and
  this module carries both in one body (D-625) — refusing the whole settlement on one
  unwitnessed leg would discard the measurements of the others permanently. See
  `SettlementRequest`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from calevate_shared.engine import AgentConfig, ModelConfig
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

#: And one refusal per leg nobody could price, for the same reason and with the same
#: argument: a MEMORY BOUND, not a claim about how many legs exist. Since D-625 a settlement
#: can carry both lists at once (a leg we measured settles beside a leg we could not), so the
#: two bounds are declared separately rather than one being read as the other's complement.
MAX_REFUSALS: Final = 32

#: The platform's call cap when an agent's owner has chosen none, DERIVED rather than
#: retyped. `agents/service.effective_call_cap` already resolves `agents.max_call_duration_s`
#: against `agents/models.CALL_CAP_DEFAULT_S` before `AgentConfig` is built, so the resolved
#: config a worker is served always carries a real integer and this default is only ever
#: read by a caller constructing a `SessionConfig` by hand (a test, a local run).
#:
#: ⚠ **NOT THE LITERAL `600`, AND THAT IS THE WHOLE POINT.** `packages/shared` cannot import
#: `apps/`, so `CALL_CAP_DEFAULT_S` is unreachable from here — but `AgentConfig.
#: max_call_duration_s` carries the same number as its own field default and IS reachable, so
#: the value is read off the model instead of being spelled a third time. A platform constant
#: with two spellings is hard rule 4's "named here rather than copied" defect, and a cap the
#: console shows while the worker enforces a different one is the version of it that costs a
#: client money.
DEFAULT_CALL_CAP_S: Final[int] = int(AgentConfig.model_fields["max_call_duration_s"].default)

#: WHO IS ON THE FAR END, OR THE NAMED REASON WE CANNOT SAY.
#:
#: ⚠ **DECLARED HERE BECAUSE `apps/api` CANNOT IMPORT THE WORKER.** `voice_worker/carrier.
#: CallerIdentityState` is the same four words and is the authority on what they mean; the
#: directory is hyphenated and lives in another deployable, so the wire needs its own
#: spelling. `carrier.py` should import THIS one rather than declaring a second — that is a
#: one-line change in a file this change was not permitted to touch, and it is reported
#: rather than made.
#:
#: The four states are not decoration. A `None` number that means four unrelated things
#: cannot be triaged, which is exactly how `calls.from_e164` came to be empty on every call
#: of this engine with nothing anywhere saying why:
#:
#: * ``known`` — a number is in hand.
#: * ``withheld_by_carrier`` — our pinned client DOES read this carrier's field and the
#:   carrier put nothing in it. A real carrier answer (caller ID withheld, or absent).
#: * ``unparsed_by_client`` — the client maps no field for this carrier, so nobody can say
#:   whether one was sent. This is Plivo today, and it is an UNKNOWN, not a finding.
#: * ``not_read`` — nobody looked. The default.
CallerIdentityState = Literal["known", "withheld_by_carrier", "unparsed_by_client", "not_read"]


#: WHETHER THIS CALL HAD ITS CLIENT'S KNOWLEDGE, OR THE NAMED REASON IT DID NOT.
#:
#: ⚠ **DECLARED HERE AND NOT IN THE WORKER, FOR `CallerIdentityState`'S REASON.**
#: `apps/api` cannot import `apps/voice-worker`, so a vocabulary declared only over there
#: is one the server can neither check nor constrain a column against — every string a
#: client sent would land in `calls.knowledge_state`. `voice_worker/knowledge.
#: UnavailableReason` IS the four-member type below, aliased rather than re-spelled, so the
#: two deployables and the CHECK constraint cannot drift apart.
#:
#: A `None` that means several things cannot be triaged, so the report is a total answer
#: and not only a failure:
#:
#: * ``available`` — the pack loaded and every question is answered out of it.
#: * ``no_pack`` — this agent has published no knowledge base. Ordinary and permanent, not
#:   a degradation: the agent says so rather than saying it cannot look right now.
#: * the four below — a pack WAS configured and the call ran without it, so every question
#:   for the whole call answered `temporarily_unavailable`.
KnowledgeUnavailableReason = Literal[
    "fetch_failed", "absent", "unsupported_format", "identity_mismatch"
]
KnowledgeState = Literal[
    "available",
    "no_pack",
    "fetch_failed",
    "absent",
    "unsupported_format",
    "identity_mismatch",
]

#: Every state, for the CHECK constraint and for a caller that needs membership.
KNOWLEDGE_STATES: Final[frozenset[str]] = frozenset(get_args(KnowledgeState))

#: The states that mean THE CALL ANSWERED NOTHING — what an alarm fires on and what an
#: operator counts. `tests/worker_knowledge_report_test.py` asserts these are exactly the
#: states `KnowledgeState` holds beyond `available` and `no_pack`, so the two declarations
#: above cannot drift without a red test.
DEGRADED_KNOWLEDGE_STATES: Final[frozenset[str]] = frozenset(get_args(KnowledgeUnavailableReason))


class KnowledgeReport(BaseModel):
    """What the container found when it went for this call's knowledge pack.

    **IT IS AN OBSERVATION AND CARRIES NO VERDICT**, which is this module's rule: the
    worker says what it saw, and `worker/service` decides whether that is worth an alarm,
    which severity it is, and how many calls it has already happened to.

    **ONE REPORT PER CALL, ON THE FIRST BATCH THAT LEAVES.** The pack is resolved once,
    while the phone is ringing, and nothing changes it for the rest of the call — so this
    is a session fact and rides beside `agent_id` and `direction` for their reason, rather
    than being re-sent per turn.

    HARD RULE 6: a state word and a content hash. The digest names an OBJECT, not a person,
    and the four failure words are authored in this repository.
    """

    model_config = _STRICT

    state: KnowledgeState
    #: The pack digest the session asked for, `""` when none was configured. Present on the
    #: failure path especially: it is the handle on the object that did not load, and it is
    #: what makes one store outage legible as one cause behind many calls.
    #:
    #: PINNED TO THE SHAPE A DIGEST HAS, for `AttestationIn.observed_prompt_sha256`'s
    #: reason: the only producer is `hashlib`, so a truncated or upper-cased value is a
    #: client built wrong, and a 422 at the edge finds that on the first call rather than
    #: leaving an unmatchable string in the alarm an operator is trying to triage with.
    digest: str = Field(default="", pattern=r"^([0-9a-f]{64})?$")


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
    #: HOW LONG THIS AGENT'S CALLS MAY RUN, IN SECONDS — the cap the console already writes
    #: (`agents/publishing_routes.py:403`) and the rented engine already pushes as
    #: `call_terminate` (`engine/bolna.py:4106`).
    #:
    #: ⚠ **NOTHING ELSE ENFORCES IT ON THIS ENGINE.** `assemble_call` sets
    #: `idle_timeout_secs=None` deliberately (a phone call has its own end), so without this
    #: a call that never ends never ends — burning a client's credits against a cap they set
    #: and were shown, which is a money defect under hard rule 7 before it is a trust one.
    #: The worker enforces it by pushing an `EndWorkerFrame`
    #: (`pipeline.CallDurationCap`), which DRAINS — the caller hears the end of the
    #: sentence in flight, not a dead line.
    max_call_duration_s: int = DEFAULT_CALL_CAP_S


class ObservationBatch(BaseModel):
    """What the container witnessed since the last batch: statuses and spoken turns.

    ONE BODY FOR BOTH because they are one fact — what happened on this call — and because
    the server has to order them anyway: a turn may arrive before the status that opened the
    call (Pipecat dispatches every handler as its own task), and the existing sink already
    converges both on one call-row upsert for exactly that reason.

    Empty lists are legal. A flush with nothing in it is a no-op the client is allowed to
    send rather than a condition it must check for.

    ⚠ **`agent_id` AND `direction` ARE ON THE BATCH, NOT ONLY ON THE EVENTS.**
    `TranscriptTurn` carries neither and `CallEvent` declares `agent_id` nullable, so the
    FIRST batch of a call — routinely a flush of turns, because Pipecat dispatches every
    handler as its own task and a turn can beat the event that opened the call — would name
    nothing the server could mint a `calls` row from. They are session facts, so they travel
    with the session's batch; deriving them from whichever event happened to be in it would
    be a guess on a FORCE-RLS'd row's `agent_id`.
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
    #: ⚠ **WHAT FILLS THEM, AND WHAT STILL CANNOT** (DEPLOYMENT §12.5 gate 9).
    #: `carrier.CallerIdentity` models the answer as a four-state verdict (`known`,
    #: `withheld_by_carrier`, `unparsed_by_client`, `not_read`), `pipeline.
    #: NormalizedEventBoundary` writes the number onto every `CallEvent` it emits when the
    #: state is `known`, and `worker/service.record_observations` takes it from the events
    #: when the batch names no party. Two facts about the PINNED client are unchanged and
    #: still bound what can arrive: Pipecat's Plivo branch writes only `streamId`/`callId`
    #: (`runner/utils.py:257-262`) so `from_number` stays `None` with nothing consulted
    #: (`runner/types.py:94`) — that is `unparsed_by_client`, an UNKNOWN rather than a
    #: finding — and the outbound dial is still `OUTBOUND_DIAL_UNKNOWN`. Telnyx (`:253`) and
    #: Exotel (`:270`) both write `"from"`, so the next carrier may simply hand it over.
    #: Absent, these leave the column NULL, which every reader above already tolerates.
    #:
    #: ⚠ **THE STATE DOES NOT RIDE HERE AND THAT IS NOT AN OVERSIGHT.** `calls` has no
    #: column for it and this change adds no migration, so the verdict is carried where a
    #: reader can act on it instead: on the tool bodies below, where it decides SYNCHRONOUSLY
    #: what an agent may tell a caller who has just asked not to be called again.
    from_e164: str | None = None
    to_e164: str | None = None
    events: list[CallEvent] = Field(default_factory=list, max_length=MAX_EVENTS_PER_BATCH)
    turns: list[TranscriptTurn] = Field(default_factory=list, max_length=MAX_TURNS_PER_BATCH)
    #: WHETHER THIS CALL HAD ITS KNOWLEDGE, SENT ONCE AND THEN NOT AGAIN.
    #:
    #: It rides an observation batch rather than travelling as a request of its own because
    #: it IS an observation — "what did this container witness?" — and because a fifth route
    #: would be a second channel for the same fact, on a path whose whole point is that the
    #: client is one door. It costs no extra round trip: the batch was going anyway.
    #:
    #: `None` on every batch after the first, and on every batch a client that predates this
    #: field sends. The server leaves the column alone rather than clearing it.
    knowledge: KnowledgeReport | None = None


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
#: ⚠ **THIS LIVES IN THE WIRE MODULE AND THE WORKER'S `MeteredLeg` IS DERIVED FROM IT.**
#: `apps/api` cannot import `apps/voice-worker`, so a vocabulary declared only in the
#: worker is one the server cannot check — every string a client sent would be echoed into
#: `call_metering_refusals.leg`. A claim that two deployables agree has to be something one
#: of them can actually check.
MeteredLegName = Literal["carrier", "runtime", "stt", "tts", "llm"]

#: The same five as a set, for a caller that needs membership rather than a type.
METERED_LEGS: Final[frozenset[str]] = frozenset(get_args(MeteredLegName))


class MeteredQuantity(BaseModel):
    """One leg's measured quantity, with NO price attached.

    `unit_cost_inr` and `total_inr` are deliberately absent: see this module's docstring.
    The server multiplies, because the server is what holds an attested rate.

    ⚠ **`qty` MUST STAY BOUNDED AND NON-NEGATIVE.** Refusing a PRICE from the worker buys
    nothing if the server then multiplies any magnitude it is handed by an attested rate and
    INSERTs the product into `usage_events`, which hard rule 4 makes INSERT-only. An
    unbounded `qty: Decimal` accepts `-99999999`, so one holder of the worker token could
    mint a permanent self-issued credit that nothing but a compensating entry could answer,
    and `1e50` is an unpayable charge by the same door. `allow_inf_nan=False` because a NaN
    in a NUMERIC column poisons every SUM taken over that tenant's usage for ever.

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
    """Why ONE leg could not be metered — the shape `call_metering_refusals` already stores.

    A refusal is a FACT the worker observed (it could not read a quantity), which is why it
    travels in the same direction as everything else here.

    ⚠ **`leg` IS THE KEY, NOT A LABEL (D-625).** A settlement carries a refusal per leg
    nobody could price and a quantity per leg somebody could, and the server refuses a body
    that names one leg in both places (`worker/service._check_settlement`).
    """

    model_config = _STRICT

    #: ⚠ **BOUNDED BECAUSE THEY ARRIVE OVER HTTP.** "Every refusal string is authored in
    #: this repository" is true of the client we ship and enforced of no client, and these
    #: land in an append-only table as `TEXT`.
    leg: MeteredLegName
    code: str = Field(max_length=MAX_IDENTIFIER)
    detail: str = Field(max_length=MAX_REFUSAL_TEXT)
    remediation: str | None = Field(default=None, max_length=MAX_REFUSAL_TEXT)


#: What a settlement may say the call ended as. Named so the worker can hold one without
#: retyping the vocabulary.
SettlementStatus = Literal["completed", "failed", "no_answer", "busy", "cancelled"]

#: The same five as a set, for a caller that needs membership rather than a type.
SETTLEMENT_STATUSES: Final[frozenset[str]] = frozenset(get_args(SettlementStatus))


class SettlementRequest(BaseModel):
    """The terminal write, and the one that carries D-607.

    **A REFUSAL NAMES A LEG; QUANTITIES NAME OTHER LEGS (D-625).** The rejected alternative
    is "a refusal OR quantities, never both": under it, no production call having a CDR
    (BLOCKER-1) means every call settles as one carrier refusal and the STT seconds, TTS
    characters and LLM tokens the worker genuinely measured are discarded — unrecoverably,
    because an append-only ledger cannot be corrected once the settlement has answered. "We
    could not witness the connected minute" is not a reason to disown the three legs we DID
    witness.

    What that rule protects is stated per leg instead: the carrier's authority is untouched,
    nothing invents a connected minute or a charge, and a leg nobody can price still becomes
    a `call_metering_refusals` row rather than a zero.

    So the invariant the server checks is DISJOINTNESS, not exclusivity: no leg may be
    refused twice, and no leg may appear in `refusals` and in `quantities` at once. It is
    validated rather than trusted, because a client is a thing on somebody else's
    infrastructure.

    ⚠ **BOTH EMPTY IS LEGAL.** It is the third state `meter.py` distinguishes deliberately
    — a session that transcribed and synthesised nothing has no leg to price, which is not
    a leg nobody can price — and it still has to
    settle, because the outbox row that starts the post-call pipeline rides the settlement
    (D-607).

    The server writes the call row, the ledger-or-refusal and the outbox row that triggers
    the post-call pipeline IN ONE TRANSACTION, exactly as the sink does today. That
    guarantee is relocated to the side that owns the database, which is where a transaction
    belongs — it is not weakened, and `docs/evidence/worker-http-contract.md` records why.
    """

    model_config = _STRICT

    final_status: SettlementStatus
    direction: CallDirection
    agent_id: UUID
    #: Carried here TOO, and not only on `ObservationBatch`, because settlement upserts the
    #: call row itself: a call that failed before its first flush is minted HERE, and a row
    #: minted without the parties is a lead and an erasure subject lost at the one moment
    #: nothing else will supply them. Same nullability and same gate as the batch's pair.
    from_e164: str | None = None
    to_e164: str | None = None
    refusals: list[SettlementRefusal] = Field(default_factory=list, max_length=MAX_REFUSALS)
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
    #: HOW MANY LEGS WERE RECORDED AS UNPRICEABLE, not whether any was (D-625). A bool could
    #: not distinguish "the carrier leg had no CDR and the other three settled" from "nothing
    #: could be priced at all", which is exactly the distinction partial settlement exists to
    #: make and the one an operator reads `rows_written` beside.
    refusals_recorded: int
    post_call_enqueued: bool


class AttestationIn(BaseModel):
    """What the worker recomputed about the prompt it actually loaded (§1.1).

    **THE WORKER SENDS WHAT IT OBSERVED; THE SERVER DECIDES WHAT THAT MEANS.** This body is
    the sharpest case of that rule in the contract, so it carries the digest and NOT the
    verdict: `voice_worker/pipeline.AssembledCall` computes `prompt_matches_config_version`
    for its own logging, and a client-supplied "yes it matched" would make
    `agents/config_versions.Attestation.matches` agree with the caller by construction —
    which is the `control_plane` defect `config_versions.py` exists to close. The server
    re-reads `agent_config_versions.prompt_sha256` and compares.

    ⚠ **THIS ROUTE IS THE TABLE'S ONLY PRODUCTION WRITER (D-626).** Without it
    `record_attestation` is called by tests alone, `PipecatEngine.get_agent` answers
    `system_prompt_readable=False` for every agent for ever, and hard rule 5's engine-side
    verification never runs on this leg — the digest is computed in the worker and reaches
    nothing.

    `agent_id` is on the body as well as in the ref the route is posted to, and the server
    refuses a disagreement rather than reconciling it — `ObservationBatch`'s posture, for
    its reason.
    """

    model_config = _STRICT

    agent_id: UUID
    #: The immutable version this process says it loaded. The server checks it belongs to
    #: that agent before it writes anything.
    agent_config_version_id: UUID
    #: sha256 of the system prompt in this container's memory, lowercase hex. PINNED to that
    #: shape here so a truncated or upper-cased digest is a 422 at the edge rather than a
    #: permanent false mismatch in a table whose whole job is to make mismatches meaningful.
    observed_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AttestationOut(BaseModel):
    """The verdict, answered back so the worker can log what the control plane concluded.

    `matches=False` IS NOT AN ERROR and the route does not fail on it: a stale worker, a
    version published after the session started, or a prompt truncated on the way into the
    process are all findings this row exists to preserve. `agents/verification.py` and the
    drift sweep score them; the writer sees one.
    """

    model_config = _STRICT

    attestation_id: UUID
    matches: bool


# --- the in-call tools (the four `apps/voice-runtime/tool_routes.py` already serves) ----
#
# **THE ENGINE LEG IS THE SPECIFICATION AND THIS IS THE SAME BEHAVIOUR, NOT A SECOND
# OPINION.** `tool_routes.py` decides what an opt-out does, what a booking validates, what a
# cancellation means and what the agent is told in each outcome; every model below is that
# vocabulary, and the handlers in `apps/api/worker/tools.py` reach the SAME service
# functions the engine leg's ARQ jobs reach (`compliance/optout.record_call_optout`,
# `callbacks/service.book`, `callbacks/service.cancel_for_phones`). Two implementations of
# "add this caller to the DNC list" is the defect this arrangement exists to prevent.
#
# **ONE WORD IS DELIBERATELY DIFFERENT AND IT IS THE HONEST ONE.** The engine leg answers
# `accepted` and never "done", because on that leg the write happens in a worker a few
# hundred milliseconds later, behind an authenticated Get Execution. There is no execution
# to fetch here and no poller: the worker names its own call ref, the server resolves the
# tenant from it and does the write IN THE REQUEST, so the truthful status is `recorded` /
# `booked` / `cancelled`. Saying "accepted" would be under-claiming, and under-claiming is
# a sentence an agent reads out to a caller.
#
# **`say` IS GUIDANCE FOR THE AGENT, IN ENGLISH, WHICH ITS OWN LLM RENDERS INTO THE
# CALLER'S LANGUAGE** — `calling_window.SlotRefusal`'s rule, which these follow because the
# caller may be speaking Telugu and a bare status word is not something a model can say.

#: The longest model-authored string a tool body may carry. `workers/optout._REASON_CHARS`
#: (80) and `callbacks.MAX_NOTE` (200) are what the values are truncated to where they are
#: STORED; this is the bound at the edge, for `MAX_REFUSAL_TEXT`'s reason — a language model
#: has no length contract and an unbounded body is a 1 vCPU host materialising it.
MAX_TOOL_TEXT: Final = 500


class CallerIdentityIn(BaseModel):
    """What the container observed about who is on the far end, carried per tool call.

    **IT IS ON THE TOOL BODY AND NOT ONLY ON `ObservationBatch` BECAUSE THE DECISION IS
    SYNCHRONOUS.** The engine leg answers an opt-out `accepted` and lets an ARQ job discover
    minutes later that the call named nobody — `workers/optout.py` alerts
    `in_call_optout_unattributable` and returns `"unattributable"`, by which time the caller
    has hung up believing they were removed. On this leg the agent is waiting for an answer
    it is about to SAY, so the verdict has to be readable in the moment.

    `state` is the fact; `e164` is the number and only ever travels with `state="known"`.
    Hard rule 6: the number is carried, never logged — the server logs `state` and nothing
    else, and `state` is authored in `voice_worker/carrier.py` rather than built from wire
    data, so it cannot smuggle one.
    """

    model_config = _STRICT

    state: CallerIdentityState = "not_read"
    e164: str | None = None


class OptOutToolIn(BaseModel):
    """ "Do not call me again", as the model reports it. Both fields are hints.

    They become EVIDENCE text in `consent_ledger` (append-only, hard rule 4) and nothing
    else: the number suppressed is never taken from either.
    """

    model_config = _STRICT

    reason: str | None = Field(default=None, max_length=MAX_TOOL_TEXT)
    language: str | None = Field(default=None, max_length=8)
    caller: CallerIdentityIn = Field(default_factory=CallerIdentityIn)


class OptOutToolOut(BaseModel):
    """Two statuses, and the second one is the whole reason this model is not a bare ack.

    **`not_recorded` MUST NOT READ AS SUCCESS ANYWHERE.** A person who asked not to be
    called again and was told "done" when nothing was written is the worst outcome
    available — worse than being told a person will handle it, because they will not ring
    again to check. So the failure carries its own `say`, and the agent is told in words
    what it may and may not claim.
    """

    model_config = _STRICT

    status: Literal["recorded", "not_recorded"]
    say: str
    #: A machine code an operator can grep, never prose for the caller: `caller_number_unknown`
    #: (with the identity state appended), `not_suppressible`, or `""` on success.
    reason: str = ""


class CallbackBookIn(BaseModel):
    """ "Ring me back Tuesday at four", already resolved by the model into date and time.

    `confirmed` IS A BOOL ON THIS WIRE AND A NARROW PARSE IN THE WORKER. The engine leg
    receives whatever the vendor substitutes and narrows it in `tool_routes._truthy`
    (`true`/`"true"`/`"yes"` and nothing else); here the narrowing happens in
    `voice_worker/call_tools.py` before the body is built, so the contract between the two
    halves of OUR product carries a decided boolean rather than a string to re-interpret.
    """

    model_config = _STRICT

    callback_date: str | None = Field(default=None, max_length=MAX_IDENTIFIER)
    callback_time: str | None = Field(default=None, max_length=MAX_IDENTIFIER)
    confirmed: bool = False
    note: str | None = Field(default=None, max_length=MAX_TOOL_TEXT)
    language: str | None = Field(default=None, max_length=8)
    caller: CallerIdentityIn = Field(default_factory=CallerIdentityIn)


class CallbackToolOut(BaseModel):
    """The booking's four answers. `tool_routes.CallbackToolOut`'s three, plus the honest one.

    `needs_confirmation` and `not_booked` are that model's, unchanged and for its reasons:
    confirm-before-commit is a SERVER-SIDE control, and a time outside 09:00-21:00 IST is
    unlawful to dial (TCCCPR; SEC-COMP §3) and must be refused while the caller is still on
    the phone. `booked` replaces `accepted` because the row is written in this request.

    The fourth is `not_booked` with `reason="caller_number_unknown"`: a promise to ring
    somebody back needs a number to ring, and this leg can be told there is none.
    """

    model_config = _STRICT

    status: Literal["booked", "needs_confirmation", "not_booked"]
    say: str
    #: The unambiguous spoken form the agent must read back — "Tuesday 8 September at
    #: 4:00 PM". Weekday and month NAME, never a numeric date (`calling_window.Slot`).
    booked_for: str = ""
    reason: str = ""


class CallbackCancelIn(BaseModel):
    """ "Actually, don't ring me back." No time in it at all — `_cancel_callback`'s rule.

    A cancellation must not be able to fail because a date could not be parsed, and it is
    NOT an opt-out: "do not ring me back on Tuesday" is not "never call me again", and
    answering it with a DNC entry would suppress a number on a sentence nobody said.
    """

    model_config = _STRICT

    caller: CallerIdentityIn = Field(default_factory=CallerIdentityIn)


class CallbackCancelOut(BaseModel):
    """What was called off. `cancelled` is a count so "nothing was booked" is sayable."""

    model_config = _STRICT

    status: Literal["cancelled", "not_cancelled"]
    say: str
    cancelled: int = 0
    reason: str = ""


class HandoffToolIn(BaseModel):
    """The model's own words about why it wants a person, passed through unread.

    Both are conversation content and neither is logged (hard rule 6) — `tool_routes.
    _handoff_started` carries the same two for the same reason.
    """

    model_config = _STRICT

    reason: str | None = Field(default=None, max_length=MAX_TOOL_TEXT)
    summary: str | None = Field(default=None, max_length=MAX_TOOL_TEXT)


#: What became of a request for a person. ONE vocabulary, declared here because both halves
#: of the product import it: the server decides which word is true, `voice_worker/
#: call_tools.py` holds the sentence the agent says for each, and neither may invent a
#: member the other has no sentence for.
#:
#: **THE THREE FAILURES ARE SEPARATE WORDS BECAUSE THEY ARE SEPARATE SENTENCES.** "Nobody
#: picked up", "there is nobody on duty" and "this line cannot transfer at all" all end the
#: same way — a call back — and collapsing them would hand a worried caller one flat
#: apology for three different situations. They also differ in what is true later: the
#: first may work on the next call, the second will work in the morning, the third never
#: will until a carrier leg is written.
#:
#: **`connected` IS THE ONLY WORD THAT LICENSES "I AM PUTTING YOU THROUGH", AND IT MEANS A
#: PERSON ACCEPTED** — not that a number was dialled, not that it is ringing. The
#: destination pattern is whisper-then-accept: the person we ring hears who is calling and
#: about what, and has to accept before the bridge. A caller told they are getting a person
#: and then handed silence is the worst outcome this feature has.
#:
#: `not_transferred` is the WIDE one: it did not happen and the answer cannot say which of
#: the three it was. It is what an engine with no handover at all has always returned, so
#: it stays a member rather than being migrated away.
HandoffOutcome = Literal[
    "connected",
    "no_answer",
    "nobody_on_duty",
    "not_available",
    "not_transferred",
]


class HandoffToolOut(BaseModel):
    """What became of the request for a person, in a word the agent has a sentence for.

    ⚠ **`owned_runtime` CANNOT TRANSFER A CALLER TODAY, AND THE REFUSAL IS THE FEATURE.**
    `engine/pipecat.PIPECAT_CAPABILITIES` declares `transfer=False` and
    `in_call_handoff=False` — facts about a carrier surface nobody has read, not policy —
    and `update_agent` already refuses to publish an agent carrying a handoff config on this
    engine. So `not_available` is the only answer any deployment currently gives, and it is
    the path to build first rather than the edge case.

    What was there before this tool existed was WORSE than a refusal: with no tool at all a
    model asked to fetch a human answers from its priors, says "putting you through now",
    and the caller hears nothing happen. `build_knowledge_tool`'s posture applied to the
    second-hardest question a caller asks — advertised and honest.

    **THE WORKER DOES NOT TRUST `say` TO CARRY THAT INVARIANT.** `call_tools.py` keys its
    own guidance on `status`, so an agent cannot be told it connected somebody unless this
    field says `connected`, whatever prose an answer carries beside it.
    """

    model_config = _STRICT

    status: HandoffOutcome
    say: str
    reason: str = ""


__all__ = [
    "DEFAULT_CALL_CAP_S",
    "DEGRADED_KNOWLEDGE_STATES",
    "KNOWLEDGE_STATES",
    "MAX_EVENTS_PER_BATCH",
    "MAX_IDENTIFIER",
    "MAX_METERED_QTY",
    "MAX_QUANTITIES",
    "MAX_REFUSALS",
    "MAX_REFUSAL_TEXT",
    "MAX_TOOL_TEXT",
    "MAX_TURNS_PER_BATCH",
    "METERED_LEGS",
    "SETTLEMENT_STATUSES",
    "AttestationIn",
    "AttestationOut",
    "CallbackBookIn",
    "CallbackCancelIn",
    "CallbackCancelOut",
    "CallbackToolOut",
    "CallerIdentityIn",
    "CallerIdentityState",
    "HandoffOutcome",
    "HandoffToolIn",
    "HandoffToolOut",
    "KnowledgeReport",
    "KnowledgeState",
    "KnowledgeUnavailableReason",
    "MeteredLegName",
    "MeteredQuantity",
    "ObservationBatch",
    "ObservationsOut",
    "OptOutToolIn",
    "OptOutToolOut",
    "SettlementOut",
    "SettlementRefusal",
    "SettlementRequest",
    "SettlementStatus",
    "WorkerSessionOut",
]
