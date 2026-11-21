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

import re
from dataclasses import dataclass
from typing import Final

from calevate_shared.call_script import CallScript
from calevate_shared.opening_notices import (
    WOVEN_AI_CHARS,
    WOVEN_RECORDING_CHARS,
    opening_max_chars,
    says_ai,
    says_recorded,
)
from calevate_shared.spoken_guard import (
    HONORIFICS_PER_LINE,
    honorific_count,
    names_used,
    without_greeting,
)

from apps.api.agents.script_lint import NAME_FIELD, NAME_PLACEMENT_RULE, step_line
from apps.api.agents.turn_checks import (
    asked_opening_again,
    claims_done,
    claims_said_before,
    is_question,
    opened_again,
    reaction_lead,
    sentences,
)

#: The longest opening line an AI may write. The greeting is spoken on every call, so each
#: character is paid on every call (a Studio voice at the founder-attested ₹4.84 per 1,000
#: characters, 11 Oct 2026), and it shares the engine's 200-character greeting with the
#: notices (`agents/engine_limits`, D-846). The starter greetings in `spoken_style.json` are
#: about 70 characters before the business name; 120 leaves room for a long name and one
#: question. Voice platforms advise the same short opener ("Aim for 5-10 seconds", "Avoid
#: long company introductions": docs.autocalls.ai/ai-assistants/initial-message, 21 Oct 2026).
OPENING_LINE_MAX_CHARS: Final = 120
#: A placed call's opening also says the agent's name and the one reason for the call
#: (`PLACED_OPENING_RULE`), which 120 cannot hold in Telugu: the reviewed te-IN starter
#: (`spoken_style.json` `outbound`) is 87 characters with neither. Its total with woven notices
#: stays at `OPENING_CEILING_CHARS`, the most an answering opening already reaches; the
#: engine's own ceilings are still measured at save and publish
#: (docs/evidence/script-generation-2026-11-21/FLOW.md §2.4).
PLACED_OPENING_MAX_CHARS: Final = 160
OPENING_CEILING_CHARS: Final = OPENING_LINE_MAX_CHARS + WOVEN_AI_CHARS + WOVEN_RECORDING_CHARS


def opening_most(text: str, *, placed: bool = False) -> int:
    """The longest an opening line holding `text` may be: the room for a notice it says
    added, and, for a placed call's opening, the room for its name and reason."""
    if not placed:
        return opening_max_chars(OPENING_LINE_MAX_CHARS, text)
    return min(opening_max_chars(PLACED_OPENING_MAX_CHARS, text), OPENING_CEILING_CHARS)


#: A placed call's opening: who, why, then permission. Stating the reason is what the person
#: hangs up without (Varsha, 20-21 Nov 2026: "who are you, what name?"); sources and the
#: limits of the check in docs/evidence/script-generation-2026-11-21/FLOW.md.
PLACED_WHO_RULE: Final = (
    "say who is calling: the agent's name, written exactly as the brief gives it"
)
PLACED_REASON_RULE: Final = (
    "say the one reason for the call in a short sentence of its own, ending with a full stop, "
    "without the names again"
)
PLACED_OPENING_RULE: Final = (
    "says who is calling (the agent's name as the brief gives it, and the business), then "
    "the call's one reason from the brief without the names, then asks only whether they "
    "can talk now: short sentences, each ending with a full stop, the question last"
)

_MERGE_FIELD: Final = re.compile(r"\{\{[^}]*\}\}")


def _gives_reason(sentence: str, names: list[str]) -> bool:
    """A statement that can carry the call's reason: not a question, no name in it, not a
    notice, and two words or more once the greeting and merge fields are gone. Structure,
    not meaning: whether those words ARE the reason no check here can read in every
    language, so the writer is told it and this only refuses an opening with no room for
    it."""
    if is_question(sentence) or names_used(sentence, names):
        return False
    if says_ai(sentence) or says_recorded(sentence):
        return False
    rest = _MERGE_FIELD.sub(" ", without_greeting(sentence))
    return len([word for word in rest.split() if any(ch.isalnum() for ch in word)]) >= 2


