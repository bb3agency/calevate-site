"""What Pip is told when it writes a campaign's or an inbound line's script (D-992, D-997,
D-1004): the ask itself, the shapes of the kinds of call a campaign makes, the owner's tone
and one-part instruction, the length the engine leaves for it, and the review pass that
writes the "why" notes and finds lines the sources do not back.

Instructions only, in English: the call's own words are the model's, in the call language,
under the spoken-style guide `ScriptBrief.user_message` carries (never hand-written Telugu or
Hindi here). The call rules, the opening rule and the speech rules are not repeated: the
writer's system instruction (`script_assist._SYSTEM_INSTRUCTION`, `call_rules.writer_rules`,
`OPENING_LINE_RULE`) carries them, and the engine composes the platform's rules into every
call (hard rule 5, `engine.compose_engine_prompt`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from calevate_shared.call_script import CallScript

from apps.api.tenancy.business_copy import provider_words

#: The last step's name (founder, 16 Nov 2026): a booking is one scenario of many, so the step
#: that reads back and closes is the call's own, never "the booking". It reads back the ONE
#: next step agreed: reminder and collection guides agree a call ends on a single clear ask
#: (appmaster.io/blog/message-templates-reminders, koalendar.com/blog/payment-reminder-email,
#: read 16 Nov 2026).
CLOSING_STEP: Final = (
    ' Name the last step "Finalise the call": it reads back the one next step agreed (what '
    "happens, and when) in one sentence, thanks the person and closes; a call that agreed "
    "nothing thanks them and closes. A booking, where one fits, is a step of its own before it."
)

#: The kinds of call a campaign makes, each with the shape its steps take. The model names
#: the kind from the main task, because the owner writes it in their own words and language.
#: - Every placed call opens with who, from where and why, then permission
#:   (`call_rules.OPENING_LINE_RULE`, its sources there).
#: - Reminder and collection: what, when, then one ask; polite, never demanding
#:   (appmaster.io/blog/message-templates-reminders; chaserhq.com/blog/how-to-ask-for-payment-
#:   over-the-phone; read 16 Nov 2026). The amount waits until the right person is confirmed,
#:   and no threat or penalty the sources do not state: RBI's recovery-conduct instructions
#:   (12 Aug 2022, as reported by theprint.in and business-standard.com, read 16 Nov 2026) bar
#:   intimidation and misleading statements on recovery calls.
#: - Qualifying: only the questions that matter, each its own step (docs.telli.com/prompt-best-
#:   practices, cited at `call_rules.SCRIPT_FLOW_RULE`).
#: - Guiding: one action, then wait for what shows it is done (`SCRIPT_FLOW_RULE`).
CALL_KINDS: Final[tuple[tuple[str, str], ...]] = (
    (
        "booking",
        "to book a visit, meeting, demo or test: confirm the right person; one question "
        "to learn what they need; one fact from the sources that answers it; ask which day "
        "or time suits them; collect what the booking needs, one detail per step.",
    ),
    (
        "reminder",
        "to remind or confirm something already arranged: say what it is about and when in "
        "one sentence; ask whether it still suits them; if not, a step that finds a new time "
        "or takes the reason for the team; never argue.",
    ),
    (
        "collection",
        "about a payment or renewal due: confirm the right person before any amount is said; "
        "say what is due and by when, only as the sources give it; ask when they can pay; "
        "someone who cannot pay now is asked for a date that suits them, with no pressure, "
        "no threat and no penalty the sources do not state.",
    ),
    (
        "feedback",
        "to ask how something went: one short rating question first, then one open question "
        "on why; a complaint is listened to and taken for the team, never argued with.",
    ),
    (
        "qualifying",
        "to learn whether a lead still needs what the business offers: the two or three "
        "questions the main task says matter, each its own step; then one fact from the "
        "sources that answers what they said; then the next step the main task names.",
    ),
    (
        "guiding",
        "to help the person do something on their phone or at home: the actions one by one in "
        "the step's procedure, each with what shows it is done; check it worked before the "
        "close.",
    ),
    (
        "news",
        "to tell people about something new the sources describe: say it in one sentence; "
        "ask one question on whether it is useful to them; answer from the sources; then the "
        "next step or a polite close.",
    ),
)

CALL_KINDS_TEXT: Final = (
    "First decide which kind of call the main task asks for, and shape the steps by it: "
    + " ".join(f"A {name} call is {shape}" for name, shape in CALL_KINDS)
    + " A main task that fits none gets the steps it needs, in the order their answers "
    "become possible. Where a step plan below differs from the kind of call, keep only its "
    "steps that serve the main task."
)

#: Objections from the business's own facts: acknowledge, answer with a fact, one question or
#: a small next step, and a firm no ends the call (the `let_go` call rule). Sales guides agree
#: on "agree and pivot", one sentence then one question (withallo.com/academy/cold-call-
#: objection-handling, cognism.com/blog/cold-call-objections, read 16 Nov 2026); writing the
#: three or four the audience always raises, rather than leaving the model to improvise, is
#: what voice-agent guides ask (dapta.ai/blog-posts/ai-voice-agent-prompt-guide, read 16 Nov
#: 2026).
OBJECTIONS_RULE: Final = (
    "Write the objections people really raise on this kind of call, such as being busy, not "
    "interested, having done it already, asking how the business got their number, or asking "
    "for it later. Each response acknowledges it in a few words, answers with a fact from "
    "the sources or the owner's facts when one fits, then asks one short question or offers "
    "one small next step; a second no gets thanks and the close. How the business got their "
    "number is answered only as the main task or sources say it."
)

#: Never a figure, offer or claim the sources do not give. Voice-agent guides name invented
#: prices and policies as the failure to forbid, and an answer the sources do not hold as one
#: to decline (docs.vapi.ai/prompting-guide "Guardrails"; simbavoice.ai/resources/how-to-
#: stop-a-voice-agent-from-hallucinating; read 16 Nov 2026). `script_lint.unknown_figure`
#: checks digits; the review pass below reads the claims digits cannot show.
GROUNDING_RULE: Final = (
    "Every price, amount, date, time, place, offer and claim in what the agent says comes from "
    "the main task, the sources or the owner's facts, with the same meaning. When they do not "
    "give a detail people will ask for, the agent says it does not have that detail and takes "
    "it for the team; it never guesses one."
)

#: Two or three sentences at most per reply and one question per turn (docs.vapi.ai/
#: prompting-guide; docs.voiso.com/docs/prompting-guide "two questions in one breath get one
#: answer"; read 16 Nov 2026). The in-call rules say it again on every call.
TURN_RULE: Final = (
    "Each line the agent says is one short sentence with at most one question in it, so the "
    "person answers one thing at a time."
)

CAMPAIGN_ASK: Final = (
    "Write this campaign's call script. Every call this agent places for the campaign follows "
    "it. The campaign's main task, in the owner's words, says what the calls must achieve; the "
    "owner's notes, links and documents below say what to tell people and how. Write the "
    "opening line for the call it places, the steps that get to the main task one at a time, "
    "quick facts (the faqs list: a question people ask and a short spoken answer, at most "
    "eight), the objections people raise with how to answer, and how the call ends. Where a "
    "note or document says how the agent should handle the call, follow it. "
    f"{CALL_KINDS_TEXT} {OBJECTIONS_RULE} {GROUNDING_RULE} {TURN_RULE}"
) + CLOSING_STEP

#: An inbound line's ask (D-997): the calls are answered, not placed, so it has no call kinds.
LINE_ASK: Final = (
    "Write this phone line's call script. Every call to this number is answered with it. "
    "The main task, in the owner's words, says what callers need; the sources below say "
    "what to tell them and how. Write the greeting the agent says when it answers, the steps "
    "that get to the main task one at a time, quick facts (the faqs list: a question callers "
    "ask and a short spoken answer, at most eight), the objections callers raise with how to "
    "answer, and how the call ends. Where a source says how the agent should handle the "
    f"call, follow it. {GROUNDING_RULE} {TURN_RULE}"
) + CLOSING_STEP

EDIT_TAIL: Final = (
    " Keep anything already in the script that the main task and sources do not change."
)

#: One part rewritten in a chosen language (founder, 16 Nov 2026); the rest stays word for word.
PART_ASK: Final = (
    "Rewrite only this part of the campaign's call script: {part}. Write it in {language}, as "
    "it should be spoken on the call. Leave every other part of the script exactly as it is. "
    "The main task and the owner's notes below say what the part must cover. "
    f"{GROUNDING_RULE}"
)

#: The part name the Script section's "Let Pip map the scenarios" sends (`CampaignFlow`).
FLOW_PART: Final = "flow"
#: The call's steps rewritten as the ways it is likely to go, each with its way out.
FLOW_ASK: Final = (
    "Rewrite only the stages of the campaign's call script as a flow of steps and scenarios. "
    "Each step is a moment of the call (for example: the greeting, whether they know the "
    "business, what they need, the close); each stage is one scenario of a step, a way that "
    "moment can go: for example the person recognises the business, does not remember it, is "
    "busy, is not interested, or has already done what the call asks. Give each stage its "
    "step number and in next the stages it can go on to (0 to end the call), so a step's "
    "scenarios lead to the scenarios of a later step. Name each scenario for what happens. "
    "Write each instruction in plain English and its sounds-like line in {language}. Keep "
    "to 12 stages in all. Leave every other part of the script exactly as it is."
) + CLOSING_STEP

#: The part name Call flow's "Translate with Pip" sends: the English scripts and caller and
#: agent responses put into the campaign's language where that language's box is empty.
TRANSLATE_PART: Final = "translate"
TRANSLATE_INSTRUCTION: Final = (
    "You translate a business's phone-call script lines into the language each item names in "
    "`to`, as a person from the region would naturally say them on a phone call: everyday "
    "spoken words in that language's own script, never word for word. Keep names, brand "
    "names, app names, numbers and amounts as they are. Translate every item and nothing "
    'else. Return JSON: {"items": [{"key": "<the key you were given>", "text": '
    '"<the translation>"}]}.'
)

Tone = Literal["warm", "respectful", "brief"]
#: The owner's tone (D-1004), as the writer reads it. Keys are the request's `tone`.
TONES: Final[dict[str, str]] = {
    "warm": "friendly and warm, like a helpful neighbour, still polite",
    "respectful": "respectful and formal, with the polite address form the spoken-style "
    "guide gives",
    "brief": "short and direct, every line as few words as it can be",
}
INSTRUCTION_MAX: Final = 300


def tone_line(tone: str | None) -> str:
    """The tone sentence, or "" when the owner chose none (Pip then follows the sources)."""
    said = TONES.get(tone or "")
    return (
        f"TONE: every line the agent says is {said}; style.tone says so in English.\n"
        if said
        else ""
    )


def instruction_line(instruction: str | None) -> str:
    """The owner's own ask for this draft, as they typed it."""
    said = " ".join((instruction or "").split())[:INSTRUCTION_MAX]
    return f"THE OWNER ASKS: {said}\n" if said else ""


