"""WhatsApp BSP adapters — turn a resolved WhatsApp action into ONE outbound HTTP request.

Three dedicated providers plus a custom fallback, per the founder's spec. Each builds the
provider's own send-a-template request from a saved credential and the values our executor
resolved (recipient, header var, ordered body vars). None of them SENDS anything — they
return a `PreparedRequest` the executor puts on the wire through the egress guard, so the
credential handling, SSRF vetting and audit stay in one place.

WHY THE GATE IS HERE AND NOT AT THE EDGE. A WhatsApp send from our WABA to a caller is
business-initiated messaging to a person, so it needs the caller's messaging consent
(`compliance/consent.read_messaging_consent`, the consumer `messaging` purpose — NOT the
client's own alert opt-in, which is a different regime). It lives on this path so no
provider branch can forget it.

**AND IT IS `check_dispatch` FIRST, THEN THE OPT-IN — THE SAME TWO QUESTIONS IN THE SAME
ORDER AS `workers/whatsapp._send_escalation`.** This path used to ask only the second one,
and the divergence had a concrete victim: a person on the tenant's DNC list who had once
granted messaging consent was refused by the campaign escalation and messaged by the
in-call action. One outbound channel cannot have two answers to "may we contact this
person" (hard rule 5: `check_dispatch` is the ONE gate every outbound path calls), and the
disagreement was not a considered split — the campaign leg simply had the gate and this
leg did not.

WhatsApp is Meta-BSP, not DLT/TCCCPR (LEGAL-OPS-PLAYBOOK §11), and the gate no longer
asks any TCCCPR-only check (D-692, D-762), so it runs the same rules as a voice dial: the
live DNC read above all, the India-only destination, the big red switch, the tenant cap.

EVIDENCE CLASS, each read on the vendor's own page on 9 Oct 2026 (VERIFIED-VENDOR-DOCS):

* Meta Cloud API: `POST https://graph.facebook.com/{version}/{phone-number-id}/messages`,
  `Authorization: Bearer <system user token>`, a template message `{messaging_product,
  recipient_type, to, type: "template", template: {name, language: {code}, components}}`;
  the reference examples use v25.0 (developers.facebook.com/documentation/business-messaging/
  whatsapp/messages/send-messages.md, …/templates/overview.md). Outside the 24-hour customer
  service window "you can only send pre-approved template messages" (send-messages.md), so
  every send here is a template: we cannot see the client's inbox and so cannot know the
  window is open. A HEADER TEXT parameter is shaped like a body one; no Meta page we read
  shows a text header in a send request (OPERATIONS gate A-5).
* AiSensy: `POST https://backend.aisensy.com/campaign/t1/api/v2` with `apiKey`,
  `campaignName` (a Live campaign), `destination` (with the country code), `userName`,
  `templateParams` (its length must match the template's) — aisensy.com/tutorials/
  api-reference-docs. The answer body is not documented; a 2xx is the only signal read.
  `userName` is "Required" and is the "Name of the user to whom the campaign has to be
  sent"; no neutral value is documented (same page, read 15 Oct 2026). AiSensy files the
  recipient under it as a contact, so it is the caller's name when the agent captured one,
  else their number — never our name.

THE IN-CALL OPT-IN (D-784). A caller with no messaging consent on file is refused, and on a
call that used to mean almost every caller. The WhatsApp action now carries the caller's
answer to the agent's question "Shall I send this on WhatsApp to this number?"
(`SpokenConsent`): a yes is appended to `consent_ledger` as `in_call_agent_question` with the
call it was spoken on and the caller's words, a no is appended as `declined`, and no answer
is refused so the agent asks. The answer is reported by the model, so the post-call pipeline
checks the caller's words against the transcript and raises
`whatsapp_spoken_consent_unconfirmed` when they are not there
(`compliance/spoken_consent.py`).
* Interakt: `POST https://api.interakt.ai/v1/public/message/`, `Authorization: Basic <key>`,
  `{countryCode, phoneNumber (no country code), type: "Template", template: {name,
  languageCode, headerValues, bodyValues}}`; "Growth Plan - 300 requests per minute",
  "Advanced Plan - 600 requests per minute", Enterprise configurable, no API on Starter —
  interakt.shop/resource-center/how-to-send-whatsapp-templates-using-apis-webhooks (read
  15 Oct 2026).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions.schema import (
    CALLER_AGREED_ARG,
    CALLER_WORDS_ARG,
    SPOKEN_CONSENT_ARGS,
    PreparedRequest,
    WhatsAppConfig,
)
from apps.api.compliance.consent import read_messaging_consent, record_messaging_consent
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.ingest.service import normalize_phone
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The question the agent asks, in the call's language. Recorded with every in-call opt-in.
SPOKEN_QUESTION: Final = "Shall I send this on WhatsApp to this number?"
SPOKEN_CONSENT_SOURCE: Final = "in_call_agent_question"
#: How much of the caller's reply is kept as evidence: a short answer, never a transcript.
MAX_CALLER_WORDS: Final = 120

_YES: Final = frozenset({"yes", "y", "true", "1", "agreed"})
_NO: Final = frozenset({"no", "n", "false", "0", "declined"})

SpokenAnswer = Literal["yes", "no", "unknown"]


@dataclass(frozen=True, slots=True)
class SpokenConsent:
    """The caller's answer to `SPOKEN_QUESTION` on this call, as the agent reported it."""

    answer: SpokenAnswer
    #: Their reply, redacted and clipped. Empty means the agent passed none.
    words: str
    #: Our `calls.id` for the call it was spoken on; a grant cannot be recorded without it.
    call_id: UUID | None
    call_ref: str | None
    action_id: UUID


