"""Agent endpoints. Reads are client-realm; publish is admin-only.

D-21 draws the control boundary and it is enforced here: clients CAN see their agents,
but editing an extraction schema is admin-only, because a schema change regenerates
prompt hints and needs a regression run — that routes through us, which is the
managed-service moat, not an oversight.

WHY THIS ROUTER HAS NO PREFIX
-----------------------------
It carries paths in two spaces — the client realm's `/v1/agents` reads and ONE admin
mutation under `/v1/admin/tenants/{tenant_id}/...` — so a shared prefix could only
describe one of them. Same resolution as `voice_routes.py`, which says so for the same
reason. Mount order is unchanged (`main.py` still includes `voice_router` first so
`/v1/agents/voices` is matched before `/v1/agents/{agent_id}`), and the new admin path
does not collide with anything on `admin/routes.py`: its `/tenants/{tenant_id}/...`
routes all take a different literal third segment (`kb`, `numbers`, `margin`, ...).

WHY PUBLISH NAMES ITS TENANT IN THE PATH
----------------------------------------
It used to be `POST /v1/agents/{agent_id}/publish`, inferring the tenant from
`Principal.tenant_id`, and in that shape it was **un-callable** — verified against the
live app, not reasoned about:

- WITHOUT `X-Impersonate-Org`: 401. Its `Depends(db)` resolves through `tenant_of` ->
  `current_any`, which without the impersonation header falls through to the CLIENT
  verifier and rejects an admin token ("not valid for this realm").
- WITH the header: 403. The principal resolves, but D-22 makes impersonation READ-ONLY
  and `requires()` refuses every `MUTATING_PERMISSIONS` entry — `agents:write`
  included — whenever that header is present.

So its `assert principal.tenant_id is not None` was unreachable code guarding a door
nobody could reach. The two ways an admin principal can carry a tenant are mutually
exclusive with mutating, which is why the fix is NOT to loosen D-22 but to stop
inferring the tenant: name it in the path and enter its RLS scope explicitly, exactly
as `admin/routes.py` does above `approve_kb` ("an admin reaching a tenant does so by
impersonation, and impersonation is read-only. The tenant is therefore named in the
path rather than inferred from a session, which also makes every approval
self-documenting in the audit log") and as `agents/prompt_routes.py` already does at
`/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt`. Publish now sits beside it.

⚠ The path changed, so the OpenAPI snapshot and the generated TS client are stale
until someone regenerates them (`pnpm gen:api`) — deliberately not done here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, get_args
from uuid import UUID

from calevate_shared.extraction import OutcomeTag
from fastapi import APIRouter, Depends, Query, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import lifecycle, roster
from apps.api.agents.llm_models import (
    validate_llm_model,
)
from apps.api.agents.models import (
    CALL_CAP_MAX_S,
    CALL_CAP_MIN_S,
    AgentDirection,
    AgentStatus,
)
from apps.api.agents.publishing import (
    CALLER_MEMORY_ATTESTATION,
    audit_action_for,
    set_caller_memory,
    set_disclosure_posture,
)
from apps.api.agents.schemas import AgentOut
from apps.api.agents.service import publish_agent

# The languages the product sells, imported rather than respelled: this repo already
# carries three copies of that Literal and a fourth is the D-103 defect class.
from apps.api.agents.voices import Language
from apps.api.compliance.audit import write_audit
from apps.api.compliance.disclosure import TRUTHFUL_ANSWER_PROMISE
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

#: The four outcome tags, zero-filled into every `AgentStatsOut.outcomes` so a screen never
#: has to guard a missing key. Derived from the contract's Literal, never retyped (D-104):
#: `crm/models.OUTCOME_TAGS` renders the CHECK from the same type, so this map and the
#: column cannot come to disagree about what an outcome is.
OUTCOME_TAGS: tuple[str, ...] = get_args(OutcomeTag)

# No prefix — see the module docstring: the reads and the admin mutation live in
# different path spaces.
router = APIRouter(tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]
# Reads the tenant DIRECTORY cross-tenant so the audit row can be written on it; it
# unlocks no agent rows. The publish itself runs under `tenant_session`, in that
# tenant's own RLS scope.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]


class PublishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    engine_agent_ref: str
    status: str


@router.get(
    "/v1/agents",
    response_model=list[AgentOut],
    openapi_extra=permission_meta("agents:read"),
    summary="This account's agents — active, inactive, draft, or the archive",
    description=(
        "`status` selects one bucket: `live` (active — on the frontline), `paused` "
        "(inactive — switched off, reversible), `draft` (being written, never published) "
        "or `archived` (retired).\n\n"
        "**Omitting `status` returns everything EXCEPT archived agents.** The archive is "
        "history: it grows without limit while the working roster does not, so a default "
        "of 'everything' would let retired agents push live ones past the page bound. Ask "
        "for `status=archived` to read it."
    ),
)
async def list_agents(
    session: Session,
    # Bounded (D-302), at the service's own ceiling rather than at a number retyped here:
    # the query and its bound moved together, and two spellings of a page limit is how a
    # route comes to promise a page the reader will not serve.
    limit: int = Query(roster.AGENT_ROSTER_LIMIT, ge=1, le=roster.AGENT_ROSTER_LIMIT),
    status: AgentStatus | None = Query(None),
    _: Principal = Depends(requires("agents:read")),
) -> list[AgentOut]:
    """One roster query, one optional bucket (D-440) — `service.list_agents`, which is
    where the ordering and the archive default are argued.

    THE DEFAULT HIDES THE ARCHIVE, and the `description` above says so in the OpenAPI so
    the UI does not have to discover it.
    """
    return await roster.list_agents(session, limit=limit, status=status)


class AgentStatsOut(BaseModel):
    """What one agent has actually done — the numbers a roster card shows (D-440).

    A SEPARATE ROUTE FROM THE ROSTER, deliberately. The roster is opened on every
    navigation and reads a handful of small rows; this aggregates `calls`, which is the
    biggest table a tenant owns and the one that only ever grows. Folding it into
    `AgentOut` would make the cheapest screen in the product pay for the most expensive
    query on every render, and nothing about an agent's identity depends on it.

    Lifetime figures, not a window. A window is a second decision (how long? whose
    timezone?) that every caller would then have to agree with, and "this agent has taken
    4,102 calls" is the number a business owner asked for. `last_call_at` is what answers
    "is this one still being used", which is the question a window was standing in for.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    status: AgentStatus
    calls_total: int
    calls_inbound: int
    calls_outbound: int
    #: Calls the engine reported as `completed`. NOT "successful" — a completed call may
    #: have gone badly; it is the one that connected and ran to its end, as opposed to
    #: `no_answer`, `busy`, `voicemail` or `failed`.
    calls_connected: int
    #: Keyed by every value of `OUTCOME_TAGS` and zero-filled, so a screen can index it
    #: without guarding. A call the post-call pipeline has not tagged (or could not) is in
    #: `calls_total` and in none of these — the difference is calls awaiting extraction.
    #: NO DEFAULT, deliberately: a field with one is `outcomes?:` in the generated client,
    #: and every screen then guards a value the server always sends.
    outcomes: dict[str, int]
    #: LAST ACTIVE. The end of this agent's most recent call, falling back to when the call
    #: started and then to when we filed it — a queued dial that never rang still says the
    #: agent was used. NULL means it has never taken a call.
    last_call_at: datetime | None


