"""One call's configuration, read over HTTP from `apps/api` (D-621).

**WHAT THIS MODULE IS FOR, IN ONE SENTENCE.** It turns three ids — a call, a tenant, an
agent — into the `SessionConfig` that `pipeline.assemble_call` takes, and it is the only
place in this worker that knows where that configuration comes from.

⚠ **IT USED TO KNOW WHICH TABLES IT LIVED IN, AND IT NO LONGER DOES.** `docs/DEPLOYMENT.md`
§12.5 gate 6: this container runs on Pipecat Cloud and cannot reach our Postgres at all, so
the three-table join that used to be here now runs in `apps/api/worker/service.load_session`
and this presents an `engine_agent_ref` and reads the answer. The join did not change — it
is the same statement against the same three tables, for the reason it always had: three
round trips would let a publish land between them and produce a `SessionConfig` whose prompt
came from one version and whose knowledge pack came from the next.

**IT READS A VERSION, NOT AN AGENT, AND THAT IS §1.1's WHOLE DESIGN.** `pipecat_agents`
holds a pointer to the immutable `agent_config_versions` row the control plane last
published, and the prompt and the resolved `ModelConfig` come FROM THAT ROW rather than
being recomposed here. A worker that composed its own prompt would be a second author of the
sentences hard rule 5 requires, and its attestation — `prompt_sha256` recomputed over what
it actually loaded (`pipeline.recompute_prompt_sha256`) — would agree with the control plane
by construction, which is the exact defect the attestation exists to catch. That is
unchanged by the move: the digest is recomputed over the prompt that arrived on the wire.

**HARD RULE 1 IS THE SERVER'S NOW, AND IT IS STRICTLY STRONGER THERE.** This process no
longer sets a `tenant_id` GUC because it no longer holds a connection; what it presents is
`pipecat:<tenant>:<agent>`, and the server parses the tenant out of that ref and runs the
read under that tenant's RLS. A worker that could name a tenant could name somebody else's;
a worker that names its own ref can only ever reach the tenant the ref says.

**HARD RULE 5 IS CHECKED ON BOTH SIDES AND NEITHER CHECK IS REDUNDANT.** The server refuses
to serve a session for an agent with no AI-disclosure sentence or a prompt that does not
carry the truthful-answer floor, because that is where the rows are. `refuse_unless_disclosed`
below re-asks both questions of what actually arrived, because THIS process is the last
reader before a model speaks — which is the argument it was written with, and the move
across a wire strengthens it rather than retiring it.

**NO VENDOR SDK, IN THE ONE PACKAGE THAT IS ALLOWED ONE.** `SessionConfig` is plain data and
so is everything on the way to it; the Pipecat legs are built from it in `pipeline.py`.
"""

from __future__ import annotations

from uuid import UUID

from calevate_shared.engine import carries_truthful_answer_floor
from calevate_shared.events import CallDirection
from loguru import logger

from voice_worker.api_client import WorkerApiClient, WorkerApiError
from voice_worker.pipeline import SessionConfig


class AgentNotRunnableError(RuntimeError):
    """This agent has nothing for a worker to run, so the call cannot be assembled.

    RAISED rather than answered with a default, which is the opposite of the choice
    `knowledge_pack_sha256 = None` gets in the same row — and the asymmetry is the point.
    A missing knowledge pack is an agent that has published nothing, which is an ordinary
    agent; a missing config VERSION is an agent with no prompt, and the prompt is where
    hard rule 5's truthful-answer floor lives. Assembling a call without one would put a
    live caller in front of a model running on whatever system message the vendor defaults
    to.

    Carries ids and never content (hard rule 6): an operator needs to know WHICH agent, and
    a row that does not exist has nothing to quote.
    """


