"""Every authentication email, as subject + plain text + HTML, composed in ONE place.

**WHY THIS EXISTS AT ALL.** `auth_email._body` returned a plain-text string, and
`scripts/bootstrap_admin` composed its own copy of one of those messages. That is the same
two-writers shape that produced a setup link pointing at a page nobody served
(`apps/api/core/console_links`) — one composer for the URL was the fix there, and one
composer for the MESSAGE is the fix here.

**WHY HTML, WHEN THE COMMENT THIS REPLACES ARGUED AGAINST IT.** It said "a transactional
secret does not need HTML and an HTML mail is one more thing that can render wrong in a
client we have never seen". That is right about the OTP codes and wrong about the setup
and invitation links: those are a person's first contact with the product, arriving before
they have seen a single screen, and a bare wall of monospace text asking them to click a
long URL is indistinguishable from phishing. Both are true at once, so:

* **link mails get the full treatment** — the wordmark, the brand green, a real button;
* **code mails stay austere** by choice, with the six digits as the only ornament. A person
  reading a login code wants to read six characters and put the phone down.

Every message is sent as **multipart**: the text part is not a fallback we tolerate, it is
the version that renders in a screen reader, in a terminal client, and in the preview pane
that shows the first line of the plain part. Both parts are composed here from the same
inputs, so they cannot say different things.

**THE HTML IS DELIBERATELY OLD-FASHIONED.** Tables, inline styles, no flexbox, no grid,
no `<style>` block carrying anything load-bearing. Outlook renders with Word's engine;
Gmail's web client strips `<style>` in some contexts and has never supported `@font-face`
from an external URL. The modern-CSS version of this file looks better in the four clients
a developer tests and collapses in the two an SMB owner actually uses.
"""

# ruff: noqa: E501 — THE LINE LIMIT IS OFF FOR THIS FILE, AND ONLY FOR THIS FILE.
#
# Every long line here is an HTML attribute list. An email `style=""` is unavoidably long
# because there is no stylesheet to move it into: Gmail's web client strips `<style>` in
# several contexts, so every declaration has to sit on the element. Wrapping them would
# put newlines inside attribute values — legal HTML that Outlook's Word engine has been
# observed to render as literal whitespace — to satisfy a rule about reading Python.
#
# Scoped to this module rather than added to the global ruff config, so the limit still
# binds every line of Python in the repository including the ones below.

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

from apps.api.core import brand, console_links


@dataclass(frozen=True, slots=True)
class Email:
    """One message, in both the forms a client can render.

    `html` is None for the code mails — that is a decision, not an omission, and the
    transports treat None as "send text only" rather than substituting anything.
    """

    subject: str
    text: str
    html: str | None


def _shell(*, preheader: str, body: str) -> str:
    """The frame every HTML mail sits in.

    The PREHEADER is the hidden line an inbox shows beside the subject. Left out, clients
    scrape the first visible text — which here is the wordmark, so every message would
    preview as "Calevate Calevate". It is hidden with the four properties that work
    together across clients; any one of them alone is defeated somewhere.

    `color-scheme` / `supported-color-schemes` are what stop a dark-mode client
    force-inverting the palette. The product is light-only by decision (D-471), and an
    email client's auto-invert produces exactly the half-dark result that CSS variable
    exists to prevent on the web.
    """
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{escape(brand.PRODUCT)}</title>
</head>
<body style="margin:0;padding:0;background-color:{brand.APP};">
<div style="display:none;font-size:1px;color:{brand.APP};line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{brand.APP};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;width:100%;">

<tr><td style="padding:0 0 20px 4px;">
<span style="font-family:{brand.FONT_STACK};font-size:19px;font-weight:600;letter-spacing:-0.3px;color:{brand.TEXT};">{escape(brand.PRODUCT)}</span>
<span style="display:inline-block;width:6px;height:6px;border-radius:3px;background-color:{brand.BRAND};margin-left:5px;vertical-align:middle;"></span>
</td></tr>

<tr><td style="background-color:{brand.SURFACE};border:1px solid {brand.LINE};border-radius:14px;padding:32px 28px;">
{body}
</td></tr>

<tr><td style="padding:20px 4px 0 4px;font-family:{brand.FONT_STACK};font-size:12px;line-height:18px;color:{brand.TEXT_FAINT};">
AI voice agents for Indian businesses.<br>
You are receiving this because someone set up an account for this address. If that was not expected, you can ignore this email &mdash; nothing happens until the link is opened.
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _heading(text: str) -> str:
    return (
        f'<h1 style="margin:0 0 12px 0;font-family:{brand.FONT_STACK};font-size:22px;'
        f'line-height:29px;font-weight:600;letter-spacing:-0.4px;color:{brand.TEXT};">'
        f"{escape(text)}</h1>"
    )


