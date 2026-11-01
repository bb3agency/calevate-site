"""The agent's opening line, written for THIS business and repaired rather than discarded
(D-957, founder 1 Nov 2026: the first agent's opening "can be more improvised and can be
relevant to the business and what info is all given").

The script writer drafts the opening with everything else. A drafted opening that breaks one
of the opening rules used to be replaced by the starter's reviewed line, the same for every
business. Here the model is asked for the opening alone, told the business (the owner's
description, documents, answers and facts, `ScriptBrief.user_message`) and, when a line was
already written, the exact problems with it. `opening_problems` is the one statement of the
rules: the first-run greeting check (`first_run.greeting_fits`) is "no problems", the writer's
instruction states the same rules in the same words (`spoken_guard`'s `*_RULE` constants), and
the problems sent back on a repair are those sentences.

Validate-and-repair rather than regenerate-and-hope: a model told precisely what failed fixes
it far more often than a fresh sample does (Self-Refine, Madaan et al. 2023,
https://arxiv.org/abs/2303.17651; the reask loop Instructor runs on a validator's error,
https://python.useinstructor.com/concepts/retrying/). The loop is bounded by the ladder it
runs on: ONE `ask_json` call, which is at most two answers from the paid leg (the second told
this module's problems) and one from the standby, all inside `ASSIST_LADDER_LEGS` request
budgets. The caller meters the answer or the refusal like any other assist.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from calevate_shared.spoken_guard import (
    INTRODUCED_GREETING_RULE,
    INTRODUCED_NAMES_RULE,
    OWN_LETTER_LANGUAGES,
    OWN_LETTERS_RULE,
    QUESTION_END_RULE,
    TEXTBOOK_RULE,
    UNINTRODUCED_RULE,
    introduced_opening_problem,
    latin_word_problem,
    question_end_problem,
    textbook_problem,
    unintroduced_opening_problem,
)

from apps.api.agents.call_rules import OPENING_LINE_MAX_CHARS, said_line_problem
from apps.api.agents.script_lint import LintContext, spoken_line_problems
from apps.api.core.logging import get_logger
from apps.api.tenancy.business_copy import provider_problem
from apps.workers.extraction import ASSIST_LADDER_LEGS, ASSIST_TIMEOUT_S, TenantModelLeg
from apps.workers.script_assist import JsonAnswer, ScriptBrief, UnusableAnswerError, ask_json

log = get_logger(__name__)

OPENING_PATH: Final = "opening_line"
OPENING_MAX_CHARS: Final = OPENING_LINE_MAX_CHARS

#: The longest the writer can take: one assist ladder. A caller with a job deadline starts it
#: only when this much is left.
OPENING_WRITER_BUDGET_S: Final = ASSIST_LADDER_LEGS * ASSIST_TIMEOUT_S

OPENING_WRITER_INSTRUCTION: Final = (
    "You write the opening line of an AI phone agent for a small Indian business: the words "
    "it says first on a call, spoken word for word. Make it about THIS business. An agent "
    "that answers calls names what callers of this business usually want, taken from the "
    "owner's description, documents, answers and facts in the brief, and asks about it as "
    "one short question, so the caller hears at once they reached the right place; an agent "
    "that only places calls says why it is calling and asks one short question. Never a "
    "line any business could use, never a list of products, an offer, a discount or a "
    "figure the owner's facts do not give, and nothing about being an AI or recording (the "
    "platform says those). Write it in the call language as people say it on the phone, "
    "following the spoken-style guide in the brief. The brief ends with the rules the line "
    "is checked against; a line that breaks one is not used. Return ONLY JSON: "
    '{"opening_line": "..."}.'
)

_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "opening_line",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"opening_line": {"type": "string"}},
            "required": ["opening_line"],
            "additionalProperties": False,
        },
    },
}


def length_problem(where: str, text: str) -> str | None:
    size = len(text.strip())
    if size <= OPENING_MAX_CHARS:
        return None
    return f"{where}: {size} characters; keep it to at most {OPENING_MAX_CHARS} characters"


def opening_problems(
    line: str,
    language: str | None,
    *,
    names: Sequence[str] = (),
    introduced: bool = False,
    where: str = OPENING_PATH,
) -> list[str]:
    """Every rule an opening line breaks, each as the sentence a model is sent to repair it:
    at most `OPENING_MAX_CHARS`, ending on a question, no textbook word, every word in the
    language's own letters apart from `names` (D-861, D-864), and placed for what comes
    before it (D-865): after the agent's introduction (`introduced`) it neither greets nor
    says `names`; said first, it greets or says who is calling."""
    clean = line.strip()
    if not clean:
        return [f"{where}: is empty; write the line"]
    found = (
        length_problem(where, clean),
        question_end_problem(where, clean),
        textbook_problem(where, clean, language),
        latin_word_problem(where, clean, language, names=names),
        introduced_opening_problem(where, clean, names=names)
        if introduced
        else unintroduced_opening_problem(where, clean, names=names),
    )
    return [problem for problem in found if problem]


def opening_rules(
    language: str | None, *, names: Sequence[str] = (), introduced: bool = False
) -> str:
    """`opening_problems`' rules as the writer is told them, in the same words."""
    kept = [name.strip() for name in names if name.strip()]
    rules = [
        f"at most {OPENING_MAX_CHARS} characters",
        QUESTION_END_RULE,
        TEXTBOOK_RULE,
    ]
    if language and language.split("-")[0].lower() in OWN_LETTER_LANGUAGES:
        rules.append(
            OWN_LETTERS_RULE
            + (f"; only these names may stay as written: {', '.join(kept)}" if kept else "")
        )
    if introduced:
        rules += [f"no greeting: {INTRODUCED_GREETING_RULE}", INTRODUCED_NAMES_RULE]
    else:
        rules.append(UNINTRODUCED_RULE)
    return "\n".join(f"- {rule}" for rule in rules)


