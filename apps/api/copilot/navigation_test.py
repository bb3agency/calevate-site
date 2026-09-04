"""THE COPILOT TAKES SOMEBODY TO A SCREEN (D-524) — where it may go, and where it may not.

The four properties this file exists for, in the order they matter:

1. **A model cannot forge a destination.** The tool takes a NAME; the route is a constant
   read out of `screens.CLIENT_SCREENS`. Every test that tries to smuggle a path through
   the argument is here, because "an open redirect waiting to happen" is the failure this
   design is shaped around rather than a hazard it filters for.
2. **Nobody is sent to a screen that would then refuse them**, which is worse than not
   moving them at all. Read off `core/rbac.ROLE_PERMISSIONS`, both directions.
3. **A refusal is a sentence the assistant can relay**, not a dead end.
4. **The receipt says how to come back**, because the panel's Undo does not reach a route
   change and a person who has learned Undo exists will look for it.
"""

from __future__ import annotations

import json

import pytest

from apps.api.copilot import navigation
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot import screens as screens_module
from apps.api.copilot.schemas import CopilotNavigateEvent
from apps.api.copilot.screens import CLIENT_SCREENS
from apps.api.core.rbac import ROLE_PERMISSIONS


def _args(**kwargs: object) -> str:
    return json.dumps(kwargs)


def _resolve(
    name: str, *, role: str = "owner", current_route: str = "/c/{slug}/leads"
) -> CopilotNavigateEvent:
    return navigation.resolve_destination(
        _args(screen=name), role=role, current_route=current_route
    )


# --- the destination is ours, not the model's ---------------------------------------------


def test_the_client_word_reaches_the_screen_and_the_route_is_the_inventory_s_own() -> None:
    """THE TRANSCRIPT, AS A TEST. "take me to billing page" is what the client asked and
    what the copilot refused; the screen is called Calling credit and its address is a
    constant nobody typed into a tool call."""
    frame = _resolve("billing")
    assert frame.screen == "Calling credit"
    assert frame.route == "/c/{slug}/credits"
    wallet = next(screen for screen in CLIENT_SCREENS if screen.name == "Calling credit")
    # IDENTITY, not equality: the string on the wire IS the inventory's, so a route can
    # only ever be one this server already knew about.
    assert frame.route is wallet.route


@pytest.mark.parametrize(
    "forged",
    [
        "/c/{slug}/credits",
        "https://evil.example/c/acme/credits",
        "//evil.example",
        "/c/{slug}/credits/../../admin/ops",
        "javascript:alert(1)",
        "Calling credit; /admin/ops",
    ],
    ids=["our-own-path", "absolute-url", "protocol-relative", "traversal", "scheme", "smuggled"],
)
def test_a_path_in_the_tool_argument_is_not_a_destination(forged: str) -> None:
    """THE OPEN-REDIRECT TEST, and it passes for a structural reason rather than a filter:
    the argument is a lookup KEY into a frozen tuple, so anything that is not a screen name
    resolves to nothing. There is no branch here that parses a path, which is why there is
    no branch here that can be tricked into accepting one."""
    with pytest.raises(navigation.NavigationRefusedError) as refusal:
        _resolve(forged)
    assert "no screen with that name" in refusal.value.reason


def test_every_screen_in_the_console_can_be_reached_by_its_own_name() -> None:
    """A destination the assistant can name but not open would be D-522's defect one layer
    on — the model reads these names off the directory in its own prompt."""
    for screen in CLIENT_SCREENS:
        found = navigation.find_screen(screen.name)
        assert found is screen, screen.name


def test_the_name_is_matched_however_it_is_capitalised_or_spaced() -> None:
    """Refusing on capitalisation would be this module inventing a rule nobody agreed to,
    and would spend a turn of the cap correcting a model that was already right."""
    for spelling in ("calling credit", "  Calling   Credit ", "CALLING CREDIT"):
        assert navigation.find_screen(spelling) is navigation.find_screen("Calling credit")


def test_a_name_beats_another_screen_s_alias() -> None:
    """Names are checked in full before any alias, so a screen can never lose its own name
    to somebody else's synonym. "Leads" is a name; "leads" is nobody's alias, but the rule
    has to hold whichever way the two lists grow."""
    names = {screen.name.casefold() for screen in CLIENT_SCREENS}
    for screen in CLIENT_SCREENS:
        for alias in screen.aliases:
            if alias.casefold() in names:
                assert navigation.find_screen(alias).name.casefold() == alias.casefold()  # type: ignore[union-attr]


def test_an_empty_or_shapeless_argument_is_refused_and_not_guessed_at() -> None:
    for arguments in ("", "not json", "[]", '{"screen": null}', '{"screen": "  "}'):
        with pytest.raises(navigation.NavigationRefusedError):
            navigation.resolve_destination(arguments, role="owner", current_route="/c/{slug}/leads")


# --- who may be taken where ---------------------------------------------------------------