def _paragraph(text: str, *, color: str | None = None, size: int = 15) -> str:
    return (
        f'<p style="margin:0 0 16px 0;font-family:{brand.FONT_STACK};font-size:{size}px;'
        f'line-height:{size + 8}px;color:{color or brand.TEXT_MUTED};">{escape(text)}</p>'
    )


def _button(label: str, url: str) -> str:
    """A padded anchor rather than a VML "bulletproof" button.

    The VML variant renders a true rectangle in Outlook's Word engine and costs twelve
    lines of conditional comments that no test in this repository can exercise. A padded
    anchor degrades in Outlook to a slightly smaller click target on the same green — a
    cosmetic difference — and the plain-text URL below it is the real fallback for any
    client that mangles the button entirely. `mso-padding-alt` and the nbsp hack cover the
    common Outlook case without the comment block.
    """
    return f"""<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 20px 0;">
<tr><td align="center" bgcolor="{brand.BRAND_STRONG}" style="border-radius:10px;mso-padding-alt:14px 26px;">
<a href="{escape(url, quote=True)}" style="display:inline-block;padding:14px 26px;font-family:{brand.FONT_STACK};font-size:15px;font-weight:600;line-height:20px;color:#ffffff;text-decoration:none;border-radius:10px;">{escape(label)}</a>
</td></tr></table>"""


def _fallback_link(url: str) -> str:
    """The URL in full, because a person who does not trust a green button is right not to.

    `word-break` matters: a 200-character token URL in a 520px column overflows the card
    in several clients, and an overflowing link is one a person cannot read to check.
    """
    return (
        f'<p style="margin:0 0 6px 0;font-family:{brand.FONT_STACK};font-size:12px;'
        f'line-height:17px;color:{brand.TEXT_FAINT};">Or paste this into your browser:</p>'
        f'<p style="margin:0;font-family:{brand.FONT_MONO};font-size:12px;line-height:18px;'
        f'color:{brand.TEXT_MUTED};word-break:break-all;">{escape(url)}</p>'
    )


