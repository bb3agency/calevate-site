"""`/v1/worker` — the four routes `apps/voice-worker` speaks to (D-621, D-626).

**WHY THIS SURFACE EXISTS AT ALL.** `docs/DEPLOYMENT.md` §12.5 gate 6: the worker runs on
Pipecat Cloud and cannot reach our Postgres — that database is on the VPS host, behind the
Docker bridge. Of the four options recorded there this is the third, and it is the only one
that does not put the database holding every client's caller data on the public internet.

**WHY IT IS HERE AND NOT IN `apps/voice-runtime`.** The same contract
`compliance/caller_data_routes.py` is held by, and for a stronger version of its reason:
these handlers read `agent_config_versions` and WRITE `calls`, `transcript_turns`,
`usage_events` and the outbox under a tenant's RLS, they run `apps/workers/redaction` and
they consult `apps/api/billing/rates`. Hard rule 3 forbids heavy imports and DB writes
beyond a minimal event row on the latency-critical service by name, and
`tests/voice_runtime_import_surface_test.py` is what measures it.

**NOT ON THE CALL'S CRITICAL PATH, WHICH IS WHY THAT IS ACCEPTABLE.** The session read
happens while the phone is ringing (the worker bounds its own wait), the observation batches
are flushes of turns nobody reads during the call, and the settlement runs after the
pipeline has drained. No caller is waiting on any of the three.

**`include_in_schema=False` ON EVERY ROUTE.** No browser and no generated client calls
this: the OpenAPI snapshot CI freezes describes the surfaces a client consumes, and
`apps/voice-runtime/carrier_routes.plivo_answer` is the precedent that says so.

**AUTHENTICATION IS THE ONE THING THAT DOES NOT DEGRADE.** Every route answers 401 without
the deployment's own Bearer token, and a deployment with no token configured answers
nobody — see `service.authorized`. That posture is `caller_data_routes`', and the stakes are
higher here: that endpoint reads a nicety, these write the ledger.

HARD RULE 6: ids and counts. Nothing here logs transcript text, and there is no phone
number on this path to log.
"""

from __future__ import annotations

from typing import Annotated

from calevate_shared.worker_api import (
    AttestationIn,
    AttestationOut,
    ObservationBatch,
    ObservationsOut,
    SettlementOut,
    SettlementRequest,
    WorkerSessionOut,
)
from fastapi import APIRouter, Header, Path

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.worker.service import (
    authorized,
    engine_enabled,
    load_session,
    record_observations,
    record_prompt_attestation,
    refuse_wrong_engine,
    settle_call,
)

log = get_logger(__name__)

# The `/v1/worker/` prefix is an entry in `core.rbac.PUBLIC_PREFIXES` and each route below
# is a row in `scripts/check_public_routes.UNAUTHENTICATED_ROUTES`. Both are required: the
# prefix exempts the surface from the permission registry (a voice worker holds no Calevate
# session and no membership), and each row is the reviewed line saying what stands in for
# one.
router = APIRouter(prefix="/v1/worker", tags=["voice-worker"])

#: How long the path segments may be. A ref is `pipecat:<uuid>:<uuid>` — 81 characters — and
#: the bound exists so an unauthenticated caller cannot make us parse a megabyte.
_REF_MAX = 128


def _admit(authorization: str | None, *, writes: bool = True) -> None:
    """401, 409, or nothing. Every route's first line, and the only shared guard.

    A FUNCTION RATHER THAN A `Depends`, deliberately: a dependency that raised would still
    be the same three lines, and this way the refusal sits where a reader of the handler can
    see it. The log line names no token, no ref and no engine — an operator debugging a
    rotation reads this and the console's Secrets panel, not a log with a credential in it.

    **THE ORDER IS THE CREDENTIAL FIRST (D-627).** A stranger who found the URL learns
    nothing about which engine this deployment runs, because they never get past the 401 —
    `engine_intake`'s gates are ordered the same way and for the same reason.

    ⚠ **THE ENGINE CHECK IS NOT TIDINESS.** Everything these routes WRITE is reconciled by
    the post-call pipeline through the PROCESS-WIDE `ENGINE`, which never reads the `engine`
    key the settlement puts in its own outbox payload. On a deployment configured for another
    engine, an accepted settlement therefore mints rows whose pipeline asks the wrong vendor
    for this call — and the extraction, CRM columns and lead are lost. See
    `service.engine_enabled`.

    **`writes=False` IS THE SESSION READ, AND THE EXEMPTION IS THE WHOLE POINT OF THE
    SMALLER FIX.** That route answers a published agent's configuration: it writes no row,
    promises no pipeline and reconciles against no vendor, so none of the harm above is
    reachable through it. It is also what `api_client.probe` presents at boot, and a
    reachability check that could not distinguish "wrong URL" from "wrong engine" would send
    an operator to the wrong dashboard. Everything that touches the ledger is gated; the
    read is not.
    """
    if not authorized(authorization):
        log.warning("worker_api_unauthorized")
        raise ProblemError.unauthorized("This caller is not permitted to reach the worker API.")
    if writes and not engine_enabled():
        log.warning("worker_api_engine_not_enabled")
        raise refuse_wrong_engine()