def placed_opening_problems(
    where: str,
    text: str,
    *,
    agent_name: str = "",
    business_name: str = "",
    introduced: bool = False,
) -> list[str]:
    """What a placed call's opening line is missing of `PLACED_OPENING_RULE`: the agent's
    name (unless the agent's introduction just said it, `introduced`), and a sentence before
    the question for the reason. The name is matched as written, the only spelling the brief
    gives; a line that writes it in other letters is sent back to write it so."""
    found: list[str] = []
    name = agent_name.strip()
    if name and not introduced and not names_used(text, [name]):
        found.append(f"{where}: does not say who is calling; {PLACED_WHO_RULE}: {name}")
    names = [n.strip() for n in (agent_name, business_name) if n.strip()]
    if not any(_gives_reason(s, names) for s in sentences(text)):
        found.append(f"{where}: does not say why the call is made; {PLACED_REASON_RULE}")
    return found


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
            "or how the caller found the business, and never takes as given what the caller "
            "did, has or uses (that they use it, installed it, liked it or asked for it) "
            "unless they said so on this call or the call's details say so: an answer that "
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
    f"{OPENING_LINE_MAX_CHARS} characters, with no list of what the business offers and no "
    "offer. When the "
    "brief says the opening_line says the AI or recording notice, it says it in a few words "
    "of its own woven into the line (a few more characters are allowed for it); otherwise it "
    "says nothing about either. For an agent that only answers calls it "
    "greets, names the business and asks one short question; if it uses "
    f"{NAME_FIELD} at all, a comma follows it straight away, with no title. For an agent that "
    f"only places calls it greets the person by name with {NAME_FIELD} "
    f"({NAME_PLACEMENT_RULE}) and {PLACED_OPENING_RULE}, in at most "
    f"{PLACED_OPENING_MAX_CHARS} characters; the business's own questions wait until they "
    "say yes. When the brief says the agent introduces itself first, the opening_line "
    "neither greets nor names the agent or the business, and says only the reason and the "
    "question. For an agent that answers calls "
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
#: - Steps in the order their answers become possible, and only questions the caller can
#:   answer on that call: on the Rytu Khata call of 6 Nov 2026 the agent asked what the app
#:   was used for before helping install it, and how they liked it seconds after. Voice-agent
#:   guides ask for a linear script ("The AI follows linear structures much more reliably")
#:   and "Only ask absolutely necessary questions" (docs.telli.com/prompt-best-practices,
#:   read 6 Nov 2026). `script_lint.order_problems` checks the English instructions.
#: - A step's line does what its instruction says: the same script's "explain one feature"
#:   step had "I'll tell our team, they will help you" as its line, which the in-call model
#:   copies; the `done` rule above is about orders, not about every question.
#: - Each thing explained once: the call re-described the app three times and answered "how
#:   do I use it" with the description (`script_lint.repeated_line_problems`).
#: - A step that is not wanted is taken out, and a step for some callers is reached through
#:   a way out: asked to drop two steps, the edit writer kept them as "Not needed."
#:   (`script_lint.placeholder_problems`).
#: - Ask, then branch on the answer; never presume: the Rytu Khata script of 9 Nov 2026 led
#:   every caller to a step whose line said "you already use the app, right? what for?", and
#:   the agent said it to a caller who had only registered. The in-call model copies a step's
#:   line (OpenAI's realtime guide: the model "strongly closely follows sample phrases"), so a
#:   line that asserts the caller's state asserts it to every caller who reaches the step.
#:   Google's conversation design asks a question before relying on its answer and warns
#:   "Don't ask the user a question if you're not prepared to handle their answer"
#:   (developers.google.com/assistant/conversation-design/questions, read 9 Nov 2026).
#:   `script_lint.order_problems` checks that such a step is reached only through a way out
#:   whose condition says the caller uses it.
#: - After the opening, the purpose's order: situation asked, steps, done checked, the one
#:   next step. On the Varsha call of 21 Nov 2026 the first step said "you gave your name in
#:   the app" before any reason (docs/evidence/script-generation-2026-11-21/FLOW.md §2.5).
SCRIPT_FLOW_RULE: Final = (
    "Every detail to collect is asked in a stage, named in the instruction of the stage "
    "where the call reaches it, one question a turn, so none is left over at the end. "
    "Stages go in the order the call can reach them: nothing is asked before what it "
    "depends on has happened, and nothing the caller cannot answer yet is asked at all; "
    "someone who has only just set something up on this call is not asked how they use or "
    "like it, so those questions sit on the way for callers who said they use it, and after "
    "setting it up the agent shows the first thing to do. Nothing about the caller is taken "
    "as given (that they use it, have it, installed it, liked it, asked for it or enquired) "
    "unless the brief says every caller did: a stage that needs it is reached only through a "
    "way out whose condition says the caller said so, after a stage that asks it as a "
    "question and branches on the answer, or its instruction first asks it and goes on only "
    "if they say yes; either way its sounds_like asks rather than asserts. "
    "Having something, installing it or registering is not using it. The opening_line "
    "already greets, says who is calling and, on a call the agent places, why and whether "
    "now is a good time, so no stage does any of that again: the first stage starts from "
    "their yes, and its sounds_like neither greets nor asks again whether they can talk. "
    "Then the stages follow the purpose: ask, never state, what the call needs to know "
    "about the person's situation; the steps one at a time; check it is done; the last "
    "stage closes on the one next step. No two stages' sounds_like open with the same "
    "words, and no spoken line opens "
    "with a reaction (OK, good, very good, understood, happy) before its point; each opens "
    "with its own point, the answer, the step or the question. A "
    "stage that walks the caller through doing something puts each action in its "
    "procedure, one action an item, and the agent waits for the caller to say it is done "
    "before the next; never several actions in one instruction followed by asking whether "
    "they understood. Each stage's sounds_like does what that stage's instruction says: a "
    "stage that explains or answers says the answer from the knowledge and passes to the "
    "team only what the knowledge does not hold. Each thing is explained in one stage only; "
    "when the caller asks how to use it, the call moves to the stage that shows the first "
    "thing to do, never back to the description. A stage meant for some callers only is "
    "reached through a way out whose condition says who; a stage that is not wanted is "
    "left out of stages, never kept with a placeholder instruction or an empty line. A "
    "number the agent gives out is said slowly, a few digits "
    "at a time. The ending thanks them and says goodbye, with nothing about keeping a note "
    "or remembering the call."
)


