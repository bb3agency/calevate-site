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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

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


#: The header the compiler puts above the opening line. A section runs from its header line
#: to the next line starting with `[` (PROMPT-GUIDE §2, `apps/api/agents/t0_block.py`).
OPENING_HEADER: Final = "[OPENING]"


def opening_line_of(body: str | None) -> str:
    """The opening line inside a compiled script body, or "" when it has none.

    The inverse of the compiler's first section, read from the body rather than from the
    stored `CallScript` because the body is what every publish path holds — the agent's
    applied version, an experiment arm's version, the builder's unsaved preview — so one
    reader serves all of them. A raw-mode script has an opening only if its author wrote
    the same section; otherwise the agent has no opening line of its own.
    """
    if not body:
        return ""
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == OPENING_HEADER), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    return "\n".join(lines[start + 1 : end]).strip()


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


# ---------------------------------------------------------------------------
# Script model v2 (first live call review, 10 Oct 2026, F-8).
# ---------------------------------------------------------------------------
# The v1 shape (opening, steps, FAQ, end-call rules) had no identity, no goal, no stages
# with exit conditions, no objections, no policies tied to what the account can do and no
# spoken samples. v2 adds those sections, following the published structure for voice
# agent prompts — OpenAI's Realtime prompting guide (role and objective, personality and
# tone, language, sample phrases, conversation flow as states with exit criteria,
# pronunciations), ElevenLabs' prompting guide (identity, goal, tone, guardrails, tools,
# character normalisation) and Vapi's (sections, one question at a time, explicit end
# conditions). v1 scripts keep `schema_version == 1` and compile exactly as before.

#: The version a new script is written in. A v1 script stays v1 until it is saved from the
#: v2 builder, so nothing already published changes without somebody saving it.
SCRIPT_SCHEMA_VERSION: Final = 2

#: Twelve because ThinnestAI's native `steps` holds at most twelve (snapshots/2026-10-08/
#: pages/api-reference/agents/update-agent.md:588-595), and a script has one shape on every
#: engine.
MAX_SCRIPT_STAGES: Final = 12
#: ThinnestAI cuts a step's title at 80 and its detail at 600 characters
#: (update-agent.md:865-905); the builder refuses longer rather than letting text vanish.
STAGE_TITLE_MAX: Final = 80
STAGE_DETAIL_MAX: Final = 600
MAX_STAGE_BRANCHES: Final = 6
MAX_STAGE_COLLECT: Final = 10
#: Branch targets that are not a section: end the call, hand the caller to a person, or
#: offer a call back. The last two become what the account can actually do at publish
#: (`native_steps`), so a trial agent's "call back" branch never promises one.
END_OF_CALL: Final = "end"
HAND_OVER: Final = "hand_over"
CALL_BACK: Final = "call_back"
SPECIAL_TARGETS: Final = frozenset({END_OF_CALL, HAND_OVER, CALL_BACK})
#: A section id: stable across edits and reorders, so branches and the canvas survive them.
SECTION_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9_-]{0,39}$"
SOUNDS_LIKE_MAX: Final = 200
MAX_SCRIPT_OBJECTIONS: Final = 30
MAX_SAMPLE_PHRASES: Final = 20
MAX_PRONUNCIATIONS: Final = 50
MAX_EXAMPLE_TURNS: Final = 20

#: The section headers v2 compiles to. The owned runtime's output guard treats the spoken
#: ones as words the agent is meant to say (`voice_worker/output_guard._SPOKEN_SECTIONS`).
BUSINESS_HEADER: Final = "[BUSINESS]"
STYLE_HEADER: Final = "[SPEAKING STYLE]"
EXAMPLE_HEADER: Final = "[EXAMPLE CALL]"
QUICK_FACTS_HEADER: Final = "[QUICK FACTS]"
QUICK_FACTS_LEAD: Final = f"{QUICK_FACTS_HEADER} These win over anything in your knowledge."
#: The section a v1 script compiled its FAQ under. Splicing pinned facts drops it, so a v1
#: agent never carries the old FAQ beside the business's quick facts.
V1_FAQ_HEADER: Final = "[FAQ]"


