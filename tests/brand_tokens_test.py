"""The email palette must be the SAME palette, and a second copy is how it stops being.

`apps/web/src/app/globals.css` is the one place a screen reads a colour from — its own
docstring says a literal hex is how a design language decays, and the tokens are named for
their role so a rebrand is one edit.

An email cannot read that file: no stylesheet, no cascade worth trusting, no build step.
So `apps/api/core/brand.py` restates the values, which creates exactly the drift the CSS
file was written to prevent — unless something checks. This is that something.

It reads BOTH files and compares. A rebrand that touches only the CSS turns this red, and
the fix is the one-line edit in `brand.py`, not a widened test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from apps.api.core import brand

CSS = Path(__file__).resolve().parents[1] / "apps/web/src/app/globals.css"

#: `brand.py` constant -> the CSS custom property it mirrors. Kept as data so a new token
#: is one row, and so the failure message can name both sides.
MIRRORED: tuple[tuple[str, str], ...] = (
    ("BRAND", "--brand"),
    ("BRAND_STRONG", "--brand-strong"),
    ("BRAND_SOFT", "--brand-soft"),
    ("APP", "--app"),
    ("SURFACE", "--surface"),
    ("LINE", "--line"),
    ("TEXT", "--text"),
    ("TEXT_MUTED", "--text-muted"),
    ("TEXT_FAINT", "--text-faint"),
)


def _css_tokens() -> dict[str, str]:
    """`--brand: #16a05d;` -> {"--brand": "#16a05d"}, from the `:root` block only.

    The `.dark` block is still in that file (D-471 keeps it rather than deleting 429
    unreachable variants), and reading a value out of it would silently give the email a
    colour no user can see on the web.
    """
    text = CSS.read_text(encoding="utf-8")
    root = text[text.index(":root {") : text.index("}", text.index(":root {"))]
    return {
        name: value.strip().lower()
        for name, value in re.findall(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", root)
    }


def test_the_css_still_declares_the_tokens_this_guard_reads() -> None:
    """The premise. FAILS IF: `:root` moves, or a token is renamed — either of which would
    otherwise make every comparison below vacuously pass on an empty dict."""
    tokens = _css_tokens()
    assert len(tokens) >= 9, f"only {len(tokens)} tokens parsed from globals.css: {tokens}"
    for _, css_name in MIRRORED:
        assert css_name in tokens, f"{css_name} is gone from :root — brand.py mirrors a ghost"


@pytest.mark.parametrize(("attr", "css_name"), MIRRORED)
def test_every_email_colour_matches_the_screen_it_came_from(attr: str, css_name: str) -> None:
    css_value = _css_tokens()[css_name]
    py_value = getattr(brand, attr).lower()
    assert py_value == css_value, (
        f"brand.{attr} is {py_value} but {css_name} is {css_value} in globals.css. The "
        "email and the console are now two different greens; fix brand.py, never this test."
    )
