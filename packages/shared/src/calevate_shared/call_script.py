"""The STRUCTURED call-script model and its compiler.

WHY THIS EXISTS. An agent's "script" used to be one thing: a freeform block of text a
human wrote, versioned in `prompt_versions.body`, wrapped by `compose_engine_prompt`
(this package's `engine.py`) with our opening line on top and the non-removable
`TRUTHFUL_ANSWER_DIRECTIVE` underneath. Freeform is the most expressive authoring model
and the worst one to hand a non-writer: there is no shape to guide "what should my agent
actually DO on a call", no place a merge field belongs, and no way for a UI to offer
drag-reorder or an FAQ editor over a wall of prose.

So this module adds the industry-standard STRUCTURED authoring model on top of the SAME
storage — an opening line, ordered natural-language steps, an FAQ with an explicit
"answer only from these" fence, end-call rules, and Liquid-style `{{variable}}` merge
fields — and COMPILES it to exactly the string `compose_engine_prompt` already consumes.
The structured model is the PRIMARY authoring surface; a raw escape hatch
(`raw_override`) keeps the full freeform expressiveness for anyone who needs it and is
also how a pre-existing freeform prompt is represented losslessly (a single freeform
step). There is one compiler and one storage; the two authoring modes are two shapes of
the same `prompt_versions` row, never two systems.

WHERE THE COMPLIANCE FLOOR LIVES, AND WHY IT IS NOT DUPLICATED HERE.
Hard rule 5's `TRUTHFUL_ANSWER_DIRECTIVE` (the one sentence no client may withdraw) is
APPENDED by `compose_engine_prompt`, last, after whatever this compiler produces — that
is the code-level guarantee and it holds for a raw override exactly as for a structured
script, because the compiled body is only ever the MIDDLE of the sandwich. This module
does NOT re-emit that directive (two copies of one rule is the drift this repo treats as
a defect); what it DOES emit, always, is a `[GUARDRAILS]` block restating PROMPT-GUIDE
§1's client-facing invariants and a built-in always-on end-call rule. Those are
structural: no field on `CallScript` can remove them, so "the structured builder can
never drop the disclosure guidance" is a property of `compile_call_script` and not of a
reviewer. `tests/call_script_compile_test.py` proves both halves — the guardrails block
survives any script, and the full engine prompt (compile + compose) always carries
`TRUTHFUL_ANSWER_MARKER` even when the script's own text tries to countermand it.

Pure and dependency-light on purpose: it imports only this package's `engine.py`
constants, so it can be unit-tested without a database, an app import, or a model call —
the same reason `compose_engine_prompt` lives beside it rather than in `apps/api`.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# The merge-field grammar.
# ---------------------------------------------------------------------------
# Liquid's output syntax is `{{ name }}` and it is what every comparable product
# (Bland, Vapi, Retell, Synthflow) exposes to non-technical authors, so it is the
# DEFAULT rather than an invention — a script author who has seen one of those tools
# already knows this. We accept ONLY the bare-variable form: no filters, no dotted
# paths, no logic. A call script is spoken aloud by a voice model in real time; a
# templating language with control flow is a second place for a caller to hear a
# stack trace, and none of the merge data (lead name, phone, product interest) needs
# more than substitution. The regex tolerates surrounding whitespace because a human
# typing `{{ lead_name }}` means the same thing as `{{lead_name}}`.
_VARIABLE_PATTERN: Final = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

#: A variable KEY, as authored and as stored. Lower snake_case, starting with a letter —
#: the same shape a Liquid identifier and a Python/JSON key can both hold, so a key is
#: safe to interpolate into a prompt AND to use as a dict key in `CallContext` merge data
#: without a second escaping rule. Enforced on `ScriptVariable.key` so a malformed key
#: cannot reach the compiler and become a `{{ }}` that never resolves.
_VARIABLE_KEY_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*$")

#: The four merge fields every agent gets for free (the founder's named set), so a new
#: script is useful without anyone defining a variable first. They map to `CallContext`
#: fields / extraction data at dial time — see `substitute_variables`. Clients add their
#: own on top. Kept here, beside the grammar, so the UI's "insert variable" menu and the
#: dial-time substitution read one list.
STANDARD_VARIABLES: Final[tuple[tuple[str, str], ...]] = (
    ("lead_name", "Lead Name"),
    ("phone", "Phone"),
    ("product_interest", "Product Interest"),
    ("delivery_location", "Delivery Location"),
)


def extract_variable_names(text: str) -> list[str]:
    """Every distinct `{{ name }}` used in `text`, in first-seen order.

    First-seen order rather than sorted, so a UI listing "variables this script uses"
    reads top-to-bottom the way the script does. Distinct, because a variable used twice
    is one merge field to define.
    """
    seen: dict[str, None] = {}
    for match in _VARIABLE_PATTERN.finditer(text):
        seen.setdefault(match.group(1), None)
    return list(seen)


def substitute_variables(
    text: str, values: dict[str, str | None], *, keep_unresolved: bool = False
) -> str:
    """Replace `{{ name }}` with `values[name]`. THE dial-time merge step (CallContext).

    `keep_unresolved` is the whole of the difference between the two callers, and it is a
    parameter rather than two functions because the substitution itself is identical:

    - **Dial time (`keep_unresolved=False`, the default).** An unresolved placeholder is
      REMOVED, not left in. `{{ lead_name }}` reaching a live call as those literal
      characters is the agent SPEAKING the template — the worst possible tell that a human
      did not write this — so a variable the lead row cannot fill collapses to nothing and
      the sentence around it still reads. A `None` value (the field exists but is empty for
      this lead) is treated the same as an absent key: both mean "we do not have it".
    - **Preview (`keep_unresolved=True`).** The builder's "view compiled prompt" shows the
      author their own `{{ }}` where a value has not been supplied, because the point of
      the preview is to see the template, not a dry run against one lead.

    Whitespace inside the braces is tolerated and normalised away by the match, so the
    output never depends on whether the author typed `{{lead_name}}` or `{{ lead_name }}`.
    """

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        if value is not None and value != "":
            return value
        return match.group(0) if keep_unresolved else ""

    return _VARIABLE_PATTERN.sub(_replace, text)


# ---------------------------------------------------------------------------
# The structured model.
# ---------------------------------------------------------------------------
#: The don't-know response a fresh FAQ ships with, in Telugu-first phrasing that matches
#: PROMPT-GUIDE §1's truth-boundary pattern verbatim ("నాకు ఆ వివరం ఖచ్చితంగా తెలియదు — మా టీమ్
#: మీకు తిరిగి కాల్ చేస్తుంది."). A client may rewrite it; this is the default so an FAQ is
#: never authored with an empty fence.
DEFAULT_FAQ_FALLBACK: Final = "నాకు ఆ వివరం ఖచ్చితంగా తెలియదు — మా టీమ్ మీకు తిరిగి కాల్ చేసి చెబుతుంది."

#: The always-on end-call rule. Present in EVERY compiled structured script regardless of
#: the client's extra rules, because "end the call cleanly" is not a preference — an agent
#: that never hangs up is a billed minute that runs to the cap on every call. Client extra
#: rules are ADDED to it, never instead of it.
BUILTIN_END_CALL_RULE: Final = (
    "When the caller's need is handled or they ask to stop, end the call politely: "
    "confirm the agreed next step, thank them by name if you have it, and hang up. "
    "Do not keep the caller on the line to fill time."
)

#: The guardrails block, restating PROMPT-GUIDE §1's client-facing invariants. Emitted by
#: the compiler on EVERY structured script, which is what makes it non-removable from the
#: structured surface — there is no `CallScript` field that omits it. It is guidance the
#: model reads in context; the HARD enforcement of the truthful-answer floor is
#: `compose_engine_prompt` appending `TRUTHFUL_ANSWER_DIRECTIVE` after this whole body, so
#: this block deliberately does NOT restate that directive (one rule, one place).
GUARDRAILS_BLOCK: Final = (
    "[GUARDRAILS]\n"
    "- Identify yourself as an AI assistant of the business when you are asked, in the "
    "caller's language, and never claim to be a human being.\n"
    "- Never invent prices, availability, or medical/legal/financial facts. If you do not "
    "know, say so and offer a callback rather than guessing.\n"
    "- If the caller asks you to stop calling, acknowledge it, add them to the do-not-call "
    "list, and confirm — never argue.\n"
    "- Announce any transfer honestly; if a transfer fails, say so and take a callback "
    "rather than pretending a person is coming."
)


#: Ceilings on the authored lists inside one `CallScript`. A script is a hand-curated config
#: document, not a data feed — but every list field here is still CALLER-CONTROLLED, and a
#: response that echoes the stored script (the builder's load/preview/assist reads) is
#: materialised in full, so the count needs a stated bound rather than "authors keep scripts
#: short" (`scripts/check_list_bounds.py`, D-302). These are generous relative to any real
#: script and enforced by `max_length` on the fields below, so the bound is a property of the
#: request model rather than of a reviewer.
MAX_SCRIPT_STEPS: Final = 100
MAX_SCRIPT_FAQS: Final = 200
MAX_SCRIPT_VARIABLES: Final = 100
MAX_END_CALL_RULES: Final = 100


class ScriptVariable(BaseModel):
    """One `{{ }}` merge field the author has declared, with the label the UI shows.

    `key` is what appears in the script text; `label` is the human name in the insert
    menu; `example` is an optional sample value the preview can substitute so an author
    sees a realistic sentence rather than `{{ }}`. Declaring a variable does not make it
    resolve at dial time — that depends on the lead/extraction data — it only makes it
    offerable in the editor and documentable in the preview.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    example: str = Field(default="", max_length=200)

    @field_validator("key")
    @classmethod
    def _key_is_a_liquid_identifier(cls, value: str) -> str:
        if not _VARIABLE_KEY_PATTERN.match(value):
            raise ValueError(
                "a variable key must be lower snake_case starting with a letter "
                "(e.g. lead_name), so it is a valid merge field in both the script and the "
                "lead data"
            )
        return value