def quick_fact_lines(facts: Sequence[tuple[str, str]]) -> str:
    """Quick facts as lines: `Q:`/`A:` for a question and answer, `- ` for a statement."""
    lines: list[str] = []
    for question, answer in facts:
        if not answer.strip():
            continue
        lines.append(
            f"Q: {question.strip()}\nA: {answer.strip()}"
            if question.strip()
            else f"- {answer.strip()}"
        )
    return "\n".join(lines)


def splice_quick_facts(
    body: str | None, facts: Sequence[tuple[str, str]], *, before: str = "[T0 FACTS]"
) -> str:
    """`body` carrying exactly `facts` as its quick-facts section.

    Pinned facts belong to the client, not to one script (founder decision 9), so they are
    spliced into every agent's compiled body rather than authored in it. Any quick-facts or
    v1 FAQ section already there is removed; the new one goes where the old one was, else
    before `before` (the platform's facts block), else at the end. A section runs to the next
    line starting with `[`, the rule the T0 splicer follows. Pure, so the save, the preview
    and the recompile produce the same text.
    """
    headers = (QUICK_FACTS_HEADER, V1_FAQ_HEADER)
    kept: list[str] = []
    at: int | None = None
    skipping = False
    for line in (body or "").splitlines():
        if line.startswith("["):
            skipping = line.startswith(headers)
            if skipping and at is None:
                at = len(kept)
        if not skipping:
            kept.append(line)
    if at is None:
        at = next((i for i, line in enumerate(kept) if line.startswith(before)), len(kept))
    head, tail = kept[:at], kept[at:]
    while head and not head[-1].strip():
        head.pop()
    while tail and not tail[0].strip():
        tail.pop(0)
    lines = quick_fact_lines(facts)
    middle = [QUICK_FACTS_LEAD, *lines.splitlines()] if lines else []
    parts: list[list[str]] = [part for part in (head, middle, tail) if part]
    return "\n\n".join("\n".join(part) for part in parts)


#: The policy line that withholds call backs. `engine.compose_engine_prompt`'s account
#: block offers a call back only when the account can keep it AND the script does not carry
#: this line (`call_backs_withheld`), so the two can never contradict each other.
NO_CALL_BACKS_POLICY: Final = "Do not offer call backs."

CodeMix = Literal["light", "natural", "heavy"]
CODE_MIX_SENTENCES: Final[dict[str, str]] = {
    "light": "Use mostly the caller's language, with an English word only where people "
    "would not know another one.",
    "natural": "Mix in the English words people use every day (order, delivery, price, "
    "booking, time), the way callers here talk.",
    "heavy": "Mix English freely into every sentence, the way young city callers talk.",
}


class Pronunciation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=80)
    say_as: str = Field(min_length=1, max_length=120)


class SpeakingStyle(BaseModel):
    """How the agent sounds: tone, how it addresses callers, how much English it mixes in,
    phrases it may use and how to say difficult words."""

    model_config = ConfigDict(extra="forbid")

    tone: str = Field(default="", max_length=300)
    address_form: str = Field(default="", max_length=200)
    code_mix: CodeMix = "natural"
    sample_phrases: list[str] = Field(default_factory=list, max_length=MAX_SAMPLE_PHRASES)
    pronunciations: list[Pronunciation] = Field(default_factory=list, max_length=MAX_PRONUNCIATIONS)

    @field_validator("sample_phrases")
    @classmethod
    def _phrases_are_short_lines(cls, value: list[str]) -> list[str]:
        out = [" ".join(p.split())[:200] for p in value if p.strip()]
        return out


class CanvasPosition(BaseModel):
    """Where a section sits on the builder's canvas. Layout only: never compiled."""

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class StageBranch(BaseModel):
    """ "When <condition>, go to <target>": a section id, or one of `SPECIAL_TARGETS`."""

    model_config = ConfigDict(extra="forbid")

    when: str = Field(min_length=1, max_length=300)
    target: str = Field(min_length=1, max_length=40)


