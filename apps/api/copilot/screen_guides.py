"""How Pip leads on a screen built around a conversation with it (D-854).

The first-agent screen (`/c/{slug}/agents/first`) is a chat with Pip beside a card that
fills in as the agent takes shape. Pip has to LEAD there, one short question at a time, in
the order the card fills, which is not how it behaves anywhere else. That instruction is
ours and trusted, so it cannot travel in the SCREEN STATE (content, never instructions), and
it is per-screen, so it cannot sit in the cached prefix (`prompt_budget_test` holds the
system prompt and tool array byte-identical across screens). It goes in the last user
message, after the screen and before the closing rules, only when the route matches.

The card's progress is recomputed from the server's rows each time, so the guide tells Pip
to read what is done from the SCREEN STATE rather than from the conversation: a person who
left half way, or built a piece by hand, is picked up where the card says they are.
"""

from __future__ import annotations

import re
from typing import Final

#: The route the first-agent screen declares, with the slug or its `{slug}` template.
FIRST_AGENT_ROUTE: Final = re.compile(r"^/c/[^/]+/agents/first/?$")

#: The greeting ceiling the first-agent screen counts toward (D-846's advice to keep the
#: opening short enough that the notices still fit). The web card reads the same number.
FIRST_GREETING_MAX_CHARS: Final = 120

FIRST_AGENT_GUIDE: Final = (
    "--- FIRST AGENT (Calevate's guide for this screen) ---\n"
    "The person is building their first agent with you; the card beside this chat shows each "
    "piece as it lands. Lead, one short question per message, in this order, skipping any "
    "piece the SCREEN STATE marks done:\n"
    "1. Its job: answer their calls, call new leads within minutes of their enquiry, or call "
    "a list of people who showed interest.\n"
    "2. Its name (offer one that fits the business) and the language callers speak. Then "
    "call `agent_create` with `job` (`answer_calls`, `call_new_leads` or `call_leads`).\n"
    "3. Its voice: call `voices_offered`, offer two or three by name, and set the one they "
    "pick with `agent_edit`. They can press Hear it on the card.\n"
    "4. Its greeting: quote the opening line from the SCREEN STATE and offer a version in "
    f"the agent's language, under {FIRST_GREETING_MAX_CHARS} characters, ending with a "
    "question; set it with `agent_edit` `opening_line` once they agree.\n"
    "5. The three things callers ask most, and the answer to each in their words; then one "
    "`knowledge_facts_pin` with all three.\n"
    "6. What it notes down: name the details from the SCREEN STATE and ask whether one is "
    "missing; change them with `agent_capture_fields_set` only if they say so.\n"
    "7. Then tell them to type their number on the card and press the call button to hear it.\n"
    "Two sentences at most. Offer choices from this business's own examples in the SCREEN "
    "STATE. Never invent a price, time or answer: ask. If they say skip, go to the next piece."
)


def screen_guide(route: str) -> str:
    """The guide for this screen's route, or "" for every screen that has none."""
    return FIRST_AGENT_GUIDE if FIRST_AGENT_ROUTE.match(route) else ""


__all__ = [
    "FIRST_AGENT_GUIDE",
    "FIRST_AGENT_ROUTE",
    "FIRST_GREETING_MAX_CHARS",
    "screen_guide",
]
