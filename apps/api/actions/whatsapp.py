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

`dlt_governed=False`, exactly as the escalation passes it: WhatsApp is Meta-BSP, not
DLT/TCCCPR (LEGAL-OPS-PLAYBOOK §11), so it has no PE-TM chain and no 140/160 header and
the DLT layer of the gate does not describe it. Every other rule — the live DNC read
above all, the India-only destination, the big red switch, the tenant cap — does.

EVIDENCE CLASS. The three vendors' send endpoints are REPORTED from their own published API
references and consistent across multiple vendor-owned pages, but the docs hosts
(developers.facebook.com, api.interakt.ai, aisensy.com) are egress-blocked in this
environment, so none was read first-party here. They are marked at each call site the way
`compliance/whatsapp_optin.py` marks its Meta sources, and OPERATIONS §2 owns a gate to
confirm each against a live account before the first real send.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions.schema import PreparedRequest, WhatsAppConfig
from apps.api.compliance.consent import read_messaging_consent
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.ingest.service import normalize_phone

log = get_logger(__name__)


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


async def assert_recipient_may_be_messaged(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, recipient_e164: str
) -> None:
    """The gate, then the opt-in — the order and the arguments `_send_escalation` uses.

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
        dlt_governed=False,
    )
    if not decision.allowed:
        # Ids and the RULE only — never the number (hard rule 6).
        log.info(
            "whatsapp_send_blocked",
            extra={"tenant_id": str(tenant_id), "rule": decision.rule or "unknown"},
        )
        raise WhatsAppBlockedError(decision.rule or "unknown")
    consent = await read_messaging_consent(session, tenant_id=tenant_id, raw_phone=phone_e164)
    if not consent.messageable:
        log.info(
            "whatsapp_send_blocked_no_consent",
            extra={"tenant_id": str(tenant_id), "reason": "not_opted_in"},
        )
        raise WhatsAppNotOptedInError()


def _digits(e164: str) -> str:
    return e164.lstrip("+")


def build_aisensy(
    config: WhatsAppConfig, *, api_key: str, recipient_e164: str, body_values: list[str]
) -> PreparedRequest:
    """AiSensy API campaign send. `template` is the CAMPAIGN name (which is the template
    reference on AiSensy), and the api key rides in the BODY, not a header.

    REPORTED (aisensy.com/tutorials/api-reference-docs, wiki.aisensy.com — vendor-owned,
    egress-blocked here): POST https://backend.aisensy.com/campaign/t1/api/v2 with
    {apiKey, campaignName, destination, userName, templateParams[]}; templateParams length
    must equal the campaign's variable count. AiSensy has no separate header variable.
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
            "userName": "Calevate",
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
) -> PreparedRequest:
    """Meta Cloud API template send.

    REPORTED (developers.facebook.com/docs/whatsapp/cloud-api/reference/messages —
    egress-blocked here): POST https://graph.facebook.com/v20.0/{phone_number_id}/messages
    with Bearer token and a `template` message carrying `language.code` and `components`
    (an optional header component, then a body component of text parameters in order).
    """
    if not config.phone_number_id:
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
        url=f"https://graph.facebook.com/v20.0/{config.phone_number_id}/messages",
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

    REPORTED (interakt.shop resource center + documenter.getpostman.com/view/14760594 —
    egress-blocked here, consistent across vendor pages, secondary-summarised 2026-08):
    POST https://api.interakt.ai/v1/public/message/ with `Authorization: Basic <apiKey>`
    and {countryCode, phoneNumber, type:"Template", template:{name, languageCode,
    headerValues[], bodyValues[]}}. The api key is used verbatim as the Basic credential
    (Interakt issues it already base64-encoded).
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
    "WhatsAppBlockedError",
    "WhatsAppNotOptedInError",
    "assert_recipient_may_be_messaged",
    "build_aisensy",
    "build_interakt",
    "build_meta_cloud",
]
