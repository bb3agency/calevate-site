"""The Meta Cloud API adapter behind `whatsapp.WhatsAppTransport` (D-91).

This is the vendor half of the WhatsApp slice. `apps/workers/whatsapp.py` owns the
messages, the gates, the delivery records and the retry ladders; NOTHING about "was this
person allowed to be messaged" is redefined here. This module only knows how to hand one
approved template to Meta and how to report what happened.

It runs in a WORKER. No request handler reaches Meta.

======================================================================================
D-91: WHY META CLOUD API DIRECTLY, AND NOT A BSP
======================================================================================

ROADMAP §6 carried no decision, so `whatsapp.py` shipped the seam and refused to guess.
The candidates were Cloud API direct versus the Indian BSP layer (AiSensy, Interakt,
Gupshup, WATI). Ranked on what actually DIFFERS for a two-person pre-revenue company
with one client — RESEARCH-DISCIPLINE R4 — the order is:

**1. Can we get a WABA without an enterprise sales process?**
Cloud API: yes. A WABA is created and a number onboarded through the Meta Developer
Console self-serve; Meta Business Verification (typically 2-4 business days) is required
to raise messaging limits and unlock some features, NOT to send at all. Gupshup's India
pricing is "negotiated case-by-case" — a sales process by another name, and the exact
shape RESEARCH-DISCIPLINE §4 says to distrust at our size. AiSensy/Interakt/WATI are
self-serve but bring point 2.

**2. Per-message price under Meta's CURRENT model, and the monthly floor (D-32, R6).**
Conversation-based pricing was replaced by PER-MESSAGE pricing on 1 July 2025. India
list prices, effective 1 July 2026: **₹0.115 per utility or authentication message,
₹0.8631 per marketing message.** Utility templates sent inside an open 24-hour customer
service window have been free since July 2025 — but that carve-out **closes on 1 October
2026**, when service and utility messages inside the window become chargeable at rates
aligned to the utility rate.

The category question decides the whole cost story, and our two messages are in
different categories:

    hot-lead alert  → UTILITY. A service notification to our own paying customer about
      (whatsapp.py)   activity on their own account. Business-initiated with no open
                      service window, so the free-in-window carve-out never applied to
                      it and its 1 Oct 2026 closure changes nothing for us.
                      ₹0.115 each.
    campaign        → MARKETING, and we should not pretend otherwise. Utility requires
    escalation        the message to follow up a specific transaction the recipient
      (whatsapp.py)   already made; a follow-up to a consumer who did not answer a
                      cold-ish outbound call is re-engagement with no prior transaction
                      attached. Meta re-categorises templates that claim otherwise, and
                      a re-categorisation is silent and retroactive on price.
                      ₹0.8631 each — 7.5x the utility rate.

At a launch month of ~100 hot-lead alerts and ~1,000 campaign escalations that is
100 x ₹0.115 + 1,000 x ₹0.8631 ≈ **₹875/month of Meta spend**. Every BSP floor exceeds
it: AiSensy and Interakt from ₹1,499/agent/mo, WATI Growth ₹2,199/mo. So a BSP would
more than double the cost of this feature *before its own per-message markup* (WATI's
has been independently measured at 20-257% depending on category) — and D-32 already
recorded this exact shape of error for LiveKit: at launch volume the monthly floor
dominates the per-message rate.

**3. Residency and DPDP — the D-36 argument applied here.** Cloud API Local Storage
lists **IN** among its supported regions (APAC: AU, ID, IN, JP, SG, KR), pinning message
payloads to in-country stores after a bounded processing window. A BSP puts its own
store in front of that, so residency becomes the BSP's claim rather than a control we
configure, and adds a sub-processor we would have to name under DPDP. Fewer processors
is the DPDP-cheaper answer as well as the D-36-consistent one.

**4. Template approval turnaround.** Meta machine-reviews templates in minutes and
escalates borderline ones to human review for up to ~48h. BSPs submit into that SAME
review — they add a dashboard in front of the loop without shortening it. So a BSP
inserts itself into the approval path and buys nothing there.

**What a BSP actually sells** is a shared inbox, a no-code chatbot builder, campaign
tooling and contact management. We are BUILDING those (`apps/api/crm`, `campaigns`,
`kb`). Paying a monthly floor for a second CRM we would not use is the clearest possible
"no".

**When to revisit.** Two triggers, written down so this is a decision and not a habit:
(a) a support/inbox requirement arrives that we will not build — a human agent replying
inside the 24h window at volume; (b) monthly Meta spend passes roughly ₹15,000, where a
BSP's per-message markup starts to matter more than its floor and negotiated rates
become worth a sales call.

SOURCES, AND WHICH ARE SECONDARY
--------------------------------
`developers.facebook.com` and `graph.facebook.com` are BOTH blocked by this build
environment's egress proxy (403 at the gateway; recorded in the proxy's own
`recentRelayFailures`). So **every Meta-sourced figure and shape below is SECONDARY**,
read from independent implementations and vendor summaries, and marked the way
`apps/api/ingest/meta.py` marks its Meta sources: verified-from-docs vs pilot gate. They
agree with each other, which is evidence and not proof.

- Per-message model + India rates + the 1 Oct 2026 service-window change:
  sleekflow.io/en-us/blog/whatsapp-business-price · sendpulse.com/blog/whatsapp-service-
  message-pricing · ycloud.com/blog/whatsapp-api-pricing-update ·
  blueticks.co/blog/whatsapp-business-api-pricing-2026 (all SECONDARY)
- Utility vs marketing categorisation and re-categorisation:
  support.wati.io "Understanding WhatsApp template message types" ·
  learn.turn.io "How to get your template reclassified" (SECONDARY)
- BSP floors: aisensy.com/pricing · wati.io pricing · codingclave.com BSP comparison
  (SECONDARY, vendor-published and analyst-published respectively)
- Cloud API Local Storage regions incl. IN: infobip.com/docs/whatsapp/compliance/
  data-privacy · api.support.vonage.com "WhatsApp Local Data Storage" (SECONDARY)
- Self-serve onboarding + Business Verification timing: wati.io/en/blog/whatsapp-api-
  prerequisites · go4whatsup.com setup guide (SECONDARY)

======================================================================================
THE WIRE FORMAT, AND THE LINE THIS MODULE WILL NOT CROSS
======================================================================================

`POST https://graph.facebook.com/<version>/<phone-number-id>/messages`, bearer token,
JSON body:

    {"messaging_product": "whatsapp",
     "recipient_type": "individual",
     "to": "<E.164 digits>",
     "type": "template",
     "template": {"name": "<approved name>",
                  "language": {"code": "<locale>"},
                  "components": [{"type": "body",
                                  "parameters": [{"type": "text", "text": "..."}]}]}}

Errors come back as `{"error": {"message", "type", "code", "error_subcode",
"error_data": {"messaging_product", "details"}, "fbtrace_id"}}`.
  <https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages/>
  (EGRESS-BLOCKED here; shape via developer.rocket.chat/apidocs/send-a-template-whatsapp-
  message, help.botpenguin.com WhatsApp Cloud API reference, and
  docs.aws.amazon.com/social-messaging "send a template message" — three independent
  implementations agreeing, all SECONDARY.)

**Nothing beyond that shape is invented here.** There is no media component, no button
component, no `messages[].id` bookkeeping, no delivery-status webhook and no
read-receipt handling — those are real parts of the Cloud API that this code does not
touch, and writing them blind is exactly the "looks finished" failure `whatsapp.py`
refused to commit. What ships is one POST and a status classification.

**`CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA = False`.** We hold no WABA, no phone number id
and no token, and the API host is unreachable from here, so this module has never
exchanged a byte with Meta. That constant is greppable on purpose — the same device
`billing/payments.py::PROVIDER_CREATES_ORDERS` and
`ingest/meta.py::LEAD_RETRIEVAL_IMPLEMENTED` use — and it stays False until the
operational gate in the class docstring is closed by a person. The tests drive this
adapter through `httpx.MockTransport`, which proves the request WE build and the
classification WE apply; it cannot prove Meta accepts either.

Hard rule 6 throughout: `to_e164` is a phone number. It is never logged, not masked and
not fingerprinted, and no vendor error BODY is logged either — an error body may quote
the payload we just sent, which contains the number. Status codes, numeric error codes
and `fbtrace_id` only; `fbtrace_id` is Meta's own opaque request id, carries nothing
about the recipient, and is the one string their support asks for.
"""

