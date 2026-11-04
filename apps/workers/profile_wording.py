"""Write the business profile's own words for ONE business, from what it says about itself.

The profile's steps are the same for every business; what it offers, whether a price
applies, how a caller goes ahead and every example inside an empty field are not
(`tenancy/profile_wording`). This asks the model for them.

Queued by `tenancy/profile_wording.maybe_write_profile_wording` when the owner's brief or
what the business sells changes, and by `read_wording` when the profile is read with no
draft for the current description. One request on the dashboard AI ladder
(`script_assist.ask_json`), no retry: a refusal leaves the neutral wording showing, and the
next change asks again. What the model sees is the business's own redacted words about
itself (`lead_fields_draft.business_context`), never a caller, and nothing of it is logged.
Metered at our cost under `ASSIST_FEATURE_LEAD_FIELDS` and absorbed, like the job steps and
detail names written from the same description.

Stored only while the description is the one it was written from: a slower answer about an
older description never overwrites a newer one.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.starter_plans import business_known
from apps.api.billing.ai_quota import new_assist_ref
from apps.api.billing.models import ASSIST_FEATURE_LEAD_FIELDS
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.tenancy.profile_wording import (
    EXAMPLE_CAPS,
    HINT_MAX,
    LABEL_MAX,
    TITLE_MAX,
    ProfileWording,
    clean_wording,
    wording_to_json,
)
from apps.workers.lead_fields_draft import business_context
from apps.workers.script_assist import JsonAnswer, ask_json

log = get_logger(__name__)

#: The ARQ name; `tenancy/profile_wording.WRITE_JOB` is the enqueue side's spelling.
JOB_NAME: Final = "write_profile_wording"

WRITE_TIMEOUT_S: Final = 40.0
WRITE_MAX_TOKENS: Final = 2048

#: What each example is, for the instruction.
EXAMPLE_MEANINGS: Final[dict[str, str]] = {
    "branch_label": "the name of one place callers can visit, or empty if it has none",
    "offer_name": "one thing it offers, as the owner would list it",
    "offer_price": "a typical price for it in whole rupees, digits only, or empty",
    "offer_note": "a short note beside it",
    "faq_question": "a question its callers ask that the list of what it offers does not answer",
    "staff_name": "a name of the kind its callers might ask for",
    "staff_spoken": "how to say that name aloud, in capitalised syllables",
    "staff_role": "that person's role in this business",
    "booking_rules": "two short sentences on how a caller goes ahead and what never to promise",
    "contact_name": "who a caller is put through to, as a desk or role",
}

#: Pinned by `tests/profile_wording_test.py`.
SYSTEM_PROMPT: Final = (
    "A small Indian business is filling in the profile its AI phone agent answers from. "
    "The form is the same for every kind of business; write ITS words for this one, from "
    "what it says about itself, so the owner recognises their own business. "
    f"offer_label: what one thing it offers is called, singular, 1 to 3 words, at most "
    f"{LABEL_MAX} characters (Service, Plan, Course, Product, Room). "
    "price_label: what its price is called (Price, Fee, Monthly fee, Rent), or an empty "
    "string when it does not quote prices on the phone or nothing it offers has one. "
    f"offers_hint: one line, at most {HINT_MAX} characters, saying what to list. "
    f"booking_title: a short question, at most {TITLE_MAX} characters, asking how a caller "
    "goes ahead with this business (books, orders, signs up, visits, applies). "
    f"booking_hint: one line, at most {HINT_MAX} characters, on what to write there. "
    "examples: the greyed-out example inside each empty field; "
    + "; ".join(f"{key}: {meaning}" for key, meaning in EXAMPLE_MEANINGS.items())
    + ". Keep each example under "
    f"{EXAMPLE_CAPS['offer_name']} characters, booking_rules under "
    f"{EXAMPLE_CAPS['booking_rules']}. "
    "Labels, the heading and the hints are plain English, because the dashboard is in "
    "English; examples are in the language the owner describes the business in. "
    "Use only what the business says about itself and what plainly fits it: never borrow "
    "another kind of business's products or words, never invent an offer, discount or "
    "guarantee, and never copy a person's name, phone number or address, or anything "
    "marked [redacted], from the description. "
    "Plain text only: no markdown, bullets, emoji or symbols, and never name a technology "
    "or AI company. Return ONLY the JSON object."
)


def _schema() -> dict[str, Any]:
    string = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "offer_label": string,
            "price_label": string,
            "offers_hint": string,
            "booking_title": string,
            "booking_hint": string,
            "examples": {
                "type": "object",
                "properties": dict.fromkeys(EXAMPLE_MEANINGS, string),
                "required": list(EXAMPLE_MEANINGS),
                "additionalProperties": False,
            },
        },
        "required": [
            "offer_label",
            "price_label",
            "offers_hint",
            "booking_title",
            "booking_hint",
            "examples",
        ],
        "additionalProperties": False,
    }


async def _store(tenant_id: UUID, known: str, answer: JsonAnswer[ProfileWording]) -> bool:
    """Store the wording and meter the answer in ONE transaction, only while what describes
    the business is still what it was written from (`starter_plans.business_known`)."""
    async with tenant_session(tenant_id) as session:
        current = await business_known(session, tenant_id=tenant_id)
        stored = None
        if current == known:
            stored = (
                await session.execute(
                    text(
                        "UPDATE organizations SET profile_wording = CAST(:wording AS jsonb) "
                        "WHERE id = :tid RETURNING id"
                    ),
                    {"tid": tenant_id, "wording": wording_to_json(known, answer.value)},
                )
            ).first()
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=ASSIST_FEATURE_LEAD_FIELDS
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            feature=ASSIST_FEATURE_LEAD_FIELDS,
            model=answer.model,
        )
    return stored is not None


async def write_profile_wording(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Ask the model once for the profile's wording, store what came back."""
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    known = str(payload.get("known", ""))
    if not known:
        return "superseded"
    try:
        description, vertical = await business_context(tenant_id)
        clinic = vertical == "clinic"
        async with tenant_session(tenant_id) as session:
            tenant_leg = await account_assist_leg(session)
        try:
            answer = await ask_json(
                description,
                SYSTEM_PROMPT,
                parse=lambda raw: clean_wording(raw, clinic=clinic),
                azure_format={
                    "type": "json_schema",
                    "json_schema": {"name": "profile_wording", "strict": True, "schema": _schema()},
                },
                tenant_leg=tenant_leg,
                max_tokens=WRITE_MAX_TOKENS,
                temperature=0.3,
                timeout_s=WRITE_TIMEOUT_S,
                health_leg="lead_fields",
            )
        except ProblemError as refused:
            async with tenant_session(tenant_id) as session:
                await crm_assist.meter_refusal(
                    session,
                    tenant_id=tenant_id,
                    refusal=refused,
                    feature=ASSIST_FEATURE_LEAD_FIELDS,
                )
            log.info(
                "profile_wording_refused",
                extra={"tenant_id": str(tenant_id), "reason": refused.code},
            )
            return "refused"
        stored = await _store(tenant_id, known, answer)
    except Exception:
        log.exception("profile_wording_crashed", extra={"tenant_id": str(tenant_id)})
        return "failed"
    log.info("profile_wording_written", extra={"tenant_id": str(tenant_id), "stored": stored})
    return "written" if stored else "superseded"


__all__ = ["JOB_NAME", "SYSTEM_PROMPT", "write_profile_wording"]
