"""THE GUARD THAT KEEPS THE COPILOT'S SCREEN INVENTORY HONEST (D-522).

`copilot/screens.py` is a Python restatement of a list that lives in TypeScript. A
restatement goes stale, and stale navigation knowledge is the exact defect that module
exists to fix — an assistant telling a client, on the billing screen, that there is no
billing screen. So the restatement is not trusted: this file PARSES the frontend and
fails when the two disagree.

WHAT IT READS, AND WHY THOSE TWO ARTEFACTS:

* `apps/web/src/lib/clientNav.ts` — the nav the client actually sees, and therefore the
  source of truth for WHICH screens exist and WHAT each is called. The layout renders it
  and nothing else; there is no second copy in the browser.
* each screen's `page.tsx` — for the one permission fact that is decidable from source: a
  WHOLE-SCREEN refusal, spelled `const refused = me.data !== undefined &&
  !me.data.permissions.includes("X")` in all seven screens that have one. A control INSIDE
  a screen (`useWriteAccess`) is deliberately not read: it does not stop a person opening
  the screen, and telling them they cannot go somewhere they can go is the same lie in the
  other direction.

WHAT IT CANNOT READ IS THE SYNONYMS, because no artefact knows that a client says
"billing" for Credits & billing. What it enforces there is that the field is non-empty and
that no two screens claim the same word — the failure mode a thesaurus produces.

A PARSER WITH NO BLIND-SPOT CHECK IS A TEST THAT PASSES WHEN IT STOPS WORKING, so
`test_the_parser_still_finds_the_nav` asserts the shape of what it found before anything
else compares against it — the property `scripts/check_web_env_parity.py` calls
`blind_spots()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.api.copilot import context
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot import screens as screens_module
from apps.api.core.rbac import KNOWN_PERMISSIONS, ROLE_PERMISSIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
NAV_SOURCE = REPO_ROOT / "apps/web/src/lib/clientNav.ts"
CLIENT_APP = REPO_ROOT / "apps/web/src/app/c/[slug]"

#: `{ href: `/c/${slug}/billing`, label: "Credits & billing", icon: Wallet },` — one entry,
#: one line, which is the shape `clientNav.ts` documents as a parse contract.
_ENTRY = re.compile(
    r"\{\s*href:\s*`/c/\$\{slug\}(?P<path>[^`]*)`,\s*label:\s*\"(?P<label>[^\"]+)\""
)

#: `heading: "Settings & account",` / `heading: null,` — the group each following entry
#: belongs to, in file order.
_HEADING = re.compile(r"heading:\s*(?:\"(?P<name>[^\"]+)\"|(?P<null>null))")

#: The WHOLE-SCREEN refusal, as every gated client screen spells it. See the header for why
#: this shape and not `useWriteAccess`.
_WHOLE_SCREEN_REFUSAL = re.compile(
    r"const refused = me\.data !== undefined && !me\.data\.permissions\.includes\("
    r"\"(?P<permission>[^\"]+)\"\)"
)


@dataclass(frozen=True, slots=True)
class NavEntry:
    """One sidebar entry as the frontend renders it."""

    route: str
    name: str
    group: str | None


def _parse_nav() -> tuple[NavEntry, ...]:
    """`clientNav.ts` as a list of (route template, label, group), in sidebar order."""
    entries: list[NavEntry] = []
    group: str | None = None
    for line in NAV_SOURCE.read_text(encoding="utf-8").splitlines():
        # SKIP THE PROSE. The module header documents the entry shape by writing one out,
        # and a parser that reads its own contract as data would find a screen called "Y".
        stripped = line.lstrip()
        if stripped.startswith(("*", "/*", "//")):
            continue
        heading = _HEADING.search(line)
        if heading is not None:
            group = heading.group("name")
            continue
        entry = _ENTRY.search(line)
        if entry is not None:
            entries.append(
                NavEntry(
                    route=f"/c/{{slug}}{entry.group('path')}",
                    name=entry.group("label"),
                    group=group,
                )
            )
    return tuple(entries)


def _page_source(route: str) -> str:
    """The `page.tsx` behind a route template. Raises if the file is not where the route
    says it is — which is itself a finding: a nav entry pointing at nothing is the
    frontend's half-wired feature."""
    suffix = route.removeprefix("/c/{slug}").strip("/")
    page = (CLIENT_APP / suffix / "page.tsx") if suffix else (CLIENT_APP / "page.tsx")
    return page.read_text(encoding="utf-8")


