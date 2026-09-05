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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, get_args
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import roster
from apps.api.campaigns import service as campaigns_service
from apps.api.copilot.prompt import defuse, function_tool
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.logging import get_logger
from apps.api.core.rbac import Permission, role_has
from apps.api.crm import lead_search
from apps.api.crm import service as crm_service
from apps.api.crm.models import CALL_STATUSES
from apps.api.crm.performance import performance
from apps.api.crm.schemas import LeadOut, LeadStatus
from apps.api.db.session import admin_session, tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval.call_chunks import describe_hits
from apps.api.retrieval.caller_search import MAX_K, search_caller_chunks
from apps.api.retrieval.embedding import ASSIST_FEATURE_CALL_SEARCH
from apps.api.retrieval.models import SUBJECT_CALL_SUMMARY, SUBJECT_CALL_TURN
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
    the PII backstop and it must see the digits as stored; `_defuse` second, because a
    lead's name is text a caller typed and both a tag-block character and a run of hyphens
    in it are prompt-injection carriers (OWASP LLM01 #5) — `prompt.py::_text` does exactly
    this to the screen block for exactly this reason.

    **IT USED TO BE `strip_invisible` ALONE, AND THAT WAS HALF THE JOB.** `_defuse` is
    `strip_invisible` PLUS `_RULE_RUN`, which collapses any run of three or more hyphens —
    the shape of this prompt's own section fences (`--- SCREEN STATE ---`,
    `--- PLATFORM RULES ---`). Without it, `_clean("Ramesh --- END SCREEN STATE ---")`
    returned that string unchanged into a `role: "tool"` message, so a value could close a
    section it was supposed to be inside and open one it had no business opening.

    THE ATTACKER HERE IS NOT THE USER, which is what makes this worth a comment rather
    than a line. The text in a tool result is a lead's name, a campaign's name, a knowledge
    passage, a redacted transcript window — written by the CLIENT'S OWN CALLERS. Somebody
    says a sentence on a phone call, it is transcribed, summarised, stored, and read back
    to the model days later on a screen nobody associates with that call. No amount of
    trust in the person typing in the dashboard defends against it; only defusing the data
    does. The screen block and the memory block were already defused at their seams
    (`prompt._text`, `memory.render_for_prompt` via `xml_text`); the tool-result path was
    the one that was not, and it is the path that carries the least trustworthy text of
    the three.
    """
    return defuse(redact(text).text)


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


#: The longest a model-supplied `status` may be when it is ECHOED BACK into a tool result.
#:
#: The argument comes from a MODEL, and it is put in front of the model again ("no calls
#: with status X") — a loop that a 2000-character `status` turns into 2000 characters of
#: attacker-chosen text in the prompt for the rest of the request. It is passed to the
#: reader too, where an unmatched value is a truthful empty answer; truncating it here keeps
#: the sentence and the query talking about the SAME value. Forty is longer than the longest
#: member of either enum by a wide margin.
_MAX_STATUS_CHARS: Final = 40


def _asked_status(args: Mapping[str, Any]) -> str | None:
    """The model's `status` argument, or `None` for "every state".

    ONE reading of it, shared by the three tools that take one, because they had three
    copies of the same four-clause expression and a bound added to one of them would have
    been a bound missing from the other two. A status the enum does not admit is NOT
    refused: it reaches the reader as a `WHERE status = :s` that matches nothing, which is a
    truthful empty answer rather than an error a person cannot act on.
    """
    status = args.get("status")
    return status[:_MAX_STATUS_CHARS] if isinstance(status, str) and status else None


def _listing(
    rows: list[str],
    *,
    nothing: str,
    total: int | None = None,
    shown_of: str = "rows",
    cap: int = MAX_ROWS,
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
        # `nothing` IS REQUIRED, AND IT USED TO HAVE A DEFAULT ("No rows — this account has
        # none yet"). One shared default meant every empty listing said the same thing, and
        # that sentence is FALSE for most of the ways a listing comes back empty: a status
        # filter that matched nothing on an account with four hundred leads, a roster whose
        # every agent is archived, an admin tool whose population is the whole platform.
        # Making it a parameter with no default is what forces each caller to say WHICH
        # empty it means — the distinction is the answer, and a default is how it got lost.
        # `_nothing()` composes the sentence; nothing here should hand-write one.
        return nothing
    if total is not None and total > len(rows):
        head = f"Showing {len(rows)} of {total} {shown_of}:"
    elif total is None and len(rows) == cap:
        head = f"Showing {len(rows)} {shown_of} (there may be more):"
    else:
        head = f"{len(rows)} {shown_of}:"
    return "\n".join([head, *rows])


#: The next move a person on a brand-new account has, said once. Every "you have none yet"
#: sentence ends in one of these, because a tool result reaches BOTH the model (which
#: composes the answer) and the person (the step list renders it verbatim,
#: `service._preview`), and "you have nothing" with no second half is the recital this
#: whole helper set exists to stop.
_START_CALLS = "Calls appear here once an agent is live and a number is pointed at it."


def _nothing(
    subject: str,
    *,
    matching: str | None = None,
    account_has_any: bool | None = None,
    next_step: str = "",
) -> str:
    """The empty result as a sentence a person can act on — and as the RIGHT empty.

    THREE DIFFERENT FACTS ARRIVE HERE AS THE SAME EMPTY LIST, and telling a client the
    wrong one of them is worse than saying nothing. "You have no leads" told to an account
    with four hundred leads and an unmatched status filter is a false statement about their
    business, made in the assistant's own confident voice; the model cannot tell the cases
    apart from `[]`, so this composes the distinction into the only thing the model reads.

    * `matching is None` — the reader was asked for everything and got nothing back, so
      the account genuinely has none of this yet.
    * `matching` given, `account_has_any is False` — a filter was applied AND we checked:
      the account has none of these at all, so the filter is not the reason.
    * `matching` given, `account_has_any is True` — the account HAS these; this filter is
      what matched nothing. The sentence says so in words the model is told not to
      contradict, because "no leads are hot" and "you have no leads" are different answers.
    * `matching` given, `account_has_any is None` — a filter was applied and nobody checked
      whether the account has any at all. The sentence declares that gap rather than
      guessing past it (hard rule 11's shape, applied to our own data).

    EVERY SENTENCE HERE HAS TWO READERS, which is why none of them instructs the model in
    the second person. A tool result is not private to the loop: `service._preview` puts the
    first 200 characters of it, verbatim, into the step list on the person's own screen. So
    "do not tell them they have none" — the natural way to write a steer — reaches the
    client as the assistant visibly coaching itself about them. Every arm below states the
    FACT and its BOUNDARY instead, which steers the model exactly as well ("this filter is
    what matched nothing, not the account" is not a sentence a model contradicts) and reads
    as an ordinary finding to the person. Where a steer genuinely has to be imperative, it
    goes LAST, past the preview's cut.

    `next_step` is what the person does about it, and it is only offered on the arms where
    "nothing yet" is the truth — suggesting how to get started to somebody whose filter
    merely missed is noise, and worse, reads as confirmation that they have nothing.
    """
    tail = f" {next_step}" if next_step else ""
    if matching is None:
        return f"This account has no {subject} yet.{tail}"
    if account_has_any is False:
        return f"This account has no {subject} at all yet, so none {matching} either.{tail}"
    if account_has_any is True:
        return (
            f"No {subject} {matching}. The account does have other {subject} — this filter "
            f"is what matched nothing, not the account."
        )
    return (
        f"No {subject} {matching}. That is only about this filter; it does not say whether "
        f"the account has any {subject} at all."
    )


# --- the executors --------------------------------------------------------------------


async def _has_any_call(session: AsyncSession) -> bool:
    """Has this account EVER taken a call? One row, asked only when we already know the
    answer to a narrower question was nothing.

    THE SECOND QUERY IS THE POINT AND IT IS CHEAP. Every "nothing found" a filtered or
    windowed reader returns is ambiguous — a new account and a busy account whose filter
    missed produce the same empty list — and the two lead a client to opposite conclusions.
    `list_calls(limit=1)` is the same reader the unfiltered tool uses with a `LIMIT 1`, so
    it costs one indexed row on a path that has, by construction, just returned none.
    """
    return bool(await crm_service.list_calls(session, limit=1))


async def _no_calls_in_window(session: AsyncSession, *, days: int) -> str:
    """The snapshot's empty state — the defect this helper set exists for.

    A BRAND-NEW ACCOUNT IS THE FIRST EXPERIENCE OF THIS PRODUCT, and what the model used to
    be handed was "0 calls, 0 connected (n/a of calls), 0 leads qualified (n/a of
    connected) … Average completed call: n/a" — six zeros and four `n/a`s, from which the
    best answer obtainable is a recital of arithmetic about nothing. Every client's first
    week reads like a fault in the product.

    The two cases are told apart because they are opposite advice: an account with NO calls
    ever is being told how to get started, and an account whose last call predates the
    window is being told to look further back — and must never be told it has no calls.
    """
    recent = await crm_service.list_calls(session, limit=1)
    if not recent:
        return (
            "This account has not taken a single call yet, so there is nothing to measure "
            "— no connect rate, no qualification rate and no average call length exist "
            f"rather than being zero. {_START_CALLS} Say that plainly and help them get "
            "there; do not report zeros as if they were performance."
        )
    # `list_calls` orders `started_at DESC NULLS LAST`, so this row is genuinely the most
    # recent one that has a start time — and a date is not a personal value (hard rule 6).
    last = recent[0].started_at
    when = f"on {last.date().isoformat()}" if last is not None else "before this window"
    return (
        f"No calls at all in the last {days} days, so nothing in that window can be "
        f"measured — the rates and the average call length do not exist rather than being "
        f"zero. This account is NOT new: its most recent call was {when}. Do not tell them "
        "they have no calls; offer to look at a longer window."
    )


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
    if funnel["calls"] == 0:
        return _clean(await _no_calls_in_window(session, days=int(result["days"])))
    outcomes = sorted(result["outcomes"].items(), key=lambda kv: -kv[1])[:4]
    hours = result["busiest_hours_ist"]
    busiest = sorted(range(24), key=lambda hour: -hours[hour])[:3]
    # PAST THIS POINT THERE IS AT LEAST ONE CALL, so `connect_rate_pct` is a measured
    # number and never `None` — the only rates that can still be undefined are the ones
    # whose OWN denominator is zero, and each of those says so in words below.
    lines = [
        f"Last {result['days']} days: {funnel['calls']} calls, "
        f"{funnel['connected']} connected ({result['connect_rate_pct']}% of calls)."
    ]
    if funnel["connected"] == 0:
        # A REAL AND COMMON STATE, not a gap: an account dialling into no answers. Saying
        # "0 qualified (n/a of connected)" invites the model to recite a ratio over nothing;
        # this says which of the two numbers is missing and why the third cannot exist.
        lines.append(
            "No call connected in this window, so nothing could be qualified from one and "
            "there is no qualification rate to work out."
        )
    elif funnel["qualified"] == 0:
        lines.append(
            f"{funnel['connected']} call(s) connected but no lead has moved past 'new' "
            "yet — the pipeline is filling and nothing has progressed."
        )
    else:
        lines.append(
            f"{funnel['qualified']} leads qualified "
            f"({result['qualify_rate_pct']}% of connected calls)."
        )
    lines.append(f"Direction: {result['inbound']} inbound, {result['outbound']} outbound.")
    lines.append(
        # UNDEFINED IS NOT ZERO, AND `n/a` IS NEITHER. `avg_duration_s` averages COMPLETED
        # calls only, so it is `None` on a window of dials that never completed — a fact
        # about the calls, which is worth a sentence, rather than a hole in the tool.
        "No call completed in this window, so there is no average call length yet."
        if result["avg_duration_s"] is None
        else f"Average completed call: {result['avg_duration_s']}s."
    )
    if outcomes:
        lines.append("Commonest outcomes: " + ", ".join(f"{tag} {n}" for tag, n in outcomes) + ".")
    if any(hours):
        lines.append(
            "Busiest hours (IST): "
            + ", ".join(f"{hour:02d}:00 ({hours[hour]} calls)" for hour in busiest if hours[hour])
            + "."
        )
    return _clean(" ".join(lines))


def _lead_line(lead: LeadOut) -> str:
    """ONE rendering of a lead row, shared by every tool that lists leads.

    Two tools now answer with leads (`leads_search` and `leads_semantic_search`) and a
    third will; one renderer is what keeps them describing the same row the same way, and
    — the part that matters — what keeps the field list ONE decision. `data` is absent from
    it deliberately: `LeadOut.data` is the tenant's extraction payload, the one thing hard
    rule 6 names beside transcripts, and `phone_e164` survives only through `_clean`, as
    `[phone ••NN]` — enough for a person to recognise the lead on their own screen and not
    enough to dial from a model's answer.
    """
    return " · ".join(
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
    asked = _asked_status(args)
    page = await crm_service.list_leads_page(session, limit=_cap(args.get("limit")), status=asked)
    lines = [_lead_line(lead) for lead in page.items]
    label = f"leads{f' with status {asked}' if asked else ''}"
    # THE COUNT LINE IS UNCONDITIONAL, AND THAT IS THE FIX (D-497). It used to be an
    # artefact of `_listing`: a total appeared only when it EXCEEDED the rows shown, so
    # "how many leads do I have?" was answerable from this tool only for an account with
    # more than ten of them — and on an account with none, `_listing` returned "No rows"
    # and the total vanished entirely. A count question must be answered by a count, and
    # `list_leads_page` produces the whole breakdown in the same two queries `list_leads`
    # already paid for (its docstring: the `GROUP BY status` replaced the `count(*)`), so
    # the total and every status are free relative to what this tool already spent.
    held = sum(page.status_counts.values())
    if held == 0:
        # NO COUNT LINE AND NO LISTING — one sentence. "This account has 0 lead(s) in total
        # (new 0, contacted 0, …)" is six zeros in a row, which is the shape D-497's fix
        # accidentally created on the account that has nothing: true, unreadable, and the
        # raw material for exactly the recital `_nothing` exists to prevent. The count is
        # still ANSWERED — "no leads yet" is the answer to "how many do I have" — it is
        # just said in words. The status filter cannot change this: an account with no
        # leads has none in every state.
        return _clean(
            _nothing(
                "leads",
                next_step=(
                    "A lead is created automatically when a caller reaches an agent, and "
                    "one can be added by hand on the Leads screen."
                ),
            )
        )
    breakdown = ", ".join(f"{name} {count}" for name, count in page.status_counts.items())
    header = f"This account has {held} lead(s) in total ({breakdown})."
    return _clean(
        f"{header}\n"
        + _listing(
            lines,
            total=page.total,
            shown_of=label,
            # WE KNOW THE ANSWER TO THE AMBIGUITY HERE FOR FREE: `status_counts` is never
            # narrowed by the status asked for, so a page of nothing on an account holding
            # leads is provably the FILTER matching nothing and is said as such.
            nothing=_nothing(
                "leads",
                matching=f"with status {asked}" if asked else "on this page",
                account_has_any=True,
            ),
        )
    )


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
    asked = _asked_status(args)
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
    if not rows:
        # THE SECOND QUERY RUNS ONLY HERE, on the path that already returned nothing. With
        # a status filter the empty list is ambiguous — "no missed calls" and "no calls at
        # all" are opposite pieces of news — and without one it is not, so the unfiltered
        # case answers from what it already knows rather than paying for a round trip to
        # re-learn it.
        return _clean(
            _nothing(
                "calls",
                matching=f"with status {asked}" if asked else None,
                account_has_any=await _has_any_call(session) if asked else None,
                next_step=_START_CALLS,
            )
        )
    return _clean(
        _listing(
            lines,
            shown_of=f"calls{f' with status {asked}' if asked else ''}",
            # Unreachable — `rows` is non-empty above — but `_listing` takes no default
            # sentence on purpose, and a caller that could not say which empty it means
            # would be the caller that gets it wrong.
            nothing=_nothing("calls", next_step=_START_CALLS),
        )
    )


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
                # A CAMPAIGN WITH NO CONTACTS IS A STATE OF THE BUSINESS, not a zero to
                # recite. "0 contacts · 0 connected" reads as two failed measurements
                # where the truth is that the list has not been uploaded yet, which is the
                # single thing the person has to do next — and the connected count is
                # meaningless until it is, so it is not printed at all.
                "no contacts loaded yet" if row["contacts"] == 0 else f"{row['contacts']} contacts",
                None
                if row["contacts"] == 0
                else (
                    "none connected yet"
                    if row["connected"] == 0
                    else f"{row['connected']} connected"
                ),
                # `launched_at` IS THE ONLY WAY TO TELL "NEVER DIALLED" FROM "DIALLED AND
                # FINISHED": a completed campaign and a draft both sit at zero connected,
                # and only one of them is a campaign that never went out.
                "never launched" if row["launched_at"] is None else None,
                f"blocked: {row['consent_provenance_blocker']}"
                if row["consent_provenance_blocker"]
                else None,
            )
            if part
        )
        for row in rows
    ]
    return _clean(
        _listing(
            lines,
            shown_of="campaigns",
            # NO FILTER EXISTS ON THIS TOOL, so an empty list has exactly one meaning and
            # there is no ambiguity to declare.
            nothing=_nothing(
                "outbound campaigns",
                next_step=(
                    "Outbound dialling starts with a campaign built on the Campaigns "
                    "screen; inbound calls do not need one."
                ),
            ),
        )
    )


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
    if not rows:
        # THE ARCHIVE IS THE AMBIGUITY HERE (`roster.list_agents` excludes it by default),
        # and the two cases are opposite advice: an account with no agents at all is being
        # told to create one, and an account that retired all of theirs is being told where
        # their agents went. Told the wrong one, a client who archived a line last week
        # hears that their agents have disappeared.
        if await roster.list_agents(session, status="archived", limit=1):
            return _clean(
                "Every voice agent in this account has been retired (archived), so there "
                "is no working roster and no agent can take a call. Retired agents are "
                "kept but are not listed here."
            )
        return _clean(
            _nothing(
                "working voice agents",
                next_step="One is built on the Agents screen.",
            )
        )
    # `shown_of` stays one word: `_listing` composes it into both "N agents:" and
    # "Showing N agents (there may be more):", and a parenthesis inside it lands inside
    # another parenthesis in the second. That the archive is excluded is in the tool's
    # DESCRIPTION, which the model reads before it calls and which costs nothing per row.
    body = _listing(
        lines,
        shown_of="agents",
        # Unreachable — the empty case is answered above, where the archive can be checked
        # — and stated anyway because `_listing` has no default sentence by design.
        nothing=_nothing("working voice agents"),
    )
    # A ROSTER THAT EXISTS AND CANNOT TAKE A CALL IS THE COMMONEST PARTIAL STATE ON A NEW
    # ACCOUNT, and it is invisible in a per-row rendering: every line says "not published"
    # and nothing says what that adds up to. This is the sentence that answers "why is
    # nothing happening?" without the model having to infer it from N rows.
    if not any(agent.published for agent in rows):
        body += (
            "\nNone of these agents has been published to the phone system yet, so no "
            "call can reach any of them."
        )
    elif not any(agent.status == "live" for agent in rows):
        body += (
            "\nNo agent is live: every one is paused or still a draft, so none of them is "
            "answering right now."
        )
    return _clean(body)


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

#: What the model is told when no lead's captured answers match. `_nothing()`'s rule applied
#: to a SEARCH rather than to a listing, and the difference is the sentence: "this account
#: has none yet" would be a false statement about the account when the truth is only that
#: nothing matched this question. It also names the boundary the tool actually has, because
#: a model that does not know a phone number is unsearchable here will otherwise conclude
#: the lead does not exist.
_NO_LEADS_MATCHED = (
    "No lead's captured answers match that. Say so rather than guessing, and note that "
    "this search covers what callers asked for — not names, phone numbers or dates, which "
    "are found with leads_search and the filters on the Leads screen."
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


#: How many opaque sources the empty-answer sentence will name before it stops. A refusal is
#: prose a model reads back to a person, and a list of forty file names is not a sentence.
_MAX_NAMED_SOURCES: Final = 5


def _sources_this_tool_cannot_read(sources: Sequence[Mapping[str, Any]]) -> list[str]:
    """The names of LIVE sources whose content neither retrieval tier can see.

    A published source with ZERO `kb_documents` rows is a PDF or a scraped link (D-534):
    `workers/kb_ingest.ingest_kb_source` extracts text for every other kind and deliberately
    not for those two — a PDF *is* the object the engine is handed, so the artefact a
    reviewer approved and the one an agent answers from are the same bytes, and a link is
    scraped by the engine itself. Neither leaves us any text, and BOTH retrieval tiers are
    built from `kb_documents` (T0 through `kb.service.active_knowledge`'s join, T3 through
    `kb/service._PROJECT_SQL`'s), so neither can match a word of them.

    THE FIX IS THE SENTENCE, NOT A WIDER TOOL. Making this reachable would mean extracting a
    PDF into chunks, which changes what `agents/t0.py` compiles into the agent's PROMPT and
    what a reviewer is shown — a voice-path decision with its own token budget (PROMPT-GUIDE
    §2), not something a dashboard read tool may take on its own. What this tool owes the
    client meanwhile is the truth: `_NOTHING_PUBLISHED` tells them to add a price list they
    uploaded this morning, which sends them to do work that is already done and teaches them
    the assistant is wrong about their own account.

    `chunks` comes from `list_sources`, which is the Knowledge screen's own reader — so what
    the assistant calls unreadable is derived from the same row the client is looking at.
    """
    return [
        str(source["name"])[:80]
        for source in sources
        if source["published_at"] is not None and source["is_active"] and not source["chunks"]
    ][:_MAX_NAMED_SOURCES]


async def _nothing_published(session: AsyncSession) -> str:
    """Which of the THREE empty knowledge bases this is.

    `_NOTHING_PUBLISHED` alone answers only the third. An account that has added nothing,
    an account whose sources are sitting unapproved in the review queue, and an account
    with a live knowledge base that simply has no fact about this question all produce an
    empty retrieval result — and the remedies are "add something", "get it approved" and
    "nothing to do, the agent genuinely does not know that". Telling the second client the
    third answer sends them looking for a fact they already wrote, which is waiting on us.

    Only reached when retrieval already came back empty, so the extra read costs nothing on
    the answering path. `kb_service.list_sources` is the same reader the Knowledge screen
    uses, so the assistant and that screen cannot disagree about what is on file.
    """
    sources = await kb_service.list_sources(session, limit=MAX_ROWS)
    if not sources:
        return (
            "This account has not added anything to its knowledge base yet, so its agents "
            "know only what was captured in the intake sheet. Nothing is missing or "
            "broken — there is simply nothing published to search. Knowledge is added on "
            "the Knowledge screen."
        )
    if not any(source["published_at"] is not None for source in sources):
        waiting = sum(1 for source in sources if source["status"] == "pending_approval")
        return (
            f"This account has {len(sources)} knowledge source(s) on file but NONE of them "
            "is published, so the agents cannot use any of it yet"
            + (f" — {waiting} is waiting for approval" if waiting else "")
            + ". That is a step outstanding on our side, not a gap in what they wrote."
        )
    opaque = _sources_this_tool_cannot_read(sources)
    if opaque:
        # THE FOURTH EMPTY KNOWLEDGE BASE, and the only one where the honest answer is
        # about US. See `_sources_this_tool_cannot_read`.
        return (
            "Nothing in the text this account has published matches that — but "
            f"{len(opaque)} live source(s) hold their content as a file or a web page we "
            "do not keep the text of, so this search could not look inside them: "
            f"{', '.join(opaque)}. The agent CAN still answer from them on a call. Say "
            "exactly that, name them, and do NOT suggest adding them again — they are "
            "already live. To make one searchable here as well, its content can be pasted "
            "or re-uploaded as a text, Word, spreadsheet or image file on the Knowledge "
            "screen."
        )
    return _NOTHING_PUBLISHED


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
        return await _nothing_published(session)
    lines = [
        f"- {passage.text[:MAX_PASSAGE_CHARS]} [{passage.provenance.label}]"
        for passage in result.passages[:MAX_PASSAGES]
    ]
    body = _clean(
        _listing(
            lines,
            shown_of=f"published facts (matched as: {decision.intent})",
            cap=MAX_PASSAGES,
            # Unreachable: an empty result is answered above, where the knowledge base
            # itself can be inspected. Stated because `_listing` takes no default.
            nothing=_NOTHING_PUBLISHED,
        )
    )
    return f"{_DEGRADED_NOTE}\n{body}" if result.unmet_capability is not None else body


async def _leads_semantic_search(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`crm/lead_search.search_leads`, rendered — leads whose captured answers match a
    question asked in words.

    THE ONE THING THIS ADDS OVER `leads_search`: that tool lists and counts, and its only
    text filter is a name or a phone suffix (`crm/service._lead_scope`). "Who asked about a
    3BHK in Gachibowli" is not a name and not a status, and before this the copilot could
    not answer it at all — the answer lives inside `leads.data`, which no tool may print
    (hard rule 6) and which nothing could search.

    IT SEARCHES THE PROJECTION, NOT THE PAYLOAD, so what is reachable here is exactly what
    `crm/lead_projection.py` chose to embed: labelled text and enum answers. A phone number
    captured in a field is NOT searchable and that is the design — an identifier is what
    `leads_search` already matches exactly.

    `context.tenant_id` IS USED and is not a second tenancy control: RLS still decides what
    the statement can see; the id is what the store's own predicate re-states (belt over
    braces) and what the question's embedding is METERED against — a spend needs an account
    to land on, and a session variable cannot hand it one.
    """
    question = strip_invisible(str(args.get("question") or "")).strip()[:_MAX_QUESTION_CHARS]
    if not question:
        return _NO_LEADS_MATCHED
    # NOT-NONE BY `run_read_tool`'s SCOPE GUARD — a `tenant`-scoped tool is never reached
    # without an account open. An assert rather than a second refusal sentence: the refusal
    # belongs where the guard is.
    assert context.tenant_id is not None
    asked_status = _asked_status(args)
    found = await lead_search.search_leads(
        session,
        tenant_id=context.tenant_id,
        question=question,
        limit=_cap(args.get("limit")),
        status=asked_status,
    )
    if not found.leads:
        # THE ACCOUNT-LEVEL FACT FIRST, because it changes the sentence completely: an
        # account with no leads is not being told that its search covers captured answers
        # rather than names — it is being told it has no leads. Only paid for on the path
        # that already found nothing.
        page = await crm_service.list_leads_page(session, limit=1)
        if sum(page.status_counts.values()) == 0:
            return _clean(
                _nothing(
                    "leads",
                    next_step=(
                        "There is nothing to search yet — a lead is created when a caller "
                        "reaches an agent."
                    ),
                )
            )
        if asked_status is not None:
            # A STATUS FILTER IS A SECOND WAY TO MATCH NOTHING, and the model cannot see
            # from the empty result which of the two bit. Named rather than folded into
            # `_NO_LEADS_MATCHED`, whose whole job is to explain that the SEARCH covers
            # captured answers — a filter that excluded every match is a different fact
            # and has a different next move.
            return _clean(
                f"{_NO_LEADS_MATCHED} This search was also narrowed to leads with status "
                f"{asked_status}, which may be what excluded them — the same question "
                "across every status may find some."
            )
        return _NO_LEADS_MATCHED
    lines = [_lead_line(lead) for lead in found.leads]
    # `total` is the number the STORE ranked, so "showing 5 of 12" is true of the search
    # rather than of the account — and `exhausted` is the only case where even that is a
    # floor, which `_listing` cannot know and this sentence says out loud.
    body = _listing(
        lines,
        total=found.ranked,
        shown_of="matching leads",
        cap=MAX_ROWS,
        # Unreachable: the empty search is answered above, where the account's own lead
        # total tells "none yet" from "none matching".
        nothing=_NO_LEADS_MATCHED,
    )
    tail = (
        "\nThere may be more matches than were ranked — ask a narrower question."
        if found.exhausted
        else ""
    )
    return _clean(body + tail)


#: What `search_calls` says when a question matched nothing in the account's calls.
#:
#: A SENTENCE THAT DISTINGUISHES THE TWO EMPTY ANSWERS, because they lead to different next
#: moves and a model told only "no rows" will guess which. "Nobody said anything like that"
#: is a finding a client acts on; "these calls are past their retention period" is a fact
#: about our own policy that the model must not report as a finding about their callers.
_NOTHING_IN_CALLS = (
    "No passage in this account's stored calls matches that. Either no caller said "
    "anything like it, or those conversations are past the account's transcript retention "
    "period and the words are gone. Say which you cannot tell apart, and do not guess."
)


async def _search_calls(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`retrieval/caller_search`, over what CALLERS SAID — the demand signal, not the script.

    THE QUESTION THIS ANSWERS AND NO OTHER TOOL DOES: "which callers asked about weekend
    appointments?". `search_knowledge` searches what the client PUBLISHED and `calls_recent`
    lists calls by time; neither can find a moment inside a conversation. The corpus here is
    windows of `transcript_turns.text_redacted` and `calls.summary`, projected into
    `caller_chunks` — with the SPEAKER labelled, which is what makes "a caller ASKED" a
    different result from "the agent MENTIONED".

    **IT NEVER TOUCHES `transcript_turns.text`.** The hit carries no words at all
    (`caller_search.CallerHit`); `call_chunks.describe_hits` reads them back from the
    redacted column, which is the same column the transcript screen and every other derived
    surface read (hard rule 5). `_clean` then runs the PII backstop over the result, so a
    number a redactor missed is masked before it reaches the model.

    Both kinds are named explicitly. `search_caller_chunks` requires that and has no
    default, so a leads search cannot silently return transcript windows and this cannot
    silently return CRM fields.
    """
    question = strip_invisible(str(args.get("question") or "")).strip()[:_MAX_QUESTION_CHARS]
    if not question:
        return _NOTHING_IN_CALLS
    # Not-None by `run_read_tool`'s scope guard: this is a `tenant`-scoped tool.
    assert context.tenant_id is not None
    limit = _cap(args.get("limit"), default=8)
    hits = await search_caller_chunks(
        session,
        tenant_id=context.tenant_id,
        question=question,
        kinds=(SUBJECT_CALL_TURN, SUBJECT_CALL_SUMMARY),
        feature=ASSIST_FEATURE_CALL_SEARCH,
        # ONE MORE THAN WE WILL SHOW, so "there may be more" is a fact rather than a guess —
        # and clamped to the adapter's own ceiling rather than assumed to fit, because a `k`
        # this tool would have to have clamped is one the adapter refuses outright.
        k=min(limit + 1, MAX_K),
    )
    lines = await describe_hits(session, hits, max_chars=MAX_PASSAGE_CHARS)
    if not lines:
        # `_NOTHING_IN_CALLS` NAMES TWO CAUSES AND THERE IS A THIRD, which on a new account
        # is the only true one: there are no calls to search. Telling that client that
        # "either no caller said anything like it, or those conversations are past the
        # retention period" describes a corpus they have never had, and the retention half
        # reads as data loss.
        if not await _has_any_call(session):
            return _clean(
                _nothing(
                    "calls",
                    next_step=("There is nothing to search until a call happens. " + _START_CALLS),
                )
            )
        return _NOTHING_IN_CALLS
    return _clean(
        _listing(
            lines[:limit],
            shown_of="passages from past calls",
            cap=limit,
            # Unreachable: the empty search is answered above, where "no calls at all" is
            # told from "nothing matched".
            nothing=_NOTHING_IN_CALLS,
        )
    )


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
        name="leads_semantic_search",
        description=(
            "Find leads by WHAT THEY ASKED FOR, in the caller's own words — 'leads who "
            "asked about a 3BHK in Gachibowli', 'anyone who wanted a weekend site visit'. "
            "It searches the answers this account's agents captured on each lead, not the "
            "lead's name or number: use `leads_search` for a name, a phone, a status or a "
            "count, and this when the question is about the CONTENT of what a caller "
            "wanted. Returns the same row summary, best match first."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "What the caller wanted, in ordinary words, e.g. '3BHK in "
                        "Gachibowli'. Do not include names, phone numbers or email "
                        "addresses — they are not searchable here."
                    ),
                },
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
            "required": ["question", "status", "limit"],
            "additionalProperties": False,
        },
        # THE SAME PERMISSION THE SCREEN SERVING THIS DATA DECLARES — `GET /v1/leads` is
        # `leads:read`, and this returns the same rows in a different order.
        permission="leads:read",
        run=_leads_semantic_search,
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
    # APPENDED AT THE END, and that is deliberate rather than incidental: `service.
    # tool_array` composes the cacheable prefix in `realm_read_tools` order, so a new tool
    # inserted in the middle would move every schema after it and cold-start the prompt
    # cache for every request of both realms. Last costs nothing.
    ReadTool(
        name="search_calls",
        description=(
            "Search what CALLERS ACTUALLY SAID on past calls, by meaning rather than by "
            "keyword — 'who asked about weekend appointments', 'callers who mentioned a "
            "refund', 'anyone unhappy about waiting'. Returns the matching passage with "
            "the speaker marked, the date and the caller's lead name where there is one. "
            "Use it for questions about DEMAND and about what people ask for; use "
            "`search_knowledge` for what the agent has been taught to say, and "
            "`calls_recent` to list calls by time rather than by topic. Transcripts are "
            "redacted, so names and numbers are not searchable here and must not be put "
            "in the question."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "What you are looking for, in ordinary words, e.g. 'weekend "
                        "appointment' or 'complained about the price'. Do not include "
                        "names, phone numbers or email addresses — they are redacted out "
                        "of transcripts and are not searchable here."
                    ),
                },
                "limit": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": (
                        f"How many passages to return, at most {MAX_ROWS}. Null means 8."
                    ),
                },
            },
            "required": ["question", "limit"],
            "additionalProperties": False,
        },
        # THE SAME PERMISSION THE SCREEN SERVING THIS DATA DECLARES — a transcript is read
        # through `GET /v1/crm/calls/{id}`, which is `calls:read`. A semantic index over
        # the same words must not be reachable on a looser permission than the words are.
        permission="calls:read",
        run=_search_calls,
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
