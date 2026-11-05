"""Each client's business-tailored examples and suggestions, written by AI (D-827).

Founder, 19 Oct 2026: every client account gets its own example text — the placeholders and
hints the per-trade table (`apps/web/src/lib/verticalExamples.ts`) serves, suggested script
steps with an example line each, example lines for the ready-made starters' steps,
caller-detail suggestions and example questions — written by AI ONCE from the business's
current details and its real-call gaps, stored, and refreshed on request or every 15 days
when those inputs changed. Headings and buttons are never generated: they stay fixed so
Pip's screen map and help stay true.

WHAT THIS MODULE OWNS. The shape the model must return (`GeneratedCopy`, a closed key set
with length caps), the text rules every string must pass (`copy_problems`), the read side,
and queueing a run. The run itself is `apps/workers/business_copy.py`.

THE CAPABILITY PROFILE. The same run judges what the business does with its callers
(`Capabilities`: bookings, orders, prices, premises, selling, health care), the objections its
callers raise, what it calls them and what its owner would ask Pip. Every consumer reads it
through `capabilities_for` and keeps today's behaviour for a capability not yet judged.

WHY A CLIENT'S WORDS ARE NEVER OVERWRITTEN. Everything stored here is the AI's own text, in
its own row. The screens show it where a field is empty (a placeholder) or as a suggestion
a person clicks to add, and `agents/starters.apply_starter` writes starter example lines
only into a brand-new agent's empty "example line" fields. So a refresh replaces only the
AI's earlier text; nothing a person typed is ever in this row to be replaced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from calevate_shared.call_script import SOUNDS_LIKE_MAX, STAGE_TITLE_MAX
from calevate_shared.spoken_guard import textbook_problem
from pydantic import ConfigDict, Field, StrictBool, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.schemas import Strict
from apps.api.reliability.service import enqueue_outbox

#: The ARQ job (`apps/workers/business_copy.generate_business_copy`).
JOB: Final = "generate_business_copy"

#: The scheduled refresh looks at an account this long after its last look (founder,
#: 19 Oct 2026), and writes new copy only when the inputs changed.
REFRESH_EVERY: Final = timedelta(days=15)

#: A run holds the row this long at most. Longer than the job's own budget (the worker's
#: 300 s `job_timeout`), so a live run is never taken over; a crashed one frees the row.
CLAIM_TTL: Final = timedelta(minutes=10)

Trigger = Literal["signup", "refresh", "scheduled", "operator", "first_run"]
StopReason = Literal[
    "allowance_used_up",
    "ai_paused",
    "inputs_unchanged",
    "provider_unavailable",
    "answer_unusable",
    "account_closed",
]

# --- the shape ------------------------------------------------------------------------------

#: Caps, in characters. The per-trade table's longest value is about 200 characters.
SHORT_MAX: Final = 80
LINE_MAX: Final = 160
PROSE_MAX: Final = 300
CHIP_MAX: Final = 40
QUESTION_MAX: Final = 120

MIN_STEPS: Final = 3
MAX_STEPS: Final = 6
MIN_CHIPS: Final = 3
MAX_CHIPS: Final = 8
MIN_QUESTIONS: Final = 3
MAX_QUESTIONS: Final = 6
#: A starter has six steps today (`agents/starters`); the exact count is checked against the
#: account's own starters when the answer is parsed.
MAX_STARTER_LINES: Final = 10

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SHORT_MAX)]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LINE_MAX)]
Prose = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PROSE_MAX)]
Chip = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CHIP_MAX)]
Question = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=QUESTION_MAX)
]
Spoken = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SOUNDS_LIKE_MAX)
]
StepName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=STAGE_TITLE_MAX)
]


class _Strict(Strict):
    # This module's models are also frozen; the shared base carries only the forbid, and
    # pydantic merges this config onto it.
    model_config = ConfigDict(frozen=True)


class Placeholders(_Strict):
    """The per-trade table's keys (`verticalExamples.ts`), in snake case, for this business.

    `orgName` and `orgSlug` are not here: they are shown only while an operator creates an
    account, before there is a business to write them for."""

    knowledge_title: Short
    knowledge_answer: Prose
    extraction_reason: Line
    script_brief: Prose
    extraction_label: Chip
    extraction_options: Line
    #: Two rules, one per line: the one key that may hold a line break.
    end_call_rules: Prose
    lead_search: Short
    #: The booking or ordering job's name and line. Absent for a business that neither books
    #: callers nor takes their orders (`booking_job_problems`): a free app's helpline has no
    #: such job, and a "Take bookings" example would tell its owner it does.
    booking_job_title: Chip | None = None
    booking_job_line: Line | None = None
    # Added with prompt version 2. Optional so a copy written under version 1 still reads
    # (the screens fall back to a neutral example for a missing key); `missing_placeholders`
    # makes every one of them required in a new answer.
    teach_note: Prose | None = None
    business_line: Line | None = None
    agent_role: Prose | None = None
    call_goal: Line | None = None
    outbound_purpose: Line | None = None
    call_ending: Line | None = None
    pronounce_word: Short | None = None
    pronounce_say_as: Short | None = None
    script_change: Line | None = None
    script_change_idea: Short | None = None
    fact_question: Line | None = None
    fact_answer: Line | None = None
    test_expectation: Line | None = None
    campaign_name: Short | None = None
    message_title: Chip | None = None
    #: A WhatsApp message with `{{1}}` where the customer's name goes.
    message_body: Line | None = None
    outcome_label: Chip | None = None
    outcome_meaning: Line | None = None
    # The business profile's own examples, asked for up to prompt version 2. They are now
    # written with that form's labels from the business's own description
    # (`tenancy/profile_wording`), so they are no longer asked for or shown; they stay
    # readable so a copy written under version 2 still parses.
    branch_label: Short | None = None
    service_name: Short | None = None
    service_price: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,8}$")] | None = None
    service_note: Short | None = None
    ask_on_arrival: Short | None = None
    faq_question: Line | None = None
    staff_name: Short | None = None
    staff_spoken: Short | None = None
    staff_role: Short | None = None
    staff_why_it_matters: Line | None = None
    booking_rules: Prose | None = None
    contact_name: Short | None = None


#: The keys no longer asked for (see the end of `Placeholders`).
RETIRED_PLACEHOLDERS: Final = frozenset(
    {
        "branch_label",
        "service_name",
        "service_price",
        "service_note",
        "ask_on_arrival",
        "faq_question",
        "staff_name",
        "staff_spoken",
        "staff_role",
        "staff_why_it_matters",
        "booking_rules",
        "contact_name",
    }
)

#: The keys, in the table's order, for the prompt and the strict schema.
PLACEHOLDER_KEYS: Final[tuple[str, ...]] = tuple(
    key for key in Placeholders.model_fields if key not in RETIRED_PLACEHOLDERS
)

#: The keys a new answer leaves empty when the business neither books nor takes orders.
BOOKING_JOB_KEYS: Final = ("booking_job_title", "booking_job_line")

#: The one blank a generated message body holds, as the message form numbers it.
MESSAGE_BLANK: Final = "{{1}}"


def missing_placeholders(placeholders: Placeholders) -> list[str]:
    """The keys a new answer left out. Every key is required of the model; only a stored
    copy from an earlier prompt version may lack the later ones. The booking job's keys are
    judged with the capabilities instead (`booking_job_problems`)."""
    return [
        key
        for key in PLACEHOLDER_KEYS
        if key not in BOOKING_JOB_KEYS and getattr(placeholders, key) is None
    ]


class StepSuggestion(_Strict):
    """A step the script builder suggests: its name (English) and how it sounds on the
    phone (the business's main call language)."""

    name: StepName
    example_line: Spoken


class StarterLines(_Strict):
    """One example line per step of each ready-made starter, in step order."""

    answer_calls: list[Spoken] = Field(min_length=1, max_length=MAX_STARTER_LINES)
    call_leads: list[Spoken] = Field(min_length=1, max_length=MAX_STARTER_LINES)


class ScreenGuide(_Strict):
    """Whether this business's callers are often on its app or website during a call, so its
    agents should guide them on screen (D-906's switch), judged from the business itself."""

    suggested: bool
    #: Why, to the owner, in plain English; empty when not suggested.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=LINE_MAX)]


Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=LINE_MAX)]