# --- the parser itself ------------------------------------------------------------------


def test_the_parser_still_finds_the_nav() -> None:
    """BLIND-SPOT CHECK, first, because everything below is vacuous if this is empty.

    A regex over another language's source is a test that can silently stop finding its
    subject — a reformat, a rename, a move — and then agree with anything. So assert what a
    working parse looks like before comparing: a couple of dozen entries, every one with a
    route and a name, and the four sidebar groups the console renders.
    """
    entries = _parse_nav()
    assert len(entries) >= 20, f"parsed {len(entries)} nav entries; clientNav.ts has more"
    assert all(entry.name and entry.route.startswith("/c/{slug}") for entry in entries)
    assert {entry.group for entry in entries} == {
        None,
        "Reports & reviews",
        "Compliance & data",
        "Settings & account",
    }


# --- the inventory against the nav -------------------------------------------------------


def test_every_screen_in_the_sidebar_is_in_the_inventory_and_nothing_else_is() -> None:
    """THE GATE. Route, NAME and GROUP, as an equality, in sidebar order.

    Add a screen, rename one, move one between groups or delete one, and this fails until
    `screens.py` is updated — which is the whole mechanism keeping the copilot from
    describing a console that no longer exists. It is an EQUALITY and not a subset in
    either direction: a screen missing from the inventory is one the assistant will deny,
    and a screen the inventory has invented is one it will send somebody to look for.
    """
    parsed = [(entry.route, entry.name, entry.group) for entry in _parse_nav()]
    ours = [(screen.route, screen.name, screen.group) for screen in screens_module.CLIENT_SCREENS]
    assert ours == parsed


def test_every_screen_has_a_page_behind_it() -> None:
    """A route in the inventory is a route that renders. `_page_source` raises otherwise."""
    for screen in screens_module.CLIENT_SCREENS:
        assert "export default" in _page_source(screen.route), screen.name


# --- the permission half -----------------------------------------------------------------


def test_a_screen_that_refuses_a_role_says_so_in_the_inventory() -> None:
    """The declared permission is the one the SCREEN ITSELF enforces — both directions.

    A screen whose page carries a whole-screen refusal must declare that permission here,
    so the copilot never sends a staff member to Invoice; a screen with no such refusal
    must declare NONE, so it never tells them a screen they can open is the owner's.
    """
    for screen in screens_module.CLIENT_SCREENS:
        found = _WHOLE_SCREEN_REFUSAL.search(_page_source(screen.route))
        enforced = None if found is None else found.group("permission")
        assert screen.permission == enforced, (
            f"{screen.name}: the screen enforces {enforced!r}, the inventory says "
            f"{screen.permission!r}"
        )


def test_a_declared_permission_is_one_the_platform_actually_has() -> None:
    """And one an OWNER holds — a screen no client role can open would be a screen the
    assistant should not be describing to clients at all."""
    for screen in screens_module.CLIENT_SCREENS:
        if screen.permission is None:
            continue
        assert screen.permission in KNOWN_PERMISSIONS
        assert screen.permission in ROLE_PERMISSIONS["owner"]


def test_the_screens_shut_to_staff_are_the_ones_rbac_shuts() -> None:
    """`screens_closed_to` reads the enforcement's own table, so this states the outcome a
    staff member actually gets rather than a role list written twice."""
    staff = screens_module.screens_closed_to(ROLE_PERMISSIONS["staff"])
    # ONE entry, where there were four, because Usage, Spend and Invoice are now tabs
    # inside a screen staff can open rather than screens of their own (D-525). The list
    # shrank without anything being opened up: the owner's figures still refuse, per TAB,
    # inside `billing/page.tsx`. AI help is the last screen that refuses at the door.
    assert [screen.name for screen in staff] == ["AI help"]
    assert screens_module.screens_closed_to(ROLE_PERMISSIONS["owner"]) == ()
    # The wallet is the one billing-shaped screen staff CAN open (`wallet:read`, 2 Sep
    # 2026) — the whole reason a role check had to be per screen rather than per group.
    assert "Credits & billing" not in {screen.name for screen in staff}


