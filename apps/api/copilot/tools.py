"""The copilot's READ tools: what it may look up about the tenant's own business, and
the four properties that make that safe.

WHY THIS EXISTS AS A REGISTRY RATHER THAN AS FOUR FUNCTIONS THE LOOP KNOWS ABOUT. A tool
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
from typing import Any, Final, get_args
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import service as campaigns_service
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.logging import get_logger
from apps.api.core.rbac import Permission, role_has
from apps.api.crm import service as crm_service
from apps.api.crm.performance import performance
from apps.api.crm.schemas import LeadStatus
from apps.api.db.session import tenant_session
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

    tenant_id: UUID
    role: str | None


#: One tool's executor: a tenant-scoped session and the model's already-parsed arguments
#: in, one compact human-readable string out. It never raises for an ordinary empty
#: result — "nothing found" is an answer — and it never returns a shape the caller has to
#: interpret, because the consumer is a language model and not a client.
_Executor = Callable[[AsyncSession, Mapping[str, Any]], Awaitable[str]]


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
    #: `leads:read`, `GET /v1/campaigns` is `leads:read`. A tool that judged itself by a
    #: looser permission than its own screen would be a way around that screen.
    permission: Permission
    run: _Executor


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


def _listing(rows: list[str], *, total: int | None = None, shown_of: str = "rows") -> str:
    """Rows as lines, with the truncation note when the cap bit.

    `total is None` means the underlying reader does not know how many exist — `list_calls`
    and `list_campaigns` are `LIMIT`ed with no count beside them, where `list_leads` returns
    one. A FULL page from such a reader is therefore reported as "there may be more" rather
    than as a total: "25 calls" would be a number this code has not measured, which is hard
    rule 11 applied to our own data rather than to a vendor's.
    """
    if not rows:
        return _NOTHING
    if total is not None and total > len(rows):
        head = f"Showing {len(rows)} of {total} {shown_of}:"
    elif total is None and len(rows) == MAX_ROWS:
        head = f"Showing {len(rows)} {shown_of} (there may be more):"
    else:
        head = f"{len(rows)} {shown_of}:"
    return "\n".join([head, *rows])


def _pct(value: object) -> str:
    return "n/a" if value is None else f"{value}%"


# --- the executors --------------------------------------------------------------------


async def _business_snapshot(session: AsyncSession, args: Mapping[str, Any]) -> str:
    """`crm/performance.performance` as a paragraph.

    THE WHOLE TAB IS NOT SENT. `performance` returns a 24-bucket IST histogram and an
    outcome map, and pasting both into a prompt spends tokens on the 3am bucket every
    subsequent turn re-reads. The three busiest hours and the four commonest outcomes are
    what a question about "when are we busy" or "how are calls going" is actually answered
    from; the screen is where the whole histogram lives.
    """
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


async def _leads_search(session: AsyncSession, args: Mapping[str, Any]) -> str:
    """`crm/service.list_leads`, rendered.

    NO `data` AND NO RAW NUMBER. `LeadOut.data` is the tenant's own extraction payload —
    the one thing hard rule 6 names alongside transcripts — and `phone_e164` is a full
    number; the phone survives only through `_clean`, as `[phone ••NN]`, which is enough
    for a person to recognise the lead on their own screen and not enough to dial from a
    model's answer.
    """
    status = args.get("status")
    rows, total = await crm_service.list_leads(
        session,
        limit=_cap(args.get("limit")),
        # A status the enum does not admit reaches `list_leads` as a `WHERE status = :s`
        # that matches nothing, which is a truthful empty answer rather than an error.
        status=status if isinstance(status, str) and status else None,
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
        for lead in rows
    ]
    label = f"leads{f' with status {status}' if isinstance(status, str) and status else ''}"
    return _clean(_listing(lines, total=total, shown_of=label))


async def _calls_recent(session: AsyncSession, args: Mapping[str, Any]) -> str:
    """`crm/service.list_calls`, rendered.

    `summary` IS ALREADY REDACTED PROSE where it is present — `list_calls` puts it through
    `redacted_summary` unconditionally, because there is no raw variant of the list — so
    including it here adds no transcript content that a `calls:read` holder is not already
    entitled to see on their own screen. It is truncated to one clause because the whole
    point of this result is that it is scannable.
    """
    rows = await crm_service.list_calls(session, limit=_cap(args.get("limit")))
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
    return _clean(_listing(lines, shown_of="calls"))


async def _campaigns_list(session: AsyncSession, args: Mapping[str, Any]) -> str:
    """`campaigns/service.list_campaigns`, rendered — including the blocker.

    `consent_provenance_blocker` IS THE FIELD WORTH THE TOKENS. It is the launch gate's own
    rule name (that function's docstring argues why it is named rather than boolean), so a
    copilot asked "why can't I launch this?" can answer with the same vocabulary the
    `/launch-check` screen uses instead of inventing a third one.
    """
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


# --- the registry ---------------------------------------------------------------------
#
# ⚠ `agents_list` IS DELIBERATELY ABSENT AND ITS ABSENCE IS A FINDING, NOT AN OVERSIGHT.
# There is no `agents/service.py::list_agents`: the roster query and its row mapper live
# INSIDE `agents/routes.py` (`_AGENT_ROSTER`, `_agent_out`) together with the `AgentOut`
# response model, and the only way to reach them is to call a route handler or to write a
# second copy of the SQL. Both are refused here — the first is a layering inversion this
# repo has no precedent for, and the second is the "two ways of doing one thing" defect the
# quality bar names. What closes it is extracting that roster into `agents/service.py`
# (moving `AgentOut` with it), which is a change to the agents module and its OpenAPI
# surface rather than to this registry.

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
            "This account's leads, newest first, optionally filtered to one status. "
            "Returns the name, status, call count, masked phone and owner of each. Use it "
            "to answer questions about who has been captured and what state they are in."
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
            "Use it to answer questions about what has been happening on the phone."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": f"How many to return, at most {MAX_ROWS}. Null means 10.",
                }
            },
            "required": ["limit"],
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
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "strict": True,
                "parameters": tool.parameters,
            },
        }
        for tool in READ_TOOLS
    ]


async def run_read_tool(name: str, arguments: str, *, context: ToolContext | None) -> str:
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
    tool = _BY_NAME.get(name)
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

    try:
        # ONE SESSION PER CALL, OPENED HERE AND CLOSED BEFORE THIS RETURNS. See the module
        # docstring: the streaming route holds no pooled connection across a provider round
        # trip, and this is what keeps that true while the loop can now touch the database.
        async with tenant_session(context.tenant_id) as session:
            result = await tool.run(session, parsed)
    except Exception:
        # Ids only (hard rule 6) — never the arguments, which the model composed from
        # screen content, and never the result.
        log.exception("copilot_tool_failed", extra={"tool": name})
        return f"`{name}` could not be read just now. Tell the user, and do not invent the answer."
    log.info("copilot_tool_ran", extra={"tool": name, "result_chars": len(result)})
    return result


__all__ = [
    "MAX_CALLS_PER_TURN",
    "MAX_ROWS",
    "READ_TOOLS",
    "READ_TOOL_NAMES",
    "ReadTool",
    "ToolContext",
    "read_tool_schemas",
    "run_read_tool",
]