class Capability(_Strict):
    """One yes/no judgement about what the business does with its callers.

    `applies` is None only in the UNKNOWN profile (`Capabilities.unknown`): no run has judged
    this account yet. A judged answer is always True or False with a reason
    (`capability_problems`). `reason` comes before `applies` so the model writes its grounds
    before its verdict: in JSON generated left to right, a reason written after the verdict
    cannot inform it.
    """

    reason: Reason
    #: Strict: lax parsing would read the string "no" as a verdict of False.
    applies: StrictBool | None


CAPABILITY_KEYS: Final = (
    "takes_bookings",
    "takes_orders",
    "quotes_prices",
    "has_premises",
    "sells",
    "health_business",
)


class Capabilities(_Strict):
    """What this business does with its callers, judged by the copy run from its own details.

    takes_bookings: callers book a time, slot, visit or meeting. takes_orders: callers order
    goods for pickup or delivery. quotes_prices: the business tells callers prices.
    has_premises: callers come to a place (a shop, an office, a site). sells: the business
    sells anything to callers at all (False for a free app helping its registered users, or a
    helpline). health_business: it gives health or medical care.

    THE UNKNOWN RULE: `applies is None` means "not judged yet", and a consumer then behaves
    exactly as it did before this profile existed. Only `applies is False` may withdraw
    anything; never read None as False.
    """

    takes_bookings: Capability
    takes_orders: Capability
    quotes_prices: Capability
    has_premises: Capability
    sells: Capability
    health_business: Capability

    @classmethod
    def unknown(cls) -> Capabilities:
        return cls.model_validate({key: {"reason": "", "applies": None} for key in CAPABILITY_KEYS})

    @property
    def judged(self) -> bool:
        return all(getattr(self, key).applies is not None for key in CAPABILITY_KEYS)