def test_nobody_is_sent_to_a_screen_their_role_would_be_refused_from() -> None:
    """Navigating somebody into a refusal is worse than not navigating: they lose the
    screen they were on AND arrive at a wall. Derived from `ROLE_PERMISSIONS` rather than
    from a list here, so this cannot drift from what the console actually does."""
    shut = screens_module.screens_closed_to(ROLE_PERMISSIONS["staff"])
    assert shut, "the fixture is meaningless if no screen is shut to staff"
    for screen in shut:
        with pytest.raises(navigation.NavigationRefusedError) as refusal:
            _resolve(screen.name, role="staff")
        assert screen.name in refusal.value.reason
        assert "account owner" in refusal.value.reason


def test_a_screen_staff_can_open_is_opened_for_staff() -> None:
    """THE OTHER DIRECTION, ON THE SCREEN THE WHOLE FEATURE IS ABOUT. Calling credit
    declares `wallet:read` and staff HOLD it — a guard keyed on "declares a permission"
    would refuse the one screen a staff member most needs to reach when dialling stops."""
    assert "wallet:read" in ROLE_PERMISSIONS["staff"]
    assert _resolve("billing", role="staff").screen == "Calling credit"


def test_a_run_with_no_role_moves_nobody() -> None:
    """An unnamed caller is not a permitted one. Production never produces this — the route
    asserts a role — and the direction to fail in is still refusal."""
    with pytest.raises(navigation.NavigationRefusedError):
        _resolve("Leads", role=None)  # type: ignore[arg-type]
    with pytest.raises(navigation.NavigationRefusedError):
        _resolve("Leads", role="not-a-role")


# --- already there ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route",
    ["/c/{slug}/credits", "/c/acme/credits", "/c/:hidden/credits", "/c/acme/credits/history"],
    ids=["declared", "address-bar", "masked-slug", "deeper"],
)
def test_the_person_standing_on_the_screen_is_not_moved_to_it(route: str) -> None:
    """`match_route` normalises every spelling of a route to one key, so this is decidable
    — and the answer to "take me to billing" from the billing screen is a sentence, not a
    flicker and a wasted back-button entry."""
    with pytest.raises(navigation.NavigationRefusedError) as refusal:
        _resolve("billing", current_route=route)
    assert "already on Calling credit" in refusal.value.reason


# --- what the person and the model are told -----------------------------------------------


def test_the_receipt_says_where_it_is_and_how_to_come_back() -> None:
    """Tier 1's contract: a receipt says what happened, where the result lives, and how to
    reverse it. Navigation's reversal is the back button and the server says so in its own
    words, because the panel's Undo belongs to a field fill and does not reach a route."""
    frame = _resolve("billing")
    assert frame.where == "Calling credit, under Settings & account in the left sidebar"
    assert frame.detail == "Opening Calling credit, under Settings & account in the left sidebar."
    assert "back button" in frame.reversal


def test_the_server_says_opening_and_never_opened() -> None:
    """The browser decides WHEN — it asks first when the screen being left may hold unsaved
    work — so a past tense here would be a claim this half cannot keep."""
    for screen in CLIENT_SCREENS:
        # A route belonging to no client screen, so nothing is refused as "already there".
        frame = _resolve(screen.name, role="owner", current_route="/legal/privacy")
        assert frame.detail.startswith("Opening ")
        assert "Opened" not in frame.detail


def test_nothing_a_person_reads_carries_a_route() -> None:
    """The founder's rule: no route paths and no code identifiers in client-facing text.
    `route` is the one field that carries one and it is never rendered or spoken."""
    frame = _resolve("billing")
    for spoken in (frame.screen, frame.where, frame.detail, frame.reversal):
        assert "/c/" not in spoken
        assert "{slug}" not in spoken


# --- the tool the model is offered --------------------------------------------------------


def test_the_tool_is_static_and_names_no_screen_of_its_own() -> None:
    """It is part of the cacheable prefix (`prompt.py` point 1), so it must be the same
    bytes every request — and it must not restate the directory, which would be a second
    copy of the screen list free to drift from the first."""
    assert navigation.open_screen_tool() == navigation.open_screen_tool()
    serialised = json.dumps(navigation.open_screen_tool())
    assert "/c/" not in serialised
    named = [screen.name for screen in CLIENT_SCREENS if screen.name in serialised]
    # Two are quoted as examples of the SHAPE of a name; the list itself is not here.
    assert len(named) <= 3, named


def test_the_prompt_tells_the_model_when_moving_somebody_is_not_the_answer() -> None:
    """ "Where is billing?" and "take me to billing" are different questions and the second
    one is the only one that moves anybody. Both halves are in the static prefix."""
    directory = screens_module.render_directory()
    assert "YOU CAN TAKE THEM THERE" in directory
    assert navigation.OPEN_SCREEN_TOOL_NAME in directory
    assert "do NOT move them" in directory
    assert navigation.OPEN_SCREEN_TOOL_NAME in prompt_module.SYSTEM_PROMPT
    assert navigation.OPEN_SCREEN_TOOL_NAME in prompt_module.CLOSING_RULES
