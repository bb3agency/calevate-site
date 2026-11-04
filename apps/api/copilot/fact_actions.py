"""Add the questions callers ask most, with the business's answers, to the business profile.

The first-agent chat (D-854) asks the owner for the three things callers ask most and their
answers. A question and its answer has ONE home: the business profile's common questions
(`tenancy/business_profile.Faq`), which every agent of the business carries in its facts
and which both the Business profile screen and What your agents know show and edit.

`confirm`, not `immediate`: the answers reach the callers of every live agent on the save,
and an answer said to a caller cannot be taken back. One card carries all of them, so the
owner confirms the set with one press rather than three.

The executor is `PATCH /v1/business-profile`'s own function (`profile_service.save_profile`),
so the profile's limits, the knowledge lock and the fan-out to every agent run exactly as
they do for the form.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final

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
from apps.api.tenancy.business_profile import (
    FAQ_ANSWER_MAX,
    FAQ_QUESTION_MAX,
    MAX_FAQS,
    Faq,
    load_profile,
)
from apps.workers.redaction import redact

#: One card holds at most this many: the first-agent chat asks for three.
MAX_FAQS_PER_CARD: Final = 3

_QUESTION_MAX: Final = FAQ_QUESTION_MAX
_ANSWER_MAX: Final = FAQ_ANSWER_MAX


class _Pair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(max_length=_QUESTION_MAX + 1)]
    answer: Annotated[str, Field(max_length=_ANSWER_MAX + 1)]


class _AddArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    faqs: Annotated[list[_Pair], Field(min_length=1, max_length=MAX_FAQS_PER_CARD)]


def _clean(pair: _Pair) -> Faq:
    question = " ".join(strip_invisible(pair.question).split())
    answer = strip_invisible(pair.answer).strip()
    if not question or not answer:
        raise WriteRefusedError("every entry needs the caller's question and the answer")
    if len(question) > _QUESTION_MAX or len(answer) > _ANSWER_MAX:
        raise WriteRefusedError(
            f"a question is at most {_QUESTION_MAX} characters and an answer at most "
            f"{_ANSWER_MAX}, so shorten it"
        )
    if redact(question).changed or redact(answer).changed:
        # The value is never named: this reason reaches a log line and the next prompt.
        raise WriteRefusedError(
            "an answer contains something shaped like a phone number, an email address or an "
            "identity number, which you may not write; say the person can add it on "
            "What your agents know themselves"
        )
    return Faq(question=question, answer=answer)


async def _checked(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> list[Faq]:
    """The cleaned entries, refused when two repeat each other, one repeats a question the
    profile already answers, or the profile would pass its limit."""
    adding = [_clean(pair) for pair in parse_args(_AddArgs, args).faqs]
    asked = {faq.question.casefold() for faq in adding}
    if len(asked) != len(adding):
        raise WriteRefusedError("two of these answer the same question; merge them")
    profile = await load_profile(session, tenant_id=actor.tenant_id)
    already = {faq.question.casefold() for faq in profile.faqs}
    repeated = [faq.question for faq in adding if faq.question.casefold() in already]
    if repeated:
        raise WriteRefusedError(
            "the business already answers "
            + "; ".join(f"“{question}”" for question in repeated)
            + ", so leave that one out or change it on What your agents know"
        )
    if len(profile.faqs) + len(adding) > MAX_FAQS:
        raise WriteRefusedError(
            f"the business profile holds at most {MAX_FAQS} common questions; "
            "remove one on What your agents know first"
        )
    return adding


async def _plan_add(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY: everything the save would refuse is refused before any card, so Confirm is
    never a click into a refusal."""
    adding = await _checked(session, actor, args)
    count = len(adding)
    return Plan(
        object_id=str(actor.tenant_id),
        title="Add what callers ask most" if count > 1 else "Add what callers ask",
        summary=(
            f"Every one of your agents answers {'these' if count > 1 else 'this'} the same "
            "way, and they show in your business details."
        ),
        current=None,
        proposed="\n".join(f"{faq.question} — {faq.answer}" for faq in adding),
        cost=None,
        reversal="Change or remove any of them on What your agents know at any time.",
        args={"faqs": [faq.model_dump() for faq in adding]},
    )


async def _execute_add(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    from apps.api.tenancy.profile_service import ProfilePatch, save_profile

    # Checked again against the profile as it is now: another save may have landed since
    # the card was drawn, and the section is replaced whole.
    adding = await _checked(session, actor, args)
    current = (await load_profile(session, tenant_id=actor.tenant_id)).faqs
    _steps, updated = await save_profile(
        session,
        tenant_id=actor.tenant_id,
        patch=ProfilePatch(faqs=[*current, *adding]),
        user_id=actor.user_id,
    )
    return Executed(
        applied=True,
        detail=(
            "Added. Every agent answers "
            + ("these" if len(adding) > 1 else "this")
            + f" now; {updated} agent(s) were updated."
        ),
        # Counts only (hard rule 6): the words live in the business profile.
        audit_summary={"sections": ["faqs"], "added": len(adding), "agents_updated": updated},
    )


BUSINESS_FAQS_ADD: Final = ActionTool(
    name="business_faqs_add",
    tier="confirm",
    undo=None,
    # `PATCH /v1/business-profile`'s gate.
    permission="org:manage",
    object_type="organization",
    audit_action="business_profile.updated",
    where="on the What your agents know screen",
    schema=action_schema(
        "business_faqs_add",
        "Add up to three caller questions to the business's common questions, each with the "
        "answer in the person's words. Never invent an answer, price or time: ask." + PROPOSES_ONLY,
        {
            "faqs": {
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
    plan=_plan_add,
    execute=_execute_add,
)

FACT_ACTIONS: Final[tuple[ActionTool, ...]] = (BUSINESS_FAQS_ADD,)

__all__ = ["BUSINESS_FAQS_ADD", "FACT_ACTIONS", "MAX_FAQS_PER_CARD"]