MAX_OBJECTIONS: Final = 3
MAX_PIP_QUESTIONS: Final = 4


class CallerObjection(_Strict):
    """A push-back this business's callers really raise, and how the agent should meet it."""

    #: What the caller says, in the business's main call language, as callers say it.
    caller_says: Line
    #: Guidance for the agent, in English.
    how_to_answer: Line


#: What the business calls the people on its calls, English and singular: one to three plain
#: words, lowercased so a screen can put it inside a sentence.
CallerNoun = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=CHIP_MAX,
        pattern=r"^[A-Za-z]+(?:[ -][A-Za-z]+){0,2}$",
    ),
]


class GeneratedCopy(_Strict):
    """Everything one run writes. Closed: an extra key is an unusable answer."""

    placeholders: Placeholders
    steps: list[StepSuggestion] = Field(min_length=MIN_STEPS, max_length=MAX_STEPS)
    starter_lines: StarterLines
    #: Details an agent may ask a caller for, as chip labels (English).
    caller_details: list[Chip] = Field(min_length=MIN_CHIPS, max_length=MAX_CHIPS)
    #: Questions callers of this business ask (English), for the knowledge screens.
    example_questions: list[Question] = Field(min_length=MIN_QUESTIONS, max_length=MAX_QUESTIONS)
    #: Optional so a copy written before it was asked still reads; a new answer must carry it
    #: (`screen_guide_problems`).
    screen_guide: ScreenGuide | None = None
    # Added with prompt version 4, optional for the same reason; `profile_problems` makes
    # each required in a new answer.
    capabilities: Capabilities | None = None
    objections: list[CallerObjection] | None = Field(default=None, max_length=MAX_OBJECTIONS)
    caller_noun: CallerNoun | None = None
    #: Questions an owner of this business would ask Pip about its calls (English).
    pip_questions: list[Question] | None = Field(default=None, max_length=MAX_PIP_QUESTIONS)


# --- the text rules -------------------------------------------------------------------------

#: The clinic vocabulary `tests/clinic_words_guard_test.py` keeps out of shared copy (D-731):
#: the guard imports this pattern, so the two cannot drift. Allowed in AI-written text only
#: for a health business or in the owner's own words (`health_words_problem`).
CLINIC_WORDS: Final = re.compile(
    r"\b(?:clinics?|hospitals?|patients?|doctors?|dentists?|dental|appointments?|symptoms?|"
    r"prescriptions?|healthcare|OPD)\b",
    re.IGNORECASE,
)

#: Providers a client never reads about (D-679): the voice platform, the voices, the carriers
#: and the language models.
VENDOR_WORDS: Final = re.compile(
    r"\b(?:sarvam|cartesia|saaras|sonic|plivo|thinnest(?:ai)?|bolna|exotel|gemini|"
    r"google|openai|chatgpt|gpt|azure|microsoft|anthropic|claude|elevenlabs|deepgram)\b",
    re.IGNORECASE,
)

#: A way to pay, not a provider: "we take Google Pay" is what a business tells its callers
#: (founder, 20 Oct 2026). Removed before `VENDOR_WORDS` is matched, so "Google" alone still is.
_PAYMENT_NAMES: Final = re.compile(r"\b(?:google\s*pay|g\s?pay)\b", re.IGNORECASE)


