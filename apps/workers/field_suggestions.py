"""Suggest changes to one agent's lead details from what the business sells and what its
callers ask for (D-889), and rebuild what an agent asks after its details changed.

Queued through the outbox by `agents/field_suggestions.queue_pass`. One pass:

1. **Claim** `field_suggestions_state` from `queued` to `running` (compare-and-swap).
2. **Read** the business's details, the agent's script, the quick facts, the agent's fields,
   and the unlisted answers and captured choices of the last `RECENT_DAYS` days. Everything a
   caller said is redacted first (D-127 G-1/G-2), and the question goes to Gemini only
   (`gemini_only`, D-827's rule for caller words: Sarvam's terms permit training on inputs).
3. **Unchanged?** When these hash the same as the last finished pass, nothing is spent. The
   owner's "Check again" forgets that hash (`queue_pass(force=True)`).
4. **May it spend?** A trial account's pass is ours; every other account's counts against its
   AI allowance (`require_ai_assist`). Used up, or the platform brake on: `skipped`.
5. **Ask once, clean, meter and store** together. The model's answer is never trusted as is:
   `suggestions_from_model` keeps only changes that fit the agent's fields, never removes a
   choice the agent captured recently, never suggests a detail every lead already carries,
   and drops what the owner turned down before.

When the pass ends and finds itself marked `queued` again (something changed while it ran), it
queues the next pass itself.

Nothing here is logged but ids, codes and counts (hard rule 6).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import CORE_KEYS, OUTPUT_KEYS
from calevate_shared.lead_fields import CORE_LEAD_FIELDS as CORE_FIELDS
from sqlalchemy import text

from apps.api.agents.assist_leg import google_assist_leg
from apps.api.agents.extraction_routes import validate_fields
from apps.api.agents.field_suggestions import (
    CHOICE_MAX,
    HINT_MAX,
    JOB,
    LABEL_MAX,
    MAX_CHOICES,
    REASON_MAX,
    RECENT_DAYS,
    RECOMPILE_COLLECT_JOB,
    Source,
    Suggestion,
    applicable,
    current_fields,
    normalise,
    suggestion_fingerprint,
)
from apps.api.agents.models import MAX_FIELD_SUGGESTIONS
from apps.api.agents.script_builder import recompile_collect
from apps.api.billing.ai_quota import new_assist_ref, platform_brake_tripped, require_ai_assist
from apps.api.billing.models import (
    ASSIST_FEATURE_FIELD_SUGGESTIONS,
    ASSIST_FEATURE_FIELD_SUGGESTIONS_ABSORBED,
)
from apps.api.billing.trials import trial_billing_active
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.crm.columns import FIXED_KEYS
from apps.api.db.session import tenant_session
from apps.api.reliability.service import enqueue_outbox
from apps.api.teach.pinned import list_pinned
from apps.workers.lead_fields_draft import _key_for, business_context
from apps.workers.redaction import redact
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

JOB_NAME: Final = JOB
COLLECT_JOB_NAME: Final = RECOMPILE_COLLECT_JOB

TIMEOUT_S: Final = 45.0
MAX_TOKENS: Final = 1500
SCRIPT_CHARS: Final = 5000
FACTS_CHARS: Final = 2000
#: Unlisted answers shown per field, most asked first.
UNLISTED_PER_FIELD: Final = 10
#: Choices a suggested new field may have.
NEW_FIELD_CHOICES: Final = (2, 12)

SYSTEM_PROMPT: Final = (
    "You keep one phone agent's lead details in step with the small Indian business it works "
    "for. Lead details are what the agent records about each CALLER after a call: what they "
    "asked for and told us about themselves. A choice detail has a fixed list of choices. "
    "You are given the business's own description, the agent's script, its quick facts, the "
    "agent's current lead details, and what callers recently asked for that none of a "
    "detail's choices fitted, with how many callers said it.\n"
    "Suggest only changes that make the details fit THIS business better, of three kinds:\n"
    "- add_choices: choices a choice detail lacks, for something the business sells or "
    "handles (named in its description, script or facts), or that at least 2 callers asked "
    "for. Write each choice in the same style as the existing ones, at most "
    f"{CHOICE_MAX} characters.\n"
    "- remove_choices: only a choice for something this business plainly does not deal in "
    "at all. Never remove one because it is sold out or rare: the details record what "
    "callers want, which is worth knowing even when the business cannot supply it.\n"
    "- new_field: only when the script asks callers for something no detail records, or "
    "callers keep giving a detail the business would act on. Never a detail for the "
    "caller's name, phone number, preferred time, language, notes or what they want: every "
    "lead already records those. Give a label of 2 to 4 plain words, choices when a short "
    f"fixed list fits ({NEW_FIELD_CHOICES[0]} to {NEW_FIELD_CHOICES[1]}) or none for free "
    "text, and a hint: one sentence telling the note-taker what to record.\n"
    "For each, reason: one plain English sentence for the owner saying where it came from "
    '("Your script lists 2BHK and 3BHK flats", "3 callers asked for 6BHK"), and source: '
    "script, business, facts or calls. Never invent products the inputs do not mention. "
    "Name no company, brand or technology. At most "
    f"{MAX_FIELD_SUGGESTIONS} suggestions; none at all is a good answer when the details "
    "already fit. Return ONLY JSON: "
    '{"suggestions": [{"kind": str, "field_key": str or null, "label": str or null, '
    '"values": [str], "hint": str or null, "reason": str, "source": str}]}.'
)

_ANSWER_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["add_choices", "remove_choices", "new_field"],
                    },
                    "field_key": {"type": ["string", "null"]},
                    "label": {"type": ["string", "null"]},
                    "values": {"type": "array", "items": {"type": "string"}},
                    "hint": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                    "source": {"type": "string", "enum": ["script", "business", "facts", "calls"]},
                },
                "required": ["kind", "field_key", "label", "values", "hint", "reason", "source"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Inputs:
    """What one pass reads. `unlisted` and `captured` are keyed by field key; `unlisted`
    values are `(redacted words, callers)` and `captured` maps a choice to how often the
    agent recorded it."""

    description: str
    fields: list[ExtractionField]
    unlisted: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    captured: dict[str, dict[str, int]] = field(default_factory=dict)
    dismissed: frozenset[str] = frozenset()

    def digest(self) -> str:
        """The hash a later pass compares against. An unlisted answer counts once it has been
        heard twice, so one more caller saying the same thing does not buy another pass."""
        repeated = {
            key: sorted(normalise(said) for said, n in rows if n >= 2)
            for key, rows in self.unlisted.items()
        }
        body = json.dumps(
            {
                "d": self.description,
                "f": [f.model_dump() for f in self.fields],
                "u": repeated,
                "x": sorted(self.dismissed),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(body.encode()).hexdigest()


def _clip(value: Any, limit: int) -> str:
    words = " ".join(str(value or "").split())
    if len(words) <= limit:
        return words
    return words[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")


def _choices(raw: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        choice = _clip(item, CHOICE_MAX)
        if choice and normalise(choice) and normalise(choice) not in seen:
            seen.add(normalise(choice))
            out.append(choice)
    return out


def _callers_for(values: list[str], rows: list[tuple[str, int]]) -> int:
    """Calls whose unlisted answer one of `values` would have caught: the same words, or one
    containing the other once spacing and case are ignored ("6 BHK" and "6BHK flat")."""
    wanted = [normalise(v) for v in values]
    return sum(
        n
        for said, n in rows
        if any(w and (w == normalise(said) or w in normalise(said)) for w in wanted)
    )


def suggestions_from_model(raw: dict[str, Any], inputs: Inputs) -> list[Suggestion]:
    """The model's answer as suggestions that can stand, or fewer. Tolerant like
    `business_outcomes_draft.outcomes_from_model`: a malformed or unsafe item is dropped."""
    items = raw.get("suggestions")
    if not isinstance(items, list):
        return []
    by_key = {f.key: f for f in inputs.fields}
    taken = set(by_key) | set(CORE_KEYS) | set(FIXED_KEYS) | set(OUTPUT_KEYS)
    out: list[Suggestion] = []
    ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or len(out) >= MAX_FIELD_SUGGESTIONS:
            continue
        suggestion = _one(item, inputs, by_key, taken)
        if suggestion is None or suggestion.id in ids or suggestion.id in inputs.dismissed:
            continue
        if not applicable(suggestion, inputs.fields):
            continue
        ids.add(suggestion.id)
        if suggestion.field is not None:
            taken.add(suggestion.field.key)
        out.append(suggestion)
    return out


def _one(
    item: dict[str, Any],
    inputs: Inputs,
    by_key: dict[str, ExtractionField],
    taken: set[str],
) -> Suggestion | None:
    kind = item.get("kind")
    source = item.get("source")
    reason = _clip(item.get("reason"), REASON_MAX)
    if source not in ("script", "business", "facts", "calls") or not reason:
        return None
    values = _choices(item.get("values"))
    if kind == "new_field":
        return _new_field(item, values, reason, source, inputs, taken)
    if kind not in ("add_choices", "remove_choices"):
        return None
    target = by_key.get(str(item.get("field_key") or ""))
    if target is None or target.type != "enum":
        return None
    have = {normalise(v): v for v in target.enum_values or []}
    if kind == "add_choices":
        values = [v for v in values if normalise(v) not in have]
        if not values or len(have) + len(values) > MAX_CHOICES:
            return None
        callers = _callers_for(values, inputs.unlisted.get(target.key, []))
    else:
        recorded = inputs.captured.get(target.key, {})
        # The stored spelling, and never one the agent captured recently: removing a choice
        # callers are choosing would turn their answers into unlisted ones.
        values = [
            have[normalise(v)]
            for v in values
            if normalise(v) in have and not recorded.get(have[normalise(v)])
        ]
        if not values or len(have) - len(values) < 2:
            return None
        callers = 0
    return Suggestion(
        id=suggestion_fingerprint(kind, target.key, values),
        kind=kind,
        field_key=target.key,
        field_label=target.label,
        values=values,
        reason=reason,
        source=source,
        callers=callers,
    )


def _new_field(
    item: dict[str, Any],
    values: list[str],
    reason: str,
    source: Source,
    inputs: Inputs,
    taken: set[str],
) -> Suggestion | None:
    label = _clip(item.get("label"), LABEL_MAX)
    key = _key_for(label, set()) if label else None
    # A label that spells a detail the agent or every lead already has ("Name", "BHK" a
    # second time) is that detail again, not a new one; a numbered "name_2" would be a
    # second column for the same answer.
    labels = {normalise(f.label) for f in inputs.fields} | {normalise(f.label) for f in CORE_FIELDS}
    if key is None or key in taken or normalise(label) in labels:
        return None
    low, high = NEW_FIELD_CHOICES
    choices = values if low <= len(values) <= high else []
    candidate = ExtractionField(
        key=key,
        label=label,
        type="enum" if choices else "text",
        enum_values=choices or None,
        reason=_clip(item.get("hint"), HINT_MAX),
        required=False,
    )
    try:
        validate_fields([*inputs.fields, candidate])
    except ProblemError:
        return None
    return Suggestion(
        id=suggestion_fingerprint("new_field", "", choices, label),
        kind="new_field",
        field_key=key,
        field_label=label,
        values=choices,
        field=candidate,
        reason=reason,
        source=source,
        callers=0,
    )


def script_text(script: Any) -> str:
    """The business-facing words of a saved script: what it says the business is, sells,
    asks and answers. Read defensively, so an older script shape costs a line, not the pass."""
    if not isinstance(script, dict):
        return ""
    lines: list[str] = []
    for key, title in (
        ("business_line", "The business"),
        ("identity", "Who the agent is"),
        ("goal", "What the agent is for"),
        ("outbound_purpose", "Why it calls"),
    ):
        if script.get(key):
            lines.append(f"{title}: {script[key]}")
    for stage in script.get("stages") or []:
        if isinstance(stage, dict):
            lines.append(f"Step '{stage.get('name', '')}': {stage.get('instruction', '')}")
    for step in script.get("steps") or []:
        if isinstance(step, dict) and step.get("instruction"):
            lines.append(f"Step: {step['instruction']}")
    for faq in script.get("faqs") or []:
        if isinstance(faq, dict):
            lines.append(f"Q: {faq.get('question', '')} A: {faq.get('answer', '')}")
    for objection in script.get("objections") or []:
        if isinstance(objection, dict):
            lines.append(
                f"If a caller says {objection.get('objection', '')}: "
                f"{objection.get('response', '')}"
            )
    if script.get("raw_override"):
        lines.append(f"Script: {script['raw_override']}")
    return "\n".join(" ".join(str(line).split()) for line in lines)


async def gather(tenant_id: UUID, agent_id: UUID, *, dismissed: list[str]) -> Inputs:
    description, _vertical = await business_context(tenant_id)
    async with tenant_session(tenant_id) as session:
        script = (
            await session.execute(
                text(
                    # The latest saved script, staged or live: the owner's newest word on
                    # what the business sells.
                    "SELECT pv.structured_script FROM agents a LEFT JOIN prompt_versions pv "
                    "ON pv.id = COALESCE(a.system_prompt_id, a.live_prompt_id) "
                    "WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).scalar()
        facts = await list_pinned(session)
        fields = await current_fields(session, agent_id)
        choice_keys = [f.key for f in fields if f.type == "enum"]
        unlisted_rows = (
            (
                await session.execute(
                    text(
                        "SELECT kv.key, kv.value FROM call_extractions ce "
                        "JOIN calls c ON c.id = ce.call_id AND c.tenant_id = ce.tenant_id "
                        "CROSS JOIN LATERAL jsonb_each_text(ce.unlisted) AS kv "
                        "WHERE c.agent_id = :aid AND ce.unlisted IS NOT NULL "
                        f"AND ce.updated_at > now() - interval '{RECENT_DAYS} days'"
                    ),
                    {"aid": agent_id},
                )
            ).all()
            if choice_keys
            else []
        )
        captured_rows = (
            (
                await session.execute(
                    text(
                        "SELECT kv.key, kv.value, count(*) FROM call_extractions ce "
                        "JOIN calls c ON c.id = ce.call_id AND c.tenant_id = ce.tenant_id "
                        "CROSS JOIN LATERAL jsonb_each_text(ce.data) AS kv "
                        "WHERE c.agent_id = :aid AND kv.key = ANY(:keys) "
                        f"AND ce.updated_at > now() - interval '{RECENT_DAYS} days' "
                        "GROUP BY kv.key, kv.value"
                    ),
                    {"aid": agent_id, "keys": choice_keys},
                )
            ).all()
            if choice_keys
            else []
        )
    unlisted = _aggregate(unlisted_rows, choice_keys)
    captured: dict[str, dict[str, int]] = {}
    for key, value, count in captured_rows:
        captured.setdefault(str(key), {})[str(value)] = int(count)
    parts = [description]
    body = script_text(script)
    if body:
        parts.append("The agent's script:\n" + body[:SCRIPT_CHARS])
    if facts:
        quick = "\n".join(f"{f.question}: {f.answer}" if f.question else f.answer for f in facts)
        parts.append("Quick facts:\n" + quick[:FACTS_CHARS])
    parts.append("The agent's lead details now:\n" + _fields_text(fields))
    if any(unlisted.values()):
        parts.append("What callers asked for that no choice fitted:\n" + _unlisted_text(unlisted))
    return Inputs(
        description=redact("\n\n".join(parts)).text,
        fields=fields,
        unlisted=unlisted,
        captured=captured,
        dismissed=frozenset(dismissed),
    )


def _aggregate(rows: Any, choice_keys: list[str]) -> dict[str, list[tuple[str, int]]]:
    """Unlisted answers per field, one row per distinct answer (spacing and case aside), the
    most asked first. Redacted here: these are callers' words."""
    groups: dict[str, dict[str, tuple[str, int]]] = {}
    for key, said in rows:
        if key not in choice_keys or not said:
            continue
        words = redact(str(said)).text
        bucket = groups.setdefault(str(key), {})
        norm = normalise(words)
        first, n = bucket.get(norm, (words, 0))
        bucket[norm] = (first, n + 1)
    return {
        key: sorted(bucket.values(), key=lambda row: -row[1])[:UNLISTED_PER_FIELD]
        for key, bucket in groups.items()
    }