def spoken_answer(raw: Any) -> SpokenAnswer:
    word = str(raw or "").strip().lower()
    if word in _YES:
        return "yes"
    if word in _NO:
        return "no"
    return "unknown"


def spoken_consent_from_args(
    args: dict[str, Any], *, call_id: UUID | None, call_ref: str | None, action_id: UUID
) -> SpokenConsent:
    words = re.sub(r"\s+", " ", str(args.get(CALLER_WORDS_ARG) or "")).strip()
    return SpokenConsent(
        answer=spoken_answer(args.get(CALLER_AGREED_ARG)),
        words=redact(words).text[:MAX_CALLER_WORDS] if words else "",
        call_id=call_id,
        call_ref=call_ref,
        action_id=action_id,
    )


#: The Graph API version of the Cloud API reference examples (send-messages.md, read
#: 9 Oct 2026). Graph v26.0 exists (developers.facebook.com/docs/graph-api/changelog); the
#: messaging reference has not moved to it, so neither do we.
META_GRAPH_VERSION = "v25.0"


class WhatsAppBlockedError(ProblemError):
    """`check_dispatch` refused this recipient. The RULE, never the client-facing prose
    of the decision and never the number — the reason code is what the executor records
    and what an operator greps for."""

    def __init__(self, rule: str) -> None:
        super().__init__(
            kind="business_rule",
            code=f"whatsapp_blocked_{rule}",
            title="This number may not be contacted",
            detail="Sending a message to this number is blocked by a compliance rule.",
            remediation=(
                "Check this number on the do-not-call screen and check the account's "
                "outbound status before trying again."
            ),
        )


class WhatsAppNotOptedInError(ProblemError):
    """The caller has not consented to messaging. A refusal the agent can act on (fall back
    to reading the info aloud) rather than a silent drop."""

    def __init__(self) -> None:
        super().__init__(
            kind="business_rule",
            code="whatsapp_recipient_not_opted_in",
            title="This number has not opted in to WhatsApp",
            detail="We do not have messaging consent on file for this caller.",
            remediation="Ask the caller for consent and record it before sending.",
        )


class WhatsAppConsentNotAskedError(ProblemError):
    """No consent on file and the agent did not pass the caller's answer: ask first."""

    def __init__(self) -> None:
        super().__init__(
            kind="business_rule",
            code="whatsapp_consent_not_asked",
            title="The caller has not been asked",
            detail="Nothing was sent: the caller was not asked before sending.",
            remediation="Ask the caller and send their answer.",
        )


class WhatsAppCallerDeclinedError(ProblemError):
    """The caller said no to the agent's question on this call."""

    def __init__(self) -> None:
        super().__init__(
            kind="business_rule",
            code="whatsapp_caller_declined",
            title="The caller said no",
            detail="Nothing was sent: the caller did not want it on WhatsApp.",
        )


async def _record_spoken(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    phone_e164: str,
    spoken: SpokenConsent,
    status: str,
) -> None:
    await record_messaging_consent(
        session,
        tenant_id=tenant_id,
        raw_phone=phone_e164,
        status=status,
        source=SPOKEN_CONSENT_SOURCE,
        call_id=spoken.call_id,
        evidence={
            "question": SPOKEN_QUESTION,
            "asked_by": "voice_agent",
            "answer_reported_by": "agent_model",
            "caller_words": spoken.words,
            "engine_call_ref": spoken.call_ref or "",
            "action_id": str(spoken.action_id),
            "transcript_check": "pending",
        },
    )
    log.info(
        "whatsapp_spoken_consent_recorded",
        extra={"tenant_id": str(tenant_id), "status": status, "action_id": str(spoken.action_id)},
    )


