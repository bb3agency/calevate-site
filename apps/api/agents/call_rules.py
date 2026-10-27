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
            '("two kg or two packets?"), is right, not a repeat.'
        ),
        writer="Ask only for the listed details, and only those the caller has not already said.",
        expect="",
        prompt_marker="Never re-ask what they said",
    ),
    CallRule(
        key="own_part",
        # D-856: a half answer gets the agent's reading offered as a question, the way the
        # competitor call the founder judged natural handled "ఒక" (one...), not a bare "go on".
        judge=(
            "It says only its own part, never the caller's. When the caller breaks off "
            'mid-answer, offering its reading as a question with a way out ("one kg, or '
            'more?") and waiting is right; finishing their sentence or acting on a guess is '
            "not."
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
    """The rules as every writer of a script, an edit or a spoken line reads them."""
    return " ".join(rule.writer for rule in CALL_RULES)


def expect_rules() -> str:
    """What a practice caller's expected outcome must allow."""
    return " ".join(rule.expect for rule in CALL_RULES if rule.expect)


#: The opening line's own rule, for a writer that writes or edits it.
OPENING_LINE_RULE: Final = (
    "The opening_line greets, names the business and asks one short question, in at most "
    f"{OPENING_LINE_MAX_CHARS} characters: no list of products, no offer, and no AI or "
    "recording notice (the platform adds those). When the brief says the agent introduces "
    "itself first, the opening_line neither greets nor names the agent or the business."
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
    if opening and len(text.strip()) > OPENING_LINE_MAX_CHARS:
        return (
            f"{where}: {len(text.strip())} characters; keep the opening line to one short "
            f"greeting and one question, at most {OPENING_LINE_MAX_CHARS} characters."
        )
    return None


__all__ = [
    "CALL_RULES",
    "OPENING_LINE_MAX_CHARS",
    "OPENING_LINE_RULE",
    "CallRule",
    "expect_rules",
    "judge_rules",
    "said_line_problem",
    "writer_rules",
]
