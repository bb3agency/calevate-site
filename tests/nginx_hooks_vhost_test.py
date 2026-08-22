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
    config = TEMPLATE.read_text(encoding="utf-8")
    candidates = [
        block
        for block in _server_blocks(config)
        if re.search(rf"server_name[^;]*\b{re.escape(server_name_fragment)}", block)
        and (("listen 443" in block) == listening_on_443)
    ]
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


# --- the timeout tightening the include used to undo --------------------------
#
# The hooks vhost sets `proxy_connect_timeout 2s; proxy_send_timeout 15s;
# proxy_read_timeout 15s` at SERVER scope, with a comment saying a callback waiting 60s is
# a call already lost. Its `location /` then includes `calevate-proxy.conf`, whose last
# three lines are 5s/60s/60s. nginx does not merge levels: a directive set at the current
# level replaces the enclosing one entirely, and `include` is textual, so those three
# landed at LOCATION scope and won. The latency-critical vhost ran on the browser realms'
# numbers, and `client_max_body_size 10m` kept working — the snippet does not define it —
# which is exactly what made it invisible.

SNIPPET = (
    Path(__file__).resolve().parents[1] / "infra" / "nginx" / "snippets" / "calevate-proxy.conf"
)

#: `proxy_read_timeout 15s;` -> ("proxy_read_timeout", "15s")
_TIMEOUT = re.compile(r"\b(proxy_(?:connect|send|read)_timeout)\s+(\S+?)\s*;")

_TIMEOUT_NAMES = ("proxy_connect_timeout", "proxy_send_timeout", "proxy_read_timeout")


def _hooks_catch_all() -> str:
    """The body of the hooks vhost's `location / { ... }`."""
    block = _block_for("hooks.")
    bodies = re.findall(r"location\s+/\s*\{([^}]*)\}", block)
    assert len(bodies) == 1, f"expected one catch-all on the hooks vhost, found {len(bodies)}"
    return bodies[0]


def test_the_proxy_snippet_still_sets_timeouts_at_whatever_level_it_is_included_in() -> None:
    """The premise the rest of this section rests on.

    FAILS IF: somebody deletes the three timeout lines from `calevate-proxy.conf`. That is
    a legitimate change — it is the other fix for this defect — but it makes the
    restatements below load-bearing in a different way, so the pair should be re-read
    together rather than one of them quietly becoming decoration.
    """
    found = dict(_TIMEOUT.findall(SNIPPET.read_text(encoding="utf-8")))
    assert set(found) == set(_TIMEOUT_NAMES), (
        "calevate-proxy.conf no longer sets all three proxy timeouts; the hooks vhost's "
        f"server-scope values may now be effective on their own. Found: {sorted(found)}"
    )


@pytest.mark.parametrize("directive", _TIMEOUT_NAMES)
def test_the_hooks_catch_all_restates_every_timeout_after_the_include(directive: str) -> None:
    """The fix, stated as the property rather than as the diff.

    FAILS IF: any of the three restatements is removed from `location /`, or moved ABOVE
    the `include` line — either way the snippet's 5s/60s/60s becomes the effective value
    on the vhost whose entire ack budget is 500ms and whose vendor never retries (D-31).
    """
    body = _hooks_catch_all()
    include_at = body.find("include /etc/nginx/snippets/calevate-proxy.conf")
    assert include_at != -1, "the hooks catch-all no longer includes the proxy snippet"
    restated = [m for m in _TIMEOUT.finditer(body) if m.group(1) == directive]
    assert restated, (
        f"{directive} is not restated inside the hooks `location /`, so the value that "
        "actually applies is the snippet's browser-realm default, not the server block's"
    )
    assert restated[-1].start() > include_at, (
        f"{directive} is set BEFORE the include that overrides it — nginx takes the last "
        "occurrence at a level, so this restatement governs nothing"
    )


@pytest.mark.parametrize("directive", _TIMEOUT_NAMES)
def test_the_hooks_vhost_actually_runs_on_its_own_tighter_numbers(directive: str) -> None:
    """Not just "a value is restated" but "the restated value is the tight one".

    FAILS IF: someone reconciles the duplication by copying the snippet's 60s into the
    location, which would make the test above pass while restoring the exact defect.
    """
    # The FIRST occurrence in the block, which is the server-scope one: `dict(findall(...))`
    # would keep the LAST, i.e. the location's own value, and compare it to itself.
    server_value = next(
        m.group(2) for m in _TIMEOUT.finditer(_block_for("hooks.")) if m.group(1) == directive
    )
    location_value = [m for m in _TIMEOUT.finditer(_hooks_catch_all()) if m.group(1) == directive][
        -1
    ].group(2)
    assert location_value == server_value, (
        f"the hooks vhost declares {directive} {server_value} at server scope but runs on "
        f"{location_value}: the two must agree, because only the location one is effective"
    )
