"""Name one call's knowledge-gap topics from what this business is (G5-4, L5-16).

`insights/detection.py` decides that a caller asked something the agent could not answer and
files it under a keyword topic. Keywords cannot hear a question in a script the word lists
do not carry, and their menu is one view of a shop. This job asks the model once per call
with gaps: here is the business, here are the topics it already has, file each question under
one of them or name a new one in the owner's terms. The gaps are then re-filed
(`insights.service.rename_call_topics`), merged where two questions are one topic.

Queued by `insights.service.record_call_gaps` in the transaction that wrote the gaps.

- **Gemini only** (`ask_json(gemini_only=True)`): the input is callers' redacted questions,
  and the standby leg's terms permit training on inputs (Sarvam ToS s.17.5), the rule
  `workers/teach_questions.py` and D-827's business copy follow.
- **What the model sees** is redacted: the stored quotes (`transcript_turns.text_redacted`
  copies) and `lead_fields_draft.business_context`. Nothing of it is logged (hard rule 6).
- **Metered** as `kb_teach` against the client's AI allowance (`require_ai_assist`), the
  feature whose list these topics fill. Allowance used up, no model, a refusal or an
  unusable answer: the keyword topics stay, which is what the client saw before.
"""

from __future__ import annotations

import re
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.assist_leg import google_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, require_ai_assist
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.insights import detection
from apps.api.insights import service as gap_service
from apps.api.teach.teaching import ASSIST_FEATURE_KB_TEACH
from apps.api.tenancy.business_copy import capabilities_for
from apps.workers.lead_fields_draft import business_context
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

JOB_NAME: Final = gap_service.NAME_TOPICS_JOB
NAME_MAX_TOKENS: Final = 600
NAME_TIMEOUT_S: Final = 30.0
#: The business's own topics offered besides the canonical ones, most recent first: enough
#: for a small business's whole list, few enough to keep the prompt short.
MAX_KNOWN_TOPICS: Final = 40
#: A topic name is a heading on the owner's list.
MAX_TOPIC_CHARS: Final = 40
#: A topic the model names is keyed by its words, so two calls naming it alike aggregate.
#: The prefix keeps it apart from a canonical key and a caller's-words key (`q_`).
NAMED_PREFIX: Final = "t_"
_MAX_KEY_WORDS_CHARS: Final = 60

SYSTEM_PROMPT: Final = (
    "A small Indian business's phone agent could not answer some callers' questions. File "
    "each numbered question under the topic this business's owner would put it under on "
    "their list of questions to answer. When one of the known topics fits, give its key. "
    "Otherwise name a new topic: 1 to 4 plain English words, a heading, in this business's "
    "own terms. The questions may be in any language or script; a topic name is always "
    "English. Questions about the same thing get the same topic. Never put a name, a number "
    "or a price in a topic name. "
    'Return ONLY JSON: {"topics": [{"n": the question number, "key": a known key or null, '
    '"name": the topic name}]}.'
)

_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "key": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "name": {"type": "string"},
                },
                "required": ["n", "key", "name"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["topics"],
    "additionalProperties": False,
}

_NOT_A_KEY: Final = re.compile(r"[^a-z0-9]+")
_DIGIT: Final = re.compile(r"\d")


def named_topic(name: object, known: dict[str, str]) -> tuple[str, str] | None:
    """(key, label) for a topic the model named; the known topic when its words make that
    key; None for a name that cannot be a heading (empty, too long, a figure in it, or no
    letter a key can be made of)."""
    label = " ".join(str(name or "").split())
    if not label or len(label) > MAX_TOPIC_CHARS or _DIGIT.search(label):
        return None
    words = _NOT_A_KEY.sub("_", label.lower()).strip("_")[:_MAX_KEY_WORDS_CHARS].strip("_")
    if not words:
        return None
    key = NAMED_PREFIX + words
    return (key, known[key]) if key in known else (key, label[0].upper() + label[1:])