def provider_words(text: str) -> frozenset[str]:
    """The provider names `text` uses (`VENDOR_WORDS`), lowercased; a payment name is not one."""
    return frozenset(m.lower() for m in VENDOR_WORDS.findall(_PAYMENT_NAMES.sub(" ", text)))


def provider_problem(where: str, text: str, *, allowed: str = "") -> str | None:
    """A problem for a line an AI wrote that names a provider; None when it names none. A name
    that also appears in `allowed` (the owner's own words) is theirs, not the model's."""
    if not provider_words(text) - provider_words(allowed):
        return None
    return f"{where}: names a technology company"


def _health_words(text: str) -> frozenset[str]:
    # Singular, so "doctors" in the owner's words allows "doctor" in the model's.
    return frozenset(m.lower().removesuffix("s") for m in CLINIC_WORDS.findall(text))


def health_words_problem(where: str, text: str, *, health: bool, allowed: str = "") -> str | None:
    """A problem for a line an AI wrote that uses medical words for a business that is not a
    health business; None otherwise. Judged from what the business is rather than its listed
    type: a pharmacy filed under retail may say "doctor", a grocery may not. A word the
    owner's own description uses (`allowed`) is theirs, as in `provider_problem`."""
    if health or not _health_words(text) - _health_words(allowed):
        return None
    return f"{where}: medical words, and this business is not a health business"


#: Formatting a screen or a voice would show literally: markdown marks and bullets.
_MARKDOWN: Final = re.compile(r"[*#`_~|\[\]<>]|^\s*(?:[-•]|\d+[.)])\s", re.MULTILINE)
_EMOJI: Final = re.compile("[☀-➿\U0001f000-\U0001faff️]")
#: A voice reads digits, rupee signs, slashes and ellipses badly; a spoken line says numbers
#: in words (`engine.VOICE_STYLE_GUIDANCE`).
_NOT_SPOKEN: Final = re.compile(r"[0-9₹/]|\.\.\.|…")


def _strings(copy: GeneratedCopy) -> list[tuple[str, str, bool]]:
    """(path, value, spoken) for every string in the copy."""
    out: list[tuple[str, str, bool]] = [
        (f"placeholders.{key}", str(value), False)
        for key, value in copy.placeholders.model_dump().items()
        if value is not None
    ]
    for i, step in enumerate(copy.steps):
        out.append((f"steps.{i}.name", step.name, False))
        out.append((f"steps.{i}.example_line", step.example_line, True))
    for job in ("answer_calls", "call_leads"):
        for i, line in enumerate(getattr(copy.starter_lines, job)):
            out.append((f"starter_lines.{job}.{i}", line, True))
    out += [(f"caller_details.{i}", v, False) for i, v in enumerate(copy.caller_details)]
    out += [(f"example_questions.{i}", v, False) for i, v in enumerate(copy.example_questions)]
    if copy.screen_guide is not None and copy.screen_guide.reason:
        out.append(("screen_guide.reason", copy.screen_guide.reason, False))
    if copy.capabilities is not None:
        for key in CAPABILITY_KEYS:
            if reason := getattr(copy.capabilities, key).reason:
                out.append((f"capabilities.{key}.reason", reason, False))
    for i, objection in enumerate(copy.objections or ()):
        out.append((f"objections.{i}.caller_says", objection.caller_says, True))
        out.append((f"objections.{i}.how_to_answer", objection.how_to_answer, False))
    if copy.caller_noun is not None:
        out.append(("caller_noun", copy.caller_noun, False))
    out += [(f"pip_questions.{i}", v, False) for i, v in enumerate(copy.pip_questions or ())]
    return out


def screen_guide_problems(copy: GeneratedCopy) -> list[str]:
    """A new answer must judge the screen question, and give a reason exactly when it
    suggests the switch."""
    guide = copy.screen_guide
    if guide is None:
        return ["screen_guide: missing"]
    if guide.suggested and not guide.reason:
        return ["screen_guide.reason: one sentence when suggested"]
    if not guide.suggested and guide.reason:
        return ["screen_guide.reason: empty when not suggested"]
    return []


def capability_problems(copy: GeneratedCopy) -> list[str]:
    """A new answer must judge every capability true or false, each with its reason."""
    caps = copy.capabilities
    if caps is None:
        return ["capabilities: missing"]
    problems: list[str] = []
    for key in CAPABILITY_KEYS:
        judged = getattr(caps, key)
        if judged.applies is None:
            problems.append(f"capabilities.{key}.applies: true or false")
        if not judged.reason:
            problems.append(f"capabilities.{key}.reason: one short line")
    return problems


