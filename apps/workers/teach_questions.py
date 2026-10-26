"""Draft one guided question's answer from what the business already gave us (D-893).

Queued by a read of the questions list (`apps/api/teach/questions.list_questions`) once per
fingerprint of the question's inputs. One run:

1. **Claim**: the row must still be `queued` for exactly this fingerprint; a newer read that
   re-queued it under new inputs owns it now, so this run stops (`stale`).
2. **Sources**: the business's profile lines, facts, earlier answers and best-matching
   files (`questions.draft_sources`). None means nothing to ground a draft in: `none`.
3. **May it spend?** The client's AI allowance, the same rule the teach box's sorting
   meets (`require_ai_assist`, metered as `kb_teach`). Used up or paused: `none`, and the
   owner simply sees no draft.
4. **Ask Gemini, and only Gemini** (`ask_json(gemini_only=True)`): the question may be a
   caller's redacted words, and the standby leg's terms permit training on inputs (Sarvam
   ToS s.17.5), the reason D-827's business copy keeps to Gemini too.
5. **Keep only a grounded answer**: the model must name one of the numbered sources, and
   the draft is stored with that source; "no answer" or an unknown source stores `none`.
   Metering and the store happen in one transaction.

Nothing is logged but ids and outcomes (hard rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.assist_leg import google_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, require_ai_assist
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.teach import questions
from apps.api.teach.models import MAX_FACT_CHARS
from apps.api.teach.teaching import ASSIST_FEATURE_KB_TEACH
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

JOB_NAME: Final = questions.DRAFT_JOB
MAX_ANSWER_TOKENS: Final = 400

SYSTEM_PROMPT: Final = (
    "You help the owner of a small Indian business answer a question their phone agent "
    "is asked. Answer ONLY from the numbered sources, which are the business's own words. "
    "Write one or two short plain sentences a receptionist could say, in the language of "
    "the sources. Never add a price, time, place or promise that is not in a source, and "
    "never change a number. If no source answers the question, answer null. "
    'Return ONLY JSON: {"answer": str or null, "source": the number of the source used, '
    "or null}."
)

_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "answer": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "source": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    },
    "required": ["answer", "source"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Drafted:
    #: None when the sources do not answer the question.
    answer: str | None
    source: questions.Source | None


def parse_draft(raw: dict[str, Any], sources: list[questions.Source]) -> Drafted | None:
    """The model's answer, grounded or explicitly empty. A source number that names nothing
    is unusable (None), so the ladder's repair gets its chance; an answer with no source is
    treated as no answer, because a draft without a source is never offered."""
    answer = raw.get("answer")
    number = raw.get("source")
    if answer is None or not str(answer).strip():
        return Drafted(None, None)
    if not isinstance(number, int) or isinstance(number, bool):
        return Drafted(None, None)
    if not 1 <= number <= len(sources):
        return None
    cleaned = " ".join(str(answer).split())
    if len(cleaned) > MAX_FACT_CHARS:
        return None
    return Drafted(cleaned, sources[number - 1])


def prompt_for(question: questions.Question, sources: list[questions.Source]) -> str:
    numbered = "\n".join(
        f"{n}. ({source.label}) {' '.join(source.text.split())}"
        for n, source in enumerate(sources, start=1)
    )
    return f"Question: {question.question}\nTopic: {question.topic}\n\nSources:\n{numbered}"


async def _store_none(tenant_id: UUID, key: str, fingerprint: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE teach_questions SET draft_status = 'none', updated_at = now() "
                "WHERE question_key = :key AND inputs_hash = :hash AND draft_status = 'queued'"
            ),
            {"key": key, "hash": fingerprint},
        )


async def _claimed(tenant_id: UUID, key: str, fingerprint: str) -> questions.Question | None:
    """The question this run drafts, while its row still waits for exactly these inputs."""
    async with tenant_session(tenant_id) as session:
        waiting = (
            await session.execute(
                text(
                    "SELECT 1 FROM teach_questions WHERE question_key = :key "
                    "AND inputs_hash = :hash AND draft_status = 'queued'"
                ),
                {"key": key, "hash": fingerprint},
            )
        ).first()
        if waiting is None:
            return None
        listed = await questions.list_questions(session, tenant_id=tenant_id)
    return next((q for q in listed.items if q.key == key), None)


async def draft_teach_question(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Draft one question's answer; returns the outcome it logged."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    key = str(payload["question_key"])
    fingerprint = str(payload["inputs_hash"])
    outcome = await _draft(tenant_id, key, fingerprint)
    log.info("teach_question_drafted", extra={"tenant_id": str(tenant_id), "outcome": outcome})
    return outcome


async def _draft(tenant_id: UUID, key: str, fingerprint: str) -> str:
    question = await _claimed(tenant_id, key, fingerprint)
    if question is None:
        return "stale"
    async with tenant_session(tenant_id) as session:
        sources = await questions.draft_sources(session, tenant_id=tenant_id, question=question)
        if not sources:
            refused: str | None = "no_sources"
        else:
            try:
                await require_ai_assist(session, tenant_id=tenant_id)
                refused = None
            except ProblemError:
                refused = "no_allowance"
    if refused is not None:
        await _store_none(tenant_id, key, fingerprint)
        return refused
    leg = google_assist_leg()
    if not leg.serves_dashboard:
        await _store_none(tenant_id, key, fingerprint)
        return "no_model"
    try:
        answer: JsonAnswer[Drafted] = await ask_json(
            prompt_for(question, sources),
            SYSTEM_PROMPT,
            parse=lambda raw: parse_draft(raw, sources),
            azure_format={
                "type": "json_schema",
                "json_schema": {"name": "teach_question_draft", "strict": True, "schema": _SCHEMA},
            },
            tenant_leg=leg,
            max_tokens=MAX_ANSWER_TOKENS,
            temperature=0.1,
            health_leg="teach",
            gemini_only=True,
        )
    except ProblemError as failed:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=failed, feature=ASSIST_FEATURE_KB_TEACH
            )
        await _store_none(tenant_id, key, fingerprint)
        return "unanswered"
    drafted = answer.value
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=ASSIST_FEATURE_KB_TEACH
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=ASSIST_FEATURE_KB_TEACH,
            model=answer.model,
        )
        await session.execute(
            text(
                "UPDATE teach_questions SET draft_status = :status, draft = :draft, "
                "draft_source_kind = :kind, draft_source_label = :label, updated_at = now() "
                "WHERE question_key = :key AND inputs_hash = :hash AND draft_status = 'queued'"
            ),
            {
                "status": "ready" if drafted.answer else "none",
                "draft": drafted.answer,
                "kind": drafted.source.kind if drafted.answer and drafted.source else None,
                "label": drafted.source.label[:200] if drafted.answer and drafted.source else None,
                "key": key,
                "hash": fingerprint,
            },
        )
    return "drafted" if drafted.answer else "not_grounded"


__all__ = ["JOB_NAME", "SYSTEM_PROMPT", "draft_teach_question", "parse_draft", "prompt_for"]
