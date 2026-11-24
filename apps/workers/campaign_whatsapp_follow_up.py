"""Pip writes a campaign's WhatsApp follow-up (D-1041): the message, and which of the
campaign's outcomes it is for.

Queued by `follow_ups/campaign_whatsapp.set_up` (the card's button, Pip's tool). One answer on
the account's dashboard AI ladder (`script_assist.ask_json`), written from the campaign's main
task and aims, what is known about the business (`lead_fields_draft.business_context`) and the
sources the campaign is written from (`company_training_draft.knowledge_words`). Everything
sent is redacted (D-127 G-1). The owner asked for this, so it does not wait for Pip's consent
the way the automatic passes do; it spends the AI allowance `set_up` checked.

GROUNDED OR NOT SENT. The message comes with a word-for-word quote of the material it rests
on, which the CODE must find there (`campaign_script_ask.quoted_in`); every figure in it must
be one the material has and it may name no technology company the material does not (D-679).
A message that fails any of these is not sent to WhatsApp for review: the pass fails with
`not_written` and the card says what to add.

THE OUTCOMES ARE THE CAMPAIGN'S OWN. The model picks, from the campaign agent's business
outcomes, those meaning the person did not finish or asked for details; a key not on that list
is dropped. The platform's "hung up early" is always added (`DID_NOT_FINISH`).

Metered as a script draft (hard rule 7), in the transaction that saves.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.languages import find_language
from sqlalchemy import text

from apps.api.agents import agent_pass
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.call_outcomes import outcomes_in_use
from apps.api.agents.languages import LANGUAGE_LABELS
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.first_run.models import KNOWLEDGE_DOCUMENT_CHARS
from apps.api.follow_ups import campaign_whatsapp as cw
from apps.api.tenancy.business_copy import provider_words
from apps.api.whatsapp.templates import client_template_languages
from apps.workers.campaign_script_ask import quoted_in
from apps.workers.company_training_draft import figures_in, knowledge_words
from apps.workers.first_run import documents_block
from apps.workers.lead_fields_draft import business_context
from apps.workers.redaction import redact
from apps.workers.script_assist import JsonAnswer, ask_json
from apps.workers.script_proposal import PROPOSAL_REQUEST_TIMEOUT_S

log = get_logger(__name__)

#: `follow_ups/campaign_whatsapp.JOB`; a literal so `scripts/check_job_wiring` reads it.
JOB_NAME: Final = "write_campaign_whatsapp_follow_up"
MAX_TOKENS: Final = 2_000
_QUOTE_MAX: Final = 300

ASK: Final = (
    "You write ONE WhatsApp message a business sends to a person a few minutes after its phone "
    "agent's call with them ended, because the call did not finish or the person asked for "
    "details. Write it in {language}, from the business's side, warm and short (at most "
    "{limit} characters), as a message a person reads on a phone: what the call was about and "
    "the one thing the person can do next, taken from the MAIN TASK and the material. Name "
    "the business. Use only what the material states: never add a price, product, link, "
    "place, time, offer or promise it does not state. No placeholders or blanks such as "
    "{{{{1}}}}, no markdown, no emoji. Under quote, put a short passage copied word for word "
    "from the material that the message rests on. Under outcomes, list the keys of the "
    "OUTCOMES below that mean the person did not finish the call or asked to be sent details; "
    "list none if none do."
)

_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "whatsapp_follow_up",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "quote": {"type": "string"},
                "outcomes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["message", "quote", "outcomes"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class Campaign:
    id: UUID
    name: str
    main_task: str
    aims: str
    classification: str
    #: WhatsApp's code for the message's language (`te`, `hi`, `en`).
    language: str
    language_label: str
    outcomes: tuple[BusinessOutcome, ...]
    source_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class Written:
    message: str
    outcomes: list[str]


def _clean(value: str) -> str:
    return redact(" ".join(value.split())).text


def request_text(campaign: Campaign, *, business: str, documents: str) -> tuple[str, str]:
    """(the request, the material a quote must be found in), both redacted."""
    main = _clean(campaign.main_task)
    aims = _clean(campaign.aims)
    outcomes = "\n".join(_clean(f"{o.key}: {o.label}. {o.meaning}") for o in campaign.outcomes)
    material = "\n\n".join(part for part in (main, aims, business, documents) if part)
    request = "\n\n".join(
        part
        for part in [
            f"MAIN TASK\n{main}",
            f"GOAL\n{aims}" if aims else "",
            f"THE BUSINESS\n{business}" if business else "",
            f"OUTCOMES\n{outcomes}" if outcomes else "",
            documents,
        ]
        if part
    )
    return request, material


def accepted(raw: dict[str, Any], *, campaign: Campaign, material: str) -> Written | None:
    """The message and outcome keys the code can stand behind, or None: one message of the
    allowed length with no blank, its quote found in the material, no figure and no provider
    name the material lacks; only the campaign's own outcome keys."""
    message, quote, keys = raw.get("message"), raw.get("quote"), raw.get("outcomes")
    if not isinstance(message, str) or not isinstance(quote, str):
        return None
    body = "\n".join(" ".join(line.split()) for line in message.strip().splitlines()).strip()
    if not body or len(body) > cw.MESSAGE_MAX or "{{" in body or "}}" in body:
        return None
    if not quoted_in(" ".join(quote.split())[:_QUOTE_MAX], material):
        return None
    if not figures_in(body) <= figures_in(material):
        return None
    if not provider_words(body) <= provider_words(material):
        return None
    own = {o.key for o in campaign.outcomes}
    chosen = [k for k in keys if isinstance(k, str) and k in own] if isinstance(keys, list) else []
    return Written(message=body, outcomes=list(dict.fromkeys(chosen)))


