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

import unicodedata
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

#: A claim about the person is asked, never told (Rytu Khata, 9 and 20-21 Nov 2026: a line
#: telling a farmer their name was "in our records" was not recognised). The list may be wrong
#: and the person may not remember, so even a sourced fact is put as a question they can
#: answer (docs/evidence/script-generation-2026-11-21/GROUNDING.md rows 8-9).
PERSON_RULE: Final = (
    "Anything the agent says about the person called (what they did, registered, bought or "
    "gave, or what the business's records hold about them) comes only from the main task, the "
    "campaign or the sources, and is asked as one short question they can answer, never told "
    "to them as a fact: the list may be wrong and the person may not remember. Nothing about "
    "the person that those do not give is said at all."
)

#: A stock line that fits any business's call is what the person on the Rytu Khata call did
#: not recognise (GROUNDING.md row 8).
SPECIFIC_RULE: Final = (
    "Write for this call only: every step serves the main task and says it with what the main "
    "task, the campaign and the sources give (the business, what it offers, who the people are "
    "and why they are called). No stock line that could be pasted into another business's "
    "call, and nothing said twice across steps."
)

CAMPAIGN_ASK: Final = (
    "Write this campaign's call script. Every call this agent places for the campaign follows "
    "it. The campaign's main task, in the owner's words, says what the calls must achieve; the "
    "owner's notes, links and documents below say what to tell people and how. Write the "
    "opening line for the call it places, whose reason for calling is the main task in one "
    "short sentence, the steps that get to the main task one at a time, "
    "quick facts (the faqs list: a question people ask and a short spoken answer, at most "
    "eight), the objections people raise with how to answer, and how the call ends. Where a "
    "note or document says how the agent should handle the call, follow it. "
    f"{CALL_KINDS_TEXT} {OBJECTIONS_RULE} {GROUNDING_RULE} {PERSON_RULE} {SPECIFIC_RULE} "
    f"{TURN_RULE}"
) + CLOSING_STEP

#: An inbound line's ask (D-997): the calls are answered, not placed, so it has no call kinds.
LINE_ASK: Final = (
    "Write this phone line's call script. Every call to this number is answered with it. "
    "The main task, in the owner's words, says what callers need; the sources below say "
    "what to tell them and how. Write the greeting the agent says when it answers, the steps "
    "that get to the main task one at a time, quick facts (the faqs list: a question callers "
    "ask and a short spoken answer, at most eight), the objections callers raise with how to "
    "answer, and how the call ends. Where a source says how the agent should handle the "
    f"call, follow it. {GROUNDING_RULE} {PERSON_RULE} {SPECIFIC_RULE} {TURN_RULE}"
) + CLOSING_STEP

EDIT_TAIL: Final = (
    " Keep anything already in the script that the main task and sources do not change."
)

#: One part rewritten in a chosen language (founder, 16 Nov 2026); the rest stays word for word.
PART_ASK: Final = (
    "Rewrite only this part of the campaign's call script: {part}. Write it in {language}, as "
    "it should be spoken on the call. Leave every other part of the script exactly as it is. "
    "The main task and the owner's notes below say what the part must cover. "
    f"{GROUNDING_RULE} {PERSON_RULE}"
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
    "to 12 stages in all. Leave every other part of the script exactly as it is. "
    f"{PERSON_RULE}"
) + CLOSING_STEP

Tone = Literal["warm", "respectful", "brief"]
#: The owner's tone (D-1004), as the writer reads it. Keys are the request's `tone`.
TONES: Final[dict[str, str]] = {
    "warm": "friendly and warm, like a helpful neighbour, still polite",
    "respectful": "respectful and formal, with the polite address form the spoken-style "
    "guide gives",
    "brief": "short and direct, every line as few words as it can be",
}
#: The owner's note for one draft, in characters. Real rewrite notes (who the agent is, what
#: it says first, which English words stay, what it never claims) run 600 to 900 (founder,
#: 21 Nov 2026), so 1,000. The note is folded onto one line, so however long it is it stays
#: inside "THE OWNER ASKS:" and cannot start a heading of its own.
INSTRUCTION_MAX: Final = 1000


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