def _fields_text(fields: list[ExtractionField]) -> str:
    if not fields:
        return "(none beyond the details every lead carries)"
    lines = []
    for f in fields:
        if f.type == "enum":
            lines.append(f"- {f.key} '{f.label}': choices {', '.join(f.enum_values or [])}")
        else:
            lines.append(f"- {f.key} '{f.label}': free {f.type}")
    return "\n".join(lines)


def _unlisted_text(unlisted: dict[str, list[tuple[str, int]]]) -> str:
    return "\n".join(
        f"- {key}: "
        + "; ".join(f"'{said}' ({n} caller{'s' if n != 1 else ''})" for said, n in rows)
        for key, rows in unlisted.items()
        if rows
    )


async def _finish(tenant_id: UUID, agent_id: UUID, state: str) -> None:
    """Close the pass, or, when it was asked for again while it ran, start the next one."""
    async with tenant_session(tenant_id) as session:
        closed = (
            await session.execute(
                text(
                    "UPDATE agents SET field_suggestions_state = :state, "
                    "field_suggestions_at = now(), updated_at = now() "
                    "WHERE id = :aid AND field_suggestions_state = 'running' RETURNING id"
                ),
                {"state": state, "aid": agent_id},
            )
        ).first()
        if closed is None:
            await _requeue_if_asked(session, tenant_id, agent_id)