def said_line_problem(
    where: str, text: str, *, opening: bool = False, close: bool = False, placed: bool = False
) -> str | None:
    """What breaks these rules in a line an AI wrote for the agent to say (an opening line, a
    "say" step, a sample phrase, the agent's side of an example call), or None. The same
    checks the practice tests run on the agent's replies (`turn_checks`), so a line the
    writer produced cannot teach the agent what the tests then fail. `close`: the call's last
    step, where thanks before the goodbye is the whole point of the line. `placed`: an
    opening on a call the agent places, with room for its name and reason (`opening_most`)."""
    if claims_done(text):
        return (
            f"{where}: says an order or details are noted or done; say the team will confirm "
            "instead."
        )
    if claims_said_before(text):
        return f'{where}: says "as I said"; the agent has said nothing before this line.'
    if (count := honorific_count(text)) > HONORIFICS_PER_LINE:
        return (
            f"{where}: says an honorific (andi, garu, ji, sir) {count} times; at most once in a "
            "line, where it fits, never at the end of every sentence."
        )
    if not close and (reaction := reaction_lead(text)) is not None:
        return (
            f'{where}: opens with the reaction "{reaction}"; the agent copies it into every '
            "reply. Start the line with its own point: the answer, the step or the question."
        )
    most = opening_most(text, placed=placed)
    if opening and len(text.strip()) > most:
        return (
            f"{where}: {len(text.strip())} characters; keep the opening line to one short "
            f"greeting and one question, at most {most} characters."
        )
    return None


def opening_redone_line_problems(script: CallScript) -> list[str]:
    """A step's spoken line that greets again or asks again whether now is a good time, in a
    script with an opening line: the practice check on the first replies
    (`turn_checks.opened_again`, `asked_opening_again`) run on the lines the in-call model
    copies. `script_lint.opening_redone_problems` reads only the English instructions, and on
    the Varsha call of 21 Nov 2026 (10:14) the first step's line greeted the person by name
    and asked whether they could talk, straight after the opening had asked."""
    openings = [line for line in (script.opening_line, script.outbound_opening_line) if line]
    if not any(line.strip() for line in openings):
        return []
    questions = [s for line in openings for s in sentences(line) if is_question(s)]
    found: list[str] = []
    for i in range(len(script.stages)):
        path, line = step_line(script, i)
        if not line.strip():
            continue
        if opened_again(line) or asked_opening_again(line, questions):
            found.append(
                f"{path}: greets again or asks again whether now is a good time, which the "
                "opening line already did; start this step from what comes after their yes."
            )
    return found


__all__ = [
    "CALL_RULES",
    "OPENING_CEILING_CHARS",
    "OPENING_LINE_MAX_CHARS",
    "OPENING_LINE_RULE",
    "PLACED_OPENING_MAX_CHARS",
    "PLACED_OPENING_RULE",
    "PLACED_REASON_RULE",
    "PLACED_WHO_RULE",
    "SCRIPT_FLOW_RULE",
    "CallRule",
    "expect_rules",
    "judge_rules",
    "opening_most",
    "opening_redone_line_problems",
    "placed_opening_problems",
    "said_line_problem",
    "writer_rules",
]