class ConversationStage(BaseModel):
    """One section of the call, a node of the script's section graph.

    The list order is the call order. `mode` "say" asks for `instruction` to be said as
    written (best effort: only the opening line is guaranteed verbatim). `sounds_like` is an
    optional line in the call's language showing how it sounds. `branches` are the ways out
    on a condition, `otherwise` where to go when none holds (empty: the next section), and
    `collect` what must be in hand first. `position` is the canvas layout and is never
    compiled. Instruction and sounds-like share ThinnestAI's 600-character step detail.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40, pattern=SECTION_ID_PATTERN)
    name: str = Field(min_length=1, max_length=STAGE_TITLE_MAX)
    mode: Literal["guide", "say"] = "guide"
    instruction: str = Field(min_length=1, max_length=STAGE_DETAIL_MAX)
    sounds_like: str = Field(default="", max_length=SOUNDS_LIKE_MAX)
    branches: list[StageBranch] = Field(default_factory=list, max_length=MAX_STAGE_BRANCHES)
    otherwise: str = Field(default="", max_length=40)
    collect: list[str] = Field(default_factory=list, max_length=MAX_STAGE_COLLECT)
    position: CanvasPosition | None = None

    @field_validator("collect")
    @classmethod
    def _collect_is_short_labels(cls, value: list[str]) -> list[str]:
        return [" ".join(v.split())[:80] for v in value if v.strip()]

    @model_validator(mode="after")
    def _detail_fits_a_step(self) -> ConversationStage:
        if len(_stage_detail(self)) > STAGE_DETAIL_MAX:
            raise ValueError(
                f"section {self.name!r}: the instruction and how it sounds together must fit "
                f"in {STAGE_DETAIL_MAX} characters"
            )
        return self


class Objection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objection: str = Field(min_length=1, max_length=300)
    response: str = Field(min_length=1, max_length=1000)


class ScriptPolicies(BaseModel):
    """What the business allows its agent to do. Call backs are also bounded by what the
    account can do (a trial cannot, D-697), which the platform enforces after the script."""

    model_config = ConfigDict(extra="forbid")

    offer_call_backs: bool = True
    share_prices: bool = True
    take_bookings: bool = True


class ExampleLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Literal["caller", "agent"]
    text: str = Field(min_length=1, max_length=500)


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

    The `opening_line` here is the agent's GREETING, the client's own words, and it is a
    separate thing from the two notices (D-163, D-708). The notices are composed by
    `compose_opening_line` from the agent's two switches; a notice that is switched on is
    said before this line, and with both off this line is the first thing a caller hears.
    No switch adds, removes or replaces it. `engine.compose_first_utterance` joins the two
    for an engine that speaks one greeting field.
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
    #: 1 for every script saved before 10 Oct 2026; such a script compiles exactly as it
    #: always did. 2 adds the sections below.
    schema_version: Literal[1, 2] = 1
    #: One line on what the business is. Also the engine's own business line where it has
    #: one (ThinnestAI `businessDescription`, at most 200 characters, update-agent.md:531).
    business_line: str = Field(default="", max_length=200)
    #: Who the agent is and its role.
    identity: str = Field(default="", max_length=1000)
    goal: str = Field(default="", max_length=1000)
    #: Outbound only: why we are calling, said early in the call.
    outbound_purpose: str = Field(default="", max_length=300)
    style: SpeakingStyle = Field(default_factory=SpeakingStyle)
    stages: list[ConversationStage] = Field(default_factory=list, max_length=MAX_SCRIPT_STAGES)
    objections: list[Objection] = Field(default_factory=list, max_length=MAX_SCRIPT_OBJECTIONS)
    policies: ScriptPolicies = Field(default_factory=ScriptPolicies)
    ending: str = Field(default="", max_length=1000)
    example_exchange: list[ExampleLine] = Field(default_factory=list, max_length=MAX_EXAMPLE_TURNS)
    #: The example was drafted by AI (a starter or the script assistant) and no native
    #: speaker has read it yet. The builder says so; editing the example clears it.
    example_needs_review: bool = False
    #: How closely the agent follows the sections (founder: two options only).
    adherence: Literal["flexible", "strict"] = "flexible"

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
            or self.has_v2_content
        ):
            raise ValueError(
                "a script is either raw (raw_override set) or structured (steps/faqs/etc.), "
                "not both — clear one side before saving"
            )
        ids = [stage.id for stage in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("each section needs its own id, so a branch can point at it")
        targets = set(ids) | SPECIAL_TARGETS
        for stage in self.stages:
            for target in [stage.otherwise, *(b.target for b in stage.branches)]:
                if target and target not in targets:
                    raise ValueError(
                        f"section {stage.name!r} goes to {target!r}, which is not a section"
                    )
        if self.schema_version == 1 and self.has_v2_content:
            # A v1 script compiles without these sections, so accepting them would store
            # content the agent never receives.
            raise ValueError(
                "the identity, goal, stages and other new sections need schema_version 2"
            )
        return self

    @property
    def is_raw(self) -> bool:
        return self.raw_override is not None

    @property
    def has_v2_content(self) -> bool:
        return bool(
            self.business_line.strip()
            or self.identity.strip()
            or self.goal.strip()
            or self.outbound_purpose.strip()
            or self.style != SpeakingStyle()
            or self.stages
            or self.objections
            or self.policies != ScriptPolicies()
            or self.ending.strip()
            or self.example_exchange
            or self.adherence != "flexible"
        )

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


@dataclass(frozen=True, slots=True)
class CollectField:
    """One detail the agent asks for, from the agent's extraction schema (PROMPT-GUIDE §4).
    Read-only in the builder: the schema is edited on its own screen."""

    label: str
    reason: str = ""
    required: bool = False


CONVERSATION_HEADER: Final = "[CONVERSATION]"
ADHERENCE_SENTENCES: Final[dict[str, str]] = {
    "flexible": "Sections in order as a guide. Follow the caller if they jump ahead; do not "
    "repeat a section that is done.",
    "strict": "Go through the sections in this order and say the quoted lines as written.",
}


def _stage_detail(stage: ConversationStage) -> str:
    text = " ".join(stage.instruction.split())
    detail = f"Say: {_quote(text)}" if stage.mode == "say" else text
    if stage.sounds_like.strip():
        detail += f" It sounds like: {_quote(stage.sounds_like)}"
    return detail


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What the account can do when the script is compiled for a call. Unknown at save
    time (text compile), known at publish (`native_steps`)."""

    call_backs: bool | None = None
    hand_over: bool | None = None


