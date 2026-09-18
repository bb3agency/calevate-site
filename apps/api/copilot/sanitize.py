"""Two guards over everything that crosses this seam: invisible characters, and PII.

BOTH RUN IN BOTH DIRECTIONS, and that is the part a reader is most likely to trim.

**Invisible characters** (OWASP GenAI LLM Top 10 2026, LLM01 #5 — "Multimodal and
Invisible Character Injection"). ⚠ **THE PRIMITIVE ITSELF NOW LIVES IN
`calevate_shared.invisible_text` AND THIS MODULE RE-EXPORTS IT** — the in-call knowledge
path needed the same families and had its own partial set, which is two guards over one
attack disagreeing about its membership. Read that module for which family is refused
where and why; the names below keep working so every call site in `apps/api/copilot/`
stays as it was. On the way IN they are a prompt-injection carrier: a
Unicode tag-block sequence is invisible to the human composing a field label and is
ordinary text to a tokenizer, so an attacker-authored knowledge-base title or lead name
rendered into a screen description can carry instructions nobody can see in review. On the
way OUT they are a correctness bug with a security shape: the browser shows a highlighted
PREVIEW of what it is about to write, and an invisible character makes the preview and the
written value different strings. A person approving what they can see is the entire
approval model here, and it fails silently if the two can differ.

**PII** (D-127 G-2). The browser is supposed to substitute placeholders for personal
values and mark those fields `redacted: true`. `assert_redacted` is what makes that a
guarantee rather than a convention: it re-runs `redact()` — the same primitive
`workers/pipeline.py` and `run_assist` use — over the whole assembled payload and refuses
it if anything still matches. `run_assist` wears exactly this belt at
`workers/extraction.py`, for exactly this reason, and that guard caught the mistake its
author predicted in the place predicted.

WHAT THE PII GUARD COSTS, said plainly because it is a real cost and not a footnote: a
person typing their clinic's OWN landline into a form field, with the copilot open, sends
a phone-shaped run of digits and is refused. That is the designed trade — the alternative
is a server that decides for itself which caller data is fine to forward to a US
processor, which is the decision D-127 removed from every surface — and the refusal names
the fix, which is the browser's placeholder substitution.
"""

from __future__ import annotations

from calevate_shared.invisible_text import has_invisible, strip_invisible

from apps.api.core.errors import ProblemError
from apps.workers.redaction import redact

# `_INVISIBLE`, `_STRIP_TABLE`, `strip_invisible` and `has_invisible` MOVED to
# `calevate_shared.invisible_text` (see this module's docstring). Imported rather than
# re-implemented, and re-exported rather than made private, because the callers in this
# package name them by this path and a second spelling of a security primitive is the
# defect that made the move necessary in the first place.


def clean_value(value: str | int | float | bool | None) -> str | int | float | bool | None:
    """A `CopilotValue` with any string half stripped. Non-strings pass through — a bool
    and a float have no invisible half to carry."""
    return strip_invisible(value) if isinstance(value, str) else value


def assert_redacted(*texts: str, authored: bool = False) -> None:
    """Refuse a payload that `redact()` still changes (D-127 G-2).

    THE INPUT GUARD IS THE POINT, and it is structural rather than documentary — the same
    argument `run_assist` makes. A parameter named `redacted` is a promise; this is the
    check. It costs one regex sweep over a screen description and removes the whole class.

    `authored` says WHO is on the other end: `True` when the text was typed by a person
    (the question), `False` when the browser composed it (the screen). It changes only the
    wording — the refusal is identical — because the two audiences can act on completely
    different things.

    AN AUTHORED REFUSAL, NOT AN ASSERTION, and nothing about the text is logged (hard rule
    6): this is reachable by a browser that forgot to substitute a placeholder, and a
    caller mistake deserves a message. The offending value is NOT named in it — naming it
    would put the personal value in a problem body, which is the thing being prevented.
    """
    for text in texts:
        if redact(text).changed:
            raise ProblemError(
                kind="validation",
                code="copilot_input_not_redacted",
                title=(
                    "Take the personal details out of your question"
                    if authored
                    else "This screen has not been redacted"
                ),
                detail=(
                    "The assistant never receives a phone number, an email address or an "
                    "identity number, and something in this request still looks like one."
                ),
                # TWO AUDIENCES, ONE REFUSAL — and the wrong one was being served.
                #
                # This is reachable two ways. A BROWSER that forgot to substitute a
                # placeholder is a defect, and the fix is a code change. But a PERSON who
                # typed "call them back on 98765…" into the ask box is not making a
                # mistake, they are doing the obvious thing, and telling them to "mark
                # those fields `redacted: true`" is telling them nothing they can act on.
                # Every failure path a user can reach needs a message they can act on;
                # every path they cannot reach needs one an operator can.
                remediation=(
                    "Type the number or address straight into the field on the form "
                    "instead — it stays on this device, and you can still ask the "
                    "assistant to fill everything around it."
                    if authored
                    else "Replace personal values with placeholders and mark those "
                    "fields `redacted: true` before asking — the browser substitutes "
                    "the real values back locally."
                ),
            )


__all__ = ["assert_redacted", "clean_value", "has_invisible", "strip_invisible"]
