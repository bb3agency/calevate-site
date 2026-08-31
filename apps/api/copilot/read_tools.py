"""The copilot's ONE read tool: `search_knowledge`, over the retrieval port.

WHY THIS EXISTS AND WHY IT IS NOT SPECULATIVE. The copilot could answer about the screen
and could fill in fields, and could not answer the question a client asks most often about
their own account — "what does my agent tell people about X?". The facts are on file
(`prompt_versions.compiled_t0_context`, compiled from approved knowledge and the intake
sheet) and were addressable only from inside the agent's own prompt. This tool makes the
port a thing that is USED today rather than a seam waiting for a provider: every question
the model routes here goes through `apps/api/retrieval/service.look_up` — router, cache,
provider, measurement — which is exactly the path an in-call caller will take the day
TRD §6.2's round-trip measurement allows one.

THREE THINGS THIS FILE IS CAREFUL ABOUT, each of which is a rule rather than a preference:

1. **THE LOOP MUST STOP.** Multi-step retrieval is where agentic RAG runs away: each search
   is a turn, each turn resends the conversation, and a model that keeps almost-finding
   something will keep looking. `MAX_SEARCHES` is the explicit stop condition, it is small,
   and hitting it is not silence — the model is TOLD it has run out of searches and must
   answer with what it has. `service.MAX_TURNS` bounds the turns; this bounds the spend
   inside them.
2. **NO SESSION IS HELD ACROSS A MODEL CALL.** `copilot/routes.py` is emphatic that a
   streaming route must not hold a pooled connection across a provider round trip. So the
   lookup is a CLOSURE over the tenant id that opens its own `tenant_session`, reads, and
   closes it — inside one tool call, never across a turn. That is also what keeps the
   retrieval under the caller's RLS context rather than under a session this module chose.
3. **THE DEGRADATION IS SPOKEN, NOT SWALLOWED.** The router asks for t3 on an open-ended
   question and no provider serves t3 today. The port's answer is a T0 result carrying
   `unmet_capability`, and this file puts that in front of the model in words, so the
   person is told they are being answered from the compiled facts rather than from a search
   of everything they have published. A tool that quietly answered from a narrower corpus
   would be the silent no-op the whole port exists to forbid.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Final
from uuid import UUID

from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.retrieval.service import look_up

log = get_logger(__name__)

#: The name the tool travels under.
SEARCH_KNOWLEDGE_TOOL_NAME: Final = "search_knowledge"

#: How many searches ONE answer may spend. Two, not one: a person often asks about two
#: things in a sentence ("what do we say about parking and about walk-ins?"), and a single
#: search would answer half. Not three: a third is where "keep looking" starts, and the
#: cost is a whole extra turn — the conversation resent, the screen resent — for a corpus
#: that is at most a few dozen compiled lines.
MAX_SEARCHES: Final = 2

#: What the model is told when it has spent them. A sentence, not silence: a tool that
#: returns nothing invites another call.
BUDGET_SPENT: Final = (
    "No searches left for this answer. Answer with what you already have, and say plainly "
    "if you could not find it."
)

#: What the model is told when the account has nothing on file for the question. Phrased so
#: the model reports it rather than inventing around it — TRD §6's T4 behaviour, which is a
#: prompt instruction with no code behind it, reaching the dashboard leg.
NOTHING_FOUND: Final = (
    "Nothing in this account's published knowledge matches that. Say so — do not guess "
    "what the agent might say — and suggest adding it under Knowledge if it should be "
    "there."
)

#: Prepended when the port answered from a lower tier than the router asked for.
DEGRADED_NOTE: Final = (
    "NOTE: a full search of everything this account has published is not available, so "
    "this is only what is compiled into the agent's own script. Tell the person that."
)

#: One tool call may not drag a document into the prompt. Four passages of at most ~400
#: characters is a bounded, quotable answer; more is a wall the model paraphrases badly.
MAX_PASSAGES: Final = 4
MAX_PASSAGE_CHARS: Final = 400

#: What the loop calls: a question in, the tool's reply text out. A CALLABLE rather than an
#: object because it is one function of one argument, and because the loop must be able to
#: run with `None` — the Sarvam fallback leg has no tools at all (`service.
#: _answer_via_sarvam`), and a test leg wants a stub with no database behind it.
KnowledgeLookup = Callable[[str], Awaitable[str]]


def search_knowledge_tool() -> dict[str, Any]:
    """THE tool definition. Same subset and same discipline as `prompt.set_fields_tool` —
    `additionalProperties: false`, every property required, no `pattern`/`format`/`minLength`
    — so the two tools cannot disagree about what a strict schema is.

    THE DESCRIPTION IS WHERE THE ROUTING ADVICE LIVES, deliberately, rather than in
    `SYSTEM_PROMPT`: the static prefix is byte-identical on every request and is what makes
    prompt caching possible (`prompt.py`), so per-capability guidance belongs on the tool
    that may or may not be present. It says what the corpus IS — the account's own approved
    knowledge — because a model told only "search" will try it on questions about the
    screen, which this cannot answer and should not be asked.
    """
    return {
        "type": "function",
        "function": {
            "name": SEARCH_KNOWLEDGE_TOOL_NAME,
            "description": (
                "Look up what THIS account's live voice agents tell callers — their "
                "published knowledge and the business facts compiled into their scripts "
                "(opening hours, address, services and prices, staff, policies). Use it "
                "whenever the person asks what their agent says or knows about something. "
                "It cannot see the screen, other accounts, or anything not yet approved "
                "and published."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "The question in the caller's own words, e.g. 'what are the "
                            "opening hours on Sunday'. Do not include names, phone "
                            "numbers or email addresses."
                        ),
                    }
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    }


def render_passages(intent: str, rendered: list[str]) -> str:
    """The tool's reply body. Kept separate from the lookup so it is testable without a
    database, and so the wording is in one place rather than three branches."""
    header = f"Published knowledge for this account (matched as: {intent}):"
    return "\n".join([header, *rendered])


def knowledge_lookup(tenant_id: UUID) -> KnowledgeLookup:
    """Bind the tool to ONE tenant. The closure is the tenancy control at this layer.

    The model supplies a question and nothing else — it cannot name a tenant, an agent or a
    source, so there is no argument it can put in a tool call that widens the scope. The
    tenant id comes from the authenticated principal in `copilot/routes.py` and is captured
    here; `copilot/read_tools_test.py` asserts the tool schema has no field that could
    carry one.
    """

    async def lookup(question: str) -> str:
        # Invisible characters out on the way IN as well as out: the question is model
        # output, it becomes a Redis key and a SQL parameter, and `strip_invisible` is
        # already this package's answer to that (`sanitize.py`).
        cleaned = strip_invisible(question).strip()
        if not cleaned:
            return NOTHING_FOUND
        async with tenant_session(tenant_id) as session:
            decision, result = await look_up(
                session, tenant_id=tenant_id, question=cleaned, k=MAX_PASSAGES
            )
        if result.is_empty():
            return NOTHING_FOUND
        rendered = [
            f"- {passage.text[:MAX_PASSAGE_CHARS]} [{passage.provenance.label}]"
            for passage in result.passages
        ]
        body = render_passages(decision.intent, rendered)
        return f"{DEGRADED_NOTE}\n{body}" if result.unmet_capability is not None else body

    return lookup


async def serve_searches(
    tool_calls: list[Any],
    *,
    lookup: KnowledgeLookup,
    remaining: int,
) -> list[dict[str, Any]]:
    """Answer every `search_knowledge` call in one turn, as `role: tool` messages.

    Returns the messages to append; an empty list means the turn asked for no search and
    the caller should treat the turn as it always did.

    EVERY CALL GETS A REPLY, INCLUDING THE ONES OVER BUDGET. A model that sent two tool
    calls and got one answer is looking at a malformed conversation — providers reject a
    tool_call with no matching tool message — so the over-budget ones are answered with
    `BUDGET_SPENT` rather than dropped. That is also the honest sentence: the search did
    not happen, and the model is told so instead of inferring it from silence.
    """
    searches = [call for call in tool_calls if call.name == SEARCH_KNOWLEDGE_TOOL_NAME]
    if not searches:
        return []
    messages: list[dict[str, Any]] = []
    for index, call in enumerate(searches):
        if index >= remaining:
            content = BUDGET_SPENT
        else:
            content = await lookup(_question_of(call.arguments))
        messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
    return messages


def _question_of(arguments: str) -> str:
    """The `question` argument, or the empty string.

    Tolerant on purpose: a truncated or malformed tool call is an ordinary event on a
    streamed leg (`service._run_tool_loop` handles the same thing for `set_fields`), and
    the right answer to one is "I found nothing", not an exception that ends a stream
    somebody is reading.
    """
    try:
        parsed = json.loads(arguments)
    except (TypeError, ValueError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    question = parsed.get("question")
    return question if isinstance(question, str) else ""


__all__ = [
    "BUDGET_SPENT",
    "DEGRADED_NOTE",
    "MAX_PASSAGES",
    "MAX_SEARCHES",
    "NOTHING_FOUND",
    "SEARCH_KNOWLEDGE_TOOL_NAME",
    "KnowledgeLookup",
    "knowledge_lookup",
    "render_passages",
    "search_knowledge_tool",
    "serve_searches",
]
