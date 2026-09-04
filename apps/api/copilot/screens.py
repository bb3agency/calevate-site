"""THE SCREENS OF THE CLIENT CONSOLE — what exists, what it is CALLED, where it sits, and
who may open it.

═══ THE DEFECT. THE COPILOT DENIED A SCREEN THE CLIENT WAS STANDING ON. ═══

Verbatim, from a live dashboard, with the person on the Calling credit screen:

    Client:   I can't see any billing page?
    Copilot:  I cannot see a billing page either. You can add funds to your wallet on
              the Billing page.
    Client:   Take me to billing page
    Copilot:  I cannot take you to the billing page. I can only show you the current
              page, which is about calling credit.

Three failures in four lines. It DENIED a screen that exists (the client was on it — our
name for it is "Calling credit", theirs is "billing"). It then CONTRADICTED itself in one
breath by naming a capitalised "Billing page" that is not a screen in this product. And
it could not say where anything IS, because it had no way to know.

The cause was structural rather than a wording problem: the copilot was given SCREEN STATE
— the contents of the one page in front of the person (`prompt.SCREEN_OPEN`) — and nothing
whatever about the console's other screens. It could describe where the person WAS and had
no list to consult for anywhere else, so it did what a model with no list does and invented
a plausible name.

═══ WHAT THIS MODULE IS, AND THE ONE RULE THAT KEEPS IT HONEST ═══

An inventory of the client console's navigation, in the console's own words, rendered into
the STATIC part of the prompt (`prompt.SCREEN_DIRECTORY_BLOCK`).

**IT IS A SECOND COPY OF A LIST THAT LIVES IN TYPESCRIPT, AND THAT IS THE WHOLE RISK.**
The nav a client actually sees is `apps/web/src/lib/clientNav.ts`; a Python constant
restating it goes stale the first time somebody renames a screen — and stale navigation
knowledge is precisely the defect above, reintroduced with more confidence. So the copy is
GUARDED rather than trusted: `copilot/screens_test.py` parses `clientNav.ts` and asserts,
as an equality, that the route→name→group map here is the one the sidebar renders. Add a
screen, rename one, move one between groups, or delete one, and that test goes red until
this file is updated. It runs in the ordinary `uv run pytest`, so there is no separate
gate to remember and no generated artefact to regenerate.

Two things are NOT derived, deliberately, and each is checked in the way it can be:

* **The synonyms.** No frontend artefact knows that a client means this screen when they
  say "billing" — that is knowledge about PEOPLE, and there is nowhere truer to read it
  from. What the guard enforces is that every screen HAS the field, so a new screen cannot
  arrive with an empty vocabulary and be undiscoverable by the only words a client uses.
* **The permission.** A screen refuses a role in its own page component, not in the nav
  (the sidebar shows every entry to everybody — see `spend/page.tsx`, which says so). The
  guard reads the one shape that IS decidable: the whole-screen refusal
  `const refused = me.data !== undefined && !me.data.permissions.includes("X")`, which is
  how the seven gated screens in this console spell it. A screen with that line must
  declare X here; a screen without it must declare none. A control INSIDE a screen
  (`useWriteAccess`, the raw-transcript check) is deliberately not read: it does not stop
  the person opening the screen, and telling somebody they cannot go somewhere they can go
  is the same class of lie as this module exists to stop.

═══ WHY THE DIRECTORY IS STATIC AND THE VIEWER IS NOT ═══

`prompt.py`'s module docstring is the argument: the leading run of the prompt must be
byte-identical on every request or the provider's prompt cache never hits, so nothing
tenant-, screen- or person-specific may be interpolated into it. The directory is the same
for every client in the product, so it belongs in the cached prefix and costs nothing after
the first request of a deployment.

WHO IS ASKING is not the same for every request, so it goes in the volatile block beside
the live business state (`context.render_live`, `<viewer>`), which is where per-request
facts already sit. The directory carries a `who` marker per screen — "everyone" or "the
account owner" — and the viewer element carries the person's role and, by NAME, the screens
their role cannot open. So the model has both halves and neither one moved the cache.

═══ WHAT THIS DOES NOT DO: IT DOES NOT NAVIGATE ═══

There is no `navigate_to` tool and the copilot cannot move anybody (D-523). What it can now
do is answer the question the client actually asked — name the screen and say where it sits
in the sidebar — which is what the two of them were failing to communicate about. The
route strings below are for MATCHING ONLY and are never spoken: `/c/{slug}/credits` is an
internal address, and the prompt says so in the words the founder has banned across the
product ("no route paths, no code identifiers").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from apps.api.core.rbac import Permission

#: The heading a group carries in the sidebar. `None` is the primary group, which is
#: rendered with no heading at all — so a screen in it is described as "in the left
#: sidebar" rather than "under <heading>".
Group = str | None

SETTINGS_GROUP: Final = "Settings & account"


@dataclass(frozen=True, slots=True)
class Screen:
    """One screen of the client console, as the assistant is allowed to talk about it."""

    #: The route TEMPLATE, exactly as the console declares it to the copilot
    #: (`useCopilotSurface({ route: "/c/{slug}/credits" })`) and exactly as `clientNav.ts`
    #: spells it with the slug substituted out. The matching key, never spoken.
    route: str
    #: What the sidebar calls it. THE name — the client's screen is called this and
    #: nothing else, and an assistant that says "Billing" is naming a screen that does not
    #: exist.
    name: str
    #: The sidebar group heading it sits under, or `None` for the primary group.
    group: Group
    #: One short sentence: what a person does here. Client-facing language, because it is
    #: the sentence the model will paraphrase back to them.
    summary: str
    #: The words a CLIENT uses for it when they do not know our name. This is the half the
    #: defect was actually about: "billing", "payment", "top up", "recharge", "wallet" all
    #: mean Calling credit, and no artefact in the frontend knows that.
    #:
    #: Lower case, no duplicates, and deliberately SHORT — enough to bridge a person's word
    #: to ours, not a thesaurus. Every screen must have at least one, which is what stops a
    #: new screen arriving undiscoverable (`screens_test.py`).
    aliases: tuple[str, ...]
    #: The permission the screen's own page requires to show anything, or `None` when every
    #: client role may open it. Derived-and-checked: see the module docstring.
    permission: Permission | None = None


#: THE INVENTORY. Order is the sidebar's, top to bottom, because that is the order a person
#: scanning the screen will find them in and therefore the order to describe them in.
#:
#: `clientNav.ts` is the source of truth for route/name/group; `screens_test.py` fails if
#: this list and that file disagree about any of the three.
CLIENT_SCREENS: Final[tuple[Screen, ...]] = (
    Screen(
        route="/c/{slug}",
        name="Dashboard",
        group=None,
        summary="The account at a glance — today's calls, what needs doing, and the balance.",
        aliases=("home", "overview", "main page", "front page"),
    ),
    Screen(
        route="/c/{slug}/attention",
        name="Needs attention",
        group=None,
        summary="The daily queue: leads and calls waiting for a person to do something.",
        aliases=("to do", "queue", "follow ups", "pending", "inbox"),
        permission="leads:read",
    ),
    Screen(
        route="/c/{slug}/campaigns",
        name="Campaigns",
        group=None,
        summary="Outbound calling campaigns — build one, launch it, pause it, watch it run.",
        aliases=("outbound", "calling list", "dialer", "broadcast"),
    ),
    Screen(
        route="/c/{slug}/agents",
        name="Agents",
        group=None,
        summary="The AI voice agents themselves — what they say, what they capture, whether "
        "they are live.",
        aliases=("bots", "ai agents", "voice agents", "assistants", "receptionist"),
    ),
    Screen(
        route="/c/{slug}/calls",
        name="Call logs",
        group=None,
        summary="Every call, with its recording, transcript and outcome.",
        aliases=("calls", "call history", "recordings", "transcripts"),
    ),
    Screen(
        route="/c/{slug}/leads",
        name="Leads",
        group=None,
        summary="The people the agents talked to, and what was captured about each one.",
        aliases=("contacts", "customers", "enquiries", "crm", "prospects"),
    ),
    Screen(
        route="/c/{slug}/callbacks",
        name="Call-backs",
        group=None,
        summary="Call-backs an agent promised a caller, and when they are due.",
        aliases=("callback", "call back", "promised calls", "call me back"),
    ),
    Screen(
        route="/c/{slug}/knowledge",
        name="Knowledge base",
        group=None,
        summary="What the agents know and are allowed to tell callers.",
        aliases=("knowledge", "faq", "training", "documents", "what the agent knows"),
    ),
    Screen(
        route="/c/{slug}/performance",
        name="Performance",
        group=None,
        summary="How the calling is going — connect rate, outcomes, busiest hours.",
        aliases=("analytics", "reports", "stats", "metrics", "results"),
        permission="calls:read",
    ),
    Screen(
        route="/c/{slug}/quality",
        name="Quality",
        group="Reports & reviews",
        summary="Sampled calls reviewed for how well the agent handled them.",
        aliases=("qa", "call quality", "reviews", "scoring"),
    ),
    Screen(
        route="/c/{slug}/campaign-review",
        name="Campaign review",
        group="Reports & reviews",
        summary="What a finished campaign did, campaign by campaign.",
        aliases=("campaign report", "campaign results"),
    ),
    Screen(
        route="/c/{slug}/agreements",
        name="Agreements",
        group="Compliance & data",
        summary="The documents the account owner has to accept before calling can start.",
        aliases=("contracts", "terms", "sign up documents", "paperwork", "consent forms"),
    ),
    Screen(
        route="/c/{slug}/verification",
        name="Verification",
        group="Compliance & data",
        summary="The identity and business checks that unlock outbound calling.",
        aliases=("kyc", "identity", "business proof", "documents check", "activation"),
    ),
    Screen(
        route="/c/{slug}/do-not-call",
        name="Do not call",
        group="Compliance & data",
        summary="Numbers that must never be called again, and how to add one.",
        aliases=("dnc", "dnd", "blocklist", "opt out", "blacklist", "stop calling"),
    ),
    Screen(
        route="/c/{slug}/messaging-consent",
        name="Messaging consent",
        group="Compliance & data",
        summary="Who has agreed to be messaged, and the record of that agreement.",
        aliases=("sms consent", "whatsapp consent", "permission to message", "opt in"),
    ),
    Screen(
        route="/c/{slug}/lead-sources",
        name="Lead sources",
        group="Compliance & data",
        summary="Where each list of numbers came from — the record that makes calling them lawful.",
        aliases=("where leads came from", "lists", "imports", "data source"),
    ),
    Screen(
        route="/c/{slug}/data-rights",
        name="Data rights",
        group="Compliance & data",
        summary="Requests from people to see or delete what is held about them.",
        aliases=("dpdp", "privacy requests", "deletion", "erasure", "data request"),
    ),
    Screen(
        route="/c/{slug}/caller-notice",
        name="Your privacy notice",
        group="Compliance & data",
        summary="The privacy notice this business shows its own callers.",
        aliases=("privacy policy", "privacy notice", "caller notice"),
    ),
    Screen(
        route="/c/{slug}/settings/team",
        name="Team",
        group=SETTINGS_GROUP,
        summary="Who can sign in to this account, and what each of them may do.",
        aliases=("users", "members", "staff", "invite", "colleagues", "access"),
    ),
    Screen(
        route="/c/{slug}/settings/alerts",
        name="Alerts",
        group=SETTINGS_GROUP,
        summary="What Calevate is allowed to notify this account about.",
        aliases=("notifications", "emails", "reminders", "warnings"),
    ),
    Screen(
        route="/c/{slug}/settings/models",
        name="AI model",
        group=SETTINGS_GROUP,
        summary="Which AI model the agents think with, and what each costs a minute.",
        aliases=("model", "ai settings", "brain", "llm"),
    ),
    Screen(
        route="/c/{slug}/integrations",
        name="Integrations",
        group=SETTINGS_GROUP,
        summary="Connections to other tools this account uses.",
        aliases=("api", "webhooks", "connections", "crm sync", "zapier"),
    ),
    Screen(
        route="/c/{slug}/credits",
        name="Calling credit",
        group=SETTINGS_GROUP,
        # THE SCREEN THE DEFECT WAS ABOUT. Its aliases are the actual fix: every word in
        # this tuple is one a client has used, or would obviously use, for the place they
        # pay. "billing" is first because it is the one that was refused.
        summary="The prepaid balance, how long it lasts, and the one place to add more money.",
        aliases=(
            "billing",
            "payment",
            "pay",
            "top up",
            "topup",
            "recharge",
            "wallet",
            "balance",
            "add money",
            "add funds",
            "credit",
            "buy credits",
        ),
        permission="wallet:read",
    ),
    Screen(
        route="/c/{slug}/usage",
        name="Usage",
        group=SETTINGS_GROUP,
        summary="What this month has cost so far, and the spending limit.",
        aliases=("cost", "this month", "spending limit", "consumption", "minutes used"),
        permission="billing:read",
    ),
    Screen(
        route="/c/{slug}/spend",
        name="Spend",
        group=SETTINGS_GROUP,
        summary="Where the money went — the per-agent and per-call breakdown behind Usage.",
        aliases=("breakdown", "charges", "where the money went", "expenses"),
        permission="billing:read",
    ),
    Screen(
        route="/c/{slug}/ai-assist",
        name="AI help",
        group=SETTINGS_GROUP,
        summary="How much of the plan's AI-help allowance this account has used.",
        aliases=("ai allowance", "assistant usage", "copilot usage"),
        permission="billing:read",
    ),
    Screen(
        route="/c/{slug}/invoice",
        name="Invoice",
        group=SETTINGS_GROUP,
        summary="The monthly statement, with tax, ready to download.",
        aliases=("bill", "receipt", "statement", "gst", "tax invoice", "download bill"),
        permission="billing:read",
    ),
)


def where_is(screen: Screen) -> str:
    """The screen's location as a person would say it out loud.

    "Calling credit, under Settings & account in the left sidebar" — the sentence the
    founder asked for, composed in ONE place so the prompt, the tests and any future
    caller cannot each invent their own phrasing. No route, no identifier: the two things
    banned from client-facing text.
    """
    if screen.group is None:
        return f"{screen.name}, in the left sidebar"
    return f"{screen.name}, under {screen.group} in the left sidebar"


def match_route(route: str) -> Screen | None:
    """The screen a route belongs to, or `None` when none owns it.

    TWO SPELLINGS ARRIVE HERE AND BOTH ARE LEGITIMATE. A screen that declares itself sends
    the TEMPLATE (`/c/{slug}/credits`, `lib/copilot/registry.ts`); a screen that has not
    declared itself gets the fallback surface, which sends the masked ADDRESS BAR
    (`/c/acme/credits`, or `/c/:hidden/credits` when the slug is not a plain name —
    `lib/copilot/fallback.ts`). Normalising the second path segment to `{slug}` makes one
    key of the two, which is the whole trick; without it the copilot would know where it
    was on declared screens and be lost on exactly the undeclared ones it can say least
    about.

    A DEEPER ROUTE RESOLVES TO ITS SCREEN, longest prefix wins — the rule `lib/nav.ts`
    already applies in the browser so the header and the sidebar agree, applied here so
    the assistant agrees with both. `/c/{slug}/calls/{callId}` is Call logs; it is not
    nothing.
    """
    normalised = _normalise(route)
    best: Screen | None = None
    for screen in CLIENT_SCREENS:
        owns = normalised == screen.route or normalised.startswith(f"{screen.route}/")
        if owns and (best is None or len(screen.route) > len(best.route)):
            best = screen
    return best


def _normalise(route: str) -> str:
    """`/c/<anything>/rest` → `/c/{slug}/rest`. Everything else is returned unchanged."""
    parts = route.split("/")
    # ["", "c", "<slug>", ...] — anything shorter is not a client-console route at all.
    if len(parts) >= 3 and parts[1] == "c":
        parts[2] = "{slug}"
        return "/".join(parts)
    return route


def screens_closed_to(permissions: frozenset[str]) -> tuple[Screen, ...]:
    """The screens this permission set may NOT open, in sidebar order.

    Takes the permissions rather than the role name so that the answer comes from
    `core/rbac.ROLE_PERMISSIONS` — the enforcement's own table — and never from a role
    list this module would have to keep in step with it. It is also the reason an
    impersonating operator gets a truthful answer rather than a client-shaped guess.
    """
    return tuple(
        screen
        for screen in CLIENT_SCREENS
        if screen.permission is not None and screen.permission not in permissions
    )


def _directory_line(screen: Screen) -> str:
    """One screen, as one line of the static directory block.

    ONE LINE PER SCREEN, not XML: this block is OURS and static (unlike the screen state,
    which is untrusted and is XML for the provenance attributes it has to carry), and it is
    read by a model as a list. The route is the LAST field on the line and is labelled as
    the internal address, so the sentence a model composes from the earlier fields — name,
    place, purpose, words — never has it in.
    """
    place = "in the left sidebar" if screen.group is None else f"under {screen.group}"
    who = "everyone on the team" if screen.permission is None else "the account owner only"
    return (
        f"- {screen.name} ({place}) — {screen.summary} "
        f"Also asked for as: {', '.join(screen.aliases)}. Open to: {who}. "
        f"[address, never say this aloud: {screen.route}]"
    )


def render_directory() -> str:
    """The whole directory, as it goes into the STATIC prompt prefix.

    A function rather than a constant for `prompt.set_fields_tool`'s reason: it is checked
    by mypy, it cannot be mutated by a previous request, and `prompt.py` interpolates its
    result exactly once at import.
    """
    lines = "\n".join(_directory_line(screen) for screen in CLIENT_SCREENS)
    return (
        "--- THE SCREENS OF THIS CONSOLE (a complete list; nothing else exists) ---\n"
        "This is every screen a client can open, in the order they appear down the left "
        "sidebar. It is complete and it is correct: if a screen is not on this list it "
        "does not exist in this product, and if it IS on this list it exists and you must "
        "never tell somebody it does not.\n"
        f"{lines}\n"
        "\n"
        "HOW TO USE THIS LIST:\n"
        "- WHEN SOMEBODY ASKS WHERE SOMETHING IS, name the screen and say where it sits — "
        '"Calling credit, under Settings & account in the left sidebar". Give the name '
        "first; that is what they are looking for on their own screen.\n"
        "- THEY WILL NOT USE OUR NAME FOR IT. Match what they said against the words after "
        '"Also asked for as" — somebody asking for the billing page, to pay, to top up or '
        'to recharge means Calling credit. Say our name for it and say theirs too: "the '
        'billing screen is called Calling credit…". Never invent a screen name, never '
        "capitalise their word as if it were one, and never say a screen does not exist "
        "because it is not called what they called it.\n"
        "- CHECK WHETHER THEY ARE ALREADY ON IT. The SCREEN STATE at the end of this "
        "prompt carries the address of the screen they are looking at, and the LIVE "
        "BUSINESS STATE names it. If it is the screen they are asking for, tell them they "
        "are already there and what to do on it.\n"
        "- YOU CANNOT MOVE THEM. There is no tool that opens a screen, so say where it is "
        "rather than promising to take them there — one sentence, not an apology.\n"
        "- NEVER SAY AN ADDRESS OUT LOUD. The bracketed address on each line is for "
        "matching only; it is not something a person is shown or told, and neither is any "
        "internal name. Screen names and sidebar groups are the only place vocabulary you "
        "use.\n"
        "- SOME SCREENS ARE THE OWNER'S ONLY. The LIVE BUSINESS STATE says who you are "
        "talking to and names any screen their role cannot open. Never send somebody to a "
        "screen they will be refused from: say the screen exists, that it is the account "
        "owner's, and what they can ask the owner to do.\n"
        "--- END SCREENS ---"
    )


__all__ = [
    "CLIENT_SCREENS",
    "Screen",
    "match_route",
    "render_directory",
    "screens_closed_to",
    "where_is",
]