def booking_job_problems(copy: GeneratedCopy) -> list[str]:
    """The booking job's title and line are both given when callers book or order, and both
    empty when they do neither, so a screen never offers a job the business does not do."""
    caps = copy.capabilities
    if caps is None or caps.takes_bookings.applies is None or caps.takes_orders.applies is None:
        return []
    wanted = bool(caps.takes_bookings.applies or caps.takes_orders.applies)
    problems: list[str] = []
    for key in BOOKING_JOB_KEYS:
        given = getattr(copy.placeholders, key) is not None
        if wanted and not given:
            problems.append(f"placeholders.{key}: needed, callers book or order")
        elif given and not wanted:
            problems.append(f"placeholders.{key}: empty string, callers neither book nor order")
    return problems


def profile_problems(copy: GeneratedCopy) -> list[str]:
    """The version-4 fields a new answer must carry (an empty list is an answer; absent is
    not), and the booking job's agreement with the capabilities."""
    problems = capability_problems(copy)
    for key in ("objections", "caller_noun", "pip_questions"):
        if getattr(copy, key) is None:
            problems.append(f"{key}: missing")
    return problems + booking_job_problems(copy)


def health_allowed(copy: GeneratedCopy) -> bool:
    """Whether the copy's own judgement says this is a health business."""
    return copy.capabilities is not None and copy.capabilities.health_business.applies is True


def screen_text_problems(path: str, value: str, *, clinic: bool, allowed: str = "") -> list[str]:
    """The rules every AI-written string a client reads keeps, whatever feature wrote it: no
    markdown or emoji, no provider (D-679), and medical words only for a health business
    (`clinic`) or where the owner's own words (`allowed`) use them (D-731).
    Names the path and the rule, never the text (hard rule 6)."""
    problems: list[str] = []
    if _MARKDOWN.search(value):
        problems.append(f"{path}: no markdown, bullets or symbols")
    if _EMOJI.search(value):
        problems.append(f"{path}: no emoji")
    if provider_words(value):
        problems.append(f"{path}: names a technology company")
    if worded := health_words_problem(path, value, health=clinic, allowed=allowed):
        problems.append(worded)
    return problems


def copy_problems(
    copy: GeneratedCopy, *, health: bool, language: str | None = None, allowed: str = ""
) -> list[str]:
    """Every rule a string breaks, as `path: rule`. Names paths, rules and the spoken-style
    list's own words (an example line's textbook words, in `language`), never the text,
    so the list can go back to the model and into a log (hard rule 6). `health` and
    `allowed` decide the medical words (`health_words_problem`)."""
    problems: list[str] = []
    for path, value, spoken in _strings(copy):
        lines = value.split("\n")
        if path == "placeholders.end_call_rules":
            if len(lines) > 2 or any(not line.strip() for line in lines):
                problems.append(f"{path}: two rules, one per line, nothing else")
        elif len(lines) > 1:
            problems.append(f"{path}: one line, no line breaks")
        problems += screen_text_problems(path, value, clinic=health, allowed=allowed)
        if spoken and (worded := textbook_problem(path, value, language)):
            problems.append(worded)
        if spoken and _NOT_SPOKEN.search(value):
            problems.append(f"{path}: numbers in words, no digits, rupee signs or slashes")
    if (body := copy.placeholders.message_body) is not None:
        problem = _message_body_problem(body)
        if problem:
            problems.append(f"placeholders.message_body: {problem}")
    return problems


def _message_body_problem(body: str) -> str | None:
    """The message form refuses a blank other than 1, 2, 3 in order, and WhatsApp refuses a
    message that starts or ends with one, so the example must be one the form would accept."""
    if body.count(MESSAGE_BLANK) != 1 or body.count("{") != 2 or body.count("}") != 2:
        return f"exactly one {MESSAGE_BLANK} and no other braces"
    stripped = body.strip().rstrip(".!?। ")
    if stripped.startswith(MESSAGE_BLANK) or stripped.endswith(MESSAGE_BLANK):
        return f"{MESSAGE_BLANK} inside the sentence, not at its start or end"
    return None


# --- the read side --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CopyState:
    """The row, as the screens read it. `copy` is None until the first run wrote one."""

    copy: GeneratedCopy | None
    language: str | None
    model: str | None
    generated_at: datetime | None
    cost_inr: Decimal | None
    absorbed: bool
    running: bool
    last_trigger: str | None
    last_attempt_at: datetime | None
    stop_reason: str | None


