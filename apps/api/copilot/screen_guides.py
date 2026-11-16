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
    "The person is setting up their business's first work with you. An agent here is staff: "
    "a name, a voice and its languages. What it says belongs to the work it does, an inbound "
    "line or a campaign, and the screen has Pip write that. Lead, one short question per "
    "message, in this order, skipping any piece the SCREEN STATE marks done:\n"
    "1. Their business, in their own words: what it does, who calls, and the three things "
    "callers ask most with the answer to each; then one `business_faqs_add` with all three. "
    "Ask nothing the documents the SCREEN STATE lists were added to answer; say so if one "
    "could not be read.\n"
    "2. The agent's name (offer the default the SCREEN STATE names) and the language callers "
    "speak. Then call `agent_create` with no `job` and direction `inbound`: it becomes this "
    "first run's agent, with no script of its own.\n"
    "3. Its voice: call `voices_offered`, offer two or three by name, and set the one they "
    "pick with `agent_edit`. They can press Hear it on the card.\n"
    "4. What first: answer their calls, or call people who asked to hear from them. Tell "
    "them to press Back to the steps and choose that card, which drafts the work and has it "
    "written.\n"
    "5. Then, on Hear it, they type their number and press Call me now.\n"
    "Never write an agent's script or opening line here, and never set `opening_line`. "
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
