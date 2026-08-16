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
