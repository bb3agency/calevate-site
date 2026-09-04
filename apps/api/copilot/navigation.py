"""THE ONE TOOL THAT MOVES SOMEBODY — `open_screen`, and the four things that have to be
true before a route reaches a browser. D-524, closing D-523.

═══ THE DEFECT ═══

    Client:   Take me to billing page
    Copilot:  I cannot take you to the billing page. I can only show you the current
              page, which is about calling credit.

D-522 gave the assistant the console's inventory (`screens.py`), so it can now answer
*where* a screen is — "Calling credit, under Settings & account in the left sidebar". It
still could not answer *take me there*, and D-523 recorded exactly what closes that: an
event on the ask stream, a browser that acts on it, and a decision about which tier a
screen change stands behind.

═══ THE TIER: 1, BY THE CONTRACT'S OWN TEST ═══

`actions.py` splits actions on one question — does it reach a caller or spend money? A
screen change does neither, and it is reversible with the back button, so it is a **Tier 1
receipt** and not a Tier 2 proposal. A Confirm button in front of every screen change would
make the feature worse than the refusal it replaces: nobody wants to approve a move they
just asked for.

**IT IS NOT AN `ActionTool`, AND THAT IS DELIBERATE.** Every member of `WRITE_TOOLS` runs a
service function under the tenant's RLS session, claims an idempotency record and writes an
`audit_log` row in the same transaction as its change. Navigation changes nothing in the
database, so all three would be machinery around an act that does not exist — and
`audit_log` is APPEND-ONLY and hash-chained (hard rule 4), so putting a row on that chain
every time somebody asked to see their leads would make a permanent, undeletable record out
of a mouse movement. What it DOES share with the tier is the shape the person sees: a
receipt saying what happened, where the result is, and how to take it back.

═══ WHAT THE MODEL MAY SAY, AND WHY A PATH IS NOT IN IT ═══

The tool takes a screen's **NAME** — "Calling credit" — and never a route. That is the whole
open-redirect argument, and it is structural rather than filtered: no path-shaped value
crosses the model boundary in either direction, so there is nothing a crafted `SCREEN STATE`
block (untrusted, fenced, and full of a tenant's own text) could make the model emit that
would become a destination. The route the browser receives is a CONSTANT looked up in
`CLIENT_SCREENS`; the only string the model contributed is the key that was looked up. An
unknown key is a refusal, never a redirect.

The slug is not substituted here. A declaring screen sends the TEMPLATE (`/c/{slug}/credits`,
`lib/copilot/registry.ts`) and the slug never reaches this server on this path at all, so the
wire carries the template and the browser substitutes its own — and then checks the result
against `lib/clientNav.ts` before it moves, so a route this server could not have emitted
cannot navigate either. Two closed lists, one on each side.

═══ THE THREE REFUSALS, AND WHY EACH IS FED BACK RATHER THAN SHOWN ═══

A refusal here goes back to the MODEL as a tool result (`service.py`'s loop), the way a
refused fill does, because each of them has a sentence the person actually needs and the
model is what composes it:

* **No such screen.** The name was not in the inventory. The model has the full list in its
  prompt and can correct itself inside the turn cap.
* **Their role cannot open it.** Read from `core/rbac.ROLE_PERMISSIONS`, the table the API
  itself refuses with — never from a list this module keeps. **Navigating somebody to a
  screen that then refuses them is worse than not navigating**, and the honest answer
  ("Invoice is the account owner's") is one the model relays.
* **They are already there.** `screens.match_route` normalises both spellings of a route to
  one key, so this is decidable. Moving somebody to where they are standing would be a
  flicker and a wasted back-button entry; "you are already on it, here is what to do" is the
  answer.

═══ WHAT THIS MODULE DOES NOT DECIDE: WHETHER IT IS SAFE TO GO ═══

**The server knows a form EXISTS on the current screen — the request declares its `fields`.
Only the browser knows whether it is DIRTY.** So this module decides the DESTINATION and
stops there; the browser owns the "you will lose what you typed" question, asks before it
moves whenever it cannot rule unsaved work out, and is the only half that can
(`lib/copilot/unsaved.ts`). That is why the `detail` sentence below says the screen is being
OPENED rather than that the person has arrived — the server is not entitled to the second
claim.
"""

