"""The building blocks every HTML email is assembled from, in ONE place.

Two composers use them: `apps/workers/email_render` (the auth mails and the wrapped
client notices) and `apps/api/core/alert_email` (operator alarms). The alarm composer has
to live under `apps/api/core` because `apps/voice-runtime` raises alarms and may not import
`apps.workers` (`tests/voice_runtime_import_surface_test.py`), so the frame lives here
rather than in the workers package and both composers import it. Two copies of the frame
would be two looks for one brand.

**THE HTML IS DELIBERATELY OLD-FASHIONED.** Tables, inline styles, no flexbox, no grid,
no `<style>` block carrying anything load-bearing. Outlook renders with Word's engine;
Gmail's web client strips `<style>` in some contexts and has never supported `@font-face`
from an external URL. The modern-CSS version looks better in the four clients a developer
tests and collapses in the two an SMB owner actually uses.

**DARK MODE IS TOLERATED, NOT DESIGNED.** The product is light-only (D-471), so the mail
declares `color-scheme: light`, which Apple Mail honours. Gmail's apps and Outlook ignore
that and invert on their own, so every coloured surface here carries BOTH the `bgcolor`
attribute and an inline `background-color` (Outlook inverts the attribute, Gmail the
style; one without the other inverts half a card), text always sits on a surface that
declares its own colour rather than on a transparent one, and no meaning is carried by
colour alone: a badge says its state in words.

Every value interpolated into markup goes through `html.escape` inside these helpers, so
a caller passes plain strings and cannot forget.
"""

# ruff: noqa: E501 — THE LINE LIMIT IS OFF FOR THIS FILE, AND ONLY FOR THIS FILE.
#
# Every long line here is an HTML attribute list. An email `style=""` is unavoidably long
# because there is no stylesheet to move it into, and wrapping one puts newlines inside an
# attribute value, which Outlook's Word engine has been observed to render as whitespace.

from __future__ import annotations

from collections.abc import Iterable, Sequence
from html import escape
from typing import Literal

from apps.api.core import brand

Tone = Literal["brand", "danger", "warn", "neutral"]

#: (text, background, border) per tone, all from `brand`, so the badge and callout colours
#: are the console's own `--danger*` / `--warn*` tokens.
_TONES: dict[Tone, tuple[str, str, str]] = {
    "brand": (brand.BRAND_STRONG, brand.BRAND_SOFT, brand.BRAND_SOFT),
    "danger": (brand.DANGER, brand.DANGER_SOFT, brand.DANGER_LINE),
    "warn": (brand.WARN, brand.WARN_SOFT, brand.WARN_LINE),
    "neutral": (brand.TEXT_MUTED, brand.APP, brand.LINE),
}


def shell(*, preheader: str, body: str, footer: Sequence[str], width: int = 560) -> str:
    """The frame every HTML mail sits in: wordmark, one card, a footer.

    The PREHEADER is the hidden line an inbox shows beside the subject. Left out, clients
    scrape the first visible text, which here is the wordmark, so every message would
    preview as "Calevate Calevate". It is hidden with the four properties that work
    together across clients; any one of them alone is defeated somewhere.

    `footer` is plain text, one paragraph per entry.
    """
    footer_html = "".join(
        f'<p style="margin:0 0 8px 0;font-family:{brand.FONT_STACK};font-size:12px;line-height:18px;color:{brand.TEXT_FAINT};">{escape(line)}</p>'
        for line in footer
    )
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
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{brand.APP}" style="background-color:{brand.APP};">
<tr><td align="center" style="padding:28px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:{width}px;width:100%;">

<tr><td style="padding:0 4px 18px 4px;">
<span style="font-family:{brand.FONT_STACK};font-size:19px;font-weight:600;letter-spacing:-0.3px;color:{brand.TEXT};">{escape(brand.PRODUCT)}</span>
<span style="display:inline-block;width:6px;height:6px;border-radius:3px;background-color:{brand.BRAND};margin-left:5px;vertical-align:middle;"></span>
</td></tr>

<tr><td bgcolor="{brand.SURFACE}" style="background-color:{brand.SURFACE};border:1px solid {brand.LINE};border-radius:14px;padding:28px 24px;">
{body}
</td></tr>