class ScriptStep(BaseModel):
    """One ordered instruction in the task flow — a natural-language sentence, not code.

    PROMPT-GUIDE §2/§4 are explicit that a task flow is a LOOSE outline of hints, not a
    rigid line-by-line script ("rigid scripts sound robotic and break on interruptions"),
    so a step is prose the model follows in spirit, and reordering steps reorders the
    outline. Supports `{{ variables }}` like every other authored field.
    """

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=1000)


class FaqEntry(BaseModel):
    """One question/answer pair the agent may answer from directly.

    The FAQ is fenced — the compiler tells the model to answer ONLY from these answers and
    to use the don't-know response otherwise — so an entry is a fact the client has
    authorised the agent to state, which is exactly the truth-boundary PROMPT-GUIDE §1.2
    draws. Both sides support `{{ variables }}`.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)


class CallScript(BaseModel):
    """A whole agent script, structured — or a raw escape hatch, never both at once.

    ONE MODEL, TWO SHAPES. `raw_override` is the escape hatch AND the lossless
    representation of a legacy freeform prompt: when it is set, the compiler returns it
    verbatim and the structured fields are ignored, so nothing an author wrote in raw mode
    is reinterpreted, and a pre-structured `prompt_versions.body` round-trips exactly (see
    `from_freeform`). When it is None, the structured fields compile. A model validator
    forbids the ambiguous middle — structured content AND a raw override — because a row
    that is half one and half the other has no single answer to "what does this compile
    to".

    The `opening_line` here is the CLIENT's opener and is distinct from the compliance
    opening: `compose_opening_line` composes the AI-disclosure / recording notices
    separately from the agent's two toggles, and the adapter speaks THAT first; this line
    follows it. Keeping them apart is D-163 — the notices are a regulated obligation with
    its own switches, not something a script author edits as free text.
    """

    model_config = ConfigDict(extra="forbid")

    opening_line: str = Field(default="", max_length=1000)
    steps: list[ScriptStep] = Field(default_factory=list, max_length=MAX_SCRIPT_STEPS)
    faqs: list[FaqEntry] = Field(default_factory=list, max_length=MAX_SCRIPT_FAQS)
    faq_fallback: str = Field(default=DEFAULT_FAQ_FALLBACK, min_length=1, max_length=500)
    end_call_extra_rules: list[str] = Field(default_factory=list, max_length=MAX_END_CALL_RULES)
    variables: list[ScriptVariable] = Field(default_factory=list, max_length=MAX_SCRIPT_VARIABLES)
    #: The raw escape hatch. `None` = structured mode. A string (including "") = raw mode:
    #: the compiler returns it unchanged. Legacy freeform prompts live here.
    raw_override: str | None = Field(default=None, max_length=20000)

    @field_validator("end_call_extra_rules")
    @classmethod
    def _rules_are_one_per_line(cls, value: list[str]) -> list[str]:
        # Each entry is one rule. A newline inside an entry would compile to a bullet that
        # spans lines and reads as two rules under one dash — the client authored "one per
        # line", so a stray newline is split rather than smuggled through.
        out: list[str] = []
        for rule in value:
            out.extend(part.strip() for part in rule.splitlines() if part.strip())
        return out

    @model_validator(mode="after")
    def _one_mode_at_a_time(self) -> CallScript:
        """Raw mode OR structured content, never both — the ambiguous middle is refused.

        A row carrying a `raw_override` AND authored steps/faqs/opening has no single
        answer to "what does this compile to" (the compiler would silently drop the
        structured half), so it is a shape a client cannot save rather than one that
        quietly loses their work. Switching modes in the UI clears the other side; this
        validator is what makes that a guarantee instead of a convention.
        """
        if self.raw_override is not None and (
            self.opening_line.strip()
            or self.steps
            or self.faqs
            or self.end_call_extra_rules
            or self.variables
        ):
            raise ValueError(
                "a script is either raw (raw_override set) or structured (steps/faqs/etc.), "
                "not both — clear one side before saving"
            )
        return self

    @property
    def is_raw(self) -> bool:
        return self.raw_override is not None

    @classmethod
    def from_freeform(cls, body: str) -> CallScript:
        """Represent an existing freeform prompt losslessly, as a raw-mode script.

        THE MIGRATION PATH for every `prompt_versions` row written before the structured
        model existed: they carry a `body` and no `structured_script`, and this is how the
        builder loads one without rewriting it. It compiles back to exactly `body`, so
        opening the builder on a legacy agent and saving without edits is a no-op on the
        engine prompt — nothing a human wrote is lost or reinterpreted.
        """
        return cls(raw_override=body)


def compile_call_script(script: CallScript) -> str:
    """THE pure function: a structured script (or raw override) to a system-prompt string.

    Consumed by `compose_engine_prompt`, which wraps this with the opening line on top and
    `TRUTHFUL_ANSWER_DIRECTIVE` underneath — so this returns the MIDDLE of that sandwich,
    the client body, never the whole engine prompt. That separation is what lets a raw
    override be returned verbatim while the compliance floor still rides every call: the
    floor is appended by the composer, not by this function, on both modes alike.

    Section order follows PROMPT-GUIDE §2 (the template order that helps TTFT and
    adherence): opening, task flow, FAQ, end-call, guardrails. Empty sections are omitted
    so an agent with no FAQ does not carry an empty `[FAQ]` header — a difference in the
    compiled string that has nothing to do with what was authored is exactly what makes a
    read-back containment check harder to reason about (`compose_engine_prompt`'s own
    argument for dropping empty limbs).
    """
    if script.raw_override is not None:
        # Raw mode: the author's text is the body, untouched. The compliance floor is still
        # appended by `compose_engine_prompt`, so even a raw script cannot drop it.
        return script.raw_override

    sections: list[str] = []

    opening = script.opening_line.strip()
    if opening:
        sections.append(f"[OPENING]\n{opening}")

    steps = [step.instruction.strip() for step in script.steps if step.instruction.strip()]
    if steps:
        numbered = "\n".join(f"{i}. {instruction}" for i, instruction in enumerate(steps, 1))
        sections.append(
            "[TASK FLOW] Follow these as a loose outline, one thing at a time. They are "
            "hints, not a rigid script — adapt to what the caller actually says.\n" + numbered
        )

    faqs = [
        (faq.question.strip(), faq.answer.strip())
        for faq in script.faqs
        if faq.question.strip() and faq.answer.strip()
    ]
    if faqs:
        pairs = "\n".join(f"Q: {question}\nA: {answer}" for question, answer in faqs)
        sections.append(
            "[FAQ] Answer these questions ONLY from the answers written here. If the caller "
            "asks something these do not cover, do not guess — say: "
            f'"{script.faq_fallback.strip()}"\n{pairs}'
        )

    # The built-in rule is always first; client extra rules follow. `_rules_are_one_per_line`
    # has already split and trimmed, so every entry is a single clean rule.
    end_rules = [BUILTIN_END_CALL_RULE, *script.end_call_extra_rules]
    sections.append("[END CALL]\n" + "\n".join(f"- {rule}" for rule in end_rules))

    # Always last, always present — the non-removable client-facing guardrails.
    sections.append(GUARDRAILS_BLOCK)

    return "\n\n".join(sections)


__all__ = [
    "BUILTIN_END_CALL_RULE",
    "DEFAULT_FAQ_FALLBACK",
    "GUARDRAILS_BLOCK",
    "STANDARD_VARIABLES",
    "CallScript",
    "FaqEntry",
    "ScriptStep",
    "ScriptVariable",
    "compile_call_script",
    "extract_variable_names",
    "substitute_variables",
]
