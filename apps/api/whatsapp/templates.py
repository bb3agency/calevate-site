"""WhatsApp message templates in a client's own account: Calevate's standard ones and the
client's own (D-784).

Every in-call WhatsApp is a template, because we cannot see the client's 24-hour window
(`actions/whatsapp.py`). On connect, Calevate submits four UTILITY templates in Telugu, Hindi
and English to the client's account; the client may add their own. Meta reviews each one
("can take up to 24 hours", templates/template-review.md, read 15 Oct 2026) and reports the
outcome on the `message_template_status_update` webhook, which `apply_status_update` records.

Template rules checked here before Meta sees them, each from Meta's pages read 15 Oct 2026:
names are "lowercase alphanumeric characters and underscores" up to 512 characters
(templates/overview.md); a body is at most 1024 characters (templates/components.md); a
template "cannot start or end with a parameter" and may be rejected for "too many variable
parameters relative to the message length" (templates/template-review.md). UTILITY must be
"non-promotional" and tied to the person's order, account or transaction
(templates/template-categorization.md).

The Telugu and Hindi wording below is ours and has not been read by a native speaker
(OPERATIONS gate W-7); Meta reviews only policy, not fluency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.whatsapp import graph
from apps.api.whatsapp.models import TEMPLATE_CATEGORIES

log = get_logger(__name__)

#: The languages Calevate's own templates are submitted in, as Meta codes them
#: (templates/supported-languages.md: Telugu `te`, Hindi `hi`, English `en`).
STANDARD_LANGUAGES: Final = ("te", "hi", "en")
#: Languages a client may write a template in. Meta supports many more; these are the ones
#: our agents speak (`agents/languages.OFFERED_LANGUAGE_IDS`).
CLIENT_LANGUAGES: Final = ("te", "hi", "en", "en_US", "en_GB", "en_IN")
#: How many blanks one template may have. Meta states no number; ten keeps a voice agent's
#: message short and well inside "too many variable parameters relative to the length".
MAX_VARIABLES: Final = 10
MAX_TEMPLATES_PER_ACCOUNT: Final = 100

_NAME_RE: Final = re.compile(r"^[a-z0-9_]{1,512}$")
_BLANK_RE: Final = re.compile(r"\{\{\s*(\d+)\s*\}\}")
#: A numbered blank missing a bracket on either side, once the well-formed ones are removed.
_HALF_BLANK_RE: Final = re.compile(r"\{\s*\d+\s*\}|\{\{\s*\d+|\d+\s*\}\}")


@dataclass(frozen=True, slots=True)
class StandardTemplate:
    purpose: str
    name: str
    #: One label per blank, in order: what the client binds to it on an action.
    variables: tuple[str, ...]
    examples: tuple[str, ...]
    bodies: dict[str, str]


#: Calevate's standard UTILITY templates. Every body names the business and, where it can,
#: the business's own number to call: Meta's policy asks automated messaging to offer an
#: escalation path (whatsappbusiness.com/policy, read 15 Oct 2026).
STANDARD: Final[tuple[StandardTemplate, ...]] = (
    StandardTemplate(
        purpose="booking_confirmed",
        name="calevate_booking_confirmed",
        variables=("Your business name", "Booking date and time", "Your phone number"),
        examples=("Lakshmi Traders", "Friday 18 October, 4 pm", "+91 98765 43210"),
        bodies={
            "en": (
                "Your booking with {{1}} is confirmed for {{2}}. To change it, please call "
                "{{3}}. Thank you."
            ),
            "hi": (
                "नमस्ते, {{1}} के साथ आपकी बुकिंग {{2}} के लिए पक्की हो गई है। बदलाव के लिए "
                "कृपया {{3}} पर कॉल करें। धन्यवाद।"
            ),
            "te": (
                "నమస్కారం, {{1}} తో మీ బుకింగ్ {{2}} కి ఖరారైంది. మార్చుకోవాలంటే దయచేసి {{3}} కి కాల్ చేయండి. ధన్యవాదాలు."
            ),
        },
    ),
    StandardTemplate(
        purpose="details_requested",
        name="calevate_details_you_asked_for",
        variables=("Your business name", "The details", "Your phone number"),
        examples=("Lakshmi Traders", "Open 9 am to 7 pm, Monday to Saturday", "+91 98765 43210"),
        bodies={
            "en": (
                "As you asked on your call with {{1}}, here are the details: {{2}}. For "
                "anything else, please call {{3}}. Thank you."
            ),
            "hi": (
                "नमस्ते, {{1}} के साथ आपकी कॉल पर आपने जो जानकारी माँगी थी, वह यह है: {{2}}। "
                "और कुछ जानना हो तो कृपया {{3}} पर कॉल करें। धन्यवाद।"
            ),
            "te": (
                "నమస్కారం, {{1}} తో మీ కాల్‌లో మీరు అడిగిన వివరాలు ఇవి: {{2}}. ఇంకేమైనా "
                "కావాలంటే దయచేసి {{3}} కి కాల్ చేయండి. ధన్యవాదాలు."
            ),
        },
    ),
    StandardTemplate(
        purpose="payment_link",
        name="calevate_payment_link",
        # The order a payment-link action fills: description, amount, link
        # (`actions/schema.PaymentMessage.body_values`).
        variables=("What the payment is for", "Amount in rupees", "Payment link"),
        examples=("your order", "1500", "https://rzp.io/l/example"),
        bodies={
            "en": (
                "Here is the payment link you asked for, for {{1}}. Amount: Rs {{2}}. Pay "
                "here: {{3}} Thank you."
            ),
            "hi": (
                "नमस्ते, आपने {{1}} के लिए जो भुगतान लिंक माँगा था, वह यह है। राशि: ₹{{2}}। "
                "यहाँ भुगतान करें: {{3}} धन्यवाद।"
            ),
            "te": (
                "నమస్కారం, మీరు {{1}} కోసం అడిగిన చెల్లింపు లింక్ ఇది. మొత్తం: ₹{{2}}. "
                "ఇక్కడ చెల్లించండి: {{3}} ధన్యవాదాలు."
            ),
        },
    ),
    StandardTemplate(
        purpose="callback_time",
        name="calevate_call_back_time",
        variables=("Your business name", "Call-back time", "Your phone number"),
        examples=("Lakshmi Traders", "Friday 18 October, 4 pm", "+91 98765 43210"),
        bodies={
            "en": (
                "This is {{1}}. We will call you back at {{2}}. If that time no longer suits "
                "you, please call {{3}}. Thank you."
            ),
            "hi": (
                "नमस्ते, {{1}} की ओर से हम आपको {{2}} पर वापस कॉल करेंगे। अगर यह समय ठीक न "
                "हो तो कृपया {{3}} पर कॉल करें। धन्यवाद।"
            ),
            "te": (
                "నమస్కారం, {{1}} నుండి మేము మీకు {{2}} కి తిరిగి కాల్ చేస్తాము. ఆ సమయం మీకు "
                "అనుకూలం కాకపోతే దయచేసి {{3}} కి కాల్ చేయండి. ధన్యవాదాలు."
            ),
        },
    ),
)

#: Meta's template status words, folded onto ours. Anything unlisted keeps the row's status
#: and is still recorded as `meta_status`.
META_STATUS: Final[dict[str, str]] = {
    "APPROVED": "approved",
    "REINSTATED": "approved",
    "UNARCHIVED": "approved",
    "FLAGGED": "approved",
    "PENDING": "pending",
    "IN_APPEAL": "pending",
    "REJECTED": "rejected",
    "PAUSED": "paused",
    "DISABLED": "disabled",
    "LOCKED": "disabled",
    "LIMIT_EXCEEDED": "submit_failed",
    "ARCHIVED": "deleted",
    "DELETED": "deleted",
    "PENDING_DELETION": "deleted",
}


def blanks(body: str) -> list[int]:
    return [int(n) for n in _BLANK_RE.findall(body)]


def template_refusal(code: str, detail: str, remediation: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code=code,
        title="This message cannot be sent to Meta yet",
        detail=detail,
        remediation=remediation,
    )


def check_template(
    *, name: str, language: str, category: str, body: str, examples: list[str]
) -> None:
    """Meta's rules a client can fix before review, as sentences they can act on."""
    if not _NAME_RE.match(name):
        raise template_refusal(
            "whatsapp_template_name_shape",
            "A template name uses only small letters, numbers and underscores.",
            "For example: order_ready or price_list.",
        )
    if language not in CLIENT_LANGUAGES:
        raise template_refusal(
            "whatsapp_template_language",
            "Choose Telugu, Hindi or English.",
            "Pick a language from the list.",
        )
    if category not in TEMPLATE_CATEGORIES:
        raise template_refusal(
            "whatsapp_template_category",
            "Choose whether this message is about an order or booking, or is marketing.",
            "Pick Utility or Marketing.",
        )
    stripped = body.strip()
    if not 1 <= len(stripped) <= 1024:
        raise template_refusal(
            "whatsapp_template_length",
            "The message must be between 1 and 1,024 characters.",
            "Shorten the message.",
        )
    # `{1}`, `{{1}` or `{1}}` is not a blank and is not counted as one, so it would pass
    # every check below and come back from review as INVALID_FORMAT ("Malformed braces",
    # thinnest-findings/mirror/snapshots/2026-10-19/pages/meta/template-review.md:57).
    if _HALF_BLANK_RE.search(_BLANK_RE.sub("", stripped)):
        raise template_refusal(
            "whatsapp_template_blank_shape",
            "A blank is written with two curly brackets on each side, like {{1}}.",
            "Fix the blank so it reads {{1}}, {{2}} and so on.",
        )
    numbers = blanks(stripped)
    distinct = sorted(set(numbers))
    if distinct != list(range(1, len(distinct) + 1)):
        raise template_refusal(
            "whatsapp_template_blanks_order",
            "Blanks must be numbered in order: {{1}}, then {{2}}, and so on.",
            "Renumber the blanks so none is skipped.",
        )
    if len(distinct) > MAX_VARIABLES:
        raise template_refusal(
            "whatsapp_template_too_many_blanks",
            f"A message can have at most {MAX_VARIABLES} blanks.",
            "Use fewer blanks and more fixed words.",
        )
    if _BLANK_RE.match(stripped) or re.search(r"\{\{\s*\d+\s*\}\}[\s.!?।]*$", stripped):
        raise template_refusal(
            "whatsapp_template_blank_at_edge",
            "Meta refuses a message that starts or ends with a blank.",
            "Add a word before the first blank and after the last one.",
        )
    if len(examples) != len(distinct) or any(not e.strip() for e in examples):
        raise template_refusal(
            "whatsapp_template_examples",
            "Meta needs an example for every blank.",
            "Give a realistic example for each blank.",
        )


