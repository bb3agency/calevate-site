"""A presented secret with a non-ASCII character is a refusal, never a 500.

`hmac.compare_digest` raises TypeError on a `str` holding any non-ASCII character, and
header values arrive latin-1-decoded, so one such byte from anybody turned each of these
checks into an unhandled exception that pages. Every verifier of a caller-supplied secret
compares bytes; these pin the Razorpay pair.
"""

from __future__ import annotations

from apps.api.billing.payments import verify_checkout_signature, verify_signature

_HOSTILE = "sha256=\xe9\xe9\xe9"


def test_the_razorpay_webhook_signature_refuses_a_non_ascii_value() -> None:
    assert verify_signature(secret="whsec", body=b"{}", signature=_HOSTILE) is False


def test_the_razorpay_checkout_signature_refuses_a_non_ascii_value() -> None:
    assert (
        verify_checkout_signature(
            key_secret="key", order_id="order_1", payment_id="pay_1", signature=_HOSTILE
        )
        is False
    )
