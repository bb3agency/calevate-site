"""Every server block nginx can answer from hides its version and bounds header reads.

`server_tokens` and `client_header_timeout` are server-scope settings, and the snippets that
carry them are included by the TLS vhosts only. The default_server and the port-80 block
answer too (a malformed request, a request with no SNI, every plain-HTTP redirect), so each
block is checked through what it includes as well as what it states itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.nginx_hooks_vhost_test import _server_blocks

INFRA = Path(__file__).resolve().parents[1] / "infra" / "nginx"
TEMPLATES = ("calevate.conf.template", "000-default.conf.template")
_INCLUDE = re.compile(r"^\s*include\s+/etc/nginx/snippets/([^;\s]+);", re.MULTILINE)
_COMMENT = re.compile(r"#.*$", re.MULTILINE)
#: A request-read timeout against slow HTTP (OWASP Denial of Service Cheat Sheet); 10s is the
#: ceiling this config holds itself to.
HEADER_TIMEOUT_CEILING_S = 10


def _uncommented(text: str) -> str:
    return _COMMENT.sub("", text)


def _effective_server_text(block: str) -> str:
    """The block's own server-scope text plus every snippet it includes, comments removed."""
    text = _uncommented(block)
    parts = [text]
    for name in _INCLUDE.findall(text):
        snippet = INFRA / "snippets" / name
        if snippet.exists():
            parts.append(_uncommented(snippet.read_text(encoding="utf-8")))
    return "\n".join(parts)


def _all_blocks() -> list[tuple[str, str]]:
    found = []
    for template in TEMPLATES:
        for block in _server_blocks((INFRA / template).read_text(encoding="utf-8")):
            names = re.search(r"server_name\s+([^;]+);", block)
            listen = re.search(r"listen\s+([^;\s]+)", block)
            name = names.group(1).split()[0] if names else "?"
            port = listen.group(1) if listen else "?"
            found.append((f"{template}:{name}:{port}", block))
    # The default_server, the port-80 redirect and the six TLS vhosts.
    assert len(found) == 8, [label for label, _ in found]
    return found


_BLOCKS = _all_blocks()


@pytest.mark.parametrize(("label", "block"), _BLOCKS, ids=[label for label, _ in _BLOCKS])
def test_every_server_block_hides_the_nginx_version(label: str, block: str) -> None:
    text = _effective_server_text(block)
    assert re.search(r"^\s*server_tokens\s+off;", text, re.MULTILINE), (
        f"{label} can answer with nginx's own error page or redirect and does not set "
        "`server_tokens off`, so that response names the nginx version"
    )


@pytest.mark.parametrize(("label", "block"), _BLOCKS, ids=[label for label, _ in _BLOCKS])
def test_every_server_block_bounds_how_long_headers_may_take(label: str, block: str) -> None:
    text = _effective_server_text(block)
    found = re.findall(r"^\s*client_header_timeout\s+(\d+)s;", text, re.MULTILINE)
    assert len(found) == 1, (
        f"{label} states client_header_timeout {len(found)} times (with its snippets); "
        "none leaves nginx's 60s, two at one level is a config nginx refuses"
    )
    assert int(found[0]) <= HEADER_TIMEOUT_CEILING_S, (
        f"{label} waits {found[0]}s for request headers; a slow-header client holds a "
        f"connection that long, so the ceiling is {HEADER_TIMEOUT_CEILING_S}s"
    )