# --- the synonyms ------------------------------------------------------------------------


def test_every_screen_carries_the_words_a_client_would_use() -> None:
    """No artefact can derive these, so what is enforced is that they EXIST, are lower
    case, and are not shared between two screens — an ambiguous word is worse than a
    missing one, because it sends somebody confidently to the wrong place."""
    seen: dict[str, str] = {}
    for screen in screens_module.CLIENT_SCREENS:
        assert screen.aliases, f"{screen.name} has no client words"
        for alias in screen.aliases:
            assert alias == alias.lower().strip(), alias
            assert alias not in seen, f"{alias!r} claimed by {seen[alias]} and {screen.name}"
            seen[alias] = screen.name


def test_the_word_the_client_actually_used_reaches_the_screen_they_were_on() -> None:
    """THE DEFECT, as a test. "billing", "payment", "top up", "recharge" and "wallet" are
    the words a client uses for the screen this console calls Credits & billing, and the
    copilot denied all of them."""
    wallet = next(
        screen for screen in screens_module.CLIENT_SCREENS if screen.name == "Credits & billing"
    )
    for word in ("billing", "payment", "top up", "recharge", "wallet"):
        assert word in wallet.aliases


# --- what the model is actually told ------------------------------------------------------


def test_the_directory_is_in_the_static_prefix_and_names_every_screen() -> None:
    """It is in `SYSTEM_PROMPT` — the cacheable prefix — rather than composed per request:
    the console is the same for every client, so this costs one prefix and not one block
    per turn (`prompt.py`, point 1b)."""
    for screen in screens_module.CLIENT_SCREENS:
        assert screen.name in prompt_module.SYSTEM_PROMPT
    assert "Also asked for as: billing" in prompt_module.SYSTEM_PROMPT


def test_the_directory_says_owner_only_for_exactly_the_screens_rbac_shuts() -> None:
    """THE LINE THAT WAS WRONG FIRST, AND ON THE ONE SCREEN THE DEFECT WAS ABOUT.

    "declares a permission" is not "owner only": Credits & billing declares `wallet:read`,
    which STAFF HOLD (2 Sep 2026), so a directory keyed on "has a permission" told a staff
    member the screen they can open is shut to them — the same lie, in the other
    direction, on the same screen. So the marker is derived from `ROLE_PERMISSIONS` and
    asserted here against `screens_closed_to`, which is what the `<viewer>` element uses:
    the static half and the per-request half cannot disagree about who may open what.
    """
    directory = screens_module.render_directory()
    shut = {screen.name for screen in screens_module.screens_closed_to(ROLE_PERMISSIONS["staff"])}
    for screen in screens_module.CLIENT_SCREENS:
        line = next(row for row in directory.splitlines() if row.startswith(f"- {screen.name} ("))
        expected = (
            "Open to: the account owner only."
            if screen.name in shut
            else ("Open to: everyone on the team.")
        )
        assert expected in line, screen.name
    assert "Credits & billing" not in shut


def test_the_prompt_never_offers_a_screen_name_the_console_does_not_have() -> None:
    """The second failure in the transcript: it named a capitalised "Billing page" that is
    not a screen. Nothing in the directory may read as one."""
    names = {screen.name for screen in screens_module.CLIENT_SCREENS}
    assert "Billing" not in names
    assert "Billing page" not in prompt_module.SYSTEM_PROMPT


def test_the_directory_tells_the_model_not_to_say_the_address_out_loud() -> None:
    """Routes are in the block because the model has to MATCH on them; they are banned from
    the answer because the founder banned route paths and code identifiers from everything
    a client reads."""
    directory = screens_module.render_directory()
    assert "/c/{slug}/billing" in directory
    assert "never say this aloud" in directory
    assert "NEVER SAY AN ADDRESS OUT LOUD" in directory


