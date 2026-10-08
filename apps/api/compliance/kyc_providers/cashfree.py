"""Cashfree Secure ID DigiLocker — the recommended provider (D-692).

Every field name below was read from Cashfree's public API reference on 8 Oct 2026
(VERIFIED-VENDOR-DOCS; the comparison is `docs/evidence/digilocker-kyc-providers-2026-10-08.md`):

  create   POST {base}/digilocker  — `x-client-id`, `x-client-secret`; body
           `verification_id` (ours, at most 50 characters), `document_requested`
           (AADHAAR/PAN/DRIVING_LICENSE), `redirect_url`; response `url`, `reference_id`,
           `status` PENDING. The URL expires 10 minutes after it is generated.
           https://www.cashfree.com/docs/api-reference/vrs/v2/digilocker/create-digilocker-url
  status   GET {base}/digilocker?verification_id=…  — `status` PENDING | AUTHENTICATED |
           EXPIRED | CONSENT_DENIED, `user_details.name`.
           …/digilocker/get-digilocker-verification-status
  document GET {base}/digilocker/document/{AADHAAR|PAN}?verification_id=…  — AADHAAR:
           `status` SUCCESS, `name`, `uid` MASKED (`xxxxxxxx5647`); PAN: `pan` (full),
           `name_pan_card`. "Currently we do not support downloading of full documents
           through Digilocker API."
           …/digilocker/get-document-from-digilocker
  webhook  `x-webhook-signature` = base64(HMAC-SHA256(client secret, `x-webhook-timestamp`
           + raw body)); body `event_type`, `data.verification_id`, `data.status`,
           `data.user_details.name`.
           …/digilocker/webhooks-digilocker and …/vrs/webhook-signature-verification
  bases    https://sandbox.cashfree.com/verification, https://api.cashfree.com/verification

THE OUTCOME IS PULLED, NOT TRUSTED FROM THE PUSH. Both the client's return and a webhook
lead to `fetch_outcome`, which asks Cashfree with our own credentials. The webhook is
signature-checked and used only to learn WHICH run finished; the facts we record come from
the authenticated pull. Only the record the client chose (Aadhaar OR PAN, D-692) is
requested.

We keep the NAME, a MASKED number (Aadhaar last four; PAN `XXXXX1234X`) and the reference.
Date of birth, gender, mobile, address, photo link, XML and the full PAN are read past in
memory and never stored or logged (hard rule 6). Cashfree also sells a separate PAN
verification with a name-match score (`POST /pan`, …/vrs/v2/pan/verify-pan-sync); it is
not used, because the DigiLocker PAN record already carries the registered name.

CALLER AUTHENTICATION IS IP WHITELISTING. "IP whitelisting is required for both the sandbox
(test) and production environments"; the alternative is the `x-cf-signature` public-key
method, only one is active at a time, and `x-cf-signature` must not be sent while
whitelisting is active. Up to 25 public IPv4 addresses, no IPv6 or CIDR. A call from an
unlisted address is refused `ip_validation_failed`
(https://www.cashfree.com/docs/secure-id/get-started/integration/ip-whitelisting-verification,
read 8 Oct 2026). We whitelist the VPS's fixed IPv4 (OPERATIONS gate K-2), so this adapter
sends no `x-cf-signature`; the signature method is not implemented. The page does not say
which response field carries the code, so it is matched in the body text.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any, Final
from uuid import uuid4

import httpx

from apps.api.compliance.kyc_providers.base import (
    IdDocument,
    VerificationOutcome,
    VerificationStart,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

BASE_URLS: Final[dict[str, str]] = {
    "sandbox": "https://sandbox.cashfree.com/verification",
    "production": "https://api.cashfree.com/verification",
}
SIGNATURE_HEADER: Final = "x-webhook-signature"
#: Cashfree's refusal for a caller IPv4 missing from the account's allow-list.
IP_VALIDATION_FAILED: Final = "ip_validation_failed"
TIMESTAMP_HEADER: Final = "x-webhook-timestamp"
TIMEOUT_S: Final = 10.0

#: Cashfree's `status` values, mapped to the reason we show a client on failure.
#: Our record choice -> Cashfree's `document_requested` / `document_type` value.
_DOCUMENT_TYPE: Final[dict[str, str]] = {"aadhaar": "AADHAAR", "pan": "PAN"}
_PAN: Final = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")

_FAILED: Final[dict[str, str]] = {
    "EXPIRED": "link_expired",
    "CONSENT_DENIED": "consent_denied",
}


def sign(*, secret: str, timestamp: str, body: bytes) -> str:
    """The signature Cashfree sends, computed the documented way. Exported so tests sign a
    delivery the way the receiver verifies it."""
    digest = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class CashfreeDigiLocker:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        environment: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = BASE_URLS.get(environment, BASE_URLS["production"])
        self._client = client

    @property
    def name(self) -> str:
        return "cashfree"

    @property
    def contract_verified(self) -> bool:
        return True

    @property
    def webhook_is_authoritative(self) -> bool:
        return False

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {
            "x-client-id": self._client_id,
            "x-client-secret": self._client_secret,
            "Content-Type": "application/json",
        }
        client = self._client or httpx.AsyncClient(base_url=self._base_url, timeout=TIMEOUT_S)
        try:
            return await client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            log.warning("kyc_provider_unreachable", extra={"reason": type(exc).__name__})
            raise ProblemError(
                kind="dependency",
                code="verification_provider_unreachable",
                title="The verification service did not respond",
                detail="We could not reach the identity verification service just now.",
                remediation="Try again in a few minutes.",
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()

    def _refused(self, response: httpx.Response) -> ProblemError:
        if IP_VALIDATION_FAILED.encode() in response.content:
            # Our server's address is not on Cashfree's allow-list: an operator fix, never
            # the client's. Distinct code so the alarm names the remedy.
            log.error("kyc_provider_ip_not_whitelisted", extra={"status": response.status_code})
            return ProblemError(
                kind="dependency",
                code="verification_provider_ip_not_whitelisted",
                title="The verification service is not set up for this server yet",
                detail="DigiLocker verification is temporarily unavailable.",
                remediation="Try again later, or upload the owner's ID for review instead.",
                failure_stage="ROUTE_HANDLER",
            )
        log.warning("kyc_provider_refused", extra={"status": response.status_code})
        return ProblemError(
            kind="dependency",
            code="verification_provider_refused",
            title="The identity check did not go through",
            detail="The identity verification service could not start or check this run.",
            remediation="Try again in a few minutes. If it keeps happening, contact support.",
        )

    async def start(
        self, *, entity_type: str, redirect_back_url: str, id_document: IdDocument
    ) -> VerificationStart:
        # Ours, unique, and within the documented 50 characters.
        verification_id = f"clv-{uuid4().hex}"
        response = await self._request(
            "POST",
            "/digilocker",
            json={
                "verification_id": verification_id,
                # Only the record the client chose: asking for both would collect a
                # second identifier we have no use for.
                "document_requested": [_DOCUMENT_TYPE[id_document]],
                "redirect_url": redirect_back_url,
            },
        )
        if response.status_code >= 400:
            raise self._refused(response)
        body = _json_object(response.content)
        url = body.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise self._refused(response)
        return VerificationStart(provider_ref=verification_id, redirect_url=url)

    async def fetch_outcome(
        self, *, provider_ref: str, id_document: IdDocument
    ) -> VerificationOutcome | None:
        response = await self._request(
            "GET", "/digilocker", params={"verification_id": provider_ref}
        )
        if response.status_code >= 400:
            raise self._refused(response)
        status = str(_json_object(response.content).get("status") or "")
        if status == "PENDING" or not status:
            return None
        if status != "AUTHENTICATED":
            return VerificationOutcome(
                provider_ref=provider_ref,
                verified=False,
                failure_reason=_FAILED.get(status, "not_completed"),
            )
        document = await self._request(
            "GET",
            f"/digilocker/document/{_DOCUMENT_TYPE[id_document]}",
            params={"verification_id": provider_ref},
        )
        if document.status_code >= 400:
            raise self._refused(document)
        # The response carries date of birth, gender, address, a photo link, the XML and
        # (for PAN) the full number. Only the name and a masked number leave this method;
        # the parsed body goes out of scope with it and is never logged.
        record = _json_object(document.content)
        if id_document == "aadhaar":
            return _aadhaar_outcome(provider_ref, record)
        return _pan_outcome(provider_ref, record)

    def verify_webhook(self, *, raw: bytes, headers: dict[str, str]) -> bool:
        presented = headers.get(SIGNATURE_HEADER)
        timestamp = headers.get(TIMESTAMP_HEADER)
        if not presented or not timestamp:
            return False
        expected = sign(secret=self._client_secret, timestamp=timestamp, body=raw)
        return hmac.compare_digest(presented.strip().encode(), expected.encode())

    def parse_outcome(self, *, raw: bytes) -> VerificationOutcome:
        """The run a signed delivery is about. Only `provider_ref` is relied on; the route
        pulls the outcome itself (`fetch_outcome`)."""
        data = _json_object(raw).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("verification_id"), str):
            raise ValueError("delivery names no verification_id")
        return VerificationOutcome(
            provider_ref=data["verification_id"], verified=False, failure_reason="pending_pull"
        )


def _aadhaar_outcome(provider_ref: str, record: dict[str, Any]) -> VerificationOutcome:
    """`status` SUCCESS, `name`, and `uid` already masked by Cashfree (`xxxxxxxx5647`)."""
    name = record.get("name")
    if record.get("status") != "SUCCESS" or not isinstance(name, str) or not name.strip():
        return VerificationOutcome(
            provider_ref=provider_ref, verified=False, failure_reason="document_unavailable"
        )
    uid = record.get("uid")
    last_four = uid[-4:] if isinstance(uid, str) and uid[-4:].isdigit() else None
    return VerificationOutcome(
        provider_ref=provider_ref,
        verified=True,
        verified_name=name,
        masked_id=f"XXXX-XXXX-{last_four}" if last_four else None,
    )


def _pan_outcome(provider_ref: str, record: dict[str, Any]) -> VerificationOutcome:
    """`pan` (FULL) and `name_pan_card`. The page shows no example value for this
    response's `status`, so success is the presence of a well-formed PAN and a name
    (UNKNOWN: what `status` reads on success). The PAN is masked here and the full one
    is not kept."""
    name = record.get("name_pan_card")
    pan = record.get("pan")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(pan, str)
        or not _PAN.fullmatch(pan.strip().upper())
    ):
        return VerificationOutcome(
            provider_ref=provider_ref, verified=False, failure_reason="document_unavailable"
        )
    return VerificationOutcome(
        provider_ref=provider_ref,
        verified=True,
        verified_name=name,
        masked_id=f"XXXXX{pan.strip().upper()[5:9]}X",
    )


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


__all__ = ["BASE_URLS", "SIGNATURE_HEADER", "TIMESTAMP_HEADER", "CashfreeDigiLocker", "sign"]