async def load_session_config(
    api: WorkerApiClient,
    *,
    call_id: str,
    tenant_id: UUID,
    agent_id: UUID,
    direction: CallDirection,
    engine_agent_ref: str,
) -> SessionConfig:
    """The configuration for one call. Raises `AgentNotRunnableError` when there is none.

    **`api` IS AN ARGUMENT AND THIS MODULE OWNS NO CLIENT, WHICH IS THE SAME DECISION THIS
    FUNCTION ALWAYS MADE.** It used to take an `AsyncConnection` and own no engine, on the
    ground that "one process wants ONE pool sized against ONE workload. So the engine belongs
    with the container entrypoint that owns both". One `httpx.AsyncClient` per process is the
    same argument with a different noun — a client per request re-does DNS, TCP and TLS — and
    it is also what lets this be tested with a transport the test owns and no socket at all.

    **`engine_agent_ref` IS AN ARGUMENT AND IS NOT REBUILT FROM THE IDS**, although this
    function is handed both. `engine/pipecat.engine_agent_ref_for` is its author, this
    container must not import the monolith, and a second spelling of one handle is the drift
    the quality bar refuses. `carrier.route_of` reads it off the stream URL the carrier
    connected to, which is where it comes from on the only path a call reaches this worker
    by.

    **`direction` IS AN ARGUMENT AND NOT A COLUMN**, because `AgentConfig.direction` may be
    `both`: it says what the agent is ALLOWED to do, and `CallDirection` says what this call
    IS. Deriving one from the other would make every call on a `both` agent claim inbound.

    **`call_id` IS OURS AND IS READ FROM NOWHERE.** §1.2 splits the record: the carrier's CDR
    is reconciled AGAINST this id rather than being its source.

    **THE TENANT AND AGENT ARE CHECKED, NOT TAKEN.** The answer carries both, resolved from
    the ref by the server; disagreeing with the ids this call was routed to would mean the
    ref and the route named different agents, which is a hard rule 1 fault and is refused
    rather than reconciled — `sink.SinkIdentityError`'s rule, at the other end of the call.
    """
    try:
        answer = await api.session(engine_agent_ref)
    except WorkerApiError as failure:
        # NOT DEGRADED. Every other read on the ring fails open — caller memory to `()`, the
        # knowledge pack to an agent that cannot answer questions about the business — and
        # this one must not: the thing that could not be read is the prompt carrying hard
        # rule 5's sentences, and a call assembled without it puts a live caller in front of
        # a model running on whatever system message the vendor defaults to.
        raise AgentNotRunnableError(
            f"the configuration for agent {agent_id} could not be read from the platform "
            f"API, so no call may run on it: {failure}"
        ) from failure
    if answer.tenant_id != tenant_id or answer.agent_id != agent_id:
        raise AgentNotRunnableError(
            f"the platform API resolved this call's agent ref to agent {answer.agent_id} of "
            f"tenant {answer.tenant_id}, and the call was routed to agent {agent_id} of "
            f"tenant {tenant_id}"
        )
    refuse_unless_disclosed(
        agent_id=agent_id,
        ai_disclosure_line=answer.ai_disclosure_line,
        composed_prompt=answer.system_prompt,
    )

    logger.info(
        "session config loaded",
        call_id=call_id,
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        agent_config_version_id=str(answer.agent_config_version_id),
        # A digest is an id and is loggable; the prompt it was taken over is not.
        prompt_sha256=answer.prompt_sha256,
        # WHETHER this call has a pack, not which one. The digest is logged by `knowledge.py`
        # on the load itself, and two places logging one id is two places to get hard rule 6
        # wrong later.
        knowledge_pack=answer.knowledge_pack_sha256 is not None,
    )
    return SessionConfig(
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_config_version_id=answer.agent_config_version_id,
        direction=direction,
        system_prompt=answer.system_prompt,
        prompt_sha256=answer.prompt_sha256,
        models=answer.models,
        # EVERY AGENT SPEAKS FIRST, ON BOTH LEGS, AND NO COLUMN DECIDES IT TODAY (D-163).
        # The server is what answers `greet_first` now; the argument moved with it rather
        # than being restated in two places.
        language=answer.language,
        greet_first=answer.greet_first,
        knowledge_pack_sha256=answer.knowledge_pack_sha256,
        engine_agent_ref=answer.engine_agent_ref,
        # THE AGENT'S CALL CAP, CARRIED LIKE EVERY OTHER PUBLISHED FIELD AND DECIDED BY
        # NOBODY HERE. It reached this engine nowhere at all until now: the console writes
        # it, the rented engine pushes it as `call_terminate`, and `assemble_call` sets
        # `idle_timeout_secs=None` deliberately — so an `owned_runtime` call ran until
        # somebody hung up, against a cap its owner had set and been shown (hard rule 7).
        # `pipeline.CallDurationCap` is what enforces it.
        max_call_duration_s=answer.max_call_duration_s,
    )