def _writer_problems(
    line: str, brief: ScriptBrief, names: Sequence[str], lint: LintContext
) -> list[str]:
    """`opening_problems`, plus the checks the script writer holds every spoken line to: no
    provider's name (D-679), no claim of a done order (D-849), the script lint (D-945)."""
    extra = (
        provider_problem(OPENING_PATH, line),
        said_line_problem(OPENING_PATH, line),
    )
    return [
        *opening_problems(line, brief.language, names=names, introduced=brief.introduced),
        *(problem for problem in extra if problem),
        *spoken_line_problems(OPENING_PATH, line, lint),
    ]


#: Said with the task when the line is a "both" agent's opening on the calls it places (D-920,
#: D-959): the brief describes an agent that also answers, and the writer would otherwise
#: write the answering kind of line.
PLACED_TASK: Final = (
    "This opening_line is the one the agent says on a call it PLACES: it rang the person, so "
    "it says why it is calling and asks one short question. "
)


def opening_request(
    brief: ScriptBrief, *, line: str = "", problems: Sequence[str] = (), placed: bool = False
) -> str:
    """What the writer reads: the brief, the rules, and the line to repair with its problems
    when there is one. `placed` asks for the opening of the calls a "both" agent places."""
    names = (brief.business_name, brief.agent_name)
    task = (PLACED_TASK if placed else "") + (
        f"This opening_line was written for the agent and cannot be used: “{line.strip()}”. "
        f"Its problems: {'; '.join(problems)}. Write the opening_line again with every "
        "problem fixed, keeping what it says about this business."
        if line.strip() and problems
        else "Write the opening_line for this agent."
    )
    return (
        f"{brief.user_message()}\n\nRules for opening_line:\n"
        f"{opening_rules(brief.language, names=names, introduced=brief.introduced)}\n\n{task}"
    )


async def write_opening(
    brief: ScriptBrief,
    *,
    line: str = "",
    problems: Sequence[str] = (),
    tenant_leg: TenantModelLeg | None = None,
    quota_exhausted: bool = False,
    placed: bool = False,
) -> JsonAnswer[str]:
    """An opening line for the agent `brief` describes that keeps every rule, or the ladder's
    refusal (a `ProblemError`, a `SpentRefusalError` when a leg answered and must be
    metered). With `line` and its `problems`, the line is repaired; without, written.
    `placed`: the opening of the calls a "both" agent places, held to the same rules."""
    names = (brief.business_name, brief.agent_name)
    lint = brief.lint_context()

    def parse(raw: dict[str, Any]) -> str | None:
        value = raw.get("opening_line")
        if not isinstance(value, str) or not value.strip():
            return None
        written = " ".join(value.split())
        found = _writer_problems(written, brief, names, lint)
        if found:
            # Counts only: the line is the business's words (hard rule 6).
            log.info("opening_line_sent_back", extra={"problems": len(found)})
            raise UnusableAnswerError("; ".join(found))
        return written

    return await ask_json(
        opening_request(brief, line=line, problems=problems, placed=placed),
        OPENING_WRITER_INSTRUCTION,
        parse=parse,
        azure_format=_FORMAT,
        tenant_leg=tenant_leg,
        quota_exhausted=quota_exhausted,
        max_tokens=600,
        temperature=0.5,
        health_leg="script",
    )


__all__ = [
    "OPENING_MAX_CHARS",
    "OPENING_PATH",
    "OPENING_WRITER_BUDGET_S",
    "OPENING_WRITER_INSTRUCTION",
    "PLACED_TASK",
    "length_problem",
    "opening_problems",
    "opening_request",
    "opening_rules",
    "write_opening",
]
