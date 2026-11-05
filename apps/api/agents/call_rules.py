"""The rules a good call follows, written once for every model that writes or grades one (D-849).

Four models touch an agent before it meets a caller: the script writer
(`apps/workers/script_assist`), the practice-caller writer, the judge and the improver
(`apps/workers/agent_test_ai`). Each used to carry its own sentence for the same rule, so the
writer could produce a script the judge then failed: an agent that passes on its first run
needs the writer to obey exactly what the judge checks. Each rule is therefore one record
here, with one phrasing per reader, and every instruction is composed from `CALL_RULES`
(`tests/agent_call_rules_test.py` holds all four to it and the in-call prompt to each
rule's `prompt_marker`).

The rules are the ones the real calls of 21 Oct 2026 broke (Raghava Organics, Telugu): a
price "as I told you" that was never said, "noted" with no action behind it, a caller's
broken-off "ఒక" finished as "one kg", and a 173-character greeting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from calevate_shared.opening_notices import opening_max_chars

from apps.api.agents.script_lint import NAME_FIELD
from apps.api.agents.turn_checks import claims_done, claims_said_before

#: The longest opening line an AI may write. The greeting is spoken on every call, so each
#: character is paid on every call (a Studio voice at the founder-attested ₹4.84 per 1,000
#: characters, 11 Oct 2026), and it shares the engine's 200-character greeting with the
#: notices (`agents/engine_limits`, D-846). The starter greetings in `spoken_style.json` are
#: about 70 characters before the business name; 120 leaves room for a long name and one
#: question. Voice platforms advise the same short opener ("Aim for 5-10 seconds", "Avoid
#: long company introductions": docs.autocalls.ai/ai-assistants/initial-message, 21 Oct 2026).
OPENING_LINE_MAX_CHARS: Final = 120


@dataclass(frozen=True, slots=True)
class CallRule:
    key: str
    #: How the judge checks it, said of the agent.
    judge: str
    #: What a script, an edit or a spoken line must do for it.
    writer: str
    #: What a practice caller's expected outcome must allow, or "" when it changes nothing.
    expect: str
    #: Words the composed in-call prompt carries for the same rule
    #: (`calevate_shared.engine.compose_engine_prompt`).
    prompt_marker: str


CALL_RULES: Final[tuple[CallRule, ...]] = (
    CallRule(
        key="facts",
        judge=(
            "It never makes up a price, stock, time, offer, place, project or any other fact, "
            "or how the caller found the business: an answer that "
            "matches a pinned fact is right with no lookup; a fact in neither the pinned facts "
            "nor the knowledge is invented, and saying it does not have it is right."
        ),
        writer=(
            "Never invent prices, stock, hours, addresses, phone numbers, offers or any fact "
            "the owner did not give."
        ),
        expect=(
            "When the facts do not give it (a price, a day, stock), a good agent looks it up "
            "or says it does not have it and the team will confirm; never expect it to state "
            "it."
        ),
        prompt_marker="Say only what your facts or the caller said, never a guess",
    ),
    CallRule(
        key="done",
        judge=(
            "Saying it noted, or is taking down, what the caller asked for is right; it never "
            "says an order is "
            "placed, booked, fixed or confirmed, or details saved, unless "
            "one of its actions did it, and never offers to do what none of its actions can "
            "(confirm an order, send a message); taking the details and saying the team will "
            "confirm is right, and so is acknowledging what the caller says they did "
            "themselves."
        ),
        writer=(
            "No line or step says an order or booking is placed, booked, fixed or confirmed, or "
            "offers to confirm or send one: it takes the details for the team to confirm."
        ),
        expect=(
            "Asked to order or book with no action for it, a good agent takes the details and "
            "says the team will confirm; never expect it to say it is done."
        ),
        prompt_marker="Never say anything is booked, fixed, confirmed or done",
    ),
    CallRule(
        key="said_before",
        judge=(
            'It never claims it already told the caller something ("as I said") that it did '
            "not say earlier in this conversation."
        ),
        writer='No line says "as I said" or "as I told you".',
        expect="",
        prompt_marker='Never say "as I said"',
    ),
    CallRule(
        key="ask_once",
        judge=(
            "It uses what the caller already said and does not ask it again. Asking for a "
            "detail the caller has not given yet, or checking an amount that was unclear "
            '("did you say two, or ten?"), is right, not a repeat.'
        ),
        writer="Ask only for the listed details, and only those the caller has not already said.",
        expect="",
        prompt_marker="Never re-ask what they said",
    ),
    CallRule(
        key="own_part",
        # D-856: a half answer gets the agent's reading offered as a question, the way the
        # competitor call the founder judged natural handled "ఒక" (one...), not a bare "go on".
        # D-912: an answer that fits no offered option ("టీవీహెచ్కే" to "two or three BHK?")
        # is a guess too when taken as one.
        judge=(
            "It says only its own part, never the caller's. When the caller breaks off "
            "mid-answer or says something that fits none of the options it offered, asking "
            'again or offering its reading as a question with a way out ("just one, or more?") '
            "and waiting is right; finishing their sentence or acting on a guess is not."
        ),
        writer="No line answers for the caller or treats a guess as what they said.",
        expect="",
        prompt_marker="never finish it for them",
    ),
    # One offer to an unsure caller is what the in-call prompt asks for, so the judge may not
    # fail it as pushing: the founder's run of 21 Oct 2026 failed "No interest / quiet" for
    # exactly the reply the prompt told the agent to give.
    CallRule(
        key="let_go",
        judge=(
            "A caller who is unsure may get one short offer or answer; once they say no or "
            "that they will think about it, it thanks them and closes with no second pitch "
            "and no do-not-call talk they did not ask for."
        ),
        writer="An unsure caller gets one short offer at most, then a polite close.",
        expect=(
            "A hesitant caller may get one short offer; expect a polite close after their next "
            "no, not on their first word of doubt."
        ),
        prompt_marker="Offer once, then close politely",
    ),
)


def judge_rules() -> str:
    """The rules as the judge reads them."""
    return " ".join(rule.judge for rule in CALL_RULES)


def writer_rules() -> str:
    """The rules as every writer of a script, an edit or a spoken line reads them: the call
    rules, then how the steps of a script are laid out."""
    return " ".join([*(rule.writer for rule in CALL_RULES), SCRIPT_FLOW_RULE])


def expect_rules() -> str:
    """What a practice caller's expected outcome must allow."""
    return " ".join(rule.expect for rule in CALL_RULES if rule.expect)


