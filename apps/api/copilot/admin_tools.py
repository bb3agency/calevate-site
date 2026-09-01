"""The ADMIN copilot's read tools: platform state, the tenant in view, and the runbooks.

The client copilot's tools answer "how is MY business doing" out of one tenant's rows under
that tenant's RLS. An operator's questions are a different shape — *which client is about
to break*, *are we dialling at all*, *how much of this month's AI budget is gone*, *what do
I do when `engine_error_spike` fires* — and none of them has a tenant. So this is a second
registry rather than a widening of the first, for the reason `tools.py` gives for being a
registry at all: a tool is a schema, a permission and an executor that must not drift, and
the drift here would be a platform query running under a tenant GUC or the reverse.

## THREE THINGS THIS REGISTRY DOES DIFFERENTLY, AND NOTHING ELSE

1. **`scope="platform"` opens an `admin_session()`, not a `tenant_session`.** That session
   is the ONLY one that can enumerate tenants (migration `b57e2f9c4a13` widens `USING` on
   `organizations` and on nothing else), and every function called below either takes it as
   its documented directory session (`admin_service.tenant_overview`,
   `admin.health.client_health` — both of which then ENTER each tenant with its own GUC) or
   reads a `platform_*` table that carries no policy at all. Hard rule 1 is not bent: no
   tenant table is read cross-tenant at any instant.
2. **The permission is `admin:tenants`, which is the one the equivalent SCREEN declares.**
   `GET /v1/admin/tenants` and the health board both declare it, and no client role holds
   it — so a tool that judged itself by anything looser would be a way around the console.
   `tools.py` makes this argument for `calls:read` and `agents:read`; this is the same rule
   applied to the console's own reads.
3. **`search_runbooks` reads the process's own runbook index** (`copilot/runbooks.py`) —
   our text, our ranker, no vendor and no embeddings, so D-28 stays the founder's open
   decision. It is declared `scope="platform"` and simply does not use the session it is
   handed; `ReadTool.scope` records why there is no third scope for it.

## WHAT AN OPERATOR CAN STILL REACH THROUGH THE *CLIENT* TOOLS

The admin tool array also carries `tools.READ_TOOLS` (see `service.tool_array`), scoped by
the route to the ONE tenant whose page is open. That is where "the tenant currently being
viewed — their calls, leads, campaigns, agents" is answered, under that tenant's own RLS,
by the same code the client copilot runs. Nothing is duplicated here for it; when no tenant
is in view those tools refuse with a sentence saying so, which is the honest answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.admin.health import client_health
from apps.api.billing.ai_quota import PLATFORM_AI_BRAKE_INR, read_platform_ai_spend
from apps.api.copilot import runbooks as runbook_index
from apps.api.copilot.tools import MAX_ROWS, ReadTool, ToolContext, _cap, _clean, _listing
from apps.api.ops.service import read_halt_state, read_tm_registration

#: What a platform tool says when the question has an answer and the answer is "nothing".
#: A sentence rather than an empty string, for `tools._NOTHING`'s reason: an empty tool
#: result reads to a model as a failure.
_NO_ACCOUNTS: Final = "No accounts on the platform yet."


def _when(value: datetime | None) -> str:
    """An instant as whole days ago, or `never`.

    DAYS AND NOT A TIMESTAMP, deliberately: an operator asking "when did this client last
    make a call" is asking whether it was recently, and a model handed an ISO string in UTC
    will render it in UTC to somebody working in IST. Days ago is unambiguous in every
    timezone and costs a third of the tokens.
    """
    if value is None:
        return "never"
    days = (datetime.now(UTC) - value).days
    if days <= 0:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"


async def _platform_tenants(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The client directory, newest first — `GET /v1/admin/tenants`' own data.

    `tenant_overview` is called rather than re-queried, so the assistant and the console's
    roster cannot answer "which clients exist" differently. It is N+1 by construction and
    says so at length; the cap below is what keeps the assistant from paying for the whole
    walk on a question about the top of the list.
    """
    del context
    rows = await admin_service.tenant_overview(session)
    limit = _cap(args.get("limit"), default=MAX_ROWS)
    lines = [
        _clean(
            f"{row['name']} ({row['slug']}) — {row['status']}, {row['vertical_template']}; "
            f"{row['live_agents']} live agent(s), {row['calls_7d']} calls in 7d, "
            f"{row['leads']} lead(s); last call {_when(row['last_call_at'])}"
            + (", SPEND-CAPPED" if row["capped"] else "")
            + (f"; held by: {', '.join(row['holds'])}" if row["holds"] else "")
        )
        for row in rows[:limit]
    ]
    return _listing(lines, total=len(rows), shown_of="accounts", nothing=_NO_ACCOUNTS)