from __future__ import annotations

from typing import Any

import httpx

from apps.api.core.logging import get_logger
from apps.workers.whatsapp import SendResult, SendStatus, WhatsAppMessage

# The import above goes ONE way: this module depends on the seam, never the reverse at
# module scope. `whatsapp.get_whatsapp_transport` imports this file inside the function
# body for exactly that reason — the alternative is an import cycle, and the alternative
# to THAT is duplicating `SendStatus` on this side, which is how two vocabularies of
# "what happened to the message" get born.

log = get_logger(__name__)

# The provider name that selects this adapter (`WHATSAPP_PROVIDER=meta_cloud_api`).
PROVIDER = "meta_cloud_api"

GRAPH_HOST = "https://graph.facebook.com"

# **Greppable claim, deliberately False.** No WABA, no credentials, and graph.facebook.com
# is egress-blocked from this environment, so not one request built here has ever been
# accepted by Meta. Flipping this is a PERSON's job, after the gate below passes; it is
# not something a test can earn.
#
# OPERATIONAL GATE — "WhatsApp Cloud API first live send". To close it:
#   1. WABA created, business verified, a number onboarded to Cloud API.
#   2. `calevate_hot_lead_v1` and `calevate_missed_call_follow_up_v1` submitted and
#      APPROVED, with their categories confirmed as UTILITY and MARKETING respectively —
#      if Meta lands the second one somewhere else, the cost model in this docstring
#      changes and D-91's arithmetic must be re-run before any campaign volume.
#   3. One real send to a staff number, confirming: the request shape is accepted, the
#      recipient format Meta wants, and that a 200 body really carries `messages[0].id`.
#   4. One deliberate FAILURE (an unapproved template name) to confirm `_classify`'s
#      numeric codes are the ones actually returned.
# Until every one of those is done, `WHATSAPP_ENABLED` stays false.
CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA = False