def test_the_static_prefix_still_does_not_vary_by_request() -> None:
    """The directory is a function call interpolated at import. If it ever became
    per-tenant or per-role the cache hit rate would go to zero, which is the one thing
    `prompt.py`'s docstring asks every addition to preserve."""
    assert prompt_module.SYSTEM_PROMPT is prompt_module.SYSTEM_PROMPT
    assert screens_module.render_directory() == screens_module.render_directory()
    for token in ("{slug}", "http", "tenant_id"):
        assert token not in prompt_module.CLOSING_RULES


# --- knowing which screen the person is on ------------------------------------------------


@pytest.mark.parametrize(
    "route",
    ["/c/{slug}/billing", "/c/acme/billing", "/c/:hidden/billing"],
    ids=["declared", "address-bar", "masked-slug"],
)
def test_the_screen_a_person_is_on_is_recognised_however_the_route_arrives(route: str) -> None:
    """A declaring screen sends the TEMPLATE; an undeclared one sends the masked address
    bar (`lib/copilot/fallback.ts`). Both are the same screen and the assistant must say
    so — the undeclared case is the one it can otherwise say least about."""
    found = screens_module.match_route(route)
    assert found is not None and found.name == "Credits & billing"


def test_a_detail_route_resolves_to_its_own_screen() -> None:
    """Longest prefix wins, exactly as `lib/nav.ts` resolves it for the sidebar."""
    call = screens_module.match_route("/c/acme/calls/0198f000-0000-7000-8000-000000000000")
    assert call is not None and call.name == "Call logs"
    settings = screens_module.match_route("/c/acme/settings/models")
    assert settings is not None and settings.name == "AI model"


def test_a_route_that_belongs_to_no_screen_is_not_guessed_at() -> None:
    """`None`, and the `<viewer>` element then omits the attribute rather than inventing a
    name — the failure this whole change is about, in miniature."""
    assert screens_module.match_route("/admin/tenants/x") is None
    assert screens_module.match_route("/") is None
    assert context.viewer_for(role="owner", route="/admin/ops").on_screen is None


def test_where_is_names_the_screen_and_its_group_and_nothing_else() -> None:
    """The founder's sentence: "Credits & billing, under Settings & account in the left
    sidebar". A screen in the primary group has no heading to name."""
    wallet = screens_module.match_route("/c/{slug}/billing")
    assert wallet is not None
    assert (
        screens_module.where_is(wallet)
        == "Credits & billing, under Settings & account in the left sidebar"
    )
    leads = screens_module.match_route("/c/{slug}/leads")
    assert leads is not None
    assert screens_module.where_is(leads) == "Leads, in the left sidebar"


# --- the viewer element -------------------------------------------------------------------


def _render(viewer: context.Viewer | None) -> str:
    return context.render_live(
        context.LiveState(
            now_ist=datetime(2026, 9, 4, 11, 0, tzinfo=UTC),
            counts=None,
            blocker_rules=(),
            viewer=viewer,
        )
    )


def test_the_block_names_the_screen_the_person_is_looking_at() -> None:
    """FAILURE ONE OF THREE, fixed: the copilot denied a screen the client was standing on
    because nothing joined "the address is /c/x/billing" to "this screen is called
    Credits & billing"."""
    rendered = _render(context.viewer_for(role="owner", route="/c/acme/billing"))
    assert (
        'looking_at="Credits &amp; billing, under Settings &amp; account in the left sidebar"'
        in (rendered)
    )
    assert 'role="owner"' in rendered


def test_a_staff_member_is_named_the_screens_they_cannot_open() -> None:
    """By NAME, because a name is what they will look for in the sidebar — and only when
    there are any, because an empty attribute is a thing a model paraphrases."""
    staff = _render(context.viewer_for(role="staff", route="/c/acme/billing"))
    # ONE name where there were four: Usage, Spend and Invoice are tabs of a screen staff
    # can open now (D-525), and their figures refuse inside it. AI help is the last screen
    # shut at the door.
    assert 'screens_you_cannot_open="AI help"' in staff
    owner = _render(context.viewer_for(role="owner", route="/c/acme/billing"))
    assert "screens_you_cannot_open" not in owner


def test_no_viewer_renders_no_element() -> None:
    """The admin realm composes this block for a TENANT's business state and has its own
    console; it passes no viewer and must not be handed a client one."""
    assert "<viewer" not in _render(None)
