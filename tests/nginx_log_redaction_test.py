"""Credentials in a URL never reach `/var/log/nginx/access.log`.

`nginx_config_parses_test` proves the config loads; this proves what it LOGS. The map's
regexes are read out of the template and run (PCRE's `(?<name>` spelled as Python's
`(?P<name>`), so a renamed parameter or a vhost logging with `combined` goes red here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[1] / "infra" / "nginx"
LOG_FORMAT = (INFRA / "00-log-format.conf.template").read_text(encoding="utf-8")
VHOSTS = (INFRA / "calevate.conf.template").read_text(encoding="utf-8")


def _map_arms(variable: str) -> list[tuple[re.Pattern[str], str]]:
    block = re.search(r"map \S+ \$" + variable + r" \{(.*?)\n\}", LOG_FORMAT, re.S)
    assert block, f"no map for ${variable}"
    arms = []
    for regex, replacement in re.findall(r'"~(.+?)"\s+"(.+?)";', block.group(1)):
        arms.append((re.compile(regex.replace("(?<", "(?P<")), replacement))
    return arms


def _logged(variable: str, value: str) -> str:
    for pattern, replacement in _map_arms(variable):
        found = pattern.search(value)
        if found:
            groups = found.groupdict()
            return re.sub(r"\$(\w+)", lambda m, g=groups: g[m.group(1)], replacement)
    return value


@pytest.mark.parametrize(
    "uri",
    [
        "/oauth/callback/google_calendar?code=4/0AbCdSECRET&state=eyJhbGciOi.SECRET",
        "/oauth/callback/zoho_crm?state=eyJSECRET&code=1000.SECRET&accounts-server=x",
        "/auth/google/callback?code=SECRET&state=SECRET&scope=email",
        "/v1/ingest/meta/0190-abc?hub.mode=subscribe&hub.verify_token=SECRET&hub.challenge=1",
        "/auth/reset-password?token=SECRET",
        "/hooks/v1/engine/x?callback_key=SECRET",
    ],
)
def test_a_credential_in_the_query_is_not_logged(uri: str) -> None:
    logged = _logged("calevate_logged_uri", uri)
    assert "SECRET" not in logged
    assert logged.startswith(uri.split("?", 1)[0] + "?")


def test_an_oauth_return_page_does_not_leak_through_the_referer() -> None:
    referer = "https://app.calevate.tech/oauth/callback/hubspot?code=SECRET&state=SECRET"
    assert "SECRET" not in _logged("calevate_logged_referer", referer)


def test_an_honest_query_is_logged_unchanged() -> None:
    assert _logged("calevate_logged_uri", "/v1/calls?window=30d") == "/v1/calls?window=30d"


def test_every_tls_vhost_logs_with_the_redacted_format() -> None:
    """A server block without its own `access_log` inherits the base config's `combined`,
    which logs `$request` whole — the gap the `api.` vhost had."""
    blocks = re.split(r"\nserver \{", VHOSTS)[1:]
    missing = []
    for block in blocks:
        if "listen 443" not in block:
            continue
        name = re.search(r"server_name ([^;]+);", block)
        if "access_log /var/log/nginx/access.log calevate_redacted;" not in block:
            missing.append(name.group(1) if name else "<unnamed>")
    assert not missing, f"TLS vhosts logging without redaction: {missing}"