# One round trip, inside a job that is racing the 2-minute hot-lead SLO and has two
# retries behind it. Long enough that a slow-but-fine request is not thrown away, short
# enough that three attempts still fit the budget.
SEND_TIMEOUT_S = 10.0

# Authored reason codes — never vendor prose. A Meta error string may quote the payload
# we just sent it, which contains the recipient's number; these land in an alert, in a
# `lead_events` payload and on a client's own screen.
AUTH_FAILED_REASON = "cloud_api_auth_failed"
TEMPLATE_NOT_APPROVED_REASON = "template_not_approved"
TEMPLATE_PARAMS_REASON = "template_parameter_mismatch"
RECIPIENT_UNREACHABLE_REASON = "recipient_unreachable"
OUTSIDE_WINDOW_REASON = "recipient_not_opted_in"
NUMBER_NOT_REGISTERED_REASON = "cloud_api_number_not_registered"
RATE_LIMITED_REASON = "cloud_api_rate_limited"
UNAVAILABLE_REASON = "cloud_api_unavailable"
REQUEST_REJECTED_REASON = "cloud_api_request_rejected"
MALFORMED_RESPONSE_REASON = "cloud_api_response_malformed"

# HTTP statuses that mean "the request was fine, the moment was not".
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})

# Meta's numeric error codes, for the handful where the OPERATOR'S NEXT ACTION differs
# from what the HTTP status alone would suggest. Deliberately small: a code table copied
# wholesale from a secondary source would be a large surface of unverified claims, and
# every member not listed here falls through to the status-based classification, which
# is correct if less specific.
#
# Numeric codes, never `error.message` or `error_data.details` — a number is not prose
# and cannot smuggle the payload back into our logs.
# (Codes via heltar.com Meta error-code guide, getgabs.com and messagebot.in — all
# SECONDARY; developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes is
# EGRESS-BLOCKED. Confirmation is step 4 of the gate above.)
_CODE_REASONS: dict[int, tuple[SendStatus, str]] = {
    # Template name/language not found, or not yet approved. A human must fix it, and
    # three retries cannot.
    132001: (SendStatus.REJECTED, TEMPLATE_NOT_APPROVED_REASON),
    # The template expects a different number of variables than we sent. Ours to fix.
    132000: (SendStatus.REJECTED, TEMPLATE_PARAMS_REASON),
    # Re-engagement: outside the 24h window with no valid template path. Reported as
    # `recipient_not_opted_in` — the SAME code the gate uses — because from the client's
    # point of view it is the same fact, and two codes for one fact means two support
    # answers.
    131047: (SendStatus.REJECTED, OUTSIDE_WINDOW_REASON),
    # The recipient is not reachable on WhatsApp (no account, or a bad number).
    131026: (SendStatus.REJECTED, RECIPIENT_UNREACHABLE_REASON),
    # OUR sending number is not registered on the platform. Config, not the recipient.
    133010: (SendStatus.REJECTED, NUMBER_NOT_REGISTERED_REASON),
}


