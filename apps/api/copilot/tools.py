"""The copilot's READ tools: what it may look up about the tenant's own business, and
the four properties that make that safe.

WHY THIS EXISTS AS A REGISTRY RATHER THAN AS A HANDFUL OF FUNCTIONS THE LOOP KNOWS ABOUT. A tool
is three things that must never drift apart — the schema the model is shown, the
permission the caller must hold, and the code that runs — and a design that keeps them in
three places is a design where a tool gains a parameter the executor ignores, or is
described to the model without the permission check the route would have applied. `ReadTool`
holds all three on one object and `READ_TOOLS` is the only enumeration of them, so
`read_tool_schemas()` (what the model sees) and `run_read_tool()` (what actually runs)
cannot disagree about what exists.

THE FOUR PROPERTIES, each of which is a rule from CLAUDE.md rather than a preference:

1. **EVERY TOOL RUNS IN ITS OWN SHORT-LIVED `tenant_session` (hard rule 1).** Tenancy is
   not a `WHERE` clause here and no tool takes a tenant id as a query parameter: the
   session sets `app.tenant_id` and Postgres RLS decides what the query can see. That is
   also why the session is opened INSIDE the tool and closed immediately — `copilot/
   routes.py` deliberately takes no `Depends(db)` so that no pooled connection is held
   across a provider round trip, and a registry that held one for the length of a stream
   would quietly undo the reason that route is affordable at all.
2. **PERMISSION IS ENFORCED IN CODE, NEVER BY THE PROMPT.** `run_read_tool` asks
   `rbac.role_has` the same question `core/auth.requires` asks, before it opens a session.
   A sentence in a system prompt is not an access control: OWASP GenAI LLM Top 10 2026
   LLM01 #4 is explicit that capability lives in application code, and `service.
   validate_fill` already makes that argument for the WRITE surface. This is the read one.
3. **READ-ONLY MEANS READ-ONLY.** Every executor below is a call to an existing service
   function that only SELECTs. Nothing here inserts, updates or deletes, and nothing here
   meters, dials, publishes or spends — the metering for the whole answer is one row pair
   written by the route after the loop finishes (`crm/assist.meter_assist`).
4. **NOTHING PERSONAL GOES BACK TO THE MODEL (hard rule 5 / D-127 G-2).** No transcript
   text and no extraction payload is returned by any tool, and every assembled result goes
   through `redact()` — the same primitive `sanitize.assert_redacted` uses on the way IN —
   so a lead's number reaches the model as `[phone ••10]` and not as digits. That is a
   BACKSTOP and not the plan: the results below are composed from names, statuses and
   counts on purpose. The guard is there because the plan is a promise and the guard is a
   check, which is exactly the argument `assert_redacted` makes about the ingress half.

RESULTS ARE COMPACT TEXT, NOT JSON. Every token here is paid for on every subsequent turn
of the loop — a tool result stays in the message list for the rest of the request — so the
rows are rendered as short lines a model reads as well as it reads a JSON object, with
NAMES rather than uuids wherever a name exists (a uuid is unreadable to the person the
model is answering and unusable to a model that cannot dereference it) and an explicit
`showing N of M` whenever the cap bit. A silently truncated list is how a copilot comes to
tell somebody they have ten leads when they have forty-seven.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, get_args
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import roster
from apps.api.campaigns import service as campaigns_service
from apps.api.copilot.prompt import function_tool
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.logging import get_logger
from apps.api.core.rbac import Permission, role_has
from apps.api.crm import service as crm_service
from apps.api.crm.models import CALL_STATUSES
from apps.api.crm.performance import performance
from apps.api.crm.schemas import LeadStatus
from apps.api.db.session import admin_session, tenant_session
from apps.api.retrieval.service import look_up
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The largest number of rows any read tool will return in one call.
#:
#: A HARD SERVER-SIDE CEILING, not a default the model may raise. The model asks for a
#: `limit`, and a model that asks for 500 is asking for a prompt that costs more on every
#: remaining turn of the loop than the answer is worth. Twenty-five is "enough rows to
#: characterise a list" — the copilot answers questions ABOUT a list ("how many are hot?",
#: "who called yesterday?"), and the screen behind it is where somebody reads all of them.
MAX_ROWS: Final = 25

#: What a tool returns when it was given no rows to work with. Said as a sentence rather
#: than as an empty string because an empty tool result reads to a model as a failure, and
#: "there is nothing yet" is a real and useful answer on a new account.
_NOTHING = "No rows — this account has none yet."

#: How many read tools one model turn may actually run. A turn that asks for twelve
#: lookups is a turn that has stopped answering a question, and each one costs a database
#: round trip against a shared pool. The extras are refused with a sentence the model can
#: act on rather than silently dropped (`service._run_tool_loop` applies it).
MAX_CALLS_PER_TURN: Final = 4

#: The longest question `search_knowledge` will carry to the retrieval port.
#:
#: TRUNCATED RATHER THAN REFUSED, and this is the one place in this module where that is
#: the right way round. `RetrievalRequest.question` is bounded at 2000 characters (D-302)
#: and the argument arrives from a MODEL — so an over-long question is a generation quirk,
#: not a caller mistake somebody could act on, and refusing would raise a ValidationError
#: through a stream a person is reading in order to punish nobody. Kept in step with the
#: port's own ceiling by being the same number.
_MAX_QUESTION_CHARS: Final = 2000


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Who is asking, reduced to the two facts a read tool needs.

    IDS AND A ROLE NAME, never a `Principal` and never a session. The tenant id is what
    scopes the RLS session; the role is what `role_has` judges. Carrying the whole
    `Principal` would put an auth object inside a loop that also holds model output, and
    carrying a session would defeat the "no connection across a provider call" property
    the route's docstring is built on.

    `role is None` is a real state (an unauthenticated or role-less principal) and it
    refuses every tool, because `role_has` has nothing to answer with.
    """

    #: `None` IS A REAL STATE SINCE D-499, not an oversight. An operator on the admin
    #: console's own screens has no tenant at all, and the admin copilot's platform tools
    #: are answered from an `admin_session()` that needs none. A `tenant`-scoped tool asked
    #: with `None` refuses with a sentence saying no account is open — it never falls back
    #: to some default tenant, which is the one failure mode this Optional could have.
    tenant_id: UUID | None
    role: str | None