def length_line(budget: int | None) -> str:
    """How much of the engine's instruction box the script may fill, or "" when unknown."""
    if budget is None or budget <= 0:
        return ""
    return (
        f"LENGTH: the whole script together must stay under {budget:,} characters, or the "
        "agent cannot hold it. Keep instructions short and say each thing once.\n"
    )


def owners_words(main_task: str, notes: str, instruction: str = "") -> str:
    """The campaign in the owner's own words: a line Pip took from them word for word is
    theirs, and is not judged by the opening rule (`finish_written`)."""
    return "\n".join(part for part in (main_task.strip(), notes, instruction.strip()) if part)


def campaign_change(
    main_task: str,
    notes: str,
    documents: str,
    *,
    edit: bool,
    ask: str = CAMPAIGN_ASK,
    part_ask: str | None = None,
    tone: str | None = None,
    instruction: str | None = None,
    budget: int | None = None,
) -> str:
    """What the script is written from: the ask, the owner's tone and instruction, the length
    it may take, the main task, the notes and the documents. A one-part rewrite replaces the
    whole ask, edit tail included."""
    lead = part_ask if part_ask is not None else f"{ask}{EDIT_TAIL if edit else ''}"
    change = (
        f"{lead}\n{tone_line(tone)}{instruction_line(instruction)}{length_line(budget)}"
        f"MAIN TASK:\n{main_task.strip()}\n"
    )
    if notes:
        change += f"OWNER'S NOTES AND LINKS:\n{notes}\n"
    return change + documents