async def _requeue_if_asked(session: Any, tenant_id: UUID, agent_id: UUID) -> None:
    again = (
        await session.execute(
            text("SELECT field_suggestions_state FROM agents WHERE id = :aid"),
            {"aid": agent_id},
        )
    ).scalar()
    if again == "queued":
        await enqueue_outbox(
            session, job=JOB, payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
        )


async def _blocked(tenant_id: UUID, *, absorbed: bool) -> bool:
    async with tenant_session(tenant_id) as session:
        if absorbed:
            return await platform_brake_tripped(session)
        try:
            await require_ai_assist(session, tenant_id=tenant_id)
        except ProblemError:
            return True
    return False


async def _store(
    tenant_id: UUID,
    agent_id: UUID,
    inputs: Inputs,
    answer: JsonAnswer[list[Suggestion]] | None,
    *,
    feature: str,
) -> None:
    """Meter the answer and store the suggestions and the inputs hash in ONE transaction."""
    async with tenant_session(tenant_id) as session:
        if answer is not None:
            await crm_assist.meter_earlier(
                session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
            )
            await crm_assist.meter_assist(
                session,
                tenant_id=tenant_id,
                ref=new_assist_ref(),
                result=answer,
                feature=feature,
                model=answer.model,
            )
        suggestions = answer.value if answer is not None else []
        closed = (
            await session.execute(
                text(
                    "UPDATE agents SET field_suggestions = CAST(:s AS jsonb), "
                    "field_suggestions_inputs = :h, "
                    "field_suggestions_state = CASE WHEN field_suggestions_state = 'running' "
                    "  THEN 'done' ELSE field_suggestions_state END, "
                    "field_suggestions_at = now(), updated_at = now() "
                    "WHERE id = :aid RETURNING field_suggestions_state"
                ),
                {
                    "aid": agent_id,
                    "h": inputs.digest(),
                    "s": json.dumps([s.model_dump(mode="json") for s in suggestions]),
                },
            )
        ).scalar()
        if closed == "queued":
            await _requeue_if_asked(session, tenant_id, agent_id)


