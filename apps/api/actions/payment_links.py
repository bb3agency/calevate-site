"""Razorpay Payment Links on the CLIENT's own Razorpay account (D-700).

The client's key pair, sealed as their `integration_credentials` row of kind `razorpay`
(`key_id` in `non_secret`, the key secret sealed). This module never reads
`Settings.razorpay_key_id/secret`: those are Calevate's own billing keys, which the PAYMENTS
lane owns (D-699), and a link created with them would put a caller's payment in our account.

VERIFIED-VENDOR-DOCS, read 9 Oct 2026 (razorpay.com/docs/api/payments/payment-links/
create-standard/):

* `POST https://api.razorpay.com/v1/payment_links/`, HTTP Basic `key_id:key_secret`.
* `amount` is an integer in paise, at least 100; `currency` `INR`; `description` up to 2048
  characters; `reference_id` up to 40 characters and unique per link; `customer.contact`
  8 to 14 characters with the country code; `expire_by` Unix seconds, at least 15 minutes ahead;
  `notify.sms`/`notify.email` true make Razorpay send its own message; `notes` up to 15
  pairs; unknown fields fail with "extra fields sent".
* The answer carries `id` (`plink_…`), `short_url` and `status` (`created`, …).
* Errors are `{"error": {"code", "description", …}}`, mostly HTTP 400.
* `GET https://api.razorpay.com/v1/payments?count=1` lists payments (count 1..100,
  razorpay.com/docs/api/payments/fetch-all-payments/): the read-only call the "test" button
  makes to prove a key pair works.

We send `notify` false: the caller gets the link on WhatsApp from the client's own number
(the founder's decision: WhatsApp, not SMS), not a second message from Razorpay.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from apps.api.actions.schema import PreparedRequest

API_BASE: Final = "https://api.razorpay.com/v1"
#: Razorpay's floor for an INR link, in paise.
MIN_AMOUNT_PAISE: Final = 100
REFERENCE_MAX: Final = 40


def _auth(key_id: str, key_secret: str) -> str:
    return "Basic " + base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()


def paise(amount_inr: Decimal) -> int:
    """Rupees to whole paise, half-up — the one conversion, never through a float."""
    return int((amount_inr * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def create_link(
    *,
    key_id: str,
    key_secret: str,
    amount_inr: Decimal,
    description: str,
    reference_id: str,
    contact_e164: str,
    expire_minutes: int,
    now: datetime | None = None,
) -> PreparedRequest:
    at = now or datetime.now(UTC)
    return PreparedRequest(
        method="POST",
        url=f"{API_BASE}/payment_links/",
        headers={"Authorization": _auth(key_id, key_secret), "Content-Type": "application/json"},
        json_body={
            "amount": paise(amount_inr),
            "currency": "INR",
            "accept_partial": False,
            "description": description[:2048],
            "reference_id": reference_id[:REFERENCE_MAX],
            "customer": {"contact": contact_e164},
            "expire_by": int((at + timedelta(minutes=expire_minutes)).timestamp()),
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
        },
    )


def probe(*, key_id: str, key_secret: str) -> PreparedRequest:
    """The read-only call that proves a key pair, for the client's test button."""
    return PreparedRequest(
        method="GET",
        url=f"{API_BASE}/payments?count=1",
        headers={"Authorization": _auth(key_id, key_secret)},
    )


__all__ = ["MIN_AMOUNT_PAISE", "create_link", "paise", "probe"]