#: Where the engine's box is measured from, and the share of what is left the ask names: the
#: writer overshoots a stated budget a little, and the save refuses a script that does not fit
#: (`script_builder.refuse_if_too_long`), so the ask names less than the room there is.
BUDGET_SHARE: Final = 0.85


def budget_of(limit: int | None, total: int, script_chars: int) -> int | None:
    """The characters the script may take: the box less everything around the script."""
    if limit is None:
        return None
    return max(int((limit - (total - script_chars)) * BUDGET_SHARE), 0)


#: The one shortening pass a draft gets when it does not fit the engine's box.
SHORTEN_ASK: Final = (
    "This script is {over:,} characters too long for the agent to hold. Shorten it: say each "
    "thing once, cut instructions to what the agent needs, merge quick facts that say the "
    "same thing, and drop objections that repeat another. Start with these parts, the "
    "longest: {parts}. Keep the opening lines exactly as they are, keep every step's meaning "
    "and keep every fact the sources give."
)
TOO_LONG_RULE: Final = (
    "Too long for the agent to hold by {over:,} characters. Shorten {parts} before you keep it"
)


#: The review pass: one short "why" per part, and the lines that say something the sources do
#: not give (D-1004). A second read, not the writer's own, because a writer asked to judge
#: itself in the same answer passes what it just wrote; a grounding check against the
#: retrieved text is what voice-agent guides propose for high-stakes lines
#: (simbavoice.ai/resources/how-to-stop-a-voice-agent-from-hallucinating, read 16 Nov 2026).
REVIEW_INSTRUCTION: Final = (
    "You review a call script an assistant just wrote for a small business, before the owner "
    "reads it. You are given the owner's main task, their sources and each part of the script "
    "with its key. For each part, write `why`: one plain English sentence of at most 20 words "
    "telling the owner why the part says what it says, naming the main task or the source it "
    "comes from by its title. Never name an AI company or model. Then list in `unsourced` "
    "every part whose spoken words state a price, amount, date, time, place, offer, discount, "
    "guarantee or other claim that neither the main task, the sources nor the owner's facts "
    "give; `claim` names it in a few plain English words. A greeting, a question or a polite "
    "phrase is never unsourced. Use only the keys given. Return ONLY JSON."
)
WHY_MAX: Final = 200
CLAIM_MAX: Final = 120
REVIEW_MAX_TOKENS: Final = 2_000
UNSOURCED_RULE: Final = (
    "Says {claim}, which your main task and sources do not give. Check it, or add it to a source."
)