def parse_topics(
    raw: dict[str, Any], count: int, known: dict[str, str]
) -> list[tuple[str, str]] | None:
    """One (key, label) per question, in question order; None for an answer that does not
    file every question exactly once, so the ladder's repair gets its chance."""
    items = raw.get("topics")
    if not isinstance(items, list):
        return None
    filed: dict[int, tuple[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        n = item.get("n")
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= count or n in filed:
            return None
        key = item.get("key")
        topic = (
            (key, known[key])
            if isinstance(key, str) and key in known
            else named_topic(item.get("name"), known)
        )
        if topic is None:
            return None
        filed[n] = topic
    if len(filed) != count:
        return None
    return [filed[n] for n in range(1, count + 1)]


def prompt_for(description: str, known: dict[str, str], gaps: list[detection.DetectedGap]) -> str:
    topics = "\n".join(f"- {key}: {label}" for key, label in known.items()) or "(none yet)"
    asked = "\n".join(
        f"{n}. Caller: {' '.join(gap.question_redacted.split())}\n"
        f"   Agent: {' '.join(gap.answer_redacted.split())}"
        for n, gap in enumerate(gaps, start=1)
    )
    return f"The business:\n{description}\n\nKnown topics:\n{topics}\n\nQuestions:\n{asked}"


async def _known_topics(tenant_id: UUID) -> dict[str, str]:
    """The canonical topics this business may have, then the ones its gaps already use."""
    async with tenant_session(tenant_id) as session:
        withheld = detection.withheld_topics(await capabilities_for(session, tenant_id))
        rows = await session.execute(
            text(
                "SELECT topic_key, (array_agg(topic_label ORDER BY last_seen_at DESC))[1] "
                "AS label FROM knowledge_gaps GROUP BY topic_key "
                "ORDER BY max(last_seen_at) DESC LIMIT :limit"
            ),
            {"limit": MAX_KNOWN_TOPICS},
        )
        own = [(str(r.topic_key), str(r.label)) for r in rows]
    known = dict(detection.topic_menu(withheld))
    for key, label in own:
        # A caller's-words topic (`q_…`) is one question, not a heading to file others under.
        if not key.startswith("q_") and key not in withheld:
            known.setdefault(key, label)
    return known


async def name_gap_topics(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Name this call's gap topics; returns the outcome it logged."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    try:
        outcome = await _name(tenant_id, UUID(str(payload["agent_id"])), call_id)
    except Exception:
        # The keyword topics stay; nothing the caller said is in the log line.
        log.exception(
            "gap_topics_crashed", extra={"tenant_id": str(tenant_id), "call_id": str(call_id)}
        )
        return "failed"
    log.info(
        "gap_topics_named",
        extra={"tenant_id": str(tenant_id), "call_id": str(call_id), "outcome": outcome},
    )
    return outcome


async def _name(tenant_id: UUID, agent_id: UUID, call_id: UUID) -> str:
    gaps = await gap_service.call_gaps(tenant_id=tenant_id, call_id=call_id)
    if not gaps:
        return "no_gaps"
    async with tenant_session(tenant_id) as session:
        try:
            await require_ai_assist(session, tenant_id=tenant_id)
        except ProblemError:
            return "no_allowance"
    leg = google_assist_leg()
    if not leg.serves_dashboard:
        return "no_model"
    known = await _known_topics(tenant_id)
    description, _vertical = await business_context(tenant_id)
    try:
        answer: JsonAnswer[list[tuple[str, str]]] = await ask_json(
            prompt_for(description, known, gaps),
            SYSTEM_PROMPT,
            parse=lambda raw: parse_topics(raw, len(gaps), known),
            azure_format={
                "type": "json_schema",
                "json_schema": {"name": "gap_topics", "strict": True, "schema": _SCHEMA},
            },
            tenant_leg=leg,
            max_tokens=NAME_MAX_TOKENS,
            temperature=0.1,
            timeout_s=NAME_TIMEOUT_S,
            health_leg="teach",
            gemini_only=True,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=ASSIST_FEATURE_KB_TEACH
            )
        return "refused"
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
    renamed = await gap_service.rename_call_topics(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        named=[(gap.topic_key, topic) for gap, topic in zip(gaps, answer.value, strict=True)],
    )
    return "named" if renamed else "stale"


__all__ = [
    "JOB_NAME",
    "SYSTEM_PROMPT",
    "name_gap_topics",
    "named_topic",
    "parse_topics",
    "prompt_for",
]