def map_meta_status(word: str | None) -> str | None:
    return META_STATUS.get((word or "").upper())


async def insert_template(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    name: str,
    language: str,
    category: str,
    body: str,
    variables: list[dict[str, str]],
    origin: str,
    purpose: str | None,
) -> UUID | None:
    """One draft row. None when this account already has the name in this language.

    Except a row whose submission to Meta failed: that one becomes the draft again, with
    this content, and its id is returned so the caller submits it. Meta never received it,
    so there is nothing on Meta's side to collide with; refusing the name instead left a
    `submit_failed` template that nobody could send again (the client's create was
    refused as a duplicate, the standard seeding counted it as already there)."""
    row = (
        await session.execute(
            text(
                "INSERT INTO whatsapp_templates (id, tenant_id, account_id, name, language, "
                "category, body, variables, origin, purpose, status, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :name, :lang, :cat, :body, CAST(:vars AS jsonb), "
                ":origin, :purpose, 'draft', now(), now()) "
                "ON CONFLICT (account_id, name, language) DO UPDATE SET "
                "category = EXCLUDED.category, body = EXCLUDED.body, "
                "variables = EXCLUDED.variables, status = 'draft', rejection_code = NULL, "
                "updated_at = now() WHERE whatsapp_templates.status = 'submit_failed' "
                "RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": account_id,
                "name": name,
                "lang": language,
                "cat": category,
                "body": body,
                "vars": graph.dumps(variables),
                "origin": origin,
                "purpose": purpose,
            },
        )
    ).first()
    return UUID(str(row[0])) if row is not None else None