def _parser(inputs: Inputs) -> Any:
    def parse(raw: dict[str, Any]) -> list[Suggestion] | None:
        # An empty list is a real answer ("the details already fit"); only a malformed one is
        # no answer, so the ladder's repair gets its chance.
        if not isinstance(raw.get("suggestions"), list):
            return None
        return suggestions_from_model(raw, inputs)

    return parse


async def _run(tenant_id: UUID, agent_id: UUID, *, previous: str | None) -> str:
    async with tenant_session(tenant_id) as session:
        dismissed = (
            await session.execute(
                text("SELECT field_suggestions_dismissed FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).scalar()
        absorbed = await trial_billing_active(session, tenant_id=tenant_id)
    inputs = await gather(tenant_id, agent_id, dismissed=[str(d) for d in dismissed or []])
    if previous == inputs.digest():
        await _finish(tenant_id, agent_id, "done")
        return "unchanged"
    if await _blocked(tenant_id, absorbed=absorbed):
        await _finish(tenant_id, agent_id, "skipped")
        return "skipped"
    feature = (
        ASSIST_FEATURE_FIELD_SUGGESTIONS_ABSORBED if absorbed else ASSIST_FEATURE_FIELD_SUGGESTIONS
    )
    leg = google_assist_leg()
    if not leg.serves_dashboard:
        alert(
            "CORE_LOGIC",
            "lead_suggestions_unavailable",
            detail="The Gemini leg the lead-detail suggestions use cannot serve; none were made.",
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )
        await _finish(tenant_id, agent_id, "failed")
        return "failed"
    try:
        answer: JsonAnswer[list[Suggestion]] = await ask_json(
            inputs.description,
            SYSTEM_PROMPT,
            parse=_parser(inputs),
            azure_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "lead_detail_suggestions",
                    "strict": True,
                    "schema": _ANSWER_SCHEMA,
                },
            },
            tenant_leg=leg,
            max_tokens=MAX_TOKENS,
            temperature=0.2,
            timeout_s=TIMEOUT_S,
            health_leg="lead_suggestions",
            gemini_only=True,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        await _finish(tenant_id, agent_id, "failed")
        log.warning(
            "lead_suggestions_failed",
            extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "code": refused.code},
        )
        return "failed"
    await _store(tenant_id, agent_id, inputs, answer, feature=feature)
    return f"stored_{len(answer.value)}"


async def suggest_lead_details(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Claim the agent's queued pass, read, ask once, store what can stand."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    async with tenant_session(tenant_id) as session:
        claimed = (
            await session.execute(
                text(
                    "UPDATE agents SET field_suggestions_state = 'running', "
                    "field_suggestions_at = now(), updated_at = now() "
                    "WHERE id = :aid AND field_suggestions_state = 'queued' "
                    "AND deleted_at IS NULL RETURNING field_suggestions_inputs"
                ),
                {"aid": agent_id},
            )
        ).first()
    if claimed is None:
        outcome = "not_queued"
    else:
        try:
            outcome = await _run(tenant_id, agent_id, previous=claimed[0])
        except Exception:
            log.exception(
                "lead_suggestions_crashed",
                extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
            )
            await _finish(tenant_id, agent_id, "failed")
            outcome = "failed"
    log.info(
        "lead_suggestions_run",
        extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "outcome": outcome},
    )
    return outcome


async def rebuild_collect(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Rebuild what one agent asks callers for after its lead details changed (D-889), and
    republish it when it is live. A refusal from the voice platform keeps the agent on what it
    had and tells an operator; the owner's save already stood."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    agent_id = UUID(str(payload["agent_id"]))
    try:
        async with tenant_session(tenant_id) as session:
            version = await recompile_collect(session, tenant_id=tenant_id, agent_id=agent_id)
    except ProblemError as exc:
        log.warning(
            "collect_rebuild_refused", extra={"agent_id": str(agent_id), "reason": exc.code}
        )
        alert(
            "CORE_LOGIC",
            "collect_rebuild_not_delivered",
            detail=(
                "An agent's lead details changed but its script could not be rebuilt with them; "
                "it keeps asking for the previous ones. The reason code says why."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            reason=exc.code,
        )
        return "refused"
    return "rebuilt" if version is not None else "unchanged"


__all__ = [
    "COLLECT_JOB_NAME",
    "JOB_NAME",
    "SYSTEM_PROMPT",
    "Inputs",
    "gather",
    "rebuild_collect",
    "script_text",
    "suggest_lead_details",
    "suggestions_from_model",
]