from __future__ import annotations

import json
from typing import Any, Final

from apps.api.copilot.prompt import function_tool
from apps.api.copilot.schemas import CopilotNavigateEvent
from apps.api.copilot.screens import CLIENT_SCREENS, Screen, match_route, where_is
from apps.api.core.rbac import ROLE_PERMISSIONS, role_has

#: The name the tool travels under. One tool, and it is the whole navigation surface.
OPEN_SCREEN_TOOL_NAME: Final = "open_screen"

#: HOW MANY SCREEN CHANGES ONE ANSWER MAY MAKE. One. A second destination in the same answer
#: is a flicker through a screen nobody read and a back button that no longer returns where
#: the person expects — the same "one act per turn" rule `set_fields` and the proposal path
#: already keep, for the same reason.
MAX_NAVIGATIONS_PER_RUN: Final = 1


class NavigationRefusedError(Exception):
    """The screen change cannot happen, in a way the model could FIX or must RELAY.

    Sibling of `service.FillRefusedError` and `actions.WriteRefusedError`, and it exists for
    their reason: the refusal is handed back as a tool result so the assistant can say the
    true thing ("Invoice is the account owner's") instead of a dead end reaching the person
    as an interrupted stream.

    `reason` names screens and roles — never a value, never a route (hard rule 6, and the
    founder's ban on route paths in client-facing text: this string is quoted back to the
    person by the model).
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def open_screen_tool() -> dict[str, Any]:
    """The tool definition — STATIC, and part of the cacheable prefix (`prompt.py` point 1).

    A function rather than a constant for `prompt.set_fields_tool`'s reasons: mypy checks the
    shape, no request can mutate what a previous one sent, and `tool_array` composes it from
    an unchanging literal.

    THE ARGUMENT IS A NAME AND THE DESCRIPTION SAYS SO TWICE, because the one failure mode
    worth spending words on is a model that invents a plausible screen ("Billing") instead of
    using ours ("Calling credit") — which is the exact defect D-522 was about, one layer on.
    It is deliberately not a schema `enum` of the screen names: an enum is the strongest
    anti-invention lever available and it is not what keeps this safe — `resolve_destination`
    refuses an unknown name whether or not the model was constrained, exactly as
    `validate_fill` does for a select — and spelling 28 names into the tool array a second
    time is a second copy of the directory that can drift from the first.
    """
    return function_tool(
        name=OPEN_SCREEN_TOOL_NAME,
        description=(
            "Open one of this console's screens in the person's browser — use this when "
            "they ask to be taken somewhere ('take me to billing', 'open my leads', 'show "
            "me the campaigns page').\n"
            "Pass the screen's NAME exactly as it appears in THE SCREENS OF THIS CONSOLE "
            "above — 'Calling credit', not 'Billing', and never an address. If they used "
            "their own word for it, translate it to our name first.\n"
            "This DOES it: the console opens the screen straight away, and asks them first "
            "only if they have unsaved work on the screen they are leaving. Say you are "
            "opening it — never that they have arrived, and never that you cannot. If they "
            "only asked WHERE something is, do not call this: say the name and where it sits."
        ),
        parameters={
            "type": "object",
            "properties": {
                "screen": {
                    "type": "string",
                    "description": (
                        "The screen's name from the list, e.g. 'Calling credit', 'Leads', "
                        "'Do not call'."
                    ),
                }
            },
            "required": ["screen"],
            "additionalProperties": False,
        },
    )


def find_screen(named: str) -> Screen | None:
    """The screen a person means by `named`, or None.

    Our NAME first, then the client's own words (`Screen.aliases`) — the two vocabularies
    `render_directory` already teaches the model to answer in, so a model that copies the
    person's word instead of ours ("billing") lands on the right screen rather than on a
    refusal it has to spend a turn correcting. `screens_test.py` enforces that no two screens
    claim one alias, which is what makes the second lookup single-valued.

    Case- and space-insensitive: "calling credit" and " Calling  Credit " are the same
    request, and refusing on capitalisation would be this module inventing a rule nobody
    agreed to. Names are checked BEFORE aliases in full, so a name can never lose to another
    screen's alias.
    """
    key = " ".join(named.split()).casefold()
    if key == "":
        return None
    for screen in CLIENT_SCREENS:
        if screen.name.casefold() == key:
            return screen
    for screen in CLIENT_SCREENS:
        if any(alias.casefold() == key for alias in screen.aliases):
            return screen
    return None


def _may_open(screen: Screen, role: str | None) -> bool:
    """May this role open this screen? Read off `core/rbac.ROLE_PERMISSIONS`.

    `role is None` — a run nobody named, which production does not produce (`routes.py`
    asserts a role before it composes the viewer) — is refused rather than allowed: an
    unknown caller is not a permitted one, and this is the direction to fail in.
    """
    if role is None:
        return False
    if screen.permission is None:
        # A screen with no whole-screen refusal is open to every CLIENT ROLE, which is not
        # the same as "open to any string": an unknown role holds no permissions anywhere
        # else in this product and must not acquire one here.
        return role in ROLE_PERMISSIONS
    return role_has(role, screen.permission)


def resolve_destination(
    arguments: str, *, role: str | None, current_route: str
) -> CopilotNavigateEvent:
    """The model's `open_screen` arguments → the frame the browser acts on.

    Raises `NavigationRefusedError` for each of the three refusals in the module docstring.
    Every string on the returned event is composed HERE, from the inventory: the model
    contributed one lookup key and nothing that is spoken, rendered or navigated to.
    """
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        raise NavigationRefusedError("the screen name was not sent in the right shape") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("screen"), str):
        raise NavigationRefusedError("the screen name was missing or was not text")

    screen = find_screen(parsed["screen"])
    if screen is None:
        # THE ASKED-FOR NAME IS NOT QUOTED BACK. It is model-composed text on its way into a
        # log line and a prompt, and the model already holds the list — naming the fix is
        # more use to it than repeating its own guess.
        raise NavigationRefusedError(
            "there is no screen with that name. Use a name exactly as it is written in the "
            "list of this console's screens"
        )
    if not _may_open(screen, role):
        raise NavigationRefusedError(
            f"{screen.name} can only be opened by the account owner, so do not open it. Tell "
            "them the screen exists, that it is the owner's, and what they can ask the owner "
            "to do"
        )
    if match_route(current_route) is screen:
        raise NavigationRefusedError(
            f"they are already on {screen.name}, so there is nowhere to take them. Tell them "
            "they are already there and what to do on it"
        )

    return CopilotNavigateEvent(
        tool=OPEN_SCREEN_TOOL_NAME,
        screen=screen.name,
        # THE INVENTORY'S OWN CONSTANT, by reference and never by construction. This is the
        # sentence of this module: a route the model influenced is an open redirect, and a
        # route read out of a frozen tuple cannot be one.
        route=screen.route,
        where=where_is(screen),
        # "OPENING", NOT "OPENED". The server decides the destination; the browser decides
        # WHEN — it asks first when the person may have unsaved work on the screen they are
        # leaving — so a past tense here would be a claim this half is not entitled to make.
        detail=f"Opening {where_is(screen)}.",
        reversal="Your browser's back button brings you back to this screen.",
    )


__all__ = [
    "MAX_NAVIGATIONS_PER_RUN",
    "OPEN_SCREEN_TOOL_NAME",
    "NavigationRefusedError",
    "find_screen",
    "open_screen_tool",
    "resolve_destination",
]
