"""Invisible characters, stripped in both directions across this seam.

BOTH DIRECTIONS, and that is the part a reader is most likely to trim (OWASP GenAI LLM Top
10 2026, LLM01 #5 — "Multimodal and Invisible Character Injection"). The primitive lives in
`calevate_shared.invisible_text` and this module re-exports it: the in-call knowledge path
needed the same families, and two guards over one attack disagreeing about its membership
is the defect that move fixed. On the way IN they are a prompt-injection carrier: a Unicode
tag-block sequence is invisible to the human composing a field label and is ordinary text
to a tokenizer, so an attacker-authored knowledge-base title or lead name rendered into a
screen description can carry instructions nobody can see in review. On the way OUT they are
a correctness bug with a security shape: the browser shows a highlighted PREVIEW of what it
is about to write, and an invisible character makes the preview and the written value
different strings. A person approving what they can see is the entire approval model here,
and it fails silently if the two can differ.

PERSONAL DETAILS ARE NOT THIS MODULE'S SUBJECT ANY MORE (D-788). It used to refuse a
question that still matched `redact()` (D-127 G-2), which told a person who typed "call
this number 98765…" to take the number out. The founder replaced that with consent: a
client account's owner turns Pip on once (`consent.py`), after which what the person types
reaches Pip's model as typed, and the admin console was never asked. Where masking still
applies is named in `consent.py`.
"""

from __future__ import annotations

from calevate_shared.invisible_text import has_invisible, strip_invisible


def clean_value(value: str | int | float | bool | None) -> str | int | float | bool | None:
    """A `CopilotValue` with any string half stripped. Non-strings pass through — a bool
    and a float have no invisible half to carry."""
    return strip_invisible(value) if isinstance(value, str) else value


__all__ = ["clean_value", "has_invisible", "strip_invisible"]
