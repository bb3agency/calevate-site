"""The staged D-933 product email: one frame new and renamed emails are built from.

No live email uses it yet (`docs/EMAILS.md`); these pin what it promises so the rename-day
switch, and the dispute and KYC emails other work adds, inherit a frame that already works.
"""

from __future__ import annotations

import re

import pytest
from apps.api.core import brand
from apps.workers.email_render import PRODUCT_EMAIL_MAX_LINES, Email, from_text, product_email

SETTINGS_URL = "https://app.example.test/c/acme/settings/notifications"


def _receipt(**overrides: object) -> Email:
    args: dict[str, object] = {
        "subject": "Payment received: ₹2,000",
        "preheader": "₹2,000 is now in your calling credit.",
        "heading": "Payment received",
        "lines": ["We added ₹2,000 to your calling credit.", "Your calls keep running."],
        "reason": "You got this because you are the billing contact for Acme.",
        "cta": "Open billing",
        "url": "https://app.example.test/c/acme/billing",
        "facts": [("Amount", "₹2,000"), ("Balance", "₹2,450")],
    }
    args.update(overrides)
    return product_email(**args)  # type: ignore[arg-type]


def test_both_parts_carry_the_same_message() -> None:
    email = _receipt()
    assert email.subject == "Payment received: ₹2,000"
    for piece in (
        "Payment received",
        "We added ₹2,000 to your calling credit.",
        "Amount: ₹2,000",
        "Open billing:\nhttps://app.example.test/c/acme/billing",
        "You got this because you are the billing contact for Acme.",
        brand.LEGAL_ENTITY_NAME,
        brand.REGISTERED_ADDRESS,
    ):
        assert piece in email.text, piece
    assert email.html is not None
    for piece in ("Payment received", "We added ₹2,000", "Balance", "₹2,450", "Open billing"):
        assert piece in email.html, piece


def test_the_html_is_accessible_and_previewable() -> None:
    html = _receipt().html
    assert html is not None
    assert '<html lang="en">' in html
    assert f'alt="{brand.PRODUCT}"' in html, "a blocked logo must still say who wrote"
    assert f'src="{brand.LOGO_URL}"' in html and brand.LOGO_URL.startswith("https://")
    assert "₹2,000 is now in your calling credit." in html, "the preheader"
    assert "<style" not in html, "Gmail strips <style>; every style is inline"
    assert 'role="presentation"' in html


def test_the_footer_names_the_company_as_the_legal_pages_do() -> None:
    html = _receipt().html
    assert html is not None
    assert f"{brand.LEGAL_ENTITY_NAME} · {brand.REGISTERED_ADDRESS}" in html


def test_a_settings_link_only_where_a_setting_exists() -> None:
    without = _receipt()
    assert "Notification settings" not in (without.html or "")
    assert "Notification settings" not in without.text
    with_link = _receipt(settings_url=SETTINGS_URL)
    assert f'href="{SETTINGS_URL}"' in (with_link.html or "")
    assert f"Notification settings: {SETTINGS_URL}" in with_link.text


@pytest.mark.parametrize("count", [0, PRODUCT_EMAIL_MAX_LINES + 1])
def test_the_body_stays_short(count: int) -> None:
    with pytest.raises(ValueError, match="lines"):
        _receipt(lines=["A line."] * count)


@pytest.mark.parametrize(("cta", "url"), [("Open billing", None), (None, "https://x.test")])
def test_a_button_needs_both_halves(cta: str | None, url: str | None) -> None:
    with pytest.raises(ValueError, match="button"):
        _receipt(cta=cta, url=url)


def test_values_are_escaped() -> None:
    html = _receipt(lines=["<b>Acme & Co</b>"]).html or ""
    assert "&lt;b&gt;Acme &amp; Co&lt;/b&gt;" in html
    assert "<b>Acme" not in html


def test_todays_emails_keep_todays_frame() -> None:
    """The staged frame is opt-in: an email built the current way still shows the text
    wordmark and no logo image (live mail is unchanged until the rename)."""
    html = from_text(subject="s", preheader="p", heading="h", text="Body.").html or ""
    assert "<img" not in html
    assert re.search(rf">{brand.PRODUCT}</span>", html)
