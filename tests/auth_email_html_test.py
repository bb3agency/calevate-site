"""The branded half of every auth email — and the properties that make it safe to send.

WHY THIS EXISTS. `auth_email._body` shipped plain text with a comment arguing for it: "a
transactional secret does not need HTML and an HTML mail is one more thing that can render
wrong in a client we have never seen." That is right about the OTP codes and wrong about
the link mails, which arrive BEFORE a person has seen a single screen of the product. A
wall of monospace asking someone to click a 200-character URL is indistinguishable from
phishing, and the first one we send is to the founder's own first administrator.

So the shape is deliberate and asymmetric — links get the frame, codes stay austere — and
the tests below pin the parts that are correctness rather than taste:

1. **Both parts, always.** An HTML-only message is invisible in a text client and in the
   preview pane. `text` is never empty and never a stub.
2. **The two parts agree.** They are composed from the same inputs; a link that differs
   between them is a person clicking one thing and reading another.
3. **Nothing is injected.** A token reaches the markup through `escape()`. Tokens are
   URL-safe today, which is exactly why nobody would notice the day one is not.
4. **No remote fetch.** An email that loads anything from a URL leaks the open to whoever
   hosts it, and every mail client blocks it anyway — so a tracking pixel or a webfont
   link is a defect twice over.
"""

from __future__ import annotations

import re

import pytest
from apps.api.core import brand, console_links
from apps.workers import email_render

LINK_KINDS = ("admin_bootstrap", "password_reset", "invite_password")
CODE_KINDS = ("otp_login_challenge", "otp_step_up", "otp_email_verify")


def _realm_for(kind: str) -> str:
    return "admin" if kind == "admin_bootstrap" else "client"


@pytest.mark.parametrize("kind", LINK_KINDS + CODE_KINDS)
def test_every_kind_has_a_subject_and_a_non_empty_text_part(kind: str) -> None:
    message = email_render.render(kind, _realm_for(kind), "tok_abc123")
    assert message.subject and message.subject in email_render.SUBJECTS.values()
    assert len(message.text.strip()) > 40, (
        "the text part is the one a screen reader, a terminal client and the inbox "
        f"preview pane read. It must be the real message: {message.text!r}"
    )


def test_an_unknown_kind_raises_rather_than_sending_a_blank_subject() -> None:
    """`deliver_auth_email` treats a bad payload as OUR bug and refuses to retry it. A
    renderer that returned an empty subject would send instead — worse, and silent."""
    with pytest.raises(ValueError, match="no subject line"):
        email_render.render("not_a_kind", "client", "tok")


@pytest.mark.parametrize("kind", LINK_KINDS)
def test_the_link_kinds_carry_the_same_url_in_both_parts(kind: str) -> None:
    """THE PROPERTY THAT MATTERS MOST HERE. A person who does not trust the button reads
    the URL underneath it; if the two disagree, one of them is a lie."""
    realm = _realm_for(kind)
    message = email_render.render(kind, realm, "tok_abc123")
    assert message.html is not None

    expected = {
        "admin_bootstrap": console_links.admin_bootstrap_link,
        "invite_password": console_links.accept_invitation_link,
    }.get(kind)
    url = (
        expected("tok_abc123")
        if expected
        else console_links.password_reset_link(realm, "tok_abc123")
    )

    assert url in message.text, "the plain-text part does not carry the link at all"
    assert f'href="{url}"' in message.html, "the button does not point at the composed link"
    # And the visible fallback, so the URL is READABLE and not only clickable.
    assert message.html.count(url) >= 2, (
        "the URL appears once — the button has it but the paste-this-instead line does "
        "not, which is the line that lets a cautious person check where they are going"
    )


@pytest.mark.parametrize("kind", CODE_KINDS)
def test_the_code_kinds_show_the_code_in_both_parts(kind: str) -> None:
    message = email_render.render(kind, "client", "482913")
    assert "482913" in message.text
    assert message.html is not None and "482913" in message.html


@pytest.mark.parametrize("kind", LINK_KINDS + CODE_KINDS)
def test_a_hostile_secret_cannot_break_out_of_the_markup(kind: str) -> None:
    """Tokens are URL-safe base64 today. That is a property of the current mint, not of
    this renderer, and "it can't contain a quote" is the assumption that ages badly."""
    hostile = '"><script>alert(1)</script>'
    message = email_render.render(kind, _realm_for(kind), hostile)
    assert message.html is not None
    assert "<script>" not in message.html, "an unescaped secret reached the markup"
    assert "&lt;script&gt;" in message.html or "%3Cscript%3E" in message.html


@pytest.mark.parametrize("kind", LINK_KINDS + CODE_KINDS)
def test_no_email_fetches_anything_from_the_network(kind: str) -> None:
    """No tracking pixel, no webfont, no remote CSS. Every client blocks them by default,
    and the ones that do not turn "did they open it" into data we did not ask for."""
    message = email_render.render(kind, _realm_for(kind), "tok_abc123")
    assert message.html is not None
    for tag in ("<img", "<link", "<script", "@import", "url("):
        assert tag not in message.html.lower(), f"the mail reaches the network via {tag!r}"


@pytest.mark.parametrize("kind", LINK_KINDS)
def test_the_html_pins_a_light_scheme(kind: str) -> None:
    """The product is light-only by decision (D-471). Without these two meta tags a
    dark-mode client force-inverts the palette and produces the half-dark result that
    `color-scheme: light` exists to prevent on the web."""
    html = email_render.render(kind, _realm_for(kind), "tok").html
    assert html is not None
    assert 'name="color-scheme" content="light"' in html
    assert 'name="supported-color-schemes" content="light"' in html


def test_the_preheader_is_not_the_wordmark() -> None:
    """Left out, clients scrape the first visible text — which is the wordmark, so every
    message would preview as 'Calevate Calevate' in the inbox list."""
    html = email_render.render("admin_bootstrap", "admin", "tok").html
    assert html is not None
    first_visible = re.search(r"<div style=\"display:none[^\"]*\">([^<]+)</div>", html)
    assert first_visible is not None, "the hidden preheader div is gone"
    assert brand.PRODUCT not in first_visible.group(1)
    assert len(first_visible.group(1)) > 20


def test_the_button_uses_the_brand_button_green_and_not_the_resting_one() -> None:
    """`--brand-strong` is the primary button; `--brand` is the resting accent. Using the
    lighter one here puts white text on a green that the console never uses for a button —
    and `brand_tokens_test` only proves the values match the CSS, not that the right one
    was picked."""
    html = email_render.render("admin_bootstrap", "admin", "tok").html
    assert html is not None
    assert brand.BRAND_STRONG in html
