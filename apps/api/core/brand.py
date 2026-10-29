"""The brand, in the one form an email client can read.

`apps/web/src/app/globals.css` is where these values live for every SCREEN, and no screen
hardcodes a hex. An email cannot read that file — it has no stylesheet, no cascade worth
relying on, and no build step — so the values are restated here, once, with the CSS
custom property each one mirrors named beside it. `tests/brand_tokens_test.py` reads both
files and fails if they drift, which is what keeps this from becoming the second palette.

**WHY NOT PP MORI.** The product's typeface is a licensed local font served by
`next/font/local`. Email clients do not load `@font-face` reliably — Gmail's web client
strips it outright — and hosting the file to try would put a licensed font on a public URL.
So the mail uses a system stack chosen to sit in the same place: a neutral geometric
grotesque, no serifs, no personality that fights the wordmark. It will not be PP Mori, and
pretending otherwise with a webfont link that silently fails is worse than choosing the
fallback deliberately.
"""

from __future__ import annotations

from typing import Final

from apps.api.core.console_links import DOMAIN as _DOMAIN

#: Mirrors `--brand` — the resting green.
BRAND: Final = "#16a05d"
#: Mirrors `--brand-strong` — the primary button.
BRAND_STRONG: Final = "#0f6b3d"
#: Mirrors `--brand-soft` — the tint behind icon medallions and callouts.
BRAND_SOFT: Final = "#eaf8f0"
#: Mirrors `--app` — the page behind the cards.
APP: Final = "#fafafa"
#: Mirrors `--surface` — the card itself.
SURFACE: Final = "#ffffff"
#: Mirrors `--line` — hairline borders.
LINE: Final = "#e2e8f0"
#: Mirrors `--text`, `--text-muted`, `--text-faint`. All three carry small text on the
#: web and are held to WCAG 1.4.3 AA against `--surface`; the same holds in mail, where
#: the background is the same white.
TEXT: Final = "#171a1c"
TEXT_MUTED: Final = "#475569"
TEXT_FAINT: Final = "#64748b"
#: Mirror `--danger`, `--danger-soft`, `--danger-line`: the state that needs action now.
DANGER: Final = "#be123c"
DANGER_SOFT: Final = "#fff1f2"
DANGER_LINE: Final = "#fecdd3"
#: Mirror `--warn`, `--warn-soft`, `--warn-line`: a caution worth reading, not an outage.
WARN: Final = "#92400e"
WARN_SOFT: Final = "#fffbeb"
WARN_LINE: Final = "#fde68a"

#: The body stack. `-apple-system` and `BlinkMacSystemFont` resolve to SF/Segoe on the
#: two clients that render most of our mail; `Helvetica Neue` and `Arial` cover the rest
#: without reaching for a serif, which is what a bare `sans-serif` gets on some Windows
#: configurations.
FONT_STACK: Final = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Helvetica, Arial, sans-serif"
)
#: For codes, tokens and anything a person retypes. Same reasoning as the console's
#: JetBrains Mono: the glyphs that collide (0/O, 1/l/I) must not.
FONT_MONO: Final = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

# --- The name, the domain and the company, ONE place each (D-933, docs/REBRAND-MAP.md) ---
#
# Every email names the product and links to its hosts through these, never through a
# literal: `tests/email_brand_guard_test.py` refuses "Calevate" or "calevate.tech" written
# into an email module, so a rename is these lines and `console_links.DOMAIN`.

#: The product name, as every email prints it.
PRODUCT: Final = "Calevate"
#: The one-line description under the name in an email footer.
TAGLINE: Final = "AI voice agents for Indian businesses."
#: The registrable domain, defined in `core/console_links` with the hosts under it.
DOMAIN: Final = _DOMAIN
#: The logo an email header shows (served by the web app from `apps/web/public/brand/`).
#: Absolute, because a mail client has no base URL to resolve a relative one against.
LOGO_URL: Final = f"https://app.{DOMAIN}/brand/calevate-full-logo-without-tagline.png"

#: MIRROR `LEGAL_ENTITY_NAME` and `REGISTERED_ADDRESS` in
#: `apps/web/src/lib/legal/placeholders.ts`, the values the legal pages publish, so an email
#: footer and the Terms name the same supplier in the same words. `tests/brand_tokens_test.py`
#: reads both files and fails when they differ. City level only, never a street (4 Sep 2026).
LEGAL_ENTITY_NAME: Final = "Calevate"
REGISTERED_ADDRESS: Final = "Guntur, Andhra Pradesh, India"

__all__ = [
    "APP",
    "BRAND",
    "BRAND_SOFT",
    "BRAND_STRONG",
    "DANGER",
    "DANGER_LINE",
    "DANGER_SOFT",
    "DOMAIN",
    "FONT_MONO",
    "FONT_STACK",
    "LEGAL_ENTITY_NAME",
    "LINE",
    "LOGO_URL",
    "PRODUCT",
    "REGISTERED_ADDRESS",
    "SURFACE",
    "TAGLINE",
    "TEXT",
    "TEXT_FAINT",
    "TEXT_MUTED",
    "WARN",
    "WARN_LINE",
    "WARN_SOFT",
]