_REVIEW_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"part": {"type": "string"}, "why": {"type": "string"}},
    "required": ["part", "why"],
    "additionalProperties": False,
}
_UNSOURCED_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"part": {"type": "string"}, "claim": {"type": "string"}},
    "required": ["part", "claim"],
    "additionalProperties": False,
}
REVIEW_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "notes": {"type": "array", "items": _REVIEW_ROW},
        "unsourced": {"type": "array", "items": _UNSOURCED_ROW},
    },
    "required": ["notes", "unsourced"],
    "additionalProperties": False,
}
REVIEW_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {"name": "script_review", "strict": True, "schema": REVIEW_SCHEMA},
}

#: The parts a note may be written for, with the label the review names them by: the keys are
#: the ones `LeftOut.part` and the review screen use (`stages.<id>` for a step).
_REVIEWED_FIELDS: Final = (
    ("opening_line", "Opening line"),
    ("outbound_opening_line", "Opening line when it calls"),
    ("goal", "The goal"),
    ("faqs", "Quick facts"),
    ("objections", "When people push back"),
    ("ending", "How it ends the call"),
)


@dataclass(frozen=True, slots=True)
class ReviewedPart:
    key: str
    label: str
    text: str


def _part_text(script: CallScript, key: str) -> str:
    if key == "faqs":
        return " | ".join(f"{f.question} -> {f.answer}" for f in script.faqs)
    if key == "objections":
        return " | ".join(f"{o.objection} -> {o.response}" for o in script.objections)
    return str(getattr(script, key))