#: How the business has the people's numbers, by the campaign's declared consent source
#: (`campaigns.models.CONSENT_SOURCES`). `purchased_list` is refused at launch and has none.
_HOW_THEY_CAME: Final[dict[str, str]] = {
    "existing_customer": "they are the business's existing customers",
    "inbound_enquiry": "they contacted the business: called, messaged or filled its enquiry form",
    "web_form_optin": "they ticked a box on the business's web form to be contacted",
    "offline_form_optin": "they signed up on a paper form, at an event or in the shop",
}


def situation_block(
    *,
    agent_name: str = "",
    holder_name: str = "",
    purpose: str = "",
    goal: str = "",
    consent_source: str | None = None,
    inbound: bool = False,
) -> str:
    """The campaign's or line's own settings, so every line is written for this call and the
    review can check a claim against them: its name, why these people are called, what a good
    call ends with, how the business has their numbers, and the agent's name. "" when none."""
    rows = [
        (("Phone line: " if inbound else "Campaign name: "), holder_name),
        ("Why these people are called: ", purpose),
        ("A good call ends with: ", goal),
        ("The agent's name: ", agent_name),
    ]
    lines = [f"{label}{value.strip()}" for label, value in rows if value.strip()]
    came = _HOW_THEY_CAME.get(consent_source or "")
    if came:
        lines.append(
            f"How the business has their numbers: {came}. The agent may say so when asked how "
            "it got their number; it never tells the person what they did."
        )
    if not lines:
        return ""
    return ("THE LINE:\n" if inbound else "THE CAMPAIGN:\n") + "\n".join(lines) + "\n"


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
    situation: str = "",
) -> str:
    """What the script is written from: the ask, the owner's tone and instruction, the length
    it may take, the main task, the campaign's own settings (`situation_block`), the notes and
    the documents. A one-part rewrite replaces the whole ask, edit tail included."""
    lead = part_ask if part_ask is not None else f"{ask}{EDIT_TAIL if edit else ''}"
    change = (
        f"{lead}\n{tone_line(tone)}{instruction_line(instruction)}{length_line(budget)}"
        f"MAIN TASK:\n{main_task.strip()}\n{situation}"
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


#: The review pass (D-1004): a "why" per part, and a binary rubric over every part Pip wrote.
#: A second read, not the writer's own: a model rarely finds its own errors in the answer it
#: just gave (arxiv.org/abs/2310.01798). Each claim carries a word-for-word `evidence` quote
#: that `parsed_review` looks up in the sources itself, so the judge's leniency on sourcing
#: is overruled by text (platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/
#: reduce-hallucinations "Verify with citations"); the checks are yes/no rather than a score
#: (docs/evidence/script-generation-2026-11-21/GROUNDING.md rows 1, 5, 6).
REVIEW_INSTRUCTION: Final = (
    "You review a call script an assistant just wrote for a small business, before the owner "
    "reads it. You are given the SOURCES (the owner's main task, the campaign, the owner's "
    "facts and documents) and each part of the script with its key. Judge only against the "
    "SOURCES, never your own knowledge.\n"
    "1. notes: for each part, `why`: one plain English sentence of at most 20 words telling "
    "the owner why the part says what it says, naming the main task or the source it comes "
    "from by its title. Never name an AI company or model.\n"
    "2. claims: every statement of fact in a part: a price, amount, date, time, place, offer, "
    "discount, guarantee, rule, or anything about the person called (what they did, "
    "registered, bought or gave, or what records hold about them). `claim` names it in a few "
    "plain English words. `evidence` copies, word for word, the shortest passage of the "
    "SOURCES that states it, or is empty when no passage does. `about_person` is true when it "
    "is about the person called. `asked` is true when the line asks it as a question rather "
    "than telling it. A greeting, a question that states nothing, or a polite phrase is not a "
    "claim.\n"
    "3. problems: a part that clearly fails one of these, with `kind` and a few plain English "
    "words in `detail`: off_task (it does not help reach the main task); generic (it names "
    "nothing from this campaign, business, sources or the people called, and would fit any "
    "business's call; a greeting, a permission question and the close are never generic); "
    "repeats (it says what another part already says; `detail` names that part's key). Most "
    "parts fail none.\n"
    "Use only the keys given. Return ONLY JSON."
)
WHY_MAX: Final = 200
CLAIM_MAX: Final = 120
#: A ceiling, not a target: billing follows the tokens used. Notes, claims with their quotes
#: and problems for a twelve-step script run past the old 2,000.
REVIEW_MAX_TOKENS: Final = 4_000
#: Claims named per part in one finding; more only lengthens the repair's ask.
_CLAIMS_PER_PART: Final = 3

#: What each rubric failure says, in the shape of a script check finding's problem
#: ("<path>: <problem>"), so the targeted repair is asked with it and the owner reads it
#: (`script_proposals.fix_change`, `fix_left`). No brackets: `owner_rule` drops an aside.
UNSOURCED_PROBLEM: Final = (
    "says {claim}, which the main task and sources do not give; say only what they give, or "
    "leave it out"
)
ASSERTED_PROBLEM: Final = (
    "tells the person as a fact that {claim}; ask it as one short question they can answer, "
    "or leave it out"
)
WEAK_PROBLEMS: Final[dict[str, str]] = {
    "off_task": "does not help reach the main task: {detail}; make it serve the main task, or "
    "leave it out",
    "generic": "is a stock line that would fit any business's call: {detail}; say it with what "
    "this campaign is about",
    "repeats": "says again what another part already says: {detail}; say it once",
}

_REVIEW_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"part": {"type": "string"}, "why": {"type": "string"}},
    "required": ["part", "why"],
    "additionalProperties": False,
}
_CLAIM_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "part": {"type": "string"},
        "claim": {"type": "string"},
        "evidence": {"type": "string"},
        "about_person": {"type": "boolean"},
        "asked": {"type": "boolean"},
    },
    "required": ["part", "claim", "evidence", "about_person", "asked"],
    "additionalProperties": False,
}
_PROBLEM_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "part": {"type": "string"},
        "kind": {"type": "string", "enum": sorted(WEAK_PROBLEMS)},
        "detail": {"type": "string"},
    },
    "required": ["part", "kind", "detail"],
    "additionalProperties": False,
}
REVIEW_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "notes": {"type": "array", "items": _REVIEW_ROW},
        "claims": {"type": "array", "items": _CLAIM_ROW},
        "problems": {"type": "array", "items": _PROBLEM_ROW},
    },
    "required": ["notes", "claims", "problems"],
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


