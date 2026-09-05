"""What the engine asks us about a caller BEFORE it answers them — the inbound leg (D-513).

An outbound dial carries what we remember in `user_data` on the `POST /call` body
(`engine/bolna.py`, VERIFIED-VENDOR-DOCS `bolna-findings/mirror/pages/api-reference/calls/
make.md:32`). An INBOUND call has no such body: the caller dialled us, so the engine is the
one holding the phone number, and it offers to fetch caller details from an endpoint of
ours at call setup and inject the answer into the agent's prompt.

VERIFIED, from the hash-pinned mirror, read 2 Sep 2026
(`bolna-findings/mirror/pages/agent-setup/inbound-tab.md`):

* It is a **GET**, not a POST — `curl -X GET "https://your-api.com/user-data?..."` (`:62`).
  The parked draft of this feature assumed a POST body; the doc says otherwise, which is
  why this reads query parameters and takes no body at all.
* The parameters are `contact_number` (the caller's phone number), `agent_id` ("your
  agent's identifier") and `execution_id` (`:49-53`).
* The credential is a Bearer token entered in their console (`:38-42`) and sent as
  `Authorization: Bearer …` (`:63`); they store it (`:78`).
* *"Your API must return a JSON response with user details. Bolna will inject this data
  directly into your agent's prompt"* (`:56`).

ASSUMED, and confined to this file (D-31/D-32): that the injection uses the SAME `{key}`
substitution the outbound `user_data` path uses, so returning `{"caller_memory": "…"}`
fills `CALLER_MEMORY_SLOT` in the published prompt. Their page shows the response shape
(`user_name`, `account_status`, …) and not the substitution syntax. That is OPERATIONS §2
gate 8c, and the failure it would produce is bounded and visible: a returning caller is
greeted generically, which is the same outcome as the store having nothing to say.

WHY IT IS HERE AND NOT IN `apps/voice-runtime`
--------------------------------------------------------------------------------------
It looks like a voice-runtime route — the engine calls it, on the call path — and it is
not, for a reason that is a contract rather than a preference. This endpoint has to derive
a KEYED caller reference (`compliance/caller_ref.py`, HMAC under a KEK-derived key) and
read `caller_memories` under the tenant's own RLS. Those live in `apps.api.compliance`,
which `tests/voice_runtime_import_surface_test.py` FORBIDS that service from importing —
along with `apps.workers`, which `caller_memory` pulls in for `redact()`. Putting the
route there would mean deleting entries from that guard, which is hard rule 3's executable
form: this endpoint does exactly the class of work — key derivation, a tenant-scoped read
of a durable store — that the guard exists to keep off the latency-critical service.

The precedent is `actions/routes.invoke_action`: an ENGINE-CALLED, IN-CALL endpoint that
lives in `apps/api` for the same reason (it needs the tenant, its credentials and its RLS),
resolves the tenant from `engine_agent_routes`, and is declared in
`scripts/check_public_routes.UNAUTHENTICATED_ROUTES`. This is the second instance of that
shape, not a new one.

IT FAILS OPEN, AND THAT IS THE DECISION
--------------------------------------------------------------------------------------
Every outcome that is not "here is what we remember" is `{}` — an unknown agent, a number
we cannot canonicalise, an agent whose client never switched memory on, a slow read, a
database that is down. A returning caller greeted as a stranger is a missed nicety; a
caller who gets no answer because a memory lookup raised is a broken product, and the
engine is holding an open line while we decide. `_BUDGET_S` is the ceiling on how long we
are willing to make that caller wait before giving up on the nicety.

**AUTHENTICATION IS THE ONE THING THAT DOES NOT FAIL OPEN.** A caller who does not present
the token gets 401, because the alternative is an endpoint that answers a stranger's
questions about our clients' callers. The refusal costs nothing: it is not a lookup
failure, so there is nothing to degrade to.

HARD RULE 6: ids and counts. The phone number arrives in a query parameter and is never
logged, and neither is a remembered fact.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Annotated
from uuid import UUID

from calevate_shared.engine import CALLER_MEMORY_VARIABLE, render_caller_memory
from fastapi import APIRouter, Header, Query
from sqlalchemy import text

from apps.api.compliance.caller_memory import recall
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session

log = get_logger(__name__)

# The `/v1/engine/caller-data/` prefix is an entry in `core.rbac.PUBLIC_PREFIXES` and the
# route below is a row in `scripts/check_public_routes.UNAUTHENTICATED_ROUTES`. Both are
# required: the prefix exempts it from the permission registry, and the row is the
# reviewed line that says why the world may call it and what stands in for a session.
router = APIRouter(prefix="/v1/engine/caller-data", tags=["in-call-tools"])

#: How long we are willing to keep a caller waiting for a nicety, in seconds.
#:
#: The whole budget for two indexed reads and one HMAC, and it is a CEILING rather than an
#: expectation — the reads are primary-key and partial-index lookups and should be single
#: -digit milliseconds. What it bounds is the pathological case: a saturated pool, a
#: failing-over database, a lock. On the other side of it is a person listening to silence
#: before their call connects, so it is set at the point where waiting longer stops being
#: worth what is being waited for.
_BUDGET_S = 0.25

#: The empty answer. One object, returned by every degraded path, so no branch can invent
#: a different shape of "we know nothing" — and so the engine substitutes nothing into the
#: prompt, which `CALLER_MEMORY_GUIDANCE` already tells the model means a caller it does
#: not know.
_NOTHING: dict[str, str] = {}


def _authorized(header: str | None) -> bool:
    """Does this request carry the token the engine was configured with?

    `hmac.compare_digest`, not `==`: this is a secret comparison on an endpoint anybody
    can reach, and Python's string equality returns as soon as two bytes differ. The
    scheme check is a plain comparison because the word "Bearer" is not a secret.

    AN UNCONFIGURED DEPLOYMENT ANSWERS NOBODY. A missing token is not "no authentication
    required" — it is a deployment that has not been wired to the engine yet, and the safe
    reading of an absent credential is that nothing may pass. This is the one place in this
    module where the safe answer is a refusal rather than an empty object.
    """
    expected = get_settings().bolna_caller_data_token
    if not expected or not header:
        return False
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return False
    return hmac.compare_digest(presented.strip(), expected)


async def _resolve_agent(engine: str, engine_agent_ref: str) -> tuple[UUID, UUID] | None:
    """`(tenant_id, agent_id)` for the engine's own agent id, or None.

    The same cross-tenant bridge `actions/routes.invoke_action` and the webhook receiver
    resolve through, read the same way: `engine_agent_routes` is the un-RLS'd routing table
    (`db/registry.py`), so this is a lookup and not an exemption.
    """
    async with untenanted_session() as anon:
        row = (
            await anon.execute(
                text(
                    "SELECT tenant_id, agent_id FROM engine_agent_routes "
                    "WHERE engine_agent_ref = :ref AND engine = :engine AND active"
                ),
                {"ref": engine_agent_ref, "engine": engine},
            )
        ).first()
    return (row[0], row[1]) if row is not None else None


def _restore_plus(contact_number: str) -> str:
    """The caller's number as E.164, undoing what the vendor's own request shape loses.

    **THEIR DOCUMENTED CALL SENDS AN UNENCODED `+`** — `curl -X GET "https://your-api.com/
    user-data?contact_number=+919876543210&..."` (VERIFIED-VENDOR-DOCS:
    `bolna-findings/mirror/pages/agent-setup/inbound-tab.md:62`, read 2 Sep 2026). In a
    query string `+` is the form-encoding for a SPACE, and every ASGI server decodes it
    that way, so the number arrives here as `" 919876543210"` and the keyed caller ref
    refuses it. Found by driving the documented request rather than by reading the code:
    the endpoint failed open on every single inbound call and said nothing but a log line.

    NARROW, AND IT NORMALISES NOTHING ELSE. It restores exactly the character the
    transport ate — a leading space or a bare leading digit becomes a leading `+` — and
    hands the result to `caller_ref`, which is the authority on whether a string is
    canonical and which refuses anything that is not. Doing more here would be a SECOND
    normaliser for phone numbers, and `caller_ref._checked` states the reason there may not
    be one: the write path and the erasure path disagreeing about the canonical form of one
    person is the divergence this store cannot survive.
    """
    candidate = contact_number.strip()
    return candidate if candidate.startswith("+") else f"+{candidate}"


async def _remembered(engine: str, engine_agent_ref: str, contact_number: str) -> dict[str, str]:
    """What this agent remembers about this caller, as the engine's variable map.

    `recall()` is the ONE reader (`compliance/caller_memory.py`), and it checks the switch
    for itself — so an agent whose client never turned this on returns an empty tuple here
    without this function needing to know the feature has a switch.

    `render_caller_memory` is the ONE renderer, shared with the outbound dial, so a caller
    hears the same thing about themselves whichever way the call was placed.
    """
    resolved = await _resolve_agent(engine, engine_agent_ref)
    if resolved is None:
        return _NOTHING
    tenant_id, agent_id = resolved
    phone = _restore_plus(contact_number)
    async with tenant_session(tenant_id) as session:
        facts = await recall(session, tenant_id, agent_id=agent_id, phone_e164=phone)
    if not facts:
        return _NOTHING
    # ONE KEY, THE CONTRACT'S. Three producers fill this variable — the outbound dial, this
    # endpoint, and the prompt token that expects it — and three spellings would be a
    # silent failure: an unfilled token is not an error, it is an agent reading a
    # placeholder out loud.
    return {CALLER_MEMORY_VARIABLE: render_caller_memory(facts)}


@router.get(
    "/{engine}",
    summary="Engine-called: what this agent remembers about the caller now ringing",
    description=(
        "The voice platform calls this when an inbound call arrives and puts the answer "
        "into the agent's instructions for that one call. It answers with nothing at all "
        "for a caller the agent has not spoken to, for an agent whose account has not "
        "switched caller continuity on, and whenever the lookup cannot be completed in "
        "time — a returning caller is then greeted normally, which is the right way for "
        "this to fail."
    ),
)
async def caller_data(
    engine: str,
    contact_number: Annotated[str, Query(max_length=32)],
    agent_id: Annotated[str, Query(max_length=128)],
    execution_id: Annotated[str, Query(max_length=128)] = "",
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """The engine's caller-details fetch. `{}` for everything we cannot answer.

    The parameter NAMES are the vendor's, not ours (`inbound-tab.md:49-53`), which is why
    `agent_id` here is the ENGINE's identifier for the agent and not `agents.id` — the same
    string `engine_agent_routes.engine_agent_ref` holds. Renaming it to something clearer
    would mean the query string we receive no longer matches the signature that reads it.

    `execution_id` is accepted and deliberately unused: the vendor sends it, refusing a
    request that carries it would be absurd, and there is nothing this read needs it for —
    the answer depends on the agent and the caller, not on which call this is. It is
    declared rather than swallowed by `**kwargs` so a reader can see it arrives.
    """
    if not _authorized(authorization):
        # Never echoes the token, the engine string or the number. An operator debugging a
        # rotation reads this line and the console's Secrets panel, not a log with a
        # credential in it.
        log.warning("caller_data_unauthorized")
        raise ProblemError.unauthorized("This caller is not permitted to read caller data.")
    try:
        async with asyncio.timeout(_BUDGET_S):
            answer = await _remembered(engine, agent_id, contact_number)
    except Exception as failure:
        # EVERY failure is the empty answer, and the breadth is the decision rather than
        # laziness: the alternative is enumerating which database, network and key-ring
        # errors are survivable, and the one nobody thought of is then a call that does not
        # connect. The budget above expires into this branch too — `asyncio.timeout` raises
        # `TimeoutError`, which is an `Exception` since 3.11, so it needs no arm of its own
        # and adding one would only invite a reader to trim the general case.
        #
        # A COUNT AND A TYPE NAME (hard rule 6). This is the line that tells an operator
        # the feature has silently stopped working, which is the failure mode fail-open
        # buys and the one it hides.
        log.warning("caller_data_failed_open", extra={"error": type(failure).__name__})
        return _NOTHING
    log.info("caller_data_served", extra={"remembered": bool(answer)})
    return answer


__all__ = ["router"]
