"""The certless-default_server fix must not eat the ACME challenge that issues its neighbour.

DEPLOYMENT §9.5a breaks a genuine deadlock: `certbot certonly --webroot` needs nginx to be
serving `/.well-known/acme-challenge/`, that location lives in `calevate.conf`, and every
TLS block in that file references `${TLS_LIVE_DIR}/fullchain.pem` — a file certbot has not
written yet. So `nginx -t` fails on the config that would let certbot obtain the
certificate. The documented escape is to load `000-default.conf` ALONE (its certificate is
the Cloudflare Origin CA one, which needs no ACME) and issue against it.

Which makes this block the only port-80 listener on the box during issuance, and therefore
the one that must answer the challenge for all four names.

**It did not, and the deploy would have failed at the one step that has no fallback.**
`return 444` was written at SERVER scope, where ngx_http_rewrite_module executes it in the
server rewrite phase — before location selection — so it fired for every request, challenge
included. `nginx -t` passes on that config; the symptom is certbot reporting an empty
response from a host that is plainly up.

The property under test is not "these lines exist". It is: **a request under
`/.well-known/acme-challenge/` on the default_server reaches the webroot, and everything
else still gets 444** — which a later edit could undo by hoisting the `return` back to
server scope just as easily as by deleting the location.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "infra" / "nginx" / "000-default.conf.template"


def _balanced(config: str, open_at: int) -> tuple[str, int]:
    """The body of the block whose `{` is at `open_at`, plus the index just past its `}`.

    Brace COUNTING rather than a regex, because the bodies here contain `${ACME_WEBROOT}` —
    and `[^}]*` stops inside that placeholder, which is how the first draft of this file
    reported the template as broken when it was the test that was.
    """
    depth, index = 0, open_at
    while index < len(config):
        if config[index] == "{":
            depth += 1
        elif config[index] == "}":
            depth -= 1
            if depth == 0:
                return config[open_at + 1 : index], index + 1
        index += 1
    raise AssertionError("unbalanced braces in 000-default.conf.template")


def _body() -> str:
    """The single `server { ... }` body, with comments stripped.

    Stripping matters: this file's comments QUOTE the directives they explain ("`return
    444` sat at SERVER scope"), so a scope check that reads them finds the defect it was
    written to detect in the prose describing its fix.
    """
    config = re.sub(r"#[^\n]*", "", TEMPLATE.read_text(encoding="utf-8"))
    starts = list(re.finditer(r"\bserver\s*\{", config))
    assert len(starts) == 1, f"expected exactly one server block, found {len(starts)}"
    return _balanced(config, starts[0].end() - 1)[0]


#: `location <modifier?> <prefix> {` — the header, not the body.
_LOCATION = re.compile(r"location\s+(?:(=|\^~|~\*?)\s+)?(\S+)\s*\{")


def _locations(body: str) -> list[tuple[str, str, str]]:
    """Every `(modifier, prefix, body)` in the server block, at any depth."""
    found: list[tuple[str, str, str]] = []
    for match in _LOCATION.finditer(body):
        inner, _ = _balanced(body, match.end() - 1)
        found.append((match.group(1) or "", match.group(2), inner))
    return found


def _server_scope(body: str) -> str:
    """The server body with every `location { ... }` cut out — i.e. server scope only."""
    out, cursor = [], 0
    for match in _LOCATION.finditer(body):
        if match.start() < cursor:
            continue  # a nested location already consumed with its parent
        out.append(body[cursor : match.start()])
        cursor = _balanced(body, match.end() - 1)[1]
    out.append(body[cursor:])
    return "".join(out)


def test_the_default_server_answers_the_acme_challenge() -> None:
    found = [loc for loc in _locations(_body()) if loc[1] == "/.well-known/acme-challenge/"]
    assert found, (
        "the default_server has no ACME challenge location. During §9.5a it is the ONLY "
        "port-80 listener loaded, so `certbot certonly --webroot` gets 444 and the first "
        "deploy stops at the certificate."
    )
    assert len(found) == 1, f"expected one ACME location, found {len(found)}"
    modifier, _, inner = found[0]
    assert modifier == "^~", (
        "the ACME location must use `^~`: nginx tries regex locations before plain prefix "
        f"ones, so a regex location added later would quietly win. Got {modifier!r}"
    )
    assert "root ${ACME_WEBROOT}" in inner, (
        "the ACME location must serve the webroot certbot writes into, and it must be the "
        f"substituted variable rather than a hard-coded path: {inner.strip()!r}"
    )


def test_the_444_is_in_a_location_and_not_at_server_scope() -> None:
    """The defect itself, stated directly.

    A server-scope `return` runs in the server rewrite phase, before nginx picks a
    location — so it beats the challenge handler above without appearing to.
    """
    assert not re.search(r"\breturn\s+444\b", _server_scope(_body())), (
        "`return 444` is at server scope again. ngx_http_rewrite_module runs it before "
        "location selection, so the ACME location above it is unreachable and certbot "
        "fails with an empty response on a config that passes `nginx -t`."
    )


def test_everything_that_is_not_a_challenge_still_gets_444() -> None:
    """The fix must not be "the default_server now serves things"."""
    body = _body()
    catch_all = [inner for _, prefix, inner in _locations(body) if prefix == "/"]
    assert len(catch_all) == 1, f"expected one catch-all, found {len(catch_all)}"
    assert re.search(r"\breturn\s+444\b", catch_all[0]), (
        "the catch-all no longer closes the connection, so a direct-to-IP scanner now "
        f"learns something from this block: {catch_all[0].strip()!r}"
    )
    assert "proxy_pass" not in body, "the default_server must never reach an upstream"


def test_it_still_carries_the_certificate_that_prevents_cloudflare_525() -> None:
    """The block's original reason for existing, which the ACME change must not displace."""
    body = _body()
    assert "listen 443 ssl default_server" in body
    assert "ssl_certificate     ${ORIGIN_CERT_PATH}" in body
    assert "ssl_certificate_key ${ORIGIN_KEY_PATH}" in body
