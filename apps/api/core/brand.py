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

PRODUCT: Final = "Calevate"

__all__ = [
    "APP",
    "BRAND",
    "BRAND_SOFT",
    "BRAND_STRONG",
    "FONT_MONO",
    "FONT_STACK",
    "LINE",
    "PRODUCT",
    "SURFACE",
    "TEXT",
    "TEXT_FAINT",
    "TEXT_MUTED",
]