@router.get("/session/{engine_agent_ref}", include_in_schema=False)
async def worker_session(
    engine_agent_ref: Annotated[str, Path(max_length=_REF_MAX)],
    authorization: Annotated[str | None, Header()] = None,
) -> WorkerSessionOut:
    """What one published agent is, for a worker about to answer its phone.

    **THE WORKER PRESENTS A REF AND WE ANSWER THE IDS**, which is the direction
    `caller_data_routes` already resolves that ref in. The worker never asks for a tenant; a
    client that could name a tenant could name somebody else's.

    This is also the route `voice_worker/boot.open_runtime` probes at startup, with a ref
    that names no agent: a 404 proves the API is reachable AND the credential is good, which
    is strictly more than the `SELECT 1` it replaces ever proved.
    """
    _admit(authorization, writes=False)
    return await load_session(engine_agent_ref)


@router.post("/calls/{engine_call_id}/observations", include_in_schema=False)
async def worker_observations(
    engine_call_id: Annotated[str, Path(max_length=_REF_MAX)],
    batch: ObservationBatch,
    authorization: Annotated[str | None, Header()] = None,
) -> ObservationsOut:
    """One batch of what the container witnessed: call statuses and spoken turns.

    Idempotent on `(call_id, idx)`, which is a constraint that already exists — so a
    re-delivered batch inserts nothing twice and the answer says how many were already
    there. That difference is the idempotency working, not loss.
    """
    _admit(authorization)
    return await record_observations(engine_call_id, batch)


@router.post("/calls/{engine_call_id}/settlement", include_in_schema=False)
async def worker_settlement(
    engine_call_id: Annotated[str, Path(max_length=_REF_MAX)],
    request: SettlementRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> SettlementOut:
    """The terminal write: the call row, the ledger-or-refusal and the post-call trigger,
    in ONE transaction (D-607).

    A re-delivery answers `already_settled` and writes nothing. An append-only ledger has no
    UPDATE with which to correct a double write, so "answer the retry" is the only shape
    available — see `service.settle_call` for what marks a call settled.
    """
    _admit(authorization)
    return await settle_call(engine_call_id, request)


@router.post("/agents/{engine_agent_ref}/attestation", include_in_schema=False)
async def worker_attestation(
    engine_agent_ref: Annotated[str, Path(max_length=_REF_MAX)],
    request: AttestationIn,
    authorization: Annotated[str | None, Header()] = None,
) -> AttestationOut:
    """What the worker recomputed about the prompt it actually loaded, at session start.

    **THIS IS THE ONLY PRODUCTION WRITER OF `agent_config_attestations` (D-626)**, and
    therefore the only thing that makes `PipecatEngine.get_agent` able to answer anything but
    "we have never heard from a worker". On `owned_runtime` there is no vendor to read the
    agent back off, so this row IS the independent witness hard rule 5's engine-side
    verification is scored against.

    **ON THE CALL'S CRITICAL PATH IN THE SENSE THAT MATTERS AND NOT IN THE SENSE THAT
    COSTS.** It is posted once per session while the pipeline is being assembled, and the
    worker does not wait on it to answer the phone — see `voice_worker/runtime.run_call` for
    why a failure here degrades rather than refuses.
    """
    _admit(authorization)
    return await record_prompt_attestation(engine_agent_ref, request)


__all__ = ["router"]
