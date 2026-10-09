"""The ADMIN console's screens, as the admin assistant may talk about and open them (D-694).

The admin twin of `screens.py`, smaller because the admin sidebar is one flat list:
`apps/web/src/app/admin/adminNav.ts` is the source of truth for route, name and
permission, and `admin_screens_test.py` fails if the two disagree. Only the sidebar's
entries are here — a client's own sub-pages (`/admin/tenants/{id}/...`) need an id the
model must never compose, so the assistant names them in words instead.

`open_screen` in the admin realm takes a NAME and answers with a route CONSTANT read from
this tuple, exactly as `navigation.resolve_destination` does for the client console; the
browser then checks it against `ADMIN_NAV` before it moves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from apps.api.copilot.navigation import OPEN_SCREEN_TOOL_NAME, NavigationRefusedError
from apps.api.copilot.prompt import function_tool
from apps.api.copilot.schemas import CopilotNavigateEvent
from apps.api.core.rbac import Permission, role_has


@dataclass(frozen=True, slots=True)
class AdminScreen:
    route: str
    name: str
    group: str | None
    summary: str
    permission: Permission


#: Sidebar order, top to bottom — `adminNav.ts`'s.
ADMIN_SCREENS: Final[tuple[AdminScreen, ...]] = (
    AdminScreen("/admin", "Clients", None, "The client directory.", "admin:tenants"),
    AdminScreen(
        "/admin/health", "Client health", None, "Accounts with something wrong.", "org:read"
    ),
    AdminScreen(
        "/admin/spend", "Money board", None, "Which client is costing what.", "billing:read"
    ),
    AdminScreen("/admin/holds", "Held accounts", None, "Accounts held on a gate.", "org:read"),
    AdminScreen(
        "/admin/kyc-reviews",
        "Identity reviews",
        None,
        "Business verification waiting for review.",
        "admin:tenants",
    ),
    AdminScreen(
        "/admin/qa-sampling",
        "Call quality checks",
        None,
        "Sampled calls to review.",
        "org:read",
    ),
    AdminScreen(
        "/admin/assistant",
        "Assistant",
        None,
        "This assistant's conversation and everything it did, with Undo.",
        "copilot:admin",
    ),
    AdminScreen(
        "/admin/new", "New client", "Onboarding", "Create a client account.", "admin:tenants"
    ),
    AdminScreen(
        "/admin/ops",
        "Operations",
        "Platform",
        "Platform switches, including the outbound halt.",
        "ops:manage",
    ),
    AdminScreen(
        "/admin/ops/config",
        "Platform configuration",
        "Platform",
        "Settings and vendor credentials.",
        "platform:config",
    ),
    AdminScreen(
        "/admin/ops/voices", "Voices", "Platform", "The voices the platform offers.", "ops:manage"
    ),
    AdminScreen(
        "/admin/ops/maintenance",
        "Planned maintenance",
        "Platform",
        "Schedule or end a maintenance window.",
        "ops:manage",
    ),
    AdminScreen(
        "/admin/ops/dnc",
        "Do-not-call list",
        "Platform",
        "The platform-wide do-not-call list.",
        "ops:manage",
    ),
    AdminScreen("/admin/ops/alerts", "Alerts", "Platform", "Raised alarms.", "ops:manage"),
    AdminScreen(
        "/admin/ops/engine-latency",
        "Voice response time",
        "Platform",
        "The voice response-time report.",
        "ops:manage",
    ),
    AdminScreen(
        "/admin/operators",
        "Admin accounts",
        "Platform",
        "Who may use this console.",
        "admin:operators",
    ),
)


def admin_where_is(screen: AdminScreen) -> str:
    if screen.group is None:
        return f"{screen.name}, in the left sidebar"
    return f"{screen.name}, under {screen.group} in the left sidebar"


def render_admin_directory() -> str:
    """The admin screens, for the admin prompt's static prefix."""
    lines = [
        "THE SCREENS OF THIS CONSOLE (use these names exactly; open one with open_screen "
        "when the operator asks to be taken there):"
    ]
    lines += [f"- {screen.name}: {screen.summary}" for screen in ADMIN_SCREENS]
    return "\n".join(lines)


def admin_open_screen_tool() -> dict[str, Any]:
    """The admin realm's `open_screen` — same name and shape as the client one, its own words."""
    return function_tool(
        name=OPEN_SCREEN_TOOL_NAME,
        description=(
            "Open one of the admin console's screens — use this when the operator asks to be "
            "taken somewhere. Pass the screen's NAME exactly as it appears in THE SCREENS OF "
            "THIS CONSOLE above. Say you are opening it, never that they have arrived. If "
            "they only asked WHERE something is, answer in words instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "screen": {
                    "type": "string",
                    "description": "The screen's name from the list, e.g. 'Client health'.",
                }
            },
            "required": ["screen"],
            "additionalProperties": False,
        },
    )


def find_admin_screen(named: str) -> AdminScreen | None:
    key = " ".join(named.split()).casefold()
    for screen in ADMIN_SCREENS:
        if screen.name.casefold() == key:
            return screen
    return None


def resolve_admin_destination(
    arguments: str, *, role: str | None, current_route: str
) -> CopilotNavigateEvent:
    """`navigation.resolve_destination`'s three refusals, over the admin inventory."""
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        raise NavigationRefusedError("the screen name was not sent in the right shape") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("screen"), str):
        raise NavigationRefusedError("the screen name was missing or was not text")
    screen = find_admin_screen(parsed["screen"])
    if screen is None:
        raise NavigationRefusedError(
            "there is no screen with that name. Use a name exactly as it is written in the "
            "list of this console's screens"
        )
    if role is None or not role_has(role, screen.permission):
        raise NavigationRefusedError(
            f"{screen.name} needs a role this operator does not hold, so do not open it. Tell "
            "them which screen it is and that a superadmin can open it"
        )
    if current_route.rstrip("/") == screen.route:
        raise NavigationRefusedError(
            f"they are already on {screen.name}, so there is nowhere to take them"
        )
    return CopilotNavigateEvent(
        tool=OPEN_SCREEN_TOOL_NAME,
        screen=screen.name,
        route=screen.route,
        where=admin_where_is(screen),
        detail=f"Opening {admin_where_is(screen)}.",
        reversal="Your browser's back button brings you back to this screen.",
    )


__all__ = [
    "ADMIN_SCREENS",
    "AdminScreen",
    "admin_open_screen_tool",
    "admin_where_is",
    "find_admin_screen",
    "render_admin_directory",
    "resolve_admin_destination",
]