def _target_action(target: str, names: dict[str, str], can: Capabilities) -> str:
    if target == END_OF_CALL:
        return "End the call politely"
    if target == HAND_OVER:
        if can.hand_over is False:
            return "Say nobody can take the call right now"
        return "Hand the caller to a person"
    if target == CALL_BACK:
        if can.call_backs is False:
            return "Say the business will get back to them"
        return "Offer a call back"
    return f"Go to '{names.get(target, target)}'"


def _stage_exits(
    stage: ConversationStage, names: dict[str, str], can: Capabilities
) -> list[tuple[str, str]]:
    """(when, action) pairs: the branches, then "Otherwise" when it is set."""

    def condition(text: str) -> str:
        return text.strip().rstrip(".").strip()

    exits = [(condition(b.when), _target_action(b.target, names, can)) for b in stage.branches]
    if stage.otherwise:
        exits.append(("Otherwise", _target_action(stage.otherwise, names, can)))
    return exits


def _stage_line(stage: ConversationStage, names: dict[str, str]) -> str:
    line = f"{stage.name.strip()}: {_stage_detail(stage)}"
    if stage.collect:
        line += f" Have in hand first: {', '.join(stage.collect)}."
    for when, action in _stage_exits(stage, names, Capabilities()):
        line += f" {when}: {action}." if when == "Otherwise" else f" When {when}: {action}."
    return line