def review_sources(
    main_task: str,
    documents: str,
    facts: Sequence[str],
    *,
    situation: str = "",
    instruction: str = "",
    business_name: str = "",
) -> str:
    """Everything a spoken claim may come from, as the review reads it: the main task, the
    owner's ask for this draft, the campaign's settings, the business's name and facts, and
    the documents. A claim's evidence quote is looked up in exactly this text."""
    lines = [f"MAIN TASK:\n{main_task.strip()}"]
    said = instruction_line(instruction)
    if said:
        lines.append(said.rstrip("\n"))
    if situation:
        lines.append(situation.rstrip("\n"))
    if business_name.strip():
        lines.append(f"Business name: {business_name.strip()}")
    if facts:
        lines.append("THE OWNER'S FACTS:\n" + "\n".join(f"- {fact}" for fact in facts))
    if documents:
        lines.append(documents)
    return "\n".join(lines)


def review_request(parts: Sequence[ReviewedPart], sources: str) -> str:
    """The review pass's message: the sources (`review_sources`), then the parts by key."""
    lines = [f"SOURCES:\n{sources}", "THE SCRIPT'S PARTS:"]
    lines += [f"[{part.key}] {part.label}: {part.text}" for part in parts]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Review:
    """What the review pass found, by part key: a note, the claims no source backs, the claims
    about the person told rather than asked, and the parts that fail the rest of the rubric
    (each its problem sentence, `WEAK_PROBLEMS`)."""

    notes: dict[str, str] = field(default_factory=dict)
    unsourced: dict[str, str] = field(default_factory=dict)
    asserted: dict[str, str] = field(default_factory=dict)
    weak: dict[str, str] = field(default_factory=dict)

    def problems(self, key: str) -> list[str]:
        """The rubric's findings on one part, as problem sentences."""
        found = []
        if key in self.unsourced:
            found.append(UNSOURCED_PROBLEM.format(claim=self.unsourced[key]))
        if key in self.asserted:
            found.append(ASSERTED_PROBLEM.format(claim=self.asserted[key]))
        if key in self.weak:
            found.append(self.weak[key])
        return found

    def flagged(self) -> list[str]:
        """Every part key with a finding, in a stable order."""
        return sorted({*self.unsourced, *self.asserted, *self.weak})


