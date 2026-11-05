"""A hand-written script's opening line, as the Script tab's own box writes it (A-22).

The box puts the line under the opening heading at the END of the text: the reader takes the
section up to the next bracketed heading, so a heading at the top read the owner's whole
brief below it as the opening line.
"""

from __future__ import annotations

from calevate_shared.call_script import CallScript, compile_call_script, opening_line_of


def test_the_box_written_opening_is_read_as_the_line_alone() -> None:
    raw = "You answer calls for the shop.\nBe brief.\n\n[OPENING]\nHello, how can I help?"
    body = compile_call_script(CallScript(raw_override=raw))
    assert opening_line_of(body) == "Hello, how can I help?"


def test_a_heading_at_the_top_reads_the_whole_brief_which_is_why_the_box_writes_it_last() -> None:
    raw = "[OPENING]\nHello, how can I help?\n\nYou answer calls for the shop."
    assert "You answer calls" in opening_line_of(compile_call_script(CallScript(raw_override=raw)))
