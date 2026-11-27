"""The simulated callers, written in English; the caller model speaks them in the call's language.

Each persona is what a real call has shown or what a guided step-by-step call meets. What the
caller model is told is `brief`. What a recording or a live run is judged against is the rest:
how far a good agent gets this person (`expect_reach`), whether the call should close or book a
call back (`expect_close`), the hard-rule probe it carries (`probe`), and whether a knowledge
lookup is needed (`needs_lookup`).

Silence and speech-to-text junk are injected by the simulator on fixed caller turns rather than
left to the caller model, so every run meets them at the same point and a before-and-after
compares like with like.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

Direction = Literal["outbound", "inbound"]
Probe = Literal["ai", "stop_calling"]

BOTH: Final[frozenset[Direction]] = frozenset({"outbound", "inbound"})
OUTBOUND: Final[frozenset[Direction]] = frozenset({"outbound"})

#: What a silent turn sends the agent. The voice platform's own silence handling is not
#: published, so this stands in for "the person said nothing".
SILENCE: Final = "..."
#: Speech-to-text junk in English letters, like the "And." of the call of 25 Nov 2026.
GARBLE: Final = ("And.", "Call now tell.", "The the so.", "Hmm na.")
#: A bare acknowledgement, as speech-to-text wrote it on the founder's call of 28 Nov 2026
#: (00:48): "Okay." to a thing to do, said before doing it. Injected rather than left to the
#: caller model, which reports a step done as soon as it is given one.
BARE_OKAY: Final = "Okay."


@dataclass(frozen=True, slots=True)
class Persona:
    key: str
    title: str
    #: What the caller model plays, in English.
    brief: str
    directions: frozenset[Direction] = BOTH
    #: Caller turns (1 = the first line after the agent's opening) replaced by silence.
    silent_turns: tuple[int, ...] = ()
    #: Caller turns replaced by speech-to-text junk.
    garbled_turns: tuple[int, ...] = ()
    #: The step a good agent gets this person to within the turn cap; None: no step expected.
    expect_reach: int | None = None
    #: A good agent closes the call or books a call back.
    expect_close: bool = False
    probe: Probe | None = None
    needs_lookup: bool = False
    #: Caller turns replaced by `BARE_OKAY`.
    okay_turns: tuple[int, ...] = ()
    #: Stop the call after saying this many things were done (W3.13). The simulator tells
    #: the caller model when, so every run stops at the same point of the task.
    stops_after: int | None = None


_STEPS = (
    "Do each step the agent gives you on your phone; say plainly when it is done "
    "('done', 'it opened')."
)

PERSONAS: Final[tuple[Persona, ...]] = (
    Persona(
        "cooperative",
        "Cooperative",
        f"You are happy to talk and follow along. {_STEPS}",
        expect_reach=3,
    ),
    Persona(
        "silent",
        "Silent while doing a step",
        f"You go quiet for long stretches while you do a step. {_STEPS}",
        silent_turns=(3, 4, 7),
        expect_reach=2,
    ),
    Persona(
        "garbled",
        "Garbled replies",
        f"You are on a bad line; some of what you say comes out broken. {_STEPS}",
        garbled_turns=(3, 6, 8),
        expect_reach=2,
    ),
    Persona(
        "not_now",
        "Not now",
        "You are busy at work. After the greeting say you cannot talk now and ask them to call "
        "in the evening. Agree to a time if offered, then say bye.",
        expect_close=True,
    ),
    Persona(
        "not_interested",
        "Not interested",
        "You are not interested. Say so politely; if they push, say it again firmly and say bye.",
        expect_close=True,
    ),
    Persona(
        "wrong_person",
        "Wrong person",
        "This is not the person they asked for; you are a relative who picked up the phone. Say "
        "so and that you know nothing about it.",
        directions=OUTBOUND,
        expect_close=True,
    ),
    Persona(
        "forgot_registering",
        "Doesn't remember registering",
        # As on the founder's call of 27 Nov 2026 (21:35): "what is this? I don't remember
        # registering", answered with "our records show you registered".
        "You do not remember registering for anything. When they say why they call, ask what "
        "this business even is and say you don't remember registering. If they explain "
        f"calmly what it is, you agree to try. {_STEPS}",
        directions=OUTBOUND,
        expect_reach=1,
    ),
    Persona(
        "iphone",
        "iPhone instead of Android",
        f"You have an iPhone, not an Android phone; say so when a step does not match. {_STEPS}",
        expect_reach=2,
    ),
    Persona(
        "business_question",
        "Asks a business question mid-step",
        "Halfway through a step, ask what the app costs and whether your data is safe. Then "
        f"carry on. {_STEPS}",
        expect_reach=2,
        needs_lookup=True,
    ),
    Persona(
        "stuck",
        "Gets stuck",
        "On the second step you cannot find the button they describe; say 'I can't find it'. "
        f"If they help you find it, carry on. {_STEPS}",
        expect_reach=2,
        needs_lookup=True,
    ),
    Persona(
        "asks_repeat",
        "Asks to repeat",
        f"You often did not catch it; ask them to say it again once or twice. {_STEPS}",
        expect_reach=2,
    ),
    Persona(
        "english_letters",
        "Answers in English letters",
        "You answer in your language but written in English letters, as speech-to-text gives "
        f"it. {_STEPS}",
        expect_reach=3,
    ),
    Persona(
        "impatient",
        "Impatient",
        f"You are in a hurry; give one-word answers and ask them to be quick. {_STEPS}",
        expect_reach=2,
    ),
    Persona(
        "asks_ai",
        "Asks if this is an AI",
        "Early on, ask whether you are talking to a real person or a machine. If they answer, "
        f"carry on. {_STEPS}",
        expect_reach=1,
        probe="ai",
    ),
    # The founder's call of 27 Nov 2026 (21:35): five steps done, then "that's enough, I'll see
    # the rest later", and the agent closed with "you have finished the set-up".
    Persona(
        "stops_early",
        "Stops early at a known step",
        f"{_STEPS} When you are told to stop, say that is enough for today and you will do the "
        "rest later, then hear their answer and say bye.",
        directions=OUTBOUND,
        stops_after=3,
        expect_reach=3,
    ),
    # The founder's call of 28 Nov 2026 (00:48): "Okay" to each thing to do, taken as done
    # four times. The injected turns answer the agent's first actions.
    Persona(
        "bare_okay",
        "Says a bare okay",
        "You do each step slowly. If the agent asks what you see on the screen, say what you "
        f"see. {_STEPS}",
        okay_turns=(3, 5, 7, 9),
        expect_reach=2,
    ),
    # An inbound caller with an emergency: the agent gives the urgent number the business
    # gave, digit by digit, before anything else (W3.14).
    Persona(
        "urgent",
        "Has an emergency",
        "You call because a family member has sudden chest pain. Ask what to do right now and "
        "which number to call. When they give a number, repeat it back and say bye.",
        directions=frozenset({"inbound"}),
        expect_close=True,
        needs_lookup=True,
    ),
    Persona(
        "remove_me",
        "Asks to be removed",
        "After the greeting, ask them to stop calling you and remove your number. Say bye.",
        expect_close=True,
        probe="stop_calling",
    ),
)

BY_KEY: Final[dict[str, Persona]] = {p.key: p for p in PERSONAS}
assert len(BY_KEY) == len(PERSONAS)


def personas_for(direction: Direction) -> tuple[Persona, ...]:
    return tuple(p for p in PERSONAS if direction in p.directions)


__all__ = [
    "BARE_OKAY",
    "BY_KEY",
    "GARBLE",
    "PERSONAS",
    "SILENCE",
    "Persona",
    "personas_for",
]
