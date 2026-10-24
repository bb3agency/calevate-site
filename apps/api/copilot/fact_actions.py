"""Pin the questions callers ask most, with the business's answers (D-854).

The first-agent chat asks the owner for the three things callers ask most and their answers.
Those are pinned facts (`teach/pinned.py`): they belong to the business (D-689) and ride in
every agent's instructions, so a caller is never answered from a search that missed.

`confirm`, not `immediate`: a pinned fact reaches the callers of every live agent on the
next recompile, and an answer said to a caller cannot be taken back. One card carries all of
them, so the owner confirms the set with one press rather than three.

The executor is `POST /v1/kb/facts`'s own function (`pinned.add_pinned`) once per pair, so
the section ceiling and the live-agent fit check (D-752) run exactly as they do for the form.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.kb.curation import CURATE_PERMISSION
from apps.api.teach import pinned
from apps.api.teach.models import MAX_PINNED_ANSWER_CHARS, MAX_PINNED_QUESTION_CHARS
from apps.workers.redaction import redact

#: One card holds at most this many: the first-agent chat asks for three.
MAX_FACTS_PER_CARD: Final = 3


class _Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(max_length=MAX_PINNED_QUESTION_CHARS + 1)]
    answer: Annotated[str, Field(max_length=MAX_PINNED_ANSWER_CHARS + 1)]


class _PinArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: Annotated[list[_Fact], Field(min_length=1, max_length=MAX_FACTS_PER_CARD)]


def _clean(fact: _Fact) -> tuple[str, str]:
    question = " ".join(strip_invisible(fact.question).split())
    answer = strip_invisible(fact.answer).strip()
    if not question or not answer:
        raise WriteRefusedError("every fact needs the caller's question and the answer")
    if len(question) > MAX_PINNED_QUESTION_CHARS or len(answer) > MAX_PINNED_ANSWER_CHARS:
        raise WriteRefusedError(
            f"a question is at most {MAX_PINNED_QUESTION_CHARS} characters and an answer at "
            f"most {MAX_PINNED_ANSWER_CHARS}, so shorten it"
        )
    if redact(question).changed or redact(answer).changed:
        # The value is never named: this reason reaches a log line and the next prompt.
        raise WriteRefusedError(
            "a fact contains something shaped like a phone number, an email address or an "
            "identity number, which you may not write; say the person can add it on "
            "What your agents know themselves"
        )
    return question, answer


async def _plan_pin(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY: the facts are cleaned, duplicates of a pinned question refused, and the
    section ceiling asked before any card, so Confirm is never a click into a refusal."""
    del actor
    parsed = parse_args(_PinArgs, args)
    pairs = [_clean(fact) for fact in parsed.facts]
    asked = {question.casefold() for question, _ in pairs}
    if len(asked) != len(pairs):
        raise WriteRefusedError("two of these facts answer the same question; merge them")
    already = {(fact.question or "").casefold() for fact in await pinned.list_pinned(session)}
    repeated = [question for question, _ in pairs if question.casefold() in already]
    if repeated:
        raise WriteRefusedError(
            "the business already has a pinned answer to "
            + "; ".join(f"“{question}”" for question in repeated)
            + ", so leave that one out"
        )
    await pinned.assert_room(session, adding=pairs)
    count = len(pairs)
    return Plan(
        object_id="",
        title="Pin what callers ask most" if count > 1 else "Pin what callers ask",
        summary=(
            f"Every one of your agents answers {'these' if count > 1 else 'this'} the same "
            "way on every call, from the next time its script is refreshed."
        ),
        current=None,
        proposed="\n".join(f"{question} — {answer}" for question, answer in pairs),
        cost=None,
        reversal="Change or unpin any of them on What your agents know at any time.",
        args={"facts": [{"question": q, "answer": a} for q, a in pairs]},
    )


async def _execute_pin(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_PinArgs, args)
    ids: list[UUID] = []
    for fact in parsed.facts:
        question, answer = _clean(fact)
        ids.append(
            await pinned.add_pinned(
                session,
                tenant_id=actor.tenant_id,
                question=question,
                answer=answer,
                origin="taught",
                created_by=actor.user_id,
            )
        )
    return Executed(
        applied=True,
        detail=(
            "Pinned. Every agent answers "
            + ("these" if len(ids) > 1 else "this")
            + " from its next refresh, which takes a few seconds."
        ),
        # Ids and a count only (hard rules 4 and 6): the words live on the `kb_facts` rows,
        # where erasure reaches them.
        audit_summary={"fact_ids": [str(fact_id) for fact_id in ids], "count": len(ids)},
    )


KNOWLEDGE_FACTS_PIN: Final = ActionTool(
    name="knowledge_facts_pin",
    tier="confirm",
    undo=None,
    # `POST /v1/kb/facts`'s gate: `kb:write` with the owner's curation switch.
    permission=CURATE_PERMISSION,
    object_type="kb_fact",
    audit_action="kb_fact.add",
    where="on the What your agents know screen",
    schema=action_schema(
        "knowledge_facts_pin",
        "Pin up to three questions callers ask, each with the business's answer in the "
        "person's own words, so every agent answers them the same way. Never invent an "
        "answer, price or time: ask. For a longer document use `knowledge_teach`." + PROPOSES_ONLY,
        {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                    },
                    "required": ["question", "answer"],
                    "additionalProperties": False,
                },
            }
        },
    ),
    plan=_plan_pin,
    execute=_execute_pin,
)

FACT_ACTIONS: Final[tuple[ActionTool, ...]] = (KNOWLEDGE_FACTS_PIN,)

__all__ = ["FACT_ACTIONS", "KNOWLEDGE_FACTS_PIN", "MAX_FACTS_PER_CARD"]