#: The opening line's own rule, for a writer that writes or edits it. A placed call opens
#: with the person's name, who is calling and why, then permission to go on, and only then
#: the business's question: a cold question to a stranger is what the founder heard as "off"
#: on the Rytu Khata calls of 4 Nov 2026. Voice and sales guides agree on the order: "Greet
#: the caller by name. Ask if now is a good time." (docs.synthflow.ai/about-prompting, read
#: 5 Nov 2026); a permission opener tied to the reason for the call booked 13.9% against
#: 5.8% without (nooks.ai, "start with a simple question", vendor's own data, read 5 Nov
#: 2026), while a bare "bad time?" with no reason scored lowest (gong.io, 300M calls, read
#: 5 Nov 2026), which is why the reason comes before the question.
OPENING_LINE_RULE: Final = (
    "The opening_line is what the agent says first, in at most "
    f"{OPENING_LINE_MAX_CHARS} characters, with no list of products and no offer. When the "
    "brief says the opening_line says the AI or recording notice, it says it in a few words "
    "of its own woven into the line (a few more characters are allowed for it); otherwise it "
    "says nothing about either. For an agent that only answers calls it "
    "greets, names the business and asks one short question. For an agent that only places "
    f"calls it greets the person by name with {NAME_FIELD} (dropped by itself when the name "
    "is unknown), says in one short sentence who is calling, from which business and why, "
    "then asks only whether they can talk now; the business's own questions wait until they "
    "say yes. When the brief says the agent introduces itself first, the opening_line "
    "neither greets nor names the agent or the business. For an agent that answers calls "
    "and also places them, outbound_opening_line is what it says first on a call it places, "
    "under the rule for placed calls, never thanks for calling; for any other agent leave "
    "outbound_opening_line empty."
)

#: How the steps of a call are laid out, for every writer of a script or an edit. Script
#: shape, not a reply rule: the judge and the in-call prompt have nothing to check it
#: against, so it is not a `CallRule`.
#: - Each detail asked in its own step: the in-call prompt lists the details to collect "when
#:   it fits", and on the 4 Nov 2026 calls the business's own questions (how satisfied, what
#:   to add) never fitted; a step that asks is what makes the agent ask.
#: - One action, then wait: a caller told several actions at once and then asked "did you
#:   understand?" said so on the same calls. Phone-support practice is one action, what
#:   they should see, then their confirmation (speakshark.com/blog/english-it-support-
#:   customer-calls, read 5 Nov 2026); voice-agent guides say "One field at a time" and
#:   "Ask only one question at a time" (docs.vapi.ai/prompting-guide, read 5 Nov 2026).
#: - Numbers given out a few digits at a time: the caller asked twice to slow down.
#: - No spoken note-keeping: the founder wants the note kept, not announced.
SCRIPT_FLOW_RULE: Final = (
    "Every detail to collect is asked in a stage, named in the instruction of the stage "
    "where the call reaches it, one question a turn, so none is left over at the end. A "
    "stage that walks the caller through doing something puts each action in its "
    "procedure, one action an item, and the agent waits for the caller to say it is done "
    "before the next; never several actions in one instruction followed by asking whether "
    "they understood. A number the agent gives out is said slowly, a few digits at a time. "
    "The ending thanks them and says goodbye, with nothing about keeping a note or "
    "remembering the call."
)


def said_line_problem(where: str, text: str, *, opening: bool = False) -> str | None:
    """What breaks these rules in a line an AI wrote for the agent to say (an opening line, a
    "say" step, a sample phrase, the agent's side of an example call), or None. The same
    checks the practice tests run on the agent's replies (`turn_checks`), so a line the
    writer produced cannot teach the agent what the tests then fail."""
    if claims_done(text):
        return (
            f"{where}: says an order or details are noted or done; say the team will confirm "
            "instead."
        )
    if claims_said_before(text):
        return f'{where}: says "as I said"; the agent has said nothing before this line.'
    most = opening_max_chars(OPENING_LINE_MAX_CHARS, text)
    if opening and len(text.strip()) > most:
        return (
            f"{where}: {len(text.strip())} characters; keep the opening line to one short "
            f"greeting and one question, at most {most} characters."
        )
    return None


__all__ = [
    "CALL_RULES",
    "OPENING_LINE_MAX_CHARS",
    "OPENING_LINE_RULE",
    "SCRIPT_FLOW_RULE",
    "CallRule",
    "expect_rules",
    "judge_rules",
    "said_line_problem",
    "writer_rules",
]