<tr><td style="padding:18px 4px 0 4px;">
{footer_html}
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def heading(text: str, *, size: int = 22) -> str:
    return (
        f'<h1 style="margin:0 0 10px 0;font-family:{brand.FONT_STACK};font-size:{size}px;'
        f'line-height:{size + 7}px;font-weight:600;letter-spacing:-0.4px;color:{brand.TEXT};">'
        f"{escape(text)}</h1>"
    )


def section_label(text: str) -> str:
    """A small heading above a group: the second level of the hierarchy, under the h1."""
    return (
        f'<h2 style="margin:22px 0 8px 0;font-family:{brand.FONT_STACK};font-size:13px;'
        f'line-height:18px;font-weight:600;letter-spacing:0.2px;color:{brand.TEXT};">'
        f"{escape(text)}</h2>"
    )


def paragraph(text: str, *, color: str | None = None, size: int = 15, margin: int = 16) -> str:
    return paragraph_html(escape(text), color=color, size=size, margin=margin)


def paragraph_html(
    markup: str, *, color: str | None = None, size: int = 15, margin: int = 16
) -> str:
    """`paragraph` for markup the caller has ALREADY escaped (see `inline_markdown`)."""
    return (
        f'<p style="margin:0 0 {margin}px 0;font-family:{brand.FONT_STACK};font-size:{size}px;'
        f'line-height:{size + 8}px;color:{color or brand.TEXT_MUTED};">{markup}</p>'
    )


def badge(text: str, *, tone: Tone) -> str:
    """A state pill. Inline-block inside a table cell so Outlook keeps its padding."""
    fg, bg, line = _TONES[tone]
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="display:inline-table;margin:0 6px 12px 0;">'
        f'<tr><td bgcolor="{bg}" style="background-color:{bg};border:1px solid {line};border-radius:999px;'
        f"padding:3px 10px;font-family:{brand.FONT_STACK};font-size:12px;line-height:16px;"
        f'font-weight:600;letter-spacing:0.2px;color:{fg};">{escape(text)}</td></tr></table>'
    )


def button(label: str, url: str) -> str:
    """A padded anchor rather than a VML "bulletproof" button.

    The VML variant renders a true rectangle in Outlook's Word engine and costs twelve
    lines of conditional comments that no test in this repository can exercise. A padded
    anchor degrades in Outlook to a slightly smaller click target on the same green, and
    the plain URL beside it is the real fallback for a client that mangles the button.
    """
    return f"""<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 20px 0;">
<tr><td align="center" bgcolor="{brand.BRAND_STRONG}" style="background-color:{brand.BRAND_STRONG};border-radius:10px;mso-padding-alt:14px 26px;">
<a href="{escape(url, quote=True)}" style="display:inline-block;padding:14px 26px;font-family:{brand.FONT_STACK};font-size:15px;font-weight:600;line-height:20px;color:#ffffff;text-decoration:none;border-radius:10px;">{escape(label)}</a>
</td></tr></table>"""


def fallback_link(url: str, *, lead: str = "Or paste this into your browser:") -> str:
    """The URL in full, because a person who does not trust a green button is right not to.

    `word-break` matters: a 200-character token URL in a 520px column overflows the card
    in several clients, and an overflowing link is one a person cannot read to check.
    """
    return (
        f'<p style="margin:0 0 6px 0;font-family:{brand.FONT_STACK};font-size:12px;'
        f'line-height:17px;color:{brand.TEXT_FAINT};">{escape(lead)}</p>'
        f'<p style="margin:0;font-family:{brand.FONT_MONO};font-size:12px;line-height:18px;'
        f'color:{brand.TEXT_MUTED};word-break:break-all;">{escape(url)}</p>'
    )


def callout(
    text: str | None = None,
    *,
    tone: Tone = "brand",
    markup: str | None = None,
    margin_top: int = 20,
) -> str:
    """A tinted block for the one sentence a reader must not skim past.

    Pass `text` (escaped here) or `markup` (already escaped by the caller), not both.
    """
    fg, bg, line = _TONES[tone]
    inner = markup if markup is not None else escape(text or "")
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:{margin_top}px 0 0 0;"><tr><td bgcolor="{bg}" style="background-color:{bg};'
        f"border:1px solid {line};border-radius:10px;padding:12px 14px;font-family:{brand.FONT_STACK};"
        f'font-size:13px;line-height:19px;color:{fg};">{inner}</td></tr></table>'
    )