def _note(text: str) -> str:
    """The expiry sentence, in the brand tint. It is the one thing in these mails a person
    must read BEFORE clicking, so it is not left as body copy among the rest."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:20px 0 0 0;"><tr><td style="background-color:{brand.BRAND_SOFT};'
        f"border-radius:10px;padding:12px 14px;font-family:{brand.FONT_STACK};font-size:13px;"
        f'line-height:19px;color:{brand.BRAND_STRONG};">{escape(text)}</td></tr></table>'
    )


def _code_block(code: str) -> str:
    return (
        f'<div style="margin:4px 0 18px 0;padding:18px 20px;background-color:{brand.APP};'
        f"border:1px solid {brand.LINE};border-radius:12px;text-align:center;"
        f"font-family:{brand.FONT_MONO};font-size:30px;line-height:36px;font-weight:600;"
        f'letter-spacing:6px;color:{brand.TEXT};">{escape(code)}</div>'
    )


def _link_email(
    *, subject: str, preheader: str, heading: str, lead: str, cta: str, url: str, expiry: str
) -> Email:
    text = (
        f"{lead}\n\n"
        f"{url}\n\n"
        f"{expiry}\n\n"
        "— Calevate\n"
        "If you were not expecting this, you can ignore this email; nothing happens "
        "until the link is opened.\n"
    )
    html = _shell(
        preheader=preheader,
        body=(
            _heading(heading)
            + _paragraph(lead)
            + _button(cta, url)
            + _fallback_link(url)
            + _note(expiry)
        ),
    )
    return Email(subject=subject, text=text, html=html)


def _code_email(*, subject: str, purpose: str, code: str) -> Email:
    """Austere on purpose — see the module docstring. Still branded, still the frame, but
    the six digits are the only thing with weight, because that is all the reader wants."""
    lead = f"Your Calevate code to {purpose} is:"
    text = (
        f"{lead}\n\n    {code}\n\n"
        "It expires in 10 minutes. If you did not ask for it, you can ignore this email.\n"
    )
    html = _shell(
        preheader=f"{code} — expires in 10 minutes",
        body=(
            _paragraph(lead, color=brand.TEXT, size=15)
            + _code_block(code)
            + _paragraph(
                "It expires in 10 minutes. If you did not ask for it, ignore this email.", size=13
            )
        ),
    )
    return Email(subject=subject, text=text, html=html)


#: Subject lines, keyed by the `kind` `authn/service._enqueue_auth_email` sends. A closed
#: mapping rather than a formatted string, so an unknown kind is a loud failure rather
#: than an email with a blank subject.
SUBJECTS: dict[str, str] = {
    "password_reset": "Reset your Calevate password",
    "otp_email_verify": "Your Calevate verification code",
    "otp_login_challenge": "Your Calevate sign-in code",
    "otp_step_up": "Your Calevate authorization code",
    "invite_password": "You have been invited to Calevate",
    "admin_bootstrap": "Set up your Calevate administrator account",
}

_OTP_PURPOSE = {
    "otp_login_challenge": "sign in",
    "otp_step_up": "authorize this action",
    "otp_email_verify": "confirm your email address",
}


def render(kind: str, realm: str, secret: str) -> Email:
    """The one composer. `secret` is a token for the link kinds and a code for the rest."""
    subject = SUBJECTS.get(kind)
    if subject is None:
        raise ValueError(f"no subject line for auth email kind {kind!r}")

    if kind == "password_reset":
        return _link_email(
            subject=subject,
            preheader="Choose a new password — the link expires in one hour.",
            heading="Reset your password",
            lead=(
                "Someone asked to reset the password for this Calevate account. "
                "Choose a new one here."
            ),
            cta="Choose a new password",
            url=console_links.password_reset_link(realm, secret),
            expiry=(
                "This link works once and expires in one hour. If this was not you, your "
                "password has not changed."
            ),
        )

    if kind == "invite_password":
        return _link_email(
            subject=subject,
            preheader="Set your password to join the workspace — expires in 72 hours.",
            heading="You have been invited to Calevate",
            lead=("Someone has invited you to their Calevate workspace. Set a password to get in."),
            cta="Accept the invitation",
            url=console_links.accept_invitation_link(secret),
            expiry="This link works once and expires in 72 hours.",
        )

    if kind == "admin_bootstrap":
        return _link_email(
            subject=subject,
            preheader="Set your password to finish setting up your administrator account.",
            heading="Set up your administrator account",
            lead=(
                "You have been given an administrator account on a Calevate deployment. "
                "Set a password to finish."
            ),
            cta="Set your password",
            url=console_links.admin_bootstrap_link(secret),
            expiry=(
                "This link works once and expires in one hour. If it expires, ask whoever "
                "deployed this environment to issue another."
            ),
        )

    return _code_email(
        subject=subject,
        purpose=_OTP_PURPOSE.get(kind, "confirm your email address"),
        code=secret,
    )


_URL_LINE = re.compile(r"^https?://\S+$")


def from_text(
    *, subject: str, preheader: str, heading: str, text: str, cta: str | None = None
) -> Email:
    """Present an ALREADY-COMPOSED plain-text message in the brand frame.

    **WHY WRAPPING RATHER THAN A SECOND COMPOSER**, which is the opposite of the choice
    made for the auth mails above. Those had no content guard; these two do. The hot-lead
    alert runs its summary through `redact()` before it is ever a string, and the weekly
    digest runs `assert_text_carries_no_call_content` over the finished text — both
    guarding THE TEXT. An HTML twin composed from the same structured inputs would be a
    second string carrying the same client data past neither check, and the first time
    that mattered would be a caller's phone number sitting in an inbox.

    So the guarded text IS the content and this only decides how it looks. Every line is
    escaped, so a value that reached the text legitimately cannot become markup.

    A paragraph that is nothing but a URL becomes the button — which is what turns "Open
    the lead to see the full number and call back:" followed by a bare link into something
    a business owner taps on a phone inside the two-minute SLO that alert exists for.
    """
    rendered: list[str] = []
    used_button = False
    for block in text.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and _URL_LINE.match(lines[0].strip()):
            url = lines[0].strip()
            if not used_button:
                rendered.append(_button(cta or "Open", url))
                used_button = True
            rendered.append(_fallback_link(url))
            continue
        body = "<br>".join(escape(line) for line in lines)
        rendered.append(
            f'<p style="margin:0 0 14px 0;font-family:{brand.FONT_STACK};font-size:15px;'
            f'line-height:23px;color:{brand.TEXT_MUTED};">{body}</p>'
        )
    return Email(
        subject=subject,
        text=text,
        html=_shell(preheader=preheader, body=_heading(heading) + "".join(rendered)),
    )


__all__ = ["SUBJECTS", "Email", "from_text", "render"]
