"""Every authentication email, as subject + plain text + HTML, composed in ONE place.

`auth_email._body` once returned a plain-text string while `scripts/bootstrap_admin`
composed its own copy of one of those messages: two writers of one message, the shape that
produced a setup link pointing at a page nobody served (`apps/api/core/console_links`). One
composer for the message is the fix, as one composer for the URL was there.

**WHY EVERY AUTH MAIL IS DESIGNED, THE CODE MAILS INCLUDED.** These are a person's first
contact with the product and often arrive before they have seen a screen of it; a bare
wall of text asking for a click or quoting a secret is indistinguishable from phishing. The
code mails carry the most-read six characters we send, so they get the most deliberate
layout rather than the least: the code alone at display size in a monospace face, its
expiry directly beneath it, and a purpose-specific "didn't ask for this?" paragraph that
tells the reader what an unexpected code means for THEIR account (after a password, it
means the password is known). The expiry is read from `authn/otp.OTP_LIFETIME`, so the
mail cannot promise a window the verifier does not keep.

Every message is sent as **multipart**: the text part is not a fallback we tolerate, it is
the version that renders in a screen reader, in a terminal client, and in the preview pane
that shows the first line of the plain part. Both parts are composed here from the same
inputs, so they cannot say different things. The frame and its Outlook/Gmail constraints
live in `apps/api/core/email_layout`.

Client-facing text names no provider (D-679).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from typing import Final

from apps.api.authn.otp import OTP_LIFETIME
from apps.api.core import brand, console_links
from apps.api.core import email_layout as layout


@dataclass(frozen=True, slots=True)
class Email:
    """One message, in both the forms a client can render.

    `html` may be None for a caller that has only text; the transports treat None as
    "send text only" rather than substituting anything.
    """

    subject: str
    text: str
    html: str | None


#: Under the card of every auth mail.
_AUTH_FOOTER: Final = (
    "Calevate · AI voice agents for Indian businesses.",
    "You are receiving this because it was requested for this email address.",
)
#: Under the card of a wrapped client notice (`from_text`), which is not about an account.
_NOTICE_FOOTER: Final = ("Calevate · AI voice agents for Indian businesses.",)

_OTP_MINUTES: Final = int(OTP_LIFETIME.total_seconds() // 60)
_OTP_EXPIRY: Final = f"It expires in {_OTP_MINUTES} minutes and works once."
_UNEXPECTED_LABEL: Final = "Didn't ask for this?"


def _link_email(
    *, subject: str, preheader: str, heading: str, lead: str, cta: str, url: str, expiry: str
) -> Email:
    text = (
        f"{heading}\n\n"
        f"{lead}\n\n"
        f"{cta}:\n{url}\n\n"
        f"{expiry}\n\n"
        "— Calevate\n"
        "If you were not expecting this, you can ignore this email; nothing happens "
        "until the link is opened.\n"
    )
    html = layout.shell(
        preheader=preheader,
        footer=_AUTH_FOOTER,
        body=(
            layout.heading(heading)
            + layout.paragraph(lead)
            + layout.button(cta, url)
            + layout.fallback_link(url)
            + layout.callout(expiry)
        ),
    )
    return Email(subject=subject, text=text, html=html)


@dataclass(frozen=True, slots=True)
class _CodeCopy:
    heading: str
    #: What to do with the code, one sentence.
    lead: str
    #: What an unexpected code means for this purpose, and what to do about it.
    unexpected: str


_CODE_COPY: Final[dict[str, _CodeCopy]] = {
    "otp_login_challenge": _CodeCopy(
        heading="Your sign-in code",
        lead="Enter this code in Calevate to finish signing in.",
        # This code is only sent after a correct password (`authn/models.OTP_PURPOSES`).
        unexpected=(
            "This code is sent only after your password was entered correctly. If that "
            "was not you, someone may know your password: do not share this code with "
            "anyone, and change your password."
        ),
    ),
    "otp_step_up": _CodeCopy(
        heading="Confirm it's you",
        lead="Enter this code in Calevate to confirm the change you asked to make.",
        unexpected=(
            "It is sent only from a signed-in session. If you did not ask for it, someone "
            "may be using your account: do not share this code, and change your password."
        ),
    ),
    "otp_email_verify": _CodeCopy(
        heading="Confirm your email address",
        lead="Enter this code in Calevate to confirm this is your email address.",
        unexpected=(
            "If you did not add this address to a Calevate account, you can ignore this "
            "email. Nothing changes without the code."
        ),
    ),
    "otp_signup": _CodeCopy(
        heading="Your sign-up code",
        lead="Enter this code to finish creating your Calevate account.",
        unexpected=(
            "If you did not try to create a Calevate account, you can ignore this email. "
            "No account is created without the code."
        ),
    ),
}


def _code_email(*, subject: str, copy: _CodeCopy, code: str) -> Email:
    text = (
        f"{copy.heading}\n\n"
        f"{copy.lead}\n\n"
        f"    {code}\n\n"
        f"{_OTP_EXPIRY}\n\n"
        f"{_UNEXPECTED_LABEL}\n"
        f"{copy.unexpected}\n\n"
        "— Calevate\n"
    )
    html = layout.shell(
        preheader=f"{code} is your code. {_OTP_EXPIRY}",
        footer=_AUTH_FOOTER,
        body=(
            layout.heading(copy.heading)
            + layout.paragraph(copy.lead, color=brand.TEXT)
            + layout.code_panel(code, caption=_OTP_EXPIRY)
            + layout.divider(margin=4)
            + layout.paragraph_html(
                f"<strong>{escape(_UNEXPECTED_LABEL)}</strong>",
                color=brand.TEXT,
                size=14,
                margin=4,
            )
            + layout.paragraph(copy.unexpected, size=14, margin=0)
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
    "otp_signup": "Your Calevate sign-up code",
    "signup_existing_account": "You already have a Calevate account",
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

    if kind == "signup_existing_account":
        return _link_email(
            subject=subject,
            preheader="Someone tried to create an account with this address.",
            heading="You already have a Calevate account",
            lead=(
                "Someone tried to create a new Calevate account with this email address. "
                "You already have one, so nothing new was created. Sign in as usual, or "
                "choose a new password here if you have forgotten it."
            ),
            cta="Choose a new password",
            url=console_links.password_reset_link(realm, secret),
            expiry=(
                "This link works once and expires in one hour. If this was not you, you can "
                "ignore this email: your account and password have not changed."
            ),
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
        copy=_CODE_COPY.get(kind, _CODE_COPY["otp_email_verify"]),
        code=secret,
    )


_URL_LINE = re.compile(r"^https?://\S+$")


def from_text(
    *, subject: str, preheader: str, heading: str, text: str, cta: str | None = None
) -> Email:
    """Present an ALREADY-COMPOSED plain-text message in the brand frame.

    **WHY WRAPPING RATHER THAN A SECOND COMPOSER**, which is the opposite of the choice
    made for the auth mails above. Those had no content guard; these do. The hot-lead
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
                rendered.append(layout.button(cta or "Open", url))
                used_button = True
            rendered.append(layout.fallback_link(url))
            continue
        rendered.append(
            layout.paragraph_html("<br>".join(escape(line) for line in lines), margin=14)
        )
    return Email(
        subject=subject,
        text=text,
        html=layout.shell(
            preheader=preheader,
            footer=_NOTICE_FOOTER,
            body=layout.heading(heading) + "".join(rendered),
        ),
    )


__all__ = ["SUBJECTS", "Email", "from_text", "render"]
