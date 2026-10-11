"""The edge's TLS vhosts: origin pulls, one HSTS header, and the apex redirects.

D-734: every TLS vhost includes the origin-pull snippet through one switch, which defaults
OFF so a deploy cannot require a client certificate before Cloudflare sends one.
D-734: a proxied response carries exactly one `Strict-Transport-Security`, the edge's.
D-732: signup, invitation acceptance and the OAuth callbacks are sent from the apex to
`app.`, which is the only origin the API credentials for them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "nginx"
SITE = (INFRA / "calevate.conf.template").read_text(encoding="utf-8")
SNIPPETS = INFRA / "snippets"
DEPLOY = (ROOT / "scripts" / "vps-deploy.sh").read_text(encoding="utf-8")

INCLUDE = "include /etc/nginx/snippets/calevate-origin-pull-${CF_ORIGIN_PULL}.conf;"


def _server_blocks(text: str) -> list[str]:
    """Each top-level `server { ... }` block, by brace depth."""
    blocks: list[str] = []
    for match in re.finditer(r"^server \{", text, re.MULTILINE):
        depth, index = 0, match.start()
        for index in range(match.start(), len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    break
        blocks.append(text[match.start() : index + 1])
    return blocks


def _uncommented(block: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in block.splitlines())


def test_every_tls_vhost_includes_the_origin_pull_switch() -> None:
    tls = [b for b in _server_blocks(SITE) if "listen 443 ssl" in _uncommented(b)]
    assert len(tls) >= 6, f"found {len(tls)} TLS vhosts; discovery is broken"
    missing = [
        re.search(r"server_name ([^;]+);", b).group(1)  # type: ignore[union-attr]
        for b in tls
        if INCLUDE not in _uncommented(b)
    ]
    assert not missing, f"these TLS vhosts do not include the origin-pull snippet: {missing}"


def test_no_plain_http_vhost_asks_for_a_client_certificate() -> None:
    """Port 80 carries the ACME http-01 challenge; a client-cert demand there is meaningless
    and the include must not appear in a block that is not TLS."""
    plain = [b for b in _server_blocks(SITE) if "listen 443" not in _uncommented(b)]
    assert plain, "no port-80 block found; discovery is broken"
    assert all(INCLUDE not in _uncommented(b) for b in plain)


@pytest.mark.parametrize(
    ("state", "verify"),
    [("off", None), ("optional", "optional"), ("on", "on")],
)
def test_each_switch_state_has_a_snippet_saying_what_it_does(
    state: str, verify: str | None
) -> None:
    body = _uncommented((SNIPPETS / f"calevate-origin-pull-{state}.conf").read_text("utf-8"))
    found = re.findall(r"ssl_verify_client\s+(\w+);", body)
    if verify is None:
        assert not found and "ssl_client_certificate" not in body
    else:
        assert found == [verify]
        assert "ssl_client_certificate /etc/nginx/certs/calevate-origin-pull-ca.pem;" in body


def test_the_deploy_renders_the_switch_and_defaults_it_off() -> None:
    assert ': "${CF_ORIGIN_PULL:=off}"' in DEPLOY
    subst = re.search(r"local subst='([^']+)'", DEPLOY)
    assert subst is not None and "${CF_ORIGIN_PULL}" in subst.group(1)
    assert "off|optional|on)" in DEPLOY


def test_a_proxied_response_carries_one_hsts_header_the_edges() -> None:
    proxy = _uncommented((SNIPPETS / "calevate-proxy.conf").read_text("utf-8"))
    headers = _uncommented((SNIPPETS / "calevate-headers.conf").read_text("utf-8"))
    for name in ("Strict-Transport-Security", "X-Content-Type-Options", "X-Frame-Options"):
        assert f"proxy_hide_header {name};" in proxy
        assert len(re.findall(rf"add_header {name} ", headers)) == 1


@pytest.mark.parametrize(
    "path",
    ["/signup", "/invite", "/auth/accept-invitation", "/auth/google/callback", "/oauth/callback"],
)
def test_the_apex_sends_client_only_pages_to_app(path: str) -> None:
    (apex,) = [
        b
        for b in _server_blocks(SITE)
        if re.search(r"server_name \$\{ROOT_DOMAIN\};", b) and "listen 443" in b
    ]
    assert f"location ^~ {path}" in apex and re.search(
        rf"location \^~ {re.escape(path)}\s+\{{ return 301 https://app\.\$\{{ROOT_DOMAIN\}}"
        r"\$request_uri; \}",
        apex,
    ), f"{path} is not redirected to app. on the apex"