class CloudApiWhatsAppTransport:
    """One class, one method — the shape `whatsapp.py` promised a decided provider.

    An instance per send is fine and expected: `get_whatsapp_transport()` builds a fresh
    one per message so a config change takes effect, and this object caches nothing. It
    holds no token cache because Cloud API uses a long-lived system-user access token
    rather than a refresh flow — there is nothing to mint (unlike
    `google_sheets.GoogleSheetsTransport`, which caches an hourly OAuth token for exactly
    that reason).

    **NEVER RUN AGAINST A REAL WABA** — see `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA` and
    the operational gate above it. The tests drive this through `httpx.MockTransport`,
    which proves the request we build and the verdict we return; it cannot prove Meta
    accepts either.
    """

    name = PROVIDER

    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        graph_version: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._graph_version = graph_version
        # Same injection seam, and the same ownership rule, as `GoogleSheetsTransport`: a
        # caller-supplied client is the caller's to close. It exists so the tests drive
        # this adapter through httpx's real request plumbing rather than through a
        # hand-written stand-in that cannot get a URL or a header wrong.
        self._client = client

    async def send(self, message: WhatsAppMessage) -> SendResult:
        url = f"{GRAPH_HOST}/{self._graph_version}/{self._phone_number_id}/messages"
        owns_client = self._client is None
        http = self._client or httpx.AsyncClient(timeout=SEND_TIMEOUT_S, follow_redirects=False)
        try:
            response = await http.post(
                url,
                json=_body(message),
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except httpx.HTTPError as exc:
            # The exception TYPE, never its string: an httpx error message can carry the
            # request URL, and a timeout's repr can carry the request itself.
            log.warning("whatsapp_cloud_transport_error", extra={"error": type(exc).__name__})
            return SendResult(SendStatus.TRANSPORT_FAILED, reason=type(exc).__name__)
        finally:
            if owns_client:
                await http.aclose()

        if response.status_code == 200:
            # `messages[0].id` is the provider's own id for the message. It is NOT stored
            # (the delivery record in `whatsapp.py` is keyed on our ids and a vendor id
            # would be a column nothing reads — the half-wired defect CLAUDE.md names),
            # and it is not logged either: it is an identifier for a message TO a person,
            # so it is recipient-adjacent. Its presence is checked because a 200 without
            # it is not a send, whatever the status line says.
            if not _accepted(response):
                log.warning("whatsapp_cloud_ok_without_message_id")
                return SendResult(SendStatus.TRANSPORT_FAILED, reason=MALFORMED_RESPONSE_REASON)
            log.info("whatsapp_cloud_sent", extra={"template": message.template})
            return SendResult(SendStatus.DELIVERED)

        result = _classify(response.status_code, _error_code(response))
        # Status and Meta's opaque trace id only. Never the body, never the number.
        log.warning(
            "whatsapp_cloud_refused",
            extra={
                "status": response.status_code,
                "reason": result.reason,
                "fbtrace_id": _fbtrace_id(response),
            },
        )
        return result


def _body(message: WhatsAppMessage) -> dict[str, Any]:
    """The template invocation, as Meta's `/messages` endpoint takes it.

    `to` is sent WITHOUT the leading `+`. Cloud API documents the recipient as a phone
    number in E.164 and is widely reported to accept both forms, but every independent
    implementation read for this adapter sends bare digits, so that is what we send —
    the narrower of two accepted forms cannot be the wrong one. (Step 3 of the
    operational gate confirms it; it is called out here rather than buried because it is
    the single most likely reason a first live send fails.)

    There is no `body` field and cannot be: `WhatsAppMessage` has no free text, so the
    only thing this function can build is a template invocation with positional
    variables. That is the template gate from `whatsapp.py` surviving all the way to the
    wire, rather than being re-asserted here as a convention.
    """
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": message.to_e164.lstrip("+"),
        "type": "template",
        "template": {
            "name": message.template,
            "language": {"code": message.locale},
            # One `body` component. Our two templates have body variables only — no
            # header, no buttons — which is also why they are trivial to get approved.
            # An empty `parameters` list is omitted entirely rather than sent empty: a
            # template with no variables takes no components at all.
            "components": (
                [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": value} for value in message.variables
                        ],
                    }
                ]
                if message.variables
                else []
            ),
        },
    }