def code_panel(code: str, *, caption: str) -> str:
    """A one-time code, large and monospaced, with its expiry directly underneath.

    `user-select:all` makes one tap select the whole code where the client honours it; the
    digits are never split by spaces or separate cells, because a pasted code with a space
    in it is refused by the input that receives it.
    """
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 20px 0;">'
        f'<tr><td align="center" bgcolor="{brand.BRAND_SOFT}" style="background-color:{brand.BRAND_SOFT};border:1px solid {brand.LINE};border-radius:12px;padding:20px 16px 16px 16px;">'
        f'<div style="font-family:{brand.FONT_MONO};font-size:34px;line-height:40px;font-weight:700;letter-spacing:8px;color:{brand.TEXT};-webkit-user-select:all;user-select:all;">{escape(code)}</div>'
        f'<div style="margin-top:8px;font-family:{brand.FONT_STACK};font-size:13px;line-height:18px;color:{brand.BRAND_STRONG};">{escape(caption)}</div>'
        f"</td></tr></table>"
    )


def divider(*, margin: int = 22) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:{margin}px 0;">'
        f'<tr><td style="border-top:1px solid {brand.LINE};font-size:0;line-height:0;">&nbsp;</td></tr></table>'
    )


def steps(items: Sequence[str]) -> str:
    """A numbered list of already-escaped markup, as table rows.

    Not `<ol>`: Outlook's Word engine indents list markers unpredictably and some clients
    drop the numbers, and in a list of steps the number is the content.
    """
    rows = "".join(
        f'<tr><td valign="top" style="width:26px;padding:0 0 10px 0;font-family:{brand.FONT_STACK};font-size:14px;line-height:21px;font-weight:600;color:{brand.BRAND_STRONG};">{index}.</td>'
        f'<td valign="top" style="padding:0 0 10px 0;font-family:{brand.FONT_STACK};font-size:14px;line-height:21px;color:{brand.TEXT};">{item}</td></tr>'
        for index, item in enumerate(items, start=1)
    )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 6px 0;">{rows}</table>'


def facts(rows: Iterable[tuple[str, str]], *, mono_values: bool = False) -> str:
    """Label/value rows. Labels in a fixed column so the values align and can be scanned."""
    value_font = brand.FONT_MONO if mono_values else brand.FONT_STACK
    body = "".join(
        f'<tr><td valign="top" style="width:118px;padding:5px 12px 5px 0;border-top:1px solid {brand.LINE};font-family:{brand.FONT_STACK};font-size:13px;line-height:19px;color:{brand.TEXT_FAINT};">{escape(label)}</td>'
        f'<td valign="top" style="padding:5px 0;border-top:1px solid {brand.LINE};font-family:{value_font};font-size:13px;line-height:19px;color:{brand.TEXT};word-break:break-all;">{escape(value)}</td></tr>'
        for label, value in rows
    )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 4px 0;">{body}</table>'


def mono_block(text: str) -> str:
    """Free text an operator may need verbatim (a redacted error detail)."""
    return (
        f'<div style="margin:0 0 4px 0;padding:10px 12px;background-color:{brand.APP};border:1px solid {brand.LINE};'
        f"border-radius:8px;font-family:{brand.FONT_MONO};font-size:12px;line-height:18px;color:{brand.TEXT_MUTED};"
        f'white-space:pre-wrap;word-break:break-word;">{escape(text)}</div>'
    )


def inline_code(markup: str) -> str:
    """Wrap already-escaped text as inline code."""
    return (
        f'<code style="font-family:{brand.FONT_MONO};font-size:0.92em;background-color:{brand.APP};'
        f'border:1px solid {brand.LINE};border-radius:4px;padding:0 3px;color:{brand.TEXT};">{markup}</code>'
    )


__all__ = [
    "Tone",
    "badge",
    "button",
    "callout",
    "code_panel",
    "divider",
    "facts",
    "fallback_link",
    "heading",
    "inline_code",
    "mono_block",
    "paragraph",
    "paragraph_html",
    "section_label",
    "shell",
    "steps",
]
