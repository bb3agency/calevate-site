"""An email that names a button has a link of its own paragraph for `from_text` to make one.

`email_render.from_text` turns a paragraph that is nothing but a URL into the button; a URL
sharing its paragraph with the line before it renders as plain text, and the `cta` label the
job passes is never shown.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.billing.service import WALLET_LEVEL_EMPTY
from apps.workers import number_holds, rate_card_notice, wallet_alerts
from apps.workers.email_render import from_text


def _hold_body() -> str:
    return number_holds.compose(
        event="held",
        business="Sri Clinic",
        slug="sri-clinic",
        rows=[("wallet_negative", datetime(2026, 11, 6, 18, 30, tzinfo=UTC), "Anjali")],
    )[1]


def _low_balance_body() -> str:
    return wallet_alerts.compose(
        level=WALLET_LEVEL_EMPTY, balance_inr=Decimal("0.00"), minutes_left=None, slug="sri-clinic"
    )


def _rate_card_body() -> str:
    return rate_card_notice.compose(starts_on="1 December 2026", rungs=(), slug="sri-clinic")


@pytest.mark.parametrize("body", [_hold_body, _low_balance_body, _rate_card_body])
def test_the_credit_link_is_the_emails_button(body: object) -> None:
    text = body()  # type: ignore[operator]
    html = from_text(subject="s", preheader="s", heading="s", text=text, cta="Add credit").html
    assert ">Add credit</a>" in html
    assert 'href="https://' in html and "/c/sri-clinic/credits" in html