@dataclass(frozen=True, slots=True)
class NativeStep:
    """One section in the shape an engine with its own step list takes (ThinnestAI `steps`).
    Ours, not a vendor's: the adapter maps it to the wire."""

    title: str
    detail: str
    branches: tuple[tuple[str, str], ...] = ()
    collect: tuple[str, ...] = ()


def native_steps(script: CallScript, *, can: Capabilities | None = None) -> tuple[NativeStep, ...]:
    """The script's sections as engine steps, or () when it has none to send that way.

    `can` turns a "hand over" or "call back" branch into what the account can do now. v2
    sections map one to one. A v1 script's steps map as untitled steps. A raw script, or a v1
    script with more steps than an engine step list holds, has none: its outline stays in the
    instructions text.
    """
    if script.is_raw:
        return ()
    can = can or Capabilities()
    if script.schema_version == SCRIPT_SCHEMA_VERSION:
        names = {stage.id: stage.name.strip() for stage in script.stages}
        return tuple(
            NativeStep(
                title=stage.name.strip(),
                detail=_stage_detail(stage),
                branches=tuple(_stage_exits(stage, names, can)),
                collect=tuple(stage.collect),
            )
            for stage in script.stages
            if stage.instruction.strip()
        )
    steps = [s.instruction.strip() for s in script.steps if s.instruction.strip()]
    if not steps or len(steps) > MAX_SCRIPT_STAGES:
        return ()
    return tuple(
        NativeStep(title=f"Step {i}", detail=text[:STAGE_DETAIL_MAX])
        for i, text in enumerate(steps, 1)
    )


def render_steps(steps: Sequence[NativeStep]) -> str:
    """The steps as text, for a preview of what an engine with its own step list holds."""
    lines = ["--- STEPS (sent as the voice platform's own step list) ---"]
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step.title}: {step.detail}")
        lines += [f"   When {when}: {action}." for when, action in step.branches]
        if step.collect:
            lines.append(f"   Have in hand: {', '.join(step.collect)}.")
    return "\n".join(lines)


#: The headers whose section an engine with native steps takes out of the instructions,
#: because the same outline goes as steps (v2 and v1 respectively).
OUTLINE_HEADERS: Final = (CONVERSATION_HEADER, "[TASK FLOW]")


def without_outline(body: str) -> str:
    """`body` without its stage outline section, every other line kept."""
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(OUTLINE_HEADERS)), None)
    if start is None:
        return body
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    return "\n".join([*lines[:start], *lines[end:]]).strip()


def _quote(text: str) -> str:
    return '"' + " ".join(text.split()).replace('"', "'") + '"'