@router.get(
    "/v1/agents/stats",
    response_model=list[AgentStatsOut],
    openapi_extra=permission_meta("agents:read"),
    summary="Call counts, outcomes and last-active for each of this account's agents",
)
async def agent_stats(
    session: Session,
    limit: int = Query(200, ge=1, le=200),
    _: Principal = Depends(requires("agents:read")),
) -> list[AgentStatsOut]:
    """One row per agent INCLUDING the archived ones, which is the opposite default to the
    roster above and is not an inconsistency.

    The roster answers "what can I work with", so the archive is noise. This answers "what
    has happened", and an archived agent's history is the largest part of the answer — a
    client who retired their old receptionist last week still needs the 4,000 calls it took
    to be somewhere. Nothing here is unbounded either way: it is one row per agent, and the
    agent list is what the `LIMIT` bounds.

    TWO QUERIES, NOT ONE, and the reason is which columns the tag counts would force into a
    GROUP BY. Counting outcomes in the first statement means naming each tag in a
    `FILTER (WHERE outcome_tag = '...')`, which retypes a vocabulary that already exists as
    a `Literal` (D-104) — the second statement groups by the tag instead, so the four names
    appear nowhere in this file's SQL and a fifth outcome needs no edit here at all.

    LEFT JOINed from `agents`, so an agent that has never taken a call is a row of zeroes
    rather than a gap the caller has to interpret.
    """
    totals = (
        await session.execute(
            text(
                "SELECT a.id, a.status, count(c.id), "
                "count(c.id) FILTER (WHERE c.direction = 'inbound'), "
                "count(c.id) FILTER (WHERE c.direction = 'outbound'), "
                "count(c.id) FILTER (WHERE c.status = 'completed'), "
                "max(coalesce(c.ended_at, c.started_at, c.created_at)) "
                "FROM agents a LEFT JOIN calls c ON c.agent_id = a.id "
                "WHERE a.deleted_at IS NULL "
                "GROUP BY a.id, a.status, a.created_at "
                "ORDER BY a.created_at LIMIT :limit"
            ),
            {"limit": limit},
        )
    ).all()
    tagged = (
        await session.execute(
            text(
                "SELECT c.agent_id, c.outcome_tag, count(*) FROM calls c "
                "WHERE c.outcome_tag IS NOT NULL GROUP BY c.agent_id, c.outcome_tag"
            )
        )
    ).all()
    by_agent: dict[UUID, dict[str, int]] = {}
    for agent_id, tag, count in tagged:
        by_agent.setdefault(agent_id, {})[str(tag)] = int(count)
    return [
        AgentStatsOut(
            agent_id=row[0],
            status=row[1],
            calls_total=int(row[2]),
            calls_inbound=int(row[3]),
            calls_outbound=int(row[4]),
            calls_connected=int(row[5]),
            outcomes={tag: by_agent.get(row[0], {}).get(tag, 0) for tag in OUTCOME_TAGS},
            last_call_at=row[6],
        )
        for row in totals
    ]