def refuse_unless_disclosed(
    *, agent_id: UUID, ai_disclosure_line: str | None, composed_prompt: str | None
) -> None:
    """HARD RULE 5, AT THE ONE DOOR EVERY CALL OF THIS ENGINE COMES THROUGH.

    ⚠ **THE SERVER ASKS BOTH QUESTIONS TOO (D-621), AND THIS IS NOT THEREFORE REDUNDANT.**
    `apps/api/worker/service.load_session` serves no session for an undisclosed agent,
    because that is where the rows are and a worker cannot check what it was never sent.
    This re-asks both of what ARRIVED, because this process is the last reader before a
    model speaks — which is the argument the paragraph below was written with, and putting a
    network between the two readers makes it stronger rather than weaker.

    **WHY IT IS HERE AND NOT IN THE CARRIER ENTRYPOINT.** `apps/api` refuses an
    undisclosed agent twice already — `agents.ai_disclosure_line` is NOT NULL with a
    `length(btrim(...)) > 0` CHECK (`apps/api/agents/models.py:211`), and
    `compliance/service.check_dispatch` refuses to DIAL one with rule
    `disclosure_missing`. Both of those guard the OUTBOUND path from our own console. An
    inbound call on an `owned_runtime` engine reaches none of them: the carrier connects
    a socket straight to this worker, and until this check existed the only thing between
    a live caller and an undisclosed agent was a CHECK constraint on a column this process
    does not read. `load_session_config` is the one read every call makes, so the refusal
    belongs here — a second entrypoint (step 6's HTTP half, an outbound dial when the
    carrier surface is read) cannot be written around it.

    **TWO CONDITIONS, BECAUSE THEY FAIL DIFFERENTLY.**

    * The agent must HAVE its AI sentence on file. That is the dial gate's own question
      (`check_dispatch`: "This agent has no AI disclosure line and may not place calls"),
      asked here of answering as well as of placing.
    * The prompt this worker is about to run must CARRY the truthful-answer floor.
      `compose_engine_prompt` appends it to every version, so a version without it is a
      version composed by something else — and this process is the last reader before a
      model speaks. `carries_truthful_answer_floor` is the repo's one predicate for that
      question (it is what the publish read-back and the drift sweep ask), so a worker
      that asked it a second way would be a second definition of the floor.

    What is deliberately NOT checked: `ai_disclosure_enabled`. D-163 makes whether the
    sentence is VOLUNTEERED the tenant's decision on both legs; what may never be absent
    is the sentence and the floor.

    Ids only, and no fragment of either string (hard rule 6).
    """
    if not ai_disclosure_line or not ai_disclosure_line.strip():
        raise AgentNotRunnableError(
            f"agent {agent_id} has no AI disclosure line on file and may not answer or "
            "place calls (hard rule 5)"
        )
    if not carries_truthful_answer_floor(composed_prompt):
        raise AgentNotRunnableError(
            f"agent {agent_id} has a published prompt that does not carry the "
            "truthful-answer floor, so no call may run on it (hard rule 5)"
        )


__all__ = ["AgentNotRunnableError", "load_session_config", "refuse_unless_disclosed"]