#: One tool's executor: a tenant-scoped session, WHO IS ASKING, and the model's
#: already-parsed arguments in, one compact human-readable string out. It never raises for
#: an ordinary empty result — "nothing found" is an answer — and it never returns a shape
#: the caller has to interpret, because the consumer is a language model and not a client.
#:
#: **THE `ToolContext` IS IN THE SIGNATURE, AND IT USED NOT TO BE.** Most executors do not
#: want it — RLS is the tenancy control and a `WHERE tenant_id = ...` in a tool would be
#: the second copy of it this module's docstring refuses. `search_knowledge` does: the
#: retrieval port keys its CACHE on the tenant (`retrieval/cache.py`), and a cache key is
#: not something RLS can supply. Threading it through the registry is `write_tools.
#: Executor`'s shape verbatim (`Callable[[AsyncSession, ToolActor, Mapping], ...]`), which
#: is the point — two registries in one package with two calling conventions is the drift
#: CLAUDE.md calls a defect even when both work. The executors that do not need it say
#: `del context` on their first line, exactly as `write_tools` does.
_Executor = Callable[[AsyncSession, "ToolContext", Mapping[str, Any]], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class ReadTool:
    """One read-only tool: its schema, its permission and its code, on one object."""

    name: str
    description: str
    #: The JSON Schema for `function.parameters`, in the SAME conservative subset
    #: `prompt.set_fields_tool` uses and for the same reason: every property in
    #: `required`, `additionalProperties: false` on every object, and no `pattern`,
    #: `format`, `minimum` or `minItems`. Bounds are enforced in this module, in Python,
    #: where they hold whether or not the provider honoured `strict`.
    parameters: dict[str, Any]
    #: The permission a caller must hold, spelled exactly as the route serving the same
    #: data spells it — `GET /v1/crm/performance` is `calls:read`, `GET /v1/leads` is
    #: `leads:read`, `GET /v1/campaigns` is `leads:read`, `GET /v1/agents` is
    #: `agents:read`. A tool that judged itself by a looser permission than its own screen
    #: would be a way around that screen.
    permission: Permission
    run: _Executor
    #: WHICH SESSION `run_read_tool` opens for this tool, and it is on the TOOL rather than
    #: inferred from the realm because it is a property of the query, not of the caller
    #: (D-499):
    #:
    #: * `tenant` — a `tenant_session(context.tenant_id)`. Tenancy is RLS and never a
    #:   `WHERE` clause (module docstring, property 1). Refused when no tenant is in scope.
    #: * `platform` — an `admin_session()`, the only session that can enumerate tenants
    #:   (migration `b57e2f9c4a13`). Every such tool reads either the directory or a
    #:   `platform_*` table that carries no policy; none reads a tenant table cross-tenant.
    #:
    #: THERE IS NO `local` SCOPE, and `search_runbooks` — which reads a process-local index
    #: and needs no database — is `platform` anyway. A nullable session threaded through
    #: `_Executor` would put an `AsyncSession | None` in front of every executor that DOES
    #: use one, to save one `set_config` round trip on a tool an operator calls during an
    #: incident. One calling convention, stated cost.
    scope: Literal["tenant", "platform"] = "tenant"


# --- rendering helpers ----------------------------------------------------------------


def _clean(text: str) -> str:
    """One tool result, safe to put in a prompt.

    TWO PASSES, in this order, and both are the ingress half of `sanitize`'s two
    directions applied to a source that is not the browser. `redact` first, because it is
    the PII backstop and it must see the digits as stored; `strip_invisible` second,
    because a lead's name is text a caller typed and a tag-block character in it is a
    prompt-injection carrier (OWASP LLM01 #5) — `prompt.py::_text` does exactly this to
    the screen block for exactly this reason.
    """
    return strip_invisible(redact(text).text)


def _cap(limit: object, *, default: int = 10) -> int:
    """The model's `limit` argument as a number this server is willing to serve.

    Clamped rather than refused: a model that asks for 100 rows has made no error a person
    can act on, and refusing the call would spend a turn teaching it a bound the schema
    cannot express (`minimum`/`maximum` are outside the strict subset — see `ReadTool.
    parameters`). A non-number, or `null` for "the model did not choose", takes the
    default.
    """
    if isinstance(limit, bool) or not isinstance(limit, int | float):
        return default
    return max(1, min(int(limit), MAX_ROWS))


def _listing(
    rows: list[str],
    *,
    total: int | None = None,
    shown_of: str = "rows",
    cap: int = MAX_ROWS,
    nothing: str = _NOTHING,
) -> str:
    """Rows as lines, with the truncation note when the cap bit.

    `total is None` means the underlying reader does not know how many exist — `list_calls`
    and `list_campaigns` are `LIMIT`ed with no count beside them, where `list_leads` returns
    one. A FULL page from such a reader is therefore reported as "there may be more" rather
    than as a total: "25 calls" would be a number this code has not measured, which is hard
    rule 11 applied to our own data rather than to a vendor's.

    `cap` is the ceiling THIS reader was asked for, and it is a parameter because not every
    reader's ceiling is `MAX_ROWS`: `search_knowledge` asks the retrieval port for a handful
    of passages, not twenty-five rows, and a full page of four would otherwise be reported
    as complete when it is not. Hard-coding `MAX_ROWS` here is what made that silent.
    """
    if not rows:
        # `nothing` is a PARAMETER since D-499 because the empty sentence is realm-specific:
        # "this account has none yet" is right on a client's screen and wrong in the admin
        # console, where the population is every account on the platform.
        return nothing
    if total is not None and total > len(rows):
        head = f"Showing {len(rows)} of {total} {shown_of}:"
    elif total is None and len(rows) == cap:
        head = f"Showing {len(rows)} {shown_of} (there may be more):"
    else:
        head = f"{len(rows)} {shown_of}:"
    return "\n".join([head, *rows])


def _pct(value: object) -> str:
    return "n/a" if value is None else f"{value}%"


# --- the executors --------------------------------------------------------------------


async def _business_snapshot(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`crm/performance.performance` as a paragraph.

    THE WHOLE TAB IS NOT SENT. `performance` returns a 24-bucket IST histogram and an
    outcome map, and pasting both into a prompt spends tokens on the 3am bucket every
    subsequent turn re-reads. The three busiest hours and the four commonest outcomes are
    what a question about "when are we busy" or "how are calls going" is actually answered
    from; the screen is where the whole histogram lives.
    """
    # Tenancy is the RLS session this was handed, not an argument — see `_Executor`.
    del context
    # NOT `_cap`: that bounds a ROW count at `MAX_ROWS`, and 25 is the wrong ceiling for a
    # window in days. `performance` already clamps its own argument to 1..365 — the schema
    # cannot, since `minimum`/`maximum` are outside the strict subset — so all this has to
    # do is turn "the model sent null, or something that is not a number" into the default.
    raw_days = args.get("days")
    days = (
        int(raw_days)
        if isinstance(raw_days, int | float) and not isinstance(raw_days, bool)
        else 30
    )
    result = await performance(session, days=days)
    funnel = result["funnel"]
    outcomes = sorted(result["outcomes"].items(), key=lambda kv: -kv[1])[:4]
    hours = result["busiest_hours_ist"]
    busiest = sorted(range(24), key=lambda hour: -hours[hour])[:3]
    lines = [
        f"Last {result['days']} days: {funnel['calls']} calls, "
        f"{funnel['connected']} connected ({_pct(result['connect_rate_pct'])} of calls), "
        f"{funnel['qualified']} leads qualified ({_pct(result['qualify_rate_pct'])} of connected).",
        f"Direction: {result['inbound']} inbound, {result['outbound']} outbound. "
        f"Average completed call: "
        f"{'n/a' if result['avg_duration_s'] is None else str(result['avg_duration_s']) + 's'}.",
    ]
    if outcomes:
        lines.append("Commonest outcomes: " + ", ".join(f"{tag} {n}" for tag, n in outcomes) + ".")
    if any(hours):
        lines.append(
            "Busiest hours (IST): "
            + ", ".join(f"{hour:02d}:00 ({hours[hour]} calls)" for hour in busiest if hours[hour])
            + "."
        )
    return _clean(" ".join(lines))


async def _leads_search(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`crm/service.list_leads_page`, rendered — a COUNT LINE and then the rows.

    `list_leads_page` RATHER THAN `list_leads`, and the reason is the whole point of this
    tool now: the page reader hands back `status_counts` across all six statuses for the
    same two queries, so a total and a per-status breakdown cost nothing extra and this
    tool can answer "how many leads do I have?" — which it could not, because a total only
    ever surfaced through `_listing`'s truncation note.

    NO `data` AND NO RAW NUMBER. `LeadOut.data` is the tenant's own extraction payload —
    the one thing hard rule 6 names alongside transcripts — and `phone_e164` is a full
    number; the phone survives only through `_clean`, as `[phone ••NN]`, which is enough
    for a person to recognise the lead on their own screen and not enough to dial from a
    model's answer.
    """
    # Tenancy is the RLS session this was handed, not an argument — see `_Executor`.
    del context
    status = args.get("status")
    asked = status if isinstance(status, str) and status else None
    page = await crm_service.list_leads_page(
        session,
        limit=_cap(args.get("limit")),
        # A status the enum does not admit reaches the reader as a `WHERE status = :s`
        # that matches nothing, which is a truthful empty answer rather than an error.
        status=asked,
    )
    lines = [
        " · ".join(
            part
            for part in (
                f"- {lead.name or 'unnamed'}",
                lead.status,
                f"{lead.call_count} call(s)",
                lead.phone_e164,
                f"updated {lead.updated_at.date().isoformat()}",
                f"owner {lead.assigned_to_name}" if lead.assigned_to_name else None,
            )
            if part
        )
        for lead in page.items
    ]
    label = f"leads{f' with status {asked}' if asked else ''}"
    # THE COUNT LINE IS UNCONDITIONAL, AND THAT IS THE FIX (D-497). It used to be an
    # artefact of `_listing`: a total appeared only when it EXCEEDED the rows shown, so
    # "how many leads do I have?" was answerable from this tool only for an account with
    # more than ten of them — and on an account with none, `_listing` returned "No rows"
    # and the total vanished entirely. A count question must be answered by a count, and
    # `list_leads_page` produces the whole breakdown in the same two queries `list_leads`
    # already paid for (its docstring: the `GROUP BY status` replaced the `count(*)`), so
    # the total and every status are free relative to what this tool already spent.
    breakdown = ", ".join(f"{name} {count}" for name, count in page.status_counts.items())
    header = f"This account has {sum(page.status_counts.values())} lead(s) in total ({breakdown})."
    return _clean(f"{header}\n{_listing(lines, total=page.total, shown_of=label)}")


async def _calls_recent(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`crm/service.list_calls`, rendered.

    THE `status` FILTER IS WHAT ANSWERS "WHAT DID MY AGENT MISS?" (D-497). Without it the
    tool returned the last N calls of any kind, so a question about the ones that did NOT
    connect was answerable only if they happened to be the most recent — on a busy day, the
    misses are the rows the cap drops. `list_calls` already took the filter; nothing was
    passing it. `no_answer`, `busy`, `failed` and `voicemail` are the four a person means by
    "missed", and the tool's description names them so the model does not have to guess
    which member of the enum it wants.

    `summary` IS ALREADY REDACTED PROSE where it is present — `list_calls` puts it through
    `redacted_summary` unconditionally, because there is no raw variant of the list — so
    including it here adds no transcript content that a `calls:read` holder is not already
    entitled to see on their own screen. It is truncated to one clause because the whole
    point of this result is that it is scannable.
    """
    # Tenancy is the RLS session this was handed, not an argument — see `_Executor`.
    del context
    status = args.get("status")
    asked = status if isinstance(status, str) and status else None
    rows = await crm_service.list_calls(session, limit=_cap(args.get("limit")), status=asked)
    lines = [
        " · ".join(
            part
            for part in (
                f"- {call.started_at.date().isoformat() if call.started_at else 'not started'}",
                call.direction,
                call.status,
                f"{call.duration_s}s" if call.duration_s is not None else None,
                f"agent {call.agent_name}" if call.agent_name else None,
                call.outcome_tag,
                (call.summary or "")[:120] or None,
            )
            if part
        )
        for call in rows
    ]
    return _clean(_listing(lines, shown_of=f"calls{f' with status {asked}' if asked else ''}"))


async def _campaigns_list(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`campaigns/service.list_campaigns`, rendered — including the blocker.

    `consent_provenance_blocker` IS THE FIELD WORTH THE TOKENS. It is the launch gate's own
    rule name (that function's docstring argues why it is named rather than boolean), so a
    copilot asked "why can't I launch this?" can answer with the same vocabulary the
    `/launch-check` screen uses instead of inventing a third one.
    """
    # Tenancy is the RLS session this was handed, not an argument — see `_Executor`.
    del context
    rows = await campaigns_service.list_campaigns(session, limit=MAX_ROWS)
    lines = [
        " · ".join(
            part
            for part in (
                f"- {row['name']}",
                row["status"],
                row["classification"],
                f"{row['contacts']} contacts",
                f"{row['connected']} connected",
                f"blocked: {row['consent_provenance_blocker']}"
                if row["consent_provenance_blocker"]
                else None,
            )
            if part
        )
        for row in rows
    ]
    return _clean(_listing(lines, shown_of="campaigns"))


async def _agents_list(session: AsyncSession, context: ToolContext, args: Mapping[str, Any]) -> str:
    """`agents/roster.list_agents`, rendered — the roster, not the configuration.

    NAMES, STATE AND WHETHER IT IS ON THE ENGINE, and nothing else out of a wide row.
    `AgentOut` also carries both disclosure sentences, the composed opening line, the
    extraction schema and the resolved model, and a copilot that pasted all of it would
    spend hundreds of tokens per agent on every subsequent turn of the loop to answer "how
    many agents do I have?". The agent's own screen is where its script and its schema are
    read; what a person asks the assistant is which ones exist, which are live, and whether
    the one they are working on has actually been pushed to the engine.

    `published` IS THE FIELD THIS TOOL EXISTS FOR and it is deliberately not folded into
    `status`: they answer different questions. `status` is what the console shows (`live`,
    `paused`, `draft`, `archived`); `published` is whether the voice platform is holding an
    agent object for it at all. "Live but never published" is the exact confusion a person
    asks the assistant about, and a rendering that showed one of the two could not answer it.

    THE ARCHIVE IS EXCLUDED, because `list_agents`'s own default excludes it (see its
    docstring: the archive is the only unbounded bucket and it would push the working
    roster past the limit). A model asking "what agents are there" means the working ones,
    and this tool takes no `status` argument rather than inventing a second answer to a
    question the roster route already settled.
    """
    # Tenancy is the RLS session this was handed, not an argument — see `_Executor`.
    del context
    # DEFAULT `MAX_ROWS`, NOT TEN. An agent roster is short in every account this product
    # has (`roster.AGENT_ROSTER_LIMIT` is 200 and exists for the wide ROW, not for a long
    # list), and the commonest question about it is a COUNT — "how many agents do I have?"
    # answered from a page silently capped at ten, reported as "there may be more", is the
    # truncation this module's docstring names as how a copilot comes to miscount.
    rows = await roster.list_agents(session, limit=_cap(args.get("limit"), default=MAX_ROWS))
    lines = [
        " · ".join(
            part
            for part in (
                f"- {agent.name}",
                agent.direction,
                agent.status,
                "published" if agent.published else "not published to the phone system yet",
                f"{agent.inbound_number_count} number(s)",
                agent.language_primary,
            )
            if part
        )
        for agent in rows
    ]
    # `shown_of` stays one word: `_listing` composes it into both "N agents:" and
    # "Showing N agents (there may be more):", and a parenthesis inside it lands inside
    # another parenthesis in the second. That the archive is excluded is in the tool's
    # DESCRIPTION, which the model reads before it calls and which costs nothing per row.
    return _clean(_listing(lines, shown_of="agents"))


#: How many passages ONE `search_knowledge` call may put in front of the model, and how
#: much of each. Four passages of at most ~400 characters is a bounded, quotable answer;
#: more is a wall the model paraphrases badly, on a corpus that is at most a few dozen
#: compiled lines to begin with. This is the tool's `cap` for `_listing`, NOT `MAX_ROWS` —
#: the retrieval port counts passages, not rows.
MAX_PASSAGES: Final = 4
MAX_PASSAGE_CHARS: Final = 400

#: What the model is told when the account has nothing on file for the question. Phrased so
#: the model reports it rather than inventing around it — TRD §6's T4 behaviour, which is a
#: prompt instruction with no code behind it, reaching the dashboard leg.
_NOTHING_PUBLISHED = (
    "Nothing in this account's published knowledge matches that. Say so — do not guess "
    "what the agent might say — and suggest adding it under Knowledge if it should be "
    "there."
)

#: Prepended when the port answered from a LOWER tier than the router asked for.
#:
#: THE DEGRADATION IS SPOKEN, NOT SWALLOWED. The router asks for t3 on an open-ended
#: question and no provider serves t3 today, so the port answers from T0 and sets
#: `unmet_capability`. Putting that in front of the model in words is what stops the person
#: being told they were answered from a search of everything they have published when they
#: were answered from the lines compiled into one script. A tool that quietly answered from
#: a narrower corpus is the silent no-op the whole port exists to forbid.
_DEGRADED_NOTE = (
    "NOTE: a full search of everything this account has published is not available, so "
    "this is only what is compiled into the agent's own script. Tell the person that."
)


async def _search_knowledge(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`retrieval/service.look_up`, rendered — what this account's live agents tell callers.

    THE ONE THING THIS TOOL ADDS OVER THE OTHERS: it is the only read tool whose corpus is
    the client's own PUBLISHED KNOWLEDGE rather than their operational rows. The facts are
    on file (`prompt_versions.compiled_t0_context`, compiled from APPROVED sources and the
    intake sheet by `agents/t0.py`) and were addressable from nowhere except the agent's own
    prompt, so the copilot could not answer the question a client asks most often about
    their own account — "what does my agent tell people about X?".

    ONLY APPROVED KNOWLEDGE IS REACHABLE, STRUCTURALLY. This does not read `kb_documents`;
    it reads the compiled block, and only `kb.service.publish_source` puts anything into
    that block, and only for an APPROVED source. The preview-and-approve gate is therefore
    inherited rather than re-implemented — re-deriving "what is approved and live" here
    would be the second copy of it CLAUDE.md calls a defect even when both copies agree.

    `context.tenant_id` IS USED, AND IT IS NOT A SECOND TENANCY CONTROL. RLS still decides
    what the SELECT can see; the id is what the retrieval CACHE keys its namespace on
    (`retrieval/cache.py`), which is not something a session variable can hand it. The
    adapter also re-states it as a `WHERE` predicate — belt over RLS's braces, defending
    the one mistake RLS cannot catch, a caller passing tenant A's id on tenant B's session.
    """
    question = strip_invisible(str(args.get("question") or "")).strip()[:_MAX_QUESTION_CHARS]
    if not question:
        return _NOTHING_PUBLISHED
    # NOT-NONE BY `run_read_tool`'s SCOPE GUARD: this is a `tenant`-scoped tool, so it is
    # never reached without an account open (D-499 made `ToolContext.tenant_id` Optional so
    # the admin realm's platform tools could exist). An assert rather than a second refusal
    # sentence — the refusal belongs where the guard is, and duplicating it here would be a
    # second answer to one question.
    assert context.tenant_id is not None
    # ONE MORE THAN WE WILL SHOW, so a truncation is a fact rather than a guess: `_listing`
    # reports "there may be more" exactly when the page came back full.
    decision, result = await look_up(
        session, tenant_id=context.tenant_id, question=question, k=MAX_PASSAGES + 1
    )
    if result.is_empty():
        return _NOTHING_PUBLISHED
    lines = [
        f"- {passage.text[:MAX_PASSAGE_CHARS]} [{passage.provenance.label}]"
        for passage in result.passages[:MAX_PASSAGES]
    ]
    body = _clean(
        _listing(
            lines,
            shown_of=f"published facts (matched as: {decision.intent})",
            cap=MAX_PASSAGES,
        )
    )
    return f"{_DEGRADED_NOTE}\n{body}" if result.unmet_capability is not None else body


# --- the registry ---------------------------------------------------------------------
#
READ_TOOLS: Final[tuple[ReadTool, ...]] = (
    ReadTool(
        name="business_snapshot",
        description=(
            "Headline numbers for this account over the last N days: how many calls, how "
            "many connected, how many leads qualified, inbound vs outbound, average call "
            "length, the commonest call outcomes and the busiest hours in IST. Call this "
            "before quoting any number about how the business is doing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": "How many days back to look. Null means 30.",
                }
            },
            "required": ["days"],
            "additionalProperties": False,
        },
        permission="calls:read",
        run=_business_snapshot,
    ),
    ReadTool(
        name="leads_search",
        description=(
            "This account's leads, newest first, optionally filtered to one status, AND "
            "the total number of leads with a count for every status. Returns the name, "
            "status, call count, masked phone and owner of each row. Use it to answer HOW "
            "MANY leads there are as well as who has been captured and what state they "
            "are in — it always reports the totals, even when it returns no rows."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "anyOf": [
                        {"type": "string", "enum": list(get_args(LeadStatus))},
                        {"type": "null"},
                    ],
                    "description": "Only leads in this state. Null means every state.",
                },
                "limit": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": f"How many to return, at most {MAX_ROWS}. Null means 10.",
                },
            },
            "required": ["status", "limit"],
            "additionalProperties": False,
        },
        permission="leads:read",
        run=_leads_search,
    ),
    ReadTool(
        name="calls_recent",
        description=(
            "This account's most recent calls, newest first: when, direction, status, "
            "length, which agent took it, its outcome tag and a short redacted summary. "
            "Use it to answer questions about what has been happening on the phone. Filter "
            "by status to find the calls a person means by 'missed' — no_answer, busy, "
            "failed or voicemail — or the ones that connected (completed)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "anyOf": [
                        {"type": "string", "enum": list(CALL_STATUSES)},
                        {"type": "null"},
                    ],
                    "description": "Only calls in this state. Null means every state.",
                },
                "limit": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": f"How many to return, at most {MAX_ROWS}. Null means 10.",
                },
            },
            "required": ["status", "limit"],
            "additionalProperties": False,
        },
        permission="calls:read",
        run=_calls_recent,
    ),
    ReadTool(
        name="campaigns_list",
        description=(
            "This account's outbound campaigns, newest first: name, status, promotional "
            "or service classification, how many contacts, how many connected, and — for "
            "a draft or scheduled campaign — the consent rule that is blocking its launch."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        permission="leads:read",
        run=_campaigns_list,
    ),
    ReadTool(
        name="agents_list",
        description=(
            "This account's voice agents: name, whether it answers inbound calls or makes "
            "outbound ones, whether it is live/paused/draft, whether it has been published "
            "to the phone system yet, how many phone numbers it answers on, and its main "
            "language. Retired (archived) agents are not included. Use it to answer which "
            "agents exist and whether one is actually switched on."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": (
                        f"How many to return, at most {MAX_ROWS}. Null means {MAX_ROWS}."
                    ),
                }
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
        # THE SAME PERMISSION THE SCREEN SERVING THIS DATA DECLARES — `GET /v1/agents` is
        # `agents:read`. A tool that judged itself by a looser one would be a way around
        # that screen.
        permission="agents:read",
        run=_agents_list,
    ),
    ReadTool(
        name="search_knowledge",
        description=(
            "Look up what THIS account's live voice agents tell callers — the business "
            "facts and approved knowledge compiled into their scripts (opening hours, "
            "address, services and prices, staff, policies). Use it whenever the person "
            "asks what their agent says or knows about something. It cannot see the "
            "screen, other accounts, or anything not yet approved and published."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The question in the caller's own words, e.g. 'what are the "
                        "opening hours on Sunday'. Do not include names, phone numbers "
                        "or email addresses."
                    ),
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        # THE SAME PERMISSION THE ROUTES SERVING THIS DATA DECLARE. `kb/routes.py:86-89`
        # settled this argument already and its comment is the one to read: the two KB
        # READS are gated on `agents:read`, not `kb:write`, because "reading what an agent
        # knows is an agent read" and `kb:write` is a submit permission. There is no
        # `kb:read` in `rbac.Permission` at all, and inventing one here so this tool could
        # have its own would be a permission no route grants.
        permission="agents:read",
        run=_search_knowledge,
    ),
)

_BY_NAME: Final[Mapping[str, ReadTool]] = {tool.name: tool for tool in READ_TOOLS}

#: Every read tool's name. `service._run_tool_loop` uses it to tell a read call from the
#: write one without importing the registry's internals.
READ_TOOL_NAMES: Final[frozenset[str]] = frozenset(_BY_NAME)


def read_tool_schemas() -> list[dict[str, Any]]:
    """The read tools as OpenAI tool definitions. BYTE-IDENTICAL ON EVERY REQUEST.

    That property is the reason this takes no arguments — not a screen, not a tenant, not
    a permission set. Azure's prompt caching keys on a leading run of identical tokens
    (`prompt.py`, point 1), and a tool array that dropped the tools a caller may not use
    would differ per ROLE, which is a cache that hits only for callers who happen to share
    one. A `staff` caller is refused INSIDE the tool by `run_read_tool` instead, which is
    also the stronger place for it: a schema the model never sees is not an access control,
    it is an obscurity, and the check has to exist in code either way.

    `strict` is requested exactly as `set_fields_tool` requests it, and nothing depends on
    it for the same reason stated there: every argument is re-read defensively in this
    module (`_cap`, the `isinstance` guards in each executor).
    """
    return [
        # ONE ENVELOPE COMPOSER for every tool this package offers (`prompt.function_tool`):
        # its key ORDER is part of the cacheable prefix, and three copies of it are three
        # chances for that order to drift with nothing to catch it.
        function_tool(name=tool.name, description=tool.description, parameters=tool.parameters)
        for tool in READ_TOOLS
    ]


async def _run_scoped(tool: ReadTool, context: ToolContext, parsed: Mapping[str, Any]) -> str:
    """One tool, under the session ITS scope calls for. See `ReadTool.scope`.

    Written as a dispatch rather than as an `if` inside `run_read_tool` so the session
    decisions sit together and a third scope has one place to be added. The
    `tenant` arm's `context.tenant_id` is not-None by the guard in the caller — asserting
    it here instead would put a second copy of that rule where a refusal sentence belongs.
    """
    if tool.scope == "platform":
        async with admin_session() as session:
            return await tool.run(session, context, parsed)
    assert context.tenant_id is not None  # guarded by the caller
    async with tenant_session(context.tenant_id) as session:
        return await tool.run(session, context, parsed)


async def run_read_tool(
    name: str,
    arguments: str,
    *,
    context: ToolContext | None,
    registry: Mapping[str, ReadTool] | None = None,
) -> str:
    """Run one read tool and return what the model should be told. NEVER RAISES.

    A tool result is a message in a conversation, so every failure here has to be a
    SENTENCE THE MODEL CAN ACT ON: an unknown tool, a permission it does not hold, an
    argument blob that is not JSON, or a database that was not there. A traceback would
    reach the person as either a spinner that stops or a stack trace read aloud by a
    language model, and an exception would kill the stream mid-answer — `routes.py`'s
    generic arm would then report "the assistant stopped part-way" for a question the
    model could have answered by asking something else.

    NO INTERNALS IN ANY OF THOSE SENTENCES, and none of them name a value: the same rule
    `validate_fill`'s reasons follow, because a tool result reaches the model, the model's
    prose reaches the screen, and a log line takes the exception through the ordinary path
    where an operator can see it.
    """
    # THE REGISTRY IS A PARAMETER SINCE D-499, defaulting to the client one. The admin
    # realm has its own tools (`copilot/admin_tools.py`) and the two must not be one flat
    # namespace: a client caller must not be able to name a platform tool even to be
    # refused by it, because "there is no such tool" and "you may not use that tool" are
    # different sentences and only the first is true for them. `service.tool_array` and
    # `service._read_tool_registry` are the one place a realm's set is composed, so the
    # array the model is SHOWN and the registry that RUNS cannot disagree.
    tool = (registry if registry is not None else _BY_NAME).get(name)
    if tool is None:
        return f"There is no tool called `{name}`. Answer without it or use another tool."
    if context is None or context.role is None or not role_has(context.role, tool.permission):
        # THE ACCESS CONTROL, and it is here rather than in the prompt or the schema. A
        # `staff` member reaches this route (it needs `org:manage`, which staff lack) only
        # if that ever changes; the check does not depend on which permission the route
        # happened to declare, which is the point of asking the same question `requires`
        # asks.
        return (
            f"Refused: this user does not have permission to read that "
            f"(`{tool.permission}`). Tell them, and do not guess the answer."
        )
    try:
        parsed = json.loads(arguments or "{}")
    except ValueError:
        return f"The arguments for `{name}` were not valid JSON. Call it again."
    if not isinstance(parsed, dict):
        return f"The arguments for `{name}` were not an object. Call it again."

    if tool.scope == "tenant" and context.tenant_id is None:
        # AN OPERATOR WITH NO ACCOUNT OPEN, which is the ordinary state of the admin
        # console. A sentence the model can act on — "open the account" — rather than a
        # refusal that reads as a permission problem, and never a fallback to some tenant.
        return (
            f"Refused: `{name}` reads one account's own data and no account is open in "
            "this session. Tell the operator to open a client's page first."
        )
    try:
        # ONE SESSION PER CALL, OPENED HERE AND CLOSED BEFORE THIS RETURNS. See the module
        # docstring: the streaming route holds no pooled connection across a provider round
        # trip, and this is what keeps that true while the loop can now touch the database.
        result = await _run_scoped(tool, context, parsed)
    except Exception:
        # Ids only (hard rule 6) — never the arguments, which the model composed from
        # screen content, and never the result.
        log.exception("copilot_tool_failed", extra={"tool": name})
        return f"`{name}` could not be read just now. Tell the user, and do not invent the answer."
    log.info("copilot_tool_ran", extra={"tool": name, "result_chars": len(result)})
    return result


__all__ = [
    "MAX_CALLS_PER_TURN",
    "MAX_PASSAGES",
    "MAX_PASSAGE_CHARS",
    "MAX_ROWS",
    "READ_TOOLS",
    "READ_TOOL_NAMES",
    "ReadTool",
    "ToolContext",
    "read_tool_schemas",
    "run_read_tool",
]
