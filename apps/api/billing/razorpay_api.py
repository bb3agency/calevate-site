"""The rest of Razorpay's API that D-699 needs, on `RazorpayOrders`' one transport.

`billing/payments.RazorpayOrders` is the one place this repository talks to Razorpay; this
module EXTENDS it rather than opening a second client, so every call shares its auth
(HTTP Basic `key_id:key_secret`), its timeout, its client lifecycle and its rule that a
vendor error is logged by status and never forwarded.

Every wire fact below was read from Razorpay's own LLM documentation on 9 Oct 2026, at
`https://razorpay.com/docs/build/llm-docs/<path>.md`; the `<path>` is cited per method.
VERIFIED-VENDOR-DOCS throughout unless a line says otherwise.

What we send Razorpay that it did not hold before: for a mandate, the account owner's
name, email and phone on `POST /v1/customers`, and their email and phone again on each
recurring charge (both fields are mandatory there). Nothing else about a client leaves.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal

import httpx

from apps.api.billing.payments import (
    ORDER_TIMEOUT_S,
    SUPPORTED_CURRENCY,
    USER_AGENT,
    RazorpayOrders,
    inr_to_paise,
    payment_capability,
    payments_not_configured,
    razorpay_api_secret,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

MandateMethod = Literal["upi", "card"]

#: `token.frequency` for a mandate we charge on demand (`as_presented`), accepted for both
#: UPI and cards (`api/payments/recurring-payments/upi/create-authorization-transaction.md`,
#: `.../cards/create-authorization-transaction.md`).
MANDATE_FREQUENCY: Final = "as_presented"

#: RBI e-mandate limit without an additional factor of authentication: a card mandate's
#: `max_amount` is at most 1500000 paise (₹15,000) — "For an amount higher than this, the
#: cardholder should provide an Additional Factor of Authentication (AFA) as per RBI
#: guidelines" (`api/payments/recurring-payments/cards/create-authorization-transaction.md`);
#: UPI Autopay: "Any auto debit above ₹15,000 undergoes an additional authorisation from the
#: customer" (`payments/recurring-payments/upi/faqs.md`). An auto-recharge needs no
#: customer present, so we never ask for more than this per debit.
MANDATE_MAX_DEBIT_INR: Final = Decimal("15000.00")

#: How long a mandate we ask for stays valid. UPI defaults to 10 years and allows 30
#: (`.../upi/create-authorization-transaction.md`, `expire_at`); we ask for 5 years so a
#: forgotten mandate does not outlive the client relationship by a decade.
MANDATE_YEARS: Final = 5

#: The authorisation payment. UPI needs at least ₹1 ("For UPI, the amount must be a
#: minimum of ₹1", same page); a card order's minimum is 100 paise
#: (`.../cards/create-subsequent-payments.md`). It is a real payment and is credited to the
#: wallet like any other.
MANDATE_AUTH_AMOUNT_INR: Final = Decimal("1.00")

#: Razorpay's list endpoints return at most 100 items per call and page with `skip`
#: (`api/payments/fetch-all-payments.md`, `api/refunds/fetch-all.md`).
LIST_PAGE: Final = 100

#: The dispute evidence categories our admin page offers, a subset of the entity's
#: evidence fields (`api/disputes/entity.md`).
EvidenceKind = Literal[
    "billing_proof",
    "proof_of_service",
    "explanation_letter",
    "access_activity_log",
    "refund_cancellation_policy",
    "term_and_conditions",
    "customer_communication",
]


@dataclass(frozen=True, slots=True)
class ProviderPayment:
    """OUR normalized view of one Razorpay payment entity (`api/payments/entity.md`)."""

    payment_id: str
    status: str
    amount_paise: int
    currency: str
    order_id: str | None
    method: str | None
    international: bool
    token_id: str | None
    customer_id: str | None
    notes: dict[str, str]
    error_code: str | None
    created_at: int


@dataclass(frozen=True, slots=True)
class ProviderRefundRow:
    refund_id: str
    payment_id: str
    amount_paise: int
    currency: str
    status: str
    notes: dict[str, str]


@dataclass(frozen=True, slots=True)
class ProviderSettlement:
    settlement_id: str
    amount_paise: int
    status: str
    created_at: int


def _notes(value: Any) -> dict[str, str]:
    """`notes` is an OBJECT when set and an empty ARRAY `[]` when not, in Razorpay's own
    samples (`webhooks/payments.md`, every sample payload). Only string pairs survive."""
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if isinstance(v, str)}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def normalize_payment(entity: Any) -> ProviderPayment | None:
    """A payment entity → `ProviderPayment`, or None when it is not one we can read."""
    if not isinstance(entity, dict):
        return None
    pid, amount, currency = entity.get("id"), _int(entity.get("amount")), entity.get("currency")
    if not isinstance(pid, str) or amount is None or not isinstance(currency, str):
        return None

    def _s(key: str) -> str | None:
        value = entity.get(key)
        return value if isinstance(value, str) and value else None

    return ProviderPayment(
        payment_id=pid,
        status=_s("status") or "",
        amount_paise=amount,
        currency=currency.upper(),
        order_id=_s("order_id"),
        method=_s("method"),
        international=entity.get("international") is True,
        token_id=_s("token_id"),
        customer_id=_s("customer_id"),
        notes=_notes(entity.get("notes")),
        error_code=_s("error_code"),
        created_at=_int(entity.get("created_at")) or 0,
    )


class RazorpayApi(RazorpayOrders):
    """`RazorpayOrders` plus customers, recurring payments, lists, disputes and documents."""

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        data: dict[str, str] | None = None,
    ) -> Any:
        """One authenticated call; a 4xx/5xx becomes OUR `payment_provider_rejected` and
        an unreadable body our `payment_provider_unreadable`. The vendor's prose is never
        read past its HTTP status (hard rule 2's argument applied to a payment provider)."""
        headers = {"User-Agent": USER_AGENT}
        if json is not None:
            headers["Content-Type"] = "application/json"
        client = self._client or httpx.AsyncClient(
            base_url=self._base_url, timeout=ORDER_TIMEOUT_S, headers=headers
        )
        try:
            response = await client.request(
                method,
                f"{self._version_path}{path}",
                json=json,
                params=params,
                files=files,
                data=data,
                auth=self._auth,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            log.warning("razorpay_request_unreachable", extra={"reason": type(exc).__name__})
            raise ProblemError(
                kind="dependency",
                code="payment_provider_unreachable",
                title="The payment provider did not respond",
                detail="We could not reach the payment provider just now.",
                remediation="Try again in a minute.",
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code >= 400:
            log.warning(
                "razorpay_request_rejected",
                extra={"status": response.status_code, "method": method},
            )
            raise ProblemError(
                kind="dependency",
                code="payment_provider_rejected",
                title="The payment provider said no",
                detail="The payment provider did not accept that.",
                remediation="Try again later, or check the payment provider's dashboard.",
            )
        try:
            return response.json()
        except ValueError as exc:
            raise _unreadable() from exc

    # --- customers (`api/customers/create.md`) -----------------------------------------

    async def create_customer(
        self, *, name: str, email: str, contact: str, notes: dict[str, str]
    ) -> str:
        """`POST /v1/customers`. `fail_existing: "0"` returns the existing customer for the
        same details instead of an error, so a second mandate attempt reuses it."""
        body = await self._send(
            "POST",
            "/customers",
            json={
                "name": name[:50],
                "email": email,
                "contact": contact,
                "fail_existing": "0",
                "notes": notes,
            },
        )
        return _id_of(body)

    # --- recurring payments -------------------------------------------------------------

    async def create_mandate_order(
        self,
        *,
        customer_id: str,
        method: MandateMethod,
        max_debit_inr: Decimal,
        expire_at: int,
        receipt: str,
        notes: dict[str, str],
    ) -> str:
        """The AUTHORISATION order: `POST /v1/orders` with `customer_id`, `method` and a
        `token` block (`max_amount`, `expire_at`, `frequency`). UPI:
        `api/payments/recurring-payments/upi/create-authorization-transaction.md` §1.1.2;
        cards: `.../cards/create-authorization-transaction.md`. The browser then opens
        Checkout with this `order_id`, the `customer_id` and `recurring: "1"`."""
        if max_debit_inr > MANDATE_MAX_DEBIT_INR:
            raise ProblemError.business_rule(
                "mandate_limit_exceeded",
                "An automatic payment can be at most ₹15,000 at a time.",
                remediation="Choose a recharge amount of ₹15,000 or less.",
            )
        body = await self._send(
            "POST",
            "/orders",
            json={
                "amount": inr_to_paise(MANDATE_AUTH_AMOUNT_INR),
                "currency": SUPPORTED_CURRENCY,
                "customer_id": customer_id,
                "method": method,
                "receipt": receipt,
                "notes": notes,
                "token": {
                    "max_amount": inr_to_paise(max_debit_inr),
                    "expire_at": expire_at,
                    "frequency": MANDATE_FREQUENCY,
                },
            },
        )
        return _id_of(body)

    async def create_charge_order(
        self, *, amount_inr: Decimal, receipt: str, notes: dict[str, str]
    ) -> str:
        """A SUBSEQUENT-payment order. A new order is required for every charge, and
        `payment_capture` is mandatory there; we send `true`
        (`.../upi/create-subsequent-payments.md` §3.1, `.../cards/...` §3.1).

        No `notification` object, deliberately: without it Razorpay sends the pre-debit
        notification itself and debits 25 hours (UPI) or 36 hours 5 minutes (cards) after
        it is delivered, and retries a failed debit; with it, Razorpay "will not attempt any
        retry if the debit fails" (same pages)."""
        body = await self._send(
            "POST",
            "/orders",
            json={
                "amount": inr_to_paise(amount_inr),
                "currency": SUPPORTED_CURRENCY,
                "receipt": receipt,
                "notes": notes,
                "payment_capture": True,
            },
        )
        return _id_of(body)

    async def create_recurring_payment(
        self,
        *,
        email: str,
        contact: str,
        amount_inr: Decimal,
        order_id: str,
        customer_id: str,
        token_id: str,
        notes: dict[str, str],
    ) -> str:
        """`POST /v1/payments/create/recurring`; the success body is
        `{"razorpay_payment_id": "pay_…"}` (`.../upi/create-subsequent-payments.md` §3.2).
        `amount` must equal the order's."""
        body = await self._send(
            "POST",
            "/payments/create/recurring",
            json={
                "email": email,
                "contact": contact,
                "currency": SUPPORTED_CURRENCY,
                "amount": inr_to_paise(amount_inr),
                "order_id": order_id,
                "customer_id": customer_id,
                "token": token_id,
                "recurring": True,
                "notes": notes,
            },
        )
        payment_id = body.get("razorpay_payment_id") if isinstance(body, dict) else None
        if not isinstance(payment_id, str) or not payment_id:
            raise _unreadable()
        return payment_id

    async def cancel_token(self, *, customer_id: str, token_id: str, method: MandateMethod) -> None:
        """Withdraw a mandate. UPI: `PUT /v1/customers/:id/tokens/:token_id/cancel`
        (`api/payments/recurring-payments/upi/tokens.md` §2.3, answers
        `cancellation_initiated`). Cards: `DELETE /v1/customers/:id/tokens/:token_id`
        (`.../cards/tokens.md` §2.3)."""
        path = f"/customers/{customer_id}/tokens/{token_id}"
        if method == "upi":
            await self._send("PUT", f"{path}/cancel")
        else:
            await self._send("DELETE", path)

    async def token_status(self, *, customer_id: str, token_id: str) -> str | None:
        """`recurring_details.status` of one token (`initiated`, `confirmed`, `rejected`,
        `cancelled`, `paused`), read off `GET /v1/customers/:id/tokens`
        (`api/payments/recurring-payments/upi/tokens.md` §2.2). None if not listed. Only
        the status is read: the items also carry VPA and card details we never keep."""
        body = await self._send("GET", f"/customers/{customer_id}/tokens")
        items = body.get("items") if isinstance(body, dict) else None
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("id") == token_id:
                details = item.get("recurring_details")
                status = details.get("status") if isinstance(details, dict) else None
                return status if isinstance(status, str) else None
        return None

    # --- reads --------------------------------------------------------------------------

    async def fetch_payment(self, payment_id: str) -> ProviderPayment:
        """`GET /v1/payments/:id` (`api/payments/fetch-with-id.md`), which also carries
        `token_id` and `customer_id` for a recurring payment."""
        payment = normalize_payment(await self._send("GET", f"/payments/{payment_id}"))
        if payment is None:
            raise _unreadable()
        return payment

    async def list_payments(self, *, since: int, until: int) -> list[ProviderPayment]:
        """`GET /v1/payments?from&to&count&skip`, every page."""
        return [
            p
            for p in (normalize_payment(i) for i in await self._list("/payments", since, until))
            if p is not None
        ]

    async def list_refunds(self, *, since: int, until: int) -> list[ProviderRefundRow]:
        """`GET /v1/refunds?from&to&count&skip` (`api/refunds/fetch-all.md`)."""
        rows: list[ProviderRefundRow] = []
        for item in await self._list("/refunds", since, until):
            if not isinstance(item, dict):
                continue
            rid, pid, amount = item.get("id"), item.get("payment_id"), _int(item.get("amount"))
            if not isinstance(rid, str) or not isinstance(pid, str) or amount is None:
                continue
            rows.append(
                ProviderRefundRow(
                    refund_id=rid,
                    payment_id=pid,
                    amount_paise=amount,
                    currency=str(item.get("currency") or "").upper(),
                    status=str(item.get("status") or ""),
                    notes=_notes(item.get("notes")),
                )
            )
        return rows

    async def list_settlements(self, *, since: int, until: int) -> list[ProviderSettlement]:
        """`GET /v1/settlements?from&to&count&skip` (`api/settlements/fetch-all.md`).
        Read only: we report settlements, we never act on them."""
        out: list[ProviderSettlement] = []
        for item in await self._list("/settlements", since, until):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                out.append(
                    ProviderSettlement(
                        settlement_id=item["id"],
                        amount_paise=_int(item.get("amount")) or 0,
                        status=str(item.get("status") or ""),
                        created_at=_int(item.get("created_at")) or 0,
                    )
                )
        return out

    async def _list(self, path: str, since: int, until: int) -> list[Any]:
        items: list[Any] = []
        skip = 0
        while True:
            body = await self._send(
                "GET",
                path,
                params={"from": since, "to": until, "count": LIST_PAGE, "skip": skip},
            )
            page = body.get("items") if isinstance(body, dict) else None
            if not isinstance(page, list):
                raise _unreadable()
            items.extend(page)
            if len(page) < LIST_PAGE:
                return items
            skip += LIST_PAGE

    # --- disputes (`api/disputes/accept.md`, `api/disputes/contest.md`) -----------------

    async def accept_dispute(self, dispute_id: str) -> str:
        """`POST /v1/disputes/:id/accept`. Irreversible: the dispute becomes `lost`."""
        body = await self._send("POST", f"/disputes/{dispute_id}/accept")
        return str(body.get("status") or "") if isinstance(body, dict) else ""

    async def contest_dispute(
        self,
        dispute_id: str,
        *,
        summary: str,
        amount_paise: int,
        evidence: dict[str, list[str]],
    ) -> str:
        """`PATCH /v1/disputes/:id/contest` with `action: "submit"` — a draft is never
        auto-submitted, and at least one document is required (same page)."""
        body = await self._send(
            "PATCH",
            f"/disputes/{dispute_id}/contest",
            json={
                "summary": summary[:1000],
                "amount": amount_paise,
                **evidence,
                "action": "submit",
            },
        )
        return str(body.get("status") or "") if isinstance(body, dict) else ""

    async def upload_document(self, *, filename: str, content: bytes, content_type: str) -> str:
        """`POST /v1/documents`, multipart, `purpose=dispute_evidence`
        (`api/documents/create.md`). Returns the `doc_…` id the contest names."""
        body = await self._send(
            "POST",
            "/documents",
            files={"file": (filename, content, content_type)},
            data={"purpose": "dispute_evidence"},
        )
        return _id_of(body)


def _id_of(body: Any) -> str:
    value = body.get("id") if isinstance(body, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise _unreadable()
    return value.strip()


def _unreadable() -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="payment_provider_unreadable",
        title="The payment provider sent an answer we could not read",
        detail="We could not complete that with the payment provider.",
        remediation="Try again in a minute.",
    )


def razorpay_api() -> RazorpayApi:
    """The adapter, behind the same capability check order creation uses."""
    capability = payment_capability()
    if not capability.available:
        raise payments_not_configured(capability.reason)
    if not capability.creates_orders:
        raise payments_not_configured(capability.orders_reason)
    key_id = get_settings().razorpay_key_id
    key_secret = razorpay_api_secret()
    assert key_id is not None and key_secret is not None
    return RazorpayApi(key_id=key_id, key_secret=key_secret)


__all__ = [
    "LIST_PAGE",
    "MANDATE_AUTH_AMOUNT_INR",
    "MANDATE_FREQUENCY",
    "MANDATE_MAX_DEBIT_INR",
    "MANDATE_YEARS",
    "EvidenceKind",
    "MandateMethod",
    "ProviderPayment",
    "ProviderRefundRow",
    "ProviderSettlement",
    "RazorpayApi",
    "normalize_payment",
    "razorpay_api",
]