async def assert_recipient_may_be_messaged(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    recipient_e164: str,
    spoken: SpokenConsent | None = None,
) -> str:
    """The gate, then the opt-in — the order and the arguments `_send_escalation` uses.

    Returns the normalized E.164 both were asked about, and the send must be addressed to
    THAT string: the raw value is model- or engine-supplied (`98765 43210`, `09876543210`),
    and a message addressed to it is not the number the gate and the consent cleared.

    Raises `WhatsAppBlockedError` when the dispatch gate refuses (DNC above all) and
    `WhatsAppNotOptedInError` when there is no current messaging consent. Two exceptions
    rather than one because they are two different next actions for the client: a
    suppression is theirs to look up, a missing opt-in is theirs to ask for.
    """
    phone_e164 = normalize_phone(recipient_e164)
    if phone_e164 is None:
        # An unusable number has no DNC key and no consent key. Refusing it as
        # "not opted in" is the truthful answer and the safe direction.
        raise WhatsAppNotOptedInError()
    decision = await check_dispatch(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        phone_e164=phone_e164,
    )
    if not decision.allowed:
        # Ids and the RULE only — never the number (hard rule 6).
        log.info(
            "whatsapp_send_blocked",
            extra={"tenant_id": str(tenant_id), "rule": decision.rule or "unknown"},
        )
        raise WhatsAppBlockedError(decision.rule or "unknown")
    consent = await read_messaging_consent(session, tenant_id=tenant_id, raw_phone=phone_e164)
    if spoken is not None:
        await _apply_spoken(
            session,
            tenant_id=tenant_id,
            phone_e164=phone_e164,
            spoken=spoken,
            on_file=consent.messageable,
        )
        return phone_e164
    if not consent.messageable:
        log.info(
            "whatsapp_send_blocked_no_consent",
            extra={"tenant_id": str(tenant_id), "reason": "not_opted_in"},
        )
        raise WhatsAppNotOptedInError()
    return phone_e164


async def _apply_spoken(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    phone_e164: str,
    spoken: SpokenConsent,
    on_file: bool,
) -> None:
    """The caller's answer on this call, after the dispatch gate has passed.

    A no stops this send. It is recorded as `declined` only when no consent is on file: a
    caller who opted in elsewhere and says "not now" has declined this message, not
    withdrawn their opt-in. A yes with no consent on file is recorded, then the send goes
    ahead; a yes with no words or no call to name is treated as not asked, because a grant
    that cannot say what it rests on is not one (`consent._assert_grant_is_evidenced`).
    """
    if spoken.answer == "no":
        if not on_file and spoken.call_id is not None:
            await _record_spoken(
                session,
                tenant_id=tenant_id,
                phone_e164=phone_e164,
                spoken=spoken,
                status="declined",
            )
        raise WhatsAppCallerDeclinedError()
    if on_file:
        return
    if spoken.answer != "yes" or not spoken.words or spoken.call_id is None:
        log.info(
            "whatsapp_send_blocked_no_consent",
            extra={"tenant_id": str(tenant_id), "reason": "not_asked"},
        )
        raise WhatsAppConsentNotAskedError()
    await _record_spoken(
        session, tenant_id=tenant_id, phone_e164=phone_e164, spoken=spoken, status="granted"
    )


async def assert_business_contact_may_be_messaged(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, recipient_e164: str
) -> str:
    """The Test button's gate: "send a test WhatsApp to my number".

    The recipient must be one of the account's OWN business contacts (the numbers the
    client recorded for their business, `business_contacts`), so a test cannot message a
    stranger. The messaging-consent ledger is about the client's CUSTOMERS and is not asked:
    the person pressing Test is messaging their own business number. The dispatch gate
    (DNC above all) still is.
    """
    phone_e164 = normalize_phone(recipient_e164)
    if phone_e164 is None:
        raise WhatsAppNotOptedInError()
    own = (
        await session.execute(
            text("SELECT 1 FROM business_contacts WHERE phone_e164 = :p"), {"p": phone_e164}
        )
    ).first()
    if own is None:
        log.info("whatsapp_test_not_business_contact", extra={"tenant_id": str(tenant_id)})
        raise WhatsAppNotOptedInError()
    decision = await check_dispatch(
        session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone_e164
    )
    if not decision.allowed:
        raise WhatsAppBlockedError(decision.rule or "unknown")
    return phone_e164