async def submit(session: AsyncSession, *, template_id: UUID, waba_id: str, token: str) -> str:
    """Send one stored draft to Meta and record what Meta said. Returns our status."""
    row = (
        await session.execute(
            text(
                "SELECT name, language, category, body, variables FROM whatsapp_templates "
                "WHERE id = :id"
            ),
            {"id": template_id},
        )
    ).one()
    variables: list[dict[str, Any]] = list(row[4] or [])
    examples = [str(v.get("example") or "") for v in variables]
    try:
        meta_id, meta_status = await graph.create_template(
            waba_id=waba_id,
            token=token,
            name=str(row[0]),
            language=str(row[1]),
            category=str(row[2]),
            body=str(row[3]),
            examples=examples,
        )
    except graph.GraphError as exc:
        await session.execute(
            text(
                "UPDATE whatsapp_templates SET status = 'submit_failed', rejection_code = :code, "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": template_id, "code": f"meta_{exc.meta_code}" if exc.meta_code else exc.code},
        )
        return "submit_failed"
    status = map_meta_status(meta_status) or "pending"
    await session.execute(
        text(
            "UPDATE whatsapp_templates SET status = :status, meta_status = :meta, "
            "meta_template_id = :mid, submitted_at = now(), rejection_code = NULL, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": template_id, "status": status, "meta": meta_status, "mid": meta_id},
    )
    return status


async def seed_standard(
    session: AsyncSession, *, tenant_id: UUID, account_id: UUID, waba_id: str, token: str
) -> dict[str, int]:
    """Store and submit every standard template not already on this account."""
    counts = {"submitted": 0, "failed": 0, "already": 0}
    for template in STANDARD:
        for language in STANDARD_LANGUAGES:
            new_id = await insert_template(
                session,
                tenant_id=tenant_id,
                account_id=account_id,
                name=template.name,
                language=language,
                category="UTILITY",
                body=template.bodies[language],
                variables=[
                    {"label": label, "example": example}
                    for label, example in zip(template.variables, template.examples, strict=True)
                ],
                origin="calevate",
                purpose=template.purpose,
            )
            if new_id is None:
                counts["already"] += 1
                continue
            outcome = await submit(session, template_id=new_id, waba_id=waba_id, token=token)
            counts["failed" if outcome == "submit_failed" else "submitted"] += 1
    if counts["failed"]:
        # Left unstamped, so the account's next setup step (`accounts.finish_setup`) seeds
        # again, and `insert_template` hands the failed rows back for another submission.
        return counts
    await session.execute(
        text("UPDATE whatsapp_accounts SET templates_seeded_at = now() WHERE id = :id"),
        {"id": account_id},
    )
    return counts


@dataclass(frozen=True, slots=True)
class StatusUpdate:
    meta_template_id: str | None
    name: str | None
    language: str | None
    event: str
    reason: str | None
    new_category: str | None = None


async def apply_status_update(
    session: AsyncSession, *, account_id: UUID, update: StatusUpdate
) -> str | None:
    """Record Meta's verdict on one template. Returns our new status, or None if unknown."""
    ours = map_meta_status(update.event)
    params: dict[str, Any] = {
        "aid": account_id,
        "mid": update.meta_template_id,
        "name": update.name,
        "lang": update.language,
        "meta": update.event[:32],
        "status": ours,
        "reason": (update.reason or "")[:128] or None,
        "cat": (update.new_category or "")[:32] or None,
        "at": datetime.now(UTC),
    }
    result = await session.execute(
        text(
            "UPDATE whatsapp_templates SET meta_status = :meta, "
            "status = COALESCE(CAST(:status AS text), status), "
            "rejection_code = CASE WHEN CAST(:status AS text) = 'rejected' "
            "THEN CAST(:reason AS text) ELSE rejection_code END, "
            "category_changed_to = COALESCE(CAST(:cat AS text), category_changed_to), "
            "decided_at = CASE WHEN CAST(:status AS text) IS NULL THEN decided_at "
            "ELSE CAST(:at AS timestamptz) END, "
            "updated_at = now() "
            "WHERE account_id = :aid AND ((CAST(:mid AS text) IS NOT NULL "
            "AND meta_template_id = CAST(:mid AS text)) "
            "OR (name = :name AND language = :lang)) RETURNING status"
        ),
        params,
    )
    row = result.first()
    return str(row[0]) if row is not None else None


__all__ = [
    "CLIENT_LANGUAGES",
    "MAX_TEMPLATES_PER_ACCOUNT",
    "MAX_VARIABLES",
    "META_STATUS",
    "STANDARD",
    "STANDARD_LANGUAGES",
    "StandardTemplate",
    "StatusUpdate",
    "apply_status_update",
    "blanks",
    "check_template",
    "insert_template",
    "map_meta_status",
    "seed_standard",
    "submit",
]