def _plain(text: str) -> str:
    """`text` with case, punctuation and spacing gone, in any script: letters, marks (Telugu
    vowel signs are marks) and digits kept, so a quote copied with other spacing still
    matches."""
    kept = (
        ch if unicodedata.category(ch)[0] in "LMN" else " "
        for ch in unicodedata.normalize("NFC", text.casefold())
    )
    return " ".join("".join(kept).split())


def quoted_in(evidence: str, sources: str) -> bool:
    """Whether `evidence` is a passage of `sources`, word for word up to case, punctuation and
    spacing. A paraphrase does not count: the point is that the code, not the judge, decides
    a claim is sourced."""
    said = _plain(evidence)
    return bool(said) and f" {said} " in f" {_plain(sources)} "


def parsed_review(
    raw: dict[str, Any], keys: Sequence[str], *, allowed: str = "", sources: str = ""
) -> Review | None:
    """The review's JSON, kept to the keys it was given and cut to the screen's lengths; None
    when it holds no note, which the ladder counts as no answer. Text that names a technology
    company the owner did not is dropped: the owner reads it (D-679). A claim is unsourced
    unless its evidence is found in `sources` (`quoted_in`), whatever the review said."""
    known = set(keys)
    theirs = provider_words(allowed)

    def clean(said: object, limit: int) -> str:
        if not isinstance(said, str):
            return ""
        said = " ".join(said.split())[:limit]
        return said if said and not provider_words(said) - theirs else ""

    def rows(name: str) -> list[tuple[str, dict[str, Any]]]:
        value = raw.get(name)
        return [
            (row["part"], row)
            for row in (value if isinstance(value, list) else [])
            if isinstance(row, dict) and isinstance(row.get("part"), str) and row["part"] in known
        ]

    notes: dict[str, str] = {}
    for key, row in rows("notes"):
        if why := clean(row.get("why"), WHY_MAX):
            notes.setdefault(key, why)
    if not notes:
        return None
    unsourced: dict[str, list[str]] = {}
    asserted: dict[str, list[str]] = {}
    for key, row in rows("claims"):
        claim = clean(row.get("claim"), CLAIM_MAX)
        if not claim:
            continue
        evidence = row.get("evidence")
        if not (isinstance(evidence, str) and quoted_in(evidence, sources)):
            unsourced.setdefault(key, []).append(claim)
        if row.get("about_person") is True and row.get("asked") is not True:
            asserted.setdefault(key, []).append(claim)
    weak: dict[str, str] = {}
    for key, row in rows("problems"):
        shape = WEAK_PROBLEMS.get(str(row.get("kind")))
        detail = clean(row.get("detail"), CLAIM_MAX)
        if shape is not None and detail:
            weak.setdefault(key, shape.format(detail=detail.rstrip(".;")))

    def joined(found: dict[str, list[str]]) -> dict[str, str]:
        return {
            key: " and ".join(dict.fromkeys(said[:_CLAIMS_PER_PART])) for key, said in found.items()
        }

    return Review(notes=notes, unsourced=joined(unsourced), asserted=joined(asserted), weak=weak)


__all__ = [
    "ASSERTED_PROBLEM",
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
    "PERSON_RULE",
    "REVIEW_FORMAT",
    "REVIEW_INSTRUCTION",
    "SHORTEN_ASK",
    "SPECIFIC_RULE",
    "TONES",
    "TOO_LONG_RULE",
    "UNSOURCED_PROBLEM",
    "WEAK_PROBLEMS",
    "Review",
    "ReviewedPart",
    "Tone",
    "budget_of",
    "campaign_change",
    "instruction_line",
    "length_line",
    "owners_words",
    "parsed_review",
    "quoted_in",
    "review_request",
    "review_sources",
    "reviewed_parts",
    "situation_block",
    "tone_line",
]