def _digits(e164: str) -> str:
    return e164.lstrip("+")


def build_aisensy(
    config: WhatsAppConfig,
    *,
    api_key: str,
    recipient_e164: str,
    body_values: list[str],
    recipient_name: str | None = None,
) -> PreparedRequest:
    """AiSensy API campaign send. `template` is the CAMPAIGN name (which is the template
    reference on AiSensy), and the api key rides in the BODY, not a header.

    AiSensy has no separate header variable (module docstring for the wire shape).
    """
    if config.header_param is not None:
        raise ProblemError.business_rule(
            "aisensy_no_header_var",
            "AiSensy campaigns have no separate header variable.",
            remediation="Remove the header variable, or use Meta Cloud / Interakt.",
        )
    return PreparedRequest(
        method="POST",
        url="https://backend.aisensy.com/campaign/t1/api/v2",
        headers={"Content-Type": "application/json"},
        json_body={
            "apiKey": api_key,
            "campaignName": config.template,
            "destination": recipient_e164,
            "userName": (recipient_name or "").strip() or recipient_e164,
            "templateParams": body_values,
        },
    )


def build_meta_cloud(
    config: WhatsAppConfig,
    *,
    access_token: str,
    recipient_e164: str,
    header_value: str | None,
    body_values: list[str],
    connected_number_id: str | None = None,
) -> PreparedRequest:
    """Meta Cloud API template send.

    The number sends from the action's own phone number id, else the one an Embedded Signup
    connection carries (`connected_number_id`, the credential's `phone_number_id`, D-784).

    A `template` message carrying `language.code` and `components`: an optional header
    component, then a body component of text parameters in order (module docstring).
    """
    number_id = config.phone_number_id or connected_number_id
    if not number_id or not number_id.isdigit():
        raise ProblemError.business_rule(
            "meta_cloud_needs_phone_number_id",
            "Meta Cloud API needs the WhatsApp Phone Number ID.",
            remediation="Add the Phone Number ID from WhatsApp Manager → API Setup.",
        )
    components: list[dict[str, object]] = []
    if header_value is not None:
        components.append(
            {"type": "header", "parameters": [{"type": "text", "text": header_value}]}
        )
    if body_values:
        components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": v} for v in body_values],
            }
        )
    template: dict[str, object] = {
        "name": config.template,
        "language": {"code": config.language or "en"},
    }
    if components:
        template["components"] = components
    return PreparedRequest(
        method="POST",
        url=f"https://graph.facebook.com/{META_GRAPH_VERSION}/{number_id}/messages",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json_body={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _digits(recipient_e164),
            "type": "template",
            "template": template,
        },
    )


def build_interakt(
    config: WhatsAppConfig,
    *,
    api_key: str,
    recipient_e164: str,
    header_value: str | None,
    body_values: list[str],
) -> PreparedRequest:
    """Interakt Send WhatsApp Template.

    The api key is used verbatim as the Basic credential (Interakt issues it already
    base64-encoded); the wire shape is in the module docstring.
    """
    country_code = config.country_code or "+91"
    number = _digits(recipient_e164)
    cc_digits = _digits(country_code)
    phone_number = number[len(cc_digits) :] if number.startswith(cc_digits) else number
    template: dict[str, object] = {
        "name": config.template,
        "languageCode": config.language or "en",
        "bodyValues": body_values,
    }
    if header_value is not None:
        template["headerValues"] = [header_value]
    return PreparedRequest(
        method="POST",
        url="https://api.interakt.ai/v1/public/message/",
        headers={
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
        },
        json_body={
            "countryCode": country_code,
            "phoneNumber": phone_number,
            "type": "Template",
            "template": template,
        },
    )


__all__ = [
    "CALLER_AGREED_ARG",
    "CALLER_WORDS_ARG",
    "SPOKEN_CONSENT_ARGS",
    "SPOKEN_CONSENT_SOURCE",
    "SPOKEN_QUESTION",
    "SpokenConsent",
    "WhatsAppBlockedError",
    "WhatsAppCallerDeclinedError",
    "WhatsAppConsentNotAskedError",
    "WhatsAppNotOptedInError",
    "assert_business_contact_may_be_messaged",
    "assert_recipient_may_be_messaged",
    "build_aisensy",
    "build_interakt",
    "build_meta_cloud",
    "spoken_answer",
    "spoken_consent_from_args",
]