def _accepted(response: httpx.Response) -> bool:
    """Did a 200 actually carry a message id?

    A 200 with no `messages[0].id` is not something Meta is documented to return — which
    is exactly why it is checked. Reporting DELIVERED on a body we did not understand is
    the failure `UnconfiguredWhatsAppTransport` exists to prevent, one layer down.
    """
    try:
        messages = response.json().get("messages") or []
    except ValueError:
        return False
    return bool(messages) and bool(messages[0].get("id"))


def _error_code(response: httpx.Response) -> int | None:
    """Meta's numeric error code, or None. A NUMBER, never the message beside it."""
    try:
        code = response.json().get("error", {}).get("code")
    except (ValueError, AttributeError):
        return None
    return code if isinstance(code, int) else None


def _fbtrace_id(response: httpx.Response) -> str | None:
    """Meta's opaque request id — the one string their support asks for.

    Safe to log: it identifies a REQUEST in Meta's systems and carries nothing about the
    recipient. Truncated defensively because it is attacker-influenced only in the sense
    that it is somebody else's string in our log line.
    """
    try:
        trace = response.json().get("error", {}).get("fbtrace_id")
    except (ValueError, AttributeError):
        return None
    return str(trace)[:64] if trace else None


def _classify(status: int, code: int | None) -> SendResult:
    """One (status, code) → one authored reason, and a verdict on whether to try again.

    The numeric code wins where we have one, because it distinguishes outcomes the HTTP
    status cannot: Cloud API returns 400 for both "your template does not exist" (a human
    must fix it) and "this recipient has no WhatsApp" (nobody can fix it), and those are
    different sentences on a client's screen.

    Everything permanent is permanent for a reason a HUMAN can act on — which is the
    whole point, and is what `whatsapp._is_operational` then splits into "page someone"
    versus "record it and move on".
    """
    if code is not None and code in _CODE_REASONS:
        send_status, reason = _CODE_REASONS[code]
        return SendResult(send_status, reason=reason)
    if status in _TRANSIENT_STATUS:
        return SendResult(
            SendStatus.TRANSPORT_FAILED,
            reason=RATE_LIMITED_REASON if status == 429 else UNAVAILABLE_REASON,
        )
    if status >= 500:
        return SendResult(SendStatus.TRANSPORT_FAILED, reason=UNAVAILABLE_REASON)
    if status in (401, 403):
        # The token is missing, expired or lacks the permission. Retrying cannot mint a
        # new one, and an operator has to.
        return SendResult(SendStatus.REJECTED, reason=AUTH_FAILED_REASON)
    # Everything else in the 4xx band is a request WE built being wrong, and repeating it
    # cannot fix that either.
    return SendResult(SendStatus.REJECTED, reason=REQUEST_REJECTED_REASON)


__all__ = [
    "AUTH_FAILED_REASON",
    "CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA",
    "GRAPH_HOST",
    "MALFORMED_RESPONSE_REASON",
    "NUMBER_NOT_REGISTERED_REASON",
    "OUTSIDE_WINDOW_REASON",
    "PROVIDER",
    "RATE_LIMITED_REASON",
    "RECIPIENT_UNREACHABLE_REASON",
    "REQUEST_REJECTED_REASON",
    "SEND_TIMEOUT_S",
    "TEMPLATE_NOT_APPROVED_REASON",
    "TEMPLATE_PARAMS_REASON",
    "UNAVAILABLE_REASON",
    "CloudApiWhatsAppTransport",
]