def reviewed_parts(script: CallScript, base: CallScript | None) -> list[ReviewedPart]:
    """The parts of `script` Pip wrote or changed against `base`, each with its key, its label
    and its text: only those get a note, so a part kept as the owner had it carries none."""
    parts: list[ReviewedPart] = []
    for key, label in _REVIEWED_FIELDS:
        text = _part_text(script, key).strip()
        if text and (base is None or text != _part_text(base, key).strip()):
            parts.append(ReviewedPart(key, label, text))
    before = {stage.id: stage for stage in (base.stages if base is not None else [])}
    for stage in script.stages:
        text = f"{stage.instruction} Says: {stage.sounds_like}".strip()
        was = before.get(stage.id)
        if was is not None and (was.instruction, was.sounds_like) == (
            stage.instruction,
            stage.sounds_like,
        ):
            continue
        parts.append(ReviewedPart(f"stages.{stage.id}", f"Step: {stage.name}", text))
    return parts


def review_request(
    parts: Sequence[ReviewedPart], main_task: str, documents: str, facts: Sequence[str]
) -> str:
    """The review pass's message: what the script was written from, then its parts by key."""
    lines = [f"MAIN TASK:\n{main_task.strip()}"]
    if facts:
        lines.append("THE OWNER'S FACTS:\n" + "\n".join(f"- {fact}" for fact in facts))
    if documents:
        lines.append(documents)
    lines.append("THE SCRIPT'S PARTS:")
    lines += [f"[{part.key}] {part.label}: {part.text}" for part in parts]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Review:
    """What the review pass found: a note per part key, and the unsourced claims by key."""

    notes: dict[str, str] = field(default_factory=dict)
    unsourced: dict[str, str] = field(default_factory=dict)


def parsed_review(raw: dict[str, Any], keys: Sequence[str], *, allowed: str = "") -> Review | None:
    """The review's JSON, kept to the keys it was given and cut to the screen's lengths; None
    when it holds nothing usable, which the ladder counts as no answer. A note that names a
    technology company the owner did not is dropped: the owner reads it (D-679)."""
    known = set(keys)
    theirs = provider_words(allowed)

    def rows(name: str, text_key: str, limit: int) -> dict[str, str]:
        found: dict[str, str] = {}
        value = raw.get(name)
        for row in value if isinstance(value, list) else []:
            if not isinstance(row, dict):
                continue
            key, said = row.get("part"), row.get(text_key)
            if not (isinstance(key, str) and key in known and isinstance(said, str)):
                continue
            said = " ".join(said.split())[:limit]
            if said and not provider_words(said) - theirs:
                found.setdefault(key, said)
        return found

    notes = rows("notes", "why", WHY_MAX)
    if not notes:
        return None
    return Review(notes=notes, unsourced=rows("unsourced", "claim", CLAIM_MAX))


__all__ = [
    "CALL_KINDS",
    "CAMPAIGN_ASK",
    "CLOSING_STEP",
    "EDIT_TAIL",
    "FLOW_ASK",
    "FLOW_PART",
    "GROUNDING_RULE",
    "LINE_ASK",
    "OBJECTIONS_RULE",
    "PART_ASK",
    "REVIEW_FORMAT",
    "REVIEW_INSTRUCTION",
    "SHORTEN_ASK",
    "TONES",
    "TOO_LONG_RULE",
    "TRANSLATE_INSTRUCTION",
    "TRANSLATE_PART",
    "UNSOURCED_RULE",
    "Review",
    "ReviewedPart",
    "Tone",
    "budget_of",
    "campaign_change",
    "instruction_line",
    "length_line",
    "owners_words",
    "parsed_review",
    "review_request",
    "reviewed_parts",
    "tone_line",
]