_SELECT: Final = (
    "SELECT generated, language, model, generated_at, cost_inr, absorbed, running_since, "
    "last_trigger, last_attempt_at, stop_reason FROM business_copies"
)


def parse_stored(raw: Any) -> GeneratedCopy | None:
    """The stored copy, or None for a row a past shape no longer reads. A shape change is a
    reason to fall back to the per-trade examples, never a 500 on every screen."""
    if not isinstance(raw, dict):
        return None
    try:
        return GeneratedCopy.model_validate(raw)
    except ValueError:
        return None


def claim_is_live(running_since: datetime | None, *, now: datetime | None = None) -> bool:
    return running_since is not None and running_since > (now or datetime.now(UTC)) - CLAIM_TTL


async def read_state(session: AsyncSession) -> CopyState | None:
    """This session's account's copy, or None when no run was ever queued. RLS scopes it."""
    row = (await session.execute(text(_SELECT))).first()
    if row is None:
        return None
    return CopyState(
        copy=parse_stored(row[0]),
        language=row[1],
        model=row[2],
        generated_at=row[3],
        cost_inr=row[4],
        absorbed=bool(row[5]),
        running=claim_is_live(row[6]),
        last_trigger=row[7],
        last_attempt_at=row[8],
        stop_reason=row[9],
    )


async def capabilities_for(session: AsyncSession, tenant_id: UUID) -> Capabilities:
    """The account's judged capability profile, or `Capabilities.unknown()` when no run has
    judged it yet (no copy, a copy from before prompt version 4, or one that no longer reads).

    The one backend door for every consumer. UNKNOWN RULE: a capability whose `applies` is
    None means "keep today's behaviour"; only False withdraws anything. Filtered on
    `tenant_id` as well as RLS, so an operator's session scoped to the tenant reads the same.
    """
    raw = (
        await session.execute(
            text("SELECT generated FROM business_copies WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    ).scalar()
    copy = parse_stored(raw)
    if copy is None or copy.capabilities is None:
        return Capabilities.unknown()
    return copy.capabilities


# --- queueing -------------------------------------------------------------------------------


async def queue_generation(session: AsyncSession, *, tenant_id: UUID, trigger: Trigger) -> UUID:
    """Queue one run in the caller's transaction (BACKEND-PATTERNS §4): it reaches the worker
    only if the caller commits."""
    return await enqueue_outbox(
        session, job=JOB, payload={"tenant_id": str(tenant_id), "trigger": trigger}
    )


#: What a person reads about the last run that wrote nothing. Plain words, no provider.
STOP_MESSAGES: Final[dict[str, str]] = {
    "allowance_used_up": (
        "Not refreshed: this month's AI help allowance is used up. Your examples stay as they are."
    ),
    "ai_paused": "Not refreshed: AI help is paused for now. Your examples stay as they are.",
    "inputs_unchanged": (
        "Checked: nothing in your business details, knowledge or calls had changed, so your "
        "examples were kept."
    ),
    "provider_unavailable": (
        "Not refreshed: AI help could not be reached. Your examples stay as they are; try "
        "again later."
    ),
    "answer_unusable": (
        "Not refreshed: the new examples did not pass our checks, so the ones you have were "
        "kept. Try again later."
    ),
    "account_closed": "Not refreshed: this account is closed.",
}


__all__ = [
    "BOOKING_JOB_KEYS",
    "CAPABILITY_KEYS",
    "CLAIM_TTL",
    "CLINIC_WORDS",
    "JOB",
    "MAX_OBJECTIONS",
    "MAX_PIP_QUESTIONS",
    "MESSAGE_BLANK",
    "PLACEHOLDER_KEYS",
    "REFRESH_EVERY",
    "RETIRED_PLACEHOLDERS",
    "STOP_MESSAGES",
    "VENDOR_WORDS",
    "CallerObjection",
    "Capabilities",
    "Capability",
    "CopyState",
    "GeneratedCopy",
    "Placeholders",
    "ScreenGuide",
    "StarterLines",
    "StepSuggestion",
    "StopReason",
    "Trigger",
    "booking_job_problems",
    "capabilities_for",
    "capability_problems",
    "claim_is_live",
    "copy_problems",
    "health_allowed",
    "health_words_problem",
    "missing_placeholders",
    "parse_stored",
    "profile_problems",
    "provider_problem",
    "provider_words",
    "queue_generation",
    "read_state",
    "screen_guide_problems",
    "screen_text_problems",
]
