"""One GST sentence, in both languages, on every client surface (D-659).

The server puts `gst.GST_STATUS_SENTENCE` on the statement's tax note and on the payment
receipt; the console and the marketing pages import the same words from
`apps/web/src/lib/gstStatus.ts`. Two copies are unavoidable across two languages, so this
test is what makes them one: it fails the moment they differ.

Run: uv run pytest -q tests/gst_status_test.py
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.api.billing.gst import GST_STATUS_SENTENCE, SupplierIdentity
from apps.api.billing.invoice import BILL_OF_SUPPLY_TAX_NOTE
from apps.api.billing.wallet_routes import RECEIPT_NOTE

WEB_CONSTANT = Path(__file__).resolve().parents[1] / "apps/web/src/lib/gstStatus.ts"


def _web_sentence() -> str:
    source = WEB_CONSTANT.read_text(encoding="utf-8")
    match = re.search(r'export const GST_STATUS_SENTENCE\s*=\s*"([^"]*)";', source)
    assert match, f"{WEB_CONSTANT} no longer declares GST_STATUS_SENTENCE as one string"
    return match.group(1)


def test_the_console_and_the_server_say_the_same_sentence() -> None:
    assert _web_sentence() == GST_STATUS_SENTENCE


def test_the_documents_a_client_keeps_carry_the_sentence() -> None:
    assert GST_STATUS_SENTENCE in BILL_OF_SUPPLY_TAX_NOTE
    assert GST_STATUS_SENTENCE in RECEIPT_NOTE


def test_the_sentence_names_no_setting_and_no_figure() -> None:
    """It is read by clients: no internals, and no threshold figure that was only
    REPORTED (founder-relayed, secondary sources; not read from the CGST Act here)."""
    nothing = SupplierIdentity(legal_name=None, address=None, gstin=None, sac=None)
    assert nothing.missing, "the operator signal must still name the settings"
    for internal in nothing.missing:
        assert internal not in GST_STATUS_SENTENCE
    assert "lakh" not in GST_STATUS_SENTENCE.lower()
    assert not re.search(r"\d", GST_STATUS_SENTENCE)