@router.get(
    "/v1/agents/{agent_id}",
    response_model=AgentOut,
    openapi_extra=permission_meta("agents:read"),
)
async def get_agent(
    agent_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> AgentOut:
    """ONE row, by id, under the caller's own RLS session — so a neighbour's agent id and
    an id nobody minted are the same 404 (hard rule 1)."""
    agent = await roster.agent_by_id(session, agent_id)
    if agent is None:
        raise ProblemError.not_found("Agent")
    return agent


# --- the agent's life: create, edit, activate, deactivate, archive, restore (D-440) ----
#
# CLIENT REALM, `org:manage`, WHICH IS THE OWNER'S PERMISSION — and that is the decision,
# argued the same way `set_disclosure` argues it below. An agent is the object a business
# owner builds and trains; the calls it makes go out under THEIR DLT Principal Entity and
# their identity, and whether their receptionist is on the line at 6pm on a Sunday is not a
# support ticket. `agents:write` would have been the neighbouring choice and is wrong here
# for the same two reasons it was wrong for the disclosure toggles: it is admin-only, so we
# would be deciding a client's roster for them, and D-22 makes impersonation read-only so
# an operator could not do it on their behalf either.
#
# WHAT DOES NOT MOVE TO THE CLIENT. The extraction schema stays admin-only (D-21's
# managed-service moat: a schema change regenerates prompt hints and needs a regression
# run), and so do the prompt-version, voice and experiment surfaces in this module's
# sibling routers. The `POST .../publish` route below is unchanged — an operator publishing
# on a client's behalf — and the two doors reach the SAME function: `publish_agent` is what
# earns `live`, here and there, so there is one definition of going live rather than two
# that drift.
#
# NOTHING HERE CAN REACH THE COMPLIANCE FLOOR. Creation writes both notices from the
# language templates and cannot be told otherwise; activation is `publish_agent`, which
# appends the truthful-answer directive through `compose_engine_prompt` and REFUSES a
# publish whose read-back shows the engine has lost it; and every transition is written to
# the hash-chained ledger. There is no argument, body field or state in this section that
# produces an agent without an AI disclosure on file.


class AgentCreateIn(BaseModel):
    """A new agent, in the three facts a business owner actually has at creation time.

    NO DISCLOSURE FIELDS, deliberately. Both sentences are generated from the language
    templates by `lifecycle.create_agent` and are not accepted from the caller: the create
    form is the one place a client is not yet thinking about TRAI, and a free-text field
    called "AI disclosure" on it is how an agent ends up announcing "Hi there!". Changing
    the wording is a reviewed surface, not a text input on the new-agent screen.

    NO SCRIPT FIELD either, and that is what `draft` is for: the agent exists, the owner
    writes and trains it, and `publish_agent` refuses to activate one with no prompt
    version by name (`agent_has_no_script`).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    #: Defaulted to `inbound` because D-38 says the receptionist is the headline
    #: capability, and because an agent that can only be called is the safe default: an
    #: `outbound` default would make "I clicked create" the first step of a dialling motion.
    direction: AgentDirection = "inbound"
    language_primary: Language = "te-IN"
    #: The cost-runaway guard. `null` means the platform default (600s), never unlimited.
    max_call_duration_s: int | None = Field(default=None, ge=CALL_CAP_MIN_S, le=CALL_CAP_MAX_S)

    @model_validator(mode="after")
    def _name_is_not_blank(self) -> AgentCreateIn:
        # `min_length` counts characters, so "   " passes it and reaches a NOT NULL column
        # as an agent nobody can find in a list. Stripped here rather than in the service
        # so the stored name and the validated name are the same string.
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name must not be blank")
        return self


class AgentUpdateIn(BaseModel):
    """What an owner may change about an existing agent. An OMITTED field is left alone.

    `DisclosureIn`'s shape and for its reason: a screen with three inputs sends whichever
    one moved, and a PATCH that could only send all three would make renaming an agent a
    read-modify-write race against a direction change.

    ⚠ **`llm_model` IS THE ONE FIELD WHERE `null` IS A VALUE AND NOT AN ABSENCE** (D-454),
    because it is the only one whose column is nullable and whose NULL MEANS something:
    "inherit the account's default". On every other field here `null` and "omitted" are
    the same request, so the model can read them the same way; on this one they are
    opposite requests — clear my choice, versus do not touch it — and a model that could
    not tell them apart would leave an owner unable to go back to the account default
    once they had chosen. `model_fields_set` is Pydantic v2's answer to exactly this and
    is what `set_llm_model` below reads: it carries which keys the CLIENT SENT, so an
    explicit `"llm_model": null` is distinguishable from a body that never mentioned it.
    The rejected alternative was a sentinel default (`UNSET = object()`), which works but
    puts a non-JSON-schema type in the OpenAPI document and therefore in every generated
    client.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    direction: AgentDirection | None = None
    language_primary: Language | None = None
    #: `null` clears the agent's own choice and falls back to the account default. A value
    #: outside the allow-list is refused by `validate_llm_model` with the permitted ones
    #: named — not by a `Literal` here, which would bake today's allow-list into the wire
    #: contract (see that function for the argument).
    llm_model: str | None = None

    @property
    def set_llm_model(self) -> bool:
        """Did the caller actually name `llm_model`? See the class docstring."""
        return "llm_model" in self.model_fields_set

    @model_validator(mode="after")
    def _at_least_one(self) -> AgentUpdateIn:
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name must not be blank")
        if (
            self.name is None
            and self.direction is None
            and self.language_primary is None
            and not self.set_llm_model
        ):
            raise ValueError("name at least one of name, direction, language_primary, llm_model")
        return self


class AgentLifecycleOut(BaseModel):
    """The result of a lifecycle move, as the screen that pressed the button needs it.

    NAMED `AgentLifecycleOut` AND NOT `LifecycleOut`, which is what it was called for an
    hour. `admin/routes.py` already has a `LifecycleOut` (the TENANT lifecycle), and two
    models of the same name in one app make FastAPI qualify BOTH in the OpenAPI document —
    so the admin console's generated type silently renamed itself to
    `apps__api__admin__routes__LifecycleOut` and every screen using it broke, from a change
    in a different module. The collision is invisible until the snapshot is regenerated,
    which is why it is recorded here rather than just fixed.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    status: AgentStatus
    #: False when the agent was ALREADY in this state — the second click, or the retry of
    #: a request whose response was lost. A success, not a conflict (RFC 9110 §9.2.2), and
    #: the signal the audit ledger keys off so a double-click writes one entry.
    changed: bool
    #: How many of this agent's numbers the voice platform was told to stop answering.
    #: Zero on an agent that was never published and on an engine that cannot route
    #: numbers; always zero on activate and restore, which bind nothing by themselves.
    numbers_released: int


async def _agent_row(session: AsyncSession, agent_id: UUID) -> AgentOut:
    """The freshly-written agent, read back through the ONE roster query.

    Read back rather than composed from the request body, so a create and a subsequent
    `GET` cannot disagree about a single field — the generated disclosure sentences and the
    server-composed `opening_line` are not in the body at all.
    """
    agent = await roster.agent_by_id(session, agent_id)
    if agent is None:  # pragma: no cover - written in this transaction, under this session
        raise ProblemError.not_found("Agent")
    return agent


@router.post(
    "/v1/agents",
    response_model=AgentOut,
    status_code=http_status.HTTP_201_CREATED,
    openapi_extra=permission_meta("org:manage"),
    summary="Create an agent (starts as a draft)",
    description=(
        "The agent is created in `draft`: it takes no calls and places none until it is "
        "activated, and it cannot be activated until it has a script.\n\n"
        "Both opening notices — the AI disclosure and the recording notice — are written "
        "for you from the chosen language and are switched on. They cannot be supplied "
        "here: every agent on this platform has an AI disclosure on file, the voice "
        "platform is verified against it on every publish, and no field on this form can "
        "change that."
    ),
)
async def create_agent_route(
    payload: AgentCreateIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> AgentOut:
    """Mint a draft agent for the caller's own tenant."""
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    agent_id = await lifecycle.create_agent(
        session,
        tenant_id=principal.tenant_id,
        name=payload.name,
        direction=payload.direction,
        language_primary=payload.language_primary,
        max_call_duration_s=payload.max_call_duration_s,
    )
    await write_audit(
        session,
        action="agent.created",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
    )
    return await _agent_row(session, agent_id)


@router.patch(
    "/v1/agents/{agent_id}",
    response_model=AgentOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Rename an agent, change its calling direction or language, or pick its model",
    description=(
        "Applies immediately. A live agent is re-published to the voice platform in the "
        "same transaction — including the numbers it answers, so switching a two-way "
        "agent to outbound-only really does stop it picking up — and if that push fails "
        "nothing is saved.\n\n"
        "`llm_model` is the one field where sending `null` MEANS something: it clears "
        "this agent's own choice so it follows the account default again. Omit the field "
        "entirely to leave the current choice alone. A model this platform does not run "
        "at all is refused with `llm_model_not_available`; one it supports but has no "
        "deployment for is refused with `llm_model_not_deployed`. Both name the models "
        "you can pick — read them off `GET /v1/organization/llm-defaults`, where a row "
        "with `is_available: false` is one of these refusals waiting to happen.\n\n"
        "An archived agent is refused: restore it first."
    ),
)
async def update_agent_route(
    agent_id: UUID,
    payload: AgentUpdateIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> AgentOut:
    assert principal.tenant_id is not None
    # BEFORE the write, so an unavailable model costs a 422 and no republish. The
    # validator is the same one the account-level routes call — one allow-list, one
    # refusal; the WORDING is the client's, because this is the client realm and the
    # person editing their own agent cannot act on an operator ground.
    llm_model = validate_llm_model(payload.llm_model, field="llm_model", audience="client")
    await lifecycle.update_agent(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        name=payload.name,
        direction=payload.direction,
        language_primary=payload.language_primary,
        llm_model=llm_model,
        set_llm_model=payload.set_llm_model,
    )
    await write_audit(
        session,
        action="agent.updated",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        # Field NAMES, never values (hard rule 6's neighbourhood): what an auditor needs
        # is which property of a live phone agent moved and when.
        #
        # `model_fields_set` RATHER THAN `model_dump(exclude_none=True)`, which is what
        # this line used to be: dumping and dropping the `None`s makes "the owner cleared
        # this agent's model choice" — a change to which model answers their phone —
        # audit as a request that changed nothing at all. What the client SENT is the
        # fact an auditor is reconstructing.
        #
        # ⚠ `llm_model` IS THE ONE FIELD WHOSE VALUE GOES IN, and the exception is argued
        # where the account-level write makes it (`llm_routes.py`): a model identifier is
        # a platform configuration constant, not a client's business copy and not anybody's
        # personal data, and WHICH model this agent was moved to is the entire fact an
        # auditor reconstructing a bill or a quality complaint is after. The field name
        # alone said that the model changed and refused to say what to. `null` is recorded
        # as itself — "put back on the account default" is a decision somebody took — and
        # the key is absent entirely when the caller did not name the field, which is the
        # same tri-state `set_llm_model` carries everywhere else on this path.
        #
        # A JOINED STRING AND NOT A LIST, which is what this was: `write_audit` hands the
        # summary to `redact_mapping`, and `_redact_value` collapses EVERY sequence to
        # `"[3 items]"` — deliberately, because a list is usually a payload. So the field
        # names this line exists to record never reached the log at all, and the entry
        # said only that an agent had been updated. `audit_log` has no summary column, so
        # the log line is the whole of this fact.
        summary=(
            {"fields": ",".join(sorted(payload.model_fields_set)), "llm_model": llm_model}
            if payload.set_llm_model
            else {"fields": ",".join(sorted(payload.model_fields_set))}
        ),
    )
    return await _agent_row(session, agent_id)


@router.post(
    "/v1/agents/{agent_id}/activate",
    response_model=AgentLifecycleOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Put the agent on the frontline (draft or inactive -> active)",
    description=(
        "Publishes the agent to the voice platform and reads it back to confirm the "
        "platform is running this script, this opening line and the answer it must give "
        "when a caller asks whether they are talking to an AI. Only then is it recorded "
        "as active; a platform that did not take the change is a refusal, not a warning."
        "\n\n"
        "Refused with `agent_has_no_script` if nothing has been written for it yet, and "
        "with `agent_archived` if it has been retired. An agent that is already active is "
        "a success that publishes nothing."
    ),
)
async def activate_agent_route(
    agent_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> AgentLifecycleOut:
    """Activation IS a publish — see `lifecycle.activate_agent` for why it cannot be a
    column write."""
    assert principal.tenant_id is not None
    result = await lifecycle.activate_agent(
        session, tenant_id=principal.tenant_id, agent_id=agent_id
    )
    return await _audited_move(session, result, "agent.activated", principal, request)


@router.post(
    "/v1/agents/{agent_id}/deactivate",
    response_model=AgentLifecycleOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Take the agent off the frontline (active -> inactive)",
    description=(
        "Stops it placing calls from the next dispatch tick, and tells the voice platform "
        "to stop answering the numbers bound to it — so an inactive agent really does go "
        "quiet on both legs. Everything is kept: the script, the numbers, the call "
        "history. Activate it again to put it back."
    ),
)
async def deactivate_agent_route(
    agent_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> AgentLifecycleOut:
    assert principal.tenant_id is not None
    result = await lifecycle.deactivate_agent(
        session, tenant_id=principal.tenant_id, agent_id=agent_id
    )
    return await _audited_move(session, result, "agent.deactivated", principal, request)


@router.post(
    "/v1/agents/{agent_id}/archive",
    response_model=AgentLifecycleOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Retire the agent — the console's Delete (draft or inactive -> archived)",
    description=(
        "An archived agent is never dialled and cannot be given to a campaign. It is NOT "
        "deleted: the agent, its scripts and every call it ever took stay readable, and "
        "it can be restored. Archiving releases any numbers the agent was answering.\n\n"
        "**An ACTIVE agent is refused with `agent_is_live` (409).** Switching off is a "
        "separate, deliberate decision (D-527): the client console shows this move as "
        "Delete on every row of the roster, and no single click there may take a working "
        "phone line down. Deactivate first, then archive."
    ),
)
async def archive_agent_route(
    agent_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> AgentLifecycleOut:
    assert principal.tenant_id is not None
    result = await lifecycle.archive_agent(
        session, tenant_id=principal.tenant_id, agent_id=agent_id
    )
    return await _audited_move(session, result, "agent.archived", principal, request)


@router.post(
    "/v1/agents/{agent_id}/restore",
    response_model=AgentLifecycleOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Bring an agent back out of the archive (archived -> inactive)",
    description=(
        "It comes back INACTIVE, not active. Nothing can prove the voice platform still "
        "holds a retired agent's configuration, and the only thing that establishes it is "
        "a publish — so activate it afterwards, deliberately."
    ),
)
async def restore_agent_route(
    agent_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> AgentLifecycleOut:
    assert principal.tenant_id is not None
    result = await lifecycle.restore_agent(
        session, tenant_id=principal.tenant_id, agent_id=agent_id
    )
    return await _audited_move(session, result, "agent.restored", principal, request)


async def _audited_move(
    session: AsyncSession,
    result: lifecycle.LifecycleResult,
    action: str,
    principal: Principal,
    request: Request,
) -> AgentLifecycleOut:
    """Write the ledger entry for a transition that ACTUALLY HAPPENED, then answer.

    `result.changed` is the whole reason this is not four copies of `write_audit`: a
    repeated click, or the retry of a request whose response was lost, is a success that
    moved nothing, and an audit row for it would claim a decision nobody took. Same signal
    and same reasoning as `integrations/routes.py::deactivate_endpoint` and as
    `set_disclosure` below, which iterates `result.changed` for the same purpose.
    """
    assert principal.tenant_id is not None
    if result.changed:
        await write_audit(
            session,
            action=action,
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="agent",
            object_id=str(result.agent_id),
            ip=client_request_ip(request),
            summary={"numbers_released": result.numbers_released},
        )
    return AgentLifecycleOut(
        agent_id=result.agent_id,
        status=result.status,
        changed=result.changed,
        numbers_released=result.numbers_released,
    )


@router.post(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish",
    response_model=PublishOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Create/update the agent on the engine and record its routing (admin realm, D-21)",
    description=(
        "The tenant is named in the path because an admin principal has no tenant of "
        "its own and the one way it could get one — impersonation — is read-only by "
        "D-22. Sending `X-Impersonate-Org` to this endpoint is still refused; publish "
        "from the admin console instead."
    ),
    tags=["admin"],
)
async def publish(
    tenant_id: UUID,
    agent_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> PublishOut:
    """Publish inside the tenant's own RLS scope, audit on the admin session.

    `admin_db` opens the tenant DIRECTORY only (`app.admin` widens `USING` on
    `organizations` alone, migration b57e2f9c4a13) — it does not unlock `agents`, so
    the engine call and the `engine_agent_ref` write must happen under
    `tenant_session`. An agent belonging to a different tenant is simply invisible
    there, which makes "not found" and "belongs to someone else" the same answer.

    `publish_agent` reaches the voice engine, so it stays OUTSIDE the audit session's
    transaction: a slow vendor call must not hold the audit row's transaction open,
    and the audit entry should describe what actually happened.
    """
    async with tenant_session(tenant_id) as scoped:
        ref = await publish_agent(scoped, tenant_id=tenant_id, agent_id=agent_id)
    await write_audit(
        session,
        action="agent.published",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
    )
    return PublishOut(agent_id=agent_id, engine_agent_ref=ref, status="live")


class DisclosureIn(BaseModel):
    """Which notices this agent volunteers. `null` on a field leaves it alone.

    Two nullable booleans rather than two endpoints: the pair is one posture, a screen
    with two switches sends whichever one moved, and a PATCH that could only send both
    would make flipping one switch a read-modify-write race against the other.
    """

    model_config = ConfigDict(extra="forbid")

    ai_disclosure_enabled: bool | None = None
    recording_notice_enabled: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> DisclosureIn:
        if self.ai_disclosure_enabled is None and self.recording_notice_enabled is None:
            # A body that names nothing is a client bug, and answering 200 for it would
            # write an audit row describing a decision nobody took.
            raise ValueError("name at least one of ai_disclosure_enabled, recording_notice_enabled")
        return self


class DisclosureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    ai_disclosure_enabled: bool
    recording_notice_enabled: bool
    #: What callers now hear first. Empty = the agent volunteers neither notice.
    opening_line: str
    #: Did the voice platform get the change? False on an agent that is not live yet —
    #: there is nothing on the platform to update, and the first publish carries it.
    engine_synced: bool
    #: The one behaviour these switches do not reach, in the words the API owns.
    truthful_answer_rule: str = TRUTHFUL_ANSWER_PROMISE


@router.patch(
    "/v1/agents/{agent_id}/disclosure",
    response_model=DisclosureOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Switch the AI disclosure and the recording notice on or off (D-163)",
    description=(
        "Each opening notice is separately controllable, per agent, on inbound and "
        "outbound agents alike. A notice switched off means the agent does not VOLUNTEER "
        "that fact at the start of the call.\n\n"
        "It does not change what the agent says when a caller ASKS. Asked whether they "
        "are speaking to a human, the agent says it is an AI assistant; asked whether "
        "the call is recorded, it says yes. That is composed server-side, appended to "
        "every agent's instructions after the script, and verified against the voice "
        "platform on every publish — no script can withdraw it.\n\n"
        "Switching the recording notice off does not stop the call being recorded, and "
        "does not discharge the client's own notice obligation under the DPDP Act; it "
        "moves where that notice is given. Every flip is written to the audit log.\n\n"
        "Applies immediately: a live agent is re-published to the voice platform in the "
        "same transaction, so the screen never claims a posture the platform is not "
        "running."
    ),
)
async def set_disclosure(
    agent_id: UUID,
    payload: DisclosureIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> DisclosureOut:
    """`org:manage`, which is the CLIENT OWNER's permission — and that is the decision.

    The client is the Principal Entity: the calls are made under their identity and their
    DLT templates, and the disclosure posture is their legal exposure to carry (D-163
    records the regulatory position and the risk the founder accepted). So the switch
    belongs to the person who answers for it. `agents:write` would have been the
    neighbouring choice and is wrong here: it is admin-only, so we would be deciding a
    client's compliance posture for them and being unable to show them the switch.

    Two consequences of `org:manage` being in `MUTATING_PERMISSIONS`, both intended: an
    admin-realm token without `X-Impersonate-Org` is refused by the client verifier, and
    an impersonating operator is refused by D-22's read-only rule. Nobody but the client
    flips these, which is exactly the accountability this decision rests on.

    THE AUDIT ROW NAMES THE TOGGLE AND THE VALUE IN ITS `action`, not in a summary:
    `write_audit` does not persist summaries (BACKEND-PATTERNS §7 — they go to the log
    stream), and "who switched the AI disclosure off, and when" has to survive in the
    hash-chained ledger to be worth anything. One row per toggle that actually moved.

    `write_audit` runs AFTER `set_disclosure_posture`, which reaches the voice platform,
    for `publish`'s reason above: a slow vendor call must not hold the audit row's
    transaction open, and the entry should describe what actually happened.
    """
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    result = await set_disclosure_posture(
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        ai_disclosure_enabled=payload.ai_disclosure_enabled,
        recording_notice_enabled=payload.recording_notice_enabled,
    )
    for field in result.changed:
        await write_audit(
            session,
            # `field` IS the column name and IS the attribute name on the result — one
            # spelling, so a third toggle needs no edit here.
            action=audit_action_for(field, enabled=bool(getattr(result, field))),
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            # The CALLER's address, never the socket peer — behind nginx that is our own
            # edge (`core/auth.client_request_ip`, `scripts/check_audit_ip.py`).
            ip=client_request_ip(request),
            summary={"engine_synced": result.engine_synced},
        )
    return DisclosureOut(
        agent_id=result.agent_id,
        ai_disclosure_enabled=result.ai_disclosure_enabled,
        recording_notice_enabled=result.recording_notice_enabled,
        opening_line=result.opening_line,
        engine_synced=result.engine_synced,
    )


class CallerMemoryIn(BaseModel):
    """Switch caller continuity on or off for one agent.

    ONE BOOLEAN AND NOT A PAIR, unlike `DisclosureIn` above, and the difference is the
    decision rather than the shape of the screen: remembering a caller and rescheduling a
    call-back are "two linked abilities, always on or off together" (D-513), so there is
    one column and there is nothing here for a second field to name. A client who could
    switch one off and keep the other would keep the ability that REUSES what was
    remembered while withdrawing the one their callers were told about.

    `accept` is the client saying yes to the sentence the refusal handed them. It is only
    read the FIRST time an account switches this on: the attestation is about the
    business, so it is asked once and then stands
    (`organizations.caller_memory_attested_at`).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    #: True = "I confirm the statement you showed me." Ignored when switching OFF, and
    #: ignored on an account that has already confirmed it — a permission is asked for
    #: when the risk is taken, not every time it is exercised.
    accept: bool = False


class CallerMemoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    enabled: bool
    #: What callers now hear first. When this is on it GAINS the sentence telling them a
    #: short note is kept; when it goes off it loses it. Shown rather than described, so
    #: the screen and the phone line cannot say different things.
    opening_line: str
    #: Did the voice platform get the change? False on an agent that is not live yet.
    engine_synced: bool
    #: When this business confirmed what its calls collect. Null until they have.
    attested_at: datetime | None = None
    #: Who confirmed it, by name — so a second agent being switched on without being
    #: asked again is explicable on the screen rather than surprising. Null when nobody
    #: has confirmed, and when the person who did has since left the account.
    attested_by_name: str | None = None
    #: The statement a client confirms to switch this on, so the screen renders the same
    #: words the refusal does.
    attestation: str = CALLER_MEMORY_ATTESTATION


@router.patch(
    "/v1/agents/{agent_id}/caller-memory",
    response_model=CallerMemoryOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Let an agent remember returning callers, and book call-backs",
    description=(
        "Two abilities, always on or off together. Your agents remember the people they "
        "have spoken to and can greet a returning caller with what they asked about last "
        "time; and when someone asks to be called back at a particular time, that "
        "follow-up is booked for exactly then and dials with everything already "
        "learned.\n\n"
        "Off unless you switch it on. Switched on, the agent says at the start of every "
        "call that a short note is kept — that sentence cannot be switched off "
        "separately.\n\n"
        "What is kept is a short note of what the caller wanted, what happened, and any "
        "preference they stated, such as the language they like or when they prefer to "
        "be called. It is used only for that person's own future calls with you, is "
        "never shared, and is deleted after 180 days or sooner if they ask.\n\n"
        "The first time anyone in your account switches this on you are asked to confirm "
        "what these calls collect. Some kinds of business cannot use it at all.\n\n"
        "Applies immediately: a live agent is updated on the voice platform in the same "
        "transaction, so the screen never claims something the phone line is not doing."
    ),
)
async def set_caller_memory_route(
    agent_id: UUID,
    payload: CallerMemoryIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> CallerMemoryOut:
    """`org:manage`, for `set_disclosure` above's reason and one more of its own.

    The disclosure switches are the client's legal exposure to carry as Principal Entity.
    This one is that AND a durable-data decision: switching it on starts writing a record
    about their callers that a DPDP request will one day be answered about, and the
    account attests to what those calls collect in the same act. `agents:write` is
    admin-only, so it would have meant us deciding to keep notes on a client's callers on
    their behalf — which is the one shape of this feature nobody could defend.

    THE AUDIT ROW NAMES THE DIRECTION IN ITS `action`, for `audit_action_for`'s reason:
    `write_audit` does not persist summaries, so "who switched caller memory on, and
    when" has to be in a column to survive in the hash-chained ledger. One row per flip
    that actually moved — a re-assertion of the state the agent is already in writes none.
    """
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    result = await set_caller_memory(
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        enabled=payload.enabled,
        # THE ACTOR, ONLY WHEN THEY ACCEPTED. Passing the principal unconditionally would
        # record an attestation for a client who never saw the sentence — the request
        # that switches memory on WITHOUT `accept` is exactly the one that must be
        # refused so the screen can show it to them.
        attested_by=principal.user_id if payload.accept else None,
    )
    if not result.unchanged:
        await write_audit(
            session,
            action=f"agent.caller_memory_{'enabled' if result.enabled else 'disabled'}",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={"engine_synced": result.engine_synced},
        )
    return CallerMemoryOut(
        agent_id=result.agent_id,
        enabled=result.enabled,
        opening_line=result.opening_line,
        engine_synced=result.engine_synced,
        attested_at=result.attested_at,
        attested_by_name=result.attested_by_name,
    )


# A/B script testing (ROADMAP M3) lives in `agents/experiment_routes.py` and is mounted
# in `main._mount_routers` with every other router. It was briefly ADOPTED here with
# `router.routes.extend(...)` because the slice that built it could not edit `main.py`;
# that worked, but it made this the one router in the app mounted by a neighbour, and
# two ways to mount a router is the drift CLAUDE.md names even when both work.

__all__ = ["router"]