def _compile_v2(script: CallScript, collect: Sequence[CollectField]) -> str:
    """The v2 sections, each said once, empty ones omitted. Platform rules (how to speak,
    where facts are, what to do when the agent cannot help, confidentiality, the truthful
    answers) are composed around this by `engine.compose_engine_prompt` and are not
    repeated here."""
    sections: list[str] = []

    def add(header: str, body: str) -> None:
        body = body.strip()
        if body:
            sections.append(f"{header}\n{body}")

    add(BUSINESS_HEADER, script.business_line)
    add("[IDENTITY]", script.identity)
    goal = script.goal.strip()
    purpose = script.outbound_purpose.strip()
    if purpose:
        goal = (
            f"{goal}\n" if goal else ""
        ) + f"On a call you place, say early and in one sentence why you are calling: {purpose}"
    add("[GOAL]", goal)
    add(OPENING_HEADER, script.opening_line)

    style = script.style
    style_lines: list[str] = []
    if style.tone.strip():
        style_lines.append(f"Tone: {style.tone.strip()}")
    if style.address_form.strip():
        style_lines.append(f"Address callers as: {style.address_form.strip()}")
    # "natural" is what the platform's register section already says, so only a departure
    # from it is written here.
    if style.code_mix != "natural":
        style_lines.append(CODE_MIX_SENTENCES[style.code_mix])
    if style.sample_phrases:
        phrases = " / ".join(_quote(p) for p in style.sample_phrases)
        style_lines.append(f"Phrases you can use, varied and never every turn: {phrases}")
    if style.pronunciations:
        said = "; ".join(f"{p.word.strip()} as {_quote(p.say_as)}" for p in style.pronunciations)
        style_lines.append(f"Say these words like this: {said}")
    add(STYLE_HEADER, "\n".join(style_lines))

    stages = [s for s in script.stages if s.instruction.strip()]
    if stages:
        add(
            f"{CONVERSATION_HEADER} {ADHERENCE_SENTENCES[script.adherence]}",
            "\n".join(
                f"{i}. {_stage_line(stage, {st.id: st.name for st in stages})}"
                for i, stage in enumerate(stages, 1)
            ),
        )

    asks = [f for f in collect if f.label.strip()]
    if asks:
        lines = []
        for field in asks:
            line = f"- {field.label.strip()}"
            if field.reason.strip():
                line += f" ({field.reason.strip()})"
            if field.required:
                line += " — needed"
            lines.append(line)
        add(
            "[WHAT TO COLLECT] One at a time, when it fits; read each back. Ask for nothing else.",
            "\n".join(lines),
        )

    objections = [o for o in script.objections if o.response.strip()]
    if objections:
        add(
            "[OBJECTIONS] Answer in this spirit, in your own words. Two noes: accept politely.",
            "\n".join(f"Q: {o.objection.strip()}\nA: {o.response.strip()}" for o in objections),
        )

    policies: list[str] = []
    if not script.policies.offer_call_backs:
        policies.append(NO_CALL_BACKS_POLICY)
    if not script.policies.share_prices:
        policies.append("Do not quote prices. Say the team will share the price with them.")
    if not script.policies.take_bookings:
        policies.append(
            "Do not book appointments or visits yourself. Note what they want and when it "
            "suits them."
        )
    add("[POLICIES]", "\n".join(f"- {p}" for p in policies))
    add("[ENDING]", script.ending)

    facts = [
        (faq.question.strip(), faq.answer.strip())
        for faq in script.faqs
        if faq.question.strip() and faq.answer.strip()
    ]
    add(QUICK_FACTS_LEAD, quick_fact_lines(facts))

    example = [line for line in script.example_exchange if line.text.strip()]
    if example:
        add(
            f"{EXAMPLE_HEADER} Copy the style, never the facts.",
            "\n".join(
                f"{'Caller' if line.speaker == 'caller' else 'You'}: {line.text.strip()}"
                for line in example
            ),
        )
    return "\n\n".join(sections)


def upgrade_to_v2(script: CallScript) -> CallScript:
    """A v1 script in the v2 sections, for the builder to open. Nothing is stored until the
    author saves, so a v1 agent's prompt does not change by being looked at.

    Steps become stages, the FAQ becomes quick facts and the extra end-call rules become the
    ending. The v1 "don't know" sentence and the built-in end-call and guardrail lines are
    dropped: the platform now says each of those once (`engine.compose_engine_prompt`).
    A raw script stays raw, and a v2 script is returned as it is.
    """
    if script.is_raw or script.schema_version == SCRIPT_SCHEMA_VERSION:
        return script
    if len(script.steps) > MAX_SCRIPT_STAGES or any(
        len(step.instruction) > STAGE_DETAIL_MAX for step in script.steps
    ):
        # More or longer steps than a stage holds: converting would drop words the author
        # wrote, so the script stays in its own format.
        return script
    return CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION,
        opening_line=script.opening_line,
        stages=[
            ConversationStage(id=f"s{i}", name=f"Step {i}", instruction=step.instruction)
            for i, step in enumerate(script.steps[:MAX_SCRIPT_STAGES], 1)
            if step.instruction.strip()
        ],
        faqs=script.faqs,
        variables=script.variables,
        ending=" ".join(script.end_call_extra_rules)[:1000],
    )


