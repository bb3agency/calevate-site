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
from typing import Annotated, Any, get_args
from uuid import UUID

from calevate_shared.engine import DisclosurePosture, compose_opening_line
from calevate_shared.extraction import ExtractionField, OutcomeTag
from fastapi import APIRouter, Depends, Query, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import lifecycle
from apps.api.agents.llm_models import (
    LlmModelSource,
    resolve_llm_model,
    validate_llm_model,
)
from apps.api.agents.models import (
    CALL_CAP_MAX_S,
    CALL_CAP_MIN_S,
    AgentDirection,
    AgentStatus,
)
from apps.api.agents.publishing import audit_action_for, set_disclosure_posture
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


class AgentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    #: TYPED, not `str` (D-440). Both columns carry a CHECK constraint rendered from these
    #: exact Literals (`agents/models.py`), `tests/orm_schema_fidelity_test.py` proves the
    #: constraint is really in the database, and a generated TypeScript client that gets a
    #: union here can exhaustively switch on it instead of comparing strings. A row that
    #: somehow held anything else fails serialization loudly, which is the same trade
    #: `_load_agent`'s direction TypeGuard makes and for the same reason: a status the
    #: platform has never heard of, on an agent answering a client's phone, is not a thing
    #: to render.
    direction: AgentDirection
    #: `live` IS "active" and `paused` IS "inactive" — the labels are the UI's, the
    #: vocabulary is the database's, and `agents/models.AgentStatus` argues why they differ.
    status: AgentStatus
    #: Set only while `status == "archived"`; a CHECK constraint holds the pair together.
    archived_at: datetime | None
    language_primary: str
    # THE LEGACY BUNDLE, kept on the wire for step 1 of D-163's two-step deprecation:
    # both sentences joined whatever the toggles say. Read it as "the notices this agent
    # HAS", never as "what it says" — `opening_line` below is what it says.
    disclosure_line: str
    # THE SPLIT (D-163). Shown to the client verbatim: they are legally the Principal
    # Entity, so they need to be able to read what their agent announces — and, now that
    # each half is theirs to switch off, to see the two halves separately.
    ai_disclosure_line: str
    ai_disclosure_enabled: bool
    recording_notice_line: str
    recording_notice_enabled: bool
    #: What a caller actually hears first, composed by the server from the two toggles.
    #: Empty string = this agent volunteers neither notice and opens on its script.
    #: Composed here rather than left to the screen because a UI that re-joined the two
    #: sentences itself would be a second implementation of a compliance rule.
    opening_line: str
    #: The one sentence no toggle reaches, in words a client can read. Server-composed for
    #: the same reason the lane table's `why` strings are: a screen that paraphrases this
    #: is a screen that can accidentally promise the opposite.
    truthful_answer_rule: str = TRUTHFUL_ANSWER_PROMISE
    engine: str
    published: bool
    #: HOW MANY LINES THIS AGENT ANSWERS IN PARALLEL — the honest per-agent deployment
    #: fact, and deliberately the only one (D-440). Inbound concurrency is a per-number
    #: binding at the engine and the vendor documents no inbound limit, so a live agent
    #: bound to three numbers picks up three simultaneous calls. OUTBOUND concurrency is
    #: not a property of an agent at all: it is an account-level pool shared by every
    #: campaign on the platform (`workers/campaign_dispatch.py`), so there is no per-agent
    #: number that could be true, and this response does not invent one.
    #:
    #: Counts the numbers BOUND to the agent in our records. A non-live agent shows its
    #: bindings too — they are what activating it would start answering — and the engine
    #: is told to release them on deactivate and archive.
    inbound_number_count: int
    #: WHAT WAS CHOSEN ON THIS AGENT, and `null` means "inherit the account's default"
    #: rather than "no model" (D-454). It is deliberately not the same field as
    #: `llm_model_effective` below: a screen that showed only the effective value could
    #: not tell an owner whether clearing this input would change anything.
    llm_model: str | None
    #: WHAT WILL ACTUALLY RUN, after `agent -> organization -> platform`. Never null:
    #: there is always an answer, and the field that says WHERE it came from is beside it
    #: so the screen never has to present a platform default as the client's own choice.
    llm_model_effective: str
    #: Which rung supplied `llm_model_effective`. A closed vocabulary, so a generated
    #: client can switch on it exhaustively (`agents/llm_models.LlmModelSource`).
    llm_model_source: LlmModelSource
    extraction_fields: list[ExtractionField] = []


class PublishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    engine_agent_ref: str
    status: str


#: The roster query, spelled once and reached from both routes below (D-302).
#:
#: It used to live inside `list_agents`, and `get_agent` CALLED THAT HANDLER and filtered
#: the result in Python — "RLS-scoped; small list per tenant in v1", said the comment.
#: Bounding the list turned that belief into a defect a reader could see: with a `LIMIT`
#: on the roster, the 201st agent of an account would be a 404 on its own detail route,
#: found by nothing except the person whose screen it is. Asking for the one row by id is
#: also the query that should always have been here — one indexed lookup instead of a
#: scan of every agent plus their extraction schemas, on the route a dashboard opens most.
#:
#: The inbound-number count is a CORRELATED SUBQUERY rather than a fourth join, because
#: `phone_numbers` is one-to-many against `agents` while `extraction_schemas` is joined by
#: primary key: a `LEFT JOIN ... GROUP BY` would multiply every agent by its numbers and
#: then need every selected column in the grouping key, including the schema's JSONB. The
#: subquery is one index lookup on `phone_numbers.agent_id` per row of a per-tenant list
#: this route already bounds at 200.
_AGENT_ROSTER = (
    "SELECT a.id, a.name, a.direction, a.status, a.language_primary, "
    "a.disclosure_line, a.engine, a.engine_agent_ref, es.fields, "
    "a.ai_disclosure_line, a.ai_disclosure_enabled, "
    "a.recording_notice_line, a.recording_notice_enabled, a.archived_at, "
    "(SELECT count(*) FROM phone_numbers pn WHERE pn.agent_id = a.id), "
    # The two rungs of the model fallback that live in the database (D-454). Joined
    # rather than fetched per row: `organizations` is one PK lookup and RLS makes it the
    # caller's own row, and resolving the fallback from two statements would let an
    # account default change land between them — a roster whose rows disagree about which
    # model the account runs.
    "a.llm_model, o.default_llm_model "
    "FROM agents a LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
    "LEFT JOIN organizations o ON o.id = a.tenant_id "
    "WHERE a.deleted_at IS NULL"
)


