"""`hooks.` must not expose a health route, and deleting two lines would not have done it.

The webhook receiver's `/healthz/ready` handler resolves the engine adapter, which imports
`apps.api.engine.bolna` and `httpx` — measured at 381-435ms on the first call, on the
service whose entire ack budget is 500ms and whose vendor delivers at most once with no
retry (D-31). Nothing needs that route on the public hostname: the deploy polls
`127.0.0.1:8100/healthz` and compose's healthcheck runs inside the container, so both
readers are already on the loopback side of nginx.

**The subtle part, and the reason this file exists rather than a one-line diff.** The
finding that produced this change said "deleting those two lines removes the public path
onto the vendor-adapter import entirely". It does not. nginx matches the longest prefix,
and the hooks vhost ends with `location /` — a prefix match on `/` that catches everything
not claimed by a more specific block. Delete `= /healthz` and `^~ /healthz/` and every
`/healthz*` request simply falls through to the catch-all, reaches the same handler, and
spends the webhook rate zone's budget doing it. Closing the path takes a location that
ANSWERS instead of proxying, and `^~` so that it beats the catch-all.

So the property under test is not "those lines are gone". It is: **no request beginning
`/healthz` on the hooks vhost can reach an upstream** — which a future edit could undo by
deleting the 404 location just as easily as by adding a proxy back.

The api vhost is asserted in the other direction. It keeps both health locations, because
that is where an operator and OPERATIONS §8's pre-launch check actually read them, and a
"fix" that removed health from both hostnames would pass a test that only looked at hooks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "infra" / "nginx" / "calevate.conf.template"


def _server_blocks(config: str) -> list[str]:
    """Every top-level `server { ... }` body, by brace depth.

    A real config parser would be a dependency; brace counting is enough here because the
    file is ours and has no braces inside strings.
    """
    blocks: list[str] = []
    for match in re.finditer(r"\bserver\s*\{", config):
        depth, index = 0, match.end() - 1
        while index < len(config):
            if config[index] == "{":
                depth += 1
            elif config[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(config[match.end() : index])
                    break
            index += 1
    return blocks


def _block_for(server_name_fragment: str, *, listening_on_443: bool = True) -> str:
    """The one server block serving `server_name_fragment`.

    MATCHES ON THE server_name TOKEN LIST, not on a substring of the block. A substring
    match cannot express "the bare apex": `${ROOT_DOMAIN}` is a suffix of
    `www.${ROOT_DOMAIN}` and of every service hostname, so the apex's own block is
    indistinguishable from five others. A fragment ending in `.` is a hostname PREFIX
    (`app.`); anything else must equal a whole token.
    """
    config = TEMPLATE.read_text(encoding="utf-8")
    candidates = []
    for block in _server_blocks(config):
        names = re.search(r"server_name([^;]*);", block)
        if names is None:
            continue
        tokens = names.group(1).split()
        matched = any(
            token.startswith(server_name_fragment)
            if server_name_fragment.endswith(".")
            else token == server_name_fragment
            for token in tokens
        )
        if matched and (("listen 443" in block) == listening_on_443):
            candidates.append(block)
    assert len(candidates) == 1, (
        f"expected exactly one server block for {server_name_fragment} "
        f"(listen 443 = {listening_on_443}), found {len(candidates)}"
    )
    return candidates[0]


#: `location <modifier?> <prefix> ...` — enough to know which requests a block claims.
_LOCATION = re.compile(r"location\s+(?:(=|\^~|~\*?)\s+)?(\S+)")


def _locations(block: str) -> list[tuple[str, str]]:
    return [(modifier or "", prefix) for modifier, prefix in _LOCATION.findall(block)]


def test_the_hooks_vhost_answers_healthz_itself_instead_of_proxying_it() -> None:
    block = _block_for("hooks.")
    healthz = [
        (modifier, prefix)
        for modifier, prefix in _locations(block)
        if prefix.startswith("/healthz")
    ]
    assert healthz, (
        "the hooks vhost has no /healthz location at all. That is NOT the fix: `location /` "
        "below it is a prefix match on `/`, so every /healthz request falls through to it "
        "and reaches voice-runtime's readiness handler — which resolves the engine adapter "
        "and drags httpx onto the event loop that has 500ms to ack a webhook."
    )
    assert any(modifier == "^~" for modifier, _ in healthz), (
        "the /healthz location on hooks must use `^~` so it beats the `location /` "
        f"catch-all rather than tying with it: {healthz}"
    )


def test_nothing_beginning_healthz_can_reach_an_upstream_on_the_hooks_vhost() -> None:
    """The actual property. A `return 404` that sits beside a `proxy_pass` proves nothing."""
    block = _block_for("hooks.")
    # The body of each /healthz location: from its `location` keyword to the next `}`.
    for body in re.findall(r"location\s+(?:\^~|=)?\s*/healthz\S*\s*\{([^}]*)\}", block):
        assert "proxy_pass" not in body, (
            "a /healthz location on the hooks vhost proxies to an upstream again. The "
            "route exists on voice-runtime and is polled on 127.0.0.1:8100 by the deploy; "
            "publishing it puts the vendor-adapter import one unauthenticated request away."
        )
        assert re.search(r"\breturn\s+404\b", body), (
            f"expected `return 404` in the hooks /healthz location, got: {body.strip()!r}"
        )


def test_the_api_vhost_still_serves_both_health_routes() -> None:
    """The fix must not be "health is gone everywhere".

    `scripts/vps-deploy.sh` polls `/healthz` and OPERATIONS §8's last pre-launch item is a
    `GET /healthz/ready` against `api.`; both are reasons this hostname keeps them.
    """
    block = _block_for("api.")
    prefixes = {prefix for _, prefix in _locations(block)}
    assert "/healthz" in prefixes and "/healthz/" in prefixes, prefixes
    for body in re.findall(r"location\s+(?:\^~|=)?\s*/healthz\S*\s*\{([^}]*)\}", block):
        assert "proxy_pass http://calevate_api" in body, body


@pytest.mark.parametrize("hostname", ["admin.", "app."])
def test_the_browser_realms_never_had_a_health_route_and_still_do_not(hostname: str) -> None:
    block = _block_for(hostname)
    assert not [prefix for _, prefix in _locations(block) if prefix.startswith("/healthz")]


# --- realm isolation: the two browser hostnames are actually two (P7.3) -------
#
# `clerkRuntime.tsx` reasons from "disjoint route trees on disjoint hostnames", and the
# shipped config was ONE server block for both — so `app.` served the operator console at
# `/admin` and `admin.` served client dashboards at `/c/`. The consequence that matters is
# not authorization (the admin realm resolves against its own JWKS): it is that the
# operator SIGN-IN page was served on the hostname clients are told to visit.
#
# Same doctrine as the hooks tests above: the property is "no request under the other
# realm's prefix can reach an upstream", not "these two lines exist". A future edit could
# undo it by deleting the 404 or by adding a proxy back, and both must fail here.

REALM_REFUSALS = (
    # (hostname fragment, prefix it must refuse, what is behind that prefix)
    ("app.", "/admin", "the operator console, including its sign-in page"),
    ("admin.", "/c/", "every client dashboard"),
    # The apex proxies to the SAME Next.js process as both consoles, so it reopens the
    # hole on a third hostname unless it refuses both trees. `_block_for` matches on a
    # server_name TOKEN, which is what distinguishes the bare apex from `www.` and from
    # every subdomain — a substring match cannot, since the apex is a suffix of all of
    # them.
    ("${ROOT_DOMAIN}", "/admin", "the operator console, on the PUBLIC hostname"),
    ("${ROOT_DOMAIN}", "/c/", "every client dashboard, on the PUBLIC hostname"),
)


@pytest.mark.parametrize(("host", "prefix", "what"), REALM_REFUSALS)
def test_each_browser_hostname_refuses_the_other_realms_tree(
    host: str, prefix: str, what: str
) -> None:
    block = _block_for(host)
    matching = [
        (modifier, at) for modifier, at in _locations(block) if at.rstrip("/") == prefix.rstrip("/")
    ]
    assert matching, (
        f"{host} has no location for {prefix}, so `location /` below it serves {what} "
        "on this hostname — the realm isolation the frontend reasons from is a comment"
    )
    assert any(modifier == "^~" for modifier, _ in matching), (
        f"the {prefix} location on {host} must use `^~`: nginx tries regex locations "
        "before plain prefix ones, so a regex location added later would win and "
        f"quietly re-open it. Got: {matching}"
    )
    for body in re.findall(rf"location\s+\^~\s*{re.escape(prefix)}\s*\{{([^}}]*)\}}", block):
        assert "proxy_pass" not in body, f"{host}{prefix} proxies to an upstream again"
        assert re.search(r"\breturn\s+404\b", body), (
            f"expected `return 404` (not 403, which confirms the tree exists) in "
            f"{host}{prefix}, got: {body.strip()!r}"
        )


@pytest.mark.parametrize(("host", "prefix"), [(h, p) for h, p, _ in REALM_REFUSALS])
def test_each_hostname_still_serves_its_own_realm(host: str, prefix: str) -> None:
    """The fix must not be "both trees are 404 everywhere". Each block still has the
    catch-all that proxies its own realm to Next.js."""
    block = _block_for(host)
    catch_all = re.findall(r"location\s+/\s*\{([^}]*)\}", block)
    assert catch_all, f"{host} lost its catch-all and now serves nothing"
    assert any("proxy_pass http://calevate_web" in body for body in catch_all), (
        f"{host} no longer proxies its own realm to the web upstream"
    )


def test_the_two_realms_are_not_sharing_one_server_block() -> None:
    """The defect itself, stated directly: one `server_name admin. app.` line is what made
    every location above apply to both hostnames at once."""
    config = TEMPLATE.read_text(encoding="utf-8")
    for block in _server_blocks(config):
        if "listen 443" not in block:
            continue  # the port-80 redirect legitimately names all four
        names = re.search(r"server_name([^;]*);", block)
        if names is None:
            continue
        listed = names.group(1).split()
        both = [n for n in listed if n.startswith(("admin.", "app."))]
        assert len(both) <= 1, (
            "one TLS server block serves both browser realms again, so every location in "
            f"it applies to both hostnames: {listed}"
        )


# --- the timeout section: what nginx actually does with a duplicated directive ---
#
# THE PREVIOUS SHAPE HERE WAS A CONFIG NGINX REFUSES TO LOAD, and these tests pinned it.
#
# `calevate-proxy.conf` ended with `proxy_connect_timeout 5s; proxy_send_timeout 60s;
# proxy_read_timeout 60s`, and the hooks `location /` RESTATED 2s/15s/15s immediately
# after including it — documented as "nginx takes the last occurrence at a level". It
# does not. A second `proxy_connect_timeout` at the same level is
#
#     nginx: [emerg] "proxy_connect_timeout" directive is duplicate in
#     /etc/nginx/conf.d/calevate-site.conf:287
#
# and the WHOLE config is rejected, every vhost with it. Found by `nginx -t` on the first
# host that ever loaded this file — not by these tests, which asserted the restatement was
# present and required it to be the tight value.
#
# The premise that produced it was half right: an `include` IS textual, so a timeout in
# the snippet does land at location scope and does shadow the server block. The fix is
# therefore not a restatement but an ABSENCE — the snippet sets no timeout at all, and
# each vhost states its own trio at server scope, where nothing shadows it.
#
# The properties below are what that costs and what protects it: every TLS vhost must
# set all three (a new one that forgets gets nginx's global 60s silently), the hooks
# numbers must stay tighter than the browser realms', and NO directive the shared snippet
# sets may be restated in a block that includes it — which is the general form of the
# defect, not just the three names it happened to hit.

PROXY_SNIPPET = (
    Path(__file__).resolve().parents[1] / "infra" / "nginx" / "snippets" / "calevate-proxy.conf"
)

_TIMEOUT = re.compile(r"\b(proxy_(?:connect|send|read)_timeout)\s+(\S+?)\s*;")

_TIMEOUT_NAMES = ("proxy_connect_timeout", "proxy_send_timeout", "proxy_read_timeout")

#: `proxy_set_header Host $host;` -> "proxy_set_header". Directive NAMES only, comments
#: stripped by the caller, so a name quoted in prose is not mistaken for a setting.
_DIRECTIVE = re.compile(r"^\s*([a-z_]+)\s", re.MULTILINE)


def _uncommented(text: str) -> str:
    return re.sub(r"#[^\n]*", "", text)


def _server_scope(block: str) -> str:
    """A server block's own directives — everything above its first `location`.

    COMMENTS ARE STRIPPED FIRST, and that ordering is the whole correctness of this
    helper. The prose above these trios explains why they are not at location scope, so
    it contains the words "location scope"; slicing at the first literal `location ` in
    the RAW block cuts above the directives and reports every vhost as setting none.
    """
    clean = _uncommented(block)
    at = clean.find("location ")
    return clean[: at if at != -1 else len(clean)]


def _tls_blocks() -> list[tuple[str, str]]:
    """Every `(hostname, body)` for the TLS server blocks, port-80 redirect excluded."""
    config = TEMPLATE.read_text(encoding="utf-8")
    found = []
    for block in _server_blocks(config):
        if "listen 443" not in block:
            continue
        names = re.search(r"server_name([^;]*);", block)
        assert names is not None
        found.append((names.group(1).split()[0], block))
    # Six: the apex, www, and the four service hostnames. A COUNT rather than a lower
    # bound, because a vhost added without the block below noticing is exactly how the
    # apex shipped with no server_name at all — `calevate.tech` landed on the certless
    # default_server and got `return 444`, i.e. the product's front door closed the
    # connection on every visitor.
    assert len(found) == 6, [name for name, _ in found]
    return found


def test_the_shared_proxy_snippet_sets_no_timeout_at_all() -> None:
    """The premise the rest of this section rests on, and the actual fix.

    FAILS IF: somebody puts the three lines back in the snippet "as defaults". That is
    what makes every vhost's server-scope trio dead again, and the first block that then
    restates one is a config that will not load.
    """
    found = _TIMEOUT.findall(_uncommented(PROXY_SNIPPET.read_text(encoding="utf-8")))
    assert not found, (
        "calevate-proxy.conf sets a proxy timeout again. An include is textual, so this "
        f"lands at LOCATION scope in every block that pulls it in: {found}"
    )


@pytest.mark.parametrize("directive", _TIMEOUT_NAMES)
def test_every_tls_vhost_states_every_timeout_at_server_scope(directive: str) -> None:
    """The cost of the fix, made a red build rather than a silent 60s.

    With the snippet no longer supplying a default, a vhost that states nothing runs on
    nginx's global 60s — which on `hooks.` is a call already lost, and on the api vhost
    is the budget `tests/assist_deadline_test` measures against.
    """
    for host, block in _tls_blocks():
        assert re.search(rf"\b{directive}\s+\S+;", _server_scope(block)), (
            f"{host} does not set {directive} at server scope, so it silently runs on "
            "nginx's 60s global default"
        )


@pytest.mark.parametrize("directive", _TIMEOUT_NAMES)
def test_the_hooks_vhost_is_tighter_than_the_browser_realms(directive: str) -> None:
    """Not merely "a value is set" but "the value is the tight one".

    FAILS IF: someone reconciles the vhosts by copying 60s everywhere, which would keep
    every test above green while restoring the defect the tightening exists for — the
    webhook vhost has 500ms to ack and its vendor never retries (D-31).
    """

    def seconds(block: str) -> float:
        match = re.search(rf"\b{directive}\s+(\d+)(s|m)?\s*;", _server_scope(block))
        assert match is not None, directive
        return float(match.group(1)) * (60.0 if match.group(2) == "m" else 1.0)

    blocks = dict(_tls_blocks())
    hooks = seconds(blocks["hooks.${ROOT_DOMAIN}"])
    for host in ("admin.${ROOT_DOMAIN}", "app.${ROOT_DOMAIN}", "api.${ROOT_DOMAIN}"):
        assert hooks < seconds(blocks[host]), (
            f"hooks {directive} ({hooks}s) is not tighter than {host}. An engine callback "
            "waiting a browser realm's timeout is a call already lost."
        )


def test_no_block_restates_a_directive_the_shared_snippet_already_sets() -> None:
    """THE GENERAL FORM OF THE DEFECT, and the only test here that would have caught it.

    nginx refuses a duplicate directive at one level, and `include` is textual — so any
    name this snippet sets, restated inside a `location` that includes it, is
    `[emerg] directive is duplicate` and the entire config is rejected. The three
    timeouts are simply the names it happened to be true of; `proxy_set_header` and
    `proxy_http_version` are one careless line away from the same outcome.

    `proxy_set_header` is exempt because nginx explicitly allows several of them at one
    level — they are a list, not a scalar.
    """
    settable = {
        name
        for name in _DIRECTIVE.findall(_uncommented(PROXY_SNIPPET.read_text(encoding="utf-8")))
        if name != "proxy_set_header"
    }
    assert settable, "the proxy snippet sets nothing — this guard is blind"

    config = TEMPLATE.read_text(encoding="utf-8")
    for block in _server_blocks(config):
        for body in re.findall(r"location\s+[^{]*\{((?:[^{}]|\{[^{}]*\})*)\}", block, re.DOTALL):
            if "calevate-proxy.conf" not in body:
                continue
            clean = _uncommented(body)
            for name in sorted(settable):
                assert not re.search(rf"^\s*{name}\s+\S", clean, re.MULTILINE), (
                    f"a location restates `{name}` after including calevate-proxy.conf, "
                    "which already sets it at that level. nginx rejects the duplicate and "
                    "refuses the whole config — set it at server scope instead."
                )