async def _read(tenant_id: UUID, campaign_id: UUID) -> Campaign | str:
    """The campaign as the pass reads it, or the `FAILURES` code that stops it."""
    from apps.api.kb.picks import CAMPAIGN_PICKS, read_picks

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.name, c.main_task, c.purpose, c.goal, c.classification, "
                    "coalesce(c.settings_overrides->>'language_primary', a.language_primary), "
                    "a.business_outcomes FROM campaigns c JOIN agents a ON a.id = c.agent_id "
                    "WHERE c.id = :cid AND c.archived_at IS NULL"
                ),
                {"cid": campaign_id},
            )
        ).first()
        if row is None:
            return "unavailable"
        picks = await read_picks(session, CAMPAIGN_PICKS, [campaign_id])
    found = find_language(str(row[5] or ""))
    code = found.bcp47.split("-")[0] if found is not None else ""
    if not code or code not in client_template_languages(tenant_id):
        return "language"
    assert found is not None
    if not (row[1] or "").strip() and not (row[2] or "").strip():
        return "no_material"
    return Campaign(
        id=campaign_id,
        name=str(row[0]),
        main_task=str(row[1] or ""),
        aims="\n".join(str(a) for a in (row[2], row[3]) if a),
        classification=str(row[4]),
        language=code,
        language_label=LANGUAGE_LABELS.get(found.bcp47, found.english_name),
        outcomes=tuple(outcomes_in_use(row[6])[0]),
        source_ids=tuple(picks[campaign_id]),
    )


async def _finish(tenant_id: UUID, campaign_id: UUID, state: str, error: str | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET whatsapp_follow_up_error = :e WHERE id = :cid"),
            {"e": error, "cid": campaign_id},
        )
        await agent_pass.finish(
            session, cw.SLOT, tenant_id=tenant_id, row_id=campaign_id, state=state
        )


async def write_campaign_whatsapp_follow_up(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    campaign_id = UUID(str(payload["campaign_id"]))
    async with tenant_session(tenant_id) as session:
        claimed, _previous = await agent_pass.claim(session, cw.SLOT, row_id=campaign_id)
    if not claimed:
        return "not_queued"
    try:
        return await _run(tenant_id, campaign_id)
    except Exception:
        log.exception(
            "campaign_whatsapp_follow_up_crashed", extra={"campaign_id": str(campaign_id)}
        )
        await _finish(tenant_id, campaign_id, "failed", "unavailable")
        return "failed"


async def _run(tenant_id: UUID, campaign_id: UUID) -> str:
    campaign = await _read(tenant_id, campaign_id)
    if isinstance(campaign, str):
        await _finish(tenant_id, campaign_id, "failed", campaign)
        return campaign
    async with tenant_session(tenant_id) as session:
        words = await knowledge_words(session, only=campaign.source_ids or None)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    business, _vertical = await business_context(tenant_id, include_type=False)
    documents = documents_block(words, budget=KNOWLEDGE_DOCUMENT_CHARS)
    request, material = request_text(campaign, business=business, documents=documents)

    def parse(raw: dict[str, Any]) -> Written | None:
        return accepted(raw, campaign=campaign, material=material)

    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    try:
        answer: JsonAnswer[Written] = await ask_json(
            request,
            ASK.format(language=campaign.language_label, limit=cw.MESSAGE_MAX),
            parse=parse,
            azure_format=_FORMAT,
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling or quota.platform_paused,
            max_tokens=MAX_TOKENS,
            temperature=0.3,
            timeout_s=PROPOSAL_REQUEST_TIMEOUT_S,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as session:
            await crm_assist.meter_refusal(
                session, tenant_id=tenant_id, refusal=refused, feature=feature
            )
        log.info("campaign_whatsapp_follow_up_refused", extra={"reason": refused.code})
        code = "unavailable" if refused.kind == "transient" else "not_written"
        await _finish(tenant_id, campaign_id, "failed", code)
        return refused.code
    async with tenant_session(tenant_id) as session:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            model=answer.model,
            feature=feature,
        )
        await session.execute(
            text("SELECT 1 FROM campaigns WHERE id = :cid FOR UPDATE"), {"cid": campaign_id}
        )
        result = await cw.install(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            name=campaign.name,
            body=answer.value.message,
            language=campaign.language,
            category=cw.template_category(campaign.classification),
            outcomes=answer.value.outcomes,
            user_id=None,
        )
        # The inputs hash records what the message was written from, so a support question
        # ("was it written before the main task changed?") has an answer.
        await session.execute(
            text(
                "UPDATE campaigns SET whatsapp_follow_up_error = :e, "
                "whatsapp_follow_up_inputs = :d WHERE id = :cid"
            ),
            {
                "e": None if result == "made" else result,
                "d": hashlib.sha256(request.encode()).hexdigest(),
                "cid": campaign_id,
            },
        )
        await agent_pass.finish(
            session,
            cw.SLOT,
            tenant_id=tenant_id,
            row_id=campaign_id,
            state="done" if result == "made" else "failed",
        )
    log.info(
        "campaign_whatsapp_follow_up_written",
        extra={
            "campaign_id": str(campaign_id),
            "outcomes": len(answer.value.outcomes),
            "result": result,
        },
    )
    return result


__all__ = [
    "ASK",
    "JOB_NAME",
    "Campaign",
    "Written",
    "accepted",
    "request_text",
    "write_campaign_whatsapp_follow_up",
]