async def _platform_health(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The triage board: accounts with at least one live signal, worst first.

    `client_health` is the console's own board and already ranks and explains itself
    (`_triage_order`: most things broken, then most things about to break, then name). The
    causes come back as the GATES' OWN RULE NAMES and never their prose — that is
    `HealthSignal`'s hard-rule-6 line and it is why this renders `signal.causes` rather
    than looking for a reason string.
    """
    del context, args
    board = await client_health(session)
    lines = [
        _clean(
            f"{row.name} ({row.slug}, {row.plan_tier}) — {row.severity}: "
            + "; ".join(
                signal.rule
                + (f" x{signal.count}" if signal.count is not None else "")
                + (f" [{', '.join(signal.causes)}]" if signal.causes else "")
                for signal in row.signals
            )
            + f"; {row.volume.calls_7d} calls in 7d (prev {row.volume.calls_prev_7d}, "
            f"basis {row.volume.basis}), last call {_when(row.volume.last_call_at)}"
        )
        for row in board
    ]
    return _listing(
        lines,
        total=len(board),
        shown_of="flagged accounts",
        nothing="No account has a live health signal — nothing is flagged right now.",
    )


async def _platform_ops_state(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """Is the platform dialling, is our telemarketer registration live, and how much of
    this month's AI budget is left.

    THREE FACTS AN OPERATOR CHECKS TOGETHER, in one tool, because they are the three that
    decide whether an incident is ours: the big red switch, the DLT registration that makes
    a commercial dial legal at all, and the ceiling that pauses every AI surface on the
    platform. Each is read through the function that OWNS it — `read_halt_state`,
    `read_tm_registration`, `read_platform_ai_spend` — never re-queried here, so the
    assistant and the ops console cannot disagree about a halt.
    """
    del context, args
    halt = await read_halt_state(session)
    registration = await read_tm_registration(session)
    spend = await read_platform_ai_spend(session)
    return _clean(
        "Outbound dialling: "
        + (f"HALTED — {halt.reason or 'no reason recorded'}" if halt.outbound_halted else "running")
        + f"\nTelemarketer (TM) registration: {registration.status}"
        + (" (live — commercial dialling is permitted)" if registration.is_live else "")
        + (f", TM id {registration.tm_id}" if registration.tm_id else "")
        + f"\nPlatform AI spend {spend.month}: INR {spend.spend_inr} of {PLATFORM_AI_BRAKE_INR} "
        f"({spend.requests} metered request(s))"
        + (
            " — BRAKE TRIPPED, AI help is paused for every tenant and for this console"
            if spend.tripped
            else ""
        )
    )


async def _search_runbooks(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """The runbook sections that answer an operator's question, verbatim.

    NO SESSION IS USED and the parameter is accepted only because the registry has one
    signature — `tools._Executor`'s shape, which `write_tools.Executor` also matches, and
    two calling conventions in one package is the drift CLAUDE.md calls a defect even when
    both work. `ReadTool.scope` records the one round trip that costs.

    VERBATIM, and truncated VISIBLY. A runbook is a procedure somebody will follow during
    an incident, so a paraphrase is the one thing this must not return; when a section does
    not fit, the marker is what lets the model say "open the file" instead of answering
    from half of it.
    """
    del session, context
    question = str(args.get("question") or "").strip()
    if not question:
        return "Ask again with the question you want the runbooks searched for."
    if not runbook_index.index():
        # NOT "there is no runbook for that". The corpus could not be read, and saying so
        # is the difference between an operator opening the file themselves and an
        # operator believing nothing is written down (hard rule 11's shape, in a sentence
        # a model will repeat).
        return (
            "The runbooks could not be read in this deployment, so I cannot search them. "
            "Tell the operator to open runbooks/ directly — do not answer from memory."
        )
    found = runbook_index.search(question)
    if not found:
        return (
            "No runbook section matched that. Say so rather than guessing a procedure — "
            "an invented incident step is worse than none."
        )
    passages = []
    for section in found:
        body = section.body
        if len(body) > runbook_index.MAX_SECTION_CHARS:
            body = body[: runbook_index.MAX_SECTION_CHARS].rstrip() + "\n… (section truncated)"
        passages.append(f"[{section.title}]\n{body}")
    return _clean("\n\n".join(passages))


ADMIN_READ_TOOLS: Final[tuple[ReadTool, ...]] = (
    ReadTool(
        name="platform_tenants",
        description=(
            "Every client account on the platform, newest first: name, slug, status, "
            "vertical, how many live agents, calls in the last 7 days, total leads, when "
            "they last made a call, whether they are spend-capped, and which human-action "
            "gates are holding them. Use it to answer which clients exist and what state "
            "an account is in."
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
        permission="admin:tenants",
        scope="platform",
        run=_platform_tenants,
    ),
    ReadTool(
        name="platform_health",
        description=(
            "The client triage board: every account with at least one live health signal, "
            "worst first, with the rule names that fired (spend cap, KYC missing, PE "
            "registration missing, stalled pipeline, knowledge waiting, failed webhook "
            "deliveries, call volume collapse) and this week's call volume against last "
            "week's. Use it to answer which clients need attention."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        permission="admin:tenants",
        scope="platform",
        run=_platform_health,
    ),
    ReadTool(
        name="platform_ops_state",
        description=(
            "The platform's own state right now: whether outbound dialling is halted (the "
            "big red switch) and why, whether Calevate's telemarketer registration is live, "
            "and how much of this month's platform-wide AI budget has been spent against "
            "the ceiling that pauses AI for everyone. Call this before saying anything "
            "about whether the platform is working."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        permission="admin:tenants",
        scope="platform",
        run=_platform_ops_state,
    ),
    ReadTool(
        name="search_runbooks",
        description=(
            "Search Calevate's own operator runbooks — the written incident procedures in "
            "runbooks/, including the alarm index that maps an alarm code to what to do "
            "about it. Use it for any 'what do I do when X' or 'how do I recover Y' "
            "question, and quote the steps it returns rather than writing your own."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "What the operator needs to do, or the alarm code they are looking "
                        "at, e.g. 'engine_error_spike' or 'restore the database'."
                    ),
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        # THE SAME DOOR AS THE CONSOLE ITSELF. The runbooks are internal operating
        # procedure, not public documentation: they name hosts, units and recovery
        # commands. `admin:tenants` is held by both admin roles and by no client role.
        permission="admin:tenants",
        scope="platform",
        run=_search_runbooks,
    ),
)

ADMIN_READ_TOOL_NAMES: Final[frozenset[str]] = frozenset(tool.name for tool in ADMIN_READ_TOOLS)


__all__ = ["ADMIN_READ_TOOLS", "ADMIN_READ_TOOL_NAMES"]