def _agent_out(r: Any) -> AgentOut:
    # Through the ONE resolver (`agents/llm_models.py`), so the roster, the detail route
    # and the config the engine is actually sent cannot disagree about which model an
    # agent runs or which level chose it.
    resolved = resolve_llm_model(agent_model=r[15], organization_model=r[16])
    return AgentOut(
        id=r[0],
        name=r[1],
        direction=r[2],
        status=r[3],
        language_primary=r[4],
        disclosure_line=r[5],
        engine=r[6],
        published=bool(r[7]),
        extraction_fields=[ExtractionField.model_validate(f) for f in (r[8] or [])],
        ai_disclosure_line=r[9],
        ai_disclosure_enabled=bool(r[10]),
        recording_notice_line=r[11],
        recording_notice_enabled=bool(r[12]),
        archived_at=r[13],
        inbound_number_count=int(r[14]),
        llm_model=r[15],
        llm_model_effective=resolved.model,
        llm_model_source=resolved.source,
        # Through the ONE composer, so the roster, the publish path and the engine
        # cannot disagree about what this agent opens with (D-163).
        opening_line=compose_opening_line(
            DisclosurePosture(
                ai_disclosure_line=str(r[9]),
                ai_disclosure_enabled=bool(r[10]),
                recording_notice_line=str(r[11]),
                recording_notice_enabled=bool(r[12]),
            )
        ),
    )


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
    # Bounded (D-302). An agent list is short in every account we have, and "short in
    # every account we have" is exactly the assumption that stops being true without
    # anyone editing this file — each row here carries the agent's whole extraction
    # schema, so the response grows in two dimensions at once.
    limit: int = Query(200, ge=1, le=200),
    status: AgentStatus | None = Query(None),
    _: Principal = Depends(requires("agents:read")),
) -> list[AgentOut]:
    """One roster query, one optional bucket (D-440).

    THE DEFAULT HIDES THE ARCHIVE, and that is the one surprising thing here. Every other
    filter in this repo defaults to "no filter"; this one cannot, because the set it would
    include is the only unbounded one — a client who retires an agent a month for two years
    has an archive longer than the `LIMIT`, and the agents they actually use would fall off
    the end of their own roster with nothing on the screen to say so. The description says
    it in the OpenAPI so the UI does not have to discover it.

    `ORDER BY` is by status bucket first and creation second, so the archive — when it is
    asked for — reads newest-retirement-first and the working roster keeps the stable order
    it had. `archived_at DESC NULLS LAST` does both in one clause: it is NULL for every
    non-archived row, which leaves those rows to the second key.
    """
    rows = (
        await session.execute(
            text(
                f"{_AGENT_ROSTER} "
                # Two spellings of one parameter, and neither is caller text: the
                # filter applies when it is given, and the `IS NULL` arm is what "no
                # bucket asked for" means. An f-string branch here would be two SQL
                # statements to keep in step (`scripts/check_raw_sql.py`).
                #
                # CAST because the parameter's only other appearance is compared to a
                # `character varying` column, which leaves `$1 IS NULL` with no type to
                # infer and makes Postgres refuse the whole statement as ambiguous.
                "AND (CAST(:status AS text) IS NULL AND a.status <> 'archived' "
                "OR a.status = CAST(:status AS text)) "
                "ORDER BY a.archived_at DESC NULLS LAST, a.created_at LIMIT :limit"
            ),
            {"limit": limit, "status": status},
        )
    ).all()
    return [_agent_out(r) for r in rows]


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
    row = (
        await session.execute(
            text(f"{_AGENT_ROSTER} AND a.id = :aid"),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _agent_out(row)


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
    row = (
        await session.execute(text(f"{_AGENT_ROSTER} AND a.id = :aid"), {"aid": agent_id})
    ).first()
    if row is None:  # pragma: no cover - written in this transaction, under this session
        raise ProblemError.not_found("Agent")
    return _agent_out(row)


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
    # refusal, one wording.
    llm_model = validate_llm_model(payload.llm_model, field="llm_model")
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
        summary={"fields": sorted(payload.model_fields_set)},
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
    summary="Retire the agent (draft, active or inactive -> archived)",
    description=(
        "An archived agent is never dialled and cannot be given to a campaign. It is NOT "
        "deleted: the agent, its scripts and every call it ever took stay readable, and "
        "it can be restored. Archiving an active agent also releases the numbers it was "
        "answering."
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


# A/B script testing (ROADMAP M3) lives in `agents/experiment_routes.py` and is mounted
# in `main._mount_routers` with every other router. It was briefly ADOPTED here with
# `router.routes.extend(...)` because the slice that built it could not edit `main.py`;
# that worked, but it made this the one router in the app mounted by a neighbour, and
# two ways to mount a router is the drift CLAUDE.md names even when both work.

__all__ = ["router"]