def _normalised(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def script_text(script: CallScript) -> str:
    """Every word an owner can write into a structured script, as one string."""
    parts = [
        script.business_line,
        script.identity,
        script.goal,
        script.outbound_purpose,
        script.opening_line,
        script.style.tone,
        script.style.address_form,
        *script.style.sample_phrases,
        *(f"{st.name} {st.instruction} {st.sounds_like}" for st in script.stages),
        *(f"{b.when}" for st in script.stages for b in st.branches),
        *(f"{o.objection} {o.response}" for o in script.objections),
        script.ending,
        *(f"{f.question} {f.answer}" for f in script.faqs),
        *(line.text for line in script.example_exchange),
        *(step.instruction for step in script.steps),
        *script.end_call_extra_rules,
    ]
    return "\n".join(parts)


def unplaced_lines(raw: str, script: CallScript) -> list[str]:
    """The lines of a hand-written prompt that appear nowhere in `script`: the round-trip
    check a conversion is shown with, so nothing is lost silently. A line counts as placed
    when its words, punctuation aside, appear in order somewhere in the sections."""
    placed = _normalised(script_text(script))
    out: list[str] = []
    for line in raw.splitlines():
        words = _normalised(line.strip().lstrip("-*0123456789.) ").strip())
        if len(words.split()) >= 3 and words not in placed:
            out.append(line.strip())
    return out


def business_line_of(body: str | None) -> str:
    """The `[BUSINESS]` line inside a compiled v2 body, or "" (v1 and raw scripts)."""
    if not body:
        return ""
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == BUSINESS_HEADER), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    return " ".join("\n".join(lines[start + 1 : end]).split())


def call_backs_withheld(body: str | None) -> bool:
    """Does the script's own policy say not to offer call backs?"""
    return body is not None and f"- {NO_CALL_BACKS_POLICY}" in body


def compile_call_script(script: CallScript, *, collect: Sequence[CollectField] = ()) -> str:
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
    if script.schema_version == SCRIPT_SCHEMA_VERSION:
        return _compile_v2(script, collect)

    # v1, byte for byte as it compiled before v2 existed.
    sections: list[str] = []

    opening = script.opening_line.strip()
    if opening:
        sections.append(f"{OPENING_HEADER}\n{opening}")

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
    "BUSINESS_HEADER",
    "CALL_BACK",
    "CODE_MIX_SENTENCES",
    "DEFAULT_FAQ_FALLBACK",
    "END_OF_CALL",
    "EXAMPLE_HEADER",
    "GUARDRAILS_BLOCK",
    "HAND_OVER",
    "MAX_SCRIPT_STAGES",
    "NO_CALL_BACKS_POLICY",
    "OPENING_HEADER",
    "QUICK_FACTS_HEADER",
    "QUICK_FACTS_LEAD",
    "SCRIPT_SCHEMA_VERSION",
    "SPECIAL_TARGETS",
    "STAGE_DETAIL_MAX",
    "STAGE_TITLE_MAX",
    "STANDARD_VARIABLES",
    "STYLE_HEADER",
    "V1_FAQ_HEADER",
    "CallScript",
    "CanvasPosition",
    "Capabilities",
    "CodeMix",
    "CollectField",
    "ConversationStage",
    "ExampleLine",
    "FaqEntry",
    "NativeStep",
    "Objection",
    "Pronunciation",
    "ScriptPolicies",
    "ScriptStep",
    "ScriptVariable",
    "SpeakingStyle",
    "StageBranch",
    "business_line_of",
    "call_backs_withheld",
    "compile_call_script",
    "extract_variable_names",
    "native_steps",
    "opening_line_of",
    "quick_fact_lines",
    "render_steps",
    "script_text",
    "splice_quick_facts",
    "substitute_variables",
    "unplaced_lines",
    "upgrade_to_v2",
    "without_outline",
]
